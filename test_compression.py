import pymupdf as fitz
from PIL import Image
import io, os, subprocess

doc_in = fitz.open('test_vec.pdf')
page = doc_in[0]
mat = fitz.Matrix(150/72, 150/72)  # 150 DPI (magick ile ayni)
pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB, alpha=False)
page_rect = page.rect  # kapatılmadan once kaydet
doc_in.close()

img_pil = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)

print(f"Goruntu boyutu: {pix.width}x{pix.height} px")
print(f"Ham piksel: {len(pix.samples):,} byte")
print()

# Tum Pillow compress level'lari dene
for lvl in range(10):
    buf = io.BytesIO()
    img_pil.save(buf, format='PNG', compress_level=lvl, optimize=(lvl==9))
    png_bytes = buf.getvalue()
    
    doc = fitz.open()
    p = doc.new_page(width=page_rect.width, height=page_rect.height)
    p.insert_image(page_rect, stream=png_bytes)
    doc.save('_tmp_lvl.pdf', garbage=4, deflate=True, deflate_images=True)
    doc.close()
    pdf_sz = os.path.getsize('_tmp_lvl.pdf')
    print(f"compress_level={lvl}: PNG={len(png_bytes):7,}  PDF={pdf_sz:7,} byte")

print()
print(f"ImageMagick PDF: 33,276 byte  (referans)")
print(f"PyMuPDF PNG (mevcut): 81,565 byte")
