"""
PDF Vektör → Bitmap Dönüştürücü
Eğitsel tasarımcılar için web uyumlu PDF hazırlama aracı.
"""

import os
import sys
import shutil
import threading
import queue
import multiprocessing as mp
from pathlib import Path
from typing import Optional
import customtkinter as ctk
from tkinter import filedialog
import tkinter as tk
from PIL import Image

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False

# ─── Tema ──────────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")
ctk.set_widget_scaling(1.05)

COLORS = {
    "bg":           "#0b0d12",
    "surface":      "#12151e",
    "card":         "#171b26",
    "surface2":     "#1e2433",
    "accent":       "#3d8bfd",
    "accent_hover": "#5ba0ff",
    "accent_soft":  "#1b2d4d",
    "accent2":      "#6366f1",
    "success":      "#34d399",
    "success_soft": "#12352c",
    "warning":      "#fbbf24",
    "warning_soft": "#3a2e12",
    "error":        "#f87171",
    "error_soft":   "#3a1818",
    "text":         "#f1f5f9",
    "text_muted":   "#94a3b8",
    "border":       "#2a3148",
}

APP_AUTHOR = "Ahmet BOZDOĞAN"
APP_VERSION = "v1.0"


def _resource_path(relative: str) -> Path:
    """Kaynak dosya yolu — kaynak kod ve PyInstaller exe için."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / relative
    return Path(__file__).resolve().parent / relative


_ICON_SOURCE: Optional[Image.Image] = None


def _prepare_icon_image(image: Image.Image) -> Image.Image:
    """
    Yuvarlatılmış ikon kenarlarındaki siyah hale/pürüzü temizler.
    Yüksek çözünürlüğü korur; düşük alfa piksellerini şeffaf yapar.
    """
    img = image.convert("RGBA")
    if max(img.size) > 512:
        img = img.resize((512, 512), Image.Resampling.LANCZOS)
    red, green, blue, alpha = img.split()
    alpha = alpha.point(lambda value: 0 if value < 18 else value)
    return Image.merge("RGBA", (red, green, blue, alpha))


def _get_icon_source() -> Optional[Image.Image]:
    global _ICON_SOURCE
    if _ICON_SOURCE is not None:
        return _ICON_SOURCE
    path = _resource_path("assets/pdf-app-icon.png")
    if not path.exists():
        return None
    _ICON_SOURCE = _prepare_icon_image(Image.open(path))
    return _ICON_SOURCE


def _load_pdf_icon(size: int) -> Optional[ctk.CTkImage]:
    source = _get_icon_source()
    if source is None:
        return None
    # Orijinal çözünürlüğü CTkImage'e ver; ikinci kez küçültme kenarı bozar
    return ctk.CTkImage(light_image=source, dark_image=source, size=(size, size))

# 150'den 300'e 20'şer adımla + 300 (toplam 9 seçenek)
DPI_VALUES = [150, 170, 190, 210, 230, 250, 270, 290, 300]
DPI_LABELS = {d: f"{d} DPI" if d != 250 else "250 DPI (önerilen)" for d in DPI_VALUES}
_DEFAULT_DPI = 250

# Web uygulamasındaki PDF.js eşiği ile aynı. İleride 15000 / 20000 yapılabilir.
VECTOR_OPERATION_THRESHOLD = 10000

# PDF.js OPS.fill / OPS.stroke / OPS.fillStroke karşılıkları (PyMuPDF path type)
_VECTOR_DRAW_TYPES = frozenset({"f", "s", "fs"})


# ─── Vektör Analizi ve PDF Yardımcıları ───────────────────────────────────────

def count_vector_operations(page) -> int:
    """
    Sayfadaki vector operation sayısını hesaplar.

    Web uygulamasındaki PDF.js getOperatorList kriterine denk:
    fill, stroke, fillStroke, closePath.
    Image/raster operation'lar (paintImageXObject vb.) sayılmaz;
    get_cdrawings yalnızca vektör path'lerini döner.
    """
    count = 0
    try:
        drawings = page.get_cdrawings()
    except TypeError:
        drawings = page.get_drawings()

    for drawing in drawings:
        draw_type = drawing.get("type")
        if draw_type in _VECTOR_DRAW_TYPES:
            count += 1
        # fill-only path'lerde closePath None olabilir; yalnızca True sayılır
        if drawing.get("closePath") is True:
            count += 1
    return count


def _format_size_mb(num_bytes: int) -> str:
    return f"{num_bytes / (1024 * 1024):.1f} MB"


def _format_page_numbers(pages: list[int], limit: int | None = 8) -> str:
    if not pages:
        return "-"
    if limit is None or len(pages) <= limit:
        return ", ".join(str(page) for page in pages)
    shown = ", ".join(str(page) for page in pages[:limit])
    return f"{shown}... ({len(pages)} sayfa)"


def _log(message: str) -> None:
    """Windows konsol kod sayfası unicode karakterleri bozmasın."""
    try:
        print(message, flush=True)
    except UnicodeEncodeError:
        print(message.encode("ascii", "replace").decode("ascii"), flush=True)


def _copy_document_extras(doc_in, doc_out) -> None:
    """Metadata, TOC ve sayfa etiketlerini mümkün olduğunca kopyala."""
    try:
        metadata = doc_in.metadata
        if metadata:
            doc_out.set_metadata(metadata)
    except Exception:
        pass
    try:
        xml_meta = doc_in.get_xml_metadata()
        if xml_meta:
            doc_out.set_xml_metadata(xml_meta)
    except Exception:
        pass
    try:
        toc = doc_in.get_toc()
        if toc:
            doc_out.set_toc(toc)
    except Exception:
        pass
    try:
        labels = doc_in.get_page_labels()
        if labels:
            doc_out.set_page_labels(labels)
    except Exception:
        pass


def _rasterize_page_to_doc(fitz, page, doc_out, dpi: int) -> None:
    """
    Mevcut bitmap ayarlarını korur: seçilen DPI, RGB, alpha yok.
    Pixmap doğrudan gömülür; kayıtta Deflate (lossless) uygulanır.
    PDF native WebP desteklemez; JPEG kayıplı olduğu için çizgi/metin
    ağırlıklı sayfalarda kullanılmaz.
    """
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB, alpha=False)
    rect = page.rect
    new_page = doc_out.new_page(width=rect.width, height=rect.height)
    new_page.insert_image(rect, pixmap=pix)


# ─── Süreç Düzeyinde Worker (GIL'den bağımsız) ────────────────────────────────

def _pdf_convert_process(input_path: str, output_path: str,
                          dpi: int,
                          result_queue: mp.Queue) -> None:
    """
    Ayrı bir süreçte çalışır — Python GIL'ini ana UI thread'iyle paylaşmaz.
    Önce operator analizi, sonra yalnızca ağır vektör sayfalar rasterize edilir.
    """
    try:
        import pymupdf as fitz

        original_size = os.path.getsize(input_path)
        doc_in = fitz.open(input_path)
        total = len(doc_in)

        _log("Analyzing PDF...")
        is_heavy: list[bool] = []
        bitmap_pages: list[int] = []
        report_lines: list[str] = [
            f"Input: {input_path}",
            f"Threshold: {VECTOR_OPERATION_THRESHOLD}",
            f"DPI: {dpi}",
            "",
            "Analyzing PDF...",
        ]

        for i, page in enumerate(doc_in):
            try:
                count = count_vector_operations(page)
                fail_note = ""
            except Exception as exc:
                # Analiz başarısızsa eski davranış: sayfayı rasterize et
                fail_note = f" (analysis failed: {exc})"
                count = VECTOR_OPERATION_THRESHOLD + 1
            heavy = count > VECTOR_OPERATION_THRESHOLD
            is_heavy.append(heavy)
            action = "BITMAP" if heavy else "ORIGINAL"
            if heavy:
                bitmap_pages.append(i + 1)
            line = f"Page {i + 1}: {count:,} vector operations -> {action}{fail_note}"
            _log(line)
            report_lines.append(line)
            result_queue.put(("progress", i + 1, total, "Analiz"))

        heavy_count = sum(is_heavy)
        preserved_count = total - heavy_count
        bitmap_pages_text = _format_page_numbers(bitmap_pages, limit=None) if bitmap_pages else "-"
        _log(f"\nHeavy vector pages: {heavy_count} / {total}")
        _log(f"Bitmap page numbers: {bitmap_pages_text}")
        report_lines.append("")
        report_lines.append(f"Heavy vector pages: {heavy_count} / {total}")
        report_lines.append(f"Bitmap page numbers: {bitmap_pages_text}")

        if heavy_count == 0:
            # Hiç ağır sayfa yoksa orijinal PDF birebir korunur
            shutil.copy2(input_path, output_path)
        else:
            doc_out = fitz.open()
            i = 0
            while i < total:
                if is_heavy[i]:
                    _rasterize_page_to_doc(fitz, doc_in[i], doc_out, dpi)
                    result_queue.put(("progress", i + 1, total, "Sayfa"))
                    i += 1
                else:
                    j = i + 1
                    while j < total and not is_heavy[j]:
                        j += 1
                    # Ardışık orijinal sayfalar tek seferde kopyalanır
                    doc_out.insert_pdf(doc_in, from_page=i, to_page=j - 1)
                    for k in range(i, j):
                        result_queue.put(("progress", k + 1, total, "Sayfa"))
                    i = j

            _copy_document_extras(doc_in, doc_out)
            doc_out.save(output_path, garbage=4, deflate=True, deflate_images=True)
            doc_out.close()

        doc_in.close()

        final_size = os.path.getsize(output_path)
        size_lines = [
            "",
            f"Original PDF size: {_format_size_mb(original_size)}",
            f"Heavy vector pages: {heavy_count}",
            f"Rasterized pages: {heavy_count}",
            f"Preserved vector pages: {preserved_count}",
            f"Final PDF size: {_format_size_mb(final_size)}",
            f"Output: {output_path}",
        ]
        for line in size_lines:
            if line:
                _log(line)
        report_lines.extend(size_lines)
        report_text = "\n".join(report_lines) + "\n"

        if bitmap_pages:
            summary = (
                f"bitmap s. {_format_page_numbers(bitmap_pages)} / "
                f"{preserved_count} vektör · {_format_size_mb(final_size)}"
            )
        else:
            summary = f"0 bitmap / {preserved_count} vektör · {_format_size_mb(final_size)}"
        result_queue.put(("done", summary, report_text))

    except Exception as e:
        result_queue.put(("error", str(e)[:200]))


# ─── Yardımcı Fonksiyonlar ────────────────────────────────────────────────────

def get_output_path(input_path: str, dpi: int, output_dir: Optional[str] = None) -> str:
    p = Path(input_path)
    out_name = f"{p.stem}-web-{dpi}dpi{p.suffix}"
    if output_dir:
        return str(Path(output_dir) / out_name)
    return str(p.parent / out_name)


# ─── Dosya Satırı Widget'ı ───────────────────────────────────────────────────

class FileRow(ctk.CTkFrame):
    STATUS_WAIT    = "bekliyor"
    STATUS_RUNNING = "işleniyor"
    STATUS_DONE    = "tamamlandı"
    STATUS_ERROR   = "hata"
    STATUS_CANCEL  = "iptal"

    def __init__(self, master, file_path: str, on_remove, **kwargs):
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
        self.status = self.STATUS_WAIT
        self.report_text = ""
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

        self.progress = ctk.CTkProgressBar(
            info_frame, height=6, corner_radius=4,
            fg_color=COLORS["surface2"],
            progress_color=COLORS["accent"],
            mode="determinate",
        )
        self.progress.set(0)
        self.progress.pack(fill="x", pady=(10, 0))

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=0, column=1, padx=(4, 12), pady=14, sticky="e")

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

        self.remove_btn = ctk.CTkButton(
            actions, text="✕", width=32, height=32, corner_radius=10,
            fg_color="transparent", hover_color=COLORS["error_soft"],
            text_color=COLORS["text_muted"],
            font=ctk.CTkFont(size=14),
            command=lambda: self.on_remove(self)
        )
        self.remove_btn.pack(side="left")

    def set_status(self, status: str, message: str = ""):
        self.status = status
        done_text = "Tamamlandı"
        styles = {
            self.STATUS_WAIT:    (COLORS["surface2"], COLORS["text_muted"], "Bekliyor"),
            self.STATUS_RUNNING: (COLORS["accent_soft"], COLORS["accent"], "Başladı"),
            self.STATUS_DONE:    (COLORS["success_soft"], COLORS["success"], done_text),
            self.STATUS_ERROR:   (COLORS["error_soft"], COLORS["error"], f"Hata: {message}"),
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
            self.configure(border_color=COLORS["accent"])
        elif status == self.STATUS_DONE:
            self.progress.stop()
            self.progress.configure(mode="determinate", progress_color=COLORS["success"])
            self.progress.set(1)
            self.remove_btn.configure(state="normal")
            self.configure(border_color=COLORS["success_soft"])
        elif status == self.STATUS_ERROR:
            self.progress.stop()
            self.progress.configure(mode="determinate", progress_color=COLORS["error"])
            self.remove_btn.configure(state="normal")
            self.configure(border_color=COLORS["error"])
        elif status == self.STATUS_CANCEL:
            self.progress.stop()
            self.progress.configure(mode="determinate", progress_color=COLORS["warning"])
            self.remove_btn.configure(state="normal")
            self.configure(border_color=COLORS["warning_soft"])
        else:
            self.remove_btn.configure(state="normal")
            self.configure(border_color=COLORS["border"])

        if status != self.STATUS_DONE:
            self.report_text = ""
            self.report_btn.configure(
                state="disabled",
                fg_color=COLORS["surface2"],
                text_color=COLORS["text_muted"],
            )

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

    def set_page_progress(self, current: int, total: int, phase: str = "Sayfa"):
        """Sayfa bazlı ilerleme: indeterminate'den determinate'e geçer."""
        pct = current / total if total > 0 else 0
        label = f"{phase} {current} / {total}"

        if self.progress.cget("mode") == "indeterminate":
            self.progress.stop()
            self.progress.configure(mode="determinate", progress_color=COLORS["accent"])

        self.progress.set(pct)
        self.status_pill.configure(fg_color=COLORS["accent_soft"])
        self.status_label.configure(text=label, text_color=COLORS["accent"])


# ─── Ana Uygulama ─────────────────────────────────────────────────────────────

class PDFConverterApp(ctk.CTk, TkinterDnD.DnDWrapper if DND_AVAILABLE else object):
    def __init__(self):
        super().__init__()

        self.title("PDF Web Dönüştürücü")
        self.geometry("860x720")
        self.minsize(760, 600)
        self.configure(fg_color=COLORS["bg"])
        self._apply_window_icon()

        # TkinterDnD başlatma
        if DND_AVAILABLE:
            try:
                self.TkdndVersion = TkinterDnD._require(self)
            except Exception as e:
                pass

        # Durum değişkenleri
        self.file_rows: list[FileRow] = []
        self.output_dir: Optional[str] = None
        self.is_converting = False
        self.cancel_event = threading.Event()
        self._msg_queue: queue.Queue = queue.Queue()
        self._selected_dpi: int = _DEFAULT_DPI
        self._about_window = None

        self._build_ui()
        self._poll_queue()

        # DnD kaydı
        self._setup_dnd(self)

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

    # ── UI ──────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

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
        ctk.CTkLabel(
            dpi_box, text="Kalite",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_muted"]
        ).pack(side="left", padx=(12, 6), pady=8)
        menu_values = [DPI_LABELS[d] for d in DPI_VALUES]
        self.dpi_var = ctk.StringVar(value=DPI_LABELS[_DEFAULT_DPI])
        self.dpi_menu = ctk.CTkOptionMenu(
            dpi_box,
            values=menu_values,
            variable=self.dpi_var,
            width=168, height=28,
            corner_radius=8,
            fg_color=COLORS["surface2"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
            dropdown_fg_color=COLORS["card"],
            dropdown_hover_color=COLORS["surface2"],
            font=ctk.CTkFont(size=12),
            command=self._on_dpi_change,
        )
        self.dpi_menu.pack(side="left", padx=(0, 8), pady=6)

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

    # ── Dosya Yönetimi ───────────────────────────────────────────────────────

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

        row = FileRow(self.scroll_frame, path, on_remove=self._remove_file)
        row.grid(row=len(self.file_rows), column=0, sticky="ew", pady=(0, 8), padx=2)
        self._setup_dnd(row)
        self.file_rows.append(row)
        self._update_summary()

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

    def _show_about(self):
        if self._about_window is not None and self._about_window.winfo_exists():
            self._about_window.focus()
            self._about_window.lift()
            return

        win = ctk.CTkToplevel(self)
        win.title("Hakkında")
        win.geometry("520x480")
        win.minsize(460, 420)
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
                "Akıllı tahtalarda PDF.js ile yavaş açılan, vektör yoğun "
                "PDF'leri web uyumlu hale getirir.\n\n"
                "Yalnızca 10.000'den fazla vektör işlemi içeren sayfalar "
                "bitmap'e çevrilir. Metin, görsel ve normal vektör "
                "sayfaları orijinal halleriyle korunur."
            ),
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_muted"],
            justify="center",
            wraplength=420,
        ).pack(padx=24)

        meta = ctk.CTkFrame(card, fg_color=COLORS["surface2"], corner_radius=12)
        meta.pack(fill="x", padx=24, pady=18)
        ctk.CTkLabel(
            meta, text="Geliştirici",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_muted"],
        ).pack(pady=(10, 0))
        ctk.CTkLabel(
            meta, text=APP_AUTHOR,
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS["text"],
        ).pack(pady=(0, 10))

        ctk.CTkButton(
            card, text="Kapat",
            width=120, height=36, corner_radius=10,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color="white",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=win.destroy,
        ).pack(pady=(0, 20))

        self._about_window = win
        win.after(50, win.focus)

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

    # ── Dönüştürme ──────────────────────────────────────────────────────────

    def _start_conversion(self):
        if self.is_converting:
            self.cancel_event.set()
            self.convert_btn.configure(
                text="Dönüştür",
                fg_color=COLORS["accent"],
                hover_color=COLORS["accent_hover"],
            )
            return

        if not self.file_rows:
            return

        self.is_converting = True
        self.cancel_event.clear()
        self.add_btn.configure(state="disabled")
        self.empty_add_btn.configure(state="disabled")
        self.convert_btn.configure(
            text="İptal et",
            fg_color=COLORS["error"],
            hover_color="#dc2626",
        )

        dpi = self._selected_dpi

        thread = threading.Thread(
            target=self._conversion_worker,
            args=(dpi,),
            daemon=True,
        )
        thread.start()

    def _conversion_worker(self, dpi: int):
        """
        Thread olarak çalışır; her dosya için ayrı bir multiprocessing.Process
        başlatır. Process → Queue → Thread → _msg_queue → UI köprüsü kurar.
        Bu sayede PyMuPDF GIL'i ana UI thread'ini bloklayamaz.
        """
        rows = list(self.file_rows)
        done = 0
        errors = 0
        output_folders: set[str] = set()  # başarıyla dönüştürülen klasörler

        for row in rows:
            if self.cancel_event.is_set():
                self._msg_queue.put(("status", row, FileRow.STATUS_CANCEL, ""))
                continue

            out_path = get_output_path(row.file_path, dpi, self.output_dir)
            self._msg_queue.put(("status", row, FileRow.STATUS_RUNNING, ""))

            # Ayrı süreç başlat
            mp_queue: mp.Queue = mp.Queue()
            process = mp.Process(
                target=_pdf_convert_process,
                args=(row.file_path, out_path, dpi, mp_queue),
                daemon=True,
            )
            process.start()

            # Process'ten gelen mesajları köprüle → _msg_queue
            file_done = False
            while not file_done:
                if self.cancel_event.is_set():
                    process.terminate()
                    process.join(timeout=3)
                    self._msg_queue.put(("status", row, FileRow.STATUS_CANCEL, ""))
                    file_done = True
                    break

                try:
                    msg = mp_queue.get(timeout=0.08)  # 80ms bekleme
                except Exception:
                    # Queue boş — process hâlâ çalışıyor mu?
                    if not process.is_alive():
                        # Süreç kapandı ama "done"/"error" gelmediyse hata
                        self._msg_queue.put(("status", row, FileRow.STATUS_ERROR,
                                             "Süreç beklenmedik şekilde kapandı"))
                        file_done = True
                    continue

                kind = msg[0]
                if kind == "progress":
                    cur, total = msg[1], msg[2]
                    phase = msg[3] if len(msg) > 3 else "Sayfa"
                    self._msg_queue.put(("page_progress", row, cur, total, phase))
                elif kind == "done":
                    done += 1
                    summary = msg[1] if len(msg) > 1 else ""
                    report_text = msg[2] if len(msg) > 2 else ""
                    self._msg_queue.put(("status", row, FileRow.STATUS_DONE, summary))
                    if report_text:
                        self._msg_queue.put(("report", row, report_text))
                    output_folders.add(str(Path(out_path).parent))
                    file_done = True
                elif kind == "error":
                    errors += 1
                    self._msg_queue.put(("status", row, FileRow.STATUS_ERROR, msg[1]))
                    file_done = True

            process.join(timeout=5)

        summary = f"✓ {done} dosya dönüştürüldü"
        if errors:
            summary += f"  ·  ✕ {errors} hata"
        self._msg_queue.put(("done", summary))

        # Başarılı dönüşüm varsa çıktı klasörlerini Explorer'da aç
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
                    row.set_page_progress(cur, total, phase)
                elif kind == "open_folders":
                    _, folders = msg
                    for folder in folders:
                        try:
                            os.startfile(folder)  # Windows Explorer
                        except Exception:
                            pass
                elif kind == "report":
                    _, row, report_text = msg
                    row.set_report(report_text)
                elif kind == "done":
                    _, summary = msg
                    self.is_converting = False
                    self.add_btn.configure(state="normal")
                    self.empty_add_btn.configure(state="normal")
                    self.convert_btn.configure(
                        text="Dönüştür",
                        fg_color=COLORS["accent"],
                        hover_color=COLORS["accent_hover"],
                    )
                    self.summary_label.configure(text=summary)
        except queue.Empty:
            pass
        self.after(50, self._poll_queue)


# ─── Giriş Noktası ────────────────────────────────────────────────────────────

def main():
    # PyInstaller ile paketlenmiş Windows exe için zorunlu
    mp.freeze_support()
    app = PDFConverterApp()
    app.mainloop()


if __name__ == "__main__":
    main()
