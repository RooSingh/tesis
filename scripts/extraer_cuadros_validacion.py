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

Donde va cada cosa
------------------
El video completo vive en `datasets/f1_25/validacion/`, fuera del control de
versiones por su tamano. Los cuadros elegidos van a `informe/tesis/figuras/`,
porque **no son material de trabajo: son las figuras que se imprimen en el
informe**.
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
# La validacion contra el video mostro que varian: en la carrera capturada, el
# indice 3 —documentado como motor— aparece en pantalla como el panel de
# desgaste de neumaticos. Se conserva el nombre de la especificacion y se
# declara la discrepancia, porque el dato util es **el cambio de panel**, que es
# lo que ancla el video, y no el nombre que se le ponga.
PANELES = {
    0: "configuracion", 1: "boxes", 2: "danos", 3: "motor", 4: "temperaturas",
    255: "ninguno",
}

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


def momentos_de_interes(ruta_captura: Path) -> list[dict]:
    """Recorre la captura y elige los instantes que vale la pena contrastar.

    Devuelve cada momento con el segundo del video y el valor que el dato afirma,
    de modo que el contraste sea una comparacion contra una cifra concreta.
    """

    momentos: list[dict] = []
    panel_anterior = None
    velocidad_maxima = (-1, 0.0, None)
    marcha_atras = None
    drs_abierto = None

    for datagrama in f1_capture.leer_captura(ruta_captura):
        if len(datagrama.carga) != f1_udp.PAQUETES[6]["tamano"]:
            continue
        try:
            r = f1_udp.decodificar(datagrama.carga)
        except f1_udp.ErrorDecodificacion:
            continue

        segundo = datagrama.desplazamiento_us / 1_000_000
        propio = r["vehiculo_propio"]
        panel = r.get("mfd_panel")

        # El cambio de panel es el instante mejor determinado de todos: lo
        # declara el propio datagrama, sin depender de ningun reloj externo.
        if panel is not None and panel != panel_anterior and panel in (2, 3, 4):
            momentos.append({
                "segundo": segundo,
                "motivo": f"panel-{PANELES[panel]}",
                "espera": f"panel de {PANELES[panel]} abierto en pantalla",
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


def extraer(ffmpeg: str, video: Path, momentos: list[dict], prefijo: str,
            desfase_s: float) -> list[dict]:
    """Extrae un cuadro por momento y devuelve el manifiesto de lo extraido."""

    FIGURAS.mkdir(parents=True, exist_ok=True)
    manifiesto = []
    for i, m in enumerate(momentos, 1):
        # El desfase corrige que la grabacion suele empezar antes que la captura.
        instante = max(0.0, m["segundo"] + desfase_s)
        destino = FIGURAS / f"{prefijo}_{i:02d}_{m['motivo']}.png"
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
            "segundo_video": round(instante, 3),
            "motivo": m["motivo"],
            "valor_declarado_por_el_dato": m["espera"],
            "extraido": ok,
            "error": None if ok else proceso.stderr.strip()[:200],
        })
        print(f"  {'ok ' if ok else 'FALLO'} {instante:8.2f} s  {m['motivo']:<22} "
              f"{m['espera']}")
    return manifiesto


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captura", type=Path, help="Archivo .f1raw de la sesion.")
    parser.add_argument("video", type=Path, help="Video de la pantalla del juego.")
    parser.add_argument("--prefijo", default=None,
                        help="Prefijo de las imagenes. Por defecto, el de la captura.")
    parser.add_argument("--desfase", type=float, default=0.0,
                        help="Segundos que el video empezo antes que la captura.")
    args = parser.parse_args()

    ffmpeg = buscar_ffmpeg()
    if ffmpeg is None:
        raise SystemExit("No se encontro ffmpeg. Instalarlo antes de extraer cuadros.")

    captura = args.captura if args.captura.exists() else VIDEOS / args.captura.name
    video = args.video if args.video.exists() else VIDEOS / args.video.name
    for ruta in (captura, video):
        if not ruta.exists():
            raise SystemExit(f"No existe: {ruta}")

    prefijo = args.prefijo or captura.stem
    momentos = momentos_de_interes(captura)
    if not momentos:
        raise SystemExit("La captura no declara ningun momento contrastable.")

    print(f"Momentos derivados de la captura: {len(momentos)}")
    print(f"Desfase aplicado al video: {args.desfase:+.2f} s\n")
    manifiesto = extraer(ffmpeg, video, momentos, prefijo, args.desfase)

    destino = FIGURAS / f"{prefijo}_validacion.json"
    destino.write_text(json.dumps({
        "captura": captura.name,
        "video": video.name,
        "desfase_s": args.desfase,
        "cuadros": manifiesto,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nmanifiesto: {destino}")
    print(f"extraidos : {sum(1 for m in manifiesto if m['extraido'])} de {len(manifiesto)}")


if __name__ == "__main__":
    main()
