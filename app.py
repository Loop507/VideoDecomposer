import streamlit as st
import os, random, tempfile, cv2, time
import numpy as np

# --- 1. IMPORTAZIONE MOVIEPY 2.2.1 ---
try:
    from moviepy.video.io.VideoFileClip import VideoFileClip
    from moviepy.video.VideoClip import VideoClip
    from moviepy.audio.AudioClip import AudioClip
    from moviepy.video.compositing.concatenate import concatenate_videoclips
except ImportError:
    from moviepy.editor import VideoFileClip, VideoClip, AudioClip, concatenate_videoclips

# --- 2. STRATEGIA FILL SCREEN (DA APP.PY ORIGINALE) ---
def apply_fill_strategy(clip, target_w, target_h):
    """
    Usa la logica di trasformazione frame-per-frame di app.py 
    per assicurare che l'output sia sempre Full Screen.
    """
    def frame_transform(get_frame, t):
        frame = get_frame(t)
        h, w, _ = frame.shape
        # Calcolo scala per coprire tutto (Fill)
        scale = max(target_w / w, target_h / h)
        nw, nh = int(w * scale), int(h * scale)
        img_res = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
        # Ritaglio centrale
        sy, sx = (img_res.shape[0] - target_h) // 2, (img_res.shape[1] - target_w) // 2
        return img_res[sy:sy+target_h, sx:sx+target_w]
    
    return clip.transform(frame_transform)

# --- 3. LOGICA SCOMPOSIZIONE (COME FILTRO AGGIUNTIVO) ---
def apply_strips_filter(segment, clips_dict, p, start_in_original):
    tw, th = p['size']
    
    # Griglia calcolata una volta per il segmento
    dim = th if p['orient'] == "Orizzontale" else tw
    grid, curr = [], 0
    while curr < dim:
        thick = random.randint(p['thick'][0], p['thick'][1])
        grid.append((curr, int(min(curr + thick, dim))))
        curr = int(min(curr + thick, dim))

    def make_glitch_frame(get_frame, t):
        out = np.zeros((th, tw, 3), dtype=np.uint8)
        # Pesi protetti (Total weights > 0)
        raw_w = [p['d1'], p['d2'], 10, 5]
        valid_ids = list(clips_dict.keys())
        active_weights = [max(0.01, raw_w[i]) for i in valid_ids]

        # Campionamento frame dai deck
        frames = {}
        for i, c in clips_dict.items():
            # Sincronizza il tempo del frame con l'originale
            f = c.get_frame((start_in_original + t) % c.duration)
            h, w, _ = f.shape
            scale = max(tw/w, th/h)
            f_res = cv2.resize(f, (int(w*scale), int(h*scale)))
            sy, sx = (f_res.shape[0]-th)//2, (f_res.shape[1]-tw)//2
            frames[i] = f_res[sy:sy+th, sx:sx+tw]

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
        # 1. Calcolo durata segmento (Ritmo)
        r = p['ritmo']
        seg_dur = random.uniform(r[0], r[1]) if isinstance(r, (list, tuple)) else r
        seg_dur = min(seg_dur, p['durata'] - current_time)

        # 2. Scelta video dominante (con protezione pesi)
        raw_w = [p['d1'], p['d2'], 10, 5]
        valid_ids = list(clips.keys())
        active_weights = [max(0.01, raw_w[i]) for i in valid_ids]
        main_id = random.choices(valid_ids, weights=active_weights)[0]

        # 3. Creazione segmento con STRATEGIA APP.PY (Subclip + Fill)
        start_pos = random.uniform(0, max(0, clips[main_id].duration - seg_dur))
        seg = clips[main_id].subclipped(start_pos, start_pos + seg_dur)
        seg = apply_fill_strategy(seg, tw, th)

        # 4. Applicazione Strisce (se attiva)
        if p['usa_strisce']:
            seg = apply_strips_filter(seg, clips, p, start_pos)

        final_segments.append(seg)
        current_time += seg_dur

    # 5. Concatenazione finale (Metodo solido per audio)
    final_video = concatenate_videoclips(final_segments, method="compose")
    
    out_p = os.path.join(tempfile.gettempdir(), f"final_{int(time.time())}.mp4")
    final_video.write_videofile(out_p, fps=24, codec="libx264", audio_codec="aac", logger=None)
    
    for c in clips.values(): c.close()
    return out_p

# --- 5. INTERFACCIA ---
def main():
    st.set_page_config(layout="wide")
    st.title("📟 GLITCH ENGINE - STRATEGIA APP.PY")
    
    col1, col2 = st.columns(2)
    with col1:
        usa_strisce = st.toggle("SCOMPOSIZIONE A STRISCE", value=True)
        v_files = [st.file_uploader(f"Video {i+1}", type=["mp4","mov"]) for i in range(4)]
        ritmo = st.slider("Ritmo (Durata Segmenti)", 0.05, 1.0, (0.1, 0.3))
        aspect = st.selectbox("Formato Output (FILL)", ["16:9", "1:1", "9:16"])
        
    with col2:
        d1 = st.slider("Peso Deck 1", 0, 100, 100)
        d2 = st.slider("Peso Deck 2", 0, 100, 50)
        durata = st.number_input("Durata Totale Video", 1, 60, 10)
        
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
        
        if not paths: st.error("Carica almeno un video!"); return
        
        res_map = {"16:9": (1280, 720), "1:1": (720, 720), "9:16": (405, 720)}
        params = {
            'durata': durata, 'ritmo': ritmo, 'size': res_map[aspect],
            'd1': d1, 'd2': d2, 'thick': thick, 'orient': orient, 'usa_strisce': usa_strisce
        }
        
        with st.spinner("Rendering con strategia FILL..."):
            try:
                res = process_video(paths, params)
                st.video(res)
                st.download_button("Scarica", open(res, "rb"), "glitch.mp4")
            except Exception as e:
                st.error(f"Errore tecnico: {e}")

if __name__ == "__main__": main()
