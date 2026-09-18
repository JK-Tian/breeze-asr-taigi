"""KM Wiki 企業知識庫 Minutes raw 檔區同步服務模組。

本模組提供針對企業 KM Wiki (Minutes 知識庫 raw 檔區) 的自動歸檔與同步服務：
1. 支援自動按日期 YYYY-MM-DD 建立層級目錄。
2. 完整複製校正逐字稿 (.md) 與 Obsidian PKM 會議記錄 (.md)。
3. 防範檔名路徑遍歷與特殊字元注入攻擊。
4. 具備平滑降級容錯 (Graceful Degradation)：當目標網路硬碟離線或無寫入權限時，捕捉例外記錄警告，不中斷主流程。
"""

from __future__ import annotations

import configparser
from datetime import datetime
import logging
import os
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional

from taigi_asr.minutes import sanitize_filename

logger = logging.getLogger(__name__)

DEFAULT_KM_WIKI_RAW_DIR = "D:/km_wiki/Minutes/raw"


class KMWikiService:
    """KM Wiki Minutes 知識庫 raw 檔區同步服務實體。"""

    def __init__(
        self,
        enabled: Optional[bool] = None,
        raw_dir: Optional[str] = None,
        date_subfolder: Optional[bool] = None,
    ) -> None:
        """初始化 KM Wiki 同步服務實例。

        優先順序：顯式傳遞參數 > 環境變數 > config.ini > 程式碼預設值。

        Args:
            enabled: 是否啟用 KM Wiki 同步。
            raw_dir: 目標 Minutes 知識庫 raw 檔區路徑。
            date_subfolder: 是否依 YYYY-MM-DD 建立子目錄。
        """
        cfg_enabled, cfg_raw_dir, cfg_date_subfolder = self._load_config()

        # 1. 決定 enabled
        if enabled is not None:
            self.enabled = enabled
        elif "KM_WIKI_ENABLED" in os.environ:
            self.enabled = os.environ["KM_WIKI_ENABLED"].lower() in ("true", "1", "yes")
        elif cfg_enabled is not None:
            self.enabled = cfg_enabled
        else:
            self.enabled = True

        # 2. 決定 raw_dir
        if raw_dir is not None:
            self.raw_dir = raw_dir
        elif "KM_WIKI_RAW_DIR" in os.environ:
            self.raw_dir = os.environ["KM_WIKI_RAW_DIR"]
        elif cfg_raw_dir is not None:
            self.raw_dir = cfg_raw_dir
        else:
            self.raw_dir = DEFAULT_KM_WIKI_RAW_DIR

        # 3. 決定 date_subfolder
        if date_subfolder is not None:
            self.date_subfolder = date_subfolder
        elif "KM_WIKI_DATE_SUBFOLDER" in os.environ:
            self.date_subfolder = os.environ["KM_WIKI_DATE_SUBFOLDER"].lower() in ("true", "1", "yes")
        elif cfg_date_subfolder is not None:
            self.date_subfolder = cfg_date_subfolder
        else:
            self.date_subfolder = True

    @staticmethod
    def _load_config() -> tuple[Optional[bool], Optional[str], Optional[bool]]:
        """自專案根目錄 config.ini 讀取 [KMWiki] 預設值。"""
        try:
            config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../config.ini"))
            if os.path.exists(config_path):
                parser = configparser.ConfigParser()
                parser.read(config_path, encoding="utf-8")
                if "KMWiki" in parser:
                    km_cfg = parser["KMWiki"]
                    enabled = km_cfg.getboolean("enabled", fallback=None)
                    raw_dir = km_cfg.get("raw_dir", fallback=None)
                    date_subfolder = km_cfg.getboolean("date_subfolder", fallback=None)
                    return enabled, raw_dir, date_subfolder
        except Exception as exc:
            logger.debug(f"讀取 config.ini [KMWiki] 忽略: {exc}")
        return None, None, None

    def get_target_dir(self, dt: Optional[datetime] = None) -> Path:
        """解析目標目錄路徑，支援日期子資料夾。

        Args:
            dt: 指定會議日期時間，預設為當前時間。

        Returns:
            Path 目標資料夾物件。
        """
        base_path = Path(self.raw_dir)
        if self.date_subfolder:
            date_str = (dt or datetime.now()).strftime("%Y-%m-%d")
            return base_path / date_str
        return base_path

    def sync_files(
        self,
        transcript_path: Path | str,
        summary_path: Path | str,
        dt: Optional[datetime] = None,
        override_title: Optional[str] = None,
    ) -> Dict[str, Any]:
        """將逐字稿與會議記錄檔案安全同步至 KM Wiki Minutes raw 檔區。

        Args:
            transcript_path: 本地已產生之逐字稿檔案路徑。
            summary_path: 本地已產生之會議記錄檔案路徑。
            dt: 會議日期時間。
            override_title: 可選的覆蓋會議名稱（自動消毒）。

        Returns:
            包含 synced(bool), target_dir, synced_files, error 的字典。
        """
        if not self.enabled:
            logger.info("KM Wiki 同步未啟用 (enabled=false)，略過同步。")
            return {"synced": False, "reason": "disabled", "synced_files": []}

        t_src = Path(transcript_path)
        s_src = Path(summary_path)

        if not t_src.exists() and not s_src.exists():
            logger.warning("KM Wiki 同步失敗：來源檔案皆不存在。")
            return {"synced": False, "error": "來源檔案不存在", "synced_files": []}

        try:
            target_dir = self.get_target_dir(dt)
            target_dir.mkdir(parents=True, exist_ok=True)

            # 檔名消毒與路徑注入防護
            if override_title:
                clean_name = sanitize_filename(override_title) or "會議筆記"
                t_dest_name = f"{clean_name}_逐字稿.md"
                s_dest_name = f"{clean_name}_會議紀錄與摘要.md"
            else:
                t_dest_name = sanitize_filename(t_src.name) or t_src.name
                s_dest_name = sanitize_filename(s_src.name) or s_src.name

            synced_paths: List[str] = []

            # 安全複製逐字稿
            if t_src.exists():
                t_dest = target_dir / t_dest_name
                shutil.copy2(t_src, t_dest)
                synced_paths.append(str(t_dest))
                logger.info(f"逐字稿成功同步至 KM Wiki: {t_dest}")

            # 安全複製會議紀錄
            if s_src.exists():
                s_dest = target_dir / s_dest_name
                shutil.copy2(s_src, s_dest)
                synced_paths.append(str(s_dest))
                logger.info(f"會議記錄成功同步至 KM Wiki: {s_dest}")

            return {
                "synced": True,
                "target_dir": str(target_dir),
                "synced_files": synced_paths,
            }

        except Exception as exc:
            # 平滑降級：捕捉所有 I/O、權限或網路硬碟離線例外，絕不拋出崩潰
            logger.warning(f"KM Wiki 同步失敗 (平滑降級，主流程維持正常): {exc}")
            return {
                "synced": False,
                "error": str(exc),
                "synced_files": [],
            }

    def check_status(self) -> Dict[str, Any]:
        """檢驗 KM Wiki Minutes raw 檔區目錄可用性與寫入權限。

        Returns:
            狀態字典。
        """
        raw_path = Path(self.raw_dir)
        is_writable = False

        if self.enabled:
            try:
                raw_path.mkdir(parents=True, exist_ok=True)
                test_file = raw_path / ".km_wiki_probe"
                test_file.write_text("probe", encoding="utf-8")
                test_file.unlink()
                is_writable = True
            except Exception as e:
                logger.debug(f"KM Wiki probe failed: {e}")
                is_writable = False

        return {
            "enabled": self.enabled,
            "raw_dir": self.raw_dir,
            "date_subfolder": self.date_subfolder,
            "is_writable": is_writable,
        }
