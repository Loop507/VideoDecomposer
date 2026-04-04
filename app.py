import streamlit as st
import os
import random
import tempfile
import traceback
from moviepy.editor import VideoFileClip, concatenate_videoclips
from PIL import Image

# Patch per compatibilità MoviePy/Pillow
if hasattr(Image, 'Resampling'):
    Image.ANTIALIAS = Image.Resampling.LANCZOS
else:
    Image.ANTIALIAS = Image.LANCZOS

class MultiVideoShuffler:
    """Gestisce la segmentazione casuale e il montaggio di più video."""
    def __init__(self):
        self.all_segments = []
        self.shuffled_order = []
        self.target_size = None 

    def add_video(self, video_id, video_name, total_duration, min_dur, max_dur):
        """Taglia il video in pezzi con durata casuale tra min_dur e max_dur."""
        current_time = 0
        added_count = 0
        
        while current_time < total_duration:
            # Sceglie una durata random nel range impostato (es. tra 0.2 e 0.4)
            seg_dur = random.uniform(min_dur, max_dur)
            end_time = min(current_time + seg_dur, total_duration)
            
            # Evitiamo micro-frammenti quasi invisibili
            if end_time - current_time > 0.05:
                self.all_segments.append({
                    'video_id': video_id,
                    'video_name': video_name,
                    'start': current_time,
                    'end': end_time,
                    'duration': end_time - current_time
                })
                added_count += 1
            current_time = end_time
        return added_count

    def shuffle(self, seed=None):
        """Mescola tutti i segmenti di tutti i video caricati."""
        if seed is not None and seed != 0:
            random.seed(seed)
        self.shuffled_order = list(self.all_segments)
        random.shuffle(self.shuffled_order)

    def process_videos(self, video_paths, output_path, progress_callback=None, fps=None, max_total_duration=None):
        """Montaggio finale ottimizzato per evitare crash di memoria."""
        video_clips_originals = {}
        extracted_clips = []
        
        try:
            # 1. Apertura flussi video
            for v_id, path in video_paths.items():
                video_clips_originals[v_id] = VideoFileClip(path)
            
            # Risoluzione basata sul primo video
            self.target_size = video_clips_originals[next(iter(video_clips_originals))].size

            # 2. Selezione segmenti per durata finale (Randomizzazione Reale)
            render_order = []
            accumulated_time = 0
            for seg in self.shuffled_order:
                if max_total_duration and accumulated_time >= max_total_duration:
                    break
                render_order.append(seg)
                accumulated_time += seg['duration']

            # Limite di sicurezza software (max 800 clip simultanee)
            if len(render_order) > 800:
                render_order = render_order[:800]
                st.info("💡 Limite di 800 frammenti raggiunto per garantire la stabilità.")

            # 3. Creazione subclips
            for i, seg in enumerate(render_order):
                source = video_clips_originals[seg['video_id']]
                # Subclip + Resize + FPS in un colpo solo
                clip = (source.subclip(seg['start'], seg['end'])
                        .resize(newsize=self.target_size)
                        .set_fps(fps if fps else 24))
                extracted_clips.append(clip)
                
                if progress_callback and i % 25 == 0:
                    progress_callback(f"Elaborazione: {i}/{len(render_order)} pezzi")

            # 4. Concatenazione e Scrittura Ultra-Veloce
            final_video = concatenate_videoclips(extracted_clips, method="chain")
            final_video.write_videofile(
                output_path, 
                fps=fps or 24, 
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
            # PULIZIA RAM: Fondamentale per evitare crash
            for c in extracted_clips:
                try: c.close()
                except: pass
            for v in video_clips_originals.values():
                try: v.close()
                except: pass

def handle_multi_video():
    st.header("🧪 Multi-Mix (Fino a 4 Video)")
    
    col1, col2 = st.columns(2)
    files = [col1.file_uploader(f"Video {i+1}", type=["mp4","mov","avi"]) for i in range(4)]
    
    st.markdown("---")
    st.subheader("🎲 Settaggi Ritmo e Random")
    
    c1, c2 = st.columns(2)
    with c1:
        ritmo = st.slider("Range durata frammenti (secondi)", 0.1, 2.0, (0.2, 0.4), step=0.1)
        min_d, max_d = ritmo
    with c2:
        final_dur = st.number_input("Durata finale desiderata (sec)", 10, 600, 120)
        seed = st.number_input("Seed (0 per random totale)", value=0)
        fps_val = st.selectbox("FPS", [24, 30, 60], index=0)

    if st.button("🚀 GENERA MIX FRENETICO"):
        valid_files = [f for f in files if f is not None]
        if not valid_files:
            st.error("Carica almeno un video!")
            return

        with st.spinner("Frullando i video..."):
            shuffler = MultiVideoShuffler()
            paths = {}
            
            # Salvataggio temporaneo
            for i, f in enumerate(valid_files):
                tfile = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4')
                tfile.write(f.read())
                paths[i] = tfile.name
                
                # Ottieni durata per segmentare
                with VideoFileClip(tfile.name) as tmp:
                    shuffler.add_video(i, f.name, tmp.duration, min_d, max_d)
            
            shuffler.shuffle(seed if seed != 0 else None)
            
            out_path = os.path.join(tempfile.gettempdir(), "mix_finale.mp4")
            
            success, msg = shuffler.process_videos(
                paths, out_path, 
                progress_callback=st.text, 
                fps=fps_val, 
                max_total_duration=final_dur
            )
            
            if success:
                st.success("✅ Mix completato!")
                with open(out_path, "rb") as f:
                    st.download_button("📥 Scarica il tuo Mix", f, "video_decomposed.mp4")
            else:
                st.error(f"Errore: {msg}")

def main():
    st.set_page_config(page_title="VideoDecomposer PRO", layout="wide")
    st.title("🎬 VideoDecomposer PRO")
    handle_multi_video()

if __name__ == "__main__":
    main()
