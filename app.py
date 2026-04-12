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

# --- 2. FUNZIONE FILL (RITAGLIO INTELLIGENTE) ---
def get_full_frame(get_frame_func, t, target_w, target_h, clip_dur):
    img = get_frame_func(t % clip_dur)
    h, w, _ = img.shape
    scale = max(target_w / w, target_h / h)
    nw, nh = int(w * scale), int(h * scale)
    img_res = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
    # Crop centrale per riempire il formato
    sy, sx = (nh - target_h) // 2, (nw - target_w) // 2
    return img_res[sy:sy+target_h, sx:sx+target_w]

# --- 3. MOTORE DI RENDERING ---
def render_engine(video_paths, p):
    clips = {i: VideoFileClip(path) for i, path in video_paths.items()}
    tw, th = p['size']
    duration = p['durata']
    
    # Stato per sincronizzare audio e video
    state = {'last_t': -1.0, 'grid': None, 'next_step': 0, 'audio_id': 0}

    def make_frame(t):
        # Gestione sicura dei parametri (Fix len() error)
        r_range = p['ritmo']
        min_r, max_r = (r_range[0], r_range[1]) if isinstance(r_range, (list, tuple)) else (r_range, r_range)
        
        # Aggiornamento griglia e scelta audio al "ritmo" giusto
        if t - state['last_t'] >= state['next_step'] or state['grid'] is None:
            # Crea nuova scomposizione
            dim = th if p['orient'] == "Orizzontale" else tw
            new_grid = []
            curr = 0
            while curr < dim:
                thick = random.randint(p['thick'][0], p['thick'][1])
                end = int(min(curr + thick, dim))
                new_grid.append((curr, end))
                curr = end
            state['grid'] = new_grid
            state['last_t'] = t
            state['next_step'] = random.uniform(min_r, max_r)
            
            # Sceglie quale deck comanda l'audio per questo intervallo
            prog = t / duration
            weights = [
                p['d1_s'] + (p['d1_e'] - p['d1_s']) * prog,
                p['d2_s'] + (p['d2_e'] - p['d2_s']) * prog,
                p['d3_w'], p['d4_w']
            ]
            valid_ids = list(clips.keys())
            # Filtra pesi solo per clip esistenti
            active_weights = [weights[i] for i in valid_ids]
            state['audio_id'] = random.choices(valid_ids, weights=active_weights)[0]

        # Generazione frame
        out = np.zeros((th, tw, 3), dtype=np.uint8)
        # Pre-carica i frame Fill per questo istante t
        dframes = {i: get_full_frame(c.get_frame, t, tw, th, c.duration) for i, c in clips.items()}
        
        # Applica le strisce
        prog = t / duration
        current_weights = [p['d1_s'] + (p['d1_e'] - p['d1_s']) * prog, 
                           p['d2_s'] + (p['d2_e'] - p['d2_s']) * prog, 
                           p['d3_w'], p['d4_w']]
        valid_ids = list(clips.keys())
        active_weights = [current_weights[i] for i in valid_ids]

        for (s, e) in state['grid']:
            chosen = random.choices(valid_ids, weights=active_weights)[0]
            if p['orient'] == "Orizzontale":
                out[s:e, :] = dframes[chosen][s:e, :]
            else:
                out[:, s:e] = dframes[chosen][:, s:e]
        return out

    def make_audio(t_array):
        # Audio masticato: segue la scelta fatta in make_frame
        audio_out = np.zeros((len(t_array), 2))
        for i, t in enumerate(t_array):
            target = state['audio_id']
            if target in clips and clips[target].audio:
                audio_out[i] = clips[target].audio.get_frame(t % clips[target].duration)
        return audio_out

    # Rendering finale
    v_clip = VideoClip(make_frame, duration=duration)
    if p['sync_audio']:
        v_clip.audio = AudioClip(make_audio, duration=duration)
    elif 0 in clips and clips[0].audio:
        v_clip.audio = clips[0].audio.with_duration(duration)

    out_file = os.path.join(tempfile.gettempdir(), f"render_{int(time.time())}.mp4")
    v_clip.write_videofile(out_file, fps=24, codec="libx264", audio_codec="aac", logger=None)
    
    for c in clips.values(): c.close()
    return out_file

# --- 4. INTERFACCIA ---
def main():
    st.set_page_config(layout="wide")
    st.title("📟 GLITCH ENGINE V4.3 - FINAL")
    
    c1, c2 = st.columns(2)
    with c1:
        v_files = [st.file_uploader(f"Video {i+1}", type=["mp4","mov"]) for i in range(4)]
        ritmo = st.slider("Ritmo Stutter", 0.01, 1.0, (0.05, 0.20))
        aspect = st.selectbox("Formato", ["16:9", "1:1", "9:16"])
        sync_audio = st.toggle("Audio masticato (Sync)", value=True)
        
    with c2:
        d1_se = st.slider("Deck 1 (%)", 0, 100, (100, 0))
        d2_se = st.slider("Deck 2 (%)", 0, 100, (0, 100))
        thick = st.slider("Spessore Strisce", 1, 300, (5, 35))
        orient = st.radio("Direzione", ["Orizzontale", "Verticale"])
        durata = st.number_input("Secondi totali", 1, 60, 10)

    if st.button("🚀 GENERA"):
        paths = {i: tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") for i, f in enumerate(v_files) if f}
        for i, f in enumerate(v_files):
            if f: paths[i].write(f.read()); paths[i] = paths[i].name
        
        if not paths:
            st.error("Manca il video sorgente!")
            return

        size_map = {"16:9": (1280, 720), "1:1": (720, 720), "9:16": (405, 720)}
        params = {
            'durata': durata, 'ritmo': ritmo, 'size': size_map[aspect],
            'd1_s': d1_se[0], 'd1_e': d1_se[1], 'd2_s': d2_se[0], 'd2_e': d2_se[1],
            'd3_w': 10, 'd4_w': 5, 'thick': thick, 'orient': orient, 
            'sync_audio': sync_audio
        }
        
        with st.spinner("Creazione in corso..."):
            try:
                res = render_engine(paths, params)
                st.video(res)
                st.download_button("Scarica", open(res, "rb"), "glitch_master.mp4")
                for p in paths.values(): os.unlink(p)
            except Exception as e:
                st.error(f"Errore: {e}")

if __name__ == "__main__": main()
