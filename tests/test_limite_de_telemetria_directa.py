# -*- coding: utf-8 -*-
"""Un limite fuera de rango se rechaza, tambien en las rutas directas.

LA PROPIEDAD QUE ESTO DEFIENDE. La interfaz de consulta declara dos reglas que
valen para todas sus familias: **ninguna respuesta se recorta en silencio**, y
**un limite fuera de rango se rechaza** en lugar de acomodarse. Las dos son la
misma idea: quien pregunta tiene que poder saber si lo que recibio es todo.

EL DEFECTO QUE ESTO CUIDA. `_validar_limite` existe desde hace tiempo
(`backend/app.py`) y lo llaman las rutas de reinyeccion, de vuelta y de tanda.
Las cuatro rutas de telemetria directa ---`/telemetry/latest`,
`/telemetry/by-signal/{senal}`, `/telemetry/latest-by-signal` y
`/telemetry/by-session/{sesion}`--- no lo llamaban.

MEDIDO el 2026-09-12 contra la API viva, antes del arreglo:

    GET /telemetry/latest?limit=-5                  -> 500
    GET /telemetry/latest?limit=0                   -> 200, lista vacia
    GET /telemetry/by-signal/speed?limit=500000     -> 200, sin marca de recorte
    GET /telemetry/by-session/...?limit=-1          -> 500

Un 500 por un limite negativo dice «el servidor se rompio» cuando lo que paso es
que la pregunta estaba mal formada; y un 200 con lista vacia por `limit=0` dice
«no hay datos» sobre una tabla de siete millones de filas. Las dos respuestas son
falsas de distinta manera.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from fastapi import HTTPException  # noqa: E402

from backend import app as modulo_app  # noqa: E402

#: Las cuatro rutas, con el nombre del parametro y como se la invoca.
RUTAS_DIRECTAS = (
    ("telemetry_latest", lambda limite: modulo_app.telemetry_latest(limit=limite)),
    ("telemetry_by_signal",
     lambda limite: modulo_app.telemetry_by_signal("speed", limit=limite)),
    ("telemetry_by_session",
     lambda limite: modulo_app.telemetry_by_session("openf1:session:9947",
                                                    limit=limite)),
)

FUERA_DE_RANGO = (0, -1, -5, modulo_app.LIMITE_MUESTRAS_MAXIMO + 1, 500000)


class UnLimiteFueraDeRangoSeRechazaTests(unittest.TestCase):

    def test_las_rutas_directas_rechazan_el_limite_fuera_de_rango(self) -> None:
        for nombre, llamar in RUTAS_DIRECTAS:
            for limite in FUERA_DE_RANGO:
                with self.subTest(ruta=nombre, limite=limite):
                    with self.assertRaises(HTTPException) as caja:
                        llamar(limite)
                    self.assertEqual(
                        caja.exception.status_code, 400,
                        "%s con limite=%d no lo rechaza con 400: la pregunta "
                        "mal formada se confunde con una falla del servidor o "
                        "con una tabla vacia" % (nombre, limite))

    def test_el_mensaje_dice_cual_es_el_rango(self) -> None:
        with self.assertRaises(HTTPException) as caja:
            modulo_app.telemetry_latest(limit=-1)
        self.assertIn(str(modulo_app.LIMITE_MUESTRAS_MAXIMO),
                      str(caja.exception.detail))

    def test_el_validador_acepta_los_extremos_validos(self) -> None:
        modulo_app._validar_limite(1)
        modulo_app._validar_limite(modulo_app.LIMITE_MUESTRAS_MAXIMO)


if __name__ == "__main__":
    unittest.main()
