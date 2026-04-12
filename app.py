import streamlit as st
import os, random, tempfile, cv2, time
import numpy as np
from moviepy.editor import VideoFileClip, VideoClip

# --- 1. FUNZIONE LOGICA SCOMPOSIZIONE (IL "MOSAICO") ---
def apply_decomposition(frames, weights, grid, offset, jitter, j_indep, orient, active_glitch):
    """
    Riceve i frame di tutti i deck e decide come comporre l'immagine finale.
    """
    # Se la scomposizione è SPENTA, restituiamo il frame del deck dominante
    if not active_glitch:
        main_id = random.choices(list(frames.keys()), weights=[weights.get(i,0) for i in frames.keys()])[0]
        return frames[main_id]

    # Se la scomposizione è ACCESA, creiamo il mosaico
    ref_frame = next(iter(frames.values()))
    h, w, c = ref_frame.shape
    out_frame = np.zeros_like(ref_frame)
    
    active_ids = list(frames.keys())
    # Vibrazione globale
    block_jitter = random.randint(-jitter, jitter) if (jitter > 0 and not j_indep) else 0

    for (start_p, end_p) in grid:
        # 1. Automazione Deck 1 -> 2: Scegliamo chi possiede questa striscia
        w_list = [weights.get(i, 0) for i in active_ids]
        chosen_id = random.choices(active_ids, weights=w_list)[0]
        source = frames[chosen_id]
        
        # 2. Calcolo Spostamento (Offset + Jitter)
        final_off = int(offset + block_jitter)
        if j_indep and jitter > 0:
            final_off += random.randint(-jitter, jitter)
            
        # 3. Taglio e Cucito
        if orient == "Orizzontale":
            strip = source[start_p:end_p, :]
            out_frame[start_p:end_p, :] = np.roll(strip, final_off, axis=1)
        else:
            strip = source[:, start_p:end_p]
            out_frame[:, start_p:end_p] = np.roll(strip, final_off, axis=0)
            
    return out_frame

# --- 2. NORMALIZZAZIONE VIDEO (ANTI-CRASH) ---
def prepare_clip(path, aspect):
    clip = VideoFileClip(path)
    h_target = 720
    w_target = 1280 if aspect == "16:9" else (720 if aspect == "1:1" else 405)

    def frame_transform(get_frame, t):
        pic = get_frame(t)
        h, w, _ = pic.shape
        scale = h_target / h
        res = cv2.resize(pic, (int(w * scale), h_target), interpolation=cv2.INTER_AREA)
        h_res, w_res, _ = res.shape
        start_x = max(0, w_res//2 - w_target//2)
        return res[:, start_x:start_x+w_target]

    # .transform è il metodo universale compatibile con MoviePy 1.0 e 2.0
    return clip.transform(frame_transform)

# --- 3. MOTORE DI RENDERING ---
def render_engine(video_paths, p):
    clips = {i: prepare_clip(path, p['aspect']) for i, path in video_paths.items()}
    duration, fps = p['durata'], 24
    
    # Stato interno per il ritmo delle strisce
    state = {'last_tick': -1.0, 'current_grid': None, 'next_dur': 0}

    def make_frame(t):
        # A. Gestione Ritmo (Stutter)
        if t - state['last_tick'] >= state['next_dur'] or state['current_grid'] is None:
            first_clip = clips[next(iter(clips))]
            sample = first_clip.get_frame(0)
            dim = sample.shape[0] if p['orient'] == "Orizzontale" else sample.shape[1]
            
            # Generazione nuova griglia spaziale
            new_grid, curr = [], 0
            while curr < dim:
                thick = random.randint(p['thick'][0], p['thick'][1])
                end = int(min(curr + thick, dim))
                new_grid.append((curr, end))
                curr = end
            state['current_grid'], state['last_tick'] = new_grid, t
            state['next_dur'] = random.uniform(p['ritmo'][0], p['ritmo'][1])

        # B. Automazione Deck 1 -> 2 (Calcolo Probabilità temporale)
        prog = min(t / duration, 1.0)
        weights = {
            0: p['d1_s'] + (p['d1_e'] - p['d1_s']) * prog, # Deck 1
            1: p['d2_s'] + (p['d2_e'] - p['d2_s']) * prog, # Deck 2
            2: p['d3_w'], # Noise Deck 3
            3: p['d4_w']  # Noise Deck 4
        }
        
        # C. Composizione Finale
        deck_frames = {i: c.get_frame(t % c.duration) for i, c in clips.items()}
        curr_offset = int(p['off_s'] + (p['off_e'] - p['off_s']) * prog)
        
        return apply_decomposition(
            deck_frames, weights, state['current_grid'], 
            curr_offset, p['jitter'], p['j_indep'], p['orient'], p['active_glitch']
        )

    # Generazione clip
    final = VideoClip(make_frame, duration=duration).set_fps(fps)
    if 0 in clips and clips[0].audio:
        final = final.set_audio(clips[0].audio.subclip(0, min(duration, clips[0].duration)))

    output_file = os.path.join(tempfile.gettempdir(), f"master_{int(time.time())}.mp4")
    final.write_videofile(output_file, codec="libx264", audio_codec="aac", preset="ultrafast", logger=None)
    
    for c in clips.values(): c.close()
    return output_file

# --- 4. INTERFACCIA STREAMLIT ---
def main():
    st.set_page_config(layout="wide", page_title="Glitch Engine V3.3")
    st.title("📟 GLITCH ENGINE: DECOMPOSITION V3.3")
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.header("🎬 Set Regia")
        v_files = [st.file_uploader(f"Video Deck {i+1}", type=["mp4","mov"]) for i in range(4)]
        ritmo = st.slider("Ritmo Stutter (sec)", 0.01, 1.0, (0.10, 0.30), step=0.01)
        aspect = st.selectbox("Formato Schermo", ["16:9", "1:1", "9:16"])
        
        st.subheader("Automazione Presenza (Start ➔ End)")
        d1_se = st.slider("Deck 1 %", 0, 100, (100, 0))
        d2_se = st.slider("Deck 2 %", 0, 100, (0, 100))
        d3_w = st.slider("Deck 3 Rumore %", 0, 100, 15)
        d4_w = st.slider("Deck 4 Rumore %", 0, 100, 5)

    with col2:
        st.header("⚡ Set Distruzione")
        active_glitch = st.toggle("ATTIVA SCOMPOSIZIONE (STRISCE)", value=True)
        orient = st.radio("Direzione Tagli", ["Orizzontale", "Verticale"])
        thick = st.slider("Spessore Strisce (Min/Max px)", 1, 500, (5, 28))
        
        st.subheader("Spostamento & Jitter")
        off_se = st.slider("Offset Pixel (Start ➔ End)", 0, 1000, (0, 250))
        jitter = st.slider("Intensità Tremore (Jitter)", 0, 150, 40)
        j_indep = st.toggle("Tremore Indipendente (Granulare)", value=True)
        durata = st.number_input("Durata Totale (sec)", 1, 300, 10)

    if st.button("🚀 GENERA VIDEO"):
        paths = {i: tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") for i, f in enumerate(v_files) if f}
        for i, f in enumerate(v_files):
            if f: paths[i].write(f.read()); paths[i] = paths[i].name
        
        if len(paths) < 2:
            st.error("Carica almeno i primi 2 Deck!")
        else:
            params = {
                'durata': durata, 'ritmo': ritmo, 'aspect': aspect, 'orient': orient,
                'd1_s': d1_se[0], 'd1_e': d1_se[1], 'd2_s': d2_se[0], 'd2_e': d2_se[1],
                'd3_w': d3_w, 'd4_w': d4_w, 'thick': thick, 'active_glitch': active_glitch,
                'off_s': off_se[0], 'off_e': off_se[1], 'jitter': jitter, 'j_indep': j_indep
            }
            with st.spinner("Sintetizzando il glitch..."):
                try:
                    res = render_engine(paths, params)
                    st.video(res)
                    st.download_button("📥 Scarica Master", open(res, "rb"), "glitch_master.mp4")
                    for p in paths.values(): os.unlink(p)
                except Exception as e:
                    st.error(f"Errore: {e}")

if __name__ == "__main__":
    main()
