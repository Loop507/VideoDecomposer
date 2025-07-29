import random
import os
import shutil
import tempfile
from datetime import timedelta
import streamlit as st

try:
    from moviepy.editor import VideoFileClip, concatenate_videoclips
    MOVIEPY_AVAILABLE = True
except ImportError:
    MOVIEPY_AVAILABLE = False
    st.warning("⚠️ MoviePy non è installato. Funzionerà solo la simulazione.")


class VideoShuffler:
    def __init__(self):
        self.segments = []
        self.shuffled_order = []

    def format_duration(self, seconds):
        return str(timedelta(seconds=round(seconds)))

    def calculate_segments(self, total_duration, segment_duration):
        num_segments = int(total_duration // segment_duration)
        remaining = total_duration % segment_duration
        self.segments = []

        for i in range(num_segments):
            start = i * segment_duration
            end = min(start + segment_duration, total_duration)
            self.segments.append({'id': i + 1, 'start': start, 'end': end, 'duration': end - start})

        # Aggiungi l'ultimo segmento se c'è un resto significativo (almeno 0.5 secondi)
        if remaining > 0.5:
            start = num_segments * segment_duration
            self.segments.append({'id': num_segments + 1, 'start': start, 'end': total_duration, 'duration': remaining})

        return len(self.segments)

    def shuffle_segments(self, seed=None):
        if seed:
            random.seed(seed)
        self.shuffled_order = list(range(len(self.segments)))
        random.shuffle(self.shuffled_order)

    def generate_schedule(self):
        schedule = []
        current_time = 0
        schedule.append("📋 SCALETTA VIDEO RIMESCOLATO\n")
        schedule.append(f"🔀 Ordine originale: {[s['id'] for s in self.segments]}")
        schedule.append(f"🎲 Ordine mescolato: {[self.segments[i]['id'] for i in self.shuffled_order]}\n")

        for i, segment_idx in enumerate(self.shuffled_order):
            s = self.segments[segment_idx]
            schedule.append(
                f"🎬 Posizione {i+1}: Segmento #{s['id']} | "
                f"Originale: {self.format_duration(s['start'])}–{self.format_duration(s['end'])} → "
                f"Nuova posizione: {self.format_duration(current_time)}–{self.format_duration(current_time + s['duration'])}"
            )
            current_time += s['duration']

        schedule.append(f"\n⏱️ DURATA TOTALE: {self.format_duration(current_time)}")
        return "\n".join(schedule)

    def process_video(self, input_path, output_path, progress_callback=None):
        if not MOVIEPY_AVAILABLE:
            return False, "❌ MoviePy non disponibile."

        if not os.path.exists(input_path):
            return False, f"❌ File non trovato: {input_path}"

        video = None
        clips = []
        final_video = None

        try:
            if progress_callback:
                progress_callback("Caricamento video...")
            
            video = VideoFileClip(input_path)
            
            if progress_callback:
                progress_callback("Estrazione segmenti nell'ordine mescolato...")
            
            # DEBUG: Stampa l'ordine dei segmenti
            print(f"Ordine originale: {list(range(len(self.segments)))}")
            print(f"Ordine mescolato: {self.shuffled_order}")
            
            # Estrai i segmenti NELL'ORDINE MESCOLATO
            for i, segment_idx in enumerate(self.shuffled_order):
                s = self.segments[segment_idx]
                
                # Verifica che i tempi siano validi
                if s['start'] >= video.duration:
                    print(f"Segmento {s['id']} saltato: start >= durata video")
                    continue
                    
                # Assicurati che end non superi la durata del video
                end_time = min(s['end'], video.duration)
                if s['start'] >= end_time:
                    print(f"Segmento {s['id']} saltato: start >= end")
                    continue
                
                # Crea il subclip
                try:
                    print(f"Estraendo segmento #{s['id']} dalla posizione {i+1}: {s['start']:.2f}s - {end_time:.2f}s")
                    clip = video.subclip(s['start'], end_time)
                    clips.append(clip)
                    
                    if progress_callback:
                        progress_callback(f"Estratto segmento #{s['id']} alla posizione {i+1}/{len(self.shuffled_order)}")
                        
                except Exception as e:
                    print(f"Errore nell'estrazione del segmento {s['id']}: {e}")
                    if progress_callback:
                        progress_callback(f"Errore segmento #{s['id']}: {e}")
                    continue

            if not clips:
                return False, "❌ Nessun segmento valido estratto dal video."

            print(f"Totale clip estratti: {len(clips)}")
            
            if progress_callback:
                progress_callback(f"Concatenazione di {len(clips)} segmenti mescolati...")

            # Concatena i clip NELL'ORDINE IN CUI SONO STATI AGGIUNTI (che è l'ordine mescolato)
            final_video = concatenate_videoclips(clips, method="compose")
            
            if progress_callback:
                progress_callback("Salvataggio video finale...")

            # Scrivi il video finale con parametri ottimizzati
            final_video.write_videofile(
                output_path,
                codec='libx264',
                audio_codec='aac',
                temp_audiofile='temp-audio.m4a',
                remove_temp=True,
                verbose=False,
                logger=None
            )

            print(f"Video finale salvato: {output_path}")
            return True, output_path

        except Exception as e:
            print(f"Errore durante l'elaborazione: {str(e)}")
            return False, f"❌ Errore durante l'elaborazione: {str(e)}"
            
        finally:
            # Pulizia memoria
            try:
                if video:
                    video.close()
                if final_video:
                    final_video.close()
                for clip in clips:
                    if clip:
                        clip.close()
            except:
                pass


# --- STREAMLIT UI ---
st.set_page_config(page_title="VideoDecomposer by loop507", layout="wide")
st.title("🎬 VideoDecomposer by loop507")

# Inizializza session state
if 'processed_video' not in st.session_state:
    st.session_state.processed_video = None
if 'output_path' not in st.session_state:
    st.session_state.output_path = None

uploaded_video = st.file_uploader("📤 Carica file video", type=["mp4", "mov", "avi", "mkv"])

if uploaded_video:
    # Crea directory temporanea se non esiste
    temp_dir = tempfile.gettempdir()
    input_path = os.path.join(temp_dir, uploaded_video.name)
    
    # Salva il file caricato
    with open(input_path, "wb") as f:
        f.write(uploaded_video.read())

    try:
        # Leggi informazioni video
        if MOVIEPY_AVAILABLE:
            clip = VideoFileClip(input_path)
            total_duration = clip.duration
            clip.close()
        else:
            total_duration = 60  # Valore di default per simulazione
            
        st.video(uploaded_video)
        st.success(f"✅ Video caricato - Durata: {round(total_duration, 2)} secondi")

        # Form per i parametri
        with st.form("params_form"):
            col1, col2 = st.columns(2)
            
            with col1:
                segment_input = st.text_input("✂️ Durata segmenti (secondi)", "3")
                
            with col2:
                seed_input = st.text_input("🎲 Seed per randomizzazione (opzionale)", "")
            
            submitted = st.form_submit_button("🚀 Avvia elaborazione", use_container_width=True)

        if submitted:
            try:
                segment_duration = float(segment_input)
                
                if segment_duration <= 0:
                    st.error("❌ La durata del segmento deve essere positiva.")
                elif segment_duration >= total_duration:
                    st.error("❌ La durata del segmento deve essere minore della durata totale del video.")
                else:
                    # Inizializza lo shuffler
                    shuffler = VideoShuffler()
                    num_segments = shuffler.calculate_segments(total_duration, segment_duration)
                    
                    # Imposta seed se fornito
                    seed = int(seed_input) if seed_input.isdigit() else None
                    shuffler.shuffle_segments(seed)

                    # Verifica che il mescolamento sia avvenuto
                    original_order = list(range(len(shuffler.segments)))
                    is_shuffled = shuffler.shuffled_order != original_order
                    
                    if not is_shuffled:
                        st.warning("⚠️ L'ordine dei segmenti non è cambiato. Prova un seed diverso o lascia vuoto per casualità.")
                    else:
                        st.success(f"✅ Segmenti mescolati correttamente!")

                    # Mostra la scaletta
                    st.subheader("📋 Scaletta generata")
                    st.code(shuffler.generate_schedule())
                    
                    st.info(f"📊 Generati {num_segments} segmenti - Mescolamento: {'SÌ' if is_shuffled else 'NO'}")

                    if MOVIEPY_AVAILABLE:
                        # Elabora il video
                        output_filename = f"remix_{uploaded_video.name}"
                        output_path = os.path.join(temp_dir, output_filename)
                        
                        # Progress bar e status
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        
                        def progress_callback(message):
                            status_text.text(f"🎞️ {message}")
                        
                        with st.spinner("🎞️ Elaborazione in corso..."):
                            success, result = shuffler.process_video(input_path, output_path, progress_callback)
                            
                        progress_bar.progress(100)
                        
                        if success:
                            st.success("✅ Video remixato completato!")
                            
                            # Salva nel session state
                            st.session_state.processed_video = result
                            st.session_state.output_path = output_path
                            
                            # Mostra anteprima del risultato
                            if os.path.exists(result):
                                file_size = os.path.getsize(result) / (1024 * 1024)  # MB
                                st.info(f"📁 File generato: {file_size:.2f} MB")
                                
                                # Pulsante download
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
                            st.error(f"❌ Errore durante l'elaborazione: {result}")
                            
                        status_text.empty()
                    else:
                        st.warning("⚠️ MoviePy non disponibile - Solo simulazione completata")
                        
            except ValueError:
                st.error("❌ Inserisci valori numerici validi.")
            except Exception as e:
                st.error(f"❌ Errore imprevisto: {str(e)}")
                
    except Exception as e:
        st.error(f"❌ Errore durante la lettura del video: {str(e)}")
        
else:
    st.info("📂 Carica un video per iniziare l'elaborazione.")
    
    # Istruzioni
    with st.expander("ℹ️ Come funziona"):
        st.markdown("""
        **VideoDecomposer** divide il tuo video in segmenti di durata uguale e li rimescola casualmente:
        
        1. **Carica** un file video (MP4, MOV, AVI, MKV)
        2. **Imposta** la durata dei segmenti (es. 3 secondi)
        3. **Opzionale**: Inserisci un seed per risultati riproducibili
        4. **Scarica** il video remixato
        
        💡 **Suggerimento**: Usa segmenti più corti (1-5 secondi) per risultati più dinamici!
        """)

# Pulizia file temporanei alla chiusura
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
