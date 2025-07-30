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
        VERSIONE CORRETTA - DEBUG ATTIVO
        """
        try:
            print("=== DEBUG COLLAGE: INIZIO ===")
            print(f"Numero clip principali ricevuti: {len(main_clips_sequence)}")
            print(f"Numero segmenti totali disponibili: {len(all_segment_dicts)}")
            print(f"Video clips originali caricati: {list(self.video_clips_map.keys())}")
            
            if not main_clips_sequence or len(main_clips_sequence) <= 0:
                print("ERRORE: Nessun clip principale fornito")
                return None
            
            # Dimensione canvas
            base_w, base_h = main_clips_sequence[0].size
            print(f"Dimensione canvas: {base_w}x{base_h}")
            
            final_clips = []
            current_time = 0

            if not self.video_clips_map:
                print("ERRORE: video_clips_map vuota!")
                return None

            # Tipi di overlay per collage
            overlay_types = [
                ("Square Small", 1.0, 0.15, 0.25, 0.3),
                ("Square Medium", 1.0, 0.25, 0.35, 0.2), 
                ("Horizontal", 2.0, 0.25, 0.45, 0.2),
                ("Vertical", 0.5, 0.25, 0.45, 0.2),
                ("Wide", 3.0, 0.20, 0.40, 0.1),
            ]
            
            total_prob = sum(ot[4] for ot in overlay_types)
            normalized_overlay_types = [(desc, ar, min_s, max_s, prob/total_prob) for desc, ar, min_s, max_s, prob in overlay_types]

            for i, main_clip in enumerate(main_clips_sequence):
                print(f"\n--- ELABORAZIONE CLIP PRINCIPALE #{i+1} ---")
                
                if progress_callback:
                    progress_callback(f"Creando collage: segmento {i+1}/{len(main_clips_sequence)}")
                
                # ELEMENTO PRINCIPALE DEL COLLAGE (NON PIÙ SCHERMO INTERO)
                primary_size_factor = random.uniform(0.50, 0.75)  # Più piccolo per essere sicuri
                primary_w = int(base_w * primary_size_factor)
                primary_h = int(base_h * primary_size_factor)
                
                primary_w = max(200, primary_w)
                primary_h = max(150, primary_h)

                # Posizione casuale ma visibile
                primary_max_x = base_w - primary_w
                primary_max_y = base_h - primary_h
                primary_pos_x = random.randint(0, max(0, primary_max_x))
                primary_pos_y = random.randint(0, max(0, primary_max_y))

                primary_clip_duration = main_clip.duration
                
                # CREA L'ELEMENTO PRINCIPALE DEL COLLAGE
                primary_collage_element = (main_clip
                                           .resize((primary_w, primary_h))
                                           .set_position((primary_pos_x, primary_pos_y))
                                           .set_start(current_time)
                                           .set_opacity(0.9))  # Quasi opaco

                final_clips.append(primary_collage_element)
                print(f"AGGIUNTO ELEMENTO PRINCIPALE: {primary_w}x{primary_h} at ({primary_pos_x},{primary_pos_y}), opacità: 0.9")
                
                # ELEMENTI SECONDARI DEL COLLAGE
                if all_segment_dicts and len(all_segment_dicts) > 1:
                    num_secondary_overlays = random.randint(2, 4)  # Più elementi per effetto visibile
                    print(f"Aggiungendo {num_secondary_overlays} elementi secondari...")
                    
                    for overlay_idx in range(num_secondary_overlays):
                        try:
                            # Seleziona tipo overlay
                            choice_weights = [ot[4] for ot in normalized_overlay_types]
                            chosen_overlay_type = random.choices(normalized_overlay_types, weights=choice_weights, k=1)[0]
                            desc, target_aspect_ratio, min_size_perc, max_size_perc, _ = chosen_overlay_type

                            # Seleziona segmento casuale DIVERSO dal principale
                            available_segments = [s for s in all_segment_dicts if s['global_id'] != self.shuffled_order[i]['global_id']]
                            if not available_segments:
                                print("Nessun segmento alternativo disponibile")
                                continue
                                
                            source_segment_info = random.choice(available_segments)
                            source_video_clip_original = self.video_clips_map.get(source_segment_info['video_id'])
                            
                            if not source_video_clip_original:
                                print(f"SKIP: Video clip originale non trovato per {source_segment_info['video_id']}")
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
                                print(f"SKIP: Durata troppo breve ({secondary_overlay_duration:.2f}s)")
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
                                secondary_overlay_clip = (source_video_clip_original
                                                          .subclip(source_start_time_in_original, source_end_time_in_original)
                                                          .resize((overlay_w, overlay_h))
                                                          .set_position((pos_x, pos_y))
                                                          .set_start(overlay_start_time_in_final_video)
                                                          .set_opacity(0.6))  # Più trasparente

                                final_clips.append(secondary_overlay_clip)
                                print(f"AGGIUNTO OVERLAY SECONDARIO #{overlay_idx+1}: '{desc}' da '{source_segment_info['video_name']}' ({overlay_w}x{overlay_h}) at ({pos_x},{pos_y}), opacità: 0.6")
                            else:
                                print(f"SKIP: Durata video insufficiente")

                        except Exception as e:
                            print(f"ERRORE overlay secondario #{overlay_idx+1}: {e}")
                            continue
                
                current_time += primary_clip_duration
            
            print(f"\n=== RIASSUNTO COLLAGE ===")
            print(f"Totale clip nel composito: {len(final_clips)}")
            print(f"Canvas finale: {base_w}x{base_h}")
            
            if not final_clips:
                print("ERRORE: Nessun clip finale da comporre!")
                return None

            # Crea il composito finale
            print("Creazione CompositeVideoClip...")
            composite_video = CompositeVideoClip(final_clips, size=(base_w, base_h))
            composite_video = composite_video.set_duration(current_time)  # Imposta durata esplicita
            
            print("=== DEBUG COLLAGE: COMPLETATO ===")
            return composite_video
            
        except Exception as e:
            print(f"ERRORE CRITICO in create_artistic_overlay: {e}")
            import traceback
            traceback.print_exc()
            
            # Fallback: concatenazione normale
            print("FALLBACK: Concatenazione normale...")
            try:
                return concatenate_videoclips(main_clips_sequence, method="compose")
            except Exception as fallback_e:
                print(f"ERRORE anche nel fallback: {fallback_e}")
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
                print(f"Caricando video {video_id}: {path}")
                video_clips_original[video_id] = VideoFileClip(path)
            
            # Salva nella classe per create_artistic_overlay
            self.video_clips_map = video_clips_original 
            print(f"Video clips map popolata: {list(self.video_clips_map.keys())}")

            # Estrai segmenti per sequenza principale
            if progress_callback:
                progress_callback("Estrazione segmenti...")
            
            for i, segment in enumerate(self.shuffled_order):
                video_id = segment['video_id']
                video_clip_source = video_clips_original[video_id] 
                
                end_time = min(segment['end'], video_clip_source.duration)
                if segment['start'] >= end_time or segment['start'] >= video_clip_source.duration:
                    print(f"SKIP segmento {segment['global_id']} - tempi non validi")
                    continue
                
                try:
                    clip = video_clip_source.subclip(segment['start'], end_time)
                    
                    if fps and fps != clip.fps:
                        clip = clip.set_fps(fps)
                    
                    extracted_clips_for_final_sequence.append(clip)
                    print(f"Estratto segmento {segment['global_id']} per sequenza principale")
                    
                    if progress_callback:
                        progress_callback(f"Estratti {len(extracted_clips_for_final_sequence)}/{len(self.shuffled_order)} segmenti")
                        
                except Exception as e:
                    print(f"ERRORE estrazione segmento {segment['global_id']}: {e}")
                    continue

            if not extracted_clips_for_final_sequence:
                return False, "Nessun segmento valido estratto."
                
            print(f"Totale segmenti estratti: {len(extracted_clips_for_final_sequence)}")
            
            # Crea video finale
            if progress_callback:
                progress_callback("Creazione video finale...")

            print(f"Overlay abilitato: {enable_overlay}")
            print(f"Lunghezza clips sequence: {len(extracted_clips_for_final_sequence)}")
            print(f"Lunghezza all_segments: {len(self.all_segments)}")
            
            # PUNTO CRITICO: Verifica che il collage sia effettivamente chiamato
            if enable_overlay and len(extracted_clips_for_final_sequence) > 1:
                print("=== APPLICANDO EFFETTI COLLAGE ===")
                final_video = self.create_artistic_overlay(
                    extracted_clips_for_final_sequence, 
                    self.all_segments,
                    progress_callback
                )
                
                if final_video is None:
                    print("ATTENZIONE: create_artistic_overlay ha restituito None!")
                    return False, "Errore nella creazione del collage artistico"
                else:
                    print("Collage artistico creato con successo!")
            else:
                print("=== CONCATENAZIONE NORMALE (collage disabilitato) ===")
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

            print(f"Salvando video in: {output_path}")
            final_video.write_videofile(output_path, **output_params)
            print(f"Video salvato con successo!")
            
            return True, output_path

        except Exception as e:
            print(f"ERRORE GENERALE in process_videos: {e}")
            import traceback
            traceback.print_exc()
            return False, f"Errore: {str(e)}"
            
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
                print("Pulizia memoria completata.")
            except Exception as cleanup_error:
                print(f"Errore pulizia: {cleanup_error}")

# Test rapido della logica di collage (solo per debug)
def test_collage_logic():
    """Funzione di test per verificare la logica del collage"""
    print("=== TEST LOGICA COLLAGE ===")
    
    # Simula alcuni segmenti
    test_segments = [
        {'video_id': 'V1', 'video_name': 'Video1.mp4', 'segment_id': 1, 'start': 0, 'end': 3, 'duration': 3, 'global_id': 'V1_S1'},
        {'video_id': 'V2', 'video_name': 'Video2.mp4', 'segment_id': 1, 'start': 0, 'end': 3, 'duration': 3, 'global_id': 'V2_S1'},
        {'video_id': 'V1', 'video_name': 'Video1.mp4', 'segment_id': 2, 'start': 3, 'end': 6, 'duration': 3, 'global_id': 'V1_S2'},
    ]
    
    shuffler = MultiVideoShuffler()
    shuffler.all_segments = test_segments
    shuffler.shuffled_order = test_segments[:2]  # Solo primi 2 per test
    
    print(f"Segmenti totali disponibili: {len(shuffler.all_segments)}")
    print(f"Sequenza principale: {len(shuffler.shuffled_order)}")
    
    # Test logica di selezione overlay
    for i, segment in enumerate(shuffler.shuffled_order):
        print(f"\nTestando segmento principale #{i+1}: {segment['global_id']}")
        
        # Segmenti disponibili per overlay (escluso quello principale)
        available_for_overlay = [s for s in shuffler.all_segments if s['global_id'] != segment['global_id']]
        print(f"Segmenti disponibili per overlay: {[s['global_id'] for s in available_for_overlay]}")
        
        if available_for_overlay:
            selected = random.choice(available_for_overlay)
            print(f"Selezionato per overlay: {selected['global_id']}")
        else:
            print("Nessun segmento disponibile per overlay!")
    
    print("=== FINE TEST ===")

# Esegui test se chiamato direttamente
if __name__ == "__main__":
    test_collage_logic()
