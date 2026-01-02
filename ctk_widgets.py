import tkinter as tk
import customtkinter as ctk


class CTkSpinbox(ctk.CTkFrame):
    """Spinbox widget for CustomTkinter with increment/decrement buttons"""

    def __init__(
        self,
        master,
        initialvalue=None,
        min_value=0,
        max_value=100,
        step=1,
        **kwargs,
    ):
        super().__init__(master, fg_color="transparent")

        self.min_value = min_value
        self.max_value = max_value
        self.step = step

        if initialvalue is None:
            initialvalue = min_value
        self.initialvalue = initialvalue

        # Entry field
        self.entry = ctk.CTkEntry(
            self,
            width=kwargs.get("width", 80),
        )
        self.entry.grid(row=0, column=0, padx=(0, 2))

        # Validation
        vcmd = (self.register(self._validate), "%P")
        self.entry.configure(validate="key", validatecommand=vcmd)

        # Button frame
        button_frame = ctk.CTkFrame(self, fg_color="transparent")
        button_frame.grid(row=0, column=1)

        # Up button
        self.up_button = ctk.CTkButton(
            button_frame,
            text="▲",
            font=ctk.CTkFont(size=8),
            width=15,
            height=10,
            command=self.increment,
            fg_color=["#3B8ED0", "#1F6AA5"],
            hover_color=["#36719F", "#144870"],
            text_color=["#DCE4EE", "#DCE4EE"],
            text_color_disabled=["gray74", "gray60"],
        )
        self.up_button.grid(row=0, column=0)

        # Down button
        self.down_button = ctk.CTkButton(
            button_frame,
            text="▼",
            font=ctk.CTkFont(size=8),
            width=15,
            height=10,
            command=self.decrement,
            fg_color=["#3B8ED0", "#1F6AA5"],
            hover_color=["#36719F", "#144870"],
            text_color=["#DCE4EE", "#DCE4EE"],
            text_color_disabled=["gray74", "gray60"],
        )
        self.down_button.grid(row=1, column=0)

        # Set default value
        self.set_value(initialvalue)

    def _validate(self, value_if_allowed):
        """Validate input is a number"""
        if value_if_allowed == "" or value_if_allowed == "-":
            return True

        try:
            int(value_if_allowed)
            return True
        except ValueError:
            return False

    def increment(self):
        """Increment value"""
        current = self.get_value()
        new_value = min(current + self.step, self.max_value)
        self.set_value(new_value)

    def decrement(self):
        """Decrement value"""
        current = self.get_value()
        new_value = max(current - self.step, self.min_value)
        self.set_value(new_value)

    def get_value(self):
        """Get current value as integer"""
        try:
            value = int(self.entry.get())
            return max(self.min_value, min(value, self.max_value))
        except ValueError:
            return self.min_value

    def set_value(self, value):
        """Set value"""
        value = max(self.min_value, min(value, self.max_value))
        self.entry.delete(0, tk.END)
        self.entry.insert(0, str(value))

    def get(self):
        """Alias for get_value()"""
        return self.get_value()
