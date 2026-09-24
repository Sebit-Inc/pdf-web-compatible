"""Süreç düzeyinde dönüştürme worker'ları."""

from __future__ import annotations

import os
import shutil
import traceback
from dataclasses import asdict
from typing import Optional

import multiprocessing as mp

from pdf_web.config import (
    LINEARIZED_FIRST_PAGE_LIMIT,
    MODE_AUTO,
    MODE_LOSSLESS,
    MODE_RASTER_ALL,
    MODE_SELECTIVE,
    PAGE_TREE_FANOUT,
    QUALITY_RECOMMENDED,
    SAVE_GARBAGE,
    VECTOR_OPERATION_THRESHOLD,
    INSERT_CHUNK,
)
from pdf_web.engine.analysis import (
    _diagnose_pdf,
    _read_linearization_params,
    count_vector_operations,
)
from pdf_web.engine.raster import (
    _copy_document_extras,
    _rasterize_into_page,
    _rasterize_page_to_doc,
)
from pdf_web.engine.repair import _rewrite_tree_and_linearize
from pdf_web.util import _format_page_numbers, _format_size_mb, _log, _progress


def _diagnose_process(path: str, result_queue: mp.Queue) -> None:
    """Teşhisi ayrı süreçte çalıştırır; nesne grafiği gezintisi UI'yi bloklamaz."""
    try:
        result_queue.put(("diagnosis", asdict(_diagnose_pdf(path))))
    except Exception as exc:
        result_queue.put(("diagnosis_error", str(exc)[:200]))


def _write_selective_raster(input_path: str, output_path: str,
                            is_heavy: list[bool], dpi: int, quality: str,
                            result_queue) -> None:
    """
    Ağır sayfaları bitmap'e çevirir, kalanları olduğu gibi kopyalar.

    Tüm sayfa rasterize edilirken önce bütün sayfa sözlükleri oluşturulur,
    görseller sonra yazılır; böylece sözlükler dosyanın başında kümelenir ve
    pdf.js'in checkLastPage taraması büyük görsellerin arasında dolaşmaz.
    """
    import pymupdf as fitz

    doc_in = fitz.open(input_path)
    doc_out = fitz.open()
    total = len(doc_in)
    try:
        if total and all(is_heavy):
            for index in range(total):
                rect = doc_in[index].rect
                doc_out.new_page(width=rect.width, height=rect.height)
            for index in range(total):
                _progress(result_queue, index + 1, total, "Raster")
                _rasterize_into_page(fitz, doc_in[index], doc_out[index], dpi, quality)
                _progress(result_queue, index + 1, total, "Sayfa")
        else:
            index = 0
            while index < total:
                if is_heavy[index]:
                    _progress(result_queue, index + 1, total, "Raster")
                    _rasterize_page_to_doc(fitz, doc_in[index], doc_out, dpi, quality)
                    _progress(result_queue, index + 1, total, "Sayfa")
                    index += 1
                    continue
                end = index + 1
                while (
                    end < total
                    and not is_heavy[end]
                    and (end - index) < INSERT_CHUNK
                ):
                    end += 1
                doc_out.insert_pdf(doc_in, from_page=index, to_page=end - 1)
                for page_index in range(index, end):
                    _progress(result_queue, page_index + 1, total, "Sayfa")
                index = end

        _copy_document_extras(doc_in, doc_out)
        _progress(result_queue, total, total, "Kayıt")
        doc_out.save(output_path, garbage=SAVE_GARBAGE, deflate=True)
    finally:
        doc_out.close()
        doc_in.close()


def _tree_note(result: dict) -> str:
    note = f"balanced fanout={PAGE_TREE_FANOUT}" if result["tree"] else "flat"
    return f"{note}, linearized={'yes' if result['linearized'] else 'no'}"


def _build_diagnosis_report(
    input_path: str, mode: str, dpi: int, diagnosis, prune: bool,
) -> list[str]:
    mode_label = {
        MODE_RASTER_ALL: "ALL PAGES",
        MODE_LOSSLESS: "LOSSLESS",
    }.get(mode, "SELECTIVE")
    report_lines = [
        f"Input: {input_path}",
        f"Mode: {mode_label}",
        f"Threshold: {VECTOR_OPERATION_THRESHOLD}",
        f"DPI: {dpi}",
        "",
        "Diagnosis:",
        f"  Pages: {diagnosis.page_count}",
        f"  First page download: {_format_size_mb(diagnosis.first_page_bytes)}"
        f" ({diagnosis.first_page_ratio * 100:.0f}% of file,"
        f" {diagnosis.first_page_objects} objects)",
        f"  Declared / used page resources (sampled):"
        f" {diagnosis.declared_resources} / {diagnosis.used_resources}",
        f"  Flat page tree: {'yes' if diagnosis.flat_tree else 'no'}",
        f"  Linearized: {'yes' if diagnosis.linearized else 'no'}",
        f"  Resource pruning: {'yes' if prune else 'no'}",
        "",
    ]
    if diagnosis.error:
        report_lines.insert(6, f"  Diagnosis error: {diagnosis.error}")
    return report_lines


def _analyze_vector_pages(
    doc_in, mode: str, diagnosis, result_queue,
) -> tuple[list[bool], list[int], list[str]]:
    """Sayfa başına bitmap / orijinal kararı ve rapor satırları."""
    total = len(doc_in)
    extra_lines: list[str] = []
    is_heavy: list[bool] = []
    bitmap_pages: list[int] = []

    if mode == MODE_RASTER_ALL:
        _log("Converting all pages to bitmap...")
        extra_lines.append("Converting all pages to bitmap...")
        is_heavy = [True] * total
        bitmap_pages = list(range(1, total + 1))
        for i in range(total):
            line = f"Page {i + 1}: ALL -> BITMAP"
            _log(line)
            extra_lines.append(line)
        return is_heavy, bitmap_pages, extra_lines

    if mode not in (MODE_AUTO, MODE_SELECTIVE):
        extra_lines.append("Lossless repair only; no page rasterized.")
        return [False] * total, [], extra_lines

    if mode == MODE_AUTO and not diagnosis.heavy_vector:
        extra_lines.append(
            "Vector sample found no heavy pages; skipping full page scan."
        )
        return [False] * total, [], extra_lines

    _log("Analyzing PDF...")
    extra_lines.append("Analyzing PDF...")
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
        extra_lines.append(line)
        result_queue.put(("progress", i + 1, total, "Analiz"))
    return is_heavy, bitmap_pages, extra_lines


def _apply_conversion_plan(
    input_path: str, output_path: str, is_heavy: list[bool],
    dpi: int, quality: str, result_queue, total: int, prune: bool,
) -> tuple[str, Optional[dict], bool]:
    heavy_count = sum(is_heavy)
    tree_note = "flat (copy)"
    prune_stats: Optional[dict] = None
    prune_reverted = False
    needs_rewrite = heavy_count > 0 or total > PAGE_TREE_FANOUT or prune

    if not needs_rewrite:
        shutil.copy2(input_path, output_path)
        return tree_note, prune_stats, prune_reverted

    if heavy_count == 0:
        rewrite = _rewrite_tree_and_linearize(
            input_path, output_path, result_queue, total, prune=prune,
        )
    else:
        _write_selective_raster(
            input_path, output_path, is_heavy, dpi, quality, result_queue,
        )
        rewrite = _rewrite_tree_and_linearize(
            output_path, output_path, result_queue, total, prune=prune,
        )
    return _tree_note(rewrite), rewrite["prune"], rewrite["prune_reverted"]


def _build_done_payload(
    output_path: str, diagnosis, original_size: int,
    heavy_count: int, preserved_count: int, bitmap_pages: list[int],
    tree_note: str, prune_stats: Optional[dict], prune_reverted: bool,
    raster_all: bool, report_lines: list[str],
) -> tuple[str, str, dict]:
    params = _read_linearization_params(output_path)
    first_page_after = params[0] if params else None

    # Kayıpsız onarım yetmediyse kalan tek çare rasterlemedir; ancak bu metni
    # kaybettirip dosyayı büyüttüğü için kendiliğinden yapılmaz, önerilir.
    needs_raster = (
        heavy_count == 0
        and params is not None
        and params[0] > params[1] * LINEARIZED_FIRST_PAGE_LIMIT
        and diagnosis.bloated_first_page
    )
    if needs_raster:
        _log("First page section still large; rasterization recommended")

    final_size = os.path.getsize(output_path)
    first_page_line = (
        f"First page download: {_format_size_mb(first_page_after)} /"
        f" {_format_size_mb(final_size)}"
        f" (before: {_format_size_mb(diagnosis.first_page_bytes)})"
        if first_page_after is not None
        else "First page download: not measured (output not linearized)"
    )
    prune_line = "Pruned resource entries: none"
    if prune_reverted:
        prune_line = "Pruned resource entries: reverted (rendering changed)"
    elif prune_stats:
        prune_line = (
            f"Pruned resource entries: {prune_stats['removed']} on"
            f" {prune_stats['pages']} pages"
            f" (skipped {prune_stats['skipped']})"
        )

    size_lines = [
        "",
        f"Original PDF size: {_format_size_mb(original_size)}",
        f"Heavy vector pages: {heavy_count}",
        f"Rasterized pages: {heavy_count}",
        f"Preserved vector pages: {preserved_count}",
        prune_line,
        f"Page tree: {tree_note}",
        first_page_line,
        f"Final PDF size: {_format_size_mb(final_size)}",
        f"Output: {output_path}",
    ]
    if needs_raster:
        size_lines.insert(
            1,
            "Note: first page section is still large; page content is genuinely"
            " shared. Try the 'Tüm sayfalar bitmap' mode for this file.",
        )
    for line in size_lines:
        if line:
            _log(line)
    report_lines.extend(size_lines)
    report_text = "\n".join(report_lines) + "\n"

    if raster_all:
        summary = f"{heavy_count} bitmap (tümü) · {_format_size_mb(final_size)}"
    elif bitmap_pages:
        summary = (
            f"bitmap s. {_format_page_numbers(bitmap_pages)} / "
            f"{preserved_count} vektör · {_format_size_mb(final_size)}"
        )
    else:
        summary = f"0 bitmap / {preserved_count} vektör · {_format_size_mb(final_size)}"
    if first_page_after is not None:
        summary += f" · ilk sayfa {_format_size_mb(first_page_after)}"

    stats = {
        "original_size": original_size,
        "final_size": final_size,
        "first_page_before": diagnosis.first_page_bytes,
        "first_page_after": first_page_after,
        "pruned": None if prune_stats is None else prune_stats["removed"],
        "rasterized": heavy_count,
        "needs_raster": needs_raster,
    }
    return summary, report_text, stats


def _pdf_convert_process(input_path: str, output_path: str,
                          dpi: int,
                          result_queue: mp.Queue,
                          convert_all: bool = False,
                          mode: str = MODE_AUTO,
                          quality: str = QUALITY_RECOMMENDED) -> None:
    """
    Ayrı bir süreçte çalışır — Python GIL'ini ana UI thread'iyle paylaşmaz.

    Teşhise göre üç onarımdan gerekli olanlar uygulanır:
      1. Kaynak budama (kayıpsız): sayfa /Resources'ında kullanılmayan girdileri
         ayıklar. Online2PDF çıktılarında ilk sayfa indirmesini dosyanın
         %99'undan ~%1'e indirir; boyut ve metin değişmez.
      2. Dengeli sayfa ağacı + linearize: pdf.js checkLastPage taramasını keser.
      3. Vektör ağır sayfaları bitmap'e çevirme.
    """
    try:
        import pymupdf as fitz

        if convert_all:
            mode = MODE_RASTER_ALL
        original_size = os.path.getsize(input_path)

        _progress(result_queue, 0, 1, "Teşhis")
        diagnosis = _diagnose_pdf(input_path)
        _progress(result_queue, 1, 1, "Teşhis")

        raster_all = mode == MODE_RASTER_ALL
        prune = mode == MODE_LOSSLESS or (
            mode in (MODE_AUTO, MODE_LOSSLESS) and diagnosis.prunable
        )

        doc_in = fitz.open(input_path)
        total = len(doc_in)
        report_lines = _build_diagnosis_report(
            input_path, mode, dpi, diagnosis, prune,
        )
        try:
            is_heavy, bitmap_pages, extra_lines = _analyze_vector_pages(
                doc_in, mode, diagnosis, result_queue,
            )
        finally:
            doc_in.close()
        report_lines.extend(extra_lines)

        heavy_count = sum(is_heavy)
        preserved_count = total - heavy_count
        bitmap_pages_text = (
            _format_page_numbers(bitmap_pages, limit=None) if bitmap_pages else "-"
        )
        _log(f"\nHeavy vector pages: {heavy_count} / {total}")
        _log(f"Bitmap page numbers: {bitmap_pages_text}")
        report_lines.append("")
        report_lines.append(f"Heavy vector pages: {heavy_count} / {total}")
        report_lines.append(f"Bitmap page numbers: {bitmap_pages_text}")

        tree_note, prune_stats, prune_reverted = _apply_conversion_plan(
            input_path, output_path, is_heavy, dpi, quality,
            result_queue, total, prune,
        )

        summary, report_text, stats = _build_done_payload(
            output_path, diagnosis, original_size,
            heavy_count, preserved_count, bitmap_pages,
            tree_note, prune_stats, prune_reverted,
            raster_all, report_lines,
        )
        result_queue.put(("done", summary, report_text, stats))

    except Exception as e:
        detail = traceback.format_exc()
        _log(f"Convert failed: {e}")
        result_queue.put(("error", str(e)[:300], detail))
