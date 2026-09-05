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

#: Valor con que la cabecera declara que no hay segundo jugador.
#:
#: Se usa 255 y no cero porque cero es un indice valido: el vehiculo de la
#: primera posicion del arreglo. Confundirlos haria que toda sesion sin segundo
#: jugador pareciera tener uno.
SIN_SEGUNDO_JUGADOR = 255


# --------------------------------------------------------------------------- #
# Motion, paquete 0
# --------------------------------------------------------------------------- #

# Una entrada por vehiculo. 60 bytes.
#
# Es el paquete que aporta los dos canales que ninguna otra estructura tiene:
#
# **La aceleracion en los tres ejes.** Es el unico canal del protocolo que existe
# con el mismo significado fisico en un vehiculo real: un acelerometro publica
# aceleracion lateral y longitudinal en el bus, y el simulador la entrega en las
# mismas unidades. Junto con la velocidad de guinada del paquete de dinamica
# extendida, es el puente mas directo entre la fuente simulada y el trabajo sobre
# vehiculo real, porque **el mismo analisis corre sobre las dos sin traducir**.
#
# **La posicion de cada vehiculo en el mundo.** Es lo que permite dibujar el
# trazado y ubicar a los veintidos vehiculos sobre el, en lugar de conocer
# unicamente su distancia recorrida.
#
# Los seis campos de direccion son enteros de dos bytes que representan vectores
# normalizados: se dividen por 32767 para volver al rango de menos uno a uno. No
# hacerlo daria vectores de decenas de miles de unidades de largo, que es un error
# que ninguna prueba de tamano puede detectar.
MOTION_FMT = "<" + "f" * 6 + "h" * 6 + "f" * 6
MOTION_TAMANO = struct.calcsize(MOTION_FMT)

#: Factor de los vectores de direccion. Es el maximo de un entero de dos bytes
#: con signo, que es como el protocolo representa un valor normalizado.
NORMALIZACION_DIRECCION = 32767.0


def _desempaquetar_motion(bruto: tuple) -> dict[str, Any]:
    """Nombra los campos de posicion, velocidad, orientacion y aceleracion.

    Los ejes siguen la convencion que este trabajo ya verifico sobre el paquete
    de dinamica extendida: **la altura es el eje y**, no el z. Se detecto
    integrando la velocidad angular de cada eje a lo largo de dos minutos de
    conduccion, donde solo uno acumulaba las vueltas completas que un circuito
    impone. Nombrar mal un eje aca intercambiaria la aceleracion lateral con la
    vertical sin alterar un solo byte.
    """

    return {
        "world_position_x_m": bruto[0],
        "world_position_y_m": bruto[1],          # altura
        "world_position_z_m": bruto[2],
        "world_velocity_x_ms": bruto[3],
        "world_velocity_y_ms": bruto[4],
        "world_velocity_z_ms": bruto[5],
        "forward_dir_x": bruto[6] / NORMALIZACION_DIRECCION,
        "forward_dir_y": bruto[7] / NORMALIZACION_DIRECCION,
        "forward_dir_z": bruto[8] / NORMALIZACION_DIRECCION,
        "right_dir_x": bruto[9] / NORMALIZACION_DIRECCION,
        "right_dir_y": bruto[10] / NORMALIZACION_DIRECCION,
        "right_dir_z": bruto[11] / NORMALIZACION_DIRECCION,
        # En unidades de g, no en metros por segundo al cuadrado.
        "g_force_lateral": bruto[12],
        "g_force_longitudinal": bruto[13],
        "g_force_vertical": bruto[14],
        "yaw_rad": bruto[15],
        "pitch_rad": bruto[16],
        "roll_rad": bruto[17],
    }


# --------------------------------------------------------------------------- #
# Participants, paquete 4
# --------------------------------------------------------------------------- #

# Una entrada por vehiculo, 57 bytes, precedida por un byte con la cantidad de
# vehiculos activos.
#
# Es el unico paquete que responde **quien** es cada vehiculo. Sin el, todo el
# resto del protocolo habla de indices: la interfaz dice "vehiculo 19" donde
# deberia decir un nombre y una escuderia.
#
# El campo de nombre es texto de treinta y dos bytes terminado en nulo. Lleva
# tratamiento aparte porque **no es un numero**: hay que recortarlo en el nulo y
# decodificarlo como UTF-8, y un nombre demasiado largo llega truncado con puntos
# suspensivos por decision del propio protocolo.
#
# Que contiene el nombre: depende del modo, y no de lo que declara la
# especificacion
# --------------------------------------------------------------------------
# La especificacion lo declara por plataforma: en PlayStation el nombre seria el
# del piloto elegido, y pasaria a ser el identificador de red solo en partida
# LAN. **Eso resulto incompleto.**
#
# Medido sobre capturas propias, en el mismo equipo y la misma consola:
#
# | modo | nombre del conductor humano |
# | --- | --- |
# | carrera de un jugador | `VERSTAPPEN`, el piloto elegido |
# | contrarreloj | `mauruiz20`, **el identificador de la plataforma** |
#
# Y en contrarreloj la parrilla incluye ademas los fantasmas de la tabla de
# tiempos en linea, con **identificadores de otras personas**.
#
# De modo que el campo **puede contener el identificador de una persona real** en
# un modo que este trabajo usa, sin que medie partida LAN ni multijugador. Quien
# publique la parrilla tiene que decidirlo sabiendo esto, y por eso el
# decodificador expone el nombre tal cual y no lo interpreta: la decision de que
# se publica no puede quedar escondida en la lectura.
#
# Registro de una correccion: este comentario afirmaba antes que los nombres eran
# siempre de piloto en los modos usados, apoyandose en una sola captura de
# carrera. **La generalizacion desde un unico modo fue el error**, y lo desmintio
# la primera captura de contrarreloj.
#
# Cada entrada declara ademas `your_telemetry`, que es el ajuste con el que el
# protocolo restringe la telemetria de un jugador ante terceros. Se expone sin
# interpretarlo: no hace falta para decidir sobre el nombre, y esconderlo en la
# lectura lo volveria invisible si algun dia hiciera falta.
PARTICIPANTS_CABEZA_FMT = "<B"
PARTICIPANTE_FMT = "<7s32s2sHBB12s"
PARTICIPANTE_TAMANO = struct.calcsize(PARTICIPANTE_FMT)

# Transcritos del apendice "Team IDs". Solo los del campeonato y los genericos:
# los historicos existen en el apendice y no aparecen en una sesion de 2025.
EQUIPOS = {
    0: "Mercedes", 1: "Ferrari", 2: "Red Bull Racing", 3: "Williams",
    4: "Aston Martin", 5: "Alpine", 6: "RB", 7: "Haas", 8: "McLaren",
    9: "Sauber", 41: "F1 Generico", 104: "Equipo personalizado",
    129: "Konnersport", 142: "APXGP",
}

PLATAFORMAS = {1: "Steam", 3: "PlayStation", 4: "Xbox", 6: "Origin", 255: "desconocida"}


def _nombre_participante(crudo: bytes) -> str:
    """Recorta en el nulo y decodifica como UTF-8.

    Sin recortar, el nombre arrastraria los bytes nulos de relleno; sin
    contemplar el error de decodificacion, un byte invalido interrumpiria la
    lectura del paquete entero por un campo que no sostiene ninguna afirmacion.
    """

    return crudo.split(b"\x00", 1)[0].decode("utf-8", "replace")


def _desempaquetar_participante(bruto: tuple) -> dict[str, Any]:
    """Nombra los campos de un participante."""

    cabeza = bruto[0]            # los siete enteros de un byte
    nombre = bruto[1]
    ajustes = bruto[2]           # your_telemetry y show_online_names
    equipo = cabeza[3]
    return {
        "ai_controlled": cabeza[0],
        "driver_id": cabeza[1],
        "network_id": cabeza[2],
        "team_id": equipo,
        "team": EQUIPOS.get(equipo, f"id-{equipo}"),
        "my_team": cabeza[4],
        "race_number": cabeza[5],
        "nationality_id": cabeza[6],
        "name": _nombre_participante(nombre),
        # Ajuste de privacidad del jugador: 0 restringido, 1 publico. Se expone
        # sin interpretarlo; quien publique decide que hacer con el.
        "your_telemetry": ajustes[0],
        "show_online_names": ajustes[1],
        "tech_level": bruto[3],
        "platform_id": bruto[4],
        "platform": PLATAFORMAS.get(bruto[4], f"id-{bruto[4]}"),
        "num_colours": bruto[5],
    }


# --------------------------------------------------------------------------- #
# Orden de las ruedas
# --------------------------------------------------------------------------- #

# La especificacion lo declara textualmente para los arreglos de Motion Ex:
# "All wheel arrays have the following order: RL, RR, FL, FR".
#
# No es el orden intuitivo. Leerlos como delantera izquierda primero intercambia
# el eje entero sin alterar el tamano, de modo que ninguna prueba aritmetica lo
# detectaria: es el mismo tipo de error que el campo de marcha con signo.
ORDEN_RUEDAS = ("trasera_izquierda", "trasera_derecha",
                "delantera_izquierda", "delantera_derecha")


def _por_rueda(valores) -> dict[str, Any]:
    """Nombra un arreglo de cuatro valores segun el orden del protocolo."""

    return dict(zip(ORDEN_RUEDAS, valores))


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

# Tres campos finales del paquete, despues del arreglo de vehiculos. Describen la
# pantalla del juego y no al vehiculo.
#
# `m_mfdPanelIndex` es el que permite **alinear un video con los datos sin
# sincronizar relojes**: el datagrama declara que panel estaba abierto, de modo
# que el instante en que cambia se lee del propio flujo. Es lo que vuelve
# practicable la validacion semantica del decodificador.
CAR_TELEMETRY_COLA_FMT = "<BBb"
CAR_TELEMETRY_COLA_TAMANO = struct.calcsize(CAR_TELEMETRY_COLA_FMT)

# Paneles que el juego puede mostrar sobre el estado del vehiculo.
PANELES_MFD = {
    0: "configuracion", 1: "boxes", 2: "danos", 3: "motor", 4: "temperaturas",
    255: "ninguno",
}


def _desempaquetar_cola_car_telemetry(bruto: tuple) -> dict[str, Any]:
    """Nombra los campos finales del paquete de telemetria."""

    return {
        "mfd_panel": bruto[0],
        "mfd_panel_nombre": PANELES_MFD.get(bruto[0], f"id-{bruto[0]}"),
        "mfd_panel_segundo_jugador": bruto[1],
        "marcha_sugerida": bruto[2],
    }


#: Tipos de superficie, transcritos del apendice "Surface types" de la
#: especificacion.
#:
#: Vive aca, en el modulo del protocolo, y no en cada consumidor. Cuando el
#: anotador en vivo se escribio con su propia copia, esa copia salio de memoria y
#: quedo corrida: declaraba "piedra" donde la especificacion dice "cesped", y las
#: dos lecturas de la misma captura describian superficies distintas. **Una tabla
#: transcrita de un documento tiene que estar una sola vez**, o la copia
#: equivocada es cuestion de tiempo.
SUPERFICIES = {
    0: "asfalto", 1: "piano", 2: "hormigon", 3: "roca", 4: "grava",
    5: "barro", 6: "arena", 7: "cesped", 8: "agua", 9: "adoquin",
    10: "metal", 11: "estriado",
}

#: Codigo de la superficie que es pista segun el reglamento deportivo.
#:
#: El articulo 33.3 declara que las lineas blancas que delimitan el borde son
#: pista **y que los pianos no lo son**. El canal no distingue la linea blanca del
#: asfalto, de modo que queda correctamente incluida sin hacer nada.
SUPERFICIE_DE_PISTA = 0

#: Superficies sobre las que el neumatico conserva agarre.
#:
#: Es una nocion **fisica** y distinta de la anterior, que es normativa. El piano
#: esta aca y no alla: se puede rodar sobre un piano sin perder agarre —en las
#: vueltas limpias de Hungaroring hay 2.083 muestras de rueda sobre piano— y aun
#: asi, segun el reglamento, un vehiculo con las cuatro ruedas sobre el piano
#: dejo la pista.
#:
#: El nombre anterior de esta constante era `SUPERFICIES_EN_PISTA`, y decia algo
#: que el reglamento contradice.
SUPERFICIES_CON_AGARRE = frozenset({0, 1})


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
        # Nombradas por rueda, igual que en el paquete de dano. Que el mismo
        # concepto fisico viajara como lista aca y como diccionario alla dejaba
        # el orden implicito justo en los canales donde ya se equivoco una vez.
        "brakes_temperature_c": _por_rueda(bruto[10:14]),
        "tyres_surface_temperature_c": _por_rueda(bruto[14:18]),
        "tyres_inner_temperature_c": _por_rueda(bruto[18:22]),
        "engine_temperature_c": bruto[22],
        "tyres_pressure_psi": _por_rueda(bruto[23:27]),
        "surface_type": _por_rueda(bruto[27:31]),
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
        # OJO: este campo **empieza en cero** y `car_position` empieza en uno.
        #
        # No es una suposicion. Sobre cuatro capturas distintas ---dos carreras de
        # Spa, el sprint y una de Spielberg--- los veinte vehiculos de cada una
        # cumplen `car_position - grid_position == 1` en los primeros segundos, y
        # el recorrido de este campo es 0..19 mientras el de la posicion es 1..20.
        # Son ochenta observaciones sin una excepcion.
        #
        # El valor se publica **tal como llega**, porque el trabajo no corrige lo
        # que la fuente declara. Lo que se corrige es el riesgo de leerlo mal:
        # compararlo de frente contra `car_position` da un puesto de diferencia, y
        # ya produjo una discrepancia aparente en el analisis de una carrera
        # ---la partida figuraba como quinta y la posicion en la vuelta 1 como
        # sexta--- que costo perseguir hasta entender que no habia ningun error.
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

# --------------------------------------------------------------------------- #
# Session, paquete 1
# --------------------------------------------------------------------------- #

# Contexto de la sesion, no del vehiculo: un solo bloque, no un arreglo de 22.
#
# Es la estructura mas compleja del protocolo: dos arreglos anidados —21 zonas de
# comisarios y 64 muestras de pronostico— suman 617 de sus 753 bytes. Se arma por
# tramos para que el conteo sea auditable; la prueba de tamano verifica el total.
#
# Su valor esta en que declara lo que el operador tendria que anotar a mano:
# circuito, longitud, tipo de sesion, clima, temperaturas y las diez ayudas de
# conduccion. Un metadato leido del flujo no puede contradecir a los datos; uno
# tipeado a mano si.
SESSION_CABEZA_FMT = "BbbBHBbBHHBBBBBB"
MARSHAL_FMT = "fb"
SESSION_MEDIO_FMT = "BBB"
PRONOSTICO_FMT = "BBBbbbbB"
SESSION_COLA_FMT = "BB" "III" "BBB" "BBBBBBBBB" "BB" "I" "B" "BBBB" "BBB" + "B" * 25 + "12B" "ff"

ZONAS_COMISARIO = 21
MUESTRAS_PRONOSTICO = 64

SESSION_FMT = ("<"
               + SESSION_CABEZA_FMT
               + MARSHAL_FMT * ZONAS_COMISARIO
               + SESSION_MEDIO_FMT
               + PRONOSTICO_FMT * MUESTRAS_PRONOSTICO
               + SESSION_COLA_FMT)
SESSION_TAMANO = struct.calcsize(SESSION_FMT)


#: Sentido del cambio de temperatura que anuncia cada muestra de pronostico.
CAMBIO_DE_TEMPERATURA = {0: "sube", 1: "baja", 2: "sin cambio"}


def _pronostico(bruto: tuple, desde: int, cuantas: int) -> list[dict[str, Any]]:
    """Nombra las muestras de pronostico del clima.

    Cada muestra declara **para que sesion**, dentro de cuantos minutos, que
    clima, que temperaturas con su sentido de cambio, y **que probabilidad de
    lluvia**.

    Por que se decodifican
    ----------------------
    El trabajo declaraba que la transicion de clima quedaba fuera de la ventana
    observada por la duracion de las capturas, y esa afirmacion se apoyaba en la
    ayuda del propio programa emisor. Con el pronostico leido, la afirmacion deja
    de ser una explicacion plausible y pasa a ser comprobable: **la fuente
    anuncia las etapas por adelantado**, de modo que se puede contrastar lo que
    anuncio contra lo que se observo.

    Se recorta a las muestras declaradas
    ------------------------------------
    El arreglo trae sesenta y cuatro posiciones y solo las primeras tienen dato.
    Devolver las sesenta y cuatro meteria decenas de muestras en cero, que un
    promedio leeria como lluvia nula anunciada a cero minutos. Es el mismo
    recorte que ya se aplica a las vueltas del historial y a las tandas.
    """

    salida = []
    for i in range(min(cuantas, MUESTRAS_PRONOSTICO)):
        m = bruto[desde + i * 8: desde + (i + 1) * 8]
        if len(m) < 8:
            break
        salida.append({
            "session_type": m[0],
            "minutos": m[1],
            "weather": m[2],
            "track_temperature_c": m[3],
            "track_temperature_cambio": CAMBIO_DE_TEMPERATURA.get(m[4], m[4]),
            "air_temperature_c": m[5],
            "air_temperature_cambio": CAMBIO_DE_TEMPERATURA.get(m[6], m[6]),
            "probabilidad_lluvia_pct": m[7],
        })
    return salida


def _desempaquetar_session(bruto: tuple) -> dict[str, Any]:
    """Nombra los campos del paquete de sesion.

    Las zonas de comisarios se resumen por cantidad: existen en el crudo y pueden
    leerse despues, pero normalizarlas hoy no sostiene ninguna afirmacion. Las
    muestras de pronostico, en cambio, **si se nombran**: son lo que permite
    contrastar el clima anunciado contra el observado.
    """

    fin_cabeza = len(SESSION_CABEZA_FMT)
    ini_medio = fin_cabeza + ZONAS_COMISARIO * 2       # cada zona aporta 2 valores
    ini_pronostico = ini_medio + 3
    ini_cola = ini_pronostico + MUESTRAS_PRONOSTICO * 8

    c = bruto[:fin_cabeza]
    medio = bruto[ini_medio:ini_pronostico]
    cola = bruto[ini_cola:]

    return {
        "weather": c[0],
        "track_temperature_c": c[1],
        "air_temperature_c": c[2],
        "total_laps": c[3],
        "track_length_m": c[4],
        "session_type": c[5],
        "track_id": c[6],
        "formula": c[7],
        "session_time_left_s": c[8],
        "session_duration_s": c[9],
        "pit_speed_limit_kmh": c[10],
        "game_paused": c[11],
        "is_spectating": c[12],
        "num_marshal_zones": c[15],
        "safety_car_status": medio[0],
        "network_game": medio[1],
        "num_weather_forecast_samples": medio[2],
        "weather_forecast": _pronostico(bruto, ini_pronostico, medio[2]),
        "forecast_accuracy": cola[0],
        "ai_difficulty": cola[1],
        "season_link_id": cola[2],
        "weekend_link_id": cola[3],
        "session_link_id": cola[4],
        # Las diez ayudas de conduccion. Que esten en el flujo convierte
        # "sesion sin ayudas" de una afirmacion del operador en un hecho
        # verificable contra el propio archivo.
        "steering_assist": cola[8],
        "braking_assist": cola[9],
        "gearbox_assist": cola[10],
        "pit_assist": cola[11],
        "pit_release_assist": cola[12],
        "ers_assist": cola[13],
        "drs_assist": cola[14],
        "dynamic_racing_line": cola[15],
        "dynamic_racing_line_type": cola[16],
        "game_mode": cola[17],
        "rule_set": cola[18],
        "time_of_day_min": cola[19],
        "session_length": cola[20],
        "num_safety_car_periods": cola[25],
        "num_virtual_safety_car_periods": cola[26],
        "num_red_flag_periods": cola[27],
        "equal_car_performance": cola[28],
        # Los indices de este bloque se contaron uno a uno contra la
        # especificacion: un desplazamiento de una sola posicion aca leia la
        # tasa de dano y la publicaba como el nivel de dano, sin que ninguna
        # prueba de tamano pudiera notarlo.
        "car_damage_setting": cola[36],
        "car_damage_rate": cola[37],
        "collisions": cola[38],
        # Ajustes de realismo. Se nombran porque son las perillas que el
        # protocolo de capturas manipula: sin leerlas del flujo, la condicion
        # experimental de cada captura seria una afirmacion del operador.
        "recovery_mode": cola[29],
        "surface_type": cola[31],
        "low_fuel_mode": cola[32],
        "tyre_temperature_model": cola[34],
        "pit_lane_tyre_sim": cola[35],
        "corner_cutting_stringency": cola[42],
        "parc_ferme_rules": cola[43],
        "pit_stop_experience": cola[44],
        "safety_car_setting": cola[45],
        "formation_lap": cola[47],
        "red_flags_setting": cola[49],
        "speed_units_lead": cola[21],
        "num_sessions_in_weekend": cola[52],
        "sector2_lap_distance_start_m": cola[-2],
        "sector3_lap_distance_start_m": cola[-1],
    }


# --------------------------------------------------------------------------- #
# Event, paquete 3
# --------------------------------------------------------------------------- #

# Es el unico paquete del protocolo que **no tiene una estructura fija**: los
# cuatro primeros bytes son un codigo de texto que decide como leer los doce
# siguientes. Interpretarlos con la estructura equivocada no falla ni cambia el
# tamano; simplemente devuelve numeros creibles y falsos.
#
# Su valor es que aca esta lo que ningun canal continuo dice: cuando salio el
# coche de seguridad, quien adelanto a quien, que penalizacion se aplico y por
# que. Un canal de telemetria muestra que el vehiculo bajo la velocidad; solo
# este paquete dice que fue por bandera amarilla y no por un error de conduccion.
EVENTO_TAMANO_DETALLE = 12

MOTIVOS_ABANDONO = {
    0: "invalido", 1: "abandono", 2: "termino", 3: "dano-terminal",
    4: "inactivo", 5: "vueltas-insuficientes", 6: "bandera-negra",
    7: "bandera-roja", 8: "falla-mecanica", 9: "sesion-salteada",
    10: "sesion-simulada",
}
MOTIVOS_DRS_DESACTIVADO = {
    0: "pista-mojada", 1: "coche-de-seguridad", 2: "bandera-roja",
    3: "vuelta-minima-no-alcanzada",
}
TIPOS_COCHE_SEGURIDAD = {
    0: "ninguno", 1: "coche-de-seguridad", 2: "coche-de-seguridad-virtual",
    3: "vuelta-de-formacion",
}
FASES_COCHE_SEGURIDAD = {
    0: "desplegado", 1: "regresando", 2: "regreso", 3: "carrera-reanudada",
}

# Las dieciocho penalizaciones y las cincuenta y cinco infracciones que la
# especificacion declara, con sus identificadores contiguos desde cero.
#
# Interesan porque son **el veredicto del juego**, y eso es un dato distinto de
# lo que miden los canales: la telemetria dice que hubo un impacto y con que
# fuerza, y solo esto dice a quien se lo atribuyo el juego y por que motivo.
#
# Que sea un veredicto y no una medicion tambien fija su alcance. La bandera de
# vuelta invalida del propio juego no marco ninguna de las diecinueve colisiones
# de la primera pasada de la prueba de dos conductores, de modo que estas tablas
# se citan como lo que el juego decidio, nunca como la determinacion de la causa.
TIPOS_PENALIZACION = {
    0: "paso-por-boxes",
    1: "detencion-obligatoria",
    2: "penalizacion-de-parrilla",
    3: "recordatorio-de-penalizacion",
    4: "penalizacion-de-tiempo",
    5: "advertencia",
    6: "descalificado",
    7: "retirado-de-la-vuelta-de-formacion",
    8: "detenido-demasiado-tiempo",
    9: "reglamento-de-neumaticos",
    10: "vuelta-invalidada",
    11: "esta-vuelta-y-la-siguiente-invalidadas",
    12: "vuelta-invalidada-sin-motivo-declarado",
    13: "esta-vuelta-y-la-siguiente-invalidadas-sin-motivo-declarado",
    14: "esta-vuelta-y-la-anterior-invalidadas",
    15: "esta-vuelta-y-la-anterior-invalidadas-sin-motivo-declarado",
    16: "retirado",
    17: "cuenta-de-bandera-negra",
}
TIPOS_INFRACCION = {
    0: "bloquear-conduciendo-lento",
    1: "bloquear-en-contramano",
    2: "retroceder-en-la-linea-de-largada",
    3: "colision-grande",
    4: "colision-chica",
    5: "no-devolver-la-posicion-a-uno",
    6: "no-devolver-la-posicion-a-varios",
    7: "cortar-curva-ganando-tiempo",
    8: "cortar-curva-para-adelantar-a-uno",
    9: "cortar-curva-para-adelantar-a-varios",
    10: "cruzar-la-salida-de-boxes",
    11: "ignorar-banderas-azules",
    12: "ignorar-banderas-amarillas",
    13: "ignorar-el-paso-por-boxes",
    14: "demasiados-pasos-por-boxes",
    15: "recordatorio-de-paso-por-boxes-en-n-vueltas",
    16: "recordatorio-de-paso-por-boxes-en-esta-vuelta",
    17: "exceso-de-velocidad-en-boxes",
    18: "detenido-demasiado-tiempo",
    19: "ignorar-el-reglamento-de-neumaticos",
    20: "demasiadas-penalizaciones",
    21: "advertencias-multiples",
    22: "al-borde-de-la-descalificacion",
    23: "eleccion-de-neumaticos-uno",
    24: "eleccion-de-neumaticos-varios",
    25: "vuelta-invalidada-por-cortar-curva",
    26: "vuelta-invalidada-por-irse-ancho",
    27: "irse-ancho-ganando-tiempo-leve",
    28: "irse-ancho-ganando-tiempo-significativo",
    29: "irse-ancho-ganando-tiempo-extremo",
    30: "vuelta-invalidada-por-apoyarse-en-el-muro",
    31: "vuelta-invalidada-por-usar-retroceso",
    32: "vuelta-invalidada-por-reposicion-en-pista",
    33: "bloquear-la-calle-de-boxes",
    34: "largada-adelantada",
    35: "colision-con-el-coche-de-seguridad",
    36: "adelantamiento-ilegal-tras-el-coche-de-seguridad",
    37: "exceder-el-ritmo-tras-el-coche-de-seguridad",
    38: "exceder-el-ritmo-tras-el-coche-de-seguridad-virtual",
    39: "vuelta-de-formacion-por-debajo-de-la-velocidad-permitida",
    40: "detenerse-en-la-vuelta-de-formacion",
    41: "retirado-por-falla-mecanica",
    42: "retirado-por-dano-terminal",
    43: "quedarse-demasiado-atras-del-coche-de-seguridad",
    44: "cuenta-de-bandera-negra",
    45: "detencion-obligatoria-sin-cumplir",
    46: "paso-por-boxes-sin-cumplir",
    47: "cambio-de-componente-del-motor",
    48: "cambio-de-caja-de-cambios",
    49: "cambio-en-parque-cerrado",
    50: "penalizacion-de-parrilla-de-liga",
    51: "penalizacion-por-reintento",
    52: "ganancia-de-tiempo-ilegal",
    53: "parada-en-boxes-obligatoria",
    54: "atributo-asignado",
}

# Cada codigo con el formato de su detalle y los nombres de sus campos. Los
# codigos ausentes no llevan detalle: el hecho de que ocurrieron es todo el dato.
_EVENTOS = {
    "FTLP": ("<Bf", ("vehiculo", "tiempo_vuelta_s")),
    "RTMT": ("<BB", ("vehiculo", "motivo")),
    "DRSD": ("<B", ("motivo",)),
    "TMPT": ("<B", ("vehiculo",)),
    "RCWN": ("<B", ("vehiculo",)),
    "PENA": ("<BBBBBBB", ("tipo_penalizacion", "tipo_infraccion", "vehiculo",
                          "otro_vehiculo", "tiempo_s", "vuelta", "puestos_ganados")),
    "SPTP": ("<BfBBBf", ("vehiculo", "velocidad_kmh", "es_mejor_de_la_sesion",
                         "es_mejor_del_piloto", "vehiculo_mas_rapido",
                         "mejor_velocidad_sesion_kmh")),
    "STLG": ("<B", ("luces",)),
    "DTSV": ("<B", ("vehiculo",)),
    "SGSV": ("<Bf", ("vehiculo", "tiempo_detenido_s")),
    "FLBK": ("<If", ("marco", "tiempo_sesion_s")),
    "BUTN": ("<I", ("botones",)),
    "OVTK": ("<BB", ("vehiculo_que_adelanta", "vehiculo_adelantado")),
    "SCAR": ("<BB", ("tipo", "fase")),
    "COLL": ("<BB", ("vehiculo_1", "vehiculo_2")),
}

NOMBRES_EVENTO = {
    "SSTA": "sesion-iniciada", "SEND": "sesion-terminada",
    "FTLP": "vuelta-rapida", "RTMT": "abandono",
    "DRSE": "drs-habilitado", "DRSD": "drs-deshabilitado",
    "TMPT": "companero-en-boxes", "CHQF": "bandera-a-cuadros",
    "RCWN": "ganador", "PENA": "penalizacion", "SPTP": "radar-de-velocidad",
    "STLG": "luces-de-largada", "LGOT": "largada",
    "DTSV": "paso-por-boxes-cumplido", "SGSV": "detencion-cumplida",
    "FLBK": "retroceso", "BUTN": "botones", "RDFL": "bandera-roja",
    "OVTK": "adelantamiento", "SCAR": "coche-de-seguridad",
    "COLL": "colision",
}


def _desempaquetar_event(datos: bytes) -> dict[str, Any]:
    """Lee el codigo de evento y, segun cual sea, el detalle que le corresponde."""

    codigo = datos[CABECERA_TAMANO:CABECERA_TAMANO + 4].decode("ascii", "replace")
    evento: dict[str, Any] = {
        "codigo": codigo,
        "evento": NOMBRES_EVENTO.get(codigo, f"desconocido-{codigo}"),
    }

    if codigo not in _EVENTOS:
        # No es un vacio a completar: estos codigos no llevan detalle.
        evento["detalle"] = {}
        return evento

    formato, campos = _EVENTOS[codigo]
    valores = struct.unpack_from(formato, datos, CABECERA_TAMANO + 4)
    detalle = dict(zip(campos, valores))

    # Se traduce solo lo que sin traducir no se entiende.
    if codigo == "SCAR":
        detalle["tipo_nombre"] = TIPOS_COCHE_SEGURIDAD.get(detalle["tipo"], "desconocido")
        detalle["fase_nombre"] = FASES_COCHE_SEGURIDAD.get(detalle["fase"], "desconocida")
    elif codigo == "RTMT":
        detalle["motivo_nombre"] = MOTIVOS_ABANDONO.get(detalle["motivo"], "desconocido")
    elif codigo == "DRSD":
        detalle["motivo_nombre"] = MOTIVOS_DRS_DESACTIVADO.get(detalle["motivo"], "desconocido")
    elif codigo == "PENA":
        detalle["tipo_penalizacion_nombre"] = TIPOS_PENALIZACION.get(
            detalle["tipo_penalizacion"], "desconocida")
        detalle["tipo_infraccion_nombre"] = TIPOS_INFRACCION.get(
            detalle["tipo_infraccion"], "desconocida")

    evento["detalle"] = detalle
    return evento


# --------------------------------------------------------------------------- #
# Car Status, paquete 7
# --------------------------------------------------------------------------- #

# Una entrada por vehiculo. 55 bytes.
CAR_STATUS_FMT = "<BBBBBfffHHBBHBBBbfffBfffB"
CAR_STATUS_TAMANO = struct.calcsize(CAR_STATUS_FMT)


def _desempaquetar_car_status(bruto: tuple) -> dict[str, Any]:
    """Nombra los campos de estado de un vehiculo."""

    return {
        "traction_control": bruto[0],       # 0 nulo, 1 medio, 2 completo
        "anti_lock_brakes": bruto[1],
        "fuel_mix": bruto[2],               # 0 pobre a 3 maximo
        "front_brake_bias_pct": bruto[3],
        "pit_limiter": bruto[4],
        "fuel_in_tank_kg": bruto[5],
        "fuel_capacity_kg": bruto[6],
        "fuel_remaining_laps": bruto[7],
        "max_rpm": bruto[8],
        "idle_rpm": bruto[9],
        "max_gears": bruto[10],
        "drs_allowed": bruto[11],
        "drs_activation_distance_m": bruto[12],
        "actual_tyre_compound": bruto[13],
        "visual_tyre_compound": bruto[14],
        "tyres_age_laps": bruto[15],
        "vehicle_fia_flags": bruto[16],     # -1 desconocido, 0 ninguna, 1 verde...
        "engine_power_ice_w": bruto[17],
        "engine_power_mguk_w": bruto[18],
        "ers_store_energy_j": bruto[19],
        "ers_deploy_mode": bruto[20],
        "ers_harvested_this_lap_mguk_j": bruto[21],
        "ers_harvested_this_lap_mguh_j": bruto[22],
        "ers_deployed_this_lap_j": bruto[23],
        "network_paused": bruto[24],
    }


# Decodificadores disponibles, por identificador de paquete.
#
# Los catorce paquetes restantes se reconocen y se validan por tamano, pero no
# se decodifican: el trabajo solo necesita telemetria y datos de vuelta, y
# escribir estructuras que nadie consume es codigo que hay que mantener sin
# obtener nada a cambio.

# --------------------------------------------------------------------------- #
# Car Damage, paquete 10
# --------------------------------------------------------------------------- #

# Una entrada por vehiculo. 46 bytes.
#
# Aporta los canales de estado mecanico que el trabajo habia declarado fuera de
# alcance por falta de fuente: desgaste y dano por rueda, y desgaste del motor
# por componente. No los convierte en medicion real, pero permite construir y
# demostrar la vista de salud del vehiculo.
CAR_DAMAGE_FMT = "<4f4B4B4B" + "B" * 18
CAR_DAMAGE_TAMANO = struct.calcsize(CAR_DAMAGE_FMT)


def _desempaquetar_car_damage(bruto: tuple) -> dict[str, Any]:
    """Nombra los campos de dano y desgaste de un vehiculo."""

    return {
        "tyres_wear_pct": _por_rueda(bruto[0:4]),
        "tyres_damage_pct": _por_rueda(bruto[4:8]),
        "brakes_damage_pct": _por_rueda(bruto[8:12]),
        "tyre_blisters_pct": _por_rueda(bruto[12:16]),
        "front_left_wing_damage_pct": bruto[16],
        "front_right_wing_damage_pct": bruto[17],
        "rear_wing_damage_pct": bruto[18],
        "floor_damage_pct": bruto[19],
        "diffuser_damage_pct": bruto[20],
        "sidepod_damage_pct": bruto[21],
        "drs_fault": bruto[22],
        "ers_fault": bruto[23],
        "gearbox_damage_pct": bruto[24],
        "engine_damage_pct": bruto[25],
        "engine_mguh_wear_pct": bruto[26],
        "engine_es_wear_pct": bruto[27],
        "engine_ce_wear_pct": bruto[28],
        "engine_ice_wear_pct": bruto[29],
        "engine_mguk_wear_pct": bruto[30],
        "engine_tc_wear_pct": bruto[31],
        "engine_blown": bruto[32],
        "engine_seized": bruto[33],
    }


# --------------------------------------------------------------------------- #
# Motion Ex, paquete 13
# --------------------------------------------------------------------------- #

# Solo el vehiculo propio. 244 bytes: sesenta y un flotantes consecutivos.
#
# Es el paquete mas rico del protocolo y el que tiende el puente con el analisis
# CAN del trabajo: `m_wheelSpeed` es la misma senal que se identifico y valido
# sobre el bus real, y la velocidad angular en el eje vertical es la guinada.
MOTION_EX_FMT = "<" + "f" * 61
MOTION_EX_TAMANO = struct.calcsize(MOTION_EX_FMT)


def _desempaquetar_motion_ex(b: tuple) -> dict[str, Any]:
    """Nombra los campos de dinamica del vehiculo propio."""

    return {
        "suspension_position": _por_rueda(b[0:4]),
        "suspension_velocity": _por_rueda(b[4:8]),
        "suspension_acceleration": _por_rueda(b[8:12]),
        # Equivalente de la senal `wheel_speeds` validada sobre el bus CAN real.
        "wheel_speed": _por_rueda(b[12:16]),
        "wheel_slip_ratio": _por_rueda(b[16:20]),
        "wheel_slip_angle": _por_rueda(b[20:24]),
        "wheel_lat_force": _por_rueda(b[24:28]),
        "wheel_long_force": _por_rueda(b[28:32]),
        "height_of_cog_above_ground_m": b[32],
        # Ejes del vehiculo, identificados por medicion sobre captura real:
        # x lateral, de -19,1 a +12,6 m/s; y vertical, de -0,4 a +0,6 m/s;
        # z longitudinal, hasta +91,3 m/s, es decir 328 km/h.
        "local_velocity_ms": {"x": b[33], "y": b[34], "z": b[35]},
        "angular_velocity_rads": {"x": b[36], "y": b[37], "z": b[38]},
        # La guinada es la rotacion alrededor del eje vertical, y por lo tanto
        # esta en el componente `y`.
        #
        # Una version anterior de este modulo la atribuia al componente `z`. El
        # error se detecto integrando cada eje sobre una captura de 120 s en la
        # que el vehiculo recorrio casi una vuelta completa: el eje `y` acumulo
        # 275,5 grados, mientras `x` y `z` acumularon 8,1 y 26,9. Un vehiculo
        # que da una vuelta a un circuito rota unos 360 grados, de modo que solo
        # `y` es compatible con el recorrido observado.
        #
        # Importa porque este es el campo equivalente a la senal `yaw_rate`
        # validada sobre el bus CAN real: mapearlo al eje equivocado habria
        # construido esa correspondencia sobre un canal casi constante.
        "yaw_rate_rads": b[37],
        "angular_acceleration_rads2": {"x": b[39], "y": b[40], "z": b[41]},
        "front_wheels_angle_rad": b[42],
        "wheel_vert_force": _por_rueda(b[43:47]),
        "front_aero_height_m": b[47],
        "rear_aero_height_m": b[48],
        "front_roll_angle_rad": b[49],
        "rear_roll_angle_rad": b[50],
        "chassis_yaw_rad": b[51],
        "chassis_pitch_rad": b[52],
        "wheel_camber_rad": _por_rueda(b[53:57]),
        "wheel_camber_gain_rad": _por_rueda(b[57:61]),
    }

# --------------------------------------------------------------------------- #
# Car Setups, paquete 5
# --------------------------------------------------------------------------- #

# Una entrada por vehiculo. 50 bytes, mas un flotante final del paquete.
#
# Hace que el reglaje forme parte del registro. Cualquier ajuste del vehiculo
# —aerodinamica, diferencial, suspension, presiones, lastre— queda declarado por
# el propio flujo, de modo que una captura no necesita que el operador anote con
# que configuracion se corrio.
#
# No convierte al reglaje en realista ni pretende hacerlo: lo vuelve **declarado**,
# que es lo que el trabajo necesita para que una condicion sea trazable.
CAR_SETUP_FMT = "<BBBB" + "ffff" + "B" * 9 + "ffff" + "B" + "f"
CAR_SETUP_TAMANO = struct.calcsize(CAR_SETUP_FMT)
CAR_SETUP_COLA_FMT = "<f"
CAR_SETUP_COLA_TAMANO = struct.calcsize(CAR_SETUP_COLA_FMT)


def _desempaquetar_car_setup(b: tuple) -> dict[str, Any]:
    """Nombra el reglaje de un vehiculo."""

    return {
        "front_wing": b[0],
        "rear_wing": b[1],
        "differential_on_throttle_pct": b[2],
        "differential_off_throttle_pct": b[3],
        "front_camber_deg": b[4],
        "rear_camber_deg": b[5],
        "front_toe_deg": b[6],
        "rear_toe_deg": b[7],
        "front_suspension": b[8],
        "rear_suspension": b[9],
        "front_anti_roll_bar": b[10],
        "rear_anti_roll_bar": b[11],
        "front_ride_height": b[12],
        "rear_ride_height": b[13],
        "brake_pressure_pct": b[14],
        "brake_bias_pct": b[15],
        "engine_braking_pct": b[16],
        # El protocolo entrega las presiones en orden trasera izquierda, trasera
        # derecha, delantera izquierda, delantera derecha, igual que el resto de
        # los arreglos por rueda.
        "tyre_pressure_psi": _por_rueda(b[17:21]),
        "ballast": b[21],
        "fuel_load_kg": b[22],
    }


# Colas de paquete que aportan informacion. La mayoria son relleno o campos que
# el trabajo no consume; solo se decodifica la que tiene uso.
_COLAS = {
    6: (CAR_TELEMETRY_COLA_FMT, _desempaquetar_cola_car_telemetry),
}


# Campos que van **antes** del arreglo de vehiculos. Es el simetrico de las
# colas, y hace falta porque el arreglo no siempre empieza pegado a la cabecera:
# el paquete de participantes lleva delante la cantidad de vehiculos activos.
#
# Se resuelve con un registro y no con un caso especial porque el desplazamiento
# de la cabeza tiene que **entrar en el calculo de la posicion de cada vehiculo**.
# Olvidarlo desplazaria las veintidos entradas un byte, y el paquete seguiria
# midiendo lo que la especificacion dice.
_CABEZAS = {
    4: (PARTICIPANTS_CABEZA_FMT, ("num_active_cars",)),
}


# --------------------------------------------------------------------------- #
# Historial de sesion y posiciones por vuelta
# --------------------------------------------------------------------------- #
#
# Estos dos no encajan en ninguno de los dos patrones anteriores, y por eso
# tienen su propio desempaquetador.
#
# Los demas paquetes describen **un instante**: llegan veinte veces por segundo
# y cada uno dice como estaba el vehiculo en ese momento. Estos describen
# **hechos cerrados**: el historial dice cuanto tardo cada vuelta, y las
# posiciones dicen en que puesto iba cada auto al empezar cada vuelta.
#
# La consecuencia es de diseno y no solo de forma. Un instante entra al contrato
# de telemetria ---senal, valor, momento---; una vuelta no, porque guardaria el
# mismo tiempo cientos de veces para declarar un solo hecho. Es el mismo
# criterio por el que la parrilla fue a la procedencia y no al contrato.

#: Una vuelta del historial. Los sectores viajan partidos en minutos y
#: milisegundos, igual que las distancias entre vehiculos del paquete de vuelta.
LAP_HISTORY_FMT = "<IHBHBHBB"
LAP_HISTORY_TAMANO = struct.calcsize(LAP_HISTORY_FMT)
LAP_HISTORY_VUELTAS = 100

#: Una tanda de neumaticos del historial.
TYRE_STINT_FMT = "<BBB"
TYRE_STINT_TAMANO = struct.calcsize(TYRE_STINT_FMT)
TYRE_STINT_MAXIMO = 8

SESSION_HISTORY_CABEZA_FMT = "<7B"
SESSION_HISTORY_CABEZA_TAMANO = struct.calcsize(SESSION_HISTORY_CABEZA_FMT)

#: Cuantas vueltas de posiciones trae el paquete, y cuantos vehiculos.
#:
#: La especificacion declara el segundo con una constante que no escribe en
#: ninguna parte del documento. **El tamano declarado la determina**: con 29
#: bytes de cabecera y dos de cabeza propia, 50 x 22 da 1131 exactos, que es el
#: tamano que la tabla de paquetes declara. Con 20 o con 24 no cerraria.
LAP_POSITIONS_VUELTAS = 50
LAP_POSITIONS_CABEZA_FMT = "<BB"
LAP_POSITIONS_CABEZA_TAMANO = struct.calcsize(LAP_POSITIONS_CABEZA_FMT)


def _milisegundos(minutos: int, ms: int) -> int:
    """Compone un tiempo partido en minutos enteros y milisegundos.

    Ninguna de las dos mitades significa nada por separado, de modo que se
    componen aca y no en cada consumidor.
    """

    return minutos * 60_000 + ms


def _desempaquetar_session_history(datos: bytes) -> dict[str, Any]:
    """Nombra el historial de vueltas y de tandas de **un** vehiculo.

    El paquete no describe a los veintidos: describe a uno, y el campo
    `car_idx` dice a cual. El juego rota entre vehiculos, de modo que la
    historia completa de la parrilla se arma acumulando paquetes sucesivos.
    """

    cabeza = struct.unpack_from(SESSION_HISTORY_CABEZA_FMT, datos, CABECERA_TAMANO)
    inicio = CABECERA_TAMANO + SESSION_HISTORY_CABEZA_TAMANO

    vueltas = []
    for i in range(LAP_HISTORY_VUELTAS):
        b = struct.unpack_from(LAP_HISTORY_FMT, datos,
                               inicio + i * LAP_HISTORY_TAMANO)
        banderas = b[7]
        vueltas.append({
            "numero": i + 1,
            "lap_time_ms": b[0],
            "sector1_ms": _milisegundos(b[2], b[1]),
            "sector2_ms": _milisegundos(b[4], b[3]),
            "sector3_ms": _milisegundos(b[6], b[5]),
            # Los cuatro bits de validez, nombrados. La especificacion los
            # declara como banderas y no como un valor: una vuelta puede ser
            # invalida con dos sectores validos, y eso es informacion que un
            # unico booleano perderia.
            "vuelta_valida": bool(banderas & 0x01),
            "sector1_valido": bool(banderas & 0x02),
            "sector2_valido": bool(banderas & 0x04),
            "sector3_valido": bool(banderas & 0x08),
        })

    inicio_tandas = inicio + LAP_HISTORY_VUELTAS * LAP_HISTORY_TAMANO
    tandas = []
    for i in range(TYRE_STINT_MAXIMO):
        b = struct.unpack_from(TYRE_STINT_FMT, datos,
                               inicio_tandas + i * TYRE_STINT_TAMANO)
        tandas.append({
            # 255 significa que la tanda es la actual y todavia no termino.
            "vuelta_final": b[0],
            "compuesto_real": b[1],
            "compuesto_visual": b[2],
        })

    num_vueltas = cabeza[1]
    num_tandas = cabeza[2]
    return {
        "car_idx": cabeza[0],
        "num_vueltas": num_vueltas,
        "num_tandas": num_tandas,
        "mejor_vuelta_num": cabeza[3],
        "mejor_sector1_num": cabeza[4],
        "mejor_sector2_num": cabeza[5],
        "mejor_sector3_num": cabeza[6],
        # El arreglo trae cien entradas siempre; solo las primeras `num_vueltas`
        # tienen dato. Se recortan aca en lugar de dejar que cada consumidor
        # decida donde termina la historia, que es como se cuelan vueltas de
        # cero milisegundos en un promedio.
        "vueltas": vueltas[:num_vueltas],
        "tandas": tandas[:num_tandas],
    }


def _desempaquetar_lap_positions(datos: bytes) -> dict[str, Any]:
    """Nombra la posicion de cada vehiculo al empezar cada vuelta."""

    num_vueltas, vuelta_inicial = struct.unpack_from(
        LAP_POSITIONS_CABEZA_FMT, datos, CABECERA_TAMANO)
    inicio = CABECERA_TAMANO + LAP_POSITIONS_CABEZA_TAMANO

    por_vuelta = []
    for v in range(LAP_POSITIONS_VUELTAS):
        fila = struct.unpack_from(f"<{VEHICULOS}B", datos,
                                  inicio + v * VEHICULOS)
        por_vuelta.append(list(fila))

    return {
        "num_vueltas": num_vueltas,
        "vuelta_inicial": vuelta_inicial,
        # Igual que arriba: el arreglo trae cincuenta filas y solo las primeras
        # `num_vueltas` describen algo. Un cero significa "sin registro" y no
        # "posicion cero", de modo que recortar evita que se lea como puesto.
        #
        # La clave se llama `por_vuelta` y no `posiciones` porque el paquete ya
        # se expone bajo esa palabra: `d["posiciones"]["posiciones"]` invita a
        # leer una de las dos por la otra.
        "por_vuelta": por_vuelta[:num_vueltas],
    }


# Paquetes de bloque unico: describen la sesion, no a cada vehiculo, de modo
# que no llevan arreglo de 22 entradas y se decodifican de una sola vez.
_DECODIFICADORES_UNICOS = {
    1: (SESSION_FMT, _desempaquetar_session),
    13: (MOTION_EX_FMT, _desempaquetar_motion_ex),
}

# Paquetes con su propia forma: ni un instante por vehiculo ni un bloque de
# sesion, sino hechos cerrados con arreglos internos.
_DECODIFICADORES_PROPIOS = {
    11: ("historial", _desempaquetar_session_history),
    15: ("posiciones", _desempaquetar_lap_positions),
}

# Paquetes con un arreglo de una entrada por vehiculo.
_DECODIFICADORES = {
    0: (MOTION_FMT, MOTION_TAMANO, 0, _desempaquetar_motion),
    4: (PARTICIPANTE_FMT, PARTICIPANTE_TAMANO, 0, _desempaquetar_participante),
    5: (CAR_SETUP_FMT, CAR_SETUP_TAMANO, CAR_SETUP_COLA_TAMANO, _desempaquetar_car_setup),
    7: (CAR_STATUS_FMT, CAR_STATUS_TAMANO, 0, _desempaquetar_car_status),
    10: (CAR_DAMAGE_FMT, CAR_DAMAGE_TAMANO, 0, _desempaquetar_car_damage),
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

    for packet_id, (formato, _) in _DECODIFICADORES_UNICOS.items():
        declarado = PAQUETES[packet_id]["tamano"]
        calculado = CABECERA_TAMANO + struct.calcsize(formato)
        filas.append({
            "estructura": PAQUETES[packet_id]["nombre"],
            "bloque_unico": True,
            "calculado": calculado,
            "declarado": declarado,
            "coincide": calculado == declarado,
        })

    for packet_id, (_, por_vehiculo, cola, _) in _DECODIFICADORES.items():
        declarado = PAQUETES[packet_id]["tamano"]
        # La cabeza entra en la cuenta. Omitirla es el mismo defecto que
        # desplazaria las veintidos entradas, visto desde la verificacion: el
        # total no cerraria y el paquete quedaria reportado como desajustado.
        cabeza = (struct.calcsize(_CABEZAS[packet_id][0])
                  if packet_id in _CABEZAS else 0)
        calculado = CABECERA_TAMANO + cabeza + VEHICULOS * por_vehiculo + cola
        filas.append({
            "estructura": PAQUETES[packet_id]["nombre"],
            "por_vehiculo": por_vehiculo,
            "cabeza": cabeza,
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

    # El evento se resuelve aparte: su forma depende del contenido, no del
    # identificador, de modo que no puede entrar en un registro de formatos.
    if packet_id == 3:
        resultado["decodificado"] = True
        resultado.update(_desempaquetar_event(datos))
        return resultado

    if packet_id in _DECODIFICADORES_UNICOS:
        formato, nombrar = _DECODIFICADORES_UNICOS[packet_id]
        resultado["decodificado"] = True
        resultado["sesion"] = nombrar(struct.unpack_from(formato, datos, CABECERA_TAMANO))
        return resultado

    if packet_id in _DECODIFICADORES_PROPIOS:
        clave, nombrar = _DECODIFICADORES_PROPIOS[packet_id]
        resultado["decodificado"] = True
        resultado[clave] = nombrar(datos)
        return resultado

    if packet_id not in _DECODIFICADORES:
        resultado["decodificado"] = False
        resultado["motivo"] = "sin decodificador para este paquete"
        return resultado

    formato, por_vehiculo, _, nombrar = _DECODIFICADORES[packet_id]

    # Los campos previos al arreglo corren el origen de las veintidos entradas.
    inicio = CABECERA_TAMANO
    if packet_id in _CABEZAS:
        formato_cabeza, nombres_cabeza = _CABEZAS[packet_id]
        valores = struct.unpack_from(formato_cabeza, datos, CABECERA_TAMANO)
        resultado.update(dict(zip(nombres_cabeza, valores)))
        inicio += struct.calcsize(formato_cabeza)

    vehiculos = []
    for indice in range(VEHICULOS):
        desplazamiento = inicio + indice * por_vehiculo
        vehiculos.append(nombrar(struct.unpack_from(formato, datos, desplazamiento)))

    resultado["decodificado"] = True
    resultado["vehiculos"] = vehiculos
    resultado["vehiculo_propio"] = vehiculos[cabecera["player_car_index"]]

    # El segundo jugador de una partida en pantalla dividida. La cabecera declara
    # su indice y usa 255 para decir que no hay ninguno, de modo que la ausencia
    # se distingue de la posicion cero sin ambiguedad.
    indice_secundario = cabecera["secondary_player_car_index"]
    if indice_secundario != SIN_SEGUNDO_JUGADOR and indice_secundario < VEHICULOS:
        resultado["vehiculo_secundario"] = vehiculos[indice_secundario]
        resultado["indice_secundario"] = indice_secundario

    if packet_id in _COLAS:
        formato_cola, nombrar_cola = _COLAS[packet_id]
        desplazamiento = inicio + VEHICULOS * por_vehiculo
        resultado.update(nombrar_cola(struct.unpack_from(formato_cola, datos, desplazamiento)))
    return resultado
