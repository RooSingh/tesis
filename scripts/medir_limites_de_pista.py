# -*- coding: utf-8 -*-
"""Contrasta la definicion reglamentaria de salida de pista contra el dato.

El criterio de este trabajo para decidir cuando un vehiculo esta fuera de pista
venia siendo propio: **tres o mas ruedas sobre una superficie que no fuera
asfalto ni piano**. Los dos numeros —el tres y la lista de superficies— se
habian elegido calibrando contra vueltas limpias, que es un metodo razonable
para un umbral fisico y no lo es para una definicion normativa: *estar fuera de
pista* no es una magnitud que se mida, es una condicion que el reglamento
define.

El articulo 33.3 del Reglamento Deportivo de Formula 1 la define asi:

    "Drivers will be judged to have left the track if no part of the car remains
    in contact with it and, for the avoidance of doubt, any white lines defining
    the track edges are considered to be part of the track but the kerbs are
    not."

    -- FIA, 2025 Formula 1 Sporting Regulations, Issue 5, art. 33.3, pag. 40

De ahi salen dos correcciones al criterio anterior, y van en sentidos opuestos:

* **el piano no es pista.** El criterio propio lo trataba como superficie normal,
  de modo que un vehiculo con las cuatro ruedas sobre el piano nunca se anotaba;

* **hace falta que salga todo el vehiculo.** El criterio propio anotaba con tres
  ruedas; el reglamento exige que **ninguna parte** siga en contacto con la pista.

Que las dos correcciones se compensen en parte es justamente el motivo de medir
antes de cambiar nada.

**Lo que este guion mide, y lo que no.** El reglamento habla del vehiculo y el
canal informa cuatro ruedas. Un vehiculo puede tener la carroceria sobre la pista
con las cuatro ruedas afuera, y ese caso el canal no lo distingue. Lo que se mide
aca es **la mejor aproximacion disponible**: ninguna de las cuatro ruedas sobre
asfalto. Se declara como aproximacion y no como la definicion.

Uso:

    PYTHONPATH=. .venv/Scripts/python.exe scripts/medir_limites_de_pista.py
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from backend import f1_capture, f1_udp  # noqa: E402

CAPTURAS = RAIZ / "datasets" / "f1_25" / "capturas"

#: Codigo de superficie que representa la pista.
#:
#: El asfalto. Las lineas blancas que delimitan el borde **son** pista segun el
#: articulo 33.3, y el canal no las distingue del asfalto, de modo que quedan
#: correctamente incluidas sin hacer nada.
ASFALTO = 0

#: Cuanto tiene que durar una salida para anotarla.
#:
#: **Cero, porque el articulo 33.3 no fija duracion minima.** Filtrar las salidas
#: cortas es una decision de presentacion y no forma parte de la definicion.
#:
#: El valor importa: con tres metros de minimo, la vuelta 5 de la captura con
#: asistencia —que el juego invalido por salirse— no registraba ninguna salida,
#: porque el instante con las cuatro ruedas sobre el piano dura unos dos metros.
#: El umbral propio estaba escondiendo justamente el caso que habia que explicar.
MINIMO_SALIDA_M = 0.0


def leer(captura: Path) -> list[dict]:
    marcos: dict[int, dict] = {}
    for datagrama in f1_capture.leer_captura(captura):
        try:
            decodificado = f1_udp.decodificar(datagrama.carga)
        except Exception:
            continue
        propio = decodificado.get("vehiculo_propio")
        if not decodificado.get("decodificado") or propio is None:
            continue
        entrada = marcos.setdefault(
            decodificado["cabecera"]["frame_identifier"], {})
        if decodificado["paquete"] == "lap_data":
            entrada["dist"] = propio["lap_distance_m"]
            entrada["vuelta"] = propio["current_lap_num"]
            entrada["invalida"] = propio["current_lap_invalid"]
        elif decodificado["paquete"] == "car_telemetry":
            entrada["sup"] = propio["surface_type"]
            entrada["vel"] = propio["speed_kmh"]

    return sorted(
        (e for e in marcos.values()
         if {"dist", "vuelta", "invalida", "sup", "vel"} <= e.keys()),
        key=lambda e: (e["vuelta"], e["dist"]))


def salidas_reglamentarias(marcos: list[dict]) -> list[dict]:
    """Tramos en que ninguna rueda esta sobre la pista."""

    tramos, abierto = [], None
    for marco in marcos:
        codigos = list(marco["sup"].values())
        fuera = all(c != ASFALTO for c in codigos)
        if fuera:
            if abierto and abierto["vuelta"] == marco["vuelta"] \
                    and marco["dist"] - abierto["hasta"] < 10:
                abierto["hasta"] = marco["dist"]
                abierto["superficies"].update(codigos)
            else:
                if abierto:
                    tramos.append(abierto)
                abierto = {"vuelta": marco["vuelta"], "desde": marco["dist"],
                           "hasta": marco["dist"], "superficies": set(codigos),
                           "velocidad": marco["vel"]}
        elif abierto:
            tramos.append(abierto)
            abierto = None
    if abierto:
        tramos.append(abierto)
    return [t for t in tramos if t["hasta"] - t["desde"] >= MINIMO_SALIDA_M]


def criterio_propio(marcos: list[dict]) -> list[dict]:
    """El criterio anterior: tres ruedas fuera de asfalto y piano."""

    tramos, abierto = [], None
    for marco in marcos:
        cuantas = sum(1 for c in marco["sup"].values() if c not in (0, 1))
        if cuantas >= 3:
            if abierto and abierto["vuelta"] == marco["vuelta"] \
                    and marco["dist"] - abierto["hasta"] < 10:
                abierto["hasta"] = marco["dist"]
            else:
                if abierto:
                    tramos.append(abierto)
                abierto = {"vuelta": marco["vuelta"], "desde": marco["dist"],
                           "hasta": marco["dist"]}
        elif abierto:
            tramos.append(abierto)
            abierto = None
    if abierto:
        tramos.append(abierto)
    return [t for t in tramos if t["hasta"] - t["desde"] >= MINIMO_SALIDA_M]


def invalidadas(marcos: list[dict]) -> set[int]:
    return {m["vuelta"] for m in marcos if m["invalida"]}


def main() -> None:
    for etiqueta, nombre in (
            ("P2 con control de traccion", "20260831_2022_hungaroring_contrarreloj"),
            ("P3 sin control de traccion", "20260831_2041_hungaroring_contrarreloj")):
        captura = CAPTURAS / f"{nombre}.f1raw"
        if not captura.exists():
            print(f"{etiqueta}: captura ausente")
            continue

        marcos = leer(captura)
        reglamentarias = salidas_reglamentarias(marcos)
        propias = criterio_propio(marcos)
        anuladas = invalidadas(marcos)

        print(f"\n{'=' * 74}")
        print(f"{etiqueta}   ({nombre})")
        print(f"{'=' * 74}")
        print(f"vueltas que el juego invalido : {sorted(anuladas) or 'ninguna'}")
        print(f"salidas por el criterio propio: {len(propias)}")
        print(f"salidas por el articulo 33.3  : {len(reglamentarias)}\n")

        for tramo in reglamentarias:
            estado = "INVALIDADA" if tramo["vuelta"] in anuladas else "  limpia  "
            nombres = "/".join(sorted(
                f1_udp.SUPERFICIES.get(c, f"id-{c}") for c in tramo["superficies"]))
            print(f"  vuelta {tramo['vuelta']:2d} [{estado}]  "
                  f"metro {tramo['desde']:7,.0f} a {tramo['hasta']:7,.0f}  "
                  f"({tramo['hasta'] - tramo['desde']:5.1f} m)  "
                  f"a {tramo['velocidad']:3.0f} km/h  sobre {nombres}")

        # La verificacion que importa: en que vueltas cada criterio encuentra
        # algo, contra las que el juego efectivamente invalido.
        con_reglamento = {t["vuelta"] for t in reglamentarias}
        con_propio = {t["vuelta"] for t in propias}
        print(f"\n  vueltas con salida segun el reglamento: {sorted(con_reglamento)}")
        print(f"  vueltas con salida segun el criterio propio: {sorted(con_propio)}")
        print(f"  vueltas invalidadas por el juego: {sorted(anuladas)}")


if __name__ == "__main__":
    main()
