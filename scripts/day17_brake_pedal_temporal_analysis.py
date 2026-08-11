"""Analiza temporalmente freno y candidatos de pedal en 30 segmentos RAV4."""

from __future__ import annotations

import json
import math
import statistics
import sys
import time
from collections import Counter
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
    / "day17_brake_pedal_temporal"
)

CAN_ID_SPEED = 180
CAN_ID_PCM_CRUISE = 466
CAN_ID_BRAKE_MODULE = 550
CAN_ID_GAS_PEDAL_ALTERNATIVE = 705
CAN_ID_GAS_PEDAL_PRIMARY = 881
MAX_ALIGNMENT_NS = 100_000_000


def dbc_positions(start_bit: int, length: int) -> list[int]:
    """Devuelve posiciones DBC big-endian de MSB a LSB."""
    positions = []
    bit = start_bit
    for _ in range(length):
        positions.append(bit)
        bit = bit + 15 if bit % 8 == 0 else bit - 1
    return positions


def extract_big_endian(payload: bytes, start_bit: int, length: int) -> int:
    """Extrae un entero sin signo de acuerdo con una definicion DBC big-endian."""
    value = 0
    for dbc_bit in dbc_positions(start_bit, length):
        byte_index = dbc_bit // 8
        bit_in_byte = dbc_bit % 8
        value = (value << 1) | ((payload[byte_index] >> bit_in_byte) & 1)
    return value


def describe(values: list[float]) -> dict:
    """Resume una serie numerica sin retener sus valores individuales."""
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None, "median": None}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": round(statistics.mean(values), 6),
        "median": round(statistics.median(values), 6),
    }


def pearson(xs: list[float], ys: list[float]) -> float | None:
    """Calcula Pearson solo cuando ambas series tienen varianza."""
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    mean_x = statistics.mean(xs)
    mean_y = statistics.mean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denominator_x = sum((x - mean_x) ** 2 for x in xs)
    denominator_y = sum((y - mean_y) ** 2 for y in ys)
    if not denominator_x or not denominator_y:
        return None
    return round(numerator / math.sqrt(denominator_x * denominator_y), 6)


def nearest_pairs(
    values: list[tuple[int, float]], references: list[tuple[int, float]]
) -> tuple[list[float], list[float], list[float]]:
    """Alinea cada valor con la referencia temporal mas cercana hasta 100 ms."""
    if not values or not references:
        return [], [], []
    index = 0
    paired_values = []
    paired_references = []
    gaps_ms = []
    for timestamp, value in values:
        while index + 1 < len(references) and references[index + 1][0] <= timestamp:
            index += 1
        candidates = [references[index]]
        if index + 1 < len(references):
            candidates.append(references[index + 1])
        reference_timestamp, reference_value = min(
            candidates, key=lambda candidate: abs(candidate[0] - timestamp)
        )
        gap_ns = abs(reference_timestamp - timestamp)
        if gap_ns <= MAX_ALIGNMENT_NS:
            paired_values.append(value)
            paired_references.append(reference_value)
            gaps_ms.append(gap_ns / 1_000_000)
    return paired_values, paired_references, gaps_ms


def analyze_sample(sample_name: str, capnp_log) -> dict:
    """Extrae series dirigidas de un log y calcula relaciones dentro de la muestra."""
    path = SAMPLES_PATH / sample_name / "rlog.zst"
    started = time.perf_counter()
    data = zstd.ZstdDecompressor().decompress(path.read_bytes())
    brake_pressure = []
    brake_position = []
    brake_state = []
    gas_pressed = []
    gas_881 = []
    gas_705 = []
    speed = []

    for event in capnp_log.Event.read_multiple_bytes(data):
        if event.which() != "can":
            continue
        timestamp = event.logMonoTime
        for frame in event.can:
            payload = bytes(frame.dat)
            if frame.address == CAN_ID_BRAKE_MODULE and len(payload) >= 5:
                pressure = extract_big_endian(payload, 0, 9)
                position = extract_big_endian(payload, 16, 9)
                pressed = (payload[4] >> 5) & 1
                brake_pressure.append((timestamp, float(pressure)))
                brake_position.append((timestamp, float(position)))
                brake_state.append((timestamp, float(pressed)))
            elif frame.address == CAN_ID_PCM_CRUISE and payload:
                released = (payload[0] >> 4) & 1
                gas_pressed.append((timestamp, float(not bool(released))))
            elif frame.address == CAN_ID_GAS_PEDAL_PRIMARY and len(payload) >= 2:
                gas_881.append((timestamp, float(extract_big_endian(payload, 15, 8))))
            elif frame.address == CAN_ID_GAS_PEDAL_ALTERNATIVE and len(payload) >= 7:
                gas_705.append((timestamp, float(extract_big_endian(payload, 55, 8))))
            elif frame.address == CAN_ID_SPEED and len(payload) >= 6:
                raw_speed = extract_big_endian(payload, 47, 16)
                speed.append((timestamp, raw_speed * 0.01))

    pressure_values = [value for _, value in brake_pressure]
    position_values = [value for _, value in brake_position]
    state_values = [value for _, value in brake_state]
    pressure_by_state = {
        str(state): describe(
            [pressure for pressure, pressed in zip(pressure_values, state_values) if pressed == state]
        )
        for state in (0.0, 1.0)
    }
    position_by_state = {
        str(state): describe(
            [position for position, pressed in zip(position_values, state_values) if pressed == state]
        )
        for state in (0.0, 1.0)
    }
    transitions = sum(
        current != previous for previous, current in zip(state_values, state_values[1:])
    )

    candidate_results = {}
    aggregation = {
        "brake_pressure": pressure_values,
        "brake_position": position_values,
        "brake_state": state_values,
        "brake_transitions": transitions,
        "candidates": {},
    }
    for can_id, values in ((CAN_ID_GAS_PEDAL_PRIMARY, gas_881), (CAN_ID_GAS_PEDAL_ALTERNATIVE, gas_705)):
        candidate_values, paired_pressed, pressed_gaps = nearest_pairs(values, gas_pressed)
        speed_values, paired_speed, speed_gaps = nearest_pairs(values, speed)
        candidate_results[str(can_id)] = {
            "raw": describe([value for _, value in values]),
            "aligned_gas_pressed": {
                "pairs": len(candidate_values),
                "pearson": pearson(candidate_values, paired_pressed),
                "by_gas_pressed": {
                    str(state): describe(
                        [
                            value
                            for value, pressed in zip(candidate_values, paired_pressed)
                            if pressed == state
                        ]
                    )
                    for state in (0.0, 1.0)
                },
                "gap_ms": describe(pressed_gaps),
            },
            "aligned_speed_kph": {
                "pairs": len(speed_values),
                "pearson": pearson(speed_values, paired_speed),
                "gap_ms": describe(speed_gaps),
            },
        }
        aggregation["candidates"][str(can_id)] = {
            "raw": [value for _, value in values],
            "gas_values": candidate_values,
            "gas_pressed": paired_pressed,
            "gas_gaps": pressed_gaps,
            "speed_values": speed_values,
            "speed": paired_speed,
            "speed_gaps": speed_gaps,
        }

    return {
        "sample_name": sample_name,
        "processing_seconds": round(time.perf_counter() - started, 6),
        "brake": {
            "pressure_raw": describe(pressure_values),
            "position_raw": describe(position_values),
            "pressed_states": dict(Counter(int(value) for value in state_values)),
            "state_transitions": transitions,
            "pressure_by_pressed": pressure_by_state,
            "position_by_pressed": position_by_state,
            "pressure_position_pearson": pearson(pressure_values, position_values),
        },
        "gas_pedal_candidates": candidate_results,
        "_aggregation": aggregation,
    }


def summarize_aggregate(aggregation: dict) -> dict:
    """Resume toda la muestra sin persistir las series temporales individuales."""
    pressure = aggregation["brake_pressure"]
    position = aggregation["brake_position"]
    states = aggregation["brake_state"]
    brake = {
        "pressure_raw": describe(pressure),
        "position_raw": describe(position),
        "pressed_states": dict(Counter(int(value) for value in states)),
        "state_transitions": aggregation["brake_transitions"],
        "pressure_by_pressed": {
            str(state): describe(
                [value for value, pressed in zip(pressure, states) if pressed == state]
            )
            for state in (0.0, 1.0)
        },
        "position_by_pressed": {
            str(state): describe(
                [value for value, pressed in zip(position, states) if pressed == state]
            )
            for state in (0.0, 1.0)
        },
        "pressure_position_pearson": pearson(pressure, position),
    }
    candidates = {}
    for can_id, values in aggregation["candidates"].items():
        candidates[can_id] = {
            "raw": describe(values["raw"]),
            "aligned_gas_pressed": {
                "pairs": len(values["gas_values"]),
                "pearson": pearson(values["gas_values"], values["gas_pressed"]),
                "by_gas_pressed": {
                    str(state): describe(
                        [
                            value
                            for value, pressed in zip(values["gas_values"], values["gas_pressed"])
                            if pressed == state
                        ]
                    )
                    for state in (0.0, 1.0)
                },
                "gap_ms": describe(values["gas_gaps"]),
            },
            "aligned_speed_kph": {
                "pairs": len(values["speed_values"]),
                "pearson": pearson(values["speed_values"], values["speed"]),
                "gap_ms": describe(values["speed_gaps"]),
            },
        }
    return {"brake": brake, "gas_pedal_candidates": candidates}


def main() -> None:
    """Procesa los 30 segmentos existentes y guarda una tercera pasada temporal."""
    sys.path.extend([str(OPENPILOT_PATH), str(OPENDBC_PATH)])
    from openpilot.cereal import log as capnp_log

    sample_names = [f"sample_{number:02d}" for number in range(1, 31)]
    missing = [name for name in sample_names if not (SAMPLES_PATH / name / "rlog.zst").is_file()]
    if missing:
        raise FileNotFoundError(f"Faltan muestras requeridas: {', '.join(missing)}")

    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()
    results = []
    aggregation = {
        "brake_pressure": [],
        "brake_position": [],
        "brake_state": [],
        "brake_transitions": 0,
        "candidates": {
            str(CAN_ID_GAS_PEDAL_PRIMARY): {
                "raw": [], "gas_values": [], "gas_pressed": [], "gas_gaps": [],
                "speed_values": [], "speed": [], "speed_gaps": [],
            },
            str(CAN_ID_GAS_PEDAL_ALTERNATIVE): {
                "raw": [], "gas_values": [], "gas_pressed": [], "gas_gaps": [],
                "speed_values": [], "speed": [], "speed_gaps": [],
            },
        },
    }
    for sample_name in sample_names:
        result = analyze_sample(sample_name, capnp_log)
        detail = result.pop("_aggregation")
        aggregation["brake_pressure"].extend(detail["brake_pressure"])
        aggregation["brake_position"].extend(detail["brake_position"])
        aggregation["brake_state"].extend(detail["brake_state"])
        aggregation["brake_transitions"] += detail["brake_transitions"]
        for can_id, candidate in detail["candidates"].items():
            for key, values in candidate.items():
                aggregation["candidates"][can_id][key].extend(values)
        results.append(result)
        print(f"processed={sample_name} seconds={result['processing_seconds']}")

    finished_at = datetime.now(timezone.utc)
    output = {
        "run": {
            "started_at_utc": started_at.isoformat(),
            "finished_at_utc": finished_at.isoformat(),
            "total_elapsed_seconds": round(time.perf_counter() - started, 6),
            "alignment_max_gap_ms": MAX_ALIGNMENT_NS / 1_000_000,
        },
        "method": {
            "brake_pressure": "ID 550, 0|9@0+, raw without physical unit",
            "brake_position": "ID 550, 16|9@0+, raw without physical unit",
            "brake_pressed": "ID 550, bit 37",
            "gas_pressed": "ID 466, inverse of GAS_RELEASED bit 4",
            "gas_881": "ID 881, 15|8@0+, raw",
            "gas_705": "ID 705, 55|8@0+, raw; DBC candidate scale 0.5 percent",
            "speed": "ID 180, 47|16@0+, scale 0.01 km/h; contextual only",
        },
        "aggregate": summarize_aggregate(aggregation),
        "samples": results,
    }
    SUMMARY_PATH.mkdir(parents=True, exist_ok=True)
    output_path = SUMMARY_PATH / "summary_30_segments.json"
    output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"summary_written={output_path}")


if __name__ == "__main__":
    main()
