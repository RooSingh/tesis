"""Inicia de forma explicita el consumidor MQTT existente para pruebas controladas."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.mqtt_consumer import detener_consumidor_mqtt, iniciar_consumidor_mqtt


def guardar_metricas(path: Path, metrics: dict[str, int]) -> None:
    """Conserva una instantanea reproducible de las metricas del consumidor."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "observed_at_utc": datetime.now(timezone.utc).isoformat(),
                **metrics,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--metrics-file",
        type=Path,
        help="Ruta opcional para guardar la ultima instantanea de metricas en JSON.",
    )
    args = parser.parse_args()
    client = iniciar_consumidor_mqtt()
    print("consumer_ready=true; stop_with=Ctrl+C")
    try:
        while True:
            time.sleep(5)
            metrics = client.user_data_get().snapshot()
            if args.metrics_file:
                guardar_metricas(args.metrics_file, metrics)
            print(
                "consumer_metrics="
                f"received={metrics['received']} "
                f"persisted={metrics['persisted']} "
                f"pending={metrics['pending']} "
                f"errors={metrics['errors']}"
            )
    except KeyboardInterrupt:
        metrics = detener_consumidor_mqtt(client)
        if args.metrics_file:
            guardar_metricas(args.metrics_file, metrics)
        print(
            "consumer_stopped=true "
            f"received={metrics['received']} "
            f"persisted={metrics['persisted']} "
            f"pending={metrics['pending']} "
            f"errors={metrics['errors']}"
        )


if __name__ == "__main__":
    main()
