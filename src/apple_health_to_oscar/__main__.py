from __future__ import annotations

from pathlib import Path

from .cli import main


if __name__ == "__main__":
    raise SystemExit(main(base_dir=Path.cwd()))
