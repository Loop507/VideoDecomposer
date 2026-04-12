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
def apply_procedural_slit_scan(get_frame, t, duration, s_min_start, s_max_start, s_min_end, s_max_end, mode):
    frame = get_frame(t).copy()
    h, w, _ = frame.shape
    progress = t / duration
    
    # Calcolo del range dinamico al tempo T
    current_min = s_min_start + (s_min_end - s_min_start) * progress
    current_max = s_max_start + (s_max_end - s_max_start) * progress
    
    # Scelta spessore random nel range calcolato
    current_strand = random.uniform(current_min, current_max)
    current_strand = max(1, current_strand)
    
    # Magnetismo
    magnet_prob = 0 if progress < 0.7 else ((progress - 0.7) / 0.3) ** 2
    
    c_mode = mode
    if mode == "Mix": c_mode = random.choice(["Orizzontale", "Verticale"])

    if c_mode == "Orizzontale":
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

# --- LOGICA DI MONTAGGIO ---
class KeyframeEngine:
    def __init__(self):
        self.video_clips = {}

    def load_sources(self, paths):
        for i, p in paths.items():
            self.video_clips[i] = VideoFileClip(p)
        return self.video_clips[next(iter(self.video_clips))].size

    def generate(self, weights, r_params, duration, fps, s_params, mode, p_bar, use_scan):
        curr_t = 0
        clips = []
        target_size = self.video_clips[next(iter(self.video_clips))].size

        while curr_t < duration:
            progress = curr_t / duration
            
            # RITMO: Calcolo range dinamico e scelta valore
            r_min = r_params[0] + (r_params[2] - r_params[0]) * progress
            r_max = r_params[1] + (r_params[3] - r_params[1]) * progress
            seg_dur = random.uniform(r_min, r_max)
            
            # PESI VIDEO
            w_list = [weights[i][0] + (weights[i][1] - weights[i][0]) * progress for i in range(len(self.video_clips))]
            if sum(w_list) == 0: w_list = [1] * len(w_list)
            
            v_idx = random.choices(list(self.video_clips.keys()), weights=w_list, k=1)[0]
            source = self.video_clips[v_idx]
            
            start_p = random.uniform(0, max(0, source.duration - seg_dur))
            clip = source.subclip(start_p, start_p + seg_dur).resize(newsize=target_size).set_fps(fps)
            clips.append(clip)
            curr_t += seg_dur
            p_bar.progress(min(curr_t / duration * 0.4, 0.4), text=f"Montaggio: {int(curr_t)}s")

        final = concatenate_videoclips(clips, method="chain").set_duration(duration)
        if use_scan:
            final = final.fl(lambda gf, t: apply_procedural_slit_scan(gf, t, final.duration, *s_params, mode))
        return final

# --- INTERFACCIA ---
def main():
    st.set_page_config(page_title="VideoDecomposer Pro", layout="wide")
    st.title("🎬 VideoDecomposer: Keyframe & Range Master")

    with st.sidebar:
        st.header("📁 Video")
        files = [st.file_uploader(f"Video {i+1}", type=["mp4","mov"]) for i in range(4)]
    
    c1, c2, c3 = st.columns(3)
    
    weights = {}
    with c1:
        st.subheader("📊 Presenza Video (%)")
        for i in range(4):
            if files[i]:
                st.write(f"Video {i+1}")
                s, e = st.columns(2)
                ws = s.number_input("Inizio", 0, 100, 100 if i==0 else 0, key=f"ws{i}")
                we = e.number_input("Fine", 0, 100, 0 if i==0 else 100, key=f"we{i}")
                weights[i] = (ws, we)

    with c2:
        st.subheader("⏱️ Ritmo (Taglio)")
        st.caption("All'INIZIO il taglio sarà tra:")
        rs1, rs2 = st.columns(2)
        rs_min = rs1.number_input("Min (s)", 0.05, 2.0, 0.1, key="rsmin")
        rs_max = rs2.number_input("Max (s)", 0.05, 2.0, 0.3, key="rsmax")
        
        st.caption("Alla FINE il taglio sarà tra:")
        re1, re2 = st.columns(2)
        re_min = re1.number_input("Min (s) ", 0.05, 5.0, 1.0, key="remin")
        re_max = re2.number_input("Max (s) ", 0.05, 5.0, 1.5, key="remax")
        
        st.markdown("---")
        st.subheader("🌀 Slit-Scan")
        usa_effetto = st.checkbox("ATTIVA STRISCE", value=True)
        
        st.caption("Spessore INIZIO (Range):")
        ss1, ss2 = st.columns(2)
        ss_min = ss1.number_input("Min px", 1, 300, 5, disabled=not usa_effetto)
        ss_max = ss2.number_input("Max px", 1, 300, 15, disabled=not usa_effetto)
        
        st.caption("Spessore FINE (Range):")
        se1, se2 = st.columns(2)
        se_min = se1.number_input("Min px ", 1, 300, 50, disabled=not usa_effetto)
        se_max = se2.number_input("Max px ", 1, 300, 100, disabled=not usa_effetto)
        
        direzione = st.selectbox("Direzione", ["Orizzontale", "Verticale", "Mix"], disabled=not usa_effetto)

    with c3:
        st.subheader("⚙️ Output")
        durata = st.number_input("Durata Totale (s)", 5, 300, 20)
        fps = st.selectbox("FPS", [24, 30])
        if st.button("🚀 AVVIA RENDERING", use_container_width=True):
            paths = {i: tempfile.NamedTemporaryFile(delete=False, suffix='.mp4').name for i, f in enumerate(files) if f}
            for i, f in enumerate(files):
                if f:
                    with open(paths[i], "wb") as tf: tf.write(f.read())
            
            if not paths: st.error("Carica i video!"); return
            
            p_bar = st.progress(0, text="Avvio...")
            try:
                engine = KeyframeEngine()
                engine.load_sources(paths)
                r_p = (rs_min, rs_max, re_min, re_max)
                s_p = (ss_min, ss_max, se_min, se_max)
                
                final = engine.generate(weights, r_p, durata, fps, s_p, direzione, p_bar, usa_effetto)
                out = os.path.join(tempfile.gettempdir(), "render_final.mp4")
                p_bar.progress(0.6, text="Rendering Finale...")
                final.write_videofile(out, codec="libx264", audio_codec="aac", preset="ultrafast", logger=None)
                st.success("✅ Completato!"); st.video(out)
            except Exception as e: st.error(f"Errore: {e}")

if __name__ == "__main__":
    main()
