"""Normaliza telemetria decodificada de F1 25 hacia el contrato interno.

Esta es la capa de adaptacion de la tercera via de entrada. Recibe la salida del
decodificador de `backend/f1_udp.py` y produce mensajes canonicos, sin conocer
nada del transporte ni de la base de datos.

Que se declara y por que
------------------------
**El dato es simulado y se declara como tal.** El `source_type` y el indicador
de calidad lo dicen en cada mensaje, no solo en la sesion, de modo que un valor
suelto en la base siga siendo identificable.

**La procedencia es obligatoria.** Cada mensaje transporta la version del
decodificador, la version de formato del protocolo, el identificador de sesion
del juego, el numero de marco y el origen de adquisicion. Con eso, un dato ya
guardado permite reconstruir con que codigo se decodifico y de que emision vino.

**La transformacion se declara por senal.** El acelerador y el freno llegan del
protocolo en el rango cero a uno y se convierten a porcentaje para coincidir con
la convencion del contrato; el resto de las senales pasa sin alterarse. Cada
mensaje dice cual de los dos casos es. Declarar una transformacion uniforme
cuando algunas senales se convierten y otras no vuelve inutil el campo.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

SOURCE_TYPE = "f1_25_udp_simulation"
QUALITY_FLAG = "simulated_f1_25"
VERSION_ADAPTADOR = "f1-25-adapter-v1"

# Origen de adquisicion. Se declara en cada mensaje porque un dato capturado en
# vivo y uno reinyectado desde una captura no sostienen las mismas afirmaciones
# sobre latencia, aunque sus valores sean identicos.
ORIGEN_EN_VIVO = "consola_en_vivo"
ORIGEN_REPRODUCIDO = "captura_reproducida"

# Senales del paquete de telemetria: campo decodificado -> nombre canonico,
# unidad, factor de escala. Un factor de 1,0 significa que el valor pasa sin
# alterarse.
SENALES_TELEMETRIA: dict[str, tuple[str, str, float]] = {
    "speed_kmh": ("speed", "km/h", 1.0),
    "throttle": ("throttle_position", "%", 100.0),
    "brake": ("brake_position", "%", 100.0),
    "steer": ("steering_normalized", "ratio", 1.0),
    "gear": ("gear_selected", "gear", 1.0),
    "engine_rpm": ("engine_speed", "rpm", 1.0),
    "engine_temperature_c": ("engine_temperature", "celsius", 1.0),
}

# Senales del paquete de datos de vuelta.
SENALES_VUELTA: dict[str, tuple[str, str, float]] = {
    "lap_distance_m": ("lap_distance", "m", 1.0),
    "total_distance_m": ("session_distance", "m", 1.0),
    "current_lap_time_ms": ("current_lap_time", "ms", 1.0),
    "current_lap_num": ("lap_number", "lap", 1.0),
    "car_position": ("track_position_order", "position", 1.0),
}


class ErrorNormalizacion(Exception):
    """El paquete decodificado no permite construir mensajes canonicos."""


def _marca_temporal(inicio_captura_utc: str, session_time_s: float) -> str:
    """Convierte el reloj de sesion del juego en una marca absoluta.

    El protocolo entrega segundos desde el inicio de la sesion, no una fecha.
    Para ubicar el dato en el tiempo hace falta el instante en que empezo la
    captura, que es un dato del operador y no del protocolo. Por eso es un
    parametro obligatorio y no un valor por defecto: inventarlo produciria una
    marca temporal falsa con apariencia de verdadera.
    """

    try:
        inicio = datetime.fromisoformat(inicio_captura_utc)
    except ValueError as error:
        raise ErrorNormalizacion(
            f"Inicio de captura no interpretable: {inicio_captura_utc!r}"
        ) from error
    if inicio.tzinfo is None:
        inicio = inicio.replace(tzinfo=timezone.utc)
    return (inicio + timedelta(seconds=session_time_s)).isoformat()


def mensajes_desde_paquete(
    decodificado: dict[str, Any],
    inicio_captura_utc: str,
    origen: str = ORIGEN_EN_VIVO,
    captura_sha256: str | None = None,
    solo_vehiculo_propio: bool = True,
) -> list[dict[str, Any]]:
    """Convierte un paquete decodificado en mensajes canonicos por senal.

    Por defecto normaliza unicamente el vehiculo propio. Los demas vehiculos de
    la sesion son terceros: en modo de un solo jugador no existen, y en
    multijugador el protocolo restringe sus datos. Emitirlos por defecto
    contradiria la restriccion de alcance del trabajo.
    """

    if not decodificado.get("decodificado"):
        raise ErrorNormalizacion(
            f"El paquete {decodificado.get('paquete')} no fue decodificado; "
            "no hay campos que normalizar."
        )
    if origen not in (ORIGEN_EN_VIVO, ORIGEN_REPRODUCIDO):
        raise ErrorNormalizacion(f"Origen de adquisicion desconocido: {origen!r}")

    paquete = decodificado["paquete"]
    if paquete == "car_telemetry":
        mapa = SENALES_TELEMETRIA
    elif paquete == "lap_data":
        mapa = SENALES_VUELTA
    else:
        raise ErrorNormalizacion(f"Paquete sin normalizacion definida: {paquete}")

    cabecera = decodificado["cabecera"]
    session_uid = cabecera["session_uid"]
    indice_propio = cabecera["player_car_index"]
    marca = _marca_temporal(inicio_captura_utc, cabecera["session_time"])

    if solo_vehiculo_propio:
        seleccion = [(indice_propio, decodificado["vehiculo_propio"])]
    else:
        seleccion = list(enumerate(decodificado["vehiculos"]))

    mensajes: list[dict[str, Any]] = []
    for indice, vehiculo in seleccion:
        comun = {
            "timestamp": marca,
            "vehicle_id": f"f1_25:session:{session_uid}:car:{indice}",
            "driver_id": f"f1_25:car:{indice}",
            "session_id": f"f1_25:session:{session_uid}",
            "lap_id": None,
            "source_type": SOURCE_TYPE,
            "quality_flag": QUALITY_FLAG,
            "track_segment_id": None,
            "sector_id": None,
            "curve_id": None,
        }
        for campo, (nombre, unidad, factor) in mapa.items():
            if campo not in vehiculo:
                continue
            crudo = vehiculo[campo]
            if unidad == "bool":
                valor: Any = bool(crudo)
            elif factor == 1.0:
                valor = crudo
            else:
                valor = round(crudo * factor, 4)

            mensajes.append({
                **comun,
                "signal_name": nombre,
                "value": valor,
                "unit": unidad,
                "metadata": {
                    "can_id": None,
                    "src": None,
                    "reference_type": "f1_25_udp",
                    "reference_id": f"session:{session_uid}/car:{indice}",
                    "extra": {
                        "simulated": True,
                        "origen_adquisicion": origen,
                        "version_adaptador": VERSION_ADAPTADOR,
                        "version_decodificador": decodificado["version_decodificador"],
                        "packet_format": cabecera["packet_format"],
                        "packet_id": decodificado["packet_id"],
                        "paquete": paquete,
                        "session_uid": session_uid,
                        "frame_identifier": cabecera["frame_identifier"],
                        "session_time_s": cabecera["session_time"],
                        "player_car_index": indice_propio,
                        "campo_origen": campo,
                        # Se declara por senal y no por mensaje uniforme: algunas
                        # se convierten y otras no.
                        "transformation": "identity" if factor == 1.0 else f"escala_x{factor:g}",
                        "captura_sha256": captura_sha256,
                    },
                },
            })

    if not mensajes:
        raise ErrorNormalizacion(
            f"El paquete {paquete} no aporto ninguna senal conocida."
        )
    return mensajes


# El estado del alerón móvil se normaliza aparte porque es booleano y su
# contraste con la fuente deportiva es un resultado del trabajo: alli el mismo
# concepto llega como un codigo de estado con valores indeterminados que hubo
# que resolver por medicion, y aqui como un booleano documentado.
def mensaje_drs(
    decodificado: dict[str, Any],
    inicio_captura_utc: str,
    origen: str = ORIGEN_EN_VIVO,
) -> dict[str, Any]:
    """Construye el mensaje del estado del aleron movil del vehiculo propio."""

    if decodificado.get("paquete") != "car_telemetry":
        raise ErrorNormalizacion("El estado del aleron solo esta en car_telemetry.")

    base = mensajes_desde_paquete(decodificado, inicio_captura_utc, origen)[0]
    vehiculo = decodificado["vehiculo_propio"]
    mensaje = {
        **base,
        "signal_name": "drs_open",
        "value": bool(vehiculo["drs"]),
        "unit": "bool",
    }
    mensaje["metadata"] = {
        **base["metadata"],
        "extra": {
            **base["metadata"]["extra"],
            "campo_origen": "drs",
            "transformation": "bool",
        },
    }
    return mensaje
