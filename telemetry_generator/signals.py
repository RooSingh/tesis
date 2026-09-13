"""Logica de actualizacion de senales para el generador de telemetria.

Este modulo contiene una primera version simple de las reglas de simulacion
del MVP. La intencion no es construir todavia un modelo fisico avanzado del
vehiculo, sino generar un estado dinamico coherente y util para las primeras
pruebas del sistema.
"""

from __future__ import annotations

import math

from telemetry_generator.state import TelemetryState


RESISTENCIA_VELOCIDAD_CUADRATICA = 0.00003

#: Ancho de via del vehiculo simulado, en metros. La separacion entre las
#: ruedas de un lado y del otro.
#:
#: NO ES UN NUMERO ELEGIDO A OJO, y esa es toda la diferencia con los demas
#: coeficientes de este archivo. La seccion 13.5 del informe lo **dedujo** del
#: bus real, ajustando la diferencia entre ruedas contra la velocidad de
#: guiñada sobre tres segmentos distintos: 1,564, 1,606 y 1,545 metros, con
#: correlaciones de +0,970, +0,997 y +0,986. Este es el promedio de esos tres.
#:
#: Se declara aqui una sola vez porque de el salen las cuatro ruedas, y porque
#: es lo que permite que el validador de `backend/recorrido.py` ---el mismo que
#: el informe aplica al vehiculo real--- pueda volver a deducirlo de las series
#: generadas y encontrar lo que corresponde a un vehiculo de ese porte.
ANCHO_DE_VIA_M = 1.572


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
        "steer_angle": (-3.0, 0.4),
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
    # El acelerador genera empuje positivo. El freno y una resistencia que crece
    # con la velocidad fuerzan desaceleracion. Los parametros son simulados y
    # revisables; no representan una calibracion de un vehiculo real.
    estado.gas_pressed = estado.gas_pedal > 0.0
    empuje_acelerador = (estado.gas_pedal / 100.0) * 3.0
    desaceleracion_freno = (estado.brake_intensity / 100.0) * 4.5
    resistencia_velocidad = RESISTENCIA_VELOCIDAD_CUADRATICA * estado.speed**2

    # La resistencia evita una aceleracion ilimitada sin imponer un tope de
    # velocidad fijo. Su coeficiente solo produce una trayectoria simulada
    # cualitativamente plausible; no modela aerodinamica calibrada.
    estado.accel_x = empuje_acelerador - desaceleracion_freno - resistencia_velocidad

    # Actualizamos velocidad global integrando aceleracion en forma simple.
    # speed esta en km/h, por eso la conversion usa 3.6.
    estado.speed = max(0.0, estado.speed + estado.accel_x * paso_s * 3.6)

    # --- 2. Dinamica lateral y rotacional -------------------------------
    # El angulo de direccion alimenta una primera aproximacion de yaw y
    # aceleracion lateral. No es un modelo de vehiculo completo; es una
    # relacion simple para mantener coherencia entre senales. Los factores
    # 0.35 y 0.08 son parametros simulados, no valores fisicos calibrados.
    estado.yaw_rate = estado.steer_angle * 0.35
    estado.accel_y = estado.steer_angle * 0.08

    # --- 3. Velocidades de rueda ---------------------------------------
    #
    # LA DIFERENCIA ENTRE LADOS ES GEOMETRIA, NO UN ADORNO.
    #
    # Antes decia «se introducen pequeñas diferencias para reflejar una
    # telemetria mas util y menos artificialmente uniforme», y hacia esto:
    #
    #     wheel_speed_fl = base - steer_angle * 0.02
    #     wheel_speed_rl = base - accel_x * 0.05
    #
    # Las delanteras se separaban por el angulo de direccion con un coeficiente
    # inventado, y las traseras por la **aceleracion longitudinal**, que no
    # tiene ninguna relacion con la diferencia entre izquierda y derecha.
    # Servian para que la serie no fuera plana.
    #
    # POR QUE NO ALCANZA CON QUE NO SEA PLANA. La seccion 13.5 del informe
    # valida la señal de guiñada del bus real por una via independiente: en una
    # curva las ruedas de afuera recorren mas que las de adentro, y esa
    # diferencia dividida por la velocidad de giro **da el ancho de via del
    # vehiculo**. Corrido ese mismo validador sobre la maniobra generada, el
    # 2026-09-13 devolvia 0,93 m: un vehiculo imposible.
    #
    # El capitulo 8 permite que un coeficiente de este generador no este
    # calibrado ---es una «simulacion controlada con ajuste cualitativo»--- y
    # no permite que una señal **contradiga** a otra. Con la guiñada y las
    # ruedas discrepando sobre el ancho del mismo vehiculo simulado, una de las
    # dos estaba mal, y demostrar el metodo de la 13.5 sobre esta fuente no
    # probaba nada.
    #
    # La relacion no hay que calibrarla porque es geometria pura:
    #
    #     diferencia entre lados [m/s] = velocidad de giro [rad/s] x ancho [m]
    #
    # El signo sigue el criterio del validador ---`derecha menos izquierda`---:
    # con guiñada positiva las ruedas de la derecha son las de afuera.
    giro_rad_s = math.radians(estado.yaw_rate)
    diferencia_kmh = giro_rad_s * ANCHO_DE_VIA_M * 3.6
    mitad = diferencia_kmh / 2.0

    base = estado.speed
    # LOS DOS EJES SE SEPARAN IGUAL, que es lo que corresponde a un vehiculo con
    # un solo ancho de via. Uno real tiene el trasero algo distinto del
    # delantero, y meter esa diferencia aqui seria agregar un segundo parametro
    # sin evidencia para sostenerlo: el validador promedia los dos ejes, de modo
    # que no cambiaria lo que se comprueba y si lo que habria que justificar.
    estado.wheel_speed_fl = _limitar(base - mitad, 0.0, 330.0)
    estado.wheel_speed_fr = _limitar(base + mitad, 0.0, 330.0)
    estado.wheel_speed_rl = _limitar(base - mitad, 0.0, 330.0)
    estado.wheel_speed_rr = _limitar(base + mitad, 0.0, 330.0)

    return estado
