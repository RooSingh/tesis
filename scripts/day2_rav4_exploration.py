"""Resume una muestra RAV4 de commaCarSegments para el analisis CAN inicial.

Lee un rlog.zst, cuenta eventos y mensajes CAN, calcula periodicidad y
variabilidad de IDs frecuentes, y escribe summary.json fuera del control de
versiones. Es un analizador offline; no participa del generador ni del pipeline
MQTT en ejecucion.
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

import zstandard as zstd

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "external" / "openpilot"))
sys.path.append(str(ROOT / "datasets" / "openDBC" / "raw" / "opendbc"))

from openpilot.cereal import log as capnp_log  # noqa: E402


def to_ms(ns: int | float) -> float:
    # Convierte nanosegundos a milisegundos para facilitar lectura humana.
    return float(ns) / 1_000_000.0


def main() -> None:
    # Muestra inicial seleccionada para la plataforma TOYOTA_RAV4_TSS2.
    sample = ROOT / "datasets" / "commaCarSegments" / "raw" / "TOYOTA_RAV4_TSS2" / "sample_01" / "rlog.zst"
    # Carpeta donde se guardan artefactos resumidos y reutilizables de esta exploracion.
    out_dir = ROOT / "datasets" / "commaCarSegments" / "summaries" / "TOYOTA_RAV4_TSS2" / "sample_01"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Se lee el archivo comprimido y se descomprime con Zstandard.
    compressed = sample.read_bytes()
    decompressed = zstd.ZstdDecompressor().decompress(compressed)

    # Contadores y estructuras acumuladoras para el resumen exploratorio.
    event_counter: Counter[str] = Counter()
    address_counter: Counter[int] = Counter()
    payload_len_counter: Counter[int] = Counter()
    src_counter: Counter[int] = Counter()
    # Para cada ID CAN guardamos los tiempos de evento donde aparece.
    event_times_by_address: dict[int, list[int]] = defaultdict(list)
    # Para cada ID CAN guardamos cuántas veces aparece cada payload observado.
    payloads_by_address: dict[int, Counter[str]] = defaultdict(Counter)

    total_can_messages = 0
    first_car_params_repr = None

    # Se recorren todos los eventos cereal del log descomprimido.
    for evt in capnp_log.Event.read_multiple_bytes(decompressed):
        evt_type = evt.which()
        event_counter[evt_type] += 1

        # Se conserva la representación del primer evento carParams para referencia contextual.
        if evt_type == "carParams" and first_car_params_repr is None:
            first_car_params_repr = str(evt)

        # Solo los eventos de tipo CAN se usan para el resumen estructural del bus.
        if evt_type != "can":
            continue

        # Un mismo evento CAN puede agrupar múltiples mensajes CAN.
        # seen_in_event evita contar varias veces el mismo address para la serie temporal del evento.
        seen_in_event: set[int] = set()
        for msg in evt.can:
            total_can_messages += 1
            address_counter[msg.address] += 1
            payload_len_counter[len(msg.dat)] += 1
            src_counter[msg.src] += 1
            # Se guarda el payload como hexadecimal para poder medir variabilidad observada.
            payloads_by_address[msg.address][bytes(msg.dat).hex()] += 1
            seen_in_event.add(msg.address)

        # Para análisis temporal, asociamos el tiempo del evento a cada address presente.
        for addr in seen_in_event:
            event_times_by_address[addr].append(evt.logMonoTime)

    # Se calcula un resumen temporal y de variabilidad para los 25 IDs más frecuentes.
    periodicity = []
    for addr, count in address_counter.most_common(25):
        ts = event_times_by_address.get(addr, [])
        diffs = [b - a for a, b in zip(ts, ts[1:])]
        periodicity.append(
            {
                "address": addr,
                "occurrences_in_messages": count,
                "occurrences_in_events": len(ts),
                "unique_payloads": len(payloads_by_address[addr]),
                "mean_delta_ms": round(to_ms(statistics.mean(diffs)), 6) if diffs else None,
                "median_delta_ms": round(to_ms(statistics.median(diffs)), 6) if diffs else None,
                "min_delta_ms": round(to_ms(min(diffs)), 6) if diffs else None,
                "max_delta_ms": round(to_ms(max(diffs)), 6) if diffs else None,
                "top_payloads": payloads_by_address[addr].most_common(5),
            }
        )

    # Resumen completo exportable a JSON para reuso posterior.
    summary = {
        "sample_file": str(sample.relative_to(ROOT)),
        "compressed_bytes": len(compressed),
        "decompressed_bytes": len(decompressed),
        "event_counts": dict(event_counter),
        "total_can_messages": total_can_messages,
        "unique_addresses": len(address_counter),
        "top_addresses": address_counter.most_common(25),
        "payload_lengths": sorted(payload_len_counter.items()),
        "sources": src_counter.most_common(),
        "first_car_params_repr": first_car_params_repr,
        "periodicity_top25": periodicity,
    }

    # Se guarda el resultado en disco para no repetir toda la exploración cada vez.
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    # Se imprime un resumen corto en consola para validación rápida.
    print(f"summary_written={out_dir / 'summary.json'}")
    print(f"total_events={sum(event_counter.values())}")
    print(f"event_counts={dict(event_counter)}")
    print(f"total_can_messages={total_can_messages}")
    print(f"unique_addresses={len(address_counter)}")


if __name__ == "__main__":
    main()
