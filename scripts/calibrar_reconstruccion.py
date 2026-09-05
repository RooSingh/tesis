# -*- coding: utf-8 -*-
"""Mide cuanto se equivoca la reconstruccion de recorrido, contra la verdad.

El agujero que esto cierra
--------------------------
El recorrido del vehiculo de calle se reconstruye integrando velocidad y giro,
porque su registro **no trae coordenadas**. Eso obliga a declarar que el error se
acumula, pero **no permite decir cuanto**: sin posicion verdadera no hay contra
que comparar.

La fuente de simulacion si transmite su posicion en el mundo. Aplicando **el mismo
metodo** a esa fuente, el error deja de ser una advertencia cualitativa y pasa a
tener un numero.

Lo que la calibracion puede y no puede sostener
----------------------------------------------
Puede caracterizar **el metodo**: cuanto se aparta una trayectoria integrada de la
real, y como crece ese apartamiento con la distancia.

**No puede transferir el numero de una fuente a la otra.** Los dos vehiculos, sus
sensores y sus cadencias son distintos, y un error medido sobre un auto de carrera
a doscientos por hora no es el de un vehiculo de calle en ciudad. Lo transferible
es **la forma en que el error crece**, no su magnitud.

La convencion de ejes no se supone
----------------------------------
Se deduce del propio dato: comparando el rumbo declarado contra el que se obtiene
del desplazamiento entre posiciones consecutivas, la relacion resulta
`rumbo = atan2(dx, dz)`, con una diferencia mediana de **una centesima de grado**
sobre 3.747 muestras. Suponer la convencion y errarle habria producido una
trayectoria espejada o rotada noventa grados, que es un error que se ve pero que
tambien se puede racionalizar mirando un dibujo.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

from backend import f1_capture, f1_udp  # noqa: E402

from reconstruir_recorrido_can import _emparejar  # noqa: E402

CAPTURAS = RAIZ / "datasets" / "f1_25" / "capturas"
FIGURAS = RAIZ / "informe" / "tesis" / "figuras"

# Mismo criterio que en la reconstruccion del vehiculo de calle: no se integra
# sobre huecos grandes, porque entre dos muestras separadas no se sabe que hizo.
HUECO_MAXIMO_S = 1.0

# Velocidad por encima de la cual un desplazamiento entre dos muestras es
# imposible y por lo tanto no es un desplazamiento.
#
# Existe porque la primera version de esta calibracion **integro a traves de
# cuatro intentos distintos** de una misma contrarreloj. Entre intento e intento
# el programa emisor devuelve el vehiculo a la linea de partida: cuatro saltos de
# unos novecientos metros, a mas de dieciocho mil metros por segundo. Ninguna
# integracion puede seguir un teletransporte, y el resultado fue un error de
# ochocientos metros que parecia deriva acumulada y era otra cosa.
#
# Es la misma confusion que ya habia aparecido al analizar vueltas: tomar por
# continuo lo que son intentos separados.
VELOCIDAD_IMPOSIBLE_MS = 120.0

# Un tramo mas corto que esto no da para caracterizar como crece un error.
TRAMO_MINIMO_S = 20.0


def _series(ruta: Path) -> tuple[dict, dict, dict, dict]:
    """Velocidad, giro, posicion verdadera y rumbo verdadero, por milisegundo."""

    vel: dict[float, float] = {}
    giro: dict[float, float] = {}
    pos: dict[float, tuple[float, float]] = {}
    rumbo: dict[float, float] = {}
    propio = None
    for dg in f1_capture.leer_captura(ruta):
        try:
            d = f1_udp.decodificar(dg.carga)
        except Exception:
            continue
        if not d.get("decodificado"):
            continue
        t = round(dg.desplazamiento_us / 1000.0, 0)
        if propio is None:
            propio = d["cabecera"]["player_car_index"]
        p = d["paquete"]
        if p == "car_telemetry":
            vel[t] = d["vehiculos"][propio]["speed_kmh"]
        elif p == "motion_ex":
            v = d["sesion"].get("yaw_rate_rads")
            if v is not None:
                giro[t] = v
        elif p == "motion":
            v = d["vehiculos"][propio]
            pos[t] = (v["world_position_x_m"], v["world_position_z_m"])
            rumbo[t] = v["yaw_rad"]
    return vel, giro, pos, rumbo


def tramos_continuos(pos: dict) -> list[tuple[float, float]]:
    """Parte la captura donde el vehiculo se teletransporta.

    Una contrarreloj no es una conduccion continua: entre intento e intento el
    programa emisor devuelve el vehiculo a la linea de partida. Eso aparece como
    un desplazamiento de cientos de metros entre dos muestras consecutivas, a una
    velocidad que ningun vehiculo alcanza.

    Integrar a traves de un salto asi no produce un error grande: produce un
    numero **sin significado**, porque la trayectoria reconstruida y la verdadera
    dejan de referirse al mismo recorrido.
    """

    marcas = sorted(pos)
    cortes = []
    for a, b in zip(marcas, marcas[1:]):
        dt = (b - a) / 1000.0
        if not 0 < dt < 1:
            continue
        d = math.hypot(pos[b][0] - pos[a][0], pos[b][1] - pos[a][1])
        if d / dt > VELOCIDAD_IMPOSIBLE_MS:
            cortes.append(b)

    tramos = []
    inicio = marcas[0]
    for corte in cortes:
        tramos.append((inicio, corte))
        inicio = corte
    tramos.append((inicio, marcas[-1]))
    return [(a, b) for a, b in tramos if (b - a) / 1000.0 >= TRAMO_MINIMO_S]


def calibrar(ruta: Path) -> dict:
    """Reconstruye e informa el apartamiento contra la posicion verdadera."""

    vel, giro, pos, rumbo = _series(ruta)
    if not pos:
        return {"muestras": 0}

    tramos = tramos_continuos(pos)
    if not tramos:
        return {"muestras": 0}
    # El mas largo: caracterizar como crece un error necesita recorrido, y un
    # tramo corto no distingue una deriva lineal de una constante.
    desde, hasta = max(tramos, key=lambda x: x[1] - x[0])
    pos = {t: v for t, v in pos.items() if desde <= t <= hasta}
    rumbo = {t: v for t, v in rumbo.items() if desde <= t <= hasta}
    vel = {t: v for t, v in vel.items() if desde <= t <= hasta}
    giro = {t: v for t, v in giro.items() if desde <= t <= hasta}

    emparejado = _emparejar({"speed": vel, "yaw_rate": giro}, "speed", "yaw_rate")
    if not emparejado or not pos:
        return {"muestras": 0}

    # La reconstruccion arranca en la pose verdadera. No puede deducirla ---eso es
    # justamente lo que no sabe--- de modo que se le concede, y lo que se mide es
    # cuanto se aparta **desde ahi**. Concederle la pose inicial es lo que separa
    # el error del metodo del error de no saber donde empieza.
    t0 = emparejado[0][0]
    verdaderos = sorted(pos)
    inicio = min(verdaderos, key=lambda t: abs(t - t0))
    x, z = pos[inicio]
    cabeza = rumbo[inicio]

    reconstruido: dict[float, tuple[float, float]] = {t0: (x, z)}
    recorrido = 0.0
    avance: dict[float, float] = {t0: 0.0}
    for (t1, v1, g1), (t2, _, _) in zip(emparejado, emparejado[1:]):
        dt = (t2 - t1) / 1000.0
        if dt <= 0 or dt > HUECO_MAXIMO_S:
            continue
        cabeza += g1 * dt
        d = v1 / 3.6 * dt
        recorrido += d
        # La convencion se dedujo del dato: rumbo = atan2(dx, dz).
        x += d * math.sin(cabeza)
        z += d * math.cos(cabeza)
        reconstruido[t2] = (x, z)
        avance[t2] = recorrido

    # Se compara en cada instante donde hay posicion verdadera.
    marcas = sorted(reconstruido)
    errores = []
    for t in verdaderos:
        if t < marcas[0] or t > marcas[-1]:
            continue
        cercano = min(marcas, key=lambda m: abs(m - t))
        if abs(cercano - t) > 100:      # mas de 100 ms de separacion: no compara
            continue
        rx, rz = reconstruido[cercano]
        vx, vz = pos[t]
        errores.append((avance[cercano], math.hypot(rx - vx, rz - vz)))

    if not errores:
        return {"muestras": 0}

    errores.sort()
    total = errores[-1][0]
    # El error a distintas fracciones del recorrido, que es lo que muestra como
    # crece. Informar solo el final escondería si crece lineal o de golpe.
    hitos = {}
    for frac in (0.1, 0.25, 0.5, 0.75, 1.0):
        objetivo = total * frac
        cerca = min(errores, key=lambda e: abs(e[0] - objetivo))
        hitos[f"{int(frac * 100)}%"] = {"metros_recorridos": cerca[0],
                                        "error_m": cerca[1]}
    return {
        "archivo": ruta.name,
        "tramos_continuos": len(tramos),
        "tramo_usado_s": (hasta - desde) / 1000.0,
        "muestras": len(errores),
        "recorrido_total_m": total,
        "error_final_m": errores[-1][1],
        "error_relativo_final": errores[-1][1] / total if total else float("nan"),
        "error_mediano_m": statistics.median(e for _, e in errores),
        "hitos": hitos,
        "reconstruido": reconstruido,
        "verdadero": pos,
    }


def figura(r: dict) -> str:
    """Las dos trayectorias superpuestas: la verdadera y la reconstruida."""

    v = sorted(r["verdadero"].items())
    rec = sorted(r["reconstruido"].items())
    pv = max(1, len(v) // 700)
    pr = max(1, len(rec) // 700)
    cv = " ".join(f"({p[0]:.1f},{p[1]:.1f})" for _, p in v[::pv])
    cr = " ".join(f"({p[0]:.1f},{p[1]:.1f})" for _, p in rec[::pr])
    return f"""% Generado por scripts/calibrar_reconstruccion.py. No editar a mano.
\\begin{{tikzpicture}}
\\begin{{axis}}[
    width=0.78\\textwidth, height=7.4cm,
    axis equal image=true,
    xlabel={{Metros}}, ylabel={{Metros}},
    tick label style={{font=\\footnotesize}}, label style={{font=\\small}},
    legend style={{at={{(0.5,-0.22)}}, anchor=north, legend columns=2, draw=none,
        /tikz/every even column/.append style={{column sep=0.7cm}}}},
    legend cell align=left,
    grid=major, grid style={{gray!20}},
]
\\addplot[thick, black] coordinates {{{cv}}};
\\addlegendentry{{Posición transmitida por la fuente}}
\\addplot[thick, dashed, black!55] coordinates {{{cr}}};
\\addlegendentry{{Reconstruida por integración}}
\\end{{axis}}
\\end{{tikzpicture}}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("captura", nargs="?", type=Path,
                    default=CAPTURAS / "20260831_2145_catalunya_contrarreloj.f1raw")
    ap.add_argument("--figura", action="store_true")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    if not args.captura.exists():
        print(f"no existe {args.captura}")
        return 1

    r = calibrar(args.captura)
    if not r.get("muestras"):
        print("no hay muestras comparables")
        return 1

    print(f"Calibracion sobre {r['archivo']}")
    print(f"  comparaciones: {r['muestras']:,}")
    print(f"  recorrido    : {r['recorrido_total_m'] / 1000:.2f} km")
    print()
    print(f"  {'recorrido':>12}{'error':>11}{'relativo':>11}")
    print("  " + "-" * 34)
    for etq, h in r["hitos"].items():
        rel = h["error_m"] / h["metros_recorridos"] if h["metros_recorridos"] else 0
        print(f"  {h['metros_recorridos']:>10,.0f} m{h['error_m']:>9,.1f} m"
              f"{rel * 100:>10.1f}%")
    print()
    print(f"  error mediano sobre todo el recorrido: {r['error_mediano_m']:,.1f} m")

    if args.figura:
        FIGURAS.mkdir(parents=True, exist_ok=True)
        destino = FIGURAS / "calibracion_reconstruccion.tex"
        destino.write_text(figura(r), encoding="utf-8")
        print(f"  figura en {destino.name}")

    if args.json:
        args.json.write_text(json.dumps(
            {k: v for k, v in r.items()
             if k not in ("reconstruido", "verdadero")}, indent=1),
            encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
