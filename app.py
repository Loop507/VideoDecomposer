import streamlit as st
import os
import random
import tempfile
import numpy as np
from moviepy.editor import VideoFileClip, concatenate_videoclips
from PIL import Image

# --- CONFIGURAZIONE E PATCH ---
if hasattr(Image, 'Resampling'):
    Image.ANTIALIAS = Image.Resampling.LANCZOS
else:
    Image.ANTIALIAS = Image.LANCZOS

# --- MOTORE PROCEDURALE (SLIT-SCAN) ---
def apply_slit_scan_effect(get_frame, t, duration, strand_val, mode):
    """
    Gestisce la scomposizione dei pixel in strisce (Punti 1, 2 e 4 del prompt tecnico).
    """
    frame = get_frame(t).copy()
    h, w, _ = frame.shape
    progress = t / duration
    
    # 4. Logica di Convergenza Condizionale (Magnetismo)
    # Aumenta la probabilità di tornare alla posizione originale verso la fine
    magnet_prob = 0 if progress < 0.7 else ((progress - 0.7) / 0.3) ** 2
    
    # Selezione direzione (Orizzontale, Verticale o Mix)
    current_mode = mode
    if mode == "Mix":
        current_mode = random.choice(["Orizzontale", "Verticale"])

    if current_mode == "Orizzontale":
        # 1. Partizionamento Spaziale (Strisce Orizzontali)
        current_y = 0
        while current_y < h:
            strand_h = int(random.uniform(strand_val * 0.5, strand_val * 2))
            next_y = min(current_y + strand_h, h)
            
            # 2. Motore di Traslazione (Pixel Shifting)
            if random.random() > magnet_prob:
                chaos_factor = np.sin(np.pi * progress) # Curva di potenza
                offset = int(random.uniform(-w, w) * chaos_factor)
                frame[current_y:next_y, :] = np.roll(frame[current_y:next_y, :], offset, axis=1)
            current_y = next_y
            
    else: # Modalità Verticale
        # 1. Partizionamento Spaziale (Strisce Verticali)
        current_x = 0
        while current_x < w:
            strand_w = int(random.uniform(strand_val * 0.5, strand_val * 2))
            next_x = min(current_x + strand_w, w)
            
            # 2. Motore di Traslazione
            if random.random() > magnet_prob:
                chaos_factor = np.sin(np.pi * progress)
                offset = int(random.uniform(-h, h) * chaos_factor)
                frame[:, current_x:next_x] = np.roll(frame[:, current_x:next_x], offset, axis=0)
            current_x = next_x
            
    return frame

# --- GESTORE LOGICA VIDEO ---
class MultiVideoShuffler:
    def __init__(self):
        self.all_segments = []
        self.shuffled_order = []
        self.target_size = None 

    def add_video(self, video_id, video_name, total_duration, min_dur, max_dur):
        """Scompone il video in segmenti temporali (Logica originale)."""
        current_time = 0
        while current_time < total_duration:
            seg_dur = random.uniform(min_dur, max_dur)
            end_time = min(current_time + seg_dur, total_duration)
            if end_time - current_time > 0.05:
                self.all_segments.append({
                    'video_id': video_id,
                    'start': current_time,
                    'end': end_time,
                    'duration': end_time - current_time
                })
            current_time = end_time

    def shuffle(self, seed=None):
        """Mescola l'ordine dei segmenti."""
        if seed is not None and seed != 0:
            random.seed(seed)
        self.shuffled_order = list(self.all_segments)
        random.shuffle(self.shuffled_order)

    def process_videos(self, video_paths, output_path, fps, max_total_duration, strand_val, use_effect, mode):
        """Montaggio finale con protezione anti-crash."""
        video_clips_originals = {}
        extracted_clips = []
        
        try:
            # 1. Caricamento flussi
            for v_id, path in video_paths.items():
                video_clips_originals[v_id] = VideoFileClip(path)
            
            self.target_size = video_clips_originals[next(iter(video_clips_originals))].size

            # 2. Selezione segmenti per durata finale
            render_order = []
            accumulated_time = 0
            for seg in self.shuffled_order:
                if accumulated_time >= max_total_duration:
                    break
                render_order.append(seg)
                accumulated_time += seg['duration']

            # 3. Estrazione clip
            for seg in render_order:
                source = video_clips_originals[seg['video_id']]
                clip = (source.subclip(seg['start'], seg['end'])
                        .resize(newsize=self.target_size)
                        .set_fps(fps))
                extracted_clips.append(clip)
                
            # 4. Concatenazione
            final_video = concatenate_videoclips(extracted_clips, method="chain")
            
            # 5. Applicazione Effetto Pixel (se attivo)
            if use_effect:
                final_video = final_video.fl(lambda gf, t: apply_slit_scan_effect(gf, t, final_video.duration, strand_val, mode))

            # 6. Scrittura su Disco (Rendering)
            final_video.write_videofile(
                output_path, 
                fps=fps, 
                codec="libx264", 
                audio_codec="aac",
                preset="ultrafast", 
                threads=4, 
                logger=None
            )
            return True, output_path

        except Exception as e:
            return False, str(e)
        finally:
            # Pulizia RAM fondamentale
            for c in extracted_clips:
                try: c.close()
                except: pass
            for v in video_clips_originals.values():
                try: v.close()
                except: pass

# --- INTERFACCIA UTENTE ---
def main():
    st.set_page_config(page_title="VideoDecomposer PRO", layout="wide")
    st.title("🎬 VideoDecomposer & Slit-Scan PRO")
    
    col1, col2 = st.columns(2)
    with col1:
        files = [st.file_uploader(f"Video {i+1}", type=["mp4","mov","avi"]) for i in range(4)]
    
    st.markdown("---")
    
    c1, c2, c3 = st.columns(3)
    with c1:
        st.subheader("🎲 Ritmo e Durata")
        ritmo = st.slider("Taglio frammenti (sec)", 0.1, 1.5, (0.2, 0.4))
        final_dur = st.number_input("Durata finale (sec)", 5, 300, 30)
        seed = st.number_input("Seed (0 = random)", value=0)

    with c2:
        st.subheader("🌀 Effetto Slit-Scan")
        attiva_effetto = st.checkbox("ATTIVA EFFETTO PIXEL", value=True)
        direzione = st.selectbox("Direzione Strisce", ["Orizzontale", "Verticale", "Mix"])
        strand_val = st.slider("Spessore strisce", 5, 100, 30, disabled=not attiva_effetto)
    
    with c3:
        st.subheader("⚙️ Esportazione")
        fps_val = st.selectbox("FPS (Consigliato 24)", [24, 30, 60], index=0)
        genera = st.button("🚀 GENERA MIX PROCEDURALE", use_container_width=True)

    if genera:
        valid_files = [f for f in files if f is not None]
        if not valid_files:
            st.error("Per favore, carica almeno un video!")
            return

        with st.spinner("Frullando i pixel... Questo processo richiede tempo CPU."):
            shuffler = MultiVideoShuffler()
            paths = {}
            
            # Salvataggio temporaneo file caricati
            for i, f in enumerate(valid_files):
                tfile = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4')
                tfile.write(f.read())
                paths[i] = tfile.name
                with VideoFileClip(tfile.name) as tmp:
                    shuffler.add_video(i, f.name, tmp.duration, ritmo[0], ritmo[1])
            
            shuffler.shuffle(seed)
            out_path = os.path.join(tempfile.gettempdir(), "mix_finale_pro.mp4")
            
            success, msg = shuffler.process_videos(
                paths, out_path, 
                fps=fps_val, 
                max_total_duration=final_dur,
                strand_val=strand_val,
                use_effect=attiva_effetto,
                mode=direzione
            )
            
            if success:
                st.success("✅ Video generato con successo!")
                st.video(out_path)
                with open(out_path, "rb") as f:
                    st.download_button("📥 Scarica il tuo Mix", f, "video_pro_result.mp4")
            else:
                st.error(f"Errore durante l'elaborazione: {msg}")

if __name__ == "__main__":
    main()
