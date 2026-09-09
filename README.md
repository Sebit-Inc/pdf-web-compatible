# PDF Web Dönüştürücü

Vektör-yoğun PDF'leri web uyumlu bitmap formatına çeviren masaüstü uygulaması.

## Ne İşe Yarar?

Web platformumuz, çok fazla vektörel çizim içeren PDF'leri bazı bilgisayarlarda yavaş render ettiğinden reddedebilmektedir. Bu araç, bu tür PDF'leri her sayfayı bitmap görüntüsüne çevirerek web ortamında hızlı yüklenen bir formata dönüştürür.

## Kullanım

1. `PDF-Web-Donusturucu.exe` dosyasını çalıştırın
2. PDF dosyalarını sürükleyip bırakın **veya** "Dosya Ekle" butonuna tıklayın
3. İsteğe bağlı: DPI kalitesini seçin (varsayılan 300 önerilir)
4. **Dönüştür** butonuna tıklayın
5. Dönüştürülen dosya, orijinalin yanına `dosya-web.pdf` adıyla kaydedilir

## DPI Seçenekleri

| DPI | Ne zaman kullanılır? |
|-----|---------------------|
| 150 | Dosya boyutu öncelikliyse, metin ağırlıklı PDF'ler |
| 300 | **Önerilen** — kalite ve boyut dengesi |
| 600 | Baskı kalitesi detay gerektiriyorsa |

## Kurulum Gerektirmez

`.exe` dosyası tüm bağımlılıklarını içinde taşır. Herhangi bir kurulum ya da ek yazılım gerekmez.

---

## Geliştirici Notları

### Gereksinimler
- Python 3.10+
- Bağımlılıklar: `requirements.txt`

### Çalıştırma (kaynak koddan)
```bash
python -m pip install -r requirements.txt
python app.py
```

### .exe Oluşturma
```bash
build.bat
```
veya
```bash
python -m PyInstaller pdf_converter.spec --clean --noconfirm
```

Çıktı: `dist/PDF-Web-Donusturucu.exe`

### Nasıl Çalışır?
1. Her PDF sayfası seçilen DPI'da piksel görüntüsüne render edilir (PyMuPDF)
2. Görüntüler ZIP (Deflate) sıkıştırma ile yeni bir PDF'e yerleştirilir
3. Sonuç PDF'i web tarayıcılarında hızlıca render edilir

Bu işlem orijinal `magick -density 300 -compress Zip` komutunun Python eşdeğeridir.
