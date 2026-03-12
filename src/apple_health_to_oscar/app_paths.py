from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

APP_DISPLAY_NAME = "DreamPort"
APP_DIR_NAME = "DreamPort"
LEGACY_APP_DIR_NAMES = ("OSCARSleepConverter", "OSCAR Sleep Converter")
SETTINGS_FILENAME = "settings.json"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def package_dir() -> Path:
    return Path(__file__).resolve().parent


def project_root() -> Path:
    return package_dir().parents[2]


def bundled_base_dir() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass).resolve()
    return Path(sys.executable).resolve().parent


def runtime_base_dir(explicit_base_dir: Optional[Path] = None) -> Path:
    if explicit_base_dir is not None:
        return explicit_base_dir.expanduser().resolve()
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return project_root()


def resource_dir() -> Path:
    return package_dir() / "resources"


def resource_path(*parts: str) -> Path:
    return resource_dir().joinpath(*parts)


def asset_dir() -> Path:
    candidates = []
    if is_frozen():
        candidates.append(bundled_base_dir() / "assets")
        candidates.append(Path(sys.executable).resolve().parent / "assets")
    candidates.append(project_root() / "assets")
    candidates.append(Path.cwd() / "assets")

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def asset_path(*parts: str) -> Path:
    return asset_dir().joinpath(*parts)


def optional_asset_path(*parts: str) -> Optional[Path]:
    path = asset_path(*parts)
    return path if path.exists() else None


def _config_dir_for_name(app_name: str) -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / app_name
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / app_name
        return Path.home() / "AppData" / "Roaming" / app_name
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / app_name
    return Path.home() / ".config" / app_name


def user_config_dir() -> Path:
    return _config_dir_for_name(APP_DIR_NAME)


def legacy_settings_file_paths() -> list[Path]:
    return [
        _config_dir_for_name(name) / SETTINGS_FILENAME
        for name in LEGACY_APP_DIR_NAMES
    ]


def settings_file_path() -> Path:
    return user_config_dir() / SETTINGS_FILENAME


def ensure_user_config_dir() -> Path:
    directory = user_config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    return directory
