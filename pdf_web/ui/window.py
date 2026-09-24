"""Ana uygulama penceresi."""

from __future__ import annotations

import os
import queue
import threading
import time
from pathlib import Path
from typing import Optional

import customtkinter as ctk
import multiprocessing as mp
from tkinter import filedialog

from pdf_web.config import (
    COLORS,
    DPI_LABELS,
    DPI_VALUES,
    MODE_AUTO,
    MODE_LABELS,
    MODE_OPTIONS,
    QUALITY_RECOMMENDED,
    RASTER_PROFILES,
    _DEFAULT_DPI,
)
from pdf_web.engine.convert import _diagnose_process, _pdf_convert_process
from pdf_web.ui.dialogs import (
    UpdateProgressDialog,
    show_about,
    show_mode_guide,
    show_update_available,
    show_update_message,
)
from pdf_web.ui.file_row import FileRow
from pdf_web.ui.tooltip import Tooltip
from pdf_web.util import (
    _get_icon_source,
    _load_pdf_icon,
    _resource_path,
    get_output_path,
)

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False
    DND_FILES = None
    TkinterDnD = None


def apply_theme() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    ctk.set_widget_scaling(1.05)


apply_theme()


class PDFConverterApp(ctk.CTk, TkinterDnD.DnDWrapper if DND_AVAILABLE else object):
    def __init__(self):
        super().__init__()

        self.title("PDF Web Dönüştürücü")
        self.geometry("1060x760")
        self.minsize(960, 620)
        self.configure(fg_color=COLORS["bg"])
        self._apply_window_icon()

        # TkinterDnD başlatma
        if DND_AVAILABLE:
            try:
                self.TkdndVersion = TkinterDnD._require(self)
            except Exception:
                pass

        # Durum değişkenleri
        self.file_rows: list[FileRow] = []
        self.output_dir: Optional[str] = None
        self.is_converting = False
        self.cancel_event = threading.Event()
        self.abort_batch = threading.Event()
        self._current_row = None
        self._msg_queue: queue.Queue = queue.Queue()
        self._selected_dpi: int = _DEFAULT_DPI
        self._quality: str = QUALITY_RECOMMENDED
        self._about_window = None
        self._guide_window = None
        self._update_window = None
        self._update_checking = False

        # Teşhis kuyruğu: dosya eklenince yapısal ölçüm ayrı süreçte yapılır
        self._diag_queue: queue.Queue = queue.Queue()
        threading.Thread(target=self._diagnosis_worker, daemon=True).start()

        self._build_ui()
        self._poll_queue()

        # DnD kaydı
        self._setup_dnd(self)
        self.after(1500, lambda: self.check_for_updates(silent=True))

    def _apply_window_icon(self) -> None:
        ico_path = _resource_path("assets/icon.ico")
        if ico_path.exists():
            try:
                self.iconbitmap(str(ico_path))
            except Exception:
                pass
        source = _get_icon_source()
        if source is not None:
            try:
                from PIL import ImageTk
                photo = ImageTk.PhotoImage(source.resize((256, 256), Image.Resampling.LANCZOS))
                self.iconphoto(True, photo)
                self._window_photo = photo
            except Exception:
                pass

    def _setup_dnd(self, widget):
        if DND_AVAILABLE:
            try:
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop)
            except Exception:
                pass

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build_header()
        self._build_file_list()
        self._build_footer()

    def _build_header(self):
        header = ctk.CTkFrame(
            self, fg_color=COLORS["surface"], corner_radius=0, height=88
        )
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.columnconfigure(1, weight=1)

        self._header_icon = _load_pdf_icon(48)
        ctk.CTkLabel(
            header,
            text="" if self._header_icon else "PDF",
            image=self._header_icon,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="white",
            width=48, height=48,
        ).grid(row=0, column=0, padx=(22, 12), pady=20)

        title_frame = ctk.CTkFrame(header, fg_color="transparent")
        title_frame.grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(
            title_frame, text="PDF Web Dönüştürücü",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=COLORS["text"]
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_frame,
            text="PDF'leri webde hızlı açılır hale getirir",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_muted"]
        ).pack(anchor="w")

        settings = ctk.CTkFrame(header, fg_color="transparent")
        settings.grid(row=0, column=2, padx=20, sticky="e")

        dpi_box = ctk.CTkFrame(
            settings, fg_color=COLORS["card"], corner_radius=12,
            border_width=1, border_color=COLORS["border"],
        )
        dpi_box.pack(side="left", padx=(0, 8))
        # Bu iki ayar yalnızca bitmap'e çevrilen sayfaları etkiler;
        # kayıpsız onarımda görüntü hiç yeniden üretilmez.
        ctk.CTkLabel(
            dpi_box, text="Bitmap",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_muted"]
        ).pack(side="left", padx=(12, 6), pady=8)
        menu_values = [DPI_LABELS[d] for d in DPI_VALUES]
        self.dpi_var = ctk.StringVar(value=DPI_LABELS[_DEFAULT_DPI])
        self.dpi_menu = ctk.CTkOptionMenu(
            dpi_box,
            values=menu_values,
            variable=self.dpi_var,
            width=148, height=28,
            corner_radius=8,
            fg_color=COLORS["surface2"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
            dropdown_fg_color=COLORS["card"],
            dropdown_hover_color=COLORS["surface2"],
            font=ctk.CTkFont(size=12),
            command=self._on_dpi_change,
        )
        self.dpi_menu.pack(side="left", padx=(0, 6), pady=6)

        self.quality_var = ctk.StringVar(
            value=RASTER_PROFILES[QUALITY_RECOMMENDED]["label"]
        )
        self.quality_menu = ctk.CTkOptionMenu(
            dpi_box,
            values=[profile["label"] for profile in RASTER_PROFILES.values()],
            variable=self.quality_var,
            width=176, height=28,
            corner_radius=8,
            fg_color=COLORS["surface2"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
            dropdown_fg_color=COLORS["card"],
            dropdown_hover_color=COLORS["surface2"],
            font=ctk.CTkFont(size=12),
            command=self._on_quality_change,
        )
        self.quality_menu.pack(side="left", padx=(0, 8), pady=6)

        Tooltip(
            self.dpi_menu,
            "Bir sayfa bitmap'e çevrilirken kullanılacak çözünürlük.\n\n"
            "Kayıpsız onarımda hiçbir sayfa yeniden üretilmediği için bu ayarın"
            " etkisi olmaz. 250 DPI çoğu kitap için yeterlidir.",
        )
        Tooltip(
            self.quality_menu,
            "Bitmap sayfaların JPEG kalitesi.\n\n"
            "Önerilen: çözünürlüğü kaynağın kendi görsel kalitesiyle sınırlar,"
            " yani görüntüyü bozmadan gereksiz büyümeyi önler.\n"
            "Yüksek: en keskin sonuç, en büyük dosya.\n"
            "Dengeli: en küçük dosya, gözle fark edilebilir yumuşama olabilir.",
        )

        self.out_btn = ctk.CTkButton(
            settings, text="Çıktı klasörü",
            width=132, height=40, corner_radius=12,
            fg_color=COLORS["card"],
            hover_color=COLORS["surface2"],
            text_color=COLORS["text"],
            border_width=1,
            border_color=COLORS["border"],
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._choose_output_dir,
        )
        self.out_btn.pack(side="left", padx=(0, 8))

        self.about_btn = ctk.CTkButton(
            settings, text="Hakkında",
            width=96, height=40, corner_radius=12,
            fg_color=COLORS["card"],
            hover_color=COLORS["surface2"],
            text_color=COLORS["text"],
            border_width=1,
            border_color=COLORS["border"],
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._show_about,
        )
        self.about_btn.pack(side="left")

    def _build_file_list(self):
        list_frame = ctk.CTkFrame(self, fg_color=COLORS["bg"], corner_radius=0)
        list_frame.grid(row=1, column=0, sticky="nsew")
        list_frame.grid_columnconfigure(0, weight=1)
        list_frame.grid_rowconfigure(0, weight=1)

        self.scroll_frame = ctk.CTkScrollableFrame(
            list_frame,
            fg_color=COLORS["bg"],
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["text_muted"],
        )
        self.scroll_frame.grid(row=0, column=0, sticky="nsew", padx=20, pady=(8, 4))
        self.scroll_frame.grid_columnconfigure(0, weight=1)

        self.empty_card = ctk.CTkFrame(
            self.scroll_frame,
            fg_color=COLORS["card"],
            corner_radius=20,
            border_width=1,
            border_color=COLORS["border"],
        )
        self.empty_card.grid(row=0, column=0, sticky="ew", pady=12, padx=2)

        self._drop_icon = _load_pdf_icon(80)
        ctk.CTkLabel(
            self.empty_card,
            text="" if self._drop_icon else "PDF",
            image=self._drop_icon,
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=COLORS["accent"],
        ).pack(pady=(36, 12))
        ctk.CTkLabel(
            self.empty_card,
            text="PDF dosyalarını buraya sürükleyin",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=COLORS["text"],
        ).pack()
        ctk.CTkLabel(
            self.empty_card,
            text="veya dosya seçmek için aşağıdaki düğmeyi kullanın",
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_muted"],
        ).pack(pady=(4, 16))
        self.empty_add_btn = ctk.CTkButton(
            self.empty_card, text="Dosya seç",
            width=140, height=36, corner_radius=10,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color="white",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._add_files,
        )
        self.empty_add_btn.pack(pady=(0, 12))
        ctk.CTkLabel(
            self.empty_card,
            text="Birden fazla dosya eklenebilir  ·  Çıktı aynı klasöre -web eki ile kaydedilir",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_muted"],
        ).pack(pady=(0, 36))

        self._setup_dnd(list_frame)
        self._setup_dnd(self.scroll_frame)
        self._setup_dnd(self.empty_card)

    def _build_footer(self):
        bottom_bar = ctk.CTkFrame(
            self, fg_color=COLORS["surface"], corner_radius=0, height=76
        )
        bottom_bar.grid(row=2, column=0, sticky="ew")
        bottom_bar.grid_propagate(False)
        bottom_bar.columnconfigure(0, weight=1)

        self.summary_label = ctk.CTkLabel(
            bottom_bar, text="Henüz dosya eklenmedi",
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_muted"],
            anchor="w"
        )
        self.summary_label.grid(row=0, column=0, padx=22, pady=20, sticky="w")

        btn_frame = ctk.CTkFrame(bottom_bar, fg_color="transparent")
        btn_frame.grid(row=0, column=1, padx=18, pady=14, sticky="e")

        self.add_btn = ctk.CTkButton(
            btn_frame, text="Dosya ekle",
            width=128, height=42, corner_radius=12,
            fg_color=COLORS["card"],
            hover_color=COLORS["surface2"],
            text_color=COLORS["text"],
            border_width=1,
            border_color=COLORS["border"],
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._add_files,
        )
        self.add_btn.pack(side="left", padx=(0, 10))

        # Satır bazlı mod menülerini tek hamlede ayarlamak için toplu seçici
        ctk.CTkLabel(
            btn_frame, text="Tümü için mod",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_muted"],
        ).pack(side="left", padx=(0, 6))

        self.bulk_mode_var = ctk.StringVar(value=MODE_LABELS[MODE_AUTO])
        self.bulk_mode_menu = ctk.CTkOptionMenu(
            btn_frame,
            values=[MODE_LABELS[key] for key in MODE_OPTIONS],
            variable=self.bulk_mode_var,
            width=186, height=42,
            corner_radius=12,
            fg_color=COLORS["card"],
            button_color=COLORS["border"],
            button_hover_color=COLORS["accent"],
            dropdown_fg_color=COLORS["card"],
            dropdown_hover_color=COLORS["surface2"],
            text_color=COLORS["text"],
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._on_bulk_mode_change,
        )
        self.bulk_mode_menu.pack(side="left", padx=(0, 4))
        Tooltip(
            self.bulk_mode_menu,
            "Tüm dosyaların modunu birden ayarlar. Tek bir dosya için satırdaki"
            " mod menüsünü kullanabilirsiniz.\n\nHangi modu seçeceğinizden emin"
            " değilseniz 'Otomatik' bırakın; yanındaki ? düğmesi modları anlatır.",
        )

        self.mode_help_btn = ctk.CTkButton(
            btn_frame, text="?",
            width=34, height=42, corner_radius=12,
            fg_color=COLORS["card"],
            hover_color=COLORS["surface2"],
            text_color=COLORS["accent"],
            border_width=1,
            border_color=COLORS["border"],
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self._show_mode_guide,
        )
        self.mode_help_btn.pack(side="left", padx=(0, 12))
        Tooltip(self.mode_help_btn, "Hangi modu ne zaman kullanmalı?")

        self.convert_btn = ctk.CTkButton(
            btn_frame, text="Dönüştür",
            width=148, height=42, corner_radius=12,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color="white",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._start_conversion,
            state="disabled",
        )
        self.convert_btn.pack(side="left")

    def _add_files(self):
        paths = filedialog.askopenfilenames(
            title="PDF Dosyaları Seçin",
            filetypes=[("PDF Dosyaları", "*.pdf"), ("Tüm Dosyalar", "*.*")]
        )
        for p in paths:
            self._add_file(p)

    def _on_drop(self, event):
        raw_paths = self.tk.splitlist(event.data)
        for p in raw_paths:
            cleaned_path = str(p).strip('{} "\'')
            if cleaned_path.lower().endswith(".pdf") and os.path.exists(cleaned_path):
                self._add_file(cleaned_path)

    def _add_file(self, path: str):
        existing = [r.file_path for r in self.file_rows]
        if path in existing:
            return
        if self.empty_card.winfo_ismapped():
            self.empty_card.grid_forget()

        row = FileRow(
            self.scroll_frame, path,
            on_remove=self._remove_file,
            on_convert=self._convert_row,
            on_cancel=self._cancel_row,
        )
        row.grid(row=len(self.file_rows), column=0, sticky="ew", pady=(0, 8), padx=2)
        row.mode_var.set(self.bulk_mode_var.get())
        row.refresh_mode_hint()
        self._setup_dnd(row)
        self.file_rows.append(row)
        self._update_summary()
        self._diag_queue.put(row)

    def _remove_file(self, row: FileRow):
        if self.is_converting:
            return
        row.grid_forget()
        row.destroy()
        self.file_rows.remove(row)
        for i, r in enumerate(self.file_rows):
            r.grid(row=i, column=0, sticky="ew", pady=(0, 8), padx=2)
        if not self.file_rows:
            self.empty_card.grid(row=0, column=0, sticky="ew", pady=12, padx=2)
        self._update_summary()

    def _choose_output_dir(self):
        d = filedialog.askdirectory(title="Çıktı Klasörü Seçin")
        if d:
            self.output_dir = d
            short = Path(d).name
            self.out_btn.configure(
                text=short,
                text_color=COLORS["accent"],
                border_color=COLORS["accent"],
            )

    def _show_mode_guide(self):
        show_mode_guide(self)

    def _show_about(self):
        show_about(self)

    def check_for_updates(self, silent: bool = True) -> None:
        if self._update_checking:
            return
        self._update_checking = True

        def worker() -> None:
            from pdf_web.config import APP_VERSION
            from pdf_web.updater import check_for_update

            info = None
            error = False
            try:
                info = check_for_update(APP_VERSION)
            except Exception:
                error = True
            self.after(0, lambda i=info, e=error: self._on_update_check_done(i, silent, e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_update_check_done(self, info, silent: bool, error: bool) -> None:
        self._update_checking = False
        if error:
            if not silent:
                show_update_message(
                    self,
                    "Güncelleme kontrol edilemedi",
                    "Sürüm bilgisi alınamadı. İnternet bağlantınızı kontrol edip tekrar deneyin.",
                )
            return
        if info is None:
            if not silent:
                show_update_message(self, "Uygulama güncel", "Yüklü sürüm en son yayınlanan sürüm.")
            return
        show_update_available(self, info, self._begin_update)

    def _begin_update(self, info) -> None:
        if self.is_converting:
            show_update_message(
                self,
                "Güncelleme bekliyor",
                "Önce dönüştürmeyi bitirin veya iptal edin, sonra tekrar deneyin.",
            )
            return

        from pdf_web.updater import apply_and_restart, download, download_dir_for, is_frozen

        if not is_frozen():
            import webbrowser
            webbrowser.open(info.url)
            show_update_message(
                self,
                "Kaynak koddan çalışıyor",
                "Güncelleme yalnızca paketlenmiş exe'de kendini kurar. İndirme sayfası tarayıcıda açıldı.",
            )
            return

        dialog = UpdateProgressDialog(self, info.version)
        dest = download_dir_for(info.version)

        def worker() -> None:
            def progress(downloaded: int, total: int) -> None:
                self.after(0, lambda d=downloaded, t=total: dialog.set_progress(d, t))

            try:
                path = download(info.url, dest, info.sha256, progress)
            except Exception as exc:
                self.after(0, lambda e=exc: dialog.set_error(str(e)))
                return

            def finish() -> None:
                try:
                    apply_and_restart(path)
                except Exception as exc:
                    dialog.set_error(str(exc))
                    return
                dialog.close()
                self.destroy()

            self.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def _update_summary(self):
        n = len(self.file_rows)
        if n == 0:
            self.summary_label.configure(text="Henüz dosya eklenmedi")
            self.convert_btn.configure(state="disabled")
        else:
            self.summary_label.configure(text=f"{n} dosya seçildi")
            if not self.is_converting:
                self.convert_btn.configure(state="normal")

    def _on_dpi_change(self, label: str):
        """DPI menüsünden seçim değiştiğinde çağrılır."""
        try:
            self._selected_dpi = int(label.split()[0])
        except (ValueError, IndexError):
            pass

    def _on_quality_change(self, label: str):
        for key, profile in RASTER_PROFILES.items():
            if profile["label"] == label:
                self._quality = key
                return

    def _on_bulk_mode_change(self, label: str):
        """Toplu seçici: her satırın mod menüsünü aynı değere çeker."""
        if self.is_converting:
            return
        for row in self.file_rows:
            row.mode_var.set(label)
            row.refresh_mode_hint()

    def _diagnosis_worker(self):
        """
        Dosya eklenince yapısal ölçümü ayrı süreçte çalıştırır.
        Nesne grafiği gezintisi saf Python olduğu için thread'de UI'yi bloklardı.
        """
        while True:
            row = self._diag_queue.get()
            if row is None:
                continue
            try:
                diag_queue: mp.Queue = mp.Queue()
                process = mp.Process(
                    target=_diagnose_process,
                    args=(row.file_path, diag_queue),
                    daemon=True,
                )
                process.start()
                try:
                    kind, payload = diag_queue.get(timeout=120)
                except Exception:
                    kind, payload = "diagnosis_error", "zaman aşımı"
                process.join(timeout=5)
                if process.is_alive():
                    process.terminate()
                if kind == "diagnosis":
                    self._msg_queue.put(("diagnosis", row, payload))
                else:
                    self._msg_queue.put(("diagnosis_error", row, payload))
            except Exception as exc:
                self._msg_queue.put(("diagnosis_error", row, str(exc)[:200]))

    def _pending_jobs(self, rows: Optional[list] = None) -> list:
        jobs = []
        for row in rows or self.file_rows:
            if row.status in (FileRow.STATUS_RUNNING, FileRow.STATUS_DONE):
                continue
            jobs.append((row, row.selected_mode()))
        return jobs

    def _set_busy(self, busy: bool) -> None:
        self.is_converting = busy
        add_state = "disabled" if busy else "normal"
        self.add_btn.configure(state=add_state)
        self.empty_add_btn.configure(state=add_state)
        self.bulk_mode_menu.configure(state=add_state)
        if busy:
            self.convert_btn.configure(
                text="İptal et",
                fg_color=COLORS["error"],
                hover_color="#dc2626",
            )
        else:
            self.convert_btn.configure(
                text="Dönüştür",
                fg_color=COLORS["accent"],
                hover_color=COLORS["accent_hover"],
            )
            self._current_row = None
        for row in self.file_rows:
            if busy and row.status != FileRow.STATUS_RUNNING:
                row.action_btn.configure(state="disabled")
            elif not busy:
                row.action_btn.configure(state="normal")

    def _convert_row(self, row: FileRow) -> None:
        """Satırdaki Dönüştür: yalnızca bu dosya. Çalışıyorsa yok sayılır."""
        if self.is_converting:
            return
        if row.status == FileRow.STATUS_RUNNING:
            return
        self._begin_jobs([(row, row.selected_mode())])

    def _cancel_row(self, row: FileRow) -> None:
        """Satırdaki İptal: yalnızca o an işlenen dosyayı durdurur, kuyruk devam eder."""
        if not self.is_converting:
            return
        if row is self._current_row or row.status == FileRow.STATUS_RUNNING:
            self.cancel_event.set()

    def _start_conversion(self):
        if self.is_converting:
            # Toplu iptal: çalışan dosya dursun, kalanlar beklemeye geri dönsün
            self.abort_batch.set()
            self.cancel_event.set()
            self.convert_btn.configure(text="İptal ediliyor…")
            return

        jobs = self._pending_jobs()
        if not jobs:
            return
        self._begin_jobs(jobs)

    def _begin_jobs(self, jobs: list) -> None:
        self.cancel_event.clear()
        self.abort_batch.clear()
        self._set_busy(True)
        thread = threading.Thread(
            target=self._conversion_worker,
            args=(self._selected_dpi, self._quality, jobs),
            daemon=True,
        )
        thread.start()

    def _conversion_worker(self, dpi: int, quality: str, jobs: list):
        """
        Thread olarak çalışır; her dosya için ayrı bir multiprocessing.Process
        başlatır. Process → Queue → Thread → _msg_queue → UI köprüsü kurar.
        Bu sayede PyMuPDF GIL'i ana UI thread'ini bloklayamaz.
        """
        done = 0
        errors = 0
        cancelled = 0
        total_jobs = len(jobs)
        output_folders: set[str] = set()

        for index, (row, mode) in enumerate(jobs):
            if self.abort_batch.is_set():
                break

            self.cancel_event.clear()
            self._current_row = row
            out_path = get_output_path(row.file_path, dpi, self.output_dir)
            self._msg_queue.put(("status", row, FileRow.STATUS_RUNNING, ""))
            self._msg_queue.put((
                "bulk", f"{index + 1}/{total_jobs} dosya  ·  {done} tamamlandı",
            ))

            mp_queue: mp.Queue = mp.Queue()
            process = mp.Process(
                target=_pdf_convert_process,
                args=(row.file_path, out_path, dpi, mp_queue, False, mode, quality),
                daemon=True,
            )
            process.start()

            file_done = False
            last_progress = ("Sayfa", 0, 1)
            last_beat = time.time()
            started = time.time()
            while not file_done:
                if self.cancel_event.is_set():
                    process.terminate()
                    process.join(timeout=3)
                    if process.is_alive():
                        process.kill()
                        process.join(timeout=2)
                    self._msg_queue.put(("status", row, FileRow.STATUS_CANCEL, ""))
                    cancelled += 1
                    file_done = True
                    break

                try:
                    msg = mp_queue.get(timeout=0.2)
                except Exception:
                    elapsed = int(time.time() - started)
                    if time.time() - last_beat >= 1:
                        last_beat = time.time()
                        phase, cur, total = last_progress
                        self._msg_queue.put((
                            "page_progress", row, cur, total, phase, elapsed,
                        ))
                    if not process.is_alive():
                        leftover = None
                        try:
                            leftover = mp_queue.get_nowait()
                        except Exception:
                            pass
                        if leftover and leftover[0] in ("done", "error"):
                            msg = leftover
                        else:
                            errors += 1
                            phase, cur, total = last_progress
                            self._msg_queue.put((
                                "status", row, FileRow.STATUS_ERROR,
                                f"Süreç kapandı ({phase} {cur}/{total})",
                            ))
                            file_done = True
                            continue
                    else:
                        continue

                kind = msg[0]
                if kind == "progress":
                    cur, total = msg[1], msg[2]
                    phase = msg[3] if len(msg) > 3 else "Sayfa"
                    last_progress = (phase, cur, total)
                    elapsed = int(time.time() - started)
                    self._msg_queue.put((
                        "page_progress", row, cur, total, phase, elapsed,
                    ))
                elif kind == "done":
                    done += 1
                    summary = msg[1] if len(msg) > 1 else ""
                    report_text = msg[2] if len(msg) > 2 else ""
                    stats = msg[3] if len(msg) > 3 else None
                    self._msg_queue.put(("status", row, FileRow.STATUS_DONE, summary))
                    if report_text:
                        self._msg_queue.put(("report", row, report_text))
                    if stats:
                        self._msg_queue.put(("result", row, out_path, stats))
                    output_folders.add(str(Path(out_path).parent))
                    file_done = True
                elif kind == "error":
                    errors += 1
                    short = msg[1] if len(msg) > 1 else "Bilinmeyen hata"
                    detail = msg[2] if len(msg) > 2 else short
                    self._msg_queue.put(("status", row, FileRow.STATUS_ERROR, short))
                    self._msg_queue.put(("report", row, detail))
                    file_done = True

            process.join(timeout=5)

        parts = [f"✓ {done} dosya dönüştürüldü"]
        if cancelled:
            parts.append(f"■ {cancelled} iptal")
        if errors:
            parts.append(f"✕ {errors} hata")
        self._msg_queue.put(("done", "  ·  ".join(parts)))
        if output_folders:
            self._msg_queue.put(("open_folders", output_folders))

    def _poll_queue(self):
        """
        Ana thread'de 50ms'de bir çalışır; iş thread'inden gelen
        UI güncellemelerini tkinter widget'larına uygular.
        """
        try:
            while True:
                msg = self._msg_queue.get_nowait()
                kind = msg[0]
                if kind == "status":
                    _, row, status, detail = msg
                    row.set_status(status, detail)
                elif kind == "page_progress":
                    _, row, cur, total = msg[:4]
                    phase = msg[4] if len(msg) > 4 else "Sayfa"
                    elapsed = msg[5] if len(msg) > 5 else None
                    row.set_page_progress(cur, total, phase, elapsed)
                elif kind == "open_folders":
                    _, folders = msg
                    for folder in folders:
                        try:
                            os.startfile(folder)
                        except Exception:
                            pass
                elif kind == "report":
                    _, row, report_text = msg
                    row.set_report(report_text)
                elif kind == "result":
                    _, row, out_path, stats = msg
                    row.output_path = out_path
                    row.set_result_detail(stats)
                elif kind == "diagnosis":
                    _, row, diagnosis = msg
                    row.set_diagnosis(diagnosis)
                elif kind == "diagnosis_error":
                    _, row, detail = msg
                    row.set_diagnosis_text("Analiz edilemedi", "unknown")
                    row.detail_label.configure(text=f"Teşhis hatası: {detail}")
                    if not row.detail_label.winfo_ismapped():
                        row.detail_label.pack(fill="x", pady=(6, 0))
                elif kind == "bulk":
                    _, text = msg
                    if self.is_converting:
                        self.summary_label.configure(text=text)
                elif kind == "done":
                    _, summary = msg
                    self._set_busy(False)
                    self.summary_label.configure(text=summary)
        except queue.Empty:
            pass
        self.after(50, self._poll_queue)
