# -*- coding: utf-8 -*-
"""Mide la latencia de la cadena con tramas reales de un vehiculo.

Que cambia respecto de la medicion sintetica
--------------------------------------------
La medicion anterior fabricaba sus mensajes. Servia para caracterizar la cadena,
pero medir un sistema con datos que el propio sistema genera es parcialmente
circular. Aca el flujo son **tramas de un vehiculo que circulaba**, decodificadas
y normalizadas por su adaptador, emitidas por el intermediario con la
temporizacion original del bus.

Por que esta fuente y no otra
-----------------------------
La tasa natural del bus, ya medida, es de unos **900 mensajes del contrato por
segundo**. La medicion sintetica encontro la latencia **plana entre 1 y 500** por
segundo y **cuadruplicada a 2.000**, sin nada medido en el medio. La tasa del bus
cae justo en ese hueco, de modo que esta corrida no solo cambia dato sintetico por
real: **mide donde el comportamiento cambia**.

Como se ubica cada mensaje
--------------------------
Por su identidad de reinyeccion. El camino por intermediario **no la ponia** hasta
esta medicion, lo que impedia ubicar las filas de una corrida y ademas dejaba que
una segunda corrida duplicara filas en silencio, porque sin esas dos claves el
indice unico no aplica.

Las filas que escribe
---------------------
Van a la tabla real, con `source_type` de reproduccion de CAN. Se cuentan, se
conciliaban contra lo emitido, y `--limpiar` las borra al terminar conciliando
contra cero.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

from adapters import can_rav4  # noqa: E402
from backend.db import obtener_conexion  # noqa: E402

import medir_latencia_cadena as med  # noqa: E402

# Cada cuanto se consulta la base. Igual que en la medicion sintetica, y por el
# mismo motivo: tiene que ser mayor que lo que tarda la consulta y chico frente a
# la latencia esperada.
MUESTREO_MS = 25.0

# Cuanto se espera despues de la ultima emision antes de dar por perdido lo que
# no llego. Diez veces el intervalo de vaciado del consumidor.
ESPERA_FINAL_S = 6.0


def contar_filas(run_id: str) -> int:
    """Cuantas filas de esta corrida hay en la base.

    Nombra `replay_seq IS NOT NULL` porque el indice de trazabilidad es parcial y
    sin esa condicion el planificador lo descarta y recorre la tabla entera: son
    110 segundos contra 5 milisegundos sobre cincuenta millones de filas.
    """

    with obtener_conexion() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM telemetry_messages "
            "WHERE replay_run_id = %s AND replay_seq IS NOT NULL", (run_id,))
        return cur.fetchone()[0]


def limpiar(run_id: str) -> int:
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM telemetry_messages "
                "WHERE replay_run_id = %s AND replay_seq IS NOT NULL", (run_id,))
            borradas = cur.rowcount
        conn.commit()
    return borradas


def _latencias(run_id: str, detectado: dict[int, float]) -> list[float]:
    """Latencia de cada mensaje, en milisegundos.

    Se leen de la base los instantes de publicacion que el reproductor sello, y
    se restan del instante en que el vigia vio aparecer esa fila. Los dos relojes
    son el de esta maquina, de modo que no hay sincronizacion que resolver.

    El reloj monotono del vigia y el reloj de pared del sello no comparten
    origen, y por eso se alinean por su **diferencia minima**: el mensaje que
    menos tardo fija el desfase entre los dos relojes, y de ahi en adelante las
    latencias son relativas a el. Eso hace que **la latencia minima quede en cero
    por construccion**, y que lo interpretable sea la **dispersion** ---cuanto se
    corren los demas respecto del mas rapido--- y no el valor absoluto.
    """

    from datetime import datetime

    if not detectado:
        return []
    with obtener_conexion() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT replay_seq, metadata->>'extra' FROM telemetry_messages "
            "WHERE replay_run_id = %s AND replay_seq IS NOT NULL", (run_id,))
        filas = cur.fetchall()

    publicado: dict[int, float] = {}
    for seq, extra in filas:
        if not extra:
            continue
        try:
            marca = json.loads(extra).get("published_at_utc")
            if marca:
                publicado[seq] = datetime.fromisoformat(marca).timestamp()
        except Exception:
            continue

    pares = [(detectado[s], publicado[s]) for s in detectado if s in publicado]
    if not pares:
        return []
    desfase = min(d - p for d, p in pares)
    return sorted((d - p - desfase) * 1000 for d, p in pares)


def medir_una(segmento: str, segundos: float, velocidad: float,
              run_id: str, muestreo_s: float) -> dict:
    """Emite un tramo del bus y cronometra cuando cada fila queda consultable."""

    vigia = med.Vigia(run_id, muestreo_s)
    vigia.start()
    # El vigia comprueba primero que su propia consulta no domine la medida. Si
    # aborta, no se emite nada: medir con un instrumento mas lento que el
    # fenomeno informa la lentitud del instrumento como latencia de la cadena.
    time.sleep(1.5)
    if vigia.error is not None:
        raise vigia.error

    arranque = time.perf_counter()
    salida = subprocess.run(
        [sys.executable, str(RAIZ / "scripts" / "reproducir_can.py"),
         "--por-broker", "--segmentos", segmento,
         "--segundos", str(segundos), "--velocidad", str(velocidad),
         "--run-id", run_id],
        capture_output=True, text=True)
    emision_s = time.perf_counter() - arranque

    publicados = None
    for linea in salida.stdout.splitlines():
        if "publicados" in linea:
            publicados = int(linea.split(":")[1].strip().split()[0].replace(",", ""))

    time.sleep(ESPERA_FINAL_S)
    vigia.parar.set()
    vigia.join(timeout=15)

    # La latencia de cada mensaje es su instante de deteccion menos **su propio**
    # instante de publicacion, que el reproductor sella en el mensaje. Medirla
    # contra el arranque de la corrida le sumaria a cada uno el tiempo que tardo
    # en llegarle su turno de emision, que es una espera distinta y no de la
    # cadena.
    detectados = len(vigia.detectado)
    presentes = contar_filas(run_id)
    latencias = _latencias(run_id, vigia.detectado)
    return {
        "segmento": segmento,
        "velocidad": velocidad,
        "segundos_de_grabacion": segundos,
        "duracion_emision_s": emision_s,
        "publicados": publicados,
        "detectados": detectados,
        "presentes_en_base": presentes,
        "tasa_emitida": (publicados / emision_s
                         if publicados and emision_s else float("nan")),
        "consulta_vacia_ms": vigia.consulta_vacia_s * 1000,
        "muestras_de_latencia": len(latencias),
        "p50_ms": med._percentil(latencias, 0.50),
        "p95_ms": med._percentil(latencias, 0.95),
        "p99_ms": med._percentil(latencias, 0.99),
        "minimo_ms": latencias[0] if latencias else float("nan"),
        "maximo_ms": latencias[-1] if latencias else float("nan"),
        "media_ms": statistics.mean(latencias) if latencias else float("nan"),
        "run_id": run_id,
        "salida_emisor": salida.stdout[-400:] if salida.returncode else None,
        "codigo_emisor": salida.returncode,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--segmento", default="sample_01")
    ap.add_argument("--velocidades", type=float, nargs="+", default=[1.0],
                    help="multiplicadores del ritmo del bus")
    ap.add_argument("--segundos", type=float, default=20.0,
                    help="segundos de grabacion por corrida")
    ap.add_argument("--muestreo-ms", type=float, default=MUESTREO_MS)
    ap.add_argument("--etiqueta", default=None)
    ap.add_argument("--limpiar", action="store_true",
                    help="borra al terminar las filas que la medicion escribio")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    sello = args.etiqueta or time.strftime("%Y%m%d_%H%M%S")
    print(f"Fuente: {can_rav4.SOURCE_TYPE}, segmento {args.segmento}")
    print(f"El consumidor escribe al juntar 1.000 mensajes o cada 0,5 s.")
    print()
    print(f"  {'velocidad':>10}{'tasa /s':>9}{'emitidos':>10}{'en base':>9}"
          f"{'faltan':>7}{'p50':>8}{'p95':>8}{'p99':>8}{'max':>8}")
    print("  " + "-" * 76)

    resultados = []
    for v in args.velocidades:
        run_id = f"can_latencia_{sello}_{v:g}x"
        r = medir_una(args.segmento, args.segundos, v, run_id,
                      args.muestreo_ms / 1000.0)
        resultados.append(r)
        faltan = ((r["publicados"] or 0) - r["presentes_en_base"])
        print(f"  {v:>10.1f}{r['tasa_emitida']:>9,.0f}"
              f"{(r['publicados'] or 0):>10,}{r['presentes_en_base']:>9,}"
              f"{faltan:>7,}{r['p50_ms']:>7.0f}m{r['p95_ms']:>7.0f}m"
              f"{r['p99_ms']:>7.0f}m{r['maximo_ms']:>7.0f}m")
        if r["codigo_emisor"]:
            print(f"     el emisor devolvio {r['codigo_emisor']}: "
                  f"{r['salida_emisor']}")

    total = sum(r["presentes_en_base"] for r in resultados)
    print()
    print(f"  filas escritas: {total:,}")
    if args.limpiar:
        borradas = sum(limpiar(r["run_id"]) for r in resultados)
        quedan = sum(contar_filas(r["run_id"]) for r in resultados)
        print(f"  borradas: {borradas:,}   quedan: {quedan:,}")
        print(f"  concilia contra cero: {quedan == 0}")

    if args.json:
        args.json.write_text(json.dumps(resultados, indent=1), encoding="utf-8")
        print(f"\n  crudo en {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
