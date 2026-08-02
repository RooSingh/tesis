"""Logica de actualizacion de senales para el generador de telemetria.

Este modulo contiene una primera version simple de las reglas de simulacion
del MVP. La intencion no es construir todavia un modelo fisico avanzado del
vehiculo, sino generar un estado dinamico coherente y util para las primeras
pruebas del sistema.
"""

from __future__ import annotations

from telemetry_generator.state import TelemetryState


DEMO_PHASES = (
    {
        "start_ms": 0,
        "end_ms": 14_000,
        "track_segment_id": "demo_straight_entry",
        "gas_pedal": (65.0, 85.0),
        "brake_intensity": (0.0, 0.0),
        "steer_angle": (0.0, 0.0),
    },
    {
        "start_ms": 14_000,
        "end_ms": 20_000,
        "track_segment_id": "demo_braking_zone",
        "gas_pedal": (85.0, 0.0),
        "brake_intensity": ((0.0, 0.0), (0.5, 75.0), (1.0, 35.0)),
        "steer_angle": (0.0, 2.0),
    },
    {
        "start_ms": 20_000,
        "end_ms": 27_000,
        "track_segment_id": "demo_corner_entry",
        "curve_id": "demo_curve_01",
        "gas_pedal": (0.0, 12.0),
        "brake_intensity": (35.0, 0.0),
        "steer_angle": (2.0, 18.0),
    },
    {
        "start_ms": 27_000,
        "end_ms": 34_000,
        "track_segment_id": "demo_corner_apex",
        "curve_id": "demo_curve_01",
        "gas_pedal": (12.0, 25.0),
        "brake_intensity": (0.0, 0.0),
        "steer_angle": (18.0, 22.0),
    },
    {
        "start_ms": 34_000,
        "end_ms": 44_000,
        "track_segment_id": "demo_corner_exit",
        "curve_id": "demo_curve_01",
        "gas_pedal": (25.0, 75.0),
        "brake_intensity": (0.0, 0.0),
        "steer_angle": (22.0, -3.0),
    },
    {
        "start_ms": 44_000,
        "end_ms": 60_000,
        "track_segment_id": "demo_straight_exit",
        "gas_pedal": (75.0, 90.0),
        "brake_intensity": (0.0, 0.0),
        "steer_angle": (-3.0, 0.0),
    },
)


def _limitar(valor: float, minimo: float, maximo: float) -> float:
    """Limita un valor numerico a un rango definido."""
    return max(minimo, min(valor, maximo))


def _interpolar(inicio: float, fin: float, progreso: float) -> float:
    """Interpola linealmente un valor dentro de una fase temporal."""
    return inicio + ((fin - inicio) * progreso)


def _interpolar_perfil(perfil: tuple, progreso: float) -> float:
    """Interpola un perfil simple o uno definido por puntos de control."""
    if len(perfil) == 2 and isinstance(perfil[0], float):
        return _interpolar(*perfil, progreso)

    for (inicio_t, inicio_valor), (fin_t, fin_valor) in zip(perfil, perfil[1:]):
        if inicio_t <= progreso <= fin_t:
            progreso_tramo = (progreso - inicio_t) / (fin_t - inicio_t)
            return _interpolar(inicio_valor, fin_valor, progreso_tramo)

    return perfil[-1][1]


def aplicar_escenario_demostrativo(estado: TelemetryState, tiempo_actual_ms: int) -> TelemetryState:
    """Aplica la fase temporal correspondiente de la demo finita de 60 s.

    El escenario es controlado y no representa una vuelta física exacta. Sus
    entradas continuas son simuladas; brake_pressed se deriva de la intensidad
    para preservar su semántica binaria.
    """

    for fase in DEMO_PHASES:
        if fase["start_ms"] <= tiempo_actual_ms < fase["end_ms"]:
            duracion_ms = fase["end_ms"] - fase["start_ms"]
            progreso = (tiempo_actual_ms - fase["start_ms"]) / duracion_ms
            estado.track_segment_id = fase["track_segment_id"]
            estado.curve_id = fase.get("curve_id")
            estado.gas_pedal = _interpolar(*fase["gas_pedal"], progreso)
            estado.brake_intensity = _interpolar_perfil(fase["brake_intensity"], progreso)
            estado.steer_angle = _interpolar(*fase["steer_angle"], progreso)
            estado.brake_pressed = estado.brake_intensity > 0.0
            return estado

    raise ValueError("El escenario demostrativo finaliza a los 60 segundos.")


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
    # Los factores 3.0 y 4.5 son parametros simulados y revisables del MVP;
    # no representan una calibracion de un vehiculo real.
    estado.gas_pressed = estado.gas_pedal > 0.0
    empuje_acelerador = (estado.gas_pedal / 100.0) * 3.0
    desaceleracion_freno = (estado.brake_intensity / 100.0) * 4.5

    # La aceleracion longitudinal resultante combina ambas influencias.
    estado.accel_x = empuje_acelerador - desaceleracion_freno

    # Actualizamos velocidad global integrando aceleracion en forma simple.
    # speed esta en km/h, por eso la conversion usa 3.6.
    estado.speed += estado.accel_x * paso_s * 3.6
    estado.speed = _limitar(estado.speed, 0.0, 320.0)

    # --- 2. Dinamica lateral y rotacional -------------------------------
    # El angulo de direccion alimenta una primera aproximacion de yaw y
    # aceleracion lateral. No es un modelo de vehiculo completo; es una
    # relacion simple para mantener coherencia entre senales. Los factores
    # 0.35 y 0.08 son parametros simulados, no valores fisicos calibrados.
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
