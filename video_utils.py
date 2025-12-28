import cv2
import os
from pathlib import Path


def split_video(video_path, split_list, output_path, progress_callback=None):
    """
    Split the video and save segments to files.
    Args:
        video_path (str): Path to the input video file
        split_list (list): List of split info dicts (containing start, end, title, etc.)
        output_path (str): Output directory
        progress_callback (callable, optional): Callback to notify progress (index, total)
    """
    video_name = Path(video_path).stem
    for i, split in enumerate(split_list):
        if progress_callback:
            progress_callback(i, len(split_list))
        title = split.get("title", f"part{i+1:03d}")
        layer = str(split.get("layer", ""))
        layer = f"l{layer}-" if layer else ""
        output_file = os.path.join(
            output_path, f"{video_name}_{layer}{title}.mp4"
        )
        cap = cv2.VideoCapture(video_path)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        out = cv2.VideoWriter(output_file, fourcc, fps, (width, height))
        start_frame = int(split["start"] * fps)
        end_frame = int(split["end"] * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        for frame_num in range(start_frame, end_frame):
            ret, frame = cap.read()
            if not ret:
                break
            out.write(frame)
        cap.release()
        out.release()


def load_video(video_path):
    """
    Load a video file and return capture object and info.
    Args:
        video_path (str): Path to the input video file
    Returns:
        cap (cv2.VideoCapture): Video capture object
        total_frames (int): Total number of frames
        fps (float): Video frame rate
    """
    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    return cap, total_frames, fps
