"""Extrae cuadros de video en los instantes que la propia captura declara.

Para que sirve
--------------
El decodificador esta **verificado pero no validado**: se sabe que las estructuras
cierran contra la especificacion y que los valores son coherentes entre si, pero
no que **signifiquen** lo que la especificacion dice. Si un campo llamado
velocidad transportara otra cosa, todo seguiria siendo consistente.

El video de la pantalla del juego es la unica evidencia independiente de que si
significan eso. Este script convierte esa evidencia en imagenes contrastables.

Como encuentra los instantes
----------------------------
No hay que buscarlos a ojo ni sincronizar relojes. **El propio datagrama declara
que panel del vehiculo estaba abierto** en cada momento, de modo que el instante
del cambio de panel se lee de los datos y se traduce directamente a un segundo
del video.

Para los demas canales se eligen instantes notables: la velocidad maxima, el
momento de marcha atras, la apertura del aleron movil. Cada uno con su valor
esperado, para que el contraste sea una comparacion y no una impresion.

El cuadro de un cambio de panel se toma despues del cambio, no en el cambio
--------------------------------------------------------------------------
La pantalla y el dato cambian de panel casi a la vez. Medido sobre los 19
cambios de panel del video de Silverstone: una decima antes y en el instante
del cambio todavia se ve el panel anterior; una decima despues el lugar esta
vacio; a las dos decimas aparece el nuevo, en 4 de los 19 todavia a medio
dibujar; a las tres decimas esta completo en los 19. Un cuadro tomado **en** el
instante del cambio muestra por lo tanto el panel anterior, y todas las figuras
quedaban corridas un indice. Por eso a cada cambio de panel se le suma
`--retardo` (0,3 s por omision).

El retardo se aplica **solo a los cambios de panel**. La velocidad maxima, la
marcha atras y la apertura del aleron son instantes de un valor, no transiciones
de pantalla: correrlos tres decimas los aleja del valor que se quiere ver.

Donde va cada cosa
------------------
El video completo vive en `datasets/f1_25/validacion/`, fuera del control de
versiones por su tamano. Los cuadros van a `--destino`, que por omision es
`informe/tesis/figuras/` porque esos cuadros son las figuras que se imprimen en
el informe. **Para trabajar o comprobar, usar un destino fuera del informe**: el
manifiesto JSON va al mismo destino que los cuadros.

`--muestreo` no extrae los momentos de interes sino tres cuadros por cada tramo
de panel ---a 1 s del comienzo, a la mitad y a 1 s del final--- para comprobar
que cada indice muestra siempre el mismo panel.

Uso
---
    python -B scripts/extraer_cuadros_validacion.py CAPTURA.f1raw VIDEO.mp4 \\
        --desfase -26.853 --destino datasets/f1_25/validacion/cuadros
    python -B scripts/extraer_cuadros_validacion.py CAPTURA.f1raw VIDEO.mp4 \\
        --desfase -26.853 --destino datasets/f1_25/validacion/cuadros --muestreo
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import f1_capture, f1_udp

VIDEOS = ROOT / "datasets" / "f1_25" / "validacion"
FIGURAS = ROOT / "informe" / "tesis" / "figuras"

# Los nombres son los de la especificacion, que los declara **para partida de un
# solo jugador en carrera** y advierte que pueden variar segun el modo de juego.
#
# La validacion contra el video mostro que varian. Lo que la pantalla muestra en
# cada indice esta en `PANTALLA`, medido sobre la carrera de Silverstone del
# 2026-08-30 con cuadros tomados dentro de cada tramo de panel (y no en el
# instante del cambio, que muestra el panel anterior: ver el docstring). Se
# conservan los nombres de la especificacion porque son los del protocolo, y al
# lado se declara lo que se ve: el 0 y el 1 coinciden con su nombre; el 2, el 3 y
# el 4 no.
#
# Dos excepciones vistas en esa carrera, que no cambian el mapeo: con el indice 0
# abierto, durante la largada y la salida de boxes el lugar del panel lo ocupan
# las indicaciones del embrague; y con el 2 abierto durante la vuelta de
# formacion, la pantalla muestra temperaturas y no desgaste.
PANELES = {
    0: "configuracion", 1: "boxes", 2: "danos", 3: "motor", 4: "temperaturas",
    255: "ninguno",
}
PANTALLA = {
    0: "ajustes",
    1: "ventana de parada en boxes",
    2: "desgaste de neumaticos (temperaturas durante la vuelta de formacion)",
    3: "temperaturas",
    4: "desgaste por componente",
    255: "ninguno",
}
# Forma corta de `PANTALLA` para nombrar archivos.
PANTALLA_CORTA = {
    0: "ajustes", 1: "boxes", 2: "desgaste-neumaticos", 3: "temperaturas",
    4: "desgaste-componentes", 255: "ninguno",
}

# Segundos que se esperan despues de un cambio de panel antes de tomar el cuadro.
RETARDO_PANEL_S = 0.3

# Precision alcanzable con este metodo, medida sobre tres anclas independientes
# del mismo video: el desfase resulto -26,853, -26,804 y -26,251 segundos, o sea
# una dispersion de seis decimas.
#
# Alcanza de sobra para los canales de estado —panel abierto, marcha, vuelta,
# posicion, desgaste, carga de bateria— que se sostienen segundos enteros. **No
# alcanza para velocidad ni revoluciones**, que a 255 km/h cambian lo suficiente
# en seis decimas como para que el contraste no signifique nada.
#
# Para esos canales el contraste tiene que anclarse **en el propio cuadro**: se
# lee el tiempo de vuelta que la pantalla muestra, se lo busca en el dato, y el
# instante queda determinado sin depender del desfase global.
DISPERSION_DESFASE_S = 0.6


def buscar_ffmpeg() -> str | None:
    """Ubica ffmpeg en el sistema o en la instalacion por usuario."""

    hallado = shutil.which("ffmpeg")
    if hallado:
        return hallado
    candidatos = list(
        (Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages")
        .glob("**/ffmpeg.exe")
    )
    return str(candidatos[0]) if candidatos else None


def instante_de_video(segundo_captura: float, desfase_s: float,
                      retardo_s: float = 0.0) -> float:
    """Segundo del video que corresponde a un segundo de la captura.

    `desfase_s` es el instante de video menos el de captura (negativo cuando el
    video empezo despues que la captura). `retardo_s` se suma despues: es la
    espera posterior al evento, no una correccion del reloj.
    """

    return max(0.0, segundo_captura + retardo_s + desfase_s)


def _telemetria(ruta_captura: Path):
    """Recorre los paquetes de telemetria (6) con su segundo de captura."""

    for datagrama in f1_capture.leer_captura(ruta_captura):
        if len(datagrama.carga) != f1_udp.PAQUETES[6]["tamano"]:
            continue
        try:
            r = f1_udp.decodificar(datagrama.carga)
        except f1_udp.ErrorDecodificacion:
            continue
        yield datagrama.desplazamiento_us / 1_000_000, r


def tramos_de_panel(ruta_captura: Path) -> list[dict]:
    """Los tramos contiguos en que la captura declara un mismo panel abierto."""

    tramos: list[dict] = []
    for segundo, r in _telemetria(ruta_captura):
        panel = r.get("mfd_panel")
        if tramos and tramos[-1]["panel"] == panel:
            tramos[-1]["fin"] = segundo
        else:
            if tramos:
                tramos[-1]["fin"] = segundo
            tramos.append({"panel": panel, "inicio": segundo, "fin": segundo})
    return tramos


def puntos_de_muestreo(inicio: float, fin: float, margen_s: float = 1.0) -> list[tuple[str, float]]:
    """A `margen_s` del comienzo, a la mitad y a `margen_s` del final.

    Un tramo demasiado corto para tres puntos distintos y alejados del borde se
    muestrea solo a la mitad, y el nombre del punto lo declara.
    """

    mitad = (inicio + fin) / 2
    if fin - inicio < 2 * margen_s + 0.5:
        return [("solo-mitad", mitad)]
    return [("comienzo", inicio + margen_s), ("mitad", mitad), ("final", fin - margen_s)]


def momentos_de_interes(ruta_captura: Path,
                        retardo_panel_s: float = RETARDO_PANEL_S) -> list[dict]:
    """Recorre la captura y elige los instantes que vale la pena contrastar.

    Devuelve cada momento con el segundo de la captura, el retardo que hay que
    sumarle antes de tomar el cuadro y el valor que el dato afirma, de modo que
    el contraste sea una comparacion contra una cifra concreta.
    """

    momentos: list[dict] = []
    panel_anterior = None
    velocidad_maxima = (-1, 0.0, None)
    marcha_atras = None
    drs_abierto = None

    for segundo, r in _telemetria(ruta_captura):
        propio = r["vehiculo_propio"]
        panel = r.get("mfd_panel")

        # El cambio de panel es el instante mejor determinado de todos: lo
        # declara el propio datagrama, sin depender de ningun reloj externo.
        # Pero la pantalla tarda en mostrar el panel nuevo: el cuadro se toma
        # `retardo_panel_s` despues.
        if panel is not None and panel != panel_anterior and panel in (2, 3, 4):
            momentos.append({
                "segundo": segundo,
                "retardo_s": retardo_panel_s,
                "motivo": f"panel{panel}-{PANTALLA_CORTA[panel]}",
                "espera": (f"panel {panel} ({PANELES[panel]} segun la especificacion; "
                           f"en pantalla: {PANTALLA[panel]})"),
            })
            panel_anterior = panel
        elif panel is not None:
            panel_anterior = panel

        if propio["speed_kmh"] > velocidad_maxima[1]:
            velocidad_maxima = (segundo, propio["speed_kmh"], propio["gear"])

        if marcha_atras is None and propio["gear"] == -1:
            marcha_atras = (segundo, propio["speed_kmh"])

        if drs_abierto is None and propio["drs"] == 1:
            drs_abierto = (segundo, propio["speed_kmh"])

    if velocidad_maxima[0] >= 0:
        momentos.append({
            "segundo": velocidad_maxima[0],
            "motivo": "velocidad-maxima",
            "espera": f"velocidad {velocidad_maxima[1]} km/h, marcha {velocidad_maxima[2]}",
        })
    if marcha_atras:
        momentos.append({
            "segundo": marcha_atras[0],
            "motivo": "marcha-atras",
            # Es el caso que la verificacion aritmetica no puede atrapar: tipear
            # el campo sin signo daria 255 sin alterar el tamano del paquete.
            "espera": "la pantalla debe mostrar R",
        })
    if drs_abierto:
        momentos.append({
            "segundo": drs_abierto[0],
            "motivo": "aleron-abierto",
            "espera": "indicador de aleron movil encendido",
        })

    return sorted(momentos, key=lambda m: m["segundo"])


def momentos_de_muestreo(ruta_captura: Path) -> list[dict]:
    """Tres momentos por tramo de panel, para comprobar que muestra cada indice."""

    momentos = []
    for n, tramo in enumerate(tramos_de_panel(ruta_captura), 1):
        panel = tramo["panel"]
        for punto, segundo in puntos_de_muestreo(tramo["inicio"], tramo["fin"]):
            momentos.append({
                "segundo": segundo,
                "retardo_s": 0.0,
                "motivo": f"tramo{n:02d}_panel{panel}_{punto}",
                "espera": (f"panel {panel} abierto de {tramo['inicio']:.3f} a "
                           f"{tramo['fin']:.3f} s de captura"),
                "tramo": n,
                "panel": panel,
            })
    return momentos


def extraer(ffmpeg: str, video: Path, momentos: list[dict], prefijo: str,
            desfase_s: float, destino_dir: Path = FIGURAS) -> list[dict]:
    """Extrae un cuadro por momento y devuelve el manifiesto de lo extraido."""

    destino_dir.mkdir(parents=True, exist_ok=True)
    manifiesto = []
    for i, m in enumerate(momentos, 1):
        # El desfase corrige que la grabacion y la captura no empiezan a la vez;
        # el retardo espera a que la pantalla muestre lo que el dato ya declara.
        retardo = m.get("retardo_s", 0.0)
        instante = instante_de_video(m["segundo"], desfase_s, retardo)
        destino = destino_dir / f"{prefijo}_{i:02d}_{m['motivo']}.png"
        proceso = subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error",
             "-ss", f"{instante:.3f}", "-i", str(video),
             "-frames:v", "1", str(destino)],
            capture_output=True, text=True,
        )
        ok = destino.exists() and proceso.returncode == 0
        manifiesto.append({
            "archivo": destino.name if ok else None,
            "segundo_captura": round(m["segundo"], 3),
            "retardo_s": retardo,
            "segundo_video": round(instante, 3),
            "motivo": m["motivo"],
            "valor_declarado_por_el_dato": m["espera"],
            "extraido": ok,
            "error": None if ok else proceso.stderr.strip()[:200],
        })
        print(f"  {'ok ' if ok else 'FALLO'} {instante:8.2f} s  {m['motivo']:<28} "
              f"{m['espera']}")
    return manifiesto


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("captura", type=Path, help="Archivo .f1raw de la sesion.")
    parser.add_argument("video", type=Path, help="Video de la pantalla del juego.")
    parser.add_argument("--prefijo", default=None,
                        help="Prefijo de las imagenes. Por defecto, el de la captura.")
    parser.add_argument("--desfase", type=float, default=0.0,
                        help="Instante de video menos instante de captura, en segundos "
                             "(negativo si el video empezo despues que la captura).")
    parser.add_argument("--retardo", type=float, default=RETARDO_PANEL_S,
                        help="Segundos que se esperan despues de un cambio de panel "
                             f"antes de tomar el cuadro (por omision {RETARDO_PANEL_S}).")
    parser.add_argument("--destino", type=Path, default=FIGURAS,
                        help="Carpeta de los cuadros y del manifiesto "
                             "(por omision, informe/tesis/figuras).")
    parser.add_argument("--muestreo", action="store_true",
                        help="Tres cuadros por tramo de panel en lugar de los momentos "
                             "de interes.")
    args = parser.parse_args(argv)

    ffmpeg = buscar_ffmpeg()
    if ffmpeg is None:
        raise SystemExit("No se encontro ffmpeg. Instalarlo antes de extraer cuadros.")

    captura = args.captura if args.captura.exists() else VIDEOS / args.captura.name
    video = args.video if args.video.exists() else VIDEOS / args.video.name
    for ruta in (captura, video):
        if not ruta.exists():
            raise SystemExit(f"No existe: {ruta}")

    prefijo = args.prefijo or captura.stem
    if args.muestreo:
        momentos = momentos_de_muestreo(captura)
        prefijo = f"{prefijo}_muestreo"
    else:
        momentos = momentos_de_interes(captura, args.retardo)
    if not momentos:
        raise SystemExit("La captura no declara ningun momento contrastable.")

    print(f"Momentos derivados de la captura: {len(momentos)}")
    print(f"Desfase aplicado al video: {args.desfase:+.3f} s")
    print(f"Retardo tras un cambio de panel: {args.retardo:.3f} s")
    print(f"Destino: {args.destino}\n")
    manifiesto = extraer(ffmpeg, video, momentos, prefijo, args.desfase, args.destino)

    destino = args.destino / f"{prefijo}_validacion.json"
    destino.write_text(json.dumps({
        "captura": captura.name,
        "video": video.name,
        "desfase_s": args.desfase,
        "retardo_panel_s": 0.0 if args.muestreo else args.retardo,
        "paneles": {str(i): {"especificacion": PANELES[i], "pantalla": PANTALLA[i]}
                    for i in PANELES},
        "cuadros": manifiesto,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nmanifiesto: {destino}")
    print(f"extraidos : {sum(1 for m in manifiesto if m['extraido'])} de {len(manifiesto)}")


if __name__ == "__main__":
    main()
