"""Prepara un stream ordenado y numerado para el replay historico OpenF1.

Motivo
------
`scripts/replay_openf1.py` construia dos listas completas en memoria antes de
publicar el primer mensaje: 1.388.782 muestras y 6.217.506 diccionarios. Para la
carrera completa de Silverstone eso es un bloqueo duro de memoria.

Este script resuelve el problema una sola vez y fuera de la corrida critica. Lee
los archivos crudos de a uno, los mezcla por tiempo con memoria acotada y escribe
un JSONL donde cada linea es una muestra lista para expandir.

Que aporta el archivo resultante
--------------------------------
1. Publicacion incremental: el replay lo lee linea por linea, sin materializar
   nada. El pico de memoria pasa de una decena de gigabytes a unos pocos MB.
2. Secuencia determinista `seq`: cada mensaje que se derivara de la muestra tiene
   un numero global asignado de antemano. Es la clave de idempotencia y lo que
   permite reconciliar contra la base y reanudar exactamente donde se corto.
3. Total conocido antes de publicar: el manifiesto declara cuantos mensajes
   deberian existir, de modo que la verificacion no depende de contar al final.

Orden temporal
--------------
`collect_samples()` ordenaba comparando el campo `date` como texto crudo. Eso
funciona solo si todas las fuentes usan exactamente el mismo formato de fecha, lo
que es una suposicion no declarada. Aqui la clave de orden se construye a partir
de la fecha ya parseada, en microsegundos enteros desde epoch y con ancho fijo,
de modo que el orden lexicografico coincide con el cronologico por construccion.

Este script no publica nada por MQTT ni toca la base de datos: solo lee archivos
locales y escribe un archivo nuevo.
"""

from __future__ import annotations

import argparse
import heapq
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.openf1 import CAR_DATA_SIGNALS, LOCATION_SIGNALS


DATA_ROOT = ROOT / "datasets" / "OpenF1" / "raw" / "2025"
SUPPORTED_ENDPOINTS = {"car_data", "location"}
SIGNAL_MAPS = {"car_data": CAR_DATA_SIGNALS, "location": LOCATION_SIGNALS}
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def parse_time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def clave_orden(fecha: datetime, endpoint: str, driver_number: int) -> str:
    """Construye una clave de ancho fijo cuyo orden de texto es el cronologico.

    Los desempates por `endpoint` y numero de piloto existen para que dos
    ejecuciones del preparador sobre los mismos archivos produzcan exactamente la
    misma secuencia. Sin ese detalle, `seq` dejaria de ser reproducible y la clave
    de idempotencia perderia sentido entre corridas.
    """
    microsegundos = int((fecha - EPOCH).total_seconds() * 1_000_000)
    return f"{microsegundos:020d}\t{endpoint}\t{driver_number:03d}"


def contar_mensajes(sample: dict, endpoint: str) -> int:
    """Cuenta los mensajes que producira una muestra, sin construirlos.

    Replica la regla de `messages_from_openf1_sample`, que omite las senales
    ausentes en la muestra. Contar en vez de expandir permite conocer el total y
    asignar `seq` sin gastar memoria.
    """
    return sum(1 for campo in SIGNAL_MAPS[endpoint] if campo in sample)


def parse_drivers(value: str, session_path: Path) -> list[tuple[int, str]]:
    drivers = json.loads((session_path / "drivers.json").read_text(encoding="utf-8"))
    acronyms = {row["driver_number"]: row["name_acronym"] for row in drivers}
    selected = sorted(acronyms) if value == "all" else sorted({int(item) for item in value.split(",")})
    unknown = [number for number in selected if number not in acronyms]
    if unknown:
        raise ValueError(f"Pilotos no disponibles en la sesion: {unknown}")
    return [(number, acronyms[number]) for number in selected]


def escribir_particion(
    path_origen: Path,
    endpoint: str,
    driver_number: int,
    start: datetime | None,
    end: datetime | None,
    destino: Path,
) -> int:
    """Vuelca un archivo crudo filtrado y ordenado a una particion temporal.

    Se lee un unico archivo por vez: el pico de memoria de esta fase es el de la
    telemetria de un piloto, no la de los veinte.
    """
    rows = json.loads(path_origen.read_text(encoding="utf-8"))
    source_url = (
        f"https://api.openf1.org/v1/{endpoint}"
        f"?session_key={rows[0]['session_key']}&driver_number={driver_number}"
        if rows
        else ""
    )
    raw_payload_path = str(path_origen)

    seleccionadas = []
    for row in rows:
        fecha = parse_time(row["date"])
        if start is not None and fecha < start:
            continue
        if end is not None and fecha >= end:
            continue
        seleccionadas.append((clave_orden(fecha, endpoint, driver_number), row))

    # Se ordena explicitamente en vez de confiar en el orden del archivo: OpenF1
    # los entrega ordenados, pero eso no esta garantizado por contrato.
    seleccionadas.sort(key=lambda par: par[0])

    with destino.open("w", encoding="utf-8") as salida:
        for clave, row in seleccionadas:
            registro = {
                "endpoint": endpoint,
                "driver_number": driver_number,
                "source_url": source_url,
                "raw_payload_path": raw_payload_path,
                "n": contar_mensajes(row, endpoint),
                "sample": row,
            }
            salida.write(f"{clave}\t{json.dumps(registro, sort_keys=True)}\n")
    return len(seleccionadas)


def lineas(path: Path):
    """Itera un archivo temporal linea por linea, sin cargarlo entero."""
    with path.open("r", encoding="utf-8") as archivo:
        for linea in archivo:
            yield linea.rstrip("\n")


def fusionar(particiones: list[Path], destino: Path) -> tuple[int, int]:
    """Mezcla las particiones por tiempo y asigna la secuencia global.

    `heapq.merge` mantiene en memoria una sola linea por particion: con cuarenta
    archivos el costo es de cuarenta cadenas, independientemente del volumen
    total. Es la pieza que hace viable el ordenamiento global sin cargar los
    296 MB de JSON de la sesion completa.
    """
    muestras = 0
    seq = 0
    with destino.open("w", encoding="utf-8") as salida:
        for linea in heapq.merge(*[lineas(path) for path in particiones]):
            # La clave ocupa los tres primeros campos: microsegundos, endpoint y
            # piloto. El cuarto es el registro JSON, que nunca contiene tabuladores
            # literales porque `json.dumps` los escapa.
            registro = json.loads(linea.split("\t", 3)[3])
            registro["seq"] = seq
            salida.write(json.dumps(registro, sort_keys=True) + "\n")
            seq += registro["n"]
            muestras += 1
    return muestras, seq


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-key", type=int, required=True)
    parser.add_argument("--drivers", required=True, help="Lista CSV de numeros o 'all'.")
    parser.add_argument("--start", help="UTC ISO 8601 inclusivo; omitir para inicio disponible.")
    parser.add_argument("--end", help="UTC ISO 8601 exclusivo; omitir para fin disponible.")
    parser.add_argument("--endpoints", default="car_data,location", help="Subset CSV: car_data,location.")
    parser.add_argument("--output", type=Path, required=True, help="Ruta del JSONL de stream a generar.")
    args = parser.parse_args()

    endpoints = args.endpoints.split(",")
    if not endpoints or not set(endpoints) <= SUPPORTED_ENDPOINTS:
        parser.error("--endpoints admite solo car_data y location.")
    start = parse_time(args.start)
    end = parse_time(args.end)
    if start and end and start >= end:
        parser.error("--start debe ser anterior a --end.")

    session_path = DATA_ROOT / str(args.session_key)
    drivers = parse_drivers(args.drivers, session_path)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    directorio_temporal = Path(tempfile.mkdtemp(prefix="replay_stream_", dir=str(args.output.parent)))
    try:
        particiones = []
        for driver_number, acronym in drivers:
            for endpoint in endpoints:
                origen = session_path / f"{endpoint}_driver_{driver_number}_{acronym}.json"
                if not origen.is_file():
                    raise FileNotFoundError(
                        f"No existe telemetria {endpoint} para piloto {driver_number}: {origen}"
                    )
                destino = directorio_temporal / f"{endpoint}_{driver_number}.part"
                escribir_particion(origen, endpoint, driver_number, start, end, destino)
                particiones.append(destino)

        muestras, mensajes = fusionar(particiones, args.output)
    finally:
        shutil.rmtree(directorio_temporal, ignore_errors=True)

    manifiesto = {
        "session_key": args.session_key,
        "drivers": [number for number, _ in drivers],
        "endpoints": endpoints,
        "requested_start": args.start,
        "requested_end": args.end,
        "stream_file": str(args.output),
        "source_samples": muestras,
        "expected_messages": mensajes,
        "prepared_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    manifiesto_path = args.output.with_suffix(args.output.suffix + ".manifest.json")
    manifiesto_path.write_text(json.dumps(manifiesto, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(manifiesto, sort_keys=True))


if __name__ == "__main__":
    main()
