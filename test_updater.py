"""Güncelleme denetimi ve sürüm karşılaştırma testleri."""

import unittest
from unittest import mock

from pdf_web.updater import (
    check_for_update,
    format_app_version,
    is_newer,
    parse_update_info,
    parse_version,
    updater_script,
)


class VersionTests(unittest.TestCase):
    def test_parse_strips_v_prefix(self):
        self.assertEqual(parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(parse_version("1.0.0"), (1, 0, 0))
        self.assertEqual(parse_version("v1.0"), (1, 0, 0))

    def test_newer_comparison(self):
        self.assertTrue(is_newer("1.0.1", "1.0.0"))
        self.assertTrue(is_newer("v1.1.0", "1.0.9"))
        self.assertFalse(is_newer("1.0.0", "1.0.0"))
        self.assertFalse(is_newer("1.0.0", "1.1.0"))

    def test_format_app_version(self):
        self.assertEqual(format_app_version("1.0.0"), "v1.0.0")
        self.assertEqual(format_app_version("v1.0.0"), "v1.0.0")


class FeedTests(unittest.TestCase):
    def test_parse_rejects_http_url(self):
        self.assertIsNone(parse_update_info({
            "version": "1.1.0",
            "url": "http://example.com/app.exe",
            "sha256": "a" * 64,
        }))

    def test_parse_rejects_short_hash(self):
        self.assertIsNone(parse_update_info({
            "version": "1.1.0",
            "url": "https://example.com/app.exe",
            "sha256": "abcd",
        }))

    def test_check_for_update_returns_newer_only(self):
        payload = {
            "version": "1.1.0",
            "notes": "yeni",
            "url": "https://github.com/Sebit-Inc/pdf-web-compatible/releases/download/v1.1.0/PDF-Web-Donusturucu.exe",
            "sha256": "b" * 64,
        }
        with mock.patch("pdf_web.updater.fetch_update_feed", return_value=payload):
            info = check_for_update("1.0.0")
            self.assertIsNotNone(info)
            self.assertEqual(info.version, "1.1.0")
            self.assertIsNone(check_for_update("1.1.0"))
            self.assertIsNone(check_for_update("1.2.0"))

    def test_updater_script_contains_copy_and_restart(self):
        script = updater_script()
        self.assertIn("%~1", script)
        self.assertIn("%~2", script)
        self.assertIn("%~3", script)
        self.assertIn("copy /y", script)
        self.assertIn("start \"\"", script)
        script.encode("ascii")


if __name__ == "__main__":
    unittest.main()
