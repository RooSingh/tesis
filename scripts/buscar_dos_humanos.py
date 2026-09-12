# -*- coding: utf-8 -*-
"""Busca en las capturas de F1 25 si alguna tiene dos conductores humanos.

POR QUE ESTA PRUEBA Y NO LA OTRA
--------------------------------
El registro ya habia verificado el campo `secondary_player_car_index`, que vale
255 cuando no hay segundo jugador, y concluyo que ninguna captura tiene dos
conductores. Esa prueba es valida pero tiene un punto ciego: **ese campo describe
la pantalla dividida del jugador local**, y hay formas de que dos personas
conduzcan que no lo enciendan.

El paquete de participantes ofrece una prueba independiente y mas directa:
declara por vehiculo si lo controla la maquina. **Dos vehiculos con
`ai_controlled` en falso son dos conductores que no son la maquina**, venga de
pantalla dividida o de donde venga.

Las dos pruebas juntas son mas fuertes que cualquiera sola: si las dos dicen que
no hay segundo humano, no lo hay; si se contradicen, la contradiccion es el
hallazgo.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from backend import f1_capture, f1_udp  # noqa: E402


def revisar(ruta: Path, tope_paquetes: int = 400_000) -> dict:
    """Cuenta, sobre los paquetes de participantes, cuantos vehiculos no son IA."""

    humanos_por_paquete: Counter[int] = Counter()
    nombres_humanos: set[str] = set()
    segundo_jugador: Counter[int] = Counter()
    participantes = 0
    leidos = 0

    for d in f1_capture.leer_captura(ruta):
        leidos += 1
        if leidos > tope_paquetes:
            break
        try:
            x = f1_udp.decodificar(d.carga)
        except f1_udp.ErrorDecodificacion:
            continue

        idx = x.get("cabecera", {}).get("secondary_player_car_index")
        if idx is not None:
            segundo_jugador[idx] += 1

        if x["paquete"] != "participants":
            continue
        participantes += 1
        cuantos = 0
        for i, v in enumerate(x.get("vehiculos", [])):
            # Un vehiculo sin piloto declara nombre vacio; no se lo cuenta.
            if not (v.get("name") or "").strip():
                continue
            if not v.get("ai_controlled"):
                cuantos += 1
                nombres_humanos.add(f"car:{i} {v.get('name', '').strip()}")
        humanos_por_paquete[cuantos] += 1

    return {
        "archivo": ruta.name,
        "paquetes_leidos": leidos - 1,
        "paquetes_de_participantes": participantes,
        "humanos_por_paquete": dict(sorted(humanos_por_paquete.items())),
        "quienes": sorted(nombres_humanos),
        "secondary_player_car_index": dict(sorted(segundo_jugador.items())),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--patron", default="*dos-conductores*.f1raw")
    ap.add_argument("--minimo-mb", type=float, default=50.0,
                    help="Se saltean las capturas chicas: una de pocos MB no "
                         "contiene una carrera.")
    ap.add_argument("--tope-paquetes", type=int, default=400_000)
    args = ap.parse_args()

    base = RAIZ / "datasets" / "f1_25" / "capturas"
    archivos = sorted(p for p in base.glob(args.patron)
                      if p.suffix == ".f1raw"
                      and p.stat().st_size / 1024**2 >= args.minimo_mb)

    print(f"  {len(archivos)} capturas de mas de {args.minimo_mb:.0f} MB\n")
    con_dos = []
    for p in archivos:
        r = revisar(p, args.tope_paquetes)
        hum = r["humanos_por_paquete"]
        maximo = max(hum) if hum else 0
        marca = "  <-- DOS O MAS" if maximo >= 2 else ""
        sp = r["secondary_player_car_index"]
        sin255 = {k: v for k, v in sp.items() if k != 255}
        print(f"  {p.name[:58]:58s} {p.stat().st_size/1024**2:7.1f} MB  "
              f"humanos={hum}  2do_jugador_distinto_de_255={sin255 or '-'}{marca}")
        if maximo >= 2:
            con_dos.append(r)

    if con_dos:
        print(f"\n  {len(con_dos)} captura(s) con dos o mas conductores no IA:")
        for r in con_dos:
            print(f"    {r['archivo']}")
            for q in r["quienes"]:
                print(f"      {q}")
    else:
        print("\n  ninguna captura declara dos conductores que no sean la maquina")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
