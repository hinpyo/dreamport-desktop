from __future__ import annotations

import argparse
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = PROJECT_ROOT / "dist"
RELEASE_DIR = PROJECT_ROOT / "release-assets"
APP_NAME = "DreamPort"



def build_archive_name(version: str, platform_name: str) -> str:
    safe_version = version.strip() or "dev"
    return f"dreamport-{safe_version}-{platform_name}.zip"



def _resolve_built_output(platform_name: str) -> Path:
    candidates = []
    if platform_name == "macos":
        candidates.append(DIST_DIR / f"{APP_NAME}.app")
    elif platform_name == "windows-x64":
        candidates.append(DIST_DIR / f"{APP_NAME}.exe")
        candidates.append(DIST_DIR / APP_NAME)
    else:
        candidates.append(DIST_DIR / APP_NAME)

    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Built output not found. Checked: {', '.join(str(p) for p in candidates)}")



def _clean_path(path: Path) -> None:
    if path.exists():
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()



def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", required=True, choices=["windows-x64", "macos", "linux"])
    parser.add_argument("--version", default="dev")
    args = parser.parse_args()

    built_output = _resolve_built_output(args.platform)

    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = RELEASE_DIR / build_archive_name(args.version, args.platform)
    _clean_path(archive_path)

    staging_root = RELEASE_DIR / f".stage-{built_output.stem}"
    _clean_path(staging_root)
    staging_root.mkdir(parents=True, exist_ok=True)

    staged_item = staging_root / built_output.name
    if built_output.is_dir():
        shutil.copytree(built_output, staged_item)
    else:
        shutil.copy2(built_output, staged_item)

    temp_base = archive_path.with_suffix("")
    _clean_path(temp_base)
    shutil.make_archive(
        base_name=str(temp_base),
        format="zip",
        root_dir=str(staging_root),
        base_dir=built_output.name,
    )

    final_zip = temp_base.with_suffix(".zip")
    if final_zip != archive_path:
        _clean_path(archive_path)
        final_zip.rename(archive_path)

    _clean_path(staging_root)

    print(archive_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
