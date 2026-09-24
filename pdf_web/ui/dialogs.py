"""Mod rehberi ve Hakkında pencereleri."""

from __future__ import annotations

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
    win.geometry("560x600")
    win.minsize(500, 540)
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
        card, text=APP_VERSION,
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

    ctk.CTkButton(
        card, text="Kapat",
        width=120, height=36, corner_radius=10,
        fg_color=COLORS["accent"],
        hover_color=COLORS["accent_hover"],
        text_color="white",
        font=ctk.CTkFont(size=13, weight="bold"),
        command=win.destroy,
    ).pack(pady=(22, 20))

    app._about_window = win
    win.after(50, win.focus)
