"""Analiza candidatos de marcha Toyota en los 30 segmentos RAV4 locales."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import zstandard as zstd


ROOT = Path(__file__).resolve().parents[1]
OPENPILOT_PATH = ROOT / "external" / "openpilot"
OPENDBC_PATH = ROOT / "datasets" / "openDBC" / "raw" / "opendbc"
SAMPLES_PATH = ROOT / "datasets" / "commaCarSegments" / "raw" / "TOYOTA_RAV4_TSS2"
SUMMARY_PATH = (
    ROOT
    / "datasets"
    / "commaCarSegments"
    / "summaries"
    / "TOYOTA_RAV4_TSS2"
    / "day17_gear"
)

CAN_ID_SPEED = 180
CAN_ID_GEAR_HYBRID = 295
CAN_ID_GEAR_PACKET = 956
MAX_ALIGNMENT_NS = 100_000_000

GEAR_295_LABELS = {
    0: "P",
    1: "R",
    2: "N",
    3: "D",
    4: "B",
}

GEAR_956_LABELS = {
    0: "D",
    1: "S",
    8: "N",
    16: "R",
    32: "P",
}

SPORT_GEAR_956_LABELS = {
    1: "S1",
    2: "S2",
    3: "S3",
    4: "S4",
    5: "S5",
    6: "S6",
}


def dbc_positions(start_bit: int, length: int) -> list[int]:
    """Devuelve posiciones DBC big-endian desde el bit mas significativo."""
    positions = []
    bit = start_bit
    for _ in range(length):
        positions.append(bit)
        bit = bit + 15 if bit % 8 == 0 else bit - 1
    return positions


def extract_big_endian(payload: bytes, start_bit: int, length: int) -> int:
    """Extrae un entero sin signo segun una definicion DBC big-endian."""
    value = 0
    for dbc_bit in dbc_positions(start_bit, length):
        byte_index = dbc_bit // 8
        bit_in_byte = dbc_bit % 8
        value = (value << 1) | ((payload[byte_index] >> bit_in_byte) & 1)
    return value


def describe(values: list[float]) -> dict:
    """Resume valores numericos sin conservar la serie temporal en el JSON."""
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None, "median": None}
    return {
        "count": len(values),
        "min": round(min(values), 6),
        "max": round(max(values), 6),
        "mean": round(statistics.mean(values), 6),
        "median": round(statistics.median(values), 6),
    }


def align_speed_by_gear(
    gear_states: list[tuple[int, int]], speeds: list[tuple[int, float]]
) -> tuple[dict[str, list[float]], list[float]]:
    """Alinea cada estado con la velocidad mas cercana en un recorrido ordenado."""
    speed_by_value: dict[str, list[float]] = defaultdict(list)
    gaps_ms = []
    speed_index = 0

    for gear_timestamp, gear_value in gear_states:
        while speed_index + 1 < len(speeds):
            current_gap = abs(speeds[speed_index][0] - gear_timestamp)
            next_gap = abs(speeds[speed_index + 1][0] - gear_timestamp)
            if next_gap > current_gap:
                break
            speed_index += 1

        if not speeds:
            continue
        speed_timestamp, speed_value = speeds[speed_index]
        gap_ns = abs(speed_timestamp - gear_timestamp)
        if gap_ns <= MAX_ALIGNMENT_NS:
            speed_by_value[str(gear_value)].append(speed_value)
            gaps_ms.append(gap_ns / 1_000_000)

    return speed_by_value, gaps_ms


def state_durations(states: list[tuple[int, int]]) -> Counter[str]:
    """Acumula el intervalo entre frames consecutivos para cada estado anterior."""
    durations = Counter()
    for (previous_time, previous_value), (current_time, _) in zip(states, states[1:]):
        if current_time >= previous_time:
            durations[str(previous_value)] += current_time - previous_time
    return durations


def label_counts(values: Counter[int], labels: dict[int, str]) -> tuple[dict, dict]:
    """Separa valores definidos por DBC de valores que deben permanecer abiertos."""
    defined = {labels[value]: count for value, count in sorted(values.items()) if value in labels}
    unknown = {str(value): count for value, count in sorted(values.items()) if value not in labels}
    return defined, unknown


def align_gear_states(
    reference_states: list[tuple[int, int]],
    candidate_states: list[tuple[int, int]],
) -> tuple[Counter[str], list[float]]:
    """Cuenta pares semanticos cercanos entre dos candidatas de marcha."""
    pairs = Counter()
    gaps_ms = []
    reference_index = 0

    for candidate_timestamp, candidate_value in candidate_states:
        while reference_index + 1 < len(reference_states):
            current_gap = abs(reference_states[reference_index][0] - candidate_timestamp)
            next_gap = abs(reference_states[reference_index + 1][0] - candidate_timestamp)
            if next_gap > current_gap:
                break
            reference_index += 1

        if not reference_states:
            continue
        reference_timestamp, reference_value = reference_states[reference_index]
        gap_ns = abs(reference_timestamp - candidate_timestamp)
        if gap_ns <= MAX_ALIGNMENT_NS:
            reference_label = GEAR_295_LABELS.get(reference_value, f"unknown_{reference_value}")
            candidate_label = GEAR_956_LABELS.get(candidate_value, f"unknown_{candidate_value}")
            pairs[f"956_{candidate_label}|295_{reference_label}"] += 1
            gaps_ms.append(gap_ns / 1_000_000)

    return pairs, gaps_ms


def analyze_rlog(path: Path, capnp_log) -> tuple[dict, dict]:
    """Analiza presencia y comportamiento de ID 295, ID 956 y velocidad."""
    started = time.perf_counter()
    data = zstd.ZstdDecompressor().decompress(path.read_bytes())
    gear_295: list[tuple[int, int]] = []
    speed: list[tuple[int, float]] = []
    sources_295: Counter[int] = Counter()
    gear_956: list[tuple[int, int]] = []
    sport_on_956: list[tuple[int, int]] = []
    sport_gear_on_956: list[tuple[int, int]] = []
    sport_gear_956: list[tuple[int, int]] = []
    b_gear_956: list[tuple[int, int]] = []
    drive_engaged_956: list[tuple[int, int]] = []
    sources_956: Counter[int] = Counter()

    for event in capnp_log.Event.read_multiple_bytes(data):
        if event.which() != "can":
            continue
        timestamp = event.logMonoTime
        for frame in event.can:
            payload = bytes(frame.dat)
            if frame.address == CAN_ID_GEAR_HYBRID and len(payload) >= 6:
                gear_295.append((timestamp, extract_big_endian(payload, 47, 4)))
                sources_295[frame.src] += 1
            elif frame.address == CAN_ID_SPEED and len(payload) >= 6:
                raw_speed = extract_big_endian(payload, 47, 16)
                speed.append((timestamp, raw_speed * 0.01))
            elif frame.address == CAN_ID_GEAR_PACKET:
                if len(payload) < 6:
                    continue
                gear_956.append((timestamp, extract_big_endian(payload, 13, 6)))
                sport_on_956.append((timestamp, extract_big_endian(payload, 2, 1)))
                sport_gear_on_956.append((timestamp, extract_big_endian(payload, 33, 1)))
                sport_gear_956.append((timestamp, extract_big_endian(payload, 38, 3)))
                b_gear_956.append((timestamp, extract_big_endian(payload, 41, 1)))
                drive_engaged_956.append((timestamp, extract_big_endian(payload, 47, 1)))
                sources_956[frame.src] += 1

    values = [value for _, value in gear_295]
    value_counts = Counter(values)
    transitions = Counter(
        f"{GEAR_295_LABELS.get(previous, f'unknown_{previous}')}->"
        f"{GEAR_295_LABELS.get(current, f'unknown_{current}')}"
        for (_, previous), (_, current) in zip(gear_295, gear_295[1:])
        if previous != current
    )
    speed_by_value, speed_gaps = align_speed_by_gear(gear_295, speed)

    durations_ns = state_durations(gear_295)
    values_956 = Counter(value for _, value in gear_956)
    labels_956, unknown_956 = label_counts(values_956, GEAR_956_LABELS)
    transitions_956 = Counter(
        f"{GEAR_956_LABELS.get(previous, f'unknown_{previous}')}->"
        f"{GEAR_956_LABELS.get(current, f'unknown_{current}')}"
        for (_, previous), (_, current) in zip(gear_956, gear_956[1:])
        if previous != current
    )
    speed_956_by_value, speed_956_gaps = align_speed_by_gear(gear_956, speed)
    pairs_956_295, pair_gaps_956_295 = align_gear_states(gear_295, gear_956)
    sport_gear_values = Counter(value for _, value in sport_gear_956)
    sport_gear_labels, sport_gear_unknown = label_counts(sport_gear_values, SPORT_GEAR_956_LABELS)
    sport_gear_with_mode_on = sum(
        sport_gear > 0 and sport_on == 1 and sport_gear_on == 1
        for (_, sport_on), (_, sport_gear_on), (_, sport_gear) in zip(
            sport_on_956, sport_gear_on_956, sport_gear_956
        )
    )
    sport_gear_active = sum(value > 0 for _, value in sport_gear_956)
    result = {
        "sample_name": path.parent.name,
        "processing_seconds": round(time.perf_counter() - started, 6),
        "id_295": {
            "frames": len(gear_295),
            "sources": dict(sources_295),
            "raw_value_counts": {str(value): count for value, count in sorted(value_counts.items())},
            "label_counts": {
                GEAR_295_LABELS[value]: count
                for value, count in sorted(value_counts.items())
                if value in GEAR_295_LABELS
            },
            "unknown_value_counts": {
                str(value): count
                for value, count in sorted(value_counts.items())
                if value not in GEAR_295_LABELS
            },
            "transitions": dict(transitions),
            "state_duration_ms": {
                str(value): round(duration / 1_000_000, 6)
                for value, duration in sorted(durations_ns.items(), key=lambda item: int(item[0]))
            },
            "aligned_speed_kph": {
                GEAR_295_LABELS.get(int(value), f"unknown_{value}"): describe(values)
                for value, values in sorted(speed_by_value.items(), key=lambda item: int(item[0]))
            },
            "speed_gap_ms": describe(speed_gaps),
        },
        "id_956": {
            "frames": len(gear_956),
            "sources": dict(sources_956),
            "gear_raw_value_counts": {str(value): count for value, count in sorted(values_956.items())},
            "gear_label_counts": labels_956,
            "gear_unknown_value_counts": unknown_956,
            "gear_transitions": dict(transitions_956),
            "gear_state_duration_ms": {
                str(value): round(duration / 1_000_000, 6)
                for value, duration in sorted(state_durations(gear_956).items(), key=lambda item: int(item[0]))
            },
            "gear_aligned_speed_kph": {
                GEAR_956_LABELS.get(int(value), f"unknown_{value}"): describe(values)
                for value, values in sorted(speed_956_by_value.items(), key=lambda item: int(item[0]))
            },
            "speed_gap_ms": describe(speed_956_gaps),
            "sport_on_counts": dict(Counter(value for _, value in sport_on_956)),
            "sport_gear_on_counts": dict(Counter(value for _, value in sport_gear_on_956)),
            "sport_gear_raw_value_counts": {
                str(value): count for value, count in sorted(sport_gear_values.items())
            },
            "sport_gear_label_counts": sport_gear_labels,
            "sport_gear_unknown_value_counts": sport_gear_unknown,
            "sport_gear_active_frames": sport_gear_active,
            "sport_gear_active_with_modes_on": sport_gear_with_mode_on,
            "b_gear_engaged_counts": dict(Counter(value for _, value in b_gear_956)),
            "drive_engaged_counts": dict(Counter(value for _, value in drive_engaged_956)),
            "aligned_id_295_pairs": dict(pairs_956_295),
            "id_295_pair_gap_ms": describe(pair_gaps_956_295),
        },
    }
    aggregation = {
        "values": values,
        "sources_295": sources_295,
        "values_956": values_956,
        "sources_956": sources_956,
        "transitions_956": transitions_956,
        "durations_956_ns": state_durations(gear_956),
        "speed_956_by_value": speed_956_by_value,
        "speed_956_gaps": speed_956_gaps,
        "sport_on_956": Counter(value for _, value in sport_on_956),
        "sport_gear_on_956": Counter(value for _, value in sport_gear_on_956),
        "sport_gear_956": sport_gear_values,
        "sport_gear_active": sport_gear_active,
        "sport_gear_with_mode_on": sport_gear_with_mode_on,
        "b_gear_956": Counter(value for _, value in b_gear_956),
        "drive_engaged_956": Counter(value for _, value in drive_engaged_956),
        "pairs_956_295": pairs_956_295,
        "pair_gaps_956_295": pair_gaps_956_295,
        "transitions": transitions,
        "durations_ns": durations_ns,
        "speed_by_value": speed_by_value,
        "speed_gaps": speed_gaps,
    }
    return result, aggregation


def summarize_aggregate(samples: list[dict], aggregations: list[dict]) -> dict:
    """Construye el resumen global sin persistir frames ni series individuales."""
    values: Counter[int] = Counter()
    sources_295: Counter[int] = Counter()
    sources_956: Counter[int] = Counter()
    transitions: Counter[str] = Counter()
    durations_ns: Counter[str] = Counter()
    speed_by_value: dict[str, list[float]] = defaultdict(list)
    speed_gaps: list[float] = []
    values_956: Counter[int] = Counter()
    transitions_956: Counter[str] = Counter()
    durations_956_ns: Counter[str] = Counter()
    speed_956_by_value: dict[str, list[float]] = defaultdict(list)
    speed_956_gaps: list[float] = []
    sport_on_956: Counter[int] = Counter()
    sport_gear_on_956: Counter[int] = Counter()
    sport_gear_956: Counter[int] = Counter()
    b_gear_956: Counter[int] = Counter()
    drive_engaged_956: Counter[int] = Counter()
    pairs_956_295: Counter[str] = Counter()
    pair_gaps_956_295: list[float] = []

    for aggregation in aggregations:
        values.update(aggregation["values"])
        sources_295.update(aggregation["sources_295"])
        values_956.update(aggregation["values_956"])
        sources_956.update(aggregation["sources_956"])
        transitions_956.update(aggregation["transitions_956"])
        durations_956_ns.update(aggregation["durations_956_ns"])
        for value, speeds in aggregation["speed_956_by_value"].items():
            speed_956_by_value[value].extend(speeds)
        speed_956_gaps.extend(aggregation["speed_956_gaps"])
        sport_on_956.update(aggregation["sport_on_956"])
        sport_gear_on_956.update(aggregation["sport_gear_on_956"])
        sport_gear_956.update(aggregation["sport_gear_956"])
        b_gear_956.update(aggregation["b_gear_956"])
        drive_engaged_956.update(aggregation["drive_engaged_956"])
        pairs_956_295.update(aggregation["pairs_956_295"])
        pair_gaps_956_295.extend(aggregation["pair_gaps_956_295"])
        transitions.update(aggregation["transitions"])
        durations_ns.update(aggregation["durations_ns"])
        for value, speeds in aggregation["speed_by_value"].items():
            speed_by_value[value].extend(speeds)
        speed_gaps.extend(aggregation["speed_gaps"])

    return {
        "id_295": {
            "samples_with_presence": sum(sample["id_295"]["frames"] > 0 for sample in samples),
            "frames": sum(values.values()),
            "sources": dict(sources_295),
            "raw_value_counts": {str(value): count for value, count in sorted(values.items())},
            "label_counts": {
                GEAR_295_LABELS[value]: count
                for value, count in sorted(values.items())
                if value in GEAR_295_LABELS
            },
            "unknown_value_counts": {
                str(value): count
                for value, count in sorted(values.items())
                if value not in GEAR_295_LABELS
            },
            "transitions": dict(transitions),
            "state_duration_ms": {
                value: round(duration / 1_000_000, 6)
                for value, duration in sorted(durations_ns.items(), key=lambda item: int(item[0]))
            },
            "aligned_speed_kph": {
                GEAR_295_LABELS.get(int(value), f"unknown_{value}"): describe(speeds)
                for value, speeds in sorted(speed_by_value.items(), key=lambda item: int(item[0]))
            },
            "speed_gap_ms": describe(speed_gaps),
        },
        "id_956": {
            "samples_with_presence": sum(sample["id_956"]["frames"] > 0 for sample in samples),
            "frames": sum(sample["id_956"]["frames"] for sample in samples),
            "sources": dict(sources_956),
            "gear_raw_value_counts": {str(value): count for value, count in sorted(values_956.items())},
            "gear_label_counts": label_counts(values_956, GEAR_956_LABELS)[0],
            "gear_unknown_value_counts": label_counts(values_956, GEAR_956_LABELS)[1],
            "gear_transitions": dict(transitions_956),
            "gear_state_duration_ms": {
                value: round(duration / 1_000_000, 6)
                for value, duration in sorted(durations_956_ns.items(), key=lambda item: int(item[0]))
            },
            "gear_aligned_speed_kph": {
                GEAR_956_LABELS.get(int(value), f"unknown_{value}"): describe(speeds)
                for value, speeds in sorted(speed_956_by_value.items(), key=lambda item: int(item[0]))
            },
            "speed_gap_ms": describe(speed_956_gaps),
            "sport_on_counts": dict(sport_on_956),
            "sport_gear_on_counts": dict(sport_gear_on_956),
            "sport_gear_raw_value_counts": {
                str(value): count for value, count in sorted(sport_gear_956.items())
            },
            "sport_gear_label_counts": label_counts(sport_gear_956, SPORT_GEAR_956_LABELS)[0],
            "sport_gear_unknown_value_counts": label_counts(sport_gear_956, SPORT_GEAR_956_LABELS)[1],
            "sport_gear_active_frames": sum(
                value for key, value in sport_gear_956.items() if key > 0
            ),
            "sport_gear_active_with_modes_on": sum(
                aggregation["sport_gear_with_mode_on"] for aggregation in aggregations
            ),
            "b_gear_engaged_counts": dict(b_gear_956),
            "drive_engaged_counts": dict(drive_engaged_956),
            "aligned_id_295_pairs": dict(pairs_956_295),
            "id_295_pair_gap_ms": describe(pair_gaps_956_295),
        },
    }


def main() -> None:
    """Procesa los 30 segmentos locales y escribe un resumen agregado reproducible."""
    parser = argparse.ArgumentParser(description="Analiza candidatos CAN de marcha RAV4.")
    parser.add_argument(
        "--max-alignment-ms",
        type=float,
        default=100.0,
        help="Tolerancia maxima para alinear una marcha con velocidad.",
    )
    args = parser.parse_args()
    if args.max_alignment_ms <= 0:
        raise ValueError("max-alignment-ms debe ser mayor que cero.")

    global MAX_ALIGNMENT_NS
    MAX_ALIGNMENT_NS = int(args.max_alignment_ms * 1_000_000)
    paths = sorted(SAMPLES_PATH.glob("sample_*/rlog.zst"))
    if len(paths) != 30:
        raise ValueError(f"Se esperaban 30 logs locales y se encontraron {len(paths)}.")

    sys.path.extend([str(OPENPILOT_PATH), str(OPENDBC_PATH)])
    from openpilot.cereal import log as capnp_log

    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()
    samples = []
    aggregations = []
    for path in paths:
        result, aggregation = analyze_rlog(path, capnp_log)
        samples.append(result)
        aggregations.append(aggregation)
        print(
            f"processed={result['sample_name']} id_295_frames={result['id_295']['frames']} "
            f"id_956_frames={result['id_956']['frames']} seconds={result['processing_seconds']}"
        )

    finished_at = datetime.now(timezone.utc)
    output = {
        "run": {
            "started_at_utc": started_at.isoformat(),
            "finished_at_utc": finished_at.isoformat(),
            "total_elapsed_seconds": round(time.perf_counter() - started, 6),
            "alignment_max_gap_ms": args.max_alignment_ms,
        },
        "method": {
            "id_295": "GEAR_PACKET_HYBRID.GEAR, 47|4@0+, labels P/R/N/D/B from DBC",
            "id_956": "GEAR_PACKET fields GEAR, SPORT_ON, SPORT_GEAR_ON, SPORT_GEAR, B_GEAR_ENGAGED and DRIVE_ENGAGED",
            "speed": "ID 180, SPEED 47|16@0+, scale 0.01 km/h, contextual only",
        },
        "aggregate": summarize_aggregate(samples, aggregations),
        "samples": samples,
    }
    SUMMARY_PATH.mkdir(parents=True, exist_ok=True)
    output_path = SUMMARY_PATH / "summary_30_segments.json"
    output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"summary_written={output_path}")


if __name__ == "__main__":
    main()
