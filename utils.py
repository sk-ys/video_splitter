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
    """
    A simple in-memory cache with a maximum size and basic FIFO eviction policy.
    Attributes:
        cache (dict): The underlying dictionary storing cached items.
        max_size (int): The maximum number of items the cache can hold.
            If set to 0 or negative, the cache size is unlimited.
    Methods:
        get(key):
            Retrieve a value from the cache by key. If the key exists and the cache
            has a positive max_size, the item is marked as recently used.
            Returns the value if found, otherwise None.
        set(key, value):
            Add a key-value pair to the cache. If the cache exceeds max_size,
            the oldest item is evicted (FIFO policy).
        clear():
            Remove all items from the cache.
    """
    def __init__(self, max_size=100):
        self.cache = {}
        self.max_size = max_size

    def get(self, key):
        value = self.cache.get(key)
        if value is not None and self.max_size > 0:
            # Move accessed item to the end to mark it as recently used
            self.cache.pop(key)
            self.cache[key] = value
        return value

    def set(self, key, value):
        if self.max_size > 0 and len(self.cache) >= self.max_size:
            # Remove the first item in the cache (simple FIFO)
            self.cache.pop(next(iter(self.cache)))
        self.cache[key] = value

    def clear(self):
        self.cache = {}
