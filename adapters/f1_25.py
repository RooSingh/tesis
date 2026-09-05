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
    # Booleano documentado. Su contraste con la fuente deportiva es un
    # resultado del trabajo: alli el mismo concepto llega como un codigo
    # de estado con valores indeterminados que hubo que resolver por
    # medicion, y aqui como un booleano documentado.
    "drs": ("drs_open", "bool", 1.0),
}

# Senales del paquete de datos de vuelta.
SENALES_VUELTA: dict[str, tuple[str, str, float]] = {
    "lap_distance_m": ("lap_distance", "m", 1.0),
    "total_distance_m": ("session_distance", "m", 1.0),
    "current_lap_time_ms": ("current_lap_time", "ms", 1.0),
    "current_lap_num": ("lap_number", "lap", 1.0),
    "car_position": ("track_position_order", "position", 1.0),
    # Sin estas, una parada en boxes y una neutralizacion por coche de
    # seguridad se ven en la base como una caida de velocidad sin causa: el
    # dato queda, la explicacion se pierde.
    "pit_status": ("pit_status", "state", 1.0),
    "num_pit_stops": ("pit_stops_completed", "count", 1.0),
    "penalties_s": ("penalty_time", "s", 1.0),
    "total_warnings": ("warnings_total", "count", 1.0),
    "safety_car_delta_s": ("safety_car_delta", "s", 1.0),
    "sector": ("sector_index", "index", 1.0),
    "current_lap_invalid": ("lap_invalid", "bool", 1.0),
    "driver_status": ("driver_status", "state", 1.0),
}

# Senales del paquete de estado. Aca vive la unidad de potencia: la carga de la
# bateria, lo que se recupera y lo que se despliega en cada vuelta.
#
# Por que importan: en esta generacion de motores el rendimiento no se explica
# solo con el acelerador. Una parte de la potencia sale de energia recuperada al
# frenar y de los gases de escape, se acumula y se gasta donde el piloto decide.
# Dos vueltas con el mismo pedal pueden dar tiempos distintos segun cuanta
# energia habia disponible. Sin estos canales, esa diferencia queda sin explicar
# y se le atribuye erroneamente a la conduccion.
SENALES_ESTADO: dict[str, tuple[str, str, float]] = {
    "ers_store_energy_j": ("ers_stored_energy", "J", 1.0),
    "ers_deploy_mode": ("ers_deploy_mode", "mode", 1.0),
    "ers_harvested_this_lap_mguk_j": ("ers_harvested_mguk_lap", "J", 1.0),
    "ers_harvested_this_lap_mguh_j": ("ers_harvested_mguh_lap", "J", 1.0),
    "ers_deployed_this_lap_j": ("ers_deployed_lap", "J", 1.0),
    "fuel_in_tank_kg": ("fuel_mass", "kg", 1.0),
    "fuel_remaining_laps": ("fuel_remaining_laps", "lap", 1.0),
    "fuel_mix": ("fuel_mix_mode", "mode", 1.0),
    "front_brake_bias_pct": ("brake_bias_front", "%", 1.0),
    "actual_tyre_compound": ("tyre_compound", "code", 1.0),
    "tyres_age_laps": ("tyre_age", "lap", 1.0),
    "drs_allowed": ("drs_allowed", "bool", 1.0),
    # Metros que faltan para que el aleron movil se habilite; cero cuando
    # no esta disponible. Es la contraparte cuantitativa del booleano, y sin
    # ella no se puede verificar donde empieza la zona.
    "drs_activation_distance_m": ("drs_activation_distance", "m", 1.0),
    "pit_limiter": ("pit_limiter", "bool", 1.0),
    "vehicle_fia_flags": ("fia_flag", "code", 1.0),
}

# Senales del paquete de dano que valen por vehiculo entero.
SENALES_DANO: dict[str, tuple[str, str, float]] = {
    "front_left_wing_damage_pct": ("wing_damage_front_left", "%", 1.0),
    "front_right_wing_damage_pct": ("wing_damage_front_right", "%", 1.0),
    "rear_wing_damage_pct": ("wing_damage_rear", "%", 1.0),
    "floor_damage_pct": ("floor_damage", "%", 1.0),
    "diffuser_damage_pct": ("diffuser_damage", "%", 1.0),
    "sidepod_damage_pct": ("sidepod_damage", "%", 1.0),
    "gearbox_damage_pct": ("gearbox_damage", "%", 1.0),
    "engine_damage_pct": ("engine_damage", "%", 1.0),
    "engine_ice_wear_pct": ("engine_wear_ice", "%", 1.0),
    "engine_mguk_wear_pct": ("engine_wear_mguk", "%", 1.0),
    "engine_mguh_wear_pct": ("engine_wear_mguh", "%", 1.0),
    "engine_es_wear_pct": ("engine_wear_es", "%", 1.0),
    "engine_ce_wear_pct": ("engine_wear_ce", "%", 1.0),
    "engine_tc_wear_pct": ("engine_wear_tc", "%", 1.0),
    "drs_fault": ("drs_fault", "bool", 1.0),
    "ers_fault": ("ers_fault", "bool", 1.0),
    "engine_blown": ("engine_blown", "bool", 1.0),
    "engine_seized": ("engine_seized", "bool", 1.0),
}

# Campos que traen un valor por rueda. Se emiten como cuatro senales con la
# rueda en el nombre: aplanarlos en el borde evita que cada consulta posterior
# tenga que saber en que orden vienen las ruedas, que es exactamente el detalle
# que ya causo un error de interpretacion en este trabajo.
SENALES_POR_RUEDA: dict[str, tuple[str, str, str]] = {
    "tyres_wear_pct": ("tyre_wear", "%", "car_damage"),
    "tyres_damage_pct": ("tyre_damage", "%", "car_damage"),
    "brakes_damage_pct": ("brake_damage", "%", "car_damage"),
    "tyre_blisters_pct": ("tyre_blisters", "%", "car_damage"),
    "tyres_surface_temperature_c": ("tyre_temperature_surface", "celsius", "car_telemetry"),
    "tyres_inner_temperature_c": ("tyre_temperature_inner", "celsius", "car_telemetry"),
    "tyres_pressure_psi": ("tyre_pressure", "psi", "car_telemetry"),
    "brakes_temperature_c": ("brake_temperature", "celsius", "car_telemetry"),
    "surface_type": ("surface_type", "code", "car_telemetry"),
    # Fraccion en que la superficie del neumatico gira mas rapido que el avance
    # del vehiculo. Es el canal del resultado central sobre asistencias.
    "wheel_slip_ratio": ("wheel_slip_ratio", "ratio", "motion_ex"),
    # Velocidad de giro de cada rueda. Es el equivalente directo de la senal
    # `wheel_speeds` ya validada sobre el bus CAN real de un vehiculo de calle.
    "wheel_speed": ("wheel_speed", "m/s", "motion_ex"),
}

# Nombre corto de cada rueda para componer el nombre de senal.
SUFIJO_RUEDA = {
    "trasera_izquierda": "rear_left", "trasera_derecha": "rear_right",
    "delantera_izquierda": "front_left", "delantera_derecha": "front_right",
}


# Senales del paquete de movimiento. **Nueve de dieciocho**, y la seleccion es
# una decision de alcance que conviene declarar:
#
# * **la aceleracion en los tres ejes** entra porque es el unico canal del
#   protocolo que existe con el mismo significado fisico en un vehiculo real. Un
#   acelerometro publica aceleracion lateral y longitudinal en el bus, y el
#   simulador la entrega en las mismas unidades, de modo que **el mismo analisis
#   corre sobre las dos fuentes sin traducir nada**;
# * **la posicion en el mundo** entra porque es lo unico que permite dibujar el
#   trazado y ubicar a los vehiculos sobre el. Sin ella solo se conoce el avance
#   sobre la linea de referencia, que no dice donde esta el vehiculo;
# * **guinada, cabeceo y balanceo** entran porque son la actitud del vehiculo, y
#   el balanceo en particular es dinamica que ningun otro paquete publica.
#
# Quedan afuera, por redundantes y no por costo:
#
# * el **vector de velocidad**, cuyo modulo ya viaja como velocidad en el paquete
#   de telemetria;
# * los **seis campos de direccion**, que expresan la misma orientacion que
#   guinada, cabeceo y balanceo y en una forma menos interpretable.
#
# Publicar los dieciocho costaria 553.104 filas por carrera contra 276.552, sin
# agregar nada que no este ya.
SENALES_MOVIMIENTO: dict[str, tuple[str, str, float]] = {
    "g_force_lateral": ("g_force_lateral", "g", 1.0),
    "g_force_longitudinal": ("g_force_longitudinal", "g", 1.0),
    "g_force_vertical": ("g_force_vertical", "g", 1.0),
    # El eje y es la altura, verificado por medicion: en la carrera capturada su
    # recorrido es de 11,6 m contra 1.022 y 1.725 de los otros dos.
    "world_position_x_m": ("world_position_x", "m", 1.0),
    "world_position_y_m": ("world_position_y", "m", 1.0),
    "world_position_z_m": ("world_position_z", "m", 1.0),
    "yaw_rad": ("yaw", "rad", 1.0),
    "pitch_rad": ("pitch", "rad", 1.0),
    "roll_rad": ("roll", "rad", 1.0),
}


# Senales de dinamica del vehiculo, del paquete `motion_ex`.
#
# **Nueve de sesenta y uno**, y la seleccion tambien es una decision de alcance.
# El paquete se decodificaba desde el Dia 25 y no entraba al contrato interno, de
# modo que sus canales existian en la captura y no en la base ni en la vista.
# Entraron cuando quedo claro que la ausencia tenia una consecuencia concreta: la
# regla del deslizamiento producia **siete de los diez incidentes** de la captura
# sin control de traccion, y en vivo no podia evaluarse.
#
# Entran:
#
# * el **deslizamiento de cada rueda**, cuatro senales, que es el canal sobre el
#   que se apoya el resultado central del analisis de asistencias y la unica
#   regla del anotador que hoy no puede evaluarse en vivo;
# * la **velocidad de guinada**, que cierra una ausencia que la propia matriz de
#   capacidades declaraba: el bus real la publica y el simulador la tenia
#   decodificada sin publicar. Va del eje `y` y no del `z`, verificado por
#   integracion sobre una vuelta completa.
#
# * la **velocidad de cada rueda**, cuatro senales, que es el equivalente directo
#   de `wheel_speeds` ya validada sobre el bus CAN real. Es la que mejor sostiene
#   el argumento central de esta tesis: **el mismo analisis corre sobre las dos
#   fuentes sin traducir nada**. Un vehiculo de calle publica la velocidad de sus
#   cuatro ruedas en el bus, y el simulador la entrega con el mismo significado
#   fisico y en la misma unidad.
#
# Quedan afuera, y conviene decir cuales porque no es por falta de valor:
#
# * los **doce campos de suspension**, el **angulo de deslizamiento**, las **ocho
#   fuerzas por rueda** y la **altura del centro de gravedad**, que describen
#   dinamica que este trabajo no analiza;
# * el **vector de velocidad local**, redundante con la velocidad que ya publica
#   el paquete de telemetria.
#
# Costo medido sobre la carrera de Silverstone, 30.728 paquetes en 23 min:
# **276.552 filas**, un 11,1 % sobre las 2.489.002 ya persistidas.
SENALES_DINAMICA: dict[str, tuple[str, str, float]] = {}

#: Senales que se componen de mas de un campo del mismo paquete.
#:
#: La distancia al vehiculo de adelante viaja partida en minutos y milisegundos, y
#: ninguna de las dos mitades significa nada por separado. Componerla aca, y no en
#: cada consumidor, evita que cada uno la rearme a su manera: el contrato interno
#: entrega una magnitud, no dos fragmentos.
SENALES_COMPUESTAS: dict[str, tuple[tuple[str, ...], Any, str, str]] = {
    "delta_to_car_in_front": (
        ("delta_to_car_in_front_minutes_part", "delta_to_car_in_front_ms_part"),
        lambda minutos, ms: minutos * 60_000 + ms,
        "ms", "lap_data",
    ),
    "delta_to_race_leader": (
        ("delta_to_race_leader_minutes_part", "delta_to_race_leader_ms_part"),
        lambda minutos, ms: minutos * 60_000 + ms,
        "ms", "lap_data",
    ),
}

#: Campos anidados: el valor no esta en la raiz del paquete sino dentro de otro.
#:
#: La velocidad angular viaja como un vector de tres ejes y solo interesa uno. Se
#: declara con su ruta en lugar de aplanarse en el decodificador, porque el
#: decodificador describe el protocolo y el protocolo la publica como vector.
SENALES_ANIDADAS: dict[str, tuple[str, str, float, str]] = {
    # ruta -> nombre, unidad, factor, paquete
    "angular_velocity_rads.y": ("yaw_rate", "rad/s", 1.0, "motion_ex"),
}


#: Estado de la pista, del paquete de sesion. Llega a 2 Hz.
#:
#: **El clima es un canal y no un metadato.** Una carrera puede empezar seca y
#: terminar mojada, y la procedencia guarda un valor por captura: el del final.
#: Publicarlo por instante es lo que permite preguntar si un deslizamiento
#: coincidio con la caida de temperatura de pista, en lugar de saber solamente
#: que en algun momento llovio.
#:
#: El clima viaja como codigo y se publica como codigo. Traducirlo aca lo
#: convertiria en texto dentro de una tabla de valores medidos, y el significado
#: de cada codigo ya vive en la tabla del capturador.
SENALES_CLIMA: dict[str, tuple[str, str, float]] = {
    "weather": ("weather_code", "codigo", 1.0),
    "track_temperature_c": ("track_temperature", "C", 1.0),
    "air_temperature_c": ("air_temperature", "C", 1.0),
}


# Que paquete alimenta que mapa. Se declara aca, y no en cada consumidor, para
# que agregar una familia de senales sea un solo cambio: mientras el capturador
# llevaba su propia lista escrita a mano, ampliar el adaptador no alcanzaba para
# que los canales nuevos llegaran a la base.
MAPAS_POR_PAQUETE: dict[str, dict[str, tuple[str, str, float]]] = {
    "motion": SENALES_MOVIMIENTO,
    "car_telemetry": SENALES_TELEMETRIA,
    "lap_data": SENALES_VUELTA,
    "car_status": SENALES_ESTADO,
    "car_damage": SENALES_DANO,
    "motion_ex": SENALES_DINAMICA,
    "session": SENALES_CLIMA,
}

#: Paquetes que describen **un solo vehiculo** y no llevan arreglo de veintidos.
#:
#: El protocolo los emite para el vehiculo propio y el decodificador los deja
#: bajo otra clave. Normalizarlos por el camino de los demas paquetes buscaria un
#: arreglo que no existe.
#: El paquete de sesion describe la sesion y no a un vehiculo, de modo que entra
#: por el mismo camino: su contenido se ata al vehiculo propio, que es el unico
#: al que este trabajo puede referirlo.
PAQUETES_DE_BLOQUE_UNICO = frozenset({"motion_ex", "session"})

#: Paquetes que este adaptador sabe convertir al contrato interno.
PAQUETES_NORMALIZABLES = frozenset(MAPAS_POR_PAQUETE)



def catalogo_de_senales() -> list[dict[str, str]]:
    """Todas las senales que este adaptador produce, con unidad y paquete.

    Se deriva de los mismos mapas que usa la normalizacion, no de una lista
    aparte ni de una consulta a la base. Los tres caminos darian hoy la misma
    respuesta; solo este **no puede** dar una distinta manana, porque no hay una
    segunda copia que pueda quedar desactualizada.

    Preguntarselo a la base tampoco serviria: solo diria que senales llegaron a
    guardarse, que es justo lo que fallaba cuando el capturador publicaba dos
    paquetes de cuatro.
    """

    catalogo: list[dict[str, str]] = []
    for paquete, mapa in MAPAS_POR_PAQUETE.items():
        for _, (nombre, unidad, _) in mapa.items():
            catalogo.append({"signal_name": nombre, "unit": unidad,
                             "paquete": paquete})
    for campo, (base, unidad, paquete) in SENALES_POR_RUEDA.items():
        for sufijo in SUFIJO_RUEDA.values():
            catalogo.append({"signal_name": f"{base}_{sufijo}", "unit": unidad,
                             "paquete": paquete})
    for _, (nombre, unidad, _, paquete) in SENALES_ANIDADAS.items():
        catalogo.append({"signal_name": nombre, "unit": unidad,
                         "paquete": paquete})
    for nombre, (_, _, unidad, paquete) in SENALES_COMPUESTAS.items():
        catalogo.append({"signal_name": nombre, "unit": unidad,
                         "paquete": paquete})
    return sorted(catalogo, key=lambda s: (s["paquete"], s["signal_name"]))


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
    desplazamiento_captura_us: int | None = None,
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
    mapas = MAPAS_POR_PAQUETE
    if paquete not in mapas:
        raise ErrorNormalizacion(f"Paquete sin normalizacion definida: {paquete}")
    mapa = mapas[paquete]
    por_rueda = {campo: destino for campo, destino in SENALES_POR_RUEDA.items()
                 if destino[2] == paquete}

    cabecera = decodificado["cabecera"]
    session_uid = cabecera["session_uid"]
    indice_propio = cabecera["player_car_index"]
    marca = _marca_temporal(inicio_captura_utc, cabecera["session_time"])

    if paquete in PAQUETES_DE_BLOQUE_UNICO:
        # Describe al vehiculo propio y nada mas. El pedido de todos los
        # vehiculos no se puede satisfacer, y devolver solo el propio en
        # silencio haria creer que se devolvieron los veintidos.
        if not solo_vehiculo_propio:
            raise ErrorNormalizacion(
                f"El paquete {paquete} describe unicamente al vehiculo propio; "
                "no puede normalizarse para todos los vehiculos."
            )
        seleccion = [(indice_propio, decodificado["sesion"])]
    elif solo_vehiculo_propio:
        seleccion = [(indice_propio, decodificado["vehiculo_propio"])]
        # En pantalla dividida el segundo jugador tambien se normaliza. No es un
        # tercero: comparte la consola. Cada uno viaja con su propio
        # identificador de vehiculo y de conductor, que es lo que permite
        # compararlos sin mezclarlos.
        secundario = decodificado.get("vehiculo_secundario")
        if secundario is not None:
            seleccion.append((decodificado["indice_secundario"], secundario))
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
        pares: list[tuple[str, str, str, Any, float]] = []
        for campo, (nombre, unidad, factor) in mapa.items():
            if campo in vehiculo:
                pares.append((campo, nombre, unidad, vehiculo[campo], factor))
        # Los campos por rueda se aplanan en cuatro senales, con la rueda en el
        # nombre y tambien declarada aparte en los metadatos.
        for campo, (base, unidad, _) in por_rueda.items():
            valores = vehiculo.get(campo)
            if not isinstance(valores, dict):
                continue
            for rueda, valor in valores.items():
                sufijo = SUFIJO_RUEDA.get(rueda, rueda)
                pares.append((campo, f"{base}_{sufijo}", unidad, valor, 1.0))
        # Senales que se componen de mas de un campo del mismo paquete.
        for nombre_c, (campos, componer, unidad_c, paquete_c) in SENALES_COMPUESTAS.items():
            if paquete_c != paquete:
                continue
            if all(c in vehiculo for c in campos):
                pares.append((nombre_c, nombre_c, unidad_c,
                              componer(*(vehiculo[c] for c in campos)), 1.0))

        # Campos que viajan dentro de otro, como un eje de un vector.
        for ruta, (nombre_a, unidad_a, factor_a, paquete_a) in SENALES_ANIDADAS.items():
            if paquete_a != paquete:
                continue
            raiz, _, subcampo = ruta.partition(".")
            contenedor = vehiculo.get(raiz)
            if isinstance(contenedor, dict) and subcampo in contenedor:
                pares.append((ruta, nombre_a, unidad_a,
                              contenedor[subcampo], factor_a))

        for campo, nombre, unidad, crudo, factor in pares:
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
                        # Dos relojes, y ninguno reemplaza al otro.
                        #
                        # El reloj de sesion es el que alinea con el juego —el
                        # video, el tablero, los eventos de carrera— pero **se
                        # detiene mientras los marcos siguen avanzando**: en una
                        # carrera de 1.537 s reales cerro en 1.377,86, y 207
                        # marcos comparten su marca con el anterior. No es una
                        # clave unica ni es proporcional al tiempo transcurrido.
                        #
                        # El desplazamiento de la captura si es monotono y mide
                        # tiempo real. Se transporta junto al otro en lugar de
                        # reemplazarlo, porque sustituir uno por otro cambiaria
                        # un punto ciego por el opuesto.
                        "desplazamiento_captura_us": desplazamiento_captura_us,
                        "player_car_index": indice_propio,
                        "campo_origen": campo,
                        # Se declara por senal y no por mensaje uniforme: algunas
                        # se convierten y otras no.
                        "transformation": (
                            "cast_bool" if unidad == "bool"
                            else "identity" if factor == 1.0
                            else f"escala_x{factor:g}"
                        ),
                        "captura_sha256": captura_sha256,
                    },
                },
            })

    if not mensajes:
        raise ErrorNormalizacion(
            f"El paquete {paquete} no aporto ninguna senal conocida."
        )
    return mensajes
