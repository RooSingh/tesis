# -*- coding: utf-8 -*-
"""El recorrido se reconstruye para las dos fuentes de bus, no solo para una.

QUE ES ESTO. La seccion 13.5 del informe ---«El recorrido sin coordenadas»---
resuelve que el bus de un vehiculo de calle no transmite posicion y que la
**forma** del recorrido si se recupera integrando lo que el vehiculo mide de si
mismo: «el rumbo es la integral de la velocidad de giro, y la posicion la
integral de la velocidad proyectada sobre ese rumbo». Hacen falta `speed` y
`yaw_rate`, y las cuatro ruedas para la comprobacion.

EL DEFECTO. `/can/recorrido/{session_id}` pedia esas series con la fuente
**escrita a mano**:

    db.obtener_series_de_senales(session_id, (...), can_rav4.SOURCE_TYPE, limite)

`can_rav4.SOURCE_TYPE` es `can_real_replay`. De modo que una sesion del
generador ---`can_simulated`, que emite exactamente esas seis señales---
contestaba `404: no tiene velocidad y guinada juntas`, cuando las tiene las dos.
Medido contra la Raspberry el 2026-09-13: el segmento real devolvia 2.999
puntos y la maniobra generada, 404.

Es la tercera vez en el dia que aparece la misma forma: un dato de la sesion
resuelto por una constante en lugar de por la sesion.

LO QUE NO SE TOCA, Y ESTAS PRUEBAS LO CUIDAN. El segmento real tiene que seguir
dando exactamente lo mismo. Se comprobo ademas fuera de las pruebas, contra la
Raspberry: 2.999 puntos, 1.795,6 m de recorrido y `sha256 1afd2fe11a536db2` del
cuerpo entero, antes y despues.

Y LAS OTRAS DOS FUENTES SIGUEN SIN ENTRAR AQUI, que no es una omision: F1 25 y
OpenF1 **publican posicion de verdad**. Integrar la suya seria reemplazar una
medicion por una derivacion, que es exactamente al reves de lo que hay que
hacer. Se las rechaza diciendo por que.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from fastapi import HTTPException  # noqa: E402

from backend import app as backend_app  # noqa: E402
from backend import recorrido  # noqa: E402


def series_de_una_curva(n: int = 400) -> dict:
    """Velocidad, guiñada y cuatro ruedas: lo que la reconstruccion necesita.

    La forma es la que declara `db.obtener_series_de_senales`:
    `dict[str, dict[float, float]]`, indexada por milisegundo desde la primera
    muestra. Se copia de ahi y no se inventa: la primera version de este arnes
    devolvia listas de pares y la reconstruccion fallaba con un
    `AttributeError` que no decia nada del defecto que se estaba probando.
    """

    import math
    series: dict = {n_: {} for n_ in ("speed", "yaw_rate") + recorrido.RUEDAS}
    for i in range(n):
        t = i * 20.0                       # 50 Hz, como emite el generador
        v = 80.0
        giro = 12.0 * math.sin(i / 60.0)   # una curva de ida y vuelta
        series["speed"][t] = v
        series["yaw_rate"][t] = giro
        for rueda in recorrido.RUEDAS:
            afuera = "right" in rueda
            series[rueda][t] = v + (0.4 if afuera else -0.4)
    return series


class LasDosFuentesDeBus(unittest.TestCase):

    def _pedir(self, session_id: str, fuente: str, series=None):
        """Llama al punto de acceso anotando con que fuente consulto la base."""

        consultado = {}

        def _series(sid, senales, source_type, limite):
            consultado["source_type"] = source_type
            return series if series is not None else {}

        pedidos_al_catalogo = []

        def _rango(sid, source_type):
            pedidos_al_catalogo.append(source_type)
            return None

        with patch.object(backend_app.db, "obtener_series_de_senales",
                          side_effect=_series), \
             patch.object(backend_app.catalogo_sesiones, "rango_de",
                          side_effect=_rango), \
             patch.object(backend_app.api_sesion, "_fuente_de",
                          return_value=fuente):
            try:
                respuesta = backend_app.can_recorrido(session_id)
            except HTTPException as fallo:
                return consultado, fallo
        consultado["catalogo"] = pedidos_al_catalogo
        return consultado, respuesta

    # ---- el defecto ----

    def test_una_maniobra_generada_se_consulta_como_lo_que_es(self) -> None:
        consultado, _ = self._pedir("can_sim:maniobra:demo_01", "can_simulated",
                                    series_de_una_curva())
        self.assertEqual(
            consultado["source_type"], "can_simulated",
            "se sigue pidiendo la serie con la fuente escrita a mano, de modo "
            "que una sesion generada nunca encuentra sus propias señales")

    def test_una_maniobra_generada_devuelve_su_recorrido(self) -> None:
        _, respuesta = self._pedir("can_sim:maniobra:demo_01", "can_simulated",
                                   series_de_una_curva())
        self.assertNotIsInstance(
            respuesta, HTTPException,
            "sigue contestando que no tiene velocidad y guiñada juntas, "
            "teniendo las dos")
        self.assertGreater(len(respuesta["puntos"]), 0)
        self.assertEqual(respuesta["naturaleza"], "derivado")

    # ---- lo que ya andaba ----

    def test_el_segmento_real_se_sigue_consultando_igual(self) -> None:
        """La pregunta que hay que responder antes de tocar nada."""

        consultado, respuesta = self._pedir(
            "can:segmento:sample_01", "can_real_replay", series_de_una_curva())
        self.assertEqual(consultado["source_type"], "can_real_replay")
        self.assertNotIsInstance(respuesta, HTTPException)
        self.assertGreater(len(respuesta["puntos"]), 0)

    def test_el_origen_temporal_tambien_se_pide_con_la_fuente_correcta(self) -> None:
        """La misma constante estaba escrita DOS veces en la misma funcion.

        `catalogo_sesiones.rango_de(session_id, can_rav4.SOURCE_TYPE)` es la
        segunda. Arreglar solo la primera habria dejado a la maniobra generada
        pasando la consulta de series y quedandose igual sin origen temporal,
        que es de las formas mas molestas de arreglar a medias.
        """

        consultado, _ = self._pedir("can_sim:maniobra:demo_01", "can_simulated",
                                    series_de_una_curva())
        self.assertEqual(consultado["catalogo"], ["can_simulated"])

    def test_sin_velocidad_o_sin_guinada_sigue_siendo_404(self) -> None:
        """La negativa util no se pierde en el arreglo."""

        solo_velocidad = {"speed": {0.0: 80.0}}
        _, fallo = self._pedir("can:segmento:sample_01", "can_real_replay",
                               solo_velocidad)
        self.assertIsInstance(fallo, HTTPException)
        self.assertEqual(fallo.status_code, 404)

    # ---- las que no entran, y por que ----

    def test_una_fuente_con_posicion_de_verdad_no_se_integra(self) -> None:
        """F1 25 y OpenF1 publican coordenadas: derivarlas seria empeorarlas."""

        for fuente in ("f1_25_udp_simulation", "openf1_historical_replay"):
            _, fallo = self._pedir("la_que_sea", fuente, series_de_una_curva())
            self.assertIsInstance(
                fallo, HTTPException,
                "%s entro a la reconstruccion por integracion, y publica "
                "posicion medida" % fuente)
            self.assertEqual(fallo.status_code, 422)
            self.assertIn("posicion", str(fallo.detail).lower())

    def test_la_negativa_dice_a_donde_ir(self) -> None:
        _, fallo = self._pedir("x", "openf1_historical_replay",
                               series_de_una_curva())
        self.assertIn("trazado", str(fallo.detail).lower(),
                      "la negativa no dice cual es la ruta que si corresponde")


if __name__ == "__main__":
    unittest.main()
