"""
PDF Vektör → Bitmap Dönüştürücü
Eğitsel tasarımcılar için web uyumlu PDF hazırlama aracı.
"""

import multiprocessing as mp

from pdf_web.config import (
    LINEARIZED_FIRST_PAGE_LIMIT,
    MODE_LOSSLESS,
    PAGE_TREE_FANOUT,
    QUALITY_RECOMMENDED,
    RASTER_PROFILES,
    SAVE_GARBAGE,
    VECTOR_OPERATION_THRESHOLD,
)
from pdf_web.engine.analysis import (
    _diagnose_pdf,
    _object_closure,
    _page_resource_usage,
    _read_linearization_params,
    count_vector_operations,
)
from pdf_web.engine.convert import _pdf_convert_process
from pdf_web.engine.raster import _effective_raster_dpi
from pdf_web.engine.repair import _build_balanced_page_tree
from pdf_web.util import _format_size_mb, get_output_path


def __getattr__(name):
    """UI'yi yalnızca gerektiğinde yükle; testler motoru GUI'siz import edebilsin."""
    if name == "PDFConverterApp":
        from pdf_web.ui.window import PDFConverterApp
        return PDFConverterApp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def main():
    # PyInstaller ile paketlenmiş Windows exe için zorunlu
    mp.freeze_support()
    from pdf_web.ui.window import PDFConverterApp
    app = PDFConverterApp()
    app.mainloop()


if __name__ == "__main__":
    main()
