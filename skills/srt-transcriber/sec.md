# 資安與語音隱私防護政策 (Security and Audio Privacy Policies)

## 1. 離線本地處理原則 (Local-First Processing)
- **零雲端上傳**：本技能處理之音訊與影片檔案可能涉及商業機密、會議錄音或產線專屬操作細節。所有語音辨識模型（包含 `faster-whisper` 多國語言權重與繁中/台語特化權重）**必須**在本地端設備進行推論，嚴禁上傳至外部未授權之公有雲端 ASR 服務。
- **金鑰與憑證管理**：代碼中 **MUST NOT** 包含任何寫死之 API Key 或敏感個人憑證。

## 2. 模型權重快取與防偽 (Model Integrity)
- **安全快取路徑**：模型權重下載後預設存放在 Hugging Face 官方或系統安全快取目錄中，禁止任意在未授權位置載入不可信任之第三方二進位執行檔。
- **安全 subprocess 調用**：若需透過系統工具抽取音軌，參數傳遞 **MUST NOT** 使用 `shell=True`，全面防範命令列注入 (Command Injection) 攻擊。

## 3. 輸出檔案安全與生命週期 (File Sanitization)
- **路徑防護**：輸出之字幕檔 (`.srt`, `.vtt`, `.txt`, `.json`) 僅限寫入使用者指定或影音來源目錄，嚴格驗證防止目錄周遊 (Directory Traversal)。
- **套件版本鎖定**：核心推論套件 (`faster-whisper`, `pytest`) 統一由 `uv` 進行依賴鎖定與虛擬環境隔離。
