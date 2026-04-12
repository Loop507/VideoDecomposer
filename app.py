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
def apply_slit_scan(get_frame, t, duration, val_a, val_b, mode_type, scan_mode):
    frame = get_frame(t).copy()
    h, w, _ = frame.shape
    progress = t / duration
    
    # Scelta spessore in base alla modalità
    if mode_type == "Keyframe (Inizio -> Fine)":
        current_strand = val_a + (val_b - val_a) * progress
    else: # Random
        current_strand = random.uniform(val_a, val_b)
    
    current_strand = max(1, current_strand)
    magnet_prob = 0 if progress < 0.7 else ((progress - 0.7) / 0.3) ** 2
    
    c_mode = scan_mode
    if scan_mode == "Mix": c_mode = random.choice(["Orizzontale", "Verticale"])

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
class SimpleEngine:
    def __init__(self):
        self.video_clips = {}

    def load_sources(self, paths):
        for i, p in paths.items():
            self.video_clips[i] = VideoFileClip(p)
        return self.video_clips[next(iter(self.video_clips))].size

    def generate(self, weights, r_a, r_b, r_mode, duration, fps, s_a, s_b, s_mode, scan_dir, p_bar, use_scan):
        curr_t = 0
        clips = []
        target_size = self.video_clips[next(iter(self.video_clips))].size

        while curr_t < duration:
            progress = curr_t / duration
            
            # Calcolo Ritmo
            if r_mode == "Keyframe (Inizio -> Fine)":
                seg_dur = r_a + (r_b - r_a) * progress
            else:
                seg_dur = random.uniform(r_a, r_b)
            
            # Calcolo Pesi Video
            w_list = [weights[i][0] + (weights[i][1] - weights[i][0]) * progress for i in range(len(self.video_clips))]
            if sum(w_list) == 0: w_list = [1] * len(w_list)
            
            v_idx = random.choices(list(self.video_clips.keys()), weights=w_list, k=1)[0]
            source = self.video_clips[v_idx]
            
            start_p = random.uniform(0, max(0, source.duration - seg_dur))
            clip = source.subclip(start_p, start_p + seg_dur).resize(newsize=target_size).set_fps(fps)
            clips.append(clip)
            curr_t += seg_dur
            p_bar.progress(min(curr_t / duration * 0.4, 0.4), text="Composizione in corso...")

        final = concatenate_videoclips(clips, method="chain").set_duration(duration)
        if use_scan:
            final = final.fl(lambda gf, t: apply_slit_scan(gf, t, final.duration, s_a, s_b, s_mode, scan_dir))
        return final

# --- INTERFACCIA ---
def main():
    st.set_page_config(page_title="VideoDecomposer Clean", layout="wide")
    st.title("🎬 VideoDecomposer: Regia Semplificata")

    with st.sidebar:
        st.header("📁 Carica Video")
        files = [st.file_uploader(f"Video {i+1}", type=["mp4","mov"]) for i in range(4)]
    
    c1, c2, c3 = st.columns(3)
    
    weights = {}
    with c1:
        st.subheader("📊 Mix Video")
        for i in range(4):
            if files[i]:
                st.write(f"**Video {i+1}**")
                s, e = st.columns(2)
                ws = s.slider("Inizio %", 0, 100, 100 if i==0 else 0, key=f"ws{i}")
                we = e.slider("Fine %", 0, 100, 0 if i==0 else 100, key=f"we{i}")
                weights[i] = (ws, we)

    with c2:
        st.subheader("⏱️ Ritmo (Taglio)")
        r_mode = st.radio("Modalità Ritmo", ["Keyframe (Inizio -> Fine)", "Random (Range)"])
        r_col1, r_col2 = st.columns(2)
        r_a = r_col1.number_input("Inizio / Min (s)", 0.05, 5.0, 0.2)
        r_b = r_col2.number_input("Fine / Max (s)", 0.05, 5.0, 1.0)
        
        st.markdown("---")
        st.subheader("🌀 Slit-Scan (Strisce)")
        use_scan = st.checkbox("ATTIVA EFFETTO", value=True)
        s_mode = st.radio("Modalità Strisce", ["Keyframe (Inizio -> Fine)", "Random (Range)"], disabled=not use_scan)
        s_col1, s_col2 = st.columns(2)
        s_a = s_col1.number_input("Inizio / Min (px)", 1, 300, 10, disabled=not use_scan)
        s_b = s_col2.number_input("Fine / Max (px)", 1, 300, 80, disabled=not use_scan)
        scan_dir = st.selectbox("Direzione", ["Orizzontale", "Verticale", "Mix"], disabled=not use_scan)

    with c3:
        st.subheader("⚙️ Output")
        durata = st.number_input("Durata Totale (s)", 5, 300, 20)
        fps = st.selectbox("FPS", [24, 30])
        if st.button("🚀 GENERA VIDEO", use_container_width=True):
            paths = {i: tempfile.NamedTemporaryFile(delete=False, suffix='.mp4').name for i, f in enumerate(files) if f}
            for i, f in enumerate(files):
                if f:
                    with open(paths[i], "wb") as tf: tf.write(f.read())
            
            if not paths: st.error("Carica i video!"); return
            
            p_bar = st.progress(0, text="Avvio...")
            try:
                engine = SimpleEngine()
                engine.load_sources(paths)
                final = engine.generate(weights, r_a, r_b, r_mode, durata, fps, s_a, s_b, s_mode, scan_dir, p_bar, use_scan)
                out = os.path.join(tempfile.gettempdir(), "final.mp4")
                final.write_videofile(out, codec="libx264", audio_codec="aac", preset="ultrafast", logger=None)
                st.success("✅ Completato!"); st.video(out)
            except Exception as e: st.error(f"Errore: {e}")

if __name__ == "__main__":
    main()
