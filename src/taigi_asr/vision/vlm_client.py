"""多模態視覺語言模型 (VLM) 客戶端模組。

連線至 vLLM (OpenAI 相容) 或相容之多模態端點，
透過 Base64 image_url 將視訊會議關鍵幀發送至視覺模型 (如 Qwen3.8-27B-FP8)，
深度萃取簡報投影片主題、圖表關鍵數據、商業決策與與會者標記。
"""

from __future__ import annotations

import base64
import configparser
from dataclasses import dataclass
import json
import logging
import os
import re
from typing import List, Optional
import urllib.request
import urllib.error

from taigi_asr.vision.keyframe_extractor import Keyframe

logger = logging.getLogger("vlm_client")


@dataclass
class VisualFrameAnalysis:
    """單張畫面之視覺解析摘要。"""

    timestamp_str: str
    description: str


class VLMClient:
    """多模態視覺模型客戶端。"""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: int = 180,
    ):
        """初始化 VLM 客戶端。

        Args:
            base_url: vLLM 或相容端點 URL (例如 http://192.168.1.100:8000/v1)
            model: 模型名稱 (設為 auto 時自動向 /v1/models 查詢)
            timeout: 請求超時時間 (秒)
        """
        # 讀取設定檔預設值
        cfg_url, cfg_model = self._load_config()

        # 優先順序: 傳入參數 > 環境變數 > config.ini > 硬性預設
        env_url = os.environ.get("VLM_URL", cfg_url or "http://192.168.1.100:8000/v1")
        env_model = os.environ.get("VLM_MODEL", cfg_model or "auto")

        self.base_url = (base_url or env_url).rstrip("/")
        self.model = model or env_model
        self.timeout = timeout
        self._resolved_model: Optional[str] = None

    def _load_config(self) -> tuple[Optional[str], Optional[str]]:
        """從根目錄 config.ini 讀取 [Vision] 設定。"""
        try:
            config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../config.ini"))
            if os.path.exists(config_path):
                parser = configparser.ConfigParser()
                parser.read(config_path, encoding="utf-8")
                if "Vision" in parser:
                    url = parser["Vision"].get("vlm_url")
                    m = parser["Vision"].get("vlm_model")
                    return url, m
        except Exception:
            pass
        return None, None

    def get_model_name(self) -> str:
        """動態查詢並快取實際可用的模型名稱。"""
        if self._resolved_model:
            return self._resolved_model

        if self.model and self.model.lower() != "auto":
            self._resolved_model = self.model
            return self._resolved_model

        # 查詢 /v1/models
        try:
            models_url = f"{self.base_url}/models"
            req = urllib.request.Request(models_url, headers={"User-Agent": "TaigiASR/1.0"})
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode("utf-8"))
                if "data" in data and len(data["data"]) > 0:
                    self._resolved_model = data["data"][0]["id"]
                    logger.info(f"自動偵測到 VLM 模型: {self._resolved_model}")
                    return self._resolved_model
        except Exception as e:
            logger.warning(f"向 {self.base_url}/models 查詢模型失敗，使用預設值: {e}")

        self._resolved_model = "Qwen/Qwen3.8-27B-FP8"
        return self._resolved_model

    def analyze_frame(self, keyframe: Keyframe) -> Optional[VisualFrameAnalysis]:
        """對單張關鍵幀進行多模態視覺理解與文字摘要。

        若連線逾時或模型異常，回傳 None 觸發平滑降級。

        Args:
            keyframe: 待分析之關鍵畫面物件

        Returns:
            VisualFrameAnalysis 或 None
        """
        if not os.path.exists(keyframe.image_path):
            return None

        try:
            # 讀取影像並編碼為 Base64
            with open(keyframe.image_path, "rb") as f:
                b64_img = base64.b64encode(f.read()).decode("utf-8")

            model_name = self.get_model_name()
            prompt = (
                "你是一位專業的高階會議紀錄視覺分析專家。請詳細審視這張視訊會議畫面，重點提取以下商務資訊："
                "1. 簡報投影片的核心主題與章節標題。"
                "2. 畫面中出現的所有具體關鍵數據（例如 KPI 指標、金額、成長率、預算、進度百分比、時程規劃）。"
                "3. 畫面中標示的關鍵結論、架構圖重點或與會發言人姓名職稱。"
                "請用繁體中文以客觀、精煉的條列摘要回覆，切勿輸出空泛引言："
            )

            endpoint = f"{self.base_url}/chat/completions"
            payload = {
                "model": model_name,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{b64_img}"
                                },
                            },
                        ],
                    }
                ],
                "max_tokens": 512,
                "temperature": 0.2,
            }

            req = urllib.request.Request(
                endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                choice = res_data["choices"][0]["message"]
                
                # 同時支援標準 content 或 reasoning 欄位
                raw_text = choice.get("content") or choice.get("reasoning") or ""

                # 清理思考標籤 <think>...</think>
                cleaned_text = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL).strip()

                if cleaned_text:
                    return VisualFrameAnalysis(
                        timestamp_str=keyframe.timestamp_str,
                        description=cleaned_text,
                    )

        except Exception as e:
            logger.warning(f"畫面 {keyframe.timestamp_str} 多模態推論失敗，平滑略過: {e}")

        return None

    def analyze_keyframes(self, keyframes: List[Keyframe]) -> List[VisualFrameAnalysis]:
        """批量分析關鍵幀清單。"""
        results: List[VisualFrameAnalysis] = []
        for idx, kf in enumerate(keyframes):
            logger.info(f"正在進行多模態視覺推論 [{idx+1}/{len(keyframes)}] {kf.timestamp_str}...")
            analysis = self.analyze_frame(kf)
            if analysis:
                results.append(analysis)
        return results

    def format_visual_timeline(self, analyses: List[VisualFrameAnalysis]) -> str:
        """將多張畫面分析結果整合為結構化時間軸文字。

        Args:
            analyses: VisualFrameAnalysis 物件清單

        Returns:
            結構化時間軸 Markdown 文字
        """
        if not analyses:
            return ""

        lines = ["### 會議簡報與視覺畫面時間軸紀錄"]
        for a in analyses:
            # 清理內部多餘換行
            inline_desc = a.description.replace("\n", " ").strip()
            lines.append(f"- {a.timestamp_str} {inline_desc}")

        return "\n".join(lines)
