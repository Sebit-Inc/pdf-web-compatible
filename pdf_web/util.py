"""Yol, format, log ve ikon yardımcıları. Motor katmanı GUI import etmez."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PIL import Image


def _resource_path(relative: str) -> Path:
    """Kaynak dosya yolu — kaynak kod ve PyInstaller exe için."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / relative
    return Path(__file__).resolve().parent.parent / relative


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


def _load_pdf_icon(size: int):
    import customtkinter as ctk

    source = _get_icon_source()
    if source is None:
        return None
    # Orijinal çözünürlüğü CTkImage'e ver; ikinci kez küçültme kenarı bozar
    return ctk.CTkImage(light_image=source, dark_image=source, size=(size, size))


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


def get_output_path(input_path: str, dpi: int, output_dir: Optional[str] = None) -> str:
    p = Path(input_path)
    out_name = f"{p.stem}-web-{dpi}dpi{p.suffix}"
    if output_dir:
        return str(Path(output_dir) / out_name)
    return str(p.parent / out_name)


def _progress(result_queue, current: int, total: int, phase: str) -> None:
    result_queue.put(("progress", current, total, phase))
