#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
旗艦版影音轉字幕逐字稿工具 (SRT Transcriber)
整合多模型切換、繁體中文與台灣台語特化、多格式輸出與硬體自適應降級。
遵循 S.O.L.I.D. 原則與 Clean Architecture 設計。

支援格式：
- 影片：mp4, mkv, avi, mov, wmv, flv, webm
- 音訊：mp3, wav, m4a, flac, ogg, aac, wma
- 輸出：srt, vtt, txt, json
"""

import os
import sys
import json
import argparse
from pathlib import Path
from typing import Optional, List, Set, Tuple, Dict, Any


# ==============================================================================
# 格式與常數定義
# ==============================================================================

# 支援的影片副檔名
VIDEO_EXTENSIONS: Set[str] = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm"}

# 支援的音訊副檔名
AUDIO_EXTENSIONS: Set[str] = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".wma"}

# 所有支援的媒體副檔名
SUPPORTED_EXTENSIONS: Set[str] = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS

# MediaTek Breeze-ASR-26 CTranslate2 格式模型權重倉庫
BREEZE_ASR_CT2_REPO = "paulpengtw/faster-whisper-Breeze-ASR-26-ct2"

# 模型名稱別名對照表 (方便 CLI 簡化輸入)
MODEL_ALIASES: Dict[str, str] = {
    "breeze-asr": BREEZE_ASR_CT2_REPO,
    "breeze-asr-26": BREEZE_ASR_CT2_REPO,
    "breeze": BREEZE_ASR_CT2_REPO,
    "taigi": BREEZE_ASR_CT2_REPO,
    "large-v3": "large-v3",
    "large-v2": "large-v2",
    "large": "large-v3",
    "medium": "medium",
    "small": "small",
    "base": "base",
    "tiny": "tiny",
}

# 台灣繁體中文與台語專用初始提示詞 (Initial Prompt)
DEFAULT_ZH_TW_PROMPT = (
    "這是一段繁體中文與台灣台語（Taigi）對話，包含各項專業工程、機台操作、換模調機、公差規格與品質管理術語，請輸出繁體中文。"
)


# ==============================================================================
# 時間戳與格式化工具 (Single Responsibility: Timestamp & Text Formatting)
# ==============================================================================

def format_timestamp(seconds: float) -> str:
    """
    將秒數轉換為標準 SRT 時間戳格式：HH:MM:SS,mmm
    例如：3.5 秒 -> 00:00:03,500
    """
    if seconds < 0:
        seconds = 0.0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    milliseconds = int(round((seconds - int(seconds)) * 1000))
    if milliseconds >= 1000:
        secs += 1
        milliseconds -= 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def format_vtt_timestamp(seconds: float) -> str:
    """
    將秒數轉換為 WebVTT 時間戳格式：HH:MM:SS.mmm
    例如：3.5 秒 -> 00:00:03.500
    """
    if seconds < 0:
        seconds = 0.0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    milliseconds = int(round((seconds - int(seconds)) * 1000))
    if milliseconds >= 1000:
        secs += 1
        milliseconds -= 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{milliseconds:03d}"


def segments_to_srt(segments, max_words_per_segment: Optional[int] = None) -> str:
    """
    將轉寫片段轉換為合規之 SRT 字幕字串。
    支援依據 max_words_per_segment 自動等比切分超長語句。
    """
    srt_lines = []
    segment_index = 1

    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue

        # 若設定了字數上限且超過則平滑拆分
        words = text.split()
        if max_words_per_segment and len(words) > max_words_per_segment:
            total_duration = segment.end - segment.start
            words_count = len(words)

            for chunk_start_idx in range(0, words_count, max_words_per_segment):
                chunk_end_idx = min(chunk_start_idx + max_words_per_segment, words_count)
                chunk_text = " ".join(words[chunk_start_idx:chunk_end_idx])

                time_start = segment.start + (chunk_start_idx / words_count) * total_duration
                time_end = segment.start + (chunk_end_idx / words_count) * total_duration

                srt_lines.append(str(segment_index))
                srt_lines.append(f"{format_timestamp(time_start)} --> {format_timestamp(time_end)}")
                srt_lines.append(chunk_text)
                srt_lines.append("")
                segment_index += 1
        else:
            srt_lines.append(str(segment_index))
            srt_lines.append(f"{format_timestamp(segment.start)} --> {format_timestamp(segment.end)}")
            srt_lines.append(text)
            srt_lines.append("")
            segment_index += 1

    return "\n".join(srt_lines)


def segments_to_vtt(segments) -> str:
    """將轉寫片段轉換為 WebVTT 字幕格式"""
    vtt_lines = ["WEBVTT", ""]
    for i, segment in enumerate(segments, start=1):
        text = segment.text.strip()
        if not text:
            continue
        vtt_lines.append(str(i))
        vtt_lines.append(f"{format_vtt_timestamp(segment.start)} --> {format_vtt_timestamp(segment.end)}")
        vtt_lines.append(text)
        vtt_lines.append("")
    return "\n".join(vtt_lines)


def segments_to_txt(segments) -> str:
    """將轉寫片段提取為純文字連續逐字稿"""
    return "\n".join(s.text.strip() for s in segments if s.text.strip())


def segments_to_json(segments, language: str = "", duration: float = 0.0) -> str:
    """將轉寫片段封裝為包含時間戳的結構化 JSON"""
    seg_list = []
    for s in segments:
        text = s.text.strip()
        if not text:
            continue
        seg_list.append({
            "start": round(s.start, 3),
            "end": round(s.end, 3),
            "text": text,
        })
    data = {
        "language": language,
        "duration": round(duration, 3),
        "segments": seg_list
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


# ==============================================================================
# 檔案與參數驗證 (Single Responsibility: Validation)
# ==============================================================================

def validate_input_file(input_path: Path) -> bool:
    """驗證輸入檔案是否存在且為受支援的影音格式"""
    if not input_path.exists():
        raise FileNotFoundError(f"找不到指定的輸入檔案：{input_path}")
    if not input_path.is_file():
        raise ValueError(f"指定路徑非檔案：{input_path}")
    if input_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"不支援的媒體檔案格式：'{input_path.suffix}'。"
            f"支援的格式包含：{', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )
    return True


def resolve_language_and_prompt(language: Optional[str] = None, initial_prompt: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """
    解析語言代碼與初始提示詞：
    若指定 zh-TW 或台語相關，正規化為 zh 並自動注入台灣繁中與台語專用語引導 Prompt。
    """
    lang = language
    prompt = initial_prompt

    if language:
        lang_lower = language.lower()
        if lang_lower in ["zh-tw", "zh_tw", "taigi", "taiwan", "nan"]:
            lang = "zh"
            if not prompt:
                prompt = DEFAULT_ZH_TW_PROMPT
            elif "繁體中文" not in prompt:
                prompt = f"{prompt}。{DEFAULT_ZH_TW_PROMPT}"

    return lang, prompt


def resolve_model_name(model_name: Optional[str] = None, language: Optional[str] = None) -> str:
    """
    解析 Whisper 模型名稱或別名：
    - 若傳入 breeze-asr / breeze-asr-26 / breeze / taigi，解析為 MediaTek Breeze-ASR-26 CTranslate2 倉庫路徑。
    - 若未指定模型名稱 (None 或空) 且未指定語言，或指定語言為繁中/台語 (zh-TW, taigi 等)，預設自動採用 Breeze-ASR。
    - 若指定其它標準模型 (如 large-v3, medium 等)，透過 MODEL_ALIASES 解析。
    - 若為自訂路徑或非別名之 Hugging Face 倉庫，則維持原樣回傳。
    """
    target = (model_name or "").strip()

    # 未指定模型時之智慧預設策略
    if not target:
        return BREEZE_ASR_CT2_REPO

    target_lower = target.lower()
    if target_lower in MODEL_ALIASES:
        return MODEL_ALIASES[target_lower]

    return target


# ==============================================================================
# 硬體偵測與推論執行器 (Transcribe Engine)
# ==============================================================================

class TranscribeEngine:
    """Faster-Whisper 轉錄推論引擎封裝"""

    def __init__(self, model_name: str = "medium", device: str = "auto", compute_type: str = "auto"):
        self.model_name = model_name
        self.device, self.compute_type = self._resolve_hardware(device, compute_type)
        self.model = None

    @staticmethod
    def _resolve_hardware(requested_device: str, requested_compute: str) -> Tuple[str, str]:
        """自動偵測環境並決定最適硬體配置"""
        device = requested_device
        compute = requested_compute

        if device == "auto":
            try:
                import torch
                if torch.cuda.is_available():
                    device = "cuda"
                    compute = "float16" if compute == "auto" else compute
                else:
                    device = "cpu"
                    compute = "int8" if compute == "auto" else compute
            except ImportError:
                device = "cpu"
                compute = "int8" if compute == "auto" else compute
        else:
            if compute == "auto":
                compute = "float16" if device == "cuda" else "int8"

        return device, compute

    def load_model(self):
        """延遲載入 Faster-Whisper 模型"""
        if self.model is None:
            from faster_whisper import WhisperModel
            print(f"[*] 載入 Whisper 模型: {self.model_name} (裝置: {self.device}, 精度: {self.compute_type})...")
            try:
                self.model = WhisperModel(self.model_name, device=self.device, compute_type=self.compute_type)
            except Exception as e:
                if self.device == "cuda":
                    print(f"[!] GPU 載入失敗 ({e})，自動降級為 CPU (int8) 模式...")
                    self.device = "cpu"
                    self.compute_type = "int8"
                    self.model = WhisperModel(self.model_name, device=self.device, compute_type=self.compute_type)
                else:
                    raise e


# ==============================================================================
# CLI 命令列入口點
# ==============================================================================

def main():
    """主程式進入點"""
    # Windows 繁體中文控制台編碼保護 (防範 cp950 UnicodeEncodeError)
    if sys.platform == "win32":
        import io
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        description="旗艦版影音轉逐字稿工具 (支援多模型、繁體中文與台灣台語特化)"
    )
    parser.add_argument("audio", nargs="*", help="一個或多個輸入影音檔案路徑")
    parser.add_argument("--model", "-m", default="breeze-asr", help="Whisper 模型名稱 (breeze-asr, large-v3, medium, small, base, tiny)")
    parser.add_argument("--language", "-l", default="zh-TW", help="指定語言 (預設 zh-TW，亦支援 zh, en, ja, taigi 等)")
    parser.add_argument("--format", "-f", default="srt", help="輸出格式，以逗號分隔 (srt, vtt, txt, json)")
    parser.add_argument("--output", "-o", default=None, help="指定單一輸出檔案路徑")
    parser.add_argument("--input-dir", "-d", default=None, help="批次處理指定目錄下的所有影音檔")
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"], help="運算裝置")
    parser.add_argument("--compute-type", default="auto", help="計算精度 (auto, float16, int8, float32)")
    parser.add_argument("--vad-filter", action="store_true", help="啟用 VAD 語音活動偵測 (過濾靜音與雜音)")
    parser.add_argument("--initial-prompt", default=None, help="初始提示詞 (引導繁中、台語或專有名詞)")
    parser.add_argument("--beam-size", type=int, default=5, help="Beam search 搜尋寬度")
    parser.add_argument("--max-words", type=int, default=None, help="單一字幕片段最大字數上限")

    args = parser.parse_args()

    # 彙整待處理檔案清單
    files_to_process: List[Path] = []
    if args.input_dir:
        in_dir = Path(args.input_dir)
        if not in_dir.is_dir():
            print(f"[錯誤] 找不到指定目錄：{in_dir}")
            sys.exit(1)
        for ext in SUPPORTED_EXTENSIONS:
            files_to_process.extend(in_dir.glob(f"*{ext}"))
            files_to_process.extend(in_dir.glob(f"*{ext.upper()}"))
    elif args.audio:
        for f in args.audio:
            files_to_process.append(Path(f))
    else:
        parser.print_help()
        sys.exit(0)

    if not files_to_process:
        print("[提示] 未找到符合條件的影音檔案。")
        sys.exit(0)

    # 預檢檔案合法性與存在性 (Fail-Fast 防呆)
    valid_files: List[Path] = []
    for file_path in files_to_process:
        try:
            validate_input_file(file_path)
            valid_files.append(file_path)
        except Exception as e:
            print(f"[跳過] {file_path}：{e}")

    if not valid_files:
        print("[錯誤] 無任何合法且存在的影音檔案可供轉錄。")
        sys.exit(1)

    # 語言與 Prompt 正規化
    lang, prompt = resolve_language_and_prompt(args.language, args.initial_prompt)

    # 解析模型名稱 (自動對應 Breeze-ASR-26 CTranslate2 權重與別名)
    actual_model = resolve_model_name(args.model, args.language)

    # 初始化推論引擎
    engine = TranscribeEngine(
        model_name=actual_model,
        device=args.device,
        compute_type=args.compute_type
    )
    engine.load_model()

    requested_formats = [fmt.strip().lower() for fmt in args.format.split(",") if fmt.strip()]

    # 逐一處理合法檔案
    for file_path in valid_files:
        print(f"\n[*] 開始轉寫：{file_path}")
        try:
            segments_gen, info = engine.model.transcribe(
                str(file_path),
                language=lang,
                initial_prompt=prompt,
                beam_size=args.beam_size,
                vad_filter=args.vad_filter,
            )
            # 轉換為列表以供重複格式化
            segments = list(segments_gen)
            print(f"[✓] 轉錄推論完成，偵測語言: {info.language} (機率: {info.language_probability:.2f})，總時長: {info.duration:.1f} 秒")

            # 依要求格式匯出
            for fmt in requested_formats:
                if args.output and len(files_to_process) == 1:
                    out_path = Path(args.output).with_suffix(f".{fmt}")
                else:
                    out_path = file_path.with_suffix(f".{fmt}")

                if fmt == "srt":
                    content = segments_to_srt(segments, max_words_per_segment=args.max_words)
                elif fmt == "vtt":
                    content = segments_to_vtt(segments)
                elif fmt == "txt":
                    content = segments_to_txt(segments)
                elif fmt == "json":
                    content = segments_to_json(segments, language=info.language, duration=info.duration)
                else:
                    print(f"[警告] 不支援的輸出格式: {fmt}，跳過。")
                    continue

                with open(out_path, "w", encoding="utf-8") as out_f:
                    out_f.write(content)
                print(f"    -> 成功產出 [{fmt.upper()}]: {out_path.resolve()}")

        except Exception as e:
            print(f"[錯誤] 處理 {file_path} 時發生異常：{e}")


if __name__ == "__main__":
    main()
