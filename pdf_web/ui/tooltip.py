"""Fare üzerinde beklerken gösterilen açıklama kartı."""

from __future__ import annotations

import tkinter as tk

from pdf_web.config import COLORS


class Tooltip:
    """
    Fare bir widget'ın üzerinde beklerken küçük açıklama kartı gösterir.

    CustomTkinter widget'ları alt bileşenlerden oluştuğu için olayları hem
    widget'a hem de üzerini kaplayan çocuklarına bağlamak gerekir.
    """

    DELAY_MS = 400

    def __init__(self, widget, text: str, bind_widgets=None, wraplength: int = 340):
        self.widget = widget
        self.text = text
        self.wraplength = wraplength
        self._window = None
        self._after_id = None
        for target in bind_widgets or [widget]:
            try:
                target.bind("<Enter>", self._schedule, add="+")
                target.bind("<Leave>", self._hide, add="+")
                target.bind("<ButtonPress>", self._hide, add="+")
            except Exception:
                pass

    def set_text(self, text: str) -> None:
        self.text = text
        self._hide()

    def _schedule(self, _event=None):
        self._cancel()
        try:
            self._after_id = self.widget.after(self.DELAY_MS, self._show)
        except Exception:
            self._after_id = None

    def _cancel(self):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self):
        self._after_id = None
        if self._window is not None or not self.text:
            return
        try:
            pos_x = self.widget.winfo_rootx() + 10
            pos_y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
            window = tk.Toplevel(self.widget)
        except Exception:
            return
        window.wm_overrideredirect(True)
        window.configure(background=COLORS["border"])
        tk.Label(
            window,
            text=self.text,
            justify="left",
            background=COLORS["card"],
            foreground=COLORS["text"],
            wraplength=self.wraplength,
            padx=12, pady=9,
            font=("Segoe UI", 9),
        ).pack(padx=1, pady=1)
        window.wm_geometry(f"+{pos_x}+{pos_y}")
        try:
            window.attributes("-topmost", True)
        except Exception:
            pass
        self._window = window

    def _hide(self, _event=None):
        self._cancel()
        if self._window is not None:
            try:
                self._window.destroy()
            except Exception:
                pass
            self._window = None
