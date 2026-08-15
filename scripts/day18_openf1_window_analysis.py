"""Propone ventanas de 60 segundos para replay usando telemetria y contexto local."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW_PATH = ROOT / "datasets" / "OpenF1" / "raw" / "2025" / "9947"
DRIVERS = {1: "VER", 4: "NOR", 81: "PIA"}
WINDOW_SECONDS = 60


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def floor_minute(value: datetime) -> datetime:
    return value.replace(second=0, microsecond=0)


def values_summary(rows: list[dict]) -> dict:
    speeds = [row["speed"] for row in rows]
    throttles = [row["throttle"] for row in rows]
    return {
        "samples": len(rows),
        "speed_min_kph": min(speeds),
        "speed_max_kph": max(speeds),
        "speed_range_kph": max(speeds) - min(speeds),
        "throttle_range_percent": max(throttles) - min(throttles),
        "brake_samples": sum(bool(row["brake"]) for row in rows),
        "moving_samples": sum(row["speed"] > 50 for row in rows),
    }


def main() -> None:
    samples_by_driver: dict[int, list[dict]] = {}
    minute_rows: dict[datetime, dict[int, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for driver_number, acronym in DRIVERS.items():
        rows = json.loads((RAW_PATH / f"car_data_driver_{driver_number}_{acronym}.json").read_text(encoding="utf-8"))
        samples_by_driver[driver_number] = rows
        for row in rows:
            minute_rows[floor_minute(parse_time(row["date"]))][driver_number].append(row)

    weather = json.loads((RAW_PATH / "weather.json").read_text(encoding="utf-8"))
    race_control = json.loads((RAW_PATH / "race_control.json").read_text(encoding="utf-8"))
    candidates = []
    for start, rows_by_driver in sorted(minute_rows.items()):
        if set(rows_by_driver) != set(DRIVERS):
            continue
        metrics = {driver: values_summary(rows_by_driver[driver]) for driver in DRIVERS}
        if min(metric["samples"] for metric in metrics.values()) < 100:
            continue
        moving = min(metric["moving_samples"] / metric["samples"] for metric in metrics.values())
        speed_range = min(metric["speed_range_kph"] for metric in metrics.values())
        throttle_range = min(metric["throttle_range_percent"] for metric in metrics.values())
        brakes = sum(metric["brake_samples"] for metric in metrics.values())
        window_end = start + timedelta(seconds=WINDOW_SECONDS)
        weather_rows = [row for row in weather if start <= parse_time(row["date"]) < window_end]
        events = [row for row in race_control if start <= parse_time(row["date"]) < window_end]
        candidate = {
            "start_utc": start.isoformat(),
            "end_utc": window_end.isoformat(),
            "all_driver_moving_fraction_min": round(moving, 3),
            "minimum_driver_speed_range_kph": speed_range,
            "minimum_driver_throttle_range_percent": throttle_range,
            "total_brake_samples": brakes,
            "rainfall_observed": any(row["rainfall"] for row in weather_rows),
            "track_temperature_c": [row["track_temperature"] for row in weather_rows],
            "race_control_messages": [row["message"] for row in events],
            "by_driver": {acronym: metrics[number] for number, acronym in DRIVERS.items()},
        }
        candidate["technical_score"] = round(moving * 100 + speed_range + throttle_range + brakes / 10, 3)
        candidates.append(candidate)

    ranked = sorted(candidates, key=lambda item: item["technical_score"], reverse=True)
    selected = {
        "method": {
            "window_seconds": WINDOW_SECONDS,
            "requires": "all three drivers, at least 100 car_data samples each, moving fraction, speed/throttle variation and brake activity",
            "source_limit": "Candidates use local OpenF1 processed data; race-control messages are context, not independent FIA timing validation.",
        },
        "top_technical": ranked[:10],
        "rain_candidates": [item for item in ranked if item["rainfall_observed"]][:10],
        "safety_car_or_vsc_candidates": [item for item in ranked if any("SAFETY CAR" in message or "VIRTUAL SAFETY CAR" in message for message in item["race_control_messages"])][:10],
    }
    output = ROOT / "datasets" / "OpenF1" / "summaries" / "day18_window_candidates.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(selected, indent=2), encoding="utf-8")
    for group in ("top_technical", "rain_candidates", "safety_car_or_vsc_candidates"):
        print(f"{group}={len(selected[group])}")
        for item in selected[group][:3]:
            print(json.dumps({key: item[key] for key in ("start_utc", "technical_score", "rainfall_observed", "race_control_messages", "minimum_driver_speed_range_kph", "minimum_driver_throttle_range_percent", "total_brake_samples")}, ensure_ascii=True))
        print()


if __name__ == "__main__":
    main()
