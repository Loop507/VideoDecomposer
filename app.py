import streamlit as st
import os, random, tempfile, cv2, time
import numpy as np

# --- 1. IMPORTAZIONE MOVIEPY 2.2.1 ---
try:
    from moviepy.video.io.VideoFileClip import VideoFileClip
    from moviepy.video.VideoClip import VideoClip
    from moviepy.audio.AudioClip import AudioClip
except ImportError:
    from moviepy.editor import VideoFileClip, VideoClip, AudioClip

# --- 2. LOGICA FILL (ZOOM AUTOMATICO) ---
def get_frame_fill(clip, t, target_w, target_h):
    # Prende il frame e lo scala per riempire tutto il canvas senza barre nere
    img = clip.get_frame(t % clip.duration)
    h, w, _ = img.shape
    scale = max(target_w / w, target_h / h)
    nw, nh = int(w * scale), int(h * scale)
    img_res = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
    sy, sx = (nh - target_h) // 2, (nw - target_w) // 2
    return img_res[sy:sy+target_h, sx:sx+target_w]

# --- 3. MOTORE DI RENDERING ---
def render_engine(video_paths, p):
    clips = {i: VideoFileClip(path) for i, path in video_paths.items()}
    tw, th = p['size']
    duration = p['durata']
    
    # Stato per sincronizzare video e audio
    state = {'last_t': -1.0, 'grid': None, 'next_step': 0, 'active_id': 0}

    def make_frame(t):
        # Scompattamento ritmo sicuro
        r = p['ritmo']
        min_r, max_r = (r[0], r[1]) if isinstance(r, (list, tuple)) else (r, r)
        
        # Cambio segmento in base al ritmo
        if t - state['last_t'] >= state['next_step'] or state['grid'] is None:
            state['last_t'] = t
            state['next_step'] = random.uniform(min_r, max_r)
            
            # Crea griglia per strisce
            dim = th if p['orient'] == "Orizzontale" else tw
            grid, curr = [], 0
            while curr < dim:
                thick = random.randint(p['thick'][0], p['thick'][1])
                grid.append((curr, int(min(curr + thick, dim))))
                curr = int(min(curr + thick, dim))
            state['grid'] = grid
            
            # Decide chi comanda l'audio/video principale
            prog = t / duration
            weights = [
                p['d1_s'] + (p['d1_e'] - p['d1_s']) * prog,
                p['d2_s'] + (p['d2_e'] - p['d2_s']) * prog,
                10, 5 # Pesi fissi per Deck 3 e 4
            ]
            valid_ids = list(clips.keys())
            active_weights = [weights[i] for i in valid_ids]
            state['active_id'] = random.choices(valid_ids, weights=active_weights)[0]

        # Carica i frame con logica FILL
        frames = {i: get_frame_fill(c, t, tw, th) for i, c in clips.items()}

        if not p['usa_strisce']:
            # Modalità "Primo Codice": Schermo pieno, solo tagli netti
            return frames[state['active_id']]
        
        # Modalità "Strisce": Mix spaziale
        out = np.zeros((th, tw, 3), dtype=np.uint8)
        prog = t / duration
        weights = [p['d1_s'] + (p['d1_e'] - p['d1_s']) * prog, 
                   p['d2_s'] + (p['d2_e'] - p['d2_s']) * prog, 10, 5]
        valid_ids = list(clips.keys())
        active_weights = [weights[i] for i in valid_ids]

        for (s, e) in state['grid']:
            chosen = random.choices(valid_ids, weights=active_weights)[0]
            if p['orient'] == "Orizzontale":
                out[s:e, :] = frames[chosen][s:e, :]
            else:
                out[:, s:e] = frames[chosen][:, s:e]
        return out

    def make_audio(t_array):
        # Audio "masticato" che segue i tagli del video
        samples = np.zeros((len(t_array), 2))
        for i, t in enumerate(t_array):
            idx = state['active_id']
            if idx in clips and clips[idx].audio:
                samples[i] = clips[idx].audio.get_frame(t % clips[idx].duration)
        return samples

    # Creazione video finale
    final = VideoClip(make_frame, duration=duration)
    final.audio = AudioClip(make_audio, duration=duration)
    
    out_p = os.path.join(tempfile.gettempdir(), f"mix_{int(time.time())}.mp4")
    final.write_videofile(out_p, fps=24, codec="libx264", audio_codec="aac", logger=None)
    for c in clips.values(): c.close()
    return out_p

# --- 4. INTERFACCIA STREAMLIT ---
def main():
    st.set_page_config(layout="wide", page_title="Glitch Engine PRO")
    st.title("📟 GLITCH ENGINE V4.7")
    
    col1, col2 = st.columns(2)
    with col1:
        st.header("⚙️ Configurazione")
        usa_strisce = st.toggle("ATTIVA STRISCE", value=True)
        v_files = [st.file_uploader(f"Video {i+1}", type=["mp4","mov"]) for i in range(4)]
        ritmo = st.slider("Ritmo Tagli (sec)", 0.02, 1.0, (0.05, 0.20))
        aspect = st.selectbox("Formato", ["16:9", "1:1", "9:16"])
        
    with col2:
        st.header("📊 Automazione")
        d1_se = st.slider("Deck 1 (%)", 0, 100, (100, 0))
        d2_se = st.slider("Deck 2 (%)", 0, 100, (0, 100))
        thick = st.slider("Spessore Strisce", 1, 300, (5, 30))
        orient = st.radio("Orientamento", ["Orizzontale", "Verticale"])
        durata = st.number_input("Durata (sec)", 1, 60, 10)

    if st.button("🚀 GENERA VIDEO"):
        paths = {}
        for i, f in enumerate(v_files):
            if f:
                t = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
                t.write(f.read())
                paths[i] = t.name
        
        if not paths:
            st.error("Carica i video!")
            return
        
        res_map = {"16:9": (1280, 720), "1:1": (720, 720), "9:16": (405, 720)}
        params = {
            'durata': durata, 'ritmo': ritmo, 'size': res_map[aspect],
            'd1_s': d1_se[0], 'd1_e': d1_se[1], 'd2_s': d2_se[0], 'd2_e': d2_se[1],
            'thick': thick, 'orient': orient, 'usa_strisce': usa_strisce
        }
        
        with st.spinner("Rendering..."):
            try:
                res = render_engine(paths, params)
                st.video(res)
                st.download_button("Scarica", open(res, "rb"), "glitch.mp4")
                for p in paths.values(): os.unlink(p)
            except Exception as e:
                st.error(f"Errore: {e}")

if __name__ == "__main__":
    main()
