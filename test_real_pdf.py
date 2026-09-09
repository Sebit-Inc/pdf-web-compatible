"""
Kullanicinin gercek PDF'i uzerinde 3 yontemi karsilastirir.
Kullanim: python test_real_pdf.py "C:/pdf/deneme.pdf"
"""
import sys, os
import pymupdf as fitz
from PIL import Image
import io

if len(sys.argv) < 2:
    print("Kullanim: python test_real_pdf.py <pdf_yolu>")
    sys.exit(1)

pdf_path = sys.argv[1]
dpi = 150

print(f"PDF: {pdf_path}")
print(f"DPI: {dpi}")
print()

doc_in = fitz.open(pdf_path)
total = len(doc_in)
print(f"Sayfa sayisi: {total}")
print()

# --- Yontem 1: Mevcut uygulama (PyMuPDF PNG tobytes) ---
doc1 = fitz.open()
for page in fitz.open(pdf_path):
    mat = fitz.Matrix(dpi/72, dpi/72)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB, alpha=False)
    png_bytes = pix.tobytes('png')  # PyMuPDF'in kendi PNG kodlamasi
    rect = page.rect
    np = doc1.new_page(width=rect.width, height=rect.height)
    np.insert_image(rect, stream=png_bytes)
doc1.save('_cmp_method1.pdf', garbage=4, deflate=True, deflate_images=True)
doc1.close()
sz1 = os.path.getsize('_cmp_method1.pdf')
print(f"[1] Mevcut (PyMuPDF tobytes+deflate): {sz1/1024/1024:.1f} MB")

# --- Yontem 2: Pillow lvl=9 PNG ---
doc2 = fitz.open()
for page in fitz.open(pdf_path):
    mat = fitz.Matrix(dpi/72, dpi/72)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB, alpha=False)
    img_pil = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
    buf = io.BytesIO()
    img_pil.save(buf, format='PNG', compress_level=9, optimize=True)
    png_bytes = buf.getvalue()
    rect = page.rect
    np = doc2.new_page(width=rect.width, height=rect.height)
    np.insert_image(rect, stream=png_bytes)
doc2.save('_cmp_method2.pdf', garbage=4, deflate=True, deflate_images=True)
doc2.close()
sz2 = os.path.getsize('_cmp_method2.pdf')
print(f"[2] Pillow PNG lvl=9+deflate:         {sz2/1024/1024:.1f} MB")

# --- Yontem 3: Direct pixmap (no PNG intermediate) ---
doc3 = fitz.open()
for page in fitz.open(pdf_path):
    mat = fitz.Matrix(dpi/72, dpi/72)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB, alpha=False)
    rect = page.rect
    np = doc3.new_page(width=rect.width, height=rect.height)
    np.insert_image(rect, pixmap=pix)  # Direkt pixmap
doc3.save('_cmp_method3.pdf', garbage=4, deflate=True, deflate_images=True)
doc3.close()
sz3 = os.path.getsize('_cmp_method3.pdf')
print(f"[3] Direct pixmap+deflate:             {sz3/1024/1024:.1f} MB")

print()
print(f"Referans (ImageMagick tahmini fark): ~%15-20 kucuk olur")
ref = min(sz1, sz2, sz3)
print(f"En kucuk: {ref/1024/1024:.1f} MB")
