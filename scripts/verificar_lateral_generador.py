# -*- coding: utf-8 -*-
"""Contrasta la aceleracion lateral del generador con la que predice v * omega.

POR QUE HACE FALTA
------------------
El capitulo 7 usa la relacion de giro plano ---aceleracion lateral igual a
velocidad por velocidad de guinada--- para confirmar la escala del acelerometro de
la captura real. El capitulo 8 publica, para la maniobra demostrativa, un maximo de
accel_y de 1,760 m/s2 y de yaw_rate de 7,70 deg/s, con una velocidad de 118,10 km/h
en el apice. Multiplicadas, esas cifras dan unos 4,4 m/s2, y la pregunta es cual de
las tres cosas falla: la relacion, la simultaneidad de los maximos o la medicion.

LO QUE HACE
-----------
Recorre la maniobra completa con el mismo bucle del generador ---seis mil pasos de
10 ms--- y, en cada paso, compara accel_y con v * omega. Informa:

- el instante del maximo de cada canal y la velocidad en ese instante,
- el instante del minimo local de velocidad,
- el rango, la mediana y el percentil 99 publicados, para confirmar que se
  reproducen,
- el cociente accel_y / (v * omega) sobre los pasos con giro apreciable,
- y el rango que tendria accel_y si se calculara como v * omega.

No modifica el generador: solo lo ejecuta.
"""

from __future__ import annotations

import math
import statistics
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from telemetry_generator.main import crear_estado_inicial  # noqa: E402
from telemetry_generator.signals import (  # noqa: E402
    aplicar_escenario_demostrativo,
    actualizar_estado_basico,
)

PASO_MS = 10
DURACION_MS = 60_000
#: Por debajo de este valor de v * omega el cociente no dice nada util.
GIRO_APRECIABLE = 0.05


def _percentil_99(valores: list[float]) -> float:
    ordenados = sorted(valores)
    return ordenados[int(0.99 * len(ordenados))]


def recorrer() -> list[dict]:
    estado = crear_estado_inicial()
    filas = []
    for t in range(0, DURACION_MS, PASO_MS):
        aplicar_escenario_demostrativo(estado, t)
        actualizar_estado_basico(estado, PASO_MS)
        v = estado.speed / 3.6
        omega = math.radians(estado.yaw_rate)
        filas.append({
            "s": t / 1000.0,
            "speed_kmh": estado.speed,
            "steer_deg": estado.steer_angle,
            "accel_y": estado.accel_y,
            "yaw_rate": estado.yaw_rate,
            "v_omega": v * omega,
        })
    return filas


def main() -> int:
    filas = recorrer()

    max_ay = max(filas, key=lambda f: f["accel_y"])
    max_yr = max(filas, key=lambda f: f["yaw_rate"])
    tramo_curva = [f for f in filas if 14.0 < f["s"] < 40.0]
    min_v = min(tramo_curva, key=lambda f: f["speed_kmh"])

    ay = [f["accel_y"] for f in filas]
    yr = [f["yaw_rate"] for f in filas]
    vo = [f["v_omega"] for f in filas]

    print(f"  pasos: {len(filas)}")
    print(f"\n  maximo de accel_y   : {max_ay['accel_y']:.3f} m/s2 a {max_ay['s']:.2f} s, "
          f"v = {max_ay['speed_kmh']:.2f} km/h, direccion {max_ay['steer_deg']:.2f} deg")
    print(f"  maximo de yaw_rate  : {max_yr['yaw_rate']:.2f} deg/s a {max_yr['s']:.2f} s")
    print(f"  minimo de velocidad : {min_v['speed_kmh']:.2f} km/h a {min_v['s']:.2f} s")

    print("\n  lo publicado, recalculado:")
    print(f"    accel_y  {min(ay):.3f} a {max(ay):.3f}, mediana {statistics.median(ay):.3f}, "
          f"p99 {_percentil_99(ay):.3f}")
    print(f"    yaw_rate {min(yr):.2f} a {max(yr):.2f}, mediana {statistics.median(yr):.3f}, "
          f"p99 {_percentil_99(yr):.3f}")

    print("\n  la relacion de giro plano:")
    print(f"    v * omega en el maximo de accel_y: {max_ay['v_omega']:.3f} m/s2")
    cocientes = [f["accel_y"] / f["v_omega"] for f in filas
                 if abs(f["v_omega"]) > GIRO_APRECIABLE]
    print(f"    accel_y / (v * omega): {min(cocientes):.3f} a {max(cocientes):.3f} "
          f"sobre {len(cocientes)} pasos")
    # accel_y = 0,08 * direccion y yaw_rate = 0,35 * direccion: su cociente es una
    # velocidad fija, la misma en cualquier instante de la maniobra.
    v_implicita = 0.08 / math.radians(0.35) * 3.6
    print(f"    velocidad implicita en el cociente de los dos factores: {v_implicita:.1f} km/h")

    print("\n  si accel_y fuera v * omega:")
    print(f"    {min(vo):.3f} a {max(vo):.3f}, mediana {statistics.median(vo):.3f}, "
          f"p99 {_percentil_99(vo):.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
