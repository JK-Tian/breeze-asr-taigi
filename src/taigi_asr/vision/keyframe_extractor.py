"""視訊會議關鍵幀智慧擷取器模組。

利用 FFmpeg 場景切換演算法 (Scene Change Detection) 與定時間隔取樣，
從視訊會議錄影檔 (.mp4, .mkv, .mov 等) 中自動萃取簡報投影片換頁與展示重點畫面，
並提供推論完畢後之「看完即忘」暫存安全清理機制。
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import re
import shutil
import subprocess
from typing import List

logger = logging.getLogger("keyframe_extractor")

# 支援處理之視訊副檔名清單
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".flv", ".wmv"}


def is_video_file(file_path: str) -> bool:
    """判斷指定路徑是否為支援的視訊會議錄影檔案。

    Args:
        file_path: 檔案路徑

    Returns:
        若為視訊檔案回傳 True，否則回傳 False
    """
    if not file_path:
        return False
    ext = os.path.splitext(file_path)[1].lower()
    return ext in VIDEO_EXTENSIONS


@dataclass
class Keyframe:
    """關鍵畫面資料物件。"""

    image_path: str
    timestamp_seconds: float
    timestamp_str: str


class KeyframeExtractor:
    """視訊會議關鍵幀抽取器。"""

    def __init__(
        self,
        scene_threshold: float = 0.3,
        min_interval_seconds: int = 15,
        max_keyframes: int = 30,
    ):
        """初始化關鍵幀抽取器。

        Args:
            scene_threshold: 簡報場景切換敏感度 (0.0 ~ 1.0)
            min_interval_seconds: 關鍵畫面最小間隔秒數，防止連續密集截圖
            max_keyframes: 單一會議最多擷取之關鍵幀上限
        """
        self.scene_threshold = scene_threshold
        self.min_interval_seconds = min_interval_seconds
        self.max_keyframes = max_keyframes

    def extract_keyframes(self, video_path: str, output_dir: str) -> List[Keyframe]:
        """從視訊檔案中智慧擷取投影片關鍵幀。

        若輸入非視訊檔案或檔案不存在，安全回傳空清單（平滑降級）。

        Args:
            video_path: 輸入視訊檔案路徑
            output_dir: 暫存關鍵幀輸出目錄

        Returns:
            Keyframe 物件清單
        """
        if not is_video_file(video_path) or not os.path.exists(video_path):
            return []

        os.makedirs(output_dir, exist_ok=True)

        try:
            # 1. 取得視訊總時長 (秒)
            duration_s = self._get_video_duration(video_path)
            logger.info(f"視訊總時長: {duration_s:.1f} 秒，開始擷取關鍵幀...")

            # 2. 透過 FFmpeg 場景切換偵測或定時間隔抽取畫面 (縮放至 1280x720 以節省 VLM 傳輸)
            # 命名規則: frame_%03d.jpg
            output_pattern = os.path.join(output_dir, "frame_%03d.jpg")
            
            # 使用 select 濾鏡同時考慮 scene 切換或每 30 秒強制取樣 1 幀
            ffmpeg_cmd = [
                "ffmpeg",
                "-y",
                "-i", video_path,
                "-vf", f"select='gt(scene,{self.scene_threshold})+isnan(prev_selected_t_ff)+gte(t-prev_selected_t_ff,{self.min_interval_seconds})',scale=1280:720:force_original_aspect_ratio=decrease",
                "-vsync", "vfr",
                "-q:v", "3",
                output_pattern,
            ]

            subprocess.run(
                ffmpeg_cmd,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            # 3. 掃描產出的圖片檔案並依名稱排序
            extracted_files = sorted(
                [f for f in os.listdir(output_dir) if f.lower().endswith((".jpg", ".jpeg", ".png"))]
            )

            if not extracted_files:
                # 若場景切換濾鏡未抓到任何畫面，退回每 30 秒定時均勻抽樣
                logger.warning("場景切換未偵測到畫面，退回均勻定時抽樣...")
                fallback_cmd = [
                    "ffmpeg",
                    "-y",
                    "-i", video_path,
                    "-vf", f"fps=1/{self.min_interval_seconds},scale=1280:720:force_original_aspect_ratio=decrease",
                    "-q:v", "3",
                    output_pattern,
                ]
                subprocess.run(
                    fallback_cmd,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                extracted_files = sorted(
                    [f for f in os.listdir(output_dir) if f.lower().endswith((".jpg", ".jpeg", ".png"))]
                )

            # 4. 數量限制與時間戳計算
            keyframes: List[Keyframe] = []
            total_count = len(extracted_files)
            if total_count == 0:
                return []

            # 若超出 max_keyframes 進行等距步長過濾
            selected_files = extracted_files
            if total_count > self.max_keyframes:
                step = total_count / self.max_keyframes
                selected_files = [extracted_files[int(i * step)] for i in range(self.max_keyframes)]

            # 計算每張畫面的估計時間戳
            time_interval = duration_s / max(total_count, 1) if duration_s > 0 else self.min_interval_seconds
            for idx, filename in enumerate(selected_files):
                file_full_path = os.path.join(output_dir, filename)
                # 從檔名解析或根據索引推估時間戳
                sec = idx * time_interval
                ts_str = self._format_timestamp(sec)
                keyframes.append(
                    Keyframe(
                        image_path=file_full_path,
                        timestamp_seconds=sec,
                        timestamp_str=ts_str,
                    )
                )

            logger.info(f"成功擷取 {len(keyframes)} 張簡報關鍵畫面。")
            return keyframes

        except Exception as e:
            logger.error(f"關鍵幀擷取失敗，平滑降級: {e}")
            return []

    def cleanup_keyframes(self, output_dir: str) -> None:
        """安全刪除暫存關鍵畫面目錄（落實看完即忘原則，防範機密畫面殘留與磁碟耗盡）。

        Args:
            output_dir: 欲清理之目錄路徑
        """
        if output_dir and os.path.exists(output_dir):
            try:
                shutil.rmtree(output_dir, ignore_errors=True)
                logger.info(f"已清理暫存關鍵幀目錄: {output_dir}")
            except Exception as e:
                logger.warning(f"清理關鍵幀目錄失敗: {e}")

    @staticmethod
    def _get_video_duration(video_path: str) -> float:
        """透過 ffprobe 取得視訊時長 (秒)。"""
        try:
            cmd = [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                video_path,
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return float(res.stdout.strip())
        except Exception:
            return 300.0  # 預設 5 分鐘估算

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        """將秒數格式化為 [HH:MM:SS] 標籤。"""
        total_sec = int(max(0, seconds))
        hrs = total_sec // 3600
        mins = (total_sec % 3600) // 60
        secs = total_sec % 60
        return f"[{hrs:02d}:{mins:02d}:{secs:02d}]"
