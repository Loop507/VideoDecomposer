import streamlit as st
import os
import random
import tempfile
import time
import numpy as np
from datetime import datetime
import bisect
from moviepy.editor import VideoFileClip, concatenate_videoclips, ImageClip, CompositeVideoClip
from PIL import Image
import librosa

# --- PATCH COMPATIBILITA' ---
if hasattr(Image, 'Resampling'):
    Image.ANTIALIAS = Image.Resampling.LANCZOS
else:
    Image.ANTIALIAS = Image.LANCZOS

# --- ANALISI AUDIO ---
def analyze_audio(audio_file, duration):
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

# --- MOTORE PROCEDURALE (slit scan) ---
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
    if rms_envelope is not None:
        idx = min(int(t / 0.05), len(rms_envelope) - 1)
        intensity = 0.2 + rms_envelope[idx] * 0.8
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

# ---------------------------------------------------------------------------
# REMIX DJ — genera sequenza slice/loop in stile CDJ
# ---------------------------------------------------------------------------
def generate_dj_remix(video_clips, duration, fps, slice_dur, loop_reps,
                      stutter_prob, pitch_glitch, p_bar,
                      beat_slice_mode=False, beat_times=None,
                      crossfade_dur=0.0, freeze_on_beat=False,
                      freeze_prob=0.0, freeze_dur=0.15,
                      source_mode="random", source_weights=None,
                      no_repeat=False):
    """
    VJ Mode:
    - slice_dur       : durata base di ogni slice (manuale, es. 0.1 ... 2.0 s)
    - loop_reps       : quante volte ogni slice viene loopata in modalita' stutter
    - stutter_prob    : probabilita' [0-1] che uno slice sia stutterato
    - pitch_glitch    : se True, alcuni slice vengono speed-warpati
    - beat_slice_mode : se True, usa i beat come punti di taglio invece di slice_dur fisso
    - beat_times      : lista di timestamp beat (da analyze_audio)
    - crossfade_dur   : durata in secondi del crossfade tra slice consecutive (0 = taglio secco)
    - freeze_on_beat  : se True, alcune slice iniziano con un freeze-frame
    - freeze_prob     : probabilita' [0-1] che una slice abbia il freeze-frame
    - freeze_dur      : durata in secondi del freeze-frame
    - source_mode     : "random" (puro caso, comportamento storico) oppure "pesata"
                        (usa source_weights per favorire alcune sorgenti)
    - source_weights  : dict {key: peso} usato quando source_mode == "pesata"
    - no_repeat       : se True, vieta che la stessa sorgente venga scelta
                        due slice consecutive di fila (comportamento "4 deck VJ")

    Anti-ripetizione v3: sistema bucket — distribuisce i tagli uniformemente
    nelle zone del sorgente, funziona bene sia su clip corti che su lunghi (50s+).
    """
    keys = list(video_clips.keys())
    target_size = video_clips[keys[0]].size
    all_clips = []
    total_fragments = 0
    curr_t = 0.0

    # Bucket anti-ripetizione per VJ Mode (stesso sistema del VideoEngine)
    recent_cuts = {}
    last_k = [None]  # mutabile, per tracciare l'ultima sorgente usata (no_repeat)

    def pick_source_key():
        candidates = keys
        if no_repeat and len(keys) > 1 and last_k[0] is not None:
            candidates = [kk for kk in keys if kk != last_k[0]]
        if source_mode == "pesata" and source_weights:
            w = [max(0.0001, source_weights.get(kk, 1.0)) for kk in candidates]
            chosen = random.choices(candidates, weights=w, k=1)[0]
        else:
            chosen = random.choice(candidates)
        last_k[0] = chosen
        return chosen

    def pick_start_dj(source, k, seg):
        max_start = max(0.0, source.duration - seg)
        if max_start < 0.01:
            return 0.0
        n_buckets = max(8, int(source.duration / max(0.5, seg)))
        n_buckets = min(n_buckets, 40)
        bucket_key = f"_b_{k}"
        if bucket_key not in recent_cuts or len(recent_cuts[bucket_key]) != n_buckets:
            recent_cuts[bucket_key] = [0] * n_buckets
        counts = recent_cuts[bucket_key]
        bucket_size = max_start / n_buckets
        min_v = min(counts)
        # Rotazione esatta: solo i bucket con il minimo assoluto di visite
        candidates = [i for i, c in enumerate(counts) if c == min_v]
        chosen = random.choice(candidates)
        s = random.uniform(chosen * bucket_size, min(chosen * bucket_size + bucket_size, max_start))
        counts[chosen] += 1
        return s

    # Costruisce la lista di durate slice: beat-driven o fissa
    if beat_slice_mode and beat_times and len(beat_times) > 1:
        # Durate slice = intervalli tra beat consecutivi, ciclati per coprire 'duration'
        beat_intervals = [beat_times[i+1] - beat_times[i] for i in range(len(beat_times)-1)]
        # Filtra intervalli anomali (< 0.05s o > 4s)
        beat_intervals = [d for d in beat_intervals if 0.05 <= d <= 4.0]
        if not beat_intervals:
            beat_intervals = [slice_dur]
        slice_schedule = []
        t = 0.0
        bi = 0
        while t < duration:
            d = beat_intervals[bi % len(beat_intervals)]
            slice_schedule.append(min(d, duration - t))
            t += d
            bi += 1
    else:
        # Slice fissa: costruisce lista uniforme
        n = max(1, int(duration / slice_dur)) + 2
        slice_schedule = [slice_dur] * n

    estimated = max(1, len(slice_schedule))
    sched_idx = 0

    # Beat reali ordinati, per ancorare il freeze-frame al tempo della musica
    # (funziona sia su beat fitti/regolari come la techno sia su beat piu'
    # radi/irregolari come la musica classica, perche' si basa sui beat
    # effettivamente rilevati da analyze_audio, non su una probabilita' a caso)
    beat_arr = sorted(beat_times) if beat_times else []
    beat_tolerance = max(1.5 / max(fps, 1), 0.05)

    while curr_t < duration and sched_idx < len(slice_schedule):
        seg = slice_schedule[sched_idx]
        seg = min(seg, duration - curr_t)
        sched_idx += 1
        if seg < 0.04:
            break

        k = pick_source_key()
        source = video_clips[k]
        start_p = pick_start_dj(source, k, seg)
        base_clip = source.subclip(start_p, start_p + seg).resize(newsize=target_size).set_fps(fps)

        if pitch_glitch and random.random() < 0.15:
            factor = random.choice([0.5, 0.75, 1.5, 2.0])
            base_clip = base_clip.speedx(factor).set_duration(seg)

        on_beat = False
        if freeze_on_beat:
            if beat_arr:
                idx = bisect.bisect_left(beat_arr, curr_t)
                candidates = []
                if idx < len(beat_arr):
                    candidates.append(beat_arr[idx])
                if idx > 0:
                    candidates.append(beat_arr[idx - 1])
                if candidates:
                    nearest = min(candidates, key=lambda b: abs(b - curr_t))
                    on_beat = abs(nearest - curr_t) <= beat_tolerance
            else:
                # nessun beat rilevato: fallback, ogni slice e' candidata
                on_beat = True

        if freeze_on_beat and on_beat and freeze_prob > 0 and random.random() < freeze_prob and seg > 0.15:
            f_dur = min(freeze_dur, seg * 0.5)
            frame = base_clip.get_frame(0)
            freeze_clip = ImageClip(frame).set_duration(f_dur).set_fps(fps)
            rest_dur = seg - f_dur
            rest_clip = base_clip.subclip(0, rest_dur) if rest_dur > 0.04 else base_clip.set_duration(0.04)
            base_clip = concatenate_videoclips([freeze_clip, rest_clip], method="chain").set_duration(seg)

        if random.random() < stutter_prob and loop_reps > 1:
            combo = concatenate_videoclips([base_clip] * loop_reps, method="chain")
            combo = combo.set_duration(seg * loop_reps)
            all_clips.append(combo)
            curr_t += seg * loop_reps
        else:
            all_clips.append(base_clip)
            curr_t += seg

        total_fragments += 1
        p_bar.progress(
            min(total_fragments / estimated * 0.5, 0.5),
            text=f"VJ Mode: {total_fragments} slice"
        )

    if crossfade_dur > 0 and len(all_clips) > 1:
        positioned = []
        t = 0.0
        for i, clip in enumerate(all_clips):
            if i == 0:
                positioned.append(clip.set_start(0))
                t = clip.duration
            else:
                cf = min(crossfade_dur, clip.duration * 0.4, all_clips[i - 1].duration * 0.4)
                cf = max(cf, 0.0)
                start_t = max(0.0, t - cf)
                c = clip.crossfadein(cf) if cf > 0 else clip
                positioned.append(c.set_start(start_t))
                t = start_t + clip.duration
        final = CompositeVideoClip(positioned, size=target_size).set_duration(min(t, duration))
    else:
        final = concatenate_videoclips(all_clips, method="chain").set_duration(duration)
    return final, total_fragments

# ---------------------------------------------------------------------------
# VIDEO ENGINE — Decompose classico
# ---------------------------------------------------------------------------
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
        for clip in self.video_clips.values():
            try:
                clip.close()
            except Exception:
                pass
        self.video_clips = {}

    def _pick_start(self, source, k, seg_dur, recent_cuts):
        """
        Anti-ripetizione v3: sistema a bucket.
        Divide il sorgente in N zone e tiene un contatore di visite per ognuna.
        Al momento di tagliare, sceglie preferibilmente le zone meno visitate,
        poi pesca un punto casuale DENTRO quella zona.
        Funziona bene sia su clip corti (5s) che su clip lunghi (50s+).
        """
        max_start = max(0.0, source.duration - seg_dur)
        if max_start < 0.01:
            return 0.0

        # Numero di bucket: piu' il video e' lungo, piu' bucket usiamo
        n_buckets = max(8, int(source.duration / max(0.5, seg_dur)))
        n_buckets = min(n_buckets, 40)  # cap per non sprecare memoria

        # Inizializza contatori bucket se non esistono ancora
        bucket_key = f"_buckets_{k}"
        if bucket_key not in recent_cuts:
            recent_cuts[bucket_key] = [0] * n_buckets

        counts = recent_cuts[bucket_key]
        # Se il numero di bucket e' cambiato (cambio parametri), reinizializza
        if len(counts) != n_buckets:
            recent_cuts[bucket_key] = [0] * n_buckets
            counts = recent_cuts[bucket_key]

        bucket_size = max_start / n_buckets

        # Scegli il bucket meno visitato (con un po' di randomness per non essere deterministici)
        min_visits = min(counts)
        # Rotazione esatta: solo i bucket con il minimo assoluto di visite
        candidates = [i for i, c in enumerate(counts) if c == min_visits]
        chosen_bucket = random.choice(candidates)

        # Punto casuale dentro il bucket scelto
        b_start = chosen_bucket * bucket_size
        b_end   = min(b_start + bucket_size, max_start)
        s = random.uniform(b_start, b_end)

        counts[chosen_bucket] += 1
        return s

    def generate_fixed_quota(self, quotas, r_a, r_b, r_rand, duration, fps,
                              s_a, s_b, s_rand, scan_dir, p_bar, use_scan,
                              beat_times=None, rms_envelope=None):
        keys = list(self.video_clips.keys())
        target_size = self.video_clips[keys[0]].size
        self.stats["fragments"] = 0
        total_q = sum(quotas.get(k, 0) for k in keys)
        if total_q == 0:
            norm = {k: 1 / len(keys) for k in keys}
        else:
            norm = {k: quotas.get(k, 0) / total_q for k in keys}
        time_budget = {k: norm[k] * duration for k in keys}
        recent_cuts = {k: [] for k in keys}
        all_clips = []

        for k in keys:
            budget = time_budget[k]
            source = self.video_clips[k]
            spent = 0.0
            progress = 0.0
            while spent < budget:
                remaining = budget - spent
                if r_rand:
                    seg_dur = random.uniform(min(r_a, r_b), max(r_a, r_b))
                else:
                    seg_dur = r_a + (r_b - r_a) * progress
                seg_dur = min(seg_dur, remaining)
                if seg_dur < 0.05:
                    break
                start_p = self._pick_start(source, k, seg_dur, recent_cuts)
                clip = source.subclip(start_p, start_p + seg_dur).resize(newsize=target_size).set_fps(fps)
                all_clips.append(clip)
                spent += seg_dur
                progress = spent / budget
                self.stats["fragments"] += 1
                p_bar.progress(min(self.stats["fragments"] / max(1, int(duration / r_a)) * 0.4, 0.4),
                               text=f"Composizione: {self.stats['fragments']} pezzi")

        random.shuffle(all_clips)
        final = concatenate_videoclips(all_clips, method="chain").set_duration(duration)
        if use_scan:
            _rms = rms_envelope
            final = final.fl(lambda gf, t: apply_procedural_slit_scan(
                gf, t, final.duration, s_a, s_b, s_rand, scan_dir, _rms))
        return final

    def generate(self, weights, r_a, r_b, r_rand, duration, fps,
                 s_a, s_b, s_rand, scan_dir, p_bar, use_scan,
                 beat_times=None, rms_envelope=None):
        curr_t = 0
        clips = []
        keys = list(self.video_clips.keys())
        target_size = self.video_clips[keys[0]].size
        self.stats["fragments"] = 0
        beat_idx = 0
        recent_cuts = {k: [] for k in keys}

        while curr_t < duration:
            progress = curr_t / duration
            if beat_times and len(beat_times) > 0:
                while beat_idx < len(beat_times) and beat_times[beat_idx] <= curr_t:
                    beat_idx += 1
                if beat_idx < len(beat_times):
                    seg_dur = max(r_a, beat_times[beat_idx] - curr_t)
                else:
                    seg_dur = random.uniform(min(r_a, r_b), max(r_a, r_b)) if r_rand else r_a
            elif r_rand:
                seg_dur = random.uniform(min(r_a, r_b), max(r_a, r_b))
            else:
                seg_dur = r_a + (r_b - r_a) * progress

            w_list = [weights[k][0] + (weights[k][1] - weights[k][0]) * progress for k in keys]
            if sum(w_list) == 0: w_list = [1] * len(w_list)
            v_idx = random.choices(keys, weights=w_list, k=1)[0]
            source = self.video_clips[v_idx]

            start_p = self._pick_start(source, v_idx, seg_dur, recent_cuts)
            clip = source.subclip(start_p, start_p + seg_dur).resize(newsize=target_size).set_fps(fps)
            clips.append(clip)
            curr_t += seg_dur
            self.stats["fragments"] += 1
            p_bar.progress(min(curr_t / duration * 0.4, 0.4),
                           text=f"Composizione: {self.stats['fragments']} pezzi")

        final = concatenate_videoclips(clips, method="chain").set_duration(duration)
        if use_scan:
            _rms = rms_envelope
            final = final.fl(lambda gf, t: apply_procedural_slit_scan(
                gf, t, final.duration, s_a, s_b, s_rand, scan_dir, _rms))
        return final


# ---------------------------------------------------------------------------
# INTERFACCIA
# ---------------------------------------------------------------------------
def main():
    st.set_page_config(page_title="VideoDecomposer PRO", layout="wide")
    st.title("VideoDecomposer: Rendering & Report")

    for key, val in [('video_ready', False), ('report_data', ''),
                     ('video_path', ''), ('preview_path', ''), ('render_name', 'loop507_render')]:
        if key not in st.session_state:
            st.session_state[key] = val

    with st.sidebar:
        st.header("Sorgenti")
        files = [st.file_uploader(f"Video {i+1}", type=["mp4","mov"]) for i in range(4)]
        st.divider()
        audio_file = st.file_uploader("Audio (mp3/wav)", type=["mp3","wav"])
        st.divider()
        st.subheader("Modalita'")
        app_mode = st.radio("", ["Decompose", "VJ Mode"], horizontal=True)
        mix_mode = None
        if app_mode == "Decompose":
            st.subheader("Mix")
            mix_mode = st.radio("", ["Random", "Quote Fisse"], horizontal=True)
            st.caption("**Random** = probabilita' per frammento  |  **Quote Fisse** = secondi garantiti per sorgente")

    c1, c2, c3 = st.columns(3)
    weights = {}
    quotas  = {}

    with c1:
        loaded = [i for i in range(4) if files[i]]
        default_quota = round(100 / len(loaded)) if loaded else 25

        if app_mode == "Decompose":
            st.subheader("Mix Video")
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
        else:
            st.subheader("Sorgenti caricate")
            for i in range(4):
                if files[i]:
                    st.write(f"V{i+1}: {files[i].name[:18]}")
            st.caption("Tutti i video vengono usati in egual misura nel remix.")

    with c2:
        if app_mode == "Decompose":
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
            # default per variabili DJ non usate in Decompose
            slice_dur = 0.25; loop_reps = 2; stutter_prob = 0.4
            pitch_glitch = False; beat_slice_mode = False
            auto_vj = False; crossfade_dur = 0.0
            freeze_on_beat = False; freeze_prob = 0.0; freeze_dur = 0.15
        else:
            st.subheader("Parametri VJ Mode")
            slice_options = [0.1, 0.2, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0]

            auto_vj = st.toggle(
                "Automatico (a tempo di musica caricata)",
                value=False,
                disabled=(audio_file is None),
                help="Sincronizza tutto alla musica caricata: slice da beat, crossfade "
                     "e freeze-frame impostati automaticamente in base al genere scelto. "
                     "Richiede audio caricato."
            )
            if audio_file is None:
                st.caption("_Carica un audio nella sidebar per attivare la modalita' automatica._")

            # Preset per genere musicale — valori tarati su stutter/loop/crossfade/freeze
            VJ_PRESETS = {
                "Techno":   dict(loop_reps=3, stutter_prob=0.50, pitch_glitch=False,
                                  crossfade_ms=40,  freeze_prob=0.35, freeze_ms=100),
                "House":    dict(loop_reps=2, stutter_prob=0.30, pitch_glitch=False,
                                  crossfade_ms=100, freeze_prob=0.20, freeze_ms=150),
                "Ambient":  dict(loop_reps=1, stutter_prob=0.10, pitch_glitch=False,
                                  crossfade_ms=250, freeze_prob=0.10, freeze_ms=300),
                "Pop":      dict(loop_reps=2, stutter_prob=0.25, pitch_glitch=False,
                                  crossfade_ms=80,  freeze_prob=0.20, freeze_ms=150),
                "Classica": dict(loop_reps=1, stutter_prob=0.05, pitch_glitch=False,
                                  crossfade_ms=300, freeze_prob=0.08, freeze_ms=250),
            }
            if auto_vj:
                vj_genre = st.selectbox(
                    "Stile musicale",
                    list(VJ_PRESETS.keys()),
                    index=0,
                    help="Tara crossfade, freeze, stutter e loop sul genere del brano caricato."
                )
                preset = VJ_PRESETS[vj_genre]
                st.caption(
                    f"_Preset {vj_genre}: loop x{preset['loop_reps']} · "
                    f"stutter {int(preset['stutter_prob']*100)}% · "
                    f"crossfade {preset['crossfade_ms']}ms · "
                    f"freeze {int(preset['freeze_prob']*100)}%/{preset['freeze_ms']}ms_"
                )
            else:
                vj_genre = None
                preset = None

            st.markdown("---")

            # Toggle PRIMA dello slider: se attivo, la durata slice viene dal beat
            beat_slice_mode = st.toggle(
                "Slice automatico da beat",
                value=auto_vj,
                disabled=(audio_file is None) or auto_vj,
                help="Usa i beat della musica caricata come punti di taglio. "
                     "Richiede audio caricato nella sidebar."
            )
            if auto_vj:
                beat_slice_mode = True

            # Slider durata visibile solo in modalita' manuale
            if not beat_slice_mode:
                slice_dur = st.select_slider(
                    "Durata slice",
                    options=slice_options,
                    value=0.25,
                    format_func=lambda x: f"{x}s",
                    help="0.1s = stutter ultra-rapido, 2.0s = loop lungo stile CDJ"
                )
            else:
                slice_dur = 0.25  # valore di fallback, non usato
                st.caption("_Durata slice determinata dai beat dell'audio._")

            st.markdown("---")
            loop_reps = st.slider(
                "Ripetizioni loop (stutter)", min_value=1, max_value=8,
                value=preset["loop_reps"] if auto_vj else 2,
                key=f"loop_reps_{vj_genre}",
                help="Quante volte uno slice viene ripetuto. 1 = nessun loop."
            )
            stutter_prob = st.slider(
                "Probabilita' stutter %", min_value=0, max_value=100,
                value=int(preset["stutter_prob"] * 100) if auto_vj else 40,
                key=f"stutter_prob_{vj_genre}",
                help="Percentuale di slice che vengono stutterati."
            ) / 100.0
            pitch_glitch = st.checkbox(
                "Pitch Glitch (speed warp)",
                value=preset["pitch_glitch"] if auto_vj else False,
                key=f"pitch_glitch_{vj_genre}",
                help="Alcuni slice vengono accelerati o rallentati casualmente (x0.5 / x2.0)."
            )

            st.markdown("---")
            crossfade_on = st.toggle(
                "Crossfade tra slice", value=auto_vj,
                key=f"crossfade_on_{vj_genre}",
                help="Dissolvenza incrociata tra una slice e la successiva invece del taglio secco."
            )
            if crossfade_on:
                crossfade_ms = st.slider(
                    "Durata crossfade (ms)", min_value=20, max_value=300,
                    value=preset["crossfade_ms"] if auto_vj else 100, step=10,
                    key=f"crossfade_ms_{vj_genre}",
                    help="Sovrapposizione tra slice consecutive."
                )
                crossfade_dur = crossfade_ms / 1000.0
            else:
                crossfade_dur = 0.0

            freeze_on_beat = st.toggle(
                "Freeze-frame on beat", value=auto_vj,
                key=f"freeze_on_beat_{vj_genre}",
                help="Su alcune slice, congela il primo frame per una frazione di secondo "
                     "prima di riprendere — effetto VJ classico."
            )
            if freeze_on_beat:
                freeze_prob = st.slider(
                    "Probabilita' freeze %", min_value=0, max_value=100,
                    value=int(preset["freeze_prob"] * 100) if auto_vj else 20,
                    key=f"freeze_prob_{vj_genre}",
                    help="Percentuale dei beat reali rilevati nell'audio su cui scatta "
                         "il freeze-frame (ancorato al beat, non casuale)."
                ) / 100.0
                freeze_ms = st.slider(
                    "Durata freeze (ms)", min_value=50, max_value=500,
                    value=preset["freeze_ms"] if auto_vj else 150, step=10,
                    key=f"freeze_ms_{vj_genre}",
                    help="Durata del frame congelato."
                )
                freeze_dur = freeze_ms / 1000.0
            else:
                freeze_prob = 0.0
                freeze_dur = 0.15

            if auto_vj:
                st.caption(f"_Preset {vj_genre} applicato — puoi ritoccare gli slider sopra, "
                           f"restano comunque a tempo della musica caricata (slice da beat fisso)._")

            st.markdown("---")
            st.subheader("Alternanza sorgenti (deck)")
            loaded_keys_preview = [i for i in range(4) if files[i]]
            source_mode_label = st.radio(
                "Modalita'",
                ["Casuale", "Pesata"],
                horizontal=True,
                help="Casuale = comportamento storico (ogni slice sceglie a caso tra le sorgenti). "
                     "Pesata = imposti tu quanto ogni video deve essere presente."
            )
            source_mode = "pesata" if source_mode_label == "Pesata" else "random"
            no_repeat = st.toggle(
                "Mai la stessa sorgente due slice di fila",
                value=False,
                help="Comportamento 'VJ a 4 deck': alterna sempre tra le sorgenti caricate, "
                     "evitando due slice consecutive dallo stesso video."
            )
            source_weights = {}
            if source_mode == "pesata" and loaded_keys_preview:
                default_w = round(100 / len(loaded_keys_preview))
                for i in loaded_keys_preview:
                    source_weights[i] = st.slider(
                        f"Presenza V{i+1}: {files[i].name[:14]}", 0, 100, default_w,
                        key=f"src_w_{i}"
                    )

            # default per variabili Decompose non usate in VJ Mode
            r_rand = False; r_a = 0.2; r_b = 1.0
            use_scan = False; s_rand = False; s_a = 10; s_b = 80; scan_dir = "Orizzontale"

    with c3:
        st.subheader("Esportazione")
        durata = st.number_input("Durata Totale (s)", 5, 300, 15)
        fps    = st.selectbox("FPS", [24, 30])
        st.markdown("---")

        if app_mode == "Decompose":
            beat_sync = st.toggle("A tempo di musica", value=False,
                help="I tagli seguiranno i beat, le strisce seguiranno il volume.")
        else:
            beat_sync = False
            st.caption("_Beat sync disponibile in modalita' Decompose._")

        use_custom_audio = False
        if app_mode == "Decompose" and beat_sync and audio_file:
            audio_choice = st.radio(
                "Traccia audio nel video finale",
                ["Audio originale dei video", "Usa la musica caricata"],
                index=0
            )
            use_custom_audio = (audio_choice == "Usa la musica caricata")
        audio_mix_mode = "custom_only"
        vol_music = 1.0
        vol_original = 1.0
        if app_mode == "VJ Mode" and audio_file:
            audio_mix_choice = st.radio(
                "Traccia audio nel video finale",
                ["Solo musica caricata", "Solo audio originale dei video", "Mix (musica + originale)"],
                index=0,
                help="Il timing resta sempre quello della musica caricata (loop/trim su durata)."
            )
            if audio_mix_choice == "Solo musica caricata":
                audio_mix_mode = "custom_only"
                use_custom_audio = True
            elif audio_mix_choice == "Solo audio originale dei video":
                audio_mix_mode = "original_only"
                use_custom_audio = False
            else:
                audio_mix_mode = "mix"
                use_custom_audio = True
                col_v1, col_v2 = st.columns(2)
                with col_v1:
                    vol_music = st.slider("Volume musica caricata", 0, 200, 100, step=5) / 100.0
                with col_v2:
                    vol_original = st.slider("Volume audio originale", 0, 200, 100, step=5) / 100.0

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
            total_frags   = 0

            try:
                # Analisi audio: Decompose beat sync OPPURE VJ Mode beat slice
                if app_mode == "Decompose" and beat_sync and audio_file:
                    p_bar.progress(0.05, text="Analisi audio...")
                    beat_times, rms_envelope = analyze_audio(audio_file, durata)
                    beat_count = len(beat_times)
                elif app_mode == "VJ Mode" and (beat_slice_mode or freeze_on_beat) and audio_file:
                    p_bar.progress(0.05, text="Analisi beat...")
                    audio_file.seek(0)
                    beat_times, _ = analyze_audio(audio_file, durata)
                    beat_count = len(beat_times)
                    audio_file.seek(0)  # reset per eventuale uso audio custom dopo

                engine = VideoEngine()
                engine.load_sources(paths)

                if app_mode == "Decompose":
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
                    total_frags = engine.stats["fragments"]
                    mode_label = "Decompose"
                    if mix_mode == "Quote Fisse":
                        mix_log = "Quote Fisse — " + " / ".join(
                            f"V{k+1}:{quotas.get(k,0)}%" for k in paths.keys())
                    else:
                        mix_log = "Random (pesi Start%/End%)"
                    extra_log = (f"* Ritmo: {r_a}s >> {r_b}s (Random: {r_rand})\n"
                                 f"* Strisce: {s_a}px >> {s_b}px (Random: {s_rand})\n"
                                 f"* Geometria: {scan_dir}")
                else:
                    final, total_frags = generate_dj_remix(
                        engine.video_clips, durata, fps,
                        slice_dur, loop_reps, stutter_prob, pitch_glitch, p_bar,
                        beat_slice_mode=beat_slice_mode,
                        beat_times=beat_times,
                        crossfade_dur=crossfade_dur,
                        freeze_on_beat=freeze_on_beat,
                        freeze_prob=freeze_prob,
                        freeze_dur=freeze_dur,
                        source_mode=source_mode,
                        source_weights=source_weights,
                        no_repeat=no_repeat
                    )
                    mode_label = "VJ Mode"
                    slice_info = f"beat-driven ({beat_count} beat)" if beat_slice_mode and beat_times else f"{slice_dur}s fisso"
                    mix_log = (f"VJ Mode — slice {slice_info} / "
                               f"loop x{loop_reps} / stutter {int(stutter_prob*100)}%")
                    src_alt_log = ("Pesata — " + " / ".join(
                        f"V{k+1}:{source_weights.get(k,0)}%" for k in source_weights)
                        if source_mode == "pesata" else "Casuale")
                    extra_log = (f"* Slice Mode: {slice_info}\n"
                                 f"* Loop Reps: {loop_reps}\n"
                                 f"* Stutter Prob: {int(stutter_prob*100)}%\n"
                                 f"* Pitch Glitch: {pitch_glitch}\n"
                                 f"* Alternanza Sorgenti: {src_alt_log}"
                                 f"{' (no ripetizioni consecutive)' if no_repeat else ''}\n"
                                 f"* Auto VJ: {auto_vj}" +
                                 (f" (preset {vj_genre})" if auto_vj and vj_genre else "") + "\n"
                                 f"* Crossfade: {int(crossfade_dur*1000)}ms\n"
                                 f"* Freeze on beat: {freeze_on_beat}" +
                                 (f" ({int(freeze_prob*100)}% / {int(freeze_dur*1000)}ms)"
                                  if freeze_on_beat else "") + "\n"
                                 f"* Audio Mix: {audio_mix_mode}" +
                                 (f" (musica {int(vol_music*100)}% / originale {int(vol_original*100)}%)"
                                  if audio_mix_mode == "mix" else ""))

                # Audio custom / mix
                if use_custom_audio and audio_file:
                    from moviepy.editor import AudioFileClip, CompositeAudioClip
                    from moviepy.audio.fx.all import audio_loop, volumex
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

                    if audio_mix_mode == "mix" and final.audio is not None:
                        music_track = audio_clip.fx(volumex, vol_music)
                        original_track = final.audio.set_duration(durata).fx(volumex, vol_original)
                        mixed = CompositeAudioClip([original_track, music_track]).set_duration(durata)
                        final = final.set_audio(mixed)
                    else:
                        final = final.set_audio(audio_clip)
                elif audio_mix_mode == "original_only":
                    pass  # mantiene l'audio originale già presente in final

                out_v = os.path.join(tempfile.gettempdir(), f"render_{random.randint(0,9999)}.mp4")
                p_bar.progress(0.75, text="Scrittura video...")
                final.write_videofile(out_v, codec="libx264", audio_codec="aac",
                                      preset="ultrafast", logger=None)
                time.sleep(1.5)

                p_bar.progress(0.90, text="Generando preview...")
                prev_v = os.path.join(tempfile.gettempdir(), f"preview_{random.randint(0,9999)}.mp4")
                prev_clip = final.resize(height=480)
                prev_clip.write_videofile(prev_v, codec="libx264", audio_codec="aac",
                                          preset="ultrafast", logger=None)
                prev_clip.close()
                final.close()
                time.sleep(0.5)
                p_bar.progress(1.0, text="Pronto!")

                # Nome condiviso video + report (stesso codice)
                render_id = datetime.now().strftime("%Y%m%d_%H%M%S")
                mode_short = "VJ" if app_mode == "VJ Mode" else "DC"
                render_name = f"loop507_{mode_short}_{render_id}"

                st.session_state.video_path   = out_v
                st.session_state.preview_path = prev_v
                st.session_state.render_name  = render_name
                st.session_state.report_data  = f"""[DECOMP_ARCHIVE] // VOL_01 // H.264 // AAC
:: FILE: {render_name}
:: STILE: Minimalismo Computazionale / Glitch Brutalista
:: MOTORE: video_decomposed [05.03]
:: AUDIO: 48 kHz / Float a 32 bit / Punto di Clipping
:: PROCESSO: {mode_label}

> TECHNICAL LOG SHEET:
* Sorgenti Video: {engine.stats['sources']}
* Frammenti Generati: {total_frags}
* Modalita': {mix_log}
{extra_log}
{'* Beat Sync: ON — ' + str(beat_count) + ' beat rilevati' if beat_sync and audio_file else ''}
{'* Slice Automatico: ON — ' + str(beat_count) + ' beat rilevati' if app_mode == 'VJ Mode' and beat_slice_mode and beat_times else ''}

"Non e' montaggio. E' anatomia di un segnale corrotto."

> Regia e Algoritmo: Loop507

#loop507 #datanoise #decomposition #glitchart #audiovisual #noisemusic #algorithmicvideo #brutalist #sounddesign #computationalminimalism #signalcorruption #recursivecollapse #newmediaart
"""
                st.session_state.video_ready = True

            except Exception as e:
                st.error(f"Errore: {e}")

            finally:
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
                                           f"{st.session_state.render_name}.mp4", key="down_v")
            with c_d2:
                st.download_button("Scarica Report", st.session_state.report_data,
                                   f"{st.session_state.render_name}_report.txt", key="down_t")

if __name__ == "__main__":
    main()
