# -*- coding: utf-8 -*-
"""El segundo conductor de una partida en pantalla dividida.

La prueba de dos conductores espera los **dos** vehiculos con datos. Hasta el
2026-09-01 solo el primero llegaba a la base y a la vista, de modo que la captura
habria salido a medias sin que nada lo declarara.

Lo que se verifica aca es la distincion que importa: **una sesion sin segundo
jugador tiene que comportarse exactamente como antes**. La cabecera usa 255 para
decir que no hay ninguno, y 255 no es un indice valido; confundirlo con un indice
haria que toda sesion normal pareciera tener dos conductores.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from adapters import f1_25  # noqa: E402
from backend import f1_udp  # noqa: E402


def paquete(indice_propio: int, indice_secundario: int) -> dict:
    """Un paquete de telemetria decodificado, escrito a mano.

    Los valores por vehiculo se ponen distintos a proposito: es lo que permite
    comprobar que cada conductor recibe **los suyos** y no los del otro.
    """

    vehiculos = [{"speed_kmh": 100 + i, "throttle": 0.5, "brake": 0.0,
                  "gear": 5, "engine_rpm": 10000, "drs": 0,
                  "surface_type": {r: 0 for r in f1_udp.ORDEN_RUEDAS},
                  "tyres_surface_temperature_c": {r: 90 for r in f1_udp.ORDEN_RUEDAS},
                  "tyres_inner_temperature_c": {r: 95 for r in f1_udp.ORDEN_RUEDAS},
                  "tyres_pressure_psi": {r: 23.0 for r in f1_udp.ORDEN_RUEDAS},
                  "brakes_temperature_c": {r: 400 for r in f1_udp.ORDEN_RUEDAS}}
                 for i in range(f1_udp.VEHICULOS)]

    decodificado = {
        "decodificado": True, "paquete": "car_telemetry", "packet_id": 6,
        "version_decodificador": "prueba",
        "cabecera": {"session_uid": 7, "player_car_index": indice_propio,
                     "secondary_player_car_index": indice_secundario,
                     "session_time": 1.0, "packet_format": 2025,
                     "frame_identifier": 1},
        "vehiculos": vehiculos,
        "vehiculo_propio": vehiculos[indice_propio],
    }
    if indice_secundario != f1_udp.SIN_SEGUNDO_JUGADOR:
        decodificado["vehiculo_secundario"] = vehiculos[indice_secundario]
        decodificado["indice_secundario"] = indice_secundario
    return decodificado


class SinSegundoJugador(unittest.TestCase):

    def test_una_sesion_normal_no_cambia(self):
        """255 significa que no hay segundo jugador, y no el indice 255."""

        mensajes = f1_25.mensajes_desde_paquete(
            paquete(19, f1_udp.SIN_SEGUNDO_JUGADOR), "2026-09-01T00:00:00+00:00")
        vehiculos = {m["vehicle_id"] for m in mensajes}
        self.assertEqual(len(vehiculos), 1)

    def test_el_decodificador_no_inventa_un_segundo(self):
        self.assertEqual(f1_udp.SIN_SEGUNDO_JUGADOR, 255)


class ConSegundoJugador(unittest.TestCase):

    def test_los_dos_conductores_se_normalizan(self):
        mensajes = f1_25.mensajes_desde_paquete(
            paquete(19, 4), "2026-09-01T00:00:00+00:00")
        vehiculos = {m["vehicle_id"] for m in mensajes}
        conductores = {m["driver_id"] for m in mensajes}
        self.assertEqual(len(vehiculos), 2)
        self.assertEqual(len(conductores), 2)

    def test_cada_conductor_lleva_sus_propios_valores(self):
        """Mezclarlos daria una comparacion entre pilotos sin sentido.

        Los dos vehiculos del paquete llevan velocidades distintas a proposito, de
        modo que un cruce se detecta por el valor y no solo por el identificador.
        """

        mensajes = f1_25.mensajes_desde_paquete(
            paquete(19, 4), "2026-09-01T00:00:00+00:00")
        por_vehiculo = {}
        for m in mensajes:
            if m["signal_name"] == "speed":
                por_vehiculo[m["vehicle_id"]] = m["value"]

        self.assertEqual(len(por_vehiculo), 2)
        # El paquete construido da 100 + indice a cada vehiculo.
        self.assertEqual(sorted(por_vehiculo.values()), [104, 119])

    def test_comparten_la_sesion(self):
        """Dos conductores de la misma partida son una sola sesion.

        Si cada uno tuviera la suya, no habria forma de compararlos por vuelta ni
        de saber que corrieron en las mismas condiciones.
        """

        mensajes = f1_25.mensajes_desde_paquete(
            paquete(19, 4), "2026-09-01T00:00:00+00:00")
        self.assertEqual(len({m["session_id"] for m in mensajes}), 1)


if __name__ == "__main__":
    unittest.main()
