from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
PACKAGE_RESOURCES_DIR = SRC_DIR / "apple_health_to_oscar" / "resources"
ASSETS_DIR = PROJECT_ROOT / "assets"
ENTRY_SCRIPT = PROJECT_ROOT / "dreamport_gui.py"
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"
APP_NAME = "DreamPort"
BUNDLE_ID = "io.github.example.dreamport"


def _data_arg(source: Path, target_dir: str) -> str:
    separator = ";" if sys.platform.startswith("win") else ":"
    return f"{source}{separator}{target_dir}"


def _icon_path() -> Path:
    if sys.platform == "darwin":
        candidate = ASSETS_DIR / "oscar_icon.icns"
        if candidate.exists():
            return candidate
    if sys.platform.startswith("win"):
        candidate = ASSETS_DIR / "oscar_icon.ico"
        if candidate.exists():
            return candidate
    for candidate in (
        ASSETS_DIR / "oscar_icon.ico",
        ASSETS_DIR / "oscar_icon.icns",
        ASSETS_DIR / "dreamport_header_icon.png",
        ASSETS_DIR / "oscar_icon_runtime.png",
        ASSETS_DIR / "oscar_icon.png",
    ):
        if candidate.exists():
            return candidate
    raise FileNotFoundError("No icon file found in assets/")


def _bundle_mode_args() -> list[str]:
    if sys.platform.startswith("win"):
        return ["--onefile"]
    return ["--onedir"]


# Modules that are safe to exclude: stdlib dev-only and build tools.
# PIL.* submodules are intentionally NOT excluded here because PIL.Image
# imports many of them internally, and excluding them causes ImportError
# at runtime (e.g. "cannot import name 'TiffTags' from 'PIL'").
_EXCLUDE_MODULES = [
    "unittest",
    "test",
    "lib2to3",
    "ensurepip",
    "distutils",
    "setuptools",
    "pkg_resources",
    "pip",
    "pydoc",
    "doctest",
    "xmlrpc",
]


def main() -> int:
    from PyInstaller.__main__ import run as pyinstaller_run

    icon_path = _icon_path()
    args = [
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        APP_NAME,
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(BUILD_DIR),
        "--specpath",
        str(BUILD_DIR / "spec"),
        "--paths",
        str(PROJECT_ROOT),
        "--paths",
        str(SRC_DIR),
        "--icon",
        str(icon_path),
        "--hidden-import",
        "tkinter",
        "--collect-data",
        "tzdata",
        "--add-data",
        _data_arg(ASSETS_DIR, "assets"),
        "--add-data",
        _data_arg(PACKAGE_RESOURCES_DIR, "apple_health_to_oscar/resources"),
    ]

    for mod in _EXCLUDE_MODULES:
        args.extend(["--exclude-module", mod])

    args.extend(_bundle_mode_args())

    if sys.platform == "darwin":
        args.extend([
            "--osx-bundle-identifier",
            BUNDLE_ID,
        ])

    args.append(str(ENTRY_SCRIPT))
    print("Running PyInstaller with arguments:")
    for item in args:
        print(item)
    pyinstaller_run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
