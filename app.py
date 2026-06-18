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
    # Preserva l'estensione originale del file (mp3/wav) invece di forzare .mp3
    orig_name = getattr(audio_file, "name", "") or ""
    suffix = os.path.splitext(orig_name)[1].lower()
    if suffix not in (".mp3", ".wav"):
        suffix = ".mp3"

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as t:
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
        first_key = next(iter(self.video_clips))
        return self.video_clips[first_key].size

    def close_sources(self):
        """Chiude tutti i VideoFileClip sorgente per liberare handle/processi ffmpeg."""
        for clip in self.video_clips.values():
            try:
                clip.close()
            except Exception:
                pass
        self.video_clips = {}

    def generate_fixed_quota(self, quotas, r_a, r_b, r_rand, duration, fps,
                              s_a, s_b, s_rand, scan_dir, p_bar, use_scan,
                              beat_times=None, rms_envelope=None):
        """Modalita' Quote Fisse: ogni sorgente contribuisce esattamente la sua
        percentuale di secondi. I tagli dentro ogni sorgente restano completamente
        random (con filtro anti-ripetizione). I frammenti vengono poi mischiati
        prima di concatenare, cosi' non appaiono tutti in blocco per sorgente."""

        keys = list(self.video_clips.keys())
        target_size = self.video_clips[keys[0]].size
        self.stats["fragments"] = 0

        # Normalizza le quote in modo che sommino a 1.0
        total_q = sum(quotas.get(k, 0) for k in keys)
        if total_q == 0:
            norm = {k: 1 / len(keys) for k in keys}
        else:
            norm = {k: quotas.get(k, 0) / total_q for k in keys}

        # Calcola i secondi assegnati a ciascuna sorgente
        time_budget = {k: norm[k] * duration for k in keys}

        recent_cuts  = {k: [] for k in keys}
        RECENT_WINDOW    = 15
        MAX_CLOSE_REPEATS = 2
        MAX_RETRIES      = 8

        all_clips = []

        for k in keys:
            budget   = time_budget[k]
            source   = self.video_clips[k]
            spent    = 0.0
            progress = 0.0

            while spent < budget:
                remaining = budget - spent
                if r_rand:
                    seg_dur = random.uniform(min(r_a, r_b), max(r_a, r_b))
                else:
                    seg_dur = r_a + (r_b - r_a) * progress

                seg_dur = min(seg_dur, remaining)  # non sforare il budget
                if seg_dur < 0.05:
                    break

                proximity = max(1.0, seg_dur * 1.5)
                max_start = max(0, source.duration - seg_dur)

                start_p  = random.uniform(0, max_start)
                attempts = 0
                while attempts < MAX_RETRIES:
                    close_count = sum(1 for s in recent_cuts[k] if abs(s - start_p) < proximity)
                    if close_count < MAX_CLOSE_REPEATS:
                        break
                    start_p  = random.uniform(0, max_start)
                    attempts += 1

                recent_cuts[k].append(start_p)
                if len(recent_cuts[k]) > RECENT_WINDOW:
                    recent_cuts[k].pop(0)

                clip = source.subclip(start_p, start_p + seg_dur).resize(newsize=target_size).set_fps(fps)
                all_clips.append(clip)
                spent   += seg_dur
                progress = spent / budget
                self.stats["fragments"] += 1
                p_bar.progress(min(self.stats["fragments"] / max(1, int(duration / r_a)) * 0.4, 0.4),
                               text=f"Composizione: {self.stats['fragments']} pezzi")

        # Mescola i frammenti cosi' non appaiono in blocchi monolitici per sorgente
        random.shuffle(all_clips)

        final = concatenate_videoclips(all_clips, method="chain").set_duration(duration)
        if use_scan:
            _rms = rms_envelope
            final = final.fl(lambda gf, t: apply_procedural_slit_scan(
                gf, t, final.duration, s_a, s_b, s_rand, scan_dir, _rms
            ))
        return final

    def generate(self, weights, r_a, r_b, r_rand, duration, fps,
                 s_a, s_b, s_rand, scan_dir, p_bar, use_scan,
                 beat_times=None, rms_envelope=None):
        curr_t = 0
        clips = []
        # FIX: usare le chiavi reali dei video caricati, non range(len(...)).
        # Se l'utente carica ad es. solo Video 1 e Video 3, le chiavi sono {0, 2}
        # e non {0, 1}: iterare su range(len(video_clips)) causava un KeyError
        # su weights[1], inesistente.
        keys = list(self.video_clips.keys())
        target_size = self.video_clips[keys[0]].size
        self.stats["fragments"] = 0
        beat_idx = 0  # indice corrente nella lista beat_times

        # --- ANTI-RIPETIZIONE TAGLI ---
        # Il random puro su start_p tende a ripescare zone vicine quando i video
        # sorgente sono corti e i frammenti tanti (legge dei grandi numeri).
        # Qui non eliminiamo il random: permettiamo che un taglio "torni" al
        # massimo una volta in una finestra recente, ma se starebbe per ripetersi
        # una terza volta lo rifiutiamo e ne peschiamo un altro.
        recent_cuts = {k: [] for k in keys}   # start_p usati di recente, per sorgente
        RECENT_WINDOW = 15                    # quanti tagli recenti tenere in memoria per sorgente
        MAX_CLOSE_REPEATS = 2                 # quante volte un taglio "vicino" e' tollerato
        MAX_RETRIES = 8                       # tentativi massimi prima di accettare comunque

        while curr_t < duration:
            progress = curr_t / duration

            if beat_times and len(beat_times) > 0:
                # Taglio sul prossimo beat disponibile
                while beat_idx < len(beat_times) and beat_times[beat_idx] <= curr_t:
                    beat_idx += 1
                if beat_idx < len(beat_times):
                    seg_dur = max(r_a, beat_times[beat_idx] - curr_t)
                else:
                    # Beat terminati prima della fine del video: fallback
                    # sul ritmo manuale (random o lineare) per il resto della durata.
                    seg_dur = random.uniform(min(r_a, r_b), max(r_a, r_b)) if r_rand else r_a
            elif r_rand:
                seg_dur = random.uniform(min(r_a, r_b), max(r_a, r_b))
            else:
                seg_dur = r_a + (r_b - r_a) * progress

            w_list = [weights[k][0] + (weights[k][1] - weights[k][0]) * progress
                      for k in keys]
            if sum(w_list) == 0: w_list = [1] * len(w_list)

            v_idx = random.choices(keys, weights=w_list, k=1)[0]
            source = self.video_clips[v_idx]

            # Soglia di "vicinanza" tra due tagli: proporzionale alla durata
            # del frammento corrente, con un minimo di 1s per non essere troppo
            # permissivi su segmenti molto brevi.
            proximity = max(1.0, seg_dur * 1.5)
            max_start = max(0, source.duration - seg_dur)

            start_p = random.uniform(0, max_start)
            attempts = 0
            while attempts < MAX_RETRIES:
                close_count = sum(1 for s in recent_cuts[v_idx] if abs(s - start_p) < proximity)
                if close_count < MAX_CLOSE_REPEATS:
                    break
                start_p = random.uniform(0, max_start)
                attempts += 1

            recent_cuts[v_idx].append(start_p)
            if len(recent_cuts[v_idx]) > RECENT_WINDOW:
                recent_cuts[v_idx].pop(0)

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
        st.divider()
        audio_file = st.file_uploader("Audio (mp3/wav)", type=["mp3","wav"])

    c1, c2, c3 = st.columns(3)
    weights  = {}
    quotas   = {}

    with c1:
        st.subheader("Mix Video")
        loaded    = [i for i in range(4) if files[i]]
        mix_mode  = st.radio("Modalità Mix", ["Random", "Quote Fisse"],
                             horizontal=True, label_visibility="collapsed")
        st.caption("**Random** = probabilità per frammento  |  **Quote Fisse** = secondi garantiti per sorgente")
        st.markdown("---")

        default_quota = round(100 / len(loaded)) if loaded else 25

        for i in range(4):
            if files[i]:
                st.write(f"**V{i+1}: {files[i].name[:12]}**")
                if mix_mode == "Random":
                    s, e = st.columns(2)
                    ws = s.slider("Start %", 0, 100, 100 if i==0 else 0, key=f"ws{i}")
                    we = e.slider("End %",   0, 100, 0 if i==0 else 100, key=f"we{i}")
                    weights[i] = (ws, we)
                else:
                    q = st.slider("Quota %", 0, 100, default_quota, key=f"wq{i}")
                    quotas[i] = q

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
        # AUDIO SYNC — toggle + uploader + scelta traccia
        beat_sync = st.toggle("A tempo di musica", value=False,
            help="Carica un audio: i tagli seguiranno i beat e le strisce seguiranno il volume.")
        use_custom_audio = False
        if beat_sync and audio_file:
            audio_choice = st.radio(
                "Traccia audio nel video finale",
                ["Audio originale dei video", "Usa la musica caricata"],
                index=0
            )
            use_custom_audio = (audio_choice == "Usa la musica caricata")

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
            engine        = None
            tmp_audio_path = None

            try:
                # Analisi audio — una tantum prima del rendering
                if beat_sync and audio_file:
                    p_bar.progress(0.05, text="Analisi audio...")
                    beat_times, rms_envelope = analyze_audio(audio_file, durata)
                    beat_count = len(beat_times)

                engine = VideoEngine()
                engine.load_sources(paths)

                if mix_mode == "Quote Fisse":
                    final = engine.generate_fixed_quota(
                        quotas, r_a, r_b, r_rand, durata, fps,
                        s_a, s_b, s_rand, scan_dir, p_bar, use_scan,
                        beat_times=beat_times, rms_envelope=rms_envelope
                    )
                else:
                    final = engine.generate(
                        weights, r_a, r_b, r_rand, durata, fps,
                        s_a, s_b, s_rand, scan_dir, p_bar, use_scan,
                        beat_times=beat_times, rms_envelope=rms_envelope
                    )

                # Sostituisce traccia audio se richiesto
                if beat_sync and audio_file and use_custom_audio:
                    from moviepy.editor import AudioFileClip
                    from moviepy.audio.fx.all import audio_loop
                    audio_file.seek(0)
                    tmp_audio = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
                    tmp_audio.write(audio_file.read())
                    tmp_audio.close()
                    tmp_audio_path = tmp_audio.name
                    audio_clip = AudioFileClip(tmp_audio_path)
                    if audio_clip.duration < durata:
                        audio_clip = audio_loop(audio_clip, duration=durata)
                    else:
                        audio_clip = audio_clip.set_duration(durata)
                    final = final.set_audio(audio_clip)

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

                # Descrizione mix per il report
                if mix_mode == "Quote Fisse":
                    mix_log = "Quote Fisse — " + " / ".join(
                        f"V{k+1}:{quotas.get(k,0)}%" for k in paths.keys()
                    )
                else:
                    mix_log = "Random (pesi Start%/End%)"

                st.session_state.video_path   = out_v
                st.session_state.preview_path = prev_v
                st.session_state.report_data  = f"""[DECOMP_ARCHIVE] // VOL_01 // H.264 // AAC
:: STILE: Minimalismo Computazionale / Glitch Brutalista
:: MOTORE: video_decomposed [01.03]
:: AUDIO: 48 kHz / Float a 32 bit / Punto di Clipping
:: PROCESSO: Collasso Ricorsivo

> TECHNICAL LOG SHEET:
* Sorgenti Video: {engine.stats['sources']}
* Frammenti Generati: {engine.stats['fragments']}
* Mix: {mix_log}
* Ritmo: {r_a}s >> {r_b}s (Random: {r_rand})
* Strisce: {s_a}px >> {s_b}px (Random: {s_rand})
* Geometria: {scan_dir}
{'* Beat Sync: ON — ' + str(beat_count) + ' beat rilevati' if beat_sync and audio_file else ''}

"Non e' montaggio. E' anatomia di un segnale corrotto."

> Regia e Algoritmo: Loop507

#loop507 #datanoise #decomposition #glitchart #audiovisual #noisemusic #algorithmicvideo #brutalist #sounddesign #computationalminimalism #signalcorruption #recursivecollapse #newmediaart
"""
                st.session_state.video_ready = True

            except Exception as e:
                st.error(f"Errore: {e}")

            finally:
                # Pulizia risorse: chiude i VideoFileClip sorgente e rimuove
                # i file temporanei creati per questo render (sorgenti caricate
                # e audio custom). video.mp4/preview.mp4 NON vengono toccati:
                # restano su disco perche' servono ai download_button successivi.
                if engine is not None:
                    engine.close_sources()
                for p in paths.values():
                    try:
                        os.remove(p)
                    except OSError:
                        pass
                if tmp_audio_path:
                    try:
                        os.remove(tmp_audio_path)
                    except OSError:
                        pass

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
