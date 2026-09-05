# -*- coding: utf-8 -*-
"""Pruebas de los dos paquetes que cierran una sesion.

Juegos de neumaticos y clasificacion final son los ultimos dos tipos emitidos
que faltaba decodificar. Los dos describen **hechos cerrados** y no un instante,
como el historial de sesion, y por eso comparten una debilidad: al construir el
datagrama de prueba con las mismas cadenas de formato que el decodificador, un
error en la cadena se cancelaria consigo mismo.

Lo que rompe esa circularidad son las pruebas del primer grupo, que contrastan
contra **231 y 1042**. Esos numeros salen de la especificacion de EA, no de este
codigo.

Y lo que rompe la otra mitad ---que el tamano cierre y los campos signifiquen
otra cosa--- son las pruebas del segundo grupo, que fijan las dos equivocaciones
que efectivamente ocurrieron al escribir estos decodificadores:

1. **el indice del juego montado se leyo antes del arreglo y va despues.** El
   tamano seguia cerrando en 231 exactos y los valores eran legibles: compuestos
   55 y 20, y un juego con 248 vueltas restantes sobre un maximo de 7;
2. **los tres arreglos de tandas se corrieron un byte.** Ese si fallo, porque el
   ultimo se salia del rango, que es la unica clase de error comoda de encontrar.
"""

from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from backend import f1_udp  # noqa: E402
from tests.test_f1_udp import _cabecera  # noqa: E402


class TamanoDeclaradoTests(unittest.TestCase):
    """Anclado en la especificacion, no en este codigo."""

    def test_juegos_de_neumaticos_cierra_en_231(self):
        self.assertEqual(f1_udp.TYRE_SET_TAMANO, 10)
        total = (f1_udp.CABECERA_TAMANO + 1
                 + f1_udp.TYRE_SETS_MAXIMO * f1_udp.TYRE_SET_TAMANO + 1)
        self.assertEqual(total, 231)
        self.assertEqual(f1_udp.PAQUETES[12]["tamano"], 231)

    def test_clasificacion_final_cierra_en_1042(self):
        self.assertEqual(f1_udp.FINAL_CLASSIFICATION_TAMANO, 46)
        total = (f1_udp.CABECERA_TAMANO + 1
                 + f1_udp.VEHICULOS * f1_udp.FINAL_CLASSIFICATION_TAMANO)
        self.assertEqual(total, 1042)
        self.assertEqual(f1_udp.PAQUETES[8]["tamano"], 1042)


def _juegos(car_idx: int = 3, montado: int = 2) -> bytes:
    """Un paquete de juegos de neumaticos con cada juego distinguible."""

    cuerpo = b""
    for i in range(f1_udp.TYRE_SETS_MAXIMO):
        cuerpo += struct.pack(
            f1_udp.TYRE_SET_FMT,
            16 + (i % 3),   # compuesto real
            16 + (i % 3),   # compuesto visual
            i,              # desgaste
            1 if i % 2 == 0 else 0,   # disponible
            5,              # recomendado para
            20 - i,         # vueltas restantes
            20,             # vida util maxima
            -100 + i,       # delta por vuelta, con signo
            1 if i == montado else 0,
        )
    return (_cabecera(12) + struct.pack("<B", car_idx) + cuerpo
            + struct.pack("<B", montado))


class JuegosDeNeumaticosTests(unittest.TestCase):

    def setUp(self):
        self.d = f1_udp.decodificar(_juegos())["juegos_de_neumaticos"]

    def test_el_indice_montado_se_lee_despues_del_arreglo(self):
        """La equivocacion que el tamano no detectaba.

        Leerlo antes corria el arreglo entero un byte y devolvia compuestos que
        no existen. Aca el primer juego tiene compuesto 16 y desgaste 0, y si el
        arreglo estuviera corrido no coincidirian.
        """

        self.assertEqual(self.d["montado_indice"], 2)
        self.assertEqual(self.d["juegos"][0]["compuesto_real"], 16)
        self.assertEqual(self.d["juegos"][0]["wear_pct"], 0)

    def test_el_juego_montado_se_expone_resuelto(self):
        """Buscarlo por indice en cada consumidor invita a equivocarse."""

        self.assertIsNotNone(self.d["montado_actual"])
        self.assertTrue(self.d["montado_actual"]["montado"])
        self.assertEqual(self.d["montado_actual"], self.d["juegos"][2])

    def test_las_vueltas_restantes_nunca_superan_el_maximo(self):
        """La comprobacion que delato los dos campos de vida intercambiados.

        Un juego con mas vueltas restantes que su maximo recomendado es
        imposible, y era lo que devolvia la version anterior.
        """

        for juego in self.d["juegos"]:
            with self.subTest(indice=juego["indice"]):
                self.assertLessEqual(juego["vueltas_restantes"],
                                     juego["vida_util_maxima_vueltas"])

    def test_la_disponibilidad_se_nombra_y_no_queda_en_entero(self):
        """Un cero aca significa consumido o no permitido, no "cero"."""

        self.assertIs(self.d["juegos"][0]["disponible"], True)
        self.assertIs(self.d["juegos"][1]["disponible"], False)

    def test_el_delta_por_vuelta_admite_signo(self):
        """La especificacion lo declara entero con signo y hay que respetarlo."""

        self.assertEqual(self.d["juegos"][0]["delta_por_vuelta_ms"], -100)

    def test_hay_veinte_juegos(self):
        self.assertEqual(len(self.d["juegos"]), 20)


def _clasificacion(num_cars: int = 20) -> bytes:
    """Una clasificacion donde cada vehiculo es distinguible por su posicion."""

    cuerpo = b""
    for i in range(f1_udp.VEHICULOS):
        cuerpo += struct.pack(
            f1_udp.FINAL_CLASSIFICATION_FMT,
            i + 1,          # posicion
            13,             # vueltas
            i,              # grid, que empieza en cero
            25 - i if i < 10 else 0,   # puntos
            1,              # paradas
            3,              # estado: termino
            3,              # motivo
            97822 + i,      # mejor vuelta en ms
            1354.6 + i,     # tiempo total
            0,              # segundos de penalizacion
            0,              # cantidad de penalizaciones
            2,              # cantidad de tandas
            16, 17, 0, 0, 0, 0, 0, 0,   # compuestos reales
            16, 17, 0, 0, 0, 0, 0, 0,   # compuestos visuales
            6, 255, 0, 0, 0, 0, 0, 0,   # vuelta final de cada tanda
        )
    return _cabecera(8) + struct.pack("<B", num_cars) + cuerpo


class ClasificacionFinalTests(unittest.TestCase):

    def setUp(self):
        self.d = f1_udp.decodificar(_clasificacion())["clasificacion"]

    def test_los_arreglos_de_tandas_arrancan_donde_corresponde(self):
        """La equivocacion que corrio los tres arreglos un byte.

        Se recorta a `num_tyre_stints`, de modo que un corrimiento no solo
        cambia los valores: cambia cuantas tandas se creen que hubo.
        """

        v = self.d["vehiculos"][0]
        self.assertEqual(v["num_tyre_stints"], 2)
        self.assertEqual(len(v["tandas"]), 2)
        self.assertEqual([t["compuesto_visual"] for t in v["tandas"]], [16, 17])
        self.assertEqual([t["vuelta_final"] for t in v["tandas"]], [6, 255])

    def test_el_tiempo_total_es_de_doble_precision(self):
        """Truncarlo a entero perderia la fraccion que separa dos vehiculos."""

        self.assertAlmostEqual(self.d["vehiculos"][0]["total_race_time_s"],
                               1354.6, places=3)

    def test_la_posicion_de_partida_empieza_en_cero(self):
        """Comprobado sobre ochenta observaciones de cuatro capturas reales.

        Se fija en una prueba porque compararlo de frente contra la posicion da
        un puesto de diferencia, y ya produjo una discrepancia aparente.
        """

        v = self.d["vehiculos"][0]
        self.assertEqual(v["position"], 1)
        self.assertEqual(v["grid_position"], 0)

    def test_el_estado_se_nombra_y_el_motivo_no(self):
        """El motivo queda crudo porque su significado no esta determinado.

        Sobre 442 vehiculos de todas las capturas vale siempre lo mismo que el
        estado, y con esa evidencia nombrarlo seria inventar.
        """

        v = self.d["vehiculos"][0]
        self.assertEqual(v["result_status_nombre"], "termino")
        self.assertEqual(v["result_reason"], 3)
        self.assertNotIn("result_reason_nombre", v)

    def test_estan_los_veintidos_lugares_aunque_corran_veinte(self):
        """El arreglo es por indice de vehiculo, no por cantidad en carrera."""

        self.assertEqual(self.d["num_cars"], 20)
        self.assertEqual(len(self.d["vehiculos"]), 22)


if __name__ == "__main__":
    unittest.main()
