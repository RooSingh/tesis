"""Configuración inicial del generador.

Este módulo define el primer catálogo de señales del MVP para el generador de
telemetría. En esta etapa, el objetivo no es simular todas las variables
posibles del vehículo, sino establecer un conjunto acotado, útil y
técnicamente justificable de señales que puedan emitirse en la primera versión
del sistema.

Nota importante:
- los períodos definidos aquí son valores iniciales de trabajo,
- no se presentan como cycle times OEM exactos,
- y quedan abiertos a revisión tras un análisis CAN más profundo o una
  validación sobre más segmentos.

Por qué este archivo importa:
- centraliza qué emite el generador,
- asigna unidad y período a cada señal,
- y conserva trazabilidad con el análisis CAN/DBC ya realizado.
"""

from __future__ import annotations


# El MVP inicial se concentra en:
# - velocidad del vehículo y velocidades de rueda,
# - entrada de dirección,
# - cinemática vehicular básica,
# - y dos variables básicas de acción del conductor: freno y acelerador.
#
# Los períodos elegidos son provisionales, pero están apoyados en:
# - evidencia local de la muestra analizada,
# - mapeo semántico preliminar mediante openDBC,
# - y bandas de frecuencia respaldadas por bibliografía.
#
# Importante sobre can_id:
# - los valores consignados aquí deben leerse como referencias CAN preliminares,
#   no como identificaciones semánticas absolutamente cerradas para toda la tesis,
# - su función actual es conservar trazabilidad con el análisis CAN ya hecho,
# - y quedan abiertos a futura consolidación o corrección en nuevas rondas de
#   estudio del dataset.
#
# El nivel de confianza no es idéntico para todas las señales:
# - wheel speeds, steer angle, speed y kinematics tienen apoyo más fuerte,
# - brake_pressed y gas_pressed cuentan con validación CAN dirigida,
# - gas_pedal se conserva como porcentaje simulado de valor deportivo, sin
#   asociarlo a un ID CAN no validado para esta plataforma.

MVP_SIGNALS = [
    {
        "signal_name": "wheel_speed_fl",
        "unit": "km/h",
        "period_ms": 10,
        "source_type": "can_simulated",
        "required": True,
        "can_id": 170,
        "notes": "Velocidad de rueda delantera izquierda. Señal dinámica de alta frecuencia con buen nivel de confianza.",
    },
    {
        "signal_name": "wheel_speed_fr",
        "unit": "km/h",
        "period_ms": 10,
        "source_type": "can_simulated",
        "required": True,
        "can_id": 170,
        "notes": "Velocidad de rueda delantera derecha. Señal dinámica de alta frecuencia con buen nivel de confianza.",
    },
    {
        "signal_name": "wheel_speed_rl",
        "unit": "km/h",
        "period_ms": 10,
        "source_type": "can_simulated",
        "required": True,
        "can_id": 170,
        "notes": "Velocidad de rueda trasera izquierda. Señal dinámica de alta frecuencia con buen nivel de confianza.",
    },
    {
        "signal_name": "wheel_speed_rr",
        "unit": "km/h",
        "period_ms": 10,
        "source_type": "can_simulated",
        "required": True,
        "can_id": 170,
        "notes": "Velocidad de rueda trasera derecha. Señal dinámica de alta frecuencia con buen nivel de confianza.",
    },
    {
        "signal_name": "steer_angle",
        "unit": "deg",
        "period_ms": 10,
        "source_type": "can_simulated",
        "required": True,
        "can_id": 37,
        "notes": "Ángulo de dirección asociado a la familia steering angle sensor. Con apoyo fuerte en la muestra y en el DBC.",
    },
    {
        "signal_name": "speed",
        "unit": "km/h",
        "period_ms": 20,
        "source_type": "can_simulated",
        "required": True,
        "can_id": 180,
        "notes": "Señal de velocidad general del vehículo con banda temporal media. Con apoyo fuerte en la muestra y en el DBC.",
    },
    {
        "signal_name": "accel_x",
        "unit": "m/s2",
        "period_ms": 20,
        "source_type": "can_simulated",
        "required": True,
        "can_id": 36,
        "notes": "Aceleración longitudinal de la familia kinematics. Buen apoyo, con período todavía revisable.",
    },
    {
        "signal_name": "accel_y",
        "unit": "m/s2",
        "period_ms": 20,
        "source_type": "can_simulated",
        "required": True,
        "can_id": 36,
        "notes": "Aceleración lateral de la familia kinematics. Buen apoyo, con período todavía revisable.",
    },
    {
        "signal_name": "yaw_rate",
        "unit": "deg/s",
        "period_ms": 20,
        "source_type": "can_simulated",
        "required": True,
        "can_id": 36,
        "notes": "Yaw rate de la familia kinematics. Buen apoyo, con período todavía revisable.",
    },
    {
        "signal_name": "brake_pressed",
        "unit": "bool",
        "period_ms": 20,
        "source_type": "can_simulated",
        "required": True,
        "can_id": 550,
        "notes": "Estado binario del freno validado en la segunda pasada CAN sobre el ID 550.",
    },
    {
        "signal_name": "gas_pedal",
        "unit": "%",
        "period_ms": 20,
        "source_type": "can_simulated",
        "required": True,
        "can_id": 865,
        "notes": "Posición continua de acelerador. Cuando se escribió este catálogo no tenía un ID CAN validado en la muestra RAV4; el análisis posterior evaluó cuatro candidatos y adoptó el ID 865, el único que responde en las dos variantes de la plataforma: 55.904 pares temporales, varía en 26 de 30 segmentos y correlación de Pearson de 0,829 contra el indicador de accionamiento (tabla A.1). Se sostiene como intensidad relativa y no como magnitud física: falta calibrarlo contra una referencia externa.",
    },
    {
        "signal_name": "gas_pressed",
        "unit": "bool",
        "period_ms": 20,
        "source_type": "can_simulated",
        "required": False,
        "can_id": 466,
        "notes": "Acción binaria de acelerador, inspirada en PCM_CRUISE.GAS_RELEASED y validada como referencia CAN en la segunda pasada dirigida.",
    },
]
