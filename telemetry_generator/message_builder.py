"""Utilidades para construir mensajes telemetricos.

Este modulo transforma el estado interno del vehiculo simulado al formato de
mensaje definido para el proyecto. La idea central es desacoplar:

- el estado interno del generador,
- de la forma concreta en que una senal viaja por el sistema.
"""

from __future__ import annotations

from adapters import can_rav4
from telemetry_generator.state import TelemetryState


# EL NOMBRE Y LA UNIDAD SE TOMAN DEL ADAPTADOR DEL BUS REAL, NO SE ESCRIBEN AQUI.
#
# `can_rav4.SENALES` traduce el nombre **crudo del bus** al **canonico del
# contrato interno**, con su unidad:
#
#     "wheel_speed_fl": ("wheel_speed_front_left", "km/h")
#     "accel_x":        ("accel_longitudinal", "m/s^2")
#
# El generador publicaba los de la izquierda y nunca cruzaba esa traduccion.
# Medido el 2026-09-13 en pantalla: de sus doce señales, el tablero dibujaba
# cinco ---las que se llaman igual de los dos lados--- y dejaba vacias las
# cuatro ruedas y las dos aceleraciones, porque el panel pedia
# `wheel_speed_front_left` y en la base habia `wheel_speed_fl`.
#
# NO HAY CONTRADICCION CON EL INFORME: la seccion 7.3 y la tabla A.1 usan
# `accel_x` porque describen el analisis del bus, no el contrato. Los dos
# nombres son correctos en su sitio; faltaba el paso entre uno y otro.
#
# SE REUSA Y NO SE COPIA, que es la regla escrita en ese mismo archivo: «dos
# nombres para la misma medida terminarian en desacuerdo». Copiar la tabla
# crearia un segundo lugar donde se decide como se llama una rueda, y el dia
# que el adaptador cambie uno el generador seguiria publicando el viejo sin que
# nadie se entere. La unidad viaja con el nombre por el mismo motivo: aqui
# decia `m/s2` y el adaptador `m/s^2`, que eran dos sitios decidiendo lo mismo.

#: Nombre del campo del estado y referencia CAN. Lo que **no** esta aqui es el
#: nombre publicado ni la unidad: eso lo pone el adaptador.
CAMPOS_DEL_ESTADO = {
    "wheel_speed_fl": {"state_field": "wheel_speed_fl", "can_id": 170},
    "wheel_speed_fr": {"state_field": "wheel_speed_fr", "can_id": 170},
    "wheel_speed_rl": {"state_field": "wheel_speed_rl", "can_id": 170},
    "wheel_speed_rr": {"state_field": "wheel_speed_rr", "can_id": 170},
    "speed": {"state_field": "speed", "can_id": 180},
    "steer_angle": {"state_field": "steer_angle", "can_id": 37},
    "accel_x": {"state_field": "accel_x", "can_id": 36},
    "accel_y": {"state_field": "accel_y", "can_id": 36},
    "yaw_rate": {"state_field": "yaw_rate", "can_id": 36},
    "brake_pressed": {"state_field": "brake_pressed", "can_id": 550},
    # El adaptador del bus real no publica el acelerador continuo, de modo que
    # no esta en su mapa y conserva su nombre. La tabla A.1 lo sostiene con el
    # ID 705 y la seccion 7.3 lo pone entre las «muy recomendadas»: traducirlo
    # a la fuerza seria inventar un canonico que nadie declaro.
    "gas_pedal": {"state_field": "gas_pedal", "unit": "%", "can_id": 705},
    "gas_pressed": {"state_field": "gas_pressed", "can_id": 466},
}


def _como_se_publica(signal_name: str) -> tuple[str, str]:
    """El nombre canonico y la unidad con que sale una señal."""

    canonico, unidad = can_rav4.SENALES.get(signal_name, (None, None))
    if canonico is not None:
        return canonico, unidad
    propio = CAMPOS_DEL_ESTADO[signal_name]
    return signal_name, propio["unit"]


#: Se conserva el nombre anterior porque hay codigo que lo consulta; lo que
#: cambia es de donde sale cada dato.
SIGNAL_DEFINITIONS = {
    nombre: {**definicion,
             "senal_publicada": _como_se_publica(nombre)[0],
             "unit": _como_se_publica(nombre)[1]}
    for nombre, definicion in CAMPOS_DEL_ESTADO.items()
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
        # El nombre que viaja es el del contrato, no el crudo con que esta
        # funcion lo recibe: ver el comentario del mapa, arriba.
        "signal_name": definition["senal_publicada"],
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
