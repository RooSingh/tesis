"""Consumidor MQTT inicial del backend.

Este modulo define una primera version del consumidor MQTT del backend. En esta
etapa, su objetivo es simple:

- conectarse al broker local,
- suscribirse al topic de telemetria del generador,
- recibir mensajes,
- mostrarlos en consola,
- y conservar una pequena memoria de los ultimos mensajes recibidos.
"""

from __future__ import annotations

import json

import paho.mqtt.client as mqtt

from backend.config import MQTT_HOST, MQTT_PORT, MQTT_TOPIC
from backend.db import insertar_telemetria
from backend.models import TelemetryMessage


# Buffer sencillo en memoria para almacenar los ultimos mensajes recibidos.
# Esto no reemplaza una base de datos; solo sirve para pruebas iniciales del
# backend mientras todavia no existe persistencia formal.
ULTIMOS_MENSAJES: list[dict] = []
MAX_MENSAJES_EN_MEMORIA = 20


def _guardar_mensaje_en_memoria(mensaje: dict) -> None:
    """Guarda un mensaje recibido en un buffer corto en memoria."""

    ULTIMOS_MENSAJES.append(mensaje)

    if len(ULTIMOS_MENSAJES) > MAX_MENSAJES_EN_MEMORIA:
        del ULTIMOS_MENSAJES[0]


def on_connect(client: mqtt.Client, userdata, flags, reason_code, properties) -> None:
    """Callback ejecutado al establecer conexion con el broker."""

    print(f"[MQTT] Conectado al broker con codigo={reason_code}")
    client.subscribe(MQTT_TOPIC)
    print(f"[MQTT] Suscripto a topic: {MQTT_TOPIC}")


def on_message(client: mqtt.Client, userdata, msg: mqtt.MQTTMessage) -> None:
    """Callback ejecutado cuando llega un mensaje desde MQTT."""

    payload = msg.payload.decode("utf-8")
    mensaje_dict = json.loads(payload)
    mensaje = TelemetryMessage.model_validate(mensaje_dict)

    print(f"[MQTT] Mensaje recibido en {msg.topic}: {mensaje.signal_name}")
    _guardar_mensaje_en_memoria(mensaje.model_dump())
    insertar_telemetria(mensaje)


def crear_cliente_mqtt() -> mqtt.Client:
    """Crea y configura el cliente MQTT del backend."""

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    return client


def iniciar_consumidor_mqtt() -> mqtt.Client:
    """Conecta y deja listo el consumidor MQTT del backend.

    Esta funcion no bloquea indefinidamente el hilo principal. Inicia el loop
    de red en segundo plano para que luego pueda integrarse con FastAPI.
    """

    client = crear_cliente_mqtt()
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.loop_start()
    return client
