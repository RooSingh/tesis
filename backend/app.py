"""Punto de entrada inicial del backend.

Este modulo crea una primera aplicacion FastAPI del proyecto y expone
endpoints minimos de verificacion. En esta etapa, su objetivo principal es
confirmar que el backend puede existir como servicio web independiente antes de
incorporar consumo MQTT, persistencia o logica mas compleja.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import BACKEND_APP_NAME
from backend.db import (
    obtener_mensajes_por_senal,
    obtener_mensajes_por_sesion,
    obtener_ultimos_mensajes,
    obtener_ultimos_por_senal,
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
