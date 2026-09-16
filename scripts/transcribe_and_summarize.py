#!/usr/bin/env python3
"""獨立命令列腳本：音訊轉錄、語意錯別字校正與結構化會議紀錄整理。

執行方式範例：
1. 傳入音訊檔案進行完整轉寫與會議記錄生成：
   uv run python scripts/transcribe_and_summarize.py --audio "meeting.mp3"

2. 傳入現有逐字稿直接進行錯別字校正與會議記錄生成：
   uv run python scripts/transcribe_and_summarize.py --transcript "transcript.txt"

3. 自訂模型與 API 端點：
   uv run python scripts/transcribe_and_summarize.py --transcript "raw.txt" --url "http://192.168.1.100:8002/v1" --model "auto"
"""

from __future__ import annotations

import argparse
import configparser
import datetime
import logging
import os
from pathlib import Path
import shutil
import sys
import time
from typing import Optional

# 將專案根目錄與 src 加入 sys.path 確保模組可用
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# 確保 Windows 控制台輸出支援 UTF-8
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from taigi_asr.llm import LLMClient
from taigi_asr.minutes import (
    extract_meeting_title,
    save_meeting_outputs,
    validate_meeting_minutes_sections,
)

logger = logging.getLogger("transcribe_and_summarize")


def load_config_defaults() -> dict:
    """載入 .env 與 config.ini 中的設定預設值。

    Returns:
        包含設定參數鍵值的字典。
    """
    defaults = {
        "url": "http://192.168.1.100:8002/v1",
        "model": "auto",
        "timeout": 1800,
        "km_wiki_enabled": False,
        "km_wiki_raw_dir": "D:/km_wiki/raw",
    }

    # 1. 讀取 config.ini
    config_file = REPO_ROOT / "config.ini"
    if config_file.exists():
        try:
            parser = configparser.ConfigParser()
            parser.read(config_file, encoding="utf-8")
            if "Correction" in parser and "correction_url" in parser["Correction"]:
                defaults["url"] = parser["Correction"]["correction_url"]
            elif "LLM" in parser and "llm_url" in parser["LLM"]:
                defaults["url"] = parser["LLM"]["llm_url"]

            if "Correction" in parser and "correction_model" in parser["Correction"]:
                defaults["model"] = parser["Correction"]["correction_model"]
            elif "LLM" in parser and "llm_model" in parser["LLM"]:
                defaults["model"] = parser["LLM"]["llm_model"]

            if "KMWiki" in parser:
                defaults["km_wiki_enabled"] = parser.getboolean("KMWiki", "enabled", fallback=False)
                defaults["km_wiki_raw_dir"] = parser.get("KMWiki", "raw_dir", fallback="D:/km_wiki/raw")
        except Exception as exc:
            logger.warning(f"讀取 config.ini 失敗: {exc}")

    # 2. 讀取環境變數 (優先於 config.ini)
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key in ("LLM_CORRECTION_URL", "LLM_URL"):
                        defaults["url"] = val
                    elif key in ("LLM_CORRECTION_MODEL", "LLM_MODEL"):
                        defaults["model"] = val
                    elif key == "KM_WIKI_ENABLED":
                        defaults["km_wiki_enabled"] = val.lower() in ("true", "1", "yes")
                    elif key == "KM_WIKI_RAW_DIR":
                        defaults["km_wiki_raw_dir"] = val
        except Exception as exc:
            logger.warning(f"讀取 .env 失敗: {exc}")

    # 亦檢查目前進程之環境變數
    defaults["url"] = os.environ.get("LLM_CORRECTION_URL", os.environ.get("LLM_URL", defaults["url"]))
    defaults["model"] = os.environ.get("LLM_CORRECTION_MODEL", os.environ.get("LLM_MODEL", defaults["model"]))

    return defaults


def build_parser() -> argparse.ArgumentParser:
    """建立命令列引數解析器。"""
    defaults = load_config_defaults()

    parser = argparse.ArgumentParser(
        prog="transcribe_and_summarize",
        description="台灣台語語音轉錄、語意錯別字校正與結構化會議紀錄整理腳本。",
    )
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument(
        "--audio",
        "-a",
        type=Path,
        default=None,
        help="輸入音訊檔案路徑 (支援 .mp3, .wav, .m4a, .flac 等)",
    )
    group.add_argument(
        "--transcript",
        "-t",
        type=Path,
        default=None,
        help="輸入已有之逐字稿文字檔路徑 (跳過 ASR 直接進行校正與會議紀錄生成)",
    )

    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=None,
        help="輸出儲存目錄 (預設為 output/YYYY-MM-DD/)",
    )
    parser.add_argument(
        "--url",
        type=str,
        default=defaults["url"],
        help=f"LLM API 端點 (預設: {defaults['url']})",
    )
    parser.add_argument(
        "--model",
        "-m",
        type=str,
        default=defaults["model"],
        help="LLM 模型名稱 (預設: auto，會自動向 /v1/models 查詢目前可用模型)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=defaults["timeout"],
        help=f"LLM 呼叫逾時秒數 (預設: {defaults['timeout']} 秒)",
    )
    parser.add_argument(
        "--skip-correction",
        action="store_true",
        help="略過錯別字校正步驟，直接從原始逐字稿生成會議紀錄",
    )
    parser.add_argument(
        "--meeting-name",
        type=str,
        default=None,
        help="手動指定會議主題名稱 (若無則自動自摘要提取)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="啟用詳細偵錯日誌輸出",
    )

    return parser


def run_asr_transcribe(audio_path: Path) -> str:
    """調用 Breeze-ASR-26 進行音訊轉寫與講者辨識。

    Args:
        audio_path: 音訊檔案本機路徑。

    Returns:
        帶講者與時間戳記之原始逐字稿文字。
    """
    logger.info(f"[階段 1/4] 開始語音轉寫 (音檔: {audio_path})...")
    print(f"🎙️  [1/4] 正在進行語音轉錄 (檔案: {audio_path.name})...")

    # 嘗試優先使用 backend 的 MeetingTranscriber (包含 Pyannote 講者分離)
    try:
        backend_dir = REPO_ROOT / "backend"
        if str(backend_dir) not in sys.path:
            sys.path.insert(0, str(backend_dir))
        from src.infrastructure.ml_models import MeetingTranscriber
        transcriber = MeetingTranscriber.get_instance()
        return transcriber.process_audio(str(audio_path))
    except Exception as exc:
        logger.warning(f"無法載入 MeetingTranscriber ({exc})，嘗試以 FasterWhisperEngine 轉錄...")

    # Fallback: 使用 taigi_asr.engines.build_engine
    from taigi_asr.audio import AudioConverter
    from taigi_asr.engines import build_engine
    from taigi_asr.formatters import to_txt
    from taigi_asr.router import EngineKind

    wav_path, duration = AudioConverter.convert(audio_path)
    try:
        engine = build_engine(EngineKind.FASTER_WHISPER)
        segments = engine.transcribe(wav_path)
        return to_txt(segments)
    finally:
        AudioConverter.cleanup(wav_path)


def run_pipeline(
    audio_path: Optional[Path],
    transcript_path: Optional[Path],
    output_dir: Optional[Path] = None,
    llm_url: str = "http://192.168.1.100:8002/v1",
    model: str = "auto",
    timeout: int = 1800,
    skip_correction: bool = False,
    meeting_name: Optional[str] = None,
    km_wiki_enabled: bool = False,
    km_wiki_raw_dir: str = "D:/km_wiki/raw",
) -> int:
    """執行會議紀錄生成流程。

    Args:
        audio_path: 音訊路徑（與 transcript_path 二擇一）。
        transcript_path: 逐字稿路徑。
        output_dir: 輸出檔案夾。
        llm_url: 模型 API 端點。
        model: 模型名稱（auto 則透過 /v1/models 查詢）。
        timeout: 逾時時間（秒）。
        skip_correction: 是否跳過校正。
        meeting_name: 指定會議名稱。
        km_wiki_enabled: 是否啟用 KM Wiki 同步。
        km_wiki_raw_dir: KM Wiki raw 目錄路徑。

    Returns:
        執行結果狀態碼 (0 代表成功)。
    """
    t_start = time.monotonic()

    # 1. 驗證輸入檔案
    if audio_path is None and transcript_path is None:
        print("❌ 錯誤：必須提供 --audio 或 --transcript 其中一項參數！")
        return 1

    target_file = audio_path or transcript_path
    if not target_file.exists():
        print(f"❌ 錯誤：找不到指定的輸入檔案: {target_file}")
        return 2

    # 設定預設輸出目錄 (output/YYYY-MM-DD)
    if output_dir is None:
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        output_dir = REPO_ROOT / "output" / today_str
    output_dir = Path(output_dir)

    # 2. 取得原始逐字稿
    raw_transcript: str = ""
    fallback_title = target_file.stem
    if audio_path is not None:
        try:
            raw_transcript = run_asr_transcribe(audio_path)
        except Exception as exc:
            print(f"[錯誤] ASR 轉錄失敗: {exc}")
            return 3
    else:
        print(f"[1/4] 讀取現有逐字稿檔案: {transcript_path.name}...")
        try:
            raw_transcript = transcript_path.read_text(encoding="utf-8")
        except Exception as exc:
            print(f"[錯誤] 讀取逐字稿失敗: {exc}")
            return 4

    if not raw_transcript.strip():
        print("[警告] 逐字稿內容為空，無法進行後續處理。")
        return 5

    # 3. 初始化 LLMClient 並自動偵測模型
    print(f"[2/4] 連線至 LLM 服務 ({llm_url})...")
    client = LLMClient(base_url=llm_url, model=model, timeout=timeout)
    active_model = client.get_available_model()
    print(f"[*] 啟用推論模型: {active_model}")

    # 4. 階段一：語意錯別字校正
    corrected_transcript = raw_transcript
    if not skip_correction:
        print("[3/4] 正在進行前後文語意錯別字校正 (LLM 8002/v1)...")
        corrected_transcript = client.correct_transcript(raw_transcript)
        print("   -> 語意校正完成。")
    else:
        print("[*] 跳過錯別字校正步驟，直接使用原始逐字稿。")

    # 5. 階段二：四大區塊會議記錄生成
    print("[4/4] 正在整理四大區塊結構化會議紀錄 (重點、決策、TODO、下次追蹤)...")
    minutes_summary = client.generate_meeting_minutes(corrected_transcript)
    validation = validate_meeting_minutes_sections(minutes_summary)
    if not validation["is_valid"]:
        logger.warning(f"會議記錄區塊完整性檢查未完全符合標準: {validation}")

    # 6. 存檔與輸出
    t_file, s_file = save_meeting_outputs(
        transcript=corrected_transcript,
        summary=minutes_summary,
        output_dir=output_dir,
        meeting_name=meeting_name,
        fallback_name=fallback_title,
    )

    print("\n" + "=" * 60)
    print("[完成] 會議紀錄轉換完成！")
    print(f"[*] 逐字稿存檔:     {t_file.resolve()}")
    print(f"[*] 會議紀錄存檔:   {s_file.resolve()}")

    # 7. 可選：KM Wiki 自動同步
    if km_wiki_enabled:
        km_dir = Path(km_wiki_raw_dir)
        try:
            today_str = datetime.datetime.now().strftime("%Y-%m-%d")
            km_target_dir = km_dir / today_str
            km_target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(t_file, km_target_dir / t_file.name)
            shutil.copy2(s_file, km_target_dir / s_file.name)
            print(f"[*] 已同步複製至 KM Wiki raw 目錄: {km_target_dir.resolve()}")
        except Exception as exc:
            print(f"[警告] KM Wiki 同步失敗 (不影響本機存檔): {exc}")

    elapsed = time.monotonic() - t_start
    print(f"[*] 總耗時: {elapsed:.2f} 秒")
    print("=" * 60 + "\n")

    return 0


def main(argv: Optional[list[str]] = None) -> int:
    """CLI 進入點函式。"""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    else:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if args.audio is None and args.transcript is None:
        parser.print_help()
        print("\n❌ 錯誤：請提供 --audio 或 --transcript 引數！")
        return 1

    defaults = load_config_defaults()
    return run_pipeline(
        audio_path=args.audio,
        transcript_path=args.transcript,
        output_dir=args.output_dir,
        llm_url=args.url,
        model=args.model,
        timeout=args.timeout,
        skip_correction=args.skip_correction,
        meeting_name=args.meeting_name,
        km_wiki_enabled=defaults["km_wiki_enabled"],
        km_wiki_raw_dir=defaults["km_wiki_raw_dir"],
    )


if __name__ == "__main__":
    sys.exit(main())
