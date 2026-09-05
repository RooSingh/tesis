"""Extrae las tramas CAN de un segmento a un formato propio.

Es el **unico** lugar del proyecto que depende de la biblioteca de openpilot.
Todo lo que se construya despues —adaptador, pruebas, reproduccion— lee el
formato propio y no necesita nada de eso.

Por que se hace una vez y no en cada lectura
--------------------------------------------
Leer un `rlog.zst` exige 1,8 GB de openpilot mas el repositorio de `opendbc`, con
dos rutas agregadas a mano al camino de importacion. Se comprobo ademas que el
esquema no puede cargarse por fuera de ese entorno: el proceso termina sin
excepcion.

Depender de eso para leer ata todo lo que venga encima. Extraido una vez, la
dependencia queda contenida aca.

Es el mismo criterio que el trabajo aplico a la fuente simulada, donde probo su
valor: conservar el registro en un formato propio permitio rehacer la
interpretacion de una captura sin volver a medirla.

Que se conserva
---------------
La trama entera, sin interpretar: instante, identificador, bus y bytes.
Decodificar es tarea del adaptador. Mantener el registro crudo es lo que permite
corregir una interpretacion equivocada sin tocar el dato.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import zstandard as zstd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Las dos rutas que la biblioteca necesita. Sin la segunda, el import falla por
# `opendbc` y no por openpilot, que es lo que despista al diagnosticar.
sys.path.append(str(ROOT / "external" / "openpilot"))
sys.path.append(str(ROOT / "datasets" / "openDBC" / "raw" / "opendbc"))

from backend import can_capture  # noqa: E402

SEGMENTOS = ROOT / "datasets" / "commaCarSegments" / "raw"
DESTINO = ROOT / "datasets" / "can" / "capturas"


def extraer(origen: Path, destino: Path, plataforma: str, segmento: str) -> dict:
    """Convierte un `rlog.zst` en una captura propia y devuelve su resumen."""

    from openpilot.cereal import log as capnp_log  # noqa: PLC0415

    with origen.open("rb") as comprimido:
        crudo = zstd.ZstdDecompressor().stream_reader(comprimido).read()

    por_identificador: Counter = Counter()
    por_bus: Counter = Counter()
    primer_instante = None
    ultimo_instante = 0
    eventos = 0

    with can_capture.EscritorCaptura(destino) as escritor:
        for evento in capnp_log.Event.read_multiple_bytes(crudo):
            eventos += 1
            if evento.which() != "can":
                continue
            # El instante del evento es el reloj del registrador, en
            # nanosegundos. Se conserva relativo al primero para que la captura
            # no dependa de cuando se grabo.
            absoluto = evento.logMonoTime
            if primer_instante is None:
                primer_instante = absoluto
            relativo = absoluto - primer_instante
            ultimo_instante = max(ultimo_instante, relativo)
            for trama in evento.can:
                escritor.escribir(relativo, trama.address, trama.src, bytes(trama.dat))
                por_identificador[trama.address] += 1
                por_bus[trama.src] += 1

    return {
        "plataforma": plataforma,
        "segmento": segmento,
        "origen": str(origen.relative_to(ROOT)).replace("\\", "/"),
        "eventos_leidos": eventos,
        "tramas": escritor.tramas,
        "duracion_s": round(ultimo_instante / 1e9, 3),
        "identificadores_distintos": len(por_identificador),
        "buses": dict(sorted(por_bus.items())),
        # Los mas frecuentes sirven para reconocer el segmento sin abrirlo.
        "identificadores_mas_frecuentes": [
            {"id": i, "tramas": n} for i, n in por_identificador.most_common(10)
        ],
        # Declarado y no supuesto: la extraccion necesito esta biblioteca, la
        # lectura posterior no.
        "extraido_con": "openpilot.cereal (dependencia contenida en la extraccion)",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plataforma", default="TOYOTA_RAV4_TSS2")
    parser.add_argument("--segmentos", nargs="*", default=None,
                        help="Nombres de segmento. Por defecto, todos.")
    parser.add_argument("--destino", type=Path, default=DESTINO)
    args = parser.parse_args()

    origen_plataforma = SEGMENTOS / args.plataforma
    if not origen_plataforma.is_dir():
        raise SystemExit(f"No existe la plataforma: {origen_plataforma}")

    disponibles = sorted(d.name for d in origen_plataforma.iterdir() if d.is_dir())
    elegidos = args.segmentos or disponibles
    print(f"plataforma : {args.plataforma}")
    print(f"segmentos  : {len(elegidos)} de {len(disponibles)} disponibles\n")

    total_tramas = 0
    for nombre in elegidos:
        origen = origen_plataforma / nombre / "rlog.zst"
        if not origen.is_file():
            print(f"  {nombre}: sin rlog.zst, se omite")
            continue
        destino = args.destino / f"{args.plataforma}_{nombre}.canraw"
        resumen = extraer(origen, destino, args.plataforma, nombre)
        can_capture.escribir_metadatos(destino, resumen)
        total_tramas += resumen["tramas"]
        print(f"  {nombre}: {resumen['tramas']:>7,} tramas, "
              f"{resumen['identificadores_distintos']:>3} identificadores, "
              f"{resumen['duracion_s']:>6.1f} s")

    print(f"\ntotal: {total_tramas:,} tramas en {args.destino}")
    print("La dependencia de openpilot termina aca: lo que sigue lee el formato propio.")


if __name__ == "__main__":
    main()
