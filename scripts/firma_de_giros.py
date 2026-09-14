#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""La firma de giros de un circuito: cuantas veces gira y cuanto, no cuanto gira.

POR QUE HACIA FALTA UN SEGUNDO INSTRUMENTO
------------------------------------------
`scripts/medir_curvas_de_un_circuito.py` encuentra las zonas de giro sostenido
mirando la aceleracion lateral. Esas zonas **funden las curvas vecinas del mismo
sentido**: en Silverstone dan una sola donde el mapa numera tres, y en Monaco una
sola de 178 m donde el mapa numera dos.

Fundidas, no se puede decir cual numero de la FIA va en cual zona, y ese es el
obstaculo que dejo trece de los diecisiete circuitos sin nombrar. Mirando la
aceleracion lateral no se sale: el canal declara **cuanto** gira el auto, no
**cuantas veces**.

La forma del recorrido si lo dice. Dos curvas del mismo sentido separadas por una
recta son dos acumulaciones de rumbo distintas, aunque el auto no suelte la
aceleracion lateral entre las dos.

QUE HACE ESTE GUION CON ESO
---------------------------
Pide el trazado de una vuelta, mide sus giros, y ---si se le pasan las zonas que
detecto el otro guion--- dice **cuantos giros cae dentro de cada zona**. Una zona
con dos giros es una fusion, y ahi hay dos numeros de la FIA para repartir.

SOBRE EL SENTIDO
----------------
El plano en que el simulador publica las coordenadas **esta espejado**: Spa, que
se corre horario, da antihorario ahi. Este guion lo invierte para informar el
sentido del mundo, y lo dice en la salida. Calibrado el 2026-09-14 contra dos
horquillas de sentido publicado: La Source, a derecha, y The Loop, a izquierda.

LOS METROS QUEDAN CORTOS, Y SE CORRIGEN
---------------------------------------
La distancia se acumula sumando cuerdas entre puntos, y una cuerda corta la
curva: el poligono de Monaco da 3.258 m contra los 3.320 que declara la ruta. Se
escala por esa razon para poder comparar contra los metros de la telemetria.

COMO SE LO CORRE
----------------
    python3 scripts/firma_de_giros.py \\
        --sesion f1_25:session:8341663191437069143 --vuelta 2 \\
        --api http://127.0.0.1:8080 \\
        --zona 1184:1286 --zona 1315:1484
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analisis.curvas import (  # noqa: E402
    UMBRAL_DE_GIRO_GRADOS, UNION_DE_GIRO_M, giros_de_la_vuelta,
)

#: Cuanto puede girar una curva antes de que convenga llamarla horquilla. No
#: decide nada: es un rotulo para leer la salida de un vistazo.
HORQUILLA_GRADOS = 140.0

#: Idem para distinguir una curva cerrada de una abierta.
CERRADA_GRADOS = 75.0


def _pedir(api: str, ruta: str) -> dict:
    with urllib.request.urlopen(api.rstrip("/") + ruta, timeout=300) as r:
        return json.loads(r.read().decode("utf-8"))


def sentido_del_mundo(grados: float, plano_crudo: str) -> str:
    """Traduce el signo del plano al sentido en que se corre.

    NO SE ADIVINA EL ESPEJO: se lo lee. La ruta del trazado publica
    `sentido_en_el_plano_crudo`, calculado con el area con signo del poligono, y
    advierte que no es el sentido en que se corre. Justamente por eso sirve: si
    la vuelta entera da antihorario en el plano y sabemos que se corre horario,
    entonces en ese plano lo antihorario es lo horario del mundo.
    """

    if plano_crudo not in ("horario", "antihorario"):
        raise ValueError(
            f"sentido_en_el_plano_crudo={plano_crudo!r}: sin saber como esta "
            f"orientado el plano, el signo de un giro no se puede traducir.")
    # En el plano crudo, positivo es antihorario. Si la vuelta entera da
    # antihorario ahi, el plano esta espejado respecto del mundo.
    espejado = plano_crudo == "antihorario"
    a_derecha = (grados > 0) if espejado else (grados < 0)
    return "derecha" if a_derecha else "izquierda"


def forma(grados: float) -> str:
    if abs(grados) >= HORQUILLA_GRADOS:
        return "horquilla"
    return "cerrada" if abs(grados) >= CERRADA_GRADOS else "abierta"


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sesion", required=True)
    p.add_argument("--vuelta", type=int, required=True)
    p.add_argument("--api", default="http://127.0.0.1:8000")
    p.add_argument("--umbral", type=float, default=UMBRAL_DE_GIRO_GRADOS,
                   help="grados minimos para informar un giro")
    # SE EXPONE PORQUE CAMBIA LA RESPUESTA, y quien la lea tiene que saberlo.
    # Mirabeau Inferior y Portier son dos giros de +119 grados separados por
    # diez metros de recta: con la union por omision salen como uno solo de
    # +236, y con una union mas corta salen como dos. Las dos lecturas son
    # ciertas y describen cosas distintas.
    p.add_argument("--union", type=float, default=UNION_DE_GIRO_M,
                   help="metros de recta que caben dentro de un mismo giro")
    # SE PIDEN LOS EXTREMOS Y NO EL APICE. La primera version tomaba el apice y
    # preguntaba que giros caian cerca; con dos curvas a cien metros, el apice de
    # una cae cerca de las dos y todo salia «fundido». Una zona es un intervalo y
    # la pregunta es que giros caen ADENTRO.
    p.add_argument("--zona", action="append", default=[], metavar="DESDE:HASTA",
                   help="extremos de una zona detectada, para ver si esta fundida")
    args = p.parse_args()

    t = _pedir(args.api, f"/sesiones/{args.sesion}/trazado"
                         f"?puntos=2000&vuelta={args.vuelta}")
    pts = t.get("puntos") or []
    if len(pts) < 3:
        print("esa vuelta no tiene posicion persistida.")
        return 1

    plano = t.get("sentido_en_el_plano_crudo")
    largo = t.get("largo_m")
    giros = giros_de_la_vuelta(pts, umbral_grados=args.umbral,
                               union_m=args.union)
    if not giros:
        print("ningun giro supera el umbral.")
        return 1

    # EL POLIGONO QUEDA CORTO Y HAY QUE ESCALARLO. Sin esto, los metros de este
    # guion y los del otro no son comparables, que es justo lo que se necesita.
    #
    # SE ESCALA CONTRA EL LARGO DEL POLIGONO ENTERO, no contra donde termina el
    # ultimo giro. La primera version hacia lo segundo y la escala salia 1,11 en
    # vez de 1,02: el ultimo giro de Monaco termina 200 m antes de la meta, y
    # esos 200 m se repartian como error sobre cada metro de la vuelta. Ninguna
    # zona coincidia y el guion no se quejaba.
    del_poligono = sum(
        math.dist(pts[i - 1], pts[i]) for i in range(1, len(pts)))
    escala = (largo / del_poligono) if (largo and del_poligono) else 1.0

    print(f"== {args.sesion}  vuelta {args.vuelta}")
    print(f"   largo declarado por la ruta   {largo} m")
    print(f"   plano crudo                   {plano}"
          f"   (se corre {'horario' if plano == 'antihorario' else 'antihorario'})")
    print(f"   umbral                        {args.umbral} grados")
    print(f"   union                         {args.union} m")
    print(f"   escala de cuerdas             {escala:.4f}\n")

    print(f"   {'#':>3} {'desde':>8} {'hasta':>8} {'grados':>8}  {'sentido':>9}  forma")
    enriquecidos = []
    for i, g in enumerate(giros, 1):
        d0, d1 = g["desde_m"] * escala, g["hasta_m"] * escala
        s = sentido_del_mundo(g["grados"], plano)
        enriquecidos.append((d0, d1, g["grados"], s))
        print(f"   {i:>3} {d0:8.1f} {d1:8.1f} {g['grados']:+8.1f}  {s:>9}  "
              f"{forma(g['grados'])}")

    if not args.zona:
        return 0

    print("\n   zonas detectadas y cuantos giros cae en cada una:")
    print("   (dos o mas giros en una zona = la deteccion fundio curvas)")
    zonas = []
    for texto in args.zona:
        if ":" not in texto:
            raise SystemExit(f"--zona {texto}: se escribe DESDE:HASTA, en metros.")
        a, b = texto.split(":", 1)
        zonas.append((float(a), float(b)))

    for z0, z1 in sorted(zonas):
        # El centro del giro es lo que decide a que zona pertenece: un giro
        # largo puede asomar por los dos extremos de una zona corta.
        dentro = [e for e in enriquecidos if z0 <= (e[0] + e[1]) / 2 <= z1]
        detalle = ", ".join(f"{g:+.0f} {s}" for _, _, g, s in dentro) or "ninguno"
        aviso = ("   <-- FUNDIDA" if len(dentro) > 1 else
                 "   <-- SIN GIRO PROPIO" if not dentro else "")
        print(f"       zona {z0:7.1f}-{z1:<7.1f}: {len(dentro)} giro(s)  "
              f"[{detalle}]{aviso}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
