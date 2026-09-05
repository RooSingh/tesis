# -*- coding: utf-8 -*-
"""Corre los escenarios de frecuencia variable y de llegada irregular.

Que escenarios son
------------------
Los dos que el anexo pide y que hasta ahora figuraban pendientes por depender de
una persona jugando: **frecuencia de actualizacion variable** y **degradacion o
fallo temporal de comunicacion**. El reproductor los vuelve ejecutables, porque
degrada **trafico real ya capturado** y lo emite por red.

Como se mide, y por que asi
---------------------------
Se levanta un capturador propio, **en otro puerto y sin publicar**, y se
reproduce contra el. Las tres decisiones tienen motivo:

- **en otro puerto**, para no interferir con el capturador que escucha al juego;
- **sin publicar**, porque republicar una sesion real duplicaria su telemetria en
  la base: las filas de una captura viva no llevan identidad de reinyeccion y
  nada las deduplicaria;
- **contra un capturador de verdad y no contra un socket de juguete**, porque lo
  que se quiere medir es lo que el camino de adquisicion hace con un flujo
  degradado, y un receptor simplificado mediria otra cosa.

Lo que la comparacion permite afirmar
-------------------------------------
La captura que resulta se compara **datagrama por datagrama** contra la original.
Eso da una conciliacion cerrada: lo emitido tiene que ser lo original menos lo
descartado, y lo recibido tiene que ser lo emitido menos lo que se perdio en el
camino. Las dos restas tienen que cerrar, y si no cierran el escenario no vale.

Lo que **no** cubre: el tramo del intermediario a la base, que se mide aparte con
`medir_latencia_cadena.py` y no se puede componer con este sin declararlo.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from backend import f1_capture  # noqa: E402

# Puerto propio del escenario. No es el del juego, a proposito.
PUERTO_ESCENARIO = 20778

DESTINO = RAIZ / "datasets" / "f1_25" / "escenarios"

# Cuanto silencio cierra la captura del escenario. Corto, porque acá no hay
# nadie navegando menús: en cuanto la reproducción termina, terminó.
SILENCIO_S = 4.0

# Los escenarios, con el nombre de lo que cada uno interroga.
ESCENARIOS = [
    # Frecuencia de actualizacion variable: el mismo flujo, mas lento y mas
    # rapido. La velocidad no altera que se envia, solo cada cuanto.
    {"nombre": "frecuencia_mitad", "velocidad": 0.5},
    {"nombre": "frecuencia_normal", "velocidad": 1.0},
    {"nombre": "frecuencia_doble", "velocidad": 2.0},
    {"nombre": "frecuencia_cuadruple", "velocidad": 4.0},
    # Llegada irregular y perdida: la velocidad se deja en uno para que lo unico
    # que cambie sea la degradacion.
    {"nombre": "perdida_5", "velocidad": 1.0, "descarte": 0.05},
    {"nombre": "perdida_20", "velocidad": 1.0, "descarte": 0.20},
    {"nombre": "irregular_20ms", "velocidad": 1.0, "jitter_ms": 20.0},
    {"nombre": "irregular_y_perdida", "velocidad": 1.0,
     "descarte": 0.05, "jitter_ms": 20.0},
]


def _contar(ruta: Path) -> int:
    return sum(1 for _ in f1_capture.leer_captura(ruta))


def _capturas_en(directorio: Path) -> set[Path]:
    return set(directorio.glob("*.f1raw"))


def correr_uno(original: Path, escenario: dict, limite: int | None,
               puerto: int) -> dict:
    """Levanta el capturador, reproduce, y devuelve la conciliacion."""

    DESTINO.mkdir(parents=True, exist_ok=True)
    antes = _capturas_en(DESTINO)

    receptor = subprocess.Popen(
        [sys.executable, str(RAIZ / "scripts" / "capturar_f1_25.py"),
         "--puerto", str(puerto), "--sin-publicar",
         "--destino", str(DESTINO), "--silencio", str(SILENCIO_S)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    # El capturador tarda en ligar el socket. Emitir antes de que este escuchando
    # perderia los primeros datagramas y el escenario informaria una perdida que
    # no ocurrio en el camino sino en el arranque.
    time.sleep(2.0)

    emisor = [sys.executable, str(RAIZ / "scripts" / "reproducir_captura_f1_25.py"),
              str(original), "--puerto", str(puerto),
              "--velocidad", str(escenario.get("velocidad", 1.0)),
              "--descarte", str(escenario.get("descarte", 0.0)),
              "--jitter-ms", str(escenario.get("jitter_ms", 0.0)),
              "--retraso-ms", str(escenario.get("retraso_ms", 0.0)),
              "--semilla", str(escenario.get("semilla", 7))]
    if limite:
        emisor += ["--limite", str(limite)]

    salida = subprocess.run(emisor, capture_output=True, text=True)
    emitidos = descartados = leidos = None
    for linea in salida.stdout.splitlines():
        partes = linea.split()
        if linea.strip().startswith("leidos"):
            leidos = int(partes[1].replace(",", ""))
        elif linea.strip().startswith("emitidos"):
            emitidos = int(partes[1].replace(",", ""))
        elif linea.strip().startswith("descartados"):
            descartados = int(partes[1].replace(",", ""))

    # Se espera el silencio que cierra la captura, mas margen.
    time.sleep(SILENCIO_S + 3.0)
    receptor.terminate()
    try:
        receptor.wait(timeout=15)
    except subprocess.TimeoutExpired:
        receptor.kill()

    nuevas = _capturas_en(DESTINO) - antes
    recibidos = None
    archivo = None
    if nuevas:
        archivo = max(nuevas, key=lambda p: p.stat().st_size)
        recibidos = _contar(archivo)
        destino = archivo.with_name(f"{escenario['nombre']}.f1raw")
        if destino.exists():
            destino.unlink()
        archivo.rename(destino)
        # Los metadatos derivados acompañan al archivo.
        meta = archivo.with_suffix(archivo.suffix + ".meta.json")
        if meta.exists():
            meta.rename(destino.with_suffix(destino.suffix + ".meta.json"))
        archivo = destino

    return {
        "escenario": escenario["nombre"],
        "velocidad": escenario.get("velocidad", 1.0),
        "descarte_pedido": escenario.get("descarte", 0.0),
        "jitter_ms": escenario.get("jitter_ms", 0.0),
        "leidos": leidos,
        "descartados": descartados,
        "emitidos": emitidos,
        "recibidos": recibidos,
        "archivo": archivo.name if archivo else None,
        # Las dos restas que tienen que cerrar.
        "cierra_el_emisor": (leidos == (descartados or 0) + (emitidos or 0)
                             if leidos is not None and emitidos is not None
                             else None),
        "perdidos_en_el_camino": ((emitidos - recibidos)
                                  if emitidos is not None and recibidos is not None
                                  else None),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("captura", type=Path, help="la captura original a degradar")
    ap.add_argument("--limite", type=int, default=4000,
                    help="datagramas por corrida; acota la duracion")
    ap.add_argument("--puerto", type=int, default=PUERTO_ESCENARIO)
    ap.add_argument("--solo", nargs="*", default=None,
                    help="corre solo estos escenarios, por nombre")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    if not args.captura.exists():
        print(f"no existe la captura: {args.captura}")
        return 1

    elegidos = [e for e in ESCENARIOS
                if args.solo is None or e["nombre"] in args.solo]
    print(f"original: {args.captura.name}")
    print(f"receptor: capturador propio en el puerto {args.puerto}, sin publicar")
    print(f"destino:  {DESTINO}")
    print()
    # Se muestran las dos restas enteras. Con solo "emitidos" y "recibidos" el
    # descarte queda invisible, porque el limite cuenta datagramas emitidos: la
    # corrida lee de mas y emite siempre la misma cantidad.
    print(f"  {'escenario':<22}{'vel':>5}{'ped':>5}{'jit':>5}"
          f"{'leidos':>9}{'descart':>9}{'real':>7}"
          f"{'emitidos':>10}{'recibidos':>11}{'perdidos':>9}{'cierra':>7}")
    print("  " + "-" * 99)

    resultados = []
    for e in elegidos:
        r = correr_uno(args.captura, e, args.limite, args.puerto)
        resultados.append(r)
        perdidos = r["perdidos_en_el_camino"]
        real = ((r["descartados"] / r["leidos"] * 100)
                if r["leidos"] else 0.0)
        r["descarte_real"] = real / 100
        print(f"  {r['escenario']:<22}{r['velocidad']:>5.1f}"
              f"{r['descarte_pedido'] * 100:>4.0f}%{r['jitter_ms']:>4.0f}m"
              f"{(r['leidos'] or 0):>9,}{(r['descartados'] or 0):>9,}"
              f"{real:>6.1f}%"
              f"{(r['emitidos'] or 0):>10,}{(r['recibidos'] or 0):>11,}"
              f"{(perdidos if perdidos is not None else 0):>9,}"
              f"{'si' if r['cierra_el_emisor'] else 'NO':>7}")

    if args.json:
        args.json.write_text(json.dumps(resultados, indent=1), encoding="utf-8")
        print(f"\n  crudo en {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
