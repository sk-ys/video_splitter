import tkinter as tk
import customtkinter as ctk
from tkinter import filedialog, messagebox
import cv2
from video_utils import load_video, split_video
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
        return self.end_frame - self.start_frame

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
    def __init__(self, items=None):
        self.items = items if items is not None else []
        self._ui = {}

    def __iter__(self):
        return iter(self.items)

    def __len__(self):
        return len(self.items)

    @classmethod
    def from_dicts(cls, fps, dicts):
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
        return cls(segments)

    def set_items(self, segments):
        self.items = segments

    def add_segment(self, segment: Segment):
        self.items.append(segment)

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


class VideoSplitterApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(t("Video Splitter"))
        self.geometry("1400x900")

        # Video-related variables
        self.video_path = None
        self.cap = None
        self.total_frames = 0
        self.fps = 0
        self.current_frame = 0
        self.is_playing = False
        self.duration = 0

        # Split layers
        self.layers = [1, 2, 3]
        self.selected_layer = self.layers[0]

        # Split segment list
        self.segments = SegmentManager()
        self.start_frame = None

        self.selected_segment_id = None

        self.setup_ui()

        self.change_layer(self.selected_layer)

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
        self.zoom_range_control_frame = ctk.CTkFrame(self.seekbar_frame)
        self.zoom_range_control_frame.grid(
            row=0, column=0, columnspan=3, padx=5, pady=5, sticky="w"
        )
        ctk.CTkLabel(
            self.zoom_range_control_frame, text=f"{t("Range")}:"
        ).grid(row=0, column=0, padx=5)
        self.zoom_range_slider = ctk.CTkSlider(
            self.zoom_range_control_frame,
            from_=1,
            to=100,
            number_of_steps=99,
            command=self.update_zoom_range_slider,
            state="disabled",
            width=150,
        )
        self.zoom_range_slider.set(100)
        self.zoom_range_slider.grid(row=0, column=1, padx=5)

        self.zoom_range_label = ctk.CTkLabel(
            self.zoom_range_control_frame, text="100%"
        )
        self.zoom_range_label.grid(row=0, column=2, padx=5)

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
        self.zoom_range = 100  # percent
        self.zoom_center = 0  # center frame for zoom

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
        self.load_project_button = ctk.CTkButton(
            parent,
            text="📂 " + t("Load Project"),
            command=self.load_project,
            height=40,
            width=150,
            fg_color="gray40",
            hover_color="gray50",
        )
        self.load_project_button.grid(row=0, column=2, padx=5, pady=5)

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
            command=self.toggle_play,
            width=100,
            state="disabled",
        )
        self.play_button.grid(row=0, column=0, padx=5, pady=5)

        # Frame navigation buttons
        self.prev_frame_button = ctk.CTkButton(
            parent,
            text=f"◀ 1F",
            command=self.prev_frame,
            width=60,
            state="disabled",
        )
        self.prev_frame_button.grid(row=0, column=1, padx=5, pady=5)

        self.next_frame_button = ctk.CTkButton(
            parent,
            text=f"1F ▶",
            command=self.next_frame,
            width=60,
            state="disabled",
        )
        self.next_frame_button.grid(row=0, column=2, padx=5, pady=5)

        self.jump_to_time_button = ctk.CTkButton(
            parent,
            text="➡️",
            command=self.jump_to_time_dialog,
            width=30,
            state="disabled",
        )
        self.jump_to_time_button.grid(row=0, column=3, padx=5, pady=5)

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

    def setup_split_control_ui(self, parent):
        self.mode_selector_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.mode_selector_frame.grid(
            row=0, column=0, padx=5, pady=0, sticky="w"
        )

        self.mode_selector = ctk.CTkOptionMenu(
            self.mode_selector_frame,
            values=[t("Add"), t("Edit")],
            command=self.change_mode,
            width=80,
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

    def change_mode(self, mode=None, select_segment=True):
        """Change between Add/Edit mode
        Args:
            mode (str, optional): "Add" or "Edit". If None, use current selector value. Defaults to None.

        Returns: None
        """
        if mode is None or mode not in ["Add", "Edit"]:
            mode = self.get_current_mode()
        mode_display_value = t("Edit") if mode == "Edit" else t("Add")

        if mode == "Edit":
            if self.selected_segment_id is not None:
                segment = self.segments.get_segment_by_id(
                    self.selected_segment_id
                )
            else:
                segment = self.segments.get_segment_by_time(
                    self.current_frame / self.fps,
                    self.selected_layer,
                )

            if segment is None:
                messagebox.showwarning(
                    t("Warning"), t("No segments available to edit.")
                )
                mode = "Add"
                mode_display_value = t("Add")

        if mode == "Edit":
            self.set_status_info(t("Edit mode enabled"))

            if select_segment:
                self.select_segment_id(segment.segment_id)
        else:
            # Default to Add mode
            self.set_status_info(t("Add mode enabled"))
            if select_segment:
                self.unselect_segment_id()

        # Update selector if needed
        if self.mode_selector.get() != mode_display_value:
            self.mode_selector.set(mode_display_value)

    def get_current_mode(self):
        return "Edit" if self.mode_selector.get() == t("Edit") else "Add"

    def toggle_link_boundaries(self):
        if self.link_boundaries_enabled.get():
            self.set_status_info(
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
            self.set_status_info(
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
            command=self.update_segment_list_display,
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
        self.output_path = None

        # Execute button
        self.execute_button = ctk.CTkButton(
            self.right_frame,
            text=t("Split Execute"),
            command=self.execute_segment,
            height=50,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color="green",
            hover_color="darkgreen",
            state="disabled",
        )
        self.execute_button.grid(
            row=3, column=0, padx=10, pady=20, sticky="ew"
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
        ctk.CTkLabel(self.header_frame, text=t("No."), width=30).grid(
            row=0, column=0, padx=2
        )
        ctk.CTkLabel(self.header_frame, text=t("L"), width=30).grid(
            row=0, column=1, padx=2
        )
        ctk.CTkLabel(self.header_frame, text=t("Title")).grid(
            row=0, column=2, padx=2
        )
        ctk.CTkLabel(self.header_frame, text=t("Start"), width=80).grid(
            row=0, column=3, padx=2
        )
        ctk.CTkLabel(self.header_frame, text=t("End"), width=80).grid(
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

    def set_status_text(
        self,
        text,
        duration=5000,
        text_color="gray40",
        bg_color="transparent",
    ):
        self.status_bar.configure(
            text=text, text_color=text_color, bg_color=bg_color
        )
        if duration > 0:
            self.after(duration, self.clear_status_text)

    def clear_status_text(self):
        self.set_status_text("", duration=0)

    def set_status_error(self, text, duration=5000):
        self.set_status_text(
            text="🛑 " + text, duration=duration, text_color="orange red"
        )

    def set_status_warning(self, text, duration=5000):
        self.set_status_text(
            text="⚠️ " + text,
            duration=duration,
            text_color="sandy brown",
        )

    def set_status_info(self, text, duration=5000):
        self.set_status_text(
            text="ℹ️ " + text, duration=duration, text_color="cornflower blue"
        )

    def seekbar_resize_event(self, event):
        self.after(10, self.draw_all_segment_ranges)

    class SettingsDialog(ctk.CTkToplevel):
        def __init__(self, parent):
            super().__init__(parent)

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

            # Language selection
            ctk.CTkLabel(self.content_frame, text=t("Language") + ":").grid(
                row=0, column=0, padx=5, pady=5, sticky="w"
            )

            self.lang_var = ctk.StringVar(value=lang)
            self.lang_option = ctk.CTkOptionMenu(
                self.content_frame,
                values=["en", "ja"],
                variable=self.lang_var,
                command=self.change_language,
            )
            self.lang_option.grid(row=0, column=1, padx=5, pady=5, sticky="w")

            # Buttons
            self.button_frame = ctk.CTkFrame(self)
            self.button_frame.grid(
                row=1, column=0, padx=10, pady=10, sticky="e"
            )
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
            with open("config.ini", "w") as config_file:
                config.write(config_file)
            self.destroy()

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

    def open_settings(self):
        # Open settings dialog
        settings_window = self.SettingsDialog(self)
        settings_window.grab_set()

    def _load_video_dialog(self):
        return filedialog.askopenfilename(
            title=t("Select video file"),
            filetypes=[
                (t("Select video file"), "*.mp4 *.avi *.mov *.mkv"),
                (t("Select"), "*.*"),
            ],
        )

    def load_video_dialog(self):
        file_path = self._load_video_dialog()
        if file_path:
            self.load_video(file_path)
            self.reset_video_controls()

    def load_video(self, file_path):
        self.video_path = file_path
        self.cap, self.total_frames, self.fps = load_video(file_path)
        self.duration = self.total_frames / self.fps

    def reset_video_controls(self):
        self.seek_slider.configure(to=self.total_frames - 1, state="normal")
        self.zoom_range_slider.configure(state="normal")
        self.play_button.configure(state="normal")
        self.prev_frame_button.configure(state="normal")
        self.next_frame_button.configure(state="normal")
        self.jump_to_time_button.configure(state="normal")
        self.start_button.configure(state="normal")
        self.end_button.configure(state="normal")
        self.mode_selector.configure(state="normal")

        self.current_frame = 0
        self.zoom_center = 0
        self.update_zoom_range()
        self.update_frame()
        self.update_time_label()
        self.update_seekbar_range_display()
        self.draw_segment_ranges()

        self.update_length_label(False)

    def update_frame(self):
        if self.cap is not None:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame)
            ret, frame = self.cap.read()

            if ret:
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

    def toggle_play(self):
        self.is_playing = not self.is_playing

        if self.is_playing:
            self.play_button.configure(text="⏸ " + t("Pause"))
            threading.Thread(target=self.play_video, daemon=True).start()
        else:
            self.play_button.configure(text="▶ " + t("Play"))

    def prev_frame(self):
        """Go back 1 frame"""
        if self.is_playing:
            self.is_playing = False
            self.play_button.configure(text="▶ " + t("Play"))

        if self.current_frame > 0:
            self.current_frame -= 1
            self.update_zoom_range()
            self.update_frame()
            self.update_time_label()
            self.update_seekbar_range_display()

    def next_frame(self):
        """Advance 1 frame"""
        if self.is_playing:
            self.is_playing = False
            self.play_button.configure(text="▶ " + t("Play"))

        if self.current_frame < self.total_frames - 1:
            self.current_frame += 1
            self.update_zoom_range()
            self.update_frame()
            self.update_time_label()
            self.update_seekbar_range_display()

    def play_video(self):
        while self.is_playing and self.current_frame < self.total_frames - 1:
            self.current_frame += 1
            self.update_frame()
            self.seek_slider.set(self.current_frame)
            self.update_time_label()
            self.after(round(1000 / self.fps))

        if self.current_frame >= self.total_frames - 1:
            self.is_playing = False
            self.play_button.configure(text="▶ " + t("Play"))

    def jump_to_frame(self, frame_num):
        self.current_frame = max(0, min(frame_num, self.total_frames - 1))
        self.update_zoom_range()
        self.update_frame()
        self.update_time_label()
        self.update_seekbar_range_display()

    def jump_to_time(self, time_sec):
        frame_num = round(time_sec * self.fps)
        self.jump_to_frame(frame_num)

    def jump_to_time_dialog(self):
        dialog = CustomCTkInputDialog(
            title=t("Jump to Time"),
            text=t("Enter time (in seconds or mm:ss.sss format):"),
            initialvalue=f"{utils.format_time(self.current_frame / self.fps)}",
        )

        time_str = dialog.get_input()

        if time_str:
            try:
                self.jump_to_time(utils.parse_time(time_str))
            except ValueError:
                messagebox.showerror(
                    t("Error"), t("Invalid time format entered.")
                )

    def seek_video(self, value):
        # Calculate zoom range
        visible_frames = self.total_frames * (self.zoom_range / 100)
        start_frame = max(0, self.zoom_center - visible_frames / 2)
        end_frame = min(self.total_frames - 1, start_frame + visible_frames)

        # Recalculate actual display range (after boundary adjustment)
        if end_frame - start_frame < visible_frames:
            if start_frame == 0:
                end_frame = min(self.total_frames - 1, visible_frames)
            else:
                start_frame = max(0, end_frame - visible_frames)

        # Convert slider value (range 0-100) to actual frame position
        slider_range = self.seek_slider.cget("to") - self.seek_slider.cget(
            "from_"
        )
        relative_pos = (
            float(value) - self.seek_slider.cget("from_")
        ) / slider_range

        self.current_frame = round(
            start_frame + relative_pos * (end_frame - start_frame)
        )
        self.current_frame = max(
            0, min(self.current_frame, self.total_frames - 1)
        )

        self.update_frame()
        self.update_time_label()

    def update_zoom_range_slider(self, value):
        self.zoom_range = float(value)
        self.zoom_range_label.configure(text=f"{round(self.zoom_range)}%")
        self.zoom_center = self.current_frame
        self.update_zoom_range()
        self.update_seekbar_range_display()
        self.draw_all_segment_ranges()

    def update_seekbar_range_display(self):
        """Update seekbar display range"""
        if self.total_frames == 0:
            return

        visible_frames = self.total_frames * (self.zoom_range / 100)
        start_frame = max(0, self.zoom_center - visible_frames / 2)
        end_frame = min(self.total_frames - 1, start_frame + visible_frames)

        # Boundary adjustment
        if end_frame - start_frame < visible_frames:
            if start_frame == 0:
                end_frame = min(self.total_frames - 1, visible_frames)
            else:
                start_frame = max(0, end_frame - visible_frames)

        start_time = start_frame / self.fps
        end_time = end_frame / self.fps

        self.seekbar_start_label.configure(text=utils.format_time(start_time))
        self.seekbar_end_label.configure(text=utils.format_time(end_time))

    def update_zoom_range(self):
        # Adjust seek slider position based on zoom
        visible_frames = self.total_frames * (self.zoom_range / 100)
        start_frame = max(0, self.zoom_center - visible_frames / 2)
        end_frame = min(self.total_frames - 1, start_frame + visible_frames)

        # Boundary adjustment
        if end_frame - start_frame < visible_frames:
            if start_frame == 0:
                end_frame = min(self.total_frames - 1, visible_frames)
            else:
                start_frame = max(0, end_frame - visible_frames)

        # Convert current frame to slider position
        if end_frame > start_frame:
            relative_pos = (self.current_frame - start_frame) / (
                end_frame - start_frame
            )
            slider_range = self.seek_slider.cget("to") - self.seek_slider.cget(
                "from_"
            )
            slider_value = (
                self.seek_slider.cget("from_") + relative_pos * slider_range
            )
            self.seek_slider.set(slider_value)

    def seek_layer_button_click(self, layer):
        self.change_layer(str(layer))
        self.unselect_segment_id()

    def change_layer(self, layer_str, update_segment_list=True):
        self.selected_layer = int(layer_str)
        self.layer_label.configure(text=f"{t('layer')}: {self.selected_layer}")
        if update_segment_list:
            self.update_segment_list_display()
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
            segment = self.segments.get_segment_by_id(id)
            if segment is None:
                self.set_status_warning(t("No segments to display"))
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
        for segment in self.segments:
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
        for segment in self.segments:
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

        if self.total_frames == 0:
            return

        canvas_width = seek_canvas.winfo_width()
        if canvas_width <= 1:
            canvas_width = 800

        canvas_height = seek_canvas.winfo_height()

        # Calculate zoom range
        visible_frames = self.total_frames * (self.zoom_range / 100)
        visible_start_frame = max(0, self.zoom_center - visible_frames / 2)
        visible_end_frame = min(
            self.total_frames - 1, visible_start_frame + visible_frames
        )

        # Boundary adjustment
        if visible_end_frame - visible_start_frame < visible_frames:
            if visible_start_frame == 0:
                visible_end_frame = min(self.total_frames - 1, visible_frames)
            else:
                visible_start_frame = max(
                    0, visible_end_frame - visible_frames
                )

        visible_range = visible_end_frame - visible_start_frame
        if visible_range <= 0:
            visible_range = 1

        # Draw segment ranges
        filtered_segment_list = self.segments.filter_by_layers([layer])

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
        current_time = self.current_frame / self.fps
        total_time = self.duration

        # Display up to milliseconds
        current_str = utils.format_time(current_time)
        total_str = utils.format_time(total_time)

        self.time_label.configure(text=f"{current_str} / {total_str}")

        # Display frame count
        self.frame_label.configure(
            text=f"{t("Frame")}: {self.current_frame} / {self.total_frames - 1}"
        )

        # Update canvas
        for layer in self.layers:
            self.draw_segment_ranges(layer, layer == self.selected_layer)

        # Update end button label if start point is set
        self.update_length_label()

    def update_length_label(self, enabled=True):
        if self.start_frame is not None and enabled:
            elapsed_frame = self.current_frame - self.start_frame
            length_sec = elapsed_frame / self.fps
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

    def get_next_free_time(self, start_time, layer):
        """Get the next free time after start_time in the selected layer"""
        segment = self.segments.get_segment_by_time(
            start_time, layer, True, False
        )

        if segment is None:
            if start_time >= self.total_frames / self.fps:
                return None
            return start_time
        else:
            return self.get_next_free_time(segment.end_time, layer)

    def get_previous_free_time(self, end_time, layer):
        """Get the previous free time before end_time in the selected layer"""
        segment = self.segments.get_segment_by_time(
            end_time, layer, False, True
        )

        if segment is None:
            if end_time <= 0:
                return None
            return end_time
        else:
            return self.get_previous_free_time(segment.start_time, layer)

    def set_start_point(self):
        if self.get_current_mode() == "Add":
            self.set_new_start_point()
        else:
            self.edit_start_point()

    def set_new_start_point(self):
        """Set the start point at the next free time from current position"""
        free_time = self.get_next_free_time(
            self.current_frame / self.fps, self.selected_layer
        )

        if free_time is None:
            messagebox.showwarning(
                t("Warning"), t("No free space available to set start point")
            )
            return

        self.start_frame = round(free_time * self.fps)

        # Set current position to new start point
        if self.start_frame != self.current_frame:
            self.jump_to_frame(self.start_frame)
            self.set_status_info(
                t("Start point set at next available position automatically")
            )

        # Update button display
        start_time_str = utils.format_time(self.start_frame / self.fps)
        self.start_button.configure(
            text=f"{t("Start")}: {start_time_str} (F:{self.start_frame})",
            fg_color="green",
            hover_color="darkgreen",
        )

        self.draw_segment_ranges()

    def edit_start_point(self, id=None):
        """Edit the start point to a specific time"""
        if id is None:
            id = self.selected_segment_id

        segment = self.segments.get_segment_by_id(id)
        if segment is None:
            messagebox.showwarning(
                t("Warning"), t("Selected segment not found")
            )
            return
        old_start_time = segment.start_time

        selected_segment = self.segments.get_segment_by_time(
            self.current_frame / self.fps,
            layer=segment.layer,
            include_start=True,
            include_end=False,
        )

        last_segment = None
        if selected_segment is not None:
            previous_segments = self.get_segments_before_time(
                segment.start_time, layer=segment.layer
            )

            if previous_segments:
                # Note: previous_segments will always contain at least the
                # current segment
                last_segment = previous_segments[-1]

                if selected_segment.segment_id != id:
                    if (
                        self.current_frame / self.fps
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

        new_start_time = self.current_frame / self.fps

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
            self.set_status_info(
                t(
                    "Start point updated and previous segment's end point "
                    + "adjusted."
                )
            )

    def set_end_point(self):
        if self.get_current_mode() == "Add":
            self.set_new_end_point()
        else:
            self.edit_end_point()

    def set_new_end_point(self):
        """Set the end point at the previous free time from current position"""
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

        free_time = self.get_previous_free_time(
            self.current_frame / self.fps, self.selected_layer
        )

        if free_time is None:
            messagebox.showwarning(
                t("Warning"), t("No free space available to set end point")
            )
            return

        start_time = self.start_frame / self.fps
        end_time = free_time
        end_frame = round(end_time * self.fps)

        if end_time <= start_time:
            # Note: This should not happen due to previous checks, but just in
            # case
            messagebox.showwarning(
                t("Warning"), t("End point must be after start point")
            )
            return

        filtered_segment_list = self.segments.filter_by_layers(
            [self.selected_layer]
        )
        self.segments.add_segment(
            Segment(
                **{
                    "fps": self.fps,
                    "segment_id": self.get_max_list_index() + 1,
                    "start_frame": self.start_frame,
                    "end_frame": end_frame,
                    "title": f"part{len(filtered_segment_list)+1:03d}",
                    "layer": self.selected_layer,
                }
            )
        )

        # Set current position to new end point
        if end_frame != self.current_frame:
            self.jump_to_frame(end_frame)
            self.set_status_info(
                t(
                    "End point set at previous available position automatically"
                    + " and segment added."
                )
            )
        else:
            self.set_status_info(t("Segment added"))

        self.update_segment_list_display()

        # Reset start point button
        self.reset_start_point()

        if len(self.segments) > 0:
            self.execute_button.configure(state="normal")

    def edit_end_point(self, id=None):
        """Edit the end point to a specific time"""
        if id is None:
            id = self.selected_segment_id

        segment = self.segments.get_segment_by_id(id)
        if segment is None:
            messagebox.showwarning(
                t("Warning"), t("Selected segment not found")
            )
            return
        old_end_time = segment.end_time

        selected_segment = self.segments.get_segment_by_time(
            self.current_frame / self.fps,
            layer=segment.layer,
            include_start=False,
            include_end=True,
        )

        next_segment = None
        if selected_segment is not None:
            next_segments = self.get_segments_after_time(
                segment.end_time, layer=segment.layer
            )

            if next_segments:
                # Note: next_segments will always contain at least the
                # current segment
                next_segment = next_segments[0]

                if selected_segment.segment_id != id:
                    if self.current_frame / self.fps > next_segment.end_time:
                        messagebox.showwarning(
                            t("Warning"),
                            t(
                                "End point must be before "
                                + "the next segment ends."
                            ),
                        )
                        return

        new_end_time = self.current_frame / self.fps

        self.update_segment_time(id, "end", str(new_end_time))

        if next_segment is not None and (
            next_segment.start_time <= new_end_time
            or (
                next_segment.start_time == old_end_time
                and self.link_boundaries_enabled.get()
            )
        ):
            self.update_segment_time(
                next_segment.segment_id, "start", str(new_end_time)
            )
            self.set_status_info(
                t(
                    "End point updated and next segment's start point "
                    + "adjusted."
                )
            )

    def reset_list_indexes(self):
        """Reassign IDs to segments based on their order in the full list"""
        for i, segment in enumerate(self.segments):
            segment.segment_id = i + 1

    def get_max_list_index(self):
        """Get the maximum ID in the full segment list"""
        if not self.segments:
            return 0
        return max(segment.segment_id for segment in self.segments)

    def get_segments_before_time(self, time_sec, layer=None):
        """Get the segments before the specified time (in seconds)"""
        if layer is None:
            layer = self.selected_layer

        filtered_segment_list = [
            segment
            for segment in self.segments
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
            for segment in self.segments
            if segment.layer == layer and segment.start_time >= time_sec
        ]

        # Return sorted list
        return sorted(filtered_segment_list, key=lambda x: x.start_time)

    def reset_start_point(self):
        self.start_frame = None
        self.start_button.configure(
            text=t("Set Start Point"),
            fg_color=["#3B8ED0", "#1F6AA5"],  # Reset to default colors
            hover_color=["#36719F", "#144870"],
        )
        self.draw_segment_ranges()

        self.update_length_label(False)

    def update_segment_list_display(self):
        # Clear existing list
        for widget in self.list_container.winfo_children():
            widget.destroy()

        # Redisplay the list
        if self.show_full_list.get():
            layers = self.layers
            self.layer_label.configure(text_color="gray")
        else:
            layers = [self.selected_layer]
            self.layer_label.configure(text_color="white")

        segment_list = sorted(
            [segment for segment in self.segments if segment.layer in layers],
            key=lambda x: x.segment_id,
        )
        for i, segment in enumerate(segment_list):
            row_frame = ctk.CTkFrame(self.list_container)
            row_frame.grid(row=i, column=0, sticky="ew", pady=2)
            id = segment.segment_id
            layer = segment.layer
            is_selected = str(id) == self.mode_selector.get()

            # Number button (jump to start position on click)
            num_btn = ctk.CTkButton(
                row_frame,
                text=str(id),
                width=30,
                command=lambda _id=id: self.select_segment_id_with_jump(_id),
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
                lambda e, _id=id, entry=title_entry: self.update_segment_title(
                    _id, entry.get()
                ),
            )
            title_entry.bind(
                "<Return>",
                lambda e, _id=id, entry=title_entry: self.update_segment_title(
                    _id, entry.get()
                ),
            )

            # Start time (editable)
            start_entry = ctk.CTkEntry(row_frame, width=80)
            start_entry.insert(0, utils.format_time(segment.start_time))
            start_entry.grid(row=0, column=3, padx=2)
            start_entry.bind(
                "<FocusOut>",
                lambda e, _id=id, entry=start_entry: self.update_segment_time(
                    _id, "start", entry.get()
                ),
            )
            start_entry.bind(
                "<Return>",
                lambda e, _id=id, entry=start_entry: self.update_segment_time(
                    _id, "start", entry.get()
                ),
            )

            # End time (editable)
            end_entry = ctk.CTkEntry(row_frame, width=80)
            end_entry.insert(0, utils.format_time(segment.end_time))
            end_entry.grid(row=0, column=4, padx=2)
            end_entry.bind(
                "<FocusOut>",
                lambda e, _id=id, entry=end_entry: self.update_segment_time(
                    _id, "end", entry.get()
                ),
            )
            end_entry.bind(
                "<Return>",
                lambda e, _id=id, entry=end_entry: self.update_segment_time(
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
                command=lambda _id=id: self.delete_segment(_id),
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

    def update_segment_title(self, id, title):
        """Update title"""
        index = self.segments.get_index_by_id(id)
        if index is not None:
            # Remove characters not allowed in filenames
            safe_title = "".join(c for c in title if c.isalnum()).strip()
            if not safe_title:
                safe_title = f"part{index+1:03d}"
            self.segments[index]["title"] = safe_title
            self.update_segment_list_display()

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
        segment = self.segments.get_segment_by_id(id)
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
            self.set_status_info(
                t("Jumped to the start of the selected segment")
            )
        elif position in ("end", "e"):
            # Jump to end
            # If already at start, jump to end
            target_frame = segment.end_frame
            self.set_status_info(
                t("Jumped to the end of the selected segment")
            )
        else:
            # Jump to middle
            mid_time = (segment.start_time + segment.end_time) / 2
            target_frame = round(mid_time * self.fps)
            self.set_status_info(
                t("Jumped to the middle of the selected segment")
            )

        self.current_frame = target_frame
        self.current_frame = max(
            0, min(self.current_frame, self.total_frames - 1)
        )

        # Stop if playing
        if self.is_playing:
            self.is_playing = False
            self.play_button.configure(text="▶ " + t("Play"))

        # Update display
        self.update_zoom_range()
        self.update_frame()
        self.update_time_label()
        self.update_seekbar_range_display()

    def update_segment_time(self, id, time_type, time_str):
        """Parse time string and update segment list"""
        segment = self.segments.get_segment_by_id(id)
        if segment is None:
            print("Segment not found")
            return

        try:
            # Convert to seconds
            total_seconds = utils.parse_time(time_str)

            # Validate value
            if total_seconds < 0 or total_seconds > self.duration:
                raise ValueError("Time out of range")

            # Update segment list
            if time_type == "start":
                if total_seconds >= segment.end_time:
                    messagebox.showwarning(
                        t("Warning"), t("Start time must be before end time")
                    )
                    self.update_segment_list_display()
                    return
                segment.start_time = total_seconds
            else:  # end
                if total_seconds <= segment.start_time:
                    messagebox.showwarning(
                        t("Warning"), t("End time must be after start time")
                    )
                    self.update_segment_list_display()
                    return
                segment.end_time = total_seconds

            # Update display
            self.update_segment_list_display()
            self.draw_segment_ranges(segment.layer)

        except (ValueError, IndexError):
            messagebox.showwarning(
                t("Warning"),
                t("Time format is incorrect. Format: mm:ss.mmm or mm:ss"),
            )
            self.update_segment_list_display()

    def delete_segment(self, id):
        segment = self.segments.get_segment_by_id(id)
        if segment is None:
            print("Segment ID not found")
            return
        self.segments.remove_segment_by_id(id)
        self.update_segment_list_display()
        layer = segment.layer
        self.draw_segment_ranges(layer, layer == self.selected_layer)

        if len(self.segments) == 0:
            self.execute_button.configure(state="disabled")

    def clear_list(self):
        if self.show_full_list.get():
            layers = self.layers
        else:
            layers = [self.selected_layer]

        filtered_segment_list = self.segments.filter_by_layers(layers)

        if len(filtered_segment_list) > 0:
            if messagebox.askyesno(
                t("Confirm"),
                (
                    t("Clear all segments?")
                    if self.show_full_list.get()
                    else t("Clear all segments in the current layer?")
                ),
            ):
                self.segments.clear(layers)
                self.start_frame = None

                # Reset start point button
                self.start_button.configure(
                    text=t("Set Start Point"),
                    fg_color=["#3B8ED0", "#1F6AA5"],
                    hover_color=["#36719F", "#144870"],
                )

                self.update_segment_list_display()
                for layer in layers:
                    self.draw_segment_ranges(layer)
                self.execute_button.configure(state="disabled")

    def select_output_folder(self):
        folder = filedialog.askdirectory(title=t("Select output folder"))
        if folder:
            self.output_path = folder

    def execute_segment(self, layers=None):
        if not self.output_path:
            messagebox.showwarning(
                t("Warning"), t("Output folder not selected")
            )
            return

        if layers is None:
            if self.show_full_list.get():
                layers = self.layers
            else:
                layers = [self.selected_layer]

        count_items = len(
            [row for row in self.segments if row["layer"] in layers]
        )

        if count_items == 0:
            messagebox.showwarning(t("Warning"), t("No segment settings"))
            return

        self.execute_button.configure(state="disabled")
        threading.Thread(
            target=self.segment_video_thread, args=(layers,), daemon=True
        ).start()

    def segment_video_thread(self, layers):
        if layers is None:
            layers = self.layers

        try:

            def progress_callback(i, total):
                self.progress_label.configure(
                    text=f"{t("Progress")}: {i+1}/{total}"
                )
                self.progress.set(i / total if total else 0)

            filtered_segment_list = self.segments.filter_by_layers(layers)

            split_video(
                self.video_path,
                filtered_segment_list,
                self.output_path,
                progress_callback=progress_callback,
            )
            self.progress.set(1.0)
            self.progress_label.configure(text=t("Complete"))
            messagebox.showinfo(t("Done"), t("Video segment completed"))
        except Exception as e:
            messagebox.showerror(
                t("Error"), f"{t("Error occurred")}: {str(e)}"
            )
        finally:
            self.execute_button.configure(state="normal")

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
            if self.total_frames > 0:
                self.draw_all_segment_ranges()

    def on_closing(self):
        if self.cap is not None:
            self.cap.release()
        self.destroy()

    def save_project(self):
        """Save project file"""
        if not self.video_path:
            messagebox.showwarning(t("Warning"), t("No video loaded"))
            return

        file_path = filedialog.asksaveasfilename(
            title=t("Save Project"),
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), (t("Select"), "*.*")],
        )

        if file_path:
            try:
                project_data = {
                    "video_path": self.video_path,
                    "output_path": self.output_path,
                    "segment_list": [
                        segment.to_dict() for segment in self.segments
                    ],
                }

                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(project_data, f, ensure_ascii=False, indent=2)

                messagebox.showinfo(t("Done"), t("Project file saved"))
            except Exception as e:
                messagebox.showerror(
                    t("Error"), f"{t("Project save failed")}: {str(e)}"
                )

    def load_project(self):
        """Load project file"""
        file_path = filedialog.askopenfilename(
            title=t("Load Project"),
            filetypes=[
                ("JSON", "*.json"),
                (t("Select"), "*.*"),
            ],
        )

        if file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    project_data = json.load(f)

                # Check if video file exists
                video_path = project_data.get("video_path")
                if not video_path or not os.path.exists(video_path):
                    messagebox.showwarning(
                        t("Warning"), t("Video file not found")
                    )
                    video_path = self._load_video_dialog()
                    if not video_path:
                        return

                # Load video
                self.load_video(video_path)
                self.reset_video_controls()

                # Restore segment list
                self.segments = SegmentManager.from_dicts(
                    self.fps,
                    project_data.get("segment_list", []),
                )
                self.update_segment_list_display()
                self.draw_all_segment_ranges()

                # Restore output path
                self.output_path = project_data.get("output_path")

                # Reset start point
                self.reset_start_point()

                if len(self.segments) > 0:
                    self.execute_button.configure(state="normal")

                messagebox.showinfo(t("Done"), t("Project file loaded"))

            except Exception as e:
                messagebox.showerror(
                    t("Error"), f"{t("Project load failed")}: {str(e)}"
                )


if __name__ == "__main__":
    app = VideoSplitterApp()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()
