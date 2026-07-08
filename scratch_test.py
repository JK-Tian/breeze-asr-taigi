import sys
import os

# 把 workspace 原有的 src 加入 sys.path
parent_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "backend/src"))
if parent_src not in sys.path:
    sys.path.insert(0, parent_src)

from infrastructure.ml_models import SimpleDiarizer
from taigi_asr.engines.faster_whisper import FasterWhisperEngine

audio_path = r"d:\OneDrive\Program\Python_code\breeze-asr-taigi\backend\uploads\新錄音 12.m4a"

print("Loading ASR engine...")
asr = FasterWhisperEngine(device="cpu", compute_type="int8")
asr.load()

print(f"Transcribing {audio_path}...")
segments_gen = asr.transcribe(audio_path)
segments = list(segments_gen)

print(f"Got {len(segments)} segments from Whisper.")
for s in segments:
    print(f"  [{s.start_time:.2f} - {s.end_time:.2f}] {s.text}")

print("\nLoading Diarizer...")
diarizer = SimpleDiarizer(device="cpu")

print("Extracting embeddings and clustering...")
labels = diarizer.diarize(audio_path, segments)

print(f"\nFinal labels ({len(labels)}):")
for s, l in zip(segments, labels):
    print(f"[{l}] {s.start_time:.2f}-{s.end_time:.2f} {s.text}")
