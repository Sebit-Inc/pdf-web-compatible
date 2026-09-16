"""
PDF Vektör → Bitmap Dönüştürücü
Eğitsel tasarımcılar için web uyumlu PDF hazırlama aracı.
"""

import io
import os
import re
import sys
import shutil
import hashlib
import threading
import queue
import multiprocessing as mp
from dataclasses import dataclass, asdict
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

# Düz /Kids listesi yerine /Count ile atlanabilen dengeli ağaç.
PAGE_TREE_FANOUT = 8

# ─── Hızlı Açılış Ölçütleri ───────────────────────────────────────────────────
# İlk sayfadan erişilebilen nesne kümesi dosyanın bu oranını geçiyorsa, pdf.js
# ilk sayfayı göstermek için neredeyse tüm dosyayı indirmek zorunda kalır.
FIRST_PAGE_CLOSURE_LIMIT = 0.4

# Sayfa /Resources'ında bildirilen girdi sayısı, gerçekten kullanılanın bu
# katından fazlaysa sözlük şişmesi vardır (Online2PDF çıktılarında ~sayfa sayısı).
UNUSED_RESOURCE_FACTOR = 4
MIN_DECLARED_RESOURCES = 16

# Linearize sonrası /E (ilk sayfa bölümü) /L'nin bu oranını geçerse onarım yetmemiştir.
LINEARIZED_FIRST_PAGE_LIMIT = 0.5

# Budamanın görüntüyü bozmadığı, örnek sayfaların render hash'i ile doğrulanır.
RENDER_CHECK_SAMPLES = 5
RENDER_CHECK_DPI = 72

# İçerik operatörü → adını çözdüğü kaynak kategorisi. Yalnızca bu üç kategori
# budanır; /ColorSpace, /Pattern, /Shading, /ProcSet aynen bırakılır.
_RESOURCE_CATEGORIES = {
    "Do": "/XObject",
    "Tf": "/Font",
    "gs": "/ExtGState",
}

# Dönüştürme modları
MODE_AUTO = "auto"
MODE_LOSSLESS = "lossless"
MODE_SELECTIVE = "selective"
MODE_RASTER_ALL = "raster_all"

MODE_LABELS = {
    MODE_AUTO: "Otomatik (önerilen)",
    MODE_LOSSLESS: "Kayıpsız onarım",
    MODE_SELECTIVE: "Seçici bitmap",
    MODE_RASTER_ALL: "Tüm sayfalar bitmap",
}
MODE_OPTIONS = [MODE_AUTO, MODE_LOSSLESS, MODE_SELECTIVE, MODE_RASTER_ALL]

# Mod menüsünün yanındaki ipucu ve "Mod rehberi" penceresi bu metinleri kullanır.
MODE_HINTS = {
    MODE_AUTO: (
        "Dosya ölçülür, gereken onarımlar kendiliğinden uygulanır: kullanılmayan "
        "sayfa kaynaklarını ayıklama, dengeli sayfa ağacı, linearize ve gerekiyorsa "
        "vektör ağır sayfaları bitmap'e çevirme.",
        "Neredeyse her dosyada bunu kullanın.",
    ),
    MODE_LOSSLESS: (
        "Hiçbir sayfa bitmap'e çevrilmez. Yalnızca dosyanın iç yapısı onarılır; "
        "metin seçilebilir kalır, görüntü ve boyut değişmez.",
        "Görüntüye kesinlikle dokunulmasın istediğinizde kullanın.",
    ),
    MODE_SELECTIVE: (
        "Yalnızca 10.000'den fazla vektör işlemi içeren sayfalar bitmap'e çevrilir; "
        "diğer sayfalar olduğu gibi kalır.",
        "Akıllı tahtada tek tek sayfalar takılıp kalıyorsa kullanın.",
    ),
    MODE_RASTER_ALL: (
        "Her sayfa görüntüye çevrilir. Metin artık seçilemez ve dosya birkaç kat "
        "büyüyebilir.",
        "Yalnızca diğer modlar yetmediyse veya uygulama satırda önerdiyse kullanın.",
    ),
}

# Satırdaki teşhis etiketlerinin ne anlama geldiği
DIAGNOSIS_HINTS = {
    "bloat": (
        "Sayfa kaynak sözlüğü şişkin: sayfa kullanmadığı içerikleri de bildiriyor, "
        "bu yüzden tarayıcı ilk sayfa için dosyanın neredeyse tamamını indiriyor. "
        "Kayıpsız onarılır; boyut, metin ve görüntü değişmez."
    ),
    "shared": (
        "İlk sayfa için inen veri çok büyük ve içerik gerçekten sayfalar arasında "
        "paylaşılıyor. Kayıpsız onarım yetmezse 'Tüm sayfalar bitmap' modu gerekir."
    ),
    "heavy": (
        "Bazı sayfalarda 10.000'den fazla vektör işlemi var; bu sayfalar tarayıcıda "
        "yavaş çizilir ve bitmap'e çevrilir. Diğer sayfalar korunur."
    ),
    "tree": (
        "İlk sayfa indirmesi sorunlu değil; sayfa ağacı dengelenecek ve dosya "
        "linearize edilecek (Fast Web View)."
    ),
    "ok": "Bu dosya web'de zaten hızlı açılıyor; dönüştürmek şart değil.",
    "unknown": "Dosyanın yapısı ölçülemedi. Dönüştürme yine denenebilir.",
}

# Raster kalite profilleri. "recommended" render çözünürlüğünü kaynağın kendi
# görsel çözünürlüğüyle sınırlar: kaynakta olmayan detay için byte harcamaz.
QUALITY_RECOMMENDED = "recommended"
RASTER_MIN_DPI = 150
RASTER_PROFILES = {
    QUALITY_RECOMMENDED: {
        "label": "Önerilen (kaynak kalitesi)",
        "quality": 85,
        "subsampling": 0,
        "source_aware": True,
    },
    "high": {
        "label": "Yüksek",
        "quality": 92,
        "subsampling": 0,
        "source_aware": False,
    },
    "balanced": {
        "label": "Dengeli",
        "quality": 75,
        "subsampling": 2,
        "source_aware": False,
    },
}

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


# ─── İlk Sayfa Erişim Grafiği: Ölçüm, Budama, Doğrulama ───────────────────────

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


def _prune_page_resources(pdf, result_queue=None) -> dict:
    """
    Sayfa /Resources sözlüklerini içerikte gerçekten kullanılan girdilere indirger.

    Ayıklanan nesneler dosyadan silinmez (her biri kendi sayfası tarafından
    kullanılır); yalnızca ilk sayfadan erişilebilen küme küçülür. Bu sayede
    linearize edilen dosyada /E, dosya boyutunun tamamı olmaktan çıkar.
    """
    from pikepdf import Dictionary

    total = len(pdf.pages)
    stats = {"pages": 0, "removed": 0, "skipped": 0}
    if result_queue is not None:
        _progress(result_queue, 0, max(total, 1), "Budama")

    for index, page in enumerate(pdf.pages):
        usage = _page_resource_usage(page)
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


def _diagnose_process(path: str, result_queue: mp.Queue) -> None:
    """Teşhisi ayrı süreçte çalıştırır; nesne grafiği gezintisi UI'yi bloklamaz."""
    try:
        result_queue.put(("diagnosis", asdict(_diagnose_pdf(path))))
    except Exception as exc:
        result_queue.put(("diagnosis_error", str(exc)[:200]))


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


def _progress(result_queue, current: int, total: int, phase: str) -> None:
    result_queue.put(("progress", current, total, phase))


# ─── Süreç Düzeyinde Worker (GIL'den bağımsız) ────────────────────────────────

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
                _rasterize_into_page(fitz, doc_in[index], doc_out[index], dpi, quality)
                _progress(result_queue, index + 1, total, "Sayfa")
        else:
            index = 0
            while index < total:
                if is_heavy[index]:
                    _rasterize_page_to_doc(fitz, doc_in[index], doc_out, dpi, quality)
                    _progress(result_queue, index + 1, total, "Sayfa")
                    index += 1
                else:
                    end = index + 1
                    while end < total and not is_heavy[end]:
                        end += 1
                    doc_out.insert_pdf(doc_in, from_page=index, to_page=end - 1)
                    for page_index in range(index, end):
                        _progress(result_queue, page_index + 1, total, "Sayfa")
                    index = end

        _copy_document_extras(doc_in, doc_out)
        _progress(result_queue, total, total, "Kayıt")
        doc_out.save(output_path, garbage=4, deflate=True, deflate_images=True)
    finally:
        doc_out.close()
        doc_in.close()


def _tree_note(result: dict) -> str:
    note = f"balanced fanout={PAGE_TREE_FANOUT}" if result["tree"] else "flat"
    return f"{note}, linearized={'yes' if result['linearized'] else 'no'}"


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
        analyze_vectors = mode in (MODE_AUTO, MODE_SELECTIVE)
        prune = mode == MODE_LOSSLESS or (
            mode in (MODE_AUTO, MODE_LOSSLESS) and diagnosis.prunable
        )

        doc_in = fitz.open(input_path)
        total = len(doc_in)

        is_heavy: list[bool] = []
        bitmap_pages: list[int] = []
        mode_label = {
            MODE_RASTER_ALL: "ALL PAGES",
            MODE_LOSSLESS: "LOSSLESS",
        }.get(mode, "SELECTIVE")
        report_lines: list[str] = [
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

        if raster_all:
            _log("Converting all pages to bitmap...")
            report_lines.append("Converting all pages to bitmap...")
            is_heavy = [True] * total
            bitmap_pages = list(range(1, total + 1))
            for i in range(total):
                line = f"Page {i + 1}: ALL -> BITMAP"
                _log(line)
                report_lines.append(line)
        elif analyze_vectors:
            _log("Analyzing PDF...")
            report_lines.append("Analyzing PDF...")
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
        else:
            is_heavy = [False] * total
            report_lines.append("Lossless repair only; no page rasterized.")

        doc_in.close()

        heavy_count = sum(is_heavy)
        preserved_count = total - heavy_count
        bitmap_pages_text = _format_page_numbers(bitmap_pages, limit=None) if bitmap_pages else "-"
        _log(f"\nHeavy vector pages: {heavy_count} / {total}")
        _log(f"Bitmap page numbers: {bitmap_pages_text}")
        report_lines.append("")
        report_lines.append(f"Heavy vector pages: {heavy_count} / {total}")
        report_lines.append(f"Bitmap page numbers: {bitmap_pages_text}")

        tree_note = "flat (copy)"
        prune_stats: Optional[dict] = None
        prune_reverted = False
        needs_rewrite = heavy_count > 0 or total > PAGE_TREE_FANOUT or prune

        if not needs_rewrite:
            shutil.copy2(input_path, output_path)
        elif heavy_count == 0:
            rewrite = _rewrite_tree_and_linearize(
                input_path, output_path, result_queue, total, prune=prune,
            )
            tree_note = _tree_note(rewrite)
            prune_stats = rewrite["prune"]
            prune_reverted = rewrite["prune_reverted"]
        else:
            _write_selective_raster(
                input_path, output_path, is_heavy, dpi, quality, result_queue,
            )
            rewrite = _rewrite_tree_and_linearize(
                output_path, output_path, result_queue, total, prune=prune,
            )
            tree_note = _tree_note(rewrite)
            prune_stats = rewrite["prune"]
            prune_reverted = rewrite["prune_reverted"]

        # Doğrulama: linearized başlıktaki /E ilk sayfa için inen byte sayısıdır
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
            summary = f"{total} bitmap (tümü) · {_format_size_mb(final_size)}"
        elif bitmap_pages:
            summary = (
                f"bitmap s. {_format_page_numbers(bitmap_pages)} / "
                f"{preserved_count} vektör · {_format_size_mb(final_size)}"
            )
        else:
            summary = f"0 bitmap / {preserved_count} vektör · {_format_size_mb(final_size)}"
        if first_page_after is not None:
            summary += f" · ilk sayfa {_format_size_mb(first_page_after)}"

        result_queue.put((
            "done", summary, report_text,
            {
                "original_size": original_size,
                "final_size": final_size,
                "first_page_before": diagnosis.first_page_bytes,
                "first_page_after": first_page_after,
                "pruned": None if prune_stats is None else prune_stats["removed"],
                "rasterized": heavy_count,
                "needs_raster": needs_raster,
            },
        ))

    except Exception as e:
        result_queue.put(("error", str(e)[:200]))


# ─── Yardımcı Fonksiyonlar ────────────────────────────────────────────────────

def get_output_path(input_path: str, dpi: int, output_dir: Optional[str] = None) -> str:
    p = Path(input_path)
    out_name = f"{p.stem}-web-{dpi}dpi{p.suffix}"
    if output_dir:
        return str(Path(output_dir) / out_name)
    return str(p.parent / out_name)


# ─── İpucu (Tooltip) ─────────────────────────────────────────────────────────

class Tooltip:
    """
    Fare bir widget'ın üzerinde beklerken küçük açıklama kartı gösterir.

    CustomTkinter widget'ları alt bileşenlerden oluştuğu için olayları hem
    widget'a hem de üzerini kaplayan çocuklarına bağlamak gerekir.
    """

    DELAY_MS = 400

    def __init__(self, widget, text: str, bind_widgets=None, wraplength: int = 340):
        self.widget = widget
        self.text = text
        self.wraplength = wraplength
        self._window = None
        self._after_id = None
        for target in bind_widgets or [widget]:
            try:
                target.bind("<Enter>", self._schedule, add="+")
                target.bind("<Leave>", self._hide, add="+")
                target.bind("<ButtonPress>", self._hide, add="+")
            except Exception:
                pass

    def set_text(self, text: str) -> None:
        self.text = text
        self._hide()

    def _schedule(self, _event=None):
        self._cancel()
        try:
            self._after_id = self.widget.after(self.DELAY_MS, self._show)
        except Exception:
            self._after_id = None

    def _cancel(self):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self):
        self._after_id = None
        if self._window is not None or not self.text:
            return
        try:
            pos_x = self.widget.winfo_rootx() + 10
            pos_y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
            window = tk.Toplevel(self.widget)
        except Exception:
            return
        window.wm_overrideredirect(True)
        window.configure(background=COLORS["border"])
        tk.Label(
            window,
            text=self.text,
            justify="left",
            background=COLORS["card"],
            foreground=COLORS["text"],
            wraplength=self.wraplength,
            padx=12, pady=9,
            font=("Segoe UI", 9),
        ).pack(padx=1, pady=1)
        window.wm_geometry(f"+{pos_x}+{pos_y}")
        try:
            window.attributes("-topmost", True)
        except Exception:
            pass
        self._window = window

    def _hide(self, _event=None):
        self._cancel()
        if self._window is not None:
            try:
                self._window.destroy()
            except Exception:
                pass
            self._window = None


def _mode_hint_text(mode: str) -> str:
    description, when = MODE_HINTS.get(mode, ("", ""))
    return f"{MODE_LABELS.get(mode, mode)}\n\n{description}\n\n{when}"


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

    # ── Teşhis ve sonuç göstergeleri ────────────────────────────────────────

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
            self.mode_menu.configure(state="disabled")
            self.configure(border_color=COLORS["accent"])
        elif status == self.STATUS_DONE:
            self.progress.stop()
            self.progress.configure(mode="determinate", progress_color=COLORS["success"])
            self.progress.set(1)
            self.remove_btn.configure(state="normal")
            self.mode_menu.configure(state="normal")
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
            self.configure(border_color=COLORS["error"])
        elif status == self.STATUS_CANCEL:
            self.progress.stop()
            self.progress.configure(mode="determinate", progress_color=COLORS["warning"])
            self.remove_btn.configure(state="normal")
            self.mode_menu.configure(state="normal")
            self.configure(border_color=COLORS["warning_soft"])
        else:
            self.remove_btn.configure(state="normal")
            self.mode_menu.configure(state="normal")
            self.configure(border_color=COLORS["border"])

        if status != self.STATUS_DONE:
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
            if self.detail_label.winfo_ismapped():
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

    def set_page_progress(self, current: int, total: int, phase: str = "Sayfa"):
        """Sayfa bazlı ilerleme: indeterminate'den determinate'e geçer."""
        pct = current / total if total > 0 else 0
        if phase == "Ağaç":
            label = "Ağaç düzenleniyor"
        elif phase == "Teşhis":
            label = "Teşhis ediliyor"
        elif phase == "Kayıt":
            label = "Kayıt"
        else:
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
        self.geometry("1060x760")
        self.minsize(960, 620)
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
        self._quality: str = QUALITY_RECOMMENDED
        self._about_window = None
        self._guide_window = None

        # Teşhis kuyruğu: dosya eklenince yapısal ölçüm ayrı süreçte yapılır
        self._diag_queue: queue.Queue = queue.Queue()
        threading.Thread(target=self._diagnosis_worker, daemon=True).start()

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
        """Mod menüsündeki seçenekleri ve satırdaki teşhis etiketlerini anlatır."""
        if getattr(self, "_guide_window", None) is not None:
            if self._guide_window.winfo_exists():
                self._guide_window.focus()
                self._guide_window.lift()
                return

        win = ctk.CTkToplevel(self)
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

        self._guide_window = win
        win.after(50, win.focus)

    def _show_about(self):
        if self._about_window is not None and self._about_window.winfo_exists():
            self._about_window.focus()
            self._about_window.lift()
            return

        win = ctk.CTkToplevel(self)
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

    # ── Teşhis ──────────────────────────────────────────────────────────────

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
        self.bulk_mode_menu.configure(state="disabled")
        self.convert_btn.configure(
            text="İptal et",
            fg_color=COLORS["error"],
            hover_color="#dc2626",
        )

        # Mod satır menülerinden okunur; her dosya kendi teşhisine göre işlenir
        jobs = [(row, row.selected_mode()) for row in self.file_rows]

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
        total_jobs = len(jobs)
        output_folders: set[str] = set()  # başarıyla dönüştürülen klasörler

        for index, (row, mode) in enumerate(jobs):
            if self.cancel_event.is_set():
                self._msg_queue.put(("status", row, FileRow.STATUS_CANCEL, ""))
                continue

            out_path = get_output_path(row.file_path, dpi, self.output_dir)
            self._msg_queue.put(("status", row, FileRow.STATUS_RUNNING, ""))
            self._msg_queue.put((
                "bulk", f"{index + 1}/{total_jobs} dosya  ·  {done} tamamlandı",
            ))

            # Ayrı süreç başlat
            mp_queue: mp.Queue = mp.Queue()
            process = mp.Process(
                target=_pdf_convert_process,
                args=(row.file_path, out_path, dpi, mp_queue, False, mode, quality),
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
                elif kind == "result":
                    _, row, out_path, stats = msg
                    row.output_path = out_path
                    row.set_result_detail(stats)
                elif kind == "diagnosis":
                    _, row, diagnosis = msg
                    row.set_diagnosis(diagnosis)
                elif kind == "diagnosis_error":
                    _, row, _detail = msg
                    row.set_diagnosis_text("Analiz edilemedi", "unknown")
                elif kind == "bulk":
                    _, text = msg
                    if self.is_converting:
                        self.summary_label.configure(text=text)
                elif kind == "done":
                    _, summary = msg
                    self.is_converting = False
                    self.add_btn.configure(state="normal")
                    self.empty_add_btn.configure(state="normal")
                    self.bulk_mode_menu.configure(state="normal")
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
