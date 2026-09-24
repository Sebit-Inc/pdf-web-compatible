"""Dosya listesindeki tek satır widget'ı."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import customtkinter as ctk

from pdf_web.config import (
    COLORS,
    DIAGNOSIS_HINTS,
    LINEARIZED_FIRST_PAGE_LIMIT,
    MODE_AUTO,
    MODE_HINTS,
    MODE_LABELS,
    MODE_OPTIONS,
)
from pdf_web.engine.analysis import _diagnosis_status
from pdf_web.ui.tooltip import Tooltip
from pdf_web.util import _format_size_mb


def _mode_hint_text(mode: str) -> str:
    description, when = MODE_HINTS.get(mode, ("", ""))
    return f"{MODE_LABELS.get(mode, mode)}\n\n{description}\n\n{when}"


class FileRow(ctk.CTkFrame):
    STATUS_WAIT    = "bekliyor"
    STATUS_RUNNING = "işleniyor"
    STATUS_DONE    = "tamamlandı"
    STATUS_ERROR   = "hata"
    STATUS_CANCEL  = "iptal"

    def __init__(self, master, file_path: str, on_remove, on_convert, on_cancel, **kwargs):
        super().__init__(
            master,
            fg_color=COLORS["card"],
            corner_radius=16,
            border_width=1,
            border_color=COLORS["border"],
            **kwargs,
        )
        self.file_path = file_path
        self.on_remove = on_remove
        self.on_convert = on_convert
        self.on_cancel = on_cancel
        self.status = self.STATUS_WAIT
        self.report_text = ""
        self.output_path: Optional[str] = None
        self.diagnosis: Optional[dict] = None
        self._report_window = None
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)

        info_frame = ctk.CTkFrame(self, fg_color="transparent")
        info_frame.grid(row=0, column=0, padx=(16, 4), pady=14, sticky="ew")

        name = Path(self.file_path).name
        try:
            size_mb = os.path.getsize(self.file_path) / (1024 * 1024)
            size_str = f"{size_mb:.1f} MB"
        except Exception:
            size_str = "?"

        self.name_label = ctk.CTkLabel(
            info_frame, text=name,
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS["text"], anchor="w"
        )
        self.name_label.pack(fill="x")

        meta_frame = ctk.CTkFrame(info_frame, fg_color="transparent")
        meta_frame.pack(fill="x", pady=(6, 0))

        self.size_label = ctk.CTkLabel(
            meta_frame, text=size_str,
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_muted"]
        )
        self.size_label.pack(side="left")

        self.status_pill = ctk.CTkFrame(
            meta_frame, fg_color=COLORS["surface2"], corner_radius=10, height=22
        )
        self.status_pill.pack(side="left", padx=(10, 0))
        self.status_label = ctk.CTkLabel(
            self.status_pill, text="Bekliyor",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=COLORS["text_muted"],
            padx=10,
        )
        self.status_label.pack(padx=2, pady=1)

        # Teşhis etiketi: dosya eklenince ölçülen "web'de neden yavaş açılıyor"
        self.diag_pill = ctk.CTkFrame(
            meta_frame, fg_color=COLORS["surface2"], corner_radius=10, height=22
        )
        self.diag_label = ctk.CTkLabel(
            self.diag_pill, text="",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_muted"],
            padx=10,
        )
        self.diag_label.pack(padx=2, pady=1)
        self.diag_tip = Tooltip(
            self.diag_pill,
            "Dosyanın yapısı ölçülüyor...",
            bind_widgets=[self.diag_pill, self.diag_label],
        )
        self.set_diagnosis_text(
            "İnceleniyor...", "unknown",
            hint="Dosyanın yapısı ölçülüyor: ilk sayfa için ne kadar veri inmesi"
                 " gerektiği, kullanılmayan kaynaklar ve vektör yükü.",
        )

        self.progress = ctk.CTkProgressBar(
            info_frame, height=6, corner_radius=4,
            fg_color=COLORS["surface2"],
            progress_color=COLORS["accent"],
            mode="determinate",
        )
        self.progress.set(0)
        self.progress.pack(fill="x", pady=(10, 0))

        self.detail_label = ctk.CTkLabel(
            info_frame, text="",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_muted"], anchor="w",
        )

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=0, column=1, padx=(4, 12), pady=14, sticky="e")

        self.mode_var = ctk.StringVar(value=MODE_LABELS[MODE_AUTO])
        self.mode_menu = ctk.CTkOptionMenu(
            actions,
            values=[MODE_LABELS[key] for key in MODE_OPTIONS],
            variable=self.mode_var,
            width=176, height=32,
            corner_radius=10,
            fg_color=COLORS["surface2"],
            button_color=COLORS["border"],
            button_hover_color=COLORS["accent"],
            dropdown_fg_color=COLORS["card"],
            dropdown_hover_color=COLORS["surface2"],
            text_color=COLORS["text"],
            font=ctk.CTkFont(size=12),
            command=self.refresh_mode_hint,
        )
        self.mode_menu.pack(side="left", padx=(0, 6))
        self.mode_tip = Tooltip(self.mode_menu, _mode_hint_text(MODE_AUTO))

        self.action_btn = ctk.CTkButton(
            actions, text="Dönüştür", width=88, height=32, corner_radius=10,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color="white",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._on_action,
        )
        self.action_btn.pack(side="left", padx=(0, 6))
        Tooltip(
            self.action_btn,
            "Yalnızca bu dosyayı dönüştürür. Çalışırken İptal'e döner; diğer"
            " dosyalar beklemeye devam eder.",
        )

        self.report_btn = ctk.CTkButton(
            actions, text="Rapor", width=72, height=32, corner_radius=10,
            fg_color=COLORS["surface2"],
            hover_color=COLORS["border"],
            text_color=COLORS["text_muted"],
            font=ctk.CTkFont(size=12, weight="bold"),
            state="disabled",
            command=self.show_report,
        )
        self.report_btn.pack(side="left", padx=(0, 6))

        self.open_btn = ctk.CTkButton(
            actions, text="Klasör", width=72, height=32, corner_radius=10,
            fg_color=COLORS["surface2"],
            hover_color=COLORS["border"],
            text_color=COLORS["text_muted"],
            font=ctk.CTkFont(size=12, weight="bold"),
            state="disabled",
            command=self.open_output_folder,
        )
        self.open_btn.pack(side="left", padx=(0, 6))

        self.remove_btn = ctk.CTkButton(
            actions, text="✕", width=32, height=32, corner_radius=10,
            fg_color="transparent", hover_color=COLORS["error_soft"],
            text_color=COLORS["text_muted"],
            font=ctk.CTkFont(size=14),
            command=lambda: self.on_remove(self)
        )
        self.remove_btn.pack(side="left")

    def _on_action(self):
        if self.status == self.STATUS_RUNNING:
            self.on_cancel(self)
        else:
            self.on_convert(self)

    def selected_mode(self) -> str:
        label = self.mode_var.get()
        for key, text in MODE_LABELS.items():
            if text == label:
                return key
        return MODE_AUTO

    def refresh_mode_hint(self, _label: str = "") -> None:
        """Mod menüsünün ipucu metnini seçili moda göre günceller."""
        self.mode_tip.set_text(_mode_hint_text(self.selected_mode()))

    def set_diagnosis_text(self, text: str, kind: str,
                           hint: Optional[str] = None) -> None:
        colors = {
            "bloat":   (COLORS["warning_soft"], COLORS["warning"]),
            "shared":  (COLORS["warning_soft"], COLORS["warning"]),
            "heavy":   (COLORS["accent_soft"], COLORS["accent"]),
            "tree":    (COLORS["accent_soft"], COLORS["accent"]),
            "ok":      (COLORS["success_soft"], COLORS["success"]),
        }
        pill_bg, color = colors.get(kind, (COLORS["surface2"], COLORS["text_muted"]))
        self.diag_pill.configure(fg_color=pill_bg)
        self.diag_label.configure(text=text, text_color=color)
        self.diag_tip.set_text(hint or DIAGNOSIS_HINTS.get(kind, ""))
        if text and not self.diag_pill.winfo_ismapped():
            self.diag_pill.pack(side="left", padx=(8, 0))

    def set_diagnosis(self, diagnosis: dict) -> None:
        """Teşhis sürecinden gelen ölçümü satırda gösterir."""
        self.diagnosis = diagnosis
        kind, text = _diagnosis_status(diagnosis)
        self.set_diagnosis_text(text, kind)

    def set_result_detail(self, stats: dict) -> None:
        """Dönüşüm sonrası önce/sonra özeti."""
        parts = [
            f"{_format_size_mb(stats['original_size'])} → "
            f"{_format_size_mb(stats['final_size'])}"
        ]
        before = stats.get("first_page_before") or 0
        after = stats.get("first_page_after")
        if after is not None and before:
            parts.append(
                f"ilk sayfa {_format_size_mb(before)} → {_format_size_mb(after)}"
            )
        if stats.get("rasterized"):
            parts.append(f"{stats['rasterized']} sayfa bitmap")
        if stats.get("pruned"):
            parts.append(f"{stats['pruned']} kullanılmayan kaynak ayıklandı")
        self.detail_label.configure(text="  ·  ".join(parts))
        if not self.detail_label.winfo_ismapped():
            self.detail_label.pack(fill="x", pady=(6, 0))

        final_size = stats.get("final_size") or 0
        if stats.get("needs_raster"):
            self.set_diagnosis_text(
                "İçerik paylaşımlı · bitmap modunu deneyin", "shared",
                hint="Kayıpsız onarım bu dosyada yetmedi: ilk sayfa için hâlâ çok"
                     " veri iniyor. Bu satırın modunu 'Tüm sayfalar bitmap' yapıp"
                     " yeniden dönüştürün. Metin seçilemez hale gelir ve dosya"
                     " büyür, ama web'de hızlı açılır.",
            )
        elif after is not None and final_size:
            if after / final_size <= LINEARIZED_FIRST_PAGE_LIMIT:
                self.set_diagnosis_text(
                    f"Hızlı açılıyor · ilk sayfa {_format_size_mb(after)}", "ok",
                    hint=f"Tarayıcı ilk sayfayı göstermek için artık yalnızca"
                         f" {_format_size_mb(after)} indiriyor."
                         f" Ayrıntılar için 'Rapor'a bakın.",
                )

    def open_output_folder(self) -> None:
        target = self.output_path or self.file_path
        folder = str(Path(target).parent)
        try:
            os.startfile(folder)
        except Exception:
            pass

    def set_status(self, status: str, message: str = ""):
        self.status = status
        done_text = "Tamamlandı"
        error_text = "Hata"
        if status == self.STATUS_ERROR and message:
            error_text = "Hata"
        styles = {
            self.STATUS_WAIT:    (COLORS["surface2"], COLORS["text_muted"], "Bekliyor"),
            self.STATUS_RUNNING: (COLORS["accent_soft"], COLORS["accent"], "Başladı"),
            self.STATUS_DONE:    (COLORS["success_soft"], COLORS["success"], done_text),
            self.STATUS_ERROR:   (COLORS["error_soft"], COLORS["error"], error_text),
            self.STATUS_CANCEL:  (COLORS["warning_soft"], COLORS["warning"], "İptal"),
        }
        pill_bg, color, label = styles.get(
            status, (COLORS["surface2"], COLORS["text_muted"], status)
        )
        self.status_pill.configure(fg_color=pill_bg)
        self.status_label.configure(text=label, text_color=color)

        if status == self.STATUS_RUNNING:
            self.progress.configure(
                mode="indeterminate",
                progress_color=COLORS["accent"],
                indeterminate_speed=1.2,
            )
            self.progress.start()
            self.remove_btn.configure(state="disabled")
            self.mode_menu.configure(state="disabled")
            self.action_btn.configure(
                text="İptal",
                fg_color=COLORS["error"],
                hover_color="#dc2626",
                state="normal",
            )
            self.configure(border_color=COLORS["accent"])
        elif status == self.STATUS_DONE:
            self.progress.stop()
            self.progress.configure(mode="determinate", progress_color=COLORS["success"])
            self.progress.set(1)
            self.remove_btn.configure(state="normal")
            self.mode_menu.configure(state="normal")
            self.action_btn.configure(
                text="Dönüştür",
                fg_color=COLORS["accent"],
                hover_color=COLORS["accent_hover"],
                state="normal",
            )
            self.open_btn.configure(
                state="normal",
                fg_color=COLORS["surface2"],
                text_color=COLORS["text"],
            )
            self.configure(border_color=COLORS["success_soft"])
        elif status == self.STATUS_ERROR:
            self.progress.stop()
            self.progress.configure(mode="determinate", progress_color=COLORS["error"])
            self.remove_btn.configure(state="normal")
            self.mode_menu.configure(state="normal")
            self.action_btn.configure(
                text="Yeniden dene",
                fg_color=COLORS["accent"],
                hover_color=COLORS["accent_hover"],
                state="normal",
            )
            self.configure(border_color=COLORS["error"])
            if message:
                self.detail_label.configure(text=f"Hata: {message}")
                if not self.detail_label.winfo_ismapped():
                    self.detail_label.pack(fill="x", pady=(6, 0))
        elif status == self.STATUS_CANCEL:
            self.progress.stop()
            self.progress.configure(mode="determinate", progress_color=COLORS["warning"])
            self.remove_btn.configure(state="normal")
            self.mode_menu.configure(state="normal")
            self.action_btn.configure(
                text="Dönüştür",
                fg_color=COLORS["accent"],
                hover_color=COLORS["accent_hover"],
                state="normal",
            )
            self.configure(border_color=COLORS["warning_soft"])
        else:
            self.remove_btn.configure(state="normal")
            self.mode_menu.configure(state="normal")
            self.action_btn.configure(
                text="Dönüştür",
                fg_color=COLORS["accent"],
                hover_color=COLORS["accent_hover"],
                state="normal",
            )
            self.configure(border_color=COLORS["border"])

        if status in (self.STATUS_WAIT, self.STATUS_RUNNING, self.STATUS_CANCEL):
            self.report_text = ""
            self.report_btn.configure(
                state="disabled",
                fg_color=COLORS["surface2"],
                text_color=COLORS["text_muted"],
            )
            self.open_btn.configure(
                state="disabled",
                fg_color=COLORS["surface2"],
                text_color=COLORS["text_muted"],
            )
            if status != self.STATUS_RUNNING and self.detail_label.winfo_ismapped():
                self.detail_label.pack_forget()

    def set_report(self, report_text: str):
        self.report_text = report_text or ""
        if self.report_text:
            self.report_btn.configure(
                state="normal",
                fg_color=COLORS["accent_soft"],
                text_color=COLORS["accent"],
                hover_color=COLORS["border"],
            )
        else:
            self.report_btn.configure(state="disabled")

    def show_report(self):
        if not self.report_text:
            return
        if self._report_window is not None and self._report_window.winfo_exists():
            self._report_window.focus()
            self._report_window.lift()
            return

        title = f"Rapor — {Path(self.file_path).name}"
        win = ctk.CTkToplevel(self)
        win.title(title)
        win.geometry("760x580")
        win.minsize(520, 360)
        win.configure(fg_color=COLORS["bg"])

        header = ctk.CTkFrame(win, fg_color=COLORS["surface"], corner_radius=0, height=56)
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkLabel(
            header, text=title,
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=COLORS["text"],
        ).pack(side="left", padx=18)

        textbox = ctk.CTkTextbox(
            win,
            font=ctk.CTkFont(family="Consolas", size=13),
            fg_color=COLORS["card"],
            text_color=COLORS["text"],
            border_width=1,
            border_color=COLORS["border"],
            corner_radius=12,
            wrap="none",
        )
        textbox.pack(fill="both", expand=True, padx=16, pady=16)
        textbox.insert("1.0", self.report_text)
        textbox.configure(state="disabled")
        self._report_window = win

    def set_page_progress(self, current: int, total: int, phase: str = "Sayfa",
                         elapsed: Optional[int] = None):
        """Sayfa bazlı ilerleme: indeterminate'den determinate'e geçer."""
        pct = current / total if total > 0 else 0
        if phase == "Ağaç":
            label = "Ağaç düzenleniyor"
        elif phase == "Teşhis":
            label = "Teşhis ediliyor"
        elif phase == "Kayıt":
            label = "Kayıt"
        elif phase == "Raster":
            label = f"Sayfa çiziliyor {current} / {total}"
        else:
            label = f"{phase} {current} / {total}"
        if elapsed and elapsed >= 8:
            label = f"{label}  ·  {elapsed} sn"

        if self.progress.cget("mode") == "indeterminate":
            self.progress.stop()
            self.progress.configure(mode="determinate", progress_color=COLORS["accent"])

        self.progress.set(pct)
        self.status_pill.configure(fg_color=COLORS["accent_soft"])
        self.status_label.configure(text=label, text_color=COLORS["accent"])
