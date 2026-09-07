"""Pruebas de configuracion del cliente MQTT sin broker real."""

from __future__ import annotations

import unittest

from backend.config import MQTT_REPLAY_TOPIC, MQTT_SYS_DROPPED_TOPIC, MQTT_TOPIC
from backend.config import MQTT_QOS_EN_VIVO
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
        #: Lo que el consumidor encolo. Antes no hacia falta porque las pruebas
        #: cubrian solo los caminos de error; con los lotes hay que poder
        #: comprobar **cuantas senales pasaron**, y no solo cuantas fallaron.
        self.enqueued = []
        #: Los mensajes del intermediario anotados a la espera de su acuse, con
        #: la cuenta de senales que cada uno dejo en la cola. El simulacro tiene
        #: que implementarlo porque **es parte del contrato del buffer**: si no,
        #: la prueba pasaria con un buffer que el consumidor real no acepta.
        self.registrados = []

    def enqueue(self, mensaje) -> None:
        self.enqueued.append(mensaje)

    def registrar_mensaje(self, mid: int, qos: int, senales: int) -> None:
        self.registrados.append((mid, qos, senales))

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
        """El topico de reproduccion se suscribe con garantia de entrega.

        Se afirma **solo eso**, que es lo que la prueba quiere fijar. La version
        anterior comparaba la lista entera y de paso congelaba la calidad del
        topico en vivo en cero, sin que nada lo justificara: una asercion de mas
        que convirtio un valor incidental en un requisito.
        """

        client = FakeMqttClient()

        on_connect(client, None, None, "Success", None)

        por_topico = dict(client.subscriptions)
        self.assertEqual(por_topico[MQTT_REPLAY_TOPIC], 1)

    def test_live_subscription_uses_configured_qos(self) -> None:
        """El topico en vivo se suscribe con la calidad configurada.

        Importa que salga de la configuracion y no de una constante escrita en el
        codigo: la entrega al suscriptor se rige por el minimo entre la calidad de
        la publicacion y la de la suscripcion, de modo que suscribirse en cero
        anula la garantia del publicador y con ella la sesion persistente.
        """

        client = FakeMqttClient()

        on_connect(client, None, None, "Success", None)

        por_topico = dict(client.subscriptions)
        self.assertEqual(por_topico[MQTT_TOPIC], MQTT_QOS_EN_VIVO)

    def test_las_estadisticas_del_broker_siguen_sin_garantia(self) -> None:
        """Son informativas: perder una no pierde telemetria."""

        client = FakeMqttClient()

        on_connect(client, None, None, "Success", None)

        por_topico = dict(client.subscriptions)
        self.assertEqual(por_topico[MQTT_SYS_DROPPED_TOPIC], 0)

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


def _senal(nombre: str = "speed_kmh") -> dict:
    """Una senal completa segun el contrato interno."""

    return {
        "timestamp": "2026-09-06T00:00:00+00:00",
        "vehicle_id": "f1_25:session:1:car:7",
        "driver_id": "f1_25:car:7",
        "session_id": "f1_25:session:1",
        "lap_id": None,
        "source_type": "f1_25_udp_simulation",
        "signal_name": nombre,
        "value": 297.0,
        "unit": "km/h",
        "quality_flag": "ok",
        "metadata": {},
    }


class MensajesEnLoteTests(unittest.TestCase):
    """El consumidor acepta una senal suelta y una lista de senales.

    Se distinguen **por la forma y no por una marca**: si lo que llega es una
    lista, son varias; si es un objeto, es una.

    Aceptar las dos no es indecision. Hay tres publicadores usando este contrato
    ---el capturador, la reproduccion del bus y la carga de la fuente
    deportiva--- y cambiarlos a los tres a la vez volveria imposible ubicar un
    fallo. Los que no agrupen siguen andando sin tocarlos.
    """

    def _procesar(self, carga) -> FakeBuffer:
        import json
        buffer = FakeBuffer()
        on_message(None, buffer, FakeMqttMessage(json.dumps(carga).encode()))
        return buffer

    def test_el_mensaje_se_anota_con_su_cuenta_de_senales(self):
        """El acuse es por mensaje y la escritura por senal: hace falta el puente.

        Sin la cuenta, no se sabria cuando un lote escrito cubrio el mensaje
        entero, que es la condicion para confirmarlo.
        """

        b = self._procesar([_senal("s%d" % i) for i in range(7)])
        self.assertEqual(len(b.registrados), 1)
        self.assertEqual(b.registrados[0][2], 7)

    def test_las_senales_rechazadas_no_cuentan_para_el_acuse(self):
        """Se anota lo que entro a la cola, no lo que llego."""

        b = self._procesar([_senal("uno"), {"basura": True}, _senal("dos")])
        self.assertEqual(b.registrados[0][2], 2)

    def test_una_senal_suelta_sigue_funcionando(self):
        """Es el contrato que los otros dos publicadores todavia usan."""

        b = self._procesar(_senal())
        self.assertEqual(len(b.enqueued), 1)
        self.assertEqual(b.decode_errors, 0)

    def test_un_lote_encola_todas_sus_senales(self):
        b = self._procesar([_senal(f"s{i}") for i in range(560)])
        self.assertEqual(len(b.enqueued), 560)
        self.assertEqual(b.decode_errors, 0)

    def test_una_senal_invalida_no_arrastra_al_resto_del_lote(self):
        """Es la razon por la que la validacion va dentro del bucle.

        Si el error cortara el procesamiento del lote, **una senal mal formada
        entre quinientas sesenta descartaria las otras quinientas cincuenta y
        nueve**, y el sintoma seria una perdida enorme por una causa minuscula.
        """

        invalida = _senal()
        del invalida["signal_name"]
        b = self._procesar([_senal("a"), invalida, _senal("b")])
        self.assertEqual(len(b.enqueued), 2)
        self.assertEqual(b.decode_errors, 1)

    def test_un_lote_vacio_no_encola_ni_falla(self):
        b = self._procesar([])
        self.assertEqual(len(b.enqueued), 0)
        self.assertEqual(b.decode_errors, 0)
        self.assertEqual(b.processing_errors, 0)
