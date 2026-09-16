#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
視訊會議轉高階會議記錄 Word 自動生成腳本 (Video to Notes Docx Generator)
遵循 S.O.L.I.D. 原則與 Clean Architecture 設計：
1. MeetingNotesParser：專責結構化 Markdown 文本與 YAML frontmatter 解析。
2. NotesStyleManager：專責字型層級 (Noto Sans TC / Calibri)、商務色彩與表格排版美化。
3. NotesDocxBuilder：專責組裝 Word 元素，提供 100% 零截圖純淨商務文件排版。

版權所有 (C) 2026 TanKong 雙軌品質管理專案
"""

import os
import re
import sys
import argparse
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional

import yaml
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn, nsdecls


# ==============================================================================
# 資料結構定義 (Domain Models)
# ==============================================================================

@dataclass
class DecisionItem:
    """關鍵決策項目資料物件"""
    id: str = ""
    topic: str = ""
    decision_content: str = ""
    owner_or_proposer: str = ""
    effective_date: str = ""


@dataclass
class TodoItem:
    """待辦事項 (Action Item) 資料物件"""
    task: str = ""
    owner: str = ""
    due_date: str = ""
    status: str = "未開始"


@dataclass
class SpeakerDiscussion:
    """發言人討論發言資料物件"""
    speaker_name: str = ""
    statement_summary: str = ""


@dataclass
class AgendaSection:
    """議題討論小節資料物件"""
    topic_title: str = ""
    discussions: List[SpeakerDiscussion] = field(default_factory=list)


@dataclass
class FollowUpItem:
    """下次會議追蹤項目資料物件"""
    item_title: str = ""
    responsible_person: str = ""
    expected_outcome: str = ""


@dataclass
class MeetingNotesData:
    """完整會議記錄資料物件"""
    parameters_yaml: str = ""
    title: str = "視訊會議記錄"
    meeting_date: str = ""
    meeting_time: str = ""
    location: str = ""
    chairperson: str = ""
    minute_taker: str = ""
    attendees: List[str] = field(default_factory=list)
    absentees: List[str] = field(default_factory=list)
    highlights: List[str] = field(default_factory=list)
    decisions: List[DecisionItem] = field(default_factory=list)
    todos: List[TodoItem] = field(default_factory=list)
    agenda_discussions: List[AgendaSection] = field(default_factory=list)
    next_meeting_followups: List[FollowUpItem] = field(default_factory=list)
    references: List[str] = field(default_factory=list)


# ==============================================================================
# Markdown 解析器 (Single Responsibility: Parsing Markdown to Domain Models)
# ==============================================================================

class MeetingNotesParser:
    """會議記錄 Markdown 解析器"""

    @staticmethod
    def parse(text: str) -> MeetingNotesData:
        """
        解析會議記錄 Markdown 字串，轉換為 MeetingNotesData 資料物件。
        支援提取 YAML frontmatter, 基本資訊, 摘要, 決策表格, Todo 清單, 發言人討論, 下次追蹤與文末參考資料。
        """
        data = MeetingNotesData()

        # 1. 擷取開頭 YAML 參數區塊 (Frontmatter 或代碼區塊)
        yaml_match = re.search(r"^(?:---[\r\n]+(.*?)[\r\n]+---|```yaml[\r\n]+(.*?)[\r\n]+```)", text, re.DOTALL | re.MULTILINE)
        if yaml_match:
            raw_yaml = (yaml_match.group(1) or yaml_match.group(2) or "").strip()
            data.parameters_yaml = raw_yaml
            try:
                y_data = yaml.safe_load(raw_yaml)
                if isinstance(y_data, dict):
                    if "title" in y_data and y_data["title"]:
                        data.title = str(y_data["title"]).strip()
                    if "date" in y_data and y_data["date"]:
                        data.meeting_date = str(y_data["date"]).strip()
            except Exception:
                pass

        # 2. 擷取 H1 文件標題 (若前置 frontmatter 未設定具體標題)
        h1_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        if h1_match and ("{{" not in h1_match.group(1)):
            data.title = h1_match.group(1).strip()

        # 3. 擷取會議基本資訊
        MeetingNotesParser._parse_basic_info(text, data)

        # 4. 擷取會議核心摘要 (Highlights)
        data.highlights = MeetingNotesParser._parse_highlights(text)

        # 5. 擷取關鍵決策事項 (Decisions Made)
        data.decisions = MeetingNotesParser._parse_decisions(text)

        # 6. 擷取待辦事項清單 (Action Items / Todo List)
        data.todos = MeetingNotesParser._parse_todos(text)

        # 7. 擷取各議題討論紀要 (Agenda & Discussions)
        data.agenda_discussions = MeetingNotesParser._parse_discussions(text)

        # 8. 擷取下次會議追蹤項目 (Next Meeting Follow-ups)
        data.next_meeting_followups = MeetingNotesParser._parse_followups(text)

        # 9. 擷取文末參考資料
        ref_match = re.search(r"(?:^|\n)#+\s*(?:參考資料|參考來源|References)[^\n]*\n([\s\S]*?)(?=\n#|\Z)", text)
        if ref_match:
            lines = [l.strip() for l in ref_match.group(1).strip().splitlines() if l.strip()]
            data.references = lines

        return data

    @staticmethod
    def _parse_basic_info(text: str, data: MeetingNotesData) -> None:
        """解析會議基本資訊（時間、地點、主席、記錄、出席、請假人員）"""
        info_section = re.search(r"(?:##|###)\s*(?:1\.\s*)?會議基本資訊[^\n]*\n([\s\S]*?)(?=\n#{2,3}|\Z)", text)
        content = info_section.group(1) if info_section else text

        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue

            # 會議時間
            m_time = re.search(r"(?:會議時間|時間)[:：]\s*(.+)$", line)
            if m_time:
                data.meeting_time = m_time.group(1).strip()

            # 會議地點
            m_loc = re.search(r"(?:會議地點|地點)[:：]\s*(.+)$", line)
            if m_loc:
                data.location = m_loc.group(1).strip()

            # 會議主席
            m_chair = re.search(r"(?:會議主席|主席)[:：]\s*(.+)$", line)
            if m_chair:
                data.chairperson = m_chair.group(1).strip()

            # 會議記錄
            m_taker = re.search(r"(?:會議記錄|記錄|紀錄)[:：]\s*(.+)$", line)
            if m_taker:
                data.minute_taker = m_taker.group(1).strip()

            # 出席人員
            m_att = re.search(r"(?:出席人員|出席者|列席人員)[:：]\s*(.+)$", line)
            if m_att:
                raw_att = m_att.group(1).strip()
                data.attendees = [p.strip() for p in re.split(r"[,、，\s]+", raw_att) if p.strip()]

            # 請假人員
            m_abs = re.search(r"(?:請假人員|缺席人員)[:：]\s*(.+)$", line)
            if m_abs:
                raw_abs = m_abs.group(1).strip()
                data.absentees = [p.strip() for p in re.split(r"[,、，\s]+", raw_abs) if p.strip()]

    @staticmethod
    def _parse_highlights(text: str) -> List[str]:
        """解析會議核心摘要清單"""
        hl_section = re.search(r"(?:##|###)\s*(?:2\.\s*)?(?:會議核心摘要|核心摘要|重點摘要|Highlights)[^\n]*\n([\s\S]*?)(?=\n#{2,3}|\Z)", text)
        if not hl_section:
            return []

        highlights = []
        for line in hl_section.group(1).splitlines():
            line = line.strip()
            if line.startswith(("-", "*", "•")) or re.match(r"^\d+\.", line):
                item = re.sub(r"^(?:[-*•]|\d+\.)\s*", "", line).strip()
                if item:
                    highlights.append(item)
        return highlights

    @staticmethod
    def _parse_decisions(text: str) -> List[DecisionItem]:
        """解析關鍵決策表格 (依據標準 Markdown 表格分隔線狀態機解析)"""
        sec = re.search(r"(?:##|###)\s*(?:3\.\s*)?(?:關鍵決策事項|決策事項|Decisions Made)[^\n]*\n([\s\S]*?)(?=\n#{2,3}|\Z)", text)
        if not sec:
            return []

        decisions: List[DecisionItem] = []
        found_sep = False
        for line in sec.group(1).splitlines():
            line = line.strip()
            if not line.startswith("|"):
                continue
            if "---" in line:
                found_sep = True
                continue
            if not found_sep:
                continue

            cols = [c.strip() for c in line.split("|")[1:-1]]
            if len(cols) >= 3:
                d = DecisionItem(
                    id=cols[0] if len(cols) > 0 else "",
                    topic=cols[1] if len(cols) > 1 else "",
                    decision_content=cols[2] if len(cols) > 2 else "",
                    owner_or_proposer=cols[3] if len(cols) > 3 else "",
                    effective_date=cols[4] if len(cols) > 4 else ""
                )
                decisions.append(d)
        return decisions

    @staticmethod
    def _parse_todos(text: str) -> List[TodoItem]:
        """解析待辦事項清單 (依據標準 Markdown 表格分隔線狀態機解析)"""
        sec = re.search(r"(?:##|###)\s*(?:4\.\s*)?(?:待辦事項清單|行動清單|Action Items|Todo List)[^\n]*\n([\s\S]*?)(?=\n#{2,3}|\Z)", text)
        if not sec:
            return []

        todos: List[TodoItem] = []
        found_sep = False
        for line in sec.group(1).splitlines():
            line = line.strip()
            if not line.startswith("|"):
                continue
            if "---" in line:
                found_sep = True
                continue
            if not found_sep:
                continue

            cols = [c.strip() for c in line.split("|")[1:-1]]
            if len(cols) >= 2:
                t = TodoItem(
                    task=cols[0],
                    owner=cols[1] if len(cols) > 1 else "",
                    due_date=cols[2] if len(cols) > 2 else "",
                    status=cols[3] if len(cols) > 3 else "未開始"
                )
                todos.append(t)
        return todos

    @staticmethod
    def _parse_discussions(text: str) -> List[AgendaSection]:
        """解析各議題討論紀要與發言人發言"""
        sec = re.search(r"(?:##|###)\s*(?:5\.\s*)?(?:各議題討論紀要|討論紀要|Agenda & Discussions)[^\n]*\n([\s\S]*?)(?=\n#+\s*(?:[6-9]\.|下次|參考|References)|\Z)", text)
        if not sec:
            return []

        sections: List[AgendaSection] = []
        raw_content = sec.group(1)
        sub_blocks = re.split(r"(?=(?:###|####)\s*(?:議題|Agenda))", raw_content, flags=re.IGNORECASE)

        for blk in sub_blocks:
            blk = blk.strip()
            if not blk:
                continue

            title_m = re.search(r"^(?:###|####)\s*(.+)$", blk, re.MULTILINE)
            raw_title = title_m.group(1).strip() if title_m else "議題討論"
            current_title = re.sub(r"^(?:議題\s*[\d一二三四五六七八九十]+|Agenda\s*\d+)[:：]?\s*", "", raw_title).strip()
            if not current_title:
                current_title = raw_title

            discussions: List[SpeakerDiscussion] = []
            for line in blk.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                # 匹配 【發言人】 或 [發言人] 格式 (排除如 [檔案.mp4] 之無內文檔名格式)
                speaker_m = re.search(r"^[-*•]?\s*(?:【([^】]+)】|\[([^\]]+)\])\s*(.*)$", line)
                if speaker_m:
                    spk_name = (speaker_m.group(1) or speaker_m.group(2) or "").strip()
                    stmt = speaker_m.group(3).strip()
                    # 防呆：若無發言內容且為影音檔名則略過
                    if not stmt and any(spk_name.lower().endswith(ext) for ext in [".mp4", ".mov", ".mkv", ".mp3", ".wav"]):
                        continue
                    discussions.append(SpeakerDiscussion(
                        speaker_name=spk_name,
                        statement_summary=stmt
                    ))
                elif line.startswith(("-", "*", "•")):
                    clean_line = re.sub(r"^[-*•]\s*", "", line).strip()
                    discussions.append(SpeakerDiscussion(
                        speaker_name="綜合討論",
                        statement_summary=clean_line
                    ))

            sections.append(AgendaSection(topic_title=current_title, discussions=discussions))

        return sections

    @staticmethod
    def _parse_followups(text: str) -> List[FollowUpItem]:
        """解析下次會議追蹤項目表格 (依據標準 Markdown 表格分隔線狀態機解析)"""
        sec = re.search(r"(?:##|###)\s*(?:6\.\s*)?(?:下次會議追蹤項目|下次會議追蹤|Next Meeting Follow-ups)[^\n]*\n([\s\S]*?)(?=\n#|\Z)", text)
        if not sec:
            return []

        followups: List[FollowUpItem] = []
        found_sep = False
        for line in sec.group(1).splitlines():
            line = line.strip()
            if not line.startswith("|"):
                continue
            if "---" in line:
                found_sep = True
                continue
            if not found_sep:
                continue

            cols = [c.strip() for c in line.split("|")[1:-1]]
            if len(cols) >= 2:
                f = FollowUpItem(
                    item_title=cols[0],
                    responsible_person=cols[1] if len(cols) > 1 else "",
                    expected_outcome=cols[2] if len(cols) > 2 else ""
                )
                followups.append(f)
        return followups


# ==============================================================================
# Word 樣式管理器 (Single Responsibility: Styling & Formatting)
# ==============================================================================

class NotesStyleManager:
    """商務會議記錄樣式管理器"""

    # 色彩定義 (優雅高階商務色調)
    COLOR_PRIMARY_NAVY = RGBColor(30, 60, 110)    # #1E3C6E 主標深藍
    COLOR_SECONDARY_BLUE = RGBColor(40, 80, 140)  # #28508C 次標藍
    COLOR_ACCENT_BLUE = RGBColor(50, 100, 160)    # #3264A0
    COLOR_TEXT_MAIN = RGBColor(45, 55, 72)        # #2D3748 深灰黑內文
    COLOR_MUTED_GRAY = RGBColor(113, 128, 150)    # #718096 輔助文字
    COLOR_HIGHLIGHT_GOLD = RGBColor(180, 110, 20) # #B46E14 重點追蹤金色

    HEX_PRIMARY_NAVY = "1E3C6E"
    HEX_LIGHT_BLUE_BG = "EBF2FA"
    HEX_ALT_ROW_BG = "F7FAFC"
    HEX_CALLOUT_BORDER = "3264A0"

    @staticmethod
    def set_font_run(run, size_pt: float = 12, bold: bool = False, color_rgb: Optional[RGBColor] = None,
                     font_chinese: str = "Noto Sans TC", font_ascii: str = "Calibri"):
        """統一設定文字樣式與中英文字型"""
        run.font.name = font_ascii
        run.font.size = Pt(size_pt)
        run.font.bold = bold
        if color_rgb:
            run.font.color.rgb = color_rgb

        rPr = run._r.get_or_add_rPr()
        rFonts = OxmlElement('w:rFonts')
        rFonts.set(qn('w:ascii'), font_ascii)
        rFonts.set(qn('w:hAnsi'), font_ascii)
        rFonts.set(qn('w:eastAsia'), font_chinese)
        rPr.append(rFonts)

    @staticmethod
    def add_heading(doc: docx.Document, text: str, level: int) -> docx.text.paragraph.Paragraph:
        """依商務規格加入結構化標題"""
        p = doc.add_paragraph()
        run = p.add_run(text)

        if level == 1:
            NotesStyleManager.set_font_run(run, size_pt=26, bold=True, color_rgb=NotesStyleManager.COLOR_PRIMARY_NAVY)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_before = Pt(20)
            p.paragraph_format.space_after = Pt(12)
        elif level == 2:
            NotesStyleManager.set_font_run(run, size_pt=18, bold=True, color_rgb=NotesStyleManager.COLOR_SECONDARY_BLUE)
            p.paragraph_format.space_before = Pt(16)
            p.paragraph_format.space_after = Pt(8)
        elif level == 3:
            NotesStyleManager.set_font_run(run, size_pt=14, bold=True, color_rgb=NotesStyleManager.COLOR_ACCENT_BLUE)
            p.paragraph_format.space_before = Pt(12)
            p.paragraph_format.space_after = Pt(6)

        return p

    @staticmethod
    def style_table_header(row, bg_hex: str = HEX_PRIMARY_NAVY):
        """格式化表格標題列（深色背景、白色粗體文字）"""
        for cell in row.cells:
            tcPr = cell._tc.get_or_add_tcPr()
            shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{bg_hex}"/>')
            tcPr.append(shd)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

            for p in cell.paragraphs:
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.paragraph_format.space_before = Pt(4)
                p.paragraph_format.space_after = Pt(4)
                for run in p.runs:
                    NotesStyleManager.set_font_run(run, size_pt=10.5, bold=True, color_rgb=RGBColor(255, 255, 255))

    @staticmethod
    def set_cell_background(cell, bg_hex: str):
        """設定單元格底色"""
        tcPr = cell._tc.get_or_add_tcPr()
        shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{bg_hex}"/>')
        tcPr.append(shd)


# ==============================================================================
# Word 建構器 (Single Responsibility: Assembling Document Structure)
# ==============================================================================

class NotesDocxBuilder:
    """商務會議記錄 Word 建構器 (嚴格保證零截圖嵌入)"""

    def __init__(self, data: MeetingNotesData):
        self.data = data
        self.doc = docx.Document()
        self._setup_page_margins()

    def _setup_page_margins(self):
        """設定標準 1 吋邊界"""
        for section in self.doc.sections:
            section.top_margin = Inches(1.0)
            section.bottom_margin = Inches(1.0)
            section.left_margin = Inches(1.0)
            section.right_margin = Inches(1.0)

    def build(self) -> docx.Document:
        """組裝並回傳完整的會議記錄 Word 文件"""
        # 1. 會議大標題
        NotesStyleManager.add_heading(self.doc, self.data.title, level=1)

        # 2. 全域參數宣告 (YAML Parameters)
        self._build_yaml_section()

        # 3. 會議基本資訊 (卡片式表格)
        self._build_basic_info_table()

        # 4. 會議核心摘要 (Highlights)
        self._build_highlights_section()

        # 5. 關鍵決策事項 (Decisions Made)
        self._build_decisions_table()

        # 6. 待辦事項清單 (Action Items / Todo List)
        self._build_todos_table()

        # 7. 各議題討論紀要 (Agenda & Discussions)
        self._build_discussions_section()

        # 8. 下次會議追蹤項目 (Next Meeting Follow-ups - 專屬高亮區塊)
        self._build_next_followups_table()

        # 9. 參考資料 (文末影片來源)
        self._build_references_section()

        return self.doc

    def _build_yaml_section(self):
        """輸出 YAML frontmatter 卡片區塊"""
        if not self.data.parameters_yaml:
            return

        NotesStyleManager.add_heading(self.doc, "全域參數宣告 (YAML Parameters)", level=2)
        t_yaml = self.doc.add_table(rows=1, cols=1)
        t_yaml.alignment = WD_TABLE_ALIGNMENT.CENTER
        cell = t_yaml.cell(0, 0)
        NotesStyleManager.set_cell_background(cell, "F8F9FA")

        p_y = cell.paragraphs[0]
        p_y.paragraph_format.space_before = Pt(4)
        p_y.paragraph_format.space_after = Pt(4)
        r_y = p_y.add_run(self.data.parameters_yaml)
        NotesStyleManager.set_font_run(r_y, size_pt=9.5, color_rgb=RGBColor(80, 90, 100), font_ascii="Consolas")

    def _build_basic_info_table(self):
        """輸出會議基本資訊表格"""
        NotesStyleManager.add_heading(self.doc, "一、會議基本資訊", level=2)

        info_rows = [
            ("會議時間", self.data.meeting_time or self.data.meeting_date or "依通知"),
            ("會議地點", self.data.location or "視訊連線 (Teams / Meet)"),
            ("會議主席", self.data.chairperson or "專案主管"),
            ("會議記錄", self.data.minute_taker or "行政秘書"),
            ("出席人員", "、".join(self.data.attendees) if self.data.attendees else "相關專案團隊成員"),
        ]
        if self.data.absentees:
            info_rows.append(("請假人員", "、".join(self.data.absentees)))

        tbl = self.doc.add_table(rows=len(info_rows), cols=2)
        tbl.alignment = WD_TABLE_ALIGNMENT.CENTER

        col_widths = [Inches(1.8), Inches(4.7)]
        for i, (k, v) in enumerate(info_rows):
            cell_k = tbl.cell(i, 0)
            cell_v = tbl.cell(i, 1)

            cell_k.width = col_widths[0]
            cell_v.width = col_widths[1]

            NotesStyleManager.set_cell_background(cell_k, NotesStyleManager.HEX_LIGHT_BLUE_BG)
            if i % 2 == 1:
                NotesStyleManager.set_cell_background(cell_v, NotesStyleManager.HEX_ALT_ROW_BG)

            p_k = cell_k.paragraphs[0]
            r_k = p_k.add_run(k)
            NotesStyleManager.set_font_run(r_k, size_pt=10.5, bold=True, color_rgb=NotesStyleManager.COLOR_PRIMARY_NAVY)

            p_v = cell_v.paragraphs[0]
            r_v = p_v.add_run(v)
            NotesStyleManager.set_font_run(r_v, size_pt=10.5, color_rgb=NotesStyleManager.COLOR_TEXT_MAIN)

        p_space = self.doc.add_paragraph()
        p_space.paragraph_format.space_before = Pt(4)

    def _build_highlights_section(self):
        """輸出核心摘要"""
        if not self.data.highlights:
            return

        NotesStyleManager.add_heading(self.doc, "二、會議核心摘要 (Highlights)", level=2)
        for hl in self.data.highlights:
            p = self.doc.add_paragraph()
            p.paragraph_format.left_indent = Inches(0.2)
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(4)

            bullet_run = p.add_run("◆ ")
            NotesStyleManager.set_font_run(bullet_run, size_pt=11, bold=True, color_rgb=NotesStyleManager.COLOR_ACCENT_BLUE)

            text_run = p.add_run(hl)
            NotesStyleManager.set_font_run(text_run, size_pt=11, color_rgb=NotesStyleManager.COLOR_TEXT_MAIN)

    def _build_decisions_table(self):
        """輸出關鍵決策表格"""
        NotesStyleManager.add_heading(self.doc, "三、關鍵決策事項 (Decisions Made)", level=2)

        if not self.data.decisions:
            p = self.doc.add_paragraph()
            r = p.add_run("本會議主要為資訊同步與現況對齊，無新增具體表決或授權之決策事項。")
            NotesStyleManager.set_font_run(r, size_pt=10.5, color_rgb=NotesStyleManager.COLOR_MUTED_GRAY)
            return

        tbl = self.doc.add_table(rows=len(self.data.decisions) + 1, cols=5)
        tbl.alignment = WD_TABLE_ALIGNMENT.CENTER

        headers = ["編號", "決策主題", "決策內容與共識", "負責人", "生效日期"]
        col_widths = [Inches(0.9), Inches(1.5), Inches(2.5), Inches(0.9), Inches(1.0)]

        # 標題列
        for col_idx, h_text in enumerate(headers):
            cell = tbl.cell(0, col_idx)
            cell.width = col_widths[col_idx]
            cell.paragraphs[0].text = h_text
        NotesStyleManager.style_table_header(tbl.rows[0])

        # 資料列
        for row_idx, d in enumerate(self.data.decisions, start=1):
            row = tbl.rows[row_idx]
            vals = [d.id or f"D-{row_idx:02d}", d.topic, d.decision_content, d.owner_or_proposer, d.effective_date]
            for col_idx, val in enumerate(vals):
                cell = row.cells[col_idx]
                cell.width = col_widths[col_idx]
                if row_idx % 2 == 0:
                    NotesStyleManager.set_cell_background(cell, NotesStyleManager.HEX_ALT_ROW_BG)

                p = cell.paragraphs[0]
                p.paragraph_format.space_before = Pt(4)
                p.paragraph_format.space_after = Pt(4)
                r = p.add_run(val)
                NotesStyleManager.set_font_run(r, size_pt=10, color_rgb=NotesStyleManager.COLOR_TEXT_MAIN)
                if col_idx in [0, 3, 4]:
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER

        p_space = self.doc.add_paragraph()
        p_space.paragraph_format.space_before = Pt(4)

    def _build_todos_table(self):
        """輸出待辦事項清單 (含核取方塊符號 ☐)"""
        NotesStyleManager.add_heading(self.doc, "四、待辦事項清單 (Action Items / Todo List)", level=2)

        if not self.data.todos:
            p = self.doc.add_paragraph()
            r = p.add_run("本會議無新增之待辦追蹤事項。")
            NotesStyleManager.set_font_run(r, size_pt=10.5, color_rgb=NotesStyleManager.COLOR_MUTED_GRAY)
            return

        tbl = self.doc.add_table(rows=len(self.data.todos) + 1, cols=4)
        tbl.alignment = WD_TABLE_ALIGNMENT.CENTER

        headers = ["待辦任務項目 (Action Item)", "負責人", "截止期限", "當前狀態"]
        col_widths = [Inches(3.6), Inches(1.1), Inches(1.1), Inches(1.0)]

        for col_idx, h_text in enumerate(headers):
            cell = tbl.cell(0, col_idx)
            cell.width = col_widths[col_idx]
            cell.paragraphs[0].text = h_text
        NotesStyleManager.style_table_header(tbl.rows[0])

        for row_idx, t in enumerate(self.data.todos, start=1):
            row = tbl.rows[row_idx]
            if row_idx % 2 == 0:
                for c in row.cells:
                    NotesStyleManager.set_cell_background(c, NotesStyleManager.HEX_ALT_ROW_BG)

            # Task 欄位加上 ☐ 核取方塊
            c_task = row.cells[0]
            c_task.width = col_widths[0]
            p_task = c_task.paragraphs[0]
            p_task.paragraph_format.space_before = Pt(4)
            p_task.paragraph_format.space_after = Pt(4)
            r_box = p_task.add_run("☐ ")
            NotesStyleManager.set_font_run(r_box, size_pt=11, bold=True, color_rgb=NotesStyleManager.COLOR_SECONDARY_BLUE)
            r_t = p_task.add_run(t.task)
            NotesStyleManager.set_font_run(r_t, size_pt=10, color_rgb=NotesStyleManager.COLOR_TEXT_MAIN)

            # 負責人
            c_owner = row.cells[1]
            c_owner.width = col_widths[1]
            p_owner = c_owner.paragraphs[0]
            p_owner.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p_owner.paragraph_format.space_before = Pt(4)
            p_owner.paragraph_format.space_after = Pt(4)
            r_o = p_owner.add_run(t.owner)
            NotesStyleManager.set_font_run(r_o, size_pt=10, bold=True, color_rgb=NotesStyleManager.COLOR_PRIMARY_NAVY)

            # 截止日
            c_due = row.cells[2]
            c_due.width = col_widths[2]
            p_due = c_due.paragraphs[0]
            p_due.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p_due.paragraph_format.space_before = Pt(4)
            p_due.paragraph_format.space_after = Pt(4)
            r_d = p_due.add_run(t.due_date)
            NotesStyleManager.set_font_run(r_d, size_pt=10, color_rgb=NotesStyleManager.COLOR_TEXT_MAIN)

            # 狀態
            c_stat = row.cells[3]
            c_stat.width = col_widths[3]
            p_stat = c_stat.paragraphs[0]
            p_stat.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p_stat.paragraph_format.space_before = Pt(4)
            p_stat.paragraph_format.space_after = Pt(4)
            r_s = p_stat.add_run(t.status)
            NotesStyleManager.set_font_run(r_s, size_pt=9.5, color_rgb=NotesStyleManager.COLOR_MUTED_GRAY)

        p_space = self.doc.add_paragraph()
        p_space.paragraph_format.space_before = Pt(4)

    def _build_discussions_section(self):
        """輸出各議題討論紀要與發言人標記"""
        if not self.data.agenda_discussions:
            return

        NotesStyleManager.add_heading(self.doc, "五、各議題討論紀要 (Agenda & Discussions)", level=2)

        for sec in self.data.agenda_discussions:
            NotesStyleManager.add_heading(self.doc, sec.topic_title, level=3)

            for d in sec.discussions:
                p = self.doc.add_paragraph()
                p.paragraph_format.left_indent = Inches(0.2)
                p.paragraph_format.space_before = Pt(2)
                p.paragraph_format.space_after = Pt(4)

                # 發言人姓名醒目標籤
                r_spk = p.add_run(f"【{d.speaker_name}】 ")
                NotesStyleManager.set_font_run(r_spk, size_pt=10.5, bold=True, color_rgb=NotesStyleManager.COLOR_SECONDARY_BLUE)

                # 發言內容要點
                r_stmt = p.add_run(d.statement_summary)
                NotesStyleManager.set_font_run(r_stmt, size_pt=10.5, color_rgb=NotesStyleManager.COLOR_TEXT_MAIN)

        p_space = self.doc.add_paragraph()
        p_space.paragraph_format.space_before = Pt(4)

    def _build_next_followups_table(self):
        """輸出下次會議追蹤項目 (重點 Highlight 表格)"""
        NotesStyleManager.add_heading(self.doc, "六、下次會議追蹤項目 (Next Meeting Follow-ups)", level=2)

        if not self.data.next_meeting_followups:
            p = self.doc.add_paragraph()
            r = p.add_run("本會議無特別約定於下次會議專題報告或檢核之追蹤事項。")
            NotesStyleManager.set_font_run(r, size_pt=10.5, color_rgb=NotesStyleManager.COLOR_MUTED_GRAY)
            return

        # 說明提示
        p_tip = self.doc.add_paragraph()
        r_tip = p_tip.add_run("※ 以下項目列為下次會議開場之重點 Highlight 檢核項目，請各負責人備妥對應成果：")
        NotesStyleManager.set_font_run(r_tip, size_pt=10, bold=True, color_rgb=NotesStyleManager.COLOR_HIGHLIGHT_GOLD)

        tbl = self.doc.add_table(rows=len(self.data.next_meeting_followups) + 1, cols=3)
        tbl.alignment = WD_TABLE_ALIGNMENT.CENTER

        headers = ["追蹤事項 (Focus Item)", "預計報告人 / 負責人", "期望產出 / 查核標準 (Deliverable)"]
        col_widths = [Inches(2.7), Inches(1.5), Inches(2.6)]

        for col_idx, h_text in enumerate(headers):
            cell = tbl.cell(0, col_idx)
            cell.width = col_widths[col_idx]
            cell.paragraphs[0].text = h_text
        NotesStyleManager.style_table_header(tbl.rows[0], bg_hex="28508C")

        for row_idx, f in enumerate(self.data.next_meeting_followups, start=1):
            row = tbl.rows[row_idx]
            if row_idx % 2 == 0:
                for c in row.cells:
                    NotesStyleManager.set_cell_background(c, NotesStyleManager.HEX_ALT_ROW_BG)

            # 項目
            c_item = row.cells[0]
            c_item.width = col_widths[0]
            p_item = c_item.paragraphs[0]
            p_item.paragraph_format.space_before = Pt(4)
            p_item.paragraph_format.space_after = Pt(4)
            r_it = p_item.add_run(f.item_title)
            NotesStyleManager.set_font_run(r_it, size_pt=10, bold=True, color_rgb=NotesStyleManager.COLOR_TEXT_MAIN)

            # 報告人
            c_resp = row.cells[1]
            c_resp.width = col_widths[1]
            p_resp = c_resp.paragraphs[0]
            p_resp.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p_resp.paragraph_format.space_before = Pt(4)
            p_resp.paragraph_format.space_after = Pt(4)
            r_rp = p_resp.add_run(f.responsible_person)
            NotesStyleManager.set_font_run(r_rp, size_pt=10, bold=True, color_rgb=NotesStyleManager.COLOR_PRIMARY_NAVY)

            # 期望成果
            c_out = row.cells[2]
            c_out.width = col_widths[2]
            p_out = c_out.paragraphs[0]
            p_out.paragraph_format.space_before = Pt(4)
            p_out.paragraph_format.space_after = Pt(4)
            r_ot = p_out.add_run(f.expected_outcome)
            NotesStyleManager.set_font_run(r_ot, size_pt=10, color_rgb=NotesStyleManager.COLOR_TEXT_MAIN)

        p_space = self.doc.add_paragraph()
        p_space.paragraph_format.space_before = Pt(4)

    def _build_references_section(self):
        """輸出文末參考資料（影片來源）"""
        if not self.data.references:
            return

        NotesStyleManager.add_heading(self.doc, "參考資料", level=2)
        for ref in self.data.references:
            p = self.doc.add_paragraph()
            p.paragraph_format.left_indent = Inches(0.2)
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(2)
            r = p.add_run(ref)
            NotesStyleManager.set_font_run(r, size_pt=10, color_rgb=NotesStyleManager.COLOR_MUTED_GRAY, font_ascii="Consolas")


# ==============================================================================
# CLI 主程式與執行流程
# ==============================================================================

def main():
    """主程式進入點"""
    # Windows 控制台編碼防護 (防範 cp950 UnicodeEncodeError)
    if sys.platform == "win32":
        import io
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="視訊會議轉高階會議記錄 Word 自動生成工具")
    parser.add_argument("--input", "-i", required=True, help="輸入之結構化會議 Markdown 檔案路徑")
    parser.add_argument("--output", "-o", default=None, help="輸出的 Word (.docx) 檔案路徑")

    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"錯誤：找不到輸入檔案 {input_path}")
        sys.exit(1)

    # 決定輸出路徑
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.with_suffix(".docx")

    print(f"[*] 讀取會議記錄 Markdown: {input_path}")
    with open(input_path, "r", encoding="utf-8") as f:
        md_text = f.read()

    print("[*] 解析會議結構 (YAML frontmatter, Highlights, Decisions, Todos, Agenda, Next Follow-ups)...")
    data = MeetingNotesParser.parse(md_text)

    print(f"[*] 解析完成：會議主題「{data.title}」")
    print(f"    - 核心摘要: {len(data.highlights)} 條")
    print(f"    - 關鍵決策: {len(data.decisions)} 項")
    print(f"    - 待辦事項: {len(data.todos)} 項")
    print(f"    - 議題討論: {len(data.agenda_discussions)} 組")
    print(f"    - 下次追蹤: {len(data.next_meeting_followups)} 項")

    print("[*] 建構純淨高階商務 Word 文件 (保證 0 截圖嵌入)...")
    builder = NotesDocxBuilder(data)
    doc = builder.build()

    # 檔案寫入與防鎖定保護
    try:
        doc.save(str(output_path))
        print(f"[OK] 成功產出商務會議記錄 Word 文件：{output_path.resolve()}")
    except PermissionError:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fallback_path = output_path.with_name(f"{output_path.stem}_{ts}.docx")
        print(f"[!] 警告：目標檔案 {output_path} 遭鎖定（可能正在 Word 中開啟）。")
        print(f"[*] 自動回退儲存至：{fallback_path}")
        doc.save(str(fallback_path))
        print(f"[OK] 成功產出備用會議記錄 Word 文件：{fallback_path.resolve()}")


if __name__ == "__main__":
    main()
