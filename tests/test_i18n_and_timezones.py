from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from apple_health_to_oscar.engine import safe_zoneinfo  # noqa: E402
from apple_health_to_oscar.i18n import SYSTEM_LANGUAGE, Translator, available_language_codes, detect_system_language, normalize_language_code  # noqa: E402
from apple_health_to_oscar.timezones import (  # noqa: E402
    SYSTEM_TIMEZONE,
    build_timezone_label,
    detect_system_timezone,
    find_timezone_entry,
    load_timezone_catalog,
    parse_fixed_offset_minutes,
    resolved_timezone_value,
)
from apple_health_to_oscar.version import get_display_version  # noqa: E402


class I18NAndTimezoneTests(unittest.TestCase):
    def test_language_normalization_handles_region_codes(self) -> None:
        self.assertEqual(normalize_language_code("ko-KR"), "ko")
        self.assertEqual(normalize_language_code("en_US"), "en")
        self.assertEqual(normalize_language_code("en-GB"), "en-GB")
        self.assertEqual(normalize_language_code("zh_CN"), "zh-Hans")
        self.assertEqual(normalize_language_code("zh-TW"), "zh-Hant")
        self.assertEqual(normalize_language_code("zh-HK"), "zh-Hant")
        self.assertEqual(normalize_language_code("es-MX"), "es-MX")
        self.assertEqual(normalize_language_code("pt-BR"), "pt-BR")
        self.assertEqual(normalize_language_code("pt-PT"), "pt")
        self.assertEqual(normalize_language_code("no-NO"), "nb")
        self.assertEqual(normalize_language_code("ms-MY"), "ms")

    def test_detect_system_language_prefers_supported_mapping(self) -> None:
        with mock.patch("apple_health_to_oscar.i18n._windows_system_languages", return_value=("zh-TW",)), mock.patch(
            "apple_health_to_oscar.i18n._macos_system_languages", return_value=()
        ), mock.patch("apple_health_to_oscar.i18n._candidate_languages_from_env", return_value=()), mock.patch(
            "apple_health_to_oscar.i18n.locale.getlocale", return_value=(None, None)
        ), mock.patch("apple_health_to_oscar.i18n.locale.getdefaultlocale", return_value=(None, None)):
            self.assertEqual(detect_system_language(), "zh-Hant")

    def test_translator_auto_mode_resolves_system_language(self) -> None:
        with mock.patch("apple_health_to_oscar.i18n.detect_system_language", return_value="ko"):
            translator = Translator(SYSTEM_LANGUAGE)
            self.assertEqual(translator.resolved_language, "ko")
            self.assertEqual(translator.language_code, SYSTEM_LANGUAGE)

    def test_timezones_cover_fixed_offset_range_and_catalog(self) -> None:
        values = {entry.value for entry in load_timezone_catalog()}
        self.assertIn("UTC-14:00", values)
        self.assertIn("UTC+14:00", values)
        self.assertIn("Asia/Seoul", values)
        self.assertEqual(parse_fixed_offset_minutes("UTC-14:00"), -(14 * 60))
        self.assertEqual(parse_fixed_offset_minutes("UTC+05:45"), 345)
        self.assertIsNotNone(safe_zoneinfo("UTC-14:00"))
        self.assertIsNotNone(safe_zoneinfo("UTC+14:00"))

    def test_detect_and_resolve_system_timezone(self) -> None:
        with mock.patch("apple_health_to_oscar.timezones._windows_system_timezone_candidates", return_value=("Korea Standard Time",)), mock.patch(
            "apple_health_to_oscar.timezones._macos_system_timezone_candidates", return_value=()
        ), mock.patch("apple_health_to_oscar.timezones._linux_system_timezone_candidates", return_value=()):
            self.assertEqual(detect_system_timezone(), "Asia/Seoul")
            self.assertEqual(resolved_timezone_value(SYSTEM_TIMEZONE, fallback="Asia/Seoul"), "Asia/Seoul")

    def test_fixed_offset_label_includes_representative_region(self) -> None:
        entry = find_timezone_entry("UTC+09:30")
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertIn("GMT+09:30", build_timezone_label(entry))
        self.assertTrue(any(name in build_timezone_label(entry) for name in ("Darwin", "Adelaide")))

    def test_additional_language_codes_are_registered(self) -> None:
        supported = set(available_language_codes())
        for code in {"af", "ar", "bg", "en-GB", "es-MX", "el", "he", "nl", "nb", "pl", "pt-BR", "ro", "fi", "sv", "tr", "th", "vi", "da", "cs", "uk", "ms"}:
            self.assertIn(code, supported)

    def test_display_version_uses_project_version(self) -> None:
        self.assertRegex(get_display_version(), r"\d+\.\d+\.\d+")


if __name__ == "__main__":
    unittest.main()
