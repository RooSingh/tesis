"""Estado del vehiculo y de la sesion para el generador de telemetria.

Este modulo define el estado interno utilizado por el MVP del generador.
La idea es simple: antes de que el generador pueda emitir mensajes, necesita
una representacion clara de como se encuentra el vehiculo simulado en un
instante dado.

Este estado no es todavia el mensaje MQTT ni el mensaje interno final. Es la
fotografia interna a partir de la cual luego se construiran esos mensajes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TelemetryState:
    """Estado simulado interno del vehiculo y de su contexto actual.

    Por que existe esta estructura:
    - agrupa en un solo lugar las senales del MVP,
    - mantiene cerca el contexto de sesion y vuelta,
    - y deja una base limpia para modulos posteriores como el scheduler y el
      constructor de mensajes.
    """

    # --- Campos de contexto ---------------------------------------------
    # Estos campos identifican a que contexto deportivo y operativo
    # pertenece la telemetria.
    timestamp: str
    vehicle_id: str
    driver_id: str
    session_id: str
    lap_id: str

    # Estos campos son opcionales porque la segmentacion de pista puede no
    # estar disponible en las primeras etapas del pipeline.
    track_segment_id: str | None = None
    sector_id: str | None = None
    curve_id: str | None = None

    # --- Dinamica principal del vehiculo --------------------------------
    # Velocidad global del vehiculo y velocidades por rueda.
    speed: float = 0.0
    wheel_speed_fl: float = 0.0
    wheel_speed_fr: float = 0.0
    wheel_speed_rl: float = 0.0
    wheel_speed_rr: float = 0.0

    # Direccion y dinamica planar del vehiculo.
    steer_angle: float = 0.0
    accel_x: float = 0.0
    accel_y: float = 0.0
    yaw_rate: float = 0.0

    # --- Entradas basicas del conductor ---------------------------------
    brake_pressed: bool = False
    gas_pedal: float = 0.0

    # --- Calidad por defecto --------------------------------------------
    # Este valor podra ser usado luego por el constructor de mensajes cuando
    # una senal no requiera una clasificacion de calidad mas especifica.
    quality_flag_default: str = "valid"
