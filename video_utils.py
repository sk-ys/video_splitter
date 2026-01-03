import tempfile
import cv2
import os
from pathlib import Path

import numpy as np


codec_and_extensions = {
    "xvid": ".avi",
    "mjpg": ".avi",
    "mp4v": ".mp4",
    "h264": ".mp4",
    "x264": ".mp4",
    "avc1": ".mp4",
    "divx": ".avi",
    "FFV1": ".avi",
    "vp80": ".webm",
    "vp90": ".webm",
}


def split_video(
    video_path,
    segment_list,
    output_path,
    progress_callback=None,
    codec="mp4v",
    backend="opencv",
):
    """
    Split the video into segments and save them as files.
    Args:
        video_path (str): Path to the input video file
        segment_list (list): List of Segment objects
        output_path (str): Output directory
        progress_callback (callable, optional): Callback to notify progress (index, total)
        codec (str): FourCC codec string for output video
        backend (str): Video backend to use ("opencv" or "ffmpeg")
    """
    video_name = Path(video_path).stem
    extension = codec_and_extensions.get(codec, ".avi")
    for i, segment in enumerate(segment_list):
        if progress_callback:
            progress_callback(i, len(segment_list))
        title = segment.title or f"part{i+1:03d}"
        layer = str(segment.layer)
        layer = f"l{layer}-" if layer else ""
        output_file = os.path.join(
            output_path, f"{video_name}_{layer}{title}{extension}"
        )
        fourcc = cv2.VideoWriter_fourcc(*codec)
        if backend == "ffmpeg" and has_ffmpeg_support():
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


def load_video(video_path, backend="opencv"):
    """
    Load a video file and return capture object and info.
    Args:
        video_path (str): Path to the input video file
        backend (str): Video backend to use ("opencv" or "ffmpeg")
    Returns:
        cap (cv2.VideoCapture): Video capture object
        total_frames (int): Total number of frames
        fps (float): Video frame rate
    """
    cap = None
    if backend == "ffmpeg" and has_ffmpeg_support():
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


def get_available_codecs():
    """Test which codecs are actually available"""
    test_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    test_fps = 30

    available_codecs = []
    for codec, extension in codec_and_extensions.items():
        fourcc = cv2.VideoWriter_fourcc(*codec)

        with tempfile.NamedTemporaryFile(
            suffix=extension, delete=False
        ) as tmp_file:
            tmp_path = tmp_file.name

        available = False
        try:
            test_writer = cv2.VideoWriter(
                tmp_path, fourcc, test_fps, test_frame.shape[1::-1]
            )
            if test_writer.isOpened():
                test_writer.write(test_frame)
                test_writer.release()

                if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
                    available = True

        except Exception as e:
            print(f"Error testing codec {codec}: {e}")

        finally:
            if available:
                available_codecs.append((codec, extension))
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    return available_codecs
