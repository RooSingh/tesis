"""Consumidor MQTT del backend.

Este modulo se ejecuta como proceso separado de FastAPI. Su objetivo es:

- conectarse al broker local,
- suscribirse al topic de telemetria del generador,
- recibir mensajes,
- validarlos,
- persistirlos en la base de datos,
- y conservar una pequena memoria de los ultimos mensajes recibidos para
  inspeccion inmediata.
"""

from __future__ import annotations

import json
import threading

import paho.mqtt.client as mqtt

from backend.config import MQTT_HOST, MQTT_PORT, MQTT_REPLAY_TOPIC, MQTT_TOPIC
from backend.db import insertar_telemetria_lote
from backend.models import TelemetryMessage


# Buffer sencillo en memoria para almacenar los ultimos mensajes recibidos.
# No reemplaza la persistencia: complementa la base de datos durante pruebas e
# inspeccion inmediata del flujo recibido.
ULTIMOS_MENSAJES: list[dict] = []
MAX_MENSAJES_EN_MEMORIA = 20
BATCH_SIZE = 250
FLUSH_INTERVAL_SECONDS = 0.5


class TelemetryBatchBuffer:
    """Desacopla la recepcion MQTT de la persistencia por lotes en TimescaleDB."""

    def __init__(self, writer=insertar_telemetria_lote, batch_size: int = BATCH_SIZE, flush_interval: float = FLUSH_INTERVAL_SECONDS) -> None:
        self.writer = writer
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.pending: list[TelemetryMessage] = []
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.metrics = {"received": 0, "persisted": 0, "errors": 0}
        self.worker = threading.Thread(target=self._run, daemon=True)
        self.worker.start()

    def enqueue(self, message: TelemetryMessage) -> None:
        with self.lock:
            self.pending.append(message)
            self.metrics["received"] += 1

    def _take_batch(self) -> list[TelemetryMessage]:
        with self.lock:
            batch = self.pending[:self.batch_size]
            del self.pending[:len(batch)]
        return batch

    def flush(self) -> int:
        batch = self._take_batch()
        if not batch:
            return 0
        try:
            persisted = self.writer(batch)
        except Exception:
            with self.lock:
                self.pending = batch + self.pending
                self.metrics["errors"] += 1
            return 0
        with self.lock:
            self.metrics["persisted"] += persisted
        return persisted

    def _run(self) -> None:
        while not self.stop_event.wait(self.flush_interval):
            self.flush()

    def close(self) -> None:
        self.stop_event.set()
        self.worker.join(timeout=self.flush_interval * 2)
        while self.flush():
            pass

    def snapshot(self) -> dict[str, int]:
        with self.lock:
            return {**self.metrics, "pending": len(self.pending)}


def _guardar_mensaje_en_memoria(mensaje: dict) -> None:
    """Guarda un mensaje recibido en un buffer corto en memoria."""

    ULTIMOS_MENSAJES.append(mensaje)

    if len(ULTIMOS_MENSAJES) > MAX_MENSAJES_EN_MEMORIA:
        del ULTIMOS_MENSAJES[0]


def on_connect(client: mqtt.Client, userdata, flags, reason_code, properties) -> None:
    """Callback ejecutado al establecer conexion con el broker."""

    print(f"[MQTT] Conectado al broker con codigo={reason_code}")
    client.subscribe([(MQTT_TOPIC, 0), (MQTT_REPLAY_TOPIC, 0)])
    print(f"[MQTT] Suscripto a topics: {MQTT_TOPIC}, {MQTT_REPLAY_TOPIC}")


def on_message(client: mqtt.Client, userdata: TelemetryBatchBuffer, msg: mqtt.MQTTMessage) -> None:
    """Callback ejecutado cuando llega un mensaje desde MQTT."""

    payload = msg.payload.decode("utf-8")
    mensaje_dict = json.loads(payload)
    mensaje = TelemetryMessage.model_validate(mensaje_dict)

    _guardar_mensaje_en_memoria(mensaje.model_dump())
    userdata.enqueue(mensaje)


def crear_cliente_mqtt() -> mqtt.Client:
    """Crea y configura el cliente MQTT del backend."""

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.user_data_set(TelemetryBatchBuffer())
    client.on_connect = on_connect
    client.on_message = on_message
    return client


def iniciar_consumidor_mqtt() -> mqtt.Client:
    """Conecta y deja listo el consumidor MQTT del backend.

    Esta funcion no bloquea indefinidamente el hilo principal porque Paho usa un
    loop de red en segundo plano. Quien la invoque debe mantener vivo su propio
    proceso; FastAPI no inicia este consumidor automaticamente.
    """

    client = crear_cliente_mqtt()
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.loop_start()
    return client


def detener_consumidor_mqtt(client: mqtt.Client) -> dict[str, int]:
    """Detiene red y vacia el buffer antes de finalizar un proceso consumidor."""
    client.loop_stop()
    client.disconnect()
    buffer: TelemetryBatchBuffer = client.user_data_get()
    buffer.close()
    return buffer.snapshot()
