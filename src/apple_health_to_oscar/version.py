from __future__ import annotations

from importlib import metadata
from pathlib import Path
from typing import Optional

try:
    import tomllib  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

__all__ = ["__version__", "get_display_version"]

_DEFAULT_VERSION = "0.1.0"


def _version_from_installed_metadata() -> Optional[str]:
    for package_name in ("apple-health-to-oscar", "apple_health_to_oscar"):
        try:
            value = metadata.version(package_name)
        except metadata.PackageNotFoundError:
            continue
        except Exception:
            continue
        if value:
            return str(value)
    return None



def _version_from_pyproject() -> Optional[str]:
    if tomllib is None:
        return None
    try:
        root = Path(__file__).resolve().parents[2]
        pyproject_path = root / "pyproject.toml"
        if not pyproject_path.exists():
            return None
        payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        value = payload.get("project", {}).get("version")
        if value:
            return str(value)
    except Exception:
        return None
    return None



def get_display_version() -> str:
    return _version_from_installed_metadata() or _version_from_pyproject() or _DEFAULT_VERSION


__version__ = get_display_version()
