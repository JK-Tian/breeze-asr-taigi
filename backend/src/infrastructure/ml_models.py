import sys
import os
import torch
import torchaudio
import numpy as np
from pathlib import Path
from sklearn.cluster import AgglomerativeClustering
from speechbrain.inference.speaker import EncoderClassifier

# 把 workspace 原有的 src 加入 sys.path 藉此重複利用 taigi_asr 模組
parent_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../src"))
if parent_src not in sys.path:
    sys.path.insert(0, parent_src)

from taigi_asr.engines.faster_whisper import FasterWhisperEngine

import os
import configparser

def get_diarization_config():
    config = configparser.ConfigParser()
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "config.ini")
    
    # 預設值
    params = {
        "window_size_s": 1.5,
        "step_s": 0.5,
        "distance_threshold": 0.70
    }
    
    if os.path.exists(config_path):
        config.read(config_path, encoding='utf-8')
        if "Diarization" in config:
            params["window_size_s"] = config.getfloat("Diarization", "window_size_s", fallback=1.5)
            params["step_s"] = config.getfloat("Diarization", "step_s", fallback=0.5)
            params["distance_threshold"] = config.getfloat("Diarization", "distance_threshold", fallback=0.70)
            
    return params

class SimpleDiarizer:
    def __init__(self, device="cpu"):
        self.device = device
        # Load ECAPA-TDNN speaker embedding model from SpeechBrain
        self.classifier = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb", 
            run_opts={"device": device}
        )
        # 讀取設定檔
        self.config = get_diarization_config()

    def diarize(self, audio_path: str):
        from faster_whisper.audio import decode_audio
        try:
            audio_np = decode_audio(audio_path, sampling_rate=16000)
        except Exception as e:
            print(f"Error loading audio: {e}")
            return None
            
        signal = torch.from_numpy(audio_np).unsqueeze(0).to(self.device)
        fs = 16000
        
        # Sliding window parameters
        window_size_s = self.config["window_size_s"]
        step_s = self.config["step_s"]
        window_samples = int(window_size_s * fs)
        step_samples = int(step_s * fs)
        total_samples = signal.shape[1]
        
        embeddings = []
        window_times = []
        
        for start_idx in range(0, total_samples, step_samples):
            end_idx = start_idx + window_samples
            if end_idx > total_samples:
                end_idx = total_samples
                
            if end_idx - start_idx < int(0.2 * fs):
                continue
                
            seg_signal = signal[:, start_idx:end_idx]
            emb = self.classifier.encode_batch(seg_signal)
            embeddings.append(emb.squeeze().cpu().numpy())
            window_times.append((start_idx / fs, end_idx / fs))
            
            if end_idx == total_samples:
                break
                
        if not embeddings:
            return None
            
        X = np.array(embeddings)
        X = X / np.linalg.norm(X, axis=1, keepdims=True)
        
        # Use AgglomerativeClustering with distance threshold from config
        clustering = AgglomerativeClustering(
            n_clusters=None,
            metric="cosine",
            linkage="average",
            distance_threshold=self.config["distance_threshold"]
        )
        labels = clustering.fit_predict(X)
        
        timeline = []
        for (w_start, w_end), label in zip(window_times, labels):
            timeline.append({"start": w_start, "end": w_end, "speaker": f"SPEAKER_{label:02d}"})
            
        return timeline

class MeetingTranscriber:
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = MeetingTranscriber()
        return cls._instance

    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Loading ML models on {self.device}...")
        
        # Determine compute_type adaptively
        # GPU 通常支援 int8_float32 或 float16，而 CPU 則最穩定的選擇是 int8 或 float32
        adaptive_compute_type = "int8_float32" if self.device == "cuda" else "int8"
        
        # 1. Load Breeze ASR
        self.asr_engine = FasterWhisperEngine(
            device=self.device,
            compute_type=adaptive_compute_type
        )
        self.asr_engine.load()
        
        # 2. Authenticate to HuggingFace Hub if token is available (prevents rate limits)
        hf_token = os.environ.get("HF_TOKEN")
        if hf_token:
            try:
                from huggingface_hub import login
                login(token=hf_token)
                print("HuggingFace Hub logged in successfully.")
            except Exception as e:
                print(f"Warning: Failed to log in to HuggingFace Hub. Error: {e}")
                
        # 3. Load SpeechBrain Diarizer
        try:
            self.diarizer = SimpleDiarizer(device=self.device)
            print("SpeechBrain Diarizer loaded successfully.")
        except Exception as e:
            self.diarizer = None
            print(f"Warning: Diarizer failed to load. Error: {e}")

    def process_audio(self, audio_path: str) -> str:
        print(f"Running ASR on {audio_path}...")
        segments = self.asr_engine.transcribe(audio_path, word_timestamps=True)
        segments_list = list(segments)
        
        if not self.diarizer or not segments_list:
            return "\n".join([f"{seg.start_time:.2f} - {seg.end_time:.2f} : {seg.text}" for seg in segments_list])
            
        print(f"Running Sliding Window Diarization on {audio_path}...")
        timeline = self.diarizer.diarize(audio_path)
        
        if not timeline:
            return "\n".join([f"{seg.start_time:.2f} - {seg.end_time:.2f} : {seg.text}" for seg in segments_list])
            
        def get_speaker_at(t):
            best_spk = "SPEAKER_UNKNOWN"
            min_dist = float('inf')
            for w in timeline:
                center = (w["start"] + w["end"]) / 2
                dist = abs(center - t)
                if w["start"] <= t <= w["end"] and dist < min_dist:
                    min_dist = dist
                    best_spk = w["speaker"]
            return best_spk if best_spk != "SPEAKER_UNKNOWN" else timeline[-1]["speaker"]
        
        result_lines = []
        for segment in segments_list:
            if not segment.words:
                center = (segment.start_time + segment.end_time) / 2
                spk = get_speaker_at(center)
                result_lines.append(f"{segment.start_time:.2f} - {segment.end_time:.2f} [{spk}]: {segment.text}")
                continue
                
            current_speaker = None
            current_chunk_words = []
            chunk_start = None
            
            def flush_chunk(end_t):
                if current_chunk_words:
                    chunk_text = "".join(w["word"] for w in current_chunk_words).strip()
                    if chunk_text:
                        result_lines.append(f"{chunk_start:.2f} - {end_t:.2f} [{current_speaker}]: {chunk_text}")
                    current_chunk_words.clear()

            for w in segment.words:
                w_center = (w["start"] + w["end"]) / 2
                spk = get_speaker_at(w_center)
                
                if current_speaker is None:
                    current_speaker = spk
                    chunk_start = w["start"]
                    
                if spk != current_speaker:
                    flush_chunk(w["start"])
                    current_speaker = spk
                    chunk_start = w["start"]
                    
                current_chunk_words.append(w)
                
            if current_chunk_words:
                flush_chunk(current_chunk_words[-1]["end"])
                
        return "\n".join(result_lines)
