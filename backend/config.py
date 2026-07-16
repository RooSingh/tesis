"""Configuracion inicial del backend.

Este modulo centraliza los parametros minimos que el backend necesita para
conectarse al broker MQTT y comenzar a recibir telemetria del generador.

En esta primera etapa la configuracion es deliberadamente simple y local.
Mas adelante podra ampliarse con:

- base de datos,
- autenticacion,
- configuracion por entorno,
- y despliegue fuera de localhost.
"""

MQTT_HOST = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "tesis/telemetry/live"

BACKEND_APP_NAME = "tesis-telemetry-backend"
