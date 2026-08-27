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
    calcular_ventanas_vueltas,
    listar_ejecuciones_procesamiento,
    listar_incidencias_procesamiento,
    obtener_mensajes_por_senal,
    obtener_mensajes_por_sesion,
    obtener_ejecucion_procesamiento,
    obtener_telemetria_en_ventana,
    obtener_ultimos_mensajes,
    obtener_ultimos_por_senal,
    obtener_comparacion_pilotos_racing,
    obtener_contexto_racing_en_instante,
    obtener_pilotos_racing,
    obtener_replay_openf1,
    obtener_serie_replay_openf1,
    obtener_sesion_racing,
    obtener_vueltas_piloto,
    resolver_ventana_stint,
    resolver_ventana_vuelta,
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


# ---------------------------------------------------------------------------
# Seleccion de telemetria por vuelta y por stint
#
# Agregado el 2026-08-27 para completar la tarea del Dia 22 que exige exponer la
# seleccion por piloto, vuelta y stint.
#
# Los tres endpoints devuelven la ventana temporal empleada junto con los datos.
# No es informacion redundante: la vuelta a la que pertenece una muestra es una
# derivacion y no un dato de origen, de modo que quien consume la respuesta debe
# poder auditar como se calculo el recorte en vez de confiar en el a ciegas.
# ---------------------------------------------------------------------------

# Tope por defecto de muestras devueltas. Una vuelta de unos 90 segundos produce
# alrededor de 3.000 muestras contando las nueve senales, de modo que el tope
# holgado para una vuelta puede quedar corto para un stint completo. Por eso toda
# respuesta declara `truncado`: una lista recortada en silencio se leeria como una
# vuelta incompleta y no como un limite de la consulta.
LIMITE_MUESTRAS_POR_DEFECTO = 20000


LIMITE_MUESTRAS_MAXIMO = 200000


def _validar_limite(limite: int) -> None:
    """Rechaza un limite fuera de rango en vez de recortarlo en silencio."""
    if limite < 1 or limite > LIMITE_MUESTRAS_MAXIMO:
        raise HTTPException(
            status_code=400,
            detail=f"`limite` debe estar entre 1 y {LIMITE_MUESTRAS_MAXIMO}.",
        )


def _respuesta_telemetria(ventana: dict, muestras: list[dict], limite: int) -> dict:
    """Arma la respuesta comun a vuelta y stint, declarando sus limitaciones."""
    respuesta = {
        "ventana": ventana,
        "muestras": muestras,
        "total_devuelto": len(muestras),
        "truncado": len(muestras) >= limite,
    }
    if not ventana.get("completa"):
        respuesta["advertencia"] = (
            "La ventana no pudo determinarse por completo, de modo que no se "
            "consulto telemetria. Revisar `fin` en la ventana devuelta."
        )
    elif ventana.get("fin_estimado"):
        respuesta["advertencia"] = (
            "El fin de la ventana es estimado a partir de la duracion declarada, "
            "porque no existe una vuelta siguiente contigua que lo delimite."
        )
    if respuesta["truncado"]:
        respuesta["advertencia_truncado"] = (
            f"Se alcanzo el limite de {limite} muestras. Acotar con `signal` o "
            "elevar `limite` para obtener el recorte completo."
        )
    return respuesta


@app.get("/racing/sessions/{session_key}/drivers/{driver_number}/laps")
def racing_driver_laps(session_key: int, driver_number: int) -> list[dict]:
    """Lista las vueltas de un piloto con la ventana temporal derivada de cada una.

    Permite descubrir que vueltas existen y cuales tienen un fin estimado antes de
    pedir su telemetria.
    """
    vueltas = obtener_vueltas_piloto(session_key, driver_number)
    if not vueltas:
        raise HTTPException(
            status_code=404,
            detail=f"No hay vueltas registradas para el piloto {driver_number} en la sesion {session_key}.",
        )
    return calcular_ventanas_vueltas(vueltas)


@app.get("/racing/sessions/{session_key}/drivers/{driver_number}/laps/{lap_number}/telemetry")
def racing_lap_telemetry(
    session_key: int,
    driver_number: int,
    lap_number: int,
    signal: str | None = None,
    replay_run_id: str | None = None,
    limite: int = LIMITE_MUESTRAS_POR_DEFECTO,
) -> dict:
    """Expone la telemetria de replay contenida en una vuelta concreta."""
    _validar_limite(limite)
    ventana = resolver_ventana_vuelta(session_key, driver_number, lap_number)
    if ventana is None:
        raise HTTPException(
            status_code=404,
            detail=f"No existe la vuelta {lap_number} para el piloto {driver_number} en la sesion {session_key}.",
        )

    muestras = []
    if ventana["completa"]:
        muestras = obtener_telemetria_en_ventana(
            session_key,
            driver_number,
            ventana["inicio"],
            ventana["fin"],
            signal_name=signal,
            replay_run_id=replay_run_id,
            limite=limite,
        )
    return _respuesta_telemetria(ventana, muestras, limite)


@app.get("/racing/sessions/{session_key}/drivers/{driver_number}/stints/{stint_number}/telemetry")
def racing_stint_telemetry(
    session_key: int,
    driver_number: int,
    stint_number: int,
    signal: str | None = None,
    replay_run_id: str | None = None,
    limite: int = LIMITE_MUESTRAS_POR_DEFECTO,
) -> dict:
    """Expone la telemetria de replay contenida en un stint completo.

    Un stint abarca decenas de vueltas, de modo que alcanzar `limite` es esperable
    si no se acota por senal. La respuesta lo declara en vez de recortar en
    silencio.
    """
    _validar_limite(limite)
    ventana = resolver_ventana_stint(session_key, driver_number, stint_number)
    if ventana is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No existe el stint {stint_number} para el piloto {driver_number} "
                f"en la sesion {session_key}, o sus vueltas no tienen ventana resoluble."
            ),
        )

    muestras = []
    if ventana["completa"]:
        muestras = obtener_telemetria_en_ventana(
            session_key,
            driver_number,
            ventana["inicio"],
            ventana["fin"],
            signal_name=signal,
            replay_run_id=replay_run_id,
            limite=limite,
        )
    return _respuesta_telemetria(ventana, muestras, limite)
