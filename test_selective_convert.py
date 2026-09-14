"""
Secici rasterize pipeline testleri.
"""

import os
import re
import tempfile
import unittest
import multiprocessing as mp
from pathlib import Path

import pymupdf as fitz

from app import (
    VECTOR_OPERATION_THRESHOLD,
    PAGE_TREE_FANOUT,
    count_vector_operations,
    get_output_path,
    _pdf_convert_process,
    _format_size_mb,
    _build_balanced_page_tree,
)


def _drain_queue(result_queue: mp.Queue) -> list:
    messages = []
    idle = 0
    while idle < 20:
        try:
            messages.append(result_queue.get(timeout=0.05))
            idle = 0
            if messages[-1][0] in ("done", "error"):
                break
        except Exception:
            idle += 1
    return messages


def _add_stroke_ops(doc: fitz.Document, page: fitz.Page, count: int) -> None:
    """Sayfaya ham PDF stroke operator'lari ekler."""
    page.insert_text((12, 16), "seed")
    xref = page.get_contents()[0]
    existing = doc.xref_stream(xref)
    strokes = "\n".join(
        f"10 {20 + (i % 500)} m 80 {20 + (i % 500)} l S" for i in range(count)
    )
    doc.update_stream(xref, existing + b"\n" + strokes.encode())


class VectorCountTests(unittest.TestCase):
    def test_threshold_is_central_10000(self):
        self.assertEqual(VECTOR_OPERATION_THRESHOLD, 10000)

    def test_text_page_is_not_vector(self):
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Hello searchable text")
        self.assertEqual(count_vector_operations(page), 0)
        doc.close()

    def test_image_page_is_not_vector(self):
        doc = fitz.open()
        page = doc.new_page()
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 32, 32), False)
        pix.clear_with(160)
        page.insert_image(page.rect, pixmap=pix)
        self.assertEqual(count_vector_operations(page), 0)
        doc.close()

    def test_fill_stroke_path_is_counted(self):
        doc = fitz.open()
        page = doc.new_page()
        shape = page.new_shape()
        shape.draw_rect(fitz.Rect(40, 40, 180, 120))
        shape.finish(color=(0, 0, 0), fill=(1, 0, 0), closePath=True)
        shape.commit()
        count = count_vector_operations(page)
        self.assertGreaterEqual(count, 1)
        self.assertLess(count, VECTOR_OPERATION_THRESHOLD)
        doc.close()

    def test_stroke_ops_are_counted_exactly(self):
        doc = fitz.open()
        page = doc.new_page()
        _add_stroke_ops(doc, page, 250)
        self.assertEqual(count_vector_operations(page), 250)
        doc.close()


class OutputPathTests(unittest.TestCase):
    def test_default_output_name(self):
        path = get_output_path(r"C:\docs\ders.pdf", 300)
        self.assertTrue(path.endswith("ders-web-300dpi.pdf"))

    def test_custom_output_dir(self):
        path = get_output_path(r"C:\docs\ders.pdf", 150, r"D:\out")
        self.assertEqual(path, r"D:\out\ders-web-150dpi.pdf")

    def test_format_size_mb(self):
        self.assertEqual(_format_size_mb(1024 * 1024), "1.0 MB")


class SelectiveConvertTests(unittest.TestCase):
    def test_mixed_pages_preserve_original_and_rasterize_heavy(self):
        with tempfile.TemporaryDirectory(prefix="pdfvec_") as tmpdir:
            src = os.path.join(tmpdir, "mixed.pdf")
            dst = os.path.join(tmpdir, "mixed-out.pdf")

            doc = fitz.open()
            doc.set_metadata({"title": "Mixed Test", "author": "Unit Test"})

            page1 = doc.new_page(width=595, height=842)
            page1.insert_text((72, 80), "Page 1 original text")

            page2 = doc.new_page(width=842, height=595)
            _add_stroke_ops(doc, page2, VECTOR_OPERATION_THRESHOLD + 2000)

            page3 = doc.new_page(width=595, height=842)
            page3.insert_text((72, 80), "Page 3 unique searchable text")

            doc.set_toc([[1, "Intro", 1], [1, "Heavy", 2], [1, "End", 3]])
            doc.save(src)
            doc.close()

            queue = mp.Queue()
            _pdf_convert_process(src, dst, 150, queue)
            messages = _drain_queue(queue)

            kinds = [msg[0] for msg in messages]
            self.assertIn("done", kinds)
            self.assertNotIn("error", kinds)
            done_msg = [msg for msg in messages if msg[0] == "done"][0]
            self.assertIn("bitmap s. 2", done_msg[1])
            self.assertIn("2 vektör", done_msg[1])
            self.assertGreaterEqual(len(done_msg), 3)
            report = done_msg[2]
            self.assertIn("Page 2: 12,000 vector operations -> BITMAP", report)
            self.assertIn("Page 1: 0 vector operations -> ORIGINAL", report)
            self.assertIn("Page 3: 0 vector operations -> ORIGINAL", report)
            self.assertIn("Bitmap page numbers: 2", report)
            leftover_reports = list(Path(tmpdir).glob("*-report.txt"))
            self.assertEqual(leftover_reports, [])

            out = fitz.open(dst)
            self.assertEqual(len(out), 3)
            self.assertEqual(out.metadata.get("title"), "Mixed Test")

            self.assertEqual(tuple(out[0].rect), (0.0, 0.0, 595.0, 842.0))
            self.assertIn("Page 1 original text", out[0].get_text())
            self.assertEqual(len(out[0].get_images()), 0)

            self.assertEqual(tuple(out[1].rect), (0.0, 0.0, 842.0, 595.0))
            self.assertEqual(len(out[1].get_images()), 1)
            self.assertEqual(count_vector_operations(out[1]), 0)
            self.assertEqual(out[1].get_text().strip(), "")

            self.assertEqual(tuple(out[2].rect), (0.0, 0.0, 595.0, 842.0))
            self.assertIn("Page 3 unique searchable text", out[2].get_text())
            self.assertEqual(len(out[2].get_images()), 0)

            toc = out.get_toc()
            self.assertTrue(any(item[1] == "Intro" for item in toc))
            out.close()

    def test_threshold_boundary_keeps_exact_10000_original(self):
        with tempfile.TemporaryDirectory(prefix="pdfvec_") as tmpdir:
            src = os.path.join(tmpdir, "edge.pdf")
            dst = os.path.join(tmpdir, "edge-out.pdf")

            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((72, 72), "boundary page stays searchable")
            _add_stroke_ops(doc, page, VECTOR_OPERATION_THRESHOLD)
            self.assertEqual(count_vector_operations(page), VECTOR_OPERATION_THRESHOLD)
            doc.save(src)
            doc.close()

            queue = mp.Queue()
            _pdf_convert_process(src, dst, 150, queue)
            messages = _drain_queue(queue)
            self.assertTrue(any(msg[0] == "done" for msg in messages))

            out = fitz.open(dst)
            self.assertIn("boundary page stays searchable", out[0].get_text())
            self.assertEqual(len(out[0].get_images()), 0)
            out.close()

    def test_no_heavy_pages_copies_original_bytes(self):
        with tempfile.TemporaryDirectory(prefix="pdfvec_") as tmpdir:
            src = os.path.join(tmpdir, "light.pdf")
            dst = os.path.join(tmpdir, "light-out.pdf")

            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((72, 72), "only text")
            doc.save(src)
            doc.close()

            queue = mp.Queue()
            _pdf_convert_process(src, dst, 300, queue)
            messages = _drain_queue(queue)
            self.assertTrue(any(msg[0] == "done" for msg in messages))

            with open(src, "rb") as src_file, open(dst, "rb") as dst_file:
                self.assertEqual(src_file.read(), dst_file.read())

    def test_light_multipage_pdf_still_gets_balanced_tree(self):
        with tempfile.TemporaryDirectory(prefix="pdfvec_") as tmpdir:
            src = os.path.join(tmpdir, "light-many.pdf")
            dst = os.path.join(tmpdir, "light-many-out.pdf")
            page_count = PAGE_TREE_FANOUT + 4

            doc = fitz.open()
            for i in range(page_count):
                page = doc.new_page(width=300, height=400)
                page.insert_text((40, 60), f"keep page {i + 1}")
            doc.save(src)
            doc.close()

            queue = mp.Queue()
            _pdf_convert_process(src, dst, 150, queue, False)
            messages = _drain_queue(queue)
            done_msg = [msg for msg in messages if msg[0] == "done"][0]
            self.assertIn("0 bitmap", done_msg[1])
            self.assertIn("Page tree: balanced fanout=8, linearized=yes", done_msg[2])

            out = fitz.open(dst)
            self.assertEqual(len(out), page_count)
            self.assertIn("keep page 1", out[0].get_text())
            self.assertIn(f"keep page {page_count}", out[-1].get_text())
            self.assertEqual(len(out[0].get_images()), 0)
            fetches = _simulate_last_page_fetches(out)
            self.assertLess(len(fetches), page_count)
            out.close()


class ConvertAllTests(unittest.TestCase):
    def test_convert_all_rasterizes_light_pages(self):
        with tempfile.TemporaryDirectory(prefix="pdfvec_") as tmpdir:
            src = os.path.join(tmpdir, "mixed.pdf")
            dst = os.path.join(tmpdir, "mixed-out.pdf")

            doc = fitz.open()
            page1 = doc.new_page(width=595, height=842)
            page1.insert_text((72, 80), "Page 1 original text")
            page2 = doc.new_page(width=842, height=595)
            page2.insert_text((72, 80), "Page 2 also searchable")
            doc.save(src)
            doc.close()

            queue = mp.Queue()
            _pdf_convert_process(src, dst, 150, queue, True)
            messages = _drain_queue(queue)

            kinds = [msg[0] for msg in messages]
            self.assertIn("done", kinds)
            self.assertNotIn("error", kinds)
            done_msg = [msg for msg in messages if msg[0] == "done"][0]
            self.assertIn("2 bitmap (tümü)", done_msg[1])
            report = done_msg[2]
            self.assertIn("Mode: ALL PAGES", report)
            self.assertIn("Page 1: ALL -> BITMAP", report)
            self.assertIn("Page 2: ALL -> BITMAP", report)

            out = fitz.open(dst)
            self.assertEqual(len(out), 2)
            self.assertEqual(len(out[0].get_images()), 1)
            self.assertEqual(len(out[1].get_images()), 1)
            self.assertEqual(out[0].get_text().strip(), "")
            self.assertEqual(out[1].get_text().strip(), "")
            self.assertEqual(count_vector_operations(out[0]), 0)
            out.close()

    def test_convert_all_false_still_preserves_light_pages(self):
        with tempfile.TemporaryDirectory(prefix="pdfvec_") as tmpdir:
            src = os.path.join(tmpdir, "light.pdf")
            dst = os.path.join(tmpdir, "light-out.pdf")

            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((72, 72), "keep me searchable")
            doc.save(src)
            doc.close()

            queue = mp.Queue()
            _pdf_convert_process(src, dst, 150, queue, False)
            messages = _drain_queue(queue)
            self.assertTrue(any(msg[0] == "done" for msg in messages))

            out = fitz.open(dst)
            self.assertIn("keep me searchable", out[0].get_text())
            self.assertEqual(len(out[0].get_images()), 0)
            out.close()


def _parse_kids(doc, xref: int) -> list[int]:
    raw = doc.xref_get_key(xref, "Kids")[1]
    return [int(num) for num in re.findall(r"(\d+) 0 R", raw)]


def _pages_root(doc) -> int:
    return int(doc.xref_get_key(doc.pdf_catalog(), "Pages")[1].split()[0])


def _simulate_last_page_fetches(doc) -> list[int]:
    """pdf.js getPageDict skip-by-Count: son sayfa için çekilen xref'ler."""
    target = len(doc) - 1
    fetched: list[int] = []

    def walk(xref: int, current: int) -> tuple[bool, int]:
        fetched.append(xref)
        keys = set(doc.xref_get_keys(xref))
        is_pages = doc.xref_get_key(xref, "Type") == ("name", "/Pages")
        if is_pages and "Count" in keys:
            count = int(doc.xref_get_key(xref, "Count")[1])
            if current + count <= target:
                return False, current + count
            for kid in _parse_kids(doc, xref):
                found, current = walk(kid, current)
                if found:
                    return True, current
            return False, current
        if current == target:
            return True, current + 1
        return False, current + 1

    walk(_pages_root(doc), 0)
    return fetched


class FastOpenPageTreeTests(unittest.TestCase):
    def test_balanced_tree_lets_check_last_page_skip_branches(self):
        doc = fitz.open()
        for _ in range(20):
            doc.new_page(width=200, height=200)
        self.assertTrue(_build_balanced_page_tree(doc, fanout=8))
        root = _pages_root(doc)
        kids = _parse_kids(doc, root)
        self.assertEqual(len(kids), 3)
        self.assertTrue(all(
            doc.xref_get_key(kid, "Type") == ("name", "/Pages") for kid in kids
        ))
        self.assertEqual(
            [int(doc.xref_get_key(kid, "Count")[1]) for kid in kids],
            [8, 8, 4],
        )
        fetches = _simulate_last_page_fetches(doc)
        self.assertLess(len(fetches), 20)
        self.assertEqual(fetches[0], root)
        doc.close()

    def test_convert_all_writes_balanced_tree_and_keeps_page_dicts_clustered(self):
        with tempfile.TemporaryDirectory(prefix="pdfvec_") as tmpdir:
            src = os.path.join(tmpdir, "many.pdf")
            dst = os.path.join(tmpdir, "many-out.pdf")
            page_count = 20

            doc = fitz.open()
            for i in range(page_count):
                page = doc.new_page(width=300, height=400)
                page.insert_text((40, 60), f"page {i + 1}")
            doc.save(src)
            doc.close()

            queue = mp.Queue()
            _pdf_convert_process(src, dst, 150, queue, True)
            messages = _drain_queue(queue)
            done_msg = [msg for msg in messages if msg[0] == "done"][0]
            self.assertIn("Page tree: balanced fanout=8, linearized=yes", done_msg[2])

            out = fitz.open(dst)
            self.assertEqual(len(out), page_count)
            self.assertTrue(out.is_fast_webaccess)
            root = _pages_root(out)
            kids = _parse_kids(out, root)
            self.assertGreater(len(kids), 1)
            self.assertTrue(all(
                out.xref_get_key(kid, "Type") == ("name", "/Pages") for kid in kids
            ))
            fetches = _simulate_last_page_fetches(out)
            self.assertLess(len(fetches), page_count)
            self.assertEqual(len(out[0].get_images()), 1)
            out.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
