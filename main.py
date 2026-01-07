from datetime import datetime
from pathlib import Path
import re
import tkinter as tk
import customtkinter as ctk
from ctk_widgets import CTkSpinbox
from tkinter import filedialog, messagebox
import cv2
import video_utils
from PIL import Image
import threading
import os
import json
import configparser
import utils

config = configparser.ConfigParser()
config["DEFAULT"] = {"language": "en"}
config.read("config.ini")

# --- i18n setup ---
import i18n

lang = config["DEFAULT"].get("language", "en")
t = lambda s: i18n.translations[lang].get(s, s)


def change_language(lang):
    global t
    t = lambda s: i18n.translations[lang].get(s, s)


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class CustomCTkInputDialog(ctk.CTkInputDialog):
    """CTkInputDialog with robust initialvalue support across versions."""

    def __init__(self, *args, initialvalue="", **kwargs):
        self._initialvalue = initialvalue
        super().__init__(*args, **kwargs)
        # Apply after widgets are built to avoid being overwritten.
        self.after(10, self._apply_initialvalue)

    def _apply_initialvalue(self):
        """Set the initial value in the input field."""
        entry_widget = getattr(self, "entry", None) or getattr(
            self, "_entry", None
        )
        if entry_widget is not None:
            entry_widget.delete(0, tk.END)
            entry_widget.insert(0, self._initialvalue)
        else:
            input_var = getattr(self, "input_var", None)
            if input_var is not None:
                input_var.set(self._initialvalue)


class Segment:
    def __init__(self, fps, segment_id, layer, title, start_frame, end_frame):
        self.fps = fps
        self.segment_id = segment_id
        self.layer = layer
        self.title = title
        self.start_frame = start_frame
        self.end_frame = end_frame
        self._ui = {}

    def to_dict(self):
        return {
            "id": self.segment_id,
            "layer": self.layer,
            "title": self.title,
            "start": self.start_time,
            "end": self.end_time,
        }

    @property
    def duration(self):
        return (self.end_frame - self.start_frame) / self.fps

    @property
    def start_time(self):
        return self.start_frame / self.fps

    @start_time.setter
    def start_time(self, value):
        self.start_frame = round(value * self.fps)

    @property
    def end_time(self):
        return self.end_frame / self.fps

    @end_time.setter
    def end_time(self, value):
        self.end_frame = round(value * self.fps)

    @property
    def ui(self):
        return self._ui

    @ui.setter
    def ui(self, value):
        self._ui = value

    @ui.deleter
    def ui(self):
        self._ui = {}


class SegmentManager:
    def __init__(self, fps, total_frames, items=None):
        self.fps = fps
        self.total_frames = total_frames
        self.items = items if items is not None else []
        self._ui = {}

    def __iter__(self):
        return iter(self.items)

    def __len__(self):
        return len(self.items)

    @classmethod
    def from_dicts(cls, fps, total_frames, dicts):
        segments = []
        for d in dicts:
            segment = Segment(
                fps=fps,
                segment_id=d.get("id", d.get("segment_id")),
                layer=d.get("layer", 1),
                title=d["title"],
                start_frame=round(d.get("start", d.get("start_time")) * fps),
                end_frame=round(d.get("end", d.get("end_time")) * fps),
            )
            segments.append(segment)
        return cls(fps, total_frames, segments)

    def get_max_list_index(self):
        """Get the maximum ID in the full segment list"""
        if not self.items:
            return 0
        return max(segment.segment_id for segment in self.items)

    def set_items(self, segments):
        self.items = segments

    def append(self, layer, start_frame, end_frame, title=None):
        if title is None:
            title = f"part{len(self.filter_by_layers([layer]))+1:03d}"

        self.items.append(
            Segment(
                fps=self.fps,
                segment_id=self.get_max_list_index() + 1,
                layer=layer,
                title=title,
                start_frame=start_frame,
                end_frame=end_frame,
            )
        )

    def get_segment_by_id(self, segment_id):
        """Get the segment by its ID"""
        for segment in self.items:
            if segment.segment_id == segment_id:
                return segment
        return None

    def get_segment_by_time(
        self, time_sec, layer, include_start=True, include_end=True
    ):
        """Get the segment by time (in seconds)"""
        for segment in self.items:
            if segment.layer != layer:
                continue

            start = segment.start_time
            end = segment.end_time

            if include_start and include_end:
                if start <= time_sec <= end:
                    return segment
            elif include_start:
                if start <= time_sec < end:
                    return segment
            elif include_end:
                if start < time_sec <= end:
                    return segment
            else:
                if start < time_sec < end:
                    return segment
        return None

    def get_segments_by_time(
        self, time_sec, layer, include_start=True, include_end=True
    ):
        """Get the segment by time (in seconds)"""
        segments = []
        for segment in self.items:
            if segment.layer != layer:
                continue

            start = segment.start_time
            end = segment.end_time

            if include_start and include_end:
                if start <= time_sec <= end:
                    segments.append(segment)
            elif include_start:
                if start <= time_sec < end:
                    segments.append(segment)
            elif include_end:
                if start < time_sec <= end:
                    segments.append(segment)
            else:
                if start < time_sec < end:
                    segments.append(segment)
        return segments

    def get_index_by_id(self, segment_id):
        """Get the index of the segment by its ID"""
        layer = self.get_segment_by_id(segment_id).layer
        filtered_segments = self.filter_by_layers([layer])
        for i, segment in enumerate(filtered_segments):
            if segment.segment_id == segment_id:
                return i
        return None

    def filter_by_layers(self, layers):
        return [s for s in self.items if s.layer in layers]

    def clear(self, layers=None):
        if layers is None:
            self.items = []
        else:
            self.items = [
                segment
                for segment in self.items
                if segment.layer not in layers
            ]

    def remove_segment_by_id(self, segment_id):
        self.items = [
            segment
            for segment in self.items
            if segment.segment_id != segment_id
        ]

    def get_next_free_time(self, start_time, layer):
        """Get the next free time after start_time in the selected layer"""
        segment = self.get_segment_by_time(start_time, layer, True, False)

        if segment is None:
            if start_time >= self.total_frames / self.fps:
                return None
            return start_time
        else:
            return self.get_next_free_time(segment.end_time, layer)

    def get_previous_free_time(self, end_time, layer):
        """Get the previous free time before end_time in the selected layer"""
        segment = self.get_segment_by_time(end_time, layer, False, True)

        if segment is None:
            if end_time <= 0:
                return None
            return end_time
        else:
            return self.get_previous_free_time(segment.start_time, layer)

    def get_next_segment(self, current_segment):
        """Get the next segment in the same layer"""
        filtered_segments = sorted(
            [
                segment
                for segment in self.items
                if segment.layer == current_segment.layer
                and segment.start_time > current_segment.start_time
            ],
            key=lambda x: x.start_time,
        )

        if len(filtered_segments) > 0:
            return filtered_segments[0]
        else:
            return None

    def get_prev_segment(self, current_segment):
        """Get the previous segment in the same layer"""
        filtered_segments = sorted(
            [
                segment
                for segment in self.items
                if segment.layer == current_segment.layer
                and segment.end_time < current_segment.end_time
            ],
            key=lambda x: x.end_time,
            reverse=True,
        )

        if len(filtered_segments) > 0:
            return filtered_segments[0]
        else:
            return None

    def get_next_segment_by_time(self, time, layer):
        """Get the next segment after the specified time (in seconds)"""
        same_layer_segments = sorted(
            [
                segment
                for segment in self.items
                if segment.layer == layer and segment.start_time > time
            ],
            key=lambda x: x.start_time,
        )

        if same_layer_segments:
            return same_layer_segments[0]
        return None

    def get_prev_segment_by_time(self, time, layer):
        """Get the previous segment before the specified time (in seconds)"""
        same_layer_segments = sorted(
            [
                segment
                for segment in self.items
                if segment.layer == layer and segment.end_time < time
            ],
            key=lambda x: x.start_time,
            reverse=True,
        )

        if same_layer_segments:
            return same_layer_segments[0]
        return None

    def reset_list_indexes(self):
        """Reassign IDs to segments based on their order in the full list"""
        for i, segment in enumerate(self.items):
            segment.segment_id = i + 1

    def get_segments_before_time(self, time_sec, layer=None):
        """Get the segments before the specified time (in seconds)"""
        if layer is None:
            layer = self.selected_layer

        filtered_segment_list = [
            segment
            for segment in self.items
            if segment.layer == layer and segment.end_time <= time_sec
        ]

        # Return sorted list
        return sorted(filtered_segment_list, key=lambda x: x.end_time)

    def get_segments_after_time(self, time_sec, layer=None):
        """Get the segments after the specified time (in seconds)"""
        if layer is None:
            layer = self.selected_layer

        filtered_segment_list = [
            segment
            for segment in self.items
            if segment.layer == layer and segment.start_time >= time_sec
        ]

        # Return sorted list
        return sorted(filtered_segment_list, key=lambda x: x.start_time)

    def sort_segments_by_title(self):
        """Sort segments by their title"""
        self.items.sort(key=lambda segment: segment.title)

    def sort_segments_by_start_time(self):
        """Sort segments by their start time"""
        self.items.sort(key=lambda segment: segment.start_time)

    def reset_indices(self):
        """Reset segment IDs based on their order in the list"""
        for index, segment in enumerate(self.items):
            segment.segment_id = index + 1


class VideoProject:
    def __init__(self, video_path, output_path=None):
        self._file_path = None
        self.video_path = video_path
        self.output_path = output_path
        self.cap, self.total_frames, self.fps = video_utils.load_video(
            video_path, backend=config.get("DEFAULT", "backend")
        )
        self.segments = SegmentManager(self.fps, self.total_frames)

    def __del__(self):
        if self.cap is not None:
            self.cap.release()

    def to_dict(self):
        return {
            "video_path": self.video_path,
            "output_path": self.output_path,
            "segments": [segment.to_dict() for segment in self.segments],
        }

    @property
    def duration(self):
        return self.total_frames / self.fps

    @property
    def file_path(self):
        return self._file_path

    def save(self, file_path):
        project_data = {
            "video_path": self.video_path,
            "output_path": self.output_path,
            "segment_list": [segment.to_dict() for segment in self.segments],
        }

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(project_data, f, ensure_ascii=False, indent=2)

        # Update the file path after saving
        self._file_path = file_path

    @classmethod
    def open_project_dialog(cls):
        return filedialog.askopenfilename(
            title=t("Open Project"),
            filetypes=[
                ("JSON", "*.json"),
                (t("Select"), "*.*"),
            ],
        )

    @classmethod
    def load(cls, file_path=None):
        if file_path is None:
            file_path = cls.open_project_dialog()

        if not file_path:
            raise ValueError("No project file selected")

        with open(file_path, "r", encoding="utf-8") as f:
            project_data = json.load(f)

        video_path = project_data.get("video_path")
        output_path = project_data.get("output_path")

        instance = cls(
            video_path=video_path,
            output_path=output_path,
        )
        instance.segments = SegmentManager.from_dicts(
            instance.fps,
            instance.total_frames,
            project_data.get("segment_list", []),
        )
        instance._file_path = file_path
        return instance

    def load_video(self):
        return utils.load_video_dialog()


class StatusText:
    def __init__(
        self,
        app,
        status_bar_label,
        default_text_color="gray40",
        default_bg_color="transparent",
    ):
        self.app = app
        self.status_bar_label = status_bar_label
        self.default_text_color = default_text_color
        self.default_bg_color = default_bg_color
        self.last_timestamp = None

    def clear_status_text(self, timestamp=None):
        # Clear only if enough time has passed since last update
        if self.last_timestamp is None or timestamp == self.last_timestamp:
            self.status_bar_label.configure(
                text="",
                text_color=self.default_text_color,
                bg_color=self.default_bg_color,
            )

    def text(self, text, duration=5000, text_color=None, bg_color=None):
        if text_color is None:
            text_color = self.default_text_color
        if bg_color is None:
            bg_color = self.default_bg_color
        self.status_bar_label.configure(
            text=text, text_color=text_color, bg_color=bg_color
        )
        timestamp = datetime.now()
        self.last_timestamp = timestamp

        if duration > 0:
            self.app.after(
                duration,
                lambda timestamp=timestamp: self.clear_status_text(timestamp),
            )

    def info(self, text, duration=5000):
        self.text("ℹ️ " + text, duration=duration, text_color="cornflower blue")

    def warning(self, text, duration=5000):
        self.text("⚠️ " + text, duration=duration, text_color="sandy brown")

    def error(self, text, duration=5000):
        self.text("🛑 " + text, duration=duration, text_color="orange red")

    def clear(self):
        self.text("", duration=0)


class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)

        self.parent = parent

        self.title(t("Settings"))
        self.geometry("400x300")

        self.grid_rowconfigure(0, weight=1)  # Content
        self.grid_rowconfigure(1, weight=0)  # Buttons
        self.grid_columnconfigure(0, weight=1)

        # Content
        self.content_frame = ctk.CTkFrame(self)
        self.content_frame.grid(
            row=0, column=0, padx=10, pady=5, sticky="nsew"
        )
        self.content_frame.grid_columnconfigure(0, weight=1)
        
        row = 0

        # Language selection
        ctk.CTkLabel(self.content_frame, text=t("Language") + ":").grid(
            row=row, column=0, padx=5, pady=5, sticky="w"
        )

        self.lang_var = ctk.StringVar(value=lang)
        self.lang_option = ctk.CTkOptionMenu(
            self.content_frame,
            values=["en", "ja"],
            variable=self.lang_var,
            command=self.change_language,
        )
        self.lang_option.grid(row=row, column=1, padx=5, pady=5, sticky="w")

        # Layer count selection
        row += 1
        self.layer_count_label = ctk.CTkLabel(
            self.content_frame, text=t("Number of default Layers") + ":"
        )
        self.layer_count_label.grid(
            row=row, column=0, padx=5, pady=5, sticky="w"
        )

        self.layer_count_var = ctk.IntVar(
            value=config.getint("DEFAULT", "layer_count", fallback=3)
        )
        self.layer_count_spinbox = ctk.CTkOptionMenu(
            self.content_frame,
            values=[str(i) for i in range(1, 11)],
            variable=self.layer_count_var,
        )
        self.layer_count_spinbox.grid(
            row=row, column=1, padx=5, pady=5, sticky="w"
        )

        # Cache size selection
        row += 1
        self.cache_size_label = ctk.CTkLabel(
            self.content_frame, text=t("Video Cache Size (frames)") + ":"
        )
        self.cache_size_label.grid(row=row, column=0, padx=5, pady=5, sticky="w")
        self.cache_size_spinbox = CTkSpinbox(
            self.content_frame,
            initialvalue=config.getint("DEFAULT", "cache_size", fallback=30),
            min_value=0,
            max_value=1000,
            step=10,
            width=120,
        )
        self.cache_size_spinbox.grid(
            row=row, column=1, padx=5, pady=5, sticky="w"
        )
        
        # Clear cache button
        row += 1
        self.clear_cache_label = ctk.CTkLabel(
            self.content_frame,
            text=t("Clear cache") + ":",
        )
        self.clear_cache_label.grid(
            row=row, column=0, padx=5, pady=5, sticky="w"
        )
        self.clear_cache_button = ctk.CTkButton(
            self.content_frame,
            text=t("Clear"),
            command=self.parent.clear_video_cache,
        )
        self.clear_cache_button.grid(
            row=row, column=1, padx=5, pady=5, sticky="w"
        )

        # Preload head frame count selection
        row += 1
        self.preload_head_frame_count_label = ctk.CTkLabel(
            self.content_frame, text=t("Preload Head Frame Count") + ":"
        )
        self.preload_head_frame_count_label.grid(
            row=row, column=0, padx=5, pady=5, sticky="w"
        )
        self.preload_head_frame_count_spinbox = CTkSpinbox(
            self.content_frame,
            initialvalue=config.getint(
                "DEFAULT", "preload_head_frame_count", fallback=300
            ),
            min_value=0,
            max_value=1000,
            step=1,
            width=120,
        )
        self.preload_head_frame_count_spinbox.grid(
            row=row, column=1, padx=5, pady=5, sticky="w"
        )

        # Codec selector
        row += 1
        ctk.CTkLabel(
            self.content_frame, text=t("Video encoder codec") + ":"
        ).grid(row=row, column=0, padx=5, pady=5, sticky="w")
        self.codec_var = ctk.StringVar(
            value=config.get("DEFAULT", "codec", fallback="mp4v")
        )
        self.codec_option = ctk.CTkOptionMenu(
            self.content_frame,
            values=[codec for codec, _ in self.parent.available_codecs],
            variable=self.codec_var,
        )
        self.codec_option.grid(row=row, column=1, padx=5, pady=5, sticky="w")

        # Backend selector
        row += 1
        ctk.CTkLabel(
            self.content_frame, text=t("Video backend (if available)") + ":"
        ).grid(row=row, column=0, padx=5, pady=5, sticky="w")
        self.backend_var = ctk.StringVar(
            value=config.get("DEFAULT", "backend", fallback="opencv")
        )
        self.backend_option = ctk.CTkOptionMenu(
            self.content_frame,
            values=["opencv", "ffmpeg"],
            variable=self.backend_var,
        )
        self.backend_option.grid(row=row, column=1, padx=5, pady=5, sticky="w")

        # Buttons
        self.button_frame = ctk.CTkFrame(self)
        self.button_frame.grid(row=1, column=0, padx=10, pady=10, sticky="e")
        self.button_frame.grid_columnconfigure(0, weight=1)

        self.ok_button = ctk.CTkButton(
            self.button_frame,
            text=t("OK"),
            command=self.on_ok,
            width=80,
        )
        self.ok_button.pack(side="left", padx=5, pady=5)
        self.cancel_button = ctk.CTkButton(
            self.button_frame,
            text=t("Cancel"),
            command=self.on_cancel,
            width=80,
        )
        self.cancel_button.pack(side="left", padx=5, pady=5)

    def on_ok(self):
        config["DEFAULT"]["language"] = self.lang_var.get()
        config["DEFAULT"]["layer_count"] = str(self.layer_count_var.get())

        cache_size = self.cache_size_spinbox.get()
        preload_head_frame_count = self.preload_head_frame_count_spinbox.get()
        config["DEFAULT"]["cache_size"] = str(cache_size)
        config["DEFAULT"]["preload_head_frame_count"] = str(
            preload_head_frame_count
        )
        config["DEFAULT"]["codec"] = self.codec_var.get()
        if config["DEFAULT"]["backend"] != self.backend_var.get():
            config["DEFAULT"]["backend"] = self.backend_var.get()
            messagebox.showinfo(
                t("Info"),
                t(
                    "Video backend changed. "
                    + "New backend applies on next video load."
                ),
            )
        with open("config.ini", "w") as config_file:
            config.write(config_file)
        self.destroy()
        self.parent.set_layer_count(self.layer_count_var.get())
        self.parent.set_cache_size(cache_size)
        self.parent.set_preload_head_frame_count(preload_head_frame_count)

    def on_cancel(self):
        self.destroy()

    def change_language(self, choice):
        global lang
        lang = choice
        change_language(lang)
        messagebox.showinfo(
            t("Info"),
            t(
                "Language changed. Please restart the application "
                + "to apply changes."
            ),
        )


class VideoSplitterApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(t("Video Splitter"))
        self.geometry("1400x900")

        self.available_codecs = []
        threading.Thread(
            target=self._load_available_codecs, daemon=True
        ).start()

        # Video-related variables
        self.current_frame = 0
        self.is_playing = False

        # Split layers
        self.seek_canvases = []
        self.set_layer_count(
            config.getint("DEFAULT", "layer_count", fallback=3)
        )

        # Project
        self.vp = None

        self.start_frame = None
        self.selected_segment_id = None

        self.video_cache = utils.SimpleCache(max_size=30)
        self.video_cache_for_head = utils.SimpleCache(max_size=0)
        self.video_cache_for_head_frame_count = 300
        self.status_text = None
        self.is_seeking = False
        self.prev_frame_click_count = 0
        self.prev_frame_auto_repeat = False
        self.next_frame_click_count = 0
        self.next_frame_auto_repeat = False
        self.auto_repeat_interval_ms = 300  # Initial delay before auto-repeat
        self.zoom_scale_list = [
            1,
            2,
            3,
            5,
            10,
            15,
            20,
            25,
            30,
            40,
            50,
            60,
            70,
            80,
            90,
            100,
        ]
        self.setup_ui()

        self.change_layer(self.selected_layer)

        # Bind keyboard shortcuts
        self.bind("<Control-s>", self.save_project)
        self.bind("<Control-Shift-S>", self.save_as_project)
        self.bind("<Control-o>", self.open_project)
        self.bind("<space>", self.toggle_playback)
        self.bind("<Left>", self.goto_prev_frame)
        self.bind("<Right>", self.goto_next_frame)
        self.bind("<Control-Left>", self.goto_prev_section)
        self.bind("<Control-Right>", self.goto_next_section)
        self.bind("<Up>", self.switch_to_upper_layer)
        self.bind("<Down>", self.switch_to_lower_layer)
        self.bind("<s>", self.set_start_point)
        self.bind("<e>", self.set_end_point)
        self.bind("<a>", self.toggle_mode)

    def _load_available_codecs(self):
        self.available_codecs = video_utils.get_available_codecs()

    def set_layer_count(self, count):
        self.layers = list(range(1, count + 1))
        self.selected_layer = self.layers[0]
        if hasattr(self, "seek_canvases_frame"):
            self.clear_seekbar_canvases_ui()
            self.setup_seekbar_canvases_ui(self.seek_canvases_frame)
            self.update_seekbar_time_labels()
            self.refresh_all_segments_in_list()
            self.change_layer(str(self.selected_layer))

    def set_cache_size(self, size):
        self.video_cache.max_size = size
        
    def clear_video_cache(self):
        self.video_cache.clear()
        self.status_text.info(t("Video cache cleared."))

    def set_preload_head_frame_count(self, count):
        self.video_cache_for_head_frame_count = count

    def setup_ui(self):
        # Main layout: two resizable columns (left/right)
        self.min_left_width = 750
        self.min_right_width = 600
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(
            0, weight=1, minsize=self.min_left_width + self.min_right_width
        )

        self.main_frame = ctk.CTkFrame(self)
        self.main_frame.grid(row=0, column=0, sticky="nsew")
        self.main_frame.grid_rowconfigure(0, weight=1)
        self.main_frame.grid_columnconfigure(
            0, weight=1, minsize=self.min_left_width
        )
        self.main_frame.grid_columnconfigure(1, weight=0)  # Separator
        self.main_frame.grid_columnconfigure(
            2, weight=0, minsize=self.min_right_width
        )

        self.status_bar_frame = ctk.CTkFrame(self, height=20)
        self.status_bar_frame.grid(
            row=1, column=0, padx=0, pady=0, sticky="ew"
        )
        self.status_bar = ctk.CTkLabel(
            self.status_bar_frame,
            text="",
            height=20,
            font=ctk.CTkFont(size=12),
            text_color="gray60",
        )
        self.status_bar.grid(row=0, column=0, padx=10, pady=2, sticky="ew")
        self.status_text = StatusText(self, self.status_bar)

        self.setup_left_ui(self.main_frame)

        self.setup_separator_ui(self.main_frame)

        self.setup_right_ui(self.main_frame)

    def setup_left_ui(self, parent):
        # Left: Video preview area
        self.left_frame = ctk.CTkFrame(parent)
        self.left_frame.grid(
            row=0, column=0, padx=(10, 0), pady=(10, 0), sticky="nsew"
        )
        self.left_frame.grid_rowconfigure(1, weight=1)
        self.left_frame.grid_columnconfigure(0, weight=1)

        # Main menu area
        self.main_menu_frame = ctk.CTkFrame(self.left_frame)
        self.main_menu_frame.grid(
            row=0, column=0, padx=10, pady=10, sticky="ew"
        )
        self.setup_main_menu_ui(self.main_menu_frame)

        # Video display canvas
        self.canvas_frame = ctk.CTkFrame(self.left_frame)
        self.canvas_frame.grid(row=1, column=0, padx=10, pady=5, sticky="nsew")

        self.video_label = ctk.CTkLabel(
            self.canvas_frame, text=t("Load a video file")
        )
        self.video_label.pack(expand=True, fill="both")

        # Control panel
        self.control_frame = ctk.CTkFrame(self.left_frame)
        self.control_frame.grid(row=2, column=0, padx=10, pady=5, sticky="ew")
        self.setup_video_control_ui(self.control_frame)

    def setup_video_control_ui(self, parent):
        # Button group
        self.video_control_buttons_frame = ctk.CTkFrame(parent)
        self.video_control_buttons_frame.grid(
            row=0, column=0, padx=5, pady=5, sticky="w"
        )
        self.setup_video_control_buttons_ui(self.video_control_buttons_frame)

        # Time and frame display
        self.info_frame = ctk.CTkFrame(parent)
        self.info_frame.grid(row=0, column=3, padx=10, pady=5)

        self.time_label = ctk.CTkLabel(
            self.info_frame, text="00:00.000 / 00:00.000"
        )
        self.time_label.pack(side="left", padx=10)

        self.frame_label = ctk.CTkLabel(
            self.info_frame, text=f"{t("Frame")}: 0 / 0"
        )
        self.frame_label.pack(side="left", padx=(0, 10))

        # Seekbar and zoom controls
        self.seekbar_frame = ctk.CTkFrame(parent)
        self.seekbar_frame.grid(
            row=1, column=0, columnspan=4, padx=5, pady=5, sticky="ew"
        )
        self.seekbar_frame.grid_columnconfigure(1, weight=1)
        self.seekbar_frame.bind("<Configure>", self.seekbar_resize_event)

        # Zoom control
        self.zoom_scale_control_frame = ctk.CTkFrame(self.seekbar_frame)
        self.zoom_scale_control_frame.grid(
            row=0, column=0, columnspan=3, padx=5, pady=5, sticky="w"
        )
        ctk.CTkLabel(
            self.zoom_scale_control_frame, text=f"{t("Scale")}: "
        ).grid(row=0, column=0, padx=(5, 2))
        self.zoom_scale_selector = ctk.CTkOptionMenu(
            self.zoom_scale_control_frame,
            values=[str(z) + "%" for z in self.zoom_scale_list],
            width=70,
            command=self.on_zoom_scale_selector_change,
            state="disabled",
        )
        self.zoom_scale_selector.grid(row=0, column=1, padx=(2, 5))
        self.zoom_scale_selector.set(f"{self.zoom_scale_list[-1]}%")

        ctk.CTkLabel(
            self.zoom_scale_control_frame, text=f"{t("Range")}:"
        ).grid(row=0, column=2, padx=5)
        self.zoom_range_slider = ctk.CTkSlider(
            self.zoom_scale_control_frame,
            from_=1,
            to=100,
            command=self.on_zoom_range_slider_update,
            state="disabled",
            width=150,
        )
        self.zoom_range_slider.set(50)
        self.zoom_range_slider.grid(row=0, column=3, padx=5)

        # Canvas for seekbar (for range display)
        self.seek_canvases_frame = ctk.CTkFrame(self.seekbar_frame)
        self.seek_canvases_frame.grid(
            row=1, column=0, columnspan=3, padx=5, pady=5, sticky="ew"
        )

        self.setup_seekbar_canvases_ui(self.seek_canvases_frame)

        # Empty canvas for main seekbar
        empty_canvas_frame = ctk.CTkFrame(
            self.seekbar_frame, width=32, height=10, fg_color="transparent"
        )
        empty_canvas_frame.grid(row=2, column=0)

        # Seekbar
        self.seek_slider = ctk.CTkSlider(
            self.seekbar_frame,
            from_=0,
            to=100,
            command=self.seek_video,
            state="disabled",
        )
        self.seek_slider.bind("<Button-1>", self.on_seek_start)
        self.seek_slider.bind("<ButtonRelease-1>", self.on_seek_end)
        self.seek_slider.grid(
            row=2, column=1, columnspan=2, padx=5, pady=0, sticky="ew"
        )

        # Seekbar range display
        self.seekbar_range_frame = ctk.CTkFrame(
            self.seekbar_frame, fg_color="transparent"
        )
        self.seekbar_range_frame.grid(
            row=3, column=1, columnspan=2, padx=5, pady=(5, 0), sticky="ew"
        )

        self.seekbar_start_label = ctk.CTkLabel(
            self.seekbar_range_frame, text="00:00.000", width=80
        )
        self.seekbar_start_label.pack(side="left")

        self.seekbar_end_label = ctk.CTkLabel(
            self.seekbar_range_frame, text="00:00.000", width=80
        )
        self.seekbar_end_label.pack(side="right")

        # Expand seekbar frame columns
        self.control_frame.grid_columnconfigure(1, weight=1)

        # Zoom-related variables
        self.update_zoom_scale(self.zoom_scale_list[-1])

        # Split point setting buttons
        self.split_control_frame = ctk.CTkFrame(self.left_frame)
        self.split_control_frame.grid(
            row=3, column=0, padx=10, pady=5, sticky="ew"
        )

        self.setup_split_control_ui(self.split_control_frame)

    def setup_main_menu_ui(self, parent):
        # Settings panel open button
        self.open_settings_button = ctk.CTkButton(
            parent,
            text="⚙",
            command=self.open_settings,
            height=40,
            width=40,
            fg_color="gray40",
            hover_color="gray50",
        )
        self.open_settings_button.grid(row=0, column=0, padx=5, pady=5)

        # File select button
        self.file_button = ctk.CTkButton(
            parent,
            text="🎦 " + t("Select video file"),
            command=self.load_video_dialog,
            height=40,
        )
        self.file_button.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        # Project load button
        self.open_project_button = ctk.CTkButton(
            parent,
            text="📂 " + t("Open Project"),
            command=self.open_project,
            height=40,
            width=150,
            fg_color="gray40",
            hover_color="gray50",
        )
        self.open_project_button.grid(row=0, column=2, padx=5, pady=5)

        # Project save button
        self.save_project_button = ctk.CTkButton(
            parent,
            text="💾 " + t("Save Project"),
            command=self.save_project,
            height=40,
            width=150,
            fg_color="gray40",
            hover_color="gray50",
        )
        self.save_project_button.grid(row=0, column=3, padx=5, pady=5)

    def setup_video_control_buttons_ui(self, parent):
        # Play/Pause button
        self.play_button = ctk.CTkButton(
            parent,
            text="▶ " + t("Play"),
            command=self.toggle_playback,
            width=100,
            state="disabled",
        )
        self.play_button.grid(row=0, column=0, padx=5, pady=5)

        self.prev_section_button = ctk.CTkButton(
            parent,
            text="⏮️",
            command=self.goto_prev_section,
            width=30,
            state="disabled",
        )
        self.prev_section_button.grid(row=0, column=1, padx=(5, 1), pady=5)

        self.rewind_10sec_button = ctk.CTkButton(
            parent,
            text="⏪10s",
            command=self.rewind_10sec,
            width=60,
            state="disabled",
        )
        self.rewind_10sec_button.grid(row=0, column=2, padx=1, pady=5)

        # Frame navigation buttons
        self.prev_frame_button = ctk.CTkButton(
            parent,
            text=f"◀",
            command=lambda: None,
            width=30,
            state="disabled",
        )
        self.prev_frame_button.grid(row=0, column=3, padx=1, pady=5)
        self.prev_frame_button.bind(
            "<Button-1>", self.on_prev_frame_button_press
        )
        self.prev_frame_button.bind(
            "<ButtonRelease-1>", self.on_prev_frame_button_release
        )

        self.next_frame_button = ctk.CTkButton(
            parent,
            text=f"▶",
            command=lambda: None,
            width=30,
            state="disabled",
        )
        self.next_frame_button.grid(row=0, column=4, padx=1, pady=5)
        self.next_frame_button.bind(
            "<Button-1>", self.on_next_frame_button_press
        )
        self.next_frame_button.bind(
            "<ButtonRelease-1>", self.on_next_frame_button_release
        )

        self.fast_forward_10sec_button = ctk.CTkButton(
            parent,
            text="10s⏩",
            command=self.fast_forward_10sec,
            width=60,
            state="disabled",
        )
        self.fast_forward_10sec_button.grid(row=0, column=5, padx=1, pady=5)

        self.next_section_button = ctk.CTkButton(
            parent,
            text="⏭️",
            command=self.goto_next_section,
            width=30,
            state="disabled",
        )
        self.next_section_button.grid(row=0, column=6, padx=(1, 5), pady=5)

        self.jump_to_button = ctk.CTkButton(
            parent,
            text="➡️",
            command=self.jump_to_dialog,
            width=30,
            state="disabled",
        )
        self.jump_to_button.grid(row=0, column=7, padx=5, pady=5)

        self.snapshot_button = ctk.CTkButton(
            parent,
            text="📷",
            command=self.take_snapshot,
            width=30,
            state="disabled",
        )
        self.snapshot_button.grid(row=0, column=8, padx=5, pady=5)

    def setup_seekbar_canvases_ui(self, parent):
        self.seek_canvases = []
        for layer in self.layers:
            pady = (
                5 if layer == 1 else 0,
                5 if layer == len(self.layers) else 1,
            )
            seek_layer_button = ctk.CTkButton(
                parent,
                text=f"L{layer}",
                command=lambda l=layer: self.seek_layer_button_click(str(l)),
                fg_color="gray40",
                width=30,
                height=30,
            )
            seek_layer_button.grid(row=layer - 1, column=0, padx=5, pady=pady)

            seek_canvas = tk.Canvas(
                parent,
                height=30,
                bg="gray10",
                highlightthickness=0,
            )
            seek_canvas.grid(
                row=layer - 1,
                column=1,
                padx=(0, 10),
                pady=pady,
                sticky="ew",
            )

            self.seek_canvases.append(
                {
                    "layer": layer,
                    "layer_button": seek_layer_button,
                    "seek_canvas": seek_canvas,
                }
            )

        parent.grid_columnconfigure(0, weight=0)
        parent.grid_columnconfigure(1, weight=1)

    def clear_seekbar_canvases_ui(self):
        for seek_canvas_info in self.seek_canvases:
            seek_canvas_info["seek_canvas"].destroy()
            seek_canvas_info["layer_button"].destroy()
        self.seek_canvases = []

    def setup_split_control_ui(self, parent):
        self.mode_selector_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.mode_selector_frame.grid(
            row=0, column=0, padx=5, pady=0, sticky="w"
        )

        self.mode_selector = ctk.CTkButton(
            self.mode_selector_frame,
            text=t("Add mode"),
            command=self.toggle_mode,
            width=60,
            state="disabled",
        )
        self.mode_selector.grid(row=0, column=1, padx=(0, 5), pady=5)

        self.link_boundaries_enabled = ctk.CTkCheckBox(
            self.mode_selector_frame,
            text=t("Link boundaries"),
            command=self.toggle_link_boundaries,
            text_color_disabled="gray40",
            state="disabled",
        )
        self.link_boundaries_enabled.grid(
            row=0, column=2, padx=5, pady=5, sticky="w"
        )

        self.start_button = ctk.CTkButton(
            parent,
            text=t("Set Start Point"),
            command=self.set_start_point,
            state="disabled",
        )
        self.start_button.grid(row=0, column=2, padx=5, pady=5, sticky="ew")

        self.end_button = ctk.CTkButton(
            parent,
            text=t("Set End Point (Add Split)"),
            command=self.set_end_point,
            state="disabled",
        )
        self.end_button.grid(row=0, column=3, padx=5, pady=5, sticky="ew")

        self.length_label = ctk.CTkLabel(
            parent,
            width=80,
        )
        self.length_label.grid(row=0, column=4, padx=10, pady=5, sticky="ew")
        self.update_length_label(False)

        parent.grid_columnconfigure(0, weight=0)
        parent.grid_columnconfigure(1, weight=0)
        parent.grid_columnconfigure(2, weight=1)
        parent.grid_columnconfigure(3, weight=1)
        parent.grid_columnconfigure(4, weight=1)

    def set_mode(self, mode):
        """Set the mode selector value
        Args:
            mode (str): "Add" or "Edit"

        Returns: None
        """
        if mode not in ["Add", "Edit"]:
            raise ValueError('Mode must be "Add" or "Edit"')

        if mode == self.get_current_mode():
            return

        if mode == "Edit":
            mode_display_value = t("Edit mode")
            fg_color = "#2FA572"
            hover_color = "#106A43"
        else:
            mode_display_value = t("Add mode")
            fg_color = "#1f6aa5"
            hover_color = "#144870"
        self.mode_selector.configure(
            text=mode_display_value, fg_color=fg_color, hover_color=hover_color
        )

    def toggle_mode(self, event=None):
        """Toggle between Add/Edit mode
        Returns: None
        """
        current_mode = self.get_current_mode()
        new_mode = "Edit" if current_mode == "Add" else "Add"
        self.change_mode(new_mode)

    def change_mode(self, mode=None, select_segment=True):
        """Change between Add/Edit mode
        Args:
            mode (str, optional): "Add" or "Edit". If None, use current selector value. Defaults to None.

        Returns: None
        """
        if mode is None or mode not in ["Add", "Edit"]:
            mode = self.get_current_mode()

        if mode == "Edit":
            if self.vp is None:
                messagebox.showwarning(
                    t("Warning"), t("No video loaded to edit segments.")
                )
                return

            if self.selected_segment_id is not None:
                segment = self.vp.segments.get_segment_by_id(
                    self.selected_segment_id
                )
            else:
                segment = self.vp.segments.get_segment_by_time(
                    self.current_frame / self.vp.fps,
                    self.selected_layer,
                )

            if segment is None:
                messagebox.showwarning(
                    t("Warning"), t("No segments available to edit.")
                )
                mode = "Add"
                mode_display_value = t("Add mode")

        if mode == "Edit":
            self.status_text.info(t("Edit mode enabled"))

            if select_segment:
                self.select_segment_id(segment.segment_id)
        else:
            # Default to Add mode
            self.status_text.info(t("Add mode enabled"))
            if select_segment:
                self.unselect_segment_id()

        # Update selector if needed
        self.set_mode(mode)

    def get_current_mode(self):
        return (
            "Edit"
            if self.mode_selector.cget("text") == t("Edit mode")
            else "Add"
        )

    def toggle_link_boundaries(self):
        if self.link_boundaries_enabled.get():
            self.status_text.info(
                t("Link mode enabled")
                + ": "
                + "("
                + t(
                    "Segment boundaries will be synchronized "
                    + "with adjacent segments."
                )
                + ")"
            )
        else:
            self.status_text.info(
                t("Link mode disabled")
                + ": "
                + "("
                + t("Segment boundaries can be set independently.")
                + ")"
            )

    def enable_toggle_link_boundaries(self, enable=True):
        if enable:
            self.link_boundaries_enabled.configure(state="normal")
        else:
            self.link_boundaries_enabled.configure(state="disabled")

    def setup_separator_ui(self, parent):
        # Separator (resize bar)
        self.separator = ctk.CTkFrame(
            parent,
            fg_color="#4a4a4a",
            width=5,
            cursor="sb_h_double_arrow",
        )
        self.separator.grid(row=0, column=1, sticky="ns", padx=0, pady=10)
        self.separator.bind("<Button-1>", self.start_resize)
        self.separator.bind("<B1-Motion>", self.do_resize)

        self.resize_start_x = 0
        self.left_width = 800  # Initial width

    def setup_right_ui(self, frame):
        # Right: Segment list and execute button
        self.right_frame = ctk.CTkFrame(frame)
        self.right_frame.grid(
            row=0, column=2, padx=(0, 10), pady=(10, 0), sticky="nsew"
        )
        self.right_frame.grid_rowconfigure(1, weight=1)
        self.right_frame.grid_columnconfigure(0, weight=1)

        self.show_full_list = ctk.CTkCheckBox(
            self.right_frame,
            text=t("Full"),
            command=self.refresh_all_segments_in_list,
        )
        self.show_full_list.grid(
            row=0, column=0, padx=(90, 10), pady=5, sticky="w"
        )

        # Title
        self.list_label = ctk.CTkLabel(
            self.right_frame,
            text=t("Segment List"),
            font=ctk.CTkFont(size=16, weight="bold"),
        )
        self.list_label.grid(row=0, column=0, padx=10, pady=10)

        # Clear button
        self.clear_button = ctk.CTkButton(
            self.right_frame,
            text=t("Clear"),
            command=self.clear_list,
            fg_color="gray",
            hover_color="darkgray",
            width=80,
        )
        self.clear_button.grid(row=0, column=0, padx=10, pady=5, sticky="e")

        # Reset index button
        self.reset_index_button = ctk.CTkButton(
            self.right_frame,
            text=t("Reset IDs"),
            command=self.reset_segment_indices,
            fg_color="gray",
            hover_color="darkgray",
            width=80,
        )
        self.reset_index_button.grid(
            row=0, column=0, padx=(10, 100), pady=5, sticky="e"
        )

        # layer label
        self.layer_label = ctk.CTkLabel(
            self.right_frame,
            text=f"{t("layer")}: {self.selected_layer}",
        )
        self.layer_label.grid(row=0, column=0, padx=10, pady=5, sticky="w")

        # Segment list display (scrollable)
        self.list_frame = ctk.CTkScrollableFrame(self.right_frame)
        self.list_frame.grid(row=1, column=0, padx=10, pady=5, sticky="nsew")
        self.list_frame.grid_columnconfigure(0, weight=1)
        self.setup_segment_list_ui(self.list_frame)

        # Output folder selection
        self.output_frame = ctk.CTkFrame(self.right_frame)
        self.output_frame.grid(row=2, column=0, padx=10, pady=5, sticky="ew")

        ctk.CTkLabel(self.output_frame, text=t("Output") + ":").grid(
            row=0, column=0, padx=5, pady=5
        )
        self.output_button = ctk.CTkButton(
            self.output_frame,
            text=t("Select output folder"),
            command=self.select_output_folder,
            width=150,
        )
        self.output_button.grid(row=0, column=1, padx=5, pady=5)

        self.execute_buttons_frame = ctk.CTkFrame(
            self.right_frame, fg_color="transparent"
        )
        self.execute_buttons_frame.grid(
            row=3, column=0, padx=10, pady=0, sticky="ew"
        )

        # Execute button
        self.execute_split_multiple_button = ctk.CTkButton(
            self.execute_buttons_frame,
            text=t("Split All Segments in List"),
            command=self.execute_split_multiple,
            height=50,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color="green",
            hover_color="darkgreen",
            state="disabled",
        )
        self.execute_split_multiple_button.grid(
            row=0, column=0, padx=10, pady=20, sticky="ew"
        )

        self.execute_split_single_button = ctk.CTkButton(
            self.execute_buttons_frame,
            text=t("Split Selected Segment"),
            command=self.execute_split_single,
            height=50,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color="green",
            hover_color="darkgreen",
            state="disabled",
        )
        self.execute_split_single_button.grid(
            row=0, column=1, padx=10, pady=20, sticky="ew"
        )

        # Progress bar
        self.progress = ctk.CTkProgressBar(self.right_frame)
        self.progress.grid(row=5, column=0, padx=10, pady=5, sticky="ew")
        self.progress.set(0)

        self.progress_label = ctk.CTkLabel(self.right_frame, text="")
        self.progress_label.grid(row=6, column=0, padx=10, pady=5)

    def setup_segment_list_ui(self, parent):
        # Header
        self.header_frame = ctk.CTkFrame(parent)
        self.header_frame.grid(row=0, column=0, sticky="ew", pady=5)
        ctk.CTkLabel(self.header_frame, text=t("ID"), width=30).grid(
            row=0, column=0, padx=2
        )
        ctk.CTkLabel(self.header_frame, text=t("L"), width=30).grid(
            row=0, column=1, padx=2
        )
        ctk.CTkButton(
            self.header_frame, text=t("Title"), command=self.sort_list_by_title
        ).grid(row=0, column=2, padx=2)
        ctk.CTkButton(
            self.header_frame,
            text=t("Start"),
            width=90,
            command=self.sort_list_by_start,
        ).grid(row=0, column=3, padx=2)
        ctk.CTkLabel(self.header_frame, text=t("End"), width=90).grid(
            row=0, column=4, padx=2
        )
        ctk.CTkLabel(self.header_frame, text=t("Length"), width=80).grid(
            row=0, column=5, padx=2
        )
        ctk.CTkLabel(self.header_frame, text=t("Del."), width=30).grid(
            row=0, column=6, padx=2
        )

        self.header_frame.grid_columnconfigure(2, weight=1)

        # List container
        self.list_container = ctk.CTkFrame(parent)
        self.list_container.grid(row=1, column=0, sticky="ew")

        self.list_container.grid_columnconfigure(0, weight=1)

    def sort_list_by_title(self):
        if self.vp is None:
            return

        self.vp.segments.sort_segments_by_title()
        self.refresh_all_segments_in_list()
        self.status_text.info(t("Segment list sorted by title."))

    def sort_list_by_start(self):
        if self.vp is None:
            return

        self.vp.segments.sort_segments_by_start_time()
        self.refresh_all_segments_in_list()
        self.status_text.info(t("Segment list sorted by start time."))

    def seekbar_resize_event(self, event):
        self.after(10, self.draw_all_segment_ranges)

    def open_settings(self):
        # Open settings dialog
        settings_window = SettingsDialog(self)
        settings_window.grab_set()

    def load_video_dialog(self):
        file_path = utils.load_video_dialog()
        if file_path and os.path.exists(file_path):
            try:
                self.video_cache.clear()
                self.video_cache_for_head.clear()
                self.vp = VideoProject(file_path)
                self.preload_head_frames()
                self.reset_video_controls()
                self.refresh_all_segments_in_list()
            except Exception as e:
                messagebox.showerror(
                    t("Error"), t("Failed to load video file." + "\n" + str(e))
                )

    def reset_video_controls(self):
        self.seek_slider.configure(to=self.vp.total_frames - 1, state="normal")
        self.zoom_scale_selector.configure(state="normal")
        self.zoom_range_slider.configure(state="normal")
        self.play_button.configure(state="normal")
        self.prev_frame_button.configure(state="normal")
        self.next_frame_button.configure(state="normal")
        self.prev_section_button.configure(state="normal")
        self.next_section_button.configure(state="normal")
        self.rewind_10sec_button.configure(state="normal")
        self.fast_forward_10sec_button.configure(state="normal")
        self.jump_to_button.configure(state="normal")
        self.start_button.configure(state="normal")
        self.end_button.configure(state="normal")
        self.mode_selector.configure(state="normal")
        self.snapshot_button.configure(state="normal")

        self.current_frame = 0
        self.update_zoom_range_slider()
        self.update_zoom_range()
        self.update_frame()
        self.update_time_label()
        self.update_seekbar_time_labels()
        self.draw_all_segment_ranges()

        self.update_length_label(False)

    def preload_head_frames(self):
        """Preload first N frames into cache for to improve stability"""
        self.status_text.info(f"{t('Start preloading frames')}...")

        # Note: If using set to 0, it may cause unexpected gap in some videos.
        # self.vp.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

        max_frames = min(
            self.video_cache_for_head_frame_count, self.vp.total_frames
        )

        for i in range(max_frames):
            ret, frame = self.vp.cap.read()
            if ret:
                self.video_cache_for_head.set(i, frame.copy())
            else:
                break

        self.status_text.info(
            f"{t('[n] frames preloaded.').replace('[n]', str(max_frames))}"
        )

        # Reset to frame 0
        self.vp.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    def update_frame(self):
        if self.vp is None or self.vp.cap is None:
            return

        if self.current_frame <= self.video_cache_for_head_frame_count:
            frame = self.video_cache_for_head.get(self.current_frame)
        else:
            frame = self.video_cache.get(self.current_frame)

        if frame is None:
            if self.current_frame != self.vp.cap.get(cv2.CAP_PROP_POS_FRAMES):
                self.vp.cap.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame)
                if self.current_frame != self.vp.cap.get(
                    cv2.CAP_PROP_POS_FRAMES
                ):
                    print(
                        "[Warn]Frame seek failed. "
                        + f"Expected: {self.current_frame}, "
                        + f"Actual: {self.vp.cap.get(cv2.CAP_PROP_POS_FRAMES)}"
                    )
                    # Sample code for reloading VideoCapture
                    # self.vp.cap.release()
                    # self.vp.cap = cv2.VideoCapture(self.vp.video_path)
                    # self.vp.cap.set(
                    #     cv2.CAP_PROP_POS_FRAMES, self.current_frame
                    # )
                    self.status_text.warning(
                        t(
                            "Frame seek failed. "
                            + "If problems persist, please reload the video."
                        )
                        + f"Expected: {self.current_frame}, "
                        + f"Actual: {self.vp.cap.get(cv2.CAP_PROP_POS_FRAMES)}. "
                    )
            ret, frame = self.vp.cap.read()

            if ret:
                self.current_frame = (
                    int(self.vp.cap.get(cv2.CAP_PROP_POS_FRAMES)) - 1
                )
                if self.current_frame <= self.video_cache_for_head_frame_count:
                    self.video_cache_for_head.set(
                        self.current_frame, frame.copy()
                    )
                else:
                    self.video_cache.set(self.current_frame, frame.copy())

        if frame is None:
            print(f"[Error] Failed to read frame {self.current_frame}")
            self.status_text.error(
                t("Error reading frame") + f": {self.current_frame}"
            )
            return

        # Check if frame is valid (not empty and has correct shape)
        if frame.size == 0:
            print(f"[Error] Frame {self.current_frame} is empty")
            return

        try:

            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            # Resize
            h, w = frame.shape[:2]
            max_width = 800
            max_height = 450
            scale = min(max_width / w, max_height / h)
            new_w, new_h = round(w * scale), round(h * scale)

            frame = cv2.resize(frame, (new_w, new_h))

            img = Image.fromarray(frame)
            ctk_img = ctk.CTkImage(
                light_image=img, dark_image=img, size=(new_w, new_h)
            )

            self.video_label.configure(image=ctk_img, text="")
            self.video_label.image = ctk_img
        except cv2.error as e:
            print(f"[Error] OpenCV error at frame {self.current_frame}: {e}")
            self.status_text.error(
                t("Error reading frame") + f": {self.current_frame}"
            )
        except Exception as e:
            print(
                f"[Error] Unexpected error at frame {self.current_frame}: {e}"
            )
            self.status_text.error(t("Unexpected error") + f": {str(e)}")

    def toggle_playback(self, event=None):
        if self.is_playing:
            self.pause_video()
        else:
            self.play_video()

    def play_video(self):
        if not self.is_playing:
            self.is_playing = True
            self.play_button.configure(
                text="⏸ " + t("Pause"),
                fg_color="indian red",
                hover_color="firebrick",
            )
            threading.Thread(target=self.play_video_core, daemon=True).start()

    def pause_video(self):
        if self.is_playing:
            self.is_playing = False
            self.play_button.configure(
                text="▶ " + t("Play"),
                fg_color="#1f6aa5",
                hover_color="#144870",
            )

    def goto_prev_frame(self, event=None):
        """Go back 1 frame"""
        self.pause_video()

        if self.current_frame > 0:
            self.current_frame -= 1
            self.update_frame()
            self.update_seekbar_slider_value()
            self.update_time_label()
            self.draw_all_segment_ranges()

    def on_prev_frame_button_press(self, event):
        self.prev_frame_click_count += 1
        if self.prev_frame_click_count > 1000000:
            self.prev_frame_click_count = 0
        if self.vp is None:
            return
        prev_frame_click = self.prev_frame_click_count
        self.prev_frame_auto_repeat = True

        def repeat():
            if (
                self.prev_frame_auto_repeat
                and prev_frame_click == self.prev_frame_click_count
            ):
                self.goto_prev_frame()
                self.after(self.auto_repeat_interval_ms, repeat)

        repeat()

    def on_prev_frame_button_release(self, event):
        self.prev_frame_auto_repeat = False

    def on_next_frame_button_press(self, event):
        self.next_frame_click_count += 1
        if self.next_frame_click_count > 1000000:
            self.next_frame_click_count = 0
        if self.vp is None:
            return
        next_frame_click = self.next_frame_click_count
        self.next_frame_auto_repeat = True

        def repeat():
            if (
                self.next_frame_auto_repeat
                and next_frame_click == self.next_frame_click_count
            ):
                self.goto_next_frame()
                self.after(self.auto_repeat_interval_ms, repeat)

        repeat()

    def on_next_frame_button_release(self, event):
        self.next_frame_auto_repeat = False

    def goto_next_frame(self, event=None):
        """Advance 1 frame"""
        self.pause_video()

        if self.current_frame < self.vp.total_frames - 1:
            self.current_frame += 1
            self.update_frame()
            self.update_seekbar_slider_value()
            self.update_time_label()
            self.draw_all_segment_ranges()

    def play_video_core(self):
        while (
            self.is_playing and self.current_frame < self.vp.total_frames - 1
        ):
            self.current_frame += 1
            self.update_frame()
            self.update_seekbar_slider_value()
            self.update_time_label()
            is_seekbar_range_changed = (
                self.seek_slider.cget("from_") == self.current_frame
                or self.seek_slider.cget("to") == self.current_frame
            )
            if is_seekbar_range_changed:
                self.draw_all_segment_ranges()
            else:
                self.draw_segment_ranges()

            # TODO: Use more precise timing control. Temporary disabled for now.
            # self.after(round(1000 / self.vp.fps))

        if self.current_frame >= self.vp.total_frames - 1:
            self.pause_video()

    def goto_next_section(self, event=None):
        if self.vp is None:
            return

        if self.current_frame >= self.vp.total_frames - 1:
            return

        current_time = self.current_frame / self.vp.fps
        current_segments = self.vp.segments.get_segments_by_time(
            current_time,
            self.selected_layer,
        )

        if not current_segments:
            next_segment = self.vp.segments.get_next_segment_by_time(
                current_time, self.selected_layer
            )
        else:
            if len(current_segments) > 1:
                # If in multiple segments, pick the last one
                current_segment = sorted(
                    current_segments, key=lambda s: s.start_frame, reverse=True
                )[0]
            else:
                current_segment = current_segments[0]

            if self.current_frame < current_segment.end_frame:
                # If in a segment, jump to its end
                self.jump_to_frame(current_segment.end_frame)
                return

            next_segment = self.vp.segments.get_next_segment(current_segment)

        if next_segment is None:
            self.jump_to_frame(self.vp.total_frames - 1)
        else:
            self.jump_to_frame(
                next_segment.start_frame
                if next_segment.start_frame > self.current_frame
                else next_segment.end_frame
            )

    def goto_prev_section(self, event=None):
        if self.vp is None:
            return

        if self.current_frame <= 0:
            return

        current_time = self.current_frame / self.vp.fps
        current_segments = self.vp.segments.get_segments_by_time(
            current_time,
            self.selected_layer,
        )

        if not current_segments:
            prev_segment = self.vp.segments.get_prev_segment_by_time(
                current_time, self.selected_layer
            )
        else:
            if len(current_segments) > 1:
                # If in multiple segments, pick the first one
                current_segment = sorted(
                    current_segments, key=lambda s: s.start_frame
                )[0]
            else:
                current_segment = current_segments[0]

            if self.current_frame > current_segment.start_frame:
                # If in a segment, jump to its start
                self.jump_to_frame(current_segment.start_frame)
                return

            prev_segment = self.vp.segments.get_prev_segment(current_segment)

        if prev_segment is None:
            self.jump_to_frame(0)
        else:
            self.jump_to_frame(
                prev_segment.end_frame
                if prev_segment.end_frame < self.current_frame
                else prev_segment.start_frame
            )

    def rewind_10sec(self):
        if self.vp is None:
            return

        target_frame = self.current_frame - round(10 * self.vp.fps)
        self.jump_to_frame(target_frame)

    def fast_forward_10sec(self):
        if self.vp is None:
            return

        target_frame = self.current_frame + round(10 * self.vp.fps)
        self.jump_to_frame(target_frame)

    def jump_to_frame(self, frame_num):
        self.current_frame = max(0, min(frame_num, self.vp.total_frames - 1))
        self.update_zoom_range()
        self.update_frame()
        self.update_time_label()
        self.update_seekbar_slider_value()
        self.update_seekbar_time_labels()
        self.draw_all_segment_ranges()

    def jump_to_time(self, time_sec):
        frame_num = round(time_sec * self.vp.fps)
        self.jump_to_frame(frame_num)

    def jump_to_dialog(self):
        current_time_str = utils.format_time(self.current_frame / self.vp.fps)
        dialog = CustomCTkInputDialog(
            title=t("Jump to Time / Frame"),
            text=t("Enter time (mm:ss.sss format) or frame number")
            + ":\n"
            + "( "
            + t("Current")
            + ": "
            + f"{current_time_str} / {self.current_frame}"
            + " )",
            initialvalue=f"{current_time_str}",
        )

        ret = dialog.get_input()

        if ret:
            if ret.isdigit():
                frame_num = int(ret)
                self.jump_to_frame(frame_num)
            else:
                try:
                    self.jump_to_time(utils.time_str_to_sec(ret))
                except ValueError:
                    messagebox.showerror(
                        t("Error"), t("Invalid format entered.")
                    )

    def take_snapshot(self):
        if self.vp is None:
            return

        base_name = os.path.splitext(os.path.basename(self.vp.video_path))[0]
        current_time_str = utils.format_time(
            self.current_frame / self.vp.fps, "hh-mm-ss.sss"
        )

        file_path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG Image", "*.png"), ("All Files", "*.*")],
            title=t("Save Snapshot As"),
            initialfile=f"{base_name}_"
            + f"{current_time_str}"
            + f"[{self.current_frame}].png",
        )

        if file_path:
            self.vp.cap.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame)
            ret, frame = self.vp.cap.read()

            if ret:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(frame_rgb)
                img.save(file_path)
                self.status_text.info(
                    t("Snapshot saved to") + f": {file_path}"
                )
            else:
                messagebox.showerror(
                    t("Error"), t("Failed to capture snapshot.")
                )

    def seek_video(self, value):
        """Seek video to specified frame value"""
        value = int(value)
        if self.current_frame != value:
            self.current_frame = value
            self.current_frame = max(
                0, min(self.current_frame, self.vp.total_frames - 1)
            )
            self.update_frame()
            self.update_time_label()
            self.draw_all_segment_ranges()

    def seek_video_timer_event(self):
        shift_frames = 0
        if self.is_seeking:
            if (
                self.current_frame > 0
                and self.seek_slider.cget("from_") == self.current_frame
            ):
                shift_frames = -1
            elif (
                self.current_frame < self.vp.total_frames - 1
                and self.seek_slider.cget("to") == self.current_frame
            ):
                shift_frames = 1

            if shift_frames != 0:
                self.current_frame += shift_frames
                self.update_frame()
                self.update_time_label()
                self.update_zoom_range(shift_frames=shift_frames)
                self.update_seekbar_time_labels()
                self.draw_all_segment_ranges()

            self.after(int(1000 / self.vp.fps), self.seek_video_timer_event)

    def on_seek_start(self, event):
        self.is_seeking = True
        self.seek_video_timer_event()

    def on_seek_end(self, event):
        self.is_seeking = False

    def zoom_scale(self):
        return int(self.zoom_scale_selector.get().rstrip("%"))

    def update_zoom_scale(self, value):
        if self.zoom_scale() != value:
            self.zoom_scale_selector.set(f"{round(int(value))}%")
        self.update_zoom_range_slider()
        self.update_zoom_range()
        self.update_seekbar_slider_value()
        self.update_seekbar_time_labels()
        self.draw_all_segment_ranges()

    def on_zoom_scale_selector_change(self, value):
        self.update_zoom_scale(int(value.rstrip("%")))

    def on_zoom_range_slider_update(self, value):
        """Update zoom range based on slider value"""
        self.update_zoom_range(center_frame=round(value))
        self.update_seekbar_slider_value(adjust_zoom_range=False)
        self.update_seekbar_time_labels()
        self.draw_all_segment_ranges()

    def update_zoom_range_slider(self):
        if self.vp is None:
            return

        zoom_scale = self.zoom_scale()

        if zoom_scale == 100:
            self.zoom_range_slider.configure(
                from_=0, to=2, number_of_steps=2, state="disabled"
            )
            self.zoom_range_slider.set(1)
            return

        visible_frames = round(self.vp.total_frames * (zoom_scale / 100))
        half_visible_frames = round(visible_frames / 2)
        min_frame = half_visible_frames
        max_frame = self.vp.total_frames - (
            visible_frames - half_visible_frames
        )
        self.zoom_range_slider.configure(
            from_=min_frame,
            to=max_frame,
            number_of_steps=self.vp.total_frames - visible_frames,
            state="normal",
        )

        self.zoom_range_slider.set(
            min(max_frame, max(min_frame, self.current_frame))
        )

    def update_seekbar_time_labels(self):
        """Update seekbar display range time labels"""
        if self.vp is None or self.vp.total_frames == 0:
            return

        start_frame = self.seek_slider.cget("from_")
        start_time = start_frame / self.vp.fps

        end_frame = self.seek_slider.cget("to")
        end_time = end_frame / self.vp.fps

        self.seekbar_start_label.configure(text=utils.format_time(start_time))
        self.seekbar_end_label.configure(text=utils.format_time(end_time))

    def update_seekbar_slider_value(self, adjust_zoom_range=True):
        """Update seekbar slider value based on current frame"""
        if self.vp is None or self.vp.total_frames == 0:
            return

        # Check current slider range
        slider_from = self.seek_slider.cget("from_")
        slider_to = self.seek_slider.cget("to")

        # Adjust zoom range if current frame is out of range
        if adjust_zoom_range and (
            self.current_frame < slider_from or self.current_frame > slider_to
        ):
            if self.current_frame < slider_from:
                shift_frames = self.current_frame - slider_from
            else:
                shift_frames = self.current_frame - slider_to

            self.update_zoom_range(shift_frames=shift_frames)
            self.update_zoom_range_slider()
            self.update_seekbar_time_labels()

        # Update slider value
        self.seek_slider.set(self.current_frame)

    def update_zoom_range(self, center_frame=None, shift_frames=0):
        """Update seek slider range based on zoom"""
        if self.vp is None or self.vp.total_frames == 0:
            return

        visible_frames = round(
            self.vp.total_frames * (self.zoom_scale() / 100)
        )

        current_start = self.seek_slider.cget("from_")
        current_end = self.seek_slider.cget("to")
        current_visible_frames = current_end - current_start

        relative_slider_position = (
            self.current_frame - current_start
        ) / current_visible_frames

        if center_frame is not None:
            visible_start_frame = max(
                0, center_frame - round(visible_frames / 2)
            )
            visible_end_frame = min(
                self.vp.total_frames - 1,
                visible_start_frame + visible_frames,
            )
        else:
            visible_start_frame = max(
                0,
                self.current_frame
                - round(visible_frames * relative_slider_position)
                + shift_frames,
            )
            visible_end_frame = min(
                self.vp.total_frames - 1 + shift_frames,
                visible_start_frame + visible_frames,
            )

        # Adjust start/end if range is smaller than expected
        if visible_end_frame - visible_start_frame < visible_frames - 1:
            if visible_start_frame == 0:
                visible_end_frame = min(
                    self.vp.total_frames - 1, visible_frames
                )
            else:
                visible_start_frame = max(
                    0, visible_end_frame - visible_frames
                )

        # Set seekbar range to visible range
        self.seek_slider.configure(
            from_=visible_start_frame, to=visible_end_frame
        )

        # Reflect current frame on slider
        self.seek_slider.set(self.current_frame)

    def seek_layer_button_click(self, layer):
        self.change_layer(str(layer))
        self.unselect_segment_id()

    def change_layer(self, layer_str, update_segment_list=True):
        self.selected_layer = int(layer_str)
        self.layer_label.configure(text=f"{t('layer')}: {self.selected_layer}")
        if update_segment_list:
            self.refresh_all_segments_in_list()
        for layer in self.layers:
            self.draw_segment_ranges(
                layer=layer, draw_current=layer == self.selected_layer
            )
            self.seek_canvases[layer - 1]["layer_button"].configure(
                fg_color=(
                    "#1F6AA5"
                    if layer == self.selected_layer
                    else "transparent"
                )
            )

    def switch_to_upper_layer(self, event=None):
        if self.selected_layer > self.layers[0]:
            self.change_layer(str(self.selected_layer - 1))

    def switch_to_lower_layer(self, event=None):
        if self.selected_layer < self.layers[-1]:
            self.change_layer(str(self.selected_layer + 1))

    def select_segment_id_with_jump(self, id):
        position = "start" if self.selected_segment_id != id else None

        self.select_segment_id(id)

        if id is not None:
            self.jump_to_segment(
                int(id),
                position=position,
            )

    def select_segment_id(self, id=None):
        self.selected_segment_id = id

        self.reset_segment_list_id_color()

        if id is None:
            segment = None
            self.enable_toggle_link_boundaries(False)
            if self.get_current_mode() == "Edit":
                self.change_mode("Add", False)
        else:
            segment = self.vp.segments.get_segment_by_id(id)
            if segment is None:
                self.status_text.warning(t("No segments to display"))
                self.select_segment_id()
                return
            self.enable_toggle_link_boundaries(True)
            if self.get_current_mode() == "Add":
                self.change_mode("Edit", False)

            if segment.layer != self.selected_layer:
                self.change_layer(str(segment.layer), False)

            self.set_segment_list_id_color(id)

        self.draw_all_segment_ranges()

    def set_segment_list_id_color(self, segment_id):
        for segment in self.vp.segments:
            if segment.segment_id == segment_id and (
                segment.layer == self.selected_layer
                or self.show_full_list.get()
            ):
                ui = segment.ui
                if ui and ui["num_btn"].winfo_exists():
                    ui["num_btn"].configure(
                        fg_color="#1F6AA5", hover_color="#36719F"
                    )
                else:
                    print("No UI found for segment:", segment)

    def reset_segment_list_id_color(self):
        if self.vp is None:
            return

        for segment in self.vp.segments:
            ui = segment.ui
            if (
                segment.layer == self.selected_layer
                or self.show_full_list.get()
            ):
                if ui and ui["num_btn"].winfo_exists():
                    ui["num_btn"].configure(
                        fg_color="gray30", hover_color="gray50"
                    )
                else:
                    print("No UI found for segment:", segment)

    def unselect_segment_id(self):
        self.select_segment_id()

    def delete_all_canvas_items(self):
        for canvas_info in self.seek_canvases:
            canvas = canvas_info["seek_canvas"]
            canvas.delete("all")

    def draw_all_segment_ranges(self):
        for layer in self.layers:
            self.draw_segment_ranges(
                layer=layer, draw_current=layer == self.selected_layer
            )

    def draw_segment_ranges(self, layer=None, draw_current=None):
        if layer is None:
            layer = self.selected_layer
        if draw_current is None:
            draw_current = layer == self.selected_layer

        seek_canvas = self.seek_canvases[layer - 1]["seek_canvas"]

        # Clear the canvas
        seek_canvas.delete("all")

        if self.vp is None or self.vp.total_frames == 0:
            return

        canvas_width = seek_canvas.winfo_width()
        if canvas_width <= 1:
            canvas_width = 800

        canvas_height = seek_canvas.winfo_height()

        # Calculate zoom range
        visible_start_frame = self.seek_slider.cget("from_")
        visible_end_frame = self.seek_slider.cget("to")
        visible_range = visible_end_frame - visible_start_frame

        # Draw segment ranges
        filtered_segment_list = self.vp.segments.filter_by_layers([layer])

        for segment in filtered_segment_list:
            start_frame = segment.start_frame
            end_frame = segment.end_frame

            id_is_selected = (
                segment.segment_id == self.selected_segment_id
                and self.get_current_mode() == "Edit"
            )
            range_color = "#ffff00" if id_is_selected else "#00ff00"

            # Draw only if within zoom range
            if (
                end_frame >= visible_start_frame
                and start_frame <= visible_end_frame
            ):
                # Calculate position on canvas (considering margins)
                x1 = (
                    (start_frame - visible_start_frame) / visible_range
                ) * canvas_width
                x2 = (
                    (end_frame - visible_start_frame) / visible_range
                ) * canvas_width

                x1 = max(0, x1)
                x2 = min(canvas_width, x2)

                # Draw range (semi-transparent green)
                seek_canvas.create_rectangle(
                    x1,
                    0,
                    x2,
                    canvas_height,
                    fill=range_color,
                    stipple="gray50",
                    outline=range_color,
                    width=2,
                )

        # If start point is set
        if draw_current and self.start_frame is not None:
            start_frame = self.start_frame
            if (
                start_frame >= visible_start_frame
                and start_frame <= visible_end_frame
            ):
                x = (
                    (start_frame - visible_start_frame) / visible_range
                ) * canvas_width
                seek_canvas.create_line(
                    x, 0, x, canvas_height, fill="#ffff00", width=3
                )

        # Draw current position
        if (
            draw_current
            and self.current_frame >= visible_start_frame
            and self.current_frame <= visible_end_frame
        ):
            x = (
                (self.current_frame - visible_start_frame) / visible_range
            ) * canvas_width
            seek_canvas.create_line(
                x, 0, x, canvas_height, fill="#ff0000", width=2
            )

    def update_time_label(self):
        current_time = self.current_frame / self.vp.fps
        total_time = self.vp.duration

        # Display up to milliseconds
        current_str = utils.format_time(current_time)
        total_str = utils.format_time(total_time)

        self.time_label.configure(text=f"{current_str} / {total_str}")

        # Display frame count
        self.frame_label.configure(
            text=f"{t("Frame")}: {self.current_frame} / {self.vp.total_frames - 1}"
        )

        # Update end button label if start point is set
        self.update_length_label()

    def update_length_label(self, enabled=True):
        if self.start_frame is not None and enabled:
            elapsed_frame = self.current_frame - self.start_frame
            length_sec = elapsed_frame / self.vp.fps
        else:
            length_sec = 0

        sign = "-" if length_sec < 0 else " "
        self.length_label.configure(
            text=f"{t('Length')}: {sign}{utils.format_time(abs(length_sec))}",
            # state=("normal" if enabled else "disabled"),
            text_color=(
                ("white" if length_sec > 0 else "indian red")
                if enabled
                else "gray"
            ),
        )

    def set_start_point(self, event=None):
        if self.get_current_mode() == "Add":
            self.set_new_start_point()
        else:
            self.edit_start_point()

    def set_new_start_point(self):
        """Set the start point at the next free time from current position"""
        if self.vp is None:
            return

        if self.start_frame is not None:
            self.reset_start_point()
            self.status_text.info(t("Start point reset"))
            return

        free_time = self.vp.segments.get_next_free_time(
            self.current_frame / self.vp.fps, self.selected_layer
        )

        if free_time is None:
            messagebox.showwarning(
                t("Warning"), t("No free space available to set start point")
            )
            return

        self.start_frame = round(free_time * self.vp.fps)

        # Set current position to new start point
        if self.start_frame != self.current_frame:
            self.jump_to_frame(self.start_frame)
            self.status_text.info(
                t("Start point set at next available position automatically")
            )

        # Update button display
        start_time_str = utils.format_time(self.start_frame / self.vp.fps)
        self.start_button.configure(
            text=f"{t("Start")}: {start_time_str} (F:{self.start_frame})",
            fg_color="green",
            hover_color="darkgreen",
        )

        self.draw_segment_ranges()

    def edit_start_point(self, id=None):
        """Edit the start point to a specific time"""
        if self.vp is None:
            return

        if id is None:
            id = self.selected_segment_id

        segment = self.vp.segments.get_segment_by_id(id)
        if segment is None:
            messagebox.showwarning(
                t("Warning"), t("Selected segment not found")
            )
            return
        old_start_time = segment.start_time

        selected_segment = self.vp.segments.get_segment_by_time(
            self.current_frame / self.vp.fps,
            layer=segment.layer,
            include_start=True,
            include_end=False,
        )

        last_segment = None
        if selected_segment is not None:
            previous_segments = self.vp.segments.get_segments_before_time(
                segment.start_time, segment.layer
            )

            if previous_segments:
                # Note: previous_segments will always contain at least the
                # current segment
                last_segment = previous_segments[-1]

                if selected_segment.segment_id != id:
                    if (
                        self.current_frame / self.vp.fps
                        <= last_segment.start_time
                    ):
                        messagebox.showwarning(
                            t("Warning"),
                            t(
                                "Start point must be after "
                                + "the previous segment begins."
                            ),
                        )
                        return

        new_start_time = self.current_frame / self.vp.fps

        self.update_segment_time(id, "start", str(new_start_time))

        if last_segment is not None and (
            last_segment.end_time > new_start_time
            or (
                last_segment.end_time == old_start_time
                and self.link_boundaries_enabled.get()
            )
        ):
            self.update_segment_time(
                last_segment.segment_id, "end", str(new_start_time)
            )
            self.status_text.info(
                t(
                    "Start point updated and previous segment's end point "
                    + "adjusted."
                )
            )

    def set_end_point(self, event=None):
        if self.get_current_mode() == "Add":
            self.set_new_end_point()
        else:
            self.edit_end_point()

    def set_new_end_point(self):
        """Set the end point at the previous free time from current position"""
        if self.vp is None:
            return

        if self.start_frame is None:
            messagebox.showwarning(
                t("Warning"), t("Start point must be set first")
            )
            return

        if self.current_frame <= self.start_frame:
            messagebox.showwarning(
                t("Warning"),
                t("End point must be after start point"),
            )
            return

        free_time = self.vp.segments.get_previous_free_time(
            self.current_frame / self.vp.fps, self.selected_layer
        )

        if free_time is None:
            messagebox.showwarning(
                t("Warning"), t("No free space available to set end point")
            )
            return

        start_time = self.start_frame / self.vp.fps
        end_time = free_time
        end_frame = round(end_time * self.vp.fps)

        if end_time <= start_time:
            # Note: This should not happen due to previous checks, but just in
            # case
            messagebox.showwarning(
                t("Warning"), t("End point must be after start point")
            )
            return

        self.vp.segments.append(
            layer=self.selected_layer,
            start_frame=self.start_frame,
            end_frame=end_frame,
        )
        if end_frame != self.current_frame:
            self.jump_to_frame(end_frame)
            self.status_text.info(
                t(
                    "End point set at previous available position automatically"
                    + " and segment added."
                )
            )
        else:
            self.status_text.info(t("Segment added"))

        self.append_segment_to_segment_list(self.vp.segments.items[-1])

        # Reset start point button
        self.reset_start_point()

        if len(self.vp.segments) > 0:
            self.execute_split_multiple_button.configure(state="normal")
            self.execute_split_single_button.configure(state="normal")

    def edit_end_point(self, id=None):
        """Edit the end point to a specific time"""
        if self.vp is None:
            return

        if id is None:
            id = self.selected_segment_id

        segment = self.vp.segments.get_segment_by_id(id)
        if segment is None:
            messagebox.showwarning(
                t("Warning"), t("Selected segment not found")
            )
            return
        old_end_time = segment.end_time

        selected_segment = self.vp.segments.get_segment_by_time(
            self.current_frame / self.vp.fps,
            layer=segment.layer,
            include_start=False,
            include_end=True,
        )

        next_section = None
        if selected_segment is not None:
            next_sections = self.vp.segments.get_segments_after_time(
                segment.end_time, segment.layer
            )

            if next_sections:
                # Note: next_sections will always contain at least the
                # current segment
                next_section = next_sections[0]

                if selected_segment.segment_id != id:
                    if (
                        self.current_frame / self.vp.fps
                        > next_section.end_time
                    ):
                        messagebox.showwarning(
                            t("Warning"),
                            t(
                                "End point must be before "
                                + "the next segment ends."
                            ),
                        )
                        return

        new_end_time = self.current_frame / self.vp.fps

        self.update_segment_time(id, "end", str(new_end_time))

        if next_section is not None and (
            next_section.start_time <= new_end_time
            or (
                next_section.start_time == old_end_time
                and self.link_boundaries_enabled.get()
            )
        ):
            self.update_segment_time(
                next_section.segment_id, "start", str(new_end_time)
            )
            self.status_text.info(
                t(
                    "End point updated and next segment's start point "
                    + "adjusted."
                )
            )

    def reset_start_point(self):
        self.start_frame = None
        self.start_button.configure(
            text=t("Set Start Point"),
            fg_color=["#3B8ED0", "#1F6AA5"],  # Reset to default colors
            hover_color=["#36719F", "#144870"],
        )
        self.draw_segment_ranges()

        self.update_length_label(False)

    def refresh_all_segments_in_list(self):
        # Clear existing list
        for widget in self.list_container.winfo_children():
            widget.destroy()

        if self.vp is None:
            return

        # Redisplay the list
        if self.show_full_list.get():
            layers = self.layers
            self.layer_label.configure(text_color="gray")
        else:
            layers = [self.selected_layer]
            self.layer_label.configure(text_color="white")

        segment_list = [
            segment for segment in self.vp.segments if segment.layer in layers
        ]

        for segment in segment_list:
            self.append_segment_to_segment_list(segment)

    def append_segment_to_segment_list(self, segment):
        row_frame = ctk.CTkFrame(self.list_container)
        row_frame.grid(
            row=len(self.list_container.winfo_children()),
            column=0,
            sticky="ew",
            pady=2,
        )
        self.update_segment_in_segment_list(row_frame, segment)

    def update_segment_in_segment_list(self, row_frame, segment):
        segment_id = segment.segment_id
        layer = segment.layer
        is_selected = segment_id == self.selected_segment_id

        # Number button (jump to start position on click)
        num_btn = ctk.CTkButton(
            row_frame,
            text=str(segment_id),
            width=30,
            command=lambda _id=segment_id: self.select_segment_id_with_jump(
                _id
            ),
            fg_color="#1F6AA5" if is_selected else "gray30",
            hover_color="gray40",
        )
        num_btn.grid(row=0, column=0, padx=2)

        # layer label
        ctk.CTkLabel(row_frame, text=str(layer), width=30).grid(
            row=0, column=1, padx=2
        )

        # Title (editable)
        title_entry = ctk.CTkEntry(row_frame)
        title_entry.insert(0, segment.title)
        title_entry.grid(row=0, column=2, padx=2, sticky="ew")
        title_entry.bind(
            "<FocusOut>",
            lambda e, _id=segment_id, entry=title_entry: self.update_segment_title(
                _id, entry.get()
            ),
        )
        title_entry.bind(
            "<Return>",
            lambda e, _id=segment_id, entry=title_entry: self.update_segment_title(
                _id, entry.get()
            ),
        )

        # Start time (editable)
        start_entry = ctk.CTkEntry(row_frame, width=90)
        start_entry.insert(0, utils.format_time(segment.start_time))
        start_entry.grid(row=0, column=3, padx=2)
        start_entry.bind(
            "<FocusOut>",
            lambda e, _id=segment_id, entry=start_entry: self.update_segment_time(
                _id, "start", entry.get()
            ),
        )
        start_entry.bind(
            "<Return>",
            lambda e, _id=segment_id, entry=start_entry: self.update_segment_time(
                _id, "start", entry.get()
            ),
        )

        # End time (editable)
        end_entry = ctk.CTkEntry(row_frame, width=90)
        end_entry.insert(0, utils.format_time(segment.end_time))
        end_entry.grid(row=0, column=4, padx=2)
        end_entry.bind(
            "<FocusOut>",
            lambda e, _id=segment_id, entry=end_entry: self.update_segment_time(
                _id, "end", entry.get()
            ),
        )
        end_entry.bind(
            "<Return>",
            lambda e, _id=segment_id, entry=end_entry: self.update_segment_time(
                _id, "end", entry.get()
            ),
        )

        # Duration (auto-calculated)
        ctk.CTkLabel(
            row_frame,
            text=utils.format_time(segment.duration),
            width=80,
        ).grid(row=0, column=5, padx=2)

        # Delete button
        delete_btn = ctk.CTkButton(
            row_frame,
            text="×",
            width=30,
            command=lambda _id=segment_id: self.delete_segment(_id),
            fg_color="transparent",
            hover_color="darkred",
            border_color="darkred",
            border_width=1,
        )
        delete_btn.grid(row=0, column=6, padx=2)

        row_frame.grid_columnconfigure(2, weight=1)

        segment.ui = {
            "frame": row_frame,
            "num_btn": num_btn,
            "title_entry": title_entry,
            "start_entry": start_entry,
            "end_entry": end_entry,
        }

    def refresh_segment_in_list(self, segment):
        ui = segment.ui
        if ui is None:
            raise Exception("No UI found for segment")

        frame = ui["frame"]
        if not frame.winfo_exists():
            raise Exception("Segment UI frame does not exist")

        # Clear all ui inner frame
        for widget in frame.winfo_children():
            widget.destroy()

        self.update_segment_in_segment_list(frame, segment)

    def update_segment_title(self, id, title):
        """Update title"""
        segment = self.vp.segments.get_segment_by_id(id)
        if segment is not None:
            # Remove characters not allowed in filenames
            safe_title = re.sub(r'[\\/:*?"<>|]', "", title.strip())
            segment.title = safe_title
            try:
                self.refresh_segment_in_list(segment)
            except:
                self.refresh_all_segments_in_list()

    def jump_to_segment(self, id: int, position: str | None = None):
        """Jump to the start or end position of the specified segment.

        Args:
            id (int): Segment ID to jump to.
            position (str | None): Specifies which position to jump to.
                If "start" | "s", jumps to the start of the segment.
                If "end" | "e", jumps to the end of the segment.
                If "middle" | "m", jumps to the middle of the segment.
                If None, jumps to the start by default unless already at the start, in which case it jumps to the end.

        Returns:
            None: This function does not return a value. It updates the current frame and display based on the segment's position.
        """
        segment = self.vp.segments.get_segment_by_id(id)
        if segment is None:
            print("Segment not found")
            return

        layer = segment.layer

        if layer != self.selected_layer:
            self.change_layer(str(layer))

        start_frame = segment.start_frame

        if position is None or position not in (
            "start",
            "end",
            "middle",
            "s",
            "e",
            "m",
        ):
            position = "start" if self.current_frame != start_frame else "end"

        if position in ("start", "s"):
            # Jump to start
            target_frame = start_frame
            self.status_text.info(
                t("Jumped to the start of the selected segment")
            )
        elif position in ("end", "e"):
            # Jump to end
            # If already at start, jump to end
            target_frame = segment.end_frame
            self.status_text.info(
                t("Jumped to the end of the selected segment")
            )
        else:
            # Jump to middle
            mid_time = (segment.start_time + segment.end_time) / 2
            target_frame = round(mid_time * self.vp.fps)
            self.status_text.info(
                t("Jumped to the middle of the selected segment")
            )

        self.current_frame = target_frame
        self.current_frame = max(
            0, min(self.current_frame, self.vp.total_frames - 1)
        )

        # Stop if playing
        if self.is_playing:
            self.is_playing = False
            self.play_button.configure(text="▶ " + t("Play"))

        # Update display
        self.update_zoom_range()
        self.update_frame()
        self.update_seekbar_time_labels()
        self.update_time_label()
        self.draw_all_segment_ranges()

    def update_segment_time(self, id, time_type, time_str):
        """Parse time string and update segment list"""
        segment = self.vp.segments.get_segment_by_id(id)
        if segment is None:
            print("Segment not found")
            return

        try:
            # Convert to seconds
            total_seconds = utils.time_str_to_sec(time_str)

            # Validate value
            if total_seconds < 0 or total_seconds > self.vp.duration:
                raise ValueError("Time out of range")

            # Update segment list
            if time_type == "start":
                if total_seconds >= segment.end_time:
                    messagebox.showwarning(
                        t("Warning"), t("Start time must be before end time")
                    )
                    try:
                        self.refresh_segment_in_list(segment)
                    except:
                        self.refresh_all_segments_in_list()
                    return
                segment.start_time = total_seconds
            else:  # end
                if total_seconds <= segment.start_time:
                    messagebox.showwarning(
                        t("Warning"), t("End time must be after start time")
                    )
                    try:
                        self.refresh_segment_in_list(segment)
                    except:
                        self.refresh_all_segments_in_list()
                    return
                segment.end_time = total_seconds

            # Update display
            try:
                self.refresh_segment_in_list(segment)
            except:
                self.refresh_all_segments_in_list()
            self.draw_segment_ranges(segment.layer)

        except (ValueError, IndexError):
            messagebox.showwarning(
                t("Warning"),
                t("Time format is incorrect. Format: mm:ss.mmm or mm:ss"),
            )
            try:
                self.refresh_segment_in_list(segment)
            except:
                self.refresh_all_segments_in_list()

    def delete_segment(self, id):
        segment = self.vp.segments.get_segment_by_id(id)
        if segment is None:
            print("Segment ID not found")
            return
        self.vp.segments.remove_segment_by_id(id)
        self.refresh_all_segments_in_list()
        layer = segment.layer

        if self.selected_segment_id == id:
            self.unselect_segment_id()

        self.draw_segment_ranges(layer, layer == self.selected_layer)

        if len(self.vp.segments) == 0:
            self.execute_split_multiple_button.configure(state="disabled")

    def clear_list(self):
        if self.show_full_list.get():
            layers = self.layers
        else:
            layers = [self.selected_layer]

        filtered_segment_list = self.vp.segments.filter_by_layers(layers)

        if len(filtered_segment_list) > 0:
            if messagebox.askyesno(
                t("Confirm"),
                (
                    t("Clear all segments?")
                    if self.show_full_list.get()
                    else t("Clear all segments in the current layer?")
                ),
            ):
                self.vp.segments.clear(layers)
                self.start_frame = None

                # Reset start point button
                self.start_button.configure(
                    text=t("Set Start Point"),
                    fg_color=["#3B8ED0", "#1F6AA5"],
                    hover_color=["#36719F", "#144870"],
                )

                self.refresh_all_segments_in_list()
                for layer in layers:
                    self.draw_segment_ranges(layer)
                self.execute_split_multiple_button.configure(state="disabled")
                self.execute_split_single_button.configure(state="disabled")

    def reset_segment_indices(self):
        if self.vp is None:
            return

        if len(self.vp.segments) > 0:
            if messagebox.askyesno(
                t("Confirm"),
                t("Reset segment IDs?"),
            ):
                self.change_mode("Add", False)
                self.vp.segments.reset_indices()
                self.refresh_all_segments_in_list()
                self.status_text.info(t("Segment IDs reset"))

    def select_output_folder(self):
        folder = filedialog.askdirectory(title=t("Select output folder"))
        if folder:
            self.vp.output_path = folder

    def execute_split_multiple(self, layers=None):
        if not self.vp.output_path:
            messagebox.showwarning(
                t("Warning"), t("Output folder not selected")
            )
            return

        if layers is None:
            if self.show_full_list.get():
                layers = self.layers
            else:
                layers = [self.selected_layer]

        count_items = len(self.vp.segments.filter_by_layers(layers))

        if count_items == 0:
            messagebox.showwarning(t("Warning"), t("No segment settings"))
            return

        self.execute_split_multiple_button.configure(state="disabled")
        threading.Thread(
            target=self.split_multiple_video_thread,
            args=(layers,),
            daemon=True,
        ).start()

    def split_multiple_video_thread(self, layers):
        if layers is None:
            layers = self.layers

        try:

            def progress_callback(i, total):
                self.progress_label.configure(
                    text=f"{t("Progress")}: {i+1}/{total}"
                )
                self.progress.set(i / total if total else 0)

            filtered_segment_list = self.vp.segments.filter_by_layers(layers)

            video_utils.split_video(
                self.vp.video_path,
                filtered_segment_list,
                self.vp.output_path,
                progress_callback=progress_callback,
                codec=config.get("DEFAULT", "codec"),
                backend=config.get("DEFAULT", "backend"),
            )
            self.progress.set(1.0)
            self.progress_label.configure(text=t("Complete"))
            messagebox.showinfo(t("Done"), t("Video splitting completed"))
        except Exception as e:
            messagebox.showerror(
                t("Error"), f"{t("Error occurred")}: {str(e)}"
            )
        finally:
            self.execute_split_multiple_button.configure(state="normal")

    def execute_split_single(self):
        if not self.vp.output_path:
            messagebox.showwarning(
                t("Warning"), t("Output folder not selected")
            )
            return

        if self.vp is None or self.vp.total_frames == 0:
            messagebox.showwarning(t("Warning"), t("No video loaded"))
            return

        segment = None
        if self.selected_segment_id is not None:
            segment = self.vp.segments.get_segment_by_id(
                self.selected_segment_id
            )

        if segment is None:
            segment = self.vp.segments.get_segment_by_time(
                self.current_frame / self.vp.fps,
            )

        if segment is None:
            messagebox.showwarning(t("Warning"), t("No segment selected"))
            return

        self.execute_split_single_button.configure(state="disabled")
        threading.Thread(
            target=self.split_single_video_thread, args=(segment,), daemon=True
        ).start()

    def split_single_video_thread(self, segment):
        try:

            def progress_callback(i, total):
                self.progress_label.configure(
                    text=f"{t("Progress")}: {i+1}/{total}"
                )
                self.progress.set(i / total if total else 0)

            video_utils.split_video(
                self.vp.video_path,
                [segment],
                self.vp.output_path,
                progress_callback=progress_callback,
                codec=config.get("DEFAULT", "codec"),
                backend=config.get("DEFAULT", "backend"),
            )
            self.progress.set(1.0)
            self.progress_label.configure(text=t("Complete"))
            messagebox.showinfo(t("Done"), t("Video splitting completed"))
        except Exception as e:
            messagebox.showerror(
                t("Error"), f"{t("Error occurred")}: {str(e)}"
            )
        finally:
            self.execute_split_single_button.configure(state="normal")

    def start_resize(self, event):
        """Start resizing"""
        self.resize_start_x = event.x_root
        self.left_width = self.left_frame.winfo_width()
        self.right_width = self.right_frame.winfo_width()

    def do_resize(self, event):
        """Do resizing"""
        delta = event.x_root - self.resize_start_x

        # Calculate new widths (ensure minimum widths)
        new_left_width = self.left_width + delta
        window_width = self.winfo_width()
        new_right_width = (
            window_width - new_left_width - self.separator.winfo_width()
        )

        # Update only if both minimum widths are maintained and total width fits
        if (
            new_left_width >= self.min_left_width
            and new_right_width >= self.min_right_width
        ):
            # Reset weight to the left side temporary
            self.main_frame.grid_columnconfigure(0, weight=0)

            # Set new sizes
            self.main_frame.grid_columnconfigure(0, minsize=new_left_width)
            self.main_frame.grid_columnconfigure(2, minsize=new_right_width)
            # Restore weight to the left side after resizing
            self.after(
                10, lambda: self.main_frame.grid_columnconfigure(0, weight=1)
            )

            self.update_idletasks()

            # Redraw canvas
            if self.vp is not None and self.vp.total_frames > 0:
                self.draw_all_segment_ranges()

    def on_closing(self):
        if self.vp is not None and self.vp.cap is not None:
            self.vp.cap.release()
        self.destroy()

    def save_project(self, event=None):
        """Save project file"""
        if not self.vp:
            messagebox.showwarning(t("Warning"), t("No video loaded"))
            return

        if not self.vp.file_path or not os.path.exists(self.vp.file_path):
            self.save_as_project()
            return

        try:
            self.vp.save(self.vp.file_path)

            messagebox.showinfo(t("Done"), t("Project file saved"))
        except Exception as e:
            messagebox.showerror(
                t("Error"), f"{t("Project save failed")}: {str(e)}"
            )

    def save_as_project(self, event=None):
        """Save project file as"""
        if not self.vp:
            messagebox.showwarning(t("Warning"), t("No video loaded"))
            return

        file_path = filedialog.asksaveasfilename(
            title=t("Save Project"),
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), (t("Select"), "*.*")],
        )

        if file_path:
            try:
                self.vp.save(file_path)

                messagebox.showinfo(t("Done"), t("Project file saved"))
            except Exception as e:
                messagebox.showerror(
                    t("Error"), f"{t("Project save failed")}: {str(e)}"
                )

    def open_project(self, event=None):
        """Open project file"""
        file_path = VideoProject.open_project_dialog()

        if not file_path:
            return

        try:
            self.vp = VideoProject.load(file_path)

            # Load video
            self.reset_video_controls()

            # Restore segment list
            self.refresh_all_segments_in_list()
            self.draw_all_segment_ranges()

            # Reset start point
            self.reset_start_point()

            if len(self.vp.segments) > 0:
                self.execute_split_multiple_button.configure(state="normal")
                self.execute_split_single_button.configure(state="normal")

            messagebox.showinfo(t("Done"), t("Project file loaded"))

        except Exception as e:
            messagebox.showerror(
                t("Error"), f"{t("Project load failed")}: {str(e)}"
            )


if __name__ == "__main__":
    app = VideoSplitterApp()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()
