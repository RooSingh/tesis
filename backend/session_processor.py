"""Inventaria y valida paquetes locales Nivel B antes de importarlos."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.session_context import import_available_context, load_available_context


PROCESSOR_VERSION = "day21-package-inventory-v1"
SOURCE_TYPE = "openf1_historical_replay"
TELEMETRY_FILE_PATTERN = re.compile(r"^(car_data|location)_driver_(\d+)_[^.]+\.json$")
OPTIONAL_CONTEXT_FILES = {
    "drivers.json": "drivers",
    "laps.json": "laps",
    "stints.json": "stints",
    "session_result.json": "results",
    "position.json": "positions",
    "intervals.json": "intervals",
    "pit.json": "pit_stops",
    "weather.json": "weather",
    "race_control.json": "race_control",
    "overtakes.json": "overtakes",
    "team_radio.json": "team_radio",
}


class SessionPackageValidationError(ValueError):
    """Indica que un paquete local no cumple la estructura minima admitida."""


def _read_json(path: Path) -> Any:
    """Lee JSON y transforma errores tecnicos en errores de paquete explicitos."""

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as error:
        raise SessionPackageValidationError(f"Archivo no UTF-8: {path.name}") from error
    except json.JSONDecodeError as error:
        raise SessionPackageValidationError(f"JSON invalido en {path.name}: {error.msg}") from error


def _file_hash(path: Path) -> str:
    """Calcula una huella de contenido para detectar cambios de paquete."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_session(session_path: Path) -> dict[str, Any]:
    """Valida la identidad minima de una sesion OpenF1 local."""

    session_file = session_path / "session.json"
    if not session_file.is_file():
        raise SessionPackageValidationError("Falta el archivo obligatorio session.json.")
    session = _read_json(session_file)
    if not isinstance(session, dict):
        raise SessionPackageValidationError("session.json debe contener un objeto JSON.")
    if not isinstance(session.get("session_key"), int):
        raise SessionPackageValidationError("session.json debe incluir session_key entero.")
    return session


def build_package_inventory(package_path: str | Path) -> dict[str, Any]:
    """Construye un inventario reproducible sin modificar los archivos de entrada."""

    session_path = Path(package_path)
    if not session_path.is_dir():
        raise SessionPackageValidationError(f"El directorio de sesion no existe: {session_path}")

    session = _validate_session(session_path)
    files = sorted(path for path in session_path.glob("*.json") if path.is_file())
    file_hashes: dict[str, str] = {}
    capabilities = {name: False for name in OPTIONAL_CONTEXT_FILES.values()}
    telemetry_drivers = {"car_data": [], "location": []}
    warnings: list[str] = []

    for path in files:
        relative_path = path.name
        if relative_path == "session.json" or relative_path in OPTIONAL_CONTEXT_FILES:
            _read_json(path)
            if relative_path in OPTIONAL_CONTEXT_FILES:
                capabilities[OPTIONAL_CONTEXT_FILES[relative_path]] = True
            file_hashes[relative_path] = _file_hash(path)
            continue

        match = TELEMETRY_FILE_PATTERN.fullmatch(relative_path)
        if match is None:
            continue
        payload = _read_json(path)
        if not isinstance(payload, list):
            raise SessionPackageValidationError(f"{relative_path} debe contener una lista JSON.")
        endpoint, driver_number = match.groups()
        telemetry_drivers[endpoint].append(int(driver_number))
        file_hashes[relative_path] = _file_hash(path)

    for endpoint in telemetry_drivers:
        telemetry_drivers[endpoint].sort()
    if not capabilities["drivers"]:
        warnings.append("No se encontro drivers.json; la sesion no tendra catalogo de pilotos.")
    if not any(telemetry_drivers.values()):
        warnings.append("No se encontro telemetria car_data ni location; solo se importara contexto disponible.")

    inventory = {
        "schema_version": 1,
        "processor_version": PROCESSOR_VERSION,
        "source_type": SOURCE_TYPE,
        "session_key": session["session_key"],
        "files": file_hashes,
        "capabilities": {**capabilities, "telemetry_drivers": telemetry_drivers},
        "warnings": warnings,
    }
    serialized = json.dumps(inventory, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return {**inventory, "package_fingerprint": hashlib.sha256(serialized.encode("utf-8")).hexdigest()}


def register_package_validation(
    package_path: str | Path,
    find_run: Callable[[str], dict | None] | None = None,
    create_run: Callable[..., dict | None] | None = None,
    record_issue: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """Registra una validacion o devuelve la corrida previa del mismo paquete."""

    if find_run is None or create_run is None or record_issue is None:
        from backend.db import (
            crear_ejecucion_validada,
            obtener_ejecucion_por_huella,
            registrar_incidencia_procesamiento,
        )

        find_run = find_run or obtener_ejecucion_por_huella
        create_run = create_run or crear_ejecucion_validada
        record_issue = record_issue or registrar_incidencia_procesamiento

    inventory = build_package_inventory(package_path)
    existing = find_run(inventory["package_fingerprint"])
    if existing is not None:
        return {"status": "already_validated", "run": existing, "inventory": inventory}

    run = create_run(
        inventory["package_fingerprint"],
        SOURCE_TYPE,
        inventory["session_key"],
        str(Path(package_path)),
        PROCESSOR_VERSION,
        inventory,
    )
    if run is None:
        # Otra ejecucion pudo registrar la misma huella entre la consulta y la insercion.
        existing = find_run(inventory["package_fingerprint"])
        if existing is not None:
            return {"status": "already_validated", "run": existing, "inventory": inventory}
        raise RuntimeError("No se pudo registrar ni recuperar la validacion del paquete.")

    for warning in inventory["warnings"]:
        record_issue(run["run_id"], "warning", "package_inventory_warning", warning)
    return {"status": "validated", "run": run, "inventory": inventory}


def import_validated_package(package_path: str | Path) -> dict[str, Any]:
    """Importa contexto disponible de una corrida validada y conserva su estado."""

    from backend.db import actualizar_ejecucion_procesamiento, registrar_incidencia_procesamiento

    validation = register_package_validation(package_path)
    run = validation["run"]
    if run["status"] in {"completed", "partial"}:
        return {"status": "already_imported", "run": run, "counts": run.get("counts", {})}

    session, datasets, missing = load_available_context(package_path)
    actualizar_ejecucion_procesamiento(run["run_id"], "running", {})
    try:
        counts = import_available_context(package_path, session, datasets)
        for filename in missing:
            registrar_incidencia_procesamiento(
                run["run_id"],
                "warning",
                "missing_optional_context",
                f"No se encontro el contexto opcional {filename}.",
                filename,
            )
        status = "partial" if missing or validation["inventory"]["warnings"] else "completed"
        actualizar_ejecucion_procesamiento(run["run_id"], status, counts)
        return {"status": status, "run": run, "counts": counts, "missing": missing}
    except Exception as error:
        actualizar_ejecucion_procesamiento(run["run_id"], "failed", {}, str(error))
        registrar_incidencia_procesamiento(run["run_id"], "error", "context_import_failed", str(error))
        raise
