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


def instantanea_metricas(metrics: dict[str, int]) -> dict[str, int | str]:
    """Agrega el instante de observacion a las metricas del consumidor."""
    return {"observed_at_utc": datetime.now(timezone.utc).isoformat(), **metrics}


def guardar_metricas(path: Path, snapshot: dict[str, int | str]) -> None:
    """Conserva la ultima instantanea reproducible de las metricas del consumidor."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, sort_keys=True),
        encoding="utf-8",
    )


def linea_metricas(metrics: dict[str, int]) -> str:
    """Arma la linea de supervision con las metricas de aceptacion.

    `broker_dropped` encabeza los indicadores de perdida porque es el unico que
    observa el tramo broker -> consumidor. Una corrida previa perdio 8.985
    mensajes con todos los demas contadores en cero, de modo que su ausencia
    dejaba la condicion de aceptacion sin forma de verificarse.

    Se usa `.get()` para que una metrica nueva o ausente no interrumpa la
    supervision de una corrida en progreso.
    """
    campos = (
        "received",
        "persisted",
        "pending",
        "errors",
        "decode_errors",
        "processing_errors",
        "disconnects",
        "broker_dropped",
        "duplicates_skipped",
        "max_pending",
    )
    return "consumer_metrics=" + " ".join(f"{campo}={metrics.get(campo, 'n/d')}" for campo in campos)


def guardar_historial_metricas(path: Path, snapshot: dict[str, int | str]) -> None:
    """Anexa snapshots para analizar tendencia de cola durante una corrida."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as history:
        history.write(json.dumps(snapshot, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--metrics-file",
        type=Path,
        help="Ruta opcional para guardar la ultima instantanea de metricas en JSON.",
    )
    parser.add_argument(
        "--metrics-history-file",
        type=Path,
        help="Ruta opcional JSONL para conservar la tendencia de metricas durante una corrida.",
    )
    args = parser.parse_args()
    client = iniciar_consumidor_mqtt()
    print("consumer_ready=true; stop_with=Ctrl+C")
    try:
        while True:
            time.sleep(5)
            metrics = client.user_data_get().snapshot()
            snapshot = instantanea_metricas(metrics)
            if args.metrics_file:
                guardar_metricas(args.metrics_file, snapshot)
            if args.metrics_history_file:
                guardar_historial_metricas(args.metrics_history_file, snapshot)
            print(linea_metricas(metrics))
    except KeyboardInterrupt:
        metrics = detener_consumidor_mqtt(client)
        snapshot = instantanea_metricas(metrics)
        if args.metrics_file:
            guardar_metricas(args.metrics_file, snapshot)
        if args.metrics_history_file:
            guardar_historial_metricas(args.metrics_history_file, snapshot)
        print("consumer_stopped=true " + linea_metricas(metrics))


if __name__ == "__main__":
    main()
