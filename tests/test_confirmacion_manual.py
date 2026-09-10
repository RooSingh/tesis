# -*- coding: utf-8 -*-
"""Confirmacion manual: un mensaje confirmado es un mensaje escrito.

Lo que se ejercita es la cola de acuses, que es la parte con filo. La unidad de
confirmacion es **el mensaje del intermediario** y la unidad de escritura es **la
senal**, y desde que se agrupa un mensaje trae muchas senales: los lotes no
coinciden con los mensajes, de modo que un lote puede llevar la cola de uno, otro
entero y la cabeza de un tercero.
"""

from __future__ import annotations

import threading
import unittest

from backend.mqtt_consumer import TelemetryBatchBuffer


class BufferDePrueba(TelemetryBatchBuffer):
    """Un buffer que no arranca su hilo ni escribe en ninguna base."""

    def __init__(self, escritas=None):
        self.confirmados: list[tuple[int, int]] = []
        self._escritas = escritas
        super().__init__(writer=self._escribir, batch_size=4,
                         confirmar=lambda mid, qos:
                         self.confirmados.append((mid, qos)))
        self.stop_event.set()

    def _escribir(self, lote):
        if self._escritas == "falla":
            raise RuntimeError("la base no responde")
        return len(lote) if self._escritas is None else self._escritas


class ColaDeAcusesTest(unittest.TestCase):

    def test_un_mensaje_cubierto_por_un_lote_se_confirma(self):
        b = BufferDePrueba()
        b.registrar_mensaje(11, 1, senales=3)
        b._confirmar_cubiertos(3)
        self.assertEqual(b.confirmados, [(11, 1)])

    def test_un_mensaje_a_medias_no_se_confirma(self):
        """Confirmar lo que falta escribir es exactamente lo que se evita."""

        b = BufferDePrueba()
        b.registrar_mensaje(11, 1, senales=10)
        b._confirmar_cubiertos(4)
        self.assertEqual(b.confirmados, [])
        self.assertEqual(b.acuses[0][2], 6)

    def test_se_confirma_cuando_el_resto_se_escribe(self):
        b = BufferDePrueba()
        b.registrar_mensaje(11, 1, senales=10)
        b._confirmar_cubiertos(4)
        b._confirmar_cubiertos(6)
        self.assertEqual(b.confirmados, [(11, 1)])

    def test_un_lote_puede_cubrir_varios_mensajes(self):
        b = BufferDePrueba()
        for mid in (1, 2, 3):
            b.registrar_mensaje(mid, 1, senales=2)
        b._confirmar_cubiertos(6)
        self.assertEqual(b.confirmados, [(1, 1), (2, 1), (3, 1)])

    def test_un_lote_a_caballo_confirma_solo_los_completos(self):
        """El caso que la agrupacion vuelve normal y no excepcional."""

        b = BufferDePrueba()
        b.registrar_mensaje(1, 1, senales=2)
        b.registrar_mensaje(2, 1, senales=5)
        b._confirmar_cubiertos(4)
        self.assertEqual(b.confirmados, [(1, 1)])
        self.assertEqual(b.acuses[0][0], 2)
        self.assertEqual(b.acuses[0][2], 3)

    def test_se_confirma_en_orden_de_llegada(self):
        b = BufferDePrueba()
        for mid in (7, 8, 9):
            b.registrar_mensaje(mid, 1, senales=1)
        b._confirmar_cubiertos(3)
        self.assertEqual([m for m, _ in b.confirmados], [7, 8, 9])

    def test_un_mensaje_sin_senales_validas_se_confirma_en_el_acto(self):
        """Si no se confirmara, el intermediario lo reenviaria sin fin.

        Ningun lote lo va a cubrir, porque no dejo nada en la cola.
        """

        b = BufferDePrueba()
        b.registrar_mensaje(42, 1, senales=0)
        self.assertEqual(b.confirmados, [(42, 1)])
        self.assertEqual(len(b.acuses), 0)

    def test_sin_funcion_de_confirmacion_no_se_anota_nada(self):
        """El modo anterior sigue disponible para poder comparar los dos."""

        b = TelemetryBatchBuffer(writer=lambda lote: len(lote), batch_size=4)
        b.stop_event.set()
        b.registrar_mensaje(1, 1, senales=5)
        self.assertEqual(len(b.acuses), 0)


class ConfirmarTrasEscribirTest(unittest.TestCase):

    def test_el_flush_confirma_lo_que_escribio(self):
        b = BufferDePrueba()
        b.registrar_mensaje(5, 1, senales=2)
        b.pending = ["a", "b"]
        b.flush()
        self.assertEqual(b.confirmados, [(5, 1)])

    def test_si_la_escritura_falla_no_se_confirma_nada(self):
        """Es lo que hace que el intermediario los reenvie."""

        b = BufferDePrueba(escritas="falla")
        b.registrar_mensaje(5, 1, senales=2)
        b.pending = ["a", "b"]
        b.flush()
        self.assertEqual(b.confirmados, [])
        self.assertEqual(len(b.acuses), 1)

    def test_un_lote_de_repeticiones_igual_confirma(self):
        """Se consume por el tamano del lote y no por las filas persistidas.

        Con `ON CONFLICT DO NOTHING`, un lote formado solo por repeticiones
        persiste cero filas habiendo consumido mensajes reales de la cola. Medir
        por filas dejaria esos mensajes sin confirmar para siempre, y el
        intermediario los reenviaria en un bucle.
        """

        b = BufferDePrueba(escritas=0)
        b.registrar_mensaje(5, 1, senales=2)
        b.pending = ["a", "b"]
        b.flush()
        self.assertEqual(b.confirmados, [(5, 1)])

    def test_se_cuenta_cuantos_se_confirmaron(self):
        b = BufferDePrueba()
        for mid in (1, 2):
            b.registrar_mensaje(mid, 1, senales=1)
        b.pending = ["a", "b"]
        b.flush()
        self.assertEqual(b.metrics.get("confirmados"), 2)


if __name__ == "__main__":
    unittest.main()


class CoberturaVisibleAlTrabajadorTest(unittest.TestCase):
    """Ninguna senal puede quedar visible en la cola sin su acuse anotado.

    EL DEFECTO. `on_message` encolaba las senales **una por una** y anotaba el
    acuse del mensaje recien al terminar el bucle. Entre la primera senal
    encolada y esa anotacion hay un instante en que el trabajador ---que corre en
    otro hilo--- puede tomar un lote, escribirlo y consumir de la cola de acuses
    una cobertura que todavia no existe. La senal queda persistida y el mensaje
    del intermediario, pendiente para siempre: nunca se confirma, y el
    intermediario lo retiene o lo reenvia.

    Reproducido con `batch_size=1`.

    COMO SE PRUEBA, SIN CARRERAS NI ESPERAS. Lo que hace visible el estado al
    trabajador es **soltar el cerrojo**, porque es lo unico que el trabajador
    necesita para tomar un lote. Se envuelve el cerrojo y se comprueba la
    invariante en cada liberacion:

        senales en la cola <= senales cubiertas por los acuses anotados

    Si en alguna liberacion hay mas senales que cobertura, el trabajador podria
    haber escrito sin ella. No hace falta que la carrera ocurra: alcanza con que
    la ventana exista. Y la prueba no depende de **como** se encole, de modo que
    no se vuelve trivial cuando la implementacion cambie.
    """

    class CerrojoQueVigila:
        """El cerrojo del buffer, con una comprobacion en cada liberacion."""

        def __init__(self, real, buffer):
            self._real = real
            self._buffer = buffer
            self.descubiertas: list[int] = []

        def acquire(self, *a, **k):
            return self._real.acquire(*a, **k)

        def release(self):
            b = self._buffer
            cubiertas = sum(e[2] for e in b.acuses)
            sobran = len(b.pending) - cubiertas
            if sobran > 0:
                self.descubiertas.append(sobran)
            return self._real.release()

        def __enter__(self):
            self.acquire()
            return self

        def __exit__(self, *_):
            self.release()
            return False

        def __getattr__(self, nombre):
            return getattr(self._real, nombre)

    def _mensaje(self, senal: str) -> dict:
        return {
            "timestamp": "2026-09-10T00:00:00+00:00",
            "vehicle_id": "f1_25:session:1:car:0",
            "driver_id": "f1_25:car:0",
            "session_id": "f1_25:session:1",
            "lap_id": None,
            "signal_name": senal,
            "value": 1.0,
            "value_numeric": 1.0,
            "unit": "km/h",
            "quality_flag": "simulated_f1_25",
            "source_type": "f1_25_udp_simulation",
            "metadata": {"extra": {}},
        }

    def test_ninguna_senal_queda_visible_sin_su_acuse(self):
        from types import SimpleNamespace
        import json
        from backend import mqtt_consumer

        b = BufferDePrueba()
        vigilante = self.CerrojoQueVigila(b.lock, b)
        b.lock = vigilante
        b.batch_ready = threading.Condition(vigilante)

        carga = json.dumps([self._mensaje("speed"),
                            self._mensaje("gear_selected"),
                            self._mensaje("engine_speed")]).encode("utf-8")
        msg = SimpleNamespace(payload=carga, mid=7, qos=1)
        mqtt_consumer.on_message(None, b, msg)

        self.assertEqual(
            vigilante.descubiertas, [],
            "en %d momentos la cola quedo visible con senales sin acuse; el "
            "trabajador podria haberlas escrito sin cobertura"
            % len(vigilante.descubiertas))

    def test_un_mensaje_sin_senales_validas_se_confirma_en_el_acto(self):
        """No lo va a cubrir ningun lote: si no se confirma aca, no se confirma."""

        from types import SimpleNamespace
        from backend import mqtt_consumer

        b = BufferDePrueba()
        msg = SimpleNamespace(payload=b'[{"basura": true}]', mid=9, qos=1)
        mqtt_consumer.on_message(None, b, msg)
        self.assertEqual(b.confirmados, [(9, 1)])
