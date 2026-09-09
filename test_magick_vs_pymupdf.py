import subprocess, os, re
import pymupdf as fitz

# ImageMagick ile donusum yap
r = subprocess.run(
    ['magick', '-density', '150', '-compress', 'Zip',
     'test_vec.pdf', 'test_magick_output.pdf'],
    capture_output=True, text=True
)
print("magick stderr:", r.stderr[:200])

if not os.path.exists('test_magick_output.pdf'):
    print("Cikti olusturulamadi")
    exit()

sz = os.path.getsize('test_magick_output.pdf')
print(f'ImageMagick cikti: {sz:,} byte')

with open('test_magick_output.pdf', 'rb') as f:
    raw = f.read()

flat = raw.count(b'FlateDecode')
pred_count = raw.count(b'Predictor')
dct = raw.count(b'DCTDecode')
print(f'FlateDecode: {flat}, Predictor mentions: {pred_count}, DCT: {dct}')

# Predictor degerini bul
preds = re.findall(rb'Predictor\s+(\d+)', raw)
colors = re.findall(rb'Colors\s+(\d+)', raw)
bpc = re.findall(rb'BitsPerComponent\s+(\d+)', raw)
print(f'Predictor values: {preds}')
print(f'Colors: {colors}')
print(f'BitsPerComponent: {bpc}')

# Image stream boyutu
doc = fitz.open('test_magick_output.pdf')
page = doc[0]
imgs = page.get_images()
for xi in imgs:
    img = doc.extract_image(xi[0])
    ext = img['ext']
    isz = len(img['image'])
    cs = img['colorspace']
    print(f'  Image ext={ext} size={isz:,} colorspace={cs}')
doc.close()

# PyMuPDF ciktisiyla karsilastir
doc2 = fitz.open('test_method1_png.pdf')
page2 = doc2[0]
print(f'\nPyMuPDF cikti: {os.path.getsize("test_method1_png.pdf"):,} byte')
for xi in page2.get_images():
    img = doc2.extract_image(xi[0])
    ext = img['ext']
    isz = len(img['image'])
    print(f'  Image ext={ext} size={isz:,}')
doc2.close()
