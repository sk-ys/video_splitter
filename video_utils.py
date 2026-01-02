import cv2
import os
from pathlib import Path


def split_video(
    video_path, segment_list, output_path, progress_callback=None
):
    """
    Split the video into segments and save them as files.
    Args:
        video_path (str): Path to the input video file
        segment_list (list): List of Segment objects
        output_path (str): Output directory
        progress_callback (callable, optional): Callback to notify progress (index, total)
    """
    video_name = Path(video_path).stem
    for i, segment in enumerate(segment_list):
        if progress_callback:
            progress_callback(i, len(segment_list))
        title = segment.title or f"part{i+1:03d}"
        layer = str(segment.layer)
        layer = f"l{layer}-" if layer else ""
        output_file = os.path.join(
            output_path, f"{video_name}_{layer}{title}.mp4"
        )
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        if has_ffmpeg_support():
            cap = cv2.VideoCapture(video_path, cv2.CAP_FFMPEG)
        else:
            cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        out = cv2.VideoWriter(output_file, fourcc, fps, (width, height))
        start_frame = int(segment.start_time * fps)
        end_frame = int(segment.end_time * fps)
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
    cap = None
    if has_ffmpeg_support():
        cap = cv2.VideoCapture(video_path, cv2.CAP_FFMPEG)

        if cap.isOpened():
            print(
                "[INFO]FFMPEG support detected and video opened "
                + "with FFMPEG backend."
            )
        else:
            print(
                "[INFO]FFMPEG support detected "
                + "but failed to open video with FFMPEG backend."
            )
            cap.release()
            cap = None

    if cap is None:
        cap = cv2.VideoCapture(video_path)

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    return cap, total_frames, fps


def has_ffmpeg_support() -> bool:
    """Check if OpenCV is built with FFMPEG support."""
    try:
        info = cv2.getBuildInformation()
    except Exception:
        return False

    return "FFMPEG:YES" in info.upper().replace(" ", "")
