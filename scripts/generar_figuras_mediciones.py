# -*- coding: utf-8 -*-
"""Genera los datos de las figuras de las mediciones, en formato pgfplots.

Por que en pgfplots y no como imagen
------------------------------------
Una figura de resultados no es una ilustracion: es evidencia. Escrita como
coordenadas dentro del propio documento queda **auditable** ---cualquiera puede
leer los numeros que la sostienen sin volver a correr nada---, sale vectorial, y
usa la misma tipografia que el texto en lugar de una pegada encima.

Cada figura es un archivo `.tex` que el informe incluye. Regenerarlas es correr
este script; el informe no cambia.
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from backend import f1_capture  # noqa: E402

CAPTURAS = RAIZ / "datasets" / "f1_25" / "capturas"
FIGURAS = RAIZ / "informe" / "tesis" / "figuras"

ID_CAR_TELEMETRY = 6

# Las dos capturas que contrastan, elegidas por su modo de juego y no por su
# resultado: una de pantalla dividida y una de un solo vehiculo.
PARTIDA = "20260902_1848_spielberg_carrera_dos-conductores.f1raw"
SOLA = "20260831_2145_catalunya_contrarreloj.f1raw"

# El histograma se corta donde deja de haber intervalos normales. Por encima ya
# no son irregularidad sino ranuras perdidas o el emisor detenido, y mezclarlos
# aplastaria la escala.
TOPE_MS = 90.0
ANCHO_BIN_MS = 2.0


def _intervalos_ms(ruta: Path) -> list[float]:
    marcas = []
    for dg in f1_capture.leer_captura(ruta):
        if len(dg.carga) > ID_CAR_TELEMETRY and dg.carga[ID_CAR_TELEMETRY] == ID_CAR_TELEMETRY:
            marcas.append(dg.desplazamiento_us)
    return [(b - a) / 1000.0 for a, b in zip(marcas, marcas[1:])]


def _histograma(valores: list[float]) -> list[tuple[float, float]]:
    """Devuelve (centro del bin, porcentaje).

    En porcentaje y no en cuenta: las dos capturas tienen distinta cantidad de
    datagramas, y comparar cuentas absolutas mostraria esa diferencia en lugar
    de la forma, que es lo que se quiere comparar.
    """

    dentro = [v for v in valores if v <= TOPE_MS]
    if not dentro:
        return []
    cuenta = Counter(int(v / ANCHO_BIN_MS) for v in dentro)
    total = len(dentro)
    return [((b + 0.5) * ANCHO_BIN_MS, 100.0 * n / total)
            for b, n in sorted(cuenta.items())]


def _coordenadas(puntos, formato: str = "({:.2f},{:.4f})") -> str:
    return " ".join(formato.format(x, y) for x, y in puntos)


def _tope(*series) -> float:
    """El alto de la serie mas alta, para colocar rotulos sin encimarlos."""

    return max(max(y for _, y in s) for s in series if s)


def figura_histograma() -> str:
    """El histograma que mostro que no era dispersion sino dos modas."""

    partida = _intervalos_ms(CAPTURAS / PARTIDA)
    sola = _intervalos_ms(CAPTURAS / SOLA)
    hp = _histograma(partida)
    hs = _histograma(sola)

    dentro_p = [v for v in partida if v <= TOPE_MS]
    dentro_s = [v for v in sola if v <= TOPE_MS]
    return f"""% Generado por scripts/generar_figuras_mediciones.py. No editar a mano.
% Pantalla dividida: {len(dentro_p):,} intervalos. Un vehiculo: {len(dentro_s):,}.
\\begin{{tikzpicture}}
\\begin{{axis}}[
    width=0.95\\textwidth, height=6.2cm,
    xlabel={{Intervalo entre entregas consecutivas (ms)}},
    ylabel={{Proporción (\\%)}},
    xmin=18, xmax=82,
    ymin=0,
    xtick={{20,30,40,50,60,70,80}},
    legend style={{at={{(0.5,-0.30)}}, anchor=north, legend columns=2, draw=none,
        /tikz/every even column/.append style={{column sep=0.7cm}}}},
    legend cell align=left,
    tick label style={{font=\\small}},
    label style={{font=\\small}},
    grid=major, grid style={{gray!20}},
    area legend,
    clip=false,
]
% El de pantalla dividida va relleno; el de un solo vehiculo, como contorno.
% Superpuestos y los dos rellenos, el de adelante tapa al de atras justo donde
% se cruzan, que es el unico lugar donde importa mirarlos juntos.
\\addplot[ybar interval, fill=gray!55, draw=gray!75!black]
    coordinates {{{_coordenadas(hp)}}};
\\addlegendentry{{Pantalla dividida}}
\\addplot[const plot, very thick, black]
    coordinates {{{_coordenadas(hs)}}};
\\addlegendentry{{Un solo vehículo}}
\\draw[dashed, thick, black!70] (axis cs:50,0) -- (axis cs:50,{_tope(hp, hs) * 1.05:.2f});
\\node[anchor=south, font=\\small, fill=white, inner sep=1pt]
    at (axis cs:50,{_tope(hp, hs) * 1.06:.2f}) {{50 ms prometidos}};
\\end{{axis}}
\\end{{tikzpicture}}
"""


def figura_dispersion() -> str:
    """Cada intervalo contra el siguiente: la alternancia se ve de una."""

    v = [x for x in _intervalos_ms(CAPTURAS / PARTIDA) if x <= TOPE_MS]
    pares = list(zip(v, v[1:]))
    # Se dibuja una submuestra regular: con catorce mil puntos la nube se
    # vuelve una mancha y deja de mostrar la estructura.
    paso = max(1, len(pares) // 600)
    muestra = pares[::paso]

    mx = statistics.mean(x for x, _ in pares)
    my = statistics.mean(y for _, y in pares)
    sx = statistics.pstdev([x for x, _ in pares])
    sy = statistics.pstdev([y for _, y in pares])
    cov = sum((x - mx) * (y - my) for x, y in pares) / len(pares)
    r = cov / (sx * sy)

    return f"""% Generado por scripts/generar_figuras_mediciones.py. No editar a mano.
% Correlacion sobre los {len(pares):,} pares: r = {r:+.3f}. Se dibujan {len(muestra):,}.
\\begin{{tikzpicture}}
\\begin{{axis}}[
    width=0.62\\textwidth, height=6.2cm,
    xlabel={{Intervalo $n$ (ms)}},
    ylabel={{Intervalo $n+1$ (ms)}},
    xmin=20, xmax=82, ymin=20, ymax=82,
    xtick={{20,40,60,80}}, ytick={{20,40,60,80}},
    tick label style={{font=\\small}},
    label style={{font=\\small}},
    grid=major, grid style={{gray!20}},
    axis equal image=false,
]
\\addplot[only marks, mark=*, mark size=0.5pt, black!55]
    coordinates {{{_coordenadas(muestra, "({:.1f},{:.1f})")}}};
\\draw[dashed, gray] (axis cs:50,20) -- (axis cs:50,82);
\\draw[dashed, gray] (axis cs:20,50) -- (axis cs:82,50);
\\node[anchor=north east, font=\\small] at (axis cs:80,80) {{$r = {r:+.3f}$}};
\\end{{axis}}
\\end{{tikzpicture}}
"""


def figura_latencia(crudo: Path) -> str:
    """Latencia contra tasa, por percentiles."""

    d = json.loads(crudo.read_text(encoding="utf-8"))
    d.sort(key=lambda r: r["tasa_pedida"])
    p50 = [(r["tasa_pedida"], r["p50_ms"]) for r in d]
    p95 = [(r["tasa_pedida"], r["p95_ms"]) for r in d]
    mini = [(r["tasa_pedida"], r["minimo_ms"]) for r in d]

    return f"""% Generado por scripts/generar_figuras_mediciones.py. No editar a mano.
\\begin{{tikzpicture}}
\\begin{{axis}}[
    width=0.95\\textwidth, height=6.2cm,
    xmode=log, log basis x=10,
    xlabel={{Tasa de publicación (mensajes por segundo)}},
    ylabel={{Latencia (ms)}},
    ymin=0, ymax=1900,
    legend style={{at={{(0.5,-0.30)}}, anchor=north, legend columns=3, draw=none}},
    legend cell align=left,
    tick label style={{font=\\small}},
    label style={{font=\\small}},
    grid=major, grid style={{gray!20}},
]
\\addplot[mark=triangle*, thick, black] coordinates {{{_coordenadas(p95, "({:.0f},{:.0f})")}}};
\\addlegendentry{{p95}}
\\addplot[mark=*, thick, black!60] coordinates {{{_coordenadas(p50, "({:.0f},{:.0f})")}}};
\\addlegendentry{{mediana}}
\\addplot[mark=square*, thick, dashed, black!45] coordinates {{{_coordenadas(mini, "({:.0f},{:.0f})")}}};
\\addlegendentry{{mínimo}}
\\draw[dotted, thick, black!60] (axis cs:700,0) -- (axis cs:700,1800);
\\node[anchor=east, font=\\small, align=right, fill=white, inner sep=2pt]
    at (axis cs:640,1450) {{el intervalo de vaciado\\\\domina a la izquierda}};
\\end{{axis}}
\\end{{tikzpicture}}
"""


def main() -> int:
    FIGURAS.mkdir(parents=True, exist_ok=True)
    crudo_latencia = RAIZ / "docs" / "mediciones" / "latencia.json"

    salidas = {
        "medicion_histograma_intervalos.tex": figura_histograma,
        "medicion_dispersion_consecutivos.tex": figura_dispersion,
    }
    for nombre, hacer in salidas.items():
        (FIGURAS / nombre).write_text(hacer(), encoding="utf-8")
        print(f"  {nombre}")

    if crudo_latencia.exists():
        (FIGURAS / "medicion_latencia_tasa.tex").write_text(
            figura_latencia(crudo_latencia), encoding="utf-8")
        print("  medicion_latencia_tasa.tex")
    else:
        print(f"  falta {crudo_latencia}: no se genero la figura de latencia")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
