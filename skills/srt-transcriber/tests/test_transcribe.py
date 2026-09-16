import json
import sys
from pathlib import Path
from dataclasses import dataclass

# 將 scripts 加入模組搜尋路徑
script_dir = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(script_dir))

from transcribe import (
    format_timestamp,
    format_vtt_timestamp,
    segments_to_srt,
    segments_to_vtt,
    segments_to_txt,
    segments_to_json,
    validate_input_file,
    resolve_language_and_prompt,
    resolve_model_name,
    SUPPORTED_EXTENSIONS,
    MODEL_ALIASES,
)


@dataclass
class MockSegment:
    """模擬 faster-whisper 的片段物件"""
    start: float
    end: float
    text: str


def test_timestamp_formatting_srt_and_vtt():
    """驗證 SRT 與 VTT 時間戳轉換精度"""
    sec = 3723.456  # 1 小時 2 分 3 秒 456 毫秒
    srt_ts = format_timestamp(sec)
    assert srt_ts == "01:02:03,456"

    vtt_ts = format_vtt_timestamp(sec)
    assert vtt_ts == "01:02:03.456"

    # 零秒驗證
    assert format_timestamp(0.0) == "00:00:00,000"
    assert format_vtt_timestamp(0.0) == "00:00:00.000"


def test_segments_to_srt_and_word_splitting():
    """驗證片段轉 SRT 字幕以及超長字數自動分段機制"""
    segments = [
        MockSegment(start=1.0, end=3.5, text="各位同仁好，今天討論導流板試產良率。"),
        MockSegment(start=4.0, end=6.2, text="目前公差已收斂至一條以內。"),
    ]

    srt_content = segments_to_srt(segments)
    lines = srt_content.strip().split("\n")

    # 第一段
    assert lines[0] == "1"
    assert lines[1] == "00:00:01,000 --> 00:00:03,500"
    assert lines[2] == "各位同仁好，今天討論導流板試產良率。"

    # 第二段
    assert lines[4] == "2"
    assert lines[5] == "00:00:04,000 --> 00:00:06,200"
    assert lines[6] == "目前公差已收斂至一條以內。"

    # 測試超長字數自動分段
    long_segment = [
        MockSegment(start=0.0, end=10.0, text="word1 word2 word3 word4 word5 word6 word7 word8 word9 word10")
    ]
    split_srt = segments_to_srt(long_segment, max_words_per_segment=5)
    split_lines = split_srt.strip().split("\n")
    # 應切成兩段字幕
    assert "1" in split_lines[0]
    assert "2" in split_lines[4]


def test_segments_to_vtt_and_txt_and_json():
    """驗證 VTT、TXT 與 JSON 多格式輸出完整性"""
    segments = [
        MockSegment(start=0.5, end=2.0, text="測試第一句"),
        MockSegment(start=2.5, end=4.0, text="測試第二句"),
    ]

    # 1. VTT 格式
    vtt = segments_to_vtt(segments)
    assert vtt.startswith("WEBVTT")
    assert "00:00:00.500 --> 00:00:02.000" in vtt

    # 2. TXT 純文字格式
    txt = segments_to_txt(segments)
    assert "測試第一句\n測試第二句" == txt.strip()

    # 3. JSON 格式
    json_str = segments_to_json(segments, language="zh", duration=4.0)
    data = json.loads(json_str)
    assert data["language"] == "zh"
    assert len(data["segments"]) == 2
    assert data["segments"][0]["text"] == "測試第一句"
    assert data["segments"][0]["start"] == 0.5


def test_audio_validator_paths_and_extensions(tmp_path):
    """驗證檔案格式檢查與防呆機制"""
    assert ".mp4" in SUPPORTED_EXTENSIONS
    assert ".wav" in SUPPORTED_EXTENSIONS
    assert ".mp3" in SUPPORTED_EXTENSIONS

    # 建立合法臨時影片檔
    valid_file = tmp_path / "sample.mp4"
    valid_file.write_text("dummy video content")
    assert validate_input_file(valid_file) is True

    # 測試不支援的副檔名
    invalid_file = tmp_path / "document.pdf"
    invalid_file.write_text("pdf")
    try:
        validate_input_file(invalid_file)
        assert False, "不支援副檔名應拋出 ValueError"
    except ValueError as e:
        assert "不支援的媒體檔案格式" in str(e)

    # 測試檔案不存在
    non_exist = tmp_path / "not_found.mp4"
    try:
        validate_input_file(non_exist)
        assert False, "不存在檔案應拋出 FileNotFoundError"
    except FileNotFoundError:
        pass


def test_prompt_and_language_normalization():
    """驗證 zh-TW 正規化與繁中/台語專用初始提示詞注入"""
    # 當傳入 zh-TW 或台語指定時
    lang, prompt = resolve_language_and_prompt(language="zh-TW", initial_prompt=None)
    assert lang == "zh"
    assert "繁體中文" in prompt
    assert "台語" in prompt

    # 當指定 taigi 語言時亦應正規化為 zh
    lang_tg, prompt_tg = resolve_language_and_prompt(language="taigi", initial_prompt=None)
    assert lang_tg == "zh"
    assert "台語" in prompt_tg

    # 當使用者自訂提示詞時，保留自訂內容並包含繁體中文引導
    custom_lang, custom_prompt = resolve_language_and_prompt(language="zh", initial_prompt="這是自訂提示詞")
    assert "自訂提示詞" in custom_prompt


def test_breeze_asr_model_resolution():
    """驗證 MediaTek Breeze-ASR-26 模型別名解析與預設規則"""
    breeze_hf_repo = "paulpengtw/faster-whisper-Breeze-ASR-26-ct2"

    # 1. 顯式指定 breeze 各種別名
    assert resolve_model_name("breeze-asr") == breeze_hf_repo
    assert resolve_model_name("breeze-asr-26") == breeze_hf_repo
    assert resolve_model_name("breeze") == breeze_hf_repo
    assert resolve_model_name("taigi") == breeze_hf_repo

    # 2. 預設模型 (None 或預設值) + zh-TW 語言自動首選 Breeze-ASR
    assert resolve_model_name(None, language="zh-TW") == breeze_hf_repo
    assert resolve_model_name("breeze-asr", language="zh-TW") == breeze_hf_repo

    # 3. 指定通用 OpenAI 官方模型
    assert resolve_model_name("large-v3") == "large-v3"
    assert resolve_model_name("medium") == "medium"
    assert resolve_model_name("small") == "small"

    # 4. 指定自訂 Hugging Face 倉庫或本地路徑
    custom_path = "custom-user/special-whisper"
    assert resolve_model_name(custom_path) == custom_path
