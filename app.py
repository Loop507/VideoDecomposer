import streamlit as st
import os, random, tempfile, cv2, time
import numpy as np

# Importazione dinamica per massima compatibilità
try:
    from moviepy.editor import VideoFileClip, VideoClip
except ImportError:
    from moviepy.video.io.VideoFileClip import VideoFileClip
    from moviepy.video.VideoClip import VideoClip

# --- 1. MOTORE DI SCOMPOSIZIONE (OTTIMIZZATO) ---
def apply_glitch_core(deck_frames, weights, strip_map, offset_val, jitter_val, jitter_indep, orientation):
    ref_id = next(iter(deck_frames))
    ref_frame = deck_frames[ref_id]
    h, w, c = ref_frame.shape
    out_frame = np.zeros_like(ref_frame)
    
    active_ids = list(deck_frames.keys())
    block_jitter = random.randint(-jitter_val, jitter_val) if (jitter_val > 0 and not jitter_indep) else 0

    for (start_p, end_p) in strip_map:
        # Pesi dinamici: sceglie quale video mostrare in questa striscia
        w_list = [weights.get(i, 0) for i in active_ids]
        chosen_id = random.choices(active_ids, weights=w_list)[0]
        source = deck_frames[chosen_id]
        
        # Calcolo Offset + Jitter
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

# --- 2. NORMALIZZAZIONE (STABILE) ---
def normalize_clip(path, aspect_ratio):
    clip = VideoFileClip(path)
    target_h = 720
    if aspect_ratio == "1:1": target_w = 720
    elif aspect_ratio == "16:9": target_w = 1280
    else: target_w = 405 # 9:16
    
    def process_frame(pic):
        h, w, _ = pic.shape
        scale = target_h / h
        new_w = int(w * scale)
        res = cv2.resize(pic, (new_w, target_h), interpolation=cv2.INTER_AREA)
        h_res, w_res, _ = res.shape
        start_x = max(0, w_res//2 - target_w//2)
        return res[:, start_x:start_x+target_w]

    return clip.fl_image(process_frame)

# --- 3. RENDERING MASTER ---
def run_full_render(video_paths, p):
    clips = {i: normalize_clip(path, p['aspect']) for i, path in video_paths.items()}
    duration, fps = p['durata'], 24
    state = {'last_tick': -1.0, 'current_map': None, 'next_tick_dur': 0}

    def make_frame(t):
        if t - state['last_tick'] >= state['next_tick_dur'] or state['current_map'] is None:
            first_id = next(iter(clips))
            sample = clips[first_id].get_frame(0)
            dim = sample.shape[0] if p['orient'] == "Orizzontale" else sample.shape[1]
            
            new_map, curr = [], 0
            while curr < dim:
                thick = random.randint(p['thick'][0], p['thick'][1])
                end = int(min(curr + thick, dim))
                new_map.append((curr, end))
                curr = end
            state['current_map'], state['last_tick'] = new_map, t
            state['next_tick_dur'] = random.uniform(p['ritmo'][0], p['ritmo'][1])

        prog = min(t / duration, 1.0)
        w_logic = {
            0: p['d1_s'] + (p['d1_e'] - p['d1_s']) * prog,
            1: p['d2_s'] + (p['d2_e'] - p['d2_s']) * prog,
            2: p['d3_w'], 3: p['d4_w']
        }
        
        # Estrazione frame dai deck (looping automatico)
        deck_frames = {i: c.get_frame(t % c.duration) for i, c in clips.items()}
        curr_off = int(p['off_s'] + (p['off_e'] - p['off_s']) * prog)
        
        return apply_glitch_core(deck_frames, w_logic, state['current_map'], 
                                 curr_off, p['jitter'], p['j_indep'], p['orient'])

    final_clip = VideoClip(make_frame, duration=duration).set_fps(fps)
    
    # Audio dal Deck 1
    if 0 in clips and clips[0].audio:
        final_clip = final_clip.set_audio(clips[0].audio.subclip(0, min(duration, clips[0].duration)))

    out_p = os.path.join(tempfile.gettempdir(), f"render_{int(time.time())}.mp4")
    final_clip.write_videofile(out_p, codec="libx264", audio_codec="aac", preset="ultrafast", logger=None)
    
    for c in clips.values(): c.close()
    return out_p

# --- 4. INTERFACCIA ---
def main():
    st.set_page_config(layout="wide", page_title="Glitch Engine V3.3")
    st.title("📟 GLITCH MASTER V3.3")
    
    col1, col2 = st.columns(2)
    with col1:
        st.header("🎬 Regia")
        v_files = [st.file_uploader(f"Video Deck {i+1}", type=["mp4","mov"]) for i in range(4)]
        # RITMO: Min 0.01, Valore iniziale 0.10
        ritmo = st.slider("Ritmo Stutter (sec)", 0.01, 1.0, (0.10, 0.30), step=0.01)
        aspect = st.selectbox("Formato Output", ["16:9", "1:1", "9:16"])
        
        st.subheader("Automazione Deck 1 ➔ 2")
        d1_se = st.slider("Deck 1 (%)", 0, 100, (100, 0))
        d2_se = st.slider("Deck 2 (%)", 0, 100, (0, 100))
        d3_w = st.slider("Deck 3 Noise (%)", 0, 100, 15)
        d4_w = st.slider("Deck 4 Noise (%)", 0, 100, 5)
    
    with col2:
        st.header("⚡ Distorsione")
        orient = st.radio("Orientamento Tagli", ["Orizzontale", "Verticale"])
        thick = st.slider("Spessore Strisce (Min/Max px)", 1, 500, (5, 40))
        off_se = st.slider("Offset Pixel (Start ➔ End)", 0, 1000, (0, 200))
        jitter = st.slider("Intensità Jitter", 0, 150, 30)
        j_indep = st.toggle("Jitter Indipendente", value=True)
        durata = st.number_input("Durata Totale (secondi)", 1, 300, 10)

    if st.button("🚀 GENERA VIDEO"):
        paths = {}
        for i, f in enumerate(v_files):
            if f:
                t = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
                t.write(f.read())
                paths[i] = t.name
        
        if len(paths) < 2:
            st.error("Carica almeno i primi 2 Deck per iniziare!")
        else:
            p = {'durata':durata, 'ritmo':ritmo, 'aspect':aspect, 'orient':orient,
                 'd1_s':d1_se[0], 'd1_e':d1_se[1], 'd2_s':d2_se[0], 'd2_e':d2_se[1],
                 'd3_w':d3_w, 'd4_w':d4_w, 'thick':thick, 'off_s':off_se[0], 
                 'off_e':off_se[1], 'jitter':jitter, 'j_indep':j_indep}
            
            with st.spinner("Scomposizione in corso..."):
                try:
                    res = run_full_render(paths, p)
                    st.video(res)
                    with open(res, "rb") as f:
                        st.download_button("📥 Scarica Master", f, "glitch_v3.mp4")
                    # Pulizia chirurgica file temporanei
                    for p_path in paths.values(): os.unlink(p_path)
                except Exception as e:
                    st.error(f"Errore critico: {e}")

if __name__ == "__main__":
    main()
