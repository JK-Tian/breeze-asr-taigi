# 進階設定與疑難排解

## GPU 加速設定

### CUDA 設定

使用 NVIDIA GPU 加速轉寫：

```bash
# 安裝 CUDA 版本
uv pip install faster-whisper

# GPU 轉寫
uv run python scripts/transcribe.py "video.mp4" --device cuda --compute-type float16
```

### 計算精度選擇

| 精度 | 裝置 | 速度 | 記憶體 | 適用場景 |
|------|------|------|--------|----------|
| `int8` | CPU / GPU | ★★★★★ | 最低 | CPU 預設，推薦 |
| `float16` | GPU | ★★★★☆ | 中等 | GPU 推薦 |
| `float32` | CPU / GPU | ★★★☆☆ | 最高 | 最高精度需求 |

> **注意**：CPU 模式僅支援 `int8` 和 `float32`，不支援 `float16`。

---

## VAD（語音活動偵測）過濾

VAD 過濾可自動跳過無聲或背景噪音片段，減少幻覺（hallucination）問題：

```bash
# 啟用 VAD
uv run python scripts/transcribe.py "long_meeting.mp4" --vad-filter --language zh
```

### VAD 進階參數（API 呼叫時使用）

```python
from faster_whisper import WhisperModel

model = WhisperModel("medium", device="cpu", compute_type="int8")

segments, info = model.transcribe(
    "audio.mp3",
    vad_filter=True,
    vad_parameters=dict(
        threshold=0.5,           # 語音偵測門檻值（0.0-1.0）
        min_speech_duration_ms=250,  # 最短語音片段（毫秒）
        max_speech_duration_s=float("inf"),  # 最長語音片段（秒）
        min_silence_duration_ms=2000,  # 用於分段的最短靜音（毫秒）
        speech_pad_ms=400,       # 語音片段前後的填充時間（毫秒）
    ),
)
```

---

## 語言代碼列表

### 常用語言

| 代碼 | 語言 |
|------|------|
| `zh` | 中文（含繁體/簡體） |
| `en` | 英文 |
| `ja` | 日文 |
| `ko` | 韓文 |
| `fr` | 法文 |
| `de` | 德文 |
| `es` | 西班牙文 |
| `pt` | 葡萄牙文 |
| `ru` | 俄文 |
| `th` | 泰文 |
| `vi` | 越南文 |

完整支援超過 90 種語言，詳見 [Whisper 語言列表](https://github.com/openai/whisper/blob/main/whisper/tokenizer.py)。

---

## 初始提示詞（Initial Prompt）

初始提示詞可引導模型的轉寫風格，特別適合：

- **專有名詞**：「這是關於 TensorFlow 和 PyTorch 的教學」
- **繁體中文強制**：「以下是繁體中文內容」
- **格式引導**：「請使用正式書面語」

```bash
uv run python scripts/transcribe.py "tech.mp4" \
    --language zh \
    --initial-prompt "這是一場關於機器學習的技術演講，提到 TensorFlow、PyTorch、GPT"
```

---

## 字數分段策略

### 依字數拆分

使用 `--max-words-per-segment` 限制每段字幕的字數：

```bash
# 每段最多 15 個字
uv run python scripts/transcribe.py "video.mp4" --max-words-per-segment 15
```

### 自訂分段（API 呼叫）

```python
from faster_whisper import WhisperModel

model = WhisperModel("medium", device="cpu", compute_type="int8")

# 使用 word_timestamps 取得逐字時間戳
segments, info = model.transcribe(
    "audio.mp3",
    word_timestamps=True,
)

for segment in segments:
    print(f"[{segment.start:.2f} -> {segment.end:.2f}] {segment.text}")
    if segment.words:
        for word in segment.words:
            print(f"  {word.word} ({word.start:.2f} -> {word.end:.2f})")
```

---

## 批次處理

### 處理多個檔案

```python
from pathlib import Path
import sys

# 將 scripts 目錄加入路徑
sys.path.insert(0, str(Path(__file__).parent / "scripts"))
from transcribe import transcribe

# 批次轉寫資料夾中所有影片
input_dir = Path("videos")
for media_file in input_dir.glob("*.mp4"):
    print(f"\n處理：{media_file.name}")
    transcribe(
        input_path=str(media_file),
        model_size="medium",
        language="zh",
        vad_filter=True,
    )
```

---

## 常見問題排解

### Q: 轉寫速度很慢？

- 使用較小的模型（如 `tiny` 或 `base`）
- 啟用 `--vad-filter` 跳過靜音片段
- 使用 `int8` 精度：`--compute-type int8`
- 有 GPU 時加上：`--device cuda --compute-type float16`

### Q: 中文轉寫變成簡體？

- 加上 `--initial-prompt "以下是繁體中文內容"`
- 或使用較大模型（medium 以上）

### Q: 出現重複文字（幻覺）？

- 啟用 VAD 過濾：`--vad-filter`
- 長時間靜音的音訊特別容易出現此問題
- 使用 `--initial-prompt` 提供上下文

### Q: 記憶體不足（OOM）？

- 換用較小模型
- CPU 模式使用 `int8`：`--compute-type int8`
- GPU 模式使用 `float16`：`--compute-type float16`

### Q: SRT 檔案在播放器中顯示亂碼？

- 腳本預設使用 UTF-8 BOM 編碼輸出，相容大多數播放器
- 若仍有問題，確認播放器字幕編碼設定為 UTF-8

### Q: 如何提升轉寫精確度？

1. 使用 `large-v3` 模型
2. 指定正確語言：`--language zh`
3. 提供初始提示詞
4. 確保音訊品質良好（減少背景噪音）
5. 啟用 VAD 過濾

---

## API 直接呼叫範例

### 基本轉寫

```python
from faster_whisper import WhisperModel

model = WhisperModel("medium", device="cpu", compute_type="int8")
segments, info = model.transcribe("audio.mp3", language="zh", beam_size=5)

print(f"偵測語言：{info.language}（{info.language_probability:.2%}）")

for segment in segments:
    print(f"[{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text}")
```

### 逐字時間戳

```python
segments, info = model.transcribe("audio.mp3", word_timestamps=True)

for segment in segments:
    for word in segment.words:
        print(f"{word.word}: {word.start:.3f} -> {word.end:.3f} (p={word.probability:.2f})")
```

### 搭配 VAD 與初始提示詞

```python
segments, info = model.transcribe(
    "meeting.mp4",
    language="zh",
    beam_size=5,
    vad_filter=True,
    initial_prompt="這是公司內部會議的錄音",
    vad_parameters=dict(
        min_silence_duration_ms=1500,
        speech_pad_ms=300,
    ),
)
```
