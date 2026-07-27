"""Busca IDs candidatos de acelerador en las muestras RAV4 seleccionadas."""

from collections import Counter
from pathlib import Path
import sys

import zstandard as zstd


ROOT = Path(__file__).resolve().parents[1]
OPENPILOT_PATH = ROOT / "external" / "openpilot"
OPENDBC_PATH = ROOT / "datasets" / "openDBC" / "raw" / "opendbc"
SAMPLES_PATH = ROOT / "datasets" / "commaCarSegments" / "raw" / "TOYOTA_RAV4_TSS2"

# El ID 881 pertenece al DBC principal de la plataforma; 705 se contrasta como candidato alternativo.
IDS_CANDIDATOS = {
    881: "GAS_PEDAL definido en toyota_nodsu_pt",
    705: "GAS_PEDAL definido en _toyota_adas_standard",
}


def analizar_log(rlog_path: Path) -> dict[int, Counter[bytes]]:
    """Cuenta los payloads de cada ID candidato dentro de un log CAN."""
    sys.path.extend([str(OPENPILOT_PATH), str(OPENDBC_PATH)])
    from openpilot.cereal import log as capnp_log

    data = zstd.ZstdDecompressor().decompress(rlog_path.read_bytes())
    payloads_por_id = {can_id: Counter() for can_id in IDS_CANDIDATOS}

    for event in capnp_log.Event.read_multiple_bytes(data):
        if event.which() != "can":
            continue

        for message in event.can:
            if message.address in payloads_por_id:
                payloads_por_id[message.address][bytes(message.dat)] += 1

    return payloads_por_id


def main() -> None:
    """Muestra la presencia de candidatos de acelerador por cada muestra local."""
    rlogs = sorted(SAMPLES_PATH.glob("sample_*/rlog.zst"))

    if not rlogs:
        raise FileNotFoundError(f"No se encontraron muestras en: {SAMPLES_PATH}")

    for rlog_path in rlogs:
        print(f"muestra={rlog_path.parent.name}")
        payloads_por_id = analizar_log(rlog_path)

        for can_id, description in IDS_CANDIDATOS.items():
            payloads = payloads_por_id[can_id]
            print(
                f"can_id={can_id} descripcion={description} "
                f"frames={sum(payloads.values())} payloads_unicos={len(payloads)}"
            )


if __name__ == "__main__":
    main()
