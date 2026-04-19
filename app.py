import streamlit as st
import os
import random
import tempfile
import time
import numpy as np
from datetime import datetime
from moviepy.editor import VideoFileClip, concatenate_videoclips
from PIL import Image
import librosa

# --- PATCH COMPATIBILITA' ---
if hasattr(Image, 'Resampling'):
    Image.ANTIALIAS = Image.Resampling.LANCZOS
else:
    Image.ANTIALIAS = Image.LANCZOS

# --- ANALISI AUDIO ---
def analyze_audio(audio_file, duration):
    """Ritorna beat_times (list) e rms_envelope (list normalizzato 0-1)."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as t:
        t.write(audio_file.read())
        tmp_path = t.name
    try:
        y, sr = librosa.load(tmp_path, sr=22050, mono=True, duration=duration)
        _, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()
        rms = librosa.feature.rms(y=y)[0]
        rms_norm = rms / (rms.max() + 1e-6)
        total_steps = max(1, int(duration / 0.05))
        rms_envelope = np.interp(
            np.linspace(0, len(rms_norm)-1, total_steps),
            np.arange(len(rms_norm)), rms_norm
        ).tolist()
    finally:
        os.remove(tmp_path)
    return beat_times, rms_envelope

# --- MOTORE PROCEDURALE ---
def apply_procedural_slit_scan(get_frame, t, duration, val_a, val_b, is_random, scan_mode,
                                rms_envelope=None):
    frame = get_frame(t).copy()
    h, w, _ = frame.shape
    progress = t / duration

    if is_random:
        current_strand = random.uniform(min(val_a, val_b), max(val_a, val_b))
    else:
        current_strand = val_a + (val_b - val_a) * progress

    current_strand = max(1, current_strand)
    magnet_prob = 0 if progress < 0.7 else ((progress - 0.7) / 0.3) ** 2

    # Intensita' strisce modulata da RMS se disponibile
    if rms_envelope is not None:
        idx = min(int(t / 0.05), len(rms_envelope) - 1)
        intensity = 0.2 + rms_envelope[idx] * 0.8  # range 0.2-1.0
    else:
        intensity = 1.0

    c_mode = scan_mode
    if scan_mode == "Mix": c_mode = random.choice(["Orizzontale", "Verticale"])

    if c_mode == "Orizzontale":
        current_y = 0
        while current_y < h:
            strand_h = int(random.uniform(current_strand * 0.5, current_strand * 2))
            next_y = min(current_y + strand_h, h)
            if random.random() > magnet_prob:
                offset = int(random.uniform(-w, w) * np.sin(np.pi * progress) * intensity)
                frame[current_y:next_y, :] = np.roll(frame[current_y:next_y, :], offset, axis=1)
            current_y = next_y
    else:
        current_x = 0
        while current_x < w:
            strand_w = int(random.uniform(current_strand * 0.5, current_strand * 2))
            next_x = min(current_x + strand_w, w)
            if random.random() > magnet_prob:
                offset = int(random.uniform(-h, h) * np.sin(np.pi * progress) * intensity)
                frame[:, current_x:next_x] = np.roll(frame[:, current_x:next_x], offset, axis=0)
            current_x = next_x
    return frame

# --- LOGICA DI MONTAGGIO ---
class VideoEngine:
    def __init__(self):
        self.video_clips = {}
        self.stats = {"fragments": 0, "sources": 0}

    def load_sources(self, paths):
        for i, p in paths.items():
            self.video_clips[i] = VideoFileClip(p)
        self.stats["sources"] = len(self.video_clips)
        return self.video_clips[next(iter(self.video_clips))].size

    def generate(self, weights, r_a, r_b, r_rand, duration, fps,
                 s_a, s_b, s_rand, scan_dir, p_bar, use_scan,
                 beat_times=None, rms_envelope=None):
        curr_t = 0
        clips = []
        target_size = self.video_clips[next(iter(self.video_clips))].size
        self.stats["fragments"] = 0
        beat_idx = 0  # indice corrente nella lista beat_times

        while curr_t < duration:
            progress = curr_t / duration

            if beat_times and len(beat_times) > 0:
                # Taglio sul prossimo beat disponibile
                while beat_idx < len(beat_times) and beat_times[beat_idx] <= curr_t:
                    beat_idx += 1
                if beat_idx < len(beat_times):
                    seg_dur = max(r_a, beat_times[beat_idx] - curr_t)
                else:
                    seg_dur = r_a
            elif r_rand:
                seg_dur = random.uniform(min(r_a, r_b), max(r_a, r_b))
            else:
                seg_dur = r_a + (r_b - r_a) * progress

            w_list = [weights[i][0] + (weights[i][1] - weights[i][0]) * progress
                      for i in range(len(self.video_clips))]
            if sum(w_list) == 0: w_list = [1] * len(w_list)

            v_idx = random.choices(list(self.video_clips.keys()), weights=w_list, k=1)[0]
            source = self.video_clips[v_idx]

            start_p = random.uniform(0, max(0, source.duration - seg_dur))
            clip = source.subclip(start_p, start_p + seg_dur).resize(newsize=target_size).set_fps(fps)
            clips.append(clip)
            curr_t += seg_dur
            self.stats["fragments"] += 1
            p_bar.progress(min(curr_t / duration * 0.4, 0.4),
                           text=f"Composizione: {self.stats['fragments']} pezzi")

        final = concatenate_videoclips(clips, method="chain").set_duration(duration)
        if use_scan:
            _rms = rms_envelope  # closure
            final = final.fl(lambda gf, t: apply_procedural_slit_scan(
                gf, t, final.duration, s_a, s_b, s_rand, scan_dir, _rms
            ))
        return final

# --- INTERFACCIA ---
def main():
    st.set_page_config(page_title="VideoDecomposer PRO", layout="wide")
    st.title("VideoDecomposer: Rendering & Report")

    if 'video_ready'   not in st.session_state: st.session_state.video_ready   = False
    if 'report_data'   not in st.session_state: st.session_state.report_data   = ""
    if 'video_path'    not in st.session_state: st.session_state.video_path    = ""
    if 'preview_path'  not in st.session_state: st.session_state.preview_path  = ""

    with st.sidebar:
        st.header("Sorgenti")
        files = [st.file_uploader(f"Video {i+1}", type=["mp4","mov"]) for i in range(4)]

    c1, c2, c3 = st.columns(3)
    weights = {}

    with c1:
        st.subheader("Mix Video")
        for i in range(4):
            if files[i]:
                st.write(f"**V{i+1}: {files[i].name[:12]}**")
                s, e = st.columns(2)
                ws = s.slider("Start %", 0, 100, 100 if i==0 else 0, key=f"ws{i}")
                we = e.slider("End %",   0, 100, 0 if i==0 else 100, key=f"we{i}")
                weights[i] = (ws, we)

    with c2:
        st.subheader("Ritmo e Strisce")
        r_rand = st.toggle("Ritmo Random")
        r_col1, r_col2 = st.columns(2)
        r_a = r_col1.number_input("Inizio/Min (s)", 0.05, 5.0, 0.2)
        r_b = r_col2.number_input("Fine/Max (s)",   0.05, 5.0, 1.0)

        st.markdown("---")
        use_scan = st.checkbox("ATTIVA STRISCE", value=True)
        s_rand   = st.toggle("Spessore Random", disabled=not use_scan)
        s_col1, s_col2 = st.columns(2)
        s_a = s_col1.number_input("Inizio/Min (px)", 1, 300, 10, disabled=not use_scan)
        s_b = s_col2.number_input("Fine/Max (px)",   1, 300, 80, disabled=not use_scan)
        scan_dir = st.selectbox("Asse", ["Orizzontale", "Verticale", "Mix"], disabled=not use_scan)

    with c3:
        st.subheader("Esportazione")
        durata = st.number_input("Durata Totale (s)", 5, 300, 15)
        fps    = st.selectbox("FPS", [24, 30])

        st.markdown("---")
        # AUDIO SYNC — toggle + uploader
        beat_sync = st.toggle("A tempo di musica", value=False,
            help="Carica un audio: i tagli seguiranno i beat e le strisce seguiranno il volume.")
        audio_file = None
        if beat_sync:
            audio_file = st.file_uploader("Audio (mp3/wav)", type=["mp3","wav"])

        st.markdown("---")

        if st.button("AVVIA RENDERING", use_container_width=True):
            paths = {i: tempfile.NamedTemporaryFile(delete=False, suffix='.mp4').name
                     for i, f in enumerate(files) if f}
            for i, f in enumerate(files):
                if f:
                    with open(paths[i], "wb") as tf: tf.write(f.read())

            if not paths:
                st.error("Carica almeno un video!")
                return

            p_bar = st.progress(0, text="Avvio...")
            beat_times    = None
            rms_envelope  = None
            beat_count    = 0

            try:
                # Analisi audio — una tantum prima del rendering
                if beat_sync and audio_file:
                    p_bar.progress(0.05, text="Analisi audio...")
                    beat_times, rms_envelope = analyze_audio(audio_file, durata)
                    beat_count = len(beat_times)

                engine = VideoEngine()
                engine.load_sources(paths)
                final = engine.generate(
                    weights, r_a, r_b, r_rand, durata, fps,
                    s_a, s_b, s_rand, scan_dir, p_bar, use_scan,
                    beat_times=beat_times, rms_envelope=rms_envelope
                )

                # Scrittura video finale
                out_v = os.path.join(tempfile.gettempdir(), f"render_{random.randint(0,9999)}.mp4")
                p_bar.progress(0.75, text="Scrittura video...")
                final.write_videofile(out_v, codec="libx264", audio_codec="aac",
                                      preset="ultrafast", logger=None)
                time.sleep(1.5)

                # Preview ridotta a 480p
                p_bar.progress(0.90, text="Generando preview...")
                prev_v = os.path.join(tempfile.gettempdir(), f"preview_{random.randint(0,9999)}.mp4")
                prev_clip = final.resize(height=480)
                prev_clip.write_videofile(prev_v, codec="libx264", audio_codec="aac",
                                          preset="ultrafast", logger=None)
                prev_clip.close()
                final.close()
                time.sleep(0.5)
                p_bar.progress(1.0, text="Pronto!")

                st.session_state.video_path   = out_v
                st.session_state.preview_path = prev_v
                st.session_state.report_data  = f"""[DECOMP_ARCHIVE] // VOL_01 // H.264 // AAC
:: STILE: Minimalismo Computazionale / Glitch Brutalista
:: MOTORE: video_decomposed [01.02]
:: AUDIO: 48 kHz / Float a 32 bit / Punto di Clipping
:: PROCESSO: Collasso Ricorsivo

> TECHNICAL LOG SHEET:
* Sorgenti Video: {engine.stats['sources']}
* Frammenti Generati: {engine.stats['fragments']}
* Ritmo: {r_a}s >> {r_b}s (Random: {r_rand})
* Strisce: {s_a}px >> {s_b}px (Random: {s_rand})
* Geometria: {scan_dir}
* Beat Sync: {'ON — ' + str(beat_count) + ' beat rilevati' if beat_sync and audio_file else 'OFF'}

"Non e' montaggio. E' anatomia di un segnale corrotto."

> Regia e Algoritmo: Loop507

#loop507 #datanoise #decomposition #glitchart #audiovisual #noisemusic #algorithmicvideo #brutalist #sounddesign #computationalminimalism #signalcorruption #recursivecollapse #newmediaart
"""
                st.session_state.video_ready = True

            except Exception as e:
                st.error(f"Errore: {e}")

        # RISULTATI
        if st.session_state.video_ready:
            st.markdown("---")
            st.caption("Preview (480p) — scarica per la versione completa")
            if st.session_state.preview_path and os.path.exists(st.session_state.preview_path):
                st.video(st.session_state.preview_path)

            c_d1, c_d2 = st.columns(2)
            with c_d1:
                if st.session_state.video_path and os.path.exists(st.session_state.video_path):
                    with open(st.session_state.video_path, "rb") as f:
                        st.download_button("Scarica Video (qualita' piena)", f,
                                           "video.mp4", key="down_v")
            with c_d2:
                st.download_button("Scarica Report", st.session_state.report_data,
                                   "report.txt", key="down_t")

if __name__ == "__main__":
    main()
