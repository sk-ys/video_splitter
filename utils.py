import configparser
from tkinter import filedialog

# --- i18n setup ---
config = configparser.ConfigParser()
config["DEFAULT"] = {"language": "en"}
config.read("config.ini")

import i18n

lang = config["DEFAULT"].get("language", "en")
t = lambda s: i18n.translations[lang].get(s, s)


def format_time(seconds):
    """Format seconds to mm:ss.sss"""
    m = int(seconds // 60)
    s = seconds % 60
    return f"{m:02d}:{s:06.3f}"


def time_str_to_sec(time_str):
    """Parse time string in seconds or mm:ss.sss format to seconds"""
    if ":" in time_str:
        parts = time_str.split(":")
        if len(parts) != 2:
            raise ValueError("Invalid time format")
        minutes = int(parts[0])
        seconds = float(parts[1])
        return minutes * 60 + seconds
    else:
        return float(time_str)


def load_video_dialog():
    return filedialog.askopenfilename(
        title=t("Select video file"),
        filetypes=[
            (t("Select video file"), "*.mp4 *.avi *.mov *.mkv"),
            (t("Select"), "*.*"),
        ],
    )


def load_video(video_path):
    import cv2

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise IOError("Cannot open video file")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    return cap, total_frames, fps
