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
import reproducir_can  # noqa: E402
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


class ConexionFalsa:
    """Una conexion que contesta lo que se le diga y anota que le preguntaron."""

    def __init__(self, cuenta):
        self.cuenta = cuenta
        self.consultas = []

    def cursor(self):
        return self

    def execute(self, sql, parametros=None):
        self.consultas.append((" ".join(sql.split()), parametros))

    def fetchone(self):
        return (self.cuenta,)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class ConciliarNoCuentaDosVecesTests(unittest.TestCase):
    """La conciliacion tiene que dar lo mismo cargando una vez o cinco.

    QUE PASO, EL 2026-09-13. El usuario volvio a subir `sample_01`, que ya
    estaba cargado. El indice unico de identidad de reproduccion suprimio las
    57.890 repeticiones ---que es exactamente lo que tiene que hacer--- y el
    guion informo **NO CONCILIA: faltan 57.890 filas** y salio con codigo 1. La
    base estaba perfecta: 57.890 filas y 57.890 identidades distintas.

    LA CUENTA ERA LA EQUIVOCADA, DOS VECES:

    1. Lo esperado se calculaba como «lo que habia antes mas lo que valide»,
       que supone que **cada mensaje validado es una fila nueva**. Eso es cierto
       la primera vez y solo la primera vez.
    2. Lo presente se contaba sobre **toda la fuente** ---`where source_type =
       'can_real_replay'`--- y no sobre los segmentos de esta carga. Con dos
       segmentos cargados, conciliar uno miraba los dos.

    La pregunta correcta no es «¿la base crecio tanto como mensajes lei?» sino
    «¿la base tiene lo que estos segmentos deben dejar?». Esa no depende de
    cuantas veces se cargaron.
    """

    def _conciliar(self, presente, esperado=57890, corridas=("can:reproducido:abc:1234",)):
        from unittest.mock import patch
        conexion = ConexionFalsa(presente)
        with patch.object(reproducir_can.db, "obtener_conexion", return_value=conexion):
            r = reproducir_can.conciliar(esperado, list(corridas), espera_maxima_s=0)
        return r, conexion

    def test_la_primera_carga_concilia(self):
        r, _ = self._conciliar(presente=57890)
        self.assertEqual(r["faltan"], 0)
        self.assertEqual(r["sobran"], 0)

    def test_EL_DEFECTO_volver_a_cargar_lo_mismo_sigue_conciliando(self):
        """La base no crece porque no debe crecer: ya tiene esas mediciones."""
        r, _ = self._conciliar(presente=57890, esperado=57890)
        self.assertEqual(r["faltan"], 0,
                         "una recarga idempotente se informa como perdida")

    def test_una_perdida_de_verdad_se_sigue_delatando(self):
        """Es para lo que existe esta conciliacion y no puede aflojarse.

        Se perdio el 63 % de una carga una vez, y la delato esto.
        """
        r, _ = self._conciliar(presente=21000, esperado=57890)
        self.assertEqual(r["faltan"], 36890)

    def test_LO_QUE_SOBRA_SE_DECLARA_APARTE_Y_NO_COMO_FALTANTE_NEGATIVO(self):
        """Mas filas de las que los segmentos deben dejar es otra cosa.

        Significa que la misma medicion entro con dos numeraciones distintas
        ---cargar el segmento 02 solo, despues de haberlo cargado junto al 01,
        le da otro `replay_seq` y por lo tanto otra identidad---. Llamarlo
        «faltan menos de cero» esconde un problema real detras de una resta.
        """
        r, _ = self._conciliar(presente=115780, esperado=57890)
        self.assertEqual(r["faltan"], 0)
        self.assertEqual(r["sobran"], 57890)

    def test_SE_CUENTA_POR_LAS_CORRIDAS_DE_ESTA_CARGA_Y_NO_POR_LA_FUENTE(self):
        """Contar toda la fuente mezcla esta carga con todo lo cargado antes."""
        _, conexion = self._conciliar(presente=57890,
                                      corridas=("can:reproducido:aa:1", "can:reproducido:bb:2"))
        sql, parametros = conexion.consultas[-1]
        self.assertIn("replay_run_id", sql)
        self.assertNotIn("source_type", sql)
        self.assertEqual(parametros, (["can:reproducido:aa:1", "can:reproducido:bb:2"],))

    def test_sin_corridas_no_se_inventa_una_conciliacion(self):
        """Sin saber que se cargo, no hay contra que comparar."""
        with self.assertRaises(ValueError):
            reproducir_can.conciliar(0, [], espera_maxima_s=0)
