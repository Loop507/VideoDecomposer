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

    def shuffle_all_segments(self, seed=None, video_weights=None):
        """Mescola tutti i segmenti di tutti i video con pesi personalizzabili"""
        if seed:
            random.seed(seed)
        
        num_videos = len(self.video_segments)
        
        if num_videos == 1:
            # Single video - shuffle normale
            self.shuffled_order = self.all_segments.copy()
            random.shuffle(self.shuffled_order)
            
        elif num_videos >= 2:
            # Multi video - bilanciamento intelligente
            video_ids = list(self.video_segments.keys())
            
            # Se non ci sono pesi, usa distribuzione uniforme
            if not video_weights:
                video_weights = {vid: 1.0/num_videos for vid in video_ids}
            
            # Normalizza i pesi
            total_weight = sum(video_weights.values())
            normalized_weights = {vid: w/total_weight for vid, w in video_weights.items()}
            
            # Raggruppa segmenti per video
            video_segment_lists = {}
            for vid in video_ids:
                video_segment_lists[vid] = [s for s in self.all_segments if s['video_id'] == vid]
            
            # Crea sequenza bilanciata
            balanced_segments = []
            max_segments = max(len(segments) for segments in video_segment_lists.values())
            
            for i in range(max_segments):
                # Per ogni posizione, scegli da quale video prendere
                available_videos = [vid for vid, segments in video_segment_lists.items() 
                                  if i < len(segments)]
                
                if not available_videos:
                    break
                
                # Scegli video basandosi sui pesi
                if len(available_videos) == 1:
                    chosen_video = available_videos[0]
                else:
                    weights = [normalized_weights[vid] for vid in available_videos]
                    chosen_video = random.choices(available_videos, weights=weights, k=1)[0]
                
                balanced_segments.append(video_segment_lists[chosen_video][i])
            
            # Shuffle finale per randomizzare l'ordine
            random.shuffle(balanced_segments)
            self.shuffled_order = balanced_segments

    def generate_schedule(self):
        schedule = []
        current_time = 0
        schedule.append("SCALETTA VIDEO MULTI-MIX (FINO A 4 VIDEO)\n")
        
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
            percentage = (stats['total_duration'] / sum(s['total_duration'] for s in video_stats.values())) * 100
            schedule.append(f"    {video_name}: {stats['count']} segmenti, {self.format_duration(stats['total_duration'])} ({percentage:.1f}%)")
        
        schedule.append(f"\nTOTALE VIDEO UTILIZZATI: {len(video_stats)}")
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
                    # Più overlay se abbiamo più video
                    num_videos = len(set(s['video_id'] for s in all_segment_dicts))
                    num_secondary_overlays = random.randint(2, min(6, 2 + num_videos))
                    
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
    st.set_page_config(page_title="VideoDecomposer Multi-Mix PRO by loop507", layout="wide")
    st.title("VideoDecomposer Multi-Mix PRO by loop507")
    st.subheader("Mescola segmenti da 1 a 4 video con effetti collage dinamici!")

    # Inizializza session state
    if 'current_progress_single_video' not in st.session_state:
        st.session_state.current_progress_single_video = 0
    if 'current_progress_multi_video' not in st.session_state:
        st.session_state.current_progress_multi_video = 0

    # Scelta modalità
    mode = st.radio(
        "Scegli modalità:",
        ["Single Video (classico)", "Multi Video Mix (2-4 video)"],
        horizontal=True
    )

    if mode == "Single Video (classico)":
        handle_single_video_mode()
    else:
        handle_multi_video_mode()

    # Guida
    with st.expander("📖 Come funziona - VERSIONE MULTI-VIDEO PRO"):
        st.markdown("""
        ## VideoDecomposer Multi-Mix PRO - Guida Completa
        
        ### **🎯 Novità Versione PRO:**
        - **Fino a 4 video contemporaneamente** (flessibile da 1 a 4)
        - **Controllo pesi intelligente** per bilanciare la presenza di ogni video
        - **Collage multi-sorgente** con overlay da tutti i video caricati
        - **Statistiche avanzate** con percentuali di utilizzo
        
        ### **🎨 Effetti Collage Multi-Video:**
        - **Collage Dinamico**: Il frame principale viene ridimensionato e posizionato casualmente
        - **Elementi Multi-Sorgente**: 2-6 overlay per segmento (più video = più overlay)
        - **Forme Artistiche**: Quadrati, rettangoli, panoramici con aspect ratio variabili
        - **Trasparenza Stratificata**: Frame principale 95%, overlay 70%
        - **Posizionamento Intelligente**: Distribuzione casuale non sovrapposta
        
        ### **📋 Modalità Multi-Video PRO:**
        1. Carica da 2 a 4 video (MP4, MOV, AVI, MKV)
        2. Imposta durata segmenti (1-5 secondi per effetti diversi)
        3. Regola i pesi per bilanciare la presenza di ogni video
        4. Attiva "Collage Dinamico" per effetti artistici avanzati
        5. Genera il Multi-Mix PRO
        
        ### **⚙️ Parametri Avanzati:**
        - **Seed**: Numero per risultati riproducibili
        - **FPS**: Controlla fotogrammi al secondo (15-60)
        - **Pesi Video**: Controllo percentuale presenza (es. 40%-30%-20%-10%)
        - **Durata Segmenti**: 1s=frenetico, 3s=dinamico, 5s=fluido
        
        ### **💡 Tips PRO:**
        - **2 video**: Mix classico bilanciato
        - **3 video**: Effetti collage più complessi
        - **4 video**: Massima varietà artistica
        - Segmenti 1-2s per effetto hypercut
        - Segmenti 3-4s per storytelling dinamico
        - MP4/H.264 garantiscono massima compatibilità
        
        ### **🚀 Prestazioni:**
        - Video HD: segmenti 2-3s consigliati
        - Video 4K: segmenti 3-5s per evitare overload
        - RAM: almeno 8GB per 4 video simultanei
        - Storage: prevedi 2-5x la dimensione originale
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
    st.markdown("### 📹 Carica da 2 a 4 video per il mix artistico")
    
    # Upload fino a 4 video
    video_slots = {}
    video_names = ["Primo", "Secondo", "Terzo", "Quarto"]
    video_keys = ["video1", "video2", "video3", "video4"]
    
    cols = st.columns(2)
    
    for i, (name, key) in enumerate(zip(video_names, video_keys)):
        with cols[i % 2]:
            if i < 2:
                st.markdown(f"#### Video {i+1} {'*(obbligatorio)*' if i < 2 else '*(opzionale)*'}")
            else:
                st.markdown(f"#### Video {i+1} *(opzionale)*")
            
            video_slots[key] = st.file_uploader(
                f"{name} video", 
                type=["mp4", "mov", "avi", "mkv"], 
                key=key,
                help=f"Carica il {name.lower()} video" + (" (opzionale)" if i >= 2 else "")
            )

    # Conta video caricati
    uploaded_videos = {k: v for k, v in video_slots.items() if v is not None}
    num_videos = len(uploaded_videos)
    
    # Info stato
    if num_videos == 0:
        st.info("🔤 Carica almeno 2 video per creare un Multi-Mix PRO!")
    elif num_videos == 1:
        st.warning("⚠️ Carica almeno un secondo video per il Multi-Mix.")
    else:
        st.success(f"✅ {num_videos} video caricati - Pronto per Multi-Mix PRO!")
        
        if num_videos >= 2:
            process_multi_video_upload(uploaded_videos)

def process_single_video(uploaded_video, input_path, total_duration, segment
_input, seed_input, custom_fps, fps_value, enable_overlay):
   try:
       segment_duration = float(segment_input)
       if segment_duration <= 0:
           st.error("La durata del segmento deve essere positiva!")
           return
   except ValueError:
       st.error("Inserisci un numero valido per la durata del segmento!")
       return

   # Crea shuffler
   shuffler = MultiVideoShuffler()
   
   # Aggiungi video
   num_segments = shuffler.add_video("video1", uploaded_video.name, total_duration, segment_duration)
   st.info(f"Video diviso in {num_segments} segmenti da ~{segment_duration}s")
   
   # Shuffle
   seed = int(seed_input) if seed_input.strip() else None
   shuffler.shuffle_all_segments(seed=seed)
   
   # Mostra scaletta
   schedule = shuffler.generate_schedule()
   st.text_area("📋 Scaletta generata:", schedule, height=200)
   
   # Progress bar
   progress_bar = st.progress(0)
   status_text = st.empty()
   
   def update_progress_single(message):
       st.session_state.current_progress_single_video = min(st.session_state.current_progress_single_video + 10, 90)
       progress_bar.progress(st.session_state.current_progress_single_video)
       status_text.text(message)
   
   # Processa
   temp_dir = tempfile.gettempdir()
   output_filename = f"shuffled_{os.path.splitext(uploaded_video.name)[0]}.mp4"
   output_path = os.path.join(temp_dir, output_filename)
   
   fps = fps_value if custom_fps else None
   
   success, result = shuffler.process_videos(
       {"video1": input_path}, 
       output_path, 
       progress_callback=update_progress_single,
       fps=fps,
       enable_overlay=enable_overlay
   )
   
   if success:
       progress_bar.progress(100)
       status_text.text("✅ Completato!")
       st.session_state.current_progress_single_video = 0
       
       st.success("🎉 Video elaborato con successo!")
       
       # Download
       with open(output_path, "rb") as f:
           st.download_button(
               label="⬇️ Scarica video mescolato",
               data=f.read(),
               file_name=output_filename,
               mime="video/mp4",
               use_container_width=True
           )
       
       # Preview
       st.video(output_path)
       
   else:
       st.error(f"❌ Errore nell'elaborazione: {result}")
       st.session_state.current_progress_single_video = 0

def process_multi_video_upload(uploaded_videos):
   # Salva file temporanei e ottieni durate
   temp_dir = tempfile.gettempdir()
   video_paths = {}
   video_durations = {}
   total_combined_duration = 0
   
   with st.spinner("📥 Caricamento e analisi video..."):
       for key, video_file in uploaded_videos.items():
           temp_filename = f"multi_{key}_{os.path.basename(video_file.name)}"
           temp_path = os.path.join(temp_dir, temp_filename)
           
           with open(temp_path, "wb") as f:
               f.write(video_file.read())
           
           video_paths[key] = temp_path
           
           # Ottieni durata
           if MOVIEPY_AVAILABLE:
               try:
                   with VideoFileClip(temp_path) as clip:
                       duration = clip.duration
                       video_durations[key] = duration
                       total_combined_duration += duration
               except Exception as e:
                   st.error(f"Errore lettura {video_file.name}: {e}")
                   return
           else:
               # Simulazione
               video_durations[key] = 60
               total_combined_duration += 60
   
   # Mostra info video caricati
   st.markdown("### 📊 Video caricati:")
   
   video_info_cols = st.columns(len(uploaded_videos))
   for i, (key, video_file) in enumerate(uploaded_videos.items()):
       with video_info_cols[i]:
           duration = video_durations[key]
           st.metric(
               label=f"Video {i+1}",
               value=f"{duration:.1f}s",
               delta=video_file.name
           )
   
   st.info(f"🎬 Durata totale combinata: {total_combined_duration:.1f} secondi")
   
   # Parametri Multi-Mix
   with st.form("multi_params_form"):
       st.markdown("### ⚙️ Configurazione Multi-Mix PRO")
       
       col1, col2 = st.columns(2)
       
       with col1:
           segment_input = st.text_input("Durata segmenti (secondi)", "3")
           seed_input = st.text_input("Seed (opzionale)", "", help="Per risultati riproducibili")
           
           custom_fps = st.checkbox("FPS personalizzato")
           fps_value = st.number_input("FPS:", min_value=15, max_value=60, value=30, disabled=not custom_fps)
       
       with col2:
           st.markdown("**🎯 Pesi video (distribuzione %):**")
           video_weights = {}
           total_weight = 0
           
           for i, (key, video_file) in enumerate(uploaded_videos.items()):
               default_weight = 100 // len(uploaded_videos)
               if i == 0:  # Aggiusta il primo per arrivare a 100
                   default_weight = 100 - (default_weight * (len(uploaded_videos) - 1))
               
               weight = st.slider(
                   f"Video {i+1} ({video_file.name[:20]}...)",
                   min_value=5,
                   max_value=70,
                   value=default_weight,
                   help=f"Percentuale di presenza del video {i+1}"
               )
               video_weights[key] = weight / 100.0
               total_weight += weight
           
           if abs(total_weight - 100) > 5:
               st.warning(f"⚠️ Somma pesi: {total_weight}% (consigliato: ~100%)")
       
       st.markdown("**🎨 Effetti Artistici Multi-Video:**")
       enable_overlay = st.checkbox(
           "Abilita Collage Dinamico Multi-Sorgente", 
           value=True,
           help="Crea collage artistici usando elementi da tutti i video caricati simultaneamente."
       )
       
       if enable_overlay:
           st.info("🎭 Ogni segmento avrà 2-6 overlay casuali da tutti i video, creando un collage artistico dinamico!")
       
       submitted = st.form_submit_button("🚀 Crea Multi-Mix PRO", use_container_width=True)

   if submitted:
       process_multi_video_creation(
           uploaded_videos, video_paths, video_durations, 
           segment_input, seed_input, video_weights,
           custom_fps, fps_value, enable_overlay
       )

def process_multi_video_creation(uploaded_videos, video_paths, video_durations, 
                               segment_input, seed_input, video_weights,
                               custom_fps, fps_value, enable_overlay):
   
   try:
       segment_duration = float(segment_input)
       if segment_duration <= 0:
           st.error("La durata del segmento deve essere positiva!")
           return
   except ValueError:
       st.error("Inserisci un numero valido per la durata del segmento!")
       return

   # Crea shuffler multi-video
   shuffler = MultiVideoShuffler()
   
   # Aggiungi tutti i video
   total_segments = 0
   for key, video_file in uploaded_videos.items():
       duration = video_durations[key]
       num_segments = shuffler.add_video(key, video_file.name, duration, segment_duration)
       total_segments += num_segments
       st.info(f"📹 {video_file.name}: {num_segments} segmenti da ~{segment_duration}s")
   
   st.success(f"🎯 Totale: {total_segments} segmenti da {len(uploaded_videos)} video")
   
   # Shuffle con pesi
   seed = int(seed_input) if seed_input.strip() else None
   shuffler.shuffle_all_segments(seed=seed, video_weights=video_weights)
   
   # Mostra scaletta
   schedule = shuffler.generate_schedule()
   with st.expander("📋 Visualizza scaletta completa", expanded=False):
       st.text_area("Scaletta Multi-Mix PRO:", schedule, height=300)
   
   # Progress bar
   progress_bar = st.progress(0)
   status_text = st.empty()
   
   def update_progress_multi(message):
       st.session_state.current_progress_multi_video = min(st.session_state.current_progress_multi_video + 5, 90)
       progress_bar.progress(st.session_state.current_progress_multi_video)
       status_text.text(message)
   
   # Nome output
   video_names = [v.name for v in uploaded_videos.values()]
   output_filename = f"MultiMix_PRO_{len(uploaded_videos)}videos_{segment_duration}s.mp4"
   
   temp_dir = tempfile.gettempdir()
   output_path = os.path.join(temp_dir, output_filename)
   
   fps = fps_value if custom_fps else None
   
   # Processa
   with st.spinner("🎬 Creazione Multi-Mix PRO in corso..."):
       success, result = shuffler.process_videos(
           video_paths, 
           output_path, 
           progress_callback=update_progress_multi,
           fps=fps,
           enable_overlay=enable_overlay
       )
   
   if success:
       progress_bar.progress(100)
       status_text.text("✅ Multi-Mix PRO completato!")
       st.session_state.current_progress_multi_video = 0
       
       st.success("🎉 Multi-Mix PRO creato con successo!")
       
       # Statistiche finali
       final_stats = shuffler.generate_schedule().split('\n')
       stats_section = []
       in_stats = False
       for line in final_stats:
           if line.startswith("STATISTICHE:"):
               in_stats = True
           elif line.startswith("TOTALE VIDEO UTILIZZATI:"):
               stats_section.append(line)
               break
           elif in_stats and line.strip():
               stats_section.append(line)
       
       if stats_section:
           st.markdown("### 📈 Statistiche finali:")
           for stat in stats_section:
               st.text(stat)
       
       # Download
       with open(output_path, "rb") as f:
           st.download_button(
               label="⬇️ Scarica Multi-Mix PRO",
               data=f.read(),
               file_name=output_filename,
               mime="video/mp4",
               use_container_width=True
           )
       
       # Preview
       st.video(output_path)
       
       # Suggerimenti
       st.markdown("### 💡 Prossimi passi:")
       st.info("""
       - 🎨 Prova diversi pesi per cambiare l'equilibrio tra i video
       - 🔀 Cambia il seed per ottenere sequenze diverse
       - ⏱️ Sperimenta con durate segmenti diverse (1-5s)
       - 🎭 Disabilita/abilita il collage per effetti diversi
       """)
       
   else:
       st.error(f"❌ Errore nell'elaborazione Multi-Mix: {result}")
       st.session_state.current_progress_multi_video = 0

if __name__ == "__main__":
   main()
