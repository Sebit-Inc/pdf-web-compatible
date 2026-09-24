"""Release asset metadata — CI tarafından latest.json üretmek için."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def main() -> None:
    exe = Path("dist/PDF-Web-Donusturucu.exe")
    digest = hashlib.sha256(exe.read_bytes()).hexdigest()
    tag = os.environ["GITHUB_REF_NAME"]
    repo = os.environ["GITHUB_REPOSITORY"]
    payload = {
        "version": tag.lstrip("vV"),
        "notes": f"PDF Web Dönüştürücü {tag}",
        "url": f"https://github.com/{repo}/releases/download/{tag}/PDF-Web-Donusturucu.exe",
        "sha256": digest,
    }
    dest = Path("dist/latest.json")
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(dest, payload["version"], payload["sha256"])


if __name__ == "__main__":
    main()
