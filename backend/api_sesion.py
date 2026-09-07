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

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from backend import (catalogo_curvas, catalogo_sesiones, db,
                     procedencia_sesiones)

router = APIRouter()

#: Nombre de la senal de distancia por fuente. La fuente deportiva no declara
#: distancia recorrida y por eso no figura: en OpenF1 no hay eje espacial
#: defendible, medido el 2026-09-06 (huecos de hasta 83 m entre muestras).
DISTANCIA_POR_FUENTE = {
    "f1_25_udp_simulation": "lap_distance",
}

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

@router.get("/sesiones/{session_id}/vueltas")
def listar_vueltas(session_id: str) -> dict[str, Any]:
    """Vueltas de la sesion, con su largo y su rango de distancia.

    Devolver el rango de distancia y no solo el numero es lo que permite al
    tablero acotar una consulta de series sin adivinar: pide de tal metro a
    tal metro de tal vuelta.
    """
    fuente = _fuente_de(session_id)
    senal_distancia = DISTANCIA_POR_FUENTE.get(fuente)
    if not senal_distancia:
        return {
            "session_id": session_id,
            "fuente": fuente,
            "vueltas": [],
            "motivo": "Esta fuente no declara distancia recorrida: no hay vueltas que delimitar por metro.",
        }

    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        filas = _filas(cursor, """
            WITH p AS (
                SELECT timestamp,
                       max(value_numeric) FILTER (WHERE signal_name = 'lap_number')   AS vuelta,
                       max(value_numeric) FILTER (WHERE signal_name = %s)             AS distancia,
                       max(value_numeric) FILTER (WHERE signal_name = 'speed')        AS velocidad,
                       max(value_numeric) FILTER (WHERE signal_name = 'lap_invalid')  AS invalida
                  FROM telemetry_messages
                 WHERE source_type = %s AND session_id = %s
                   AND signal_name IN ('lap_number', %s, 'speed', 'lap_invalid')
                 GROUP BY timestamp)
            SELECT vuelta::int,
                   count(*)                       AS muestras,
                   min(distancia)                 AS desde_m,
                   max(distancia)                 AS hasta_m,
                   min(timestamp)                 AS inicio,
                   max(timestamp)                 AS fin,
                   min(velocidad)                 AS v_min,
                   max(velocidad)                 AS v_max,
                   max(invalida)                  AS invalida
              FROM p
             WHERE vuelta IS NOT NULL AND distancia IS NOT NULL
             GROUP BY vuelta
             ORDER BY vuelta
        """, (senal_distancia, fuente, session_id, senal_distancia))

    vueltas = []
    for f in filas:
        duracion = (f[5] - f[4]).total_seconds() if f[4] and f[5] else None
        vueltas.append({
            "numero": f[0],
            "muestras": f[1],
            "desde_m": round(f[2], 1) if f[2] is not None else None,
            "hasta_m": round(f[3], 1) if f[3] is not None else None,
            "largo_m": round(f[3] - f[2], 1) if f[2] is not None and f[3] is not None else None,
            "duracion_s": round(duracion, 3) if duracion is not None else None,
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
    return {"session_id": session_id, "fuente": fuente, "vueltas": vueltas}


@router.get("/sesiones/{session_id}/posiciones")
def posiciones_en_pista(
        session_id: str,
        vuelta: int,
        puntos: Annotated[int, Query(ge=20, le=400)] = 160,
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
            detail=("La fuente %s no declara distancia recorrida: no se puede "
                    "ubicar a los vehiculos sobre la vuelta." % fuente))

    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        ventana = _filas(cursor, """
            SELECT min(timestamp), max(timestamp)
              FROM telemetry_messages
             WHERE source_type = %s AND session_id = %s
               AND signal_name = 'lap_number' AND value_numeric = %s
        """, (fuente, session_id, float(vuelta)))
        if not ventana or ventana[0][0] is None:
            return {"session_id": session_id, "vuelta": vuelta, "vehiculos": {},
                    "motivo": "No hay muestras de esa vuelta."}
        t0, t1 = ventana[0]

        filas = _filas(cursor, """
            WITH m AS (
                SELECT vehicle_id, timestamp, value_numeric AS d,
                       width_bucket(extract(epoch FROM timestamp),
                                    extract(epoch FROM %s::timestamptz),
                                    extract(epoch FROM %s::timestamptz), %s) AS cubo
                  FROM telemetry_messages
                 WHERE source_type = %s AND session_id = %s AND signal_name = %s
                   AND timestamp BETWEEN %s AND %s)
            SELECT DISTINCT ON (vehicle_id, cubo) vehicle_id, cubo, d
              FROM m
             WHERE d IS NOT NULL
             ORDER BY vehicle_id, cubo, timestamp
        """, (t0, t1, puntos, fuente, session_id, senal_distancia, t0, t1))

    vehiculos: dict[str, list] = {}
    for vehiculo, cubo, d in filas:
        serie = vehiculos.setdefault(vehiculo, [None] * (puntos + 2))
        if 0 <= cubo < len(serie):
            serie[cubo] = round(d, 1)

    return {
        "session_id": session_id,
        "fuente": fuente,
        "vuelta": vuelta,
        "desde_utc": t0.isoformat(),
        "hasta_utc": t1.isoformat(),
        "puntos": puntos,
        "senal": senal_distancia,
        "vehiculos": vehiculos,
        "eje": "tiempo repartido en intervalos iguales dentro de la vuelta",
    }


# --------------------------------------------------------------------------
# 1 y 4. Series contra distancia, para uno o varios vehiculos
# --------------------------------------------------------------------------

@router.get("/sesiones/{session_id}/series")
def series_por_distancia(
    session_id: str,
    senales: Annotated[str, Query(description="Nombres de senal separados por coma")],
    vuelta: int | None = None,
    vehiculos: Annotated[str | None, Query(description="Identificadores separados por coma")] = None,
    desde_m: float = 0.0,
    hasta_m: float | None = None,
    puntos: Annotated[int, Query(ge=50, le=5000)] = 600,
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
            detail=("La fuente %s no declara distancia recorrida. En OpenF1 el muestreo "
                    "deja huecos de hasta 83 m y el eje espacial no es defendible; "
                    "usar las rutas por tiempo." % fuente),
        )

    pedidas = [s.strip() for s in senales.split(",") if s.strip()]
    if not pedidas:
        raise HTTPException(status_code=422, detail="Hay que pedir al menos una senal.")
    if len(pedidas) > 12:
        raise HTTPException(status_code=422, detail="Hasta doce senales por consulta.")

    autos = [v.strip() for v in vehiculos.split(",")] if vehiculos else []

    condiciones = ["source_type = %s", "session_id = %s"]
    parametros: list[Any] = [fuente, session_id]
    if autos:
        condiciones.append("vehicle_id = ANY(%s)")
        parametros.append(autos)

    # Tiempo y distancia de sesion ya llegan en cada muestra F1 25. Se
    # conservan en la respuesta para que el navegador no tenga que convertir
    # metros a segundos ni fabricar una distancia acumulada entre vueltas.
    interes = pedidas + [senal_distancia, "session_distance"] + (["lap_number"] if vuelta is not None else [])
    condiciones.append("signal_name = ANY(%s)")
    parametros.append(interes)

    consulta = """
        WITH p AS (
            SELECT timestamp, vehicle_id,
                   %s
              FROM telemetry_messages
             WHERE {donde}
             GROUP BY timestamp, vehicle_id)
        SELECT * FROM p WHERE distancia IS NOT NULL {filtro_vuelta}
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
    consulta = consulta % ",\n                   ".join(columnas)
    consulta = consulta.replace("{donde}", " AND ".join(condiciones))
    consulta = consulta.replace("{filtro_vuelta}", "AND vuelta = %s" if vuelta is not None else "")

    todos = columnas_par + parametros + ([vuelta] if vuelta is not None else [])

    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        cursor.execute(consulta, tuple(todos))
        filas = cursor.fetchall()

    if not filas:
        return {"session_id": session_id, "fuente": fuente, "senales": pedidas,
                "vehiculos": {}, "muestras": 0,
                "motivo": "La sesion no tiene esas senales en el rango pedido."}

    desplazamiento = 2 if vuelta is not None else 1  # timestamp, vehicle_id
    idx_dist = 2
    idx_dist_sesion = 3 + (1 if vuelta is not None else 0)
    idx_primera = idx_dist_sesion + 1

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
    for vehiculo, fs in por_vehiculo.items():
        paso = max(1, len(fs) // puntos)
        if paso > 1:
            submuestreado = True
        recorte = fs[::paso]
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
        "muestras": sum(len(v["distancia_m"]) for v in salida.values()),
        "submuestreado": submuestreado,
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

@router.get("/sesiones/{session_id}/trazado")
def trazado(session_id: str, vuelta: int | None = None,
            puntos: Annotated[int, Query(ge=50, le=3000)] = 400) -> dict[str, Any]:
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
                 GROUP BY timestamp)
            SELECT x, z, y, distancia, vuelta FROM p
             WHERE x IS NOT NULL AND z IS NOT NULL
             ORDER BY vuelta NULLS LAST, distancia NULLS LAST, timestamp
        """, (eje_x, eje_z, fuente, session_id, interes))
        filas = cursor.fetchall()

    if not filas:
        return {"session_id": session_id, "fuente": fuente, "puntos": [],
                "motivo": "La sesion no tiene posicion persistida."}

    if vuelta is not None:
        filas = [f for f in filas if f[4] is not None and int(f[4]) == vuelta]
    else:
        # Sin vuelta pedida se elige la que mas puntos tenga: es la que mejor
        # dibuja el trazado completo.
        por_vuelta: dict[Any, list] = {}
        for f in filas:
            por_vuelta.setdefault(f[4], []).append(f)
        filas = max(por_vuelta.values(), key=len)

    if not filas:
        return {"session_id": session_id, "fuente": fuente, "puntos": [],
                "motivo": "Esa vuelta no tiene posicion persistida."}

    paso = max(1, len(filas) // puntos)
    recorte = filas[::paso]
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
    "sesgo_de_freno_pct": "brake_bias_front",
    "mezcla_de_combustible": "fuel_mix_mode",
    "modo_de_despliegue_ers": "ers_deploy_mode",
    "compuesto": "tyre_compound",
    "edad_del_neumatico_vueltas": "tyre_age",
}


def _ultimos_valores(cursor, fuente: str, session_id: str, senales: list[str],
                     hasta_utc: str | None = None) -> dict[str, float]:
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
    if not senales:
        return {}
    condicion = ""
    parametros: list[Any] = [fuente, session_id, senales]
    if hasta_utc:
        condicion = " AND timestamp <= %s"
        parametros.append(hasta_utc)
    cursor.execute("""
        SELECT DISTINCT ON (signal_name)
               signal_name, value_numeric, value_boolean, value_text, unit, timestamp
          FROM telemetry_messages
         WHERE source_type = %s AND session_id = %s AND signal_name = ANY(%s)""" +
        condicion + """
         ORDER BY signal_name, timestamp DESC
    """, tuple(parametros))
    salida = {}
    for nombre, num, boo, txt, unidad, ts in cursor.fetchall():
        valor = num if num is not None else (boo if boo is not None else txt)
        salida[nombre] = {"valor": valor, "unidad": unidad,
                          "instante": ts.isoformat() if ts else None}
    return salida


@router.get("/sesiones/{session_id}/vehiculo")
def estado_del_vehiculo(
        session_id: str,
        hasta: Annotated[str | None, Query(
            description="Instante ISO-8601: estado del vehiculo vigente hasta ahi")] = None,
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
        valores = _ultimos_valores(cursor, fuente, session_id, pedidas, hasta)

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
            "Esta fuente no publica estado de neumaticos ni de dano."
            if not esquinas and not carroceria else None
        ),
    }


@router.get("/sesiones/{session_id}/puesta-a-punto")
def puesta_a_punto(session_id: str) -> dict[str, Any]:
    """Configuracion asentada del vehiculo.

    IMPORTANTE. Se devuelve el ultimo valor persistido, que es la
    configuracion **con la que se rodo**. El menu del juego publica valores
    intermedios mientras se navega, y mostrarlos seria declarar como puesta a
    punto algo que nunca se llevo a la pista.
    """
    fuente = _fuente_de(session_id)
    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        valores = _ultimos_valores(cursor, fuente, session_id,
                                   list(CANALES_PUESTA_A_PUNTO.values()))
    datos = {}
    for clave, canal in CANALES_PUESTA_A_PUNTO.items():
        v = valores.get(canal)
        if v is not None:
            datos[clave] = v["valor"]
    return {
        "session_id": session_id,
        "fuente": fuente,
        "puesta_a_punto": datos,
        "criterio": "ultimo valor persistido: la configuracion con la que se rodo",
        "motivo_ausencia": None if datos else "Esta fuente no publica configuracion del vehiculo.",
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

#: Tipos de superficie que no son pista. El piano **no** esta: se puede rodar
#: sobre un piano sin perder agarre, y en la trazada normal se pisa.
SUPERFICIES_FUERA = {2: "grava", 3: "arena", 4: "tierra", 6: "cesped artificial"}


@router.get("/sesiones/{session_id}/avisos")
def avisos(session_id: str,
           limite: Annotated[int, Query(ge=1, le=300)] = 60) -> dict[str, Any]:
    """Avisos de una sesion ya corrida, con la vuelta y el metro en que ocurren.

    Existe `/live/anotaciones` para el flujo en vivo. Esto es lo mismo para una
    sesion guardada: sin momento, un aviso no se puede ubicar en la carrera ni
    cruzar con la traza, que es para lo que sirve.

    Se devuelve el **primer** instante en que cada condicion se cumple, no cada
    muestra que la cumple: un piso roto lo sigue estando durante mil muestras y
    eso es un solo hecho.
    """
    fuente = _fuente_de(session_id)
    if fuente != "f1_25_udp_simulation":
        return {"session_id": session_id, "fuente": fuente, "avisos": [],
                "motivo": ("Esta fuente no publica banderas, dano ni tipo de "
                           "superficie: no hay con que levantar un aviso.")}

    canales = [r["canal"] for r in REGLAS_DE_AVISO]
    superficies = ["surface_type_%s" % e for e in ESQUINAS]

    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        cursor.execute("""
            WITH p AS (
                SELECT timestamp,
                       max(value_numeric) FILTER (WHERE signal_name = 'lap_number')  AS vuelta,
                       max(value_numeric) FILTER (WHERE signal_name = 'lap_distance') AS metro,
                       signal_name, max(value_numeric) AS valor
                  FROM telemetry_messages
                 WHERE source_type = %s AND session_id = %s
                   AND signal_name = ANY(%s)
                 GROUP BY timestamp, signal_name)
            SELECT signal_name, min(timestamp) FILTER (WHERE valor IS NOT NULL) AS primero,
                   max(valor) AS pico
              FROM p GROUP BY signal_name
        """, (fuente, session_id, canales + superficies + ["lap_number", "lap_distance"]))
        picos = {f[0]: {"primero": f[1], "pico": f[2]} for f in cursor.fetchall()}

        # El momento exacto de cada condicion: una consulta por regla que se
        # cumple, no por regla declarada.
        encontrados = []
        for regla in REGLAS_DE_AVISO:
            info = picos.get(regla["canal"])
            if not info or info["pico"] is None or info["pico"] < regla["umbral"]:
                continue
            cursor.execute("""
                WITH p AS (
                    SELECT timestamp,
                           max(value_numeric) FILTER (WHERE signal_name = %s) AS v,
                           max(value_numeric) FILTER (WHERE signal_name = 'lap_number') AS vuelta,
                           max(value_numeric) FILTER (WHERE signal_name = 'lap_distance') AS metro
                      FROM telemetry_messages
                     WHERE source_type = %s AND session_id = %s
                       AND signal_name IN (%s, 'lap_number', 'lap_distance')
                     GROUP BY timestamp)
                SELECT vuelta, metro, v, timestamp FROM p
                 WHERE v >= %s ORDER BY timestamp LIMIT 1
            """, (regla["canal"], fuente, session_id, regla["canal"], regla["umbral"]))
            fila = cursor.fetchone()
            if not fila:
                continue
            encontrados.append({
                "nivel": regla["nivel"],
                "que": regla["que"],
                "valor": round(fila[2], 2) if fila[2] is not None else None,
                "unidad": regla["unidad"],
                "vuelta": int(fila[0]) if fila[0] is not None else None,
                "metro": round(fila[1], 1) if fila[1] is not None else None,
                "instante": fila[3].isoformat() if fila[3] else None,
                "canal": regla["canal"],
                "umbral": regla["umbral"],
            })

    encontrados.sort(key=lambda a: (-(a["vuelta"] or 0), -(a["metro"] or 0)))
    return {
        "session_id": session_id,
        "fuente": fuente,
        "avisos": encontrados[:limite],
        "reglas_evaluadas": len(REGLAS_DE_AVISO),
        "criterio": ("primer instante en que cada condicion se cumple; cada aviso "
                     "declara su canal y su umbral"),
    }


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
