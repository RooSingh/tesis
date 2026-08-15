"""Reproduce datos OpenF1 locales por MQTT con filtros explícitos y modo seco seguro."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.openf1 import messages_from_openf1_sample
from backend.config import MQTT_HOST, MQTT_PORT, MQTT_REPLAY_TOPIC


DATA_ROOT = ROOT / "datasets" / "OpenF1" / "raw" / "2025"
SUPPORTED_ENDPOINTS = {"car_data", "location"}


def parse_time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def parse_drivers(value: str, session_path: Path) -> list[tuple[int, str]]:
    drivers = json.loads((session_path / "drivers.json").read_text(encoding="utf-8"))
    acronyms = {row["driver_number"]: row["name_acronym"] for row in drivers}
    selected = sorted(acronyms) if value == "all" else sorted({int(item) for item in value.split(",")})
    unknown = [number for number in selected if number not in acronyms]
    if unknown:
        raise ValueError(f"Pilotos no disponibles en la sesion: {unknown}")
    return [(number, acronyms[number]) for number in selected]


def collect_samples(
    session_path: Path,
    drivers: list[tuple[int, str]],
    endpoints: list[str],
    start: datetime | None,
    end: datetime | None,
) -> list[tuple[dict, str, str, str]]:
    """Filtra archivos crudos por reloj deportivo, sin alterar las muestras."""
    selected = []
    for driver_number, acronym in drivers:
        for endpoint in endpoints:
            path = session_path / f"{endpoint}_driver_{driver_number}_{acronym}.json"
            if not path.is_file():
                raise FileNotFoundError(f"No existe telemetria {endpoint} para piloto {driver_number}: {path}")
            rows = json.loads(path.read_text(encoding="utf-8"))
            for row in rows:
                timestamp = parse_time(row["date"])
                if (start is None or timestamp >= start) and (end is None or timestamp < end):
                    source_url = f"https://api.openf1.org/v1/{endpoint}?session_key={row['session_key']}&driver_number={driver_number}"
                    selected.append((row, endpoint, source_url, str(path)))
    return sorted(selected, key=lambda item: item[0]["date"])


def build_messages(samples: list[tuple[dict, str, str, str]]) -> list[dict]:
    messages = []
    for row, endpoint, source_url, path in samples:
        messages.extend(messages_from_openf1_sample(row, endpoint, source_url, path, datetime.now(timezone.utc).isoformat()))
    return messages


def publish(messages: list[dict], speed: float, max_delay: float) -> None:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.loop_start()
    previous = None
    try:
        for message in messages:
            current = parse_time(message["timestamp"])
            if previous is not None:
                time.sleep(min((current - previous).total_seconds() / speed, max_delay))
            message["metadata"]["extra"]["published_at_utc"] = datetime.now(timezone.utc).isoformat()
            result = client.publish(MQTT_REPLAY_TOPIC, json.dumps(message), qos=1)
            result.wait_for_publish()
            previous = current
    finally:
        client.loop_stop()
        client.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-key", type=int, required=True)
    parser.add_argument("--drivers", required=True, help="Lista CSV de numeros o 'all'.")
    parser.add_argument("--start", help="UTC ISO 8601 inclusivo; omitir para inicio disponible.")
    parser.add_argument("--end", help="UTC ISO 8601 exclusivo; omitir para fin disponible.")
    parser.add_argument("--endpoints", default="car_data,location", help="Subset CSV: car_data,location.")
    parser.add_argument("--replay-run-id", required=True, help="Identificador legible y estable de esta ejecucion.")
    parser.add_argument("--speed", type=float, default=20.0)
    parser.add_argument("--max-delay-seconds", type=float, default=0.25)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--confirm-publish", help="Debe ser exactamente REPLAY_OPENF1.")
    args = parser.parse_args()
    if args.speed <= 0 or args.max_delay_seconds < 0:
        parser.error("--speed debe ser positivo y --max-delay-seconds no negativo.")
    if args.publish and args.confirm_publish != "REPLAY_OPENF1":
        parser.error("Publicar exige --confirm-publish REPLAY_OPENF1.")
    if args.start and args.end and parse_time(args.start) >= parse_time(args.end):
        parser.error("--start debe ser anterior a --end.")
    endpoints = args.endpoints.split(",")
    if not endpoints or not set(endpoints) <= SUPPORTED_ENDPOINTS:
        parser.error("--endpoints admite solo car_data y location.")

    session_path = DATA_ROOT / str(args.session_key)
    drivers = parse_drivers(args.drivers, session_path)
    samples = collect_samples(session_path, drivers, endpoints, parse_time(args.start), parse_time(args.end))
    messages = build_messages(samples)
    for message in messages:
        message["metadata"]["extra"]["replay_run_id"] = args.replay_run_id
    summary = {
        "mode": "publish" if args.publish else "dry_run",
        "session_key": args.session_key,
        "replay_run_id": args.replay_run_id,
        "drivers": [number for number, _ in drivers],
        "endpoints": endpoints,
        "source_samples": len(samples),
        "mqtt_messages": len(messages),
        "historical_start": messages[0]["timestamp"] if messages else None,
        "historical_end": messages[-1]["timestamp"] if messages else None,
        "topic": MQTT_REPLAY_TOPIC,
    }
    print(json.dumps(summary, sort_keys=True))
    if args.publish:
        publish(messages, args.speed, args.max_delay_seconds)
        print(f"published_messages={len(messages)}")


if __name__ == "__main__":
    main()
