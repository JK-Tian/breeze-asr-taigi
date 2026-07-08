## Round 1 — 2026-07-04 00:26

**失敗現象**：Celery Worker 報錯 `Received unregistered task of type 'process_audio'.`
**根因分析**：在啟動 Celery Worker 載入 `celery_app.py` 時，並沒有匯入包含任務的模組 (`src.usecases.transcription`)，導致 Celery 不知道該任務的存在。
**嘗試的策略**：在 `celery_app.py` 的 Celery 初始化參數中加入 `include=["src.usecases.transcription"]`。
**結論**：待驗證
**下一步方向**：修改 `celery_app.py` 並重啟 Worker 測試。
