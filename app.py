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
        self.all_segments = []    # Lista di tutti i segmenti con info video (dizionari)
        self.shuffled_order = []  # L'ordine mescolato dei segmenti per la sequenza finale
        self.video_clips_map = {} # Mappa video_id -> VideoFileClip caricato originale (aggiunto per overlay)

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
            self.all_segments.append(segment) # Aggiungi a tutti i segmenti per il pool degli overlay

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
            self.all_segments.append(segment) # Aggiungi a tutti i segmenti per il pool degli overlay

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
            
            # Distribuisci alternativamente i segmenti dai due video basandosi sul mix_ratio
            for i in range(max_len):
                if i < len(video1_segments) and (random.random() < mix_ratio or i >= len(video2_segments)):
                    balanced_segments.append(video1_segments[i])
                if i < len(video2_segments) and (random.random() >= mix_ratio or i >= len(video1_segments)):
                    balanced_segments.append(video2_segments[i])
            
            # Mescola la lista bilanciata per randomizzare ulteriormente l'ordine
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
            # Trova il nome del video usando il video_id
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
        Crea un video con un composito in stile collage, dove anche il 'main_clip' è un elemento del collage.
        main_clips_sequence: lista di clip MoviePy che formeranno gli elementi 'principali' del collage.
        all_segment_dicts: lista di Dictionaries di TUTTI i segmenti disponibili (da self.all_segments).
                           Usati per selezionare casualmente i segmenti per gli overlay 'secondari'.
        """
        try:
            import random
            
            if not main_clips_sequence or len(main_clips_sequence) <= 0:
                print("LOG: Troppo pochi clip principali per creare il video collage. Nessun output.")
                return None
            
            # La dimensione del canvas finale sarà quella del primo clip principale
            # Assumiamo che tutti i video siano della stessa risoluzione o si adattino bene.
            base_w, base_h = main_clips_sequence[0].size
            print(f"LOG: Dimensione Canvas del video finale: {base_w}x{base_h}")
            st.info(f"DEBUG Streamlit: create_artistic_overlay avviata. Dimensione Canvas: {base_w}x{base_h}.")
            
            final_clips = []
            current_time = 0 # Tempo corrente nella sequenza del video composito

            if not self.video_clips_map:
                raise ValueError("LOG: La mappa dei VideoFileClip originali (self.video_clips_map) non è stata popolata.")

            # Definizione dei tipi di overlay per il collage
            # Ogni tupla: (descrizione, rapporto_aspetto_target, dimensione_min_perc, dimensione_max_perc, probabilità)
            # Le percentuali sono relative alla dimensione del canvas (base_w, base_h)
            overlay_types = [
                # Tipi per gli elementi secondari del collage
                ("Square Small", 1.0, 0.10, 0.20, 0.3),  
                ("Square Medium", 1.0, 0.20, 0.30, 0.2), 
                ("Horizontal Thin", 2.5, 0.20, 0.40, 0.2),
                ("Vertical Thin", 0.4, 0.20, 0.40, 0.2),  
                ("Standard Small", base_w/base_h, 0.15, 0.25, 0.1), 
            ]
            
            # Normalizza le probabilità per la selezione casuale
            total_prob = sum(ot[4] for ot in overlay_types)
            normalized_overlay_types = [(desc, ar, min_s, max_s, prob/total_prob) for desc, ar, min_s, max_s, prob in overlay_types]

            for i, main_clip in enumerate(main_clips_sequence):
                if progress_callback:
                    progress_callback(f"Collage Artistico: segmento {i+1}/{len(main_clips_sequence)}")
                
                # --- TRATTAMENTO DEL CLIP "PRINCIPALE" COME ELEMENTO DEL COLLAGE ---
                # Questo clip sarà l'elemento più prominente per questo intervallo di tempo
                
                # Definire dimensioni e posizione per il clip "principale"
                # Può essere leggermente più grande e più centrale
                primary_size_factor = random.uniform(0.60, 0.90) # Occupare 60-90% della dimensione del canvas
                primary_w = int(base_w * primary_size_factor)
                primary_h = int(base_h * primary_size_factor)
                
                primary_w = max(100, primary_w) # Assicurare dimensioni minime
                primary_h = max(100, primary_h)

                # Posizione semi-casuale, più vicina al centro
                primary_max_x = base_w - primary_w
                primary_max_y = base_h - primary_h
                primary_pos_x = random.randint(int(primary_max_x * 0.1), max(0, int(primary_max_x * 0.9)))
                primary_pos_y = random.randint(int(primary_max_y * 0.1), max(0, int(primary_max_y * 0.9)))

                # Durata del clip principale come elemento del collage
                # Può durare per l'intera durata del suo segmento originale
                primary_clip_duration = main_clip.duration
                
                primary_collage_element = (main_clip
                                           .resize((primary_w, primary_h))
                                           .set_position((primary_pos_x, primary_pos_y))
                                           .set_start(current_time)
                                           .set_opacity(random.uniform(0.8, 1.0))) # Meno trasparente o del tutto opaco

                final_clips.append(primary_collage_element)
                st.info(f"DEBUG Streamlit: Aggiunto elemento PRIMARIO del collage. Clip #{i+1}, tempo: {current_time:.2f}s.")
                print(f"LOG: Aggiunto elemento PRIMARIO del collage #{i+1}: ({primary_w}x{primary_h}) at ({primary_pos_x},{primary_pos_y}), start:{current_time:.2f}s, durata:{primary_clip_duration:.2f}s")
                
                # --- AGGIUNTA DI ELEMENTI DI COLLAGE "SECONDARI" ---
                if all_segment_dicts:
                    num_secondary_overlays = random.randint(1, 3) # 1-3 elementi secondari per ogni periodo primario
                    print(f"LOG: Tentativo di aggiungere {num_secondary_overlays} elementi secondari per il periodo del clip principale #{i+1}")
                    
                    for overlay_idx in range(num_secondary_overlays):
                        try:
                            # Scegli il tipo di overlay per l'elemento secondario
                            choice_weights = [ot[4] for ot in normalized_overlay_types]
                            chosen_overlay_type = random.choices(normalized_overlay_types, weights=choice_weights, k=1)[0]
                            
                            desc, target_aspect_ratio, min_size_perc, max_size_perc, _ = chosen_overlay_type

                            # Scegli un segmento CASUALE da TUTTI I SEGMENTI DISPONIBILI
                            source_segment_info = random.choice(all_segment_dicts)
                            
                            # Evita di sovrapporre il clip principale con un overlay dello stesso identico segmento
                            if source_segment_info['global_id'] == self.shuffled_order[i]['global_id']:
                                potential_source_segment_info = [s for s in all_segment_dicts if s['global_id'] != self.shuffled_order[i]['global_id']]
                                if potential_source_segment_info:
                                    source_segment_info = random.choice(potential_source_segment_info)
                                else:
                                    print("LOG: Nessun altro segmento disponibile per l'overlay secondario, salta.")
                                    continue
                            
                            source_video_clip_original = self.video_clips_map.get(source_segment_info['video_id'])
                            if not source_video_clip_original:
                                print(f"LOG: SKIP Overlay Secondario: VideoFileClip originale non trovato per ID {source_segment_info['video_id']}")
                                continue

                            # Calcola le dimensioni dell'overlay secondario
                            random_size_factor = random.uniform(min_size_perc, max_size_perc)
                            
                            if target_aspect_ratio >= 1.0: # Orizzontale o Quadrato
                                overlay_w = int(base_w * random_size_factor)
                                overlay_h = int(overlay_w / target_aspect_ratio)
                            else: # Verticale
                                overlay_h = int(base_h * random_size_factor)
                                overlay_w = int(overlay_h * target_aspect_ratio)

                            overlay_w = max(50, overlay_w)
                            overlay_h = max(50, overlay_h)
                            
                            # Posizione casuale per l'overlay secondario
                            max_x = base_w - overlay_w
                            max_y = base_h - overlay_h
                            pos_x = random.randint(0, max(0, max_x))
                            pos_y = random.randint(0, max(0, max_y))
                            
                            # Durata overlay casuale (parte della durata del periodo primario)
                            secondary_overlay_duration = min(
                                primary_clip_duration * random.uniform(0.3, 0.7), # Durata 30-70% del periodo primario
                                source_video_clip_original.duration,          
                                source_segment_info['duration']               
                            )
                            
                            # Inizio casuale all'interno del segmento sorgente per l'overlay secondario
                            max_subclip_start = source_segment_info['duration'] - secondary_overlay_duration
                            source_subclip_start_offset = random.uniform(0, max(0, max_subclip_start))
                            
                            source_start_time_in_original = source_segment_info['start'] + source_subclip_start_offset
                            source_end_time_in_original = source_start_time_in_original + secondary_overlay_duration

                            # Ritardo dell'overlay secondario rispetto all'inizio del periodo primario
                            start_delay_in_primary_period = random.uniform(0, max(0, primary_clip_duration - secondary_overlay_duration))
                            overlay_start_time_in_final_video = current_time + start_delay_in_primary_period
                            
                            if source_video_clip_original.duration >= source_end_time_in_original:
                                secondary_overlay_clip = (source_video_clip_original
                                                          .subclip(source_start_time_in_original, source_end_time_in_original)
                                                          .resize((overlay_w, overlay_h))
                                                          .set_position((pos_x, pos_y))
                                                          .set_start(overlay_start_time_in_final_video)
                                                          .set_opacity(0.7)) # Trasparenza 70%

                                final_clips.append(secondary_overlay_clip)
                                st.info(f"DEBUG Streamlit: Aggiunto elemento SECONDARIO del collage. Clip #{overlay_idx+1}, tipo: '{desc}'.")
                                print(f"LOG: AGGIUNTO Overlay SECONDARIO #{overlay_idx+1}: '{desc}' da '{source_segment_info['video_name']}' S#{source_segment_info['segment_id']} ({overlay_w}x{overlay_h}) at ({pos_x},{pos_y}), start_composito:{overlay_start_time_in_final_video:.2f}s, durata:{secondary_overlay_duration:.2f}s")
                            else:
                                print(f"LOG: SKIP Overlay Secondario: durata insufficiente per subclip. Originale: {source_video_clip_original.duration:.2f}s, Desiderata: {source_end_time_in_original:.2f}s")

                        except Exception as e:
                            print(f"LOG: Errore durante la creazione di un elemento collage secondario: {e}")
                            import traceback
                            traceback.print_exc()
                            continue
                
                # Avanza il tempo nel video composito per il prossimo periodo primario
                current_time += primary_clip_duration
            
            print(f"LOG: Totale clip nella lista per il composito (elementi primari + secondari): {len(final_clips)}")
            
            if not final_clips:
                print("LOG: Nessun clip finale da comporre dopo l'elaborazione del collage.")
                return None

            # Crea il video composito finale
            # La dimensione del canvas è definita all'inizio
            composite_video = CompositeVideoClip(final_clips, size=(base_w, base_h))
            st.info(f"DEBUG Streamlit: CompositeVideoClip creato. Totale elementi: {len(final_clips)}. Tempo totale: {composite_video.duration:.2f}s.")
            print("LOG: CompositeVideoClip collage creato con successo.")
            return composite_video
            
        except Exception as e:
            print(f"ERRORE CRITICO in create_artistic_overlay (collage): {e}")
            import traceback
            traceback.print_exc()
            try:
                print("LOG: Fallback: concatenazione normale dopo errore critico collage.")
                return concatenate_videoclips(main_clips_sequence, method="compose")
            except Exception as fallback_e:
                print(f"LOG: Errore anche nel fallback: {fallback_e}")
                return None

    def process_videos(self, video_paths, output_path, progress_callback=None, fps=None, enable_overlay=False, overlay_sizes=None): # overlay_sizes ora non usato
        """Processa i video per creare la sequenza finale, con opzione per overlay artistici."""
        if not MOVIEPY_AVAILABLE:
            return False, "MoviePy non disponibile."

        # Verifica che tutti i file video esistano
        for video_id, path in video_paths.items():
            if not os.path.exists(path):
                return False, f"File non trovato: {path}"

        video_clips_original = {} # Mappa video_id -> VideoFileClip caricato originale
        extracted_clips_for_final_sequence = [] # I clip MoviePy già subclipati e ordinati per la sequenza finale
        final_video = None

        try:
            if progress_callback:
                progress_callback("Caricamento video originali...")
                
            # Carica tutti i VideoFileClip originali una sola volta
            for video_id, path in video_paths.items():
                print(f"Caricando video originale {video_id}: {path}")
                video_clips_original[video_id] = VideoFileClip(path)
            
            # Salva questa mappa nella classe per renderla disponibile a create_artistic_overlay
            self.video_clips_map = video_clips_original 

            # Estrai i segmenti MoviePy che formeranno la sequenza principale del video finale
            if progress_callback:
                progress_callback("Estrazione segmenti per sequenza finale...")
            
            for i, segment in enumerate(self.shuffled_order):
                video_id = segment['video_id']
                # Usa il VideoFileClip originale precedentemente caricato
                video_clip_source = video_clips_original[video_id] 
                
                # Controlli di validità sui tempi del segmento
                end_time = min(segment['end'], video_clip_source.duration)
                if segment['start'] >= end_time or segment['start'] >= video_clip_source.duration:
                    print(f"SKIP: Segmento {segment['global_id']} - tempi non validi (start {segment['start']:.2f}s, end {end_time:.2f}s, durata video {video_clip_source.duration:.2f}s)")
                    continue
                
                try:
                    # Estrai il clip MoviePy per la sequenza principale
                    clip = video_clip_source.subclip(segment['start'], end_time)
                    
                    # Applica FPS se richiesto e diverso dal clip originale
                    if fps and fps != clip.fps:
                        clip = clip.set_fps(fps)
                    
                    extracted_clips_for_final_sequence.append(clip)
                    print(f"OK: Estratto segmento {segment['global_id']} ({segment['start']:.2f}-{end_time:.2f}s) per sequenza finale.")
                    
                    if progress_callback:
                        progress_callback(f"Estratti {len(extracted_clips_for_final_sequence)}/{len(self.shuffled_order)} segmenti per sequenza finale")
                        
                except Exception as e:
                    print(f"ERRORE estrazione segmento {segment['global_id']} per sequenza finale: {e}")
                    continue

            if not extracted_clips_for_final_sequence:
                return False, "Nessun segmento valido estratto per la sequenza finale."
            print(f"Totale segmenti estratti per sequenza finale: {len(extracted_clips_for_final_sequence)}")
            
            # Crea video finale
            if progress_callback:
                progress_callback("Creazione video finale...")

            # Abilita l'overlay se la flag è True E ci sono almeno 2 clip (per un collage significativo)
            if enable_overlay and len(extracted_clips_for_final_sequence) > 1:
                st.info("DEBUG Streamlit: Tentativo di applicare effetti collage.")
                print("Applicando effetti collage artistici...")
                # Chiama create_artistic_overlay passando i clip della sequenza principale,
                # e la lista di tutti i dizionari dei segmenti (per la selezione casuale degli overlay)
                final_video = self.create_artistic_overlay(
                    extracted_clips_for_final_sequence, 
                    self.all_segments, # all_segments contiene i dizionari di tutti i segmenti disponibili
                    progress_callback
                )
            else:
                st.info("DEBUG Streamlit: Concatenazione normale (collage disabilitato o insufficienti clip).")
                print("Concatenazione normale (collage disabilitato o insufficienti clip)...")
                final_video = concatenate_videoclips(extracted_clips_for_final_sequence, method="compose")
            
            if not final_video:
                return False, "Impossibile creare video finale (forse nessun clip o errore composizione)."

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
            print(f"ERRORE GENERALE in process_videos: {e}")
            import traceback
            traceback.print_exc()
            return False, f"Errore: {str(e)}"
            
        finally:
            # Pulizia memoria
            try:
                # Chiudi tutti i VideoFileClip originali caricati
                for video in video_clips_original.values():
                    if video:
                        video.close()
                # Chiudi i clip estratti per la sequenza finale (anche se moviepy li chiude in concatenate/composite)
                for clip in extracted_clips_for_final_sequence:
                    if clip:
                        clip.close()
                # Chiudi il video finale composito
                if final_video:
                    final_video.close()
                print("Pulizia memoria MoviePy completata.")
            except Exception as cleanup_error:
                print(f"Errore durante la pulizia di MoviePy: {cleanup_error}")

# --- STREAMLIT UI ---
st.set_page_config(page_title="VideoDecomposer Multi-Mix by loop507", layout="wide")
st.title("VideoDecomposer Multi-Mix by loop507")
st.subheader("Mescola segmenti da più video con effetti collage dinamici!")

# Inizializza session state per le variabili di progresso
if 'current_progress_single_video' not in st.session_state:
    st.session_state.current_progress_single_video = 0
if 'current_progress_multi_video' not in st.session_state:
    st.session_state.current_progress_multi_video = 0
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
        # Costruisci un nome file sicuro per evitare problemi di path
        input_filename = f"single_video_{os.path.basename(uploaded_video.name)}"
        input_path = os.path.join(temp_dir, input_filename)
        
        with open(input_path, "wb") as f:
            f.write(uploaded_video.read())

        try:
            total_duration = 0
            if MOVIEPY_AVAILABLE:
                # Carica il clip per ottenere la durata e poi chiudilo immediatamente
                # per liberare risorse se non viene usato ulteriormente qui.
                with VideoFileClip(input_path) as clip:
                    total_duration = clip.duration
                st.success(f"Video caricato - Durata: {round(total_duration, 2)} secondi")
            else:
                total_duration = 60 # Simulazione durata per MoviePy non installato
                st.warning("MoviePy non disponibile, durata video simulata.")
            
            # Mostra l'anteprima del video caricato
            st.video(input_path) # Usa il path locale temporaneo

            with st.form("single_params_form"):
                col1, col2 = st.columns(2)
                
                with col1:
                    segment_input = st.text_input("Durata segmenti (secondi)", "3")
                    seed_input = st.text_input("Seed (opzionale)", "", help="Stesso seed = stesso ordine!")
                    
                with col2:
                    custom_fps = st.checkbox("FPS personalizzato")
                    fps_value = st.number_input("FPS:", min_value=1, max_value=60, value=30, disabled=not custom_fps)
                
                # Effetti artistici
                st.markdown("**Effetti Artistici (Collage Dinamico):**")
                # Rimossi gli slider per le dimensioni specifiche, la logica è interna ora
                enable_overlay = st.checkbox("Abilita effetto collage dinamico", help="Il video principale diventa parte del collage con elementi secondari sovrapposti.", key="single_overlay_check")
                
                if enable_overlay:
                    st.info("I frame verranno mescolati in un collage con forme e dimensioni casuali. Anche il frame principale non sarà più a schermo intero.")
                
                submitted = st.form_submit_button("Avvia elaborazione", use_container_width=True)

            if submitted:
                try:
                    segment_duration = float(segment_input)
                    
                    if segment_duration <= 0 or segment_duration >= total_duration:
                        st.error("Durata segmento non valida o troppo grande rispetto alla durata totale del video.")
                    else:
                        shuffler = MultiVideoShuffler()
                        shuffler.add_video("V1", uploaded_video.name, total_duration, segment_duration)
                        
                        seed = int(seed_input) if seed_input.isdigit() else None
                        shuffler.shuffle_all_segments(seed)

                        st.subheader("Scaletta generata")
                        st.code(shuffler.generate_schedule())

                        if MOVIEPY_AVAILABLE:
                            output_filename = f"remix_collage_{os.path.splitext(uploaded_video.name)[0]}.mp4" if enable_overlay else f"remix_{os.path.splitext(uploaded_video.name)[0]}.mp4" 
                            output_path = os.path.join(temp_dir, output_filename)
                            
                            progress_bar = st.progress(0)
                            status_text = st.empty()
                            
                            st.session_state.current_progress_single_video = 0 

                            def progress_callback(message):
                                status_text.text(f" {message}")
                                # Incrementa il progresso e assicurati che non superi 90
                                # Il 100% verrà raggiunto dopo il completamento.
                                st.session_state.current_progress_single_video = min(90, st.session_state.current_progress_single_video + 5) 
                                progress_bar.progress(st.session_state.current_progress_single_video) 
                            
                            video_paths = {"V1": input_path}
                            fps_param = fps_value if custom_fps else None
                            
                            with st.spinner("Creazione video remix in corso..."):
                                success, result = shuffler.process_videos(
                                    video_paths, output_path, progress_callback, 
                                    fps=fps_param, enable_overlay=enable_overlay # overlay_sizes rimosso
                                )
                            
                            progress_bar.progress(100) # Completa la barra al 100% alla fine
                            
                            if success:
                                st.success("Video remixato completato!")
                                if os.path.exists(result):
                                    file_size = os.path.getsize(result) / (1024 * 1024)
                                    st.info(f"File generato: {file_size:.2f} MB")
                                    with open(result, "rb") as f:
                                        st.download_button(
                                            "Scarica video remixato",
                                            f.read(),
                                            file_name=output_filename,
                                            mime="video/mp4",
                                            use_container_width=True
                                        )
                                else:
                                    st.error("File di output non trovato. Si prega di riprovare.")
                            else:
                                st.error(f"Errore durante l'elaborazione: {result}")
                            
                            status_text.empty()
                        else:
                            st.warning("MoviePy non disponibile - Solo simulazione della scaletta.")
                            
                except ValueError:
                    st.error("Inserisci valori numerici validi per la durata dei segmenti o il seed.")
                except Exception as e:
                    st.error(f"Errore imprevisto durante l'elaborazione: {str(e)}")
                    st.exception(e) # Mostra stack trace completa per debug
                    
        except Exception as e:
            st.error(f"Errore lettura video caricato: {str(e)}")
            st.exception(e)

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
        video1_path = os.path.join(temp_dir, f"v1_{os.path.basename(video1.name)}")
        video2_path = os.path.join(temp_dir, f"v2_{os.path.basename(video2.name)}")
        
        # Salva i file temporaneamente
        with open(video1_path, "wb") as f:
            f.write(video1.read())
        with open(video2_path, "wb") as f:
            f.write(video2.read())

        try:
            duration1, duration2 = 0, 0
            if MOVIEPY_AVAILABLE:
                with VideoFileClip(video1_path) as clip1:
                    duration1 = clip1.duration
                with VideoFileClip(video2_path) as clip2:
                    duration2 = clip2.duration
            else:
                duration1 = duration2 = 60 # Simulazione durata per MoviePy non installato
                st.warning("MoviePy non disponibile, durate video simulate.")
                
            # Mostra anteprime
            col1, col2 = st.columns(2)
            with col1:
                st.video(video1_path) # Usa il path locale temporaneo
                st.info(f"Durata: {round(duration1, 2)}s")
            with col2:
                st.video(video2_path) # Usa il path locale temporaneo
                st.info(f"Durata: {round(duration2, 2)}s")

            with st.form("multi_params_form"):
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    segment_input = st.text_input("Durata segmenti (secondi)", "3")
                    seed_input = st.text_input("Seed (opzionale)", "", help="Per risultati riproducibili")
                    
                with col2:
                    mix_ratio = st.slider("Bilancio Video 1/Video 2", 0.1, 0.9, 0.5, 0.1)
                    custom_fps = st.checkbox("FPS personalizzato", key="multi_custom_fps_check")
                
                with col3:
                    fps_value = st.number_input("FPS:", min_value=1, max_value=60, value=30, disabled=not custom_fps, key="multi_fps_value")
                
                st.markdown(f"**Mix Ratio:** {mix_ratio:.1f} = {int(mix_ratio*100)}% Video 1, {int((1-mix_ratio)*100)}% Video 2")
                
                # Effetti artistici multi-video
                st.markdown("**Effetti Artistici Multi-Video (Collage Dinamico):**")
                # Rimossi gli slider per le dimensioni specifiche, la logica è interna ora
                enable_overlay = st.checkbox("Abilita effetto collage dinamico", help="Il video principale diventa parte del collage con elementi secondari sovrapposti. Frame da entrambi i video.", key="multi_overlay_check")
                
                if enable_overlay:
                    st.info("I frame verranno mescolati in un collage con forme e dimensioni casuali. Anche il frame principale non sarà più a schermo intero.")
                
                submitted = st.form_submit_button("Crea Multi-Mix Artistico", use_container_width=True)

            if submitted:
                try:
                    segment_duration = float(segment_input)
                    
                    if segment_duration <= 0:
                        st.error("Durata segmento deve essere positiva.")
                    else:
                        shuffler = MultiVideoShuffler()
                        
                        # Aggiungi entrambi i video al shuffler
                        num_seg1 = shuffler.add_video("V1", video1.name, duration1, segment_duration)
                        num_seg2 = shuffler.add_video("V2", video2.name, duration2, segment_duration)
                        
                        seed = int(seed_input) if seed_input.isdigit() else None
                        shuffler.shuffle_all_segments(seed, mix_ratio)

                        st.subheader("Scaletta Multi-Mix generata")
                        st.code(shuffler.generate_schedule())
                        
                        st.success(f"Mescolati {num_seg1 + num_seg2} segmenti totali ({num_seg1} + {num_seg2})")

                        if MOVIEPY_AVAILABLE:
                            output_filename = f"multimix_collage_{os.path.splitext(video1.name)[0]}_{os.path.splitext(video2.name)[0]}.mp4" if enable_overlay else f"multimix_{os.path.splitext(video1.name)[0]}_{os.path.splitext(video2.name)[0]}.mp4"
                            output_path = os.path.join(temp_dir, output_filename)
                            
                            progress_bar = st.progress(0)
                            status_text = st.empty()
                            
                            st.session_state.current_progress_multi_video = 0

                            def progress_callback(message):
                                status_text.text(f" {message}")
                                st.session_state.current_progress_multi_video = min(90, st.session_state.current_progress_multi_video + 5)
                                progress_bar.progress(st.session_state.current_progress_multi_video) 
                            
                            video_paths = {"V1": video1_path, "V2": video2_path}
                            fps_param = fps_value if custom_fps else None
                            
                            with st.spinner("Creazione Multi-Mix artistico in corso..."):
                                success, result = shuffler.process_videos(
                                    video_paths, output_path, progress_callback,
                                    fps=fps_param, enable_overlay=enable_overlay # overlay_sizes rimosso
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
                                    st.error("File di output non trovato. Si prega di riprovare.")
                            else:
                                st.error(f"Errore durante l'elaborazione: {result}")
                                
                            status_text.empty()
                        else:
                            st.warning("MoviePy non disponibile - Solo simulazione della scaletta.")
                            
                except ValueError:
                    st.error("Inserisci valori numerici validi per la durata dei segmenti o il seed.")
                except Exception as e:
                    st.error(f"Errore imprevisto durante l'elaborazione: {str(e)}")
                    st.exception(e)
                    
        except Exception as e:
            st.error(f"Errore lettura video caricati: {str(e)}")
            st.exception(e)
    
    elif video1 or video2:
        st.info("Carica entrambi i video per procedere con il Multi-Mix.")
    else:
        st.info("Carica due video per creare un Multi-Mix artistico!")

# Istruzioni dettagliate
with st.expander("Come funziona - VERSIONE COLLAGE DINAMICO"):
    st.markdown("""
    ## VideoDecomposer Multi-Mix - Guida Completa (COLLAGE DINAMICO)
    
    ### **Novità e Effetti Collage:**
    - **Collage Dinamico**: Anche il "frame principale" (il segmento corrente della tua sequenza) diventa un elemento del collage, ridimensionato e posizionato casualmente.
    - **Canvas Fisso**: La risoluzione del video di output rimane quella del primo video originale caricato.
    - **Trasparenza Variabile**: Il frame "principale" del collage avrà un'opacità più alta (quasi opaco), mentre gli elementi secondari manterranno una trasparenza del 70%.
    - **Mix di Forme e Dimensioni**: Gli elementi secondari avranno forme (quadrate, orizzontali strette, verticali alte, ecc.) e dimensioni casuali.
    - **Posizionamento Casuale**: Tutti gli elementi del collage (primario e secondari) sono posizionati casualmente.
    - **Multi-Video**: Gli elementi del collage (primari e secondari) provengono casualmente da *tutti* i video sorgente caricati, creando un mix visivo completo.

    ### **Modalità Multi-Video (Aggiornata):**
    1. **Carica 2 video** di qualsiasi formato compatibile con MoviePy (MP4, MOV, AVI, MKV).
    2. **Imposta durata segmenti** (consigliato: 2-5 secondi per un buon mix).
    3. Regola il **Mix Ratio** per bilanciare la quantità di segmenti di ciascun video nella sequenza finale.
    4. Attiva **"Abilita effetto collage dinamico"** per la nuova sovrapposizione artistica.
    5. Genera il **Multi-Mix** con mescolamento intelligente.
    
    ### **Parametri Avanzati:**
    - **Seed**: Un numero intero opzionale. Usare lo stesso seed garantisce che l'ordine di mescolamento e la disposizione del collage siano esattamente gli stessi ad ogni esecuzione, utile per risultati riproducibili.
    - **FPS Custom**: Permette di controllare i fotogrammi al secondo del video di output (utile per ridurre la dimensione del file o aumentare la fluidità).
    - **Mix Ratio**: Controlla la preferenza per il Video 1 (es. 0.5 = 50% Video 1 / 50% Video 2; 0.3 = 30% Video 1 / 70% Video 2).
    - **Durata Segmenti**: Segmenti più brevi creano un remix più "frenetico" e dinamico; segmenti più lunghi rendono il video più "calmo".

    ### **Troubleshooting & Consigli:**
    - **Video troppo lunghi o grandi**: Possono causare problemi di memoria o tempi di elaborazione molto lunghi. Per video lunghi, prova con durate di segmento di 2-3 secondi per ridurre il numero totale di clip da gestire.
    - **Consumo Memoria (RAM)**: L'elaborazione video è intensiva. Chiudi altre applicazioni e assicurati di avere RAM disponibile. Se continui ad avere problemi, prova con video più brevi o con risoluzioni più basse.
    - **Crash durante processing**: Verifica che i tuoi file video siano integri e in un formato ben supportato da MoviePy (MP4 con codec H.264 è il più affidabile). A volte i file con codec esotici possono dare problemi. Controlla la console/terminale dove è lanciata l'app Streamlit per messaggi di errore dettagliati (stack trace).

    ### **Performance Attese:**
    - **Tempo elaborazione**: Varia in base alla potenza del tuo hardware e alla durata/risoluzione del video. Tipicamente, aspettati circa 30-60 secondi di elaborazione per ogni minuto di video di output. L'effetto collage può aumentare leggermente il tempo.
    - **Memoria RAM**: Per video HD standard, MoviePy può richiedere tra ~2GB e ~4GB o più, a seconda della complessità degli effetti e della lunghezza del video.
    - **Formati supportati**: MP4, MOV, AVI, MKV sono i più comuni.
    - **Risoluzione di output**: La risoluzione del video di output sarà quella del primo video caricato.

    """)
