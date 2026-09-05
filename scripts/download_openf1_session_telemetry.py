"""Completa telemetria OpenF1 faltante de una sesion local de forma reanudable."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_URL = "https://api.openf1.org/v1"
ENDPOINTS = ("car_data", "location")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_session_identity(session_path: Path) -> tuple[int, list[dict[str, Any]]]:
    """Lee la identidad minima de la sesion y su catalogo de pilotos."""

    session = read_json(session_path / "session.json")
    drivers = read_json(session_path / "drivers.json")
    if not isinstance(session, dict) or not isinstance(session.get("session_key"), int):
        raise ValueError("session.json debe contener session_key entero.")
    if not isinstance(drivers, list):
        raise ValueError("drivers.json debe contener una lista.")
    return session["session_key"], drivers


def telemetry_filename(endpoint: str, driver: dict[str, Any]) -> str:
    return f"{endpoint}_driver_{driver['driver_number']}_{driver['name_acronym']}.json"


def plan_downloads(session_path: Path, endpoints: tuple[str, ...] = ENDPOINTS) -> dict[str, Any]:
    """Construye un plan determinista de cache y faltantes sin usar red."""

    session_key, drivers = load_session_identity(session_path)
    records = []
    for driver in sorted(drivers, key=lambda row: row["driver_number"]):
        for endpoint in endpoints:
            filename = telemetry_filename(endpoint, driver)
            path = session_path / filename
            records.append(
                {
                    "endpoint": endpoint,
                    "session_key": session_key,
                    "driver_number": driver["driver_number"],
                    "name_acronym": driver["name_acronym"],
                    "path": str(path),
                    "status": "cached" if path.is_file() else "missing",
                    "rows": len(read_json(path)) if path.is_file() else None,
                    "error": None,
                }
            )
    return {
        "session_key": session_key,
        "drivers": len(drivers),
        "endpoints": list(endpoints),
        "records": records,
        "missing": sum(1 for record in records if record["status"] == "missing"),
        "cached": sum(1 for record in records if record["status"] == "cached"),
    }


#: Techo declarado por el proveedor para el plan gratuito, consultado el
#: 2026-09-02: "Up to 3 requests per second and 30 requests per minute".
#:
#: Se respetan los dos. Media segundo entre consultas cumple el techo por segundo
#: con margen, pero sostenido son ciento veinte solicitudes por minuto contra un
#: techo de treinta: el limite por minuto es el que gobierna una descarga larga, y
#: era el que faltaba. Cuando el proveedor publica un limite, el limite se respeta
#: en lugar de estimar uno propio.
ESPERA_ENTRE_CONSULTAS_S = 0.5
LIMITE_POR_MINUTO = 30
VENTANA_S = 60.0

#: Marcas temporales de las consultas de la ultima ventana. Es una lista y no un
#: contador porque hay que saber **cuando** vence cada una para poder esperar solo
#: lo necesario.
_ventana: list[float] = []


def _esperar_turno() -> None:
    """Bloquea hasta que quepa una consulta mas dentro del techo por minuto."""

    ahora = time.monotonic()
    # Se descartan las que ya salieron de la ventana.
    while _ventana and ahora - _ventana[0] >= VENTANA_S:
        _ventana.pop(0)
    if len(_ventana) >= LIMITE_POR_MINUTO:
        # Se espera a que venza la mas antigua, mas un margen para no quedar
        # justo en el borde por redondeo del reloj.
        time.sleep(VENTANA_S - (ahora - _ventana[0]) + 0.05)
        return _esperar_turno()
    _ventana.append(time.monotonic())


def fetch_openf1(endpoint: str, params: dict[str, int], last_request: list[float]) -> tuple[list[dict] | None, dict[str, Any]]:
    """Consulta OpenF1 con pausas y reintentos simples."""

    elapsed = time.monotonic() - last_request[0]
    if elapsed < ESPERA_ENTRE_CONSULTAS_S:
        time.sleep(ESPERA_ENTRE_CONSULTAS_S - elapsed)
    _esperar_turno()
    url = f"{BASE_URL}/{endpoint}?{urlencode(params)}"
    for attempt in range(1, 4):
        requested_at = datetime.now(timezone.utc).isoformat()
        try:
            request = Request(url, headers={"User-Agent": "tesis-openf1-day22/1.0"})
            with urlopen(request, timeout=120) as response:
                payload = json.loads(response.read())
                status = response.status
            if not isinstance(payload, list):
                raise ValueError("OpenF1 no devolvio una lista JSON.")
            last_request[0] = time.monotonic()
            return payload, {"url": url, "requested_at_utc": requested_at, "status": status, "attempt": attempt, "rows": len(payload), "error": None}
        except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as error:
            last_request[0] = time.monotonic()
            if attempt == 3:
                return None, {"url": url, "requested_at_utc": requested_at, "status": getattr(error, "code", None), "attempt": attempt, "rows": None, "error": str(error)}
            time.sleep(attempt)
    raise RuntimeError("Bucle de reintentos inesperado.")


def execute_downloads(session_path: Path, plan: dict[str, Any]) -> dict[str, Any]:
    """Descarga solo registros faltantes y conserva el plan reanudable."""

    last_request = [0.0]
    records = []
    for record in plan["records"]:
        path = Path(record["path"])
        if record["status"] == "cached":
            records.append(record)
            continue
        payload, fetch_record = fetch_openf1(
            record["endpoint"],
            {"session_key": record["session_key"], "driver_number": record["driver_number"]},
            last_request,
        )
        record = {**record, **fetch_record, "status": "downloaded" if payload is not None else "error"}
        if payload is not None:
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        records.append(record)
    return {**plan, "records": records, "downloaded": sum(1 for record in records if record["status"] == "downloaded"), "errors": sum(1 for record in records if record["status"] == "error")}


def write_manifest(session_path: Path, result: dict[str, Any], mode: str) -> Path:
    manifest = {
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "scope": {
            "session_key": result["session_key"],
            "drivers": result["drivers"],
            "endpoints": result["endpoints"],
            "database_writes": False,
            "mqtt_publish": False,
        },
        "summary": {key: result.get(key, 0) for key in ("cached", "missing", "downloaded", "errors")},
        "requests": result["records"],
    }
    path = session_path / "day22_telemetry_manifest.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-path", type=Path, required=True)
    parser.add_argument("--download", action="store_true", help="Sin este flag solo inventaria faltantes.")
    args = parser.parse_args()
    plan = plan_downloads(args.session_path)
    result = execute_downloads(args.session_path, plan) if args.download else plan
    manifest = write_manifest(args.session_path, result, "download" if args.download else "dry_run")
    print(json.dumps({"mode": "download" if args.download else "dry_run", "manifest": str(manifest), "summary": {key: result.get(key, 0) for key in ("cached", "missing", "downloaded", "errors")}}, sort_keys=True))


if __name__ == "__main__":
    main()
