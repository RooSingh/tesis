"""Analiza el angulo de direccion candidato del ID 37 en 30 logs RAV4."""

from __future__ import annotations

import json
import math
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
    / "day17_steer_angle"
)

CAN_ID_KINEMATICS = 36
CAN_ID_STEER_ANGLE = 37
CAN_ID_SPEED = 180
MAX_ALIGNMENT_NS = 100_000_000


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


def extract_signed_big_endian(payload: bytes, start_bit: int, length: int) -> int:
    """Extrae un entero DBC big-endian con complemento a dos."""
    value = extract_big_endian(payload, start_bit, length)
    return value - (1 << length) if value & (1 << (length - 1)) else value


def describe(values: list[float]) -> dict:
    """Resume una serie numerica sin persistir sus valores individuales."""
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None, "median": None}
    return {
        "count": len(values),
        "min": round(min(values), 6),
        "max": round(max(values), 6),
        "mean": round(statistics.mean(values), 6),
        "median": round(statistics.median(values), 6),
    }


def pearson(left: list[float], right: list[float]) -> float | None:
    """Calcula Pearson solo si ambas series tienen variacion suficiente."""
    if len(left) < 2 or len(left) != len(right):
        return None
    left_mean = statistics.mean(left)
    right_mean = statistics.mean(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    left_sum = sum((a - left_mean) ** 2 for a in left)
    right_sum = sum((b - right_mean) ** 2 for b in right)
    if left_sum == 0 or right_sum == 0:
        return None
    return round(numerator / math.sqrt(left_sum * right_sum), 6)


def align_nearest(
    left: list[tuple[int, float]], right: list[tuple[int, float]]
) -> tuple[list[float], list[float], list[float]]:
    """Alinea dos series ordenadas por tiempo sin reexplorar frames ya superados."""
    aligned_left = []
    aligned_right = []
    gaps_ms = []
    right_index = 0

    for left_timestamp, left_value in left:
        while right_index + 1 < len(right):
            current_gap = abs(right[right_index][0] - left_timestamp)
            next_gap = abs(right[right_index + 1][0] - left_timestamp)
            if next_gap > current_gap:
                break
            right_index += 1

        if not right:
            continue
        right_timestamp, right_value = right[right_index]
        gap_ns = abs(right_timestamp - left_timestamp)
        if gap_ns <= MAX_ALIGNMENT_NS:
            aligned_left.append(left_value)
            aligned_right.append(right_value)
            gaps_ms.append(gap_ns / 1_000_000)

    return aligned_left, aligned_right, gaps_ms


def canonicalize(records: list[tuple[int, float, float, float, int]]) -> tuple[list[tuple[int, float, float, float]], int]:
    """Conserva una medicion por timestamp y cuenta duplicados con valores distintos."""
    grouped: dict[int, list[tuple[float, float, float]]] = defaultdict(list)
    for timestamp, angle, fraction, rate, _ in records:
        grouped[timestamp].append((angle, fraction, rate))

    canonical = []
    conflicting_duplicates = 0
    for timestamp, values in sorted(grouped.items()):
        if len(set(values)) > 1:
            conflicting_duplicates += 1
        angle, fraction, rate = values[0]
        canonical.append((timestamp, angle, fraction, rate))
    return canonical, conflicting_duplicates


def summarize_source(records: list[tuple[int, float, float, float, int]]) -> tuple[dict, list[tuple[int, float, float, float]]]:
    """Resume una fuente sin mezclarla con otros buses o canales de captura."""
    canonical, conflicting_duplicates = canonicalize(records)
    timestamps = [timestamp for timestamp, _, _, _ in canonical]
    angles = [main + fraction for _, main, fraction, _ in canonical]
    rates = [rate for _, _, _, rate in canonical]
    periodicity_ms = [
        (later - earlier) / 1_000_000 for earlier, later in zip(timestamps, timestamps[1:])
    ]
    return (
        {
            "frames": len(records),
            "unique_timestamps": len(canonical),
            "conflicting_duplicate_timestamps": conflicting_duplicates,
            "steer_angle_candidate_deg": describe(angles),
            "steer_rate_candidate_deg_per_s": describe(rates),
            "periodicity_ms": describe(periodicity_ms),
        },
        canonical,
    )


def analyze_rlog(path: Path, capnp_log) -> tuple[dict, dict]:
    """Decodifica ID 37 y conserva ID 180/36 solo como contexto temporal."""
    started = time.perf_counter()
    data = zstd.ZstdDecompressor().decompress(path.read_bytes())
    steer_records: list[tuple[int, float, float, float, int]] = []
    speeds: list[tuple[int, float]] = []
    yaw_rates: list[tuple[int, float]] = []
    sources = Counter()

    for event in capnp_log.Event.read_multiple_bytes(data):
        if event.which() != "can":
            continue
        timestamp = event.logMonoTime
        for frame in event.can:
            payload = bytes(frame.dat)
            if frame.address == CAN_ID_STEER_ANGLE and len(payload) >= 6:
                main_angle = extract_signed_big_endian(payload, 3, 12) * 1.5
                fraction = extract_signed_big_endian(payload, 39, 4) * 0.1
                rate = extract_signed_big_endian(payload, 35, 12)
                steer_records.append((timestamp, main_angle, fraction, rate, frame.src))
                sources[frame.src] += 1
            elif frame.address == CAN_ID_SPEED and len(payload) >= 6:
                speeds.append((timestamp, extract_big_endian(payload, 47, 16) * 0.01))
            elif frame.address == CAN_ID_KINEMATICS and len(payload) >= 2:
                yaw_rates.append((timestamp, extract_big_endian(payload, 1, 10) * 0.244 - 125))

    records_by_source: dict[int, list[tuple[int, float, float, float, int]]] = defaultdict(list)
    for record in steer_records:
        records_by_source[record[4]].append(record)
    source_results = {}
    canonical_by_source = {}
    for source, records in records_by_source.items():
        source_results[str(source)], canonical_by_source[source] = summarize_source(records)

    # src 0 representa la recepcion normal del bus logico Panda 0. Los valores
    # returned (>=128) se conservan como trazabilidad, no como mediciones extra.
    canonical = canonical_by_source.get(0, [])
    conflicting_duplicates = source_results.get("0", {}).get("conflicting_duplicate_timestamps", 0)

    source_comparison = {
        "shared_timestamps": 0,
        "exact_angle_matches": 0,
        "different_angle_values": 0,
        "angle_absolute_difference_deg": describe([]),
        "rate_absolute_difference_deg_per_s": describe([]),
    }
    if 0 in canonical_by_source and 130 in canonical_by_source:
        source_zero = {timestamp: (main + fraction, rate) for timestamp, main, fraction, rate in canonical_by_source[0]}
        source_130 = {timestamp: (main + fraction, rate) for timestamp, main, fraction, rate in canonical_by_source[130]}
        shared_timestamps = sorted(source_zero.keys() & source_130.keys())
        angle_differences = [abs(source_zero[timestamp][0] - source_130[timestamp][0]) for timestamp in shared_timestamps]
        rate_differences = [abs(source_zero[timestamp][1] - source_130[timestamp][1]) for timestamp in shared_timestamps]
        source_comparison = {
            "shared_timestamps": len(shared_timestamps),
            "exact_angle_matches": sum(difference == 0 for difference in angle_differences),
            "different_angle_values": sum(difference != 0 for difference in angle_differences),
            "angle_absolute_difference_deg": describe(angle_differences),
            "rate_absolute_difference_deg_per_s": describe(rate_differences),
        }
    timestamps = [timestamp for timestamp, _, _, _ in canonical]
    angles = [angle + fraction for _, angle, fraction, _ in canonical]
    main_angles = [angle for _, angle, _, _ in canonical]
    fractions = [fraction for _, _, fraction, _ in canonical]
    rates = [rate for _, _, _, rate in canonical]
    angle_series = [(timestamp, angle) for timestamp, angle in zip(timestamps, angles)]
    rate_series = [(timestamp, rate) for timestamp, rate in zip(timestamps, rates)]
    angle_deltas = [later - earlier for earlier, later in zip(angles, angles[1:])]
    periodicity_ms = [
        (later - earlier) / 1_000_000 for earlier, later in zip(timestamps, timestamps[1:])
    ]
    angle_speed, speed_values, speed_gaps = align_nearest(angle_series, speeds)
    rate_yaw, yaw_values, yaw_gaps = align_nearest(rate_series, yaw_rates)

    sign_counts = Counter(
        "negative" if angle < 0 else "positive" if angle > 0 else "zero" for angle in angles
    )
    result = {
        "sample_name": path.parent.name,
        "processing_seconds": round(time.perf_counter() - started, 6),
        "id_37": {
            "primary_source": 0,
            "frames": len(records_by_source.get(0, [])),
            "frames_all_sources": len(steer_records),
            "unique_timestamps": len(canonical),
            "sources": dict(sources),
            "by_source": source_results,
            "src_0_vs_130": source_comparison,
            "conflicting_duplicate_timestamps": conflicting_duplicates,
            "steer_angle_main_deg": describe(main_angles),
            "steer_fraction_deg": describe(fractions),
            "steer_angle_candidate_deg": describe(angles),
            "steer_angle_sign_counts": dict(sign_counts),
            "steer_rate_candidate_deg_per_s": describe(rates),
            "angle_change_between_unique_samples_deg": describe(angle_deltas),
            "periodicity_ms": describe(periodicity_ms),
            "aligned_speed_kph": {
                "pairs": len(angle_speed),
                "angle_speed_pearson": pearson(angle_speed, speed_values),
                "speed_gap_ms": describe(speed_gaps),
            },
            "aligned_yaw_rate_deg_per_s": {
                "pairs": len(rate_yaw),
                "steer_rate_yaw_rate_pearson": pearson(rate_yaw, yaw_values),
                "alignment_gap_ms": describe(yaw_gaps),
            },
        },
    }
    aggregation = {
        "frames": len(records_by_source.get(0, [])),
        "frames_all_sources": len(steer_records),
        "timestamps": len(canonical),
        "sources": sources,
        "by_source": {
            str(source): {
                "frames": len(records),
                "canonical": canonical_by_source[source],
            }
            for source, records in records_by_source.items()
        },
        "source_comparison": source_comparison,
        "source_angle_differences": angle_differences if 0 in canonical_by_source and 130 in canonical_by_source else [],
        "source_rate_differences": rate_differences if 0 in canonical_by_source and 130 in canonical_by_source else [],
        "conflicting_duplicates": conflicting_duplicates,
        "main_angles": main_angles,
        "fractions": fractions,
        "angles": angles,
        "rates": rates,
        "angle_deltas": angle_deltas,
        "periodicity_ms": periodicity_ms,
        "angle_speed": angle_speed,
        "speeds": speed_values,
        "speed_gaps": speed_gaps,
        "rate_yaw": rate_yaw,
        "yaw_values": yaw_values,
        "yaw_gaps": yaw_gaps,
    }
    return result, aggregation


def summarize_aggregate(samples: list[dict], aggregations: list[dict]) -> dict:
    """Resume la muestra sin persistir series temporales individuales."""
    sources = Counter()
    main_angles = []
    fractions = []
    angles = []
    rates = []
    angle_deltas = []
    periodicity_ms = []
    angle_speed = []
    speeds = []
    speed_gaps = []
    rate_yaw = []
    yaw_values = []
    yaw_gaps = []
    by_source: dict[str, dict] = defaultdict(lambda: {"frames": 0, "angles": [], "rates": [], "periodicity_ms": []})
    shared_timestamps = 0
    exact_angle_matches = 0
    different_angle_values = 0
    source_angle_differences = []
    source_rate_differences = []

    for aggregation in aggregations:
        sources.update(aggregation["sources"])
        for source, detail in aggregation["by_source"].items():
            canonical = detail["canonical"]
            timestamps = [timestamp for timestamp, _, _, _ in canonical]
            by_source[source]["frames"] += detail["frames"]
            by_source[source]["angles"].extend(main + fraction for _, main, fraction, _ in canonical)
            by_source[source]["rates"].extend(rate for _, _, _, rate in canonical)
            by_source[source]["periodicity_ms"].extend(
                (later - earlier) / 1_000_000 for earlier, later in zip(timestamps, timestamps[1:])
            )
        comparison = aggregation["source_comparison"]
        shared_timestamps += comparison["shared_timestamps"]
        exact_angle_matches += comparison["exact_angle_matches"]
        different_angle_values += comparison["different_angle_values"]
        source_angle_differences.extend(aggregation["source_angle_differences"])
        source_rate_differences.extend(aggregation["source_rate_differences"])
        main_angles.extend(aggregation["main_angles"])
        fractions.extend(aggregation["fractions"])
        angles.extend(aggregation["angles"])
        rates.extend(aggregation["rates"])
        angle_deltas.extend(aggregation["angle_deltas"])
        periodicity_ms.extend(aggregation["periodicity_ms"])
        angle_speed.extend(aggregation["angle_speed"])
        speeds.extend(aggregation["speeds"])
        speed_gaps.extend(aggregation["speed_gaps"])
        rate_yaw.extend(aggregation["rate_yaw"])
        yaw_values.extend(aggregation["yaw_values"])
        yaw_gaps.extend(aggregation["yaw_gaps"])

    sign_counts = Counter(
        "negative" if angle < 0 else "positive" if angle > 0 else "zero" for angle in angles
    )
    return {
        "id_37": {
            "samples_with_presence": sum(sample["id_37"]["frames"] > 0 for sample in samples),
            "primary_source": 0,
            "frames": sum(aggregation["frames"] for aggregation in aggregations),
            "frames_all_sources": sum(aggregation["frames_all_sources"] for aggregation in aggregations),
            "unique_timestamps": sum(aggregation["timestamps"] for aggregation in aggregations),
            "sources": dict(sources),
            "by_source": {
                source: {
                    "frames": detail["frames"],
                    "steer_angle_candidate_deg": describe(detail["angles"]),
                    "steer_rate_candidate_deg_per_s": describe(detail["rates"]),
                    "periodicity_ms": describe(detail["periodicity_ms"]),
                }
                for source, detail in sorted(by_source.items(), key=lambda item: int(item[0]))
            },
            "src_0_vs_130": {
                "shared_timestamps": shared_timestamps,
                "exact_angle_matches": exact_angle_matches,
                "different_angle_values": different_angle_values,
                "angle_absolute_difference_deg": describe(source_angle_differences),
                "rate_absolute_difference_deg_per_s": describe(source_rate_differences),
            },
            "conflicting_duplicate_timestamps": sum(
                aggregation["conflicting_duplicates"] for aggregation in aggregations
            ),
            "steer_angle_main_deg": describe(main_angles),
            "steer_fraction_deg": describe(fractions),
            "steer_angle_candidate_deg": describe(angles),
            "steer_angle_sign_counts": dict(sign_counts),
            "steer_rate_candidate_deg_per_s": describe(rates),
            "angle_change_between_unique_samples_deg": describe(angle_deltas),
            "periodicity_ms": describe(periodicity_ms),
            "aligned_speed_kph": {
                "pairs": len(angle_speed),
                "angle_speed_pearson": pearson(angle_speed, speeds),
                "speed_gap_ms": describe(speed_gaps),
            },
            "aligned_yaw_rate_deg_per_s": {
                "pairs": len(rate_yaw),
                "steer_rate_yaw_rate_pearson": pearson(rate_yaw, yaw_values),
                "alignment_gap_ms": describe(yaw_gaps),
            },
        }
    }


def main() -> None:
    """Procesa los 30 logs locales y escribe el resumen reproducible de direccion."""
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
            f"processed={result['sample_name']} id_37_frames={result['id_37']['frames']} "
            f"unique_timestamps={result['id_37']['unique_timestamps']} "
            f"seconds={result['processing_seconds']}"
        )

    finished_at = datetime.now(timezone.utc)
    output = {
        "run": {
            "started_at_utc": started_at.isoformat(),
            "finished_at_utc": finished_at.isoformat(),
            "total_elapsed_seconds": round(time.perf_counter() - started, 6),
            "alignment_max_gap_ms": MAX_ALIGNMENT_NS / 1_000_000,
        },
        "method": {
            "steer_angle": "ID 37: STEER_ANGLE 3|12@0- scale 1.5 plus STEER_FRACTION 39|4@0- scale 0.1",
            "steer_rate": "ID 37: STEER_RATE 35|12@0- scale 1 deg/s",
            "speed_context": "ID 180 SPEED, 47|16@0+, scale 0.01 km/h",
            "yaw_context": "ID 36 YAW_RATE, 1|10@0+, scale 0.244 and offset -125 deg/s",
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
