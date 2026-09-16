"""會議紀錄格式化、標題提取與輸出存檔工具模組。

提供：
1. 檔名字元消毒與安全性過濾 (sanitize_filename)
2. 會議主題提煉 (extract_meeting_title)
3. 四大結構化區塊完整性檢查 (validate_meeting_minutes_sections)
4. Markdown 檔案自動輸出存檔與同名流水號防覆蓋 (save_meeting_outputs)
"""

from __future__ import annotations

import datetime
from pathlib import Path
import re
from typing import Any, Dict, Optional, Tuple


def sanitize_filename(name: Optional[str]) -> str:
    """過濾非法檔名字元並防範路徑遍歷攻擊 (Path Traversal)。

    Args:
        name: 原始字串。

    Returns:
        安全且清理後的檔名字串。
    """
    if not name:
        return ""

    # 移除路徑遍歷字元
    cleaned = name.replace("..", "")
    # 移除非法檔名字元 (\, /, *, ?, :, ", <, >, |, 換行符等)
    cleaned = re.sub(r'[\\/*?:"<>|\r\n\t]', '', cleaned)
    # 移除前後 Markdown 標頭符號、星號與空白
    cleaned = re.sub(r'^[#*\s]+', '', cleaned)
    cleaned = re.sub(r'[#*\s]+$', '', cleaned)
    # 連續空白替換為單一空格
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    return cleaned[:80]


def extract_meeting_title(summary: Optional[str], fallback: str = "未命名會議") -> str:
    """從 LLM 生成的會議紀錄 Markdown 內容中提煉會議主題名稱。

    Args:
        summary: 會議紀錄 Markdown 全文。
        fallback: 當未能解析出標題時的備用名稱。

    Returns:
        清理後的會議主題字串。
    """
    if summary:
        lines = summary.splitlines()
        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            clean_line = line_str.replace('*', '').strip()

            # 匹配「會議名稱：XXX」或「會議主題：XXX」
            match = re.search(r'(?:會議名稱|會議主題|主題|標題)[：:]\s*(.+)', clean_line)
            if match:
                extracted = match.group(1).strip()
                clean_name = sanitize_filename(extracted)
                if clean_name:
                    return clean_name

            # 匹配 # 主題 (僅限一級標頭，不包含 ## 二級章節標頭)
            h1_match = re.match(r'^#\s+([^#].*)$', clean_line)
            if h1_match:
                extracted = h1_match.group(1).strip()
                clean_name = sanitize_filename(extracted)
                # 排除常見的固定章節詞彙
                invalid_titles = [
                    "會議紀錄", "會議摘要", "會議重點", "摘要",
                    "【會議重點】", "【關鍵決策】", "【TODO / 行動項目】", "【下次會議追蹤項目】"
                ]
                if clean_name and clean_name not in invalid_titles and not clean_name.startswith("【"):
                    return clean_name

    clean_fallback = sanitize_filename(fallback)
    return clean_fallback if clean_fallback else "未命名會議"


def validate_meeting_minutes_sections(markdown_text: Optional[str]) -> Dict[str, bool]:
    """檢驗會議紀錄是否完整包含四大核心區塊。

    Args:
        markdown_text: 會議記錄全文。

    Returns:
        包含各區塊是否存在以及整體 is_valid 狀態的字典。
    """
    if not markdown_text:
        return {
            "has_focus": False,
            "has_decisions": False,
            "has_todos": False,
            "has_followups": False,
            "is_valid": False,
        }

    has_focus = "【會議重點】" in markdown_text
    has_decisions = "【關鍵決策】" in markdown_text
    has_todos = "【TODO" in markdown_text or "【行動項目】" in markdown_text
    has_followups = "【下次會議追蹤項目】" in markdown_text

    is_valid = has_focus and has_decisions and has_todos and has_followups

    return {
        "has_focus": has_focus,
        "has_decisions": has_decisions,
        "has_todos": has_todos,
        "has_followups": has_followups,
        "is_valid": is_valid,
    }


def save_meeting_outputs(
    transcript: str,
    summary: str,
    output_dir: Path | str,
    meeting_name: Optional[str] = None,
    fallback_name: str = "未命名會議",
    task_id: Optional[str] = None,
) -> Tuple[Path, Path]:
    """將校正逐字稿與會議記錄摘要儲存為 Markdown 檔案，支援同名流水號防覆蓋。

    Args:
        transcript: 逐字稿文字。
        summary: 會議記錄摘要文字。
        output_dir: 輸出資料夾路徑。
        meeting_name: 指定會議名稱（若無則自動自 summary 提煉）。
        fallback_name: 備援檔案名稱。
        task_id: 可選的任務 ID。

    Returns:
        (transcript_file_path, summary_file_path) 的 Path 元組。
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    title = meeting_name or extract_meeting_title(summary, fallback=fallback_name)
    title = sanitize_filename(title) or "未命名會議"

    today_str = datetime.datetime.now().strftime("%Y-%m-%d")

    base_filename = title
    transcript_file = out_path / f"{base_filename}_逐字稿.md"
    summary_file = out_path / f"{base_filename}_會議紀錄與摘要.md"

    # 若檔案已存在，自動加上流水號遞增
    counter = 1
    while transcript_file.exists() or summary_file.exists():
        base_filename = f"{title}_{counter}"
        transcript_file = out_path / f"{base_filename}_逐字稿.md"
        summary_file = out_path / f"{base_filename}_會議紀錄與摘要.md"
        counter += 1

    id_header = f"- **任務 ID**: {task_id}\n\n" if task_id else "\n"

    # 寫入逐字稿
    transcript_content = (
        f"# {title} - 會議逐字稿\n\n"
        f"- **日期**: {today_str}\n"
        f"{id_header}"
        "---\n\n"
        f"{transcript or ''}\n"
    )
    transcript_file.write_text(transcript_content, encoding="utf-8")

    # 寫入會議紀錄
    summary_content = (
        f"# {title} - 會議紀錄與摘要\n\n"
        f"- **日期**: {today_str}\n"
        f"{id_header}"
        "---\n\n"
        f"{summary or ''}\n"
    )
    summary_file.write_text(summary_content, encoding="utf-8")

    return transcript_file, summary_file
