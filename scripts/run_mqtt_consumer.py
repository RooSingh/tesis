"""Inicia de forma explicita el consumidor MQTT existente para pruebas controladas."""

from __future__ import annotations

import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.mqtt_consumer import detener_consumidor_mqtt, iniciar_consumidor_mqtt


def main() -> None:
    client = iniciar_consumidor_mqtt()
    print("consumer_ready=true; stop_with=Ctrl+C")
    try:
        while True:
            time.sleep(5)
            metrics = client.user_data_get().snapshot()
            print(
                "consumer_metrics="
                f"received={metrics['received']} "
                f"persisted={metrics['persisted']} "
                f"pending={metrics['pending']} "
                f"errors={metrics['errors']}"
            )
    except KeyboardInterrupt:
        metrics = detener_consumidor_mqtt(client)
        print(
            "consumer_stopped=true "
            f"received={metrics['received']} "
            f"persisted={metrics['persisted']} "
            f"pending={metrics['pending']} "
            f"errors={metrics['errors']}"
        )


if __name__ == "__main__":
    main()
