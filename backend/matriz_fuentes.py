"""Matriz de capacidades y ausencias de las tres fuentes.

Que responde
------------
No «que senales tiene cada fuente» —eso es una lista— sino **que puede medirse en
cada una y con que resolucion**. Son preguntas distintas: dos fuentes pueden
publicar la aceleracion lateral y una entregarla a setenta y ocho hercios en
metros por segundo al cuadrado mientras la otra la da a veintidos en unidades de
g. Ese contraste **es en si mismo un resultado del trabajo**, y es lo que decide
que analisis habilita cada fuente.

Como se construye
-----------------
Se organiza **por magnitud fisica** y no por nombre de senal. Cada fuente nombra
lo suyo a su manera —la fuente deportiva llama `brake_applied` a lo que el bus del
vehiculo llama `brake_pressed`— y comparar nombres no compararia nada.

La correspondencia entre magnitud y senal es la unica parte escrita a mano, y se
justifica: **no se deduce del dato**. Que el angulo de direccion en grados y la
posicion normalizada del volante midan lo mismo es conocimiento del dominio, no
una propiedad de las tablas.

Todo lo demas se deriva: las senales disponibles salen del catalogo de cada
adaptador, la frecuencia se **mide sobre lo persistido** y la confianza viene de
la matriz de evidencia. Ninguna cifra se declara sin haberla medido.

Que se cuenta como ausencia
---------------------------
Una magnitud que una fuente no publica aparece como ausencia **con su motivo**, y
los motivos no son equivalentes: el bus de un vehiculo de calle no tiene alerones
moviles porque el vehiculo no los tiene, mientras que la fuente deportiva no
entrega aceleracion porque **su interfaz publica no la expone**, aunque el
vehiculo la mida. La primera es un limite del objeto; la segunda, del acceso.
"""

from __future__ import annotations

import time
from typing import Any

from backend import db

#: Vigencia del calculo. La matriz cambia solo cuando se cargan datos nuevos, y
#: medir frecuencias sobre millones de filas no es gratis.
VIGENCIA_S = 300.0
_CACHE: tuple[float, dict] | None = None

FUENTES = [
    {
        "clave": "can_real_replay",
        "nombre": "Bus de vehiculo real",
        "detalle": "Toyota RAV4, tramas grabadas y reproducidas",
        "nivel": "A",
        "medicion": "sensores del vehiculo",
    },
    {
        "clave": "openf1_historical_replay",
        "nombre": "Fuente deportiva",
        "detalle": "OpenF1, sesion historica reproducida",
        "nivel": "B",
        "medicion": "vehiculo de competicion, ya procesado por un tercero",
    },
    {
        "clave": "f1_25_udp_simulation",
        "nombre": "Simulador",
        "detalle": "F1 25 por UDP oficial",
        "nivel": "C",
        "medicion": "modelo fisico del simulador",
    },
]

#: Correspondencia entre magnitud fisica y como la nombra cada fuente.
#:
#: Es la unica parte escrita a mano de este modulo. Se justifica porque **no se
#: deduce del dato**: que `brake_applied` y `brake_pressed` midan lo mismo, o que
#: la posicion normalizada del volante y el angulo en grados sean la misma
#: magnitud, es conocimiento del dominio.
#:
#: Donde una fuente no publica la magnitud va el motivo, y los motivos se
#: distinguen: no tenerlo el vehiculo no es lo mismo que no exponerlo la interfaz.
MAGNITUDES: list[dict[str, Any]] = [
    {
        "magnitud": "Velocidad del vehiculo",
        "familia": "movimiento",
        "por_fuente": {
            "can_real_replay": "speed",
            "openf1_historical_replay": "speed",
            "f1_25_udp_simulation": "speed",
        },
    },
    {
        "magnitud": "Velocidad por rueda",
        "familia": "movimiento",
        "por_fuente": {
            "can_real_replay": "wheel_speed_front_left",
            "openf1_historical_replay": None,
            "f1_25_udp_simulation": None,
        },
        "ausencias": {
            "openf1_historical_replay": "la interfaz publica no la expone",
            "f1_25_udp_simulation": "el protocolo no publica velocidad por rueda",
        },
    },
    {
        "magnitud": "Aceleracion longitudinal",
        "familia": "dinamica",
        "por_fuente": {
            "can_real_replay": "accel_longitudinal",
            "openf1_historical_replay": None,
            "f1_25_udp_simulation": "g_force_longitudinal",
        },
        "ausencias": {
            "openf1_historical_replay": "la interfaz publica no la expone, "
                                        "aunque el vehiculo la mide",
        },
        "nota": "la misma magnitud en unidades distintas: el bus la da en metros "
                "por segundo al cuadrado y el simulador en unidades de g",
    },
    {
        "magnitud": "Aceleracion lateral",
        "familia": "dinamica",
        "por_fuente": {
            "can_real_replay": "accel_lateral",
            "openf1_historical_replay": None,
            "f1_25_udp_simulation": "g_force_lateral",
        },
        "ausencias": {
            "openf1_historical_replay": "la interfaz publica no la expone",
        },
    },
    {
        "magnitud": "Velocidad de guinada",
        "familia": "dinamica",
        "por_fuente": {
            "can_real_replay": "yaw_rate",
            "openf1_historical_replay": None,
            "f1_25_udp_simulation": "yaw_rate_rads",
        },
        "ausencias": {
            "openf1_historical_replay": "la interfaz publica no la expone",
        },
    },
    {
        "magnitud": "Direccion",
        "familia": "conduccion",
        "por_fuente": {
            "can_real_replay": "steer_angle",
            "openf1_historical_replay": None,
            "f1_25_udp_simulation": "steering_normalized",
        },
        "ausencias": {
            "openf1_historical_replay": "la interfaz publica no la expone",
        },
        "nota": "el bus la da en grados y el simulador normalizada entre menos "
                "uno y uno: comparables en forma, no en escala",
    },
    {
        "magnitud": "Freno",
        "familia": "conduccion",
        "por_fuente": {
            "can_real_replay": "brake_pressed",
            "openf1_historical_replay": "brake_applied",
            "f1_25_udp_simulation": "brake_position",
        },
        "nota": "solo el simulador entrega intensidad; las otras dos publican si "
                "el freno esta aplicado o no",
    },
    {
        "magnitud": "Acelerador",
        "familia": "conduccion",
        "por_fuente": {
            "can_real_replay": "gas_pressed",
            "openf1_historical_replay": "throttle_position",
            "f1_25_udp_simulation": "throttle_position",
        },
        "nota": "el bus publica un booleano; las otras dos, porcentaje",
    },
    {
        "magnitud": "Regimen del motor",
        "familia": "motor",
        "por_fuente": {
            "can_real_replay": None,
            "openf1_historical_replay": "engine_speed",
            "f1_25_udp_simulation": "engine_speed",
        },
        "ausencias": {
            "can_real_replay": "queda fuera del conjunto respaldado por la "
                               "matriz de evidencia",
        },
    },
    {
        "magnitud": "Marcha",
        "familia": "motor",
        "por_fuente": {
            "can_real_replay": None,
            "openf1_historical_replay": "gear_selected",
            "f1_25_udp_simulation": "gear_selected",
        },
        "ausencias": {
            "can_real_replay": "el campo declara estacionado con el vehiculo en "
                               "movimiento en 28 de 30 segmentos",
        },
    },
    {
        "magnitud": "Energia y unidad de potencia",
        "familia": "motor",
        "por_fuente": {
            "can_real_replay": None,
            "openf1_historical_replay": None,
            "f1_25_udp_simulation": "ers_stored_energy",
        },
        "ausencias": {
            "can_real_replay": "el vehiculo no tiene sistema de recuperacion",
            "openf1_historical_replay": "la interfaz publica no la expone",
        },
    },
    {
        "magnitud": "Dano y desgaste",
        "familia": "salud",
        "por_fuente": {
            "can_real_replay": None,
            "openf1_historical_replay": None,
            "f1_25_udp_simulation": "tyre_wear_front_left",
        },
        "ausencias": {
            "can_real_replay": "un vehiculo de calle no publica desgaste por rueda",
            "openf1_historical_replay": "la interfaz publica no la expone",
        },
    },
    {
        "magnitud": "Posicion en el trazado",
        "familia": "trazado",
        "por_fuente": {
            "can_real_replay": None,
            "openf1_historical_replay": "track_position_x",
            "f1_25_udp_simulation": "world_position_x",
        },
        "ausencias": {
            "can_real_replay": "el conjunto es anonimo y no publica localizacion",
        },
    },
    {
        "magnitud": "Aleron movil",
        "familia": "competicion",
        "por_fuente": {
            "can_real_replay": None,
            "openf1_historical_replay": "drs_state_code",
            "f1_25_udp_simulation": "drs_open",
        },
        "ausencias": {
            "can_real_replay": "el vehiculo no lo tiene",
        },
        "nota": "el simulador lo entrega como booleano documentado y la fuente "
                "deportiva como codigo de estado con valores indeterminados",
    },
]


#: Ventana sobre la que se mide la frecuencia.
#:
#: Una frecuencia es una razon: medirla sobre un minuto da lo mismo que sobre
#: dos horas, y cuesta muchisimo menos. La primera version media sobre la sesion
#: completa y tardaba tres minutos en construir la matriz, porque la sesion de la
#: fuente deportiva tiene siete millones y medio de filas.
VENTANA_MEDICION_S = 120


def _contexto_reciente(cursor, fuente: str) -> tuple[str, str, Any] | None:
    """Sesion, conductor e instante mas recientes de una fuente.

    Se resuelve **una vez por fuente** y no una vez por senal, y se toma el
    conductor y no el vehiculo porque es lo que el indice de la tabla ordena
    despues de la sesion.

    Medir por conductor no es un detalle: la fuente deportiva reune veinte en una
    misma sesion, y contarlos juntos multiplica por veinte la frecuencia
    aparente. Ya paso —la primera medicion dio noventa hercios donde hay cuatro—
    y por eso la resolucion del contexto incluye al conductor.
    """

    cursor.execute(
        """select session_id, driver_id, max(timestamp)
           from telemetry_messages
           where source_type = %s
           group by session_id, driver_id
           order by max(timestamp) desc limit 1""",
        (fuente,),
    )
    return cursor.fetchone()


def _medir(cursor, fuente: str, senal: str,
           contexto: tuple[str, str, Any] | None) -> dict[str, Any] | None:
    """Mide la frecuencia de una senal sobre una ventana del final de la sesion."""

    if contexto is None:
        return None
    sesion, conductor, hasta = contexto

    cursor.execute(
        """select count(*),
                  extract(epoch from (max(timestamp) - min(timestamp))),
                  min(unit)
           from telemetry_messages
           where source_type = %s and session_id = %s and driver_id = %s
             and signal_name = %s
             and timestamp > %s - make_interval(secs => %s)
             and timestamp <= %s""",
        (fuente, sesion, conductor, senal, hasta, VENTANA_MEDICION_S, hasta),
    )
    muestras, ventana, unidad = cursor.fetchone()
    if not muestras:
        return None
    if not ventana or float(ventana) <= 0:
        return {"senal": senal, "unidad": unidad, "muestras": muestras, "hz": None}
    return {
        "senal": senal,
        "unidad": unidad,
        "muestras": muestras,
        "ventana_s": round(float(ventana), 1),
        "hz": round(muestras / float(ventana), 1),
    }


def construir() -> dict[str, Any]:
    """Arma la matriz midiendo sobre lo persistido."""

    global _CACHE
    ahora = time.monotonic()
    if _CACHE and ahora - _CACHE[0] < VIGENCIA_S:
        return {**_CACHE[1], "edad_del_calculo_s": round(ahora - _CACHE[0], 1)}

    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        fuentes = []
        for definicion in FUENTES:
            cursor.execute(
                """select count(*), count(distinct signal_name),
                          count(distinct session_id), count(distinct vehicle_id)
                   from telemetry_messages where source_type = %s""",
                (definicion["clave"],),
            )
            filas, senales, sesiones, vehiculos = cursor.fetchone()
            fuentes.append({**definicion, "filas": filas, "senales": senales,
                            "sesiones": sesiones, "vehiculos": vehiculos})

        # Una sola resolucion de contexto por fuente, no una por senal.
        contextos = {f["clave"]: _contexto_reciente(cursor, f["clave"])
                     for f in FUENTES}

        magnitudes = []
        for entrada in MAGNITUDES:
            fila: dict[str, Any] = {
                "magnitud": entrada["magnitud"],
                "familia": entrada["familia"],
                "nota": entrada.get("nota"),
                "fuentes": {},
            }
            for clave in (f["clave"] for f in FUENTES):
                senal = entrada["por_fuente"].get(clave)
                if senal is None:
                    fila["fuentes"][clave] = {
                        "disponible": False,
                        "motivo": entrada.get("ausencias", {}).get(clave),
                    }
                    continue
                medida = _medir(cursor, clave, senal, contextos.get(clave))
                fila["fuentes"][clave] = {
                    "disponible": medida is not None,
                    **(medida or {"senal": senal,
                                  "motivo": "declarada pero sin datos cargados"}),
                }
            magnitudes.append(fila)

    resultado = {"fuentes": fuentes, "magnitudes": magnitudes,
                 "medido_sobre": "la sesion y el vehiculo mas recientes de cada fuente"}
    _CACHE = (ahora, resultado)
    return resultado
