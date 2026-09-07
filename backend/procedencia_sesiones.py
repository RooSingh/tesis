# -*- coding: utf-8 -*-
"""Que es cada sesion: circuito, tipo, clima y vueltas.

EL HUECO QUE CIERRA
-------------------
La base guarda la procedencia **tecnica** de cada mensaje ---identificador de
sesion, paquete, marco, los dos relojes--- y nada que diga **que es** esa
sesion. Una clasificacion y una carrera se ven iguales en la lista: dos
identificadores numericos con muchas filas.

El dato existe y esta derivado. El capturador lo lee del propio flujo ---del
paquete de sesion--- y lo escribe en el archivo de metadatos de cada captura:
circuito, tipo de sesion, modo de juego, clima, temperaturas, vueltas totales y
dificultad. Al 2026-09-07 hay **69 capturas y las 69 lo declaran**.

Lo que faltaba era que ese archivo cruzara a la consulta. Es la misma clase de
hueco que dejo trece senales de ochenta y nueve fuera de la persistencia:
informacion derivada correctamente que no atraviesa una frontera.

COMO SE UNE
-----------
Por `session_uid`. El identificador de la base es `f1_25:session:<uid>` y el
metadato de captura declara ese mismo `uid` en su procedencia. No hace falta
adivinar por fecha ni por nombre de archivo.

QUE NO HACE
-----------
No copia nada a la base. Lee los archivos, que son la fuente, y los deja donde
estan. Persistir la procedencia es una decision de esquema que corresponde a
otra jornada; esto la hace consultable mientras tanto, sin adelantarse.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

#: Donde viven los metadatos de captura.
DIRECTORIO = Path(__file__).resolve().parent.parent / "datasets" / "f1_25" / "capturas"

#: Cuanto se conserva el indice antes de releer el directorio. Los archivos
#: cambian solo cuando se captura, que no ocurre mientras alguien consulta.
VIGENCIA_S = 300.0

#: Como se lee cada tipo de sesion. Las claves son las que escribe el
#: capturador, derivadas del identificador oficial del paquete de sesion.
LECTURA_DEL_TIPO = {
    "practica-corta": ("Práctica", "practica"),
    "practica-1": ("Práctica 1", "practica"),
    "practica-2": ("Práctica 2", "practica"),
    "practica-3": ("Práctica 3", "practica"),
    "clasificacion-1": ("Clasificación 1", "clasificacion"),
    "clasificacion-2": ("Clasificación 2", "clasificacion"),
    "clasificacion-3": ("Clasificación 3", "clasificacion"),
    "clasificacion-corta": ("Clasificación corta", "clasificacion"),
    "sprint-shootout-1": ("Sprint shootout 1", "sprint"),
    "sprint-shootout-2": ("Sprint shootout 2", "sprint"),
    "sprint-shootout-3": ("Sprint shootout 3", "sprint"),
    "carrera": ("Carrera", "carrera"),
    "carrera-2": ("Carrera 2", "carrera"),
    "carrera-sprint": ("Carrera sprint", "sprint"),
    "contrarreloj": ("Contrarreloj", "contrarreloj"),
}

_CACHE: tuple[float, dict[str, dict]] | None = None


def _leer_uno(ruta: Path) -> tuple[str, dict] | None:
    """Lee un metadato de captura y devuelve su sesion y su procedencia."""
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

    proc = datos.get("procedencia") or {}
    uid = proc.get("session_uid")
    if uid is None:
        return None

    crudo = proc.get("tipo_sesion")
    nombre, familia = LECTURA_DEL_TIPO.get(crudo, (crudo or "sin declarar", "otro"))

    return "f1_25:session:%s" % uid, {
        "circuito": proc.get("circuito"),
        "circuito_id": proc.get("circuito_id"),
        "longitud_declarada_m": proc.get("longitud_declarada_m"),
        "tipo_sesion": crudo,
        "tipo_sesion_nombre": nombre,
        "familia_de_sesion": familia,
        "modo_juego": proc.get("modo_juego"),
        "clima": proc.get("clima"),
        "temperatura_pista_c": proc.get("temperatura_pista_c"),
        "temperatura_aire_c": proc.get("temperatura_aire_c"),
        "vueltas_totales": proc.get("vueltas_totales"),
        "dificultad_ia": proc.get("dificultad_ia"),
        "capturado_utc": datos.get("inicio_utc"),
        "duracion_capturada_s": datos.get("duracion_s"),
        "archivo": datos.get("archivo"),
        "origen": "metadato de captura, derivado del paquete de sesion",
    }


def indice(refrescar: bool = False) -> dict[str, dict]:
    """Procedencia de cada sesion de simulacion, indexada por `session_id`.

    Si dos capturas comparten `session_uid` ---dos tramos de la misma sesion---
    gana la mas larga, que es la que mejor la describe.
    """
    global _CACHE
    ahora = time.monotonic()
    if _CACHE and not refrescar and ahora - _CACHE[0] < VIGENCIA_S:
        return _CACHE[1]

    salida: dict[str, dict] = {}
    if DIRECTORIO.is_dir():
        for ruta in sorted(DIRECTORIO.glob("*.meta.json")):
            leido = _leer_uno(ruta)
            if not leido:
                continue
            sesion, proc = leido
            previo = salida.get(sesion)
            if previo and (previo.get("duracion_capturada_s") or 0) >= (
                    proc.get("duracion_capturada_s") or 0):
                continue
            salida[sesion] = proc

    _CACHE = (ahora, salida)
    return salida


def de(session_id: str) -> dict[str, Any] | None:
    """Procedencia de una sesion, o `None` si no se conoce."""
    return indice().get(session_id)


def resumen() -> dict[str, Any]:
    """Cuantas sesiones se conocen y de que tipo son."""
    todas = indice()
    por_familia: dict[str, int] = {}
    por_circuito: dict[str, int] = {}
    for p in todas.values():
        por_familia[p["familia_de_sesion"]] = por_familia.get(p["familia_de_sesion"], 0) + 1
        c = p.get("circuito") or "sin declarar"
        por_circuito[c] = por_circuito.get(c, 0) + 1
    return {
        "sesiones_con_procedencia": len(todas),
        "por_familia": por_familia,
        "por_circuito": por_circuito,
        "origen": str(DIRECTORIO),
    }
