# -*- coding: utf-8 -*-
"""Leer un fuente para preguntarle por su forma, sin que el comentario estorbe.

POR QUE EXISTE. Varias pruebas de este proyecto no comprueban conducta sino
**forma**: «¿esta escrita esta llamada?», «¿quedo esta constante a mano?». Son
las que atajan el defecto que todavia no ocurrio, porque el codigo que lo
cometeria no existe y ninguna prueba de conducta puede ejercitarlo.

Tienen un modo de fallar propio y muy repetido: **el comentario que explica la
guarda la rompe**, porque para explicar que algo no debe escribirse hay que
escribirlo. Paso ocho veces el 2026-09-13, en los dos lenguajes del proyecto.

EL EQUIVALENTE DE JAVASCRIPT vive en `test_dashboard_frontend.py` y tiene que
aproximarse con expresiones regulares; lo declara: «no es un analizador y no
pretende serlo». En Python no hace falta aproximar, y por eso esto usa
`tokenize`, que es el mismo lexico del interprete: una almohadilla dentro de
una cadena no lo confunde.

SE QUITAN LOS COMENTARIOS Y **NO** LAS CADENAS, y eso decide si la guarda sirve
o no. La primera version quitaba las dos y con eso dejaba de mirar justo lo que
prohibe, porque un nombre escrito a mano **es** una cadena: pasaba en verde con
el defecto puesto. Se descubrio mutando el modulo vigilado. Una guarda
estructural que no se muto no esta comprobada.

Los docstrings sobreviven a proposito: si alguien escribe ahi dentro lo que la
guarda prohibe, sigue siendo un segundo sitio donde figura.
"""

from __future__ import annotations

import tokenize
from pathlib import Path


def solo_codigo(ruta: Path) -> str:
    """El modulo sin sus comentarios. Las cadenas se conservan."""

    partes = []
    with Path(ruta).open("rb") as f:
        for token in tokenize.tokenize(f.readline):
            if token.type == tokenize.COMMENT:
                continue
            partes.append(token.string)
    return " ".join(partes)
