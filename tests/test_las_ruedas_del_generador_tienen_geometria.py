# -*- coding: utf-8 -*-
"""La diferencia entre ruedas sale de una geometria, no de un factor a ojo.

QUE COMPRUEBA EL INFORME CON ESTO. La seccion 13.5 valida la señal de guiñada
del bus real por una via independiente: en una curva las ruedas de afuera
recorren mas que las de adentro, y **esa diferencia dividida por la velocidad de
giro da el ancho de via del vehiculo**. Sobre tres segmentos converge en 1,564,
1,606 y 1,545 metros, con correlaciones de +0,970, +0,997 y +0,986.

    «Que dos señales decodificadas por separado coincidan en una dimension
    fisica del automovil es la comprobacion mas fuerte disponible de que ambas
    estan bien decodificadas, con la escala y las unidades correctas.»

EL DEFECTO, MEDIDO el 2026-09-13. Corrida la maniobra generada contra ese mismo
validador, el ancho de via daba **0,93 m** ---un vehiculo imposible--- con
correlacion 0,95. No fallaba el validador: fallaba el generador. Sus ruedas
eran decorativas:

    wheel_speed_fl = base - steer_angle * 0.02      # un factor a ojo
    wheel_speed_rl = base - accel_x * 0.05          # y este ni siquiera es lateral

Las delanteras se separaban por el angulo de direccion con un coeficiente
inventado, y **las traseras por la aceleracion longitudinal**, que no tiene
ninguna relacion con la diferencia entre izquierda y derecha. El comentario lo
decia sin darse cuenta: «se introducen pequeñas diferencias para reflejar una
telemetria mas util y menos artificialmente uniforme». Servian para que la
serie no fuera plana, no para significar algo.

POR QUE IMPORTA MAS DE LO QUE PARECE. El capitulo 8 declara al generador una
«simulacion controlada con ajuste cualitativo», y eso permite que un coeficiente
no este calibrado. Lo que no permite es que una señal **contradiga** a otra: si
la guiñada y las ruedas del mismo vehiculo simulado no coinciden en su ancho de
via, entonces una de las dos esta mal, y la demostracion del metodo de la
seccion 13.5 sobre la fuente simulada no prueba nada.

LO QUE SE ADOPTA. La relacion es geometria pura y no necesita calibrarse:

    diferencia entre lados [m/s] = velocidad de giro [rad/s] x ancho de via [m]

El ancho se declara una vez, con su procedencia, y las cuatro ruedas se derivan
de el. Deja de ser un adorno y pasa a ser una afirmacion comprobable ---por el
mismo validador que el informe usa sobre el bus real---.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from backend import recorrido  # noqa: E402
from tests.ayuda_estructural import solo_codigo  # noqa: E402
from telemetry_generator import signals  # noqa: E402
from telemetry_generator.main import crear_estado_inicial  # noqa: E402

#: El rango que el informe midio sobre el vehiculo real (seccion 13.5).
ANCHO_MEDIDO_MIN, ANCHO_MEDIDO_MAX = 1.545, 1.606


def maniobra_completa(paso_ms: int = 10) -> dict:
    """Las series que deja la maniobra, en la forma que pide el validador."""

    estado = crear_estado_inicial()
    series: dict = {n: {} for n in ("speed", "yaw_rate") + recorrido.RUEDAS}
    t = 0
    while t < 60_000:
        signals.aplicar_escenario_demostrativo(estado, t)
        signals.actualizar_estado_basico(estado, paso_ms)
        series["speed"][float(t)] = estado.speed
        series["yaw_rate"][float(t)] = estado.yaw_rate
        series["wheel_speed_front_left"][float(t)] = estado.wheel_speed_fl
        series["wheel_speed_front_right"][float(t)] = estado.wheel_speed_fr
        series["wheel_speed_rear_left"][float(t)] = estado.wheel_speed_rl
        series["wheel_speed_rear_right"][float(t)] = estado.wheel_speed_rr
        t += paso_ms
    return series


class ElAnchoDeViaEmerge(unittest.TestCase):
    """Se corre **el mismo validador** que el informe aplica al bus real."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.validacion = recorrido.validar_contra_ruedas(maniobra_completa())

    def test_el_ancho_de_via_cae_en_el_rango_que_el_informe_midio(self) -> None:
        ancho = self.validacion["ancho_de_via_m"]
        self.assertIsNotNone(ancho, "el validador no pudo deducir nada")
        self.assertTrue(
            ANCHO_MEDIDO_MIN <= ancho <= ANCHO_MEDIDO_MAX,
            "el ancho de via deducido es %.2f m, fuera del rango %.3f-%.3f que "
            "la seccion 13.5 midio sobre el vehiculo real. Antes daba 0,93: un "
            "vehiculo imposible." % (ancho, ANCHO_MEDIDO_MIN, ANCHO_MEDIDO_MAX))

    def test_la_correlacion_es_la_de_una_relacion_geometrica(self) -> None:
        """Sobre el bus real da entre +0,970 y +0,997. Aqui, siendo exacta, ~1."""

        r = self.validacion["correlacion"]
        self.assertIsNotNone(r)
        self.assertGreater(
            r, 0.999,
            "la correlacion es %.4f: la diferencia entre ruedas todavia lleva "
            "algo que no es la guiñada" % r)

    def test_hay_muestras_suficientes_para_que_signifique_algo(self) -> None:
        self.assertGreater(self.validacion["muestras"], 500)


class LaGeometriaSeSostieneEnCadaInstante(unittest.TestCase):

    def _estado_en(self, ms: int):
        estado = crear_estado_inicial()
        t = 0
        while t <= ms:
            signals.aplicar_escenario_demostrativo(estado, t)
            signals.actualizar_estado_basico(estado, 10)
            t += 10
        return estado

    def test_en_recta_las_cuatro_ruedas_van_a_la_velocidad_del_vehiculo(self) -> None:
        """Sin giro no hay diferencia que inventar."""

        e = self._estado_en(5_000)                  # recta de entrada
        for rueda in ("wheel_speed_fl", "wheel_speed_fr",
                      "wheel_speed_rl", "wheel_speed_rr"):
            self.assertAlmostEqual(
                getattr(e, rueda), e.speed, delta=0.01,
                msg="%s se aparta de la velocidad con el vehiculo derecho" % rueda)

    def test_en_curva_las_de_afuera_van_mas_rapido(self) -> None:
        e = self._estado_en(30_000)                 # apice, girando
        self.assertGreater(abs(e.yaw_rate), 1.0, "no hay giro en el apice")
        afuera = e.wheel_speed_fr if e.yaw_rate > 0 else e.wheel_speed_fl
        adentro = e.wheel_speed_fl if e.yaw_rate > 0 else e.wheel_speed_fr
        self.assertGreater(
            afuera, adentro,
            "las ruedas de afuera no van mas rapido que las de adentro")

    def test_los_dos_ejes_se_separan_igual(self) -> None:
        """Un mismo vehiculo tiene un solo ancho de via en este modelo."""

        e = self._estado_en(30_000)
        delante = e.wheel_speed_fr - e.wheel_speed_fl
        detras = e.wheel_speed_rr - e.wheel_speed_rl
        self.assertAlmostEqual(
            delante, detras, delta=0.01,
            msg="los ejes se separan distinto (%.3f contra %.3f): antes el "
                "trasero seguia a la aceleracion longitudinal, que no es una "
                "diferencia lateral" % (delante, detras))

    def test_la_diferencia_ya_no_depende_de_la_aceleracion_longitudinal(self) -> None:
        """El defecto exacto que tenia el eje trasero."""

        cuerpo = solo_codigo(
            RAIZ / "telemetry_generator" / "signals.py").split("wheel_speed_fl =")[1]
        self.assertNotIn(
            "accel_x", cuerpo,
            "la velocidad de una rueda sigue calculandose con la aceleracion "
            "longitudinal")

    def test_el_ancho_declarado_esta_en_el_rango_del_informe(self) -> None:
        self.assertTrue(
            ANCHO_MEDIDO_MIN <= signals.ANCHO_DE_VIA_M <= ANCHO_MEDIDO_MAX,
            "el ancho declarado (%s) no es el de un vehiculo como el del "
            "capitulo 7" % signals.ANCHO_DE_VIA_M)


if __name__ == "__main__":
    unittest.main()
