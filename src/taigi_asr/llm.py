"""LLM 外部模型通訊與會議紀錄處理服務模組。

本模組提供針對相容 OpenAI / vLLM API (如 http://192.168.1.100:8002/v1) 的客戶端：
1. 支援透過 GET /v1/models 自動動態查詢伺服器正在運行的模型名稱。
2. 階段一：語意錯別字校正 (correct_transcript)，校正同音錯字並保留講者時間標籤。
3. 階段二：四區塊結構化會議記錄生成 (generate_meeting_minutes)。
4. 思考模型標籤 (<think>...</think>) 之自動解析與徹底過濾。
5. 連線超時與異常時之 Graceful Degradation (優雅降級) 機制。
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 預設錯別字校正提示詞
DEFAULT_CORRECTION_PROMPT = (
    "你是一位專業的中文與台灣台語語音轉錄校對專家。\n"
    "以下是一段由 ASR (語音辨識) 產生的會議逐字稿。語音轉寫過程中可能包含同音錯別字、"
    "專有名詞誤辨或贅字。\n"
    "請在嚴格遵守以下規則的前提下進行校正：\n"
    "1. 根據前後文語意修復錯別字、同音字及專有名詞（如技術術語、人名、公司名）。\n"
    "2. 務必完整保留每一行開頭的講者標籤與時間戳記（例如：[00:01:23] 講者 A:），切勿刪除或修改任何時間軸與講者編號。\n"
    "3. 請直接輸出校正後的逐字稿全文，切勿輸出任何引言、開場白、結語或額外解釋。\n\n"
    "以下是原始逐字稿內容：\n"
)

# 預設遵循 video-to-notes 規格之六大結構化會議紀錄提示詞
DEFAULT_MINUTES_PROMPT = (
    "請用繁體中文，以專業「會議記錄者」的客觀視角，根據以下校正後的逐字稿整理為高規格的結構化商務會議記錄。\n"
    "請務必嚴格遵循以下 Markdown 格式與章節架構輸出：\n\n"
    "# [請提煉出簡短明確的會議核心主題]\n\n"
    "## 1. 會議基本資訊\n"
    "- 會議時間: [YYYY-MM-DD 或從逐字稿/時間資訊提取]\n"
    "- 會議地點: [線上會議 (Teams / Google Meet / Zoom) 或 實體會議室]\n"
    "- 會議主席: [會議主持人 / 主席姓名與職稱]\n"
    "- 會議記錄: [記錄人姓名]\n"
    "- 出席人員: [出/列席人員姓名清單，以頓號或逗號分隔]\n"
    "- 請假人員: [缺席/請假人員名單，若無則填寫「無」]\n\n"
    "## 2. 會議核心摘要 (Highlights)\n"
    "- 條列 3 ~ 5 點本次會議之核心成果、關鍵進展或重大共識結論。\n\n"
    "## 3. 關鍵決策事項 (Decisions Made)\n"
    "| 編號 | 決策主題 | 決策內容與共識 | 提案人 / 負責人 | 生效日期 |\n"
    "|---|---|---|---|---|\n"
    "| D-01 | [主題] | [明確決策內容與授權共識] | [負責人] | [生效日期] |\n\n"
    "## 4. 待辦事項清單 (Action Items / Todo List)\n"
    "| 待辦任務項目 (Action Item) | 負責人 | 截止期限 | 當前狀態 |\n"
    "|---|---|---|---|\n"
    "| [具體待辦任務名稱] | [負責人] | [YYYY-MM-DD 或未提及] | 進行中 / 未開始 |\n\n"
    "## 5. 各議題討論紀要 (Agenda & Discussions)\n"
    "### 議題一: [議題主題名稱]\n"
    "- 【發言人姓名 / 職稱】 [具體發言要點、觀點陳述或提問回應摘要]\n\n"
    "## 6. 下次會議追蹤項目 (Next Meeting Follow-ups)\n"
    "※ 以下項目列為下次會議開場之重點 Highlight 檢核項目：\n"
    "| 追蹤項目 (Focus Item) | 預計報告人 / 負責人 | 期望產出 / 查核標準 (Deliverable) |\n"
    "|---|---|---|\n"
    "| [追蹤項目名稱] | [報告人] | [明確交付成果] |\n\n"
    "注意：保持客觀嚴謹，不可憑空捏造人物、日期或未提及的決議。以下為會議逐字稿：\n"
)


def clean_think_tags(content: Optional[str]) -> str:
    """徹底過濾並清除推理型模型輸出中包含的 <think>...</think> 標籤與思考過程。

    Args:
        content: 包含潛在思考標籤的原始字串。

    Returns:
        過濾乾淨後的文字內容。
    """
    if not content:
        return ""

    # 移除成對的 <think>...</think> 標籤及其中內容（支援跨行）
    cleaned = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
    # 若模型輸出未閉合的 <think> 開頭
    cleaned = re.sub(r"^.*?<\/think>", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"<think>.*$", "", cleaned, flags=re.DOTALL)

    return cleaned.strip()


class LLMClient:
    """相容 OpenAI / vLLM API 之通訊客戶端，負責動態查詢模型、逐字稿校正與會議記錄生成。"""

    @staticmethod
    def clean_think_tags(content: Optional[str]) -> str:
        """過濾並清除思考標籤。"""
        return clean_think_tags(content)

    def __init__(
        self,
        base_url: str = "http://192.168.1.100:8002/v1",
        model: str = "auto",
        fallback_model: str = "nvidia/Qwen3.6-35B-A3B-NVFP4",
        timeout: int = 1800,
        api_key: str = "",
    ) -> None:
        """初始化 LLMClient 客戶端。

        Args:
            base_url: LLM 服務 API 根端點 (例如 http://192.168.1.100:8002/v1)。
            model: 模型名稱，若為 "auto" 則自動呼叫 /v1/models 查詢。
            fallback_model: 當查詢失敗或自動偵測無效時的備援模型名稱。
            timeout: HTTP 請求逾時秒數 (預設 1800 秒 / 30分鐘)。
            api_key: 可選的 API 金鑰 (Bearer Token)。
        """
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.fallback_model = fallback_model
        self.timeout = timeout
        self.api_key = api_key

    def get_available_model(self) -> str:
        """向 /v1/models 端點查詢當前伺服器運行的可用模型名稱。

        Returns:
            取得之模型 ID 字串；若查詢失敗則回傳 fallback_model。
        """
        if self.model and self.model.lower() != "auto":
            return self.model

        models_endpoint = f"{self.base_url}/models"
        logger.info(f"正在自 {models_endpoint} 動態查詢可用模型...")

        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = urllib.request.Request(models_endpoint, headers=headers, method="GET")

        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
                data_list = payload.get("data", [])
                if data_list and isinstance(data_list, list):
                    first_model_id = data_list[0].get("id")
                    if first_model_id:
                        logger.info(f"成功偵測到伺服器模型: {first_model_id}")
                        self.model = first_model_id
                        return first_model_id
        except Exception as exc:
            logger.warning(
                f"無法自 {models_endpoint} 查詢模型清單: {exc}，使用備援模型: {self.fallback_model}"
            )

        self.model = self.fallback_model
        return self.fallback_model

    def _chat_completion(self, prompt: str, temperature: float = 0.3) -> str:
        """內部呼叫 /v1/chat/completions 發送請求並回傳乾淨文字。

        Args:
            prompt: 完整的提示詞字串。
            temperature: 取樣溫度值。

        Returns:
            模型產出的乾淨內容。
        """
        current_model = self.get_available_model()
        endpoint = f"{self.base_url}/chat/completions"

        data: Dict[str, Any] = {
            "model": current_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 65536,
            "temperature": temperature,
        }

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = urllib.request.Request(
            endpoint,
            data=json.dumps(data).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=self.timeout) as response:
            res_json = json.loads(response.read().decode("utf-8"))
            choice = res_json.get("choices", [{}])[0]
            message = choice.get("message", {})
            content = message.get("content") or ""
            return clean_think_tags(content)

    def _call_chat_completion(self, prompt: str, temperature: float = 0.3) -> str:
        """內部請求別名，向下相容呼叫。"""
        return self._chat_completion(prompt, temperature=temperature)

    def correct_transcript(
        self, raw_transcript: str, prompt_template: Optional[str] = None
    ) -> str:
        """將原始逐字稿送交模型進行語意錯別字與專有名詞校正。

        Args:
            raw_transcript: ASR 轉出的原始逐字稿。
            prompt_template: 可選的自訂校正提示詞。

        Returns:
            校正後之逐字稿全文；若連線失敗或異常，自動降級回退為原始逐字稿以確保資料不遺失。
        """
        if not raw_transcript or not raw_transcript.strip():
            logger.info("輸入逐字稿為空，略過錯別字校正。")
            return ""

        base_prompt = prompt_template or DEFAULT_CORRECTION_PROMPT
        full_prompt = f"{base_prompt}\n{raw_transcript}"

        logger.info("開始執行逐字稿語意錯別字校正...")
        try:
            corrected = self._chat_completion(full_prompt, temperature=0.2)
            if not corrected.strip():
                logger.warning("模型回傳空白校正內容，降級保留原始逐字稿。")
                return raw_transcript
            return corrected
        except Exception as exc:
            logger.error(f"錯別字校正請求失敗 ({exc})，優雅降級採用原始逐字稿。")
            return raw_transcript

    def _build_minutes_prompt(
        self,
        transcript: str,
        prompt_template: Optional[str] = None,
        visual_context: Optional[str] = None,
    ) -> str:
        """組裝會議記錄提示詞，支援注入音視雙模態視覺上下文。

        Args:
            transcript: 逐字稿文字。
            prompt_template: 可選自訂模板。
            visual_context: 多模態視覺時間軸摘要 (由 VLM 分析關鍵畫面所得)。

        Returns:
            完整之提示詞字串。
        """
        base_prompt = prompt_template or DEFAULT_MINUTES_PROMPT
        parts = [base_prompt]

        if visual_context and visual_context.strip():
            visual_block = (
                "\n\n### 會議簡報與視覺畫面時間軸紀錄\n"
                "以下為從會議影片中自動擷取之關鍵畫面與投影片重點，請結合語音逐字稿與此視覺資訊進行綜合分析，"
                "修正語音中的專有名詞/同音字，並將投影片中的關鍵指標、圖表數據融入會議核心摘要、關鍵決策與議題紀要中：\n"
                f"{visual_context.strip()}"
            )
            parts.append(visual_block)

        parts.append(f"\n\n### 會議逐字稿內容：\n{transcript.strip()}")
        return "\n".join(parts)

    def generate_meeting_minutes(
        self,
        transcript: str,
        prompt_template: Optional[str] = None,
        visual_context: Optional[str] = None,
    ) -> str:
        """根據逐字稿整理出遵循 video-to-notes 規格的結構化會議記錄，支援視覺上下文整合。

        Args:
            transcript: 已校正之逐字稿內容。
            prompt_template: 可選的自訂會議記錄提示詞。
            visual_context: 多模態視覺畫面時間軸資訊。

        Returns:
            結構化 Markdown 會議記錄；若出錯則回傳包含原因之降級文字。
        """
        if not transcript or not transcript.strip():
            return "逐字稿內容為空，無法進行會議記錄生成。"

        full_prompt = self._build_minutes_prompt(
            transcript, prompt_template=prompt_template, visual_context=visual_context
        )

        logger.info("開始生成遵循 video-to-notes 規格之結構化會議記錄...")
        try:
            minutes = self._chat_completion(full_prompt, temperature=0.3)
            if not minutes.strip():
                return "摘要生成失敗：模型回傳了空白結果（可能超出上下文窗口）。"
            return minutes
        except Exception as exc:
            logger.error(f"會議記錄生成失敗: {exc}")
            return f"摘要生成失敗: {exc}"
