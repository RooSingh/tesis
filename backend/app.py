"""Punto de entrada inicial del backend.

Este modulo crea una primera aplicacion FastAPI del proyecto y expone
endpoints de verificacion y consulta de telemetria persistida. El consumo MQTT
se ejecuta en un proceso separado mediante `backend.mqtt_consumer`; esta
aplicacion expone por HTTP los datos que dicho consumidor ya inserto en la base
de datos.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Query
from fastapi.middleware.cors import CORSMiddleware

from backend.config import BACKEND_APP_NAME
from backend.db import (
    listar_ejecuciones_procesamiento,
    listar_incidencias_procesamiento,
    obtener_mensajes_por_senal,
    obtener_mensajes_por_sesion,
    obtener_ejecucion_procesamiento,
    obtener_ultimos_mensajes,
    obtener_ultimos_por_senal,
    obtener_comparacion_pilotos_racing,
    obtener_contexto_racing_en_instante,
    obtener_pilotos_racing,
    obtener_replay_openf1,
    obtener_serie_replay_openf1,
    obtener_sesion_racing,
)


app = FastAPI(title=BACKEND_APP_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> dict:
    """Endpoint basico para verificar que el backend esta activo."""
    return {"message": "Backend de telemetria activo"}


@app.get("/health")
def health() -> dict:
    """Endpoint de salud simple para pruebas locales iniciales."""
    return {"status": "ok"}


@app.get("/telemetry/latest")
def telemetry_latest(limit: int = 20) -> list[dict]:
    """Devuelve los ultimos mensajes telemetricos persistidos.

    Parametros:
    - limit: cantidad maxima de mensajes a devolver.
    """

    return obtener_ultimos_mensajes(limit)


@app.get("/telemetry/by-signal/{signal_name}")
def telemetry_by_signal(signal_name: str, limit: int = 50) -> list[dict]:
    """Devuelve los ultimos mensajes persistidos para una senal concreta.

    Parametros:
    - signal_name: nombre logico de la senal a consultar.
    - limit: cantidad maxima de mensajes a devolver.
    """

    return obtener_mensajes_por_senal(signal_name, limit)


@app.get("/telemetry/latest-by-signal")
def telemetry_latest_by_signal() -> list[dict]:
    """Devuelve la ultima muestra disponible de cada senal."""

    return obtener_ultimos_por_senal()


@app.get("/telemetry/by-session/{session_id}")
def telemetry_by_session(session_id: str, limit: int = 100) -> list[dict]:
    """Devuelve mensajes persistidos pertenecientes a una sesion concreta."""

    return obtener_mensajes_por_sesion(session_id, limit)


@app.get("/processing/runs")
def processing_runs(limit: int = 50) -> list[dict]:
    """Lista paquetes Nivel B procesados o validados."""

    return listar_ejecuciones_procesamiento(limit)


@app.get("/processing/runs/{run_id}")
def processing_run(run_id: int) -> dict:
    """Expone estado, capacidades, conteos y limites de una corrida."""

    run = obtener_ejecucion_procesamiento(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Corrida de procesamiento no encontrada.")
    return run


@app.get("/processing/runs/{run_id}/issues")
def processing_run_issues(run_id: int) -> list[dict]:
    """Expone advertencias y errores persistidos para una corrida."""

    if obtener_ejecucion_procesamiento(run_id) is None:
        raise HTTPException(status_code=404, detail="Corrida de procesamiento no encontrada.")
    return listar_incidencias_procesamiento(run_id)


@app.get("/racing/sessions/{session_key}")
def racing_session(session_key: int) -> dict:
    """Expone el contexto de una carrera historica para analisis profesional."""

    session = obtener_sesion_racing(session_key)
    if session is None:
        raise HTTPException(status_code=404, detail="Sesion racing no encontrada.")
    return session


@app.get("/racing/sessions/{session_key}/drivers")
def racing_drivers(session_key: int) -> list[dict]:
    """Expone pilotos y equipos disponibles para comparar en una sesion."""

    return obtener_pilotos_racing(session_key)


@app.get("/racing/sessions/{session_key}/driver-comparison")
def racing_driver_comparison(
    session_key: int, drivers: list[int] = Query(..., min_length=1)
) -> list[dict]:
    """Expone resultado, ritmo y estrategia para pilotos seleccionados."""

    return obtener_comparacion_pilotos_racing(session_key, drivers)


@app.get("/racing/sessions/{session_key}/replay-series")
def racing_replay_series(
    session_key: int,
    replay_run_id: str,
    drivers: list[int] = Query(..., min_length=1),
    signal: str = Query(..., min_length=1),
) -> list[dict]:
    """Expone una serie temporal OpenF1 filtrada por ejecucion, pilotos y senal."""

    return obtener_serie_replay_openf1(session_key, replay_run_id, drivers, signal)


@app.get("/racing/sessions/{session_key}/context-at")
def racing_context_at(
    session_key: int,
    timestamp: str = Query(..., min_length=1),
    drivers: list[int] = Query(..., min_length=1),
) -> dict:
    """Expone contexto racing mas cercano a un instante UTC de telemetria."""

    return obtener_contexto_racing_en_instante(session_key, timestamp, drivers)


@app.get("/racing/sessions/{session_key}/replay")
def racing_replay(
    session_key: int, driver_number: int | None = None, replay_run_id: str | None = None
) -> list[dict]:
    """Expone muestras OpenF1 que atravesaron el pipeline MQTT de replay."""

    return obtener_replay_openf1(session_key, driver_number, replay_run_id)
