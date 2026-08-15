"""Prueba del lote MQTT acotado sin publicar en el broker."""

from __future__ import annotations

import unittest

from scripts.day18_openf1_technical_batch import build_batch


class OpenF1TechnicalBatchTests(unittest.TestCase):
    def test_builds_exactly_the_authorized_messages(self) -> None:
        messages = build_batch()
        self.assertEqual(len(messages), 27)
        self.assertEqual({message["driver_id"] for message in messages}, {"openf1:driver:1", "openf1:driver:4", "openf1:driver:81"})
        self.assertTrue(all(message["metadata"]["extra"]["replay_mode"] for message in messages))


if __name__ == "__main__":
    unittest.main()
