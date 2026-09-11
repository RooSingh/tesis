# -*- coding: utf-8 -*-
"""Catalogo de sesiones persistidas: que hay guardado y como se llama.

EL HUECO QUE CIERRA
-------------------
La base guardaba la procedencia tecnica de cada mensaje ---identificador de
sesion, paquete, marco, los dos relojes--- y **nada que identificara a la
sesion**. Las sesiones eran consultables por identificador pero no
descubribles: una carrera con millones de filas no figuraba en ninguna lista,
y el tablero llevaba un identificador escrito en el codigo.

POR QUE UNA TABLA Y NO UNA CONSULTA
-----------------------------------
Medido el 2026-09-07: agrupar `telemetry_messages` por fuente y sesion para
contar filas y senales distintas cuesta **155 segundos** sobre los ochenta y
siete millones de filas comprimidas. Es la misma clase de consulta que ya
habia dejado dos modos del tablero sin cargar.

Lo que el catalogo describe cambia **cuando se carga una sesion**, no cuando
se consulta. Por eso se calcula una vez, se guarda, y se reconstruye cuando
hace falta ---no en cada peticion---. Consultarlo cuesta milisegundos y su
costo no crece con el volumen persistido.

QUE NO RESUELVE
---------------
No se mantiene solo. Una sesion nueva aparece cuando se reconstruye el
catalogo, no cuando se carga. Engancharlo a la ingesta es la tarea que lo
cerraria, y toca codigo de otra jornada.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from backend import db

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS sesiones_catalogo (
    session_id      text PRIMARY KEY,
    -- Puede ser nulo: la base tiene sesiones cargadas antes de que existiera
    -- la columna de procedencia. Prohibirlo las habria dejado fuera del
    -- catalogo, que es exactamente el hueco que este catalogo cierra.
    source_type     text,
    filas           bigint,
    senales         integer,
    vehiculos       integer,
    desde           timestamptz,
    hasta           timestamptz,
    actualizado_utc timestamptz NOT NULL
)
"""

#: Una sola pasada. Agrupa por las dos columnas de segmentacion de la
#: compresion, que es lo mas barato que se puede pedir sobre esta tabla.
_RECUENTO = """
SELECT source_type, session_id,
       count(*), count(DISTINCT signal_name), count(DISTINCT vehicle_id),
       min(timestamp), max(timestamp)
  FROM telemetry_messages
 WHERE session_id IS NOT NULL
 GROUP BY source_type, session_id
"""

_CERROJO = threading.Lock()
_RECONSTRUYENDO = False


def asegurar_tabla() -> None:
    """Crea la tabla si no existe. Aditivo: no toca nada de lo persistido."""
    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        cursor.execute(_ESQUEMA)
        conexion.commit()


def reconstruir() -> int:
    """Recorre la tabla una vez y deja el catalogo al dia."""
    asegurar_tabla()
    ahora = datetime.now(timezone.utc)
    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        cursor.execute(_RECUENTO)
        filas = cursor.fetchall()
        cursor.execute("DELETE FROM sesiones_catalogo")
        for f in filas:
            cursor.execute(
                """INSERT INTO sesiones_catalogo
                       (source_type, session_id, filas, senales, vehiculos,
                        desde, hasta, actualizado_utc)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (*f, ahora),
            )
        conexion.commit()
    return len(filas)


#: Una sola sesion, no la tabla entera.
_RECUENTO_DE_UNA = """
SELECT source_type, session_id,
       count(*), count(DISTINCT signal_name), count(DISTINCT vehicle_id),
       min(timestamp), max(timestamp)
  FROM telemetry_messages
 WHERE session_id = %s
 GROUP BY source_type, session_id
"""


def refrescar_sesion(session_id: str) -> bool:
    """Pone al dia **una** sesion del catalogo.

    POR QUE ESTO Y NO RECONSTRUIR TODO. Rehacer el catalogo entero cuesta
    149 s; recontar una sola sesion costo **7,2 s** medidos el 2026-09-07
    sobre la mas grande que hay, de 5,6 millones de filas, y menos de un
    segundo sobre las chicas. La diferencia es que la consulta acota por
    `session_id`, que es columna de segmentacion de la compresion.

    Esto es lo que permite que el catalogo deje de ser una foto de ayer: al
    terminar una carga se actualiza la fila de esa sesion y nada mas.

    Devuelve si la sesion quedo registrada. Una sesion que no dejo ninguna
    fila ---una carga que fallo--- se borra del catalogo en vez de quedar
    con los numeros viejos, que serian mentira.
    """
    asegurar_tabla()
    ahora = datetime.now(timezone.utc)
    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        cursor.execute(_RECUENTO_DE_UNA, (session_id,))
        filas = cursor.fetchall()
        if not filas:
            cursor.execute("DELETE FROM sesiones_catalogo WHERE session_id = %s",
                           (session_id,))
            conexion.commit()
            return False
        f = filas[0]
        cursor.execute("""
            INSERT INTO sesiones_catalogo
                   (source_type, session_id, filas, senales, vehiculos,
                    desde, hasta, actualizado_utc)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (session_id) DO UPDATE SET
                   source_type = EXCLUDED.source_type,
                   filas = EXCLUDED.filas,
                   senales = EXCLUDED.senales,
                   vehiculos = EXCLUDED.vehiculos,
                   desde = EXCLUDED.desde,
                   hasta = EXCLUDED.hasta,
                   actualizado_utc = EXCLUDED.actualizado_utc
        """, (*f, ahora))
        conexion.commit()
    return True


def refrescar_en_segundo_plano(session_id: str | None) -> None:
    """Refresca una sesion sin que nadie espere. Si no se sabe cual, no hace nada.

    No refrescar todo cuando falta el identificador es deliberado: una carga
    que no declara su sesion no justifica ciento cincuenta segundos de
    recorrido, y el catalogo tiene su reconstruccion manual para eso.
    """
    if not session_id:
        return

    def _correr() -> None:
        try:
            refrescar_sesion(session_id)
        except Exception:  # pragma: no cover - no debe tumbar al que lo llamo
            pass

    threading.Thread(target=_correr, name="catalogo-sesion-refresco",
                     daemon=True).start()


def _reconstruir_en_segundo_plano() -> None:
    global _RECONSTRUYENDO
    try:
        reconstruir()
    except Exception:  # pragma: no cover - un fallo aca no debe tumbar el hilo
        pass
    finally:
        with _CERROJO:
            _RECONSTRUYENDO = False


def pedir_reconstruccion() -> bool:
    """Lanza la reconstruccion por detras. Devuelve si la lanzo esta llamada."""
    global _RECONSTRUYENDO
    with _CERROJO:
        if _RECONSTRUYENDO:
            return False
        _RECONSTRUYENDO = True
    threading.Thread(
        target=_reconstruir_en_segundo_plano,
        name="catalogo-sesiones-reconstruccion",
        daemon=True,
    ).start()
    return True


def listar(fuente: str | None = None, limite: int = 400) -> dict[str, Any]:
    """Sesiones del catalogo, de la mas reciente a la mas vieja.

    Si el catalogo esta vacio pide su reconstruccion por detras y devuelve una
    lista vacia declarando que se esta calculando. **Vacio y calculando no son
    lo mismo que vacio y listo**, y confundirlos haria que alguien concluya
    que no hay nada guardado.
    """
    asegurar_tabla()
    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        if fuente:
            cursor.execute(
                """SELECT session_id, source_type, filas, senales, vehiculos,
                          desde, hasta, actualizado_utc
                     FROM sesiones_catalogo WHERE source_type = %s
                    ORDER BY hasta DESC NULLS LAST LIMIT %s""",
                (fuente, limite),
            )
        else:
            cursor.execute(
                """SELECT session_id, source_type, filas, senales, vehiculos,
                          desde, hasta, actualizado_utc
                     FROM sesiones_catalogo
                    ORDER BY hasta DESC NULLS LAST LIMIT %s""",
                (limite,),
            )
        filas = cursor.fetchall()

    calculando = False
    if not filas:
        calculando = pedir_reconstruccion() or _RECONSTRUYENDO

    sesiones = [
        {
            "session_id": f[0],
            "fuente": f[1],
            "fuente_declarada": f[1] is not None,
            "filas": f[2],
            "senales": f[3],
            "vehiculos": f[4],
            "desde": f[5].isoformat() if f[5] else None,
            "hasta": f[6].isoformat() if f[6] else None,
            "duracion_s": round((f[6] - f[5]).total_seconds(), 1) if f[5] and f[6] else None,
            "catalogo_actualizado_utc": f[7].isoformat() if f[7] else None,
        }
        for f in filas
    ]
    return {
        "sesiones": sesiones,
        "cantidad": len(sesiones),
        "calculando": calculando,
        "vacio_porque": (
            "El catalogo todavia no se armo; se esta calculando por detras."
            if calculando else None
        ),
    }


def extremos_de(session_id: str, source_type: str,
                cursor: Any = None) -> tuple[str | None, str | None]:
    """Los dos extremos de lo guardado de esta sesion, o `(None, None)`.

    Lo contesta el catalogo, que ya los tiene calculados, y solo mira la tabla
    grande si esa sesion todavia no fue catalogada. La distincion importa:
    preguntarle a la tabla de mediciones por el minimo de una sesion recorre su
    particion entera, y el catalogo existe justamente para no tener que hacerlo.

    CUANTO IMPORTA, MEDIDO. Sobre `openf1:session:9947` ---932.625 filas, dos
    horas y media--- `min(timestamp), max(timestamp)` acotado por sesion tarda
    **26,3 s**. Era lo unico lento de `/contexto`: las consultas que buscan los
    valores tardan treinta milisegundos. Con el catalogo el mismo dato sale de
    una fila ya escrita.

    `cursor` permite reusar el que la consulta ya tiene abierto: abrir una
    conexion nueva para leer una fila del catalogo es mas caro que la lectura.
    """
    def _texto(valor: Any) -> str | None:
        """Un instante como texto, venga como fecha o como cadena.

        El controlador devuelve `datetime` para una columna de instante, pero no
        todas las rutas pasan por el: acotar a `isoformat` ataba esta funcion a
        un solo origen de datos.
        """
        if valor is None:
            return None
        return valor.isoformat() if hasattr(valor, "isoformat") else str(valor)

    def _leer(cur: Any) -> tuple[str | None, str | None]:
        cur.execute(
            "SELECT desde, hasta FROM sesiones_catalogo WHERE session_id = %s",
            (session_id,))
        fila = cur.fetchone()
        if fila and fila[0]:
            return (_texto(fila[0]), _texto(fila[1]))
        cur.execute(
            """SELECT min(timestamp), max(timestamp) FROM telemetry_messages
                WHERE source_type = %s AND session_id = %s""",
            (source_type, session_id))
        fila = cur.fetchone()
        if not fila or not fila[0]:
            return (None, None)
        return (_texto(fila[0]), _texto(fila[1]))

    # `asegurar_tabla` abre su propia conexion y commitea. Con un cursor
    # prestado eso es abrir una transaccion dentro de otra para crear algo que
    # quien presta el cursor ya dio por hecho: quien consulta el catalogo desde
    # una peticion lo hace porque la aplicacion ya lo tiene en pie.
    if cursor is not None:
        return _leer(cursor)
    asegurar_tabla()
    with db.obtener_conexion() as conexion, conexion.cursor() as cur:
        return _leer(cur)


def rango_de(session_id: str, source_type: str) -> str | None:
    """Cuando empieza lo guardado de esta sesion, o `None` si no hay nada."""
    return extremos_de(session_id, source_type)[0]


def estado() -> dict[str, Any]:
    """Cuantas sesiones tiene el catalogo y cuando se armo."""
    asegurar_tabla()
    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        cursor.execute("SELECT count(*), max(actualizado_utc) FROM sesiones_catalogo")
        cantidad, actualizado = cursor.fetchone()
    return {
        "sesiones": cantidad,
        "actualizado_utc": actualizado.isoformat() if actualizado else None,
        "reconstruyendo": _RECONSTRUYENDO,
        "vacio": cantidad == 0,
    }
