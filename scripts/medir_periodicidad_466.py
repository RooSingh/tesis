# -*- coding: utf-8 -*-
"""Mide la periodicidad del identificador 466 con el mismo procedimiento que los quince de la tabla.

POR QUE HACE FALTA
------------------
El catalogo del generador le asigna al identificador 466 un periodo de 20 ms, pero
el 466 **no esta entre los quince identificadores de mayor volumen** que la tabla
de periodicidad recoge, de modo que ese numero no tiene una medicion detras.

EL PROCEDIMIENTO ES EL DE `day2_rav4_exploration.py`, Y ESO NO ES UN DETALLE
----------------------------------------------------------------------------
Una cifra medida con otro criterio no seria comparable con las quince ya
publicadas. Dos partes del criterio importan especialmente:

1. **El intervalo se mide entre EVENTOS, no entre tramas.** Un evento `can` del
   registro agrupa varias tramas, y un mismo identificador puede aparecer mas de
   una vez dentro del mismo evento ---el 550 aporta dos---. Contar tramas y
   dividir por la duracion da un periodo que es la mitad del real.

2. **Un identificador cuenta una sola vez por evento**, aunque traiga varias
   tramas. Es lo que hace `seen_in_event` en el guion original y lo que separa la
   columna «Tramas» de la columna «Eventos» de la tabla publicada.

Se informan ademas las tramas por evento, que es lo que permite saber si el 466 se
comporta como el 550 ---dos por evento--- o como los que aportan una sola.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

import zstandard as zstd  # noqa: E402

# Las mismas dos rutas que `day2_rav4_exploration.py`, para leer con el mismo
# esquema con el que se midieron los quince publicados.
sys.path.append(str(RAIZ / "external" / "openpilot"))
sys.path.append(str(RAIZ / "datasets" / "openDBC" / "raw" / "opendbc"))

from openpilot.cereal import log as capnp_log  # noqa: E402


def _ms(ns: float) -> float:
    return ns / 1_000_000.0


def medir(muestra: Path, identificadores: set[int]) -> dict:
    crudo = zstd.ZstdDecompressor().decompress(muestra.read_bytes())

    tramas: Counter[int] = Counter()
    eventos_por_id: dict[int, list[int]] = defaultdict(list)
    #: Cuantas tramas del mismo identificador trae cada evento donde aparece.
    tramas_por_evento: dict[int, Counter[int]] = defaultdict(Counter)
    cargas: dict[int, Counter[str]] = defaultdict(Counter)
    eventos_can = 0
    primero = ultimo = None

    for evt in capnp_log.Event.read_multiple_bytes(crudo):
        if evt.which() != "can":
            continue
        eventos_can += 1
        if primero is None:
            primero = evt.logMonoTime
        ultimo = evt.logMonoTime

        cuenta_en_este: Counter[int] = Counter()
        for msg in evt.can:
            if msg.address not in identificadores:
                continue
            tramas[msg.address] += 1
            cuenta_en_este[msg.address] += 1
            cargas[msg.address][bytes(msg.dat).hex()] += 1
        for addr, cuantas in cuenta_en_este.items():
            eventos_por_id[addr].append(evt.logMonoTime)
            tramas_por_evento[addr][cuantas] += 1

    salida: dict = {
        "muestra": str(muestra.relative_to(RAIZ)),
        "eventos_can_en_la_muestra": eventos_can,
        "duracion_s": round(_ms(ultimo - primero) / 1000.0, 3)
        if primero is not None else None,
        "identificadores": {},
    }

    for addr in sorted(identificadores):
        ts = eventos_por_id.get(addr, [])
        difs = [b - a for a, b in zip(ts, ts[1:])]
        salida["identificadores"][str(addr)] = {
            "tramas": tramas[addr],
            "eventos": len(ts),
            "tramas_por_evento": dict(sorted(tramas_por_evento[addr].items())),
            "cargas_unicas": len(cargas[addr]),
            "media_ms": round(_ms(statistics.mean(difs)), 3) if difs else None,
            "mediana_ms": round(_ms(statistics.median(difs)), 3) if difs else None,
            "min_ms": round(_ms(min(difs)), 3) if difs else None,
            "max_ms": round(_ms(max(difs)), 3) if difs else None,
        }
    return salida


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--muestras", type=int, default=1,
                    help="Cuantas muestras consecutivas medir, desde sample_01.")
    ap.add_argument("--identificadores", default="466,550,170",
                    help="El 550 y el 170 van de control: sus cifras ya estan "
                         "publicadas y tienen que reproducirse.")
    ap.add_argument("--salida", type=Path,
                    default=RAIZ / "logs" / "periodicidad_466.json")
    args = ap.parse_args()

    ids = {int(x) for x in args.identificadores.split(",") if x.strip()}
    base = RAIZ / "datasets" / "commaCarSegments" / "raw" / "TOYOTA_RAV4_TSS2"

    resultados = []
    for n in range(1, args.muestras + 1):
        muestra = base / f"sample_{n:02d}" / "rlog.zst"
        if not muestra.exists():
            print(f"  no existe {muestra.relative_to(RAIZ)}, se detiene")
            break
        print(f"  midiendo {muestra.parent.name}...")
        resultados.append(medir(muestra, ids))

    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps(resultados, indent=1, ensure_ascii=False),
                           encoding="utf-8")

    for r in resultados:
        print(f"\n  {r['muestra']}")
        print(f"  duracion: {r['duracion_s']} s   "
              f"eventos can: {r['eventos_can_en_la_muestra']:,}")
        print(f"    {'id':>5} {'tramas':>8} {'eventos':>8} {'tr/ev':>10} "
              f"{'media':>8} {'mediana':>8} {'min':>8} {'max':>8}")
        for addr, v in r["identificadores"].items():
            tpe = ", ".join(f"{k}x{c}" for k, c in v["tramas_por_evento"].items())
            print(f"    {addr:>5} {v['tramas']:>8,} {v['eventos']:>8,} "
                  f"{tpe:>10} {str(v['media_ms']):>8} {str(v['mediana_ms']):>8} "
                  f"{str(v['min_ms']):>8} {str(v['max_ms']):>8}")
    print(f"\n  detalle en {args.salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
