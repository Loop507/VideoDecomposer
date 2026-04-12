import streamlit as st
import os, random, tempfile, cv2
import numpy as np

# Prova l'importazione per MoviePy 1.x e 2.x
try:
    from moviepy.editor import VideoFileClip, VideoClip
except ImportError:
    from moviepy.video.io.VideoFileClip import VideoFileClip
    from moviepy.video.VideoClip import VideoClip

# --- 1. MOTORE DI SCOMPOSIZIONE (ROBUSTO) ---
def apply_glitch_core(deck_frames, weights, strip_map, offset_val, jitter_val, jitter_indep, orientation):
    ref_id = next(iter(deck_frames))
    ref_frame = deck_frames[ref_id]
    h, w, c = ref_frame.shape
    out_frame = np.zeros_like(ref_frame)
    
    active_ids = list(deck_frames.keys())
    block_jitter = random.randint(-jitter_val, jitter_val) if (jitter_val > 0 and not jitter_indep) else 0

    for (start_p, end_p) in strip_map:
        chosen_id = random.choices(active_ids, weights=[weights[i] for i in active_ids])[0]
        source = deck_frames[chosen_id]
        
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

# --- 2. NORMALIZZAZIONE (VERSIONE ANTI-CRASH) ---
def normalize_clip(clip, aspect_ratio):
    target_h = 720
    if aspect_ratio == "1:1": target_w = 720
    elif aspect_ratio == "16:9": target_w = 1280
    else: target_w = 405 # 9:16
    
    # Ridimensionamento diretto con OpenCV (salta i bug di MoviePy/Pillow)
    def resizer(pic):
        return cv2.resize(pic, (target_w, target_h), interpolation=cv2.INTER_AREA)
    
    # Ritaglio centrale manuale su array NumPy (sicuro al 100%)
    def center_crop(pic):
        h, w, _ = pic.shape
        start_x = w//2 - target_w//2
        start_y = h//2 - target_h//2
        return pic[start_y:start_y+target_h, start_x:start_x+target_w]

    return clip.fl_image(resizer).fl_image(center_crop)

# --- 3. RENDERING MASTER ---
def run_full_render(video_paths, p):
    clips = {i: normalize_clip(VideoFileClip(path), p['aspect']) for i, path in video_paths.items()}
    duration, fps = p['durata'], 24
    state = {'last_tick': -1.0, 'current_map': None, 'next_tick_dur': 0}

    def make_frame(t):
        if t - state['last_tick'] >= state['next_tick_dur'] or state['current_map'] is None:
            # Calcolo dimensioni basato sulla prima clip caricata
            first_clip = clips[next(iter(clips))]
            dim = 720 if p['orient'] == "Orizzontale" else first_clip.w
            
            new_map, curr = [], 0
            while curr < dim:
                thick = random.randint(p['thick'][0], p['thick'][1])
                end = int(min(curr + thick, dim))
                new_map.append((curr, end))
                curr = end
            state['current_map'], state['last_tick'] = new_map, t
            state['next_tick_dur'] = random.uniform(p['ritmo'][0], p['ritmo'][1])

        prog = min(t / duration, 1.0)
        weights = {0: p['d1_s']+(p['d1_e']-p['d1_s'])*prog, 
                   1: p['d2_s']+(p['d2_e']-p['d2_s'])*prog, 
                   2: p['d3_w'], 3: p['d4_w']}
        
        # Sincronizza i pesi con i deck esistenti
        current_weights = [weights.get(i, 0) for i in clips.keys()]
        deck_frames = {i: c.get_frame(t % c.duration) for i, c in clips.items()}
        
        return apply_glitch_core(deck_frames, weights, state['current_map'], 
                                 int(p['off_s']+(p['off_e']-p['off_s'])*prog), 
                                 p['jitter'], p['j_indep'], p['orient'])

    final_clip = VideoClip(make_frame, duration=duration).set_fps(fps)
    if 0 in clips and clips[0].audio:
        final_clip = final_clip.set_audio(clips[0].audio.subclip(0, min(duration, clips[0].duration)))

    out_p = os.path.join(tempfile.gettempdir(), "render.mp4")
    final_clip.write_videofile(out_p, codec="libx264", audio_codec="aac", preset="ultrafast", logger=None)
    for c in clips.values(): c.close()
    return out_p

# --- 4. INTERFACCIA ---
def main():
    st.set_page_config(layout="wide")
    st.title("📟 GLITCH MASTER V3.1")
    col1, col2 = st.columns(2)
    with col1:
        v_files = [st.file_uploader(f"Deck {i+1}", type=["mp4","mov"]) for i in range(4)]
        ritmo = st.slider("Ritmo Stutter", 0.05, 1.0, (0.20, 0.40))
        aspect = st.selectbox("Formato", ["16:9", "1:1", "9:16"])
        d1_se = st.slider("Deck 1 Presenza", 0, 100, (100, 0))
        d2_se = st.slider("Deck 2 Presenza", 0, 100, (0, 100))
        d3_w = st.slider("Deck 3 Noise %", 0, 100, 15)
        d4_w = st.slider("Deck 4 Noise %", 0, 100, 5)
    with col2:
        orient = st.radio("Tagli", ["Orizzontale", "Verticale"])
        thick = st.slider("Spessore (Min/Max)", 1, 500, (5, 30))
        off_se = st.slider("Offset (Start/End)", 0, 1000, (0, 250))
        jitter = st.slider("Jitter", 0, 150, 40)
        j_indep = st.toggle("Indipendente", value=True)
        durata = st.number_input("Durata (sec)", 1, 300, 10)

    if st.button("🚀 GENERA"):
        paths = {i: tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") for i, f in enumerate(v_files) if f}
        for i, f in enumerate(v_files): 
            if f: paths[i].write(f.read()); paths[i] = paths[i].name
        
        if len(paths) < 2: st.error("Carica almeno 2 Deck!")
        else:
            p = {'durata':durata, 'ritmo':ritmo, 'aspect':aspect, 'orient':orient,
                 'd1_s':d1_se[0], 'd1_e':d1_se[1], 'd2_s':d2_se[0], 'd2_e':d2_se[1],
                 'd3_w':d3_w, 'd4_w':d4_w, 'thick':thick, 'off_s':off_se[0], 
                 'off_e':off_se[1], 'jitter':jitter, 'j_indep':j_indep}
            with st.spinner("Rendering..."):
                res = run_full_render(paths, p)
                st.video(res)
                st.download_button("📥 Scarica", open(res,"rb"), "glitch.mp4")

if __name__ == "__main__": main()
