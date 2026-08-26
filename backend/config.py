"""Configuracion local del backend.

Este modulo centraliza los parametros que usan el consumidor MQTT, la API y la
capa de persistencia para conectarse a los servicios locales de la tesis.

La configuracion es deliberadamente simple y local. No distingue todavia
entornos de desarrollo, prueba o despliegue.
Mas adelante podra ampliarse con:

- autenticacion,
- configuracion por entorno,
- y despliegue fuera de localhost.
"""

import os

MQTT_HOST = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "tesis/telemetry/live"
MQTT_REPLAY_TOPIC = "tesis/telemetry/replay"
MQTT_BATCH_SIZE = int(os.getenv("MQTT_BATCH_SIZE", "1000"))
MQTT_FLUSH_INTERVAL_SECONDS = float(os.getenv("MQTT_FLUSH_INTERVAL_SECONDS", "0.5"))

# Cota superior de la cola en memoria del consumidor. En `0` el buffer crece sin
# limite, que es el comportamiento historico y el que se conserva por defecto
# para no alterar corridas ya validadas. Un valor positivo activa contrapresion:
# el hilo de red se frena antes de agotar la RAM, a costa de dejar de confirmar
# mensajes al broker. Solo debe activarse en una prueba controlada.
MQTT_MAX_PENDING_MESSAGES = int(os.getenv("MQTT_MAX_PENDING_MESSAGES", "0"))

# Estadistica interna que publica Mosquitto con la cantidad acumulada de mensajes
# descartados hacia sus clientes. Es el unico observador del tramo
# broker -> consumidor, donde el proyecto demostro perder mensajes sin que ningun
# contador propio lo reflejara.
MQTT_SYS_DROPPED_TOPIC = "$SYS/broker/publish/messages/dropped"

BACKEND_APP_NAME = "tesis-telemetry-backend"

DB_HOST = "localhost"
DB_PORT = 5432
DB_NAME = "tesis_db"
DB_USER = "tesis_user"
DB_PASSWORD = "tesis_pass"
