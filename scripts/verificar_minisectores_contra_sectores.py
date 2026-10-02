# -*- coding: utf-8 -*-
"""Contrasta los codigos de minisector de OpenF1 contra los tiempos oficiales por sector.

POR QUE HACE FALTA
------------------
La lectura de los codigos ---2051 mejor tiempo de la sesion en ese tramo, 2049 mejor
personal, 2048 ninguno de los dos--- se obtuvo contrastando su distribucion contra la
duracion de la vuelta (`backend/session_analysis.py:44-53`). El informe afirmaba ademas
que se habia verificado contra los tiempos oficiales por sector, y esa verificacion no
existia. Este guion la corre.

QUE LA HACE INDEPENDIENTE
-------------------------
Los tiempos por sector (`duration_sector_1..3`) no se usaron para construir la lectura.
Si la lectura es correcta, los sectores que marcan un mejor tiempo tienen que traer los
codigos de mejor tiempo en sus minisectores, y los que no marcan nada, no.

COMO SE CLASIFICA CADA SECTOR
-----------------------------
Los codigos describen el estado **en el momento** en que el vehiculo paso por el tramo:
un 2051 es «mejor de la sesion hasta ahora», no «mejor de toda la sesion». Por eso se
recorren los sectores en orden cronologico ---el instante en que cada uno termina es el
inicio de la vuelta mas la suma de los sectores ya completados--- llevando dos mejores
tiempos corrientes: el de la sesion por sector, y el de cada piloto por sector. Cada
sector cae en una clase:

``mejor_sesion``   su tiempo baja el mejor de la sesion en ese sector;
``mejor_personal`` baja el mejor del piloto, sin bajar el de la sesion;
``ninguno``        no baja ninguno de los dos.

El primer sector de cada piloto es por definicion su mejor personal, y el primero de
la sesion es el mejor de la sesion: se informan igual, pero se cuentan tambien aparte.

LO QUE NO SE PUEDE EXIGIR
-------------------------
La relacion es estadistica y no uno a uno: un minisector puede ser el mejor de la sesion
sin que lo sea el sector entero, y un sector puede ser el mejor sin que lo sea cada uno
de sus minisectores. Lo que se mide es si la proporcion de cada codigo ordena las clases
como la lectura predice.

Uso
---
    python -B scripts/verificar_minisectores_contra_sectores.py \\
        datasets/OpenF1/raw/2025/9947/laps.json --salida docs/mediciones/minisectores_contra_sectores.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

CODIGO_SESION = 2051
CODIGO_PERSONAL = 2049
CODIGO_NINGUNO = 2048
#: Minisector recorrido por la calle de boxes (`informe/RESPUESTAS_FALTA_DATO.md:495-499`).
CODIGO_BOXES = 2064
CODIGOS_DE_TIEMPO = (CODIGO_SESION, CODIGO_PERSONAL, CODIGO_NINGUNO)
CLASES = ("mejor_sesion", "mejor_personal", "ninguno")


def eventos_de_sector(vueltas: list[dict]) -> list[dict]:
    """Un evento por sector con tiempo oficial, con el instante en que termina."""

    eventos = []
    for v in vueltas:
        if not v.get("date_start"):
            continue
        inicio = datetime.fromisoformat(v["date_start"])
        acumulado = 0.0
        for k in (1, 2, 3):
            duracion = v.get(f"duration_sector_{k}")
            if duracion is None:
                break           # sin este sector no se puede ubicar el siguiente
            acumulado += duracion
            eventos.append({
                "fin": inicio + timedelta(seconds=acumulado),
                "piloto": v["driver_number"],
                "vuelta": v["lap_number"],
                "sector": k,
                "tiempo": duracion,
                "codigos": list(v.get(f"segments_sector_{k}") or []),
                "salida_de_boxes": bool(v.get("is_pit_out_lap")),
            })
    return sorted(eventos, key=lambda e: e["fin"])


def clasificar(eventos: list[dict]) -> None:
    """Agrega `clase` y `primero` a cada evento, con mejores corrientes."""

    mejor_sesion: dict[int, float] = {}
    mejor_piloto: dict[tuple[int, int], float] = {}
    for e in eventos:
        k, p, t = e["sector"], e["piloto"], e["tiempo"]
        # UN SECTOR QUE PASA POR BOXES NO COMPITE. Su tiempo no es de pista ---el de
        # entrada sale corto por la calle de boxes--- y si bajara el mejor corriente
        # dejaria mal clasificados todos los sectores genuinos que vienen despues.
        if e["salida_de_boxes"] or CODIGO_BOXES in e["codigos"]:
            e["primero"] = False
            e["clase"] = "paso_por_boxes"
            continue
        previo_sesion = mejor_sesion.get(k)
        previo_piloto = mejor_piloto.get((p, k))
        e["primero"] = previo_piloto is None
        if previo_sesion is None or t < previo_sesion:
            e["clase"] = "mejor_sesion"
        elif previo_piloto is None or t < previo_piloto:
            e["clase"] = "mejor_personal"
        else:
            e["clase"] = "ninguno"
        if previo_sesion is None or t < previo_sesion:
            mejor_sesion[k] = t
        if previo_piloto is None or t < previo_piloto:
            mejor_piloto[(p, k)] = t


def resumir(eventos: list[dict]) -> dict:
    por_clase: dict[str, dict] = {}
    for clase in CLASES:
        sel = [e for e in eventos if e["clase"] == clase]
        codigos = Counter(c for e in sel for c in e["codigos"] if c in CODIGOS_DE_TIEMPO)
        total = sum(codigos.values())
        por_clase[clase] = {
            "sectores": len(sel),
            "de_ellos_primer_sector_del_piloto": sum(1 for e in sel if e["primero"]),
            "minisectores_con_codigo_de_tiempo": total,
            "pct_2051": round(100 * codigos[CODIGO_SESION] / total, 2) if total else None,
            "pct_2049": round(100 * codigos[CODIGO_PERSONAL] / total, 2) if total else None,
            "pct_2048": round(100 * codigos[CODIGO_NINGUNO] / total, 2) if total else None,
            "sectores_con_algun_2051": sum(1 for e in sel if CODIGO_SESION in e["codigos"]),
            "sectores_con_algun_2049_o_2051": sum(
                1 for e in sel if CODIGO_SESION in e["codigos"] or CODIGO_PERSONAL in e["codigos"]),
            "sectores_solo_2048": sum(
                1 for e in sel if e["codigos"] and all(c == CODIGO_NINGUNO for c in e["codigos"] if c in CODIGOS_DE_TIEMPO)
                and any(c in CODIGOS_DE_TIEMPO for c in e["codigos"])),
        }
    return por_clase


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("laps", type=Path, help="laps.json de una sesion de OpenF1")
    ap.add_argument("--salida", type=Path, default=None)
    args = ap.parse_args()

    vueltas = json.loads(args.laps.read_text(encoding="utf-8"))
    eventos = eventos_de_sector(vueltas)
    clasificar(eventos)

    todos = resumir(eventos)
    sin_primeros = resumir([e for e in eventos if not e["primero"]])
    sin_boxes = resumir([e for e in eventos if not e["primero"] and not e["salida_de_boxes"]])
    # LA VUELTA DE ENTRADA A BOXES NO SE MARCA, PERO SE VE: su sector 3 termina en la
    # calle de boxes, con los ultimos minisectores en 2064. `clasificar` ya no los deja
    # competir; aca se los excluye tambien del resumen.
    def limpio(e):
        return not e["primero"] and not e["salida_de_boxes"] and CODIGO_BOXES not in e["codigos"]
    sin_paso_por_boxes = resumir([e for e in eventos if limpio(e)])

    # Los casos que contradicen la lectura de forma directa.
    mejor_sesion_sin_2051 = [
        {k: e[k] for k in ("piloto", "vuelta", "sector", "tiempo", "codigos")}
        for e in eventos if e["clase"] == "mejor_sesion" and limpio(e)
        and CODIGO_SESION not in e["codigos"]]
    ninguno_con_2051 = [
        {k: e[k] for k in ("piloto", "vuelta", "sector", "tiempo", "codigos")}
        for e in eventos if e["clase"] == "ninguno" and limpio(e) and CODIGO_SESION in e["codigos"]]

    resultado = {
        "fuente": str(args.laps).replace("\\", "/"),
        "vueltas": len(vueltas),
        "sectores_con_tiempo": len(eventos),
        "criterio": "mejores tiempos corrientes, en orden del instante en que termina cada sector",
        "todos": todos,
        "sin_primer_sector_de_cada_piloto": sin_primeros,
        "sin_primeros_ni_salidas_de_boxes": sin_boxes,
        "sin_primeros_ni_paso_por_boxes": sin_paso_por_boxes,
        "sectores_con_paso_por_boxes": sum(1 for e in eventos if e["clase"] == "paso_por_boxes"),
        "mejor_sesion_sin_ningun_2051": mejor_sesion_sin_2051,
        "ninguno_con_algun_2051_cantidad": len(ninguno_con_2051),
        "ninguno_con_algun_2051_muestra": ninguno_con_2051[:15],
    }

    for nombre in ("todos", "sin_primer_sector_de_cada_piloto", "sin_primeros_ni_salidas_de_boxes", "sin_primeros_ni_paso_por_boxes"):
        print(f"\n{nombre}:")
        for clase, r in resultado[nombre].items():
            print(f"  {clase:<15} sectores {r['sectores']:>4}  2051 {r['pct_2051']}%  "
                  f"2049 {r['pct_2049']}%  2048 {r['pct_2048']}%  "
                  f"con algun 2051 {r['sectores_con_algun_2051']}  "
                  f"con 2049 o 2051 {r['sectores_con_algun_2049_o_2051']}  solo 2048 {r['sectores_solo_2048']}")
    print(f"\nmejor de sesion sin ningun 2051 (sin primeros): {len(mejor_sesion_sin_2051)}")
    print(f"sin primeros ni paso por boxes: ninguno con algun 2051: {len(ninguno_con_2051)}")

    if args.salida:
        args.salida.parent.mkdir(parents=True, exist_ok=True)
        args.salida.write_text(json.dumps(resultado, indent=1, ensure_ascii=False, default=str),
                               encoding="utf-8")
        print(f"\ndetalle en {args.salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
