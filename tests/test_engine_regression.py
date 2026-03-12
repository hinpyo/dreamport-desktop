from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from apple_health_to_oscar.engine import (  # noqa: E402
    DREEM_HEADER,
    ZEO_HEADER,
    ConversionConfig,
    run_conversion,
)
from apple_health_to_oscar.timezones import load_timezone_catalog  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "sample_export.xml"


class EngineRegressionTests(unittest.TestCase):
    def test_first_run_writes_expected_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "output"
            result = run_conversion(
                ConversionConfig(
                    input_path=str(FIXTURE),
                    output_dir=str(output_dir),
                    output_format="both",
                    timezone="Asia/Seoul",
                ),
                base_dir=ROOT,
            )

            self.assertEqual(result.stats.final_sessions, 1)
            self.assertEqual(result.stats.files_written, 2)
            self.assertTrue(result.manifest_path.exists())

            dreem_files = list((output_dir / "Dreem").glob("*.dreem.csv"))
            zeo_files = list((output_dir / "ZEO").glob("*.zeo.csv"))
            self.assertEqual(len(dreem_files), 1)
            self.assertEqual(len(zeo_files), 1)

            with dreem_files[0].open("r", encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh, delimiter=";")
                self.assertEqual(reader.fieldnames, DREEM_HEADER)
                row = next(reader)
                self.assertEqual(row["Start Time"], "2026-03-09T01:00:00+09:00")
                self.assertEqual(row["Stop Time"], "2026-03-09T06:00:00+09:00")
                self.assertEqual(row["Sleep Duration"], "4:30:00")
                self.assertEqual(row["Sleep Onset Duration"], "0:30:00")
                self.assertEqual(row["Light Sleep Duration"], "2:30:00")
                self.assertEqual(row["Deep Sleep Duration"], "1:00:00")
                self.assertEqual(row["REM Duration"], "1:00:00")
                self.assertEqual(row["Number of awakenings"], "0")

            with zeo_files[0].open("r", encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh, delimiter=",")
                self.assertEqual(reader.fieldnames, ZEO_HEADER)
                row = next(reader)
                self.assertEqual(row["Start of Night"], "03/09/2026 01:00")
                self.assertEqual(row["End of Night"], "03/09/2026 06:00")

            with result.manifest_path.open("r", encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh)
                rows = list(reader)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["manifest_version"], "4")
                self.assertEqual(rows[0]["start_time"], "2026-03-09T01:00:00+09:00")
                self.assertEqual(rows[0]["stop_time"], "2026-03-09T06:00:00+09:00")

    def test_second_run_reuses_existing_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "output"
            config = ConversionConfig(
                input_path=str(FIXTURE),
                output_dir=str(output_dir),
                output_format="both",
                timezone="Asia/Seoul",
            )
            first = run_conversion(config, base_dir=ROOT)
            second = run_conversion(config, base_dir=ROOT)

            self.assertEqual(first.stats.files_written, 2)
            self.assertEqual(second.stats.files_written, 0)
            self.assertEqual(second.stats.files_reused, 2)
            self.assertEqual(second.stats.final_sessions, 1)

    def test_timezone_catalog_covers_wide_offset_range(self) -> None:
        values = {entry.value for entry in load_timezone_catalog()}
        self.assertIn("Etc/GMT+12", values)
        self.assertIn("Pacific/Kiritimati", values)
        self.assertIn("Asia/Seoul", values)
        self.assertIn("Asia/Kathmandu", values)


if __name__ == "__main__":
    unittest.main()
