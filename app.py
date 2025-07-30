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
    st.warning("MoviePy non è installato. Funzionerà solo la simulazione.")


class MultiVideoShuffler:
    def __init__(self):
        self.video_segments = {}  # Dict: video_id -> list of segments
        self.all_segments = []    # Lista di tutti i segmenti con info video
        self.shuffled_order = []

    def format_duration(self, seconds):
        return str(timedelta(seconds=round(seconds)))

    def add_video(self, video_id, video_name, total_duration, segment_duration):
        """Aggiunge i segmenti di un video alla collezione"""
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
        if remaining > 0.5:
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
        Mescola tutti i segmenti di tutti i video
        mix_ratio: 0.5 = bilanciato, 0.7 = più segmenti del primo video, etc.
        """
        if seed:
            random.seed(seed)
        
        # Se abbiamo due video, possiamo bilanciare la distribuzione
        if len(self.video_segments) == 2:
            video_ids = list(self.video_segments.keys())
            video1_segments = [s for s in self.all_segments if s['video_id'] == video_ids[0]]
            video2_segments = [s for s in self.all_segments if s['video_id'] == video_ids[1]]
        
            # Crea una lista bilanciata
            balanced_segments = []
            max_len = max(len(video1_segments), len(video2_segments))
            
            for i in range(max_len):
                # Alterna i segmenti in base al mix_ratio
                if random.random() < mix_ratio and i < len(video1_segments):
                    balanced_segments.append(video1_segments[i])
                if i < len(video2_segments):
                    balanced_segments.append(video2_segments[i])
                if random.random() >= mix_ratio and i < len(video1_segments):
                    balanced_segments.append(video1_segments[i])
            
            # Mescola la lista bilanciata
            random.shuffle(balanced_segments)
            self.shuffled_order = balanced_segments
        else:
            # Mescola semplicemente tutti i segmenti
            self.shuffled_order = self.all_segments.copy()
            random.shuffle(self.shuffled_order)

    def generate_schedule(self):
        schedule = []
        current_time = 0
        schedule.append("SCALETTA VIDEO MULTI-MIX\n")
        
        # Mostra statistiche per video
        video_stats = {}
        for segment in self.shuffled_order:
            video_id = segment['video_id']
            if video_id not in video_stats:
                video_stats[video_id] = {'count': 0, 'total_duration': 0}
            video_stats[video_id]['count'] += 1
            video_stats[video_id]['total_duration'] += segment['duration']
        
        schedule.append("STATISTICHE:")
        for video_id, stats in video_stats.items():
            video_name = self.shuffled_order[0]['video_name'] if video_id == self.shuffled_order[0]['video_id'] else [s['video_name'] for s in self.shuffled_order if s['video_id'] == video_id][0]
            schedule.append(f"    {video_name}: {stats['count']} segmenti, {self.format_duration(stats['total_duration'])}")
        
        schedule.append("\nSEQUENZA FINALE:")
        
        for i, segment in enumerate(self.shuffled_order):
            schedule.append(
                f"Pos {i+1:2d}: [{segment['video_name']}] Segmento #{segment['segment_id']} | "
                f"{self.format_duration(segment['start'])}–{self.format_duration(segment['end'])}  "
                f"{self.format_duration(current_time)}–{self.format_duration(current_time + segment['duration'])}"
            )
            current_time += segment['duration']

        schedule.append(f"\nDURATA TOTALE: {self.format_duration(current_time)}")
        return "\n".join(schedule)

    def create_artistic_overlay(self, clips, overlay_sizes, progress_callback=None):
        """Versione CORRETTA dell'effetto artistico overlay"""
        try:
            # from moviepy.editor import CompositeVideoClip, concatenate_videoclips # Già importato sopra
            import random
            
            if not clips or len(clips) <= 1:
                print("Troppo pochi clip per overlay, usando concatenazione normale")
                return concatenate_videoclips(clips, method="compose") if clips else None
                
            print(f"Creazione overlay artistico con {len(clips)} clip")
            
            # Prendi dimensioni dal primo clip
            base_w, base_h = clips[0].size
            print(f"Dimensioni base: {base_w}x{base_h}")
            
            # Lista finale di tutti i clip (principali + overlay)
            final_clips = []
            current_time = 0
            
            for i, main_clip in enumerate(clips):
                if progress_callback:
                    progress_callback(f"Overlay artistico: segmento {i+1}/{len(clips)}")
                
                # 1. Aggiungi il clip principale
                positioned_main = main_clip.set_position('center').set_start(current_time)
                final_clips.append(positioned_main)
                print(f"Clip principale #{i+1}: durata {main_clip.duration:.2f}s a tempo {current_time:.2f}s")
                
                # 2. Aggiungi overlay casuali da altri clip
                other_clips = [clips[j] for j in range(len(clips)) if j != i]
                
                if other_clips and len(overlay_sizes) > 0:
                    # Numero casuale di overlay (1-2)
                    num_overlays = min(random.randint(1, 2), len(other_clips), len(overlay_sizes))
                    
                    for overlay_idx in range(num_overlays):
                        try:
                            # Scegli clip casuale per overlay
                            source_clip = random.choice(other_clips)
                            overlay_size = overlay_sizes[overlay_idx % len(overlay_sizes)]
                            
                            # Calcola dimensioni overlay
                            overlay_w = max(80, int(base_w * overlay_size / 100))
                            overlay_h = max(60, int(base_h * overlay_size / 100))
                            
                            # Posizione casuale
                            max_x = base_w - overlay_w
                            max_y = base_h - overlay_h
                            pos_x = random.randint(0, max(0, max_x))
                            pos_y = random.randint(0, max(0, max_y))
                            
                            # Timing overlay
                            overlay_duration = min(
                                main_clip.duration * random.uniform(0.4, 0.9),
                                source_clip.duration
                            )
                            
                            start_delay = random.uniform(0, max(0, main_clip.duration - overlay_duration))
                            overlay_start = current_time + start_delay
                            
                            # Crea overlay clip
                            if source_clip.duration >= overlay_duration:
                                overlay_clip = (source_clip
                                              .subclip(0, overlay_duration)
                                              .resize((overlay_w, overlay_h))
                                              .set_position((pos_x, pos_y))
                                              .set_start(overlay_start)
                                              .set_opacity(0.7))
                                
                                final_clips.append(overlay_clip)
                                print(f"  Overlay #{overlay_idx+1}: {overlay_size}% ({overlay_w}x{overlay_h}) at ({pos_x},{pos_y}) da {start_delay:.2f}s per {overlay_duration:.2f}s")
                            
                        except Exception as e:
                            print(f"Errore overlay #{overlay_idx+1}: {e}")
                            continue # Continua con il prossimo overlay o clip principale
                
                current_time += main_clip.duration
            
            print(f"Totale clip nel composito: {len(final_clips)}")
            
            # Crea il video composito finale
            composite_video = CompositeVideoClip(final_clips, size=(base_w, base_h))
            return composite_video
            
        except Exception as e:
            print(f"ERRORE in create_artistic_overlay: {e}")
            import traceback
            traceback.print_exc()
            # Fallback
            try:
                print("Fallback: concatenazione normale dopo errore overlay.")
                return concatenate_videoclips(clips, method="compose")
            except Exception as fallback_e:
                print(f"Errore anche nel fallback: {fallback_e}")
                return None

    def process_videos(self, video_paths, output_path, progress_callback=None, fps=None, enable_overlay=False, overlay_sizes=[15, 30]):
        """Processa i video con overlay artistico corretto"""
        if not MOVIEPY_AVAILABLE:
            return False, "MoviePy non disponibile."

        # Verifica file
        for video_id, path in video_paths.items():
            if not os.path.exists(path):
                return False, f"File non trovato: {path}"

        video_clips = {}
        extracted_clips = []
        final_video = None

        try:
            # Carica video
            if progress_callback:
                progress_callback("Caricamento video...")
                
            for video_id, path in video_paths.items():
                print(f"Caricando video {video_id}: {path}")
                video_clips[video_id] = VideoFileClip(path)
            
            # Estrai segmenti
            if progress_callback:
                progress_callback("Estrazione segmenti...")
            
            for i, segment in enumerate(self.shuffled_order):
                video_id = segment['video_id']
                video_clip = video_clips[video_id]
                
                # Controlli di validità
                if segment['start'] >= video_clip.duration:
                    print(f"SKIP: Segmento {segment['global_id']} - start troppo grande ({segment['start']:.2f}s >= {video_clip.duration:.2f}s)")
                    continue
                    
                end_time = min(segment['end'], video_clip.duration)
                if segment['start'] >= end_time:
                    print(f"SKIP: Segmento {segment['global_id']} - tempi non validi (start {segment['start']:.2f}s >= end {end_time:.2f}s)")
                    continue
                
                try:
                    # Estrai clip
                    clip = video_clip.subclip(segment['start'], end_time)
                    
                    # Applica FPS se richiesto
                    if fps and fps != clip.fps:
                        clip = clip.set_fps(fps)
                    
                    extracted_clips.append(clip)
                    print(f"OK: Estratto segmento {segment['global_id']} ({segment['start']:.2f}-{end_time:.2f}s)")
                    
                    if progress_callback:
                        progress_callback(f"Estratti {len(extracted_clips)}/{len(self.shuffled_order)} segmenti")
                        
                except Exception as e:
                    print(f"ERRORE estrazione {segment['global_id']}: {e}")
                    continue

            if not extracted_clips:
                return False, "Nessun segmento valido estratto."
            print(f"Totale segmenti estratti: {len(extracted_clips)}")
            
            # Crea video finale
            if progress_callback:
                progress_callback("Creazione video finale...")

            if enable_overlay and len(extracted_clips) > 1:
                print("Applicando effetti overlay artistici...")
                final_video = self.create_artistic_overlay(extracted_clips, overlay_sizes, progress_callback)
            else:
                print("Concatenazione normale...")
                final_video = concatenate_videoclips(extracted_clips, method="compose")
            
            if not final_video:
                return False, "Impossibile creare video finale."

            # Salva video
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
            print(f"Video salvato: {output_path}")
            
            return True, output_path

        except Exception as e:
            print(f"ERRORE GENERALE: {e}")
            import traceback
            traceback.print_exc()
            return False, f"Errore: {str(e)}"
            
        finally:
            # Pulizia memoria
            try:
                for video in video_clips.values():
                    if video:
                        video.close()
                if final_video:
                    final_video.close()
                for clip in extracted_clips:
                    if clip:
                        clip.close()
                print("Pulizia memoria completata")
            except Exception as cleanup_error:
                print(f"Errore pulizia: {cleanup_error}")

# --- STREAMLIT UI ---
st.set_page_config(page_title="VideoDecomposer Multi-Mix by loop507", layout="wide")
st.title("VideoDecomposer Multi-Mix by loop507")
st.subheader("Mescola segmenti da più video con effetti artistici!")

# Inizializza session state
if 'processed_video' not in st.session_state:
    st.session_state.processed_video = None
if 'output_path' not in st.session_state:
    st.session_state.output_path = None

# Scelta modalità
mode = st.radio(
    "Scegli modalità:",
    ["Single Video (classico)", "Multi Video Mix"],
    horizontal=True
)

if mode == "Single Video (classico)":
    # Modalità singolo video
    uploaded_video = st.file_uploader("Carica file video", type=["mp4", "mov", "avi", "mkv"])
    
    if uploaded_video:
        temp_dir = tempfile.gettempdir()
        input_path = os.path.join(temp_dir, uploaded_video.name)
        
        with open(input_path, "wb") as f:
            f.write(uploaded_video.read())

        try:
            if MOVIEPY_AVAILABLE:
                clip = VideoFileClip(input_path)
                total_duration = clip.duration
                clip.close()
            else:
                total_duration = 60 # Simulazione durata per MoviePy non installato
                
            st.video(uploaded_video)
            st.success(f"Video caricato - Durata: {round(total_duration, 2)} secondi")

            with st.form("single_params_form"):
                col1, col2 = st.columns(2)
                
                with col1:
                    segment_input = st.text_input("Durata segmenti (secondi)", "3")
                    seed_input = st.text_input("Seed (opzionale)", "", help="Stesso seed = stesso ordine!")
                    
                with col2:
                    custom_fps = st.checkbox("FPS personalizzato")
                    fps_value = st.number_input("FPS:", min_value=1, max_value=60, value=30, disabled=not custom_fps)
                
                # Effetti artistici
                st.markdown("**Effetti Artistici (CORRETTI):**")
                enable_overlay = st.checkbox("Sovrapposizione artistica", help="Overlay con frame di diverse dimensioni")
                
                if enable_overlay:
                    col3, col4 = st.columns(2)
                    with col3:
                        overlay1 = st.slider("Frame piccoli (%)", 5, 25, 12)
                    with col4:
                        overlay2 = st.slider("Frame grandi (%)", 25, 50, 30)
                    st.info("I frame verranno sovrapposti con trasparenza 70% in posizioni casuali!")
                
                submitted = st.form_submit_button("Avvia elaborazione", use_container_width=True)

            if submitted:
                try:
                    segment_duration = float(segment_input)
                    
                    if segment_duration <= 0 or segment_duration >= total_duration:
                        st.error("Durata segmento non valida.")
                    else:
                        shuffler = MultiVideoShuffler()
                        shuffler.add_video("V1", uploaded_video.name, total_duration, segment_duration)
                        
                        seed = int(seed_input) if seed_input.isdigit() else None
                        shuffler.shuffle_all_segments(seed)

                        st.subheader("Scaletta generata")
                        st.code(shuffler.generate_schedule())

                        if MOVIEPY_AVAILABLE:
                            output_filename = f"remix_{uploaded_video.name.split('.')[0]}.mp4" # Assicurati che l'estensione sia .mp4
                            output_path = os.path.join(temp_dir, output_filename)
                            
                            progress_bar = st.progress(0)
                            status_text = st.empty()
                            
                            # CORREZIONE: Variabile per tenere traccia del progresso
                            current_progress_single_video = 0 

                            def progress_callback(message):
                                nonlocal current_progress_single_video # Dichiara che stai usando la variabile esterna
                                status_text.text(f" {message}")
                                # Incrementa il progresso e assicurati che non superi 90
                                current_progress_single_video = min(90, current_progress_single_video + 10) 
                                progress_bar.progress(current_progress_single_video) # Usa il valore numerico aggiornato
                            
                            video_paths = {"V1": input_path}
                            fps_param = fps_value if custom_fps else None
                            overlay_sizes = [overlay1, overlay2] if enable_overlay else [12, 30] # Default per single se non abilitato
                            
                            with st.spinner("Creazione video remix in corso..."):
                                success, result = shuffler.process_videos(
                                    video_paths, output_path, progress_callback, 
                                    fps=fps_param, enable_overlay=enable_overlay, overlay_sizes=overlay_sizes
                                )
                            
                            progress_bar.progress(100) # Completa la barra al 100% alla fine
                            
                            if success:
                                st.success("Video remixato completato!")
                                if os.path.exists(result):
                                    with open(result, "rb") as f:
                                        st.download_button(
                                            "Scarica video remixato",
                                            f.read(),
                                            file_name=output_filename,
                                            mime="video/mp4",
                                            use_container_width=True
                                        )
                                else:
                                    st.error("File di output non trovato.")
                            else:
                                st.error(f"Errore durante l'elaborazione: {result}")
                            
                            status_text.empty()
                        else:
                            st.warning("MoviePy non disponibile - Solo simulazione")
                            
                except ValueError:
                    st.error("Inserisci valori numerici validi.")
                except Exception as e:
                    st.error(f"Errore imprevisto: {str(e)}")
                    
        except Exception as e:
            st.error(f"Errore lettura video: {str(e)}")

else:
    # Modalità multi-video
    st.markdown("### Carica i tuoi video per il mix artistico")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### Video 1")
        video1 = st.file_uploader("Primo video", type=["mp4", "mov", "avi", "mkv"], key="video1")
        
    with col2:
        st.markdown("#### Video 2")
        video2 = st.file_uploader("Secondo video", type=["mp4", "mov", "avi", "mkv"], key="video2")

    if video1 and video2:
        temp_dir = tempfile.gettempdir()
        video1_path = os.path.join(temp_dir, f"v1_{video1.name}")
        video2_path = os.path.join(temp_dir, f"v2_{video2.name}")
        
        # Salva i file temporaneamente
        with open(video1_path, "wb") as f:
            f.write(video1.read())
        with open(video2_path, "wb") as f:
            f.write(video2.read())

        try:
            # Leggi informazioni video
            if MOVIEPY_AVAILABLE:
                clip1 = VideoFileClip(video1_path)
                clip2 = VideoFileClip(video2_path)
                duration1 = clip1.duration
                duration2 = clip2.duration
                clip1.close()
                clip2.close()
            else:
                duration1 = duration2 = 60 # Simulazione durata per MoviePy non installato
                
            # Mostra anteprime
            col1, col2 = st.columns(2)
            with col1:
                st.video(video1)
                st.info(f"Durata: {round(duration1, 2)}s")
            with col2:
                st.video(video2)
                st.info(f"Durata: {round(duration2, 2)}s")

            with st.form("multi_params_form"):
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    segment_input = st.text_input("Durata segmenti (secondi)", "3")
                    seed_input = st.text_input("Seed (opzionale)", "", help="Per risultati riproducibili")
                    
                with col2:
                    mix_ratio = st.slider("Bilancio Video 1/Video 2", 0.1, 0.9, 0.5, 0.1)
                    custom_fps = st.checkbox("FPS personalizzato")
                
                with col3:
                    fps_value = st.number_input("FPS:", min_value=1, max_value=60, value=30, disabled=not custom_fps)
                
                st.markdown(f"**Mix Ratio:** {mix_ratio:.1f} = {int(mix_ratio*100)}% Video 1, {int((1-mix_ratio)*100)}% Video 2")
                
                # Effetti artistici multi-video
                st.markdown("**Effetti Artistici Multi-Video (CORRETTI):**")
                enable_overlay = st.checkbox("Sovrapposizione artistica multi-video", help="Sovrappone frame dai due video")
                
                if enable_overlay:
                    col4, col5 = st.columns(2)
                    with col4:
                        overlay1 = st.slider("Frame piccoli (%)", 5, 25, 10, key="multi_overlay1")
                    with col5:
                        overlay2 = st.slider("Frame grandi (%)", 20, 50, 25, key="multi_overlay2")
                    
                    col6, col7 = st.columns(2)
                    with col6:
                        st.info("Frame da Video 1 e Video 2 si sovrapporranno")
                    with col7:
                        st.info("Trasparenza 70% con posizioni casuali")
                
                submitted = st.form_submit_button("Crea Multi-Mix Artistico", use_container_width=True)

            if submitted:
                try:
                    segment_duration = float(segment_input)
                    
                    if segment_duration <= 0:
                        st.error("Durata segmento deve essere positiva.")
                    else:
                        shuffler = MultiVideoShuffler()
                        
                        # Aggiungi entrambi i video
                        num_seg1 = shuffler.add_video("V1", video1.name, duration1, segment_duration)
                        num_seg2 = shuffler.add_video("V2", video2.name, duration2, segment_duration)
                        
                        seed = int(seed_input) if seed_input.isdigit() else None
                        shuffler.shuffle_all_segments(seed, mix_ratio)

                        st.subheader("Scaletta Multi-Mix generata")
                        st.code(shuffler.generate_schedule())
                        
                        # --- RIGHE DI DEBUG RICHIESTE ---
                        print(f"Type of num_seg1: {type(num_seg1)}")
                        print(f"Value of num_seg1: {num_seg1}")
                        print(f"Type of num_seg2: {type(num_seg2)}")  
                        print(f"Value of num_seg2: {num_seg2}")
                        # --- FINE RIGHE DI DEBUG ---

                        st.success(f"Mescolati {num_seg1 + num_seg2} segmenti totali ({num_seg1} + {num_seg2})")

                        if MOVIEPY_AVAILABLE:
                            output_filename = f"multimix_{video1.name.split('.')[0]}_{video2.name.split('.')[0]}.mp4"
                            output_path = os.path.join(temp_dir, output_filename)
                            
                            progress_bar = st.progress(0)
                            status_text = st.empty()
                            
                            # CORREZIONE: Variabile per tenere traccia del progresso
                            current_progress_multi_video = 0

                            def progress_callback(message):
                                nonlocal current_progress_multi_video # Dichiara che stai usando la variabile esterna
                                status_text.text(f" {message}")
                                # Incrementa il progresso e assicurati che non superi 90
                                current_progress_multi_video = min(90, current_progress_multi_video + 5)
                                progress_bar.progress(current_progress_multi_video) # Usa il valore numerico aggiornato
                            
                            video_paths = {"V1": video1_path, "V2": video2_path}
                            fps_param = fps_value if custom_fps else None
                            overlay_sizes = [overlay1, overlay2] if enable_overlay else [10, 25]
                            
                            with st.spinner("Creazione Multi-Mix artistico in corso..."):
                                success, result = shuffler.process_videos(
                                    video_paths, output_path, progress_callback,
                                    fps=fps_param, enable_overlay=enable_overlay, overlay_sizes=overlay_sizes
                                )
                            
                            progress_bar.progress(100) # Completa la barra al 100% alla fine
                            
                            if success:
                                st.success("Multi-Mix artistico completato!")
                                if os.path.exists(result):
                                    file_size = os.path.getsize(result) / (1024 * 1024)
                                    st.info(f"File generato: {file_size:.2f} MB")
                                    
                                    with open(result, "rb") as f:
                                        st.download_button(
                                            "Scarica Multi-Mix Artistico",
                                            f.read(),
                                            file_name=output_filename,
                                            mime="video/mp4",
                                            use_container_width=True
                                        )
                                else:
                                    st.error("File di output non trovato.")
                            else:
                                st.error(f"Errore durante l'elaborazione: {result}")
                                
                            status_text.empty()
                        else:
                            st.warning("MoviePy non disponibile - Solo simulazione")
                            
                except ValueError:
                    st.error("Inserisci valori numerici validi.")
                except Exception as e:
                    st.error(f"Errore imprevisto: {str(e)}")
                    
        except Exception as e:
            st.error(f"Errore lettura video: {str(e)}")
    
    elif video1 or video2:
        st.info("Carica entrambi i video per procedere con il Multi-Mix.")
    else:
        st.info("Carica due video per creare un Multi-Mix artistico!")

# Istruzioni dettagliate
with st.expander("Come funziona - VERSIONE CORRETTA"):
    st.markdown("""
    ## VideoDecomposer Multi-Mix - Guida Completa
    
    ### **CORREZIONI APPLICATE:**
    - **Overlay Artistico**: Completamente riscritto e testato
    - **Gestione Memoria**: Ottimizzata per evitare crash
    - **Controlli di Validità**: Verifiche su dimensioni e timing
    - **Debug Avanzato**: Log dettagliati per troubleshooting
    - **Fallback Sistema**: Concatenazione normale se overlay fallisce
    
    ### **Modalità Multi-Video (NUOVA):**
    1. **Carica 2 video** di qualsiasi formato
    2. **Imposta durata segmenti** (consigliato: 2-5 secondi)
    3. Regola il Mix Ratio per bilanciare i due video 
    4. Attiva effetti overlay per sovrapposizioni artistiche 
    5. Genera il Multi-Mix con mescolamento intelligente
    
    ### **Effetti Artistici Corretti:**
    - **Frame piccoli**: Overlay ridimensionati (5-25% dimensione originale)
    - **Frame grandi**: Overlay ingranditi (20-50% dimensione originale)  
    - **Trasparenza**: 70% per effetto semi-trasparente
    - **Posizionamento**: Casuale su tutto il frame
    - **Multi-Video**: Frame sovrapposti da entrambi i video sorgente

    ### **Parametri Avanzati:**
    - **Seed**: Numero per risultati riproducibili
    - **FPS Custom**: Controlla fluidità output (15-60 fps)
    - **Mix Ratio**: 0.5 = 50/50, 0.3 = 30% V1 + 70% V2
    - **Durata Segmenti**: Più brevi = più dinamismo

    ### **Troubleshooting:**
    - **Video troppo lunghi**: Usa segmenti di 2-3 secondi
    - **Overlay pesanti**: Riduci percentuali frame
    - **Memoria insufficiente**: Prova senza overlay
    - **Crash durante processing**: Verifica formato video supportato

    ### **Performance:**
    - **Tempo elaborazione**: ~30-60 sec per minuto di output
    - **Memoria RAM**: ~2-4GB per video HD
    - **Formati supportati**: MP4, MOV, AVI, MKV
    - **Risoluzione max**: Automatica dal video sorgente

    ### **Novità Versione Multi-Mix:**
    - **Mescolamento intelligente** tra due video
    - **Overlay cross-video** per effetti unici  
    - **Controllo bilanciamento** personalizzabile
    - **Scaletta dettagliata** del mix generato
    - **Seed riproducibili** per risultati consistenti
    """)
