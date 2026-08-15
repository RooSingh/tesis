"""Descarga el primer bloque profesional de Silverstone 2025 de forma reanudable.

Obtiene contexto de carrera para los 20 pilotos y telemetria detallada solo de
Verstappen, Norris y Piastri. No escribe en TimescaleDB ni descarga car_data o
location del resto de la grilla hasta una autorizacion posterior.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
RAW_PATH = ROOT / "datasets" / "OpenF1" / "raw" / "2025" / "9947"
BASE_URL = "https://api.openf1.org/v1"
SESSION_KEY = 9947
MEETING_KEY = 1277
INITIAL_DRIVERS = {1: "VER", 4: "NOR", 81: "PIA"}
CONTEXT_ENDPOINTS = ("starting_grid", "position", "intervals", "overtakes", "team_radio")
TELEMETRY_ENDPOINTS = ("car_data", "location")


def cached_payload(path: Path) -> list[dict] | None:
    """Devuelve una respuesta local valida para no repetir una descarga terminada."""
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, list) else None


def fetch(endpoint: str, params: dict[str, int], last_request: list[float]) -> tuple[list[dict] | None, dict]:
    """Consulta OpenF1 con dos reintentos y al menos 0,5 segundos entre llamadas."""
    elapsed = time.monotonic() - last_request[0]
    if elapsed < 0.5:
        time.sleep(0.5 - elapsed)
    url = f"{BASE_URL}/{endpoint}?{urlencode(params)}"
    for attempt in range(1, 4):
        requested_at = datetime.now(timezone.utc).isoformat()
        try:
            request = Request(url, headers={"User-Agent": "tesis-openf1-silverstone-stage1/1.0"})
            with urlopen(request, timeout=120) as response:
                payload = json.loads(response.read())
                status = response.status
            if not isinstance(payload, list):
                raise ValueError("OpenF1 no devolvio una lista JSON.")
            last_request[0] = time.monotonic()
            return payload, {"endpoint": endpoint, "params": params, "url": url, "requested_at_utc": requested_at, "status": status, "attempt": attempt, "rows": len(payload), "error": None}
        except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as error:
            last_request[0] = time.monotonic()
            if attempt == 3:
                return None, {"endpoint": endpoint, "params": params, "url": url, "requested_at_utc": requested_at, "status": getattr(error, "code", None), "attempt": attempt, "rows": None, "error": str(error)}
            time.sleep(attempt)
    raise RuntimeError("Bucle de reintentos inesperado.")


def collect(endpoint: str, params: dict[str, int], destination: Path, last_request: list[float]) -> dict:
    """Usa cache valida o persiste una respuesta cruda junto a su manifiesto."""
    payload = cached_payload(destination)
    if payload is not None:
        return {"endpoint": endpoint, "params": params, "path": str(destination), "status": "cached", "rows": len(payload), "error": None}
    payload, record = fetch(endpoint, params, last_request)
    record["path"] = str(destination)
    if payload is not None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    return record


def main() -> None:
    RAW_PATH.mkdir(parents=True, exist_ok=True)
    last_request = [0.0]
    records = []
    records.append(collect("meetings", {"meeting_key": MEETING_KEY}, RAW_PATH / "meeting.json", last_request))
    for endpoint in CONTEXT_ENDPOINTS:
        records.append(collect(endpoint, {"session_key": SESSION_KEY}, RAW_PATH / f"{endpoint}.json", last_request))
    for driver_number, acronym in INITIAL_DRIVERS.items():
        for endpoint in TELEMETRY_ENDPOINTS:
            filename = f"{endpoint}_driver_{driver_number}_{acronym}.json"
            records.append(collect(endpoint, {"session_key": SESSION_KEY, "driver_number": driver_number}, RAW_PATH / filename, last_request))

    manifest = {
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "session_key": SESSION_KEY,
            "meeting_key": MEETING_KEY,
            "context": "all 20 drivers through session-scoped endpoints",
            "detailed_telemetry_drivers": INITIAL_DRIVERS,
            "explicitly_not_downloaded": "car_data and location for the remaining 17 drivers",
            "database_writes": False,
        },
        "requests": records,
    }
    (RAW_PATH / "stage1_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
    for record in records:
        print(f"endpoint={record['endpoint']} status={record['status']} rows={record['rows']} error={record['error']}")


if __name__ == "__main__":
    main()
