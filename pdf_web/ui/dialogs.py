"""Mod rehberi, Hakkında ve güncelleme pencereleri."""

from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk

from pdf_web.config import (
    APP_VERSION,
    COLORS,
    DIAGNOSIS_HINTS,
    MODE_AUTO,
    MODE_HINTS,
    MODE_LABELS,
    MODE_OPTIONS,
)
from pdf_web.updater import UpdateInfo, format_app_version
from pdf_web.util import _load_pdf_icon


def show_mode_guide(app) -> None:
    """Mod menüsündeki seçenekleri ve satırdaki teşhis etiketlerini anlatır."""
    if getattr(app, "_guide_window", None) is not None:
        if app._guide_window.winfo_exists():
            app._guide_window.focus()
            app._guide_window.lift()
            return

    win = ctk.CTkToplevel(app)
    win.title("Mod rehberi")
    win.geometry("640x700")
    win.minsize(560, 560)
    win.configure(fg_color=COLORS["bg"])

    header = ctk.CTkFrame(win, fg_color=COLORS["surface"], corner_radius=0, height=64)
    header.pack(fill="x")
    header.pack_propagate(False)
    ctk.CTkLabel(
        header, text="Hangi modu ne zaman kullanmalı?",
        font=ctk.CTkFont(size=16, weight="bold"),
        text_color=COLORS["text"],
    ).pack(side="left", padx=20)

    body = ctk.CTkScrollableFrame(
        win, fg_color=COLORS["bg"],
        scrollbar_button_color=COLORS["border"],
        scrollbar_button_hover_color=COLORS["text_muted"],
    )
    body.pack(fill="both", expand=True, padx=16, pady=(12, 8))
    body.grid_columnconfigure(0, weight=1)

    ctk.CTkLabel(
        body,
        text=(
            "Uygulama her dosyayı eklendiğinde ölçer ve satırda renkli bir "
            "etiketle ne bulduğunu söyler. Emin değilseniz modu 'Otomatik' "
            "bırakmanız yeterlidir."
        ),
        font=ctk.CTkFont(size=13),
        text_color=COLORS["text_muted"],
        justify="left", wraplength=540, anchor="w",
    ).grid(row=0, column=0, sticky="ew", padx=6, pady=(4, 12))

    row_index = 1
    for mode in MODE_OPTIONS:
        description, when = MODE_HINTS[mode]
        card = ctk.CTkFrame(
            body, fg_color=COLORS["card"], corner_radius=14,
            border_width=1, border_color=COLORS["border"],
        )
        card.grid(row=row_index, column=0, sticky="ew", padx=6, pady=(0, 10))
        row_index += 1
        ctk.CTkLabel(
            card, text=MODE_LABELS[mode],
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS["accent"] if mode == MODE_AUTO else COLORS["text"],
            anchor="w",
        ).pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(
            card, text=description,
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_muted"],
            justify="left", wraplength=500, anchor="w",
        ).pack(fill="x", padx=16)
        ctk.CTkLabel(
            card, text=when,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["success"],
            justify="left", wraplength=500, anchor="w",
        ).pack(fill="x", padx=16, pady=(6, 14))

    ctk.CTkLabel(
        body, text="Satırdaki etiketler",
        font=ctk.CTkFont(size=14, weight="bold"),
        text_color=COLORS["text"], anchor="w",
    ).grid(row=row_index, column=0, sticky="ew", padx=6, pady=(8, 8))
    row_index += 1

    labels = [
        ("Şişkin ilk sayfa", "bloat"),
        ("İçerik paylaşımlı", "shared"),
        ("Vektör ağır sayfalar var", "heavy"),
        ("Sayfa ağacı ve linearize onarılacak", "tree"),
        ("Zaten hızlı açılıyor", "ok"),
    ]
    for title, kind in labels:
        card = ctk.CTkFrame(
            body, fg_color=COLORS["card"], corner_radius=14,
            border_width=1, border_color=COLORS["border"],
        )
        card.grid(row=row_index, column=0, sticky="ew", padx=6, pady=(0, 8))
        row_index += 1
        ctk.CTkLabel(
            card, text=title,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLORS["text"], anchor="w",
        ).pack(fill="x", padx=16, pady=(10, 2))
        ctk.CTkLabel(
            card, text=DIAGNOSIS_HINTS[kind],
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_muted"],
            justify="left", wraplength=500, anchor="w",
        ).pack(fill="x", padx=16, pady=(0, 12))

    ctk.CTkButton(
        win, text="Kapat",
        width=120, height=36, corner_radius=10,
        fg_color=COLORS["accent"],
        hover_color=COLORS["accent_hover"],
        text_color="white",
        font=ctk.CTkFont(size=13, weight="bold"),
        command=win.destroy,
    ).pack(pady=(0, 14))

    app._guide_window = win
    win.after(50, win.focus)


def show_about(app) -> None:
    if app._about_window is not None and app._about_window.winfo_exists():
        app._about_window.focus()
        app._about_window.lift()
        return

    win = ctk.CTkToplevel(app)
    win.title("Hakkında")
    win.geometry("560x640")
    win.minsize(500, 580)
    win.configure(fg_color=COLORS["bg"])
    win.resizable(False, False)

    card = ctk.CTkFrame(
        win, fg_color=COLORS["card"], corner_radius=16,
        border_width=1, border_color=COLORS["border"],
    )
    card.pack(fill="both", expand=True, padx=20, pady=20)

    about_icon = _load_pdf_icon(72)
    ctk.CTkLabel(
        card,
        text="" if about_icon else "PDF",
        image=about_icon,
        font=ctk.CTkFont(size=16, weight="bold"),
        text_color=COLORS["accent"],
    ).pack(pady=(22, 8))
    win._about_icon = about_icon

    ctk.CTkLabel(
        card, text="PDF Web Dönüştürücü",
        font=ctk.CTkFont(size=20, weight="bold"),
        text_color=COLORS["text"],
    ).pack()
    ctk.CTkLabel(
        card, text=format_app_version(APP_VERSION),
        font=ctk.CTkFont(size=13, weight="bold"),
        text_color=COLORS["accent"],
    ).pack(pady=(2, 14))

    ctk.CTkLabel(
        card,
        text=(
            "Akıllı tahtalarda PDF.js ile yavaş açılan PDF'leri "
            "web uyumlu hale getirir.\n\n"
            "Dosya eklenince yapı ölçülür ve gerekli onarımlar uygulanır:\n"
            "• Kullanılmayan sayfa kaynaklarını ayıklama — ilk sayfa için "
            "inen veriyi dosyanın tamamı olmaktan çıkarır. Kayıpsızdır: "
            "boyut, metin ve görüntü değişmez.\n"
            "• Dengeli sayfa ağacı ve linearize (Fast Web View).\n"
            "• 10.000'den fazla vektör işlemi içeren sayfaları bitmap'e "
            "çevirme; diğer sayfalar korunur.\n\n"
            "Mod menüsünden bir dosyayı elle kayıpsız onarıma veya "
            "tüm sayfaları bitmap'e çevirmeye zorlayabilirsiniz."
        ),
        font=ctk.CTkFont(size=13),
        text_color=COLORS["text_muted"],
        justify="center",
        wraplength=420,
    ).pack(padx=24)

    buttons = ctk.CTkFrame(card, fg_color="transparent")
    buttons.pack(pady=(22, 20))
    ctk.CTkButton(
        buttons, text="Güncellemeleri kontrol et",
        width=200, height=36, corner_radius=10,
        fg_color=COLORS["card"],
        hover_color=COLORS["surface2"],
        text_color=COLORS["text"],
        border_width=1,
        border_color=COLORS["border"],
        font=ctk.CTkFont(size=13, weight="bold"),
        command=lambda: app.check_for_updates(silent=False),
    ).pack(side="left", padx=(0, 8))
    ctk.CTkButton(
        buttons, text="Kapat",
        width=120, height=36, corner_radius=10,
        fg_color=COLORS["accent"],
        hover_color=COLORS["accent_hover"],
        text_color="white",
        font=ctk.CTkFont(size=13, weight="bold"),
        command=win.destroy,
    ).pack(side="left")

    app._about_window = win
    win.after(50, win.focus)


def show_update_message(app, title: str, message: str) -> None:
    win = ctk.CTkToplevel(app)
    win.title(title)
    win.geometry("420x220")
    win.minsize(380, 200)
    win.configure(fg_color=COLORS["bg"])
    win.resizable(False, False)

    card = ctk.CTkFrame(
        win, fg_color=COLORS["card"], corner_radius=16,
        border_width=1, border_color=COLORS["border"],
    )
    card.pack(fill="both", expand=True, padx=18, pady=18)
    ctk.CTkLabel(
        card, text=title,
        font=ctk.CTkFont(size=16, weight="bold"),
        text_color=COLORS["text"],
    ).pack(pady=(18, 8))
    ctk.CTkLabel(
        card, text=message,
        font=ctk.CTkFont(size=13),
        text_color=COLORS["text_muted"],
        justify="center",
        wraplength=340,
    ).pack(padx=20)
    ctk.CTkButton(
        card, text="Tamam",
        width=120, height=36, corner_radius=10,
        fg_color=COLORS["accent"],
        hover_color=COLORS["accent_hover"],
        text_color="white",
        font=ctk.CTkFont(size=13, weight="bold"),
        command=win.destroy,
    ).pack(pady=(18, 16))
    win.after(50, win.focus)


def show_update_available(app, info: UpdateInfo, on_update: Callable[[UpdateInfo], None]) -> None:
    existing = getattr(app, "_update_window", None)
    if existing is not None and existing.winfo_exists():
        existing.focus()
        existing.lift()
        return

    win = ctk.CTkToplevel(app)
    win.title("Yeni sürüm")
    win.geometry("460x320")
    win.minsize(420, 280)
    win.configure(fg_color=COLORS["bg"])
    win.resizable(False, False)

    card = ctk.CTkFrame(
        win, fg_color=COLORS["card"], corner_radius=16,
        border_width=1, border_color=COLORS["border"],
    )
    card.pack(fill="both", expand=True, padx=18, pady=18)
    ctk.CTkLabel(
        card, text="Yeni sürüm hazır",
        font=ctk.CTkFont(size=18, weight="bold"),
        text_color=COLORS["text"],
    ).pack(pady=(18, 4))
    ctk.CTkLabel(
        card,
        text=f"{format_app_version(APP_VERSION)}  →  {format_app_version(info.version)}",
        font=ctk.CTkFont(size=13, weight="bold"),
        text_color=COLORS["accent"],
    ).pack(pady=(0, 10))
    ctk.CTkLabel(
        card,
        text=info.notes or "Uygulamayı güncelleyerek yeni sürümü kurabilirsiniz.",
        font=ctk.CTkFont(size=13),
        text_color=COLORS["text_muted"],
        justify="center",
        wraplength=380,
    ).pack(padx=22)

    buttons = ctk.CTkFrame(card, fg_color="transparent")
    buttons.pack(pady=(22, 16))

    def accept() -> None:
        win.destroy()
        on_update(info)

    ctk.CTkButton(
        buttons, text="Daha sonra",
        width=120, height=36, corner_radius=10,
        fg_color=COLORS["card"],
        hover_color=COLORS["surface2"],
        text_color=COLORS["text"],
        border_width=1,
        border_color=COLORS["border"],
        font=ctk.CTkFont(size=13, weight="bold"),
        command=win.destroy,
    ).pack(side="left", padx=(0, 8))
    ctk.CTkButton(
        buttons, text="Güncelle",
        width=120, height=36, corner_radius=10,
        fg_color=COLORS["accent"],
        hover_color=COLORS["accent_hover"],
        text_color="white",
        font=ctk.CTkFont(size=13, weight="bold"),
        command=accept,
    ).pack(side="left")

    app._update_window = win
    win.after(50, win.focus)


class UpdateProgressDialog:
    def __init__(self, app, version: str):
        self.win = ctk.CTkToplevel(app)
        self.win.title("Güncelleniyor")
        self.win.geometry("420x220")
        self.win.minsize(380, 200)
        self.win.configure(fg_color=COLORS["bg"])
        self.win.resizable(False, False)
        self.win.protocol("WM_DELETE_WINDOW", lambda: None)

        card = ctk.CTkFrame(
            self.win, fg_color=COLORS["card"], corner_radius=16,
            border_width=1, border_color=COLORS["border"],
        )
        card.pack(fill="both", expand=True, padx=18, pady=18)
        self._card = card
        ctk.CTkLabel(
            card, text=f"{format_app_version(version)} indiriliyor",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=COLORS["text"],
        ).pack(pady=(18, 12))
        self.status = ctk.CTkLabel(
            card, text="Bağlanılıyor…",
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_muted"],
        )
        self.status.pack()
        self.progress = ctk.CTkProgressBar(
            card, width=280, height=10,
            progress_color=COLORS["accent"],
            fg_color=COLORS["surface2"],
        )
        self.progress.pack(pady=(14, 8))
        self.progress.set(0)
        self.close_btn: Optional[ctk.CTkButton] = None
        self.win.after(50, self.win.focus)

    def set_progress(self, downloaded: int, total: int) -> None:
        if total > 0:
            ratio = min(1.0, downloaded / total)
            self.progress.set(ratio)
            self.status.configure(
                text=f"{_format_mb(downloaded)} / {_format_mb(total)}"
            )
        else:
            self.status.configure(text=f"{_format_mb(downloaded)} indirildi")

    def set_error(self, message: str) -> None:
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.status.configure(text=message, text_color=COLORS["error"])
        if self.close_btn is None:
            self.close_btn = ctk.CTkButton(
                self._card, text="Kapat",
                width=120, height=36, corner_radius=10,
                fg_color=COLORS["accent"],
                hover_color=COLORS["accent_hover"],
                text_color="white",
                font=ctk.CTkFont(size=13, weight="bold"),
                command=self.close,
            )
            self.close_btn.pack(pady=(8, 16))

    def close(self) -> None:
        if self.win.winfo_exists():
            self.win.destroy()


def _format_mb(num_bytes: int) -> str:
    return f"{num_bytes / (1024 * 1024):.1f} MB"
