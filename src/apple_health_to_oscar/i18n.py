from __future__ import annotations

import json
import locale
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Dict, Iterable, Optional

from .app_paths import resource_path

FALLBACK_LANGUAGE = "en"
SYSTEM_LANGUAGE = "auto"


@dataclass(frozen=True)
class LanguageInfo:
    code: str
    autonym: str


SUPPORTED_LANGUAGES: Dict[str, LanguageInfo] = {
    "en": LanguageInfo("en", "English"),
    "en-GB": LanguageInfo("en-GB", "English (UK)"),
    "ko": LanguageInfo("ko", "한국어"),
    "ja": LanguageInfo("ja", "日本語"),
    "de": LanguageInfo("de", "Deutsch"),
    "fr": LanguageInfo("fr", "Français"),
    "it": LanguageInfo("it", "Italiano"),
    "es": LanguageInfo("es", "Español"),
    "es-MX": LanguageInfo("es-MX", "Español (México)"),
    "pt": LanguageInfo("pt", "Português"),
    "pt-BR": LanguageInfo("pt-BR", "Português (Brasil)"),
    "hi": LanguageInfo("hi", "हिन्दी"),
    "ru": LanguageInfo("ru", "Русский"),
    "uk": LanguageInfo("uk", "Українська"),
    "zh-Hans": LanguageInfo("zh-Hans", "简体中文"),
    "zh-Hant": LanguageInfo("zh-Hant", "繁體中文"),
    "id": LanguageInfo("id", "Bahasa Indonesia"),
    "ms": LanguageInfo("ms", "Bahasa Melayu"),
    "af": LanguageInfo("af", "Afrikaans"),
    "ar": LanguageInfo("ar", "العربية"),
    "bg": LanguageInfo("bg", "Български"),
    "el": LanguageInfo("el", "Ελληνικά"),
    "he": LanguageInfo("he", "עברית"),
    "nl": LanguageInfo("nl", "Nederlands"),
    "nb": LanguageInfo("nb", "Norsk Bokmål"),
    "pl": LanguageInfo("pl", "Polski"),
    "ro": LanguageInfo("ro", "Română"),
    "fi": LanguageInfo("fi", "Suomi"),
    "sv": LanguageInfo("sv", "Svenska"),
    "tr": LanguageInfo("tr", "Türkçe"),
    "th": LanguageInfo("th", "ไทย"),
    "vi": LanguageInfo("vi", "Tiếng Việt"),
    "da": LanguageInfo("da", "Dansk"),
    "cs": LanguageInfo("cs", "Čeština"),
}



_WINDOWS_LOCALE_OVERRIDES = {
    "0x0411": "ja-JP",
    "0x0412": "ko-KR",
    "0x0409": "en-US",
    "0x0809": "en-GB",
    "0x0804": "zh-CN",
    "0x0404": "zh-TW",
    "0x0c04": "zh-HK",
    "0x0416": "pt-BR",
    "0x0816": "pt-PT",
    "0x0421": "id-ID",
    "0x080c": "fr-BE",
    "0x0422": "uk-UA",
    "0x041f": "tr-TR",
    "0x041e": "th-TH",
    "0x042a": "vi-VN",
    "0x041d": "sv-SE",
    "0x0406": "da-DK",
    "0x0405": "cs-CZ",
    "0x0404": "zh-TW",
}


def _read_locale(code: str) -> Dict[str, str]:
    path = resource_path("locales", f"{code}.json")
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    return {str(key): str(value) for key, value in data.items()}


def normalize_language_code(code: Optional[str]) -> str:
    if not code:
        return FALLBACK_LANGUAGE

    raw = str(code).replace("_", "-").strip()
    lower = raw.casefold()

    if lower in {"auto", "system"}:
        return SYSTEM_LANGUAGE

    if lower.startswith("zh-cn") or lower.startswith("zh-sg") or lower == "zh-hans":
        return "zh-Hans"
    if lower.startswith("zh-tw") or lower.startswith("zh-hk") or lower.startswith("zh-mo") or lower == "zh-hant":
        return "zh-Hant"
    if lower in {"zh", "zh-chs"}:
        return "zh-Hans"
    if lower == "zh-cht":
        return "zh-Hant"

    if lower in {"en-gb", "en-uk"}:
        return "en-GB"
    if lower.startswith("es-mx"):
        return "es-MX"
    if lower.startswith("pt-br"):
        return "pt-BR"
    if lower.startswith("pt-pt") or lower == "pt":
        return "pt"
    if lower in {"no", "no-no", "nb", "nb-no", "nn", "nn-no"}:
        return "nb"

    exact_matches = {
        "af": "af",
        "ar": "ar",
        "bg": "bg",
        "cs": "cs",
        "da": "da",
        "de": "de",
        "el": "el",
        "en": "en",
        "es": "es",
        "fi": "fi",
        "fr": "fr",
        "he": "he",
        "hi": "hi",
        "id": "id",
        "it": "it",
        "ja": "ja",
        "ko": "ko",
        "ms": "ms",
        "nl": "nl",
        "pl": "pl",
        "ro": "ro",
        "ru": "ru",
        "sv": "sv",
        "th": "th",
        "tr": "tr",
        "uk": "uk",
        "vi": "vi",
    }
    base = lower.split("-", 1)[0]
    if base in exact_matches:
        return exact_matches[base]

    if raw in SUPPORTED_LANGUAGES:
        return raw

    return FALLBACK_LANGUAGE


def _candidate_languages_from_env() -> Iterable[str]:
    for env_key in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG"):
        value = os.environ.get(env_key)
        if not value:
            continue
        for candidate in str(value).split(":"):
            cleaned = candidate.strip()
            if cleaned:
                yield cleaned


def _macos_system_languages() -> Iterable[str]:
    if sys.platform != "darwin":
        return ()
    commands = [
        ["defaults", "read", "-g", "AppleLanguages"],
        ["/usr/bin/defaults", "read", "-g", "AppleLanguages"],
    ]
    for command in commands:
        try:
            completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=1.5)
        except Exception:
            continue
        if completed.returncode != 0 or not completed.stdout.strip():
            continue
        for line in completed.stdout.splitlines():
            token = line.strip().strip(",").strip('"').strip()
            if token and token not in {"(", ")"}:
                yield token
        return ()
    return ()


def _windows_system_languages() -> Iterable[str]:
    if not sys.platform.startswith("win"):
        return ()
    candidates: list[str] = []
    try:
        import ctypes
        from locale import windows_locale

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        buffer = ctypes.create_unicode_buffer(85)
        get_locale_name = getattr(kernel32, "GetUserDefaultLocaleName", None)
        if get_locale_name is not None:
            result = get_locale_name(buffer, len(buffer))
            if result:
                candidates.append(buffer.value)

        get_ui_language = getattr(kernel32, "GetUserDefaultUILanguage", None)
        if get_ui_language is not None:
            language_id = int(get_ui_language())
            if language_id:
                mapped = windows_locale.get(language_id) or windows_locale.get(f"0x{language_id:04x}")
                if mapped:
                    candidates.append(mapped)
                hex_key = f"0x{language_id:04x}"
                if hex_key in _WINDOWS_LOCALE_OVERRIDES:
                    candidates.append(_WINDOWS_LOCALE_OVERRIDES[hex_key])
    except Exception:
        pass
    return tuple(candidate for candidate in candidates if candidate)


def detect_system_language() -> str:
    candidates: list[str] = []

    candidates.extend(_windows_system_languages())
    candidates.extend(_macos_system_languages())
    candidates.extend(_candidate_languages_from_env())

    for getter in (locale.getlocale, locale.getdefaultlocale):  # type: ignore[attr-defined]
        try:
            value = getter()[0]  # type: ignore[misc]
        except Exception:
            value = None
        if value:
            candidates.append(str(value))

    try:
        preferred = locale.getpreferredencoding(False)
        if preferred:
            candidates.append(str(preferred))
    except Exception:
        pass

    for candidate in candidates:
        normalized = normalize_language_code(candidate)
        if normalized in SUPPORTED_LANGUAGES:
            return normalized
    return FALLBACK_LANGUAGE


class Translator:
    def __init__(self, language_code: str = SYSTEM_LANGUAGE) -> None:
        self._english = _read_locale(FALLBACK_LANGUAGE)
        self._language_code = SYSTEM_LANGUAGE
        self._messages: Dict[str, str] = dict(self._english)
        self._resolved_language = FALLBACK_LANGUAGE
        self.set_language(language_code)

    @property
    def language_code(self) -> str:
        return self._language_code

    @property
    def resolved_language(self) -> str:
        return self._resolved_language

    def set_language(self, language_code: str) -> None:
        normalized = normalize_language_code(language_code)
        if normalized == SYSTEM_LANGUAGE:
            resolved = detect_system_language()
            self._language_code = SYSTEM_LANGUAGE
        else:
            resolved = normalized
            self._language_code = resolved

        localized = _read_locale(resolved)
        self._resolved_language = resolved
        self._messages = dict(self._english)
        self._messages.update(localized)

    def t(self, key: str, **kwargs: object) -> str:
        template = self._messages.get(key, self._english.get(key, key))
        try:
            return template.format(**kwargs)
        except Exception:
            return template


def available_language_codes() -> Iterable[str]:
    return SUPPORTED_LANGUAGES.keys()


def language_autonym(code: str) -> str:
    if code == SYSTEM_LANGUAGE:
        return "Auto"
    info = SUPPORTED_LANGUAGES.get(code)
    if info is None:
        return code
    return info.autonym
