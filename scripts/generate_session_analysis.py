"""Genera el analisis automatico de una sesion completa a partir de un replay.

Recorre la telemetria persistida de una corrida, la reparte contra las ventanas de
vuelta y de stint, calcula las metricas de cada nivel de evidencia y guarda el
resultado en `session_lap_analysis` y `session_stint_analysis`.

El calculo se hace una sola vez y se persiste porque los resultados son unas 1.100
filas frente a los 6.217.506 mensajes que los originan. Recalcularlos en cada
consulta obligaria a recorrer millones de filas por request.

Este script lee telemetria y escribe unicamente en las tablas de analisis. No
publica por MQTT ni modifica `telemetry_messages`.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.db import (
    calcular_ventanas_vueltas,
    guardar_analisis_sesion,
    obtener_pilotos_racing,
    obtener_sesion_racing,
    obtener_stints_piloto,
    obtener_telemetria_corrida_piloto,
    obtener_vueltas_oficiales_piloto,
)
from backend.session_analysis import (
    ANALYZER_VERSION,
    contar_minisectores_vuelta,
    evaluar_calidad,
    resolver_referencia_circuito,
    resolver_resolucion_minisector,
    resumir_minisectores,
    resumir_telemetria,
    validar_distancia,
)


def repartir_por_ventana(muestras: list[tuple], ventanas: list[dict]) -> dict[int, dict[str, list]]:
    """Asigna cada muestra a la ventana que la contiene, en una sola pasada.

    Las muestras y las ventanas llegan ordenadas por tiempo, de modo que basta con
    avanzar un puntero sobre las ventanas en vez de buscar la correspondiente para
    cada una de las 310.000 muestras de un piloto.

    El intervalo es `[inicio, fin)`: una muestra situada exactamente en el limite
    pertenece a una sola vuelta.
    """
    completas = [v for v in ventanas if v["completa"]]
    por_vuelta: dict[int, dict[str, list]] = {v["lap_number"]: {} for v in completas}
    indice = 0
    for timestamp, signal_name, value_numeric, value_boolean in muestras:
        while indice < len(completas) and timestamp >= completas[indice]["fin"]:
            indice += 1
        if indice >= len(completas):
            break
        ventana = completas[indice]
        if timestamp < ventana["inicio"]:
            continue
        por_vuelta[ventana["lap_number"]].setdefault(signal_name, []).append(
            (timestamp, value_numeric, value_boolean)
        )
    return por_vuelta


def metricas_oficiales_vuelta(vuelta: dict) -> dict:
    """Arma las metricas que provienen de OpenF1 sin transformar."""
    segmentos = []
    for sector in (1, 2, 3):
        segmentos += list(vuelta.get(f"segments_sector_{sector}") or [])
    oficiales = {
        "lap_duration_seconds": vuelta["lap_duration_seconds"],
        "duration_sector_1_seconds": vuelta["duration_sector_1_seconds"],
        "duration_sector_2_seconds": vuelta["duration_sector_2_seconds"],
        "duration_sector_3_seconds": vuelta["duration_sector_3_seconds"],
        "i1_speed_kph": vuelta["i1_speed_kph"],
        "i2_speed_kph": vuelta["i2_speed_kph"],
        "speed_trap_kph": vuelta["speed_trap_kph"],
        "is_pit_out_lap": vuelta["is_pit_out_lap"],
    }
    oficiales.update(resumir_minisectores(segmentos))
    return {clave: valor for clave, valor in oficiales.items() if valor is not None}


def analizar_piloto(session_key: int, replay_run_id: str, driver_number: int, referencia_circuito: dict):
    """Devuelve las filas de vuelta y de stint de un piloto, y sus conteos de minisector.

    El tercer valor son los minisectores que declara cada vuelta del piloto. Se
    devuelve desde aca porque las vueltas oficiales ya estan leidas: recolectarlas
    de nuevo en `main` duplicaria una consulta por piloto para un dato que este
    recorrido tiene a mano.
    """
    oficiales = obtener_vueltas_oficiales_piloto(session_key, driver_number)
    if not oficiales:
        return [], [], []
    conteos_minisectores = [contar_minisectores_vuelta(vuelta) for vuelta in oficiales]
    ventanas = calcular_ventanas_vueltas(
        [{"lap_number": v["lap_number"], "date_start": v["date_start"],
          "lap_duration_seconds": v["lap_duration_seconds"]} for v in oficiales]
    )
    ventana_por_vuelta = {v["lap_number"]: v for v in ventanas}
    muestras = obtener_telemetria_corrida_piloto(session_key, driver_number, replay_run_id)
    por_vuelta = repartir_por_ventana(muestras, ventanas)

    filas_vuelta = []
    for vuelta in oficiales:
        numero = vuelta["lap_number"]
        ventana = ventana_por_vuelta[numero]
        senales = por_vuelta.get(numero, {})
        derivadas = resumir_telemetria(senales)
        derivadas.update(validar_distancia(derivadas.get("distancia_m"), referencia_circuito))
        calidad = evaluar_calidad(senales, referencia_circuito)
        calidad["ventana_fin_estimado"] = ventana["fin_estimado"]
        calidad["ventana_completa"] = ventana["completa"]
        filas_vuelta.append({
            "driver_number": driver_number,
            "lap_number": numero,
            "window_start": ventana["inicio"],
            "window_end": ventana["fin"],
            "metricas_oficiales": json.dumps(metricas_oficiales_vuelta(vuelta), default=float),
            "metricas_derivadas": json.dumps(derivadas, default=float),
            "calidad": json.dumps(calidad, default=float),
        })

    filas_stint = []
    for stint in obtener_stints_piloto(session_key, driver_number):
        primera = ventana_por_vuelta.get(stint["lap_start"])
        ultima = ventana_por_vuelta.get(stint["lap_end"])
        if primera is None or ultima is None:
            continue
        senales: dict[str, list] = {}
        for numero in range(stint["lap_start"], stint["lap_end"] + 1):
            for senal, valores in por_vuelta.get(numero, {}).items():
                senales.setdefault(senal, []).extend(valores)
        derivadas = resumir_telemetria(senales)
        # La distancia de un stint no se valida contra la longitud de una vuelta:
        # abarca varias, de modo que la referencia deja de aplicar.
        derivadas.pop("distancia_metodo", None)
        vueltas_stint = stint["lap_end"] - stint["lap_start"] + 1
        oficiales_stint = {
            "vueltas": vueltas_stint,
            "tyre_age_at_start": stint["tyre_age_at_start"],
        }
        filas_stint.append({
            "driver_number": driver_number,
            "stint_number": stint["stint_number"],
            "compound": stint["compound"],
            "lap_start": stint["lap_start"],
            "lap_end": stint["lap_end"],
            "window_start": primera["inicio"],
            "window_end": ultima["fin"],
            "metricas_oficiales": json.dumps(oficiales_stint, default=float),
            "metricas_derivadas": json.dumps(derivadas, default=float),
            "calidad": json.dumps(evaluar_calidad(senales), default=float),
        })
    return filas_vuelta, filas_stint, conteos_minisectores


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-key", type=int, required=True)
    parser.add_argument("--replay-run-id", required=True, help="Corrida de replay a analizar.")
    parser.add_argument(
        "--track-length-m",
        type=float,
        default=None,
        help=(
            "Longitud del circuito en metros. Solo para circuitos que todavia no "
            "figuran en la tabla declarada. Sin este argumento la longitud se "
            "resuelve por circuit_key de la sesion, y si no hay entrada el analisis "
            "declara que la validacion de distancia no esta disponible."
        ),
    )
    parser.add_argument("--drivers", default="all", help="Lista CSV de numeros o 'all'.")
    args = parser.parse_args()

    # La referencia se resuelve una sola vez, a partir de la identidad de la sesion
    # que ya esta persistida. No hay default de circuito: antes lo habia, y era
    # Silverstone, de modo que analizar Spa-Francorchamps sin recordar el argumento
    # producia un desvio calculado contra un circuito 1.113 metros mas corto.
    sesion = obtener_sesion_racing(args.session_key)
    if sesion is None:
        parser.error(f"No hay sesion importada con session_key={args.session_key}.")
    referencia_circuito = resolver_referencia_circuito(
        circuit_key=sesion.get("circuit_key"),
        circuit_short_name=sesion.get("circuit_short_name"),
        longitud_declarada_m=args.track_length_m,
    )
    if referencia_circuito["referencia_disponible"]:
        print(
            f"referencia de circuito: {referencia_circuito['longitud_referencia_m']} m "
            f"({referencia_circuito.get('referencia_circuito')}) "
            f"fuente={referencia_circuito.get('referencia_fuente')}",
            flush=True,
        )
    else:
        # No se aborta: el resto del analisis es valido sin esta validacion. Lo que
        # no se admite es continuar en silencio.
        print(f"ADVERTENCIA: {referencia_circuito['referencia_motivo']}", flush=True)

    pilotos = [p["driver_number"] for p in obtener_pilotos_racing(args.session_key)]
    if args.drivers != "all":
        seleccionados = {int(x) for x in args.drivers.split(",")}
        pilotos = [p for p in pilotos if p in seleccionados]
    if not pilotos:
        parser.error("No hay pilotos que analizar para esa seleccion.")

    inicio = time.monotonic()
    vueltas: list[dict] = []
    stints: list[dict] = []
    conteos_minisectores: list[int | None] = []
    for driver_number in pilotos:
        fv, fs, cm = analizar_piloto(
            args.session_key, args.replay_run_id, driver_number, referencia_circuito
        )
        vueltas += fv
        stints += fs
        conteos_minisectores += cm
        print(f"piloto={driver_number} vueltas={len(fv)} stints={len(fs)}", flush=True)

    longitud_m = referencia_circuito.get("longitud_referencia_m")
    counts = {"pilotos": len(pilotos), "vueltas": len(vueltas), "stints": len(stints)}
    limits = {
        "muestreo_telemetria_hz": 3.7,
        "distancia_por_integracion_de_velocidad": True,
        "curvas_y_apices": "no disponible: requiere metadatos curados del circuito",
        "comparacion_por_metros": "no defendible al muestreo disponible",
        "drs_interpretacion_validada": True,
        "drs_umbral_abierto": "codigo >= 9, validado contra velocidad",
        # Procedencia completa de la longitud usada. Va en `limits` y no en `counts`
        # porque es un limite del resultado: dice hasta donde llega la validacion de
        # distancia y sobre que dato externo se apoya.
        "longitud_circuito_referencia": referencia_circuito,
    }
    # Resolucion espacial derivada de la propia sesion, con su procedencia completa.
    # Antes era `longitud / 26`, y el 26 era el conteo de Silverstone aplicado a
    # cualquier circuito. El bloque entero se guarda para que el numero pueda
    # auditarse: dice cuantos minisectores se detectaron, sobre cuantas vueltas y
    # con que distribucion.
    resolucion = resolver_resolucion_minisector(conteos_minisectores, longitud_m)
    limits["resolucion_minisector"] = resolucion
    if resolucion["disponible"]:
        # Copia plana del valor. Es redundante con el bloque de arriba a proposito:
        # `resolucion_minisector_m` es la llave que ya consumen los analisis
        # anteriores y la interfaz, y romperla obligaria a releer corridas viejas.
        limits["resolucion_minisector_m"] = resolucion["resolucion_m"]
    if not longitud_m:
        limits["validacion_de_distancia"] = (
            "no disponible: " + referencia_circuito["referencia_motivo"]
        )
    print(
        "resolucion de minisector: "
        + (
            f"{resolucion['resolucion_m']} m "
            f"({resolucion['minisectores_por_vuelta']} minisectores por vuelta, "
            f"moda sobre {resolucion['vueltas_consideradas']} vueltas)"
            if resolucion["disponible"]
            else f"no disponible: {resolucion['motivo']}"
        ),
        flush=True,
    )
    analysis_run_id = guardar_analisis_sesion(
        args.session_key, args.replay_run_id, ANALYZER_VERSION,
        longitud_m, counts, limits, vueltas, stints,
    )
    print(json.dumps({
        "analysis_run_id": analysis_run_id,
        "analyzer_version": ANALYZER_VERSION,
        "replay_run_id": args.replay_run_id,
        "counts": counts,
        "segundos": round(time.monotonic() - inicio, 1),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
