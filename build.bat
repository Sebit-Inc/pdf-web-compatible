@echo off
chcp 65001 > nul
echo.
echo ========================================
echo  PDF Web Donusturucu — Build Script
echo ========================================
echo.

:: Python kontrolü
python --version 2>nul
if errorlevel 1 (
    echo [HATA] Python bulunamadi! Lutfen Python 3.10+ yukleyin.
    pause
    exit /b 1
)

:: Bağımlılıkları kur
echo [1/3] Bagimliliklar kontrol ediliyor...
python -m pip install pymupdf customtkinter tkinterdnd2 pyinstaller --only-binary pymupdf -q
if errorlevel 1 (
    echo [HATA] Bagimliliklar yuklenemedi.
    pause
    exit /b 1
)

:: dist klasörünü temizle
echo [2/3] Eski build temizleniyor...
if exist dist\PDF-Web-Donusturucu.exe del /f dist\PDF-Web-Donusturucu.exe

:: PyInstaller ile derle
echo [3/3] Uygulama derleniyor... (1-3 dakika surebilir)
python -m PyInstaller pdf_converter.spec --clean --noconfirm

if errorlevel 1 (
    echo.
    echo [HATA] Derleme basarisiz!
    pause
    exit /b 1
)

echo.
echo ========================================
echo  BASARILI! Cikti: dist\PDF-Web-Donusturucu.exe
echo ========================================
echo.
pause
