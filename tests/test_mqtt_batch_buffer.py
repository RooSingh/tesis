"""Pruebas locales del buffer MQTT sin broker ni TimescaleDB."""

from __future__ import annotations

import unittest

from backend.models import TelemetryMessage
from backend.mqtt_consumer import TelemetryBatchBuffer


def message(index: int) -> TelemetryMessage:
    return TelemetryMessage.model_validate({
        "timestamp": f"2025-07-06T15:18:{index:02d}+00:00",
        "vehicle_id": "test:vehicle",
        "driver_id": "test:driver",
        "session_id": "test:session",
        "lap_id": None,
        "source_type": "test",
        "signal_name": "speed",
        "value": index,
        "unit": "km/h",
        "quality_flag": "test",
        "metadata": {},
    })


class TelemetryBatchBufferTests(unittest.TestCase):
    def test_flushes_in_configured_batches(self) -> None:
        written = []
        buffer = TelemetryBatchBuffer(lambda batch: written.append(len(batch)) or len(batch), batch_size=2, flush_interval=60)
        try:
            for index in range(5):
                buffer.enqueue(message(index))
            self.assertEqual(buffer.flush(), 2)
            self.assertEqual(buffer.flush(), 2)
            self.assertEqual(buffer.flush(), 1)
            self.assertEqual(written, [2, 2, 1])
            self.assertEqual(buffer.snapshot(), {"received": 5, "persisted": 5, "errors": 0, "pending": 0})
        finally:
            buffer.close()

    def test_requeues_failed_batch(self) -> None:
        buffer = TelemetryBatchBuffer(lambda batch: (_ for _ in ()).throw(RuntimeError("db unavailable")), batch_size=2, flush_interval=60)
        try:
            buffer.enqueue(message(1))
            self.assertEqual(buffer.flush(), 0)
            self.assertEqual(buffer.snapshot(), {"received": 1, "persisted": 0, "errors": 1, "pending": 1})
        finally:
            buffer.writer = lambda batch: len(batch)
            buffer.close()
