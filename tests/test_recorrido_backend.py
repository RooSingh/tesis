# -*- coding: utf-8 -*-
"""El recorrido reconstruido, en el modulo que el tablero y el informe comparten.

Por que el modulo vive en el backend
------------------------------------
Lo usan dos consumidores ---el script que genera la figura del informe y el punto
de acceso que lo dibuja en el tablero--- y tenerlo en un solo lugar es lo que
evita que las dos versiones se separen y muestren recorridos distintos para el
mismo dato.

El defecto que estas pruebas cierran, y que solo aparecia en algunos datos
------------------------------------------------------------------------------
La comprobacion del giro contra las cuatro ruedas es geometrica y **supone las
ruedas girando**. Con el vehiculo detenido o casi, la diferencia entre ruedas es
ruido de cuantizacion mientras el sensor de guinada sigue informando.

Sin piso de velocidad, un segmento con paradas daba un ancho de via de **0,44
metros con correlacion 0,25**; con el piso da **1,55 metros con correlacion
0,99**. Un segmento que nunca se detuvo daba bien en los dos casos, de modo que
el defecto **solo se manifestaba en algunos datos**, que es la peor forma de que
se manifieste.
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from backend import recorrido  # noqa: E402


def _serie_en_curva(ancho_de_via: float, velocidad_kmh: float,
                    giro_deg_s: float, n: int = 200) -> dict:
    """Un vehiculo girando, con las cuatro ruedas coherentes con ese giro."""

    s: dict[str, dict[float, float]] = {"yaw_rate": {}, "speed": {}}
    for r in recorrido.RUEDAS:
        s[r] = {}
    for i in range(n):
        t = i * 10.0
        g = giro_deg_s if i % 2 else -giro_deg_s * 0.9
        s["yaw_rate"][t] = g
        s["speed"][t] = velocidad_kmh
        dif = math.radians(g) * ancho_de_via * 3.6
        s[recorrido.RUEDAS[0]][t] = velocidad_kmh - dif / 2
        s[recorrido.RUEDAS[2]][t] = velocidad_kmh - dif / 2
        s[recorrido.RUEDAS[1]][t] = velocidad_kmh + dif / 2
        s[recorrido.RUEDAS[3]][t] = velocidad_kmh + dif / 2
    return s


class LaComprobacionExigeElVehiculoEnMarcha(unittest.TestCase):

    def test_con_el_vehiculo_en_marcha_deduce_el_ancho_de_via(self):
        r = recorrido.validar_contra_ruedas(_serie_en_curva(1.6, 40.0, 20.0))
        self.assertAlmostEqual(r["ancho_de_via_m"], 1.6, delta=0.02)
        self.assertGreater(r["correlacion"], 0.99)

    def test_con_el_vehiculo_detenido_no_intenta_deducirlo(self):
        """Es el defecto: antes devolvia un ancho de via absurdo en vez de nada."""

        r = recorrido.validar_contra_ruedas(_serie_en_curva(1.6, 1.0, 20.0))
        self.assertEqual(r["muestras"], 0)

    def test_sin_giro_no_hay_de_donde_deducirlo(self):
        """En un tramo recto la diferencia entre ruedas es ruido.

        Que un segmento de autopista no permita deducir el ancho de via **es
        informacion**, no una falla: significa que el vehiculo iba derecho.
        """

        r = recorrido.validar_contra_ruedas(_serie_en_curva(1.6, 100.0, 0.1))
        self.assertEqual(r["muestras"], 0)

    def test_el_piso_de_velocidad_deja_pasar_la_circulacion_urbana(self):
        """Cinco por hora no descarta conduccion real, solo el vehiculo parado."""

        self.assertLessEqual(recorrido.VELOCIDAD_MINIMA_KMH, 10.0)

    def test_sin_muestras_devuelve_nan_y_no_cero(self):
        """Un cero se leeria como "el ancho de via es cero"."""

        r = recorrido.validar_contra_ruedas({})
        self.assertTrue(math.isnan(r["ancho_de_via_m"]))


class ReconstruyeLaForma(unittest.TestCase):

    def test_sin_giro_el_recorrido_es_recto(self):
        s = {"speed": {i * 50.0: 36.0 for i in range(41)},
             "yaw_rate": {i * 50.0: 0.0 for i in range(41)}}
        r = recorrido.reconstruir(s)
        self.assertAlmostEqual(r["recorrido_m"], 20.0, delta=0.6)
        self.assertLess(r["extension_y_m"], 0.01)

    def test_un_giro_constante_cierra_el_circulo(self):
        """Comprueba de una vez que rumbo y posicion usan la misma convencion."""

        paso, n = 10.0, 2000
        w_deg = 360.0 / (n * paso / 1000.0)
        s = {"speed": {i * paso: 36.0 for i in range(n + 1)},
             "yaw_rate": {i * paso: w_deg for i in range(n + 1)}}
        r = recorrido.reconstruir(s)
        cierre = math.hypot(r["x"][-1] - r["x"][0], r["y"][-1] - r["y"][0])
        self.assertLess(cierre, r["recorrido_m"] * 0.02)

    def test_la_guinada_se_interpreta_en_grados(self):
        """Es la unidad del catalogo. En radianes daria una recta, sin fallar."""

        s = {"speed": {i * 10.0: 36.0 for i in range(201)},
             "yaw_rate": {i * 10.0: 90.0 for i in range(201)}}
        r = recorrido.reconstruir(s)
        self.assertGreater(abs(r["rumbo_final_deg"]), 100.0)

    def test_no_integra_sobre_huecos_grandes(self):
        s = {"speed": {0.0: 36.0, 50.0: 36.0, 90_000.0: 36.0},
             "yaw_rate": {0.0: 0.0, 50.0: 0.0, 90_000.0: 0.0}}
        r = recorrido.reconstruir(s)
        self.assertGreaterEqual(r["huecos_saltados"], 1)

    def test_sin_datos_no_inventa_recorrido(self):
        r = recorrido.reconstruir({})
        self.assertEqual(r["recorrido_m"], 0.0)
        self.assertEqual(r["puntos"], 1)


class ElPuntoDeAccesoDeclaraQueEsDerivado(unittest.TestCase):
    """Quien consuma la respuesta tiene que saberlo sin leer documentacion."""

    def test_la_respuesta_declara_su_naturaleza(self):
        fuente = (RAIZ / "backend" / "app.py").read_text(encoding="utf-8")
        i = fuente.index("def can_recorrido")
        cuerpo = fuente[i:i + 3000]
        self.assertIn('"naturaleza": "derivado"', cuerpo)

    def test_la_respuesta_lleva_la_advertencia(self):
        fuente = (RAIZ / "backend" / "app.py").read_text(encoding="utf-8")
        i = fuente.index("def can_recorrido")
        cuerpo = fuente[i:i + 3000]
        self.assertIn("advertencia", cuerpo)

    def test_devuelve_la_comprobacion_junto_con_el_recorrido(self):
        """El recorrido sin su validacion es un dibujo sin respaldo."""

        fuente = (RAIZ / "backend" / "app.py").read_text(encoding="utf-8")
        i = fuente.index("def can_recorrido")
        cuerpo = fuente[i:i + 3000]
        self.assertIn("validacion_guinada", cuerpo)

    def test_una_sesion_sin_las_dos_senales_no_devuelve_un_recorrido_vacio(self):
        """Devolver cero metros dejaria creer que el vehiculo no se movio."""

        fuente = (RAIZ / "backend" / "app.py").read_text(encoding="utf-8")
        i = fuente.index("def can_recorrido")
        cuerpo = fuente[i:i + 3000]
        self.assertIn("status_code=404", cuerpo)


if __name__ == "__main__":
    unittest.main()
