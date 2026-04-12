import streamlit as st
import os, random, tempfile, cv2, time
import numpy as np

# --- 1. IMPORTAZIONE MOVIEPY 2.x ---
try:
    from moviepy.video.io.VideoFileClip import VideoFileClip
    from moviepy.video.VideoClip import VideoClip
    from moviepy.audio.AudioClip import AudioClip
except ImportError:
    from moviepy.editor import VideoFileClip, VideoClip, AudioClip

# --- 2. LOGICA SCOMPOSIZIONE (VISIVA) ---
def apply_decomposition(frames, weights, grid, offset, jitter, j_indep, orient, active_glitch):
    active_ids = list(frames.keys())
    w_list = [float(weights.get(i, 0.01)) for i in active_ids]
    if sum(w_list) <= 0: w_list[0] = 1.0

    # Scelta del Deck dominante per l'audio di questo istante
    winner_audio_id = random.choices(active_ids, weights=w_list)[0]

    if not active_glitch:
        return frames[winner_audio_id], winner_audio_id

    ref_frame = next(iter(frames.values()))
    h, w, c = ref_frame.shape
    out_frame = np.zeros_like(ref_frame)
    block_jitter = random.randint(-jitter, jitter) if (jitter > 0 and not j_indep) else 0

    for (start_p, end_p) in grid:
        # Ogni striscia pesca da un deck a caso in base ai pesi
        strip_id = random.choices(active_ids, weights=w_list)[0]
        source = frames[strip_id]
        
        final_off = int(offset + block_jitter)
        if j_indep and jitter > 0:
            final_off += random.randint(-jitter, jitter)
            
        if orient == "Orizzontale":
            strip = source[start_p:end_p, :]
            out_frame[start_p:end_p, :] = np.roll(strip, final_off, axis=1)
        else:
            strip = source[:, start_p:end_p]
            out_frame[:, start_p:end_p] = np.roll(strip, final_off, axis=0)
            
    return out_frame, winner_audio_id

# --- 3. PREPARAZIONE CLIP (ZOOM/FILL - NO BARRE NERE) ---
def prepare_clip(path, aspect):
    clip = VideoFileClip(path)
    if aspect == "16:9": target_w, target_h = 1280, 720
    elif aspect == "1:1": target_w, target_h = 720, 720
    else: target_w, target_h = 405, 720 # 9:16

    def frame_transform(get_frame, t):
        pic = get_frame(t % clip.duration)
        h, w, _ = pic.shape
        # Logica Fill: zooma finché non copre tutto il canvas
        scale = max(target_w / w, target_h / h)
        res = cv2.resize(pic, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        # Crop centrale
        sy, sx = (res.shape[0] - target_h) // 2, (res.shape[1] - target_w) // 2
        return res[sy:sy+target_h, sx:sx+target_w]

    return clip.transform(frame_transform), target_w, target_h

# --- 4. MOTORE RENDERING ---
def render_engine(video_paths, p):
    clips = {}
    tw, th = 1280, 720
    for i, path in video_paths.items():
        c, tw, th = prepare_clip(path, p['aspect'])
        clips[i] = c

    duration, fps = p['durata'], 24
    state = {'last_tick': -1.0, 'grid': None, 'next_dur': 0, 'audio_map': {}}

    def make_frame(t):
        # Cambio griglia in base al "Ritmo Stutter"
        if t - state['last_tick'] >= state['next_dur'] or state['grid'] is None:
            dim = th if p['orient'] == "Orizzontale" else tw
            new_grid, curr = [], 0
            while curr < dim:
                thick = random.randint(p['thick'][0], p['thick'][1])
                end = int(min(curr + thick, dim))
                new_grid.append((curr, end))
                curr = end
            state['grid'], state['last_tick'] = new_grid, t
            state['next_dur'] = random.uniform(p['ritmo'][0], p['ritmo'][1])

        prog = min(t / duration, 1.0)
        weights = {
            0: max(0.01, float(p['d1_s'] + (p['d1_e'] - p['d1_s']) * prog)),
            1: max(0.01, float(p['d2_s'] + (p['d2_e'] - p['d2_s']) * prog)),
            2: max(0.01, float(p['d3_w'])),
            3: max(0.01, float(p['d4_w']))
        }
        
        deck_frames = {i: c.get_frame(t % c.duration) for i, c in clips.items()}
        curr_offset = int(p['off_s'] + (p['off_e'] - p['off_s']) * prog)
        
        img, win_id = apply_decomposition(
            deck_frames, weights, state['grid'], 
            curr_offset, p['jitter'], p['j_indep'], p['orient'], p['active_glitch']
        )
        
        # Salviamo chi comanda l'audio in questo esatto millisecondo
        state['audio_map'][round(t, 3)] = win_id
        return img

    def make_audio(t_array):
        # Questa funzione trita l'audio seguendo la mappa generata dai frame
        samples = np.zeros((len(t_array), 2))
        for i, t in enumerate(t_array):
            target_id = state['audio_map'].get(round(t, 3), 0)
            if target_id in clips and clips[target_id].audio:
                # Salta al pezzo di audio del video corrispondente (Logica Shuffle)
                samples[i] = clips[target_id].audio.get_frame(t % clips[target_id].duration)
        return samples

    final_v = VideoClip(make_frame, duration=duration)
    final_v.fps, final_v.size = fps, (tw, th)
    
    # Se l'audio sync è attivo, genera la traccia "tritata"
    if p['sync_audio']:
        final_v.audio = AudioClip(make_audio, duration=duration)
    elif 0 in clips and clips[0].audio:
        final_v.audio = clips[0].audio.subclipped(0, duration)

    out_p = os.path.join(tempfile.gettempdir(), f"render_{int(time.time())}.mp4")
    final_v.write_videofile(out_p, codec="libx264", audio_codec="aac", fps=fps, preset="ultrafast", logger=None)
    
    for c in clips.values(): c.close()
    return out_p

# --- 5. UI (BASATA SU APP 222.PY) ---
def main():
    st.set_page_config(layout="wide")
    st.title("📟 GLITCH ENGINE V4.0 - TOTAL SYNC")
    
    col1, col2 = st.columns(2)
    with col1:
        st.header("🎬 Regia")
        v_files = [st.file_uploader(f"Video {i+1}", type=["mp4","mov"]) for i in range(4)]
        ritmo = st.slider("Ritmo Stutter (Taglio Audio/Video)", 0.02, 1.0, (0.05, 0.20))
        aspect = st.selectbox("Formato Output (FILL)", ["16:9", "1:1", "9:16"])
        sync_audio = st.toggle("SINCRONIZZA AUDIO AI TAGLI (Shuffle Audio)", value=True)
        
        st.subheader("Automazione Presenza")
        d1_se = st.slider("Deck 1 (%)", 0, 100, (100, 0))
        d2_se = st.slider("Deck 2 (%)", 0, 100, (0, 100))
        d3_w = st.slider("Noise 3 (%)", 0, 100, 10)
        d4_w = st.slider("Noise 4 (%)", 0, 100, 5)

    with col2:
        st.header("⚡ Effetti Strisce")
        active_glitch = st.toggle("ATTIVA SCOMPOSIZIONE", value=True)
        orient = st.radio("Direzione Tagli", ["Orizzontale", "Verticale"])
        thick = st.slider("Spessore (px)", 1, 500, (2, 20))
        off_se = st.slider("Offset Movimento (px)", 0, 1000, (0, 300))
        jitter = st.slider("Jitter (Vibrazione)", 0, 150, 40)
        j_indep = st.toggle("Jitter Indipendente", value=True)
        durata = st.number_input("Durata Totale (sec)", 1, 300, 10)

    if st.button("🚀 GENERA VIDEO DEFINITIVO"):
        paths = {i: tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") for i, f in enumerate(v_files) if f}
        for i, f in enumerate(v_files):
            if f: paths[i].write(f.read()); paths[i] = paths[i].name
        
        if not paths: st.error("Carica i video!")
        else:
            params = {
                'durata': durata, 'ritmo': ritmo, 'aspect': aspect, 'orient': orient,
                'd1_s': d1_se[0], 'd1_e': d1_se[1], 'd2_s': d2_se[0], 'd2_e': d2_se[1],
                'd3_w': d3_w, 'd4_w': d4_w, 'thick': thick, 'active_glitch': active_glitch,
                'off_s': off_se[0], 'off_e': off_se[1], 'jitter': jitter, 'j_indep': j_indep,
                'sync_audio': sync_audio
            }
            with st.spinner("Sintetizzando Audio e Video..."):
                try:
                    res = render_engine(paths, params)
                    st.video(res)
                    st.download_button("📥 Scarica Master", open(res, "rb"), "glitch_master.mp4")
                    for p in paths.values(): os.unlink(p)
                except Exception as e: st.error(f"Errore: {e}")

if __name__ == "__main__":
    main()
