"""Analiza bit a bit BRAKE_PRESSED en el mensaje CAN 550 de la muestra RAV4."""

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

CAN_ID_BRAKE_MODULE = 550

SENALES_FRENO = (
    ("BRAKE_PRESSURE", 0, 9, 1, 0),
    ("BRAKE_POSITION", 16, 9, 1, 0),
    ("BRAKE_PRESSED", 37, 1, 1, 0),
)


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


def cargar_payloads_freno(rlog_path: Path) -> Counter[bytes]:
    """Recorre el log y cuenta los payloads del mensaje BRAKE_MODULE."""
    sys.path.extend([str(OPENPILOT_PATH), str(OPENDBC_PATH)])
    from openpilot.cereal import log as capnp_log

    data = zstd.ZstdDecompressor().decompress(rlog_path.read_bytes())
    payloads: Counter[bytes] = Counter()

    for event in capnp_log.Event.read_multiple_bytes(data):
        if event.which() != "can":
            continue

        for message in event.can:
            if message.address == CAN_ID_BRAKE_MODULE:
                payloads[bytes(message.dat)] += 1

    return payloads


def main() -> None:
    """Muestra los payloads y las senales de freno decodificadas desde el DBC."""
    parser = argparse.ArgumentParser(
        description="Decodifica las senales de freno del mensaje CAN 550."
    )
    parser.add_argument(
        "--rlog",
        type=Path,
        default=RLOG_PATH_POR_DEFECTO,
        help="Ruta al archivo rlog.zst que se desea analizar.",
    )
    parser.add_argument(
        "--detallado",
        action="store_true",
        help="Muestra cada payload distinto en lugar del resumen consolidado.",
    )
    args = parser.parse_args()
    rlog_path = args.rlog.resolve()

    if not rlog_path.is_file():
        raise FileNotFoundError(f"No se encontro el log: {rlog_path}")

    payloads = cargar_payloads_freno(rlog_path)

    print(f"rlog={rlog_path}")
    print(f"can_id={CAN_ID_BRAKE_MODULE}")
    print("mensaje=BRAKE_MODULE")
    print("orden_de_bits=big-endian (@0 en DBC)")
    for signal_name, start_bit, length, scale, offset in SENALES_FRENO:
        print(
            f"senal={signal_name} dbc={start_bit}|{length}@0+ "
            f"posiciones={posiciones_big_endian(start_bit, length)} "
            f"escala={scale} offset={offset}"
        )
    print(f"payloads_unicos={len(payloads)}")

    filas = []
    for payload, occurrences in payloads.most_common():
        values = {}
        for signal_name, start_bit, length, scale, offset in SENALES_FRENO:
            raw_value = extraer_valor_big_endian(payload, start_bit, length)
            physical_value = raw_value * scale + offset
            values[signal_name] = physical_value

        filas.append((payload, occurrences, values))

    total_frames = sum(occurrences for _, occurrences, _ in filas)
    frames_por_freno = Counter()
    valores_presion = []
    valores_posicion = []
    payload_representativo = {}

    for payload, occurrences, values in filas:
        brake_pressed = values["BRAKE_PRESSED"]
        frames_por_freno[brake_pressed] += occurrences
        valores_presion.append(values["BRAKE_PRESSURE"])
        valores_posicion.append(values["BRAKE_POSITION"])

        if (
            brake_pressed not in payload_representativo
            or occurrences > payload_representativo[brake_pressed][1]
        ):
            payload_representativo[brake_pressed] = (payload, occurrences, values)

    print(f"frames_totales={total_frames}")
    print(
        "rango_BRAKE_PRESSURE="
        f"{min(valores_presion)}..{max(valores_presion)}"
    )
    print(
        "rango_BRAKE_POSITION="
        f"{min(valores_posicion)}..{max(valores_posicion)}"
    )

    for brake_pressed in sorted(frames_por_freno):
        payload, occurrences, values = payload_representativo[brake_pressed]
        print(
            f"BRAKE_PRESSED={brake_pressed} frames={frames_por_freno[brake_pressed]} "
            f"payload_representativo={payload.hex()} "
            f"ocurrencias_payload={occurrences} "
            f"BRAKE_PRESSURE={values['BRAKE_PRESSURE']} "
            f"BRAKE_POSITION={values['BRAKE_POSITION']}"
        )

    if args.detallado:
        for payload, occurrences, values in filas:
            valores_formateados = " ".join(
                f"{signal_name}={value}" for signal_name, value in values.items()
            )
            print(
                f"payload={payload.hex()} ocurrencias={occurrences} "
                f"{valores_formateados}"
            )


if __name__ == "__main__":
    main()
