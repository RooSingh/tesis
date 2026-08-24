"""Pruebas locales del inventario de paquetes Nivel B sin base de datos."""

from __future__ import annotations

import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from backend.session_processor import (
    SessionPackageValidationError,
    build_package_inventory,
    register_package_validation,
)
from backend.session_context import load_available_context
from scripts.validate_session_package import main as validate_session_package_main


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


class SessionProcessorTests(unittest.TestCase):
    """Verifica validacion, capacidades y huellas reproducibles de paquetes locales."""

    def test_inventory_detects_partial_telemetry_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory)
            write_json(package / "drivers.json", [{"driver_number": 1}])
            write_json(package / "car_data_driver_1_VER.json", [{"speed": 250}])
            write_json(package / "session.json", {"session_key": 1234})
            write_json(package / "laps.json", [])

            first = build_package_inventory(package)
            second = build_package_inventory(package)

            self.assertEqual(first["package_fingerprint"], second["package_fingerprint"])
            self.assertEqual(first["session_key"], 1234)
            self.assertTrue(first["capabilities"]["drivers"])
            self.assertTrue(first["capabilities"]["laps"])
            self.assertEqual(first["capabilities"]["telemetry_drivers"]["car_data"], [1])
            self.assertEqual(first["capabilities"]["telemetry_drivers"]["location"], [])

    def test_inventory_changes_when_supported_input_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory)
            write_json(package / "session.json", {"session_key": 1234})
            write_json(package / "drivers.json", [])
            first = build_package_inventory(package)
            write_json(package / "drivers.json", [{"driver_number": 1}])
            second = build_package_inventory(package)

            self.assertNotEqual(first["package_fingerprint"], second["package_fingerprint"])

    def test_missing_session_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(SessionPackageValidationError, "session.json"):
                build_package_inventory(directory)

    def test_invalid_telemetry_json_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory)
            write_json(package / "session.json", {"session_key": 1234})
            (package / "car_data_driver_1_VER.json").write_text("not-json", encoding="utf-8")

            with self.assertRaisesRegex(SessionPackageValidationError, "JSON invalido"):
                build_package_inventory(package)

    def test_registering_same_package_twice_returns_existing_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory)
            write_json(package / "session.json", {"session_key": 1234})
            runs = {}
            issues = []

            def find_run(fingerprint: str) -> dict | None:
                return runs.get(fingerprint)

            def create_run(fingerprint: str, *args: object) -> dict | None:
                if fingerprint in runs:
                    return None
                run = {"run_id": len(runs) + 1, "package_fingerprint": fingerprint, "status": "validated"}
                runs[fingerprint] = run
                return run

            def record_issue(*args: object) -> None:
                issues.append(args)

            first = register_package_validation(package, find_run, create_run, record_issue)
            second = register_package_validation(package, find_run, create_run, record_issue)

            self.assertEqual(first["status"], "validated")
            self.assertEqual(second["status"], "already_validated")
            self.assertEqual(len(runs), 1)
            self.assertEqual(len(issues), 2)

    def test_validation_command_prints_traceable_summary(self) -> None:
        result = {
            "status": "validated",
            "run": {"run_id": 7},
            "inventory": {
                "session_key": 1234,
                "package_fingerprint": "test-fingerprint",
                "warnings": ["Advertencia de prueba"],
            },
        }
        with patch("scripts.validate_session_package.register_package_validation", return_value=result):
            with patch("sys.argv", ["validate_session_package.py", "test-package"]):
                with patch("sys.stdout", new_callable=StringIO) as output:
                    validate_session_package_main()

        summary = json.loads(output.getvalue())
        self.assertEqual(summary["status"], "validated")
        self.assertEqual(summary["run_id"], 7)
        self.assertEqual(summary["package_fingerprint"], "test-fingerprint")

    def test_context_loader_accepts_partial_session_and_reports_absences(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory)
            write_json(package / "session.json", {"session_key": 1234})
            write_json(package / "drivers.json", [{"driver_number": 1}])
            write_json(package / "laps.json", [])

            session, datasets, missing = load_available_context(package)

            self.assertEqual(session["session_key"], 1234)
            self.assertEqual(set(datasets), {"drivers", "laps"})
            self.assertIn("stints.json", missing)
            self.assertIn("session_result.json", missing)


if __name__ == "__main__":
    unittest.main()
