# Video Screenshot (影片截圖工具)

## 介紹
這是一個基於 Python 與系統內建 FFmpeg 的輕量化影片截圖工具，它能以指定的取樣頻率 (預設為 0.5 FPS，即每 2 秒截取 1 張圖) 自動從影片中擷取圖片，並自動存放入與影片同名的資料夾中。

## 系統需求
- Windows 11
- 安裝 [uv](https://github.com/astral-sh/uv) 套件管理工具
- 系統已安裝 `ffmpeg`，並確定其已加入至系統環境變數 PATH 中。

## 使用方式
使用 `uv run` 來執行檔案，程式將管理與建立虛擬環境：
```bash
uv run scripts/screenshot.py path/to/your_video.mp4
```

亦可自訂 FPS，例如設定 1.0 每秒一張：
```bash
uv run scripts/screenshot.py path/to/your_video.mp4 --fps 1.0
```

## 開發原則
專案的設計遵循 S.O.L.I.D. 原則，重點包含拆分介面與實作、具體職責分離，以確保後續的擴充性與易讀性。全部功能具備繁體中文註解。
