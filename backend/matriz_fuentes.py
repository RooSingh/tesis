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

import threading
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
#: DOS LLAVES QUE DECIDEN SI DOS FUENTES SE PUEDEN RESTAR.
#:
#: `naturalezas` dice **que clase de valor** publica cada fuente cuando no es una
#: cifra continua: `si_no` para un booleano y `codigo` para un identificador de
#: estado. Estaba dicho en prosa, en las notas ---«solo el simulador entrega
#: intensidad»---, y una nota no la puede leer quien decide si restar. Sin
#: declarar, se asume `cifra`.
#:
#: `marco_propio` dice que cada fuente la expresa en **su** sistema, de modo que
#: las cifras no son comparables entre fuentes aunque compartan unidad: la
#: posicion en el trazado y el angulo de direccion son los dos casos.
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
            "f1_25_udp_simulation": "wheel_speed_front_left",
        },
        "ausencias": {
            "openf1_historical_replay": "la interfaz publica no la expone",
        },
        "nota": "la misma magnitud en unidades distintas: el bus la da en "
                "kilometros por hora y el simulador en metros por segundo. Las "
                "dos fuentes publican las cuatro esquinas; la matriz mide sobre "
                "la delantera izquierda",
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
            "f1_25_udp_simulation": "yaw_rate",
        },
        "ausencias": {
            "openf1_historical_replay": "la interfaz publica no la expone",
        },
        "nota": "la misma magnitud en unidades distintas: el bus la da en grados "
                "por segundo y el simulador en radianes por segundo. La unidad "
                "no va en el nombre de la senal: viaja en cada fila",
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
        "marco_propio": "el bus la da en grados y el simulador normalizada entre "
                        "menos uno y uno: la forma se compara, la escala no",
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
        "naturalezas": {
            "can_real_replay": "si_no",
            "openf1_historical_replay": "si_no",
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
        "naturalezas": {"can_real_replay": "si_no"},
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
        "marco_propio": "cada fuente la publica en su propio sistema de "
                        "coordenadas, con otro origen y otra orientacion",
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
        "naturalezas": {
            "openf1_historical_replay": "codigo",
            "f1_25_udp_simulation": "si_no",
        },
        "nota": "el simulador lo entrega como booleano documentado y la fuente "
                "deportiva como codigo de estado con valores indeterminados",
    },
]


#: QUE FUENTE PUBLICA DISTANCIA RECORRIDA, Y POR QUE LAS OTRAS NO.
#:
#: Es lo que decide si dos fuentes se pueden alinear sobre el circuito o solo
#: comparar en conjunto. Sin metro medido no hay eje espacial, y entonces la
#: unica comparacion honesta es la de los valores alcanzados y su frecuencia.
#:
#: EL MISMO HECHO ESTA ESCRITO EN EL TABLERO, en `EJE_DE_DISTANCIA_POR_FUENTE`,
#: porque el panel de trazado tiene que poder explicar la ausencia sin esperar a
#: que la API falle. Dos copias de un hecho es una de mas, y mientras no se
#: unifiquen hay una prueba que compara las dos y cae si se separan: una
#: duplicacion vigilada no es lo mismo que una duplicacion.
EJE_DE_DISTANCIA = {
    "f1_25_udp_simulation": {"hay": True, "porque": ""},
    "openf1_historical_replay": {"hay": False, "porque":
        "el muestreo de 3,7 Hz deja huecos de hasta 1,3 s entre muestras, y a "
        "velocidad de recta eso son más de 110 m: sobre ese eje dos puntos "
        "vecinos no son dos lugares vecinos del circuito"},
    "can_real_replay": {"hay": False, "porque":
        "el bus publica velocidad de rueda pero no odómetro ni distancia de "
        "vuelta: no hay metro medido con el que ubicar una muestra en el "
        "circuito"},
}


def eje_comun_de_distancia(fuente_a: str, fuente_b: str) -> dict:
    """Si las dos fuentes admiten el mismo eje espacial, y si no, por que.

    Alcanza con que a una le falte. Y el motivo que viaja es el de la que no lo
    tiene, no una frase generica: «no hay eje comun» no le dice a nadie que el
    problema es un hueco de ochenta y tres metros.
    """

    faltan = [f for f in (fuente_a, fuente_b)
              if not EJE_DE_DISTANCIA.get(f, {"hay": True})["hay"]]
    if not faltan:
        return {"hay": True, "porque": ""}
    return {"hay": False,
            "porque": "; ".join(EJE_DE_DISTANCIA[f]["porque"] for f in faltan)}


#: Ventana sobre la que se mide la frecuencia.
#:
#: Una frecuencia es una razon: medirla sobre un minuto da lo mismo que sobre
#: dos horas, y cuesta muchisimo menos. La primera version media sobre la sesion
#: completa y tardaba tres minutos en construir la matriz, porque la sesion de la
#: fuente deportiva tiene siete millones y medio de filas.
VENTANA_MEDICION_S = 120

#: Sobre que recorte se midio, escrito para que viaje con el resultado. Decia
#: «la sesion y el vehiculo mas recientes de cada fuente» y era cierto; el
#: problema era el criterio, no la frase. Describir mal el recorte es peor que no
#: describirlo, porque invita a confiar.
MEDIDO_SOBRE = ("la sesion con mas filas de cada fuente, acotada a un conductor: "
                "lo mas reciente suele ser una captura de prueba y su frecuencia "
                "no caracteriza a la fuente")


def _contexto_reciente(cursor, fuente: str) -> tuple[str, str, Any] | None:
    """Sobre que sesion y conductor se mide la frecuencia de una fuente.

    Se resuelve **una vez por fuente** y no una vez por senal, y se toma el
    conductor y no el vehiculo porque es lo que el indice de la tabla ordena
    despues de la sesion.

    Medir por conductor no es un detalle: la fuente deportiva reune veinte en una
    misma sesion, y contarlos juntos multiplica por veinte la frecuencia
    aparente. Ya paso —la primera medicion dio noventa hercios donde hay cuatro—
    y por eso la resolucion del contexto incluye al conductor.

    SE ELIGE LA QUE MAS FILAS TIENE, NO LA MAS RECIENTE, y es el mismo descuido
    que el del conductor en otra dimension. Lo mas reciente de una fuente suele
    ser una captura de prueba de unos segundos, y la frecuencia que sale de ahi
    se publica como caracteristica de la fuente. Medido sobre la base local el
    2026-09-12: el simulador tiene tres sesiones, la mas reciente con 17.094
    filas y la captura de verdad con 5.641.702 ---trescientas treinta veces
    mas, y mas vieja---. La matriz declaraba 2,9 Hz donde lo medido sobre la
    captura real es 58,3. Veinte veces menos, en el numero que alguien copiaria.

    `backend.analisis.disponibilidad` ya elegia asi para sus propias mediciones.
    Dos modulos contestaban distinto a la misma pregunta.
    """

    cursor.execute(
        """select session_id, driver_id, max(timestamp)
           from telemetry_messages
           where source_type = %s
           group by session_id, driver_id
           order by count(*) desc limit 1""",
        (fuente,),
    )
    return cursor.fetchone()


def _medir(cursor, fuente: str, senal: str,
           contexto: tuple[str, str, Any] | None) -> dict[str, Any] | None:
    """Mide la frecuencia de una señal sobre una ventana del final de la sesion."""

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


#: Un solo recalculo a la vez, y nunca dentro de una peticion si ya hay un
#: resultado anterior que servir.
_CERROJO_REFRESCO = threading.Lock()
_REFRESCANDO = False


def _refrescar_en_segundo_plano() -> None:
    """Recalcula la matriz sin que nadie espere el resultado."""

    global _REFRESCANDO
    try:
        _construir_midiendo()
    except Exception:  # pragma: no cover - el refresco no debe tumbar el hilo
        pass
    finally:
        with _CERROJO_REFRESCO:
            _REFRESCANDO = False


def construir() -> dict[str, Any]:
    """Devuelve la matriz, midiendo solo cuando no hay nada que servir.

    POR QUE NO SE RECALCULA DENTRO DE LA PETICION.

    La medicion recorre la tabla entera: son 19,9 s con las consultas ya
    corregidas, y eran mas de cinco minutos antes. Con una vigencia de cinco
    minutos, una de cada tantas visitas pagaba esa espera completa, y el
    tablero parecia colgado sin decir por que.

    Lo que la matriz describe ---cuantas filas, senales, sesiones y vehiculos
    tiene cada fuente--- **cambia cuando se carga una sesion, no cuando se
    consulta**. Por eso, vencida la vigencia, se entrega igual el ultimo
    calculo, declarando su edad, y el recalculo ocurre por detras. Quien mira
    ve un dato de hace unos minutos, que es exacto salvo que se haya cargado
    algo en el medio, en lugar de esperar veinte segundos.

    La unica espera real es la primera, cuando todavia no hay nada que servir.
    """

    global _REFRESCANDO
    ahora = time.monotonic()

    if _CACHE:
        edad = ahora - _CACHE[0]
        if edad >= VIGENCIA_S:
            with _CERROJO_REFRESCO:
                if not _REFRESCANDO:
                    _REFRESCANDO = True
                    hilo = threading.Thread(
                        target=_refrescar_en_segundo_plano,
                        name="matriz-fuentes-refresco",
                        daemon=True,
                    )
                    hilo.start()
        return {
            **_CACHE[1],
            "edad_del_calculo_s": round(edad, 1),
            "recalculando": edad >= VIGENCIA_S,
        }

    # SIN NADA QUE SERVIR, TAMPOCO SE RETIENE LA PETICION.
    #
    # Al arrancar, `backend/app.py` lanza el precalculo en segundo plano. Pero
    # el tablero pide esta ruta al abrir, y con el proceso recien arrancado la
    # peticion llega **antes** de que ese precalculo termine: sin cache,
    # `construir` arrancaba una segunda medicion completa dentro de la peticion,
    # en paralelo con la primera. Medido el 2026-09-08: **41,45 s**, y las dos
    # recorriendo la tabla a la vez.
    #
    # Ahora se responde que todavia no esta. La matriz es el pie del tablero
    # ---que sostiene cada fuente---, no algo que haga falta para dibujar: decir
    # «se esta midiendo» y llegar treinta segundos despues es mejor que retener
    # la conexion, que ademas es una de las seis que el navegador da por origen.
    with _CERROJO_REFRESCO:
        arrancar = not _REFRESCANDO
        if arrancar:
            _REFRESCANDO = True
    if arrancar:
        threading.Thread(
            target=_refrescar_en_segundo_plano,
            name="matriz-fuentes-primera",
            daemon=True,
        ).start()
    return {
        "fuentes": [],
        "magnitudes": [],
        "sin_medir": True,
        "recalculando": True,
        "edad_del_calculo_s": None,
        "motivo_ausencia": ("la matriz se mide recorriendo lo persistido y "
                            "todavia no termino; se esta calculando ahora"),
    }


def _construir_midiendo() -> dict[str, Any]:
    """Mide contra la base. Es la parte cara; no llamarla desde una peticion
    si hay un resultado anterior disponible."""

    global _CACHE
    ahora = time.monotonic()
    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        fuentes = []
        for definicion in FUENTES:
            # POR QUE ESTO SON TRES CONSULTAS Y NO UNA.
            #
            # Escrito como una sola sentencia con los cuatro agregados juntos,
            # el planificador resuelve todo en una pasada que descomprime la
            # tabla entera: medido el 2026-09-06 sobre la fuente de simulacion
            # ---64,9 millones de filas--- costaba 282 segundos, y la matriz
            # tiene varias fuentes. El modo del tablero que la consume no
            # llegaba a cargar nunca.
            #
            # Separadas, cada una puede aprovechar que `signal_name`,
            # `session_id`, `source_type` y `vehicle_id` son columnas de
            # segmentacion de la compresion, y que los valores distintos estan
            # disponibles sin descomprimir el contenido. El conteo de filas baja
            # a 0,2 s, el de senales a 1,4 s, y los dos conteos de valores
            # distintos, resueltos sobre una subconsulta `distinct` comun, a
            # 7,7 s. La misma respuesta en 9,3 s en lugar de 282.
            cursor.execute(
                "select count(*) from telemetry_messages where source_type = %s",
                (definicion["clave"],),
            )
            (filas,) = cursor.fetchone()

            cursor.execute(
                """select count(distinct signal_name)
                     from telemetry_messages where source_type = %s""",
                (definicion["clave"],),
            )
            (senales,) = cursor.fetchone()

            cursor.execute(
                """select count(*), count(distinct vehicle_id)
                     from (select distinct session_id, vehicle_id
                             from telemetry_messages
                            where source_type = %s) as pares""",
                (definicion["clave"],),
            )
            _pares, vehiculos = cursor.fetchone()

            cursor.execute(
                """select count(*)
                     from (select distinct session_id
                             from telemetry_messages
                            where source_type = %s) as s""",
                (definicion["clave"],),
            )
            (sesiones,) = cursor.fetchone()
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
                 "medido_sobre": MEDIDO_SOBRE}
    _CACHE = (ahora, resultado)
    return resultado
