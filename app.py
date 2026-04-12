import streamlit as st
import os
import random
import tempfile
import numpy as np
from moviepy.editor import VideoFileClip, concatenate_videoclips
from PIL import Image

# --- PATCH COMPATIBILITÀ ---
if hasattr(Image, 'Resampling'):
    Image.ANTIALIAS = Image.Resampling.LANCZOS
else:
    Image.ANTIALIAS = Image.LANCZOS

# --- MOTORE PROCEDURALE (SLIT-SCAN) ---
def apply_procedural_slit_scan(get_frame, t, duration, start_strand, end_strand, mode):
    frame = get_frame(t).copy()
    h, w, _ = frame.shape
    progress = t / duration
    
    current_strand = start_strand + (end_strand - start_strand) * progress
    current_strand = max(1, current_strand)
    
    # Magnetismo (Convergenza verso il finale)
    magnet_prob = 0 if progress < 0.7 else ((progress - 0.7) / 0.3) ** 2
    
    current_mode = mode
    if mode == "Mix":
        current_mode = random.choice(["Orizzontale", "Verticale"])

    if current_mode == "Orizzontale":
        current_y = 0
        while current_y < h:
            strand_h = int(random.uniform(current_strand * 0.5, current_strand * 2))
            next_y = min(current_y + strand_h, h)
            if random.random() > magnet_prob:
                offset = int(random.uniform(-w, w) * np.sin(np.pi * progress))
                frame[current_y:next_y, :] = np.roll(frame[current_y:next_y, :], offset, axis=1)
            current_y = next_y
    else:
        current_x = 0
        while current_x < w:
            strand_w = int(random.uniform(current_strand * 0.5, current_strand * 2))
            next_x = min(current_x + strand_w, w)
            if random.random() > magnet_prob:
                offset = int(random.uniform(-h, h) * np.sin(np.pi * progress))
                frame[:, current_x:next_x] = np.roll(frame[:, current_x:next_x], offset, axis=0)
            current_x = next_x
            
    return frame

# --- LOGICA DI MONTAGGIO DINAMICO ---
class AdvancedKeyframeShuffler:
    def __init__(self):
        self.video_clips = {}

    def load_sources(self, paths):
        for i, p in paths.items():
            self.video_clips[i] = VideoFileClip(p)
        return self.video_clips[next(iter(self.video_clips))].size

    def generate_video(self, weights, ritmi, duration, fps, strand_kf, mode, p_bar, use_slit_scan):
        curr_t = 0
        clips = []
        target_size = self.video_clips[next(iter(self.video_clips))].size

        while curr_t < duration:
            progress = curr_t / duration
            
            # Keyframe Ritmo
            r_start, r_end = ritmi
            current_ritmo = r_start + (r_end - r_start) * progress
            seg_dur = random.uniform(current_ritmo * 0.7, current_ritmo * 1.3)
            
            # Keyframe Pesi Video
            w_list = []
            for i in range(len(self.video_clips)):
                ws, we = weights.get(i, (0, 0))
                w_list.append(ws + (we - ws) * progress)
            
            if sum(w_list) == 0: w_list = [1] * len(w_list)
            
            v_idx = random.choices(list(self.video_clips.keys()), weights=w_list, k=1)[0]
            source = self.video_clips[v_idx]
            
            start_p = random.uniform(0, max(0, source.duration - seg_dur))
            clip = source.subclip(start_p, start_p + seg_dur).resize(newsize=target_size).set_fps(fps)
            
            clips.append(clip)
            curr_t += seg_dur
            
            p_bar.progress(min(curr_t / duration * 0.4, 0.4), text=f"Assemblaggio: {int(curr_t)}s / {duration}s")

        final = concatenate_videoclips(clips, method="chain").set_duration(duration)
        
        # APPLICAZIONE EFFETTO SOLO SE IL SELECTOR È ATTIVO
        if use_slit_scan:
            final = final.fl(lambda gf, t: apply_procedural_slit_scan(
                gf, t, final.duration, strand_kf[0], strand_kf[1], mode
            ))
        
        return final

# --- INTERFACCIA ---
def main():
    st.set_page_config(page_title="VideoDecomposer PRO", layout="wide")
    st.title("🎬 VideoDecomposer: Regia e Pixel Engine")

    with st.sidebar:
        st.header("📁 Sorgenti")
        files = [st.file_uploader(f"Video {i+1}", type=["mp4","mov"]) for i in range(4)]
    
    c1, c2, c3 = st.columns(3)
    
    weights = {}
    with c1:
        st.subheader("📊 Keyframe Video")
        for i in range(4):
            if files[i]:
                st.write(f"Video {i+1}")
                s, e = st.columns(2)
                ws = s.number_input("Inizio %", 0, 100, 100 if i==0 else 0, key=f"ws{i}")
                we = e.number_input("Fine %", 0, 100, 0 if i==0 else 100, key=f"we{i}")
                weights[i] = (ws, we)

    with c2:
        st.subheader("⏱️ Keyframe Ritmo")
        r_start = st.slider("Ritmo Inizio (sec)", 0.1, 2.0, 0.2)
        r_end = st.slider("Ritmo Fine (sec)", 0.1, 2.0, 0.8)
        
        st.markdown("---")
        st.subheader("🌀 Configurazione Slit-Scan")
        # --- IL SELECTOR RICHIESTO ---
        attiva_strisce = st.checkbox("ATTIVA EFFETTO STRISCE", value=True)
        
        s_strand = st.slider("Spessore Inizio", 1, 150, 10, disabled=not attiva_strisce)
        e_strand = st.slider("Spessore Fine", 1, 150, 50, disabled=not attiva_strisce)
        direzione = st.selectbox("Direzione", ["Orizzontale", "Verticale", "Mix"], disabled=not attiva_strisce)

    with c3:
        st.subheader("⚙️ Output Finale")
        durata = st.number_input("Durata Totale (sec)", 5, 120, 20)
        fps = st.selectbox("FPS", [24, 30])
        btn = st.button("🚀 AVVIA RENDERING", use_container_width=True)

    if btn:
        paths = {}
        for i, f in enumerate(files):
            if f:
                tf = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4')
                tf.write(f.read())
                paths[i] = tf.name

        if not paths:
            st.error("Carica i video!")
            return

        p_bar = st.progress(0, text="Preparazione...")
        
        try:
            engine = AdvancedKeyframeShuffler()
            engine.load_sources(paths)
            
            # Passiamo lo stato del selector alla funzione di generazione
            final_v = engine.generate_video(
                weights, (r_start, r_end), durata, fps, (s_strand, e_strand), direzione, p_bar, attiva_strisce
            )
            
            out = os.path.join(tempfile.gettempdir(), "final_render.mp4")
            label = "Rendering Pixel & Encoding..." if attiva_strisce else "Esportazione Montaggio..."
            p_bar.progress(0.5, text=label)
            
            final_v.write_videofile(out, codec="libx264", audio_codec="aac", preset="ultrafast", logger=None)
            
            p_bar.progress(1.0, text="✅ Video Pronto!")
            st.video(out)
            with open(out, "rb") as f:
                st.download_button("📥 Scarica", f, "procedural_master.mp4")
                
        except Exception as e:
            st.error(f"Errore: {e}")

if __name__ == "__main__":
    main()
