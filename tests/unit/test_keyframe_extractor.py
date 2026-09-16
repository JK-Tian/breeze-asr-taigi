"""視訊會議關鍵幀智慧擷取器單元測試模組。

遵循 TDD 原則，驗證：
1. 視訊關鍵幀提取與時間戳記解析
2. 關鍵幀上限與間隔篩選
3. 非視訊檔案平滑降級與空處理
4. 暫存截圖目錄之看完即忘安全清理
"""

import os
import shutil
import pytest
from unittest.mock import patch, MagicMock
from taigi_asr.vision.keyframe_extractor import Keyframe, KeyframeExtractor, is_video_file


class TestKeyframeExtractor:
    """測試關鍵幀擷取器的核心邏輯與邊界條件。"""

    def test_is_video_file(self):
        """驗證副檔名辨識：視訊檔案為 True，純音訊為 False。"""
        assert is_video_file("meeting.mp4") is True
        assert is_video_file("demo.mkv") is True
        assert is_video_file("record.mov") is True
        assert is_video_file("web.webm") is True
        assert is_video_file("clip.avi") is True
        assert is_video_file("audio.mp3") is False
        assert is_video_file("speech.wav") is False
        assert is_video_file("voice.m4a") is False
        assert is_video_file("") is False

    def test_extract_keyframes_non_video_returns_empty(self, tmp_path):
        """驗證傳入非視訊檔案時，安全回傳空清單，不拋出例外。"""
        audio_file = tmp_path / "test.mp3"
        audio_file.write_text("dummy")
        extractor = KeyframeExtractor()
        keyframes = extractor.extract_keyframes(str(audio_file), str(tmp_path / "frames"))
        assert keyframes == []

    def test_extract_keyframes_with_ffmpeg_mock(self, tmp_path):
        """模擬 FFmpeg 場景切換偵測並產出關鍵幀。"""
        video_file = tmp_path / "test.mp4"
        video_file.write_text("dummy_video")
        out_dir = tmp_path / "extracted_frames"

        extractor = KeyframeExtractor(max_keyframes=5, scene_threshold=0.3)

        # 模擬 subprocess.run 成功並建立模擬截圖檔案
        def mock_ffmpeg_run(cmd, *args, **kwargs):
            os.makedirs(out_dir, exist_ok=True)
            for i in range(3):
                frame_path = out_dir / f"frame_{i:03d}_00_{i*15:02d}.jpg"
                frame_path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=mock_ffmpeg_run):
            keyframes = extractor.extract_keyframes(str(video_file), str(out_dir))

        assert len(keyframes) == 3
        assert isinstance(keyframes[0], Keyframe)
        assert os.path.exists(keyframes[0].image_path)
        assert keyframes[0].timestamp_str.startswith("[00:")

    def test_cleanup_keyframes(self, tmp_path):
        """驗證看完即忘清理函式能安全刪除暫存目錄。"""
        out_dir = tmp_path / "temp_frames"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "frame_001.jpg").write_bytes(b"test")

        extractor = KeyframeExtractor()
        extractor.cleanup_keyframes(str(out_dir))
        assert not os.path.exists(out_dir)
