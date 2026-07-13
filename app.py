import streamlit as st
import os
import random
import tempfile
import time
import numpy as np
from datetime import datetime
import bisect
from moviepy.editor import VideoFileClip, concatenate_videoclips, ImageClip, CompositeVideoClip
from moviepy.video.io.ffmpeg_reader import ffmpeg_parse_infos
from PIL import Image
import librosa

# --- PATCH COMPATIBILITA' ---
if hasattr(Image, 'Resampling'):
    Image.ANTIALIAS = Image.Resampling.LANCZOS
else:
    Image.ANTIALIAS = Image.LANCZOS

EXPORT_SIZES = {
    "16:9 (1280x720)": (1280, 720),
    "9:16 (720x1280)": (720, 1280),
    "1:1 (720x720)":   (720, 720),
}

def fit_to_size(clip, target_size):
    """
    Adatta un clip a target_size con crop-to-fill: scala per riempire
    completamente il formato (nessuna barra nera) poi ritaglia al centro
    l'eccedenza. Niente deformazione dell'immagine (a differenza del resize
    "a stiramento" usato prima). Costo quasi nullo: e' lo stesso identico
    resize che il codice faceva già su ogni frammento, con l'aggiunta di un
    semplice crop — il peso del render resta sull'encoding ffmpeg finale,
    non su questo passaggio.
    """
    tw, th = target_size
    cw, ch = clip.size
    if cw == tw and ch == th:
        return clip
    scale = max(tw / cw, th / ch)
    new_w, new_h = max(1, round(cw * scale)), max(1, round(ch * scale))
    resized = clip.resize(newsize=(new_w, new_h))
    x1 = max(0, (new_w - tw) // 2)
    y1 = max(0, (new_h - th) // 2)
    return resized.crop(x1=x1, y1=y1, width=tw, height=th)


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
        actual_dur = (len(y) / sr) if sr else 0.0

        _, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()

        # --- Onset detection ---
        # beat_track() cerca un TEMPO PERIODICO (una griglia a intervalli
        # regolari): su un ritmo irregolare/sincopato (es. bum, bum-bum,
        # bum-bum-bum — gruppi di colpi non equidistanti) smussa tutto sulla
        # griglia piu' plausibile, perdendo il singolo colpo fuori schema.
        # onset_detect() non assume periodicita': trova ogni transiente
        # cosi' com'e', regolare o no.
        #
        # ATTENZIONE pero': onset_detect() su tutto lo spettro (com'era prima)
        # rileva QUALSIASI transiente — hi-hat, rumore, armonici, texture —
        # non solo il colpo di cassa/basso che si segue a orecchio. Su un
        # brano sperimentale pieno di suoni non percussivi questo produce
        # tagli che sembrano "non seguire il ritmo" perche' in realta' stanno
        # seguendo fedelmente ANCHE cose che non sono la cassa. Restringiamo
        # l'envelope di onset alla sola banda bassa (0-200Hz circa, dove vive
        # kick/basso) con un mel-spectrogram a pochi filtri (n_mels basso,
        # altrimenti alcuni filtri restano vuoti su una banda cosi' stretta e
        # librosa avvisa con un warning): il risultato segue il "bum" reale,
        # ignorando hi-hat/testure/armonici che vivono altrove nello spettro.
        onset_env_low = librosa.onset.onset_strength(y=y, sr=sr, fmax=200, n_mels=24)
        onset_times = librosa.onset.onset_detect(
            onset_envelope=onset_env_low, sr=sr, units="time", backtrack=True, y=y
        ).tolist()

        rms = librosa.feature.rms(y=y)[0]
        rms_norm = rms / (rms.max() + 1e-6)

        # --- Energia per banda (bassi/medi/alti) ---
        # Serve a rendere il VJ reattivo a cosa succede nel brano oltre al
        # semplice beat: una cassa in 4 sta nei bassi, un tom o uno snare
        # aprono nei medi, hi-hat/percussioni brillanti negli alti. Usiamo
        # lo stesso STFT per tutte e tre le bande cosi' la griglia temporale
        # e' identica a quella dell'RMS (stesso hop_length di default).
        S = np.abs(librosa.stft(y))
        freqs = librosa.fft_frequencies(sr=sr)

        def _band(lo, hi):
            idx = np.where((freqs >= lo) & (freqs < hi))[0]
            if len(idx) == 0:
                return np.zeros(S.shape[1])
            e = S[idx, :].mean(axis=0)
            m = e.max()
            return e / (m + 1e-6) if m > 0 else e

        low_norm  = _band(20, 150)
        mid_norm  = _band(150, 2000)
        high_norm = _band(2000, 8000)

        # --- Energia "melodica/vocale" ---
        # Le bande di frequenza sopra mescolano percussivo e armonico: un
        # hi-hat e una voce acuta vivono nella stessa banda "high", e per il
        # taglio non sono la stessa cosa (un hi-hat deve tagliare fitto, una
        # voce che sale no). Con HPSS separiamo la componente armonica
        # (melodia, voce, pad) da quella percussiva (batteria) e misuriamo
        # l'energia della sola parte armonica: cosi' il motore puo' distinguere
        # "sta suonando la batteria" da "sta cantando/suonando una melodia".
        y_harm, _y_perc = librosa.effects.hpss(y)
        harm_rms = librosa.feature.rms(y=y_harm)[0]
        melody_norm = harm_rms / (harm_rms.max() + 1e-6)

        # Allinea le lunghezze (STFT e RMS possono differire di 1 frame)
        n_common = min(len(rms_norm), len(low_norm), len(mid_norm), len(high_norm), len(melody_norm))
        rms_norm    = rms_norm[:n_common]
        low_norm    = low_norm[:n_common]
        mid_norm    = mid_norm[:n_common]
        high_norm   = high_norm[:n_common]
        melody_norm = melody_norm[:n_common]

        # Se il brano caricato e' piu' corto della durata richiesta, in fase
        # di rendering viene ripetuto in loop (audio_loop). Beat e RMS qui
        # venivano invece "stirati" su tutta la durata (np.interp su un
        # array troppo corto) invece che ripetuti: il risultato erano beat
        # rilevati solo nel primo tratto e poi piu' nulla, con il video che
        # perdeva il sync dopo il primo giro del loop audio. Fix: estendiamo
        # beat_times e rms_norm (e le bande) con lo stesso principio di loop
        # usato per l'audio vero e proprio, cosi' restano coerenti su tutta
        # la durata.
        if 0.05 < actual_dur < duration:
            looped_beats = list(beat_times)
            offset = actual_dur
            while offset < duration:
                looped_beats.extend([b + offset for b in beat_times])
                offset += actual_dur
            beat_times = [b for b in looped_beats if b <= duration]

            looped_onsets = list(onset_times)
            offset = actual_dur
            while offset < duration:
                looped_onsets.extend([o + offset for o in onset_times])
                offset += actual_dur
            onset_times = [o for o in looped_onsets if o <= duration]

            n_loops = int(np.ceil(duration / actual_dur))
            rms_norm    = np.tile(rms_norm, n_loops)
            low_norm    = np.tile(low_norm, n_loops)
            mid_norm    = np.tile(mid_norm, n_loops)
            high_norm   = np.tile(high_norm, n_loops)
            melody_norm = np.tile(melody_norm, n_loops)

        total_steps = max(1, int(duration / 0.05))

        def _to_envelope(arr):
            return np.interp(
                np.linspace(0, len(arr) - 1, total_steps),
                np.arange(len(arr)), arr
            ).tolist()

        rms_envelope = _to_envelope(rms_norm)
        band_envelope = {
            "low":    _to_envelope(low_norm),
            "mid":    _to_envelope(mid_norm),
            "high":   _to_envelope(high_norm),
            "melody": _to_envelope(melody_norm),
        }
    finally:
        os.remove(tmp_path)
    return beat_times, rms_envelope, band_envelope, onset_times

def detect_bpm(audio_file):
    """Stima rapida del BPM analizzando solo i primi 30s del file audio.
    Restituisce il BPM come float, o None in caso di errore.
    Non consuma il file_uploader (fa seek(0) alla fine)."""
    try:
        orig_name = getattr(audio_file, "name", "") or ""
        suffix = os.path.splitext(orig_name)[1].lower()
        if suffix not in (".mp3", ".wav"):
            suffix = ".mp3"
        audio_file.seek(0)
        raw = audio_file.read()
        audio_file.seek(0)
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as t:
            t.write(raw)
            tmp_path = t.name
        try:
            y, sr = librosa.load(tmp_path, sr=22050, mono=True, duration=30.0)
            tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
            return float(tempo)
        finally:
            os.remove(tmp_path)
    except Exception:
        return None


def bpm_to_default_subdivision(bpm):
    """Sceglie la misura di subdivisione piu' sensata dato il BPM rilevato."""
    if bpm is None:
        return "4"
    if bpm < 75:
        return "2"    # lento: 2 beat = fraseggio naturale senza essere statico
    if bpm <= 175:
        return "4"    # fascia principale: 1 battuta in 4/4
    return "2"        # molto veloce (D&B, hardcore): 4 beat ok ma 2 e' piu' incisivo


def local_bpm_to_subdivision_factor(local_bpm):
    """Mappa il BPM ISTANTANEO (calcolato dall'intervallo reale tra due beat
    consecutivi, non dalla media dell'intero brano) a una misura di
    subdivisione: piu' il tratto e' veloce, piu' fine il taglio; quando il
    tempo rallenta (es. un ritornello piu' disteso), la misura si allarga di
    conseguenza — cosi' un brano che accelera e rallenta nel corso della
    durata non resta ancorato a un'unica misura scelta sulla media globale."""
    if local_bpm is None or local_bpm <= 0:
        return 1.0
    if local_bpm >= 150:
        return 0.5   # molto veloce: mezzo beat, taglio incisivo
    if local_bpm >= 100:
        return 1.0   # medio-veloce: un beat
    if local_bpm >= 75:
        return 2.0   # medio-lento: raggruppa 2 beat, si respira un po'
    return 4.0        # lento: raggruppa 4 beat, fraseggio ampio


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
MEASURE_FACTORS = {
    "1/16": 1/16, "1/8": 1/8, "1/6": 1/6, "1/4": 1/4, "1/3": 1/3, "1/2": 1/2,
    "1/1": 1.0, "2": 2.0, "4": 4.0, "8": 8.0, "16": 16.0,
}
MEASURE_ORDER = ["1/16", "1/8", "1/6", "1/4", "1/3", "1/2", "1/1", "2", "4", "8", "16"]

AUDIO_MIX_LABELS = {
    "custom_only": "Solo musica caricata",
    "custom_decomposed": "Musica decomposta (stessi tagli del video)",
    "original_only": "Solo audio originale dei video",
    "mix": "Mix (musica + originale)",
    "mix_decomposed": "Mix decomposto (musica decomposta + originale)",
}

def concatenate_in_batches(clips, method="chain", batch_size=250):
    """Concatena una lista (anche molto lunga, migliaia di elementi) di clip
    in modo gerarchico invece che in un'unica chiamata piatta.

    Con brani lunghi (3-4 min) e subdivisioni beat fitte, generate_dj_remix
    puo' produrre migliaia di frammenti minuscoli: passarli tutti insieme a
    concatenate_videoclips() fa crescere l'overhead di MoviePy (indicizzazione
    interna, profondita' della catena di wrapper per get_frame) in modo molto
    piu' che lineare. Concatenando prima a blocchi da `batch_size` e poi i
    blocchi tra loro, il risultato finale e' identico (stesso ordine, stessa
    durata) ma ogni singola chiamata a concatenate_videoclips lavora su una
    lista corta, tenendo l'overhead sotto controllo.
    """
    if len(clips) <= batch_size:
        return concatenate_videoclips(clips, method=method)
    batches = [
        concatenate_videoclips(clips[i:i + batch_size], method=method)
        for i in range(0, len(clips), batch_size)
    ]
    return concatenate_videoclips(batches, method=method)

def generate_dj_remix(video_clips, duration, fps, slice_dur, loop_reps,
                      stutter_prob, pitch_glitch, p_bar,
                      beat_slice_mode=False, beat_times=None,
                      rms_envelope=None, band_envelope=None,
                      crossfade_dur=0.0, freeze_on_beat=False,
                      freeze_prob=0.0, freeze_dur=0.15,
                      source_mode="random", source_weights=None,
                      no_repeat=False,
                      slice_density=1.0,
                      beat_subdivision_mode="fixed", beat_subdivision_factor=1.0,
                      beat_subdivision_choices=None,
                      manual_duration_mode="fixed", manual_duration_choices=None,
                      export_size=None, react_to_peaks=True,
                      cut_source="beat", onset_times=None):
    """
    VJ Mode:
    - slice_dur       : durata base di ogni slice (manuale, es. 0.1 ... 2.0 s)
    - loop_reps       : quante volte ogni slice viene loopata in modalita' stutter
    - stutter_prob    : probabilita' [0-1] che uno slice sia stutterato
    - pitch_glitch    : se True, alcuni slice vengono speed-warpati
    - beat_slice_mode : se True, usa i beat (o gli onset, vedi cut_source) come punti di taglio invece di slice_dur fisso
    - beat_times      : lista di timestamp beat (da analyze_audio)
    - cut_source      : "beat" (default, griglia ritmica periodica da beat_track)
                        oppure "onset" (ogni transiente/colpo rilevato da onset_detect,
                        utile su ritmi irregolari/sincopati dove beat_track smussa
                        tutto su una griglia periodica e perde i colpi fuori schema)
    - onset_times     : lista di timestamp onset (da analyze_audio), usata quando cut_source="onset"
    - crossfade_dur   : durata in secondi del crossfade tra slice consecutive (0 = taglio secco)
    - freeze_on_beat  : se True, alcune slice iniziano con un freeze-frame
    - freeze_prob     : probabilita' [0-1] che una slice abbia il freeze-frame
    - freeze_dur      : durata in secondi del freeze-frame
    - source_mode     : "random" (puro caso, comportamento storico) oppure "pesata"
                        (usa source_weights per favorire alcune sorgenti)
    - source_weights  : dict {key: peso} usato quando source_mode == "pesata"
    - no_repeat       : se True, vieta che la stessa sorgente venga scelta
                        due slice consecutive di fila (comportamento "4 deck VJ")
    - beat_subdivision_mode    : "fixed" (misura unica), "random_total" (random
                        su tutte le misure), "random_subset" (random tra le
                        misure scelte in beat_subdivision_choices)
    - beat_subdivision_factor  : misura fissa, in unita' di beat (es. 0.25 = 1/4
                        di beat, 4.0 = 4 beat per slice). Usata se mode="fixed".
    - beat_subdivision_choices : lista di fattori (float) tra cui pescare a
                        caso quando mode="random_subset"
    - manual_duration_mode : "fixed" (usa slice_dur), "random_total" (pesca
                        a caso tra manual_duration_choices, lista di secondi),
                        "random_range" (pesca un valore continuo tra
                        manual_duration_choices=(min,max) in secondi).
                        Si applica SOLO quando beat_slice_mode=False: durate
                        variabili senza bisogno di nessun audio caricato,
                        a differenza della subdivisione beat che richiede
                        i beat rilevati da un brano.
    - manual_duration_choices : lista di secondi (random_total) o tupla
                        (min, max) in secondi (random_range)
    - rms_envelope    : energia globale nel tempo (griglia 0.05s, da
                        analyze_audio). Usata per distinguere un vero
                        silenzio/break da un tratto rumoroso in cui il beat
                        tracker ha solo perso l'aggancio.
    - band_envelope   : dict {"low","mid","high"} di energia per banda
                        (stessa griglia 0.05s). Rende slice_density e
                        freeze_prob reattivi a cosa succede nel brano (tom,
                        hi-hat, apertura sui medi/alti) oltre al beat nudo.
    - react_to_peaks  : se True (default), un accento percussivo forte forza
                        un taglio fine (BURST_FACTOR) anche quando la misura
                        scelta o pescata a caso e' diversa — utile in
                        subdivisione "Fissa" per dare reattivita' al ritmo.
                        Se False, gli accenti NON scavalcano piu' la misura
                        gia' scelta: in "Random totale"/"Random in range" la
                        pesca resta puramente casuale tra i valori previsti,
                        senza che il burst-detector la sovrascriva mai.

    Anti-ripetizione v3: sistema bucket — distribuisce i tagli uniformemente
    nelle zone del sorgente, funziona bene sia su clip corti che su lunghi (50s+).
    """
    keys = list(video_clips.keys())
    target_size = export_size or video_clips[keys[0]].size
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

    # Costruisce la lista di durate slice: beat-driven, onset-driven o fissa
    _cut_time_source = onset_times if (cut_source == "onset" and onset_times) else beat_times
    cut_points = None  # None se si finisce nel ramo "slice manuale" (non beat-driven)
    if beat_slice_mode and _cut_time_source and len(_cut_time_source) > 1:
        # Punti di taglio ancorati ai beat REALI (timestamp assoluti), non a
        # intervalli ri-ciclati da t=0 (che desincronizzavano i tagli dalla musica).
        beat_arr_sorted = sorted(_cut_time_source)

        # Beat REALI (non onset), sempre — servono a "Adattiva al tempo" per
        # calcolare il BPM istantaneo anche quando cut_source="onset": un
        # intervallo tra due onset consecutivi puo' essere molto piu' corto
        # di un beat vero (es. un sedicesimo), e usarlo direttamente come se
        # fosse "un beat" produrrebbe un BPM istantaneo enorme e sballato,
        # facendo collassare la subdivisione sempre sulla misura piu' fine.
        _real_beats_sorted = sorted(beat_times) if beat_times else []

        def _real_beat_duration_at(t):
            """Durata del beat reale in cui cade il tempo assoluto t."""
            if len(_real_beats_sorted) < 2:
                return None
            idx = bisect.bisect_right(_real_beats_sorted, t) - 1
            idx = max(0, min(idx, len(_real_beats_sorted) - 2))
            d = _real_beats_sorted[idx + 1] - _real_beats_sorted[idx]
            return d if d > 0 else None

        # Intervallo medio "valido" tra beat consecutivi, usato come fallback
        # per coprire l'eventuale coda prima del primo beat e dopo l'ultimo.
        raw_intervals = [beat_arr_sorted[i+1] - beat_arr_sorted[i]
                          for i in range(len(beat_arr_sorted) - 1)]
        valid_intervals = [d for d in raw_intervals if 0.05 <= d <= 4.0]
        avg_interval = (sum(valid_intervals) / len(valid_intervals)) if valid_intervals else slice_dur

        # Cut points = beat reali entro [0, duration], includendo gli estremi.
        cut_points = [0.0] + [b for b in beat_arr_sorted if 0.0 < b < duration] + [duration]
        cut_points = sorted(set(cut_points))

        # Energia media del brano su un intervallo [t0, t1), dalla griglia
        # 0.05s di rms_envelope. Se non e' disponibile, torna un valore
        # "neutro" (comportamento storico: tratta il gap come rumoroso).
        def _avg_energy(t0, t1):
            if not rms_envelope:
                return 1.0
            i0 = min(int(t0 / 0.05), len(rms_envelope) - 1)
            i1 = min(max(i0, int(t1 / 0.05)), len(rms_envelope) - 1)
            seg = rms_envelope[i0:i1 + 1] or [rms_envelope[i0]]
            return sum(seg) / len(seg)

        # Media di una banda (low/mid/high) su un intervallo [t0, t1).
        # 0.0 se band_envelope non e' disponibile.
        def _avg_band(t0, t1, band_name):
            if not band_envelope:
                return 0.0
            arr = band_envelope.get(band_name)
            if not arr:
                return 0.0
            i0 = min(int(t0 / 0.05), len(arr) - 1)
            i1 = min(max(i0, int(t1 / 0.05)), len(arr) - 1)
            seg = arr[i0:i1 + 1] or [arr[i0]]
            return sum(seg) / len(seg)

        # "Intensita' ritmica" su un intervallo: energia percussiva (medi/alti)
        # al netto della componente melodica/vocale. Senza sottrarre la
        # melodia, una voce acuta o un lead che sale attiverebbe la stessa
        # reazione di un tom o un hi-hat — qui distinguiamo "sta suonando la
        # batteria" da "sta cantando/suonando una melodia".
        def _rhythmic_intensity_range(t0, t1):
            perc = 0.6 * _avg_band(t0, t1, "high") + 0.4 * _avg_band(t0, t1, "mid")
            mel = _avg_band(t0, t1, "melody")
            return max(0.0, min(1.0, perc - 0.35 * mel))

        QUIET_ENERGY_THRESH = 0.15

        # --- Segmenti base: un elemento per ogni intervallo beat-to-beat ---
        # Quando il beat tracker perde l'aggancio per >4s (break, cambio di
        # sezione, silenzio) il vecchio codice riempiva SEMPRE il buco con
        # n fette identiche calcolate sulla media globale del brano. Il
        # problema: se il buco e' un vero break/calo di energia, quelle
        # fette artificiali tagliano comunque a raffica, dando la sensazione
        # che il video "acceleri" in un punto musicalmente calmo; se invece
        # e' un tratto rumoroso ma non periodico, la griglia troppo fitta
        # produce la stessa raffica. In entrambi i casi, al ritorno del
        # beat vero il taglio successivo e' comunque ancorato al timestamp
        # reale (cut_points[i+1]), quindi il problema non e' la fase ma il
        # "riempimento" scelto per il buco. Ora guardiamo l'energia:
        # silenzio vero -> una sola slice lunga (nessun taglio finto);
        # energia presente ma beat non rilevato -> griglia piu' larga.
        base_segments = []
        for i in range(len(cut_points) - 1):
            d = cut_points[i+1] - cut_points[i]
            if d <= 0:
                continue
            if d > 4.0:
                gap_energy = _avg_energy(cut_points[i], cut_points[i+1])
                if gap_energy < QUIET_ENERGY_THRESH:
                    base_segments.append(d)
                else:
                    interval = max(avg_interval * 1.5, 1.0)
                    n_fill = max(1, round(d / interval))
                    fill_d = d / n_fill
                    base_segments.extend([fill_d] * n_fill)
            else:
                base_segments.append(d)

        # --- Applica la subdivisione beat ---
        # beat_subdivision_mode:
        #   "fixed"          -> ogni segmento usa beat_subdivision_factor
        #   "random_total"   -> fattore pescato a caso tra TUTTE le misure per ogni segmento
        #   "random_subset"  -> fattore pescato tra beat_subdivision_choices per ogni segmento
        #   "tempo_adaptive" -> fattore calcolato dal BPM ISTANTANEO reale del
        #                       punto in cui ci si trova: con cut_source="beat"
        #                       usa la durata del segmento stesso (che GIA' e'
        #                       un intervallo beat); con cut_source="onset" usa
        #                       invece la durata del beat REALE che contiene
        #                       quell'istante (_real_beat_duration_at), non
        #                       l'intervallo tra un onset e l'altro (che e'
        #                       spesso una frazione di beat e produrrebbe un
        #                       BPM istantaneo sballato, facendo collassare la
        #                       subdivisione sempre sulla misura piu' fine).
        ALL_FACTORS = list(MEASURE_FACTORS.values())
        choices_pool = (beat_subdivision_choices or ALL_FACTORS)
        choices_pool = [f for f in choices_pool if f > 0]
        if not choices_pool:
            choices_pool = [1.0]

        slice_schedule = []
        i = 0
        abs_t = 0.0  # tempo assoluto di inizio del base_segment corrente
        BURST_THRESH = 0.55   # soglia di accento oltre la quale forziamo un taglio fine
        BURST_FACTOR = 0.25   # misura forzata durante un accento (1/4 di beat)
        while i < len(base_segments):
            if beat_subdivision_mode == "fixed":
                sv = beat_subdivision_factor
            elif beat_subdivision_mode == "random_total":
                sv = random.choice(ALL_FACTORS)
            elif beat_subdivision_mode == "tempo_adaptive":
                if cut_source == "onset" and _real_beats_sorted:
                    _d = _real_beat_duration_at(abs_t)
                else:
                    _d = base_segments[i]
                _local_bpm = 60.0 / _d if _d else None
                sv = local_bpm_to_subdivision_factor(_local_bpm)
            else:  # random_subset
                sv = random.choice(choices_pool)

            # Override reattivo (solo se react_to_peaks=True): prima di
            # applicare la misura scelta (o quella del preset), guardiamo se
            # in QUESTO punto del brano c'e' un accento percussivo forte
            # (tom, snare, raffica di hi-hat), al netto della componente
            # melodica/vocale — cosi' una voce acuta o un lead che sale non
            # vengono scambiati per una batteria. Senza questo, un fill
            # veloce dentro un brano piu' lento viene comunque tagliato alla
            # stessa cadenza fissa di tutto il resto — la misura scelta non
            # ha mai modo di "sapere" cosa succede davvero nell'audio in
            # quel preciso istante. Con react_to_peaks=False (default per
            # "Random totale"/"Random in range") questo scavalcamento e'
            # disattivato: le misure pescate a caso restano tali, senza che
            # un accento le sovrascriva mai con BURST_FACTOR — cosi' TUTTI i
            # valori selezionati dall'utente vengono davvero sfruttati.
            # Importante: se sv raggruppa piu' beat (sv >= 1.0), un burst
            # breve nascosto in UN beat del gruppo si annacqua se mediamo
            # l'intensita' sull'intero intervallo del gruppo (2s di media
            # spengono un picco di 0.2s). Guardiamo quindi il picco per
            # singolo beat dentro il gruppo, non la media sul gruppo intero.
            if sv >= 1.0:
                n_candidate = max(1, round(sv))
                t_cursor = abs_t
                accent_here = 0.0
                for d in base_segments[i:i + n_candidate]:
                    a = _rhythmic_intensity_range(t_cursor, t_cursor + d)
                    accent_here = max(accent_here, a)
                    t_cursor += d
            else:
                accent_here = _rhythmic_intensity_range(abs_t, abs_t + base_segments[i])
            if react_to_peaks and band_envelope and accent_here > BURST_THRESH and sv > BURST_FACTOR:
                sv = BURST_FACTOR

            if sv >= 1.0:
                # Raggruppa: somma sv segmenti consecutivi in uno solo
                n = max(1, round(sv))
                group = base_segments[i:i + n]
                total = sum(group)
                if total >= 0.04:
                    slice_schedule.append(total)
                abs_t += total
                i += n
            else:
                # Suddividi: spezza il segmento corrente in 1/sv parti uguali
                n = max(1, round(1.0 / sv))
                piece = base_segments[i] / n
                if piece >= 0.04:
                    slice_schedule.extend([piece] * n)
                else:
                    slice_schedule.append(base_segments[i])
                abs_t += base_segments[i]
                i += 1
    else:
        # Slice manuale: fissa oppure durata variabile (random) — NON richiede
        # nessun audio. Prima l'unico modo di ottenere durate variabili era la
        # subdivisione beat, che pero' pretende un audio caricato per rilevare
        # i beat: qui la variazione e' in secondi assoluti, non beat-relativa.
        if manual_duration_mode == "random_range" and manual_duration_choices:
            dmin, dmax = manual_duration_choices
            dmin = max(0.05, dmin)
            dmax = max(dmin, dmax)
            base_dur = dmin
            n = max(1, int(duration / base_dur)) + 6
            slice_schedule = [random.uniform(dmin, dmax) for _ in range(n)]
        elif manual_duration_mode == "random_total" and manual_duration_choices:
            base_dur = max(0.05, min(manual_duration_choices))
            n = max(1, int(duration / base_dur)) + 6
            slice_schedule = [random.choice(manual_duration_choices) for _ in range(n)]
        else:
            n = max(1, int(duration / slice_dur)) + 2
            slice_schedule = [slice_dur] * n

    estimated = max(1, len(slice_schedule))
    sched_idx = 0

    # Beat reali ordinati per freeze-frame e density check
    beat_arr = sorted(beat_times) if beat_times else []
    beat_tolerance = max(1.5 / max(fps, 1), 0.05)

    # Timing frame-accurate: teniamo il contatore in frame interi
    # per evitare il drift cumulativo da arrotondamento float.
    # curr_t viene ricalcolato da frame_count ad ogni iterazione.
    total_frames = max(1, round(duration * fps))
    frame_count = 0  # frame gia' renderizzati

    # Stato per slice_density: accumula segmenti che "passano" senza taglio
    pending_seg   = 0.0   # durata accumulata da consumare con la stessa sorgente
    pending_k     = None  # sorgente corrente (None = prima slice)
    pending_start = 0.0   # punto di inizio nel video sorgente

    # Energia per banda nel punto t (griglia 0.05s). Restituisce 0 se non
    # disponibile: senza band_envelope il comportamento resta quello storico.
    def _band_at(t, band_name):
        if not band_envelope:
            return 0.0
        arr = band_envelope.get(band_name)
        if not arr:
            return 0.0
        idx = min(int(t / 0.05), len(arr) - 1)
        return arr[idx]

    # Compensazione crossfade: ogni clip crossfadata viene posizionata
    # "start_t = t - cf" secondi PRIMA del taglio secco (vedi assemblaggio
    # finale piu' sotto). Il loop qui sopra pero' si fermava quando
    # frame_count raggiungeva total_frames NOMINALE (somma delle durate,
    # senza overlap): la timeline REALE dopo il crossfade e' piu' corta di
    # quanto sottratto da ogni overlap, quindi il video finale usciva piu'
    # breve del richiesto e, con molti tagli (beat-slice fitto), sempre
    # piu' fuori sync via via che gli overlap si accumulavano. Estendiamo
    # qui il target (total_frames) della stessa quantita' che il
    # crossfade sottrarra' dopo, cosi' la timeline compressa finale torna
    # a coincidere con "duration".
    last_committed_dur = [None]  # mutabile, ultima durata clip aggiunta

    def _register_clip(dur):
        nonlocal total_frames
        if crossfade_dur > 0 and last_committed_dur[0] is not None:
            cf_est = min(crossfade_dur, dur * 0.4, last_committed_dur[0] * 0.4)
            total_frames += max(0, round(cf_est * fps))
        last_committed_dur[0] = dur

    while frame_count < total_frames:
        if sched_idx >= len(slice_schedule):
            if not slice_schedule:
                break
            # Materiale extra richiesto solo per compensare l'overlap dei
            # crossfade: ricicliamo la stessa griglia di tagli dall'inizio.
            sched_idx = 0
        curr_t = frame_count / fps
        seg_raw = slice_schedule[sched_idx]
        sched_idx += 1

        # Intensita' ritmica nel punto corrente: energia percussiva (medi/
        # alti — tom, snare, hi-hat) al netto della componente melodica/
        # vocale, cosi' una voce o un lead che sale non viene scambiato per
        # una batteria. Il basso viene tenuto separato: e' gia' coperto dal
        # beat tracking sulla cassa, ma lo riusiamo sotto per il freeze
        # (il classico "freeze sul colpo di cassa").
        rhythmic_intensity = max(0.0, min(1.0,
            0.6 * _band_at(curr_t, "high") + 0.4 * _band_at(curr_t, "mid")
            - 0.35 * _band_at(curr_t, "melody")
        ))
        bass_level = _band_at(curr_t, "low")

        # Frame-accurate: quanti frame servono per questo segmento?
        remaining_frames = total_frames - frame_count
        n_frames = max(1, round(seg_raw * fps))
        n_frames = min(n_frames, remaining_frames)
        seg = n_frames / fps
        if seg < 0.02:
            break

        # ── Slice density: decide se questo beat genera un taglio nuovo ──
        # Se il dado non supera la soglia, accorpa il segmento al pending
        # (stessa sorgente, stessa posizione — effetto "continua a girare").
        # Non e' piu' un tetto fisso: nei tratti calmi/melodici la densita'
        # scende sotto la base scelta (il video "respira", meno tagli),
        # nei tratti percussivi densi sale fino a tagliare su ogni beat.
        # ECCEZIONE IMPORTANTE: se la base e' gia' al 100% (utente ha scelto
        # "taglia sempre", oppure siamo in Auto VJ dove slice_density=1.0 e
        # non c'e' nessuno slider per accorgersene), la modulazione reattiva
        # viene SALTATA — altrimenti "100%" smetteva silenziosamente di
        # significare "sempre" nei tratti calmi (poteva scendere fino al
        # 50%), e in Auto VJ l'utente non ha nessun modo di saperlo o
        # correggerlo. Sotto al 100% la modulazione resta invece attiva
        # com'era pensata: la densita' scelta e' un tetto, non un valore fisso.
        if band_envelope and slice_density < 1.0:
            local_density = max(0.1, min(1.0, slice_density * (0.5 + 0.9 * rhythmic_intensity)))
        else:
            local_density = slice_density
        make_cut = (pending_k is None) or (random.random() < local_density)

        if make_cut:
            # Scarica eventuale pending prima di iniziare il nuovo clip
            if pending_k is not None and pending_seg >= 0.02:
                pn = max(1, round(pending_seg * fps))
                p_actual = pn / fps
                p_src = video_clips[pending_k]
                # Guardia: se pending_start e' già oltre (o troppo vicino a)
                # la fine del file sorgente non c'e' footage da prendere,
                # meglio scartare il pending che tentare un subclip invalido.
                if pending_start >= p_src.duration - (1.0 / fps):
                    pending_seg = 0.0
                else:
                    p_end = min(pending_start + p_actual, p_src.duration)
                    # Clamp di sicurezza: se il buffer accumulato (pending_seg)
                    # richiederebbe piu' footage di quanto ne resti davvero nella
                    # sorgente da pending_start in poi, p_end viene tagliato da
                    # min() ma prima qui si forzava comunque set_duration(p_actual)
                    # con p_actual NON aggiornato: il clip dichiarava una durata
                    # maggiore del footage realmente disponibile, e moviepy andava
                    # in errore "Accessing time t=... with clip duration=..." in
                    # fase di scrittura. Ora ricalcoliamo p_actual/pn sulla durata
                    # effettivamente disponibile dopo il clamp.
                    p_actual = max(1.0 / fps, p_end - pending_start)
                    pn = max(1, round(p_actual * fps))
                    pclip = fit_to_size(p_src.subclip(pending_start, p_end), target_size).set_fps(fps).set_duration(p_actual)
                    all_clips.append(pclip)
                    _register_clip(p_actual)
                    frame_count += pn
                    total_fragments += 1
                    pending_seg = 0.0

            # Nuovo taglio
            k = pick_source_key()
            source = video_clips[k]
            start_p = pick_start_dj(source, k, seg)
            base_clip = fit_to_size(source.subclip(start_p, min(start_p + seg, source.duration)), target_size).set_fps(fps).set_duration(seg)

            if pitch_glitch and random.random() < 0.15:
                factor = random.choice([0.5, 0.75, 1.5, 2.0])
                base_clip = base_clip.speedx(factor).set_duration(seg)

            # Freeze-frame on beat
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
                    on_beat = True

            # Il freeze scatta piu' spesso sugli accenti percussivi reali
            # (tom/snare/hi-hat) O su un colpo di basso/cassa forte (il
            # classico "freeze sul kick") — si prende il piu' alto dei due,
            # non serve che scattino insieme. 0.5 e' la base, fino a 1.4x
            # quando uno dei due trigger e' al massimo.
            freeze_trigger = max(rhythmic_intensity, 0.8 * bass_level)
            local_freeze_prob = min(1.0, freeze_prob * (0.5 + 0.9 * freeze_trigger))
            if freeze_on_beat and on_beat and local_freeze_prob > 0 and random.random() < local_freeze_prob and seg > 0.15:
                f_dur = min(freeze_dur, seg * 0.5)
                frame_f = base_clip.get_frame(0)
                freeze_clip = ImageClip(frame_f).set_duration(f_dur).set_fps(fps)
                rest_dur = seg - f_dur
                rest_clip = base_clip.subclip(0, rest_dur) if rest_dur > 0.04 else base_clip.set_duration(0.04)
                base_clip = concatenate_videoclips([freeze_clip, rest_clip], method="chain").set_duration(seg)

            if random.random() < stutter_prob and loop_reps > 1:
                combo = concatenate_videoclips([base_clip] * loop_reps, method="chain")
                # PRIMA: durava n_frames * loop_reps — cioe' DOPPIO/TRIPLO
                # dello slot che il beat/onset aveva assegnato a quel
                # segmento. frame_count avanzava piu' dell'audio (che
                # continua al suo ritmo naturale, ignaro dello stutter), e
                # ogni volta che scattava (dipende da un tiro random ad ogni
                # segmento, quindi imprevedibile) tutto cio' che seguiva
                # restava permanentemente fuori sync — esattamente il
                # pattern "sembra a caso, senza un pattern preciso" quando
                # stutter_prob non e' zero. ORA: la ripetizione viene
                # compressa (speedx) nello STESSO slot temporale originale
                # (n_frames) — stesso effetto visivo di stutter (il clip si
                # ripete loop_reps volte, solo piu' veloce), ma il tempo
                # totale consumato resta identico a quello non-stutterato,
                # quindi l'audio non si disallinea mai.
                combo = combo.speedx(loop_reps).set_duration(n_frames / fps)
                all_clips.append(combo)
                _register_clip(n_frames / fps)
                frame_count += n_frames
            else:
                all_clips.append(base_clip)
                _register_clip(seg)
                frame_count += n_frames

            pending_seg   = 0.0
            pending_k     = k
            pending_start = start_p + seg
            total_fragments += 1

        else:
            # Nessun taglio: accumula nel pending (stessa sorgente)
            pending_seg += seg

        p_bar.progress(
            min(total_fragments / estimated * 0.5, 0.5),
            text=f"VJ Mode: {total_fragments} slice"
        )

    # Scarica eventuale pending residuo a fine schedule
    if pending_k is not None and pending_seg >= 0.02:
        p_src = video_clips[pending_k]
        if pending_start >= p_src.duration - (1.0 / fps):
            pass  # niente footage residuo da prendere
        else:
            pn = max(1, round(pending_seg * fps))
            p_actual = pn / fps
            p_end = min(pending_start + p_actual, p_src.duration)
            # Stesso fix del flush precedente: ricalcolo p_actual sulla durata
            # realmente disponibile dopo il clamp, per non dichiarare un
            # set_duration maggiore del footage esistente nella sorgente.
            p_actual = max(1.0 / fps, p_end - pending_start)
            pclip = fit_to_size(p_src.subclip(pending_start, p_end), target_size).set_fps(fps).set_duration(p_actual)
            all_clips.append(pclip)
            _register_clip(p_actual)
            total_fragments += 1

    # Schema reale dei tagli usati per assemblare il video (durata di ogni
    # frammento nell'ordine finale, incluse le combo di stutter): serve per
    # poter "decomporre" l'audio caricato con la stessa identica griglia.
    cut_schedule = [c.duration for c in all_clips]

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
        final = concatenate_in_batches(all_clips, method="chain").set_duration(duration)
    return final, total_fragments, cut_schedule

def decompose_audio_track(audio_clip, cut_schedule, total_duration):
    """
    Applica al brano caricato la STESSA griglia di tagli usata per assemblare
    il video (cut_schedule = lista di durate, nello stesso ordine con cui
    sono stati montati i frammenti video). Per ogni slot pesca un punto
    casuale nel brano (con bucket anti-ripetizione, stesso principio usato
    per i video) invece del punto "naturale" in sequenza: il risultato e'
    il brano rimescolato nella stessa grammatica ritmica del video, cioe'
    gli slice tagliano anche il brano caricato.
    """
    from moviepy.editor import concatenate_audioclips

    if not cut_schedule:
        return audio_clip.set_duration(total_duration)

    audio_dur = audio_clip.duration
    if audio_dur is None or audio_dur <= 0.05:
        return audio_clip.set_duration(total_duration)

    n_buckets = min(40, max(8, int(audio_dur / 0.5)))
    bucket_counts = [0] * n_buckets
    bucket_size = audio_dur / n_buckets

    pieces = []
    elapsed = 0.0
    for seg in cut_schedule:
        if elapsed >= total_duration:
            break
        seg = min(seg, total_duration - elapsed)
        if seg < 0.02:
            break

        max_start = max(0.0, audio_dur - seg)
        if max_start < 0.01:
            start = 0.0
        else:
            min_v = min(bucket_counts)
            candidates = [i for i, c in enumerate(bucket_counts) if c == min_v]
            chosen = random.choice(candidates)
            b_start = chosen * bucket_size
            b_end = min(b_start + bucket_size, audio_dur)
            start = random.uniform(b_start, max(b_start, b_end))
            # Clamp di sicurezza: i bucket sono ritagliati sulla durata TOTALE
            # del brano, ma il punto di partenza valido per questo segmento
            # e' al massimo max_start (altrimenti start+seg supera la durata
            # del file e moviepy va in errore "Accessing time t=... with clip
            # duration=..."). Senza questo clamp, bucket vicini alla fine del
            # brano potevano restituire start > max_start.
            start = min(start, max_start)
            bucket_counts[chosen] += 1

        piece = audio_clip.subclip(start, min(start + seg, audio_dur)).set_duration(seg)
        pieces.append(piece)
        elapsed += seg

    if not pieces:
        return audio_clip.set_duration(total_duration)

    result = concatenate_audioclips(pieces)
    return result.set_duration(min(elapsed, total_duration))


# ---------------------------------------------------------------------------
# VIDEO ENGINE — Decompose classico
# ---------------------------------------------------------------------------
class VideoEngine:
    def __init__(self):
        self.video_clips = {}
        self.stats = {"fragments": 0, "sources": 0}

    def load_sources(self, paths, target_size=None):
        # target_size = (w, h) del formato di export scelto. Il video finale
        # verra' comunque tagliato/scalato a quella dimensione (fit_to_size)
        # — decodificare le sorgenti a piena risoluzione nativa (es. 4K) per
        # poi scartare i pixel in piu' e' solo spreco di RAM, moltiplicato
        # per ogni sorgente caricata (con piu' video insieme il carico si
        # somma: candidato concreto per OOM su host con memoria limitata
        # come il piano gratuito di Streamlit Cloud).
        #
        # ATTENZIONE: MoviePy, se target_resolution specifica SIA altezza CHE
        # larghezza, forza quell'esatta dimensione senza rispettare l'aspect
        # ratio (deformazione) — romperebbe silenziosamente il crop-to-fill di
        # fit_to_size. Per questo qui si vincola SOLO l'asse piu' grande della
        # sorgente (l'altro resta None), cosi' MoviePy scala mantenendo l'aspect
        # ratio nativo — fit_to_size riceve un frame piu' piccolo ma con le
        # stesse proporzioni di sempre, e ricalcola scale/crop esattamente come
        # prima, solo partendo da una risoluzione di decodifica piu' bassa.
        # Se il probe fallisce per qualsiasi motivo, si procede alla risoluzione
        # nativa: nessuna regressione, solo nessun risparmio di memoria.
        DECODE_CAP = 1600  # margine oltre il piu' grande formato di export (1280px)
        for i, p in paths.items():
            target_resolution = None
            if target_size is not None:
                try:
                    native_w, native_h = ffmpeg_parse_infos(p)["video_size"]
                    if max(native_w, native_h) > DECODE_CAP:
                        target_resolution = (None, DECODE_CAP) if native_w >= native_h else (DECODE_CAP, None)
                except Exception:
                    target_resolution = None
            self.video_clips[i] = VideoFileClip(p, target_resolution=target_resolution)
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
                              beat_times=None, rms_envelope=None, export_size=None):
        keys = list(self.video_clips.keys())
        target_size = export_size or self.video_clips[keys[0]].size
        self.stats["fragments"] = 0
        total_q = sum(quotas.get(k, 0) for k in keys)
        if total_q == 0:
            norm = {k: 1 / len(keys) for k in keys}
        else:
            norm = {k: quotas.get(k, 0) / total_q for k in keys}
        time_budget = {k: norm[k] * duration for k in keys}
        recent_cuts = {k: [] for k in keys}
        all_clips = []

        # --- Intervalli beat reali: se disponibili, guidano la durata delle
        # slice anche in Quote Fisse (prima venivano ignorati del tutto: il
        # toggle "A tempo di musica" non aveva alcun effetto sui tagli in
        # questa modalita', solo sulle strisce via rms_envelope). Nota: per
        # via dello shuffle finale (necessario per distribuire le quote nel
        # tempo) non e' possibile un ancoraggio assoluto al singolo beat come
        # in modalita' "Random" — qui i tagli hanno pero' la stessa durata
        # ritmica dei beat rilevati, quindi il "feel" a tempo resta.
        beat_intervals = None
        if beat_times and len(beat_times) > 1:
            bt = sorted(beat_times)
            beat_intervals = [bt[i+1] - bt[i] for i in range(len(bt) - 1)]
            beat_intervals = [d for d in beat_intervals if 0.05 <= d <= 4.0]
            if not beat_intervals:
                beat_intervals = None

        for k in keys:
            budget = time_budget[k]
            source = self.video_clips[k]
            spent = 0.0
            progress = 0.0
            b_idx = random.randrange(len(beat_intervals)) if beat_intervals else 0
            while spent < budget:
                remaining = budget - spent
                if beat_intervals:
                    seg_dur = beat_intervals[b_idx % len(beat_intervals)]
                    b_idx += 1
                elif r_rand:
                    seg_dur = random.uniform(min(r_a, r_b), max(r_a, r_b))
                else:
                    seg_dur = r_a + (r_b - r_a) * progress
                seg_dur = min(seg_dur, remaining)
                if seg_dur < 0.05:
                    break
                start_p = self._pick_start(source, k, seg_dur, recent_cuts)
                clip = fit_to_size(source.subclip(start_p, start_p + seg_dur), target_size).set_fps(fps)
                all_clips.append(clip)
                spent += seg_dur
                progress = spent / budget
                self.stats["fragments"] += 1
                p_bar.progress(min(self.stats["fragments"] / max(1, int(duration / r_a)) * 0.4, 0.4),
                               text=f"Composizione: {self.stats['fragments']} pezzi")

        random.shuffle(all_clips)
        cut_schedule = [c.duration for c in all_clips]
        final = concatenate_in_batches(all_clips, method="chain").set_duration(duration)
        if use_scan:
            _rms = rms_envelope
            final = final.fl(lambda gf, t: apply_procedural_slit_scan(
                gf, t, final.duration, s_a, s_b, s_rand, scan_dir, _rms))
        return final, cut_schedule

    def generate(self, weights, r_a, r_b, r_rand, duration, fps,
                 s_a, s_b, s_rand, scan_dir, p_bar, use_scan,
                 beat_times=None, rms_envelope=None, export_size=None):
        curr_t = 0
        clips = []
        keys = list(self.video_clips.keys())
        target_size = export_size or self.video_clips[keys[0]].size
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
            clip = fit_to_size(source.subclip(start_p, start_p + seg_dur), target_size).set_fps(fps)
            clips.append(clip)
            curr_t += seg_dur
            self.stats["fragments"] += 1
            p_bar.progress(min(curr_t / duration * 0.4, 0.4),
                           text=f"Composizione: {self.stats['fragments']} pezzi")

        cut_schedule = [c.duration for c in clips]
        final = concatenate_in_batches(clips, method="chain").set_duration(duration)
        if use_scan:
            _rms = rms_envelope
            final = final.fl(lambda gf, t: apply_procedural_slit_scan(
                gf, t, final.duration, s_a, s_b, s_rand, scan_dir, _rms))
        return final, cut_schedule


# ---------------------------------------------------------------------------
# REPORT: traduzione IT -> EN (etichette statiche; i valori dinamici restano
# invariati perche' sono numeri/nomi file e non vengono intercettati dalle
# sostituzioni sotto). Le frasi piu' lunghe/specifiche vengono sostituite
# prima di quelle piu' corte per evitare match parziali indesiderati.
# ---------------------------------------------------------------------------
_REPORT_IT_EN = [
    ("Non e' montaggio. E' anatomia di un segnale corrotto.",
     "This isn't editing. It's the anatomy of a corrupted signal."),
    ("Regia e Algoritmo", "Direction and Algorithm"),
    ("Minimalismo Computazionale / Glitch Brutalista", "Computational Minimalism / Brutalist Glitch"),
    ("Float a 32 bit / Punto di Clipping", "32-bit Float / Clipping Point"),
    ("Random (pesi Start%/End%)", "Random (Start%/End% weights)"),
    ("Reattivita' multi-banda", "Multi-band Reactivity"),
    ("no ripetizioni consecutive", "no consecutive repeats"),
    ("Alternanza Sorgenti", "Source Alternation"),
    ("Slice Automatico", "Automatic Slice"),
    ("random totale", "full random"),
    ("random in range", "random in range"),
    ("beat rilevati", "beats detected"),
    ("Sorgenti Video", "Video Sources"),
    ("Frammenti Generati", "Fragments Generated"),
    ("Quote Fisse", "Fixed Quotas"),
    ("Beat Sync", "Beat Sync"),
    ("Freeze on beat", "Freeze on beat"),
    ("Audio Mix", "Audio Mix"),
    ("Auto VJ", "Auto VJ"),
    ("Slice Mode", "Slice Mode"),
    ("Loop Reps", "Loop Reps"),
    ("Stutter Prob", "Stutter Prob"),
    ("Pitch Glitch", "Pitch Glitch"),
    ("Crossfade", "Crossfade"),
    ("Modalita'", "Mode"),
    ("Geometria", "Geometry"),
    ("Strisce", "Stripes"),
    ("Formato", "Format"),
    ("Ritmo", "Rhythm"),
    ("Pesata", "Weighted"),
    ("Casuale", "Random"),
    ("musica", "music"),
    ("originale", "original"),
    ("preset", "preset"),
    ("fisso", "fixed"),
    ("FILE", "FILE"),
    ("STILE", "STYLE"),
    ("MOTORE", "ENGINE"),
    ("AUDIO", "AUDIO"),
    ("PROCESSO", "PROCESS"),
    ("TECHNICAL LOG SHEET", "TECHNICAL LOG SHEET"),
]


def translate_report_to_en(text: str) -> str:
    """Traduce le etichette statiche del report IT in EN, lasciando invariati
    i valori dinamici (nomi file, numeri, percentuali)."""
    result = text
    for it, en in _REPORT_IT_EN:
        result = result.replace(it, en)
    return result


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
        if audio_file is not None:
            audio_key = f"bpm_{audio_file.name}_{audio_file.size}"
            if st.session_state.get("_bpm_key") != audio_key:
                with st.spinner("Analisi BPM..."):
                    _bpm = detect_bpm(audio_file)
                st.session_state["detected_bpm"] = _bpm
                st.session_state["_bpm_key"] = audio_key
                st.session_state["manual_bpm_input"] = 0.0  # nuovo brano: azzera l'eventuale BPM manuale del brano precedente
            detected_bpm = st.session_state.get("detected_bpm")
            if detected_bpm:
                st.caption(f"_BPM rilevato: **{detected_bpm:.1f}**_")
            _manual_bpm = st.number_input(
                "BPM manuale (0 = usa quello rilevato)",
                min_value=0.0, max_value=300.0, value=0.0, step=0.5,
                key="manual_bpm_input",
                help=(
                    "Lascia a 0 per usare il BPM rilevato automaticamente. "
                    "Inserisci un valore per forzarlo — utile su brani "
                    "sperimentali dove la rilevazione automatica puo' "
                    "sbagliare, o se conosci gia' il BPM esatto. "
                    "Attenzione: i TAGLI continuano comunque a seguire i "
                    "beat reali rilevati nell'audio (la cassa) — questo "
                    "valore serve solo a guidare la misura suggerita in "
                    "'Fissa' e i calcoli di 'Adattiva al tempo'/stima "
                    "frammenti, non sposta i punti di taglio."
                )
            )
            if _manual_bpm > 0:
                detected_bpm = _manual_bpm
                st.session_state["detected_bpm"] = _manual_bpm
        else:
            detected_bpm = None
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
            beat_subdivision_mode = "fixed"; beat_subdivision_factor = 1.0; beat_subdivision_choices = None
            manual_duration_mode = "fixed"; manual_duration_choices = None
            slice_density = 1.0; react_to_peaks = True
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

            # Preset per genere musicale — valori tarati su stutter/loop/crossfade/freeze.
            # "subdiv" e' la misura beat di base (in unita' MEASURE_FACTORS) usata in
            # automatico: prima non esisteva, e il default generico (bpm_to_default_
            # subdivision) raggruppava 4 beat per slice per QUALSIASI genere a tempo
            # medio/alto — quindi "Techno" tagliava alla stessa grana lenta di
            # "Ambient", niente affatto reattivo.
            VJ_PRESETS = {
                "Techno":   dict(loop_reps=3, stutter_prob=0.50, pitch_glitch=False,
                                  crossfade_ms=40,  freeze_prob=0.35, freeze_ms=100, subdiv=0.5),
                "House":    dict(loop_reps=2, stutter_prob=0.30, pitch_glitch=False,
                                  crossfade_ms=100, freeze_prob=0.20, freeze_ms=150, subdiv=1.0),
                "Ambient":  dict(loop_reps=1, stutter_prob=0.10, pitch_glitch=False,
                                  crossfade_ms=250, freeze_prob=0.10, freeze_ms=300, subdiv=2.0),
                "Pop":      dict(loop_reps=2, stutter_prob=0.25, pitch_glitch=False,
                                  crossfade_ms=80,  freeze_prob=0.20, freeze_ms=150, subdiv=1.0),
                "Classica": dict(loop_reps=1, stutter_prob=0.05, pitch_glitch=False,
                                  crossfade_ms=300, freeze_prob=0.08, freeze_ms=250, subdiv=4.0),
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
                    f"freeze {int(preset['freeze_prob']*100)}%/{preset['freeze_ms']}ms · "
                    f"taglio: adattivo al BPM reale del brano_"
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
            # Senza una key esplicita, st.toggle mantiene il suo stato nella
            # sessione a prescindere da "value" e "disabled": se in questa
            # sessione era stato attivato con un audio caricato e poi l'audio
            # viene rimosso, il toggle resta visivamente disabilitato ma
            # BLOCCATO su True — nascondendo tutti i controlli manuali (durata
            # slice, subdivisione, densita') anche se non c'e' piu' nessun
            # beat da cui derivare i tagli. Forziamo qui la coerenza: senza
            # audio, beat_slice_mode e' sempre False.
            if audio_file is None:
                beat_slice_mode = False
            if auto_vj:
                beat_slice_mode = True

            cut_source = "beat"
            if beat_slice_mode and not auto_vj:
                cut_source_label = st.radio(
                    "Sorgente tagli",
                    ["Beat (griglia ritmica)", "Onset (ogni colpo rilevato)"],
                    horizontal=True,
                    key="cut_source_radio",
                    help=(
                        "Beat: griglia a tempo periodico (beat_track) — ideale "
                        "su ritmi regolari a 4/4. Onset: segue OGNI transiente "
                        "rilevato nell'audio, regolare o no — utile su ritmi "
                        "irregolari/sincopati (es. bum, bum-bum, bum-bum-bum) "
                        "dove la griglia periodica smusserebbe i colpi fuori "
                        "schema."
                    )
                )
                cut_source = "onset" if cut_source_label.startswith("Onset") else "beat"

            # Slider durata visibile solo in modalita' manuale
            if not beat_slice_mode:
                st.markdown("**Durata slice**")
                dur_mode_label = st.radio(
                    "Modalita' durata",
                    ["Fissa", "Random tra durate", "Random in range"],
                    horizontal=True,
                    key="manual_dur_mode_radio",
                    help=(
                        "Fissa: tutte le slice hanno la stessa durata. "
                        "Random tra durate: ogni slice pesca a caso tra le durate scelte. "
                        "Random in range: ogni slice pesca un valore continuo tra un minimo e un massimo. "
                        "Non serve nessun audio: la variazione e' in secondi, non legata al beat."
                    )
                )

                if dur_mode_label == "Fissa":
                    manual_duration_mode = "fixed"
                    manual_duration_choices = None
                    slice_dur = st.select_slider(
                        "Durata slice",
                        options=slice_options,
                        value=0.25,
                        format_func=lambda x: f"{x}s",
                        help="0.1s = stutter ultra-rapido, 2.0s = loop lungo stile CDJ"
                    )

                elif dur_mode_label == "Random tra durate":
                    manual_duration_mode = "random_total"
                    chosen = st.multiselect(
                        "Durate possibili",
                        options=slice_options,
                        default=[0.1, 0.25, 0.5, 1.0],
                        format_func=lambda x: f"{x}s",
                        help="Ogni slice pesca a caso una di queste durate."
                    )
                    manual_duration_choices = chosen if chosen else [0.25]
                    slice_dur = manual_duration_choices[0]
                    st.caption(f"_Random tra: {', '.join(f'{d}s' for d in manual_duration_choices)}_")

                else:  # Random in range
                    manual_duration_mode = "random_range"
                    col_ma, col_mb = st.columns(2)
                    with col_ma:
                        dmin = st.select_slider(
                            "Min", options=slice_options, value=0.1,
                            format_func=lambda x: f"{x}s", key="manual_dur_min"
                        )
                    with col_mb:
                        dmax = st.select_slider(
                            "Max", options=slice_options, value=1.0,
                            format_func=lambda x: f"{x}s", key="manual_dur_max"
                        )
                    if dmin > dmax:
                        dmin, dmax = dmax, dmin
                    manual_duration_choices = (dmin, dmax)
                    slice_dur = dmin
                    st.caption(f"_Random continuo tra {dmin}s e {dmax}s._")

                # Subdivisione beat non applicabile in slice manuale: defaults
                beat_subdivision_mode = "fixed"
                beat_subdivision_factor = 1.0
                beat_subdivision_choices = None
                slice_density = 1.0
                react_to_peaks = True
            else:
                manual_duration_mode = "fixed"
                manual_duration_choices = None
                slice_dur = 0.25  # valore di fallback, non usato
                st.caption("_Durata slice determinata dai beat dell'audio._")

                if auto_vj:
                    # PRIMA: la grana del taglio veniva dal valore "subdiv" del
                    # preset di genere (fixed) — una costante scelta a priori
                    # per etichetta di genere, del tutto scollegata dal BPM
                    # reale del brano caricato: un "Techno" a 90 bpm e uno a
                    # 180 bpm ricevevano lo stesso taglio, perche' il preset
                    # non guardava mai il BPM effettivo. ORA: subdivisione
                    # "tempo_adaptive", che calcola il fattore dal BPM
                    # ISTANTANEO reale rilevato punto per punto — il genere
                    # continua comunque a caratterizzare loop/stutter/
                    # crossfade/freeze (quelli si', per design, restano
                    # costanti di stile), solo la grana del taglio ora segue
                    # davvero il tempo del brano invece dell'etichetta scelta.
                    beat_subdivision_mode = "tempo_adaptive"
                    beat_subdivision_factor = preset["subdiv"]  # tenuto per compatibilita' report, non piu' usato per il taglio
                    beat_subdivision_choices = None
                    slice_density = 1.0
                    react_to_peaks = True
                else:
                    # --- Subdivisione Beat ---
                    st.markdown("**Subdivisione beat**")
                    subdiv_mode_label = st.radio(
                        "Modalita'",
                        ["Fissa", "Adattiva al tempo", "Random totale", "Random in range"],
                        horizontal=True,
                        key="subdiv_mode_radio",
                        help=(
                            "Fissa: tutti gli slice usano la stessa misura. "
                            "Adattiva al tempo: la misura si calcola dal BPM istantaneo di "
                            "ogni tratto — piu' veloce = taglio piu' fine, piu' lento = misura "
                            "piu' larga, senza bisogno di sceglierla a mano. "
                            "Random totale: ogni slice pesca una misura a caso tra tutte. "
                            "Random in range: ogni slice pesca tra le misure nel range scelto."
                        )
                    )

                    _subdiv_mode_tmp = {
                        "Fissa": "fixed", "Adattiva al tempo": "tempo_adaptive",
                        "Random totale": "random_total",
                        "Random in range": "random_subset"
                    }[subdiv_mode_label]
                    _react_default = (_subdiv_mode_tmp in ("fixed", "tempo_adaptive")) and cut_source != "onset"
                    react_to_peaks = st.toggle(
                        "Reagisci ai picchi audio",
                        value=_react_default,
                        key=f"react_peaks_{_subdiv_mode_tmp}_{cut_source}",
                        help=(
                            "Se ON, un accento percussivo forte (tom/snare/raffica di "
                            "hi-hat) forza un taglio piu' fine anche se la misura scelta "
                            "e' un'altra — utile in 'Fissa' e 'Adattiva al tempo' per un "
                            "ritmo che reagisce anche ai picchi, non solo al tempo. Se OFF, "
                            "gli accenti non scavalcano mai la misura: in 'Random totale'/"
                            "'Random in range' il taglio resta puramente casuale tra i "
                            "valori previsti, tutti davvero sfruttati. Con Sorgente tagli "
                            "'Onset' i segmenti sono gia' allineati sui colpi reali, quindi "
                            "qui e' OFF di default (una suddivisione forzata aritmetica "
                            "reintrodurrebbe l'imprecisione che Onset elimina). Default: ON "
                            "in 'Fissa'/'Adattiva al tempo' con Beat, OFF con Onset."
                        )
                    )

                    if subdiv_mode_label == "Fissa":
                        beat_subdivision_mode = "fixed"
                        # Auto-adatta il default al BPM rilevato
                        _auto_subdiv = bpm_to_default_subdivision(
                            st.session_state.get("detected_bpm")
                        )
                        subdiv_sel = st.selectbox(
                            "Misura",
                            MEASURE_ORDER,
                            index=MEASURE_ORDER.index(_auto_subdiv),
                            key="subdiv_fixed_sel",
                            help="< 1/1 = taglia il beat in frazioni (stutter/roll) | > 1 = raggruppa piu' beat per slice. Il default si adatta automaticamente al BPM rilevato."
                        )
                        beat_subdivision_factor = MEASURE_FACTORS[subdiv_sel]
                        beat_subdivision_choices = None
                        if beat_subdivision_factor < 1.0:
                            desc = f"frazionato x{round(1/beat_subdivision_factor)}"
                        else:
                            desc = f"{round(beat_subdivision_factor)} beat per slice"
                        _bpm_note = f" · auto da {st.session_state['detected_bpm']:.1f} bpm" if st.session_state.get("detected_bpm") else ""
                        st.caption(f"_Slice = {subdiv_sel} beat — {desc}{_bpm_note}_")

                    elif subdiv_mode_label == "Adattiva al tempo":
                        beat_subdivision_mode = "tempo_adaptive"
                        beat_subdivision_factor = 1.0
                        beat_subdivision_choices = None
                        st.caption(
                            "_Ogni slice si adatta al BPM istantaneo del tratto: "
                            "≥150 bpm → 1/2 beat, 100-150 → 1 beat, 75-100 → 2 beat, "
                            "<75 → 4 beat. Se il brano accelera o rallenta (es. "
                            "ritornello piu' disteso), il taglio si allarga o si "
                            "restringe di conseguenza, senza doverlo impostare a mano._"
                        )

                    elif subdiv_mode_label == "Random totale":
                        beat_subdivision_mode = "random_total"
                        beat_subdivision_factor = 1.0
                        beat_subdivision_choices = None
                        st.caption("_Ogni slice riceve una misura casuale tra 1/16 e 16 beat._")

                    else:  # Random in range
                        beat_subdivision_mode = "random_subset"
                        beat_subdivision_factor = 1.0
                        col_ra, col_rb = st.columns(2)
                        with col_ra:
                            range_min_label = st.selectbox(
                                "Min", MEASURE_ORDER,
                                index=MEASURE_ORDER.index("1/4"),
                                key="subdiv_range_min"
                            )
                        with col_rb:
                            range_max_label = st.selectbox(
                                "Max", MEASURE_ORDER,
                                index=MEASURE_ORDER.index("4"),
                                key="subdiv_range_max"
                            )
                        min_f = MEASURE_FACTORS[range_min_label]
                        max_f = MEASURE_FACTORS[range_max_label]
                        if min_f > max_f:
                            min_f, max_f = max_f, min_f
                        beat_subdivision_choices = [
                            MEASURE_FACTORS[m] for m in MEASURE_ORDER
                            if min_f <= MEASURE_FACTORS[m] <= max_f
                        ]
                        if not beat_subdivision_choices:
                            beat_subdivision_choices = [1.0]
                        labels_in_range = [m for m in MEASURE_ORDER if min_f <= MEASURE_FACTORS[m] <= max_f]
                        st.caption(f"_Random tra: {', '.join(labels_in_range)}_")

                    # --- Densità slice ---
                    st.markdown("**Densita' slice**")
                    slice_density_pct = st.slider(
                        "% beat che generano un taglio",
                        min_value=10, max_value=100, value=100, step=5,
                        key="slice_density_slider",
                        help=(
                            "100% = ogni beat genera un nuovo taglio (comportamento classico). "
                            "Valori inferiori lasciano 'respirare' il video: alcuni beat passano "
                            "senza cambiare sorgente, creando fraseggi piu' lunghi."
                        )
                    )
                    slice_density = slice_density_pct / 100.0
                    if slice_density_pct < 100:
                        st.caption(f"_Solo il {slice_density_pct}% dei beat genera un taglio — il resto continua sulla stessa sorgente._")

                    # --- Stima frammenti previsti (avviso per brani lunghi) ---
                    # fragments_per_beat = 1/sv sia per sv<1 (uno slice diventa
                    # 1/sv frammenti) sia per sv>=1 (sv beat vengono accorpati
                    # in 1 frammento, quindi 1/sv frammenti per beat): formula
                    # unica, media sui fattori in gioco per la modalita' scelta.
                    _bpm_est = st.session_state.get("detected_bpm") or 120.0
                    _dur_est = st.session_state.get("durata_input", 15)
                    _beats_est = max(1.0, (_dur_est * _bpm_est) / 60.0)
                    if beat_subdivision_mode == "fixed":
                        _factors_est = [beat_subdivision_factor]
                    elif beat_subdivision_mode == "tempo_adaptive":
                        _factors_est = [local_bpm_to_subdivision_factor(_bpm_est)]
                    elif beat_subdivision_mode == "random_total":
                        _factors_est = list(MEASURE_FACTORS.values())
                    else:
                        _factors_est = beat_subdivision_choices or [1.0]
                    _mean_fpb = sum(1.0 / f for f in _factors_est) / len(_factors_est)
                    _est_fragments = int(_beats_est * slice_density * _mean_fpb)
                    if _est_fragments > 1200:
                        st.warning(
                            f"⚠️ Con questi parametri sono previsti circa **{_est_fragments} "
                            f"frammenti** per {_dur_est}s di durata finale. Su brani lunghi "
                            f"(3-4 min), tante sorgenti caricate insieme o subdivisioni molto "
                            f"fitte, tanti frammenti rallentano parecchio il rendering e possono "
                            f"causare un riavvio dell'app per esaurimento memoria. Se noti l'app "
                            f"lenta o che si riavvia, prova una misura piu' larga (es. 1/4 invece "
                            f"di 1/16) o abbassa la densita' slice."
                        )
                    elif _est_fragments > 500:
                        st.caption(f"_Frammenti previsti: ~{_est_fragments}._")

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
        durata = st.number_input("Durata Totale (s)", 5, 300, 15, key="durata_input")
        fps    = st.selectbox("FPS", [24, 30])
        formato_label = st.selectbox(
            "Formato",
            ["16:9 (1280x720)", "9:16 (720x1280)", "1:1 (720x720)"],
            key="formato_select",
            help="Crop-to-fill: scala e ritaglia al centro, senza deformare l'immagine "
                 "e senza barre nere. Le sorgenti vengono decodificate gia' vicino a "
                 "questa risoluzione invece che a piena risoluzione nativa — piu' "
                 "leggero e meno a rischio OOM su video lunghi o piu' sorgenti insieme."
        )
        export_size = EXPORT_SIZES.get(formato_label)
        st.markdown("---")

        if app_mode == "Decompose":
            beat_sync = st.toggle("A tempo di musica", value=False,
                help="I tagli seguiranno i beat, le strisce seguiranno il volume.")
        else:
            beat_sync = False
            st.caption("_Beat sync disponibile in modalita' Decompose._")

        use_custom_audio = False
        audio_mix_mode = "custom_only"
        vol_music = 1.0
        vol_original = 1.0
        if audio_file:
            audio_choices = ["Solo musica caricata", "Musica decomposta (stessi tagli del video)",
                              "Solo audio originale dei video", "Mix (musica + originale)",
                              "Mix decomposto (musica decomposta + originale)"]
            audio_mix_choice = st.radio(
                "Traccia audio nel video finale",
                audio_choices,
                index=0,
                help="Il timing resta sempre quello della musica caricata (loop/trim su durata)."
            )
            if audio_mix_choice == "Solo musica caricata":
                audio_mix_mode = "custom_only"
                use_custom_audio = True
            elif audio_mix_choice == "Musica decomposta (stessi tagli del video)":
                audio_mix_mode = "custom_decomposed"
                use_custom_audio = True
                st.caption("_Il brano viene tagliato e rimescolato con la stessa griglia "
                           "ritmica del video: ogni slice video pesca un punto a caso "
                           "diverso nel brano. Stesso ritmo, contenuto decomposto._")
            elif audio_mix_choice == "Solo audio originale dei video":
                audio_mix_mode = "original_only"
                use_custom_audio = False
            elif audio_mix_choice == "Mix decomposto (musica decomposta + originale)":
                audio_mix_mode = "mix_decomposed"
                use_custom_audio = True
                st.caption("_Come 'Musica decomposta', ma mixata con l'audio originale "
                           "dei video invece di sostituirlo._")
                col_v1, col_v2 = st.columns(2)
                with col_v1:
                    vol_music = st.slider("Volume musica decomposta", 0, 200, 100, step=5) / 100.0
                with col_v2:
                    vol_original = st.slider("Volume audio originale", 0, 200, 100, step=5) / 100.0
            else:
                audio_mix_mode = "mix"
                use_custom_audio = True
                col_v1, col_v2 = st.columns(2)
                with col_v1:
                    vol_music = st.slider("Volume musica caricata", 0, 200, 100, step=5) / 100.0
                with col_v2:
                    vol_original = st.slider("Volume audio originale", 0, 200, 100, step=5) / 100.0

        st.markdown("---")

        do_final = st.button("AVVIA RENDERING", use_container_width=True)

        if do_final:
            run_durata = durata
            export_size_run = export_size

            paths = {i: tempfile.NamedTemporaryFile(delete=False, suffix='.mp4').name
                     for i, f in enumerate(files) if f}
            for i, f in enumerate(files):
                if f:
                    with open(paths[i], "wb") as tf: tf.write(f.read())

            if not paths:
                st.error("Carica almeno un video!")
                return

            p_bar = st.progress(0, text="Avvio...")
            beat_times      = None
            rms_envelope    = None
            vj_rms_envelope = None
            vj_band_envelope = None
            vj_onset_times  = None
            beat_count    = 0
            engine        = None
            tmp_audio_path = None
            total_frags   = 0
            cut_schedule  = None

            try:
                # Analisi audio: Decompose beat sync OPPURE VJ Mode beat slice.
                # Sempre calcolata sulla durata PIENA e tenuta in cache: se si
                # rigenera il render cambiando solo un parametro (stutter,
                # subdivisione...) non si rifa' da capo beat-tracking/HPSS,
                # che e' il pezzo piu' lento.
                _audio_cache_key = (
                    getattr(audio_file, "name", None), getattr(audio_file, "size", None), round(durata, 2)
                ) if audio_file else None

                if app_mode == "Decompose" and beat_sync and audio_file:
                    if _audio_cache_key and st.session_state.get("_audio_cache_key") == _audio_cache_key:
                        beat_times, rms_envelope = st.session_state["_audio_cache"]
                    else:
                        p_bar.progress(0.05, text="Analisi audio...")
                        beat_times, rms_envelope, _, _ = analyze_audio(audio_file, durata)
                        st.session_state["_audio_cache_key"] = _audio_cache_key
                        st.session_state["_audio_cache"] = (beat_times, rms_envelope)
                    beat_count = len(beat_times)
                elif app_mode == "VJ Mode" and (beat_slice_mode or freeze_on_beat) and audio_file:
                    if _audio_cache_key and st.session_state.get("_vj_audio_cache_key") == _audio_cache_key:
                        beat_times, vj_rms_envelope, vj_band_envelope, vj_onset_times = st.session_state["_vj_audio_cache"]
                    else:
                        p_bar.progress(0.05, text="Analisi beat...")
                        audio_file.seek(0)
                        beat_times, vj_rms_envelope, vj_band_envelope, vj_onset_times = analyze_audio(audio_file, durata)
                        audio_file.seek(0)  # reset per eventuale uso audio custom dopo
                        st.session_state["_vj_audio_cache_key"] = _audio_cache_key
                        st.session_state["_vj_audio_cache"] = (beat_times, vj_rms_envelope, vj_band_envelope, vj_onset_times)
                    beat_count = len(beat_times)

                engine = VideoEngine()
                engine.load_sources(paths, target_size=export_size_run)

                if app_mode == "Decompose":
                    if mix_mode == "Quote Fisse":
                        final, cut_schedule = engine.generate_fixed_quota(
                            quotas, r_a, r_b, r_rand, run_durata, fps,
                            s_a, s_b, s_rand, scan_dir, p_bar, use_scan,
                            beat_times=beat_times, rms_envelope=rms_envelope,
                            export_size=export_size_run
                        )
                    else:
                        final, cut_schedule = engine.generate(
                            weights, r_a, r_b, r_rand, run_durata, fps,
                            s_a, s_b, s_rand, scan_dir, p_bar, use_scan,
                            beat_times=beat_times, rms_envelope=rms_envelope,
                            export_size=export_size_run
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
                                 f"* Geometria: {scan_dir}\n"
                                 f"* Formato: {formato_label}")
                else:
                    final, total_frags, cut_schedule = generate_dj_remix(
                        engine.video_clips, run_durata, fps,
                        slice_dur, loop_reps, stutter_prob, pitch_glitch, p_bar,
                        beat_slice_mode=beat_slice_mode,
                        beat_times=beat_times,
                        rms_envelope=vj_rms_envelope,
                        band_envelope=vj_band_envelope,
                        crossfade_dur=crossfade_dur,
                        freeze_on_beat=freeze_on_beat,
                        freeze_prob=freeze_prob,
                        freeze_dur=freeze_dur,
                        source_mode=source_mode,
                        source_weights=source_weights,
                        no_repeat=no_repeat,
                        slice_density=slice_density,
                        beat_subdivision_mode=beat_subdivision_mode,
                        beat_subdivision_factor=beat_subdivision_factor,
                        beat_subdivision_choices=beat_subdivision_choices,
                        manual_duration_mode=manual_duration_mode,
                        manual_duration_choices=manual_duration_choices,
                        export_size=export_size_run,
                        react_to_peaks=react_to_peaks,
                        cut_source=cut_source,
                        onset_times=vj_onset_times
                    )
                    mode_label = "VJ Mode"
                    if beat_slice_mode and beat_times:
                        _subdiv_lbl = next((m for m, v in MEASURE_FACTORS.items() if abs(v - beat_subdivision_factor) < 1e-9), "1/1")
                        _subdiv_str = {"fixed": _subdiv_lbl, "tempo_adaptive": "adattiva al tempo", "random_total": "random totale", "random_subset": "random in range"}.get(beat_subdivision_mode, _subdiv_lbl)
                        slice_info = f"beat-driven ({beat_count} beat, subdiv {_subdiv_str})"
                    else:
                        slice_info = f"{slice_dur}s fisso"
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
                                 f"* Audio Mix: {AUDIO_MIX_LABELS.get(audio_mix_mode, audio_mix_mode)}" +
                                 (f" (musica {int(vol_music*100)}% / originale {int(vol_original*100)}%)"
                                  if audio_mix_mode in ("mix", "mix_decomposed") else "") + "\n"
                                 f"* Reattivita' multi-banda: {'ON' if vj_band_envelope else 'OFF'}\n"
                                 f"* Formato: {formato_label}")

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

                    if audio_mix_mode in ("custom_decomposed", "mix_decomposed"):
                        # Gli slice tagliano anche il brano: stessa griglia
                        # di tagli del video (cut_schedule), ma pescati a
                        # caso nel brano invece che in sequenza naturale.
                        audio_clip = decompose_audio_track(audio_clip, cut_schedule, run_durata)
                    elif audio_clip.duration < run_durata:
                        audio_clip = audio_loop(audio_clip, duration=run_durata)
                    else:
                        audio_clip = audio_clip.set_duration(run_durata)

                    if audio_mix_mode in ("mix", "mix_decomposed") and final.audio is not None:
                        music_track = audio_clip.fx(volumex, vol_music)
                        original_track = final.audio.set_duration(run_durata).fx(volumex, vol_original)
                        mixed = CompositeAudioClip([original_track, music_track]).set_duration(run_durata)
                        final = final.set_audio(mixed)
                    else:
                        final = final.set_audio(audio_clip)
                elif audio_mix_mode == "original_only":
                    pass  # mantiene l'audio originale già presente in final

                out_v = os.path.join(tempfile.gettempdir(), f"render_{random.randint(0,9999)}.mp4")
                p_bar.progress(0.75, text="Scrittura video...")
                final.write_videofile(out_v, codec="libx264", audio_codec="aac",
                                      preset="ultrafast", logger=None)
                final.close()
                time.sleep(1.5)

                # --- Anteprima 480p ---
                # NON si riparte da 'final' (l'intera catena di frammenti,
                # crossfade e composizione andrebbe rieseguita una seconda
                # volta: su un brano corto e' invisibile, su 3-4 minuti con
                # centinaia/migliaia di frammenti raddoppia memoria di picco
                # e tempo, proprio il tipo di carico che fa andare in OOM un
                # host con RAM limitata come il piano gratuito di Streamlit
                # Cloud). Si riapre invece il file GIA' scritto su disco: e'
                # un singolo stream h264 semplice, molto piu' leggero da
                # ridecodificare che l'intero grafo di clip.
                p_bar.progress(0.90, text="Generando preview...")
                prev_v = os.path.join(tempfile.gettempdir(), f"preview_{random.randint(0,9999)}.mp4")
                prev_src = VideoFileClip(out_v)
                prev_clip = prev_src.resize(height=480)
                prev_clip.write_videofile(prev_v, codec="libx264", audio_codec="aac",
                                          preset="ultrafast", logger=None)
                prev_clip.close()
                prev_src.close()
                time.sleep(0.5)
                p_bar.progress(1.0, text="Pronto!")

                # Nome condiviso video + report (stesso codice)
                render_id = datetime.now().strftime("%Y%m%d_%H%M%S")
                mode_short = "VJ" if app_mode == "VJ Mode" else "DC"
                render_name = f"loop507_{mode_short}_{render_id}"

                st.session_state.video_path   = out_v
                st.session_state.preview_path = prev_v
                st.session_state.render_name  = render_name

                report_it = f"""[DECOMP_ARCHIVE] // VOL_01 // H.264 // AAC
:: FILE: {render_name}
:: STILE: Minimalismo Computazionale / Glitch Brutalista
:: MOTORE: video_decomposed [05.03]
:: AUDIO: 48 kHz / Float a 32 bit / Punto di Clipping
:: PROCESSO: {mode_label}

:: TECHNICAL LOG SHEET:
* Sorgenti Video: {engine.stats['sources']}
* Frammenti Generati: {total_frags}
* Modalita': {mix_log}
{extra_log}
{'* Beat Sync: ON — ' + str(beat_count) + ' beat rilevati' if beat_sync and audio_file else ''}
{'* Slice Automatico: ON — ' + str(len(vj_onset_times) if cut_source == 'onset' and vj_onset_times else beat_count) + (' onset rilevati' if cut_source == 'onset' else ' beat rilevati') if app_mode == 'VJ Mode' and beat_slice_mode and beat_times else ''}

"Non e' montaggio. E' anatomia di un segnale corrotto."

:: Regia e Algoritmo: Loop507

#loop507 #datanoise #decomposition #glitchart #audiovisual #noisemusic #algorithmicvideo #brutalist #sounddesign #computationalminimalism #signalcorruption #recursivecollapse #newmediaart"""

                report_en = translate_report_to_en(report_it)

                st.session_state.report_data = report_it + "\n\n" + ("=" * 40) + "\n\n" + report_en + "\n"
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
