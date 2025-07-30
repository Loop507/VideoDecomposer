import random
import os
import tempfile
from datetime import timedelta
import streamlit as st

try:
    from moviepy.editor import VideoFileClip, concatenate_videoclips, CompositeVideoClip
    MOVIEPY_AVAILABLE = True
except ImportError:
    MOVIEPY_AVAILABLE = False
    st.warning("⚠️ MoviePy non è installato. Funzionerà solo la simulazione e non potrai generare video.")


class MultiVideoShuffler:
    def __init__(self):
        self.video_segments = {}  # Dict: video_id -> list of segments
        self.all_segments = []    # Lista di tutti i segmenti con info video
        self.shuffled_order = []

    def format_duration(self, seconds):
        """Formatta una durata in secondi in un formato leggibile (HH:MM:SS)."""
        return str(timedelta(seconds=round(seconds)))

    def add_video(self, video_id, video_name, total_duration, segment_duration):
        """
        Aggiunge i segmenti di un video alla collezione.

        Parameters:
            video_id (str): ID univoco per il video (es. "V1", "V2").
            video_name (str): Nome del video (per la visualizzazione).
            total_duration (float): Durata totale del video in secondi.
            segment_duration (float): Durata desiderata per ogni segmento in secondi.

        Returns:
            int: Numero di segmenti creati per questo video.
        """
        num_segments = int(total_duration // segment_duration)
        remaining = total_duration % segment_duration
        segments = []

        for i in range(num_segments):
            start = i * segment_duration
            end = min(start + segment_duration, total_duration)
            segment = {
                'video_id': video_id,
                'video_name': video_name,
                'segment_id': i + 1,
                'start': start,
                'end': end,
                'duration': end - start,
                'global_id': f"{video_id}_S{i + 1}"
            }
            segments.append(segment)
            self.all_segments.append(segment)

        # Aggiungi l'ultimo segmento se c'è un resto significativo
        if remaining > 0.5:  # Considera un resto significativo se > 0.5 secondi
            start = num_segments * segment_duration
            segment = {
                'video_id': video_id,
                'video_name': video_name,
                'segment_id': num_segments + 1,
                'start': start,
                'end': total_duration,
                'duration': remaining,
                'global_id': f"{video_id}_S{num_segments + 1}"
            }
            segments.append(segment)
            self.all_segments.append(segment)

        self.video_segments[video_id] = segments
        return len(segments)

    def shuffle_all_segments(self, seed=None, mix_ratio=0.5):
        """
        Mescola tutti i segmenti di tutti i video.

        Parameters:
            seed (int, optional): Un seme per il generatore di numeri casuali per risultati riproducibili.
            mix_ratio (float, optional): Rapporto di mix per due video (0.0-1.0).
                                        0.5 = bilanciato, >0.5 = più segmenti del primo video, ecc.
        """
        if seed:
            random.seed(seed)

        # Se abbiamo esattamente due video, possiamo applicare il bilanciamento
        if len(self.video_segments) == 2:
            video_ids = list(self.video_segments.keys())
            video1_segments = [s for s in self.all_segments if s['video_id'] == video_ids[0]]
            video2_segments = [s for s in self.all_segments if s['video_id'] == video_ids[1]]

            # Reset delle liste per garantire un mix corretto ogni volta
            random.shuffle(video1_segments)
            random.shuffle(video2_segments)

            balanced_segments = []

            # Cicla e aggiungi segmenti alternati in base al mix_ratio
            idx1, idx2 = 0, 0
            while idx1 < len(video1_segments) or idx2 < len(video2_segments):
                if random.random() < mix_ratio and idx1 < len(video1_segments):
                    balanced_segments.append(video1_segments[idx1])
                    idx1 += 1
                elif idx2 < len(video2_segments):
                    balanced_segments.append(video2_segments[idx2])
                    idx2 += 1
                elif idx1 < len(video1_segments): # Aggiungi i rimanenti del video 1 se il video 2 è finito
                    balanced_segments.append(video1_segments[idx1])
                    idx1 += 1

            self.shuffled_order = balanced_segments
        else:
            # Per un singolo video o più di due, mescola semplicemente tutti i segmenti
            self.shuffled_order = self.all_segments.copy()
            random.shuffle(self.shuffled_order)

    def generate_schedule(self):
        """Genera una stringa formattata con la scaletta dei segmenti mescolati."""
        schedule = []
        current_time = 0
        schedule.append("📋 SCALETTA VIDEO MULTI-MIX\n")

        # Mostra statistiche per video
        video_stats = {}
        # Popola video_stats con i nomi dei video iniziali e inizializza i contatori
        for video_id, segments in self.video_segments.items():
            if segments:
                video_stats[video_id] = {'name': segments[0]['video_name'], 'count': 0, 'total_duration': 0}

        # Aggiorna le statistiche in base all'ordine mescolato
        for segment in self.shuffled_order:
            video_id = segment['video_id']
            if video_id in video_stats: # Assicurati che l'ID esista (dovrebbe sempre)
                video_stats[video_id]['count'] += 1
                video_stats[video_id]['total_duration'] += segment['duration']

        schedule.append("📊 STATISTICHE:")
        for video_id, stats in video_stats.items():
            schedule.append(f"    🎬 {stats['name']}: {stats['count']} segmenti, {self.format_duration(stats['total_duration'])}")

        schedule.append("\n🎵 SEQUENZA FINALE:")

        for i, segment in enumerate(self.shuffled_order):
            schedule.append(
                f"🎬 Pos {i+1:2d}: [{segment['video_name']}] Segmento #{segment['segment_id']} | "
                f"{self.format_duration(segment['start'])}–{self.format_duration(segment['end'])} → "
                f"{self.format_duration(current_time)}–{self.format_duration(current_time + segment['duration'])}"
            )
            current_time += segment['duration']

        schedule.append(f"\n⏱️ DURATA TOTALE: {self.format_duration(current_time)}")
        return "\n".join(schedule)

    def create_artistic_overlay(self, clips, overlay_sizes, progress_callback=None):
        """
        Crea un effetto artistico con overlay di frame di diverse dimensioni.

        Parameters:
            clips (list): Lista di oggetti VideoFileClip da cui prendere i segmenti.
            overlay_sizes (list): Lista di percentuali per le dimensioni degli overlay (es. [15, 35]).
            progress_callback (function, optional): Funzione per aggiornare lo stato di avanzamento.

        Returns:
            CompositeVideoClip: Il video composito con gli overlay.
        """
        try:
            if not clips:
                return None

            if len(clips) <= 1:
                # Se c'è solo un clip, la composizione con overlay non ha senso,
                # quindi si concatena normalmente.
                return concatenate_videoclips(clips, method="compose")

            # Prendi il primo clip come base per dimensioni del video finale
            base_clip = clips[0]
            base_w, base_h = base_clip.size

            all_composite_elements = [] # Elementi da comporre (clip principali e overlay)
            current_time = 0

            for i, clip in enumerate(clips):
                if progress_callback:
                    progress_callback(f"Applicazione effetti su segmento {i+1}/{len(clips)}")

                # Aggiungi il clip corrente come elemento principale a schermo intero
                main_clip = clip.set_position('center').set_start(current_time)
                all_composite_elements.append(main_clip)

                # Aggiungi overlay artistici utilizzando altri clip
                # Scegli clip diversi dal principale per evitare sovrapposizioni dello stesso clip su se stesso
                available_overlay_sources = [clips[j] for j in range(len(clips)) if j != i]

                # Limita il numero di overlay per evitare un'immagine troppo caotica
                num_overlays = min(len(overlay_sizes), len(available_overlay_sources), 3) # Max 3 overlay per segmento

                for overlay_idx in range(num_overlays):
                    try:
                        # Scegli un clip casuale tra quelli disponibili per l'overlay
                        overlay_source = random.choice(available_overlay_sources)
                        overlay_size_percent = overlay_sizes[random.randint(0, len(overlay_sizes) - 1)] # Scegli dimensione casuale

                        # Calcola le dimensioni in pixel
                        overlay_w = max(50, int(base_w * overlay_size_percent / 100))
                        overlay_h = max(50, int(base_h * overlay_size_percent / 100))

                        # Posizione casuale (assicurati che rimanga dentro lo schermo)
                        max_x = max(0, base_w - overlay_w)
                        max_y = max(0, base_h - overlay_h)
                        pos_x = random.randint(0, max_x) if max_x > 0 else 0
                        pos_y = random.randint(0, max_y) if max_y > 0 else 0

                        # Durata dell'overlay, più breve del clip principale
                        overlay_duration = min(
                            clip.duration * random.uniform(0.3, 0.8), # Durata casuale tra 30% e 80% del segmento
                            overlay_source.duration # Non superare la durata del video sorgente
                        )

                        # Momento di inizio dell'overlay (casuale all'interno del segmento corrente)
                        max_start_delay = max(0, clip.duration - overlay_duration)
                        overlay_start_delay = random.uniform(0, max_start_delay)
                        overlay_start_time = current_time + overlay_start_delay

                        # Crea il clip dell'overlay
                        if overlay_source.duration >= overlay_duration:
                            overlay_clip = (overlay_source
                                            .subclip(0, overlay_duration) # Prendi dall'inizio del video sorgente
                                            .resize((overlay_w, overlay_h))
                                            .set_position((pos_x, pos_y))
                                            .set_start(overlay_start_time)
                                            .set_opacity(0.6)) # Applica trasparenza per un effetto artistico

                            all_composite_elements.append(overlay_clip)

                    except Exception as overlay_error:
                        print(f"Errore nella creazione dell'overlay {overlay_idx}: {overlay_error}")
                        continue # Continua anche se un overlay fallisce

                current_time += clip.duration # Aggiorna il tempo corrente per il prossimo segmento principale

            # Crea il video composito finale
            if all_composite_elements:
                return CompositeVideoClip(all_composite_elements, size=(base_w, base_h))
            else:
                return concatenate_videoclips(clips, method="compose") # Fallback se non ci sono elementi

        except Exception as e:
            print(f"Errore generale nella creazione dell'overlay artistico: {e}")
            import traceback
            traceback.print_exc()
            # Fallback in caso di errori critici: concatenazione normale
            try:
                return concatenate_videoclips(clips, method="compose")
            except Exception as fallback_error:
                print(f"Errore anche nel fallback di concatenazione: {fallback_error}")
                return None

    def process_videos(self, video_paths, output_path, progress_callback=None, fps=None, enable_overlay=False, overlay_sizes=[15, 35]):
        """
        Processa i video per creare il mix finale.

        Parameters:
            video_paths (dict): Dizionario con video_id e percorso del file video.
            output_path (str): Percorso dove salvare il video di output.
            progress_callback (function, optional): Funzione per aggiornare lo stato di avanzamento.
            fps (int, optional): Fotogrammi al secondo per il video di output. Se None, usa l'FPS originale.
            enable_overlay (bool): Se abilitare gli effetti di sovrapposizione artistica.
            overlay_sizes (list): Percentuali per le dimensioni degli overlay se enable_overlay è True.

        Returns:
            tuple: (bool, str) - True se successo, False altrimenti, e un messaggio.
        """
        if not MOVIEPY_AVAILABLE:
            return False, "❌ MoviePy non disponibile. Installa MoviePy per elaborare i video."

        # Verifica che tutti i file esistano
        for video_id, path in video_paths.items():
            if not os.path.exists(path):
                return False, f"❌ File non trovato: {path}"

        video_clips_objects = {} # Oggetti VideoFileClip aperti
        clips_for_concatenation = [] # I subclip estratti e pronti per essere uniti
        final_video_clip = None # Il clip finale risultante dalla concatenazione/composizione

        try:
            # Carica tutti i video come oggetti VideoFileClip
            if progress_callback:
                progress_callback("Caricamento video originali...")

            for video_id, path in video_paths.items():
                video_clips_objects[video_id] = VideoFileClip(path)

            if progress_callback:
                progress_callback("Estrazione segmenti nell'ordine mescolato...")

            # Estrai i segmenti nell'ordine mescolato
            for i, segment in enumerate(self.shuffled_order):
                video_id = segment['video_id']
                video = video_clips_objects[video_id]

                # Verifica che i tempi del segmento siano validi rispetto alla durata del video originale
                if segment['start'] >= video.duration:
                    print(f"AVVISO: Segmento {segment['global_id']} saltato (start {segment['start']:.2f}s >= durata video {video.duration:.2f}s)")
                    continue

                end_time = min(segment['end'], video.duration) # Assicurati che 'end' non superi la durata del video
                if segment['start'] >= end_time:
                    print(f"AVVISO: Segmento {segment['global_id']} saltato (start {segment['start']:.2f}s >= end {end_time:.2f}s)")
                    continue

                try:
                    print(f"Estraendo [{segment['video_name']}] Segmento #{segment['segment_id']} ({i+1}/{len(self.shuffled_order)}): {segment['start']:.2f}s - {end_time:.2f}s")
                    clip = video.subclip(segment['start'], end_time)

                    # Applica velocità FPS se specificata
                    if fps and fps != clip.fps:
                        clip = clip.set_fps(fps)
                        print(f"  FPS del clip cambiato da {video.fps} a {fps}")

                    clips_for_concatenation.append(clip)

                    if progress_callback:
                        progress_callback(f"Estratto [{segment['video_name']}] Segm. #{segment['segment_id']} ({i+1}/{len(self.shuffled_order)})")

                except Exception as e:
                    print(f"ERRORE: Errore nell'estrazione del segmento {segment['global_id']}: {e}")
                    if progress_callback:
                        progress_callback(f"Errore estrazione segmento {segment['global_id']}: {e}")
                    continue # Continua con il prossimo segmento

            if not clips_for_concatenation:
                return False, "❌ Nessun segmento valido estratto dai video. Controlla le durate dei segmenti e dei video."

            print(f"Totale clip estratti e pronti per la concatenazione: {len(clips_for_concatenation)}")

            if progress_callback:
                progress_callback(f"Concatenazione di {len(clips_for_concatenation)} segmenti...")

            # Concatena o componi i clip nell'ordine mescolato
            if enable_overlay and len(clips_for_concatenation) > 1:
                if progress_callback:
                    progress_callback("Applicazione effetti artistici overlay...")

                final_video_clip = self.create_artistic_overlay(clips_for_concatenation, overlay_sizes, progress_callback)
            else:
                # Concatenazione normale se overlay non abilitato o c'è solo un clip
                final_video_clip = concatenate_videoclips(clips_for_concatenation, method="compose")

            if final_video_clip is None:
                return False, "❌ Impossibile creare il video finale (errore di composizione/concatenazione)."

            if progress_callback:
                progress_callback("Salvataggio video finale...")

            # Parametri di output per MoviePy
            output_params = {
                'codec': 'libx264',
                'audio_codec': 'aac',
                'temp_audiofile': 'temp-audio.m4a', # File temporaneo per l'audio
                'remove_temp': True, # Rimuovi il file temporaneo dopo l'uso
                'verbose': False, # Nasconde l'output dettagliato di MoviePy
                'logger': None # Disabilita il logger di MoviePy
            }

            # Aggiungi FPS se specificato
            if fps:
                output_params['fps'] = fps

            # Scrivi il video finale
            final_video_clip.write_videofile(output_path, **output_params)

            print(f"Video finale multi-mix salvato: {output_path}")
            return True, output_path

        except Exception as e:
            print(f"ERRORE CRITICO durante l'elaborazione del video: {str(e)}")
            import traceback
            traceback.print_exc() # Stampa lo stack trace per debug
            return False, f"❌ Errore critico durante l'elaborazione del video: {str(e)}"

        finally:
            # Pulizia: chiudi tutti i clip di MoviePy aperti per rilasciare le risorse
            try:
                for video_obj in video_clips_objects.values():
                    if video_obj:
                        video_obj.close()
                for clip_obj in clips_for_concatenation:
                    if clip_obj:
                        clip_obj.close()
                if final_video_clip:
                    final_video_clip.close()
            except Exception as cleanup_error:
                print(f"AVVISO: Errore durante la pulizia dei clip MoviePy: {cleanup_error}")


# --- STREAMLIT UI ---
st.set_page_config(page_title="VideoDecomposer Multi-Mix by loop507", layout="wide")
st.title("🎬 VideoDecomposer Multi-Mix by loop507")
st.subheader("🔀 Mescola segmenti da più video!")

# Inizializza session state
if 'processed_video' not in st.session_state:
    st.session_state.processed_video = None
if 'output_path' not in st.session_state:
    st.session_state.output_path = None

# Scelta modalità
mode = st.radio(
    "🎯 Scegli modalità:",
    ["🎬 Single Video (classico)", "🎭 Multi Video Mix"],
    horizontal=True
)

if mode == "🎬 Single Video (classico)":
    # Modalità singolo video
    uploaded_video = st.file_uploader("📤 Carica file video", type=["mp4", "mov", "avi", "mkv"])

    if uploaded_video:
        temp_dir = tempfile.gettempdir()
        input_path = os.path.join(temp_dir, uploaded_video.name)

        # Salva il file caricato in un percorso temporaneo
        with open(input_path, "wb") as f:
            f.write(uploaded_video.read())

        try:
            total_duration = 0
            if MOVIEPY_AVAILABLE:
                # Usa MoviePy per ottenere la durata reale se disponibile
                try:
                    clip = VideoFileClip(input_path)
                    total_duration = clip.duration
                    clip.close()
                except Exception as e:
                    st.warning(f"⚠️ Impossibile leggere la durata con MoviePy ({e}). Usando durata predefinita.")
                    total_duration = 60 # Durata di fallback
            else:
                total_duration = 60 # Durata di fallback se MoviePy non c'è

            st.video(uploaded_video)
            st.success(f"✅ Video caricato - Durata: {round(total_duration, 2)} secondi")

            with st.form("single_params_form"):
                col1, col2 = st.columns(2)

                with col1:
                    segment_input = st.text_input("✂️ Durata segmenti (secondi)", "3")
                    seed_input = st.text_input("🎲 Seed (opzionale)", "", help="Numero per risultati riproducibili. Stesso seed = stesso ordine!")
                with col2:
                    # Controlli avanzati
                    st.markdown("**🎬 Controlli Video:**")
                    custom_fps = st.checkbox("📹 FPS personalizzato")
                    fps_value = st.number_input("FPS:", min_value=1, max_value=60, value=30, disabled=not custom_fps)

                # Effetti artistici
                st.markdown("**🎨 Effetti Artistici:**")
                enable_overlay = st.checkbox("✨ Sovrapposizione artistica", help="Crea overlay con frame di diverse dimensioni")

                if enable_overlay:
                    col3, col4 = st.columns(2)
                    with col3:
                        overlay1 = st.slider("📐 Overlay piccolo (%)", 5, 30, 15)
                    with col4:
                        overlay2 = st.slider("📐 Overlay grande (%)", 25, 50, 35)

                submitted = st.form_submit_button("🚀 Avvia elaborazione", use_container_width=True)

            if submitted:
                try:
                    segment_duration = float(segment_input)

                    if segment_duration <= 0 or segment_duration >= total_duration:
                        st.error("❌ Durata segmento non valida. Deve essere positiva e inferiore alla durata totale del video.")
                    else:
                        shuffler = MultiVideoShuffler()
                        shuffler.add_video("V1", uploaded_video.name, total_duration, segment_duration)

                        seed = int(seed_input) if seed_input.isdigit() else None
                        shuffler.shuffle_all_segments(seed)

                        st.subheader("📋 Scaletta generata")
                        st.code(shuffler.generate_schedule())

                        if MOVIEPY_AVAILABLE:
                            output_filename = f"remix_{os.path.splitext(uploaded_video.name)[0]}.mp4" # Nome file pulito
                            output_path = os.path.join(temp_dir, output_filename)

                            progress_bar = st.progress(0)
                            status_text = st.empty()

                            # Funzione di callback per aggiornare la barra di progresso e lo stato
                            def progress_callback_single(message):
                                status_text.text(f"🎞️ {message}")

                            video_paths = {"V1": input_path}

                            # Parametri per elaborazione
                            fps_param = fps_value if custom_fps else None
                            overlay_sizes = [overlay1, overlay2] if enable_overlay else [15, 35] # Usa i valori slider solo se abilitato

                            with st.spinner("⏳ Creazione video remixato in corso..."):
                                success, result = shuffler.process_videos(
                                    video_paths, output_path, progress_callback_single,
                                    fps=fps_param, enable_overlay=enable_overlay, overlay_sizes=overlay_sizes
                                )

                            progress_bar.progress(100) # Completa la barra al termine

                            if success:
                                st.success("✅ Video remixato completato!")

                                if os.path.exists(result):
                                    file_size = os.path.getsize(result) / (1024 * 1024)
                                    st.info(f"📁 File generato: {file_size:.2f} MB")

                                    with open(result, "rb") as f:
                                        st.download_button(
                                            "⬇️ Scarica video remixato",
                                            f.read(),
                                            file_name=output_filename,
                                            mime="video/mp4",
                                            use_container_width=True
                                        )
                                else:
                                    st.error("❌ File di output non trovato dopo l'elaborazione.")
                            else:
                                st.error(f"❌ {result}")

                            status_text.empty() # Pulisce il messaggio di stato
                        else:
                            st.warning("⚠️ MoviePy non è installato. Solo la simulazione della scaletta è disponibile.")

                except ValueError:
                    st.error("❌ Inserisci valori numerici validi per la durata del segmento e il seed.")
                except Exception as e:
                    st.error(f"❌ Si è verificato un errore inatteso: {str(e)}")
                    # Debug: st.exception(e) # Per mostrare lo stack trace completo in Streamlit

        except Exception as e:
            st.error(f"❌ Errore durante la lettura o il caricamento del video: {str(e)}")

else:
    # Modalità multi-video
    st.markdown("### 🎭 Carica i tuoi video per il mix")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### 🎬 Video 1")
        video1 = st.file_uploader("📤 Primo video", type=["mp4", "mov", "avi", "mkv"], key="video1")

    with col2:
        st.markdown("#### 🎬 Video 2")
        video2 = st.file_uploader("📤 Secondo video", type=["mp4", "mov", "avi", "mkv"], key="video2")

    if video1 and video2:
        temp_dir = tempfile.gettempdir()
        video1_path = os.path.join(temp_dir, f"v1_{video1.name}")
        video2_path = os.path.join(temp_dir, f"v2_{video2.name}")

        # Salva i file caricati
        with open(video1_path, "wb") as f:
            f.write(video1.read())
        with open(video2_path, "wb") as f:
            f.write(video2.read())

        try:
            duration1 = 0
            duration2 = 0
            if MOVIEPY_AVAILABLE:
                try:
                    clip1 = VideoFileClip(video1_path)
                    clip2 = VideoFileClip(video2_path)
                    duration1 = clip1.duration
                    duration2 = clip2.duration
                    clip1.close()
                    clip2.close()
                except Exception as e:
                    st.warning(f"⚠️ Impossibile leggere la durata con MoviePy ({e}). Usando durata predefinita.")
                    duration1 = duration2 = 60 # Durata di fallback
            else:
                duration1 = duration2 = 60 # Durata di fallback se MoviePy non c'è

            # Mostra anteprime
            col1, col2 = st.columns(2)
            with col1:
                st.video(video1)
                st.info(f"📏 Durata: {round(duration1, 2)}s")
            with col2:
                st.video(video2)
                st.info(f"📏 Durata: {round(duration2, 2)}s")

            with st.form("multi_params_form"):
                col1, col2, col3 = st.columns(3)

                with col1:
                    segment_input = st.text_input("✂️ Durata segmenti (secondi)", "3")
                    seed_input = st.text_input("🎲 Seed (opzionale)", "", help="Per risultati riproducibili")
                with col2:
                    mix_ratio = st.slider("⚖️ Bilancio Video 1/Video 2", 0.1, 0.9, 0.5, 0.1)
                    # Controlli FPS
                    custom_fps = st.checkbox("📹 FPS personalizzato")
                with col3:
                    fps_value = st.number_input("FPS:", min_value=1, max_value=60, value=30, disabled=not custom_fps)

                st.markdown(f"**Mix Ratio:** {mix_ratio:.1f} = {int(mix_ratio*100)}% Video 1, {int((1-mix_ratio)*100)}% Video 2")

                # Effetti artistici
                st.markdown("**🎨 Effetti Artistici Multi-Video:**")
                enable_overlay = st.checkbox("✨ Sovrapposizione artistica", help="Sovrappone frame dei due video con diverse dimensioni")

                if enable_overlay:
                    col4, col5 = st.columns(2)
                    with col4:
                        overlay1 = st.slider("📐 Frame piccoli (%)", 5, 25, 12, key="multi_overlay1")
                    with col5:
                        overlay2 = st.slider("📐 Frame grandi (%)", 20, 50, 30, key="multi_overlay2")

                    st.info("🎭 L'effetto sovrapporrà frame casuali dai due video creando un mix artistico!")

                submitted = st.form_submit_button("🎭 Crea Multi-Mix", use_container_width=True)

            if submitted:
                try:
                    segment_duration = float(segment_input)

                    if segment_duration <= 0:
                        st.error("❌ Durata segmento deve essere positiva.")
                    elif segment_duration >= duration1 and segment_duration >= duration2:
                        st.error("❌ La durata del segmento deve essere inferiore ad almeno uno dei due video.")
                    else:
                        shuffler = MultiVideoShuffler()

                        # Aggiungi entrambi i video
                        num_seg1 = shuffler.add_video("V1", video1.name, duration1, segment_duration)
                        num_seg2 = shuffler.add_video("V2", video2.name, duration2, segment_duration)

                        seed = int(seed_input) if seed_input.isdigit() else None
                        shuffler.shuffle_all_segments(seed, mix_ratio)

                        st.subheader("📋 Scaletta Multi-Mix generata")
                        st.code(shuffler.generate_schedule())

                        st.success(f"✅ Mescolati {num_seg1 + num_seg2} segmenti totali ({num_seg1} + {num_seg2})")

                        if MOVIEPY_AVAILABLE:
                            # Genera un nome file più significativo per il multi-mix
                            base_name1 = os.path.splitext(video1.name)[0]
                            base_name2 = os.path.splitext(video2.name)[0]
                            output_filename = f"multimix_{base_name1}_and_{base_name2}.mp4"
                            output_path = os.path.join(temp_dir, output_filename)

                            progress_bar = st.progress(0)
                            status_text = st.empty()

                            # Funzione di callback per aggiornare la barra di progresso e lo stato
                            def progress_callback_multi(message):
                                status_text.text(f"🎭 {message}")

                            video_paths = {"V1": video1_path, "V2": video2_path}

                            # Parametri per elaborazione
                            fps_param = fps_value if custom_fps else None
                            overlay_sizes = [overlay1, overlay2] if enable_overlay else [12, 30] # Usa i valori slider solo se abilitato

                            with st.spinner("⏳ Creazione Multi-Mix in corso..."):
                                success, result = shuffler.process_videos(
                                    video_paths, output_path, progress_callback_multi,
                                    fps=fps_param, enable_overlay=enable_overlay, overlay_sizes=overlay_sizes
                                )

                            progress_bar.progress(100) # Completa la barra al termine

                            if success:
                                st.success("✅ Multi-Mix completato!")

                                if os.path.exists(result):
                                    file_size = os.path.getsize(result) / (1024 * 1024)
                                    st.info(f"📁 File generato: {file_size:.2f} MB")

                                    with open(result, "rb") as f:
                                        st.download_button(
                                            "⬇️ Scarica Multi-Mix",
                                            f.read(),
                                            file_name=output_filename,
                                            mime="video/mp4",
                                            use_container_width=True
                                        )
                                else:
                                    st.error("❌ File di output non trovato dopo l'elaborazione.")
                            else:
                                st.error(f"❌ {result}")

                            status_text.empty() # Pulisce il messaggio di stato
                        else:
                            st.warning("⚠️ MoviePy non è installato. Solo la simulazione della scaletta è disponibile.")

                except ValueError:
                    st.error("❌ Inserisci valori numerici validi per la durata del segmento e il seed.")
                except Exception as e:
                    st.error(f"❌ Si è verificato un errore inatteso: {str(e)}")
                    # Debug: st.exception(e) # Per mostrare lo stack trace completo in Streamlit

        except Exception as e:
            st.error(f"❌ Errore durante la lettura o il caricamento dei video: {str(e)}")

    elif video1 or video2:
        st.info("📂 Carica entrambi i video per procedere con il Multi-Mix.")
    else:
        st.info("📂 Carica due video per creare un Multi-Mix!")

---
### ℹ️ Come funziona il Multi-Mix - AGGIORNATO

**VideoDecomposer Multi-Mix** ti permette di:

### 🎬 Modalità Single Video:
* Stessa funzionalità della versione originale.
* Divide un video in segmenti e li rimescola.
* **Novità:** Controlli **FPS** e **effetti artistici** corretti!

### 🎭 Modalità Multi-Mix:
* **Carica 2 video** diversi.
* **Imposta durata segmenti** (es. 3 secondi).
* **Bilancia il mix** con lo slider "Bilancio Video 1/Video 2":
    * **Valore 0.5 (centrale):** I segmenti di entrambi i video vengono mescolati in modo **equilibrato**.
    * **Valore > 0.5 (es. 0.7):** Verranno privilegiati più segmenti dal **Video 1**.
    * **Valore < 0.5 (es. 0.3):** Verranno privilegiati più segmenti dal **Video 2**.
* **Seed (opzionale):** Usa lo stesso numero di "seed" per ottenere lo stesso ordine di segmenti ogni volta che esegui il mix con gli stessi video e parametri.
* **FPS personalizzato:** Seleziona questa opzione per impostare manualmente i fotogrammi al secondo (FPS) del video di output.
* **Sovrapposizione artistica:** Attiva questa opzione per creare un effetto visivo dinamico, dove frammenti casuali di uno dei due video vengono sovrapposti al video principale, con dimensioni e posizioni variabili.

Premi "**Crea Multi-Mix**" e il sistema mescolerà i segmenti dei due video in base alle tue impostazioni, generando un video unico e creativo!
