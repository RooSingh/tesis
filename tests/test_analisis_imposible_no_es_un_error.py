# -*- coding: utf-8 -*-
"""Que una fuente no sostenga un analisis es una respuesta, no una falla.

LA DISTINCION, QUE ES DEL TRABAJO Y NO DE LA INTERFAZ. El modulo de analisis
decide, herramienta por herramienta y fuente por fuente, si puede contestar. Un
bus de vehiculo de calle no recorre vueltas, de modo que «separar la sesion en
vueltas» sobre esa fuente es **imposible**, y decirlo con sus impedimentos es el
resultado correcto. Eso no es un error del servidor: es la herramienta
funcionando.

EL DEFECTO QUE ESTO CUIDA. `_correr` (`backend/api_analisis.py`) prometia
exactamente esa distincion en su docstring ---«llega al cliente como 422 con el
motivo, que es una respuesta y no un error del servidor»--- y a la vez atrapaba
**toda** excepcion para convertirla en 500. Las herramientas que declaran su
negativa devolviendo una estructura salian con 422; las que la declaran
levantando `SinVueltas` ---vueltas, degradacion y consistencia--- salian con 500.

MEDIDO el 2026-09-12 contra la API viva: `/analisis/openf1:session:9947/vueltas`,
`/degradacion` y `/consistencia` devolvian **500**, con un cuerpo que no era un
error sino el motivo bien escrito («separar una vuelta de la siguiente: la
interfaz publica no la expone en el flujo de telemetria»). Las mismas tres sobre
un segmento del bus, igual. `/frenadas` y `/traccion`, que declaran su negativa
por la otra via, devolvian 422.

Un 500 le dice a quien consulta «algo se rompio, reintenta»; un 422 le dice
«preguntaste algo que esta fuente no puede contestar, y aca esta por que». La
segunda es la unica cierta.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from fastapi import HTTPException  # noqa: E402

from backend import api_analisis  # noqa: E402
from backend.analisis.disponibilidad import Disponibilidad  # noqa: E402
from backend.analisis.vueltas import SinVueltas  # noqa: E402


def _imposible() -> Disponibilidad:
    return Disponibilidad(
        herramienta="vueltas_limpias",
        nombre="Separacion en vueltas",
        fuente="openf1_historical_replay",
        session_id="openf1:session:9947",
        estado="imposible",
        impedimentos=[
            "separar una vuelta de la siguiente: la interfaz publica no la "
            "expone en el flujo de telemetria",
            "descartar las vueltas que la sesion invalido: la interfaz publica "
            "no la expone",
        ],
    )


class UnaNegativaNoEsUnErrorDelServidorTests(unittest.TestCase):

    def test_sin_vueltas_sale_como_422_y_no_como_500(self) -> None:
        def herramienta():
            raise SinVueltas(_imposible())

        with self.assertRaises(HTTPException) as caja:
            api_analisis._correr(herramienta)
        self.assertEqual(
            caja.exception.status_code, 422,
            "una fuente que no sostiene el analisis sale como error del "
            "servidor: quien consulta no puede distinguirla de una caida")

    def test_la_respuesta_lleva_los_impedimentos_y_no_solo_un_texto(self) -> None:
        def herramienta():
            raise SinVueltas(_imposible())

        with self.assertRaises(HTTPException) as caja:
            api_analisis._correr(herramienta)
        detalle = caja.exception.detail
        self.assertIsInstance(
            detalle, dict,
            "el motivo llega como una cadena suelta y no como la estructura "
            "que la herramienta produjo")
        disponibilidad = detalle.get("disponibilidad", detalle)
        self.assertEqual(disponibilidad.get("estado"), "imposible")
        self.assertEqual(len(disponibilidad.get("impedimentos") or []), 2)
        self.assertIn("interfaz publica no la expone",
                      " ".join(disponibilidad["impedimentos"]))

    def test_un_fallo_de_verdad_sigue_siendo_un_500(self) -> None:
        """La distincion tiene que cortar para los dos lados."""

        def herramienta():
            raise RuntimeError("la conexion a la base se cayo")

        with self.assertRaises(HTTPException) as caja:
            api_analisis._correr(herramienta)
        self.assertEqual(caja.exception.status_code, 500)

    def test_una_herramienta_que_contesta_contesta(self) -> None:
        self.assertEqual(api_analisis._correr(lambda: {"vueltas": [1, 2]}),
                         {"vueltas": [1, 2]})


if __name__ == "__main__":
    unittest.main()
