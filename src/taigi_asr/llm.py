"""LLM 外部模型通訊與會議紀錄處理服務模組。

本模組提供針對相容 OpenAI / vLLM API (如 http://192.168.1.100:8002/v1) 的客戶端：
1. 支援透過 GET /v1/models 自動動態查詢伺服器正在運行的模型名稱。
2. 階段一：語意錯別字校正 (correct_transcript)，校正同音錯字並保留講者時間標籤。
   - 長逐字稿自動分段 (chunked correction)，以 ThreadPoolExecutor 並行呼叫 LLM，
     並於合併時去除重疊行以確保完整性。
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
from concurrent.futures import ThreadPoolExecutor, as_completed
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


# ─── 逐字稿分段 (Chunked Transcript) ──────────────────────────────────────

# 匹配逐字稿行首的 SPEAKER 標籤，用於偵測講者邊界
_SPEAKER_RE = re.compile(r"\[SPEAKER_\d+\]")


def _extract_speaker(line: str) -> Optional[str]:
    """從逐字稿行中提取 SPEAKER 標籤。

    Args:
        line: 單行逐字稿文字。

    Returns:
        SPEAKER 標籤字串；若該行無標籤則回傳 None。
    """
    m = _SPEAKER_RE.search(line)
    return m.group(0) if m else None


def chunk_transcript(
    transcript: str,
    max_lines: int = 50,
    overlap_lines: int = 3,
) -> List[str]:
    """將逐字稿按行數分段，確保不在同一 SPEAKER 段落中間截斷。

    分段策略：
    1. 以 max_lines 為目標長度逐行累積。
    2. 當累積行數達到 max_lines 時，尋找最近的 SPEAKER 切換點作為分段邊界。
       若往回找不到（整段同一講者），則直接在 max_lines 處截斷。
    3. 相鄰 chunk 之間重疊 overlap_lines 行，提供上下文語境給 LLM。

    Args:
        transcript: 完整逐字稿文字。
        max_lines: 每段最大行數（預設 50）。
        overlap_lines: 相鄰段重疊行數（預設 3）。

    Returns:
        分段後的逐字稿字串列表。
    """
    lines = transcript.splitlines()
    total = len(lines)

    if total <= max_lines:
        return [transcript]

    chunks: List[str] = []
    start = 0

    while start < total:
        end = min(start + max_lines, total)

        # 若尚未到達文件末尾，向回搜尋最近的 SPEAKER 切換點
        if end < total:
            cut = end
            current_speaker = _extract_speaker(lines[end - 1]) if end > 0 else None
            # 從 end 往回尋找不同講者的邊界
            for i in range(end - 1, start, -1):
                sp = _extract_speaker(lines[i])
                if sp and sp != current_speaker:
                    cut = i + 1
                    break
            end = cut

        chunk_lines = lines[start:end]

        # 若不是最後一段，附加 overlap_lines 行
        if end < total:
            overlap_end = min(end + overlap_lines, total)
            chunk_lines = lines[start:overlap_end]

        chunks.append("\n".join(chunk_lines))
        start = end

    return chunks


def _merge_corrected_chunks(
    corrected_chunks: List[str],
    overlap_lines: int,
) -> str:
    """合併分段校正結果，去除重疊區域的重複行。

    去重策略：每個 chunk（除最後一個之外）的末尾 overlap_lines 行
    會與下一個 chunk 的開頭重疊，合併時截除前一個 chunk 的尾部重疊區域。

    Args:
        corrected_chunks: 各段校正後的文字列表。
        overlap_lines: 重疊行數。

    Returns:
        合併去重後的完整逐字稿。
    """
    if not corrected_chunks:
        return ""
    if len(corrected_chunks) == 1:
        return corrected_chunks[0]

    merged_lines: List[str] = []
    for idx, chunk in enumerate(corrected_chunks):
        lines = chunk.splitlines()
        if idx < len(corrected_chunks) - 1:
            # 非最後一段：截除末尾 overlap 行（下一段開頭已包含這些行）
            merged_lines.extend(lines[:-overlap_lines] if overlap_lines > 0 else lines)
        else:
            # 最後一段：保留全部行
            merged_lines.extend(lines)

    return "\n".join(merged_lines)


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
        self,
        raw_transcript: str,
        prompt_template: Optional[str] = None,
        chunk_max_lines: int = 50,
        chunk_overlap_lines: int = 3,
    ) -> str:
        """將原始逐字稿送交模型進行語意錯別字與專有名詞校正。

        長逐字稿（超過 chunk_max_lines 行）自動分段並行校正，
        合併時去除重疊行以確保完整性。

        Args:
            raw_transcript: ASR 轉出的原始逐字稿。
            prompt_template: 可選的自訂校正提示詞。
            chunk_max_lines: 每段最大行數（預設 50）。
            chunk_overlap_lines: 相鄰段重疊行數（預設 3）。

        Returns:
            校正後之逐字稿全文；若連線失敗或異常，自動降級回退為原始逐字稿以確保資料不遺失。
        """
        if not raw_transcript or not raw_transcript.strip():
            logger.info("輸入逐字稿為空，略過錯別字校正。")
            return ""

        line_count = len(raw_transcript.strip().splitlines())
        base_prompt = prompt_template or DEFAULT_CORRECTION_PROMPT

        # 短逐字稿：走原始單次校正路徑
        if line_count <= chunk_max_lines:
            full_prompt = f"{base_prompt}\n{raw_transcript}"
            logger.info("開始執行逐字稿語意錯別字校正（單次模式）...")
            try:
                corrected = self._chat_completion(full_prompt, temperature=0.2)
                if not corrected.strip():
                    logger.warning("模型回傳空白校正內容，降級保留原始逐字稿。")
                    return raw_transcript
                return corrected
            except Exception as exc:
                logger.error(f"錯別字校正請求失敗 ({exc})，優雅降級採用原始逐字稿。")
                return raw_transcript

        # 長逐字稿：分段並行校正
        return self._correct_transcript_chunked(
            raw_transcript,
            base_prompt=base_prompt,
            chunk_max_lines=chunk_max_lines,
            chunk_overlap_lines=chunk_overlap_lines,
        )

    def _correct_transcript_chunked(
        self,
        raw_transcript: str,
        base_prompt: str,
        chunk_max_lines: int,
        chunk_overlap_lines: int,
    ) -> str:
        """將長逐字稿分段並行送交 LLM 校正，合併去重後回傳完整結果。

        Args:
            raw_transcript: 完整原始逐字稿。
            base_prompt: 校正提示詞模板。
            chunk_max_lines: 每段最大行數。
            chunk_overlap_lines: 重疊行數。

        Returns:
            合併去重後之校正逐字稿。
        """
        chunks = chunk_transcript(
            raw_transcript,
            max_lines=chunk_max_lines,
            overlap_lines=chunk_overlap_lines,
        )
        total = len(chunks)
        logger.info(
            f"長逐字稿分段校正：共 {total} 段 "
            f"(max_lines={chunk_max_lines}, overlap={chunk_overlap_lines})，以並行模式執行..."
        )

        # 索引 -> 校正結果的字典，用於保持順序
        corrected_map: Dict[int, str] = {}

        def _correct_one(idx: int, chunk: str) -> tuple:
            """校正單一段落，失敗時降級回傳原始文字。"""
            prompt = f"{base_prompt}\n{chunk}"
            try:
                result = self._chat_completion(prompt, temperature=0.2)
                if not result.strip():
                    logger.warning(f"分段校正 [{idx + 1}/{total}]：模型回傳空白，降級保留原始。")
                    return idx, chunk
                logger.info(f"分段校正 [{idx + 1}/{total}]：完成。")
                return idx, result
            except Exception as exc:
                logger.warning(f"分段校正 [{idx + 1}/{total}] 失敗 ({exc})，降級保留原始。")
                return idx, chunk

        # 並行送出所有段落，最多 4 條並行
        with ThreadPoolExecutor(max_workers=min(total, 4)) as executor:
            futures = {
                executor.submit(_correct_one, i, chunk): i
                for i, chunk in enumerate(chunks)
            }
            for future in as_completed(futures):
                idx, result = future.result()
                corrected_map[idx] = result

        # 按原始順序組裝並合併去重
        ordered = [corrected_map[i] for i in range(total)]
        merged = _merge_corrected_chunks(ordered, overlap_lines=chunk_overlap_lines)

        logger.info(f"分段校正合併完成，共 {len(merged.splitlines())} 行。")
        return merged

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
