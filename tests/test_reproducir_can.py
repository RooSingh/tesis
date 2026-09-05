"""Pruebas del descarte de copias en la reproduccion CAN.

Que protegen
------------
Un registrador que escucha varios buses ve la misma trama mas de una vez: la
pasarela del vehiculo la reenvia entre buses fisicos, y el sistema de asistencia
la reenvia hacia el suyo. Ninguna copia es una medicion nueva, y contarlas
inflaria la frecuencia declarada sin que nada falle.

El defecto que estas pruebas fijan **ya ocurrio**: la primera version quitaba las
copias y dejaba el descarte de lo transmitido para despues. Como el descarte de
copias conserva la primera que aparece sin mirar el bus, cuando la primera era
una trama transmitida el adaptador la tiraba mas tarde y **la medicion se perdia
entera**, aunque su copia en un bus fisico existiera en el archivo. Se perdio el
63 % de una carga antes de que la conciliacion lo delatara.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from adapters import can_rav4  # noqa: E402
from backend import can_capture  # noqa: E402
from reproducir_can import tramas_unicas  # noqa: E402

DATOS = bytes.fromhex("4436444f44324410")
OTROS = bytes.fromhex("0011223344556677")


class DescarteDeCopiasTests(unittest.TestCase):

    def setUp(self):
        self._dir = TemporaryDirectory()
        self.ruta = Path(self._dir.name) / "prueba.canraw"

    def tearDown(self):
        self._dir.cleanup()

    def _escribir(self, tramas) -> None:
        with can_capture.EscritorCaptura(self.ruta) as escritor:
            for instante, identificador, bus, datos in tramas:
                escritor.escribir(instante, identificador, bus, datos)

    def _leidas(self):
        return [(t.instante_ns, t.identificador, t.bus, t.datos)
                for t in tramas_unicas(self.ruta)]

    def test_la_copia_entre_buses_fisicos_se_descarta(self):
        """Misma trama, mismo instante, dos buses: es una medicion."""

        self._escribir([(1000, 170, 0, DATOS), (1000, 170, 2, DATOS)])
        leidas = self._leidas()
        self.assertEqual(len(leidas), 1)
        self.assertEqual(leidas[0][2], 0)

    def test_la_trama_transmitida_no_desplaza_a_la_medida(self):
        """El defecto exacto que costo una recarga.

        La transmitida aparece **primero** en el archivo. Si el descarte de
        copias la conservara, el adaptador la tiraria despues por su bus y la
        medicion se perderia, pese a estar en el archivo.
        """

        self._escribir([(1000, 170, 130, DATOS), (1000, 170, 0, DATOS)])
        leidas = self._leidas()
        self.assertEqual(len(leidas), 1)
        self.assertLess(leidas[0][2], can_rav4.BUS_TRANSMITIDO_DESDE)
        self.assertEqual(leidas[0][2], 0)

    def test_ninguna_trama_transmitida_sobrevive(self):
        self._escribir([(1000, 170, 128, DATOS), (2000, 170, 130, OTROS)])
        self.assertEqual(self._leidas(), [])

    def test_dos_mediciones_distintas_en_el_mismo_instante_se_conservan(self):
        """Dos identificadores distintos son dos mediciones, no una copia."""

        self._escribir([(1000, 170, 0, DATOS), (1000, 180, 0, DATOS)])
        self.assertEqual(len(self._leidas()), 2)

    def test_la_misma_trama_en_instantes_distintos_se_conserva(self):
        """Un valor que no cambia sigue siendo una medicion nueva cada vez."""

        self._escribir([(1000, 170, 0, DATOS), (2000, 170, 0, DATOS)])
        self.assertEqual(len(self._leidas()), 2)

    def test_el_mismo_identificador_con_otro_contenido_se_conserva(self):
        """Mismo instante y mismo identificador, bytes distintos: no es copia."""

        self._escribir([(1000, 170, 0, DATOS), (1000, 170, 1, OTROS)])
        self.assertEqual(len(self._leidas()), 2)


if __name__ == "__main__":
    unittest.main()
