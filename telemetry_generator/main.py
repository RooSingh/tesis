"""Punto de entrada del MVP del generador de telemetria.

Este modulo orquesta una primera cadena funcional del modo simulacion:

1. crea un estado inicial del vehiculo,
2. avanza el tiempo en pasos simples,
3. actualiza el estado del vehiculo,
4. consulta al scheduler que senales toca emitir,
5. construye los mensajes correspondientes,
6. los imprime por consola,
7. y los publica por MQTT.

La ejecucion requiere un broker MQTT accesible en la configuracion local. El
generador sigue siendo una fuente simulada: MQTT solo transporta los mensajes
hacia el resto de la arquitectura.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import paho.mqtt.client as mqtt

from telemetry_generator.message_builder import construir_mensaje_senal
from telemetry_generator.scheduler import SignalScheduler
from telemetry_generator.signals import aplicar_escenario_demostrativo, actualizar_estado_basico
from telemetry_generator.state import TelemetryState


MQTT_HOST = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "tesis/telemetry/live"


def crear_estado_inicial() -> TelemetryState:
    """Crea un estado inicial simple para el modo simulacion."""

    return TelemetryState(
        timestamp="2026-07-01T15:30:12.120000Z",
        vehicle_id="demo_car_01",
        driver_id="demo_driver_01",
        session_id="demo_session_01",
        lap_id="demo_sequence_01",
        sector_id="demo_sector_01",
        speed=100.0,
        wheel_speed_fl=100.0,
        wheel_speed_fr=100.0,
        wheel_speed_rl=100.0,
        wheel_speed_rr=100.0,
        steer_angle=0.0,
        accel_x=0.0,
        accel_y=0.0,
        yaw_rate=0.0,
        brake_pressed=False,
        gas_pedal=65.0,
    )


def _sumar_milisegundos_a_timestamp(timestamp_iso: str, delta_ms: int) -> str:
    """Suma milisegundos a un timestamp ISO 8601 en UTC.

    Esta funcion permite que el tiempo visible del mensaje acompañe el avance
    del scheduler y del estado interno, evitando que la simulacion muestre un
    reloj fijo mientras el tiempo logico del generador si avanza.
    """

    base = datetime.fromisoformat(timestamp_iso.replace("Z", "+00:00"))
    nuevo = base + timedelta(milliseconds=delta_ms)
    return nuevo.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _formatear_mensaje_resumido(mensaje: dict) -> str:
    """Devuelve una representacion mas legible del mensaje para consola."""

    timestamp = mensaje["timestamp"]
    signal_name = mensaje["signal_name"]
    value = mensaje["value"]
    unit = mensaje["unit"]
    can_id = mensaje["metadata"]["can_id"]

    if isinstance(value, bool):
        value = str(value)
    elif isinstance(value, float):
        value = round(value, 3)

    return f"- {signal_name:<15} | t={timestamp} | valor={value:<8} {unit:<6} | can_id={can_id}"


def ejecutar_ciclos_simulados(cantidad_ciclos: int = 6_000, paso_ms: int = 10) -> None:
    """Ejecuta la secuencia demostrativa de 60 segundos del generador MVP.

    Parametros:
    - cantidad_ciclos: cantidad de iteraciones del flujo. Por defecto cubre
      los 60 segundos completos de la demostracion.
    - paso_ms: tamano del paso temporal por ciclo.
    """

    estado = crear_estado_inicial()
    scheduler = SignalScheduler()
    cliente_mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    cliente_mqtt.connect(MQTT_HOST, MQTT_PORT, 60)

    tiempo_actual_ms = 0

    for ciclo in range(cantidad_ciclos):
        print(f"\n--- CICLO {ciclo + 1} | t={tiempo_actual_ms} ms ---")

        # Actualizamos el timestamp visible del estado para que refleje el
        # tiempo actual de simulacion.
        estado.timestamp = _sumar_milisegundos_a_timestamp(
            "2026-07-01T15:30:12.120000Z", tiempo_actual_ms
        )

        # 1. Aplicamos la fase temporal y actualizamos el estado del vehiculo.
        aplicar_escenario_demostrativo(estado, tiempo_actual_ms)
        actualizar_estado_basico(estado, paso_ms=paso_ms)

        # 2. Preguntamos al scheduler que senales toca emitir ahora.
        senales = scheduler.obtener_senales_a_emitir(tiempo_actual_ms)
        print(f"Total de senales emitidas: {len(senales)}")
        print(f"Senales: {', '.join(senales)}")

        # 3. Construimos e imprimimos los mensajes correspondientes.
        for signal_name in senales:
            mensaje = construir_mensaje_senal(estado, signal_name)
            print(_formatear_mensaje_resumido(mensaje))
            cliente_mqtt.publish(MQTT_TOPIC, json.dumps(mensaje))

        tiempo_actual_ms += paso_ms

    cliente_mqtt.disconnect()


if __name__ == "__main__":
    ejecutar_ciclos_simulados()
