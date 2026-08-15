"""Publica solo 27 mensajes OpenF1 autorizados para validar el pipeline MQTT."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.openf1 import messages_from_openf1_sample
from backend.config import MQTT_HOST, MQTT_PORT, MQTT_REPLAY_TOPIC


RAW_PATH = ROOT / "datasets" / "OpenF1" / "raw" / "2025" / "9947"
DRIVERS = {1: "VER", 4: "NOR", 81: "PIA"}


def build_batch() -> list[dict]:
    """Construye seis muestras fuente: car_data y location de cada piloto autorizado."""
    messages = []
    for driver_number, acronym in DRIVERS.items():
        for endpoint in ("car_data", "location"):
            filename = f"{endpoint}_driver_{driver_number}_{acronym}.json"
            path = RAW_PATH / filename
            sample = json.loads(path.read_text(encoding="utf-8"))[0]
            source_url = f"https://api.openf1.org/v1/{endpoint}?session_key=9947&driver_number={driver_number}"
            messages.extend(messages_from_openf1_sample(sample, endpoint, source_url, str(path), datetime.now(timezone.utc).isoformat()))
    return sorted(messages, key=lambda message: message["timestamp"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish", action="store_true", help="Publica los 27 mensajes; sin este flag solo resume.")
    args = parser.parse_args()
    messages = build_batch()
    if len(messages) != 27:
        raise ValueError(f"El lote tecnico debe tener 27 mensajes y tiene {len(messages)}.")
    print(json.dumps({"mode": "publish" if args.publish else "dry_run", "mqtt_messages": len(messages), "drivers": sorted(DRIVERS), "topic": MQTT_REPLAY_TOPIC, "wait_between_messages": False}, sort_keys=True))
    if not args.publish:
        return
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.loop_start()
    try:
        for message in messages:
            message["metadata"]["extra"]["published_at_utc"] = datetime.now(timezone.utc).isoformat()
            result = client.publish(MQTT_REPLAY_TOPIC, json.dumps(message), qos=1)
            result.wait_for_publish()
    finally:
        client.loop_stop()
        client.disconnect()
    print("published_messages=27")


if __name__ == "__main__":
    main()
