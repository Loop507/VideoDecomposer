import random
import os
import sys
from datetime import timedelta

try:
    from moviepy.editor import VideoFileClip, concatenate_videoclips
    MOVIEPY_AVAILABLE = True
except ImportError:
    MOVIEPY_AVAILABLE = False
    print("⚠️  MoviePy non installato. Funzionerà solo la simulazione.")
    print("   Per processare video reali, installa: pip install moviepy")

class VideoShuffler:
    def __init__(self):
        self.segments = []
        self.shuffled_order = []
        
    def parse_duration(self, duration_str):
        """Converte una stringa di durata (es. '5:30' o '330') in secondi"""
        if ':' in duration_str:
            parts = duration_str.split(':')
            if len(parts) == 2:  # MM:SS
                minutes, seconds = map(int, parts)
                return minutes * 60 + seconds
            elif len(parts) == 3:  # HH:MM:SS
                hours, minutes, seconds = map(int, parts)
                return hours * 3600 + minutes * 60 + seconds
        else:
            return int(duration_str)  # Secondi diretti
    
    def format_duration(self, seconds):
        """Converte secondi in formato HH:MM:SS"""
        return str(timedelta(seconds=seconds))
    
    def calculate_segments(self, total_duration, segment_duration):
        """Calcola i segmenti del video"""
        num_segments = total_duration // segment_duration
        remaining = total_duration % segment_duration
        
        self.segments = []
        
        # Segmenti completi
        for i in range(num_segments):
            start = i * segment_duration
            end = start + segment_duration
            self.segments.append({
                'id': i + 1,
                'start': start,
                'end': end,
                'duration': segment_duration
            })
        
        # Segmento finale se c'è un resto
        if remaining > 0:
            start = num_segments * segment_duration
            self.segments.append({
                'id': num_segments + 1,
                'start': start,
                'end': total_duration,
                'duration': remaining
            })
        
        return len(self.segments)
    
    def shuffle_segments(self, seed=None):
        """Rimescola i segmenti"""
        if seed:
            random.seed(seed)
        
        self.shuffled_order = list(range(len(self.segments)))
        random.shuffle(self.shuffled_order)
        
        return self.shuffled_order
    
    def generate_schedule(self):
        """Genera la scaletta testuale del video rimescolato"""
        schedule = []
        current_time = 0
        
        schedule.append("=" * 60)
        schedule.append("📋 SCALETTA VIDEO RIMESCOLATO")
        schedule.append("=" * 60)
        
        for i, segment_idx in enumerate(self.shuffled_order):
            segment = self.segments[segment_idx]
            
            schedule.append(f"\n🎬 Posizione {i+1} nel video finale:")
            schedule.append(f"   ├─ Segmento originale: #{segment['id']}")
            schedule.append(f"   ├─ Tempo originale: {self.format_duration(segment['start'])} → {self.format_duration(segment['end'])}")
            schedule.append(f"   ├─ Durata: {self.format_duration(segment['duration'])}")
            schedule.append(f"   └─ Nuovo tempo: {self.format_duration(current_time)} → {self.format_duration(current_time + segment['duration'])}")
            
            current_time += segment['duration']
        
        schedule.append("\n" + "=" * 60)
        schedule.append(f"⏱️  DURATA TOTALE: {self.format_duration(current_time)}")
        schedule.append("=" * 60)
        
        return "\n".join(schedule)
    
    def simulate_processing(self, input_file=None, output_file=None):
        """Simula il processo di creazione del video"""
        print("\n🎭 SIMULAZIONE RIMESCOLAMENTO VIDEO")
        print("=" * 50)
        
        if input_file:
            print(f"📁 File input: {input_file}")
        if output_file:
            print(f"💾 File output: {output_file}")
        
        print(f"🎯 Segmenti totali: {len(self.segments)}")
        print(f"🔀 Ordine rimescolato: {[i+1 for i in self.shuffled_order]}")
        
        # Simula il progresso
        print("\n⚙️  Processamento in corso...")
        for i, segment_idx in enumerate(self.shuffled_order):
            segment = self.segments[segment_idx]
            print(f"   └─ Processando segmento {segment['id']} ({i+1}/{len(self.segments)})")
        
        print("\n✅ Simulazione completata!")
        
    def process_video(self, input_file, output_file):
        """Processa il video reale usando MoviePy"""
        if not MOVIEPY_AVAILABLE:
            print("❌ MoviePy non disponibile. Uso solo simulazione.")
            self.simulate_processing(input_file, output_file)
            return False
        
        if not os.path.exists(input_file):
            print(f"❌ File non trovato: {input_file}")
            return False
        
        try:
            print(f"\n🎬 Caricamento video: {input_file}")
            video = VideoFileClip(input_file)
            
            print("✂️  Taglio segmenti...")
            clips = []
            
            for i, segment_idx in enumerate(self.shuffled_order):
                segment = self.segments[segment_idx]
                print(f"   └─ Segmento {segment['id']} ({i+1}/{len(self.segments)})")
                
                clip = video.subclip(segment['start'], segment['end'])
                clips.append(clip)
            
            print("🔗 Unione segmenti...")
            final_video = concatenate_videoclips(clips)
            
            print(f"💾 Salvataggio: {output_file}")
            final_video.write_videofile(output_file, verbose=False, logger=None)
            
            # Pulizia
            video.close()
            final_video.close()
            for clip in clips:
                clip.close()
            
            print("✅ Video rimescolato creato con successo!")
            return True
            
        except Exception as e:
            print(f"❌ Errore durante il processamento: {str(e)}")
            return False

def main():
    print("🎬 VIDEO SEGMENT SHUFFLER")
    print("=" * 40)
    
    shuffler = VideoShuffler()
    
    # Input durata video
    while True:
        try:
            duration_input = input("\n⏱️  Durata video (es. '5:30' o '330' secondi): ").strip()
            total_duration = shuffler.parse_duration(duration_input)
            print(f"   Durata riconosciuta: {shuffler.format_duration(total_duration)}")
            break
        except ValueError:
            print("❌ Formato non valido. Usa MM:SS, HH:MM:SS o secondi diretti.")
    
    # Input durata segmenti
    while True:
        try:
            segment_input = input("\n✂️  Durata segmenti (es. '30' secondi): ").strip()
            segment_duration = shuffler.parse_duration(segment_input)
            
            if segment_duration >= total_duration:
                print("❌ La durata del segmento deve essere minore della durata totale.")
                continue
                
            print(f"   Durata segmento: {shuffler.format_duration(segment_duration)}")
            break
        except ValueError:
            print("❌ Formato non valido. Usa MM:SS, HH:MM:SS o secondi diretti.")
    
    # Calcola segmenti
    num_segments = shuffler.calculate_segments(total_duration, segment_duration)
    print(f"\n📊 Saranno creati {num_segments} segmenti")
    
    # Seed per randomizzazione
    seed_input = input("\n🎲 Seed per randomizzazione (opzionale, premi Enter per random): ").strip()
    seed = int(seed_input) if seed_input.isdigit() else None
    
    # Rimescola
    shuffler.shuffle_segments(seed)
    
    # Mostra scaletta
    print("\n" + shuffler.generate_schedule())
    
    # Opzioni per il video
    print("\n🎥 OPZIONI VIDEO:")
    print("1. Solo simulazione")
    print("2. Processa video reale")
    
    choice = input("\nScelta (1-2): ").strip()
    
    if choice == "2":
        input_file = input("\n📁 Percorso file video input: ").strip()
        output_file = input("💾 Nome file output (es. 'video_rimescolato.mp4'): ").strip()
        
        if not output_file.endswith(('.mp4', '.avi', '.mov', '.mkv')):
            output_file += '.mp4'
        
        shuffler.process_video(input_file, output_file)
    else:
        shuffler.simulate_processing()
    
    print("\n🎉 Processo completato!")
    input("\nPremi Enter per uscire...")

if __name__ == "__main__":
    main()
