"""Pruebas de persistencia de snapshots de metricas MQTT."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("run_mqtt_consumer", ROOT / "scripts" / "run_mqtt_consumer.py")
assert SPEC is not None and SPEC.loader is not None
run_mqtt_consumer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(run_mqtt_consumer)


class RunMqttConsumerTests(unittest.TestCase):
    def test_appends_metrics_history_as_json_lines(self) -> None:
        snapshot = {"observed_at_utc": "2025-07-06T14:05:00+00:00", "received": 2, "pending": 0}
        with tempfile.TemporaryDirectory() as directory:
            history_path = Path(directory) / "metrics.jsonl"

            run_mqtt_consumer.guardar_historial_metricas(history_path, snapshot)
            run_mqtt_consumer.guardar_historial_metricas(history_path, snapshot)

            rows = [json.loads(line) for line in history_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(rows, [snapshot, snapshot])

    def test_la_linea_de_supervision_expone_los_descartes_del_broker(self) -> None:
        """`broker_dropped` debe verse durante la corrida, no solo en el JSONL.

        Es el unico indicador del tramo broker -> consumidor: sin el, una corrida
        puede mostrar todos los contadores en cero mientras pierde mensajes.
        """
        linea = run_mqtt_consumer.linea_metricas({
            "received": 40800,
            "persisted": 40800,
            "pending": 0,
            "errors": 0,
            "decode_errors": 0,
            "processing_errors": 0,
            "disconnects": 0,
            "broker_dropped": 0,
            "duplicates_skipped": 0,
            "max_pending": 1199,
        })

        self.assertIn("broker_dropped=0", linea)
        self.assertIn("duplicates_skipped=0", linea)
        self.assertIn("max_pending=1199", linea)

    def test_una_metrica_ausente_no_interrumpe_la_supervision(self) -> None:
        """Un consumidor viejo no debe romper el script de supervision."""
        linea = run_mqtt_consumer.linea_metricas({"received": 10})

        self.assertIn("received=10", linea)
        self.assertIn("broker_dropped=n/d", linea)


if __name__ == "__main__":
    unittest.main()
