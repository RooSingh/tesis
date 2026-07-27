"""Logica de actualizacion de senales para el generador de telemetria.

Este modulo contiene una primera version simple de las reglas de simulacion
del MVP. La intencion no es construir todavia un modelo fisico avanzado del
vehiculo, sino generar un estado dinamico coherente y util para las primeras
pruebas del sistema.
"""

from __future__ import annotations

from telemetry_generator.state import TelemetryState


def _limitar(valor: float, minimo: float, maximo: float) -> float:
    """Limita un valor numerico a un rango definido."""
    return max(minimo, min(valor, maximo))


def actualizar_estado_basico(estado: TelemetryState, paso_ms: int = 10) -> TelemetryState:
    """Actualiza el estado del vehiculo con una logica simple y coherente.

    Parametros:
    - estado: estado actual del vehiculo simulado.
    - paso_ms: tamano del paso temporal en milisegundos.

    Logica general de esta primera version:
    - el acelerador empuja la velocidad y la aceleracion longitudinal,
    - el freno fuerza desaceleracion,
    - el angulo de direccion influye en aceleracion lateral y yaw rate,
    - las velocidades de rueda siguen a la velocidad global con pequenas
      diferencias por esquina.

    Esta logica es intencionalmente simple y revisable. Busca coherencia
    interna suficiente para el MVP, no fidelidad fisica definitiva.
    """

    paso_s = paso_ms / 1000.0

    # --- 1. Dinamica longitudinal --------------------------------------
    # El acelerador genera empuje positivo. El freno fuerza desaceleracion.
    estado.gas_pressed = estado.gas_pedal > 0.0
    empuje_acelerador = (estado.gas_pedal / 100.0) * 3.0
    desaceleracion_freno = 4.5 if estado.brake_pressed else 0.0

    # La aceleracion longitudinal resultante combina ambas influencias.
    estado.accel_x = empuje_acelerador - desaceleracion_freno

    # Actualizamos velocidad global integrando aceleracion en forma simple.
    # speed esta en km/h, por eso la conversion usa 3.6.
    estado.speed += estado.accel_x * paso_s * 3.6
    estado.speed = _limitar(estado.speed, 0.0, 320.0)

    # --- 2. Dinamica lateral y rotacional -------------------------------
    # El angulo de direccion alimenta una primera aproximacion de yaw y
    # aceleracion lateral. No es un modelo de vehiculo completo; es una
    # relacion simple para mantener coherencia entre senales.
    estado.yaw_rate = estado.steer_angle * 0.35
    estado.accel_y = estado.steer_angle * 0.08

    # --- 3. Velocidades de rueda ---------------------------------------
    # Las velocidades de rueda siguen a la velocidad global, pero no son
    # exactamente identicas. Se introducen pequenas diferencias para reflejar
    # una telemetria mas util y menos artificialmente uniforme.
    base = estado.speed
    estado.wheel_speed_fl = _limitar(base - (estado.steer_angle * 0.02), 0.0, 330.0)
    estado.wheel_speed_fr = _limitar(base + (estado.steer_angle * 0.02), 0.0, 330.0)
    estado.wheel_speed_rl = _limitar(base - (estado.accel_x * 0.05), 0.0, 330.0)
    estado.wheel_speed_rr = _limitar(base + (estado.accel_x * 0.05), 0.0, 330.0)

    return estado
