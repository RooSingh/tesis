"""Decodificador del protocolo UDP de telemetria de F1 25.

Este modulo traduce los datagramas binarios que emite el simulador hacia
estructuras de Python, sin normalizarlos todavia al contrato interno: esa
traduccion es responsabilidad de la capa de adaptacion.

Es el segundo ejercicio de decodificacion binaria del proyecto. El primero fue
el bus CAN, donde una trama es un identificador mas ocho bytes y el significado
vive fuera, en un archivo DBC. Aca el paralelo es exacto: un datagrama es una
cabecera mas una carga util, y el significado vive fuera, en la especificacion
publicada por el fabricante. El identificador de paquete cumple el rol del
identificador de trama, y el campo de formato cumple el rol de la version del
DBC.

Procedencia de las estructuras
------------------------------
Todo lo que sigue se transcribio de `Data Output from F1 25 v3.pdf`, la
especificacion oficial de EA, archivada en `datasets/f1_25/spec/` fuera del
control de versiones por tener derechos de terceros. Su huella `sha256` es
`850199d1ea817b887b150118095c5ca86527a397d578d53fd5c83427636b92d5`, registrada
para que cualquier lector pueda comprobar que trabajo sobre el mismo documento.

La propia especificacion declara que EA no garantiza su exactitud. Por eso cada
estructura se verifica sumando sus campos contra el tamano declarado, y esa
verificacion es una prueba automatica y permanente, no un control de una sola
vez.

El prefijo `<` de los formatos
------------------------------
No indica solamente orden de bytes. En el modulo `struct` de Python tambien
significa **sin relleno de alineacion**. Omitirlo, o usar `=` o `@`, hace que el
interprete inserte bytes de relleno despues del entero de 64 bits de la
cabecera, y a partir de ahi **todos los campos siguientes quedan corridos**.

El resultado no es un error ruidoso: son valores que parecen plausibles y son
basura. Es la causa mas frecuente de fallos en este dominio, y el motivo por el
que las pruebas de tamano existen.
"""

from __future__ import annotations

import struct
from typing import Any


VERSION_DECODIFICADOR = "f1-udp-decoder-v1"

# Version de formato admitida. Se congela a proposito.
#
# El juego permite elegir el formato de salida y una actualizacion puede cambiar
# el valor por defecto. Un datagrama con otro formato se rechaza en lugar de
# intentar interpretarse: es preferible que el sistema falle de forma visible a
# que entregue campos corridos que nadie va a notar.
FORMATO_ADMITIDO = 2025


# --------------------------------------------------------------------------- #
# Errores
# --------------------------------------------------------------------------- #

class ErrorDecodificacion(Exception):
    """Base de los errores de decodificacion del protocolo."""


class FormatoNoAdmitido(ErrorDecodificacion):
    """El datagrama declara una version de formato distinta de la congelada."""


class TamanoInvalido(ErrorDecodificacion):
    """El datagrama no mide lo que su tipo de paquete declara."""


class PaqueteNoDecodificable(ErrorDecodificacion):
    """El identificador de paquete es valido pero no hay decodificador escrito."""


# --------------------------------------------------------------------------- #
# Cabecera
# --------------------------------------------------------------------------- #

# Comun a los dieciseis paquetes. 29 bytes.
CABECERA_FMT = "<HBBBBBQfIIBB"
CABECERA_TAMANO = struct.calcsize(CABECERA_FMT)

CABECERA_CAMPOS = (
    "packet_format",              # uint16: version del formato, clave de despacho
    "game_year",                  # uint8:  ultimos dos digitos del anio
    "game_major_version",         # uint8
    "game_minor_version",         # uint8
    "packet_version",             # uint8:  version de este tipo de paquete
    "packet_id",                  # uint8:  tipo de paquete, clave de despacho
    "session_uid",                # uint64: identificador unico de sesion
    "session_time",               # float:  segundos desde el inicio de sesion
    "frame_identifier",           # uint32
    "overall_frame_identifier",   # uint32: no retrocede con los flashbacks
    "player_car_index",           # uint8:  indice del auto propio en los arreglos
    "secondary_player_car_index",  # uint8: 255 si no hay segundo jugador
)


# --------------------------------------------------------------------------- #
# Catalogo de paquetes
# --------------------------------------------------------------------------- #

# Los dieciseis tipos, con el tamano total que la especificacion declara.
#
# La tabla existe aunque solo dos paquetes se decodifiquen: permite validar el
# tamano de cualquier datagrama recibido y contabilizar los que llegan sin
# decodificador, en vez de descartarlos en silencio.
PAQUETES: dict[int, dict[str, Any]] = {
    0:  {"nombre": "motion",               "tamano": 1349, "frecuencia": "menu"},
    1:  {"nombre": "session",              "tamano": 753,  "frecuencia": "2/s"},
    2:  {"nombre": "lap_data",             "tamano": 1285, "frecuencia": "menu"},
    3:  {"nombre": "event",                "tamano": 45,   "frecuencia": "evento"},
    4:  {"nombre": "participants",         "tamano": 1284, "frecuencia": "5 s"},
    5:  {"nombre": "car_setups",           "tamano": 1133, "frecuencia": "2/s"},
    6:  {"nombre": "car_telemetry",        "tamano": 1352, "frecuencia": "menu"},
    7:  {"nombre": "car_status",           "tamano": 1239, "frecuencia": "menu"},
    8:  {"nombre": "final_classification", "tamano": 1042, "frecuencia": "fin"},
    9:  {"nombre": "lobby_info",           "tamano": 954,  "frecuencia": "2/s"},
    10: {"nombre": "car_damage",           "tamano": 1041, "frecuencia": "10/s"},
    11: {"nombre": "session_history",      "tamano": 1460, "frecuencia": "20/s"},
    12: {"nombre": "tyre_sets",            "tamano": 231,  "frecuencia": "20/s"},
    13: {"nombre": "motion_ex",            "tamano": 273,  "frecuencia": "menu"},
    14: {"nombre": "time_trial",           "tamano": 101,  "frecuencia": "1/s"},
    15: {"nombre": "lap_positions",        "tamano": 1131, "frecuencia": "1/s"},
}

# Cantidad de vehiculos en los paquetes que llevan un arreglo por auto.
VEHICULOS = 22


# --------------------------------------------------------------------------- #
# Car Telemetry, paquete 6
# --------------------------------------------------------------------------- #

# Una entrada por vehiculo. 60 bytes.
#
# `m_gear` es int8 y no uint8: admite -1 para la marcha atras. Tipearlo como sin
# signo devolveria 255 en lugar de -1, y ademas no alteraria el tamano, de modo
# que la prueba aritmetica no lo detectaria. Por eso hay una prueba de valor
# dedicada a este campo.
CAR_TELEMETRY_FMT = "<HfffBbHBBH4H4B4BH4f4B"
CAR_TELEMETRY_TAMANO = struct.calcsize(CAR_TELEMETRY_FMT)

# Tres campos finales del paquete, despues del arreglo de vehiculos.
CAR_TELEMETRY_COLA_FMT = "<BBb"
CAR_TELEMETRY_COLA_TAMANO = struct.calcsize(CAR_TELEMETRY_COLA_FMT)


def _desempaquetar_car_telemetry(bruto: tuple) -> dict[str, Any]:
    """Nombra los campos de un vehiculo del paquete de telemetria."""

    return {
        "speed_kmh": bruto[0],
        "throttle": bruto[1],            # 0,0 a 1,0
        "steer": bruto[2],               # -1,0 tope izquierdo a 1,0 tope derecho
        "brake": bruto[3],               # 0,0 a 1,0
        "clutch": bruto[4],              # 0 a 100
        "gear": bruto[5],                # 1 a 8, N=0, R=-1
        "engine_rpm": bruto[6],
        "drs": bruto[7],                 # 0 cerrado, 1 abierto
        "rev_lights_percent": bruto[8],
        "rev_lights_bit_value": bruto[9],
        "brakes_temperature_c": list(bruto[10:14]),
        "tyres_surface_temperature_c": list(bruto[14:18]),
        "tyres_inner_temperature_c": list(bruto[18:22]),
        "engine_temperature_c": bruto[22],
        "tyres_pressure_psi": list(bruto[23:27]),
        "surface_type": list(bruto[27:31]),
    }


# --------------------------------------------------------------------------- #
# Lap Data, paquete 2
# --------------------------------------------------------------------------- #

# Una entrada por vehiculo. 57 bytes.
#
# Los quince campos de un byte consecutivos van entre los tres flotantes de
# distancia y los dos enteros de tiempos de boxes. Se escriben como `"B" * 15`
# en lugar de quince letras seguidas para que el conteo sea legible: una letra
# de mas o de menos aca desplaza todo lo que sigue.
LAP_DATA_FMT = "<IIHBHBHBHBfff" + "B" * 15 + "HHBfB"
LAP_DATA_TAMANO = struct.calcsize(LAP_DATA_FMT)

# Dos campos finales del paquete, despues del arreglo de vehiculos.
LAP_DATA_COLA_FMT = "<BB"
LAP_DATA_COLA_TAMANO = struct.calcsize(LAP_DATA_COLA_FMT)


def _desempaquetar_lap_data(bruto: tuple) -> dict[str, Any]:
    """Nombra los campos de un vehiculo del paquete de datos de vuelta."""

    return {
        "last_lap_time_ms": bruto[0],
        "current_lap_time_ms": bruto[1],
        "sector1_time_ms_part": bruto[2],
        "sector1_time_minutes_part": bruto[3],
        "sector2_time_ms_part": bruto[4],
        "sector2_time_minutes_part": bruto[5],
        "delta_to_car_in_front_ms_part": bruto[6],
        "delta_to_car_in_front_minutes_part": bruto[7],
        "delta_to_race_leader_ms_part": bruto[8],
        "delta_to_race_leader_minutes_part": bruto[9],
        "lap_distance_m": bruto[10],      # negativa si no se cruzo la linea
        "total_distance_m": bruto[11],    # negativa si no se cruzo la linea
        "safety_car_delta_s": bruto[12],
        "car_position": bruto[13],
        "current_lap_num": bruto[14],
        "pit_status": bruto[15],          # 0 ninguno, 1 entrando, 2 en boxes
        "num_pit_stops": bruto[16],
        "sector": bruto[17],              # 0, 1 o 2
        "current_lap_invalid": bruto[18],
        "penalties_s": bruto[19],
        "total_warnings": bruto[20],
        "corner_cutting_warnings": bruto[21],
        "num_unserved_drive_through_pens": bruto[22],
        "num_unserved_stop_go_pens": bruto[23],
        "grid_position": bruto[24],
        "driver_status": bruto[25],
        "result_status": bruto[26],
        "pit_lane_timer_active": bruto[27],
        "pit_lane_time_in_lane_ms": bruto[28],
        "pit_stop_timer_ms": bruto[29],
        "pit_stop_should_serve_pen": bruto[30],
        "speed_trap_fastest_speed_kmh": bruto[31],
        "speed_trap_fastest_lap": bruto[32],  # 255 si no hay
    }


# Decodificadores disponibles, por identificador de paquete.
#
# Los catorce paquetes restantes se reconocen y se validan por tamano, pero no
# se decodifican: el trabajo solo necesita telemetria y datos de vuelta, y
# escribir estructuras que nadie consume es codigo que hay que mantener sin
# obtener nada a cambio.
_DECODIFICADORES = {
    2: (LAP_DATA_FMT, LAP_DATA_TAMANO, LAP_DATA_COLA_TAMANO, _desempaquetar_lap_data),
    6: (CAR_TELEMETRY_FMT, CAR_TELEMETRY_TAMANO, CAR_TELEMETRY_COLA_TAMANO,
        _desempaquetar_car_telemetry),
}


# --------------------------------------------------------------------------- #
# Verificacion estructural
# --------------------------------------------------------------------------- #

def verificar_estructuras() -> list[dict[str, Any]]:
    """Contrasta el tamano calculado de cada estructura contra el declarado.

    Devuelve una fila por paquete decodificable con el tamano que resulta de
    sumar sus campos y el que la especificacion declara. Es la verificacion que
    la propia especificacion vuelve obligatoria al advertir que EA no garantiza
    su exactitud.

    Un desajuste de un solo byte desplaza todos los campos siguientes y produce
    valores plausibles pero falsos, que es la peor clase de error posible en un
    formato binario.
    """

    filas = [{
        "estructura": "cabecera",
        "calculado": CABECERA_TAMANO,
        "declarado": 29,
        "coincide": CABECERA_TAMANO == 29,
    }]

    for packet_id, (_, por_vehiculo, cola, _) in _DECODIFICADORES.items():
        declarado = PAQUETES[packet_id]["tamano"]
        calculado = CABECERA_TAMANO + VEHICULOS * por_vehiculo + cola
        filas.append({
            "estructura": PAQUETES[packet_id]["nombre"],
            "por_vehiculo": por_vehiculo,
            "calculado": calculado,
            "declarado": declarado,
            "coincide": calculado == declarado,
        })

    return filas


# --------------------------------------------------------------------------- #
# Decodificacion
# --------------------------------------------------------------------------- #

def decodificar_cabecera(datos: bytes) -> dict[str, Any]:
    """Lee la cabecera comun sin interpretar la carga util.

    Rechaza el datagrama si no alcanza para la cabecera o si declara un formato
    distinto del congelado.
    """

    if len(datos) < CABECERA_TAMANO:
        raise TamanoInvalido(
            f"El datagrama mide {len(datos)} bytes y la cabecera requiere "
            f"{CABECERA_TAMANO}."
        )

    valores = struct.unpack_from(CABECERA_FMT, datos, 0)
    cabecera = dict(zip(CABECERA_CAMPOS, valores))

    if cabecera["packet_format"] != FORMATO_ADMITIDO:
        raise FormatoNoAdmitido(
            f"Formato {cabecera['packet_format']} no admitido; este decodificador "
            f"esta congelado en {FORMATO_ADMITIDO}."
        )

    return cabecera


def decodificar(datos: bytes) -> dict[str, Any]:
    """Decodifica un datagrama completo despachando por formato e identificador.

    Devuelve siempre la cabecera y la descripcion del paquete. Incluye la carga
    util solo si hay decodificador escrito para ese identificador; en caso
    contrario marca `decodificado` en falso y explica el motivo, de modo que un
    paquete no consumido quede contabilizado y no descartado en silencio.
    """

    cabecera = decodificar_cabecera(datos)
    packet_id = cabecera["packet_id"]

    if packet_id not in PAQUETES:
        raise PaqueteNoDecodificable(
            f"Identificador de paquete {packet_id} fuera del rango conocido 0-15."
        )

    descripcion = PAQUETES[packet_id]
    if len(datos) != descripcion["tamano"]:
        raise TamanoInvalido(
            f"El paquete {descripcion['nombre']} mide {len(datos)} bytes y la "
            f"especificacion declara {descripcion['tamano']}."
        )

    resultado: dict[str, Any] = {
        "version_decodificador": VERSION_DECODIFICADOR,
        "cabecera": cabecera,
        "paquete": descripcion["nombre"],
        "packet_id": packet_id,
    }

    if packet_id not in _DECODIFICADORES:
        resultado["decodificado"] = False
        resultado["motivo"] = "sin decodificador para este paquete"
        return resultado

    formato, por_vehiculo, _, nombrar = _DECODIFICADORES[packet_id]
    vehiculos = []
    for indice in range(VEHICULOS):
        desplazamiento = CABECERA_TAMANO + indice * por_vehiculo
        vehiculos.append(nombrar(struct.unpack_from(formato, datos, desplazamiento)))

    resultado["decodificado"] = True
    resultado["vehiculos"] = vehiculos
    resultado["vehiculo_propio"] = vehiculos[cabecera["player_car_index"]]
    return resultado
