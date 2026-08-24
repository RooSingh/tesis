"""Pruebas locales de endpoints de procesamiento sin TimescaleDB."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import HTTPException

from backend.app import processing_run, processing_run_issues


class ProcessingApiTests(unittest.TestCase):
    def test_processing_run_returns_traceable_status(self) -> None:
        run = {"run_id": 1, "session_key": 9947, "status": "completed", "counts": {"drivers": 20}}
        with patch("backend.app.obtener_ejecucion_procesamiento", return_value=run):
            response = processing_run(1)

        self.assertEqual(response["status"], "completed")
        self.assertEqual(response["counts"]["drivers"], 20)

    def test_processing_run_404_when_missing(self) -> None:
        with patch("backend.app.obtener_ejecucion_procesamiento", return_value=None):
            with self.assertRaises(HTTPException) as error:
                processing_run(999)

        self.assertEqual(error.exception.status_code, 404)

    def test_processing_issues_returns_warnings(self) -> None:
        run = {"run_id": 2, "session_key": 10006, "status": "partial"}
        issues = [{"severity": "warning", "message": "faltan archivos opcionales"}]
        with patch("backend.app.obtener_ejecucion_procesamiento", return_value=run):
            with patch("backend.app.listar_incidencias_procesamiento", return_value=issues):
                response = processing_run_issues(2)

        self.assertEqual(response[0]["severity"], "warning")


if __name__ == "__main__":
    unittest.main()
