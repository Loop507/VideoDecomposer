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

    def parse_duration(self, duration_str):
        if ':' in duration_str:
            parts = duration_str.split(':')
            if len(parts) == 2:
                minutes, seconds = map(int, parts)
                return minutes * 60 + seconds
            elif len(parts) == 3:
                hours, minutes, seconds = map(int, parts)
                return hours * 3600 + minutes * 60 + seconds
        return int(duration_str)

    def format_duration(self, seconds):
        return str(timedelta(seconds=seconds))

    def calculate_segments(self, total_duration, segment_duration):
        num_segments = total_duration // segment_duration
        remaining = total_duration % segment_duration
        self.segments = []

        for i in range(num_segments):
            start = i * segment_duration
            end = start + segment_duration
            self.segments.append({'id': i + 1, 'start': start, 'end': end, 'duration': segment_duration})

        if remaining > 0:
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

        for i, segment_idx in enumerate(self.shuffled_order):
            s = self.segments[segment_idx]
            schedule.append(f"🎬 Posizione {i+1}: Segmento #{s['id']} | {self.format_duration(s['start'])}–{self.format_duration(s['end'])} → Nuovo tempo: {self.format_duration(current_time)}–{self.format_duration(current_time + s['duration'])}")
            current_time += s['duration']

        schedule.append(f"\n⏱️ DURATA TOTALE: {self.format_duration(current_time)}")
        return "\n".join(schedule)

    def simulate_processing(self):
        log = []
        log.append("🎭 SIMULAZIONE RIMESCOLAMENTO VIDEO\n")
        for i, segment_idx in enumerate(self.shuffled_order):
            segment = self.segments[segment_idx]
            log.append(f"   └─ Processando segmento {segment['id']} ({i+1}/{len(self.segments)})")
        log.append("\n✅ Simulazione completata!")
        return "\n".join(log)

    def process_video(self, input_path, output_path):
        if not MOVIEPY_AVAILABLE:
            return False, "❌ MoviePy non disponibile."

        if not os.path.exists(input_path):
            return False, f"❌ File non trovato: {input_path}"

        try:
            video = VideoFileClip(input_path)
            clips = [video.subclip(self.segments[idx]['start'], self.segments[idx]['end']) for idx in self.shuffled_order]
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
st.title("🎬 Video Segment Shuffler")

with st.form("params_form"):
    duration_input = st.text_input("⏱️ Durata totale video (es. '5:30' o '330')", "2:00")
    segment_input = st.text_input("✂️ Durata segmenti (es. '30')", "30")
    seed_input = st.text_input("🎲 Seed per randomizzazione (opzionale)", "")
    uploaded_video = st.file_uploader("📤 Carica file video", type=["mp4", "mov", "avi", "mkv"])
    submitted = st.form_submit_button("Avvia")

if submitted:
    try:
        shuffler = VideoShuffler()
        total_duration = shuffler.parse_duration(duration_input)
        segment_duration = shuffler.parse_duration(segment_input)

        if segment_duration >= total_duration:
            st.error("❌ La durata del segmento deve essere minore della durata totale.")
        else:
            shuffler.calculate_segments(total_duration, segment_duration)
            seed = int(seed_input) if seed_input.isdigit() else None
            shuffler.shuffle_segments(seed)

            st.success("✅ Segmenti creati e rimescolati")
            st.code(shuffler.generate_schedule())

            if uploaded_video is None:
                st.info("💡 Nessun video caricato: eseguo solo simulazione.")
                st.text(shuffler.simulate_processing())
            else:
                with st.spinner("🎞️ Elaborazione video in corso..."):
                    input_path = f"/tmp/input_{uploaded_video.name}"
                    output_path = f"/tmp/remixed_{uploaded_video.name}"
                    with open(input_path, "wb") as f:
                        f.write(uploaded_video.read())

                    success, result = shuffler.process_video(input_path, output_path)
                    if success:
                        st.success("✅ Video remixato creato!")
                        with open(output_path, "rb") as f:
                            st.download_button("⬇️ Scarica video remixato", f, file_name=f"remix_{uploaded_video.name}", mime="video/mp4")
                    else:
                        st.error(result)
    except Exception as e:
        st.error(f"Errore: {e}")
