#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Legacy DreamPort GUI shim.

This file is kept for backwards compatibility. Prefer `python dreamport_gui.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from dreamport_gui import main


if __name__ == "__main__":
    raise SystemExit(main(base_dir=ROOT_DIR))
