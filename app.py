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

# --- MOTORE PROCEDURALE CON KEYFRAMES ---
def apply_procedural_slit_scan(get_frame, t, duration, start_strand, end_strand, mode):
    """Applica lo Slit-Scan interpolando lo spessore tra inizio e fine video."""
    frame = get_frame(t).copy()
    h, w, _ = frame.shape
    progress = t / duration
    
    # Interpolazione lineare dello spessore delle strisce (Keyframe)
    current_strand = start_strand + (end_strand - start_strand) * progress
    if current_strand < 1: current_strand = 1 # Sicurezza
    
    # Magnetismo: convergenza condizionale verso la fine
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
                chaos = np.sin(np.pi * progress)
                offset = int(random.uniform(-w, w) * chaos)
                frame[current_y:next_y, :] = np.roll(frame[current_y:next_y, :], offset, axis=1)
            current_y = next_y
    else:
        current_x = 0
        while current_x < w:
            strand_w = int(random.uniform(current_strand * 0.5, current_strand * 2))
            next_x = min(current_x + strand_w, w)
            if random.random() > magnet_prob:
                chaos = np.sin(np.pi * progress)
                offset = int(random.uniform(-h, h) * chaos)
                frame[:, current_x:next_x] = np.roll(frame[:, current_x:next_x], offset, axis=0)
            current_x = next_x
            
    return frame

# --- LOGICA DI MONTAGGIO PESATA ---
class KeyframeShuffler:
    def __init__(self):
        self.segments = {i: [] for i in range(4)}

    def add_video_source(self, v_id, path, min_d, max_d):
        with VideoFileClip(path) as clip:
            dur = clip.duration
            curr = 0
            while curr < dur:
                s_dur = random.uniform(min_d, max_d)
                end = min(curr + s_dur, dur)
                self.segments[v_id].append((curr, end))
                curr = end

    def generate_weighted_mix(self, video_paths, weights, duration, fps, strand_keyframes, mode, progress_bar):
        clips = []
        curr_t = 0
        video_objects = {i: VideoFileClip(path) for i, path in video_paths.items()}
        target_size = video_objects[next(iter(video_objects))].size

        # Creazione Timeline passo dopo passo
        while curr_t < duration:
            progress = curr_t / duration
            
            # Calcolo pesi correnti (Keyframe Probabilità)
            current_weights = []
            for i in range(len(video_paths)):
                w_start, w_end = weights[i]
                current_weights.append(w_start + (w_end - w_start) * progress)
            
            # Scelta del video in base ai pesi (Dado pesato)
            v_index = random.choices(list(video_paths.keys()), weights=current_weights, k=1)[0]
            
            # Pesca un segmento random dal video scelto
            seg = random.choice(self.segments[v_index])
            clip = video_objects[v_index].subclip(seg[0], seg[1]).resize(newsize=target_size).set_fps(fps)
            clips.append(clip)
            curr_t += clip.duration
            
            # Aggiorna Barra di Navigazione (Fase 1: Assemblaggio)
            perc = min(curr_t / duration, 1.0)
            progress_bar.progress(perc / 2, text=f"Assemblaggio segmenti: {int(perc*50)}%")

        final = concatenate_videoclips(clips, method="chain")
        
        # Applicazione Effetto Procedurale
        final = final.fl(lambda gf, t: apply_procedural_slit_scan(
            gf, t, final.duration, strand_keyframes[0], strand_keyframes[1], mode
        ))

        return final, video_objects

# --- INTERFACCIA STREAMLIT ---
def main():
    st.set_page_config(page_title="VideoDecomposer AI", layout="wide")
    st.title("🧪 VideoDecomposer: Keyframe & Procedural Engine")

    # Sidebar per caricamento
    with st.sidebar:
        st.header("📁 Sorgenti Video")
        files = [st.file_uploader(f"Video {i+1}", type=["mp4","mov"]) for i in range(4)]
    
    # Parametri in Main Page
    c1, c2, c3 = st.columns(3)
    
    video_weights = {}
    with c1:
        st.subheader("📊 Keyframes Video (%)")
        for i in range(4):
            if files[i]:
                st.write(f"**Video {i+1}: {files[i].name}**")
                s, e = st.columns(2)
                w_start = s.number_input(f"Start %", 0, 100, 100 if i==0 else 0, key=f"ws{i}")
                w_end = e.number_input(f"End %", 0, 100, 0 if i==0 else 100, key=f"we{i}")
                video_weights[i] = (w_start, w_end)

    with c2:
        st.subheader("🌀 Keyframes Effetto")
        st_strand = st.slider("Spessore Inizio (px)", 1, 200, 10)
        en_strand = st.slider("Spessore Fine (px)", 1, 200, 80)
        direzione = st.selectbox("Direzione", ["Orizzontale", "Verticale", "Mix"])
        ritmo = st.slider("Taglio (sec)", 0.1, 2.0, (0.2, 0.5))

    with c3:
        st.subheader("⚙️ Output")
        final_d = st.number_input("Durata Totale (sec)", 5, 120, 20)
        fps_out = st.selectbox("FPS", [24, 30])
        go = st.button("🚀 GENERA RENDERING", use_container_width=True)

    if go:
        valid_paths = {}
        for i, f in enumerate(files):
            if f:
                tfile = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4')
                tfile.write(f.read())
                valid_paths[i] = tfile.name

        if not valid_paths:
            st.error("Carica almeno un video!")
            return

        # BARRA DI NAVIGAZIONE
        p_bar = st.progress(0, text="Inizializzazione...")
        
        try:
            shuffler = KeyframeShuffler()
            for i, p in valid_paths.items():
                shuffler.add_video_source(i, p, ritmo[0], ritmo[1])
            
            final_clip, v_objs = shuffler.generate_weighted_mix(
                valid_paths, video_weights, final_d, fps_out, (st_strand, en_strand), direzione, p_bar
            )
            
            out_p = os.path.join(tempfile.gettempdir(), "render.mp4")
            
            # Fase 2: Rendering effettivo
            p_bar.progress(0.6, text="Rendering Pixel & Compressione (Fase Finale)...")
            final_clip.write_videofile(out_p, codec="libx264", audio_codec="aac", preset="ultrafast", logger=None)
            
            p_bar.progress(1.0, text="✅ Rendering Completato!")
            st.video(out_p)
            with open(out_p, "rb") as f:
                st.download_button("📥 Scarica Video", f, "procedural_mix.mp4")

            # Cleanup
            for v in v_objs.values(): v.close()

        except Exception as e:
            st.error(f"Errore: {e}")

if __name__ == "__main__":
    main()
