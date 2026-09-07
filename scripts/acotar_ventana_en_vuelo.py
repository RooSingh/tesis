# -*- coding: utf-8 -*-
"""Acota el maximo estable de la ventana de mensajes en vuelo.

Que quedo abierto
-----------------
La escalera de concurrencia se corrio en **2, 5, 10 y 500**. Los tres primeros
peldanos entregaron el 100 % y el ultimo perdio el 22,02 %, de modo que el umbral
entre diez y quinientos **no esta acotado**: podria estar en once o en
cuatrocientos noventa y nueve, y el informe lo declara como dato faltante.

Este guion corre los peldanos intermedios con el **mismo volumen y la misma
duracion**, que es la condicion que hace comparables las corridas: si cambiara
alguna de las dos, la perdida podria venir de ahi y no de la concurrencia.

Por que la perdida no se ve venir
---------------------------------
En la corrida que perdio el 22 %, **ningun contador propio lo reflejo**: los
mensajes intentados, los confirmados, los errores de publicacion, los recibidos,
los persistidos, los pendientes y las desconexiones quedaron todos en el valor
esperado o en cero.

De ahi que la unica medida confiable sea **contar las filas en la base** contra lo
que se emitio. Cada peldano lleva su propia identidad de reinyeccion para poder
contarlas por separado, y se borran al terminar.

Que se busca, exactamente
-------------------------
El peldano mas alto con entrega completa. No el mas rapido: la configuracion de
operacion adoptada es de **un solo mensaje en vuelo**, y esta medicion no la
cambia. Lo que produce es el limite documentado de hasta donde se podria subir si
alguna vez hiciera falta.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from backend import db  # noqa: E402

#: Los peldanos que faltan entre diez y quinientos. Se eligen en progresion
#: aproximadamente geometrica: si el umbral estuviera cerca de diez, una
#: progresion lineal gastaria las corridas en la zona alta donde ya se sabe que
#: pierde.
PELDANOS = (20, 50, 100, 200, 350)

#: Cuanto se espera a que el consumidor termine de persistir antes de contar. La
#: cuenta se hace sobre la base, de modo que contar antes de que drene informaria
#: una perdida que no existe.
ESPERA_DRENAJE_S = 45.0

METRICAS = RAIZ / "logs" / "consumidor_metricas.json"


def _pendientes() -> int | None:
    try:
        return json.loads(METRICAS.read_text(encoding="utf-8")).get("pending")
    except (OSError, ValueError):
        return None


def _esperar_drenaje(limite_s: float = ESPERA_DRENAJE_S * 8) -> None:
    """Espera a que la cola del consumidor quede vacia."""

    inicio = time.perf_counter()
    while time.perf_counter() - inicio < limite_s:
        if _pendientes() == 0:
            return
        time.sleep(5.0)


def _contar(run_id: str) -> int:
    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        cursor.execute("select count(*) from telemetry_messages "
                       "where replay_run_id = %s", (run_id,))
        return cursor.fetchone()[0]


def _borrar(run_id: str) -> int:
    with db.obtener_conexion() as conexion:
        conexion.autocommit = True
        with conexion.cursor() as cursor:
            cursor.execute("delete from telemetry_messages "
                           "where replay_run_id = %s", (run_id,))
            return cursor.rowcount


def correr_peldano(sesion: int, pilotos: str, en_vuelo: int, marca: str,
                   desde: str | None = None, hasta: str | None = None) -> dict:
    run_id = f"ventana_{en_vuelo:03d}_{marca}"
    orden = [sys.executable, str(RAIZ / "scripts" / "replay_openf1.py"),
             "--session-key", str(sesion), "--drivers", pilotos,
             "--replay-run-id", run_id, "--publish",
             # La herramienta exige confirmar la publicacion a proposito, para
             # que nadie escriba en la base por descuido. La prueba la confirma.
             "--confirm-publish", "REPLAY_OPENF1",
             "--max-inflight-messages", str(en_vuelo)]
    # La ventana temporal se fija igual para todos los peldanos: si el volumen
    # cambiara entre corridas, la perdida podria venir de ahi y no de la
    # concurrencia, que es lo unico que la prueba quiere variar.
    if desde:
        orden += ["--start", desde]
    if hasta:
        orden += ["--end", hasta]

    inicio = time.perf_counter()
    salida = subprocess.run(orden, capture_output=True, text=True,
                            cwd=str(RAIZ))
    duracion = time.perf_counter() - inicio

    # La herramienta informa una linea JSON. Se lee ese campo y no se cuenta
    # aparte: contar por otra via daria dos numeros que podrian discrepar, y la
    # prueba compara lo emitido contra lo persistido.
    emitidos = None
    informe = None
    for linea in (salida.stdout or "").splitlines():
        linea = linea.strip()
        if linea.startswith("{"):
            try:
                informe = json.loads(linea)
            except ValueError:
                continue
            # En modo seco la herramienta informa `mqtt_messages`; publicando
            # informa `publish_metrics.attempted`. Se aceptan las dos formas
            # porque las dos son la misma cantidad contada por el emisor.
            metricas = informe.get("publish_metrics") or {}
            emitidos = metricas.get("attempted") or informe.get("mqtt_messages")

    _esperar_drenaje()
    persistidos = _contar(run_id)
    borradas = _borrar(run_id)

    faltantes = (emitidos - persistidos) if emitidos is not None else None
    return {
        "en_vuelo": en_vuelo,
        "run_id": run_id,
        "emitidos": emitidos,
        "persistidos": persistidos,
        "faltantes": faltantes,
        "perdida": (faltantes / emitidos) if emitidos else None,
        "borradas": borradas,
        "duracion_s": round(duracion, 1),
        "codigo_de_salida": salida.returncode,
        "informe_del_emisor": informe,
        "error": (salida.stderr or "").strip()[-200:] or None,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sesion", type=int, required=True,
                    help="clave de sesion de la fuente deportiva")
    ap.add_argument("--pilotos", default="1",
                    help="lista de numeros, o 'all'")
    ap.add_argument("--peldanos", type=int, nargs="*", default=list(PELDANOS))
    ap.add_argument("--desde", default=None, help="UTC ISO 8601 inclusivo")
    ap.add_argument("--hasta", default=None, help="UTC ISO 8601 exclusivo")
    ap.add_argument("--salida", type=Path,
                    default=RAIZ / "logs" / "ventana_en_vuelo.json")
    args = ap.parse_args()

    marca = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    print(f"  sesion {args.sesion}, pilotos {args.pilotos}")
    print(f"  peldanos: {', '.join(str(p) for p in args.peldanos)}")
    print()

    resultados = []
    for en_vuelo in args.peldanos:
        print(f"  en vuelo {en_vuelo}...", flush=True)
        r = correr_peldano(args.sesion, args.pilotos, en_vuelo, marca,
                           args.desde, args.hasta)
        resultados.append(r)
        perdida = "-" if r["perdida"] is None else f"{r['perdida']:.2%}"
        print(f"     emitidos {r['emitidos']}  persistidos {r['persistidos']:,}  "
              f"perdida {perdida}", flush=True)

    args.salida.write_text(json.dumps(resultados, indent=1, ensure_ascii=False),
                           encoding="utf-8")
    print()
    print(f"  {'en vuelo':>9} {'emitidos':>10} {'persistidos':>12} {'perdida':>9}")
    print("  " + "-" * 44)
    for r in resultados:
        perdida = "-" if r["perdida"] is None else f"{r['perdida']:.2%}"
        print(f"  {r['en_vuelo']:>9} {str(r['emitidos']):>10} "
              f"{r['persistidos']:>12,} {perdida:>9}")

    completos = [r["en_vuelo"] for r in resultados
                 if r["faltantes"] == 0]
    if completos:
        print()
        print(f"  peldano mas alto con entrega completa: {max(completos)}")
    print(f"  detalle en {args.salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
