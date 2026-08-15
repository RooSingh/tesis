"""Recolecta una matriz reproducible de sesiones Race y Sprint de OpenF1.

Guarda las respuestas crudas fuera de Git y calcula indicadores comparables para
seleccionar un evento historico. No descarga car_data/location ni escribe en la
base de datos: esos endpoints se reservan para el evento finalista.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "datasets" / "OpenF1"
BASE_URL = "https://api.openf1.org/v1"
ENDPOINTS = ("drivers", "laps", "stints", "pit", "race_control", "weather", "session_result")
TARGET_SESSIONS = {"Race", "Sprint"}
WEIGHTS = {
    "strategy": 0.30,
    "climate_thermal": 0.25,
    "incidents_circuit": 0.20,
    "completeness": 0.15,
    "sprint_race": 0.10,
}


class OpenF1Client:
    """Cliente conservador que deja trazabilidad de cada respuesta y error."""

    def __init__(self, minimum_interval: float, retries: int) -> None:
        self.minimum_interval = minimum_interval
        self.retries = retries
        self.last_request_at = 0.0

    def fetch(self, endpoint: str, params: dict[str, int]) -> tuple[list[dict] | None, dict]:
        elapsed = time.monotonic() - self.last_request_at
        if elapsed < self.minimum_interval:
            time.sleep(self.minimum_interval - elapsed)

        url = f"{BASE_URL}/{endpoint}?{urlencode(params)}"
        for attempt in range(1, self.retries + 2):
            requested_at = datetime.now(timezone.utc).isoformat()
            try:
                request = Request(url, headers={"User-Agent": "tesis-openf1-day18/1.0"})
                with urlopen(request, timeout=60) as response:
                    body = response.read()
                    status = response.status
                self.last_request_at = time.monotonic()
                payload = json.loads(body)
                if not isinstance(payload, list):
                    raise ValueError("OpenF1 no devolvio una lista JSON.")
                return payload, {
                    "endpoint": endpoint,
                    "params": params,
                    "url": url,
                    "requested_at_utc": requested_at,
                    "status": status,
                    "attempt": attempt,
                    "rows": len(payload),
                    "error": None,
                }
            except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as error:
                self.last_request_at = time.monotonic()
                if attempt == self.retries + 1:
                    return None, {
                        "endpoint": endpoint,
                        "params": params,
                        "url": url,
                        "requested_at_utc": requested_at,
                        "status": getattr(error, "code", None),
                        "attempt": attempt,
                        "rows": None,
                        "error": str(error),
                    }
                time.sleep(attempt)
        raise RuntimeError("Bucle de reintentos inesperado.")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True), encoding="utf-8")


def read_cached_payload(path: Path, endpoint: str, params: dict[str, int]) -> tuple[list[dict] | None, dict | None]:
    """Recupera una respuesta cruda valida para reanudar una ejecucion interrumpida."""
    if not path.is_file():
        return None, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            return None, None
    except (OSError, json.JSONDecodeError):
        return None, None
    return payload, {
        "endpoint": endpoint,
        "params": params,
        "url": f"{BASE_URL}/{endpoint}?{urlencode(params)}",
        "requested_at_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        "status": "cached",
        "attempt": 0,
        "rows": len(payload),
        "error": None,
    }


def text_of(record: dict) -> str:
    """Normaliza el texto de control de carrera sin depender de un campo unico."""
    return " ".join(str(value) for value in record.values() if value is not None).upper()


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * fraction)
    return ordered[index]


def normalize(values: list[float | None]) -> list[float | None]:
    """Escala indicadores al rango 0..1, sin convertir ausencia de datos en cero."""
    present = [value for value in values if value is not None]
    if not present:
        return [None] * len(values)
    lower, upper = min(present), max(present)
    if lower == upper:
        return [1.0 if value is not None else None for value in values]
    return [None if value is None else (value - lower) / (upper - lower) for value in values]


def mean_present(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return round(statistics.mean(present), 6) if present else None


def session_summary(session: dict, data: dict[str, list[dict] | None], requests: dict[str, dict]) -> dict:
    """Extrae indicadores observables; el puntaje se calcula despues entre eventos."""
    drivers = data["drivers"] or []
    stints = data["stints"] or []
    pits = data["pit"] or []
    weather = data["weather"] or []
    race_control = data["race_control"] or []
    results = data["session_result"] or []

    sequences: dict[int, list[str]] = {}
    compounds = set()
    for stint in sorted(stints, key=lambda row: (row.get("driver_number", -1), row.get("stint_number", -1))):
        driver = stint.get("driver_number")
        compound = stint.get("compound")
        if driver is None or not compound:
            continue
        sequences.setdefault(driver, []).append(str(compound).upper())
        compounds.add(str(compound).upper())
    strategy_sequences = {tuple(sequence) for sequence in sequences.values()}

    rain_values = [row.get("rainfall") for row in weather if row.get("rainfall") is not None]
    track_temperatures = [float(row["track_temperature"]) for row in weather if row.get("track_temperature") is not None]
    control_text = [text_of(row) for row in race_control]
    safety_car = sum("SAFETY CAR" in row or "VSC" in row for row in control_text)
    flags = sum(any(flag in row for flag in ("YELLOW", "RED FLAG", "DOUBLE YELLOW")) for row in control_text)
    dnf = sum(str(row.get("status", "")).upper() in {"DNF", "DNS", "DSQ"} for row in results)
    successful_endpoints = sum(request["error"] is None for request in requests.values())

    return {
        "session_key": session["session_key"],
        "session_name": session["session_name"],
        "drivers": len(drivers),
        "laps": len(data["laps"] or []),
        "stints": len(stints),
        "pit_events": len(pits),
        "unique_compounds": len(compounds),
        "unique_driver_strategies": len(strategy_sequences),
        "driver_strategy_diversity": round(len(strategy_sequences) / len(sequences), 6) if sequences else None,
        "pit_events_per_driver": round(len(pits) / len(drivers), 6) if drivers else None,
        "rainfall_sample_fraction": round(sum(bool(value) for value in rain_values) / len(rain_values), 6) if rain_values else None,
        "track_temperature_max_c": round(max(track_temperatures), 3) if track_temperatures else None,
        "track_temperature_range_c": round(max(track_temperatures) - min(track_temperatures), 3) if track_temperatures else None,
        "safety_car_or_vsc_messages": safety_car,
        "yellow_or_red_flag_messages": flags,
        "dnf_dns_or_dsq": dnf,
        "successful_endpoints": successful_endpoints,
        "endpoint_count": len(ENDPOINTS),
    }


def meeting_summary(meeting: dict, sessions: list[dict]) -> dict:
    race = next((row for row in sessions if row["session_name"] == "Race"), None)
    sprint = next((row for row in sessions if row["session_name"] == "Sprint"), None)
    primary = race or sprint
    if primary is None:
        raise ValueError("El meeting no contiene Race ni Sprint.")
    return {
        "meeting_key": meeting["meeting_key"],
        "meeting_name": meeting.get("meeting_name"),
        "location": meeting.get("location"),
        "country_name": meeting.get("country_name"),
        "circuit_short_name": meeting.get("circuit_short_name"),
        "race": race,
        "sprint": sprint,
        "has_race_and_sprint": race is not None and sprint is not None,
        "primary_session": primary["session_name"],
    }


def score_meetings(meetings: list[dict]) -> None:
    """Normaliza por temporada para que el clima no use umbrales fijos arbitrarios."""
    primary = [row["race"] or row["sprint"] for row in meetings]
    strategy = [
        mean_present([row["driver_strategy_diversity"], row["pit_events_per_driver"], row["unique_compounds"]])
        for row in primary
    ]
    climate = [
        mean_present([row["rainfall_sample_fraction"], row["track_temperature_max_c"], row["track_temperature_range_c"]])
        for row in primary
    ]
    incidents = [
        float(row["safety_car_or_vsc_messages"] + row["yellow_or_red_flag_messages"] + row["dnf_dns_or_dsq"])
        for row in primary
    ]
    completeness = [row["successful_endpoints"] / row["endpoint_count"] for row in primary]
    sprint_race = [1.0 if row["has_race_and_sprint"] else 0.0 for row in meetings]

    # Cada subindicador se normaliza primero para impedir que grados Celsius o
    # numero de mensajes domine a los restantes por su escala numerica.
    strategy_components = list(zip(
        normalize([row["driver_strategy_diversity"] for row in primary]),
        normalize([row["pit_events_per_driver"] for row in primary]),
        normalize([float(row["unique_compounds"]) for row in primary]),
    ))
    climate_components = list(zip(
        normalize([row["rainfall_sample_fraction"] for row in primary]),
        normalize([row["track_temperature_max_c"] for row in primary]),
        normalize([row["track_temperature_range_c"] for row in primary]),
    ))
    normalized_incidents = normalize(incidents)
    normalized_completeness = normalize(completeness)

    for index, meeting in enumerate(meetings):
        strategy_score = mean_present(list(strategy_components[index]))
        climate_score = mean_present(list(climate_components[index]))
        incident_score = normalized_incidents[index]
        completeness_score = normalized_completeness[index]
        sprint_score = sprint_race[index]
        weighted = sum(
            weight * score
            for weight, score in (
                (WEIGHTS["strategy"], strategy_score),
                (WEIGHTS["climate_thermal"], climate_score),
                (WEIGHTS["incidents_circuit"], incident_score),
                (WEIGHTS["completeness"], completeness_score),
                (WEIGHTS["sprint_race"], sprint_score),
            )
            if score is not None
        )
        available_weight = sum(
            weight
            for weight, score in (
                (WEIGHTS["strategy"], strategy_score),
                (WEIGHTS["climate_thermal"], climate_score),
                (WEIGHTS["incidents_circuit"], incident_score),
                (WEIGHTS["completeness"], completeness_score),
                (WEIGHTS["sprint_race"], sprint_score),
            )
            if score is not None
        )
        meeting["scores"] = {
            "strategy": strategy_score,
            "climate_thermal": climate_score,
            "incidents_observed": incident_score,
            "completeness": completeness_score,
            "sprint_race": sprint_score,
            "weighted_score": round(weighted / available_weight * 100, 3) if available_weight else None,
            "available_weight": round(available_weight, 3),
        }


def write_csv(path: Path, meetings: list[dict]) -> None:
    fields = ["rank", "meeting_key", "meeting_name", "circuit_short_name", "primary_session", "has_race_and_sprint", "weighted_score", "strategy", "climate_thermal", "incidents_observed", "completeness", "sprint_race"]
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(meetings, key=lambda row: row["scores"]["weighted_score"] or -1, reverse=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for rank, meeting in enumerate(ordered, start=1):
            scores = meeting["scores"]
            writer.writerow(
                {
                    field: rank if field == "rank" else scores.get(field, meeting.get(field))
                    for field in fields
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--minimum-interval", type=float, default=0.5)
    parser.add_argument("--retries", type=int, default=2)
    args = parser.parse_args()
    if args.minimum_interval <= 0:
        parser.error("--minimum-interval debe ser mayor que cero.")

    raw_root = args.output_root / "raw" / str(args.year)
    summary_root = args.output_root / "summaries" / f"day18_event_matrix_{args.year}"
    client = OpenF1Client(args.minimum_interval, args.retries)
    started_at = datetime.now(timezone.utc).isoformat()
    all_sessions, session_request = client.fetch("sessions", {"year": args.year})
    if all_sessions is None:
        raise RuntimeError(f"No se pudo obtener el catalogo de sesiones: {session_request['error']}")

    selected = [session for session in all_sessions if session.get("session_name") in TARGET_SESSIONS]
    selected.sort(key=lambda row: (row["meeting_key"], row["date_start"], row["session_key"]))
    by_meeting: dict[int, list[dict]] = {}
    manifests = [session_request]
    for session in selected:
        session_key = session["session_key"]
        data: dict[str, list[dict] | None] = {}
        request_log: dict[str, dict] = {}
        for endpoint in ENDPOINTS:
            params = {"session_key": session_key}
            payload, request = read_cached_payload(raw_root / str(session_key) / f"{endpoint}.json", endpoint, params)
            if request is None:
                payload, request = client.fetch(endpoint, params)
            data[endpoint] = payload
            request_log[endpoint] = request
            manifests.append(request)
            if payload is not None:
                write_json(raw_root / str(session_key) / f"{endpoint}.json", payload)
        write_json(raw_root / str(session_key) / "session.json", session)
        by_meeting.setdefault(session["meeting_key"], []).append(session_summary(session, data, request_log))
        print(f"collected=session_key={session_key} name={session['session_name']}")

    meetings_by_key = {session["meeting_key"]: session for session in selected}
    meetings = [meeting_summary(meetings_by_key[key], rows) for key, rows in sorted(by_meeting.items())]
    score_meetings(meetings)
    ordered = sorted(meetings, key=lambda row: row["scores"]["weighted_score"] or -1, reverse=True)
    output = {
        "run": {
            "started_at_utc": started_at,
            "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            "year": args.year,
            "base_url": BASE_URL,
            "minimum_interval_seconds": args.minimum_interval,
            "retries": args.retries,
        },
        "scope": {
            "included_sessions": sorted(TARGET_SESSIONS),
            "excluded_endpoints": ["car_data", "location"],
            "persistence": "raw JSON and summaries only; no TimescaleDB writes",
            "source_limit": "OpenF1 is processed racing data, not raw CAN or FIA timing data.",
        },
        "weights": WEIGHTS,
        "requests": manifests,
        "meetings_ranked": ordered,
    }
    write_json(summary_root / "event_matrix.json", output)
    write_csv(summary_root / "event_matrix.csv", meetings)
    print(f"summary_written={summary_root / 'event_matrix.json'}")
    print(f"ranking_written={summary_root / 'event_matrix.csv'}")


if __name__ == "__main__":
    main()
