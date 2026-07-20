"""Acceso inicial a base de datos para el backend.

Este modulo centraliza una primera capa simple de acceso a PostgreSQL/
TimescaleDB. En esta etapa no se utiliza ORM; se trabaja con SQL directo para
mantener visibilidad y control sobre el flujo real de persistencia.
"""

from __future__ import annotations

from typing import Any

import psycopg

from backend.config import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER
from backend.models import TelemetryMessage


def obtener_conexion() -> psycopg.Connection:
    """Crea una conexion simple a la base de datos del proyecto."""

    return psycopg.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )


def _separar_valor(value: Any) -> tuple[float | None, bool | None, str | None]:
    """Separa el valor telemetrico en la columna correcta segun su tipo.

    Regla adoptada:
    - bool -> value_boolean
    - int/float -> value_numeric
    - str -> value_text
    - cualquier otro tipo se serializa como texto
    """

    if isinstance(value, bool):
        return None, value, None

    if isinstance(value, (int, float)):
        return float(value), None, None

    if isinstance(value, str):
        return None, None, value

    return None, None, str(value)


def insertar_telemetria(mensaje: TelemetryMessage) -> None:
    """Inserta un mensaje telemetrico en la tabla `telemetry_messages`."""

    value_numeric, value_boolean, value_text = _separar_valor(mensaje.value)

    metadata = mensaje.metadata

    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO telemetry_messages (
                    timestamp,
                    vehicle_id,
                    driver_id,
                    session_id,
                    lap_id,
                    signal_name,
                    value_numeric,
                    value_boolean,
                    value_text,
                    unit,
                    quality_flag,
                    can_id,
                    src
                ) VALUES (
                    %(timestamp)s,
                    %(vehicle_id)s,
                    %(driver_id)s,
                    %(session_id)s,
                    %(lap_id)s,
                    %(signal_name)s,
                    %(value_numeric)s,
                    %(value_boolean)s,
                    %(value_text)s,
                    %(unit)s,
                    %(quality_flag)s,
                    %(can_id)s,
                    %(src)s
                )
                """,
                {
                    "timestamp": mensaje.timestamp,
                    "vehicle_id": mensaje.vehicle_id,
                    "driver_id": mensaje.driver_id,
                    "session_id": mensaje.session_id,
                    "lap_id": mensaje.lap_id,
                    "signal_name": mensaje.signal_name,
                    "value_numeric": value_numeric,
                    "value_boolean": value_boolean,
                    "value_text": value_text,
                    "unit": mensaje.unit,
                    "quality_flag": mensaje.quality_flag,
                    "can_id": metadata.can_id,
                    "src": metadata.src,
                },
            )
