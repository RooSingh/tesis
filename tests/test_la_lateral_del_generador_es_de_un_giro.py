# -*- coding: utf-8 -*-
"""La aceleracion lateral sale del giro, y no de un factor sobre el volante.

EL DEFECTO, MEDIDO POR UN TERCERO. El generador calculaba asi sus dos canales
laterales:

    estado.yaw_rate = estado.steer_angle * 0.35
    estado.accel_y  = estado.steer_angle * 0.08

**Las dos proporcionales al mismo volante**, de modo que su cociente es una
constante. Y la fisica dice otra cosa: en un giro plano la aceleracion lateral
es el producto de la velocidad por la velocidad de giro, `a = v * omega`, de
modo que `a / omega` **es la velocidad** y tiene que variar con ella.

Medido sobre la maniobra completa: el cociente se mueve entre 0,204 y 0,399
sobre 4.413 pasos ---lo poco que varia es el redondeo--- y equivale a un
vehiculo circulando a **47,1 km/h fijos**, mientras la maniobra va de 100 a 231.

POR QUE NO ES UN COEFICIENTE SIN CALIBRAR, QUE SI ESTARIA PERMITIDO. El capitulo
8 declara al generador una «simulacion controlada con ajuste cualitativo», y eso
permite que un parametro no este calibrado. Pero **el capitulo 7 usa esta misma
relacion para confirmar la escala del acelerometro de la captura real**:

> «En un giro plano la aceleración lateral es el producto de la velocidad por la
> velocidad de giro»

Con la lateral y la guiñada del generador proporcionales entre si, esa
comprobacion **no se puede demostrar sobre la fuente simulada**: da siempre el
mismo cociente, y el resultado seria una velocidad constante que el vehiculo no
tiene. Es el mismo caso que tenian las ruedas antes del 2026-09-13, cuando el
validador del capitulo 13 deducia un ancho de via de 0,93 m.

Una señal que contradice a otra del mismo vehiculo no es una simulacion
cualitativa: es un error.

CONSECUENCIA PARA EL INFORME. La tabla 8.2 publica `accel_y` en el rango
-0,240 a 1,760 m/s². Con la relacion correcta ese rango pasa a ser -0,793 a
4,535.
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from telemetry_generator import signals  # noqa: E402
from telemetry_generator.main import crear_estado_inicial  # noqa: E402

#: Debajo de este giro la relacion no dice nada: el cociente de dos numeros
#: chicos es ruido, y es el mismo criterio que usa `recorrido.py` para el ancho
#: de via.
GIRO_MINIMO_DEG_S = 0.5


def la_maniobra(paso_ms: int = 10):
    """Cada paso de la maniobra, con lo que hace falta para la comprobacion."""

    estado = crear_estado_inicial()
    t = 0
    while t < 60_000:
        signals.aplicar_escenario_demostrativo(estado, t)
        signals.actualizar_estado_basico(estado, paso_ms)
        yield t / 1000.0, estado.speed, estado.yaw_rate, estado.accel_y
        t += paso_ms


class LaLateralSaleDelGiro(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.pasos = list(la_maniobra())

    def test_la_lateral_es_la_velocidad_por_la_guinada(self) -> None:
        """La relacion del capitulo 7, comprobada paso por paso."""

        peor = (0.0, None)
        for t, v, giro, lateral in self.pasos:
            esperada = (v / 3.6) * math.radians(giro)
            error = abs(lateral - esperada)
            if error > peor[0]:
                peor = (error, (t, v, giro, lateral, esperada))
        self.assertLess(
            peor[0], 1e-9,
            "la lateral no es v * omega. El peor caso es a los %.2f s: con "
            "%.2f km/h y %.3f deg/s, publica %.4f y la relacion da %.4f"
            % ((peor[1][0], peor[1][1], peor[1][2], peor[1][3], peor[1][4])
               if peor[1] else (0, 0, 0, 0, 0)))

    def test_el_cociente_deja_de_ser_una_constante(self) -> None:
        """Era 47,1 km/h fijos mientras la maniobra iba de 100 a 231."""

        implicitas = [lateral / math.radians(giro) * 3.6
                      for _t, _v, giro, lateral in self.pasos
                      if abs(giro) >= GIRO_MINIMO_DEG_S]
        self.assertGreater(len(implicitas), 1000, "no hay giro que medir")
        ancho = max(implicitas) - min(implicitas)
        self.assertGreater(
            ancho, 50.0,
            "la velocidad implicita en el cociente se mueve solo %.1f km/h: "
            "sigue siendo practicamente constante" % ancho)

    def test_la_velocidad_implicita_es_la_velocidad_de_verdad(self) -> None:
        """Y no cualquier rango: tiene que dar **la** velocidad del vehiculo."""

        for t, v, giro, lateral in self.pasos:
            if abs(giro) < GIRO_MINIMO_DEG_S:
                continue
            implicita = lateral / math.radians(giro) * 3.6
            self.assertAlmostEqual(
                implicita, v, delta=0.01,
                msg="a los %.2f s el cociente implica %.1f km/h y el vehiculo "
                    "va a %.1f" % (t, implicita, v))

    def test_sin_giro_no_hay_lateral(self) -> None:
        for t, _v, giro, lateral in self.pasos:
            if abs(giro) < 1e-9:
                self.assertAlmostEqual(
                    lateral, 0.0, delta=1e-9,
                    msg="a los %.2f s no hay giro y si hay lateral" % t)

    def test_el_signo_acompana_al_giro(self) -> None:
        for t, _v, giro, lateral in self.pasos:
            if abs(giro) >= GIRO_MINIMO_DEG_S:
                self.assertEqual(
                    lateral > 0, giro > 0,
                    "a los %.2f s el giro y la lateral tienen signos "
                    "distintos" % t)

    def test_la_guinada_no_se_toco(self) -> None:
        """El arreglo es de la lateral. La guiñada ya estaba bien declarada."""

        e = crear_estado_inicial()
        signals.aplicar_escenario_demostrativo(e, 30_000)
        signals.actualizar_estado_basico(e, 10)
        self.assertAlmostEqual(e.yaw_rate, e.steer_angle * 0.35, delta=1e-9)


class ElRangoQueElInformePublica(unittest.TestCase):
    """La tabla 8.2 publica un rango de `accel_y`, y este cambio lo mueve."""

    def test_el_rango_nuevo_es_el_que_hay_que_llevar_al_informe(self) -> None:
        laterales = [lateral for _t, _v, _g, lateral in la_maniobra()]
        self.assertAlmostEqual(min(laterales), -0.793, delta=0.01)
        self.assertAlmostEqual(max(laterales), 4.535, delta=0.01)


if __name__ == "__main__":
    unittest.main()
