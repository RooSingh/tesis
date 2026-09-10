"""Punto de entrada inicial del backend.

Este modulo crea una primera aplicacion FastAPI del proyecto y expone
endpoints de verificacion y consulta de telemetria persistida. El consumo MQTT
se ejecuta en un proceso separado mediante `backend.mqtt_consumer`; esta
aplicacion expone por HTTP los datos que dicho consumidor ya inserto en la base
de datos.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import deque
from pathlib import Path

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from adapters import f1_25 as f1_25_adapter
from backend import api_analisis
from backend import api_sesion
from backend import catalogo_corridas
from backend import catalogo_sesiones
from backend import config
from backend import db
from backend import ingesta
from backend import live_stream
from backend import matriz_fuentes
from backend import anotador_vivo
from adapters import can_rav4
from backend import recorrido
from backend import resumen_sesion

from backend.config import BACKEND_APP_NAME
from backend.config import CORS_ORIGENES
from backend.config import DIRECTORIO_TABLERO
from backend.config import SERVIR_TABLERO
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

# Las respuestas de esta API son JSON de numeros: listas largas de pares
# distancia-valor, con los mismos digitos y los mismos nombres de campo
# repetidos miles de veces. Es exactamente la forma que mejor comprime. Medido
# sobre una vuelta de doce senales la respuesta pasa de 43.019 a 13.545 bytes,
# y el catalogo de sesiones de 132.948 a 10.823.
#
# El umbral evita comprimir lo que no vale la pena: por debajo de un kilobyte
# el trabajo de comprimir cuesta mas que los bytes que ahorra.
app.add_middleware(GZipMiddleware, minimum_size=1024)


# ---------------------------------------------------------------------------
# DIAGNOSTICO: QUE TARDA, CUANTAS HAY A LA VEZ, Y SI EL BUCLE SE FRENA
# ---------------------------------------------------------------------------
#
# Que una ruta rapida espere detras de una pesada demuestra contencion, no
# donde esta. Tres causas dan predicciones distintas y hay que poder
# distinguirlas con datos y no con una explicacion plausible:
#
#   * el bucle de asyncio bloqueado ---se frena todo, incluso lo que no
#     consulta---;
#   * el pool de hilos agotado ---se encolan las peticiones sincronas---;
#   * la base ---solo se frena lo que consulta---.
#
# `_RETRASO_DEL_BUCLE` mide la primera: una tarea que se programa para dentro de
# 100 ms y anota cuanto tardo de mas. Si el bucle esta libre, el retraso es de
# milisegundos aunque haya consultas de un minuto corriendo en hilos.
_PETICIONES: "deque" = deque(maxlen=400)
_ACTIVAS = 0
_PICO_ACTIVAS = 0
_CANDADO_DIAG = threading.Lock()
_RETRASO_DEL_BUCLE: "deque" = deque(maxlen=600)


async def _vigilar_el_bucle() -> None:
    """Anota cuanto se atrasa una tarea que pidio dormir 100 ms."""

    while True:
        antes = time.perf_counter()
        await asyncio.sleep(0.1)
        _RETRASO_DEL_BUCLE.append((time.perf_counter() - antes - 0.1) * 1000.0)


@app.get("/diagnostico/peticiones")
def diagnostico_peticiones(limite: int = 40) -> dict:
    """Lo que este proceso vio: tiempos por peticion y retraso del bucle.

    No mide la base ni el navegador: mide **este** proceso, que es la pieza
    sobre la que se estaba conjeturando.
    """

    ultimas = list(_PETICIONES)[-max(1, min(limite, 400)):]
    lentas = sorted(_PETICIONES, key=lambda x: -x["ms"])[:10]
    retrasos = sorted(_RETRASO_DEL_BUCLE)
    def q(p):
        return round(retrasos[min(len(retrasos) - 1, int(p * len(retrasos)))], 2) if retrasos else None
    return {
        "peticiones_recientes": ultimas,
        "las_mas_lentas": lentas,
        "activas_ahora": _ACTIVAS,
        "pico_de_activas": _PICO_ACTIVAS,
        "retraso_del_bucle_ms": {
            "muestras": len(retrasos),
            "p50": q(0.5), "p95": q(0.95), "p99": q(0.99),
            "maximo": round(retrasos[-1], 2) if retrasos else None,
            "que_significa": ("cuanto se atrasa una tarea que pidio dormir 100 ms. "
                              "Milisegundos = el bucle esta libre; segundos = hay "
                              "trabajo sincrono corriendo dentro del bucle"),
        },
        "hilos_del_pool": _tamano_del_pool(),
    }


def _tamano_del_pool() -> Any:
    """Cuantos hilos puede usar FastAPI para las rutas declaradas con `def`."""

    try:
        from anyio import to_thread

        return to_thread.current_default_thread_limiter().total_tokens
    except Exception:  # pragma: no cover - depende de la version de anyio
        return None


@app.middleware("http")
async def anotar_tiempos(request, call_next):
    """Registra cuanto tardo cada peticion y cuantas hubo a la vez."""

    global _ACTIVAS, _PICO_ACTIVAS
    with _CANDADO_DIAG:
        _ACTIVAS += 1
        if _ACTIVAS > _PICO_ACTIVAS:
            _PICO_ACTIVAS = _ACTIVAS
    inicio = time.perf_counter()
    try:
        return await call_next(request)
    finally:
        ms = (time.perf_counter() - inicio) * 1000.0
        with _CANDADO_DIAG:
            _ACTIVAS -= 1
            activas = _ACTIVAS
        ruta = request.url.path
        if request.url.query:
            ruta += "?" + request.url.query[:80]
        # El propio diagnostico no se anota: se estaria midiendo a si mismo.
        if not ruta.startswith("/diagnostico"):
            _PETICIONES.append({"ruta": ruta, "ms": round(ms, 1),
                                "activas_al_terminar": activas})


@app.middleware("http")
async def permitir_medir_los_tiempos(request, call_next):
    """Deja que una pagina de otro origen lea los tiempos de sus consultas.

    Sin esta cabecera, `PerformanceResourceTiming` de una respuesta de otro
    origen viene opaca: `transferSize` da 0 y las marcas intermedias quedan en
    cero. El tablero se sirve en el puerto 3000 y la API en el 8000, de modo que
    **toda** medicion hecha desde el navegador informaba cero bytes ---y eso no
    es un dato faltante, es un dato falso que parece medido.

    Es una cabecera de observabilidad: expone cuanto tardo y cuanto peso una
    respuesta que ese origen ya tiene permitido leer entera por CORS. No abre
    nada que no estuviera abierto.
    """

    respuesta = await call_next(request)
    respuesta.headers["Timing-Allow-Origin"] = "*"
    return respuesta

# Los origenes salen del entorno. Estaban escritos aca y por eso el tablero solo
# podia servirse desde `localhost:3000`; el motivo completo esta en
# `backend/config.py`, junto a los valores por omision, que son estos mismos.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGENES,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Los endpoints de escritura viven en su propio modulo: iniciar y detener
# captura, importar datasets y borrar una sesion persistida.
app.include_router(ingesta.router)

# Lectura de una sesion persistida ---series por distancia, trazado, estado del
# vehiculo, clima, avisos y catalogo--- y el modulo de analisis, que hasta aqui
# no tenia ninguna ruta.
app.include_router(api_sesion.router)
app.include_router(api_analisis.router)


LIMITE_MUESTRAS_MAXIMO = 200000


def _validar_limite(limite: int) -> None:
    """Rechaza un limite fuera de rango en vez de recortarlo en silencio."""
    if limite < 1 or limite > LIMITE_MUESTRAS_MAXIMO:
        raise HTTPException(
            status_code=400,
            detail=f"`limite` debe estar entre 1 y {LIMITE_MUESTRAS_MAXIMO}.",
        )


# QUE UN DESPLIEGUE SE VEA SIN VACIAR EL CACHE A MANO.
#
# `StaticFiles` manda `ETag` y `Last-Modified`, pero no manda `Cache-Control`, y
# sin esa cabecera el navegador **no pregunta**: aplica una frescura heuristica
# ---una fraccion del tiempo transcurrido desde la ultima modificacion--- y
# sirve lo que tiene guardado. Delante hay ademas una red de distribucion que
# trata a un `.css` como un archivo estatico cualquiera.
#
# El resultado es que copiar el tablero a la Raspberry no alcanza para verlo.
# Paso: la hoja de estilos ya era la nueva en el disco de la Raspberry y en la
# respuesta de la API, y el navegador seguia dibujando la vieja. El tablero pide
# sus archivos por nombre pelado ---`styles.css`, sin version--- de modo que no
# hay nada en la direccion que le avise al cache que el contenido cambio.
#
# `no-cache` no significa no guardar, que es `no-store`: significa preguntar
# antes de usar lo guardado. Con el `ETag` que ya se manda, esa pregunta se
# contesta casi siempre con un 304 sin cuerpo, asi que no cuesta el archivo.
class TableroQueSeRevalida(StaticFiles):
    """Los archivos del tablero, con la obligacion de preguntar antes de usarse."""

    def file_response(self, *args, **kwargs):
        respuesta = super().file_response(*args, **kwargs)
        respuesta.headers["Cache-Control"] = "no-cache"
        return respuesta


def _tablero_revalidado(ruta: Path) -> FileResponse:
    """La misma obligacion, para lo que no pasa por el montaje."""

    return FileResponse(ruta, headers={"Cache-Control": "no-cache"})


@app.get("/")
def root():
    """El estado del backend, o el tablero cuando esta aplicacion lo sirve.

    Sin `SERVIR_TABLERO` devuelve exactamente lo que devolvia siempre: dos
    servidores, cada uno con su raiz. Con el encendido, la raiz del dominio
    tiene que ser el tablero y no un JSON, que es lo que espera quien escribe
    el nombre en la barra de direcciones.
    """

    if SERVIR_TABLERO:
        return _tablero_revalidado(Path(DIRECTORIO_TABLERO) / "index.html")
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
    """Devuelve la ultima muestra disponible de cada señal."""

    return obtener_ultimos_por_senal()


@app.get("/telemetry/by-session/{session_id}")
def telemetry_by_session(session_id: str, limit: int = 100) -> list[dict]:
    """Devuelve mensajes persistidos pertenecientes a una sesion concreta."""

    return obtener_mensajes_por_sesion(session_id, limit)


@app.get("/can/recorrido/{session_id}")
def can_recorrido(session_id: str, limite: int = 80000) -> dict:
    """Recorrido reconstruido de un segmento de bus vehicular.

    El registro del vehiculo de calle **no trae coordenadas**: la forma del
    recorrido se obtiene integrando velocidad y velocidad de guinada. Es una
    derivacion declarada y no una medicion de posicion, y la respuesta lo dice
    en su propio contenido para que ningun consumidor pueda usarla como si
    fuera lo otro.

    Se devuelve tambien el ancho de via que se deduce de la guinada y las cuatro
    ruedas. No es un adorno: es la comprobacion, por una via independiente, de
    que la senal sobre la que se integra esta bien decodificada.
    """

    # El tope cuenta filas, no muestras: seis senales de un segmento de un minuto
    # suman unas veintiseis mil. Un tope de veinte mil truncaba el recorrido a un
    # tercio sin avisar, que es de las peores formas de equivocarse porque el
    # resultado sigue pareciendo un recorrido.
    series = db.obtener_series_de_senales(
        session_id,
        ("speed", "yaw_rate") + recorrido.RUEDAS,
        can_rav4.SOURCE_TYPE,
        limite)
    if not series.get("speed") or not series.get("yaw_rate"):
        raise HTTPException(
            status_code=404,
            detail=f"La sesion {session_id} no tiene velocidad y guinada juntas.")

    trazado = recorrido.reconstruir(series)
    validacion = recorrido.validar_contra_ruedas(series)

    # DE QUE INSTANTE CUELGA EL CERO.
    #
    # Las marcas son milisegundos **desde la primera muestra**, y eso no es un
    # descuido: lo que se integra son diferencias, y la fecha de origen de un
    # segmento de bus es una asignacion declarada y no un dato del registro
    # ---ver `db.obtener_series_de_senales`---. Convertirlas a UTC aca les daria
    # una precision que no tienen.
    #
    # Pero sin saber de donde cuelga el cero, la forma no se puede cruzar con
    # ninguna otra serie. Se declara el origen, con su naturaleza: quien quiera
    # atar el recorrido a una senal suma, y quien quiera saber de donde salio
    # ese instante lo tiene escrito al lado.
    origen = catalogo_sesiones.rango_de(session_id, can_rav4.SOURCE_TYPE)
    return {
        "session_id": session_id,
        # CADA PUNTO LLEVA SU INSTANTE.
        #
        # `reconstruir` ya calculaba una marca por punto ---integra sobre pares
        # de muestras y sabe entre que dos instantes avanzo--- y esta respuesta
        # la descartaba. Sin ella la forma es un dibujo suelto: se la puede
        # mirar, pero no se la puede cruzar con ninguna senal, porque nada dice
        # que punto corresponde a que momento. Con la marca, el mismo instante
        # que ya comparten los instrumentos ubica tambien al vehiculo sobre el
        # recorrido, y la traza se puede pintar por lo que se estaba midiendo.
        #
        # Va en milisegundos UTC, que es la unidad en que la reconstruccion
        # empareja las series: convertirla aca seria inventar una precision que
        # el emparejamiento no tiene.
        "puntos": [{"x": round(x, 2), "y": round(y, 2), "t_ms": t}
                   for x, y, t in zip(trazado["x"], trazado["y"],
                                      trazado["marcas_ms"])],
        "recorrido_m": round(trazado["recorrido_m"], 1),
        "extension_x_m": round(trazado["extension_x_m"], 1),
        "extension_y_m": round(trazado["extension_y_m"], 1),
        "rumbo_final_deg": round(trazado["rumbo_final_deg"], 1),
        "huecos_saltados": trazado["huecos_saltados"],
        "validacion_guinada": {
            "muestras": validacion["muestras"],
            "ancho_de_via_m": (round(validacion["ancho_de_via_m"], 3)
                               if validacion["muestras"] else None),
            "correlacion": (round(validacion["correlacion"], 3)
                            if validacion["muestras"] else None),
        },
        "eje_temporal": {
            "campo": "t_ms",
            "unidad": "ms",
            "referencia": "milisegundos desde la primera muestra del segmento",
            "origen_utc": origen,
            "naturaleza_del_origen": (
                "instante declarado al cargar el segmento, no medido por el "
                "registro: sirve para alinear, no para fechar"),
        },
        # Va en la respuesta y no solo en la documentacion: quien consuma esto
        # tiene que poder saber que no es una posicion medida sin leer nada mas.
        "naturaleza": "derivado",
        "advertencia": ("Forma reconstruida por integracion, sin coordenadas. "
                        "La orientacion absoluta y la ubicacion en el mundo no "
                        "son recuperables."),
    }


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
    # CORRECCION DEL 2026-09-06. Lo que este docstring afirmaba dejo de ser
    # cierto al comprimirse la tabla: `listar_corridas_replay_acotado` tardo
    # **302,3 segundos** en devolver una corrida, y este modo del tablero no
    # llegaba a cargar. La enumeracion por saltos de indice se apoya en
    # `replay_run_id`, que **no es columna de segmentacion** de la compresion,
    # de modo que cada salto degrada a recorrer y descomprimir.
    #
    # Se sirve desde un catalogo mantenido, que responde en milisegundos y cuyo
    # costo si es independiente del volumen. La funcion anterior se conserva:
    # sigue siendo la definicion correcta de que es una corrida, y es de donde
    # el catalogo saldria si hubiera que rehacerlo sin esta tabla.
    return catalogo_corridas.listar(session_key)


@app.get("/racing/sessions/{session_key}/replay-series")
def racing_replay_series(
    session_key: int,
    replay_run_id: str,
    drivers: list[int] = Query(..., min_length=1),
    signal: str = Query(..., min_length=1),
    limite: int = LIMITE_FILAS_REPLAY,
) -> list[dict]:
    """Expone una serie temporal OpenF1 filtrada por ejecucion, pilotos y señal."""

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

    # ESTO SI IMPIDE ARRANCAR, Y A PROPOSITO.
    #
    # Todo lo demas de esta funcion esta escrito para que un fallo no tumbe el
    # servicio: si el intermediario no responde, el historico se sigue sirviendo.
    # La verificacion de secretos es la excepcion, porque lo que detecta no es
    # una indisponibilidad sino una configuracion que no deberia existir: la
    # contrasena que el repositorio publica, apuntando a una base que no es esta
    # maquina. Seguir sirviendo en ese caso seria seguir exponiendola.
    #
    # Mientras la base sea local no cambia absolutamente nada.
    config.verificar_secretos()

    live_stream.difusor.iniciar(asyncio.get_running_loop())

    # La matriz se calcula midiendo sobre lo persistido y tarda decenas de
    # segundos. Se calienta al arrancar y en segundo plano, para que la primera
    # consulta no la pague y para que un fallo aca no impida servir el resto.
    async def _calentar_matriz() -> None:
        try:
            await asyncio.to_thread(matriz_fuentes.construir)
        except Exception as error:  # noqa: BLE001
            print(f"[matriz] no se pudo precalcular: {type(error).__name__}: {error}")

    asyncio.create_task(_calentar_matriz())
    asyncio.create_task(_vigilar_el_bucle())


@app.on_event("shutdown")
async def _detener_difusor() -> None:
    live_stream.difusor.detener()


@app.get("/live/status")
def live_status() -> dict:
    """Estado del camino en vivo, para distinguir 'sin datos' de 'sin conexion'."""

    return live_stream.difusor.estado()


# Cuanto vale una respuesta antes de volver a preguntarle a la base. La vista
# consulta cada pocos segundos y el indicador cambia despacio: sin vigencia,
# mirar la persistencia le costaria a la base mas que guardarla.
VIGENCIA_PERSISTENCIA_S = 5.0
_CACHE_PERSISTENCIA: tuple[float, dict] | None = None


# Donde viven las capturas y sus metadatos. La parrilla se sirve desde ahi y no
# desde la base, porque no es una medicion: es identidad de sesion.
CAPTURAS = Path(__file__).resolve().parents[1] / "datasets" / "f1_25" / "capturas"


@app.get("/fuentes/matriz")
def fuentes_matriz() -> dict:
    """Que puede medirse en cada fuente y con que resolucion.

    No es una lista de senales: es el contraste entre las tres, organizado por
    magnitud fisica. **Ese contraste es en si mismo un resultado del trabajo**,
    porque es lo que decide que analisis habilita cada fuente.

    Las ausencias figuran con su motivo, y los motivos no son equivalentes: que
    un vehiculo de calle no tenga aleron movil es un limite del objeto; que la
    fuente deportiva no exponga la aceleracion es un limite del acceso, porque el
    vehiculo si la mide.
    """

    return matriz_fuentes.construir()


@app.get("/live/parrilla")
def live_parrilla(sesion: str | None = None) -> dict:
    """Quien es cada vehiculo de una sesion capturada.

    Existe porque la parrilla **no esta en la base a proposito**. Guardar el
    nombre de un conductor como senal de telemetria almacenaria el mismo texto
    casi siete mil veces para decir veintidos cosas que no cambian, y pondria
    identidad en una tabla de mediciones.

    Vive entonces donde vive el resto de lo que describe a la sesion —circuito,
    tipo, clima, ajustes—: en la procedencia derivada del flujo, que el capturador
    escribe junto a cada archivo crudo. Este endpoint la lee de ahi.

    **Limite declarado:** la procedencia se escribe al cerrar la captura, de modo
    que una sesion en curso todavia no tiene parrilla servible. Se resuelve solo
    cuando la sesion termina, y de forma completa cuando exista el catalogo de
    sesiones persistidas que el cronograma tiene previsto.
    """

    if not CAPTURAS.is_dir():
        return {"disponible": False, "motivo": "no hay directorio de capturas"}

    encontradas = []
    for meta in sorted(CAPTURAS.glob("*.meta.json")):
        try:
            datos = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        procedencia = datos.get("procedencia") or {}
        parrilla = procedencia.get("parrilla")
        if not parrilla:
            continue
        uid = procedencia.get("session_uid")
        identificador = f"f1_25:session:{uid}" if uid is not None else None
        if sesion is not None and identificador != sesion:
            continue
        encontradas.append({
            "sesion": identificador,
            "captura": datos.get("archivo"),
            "circuito": procedencia.get("circuito"),
            "tipo_sesion": procedencia.get("tipo_sesion"),
            "vehiculo_propio": procedencia.get("indice_vehiculo_propio"),
            "parrilla": parrilla,
        })

    if sesion is not None:
        if not encontradas:
            return {"disponible": False, "sesion": sesion,
                    "motivo": "ninguna captura cerrada declara esa sesion"}
        return {"disponible": True, **encontradas[0]}
    return {"disponible": True, "sesiones": encontradas}


@app.get("/live/senales")
def live_senales() -> dict:
    """Catalogo completo de senales que la fuente puede producir.

    La vista en vivo arma su catalogo con lo que va llegando, y eso deja un
    hueco: **con el flujo detenido no hay nada que elegir**, aunque la sesion
    tenga ochenta y nueve canales. Quien abre la pagina fuera de una sesion
    veria un catalogo vacio, que dice algo falso: no es que no haya canales, es
    que en ese instante no llega ninguno.

    El catalogo se le pide al adaptador y no a la base. La base solo sabe que
    senales **llegaron a guardarse**, que es exactamente lo que fallaba cuando
    el capturador publicaba dos paquetes de cuatro: preguntarle habria devuelto
    el alcance incompleto como si fuera el alcance real.
    """

    return {"disponible": True, "senales": f1_25_adapter.catalogo_de_senales()}


@app.get("/live/persistencia")
def live_persistencia() -> dict:
    """Evidencia de que la base esta recibiendo mientras la vista corre.

    Existe porque la vista en vivo declara que no pasa por la base, y esa frase
    —cierta— se lee como que el dato no se guarda. En lugar de explicarlo con
    una aclaracion, la vista muestra **el estado real de la persistencia**: la
    ultima marca temporal almacenada y cuantas filas entraron en el ultimo
    minuto de datos.

    El conteo se acota a una ventana en lugar de contar la sesion entera: una
    sesion de carrera supera los dos millones de filas y contarlas en cada
    consulta convertiria un indicador en una carga.
    """

    global _CACHE_PERSISTENCIA
    ahora = time.monotonic()
    if _CACHE_PERSISTENCIA and ahora - _CACHE_PERSISTENCIA[0] < VIGENCIA_PERSISTENCIA_S:
        return {**_CACHE_PERSISTENCIA[1],
                "edad_del_dato_s": round(ahora - _CACHE_PERSISTENCIA[0], 1)}

    # La sesion se toma del propio flujo en vivo. No es una comodidad: el indice
    # de la tabla empieza por fuente y sesion, de modo que preguntar sin la
    # sesion obliga a recorrer todas y la consulta pasa de 260 ms a 3,5 s.
    sesion = None
    if live_stream.difusor.recientes:
        sesion = live_stream.difusor.recientes[-1].get("session_id")

    ventana_s = 60
    try:
        with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
            if sesion is None:
                cursor.execute(
                    """select session_id from telemetry_messages
                       where source_type = %s
                       order by timestamp desc limit 1""",
                    (f1_25_adapter.SOURCE_TYPE,),
                )
                fila = cursor.fetchone()
                sesion = fila[0] if fila else None
            if sesion is None:
                respuesta = {"disponible": True, "filas_recientes": 0,
                             "ultimo_dato": None, "ventana_s": ventana_s,
                             "motivo": "todavia no hay datos de esta fuente en la base"}
                _CACHE_PERSISTENCIA = (ahora, respuesta)
                return respuesta

            cursor.execute(
                """select max(timestamp) from telemetry_messages
                   where source_type = %s and session_id = %s""",
                (f1_25_adapter.SOURCE_TYPE, sesion),
            )
            ultima = cursor.fetchone()[0]
            cursor.execute(
                """select count(*), count(distinct signal_name)
                   from telemetry_messages
                   where source_type = %s and session_id = %s
                     and timestamp > %s - make_interval(secs => %s)""",
                (f1_25_adapter.SOURCE_TYPE, sesion, ultima, ventana_s),
            )
            filas, senales = cursor.fetchone()
    except Exception as error:
        # Que la base no responda no debe romper la vista en vivo: son caminos
        # independientes, y mostrarlo asi es justamente lo que se quiere decir.
        return {"disponible": False, "motivo": f"{type(error).__name__}: {error}"}

    respuesta = {
        "disponible": True,
        "sesion": sesion,
        "ultimo_dato": ultima.isoformat() if ultima else None,
        "ventana_s": ventana_s,
        "filas_recientes": filas,
        "senales_distintas": senales,
    }
    _CACHE_PERSISTENCIA = (ahora, respuesta)
    return respuesta


@app.get("/live/anotaciones")
def live_anotaciones() -> dict:
    """Lo que los anotadores declararon durante la sesion en curso.

    Hay **un anotador por vehiculo**: uno solo compondria instantes con canales de
    dos autos distintos y podria declarar incidentes que no ocurrieron.

    La vista lo pide al abrirse para no arrancar con la lista vacia cuando ya
    ocurrieron cosas, y despues las recibe por el flujo a medida que se emiten.
    """

    difusor = live_stream.difusor
    por_vehiculo = {}
    for vehiculo, anotador in difusor.anotadores.items():
        por_vehiculo[vehiculo] = {
            "anotaciones": list(anotador.anotaciones),
            "mensajes_observados": anotador.observados,
            "curvas_del_circuito": len(anotador.catalogo.curvas),
            # Una regla cuyo canal no llega **no dice que no paso nada**: dice
            # que no pudo mirarse. Declararlo evita que la ausencia de
            # anotaciones se lea como ausencia de incidentes.
            "reglas_evaluables": {
                "fuera de pista": all(f"surface_type_{r}" in anotador.ultimos
                                      for r in anotador_vivo.RUEDAS),
                "impacto vertical": "g_force_vertical" in anotador.ultimos,
                "perdida de tren trasero": any(
                    f"wheel_slip_ratio_{r}" in anotador.ultimos
                    for r in ("rear_left", "rear_right")),
                "caida brusca de velocidad": "speed" in anotador.ultimos,
                "aleron movil": "drs_allowed" in anotador.ultimos,
            },
        }

    return {
        "conservadas": anotador_vivo.ANOTACIONES_CONSERVADAS,
        "vehiculos": por_vehiculo,
    }


@app.get("/live/historia")
def live_historia() -> dict:
    """Lo que ya paso, por vehiculo y por senal, para quien abre la vista tarde.

    Sin esto la vista arrancaba en el instante de conectarse: abrir la pagina a
    mitad de una vuelta mostraba las trazas vacias, como si antes no hubiera
    ocurrido nada. **La vista empezaba cuando miraba el observador y no cuando
    empezo el vehiculo**, que es lo que quien mira espera ver.

    Se agrupa por vehiculo porque en pantalla dividida hay dos conductores
    publicando las mismas senales, y una serie que los mezclara no describiria a
    ninguno de los dos.

    Cada serie viaja con su eje temporal y, cuando existe, con la distancia
    recorrida: **es lo que permite alinear dos conductores por lugar del circuito
    en lugar de por reloj**, que es como se comparan dos vueltas.
    """

    difusor = live_stream.difusor
    return {
        "muestras_por_senal": live_stream.MUESTRAS_POR_SENAL,
        "vehiculos": {
            vehiculo: {
                "series": {senal: list(valores)
                           for senal, valores in senales.items()},
                "tiempos": {senal: list(marcas) for senal, marcas
                            in difusor.historia_tiempos.get(vehiculo, {}).items()},
                "distancia": list(difusor.historia_distancia.get(vehiculo, [])),
            }
            for vehiculo, senales in difusor.historia.items()
        },
    }


@app.get("/live/resumen")
def live_resumen() -> dict:
    """La sesión entera a resolución reducida, para un eje que crece.

    La ventana de \\texttt{/live/historia} conserva treinta segundos y descarta lo
    anterior, de modo que el eje del gráfico **se desplaza**: lo viejo sale por la
    izquierda. Con eso, una anotación de hace dos minutos no tiene dónde
    dibujarse, y por eso las anotaciones vivían en una lista aparte, desconectadas
    de las trazas.

    Este recurso devuelve **toda** la sesión, con un intervalo por segundo. Cada
    intervalo lleva su instante, su mínimo, su máximo y cuántas muestras lo
    formaron.

    **El mínimo y el máximo, y no un valor representativo.** Una miniatura mide
    trescientos cincuenta píxeles y no puede dibujar veinte muestras por segundo;
    pero quedarse con una de cada veinte borraría el pico de una frenada, que dura
    menos que el intervalo reducido. El gráfico saldría más suave que la
    conducción que describe, y justo en los instantes que las anotaciones señalan.
    Conservando los dos extremos, **lo que el gráfico dibuja como pico ocurrió, y
    lo que no dibuja no ocurrió**.
    """

    resumen = live_stream.difusor.resumen
    return {
        "intervalo_s": resumen_sesion.INTERVALO_S,
        "formato": ["segundo", "minimo", "maximo", "muestras"],
        # El instante absoluto de la primera muestra. Las anotaciones viajan con
        # el reloj de la sesión y esta serie con el tiempo transcurrido; sin un
        # origen común no se las puede ubicar sobre la traza.
        "origen_s": resumen.origen,
        "vehiculos": resumen.vehiculos(),
    }


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


# EL TABLERO, SERVIDO POR ESTA MISMA APLICACION CUANDO SE LO PIDE.
#
# Va **al final del archivo a proposito**: un montaje en `/` atrapa todo lo que
# no haya coincidido antes, de modo que tiene que registrarse despues de la
# ultima ruta de la API. Puesto mas arriba se comeria los endpoints declarados
# debajo de el, y en silencio.
#
# `html=True` hace que un directorio resuelva a su `index.html`, que es lo que
# espera un tablero servido desde la raiz de un dominio.
#
# Apagado por omision: en desarrollo siguen siendo dos servidores. El por que de
# encenderlo hacia afuera esta en `backend/config.py`.
if SERVIR_TABLERO:
    app.mount("/", TableroQueSeRevalida(directory=DIRECTORIO_TABLERO, html=True),
              name="tablero")
