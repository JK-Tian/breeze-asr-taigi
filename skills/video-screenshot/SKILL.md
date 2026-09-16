---
name: Video Screenshot
description: This skill should be used when the user wants to "extract screenshots from video", "convert video to images", "sample video frames", "take screenshots every few seconds", or "影片截圖". It provides a script to extract frames from a video at 0.5 FPS using ffmpeg.
version: 0.1.0
---

# Video Screenshot Skill

提供將影片透過 ffmpeg 以指定的 FPS (預設 0.5) 進行截圖的功能，並建立與影片同名的資料夾來儲存圖片。

## 使用方式

請使用 `uv run` 執行此腳本，支援以下兩種模式：

**模式一：按頻率截圖 (預設)**
```bash
uv run scripts/screenshot.py <影片路徑> [--fps 0.5]
```

**模式二：精準時間戳記截圖**
若您已經知道哪些時間點需要截圖，可使用 `--timestamps` 參數傳入（以逗號分隔）。這能大幅節省處理時間與儲存空間。
```bash
uv run scripts/screenshot.py <影片路徑> --timestamps 00:02,00:15,01:30
```

## 資源結構

- `scripts/screenshot.py`: 核心執行腳本
- `README.md`: 專案說明文件
- `sec.md`: 資安與隱私防護說明
- `pyproject.toml`: 專案相依性定義檔

## 執行流程
1. 確認輸入影片存在。
2. 建立與影片同名的資料夾。
3. 呼叫系統指令 `ffmpeg -i <影片> -vf fps=<fps> <資料夾>/%04d.png`。
4. 輸出執行結果。
