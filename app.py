import streamlit as st
import os
import random
import tempfile
import moviepy
import traceback
from moviepy.editor import VideoFileClip, concatenate_videoclips, vfx
from PIL import Image
Image.ANTIALIAS = Image.Resampling.LANCZOS
MOVIEPY_AVAILABLE = False
try:
    if moviepy.__version__:
        MOVIEPY_AVAILABLE = True
except Exception:
    pass
if not MOVIEPY_AVAILABLE:
    st.warning("MoviePy non trovato! Alcune funzionalità potrebbero essere disabilitate.")

class MultiVideoShuffler:
    """Gestisce la segmentazione e il mescolamento di più video."""
    def __init__(self):
        self.all_segments = []
        self.shuffled_order = []
        self.video_clips_map = {}
        self.target_size = None # Risoluzione comune per i video

    def add_video(self, video_id, video_name, total_duration, segment_duration):
        """Aggiunge un video e lo segmenta."""
        if total_duration <= 0 or segment_duration <= 0:
            return 0
        
        num_segments = int(total_duration / segment_duration)
        if total_duration % segment_duration != 0:
            num_segments += 1
            
        added_segments = 0
        for i in range(num_segments):
            start_time = i * segment_duration
            end_time = min((i + 1) * segment_duration, total_duration)
            
            # Controllo per evitare segmenti troppo corti
            if end_time - start_time >= 0.1: 
                self.all_segments.append({
                    'video_id': video_id,
                    'start': start_time,
                    'end': end_time,
                    'source_name': video_name,
                    'duration': end_time - start_time
                })
                added_segments += 1
        return added_segments

    def shuffle_all_segments(self, seed=None):
        """Mescola tutti i segmenti di tutti i video in modo casuale."""
        if seed:
            random.seed(seed)
        self.shuffled_order = self.all_segments.copy()
        random.shuffle(self.shuffled_order)

    def generate_schedule(self):
        """Genera una stringa che rappresenta la scaletta dei segmenti mescolati."""
        schedule_str = "Scaletta Segmenti:\n"
        for i, segment in enumerate(self.shuffled_order):
            schedule_str += f"{i+1:03d} - [Video {segment['video_id']}] da {segment['start']:.2f}s a {segment['end']:.2f}s (Fonte: {segment['source_name']})\n"
        return schedule_str
    
    def process_videos(self, video_paths, output_path, progress_callback=None, fps=None, custom_duration=None):
        """Processa i video per creare la sequenza finale, con opzione di durata personalizzata"""
        if not MOVIEPY_AVAILABLE:
            return False, "MoviePy non disponibile."

        for video_id, path in video_paths.items():
            if not os.path.exists(path):
                return False, f"File non trovato: {path}"

        video_clips_original = {}
        extracted_clips_for_final_sequence = []
        final_video = None
        
        try:
            if progress_callback:
                progress_callback("Caricamento video originali...")
            for video_id, path in video_paths.items():
                video_clips_original[video_id] = VideoFileClip(path)
            self.video_clips_map = video_clips_original
            
            # Imposta la risoluzione target basandosi sul primo video
            if video_clips_original:
                first_clip = next(iter(video_clips_original.values()))
                self.target_size = first_clip.size
                st.info(f"Risoluzione video impostata su {self.target_size} per una transizione fluida.")

            if progress_callback:
                progress_callback("Estrazione e riadattamento segmenti...")
            for i, segment in enumerate(self.shuffled_order):
                video_id = segment['video_id']
                video_clip_source = video_clips_original[video_id]
                end_time = min(segment['end'], video_clip_source.duration)
                
                try:
                    # Tenta di estrarre il clip
                    clip = video_clip_source.subclip(segment['start'], end_time)
                    # Ridimensiona il clip alla risoluzione comune per evitare glitch
                    if self.target_size:
                        clip = clip.fx(vfx.resize, newsize=self.target_size)
                        
                    if fps and fps != clip.fps:
                        clip = clip.set_fps(fps)
                    extracted_clips_for_final_sequence.append(clip)
                    if progress_callback:
                        progress_callback(f"Estratti {len(extracted_clips_for_final_sequence)}/{len(self.shuffled_order)} segmenti")
                except Exception as e:
                    # Se fallisce, avvisa ma continua l'elaborazione
                    st.warning(f"⚠️ **Errore durante l'estrazione del segmento {i+1}: {e}** - Il segmento verrà saltato.")
                    continue

            if not extracted_clips_for_final_sequence:
                return False, "Nessun segmento valido estratto. Prova con una durata segmento più lunga."

            if progress_callback:
                progress_callback("Creazione video finale...")
                
            st.info("📹 **Concatenazione segmenti in corso...**")
            final_video = concatenate_videoclips(extracted_clips_for_final_sequence, method="chain")

            if not final_video:
                return False, "Impossibile creare video finale."

            if custom_duration and final_video.duration > custom_duration:
                final_video = final_video.subclip(0, custom_duration)
                st.success(f"✂️ Video tagliato alla durata personalizzata di {custom_duration} secondi.")

            if progress_callback:
                progress_callback("Salvataggio video...")
                
            output_params = {
                'codec': 'libx264',
                'audio_codec': 'aac',
                'temp_audiofile': 'temp-audio.m4a',
                'remove_temp': True,
                'verbose': False,
                'logger': None
            }
            if fps:
                output_params['fps'] = fps

            final_video.write_videofile(output_path, **output_params)

            return True, output_path
        except Exception as e:
            return False, f"Errore: {str(e)}\n{traceback.format_exc()}"
        finally:
            try:
                for video in video_clips_original.values():
                    if video:
                        video.close()
                for clip in extracted_clips_for_final_sequence:
                    if clip:
                        clip.close()
                if final_video:
                    final_video.close()
            except Exception:
                pass

def process_single_video(uploaded_video, input_path, total_duration, segment_input, seed_input, set_custom_fps, fps_value, custom_duration_enabled, custom_duration_input):
    try:
        segment_duration = float(segment_input)
        if segment_duration <= 0.1:
            st.error("❌ La durata dei segmenti deve essere maggiore di 0.1 secondi.")
            return

        shuffler = MultiVideoShuffler()
        num_segments = shuffler.add_video("V1", uploaded_video.name, total_duration, segment_duration)
        st.write(f"Generati {num_segments} segmenti da {uploaded_video.name}")

        seed = int(seed_input) if seed_input.isdigit() else None
        shuffler.shuffle_all_segments(seed)

        st.subheader("📋 Scaletta video generata")
        schedule = shuffler.generate_schedule()
        st.code(schedule, language="text")

        schedule_filename = f"scaletta_remix_{os.path.splitext(uploaded_video.name)[0]}.txt"
        st.download_button(
            "📄 Scarica Scaletta",
            schedule,
            file_name=schedule_filename,
            mime="text/plain"
        )
        
        if MOVIEPY_AVAILABLE:
            st.markdown("---")
            st.subheader("🎬 Elaborazione Video Remix")
            output_filename = f"remix_{os.path.splitext(uploaded_video.name)[0]}.mp4"
            output_path = os.path.join(tempfile.gettempdir(), output_filename)
            video_paths = {"V1": input_path}

            progress_bar = st.progress(0)
            status_text = st.empty()
            st.session_state.current_progress_single_video = 0

            def progress_callback(message):
                status_text.text(f"⏳ {message}")
                st.session_state.current_progress_single_video = min(95, st.session_state.current_progress_single_video + 3)
                progress_bar.progress(st.session_state.current_progress_single_video)

            fps_param = fps_value if set_custom_fps else None

            with st.spinner("⏳ Creazione remix in corso..."):
                success, result = shuffler.process_videos(
                    video_paths, 
                    output_path, 
                    progress_callback, 
                    fps=fps_param, 
                    custom_duration=custom_duration_input if custom_duration_enabled else None
                )

            progress_bar.progress(100)
            status_text.empty()

            if success:
                st.success("🎉 **Remix completato con successo!**")
                if os.path.exists(result):
                    file_size = os.path.getsize(result) / (1024 * 1024)
                    st.metric("Dimensione File", f"{file_size:.2f} MB")
                    if file_size < 50:
                        st.video(result)
                    else:
                        st.warning("File troppo grande per l'anteprima, usa il download.")
                    with open(result, "rb") as f:
                        st.download_button(
                            "⬇️ Scarica Video Remix",
                            f.read(),
                            file_name=output_filename,
                            mime="video/mp4",
                            use_container_width=True
                        )
                else:
                    st.error("❌ File di output non trovato dopo l'elaborazione.")
            else:
                st.error(f"❌ Errore durante l'elaborazione: {result}")
        else:
            st.warning("🔧 MoviePy non disponibile - mostrata solo la scaletta.")
    except ValueError:
        st.error("❌ Inserisci valori numerici validi per la durata dei segmenti e del video finale.")
    except Exception as e:
        st.error(f"❌ Errore imprevisto: {str(e)}")
        with st.expander("🔍 Dettagli errore (per debug)"):
            st.code(traceback.format_exc())

def process_multi_video_generation(uploaded_videos, valid_video_paths, durations, 
                                 segment_input, seed_input, set_custom_fps, fps_value, custom_duration_enabled, custom_duration_input):
    try:
        segment_duration = float(segment_input)
        if segment_duration <= 0.1:
            st.error("❌ La durata dei segmenti deve essere maggiore di 0.1 secondi.")
            return

        if len(valid_video_paths) < 2:
            st.error("❌ Non ci sono abbastanza video validi con durate note per creare un mix. Assicurati che i file siano in un formato supportato.")
            return
        
        shuffler = MultiVideoShuffler()
        st.markdown("---")
        st.subheader("📊 Segmentazione video")
        for i, video in enumerate(uploaded_videos):
            video_id = f"V{i+1}"
            if video_id in durations:
                num_segments = shuffler.add_video(video_id, video.name, durations[video_id], segment_duration)
                st.write(f"• **{video.name}**: generati {num_segments} segmenti.")
        
        seed = int(seed_input) if seed_input.isdigit() else None
        shuffler.shuffle_all_segments(seed)

        st.subheader("📋 Scaletta Multi-Mix generata")
        schedule = shuffler.generate_schedule()
        st.code(schedule, language="text")

        schedule_filename = f"scaletta_multimix.txt"
        st.download_button(
            "📄 Scarica Scaletta",
            schedule,
            file_name=schedule_filename,
            mime="text/plain"
        )

        if MOVIEPY_AVAILABLE:
            st.markdown("---")
            st.subheader("🎬 Elaborazione Video Multi-Mix")
            video_names = "_".join([os.path.splitext(v.name)[0] for v in uploaded_videos])
            output_filename = f"multimix_{video_names}.mp4"
            output_path = os.path.join(tempfile.gettempdir(), output_filename)

            progress_bar = st.progress(0)
            status_text = st.empty()
            st.session_state.current_progress_multi_video = 0

            def progress_callback(message):
                status_text.text(f"⏳ {message}")
                st.session_state.current_progress_multi_video = min(95, st.session_state.current_progress_multi_video + 3)
                progress_bar.progress(st.session_state.current_progress_multi_video)
                
            fps_param = fps_value if set_custom_fps else None

            with st.spinner("⏳ Creazione Multi-Mix in corso..."):
                success, result = shuffler.process_videos(
                    valid_video_paths,
                    output_path,
                    progress_callback,
                    fps=fps_param,
                    custom_duration=custom_duration_input if custom_duration_enabled else None
                )

            progress_bar.progress(100)
            status_text.empty()

            if success:
                st.success("🎉 **Multi-Mix completato con successo!**")
                if os.path.exists(result):
                    file_size = os.path.getsize(result) / (1024 * 1024)
                    st.markdown("### 📈 Statistiche Finali")
                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("Dimensione File", f"{file_size:.2f} MB")
                    with col2:
                        total_segments = len(shuffler.shuffled_order)
                        st.metric("Segmenti Totali", total_segments)

                    if file_size < 50:
                        st.video(result)
                    else:
                        st.warning("File troppo grande per l'anteprima, usa il download.")

                    with open(result, "rb") as f:
                        st.download_button(
                            "⬇️ Scarica Multi-Mix",
                            f.read(),
                            file_name=output_filename,
                            mime="video/mp4",
                            use_container_width=True
                        )
                    
                    with st.expander("📊 Statistiche Dettagliate"):
                        video_stats = {}
                        for segment in shuffler.shuffled_order:
                            video_id = segment['video_id']
                            if video_id not in video_stats:
                                video_stats[video_id] = {'count': 0, 'total_duration': 0}
                            video_stats[video_id]['count'] += 1
                            video_stats[video_id]['total_duration'] += segment['duration']
                        
                        total_duration_final = sum(stats['total_duration'] for stats in video_stats.values())
                        for video_id, stats in video_stats.items():
                            video_name = next((v.name for v in uploaded_videos if f"V{uploaded_videos.index(v)+1}" == video_id), f"Video {video_id}")
                            percentage = (stats['total_duration'] / total_duration_final) * 100
                            st.write(f"**{video_name}:**")
                            st.write(f"  • Segmenti utilizzati: {stats['count']}")
                            st.write(f"  • Durata totale: {stats['total_duration']:.1f}s")
                            st.write(f"  • Percentuale finale: {percentage:.1f}%")
                else:
                    st.error("❌ File di output non trovato dopo l'elaborazione.")
            else:
                st.error(f"❌ Errore durante l'elaborazione: {result}")
                st.write("💡 **Suggerimenti per risolvere:**")
                st.write("• Prova con video più corti")
                st.write("• Usa segmenti più lunghi (3-5 secondi)")
                st.write("• Assicurati che i video siano in formato MP4/H.264")
        else:
            st.warning("🔧 MoviePy non disponibile - mostrata solo la scaletta.")
    except ValueError:
        st.error("❌ Inserisci valori numerici validi per la durata dei segmenti e del video finale.")
    except Exception as e:
        st.error(f"❌ Errore imprevisto: {str(e)}")
        with st.expander("🔍 Dettagli errore (per debug)"):
            st.code(traceback.format_exc())

def handle_single_video_mode(uploaded_video):
    temp_dir = tempfile.gettempdir()
    video_filename = f"single_video_{os.path.basename(uploaded_video.name)}"
    input_path = os.path.join(temp_dir, video_filename)
    with open(input_path, "wb") as f:
        f.write(uploaded_video.read())

    total_duration = 0
    if MOVIEPY_AVAILABLE:
        try:
            with VideoFileClip(input_path) as clip:
                total_duration = clip.duration
        except Exception:
            st.error("❌ Impossibile leggere la durata del video. Assicurati che sia un file video valido.")
            return

    st.markdown("---")
    st.subheader(f"Video caricato: **{uploaded_video.name}**")
    st.video(input_path, width=250)
    st.metric("Durata totale", f"{total_duration:.2f} secondi")

    st.markdown("### ⚙️ Parametri di Elaborazione")
    col1, col2 = st.columns(2)
    with col1:
        set_custom_fps = st.checkbox("Frequenza dei fotogrammi (FPS) personalizzata", help="Spunta per inserire un valore di FPS specifico. Altrimenti, verrà usato l'FPS del video originale.")
    with col2:
        fps_value = st.number_input("FPS:", min_value=1, max_value=60, value=30, disabled=not set_custom_fps)

    custom_duration_enabled = st.checkbox("Imposta durata video finale (Opzionale)", help="Spunta per impostare una durata specifica in secondi. Altrimenti, la durata sarà la somma dei segmenti.")
    custom_duration_input = st.number_input(
        "Durata video finale (secondi)",
        min_value=1,
        value=60,
        disabled=not custom_duration_enabled
    )

    with st.form("single_params_form"):
        col1, col2 = st.columns(2)
        with col1:
            segment_input = st.text_input("Durata segmenti (secondi)", "3")
        with col2:
            seed_input = st.text_input("Seed (opzionale)", "", help="Stesso seed = stesso ordine!")

        submitted = st.form_submit_button("🚀 Avvia elaborazione", use_container_width=True)

    if submitted:
        process_single_video(
            uploaded_video, input_path, total_duration, segment_input, 
            seed_input, set_custom_fps, fps_value, 
            custom_duration_enabled, custom_duration_input
        )

def handle_multi_video_mode():
    st.markdown("### 📹 Carica i tuoi video per il mix")
    cols = st.columns(4)
    uploaded_videos = []
    for i, col in enumerate(cols):
        with col:
            st.markdown(f"#### Video {i+1}")
            video = st.file_uploader(f"Video {i+1}", type=["mp4", "mov", "avi", "mkv"], key=f"video_{i+1}")
            if video:
                uploaded_videos.append(video)

    if not uploaded_videos:
        st.info("Carica almeno un video per iniziare.")
        return

    temp_dir = tempfile.gettempdir()
    video_paths = {}
    durations = {}

    st.success("✅ Video caricati:")
    for i, video in enumerate(uploaded_videos):
        video_id = f"V{i+1}"
        video_filename = f"multi_video_{video_id}_{os.path.basename(video.name)}"
        video_path = os.path.join(temp_dir, video_filename)
        with open(video_path, "wb") as f:
            f.write(video.read())
        video_paths[video_id] = video_path

        if MOVIEPY_AVAILABLE:
            try:
                with VideoFileClip(video_path) as clip:
                    durations[video_id] = clip.duration
                    st.write(f"• **{video.name}** ({video_id}): {round(durations[video_id], 2)} secondi")
            except Exception:
                st.error(f"❌ Impossibile leggere la durata di {video.name}. Il video verrà ignorato.")
        else:
            durations[video_id] = 120
            st.warning("MoviePy non disponibile - durate simulate.")

    num_videos = len(uploaded_videos)
    if num_videos > 0:
        cols_preview = st.columns(num_videos)
        for i, video in enumerate(uploaded_videos):
            with cols_preview[i]:
                st.video(video_paths[f"V{i+1}"], width=250)

    st.markdown("### ⚙️ Parametri Multi-Mix")
    col1, col2 = st.columns(2)
    with col1:
        set_custom_fps = st.checkbox("Frequenza dei fotogrammi (FPS) personalizzata", help="Spunta per inserire un valore di FPS specifico. Altrimenti, verrà usato l'FPS del video originale.")
    with col2:
        fps_value = st.number_input("FPS:", min_value=15, max_value=60, value=24, disabled=not set_custom_fps)

    custom_duration_enabled = st.checkbox("Imposta durata video finale (Opzionale)", help="Spunta per impostare una durata specifica in secondi. Altrimenti, la durata sarà la somma dei segmenti.")
    custom_duration_input = st.number_input(
        "Durata video finale (secondi)",
        min_value=1,
        value=60,
        disabled=not custom_duration_enabled
    )

    with st.form("multi_params_form"):
        col1, col2 = st.columns(2)
        with col1:
            segment_input = st.text_input("Durata segmenti (sec)", "2.5", help="Segmenti più brevi = mix più dinamico")
        with col2:
            seed_input = st.text_input("Seed (opzionale)", "", help="Per risultati riproducibili")
        
        submitted = st.form_submit_button("🚀 Genera Multi-Mix", use_container_width=True)

    if submitted:
        valid_video_paths = {}
        for video_id, path in video_paths.items():
            if video_id in durations and durations[video_id] > 0:
                valid_video_paths[video_id] = path
        
        process_multi_video_generation(
            uploaded_videos, valid_video_paths, durations,
            segment_input, seed_input, set_custom_fps, fps_value,
            custom_duration_enabled, custom_duration_input
        )


def main():
    st.set_page_config(
        page_title="VideoComposer by Loop507",
        page_icon="🎬",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    st.title("🎬 VideoComposer")
    st.markdown("##### by Loop507")
    st.markdown("Benvenuto! Questo strumento ti permette di creare mix casuali con uno o più video. "
                "Scegli una modalità qui sotto per iniziare la tua creazione!")

    mode = st.radio("Seleziona la modalità:", ["Remix Video Singolo", "Multi-Mix"],
                    help="""
                    - **Remix Video Singolo**: crea un remix di un singolo video, mescolandone i segmenti.
                    - **Multi-Mix**: combina i segmenti di più video (fino a 4) per creare un mix dinamico.
                    """)
    st.markdown("---")

    if mode == "Remix Video Singolo":
        uploaded_video = st.file_uploader(
            "Carica un singolo video",
            type=["mp4", "mov", "avi", "mkv"],
            help="Carica il tuo file video per creare un remix."
        )
        if uploaded_video is not None:
            handle_single_video_mode(uploaded_video)
    elif mode == "Multi-Mix":
        handle_multi_video_mode()

if __name__ == "__main__":
    main()
   
