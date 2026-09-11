# -*- coding: utf-8 -*-
"""Rutas de lectura de una sesion persistida, para las tres fuentes.

QUE RESUELVE ESTE MODULO
------------------------
El tablero se dibuja contra la distancia recorrida, muestra el trazado, el
estado del vehiculo, el clima y los avisos de una sesion **ya guardada**.
Nada de eso tenia ruta: la API servia el flujo en vivo y la fuente deportiva,
y para la fuente de simulacion solo habia consultas crudas por senal.

POR QUE TODO PIDE `session_id` Y `fuente`
-----------------------------------------
`telemetry_messages` es una hipertabla comprimida cuyas columnas de
segmentacion son `signal_name`, `session_id`, `source_type` y `vehicle_id`.
Filtrar por esas columnas es barato; filtrar por cualquier otra obliga a
descomprimir. Por eso toda consulta de aca acota primero por fuente y sesion,
y nunca recorre la tabla entera. La leccion la dejo escrita el 2026-09-06:
dos rutas que no lo hacian tardaban cinco minutos.

QUE NO HACE
-----------
No interpreta. Devuelve lo que la sesion tiene, declarando lo que falta. La
interpretacion vive en `backend/analisis` y se expone en `api_analisis`.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from adapters import f1_25 as adaptador_f1_25
from backend import (anotador_vivo, catalogo_curvas, catalogo_reglajes,
                     catalogo_sesiones, db, f1_udp, procedencia_sesiones)

router = APIRouter()

#: A veinte muestras por segundo, dos consecutivas estan a cincuenta
#: milisegundos. Un salto de mas de dos segundos no es conduccion: es el
#: vehiculo detenido, la captura cortada, o dos cargas distintas de la misma
#: sesion pegadas una a la otra.
#:
#: Vive en el modulo, y no dentro de `vueltas`, porque de el salen tres cosas
#: que tienen que decir lo mismo: la duracion efectiva, el hueco mayor y los
#: limites de cada hueco. Escrito tres veces, tarde o temprano una de las tres
#: queda en otro numero.
HUECO_MAXIMO_S = 2.0

#: Nombre de la senal de distancia por fuente. Las que no figuran no tienen eje
#: espacial, y cada una por su motivo: ver `SIN_DISTANCIA_PORQUE`.
DISTANCIA_POR_FUENTE = {
    "f1_25_udp_simulation": "lap_distance",
}

#: POR QUE ESA FUENTE NO TIENE EJE DE DISTANCIA, UNA RAZON POR FUENTE.
#:
#: El mensaje era uno solo y explicaba el caso de OpenF1 ---los huecos de 83 m
#: entre muestras---, y se devolvia igual para cualquier fuente sin distancia.
#: Quien abria una captura del bus leia una explicacion sobre una fuente que no
#: estaba usando, y ademas equivocada: en el bus el problema no es que el
#: muestreo sea pobre, es que **la senal no existe**. Un motivo que no
#: corresponde es peor que no dar ninguno, porque manda a buscar donde no hay.
SIN_DISTANCIA_PORQUE = {
    "openf1_historical_replay": (
        "el muestreo de 3,7 Hz deja huecos de hasta 83 m entre muestras "
        "---medido el 2026-09-06--- y el eje espacial no es defendible"),
    "can_real_replay": (
        "el bus del vehiculo publica velocidad de rueda pero no odometro ni "
        "distancia de vuelta, de modo que no hay metro medido con el que "
        "ubicar una muestra en el circuito"),
}


def _sin_distancia(fuente: str) -> str:
    """El motivo por el que esta fuente no tiene eje de distancia."""
    return SIN_DISTANCIA_PORQUE.get(
        fuente, "esta fuente no declara distancia recorrida")

#: Posicion en el plano, por fuente.
POSICION_POR_FUENTE = {
    "f1_25_udp_simulation": ("world_position_x", "world_position_z"),
    "openf1_historical_replay": ("track_position_x", "track_position_y"),
}

def _fuente_de(session_id: str) -> str:
    """Deduce la fuente por el prefijo del identificador de sesion.

    Los identificadores llevan su origen: `f1_25:session:...`,
    `can:segmento:...`, y los de la fuente deportiva son la clave numerica.
    Deducirlo evita que quien consulta tenga que repetir un dato que ya esta
    en el identificador, y que pueda equivocarse al repetirlo.
    """
    if session_id.startswith("f1_25:"):
        return "f1_25_udp_simulation"
    if session_id.startswith("can:"):
        return "can_real_replay"
    return "openf1_historical_replay"


def _filas(cursor, consulta: str, parametros: tuple) -> list[tuple]:
    cursor.execute(consulta, parametros)
    return cursor.fetchall()


# --------------------------------------------------------------------------
# 11. Catalogo de sesiones: que hay guardado y como se llama
# --------------------------------------------------------------------------

@router.get("/sesiones")
def listar_sesiones(fuente: str | None = None, limite: int = 400) -> dict[str, Any]:
    """Sesiones persistidas, con lo que hace falta para elegir una.

    POR QUE HACIA FALTA. La base guardaba la procedencia tecnica de cada
    mensaje y **nada que identificara la sesion**: eran consultables pero no
    descubribles, de modo que una carrera con millones de filas no figuraba en
    ninguna lista.

    POR QUE SALE DE UN CATALOGO Y NO DE UNA CONSULTA. Derivarlo en cada
    peticion costaba **155 segundos** medidos el 2026-09-07 sobre los ochenta y
    siete millones de filas comprimidas. Lo que describe cambia al cargar una
    sesion, no al consultarla. Ver `backend/catalogo_sesiones.py`.
    """
    r = catalogo_sesiones.listar(fuente=fuente, limite=limite)

    # Se enriquece con lo que la sesion **es**, no solo con cuanto pesa. El
    # circuito y el tipo viven en los metadatos de captura, derivados del
    # paquete de sesion; sin esto, una clasificacion y una carrera se ven
    # iguales: dos identificadores con muchas filas.
    for sesion in r["sesiones"]:
        proc = procedencia_sesiones.de(sesion["session_id"])
        sesion["procedencia"] = proc
        sesion["tipo"] = proc.get("tipo_sesion_nombre") if proc else None
        sesion["familia_de_sesion"] = proc.get("familia_de_sesion") if proc else None
        sesion["circuito"] = proc.get("circuito") if proc else None
        # El instante que trae el catalogo es el de los datos, y en la fuente
        # del bus **es asignado**: el conjunto es anonimo, no trae fecha, y la
        # carga le pone una. Decir «guardada el 5 de septiembre» sobre una
        # fecha inventada seria afirmar algo que no ocurrio.
        sesion["instante_asignado"] = sesion["fuente"] in (
            "can_real_replay", "can_simulated")
    return r


@router.get("/sesiones/tipos")
def tipos_de_sesion() -> dict[str, Any]:
    """Cuantas sesiones hay de cada tipo y en que circuitos.

    Practica, clasificacion, sprint, carrera y contrarreloj persiguen cosas
    distintas, y agruparlas todas como «sesiones» borra esa diferencia.
    """
    return procedencia_sesiones.resumen()


@router.post("/sesiones/reconstruir-catalogo")
def reconstruir_catalogo() -> dict[str, Any]:
    """Vuelve a armar el catalogo. Es la operacion cara: corre por detras."""
    lanzada = catalogo_sesiones.pedir_reconstruccion()
    return {
        "lanzada": lanzada,
        "motivo": None if lanzada else "Ya habia una reconstruccion en curso.",
        "estado": catalogo_sesiones.estado(),
    }


# --------------------------------------------------------------------------
# 3. Vueltas de una sesion
# --------------------------------------------------------------------------

@router.get("/sesiones/{session_id}/procedencia")
def procedencia_de_sesion(session_id: str) -> dict[str, Any]:
    """Circuito, tipo de sesion y parrilla de una sesion, sin pasar por el catalogo.

    POR QUE NO ALCANZABA CON `/sesiones`. Esa lista sale de `sesiones_catalogo`,
    que se recuenta por detras y **no incluye una sesion que se esta capturando
    ahora**. Mientras se escucha, el tablero no la encuentra ahi y arma una
    entrada propia sin procedencia, de modo que llamaba «sesion sin procedencia
    declarada» a una captura cuyo circuito el flujo ya habia declarado, y solo
    le ponia el nombre al terminar.

    Esto la lee de los metadatos de captura, que el capturador escribe apenas el
    flujo se declara. No toca la base: es el mismo indice que enriquece el
    catalogo.
    """

    proc = procedencia_sesiones.de(session_id)
    # QUIEN ES CADA VEHICULO VIENE ACA MISMO, y no en otra consulta.
    #
    # El tablero la sacaba de `/adquisiciones`, que se pide al abrir una sesion
    # guardada y no mientras se escucha: durante la captura el vehiculo se
    # llamaba «Vehiculo 0» aunque el paquete de participantes ya hubiera dicho
    # el nombre. Es el mismo indice y el mismo archivo que la procedencia, de
    # modo que separarlas seria leer dos veces lo mismo.
    #
    # `parrilla_de` **se abstiene** cuando la sesion tiene varias capturas que
    # declaran participantes distintos: ahi no hay una parrilla «de la sesion» y
    # hace falta saber cual adquisicion se esta mirando.
    declarada = procedencia_sesiones.parrilla_de(session_id)
    parrilla = {"disponible": False,
                "motivo": ("ninguna captura de esta sesion declara una parrilla, "
                           "o hay mas de una y declaran participantes distintos")}
    if declarada and declarada.get("vehiculos"):
        # Quien conduce sale del flujo, no de que vehiculo tenga mas senales.
        with db.obtener_conexion() as _c, _c.cursor() as _cur:
            _propio = _vehiculo_propio(_cur, _fuente_de(session_id), session_id)
        parrilla = {
            "disponible": True,
            "vehiculos": _vehiculos_nombrados(session_id, declarada,
                                              propio=_propio),
            "vehiculos_en_carrera": declarada.get("vehiculos_en_carrera"),
            "origen": declarada.get("origen"),
            "captura": (declarada.get("captura") or {}).get("archivo"),
        }
    return {
        "session_id": session_id,
        "procedencia": proc,
        "parrilla": parrilla,
        # Que no haya no es un fallo: una captura que todavia no vio un paquete
        # de sesion con tipo declarado no tiene procedencia que dar.
        "motivo_ausencia": None if proc else (
            "Todavia no hay metadatos de captura para esta sesion: el flujo no "
            "declaro su tipo de sesion, o la captura no la hizo esta maquina."),
    }


@router.get("/sesiones/{session_id}/vueltas")
def listar_vueltas(
        session_id: str,
        vehiculo: Annotated[str | None, Query(
            description="Identificador del vehiculo; por omision, el mas muestreado")] = None,
        adquisicion: Annotated[str | None, Query(
            description="Que adquisicion mirar: `original`, un `replay_run_id`, "
                        "o `todas`. Sin elegir se devuelven todas juntas y la "
                        "respuesta lo declara")] = None,
        fase: Annotated[int | None, Query(
            ge=1, description="Tramo entre reinicios del reloj del juego, "
                              "numerado como en /adquisiciones")] = None,
        ) -> dict[str, Any]:
    """Vueltas de **un** vehiculo, con su largo y su rango de distancia.

    Devolver el rango de distancia y no solo el numero es lo que permite al
    tablero acotar una consulta de series sin adivinar: pide de tal metro a
    tal metro de tal vuelta.

    LAS VUELTAS SON DE UN VEHICULO, NO DE LA SESION.
    -----------------------------------------------
    Antes esta consulta agrupaba por numero de vuelta **sobre todos los
    vehiculos a la vez**. En una sesion de un solo coche daba bien; en una de
    veinte, «vuelta 1» iba desde que el primero cruzo la linea hasta que la
    cruzo el ultimo, y una vuelta de hora y media aparecia como si alguien la
    hubiera rodado. Medido sobre una sesion de veinte vehiculos: cuatro vueltas
    sumando sesenta y cinco minutos, que es la sesion entera.

    Eso rompia todo lo que cuelga de aca: la duracion de la sesion, donde
    empieza cada vuelta y, por lo tanto, la posicion del cabezal.

    Por omision se toman las del vehiculo mas muestreado, que es el propio: de
    los rivales la fuente publica cronometraje y no telemetria, de modo que el
    que tiene mas filas es siempre el que se conduce.
    """
    fuente = _fuente_de(session_id)
    senal_distancia = DISTANCIA_POR_FUENTE.get(fuente)
    if not senal_distancia:
        return {
            "session_id": session_id,
            "fuente": fuente,
            "vueltas": [],
            "motivo": ("Esta fuente no tiene eje de distancia: %s. Sin metro medido "
                       "no hay vueltas que delimitar." % _sin_distancia(fuente)),
        }

    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        # El alcance se resuelve una vez y acota todo lo que sigue: elegir el
        # vehiculo mas muestreado sobre las tres adquisiciones juntas daria el
        # de las pruebas de parrilla, que aportan una vuelta.
        v0, v1 = (_ventana_de_alcance(cursor, fuente, session_id, adquisicion)
                  or (None, None))
        f0, f1 = _limites_de_fase(cursor, fuente, session_id, adquisicion, fase)
        tramo, tramo_par = _clausula_de_tramo(f0, f1)
        if not vehiculo:
            # PRIMERO SE PREGUNTA QUIEN CONDUCE.
            #
            # Debajo se elige el vehiculo con mas filas, y el razonamiento que
            # lo justificaba estaba escrito y era correcto **mientras se
            # capturaba un solo coche**: de los rivales la fuente publicaba
            # cronometraje y no telemetria, de modo que el mas muestreado era
            # siempre el propio.
            #
            # Desde que se puede elegir a quien escuchar, los rivales traen
            # exactamente las mismas senales y con la misma frecuencia: el mas
            # muestreado volvio a ser cualquiera. El 2026-09-10 esta consulta
            # devolvio a Russell en una sesion corrida con Hamilton, y el
            # tablero la tomaba como autoritativa.
            vehiculo = _vehiculo_propio(cursor, fuente, session_id)
        if not vehiculo:
            # El mas muestreado **de la fase pedida**: en la formacion de Spa
            # rueda un vehiculo y en las pruebas de parrilla, veinte. Queda de
            # respaldo para las capturas que no declaran quien conduce.
            elegido = _filas(cursor, """
                SELECT vehicle_id, count(*)
                  FROM telemetry_messages
                 WHERE source_type = %s AND session_id = %s AND signal_name = %s
                   AND (%s::timestamptz IS NULL OR timestamp BETWEEN %s AND %s)""" +
                tramo + """
                 GROUP BY vehicle_id
                 ORDER BY 2 DESC
                 LIMIT 1
            """, tuple([fuente, session_id, senal_distancia, v0, v0, v1] + tramo_par))
            vehiculo = elegido[0][0] if elegido else None
        if not vehiculo:
            return {"session_id": session_id, "fuente": fuente, "vueltas": [],
                    "motivo": "Ningun vehiculo de esta sesion declara distancia recorrida."}

        filas = _filas(cursor, """
            WITH p AS (
                SELECT timestamp,
                       max(value_numeric) FILTER (WHERE signal_name = 'lap_number')   AS vuelta,
                       max(value_numeric) FILTER (WHERE signal_name = %s)             AS distancia,
                       max(value_numeric) FILTER (WHERE signal_name = 'speed')        AS velocidad,
                       max(value_numeric) FILTER (WHERE signal_name = 'lap_invalid')  AS invalida
                  FROM telemetry_messages
                 WHERE source_type = %s AND session_id = %s AND vehicle_id = %s
                   AND signal_name IN ('lap_number', %s, 'speed', 'lap_invalid')
                   AND (%s::timestamptz IS NULL OR timestamp BETWEEN %s AND %s)""" +
                tramo + """
                 GROUP BY timestamp)
            , q AS (
                SELECT vuelta, timestamp, distancia, velocidad, invalida,
                       timestamp - lag(timestamp)
                           OVER (PARTITION BY vuelta ORDER BY timestamp) AS salto
                  FROM p
                 WHERE vuelta IS NOT NULL AND distancia IS NOT NULL)
            SELECT vuelta::int,
                   count(*)                       AS muestras,
                   min(distancia)                 AS desde_m,
                   max(distancia)                 AS hasta_m,
                   min(timestamp)                 AS inicio,
                   max(timestamp)                 AS fin,
                   min(velocidad)                 AS v_min,
                   max(velocidad)                 AS v_max,
                   max(invalida)                  AS invalida,
                   -- Suma de los intervalos que son de conduccion continua.
                   extract(epoch FROM sum(salto)
                           FILTER (WHERE salto < interval '{hueco}')) AS efectiva,
                   extract(epoch FROM max(salto))                       AS hueco,
                   -- DONDE estan los huecos, no solo cuanto dura el mayor.
                   --
                   -- `hueco_mayor_s` dice si la vuelta se corto; no dice en que
                   -- momento. Quien reproduce la vuelta necesita lo segundo: sin
                   -- los limites no puede saltarse el hueco, y deducirlos de la
                   -- serie que recibe ---que llega submuestreada--- da un umbral
                   -- distinto segun cuantos puntos haya pedido. Aca se calculan
                   -- sobre la resolucion completa, que es la unica que los tiene.
                   jsonb_agg(jsonb_build_array(
                                 extract(epoch FROM (timestamp - salto)),
                                 extract(epoch FROM timestamp))
                             ORDER BY timestamp)
                       FILTER (WHERE salto >= interval '{hueco}')       AS huecos
              FROM q
             GROUP BY vuelta
             ORDER BY vuelta
        """.replace("{hueco}", "%g seconds" % HUECO_MAXIMO_S),
            tuple([senal_distancia, fuente, session_id, vehiculo, senal_distancia,
                    v0, v0, v1] + tramo_par))

    vueltas = []
    for f in filas:
        bruta = (f[5] - f[4]).total_seconds() if f[4] and f[5] else None
        # Se leen con cuidado: una fila mas corta no debe tumbar la respuesta.
        efectiva = float(f[9]) if len(f) > 9 and f[9] is not None else None
        hueco = float(f[10]) if len(f) > 10 and f[10] is not None else None
        # La duracion que sirve es la efectiva: la que se estuvo rodando.
        duracion = efectiva if efectiva is not None else bruta
        vueltas.append({
            "numero": f[0],
            "muestras": f[1],
            "desde_m": round(f[2], 1) if f[2] is not None else None,
            "hasta_m": round(f[3], 1) if f[3] is not None else None,
            "largo_m": round(f[3] - f[2], 1) if f[2] is not None and f[3] is not None else None,
            "duracion_s": round(duracion, 3) if duracion is not None else None,
            # QUE SIGNIFICA CADA UNA.
            # `duracion_s` es lo que se estuvo rodando, sumando solo los
            # intervalos de conduccion continua. `duracion_bruta_s` es lo que
            # va del primer al ultimo instante, que incluye lo que haya pasado
            # en el medio. Cuando difieren, el vehiculo estuvo detenido, la
            # captura se corto, o hay dos cargas de la misma sesion pegadas.
            # Se declaran las dos porque la diferencia **es** el hallazgo.
            "duracion_bruta_s": round(bruta, 3) if bruta is not None else None,
            "hueco_mayor_s": round(hueco, 3) if hueco is not None else None,
            "continua": bool(hueco is not None and hueco <= HUECO_MAXIMO_S),
            # DONDE SE CORTO, NO SOLO CUANTO.
            #
            # Los mismos intervalos que `duracion_s` descarta, dichos con sus
            # dos extremos. Quien reproduce la vuelta los necesita para saltar
            # el hueco en vez de recorrerlo, y para no unir con una recta dos
            # muestras que no se tocan. Deducirlos de la serie submuestreada da
            # un umbral distinto en cada resolucion; estos salen de la
            # resolucion completa. Una vuelta continua devuelve la lista vacia,
            # que es una afirmacion: no hubo cortes.
            "huecos": _huecos_legibles(f[11] if len(f) > 11 else None),
            # Los dos instantes ya se calculaban para la duracion y no se
            # devolvian. Sin ellos, un tablero que recorre la sesion no puede
            # preguntar «como estaba el clima aca» ni ubicar a los rivales en
            # el tiempo: solo sabe cuanto duro, no cuando fue.
            "desde_utc": f[4].isoformat() if f[4] else None,
            "hasta_utc": f[5].isoformat() if f[5] else None,
            "velocidad_minima_kmh": round(f[6], 1) if f[6] is not None else None,
            "velocidad_maxima_kmh": round(f[7], 1) if f[7] is not None else None,
            "invalida": bool(f[8]) if f[8] is not None else None,
            # Una vuelta que no arranca en cero es un tramo, no una vuelta: se
            # declara para que el tablero no la ofrezca como comparable.
            "completa": bool(f[2] is not None and f[2] < 60 and f[3] and f[3] > 1000),
        })
    return {"session_id": session_id, "fuente": fuente,
            "vehiculo": vehiculo, "vueltas": vueltas}


def _huecos_legibles(crudos: Any) -> list[dict]:
    """Los limites de cada hueco de captura, en ISO y en segundos.

    Entran como pares de epoch ---es lo que `jsonb_build_array` sabe agregar sin
    depender de la zona horaria de la sesion--- y salen como los declara el
    resto de la respuesta: `desde_utc`, `hasta_utc`. Se devuelve lista vacia y
    no `None` cuando la vuelta no tuvo cortes, porque «no hubo» es una
    afirmacion y `None` seria «no se sabe».
    """
    if not crudos:
        return []
    salida = []
    for par in crudos:
        try:
            a, b = float(par[0]), float(par[1])
        except (TypeError, ValueError, IndexError):
            continue
        if not (b > a):
            continue
        salida.append({
            "desde_utc": datetime.fromtimestamp(a, tz=timezone.utc).isoformat(),
            "hasta_utc": datetime.fromtimestamp(b, tz=timezone.utc).isoformat(),
            "duracion_s": round(b - a, 3),
        })
    return salida


def _explicar_descensos(fuente: str, session_id: str, vehiculos: dict,
                        sellos: dict) -> list[dict]:
    """Que pasa donde la distancia de vuelta baja, dicho con evidencia.

    EL CASO QUE ESTO EXPLICA, MEDIDO EN SPA.

    La vuelta 22 de la carrera original termina en `... 6.948,5 · 6.978,0 · 2,1`
    metros. No es una muestra de otra fase ---sigue estando despues de acotar
    por fase--- y no es un fallo del tablero. Son tres cuadros seguidos:

    | cuadro | vuelta | distancia de vuelta | distancia de sesion |
    |---|---:|---:|---:|
    | 64.492 | 22 | 7.005,995 m | 154.162,531 m |
    | 64.493 | 22 |     1,229 m | 154.165,219 m |
    | 64.494 | 22 |     2,135 m | 154.166,125 m |

    La distancia de vuelta se reinicia y **la de sesion sigue creciendo**: el
    vehiculo cruzo la meta. El numero de vuelta todavia dice 22 porque el juego
    lo publica asi; de eso no se deduce ninguna clasificacion deportiva.

    POR QUE NO SE CORRIGE. Se podria recortar el descenso, o forzar que la serie
    crezca, y el grafico quedaria prolijo. Pero entonces un descenso que **si**
    fuera un error ---una muestra de otra fase, una fila mal atribuida--- se
    veria igual de prolijo. Se declara cada uno con su evidencia y se deja que
    quien mire sepa cual es cual.
    """

    sospechas = []
    for vehiculo, serie in vehiculos.items():
        crudos = sellos.get(vehiculo) or []
        medidos = [(i, v) for i, v in enumerate(serie) if v is not None]
        for (i, a), (j, b) in zip(medidos, medidos[1:]):
            if b < a and i < len(crudos) and j < len(crudos):
                sospechas.append((vehiculo, i, j, a, b, crudos[i], crudos[j]))
    if not sospechas:
        return []

    # Una sola consulta para los pocos instantes involucrados: en una vuelta
    # normal no hay ninguno, y en la ultima hay uno.
    instantes = sorted({t for s in sospechas for t in (s[5], s[6])})
    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        cursor.execute("""
            SELECT vehicle_id, timestamp, value_numeric
              FROM telemetry_messages
             WHERE source_type = %s AND session_id = %s
               AND signal_name = 'session_distance'
               AND timestamp = ANY(%s)
        """, (fuente, session_id, instantes))
        acumulada = {(v, t): d for v, t, d in cursor.fetchall()}

    salida = []
    for vehiculo, i, j, a, b, ta, tb in sospechas:
        da = acumulada.get((vehiculo, ta))
        db_ = acumulada.get((vehiculo, tb))
        crece = (da is not None and db_ is not None and db_ > da)
        salida.append({
            "vehiculo": vehiculo,
            "indice_desde": i,
            "indice_hasta": j,
            "distancia_de_vuelta_m": [round(a, 1), round(b, 1)],
            "distancia_de_sesion_m": ([round(da, 1), round(db_, 1)]
                                      if da is not None and db_ is not None else None),
            "session_distance_crece": crece,
            "motivo": ("la vuelta se cierra: la distancia de vuelta se reinicia "
                       "y la de sesion sigue creciendo" if crece else
                       "sin explicar: la distancia de vuelta baja y la de sesion "
                       "no lo respalda"),
        })
    return salida


@router.get("/sesiones/{session_id}/posiciones")
def posiciones_en_pista(
        session_id: str,
        vuelta: int,
        puntos: Annotated[int, Query(ge=20, le=400)] = 160,
        adquisicion: Annotated[str | None, Query(
            description="Que adquisicion mirar: `original`, un `replay_run_id`, "
                        "o `todas`. Sin elegir se devuelven todas juntas y la "
                        "respuesta lo declara")] = None,
        fase: Annotated[int | None, Query(
            ge=1, description="Tramo entre reinicios del reloj del juego, "
                              "numerado como en /adquisiciones")] = None,
        ) -> dict[str, Any]:
    """Donde esta cada vehiculo de la sesion a lo largo de una vuelta.

    POR QUE NO ALCANZA CON `/series`.
    ---------------------------------
    Las series van contra la distancia recorrida **de cada vehiculo**, y esa es
    la eleccion correcta para comparar dos vueltas: el mismo metro es el mismo
    lugar del circuito. Pero para ver un adelantamiento hace falta lo
    contrario: **un eje comun de tiempo**, y sobre el, donde esta cada uno. Dos
    vehiculos en el mismo metro no estan juntos si pasaron por ahi con veinte
    segundos de diferencia.

    Este endpoint reparte la vuelta en `puntos` intervalos de tiempo iguales y
    devuelve, para cada vehiculo, su distancia recorrida en cada intervalo. Con
    eso el tablero coloca a los veinte sobre el trazado y quien mira ve quien
    pasa a quien.

    QUE NO ENTREGA. Solo la posicion en la vuelta, que es lo que la fuente
    publica de todos. La telemetria privada ---frenos, combustible, puesta a
    punto--- sigue siendo del vehiculo propio: la fuente la entrega de todos y
    mostrarla enseniaria un procedimiento que en un vehiculo real no se puede
    ejecutar.
    """
    fuente = _fuente_de(session_id)
    senal_distancia = DISTANCIA_POR_FUENTE.get(fuente)
    if not senal_distancia:
        raise HTTPException(
            status_code=422,
            detail=("La fuente %s no tiene eje de distancia: %s. No se puede "
                    "ubicar a los vehiculos sobre la vuelta, y no es un fallo "
                    "que se pueda reintentar." % (fuente, _sin_distancia(fuente))))

    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        v0, v1 = (_ventana_de_alcance(cursor, fuente, session_id, adquisicion)
                  or (None, None))
        # LA VENTANA DE LA VUELTA SE BUSCA DENTRO DEL ALCANCE.
        #
        # Sin esto, `min/max(timestamp)` de la vuelta 1 de Spa abarca los tres
        # dias que separan la captura original de las corridas de prueba, y los
        # doscientos cubos quedan de veintidos minutos de reloj cada uno: el
        # cabezal recorre 283 s y cae siempre en el mismo cubo, de modo que el
        # coche no se mueve.
        f0, f1 = _limites_de_fase(cursor, fuente, session_id, adquisicion, fase)
        tramo, tramo_par = _clausula_de_tramo(f0, f1)
        ventana = _filas(cursor, """
            SELECT min(timestamp), max(timestamp)
              FROM telemetry_messages
             WHERE source_type = %s AND session_id = %s
               AND signal_name = 'lap_number' AND value_numeric = %s
               AND (%s::timestamptz IS NULL OR timestamp BETWEEN %s AND %s)""" +
            tramo + """
        """, tuple([fuente, session_id, float(vuelta), v0, v0, v1] + tramo_par))
        if not ventana or ventana[0][0] is None:
            return {"session_id": session_id, "vuelta": vuelta, "vehiculos": {},
                    "motivo": "No hay muestras de esa vuelta."}
        t0, t1 = ventana[0]

        # LA FASE TAMBIEN ACOTA ESTA CONSULTA, QUE ES LA QUE DEVUELVE EL DATO.
        #
        # Acotarla solo al calcular la ventana no alcanza: la formacion y la
        # carrera se solapan en UTC a proposito, porque el reloj del juego se
        # reinicia en la largada y el `timestamp` derivado retrocede con el. Sin
        # esta linea, en la vuelta 2 de Spa entraban 34 muestras de formacion y
        # la distancia iba de 0,2 a 5.676,2 m entre dos cubos seguidos.
        #
        # Se comprueba, ademas, que la fila elegida por cubo sea la primera en
        # el tiempo: `DISTINCT ON` con `ORDER BY ... timestamp` ya lo hacia, y
        # ahora ademas se devuelve **cual instante es**, para no tener que
        # suponerlo repartido en partes iguales.
        filas = _filas(cursor, """
            WITH m AS (
                SELECT vehicle_id, timestamp, value_numeric AS d,
                       width_bucket(extract(epoch FROM timestamp),
                                    extract(epoch FROM %s::timestamptz),
                                    extract(epoch FROM %s::timestamptz), %s) AS cubo
                  FROM telemetry_messages
                 WHERE source_type = %s AND session_id = %s AND signal_name = %s
                   AND timestamp BETWEEN %s AND %s""" + tramo + """)
            SELECT DISTINCT ON (vehicle_id, cubo) vehicle_id, cubo, d, timestamp
              FROM m
             WHERE d IS NOT NULL
             ORDER BY vehicle_id, cubo, timestamp
        """, tuple([t0, t1, puntos, fuente, session_id, senal_distancia, t0, t1]
                   + tramo_par))

    # EL CONTRATO TEMPORAL, DICHO EN VEZ DE SUPUESTO.
    #
    # `width_bucket` devuelve 1..`puntos` dentro del rango y `puntos`+1 para el
    # valor que cae justo en el extremo superior. El arreglo se indexaba con esa
    # cifra tal cual, de modo que **el indice 0 nunca se usaba**: quedaba un
    # hueco al principio que no era una muestra que faltara sino un artefacto
    # del formato, y quien lo leia como una rejilla pareja arrancaba corrido.
    #
    # Ahora el indice `k` es el intervalo `k`, contado desde cero, y hay
    # `puntos`+1 de ellos: los `puntos` intervalos mas el instante final exacto.
    #
    # Y sobre todo: se devuelve **cuando** se midio cada uno. La API conservaba
    # la primera muestra de cada intervalo y no decia su instante, asi que el
    # unico camino que quedaba era suponerlas equiespaciadas. No lo estan: entre
    # una y la siguiente hay lo que haya, y con `instantes_ms` se puede colocar
    # cada una donde ocurrio en vez de repartirlas en partes iguales.
    largo = puntos + 1
    base = t0.timestamp()
    vehiculos: dict[str, list] = {}
    instantes: dict[str, list] = {}
    sellos: dict[str, list] = {}
    for vehiculo, cubo, d, cuando in filas:
        i = cubo - 1
        if not (0 <= i < largo):
            continue
        serie = vehiculos.setdefault(vehiculo, [None] * largo)
        marcas = instantes.setdefault(vehiculo, [None] * largo)
        crudos = sellos.setdefault(vehiculo, [None] * largo)
        serie[i] = round(d, 1)
        marcas[i] = round((cuando.timestamp() - base) * 1000.0, 1)
        crudos[i] = cuando

    descensos = _explicar_descensos(fuente, session_id, vehiculos, sellos)

    return {
        "session_id": session_id,
        "fuente": fuente,
        "vuelta": vuelta,
        "desde_utc": t0.isoformat(),
        "hasta_utc": t1.isoformat(),
        "puntos": puntos,
        "senal": senal_distancia,
        "vehiculos": vehiculos,
        "instantes_ms": instantes,
        "descensos": descensos,
        "sobre_los_descensos": (
            "una distancia de vuelta que baja no es siempre un error. Cada uno "
            "se contrasta con `session_distance`, que no se reinicia: si esa "
            "sigue creciendo entre las dos muestras, la vuelta se cerro ahi. Se "
            "declaran y no se corrigen: forzar que la distancia crezca "
            "esconderia los que si son un error"),
        "intervalo_ms": round((t1 - t0).total_seconds() * 1000.0 / puntos, 3),
        "eje": ("tiempo repartido en intervalos iguales dentro de la vuelta; el "
                "indice k es el intervalo k contado desde cero, y son puntos+1 "
                "---los intervalos mas el instante final"),
        "instantes": ("milisegundos desde `desde_utc` de la muestra elegida en "
                      "cada intervalo, que es la primera del intervalo. Sin esto "
                      "habria que suponerlas equiespaciadas, y no lo estan"),
    }


# --------------------------------------------------------------------------
# 1 y 4. Series contra distancia, para uno o varios vehiculos
# --------------------------------------------------------------------------

def _reducir(filas: list, puntos: int,
             plegables: tuple[int, int] | None = None) -> tuple[list, bool]:
    """Deja como mucho `puntos` filas, conservando los dos extremos.

    `max(1, len // puntos)` no acota. Con 599 filas y `puntos=300` la division
    entera da 1, el paso queda en 1 y se devuelven las 599: el limite declarado
    dejaba de cumplirse justo en el caso en que empieza a importar, y encima
    `submuestreado` decia que no se habia reducido nada. Con 2*puntos-1 filas
    ---el peor caso--- se devolvia casi el doble de lo pedido.

    Se toma una de cada N con N redondeado hacia arriba, y se garantiza que la
    ultima fila este: sin eso la serie termina antes que el dato y el ultimo
    tramo de la vuelta, que es la frenada de meta, no se dibuja.

    LO QUE ESTO PIERDE, Y HAY QUE DECIRLO. Tomar una de cada N puede saltear un
    pico que ocurre entre dos muestras elegidas. La respuesta declara
    `submuestreado` y `muestras_originales` para que el grafico pueda decir que
    lo que muestra esta reducido, y la resolucion completa se obtiene acotando
    la distancia o pidiendo mas puntos.

    No se elige por valor ---quedarse con el maximo de cada tramo--- porque cada
    fila trae varias señales sobre una misma distancia: el extremo de una no es
    el de las otras, y elegir la fila por una de ellas falsearia a todas las
    demas.

    UNA FILA POR INSTANTE EXACTO ES UNA FILA POR SEÑAL, Y ENTONCES SALTEAR
    FILAS ES BORRAR CANALES.

    Lo de arriba supone que cada fila trae varias señales. En el simulador es
    cierto: un paquete de movimiento publica todas sus magnitudes con el mismo
    sello. En un bus vehicular no: cada trama lleva lo suyo y llega cuando le
    toca, de modo que agrupando por instante exacto **cada fila tiene una sola
    señal** y las demas en nulo.

    Sobre eso, `filas[::paso]` no adelgaza: elimina. Medido sobre `sample_28`,
    6.158 filas de las cuales 3.079 traen `speed`, y estan **exactamente en los
    indices pares**, porque el bus las intercala con regularidad. Con `paso`
    par sobreviven todas y se borran las de al lado; con `paso` impar sobrevive
    la mitad; y pidiendo las trece señales del bus el patron cambia y `speed`
    desaparece entera: cero muestras de tres mil. El tablero mostraba «sin dato
    en esta vuelta» sobre una sesion completa, y como el eje temporal se apoya
    en esa señal, los otros doce graficos se quedaban sin ventana y tampoco
    dibujaban.

    `plegables` dice que columnas son señales. Cuando se da, el tramo no se
    saltea: se **pliega**. Las `paso` filas contiguas se funden en una y cada
    columna se queda con su primera muestra del tramo, de modo que ninguna señal
    puede desaparecer por como el bus intercala sus tramas. El instante de la
    fila es el de la primera del tramo; una muestra plegada puede quedar
    atribuida hasta el ancho del tramo antes de cuando se midio, y esa es la
    aproximacion que este submuestreo declara con `submuestreado`.
    """

    total = len(filas)
    if total <= puntos:
        return filas, False
    paso = -(-total // puntos)              # division hacia arriba
    if plegables is not None:
        desde, hasta = plegables
        recorte = []
        for i in range(0, total, paso):
            tramo = filas[i:i + paso]
            fundida = list(tramo[0])
            for fila in tramo[1:]:
                for c in range(desde, hasta):
                    if fundida[c] is None and fila[c] is not None:
                        fundida[c] = fila[c]
            recorte.append(tuple(fundida))
        # El ultimo tramo contiene la ultima fila: no hace falta reponerla.
        return recorte, True
    recorte = list(filas[::paso])
    if recorte[-1] is not filas[-1]:
        if len(recorte) >= puntos:
            recorte[-1] = filas[-1]
        else:
            recorte.append(filas[-1])
    return recorte, True


# ---------------------------------------------------------------------------
# ADQUISICION Y FASE: TRES COSAS QUE NO SON LA MISMA
# ---------------------------------------------------------------------------
#
# `session_id` deriva del identificador que el juego le da a la sesion. Es
# estable, y por eso **volver a capturar la misma sesion produce filas con el
# mismo identificador**. Lo que se guarda bajo un `session_id` puede ser, en
# consecuencia, mas de una adquisicion.
#
# En `f1_25:session:3731090176871608020` conviven tres: la original del 5 de
# septiembre y dos corridas de prueba del 8, documentadas en
# `docs/diagnostico_spa_carrera_2.md`. Agrupadas como una sola carrera, la
# vuelta 1 abarca tres dias y `posiciones_en_pista` reparte 260.454 s en 200
# cubos ---1.302 s cada uno--- mientras el reproductor recorre 283 s.
#
# Son tres conceptos distintos:
#
#   * **sesion del juego**: el identificador, que es lo que hay hoy;
#   * **adquisicion**: cada vez que se capturo o se reprodujo esa sesion;
#   * **fase**: dentro de una adquisicion, cada tramo entre reinicios del reloj
#     del juego. En el original de Spa son tres ---formacion, espera de luces y
#     carrera--- y el reloj vuelve a cero en cada uno.
#
# Y dos relojes que no se pueden mezclar:
#
#   * el **monotonico de captura** (`desplazamiento_captura_us`), que no
#     retrocede nunca y es el unico que ordena de verdad;
#   * el **del juego** (`session_time_s`), que se detiene y se reinicia.
#
# El `timestamp` de la tabla es el segundo sumado a una base UTC, de modo que
# **retrocede** en cada reinicio: por eso la ventana UTC de la vuelta 2 se
# solapa con la formacion, aunque en orden de captura no se solapen.
#
# COMO SE IDENTIFICA UNA ADQUISICION, Y QUE NO SE PUEDE SUPONER.
#
# Con `replay_run_id`: la columna que el reproductor escribe. En esta sesion la
# original no lo declara y las dos pruebas si. **Eso no autoriza a leer un nulo
# como «original» en cualquier sesion**: la columna se agrego despues de que
# existieran capturas, y una sesion vieja tendra nulo en todas sus filas sin que
# eso signifique nada.
#
# Se probo `metadata.extra.origen_adquisicion` como discriminador alternativo y
# **no sirve**: las tres adquisiciones de Spa declaran `consola_en_vivo`, porque
# el reproductor reemite la carga original con sus metadatos. Queda dicho para
# que nadie lo vuelva a intentar.
#
# Por eso la respuesta declara `mezclada` y `como_se_identifica`, y cuando hay
# mas de una adquisicion el cliente **tiene que elegir**: contestar una
# cualquiera seria inventar cual.

ORIGEN_SIN_CORRIDA = "original"

#: RESOLVER EL ALCANCE UNA VEZ POR APERTURA, NO SEIS.
#:
#: Los bordes de una adquisicion y de sus fases son los mismos para las seis
#: rutas que los piden, y sacarlos cuesta recorrer la sesion: la ventana se mide
#: sobre `min/max(timestamp)` filtrando por `replay_run_id`, que **no** es
#: columna de segmentacion, de modo que hay que descomprimir para mirarla.
#:
#: Medido sobre Spa con la cache de PostgreSQL fria, abriendo el tablero en
#: `original`, fase 3: seis consultas concurrentes tardaron entre 22,8 y 28,8 s
#: cada una y el primer trazo llego a los 62,2 s. En caliente y de a una,
#: `/vueltas` pasa de 1,3 s sin alcance a 3,9 s con adquisicion y 5,0 s con
#: fase: la diferencia son estas resoluciones, repetidas en cada ruta.
#:
#: POR QUE CADUCA. Una sesion guardada no cambia, pero una que **se esta
#: capturando** crece: su ultimo instante se corre. Un minuto de vigencia deja
#: que una apertura entera ---que dura segundos--- comparta la resolucion, y que
#: una sesion viva la vuelva a medir enseguida.
_ALCANCE_CACHE: OrderedDict = OrderedDict()
ALCANCES_EN_CACHE = 64
VIGENCIA_DEL_ALCANCE_S = 60.0

#: UN CERROJO POR CLAVE, PORQUE LA APERTURA ES SIMULTANEA.
#:
#: Guardar el resultado no alcanza. Al abrir el tablero las seis rutas salen
#: **a la vez**: las seis fallan la cache al mismo tiempo y las seis resuelven
#: el mismo alcance en paralelo, contra la misma base. Medido con el proceso
#: recien arrancado y las seis concurrentes, `/vueltas` y `/contexto` pasaron de
#: 3,1 y 2,6 s ---de a una, con la cache puesta--- a agotar los 30 s de espera
#: del navegador, y `/avisos`, que sola tarda 0,01 s, tardo 23,4.
#:
#: Con el cerrojo la primera resuelve y las demas esperan a que termine, que es
#: mas rapido que resolverlo cada una: es el mismo trabajo, hecho una vez.
_ALCANCE_CERROJOS: dict = {}
_CERROJO_DE_CERROJOS = threading.Lock()


def _cerrojo_de(clave: tuple) -> threading.Lock:
    with _CERROJO_DE_CERROJOS:
        cerrojo = _ALCANCE_CERROJOS.get(clave)
        if cerrojo is None:
            cerrojo = _ALCANCE_CERROJOS[clave] = threading.Lock()
        return cerrojo


def _vigente(clave: tuple):
    """Lo guardado, si todavia sirve. `None` si no hay o si caduco."""

    guardado = _ALCANCE_CACHE.get(clave)
    if guardado is None or time.monotonic() - guardado[0] >= VIGENCIA_DEL_ALCANCE_S:
        return None
    _ALCANCE_CACHE.move_to_end(clave)
    return guardado


def _memorizado(clave: tuple, calcular):
    """Lo que `calcular` devuelva, reutilizado durante un minuto.

    Se mira dos veces: antes de pedir el cerrojo, para no serializar lo que ya
    esta resuelto, y despues de obtenerlo, porque mientras se esperaba pudo
    resolverlo otro.
    """

    guardado = _vigente(clave)
    if guardado is not None:
        return guardado[1]
    with _cerrojo_de(clave):
        guardado = _vigente(clave)
        if guardado is not None:
            return guardado[1]
        valor = calcular()
        _ALCANCE_CACHE[clave] = (time.monotonic(), valor)
        _ALCANCE_CACHE.move_to_end(clave)
        while len(_ALCANCE_CACHE) > ALCANCES_EN_CACHE:
            _ALCANCE_CACHE.popitem(last=False)
        return valor

def _limites_de_fase(cursor, fuente: str, session_id: str,
                     adquisicion: str | None,
                     fase: int | None) -> tuple[int | None, int | None]:
    """Los bordes de una fase, en reloj monotonico de captura.

    En UTC no se pueden expresar: el reloj del juego se reinicia en la largada y
    el `timestamp` derivado retrocede con el, de modo que la formacion y la
    carrera **se solapan en UTC a proposito**. El reloj de captura no retrocede
    nunca y es el unico que las separa.
    """

    if fase is None:
        return (None, None)
    fases = _fases_de(cursor, fuente, session_id, adquisicion)
    elegida = next((f for f in fases if f["orden"] == fase), None)
    if elegida is None:
        raise HTTPException(status_code=422, detail={
            "motivo": "esa fase no existe en la adquisicion elegida",
            "adquisicion": adquisicion or "todas",
            "fases_disponibles": [f["orden"] for f in fases]})
    return (elegida["limite_desde_us"], elegida["limite_hasta_us"])


def _ventana_de_alcance(cursor, fuente: str, session_id: str,
                        adquisicion: str | None,
                        fase: int | None = None) -> tuple[str, str] | None:
    """El tramo de tiempo que ocupa lo pedido, o `None` si es todo.

    POR QUE UNA VENTANA Y NO UNA CONDICION POR CONSULTA.

    Las seis rutas que hay que acotar arman su SQL de seis formas distintas, y
    meterle a cada una una condicion con sus parametros en el sitio correcto es
    seis oportunidades de equivocarse en silencio. Todas, en cambio, ya filtran
    por `timestamp`, que ademas es la dimension por la que la tabla esta
    particionada: acotar ahi es una linea igual en todas y encima es lo barato.

    La ventana se **deriva** del filtro exacto ---`replay_run_id`--- de modo que
    la identificacion no depende de que las adquisiciones esten en dias
    distintos. Lo unico que se supone es que una adquisicion ocupa un tramo
    continuo de reloj, que es lo que significa haberla capturado.

    LAS FASES NO. Dentro de una adquisicion el reloj del juego se reinicia y el
    `timestamp` derivado retrocede: las fases **se solapan en UTC a proposito**.
    Por eso la fase se acota por el reloj monotonico de captura y se resuelve
    aparte, en las rutas donde tiene sentido.
    """

    if not adquisicion or adquisicion == "todas":
        return None

    # El reparto se memoriza entero, no por adquisicion: es una sola consulta
    # que resuelve las tres, y pedirla una vez por clave seria pagarla tres.
    reparto = _memorizado(("reparto", fuente, session_id),
                          lambda: _repartir_el_reloj(cursor, fuente, session_id))
    ventana = reparto.get(adquisicion)
    if ventana is None:
        raise HTTPException(status_code=404, detail={
            "motivo": "esa adquisicion no tiene filas en esta sesion",
            "adquisicion": adquisicion})
    return ventana


def _repartir_el_reloj(cursor, fuente: str, session_id: str) -> dict:
    """El reloj de la sesion repartido entre sus adquisiciones, sin huecos.

    POR QUE NO SE MIDE CADA VENTANA POR SEPARADO.

    La forma directa ---`min/max(timestamp)` filtrando por `replay_run_id`---
    recorre las 113 senales y filtra por una columna que **no** es de
    segmentacion, de modo que hay que descomprimir para mirarla. Medido sobre
    Spa, 5,64 millones de filas: **18,04 s**. La misma medida sobre
    `lap_number`, que si esta segmentada, tarda **0,69 s**, y las tres
    adquisiciones de una sola pasada, **0,11 s**.

    POR QUE EL PUNTO MEDIO Y NO LOS EXTREMOS DE `lap_number`.

    Acotar a `[min, max]` de `lap_number` recortaria las filas de las otras 112
    senales que caigan un instante antes o despues. El corte entre dos
    adquisiciones se pone, en cambio, **a mitad de camino** entre el final de
    una y el principio de la siguiente, y los extremos quedan abiertos: asi
    cada fila de la sesion cae en exactamente una adquisicion y ninguna se
    pierde.

    Lo unico que se supone es lo que ya suponia la version anterior: que una
    adquisicion ocupa un tramo continuo de reloj y que no se intercalan. Es lo
    que significa haber capturado o reproducido de corrido.
    """

    cursor.execute("""
        SELECT replay_run_id, min(timestamp), max(timestamp)
          FROM telemetry_messages
         WHERE source_type = %s AND session_id = %s AND signal_name = 'lap_number'
         GROUP BY replay_run_id
         ORDER BY min(timestamp)
    """, (fuente, session_id))
    tramos = cursor.fetchall()

    ventanas: dict = {}
    for i, (run, desde, hasta) in enumerate(tramos):
        antes = tramos[i - 1][2] if i > 0 else None
        despues = tramos[i + 1][1] if i + 1 < len(tramos) else None
        v0 = _iso(antes + (desde - antes) / 2) if antes is not None else "-infinity"
        v1 = _iso(hasta + (despues - hasta) / 2) if despues is not None else "infinity"
        ventanas[run or ORIGEN_SIN_CORRIDA] = (v0, v1)
        if run is not None:
            ventanas[run] = (v0, v1)
    return ventanas


def _declarar_alcance(cursor, fuente: str, session_id: str,
                      adquisicion: str | None, fase: int | None) -> dict:
    """Que se esta mirando, dicho en la respuesta.

    Una respuesta que junta tres adquisiciones y no lo dice se lee como una
    carrera continua. Aunque el comportamiento por omision no cambie ---y no
    cambia, para no romper a nadie--- la respuesta tiene que declararlo.
    """

    cursor.execute("""
        SELECT count(DISTINCT COALESCE(replay_run_id, '')) FROM telemetry_messages
         WHERE source_type = %s AND session_id = %s AND signal_name = 'lap_number'
    """, (fuente, session_id))
    fila = cursor.fetchone()
    cuantas = int(fila[0]) if fila and fila[0] is not None else 1
    elegida = adquisicion or ("todas" if cuantas > 1 else ORIGEN_SIN_CORRIDA)
    return {
        "adquisicion": elegida,
        "fase": fase,
        "adquisiciones_en_la_sesion": cuantas,
        "mezclada": cuantas > 1 and elegida == "todas",
        "advertencia": (
            "esta respuesta junta %d adquisiciones distintas bajo el mismo "
            "identificador de sesion: no es una carrera continua. Elegir con "
            "`?adquisicion=`; ver /sesiones/{id}/adquisiciones" % cuantas
        ) if (cuantas > 1 and elegida == "todas") else None,
    }




def _clausula_de_adquisicion(adquisicion: str | None) -> tuple[str, list]:
    """Condicion SQL para acotar a una adquisicion. Vacia si no se pidio."""

    if not adquisicion or adquisicion == "todas":
        return "", []
    if adquisicion == ORIGEN_SIN_CORRIDA:
        return " AND replay_run_id IS NULL", []
    return " AND replay_run_id = %s", [adquisicion]


def _captura_us() -> str:
    """El reloj monotonico de captura, venga de la columna o del metadato.

    La columna se agrego despues; las capturas anteriores lo llevan en el
    metadato y ahi sigue estando. Leer solo la columna dejaria al original de
    Spa sin reloj de captura, que es justamente el que hace falta para separar
    sus fases.
    """

    return ("COALESCE(desplazamiento_captura_us, "
            "(metadata->'extra'->>'desplazamiento_captura_us')::bigint)")


def _orden_dentro_de_la_sesion() -> str:
    """Con que se ordenan las muestras de una sesion, y por que no es el otro.

    EL RELOJ DE CAPTURA NO SIRVE PARA ORDENAR, Y SE MIDIO POR QUE
    ------------------------------------------------------------
    `_captura_us()` se llama a si mismo monotonico, y lo es **dentro de una
    captura**. Deja de serlo apenas hay dos: cada una numera su desplazamiento
    desde cero, de modo que ordenarlas juntas las **entrelaza**.

    Eso no es un caso raro. En el simulador se reinicia la vuelta sin terminar
    la sesion ---para no perder tiempo--- y el resultado son dos capturas del
    mismo `session_uid`, las dos originales, las dos con `replay_run_id` nulo:
    indistinguibles.

    Medido el 2026-09-09 sobre una contrarreloj de Spielberg con dos capturas:
    ordenando por reloj de captura, `session_time_s` retrocedia **401 veces**, y
    los 401 saltos eran de **exactamente -51,434 s**. Un reloj que se reinicia
    de verdad da saltos distintos; una constante repetida cuatrocientas veces
    son dos series con un desfase fijo. El resultado eran 401 fases inventadas
    ---casi todas rotuladas «Espera de luces» en una sesion que no tiene
    luces--- y el coche saltando entre dos puntos de la pista separados por
    cincuenta y un segundos.

    EL CONTADOR DE CUADROS SI ES MONOTONICO EN LA SESION
    ----------------------------------------------------
    Lo emite el juego y no el capturador, de modo que no sabe ni le importa
    cuantas veces se empezo a grabar. Sobre esa misma sesion: 10.898 valores
    distintos para 10.898 muestras ---uno por muestra, sin repetir--- y
    ordenando por el, `session_time_s` retrocede **cero veces**.

    Se conserva `COALESCE` con el reloj de captura para lo que no traiga
    contador: OpenF1 y el bus del vehiculo real no lo tienen, y ahi el orden
    anterior sigue siendo el correcto. Las capturas de F1 25 si lo traen, tambien
    las viejas ---comprobado sobre las 60.468 muestras del original de Spa---,
    de modo que este cambio no deja a ninguna sin ordenar.
    """

    return ("COALESCE((metadata->'extra'->>'frame_identifier')::bigint, %s)"
            % _captura_us())


def _clausula_de_tramo(f0: int | None, f1: int | None) -> tuple[str, list]:
    """La condicion que acota a una fase, lista para concatenar.

    UNA SOLA, PARA TODAS LAS CONSULTAS.

    El defecto que esto corrige era exactamente el de tenerla escrita en unos
    sitios y no en otros: `/posiciones` resolvia los limites de la fase, los
    usaba para calcular la ventana de la vuelta y despues **seleccionaba las
    distancias sin volver a filtrar**. Como la formacion y la carrera se
    solapan en UTC a proposito, acotar por ventana no implica que las filas de
    esa ventana sean de esa fase: en la vuelta 2 de Spa entraban 34 muestras de
    formacion y la distancia saltaba de 0,2 a 5.676,2 m.

    Se emite vacia cuando no hay fase pedida, en vez de un `IS NULL OR`: asi la
    consulta por omision queda igual que antes y el planificador no carga con
    una condicion que nunca filtra.
    """

    preds, par = _predicados_de_tramo(f0, f1)
    return "".join(" AND " + p for p in preds), par


def _predicados_de_tramo(f0: int | None, f1: int | None) -> tuple[list[str], list]:
    """Lo mismo, suelto, para las consultas que arman su `WHERE` por partes."""

    preds, par = [], []
    if f0 is not None:
        preds.append("%s >= %%s" % _captura_us())
        par.append(f0)
    if f1 is not None:
        preds.append("%s < %%s" % _captura_us())
        par.append(f1)
    return preds, par


def _fases_de(cursor, fuente: str, session_id: str,
              adquisicion: str | None) -> list[dict]:
    """Los tramos entre reinicios del reloj del juego, en orden de captura.

    Se mira `lap_number`, que es una senal que el juego publica de forma
    continua durante toda la sesion: alcanza para ubicar los reinicios sin
    recorrer las 113. El resultado se memoriza: seis rutas piden lo mismo en la
    misma apertura ---ver `_memorizado`---.
    """

    clave = adquisicion or "todas"
    if clave != "todas":
        # Todas las adquisiciones se resuelven de una pasada: `/adquisiciones`
        # las pide las tres seguidas y hacerlo de a una eran seis consultas.
        todas = _memorizado(("fases_todas", fuente, session_id),
                            lambda: _medir_fases_de_todas(cursor, fuente, session_id))
        if clave in todas:
            return todas[clave]
    return _memorizado(("fases", fuente, session_id, clave),
                       lambda: _medir_fases(cursor, fuente, session_id, adquisicion))


def _medir_fases_de_todas(cursor, fuente: str, session_id: str) -> dict:
    """Las fases de cada adquisicion, en dos consultas y no en dos por cada una.

    Medido sobre Spa, que tiene tres: `/adquisiciones` tardaba 8,34 s vistos
    desde el navegador, y es lo primero que el tablero espera ---sin saber que
    adquisiciones hay no puede pedir nada mas---. El trabajo es el mismo para
    las tres y se agrupa por `replay_run_id`.
    """

    cap = _captura_us()
    cursor.execute("""
        WITH p AS (
          SELECT replay_run_id AS run, %s AS d, %s AS orden,
                 (metadata->'extra'->>'session_time_s')::double precision AS reloj
            FROM telemetry_messages
           WHERE source_type = %%s AND session_id = %%s
             AND signal_name = 'lap_number'),
        q AS (SELECT run, d, reloj,
                     lag(reloj) OVER (PARTITION BY run ORDER BY orden) AS ant
                FROM p WHERE d IS NOT NULL AND reloj IS NOT NULL)
        SELECT run, d FROM q
         WHERE ant IS NOT NULL AND reloj < ant ORDER BY run, d
    """ % (cap, _orden_dentro_de_la_sesion()), (fuente, session_id))
    cortes: dict = {}
    for run, d in cursor.fetchall():
        cortes.setdefault(run or ORIGEN_SIN_CORRIDA, []).append(d)

    cursor.execute("""
        SELECT replay_run_id, min(%s), max(%s)
          FROM telemetry_messages
         WHERE source_type = %%s AND session_id = %%s
           AND signal_name = 'lap_number'
         GROUP BY replay_run_id
    """ % (cap, cap), (fuente, session_id))

    salida: dict = {}
    for run, inicio, fin in cursor.fetchall():
        clave = run or ORIGEN_SIN_CORRIDA
        if inicio is None:
            salida[clave] = []
            continue
        salida[clave] = _armar_fases([inicio] + cortes.get(clave, []) + [fin])
    return salida


def _armar_fases(bordes: list) -> list[dict]:
    """Los tramos que delimitan unos bordes en reloj de captura.

    DOS COSAS DISTINTAS, Y POR ESO DOS PARES DE NUMEROS.

    `desde_us`/`hasta_us` son lo **medido**: el primero y el ultimo
    `lap_number` del tramo. Sirven para decir cuanto dura y no para filtrar.

    `limite_desde_us`/`limite_hasta_us` son con lo que **se acota**, y no son lo
    mismo:

    * medio abiertos ---`[desde, hasta)`--- de modo que cada fila caiga en
      exactamente una fase y el corte entre dos no repita ni pierda nada;
    * **abiertos en los extremos**. Un borde tomado del ultimo `lap_number`
      dejaria afuera muestras validas de la misma adquisicion: en el cuadro
      64494 de Spa, `lap_number` llega con desplazamiento 3.030.179.999 y la
      posicion del mismo cuadro, 757 microsegundos despues. Acotar por el
      primero borra esa coordenada. El ultimo tramo llega hasta donde llegue la
      adquisicion ---que ya viene acotada por su ventana de tiempo--- y no hasta
      la ultima muestra de una senal en particular. Lo mismo, al reves, con el
      primero.
    """

    fases = []
    ultimo = len(bordes) - 2
    for i in range(len(bordes) - 1):
        desde, hasta = bordes[i], bordes[i + 1]
        fases.append({
            "orden": i + 1,
            "desde_us": int(desde),
            "hasta_us": int(hasta),
            "limite_desde_us": None if i == 0 else int(desde),
            "limite_hasta_us": None if i == ultimo else int(hasta),
            "duracion_de_captura_s": round((hasta - desde) / 1e6, 3),
            "reloj_del_juego_reinicia_al_entrar": i > 0,
        })
    return fases


def _medir_fases(cursor, fuente: str, session_id: str,
                 adquisicion: str | None) -> list[dict]:
    """Los bordes de las fases, medidos de verdad contra la base."""

    cond, par = _clausula_de_adquisicion(adquisicion)
    cursor.execute("""
        WITH p AS (
          SELECT %s AS d,
                 (metadata->'extra'->>'session_time_s')::double precision AS reloj
            FROM telemetry_messages
           WHERE source_type = %%s AND session_id = %%s
             AND signal_name = 'lap_number'""" % _captura_us() + cond + """),
        q AS (SELECT d, reloj, lag(reloj) OVER (ORDER BY d) AS ant FROM p
               WHERE d IS NOT NULL AND reloj IS NOT NULL)
        SELECT d, ant, reloj FROM q
         WHERE ant IS NOT NULL AND reloj < ant ORDER BY d
    """, tuple([fuente, session_id] + par))
    cortes = cursor.fetchall()

    cursor.execute("""
        SELECT min(%s), max(%s)
          FROM telemetry_messages
         WHERE source_type = %%s AND session_id = %%s
           AND signal_name = 'lap_number'""" % (_captura_us(), _captura_us()) + cond,
                   tuple([fuente, session_id] + par))
    extremos = cursor.fetchone()
    if not extremos or extremos[0] is None:
        return []
    inicio, fin = extremos
    return _armar_fases([inicio] + [c[0] for c in cortes] + [fin])


# --------------------------------------------------------------------------
# Quien es cada vehiculo, y de cuantos hay telemetria
# --------------------------------------------------------------------------
#
# SON DOS COSAS DISTINTAS Y SE DECLARAN POR SEPARADO.
#
# La **identidad** sale del metadato de captura: el paquete de participantes
# dice que el vehiculo de indice 19 es NORRIS, numero 4, McLaren. No esta en la
# base a proposito ---guardar un nombre como senal de telemetria almacenaria el
# mismo texto millones de veces para decir veinte cosas que no cambian--- y por
# eso se lee de donde vive.
#
# La **cobertura** sale de la base: cuantos de esos vehiculos llegaron a tener
# una sola muestra guardada. En la carrera de Spa la parrilla declara veinte y
# la base tiene uno. Conocer el nombre de los otros diecinueve no es tener sus
# señales, y presentarlo junto seria afirmar que las hay.

#: Como se llama el vehiculo de indice `n` de una sesion. Es el mismo formato
#: que acuña el adaptador al normalizar (`adapters/f1_25.py`); escrito aca una
#: sola vez para que la union no se arme con un `split` del identificador.
FORMA_DEL_VEHICULO = "%s:car:%d"


def _vehiculos_nombrados(session_id: str, declarada: dict,
                         con_telemetria: set[str] | None = None,
                         propio: str | None = None) -> list[dict]:
    """Los participantes de una parrilla, unidos a la clave tecnica del vehiculo.

    LA UNION SE DECLARA, NO SE ADIVINA. `vehicle_id` se compone en el adaptador
    como `<session_id>:car:<indice>`, y ese es el unico camino del indice del
    protocolo a la clave de la base.

    `con_telemetria` es opcional porque no siempre se sabe. Saberlo cuesta
    recorrer la base buscando que vehiculos tienen muestras, y hay un caso donde
    no hace falta: mientras la sesion se esta capturando, lo que se quiere es el
    nombre, y quien tiene muestras cambia con cada mensaje que llega. Cuando no
    se pasa, el campo **no se inventa**: no aparece.
    """

    salida = []
    for v in declarada["vehiculos"]:
        clave = FORMA_DEL_VEHICULO % (session_id, v["indice"])
        fila = {
            "indice": v["indice"],
            "vehicle_id": clave,
            "nombre": v["nombre"],
            "numero": v["numero"],
            "equipo": v["equipo"],
            "es_ia": v["es_ia"],
            # QUIEN CONDUCE, DECLARADO Y NO ADIVINADO.
            #
            # El tablero lo tomaba del vehiculo cuya serie devolvia primero la
            # consulta. Con un vehiculo capturado eso acertaba por construccion;
            # con cuatro es arbitrario, y una sesion corrida con Hamilton abria
            # mostrando a Russell ---y el panel de vehiculo en ceros, porque de
            # un rival el protocolo no publica ni temperaturas ni presiones---.
            #
            # Sin declaracion no se marca a ninguno: marcar al primero seria
            # volver a adivinar con otra excusa.
            "es_propio": propio is not None and clave == propio,
        }
        if con_telemetria is not None:
            fila["con_telemetria"] = clave in con_telemetria
        salida.append(fila)
    return salida


def _parrilla_de_la_adquisicion(session_id: str, fuente: str, desde, hasta,
                                shas: list, con_telemetria: set[str],
                                propio: str | None = None) -> dict:
    """La parrilla de **esta adquisicion**, unida a las claves tecnicas.

    LA UNION SE DECLARA, NO SE ADIVINA. `vehicle_id` se compone en el adaptador
    como `<session_id>:car:<indice>`, y ese es el unico camino del indice del
    protocolo a la clave de la base. Se arma la clave que le corresponderia a
    cada participante y se dice, para cada una, si la base tiene muestras suyas.

    NO SE REUTILIZA UNA PARRILLA DE OTRA CAPTURA. La busqueda es por
    `session_id`: que dos sesiones tengan un `car:19` no las relaciona, porque
    el indice es la posicion del vehiculo en el paquete de esa sesion.

    Y TAMPOCO SE REUTILIZA LA DE OTRA ADQUISICION DE LA MISMA SESION. Volver a
    capturar produce filas con el mismo `session_uid`, y esas dos capturas
    pueden declarar gente distinta en el mismo indice. Antes ganaba la mas
    larga, que no es una prueba de pertenencia: ahora se ata cada adquisicion a
    su captura por la huella del archivo o por la ventana en que se escribio, y
    si no se puede atar se dice que es ambigua y nadie queda nombrado.
    """
    if fuente != "f1_25_udp_simulation":
        return {"disponible": False,
                "motivo": "solo la simulacion declara participantes",
                "con_telemetria": len(con_telemetria)}

    candidatas = procedencia_sesiones.candidatas_de_parrilla(session_id)
    if not candidatas:
        return {"disponible": False,
                "motivo": ("ninguna captura cerrada declara la parrilla de esta "
                           "sesion: se escribe al cerrar el archivo"),
                "con_telemetria": len(con_telemetria)}

    declarada = _elegir_parrilla(candidatas, desde, hasta, shas)
    if declarada is None:
        return {"disponible": False, "ambigua": True,
                "motivo": ("%d capturas comparten esta sesion y declaran "
                           "participantes distintos; sus metadatos no permiten "
                           "decir cual corresponde a esta adquisicion"
                           % len(candidatas)),
                "con_telemetria": len(con_telemetria)}

    vehiculos = _vehiculos_nombrados(session_id, declarada, con_telemetria, propio)

    return {
        "disponible": True,
        "vehiculos": vehiculos,
        "vehiculos_en_carrera": declarada.get("vehiculos_en_carrera"),
        # Cuantos vehiculos de la base tienen muestras, se los haya reconocido
        # en la parrilla o no: es la cobertura de la telemetria, no un recuento
        # de los que se pudieron nombrar.
        "con_telemetria": len(con_telemetria),
        "origen": declarada["origen"],
        # De la captura solo viaja lo que sirve para reconocerla. Ni la ruta ni
        # el resto del sidecar: eso se queda del lado del servidor.
        "captura": (declarada.get("captura") or {}).get("archivo"),
        "es_una_foto": declarada.get("es_una_foto"),
        "que_no_significa": (
            "que un vehiculo figure en la parrilla no dice que haya una sola "
            "muestra suya: `con_telemetria` lo declara por vehiculo"),
    }


def _elegir_parrilla(candidatas: list[dict], desde, hasta, shas: list) -> dict | None:
    """Cual de las capturas de esta sesion es la de esta adquisicion.

    Con una sola no hay nada que elegir. Con varias que declaran exactamente los
    mismos participantes tampoco: cual sea da igual. Recien cuando difieren hay
    que atarlas, y si no se puede se devuelve `None`, que el tablero lee como
    «Vehículo 19». Inventar la asociacion para evitar ese respaldo seria
    ponerle a un vehiculo el nombre del de otra carrera.
    """
    if len(candidatas) == 1:
        return candidatas[0]
    if all(procedencia_sesiones.mismos_participantes(candidatas[0], c)
           for c in candidatas[1:]):
        return candidatas[0]
    atadas = [c for c in candidatas
              if procedencia_sesiones.pertenece_a(c, desde, hasta, shas)]
    if len(atadas) == 1:
        return atadas[0]
    if atadas and all(procedencia_sesiones.mismos_participantes(atadas[0], c)
                      for c in atadas[1:]):
        return atadas[0]
    return None


@router.get("/sesiones/{session_id}/adquisiciones")
def adquisiciones(session_id: str) -> dict:
    """Cuantas veces se capturo o se reprodujo esta sesion, y en que fases.

    Es la ruta que permite no tratar como una carrera continua lo que comparte
    identificador de juego y no comparte adquisicion.
    """

    fuente = _fuente_de(session_id)
    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        cursor.execute("""
            SELECT replay_run_id, count(*), count(DISTINCT vehicle_id),
                   min(timestamp), max(timestamp),
                   array_agg(DISTINCT vehicle_id),
                   -- La huella del archivo del que salieron estas filas, cuando
                   -- el capturador la escribio. Es lo que ata una adquisicion a
                   -- su captura sin depender de cual sea la mas larga.
                   array_agg(DISTINCT metadata->'extra'->>'captura_sha256')
              FROM telemetry_messages
             WHERE source_type = %s AND session_id = %s
               AND signal_name = 'lap_number'
             GROUP BY replay_run_id
             ORDER BY min(timestamp)
        """, (fuente, session_id))
        crudas = cursor.fetchall()

        salida = []
        con_telemetria: set[str] = set()
        for fila in crudas:
            run, filas, vehiculos, desde, hasta = fila[:5]
            suyos = [x for x in (fila[5] if len(fila) > 5 else None) or [] if x]
            shas = [x for x in (fila[6] if len(fila) > 6 else None) or [] if x]
            con_telemetria.update(suyos)
            clave = run or ORIGEN_SIN_CORRIDA
            salida.append({
                "clave": clave,
                "replay_run_id": run,
                "es_reproduccion": run is not None,
                "muestras_de_vuelta": filas,
                "vehiculos": vehiculos,
                "desde_utc": desde.isoformat() if desde else None,
                "hasta_utc": hasta.isoformat() if hasta else None,
                # QUIEN ES CADA VEHICULO **EN ESTA ADQUISICION**. Va aca y no en
                # la raiz porque dos capturas de la misma sesion pueden declarar
                # gente distinta en el mismo indice.
                "parrilla": _parrilla_de_la_adquisicion(
                    session_id, fuente, desde, hasta, shas, set(suyos),
                    _vehiculo_propio(cursor, fuente, session_id)),
                "fases": _fases_de(cursor, fuente, session_id, clave),
            })

    return {
        "session_id": session_id,
        "fuente": fuente,
        "adquisiciones": salida,
        "mezclada": len(salida) > 1,
        "como_se_identifica": (
            "por `replay_run_id`: el reproductor lo escribe y la captura "
            "original no. NO vale como regla general ---la columna se agrego "
            "despues de que existieran capturas--- y `origen_adquisicion` del "
            "metadato no discrimina, porque el reproductor reemite la carga "
            "original con sus metadatos"),
        "reloj_de_las_fases": (
            "monotonico de captura (`desplazamiento_captura_us`), no el "
            "`timestamp`: el reloj del juego se reinicia en la largada y el "
            "timestamp derivado retrocede con el"),
        "si_hay_mas_de_una": (
            "elegir con `?adquisicion=` en cada consulta. Sin elegir, las rutas "
            "devuelven todo junto y lo declaran, que es lo que hacian antes"),
    }


@router.get("/sesiones/{session_id}/series-tiempo")
def series_por_tiempo(
    session_id: str,
    senales: Annotated[str, Query(description="Nombres de senal separados por coma")],
    vehiculos: Annotated[str | None, Query(description="Identificadores separados por coma")] = None,
    puntos: Annotated[int, Query(ge=50, le=5000)] = 600,
    adquisicion: Annotated[str | None, Query(
        description="Que adquisicion mirar: `original`, un `replay_run_id`, o `todas`")] = None,
    fase: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, Any]:
    """Series contra el reloj de sesion para fuentes sin distancia medida."""

    fuente = _fuente_de(session_id)
    pedidas = [s.strip() for s in senales.split(",") if s.strip()]
    if not pedidas:
        raise HTTPException(status_code=422, detail="Hay que pedir al menos una señal.")
    if len(pedidas) > 20:
        raise HTTPException(status_code=422, detail="Hasta veinte señales por consulta temporal.")

    condiciones = ["source_type = %s", "session_id = %s"]
    parametros: list[Any] = [fuente, session_id]
    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        ventana = _ventana_de_alcance(cursor, fuente, session_id, adquisicion)
        fase_desde, fase_hasta = _limites_de_fase(
            cursor, fuente, session_id, adquisicion, fase)
    if ventana:
        condiciones.append("timestamp BETWEEN %s AND %s")
        parametros.extend([ventana[0], ventana[1]])
    predicados_fase, parametros_fase = _predicados_de_tramo(
        fase_desde, fase_hasta)
    condiciones.extend(predicados_fase)
    parametros.extend(parametros_fase)

    autos = [v.strip() for v in vehiculos.split(",") if v.strip()] if vehiculos else []
    if autos:
        condiciones.append("vehicle_id = ANY(%s)")
        parametros.append(autos)
    condiciones.append("signal_name = ANY(%s)")
    parametros.append(pedidas)

    # Los canales binarios CAN viven en value_boolean. Llevarlos a 0/1 en esta
    # vista permite graficarlos sin alterar el valor persistido ni su unidad.
    columnas = []
    columnas_par: list[Any] = []
    for indice, senal in enumerate(pedidas):
        columnas.append(
            'max(COALESCE(value_numeric, CASE WHEN value_boolean THEN 1.0 '
            'WHEN value_boolean IS FALSE THEN 0.0 END)) '
            'FILTER (WHERE signal_name = %s) AS senal_%d' % ("%s", indice))
        columnas_par.append(senal)
    for indice, senal in enumerate(pedidas):
        columnas.append(
            'max(unit) FILTER (WHERE signal_name = %s) AS unidad_%d'
            % ("%s", indice))
        columnas_par.append(senal)

    consulta = """
        SELECT timestamp, vehicle_id,
               {columnas}
          FROM telemetry_messages
         WHERE {donde}
         GROUP BY timestamp, vehicle_id
         ORDER BY vehicle_id, timestamp
    """.format(columnas=",\n               ".join(columnas),
               donde=" AND ".join(condiciones))

    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        cursor.execute(consulta, tuple(columnas_par + parametros))
        filas = cursor.fetchall()

    if not filas:
        return {"session_id": session_id, "fuente": fuente, "senales": pedidas,
                "vehiculos": {}, "muestras": 0, "unidades": {},
                "motivo": "La sesion no tiene esas senales en el rango pedido."}

    origen = min(f[0] for f in filas)
    idx_unidades = 2 + len(pedidas)
    unidades: dict[str, str] = {}
    for fila in filas:
        for i, senal in enumerate(pedidas):
            if senal not in unidades and fila[idx_unidades + i] is not None:
                unidades[senal] = fila[idx_unidades + i]

    por_vehiculo: dict[str, list[tuple]] = {}
    for fila in filas:
        por_vehiculo.setdefault(fila[1], []).append(fila)

    salida: dict[str, Any] = {}
    submuestreado = False
    originales = 0
    for vehiculo, suyas in por_vehiculo.items():
        originales = max(originales, len(suyas))
        # Las columnas 2..2+n son las señales; despues vienen sus unidades.
        recorte, reducida = _reducir(suyas, puntos, (2, 2 + len(pedidas)))
        submuestreado = submuestreado or reducida
        serie: dict[str, list] = {
            "tiempo_s": [round((f[0] - origen).total_seconds(), 6) for f in recorte],
            "timestamp_utc": [f[0].isoformat() for f in recorte],
        }
        for i, senal in enumerate(pedidas):
            serie[senal] = [
                round(f[2 + i], 4) if f[2 + i] is not None else None
                for f in recorte
            ]
        salida[vehiculo] = serie

    return {
        "session_id": session_id,
        "fuente": fuente,
        "senales": pedidas,
        "vehiculos": salida,
        "unidades": unidades,
        "muestras": sum(len(v["tiempo_s"]) for v in salida.values()),
        "submuestreado": submuestreado,
        "muestras_originales": originales,
        "reduccion": ("una de cada %d" % -(-originales // puntos)) if submuestreado else None,
        "puntos_pedidos": puntos,
        "desde_utc": origen.isoformat(),
        "hasta_utc": max(f[0] for f in filas).isoformat(),
        "duracion_s": round((max(f[0] for f in filas) - origen).total_seconds(), 6),
        "eje": "tiempo desde el inicio del tramo, en segundos",
        "ejes_disponibles": {
            "tiempo": {"campo": "tiempo_s", "unidad": "s", "reloj": "reloj de sesion"},
        },
    }


@router.get("/sesiones/{session_id}/series")
def series_por_distancia(
    session_id: str,
    senales: Annotated[str, Query(description="Nombres de senal separados por coma")],
    vuelta: int | None = None,
    vehiculos: Annotated[str | None, Query(description="Identificadores separados por coma")] = None,
    desde_m: float = 0.0,
    hasta_m: float | None = None,
    puntos: Annotated[int, Query(ge=50, le=5000)] = 600,
    adquisicion: Annotated[str | None, Query(
        description="Que adquisicion mirar: `original`, un `replay_run_id`, o `todas`")] = None,
    fase: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, Any]:
    """Series de una o varias senales contra la distancia recorrida.

    ES EL ENDPOINT QUE SOSTIENE EL TABLERO. Todos los graficos van contra
    distancia y no contra tiempo, porque contra distancia dos vueltas se
    superponen: el mismo metro es el mismo lugar del circuito.

    `puntos` submuestrea de forma pareja. Una vuelta de Spa tiene 2.644
    muestras por senal; devolverlas todas para cinco senales y cuatro
    vehiculos serian mas de cincuenta mil puntos para dibujar un grafico de
    trescientos pixeles de ancho. El submuestreo se declara en la respuesta.
    """
    fuente = _fuente_de(session_id)
    senal_distancia = DISTANCIA_POR_FUENTE.get(fuente)
    if not senal_distancia:
        raise HTTPException(
            status_code=422,
            detail=("La fuente %s no tiene eje de distancia: %s. No es un fallo "
                    "que se pueda reintentar; para esta fuente hay que usar las "
                    "rutas por tiempo." % (fuente, _sin_distancia(fuente))),
        )

    pedidas = [s.strip() for s in senales.split(",") if s.strip()]
    if not pedidas:
        raise HTTPException(status_code=422, detail="Hay que pedir al menos una señal.")
    if len(pedidas) > 12:
        raise HTTPException(status_code=422, detail="Hasta doce señales por consulta.")

    autos = [v.strip() for v in vehiculos.split(",")] if vehiculos else []

    condiciones = ["source_type = %s", "session_id = %s"]
    parametros: list[Any] = [fuente, session_id]
    # El alcance entra como una condicion mas, antes de cualquier otra: acota
    # tambien la consulta que resuelve la ventana de la vuelta.
    with db.obtener_conexion() as _cx, _cx.cursor() as _cur:
        _v = _ventana_de_alcance(_cur, fuente, session_id, adquisicion)
        _f0, _f1 = _limites_de_fase(_cur, fuente, session_id, adquisicion, fase)
    if _v:
        condiciones.append("timestamp BETWEEN %s AND %s")
        parametros.extend([_v[0], _v[1]])
    # La fase acota estas filas, no solo la ventana: formacion y carrera se
    # solapan en UTC y sin esto una serie de la carrera arrastraria muestras de
    # la formacion con la misma distancia recorrida.
    _tpreds, _tpar = _predicados_de_tramo(_f0, _f1)
    condiciones.extend(_tpreds)
    parametros.extend(_tpar)
    if autos:
        condiciones.append("vehicle_id = ANY(%s)")
        parametros.append(autos)

    # Tiempo y distancia de sesion ya llegan en cada muestra F1 25. Se
    # conservan en la respuesta para que el navegador no tenga que convertir
    # metros a segundos ni fabricar una distancia acumulada entre vueltas.
    interes = pedidas + [senal_distancia, "session_distance"] + (["lap_number"] if vuelta is not None else [])
    condiciones.append("signal_name = ANY(%s)")
    parametros.append(interes)

    # ACOTAR POR TIEMPO ANTES DE AGRUPAR.
    #
    # El filtro por vuelta se aplicaba **despues** de agrupar toda la sesion
    # por instante: para devolver una vuelta de dos minutos se recorrian los
    # cinco millones y medio de filas de la sesion entera. Medido el
    # 2026-09-07: pedir **una** señal costaba 5,6 s y pedir doce, 4,8 s. El
    # costo no estaba en las señales sino en el recorrido.
    #
    # La vuelta ocupa una ventana de tiempo conocida, y `timestamp` es la
    # dimension por la que la tabla esta particionada: acotar por ahi deja
    # fuera todos los trozos que no la contienen antes de agrupar nada. La
    # ventana sale de una consulta previa que solo mira `lap_number`, que es
    # una señal y una columna de segmentacion.
    ventana = None
    if vuelta is not None:
        with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
            # La ventana de la vuelta se busca **dentro** del alcance: sin
            # esto, la vuelta 1 de Spa abarca los tres dias que separan la
            # captura original de las corridas de prueba.
            filas_v = _filas(cursor, """
                SELECT min(timestamp), max(timestamp)
                  FROM telemetry_messages
                 WHERE source_type = %s AND session_id = %s
                   AND signal_name = 'lap_number' AND value_numeric = %s
                   AND (%s::timestamptz IS NULL OR timestamp BETWEEN %s AND %s)""" +
                "".join(" AND " + p for p in _tpreds) + """
            """, tuple([fuente, session_id, float(vuelta),
                        _v[0] if _v else None, _v[0] if _v else None,
                        _v[1] if _v else None] + _tpar))
        if filas_v and filas_v[0][0] is not None:
            ventana = (filas_v[0][0], filas_v[0][1])
            condiciones.append("timestamp BETWEEN %s AND %s")
            parametros.extend([ventana[0], ventana[1]])

    consulta = """
        WITH p AS (
            SELECT timestamp, vehicle_id,
                   %s
              FROM telemetry_messages
             WHERE {donde}
             GROUP BY timestamp, vehicle_id)
        SELECT * FROM p
         WHERE distancia IS NOT NULL {filtro_distancia} {filtro_vuelta}
         ORDER BY vehicle_id, distancia
    """
    columnas = ["max(value_numeric) FILTER (WHERE signal_name = %s) AS distancia"]
    columnas_par: list[Any] = [senal_distancia]
    if vuelta is not None:
        columnas.append("max(value_numeric) FILTER (WHERE signal_name = 'lap_number') AS vuelta")
    columnas.append("max(value_numeric) FILTER (WHERE signal_name = 'session_distance') AS distancia_sesion")
    for s in pedidas:
        columnas.append('max(value_numeric) FILTER (WHERE signal_name = %s) AS "%s"' % ("%s", s))
        columnas_par.append(s)
    # LA UNIDAD SALE DE LAS MISMAS FILAS QUE EL VALOR.
    #
    # POR QUE HACIA FALTA. `delta_to_race_leader` se compone en milisegundos y
    # el tablero lo imprimia crudo bajo un rotulo que decia segundos: 2.937 ms
    # se leian como «2937.000». El navegador no tenia como saberlo, porque la
    # respuesta no declaraba la unidad de nada.
    #
    # POR QUE DE ACA Y NO DE UNA TABLA. Dividir por mil en el navegador segun
    # una lista de nombres escrita a mano rompe la primera vez que otra fuente
    # publique un canal parecido ya en segundos ---`penalty_time` y
    # `safety_car_delta` ya lo estan---. La unidad viaja en cada fila desde que
    # el adaptador la normaliza; se la agrega sobre las filas que la consulta ya
    # esta leyendo, sin una pasada mas.
    for s in pedidas:
        columnas.append('max(unit) FILTER (WHERE signal_name = %s) AS "unidad:%s"' % ("%s", s))
        columnas_par.append(s)
    consulta = consulta % ",\n                   ".join(columnas)
    consulta = consulta.replace("{donde}", " AND ".join(condiciones))
    consulta = consulta.replace("{filtro_vuelta}", "AND vuelta = %s" if vuelta is not None else "")

    # EL RECORTE POR DISTANCIA TAMBIEN SE HACE EN LA BASE.
    #
    # Se hacia en Python despues de traer todo: para dibujar doscientos metros
    # de una vuelta se traian los siete mil, se armaban las filas en memoria y
    # se descartaban casi todas. Puesto aca, la base no las materializa.
    distancia_par: list[Any] = []
    filtro_distancia = ""
    if desde_m:
        filtro_distancia += " AND distancia >= %s"
        distancia_par.append(desde_m)
    if hasta_m is not None:
        filtro_distancia += " AND distancia <= %s"
        distancia_par.append(hasta_m)
    consulta = consulta.replace("{filtro_distancia}", filtro_distancia)

    todos = (columnas_par + parametros + distancia_par
             + ([vuelta] if vuelta is not None else []))

    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        cursor.execute(consulta, tuple(todos))
        filas = cursor.fetchall()

    if not filas:
        return {"session_id": session_id, "fuente": fuente, "senales": pedidas,
                "vehiculos": {}, "muestras": 0, "unidades": {},
                "motivo": "La sesion no tiene esas senales en el rango pedido."}

    desplazamiento = 2 if vuelta is not None else 1  # timestamp, vehicle_id
    idx_dist = 2
    idx_dist_sesion = 3 + (1 if vuelta is not None else 0)
    idx_primera = idx_dist_sesion + 1
    idx_unidades = idx_primera + len(pedidas)

    # QUE UNIDAD TRAJO CADA SENAL. Se toma la primera fila que la declare: la
    # columna es `NOT NULL` en el esquema, de modo que un nulo aca solo puede
    # significar que esa senal no aparece en esa fila.
    unidades: dict[str, str] = {}
    for f in filas:
        if len(unidades) == len(pedidas):
            break
        for i, s in enumerate(pedidas):
            if s in unidades:
                continue
            u = f[idx_unidades + i] if len(f) > idx_unidades + i else None
            if u is not None:
                unidades[s] = u

    por_vehiculo: dict[str, list[tuple]] = {}
    for f in filas:
        d = f[idx_dist]
        if d is None or d < desde_m:
            continue
        if hasta_m is not None and d > hasta_m:
            continue
        por_vehiculo.setdefault(f[1], []).append(f)

    salida: dict[str, Any] = {}
    submuestreado = False
    originales = 0
    for vehiculo, fs in por_vehiculo.items():
        originales = max(originales, len(fs))
        recorte, reducida = _reducir(fs, puntos)
        submuestreado = submuestreado or reducida
        serie: dict[str, list] = {
            "distancia_m": [round(f[idx_dist], 2) for f in recorte],
            "distancia_sesion_m": [
                round(f[idx_dist_sesion], 2) if f[idx_dist_sesion] is not None else None
                for f in recorte
            ],
            "timestamp_utc": [
                f[0].isoformat() if hasattr(f[0], "isoformat") else str(f[0])
                for f in recorte
            ],
        }
        for i, s in enumerate(pedidas):
            serie[s] = [
                (round(f[idx_primera + i], 4) if f[idx_primera + i] is not None else None)
                for f in recorte
            ]
        salida[vehiculo] = serie

    return {
        "session_id": session_id,
        "fuente": fuente,
        "vuelta": vuelta,
        "senales": pedidas,
        "vehiculos": salida,
        # La unidad en que viene cada senal, tal como la persistio el
        # adaptador. Quien la muestre convierte una sola vez y sabe cuando no
        # tiene que convertir: no todas las que se parecen estan en la misma
        # unidad.
        "unidades": unidades,
        "muestras": sum(len(v["distancia_m"]) for v in salida.values()),
        "submuestreado": submuestreado,
        # Cuantas muestras habia antes de reducir, para que el grafico pueda
        # declarar que lo que dibuja no es la resolucion de la medicion. Sin
        # esta cifra «submuestreado» no dice de cuanto a cuanto.
        "muestras_originales": originales,
        "reduccion": ("una de cada %d" % -(-originales // puntos)) if submuestreado else None,
        "puntos_pedidos": puntos,
        "eje": "distancia recorrida, en metros",
        "ejes_disponibles": {
            "distancia_vuelta": {"campo": "distancia_m", "unidad": "m", "naturaleza": "medido"},
            "distancia_sesion": {"campo": "distancia_sesion_m", "unidad": "m", "naturaleza": "medido"},
            "tiempo": {"campo": "timestamp_utc", "unidad": "s", "reloj": "reloj de sesion"},
        },
    }


# --------------------------------------------------------------------------
# 2. Trazado del circuito
# --------------------------------------------------------------------------

def _vueltas_por_reloj(cursor, session_id: str, vehicle_id: str | None) -> list[tuple]:
    """Las vueltas de esta sesion como ventanas de tiempo, o lista vacia.

    POR QUE HACE FALTA. El trazado agrupa por `lap_number`, que viaja en la
    telemetria del simulador. OpenF1 no lo publica: sus nueve señales son
    posicion y estado del coche, y nada dice en que vuelta va. Sin numero de
    vuelta **todas las filas caen en un solo grupo** y el dibujo sale con las
    cincuenta y dos vueltas de la carrera superpuestas ---mas la de formacion y
    el regreso a boxes---, que es un ovillo y no un circuito.

    Pero las vueltas existen: el contexto deportivo las trae con su instante de
    comienzo y su duracion. Son ventanas de **tiempo**, que es la dimension que
    esta fuente si tiene. De ahi salen.

    Se piden del vehiculo que se esta dibujando: dos pilotos cruzan la meta en
    instantes distintos, y usar las vueltas de uno para cortar el recorrido del
    otro parte el lazo por donde no corresponde.
    """

    clave = session_id.rsplit(":", 1)[-1]
    if not clave.isdigit():
        return []
    piloto = None
    if vehicle_id and ":driver:" in vehicle_id:
        cola = vehicle_id.rsplit(":driver:", 1)[-1]
        if cola.isdigit():
            piloto = int(cola)
    if piloto is None:
        return []
    cursor.execute("""
        SELECT lap_number, date_start,
               date_start + make_interval(secs => lap_duration_seconds)
          FROM racing_laps
         WHERE session_key = %s AND driver_number = %s
           AND date_start IS NOT NULL AND lap_duration_seconds IS NOT NULL
         ORDER BY lap_number
    """, (int(clave), piloto))
    return [(int(n), a, b) for n, a, b in cursor.fetchall()]


def _numerar_por_reloj(filas: list, vueltas: list[tuple]) -> list:
    """Le pone su numero de vuelta a cada fila, por el instante en que se midio.

    Las filas llegan ordenadas por tiempo y las vueltas tambien, asi que alcanza
    con avanzar una vez por cada lista. Lo que cae fuera de toda vuelta ---la
    formacion, el regreso a boxes--- se queda sin numero y queda fuera del
    dibujo, que es lo correcto: no son parte del circuito.
    """

    if not vueltas:
        return filas
    salida = []
    i = 0
    for fila in filas:
        cuando = fila[5]
        while i < len(vueltas) and vueltas[i][2] < cuando:
            i += 1
        if i < len(vueltas) and vueltas[i][1] <= cuando:
            salida.append(fila[:4] + (vueltas[i][0],) + fila[5:])
        else:
            salida.append(fila)
    return salida


def _vuelta_que_mejor_dibuja(por_vuelta: dict) -> list:
    """La vuelta que sirve de contorno del circuito: la que **cierra**.

    ANTES SE ELEGIA LA QUE MAS MUESTRAS TENIA, Y ESA ES LA MAS LENTA.

    Un contorno de circuito es un lazo: el ultimo punto tiene que volver al
    primero. Una vuelta que no cierra o le falta un tramo, o recorrio otro
    camino. Las dos cosas pasan en Spa, y elegir por cantidad de muestras caia
    justo en la segunda:

    | vuelta | muestras | poligonal | cierre |
    |---|---:|---:|---:|
    | 1  | 2.735 | 6.875,5 m | **78,19 m** ---le falta la recta de meta, que es de la fase anterior |
    | 13 | **2.809** | 6.853,4 m | **14,19 m** ---la de la parada: pasa por la calle de boxes |
    | 20 | 2.534 | 6.939,8 m | **1,49 m** |

    La vuelta 13 gana por muestras **porque es la mas lenta**: mas tiempo en
    pista son mas muestras. Y es justamente la que no describe el circuito.

    Se elige, entonces, entre las que cubren casi toda la distancia ---para que
    una media vuelta que casualmente cierre no gane--- la de menor cuerda de
    cierre. No se completa ni se suaviza nada: se elige cual de las vueltas
    medidas se dibuja, y la respuesta declara cual y cuanto cierra.
    """

    import math

    def cobertura(f):
        ds = [r[3] for r in f if r[3] is not None]
        return (max(ds) - min(ds)) if ds else 0.0

    def cierre(f):
        return math.hypot(f[0][0] - f[-1][0], f[0][1] - f[-1][1]) if f else float("inf")

    candidatas = list(por_vuelta.values())
    mejor = max((cobertura(f) for f in candidatas), default=0.0)
    if mejor > 0:
        # Nueve decimos de la mejor cobertura: la vuelta 1 de Spa, a la que le
        # falta la recta de meta, todavia entra ---cubre el 98,9 %--- y pierde
        # por la cuerda, que es lo que corresponde. Lo que este umbral descarta
        # es una vuelta cortada por la mitad.
        completas = [f for f in candidatas if cobertura(f) >= 0.9 * mejor]
        if completas:
            candidatas = completas
    return min(candidatas, key=cierre)


@router.get("/sesiones/{session_id}/trazado")
def trazado(session_id: str, vuelta: int | None = None,
            puntos: Annotated[int, Query(ge=50, le=3000)] = 400,
            adquisicion: Annotated[str | None, Query()] = None,
            vehiculo: Annotated[str | None, Query(
                description="De quien es el recorrido; por omision, quien conduce")] = None,
            fase: Annotated[int | None, Query(ge=1)] = None) -> dict[str, Any]:
    """Trazado del circuito en el plano, con su desnivel y su sentido de giro.

    El sentido se calcula con el area con signo del poligono y **no se
    supone**: sirve para orientar el dibujo, porque un circuito horario tiene
    que verse horario en pantalla.
    """
    fuente = _fuente_de(session_id)
    par = POSICION_POR_FUENTE.get(fuente)
    if not par:
        return {"session_id": session_id, "fuente": fuente, "puntos": [],
                "motivo": ("El bus del vehiculo no declara posicion. El recorrido se "
                           "reconstruye por integracion en /can/recorrido y se muestra "
                           "como reconstruccion, no como medicion.")}

    eje_x, eje_z = par
    senal_distancia = DISTANCIA_POR_FUENTE.get(fuente)
    interes = [eje_x, eje_z]
    if senal_distancia:
        interes.append(senal_distancia)
    if fuente == "f1_25_udp_simulation":
        interes += ["world_position_y", "lap_number"]

    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        # Sin acotar, el recorrido de Spa mezcla el de la captura original con
        # el de las pruebas de parrilla, y sale un circuito deformado.
        _tv = _ventana_de_alcance(cursor, fuente, session_id, adquisicion)
        # LA FASE, APLICADA Y NO SOLO ACEPTADA.
        #
        # Esta ruta declaraba `fase` en su firma y no la usaba: con `fase=3`
        # devolvia la geometria de la vuelta 1 armada con 6.435 muestras, de las
        # cuales solo 2.735 son de la carrera. La procedencia era incorrecta
        # aunque el dibujo cerrara.
        _tf0, _tf1 = _limites_de_fase(cursor, fuente, session_id, adquisicion, fase)
        _tramo, _tramo_par = _clausula_de_tramo(_tf0, _tf1)
        # EL TRAZADO ES EL DE UN COCHE, NO EL DE LA PARRILLA.
        #
        # Esta consulta gira la tabla a una fila por instante con
        # `max(value_numeric)`. Con un vehiculo eso es su posicion. Con cuatro es
        # **la mayor x de los cuatro junto a la mayor z de los cuatro**, que no
        # es donde estuvo ninguno: es una esquina de la caja que los contiene, y
        # dibuja un circuito que no existe.
        #
        # Se vio el 2026-09-10 en Austin, la primera carrera con la parrilla
        # acotada: el trazado salio como una tira angosta en vez del circuito.
        # El defecto estaba desde siempre y hacia falta un segundo coche para
        # que se notara.
        # QUIEN CONDUCE NO SIEMPRE LO DICE LA TELEMETRIA.
        #
        # `_vehiculo_propio` lo lee de `player_car_index`, que viaja en la
        # cabecera del protocolo del simulador. OpenF1 no tiene nada
        # equivalente: sus nueve señales describen el coche y ninguna dice cual
        # de ellos es el que se esta mirando. Quien consulta si lo sabe ---el
        # tablero tiene su vehiculo elegido--- y por eso se lo puede decir.
        _propio = vehiculo or _vehiculo_propio(cursor, fuente, session_id)
        _cv, _cv_par = _acotar_al_vehiculo(_propio)
        cursor.execute("""
            WITH p AS (
                SELECT timestamp,
                       max(value_numeric) FILTER (WHERE signal_name = %s) AS x,
                       max(value_numeric) FILTER (WHERE signal_name = %s) AS z,
                       max(value_numeric) FILTER (WHERE signal_name = 'world_position_y') AS y,
                       max(value_numeric) FILTER (WHERE signal_name = 'lap_distance') AS distancia,
                       max(value_numeric) FILTER (WHERE signal_name = 'lap_number') AS vuelta
                  FROM telemetry_messages
                 WHERE source_type = %s AND session_id = %s AND signal_name = ANY(%s)
                   AND (%s::timestamptz IS NULL OR timestamp BETWEEN %s AND %s)""" +
            _cv + _tramo + """
                 GROUP BY timestamp)
            SELECT x, z, y, distancia, vuelta, timestamp FROM p
             WHERE x IS NOT NULL AND z IS NOT NULL
             ORDER BY vuelta NULLS LAST, distancia NULLS LAST, timestamp
        """, tuple([eje_x, eje_z, fuente, session_id, interes,
                    _tv[0] if _tv else None, _tv[0] if _tv else None,
                    _tv[1] if _tv else None] + _cv_par + _tramo_par))
        filas = cursor.fetchall()

    if not filas:
        return {"session_id": session_id, "fuente": fuente, "puntos": [],
                "motivo": "La sesion no tiene posicion persistida."}

    # SIN `lap_number`, LA VUELTA SE DEDUCE DEL RELOJ.
    # Ver `_vueltas_por_reloj`: sin esto, una fuente que no publica el numero de
    # vuelta dibuja la sesion entera superpuesta.
    if all(f[4] is None for f in filas):
        with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
            _vs = _vueltas_por_reloj(cursor, session_id, _propio)
        filas = _numerar_por_reloj(filas, _vs)

    if vuelta is not None:
        filas = [f for f in filas if f[4] is not None and int(f[4]) == vuelta]
    else:
        por_vuelta: dict[Any, list] = {}
        for f in filas:
            por_vuelta.setdefault(f[4], []).append(f)
        filas = _vuelta_que_mejor_dibuja(por_vuelta)

    if not filas:
        return {"session_id": session_id, "fuente": fuente, "puntos": [],
                "motivo": "Esa vuelta no tiene posicion persistida."}

    recorte, _reducido = _reducir(filas, puntos)
    pts = [[round(f[0], 2), round(f[1], 2)] for f in recorte]

    area = 0.0
    for i in range(len(pts)):
        j = (i + 1) % len(pts)
        area += pts[i][0] * pts[j][1] - pts[j][0] * pts[i][1]

    alturas = [f[2] for f in filas if f[2] is not None]
    distancias = [f[3] for f in filas if f[3] is not None]

    return {
        "session_id": session_id,
        "fuente": fuente,
        "vuelta": int(recorte[0][4]) if recorte[0][4] is not None else None,
        "puntos": pts,
        "senales": {"x": eje_x, "y": eje_z},
        # CUIDADO CON ESTE CAMPO. Es el sentido **en el plano crudo de la
        # fuente**, no el sentido en que se corre el circuito. El juego usa un
        # sistema de coordenadas propio, y Spa ---que se corre en sentido
        # horario--- da antihorario en ese plano. Llamarlo «sentido» a secas
        # habria hecho que la API afirmara algo falso sobre el circuito.
        "sentido_en_el_plano_crudo": "antihorario" if area > 0 else "horario",
        "para_dibujarlo": (
            "invertir el eje vertical" if area <= 0 else "no invertir el eje vertical"),
        "metodo": ("area con signo del poligono. El sentido en que se corre el "
                   "circuito es un dato externo y no se deduce de aca."),
        "desnivel_m": round(max(alturas) - min(alturas), 1) if alturas else None,
        "largo_m": round(max(distancias), 1) if distancias else None,
        "muestras_originales": len(filas),
        # CUANTO LE FALTA AL LAZO PARA CERRAR, DICHO EN LA RESPUESTA.
        #
        # Es la medida de si esta vuelta describe el circuito. Una cuerda
        # grande significa que falta un tramo o que se recorrio otro camino
        # ---la calle de boxes---, y quien lea el trazado tiene que poder
        # saberlo sin volver a calcularlo.
        "cierre_m": round(
            ((pts[0][0] - pts[-1][0]) ** 2 + (pts[0][1] - pts[-1][1]) ** 2) ** 0.5, 2)
        if len(pts) > 1 else None,
    }


# --------------------------------------------------------------------------
# 5 y 9. Estado del vehiculo y puesta a punto
# --------------------------------------------------------------------------

ESQUINAS = ("front_left", "front_right", "rear_left", "rear_right")

CANALES_POR_ESQUINA = {
    "temperatura_superficie_c": "tyre_temperature_surface_%s",
    "temperatura_interna_c": "tyre_temperature_inner_%s",
    "presion_psi": "tyre_pressure_%s",
    "desgaste_pct": "tyre_wear_%s",
    "dano_pct": "tyre_damage_%s",
    "ampollas_pct": "tyre_blisters_%s",
    "freno_c": "brake_temperature_%s",
    "dano_freno_pct": "brake_damage_%s",
    "deslizamiento": "wheel_slip_ratio_%s",
    "velocidad_rueda_kmh": "wheel_speed_%s",
    "superficie": "surface_type_%s",
}

def senales_de_contexto() -> list[str]:
    """Todas las señales que describen el contexto de un instante.

    Es la union de clima, esquinas, carroceria y puesta a punto. Se arma en un
    solo lugar para que la consulta unica y las tres rutas sueltas no puedan
    quedar pidiendo cosas distintas.
    """
    senales = list(CANALES_CLIMA.values()) + list(CANALES_PUESTA_A_PUNTO.values())
    for plantilla in CANALES_POR_ESQUINA.values():
        senales += [plantilla % e for e in ESQUINAS]
    senales += list(CANALES_CARROCERIA.values())
    return list(dict.fromkeys(senales))


CANALES_CARROCERIA = {
    "ala_delantera_izq_pct": "wing_damage_front_left",
    "ala_delantera_der_pct": "wing_damage_front_right",
    "ala_trasera_pct": "wing_damage_rear",
    "piso_pct": "floor_damage",
    "difusor_pct": "diffuser_damage",
    "pontones_pct": "sidepod_damage",
    "caja_pct": "gearbox_damage",
    "motor_pct": "engine_damage",
}

CANALES_PUESTA_A_PUNTO = {
    "aleron_delantero": "setup_front_wing",
    "aleron_trasero": "setup_rear_wing",
    "diferencial_con_acelerador_pct": "setup_differential_on_throttle",
    "diferencial_sin_acelerador_pct": "setup_differential_off_throttle",
    "caida_delantera_deg": "setup_camber_front",
    "caida_trasera_deg": "setup_camber_rear",
    "convergencia_delantera_deg": "setup_toe_front",
    "convergencia_trasera_deg": "setup_toe_rear",
    "suspension_delantera": "setup_suspension_front",
    "suspension_trasera": "setup_suspension_rear",
    "barra_delantera": "setup_anti_roll_bar_front",
    "barra_trasera": "setup_anti_roll_bar_rear",
    "altura_delantera": "setup_ride_height_front",
    "altura_trasera": "setup_ride_height_rear",
    "presion_de_freno_pct": "setup_brake_pressure",
    "sesgo_de_freno_pct": "setup_brake_bias_front",
    "freno_motor_pct": "setup_engine_braking",
    "presion_neumatico_trasero_izq_psi": "setup_tyre_pressure_rear_left",
    "presion_neumatico_trasero_der_psi": "setup_tyre_pressure_rear_right",
    "presion_neumatico_delantero_izq_psi": "setup_tyre_pressure_front_left",
    "presion_neumatico_delantero_der_psi": "setup_tyre_pressure_front_right",
    "lastre": "setup_ballast",
    "combustible_inicial_kg": "setup_fuel_load",
}


def _motivo_sin_puesta(fuente: str) -> str:
    if fuente == "f1_25_udp_simulation":
        return ("Esta sesion no contiene el paquete de reglaje normalizado; "
                "las capturas anteriores necesitan reinyectarse.")
    return "Esta fuente no publica configuracion del vehiculo."


#: Cuanto se mira hacia atras antes de buscar sin acotar. Dos minutos cubren de
#: sobra el intervalo de cualquier senal que se publique de forma periodica; las
#: que se publican una sola vez caen en el segundo paso.
VENTANA_DE_CONTEXTO_S = 120

#: SENALES QUE UNA SESION GUARDADA NO TIENE.
#:
#: El tercer paso ---buscar sin acotar--- es caro justo cuando **no encuentra
#: nada**: para concluir que una senal no esta hay que recorrer la sesion
#: entera. Y eso se repetia en cada consulta.
#:
#: Que una sesion guardada no publique una senal no cambia: no se van a agregar
#: filas a una carrera que termino. Se recuerda cuales faltan y no se las vuelve
#: a buscar. Con tope y por desuso, como las demas caches de este modulo.
#:
#: Medido el 2026-09-08 sobre `f1_25:session:10802737583091545160`, donde falta
#: la temperatura de pista: 31,42 s -> 20,66 s con la ventana del comienzo, y de
#: ahi a la fraccion de segundo con esto, a partir de la segunda consulta.
_AUSENTES_CACHE: OrderedDict = OrderedDict()
AUSENTES_EN_CACHE = 48


def _iso(v) -> str | None:
    """Una marca de tiempo como texto, venga como `datetime` o ya escrita."""

    if v is None:
        return None
    return v.isoformat() if hasattr(v, "isoformat") else str(v)


def _sumar(instante_iso: str, segundos: int) -> str | None:
    """Suma segundos a una marca ISO. Si no se puede leer, no se acota."""

    try:
        t = datetime.fromisoformat(str(instante_iso))
    except (TypeError, ValueError):
        return None
    return (t + timedelta(seconds=segundos)).isoformat()


def _restar(instante_iso: str, segundos: int) -> str | None:
    """Resta segundos a una marca ISO. Si no se puede leer, no se acota."""

    try:
        t = datetime.fromisoformat(str(instante_iso))
    except (TypeError, ValueError):
        return None
    return (t - timedelta(seconds=segundos)).isoformat()


def _ultimos_valores(cursor, fuente: str, session_id: str, senales: list[str],
                     hasta_utc: str | None = None,
                     ventana_alcance: tuple[str, str] | None = None,
                     vehiculo: str | None = None,
                     limites_fase: tuple[int | None, int | None] = (None, None),
                     ) -> dict[str, float]:
    """Ultimo valor de cada senal **hasta un instante**, o de toda la sesion.

    Se resuelve con una sola consulta y `DISTINCT ON`, que sobre las columnas
    de segmentacion es barato. Una consulta por senal serian cuarenta idas a
    la base para pintar un panel.

    POR QUE HACE FALTA `hasta_utc`.
    -------------------------------
    Sin el, estas consultas contestan siempre con el ultimo valor de la sesion
    entera. Para un panel que acompana una reproduccion eso es sencillamente
    falso: quien mira la vuelta 3 de una carrera que termino con tormenta veia
    «tormenta», y los neumaticos de la vuelta 3 aparecian con el desgaste de la
    vuelta 22. El panel decia el final mientras el cabezal estaba en el medio.

    Con el instante, cada panel contesta lo que la fuente publicaba **en ese
    momento**, que es lo unico que se puede afirmar de un tablero que se
    recorre.
    """
    # EL ESTADO ES DE UN VEHICULO, Y CON UNO SOLO NO SE NOTABA.
    #
    # `DISTINCT ON (signal_name)` sobre la sesion entera devuelve, para cada
    # canal, la fila mas reciente **de cualquier vehiculo**. Con uno solo eso
    # era su estado. Con cuatro es el del que publico ultimo, canal por canal:
    # la temperatura de una goma de uno junto al dano de otro.
    #
    # Medido el 2026-09-10 en Red Bull Ring: Hamilton termino con los dos
    # alerones delanteros al 100 % de dano, 2.974 muestras lo declaran, y el
    # panel decia «sin dano, ninguna pieza lo declara».
    _cv, _cvp = _acotar_al_vehiculo(vehiculo)
    _cf, _cfp = _clausula_de_tramo(*limites_fase)
    if not senales:
        return {}

    # PRIMERO UNA VENTANA CORTA, Y DESPUES LO QUE FALTE.
    #
    # Acotar por arriba no acota: `timestamp <= T` deja igual toda la sesion
    # desde su comienzo, y `DISTINCT ON` tiene que recorrerla para saber cual
    # es la ultima de cada senal. Medido el 2026-09-07, esta consulta era lo
    # mas lento de abrir una sesion: 3,4 s con seis consultas en paralelo.
    #
    # `timestamp` es la dimension por la que la tabla esta particionada, de
    # modo que un limite **inferior** deja fuera los trozos enteros. Casi todas
    # estas senales se publican varias veces por segundo: su ultimo valor antes
    # de T esta a segundos de T.
    #
    # Pero no todas. La puesta a punto se publica al empezar y no se repite, y
    # una ventana la perderia. Por eso son dos pasos y no uno: lo que la
    # ventana no encuentra se busca sin acotar, **solo para esas senales**. No
    # se pierde nada; lo unico que cambia es cuanto se recorre en el caso
    # normal.
    # La cache de ausentes es por sesion, por alcance **y por vehiculo**.
    #
    # Por alcance: una senal que no esta en una adquisicion puede estar en otra,
    # y recordar la ausencia sin el alcance haria que una prueba de parrilla
    # "confirmara" que a la carrera original le falta un canal.
    #
    # Por vehiculo, desde que estas consultas se acotan: de un rival el
    # protocolo no publica clima ni puesta a punto, de modo que preguntarle a el
    # y recordar la ausencia sin decir de quien deja al coche propio marcado
    # como si tampoco los tuviera. Se vio en pantalla: «SIN CLIMA» sobre una
    # sesion cuya API devolvia veinticuatro grados.
    _clave_ausentes = (fuente, session_id, ventana_alcance, vehiculo, limites_fase)
    salida: dict[str, Any] = {}

    def _consultar_ventana(faltan: list[str], desde: str, hasta: str) -> None:
        """Busca en un tramo cerrado, sin el tope general de la funcion."""

        cursor.execute("""
            SELECT DISTINCT ON (signal_name)
                   signal_name, value_numeric, value_boolean, value_text, unit, timestamp
              FROM telemetry_messages
             WHERE source_type = %s AND session_id = %s AND signal_name = ANY(%s)"""
                   + _cv + _cf + """
               AND timestamp >= %s AND timestamp <= %s
               AND (%s::timestamptz IS NULL OR timestamp <= %s)
               AND (%s::timestamptz IS NULL OR timestamp BETWEEN %s AND %s)
             ORDER BY signal_name, timestamp DESC
        """, tuple([fuente, session_id, faltan] + _cvp + _cfp + [desde, hasta,
              hasta_utc, hasta_utc,
              ventana_alcance[0] if ventana_alcance else None,
              ventana_alcance[0] if ventana_alcance else None,
              ventana_alcance[1] if ventana_alcance else None]))
        for nombre, num, boo, txt, unidad, ts in cursor.fetchall():
            valor = num if num is not None else (boo if boo is not None else txt)
            salida[nombre] = {"valor": valor, "unidad": unidad,
                              "instante": ts.isoformat() if ts else None}

    def _consultar(faltan: list[str], desde: str | None) -> None:
        condicion = ""
        parametros: list[Any] = [fuente, session_id, faltan] + _cvp + _cfp
        # El alcance acota siempre, incluso en el paso «sin acotar»: ese paso no
        # acota **por tiempo de sesion**, pero no puede salirse de la
        # adquisicion elegida.
        if ventana_alcance:
            condicion += " AND timestamp BETWEEN %s AND %s"
            parametros.extend([ventana_alcance[0], ventana_alcance[1]])
        if hasta_utc:
            condicion += " AND timestamp <= %s"
            parametros.append(hasta_utc)
        if desde is not None:
            condicion += " AND timestamp >= %s"
            parametros.append(desde)
        cursor.execute("""
            SELECT DISTINCT ON (signal_name)
                   signal_name, value_numeric, value_boolean, value_text, unit, timestamp
              FROM telemetry_messages
             WHERE source_type = %s AND session_id = %s AND signal_name = ANY(%s)"""
                   + _cv + _cf + """""" +
            condicion + """
             ORDER BY signal_name, timestamp DESC
        """, tuple(parametros))
        for nombre, num, boo, txt, unidad, ts in cursor.fetchall():
            valor = num if num is not None else (boo if boo is not None else txt)
            salida[nombre] = {"valor": valor, "unidad": unidad,
                              "instante": ts.isoformat() if ts else None}

    # LOS DOS EXTREMOS DE LA SESION, EN UNA CONSULTA.
    #
    # El maximo hace de tope cuando no se pidio un instante; el minimo abre la
    # ventana del comienzo, que es donde estan las senales que se publican una
    # sola vez. La tabla resuelve los dos con los metadatos de sus trozos.
    #
    # El controlador devuelve `datetime`; un banco de pruebas puede devolver la
    # marca ya escrita. Si no se la puede leer, las ventanas no se aplican y se
    # cae en la consulta sin acotar: se pierde velocidad, nunca el dato.
    # LOS DOS EXTREMOS LOS SABE EL CATALOGO, Y PREGUNTARSELOS A LA TABLA GRANDE
    # ERA LO UNICO LENTO DE ESTE PUNTO DE ACCESO.
    #
    # `min/max(timestamp)` acotado por sesion recorre su particion entera.
    # Medido sobre `openf1:session:9947` ---932.625 filas, dos horas y media---:
    # **26,3 s**, mientras las consultas que de verdad buscan los valores tardan
    # treinta milisegundos. El navegador corta a los treinta segundos, asi que
    # esa sesion no terminaba de abrirse y el clima quedaba en «la consulta no
    # contesto».
    #
    # Con alcance elegido no sirve el catalogo ---sus extremos son los de la
    # sesion entera y no los de esa adquisicion--- pero entonces la consulta va
    # acotada por tiempo, que es la dimension de particion, y es barata.
    if ventana_alcance or _cf:
        condicion_ventana = ""
        parametros_extremos: list[Any] = [fuente, session_id, senales] + _cfp
        if ventana_alcance:
            condicion_ventana = " AND timestamp BETWEEN %s AND %s"
            parametros_extremos.extend(ventana_alcance)
        cursor.execute("""
            SELECT min(timestamp), max(timestamp) FROM telemetry_messages
             WHERE source_type = %s AND session_id = %s
               AND signal_name = ANY(%s)""" + _cf + condicion_ventana,
            tuple(parametros_extremos))
        fila = cursor.fetchone()
        piso = _iso(fila[0]) if fila else None
        fin = _iso(fila[1]) if fila else None
    else:
        piso, fin = catalogo_sesiones.extremos_de(session_id, fuente, cursor)
    tope = hasta_utc if hasta_utc is not None else fin

    if tope is not None:
        _consultar(senales, _restar(tope, VENTANA_DE_CONTEXTO_S))

    # SEGUNDO INTENTO: EL COMIENZO DE LA SESION.
    #
    # Lo que la ventana reciente no encuentra suele ser una senal que se
    # publica **una sola vez, al empezar**: la puesta a punto, el circuito, el
    # tipo de sesion. Buscarla en los primeros dos minutos cuesta lo mismo que
    # buscarla en los ultimos, y evita el recorrido completo.
    #
    # Medido el 2026-09-08: sin este paso, `/contexto` de
    # `f1_25:session:10802737583091545160` tardaba **31,42 s**, justo por
    # encima del corte de 30 s del navegador, de modo que se anulaba siempre y
    # esa sesion no terminaba de abrirse nunca.
    faltantes = [x for x in senales if x not in salida]
    if faltantes and piso is not None:
        _consultar_ventana(faltantes, piso, _sumar(piso, VENTANA_DE_CONTEXTO_S))

    # TERCER INTENTO: sin acotar, solo para lo que siga faltando. Es caro y por
    # eso es el ultimo, pero tiene que estar: sin el, una senal publicada a
    # mitad de sesion y nunca mas se perderia, y perder un dato para ir mas
    # rapido no es una opcion.
    faltantes = [x for x in senales if x not in salida]
    if faltantes:
        conocidas_ausentes = _AUSENTES_CACHE.get(_clave_ausentes) or set()
        por_buscar = [x for x in faltantes if x not in conocidas_ausentes]
        if por_buscar:
            _consultar(por_buscar, None)
            # Lo que ni asi aparecio, no esta en esta sesion.
            nuevas = {x for x in por_buscar if x not in salida}
            if nuevas:
                clave_c = _clave_ausentes
                _AUSENTES_CACHE[clave_c] = conocidas_ausentes | nuevas
                _AUSENTES_CACHE.move_to_end(clave_c)
                while len(_AUSENTES_CACHE) > AUSENTES_EN_CACHE:
                    _AUSENTES_CACHE.popitem(last=False)
    return salida


@router.get("/sesiones/{session_id}/vehiculo")
def estado_del_vehiculo(
        session_id: str,
        hasta: Annotated[str | None, Query(
            description="Instante ISO-8601: estado del vehiculo vigente hasta ahi")] = None,
        vehiculo: Annotated[str | None, Query(
            description="De que vehiculo; por omision, el de quien conduce")] = None,
        ) -> dict[str, Any]:
    """Neumaticos, frenos y dano, por esquina y por pieza.

    Devuelve el ultimo valor persistido de cada canal. Los canales que la
    fuente no tiene **no se omiten**: figuran en `ausentes`, porque saber que
    algo no se midio es tan util como el valor de lo que si.
    """
    fuente = _fuente_de(session_id)
    pedidas = []
    for plantilla in CANALES_POR_ESQUINA.values():
        pedidas += [plantilla % e for e in ESQUINAS]
    pedidas += list(CANALES_CARROCERIA.values())

    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        # Sin decir cual, el de quien conduce. Mirar a un rival es una pregunta
        # legitima ---hoy hay datos suyos--- pero hay que pedirla.
        de_quien = vehiculo or _vehiculo_propio(cursor, fuente, session_id)
        valores = _ultimos_valores(cursor, fuente, session_id, pedidas, hasta,
                                   vehiculo=de_quien)

    esquinas: dict[str, dict] = {}
    for e in ESQUINAS:
        datos = {}
        for clave, plantilla in CANALES_POR_ESQUINA.items():
            v = valores.get(plantilla % e)
            if v is not None:
                datos[clave] = v["valor"]
        if datos:
            esquinas[e] = datos

    carroceria = {}
    for clave, canal in CANALES_CARROCERIA.items():
        v = valores.get(canal)
        if v is not None:
            carroceria[clave] = v["valor"]

    ausentes = [c for c in pedidas if c not in valores]
    return {
        "session_id": session_id,
        "fuente": fuente,
        "esquinas": esquinas,
        "carroceria": carroceria,
        "ausentes": ausentes,
        "motivo_ausencia": (
            "Esta fuente no publica estado de neumaticos ni de daño."
            if not esquinas and not carroceria else None
        ),
    }


# Unidades del reglaje declarado. A diferencia del estado operativo que ocupaba
# antes este panel, ningun campo es un codigo sin interpretar.
UNIDADES_PUESTA_A_PUNTO = {
    clave: {"unidad": unidad, "decodificado": True}
    for clave, unidad in {
        "aleron_delantero": "nivel", "aleron_trasero": "nivel",
        "diferencial_con_acelerador_pct": "%",
        "diferencial_sin_acelerador_pct": "%",
        "caida_delantera_deg": "deg", "caida_trasera_deg": "deg",
        "convergencia_delantera_deg": "deg", "convergencia_trasera_deg": "deg",
        "suspension_delantera": "nivel", "suspension_trasera": "nivel",
        "barra_delantera": "nivel", "barra_trasera": "nivel",
        "altura_delantera": "nivel", "altura_trasera": "nivel",
        "presion_de_freno_pct": "%", "sesgo_de_freno_pct": "%",
        "freno_motor_pct": "%",
        "presion_neumatico_trasero_izq_psi": "psi",
        "presion_neumatico_trasero_der_psi": "psi",
        "presion_neumatico_delantero_izq_psi": "psi",
        "presion_neumatico_delantero_der_psi": "psi",
        "lastre": "nivel", "combustible_inicial_kg": "kg",
    }.items()
}


def _armar_puesta_a_punto(valores: dict[str, dict]) -> tuple[dict, list, str | None, bool]:
    """Reconstruye un paquete completo sin mezclar instantes."""

    datos, campos, instantes = {}, [], set()
    for clave, canal in CANALES_PUESTA_A_PUNTO.items():
        v = valores.get(canal)
        if v is None:
            continue
        datos[clave] = v["valor"]
        meta = UNIDADES_PUESTA_A_PUNTO[clave]
        campos.append({"clave": clave, "canal": canal, "valor": v["valor"],
                       "unidad": meta["unidad"], "decodificado": True,
                       "instante": v.get("instante")})
        if v.get("instante") is not None:
            instantes.add(v["instante"])
    completa = len(datos) == len(CANALES_PUESTA_A_PUNTO) and len(instantes) == 1
    instante = next(iter(instantes)) if completa else None
    return datos, campos, instante, completa


def _hay_rodaje_despues(cursor, fuente: str, session_id: str,
                        vehiculo: str | None, desde: str,
                        hasta: str | None = None,
                        ventana: tuple[str, str] | None = None,
                        limites_fase: tuple[int | None, int | None] = (None, None),
                        ) -> bool:
    """Confirma que el reglaje observado llego a una vuelta conducida."""

    cv, pv = _acotar_al_vehiculo(vehiculo)
    cf, pf = _clausula_de_tramo(*limites_fase)
    condicion_ventana = " AND timestamp BETWEEN %s AND %s" if ventana else ""
    parametros = [fuente, session_id] + pv + pf + list(ventana or ()) + [desde,
                  hasta, hasta]
    cursor.execute("""
        SELECT EXISTS (
            SELECT 1 FROM telemetry_messages
             WHERE source_type = %s AND session_id = %s
               AND signal_name = 'speed' AND value_numeric > 0""" + cv + cf + condicion_ventana + """
               AND timestamp > %s
               AND (%s::timestamptz IS NULL OR timestamp <= %s)
             LIMIT 1)
    """, tuple(parametros))
    fila = cursor.fetchone()
    return bool(fila and fila[0])


def _comparar_con_referencia(session_id: str, puesta: dict,
                             asentada: bool) -> tuple[dict | None, list[dict]]:
    procedencia = procedencia_sesiones.de(session_id) or {}
    referencia = catalogo_reglajes.referencia_de(procedencia.get("circuito"))
    diferencias = []
    if referencia and asentada:
        for clave, esperado in referencia["valores"].items():
            if clave not in puesta:
                continue
            aplicado = puesta[clave]
            diferencias.append({"clave": clave, "aplicado": aplicado,
                                "referencia": esperado,
                                "diferencia": aplicado - esperado})
    return referencia, diferencias


@router.get("/sesiones/{session_id}/puesta-a-punto")
def puesta_a_punto(
        session_id: str,
        hasta: Annotated[str | None, Query(
            description="Instante ISO-8601: la configuracion vigente hasta ahi")] = None,
        ) -> dict[str, Any]:
    """Reglaje observado y confirmacion de que luego se condujo con el.

    El menu publica valores intermedios. Por eso observar un paquete no alcanza:
    se lo llama `asentado` solamente si sus veintitres señales pertenecen al
        mismo instante y existe una muestra posterior con el vehiculo en marcha.
    """
    fuente = _fuente_de(session_id)
    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        propio = _vehiculo_propio(cursor, fuente, session_id)
        valores = _ultimos_valores(cursor, fuente, session_id,
                                   list(CANALES_PUESTA_A_PUNTO.values()), hasta,
                                   vehiculo=propio)
        datos, campos, instante, completa = _armar_puesta_a_punto(valores)
        asentada = bool(completa and _hay_rodaje_despues(
            cursor, fuente, session_id, propio, instante, hasta))
    referencia, diferencias = _comparar_con_referencia(
        session_id, datos, asentada)
    return {
        "session_id": session_id,
        "fuente": fuente,
        "puesta_a_punto": datos,
        "campos": campos,
        "completa": completa,
        "asentada": asentada,
        "instante_observado": instante,
        "referencia": referencia,
        "diferencias": diferencias,
        "criterio": ("paquete completo observado antes de una muestra posterior "
                     "con velocidad positiva: configuracion llevada a la pista"),
        "sin_decodificar": [],
        "motivo_ausencia": None if datos else _motivo_sin_puesta(fuente),
    }


# --------------------------------------------------------------------------
# 6. Clima
# --------------------------------------------------------------------------

CANALES_CLIMA = {
    "temperatura_aire_c": "air_temperature",
    "temperatura_pista_c": "track_temperature",
    "codigo_de_clima": "weather_code",
    "bandera": "fia_flag",
    "retraso_del_coche_de_seguridad_s": "safety_car_delta",
}

CLIMA_TEXTO = {0: "despejado", 1: "nubes ligeras", 2: "nublado",
               3: "lluvia ligera", 4: "lluvia intensa", 5: "tormenta"}
BANDERA_TEXTO = {-1: "sin dato", 0: "ninguna", 1: "verde",
                 2: "azul", 3: "amarilla", 4: "roja"}


def _senales_del_vehiculo() -> list[str]:
    """Los canales que describen al coche y no a la sesion.

    Se derivan de los mismos mapas que arma el panel, no de una lista aparte:
    una segunda copia se desactualiza el dia que se agregue una esquina.
    """

    pedidas = []
    for plantilla in CANALES_POR_ESQUINA.values():
        pedidas += [plantilla % e for e in ESQUINAS]
    return pedidas + list(CANALES_CARROCERIA.values())


@router.get("/sesiones/{session_id}/contexto")
def contexto(
        session_id: str,
        adquisicion: Annotated[str | None, Query()] = None,
        fase: Annotated[int | None, Query(ge=1)] = None,
        hasta: Annotated[str | None, Query(
            description="Instante ISO-8601: el contexto vigente hasta ahi")] = None,
        vehiculo: Annotated[str | None, Query(
            description="De que vehiculo es el estado; por omision, el de quien "
                        "conduce. El clima y la puesta a punto no cambian: son "
                        "de la sesion")] = None,
        ) -> dict[str, Any]:
    """Clima, estado del vehiculo y puesta a punto **en una sola consulta**.

    POR QUE EXISTE. Los tres se piden juntos y siempre al mismo instante: son
    el contexto del punto que se esta mirando. Pedirlos por separado eran tres
    idas a la base y tres viajes de red para resolver la misma pregunta, y en
    un tablero que se recorre eso ocurre en cada cambio de vuelta.

    Medido el 2026-09-07 sobre la sesion de 5.641.702 filas: 0,45 + 0,85 + 0,41
    segundos por separado; una sola consulta sobre la union de las señales
    ---que son las mismas columnas de segmentacion--- resuelve lo mismo.

    No es una ruta de conveniencia: las tres respuestas **tienen que ser del
    mismo instante**. Pedidas por separado pueden diferir si una tarda mas que
    otra, y entonces el panel mostraria el clima de un momento y el neumatico
    de otro.
    """
    fuente = _fuente_de(session_id)
    senales = senales_de_contexto()

    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        # El clima y el estado del vehiculo son de una adquisicion concreta: los
        # de la carrera original no son los de una prueba de parrilla corrida
        # tres dias despues.
        _cv = _ventana_de_alcance(cursor, fuente, session_id, adquisicion)
        _lf = _limites_de_fase(cursor, fuente, session_id, adquisicion, fase)
        # DE QUIEN ES CADA PARTE.
        #
        # `DISTINCT ON (signal_name)` sin acotar el vehiculo devuelve, por cada
        # canal, la fila mas reciente de cualquiera. Con un vehiculo capturado
        # eso era su estado; con cuatro es el del que publico ultimo, canal por
        # canal. Por eso el panel mostraba las cuatro esquinas identicas y «sin
        # dano» sobre un coche que termino con los dos alerones rotos.
        #
        # El clima es de la sesion y el reglaje es telemetria privada del propio.
        # Ambos llegan atados a su identificador porque toda fila canonica exige
        # vehiculo. Por eso la consulta base va siempre acotada al propio, y solo
        # cuando se pide otro se reemplazan sus canales fisicos. Mirar a un rival
        # no tiene por que costar ni el clima ni el reglaje propio.
        propio = _vehiculo_propio(cursor, fuente, session_id)
        valores = _ultimos_valores(cursor, fuente, session_id, senales, hasta,
                                   ventana_alcance=_cv, vehiculo=propio,
                                   limites_fase=_lf)
        if vehiculo and vehiculo != propio:
            del_otro = _ultimos_valores(cursor, fuente, session_id,
                                        _senales_del_vehiculo(), hasta,
                                        ventana_alcance=_cv, vehiculo=vehiculo,
                                        limites_fase=_lf)
            valores = {**valores, **del_otro}
        puesta, campos, instante_puesta, completa = _armar_puesta_a_punto(valores)
        asentada = bool(completa and _hay_rodaje_despues(
            cursor, fuente, session_id, propio, instante_puesta, hasta,
            ventana=_cv, limites_fase=_lf))

    clima = {}
    for clave, canal in CANALES_CLIMA.items():
        v = valores.get(canal)
        if v is not None:
            clima[clave] = v["valor"]
    if "codigo_de_clima" in clima:
        clima["clima"] = CLIMA_TEXTO.get(int(clima["codigo_de_clima"]), "desconocido")
    if "bandera" in clima:
        clima["bandera_texto"] = BANDERA_TEXTO.get(int(clima["bandera"]), "desconocida")

    esquinas: dict[str, dict] = {}
    for e in ESQUINAS:
        datos = {}
        for clave, plantilla in CANALES_POR_ESQUINA.items():
            v = valores.get(plantilla % e)
            if v is not None:
                datos[clave] = v["valor"]
        if datos:
            esquinas[e] = datos

    carroceria = {}
    for clave, canal in CANALES_CARROCERIA.items():
        v = valores.get(canal)
        if v is not None:
            carroceria[clave] = v["valor"]

    referencia, diferencias = _comparar_con_referencia(
        session_id, puesta, asentada)

    return {
        "session_id": session_id,
        "fuente": fuente,
        "hasta": hasta,
        "clima": clima or None,
        "clima_motivo": None if clima else "Esta fuente no publica clima ni estado de pista.",
        "esquinas": esquinas,
        "carroceria": carroceria,
        "vehiculo_motivo": (None if (esquinas or carroceria)
                            else "Esta fuente no publica estado de neumaticos ni de daño."),
        "puesta_a_punto": puesta,
        "campos": campos,
        "puesta_completa": completa,
        "puesta_asentada": asentada,
        "puesta_instante_observado": instante_puesta,
        "referencia_puesta": referencia,
        "diferencias_puesta": diferencias,
        "puesta_motivo": None if puesta else _motivo_sin_puesta(fuente),
        "sin_decodificar": [],
        "criterio": ("ultimo valor de cada señal hasta el instante pedido; "
                     "el reglaje solo se declara asentado si despues se rodo"),
    }


@router.get("/sesiones/{session_id}/clima")
def clima(session_id: str,
          hasta: Annotated[str | None, Query(
              description="Instante ISO-8601: devuelve el clima vigente hasta ahi")] = None,
          ) -> dict[str, Any]:
    """Clima y estado de pista **en un instante** de la sesion.

    Sin `hasta` devuelve el ultimo de la sesion, que es lo correcto para un
    panel estatico. Con `hasta` devuelve el que estaba vigente en ese momento,
    que es lo que necesita un tablero que se recorre: una carrera que empieza
    seca y termina en tormenta tiene dos climas, y decir siempre el segundo es
    decir algo falso durante las tres cuartas partes de la reproduccion.
    """
    fuente = _fuente_de(session_id)
    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        valores = _ultimos_valores(cursor, fuente, session_id,
                                   list(CANALES_CLIMA.values()), hasta)

    datos = {}
    for clave, canal in CANALES_CLIMA.items():
        v = valores.get(canal)
        if v is not None:
            datos[clave] = v["valor"]

    if "codigo_de_clima" in datos:
        datos["clima"] = CLIMA_TEXTO.get(int(datos["codigo_de_clima"]), "desconocido")
    if "bandera" in datos:
        datos["bandera_texto"] = BANDERA_TEXTO.get(int(datos["bandera"]), "desconocida")

    return {
        "session_id": session_id,
        "fuente": fuente,
        "clima": datos,
        "motivo_ausencia": None if datos else (
            "El clima no viaja en la telemetria de esta fuente; llega por el "
            "contexto de sesion, aparte."),
    }


# --------------------------------------------------------------------------
# 7. Avisos de una sesion guardada
# --------------------------------------------------------------------------

#: Cada aviso declara el canal que lo dispara y el umbral con que se dispara.
#: Un aviso es una afirmacion, y una afirmacion sin su origen no se puede
#: discutir. Una condicion que no se cumple con claridad no se anota: anotar
#: de mas es peor que no anotar.
REGLAS_DE_AVISO = [
    {"canal": "floor_damage", "umbral": 1.0, "nivel": "critico",
     "que": "Piso danado", "unidad": "%"},
    {"canal": "diffuser_damage", "umbral": 1.0, "nivel": "critico",
     "que": "Difusor danado", "unidad": "%"},
    {"canal": "wing_damage_front_left", "umbral": 1.0, "nivel": "alerta",
     "que": "Ala delantera izquierda danada", "unidad": "%"},
    {"canal": "wing_damage_front_right", "umbral": 1.0, "nivel": "alerta",
     "que": "Ala delantera derecha danada", "unidad": "%"},
    {"canal": "wing_damage_rear", "umbral": 1.0, "nivel": "alerta",
     "que": "Ala trasera danada", "unidad": "%"},
    {"canal": "sidepod_damage", "umbral": 1.0, "nivel": "alerta",
     "que": "Ponton danado", "unidad": "%"},
    {"canal": "gearbox_damage", "umbral": 1.0, "nivel": "critico",
     "que": "Caja de cambios danada", "unidad": "%"},
    {"canal": "engine_damage", "umbral": 1.0, "nivel": "critico",
     "que": "Motor danado", "unidad": "%"},
    {"canal": "engine_blown", "umbral": 0.5, "nivel": "critico",
     "que": "Motor roto", "unidad": ""},
    {"canal": "ers_fault", "umbral": 0.5, "nivel": "critico",
     "que": "Fallo de ERS", "unidad": ""},
    {"canal": "drs_fault", "umbral": 0.5, "nivel": "alerta",
     "que": "Fallo de DRS", "unidad": ""},
    {"canal": "lap_invalid", "umbral": 0.5, "nivel": "info",
     "que": "Vuelta invalidada", "unidad": ""},
    {"canal": "penalty_time", "umbral": 0.5, "nivel": "alerta",
     "que": "Penalizacion de tiempo", "unidad": "s"},
    {"canal": "warnings_total", "umbral": 0.5, "nivel": "info",
     "que": "Aviso por limites de pista", "unidad": ""},
]

#: LA TABLA DE SUPERFICIES SE LEE DEL DECODIFICADOR, NO SE COPIA.
#:
#: Aca habia una copia, sin usar en ninguna parte y **corrida**: declaraba 2 como
#: grava cuando 2 es hormigon, 4 como tierra cuando 4 es grava, 6 como cesped
#: artificial cuando 6 es arena. Y le faltaba el 7, que es el cesped, o sea la
#: superficie sobre la que se sale de pista casi siempre: en una sesion de Abu
#: Dabi son 508 muestras.
#:
#: Una segunda tabla del mismo hecho no se mantiene sola, y esta lo demostro. La
#: unica que vale es `f1_udp.SUPERFICIES`, que es la que ya usa el anotador en
#: vivo, de modo que las dos lecturas ---la de en vivo y la de despues--- hablan
#: del mismo mundo.

#: Fuera de pista, segun el articulo 33.3 del reglamento deportivo: ninguna
#: parte del vehiculo en contacto con la pista, y **el piano no es pista**. Es
#: la misma regla que aplica `backend/anotador_vivo.py` sobre el flujo en vivo;
#: estaba solo alli, de modo que una sesion mirada en vivo anotaba salidas que
#: la misma sesion reproducida no mostraba.
REGLA_FUERA_DE_PISTA = {
    "que": "Fuera de pista",
    "nivel": "alerta",
    "canal": "surface_type_*",
    "umbral": "las cuatro ruedas sobre superficie que no es asfalto",
}


#: Los avisos de una sesion guardada no cambian: recorren la sesion entera
#: buscando el primer instante en que se cumple cada condicion, y eso costo
#: 4,25 s medidos el 2026-09-07. Se guarda el resultado por sesion para que
#: reabrirla sea inmediato. La clave incluye el umbral, que es parametro.
#:
#: El tamano tiene tope. Un proceso que corre semanas en la Raspberry con 258
#: sesiones en el catalogo terminaria guardando las 258 respuestas; se queda con
#: las ultimas que se pidieron, que son las que alguien esta mirando.
_AVISOS_CACHE: OrderedDict = OrderedDict()
AVISOS_EN_CACHE = 24


#: TROMPO: LOS TRES A LA VEZ, Y QUE DURE.
#:
#: Calibrado contra un trompo real ---dos, en verdad--- de la sesion de Bahrein
#: del 2026-09-10, vuelta 7. La firma medida en el metro 2.765: el giro llega a
#: 3,05 rad/s mientras el volante esta en -1,00, o sea a tope **al reves**, el
#: eje trasero desliza 8,13 y la velocidad cae de 92 a 29 km/h. El segundo, en
#: el metro 4.197, cae de 117 a 12 km/h.
#:
#: NINGUNA DE LAS TRES CONDICIONES ALCANZA SOLA:
#:
#: * el giro alto tambien lo produce una horquilla lenta;
#: * el deslizamiento trasero solo, con el volante acompanando, es la
#:   sobreviraje normal que la regla de tren trasero ya anota;
#: * **el contravolante es lo que distingue**: el coche rota hacia un lado y el
#:   volante esta hacia el otro. Eso no ocurre trazando.
#:
#: Y que dure. Medido sobre las seis sesiones capturadas: con las tres
#: condiciones, la de Bahrein da 71 muestras y las otras cinco dan cero, salvo
#: Monaco con **una sola**. Los episodios de Bahrein llegan a veintitres
#: muestras seguidas; el de Monaco y uno suelto duran una. Un trompo dura, un
#: tiron no, y tres muestras ---unos 150 ms a 20 Hz--- los separan sin tocar
#: ninguno de los episodios reales.
UMBRAL_GIRO_TROMPO = 1.5
MINIMO_MUESTRAS_TROMPO = 3

#: EL ANOTADOR MIRA LA SENAL CRUDA; ESTAS REGLAS MIRAN LA GUARDADA.
#:
#: No estan en la misma escala, y ahi se cometio el error. El adaptador publica
#: el acelerador y el freno **multiplicados por cien**, porque los declara en
#: por ciento; el anotador en vivo los evalua antes de eso, sobre la fraccion de
#: cero a uno que entrega el juego. Importar el umbral del anotador y
#: compararlo contra la columna guardada ---que es lo que hacia la regla de tren
#: trasero--- convertia "acelerador sobre el 50 %" en "acelerador sobre el
#: 0,5 %": el pedal apenas tocado alcanzaba, de modo que la condicion que debia
#: separar el deslizamiento acelerando del deslizamiento al frenar no separaba
#: nada. El texto del umbral decia una cosa y la consulta hacia otra.
#:
#: Por eso estos dos viven aca con el sufijo de su unidad, y una prueba fija la
#: conversion contra el factor que declara el adaptador. Los demas
#: ---deslizamiento, giro, fuerza vertical--- se guardan con factor 1,0 y se
#: siguen importando del anotador tal cual.
UMBRAL_ACELERADOR_PCT = 50.0
UMBRAL_FRENO_SUELTO_PCT = anotador_vivo.UMBRAL_FRENO_SUELTO * 100.0

#: Las reglas fisicas que el anotador en vivo evalua sobre el flujo, escritas
#: para pedirselas a una sesion guardada.
#:
#: LOS UMBRALES SE IMPORTAN, NO SE COPIAN. Estan calibrados en
#: `backend/anotador_vivo.py` contra vueltas reales, y una segunda copia se
#: desincroniza sin que nadie lo note ---en este mismo archivo habia una tabla
#: de superficies duplicada y equivocada en todas sus entradas---. Que las dos
#: lecturas usen el mismo numero es lo que hace que una sesion mirada en vivo y
#: la misma reproducida digan lo mismo.
#:
#: La medicion que respalda el umbral de deslizamiento: sobre 47.481 muestras,
#: el deslizamiento trasero tiene mediana 0,02 y percentil 99 entre 0,18 y 0,22.
#: El umbral de 0,25 queda apenas por encima de lo que ocurre normalmente, que
#: es lo que se le pide a un umbral.
REGLAS_FISICAS = [
    {
        "que": "Perdida de tren trasero",
        "nivel": "alerta",
        "canal": "wheel_slip_ratio_rear_*",
        "umbral": ("deslizamiento trasero sobre %.2f con el acelerador sobre %.0f %%"
                   % (anotador_vivo.UMBRAL_DESLIZAMIENTO, UMBRAL_ACELERADOR_PCT)),
        "unidad": "%",
    },
    {
        "que": "Trompo",
        "nivel": "critico",
        "canal": "yaw_rate + steering_normalized + wheel_slip_ratio_rear_*",
        "umbral": ("giro sobre %.1f rad/s contra el volante, con el tren trasero "
                   "deslizando, durante al menos %d muestras seguidas"
                   % (UMBRAL_GIRO_TROMPO, MINIMO_MUESTRAS_TROMPO)),
        "unidad": "rad/s",
    },
    {
        "que": "Impacto vertical",
        "nivel": "alerta",
        "canal": "g_force_vertical",
        "umbral": "%.1f g" % anotador_vivo.UMBRAL_VERTICAL_G,
        "unidad": "g",
    },
    {
        "que": "Caida brusca de velocidad",
        "nivel": "alerta",
        "canal": "speed + brake_position",
        "umbral": ("mas de %.0f km/h perdidos en %.1f s con el freno bajo el "
                   "%.0f %% durante toda la ventana"
                   % (anotador_vivo.UMBRAL_CAIDA_KMH,
                      anotador_vivo.VENTANA_CAIDA_S, UMBRAL_FRENO_SUELTO_PCT)),
        "unidad": "km/h",
    },
]


def _vehiculo_propio(cursor, fuente: str, session_id: str) -> str | None:
    """El vehiculo de quien conduce, **declarado** por el flujo y no inferido.

    Se lee de `player_car_index`, que el paquete de cabecera trae en cada
    mensaje y el adaptador copia al metadato. Se podria adivinar por que
    vehiculo tiene `yaw_rate` ---`motion_ex` describe solo al propio--- pero eso
    seria deducir del sintoma lo que la fuente ya dice con todas las letras, y
    dejaria de funcionar el dia que se publique otro paquete privado.

    Devuelve `None` cuando la sesion no lo declara. Con las capturas viejas, de
    un solo vehiculo, eso no cambia nada: donde hay uno el promedio de uno es
    ese uno.
    """

    cursor.execute("""
        SELECT metadata->'extra'->>'player_car_index'
          FROM telemetry_messages
         WHERE source_type = %s AND session_id = %s
           AND metadata->'extra'->>'player_car_index' IS NOT NULL
         LIMIT 1
    """, (fuente, session_id))
    fila = cursor.fetchone()
    if not fila or fila[0] is None:
        return None
    try:
        return FORMA_DEL_VEHICULO % (session_id, int(fila[0]))
    except (TypeError, ValueError):
        return None


#: UN AVISO ES DE UN VEHICULO, Y CON UNO SOLO NO SE NOTABA.
#:
#: Todas las reglas giran la tabla larga a una fila por instante con
#: `max(value_numeric) FILTER (WHERE signal_name = ...)`. Con **un** vehiculo
#: capturado ese `max` es el unico valor que hay. Con cuatro toma el mayor de
#: los cuatro por cada canal por separado: el giro de uno con el volante de otro
#: y el deslizamiento de un tercero. **Eso no describe a ningun coche**, y el
#: aviso que sale de ahi afirma algo que no ocurrio.
#:
#: Estuvo latente desde el principio y aparecio el 2026-09-10, en la primera
#: carrera con la parrilla acotada a cuatro. Un defecto que solo se ve con datos
#: que todavia no existian es un defecto igual.
def _acotar_al_vehiculo(vehiculo: str | None) -> tuple[str, list]:
    """La clausula y su parametro, o nada cuando no se sabe a quien acotar.

    Sin saber cual es el propio **no se acota, y no se calla**: con un unico
    vehiculo la lectura sigue siendo correcta, y devolver cero avisos por no
    poder acotar seria peor que devolverlos como se venian devolviendo.
    """

    return ("", []) if vehiculo is None else (" AND vehicle_id = %s", [vehiculo])


def _primera_perdida_de_tren_trasero(cursor, fuente: str, session_id: str,
                                    vehiculo: str | None = None,
                                    alcance: tuple[str, tuple] = ("", ())):
    """El primer instante en que el eje trasero desliza **acelerando**.

    El acelerador esta en la regla y no de adorno: el deslizamiento solo por si
    mismo aparece tambien al frenar fuerte y en cada cambio de apoyo, y llamar a
    eso perdida de tren trasero seria anotar la conduccion normal. Es la misma
    condicion que el anotador evalua sobre el flujo.
    """

    _clausula, _par = _acotar_al_vehiculo(vehiculo)
    _ca, _pa = alcance
    cursor.execute("""
        WITH p AS (
            SELECT timestamp,
                   max(value_numeric) FILTER (WHERE signal_name = 'wheel_slip_ratio_rear_left')  AS izq,
                   max(value_numeric) FILTER (WHERE signal_name = 'wheel_slip_ratio_rear_right') AS der,
                   max(value_numeric) FILTER (WHERE signal_name = 'throttle_position')           AS acelerador,
                   max(value_numeric) FILTER (WHERE signal_name = 'lap_number')   AS vuelta,
                   max(value_numeric) FILTER (WHERE signal_name = 'lap_distance') AS metro
              FROM telemetry_messages
             WHERE source_type = %s AND session_id = %s
               AND signal_name = ANY(%s)""" + _clausula + _ca + """
             GROUP BY timestamp)
        SELECT vuelta, metro, greatest(abs(izq), abs(der)) AS peor, timestamp FROM p
         WHERE izq IS NOT NULL AND der IS NOT NULL AND acelerador IS NOT NULL
           AND greatest(abs(izq), abs(der)) > %s AND acelerador > %s
         ORDER BY timestamp LIMIT 1
    """, (fuente, session_id,
          ["wheel_slip_ratio_rear_left", "wheel_slip_ratio_rear_right",
           "throttle_position", "lap_number", "lap_distance"],
           *_par,
           *_pa,
           anotador_vivo.UMBRAL_DESLIZAMIENTO, UMBRAL_ACELERADOR_PCT))
    return cursor.fetchone()


def _primer_trompo(cursor, fuente: str, session_id: str,
                  vehiculo: str | None = None,
                  alcance: tuple[str, tuple] = ("", ())):
    """El primer trompo: giro contra el volante, tren trasero fuera, y que dure.

    LA DURACION SE MIDE CON EL RELOJ Y NO CONTANDO FILAS. Dos muestras seguidas
    en el orden no son dos muestras seguidas en el tiempo si entre ellas hubo un
    hueco de captura ---los hay, de minutos, cuando el juego pasa por el menu---
    y un trompo partido por ese hueco no es un trompo mas largo. Un corte de mas
    de tres decimas separa episodios; a veinte muestras por segundo, lo seguido
    llega cada cinco centesimas.
    """

    _clausula, _par = _acotar_al_vehiculo(vehiculo)
    _ca, _pa = alcance
    cursor.execute("""
        WITH p AS (
            SELECT timestamp,
                   max(value_numeric) FILTER (WHERE signal_name = 'yaw_rate')            AS giro,
                   max(value_numeric) FILTER (WHERE signal_name = 'steering_normalized') AS volante,
                   greatest(
                     abs(max(value_numeric) FILTER (WHERE signal_name = 'wheel_slip_ratio_rear_left')),
                     abs(max(value_numeric) FILTER (WHERE signal_name = 'wheel_slip_ratio_rear_right'))
                   ) AS desliz,
                   max(value_numeric) FILTER (WHERE signal_name = 'lap_number')   AS vuelta,
                   max(value_numeric) FILTER (WHERE signal_name = 'lap_distance') AS metro
              FROM telemetry_messages
             WHERE source_type = %s AND session_id = %s
               AND signal_name = ANY(%s)""" + _clausula + _ca + """
             GROUP BY timestamp),
        q AS (
            SELECT * FROM p
             WHERE giro IS NOT NULL AND volante IS NOT NULL AND desliz IS NOT NULL
               AND giro * volante < 0 AND abs(giro) > %s AND desliz > %s),
        d AS (
            SELECT *, CASE WHEN timestamp - lag(timestamp) OVER (ORDER BY timestamp)
                                > interval '300 milliseconds'
                           THEN 1 ELSE 0 END AS corte
              FROM q),
        i AS (SELECT *, sum(corte) OVER (ORDER BY timestamp) AS isla FROM d),
        c AS (
            SELECT isla, count(*) AS muestras, min(timestamp) AS empieza,
                   max(abs(giro)) AS giro_maximo
              FROM i GROUP BY isla HAVING count(*) >= %s)
        SELECT i.vuelta, i.metro, c.giro_maximo, c.empieza, c.muestras
          FROM c JOIN i ON i.isla = c.isla AND i.timestamp = c.empieza
         ORDER BY c.empieza LIMIT 1
    """, (fuente, session_id,
          ["yaw_rate", "steering_normalized",
           "wheel_slip_ratio_rear_left", "wheel_slip_ratio_rear_right",
           "lap_number", "lap_distance"],
           *_par,
           *_pa,
           UMBRAL_GIRO_TROMPO, anotador_vivo.UMBRAL_DESLIZAMIENTO,
          MINIMO_MUESTRAS_TROMPO))
    return cursor.fetchone()


def _primer_impacto_vertical(cursor, fuente: str, session_id: str,
                            vehiculo: str | None = None,
                            alcance: tuple[str, tuple] = ("", ())):
    """El primer golpe vertical, mirando el valor absoluto.

    **En valor absoluto y no por el maximo**, que es lo que las reglas de canal
    contra umbral hacen: un golpe hacia abajo llega como negativo y aquellas
    nunca lo verian.
    """

    _clausula, _par = _acotar_al_vehiculo(vehiculo)
    _ca, _pa = alcance
    cursor.execute("""
        WITH p AS (
            SELECT timestamp,
                   max(value_numeric) FILTER (WHERE signal_name = 'g_force_vertical') AS g,
                   max(value_numeric) FILTER (WHERE signal_name = 'lap_number')   AS vuelta,
                   max(value_numeric) FILTER (WHERE signal_name = 'lap_distance') AS metro
              FROM telemetry_messages
             WHERE source_type = %s AND session_id = %s
               AND signal_name = ANY(%s)""" + _clausula + _ca + """
             GROUP BY timestamp)
        SELECT vuelta, metro, g, timestamp FROM p
         WHERE g IS NOT NULL AND abs(g) > %s
         ORDER BY timestamp LIMIT 1
    """, (fuente, session_id,
           ["g_force_vertical", "lap_number", "lap_distance"],
           *_par,
           *_pa,
           anotador_vivo.UMBRAL_VERTICAL_G))
    return cursor.fetchone()


def _primera_caida_brusca(cursor, fuente: str, session_id: str,
                         vehiculo: str | None = None,
                         alcance: tuple[str, tuple] = ("", ())):
    """La primera perdida grande de velocidad **sin frenar**, sobre una ventana.

    Es la tercera regla del anotador en vivo y la unica de las suyas que no cabe
    en la forma "un canal contra un umbral": no pregunta cuanto vale la
    velocidad ahora sino **cuanto cayo en medio segundo**. Por eso quedo afuera
    cuando se trajeron las otras dos, y por eso una sesion mirada en vivo
    anotaba caidas que la misma sesion reproducida no mostraba.

    EL FRENO TIENE QUE HABER ESTADO SUELTO EN TODA LA VENTANA, NO SOLO AL FINAL.
    Comprobarlo solo en el instante final convierte cada frenada normal en un
    incidente: se frena fuerte, se suelta al entrar en la curva, y justo ahi
    ---con el pedal ya libre--- la caida acumulada es la mayor de todas. Es el
    mismo error que el anotador ya habia cometido y corregido, y aca se evita
    con `max(freno)` sobre el marco, no con el valor de la fila.

    LOS HUECOS DE CAPTURA NO NECESITAN TRATO APARTE, y esta es la ventaja de
    medir la ventana con el reloj y no contando filas. El marco es `RANGE`
    sobre el tiempo: si entre dos muestras pasaron minutos ---el juego estuvo en
    el menu--- la fila anterior sencillamente no entra en el marco, la mas
    antigua de la ventana es ella misma y la caida da cero. Con un marco `ROWS`
    habria que descartar esos saltos a mano, como hubo que hacerlo en el trompo.

    **Si falta el freno, la regla se abstiene.** El anotador en vivo, con la
    cola vacia, evalua igual; aca no, porque sin el freno lo que queda es "la
    velocidad cayo mucho", que es la descripcion de cualquier frenada de fin de
    recta. Afirmar un incidente sin haber podido mirar el pedal seria inventar
    el hecho, igual que con las cuatro ruedas de la salida de pista.
    """

    _clausula, _par = _acotar_al_vehiculo(vehiculo)
    _ca, _pa = alcance
    cursor.execute("""
        WITH p AS (
            SELECT timestamp,
                   max(value_numeric) FILTER (WHERE signal_name = 'speed')          AS velocidad,
                   max(value_numeric) FILTER (WHERE signal_name = 'brake_position') AS freno,
                   max(value_numeric) FILTER (WHERE signal_name = 'lap_number')     AS vuelta,
                   max(value_numeric) FILTER (WHERE signal_name = 'lap_distance')   AS metro
              FROM telemetry_messages
             WHERE source_type = %s AND session_id = %s
               AND signal_name = ANY(%s)""" + _clausula + _ca + """
             GROUP BY timestamp),
        q AS (
            SELECT * FROM p WHERE velocidad IS NOT NULL AND freno IS NOT NULL),
        v AS (
            SELECT *,
                   first_value(velocidad) OVER ventana - velocidad AS caida,
                   max(freno) OVER ventana                         AS freno_maximo
              FROM q
            WINDOW ventana AS (ORDER BY timestamp
                               RANGE BETWEEN interval '{ventana} milliseconds'
                                     PRECEDING AND CURRENT ROW))
        SELECT vuelta, metro, caida, timestamp FROM v
         WHERE caida > %s AND freno_maximo < %s
         ORDER BY timestamp LIMIT 1
    """.format(ventana=int(anotador_vivo.VENTANA_CAIDA_S * 1000)),
        (fuente, session_id,
          ["speed", "brake_position", "lap_number", "lap_distance"],
          *_par,
          *_pa,
          anotador_vivo.UMBRAL_CAIDA_KMH, UMBRAL_FRENO_SUELTO_PCT))
    return cursor.fetchone()


def _primera_salida_de_pista(cursor, fuente: str, session_id: str,
                            vehiculo: str | None = None,
                            alcance: tuple[str, tuple] = ("", ())):
    """El primer instante con las cuatro ruedas fuera del asfalto, o `None`.

    Se pide en una consulta y no recorriendo la sesion: la condicion es sobre
    los cuatro canales **del mismo instante**, de modo que hay que juntarlos
    antes de compararlos.

    **Con un canal ausente la regla se abstiene**, igual que en vivo: podria
    faltar justamente la rueda que seguia tocando la pista, y afirmar una salida
    sin haber podido mirar las cuatro seria inventar el hecho.
    """

    esquinas = ["surface_type_%s" % e for e in ESQUINAS]
    _clausula, _par = _acotar_al_vehiculo(vehiculo)
    _ca, _pa = alcance
    cursor.execute("""
        WITH p AS (
            SELECT timestamp,
                   max(value_numeric) FILTER (WHERE signal_name = %s) AS a,
                   max(value_numeric) FILTER (WHERE signal_name = %s) AS b,
                   max(value_numeric) FILTER (WHERE signal_name = %s) AS c,
                   max(value_numeric) FILTER (WHERE signal_name = %s) AS d,
                   max(value_numeric) FILTER (WHERE signal_name = 'lap_number')   AS vuelta,
                   max(value_numeric) FILTER (WHERE signal_name = 'lap_distance') AS metro
              FROM telemetry_messages
             WHERE source_type = %s AND session_id = %s
               AND signal_name = ANY(%s)""" + _clausula + _ca + """
             GROUP BY timestamp)
        SELECT vuelta, metro, a, b, c, d, timestamp FROM p
         WHERE a IS NOT NULL AND b IS NOT NULL AND c IS NOT NULL AND d IS NOT NULL
           AND a <> %s AND b <> %s AND c <> %s AND d <> %s
         ORDER BY timestamp LIMIT 1
    """, tuple(esquinas) + (fuente, session_id,
                             esquinas + ["lap_number", "lap_distance"])
         + tuple(_par) + tuple(_pa) + (f1_udp.SUPERFICIE_DE_PISTA,) * 4)
    fila = cursor.fetchone()
    if not fila:
        return None
    vuelta, metro, a, b, c, d, instante = fila
    return vuelta, metro, [int(a), int(b), int(c), int(d)], instante


def _avisos_reproducidos(cursor, fuente: str, session_id: str,
                         vehiculo: str | None,
                         ventana: tuple[str, str] | None,
                         limites_fase: tuple[int | None, int | None],
                         limite: int) -> list[dict[str, Any]]:
    """Ejecuta sobre lo guardado la misma autoridad que observa el flujo vivo."""

    clausula_vehiculo, parametros_vehiculo = _acotar_al_vehiculo(vehiculo)
    clausula_fase, parametros_fase = _clausula_de_tramo(*limites_fase)
    clausula_ventana = " AND timestamp BETWEEN %s AND %s" if ventana else ""
    parametros_ventana = list(ventana or ())
    cursor.execute("""
        SELECT signal_name, value_numeric, value_boolean, value_text, unit, timestamp
          FROM telemetry_messages
         WHERE source_type = %s AND session_id = %s
           AND signal_name = ANY(%s)""" + clausula_vehiculo + clausula_ventana
                   + clausula_fase + """
         ORDER BY COALESCE(replay_seq, """ + _captura_us() + "), """
                   "array_position(%s::text[], "
                   "COALESCE(metadata->'extra'->>'paquete', '') || ':' || signal_name), "
                   "timestamp, signal_name",
        tuple([fuente, session_id, list(anotador_vivo.CANALES_PARA_ANOTAR)]
              + parametros_vehiculo + parametros_ventana + parametros_fase
              + [adaptador_f1_25.orden_de_publicacion()]))

    anotador = anotador_vivo.Anotador()
    while True:
        filas = (cursor.fetchmany(5000) if hasattr(cursor, "fetchmany")
                 else cursor.fetchall())
        if not filas:
            break
        for nombre, numero, booleano, texto, unidad, instante in filas:
            valor = numero if numero is not None else (
                booleano if booleano is not None else texto)
            anotador.observar({
                "signal_name": nombre,
                "value": valor,
                "unit": unidad,
                "timestamp": (instante.isoformat()
                              if hasattr(instante, "isoformat") else instante),
            })
        if not hasattr(cursor, "fetchmany"):
            break
    anotador.cerrar_pendiente()

    salida = []
    for anotacion in anotador.anotaciones:
        salida.append({
            "id": anotacion.get("id"),
            "nivel": "alerta" if anotacion.get("nivel") == "incidente" else "info",
            "que": anotacion.get("titulo") or "Anotacion",
            "detalle": anotacion.get("detalle") or "",
            "vuelta": anotacion.get("vuelta"),
            "metro": anotacion.get("distancia_m"),
            "instante": (datetime.fromtimestamp(anotacion["reloj_s"], timezone.utc).isoformat()
                          if anotacion.get("reloj_s") is not None else None),
            "canal": anotacion.get("fundamento") or "anotador en vivo",
            "umbral": anotacion.get("fundamento"),
            "valor": None,
            "unidad": "",
        })
    return salida[-limite:]


@router.get("/sesiones/{session_id}/avisos")
def avisos(session_id: str,
           limite: Annotated[int, Query(
               ge=1, le=anotador_vivo.ANOTACIONES_CONSERVADAS)] = 60,
           adquisicion: Annotated[str | None, Query()] = None,
           fase: Annotated[int | None, Query(ge=1)] = None) -> dict[str, Any]:
    """Avisos de una sesion ya corrida, con la vuelta y el metro en que ocurren.

    Existe `/live/anotaciones` para el flujo en vivo. Esto es lo mismo para una
    sesion guardada: sin momento, un aviso no se puede ubicar en la carrera ni
    cruzar con la traza, que es para lo que sirve.

    La secuencia persistida pasa por el mismo `Anotador` del flujo vivo. Esto
    conserva no sólo los umbrales, sino también su agrupamiento, silencios,
    textos y avisos transitorios.
    """
    # El recorrido es el mismo cada vez sobre una sesion guardada: se guarda.
    # LA CLAVE DE LA CACHE LLEVA EL ALCANCE.
    # Sin el, la respuesta de `?adquisicion=original` se serviria despues a quien
    # pida la sesion entera, y al reves: una cache que ignora el alcance es peor
    # que no tener cache, porque la mezcla queda escondida.
    clave = (session_id, limite, adquisicion or "todas", fase)
    if clave in _AVISOS_CACHE:
        _AVISOS_CACHE.move_to_end(clave)
        guardado = dict(_AVISOS_CACHE[clave])
        guardado["de_cache"] = True
        return guardado

    fuente = _fuente_de(session_id)
    if fuente != "f1_25_udp_simulation":
        return {"session_id": session_id, "fuente": fuente, "avisos": [],
                "motivo": ("Esta fuente no publica banderas, dano ni tipo de "
                            "superficie: no hay con que levantar un aviso.")}

    with db.obtener_conexion() as conexion:
        with conexion.cursor() as cursor:
            propio = _vehiculo_propio(cursor, fuente, session_id)
            ventana = _ventana_de_alcance(cursor, fuente, session_id, adquisicion)
            limites_fase = _limites_de_fase(
                cursor, fuente, session_id, adquisicion, fase)
        # Un cursor del servidor evita materializar toda la carrera en la RAM de
        # la API. `fetchmany` mantiene acotado también el lote de Python.
        with conexion.cursor(name="avisos_reproducidos") as cursor_avisos:
            encontrados = _avisos_reproducidos(
                cursor_avisos, fuente, session_id, propio, ventana,
                limites_fase, limite)

    respuesta = {
        "session_id": session_id,
        "fuente": fuente,
        "vehiculo": propio,
        "avisos": encontrados,
        "reglas_evaluadas": anotador_vivo.CANTIDAD_REGLAS,
        "criterio": ("mismas reglas, umbrales, agrupamiento y textos que el flujo "
                     "vivo, reproducidos sobre las muestras persistidas"),
    }
    _AVISOS_CACHE[clave] = respuesta
    _AVISOS_CACHE.move_to_end(clave)
    while len(_AVISOS_CACHE) > AVISOS_EN_CACHE:
        _AVISOS_CACHE.popitem(last=False)
    return dict(respuesta, de_cache=False)


# --------------------------------------------------------------------------
# 8. Catalogo de curvas
# --------------------------------------------------------------------------

@router.get("/circuitos/{circuito}/curvas")
def curvas_del_circuito(circuito: str) -> dict[str, Any]:
    """Nombres de curva de un circuito, con su anclaje medido.

    El nombre es **anotacion** y viene de un catalogo externo citado; el metro
    es **medicion**. Cada entrada lo declara, para que nadie lea un nombre
    como si el sistema lo hubiera derivado del dato.
    """
    cs = catalogo_curvas.curvas_de(circuito)
    if not cs:
        return {"circuito": circuito, "curvas": [],
                "motivo": "No hay catalogo para ese circuito."}
    return {
        "circuito": circuito,
        "largo_declarado_m": catalogo_curvas.SPA_LARGO_DECLARADO_M,
        "desnivel_declarado_m": catalogo_curvas.SPA_DESNIVEL_DECLARADO_M,
        "sentido": catalogo_curvas.SPA_SENTIDO,
        "sin_frenada": list(catalogo_curvas.SPA_SIN_FRENADA),
        "curvas": [
            {
                "orden": c.orden,
                "nombre": c.nombre,
                "numeros_cronometraje": list(c.numeros_cronometraje),
                "metro_medido": c.metro_medido,
                "velocidad_minima_kmh": c.velocidad_minima_kmh,
                "origen": c.origen,
            }
            for c in cs
        ],
    }
