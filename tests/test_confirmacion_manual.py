# -*- coding: utf-8 -*-
"""Confirmacion manual: un mensaje confirmado es un mensaje escrito.

Lo que se ejercita es la cola de acuses, que es la parte con filo. La unidad de
confirmacion es **el mensaje del intermediario** y la unidad de escritura es **la
senal**, y desde que se agrupa un mensaje trae muchas senales: los lotes no
coinciden con los mensajes, de modo que un lote puede llevar la cola de uno, otro
entero y la cabeza de un tercero.
"""

from __future__ import annotations

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
