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
    st.warning("⚠️ MoviePy non è installato. Funzionerà solo la simulazione.")


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
        schedule.append("📋 SCALETTA VIDEO MULTI-MIX\n")
        
        # Mostra statistiche per video
        video_stats = {}
        for segment in self.shuffled_order:
            video_id = segment['video_id']
            if video_id not in video_stats:
                video_stats[video_id] = {'count': 0, 'total_duration': 0}
            video_stats[video_id]['count'] += 1
            video_stats[video_id]['total_duration'] += segment['duration']
        
        schedule.append("📊 STATISTICHE:")
        for video_id, stats in video_stats.items():
            video_name = self.shuffled_order[0]['video_name'] if video_id == self.shuffled_order[0]['video_id'] else [s['video_name'] for s in self.shuffled_order if s['video_id'] == video_id][0]
            schedule.append(f"   🎬 {video_name}: {stats['count']} segmenti, {self.format_duration(stats['total_duration'])}")
        
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

    def process_videos(self, video_paths, output_path, progress_callback=None, fps=None, enable_overlay=False, overlay_sizes=[50, 100]):
        if not MOVIEPY_AVAILABLE:
            return False, "❌ MoviePy non disponibile."

        # Verifica che tutti i file esistano
        for video_id, path in video_paths.items():
            if not os.path.exists(path):
                return False, f"❌ File non trovato: {path}"

        try:
            # Assicurati che CompositeVideoClip sia importato, sebbene l'abbiamo messo all'inizio del file
            from moviepy.editor import CompositeVideoClip
        except ImportError:
            return False, "❌ Impossibile importare CompositeVideoClip da MoviePy."

        video_clips = {}
        clips = []
        final_video = None

        try:
            # Carica tutti i video
            if progress_callback:
                progress_callback("Caricamento video...")
                
            for video_id, path in video_paths.items():
                video_clips[video_id] = VideoFileClip(path)
                
            if progress_callback:
                progress_callback("Estrazione segmenti nell'ordine mescolato...")
            
            # Estrai i segmenti nell'ordine mescolato
            for i, segment in enumerate(self.shuffled_order):
                video_id = segment['video_id']
                video = video_clips[video_id]
                
                # Verifica che i tempi siano validi
                if segment['start'] >= video.duration:
                    print(f"Segmento {segment['global_id']} saltato: start >= durata video")
                    continue
                    
                # Assicurati che end non superi la durata del video
                end_time = min(segment['end'], video.duration)
                if segment['start'] >= end_time:
                    print(f"Segmento {segment['global_id']} saltato: start >= end")
                    continue
                
                # Crea il subclip
                try:
                    print(f"Estraendo [{segment['video_name']}] Segmento #{segment['segment_id']} dalla posizione {i+1}: {segment['start']:.2f}s - {end_time:.2f}s")
                    clip = video.subclip(segment['start'], end_time)
                    
                    # Applica velocità FPS se specificata
                    if fps and fps != clip.fps:
                        clip = clip.set_fps(fps)
                        print(f"FPS cambiato da {video.fps} a {fps}")
                    
                    clips.append(clip)
                    
                    if progress_callback:
                        progress_callback(f"Estratto [{segment['video_name']}] Segm. #{segment['segment_id']} ({i+1}/{len(self.shuffled_order)})")
                        
                except Exception as e:
                    print(f"Errore nell'estrazione del segmento {segment['global_id']}: {e}")
                    if progress_callback:
                        progress_callback(f"Errore segmento {segment['global_id']}: {e}")
                    continue

            if not clips:
                return False, "❌ Nessun segmento valido estratto dai video."

            print(f"Totale clip estratti: {len(clips)}")
            
            if progress_callback:
                progress_callback(f"Concatenazione di {len(clips)} segmenti...")

            # Concatena i clip nell'ordine mescolato
            # NOTA BENE: la funzione create_artistic_overlay riceve 'clips' che sono i segmenti già estratti.
            # Questo è corretto.
            if enable_overlay and len(clips) > 1:
                if progress_callback:
                    progress_callback("Applicazione effetti artistici overlay...")
                
                # Chiama la funzione aggiornata
                final_video = self.create_artistic_overlay(clips, overlay_sizes, progress_callback)
            else:
                # Concatenazione normale
                final_video = concatenate_videoclips(clips, method="compose")
            
            if progress_callback:
                progress_callback("Salvataggio video finale...")

            # Parametri di output
            output_params = {
                'codec': 'libx264',
                'audio_codec': 'aac',
                'temp_audiofile': 'temp-audio.m4a',
                'remove_temp': True,
                'verbose': False,
                'logger': None
            }
            
            # Aggiungi FPS se specificato
            if fps:
                output_params['fps'] = fps

            # Scrivi il video finale
            final_video.write_videofile(output_path, **output_params)

            print(f"Video finale multi-mix salvato: {output_path}")
            return True, output_path

        except Exception as e:
            print(f"Errore durante l'elaborazione: {str(e)}")
            return False, f"❌ Errore durante l'elaborazione: {str(e)}"
            
        finally:
            # Pulizia memoria
            try:
                for video in video_clips.values():
                    if video:
                        video.close()
                if final_video:
                    final_video.close()
                for clip in clips:
                    if clip:
                        clip.close()
            except:
                pass

    # --- INIZIO: LA FUNZIONE create_artistic_overlay AGGIORNATA ---
    def create_artistic_overlay(self, clips, overlay_sizes, progress_callback=None):
        """Crea un effetto artistico con overlay di frame di diverse dimensioni.

        Args:
            clips (list): Una lista di oggetti MoviePy VideoClip che rappresentano
                          i segmenti video da combinare.
            overlay_sizes (list): Lista di dimensioni percentuali per gli overlay (es. [12, 30]).
            progress_callback (callable, optional): Una funzione di callback per
                                                    aggiornare lo stato di avanzamento.
                                                    Defaults to None.

        Returns:
            CompositeVideoClip: Il video composito con gli effetti di overlay,
                                o il risultato della concatenazione normale in caso di errore.
        """
        try:
            # Assicurati che CompositeVideoClip sia importato (già presente all'inizio del file, ma per sicurezza)
            from moviepy.editor import CompositeVideoClip
            import random
            
            if not clips:
                print("Nessun clip fornito per la creazione dell'overlay artistico.")
                return None
            
            # Se c'è solo un clip, non ha senso fare overlay complessi, si concatena normalmente.
            # Questo caso è già gestito in process_videos prima di chiamare questa funzione,
            # ma è buona pratica avere un controllo qui in caso di chiamate dirette.
            if len(clips) <= 1:
                print("Meno di due clip, non verranno creati overlay artistici complessi. Concatenazione normale.")
                return concatenate_videoclips(clips, method="compose")

            # Prendi il primo clip come riferimento per le dimensioni del video finale.
            base_clip = clips[0]
            base_w, base_h = base_clip.size

            all_composite_clips = []
            current_time = 0

            # Definiamo i range di dimensione per piccoli e grandi overlay
            # Questi valori sono presi dalle slider di Streamlit (overlay1, overlay2)
            # ma qui li usiamo per definire i range per la scelta casuale.
            # La funzione riceve overlay_sizes come [overlay1_value, overlay2_value]
            # Quindi overlay_sizes[0] è il valore per l'overlay piccolo, overlay_sizes[1] per il grande.
            small_overlay_base_size = overlay_sizes[0] if len(overlay_sizes) > 0 else 12
            large_overlay_base_size = overlay_sizes[1] if len(overlay_sizes) > 1 else 30

            # Definiamo range attorno ai valori base forniti dall'utente
            # Ad esempio, se l'utente mette 12%, il range sarà 5-20% circa.
            # Questo dà variabilità mantenendo il controllo utente.
            small_overlay_range = (max(5, small_overlay_base_size * 0.5), min(25, small_overlay_base_size * 1.5))
            large_overlay_range = (max(20, large_overlay_base_size * 0.7), min(50, large_overlay_base_size * 1.3))

            # Numero di overlay da generare per ogni segmento principale.
            # Puoi rendere questi numeri configurabili tramite Streamlit se vuoi più controllo.
            num_small_overlays_per_segment = 1
            num_large_overlays_per_segment = 1
            
            # Iterazione su ogni clip (che è un segmento del video finale) per usarlo come "frame principale"
            for i, clip in enumerate(clips):
                if progress_callback:
                    progress_callback(f"Applicazione overlay su segmento {i+1}/{len(clips)}")
                
                # Il clip principale di questo segmento, posizionato al centro.
                main_clip = clip.set_position('center').set_start(current_time)
                segment_composite_clips = [main_clip] # Inizia la lista dei clip per questo segmento con il principale

                # --- Generazione degli overlay ---
                # 'clips' contiene tutti i segmenti video già ordinati che formeranno il video finale.
                # Scegliamo da questa lista per creare gli overlay. Questo assicura che gli overlay
                # provengano dai video che sono stati caricati e mescolati.
                available_overlay_sources = clips # Usiamo tutti i clip disponibili come sorgenti per gli overlay

                if not available_overlay_sources: # Dovrebbe essere raro qui dato il controllo iniziale
                    print(f"Non ci sono abbastanza clip per creare overlay per il segmento {i+1}. Saltando gli overlay.")
                    current_time += clip.duration
                    all_composite_clips.extend(segment_composite_clips)
                    continue

                # Ciclo per gli overlay piccoli
                for _ in range(num_small_overlays_per_segment):
                    try:
                        # Scegli un clip casuale per l'overlay dalla lista di tutti i segmenti
                        overlay_source = random.choice(available_overlay_sources)
                        
                        # Calcola una dimensione casuale all'interno del range piccolo
                        overlay_scale = random.uniform(small_overlay_range[0], small_overlay_range[1]) / 100.0 # Converti a frazione
                        overlay_w = max(50, int(base_w * overlay_scale))
                        overlay_h = max(50, int(base_h * overlay_scale))

                        # Calcola posizione casuale, assicurandoti che l'overlay rimanga dentro lo schermo
                        pos_x = random.randint(0, max(0, base_w - overlay_w))
                        pos_y = random.randint(0, max(0, base_h - overlay_h))

                        # Durata dell'overlay, più breve del clip principale per dinamicità
                        overlay_duration = min(
                            clip.duration * random.uniform(0.3, 0.8), # L'overlay dura una frazione del segmento principale
                            overlay_source.duration # Non può durare più del clip sorgente
                        )

                        # Momento di inizio dell'overlay all'interno del segmento corrente
                        max_start_delay = max(0, clip.duration - overlay_duration)
                        overlay_start_delay = random.uniform(0, max_start_delay)
                        overlay_start_time = current_time + overlay_start_delay

                        # Assicurati che l'overlay_source abbia durata sufficiente per il subclip
                        if overlay_source.duration >= overlay_duration:
                            overlay_clip = (overlay_source
                                            .subclip(0, overlay_duration) # Prendi solo una parte del clip sorgente
                                            .resize((overlay_w, overlay_h))
                                            .set_position((pos_x, pos_y))
                                            .set_start(overlay_start_time)
                                            .set_opacity(0.7)) # Trasparenza al 70% (0.7)
                            
                            segment_composite_clips.append(overlay_clip)
                            # print(f"Overlay PICCOLO aggiunto: {overlay_w}x{overlay_h} at ({pos_x},{pos_y}) from {overlay_start_delay:.2f}s for {overlay_duration:.2f}s")
                        else:
                            # print(f"Clip sorgente per overlay piccolo troppo corto ({overlay_source.duration:.2f}s) per la durata richiesta ({overlay_duration:.2f}s). Saltato.")
                            pass # Silenzia questi messaggi per non intasare l'output di Streamlit

                    except Exception as overlay_error:
                        print(f"Errore nella creazione di un overlay piccolo: {overlay_error}")
                        continue

                # Ciclo per gli overlay grandi
                for _ in range(num_large_overlays_per_segment):
                    try:
                        overlay_source = random.choice(available_overlay_sources)
                        
                        # Calcola una dimensione casuale all'interno del range grande
                        overlay_scale = random.uniform(large_overlay_range[0], large_overlay_range[1]) / 100.0 # Converti a frazione
                        overlay_w = max(50, int(base_w * overlay_scale))
                        overlay_h = max(50, int(base_h * overlay_scale))

                        # Calcola posizione casuale
                        pos_x = random.randint(0, max(0, base_w - overlay_w))
                        pos_y = random.randint(0, max(0, base_h - overlay_h))

                        # Durata dell'overlay
                        overlay_duration = min(
                            clip.duration * random.uniform(0.3, 0.8),
                            overlay_source.duration
                        )
                        
                        # Momento di inizio dell'overlay
                        max_start_delay = max(0, clip.duration - overlay_duration)
                        overlay_start_delay = random.uniform(0, max_start_delay)
                        overlay_start_time = current_time + overlay_start_delay

                        if overlay_source.duration >= overlay_duration:
                            overlay_clip = (overlay_source
                                            .subclip(0, overlay_duration)
                                            .resize((overlay_w, overlay_h))
                                            .set_position((pos_x, pos_y))
                                            .set_start(overlay_start_time)
                                            .set_opacity(0.7)) # Trasparenza al 70%
                            
                            segment_composite_clips.append(overlay_clip)
                            # print(f"Overlay GRANDE aggiunto: {overlay_w}x{overlay_h} at ({pos_x},{pos_y}) from {overlay_start_delay:.2f}s for {overlay_duration:.2f}s")
                        else:
                            # print(f"Clip sorgente per overlay grande troppo corto ({overlay_source.duration:.2f}s) per la durata richiesta ({overlay_duration:.2f}s). Saltato.")
                            pass

                    except Exception as overlay_error:
                        print(f"Errore nella creazione di un overlay grande: {overlay_error}")
                        continue

                # Aggiungi tutti i clip (principale + overlay) di questo segmento alla lista generale
                all_composite_clips.extend(segment_composite_clips)
                current_time += clip.duration # Avanza il tempo per il prossimo segmento
            
            # print(f"Totale clip per il composito finale: {len(all_composite_clips)}")

            # Crea il video composito finale
            if all_composite_clips:
                final_video = CompositeVideoClip(all_composite_clips, size=(base_w, base_h))
                # print("Video composito artistico creato con successo!")
                return final_video
            else:
                print("Nessun clip valido per creare il video composito (dopo tentativi overlay). Fallback.")
                return concatenate_videoclips(clips, method="compose") # Fallback se non si riesce a creare overlay
            
        except Exception as e:
            print(f"Errore critico nella creazione dell'overlay artistico: {e}")
            import traceback
            traceback.print_exc() # Stampa la traccia completa dell'errore per il debug
            # Fallback: se tutto fallisce, prova a concatenare i clip normalmente
            try:
                print("Tentativo di fallback: concatenazione normale dei clip.")
                return concatenate_videoclips(clips, method="compose")
            except Exception as fallback_error:
                print(f"Errore anche nel fallback della concatenazione: {fallback_error}")
                return None
    # --- FINE: LA FUNZIONE create_artistic_overlay AGGIORNATA ---


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
    # Modalità singolo video (codice originale semplificato)
    uploaded_video = st.file_uploader("📤 Carica file video", type=["mp4", "mov", "avi", "mkv"])
    
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
                total_duration = 60
                
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
                        overlay1 = st.slider("📐 Overlay piccolo (%)", 5, 25, 12) # Range aggiornato
                    with col4:
                        overlay2 = st.slider("📐 Overlay grande (%)", 20, 50, 30) # Range aggiornato
                
                submitted = st.form_submit_button("🚀 Avvia elaborazione", use_container_width=True)

            if submitted:
                try:
                    segment_duration = float(segment_input)
                    
                    if segment_duration <= 0 or segment_duration >= total_duration:
                        st.error("❌ Durata segmento non valida.")
                    else:
                        shuffler = MultiVideoShuffler()
                        shuffler.add_video("V1", uploaded_video.name, total_duration, segment_duration)
                        
                        seed = int(seed_input) if seed_input.isdigit() else None
                        shuffler.shuffle_all_segments(seed)

                        st.subheader("📋 Scaletta generata")
                        st.code(shuffler.generate_schedule())

                        if MOVIEPY_AVAILABLE:
                            output_filename = f"remix_{uploaded_video.name}"
                            output_path = os.path.join(temp_dir, output_filename)
                            
                            progress_bar = st.progress(0)
                            status_text = st.empty()
                            
                            def progress_callback(message):
                                status_text.text(f"🎞️ {message}")
                            
                            video_paths = {"V1": input_path}
                            
                            # Parametri per elaborazione
                            fps_param = fps_value if custom_fps else None
                            # Passa i valori delle slider a overlay_sizes
                            overlay_sizes = [overlay1, overlay2] if enable_overlay else [12, 30] # Valori di default se disabilitato
                            
                            with st.spinner("🚀 Creazione video in corso..."):
                                success, result = shuffler.process_videos(
                                    video_paths, output_path, progress_callback, 
                                    fps=fps_param, enable_overlay=enable_overlay, overlay_sizes=overlay_sizes
                                )
                            
                            progress_bar.progress(100)
                            
                            if success:
                                st.success("✅ Video remixato completato!")
                                
                                with open(result, "rb") as f:
                                    st.download_button(
                                        "⬇️ Scarica video remixato",
                                        f.read(),
                                        file_name=output_filename,
                                        mime="video/mp4",
                                        use_container_width=True
                                    )
                            else:
                                st.error(f"❌ {result}")
                                
                            status_text.empty()
                        else:
                            st.warning("⚠️ MoviePy non disponibile - Solo simulazione")
                            
                except ValueError:
                    st.error("❌ Inserisci valori numerici validi.")
                except Exception as e:
                    st.error(f"❌ Errore: {str(e)}")
                    
        except Exception as e:
            st.error(f"❌ Errore lettura video: {str(e)}")

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
        
        # Salva i file
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
                duration1 = duration2 = 60
                
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
                        # Ho aggiornato il range dello slider per "Overlay piccolo" a 5-25%
                        overlay1 = st.slider("📐 Frame piccoli (%)", 5, 25, 12, key="multi_overlay1") 
                    with col5:
                        # Ho aggiornato il range dello slider per "Overlay grande" a 20-50%
                        overlay2 = st.slider("📐 Frame grandi (%)", 20, 50, 30, key="multi_overlay2")
                    
                    st.info("🎭 L'effetto sovrapporrà frame casuali dai due video creando un mix artistico!")
                
                submitted = st.form_submit_button("🎭 Crea Multi-Mix", use_container_width=True)

            if submitted:
                try:
                    segment_duration = float(segment_input)
                    
                    if segment_duration <= 0:
                        st.error("❌ Durata segmento deve essere positiva.")
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
                            output_filename = f"multimix_{video1.name.split('.')[0]}_{video2.name.split('.')[0]}.mp4"
                            output_path = os.path.join(temp_dir, output_filename)
                            
                            progress_bar = st.progress(0)
                            status_text = st.empty()
                            
                            def progress_callback(message):
                                status_text.text(f"🎭 {message}")
                            
                            video_paths = {"V1": video1_path, "V2": video2_path}
                            
                            # Parametri per elaborazione
                            fps_param = fps_value if custom_fps else None
                            # Passa i valori delle slider a overlay_sizes
                            overlay_sizes = [overlay1, overlay2] if enable_overlay else [12, 30] # Valori di default se disabilitato
                            
                            with st.spinner("🎭 Creazione Multi-Mix in corso..."):
                                success, result = shuffler.process_videos(
                                    video_paths, output_path, progress_callback,
                                    fps=fps_param, enable_overlay=enable_overlay, overlay_sizes=overlay_sizes
                                )
                            
                            progress_bar.progress(100)
                            
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
                                    st.error("❌ File di output non trovato.")
                            else:
                                st.error(f"❌ {result}")
                                
                            status_text.empty()
                        else:
                            st.warning("⚠️ MoviePy non disponibile - Solo simulazione")
                            
                except ValueError:
                    st.error("❌ Inserisci valori numerici validi.")
                except Exception as e:
                    st.error(f"❌ Errore: {str(e)}")
                    
        except Exception as e:
            st.error(f"❌ Errore lettura video: {str(e)}")
    
    elif video1 or video2:
        st.info("📂 Carica entrambi i video per procedere con il Multi-Mix.")
    else:
        st.info("📂 Carica due video per creare un Multi-Mix!")

# Istruzioni
with st.expander("ℹ️ Come funziona il Multi-Mix"):
    st.markdown("""
    **VideoDecomposer Multi-Mix** ti permette di:
    
    ### 🎬 Modalità Single Video:
    - Stessa funzionalità della versione originale
    - Divide un video in segmenti e li rimescola
    - **Novità:** Controlli FPS e effetti artistici!
    
    ### 🎭 Modalità Multi-Mix:
    - **Carica 2 video** diversi
    - **Imposta durata segmenti** (es. 3 secondi)
    - **Bilancia il mix** con lo slider (0.5 = bilanciato)
    - **Ottieni un video finale** con segmenti alternati dai due video!
    
    ### 🎲 **SEED Spiegato:**
    - **Senza seed**: Ordine casuale diverso ogni volta
    - **Con seed (es. 42)**: Ordine riproducibile identico
    - **Utilità**: Salva il seed per ricreare lo stesso mix!
    
    ### 🎨 **Effetti Artistici:**
    - **Sovrapposizione Frame**: Sovrappone frame più piccoli durante il video
    - **Frame Piccoli/Grandi**: Controlla dimensioni overlay (% dello schermo)
    - **Multi-Video**: Usa frame da entrambi i video per overlay creativi!
    
    ### 📹 **Controlli FPS:**
    - **FPS personalizzato**: Cambia velocità di riproduzione
    - **Valori bassi (15 FPS)**: Effetto cinematico vintage
    - **Valori alti (60 FPS)**: Fluidità extra per azioni veloci
    
    💡 **Suggerimenti:**
    - Usa video con durate simili per risultati migliori
    - Mix ratio 0.3 = più Video 2, 0.7 = più Video 1
    - Segmenti corti (1-3s) per transizioni dinamiche
    - Overlay artistici funzionano meglio con contenuti contrastanti
    - FPS 24-30 per risultati naturali, 15 per effetti vintage
    """)

# Pulizia file temporanei
if st.session_state.get('output_path') and os.path.exists(st.session_state.output_path):
    if st.button("🗑️ Pulisci file temporanei"):
        try:
            os.remove(st.session_state.output_path)
            st.session_state.processed_video = None
            st.session_state.output_path = None
            st.success("✅ File temporanei eliminati")
            st.rerun()
        except:
            st.warning("⚠️ Impossibile eliminare alcuni file temporanei")
