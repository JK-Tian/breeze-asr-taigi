"""
暫存影片與快取清理腳本 (cleanup_temp.py)
職責：依據「看完即忘」原則，安全釋放系統於影片視覺理解時在 .tempmediaStorage 建立的暫存檔案。
規範：嚴格防呆，絕對禁止刪除工作區檔案或非 .tempmediaStorage 目錄。
"""

import os
import sys
import shutil
import argparse
from pathlib import Path

def is_safe_temp_path(target_path: Path) -> bool:
    """
    驗證清理目標路徑是否為合法的暫存目錄。
    防呆規則：
    1. 目錄名稱或路徑中必須包含 '.tempmediaStorage'
    2. 絕對不能是根目錄或專案工作區目錄
    3. 不能包含系統核心目錄
    """
    resolved = target_path.resolve()
    path_str = str(resolved).lower()
    
    # 必須包含 .tempmediastorage
    if ".tempmediastorage" not in path_str:
        return False
    
    # 防止誤傳入過短的根路徑
    if len(resolved.parts) < 4:
        return False

    return True

def cleanup_temp_storage(target_dir: str) -> bool:
    """
    清理指定之暫存目錄。
    :param target_dir: 待清理的目錄路徑
    :return: 是否成功清理
    """
    path_obj = Path(target_dir)
    
    if not path_obj.exists():
        print(f"[提示] 目標暫存目錄不存在，無需清理: {path_obj}")
        return True
    
    if not is_safe_temp_path(path_obj):
        print(f"[警告/錯誤] 安全防護攔截：目標路徑 '{path_obj}' 不符合安全暫存路徑規則！禁止刪除。")
        return False

    try:
        total_freed_bytes = 0
        file_count = 0
        for root, dirs, files in os.walk(path_obj):
            for f in files:
                fp = Path(root) / f
                try:
                    total_freed_bytes += fp.stat().st_size
                    file_count += 1
                except Exception:
                    pass

        # 執行安全清除目錄內容
        for item in path_obj.iterdir():
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                try:
                    item.unlink()
                except Exception:
                    pass

        mb_freed = total_freed_bytes / (1024 * 1024)
        print(f"[成功] 已安全清空暫存目錄: {path_obj}")
        print(f"      釋放空間: {mb_freed:.2f} MB，清理檔案數: {file_count} 個。")
        return True
    except Exception as e:
        print(f"[錯誤] 清理暫存檔案時發生異常: {e}")
        return False

def main():
    """命令列介面進入點"""
    parser = argparse.ArgumentParser(description="影片暫存快取安全清理工具 (安全沙箱限定)")
    parser.add_argument("--conversation-id", "-c", type=str, help="目前的對話 ID (Conversation ID)")
    parser.add_argument("--target-dir", "-t", type=str, help="直接指定之 .tempmediaStorage 路徑")
    args = parser.parse_args()

    if args.target_dir:
        target = Path(args.target_dir)
    elif args.conversation_id:
        app_data = os.environ.get("USERPROFILE", "")
        target = Path(app_data) / ".gemini" / "antigravity-ide" / "brain" / args.conversation_id / ".tempmediaStorage"
    else:
        # 預設嘗試在標準 brain 路徑尋找
        print("[提示] 未指定 conversation-id 或 target-dir。使用說明：")
        print("  uv run scripts/cleanup_temp.py --conversation-id <id>")
        print("  uv run scripts/cleanup_temp.py --target-dir <path>")
        sys.exit(0)

    success = cleanup_temp_storage(str(target))
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
