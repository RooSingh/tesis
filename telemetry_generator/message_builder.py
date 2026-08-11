"""Utilidades para construir mensajes telemetricos.

Este modulo transforma el estado interno del vehiculo simulado al formato de
mensaje definido para el proyecto. La idea central es desacoplar:

- el estado interno del generador,
- de la forma concreta en que una senal viaja por el sistema.
"""

from __future__ import annotations

from telemetry_generator.state import TelemetryState


# Este catalogo se usa solo al construir mensajes. config.py conserva ademas
# periodos y obligatoriedad para el scheduler.
# Vincula el nombre logico de una senal con:
# - el nombre del campo dentro del estado,
# - la unidad fisica esperada,
# - y la referencia CAN preliminar cuando existe.
SIGNAL_DEFINITIONS = {
    "wheel_speed_fl": {"state_field": "wheel_speed_fl", "unit": "km/h", "can_id": 170},
    "wheel_speed_fr": {"state_field": "wheel_speed_fr", "unit": "km/h", "can_id": 170},
    "wheel_speed_rl": {"state_field": "wheel_speed_rl", "unit": "km/h", "can_id": 170},
    "wheel_speed_rr": {"state_field": "wheel_speed_rr", "unit": "km/h", "can_id": 170},
    "speed": {"state_field": "speed", "unit": "km/h", "can_id": 180},
    "steer_angle": {"state_field": "steer_angle", "unit": "deg", "can_id": 37},
    "accel_x": {"state_field": "accel_x", "unit": "m/s2", "can_id": 36},
    "accel_y": {"state_field": "accel_y", "unit": "m/s2", "can_id": 36},
    "yaw_rate": {"state_field": "yaw_rate", "unit": "deg/s", "can_id": 36},
    "brake_pressed": {"state_field": "brake_pressed", "unit": "bool", "can_id": 550},
    "gas_pedal": {"state_field": "gas_pedal", "unit": "%", "can_id": None},
    "gas_pressed": {"state_field": "gas_pressed", "unit": "bool", "can_id": 466},
}


def construir_mensaje_senal(estado: TelemetryState, signal_name: str) -> dict:
    """Construye un mensaje telemetrico a partir del estado y una senal.

    Parametros:
    - estado: estado actual del vehiculo simulado.
    - signal_name: nombre logico de la senal que se desea emitir.

    Devuelve:
    - un diccionario con el formato interno de mensaje definido para el MVP.
    """

    if signal_name not in SIGNAL_DEFINITIONS:
        raise ValueError(f"La senal '{signal_name}' no esta definida en el catalogo del generador.")

    definition = SIGNAL_DEFINITIONS[signal_name]
    state_field = definition["state_field"]
    value = getattr(estado, state_field)

    mensaje = {
        "timestamp": estado.timestamp,
        "vehicle_id": estado.vehicle_id,
        "driver_id": estado.driver_id,
        "session_id": estado.session_id,
        "lap_id": estado.lap_id,
        # El generador representa el modo Nivel C. Un adaptador real debera
        # construir el mismo contrato con el source_type que corresponda.
        "source_type": "can_simulated",
        "signal_name": signal_name,
        "value": value,
        "unit": definition["unit"],
        "quality_flag": estado.quality_flag_default,
        "track_segment_id": estado.track_segment_id,
        "sector_id": estado.sector_id,
        "curve_id": estado.curve_id,
        "metadata": {
            "can_id": definition.get("can_id"),
            "src": None,
        },
    }

    return mensaje
