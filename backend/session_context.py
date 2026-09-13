"""Importa contexto OpenF1 disponible desde un paquete local de sesion."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.db import obtener_conexion


BASE_URL = "https://api.openf1.org/v1"
CONTEXT_FILES = {
    "drivers": "drivers.json",
    "laps": "laps.json",
    "stints": "stints.json",
    "pit": "pit.json",
    "weather": "weather.json",
    "race_control": "race_control.json",
    "position": "position.json",
    "intervals": "intervals.json",
    "overtakes": "overtakes.json",
    "team_radio": "team_radio.json",
    "session_result": "session_result.json",
}


class SessionContextValidationError(ValueError):
    """Indica que un archivo de contexto disponible no tiene el formato esperado."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SessionContextValidationError(f"JSON de contexto invalido: {path.name}") from error


def load_available_context(package_path: str | Path) -> tuple[dict[str, Any], dict[str, list[dict]], list[str]]:
    """Lee solo contexto disponible y declara los archivos opcionales ausentes."""

    path = Path(package_path)
    session_path = path / "session.json"
    session = _read_json(session_path)
    if not isinstance(session, dict) or not isinstance(session.get("session_key"), int):
        raise SessionContextValidationError("session.json debe contener session_key entero.")
    datasets: dict[str, list[dict]] = {}
    missing: list[str] = []
    for name, filename in CONTEXT_FILES.items():
        file_path = path / filename
        if not file_path.is_file():
            missing.append(filename)
            continue
        payload = _read_json(file_path)
        if not isinstance(payload, list):
            raise SessionContextValidationError(f"{filename} debe contener una lista JSON.")
        datasets[name] = payload
    return session, datasets, missing


def _source_url(endpoint: str, session_key: int) -> str:
    return f"{BASE_URL}/{endpoint}?session_key={session_key}"


def _json(row: dict) -> str:
    return json.dumps(row, ensure_ascii=True)


def _numeric_or_text(value: Any) -> tuple[float | None, str | None]:
    return (float(value), None) if isinstance(value, (int, float)) else (None, value)


class PaqueteSinSesion(Exception):
    """Un paquete cuyo `session.json` no alcanza para registrar la sesion.

    Es una excepcion propia y no un `KeyError` porque **su mensaje esta escrito
    para que lo lea una persona**. El 2026-09-13 una subida termino mostrando
    «KeyError: 'meeting_key'» en pantalla: el nombre interno de una excepcion de
    Python, que no dice que archivo mirar, ni que hay tres campos obligatorios,
    ni por que lo son.
    """


#: LO QUE LA TABLA EXIGE, Y SALE DE LA TABLA. `racing_sessions` declara estos
#: tres `NOT NULL` ---ver `database/001_openf1_replay_metadata.sql`--- y por eso
#: se leen con indexado directo mientras todos los demas campos usan `.get()`:
#: el codigo espeja el esquema a proposito.
#:
#: NO ES LA MISMA LISTA QUE `CAMPOS_DE_UNA_SESION` de
#: `scripts/descargar_paquete_openf1.py`, y no tiene por que serlo: aquella
#: pregunta si el archivo **describe** una sesion; esta, si la tabla la puede
#: **aceptar**. Dos preguntas distintas con dos respuestas medidas cada una en
#: su sitio.
CAMPOS_QUE_LA_TABLA_EXIGE = ("meeting_key", "session_name", "session_type")


def import_available_context(package_path: str | Path, session: dict, datasets: dict[str, list[dict]]) -> dict[str, int]:
    """Inserta o actualiza contexto disponible sin requerir una sesion fija."""

    path = Path(package_path)
    faltan = [campo for campo in CAMPOS_QUE_LA_TABLA_EXIGE
              if session.get(campo) is None]
    if faltan:
        raise PaqueteSinSesion(
            "El `session.json` de %s no declara %s. La tabla de sesiones no "
            "acepta un nulo en esos campos: son los que identifican la sesion, "
            "y sin ellos no hay nada que registrar."
            % (path, ", ".join("`%s`" % c for c in faltan)))

    session_key = session["session_key"]
    retrieved_at = datetime.now(timezone.utc).isoformat()
    counts = {"sessions": 1, **{name: len(rows) for name, rows in datasets.items()}}
    with obtener_conexion() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO racing_sessions (meeting_key, session_key, source_type, session_name, session_type, circuit_key, circuit_short_name, country_name, location, date_start, date_end, source_url, raw_payload_path, retrieved_at_utc)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (session_key) DO UPDATE SET source_type=EXCLUDED.source_type, session_name=EXCLUDED.session_name, session_type=EXCLUDED.session_type, source_url=EXCLUDED.source_url, raw_payload_path=EXCLUDED.raw_payload_path, retrieved_at_utc=EXCLUDED.retrieved_at_utc""",
                (session["meeting_key"], session_key, "openf1_historical", session["session_name"], session["session_type"], session.get("circuit_key"), session.get("circuit_short_name"), session.get("country_name"), session.get("location"), session.get("date_start"), session.get("date_end"), _source_url("sessions", session_key), str(path / "session.json"), retrieved_at),
            )
            for row in datasets.get("drivers", []):
                cursor.execute("""INSERT INTO racing_drivers (session_key,driver_number,full_name,name_acronym,team_name,team_colour,source_url,raw_payload_path,retrieved_at_utc) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (session_key,driver_number) DO UPDATE SET full_name=EXCLUDED.full_name,name_acronym=EXCLUDED.name_acronym,team_name=EXCLUDED.team_name,team_colour=EXCLUDED.team_colour,retrieved_at_utc=EXCLUDED.retrieved_at_utc""", (session_key,row["driver_number"],row.get("full_name"),row.get("name_acronym"),row.get("team_name"),row.get("team_colour"),_source_url("drivers",session_key),str(path / "drivers.json"),retrieved_at))
            for row in datasets.get("laps", []):
                cursor.execute("""INSERT INTO racing_laps VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT (session_key,driver_number,lap_number) DO UPDATE SET raw_payload=EXCLUDED.raw_payload""", (session_key,row["driver_number"],row["lap_number"],row.get("date_start"),row.get("lap_duration"),row.get("duration_sector_1"),row.get("duration_sector_2"),row.get("duration_sector_3"),row.get("i1_speed"),row.get("i2_speed"),row.get("st_speed"),row.get("is_pit_out_lap"),_json(row)))
            for row in datasets.get("stints", []):
                cursor.execute("""INSERT INTO racing_stints VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT (session_key,driver_number,stint_number) DO UPDATE SET raw_payload=EXCLUDED.raw_payload""", (session_key,row["driver_number"],row["stint_number"],row.get("compound"),row.get("lap_start"),row.get("lap_end"),row.get("tyre_age_at_start"),_json(row)))
            for row in datasets.get("pit", []):
                cursor.execute("""INSERT INTO racing_pit_stops VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT (session_key,driver_number,date) DO UPDATE SET raw_payload=EXCLUDED.raw_payload""", (session_key,row["driver_number"],row["date"],row.get("lap_number"),row.get("lane_duration"),row.get("stop_duration"),_json(row)))
            for row in datasets.get("weather", []):
                cursor.execute("""INSERT INTO racing_weather VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT (session_key,date) DO UPDATE SET raw_payload=EXCLUDED.raw_payload""", (session_key,row["date"],row.get("air_temperature"),row.get("track_temperature"),bool(row["rainfall"]) if row.get("rainfall") is not None else None,row.get("humidity"),row.get("pressure"),row.get("wind_direction"),row.get("wind_speed"),_json(row)))
            cursor.execute("DELETE FROM racing_events WHERE session_key=%s AND event_type='race_control'", (session_key,))
            for row in datasets.get("race_control", []):
                cursor.execute("INSERT INTO racing_events (session_key,event_type,event_time,driver_number,lap_number,raw_payload) VALUES (%s,'race_control',%s,%s,%s,%s::jsonb)", (session_key,row["date"],row.get("driver_number"),row.get("lap_number"),_json(row)))
            for row in datasets.get("position", []):
                cursor.execute("""INSERT INTO racing_positions VALUES (%s,%s,%s,%s,%s::jsonb) ON CONFLICT (session_key,driver_number,date) DO UPDATE SET position=EXCLUDED.position,raw_payload=EXCLUDED.raw_payload""", (session_key,row["driver_number"],row["date"],row["position"],_json(row)))
            for row in datasets.get("intervals", []):
                leader_num, leader_text = _numeric_or_text(row.get("gap_to_leader")); interval_num, interval_text = _numeric_or_text(row.get("interval"))
                cursor.execute("""INSERT INTO racing_intervals VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT (session_key,driver_number,date) DO UPDATE SET gap_to_leader_seconds=EXCLUDED.gap_to_leader_seconds,gap_to_leader_text=EXCLUDED.gap_to_leader_text,interval_seconds=EXCLUDED.interval_seconds,interval_text=EXCLUDED.interval_text,raw_payload=EXCLUDED.raw_payload""", (session_key,row["driver_number"],row["date"],leader_num,leader_text,interval_num,interval_text,_json(row)))
            for row in datasets.get("overtakes", []):
                cursor.execute("""INSERT INTO racing_overtakes VALUES (%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT (session_key,date,overtaking_driver_number,overtaken_driver_number) DO UPDATE SET position=EXCLUDED.position,raw_payload=EXCLUDED.raw_payload""", (session_key,row["date"],row["overtaking_driver_number"],row["overtaken_driver_number"],row.get("position"),_json(row)))
            for row in datasets.get("team_radio", []):
                cursor.execute("""INSERT INTO racing_team_radio VALUES (%s,%s,%s,%s,%s::jsonb) ON CONFLICT (session_key,driver_number,date) DO UPDATE SET recording_url=EXCLUDED.recording_url,raw_payload=EXCLUDED.raw_payload""", (session_key,row["driver_number"],row["date"],row.get("recording_url"),_json(row)))
            for row in datasets.get("session_result", []):
                cursor.execute("""INSERT INTO racing_session_results VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT (session_key,driver_number) DO UPDATE SET position=EXCLUDED.position,points=EXCLUDED.points,number_of_laps=EXCLUDED.number_of_laps,duration_seconds=EXCLUDED.duration_seconds,gap_to_leader=EXCLUDED.gap_to_leader,dnf=EXCLUDED.dnf,dns=EXCLUDED.dns,dsq=EXCLUDED.dsq,raw_payload=EXCLUDED.raw_payload""", (session_key,row["driver_number"],row.get("position"),row.get("points"),row.get("number_of_laps"),row.get("duration"),str(row.get("gap_to_leader")) if row.get("gap_to_leader") is not None else None,row.get("dnf"),row.get("dns"),row.get("dsq"),_json(row)))
    return counts
