# -*- coding: utf-8 -*-
"""Pruebas de las dos escalas de compuesto de neumatico.

Por que existen estas pruebas
-----------------------------
El paquete de estado del vehiculo trae dos campos de compuesto ---el visual y el
real--- y **los mismos codigos significan cosas distintas en cada uno**. La
confusion no falla: produce un nombre valido y equivocado.

Ocurrio. Un analisis del fin de semana de Spa aplico los nombres visuales al
campo real e informo **compuesto duro** donde la pantalla del juego mostraba
**M** de medio, y la equivocacion llego al informe. Lo detecto la validacion
contra video, no una prueba.

Estas pruebas fijan la distincion para que no vuelva a perderse en una tabla
suelta de un guion de analisis.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from scripts.analizar_carrera_f1_25 import (  # noqa: E402
    COMPUESTOS_REALES,
    COMPUESTOS_VISUALES,
)


class EscalasDeCompuestoTests(unittest.TestCase):
    """Las dos escalas existen, se distinguen, y no se pisan."""

    def test_el_codigo_18_significa_cosas_distintas(self):
        """Es el caso que delata la confusion y el que la produjo."""

        self.assertEqual(COMPUESTOS_VISUALES[18], "duro")
        self.assertEqual(COMPUESTOS_REALES[18], "C3")
        self.assertNotEqual(COMPUESTOS_VISUALES[18], COMPUESTOS_REALES[18])

    def test_la_escala_visual_solo_nombra_lo_que_la_pantalla_muestra(self):
        """Cinco nombres y ni uno mas.

        La version anterior incluia 20, 21 y 22 como blando, medio y duro. En la
        escala visual **esos codigos no existen**, y tenerlos invitaba a usar la
        tabla sobre el campo real, donde 20 es C1: el compuesto mas duro de la
        gama, nombrado como blando.
        """

        self.assertEqual(set(COMPUESTOS_VISUALES),
                         {16, 17, 18, 7, 8})
        self.assertEqual(sorted(COMPUESTOS_VISUALES.values()),
                         sorted(["blando", "medio", "duro",
                                 "intermedio", "lluvia"]))

    def test_la_escala_real_nombra_especificaciones_y_no_durezas(self):
        """Ningun nombre de la escala real es un nombre de dureza.

        Es lo que vuelve visible la confusion al leer una salida: si aparece
        `C3` nadie lo toma por una dureza, y si aparece `duro` sobre el campo
        real nadie lo nota.
        """

        durezas = {"blando", "medio", "duro"}
        secos = {c: n for c, n in COMPUESTOS_REALES.items() if c not in (7, 8)}
        self.assertTrue(secos)
        for nombre in secos.values():
            self.assertNotIn(nombre, durezas)
            self.assertRegex(nombre, r"^C[0-5]$")

    def test_los_compuestos_de_agua_comparten_codigo_en_las_dos_escalas(self):
        """Intermedio y lluvia son la excepcion, y conviene que este fijada.

        Que coincidan es lo que hizo que el analisis de la carrera bajo lluvia
        diera bien **por casualidad** mientras el del sprint en seco daba mal.
        """

        for codigo in (7, 8):
            self.assertEqual(COMPUESTOS_VISUALES[codigo],
                             COMPUESTOS_REALES[codigo])


if __name__ == "__main__":
    unittest.main()
