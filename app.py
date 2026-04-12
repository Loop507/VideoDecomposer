import streamlit as st
import os
import random
import tempfile
import numpy as np
from moviepy.editor import VideoFileClip, VideoClip

# --- 1. MOTORE DI SCOMPOSIZIONE (CORE) ---
def apply_glitch_engine(deck_frames, weights, strip_map, offset_val, jitter_val, jitter_indep, orientation):
    # Prendiamo le dimensioni dal primo deck come riferimento
    ref_frame = next(iter(deck_frames.values()))
    h, w, c = ref_frame.shape
    out_frame = np.zeros_like(ref_frame)
    
    active_ids = list(deck_frames.keys())
    # Jitter globale (se non indipendente, vibra tutto il blocco)
    block_jitter = random.randint(-jitter_val, jitter_val) if (jitter_val > 0 and not jitter_indep) else 0

    for (start_p, end_p) in strip_map:
        # Scelta del Deck tramite pesi probabilistici
        chosen_id = random.choices(active_ids, weights=[weights[i] for i in active_ids])[0]
        source = deck_frames[chosen_id]
        
        # Calcolo Offset finale (Spostamento + Jitter scelto)
        final_off = offset_val + block_jitter
        if jitter_indep and jitter_val > 0:
            final_off += random.randint(-jitter_val, jitter_val)
            
        if orientation == "Orizzontale":
            strip = source[start_p:end_p, :]
            out_frame[start_p:end_p, :] = np.roll(strip, final_off, axis=1)
        else:
            strip = source[:, start_p:end_p]
            out_frame[:, start_p:end_p] = np.roll(strip, final_off, axis=0)
            
    return out_frame

# --- 2. NORMALIZZAZIONE FORMATI (1:1, 16:9, 9:16) ---
def normalize_clip(clip, aspect_ratio):
    target_h = 720
    if aspect_ratio == "1:1": target_w = 720
    elif aspect_ratio == "16:9": target_w = 1280
    else: target_w = 405 # 9:16
    
    # Resize e Crop centrale per evitare distorsioni
    c_res = clip.resize(height=target_h)
    return c_res.crop(x_center=c_res.w/2, y_center=target_h/2, width=target_w, height=target_h)

# --- 3. RENDERING MASTER ---
def run_full_render(video_paths, p):
    # Caricamento e pulizia Deck
    clips = {}
    for i, path in video_paths.items():
        clips[i] = normalize_clip(VideoFileClip(path), p['aspect'])

    duration = p['durata']
    fps = 24
    
    # Stato persistente per il Ritmo (Stutter)
    state = {'last_tick': -1.0, 'current_map': None, 'next_tick_dur': 0}

    def make_frame(t):
        # A. LOGICA RITMICA (Aggiorna la griglia ogni X secondi)
        if t - state['last_tick'] >= state['next_tick_dur'] or state['current_map'] is None:
            dim = 720 if p['orient'] == "Orizzontale" else clips[0].w
            new_map = []
            curr = 0
            while curr < dim:
                # Spessore random o fisso
                thick = random.randint(p['thick'][0], p['thick'][1]) if p['rand'] else p['thick'][1]
                end = min(curr + thick, dim)
                new_map.append((curr, end))
                curr = end
            state['current_map'] = new_map
            state['last_tick'] = t
            state['next_tick_dur'] = random.uniform(p['ritmo'][0], p['ritmo'][1])

        # B. EVOLUZIONE TEMPORALE (Pesi e Offset)
        prog = t / duration
        # Interpolazione dei deck principali
        w1 = p['d1_s'] + (p['d1_e'] - p['d1_s']) * prog
        w2 = p['d2_s'] + (p['d2_e'] - p['d2_s']) * prog
        weights = {0: w1, 1: w2, 2: p['d3_w'], 3: p['d4_w']}
        
        # Interpolazione spostamento pixel
        curr_off = int(p['off_s'] + (p['off_e'] - p['off_s']) * prog)
        
        # C. ESTRAZIONE FRAME (Con loop infinito automatico)
        deck_frames = {i: c.get_frame(t % c.duration) for i, c in clips.items()}
        
        return apply_glitch_engine(deck_frames, weights, state['current_map'], 
                                   curr_off, p['jitter'], p['j_indep'], p['orient'])

    # Creazione video finale
    final_clip = VideoClip(make_frame, duration=duration).set_fps(fps)
    
    # Audio Master dal Deck 1 (tagliato alla durata esatta)
    if clips[0].audio:
        final_clip = final_clip.set_audio(clips[0].audio.subclip(0, min(duration, clips[0].duration)))

    out_p = os.path.join(tempfile.gettempdir(), "glitch_master_render.mp4")
    final_clip.write_videofile(out_p, codec="libx264", audio_codec="aac", preset="ultrafast", threads=4)
    
    # Pulizia memoria
    for c in clips.values(): c.close()
    return out_p

# --- 4. INTERFACCIA STREAMLIT ---
def main():
    st.set_page_config(layout="wide", page_title="Glitch Engine V3")
    st.title("📟 GLITCH ENGINE: DECOMPOSITION V3")

    col1, col2 = st.columns(2)

    with col1:
        st.header("🎬 Set Regia")
        v_files = [st.file_uploader(f"Video Deck {i+1}", type=["mp4","mov"]) for i in range(4)]
        ritmo = st.slider("Ritmo Stutter (sec)", 0.05, 1.0, (0.2, 0.4))
        aspect = st.selectbox("Formato Schermo", ["16:9", "1:1", "9:16"])
        
        st.subheader("Automazione Presenza (Start ➔ End)")
        d1_se = st.slider("Deck 1 %", 0, 100, (100, 0))
        d2_se = st.slider("Deck 2 %", 0, 100, (0, 100))
        d3_w = st.slider("Deck 3 Rumore %", 0, 100, 15)
        d4_w = st.slider("Deck 4 Rumore %", 0, 100, 5)

    with col2:
        st.header("⚡ Set Distruzione")
        orient = st.radio("Direzione Tagli", ["Orizzontale", "Verticale"])
        thick = st.slider("Spessore Strisce (Min/Max px)", 1, 500, (5, 50))
        is_rand = st.checkbox("Spessore Random 100%", value=True)
        
        st.subheader("Spostamento & Jitter")
        off_se = st.slider("Offset Pixel (Start ➔ End)", 0, 1000, (0, 250))
        jitter = st.slider("Intensità Tremore (Jitter)", 0, 150, 40)
        j_indep = st.toggle("Tremore Indipendente (Granulare)", value=True)
        
        durata = st.number_input("Durata Totale (sec)", 1, 300, 10)

    if st.button("🚀 GENERA VIDEO"):
        paths = {}
        for i, f in enumerate(v_files):
            if f:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as t:
                    t.write(f.read())
                    paths[i] = t.name
        
        if len(paths) < 2:
            st.error("Carica almeno i primi 2 Deck!")
        else:
            p = {
                'durata': durata, 'ritmo': ritmo, 'aspect': aspect, 'orient': orient,
                'd1_s': d1_se[0], 'd1_e': d1_se[1], 'd2_s': d2_se[0], 'd2_e': d2_se[1],
                'd3_w': d3_w, 'd4_w': d4_w, 'thick': thick, 'rand': is_rand,
                'off_s': off_se[0], 'off_e': off_se[1], 'jitter': jitter, 'j_indep': j_indep
            }
            with st.spinner("Scomposizione molecolare in corso..."):
                result = run_full_render(paths, p)
                st.video(result)
                with open(result, "rb") as f:
                    st.download_button("📥 Scarica Master", f, "glitch_render.mp4")

if __name__ == "__main__":
    main()
