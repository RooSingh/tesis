"""Pruebas locales del descargador OpenF1 sin red."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.download_openf1_session_telemetry import plan_downloads, write_manifest


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


class OpenF1DownloaderTests(unittest.TestCase):
    def test_plan_detects_cached_and_missing_driver_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session_path = Path(directory)
            write_json(session_path / "session.json", {"session_key": 9947})
            write_json(session_path / "drivers.json", [{"driver_number": 1, "name_acronym": "VER"}, {"driver_number": 4, "name_acronym": "NOR"}])
            write_json(session_path / "car_data_driver_1_VER.json", [{"speed": 1}])
            write_json(session_path / "location_driver_1_VER.json", [{"x": 1}])

            plan = plan_downloads(session_path)

            self.assertEqual(plan["cached"], 2)
            self.assertEqual(plan["missing"], 2)
            missing = [record for record in plan["records"] if record["status"] == "missing"]
            self.assertEqual({Path(record["path"]).name for record in missing}, {"car_data_driver_4_NOR.json", "location_driver_4_NOR.json"})

    def test_manifest_records_dry_run_without_database_or_mqtt_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session_path = Path(directory)
            result = {"session_key": 9947, "drivers": 1, "endpoints": ["car_data"], "records": [], "cached": 1, "missing": 0}

            manifest = write_manifest(session_path, result, "dry_run")
            payload = json.loads(manifest.read_text(encoding="utf-8"))

            self.assertEqual(payload["mode"], "dry_run")
            self.assertFalse(payload["scope"]["database_writes"])
            self.assertFalse(payload["scope"]["mqtt_publish"])


if __name__ == "__main__":
    unittest.main()
