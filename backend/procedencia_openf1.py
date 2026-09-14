# -*- coding: utf-8 -*-
"""De donde viene una sesion de la fuente deportiva.

EL HUECO QUE CIERRA. `/sesiones` enriquece cada fila con
`procedencia_sesiones.de()`, que lee los metadatos que el **capturador** escribe
junto a cada captura del simulador. Una sesion de la fuente deportiva no pasa
por el capturador y no tiene esos metadatos: su procedencia era `None`, y con
ella el circuito, el tipo y la familia. El tablero titulaba la carrera de Spa
«Sesion OpenF1 9939» teniendo `circuit_short_name = 'Spa-Francorchamps'`
guardado en `racing_sessions` desde la importacion de contexto.

DOS FUENTES DE PROCEDENCIA PARA DOS ORIGENES, Y ESTA BIEN QUE SEAN DOS. La del
simulador la declara el paquete de sesion que el juego emite en cada captura; la
de la fuente deportiva la declara su propio `session.json`, que llega dentro del
paquete. No hay una tercera forma de saberlo, y derivar el circuito de las
coordenadas seria inventar lo que el dato ya dice.

SE LEEN TODAS DE UNA VEZ. El listado trae treinta sesiones y esto llena una
columna: una consulta por sesion serian treinta viajes a la base para decorar.
"""

from __future__ import annotations

from typing import Any

from backend import db

_CONSULTA = """
SELECT session_key, circuit_short_name, country_name, session_name, session_type
  FROM racing_sessions
"""


def indice() -> dict[str, dict[str, Any]]:
    """Lo que se sabe de cada sesion deportiva, por el identificador del catalogo.

    `racing_sessions` guarda `9939`; el catalogo, `openf1:session:9939`. La
    traduccion se hace aqui y en un solo sitio.

    UN FALLO NO TUMBA EL LISTADO. Esto **decora**: dice como se llama lo que ya
    esta listado. Que la consulta no salga no puede dejar sin lista a quien
    queria abrir una sesion, y es la misma regla que gobierna el resto del
    enriquecimiento.
    """

    try:
        with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
            cursor.execute(_CONSULTA)
            filas = cursor.fetchall()
    except Exception:  # noqa: BLE001 - lo que decora no puede tumbar lo que informa
        return {}

    return {
        "openf1:session:%s" % clave: {
            "circuito": circuito,
            "pais": pais,
            "tipo_sesion_nombre": tipo_nombre,
            # La fuente publica dos campos y casi siempre coinciden. Se conserva
            # el que declara **la clase** y no el nombre de fantasia.
            "familia_de_sesion": (tipo or "").lower() or None,
        }
        for clave, circuito, pais, tipo_nombre, tipo in filas
    }
