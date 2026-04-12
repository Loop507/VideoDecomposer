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

# --- MOTORE PROCEDURALE CON KEYFRAME + RANGE ---
def apply_procedural_slit_scan(get_frame, t, duration, s_min, s_max, e_min, e_max, mode):
    frame = get_frame(t).copy()
    h, w, _ = frame.shape
    progress = t / duration
    
    # Interpolazione dei limiti Min e Max
    current_min = s_min + (e_min - s_min) * progress
    current_max = s_max + (e_max - s_max) * progress
    
    # Scelta spessore random nel range calcolato per quel momento t
    current_strand = random.uniform(current_min, current_max)
    current_strand = max(1, current_strand)
    
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

# --- LOGICA DI MONTAGGIO AVANZATA ---
class UltimateKeyframeShuffler:
    def __init__(self):
        self.video_clips = {}

    def load_sources(self, paths):
        for i, p in paths.items():
            self.video_clips[i] = VideoFileClip(p)
        return self.video_clips[next(iter(self.video_clips))].size

    def generate_video(self, weights, r_params, duration, fps, s_params, mode, p_bar, use_slit_scan):
        curr_t = 0
        clips = []
        target_size = self.video_clips[next(iter(self.video_clips))].size
        
        # r_params = (rs_min, rs_max, re_min, re_max)
        # s_params = (ss_min, ss_max, se_min, se_max)

        while curr_t < duration:
            progress = curr_t / duration
            
            # Interpolazione dinamica del range di ritmo
            cur_r_min = r_params[0] + (r_params[2] - r_params[0]) * progress
            cur_r_max = r_params[1] + (r_params[3] - r_params[1]) * progress
            seg_dur = random.uniform(cur_r_min, cur_r_max)
            
            # Pesi Video
            w_list = [weights[i][0] + (weights[i][1] - weights[i][0]) * progress for i in range(len(self.video_clips))]
            if sum(w_list) == 0: w_list = [1] * len(w_list)
            
            v_idx = random.choices(list(self.video_clips.keys()), weights=w_list, k=1)[0]
            source = self.video_clips[v_idx]
            
            start_p = random.uniform(0, max(0, source.duration - seg_dur))
            clip = source.subclip(start_p, start_p + seg_dur).resize(newsize=target_size).set_fps(fps)
            clips.append(clip)
            curr_t += seg_dur
            
            p_bar.progress(min(curr_t / duration * 0.4, 0.4), text=f"Montaggio: {int(curr_t)}s / {duration}s")

        final = concatenate_videoclips(clips, method="chain").set_duration(duration)
        
        if use_slit_scan:
            final = final.fl(lambda gf, t: apply_procedural_slit_scan(
                gf, t, final.duration, s_params[0], s_params[1], s_params[2], s_params[3], mode
            ))
        
        return final

# --- INTERFACCIA STREAMLIT ---
def main():
    st.set_page_config(page_title="VideoDecomposer MASTER", layout="wide")
    st.title("🎬 VideoDecomposer: Ultimate Keyframe & Range Control")

    with st.sidebar:
        st.header("📁 Sorgenti Video")
        files = [st.file_uploader(f"Video {i+1}", type=["mp4","mov"]) for i in range(4)]
    
    c1, c2, c3 = st.columns(3)
    
    weights = {}
    with c1:
        st.subheader("📊 Pesi Video (Start % -> End %)")
        for i in range(4):
            if files[i]:
                st.write(f"Video {i+1}: {files[i].name[:15]}...")
                s, e = st.columns(2)
                ws = s.number_input("Inizio", 0, 100, 100 if i==0 else 0, key=f"ws{i}")
                we = e.number_input("Fine", 0, 100, 0 if i==0 else 100, key=f"we{i}")
                weights[i] = (ws, we)

    with c2:
        st.subheader("⏱️ Ritmo (Taglio)")
        st.write("Definisci il range randomico iniziale e finale")
        rs_col1, rs_col2 = st.columns(2)
        rs_min = rs_col1.number_input("Inizio Min (sec)", 0.05, 2.0, 0.1)
        rs_max = rs_col2.number_input("Inizio Max (sec)", 0.05, 2.0, 0.4)
        
        re_col1, re_col2 = st.columns(2)
        re_min = re_col1.number_input("Fine Min (sec)", 0.05, 5.0, 0.8)
        re_max = re_col2.number_input("Fine Max (sec)", 0.05, 5.0, 1.2)
        
        st.markdown("---")
        st.subheader("🌀 Slit-Scan")
        attiva_strisce = st.checkbox("ATTIVA EFFETTO STRISCE", value=True)
        
        ss_col1, ss_col2 = st.columns(2)
        ss_min = ss_col1.number_input("Spessore Inizio Min", 1, 300, 5, disabled=not attiva_strisce)
        ss_max = ss_col2.number_input("Spessore Inizio Max", 1, 300, 20, disabled=not attiva_strisce)
        
        se_col1, se_col2 = st.columns(2)
        se_min = se_col1.number_input("Spessore Fine Min", 1, 300, 50, disabled=not attiva_strisce)
        se_max = se_col2.number_input("Spessore Fine Max", 1, 300, 100, disabled=not attiva_strisce)
        
        direzione = st.selectbox("Direzione", ["Orizzontale", "Verticale", "Mix"], disabled=not attiva_strisce)

    with c3:
        st.subheader("⚙️ Esportazione")
        durata = st.number_input("Durata Totale (sec)", 5, 300, 20)
        fps = st.selectbox("FPS", [24, 30])
        btn = st.button("🚀 AVVIA RENDERING", use_container_width=True)

    if btn:
        paths = {i: tempfile.NamedTemporaryFile(delete=False, suffix='.mp4').name for i, f in enumerate(files) if f}
        for i, f in enumerate(files):
            if f:
                with open(paths[i], "wb") as tf: tf.write(f.read())

        if not paths:
            st.error("Carica almeno un video!"); return

        p_bar = st.progress(0, text="Inizializzazione...")
        try:
            engine = UltimateKeyframeShuffler()
            engine.load_sources(paths)
            
            r_params = (rs_min, rs_max, re_min, re_max)
            s_params = (ss_min, ss_max, se_min, se_max)
            
            final_v = engine.generate_video(weights, r_params, durata, fps, s_params, direzione, p_bar, attiva_strisce)
            
            out = os.path.join(tempfile.gettempdir(), "final_render_master.mp4")
            p_bar.progress(0.5, text="Rendering Pixel & Encoding...")
            final_v.write_videofile(out, codec="libx264", audio_codec="aac", preset="ultrafast", logger=None)
            
            p_bar.progress(1.0, text="✅ Video Pronto!")
            st.video(out)
            with open(out, "rb") as f: st.download_button("📥 Scarica", f, "procedural_master.mp4")
        except Exception as e: st.error(f"Errore: {e}")

if __name__ == "__main__":
    main()
