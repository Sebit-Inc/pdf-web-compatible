"""Uygulama sabitleri — renkler, eşikler, dönüştürme modları."""

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

APP_VERSION = "1.0.2"
UPDATE_FEED_URL = (
    "https://github.com/Sebit-Inc/pdf-web-compatible/"
    "releases/latest/download/latest.json"
)
UPDATE_EXE_NAME = "PDF-Web-Donusturucu.exe"

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

# PyMuPDF garbage=4 karmaşık PDF24 dosyalarında dakikalarca/hiç bitmeden
# xref tarar. pikepdf zaten dosyayı yeniden yazdığı için 1 yeter.
SAVE_GARBAGE = 1
INSERT_CHUNK = 16
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
