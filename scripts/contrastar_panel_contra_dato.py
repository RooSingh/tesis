"""Contrasta lo que muestra el panel del juego contra lo que declara la captura.

Para que sirve
--------------
El decodificador de F1 25 esta verificado contra la especificacion, pero que un
campo **signifique** lo que su nombre dice solo lo prueba una evidencia
independiente: la pantalla del juego grabada en video. Este guion cierra ese
contraste para dos paneles de la carrera de Silverstone del 2026-08-30:

- **temperaturas** (indice 3 de `mfd_panel`): interior, superficie y frenos de
  cada rueda, y motor, del paquete 6;
- **desgaste por componente** (indice 4): MGU-H, SAE, EC, MCI, MGU-K, TC y caja
  de cambios, del paquete 10 (Car Damage).

Todo se hace sobre la captura cruda, **sin la base**.

Lectura sin sesgo, en dos pasos
-------------------------------
1. `cuadros` extrae los cuadros, sus recortes y una plantilla de lecturas. No
   decodifica ningun valor de temperatura ni de desgaste: solo el indice de
   panel, para saber cuando esta abierto el 4.
2. Una persona lee la pantalla y completa la plantilla. **Ese archivo se versiona
   antes de correr el paso siguiente**, de modo que el historial prueba que la
   lectura no se hizo mirando el dato. Un digito ambiguo (0 u 8) se anota con
   las dos lecturas: `pantalla` y `pantalla_alternativa`.
3. `contrastar` decodifica, alinea cada cuadro y escribe los pares.

Alineacion de cada cuadro
-------------------------
1. **Desfase global**: instante de captura = segundo de video + 26,853 s
   (`informe/tesis/figuras/carrera_silverstone_validacion.json:4`, con el signo
   del extractor: video = captura - 26,853).
2. **Instante real del cuadro**: el que informa `ffmpeg` con `showinfo`, no el
   pedido; el cuadro sale en la grilla de 59,94 cuadros por segundo.
3. **Ancla en el propio cuadro**: el tiempo de vuelta en curso que muestra la
   pantalla se busca en el paquete de vuelta (2). El residuo es el instante
   global menos el del ancla. Si el tiempo no se reproduce a menos de
   `TOLERANCIA_ANCLA_S` del instante global ---la pantalla congela el parcial al
   cruzar un sector---, el cuadro usa **el residuo medio** de los anclados, y la
   fila lo declara.

Comprobacion independiente: las revoluciones que muestra la pantalla contra
`engine_rpm` en el instante anclado.

Uso
---
    python -B scripts/contrastar_panel_contra_dato.py cuadros
    (leer la pantalla y completar docs/mediciones/contraste_panel_lecturas_de_pantalla.csv)
    python -B scripts/contrastar_panel_contra_dato.py contrastar
"""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import f1_capture, f1_udp  # noqa: E402
from scripts.extraer_cuadros_validacion import (  # noqa: E402
    buscar_ffmpeg,
    puntos_de_muestreo,
    tramos_de_panel,
)

CAPTURA = ROOT / "datasets" / "f1_25" / "capturas" / "20260830_2121_silverstone_carrera.f1raw"
VIDEO = ROOT / "datasets" / "f1_25" / "validacion" / "20260830_2121_silverstone_carrera_pantalla.mp4"
CUADROS = ROOT / "datasets" / "f1_25" / "validacion" / "cuadros_2026-09-14" / "contraste"
LECTURAS = ROOT / "docs" / "mediciones" / "contraste_panel_lecturas_de_pantalla.csv"
SALIDA = ROOT / "docs" / "mediciones" / "contraste_panel_temperaturas_y_componentes.csv"

#: Instante de captura menos segundo de video.
CAPTURA_MENOS_VIDEO_S = 26.853

#: Segundos de video de los cinco pasos por el panel de temperaturas de la
#: primera pasada; se conservan para que las dos pasadas miren los mismos pasos.
TIEMPOS_TEMPERATURAS_S = (325.025, 645.612, 900.800, 1310.309, 1414.113)

PANEL_TEMPERATURAS = 3
PANEL_COMPONENTES = 4

#: Mas lejos que esto del instante global, un tiempo de vuelta no ancla el
#: cuadro: es un parcial congelado que la vuelta alcanzo antes.
TOLERANCIA_ANCLA_S = 0.25

#: Ventana alrededor del instante usado para declarar si el dato cambiaba.
VENTANA_S = 0.5

RUEDAS = ("delantera_izquierda", "delantera_derecha", "trasera_izquierda", "trasera_derecha")
assert set(RUEDAS) == set(f1_udp.ORDEN_RUEDAS)

#: Canales de temperatura del panel. En pantalla, la fila del punto lleno es el
#: interior y la del anillo, la superficie.
CANALES_TEMPERATURA = {
    "interior": "tyres_inner_temperature_c",
    "superficie": "tyres_surface_temperature_c",
    "freno": "brakes_temperature_c",
}

#: Etiqueta de pantalla -> campo del paquete 10.
COMPONENTES = {
    "MGU-H": "engine_mguh_wear_pct",
    "SAE": "engine_es_wear_pct",
    "EC": "engine_ce_wear_pct",
    "MCI": "engine_ice_wear_pct",
    "MGU-K": "engine_mguk_wear_pct",
    "TC": "engine_tc_wear_pct",
    "CAJA": "gearbox_damage_pct",
}

# Recortes sobre el cuadro de 1920x1080: ancho, alto, x, y.
RECORTES = {
    "panel": (520, 300, 1370, 750),
    "tiempo": (400, 130, 1480, 30),
    "tablero": (440, 170, 740, 860),
}

CAMPOS_LECTURA = ("paso", "magnitud", "canal", "rueda", "pantalla",
                  "pantalla_alternativa", "nota")


# --------------------------------------------------------------------------- #
# Funciones puras
# --------------------------------------------------------------------------- #

def tiempo_de_vuelta_a_segundos(texto: str) -> float:
    """`1:12.845` o `50.268` a segundos."""
    texto = texto.strip().replace(",", ".")
    if ":" in texto:
        minutos, segundos = texto.split(":")
        return 60 * int(minutos) + float(segundos)
    return float(texto)


def pts_de_showinfo(salida_error: str) -> float:
    """El `pts_time` del primer cuadro que informa el filtro `showinfo`."""
    hallado = re.search(r"pts_time:\s*([0-9.]+)", salida_error)
    if not hallado:
        raise ValueError("ffmpeg no informo pts_time")
    return float(hallado.group(1))


@dataclass
class Vuelta:
    """Una muestra del paquete de vuelta del vehiculo propio."""

    segundo: float
    numero: int
    tiempo_ms: int


def anclar(vueltas: Sequence[Vuelta], objetivo_s: float, instante_global: float,
           tolerancia_s: float = TOLERANCIA_ANCLA_S) -> float | None:
    """Instante de captura en que el tiempo de vuelta vale `objetivo_s`.

    Entre dos muestras del paquete de vuelta el tiempo avanza con el reloj de la
    captura, de modo que el instante que lo reproduce se despeja de la muestra
    anterior. Se acepta solo si cae dentro del tramo hasta la muestra siguiente
    (mas un cuadro de margen) y a menos de `tolerancia_s` del instante global.
    Devuelve el mas cercano al global, o None.
    """
    segundos = [v.segundo for v in vueltas]
    desde = bisect.bisect_left(segundos, instante_global - tolerancia_s - 1.0)
    hasta = bisect.bisect_right(segundos, instante_global + tolerancia_s + 1.0)
    mejor = None
    for j in range(max(desde - 1, 0), min(hasta, len(vueltas))):
        v = vueltas[j]
        candidato = v.segundo + (objetivo_s - v.tiempo_ms / 1000.0)
        siguiente = vueltas[j + 1].segundo if j + 1 < len(vueltas) else float("inf")
        if not (v.segundo <= candidato <= siguiente + 1 / 60):
            continue
        if abs(candidato - instante_global) > tolerancia_s:
            continue
        if mejor is None or abs(candidato - instante_global) < abs(mejor - instante_global):
            mejor = candidato
    return mejor


def muestra_cercana(segundos: Sequence[float], instante: float) -> int:
    """Indice de la muestra mas cercana a `instante`."""
    i = bisect.bisect_left(segundos, instante)
    if i == 0:
        return 0
    if i == len(segundos):
        return len(segundos) - 1
    return i if segundos[i] - instante < instante - segundos[i - 1] else i - 1


def resumir(diferencias: Iterable[int]) -> dict:
    """Pares, exactos, distribucion y maximo absoluto de pantalla menos dato."""
    lista = list(diferencias)
    return {
        "pares": len(lista),
        "exactos": sum(1 for d in lista if d == 0),
        "distribucion": dict(sorted(Counter(lista).items())),
        "maximo_absoluto": max((abs(d) for d in lista), default=None),
    }


# --------------------------------------------------------------------------- #
# Paso 1: cuadros y plantilla
# --------------------------------------------------------------------------- #

def plan_de_cuadros(ruta_captura: Path) -> list[dict]:
    """Los cuadros a leer: cinco pasos de temperaturas y el muestreo del panel 4."""
    plan = [{"paso": f"t{n}", "magnitud": "temperatura", "segundo_video_pedido": t}
            for n, t in enumerate(TIEMPOS_TEMPERATURAS_S, 1)]
    n = 0
    for tramo in tramos_de_panel(ruta_captura):
        if tramo["panel"] != PANEL_COMPONENTES:
            continue
        for punto, segundo in puntos_de_muestreo(tramo["inicio"], tramo["fin"]):
            n += 1
            plan.append({"paso": f"c{n}", "magnitud": "componente", "punto": punto,
                         "segundo_video_pedido": round(segundo - CAPTURA_MENOS_VIDEO_S, 3)})
    return plan


def extraer_cuadro(ffmpeg: str, video: Path, segundo: float, carpeta: Path, nombre: str) -> float:
    """Extrae el cuadro completo y sus recortes; devuelve su instante real."""
    divisiones = len(RECORTES) + 1
    grafo = f"[0:v]showinfo,split={divisiones}[completo]" + "".join(
        f"[r{i}]" for i in range(len(RECORTES)))
    for i, (w, h, x, y) in enumerate(RECORTES.values()):
        grafo += f";[r{i}]crop={w}:{h}:{x}:{y},scale=iw*2:ih*2[s{i}]"
    orden = [ffmpeg, "-hide_banner", "-y", "-ss", f"{segundo:.3f}", "-copyts",
             "-i", str(video), "-filter_complex", grafo,
             "-map", "[completo]", "-frames:v", "1", str(carpeta / f"{nombre}_completo.png")]
    for i, recorte in enumerate(RECORTES):
        orden += ["-map", f"[s{i}]", "-frames:v", "1", str(carpeta / f"{nombre}_{recorte}.png")]
    proceso = subprocess.run(orden, capture_output=True, text=True)
    if proceso.returncode != 0:
        raise RuntimeError(proceso.stderr.strip()[-400:])
    return pts_de_showinfo(proceso.stderr)


def filas_de_plantilla(plan: list[dict]) -> list[dict]:
    filas = []
    for p in plan:
        base = {"paso": p["paso"], "pantalla": "", "pantalla_alternativa": "", "nota": ""}
        filas.append({**base, "magnitud": "ancla", "canal": "tiempo_de_vuelta", "rueda": ""})
        filas.append({**base, "magnitud": "ancla", "canal": "rpm", "rueda": ""})
        if p["magnitud"] == "temperatura":
            for canal in CANALES_TEMPERATURA:
                for rueda in RUEDAS:
                    filas.append({**base, "magnitud": "temperatura", "canal": canal, "rueda": rueda})
            filas.append({**base, "magnitud": "temperatura", "canal": "motor", "rueda": ""})
        else:
            for etiqueta in COMPONENTES:
                filas.append({**base, "magnitud": "componente", "canal": etiqueta, "rueda": ""})
    return filas


def paso_cuadros(argumentos) -> int:
    ffmpeg = buscar_ffmpeg()
    if ffmpeg is None:
        print("No se encontro ffmpeg.", file=sys.stderr)
        return 2
    argumentos.cuadros.mkdir(parents=True, exist_ok=True)
    plan = plan_de_cuadros(argumentos.captura)
    for p in plan:
        nombre = f"{p['paso']}_{p['magnitud']}"
        p["cuadro"] = nombre
        p["segundo_video_cuadro"] = extraer_cuadro(
            ffmpeg, argumentos.video, p["segundo_video_pedido"], argumentos.cuadros, nombre)
        print(f"  {p['paso']:>4} pedido {p['segundo_video_pedido']:9.3f} s  "
              f"cuadro {p['segundo_video_cuadro']:9.4f} s  {nombre}")
    ruta_plan = argumentos.cuadros / "plan.json"
    ruta_plan.write_text(json.dumps(plan, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"plan: {ruta_plan} ({len(plan)} cuadros)")

    if argumentos.lecturas.exists():
        print(f"La plantilla ya existe y no se pisa: {argumentos.lecturas}")
    else:
        argumentos.lecturas.parent.mkdir(parents=True, exist_ok=True)
        with argumentos.lecturas.open("w", newline="", encoding="utf-8") as archivo:
            escritor = csv.DictWriter(archivo, fieldnames=CAMPOS_LECTURA)
            escritor.writeheader()
            escritor.writerows(filas_de_plantilla(plan))
        print(f"plantilla de lecturas: {argumentos.lecturas}")
    return 0


# --------------------------------------------------------------------------- #
# Paso 2: contraste
# --------------------------------------------------------------------------- #

def indexar(ruta_captura: Path) -> dict:
    """Series del vehiculo propio: vuelta (2), telemetria (6) y dano (10)."""
    cabeceras: Counter = Counter()
    crudos: list[tuple[float, bytes]] = []
    tamanos = {f1_udp.PAQUETES[i]["tamano"] for i in (2, 6, 10)}
    for d in f1_capture.leer_captura(ruta_captura):
        try:
            cabecera = f1_udp.decodificar_cabecera(d.carga)
        except f1_udp.ErrorDecodificacion:
            continue
        cabeceras[cabecera["player_car_index"]] += 1
        if cabecera["packet_id"] in (2, 6, 10) and len(d.carga) in tamanos:
            crudos.append((d.desplazamiento_us / 1e6, d.carga))
    propio = cabeceras.most_common(1)[0][0]

    vueltas: list[Vuelta] = []
    telemetria: list[tuple[float, dict]] = []
    dano: list[tuple[float, dict]] = []
    for segundo, carga in crudos:
        try:
            r = f1_udp.decodificar(carga)
        except f1_udp.ErrorDecodificacion:
            continue
        v = r["vehiculos"][propio]
        if r["packet_id"] == 2:
            vueltas.append(Vuelta(segundo, v["current_lap_num"], v["current_lap_time_ms"]))
        elif r["packet_id"] == 6:
            telemetria.append((segundo, v))
        else:
            dano.append((segundo, v))
    return {"propio": propio, "cabeceras": dict(cabeceras), "vueltas": vueltas,
            "telemetria": telemetria, "dano": dano}


def _entero(texto: str) -> int | None:
    texto = (texto or "").strip().replace("%", "").replace("°C", "")
    return int(texto) if texto else None


def _valor_del_dato(serie, instante: float, extraer) -> tuple[int, float, int, int]:
    segundos = [s for s, _ in serie]
    i = muestra_cercana(segundos, instante)
    desde = bisect.bisect_left(segundos, instante - VENTANA_S)
    hasta = bisect.bisect_right(segundos, instante + VENTANA_S)
    ventana = [extraer(serie[j][1]) for j in range(desde, hasta)] or [extraer(serie[i][1])]
    return extraer(serie[i][1]), serie[i][0], min(ventana), max(ventana)


def paso_contrastar(argumentos) -> int:
    plan = {p["paso"]: p for p in json.loads(
        (argumentos.cuadros / "plan.json").read_text(encoding="utf-8"))}
    with argumentos.lecturas.open(encoding="utf-8") as archivo:
        lecturas = list(csv.DictReader(archivo))
    faltan = [f for f in lecturas if f["magnitud"] != "ancla" and not f["pantalla"].strip()
              and "ilegible" not in f["nota"]]
    if faltan:
        print(f"Hay {len(faltan)} lecturas sin completar; primera: {faltan[0]}", file=sys.stderr)
        return 2

    datos = indexar(argumentos.captura)
    print(f"vehiculo propio: {datos['propio']} (cabeceras: {datos['cabeceras']})")
    vueltas = datos["vueltas"]

    # Ancla de cada cuadro.
    anclas: dict[str, dict] = {}
    for paso, p in plan.items():
        instante_global = p["segundo_video_cuadro"] + CAPTURA_MENOS_VIDEO_S
        leido = next((f for f in lecturas if f["paso"] == paso
                      and f["canal"] == "tiempo_de_vuelta"), None)
        ancla = None
        if leido and leido["pantalla"].strip():
            ancla = anclar(vueltas, tiempo_de_vuelta_a_segundos(leido["pantalla"]), instante_global)
        anclas[paso] = {"global": instante_global, "ancla": ancla,
                        "residuo": None if ancla is None else instante_global - ancla}
    residuos = [a["residuo"] for a in anclas.values() if a["residuo"] is not None]
    if not residuos:
        print("Ningun cuadro se pudo anclar.", file=sys.stderr)
        return 2
    residuo_medio = sum(residuos) / len(residuos)
    print(f"cuadros anclados: {len(residuos)} de {len(anclas)}; residuos "
          f"{min(residuos) * 1000:+.0f} a {max(residuos) * 1000:+.0f} ms; "
          f"medio {residuo_medio * 1000:+.1f} ms")

    salida = []
    for paso, p in plan.items():
        a = anclas[paso]
        usado = a["ancla"] if a["ancla"] is not None else a["global"] - residuo_medio
        criterio = "propio" if a["ancla"] is not None else "residuo medio"
        numero_vuelta = vueltas[max(bisect.bisect_right([v.segundo for v in vueltas], usado) - 1, 0)].numero
        for f in (f for f in lecturas if f["paso"] == paso):
            if f["magnitud"] == "ancla" and f["canal"] == "tiempo_de_vuelta":
                continue
            if f["magnitud"] == "ancla":  # rpm
                extraer = lambda v: v["engine_rpm"]  # noqa: E731
                serie = datos["telemetria"]
            elif f["magnitud"] == "temperatura":
                campo = ("engine_temperature_c" if f["canal"] == "motor"
                         else CANALES_TEMPERATURA[f["canal"]])
                rueda = f["rueda"]
                extraer = (lambda v, c=campo: v[c]) if f["canal"] == "motor" else \
                    (lambda v, c=campo, r=rueda: v[c][r])
                serie = datos["telemetria"]
            else:
                extraer = lambda v, c=COMPONENTES[f["canal"]]: v[c]  # noqa: E731
                serie = datos["dano"]
            dato, muestra, minimo, maximo = _valor_del_dato(serie, usado, extraer)
            pantalla = _entero(f["pantalla"])
            alternativa = _entero(f["pantalla_alternativa"])
            salida.append({
                "paso": paso, "magnitud": f["magnitud"], "canal": f["canal"], "rueda": f["rueda"],
                "vuelta": numero_vuelta,
                "segundo_video_cuadro": f"{p['segundo_video_cuadro']:.4f}",
                "segundo_captura_global": f"{a['global']:.4f}",
                "ancla": criterio,
                "residuo_ms": "" if a["residuo"] is None else f"{a['residuo'] * 1000:+.1f}",
                "segundo_captura_usado": f"{usado:.4f}",
                "muestra_dato_s": f"{muestra:.4f}",
                "pantalla": "" if pantalla is None else pantalla,
                "pantalla_alternativa": "" if alternativa is None else alternativa,
                "dato": dato,
                "pantalla_menos_dato": "" if pantalla is None else pantalla - dato,
                "alternativa_menos_dato": "" if alternativa is None else alternativa - dato,
                "dato_min_ventana": minimo, "dato_max_ventana": maximo,
                "nota": f["nota"],
            })

    argumentos.salida.parent.mkdir(parents=True, exist_ok=True)
    with argumentos.salida.open("w", newline="", encoding="utf-8") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=list(salida[0]))
        escritor.writeheader()
        escritor.writerows(salida)
    print(f"pares: {argumentos.salida} ({len(salida)} filas)\n")
    informar(salida)
    return 0


def informar(salida: list[dict]) -> None:
    def difs(filtro):
        return [f["pantalla_menos_dato"] for f in salida
                if filtro(f) and f["pantalla_menos_dato"] != ""]

    grupos = [(f"temperatura {c}", lambda f, c=c: f["magnitud"] == "temperatura" and f["canal"] == c)
              for c in (*CANALES_TEMPERATURA, "motor")]
    grupos.append(("temperatura, todas", lambda f: f["magnitud"] == "temperatura"))
    grupos += [(f"componente {c}", lambda f, c=c: f["magnitud"] == "componente" and f["canal"] == c)
               for c in COMPONENTES]
    grupos.append(("componente, todos", lambda f: f["magnitud"] == "componente"))
    grupos.append(("rpm (comprobacion)", lambda f: f["magnitud"] == "ancla"))
    print(f"{'magnitud':<24} {'pares':>5} {'exactos':>7} {'max|d|':>6}  distribucion de pantalla - dato")
    for nombre, filtro in grupos:
        r = resumir(difs(filtro))
        print(f"{nombre:<24} {r['pares']:>5} {r['exactos']:>7} {str(r['maximo_absoluto']):>6}  "
              f"{r['distribucion']}")

    # La asignacion inversa de filas: punto lleno = superficie, anillo = interior.
    por_paso: dict = {}
    for f in salida:
        if f["magnitud"] == "temperatura" and f["canal"] in ("interior", "superficie"):
            por_paso.setdefault(f["paso"], {})[(f["canal"], f["rueda"])] = f
    for paso, celdas in sorted(por_paso.items()):
        directa = sum(abs(c["pantalla_menos_dato"]) for c in celdas.values())
        inversa = sum(abs(celdas[(canal, r)]["pantalla"] -
                          celdas[("superficie" if canal == "interior" else "interior", r)]["dato"])
                      for canal, r in celdas)
        print(f"  {paso}: suma |pantalla - dato| con punto lleno = interior {directa}; "
              f"invertida {inversa}")


def main(argv: Sequence[str] | None = None) -> int:
    analizador = argparse.ArgumentParser(description="Contraste del panel del juego contra el dato.")
    analizador.add_argument("paso", choices=("cuadros", "contrastar"))
    analizador.add_argument("--captura", type=Path, default=CAPTURA)
    analizador.add_argument("--video", type=Path, default=VIDEO)
    analizador.add_argument("--cuadros", type=Path, default=CUADROS)
    analizador.add_argument("--lecturas", type=Path, default=LECTURAS)
    analizador.add_argument("--salida", type=Path, default=SALIDA)
    argumentos = analizador.parse_args(argv)
    for ruta in (argumentos.captura, argumentos.video):
        if argumentos.paso == "cuadros" or ruta == argumentos.captura:
            if not ruta.exists():
                print(f"No existe: {ruta}", file=sys.stderr)
                return 2
    return paso_cuadros(argumentos) if argumentos.paso == "cuadros" else paso_contrastar(argumentos)


if __name__ == "__main__":
    raise SystemExit(main())
