"""Decodifica GAS_RELEASED y deriva gas_pressed desde el mensaje CAN 466."""

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

CAN_ID_PCM_CRUISE = 466
GAS_RELEASED_BIT = 4


def extraer_bit(payload: bytes, bit_dbc: int) -> int:
    """Extrae una senal DBC de un bit; para un bit, el orden no altera el valor."""
    byte_index = bit_dbc // 8
    bit_en_byte = bit_dbc % 8
    return (payload[byte_index] >> bit_en_byte) & 1


def cargar_payloads_pcm_cruise(rlog_path: Path) -> Counter[bytes]:
    """Recorre un log y cuenta los payloads del mensaje PCM_CRUISE."""
    sys.path.extend([str(OPENPILOT_PATH), str(OPENDBC_PATH)])
    from openpilot.cereal import log as capnp_log

    data = zstd.ZstdDecompressor().decompress(rlog_path.read_bytes())
    payloads: Counter[bytes] = Counter()

    for event in capnp_log.Event.read_multiple_bytes(data):
        if event.which() != "can":
            continue

        for message in event.can:
            if message.address == CAN_ID_PCM_CRUISE:
                payloads[bytes(message.dat)] += 1

    return payloads


def main() -> None:
    """Resume ambos estados de GAS_RELEASED y la bandera gas_pressed derivada."""
    parser = argparse.ArgumentParser(
        description="Decodifica GAS_RELEASED del mensaje CAN 466."
    )
    parser.add_argument(
        "--rlog",
        type=Path,
        default=RLOG_PATH_POR_DEFECTO,
        help="Ruta al archivo rlog.zst que se desea analizar.",
    )
    args = parser.parse_args()
    rlog_path = args.rlog.resolve()

    if not rlog_path.is_file():
        raise FileNotFoundError(f"No se encontro el log: {rlog_path}")

    payloads = cargar_payloads_pcm_cruise(rlog_path)

    if not payloads:
        print(f"rlog={rlog_path}")
        print(f"can_id={CAN_ID_PCM_CRUISE}")
        print("frames_totales=0")
        return

    frames_por_estado = Counter()
    representativos = {}

    for payload, occurrences in payloads.items():
        gas_released = extraer_bit(payload, GAS_RELEASED_BIT)
        gas_pressed = not bool(gas_released)
        frames_por_estado[gas_released] += occurrences

        if (
            gas_released not in representativos
            or occurrences > representativos[gas_released][1]
        ):
            representativos[gas_released] = (payload, occurrences, gas_pressed)

    print(f"rlog={rlog_path}")
    print(f"can_id={CAN_ID_PCM_CRUISE}")
    print("mensaje=PCM_CRUISE")
    print("senal=GAS_RELEASED")
    print("dbc=4|1@0+ (big-endian)")
    print("ubicacion=byte_0, bit_4")
    print(f"frames_totales={sum(payloads.values())}")
    print(f"payloads_unicos={len(payloads)}")

    for gas_released in sorted(frames_por_estado):
        payload, occurrences, gas_pressed = representativos[gas_released]
        print(
            f"GAS_RELEASED={gas_released} "
            f"gas_pressed={str(gas_pressed).lower()} "
            f"frames={frames_por_estado[gas_released]} "
            f"payload_representativo={payload.hex()} "
            f"ocurrencias_payload={occurrences}"
        )


if __name__ == "__main__":
    main()
