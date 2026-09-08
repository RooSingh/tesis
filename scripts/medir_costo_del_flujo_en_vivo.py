# -*- coding: utf-8 -*-
"""Mide en que se le va el nucleo al servidor de la interfaz.

QUE PREGUNTA RESPONDE
---------------------
La medicion de consumo de recursos encontro que el servidor de la interfaz ocupa
**1,021 nucleos con cero suscriptores**, y es la pieza propia que mas procesador
gasta. Pero saber cuanto no dice **en que**, y sin eso cualquier arreglo es a
ciegas: si el grueso se va en interpretar el JSON, no servirian de nada ni saltear
el anotador ni saltear el resumen, porque el JSON hay que interpretarlo igual para
saber si el mensaje interesa.

El manejador hace cuatro cosas por mensaje, y **las hace todas antes de preguntar
si alguien escucha**:

1. interpretar el JSON del lote;
2. mantener una serie por senal y por vehiculo, mas la de distancia;
3. alimentar un resumen de la sesion entera, segundo a segundo;
4. correr el anotador en vivo.

Esta prueba las cronometra por separado.

POR QUE ES UN BANCO Y NO UNA MEDICION EN VIVO
---------------------------------------------
No toca el servidor que esta corriendo ni cambia una linea suya: importa el mismo
modulo, arma lotes con la forma real que publica el capturador y cronometra las
partes. Medir sobre el proceso vivo exigiria instrumentarlo, que es justamente el
cambio que esta medicion tiene que justificar antes de que se haga.

LA FORMA DEL LOTE IMPORTA
-------------------------
El capturador agrupa **un envio por paquete de juego**, no uno por senal, y con la
parrilla completa un solo envio puede llevar cientos de senales. Medir con mensajes
sueltos daria un costo por mensaje que no es el que el servidor paga.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from backend import live_stream  # noqa: E402

#: Senales de un vehiculo en un paquete de telemetria, con nombres reales del
#: contrato interno.
SENALES = (
    "speed", "throttle_position", "brake_position", "steering_normalized",
    "engine_speed", "gear_selected", "lap_distance", "lap_number",
    "current_lap_time", "g_force_lateral", "g_force_longitudinal",
    "tyre_temperature_surface_front_left", "tyre_wear_front_left",
    "wheel_slip_ratio_rear_left", "drs_active",
)


def _lote(vehiculos: int, base_s: float) -> list[dict]:
    """Un envio con la forma que publica el capturador con parrilla completa."""

    marca = datetime.fromtimestamp(base_s, timezone.utc).isoformat()
    salida: list[dict] = []
    for v in range(vehiculos):
        for i, senal in enumerate(SENALES):
            salida.append({
                "timestamp": marca,
                "vehicle_id": f"f1_25:session:banco:car:{v}",
                "driver_id": f"d{v}", "session_id": "f1_25:session:banco",
                "lap_id": None, "signal_name": senal,
                "value": float(i) + base_s % 7, "unit": "u",
                "source_type": "f1_25_udp_simulation", "quality_flag": "ok",
                "metadata": {"can_id": None, "src": None,
                             "reference_type": "p", "reference_id": "banco",
                             "extra": {}},
            })
    return salida


def medir(vehiculos: int, lotes: int) -> dict:
    difusor = live_stream.DifusorEnVivo()
    cargas = [json.dumps(_lote(vehiculos, 1000.0 + n * 0.05))
              for n in range(lotes)]
    senales = sum(len(json.loads(c)) for c in cargas[:1]) * lotes

    # --- 1. interpretar el JSON -------------------------------------------
    t0 = time.perf_counter()
    interpretados = [json.loads(c) for c in cargas]
    t_json = time.perf_counter() - t0

    marca = datetime.now(timezone.utc).isoformat()

    # --- 2. las series por senal ------------------------------------------
    # Se reproduce lo que el manejador hace, sin resumen ni anotador, para
    # aislar el costo de mantener las colas.
    historia: dict = {}
    tiempos: dict = {}
    t0 = time.perf_counter()
    for lote in interpretados:
        for cuerpo in lote:
            senal = cuerpo.get("signal_name")
            vehiculo = cuerpo.get("vehicle_id") or "sin-vehiculo"
            del_vehiculo = historia.setdefault(vehiculo, {})
            t = tiempos.setdefault(vehiculo, {})
            serie = del_vehiculo.get(senal)
            if serie is None:
                serie = del_vehiculo[senal] = deque(
                    maxlen=live_stream.MUESTRAS_POR_SENAL)
                t[senal] = deque(maxlen=live_stream.MUESTRAS_POR_SENAL)
            serie.append(cuerpo.get("value"))
            t[senal].append(cuerpo.get("timestamp"))
    t_series = time.perf_counter() - t0

    # --- 3. el resumen de la sesion entera --------------------------------
    t0 = time.perf_counter()
    for lote in interpretados:
        for cuerpo in lote:
            segundo = live_stream._segundo_de(cuerpo.get("timestamp"))
            if segundo is not None:
                difusor.resumen.observar(cuerpo.get("vehicle_id"),
                                         cuerpo.get("signal_name"),
                                         segundo, cuerpo.get("value"))
    t_resumen = time.perf_counter() - t0

    # --- 4. el anotador en vivo -------------------------------------------
    from backend import anotador_vivo
    anotadores: dict = {}
    t0 = time.perf_counter()
    for lote in interpretados:
        for cuerpo in lote:
            vehiculo = cuerpo.get("vehicle_id") or "sin-vehiculo"
            a = anotadores.get(vehiculo)
            if a is None:
                a = anotadores[vehiculo] = anotador_vivo.Anotador(
                    al_anotar=lambda _a, _v=vehiculo: None)
            a.observar(cuerpo)
    t_anotador = time.perf_counter() - t0

    # --- el manejador entero, en sus dos modos ----------------------------
    # Con alguien mirando hace todo; sin nadie, saltea el anotador y el resumen.
    # Los dos numeros juntos son la verificacion de que el ahorro es el que la
    # descomposicion de arriba predice.
    mirando = live_stream.DifusorEnVivo()
    mirando._cuantos_suscriptores = 1
    t0 = time.perf_counter()
    for lote in interpretados:
        for cuerpo in lote:
            mirando._procesar_cuerpo(dict(cuerpo), marca)
    t_entero = time.perf_counter() - t0

    solo = live_stream.DifusorEnVivo()
    t0 = time.perf_counter()
    for lote in interpretados:
        for cuerpo in lote:
            solo._procesar_cuerpo(dict(cuerpo), marca)
    t_sin_nadie = time.perf_counter() - t0

    partes = {
        "interpretar el JSON": t_json,
        "las series por senal": t_series,
        "el resumen de la sesion": t_resumen,
        "el anotador en vivo": t_anotador,
    }
    return {
        "vehiculos": vehiculos, "lotes": lotes, "senales": senales,
        "partes_s": {k: round(v, 4) for k, v in partes.items()},
        "manejador_entero_s": round(t_entero, 4),
        "manejador_sin_suscriptores_s": round(t_sin_nadie, 4),
        "ahorro_sin_suscriptores": round(1 - t_sin_nadie / t_entero, 3),
        "suma_de_las_partes_s": round(sum(partes.values()), 4),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vehiculos", type=int, default=20)
    ap.add_argument("--lotes", type=int, default=200)
    ap.add_argument("--salida", type=Path,
                    default=RAIZ / "logs" / "costo_del_flujo_en_vivo.json")
    args = ap.parse_args()

    r = medir(args.vehiculos, args.lotes)
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps(r, indent=1, ensure_ascii=False),
                           encoding="utf-8")

    print(f"  {args.lotes} lotes de {args.vehiculos} vehiculos: "
          f"{r['senales']:,} senales")
    print()
    total = r["suma_de_las_partes_s"]
    for nombre, s in sorted(r["partes_s"].items(), key=lambda x: -x[1]):
        print(f"  {nombre:26s} {s * 1000:9.1f} ms   {s / total * 100:5.1f} %")
    print(f"  {'-' * 26} {'-' * 9}")
    print(f"  {'suma de las partes':26s} {total * 1000:9.1f} ms")
    print(f"  {'el manejador, con alguien':26s} "
          f"{r['manejador_entero_s'] * 1000:9.1f} ms")
    print(f"  {'el manejador, sin nadie':26s} "
          f"{r['manejador_sin_suscriptores_s'] * 1000:9.1f} ms   "
          f"ahorra {r['ahorro_sin_suscriptores'] * 100:.0f} %")
    print()
    # Cuanto de un nucleo se lleva sostener la carga real de la parrilla.
    por_senal_us = r["manejador_entero_s"] / r["senales"] * 1e6
    print(f"  costo por senal            {por_senal_us:9.2f} us")
    print(f"  a 35.186 senales/s eso es {35186 * por_senal_us / 1e6:9.3f} nucleos")
    print(f"  detalle en {args.salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
