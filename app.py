import streamlit as st
import os, random, tempfile, cv2, time
import numpy as np

# --- 1. IMPORTAZIONE MOVIEPY 2.x ---
try:
    from moviepy.video.io.VideoFileClip import VideoFileClip
    from moviepy.video.VideoClip import VideoClip
except ImportError:
    from moviepy.editor import VideoFileClip, VideoClip

# --- 2. LOGICA SCOMPOSIZIONE (ROBUSTA) ---
def apply_decomposition(frames, weights, grid, offset, jitter, j_indep, orient, active_glitch):
    # Trasformiamo i pesi in float per evitare errori di precisione
    active_ids = list(frames.keys())
    w_list = [float(weights.get(i, 0.01)) for i in active_ids]
    
    # Se la somma è zero, forziamo il primo deck disponibile
    if sum(w_list) <= 0:
        w_list[0] = 1.0

    if not active_glitch:
        chosen_id = random.choices(active_ids, weights=w_list)[0]
        return frames[chosen_id]

    ref_frame = next(iter(frames.values()))
    h, w, c = ref_frame.shape
    out_frame = np.zeros_like(ref_frame)
    block_jitter = random.randint(-jitter, jitter) if (jitter > 0 and not j_indep) else 0

    for (start_p, end_p) in grid:
        chosen_id = random.choices(active_ids, weights=w_list)[0]
        source = frames[chosen_id]
        
        final_off = int(offset + block_jitter)
        if j_indep and jitter > 0:
            final_off += random.randint(-jitter, jitter)
            
        if orient == "Orizzontale":
            strip = source[start_p:end_p, :]
            out_frame[start_p:end_p, :] = np.roll(strip, final_off, axis=1)
        else:
            strip = source[:, start_p:end_p]
            out_frame[:, start_p:end_p] = np.roll(strip, final_off, axis=0)
            
    return out_frame

# --- 3. PREPARAZIONE CLIP ---
def prepare_clip(path, aspect):
    clip = VideoFileClip(path)
    h_target = 720
    w_target = 1280 if aspect == "16:9" else (720 if aspect == "1:1" else 405)

    def frame_transform(get_frame, t):
        # Protezione: se t supera la durata, facciamo il loop del tempo
        pic = get_frame(t % clip.duration)
        h, w, _ = pic.shape
        scale = h_target / h
        res = cv2.resize(pic, (int(w * scale), h_target), interpolation=cv2.INTER_AREA)
        h_res, w_res, _ = res.shape
        start_x = max(0, w_res//2 - w_target//2)
        return res[:, start_x:start_x+w_target]

    return clip.transform(frame_transform)

# --- 4. MOTORE RENDERING ---
def render_engine(video_paths, p):
    clips = {i: prepare_clip(path, p['aspect']) for i, path in video_paths.items()}
    duration, fps = p['durata'], 24
    state = {'last_tick': -1.0, 'current_grid': None, 'next_dur': 0}

    def make_frame(t):
        if t - state['last_tick'] >= state['next_dur'] or state['current_grid'] is None:
            first_clip = clips[next(iter(clips))]
            sample = first_clip.get_frame(0)
            dim = sample.shape[0] if p['orient'] == "Orizzontale" else sample.shape[1]
            
            new_grid, curr = [], 0
            while curr < dim:
                thick = random.randint(p['thick'][0], p['thick'][1])
                end = int(min(curr + thick, dim))
                new_grid.append((curr, end))
                curr = end
            state['current_grid'], state['last_tick'] = new_grid, t
            state['next_dur'] = random.uniform(p['ritmo'][0], p['ritmo'][1])

        prog = min(t / duration, 1.0)
        
        # Calcolo pesi con micro-offset di sicurezza
        weights = {
            0: max(0.01, float(p['d1_s'] + (p['d1_e'] - p['d1_s']) * prog)),
            1: max(0.01, float(p['d2_s'] + (p['d2_e'] - p['d2_s']) * prog)),
            2: max(0.01, float(p['d3_w'])),
            3: max(0.01, float(p['d4_w']))
        }
        
        # Estrazione frame con gestione errori
        deck_frames = {}
        for i, c in clips.items():
            try:
                deck_frames[i] = c.get_frame(t % c.duration)
            except:
                deck_frames[i] = np.zeros((720, 1280, 3), dtype="uint8") # Frame nero di emergenza
        
        curr_offset = int(p['off_s'] + (p['off_e'] - p['off_s']) * prog)
        
        return apply_decomposition(
            deck_frames, weights, state['current_grid'], 
            curr_offset, p['jitter'], p['j_indep'], p['orient'], p['active_glitch']
        )

    final = VideoClip(make_frame, duration=duration).set_fps(fps)
    if 0 in clips and clips[0].audio:
        final = final.set_audio(clips[0].audio.subclip(0, min(duration, clips[0].duration)))

    out_p = os.path.join(tempfile.gettempdir(), f"render_{int(time.time())}.mp4")
    final.write_videofile(out_p, codec="libx264", audio_codec="aac", preset="ultrafast", logger=None)
    
    for c in clips.values(): c.close()
    return out_p

# --- 5. UI ---
def main():
    st.set_page_config(layout="wide")
    st.title("📟 GLITCH ENGINE V3.4 - STABLE")
    
    col1, col2 = st.columns(2)
    with col1:
        st.header("🎬 Regia")
        v_files = [st.file_uploader(f"Video {i+1}", type=["mp4","mov"]) for i in range(4)]
        ritmo = st.slider("Ritmo Stutter", 0.01, 1.0, (0.10, 0.30), step=0.01)
        aspect = st.selectbox("Formato", ["16:9", "1:1", "9:16"])
        d1_se = st.slider("Deck 1 %", 0, 100, (100, 0))
        d2_se = st.slider("Deck 2 %", 0, 100, (0, 100))
        d3_w = st.slider("Noise 3 %", 0, 100, 15)
        d4_w = st.slider("Noise 4 %", 0, 100, 5)

    with col2:
        st.header("⚡ Distorsione")
        active_glitch = st.toggle("ATTIVA SCOMPOSIZIONE", value=True)
        orient = st.radio("Tagli", ["Orizzontale", "Verticale"])
        thick = st.slider("Spessore (px)", 1, 500, (5, 30))
        off_se = st.slider("Offset (px)", 0, 1000, (0, 250))
        jitter = st.slider("Jitter", 0, 150, 40)
        j_indep = st.toggle("Jitter Indipendente", value=True)
        durata = st.number_input("Durata (sec)", 1, 300, 10)

    if st.button("🚀 GENERA VIDEO"):
        paths = {i: tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") for i, f in enumerate(v_files) if f}
        for i, f in enumerate(v_files):
            if f: paths[i].write(f.read()); paths[i] = paths[i].name
        
        if len(paths) < 2:
            st.error("Carica almeno i primi 2 video!")
        else:
            params = {
                'durata': durata, 'ritmo': ritmo, 'aspect': aspect, 'orient': orient,
                'd1_s': d1_se[0], 'd1_e': d1_se[1], 'd2_s': d2_se[0], 'd2_e': d2_se[1],
                'd3_w': d3_w, 'd4_w': d4_w, 'thick': thick, 'active_glitch': active_glitch,
                'off_s': off_se[0], 'off_e': off_se[1], 'jitter': jitter, 'j_indep': j_indep
            }
            with st.spinner("Rendering..."):
                try:
                    res = render_engine(paths, params)
                    st.video(res)
                    st.download_button("📥 Scarica", open(res, "rb"), "glitch.mp4")
                    for p in paths.values(): os.unlink(p)
                except Exception as e:
                    st.error(f"Errore critico: {e}")

if __name__ == "__main__":
    main()
