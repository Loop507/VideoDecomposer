import random
import os
import shutil
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

        if remaining > 0 and total_duration > num_segments * segment_duration:
            start = num_segments * segment_duration
            self.segments.append({'id': num_segments + 1, 'start': start, 'end': total_duration, 'duration': total_duration - start})

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

        for i, segment_idx in enumerate(self.shuffled_order):
            s = self.segments[segment_idx]
            schedule.append(
                f"🎬 Posizione {i+1}: Segmento #{s['id']} | "
                f"{self.format_duration(s['start'])}–{self.format_duration(s['end'])} → "
                f"Nuovo tempo: {self.format_duration(current_time)}–{self.format_duration(current_time + s['duration'])}"
            )
            current_time += s['duration']

        schedule.append(f"\n⏱️ DURATA TOTALE: {self.format_duration(current_time)}")
        return "\n".join(schedule)

    def process_video(self, input_path, output_path):
        if not MOVIEPY_AVAILABLE:
            return False, "❌ MoviePy non disponibile."

        if not os.path.exists(input_path):
            return False, f"❌ File non trovato: {input_path}"

        try:
            video = VideoFileClip(input_path)
            clips = []
            for idx in self.shuffled_order:
                s = self.segments[idx]
                if s['start'] < s['end'] <= video.duration:
                    clips.append(video.subclip(s['start'], s['end']))
            final_video = concatenate_videoclips(clips)
            final_video.write_videofile(output_path)
            video.close()
            final_video.close()
            for clip in clips:
                clip.close()
            return True, output_path
        except Exception as e:
            return False, f"❌ Errore: {e}"


# --- STREAMLIT UI ---
st.set_page_config(page_title="VideoDecomposer by loop507")
st.title("🎬 VideoDecomposer by loop507")

uploaded_video = st.file_uploader("📤 Carica file video", type=["mp4", "mov", "avi", "mkv"])

if uploaded_video:
    input_path = f"/tmp/{uploaded_video.name}"
    with open(input_path, "wb") as f:
        f.write(uploaded_video.read())

    try:
        clip = VideoFileClip(input_path)
        total_duration = clip.duration
        st.video(uploaded_video)
        st.success(f"Durata video: {round(total_duration, 2)} secondi")

        with st.form("params_form"):
            segment_input = st.text_input("✂️ Durata segmenti (in secondi)", "3")
            seed_input = st.text_input("🎲 Seed per randomizzazione (opzionale)", "")
            submitted = st.form_submit_button("Avvia elaborazione")

        if submitted:
            try:
                segment_duration = int(segment_input)
                if segment_duration >= total_duration:
                    st.error("❌ Il segmento deve essere più corto del video.")
                else:
                    shuffler = VideoShuffler()
                    shuffler.calculate_segments(total_duration, segment_duration)
                    seed = int(seed_input) if seed_input.isdigit() else None
                    shuffler.shuffle_segments(seed)

                    st.code(shuffler.generate_schedule())

                    with st.spinner("🎞️ Elaborazione video..."):
                        output_path = f"/tmp/remix_{uploaded_video.name}"
                        success, result = shuffler.process_video(input_path, output_path)
                        if success:
                            st.success("✅ Video remixato completato!")
                            with open(result, "rb") as f:
                                st.download_button("⬇️ Scarica video remixato", f, file_name=f"remix_{uploaded_video.name}", mime="video/mp4")
                        else:
                            st.error(result)
            except Exception as e:
                st.error(f"Errore: {e}")
    except Exception as e:
        st.error(f"Errore durante la lettura del video: {e}")
else:
    st.info("📂 Carica un video per iniziare.")
