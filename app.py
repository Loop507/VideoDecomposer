import streamlit as st
import os, random, tempfile, cv2, time
import numpy as np

# --- 1. IMPORTAZIONE CORRETTA PER MOVIEPY 2.2.1 (FIX LOGS) ---
# Non usiamo più moviepy.editor perché i tuoi log dicono che non esiste
from moviepy.video.io.VideoFileClip import VideoFileClip
from moviepy.video.VideoClip import VideoClip
from moviepy.audio.AudioClip import AudioClip
from moviepy.video.compositing.concatenate import concatenate_videoclips

# --- 2. STRATEGIA FILL SCREEN ORIGINALE (DA APP.PY) ---
def apply_fill_strategy(clip, target_w, target_h):
    def frame_transform(get_frame, t):
        frame = get_frame(t)
        h, w, _ = frame.shape
        # Calcolo scala per coprire tutto il formato scelto
        scale = max(target_w / w, target_h / h)
        nw, nh = int(w * scale), int(h * scale)
        img_res = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
        # Ritaglio centrale esatto
        sy, sx = (img_res.shape[0] - target_h) // 2, (img_res.shape[1] - target_w) // 2
        return img_res[sy:sy+target_h, sx:sx+target_w]
    return clip.transform(frame_transform)

# --- 3. LOGICA SCOMPOSIZIONE (DA APP 222.PY) ---
def apply_strips_filter(segment, clips_dict, p, start_in_original):
    tw, th = p['size']
    dim = th if p['orient'] == "Orizzontale" else tw
    
    # Creazione griglia strisce
    grid, curr = [], 0
    while curr < dim:
        thick = random.randint(p['thick'][0], p['thick'][1])
        grid.append((curr, int(min(curr + thick, dim))))
        curr = int(min(curr + thick, dim))

    def make_glitch_frame(get_frame, t):
        out = np.zeros((th, tw, 3), dtype=np.uint8)
        
        # FIX LOGS: "Total of weights must be greater than zero"
        # Assegniamo un valore minimo (0.1) se lo slider è a zero
        weights_raw = [p['d1'], p['d2'], 10, 5]
        valid_ids = list(clips_dict.keys())
        active_weights = [max(0.1, float(weights_raw[i])) for i in valid_ids]

        # Campionamento frame dai vari Deck
        frames = {}
        for i, c in clips_dict.items():
            f = c.get_frame((start_in_original + t) % c.duration)
            # Fill veloce per le singole strisce
            fh, fw, _ = f.shape
            f_scale = max(tw/fw, th/fh)
            f_res = cv2.resize(f, (int(fw*f_scale), int(fh*f_scale)))
            fsy, fsx = (f_res.shape[0]-th)//2, (f_res.shape[1]-tw)//2
            frames[i] = f_res[fsy:fsy+th, fsx:fsx+tw]

        for (s, e) in grid:
            chosen = random.choices(valid_ids, weights=active_weights)[0]
            if p['orient'] == "Orizzontale":
                out[s:e, :] = frames[chosen][s:e, :]
            else:
                out[:, s:e] = frames[chosen][:, s:e]
        return out

    return segment.transform(make_glitch_frame)

# --- 4. MOTORE DI RENDERING (STRUTTURA APP.PY) ---
def process_video(video_paths, p):
    clips = {i: VideoFileClip(path) for i, path in video_paths.items()}
    tw, th = p['size']
    final_segments = []
    current_time = 0
    
    while current_time < p['durata']:
        # Ritmo
        r = p['ritmo']
        seg_dur = random.uniform(r[0], r[1]) if isinstance(r, (list, tuple)) else r
        seg_dur = min(seg_dur, p['durata'] - current_time)

        # Scelta Deck dominante (Pesi sicuri)
        weights_raw = [p['d1'], p['d2'], 10, 5]
        valid_ids = list(clips.keys())
        active_weights = [max(0.1, float(weights_raw[i])) for i in valid_ids]
        main_id = random.choices(valid_ids, weights=active_weights)[0]

        # Subclip + Strategia Fill di app.py
        start_pos = random.uniform(0, max(0, clips[main_id].duration - seg_dur))
        seg = clips[main_id].subclipped(start_pos, start_pos + seg_dur)
        seg = apply_fill_strategy(seg, tw, th)

        # Se le strisce sono attive, le applichiamo sopra
        if p['usa_strisce']:
            seg = apply_strips_filter(seg, clips, p, start_pos)

        final_segments.append(seg)
        current_time += seg_dur

    # Concatenazione finale (Metodo solido per l'audio)
    final_video = concatenate_videoclips(final_segments, method="compose")
    
    out_p = os.path.join(tempfile.gettempdir(), f"output_{int(time.time())}.mp4")
    final_video.write_videofile(out_p, fps=24, codec="libx264", audio_codec="aac", logger=None)
    
    for c in clips.values(): c.close()
    return out_p

# --- 5. INTERFACCIA ---
def main():
    st.set_page_config(layout="wide", page_title="Video Decomposer Stabile")
    st.title("📟 VIDEO DECOMPOSER - STRUTTURA SOLIDA")
    
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Configurazione")
        usa_strisce = st.toggle("ATTIVA SCOMPOSIZIONE (STRISCE)", value=True)
        v_files = [st.file_uploader(f"Video Deck {i+1}", type=["mp4","mov"]) for i in range(4)]
        ritmo = st.slider("Ritmo di Taglio (sec)", 0.05, 1.0, (0.1, 0.3))
        aspect = st.selectbox("Formato Output (FILL)", ["16:9", "1:1", "9:16"])
        
    with col2:
        st.subheader("Pesi e Strisce")
        d1 = st.slider("Peso Deck 1", 0, 100, 100)
        d2 = st.slider("Peso Deck 2", 0, 100, 50)
        durata = st.number_input("Durata Totale (sec)", 1, 60, 10)
        
        if usa_strisce:
            thick = st.slider("Spessore Strisce", 1, 300, (10, 40))
            orient = st.radio("Direzione", ["Orizzontale", "Verticale"])
        else:
            thick, orient = (10, 40), "Orizzontale"

    if st.button("🚀 GENERA VIDEO"):
        paths = {}
        for i, f in enumerate(v_files):
            if f:
                t = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
                t.write(f.read())
                paths[i] = t.name
        
        if not paths:
            st.error("Devi caricare almeno un video!")
            return
        
        res_map = {"16:9": (1280, 720), "1:1": (720, 720), "9:16": (405, 720)}
        params = {
            'durata': durata, 'ritmo': ritmo, 'size': res_map[aspect],
            'd1': d1, 'd2': d2, 'thick': thick, 'orient': orient, 'usa_strisce': usa_strisce
        }
        
        with st.spinner("Rendering in corso..."):
            try:
                res = process_video(paths, params)
                st.video(res)
                st.download_button("Scarica", open(res, "rb"), "video_output.mp4")
            except Exception as e:
                st.error(f"Errore tecnico: {e}")

if __name__ == "__main__":
    main()
