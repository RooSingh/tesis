"""Punto de entrada inicial del backend.

Este modulo crea una primera aplicacion FastAPI del proyecto y expone
endpoints de verificacion y consulta de telemetria persistida. El consumo MQTT
se ejecuta en un proceso separado mediante `backend.mqtt_consumer`; esta
aplicacion expone por HTTP los datos que dicho consumidor ya inserto en la base
de datos.
"""

from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from backend import live_stream

from backend.config import BACKEND_APP_NAME
from backend.db import (
    LIMITE_FILAS_REPLAY,
    calcular_ventanas_vueltas,
    listar_analisis_sesion,
    obtener_analisis_stints,
    obtener_analisis_vueltas,
    listar_corridas_replay_acotado,
    listar_ejecuciones_procesamiento,
    listar_incidencias_procesamiento,
    listar_sesiones_racing,
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


LIMITE_MUESTRAS_MAXIMO = 200000


def _validar_limite(limite: int) -> None:
    """Rechaza un limite fuera de rango en vez de recortarlo en silencio."""
    if limite < 1 or limite > LIMITE_MUESTRAS_MAXIMO:
        raise HTTPException(
            status_code=400,
            detail=f"`limite` debe estar entre 1 y {LIMITE_MUESTRAS_MAXIMO}.",
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


def _telemetria_declarada(inventario: dict | None) -> dict:
    """Traduce el inventario de un paquete a la disponibilidad de telemetria.

    La declaracion sale del inventario que ya persiste el procesador de sesiones y
    no de una consulta nueva: el paquete de Spa-Francorchamps y el de Suzuka se
    importaron sin `car_data`, y eso ya esta registrado como capacidad ausente. La
    interfaz necesita esa ausencia dicha, no deducida de un panel vacio.
    """
    capacidades = (inventario or {}).get("capabilities") or {}
    pilotos = capacidades.get("telemetry_drivers") or {}
    car_data = len(pilotos.get("car_data") or [])
    location = len(pilotos.get("location") or [])
    declaracion = {
        "disponible": car_data > 0,
        "pilotos_car_data": car_data,
        "pilotos_location": location,
        "origen": "inventario del paquete procesado (session_processing_runs)",
    }
    if not car_data:
        declaracion["motivo"] = (
            "el paquete importado de esta sesion no incluye car_data: hay contexto "
            "oficial (vueltas, stints, clima, control de carrera) pero no hay "
            "telemetria que replicar ni analizar"
        )
    return declaracion


@app.get("/racing/sessions")
def racing_sessions() -> list[dict]:
    """Lista las sesiones importadas con su circuito, tipo, fecha y capacidades.

    Existe para que la aplicacion deje de llevar una clave de sesion escrita a
    mano. El dashboard tenia `9947` fijo, de modo que Spa-Francorchamps y Suzuka
    estaban en la base y eran invisibles desde la interfaz, lo que contradecia la
    reutilizacion multicircuito que el trabajo sostiene.

    Cada sesion viaja con su telemetria declarada, disponible o ausente. Una sesion
    sin `car_data` no es un error de consulta y la respuesta lo dice, para que la
    interfaz pueda declararlo en vez de mostrar paneles vacios.
    """
    inventarios: dict[int, dict] = {}
    for run in listar_ejecuciones_procesamiento():
        # `listar_ejecuciones_procesamiento` ordena de la mas reciente a la mas
        # antigua, de modo que la primera que aparece de cada sesion es la vigente.
        inventarios.setdefault(run["session_key"], run.get("inventory") or {})

    sesiones = listar_sesiones_racing()
    for sesion in sesiones:
        sesion["telemetria"] = _telemetria_declarada(inventarios.get(sesion["session_key"]))
    return sesiones


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


@app.get("/racing/sessions/{session_key}/replay-runs")
def racing_replay_runs(session_key: int) -> list[dict]:
    """Lista las corridas de replay persistidas para una sesion.

    POR QUE ESTA RUTA EXISTE AHORA Y NO ANTES. El listado de corridas se dejo
    deliberadamente fuera de HTTP porque `listar_corridas_replay` agrupa millones
    de filas: se volvio a medir el 2026-08-28 y sigue costando 23,2 segundos. Lo
    que se expone aca no es esa consulta sino `listar_corridas_replay_acotado`, que
    enumera las corridas por saltos de indice y lee una fila por corrida. Medido en
    milisegundos, y su costo no crece con el volumen persistido.

    Hacia falta porque el dashboard llevaba `d7_silverstone_full_001` escrito en el
    codigo, y ya habia tenido que cambiarse a mano una vez. Elegir corrida no es
    opcional: una misma sesion acumula el replay definitivo junto a sondeos de
    carga de las mismas vueltas.

    La respuesta puede ser una lista vacia, y eso es una respuesta valida: la
    sesion existe pero no tiene telemetria replicada.
    """
    return listar_corridas_replay_acotado(session_key)


@app.get("/racing/sessions/{session_key}/replay-series")
def racing_replay_series(
    session_key: int,
    replay_run_id: str,
    drivers: list[int] = Query(..., min_length=1),
    signal: str = Query(..., min_length=1),
    limite: int = LIMITE_FILAS_REPLAY,
) -> list[dict]:
    """Expone una serie temporal OpenF1 filtrada por ejecucion, pilotos y senal."""

    _validar_limite(limite)
    return obtener_serie_replay_openf1(session_key, replay_run_id, drivers, signal, limite)


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
    session_key: int,
    replay_run_id: str,
    driver_number: int | None = None,
    limite: int = LIMITE_FILAS_REPLAY,
) -> dict:
    """Expone muestras OpenF1 que atravesaron el pipeline MQTT de replay.

    `replay_run_id` pasa a ser obligatorio y la respuesta viene acotada. Antes ambos
    eran opcionales y sin tope: tras persistir la carrera completa, una llamada sin
    parametros pedia 10.079.006 filas, del orden de 13 GB de objetos en memoria del
    backend, mezclando ademas el replay definitivo con mas de una decena de sondeos
    de carga de la misma carrera.

    La respuesta declara el total real disponible junto a lo devuelto, para que un
    lote acotado no se confunda con el volumen completo de la corrida.
    """
    _validar_limite(limite)
    muestras, hay_mas = obtener_replay_openf1(session_key, replay_run_id, driver_number, limite)
    respuesta = {
        "replay_run_id": replay_run_id,
        "driver_number": driver_number,
        "total_devuelto": len(muestras),
        "truncado": hay_mas,
        "muestras": muestras,
    }
    if hay_mas:
        respuesta["advertencia_truncado"] = (
            f"La corrida tiene mas de {limite} muestras para esta seleccion. Acotar "
            "por piloto o elevar `limite`. El total exacto no se calcula aqui porque "
            "contar la corrida completa recorre millones de filas."
        )
    return respuesta


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


# ---------------------------------------------------------------------------
# Analisis automatico por sesion
#
# Agregado el 2026-08-27. Los resultados se leen de `session_lap_analysis` y
# `session_stint_analysis`, generados por `scripts/generate_session_analysis.py`.
#
# Cada respuesta conserva la separacion por nivel de evidencia con la que fue
# calculada: `metricas_oficiales` proviene de OpenF1 sin transformar,
# `metricas_derivadas` la calcula el proyecto, y `calidad` declara sobre cuantas
# muestras se apoya cada resultado. No se aplanan en un unico diccionario porque
# esa distincion es el aporte metodologico del analisis, no un detalle interno.
# ---------------------------------------------------------------------------


@app.get("/racing/sessions/{session_key}/analysis")
def racing_session_analysis(session_key: int) -> list[dict]:
    """Lista los analisis generados para una sesion, con sus conteos y limites.

    Reemplaza al recuento sobre `telemetry_messages` como fuente del listado de
    corridas disponibles: aquel recorre diez millones de filas y tarda mas de
    diecisiete segundos medidos, mientras que este consulta unas pocas filas.
    """
    return listar_analisis_sesion(session_key)


@app.get("/racing/sessions/{session_key}/analysis/{replay_run_id}/laps")
def racing_analysis_laps(
    session_key: int, replay_run_id: str, driver_number: int | None = None
) -> list[dict]:
    """Expone el analisis por vuelta de una corrida, opcionalmente de un piloto."""
    filas = obtener_analisis_vueltas(session_key, replay_run_id, driver_number)
    if not filas:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No hay analisis generado para la corrida {replay_run_id!r} en la sesion "
                f"{session_key}. Ejecutar scripts/generate_session_analysis.py."
            ),
        )
    return filas


@app.get("/racing/sessions/{session_key}/analysis/{replay_run_id}/stints")
def racing_analysis_stints(
    session_key: int, replay_run_id: str, driver_number: int | None = None
) -> list[dict]:
    """Expone el analisis por stint de una corrida, opcionalmente de un piloto."""
    filas = obtener_analisis_stints(session_key, replay_run_id, driver_number)
    if not filas:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No hay analisis de stints para la corrida {replay_run_id!r} en la sesion "
                f"{session_key}. Ejecutar scripts/generate_session_analysis.py."
            ),
        )
    return filas


# --------------------------------------------------------------------------- #
# Camino en vivo
# --------------------------------------------------------------------------- #
#
# Coexiste con el historico y no lo reemplaza. El historico consulta la base; este
# recibe del broker y empuja al navegador. Que sean caminos distintos es lo que
# vuelve significativa la comparacion entre operacion en vivo y post-sesion.


@app.on_event("startup")
async def _iniciar_difusor() -> None:
    """Conecta al broker al arrancar. Un fallo no impide servir el historico."""

    live_stream.difusor.iniciar(asyncio.get_running_loop())


@app.on_event("shutdown")
async def _detener_difusor() -> None:
    live_stream.difusor.detener()


@app.get("/live/status")
def live_status() -> dict:
    """Estado del camino en vivo, para distinguir 'sin datos' de 'sin conexion'."""

    return live_stream.difusor.estado()


@app.get("/live/recent")
def live_recent(limite: int = Query(50, ge=1, le=100)) -> list[dict]:
    """Ventana corta de lo ultimo recibido.

    Permite que un navegador que abre la pagina vea algo de inmediato en lugar de
    esperar al proximo mensaje. No sustituye al flujo: es su punto de partida.
    """

    recientes = list(live_stream.difusor.recientes)
    return recientes[-limite:]


@app.get("/live/stream")
async def live_stream_endpoint() -> StreamingResponse:
    """Flujo de eventos enviados por el servidor con la telemetria en vivo.

    El navegador abre esta conexion una vez y recibe cada mensaje al llegar, sin
    volver a preguntar. La telemetria va en una sola direccion, de modo que un
    canal bidireccional resolveria un problema que no existe.
    """

    cola = live_stream.difusor.suscribir()
    if cola is None:
        raise HTTPException(
            status_code=503,
            detail=(f"Se alcanzo el maximo de {live_stream.MAX_SUSCRIPTORES} "
                    "suscriptores simultaneos al flujo en vivo."),
        )

    async def generar():
        try:
            async for evento in live_stream.flujo_de_eventos(cola):
                yield evento
        finally:
            live_stream.difusor.desuscribir(cola)

    return StreamingResponse(
        generar(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Evita que un proxy inverso acumule la respuesta antes de enviarla,
            # que anularia el proposito del flujo.
            "X-Accel-Buffering": "no",
        },
    )
