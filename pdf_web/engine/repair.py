"""Kaynak budama, dengeli sayfa ağacı ve linearize."""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
from typing import Optional

from pdf_web.config import (
    PAGE_TREE_FANOUT,
    RENDER_CHECK_DPI,
    RENDER_CHECK_SAMPLES,
)
from pdf_web.engine.analysis import (
    _page_resource_usage,
    _page_resources,
    _sample_indices,
)
from pdf_web.util import _log, _progress


def _pikepdf_node_count(node) -> int:
    from pikepdf import Name
    if node.get("/Type") == Name.Pages:
        return int(node["/Count"])
    return 1


def _build_balanced_page_tree_pikepdf(
    pdf, fanout: int = PAGE_TREE_FANOUT, result_queue=None
) -> bool:
    """Düz /Pages listesini pikepdf ile dengeli ağaca çevirir."""
    from pikepdf import Array, Dictionary, Name

    page_total = len(pdf.pages)
    if result_queue is not None:
        _progress(result_queue, 0, max(page_total, 1), "Ağaç")

    nodes = []
    for i, page in enumerate(pdf.pages):
        nodes.append(page.obj)
        if result_queue is not None:
            _progress(result_queue, i + 1, page_total, "Ağaç")
    if len(nodes) <= fanout:
        if result_queue is not None and page_total:
            _progress(result_queue, page_total, page_total, "Ağaç")
        return False

    first_level = True
    while len(nodes) > 1:
        level = []
        done = 0
        for i in range(0, len(nodes), fanout):
            group = nodes[i : i + fanout]
            if len(group) == 1:
                level.append(group[0])
                done += 1
            else:
                count = sum(_pikepdf_node_count(node) for node in group)
                parent = pdf.make_indirect(
                    Dictionary(
                        Type=Name.Pages,
                        Kids=Array(group),
                        Count=count,
                    )
                )
                for node in group:
                    node[Name.Parent] = parent
                    done += 1
                    if first_level and result_queue is not None:
                        _progress(
                            result_queue, min(done, page_total), page_total, "Ağaç"
                        )
                level.append(parent)
                continue
            if first_level and result_queue is not None:
                _progress(result_queue, min(done, page_total), page_total, "Ağaç")
        if len(level) >= len(nodes):
            break
        nodes = level
        first_level = False

    pdf.Root[Name.Pages] = nodes[0]
    if result_queue is not None and page_total:
        _progress(result_queue, page_total, page_total, "Ağaç")
    return True


def _prune_page_resources(pdf, result_queue=None) -> dict:
    """
    Sayfa /Resources sözlüklerini içerikte gerçekten kullanılan girdilere indirger.

    Ayıklanan nesneler dosyadan silinmez (her biri kendi sayfası tarafından
    kullanılır); yalnızca ilk sayfadan erişilebilen küme küçülür. Bu sayede
    linearize edilen dosyada /E, dosya boyutunun tamamı olmaktan çıkar.
    """
    from pikepdf import Dictionary

    # test_selective_convert mock.patch("app._page_resource_usage") yolunu koru
    usage_fn = _page_resource_usage
    app_mod = sys.modules.get("app")
    if app_mod is not None:
        usage_fn = getattr(app_mod, "_page_resource_usage", usage_fn)

    total = len(pdf.pages)
    stats = {"pages": 0, "removed": 0, "skipped": 0}
    if result_queue is not None:
        _progress(result_queue, 0, max(total, 1), "Budama")

    for index, page in enumerate(pdf.pages):
        usage = usage_fn(page)
        resources = _page_resources(page) if usage is not None else None
        if usage is None or resources is None:
            stats["skipped"] += 1
        else:
            pruned = Dictionary()
            removed = 0
            try:
                for key in resources.keys():
                    value = resources[key]
                    names = usage.get(key)
                    if names is None or not isinstance(value, Dictionary):
                        pruned[key] = value
                        continue
                    kept = Dictionary()
                    for name in value.keys():
                        if name in names:
                            kept[name] = value[name]
                        else:
                            removed += 1
                    pruned[key] = kept
            except Exception:
                removed = 0
                stats["skipped"] += 1
            if removed:
                page.obj["/Resources"] = pruned
                stats["pages"] += 1
                stats["removed"] += removed
        if result_queue is not None:
            _progress(result_queue, index + 1, max(total, 1), "Budama")
    return stats


def _render_signatures(path: str, indices: list[int],
                       dpi: int = RENDER_CHECK_DPI) -> list[str]:
    """Örnek sayfaların düşük çözünürlüklü render hash'leri."""
    if not indices:
        return []
    try:
        import pymupdf as fitz
    except ImportError:
        return []
    signatures: list[str] = []
    try:
        doc = fitz.open(path)
    except Exception:
        return []
    try:
        matrix = fitz.Matrix(dpi / 72, dpi / 72)
        for index in indices:
            if index >= len(doc):
                continue
            pix = doc[index].get_pixmap(matrix=matrix, alpha=False)
            signatures.append(hashlib.sha1(pix.samples).hexdigest())
    except Exception:
        return []
    finally:
        doc.close()
    return signatures


def _rewrite_tree_and_linearize(
    src: str, dst: str, result_queue, total: int, prune: bool = False
) -> dict:
    """
    Sayfa ağacını kurup linearized kaydeder; istenirse önce sayfa /Resources
    sözlüklerini budar. Büyük dosyalarda PyMuPDF xref yazımı kullanmaz.

    Budama render'ı değiştirirse (ör. sayfa kaynaklarına yaslanan Type3 font)
    budamasız yeniden yazılır.
    """
    result = {
        "tree": False,
        "linearized": False,
        "prune": None,
        "prune_reverted": False,
    }
    try:
        import pikepdf
    except ImportError:
        if src != dst:
            shutil.copy2(src, dst)
        return result

    _progress(result_queue, 0, max(total, 1), "Ağaç")
    tmp_path = f"{dst}.tmp"

    def write(do_prune: bool) -> tuple[bool, Optional[dict]]:
        stats = None
        with pikepdf.open(src) as pdf:
            if do_prune:
                stats = _prune_page_resources(pdf, result_queue)
            tree_built = _build_balanced_page_tree_pikepdf(
                pdf, result_queue=result_queue
            )
            last_pct = [-1]
            page_count = len(pdf.pages)

            def on_linearize_progress(percent: int) -> None:
                if percent == last_pct[0]:
                    return
                last_pct[0] = percent
                current = int(round(percent * page_count / 100)) if page_count else percent
                _progress(result_queue, current, max(page_count, 1), "Linearize")

            _progress(result_queue, 0, max(page_count, 1), "Linearize")
            pdf.save(tmp_path, linearize=True, progress=on_linearize_progress)
            if last_pct[0] < 100:
                _progress(result_queue, page_count, max(page_count, 1), "Linearize")
        return tree_built, stats

    try:
        sample = _sample_indices(total, RENDER_CHECK_SAMPLES) if prune else []
        before = _render_signatures(src, sample) if sample else []
        try:
            tree_built, stats = write(prune)
        except Exception as exc:
            if not prune:
                raise
            _log(f"Prune pass failed ({exc}); retrying without pruning")
            tree_built, stats = write(False)
            result["prune_reverted"] = True

        if prune and before and not result["prune_reverted"]:
            if _render_signatures(tmp_path, sample) != before:
                _log("Prune changed page rendering; reverting")
                tree_built, stats = write(False)
                result["prune_reverted"] = True

        os.replace(tmp_path, dst)
        result["tree"] = tree_built
        result["linearized"] = True
        result["prune"] = None if result["prune_reverted"] else stats
        return result
    except Exception as exc:
        _log(f"Tree/linearize failed ({exc})")
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        if src != dst:
            try:
                shutil.copy2(src, dst)
            except Exception:
                pass
        return result


def _xref_ref(xref: int) -> str:
    return f"{xref} 0 R"


def _is_pages_node(doc, xref: int) -> bool:
    return doc.xref_get_key(xref, "Type") == ("name", "/Pages")


def _page_tree_leaf_count(doc, xref: int) -> int:
    if _is_pages_node(doc, xref):
        kind, value = doc.xref_get_key(xref, "Count")
        if kind == "int":
            return int(value)
    return 1


def _build_balanced_page_tree(doc, fanout: int = PAGE_TREE_FANOUT) -> bool:
    """Düz /Pages listesini, /Count ile atlanabilen dengeli ağaca çevirir."""
    total = len(doc)
    if total <= fanout:
        return False

    nodes = [doc[i].xref for i in range(total)]
    while len(nodes) > 1:
        level: list[int] = []
        for i in range(0, len(nodes), fanout):
            group = nodes[i : i + fanout]
            if len(group) == 1:
                level.append(group[0])
                continue
            count = sum(_page_tree_leaf_count(doc, xref) for xref in group)
            new_xref = doc.get_new_xref()
            kids = " ".join(_xref_ref(xref) for xref in group)
            doc.update_object(
                new_xref,
                f"<< /Type /Pages /Kids [{kids}] /Count {count} >>",
            )
            parent_ref = _xref_ref(new_xref)
            for xref in group:
                doc.xref_set_key(xref, "Parent", parent_ref)
            level.append(new_xref)
        if level == nodes:
            break
        nodes = level

    doc.xref_set_key(doc.pdf_catalog(), "Pages", _xref_ref(nodes[0]))
    return True
