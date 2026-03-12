from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from .app_paths import ensure_user_config_dir, legacy_settings_file_paths, settings_file_path
from .options import merge_with_defaults

SETTINGS_SCHEMA_VERSION = 1


class SettingsStore:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or settings_file_path()

    def _candidate_paths(self) -> list[Path]:
        candidates = [self.path]
        if self.path == settings_file_path():
            candidates.extend(legacy_settings_file_paths())
        return candidates

    def _read_values(self, path: Path) -> Optional[Dict[str, Any]]:
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

        values = payload.get("values") if isinstance(payload, dict) else None
        if not isinstance(values, dict):
            return None
        return values

    def load(self) -> Dict[str, Any]:
        defaults = merge_with_defaults({})
        for candidate in self._candidate_paths():
            values = self._read_values(candidate)
            if values is not None:
                return merge_with_defaults(values)
        return defaults

    def save(self, values: Dict[str, Any]) -> None:
        ensure_user_config_dir()
        payload = {
            "schema_version": SETTINGS_SCHEMA_VERSION,
            "values": merge_with_defaults(values),
        }

        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp_path.replace(self.path)
