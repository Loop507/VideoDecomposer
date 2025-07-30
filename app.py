import random
import os
import tempfile
from datetime import timedelta
import streamlit as st

# Fix per compatibilità PIL/Pillow con MoviePy
try:
    from PIL import Image
    if not hasattr(Image, 'ANTIALIAS'):
        Image.ANTIALIAS = Image.LANCZOS
    if not hasattr(Image, 'LINEAR'):
        Image.LINEAR = Image.BILINEAR
    # Fix aggiuntivo per versioni molto recenti
    if hasattr(Image, 'Resampling'):
        Image.ANTIALIAS = Image.Resampling.LANCZOS
        Image.LINEAR = Image.Resampling.BILINEAR
except ImportError:
    pass

try:
    from moviepy.editor import VideoFileClip, concatenate_videoclips, CompositeVideoClip
    MOVIEPY_AVAILABLE = True
except ImportError:
    MOVIEPY_AVAILABLE = False
    st.warning("MoviePy non è installato. Funzionerà solo la simulazione.")


class MultiVideoShuffler:
    def __init__(self):
        self.video_segments = {}  # Dict: video_id -> list of segments
        self.all_segments = []    # Lista di tutti i segmenti con info video (dizionari)
        self.shuffled_order = []  # L'ordine mescolato dei segmenti per la sequenza finale
        self.video_clips_map = {} # Mappa video_id -> VideoFileClip caricato originale

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
        """Mescola tutti i segmenti di tutti i video"""
        if seed:
            random.seed(seed)
        
        if len(self.video_segments) == 2:
            video_ids = list(self.video_segments.keys())
            video1_segments = [s for s in self.all_segments if s['video_id'] == video_ids[0]]
            video2_segments = [s for s in self.all_segments if s['video_id'] == video_ids[1]]
        
            balanced_segments = []
            max_len = max(len(video1_segments), len(video2_segments))
            
            for i in range(max_len):
                if i < len(video1_segments) and (random.random() < mix_ratio or i >= len(video2_segments)):
                    balanced_segments.append(video1_segments[i])
                if i < len(video2_segments) and (random.random() >= mix_ratio or i >= len(video1_segments)):
                    balanced_segments.append(video2_segments[i])
            
            random.shuffle(balanced_segments)
            self.shuffled_order = balanced_segments
        else:
            self.shuffled_order = self.all_segments.copy()
            random.shuffle(self.shuffled_order)

    def generate_schedule(self):
        schedule = []
        current_time = 0
        schedule.append("SCALETTA VIDEO MULTI-MIX\n")
        
        video_stats = {}
        for segment in self.shuffled_order:
            video_id = segment['video_id']
            if video_id not in video_stats:
                video_stats[video_id] = {'count': 0, 'total_duration': 0}
            video_stats[video_id]['count'] += 1
            video_stats[video_id]['total_duration'] += segment['duration']
        
        schedule.append("STATISTICHE:")
        for video_id, stats in video_stats.items():
            video_name = next((s['video_name'] for s in self.all_segments if s['video_id'] == video_id), f"Video {video_id}")
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

    def create_artistic_overlay(self, main_clips_sequence, all_segment_dicts, progress_callback=None):
        """
        Crea un video collage artistico con elementi sovrapposti casuali
        """
        try:
            st.write("🎨 **DEBUG:** Iniziando creazione collage artistico...")
            
            if not main_clips_sequence or len(main_clips_sequence) <= 0:
                st.error("Nessun clip principale fornito per il collage")
                return None
            
            # Dimensione canvas
            base_w, base_h = main_clips_sequence[0].size
            st.write(f"📐 **Canvas:** {base_w}x{base_h}")
            
            final_clips = []
            current_time = 0

            if not self.video_clips_map:
                st.error("Mappa video clips non disponibile!")
                return None

            # Tipi di overlay per collage
            overlay_types = [
                ("Quadrato Piccolo", 1.0, 0.15, 0.25, 0.3),
                ("Quadrato Medio", 1.0, 0.25, 0.35, 0.2), 
                ("Orizzontale", 2.0, 0.25, 0.45, 0.2),
                ("Verticale", 0.5, 0.25, 0.45, 0.2),
                ("Panoramico", 3.0, 0.20, 0.40, 0.1),
            ]
            
            total_prob = sum(ot[4] for ot in overlay_types)
            normalized_overlay_types = [(desc, ar, min_s, max_s, prob/total_prob) for desc, ar, min_s, max_s, prob in overlay_types]

            progress_info = st.empty()
            
            for i, main_clip in enumerate(main_clips_sequence):
                progress_info.write(f"🔄 Elaborando segmento principale {i+1}/{len(main_clips_sequence)}")
                
                if progress_callback:
                    progress_callback(f"Creando collage: segmento {i+1}/{len(main_clips_sequence)}")
                
                # ELEMENTO PRINCIPALE DEL COLLAGE (ridimensionato e riposizionato)
                primary_size_factor = random.uniform(0.60, 0.80)
                primary_w = int(base_w * primary_size_factor)
                primary_h = int(base_h * primary_size_factor)
                
                primary_w = max(200, primary_w)
                primary_h = max(150, primary_h)

                # Posizione casuale per elemento principale
                primary_max_x = base_w - primary_w
                primary_max_y = base_h - primary_h
                primary_pos_x = random.randint(0, max(0, primary_max_x))
                primary_pos_y = random.randint(0, max(0, primary_max_y))

                primary_clip_duration = main_clip.duration
                
                # Crea elemento principale del collage
                try:
                    primary_collage_element = (main_clip
                                               .resize((primary_w, primary_h))
                                               .set_position((primary_pos_x, primary_pos_y))
                                               .set_start(current_time)
                                               .set_opacity(0.95))
                except Exception as resize_error:
                    st.warning(f"Errore ridimensionamento principale: {resize_error}")
                    # Fallback senza ridimensionamento
                    primary_collage_element = (main_clip
                                               .set_position((primary_pos_x, primary_pos_y))
                                               .set_start(current_time)
                                               .set_opacity(0.95))

                final_clips.append(primary_collage_element)
                st.write(f"✅ **Elemento Principale #{i+1}:** {primary_w}x{primary_h} a posizione ({primary_pos_x},{primary_pos_y})")
                
                # ELEMENTI SECONDARI DEL COLLAGE
                if all_segment_dicts and len(all_segment_dicts) > 1:
                    num_secondary_overlays = random.randint(2, 4)
                    
                    for overlay_idx in range(num_secondary_overlays):
                        try:
                            # Seleziona tipo overlay
                            choice_weights = [ot[4] for ot in normalized_overlay_types]
                            chosen_overlay_type = random.choices(normalized_overlay_types, weights=choice_weights, k=1)[0]
                            desc, target_aspect_ratio, min_size_perc, max_size_perc, _ = chosen_overlay_type

                            # Seleziona segmento casuale DIVERSO dal principale
                            available_segments = [s for s in all_segment_dicts 
                                                  if s['global_id'] != self.shuffled_order[i]['global_id']]
                            if not available_segments:
                                continue
                                
                            source_segment_info = random.choice(available_segments)
                            source_video_clip_original = self.video_clips_map.get(source_segment_info['video_id'])
                            
                            if not source_video_clip_original:
                                continue

                            # Calcola dimensioni overlay
                            random_size_factor = random.uniform(min_size_perc, max_size_perc)
                            
                            if target_aspect_ratio >= 1.0:
                                overlay_w = int(base_w * random_size_factor)
                                overlay_h = int(overlay_w / target_aspect_ratio)
                            else:
                                overlay_h = int(base_h * random_size_factor)
                                overlay_w = int(overlay_h * target_aspect_ratio)

                            overlay_w = max(100, overlay_w)
                            overlay_h = max(75, overlay_h)
                            
                            # Posizione casuale
                            max_x = base_w - overlay_w
                            max_y = base_h - overlay_h
                            pos_x = random.randint(0, max(0, max_x))
                            pos_y = random.randint(0, max(0, max_y))
                            
                            # Durata overlay
                            secondary_overlay_duration = min(
                                primary_clip_duration * random.uniform(0.4, 0.8),
                                source_video_clip_original.duration,          
                                source_segment_info['duration']               
                            )
                            
                            if secondary_overlay_duration < 0.5:
                                continue
                            
                            # Tempo di inizio nel segmento sorgente
                            max_subclip_start = max(0, source_segment_info['duration'] - secondary_overlay_duration)
                            source_subclip_start_offset = random.uniform(0, max_subclip_start)
                            
                            source_start_time_in_original = source_segment_info['start'] + source_subclip_start_offset
                            source_end_time_in_original = source_start_time_in_original + secondary_overlay_duration

                            # Ritardo nell'apparizione
                            start_delay_in_primary_period = random.uniform(0, max(0, primary_clip_duration - secondary_overlay_duration))
                            overlay_start_time_in_final_video = current_time + start_delay_in_primary_period
                            
                            if source_video_clip_original.duration >= source_end_time_in_original:
                                try:
                                    secondary_overlay_clip = (source_video_clip_original
                                                              .subclip(source_start_time_in_original, source_end_time_in_original)
                                                              .resize((overlay_w, overlay_h))
                                                              .set_position((pos_x, pos_y))
                                                              .set_start(overlay_start_time_in_final_video)
                                                              .set_opacity(0.7))
                                except Exception as overlay_resize_error:
                                    st.warning(f"Errore ridimensionamento overlay: {overlay_resize_error}")
                                    # Fallback senza ridimensionamento
                                    try:
                                        secondary_overlay_clip = (source_video_clip_original
                                                                  .subclip(source_start_time_in_original, source_end_time_in_original)
                                                                  .set_position((pos_x, pos_y))
                                                                  .set_start(overlay_start_time_in_final_video)
                                                                  .set_opacity(0.7))
                                    except Exception as fallback_error:
                                        st.warning(f"Errore anche nel fallback overlay: {fallback_error}")
                                        continue

                                final_clips.append(secondary_overlay_clip)
                                st.write(f"  ➕ **Overlay #{overlay_idx+1}:** {desc} ({overlay_w}x{overlay_h}) da '{source_segment_info['video_name']}'")

                        except Exception as e:
                            st.warning(f"Errore overlay secondario: {e}")
                            continue
                
                current_time += primary_clip_duration
            
            progress_info.write(f"🎬 **Totale elementi collage:** {len(final_clips)}")
            
            if not final_clips:
                st.error("Nessun clip finale da comporre!")
                return None

            # Crea il composito finale
            st.write("🔧 Assemblando video collage...")
            composite_video = CompositeVideoClip(final_clips, size=(base_w, base_h))
            composite_video = composite_video.set_duration(current_time)
            
            st.success("✅ Collage artistico creato con successo!")
            return composite_video
            
        except Exception as e:
            st.error(f"❌ Errore critico nel collage: {e}")
            import traceback
            st.code(traceback.format_exc())
            
            # Fallback: concatenazione normale
            st.warning("🔄 Fallback: concatenazione normale...")
            try:
                return concatenate_videoclips(main_clips_sequence, method="compose")
            except Exception as fallback_e:
                st.error(f"❌ Errore anche nel fallback: {fallback_e}")
                return None

    def process_videos(self, video_paths, output_path, progress_callback=None, fps=None, enable_overlay=False):
        """Processa i video per creare la sequenza finale"""
        if not MOVIEPY_AVAILABLE:
            return False, "MoviePy non disponibile."

        # Verifica file
        for video_id, path in video_paths.items():
            if not os.path.exists(path):
                return False, f"File non trovato: {path}"

        video_clips_original = {}
        extracted_clips_for_final_sequence = []
        final_video = None

        try:
            if progress_callback:
                progress_callback("Caricamento video originali...")
                
            # Carica VideoFileClip originali
            for video_id, path in video_paths.items():
                video_clips_original[video_id] = VideoFileClip(path)
            
            # Salva nella classe per create_artistic_overlay
            self.video_clips_map = video_clips_original 

            # Estrai segmenti per sequenza principale
            if progress_callback:
                progress_callback("Estrazione segmenti...")
            
            for i, segment in enumerate(self.shuffled_order):
                video_id = segment['video_id']
                video_clip_source = video_clips_original[video_id] 
                
                end_time = min(segment['end'], video_clip_source.duration)
                if segment['start'] >= end_time or segment['start'] >= video_clip_source.duration:
                    continue
                
                try:
                    clip = video_clip_source.subclip(segment['start'], end_time)
                    
                    if fps and fps != clip.fps:
                        clip = clip.set_fps(fps)
                    
                    extracted_clips_for_final_sequence.append(clip)
                    
                    if progress_callback:
                        progress_callback(f"Estratti {len(extracted_clips_for_final_sequence)}/{len(self.shuffled_order)} segmenti")
                        
                except Exception as e:
                    continue

            if not extracted_clips_for_final_sequence:
                return False, "Nessun segmento valido estratto."
                
            # Crea video finale
            if progress_callback:
                progress_callback("Creazione video finale...")

            # VERIFICA CRITICA: Il collage viene applicato?
            if enable_overlay and len(extracted_clips_for_final_sequence) > 1:
                st.info("🎨 **Applicando effetti collage artistici...**")
                final_video = self.create_artistic_overlay(
                    extracted_clips_for_final_sequence, 
                    self.all_segments,
                    progress_callback
                )
                
                if final_video is None:
                    return False, "Errore nella creazione del collage artistico"
            else:
                st.info("📹 **Concatenazione normale (collage disabilitato)**")
                final_video = concatenate_videoclips(extracted_clips_for_final_sequence, method="compose")
            
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
            
            return True, output_path

        except Exception as e:
            import traceback
            return False, f"Errore: {str(e)}\n{traceback.format_exc()}"
            
        finally:
            # Pulizia memoria
            try:
                for video in video_clips_original.values():
                    if video:
                        video.close()
                for clip in extracted_clips_for_final_sequence:
                    if clip:
                        clip.close()
                if final_video:
                    final_video.close()
            except Exception as cleanup_error:
                pass

# --- STREAMLIT UI ---
def main():
    st.set_page_config(page_title="VideoDecomposer Multi-Mix by loop507", layout="wide")
    st.title("VideoDecomposer Multi-Mix by loop507")
    st.subheader("Mescola segmenti da più video con effetti collage dinamici!")

    # Inizializza session state
    if 'current_progress_single_video' not in st.session_state:
        st.session_state.current_progress_single_video = 0
    if 'current_progress_multi_video' not in st.session_state:
        st.session_state.current_progress_multi_video = 0

    # Scelta modalità
    mode = st.radio(
        "Scegli modalità:",
        ["Single Video (classico)", "Multi Video Mix"],
        horizontal=True
    )

    if mode == "Single Video (classico)":
        handle_single_video_mode()
    else:
        handle_multi_video_mode()

    # Guida
    with st.expander("📖 Come funziona - VERSIONE COLLAGE DINAMICO"):
        st.markdown("""
        ## VideoDecomposer Multi-Mix - Guida Completa (COLLAGE DINAMICO)
        
        ### **🎨 Effetti Collage:**
        - **Collage Dinamico**: Il frame principale viene ridimensionato e posizionato casualmente
        - **Elementi Secondari**: 2-4 overlay per ogni segmento principale
        - **Forme Casuali**: Quadrati, rettangoli orizzontali/verticali, panoramici
        - **Trasparenza**: Frame principale 95% opaco, overlay 70% trasparenti
        - **Posizioni Random**: Tutti gli elementi sono posizionati casualmente
        
        ### **📋 Modalità Multi-Video:**
        1. Carica 2 video (MP4, MOV, AVI, MKV)
        2. Imposta durata segmenti (2-5 secondi consigliati)
        3. Regola Mix Ratio per bilanciare i video
        4. Attiva "Collage Dinamico" per gli effetti artistici
        5. Genera il Multi-Mix
        
        ### **⚙️ Parametri:**
        - **Seed**: Numero per risultati riproducibili
        - **FPS**: Controlla fotogrammi al secondo
        - **Mix Ratio**: 0.5 = 50%/50%, 0.3 = 30%/70%
        - **Durata Segmenti**: Più brevi = più dinamico
        
        ### **💡 Tips:**
        - Video troppo lunghi possono causare problemi di memoria
        - MP4/H.264 sono i formati più affidabili
        - Segmenti 2-3 secondi per effetto frenetico
        - Chiudi altre app per liberare RAM
        """)

def handle_single_video_mode():
    uploaded_video = st.file_uploader("Carica file video", type=["mp4", "mov", "avi", "mkv"])
    
    if uploaded_video:
        temp_dir = tempfile.gettempdir()
        input_filename = f"single_video_{os.path.basename(uploaded_video.name)}"
        input_path = os.path.join(temp_dir, input_filename)
        
        with open(input_path, "wb") as f:
            f.write(uploaded_video.read())

        try:
            total_duration = 0
            if MOVIEPY_AVAILABLE:
                with VideoFileClip(input_path) as clip:
                    total_duration = clip.duration
                st.success(f"Video caricato - Durata: {round(total_duration, 2)} secondi")
            else:
                total_duration = 60
                st.warning("MoviePy non disponibile, durata video simulata.")
            
            st.video(input_path)

            with st.form("single_params_form"):
                col1, col2 = st.columns(2)
                
                with col1:
                    segment_input = st.text_input("Durata segmenti (secondi)", "3")
                    seed_input = st.text_input("Seed (opzionale)", "", help="Stesso seed = stesso ordine!")
                    
                with col2:
                    custom_fps = st.checkbox("FPS personalizzato")
                    fps_value = st.number_input("FPS:", min_value=1, max_value=60, value=30, disabled=not custom_fps)
                
                st.markdown("**🎨 Effetti Artistici (Collage Dinamico):**")
                enable_overlay = st.checkbox(
                    "Abilita effetto collage dinamico", 
                    help="Il video principale diventa parte del collage con elementi secondari sovrapposti.",
                    key="single_overlay_check"
                )
                
                if enable_overlay:
                    st.info("🎭 I frame verranno mescolati in un collage con forme e dimensioni casuali!")
                
                submitted = st.form_submit_button("🚀 Avvia elaborazione", use_container_width=True)

            if submitted:
                process_single_video(uploaded_video, input_path, total_duration, segment_input, seed_input, custom_fps, fps_value, enable_overlay)
                        
        except Exception as e:
            st.error(f"Errore lettura video: {str(e)}")

def handle_multi_video_mode():
    st.markdown("### 📹 Carica i tuoi video per il mix artistico")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### Video 1")
        video1 = st.file_uploader("Primo video", type=["mp4", "mov", "avi", "mkv"], key="video1")
        
    with col2:
        st.markdown("#### Video 2")
        video2 = st.file_uploader("Secondo video", type=["mp4", "mov", "avi", "mkv"], key="video2")

    if video1 and video2:
        process_multi_video_upload(video1, video2)
    elif video1 or video2:
        st.info("Carica entrambi i video per procedere con il Multi-Mix.")
    else:
        st.info("Carica due video per creare un Multi-Mix artistico!")

def process_single_video(uploaded_video, input_path, total_duration, segment_input, seed_input, custom_fps, fps_value, enable_overlay):
    try:
        segment_duration = float(segment_input)
        
        if segment_duration <= 0 or segment_duration >= total_duration:
            st.error("Durata segmento non valida o troppo grande rispetto alla durata totale del video.")
        else:
            shuffler = MultiVideoShuffler()
            shuffler.add_video("V1", uploaded_video.name, total_duration, segment_duration)
            
            seed = int(seed_input) if seed_input.isdigit() else None
            shuffler.shuffle_all_segments(seed)

            st.subheader("📋 Scaletta generata")
            st.code(shuffler.generate_schedule())

            if MOVIEPY_AVAILABLE:
                output_filename = f"remix_collage_{os.path.splitext(uploaded_video.name)[0]}.mp4" if enable_overlay else f"remix_{os.path.splitext(uploaded_video.name)[0]}.mp4" 
                output_path = os.path.join(tempfile.gettempdir(), output_filename)
                
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                st.session_state.current_progress_single_video = 0 

                def progress_callback(message):
                    status_text.text(f"⏳ {message}")
                    st.session_state.current_progress_single_video = min(90, st.session_state.current_progress_single_video + 5) 
                    progress_bar.progress(st.session_state.current_progress_single_video) 
                
                video_paths = {"V1": input_path}
                fps_param = fps_value if custom_fps else None
                
                with st.spinner("🎬 Creazione video remix in corso..."):
                    success, result = shuffler.process_videos(
                        video_paths, output_path, progress_callback, 
                        fps=fps_param, enable_overlay=enable_overlay
                    )
                
                progress_bar.progress(100)
                
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
                        st.error("File di output non trovato. Si prega di riprovare.")
                else:
                    st.error(f"❌ Errore durante l'elaborazione: {result}")
                
                status_text.empty()
            else:
                st.warning("MoviePy non disponibile - Solo simulazione della scaletta.")
                
    except ValueError:
        st.error("Inserisci valori numerici validi per la durata dei segmenti o il seed.")
    except Exception as e:
        st.error(f"Errore imprevisto: {str(e)}")

def process_multi_video_upload(video1, video2):
    temp_dir = tempfile.gettempdir()
    
    # Salva i file temporanei
    video1_filename = f"multi_video1_{os.path.basename(video1.name)}"
    video2_filename = f"multi_video2_{os.path.basename(video2.name)}"
    video1_path = os.path.join(temp_dir, video1_filename)
    video2_path = os.path.join(temp_dir, video2_filename)
    
    with open(video1_path, "wb") as f:
        f.write(video1.read())
    with open(video2_path, "wb") as f:
        f.write(video2.read())

    try:
        # Ottieni durate video
        durations = {}
        if MOVIEPY_AVAILABLE:
            with VideoFileClip(video1_path) as clip1:
                durations["V1"] = clip1.duration
            with VideoFileClip(video2_path) as clip2:
                durations["V2"] = clip2.duration
            
            st.success(f"✅ Video caricati:")
            st.write(f"• **{video1.name}**: {round(durations['V1'], 2)} secondi")
            st.write(f"• **{video2.name}**: {round(durations['V2'], 2)} secondi")
        else:
            durations = {"V1": 120, "V2": 90}  # Valori simulati
            st.warning("MoviePy non disponibile - durate simulate.")

        # Anteprima video
        col1, col2 = st.columns(2)
        with col1:
            st.video(video1_path)
        with col2:
            st.video(video2_path)

        # Form parametri multi-video
        with st.form("multi_params_form"):
            st.markdown("### ⚙️ Parametri Multi-Mix")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                segment_input = st.text_input("Durata segmenti (sec)", "2.5", help="Segmenti più brevi = mix più dinamico")
                seed_input = st.text_input("Seed (opzionale)", "", help="Per risultati riproducibili")
                
            with col2:
                mix_ratio = st.slider(
                    "Mix Ratio", 
                    min_value=0.1, 
                    max_value=0.9, 
                    value=0.5, 
                    step=0.1,
                    help=f"0.5 = 50%/50%, 0.3 = più {video2.name}"
                )
                custom_fps = st.checkbox("FPS personalizzato")
                
            with col3:
                fps_value = st.number_input("FPS:", min_value=15, max_value=60, value=24, disabled=not custom_fps)
                st.write(f"**Rapporto previsto:**")
                st.write(f"• {video1.name}: {int(mix_ratio*100)}%")
                st.write(f"• {video2.name}: {int((1-mix_ratio)*100)}%")
            
            st.markdown("---")
            st.markdown("**🎨 Effetti Artistici Avanzati:**")
            
            enable_overlay = st.checkbox(
                "🎭 Abilita Collage Dinamico Multi-Video", 
                value=True,
                help="Crea un collage artistico con elementi sovrapposti da entrambi i video"
            )
            
            if enable_overlay:
                st.info("🌟 **Collage Attivo:** I segmenti principali verranno mescolati con overlay casuali dall'altro video!")
                
                col_effect1, col_effect2 = st.columns(2)
                with col_effect1:
                    st.markdown("**Effetti inclusi:**")
                    st.write("• Ridimensionamento dinamico")
                    st.write("• Posizionamento casuale")
                    st.write("• Overlay multipli (2-4 per segmento)")
                    
                with col_effect2:
                    st.markdown("**Forme artistiche:**")
                    st.write("• Quadrati piccoli/medi")
                    st.write("• Rettangoli orizzontali/verticali")
                    st.write("• Panoramici allungati")
            else:
                st.warning("⚠️ Collage disabilitato - verrà usata concatenazione normale")
            
            submitted = st.form_submit_button("🚀 Genera Multi-Mix Collage", use_container_width=True)

        if submitted:
            process_multi_video_generation(
                video1, video2, video1_path, video2_path, durations,
                segment_input, seed_input, mix_ratio, custom_fps, fps_value, enable_overlay
            )
            
    except Exception as e:
        st.error(f"Errore durante il caricamento dei video: {str(e)}")

def process_multi_video_generation(video1, video2, video1_path, video2_path, durations, 
                                 segment_input, seed_input, mix_ratio, custom_fps, fps_value, enable_overlay):
    try:
        segment_duration = float(segment_input)
        
        if segment_duration <= 0:
            st.error("La durata dei segmenti deve essere positiva.")
            return
            
        # Crea shuffler
        shuffler = MultiVideoShuffler()
        
        # Aggiungi video
        num_segments_v1 = shuffler.add_video("V1", video1.name, durations["V1"], segment_duration)
        num_segments_v2 = shuffler.add_video("V2", video2.name, durations["V2"], segment_duration)
        
        st.write(f"📊 **Segmenti generati:** {video1.name} = {num_segments_v1}, {video2.name} = {num_segments_v2}")
        
        # Mescola segmenti
        seed = int(seed_input) if seed_input.isdigit() else None
        shuffler.shuffle_all_segments(seed, mix_ratio)

        # Mostra scaletta
        st.subheader("📋 Scaletta Multi-Mix generata")
        schedule = shuffler.generate_schedule()
        st.code(schedule, language="text")
        
        # Salva scaletta
        schedule_filename = f"scaletta_multimix_{video1.name}_{video2.name}.txt"
        st.download_button(
            "📄 Scarica Scaletta",
            schedule,
            file_name=schedule_filename,
            mime="text/plain"
        )

        # Elaborazione video
        if MOVIEPY_AVAILABLE:
            st.markdown("---")
            st.subheader("🎬 Elaborazione Video Multi-Mix")
            
            # Nome file output
            if enable_overlay:
                output_filename = f"multimix_collage_{os.path.splitext(video1.name)[0]}_{os.path.splitext(video2.name)[0]}.mp4"
            else:
                output_filename = f"multimix_{os.path.splitext(video1.name)[0]}_{os.path.splitext(video2.name)[0]}.mp4"
                
            output_path = os.path.join(tempfile.gettempdir(), output_filename)
            
            # Progress tracking
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            st.session_state.current_progress_multi_video = 0

            def progress_callback(message):
                status_text.text(f"⏳ {message}")
                st.session_state.current_progress_multi_video = min(95, st.session_state.current_progress_multi_video + 3)
                progress_bar.progress(st.session_state.current_progress_multi_video)
            
            # Parametri video
            video_paths = {"V1": video1_path, "V2": video2_path}
            fps_param = fps_value if custom_fps else None
            
            # Elaborazione
            with st.spinner("🎭 Creazione Multi-Mix con effetti collage..."):
                success, result = shuffler.process_videos(
                    video_paths, output_path, progress_callback, 
                    fps=fps_param, enable_overlay=enable_overlay
                )
            
            progress_bar.progress(100)
            status_text.empty()
            
            if success:
                st.success("🎉 **Multi-Mix Collage completato con successo!**")
                
                if os.path.exists(result):
                    file_size = os.path.getsize(result) / (1024 * 1024)
                    
                    # Info risultato
                    st.markdown("### 📈 Statistiche Finali")
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Dimensione File", f"{file_size:.2f} MB")
                    with col2:
                        total_segments = len(shuffler.shuffled_order)
                        st.metric("Segmenti Totali", total_segments)
                    with col3:
                        if enable_overlay:
                            estimated_overlays = total_segments * 3  # Media overlay per segmento
                            st.metric("Overlay Stimati", estimated_overlays)
                        else:
                            st.metric("Tipo", "Standard")
                    
                    # Anteprima risultato
                    if file_size < 50:  # Solo se il file non è troppo grande
                        st.video(result)
                    else:
                        st.warning("File troppo grande per l'anteprima, usa il download.")
                    
                    # Download
                    with open(result, "rb") as f:
                        st.download_button(
                            "⬇️ Scarica Multi-Mix Collage",
                            f.read(),
                            file_name=output_filename,
                            mime="video/mp4",
                            use_container_width=True
                        )
                        
                    # Statistiche dettagliate
                    with st.expander("📊 Statistiche Dettagliate"):
                        video_stats = {}
                        for segment in shuffler.shuffled_order:
                            video_id = segment['video_id']
                            if video_id not in video_stats:
                                video_stats[video_id] = {'count': 0, 'total_duration': 0}
                            video_stats[video_id]['count'] += 1
                            video_stats[video_id]['total_duration'] += segment['duration']
                        
                        for video_id, stats in video_stats.items():
                            video_name = video1.name if video_id == "V1" else video2.name
                            percentage = (stats['total_duration'] / sum(s['total_duration'] for s in video_stats.values())) * 100
                            
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
                st.write("• Disabilita il collage se hai problemi di memoria")
                st.write("• Assicurati che i video siano in formato MP4/H.264")
        else:
            st.warning("🔧 MoviePy non disponibile - mostrata solo la scaletta.")
            
    except ValueError:
        st.error("❌ Inserisci valori numerici validi per la durata dei segmenti.")
    except Exception as e:
        st.error(f"❌ Errore imprevisto: {str(e)}")
        import traceback
        with st.expander("🔍 Dettagli errore (per debug)"):
            st.code(traceback.format_exc())

if __name__ == "__main__":
    main()
