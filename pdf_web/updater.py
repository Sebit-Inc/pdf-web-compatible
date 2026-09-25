"""GitHub Releases üzerinden sürüm kontrolü ve Windows self-replace."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

from pdf_web.config import UPDATE_EXE_NAME, UPDATE_FEED_URL

USER_AGENT = "PDF-Web-Donusturucu"
REQUEST_TIMEOUT = 15
DOWNLOAD_TIMEOUT = 180
CHUNK_SIZE = 64 * 1024


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    notes: str
    url: str
    sha256: str


def format_app_version(version: str) -> str:
    value = (version or "").strip()
    if not value:
        return "v0.0.0"
    return value if value.lower().startswith("v") else f"v{value}"


def parse_version(value: str) -> tuple[int, int, int]:
    cleaned = (value or "").strip().lstrip("vV")
    parts: list[int] = []
    for token in cleaned.split("."):
        digits = ""
        for char in token:
            if char.isdigit():
                digits += char
            else:
                break
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]


def is_newer(remote: str, current: str) -> bool:
    return parse_version(remote) > parse_version(current)


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def current_exe_path() -> Optional[Path]:
    if not is_frozen():
        return None
    return Path(sys.executable).resolve()


def _require_https(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Güncelleme adresi yalnızca HTTPS olabilir.")
    return url


def _open_url(url: str, timeout: int):
    request = urllib.request.Request(
        _require_https(url),
        headers={"User-Agent": USER_AGENT, "Accept": "application/octet-stream,*/*"},
    )
    return urllib.request.urlopen(request, timeout=timeout)


def fetch_update_feed(feed_url: str | None = None) -> dict:
    url = feed_url or UPDATE_FEED_URL
    with _open_url(url, REQUEST_TIMEOUT) as response:
        raw = response.read()
    payload = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("Sürüm bilgisi geçersiz.")
    return payload


def parse_update_info(payload: dict) -> Optional[UpdateInfo]:
    version = str(payload.get("version") or "").strip()
    url = str(payload.get("url") or "").strip()
    sha256 = str(payload.get("sha256") or "").strip().lower()
    notes = str(payload.get("notes") or "").strip()
    if not version or not url or not sha256 or len(sha256) != 64:
        return None
    try:
        _require_https(url)
    except ValueError:
        return None
    return UpdateInfo(version=version, notes=notes, url=url, sha256=sha256)


def check_for_update(current: str, feed_url: str | None = None) -> Optional[UpdateInfo]:
    info = parse_update_info(fetch_update_feed(feed_url))
    if info is None or not is_newer(info.version, current):
        return None
    return info


def download(
    url: str,
    dest: Path,
    sha256: str,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> Path:
    expected = sha256.strip().lower()
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    hasher = hashlib.sha256()
    downloaded = 0
    tmp_path = dest.with_suffix(dest.suffix + ".part")

    try:
        with _open_url(url, DOWNLOAD_TIMEOUT) as response:
            total = int(response.headers.get("Content-Length") or 0)
            with tmp_path.open("wb") as handle:
                while True:
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    handle.write(chunk)
                    hasher.update(chunk)
                    downloaded += len(chunk)
                    if progress_cb is not None:
                        progress_cb(downloaded, total)
        digest = hasher.hexdigest()
        if digest != expected:
            raise ValueError("İndirilen dosyanın imzası eşleşmedi.")
        tmp_path.replace(dest)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise
    return dest


def download_dir_for(version: str) -> Path:
    safe = parse_version(version)
    name = f"{Path(UPDATE_EXE_NAME).stem}-{safe[0]}.{safe[1]}.{safe[2]}.exe"
    return Path(tempfile.gettempdir()) / name


def updater_script() -> str:
    """Yollar bat içine yazılmaz; Türkçe klasör adları ASCII encode hatası vermesin."""
    return (
        "@echo off\r\n"
        "setlocal EnableExtensions\r\n"
        "set \"PID=%~1\"\r\n"
        "set \"SRC=%~2\"\r\n"
        "set \"DST=%~3\"\r\n"
        "set /a n=0\r\n"
        ":wait\r\n"
        ">nul 2>&1 ping 127.0.0.1 -n 2\r\n"
        "tasklist /FI \"PID eq %PID%\" /NH | findstr /I /C:\" %PID% \" >nul\r\n"
        "if %errorlevel%==0 goto wait\r\n"
        ":retry\r\n"
        "copy /y \"%SRC%\" \"%DST%\" >nul\r\n"
        "if not errorlevel 1 goto done\r\n"
        "set /a n+=1\r\n"
        "if %n% geq 30 goto done\r\n"
        ">nul 2>&1 ping 127.0.0.1 -n 2\r\n"
        "goto retry\r\n"
        ":done\r\n"
        "start \"\" \"%DST%\"\r\n"
        "del /f /q \"%SRC%\" >nul 2>&1\r\n"
        "del /f /q \"%~f0\" >nul 2>&1\r\n"
    )


def apply_and_restart(new_exe: Path) -> None:
    current = current_exe_path()
    if current is None:
        raise RuntimeError("Güncelleme yalnızca paketlenmiş uygulamada uygulanır.")
    if os.name != "nt":
        raise RuntimeError("Otomatik güncelleme yalnızca Windows'ta desteklenir.")

    source = Path(new_exe).resolve()
    if not source.exists():
        raise FileNotFoundError("İndirilen güncelleme bulunamadı.")

    script_path = Path(tempfile.gettempdir()) / "pdf-web-donusturucu-update.bat"
    script_path.write_text(updater_script(), encoding="ascii")

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        [
            "cmd.exe",
            "/c",
            str(script_path),
            str(os.getpid()),
            str(source),
            str(current),
        ],
        creationflags=creationflags,
        close_fds=True,
    )
