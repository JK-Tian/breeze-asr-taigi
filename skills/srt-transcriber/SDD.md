# 系統設計文件 (System Design Document - SDD)
## 專案名稱：SRT Transcriber 旗艦版 (三合一整合影音轉逐字稿技能)

---

## 1. 系統脈絡與架構選型 (System Context & Architecture)

### 1.1 系統脈絡圖 (System Context Diagram)
```mermaid
flowchart LR
    User[使用者 / Agent 技能] -->|提供影音檔案與參數| SrtTranscriber["SRT Transcriber 旗艦技能\n(.agent/skills/srt-transcriber)"]
    
    subgraph CoreEngine["推論與格式化核心"]
        SrtTranscriber --> Validator["媒體格式驗證器\n(AudioValidator)"]
        Validator --> DeviceDetector["硬體環境偵測與降級策略\n(CUDA / CPU Fallback)"]
        DeviceDetector --> PromptEngine["繁中/台語專用語意引導\n(Prompt Injection)"]
        PromptEngine --> Inference["Faster-Whisper (CTranslate2)\n語音轉錄引擎"]
        Inference --> Formatter["多格式封裝器\n(SRT / VTT / TXT / JSON)"]
    end
    
    Formatter --> OutFiles[("字幕逐字稿檔案\n(.srt / .vtt / .txt / .json)")]
    OutFiles --> User
```

### 1.2 技術選型與決策矩陣
| 維度 | 選型方案 | 優勢與架構考量 |
|---|---|---|
| **核心台語/繁中模型** | **MediaTek Breeze-ASR-26** (`paulpengtw/faster-whisper-Breeze-ASR-26-ct2`) | 聯發創新基地 (MediaTek Research) 專為台灣華語口音、中英混用與台語 (Taigi) 深度調校的旗艦模型，台語與繁中辨識率顯著優於通用 Whisper。 |
| **通用多國語言模型** | `large-v3` / `medium` (OpenAI Whisper) | 支援 90+ 種語言自動偵測，可透過 `--model` 自由指定切換。 |
| **推論加速引擎** | `faster-whisper` (CTranslate2) | 效能較原生 PyTorch 提升 4 倍以上，記憶體佔用降低 50% 以上，相容 RTX 3050 4GB VRAM 與 CPU int8。 |
| **繁中/台語支援** | 專屬 Prompt 注入 + `zh-TW` 映射至 `zh` | 將常見台語詞彙（如「調機」、「夾爪」、「巡檢」）與繁體中文規範透過 Initial Prompt 傳入，有效壓制簡體字與同音雜訊。 |
| **套件管理** | `uv` (Windows 11) | 極速安裝、隔離環境、零跨專案污染。 |

---

## 2. 關鍵流程時序圖 (Sequence Diagram)

```mermaid
sequenceDiagram
    autonumber
    actor Caller as 呼叫端 (Agent / User)
    participant CLI as scripts/transcribe.py
    participant Val as AudioValidator
    participant Dev as DeviceDetector
    participant FW as WhisperModel (faster-whisper)
    participant Fmt as SubtitleFormatter
    participant Disk as 本地磁碟

    Caller->>CLI: 執行轉寫指令 (傳入影片路徑與參數)
    CLI->>Val: 驗證檔案路徑與副檔名
    Val-->>CLI: 驗證合法通過
    CLI->>Dev: 檢測可用運算裝置 (CUDA / CPU)
    Dev-->>CLI: 回傳最適裝置與計算精度 (如 cuda+float16 或 cpu+int8)
    CLI->>FW: 初始化模型權重並配置 VAD 與繁中/台語 Prompt
    FW->>FW: 執行音訊分段推論 (Transcribe)
    FW-->>CLI: 產生轉錄片段迭代器 (Segments)
    CLI->>Fmt: 依指定格式 (SRT/VTT/TXT/JSON) 轉換時間戳與文本
    Fmt->>Disk: 寫入目標字幕檔案 (UTF-8 編碼)
    Disk-->>Caller: 產出完成回報
```

---

## 3. 類別設計架構 (Class Diagram - S.O.L.I.D.)

```mermaid
classDiagram
    class AudioValidator {
        +Set~str~ SUPPORTED_EXTS
        +validate_path(path: Path) bool
        +scan_directory(dir_path: Path) List~Path~
    }

    class TimestampFormatter {
        +to_srt(seconds: float) str
        +to_vtt(seconds: float) str
    }

    class SubtitleFormatter {
        +to_srt_string(segments, max_words) str
        +to_vtt_string(segments) str
        +to_txt_string(segments) str
        +to_json_string(segments, info) str
    }

    class TranscribeEngine {
        -model_name: str
        -device: str
        -compute_type: str
        -model: WhisperModel
        +load_model()
        +transcribe(audio_path, language, initial_prompt, vad_filter) tuple
        -_resolve_hardware() tuple
        -_build_zh_prompt(user_prompt, language) str
    }

    class TranscribeApp {
        +run(args)
    }

    TranscribeApp --> AudioValidator : 調用驗證
    TranscribeApp --> TranscribeEngine : 調用推論
    TranscribeApp --> SubtitleFormatter : 調用格式化
    SubtitleFormatter ..> TimestampFormatter : 時間戳轉換
```

---

## 4. 關鍵機制與設計細節

### 4.1 台灣繁中與台語語意引導 (Prompt Injection)
當指定 `--language zh-TW` 或轉錄包含台語內容時，系統自動將語言代碼正規化為 `zh`，並注入預設 Initial Prompt：
> 「這是一段繁體中文與台灣台語對話，包含各項專業工程、機台操作、換模調機、公差規格與品質管理術語，請輸出繁體中文。」

### 4.2 硬體自適應降級策略 (Hardware Fallback)
```mermaid
stateDiagram-v2
    [*] --> DetectCUDA: 檢查 PyTorch CUDA 可用性
    DetectCUDA --> CUDA_Mode: 偵測到 NVIDIA GPU 且支援
    DetectCUDA --> CPU_Mode: 無 GPU 或 CUDA 缺失
    
    state CUDA_Mode {
        [*] --> Float16: 嘗試 float16 推論
        Float16 --> Int8_GPU: 顯存不足 (OOM)
    }
    
    state CPU_Mode {
        [*] --> Int8_CPU: 使用 int8 量化運算 (極低記憶體)
    }
    
    CUDA_Mode --> Success: 推論成功
    CPU_Mode --> Success: 推論成功
```

### 4.3 Windows 控制台編碼防護 (cp950 Protection)
在 Windows 繁體中文環境下，標準控制台輸出預設為 `cp950`，容易在印出特殊 UTF-8 符號時崩潰。
腳本全面於 CLI 入口點配置安全輸出保護，確保跨平臺穩定。
