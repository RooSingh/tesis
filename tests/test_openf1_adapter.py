"""Pruebas del contrato MQTT para replay historico OpenF1."""

from __future__ import annotations

import unittest

from adapters.openf1 import messages_from_openf1_sample
from backend.models import TelemetryMessage


class OpenF1AdapterTests(unittest.TestCase):
    """Verifica construccion local; no publica MQTT ni requiere base de datos."""

    def test_car_data_creates_six_valid_messages(self) -> None:
        sample = {
            "date": "2025-07-06T14:20:01.123000+00:00",
            "meeting_key": 1277,
            "session_key": 9947,
            "driver_number": 4,
            "speed": 245,
            "throttle": 100,
            "brake": 0,
            "rpm": 12000,
            "n_gear": 8,
            "drs": 12,
        }
        messages = messages_from_openf1_sample(sample, "car_data", "https://example.test/car_data", "raw.json", "2026-08-12T00:00:00+00:00")
        self.assertEqual(len(messages), 6)
        self.assertEqual({message["signal_name"] for message in messages}, {"speed", "throttle_position", "brake_applied", "engine_speed", "gear_selected", "drs_state_code"})
        for message in messages:
            validated = TelemetryMessage.model_validate(message)
            self.assertEqual(validated.source_type, "openf1_historical_replay")
            self.assertTrue(validated.metadata.extra["replay_mode"])
            self.assertEqual(validated.metadata.extra["published_at_utc"], "2026-08-12T00:00:00+00:00")
        brake = next(message for message in messages if message["signal_name"] == "brake_applied")
        self.assertIs(brake["value"], False)

    def test_location_creates_three_valid_messages(self) -> None:
        sample = {"date": "2025-07-06T14:20:01.123000+00:00", "meeting_key": 1277, "session_key": 9947, "driver_number": 1, "x": 10, "y": 20, "z": 30}
        messages = messages_from_openf1_sample(sample, "location", "https://example.test/location", "raw.json", "2026-08-12T00:00:00+00:00")
        self.assertEqual([message["signal_name"] for message in messages], ["track_position_x", "track_position_y", "track_position_z"])


if __name__ == "__main__":
    unittest.main()
