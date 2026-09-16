#!/usr/bin/env python3
"""
圖片多模態預處理、去重與串流解析腳本 (analyze_images.py)

本腳本實現：
1. 自動輪詢 4 個 Docker vLLM 端點，並透過 GET /v1/models 動態獲取可用模型名稱。
2. 圖片自動 Resize (Max 2048px) 與 Base64 Data URL 編碼，解決 Docker 容器隔離讀不到圖與顯存 OOM。
3. dHash (Perceptual Hash) 漢明距離比對，自動過濾批次圖片中的重複/極相似圖片。
4. 單圖串流處理：呼叫 Docker vLLM API 產出視覺描述、OCR 與標籤。
5. 流式持久化：即時 Append 寫入 image_analysis_report.md。
"""

import argparse
import base64
import io
import os
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

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

DEFAULT_ENDPOINTS = [
    "http://192.168.1.100:8000/v1",
    "http://192.168.1.100:8001/v1",
    "http://192.168.1.100:8002/v1",
    "http://192.168.3.9:8000/v1",
    "http://192.168.3.80:8000/v1",
    "http://localhost:8000/v1",
]


def discover_active_vllm_endpoint(specified_url: Optional[str] = None, specified_model: Optional[str] = None) -> Tuple[str, str]:
    """輪詢探索健康的 vLLM 端點並透過 GET /v1/models 自動獲取模型名稱。"""
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

    final_url = (specified_url or DEFAULT_ENDPOINTS[0]).rstrip("/")
    final_model = specified_model or "Qwen/Qwen2-VL-7B-Instruct"
    print(f"[vLLM 探索警告] 無法連線至候選端點，使用備用配置: {final_url} | 模型: {final_model}", file=sys.stderr)
    return final_url, final_model


def calculate_dhash_fallback(img_path: Path) -> int:
    """當缺乏 imagehash 套件時之退回 dHash 計算器。"""
    if not HAS_PIL:
        with open(img_path, "rb") as f:
            return hash(f.read()[:1024])

    with Image.open(img_path) as img:
        img = img.convert("L").resize((9, 8), Image.Resampling.BILINEAR)
        pixels = list(img.getdata())
        diff = [pixels[row * 9 + col] > pixels[row * 9 + col + 1] for row in range(8) for col in range(8)]
        decimal_val = 0
        for bit in diff:
            decimal_val = (decimal_val << 1) | int(bit)
        return decimal_val


def hamming_distance(hash1: int, hash2: int) -> int:
    """計算兩個 64 位元 Hash 之漢明距離。"""
    return bin(hash1 ^ hash2).count("1")


class ImageVlmAnalyzer:
    """圖片多模態解析器。"""

    def __init__(
        self,
        vllm_url: Optional[str] = None,
        model_name: Optional[str] = None,
        api_key: str = "EMPTY",
        max_dimension: int = 2048,
        hamming_threshold: int = 4,
    ):
        self.vllm_url, self.model_name = discover_active_vllm_endpoint(vllm_url, model_name)
        self.api_key = api_key
        self.max_dimension = max_dimension
        self.hamming_threshold = hamming_threshold
        self.last_hash = None

    def preprocess_image(self, img_path: Path) -> Tuple[str, str]:
        """讀取圖片、進行自動 Resize 並轉換為 Base64 Data URL。"""
        if not HAS_PIL:
            with open(img_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            return f"data:image/jpeg;base64,{b64}", "原始尺寸 (無 PIL)"

        with Image.open(img_path) as img:
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            width, height = img.size

            if max(width, height) > self.max_dimension:
                if width > height:
                    new_width = self.max_dimension
                    new_height = int(height * (self.max_dimension / width))
                else:
                    new_height = self.max_dimension
                    new_width = int(width * (self.max_dimension / height))
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                dimension_info = f"{width}x{height} -> {new_width}x{new_height} (已 Resize)"
            else:
                dimension_info = f"{width}x{height} (原始尺寸)"

            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=85)
            b64_str = base64.b64encode(buffer.getvalue()).decode("utf-8")
            return f"data:image/jpeg;base64,{b64_str}", dimension_info

    def analyze_single_image(self, data_url: str, prompt: Optional[str] = None) -> str:
        """呼叫 Docker vLLM API 進行多模態分析。"""
        default_prompt = (
            "請用繁體中文詳細分析此圖片內容，輸出包含以下三個區塊：\n"
            "1. 🔍 視覺內容描述 (簡述畫面人物、物件與場景)\n"
            "2. 📝 文字識別 (若畫面有文字或程式碼請轉錄，若無則寫「無顯著文字」)\n"
            "3. 🏷️ 關鍵標籤 (輸出 3-5 個以 # 開頭的標籤)"
        )
        user_prompt = prompt or default_prompt

        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": data_url}}
                    ]
                }
            ],
            "max_tokens": 512
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        try:
            with httpx.Client(timeout=45.0) as client:
                response = client.post(f"{self.vllm_url}/chat/completions", json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"].strip()
        except Exception as err:
            print(f"[vLLM 錯誤] 圖片解析失敗: {err}", file=sys.stderr)
            return "無法解析該圖片內容。"

    def process_targets(self, targets: List[Path], output_md_path: Path, prompt: Optional[str] = None) -> Path:
        """執行圖片清單之批次/單圖處理並流式寫入 Markdown 報告。"""
        output_md_path = output_md_path.resolve()
        source_desc = f"圖片資料夾 ({targets[0].parent})" if len(targets) > 1 else f"單張圖片 ({targets[0]})"

        header_text = (
            f"# 圖片多模態分析與檢索日誌 (Image Analysis Report)\n"
            f"- **解析目標**：{source_desc}\n"
            f"- **生成時間**：{time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"- **vLLM 端點與模型**：`{self.vllm_url}` | `{self.model_name}`\n"
            f"- **預處理機制**：自動 Resize (Max {self.max_dimension}px) + dHash 相似去重 (Threshold <= {self.hamming_threshold})\n\n"
            f"---\n\n"
            f"## 📊 圖片解析明細 (Image Entries)\n\n"
        )
        output_md_path.write_text(header_text, encoding="utf-8")

        self.last_hash = None
        processed_count = 0

        for index, img_path in enumerate(targets, 1):
            img_path = img_path.resolve()
            if not img_path.exists():
                continue

            if len(targets) > 1:
                if HAS_IMAGEHASH and HAS_PIL:
                    with Image.open(img_path) as img:
                        curr_hash = imagehash.dhash(img)
                    if self.last_hash is not None and (curr_hash - self.last_hash) <= self.hamming_threshold:
                        print(f"[跳過重複圖片] {img_path.name}")
                        continue
                    self.last_hash = curr_hash
                else:
                    curr_hash_int = calculate_dhash_fallback(img_path)
                    if self.last_hash is not None and hamming_distance(curr_hash_int, self.last_hash) <= self.hamming_threshold:
                        print(f"[跳過重複圖片] {img_path.name}")
                        continue
                    self.last_hash = curr_hash_int

            processed_count += 1
            print(f"[{processed_count}/{len(targets)}] 正在解析圖片: {img_path.name}...")

            data_url, dim_info = self.preprocess_image(img_path)
            analysis_res = self.analyze_single_image(data_url, prompt=prompt)

            entry_md = (
                f"### {processed_count}. `{img_path}`\n"
                f"- **解析時間**：[{time.strftime('%Y-%m-%d %H:%M:%S')}]\n"
                f"- **圖片狀態**：`{dim_info}`\n\n"
                f"{analysis_res}\n\n"
                f"---\n\n"
            )
            with open(output_md_path, "a", encoding="utf-8") as f:
                f.write(entry_md)

        print(f"\n[完成] 圖片解析報告已生成！共處理 {processed_count} 張有效圖片。")
        print(f" 報告檔案：{output_md_path}")
        return output_md_path


def main():
    parser = argparse.ArgumentParser(description="圖片多模態預處理、去重與串流解析工具")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--image", "-i", type=Path, help="單張圖片檔案路徑")
    group.add_argument("--dir", "-d", type=Path, help="包含圖片之資料夾目錄")

    parser.add_argument("--output", "-o", required=True, type=Path, help="輸出的 Markdown 報告路徑")
    parser.add_argument("--prompt", type=str, help="自訂 Vision Prompt 需求")
    parser.add_argument("--max-dim", type=int, default=2048, help="最大圖片邊長 (預設 2048px)")
    parser.add_argument("--threshold", type=int, default=4, help="dHash 相似去重門檻 (預設 4)")
    parser.add_argument("--vllm-url", type=str, default=os.getenv("VLLM_BASE_URL"), help="指定 vLLM API Base URL (預設自動輪詢預設 4 端點)")
    parser.add_argument("--model", type=str, default=os.getenv("VLLM_MODEL_NAME"), help="指定 vLLM 模型名稱 (預設透過 GET /v1/models 自動查詢)")

    args = parser.parse_args()

    targets: List[Path] = []
    if args.image:
        targets = [args.image]
    elif args.dir:
        dir_path = args.dir.resolve()
        if not dir_path.exists():
            print(f"錯誤: 資料夾不存在: {dir_path}", file=sys.stderr)
            sys.exit(1)
        targets = sorted([p for p in dir_path.glob("*") if p.suffix.lower() in SUPPORTED_EXTENSIONS])

    if not targets:
        print("未找到任何有效之圖片檔案。", file=sys.stderr)
        sys.exit(1)

    analyzer = ImageVlmAnalyzer(
        vllm_url=args.vllm_url,
        model_name=args.model,
        max_dimension=args.max_dim,
        hamming_threshold=args.threshold
    )

    analyzer.process_targets(targets, args.output, prompt=args.prompt)


if __name__ == "__main__":
    main()
