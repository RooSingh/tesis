# -*- coding: utf-8 -*-
"""Reconstruye el recorrido de un vehiculo a partir de su bus, sin GPS.

El problema
-----------
El registro no trae posicion. Se verifico sobre el crudo: los eventos presentes
son unicamente de bus, de estado del dispositivo y de parametros del vehiculo.
**No hay ninguna coordenada**, de modo que un recorrido georreferenciado no
existe y afirmarlo seria inventarlo.

Lo que si se puede
------------------
La **forma** del recorrido, integrando lo que el vehiculo mide de si mismo:

- el rumbo es la integral de la velocidad de guinada;
- la posicion es la integral de la velocidad proyectada sobre ese rumbo.

Eso da una trayectoria **relativa**: su forma es la real, su orientacion absoluta
y su ubicacion en el mundo no. Es una **derivacion declarada**, no una medicion de
posicion, y el error se acumula: un sesgo en la guinada crece lineal en el rumbo y
cuadratico en la posicion.

Por que se puede confiar en la guinada
--------------------------------------
Porque no se la toma por buena: se la contrasta contra otras dos senales que el
mismo bus entrega por caminos independientes.

**Contra las cuatro ruedas.** En una curva las ruedas de afuera recorren mas que
las de adentro, y la diferencia dividida por la velocidad de guinada da el **ancho
de via** del vehiculo. Es geometria pura, sin ningun supuesto sobre el neumatico.

**Contra la direccion.** Con la distancia entre ejes y la relacion de direccion
---que **el propio registro declara**, no se suponen--- el modelo cinematico
predice la guinada a partir del angulo del volante. Ese modelo ignora el
deslizamiento del neumatico, de modo que **debe sobreestimar**: confirma la forma
pero no la escala, y que sobreestime es lo esperable y no un defecto.

La primera valida escala y forma; la segunda, solo forma. Se informan las dos, con
lo que cada una puede y no puede sostener.
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

from adapters import can_rav4  # noqa: E402
from backend import can_capture  # noqa: E402

CAPTURAS = RAIZ / "datasets" / "can" / "capturas"
FIGURAS = RAIZ / "informe" / "tesis" / "figuras"

RUEDAS = ("wheel_speed_front_left", "wheel_speed_front_right",
          "wheel_speed_rear_left", "wheel_speed_rear_right")

# Geometria que el propio registro declara en su evento de parametros del
# vehiculo. No son supuestos: vienen con el dato.
DISTANCIA_ENTRE_EJES_M = 2.6898601055145264
RELACION_DIRECCION = 14.300000190734863

# Por debajo de esta velocidad el vehiculo esta practicamente detenido y el
# modelo de la direccion no aplica: con el auto parado se puede girar el volante
# sin que el vehiculo rote.
VELOCIDAD_MINIMA_MS = 2.0

# Giro por debajo del cual la diferencia entre ruedas es ruido de cuantizacion y
# no senal. Sin este piso, los tramos rectos ---que son la mayoria--- dominan el
# ajuste con puntos que no contienen informacion sobre el giro.
GIRO_MINIMO_DEG_S = 1.0

# Hueco a partir del cual no se integra: entre dos muestras muy separadas no se
# sabe que hizo el vehiculo, y suponer que mantuvo rumbo y velocidad inventaria
# recorrido.
HUECO_MAXIMO_S = 1.0


def _series(ruta: Path) -> dict[str, dict[float, float]]:
    """Cada senal, indexada por milisegundo, desde las tramas de bus fisico."""

    meta = json.loads((ruta.with_suffix(ruta.suffix + ".meta.json"))
                      .read_text(encoding="utf-8"))
    inicio = meta.get("inicio_utc") or "2025-01-01T00:00:00+00:00"
    seg = meta.get("segmento", "?")
    s: dict[str, dict[float, float]] = {}
    for tr in can_capture.leer_captura(ruta):
        if tr.bus >= can_rav4.BUS_TRANSMITIDO_DESDE:
            continue
        for m in can_rav4.mensajes_desde_trama(
                tr.identificador, tr.datos, tr.instante_ns, inicio, seg, tr.bus):
            s.setdefault(m["signal_name"], {})[round(tr.instante_ns / 1e6, 0)] = \
                m["value"]
    return s


def _ajuste(pares: list[tuple[float, float]]) -> tuple[float, float]:
    """Pendiente y correlacion de una nube de puntos."""

    if len(pares) < 3:
        return float("nan"), float("nan")
    mx = statistics.mean(a for a, _ in pares)
    my = statistics.mean(b for _, b in pares)
    sxy = sum((a - mx) * (b - my) for a, b in pares)
    sxx = sum((a - mx) ** 2 for a, _ in pares)
    sx = statistics.pstdev([a for a, _ in pares])
    sy = statistics.pstdev([b for _, b in pares])
    if not sxx or not sx or not sy:
        return float("nan"), float("nan")
    return sxy / sxx, (sxy / len(pares)) / (sx * sy)


def validar_contra_ruedas(s: dict) -> dict:
    """El ancho de via que se deduce de la guinada y las cuatro ruedas."""

    comunes = set(s.get("yaw_rate", {}))
    for r in RUEDAS:
        comunes &= set(s.get(r, {}))
    pares = []
    for t in sorted(comunes):
        w = math.radians(s["yaw_rate"][t])
        if abs(s["yaw_rate"][t]) < GIRO_MINIMO_DEG_S:
            continue
        derecha = (s[RUEDAS[1]][t] + s[RUEDAS[3]][t]) / 2
        izquierda = (s[RUEDAS[0]][t] + s[RUEDAS[2]][t]) / 2
        pares.append((w, (derecha - izquierda) / 3.6))
    ancho, r = _ajuste(pares)
    return {"muestras": len(pares), "ancho_de_via_m": ancho, "correlacion": r}


def validar_contra_direccion(s: dict) -> dict:
    """La guinada que el angulo del volante predice, con el modelo cinematico."""

    comunes = sorted(set(s.get("yaw_rate", {})) & set(s.get("steer_angle", {}))
                     & set(s.get("speed", {})))
    pares = []
    for t in comunes:
        v = s["speed"][t] / 3.6
        if v < VELOCIDAD_MINIMA_MS:
            continue
        delta = math.radians(s["steer_angle"][t] / RELACION_DIRECCION)
        pares.append((math.radians(s["yaw_rate"][t]),
                      v * math.tan(delta) / DISTANCIA_ENTRE_EJES_M))
    pendiente, r = _ajuste(pares)
    return {"muestras": len(pares), "pendiente": pendiente, "correlacion": r}


def _emparejar(s: dict, principal: str, *acompanantes: str) -> list[tuple]:
    """Alinea senales que **no llegan en el mismo instante**.

    Cada senal viene de su propio identificador, con su propio periodo, de modo
    que exigir que dos coincidan exactamente en el milisegundo es un error de
    metodo: en un segmento coincidieron por casualidad y en otro la interseccion
    quedo **vacia**, y la reconstruccion devolvio un recorrido de cero metros sin
    que nada fallara.

    Se alinean sosteniendo el ultimo valor conocido de cada acompanante, que es
    lo que un consumidor puede hacer con un flujo asincronico y lo unico que no
    inventa datos: mientras no llegue una lectura nueva, la anterior sigue siendo
    la mejor disponible. Se descartan los instantes previos a la primera lectura
    de cada senal, porque ahi no hay valor que sostener.
    """

    if principal not in s:
        return []
    eventos = sorted((t, principal, v) for t, v in s[principal].items())
    for nombre in acompanantes:
        eventos += [(t, nombre, v) for t, v in s.get(nombre, {}).items()]
    eventos.sort()

    ultimo: dict[str, float] = {}
    salida = []
    for t, nombre, v in eventos:
        ultimo[nombre] = v
        if nombre != principal:
            continue
        if any(a not in ultimo for a in acompanantes):
            continue
        salida.append((t, v, *(ultimo[a] for a in acompanantes)))
    return salida


def reconstruir(s: dict) -> dict:
    """Integra rumbo y posicion. Devuelve la trayectoria y su extension."""

    emparejado = _emparejar(s, "speed", "yaw_rate")
    comunes = [t for t, _, _ in emparejado]
    s = {"speed": {t: v for t, v, _ in emparejado},
         "yaw_rate": {t: y for t, _, y in emparejado}}
    xs, ys = [0.0], [0.0]
    rumbo = 0.0
    recorrido = 0.0
    saltados = 0
    for t1, t2 in zip(comunes, comunes[1:]):
        dt = (t2 - t1) / 1000.0
        if dt <= 0 or dt > HUECO_MAXIMO_S:
            saltados += 1
            continue
        rumbo += math.radians(s["yaw_rate"][t1]) * dt
        d = s["speed"][t1] / 3.6 * dt
        recorrido += d
        xs.append(xs[-1] + d * math.cos(rumbo))
        ys.append(ys[-1] + d * math.sin(rumbo))
    return {"x": xs, "y": ys, "puntos": len(xs), "recorrido_m": recorrido,
            "huecos_saltados": saltados,
            "extension_x_m": max(xs) - min(xs), "extension_y_m": max(ys) - min(ys),
            "rumbo_final_deg": math.degrees(rumbo)}


def _panel(tr: dict, titulo: str, giro: float) -> str:
    """Un recorrido, con la escala en metros y el mismo criterio de dibujo."""

    # El guion bajo de los nombres de segmento es caracter matematico en LaTeX y
    # rompe la compilacion desde el titulo, que es donde menos se lo busca.
    titulo = titulo.replace("_", r"\_")
    paso = max(1, tr["puntos"] // 700)
    pts = list(zip(tr["x"], tr["y"]))[::paso]
    coords = " ".join(f"({x:.1f},{y:.1f})" for x, y in pts)
    # `axis equal image` mantiene la misma escala en los dos ejes. Sin eso, un
    # recorrido de mil ochocientos metros de largo por ciento treinta de ancho se
    # estiraria hasta parecer sinuoso, que es exactamente lo contrario de lo que
    # el dato dice. La proporcion real es parte del resultado.
    return f"""\\begin{{tikzpicture}}
\\begin{{axis}}[
    width=0.92\\textwidth, height=5.4cm,
    axis equal image=true,
    title={{{titulo}}},
    title style={{font=\\small}},
    xlabel={{Metros}}, ylabel={{Metros}},
    tick label style={{font=\\footnotesize}}, label style={{font=\\small}},
    grid=major, grid style={{gray!20}},
]
\\addplot[thick, black, mark=none] coordinates {{{coords}}};
\\addplot[only marks, mark=*, mark size=1.8pt, black]
    coordinates {{({pts[0][0]:.1f},{pts[0][1]:.1f})}};
\\end{{axis}}
\\end{{tikzpicture}}"""


def figura(paneles: list[tuple[dict, str, float]]) -> str:
    """Los recorridos uno debajo del otro, a la misma escala de metros.

    Van juntos a proposito. Visto solo, el de autopista parece una limitacion del
    dibujo; visto contra el urbano, se entiende que **el vehiculo iba derecho**.
    La comparacion es la que convierte una recta sospechosa en un dato.
    """

    return ("% Generado por scripts/reconstruir_recorrido_can.py. "
            "No editar a mano.\n"
            + "\n\n\\vspace{4mm}\n\n".join(
                _panel(tr, titulo, giro) for tr, titulo, giro in paneles)
            + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--segmento", default="sample_09")
    ap.add_argument("--comparar-con", default="sample_01",
                    help="segundo segmento, para el panel de contraste")
    ap.add_argument("--figura", action="store_true",
                    help="escribe el archivo de figura del informe")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    ruta = CAPTURAS / f"TOYOTA_RAV4_TSS2_{args.segmento}.canraw"
    if not ruta.exists():
        print(f"no existe {ruta}")
        return 1

    s = _series(ruta)
    ruedas = validar_contra_ruedas(s)
    direccion = validar_contra_direccion(s)
    tr = reconstruir(s)

    print(f"Segmento {args.segmento}")
    print()
    print("  Validacion de la guinada, por dos caminos independientes")
    print(f"    contra las cuatro ruedas : ancho de via {ruedas['ancho_de_via_m']:.3f} m, "
          f"r = {ruedas['correlacion']:+.3f}  ({ruedas['muestras']:,} muestras)")
    print(f"    contra la direccion      : pendiente {direccion['pendiente']:.3f}, "
          f"r = {direccion['correlacion']:+.3f}  ({direccion['muestras']:,} muestras)")
    print("    la segunda sobreestima porque el modelo cinematico ignora el")
    print("    deslizamiento del neumatico: confirma la forma, no la escala.")
    print()
    print("  Recorrido reconstruido")
    print(f"    puntos     : {tr['puntos']:,}")
    print(f"    recorrido  : {tr['recorrido_m'] / 1000:.2f} km")
    print(f"    extension  : {tr['extension_x_m']:.0f} x {tr['extension_y_m']:.0f} m")
    print(f"    rumbo final: {tr['rumbo_final_deg']:+.0f} deg respecto del inicial")
    if tr["huecos_saltados"]:
        print(f"    huecos no integrados: {tr['huecos_saltados']:,}")

    if args.figura:
        # El segundo panel es el que vuelve interpretable al primero: solo, un
        # recorrido recto parece una falla del dibujo.
        otra = CAPTURAS / f"TOYOTA_RAV4_TSS2_{args.comparar_con}.canraw"
        if not otra.exists():
            print(f"  falta {otra.name}: no se genera la figura")
            return 1
        tr2 = reconstruir(_series(otra))
        print(f"\n  contraste con {args.comparar_con}: "
              f"{tr2['extension_x_m']:.0f} x {tr2['extension_y_m']:.0f} m, "
              f"{tr2['recorrido_m'] / 1000:.2f} km")
        FIGURAS.mkdir(parents=True, exist_ok=True)
        destino = FIGURAS / "recorrido_can_reconstruido.tex"
        destino.write_text(figura([
            (tr2, f"Autopista ({args.comparar_con})", 0.0),
            (tr, f"Urbano ({args.segmento})", 0.0),
        ]), encoding="utf-8")
        print(f"  figura en {destino.name}")

    if args.json:
        args.json.write_text(json.dumps(
            {"segmento": args.segmento, "ruedas": ruedas, "direccion": direccion,
             "recorrido": {k: v for k, v in tr.items() if k not in ("x", "y")}},
            indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
