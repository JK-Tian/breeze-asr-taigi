"use client";

import { useState, useRef, useEffect } from "react";
import { Upload, FileAudio, Loader2, CheckCircle, XCircle, Download, Mic, Square } from "lucide-react";
import axios from "axios";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const getApiBase = () => {
  if (process.env.NEXT_PUBLIC_API_BASE) return process.env.NEXT_PUBLIC_API_BASE;
  if (typeof window !== 'undefined') {
    const { hostname, protocol } = window.location;
    if (protocol === 'https:') {
      return `https://${hostname}:8788/api/v1`;
    }
    return `http://${hostname}:8787/api/v1`;
  }
  return "/api/v1";
};
const API_BASE = getApiBase();

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [status, setStatus] = useState<string>("idle"); // idle, uploading, pending, processing, completed, failed
  const [transcript, setTranscript] = useState<string>("");
  const [summary, setSummary] = useState<string>("");
  const [errorMessage, setErrorMessage] = useState<string>("");
  const [isDragging, setIsDragging] = useState<boolean>(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // 當處理完成且有 taskId 時，直接使用後端提供的音檔網址，避免前端 File Blob 被瀏覽器回收造成破圖/無法播放
  const audioUrl = status === "completed" && taskId ? `${API_BASE}/transcriptions/${taskId}/audio` : "";

  // 錄音相關狀態
  const [isRecording, setIsRecording] = useState<boolean>(false);
  const [recordingTime, setRecordingTime] = useState<number>(0);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    let interval: NodeJS.Timeout;
    if (taskId && (status === "pending" || status === "processing")) {
      interval = setInterval(async () => {
        try {
          const res = await axios.get(`${API_BASE}/transcriptions/${taskId}`);
          setStatus(res.data.status);
          if (res.data.status === "completed") {
            setTranscript(res.data.transcript || "無轉錄結果");
            setSummary(res.data.summary || "無摘要結果");
            clearInterval(interval);
          } else if (res.data.status === "failed") {
            setErrorMessage(res.data.error_message || "處理失敗");
            clearInterval(interval);
          }
        } catch (err) {
          console.error(err);
        }
      }, 5000);
    }
    return () => clearInterval(interval);
  }, [taskId, status]);

  const startRecording = async () => {
    try {
      // 偵錯：確認按鈕有被成功點擊
      console.log("開始請求麥克風...");
      
      // 防呆：如果找不到 mediaDevices API，代表網頁可能不是在安全的 HTTPS 環境下
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        alert("⛔ 錯誤：瀏覽器封鎖了麥克風 API！\n原因可能是您目前沒有使用 HTTPS 安全連線 (例如 ngrok)，或是您的瀏覽器不支援。");
        return;
      }

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;
      chunksRef.current = [];

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
          chunksRef.current.push(e.data);
        }
      };

      mediaRecorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' });
        const now = new Date();
        const timestamp = `${now.getHours()}${now.getMinutes()}${now.getSeconds()}`;
        const recordedFile = new File([blob], `recording_${timestamp}.webm`, { type: 'audio/webm' });
        setFile(recordedFile);
        stream.getTracks().forEach(track => track.stop());
      };

      mediaRecorder.start();
      setIsRecording(true);
      setRecordingTime(0);
      
      timerRef.current = setInterval(() => {
        setRecordingTime(prev => prev + 1);
      }, 1000);
      
    } catch (err: any) {
      console.error("無法存取麥克風", err);
      alert(`⛔ 麥克風存取失敗：\n${err.message || err}\n請確認您是否已授予麥克風權限，或您的電腦是否有連接麥克風。`);
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    }
  };

  const handleUpload = async () => {
    if (!file) return;
    const formData = new FormData();
    formData.append("file", file);

    try {
      setStatus("uploading");
      const res = await axios.post(`${API_BASE}/transcriptions`, formData);
      setTaskId(res.data.id);
      setStatus("pending");
    } catch (err) {
      console.error(err);
      setStatus("failed");
      setErrorMessage("上傳失敗，請確認後端是否運作中。");
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      setFile(e.dataTransfer.files[0]);
    }
  };

  const handleDownload = (filename: string, content: string) => {
    const blob = new Blob([content], { type: "text/markdown;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.setAttribute("download", filename);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <main className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 text-white p-8 font-sans selection:bg-cyan-500/30">
      <div className="max-w-7xl mx-auto space-y-12">
        {/* Header */}
        <div className="text-center space-y-4 pt-12">
          <h1 className="text-5xl font-extrabold tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-cyan-400 to-blue-500">
            Breeze ASR 會議紀錄
          </h1>
          <p className="text-slate-400 text-lg max-w-xl mx-auto">
            上傳您的長音檔，交給聯發科 Breeze ASR 26 進行高精準度的中英台辨識與講者分離，並由 Ollama 自動生成會議摘要。
          </p>
        </div>

        {/* Upload Card */}
        {status === "idle" || status === "uploading" ? (
          <div className="bg-white/5 backdrop-blur-xl border border-white/10 rounded-3xl p-8 shadow-2xl transition-all duration-300 hover:bg-white/10 max-w-4xl mx-auto">
            <div 
              className={`border-2 border-dashed rounded-2xl p-12 text-center cursor-pointer transition-colors ${
                isDragging ? 'border-cyan-400 bg-cyan-400/20' :
                file ? 'border-cyan-500/50 bg-cyan-500/5' : 'border-slate-600 hover:border-slate-400'
              }`}
              onClick={() => fileInputRef.current?.click()}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
            >
              <input 
                type="file" 
                className="w-0 h-0 absolute opacity-0 overflow-hidden" 
                ref={fileInputRef} 
                accept="audio/*"
                onChange={(e) => {
                  if (e.target.files && e.target.files.length > 0) {
                    setFile(e.target.files[0]);
                  }
                }}
              />
              {file ? (
                <div className="flex flex-col items-center space-y-4">
                  <div className="p-4 bg-cyan-500/20 rounded-full text-cyan-400">
                    <FileAudio size={40} />
                  </div>
                  <p className="text-xl font-medium text-cyan-50">{file.name}</p>
                  <p className="text-slate-400 text-sm">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
                </div>
              ) : (
                <div className="flex flex-col items-center space-y-4">
                  <div className="flex items-center justify-center space-x-6">
                    <button
                      onClick={(e) => {
                        e.stopPropagation(); // 避免觸發最外層的點擊上傳
                        isRecording ? stopRecording() : startRecording();
                      }}
                      className={`p-5 rounded-full transition-all duration-300 border-2 ${
                        isRecording 
                        ? 'bg-rose-500/10 border-rose-500 text-rose-500 shadow-[0_0_20px_rgba(244,63,94,0.4)] animate-pulse' 
                        : 'bg-cyan-500/10 border-cyan-500/50 text-cyan-400 hover:bg-cyan-500/20 hover:border-cyan-400 hover:scale-105 hover:shadow-[0_0_15px_rgba(34,211,238,0.2)]'
                      }`}
                    >
                      {isRecording ? <Square size={36} fill="currentColor" /> : <Mic size={36} />}
                    </button>
                    {!isRecording && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          fileInputRef.current?.click();
                        }}
                        className="p-5 border-2 border-slate-700 bg-slate-800/50 rounded-full text-slate-400 hover:bg-slate-700 hover:text-white hover:border-slate-500 transition-all duration-300 hover:scale-105"
                      >
                        <Upload size={36} />
                      </button>
                    )}
                  </div>
                  
                  {isRecording ? (
                    <div className="text-center space-y-2 mt-4">
                      <p className="text-3xl font-bold text-rose-400 tracking-wider font-mono">
                        {Math.floor(recordingTime / 60).toString().padStart(2, '0')}:
                        {(recordingTime % 60).toString().padStart(2, '0')}
                      </p>
                      <p className="text-rose-500/70 text-sm">正在錄音... (點擊正方形停止)</p>
                    </div>
                  ) : (
                    <div className="text-center mt-4">
                      <p className="text-xl font-medium text-slate-300">點擊麥克風錄音，或將音檔拖曳至此</p>
                      <p className="text-slate-500 text-sm mt-2">支援網頁錄音 / MP3 / WAV / M4A</p>
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="mt-8 flex justify-center">
              <button
                disabled={!file || status === "uploading"}
                onClick={handleUpload}
                className={`px-8 py-4 rounded-full font-bold text-lg transition-all duration-300 flex items-center space-x-2 ${
                  !file ? 'bg-slate-700 text-slate-400 cursor-not-allowed' 
                  : status === 'uploading' ? 'bg-cyan-600 text-white cursor-wait'
                  : 'bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-white shadow-lg shadow-cyan-500/25 hover:shadow-cyan-500/40 hover:-translate-y-1'
                }`}
              >
                {status === "uploading" ? (
                  <><Loader2 className="animate-spin" size={24} /><span>上傳中...</span></>
                ) : (
                  <span>開始轉錄會議紀錄</span>
                )}
              </button>
            </div>
          </div>
        ) : null}

        {/* Status & Result */}
        {status !== "idle" && status !== "uploading" && (
          <div className="bg-white/5 backdrop-blur-xl border border-white/10 rounded-3xl p-8 shadow-2xl animate-in fade-in slide-in-from-bottom-8 duration-500">
            <div className="flex items-center justify-between mb-6 pb-6 border-b border-white/10">
              <div className="flex items-center space-x-4">
                {status === "pending" || status === "processing" ? (
                  <Loader2 className="animate-spin text-cyan-400" size={32} />
                ) : status === "completed" ? (
                  <CheckCircle className="text-emerald-400" size={32} />
                ) : (
                  <XCircle className="text-rose-400" size={32} />
                )}
                
                <div>
                  <h2 className="text-2xl font-bold text-slate-100">
                    {status === "pending" && "已加入佇列"}
                    {status === "processing" && "AI 模型處理中 (可能需要幾分鐘)..."}
                    {status === "completed" && "處理完成"}
                    {status === "failed" && "處理失敗"}
                  </h2>
                  <p className="text-slate-400 text-sm font-mono mt-1">Task ID: {taskId}</p>
                </div>
              </div>
              
              {status === "completed" && (
                <button
                  onClick={() => {
                    setFile(null);
                    setTaskId(null);
                    setStatus("idle");
                    setTranscript("");
                    setSummary("");
                    setErrorMessage("");
                  }}
                  className="px-4 py-2 bg-slate-800 hover:bg-slate-700 rounded-lg text-sm text-slate-300 transition-colors"
                >
                  處理下一筆
                </button>
              )}
            </div>

            {status === "completed" && (
              <>
                {audioUrl && (
                  <div className="mt-6 mb-2 p-4 bg-slate-900/40 rounded-2xl border border-white/5 flex flex-col md:flex-row items-center justify-center gap-4">
                    <audio 
                      key={audioUrl}
                      controls 
                      controlsList="nodownload"
                      src={audioUrl} 
                      className="w-full max-w-2xl h-14 outline-none rounded-lg flex-1"
                    />
                    <button
                      onClick={async () => {
                        try {
                          const res = await fetch(audioUrl);
                          if (!res.ok) throw new Error("Network response was not ok");
                          const blob = await res.blob();
                          const url = window.URL.createObjectURL(blob);
                          const a = document.createElement("a");
                          a.href = url;
                          a.download = `會議錄音_${taskId}.mp3`;
                          document.body.appendChild(a);
                          a.click();
                          window.URL.revokeObjectURL(url);
                          document.body.removeChild(a);
                        } catch (err) {
                          console.error(err);
                          alert("音檔下載失敗，請檢查網路連線或稍後再試。");
                        }
                      }}
                      className="flex items-center justify-center space-x-2 px-6 py-3 bg-cyan-600/80 hover:bg-cyan-500 text-white font-medium rounded-xl transition-all duration-300 hover:shadow-lg hover:shadow-cyan-500/25 shrink-0"
                    >
                      <Download size={20} />
                      <span>下載音檔</span>
                    </button>
                  </div>
                )}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mt-6">
                {/* 左邊：逐字稿 */}
                <div className="flex flex-col h-[65vh]">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-xl font-semibold text-cyan-400">會議逐字稿</h3>
                    <button
                      onClick={() => handleDownload("transcript.md", transcript)}
                      className="flex items-center space-x-1 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-cyan-400 text-sm rounded-md transition-colors"
                    >
                      <Download size={16} />
                      <span>下載 .md</span>
                    </button>
                  </div>
                  <div className="flex-1 bg-slate-900/50 rounded-2xl p-6 font-mono text-sm leading-relaxed overflow-y-auto border border-white/5 whitespace-pre-wrap">
                    {transcript}
                  </div>
                </div>

                {/* 右邊：會議摘要 */}
                <div className="flex flex-col h-[65vh]">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-xl font-semibold text-emerald-400">會議紀錄與摘要</h3>
                    <button
                      onClick={() => handleDownload("summary.md", summary)}
                      className="flex items-center space-x-1 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-emerald-400 text-sm rounded-md transition-colors"
                    >
                      <Download size={16} />
                      <span>下載 .md</span>
                    </button>
                  </div>
                  <div className="flex-1 bg-slate-900/50 rounded-2xl p-6 overflow-y-auto border border-white/5">
                    <article className="prose prose-invert prose-slate max-w-none prose-headings:text-cyan-400 prose-a:text-cyan-300">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {summary}
                      </ReactMarkdown>
                    </article>
                  </div>
                </div>
              </div>
              </>
            )}

            {status === "failed" && (
               <div className="bg-rose-500/10 border border-rose-500/20 rounded-2xl p-6 text-rose-200 whitespace-pre-wrap mt-4">
                 {errorMessage}
               </div>
            )}
          </div>
        )}
      </div>
    </main>
  );
}
