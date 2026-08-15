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

MQTT_HOST = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "tesis/telemetry/live"
MQTT_REPLAY_TOPIC = "tesis/telemetry/replay"

BACKEND_APP_NAME = "tesis-telemetry-backend"

DB_HOST = "localhost"
DB_PORT = 5432
DB_NAME = "tesis_db"
DB_USER = "tesis_user"
DB_PASSWORD = "tesis_pass"
