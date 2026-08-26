"""Pruebas de configuracion del cliente MQTT sin broker real."""

from __future__ import annotations

import unittest

from backend.config import MQTT_REPLAY_TOPIC, MQTT_SYS_DROPPED_TOPIC, MQTT_TOPIC
from backend.mqtt_consumer import on_connect, on_disconnect, on_message, on_sys_dropped


class FakeMqttClient:
    def __init__(self) -> None:
        self.subscriptions = []

    def subscribe(self, subscriptions: list[tuple[str, int]]) -> None:
        self.subscriptions = subscriptions


class FakeBuffer:
    def __init__(self) -> None:
        self.decode_errors = 0
        self.processing_errors = 0
        self.disconnects = 0
        self.broker_dropped = []

    def record_decode_error(self) -> None:
        self.decode_errors += 1

    def record_processing_error(self) -> None:
        self.processing_errors += 1

    def record_disconnect(self) -> None:
        self.disconnects += 1

    def record_broker_dropped(self, total: int) -> None:
        self.broker_dropped.append(total)


class FakeMqttMessage:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload


class MqttConsumerTests(unittest.TestCase):
    def test_replay_subscription_uses_qos_one(self) -> None:
        client = FakeMqttClient()

        on_connect(client, None, None, "Success", None)

        self.assertEqual(
            client.subscriptions,
            [(MQTT_TOPIC, 0), (MQTT_REPLAY_TOPIC, 1), (MQTT_SYS_DROPPED_TOPIC, 0)],
        )

    def test_invalid_message_increments_decode_errors(self) -> None:
        buffer = FakeBuffer()

        on_message(None, buffer, FakeMqttMessage(b"not-json"))

        self.assertEqual(buffer.decode_errors, 1)
        self.assertEqual(buffer.processing_errors, 0)

    def test_disconnect_increments_counter(self) -> None:
        buffer = FakeBuffer()

        on_disconnect(None, buffer, None, "Success", None)

        self.assertEqual(buffer.disconnects, 1)

    def test_estadistica_sys_registra_descartes_del_broker(self) -> None:
        """Mosquitto publica el acumulado como texto en su topico de estadisticas."""
        buffer = FakeBuffer()

        on_sys_dropped(None, buffer, FakeMqttMessage(b"8985"))

        self.assertEqual(buffer.broker_dropped, [8985])

    def test_estadistica_sys_ilegible_no_se_cuenta_como_error_de_telemetria(self) -> None:
        """Un `$SYS` corrupto no debe contaminar `decode_errors`.

        Esos contadores existen para distinguir perdidas de telemetria; mezclar
        alli una estadistica del broker haria ilegible el diagnostico.
        """
        buffer = FakeBuffer()

        on_sys_dropped(None, buffer, FakeMqttMessage(b"no-es-un-numero"))

        self.assertEqual(buffer.broker_dropped, [])
        self.assertEqual(buffer.decode_errors, 0)
        self.assertEqual(buffer.processing_errors, 0)


if __name__ == "__main__":
    unittest.main()
