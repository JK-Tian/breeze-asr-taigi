#!/usr/bin/env python3
"""
影片時間軸雙重過濾與流式索引腳本 (index_video.py)

本腳本實現：
1. 自動輪詢 4 個 Docker vLLM 端點，並透過 GET /v1/models 動態獲取可用模型名稱。
2. 第一階段 (粗篩)：FFmpeg fps=1 採樣 + mpdecimate 靜態過濾。
3. 第二階段 (精篩)：dHash (Perceptual Hash) 漢明距離比對，過濾手持晃動與高頻噪點。
4. 單幀推論：呼叫 Docker vLLM OpenAI API 產出繁體中文畫面描述。
5. 流式持久化：即時 Append 寫入 Markdown，完成即刪除臨時圖檔，零硬碟與顯存洩漏。
"""

import argparse
import base64
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

import httpx

# 嘗試載入 PIL 與 imagehash，若未安裝則提供內建退回機制
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import imagehash
    HAS_IMAGEHASH = True
except ImportError:
    HAS_IMAGEHASH = False

DEFAULT_ENDPOINTS = [
    "http://192.168.1.100:8000/v1",
    "http://192.168.1.100:8001/v1",
    "http://192.168.1.100:8002/v1",
    "http://192.168.3.9:8000/v1",
    "http://192.168.3.80:8000/v1",
    "http://localhost:8000/v1",
]


def discover_active_vllm_endpoint(specified_url: Optional[str] = None, specified_model: Optional[str] = None) -> Tuple[str, str]:
    """輪詢探索健康的 vLLM 端點並透過 GET /v1/models 自動獲取模型名稱。

    Returns:
        Tuple[str, str]: (選定之端點 URL, 選定之模型名稱)
    """
    candidate_urls = [specified_url] if specified_url else DEFAULT_ENDPOINTS

    for url in candidate_urls:
        if not url:
            continue
        clean_url = url.rstrip("/")
        models_url = f"{clean_url}/models"
        try:
            with httpx.Client(timeout=3.0) as client:
                res = client.get(models_url)
                if res.status_code == 200:
                    data = res.json()
                    model_id = specified_model
                    if not model_id and "data" in data and len(data["data"]) > 0:
                        model_id = data["data"][0]["id"]
                    if not model_id:
                        model_id = "Qwen/Qwen2-VL-7B-Instruct"
                    print(f"[vLLM 探索成功] 選擇健康端點: {clean_url} | 模型: {model_id}")
                    return clean_url, model_id
        except Exception:
            continue

    # 連線失敗備用回退
    final_url = (specified_url or DEFAULT_ENDPOINTS[0]).rstrip("/")
    final_model = specified_model or "Qwen/Qwen2-VL-7B-Instruct"
    print(f"[vLLM 探索警告] 無法連線至候選端點，使用備用配置: {final_url} | 模型: {final_model}", file=sys.stderr)
    return final_url, final_model


def format_timestamp(seconds: float) -> str:
    """將秒數轉換為 HH:MM:SS 格式時間戳。"""
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def calculate_dhash_fallback(image_path: Path) -> int:
    """自建退回 64-bit dHash 演算法 (當缺少 imagehash 套件時使用)。"""
    if not HAS_PIL:
        with open(image_path, "rb") as f:
            return hash(f.read()[:1024])

    with Image.open(image_path) as img:
        img = img.convert("L").resize((9, 8), Image.Resampling.BILINEAR)
        pixels = list(img.getdata())
        diff = [pixels[row * 9 + col] > pixels[row * 9 + col + 1] for row in range(8) for col in range(8)]
        decimal_val = 0
        for bit in diff:
            decimal_val = (decimal_val << 1) | int(bit)
        return decimal_val


def hamming_distance(hash1: int, hash2: int) -> int:
    """計算兩個 64 位元整數 Hash 之間的漢明距離。"""
    return bin(hash1 ^ hash2).count("1")


class VideoTimelineIndexer:
    """影片時間軸雙重過濾與串流索引器。"""

    def __init__(
        self,
        vllm_url: Optional[str] = None,
        model_name: Optional[str] = None,
        api_key: str = "EMPTY",
        hamming_threshold: int = 4,
    ):
        # 自動探測端點與模型 ID
        self.vllm_url, self.model_name = discover_active_vllm_endpoint(vllm_url, model_name)
        self.api_key = api_key
        self.hamming_threshold = hamming_threshold
        self.last_frame_hash = None

    def extract_ffmpeg_frames(self, video_path: Path, output_dir: Path, fps: float = 1.0) -> List[Path]:
        """使用 FFmpeg 進行第一階段採樣 (fps=1) 與 mpdecimate 靜態畫面粗篩。"""
        output_pattern = str(output_dir / "frame_%05d.jpg")
        vf_filter = f"fps={fps},mpdecimate=hi=64:lo=64:frac=0.1"

        cmd = [
            "ffmpeg",
            "-y",
            "-i", str(video_path),
            "-vf", vf_filter,
            "-vsync", "vfr",
            output_pattern
        ]

        print(f"[FFmpeg] 執行第一階段粗篩: {' '.join(cmd)}")
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        if result.returncode != 0:
            print(f"[FFmpeg 錯誤] {result.stderr}", file=sys.stderr)
            raise RuntimeError("FFmpeg 畫格解碼失敗，請確認 FFmpeg 已安裝且影片檔案正常。")

        extracted_files = sorted(list(output_dir.glob("frame_*.jpg")))
        print(f"[FFmpeg] 粗篩解碼完成，共產出 {len(extracted_files)} 張候選畫格。")
        return extracted_files

    def describe_frame(self, image_path: Path) -> str:
        """呼叫 Docker vLLM API 對單張圖片進行繁體中文描述。"""
        with open(image_path, "rb") as image_file:
            base64_data = base64.b64encode(image_file.read()).decode("utf-8")
        
        mime_type = "image/jpeg"
        data_url = f"data:{mime_type};base64,{base64_data}"

        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "請用繁體中文以一至兩句話精準描述此畫面中的主要人物、物件動作或畫面變更。"
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url}
                        }
                    ]
                }
            ],
            "max_tokens": 150
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        try:
            with httpx.Client(timeout=40.0) as client:
                response = client.post(f"{self.vllm_url}/chat/completions", json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                return content.strip()
        except Exception as err:
            print(f"[vLLM API 警告] 單幀描述失敗 ({image_path.name}): {err}", file=sys.stderr)
            return "無法解析該畫面細節"

    def process_video(self, video_path: Path, output_md_path: Path, fps: float = 1.0) -> Path:
        """執行整套影片時間軸雙重過濾與 Markdown 串流索引。"""
        video_path = video_path.resolve()
        output_md_path = output_md_path.resolve()

        if not video_path.exists():
            raise FileNotFoundError(f"影片檔案不存在: {video_path}")

        tmp_dir = video_path.parent / f".tmp_frames_{int(time.time())}"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        header_text = (
            f"# 影片關鍵動態時間軸日誌 (Video Timeline Log)\n"
            f"- **來源影片檔案**：`{video_path}`\n"
            f"- **解析生成時間**：{time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"- **採樣頻率**：每 {1.0 / fps:.1f} 秒 1 幀 (`fps={fps}`)\n"
            f"- **vLLM 端點與模型**：`{self.vllm_url}` | `{self.model_name}`\n"
            f"- **雙重過濾機制**：FFmpeg mpdecimate 粗篩 + dHash (門檻 threshold<={self.hamming_threshold}) 精篩\n\n"
            f"---\n\n"
            f"## 時間軸紀錄 (Chronological Entries)\n\n"
        )
        output_md_path.write_text(header_text, encoding="utf-8")

        try:
            extracted_frames = self.extract_ffmpeg_frames(video_path, tmp_dir, fps=fps)

            self.last_frame_hash = None
            valid_count = 0

            print(f"[Indexing] 開始第二階段 (dHash 精篩) 與 Docker vLLM 推論...")

            for index, frame_path in enumerate(extracted_frames):
                if HAS_IMAGEHASH and HAS_PIL:
                    with Image.open(frame_path) as img:
                        current_hash = imagehash.dhash(img)
                    if self.last_frame_hash is not None:
                        dist = current_hash - self.last_frame_hash
                        if dist <= self.hamming_threshold:
                            os.remove(frame_path)
                            continue
                    self.last_frame_hash = current_hash
                else:
                    current_hash_int = calculate_dhash_fallback(frame_path)
                    if self.last_frame_hash is not None:
                        dist = hamming_distance(current_hash_int, self.last_frame_hash)
                        if dist <= self.hamming_threshold:
                            os.remove(frame_path)
                            continue
                    self.last_frame_hash = current_hash_int

                valid_count += 1
                timestamp_sec = index * (1.0 / fps)
                timestamp_str = format_timestamp(timestamp_sec)

                description = self.describe_frame(frame_path)

                entry_md = f"## [{timestamp_str}] ({int(timestamp_sec)} 秒)\n**畫面描述**：{description}\n\n"
                with open(output_md_path, "a", encoding="utf-8") as f:
                    f.write(entry_md)

                print(f" -> 已寫入 [{timestamp_str}] 畫面描述: {description[:30]}...")
                os.remove(frame_path)

            print(f"\n[完成] 影片時間軸索引完畢！共過濾產出 {valid_count} 個有效動態時間節點。")
            print(f" Markdown 檔案已儲存至：{output_md_path}")
            return output_md_path

        finally:
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="影片時間軸雙重過濾與流式索引工具")
    parser.add_argument("--video", "-v", required=True, type=Path, help="影片檔案路徑 (.mp4, .mkv, .mov)")
    parser.add_argument("--output", "-o", required=True, type=Path, help="產出的 .md 檔案路徑")
    parser.add_argument("--fps", type=float, default=1.0, help="採樣頻率 (預設 1.0，即每秒 1 幀)")
    parser.add_argument("--threshold", type=int, default=4, help="dHash 漢明距離過濾門檻 (預設 4)")
    parser.add_argument("--vllm-url", type=str, default=os.getenv("VLLM_BASE_URL"), help="指定 vLLM API Base URL (預設自動輪詢預設 4 端點)")
    parser.add_argument("--model", type=str, default=os.getenv("VLLM_MODEL_NAME"), help="指定 vLLM 模型名稱 (預設透過 GET /v1/models 自動查詢)")

    args = parser.parse_args()

    indexer = VideoTimelineIndexer(
        vllm_url=args.vllm_url,
        model_name=args.model,
        hamming_threshold=args.threshold
    )

    indexer.process_video(
        video_path=args.video,
        output_md_path=args.output,
        fps=args.fps
    )


if __name__ == "__main__":
    main()
