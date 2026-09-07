# -*- coding: utf-8 -*-
"""Catalogo de corridas de reinyeccion, mantenido en vez de derivado.

POR QUE ESTE MODULO EXISTE
--------------------------
`db.listar_corridas_replay_acotado` enumera las corridas recorriendo un indice
por saltos: pide el primer identificador, salta al siguiente distinto, y asi.
Sobre una tabla comun eso cuesta milisegundos y su costo no depende del volumen,
que es lo que su documentacion afirma.

**Dejo de ser cierto el dia que la tabla se comprimio.** Medido el 2026-09-06:
302,3 segundos para devolver **una** corrida. La causa esta en como se configuro
la compresion: segmenta por `signal_name`, `session_id`, `source_type` y
`vehicle_id`, y `replay_run_id` **no esta entre esas columnas**. Los valores de
las columnas de segmentacion quedan accesibles sin descomprimir; los demas viajan
dentro del lote comprimido. Un salto de indice sobre una columna que no segmenta
degrada a recorrer y descomprimir, y el costo pasa a depender por completo del
volumen.

QUE HACE ESTE MODULO EN VEZ DE ESO
-----------------------------------
Mantiene una tabla chica con una fila por corrida. Consultarla cuesta
milisegundos y **su costo no depende del volumen persistido**, que es la promesa
que la ruta hacia y ya no podia cumplir.

El recuento se hace **una vez**, no en cada peticion. Es la misma decision que
tomo `track_reference` con las longitudes de circuito y `catalogo_curvas` con los
nombres: lo que no cambia al consultarse no se recalcula al consultarse.

QUE NO RESUELVE
---------------
No mantiene el catalogo al dia por si solo. Una corrida nueva aparece cuando se
reconstruye el catalogo, no cuando se carga la corrida. Conectarlo a la ingesta
es la tarea que lo cerraria, y toca codigo de otra jornada.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from backend import db

#: Tope de corridas que se enumeran. El mismo criterio que la funcion que
#: reemplaza: hoy hay unas pocas, y si alguna vez se acerca al tope hay que
#: elevarlo o declarar el recorte.
LIMITE = 200

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS replay_runs_catalogo (
    replay_run_id   text PRIMARY KEY,
    session_id      text,
    source_type     text,
    desde           timestamptz,
    hasta           timestamptz,
    mensajes        bigint,
    actualizado_utc timestamptz NOT NULL
)
"""

#: Una sola pasada sobre la tabla, no una por corrida. La consulta anterior
#: hacia un salto de indice por corrida y ademas una lectura por corrida.
_RECUENTO = """
SELECT replay_run_id,
       min(session_id)  AS session_id,
       min(source_type) AS source_type,
       min(timestamp)   AS desde,
       max(timestamp)   AS hasta,
       count(*)         AS mensajes
  FROM telemetry_messages
 WHERE replay_run_id IS NOT NULL
 GROUP BY replay_run_id
 LIMIT %(limite)s
"""

_CERROJO = threading.Lock()
_RECONSTRUYENDO = False


def asegurar_tabla() -> None:
    """Crea la tabla si no existe. Es aditivo y no toca nada de lo persistido."""
    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        cursor.execute(_ESQUEMA)
        conexion.commit()


def reconstruir() -> int:
    """Recorre la tabla una vez y deja el catalogo al dia.

    Devuelve cuantas corridas quedaron registradas. Es la operacion cara: no
    debe llamarse desde una peticion si el catalogo ya tiene algo que servir.
    """
    asegurar_tabla()
    ahora = datetime.now(timezone.utc)
    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        cursor.execute(_RECUENTO, {"limite": LIMITE})
        filas = cursor.fetchall()
        cursor.execute("DELETE FROM replay_runs_catalogo")
        for fila in filas:
            cursor.execute(
                """INSERT INTO replay_runs_catalogo
                       (replay_run_id, session_id, source_type, desde, hasta,
                        mensajes, actualizado_utc)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (*fila, ahora),
            )
        conexion.commit()
    return len(filas)


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
        name="catalogo-corridas-reconstruccion",
        daemon=True,
    ).start()
    return True


def listar(session_key: int | None = None) -> list[dict[str, Any]]:
    """Corridas del catalogo, opcionalmente acotadas a una sesion.

    Si el catalogo esta vacio pide su reconstruccion por detras y devuelve una
    lista vacia. **Una lista vacia es una respuesta valida** ---la sesion puede
    no tener telemetria reinyectada--- y por eso el estado del catalogo se
    declara aparte, en `estado_catalogo`, en vez de confundirse con el dato.
    """
    asegurar_tabla()
    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        if session_key is None:
            cursor.execute(
                """SELECT replay_run_id, session_id, source_type, desde, hasta,
                          mensajes, actualizado_utc
                     FROM replay_runs_catalogo ORDER BY replay_run_id"""
            )
        else:
            cursor.execute(
                """SELECT replay_run_id, session_id, source_type, desde, hasta,
                          mensajes, actualizado_utc
                     FROM replay_runs_catalogo
                    WHERE session_id LIKE %s ORDER BY replay_run_id""",
                ("%%%s%%" % session_key,),
            )
        filas = cursor.fetchall()

    if not filas:
        pedir_reconstruccion()

    # Los nombres de campo son los que ya consume el tablero. `mensajes_estimados`
    # conserva el nombre aunque aca el conteo sea exacto: cambiarlo obligaria a
    # tocar la interfaz sin que el dato mejore para quien la mira. Lo que si se
    # declara, en `volumen_metodo`, es que este numero ya no es una estimacion.
    return [
        {
            "replay_run_id": f[0],
            "session_id": f[1],
            "session_key": _session_key_de(f[1]),
            "source_type": f[2],
            "desde": f[3].isoformat() if f[3] else None,
            "hasta": f[4].isoformat() if f[4] else None,
            "mensajes_estimados": f[5],
            "volumen_metodo": "conteo exacto, tomado del catalogo",
            "identidad_en_columna": True,
            "catalogo_actualizado_utc": f[6].isoformat() if f[6] else None,
        }
        for f in filas
    ]


def _session_key_de(session_id: str | None) -> int | None:
    """Extrae la clave numerica de sesion del identificador, si la tiene.

    Los identificadores de la fuente deportiva llevan la clave; los de las otras
    fuentes no, y en ese caso se devuelve `None` en vez de inventar un numero.
    """
    if not session_id:
        return None
    for trozo in str(session_id).replace(":", "_").split("_"):
        if trozo.isdigit():
            return int(trozo)
    return None


def estado() -> dict[str, Any]:
    """Cuantas corridas tiene el catalogo y cuando se armo."""
    asegurar_tabla()
    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        cursor.execute(
            "SELECT count(*), max(actualizado_utc) FROM replay_runs_catalogo"
        )
        cantidad, actualizado = cursor.fetchone()
    return {
        "corridas": cantidad,
        "actualizado_utc": actualizado.isoformat() if actualizado else None,
        "reconstruyendo": _RECONSTRUYENDO,
        "vacio": cantidad == 0,
    }
