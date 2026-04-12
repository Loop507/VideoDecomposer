import streamlit as st
import os, random, tempfile, cv2, time
import numpy as np

# --- 1. IMPORTAZIONE SICURA ---
try:
    from moviepy.video.io.VideoFileClip import VideoFileClip
    from moviepy.video.VideoClip import VideoClip
    from moviepy.audio.AudioClip import AudioClip
except ImportError:
    from moviepy.editor import VideoFileClip, VideoClip, AudioClip

# --- 2. FUNZIONE PER RIEMPIRE LO SCHERMO (NO BARRE NERE) ---
def get_frame_fill(clip, t, target_w, target_h):
    frame = clip.get_frame(t % clip.duration)
    h, w, _ = frame.shape
    scale = max(target_w / w, target_h / h)
    nw, nh = int(w * scale), int(nh * scale) if 'nh' in locals() else int(h * scale)
    # Ridimensiona e taglia al centro
    img_res = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    sy, sx = (img_res.shape[0] - target_h) // 2, (img_res.shape[1] - target_w) // 2
    return img_res[sy:sy+target_h, sx:sx+target_w]

# --- 3. MOTORE DI RENDERING (BASATO SU APP 222.PY) ---
def render_engine(video_paths, p):
    clips = {i: VideoFileClip(path) for i, path in video_paths.items()}
    tw, th = p['size']
    duration = p['durata']
    
    # Stato per sincronizzare tutto
    state = {'last_t': -1.0, 'grid': None, 'next_step': 0, 'active_id': 0}

    def make_frame(t):
        # Gestione sicura del Ritmo (Fix errore len)
        r = p['ritmo']
        min_r, max_r = (r[0], r[1]) if isinstance(r, (list, tuple)) else (r, r)
        
        # Se è ora di cambiare "taglio"
        if t - state['last_t'] >= state['next_step'] or state['grid'] is None:
            state['last_t'] = t
            state['next_step'] = random.uniform(min_r, max_r)
            
            # Griglia per le strisce
            dim = th if p['orient'] == "Orizzontale" else tw
            new_grid, curr = [], 0
            while curr < dim:
                thick = random.randint(p['thick'][0], p['thick'][1])
                new_grid.append((curr, int(min(curr + thick, dim))))
                curr = int(min(curr + thick, dim))
            state['grid'] = new_grid
            
            # Scelta deck dominante (Audio + Video se strisce OFF)
            prog = t / duration
            w = [p['d1_s']+(p['d1_e']-p['d1_s'])*prog, p['d2_s']+(p['d2_e']-p['d2_s'])*prog, 10, 5]
            state['active_id'] = random.choices(list(clips.keys()), weights=[w[i] for i in clips.keys()])[0]

        # Carica i frame correnti (con FILL)
        frames = {i: get_frame_fill(c, t, tw, th) for i, c in clips.items()}

        if not p['usa_strisce']:
            return frames[state['active_id']]
        
        # Logica Strisce
        out = np.zeros((th, tw, 3), dtype=np.uint8)
        for (s, e) in state['grid']:
            prog = t / duration
            w = [p['d1_s']+(p['d1_e']-p['d1_s'])*prog, p['d2_s']+(p['d2_e']-p['d2_s'])*prog, 10, 5]
            cid = random.choices(list(clips.keys()), weights=[w[i] for i in clips.keys()])[0]
            if p['orient'] == "Orizzontale": out[s:e, :] = frames[cid][s:e, :]
            else: out[:, s:e] = frames[cid][:, s:e]
        return out

    def make_audio(t_array):
        samples = np.zeros
