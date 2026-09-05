"""Carga contexto OpenF1 crudo en las tablas racing_* de forma idempotente."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.db import obtener_conexion


#: Sesion por defecto, la primera que se cargo. Se conserva para que las
#: invocaciones anteriores sigan funcionando igual.
RAW_PATH = ROOT / "datasets" / "OpenF1" / "raw" / "2025" / "9947"
BASE_URL = "https://api.openf1.org/v1"


def read_rows(filename: str) -> list[dict[str, Any]]:
    """Lee una respuesta OpenF1 local y exige el formato de lista esperado."""
    payload = json.loads((RAW_PATH / filename).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{filename} no contiene una lista JSON.")
    return payload


def read_object(filename: str) -> dict[str, Any]:
    """Lee el objeto unico de sesion o meeting preservado durante la descarga."""
    payload = json.loads((RAW_PATH / filename).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{filename} no contiene un objeto JSON.")
    return payload


def source_url(endpoint: str, session_key: int) -> str:
    return f"{BASE_URL}/{endpoint}?session_key={session_key}"


def as_json(row: dict[str, Any]) -> str:
    return json.dumps(row, ensure_ascii=True)


def as_float_or_text(value: Any) -> tuple[float | None, str | None]:
    """Conserva gaps numericos o etiquetas como '+1 LAP' sin inventar conversion."""
    return (float(value), None) if isinstance(value, (int, float)) else (None, value)


def load_context() -> dict[str, int]:
    """Inserta o actualiza contexto Silverstone sin publicar MQTT."""
    session = read_object("session.json")
    drivers = read_rows("drivers.json")
    datasets = {name: read_rows(f"{name}.json") for name in (
        "laps", "stints", "pit", "weather", "race_control", "position",
        "intervals", "overtakes", "team_radio", "session_result",
    )}
    session_key = session["session_key"]
    retrieved_at = datetime.now(timezone.utc).isoformat()
    counts = {"sessions": 0, "drivers": 0, **{name: 0 for name in datasets}}

    with obtener_conexion() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO racing_sessions (
                    meeting_key, session_key, source_type, session_name, session_type,
                    circuit_key, circuit_short_name, country_name, location, date_start,
                    date_end, source_url, raw_payload_path, retrieved_at_utc
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (session_key) DO UPDATE SET
                    source_type = EXCLUDED.source_type,
                    session_name = EXCLUDED.session_name,
                    session_type = EXCLUDED.session_type,
                    source_url = EXCLUDED.source_url,
                    raw_payload_path = EXCLUDED.raw_payload_path,
                    retrieved_at_utc = EXCLUDED.retrieved_at_utc
                """,
                (session["meeting_key"], session_key, "openf1_historical", session["session_name"], session["session_type"], session.get("circuit_key"), session.get("circuit_short_name"), session.get("country_name"), session.get("location"), session.get("date_start"), session.get("date_end"), source_url("sessions", session_key), str(RAW_PATH / "session.json"), retrieved_at),
            )
            counts["sessions"] = 1
            for row in drivers:
                cursor.execute(
                    """INSERT INTO racing_drivers (session_key, driver_number, full_name, name_acronym, team_name, team_colour, source_url, raw_payload_path, retrieved_at_utc)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (session_key, driver_number) DO UPDATE SET full_name = EXCLUDED.full_name, name_acronym = EXCLUDED.name_acronym, team_name = EXCLUDED.team_name, team_colour = EXCLUDED.team_colour, retrieved_at_utc = EXCLUDED.retrieved_at_utc""",
                    (session_key, row["driver_number"], row.get("full_name"), row.get("name_acronym"), row.get("team_name"), row.get("team_colour"), source_url("drivers", session_key), str(RAW_PATH / "drivers.json"), retrieved_at),
                )
                counts["drivers"] += 1
            for row in datasets["laps"]:
                cursor.execute("""INSERT INTO racing_laps VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (session_key, driver_number, lap_number) DO UPDATE SET raw_payload = EXCLUDED.raw_payload""", (session_key, row["driver_number"], row["lap_number"], row.get("date_start"), row.get("lap_duration"), row.get("duration_sector_1"), row.get("duration_sector_2"), row.get("duration_sector_3"), row.get("i1_speed"), row.get("i2_speed"), row.get("st_speed"), row.get("is_pit_out_lap"), as_json(row)))
                counts["laps"] += 1
            for row in datasets["stints"]:
                cursor.execute("""INSERT INTO racing_stints VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (session_key, driver_number, stint_number) DO UPDATE SET raw_payload = EXCLUDED.raw_payload""", (session_key, row["driver_number"], row["stint_number"], row.get("compound"), row.get("lap_start"), row.get("lap_end"), row.get("tyre_age_at_start"), as_json(row)))
                counts["stints"] += 1
            for row in datasets["pit"]:
                cursor.execute("""INSERT INTO racing_pit_stops VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (session_key, driver_number, date) DO UPDATE SET raw_payload = EXCLUDED.raw_payload""", (session_key, row["driver_number"], row["date"], row.get("lap_number"), row.get("lane_duration"), row.get("stop_duration"), as_json(row)))
                counts["pit"] += 1
            for row in datasets["weather"]:
                cursor.execute("""INSERT INTO racing_weather VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (session_key, date) DO UPDATE SET raw_payload = EXCLUDED.raw_payload""", (session_key, row["date"], row.get("air_temperature"), row.get("track_temperature"), bool(row["rainfall"]) if row.get("rainfall") is not None else None, row.get("humidity"), row.get("pressure"), row.get("wind_direction"), row.get("wind_speed"), as_json(row)))
                counts["weather"] += 1
            # racing_events has a surrogate key, so replace this source slice before reload.
            cursor.execute(
                "DELETE FROM racing_events WHERE session_key = %s AND event_type = %s",
                (session_key, "race_control"),
            )
            for row in datasets["race_control"]:
                cursor.execute("""INSERT INTO racing_events (session_key, event_type, event_time, driver_number, lap_number, raw_payload)
                VALUES (%s,%s,%s,%s,%s,%s::jsonb)""", (session_key, "race_control", row["date"], row.get("driver_number"), row.get("lap_number"), as_json(row)))
                counts["race_control"] += 1
            for row in datasets["position"]:
                cursor.execute("""INSERT INTO racing_positions VALUES (%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (session_key, driver_number, date) DO UPDATE SET position = EXCLUDED.position, raw_payload = EXCLUDED.raw_payload""", (session_key, row["driver_number"], row["date"], row["position"], as_json(row)))
                counts["position"] += 1
            for row in datasets["intervals"]:
                leader_num, leader_text = as_float_or_text(row.get("gap_to_leader"))
                interval_num, interval_text = as_float_or_text(row.get("interval"))
                cursor.execute("""INSERT INTO racing_intervals VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (session_key, driver_number, date) DO UPDATE SET gap_to_leader_seconds = EXCLUDED.gap_to_leader_seconds, gap_to_leader_text = EXCLUDED.gap_to_leader_text, interval_seconds = EXCLUDED.interval_seconds, interval_text = EXCLUDED.interval_text, raw_payload = EXCLUDED.raw_payload""", (session_key, row["driver_number"], row["date"], leader_num, leader_text, interval_num, interval_text, as_json(row)))
                counts["intervals"] += 1
            for row in datasets["overtakes"]:
                cursor.execute("""INSERT INTO racing_overtakes VALUES (%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (session_key, date, overtaking_driver_number, overtaken_driver_number) DO UPDATE SET position = EXCLUDED.position, raw_payload = EXCLUDED.raw_payload""", (session_key, row["date"], row["overtaking_driver_number"], row["overtaken_driver_number"], row.get("position"), as_json(row)))
                counts["overtakes"] += 1
            for row in datasets["team_radio"]:
                cursor.execute("""INSERT INTO racing_team_radio VALUES (%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (session_key, driver_number, date) DO UPDATE SET recording_url = EXCLUDED.recording_url, raw_payload = EXCLUDED.raw_payload""", (session_key, row["driver_number"], row["date"], row.get("recording_url"), as_json(row)))
                counts["team_radio"] += 1
            for row in datasets["session_result"]:
                cursor.execute("""INSERT INTO racing_session_results VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (session_key, driver_number) DO UPDATE SET position = EXCLUDED.position, points = EXCLUDED.points, number_of_laps = EXCLUDED.number_of_laps, duration_seconds = EXCLUDED.duration_seconds, gap_to_leader = EXCLUDED.gap_to_leader, dnf = EXCLUDED.dnf, dns = EXCLUDED.dns, dsq = EXCLUDED.dsq, raw_payload = EXCLUDED.raw_payload""", (session_key, row["driver_number"], row.get("position"), row.get("points"), row.get("number_of_laps"), row.get("duration"), str(row.get("gap_to_leader")) if row.get("gap_to_leader") is not None else None, row.get("dnf"), row.get("dns"), row.get("dsq"), as_json(row)))
                counts["session_result"] += 1
    return counts


def main() -> None:
    global RAW_PATH
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Realiza las inserciones; sin este flag solo valida archivos.")
    parser.add_argument("--session-path", type=Path, default=None,
                        help="Directorio crudo de la sesion. Por defecto, la primera cargada.")
    args = parser.parse_args()
    if args.session_path is not None:
        RAW_PATH = args.session_path.resolve()
    if not args.apply:
        for filename in ("session.json", "drivers.json", "laps.json", "stints.json", "pit.json", "weather.json", "race_control.json", "position.json", "intervals.json", "overtakes.json", "team_radio.json", "session_result.json"):
            if not (RAW_PATH / filename).is_file():
                raise FileNotFoundError(RAW_PATH / filename)
        print("validation_ok=all_required_raw_files_present")
        return
    print(json.dumps(load_context(), sort_keys=True))


if __name__ == "__main__":
    main()
