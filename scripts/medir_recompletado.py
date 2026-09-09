# -*- coding: utf-8 -*-
"""Corre el recompletado de rivales midiendo lo que cuesta.

QUE MIDE Y POR QUE LAS TRES COSAS JUNTAS
----------------------------------------
El recompletado es la operacion de escritura mas grande que este trabajo ejecuta,
y hasta aqui no habia ninguna cifra suya. Las tres preguntas que deja abiertas se
responden a la vez o no se responden:

``cuanto tarda``
    Con el ritmo efectivo, que no es el de una insercion suelta: el camino
    atraviesa la lectura del crudo, la decodificacion, la normalizacion y la
    validacion antes de tocar la base.
``cuanto ocupa la maquina``
    Escribir veinticinco millones de filas no es lo mismo que escribir mil, y el
    equipo de destino tiene cuatro nucleos. Se muestrea igual que la medicion de
    consumo de recursos, en **nucleos ocupados**.
``cuanto pesa en disco``
    Y aca hay una trampa que conviene declarar: la tabla es una hipertabla
    comprimida, y **la compresion no ocurre al escribir**. Lo que se mide justo
    despues es el tamano sin comprimir de los fragmentos nuevos; el tamano final
    llega cuando la politica los comprime. Se informan los dos y se dice cual es
    cual.

POR QUE NO SE MIDE CONTRA UNA LINEA DE BASE EN REPOSO
-----------------------------------------------------
La medicion de consumo de recursos si lo hace, porque alli interesa el costo
**incremental** de una carga sobre un sistema que ya corre. Aca interesa el costo
**total** de la operacion: cuanto de la maquina se lleva mientras dura. Restarle
un reposo daria un numero mas chico y menos util para decidir si conviene
correrla mientras alguien usa el equipo.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from backend import db  # noqa: E402

sys.path.insert(0, str(RAIZ / "scripts"))
from medir_consumo_de_recursos import (  # noqa: E402
    _muestra_de_contenedores,
    _muestra_de_procesos,
)

PERIODO_S = 10.0


def _tamano_de_la_tabla() -> dict:
    """Lo que la tabla ocupa, separando lo comprimido de lo que no lo esta."""

    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        # `pg_total_relation_size` sobre una hipertabla devuelve **cero**: la
        # tabla padre esta vacia y los datos viven en los fragmentos. Es una
        # respuesta plausible y falsa, de la clase que este trabajo persigue.
        cursor.execute("select hypertable_size('telemetry_messages')")
        total = cursor.fetchone()[0]
        cursor.execute("select count(*) from telemetry_messages")
        filas = cursor.fetchone()[0]
        try:
            cursor.execute("""
                select count(*) filter (where is_compressed),
                       count(*) filter (where not is_compressed)
                from timescaledb_information.chunks
                where hypertable_name = 'telemetry_messages'""")
            comprimidos, sin_comprimir = cursor.fetchone()
        except Exception:
            comprimidos = sin_comprimir = None
    return {"bytes": total, "filas": filas,
            "fragmentos_comprimidos": comprimidos,
            "fragmentos_sin_comprimir": sin_comprimir}


class Muestreador(threading.Thread):
    """Toma el pulso de la maquina mientras la escritura corre."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.muestras: list[dict] = []
        self._seguir = True

    def run(self) -> None:
        while self._seguir:
            t0 = time.perf_counter()
            try:
                self.muestras.append({
                    "t": round(time.perf_counter(), 1),
                    "procesos": _muestra_de_procesos(),
                    "contenedores": _muestra_de_contenedores(),
                })
            except Exception:
                pass
            sobra = PERIODO_S - (time.perf_counter() - t0)
            if sobra > 0:
                time.sleep(sobra)

    def detener(self) -> None:
        self._seguir = False


def _resumir(muestras: list[dict], clave: str, nombre: str) -> dict:
    valores = [m[clave].get(nombre, {}) for m in muestras]
    nucleos = [v.get("nucleos", 0.0) for v in valores]
    memoria = [v.get("memoria_mb", 0.0) for v in valores]
    return {
        "nucleos_medios": round(sum(nucleos) / len(nucleos), 3) if nucleos else 0.0,
        "nucleos_maximos": round(max(nucleos), 3) if nucleos else 0.0,
        "memoria_mb_media": round(sum(memoria) / len(memoria), 1) if memoria else 0.0,
        "memoria_mb_maxima": round(max(memoria), 1) if memoria else 0.0,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("captura", type=Path)
    ap.add_argument("--vehiculos", required=True)
    ap.add_argument("--salida", type=Path,
                    default=RAIZ / "logs" / "recompletado.json")
    args = ap.parse_args()

    print("  midiendo el tamano de la tabla antes...")
    antes = _tamano_de_la_tabla()
    print(f"    {antes['filas']:,} filas, {antes['bytes'] / 1024**3:.2f} GB")
    print(f"    fragmentos: {antes['fragmentos_comprimidos']} comprimidos, "
          f"{antes['fragmentos_sin_comprimir']} sin comprimir")
    print()

    muestreador = Muestreador()
    muestreador.start()
    t0 = time.perf_counter()

    print(f"  escribiendo los vehiculos {args.vehiculos}...")
    proceso = subprocess.run(
        [sys.executable, "-u", "scripts/republicar_captura.py",
         str(args.captura), "--parrilla-completa",
         "--vehiculos", args.vehiculos],
        cwd=str(RAIZ), capture_output=True, text=True)

    duracion = time.perf_counter() - t0
    muestreador.detener()
    muestreador.join(timeout=15)

    print(proceso.stdout[-3000:] if proceso.stdout else "(sin salida)")
    if proceso.returncode != 0:
        print(f"  la herramienta termino con codigo {proceso.returncode}")
        if proceso.stderr:
            print(proceso.stderr[-1500:])

    print("\n  midiendo el tamano despues...")
    despues = _tamano_de_la_tabla()
    escritas = despues["filas"] - antes["filas"]
    crecio = despues["bytes"] - antes["bytes"]

    piezas = {}
    for nombre in ("tesis-timescaledb", "tesis-mosquitto"):
        piezas[nombre] = _resumir(muestreador.muestras, "contenedores", nombre)
    for nombre in ("consumidor", "servidor de la interfaz"):
        piezas[nombre] = _resumir(muestreador.muestras, "procesos", nombre)

    r = {
        "momento": datetime.now(timezone.utc).isoformat(),
        "captura": args.captura.name,
        "vehiculos": args.vehiculos,
        "duracion_s": round(duracion, 1),
        "filas_escritas": escritas,
        "filas_por_segundo": round(escritas / duracion, 1) if duracion else 0,
        "tabla_antes": antes,
        "tabla_despues": despues,
        "crecimiento_bytes": crecio,
        "bytes_por_fila_sin_comprimir": round(crecio / escritas, 1) if escritas else 0,
        "muestras_de_recursos": len(muestreador.muestras),
        "recursos": piezas,
        "codigo_de_salida": proceso.returncode,
    }
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps(r, indent=1, ensure_ascii=False),
                           encoding="utf-8")

    print()
    print(f"  duracion            : {duracion / 60:,.1f} min")
    print(f"  filas escritas      : {escritas:,}")
    print(f"  ritmo               : {r['filas_por_segundo']:,.0f} filas/s")
    print(f"  la tabla crecio     : {crecio / 1024**3:.2f} GB "
          f"({r['bytes_por_fila_sin_comprimir']:.0f} bytes por fila, SIN comprimir)")
    print(f"  fragmentos despues  : {despues['fragmentos_comprimidos']} comprimidos, "
          f"{despues['fragmentos_sin_comprimir']} sin comprimir")
    print()
    print(f"  {'pieza':26s} {'nucleos':>16s} {'memoria':>18s}")
    for nombre, v in piezas.items():
        print(f"  {nombre[:26]:26s} "
              f"{v['nucleos_medios']:6.3f} ({v['nucleos_maximos']:5.2f}) "
              f"{v['memoria_mb_media']:9.0f} MB ({v['memoria_mb_maxima']:6.0f})")
    print()
    print(f"  detalle en {args.salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
