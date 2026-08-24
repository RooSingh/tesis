"""Acceso a TimescaleDB para el backend.

Este modulo centraliza inserciones y consultas sobre PostgreSQL/TimescaleDB. No
se utiliza ORM: se trabaja con SQL directo para mantener visibilidad y control
sobre el flujo real de persistencia.
"""

from __future__ import annotations

import json
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
                    src,
                    metadata
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
                    %(src)s,
                    %(metadata)s::jsonb
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
                    "metadata": json.dumps(metadata.model_dump(mode="json", exclude_none=True)),
                },
            )


def _parametros_telemetria(mensaje: TelemetryMessage) -> dict[str, Any]:
    """Normaliza un mensaje para insercion individual o por lote."""
    value_numeric, value_boolean, value_text = _separar_valor(mensaje.value)
    metadata = mensaje.metadata
    return {
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
        "metadata": json.dumps(metadata.model_dump(mode="json", exclude_none=True)),
    }


INSERT_TELEMETRY_SQL = """
    INSERT INTO telemetry_messages (
        timestamp, vehicle_id, driver_id, session_id, lap_id, source_type,
        signal_name, value_numeric, value_boolean, value_text, unit,
        quality_flag, track_segment_id, sector_id, curve_id, can_id, src, metadata
    ) VALUES (
        %(timestamp)s, %(vehicle_id)s, %(driver_id)s, %(session_id)s, %(lap_id)s,
        %(source_type)s, %(signal_name)s, %(value_numeric)s, %(value_boolean)s,
        %(value_text)s, %(unit)s, %(quality_flag)s, %(track_segment_id)s,
        %(sector_id)s, %(curve_id)s, %(can_id)s, %(src)s, %(metadata)s::jsonb
    )
"""


def insertar_telemetria_lote(mensajes: list[TelemetryMessage]) -> int:
    """Persiste un lote en una sola conexion/transaccion de PostgreSQL."""
    if not mensajes:
        return 0
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.executemany(INSERT_TELEMETRY_SQL, [_parametros_telemetria(mensaje) for mensaje in mensajes])
    return len(mensajes)


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


def obtener_sesion_racing(session_key: int) -> dict | None:
    """Devuelve contexto profesional de una sesion racing ya normalizada."""

    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    session_key, meeting_key, session_name, session_type,
                    circuit_short_name, country_name, location, date_start, date_end,
                    (SELECT count(*) FROM racing_laps WHERE racing_laps.session_key = racing_sessions.session_key) AS laps,
                    (SELECT count(*) FROM racing_stints WHERE racing_stints.session_key = racing_sessions.session_key) AS stints,
                    (SELECT count(*) FROM racing_pit_stops WHERE racing_pit_stops.session_key = racing_sessions.session_key) AS pit_stops,
                    (SELECT count(*) FROM racing_weather WHERE racing_weather.session_key = racing_sessions.session_key) AS weather_samples,
                    (SELECT count(*) FROM racing_events WHERE racing_events.session_key = racing_sessions.session_key) AS race_control_events
                FROM racing_sessions
                WHERE session_key = %s
                """,
                (session_key,),
            )
            row = cur.fetchone()
            if row is None or cur.description is None:
                return None
            return dict(zip([desc[0] for desc in cur.description], row))


def obtener_pilotos_racing(session_key: int) -> list[dict]:
    """Devuelve pilotos/equipos de la sesion para seleccionar comparaciones."""

    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT driver_number, full_name, name_acronym, team_name, team_colour
                FROM racing_drivers
                WHERE session_key = %s
                ORDER BY driver_number
                """,
                (session_key,),
            )
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]


def obtener_replay_openf1(
    session_key: int, driver_number: int | None = None, replay_run_id: str | None = None
) -> list[dict]:
    """Devuelve el lote replay con trazabilidad para una sesion y piloto opcional."""

    session_id = f"openf1:session:{session_key}"
    query = """
        SELECT timestamp, vehicle_id, driver_id, session_id, source_type,
               signal_name, value_numeric, value_boolean, value_text, unit,
               quality_flag, metadata
        FROM telemetry_messages
        WHERE session_id = %s
          AND source_type = 'openf1_historical_replay'
    """
    params: list[object] = [session_id]
    if driver_number is not None:
        query += " AND driver_id = %s"
        params.append(f"openf1:driver:{driver_number}")
    if replay_run_id is not None:
        query += " AND metadata->'extra'->>'replay_run_id' = %s"
        params.append(replay_run_id)
    query += " ORDER BY timestamp, driver_id, signal_name"
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]


def obtener_comparacion_pilotos_racing(session_key: int, driver_numbers: list[int]) -> list[dict]:
    """Resume resultado, ritmo y estrategia para pilotos de una sesion racing."""
    if not driver_numbers:
        return []
    query = """
        SELECT
            drivers.driver_number,
            drivers.name_acronym,
            drivers.full_name,
            drivers.team_name,
            results.position AS final_position,
            results.points,
            laps.best_lap_seconds,
            stints.stint_count,
            stints.compounds,
            COALESCE(pit_stops.pit_stop_count, 0) AS pit_stop_count
        FROM racing_drivers AS drivers
        LEFT JOIN racing_session_results AS results
            ON results.session_key = drivers.session_key
            AND results.driver_number = drivers.driver_number
        LEFT JOIN (
            SELECT session_key, driver_number, MIN(lap_duration_seconds) AS best_lap_seconds
            FROM racing_laps
            WHERE lap_duration_seconds IS NOT NULL AND COALESCE(is_pit_out_lap, false) = false
            GROUP BY session_key, driver_number
        ) AS laps
            ON laps.session_key = drivers.session_key
            AND laps.driver_number = drivers.driver_number
        LEFT JOIN (
            SELECT
                session_key,
                driver_number,
                COUNT(*) AS stint_count,
                STRING_AGG(DISTINCT compound, ', ' ORDER BY compound) AS compounds
            FROM racing_stints
            GROUP BY session_key, driver_number
        ) AS stints
            ON stints.session_key = drivers.session_key
            AND stints.driver_number = drivers.driver_number
        LEFT JOIN (
            SELECT session_key, driver_number, COUNT(*) AS pit_stop_count
            FROM racing_pit_stops
            GROUP BY session_key, driver_number
        ) AS pit_stops
            ON pit_stops.session_key = drivers.session_key
            AND pit_stops.driver_number = drivers.driver_number
        WHERE drivers.session_key = %s AND drivers.driver_number = ANY(%s)
        ORDER BY results.position NULLS LAST, drivers.driver_number
    """
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (session_key, driver_numbers))
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]


def obtener_serie_replay_openf1(
    session_key: int, replay_run_id: str, driver_numbers: list[int], signal_name: str
) -> list[dict]:
    """Devuelve una senal temporal replay, ordenada por reloj deportivo."""
    if not driver_numbers:
        return []
    query = """
        SELECT timestamp, driver_id, signal_name, value_numeric, value_boolean, unit
        FROM telemetry_messages
        WHERE session_id = %s
          AND source_type = 'openf1_historical_replay'
          AND metadata->'extra'->>'replay_run_id' = %s
          AND driver_id = ANY(%s)
          AND signal_name = %s
        ORDER BY timestamp, driver_id
    """
    driver_ids = [f"openf1:driver:{number}" for number in driver_numbers]
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (f"openf1:session:{session_key}", replay_run_id, driver_ids, signal_name))
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]


def obtener_contexto_racing_en_instante(
    session_key: int, timestamp: str, driver_numbers: list[int]
) -> dict:
    """Devuelve contexto racing cercano a un instante UTC para pilotos elegidos."""
    if not driver_numbers:
        return {"drivers": [], "weather": None}
    query = """
        SELECT
            drivers.driver_number,
            drivers.name_acronym,
            position.position,
            position.age_seconds AS position_age_seconds,
            interval.gap_to_leader_seconds,
            interval.gap_to_leader_text,
            interval.interval_seconds,
            interval.interval_text,
            interval.age_seconds AS interval_age_seconds,
            stint.stint_number,
            stint.compound,
            stint.tyre_age_at_start
        FROM racing_drivers AS drivers
        LEFT JOIN LATERAL (
            SELECT position, ABS(EXTRACT(EPOCH FROM (date - %s::timestamptz))) AS age_seconds
            FROM racing_positions
            WHERE session_key = drivers.session_key
              AND driver_number = drivers.driver_number
            ORDER BY ABS(EXTRACT(EPOCH FROM (date - %s::timestamptz)))
            LIMIT 1
        ) AS position ON true
        LEFT JOIN LATERAL (
            SELECT gap_to_leader_seconds, gap_to_leader_text, interval_seconds, interval_text,
                   ABS(EXTRACT(EPOCH FROM (date - %s::timestamptz))) AS age_seconds
            FROM racing_intervals
            WHERE session_key = drivers.session_key
              AND driver_number = drivers.driver_number
            ORDER BY ABS(EXTRACT(EPOCH FROM (date - %s::timestamptz)))
            LIMIT 1
        ) AS interval ON true
        LEFT JOIN LATERAL (
            SELECT stint_number, compound, tyre_age_at_start
            FROM racing_stints AS stints
            WHERE stints.session_key = drivers.session_key
              AND lap_start IS NOT NULL
              AND lap_end IS NOT NULL
              AND lap_start <= (
                  SELECT laps.lap_number
                  FROM racing_laps AS laps
                  WHERE laps.session_key = drivers.session_key
                    AND laps.driver_number = drivers.driver_number
                    AND laps.date_start <= %s::timestamptz
                  ORDER BY laps.date_start DESC
                  LIMIT 1
              )
              AND lap_end >= (
                  SELECT laps.lap_number
                  FROM racing_laps AS laps
                  WHERE laps.session_key = drivers.session_key
                    AND laps.driver_number = drivers.driver_number
                    AND laps.date_start <= %s::timestamptz
                  ORDER BY laps.date_start DESC
                  LIMIT 1
              )
            LIMIT 1
        ) AS stint ON true
        WHERE drivers.session_key = %s AND drivers.driver_number = ANY(%s)
        ORDER BY drivers.driver_number
    """
    weather_query = """
        SELECT air_temperature_c, track_temperature_c, rainfall, humidity_percent,
               ABS(EXTRACT(EPOCH FROM (date - %s::timestamptz))) AS weather_age_seconds
        FROM racing_weather
        WHERE session_key = %s
        ORDER BY ABS(EXTRACT(EPOCH FROM (date - %s::timestamptz)))
        LIMIT 1
    """
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                query,
                (timestamp, timestamp, timestamp, timestamp, timestamp, timestamp, session_key, driver_numbers),
            )
            columns = [desc[0] for desc in cur.description]
            drivers = [dict(zip(columns, row)) for row in cur.fetchall()]
            cur.execute(weather_query, (timestamp, session_key, timestamp))
            weather_row = cur.fetchone()
            weather = None if weather_row is None else dict(zip([desc[0] for desc in cur.description], weather_row))
    for driver in drivers:
        _clasificar_frescura_contexto(driver, "position", "position_age_seconds")
        _clasificar_frescura_contexto(driver, "interval", "interval_age_seconds")
    if weather is not None:
        _clasificar_frescura_contexto(weather, "weather", "weather_age_seconds")
    return {"drivers": drivers, "weather": weather}


def _clasificar_frescura_contexto(context: dict, name: str, age_key: str) -> None:
    """Marca la frescura de un contexto OpenF1 sin interpolar sus valores."""
    age_seconds = float(context[age_key]) if context.get(age_key) is not None else None
    context[f"{name}_freshness"] = (
        "unavailable" if age_seconds is None or age_seconds > 30
        else "aged" if age_seconds > 10
        else "current"
    )
    if context[f"{name}_freshness"] != "unavailable":
        return
    if name == "position":
        context["position"] = None
    elif name == "interval":
        context["gap_to_leader_seconds"] = None
        context["gap_to_leader_text"] = None
        context["interval_seconds"] = None
        context["interval_text"] = None
    elif name == "weather":
        context["air_temperature_c"] = None
        context["track_temperature_c"] = None
        context["rainfall"] = None
        context["humidity_percent"] = None


def obtener_ejecucion_por_huella(package_fingerprint: str) -> dict | None:
    """Busca una ejecucion previa para evitar importar dos veces el mismo paquete."""

    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT run_id, package_fingerprint, source_type, session_key, package_path,
                       processor_version, inventory, status, counts, started_at_utc,
                       completed_at_utc, error_summary
                FROM session_processing_runs
                WHERE package_fingerprint = %s
                """,
                (package_fingerprint,),
            )
            row = cur.fetchone()
            if row is None or cur.description is None:
                return None
            return dict(zip([description[0] for description in cur.description], row))


def crear_ejecucion_validada(
    package_fingerprint: str,
    source_type: str,
    session_key: int,
    package_path: str,
    processor_version: str,
    inventory: dict,
) -> dict | None:
    """Registra una validacion previa a la importacion real del paquete."""

    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO session_processing_runs (
                    package_fingerprint, source_type, session_key, package_path,
                    processor_version, inventory, status
                ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, 'validated')
                ON CONFLICT (package_fingerprint) DO NOTHING
                RETURNING run_id, package_fingerprint, status, session_key, inventory
                """,
                (
                    package_fingerprint,
                    source_type,
                    session_key,
                    package_path,
                    processor_version,
                    json.dumps(inventory),
                ),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return dict(zip([description[0] for description in cur.description], row))


def registrar_incidencia_procesamiento(
    run_id: int,
    severity: str,
    issue_code: str,
    message: str,
    file_path: str | None = None,
    context: dict | None = None,
) -> None:
    """Conserva advertencias y errores de una corrida sin ocultar su contexto."""

    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO session_processing_issues (
                    run_id, severity, issue_code, file_path, message, context
                ) VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                """,
                (run_id, severity, issue_code, file_path, message, json.dumps(context or {})),
            )


def actualizar_ejecucion_procesamiento(
    run_id: int, status: str, counts: dict, error_summary: str | None = None
) -> None:
    """Actualiza el estado y los conteos de una corrida de procesamiento."""

    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE session_processing_runs
                SET status = %s,
                    counts = %s::jsonb,
                    error_summary = %s,
                    completed_at_utc = CASE
                        WHEN %s IN ('completed', 'partial', 'failed') THEN NOW()
                        ELSE NULL
                    END
                WHERE run_id = %s
                """,
                (status, json.dumps(counts), error_summary, status, run_id),
            )


def listar_ejecuciones_procesamiento(limite: int = 50) -> list[dict]:
    """Lista corridas de procesamiento con inventario y conteos persistidos."""

    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT run_id, package_fingerprint, source_type, session_key,
                       package_path, processor_version, inventory, status, counts,
                       started_at_utc, completed_at_utc, error_summary
                FROM session_processing_runs
                ORDER BY started_at_utc DESC, run_id DESC
                LIMIT %s
                """,
                (limite,),
            )
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]


def obtener_ejecucion_procesamiento(run_id: int) -> dict | None:
    """Devuelve una corrida de procesamiento concreta."""

    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT run_id, package_fingerprint, source_type, session_key,
                       package_path, processor_version, inventory, status, counts,
                       started_at_utc, completed_at_utc, error_summary
                FROM session_processing_runs
                WHERE run_id = %s
                """,
                (run_id,),
            )
            row = cur.fetchone()
            if row is None or cur.description is None:
                return None
            return dict(zip([desc[0] for desc in cur.description], row))


def listar_incidencias_procesamiento(run_id: int) -> list[dict]:
    """Lista advertencias y errores registrados para una corrida."""

    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT issue_id, run_id, severity, issue_code, file_path, message,
                       context, created_at_utc
                FROM session_processing_issues
                WHERE run_id = %s
                ORDER BY issue_id
                """,
                (run_id,),
            )
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]
