"""Decodifica candidatos DBC de la senal GAS_PEDAL en una muestra RAV4."""

import argparse
from collections import Counter
from pathlib import Path
import sys

import zstandard as zstd


ROOT = Path(__file__).resolve().parents[1]
OPENPILOT_PATH = ROOT / "external" / "openpilot"
OPENDBC_PATH = ROOT / "datasets" / "openDBC" / "raw" / "opendbc"
RLOG_PATH_POR_DEFECTO = (
    ROOT
    / "datasets"
    / "commaCarSegments"
    / "raw"
    / "TOYOTA_RAV4_TSS2"
    / "sample_01"
    / "rlog.zst"
)

CANDIDATOS_GAS_PEDAL = {
    "881": {
        "can_id": 881,
        "start_bit": 15,
        "length": 8,
        "scale": 0.005,
        "offset": 0,
        "unit": "normalizado",
        "dbc_source": "toyota_nodsu_pt",
    },
    "705": {
        "can_id": 705,
        "start_bit": 55,
        "length": 8,
        "scale": 0.5,
        "offset": 0,
        "unit": "%",
        "dbc_source": "_toyota_adas_standard",
    },
}


def posiciones_big_endian(bit_inicial: int, longitud: int) -> list[int]:
    """Devuelve las posiciones DBC de una senal big-endian, de MSB a LSB."""
    posiciones = []
    bit_actual = bit_inicial

    for _ in range(longitud):
        posiciones.append(bit_actual)
        bit_actual = bit_actual + 15 if bit_actual % 8 == 0 else bit_actual - 1

    return posiciones


def extraer_valor_big_endian(payload: bytes, bit_inicial: int, longitud: int) -> int:
    """Extrae una senal DBC big-endian y devuelve su valor crudo sin signo."""
    valor = 0

    for bit_dbc in posiciones_big_endian(bit_inicial, longitud):
        byte_index = bit_dbc // 8
        bit_en_byte = bit_dbc % 8
        valor = (valor << 1) | ((payload[byte_index] >> bit_en_byte) & 1)

    return valor


def cargar_payloads_acelerador(rlog_path: Path, can_id: int) -> Counter[bytes]:
    """Recorre un log y cuenta los payloads del mensaje CAN de acelerador."""
    sys.path.extend([str(OPENPILOT_PATH), str(OPENDBC_PATH)])
    from openpilot.cereal import log as capnp_log

    data = zstd.ZstdDecompressor().decompress(rlog_path.read_bytes())
    payloads: Counter[bytes] = Counter()

    for event in capnp_log.Event.read_multiple_bytes(data):
        if event.which() != "can":
            continue

        for message in event.can:
            if message.address == can_id:
                payloads[bytes(message.dat)] += 1

    return payloads


def main() -> None:
    """Resume los valores decodificados de GAS_PEDAL para un archivo rlog.zst."""
    parser = argparse.ArgumentParser(
        description="Decodifica una senal GAS_PEDAL definida en un DBC candidato."
    )
    parser.add_argument(
        "--rlog",
        type=Path,
        default=RLOG_PATH_POR_DEFECTO,
        help="Ruta al archivo rlog.zst que se desea analizar.",
    )
    parser.add_argument(
        "--candidato",
        choices=CANDIDATOS_GAS_PEDAL,
        default="881",
        help="Definicion DBC candidata que se desea decodificar.",
    )
    args = parser.parse_args()
    rlog_path = args.rlog.resolve()

    if not rlog_path.is_file():
        raise FileNotFoundError(f"No se encontro el log: {rlog_path}")

    candidate = CANDIDATOS_GAS_PEDAL[args.candidato]
    can_id = candidate["can_id"]
    start_bit = candidate["start_bit"]
    length = candidate["length"]
    scale = candidate["scale"]
    offset = candidate["offset"]
    unit = candidate["unit"]
    dbc_source = candidate["dbc_source"]
    payloads = cargar_payloads_acelerador(rlog_path, can_id)
    valores = []

    for payload, occurrences in payloads.items():
        raw_value = extraer_valor_big_endian(payload, start_bit, length)
        physical_value = raw_value * scale + offset
        valores.append((payload, occurrences, raw_value, physical_value))

    if not valores:
        print(f"rlog={rlog_path}")
        print(f"can_id={can_id}")
        print(f"dbc_source={dbc_source}")
        print("frames_totales=0")
        return

    total_frames = sum(occurrences for _, occurrences, _, _ in valores)
    raw_min = min(value[2] for value in valores)
    raw_max = max(value[2] for value in valores)
    values_by_raw = Counter()

    for _, occurrences, raw_value, _ in valores:
        values_by_raw[raw_value] += occurrences

    representative_min = max(
        (value for value in valores if value[2] == raw_min), key=lambda value: value[1]
    )
    representative_max = max(
        (value for value in valores if value[2] == raw_max), key=lambda value: value[1]
    )

    print(f"rlog={rlog_path}")
    print(f"can_id={can_id}")
    print("senal=GAS_PEDAL")
    print(f"dbc_source={dbc_source}")
    print(f"dbc={start_bit}|{length}@0+ (big-endian)")
    print(f"posiciones={posiciones_big_endian(start_bit, length)}")
    print(f"escala={scale} offset={offset} unidad={unit}")
    print(f"frames_totales={total_frames}")
    print(f"payloads_unicos={len(payloads)}")
    print(f"valores_crudos_unicos={len(values_by_raw)}")
    print(f"rango_crudo={raw_min}..{raw_max}")
    print(
        "rango_decodificado="
        f"{raw_min * scale + offset:.3f}..{raw_max * scale + offset:.3f}"
    )
    print(
        "minimo="
        f"payload={representative_min[0].hex()} ocurrencias={representative_min[1]} "
        f"crudo={representative_min[2]} decodificado={representative_min[3]:.3f}"
    )
    print(
        "maximo="
        f"payload={representative_max[0].hex()} ocurrencias={representative_max[1]} "
        f"crudo={representative_max[2]} decodificado={representative_max[3]:.3f}"
    )


if __name__ == "__main__":
    main()
