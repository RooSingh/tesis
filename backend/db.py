"""Acceso a TimescaleDB para el backend.

Este modulo centraliza inserciones y consultas sobre PostgreSQL/TimescaleDB. No
se utiliza ORM: se trabaja con SQL directo para mantener visibilidad y control
sobre el flujo real de persistencia.
"""

from __future__ import annotations

import json
import threading
from datetime import timedelta
from typing import Any

import psycopg

from backend.config import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER
from backend.models import TelemetryMessage, TelemetryMetadata


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


def _identidad_replay(metadata: TelemetryMetadata) -> tuple[str | None, int | None]:
    """Extrae la identidad de replay que habilita idempotencia y reconciliacion.

    El publicador inyecta `replay_run_id` y `replay_seq` en `metadata.extra`. Se
    promueven a columnas propias porque contar 6,2 millones de filas filtrando
    por un campo JSONB no es indexable de forma economica, y porque la clave de
    idempotencia debe poder expresarse como indice unico.

    Los mensajes que no provienen de un replay devuelven `(None, None)` y quedan
    fuera del indice unico parcial definido en `database/003_*.sql`.
    """
    extra = metadata.extra or {}
    replay_run_id = extra.get("replay_run_id")
    replay_seq = extra.get("replay_seq")
    if replay_run_id is None or replay_seq is None:
        return None, None
    return str(replay_run_id), int(replay_seq)


def _parametros_telemetria(mensaje: TelemetryMessage) -> dict[str, Any]:
    """Normaliza un mensaje para insercion individual o por lote."""
    value_numeric, value_boolean, value_text = _separar_valor(mensaje.value)
    metadata = mensaje.metadata
    replay_run_id, replay_seq = _identidad_replay(metadata)
    return {
        "replay_run_id": replay_run_id,
        "replay_seq": replay_seq,
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
        quality_flag, track_segment_id, sector_id, curve_id, can_id, src, metadata,
        replay_run_id, replay_seq
    ) VALUES (
        %(timestamp)s, %(vehicle_id)s, %(driver_id)s, %(session_id)s, %(lap_id)s,
        %(source_type)s, %(signal_name)s, %(value_numeric)s, %(value_boolean)s,
        %(value_text)s, %(unit)s, %(quality_flag)s, %(track_segment_id)s,
        %(sector_id)s, %(curve_id)s, %(can_id)s, %(src)s, %(metadata)s::jsonb,
        %(replay_run_id)s, %(replay_seq)s
    )
    ON CONFLICT (replay_run_id, replay_seq, timestamp)
        WHERE replay_run_id IS NOT NULL AND replay_seq IS NOT NULL
        DO NOTHING
"""


def _filas_insertadas(rowcount: int | None, esperadas: int) -> int:
    """Interpreta `cur.rowcount` de forma conservadora.

    psycopg 3 acumula en `rowcount` las filas afectadas por todo `executemany`.
    Con `ON CONFLICT DO NOTHING`, una fila duplicada no se cuenta: por eso el
    valor devuelto es persistencia real y no intencion. Si el driver no informa
    un valor utilizable se devuelve el esperado, porque suponer una perdida sin
    evidencia seria tan incorrecto como suponer un exito.
    """
    if rowcount is None or rowcount < 0:
        return esperadas
    return rowcount


def insertar_telemetria_lote(mensajes: list[TelemetryMessage]) -> int:
    """Persiste un lote en una sola conexion/transaccion de PostgreSQL.

    Devuelve las filas realmente insertadas segun `cur.rowcount`, no la cantidad
    de mensajes recibidos. La diferencia entre ambos numeros es exactamente la
    cantidad de duplicados suprimidos por `ON CONFLICT DO NOTHING`.
    """
    if not mensajes:
        return 0
    parametros = [_parametros_telemetria(mensaje) for mensaje in mensajes]
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.executemany(INSERT_TELEMETRY_SQL, parametros)
            insertadas = cur.rowcount
    return _filas_insertadas(insertadas, len(mensajes))


class EscritorTelemetria:
    """Persiste lotes reutilizando una unica conexion PostgreSQL.

    El consumidor abria una conexion nueva por lote. Para la carrera completa de
    Silverstone eso equivale a unos 6.218 handshakes TCP y de autenticacion. Esta
    clase conserva la conexion entre lotes y la reabre solo despues de un error.

    Es intencional que un fallo cierre la conexion y vuelva a lanzar la
    excepcion: `TelemetryBatchBuffer.flush` reencola el lote completo, de modo que
    ningun mensaje se pierde por un corte transitorio de base de datos.
    """

    def __init__(self, conexion_factory=obtener_conexion) -> None:
        self.conexion_factory = conexion_factory
        self.lock = threading.Lock()
        self._conexion: psycopg.Connection | None = None

    def _conexion_activa(self) -> psycopg.Connection:
        if self._conexion is None or self._conexion.closed:
            self._conexion = self.conexion_factory()
        return self._conexion

    def __call__(self, mensajes: list[TelemetryMessage]) -> int:
        if not mensajes:
            return 0
        parametros = [_parametros_telemetria(mensaje) for mensaje in mensajes]
        with self.lock:
            try:
                conn = self._conexion_activa()
                with conn.transaction():
                    with conn.cursor() as cur:
                        cur.executemany(INSERT_TELEMETRY_SQL, parametros)
                        insertadas = cur.rowcount
            except Exception:
                self._cerrar_sin_bloquear()
                raise
        return _filas_insertadas(insertadas, len(mensajes))

    def _cerrar_sin_bloquear(self) -> None:
        if self._conexion is not None:
            try:
                self._conexion.close()
            except Exception:
                pass
            self._conexion = None

    def cerrar(self) -> None:
        """Libera la conexion al terminar un proceso consumidor."""
        with self.lock:
            self._cerrar_sin_bloquear()


CONTAR_REPLAY_SQL = """
    SELECT
        count(*) AS filas,
        count(DISTINCT replay_seq) AS unicos,
        min(replay_seq) AS seq_min,
        max(replay_seq) AS seq_max
    FROM telemetry_messages
    WHERE replay_run_id = %(replay_run_id)s
      AND (%(seq_desde)s::bigint IS NULL OR replay_seq >= %(seq_desde)s::bigint)
      AND (%(seq_hasta)s::bigint IS NULL OR replay_seq <= %(seq_hasta)s::bigint)
"""


def contar_replay_persistido(
    replay_run_id: str,
    seq_desde: int | None = None,
    seq_hasta: int | None = None,
) -> dict[str, int | None]:
    """Cuenta filas reales de un replay para reconciliar un bloque.

    Es la unica fuente de verdad admitida para cerrar un bloque: las metricas del
    publicador y del consumidor pueden coincidir entre si y aun asi no
    corresponder a lo persistido.

    `unicos` permite detectar duplicados sin recorrer las filas: si `filas` y
    `unicos` difieren, hay repeticiones que el indice unico deberia haber
    impedido.
    """
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                CONTAR_REPLAY_SQL,
                {
                    "replay_run_id": replay_run_id,
                    "seq_desde": seq_desde,
                    "seq_hasta": seq_hasta,
                },
            )
            fila = cur.fetchone()
    if fila is None:
        return {"filas": 0, "unicos": 0, "seq_min": None, "seq_max": None}
    return {"filas": fila[0], "unicos": fila[1], "seq_min": fila[2], "seq_max": fila[3]}


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


# ---------------------------------------------------------------------------
# Derivacion de ventanas de vuelta y stint sobre telemetria OpenF1
#
# Agregado el 2026-08-27. Permite recortar la telemetria del replay por vuelta o
# por stint sin escribir esa asignacion en `telemetry_messages`.
#
# Por que la asignacion no se persiste: atribuir una vuelta a una muestra es una
# derivacion, no un dato observado. La columna `lap_id` existe y el adaptador
# OpenF1 la deja deliberadamente en NULL. Escribir alli el resultado volveria la
# derivacion indistinguible del origen y la congelaria: si mas adelante se
# corrigen los limites de vuelta, la columna quedaria desactualizada sin aviso.
# Derivar en la consulta mantiene la separacion y permite devolver la ventana
# empleada junto con los datos.
# ---------------------------------------------------------------------------

SOURCE_TYPE_REPLAY_OPENF1 = "openf1_historical_replay"


def identificadores_openf1(session_key: int, driver_number: int) -> tuple[str, str]:
    """Construye los identificadores canonicos que usa el adaptador OpenF1."""
    return f"openf1:session:{session_key}", f"openf1:driver:{driver_number}"


def obtener_vueltas_piloto(session_key: int, driver_number: int) -> list[dict]:
    """Devuelve las vueltas de un piloto ordenadas por numero.

    Son unas decenas de filas por piloto, de modo que traerlas completas y
    calcular las ventanas en Python resulta mas barato y mucho mas auditable que
    resolver el limite dentro de una consulta sobre millones de muestras.
    """
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT lap_number, date_start, lap_duration_seconds
                FROM racing_laps
                WHERE session_key = %s AND driver_number = %s
                ORDER BY lap_number
                """,
                (session_key, driver_number),
            )
            columnas = [desc[0] for desc in cur.description]
            return [dict(zip(columnas, fila)) for fila in cur.fetchall()]


def calcular_ventanas_vueltas(vueltas: list[dict]) -> list[dict]:
    """Calcula la ventana `[inicio, fin)` de cada vuelta. Funcion pura.

    Regla adoptada: **el fin de una vuelta es el inicio de la siguiente**, y no
    `date_start + lap_duration_seconds`.

    El motivo es empirico. Sobre las 827 vueltas de Silverstone `9947`, 25 vueltas
    presentan una discrepancia mayor a medio segundo entre la duracion declarada y
    el inicio de la vuelta siguiente, con un maximo de 11,802 segundos, y 5 vueltas
    carecen de duracion. Cerrar por duracion dejaria huecos y solapamientos de
    varios segundos, que a 3,7 Hz por senal y con veinte pilotos equivalen a miles
    de muestras asignadas a ninguna vuelta o a dos.

    Tomar el inicio de la siguiente garantiza una particion sin huecos ni
    solapamientos por construccion.

    Excepciones, ambas marcadas en el resultado:

    - la ultima vuelta de un piloto no tiene siguiente: se cierra con la duracion
      declarada y se marca `fin_estimado`;
    - si la numeracion salta, la vuelta posterior no es contigua y no puede usarse
      como limite: se recurre tambien a la duracion y se marca `fin_estimado`.

    Cuando no hay forma de determinar el fin, la ventana se devuelve con
    `fin = None` y `completa = False`, en vez de inventar un limite.
    """
    ventanas = []
    for indice, vuelta in enumerate(vueltas):
        inicio = vuelta["date_start"]
        siguiente = vueltas[indice + 1] if indice + 1 < len(vueltas) else None
        contigua = (
            siguiente is not None
            and siguiente["date_start"] is not None
            and siguiente["lap_number"] == vuelta["lap_number"] + 1
        )

        if inicio is None:
            fin, estimado = None, False
        elif contigua:
            fin, estimado = siguiente["date_start"], False
        elif vuelta["lap_duration_seconds"] is not None:
            fin = inicio + timedelta(seconds=float(vuelta["lap_duration_seconds"]))
            estimado = True
        else:
            fin, estimado = None, False

        ventanas.append({
            "lap_number": vuelta["lap_number"],
            "inicio": inicio,
            "fin": fin,
            "fin_estimado": estimado,
            "completa": inicio is not None and fin is not None,
        })
    return ventanas


def resolver_ventana_vuelta(session_key: int, driver_number: int, lap_number: int) -> dict | None:
    """Devuelve la ventana temporal de una vuelta concreta, o None si no existe."""
    ventanas = calcular_ventanas_vueltas(obtener_vueltas_piloto(session_key, driver_number))
    for ventana in ventanas:
        if ventana["lap_number"] == lap_number:
            return ventana
    return None


def resolver_ventana_stint(session_key: int, driver_number: int, stint_number: int) -> dict | None:
    """Devuelve la ventana temporal de un stint, compuesta desde sus vueltas.

    El stint declara `lap_start` y `lap_end`, de modo que su ventana va del inicio
    de la primera vuelta al fin de la ultima. Se reutiliza el mismo criterio de
    limites que las vueltas, para que ambos recortes sean consistentes entre si.
    """
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT stint_number, compound, lap_start, lap_end, tyre_age_at_start
                FROM racing_stints
                WHERE session_key = %s AND driver_number = %s AND stint_number = %s
                """,
                (session_key, driver_number, stint_number),
            )
            fila = cur.fetchone()
            if fila is None:
                return None
            columnas = [desc[0] for desc in cur.description]
            stint = dict(zip(columnas, fila))

    ventanas = {v["lap_number"]: v for v in calcular_ventanas_vueltas(obtener_vueltas_piloto(session_key, driver_number))}
    primera = ventanas.get(stint["lap_start"])
    ultima = ventanas.get(stint["lap_end"])
    if primera is None or ultima is None:
        return None

    return {
        "stint_number": stint["stint_number"],
        "compound": stint["compound"],
        "lap_start": stint["lap_start"],
        "lap_end": stint["lap_end"],
        "tyre_age_at_start": stint["tyre_age_at_start"],
        "inicio": primera["inicio"],
        "fin": ultima["fin"],
        "fin_estimado": ultima["fin_estimado"],
        "completa": primera["inicio"] is not None and ultima["fin"] is not None,
    }


def obtener_telemetria_en_ventana(
    session_key: int,
    driver_number: int,
    inicio,
    fin,
    signal_name: str | None = None,
    replay_run_id: str | None = None,
    limite: int = 5000,
) -> list[dict]:
    """Devuelve la telemetria de replay contenida en una ventana temporal.

    El filtro se ordena para aprovechar
    `telemetry_messages_source_session_driver_timestamp_idx`, que indexa
    `(source_type, session_id, driver_id, timestamp)`: los tres primeros campos se
    fijan por igualdad y el cuarto se recorre por rango, que es el caso optimo de
    un B-tree. Por eso no se resuelve el limite de vuelta con un join contra la
    tabla de telemetria.

    El intervalo es `[inicio, fin)`, cerrado al comienzo y abierto al final, de
    modo que una muestra situada justo en el limite pertenece a una sola vuelta.
    """
    session_id, driver_id = identificadores_openf1(session_key, driver_number)
    condiciones = [
        "source_type = %(source_type)s",
        "session_id = %(session_id)s",
        "driver_id = %(driver_id)s",
        "timestamp >= %(inicio)s",
    ]
    parametros = {
        "source_type": SOURCE_TYPE_REPLAY_OPENF1,
        "session_id": session_id,
        "driver_id": driver_id,
        "inicio": inicio,
        "fin": fin,
        "signal_name": signal_name,
        "replay_run_id": replay_run_id,
        "limite": limite,
    }
    if fin is not None:
        condiciones.append("timestamp < %(fin)s")
    if signal_name is not None:
        condiciones.append("signal_name = %(signal_name)s")
    if replay_run_id is not None:
        condiciones.append("replay_run_id = %(replay_run_id)s")

    consulta = f"""
        SELECT timestamp, driver_id, signal_name, value_numeric, value_boolean,
               value_text, unit, quality_flag, replay_run_id, replay_seq
        FROM telemetry_messages
        WHERE {' AND '.join(condiciones)}
        ORDER BY timestamp, signal_name
        LIMIT %(limite)s
    """
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(consulta, parametros)
            columnas = [desc[0] for desc in cur.description]
            return [dict(zip(columnas, fila)) for fila in cur.fetchall()]
