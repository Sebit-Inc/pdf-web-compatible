"""Vektör sayımı, ilk sayfa nesne grafiği ve yapısal teşhis."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional

from pdf_web.config import (
    FIRST_PAGE_CLOSURE_LIMIT,
    MIN_DECLARED_RESOURCES,
    PAGE_TREE_FANOUT,
    UNUSED_RESOURCE_FACTOR,
    VECTOR_OPERATION_THRESHOLD,
    _RESOURCE_CATEGORIES,
    _VECTOR_DRAW_TYPES,
)
from pdf_web.util import _format_size_mb


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


def _sample_indices(total: int, limit: int) -> list[int]:
    """İlk, son ve aradan eşit aralıklı örnek sayfa indeksleri."""
    if total <= 0:
        return []
    if total <= limit:
        return list(range(total))
    step = (total - 1) / (limit - 1)
    indices = sorted({int(round(i * step)) for i in range(limit)})
    return [min(index, total - 1) for index in indices]


def _object_closure(obj) -> tuple[int, int]:
    """
    Bir nesneden erişilebilen tüm nesnelerin toplam ham stream boyutu ve sayısı.
    Linearize edicinin "ilk sayfa bölümü" hesabıyla aynı grafiği gezer;
    /Parent atlanır, yoksa tüm dosya erişilebilir görünür.
    """
    import pikepdf

    seen: set = set()
    total = 0
    stack = [obj]
    while stack:
        current = stack.pop()
        try:
            handle = current.objgen
        except Exception:
            handle = None
        if handle and handle != (0, 0):
            if handle in seen:
                continue
            seen.add(handle)
        if isinstance(current, pikepdf.Stream):
            try:
                total += len(current.read_raw_bytes())
            except Exception:
                pass
        try:
            if isinstance(current, (pikepdf.Dictionary, pikepdf.Stream)):
                for key in current.keys():
                    if key == "/Parent":
                        continue
                    stack.append(current[key])
            elif isinstance(current, pikepdf.Array):
                stack.extend(current)
        except Exception:
            pass
    return total, len(seen)


def _page_resources(page):
    """Sayfanın /Resources sözlüğü; sayfada yoksa /Parent zincirinden miras alınan."""
    node = getattr(page, "obj", page)
    depth = 0
    while node is not None and depth < 32:
        try:
            resources = node.get("/Resources")
        except Exception:
            return None
        if resources is not None:
            return resources
        try:
            node = node.get("/Parent")
        except Exception:
            return None
        depth += 1
    return None


def _collect_resource_names(instructions, used: dict) -> None:
    from pikepdf import Name

    for instruction in instructions:
        category = _RESOURCE_CATEGORIES.get(str(instruction.operator))
        if category is None:
            continue
        for operand in instruction.operands:
            if isinstance(operand, Name):
                used[category].add(str(operand))


def _page_resource_usage(page, max_depth: int = 6) -> Optional[dict]:
    """
    Sayfa içeriğinde gerçekten kullanılan kaynak adları.

    Kendi /Resources'ı olmayan form XObject'ler sayfa kaynaklarını miras alır;
    o formların içeriği de taranır. İçerik parse edilemezse None döner ve
    çağıran taraf sayfaya dokunmaz.
    """
    import pikepdf

    resources = _page_resources(page)
    if resources is None:
        return None
    try:
        instructions = pikepdf.parse_content_stream(page)
    except Exception:
        return None

    used = {category: set() for category in _RESOURCE_CATEGORIES.values()}
    _collect_resource_names(instructions, used)

    try:
        xobjects = resources.get("/XObject")
    except Exception:
        return None
    if xobjects is None:
        return used

    pending = [(name, 0) for name in used["/XObject"]]
    visited: set = set()
    while pending:
        name, depth = pending.pop()
        if depth >= max_depth:
            continue
        try:
            if name not in xobjects.keys():
                continue
            form = xobjects[name]
        except Exception:
            continue
        handle = getattr(form, "objgen", None)
        if handle:
            if handle in visited:
                continue
            visited.add(handle)
        try:
            if form.get("/Subtype") != pikepdf.Name.Form:
                continue
            own = form.get("/Resources")
            own_keys = set(own.keys()) if own is not None else set()
        except Exception:
            continue
        missing = [
            category
            for category in _RESOURCE_CATEGORIES.values()
            if category not in own_keys
        ]
        if not missing:
            continue
        try:
            nested = pikepdf.parse_content_stream(form)
        except Exception:
            # Miras alınan kaynakları göremiyoruz; budama güvenli değil
            return None
        extra = {category: set() for category in _RESOURCE_CATEGORIES.values()}
        _collect_resource_names(nested, extra)
        for category in missing:
            used[category] |= extra[category]
        if "/XObject" in missing:
            pending.extend((child, depth + 1) for child in extra["/XObject"])
    return used


def _read_linearization_params(path: str) -> Optional[tuple[int, int]]:
    """Linearized PDF başlığındaki /E (ilk sayfa bölümünün sonu) ve /L (dosya boyutu)."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(4096)
    except OSError:
        return None
    if b"/Linearized" not in head:
        return None
    end = re.search(rb"/E\s+(\d+)", head)
    length = re.search(rb"/L\s+(\d+)", head)
    if end is None or length is None:
        return None
    return int(end.group(1)), int(length.group(1))


@dataclass
class FastOpenDiagnosis:
    """Bir PDF'in web'de neden yavaş açıldığına dair ölçüm sonucu."""

    path: str = ""
    page_count: int = 0
    file_size: int = 0
    first_page_bytes: int = 0
    first_page_objects: int = 0
    declared_resources: int = 0
    used_resources: int = 0
    sampled_pages: int = 0
    heavy_sample_pages: int = 0
    flat_tree: bool = False
    linearized: bool = False
    error: str = ""

    @property
    def first_page_ratio(self) -> float:
        if self.file_size <= 0:
            return 0.0
        return self.first_page_bytes / self.file_size

    @property
    def bloated_first_page(self) -> bool:
        """İlk sayfa için dosyanın büyük kısmının indirilmesi gerekiyor mu?"""
        return (
            self.page_count > PAGE_TREE_FANOUT
            and self.first_page_ratio >= FIRST_PAGE_CLOSURE_LIMIT
        )

    @property
    def has_unused_resources(self) -> bool:
        return (
            self.declared_resources >= MIN_DECLARED_RESOURCES
            and self.declared_resources
            >= UNUSED_RESOURCE_FACTOR * max(self.used_resources, 1)
        )

    @property
    def prunable(self) -> bool:
        """Kayıpsız kaynak budaması bu dosyada işe yarar mı?"""
        return self.bloated_first_page and self.has_unused_resources

    @property
    def heavy_vector(self) -> bool:
        return self.heavy_sample_pages > 0

    def status(self) -> tuple[str, str]:
        """(durum anahtarı, kullanıcıya gösterilecek metin)"""
        if self.error:
            return "unknown", "Analiz edilemedi"
        if self.prunable:
            return "bloat", (
                f"Şişkin ilk sayfa · {_format_size_mb(self.first_page_bytes)} / "
                f"{_format_size_mb(self.file_size)}"
            )
        if self.bloated_first_page:
            return "shared", (
                f"Paylaşımlı içerik · ilk sayfa {_format_size_mb(self.first_page_bytes)}"
            )
        if self.heavy_vector:
            return "heavy", "Vektör ağır sayfalar var"
        if self.flat_tree or not self.linearized:
            return "tree", "Sayfa ağacı ve linearize onarılacak"
        return "ok", "Zaten hızlı açılıyor"


def _diagnosis_status(diagnosis: dict) -> tuple[str, str]:
    """Süreçten sözlük olarak gelen teşhisi UI etiketine çevirir."""
    try:
        return FastOpenDiagnosis(**diagnosis).status()
    except Exception:
        return "unknown", "Analiz edilemedi"


def _diagnose_pdf(path: str, sample_limit: int = 12) -> FastOpenDiagnosis:
    """
    Yapısal ölçüm: ilk sayfanın nesne kapanışı, kullanılmayan kaynak oranı,
    sayfa ağacı ve linearize durumu, örnek sayfalarda vektör yükü.

    Üretici adına bakmaz; ölçüme bakar, böylece bilinmeyen üreticiler de kapsanır.
    """
    diagnosis = FastOpenDiagnosis(path=path)
    try:
        diagnosis.file_size = os.path.getsize(path)
    except OSError:
        pass

    try:
        import pikepdf
    except ImportError:
        diagnosis.error = "pikepdf bulunamadı"
        return diagnosis

    try:
        with pikepdf.open(path) as pdf:
            diagnosis.page_count = len(pdf.pages)
            diagnosis.linearized = bool(pdf.is_linearized)
            try:
                kids = len(pdf.Root.Pages.Kids)
                diagnosis.flat_tree = (
                    kids == diagnosis.page_count and kids > PAGE_TREE_FANOUT
                )
            except Exception:
                diagnosis.flat_tree = False

            if diagnosis.page_count:
                closure_bytes, closure_objects = _object_closure(pdf.pages[0].obj)
                diagnosis.first_page_bytes = closure_bytes
                diagnosis.first_page_objects = closure_objects

                for index in _sample_indices(diagnosis.page_count, sample_limit):
                    page = pdf.pages[index]
                    usage = _page_resource_usage(page)
                    if usage is None:
                        continue
                    resources = _page_resources(page)
                    if resources is None:
                        continue
                    for category in _RESOURCE_CATEGORIES.values():
                        try:
                            entries = resources.get(category)
                            declared = len(entries.keys()) if entries is not None else 0
                        except Exception:
                            declared = 0
                        diagnosis.declared_resources += declared
                        diagnosis.used_resources += len(usage.get(category, ()))
    except Exception as exc:
        diagnosis.error = str(exc)[:200]
        return diagnosis

    try:
        import pymupdf as fitz

        doc = fitz.open(path)
        try:
            for index in _sample_indices(len(doc), sample_limit):
                diagnosis.sampled_pages += 1
                if count_vector_operations(doc[index]) > VECTOR_OPERATION_THRESHOLD:
                    diagnosis.heavy_sample_pages += 1
        finally:
            doc.close()
    except Exception:
        pass

    return diagnosis
