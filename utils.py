import configparser
from tkinter import filedialog

# --- i18n setup ---
config = configparser.ConfigParser()
config["DEFAULT"] = {"language": "en"}
config.read("config.ini")

import i18n

lang = config["DEFAULT"].get("language", "en")
t = lambda s: i18n.translations[lang].get(s, s)


def format_time(seconds, format_type="hh:mm:ss.sss"):
    """Format seconds to hh:mm:ss.sss"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    if format_type == "hh:mm:ss.sss":
        return f"{h:02d}:{m:02d}:{s:06.3f}"
    elif format_type == "mm:ss.sss":
        total_minutes = int(seconds // 60)
        return f"{total_minutes:02d}:{s:06.3f}"
    elif format_type == "hh-mm-ss.sss":
        return f"{h:02d}-{m:02d}-{s:06.3f}"
    elif format_type == "mm-ss.sss":
        total_minutes = int(seconds // 60)
        return f"{total_minutes:02d}-{s:06.3f}"
    elif format_type == "ss.sss":
        return f"{seconds:.3f}"
    elif format_type == "hhmmss.sss":
        return f"{h:02d}{m:02d}{s:06.3f}"
    else:
        raise ValueError("Invalid format type")


def time_str_to_sec(time_str):
    """Parse time string in seconds or hh:mm:ss.sss or mm:ss.sss format to seconds"""
    if ":" in time_str:
        parts = time_str.split(":")
        if len(parts) not in (2, 3):
            raise ValueError("Invalid time format")
        if len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = float(parts[2])
            return hours * 3600 + minutes * 60 + seconds
        else:
            minutes = int(parts[0])
            seconds = float(parts[1])
            return minutes * 60 + seconds
    else:
        return float(time_str)


def load_video_dialog():
    return filedialog.askopenfilename(
        title=t("Select video file"),
        filetypes=[
            (
                t("Select video file"),
                "*.mp4 *.avi *.mov *.mkv *.flv *.wmv "
                + "*.webm *.mpg *.mpeg *.3gp *.mts *.ts *.vob",
            ),
            (t("Select"), "*.*"),
        ],
    )


class SimpleCache:
    def __init__(self, max_size=100):
        self.cache = {}
        self.max_size = max_size

    def get(self, key):
        value = self.cache.get(key)
        if value is not None:
            # Move accessed item to the end to mark it as recently used
            self.cache.pop(key)
            self.cache[key] = value
        return value

    def set(self, key, value):
        if len(self.cache) >= self.max_size:
            # Remove the first item in the cache (simple FIFO)
            self.cache.pop(next(iter(self.cache)))
        self.cache[key] = value

    def clear(self):
        self.cache = {}
