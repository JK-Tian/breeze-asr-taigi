import os
import sys
import argparse
from pathlib import Path
import cv2

def parse_timestamp_to_seconds(ts_str: str) -> float:
    """將 MM:SS 或 HH:MM:SS 轉為秒數"""
    parts = ts_str.strip().split(':')
    if len(parts) == 2:
        m, s = map(float, parts)
        return m * 60 + s
    elif len(parts) == 3:
        h, m, s = map(float, parts)
        return h * 3600 + m * 60 + s
    else:
        return float(parts[0])

def process_video_cv2(video_path: str, output_dir: str, timestamps: str = None, fps: float = 0.5):
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"無法開啓影片檔案: {video_path}")

    video_fps = cap.get(cv2.CAP_PROP_FPS)
    if video_fps <= 0:
        video_fps = 30.0

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / video_fps

    if timestamps:
        print(f"模式：指定時間戳記截圖 ({timestamps})")
        ts_list = [ts.strip() for ts in timestamps.split(',')]
        for idx, ts in enumerate(ts_list, start=1):
            sec = parse_timestamp_to_seconds(ts)
            target_frame = int(sec * video_fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
            ret, frame = cap.read()
            if ret:
                output_file = os.path.join(output_dir, f"{idx:04d}.png")
                cv2.imwrite(output_file, frame)
                print(f"擷取時間點 {ts} ({sec}s) -> {output_file}")
            else:
                print(f"警告：無法讀取時間點 {ts} 的畫面")
    else:
        print(f"模式：固定頻率截圖 (FPS: {fps})")
        step_sec = 1.0 / fps
        curr_sec = 0.0
        idx = 1
        while curr_sec < duration:
            target_frame = int(curr_sec * video_fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
            ret, frame = cap.read()
            if ret:
                output_file = os.path.join(output_dir, f"{idx:04d}.png")
                cv2.imwrite(output_file, frame)
                idx += 1
            curr_sec += step_sec

    cap.release()
    print("截圖完成！圖片已儲存於：", output_dir)

def main():
    parser = argparse.ArgumentParser(description="影片自動截圖工具 (使用 OpenCV)")
    parser.add_argument("video_path", type=str, help="欲截圖的影片檔案路徑")
    parser.add_argument("--fps", type=float, default=0.5, help="截圖頻率 FPS")
    parser.add_argument("--timestamps", type=str, default=None, help="指定截圖的時間點清單，以逗號分隔")
    args = parser.parse_args()

    video_file_path = Path(args.video_path)
    output_dir = video_file_path.with_suffix('')
    process_video_cv2(str(video_file_path), str(output_dir), args.timestamps, args.fps)

if __name__ == "__main__":
    main()
