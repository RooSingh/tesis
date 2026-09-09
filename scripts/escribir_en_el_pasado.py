# -*- coding: utf-8 -*-
"""Descomprime los fragmentos de una sesion, corre una escritura, y recomprime.

POR QUE HACE FALTA
------------------
Insertar en una hipertabla **comprimida** obliga al motor a descomprimir los
fragmentos donde caen las filas nuevas, y hay un tope por transaccion:

    tuple decompression limit exceeded by operation
    current limit: 100000, tuples decompressed: 113000

Subir ese tope hace pasar la escritura pero deja al motor descomprimiendo y
recomprimiendo de a pedazos dentro de cada transaccion, que es la forma cara de
hacerlo. Descomprimir **una vez** los fragmentos afectados, escribir sobre
fragmentos planos y recomprimir al final es lo que la documentacion recomienda
para una carga grande, y ademas deja tres tiempos separados en lugar de uno.

QUE FRAGMENTOS TOCA, Y POR QUE SON POCOS
----------------------------------------
Los que cubren la ventana temporal de la sesion, y nada mas. Es poco porque las
marcas de los rivales **son las mismas que las del vehiculo propio**: se derivan
del reloj de sesion de la fuente, de modo que caen exactamente en los mismos
fragmentos. Para la carrera de Spa son dos, de una hora cada uno.

QUE PASA SI SE INTERRUMPE
-------------------------
Los fragmentos quedan descomprimidos. No se pierde una fila ---descomprimir es
reversible y no toca el contenido--- pero la tabla ocupa mas hasta que se los
recomprima. Este guion recomprime en un `finally`, y si aun asi quedara a medias,
volver a correrlo con `--solo-recomprimir` lo cierra.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from backend import db  # noqa: E402


def _fragmentos(session_id: str) -> list[tuple[str, bool]]:
    with db.obtener_conexion() as c, c.cursor() as cur:
        cur.execute("""select min(timestamp), max(timestamp)
                       from telemetry_messages where session_id = %s""",
                    (session_id,))
        desde, hasta = cur.fetchone()
        if desde is None:
            raise SystemExit(f"La sesion {session_id} no tiene filas.")
        cur.execute("""select format('%%I.%%I', chunk_schema, chunk_name),
                              is_compressed
                       from timescaledb_information.chunks
                       where hypertable_name = 'telemetry_messages'
                         and range_end > %s and range_start <= %s
                       order by range_start""", (desde, hasta))
        return [(f[0], f[1]) for f in cur.fetchall()]


def _tamano() -> tuple[int, int]:
    with db.obtener_conexion() as c, c.cursor() as cur:
        # `from` incluido: sin el, `count(*)` cuenta la unica fila
        # implicita de un select sin tabla y devuelve 1.
        cur.execute("select count(*), hypertable_size('telemetry_messages') "
                    "from telemetry_messages")
        return cur.fetchone()


def _aplicar(fragmentos: list[str], funcion: str) -> float:
    """`decompress_chunk` o `compress_chunk` sobre cada uno, y cuanto tardo."""

    t0 = time.perf_counter()
    with db.obtener_conexion() as c:
        c.autocommit = True
        with c.cursor() as cur:
            for f in fragmentos:
                try:
                    cur.execute(f"select {funcion}('{f}')")
                    print(f"    {funcion:18s} {f}")
                except Exception as error:
                    # Un fragmento ya en el estado pedido no es un fallo.
                    print(f"    {funcion:18s} {f}  ({type(error).__name__})")
    return time.perf_counter() - t0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sesion", required=True)
    ap.add_argument("--comando", nargs=argparse.REMAINDER, default=[],
                    help="Lo que se ejecuta con los fragmentos descomprimidos.")
    ap.add_argument("--solo-recomprimir", action="store_true",
                    help="Cierra una corrida que quedo a medias.")
    args = ap.parse_args()

    fragmentos = _fragmentos(args.sesion)
    nombres = [f for f, _ in fragmentos]
    print(f"  fragmentos de la sesion: {len(nombres)}")
    for f, comprimido in fragmentos:
        print(f"    {f}  comprimido={comprimido}")

    if args.solo_recomprimir:
        print("\n  recomprimiendo...")
        t = _aplicar(nombres, "compress_chunk")
        print(f"  recomprimido en {t / 60:.1f} min")
        return 0

    filas_antes, bytes_antes = _tamano()
    print(f"\n  antes: {filas_antes:,} filas, {bytes_antes / 1024**3:.2f} GB")

    print("\n  descomprimiendo...")
    t_desc = _aplicar(nombres, "decompress_chunk")
    _, bytes_planos = _tamano()
    print(f"  descomprimido en {t_desc / 60:.1f} min "
          f"({bytes_planos / 1024**3:.2f} GB, "
          f"{(bytes_planos - bytes_antes) / 1024**3:+.2f})")

    t_escritura = 0.0
    codigo = 0
    try:
        if args.comando:
            print(f"\n  ejecutando: {' '.join(args.comando[:4])} ...")
            t0 = time.perf_counter()
            r = subprocess.run(args.comando, cwd=str(RAIZ))
            t_escritura = time.perf_counter() - t0
            codigo = r.returncode
            print(f"  la escritura termino con codigo {codigo} "
                  f"en {t_escritura / 60:.1f} min")
    finally:
        # Recomprimir SIEMPRE. Dejar los fragmentos planos por un fallo de la
        # escritura seria pagar el espacio sin haber conseguido nada.
        print("\n  recomprimiendo...")
        t_rec = _aplicar(nombres, "compress_chunk")
        filas_fin, bytes_fin = _tamano()
        print(f"  recomprimido en {t_rec / 60:.1f} min")
        print()
        print(f"  filas escritas : {filas_fin - filas_antes:,}")
        print(f"  descompresion  : {t_desc / 60:6.1f} min")
        print(f"  escritura      : {t_escritura / 60:6.1f} min")
        print(f"  recompresion   : {t_rec / 60:6.1f} min")
        print(f"  TOTAL          : {(t_desc + t_escritura + t_rec) / 60:6.1f} min")
        print(f"  la tabla       : {bytes_antes / 1024**3:.2f} -> "
              f"{bytes_fin / 1024**3:.2f} GB")
        if filas_fin > filas_antes:
            print(f"  por fila       : "
                  f"{(bytes_fin - bytes_antes) / (filas_fin - filas_antes):.1f} bytes")

    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
