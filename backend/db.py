"""Acceso a TimescaleDB para el backend.

Este modulo centraliza inserciones y consultas sobre PostgreSQL/TimescaleDB. No
se utiliza ORM: se trabaja con SQL directo para mantener visibilidad y control
sobre el flujo real de persistencia.
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
    """Inserta un mensaje y conserva valor tipado, contexto y trazabilidad."""

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
                    source_type,
                    signal_name,
                    value_numeric,
                    value_boolean,
                    value_text,
                    unit,
                    quality_flag,
                    track_segment_id,
                    sector_id,
                    curve_id,
                    can_id,
                    src
                ) VALUES (
                    %(timestamp)s,
                    %(vehicle_id)s,
                    %(driver_id)s,
                    %(session_id)s,
                    %(lap_id)s,
                    %(source_type)s,
                    %(signal_name)s,
                    %(value_numeric)s,
                    %(value_boolean)s,
                    %(value_text)s,
                    %(unit)s,
                    %(quality_flag)s,
                    %(track_segment_id)s,
                    %(sector_id)s,
                    %(curve_id)s,
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
                    "source_type": mensaje.source_type,
                    "signal_name": mensaje.signal_name,
                    "value_numeric": value_numeric,
                    "value_boolean": value_boolean,
                    "value_text": value_text,
                    "unit": mensaje.unit,
                    "quality_flag": mensaje.quality_flag,
                    "track_segment_id": mensaje.track_segment_id,
                    "sector_id": mensaje.sector_id,
                    "curve_id": mensaje.curve_id,
                    "can_id": metadata.can_id,
                    "src": metadata.src,
                },
            )


def obtener_ultimos_mensajes(limite: int = 20) -> list[dict]:
    """Devuelve los ultimos mensajes persistidos en la base de datos.

    Parametros:
    - limite: cantidad maxima de filas a recuperar.
    """

    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    timestamp,
                    vehicle_id,
                    driver_id,
                    session_id,
                    lap_id,
                    source_type,
                    signal_name,
                    value_numeric,
                    value_boolean,
                    value_text,
                    unit,
                    quality_flag,
                    track_segment_id,
                    sector_id,
                    curve_id,
                    can_id,
                    src
                FROM telemetry_messages
                ORDER BY timestamp DESC
                LIMIT %s
                """,
                (limite,),
            )

            if cur.description is None:
                return []

            columnas = [desc[0] for desc in cur.description]
            filas = cur.fetchall()

    return [dict(zip(columnas, fila)) for fila in filas]


def obtener_mensajes_por_senal(signal_name: str, limite: int = 50) -> list[dict]:
    """Devuelve los ultimos mensajes persistidos para una senal concreta.

    Parametros:
    - signal_name: nombre logico de la senal a consultar.
    - limite: cantidad maxima de filas a recuperar.
    """

    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    timestamp,
                    vehicle_id,
                    driver_id,
                    session_id,
                    lap_id,
                    source_type,
                    signal_name,
                    value_numeric,
                    value_boolean,
                    value_text,
                    unit,
                    quality_flag,
                    track_segment_id,
                    sector_id,
                    curve_id,
                    can_id,
                    src
                FROM telemetry_messages
                WHERE signal_name = %s
                ORDER BY timestamp DESC
                LIMIT %s
                """,
                (signal_name, limite),
            )

            if cur.description is None:
                return []

            columnas = [desc[0] for desc in cur.description]
            filas = cur.fetchall()

    return [dict(zip(columnas, fila)) for fila in filas]


def obtener_ultimos_por_senal() -> list[dict]:
    """Devuelve la ultima muestra disponible de cada senal.

    Esta consulta resulta util para vistas tipo snapshot o panel en vivo,
    donde interesa el ultimo estado conocido del vehiculo por cada senal.
    """

    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (signal_name)
                    timestamp,
                    vehicle_id,
                    driver_id,
                    session_id,
                    lap_id,
                    source_type,
                    signal_name,
                    value_numeric,
                    value_boolean,
                    value_text,
                    unit,
                    quality_flag,
                    track_segment_id,
                    sector_id,
                    curve_id,
                    can_id,
                    src
                FROM telemetry_messages
                ORDER BY signal_name, timestamp DESC
                """
            )

            if cur.description is None:
                return []

            columnas = [desc[0] for desc in cur.description]
            filas = cur.fetchall()

    return [dict(zip(columnas, fila)) for fila in filas]


def obtener_mensajes_por_sesion(session_id: str, limite: int = 100) -> list[dict]:
    """Devuelve mensajes persistidos pertenecientes a una sesion concreta."""

    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    timestamp,
                    vehicle_id,
                    driver_id,
                    session_id,
                    lap_id,
                    source_type,
                    signal_name,
                    value_numeric,
                    value_boolean,
                    value_text,
                    unit,
                    quality_flag,
                    track_segment_id,
                    sector_id,
                    curve_id,
                    can_id,
                    src
                FROM telemetry_messages
                WHERE session_id = %s
                ORDER BY timestamp DESC
                LIMIT %s
                """,
                (session_id, limite),
            )

            if cur.description is None:
                return []

            columnas = [desc[0] for desc in cur.description]
            filas = cur.fetchall()

    return [dict(zip(columnas, fila)) for fila in filas]
