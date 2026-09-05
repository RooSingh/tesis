# -*- coding: utf-8 -*-
"""Comprueba que se puede operar sobre una hipertabla comprimida.

Por que hace falta
------------------
La medicion de compresion respondio cuanto se ahorra y que pasa con las
consultas. Queda una pregunta anterior a esas dos, que es la que decide si la
conversion es viable: **si despues de comprimir se puede seguir trabajando**.

Tres casos, y el primero es el unico que toca la operacion diaria:

1. **escribir en un fragmento ya comprimido.** El sistema captura todos los dias.
   Si el fragmento del dia estuviera comprimido, cada fila nueva caeria ahi;
2. **modificar y borrar filas comprimidas**, que es lo que hace falta para
   corregir o para retirar filas de instrumentacion;
3. **descomprimir**, que es la garantia de que la decision es reversible.

Que se afirma y que no
----------------------
Cada caso se **ejecuta** y se informa lo que ocurrio, incluido el fallo. No se
cita documentacion: lo que este guion imprime es lo que el motor instalado hizo
sobre datos de este proyecto.

La comprobacion de que no se pierde nada usa **la diferencia de conjuntos en las
dos direcciones**, sobre todas las columnas. Una sola direccion detectaria filas
perdidas y no filas alteradas.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from backend import db  # noqa: E402

ORIGEN = "telemetry_messages"
PLANA = "verif_comprimida_plana"
HIPER = "verif_comprimida_hiper"
SEGMENTAR_POR = "signal_name, session_id, source_type, vehicle_id"


def _intentar(cur, descripcion: str, sql: str, args: tuple = ()) -> dict:
    """Ejecuta y devuelve que paso, sin dejar que un fallo corte la corrida.

    Un fallo **es un resultado**: si no se puede borrar sobre comprimido, eso es
    justamente lo que hay que saber antes de convertir.
    """

    t0 = time.perf_counter()
    try:
        cur.execute(sql, args)
        return {"caso": descripcion, "funciono": True,
                "ms": round((time.perf_counter() - t0) * 1000, 1)}
    except Exception as e:  # noqa: BLE001
        return {"caso": descripcion, "funciono": False,
                "error": type(e).__name__,
                "detalle": str(e).splitlines()[0][:160]}


def _diferencias(cur, a: str, b: str) -> tuple[int, int]:
    cur.execute(f"select count(*) from (select * from {a} except select * from {b}) d")
    faltan = cur.fetchone()[0]
    cur.execute(f"select count(*) from (select * from {b} except select * from {a}) d")
    sobran = cur.fetchone()[0]
    return faltan, sobran


def verificar(filas: int, fuente: str) -> dict:
    r: dict = {"verificado_en": datetime.now(timezone.utc).isoformat(),
               "filas": filas, "fuente": fuente, "casos": []}

    with db.obtener_conexion() as conexion:
        conexion.autocommit = True
        cur = conexion.cursor()

        cur.execute(f"drop table if exists {PLANA}")
        cur.execute(f"drop table if exists {HIPER}")

        print(f"  preparando {filas:,} filas...", flush=True)
        cur.execute(f"create table {PLANA} as select * from {ORIGEN} "
                    f"where source_type = %s limit %s", (fuente, filas))
        cur.execute(f"create table {HIPER} (like {PLANA} including defaults)")
        cur.execute("select create_hypertable(%s::regclass, "
                    "by_range('timestamp', interval '1 day'))", (HIPER,))
        cur.execute(f"insert into {HIPER} select * from {PLANA}")
        cur.execute(f"alter table {HIPER} set (timescaledb.compress, "
                    f"timescaledb.compress_segmentby = '{SEGMENTAR_POR}', "
                    f"timescaledb.compress_orderby = 'timestamp')")
        cur.execute(f"select compress_chunk(c) from show_chunks('{HIPER}') c")
        cur.execute(f"analyze {HIPER}")

        cur.execute(f"select count(*) from {HIPER}")
        r["filas_tras_comprimir"] = cur.fetchone()[0]

        # --- caso 1: escribir sobre comprimido -----------------------------
        print("  1. escribir en un fragmento comprimido...", flush=True)
        caso = _intentar(
            cur, "insertar en fragmento comprimido",
            f"insert into {HIPER} select * from {PLANA} limit 1000")
        if caso["funciono"]:
            cur.execute(f"select count(*) from {HIPER}")
            caso["filas_despues"] = cur.fetchone()[0]
            # Que la insercion no falle no alcanza: hay que poder **leerlas**.
            cur.execute(f"select count(*) from {HIPER} where source_type = %s",
                        (fuente,))
            caso["se_pueden_leer"] = cur.fetchone()[0] > r["filas_tras_comprimir"]
        r["casos"].append(caso)

        # --- caso 2: modificar y borrar ------------------------------------
        print("  2. modificar y borrar sobre comprimido...", flush=True)
        cur.execute(f"select signal_name from {HIPER} limit 1")
        senal = cur.fetchone()[0]
        r["casos"].append(_intentar(
            cur, "actualizar filas comprimidas",
            f"update {HIPER} set quality_flag = 'verificacion' "
            f"where signal_name = %s", (senal,)))
        r["casos"].append(_intentar(
            cur, "borrar filas comprimidas",
            f"delete from {HIPER} where signal_name = %s", (senal,)))

        # --- caso 3: descomprimir ------------------------------------------
        print("  3. descomprimir...", flush=True)
        caso = _intentar(cur, "descomprimir todos los fragmentos",
                         f"select decompress_chunk(c, true) "
                         f"from show_chunks('{HIPER}') c")
        if caso["funciono"]:
            cur.execute(f"analyze {HIPER}")
            cur.execute(f"select count(*) from {HIPER}")
            caso["filas_tras_descomprimir"] = cur.fetchone()[0]
        r["casos"].append(caso)

        # --- la vuelta completa, sin tocar nada ----------------------------
        #
        # Se rehace desde cero para que la comparacion sea contra datos
        # intactos: la hipertabla de arriba quedo modificada por los casos 2 y
        # 3, que es justamente lo que se queria probar.
        print("  4. vuelta completa comprimir y descomprimir...", flush=True)
        cur.execute(f"drop table if exists {HIPER}")
        cur.execute(f"create table {HIPER} (like {PLANA} including defaults)")
        cur.execute("select create_hypertable(%s::regclass, "
                    "by_range('timestamp', interval '1 day'))", (HIPER,))
        cur.execute(f"insert into {HIPER} select * from {PLANA}")
        cur.execute(f"alter table {HIPER} set (timescaledb.compress, "
                    f"timescaledb.compress_segmentby = '{SEGMENTAR_POR}', "
                    f"timescaledb.compress_orderby = 'timestamp')")
        cur.execute(f"select compress_chunk(c) from show_chunks('{HIPER}') c")
        cur.execute(f"select decompress_chunk(c, true) from show_chunks('{HIPER}') c")
        faltan, sobran = _diferencias(cur, PLANA, HIPER)
        r["vuelta_completa"] = {
            "faltan": faltan, "sobran": sobran,
            "identicas": faltan == 0 and sobran == 0,
        }

        cur.execute(f"drop table if exists {PLANA}")
        cur.execute(f"drop table if exists {HIPER}")
    return r


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--filas", type=int, default=200_000)
    ap.add_argument("--fuente", default="f1_25_udp_simulation")
    ap.add_argument("--salida", type=Path,
                    default=RAIZ / "logs" / "verificacion_hipertabla.json")
    args = ap.parse_args()

    r = verificar(args.filas, args.fuente)
    args.salida.write_text(json.dumps(r, indent=2, ensure_ascii=False),
                           encoding="utf-8")

    print()
    for c in r["casos"]:
        estado = "FUNCIONA" if c["funciono"] else "NO FUNCIONA"
        extra = ""
        if c["funciono"]:
            extra = f"  ({c['ms']} ms)"
            if "se_pueden_leer" in c:
                extra += "  y se leen" if c["se_pueden_leer"] else "  PERO NO SE LEEN"
        else:
            extra = f"  {c['error']}: {c['detalle']}"
        print(f"  {c['caso']:<42} {estado}{extra}")
    v = r["vuelta_completa"]
    print()
    print(f"  vuelta completa: faltan {v['faltan']}, sobran {v['sobran']}  "
          f"-> {'identicas' if v['identicas'] else 'HAY DIFERENCIAS'}")
    print(f"  detalle en {args.salida}")


if __name__ == "__main__":
    main()
