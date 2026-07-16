"""Punto de entrada inicial del backend.

Este modulo crea una primera aplicacion FastAPI del proyecto y expone
endpoints minimos de verificacion. En esta etapa, su objetivo principal es
confirmar que el backend puede existir como servicio web independiente antes de
incorporar consumo MQTT, persistencia o logica mas compleja.
"""

from __future__ import annotations

from fastapi import FastAPI

from backend.config import BACKEND_APP_NAME


app = FastAPI(title=BACKEND_APP_NAME)


@app.get("/")
def root() -> dict:
    """Endpoint basico para verificar que el backend esta activo."""
    return {"message": "Backend de telemetria activo"}


@app.get("/health")
def health() -> dict:
    """Endpoint de salud simple para pruebas locales iniciales."""
    return {"status": "ok"}
