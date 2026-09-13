# -*- coding: utf-8 -*-
"""El generador publica los nombres del contrato, no los crudos del bus.

EL DEFECTO, VISTO EN PANTALLA el 2026-09-13. La maniobra generada se abrio en
el tablero con las ruedas y las aceleraciones vacias, mientras velocidad,
direccion y guiñada si aparecian. Cinco de doce andaban y siete no.

LA CAUSA. `adapters/can_rav4.py` lleva un mapa que traduce **el nombre crudo
del bus al nombre canonico del contrato interno**:

    "wheel_speed_fl": ("wheel_speed_front_left", "km/h"),
    "accel_x":        ("accel_longitudinal", "m/s^2"),
    "accel_y":        ("accel_lateral", "m/s^2"),

El generador emitia los de la **izquierda** ---los crudos--- y nunca cruzaba
esa traduccion. Por eso el tablero pedia `wheel_speed_front_left` y encontraba
`wheel_speed_fl`. Las cinco que funcionaban eran justamente las que se llaman
igual de los dos lados: `speed`, `steer_angle`, `yaw_rate`, `brake_pressed` y
`gas_pressed`.

NO HAY CONTRADICCION CON EL INFORME, y conviene decirlo porque la primera
lectura asusta: la seccion 7.3 y la tabla A.1 usan `accel_x` y `wheel_speeds`
porque describen **el analisis del bus**, no el contrato interno. Los dos
nombres son correctos en su sitio; lo que faltaba era el paso entre uno y otro.

POR QUE SE REUSA EL MAPA Y NO SE COPIA. Es la regla que el propio proyecto
escribio en ese archivo: «dos nombres para la misma medida terminarian en
desacuerdo». Copiar la tabla aqui crearia un segundo lugar donde decidir como
se llama una rueda, y el dia que el adaptador cambie uno, el generador seguiria
publicando el viejo sin que nadie se entere.

Y LA UNIDAD VIAJA CON EL NOMBRE. El generador declaraba `m/s2` y el adaptador
`m/s^2` para la misma magnitud. Son la misma familia de defecto: dos sitios
decidiendo lo mismo. Al tomar el mapa entero, la unidad deja de ser una segunda
decision.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from adapters import can_rav4  # noqa: E402
from telemetry_generator import config as gen_config  # noqa: E402
from tests.ayuda_estructural import solo_codigo  # noqa: E402
from telemetry_generator import message_builder as mb  # noqa: E402
from telemetry_generator.main import crear_estado_inicial  # noqa: E402
from telemetry_generator.signals import (  # noqa: E402
    actualizar_estado_basico, aplicar_escenario_demostrativo)

#: Las que en el bus real se llaman igual crudas que canonicas. Son las cinco
#: que ya funcionaban, y sirven para comprobar que el cambio no las movio.
YA_COINCIDIAN = {"speed", "steer_angle", "yaw_rate", "brake_pressed", "gas_pressed"}


def un_mensaje(nombre: str) -> dict:
    estado = crear_estado_inicial()
    aplicar_escenario_demostrativo(estado, 0)
    actualizar_estado_basico(estado, 10)
    return mb.construir_mensaje_senal(estado, nombre)


class LosNombresSonLosDelContrato(unittest.TestCase):

    def _emitidos(self) -> set[str]:
        return {un_mensaje(s["signal_name"])["signal_name"]
                for s in gen_config.MVP_SIGNALS}

    # ---- el caso visto en pantalla ----

    def test_las_ruedas_salen_con_el_nombre_que_el_tablero_pide(self) -> None:
        emitidos = self._emitidos()
        for canonico in ("wheel_speed_front_left", "wheel_speed_front_right",
                         "wheel_speed_rear_left", "wheel_speed_rear_right"):
            self.assertIn(
                canonico, emitidos,
                "la rueda sigue saliendo con el nombre crudo del bus: el panel "
                "pide %r y no lo encuentra" % canonico)

    def test_las_aceleraciones_tambien(self) -> None:
        emitidos = self._emitidos()
        self.assertIn("accel_longitudinal", emitidos)
        self.assertIn("accel_lateral", emitidos)

    def test_ya_no_sale_ningun_nombre_crudo(self) -> None:
        emitidos = self._emitidos()
        crudos = {c for c in can_rav4.SENALES
                  if can_rav4.SENALES[c][0] != c} & emitidos
        self.assertEqual(
            crudos, set(),
            "siguen saliendo nombres crudos del bus: %r" % crudos)

    def test_las_cinco_que_ya_coincidian_no_se_movieron(self) -> None:
        """Un arreglo que cambia lo que ya andaba no es un arreglo."""

        emitidos = self._emitidos()
        for n in YA_COINCIDIAN:
            self.assertIn(n, emitidos, "se perdio %r, que ya funcionaba" % n)

    def test_siguen_siendo_doce(self) -> None:
        self.assertEqual(len(self._emitidos()), len(gen_config.MVP_SIGNALS))

    # ---- la unidad viaja con el nombre ----

    def test_la_unidad_es_la_del_adaptador_y_no_otra(self) -> None:
        """`m/s2` contra `m/s^2` eran dos sitios decidiendo lo mismo."""

        for crudo, (canonico, unidad) in can_rav4.SENALES.items():
            if crudo not in {s["signal_name"] for s in gen_config.MVP_SIGNALS}:
                continue
            mensaje = un_mensaje(crudo)
            self.assertEqual(
                mensaje["unit"], unidad,
                "%s sale en %r y el bus real la declara en %r"
                % (canonico, mensaje["unit"], unidad))

    # ---- que no se copie la tabla ----

    def test_el_mapa_se_reusa_del_adaptador(self) -> None:
        """Estructural: copiar la tabla crearia un segundo sitio que decide.

        Es la regla que el propio `can_rav4.py` escribio: «dos nombres para la
        misma medida terminarian en desacuerdo». Si el generador copiara los
        pares, el dia que el adaptador cambie uno seguiria publicando el viejo.
        """

        ruta = RAIZ / "telemetry_generator" / "message_builder.py"
        self.assertIn(
            "can_rav4", ruta.read_text(encoding="utf-8"),
            "el generador no toma el mapa del adaptador: si lo copio, hay dos "
            "sitios donde se decide como se llama una rueda")
        self.assertNotIn(
            "wheel_speed_front_left", solo_codigo(ruta),
            "el nombre canonico esta escrito a mano aqui ademas de en el "
            "adaptador")

    # ---- lo que el adaptador no traduce ----

    def test_lo_que_el_bus_no_publica_conserva_su_nombre(self) -> None:
        """`gas_pedal` no esta en el mapa porque el adaptador no lo emite.

        La tabla A.1 lo sostiene con el ID 865 y la seccion 7.3 lo pone entre
        las «muy recomendadas», de modo que el nombre correcto es el que ya
        tenia. Traducirlo a la fuerza seria inventar un canonico que nadie
        declaro.
        """

        self.assertNotIn("gas_pedal", can_rav4.SENALES)
        self.assertEqual(un_mensaje("gas_pedal")["signal_name"], "gas_pedal")


if __name__ == "__main__":
    unittest.main()
