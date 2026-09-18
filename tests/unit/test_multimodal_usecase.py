"""後端轉錄 Use Case 多模態管線單元測試模組。

驗證：
1. 影片輸入時自動觸發關鍵幀抽取、VLM 分析與看完即忘清理
2. 純音訊輸入時平滑相容（不觸發視覺管線）
3. VLM 失敗或逾時時之平滑降級（任務依舊完成且暫存幀妥善清理）
"""

import os
import sys
from unittest.mock import MagicMock, patch
import pytest

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from src.infrastructure.database import Base, SessionLocal, TaskModel, engine
from src.usecases.transcription import process_audio_task, get_vlm_client

Base.metadata.create_all(bind=engine)


@pytest.fixture
def clean_db():
    """提供乾淨的測試任務資料庫環境。"""
    task_ids = []

    def _create_task(task_id: str, file_path: str):
        db = SessionLocal()
        db.query(TaskModel).filter(TaskModel.id == task_id).delete()
        db.commit()
        task = TaskModel(id=task_id, file_path=file_path, status="pending")
        db.add(task)
        db.commit()
        db.close()
        task_ids.append(task_id)
        return task_id

    yield _create_task

    db = SessionLocal()
    for tid in task_ids:
        db.query(TaskModel).filter(TaskModel.id == tid).delete()
    db.commit()
    db.close()


class TestMultimodalUseCase:
    """測試音視雙模態多工後端管線。"""

    @patch("src.usecases.transcription.save_output_md_files")
    @patch("src.infrastructure.ml_models.MeetingTranscriber.get_instance")
    def test_process_video_triggers_vlm_and_cleanup(self, mock_transcriber_factory, mock_save_md, clean_db):
        """驗證當上傳影片時，自動觸發關鍵幀擷取、VLM 分析與及時清理。"""
        mock_save_md.return_value = True
        task_id = "test-multimodal-video-task"
        video_filename = "presentation.mp4"
        clean_db(task_id, video_filename)

        # Mock ASR
        mock_transcriber = MagicMock()
        mock_transcriber.process_audio.return_value = "[00:00:10] 主持人: 請看投影片第一頁。"
        mock_transcriber_factory.return_value = mock_transcriber

        # Mock Extractor & VLM
        mock_keyframes = [
            {"path": "temp_frame_01.jpg", "timestamp": "00:00:10", "time_sec": 10.0}
        ]
        mock_timeline = "### 會議簡報與視覺畫面時間軸紀錄\n- [00:00:10] 投影片：年度策略規劃"

        with patch("src.usecases.transcription.KeyframeExtractor") as MockExtractorCls, \
             patch("src.usecases.transcription.get_vlm_client") as mock_get_vlm, \
             patch("src.usecases.transcription.get_minutes_llm_client") as mock_get_minutes_llm, \
             patch("src.usecases.transcription.get_correction_llm_client") as mock_get_corr_llm:

            mock_extractor = MockExtractorCls.return_value
            mock_extractor.is_video_file.return_value = True
            mock_extractor.extract_keyframes.return_value = mock_keyframes

            mock_vlm = MagicMock()
            mock_vlm.analyze_keyframes.return_value = mock_timeline
            mock_get_vlm.return_value = mock_vlm

            mock_llm = MagicMock()
            mock_llm.correct_transcript.return_value = "[00:00:10] 主持人: 請看投影片第一頁。"
            mock_llm.generate_meeting_minutes.return_value = (
                "# 會議名稱：年度策略規劃會議\n\n"
                "## 【會議重點】\n- 討論年度策略規劃。\n\n"
                "## 【關鍵決策】\n- 確立目標。\n\n"
                "## 【TODO / 行動項目】\n- 行動 1\n\n"
                "## 【下次會議追蹤項目】\n- 追蹤 1"
            )
            mock_get_minutes_llm.return_value = mock_llm
            mock_get_corr_llm.return_value = mock_llm

            # 執行任務
            process_audio_task(task_id, video_filename)

            # 驗證抽取被呼叫
            mock_extractor.extract_keyframes.assert_called_once_with(video_filename)
            # 驗證 VLM 分析被呼叫
            mock_vlm.analyze_keyframes.assert_called_once_with(mock_keyframes)
            # 驗證 看完即忘及時清理
            mock_extractor.cleanup_keyframes.assert_called_once_with(mock_keyframes)
            # 驗證 LLM 會議記錄生成接收到了視覺上下文
            mock_llm.generate_meeting_minutes.assert_called_once_with(
                mock_llm.correct_transcript.return_value,
                visual_context=mock_timeline,
            )

            # 驗證 DB 狀態完成
            db = SessionLocal()
            task = db.query(TaskModel).filter(TaskModel.id == task_id).first()
            assert task.status == "completed"
            assert task.transcript is not None
            assert "年度策略規劃會議" in task.summary
            db.close()

    @patch("src.usecases.transcription.save_output_md_files")
    @patch("src.infrastructure.ml_models.MeetingTranscriber.get_instance")
    def test_process_audio_only_bypasses_vlm(self, mock_transcriber_factory, mock_save_md, clean_db):
        """驗證當上傳純音訊時，平滑跳過視覺關鍵幀抽取與 VLM 分析。"""
        mock_save_md.return_value = True
        task_id = "test-audio-only-task"
        audio_filename = "recording.wav"
        clean_db(task_id, audio_filename)

        mock_transcriber = MagicMock()
        mock_transcriber.process_audio.return_value = "[00:00:05] 講者: 純音訊測試。"
        mock_transcriber_factory.return_value = mock_transcriber

        with patch("src.usecases.transcription.KeyframeExtractor") as MockExtractorCls, \
             patch("src.usecases.transcription.get_vlm_client") as mock_get_vlm, \
             patch("src.usecases.transcription.get_minutes_llm_client") as mock_get_minutes_llm, \
             patch("src.usecases.transcription.get_correction_llm_client") as mock_get_corr_llm:

            mock_extractor = MockExtractorCls.return_value
            mock_extractor.is_video_file.return_value = False

            mock_llm = MagicMock()
            mock_llm.correct_transcript.return_value = "[00:00:05] 講者: 純音訊測試。"
            mock_llm.generate_meeting_minutes.return_value = (
                "# 會議名稱：純音訊測試會議\n\n"
                "## 【會議重點】\n- 重點\n\n"
                "## 【關鍵決策】\n- 決策\n\n"
                "## 【TODO / 行動項目】\n- 行動\n\n"
                "## 【下次會議追蹤項目】\n- 追蹤"
            )
            mock_get_minutes_llm.return_value = mock_llm
            mock_get_corr_llm.return_value = mock_llm

            process_audio_task(task_id, audio_filename)

            # 驗證未呼叫抽取
            mock_extractor.extract_keyframes.assert_not_called()
            mock_get_vlm.assert_not_called()
            # 視覺上下文為 None
            mock_llm.generate_meeting_minutes.assert_called_once_with(
                mock_llm.correct_transcript.return_value,
                visual_context=None,
            )

            db = SessionLocal()
            task = db.query(TaskModel).filter(TaskModel.id == task_id).first()
            assert task.status == "completed"
            db.close()

    @patch("src.usecases.transcription.save_output_md_files")
    @patch("src.infrastructure.ml_models.MeetingTranscriber.get_instance")
    def test_vlm_failure_gracefully_degrades(self, mock_transcriber_factory, mock_save_md, clean_db):
        """驗證當 VLM 拋出異常時，管線優雅降級為純語音摘要，任務狀態正常完成且暫存幀妥善清理。"""
        mock_save_md.return_value = True
        task_id = "test-vlm-degradation-task"
        video_filename = "bad_vlm.mp4"
        clean_db(task_id, video_filename)

        mock_transcriber = MagicMock()
        mock_transcriber.process_audio.return_value = "[00:00:05] 講者: 降級容錯測試。"
        mock_transcriber_factory.return_value = mock_transcriber

        mock_keyframes = [
            {"path": "temp_frame_bad.jpg", "timestamp": "00:00:05", "time_sec": 5.0}
        ]

        with patch("src.usecases.transcription.KeyframeExtractor") as MockExtractorCls, \
             patch("src.usecases.transcription.get_vlm_client") as mock_get_vlm, \
             patch("src.usecases.transcription.get_minutes_llm_client") as mock_get_minutes_llm, \
             patch("src.usecases.transcription.get_correction_llm_client") as mock_get_corr_llm:

            mock_extractor = MockExtractorCls.return_value
            mock_extractor.is_video_file.return_value = True
            mock_extractor.extract_keyframes.return_value = mock_keyframes

            # 模擬 VLM 拋出連線失敗
            mock_vlm = MagicMock()
            mock_vlm.analyze_keyframes.side_effect = RuntimeError("VLM Endpoint unreachable")
            mock_get_vlm.return_value = mock_vlm

            mock_llm = MagicMock()
            mock_llm.correct_transcript.return_value = "[00:00:05] 講者: 降級容錯測試。"
            mock_llm.generate_meeting_minutes.return_value = (
                "# 會議名稱：降級容錯測試\n\n"
                "## 【會議重點】\n- 重點\n\n"
                "## 【關鍵決策】\n- 決策\n\n"
                "## 【TODO / 行動項目】\n- 行動\n\n"
                "## 【下次會議追蹤項目】\n- 追蹤"
            )
            mock_get_minutes_llm.return_value = mock_llm
            mock_get_corr_llm.return_value = mock_llm

            process_audio_task(task_id, video_filename)

            # 驗證即使 VLM 失敗，暫存幀依然被清理
            mock_extractor.cleanup_keyframes.assert_called_once_with(mock_keyframes)
            # 驗證視覺上下文降級為 None
            mock_llm.generate_meeting_minutes.assert_called_once_with(
                mock_llm.correct_transcript.return_value,
                visual_context=None,
            )

            # 任務依舊成功完成
            db = SessionLocal()
            task = db.query(TaskModel).filter(TaskModel.id == task_id).first()
            assert task.status == "completed"
            db.close()
