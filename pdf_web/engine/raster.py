"""Sayfa rasterizasyonu ve JPEG gömme."""

from __future__ import annotations

import io
from typing import Optional

from PIL import Image

from pdf_web.config import QUALITY_RECOMMENDED, RASTER_MIN_DPI, RASTER_PROFILES


def _raster_profile(quality: str) -> dict:
    return RASTER_PROFILES.get(quality, RASTER_PROFILES[QUALITY_RECOMMENDED])


def _source_image_dpi(page) -> float:
    """Sayfadaki gömülü görsellerin en yüksek etkin çözünürlüğü (DPI)."""
    try:
        infos = page.get_image_info(xrefs=False)
    except Exception:
        return 0.0
    best = 0.0
    for info in infos:
        bbox = info.get("bbox")
        width = info.get("width", 0)
        if not bbox or width <= 0:
            continue
        bbox_width = abs(bbox[2] - bbox[0])
        if bbox_width <= 1:
            continue
        best = max(best, width * 72.0 / bbox_width)
    return best


def _effective_raster_dpi(page, dpi: int, profile: dict) -> int:
    """
    "Önerilen" profilde render çözünürlüğünü kaynağın kendi çözünürlüğüyle sınırlar.
    Kaynak görselleri 200 DPI ise 250 DPI'da render etmek detay eklemez, yalnızca
    dosyayı büyütür. Görsel içermeyen (metin/vektör) sayfalarda seçilen DPI kalır.
    """
    if not profile.get("source_aware"):
        return dpi
    source_dpi = _source_image_dpi(page)
    if source_dpi <= 0:
        return dpi
    return max(RASTER_MIN_DPI, min(dpi, int(round(source_dpi * 1.1))))


def _pixmap_to_jpeg(pix, profile: dict) -> Optional[bytes]:
    """Pixmap'i JPEG'e çevirir. 4:4:4 (subsampling=0) renkli ince metni bulanıklaştırmaz."""
    try:
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    except Exception:
        return None
    buffer = io.BytesIO()
    try:
        image.save(
            buffer,
            format="JPEG",
            quality=profile["quality"],
            subsampling=profile["subsampling"],
            optimize=True,
        )
    except Exception:
        return None
    finally:
        image.close()
    return buffer.getvalue()


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


def _rasterize_into_page(fitz, src_page, dest_page, dpi: int,
                         quality: str = QUALITY_RECOMMENDED) -> None:
    """
    Sayfayı RGB bitmap'e çevirip JPEG olarak gömer.

    Pixmap'i kayıpsız Deflate ile gömmek 250 DPI'lık 960x540 pt bir slaytta
    sayfa başına ~29 MB ham veri üretiyordu (158 sayfalık kitap ~1 GB).
    JPEG sıkıştırma aynı çözünürlüğü sayfa başına ~0.5 MB'a indirir.
    """
    profile = _raster_profile(quality)
    render_dpi = _effective_raster_dpi(src_page, dpi, profile)
    mat = fitz.Matrix(render_dpi / 72, render_dpi / 72)
    pix = src_page.get_pixmap(matrix=mat, colorspace=fitz.csRGB, alpha=False)
    stream = _pixmap_to_jpeg(pix, profile)
    if stream is None:
        dest_page.insert_image(dest_page.rect, pixmap=pix)
        return
    dest_page.insert_image(dest_page.rect, stream=stream)


def _rasterize_page_to_doc(fitz, src_page, doc_out, dpi: int,
                           quality: str = QUALITY_RECOMMENDED) -> None:
    rect = src_page.rect
    dest = doc_out.new_page(width=rect.width, height=rect.height)
    _rasterize_into_page(fitz, src_page, dest, dpi, quality)
