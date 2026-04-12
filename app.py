import streamlit as st
import os
import random
import tempfile
import numpy as np
import cv2
from moviepy.editor import VideoFileClip, VideoClip
from PIL import Image

# --- PATCH DI COMPATIBILITÀ ---
# Forza il sistema a riconoscere ANTIALIAS anche nelle versioni nuove di Pillow
if not hasattr(Image, 'LANCZOS'):
    Image.LANCZOS = Image.Resampling.LANCZOS
if not hasattr(Image, 'ANTIALIAS'):
    Image.ANTIALIAS = Image.LANCZOS

# --- 1. MOTORE DI SCOMPOSIZIONE (OTTIMIZZATO) ---
def apply_glitch_core(deck_frames, weights, strip_map, offset_val, jitter_val, jitter_indep, orientation):
    # Usiamo il primo deck disponibile come riferimento
    ref_id = next(iter(deck_frames))
    ref_frame = deck_frames[ref_id]
    h, w, c = ref_frame.shape
    out_frame = np.zeros_like(ref_frame)
    
    active_ids = list(deck_frames.keys())
    # Jitter di blocco (vibrazione globale)
    block_jitter = random.randint(-jitter_val, jitter_val) if (jitter_val > 0 and not jitter_indep) else 0

    for (start_p, end_p) in strip_map:
        # Selezione probabilistica del Deck
        chosen_id = random.choices(active_ids, weights=[weights[i] for i in active_ids])[0]
        source = deck_frames[chosen_id]
        
        # Calcolo Offset finale
        final_off = int(offset_val + block_jitter)
        if jitter_indep and jitter_val > 0:
            final_off += random.randint(-jitter_val, jitter_val)
            
        if orientation == "Orizzontale":
            strip = source[start_p:end_p, :]
            out_frame[start_p:end_p, :] = np.roll(strip, final_off, axis=1)
        else:
            strip = source[:, start_p:end_p]
            out_frame[:, start_p:end_p] = np.roll(strip, final_off, axis=0)
            
    return out_frame

# --- 2. NORMALIZZAZIONE FORMATI (BYPASS MOVIEPY RESIZE) ---
def normalize_clip(clip, aspect_ratio):
    target_h = 720
    if aspect_ratio == "1:1": target_w = 720
    elif aspect_ratio == "16:9": target_w = 1280
    else: target_w = 405 # 9:16
    
    # Usiamo OpenCV per il ridimensionamento: è 10x più veloce e non ha bug di Pillow
    def resizer(pic):
        return cv2.resize(pic, (target_w, target_h), interpolation=cv2.INTER_AREA)
    
    # Applichiamo il ridimensionamento frame per frame
    c_res = clip.fl_image(resizer)
    
    # Ritaglio centrale chirurgico per far combaciare i pixel
    return c_res.crop(x_center=target_w/2, y_center=target_h/2, width=target_w, height=target_h)

# --- 3. RENDERING MASTER ---
def run_full_render(video_paths, p):
    clips = {}
    for i, path in video_paths.items():
        try:
            clips[i] = normalize_clip(VideoFileClip(path), p['aspect'])
        except Exception as e:
            st.error(f"Errore nel caricamento del Deck {i+1}: {e}")

    duration = p['durata']
    fps = 24
    state = {'last_tick': -1.0, 'current_map': None, 'next_tick_dur': 0}

    def make_frame(t):
        # A. LOGICA RITMO (Stutter)
        if t - state['last_tick'] >= state['next_tick_dur'] or state['current_map'] is None:
            # Determiniamo la dimensione su cui tagliare
            dim = 720 if p['orient'] == "Orizzontale" else clips[next(iter(clips))].w
            
            new_map = []
            curr = 0
            while curr < dim:
                thick = random.randint(p['thick'][0], p['thick'][1])
                end = int(min(curr + thick, dim))
                new_map.append((curr, end))
                curr = end
            state['current_map'] = new_map
            state['last_tick'] = t
            state['next_tick_dur'] = random.uniform(p['ritmo'][0], p['ritmo'][1])

        # B. CALCOLO EVOLUZIONE
        prog = min(t / duration, 1.0)
        w1 = p['d1_s'] + (p['d1_e'] - p['d1_s']) * prog
        w2 = p['d2_s'] + (p['d2_e'] - p['d2_s']) * prog
        weights = {i: 0 for i in range(4)}
        weights[0], weights[1] = w1, w2
        weights[2], weights[3] = p['d3_w'], p['d4_w']
        
        # Filtriamo solo i pesi dei deck effettivamente caricati
        final_weights = [weights[i] for i in clips.keys()]
        
        curr_off = int(p['off_s'] + (p['off_e'] - p['off_s']) * prog)
        
        # C. ESTRAZIONE FRAME
        deck_frames = {i: c.get_frame(t % c.duration) for i, c in clips.items()}
        
        return apply_glitch_core(deck_frames, weights, state['current_map'], 
                                 curr_off, p['jitter'], p['j_indep'], p['orient'])

    final_clip = VideoClip(make_frame, duration=duration).set_fps(fps)
    
    # Audio dal Deck 1 (se presente)
    if 0 in clips and clips[0].audio:
        final_clip = final_clip.set_audio(clips[0].audio.subclip(0, min(duration, clips[0].duration)))

    out_p = os.path.join(tempfile.gettempdir(), "render_final.mp4")
    final_clip.write_videofile(out_p, codec="libx264", audio_codec="aac", preset="ultrafast", logger=None)
    
    for c in clips.values(): c.close()
    return out_p

# --- 4. INTERFACCIA ---
def main():
    st.set_page_config(layout="wide", page_title="Glitch V3 Final")
    st.title("📟 GLITCH ENGINE V3: FINAL SURGERY")

    col1, col2 = st.columns(2)

    with col1:
        st.header("🎬 Regia")
        v_files = [st.file_uploader(f"Video Deck {i+1}", type=["mp4","mov"]) for i in range(4)]
        ritmo = st.slider("Ritmo Stutter (sec)", 0.05, 1.0, (0.20, 0.40))
        aspect = st.selectbox("Formato Schermo", ["16:9", "1:1", "9:16"])
        
        st.subheader("Automazione Presenza %")
        d1_se = st.slider("Deck 1 (Inizio/Fine)", 0, 100, (100, 0))
        d2_se = st.slider("Deck 2 (Inizio/Fine)", 0, 100, (0, 100))
        d3_w = st.slider("Deck 3 Rumore %", 0, 100, 15)
        d4_w = st.slider("Deck 4 Rumore %", 0, 100, 5)

    with col2:
        st.header("⚡ Distruzione")
        orient = st.radio("Direzione Tagli", ["Orizzontale", "Verticale"])
        thick = st.slider("Spessore Strisce (Min/Max px)", 1, 500, (5, 28))
        
        st.subheader("Spostamento & Jitter")
        off_se = st.slider("Offset Pixel (Inizio/Fine)", 0, 1000, (0, 250))
        jitter = st.slider("Intensità Tremore (Jitter)", 0, 150, 40)
        j_indep = st.toggle("Tremore Indipendente", value=True)
        durata = st.number_input("Durata Totale (sec)", 1, 300, 10)

    if st.button("🚀 GENERA VIDEO"):
        paths = {}
        for i, f in enumerate(v_files):
            if f:
                t = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
                t.write(f.read())
                paths[i] = t.name
        
        if len(paths) < 2:
            st.error("Carica almeno i primi 2 Deck!")
        else:
            p = {
                'durata': durata, 'ritmo': ritmo, 'aspect': aspect, 'orient': orient,
                'd1_s': d1_se[0], 'd1_e': d1_se[1], 'd2_s': d2_se[0], 'd2_e': d2_se[1],
                'd3_w': d3_w, 'd4_w': d4_w, 'thick': thick, 'rand': True,
                'off_s': off_se[0], 'off_e': off_se[1], 'jitter': jitter, 'j_indep': j_indep
            }
            with st.spinner("Rendering..."):
                try:
                    result = run_full_render(paths, p)
                    st.video(result)
                    with open(result, "rb") as f:
                        st.download_button("📥 Scarica Master", f, "glitch_final.mp4")
                except Exception as e:
                    st.error(f"Errore durante il rendering: {e}")

if __name__ == "__main__":
    main()
