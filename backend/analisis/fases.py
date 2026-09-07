# -*- coding: utf-8 -*-
"""Curvas de una sesion y las fases de cada una.

Que agrega sobre `curvas.py`
----------------------------
`curvas.py` responde **donde estan las curvas** derivandolas del dato: una curva
es donde el vehiculo sostiene aceleracion lateral. Ese modulo es una funcion pura
que recibe pares de distancia y aceleracion, y hasta aca solo lo alimentaba el
anotador en vivo, desde marcos de captura cruda de una fuente concreta.

Este lo alimenta **desde el contrato interno**, de modo que la misma deteccion
corre sobre cualquier fuente que declare las magnitudes, y agrega lo que la
herramienta promete y aquel no da: **entrada, apice y salida como tramos
distintos**, con su velocidad y su duracion.

Donde empieza la entrada
------------------------
La fase de entrada arranca **donde la aceleracion lateral cruza el umbral de
giro**, y no en el punto de frenada.

La eleccion no es de comodidad. Un ingeniero de rendimiento llama entrada al tramo
que empieza al frenar, y esa definicion seria la natural si el analisis viviera
sobre una sola fuente. Pero ata la herramienta al canal de freno, que dos de las
tres fuentes del trabajo entregan como interruptor y que una cuarta podria no
entregar: la deteccion de curvas dejaria de funcionar por falta de un canal que
las curvas no necesitan.

Cuando el freno **si** esta disponible, el punto de frenada se agrega como
enriquecimiento y **se declara como tal**. Es dato adicional sobre la misma curva,
no una definicion distinta de la curva.

Por que el apice es un punto y no un tramo
------------------------------------------
Nombrar un tramo de apice exigiria un umbral ---«donde la lateral supera tal
fraccion del pico»--- que ningun canal declara y que habria que elegir. El trabajo
no admite umbrales elegidos, de modo que el apice se informa como punto.

Se informan **dos puntos y no uno**, porque hay dos anclajes posibles y no
coinciden: el maximo de aceleracion lateral, que es el que `curvas.py` usa para
ordenar el catalogo, y el minimo de velocidad, que es el que
`backend/catalogo_curvas.py` usa para anclar los nombres. Su separacion es en si
misma una magnitud observable, y elegir uno en silencio la borraria.

El catalogo se deriva una vez
-----------------------------
Derivar el catalogo exige recorrer varias vueltas, de modo que se cachea por
sesion. Es la misma decision que toma la matriz de fuentes, y por el mismo motivo:
lo que no cambia entre consultas no se recalcula en cada una.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from backend import db
from backend.analisis import curvas as mod_curvas
from backend.analisis.lectura import (
    SENAL_FRENO,
    SENAL_LATERAL,
    SENAL_NUMERO,
    SENAL_DISTANCIA,
    SENAL_VELOCIDAD,
    leer,
    muestras_por_vuelta,
)
from backend.analisis.disponibilidad import IMPOSIBLE, Disponibilidad, evaluar
from backend.analisis.vueltas import SinVueltas, extraer


#: Cuanto vive el catalogo derivado de una sesion. Una sesion cerrada no cambia,
#: de modo que el unico motivo del vencimiento es no retener memoria para siempre.
VIGENCIA_S = 300.0

#: Cuanto antes del comienzo de la curva se busca el punto de frenada que la
#: precede. Doscientos metros a 200 km/h son tres segundos y medio: mas que
#: suficiente para cualquier frenada, y poco para alcanzar la curva anterior.
VENTANA_FRENADA_M = 200.0

_CACHE: dict[tuple[str, str], tuple[float, "Trazado"]] = {}


@dataclass
class Fase:
    """Un tramo de la curva, con lo que se midio en el."""

    nombre: str
    desde_m: float
    hasta_m: float
    duracion_s: float | None
    velocidad_entrada_kmh: float | None
    velocidad_salida_kmh: float | None

    @property
    def largo_m(self) -> float:
        return round(self.hasta_m - self.desde_m, 1)


@dataclass
class CurvaEnVuelta:
    """Una curva recorrida en una vuelta concreta."""

    numero: int
    desde_m: float
    hasta_m: float
    #: Maximo de aceleracion lateral. Es el anclaje con que se ordena el catalogo.
    apice_lateral_m: float
    #: Minimo de velocidad. Es el anclaje con que se rotulan los nombres.
    apice_velocidad_m: float | None
    velocidad_minima_kmh: float | None
    pico_lateral_g: float
    fases: list[Fase] = field(default_factory=list)
    #: Enriquecimiento, solo cuando el canal de freno esta disponible.
    punto_de_frenada_m: float | None = None
    #: Nombre externo, cuando el catalogo del circuito lo tiene. Es anotacion.
    nombre: str | None = None

    @property
    def separacion_de_apices_m(self) -> float | None:
        """Cuanto distan los dos anclajes. Se informa en lugar de elegir uno."""

        if self.apice_velocidad_m is None:
            return None
        return round(self.apice_velocidad_m - self.apice_lateral_m, 1)


@dataclass
class Trazado:
    """El catalogo de curvas de una sesion, con lo que lo respalda."""

    session_id: str
    fuente: str
    disponibilidad: Disponibilidad
    catalogo: mod_curvas.CatalogoDeCurvas
    vueltas_usadas: list[int] = field(default_factory=list)
    #: Si el enriquecimiento por punto de frenada esta disponible en esta sesion.
    con_frenada: bool = False


def _en_rango(muestras: list[dict], desde: float, hasta: float) -> list[dict]:
    return [m for m in muestras if desde <= m["m"] <= hasta]


def _extremo(muestras: list[dict], clave: str, menor: bool) -> dict | None:
    validas = [m for m in muestras if m.get(clave) is not None]
    if not validas:
        return None
    return (min if menor else max)(validas, key=lambda m: m[clave])


def _fase(nombre: str, muestras: list[dict], desde: float,
          hasta: float) -> Fase:
    tramo = _en_rango(muestras, desde, hasta)
    duracion = None
    entrada = salida = None
    if tramo:
        duracion = round(tramo[-1]["s"] - tramo[0]["s"], 3)
        entrada = tramo[0].get("velocidad")
        salida = tramo[-1].get("velocidad")
    return Fase(nombre=nombre, desde_m=round(desde, 1), hasta_m=round(hasta, 1),
                duracion_s=duracion,
                velocidad_entrada_kmh=entrada, velocidad_salida_kmh=salida)


def _punto_de_frenada(muestras: list[dict], desde_m: float) -> float | None:
    """El metro donde empieza la frenada que precede a la curva.

    Se busca hacia atras el primer instante en que el freno deja de estar suelto,
    dentro de una ventana acotada. Fuera de esa ventana no se busca: una frenada
    que empezara doscientos metros antes seria la de la curva anterior.
    """

    ventana = [m for m in muestras
               if desde_m - VENTANA_FRENADA_M <= m["m"] <= desde_m
               and m.get("freno") is not None]
    if not ventana:
        return None
    # Se busca el comienzo de la **ultima tanda continua de freno** de la
    # ventana, y no el de una que siga pisada al llegar a la curva.
    #
    # La primera version exigia lo segundo ---reiniciaba el comienzo en cuanto el
    # freno se soltaba--- y encontraba el punto de frenada de **una sola** de las
    # veinte curvas. El motivo es que soltar el freno antes de entrar es lo
    # normal: se frena en recta y se libera al girar. La regla pedia justamente la
    # excepcion.
    ultimo_comienzo = None
    comienzo = None
    for m in ventana:
        if m["freno"] > 0:
            if comienzo is None:
                comienzo = m["m"]
                ultimo_comienzo = comienzo
        else:
            comienzo = None
    return round(ultimo_comienzo, 1) if ultimo_comienzo is not None else None


def trazado(fuente: str, session_id: str,
            refrescar: bool = False) -> Trazado:
    """Deriva el catalogo de curvas de la sesion, y lo cachea.

    Se derivan **solo las vueltas comparables**: `curvas.py` descarta lo que no se
    repite entre vueltas, pero ese criterio de mayoria deja de servir si la
    mayoria de las vueltas tiene incidentes.
    """

    clave = (fuente, session_id)
    ahora = time.monotonic()
    if not refrescar and clave in _CACHE and ahora - _CACHE[clave][0] < VIGENCIA_S:
        return _CACHE[clave][1]

    disponible = evaluar("curvas_y_fases", fuente, session_id)
    if disponible.estado == IMPOSIBLE:
        raise SinVueltas(disponible)

    sesion = extraer(fuente, session_id)
    comparables = [v.numero for v in sesion.comparables]
    if not comparables:
        raise SinVueltas(disponible)

    contexto = disponible.contexto or (None, None, None)
    presentes = {m.senal for m in disponible.mediciones if m.presente and m.senal}
    con_frenada = SENAL_FRENO in presentes
    senales = (SENAL_NUMERO, SENAL_DISTANCIA, SENAL_LATERAL, SENAL_VELOCIDAD)
    if con_frenada:
        senales = senales + (SENAL_FRENO,)

    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        filas = leer(cursor, fuente, session_id, contexto, senales)

    por_vuelta = muestras_por_vuelta(filas)
    entradas = [
        [(m["m"], m["lateral"]) for m in por_vuelta[n] if m["lateral"] is not None]
        for n in comparables if n in por_vuelta
    ]
    entradas = [v for v in entradas if len(v) > 1]
    catalogo = mod_curvas.derivar(entradas, circuito=session_id)

    resultado = Trazado(session_id=session_id, fuente=fuente,
                        disponibilidad=disponible, catalogo=catalogo,
                        vueltas_usadas=comparables, con_frenada=con_frenada)
    _CACHE[clave] = (ahora, resultado)
    return resultado


def fases_de_vuelta(fuente: str, session_id: str,
                    vuelta: int) -> list[CurvaEnVuelta]:
    """Las curvas de una vuelta, cada una con sus fases medidas."""

    t = trazado(fuente, session_id)
    contexto = t.disponibilidad.contexto or (None, None, None)
    senales = (SENAL_NUMERO, SENAL_DISTANCIA, SENAL_LATERAL, SENAL_VELOCIDAD)
    if t.con_frenada:
        senales = senales + (SENAL_FRENO,)

    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        filas = leer(cursor, fuente, session_id, contexto, senales)
    muestras = muestras_por_vuelta(filas).get(vuelta, [])
    if not muestras:
        return []

    resultado: list[CurvaEnVuelta] = []
    for curva in t.catalogo.curvas:
        tramo = _en_rango(muestras, curva.desde_m, curva.hasta_m)
        if not tramo:
            continue
        minimo = _extremo(tramo, "velocidad", menor=True)
        c = CurvaEnVuelta(
            numero=curva.numero, desde_m=curva.desde_m, hasta_m=curva.hasta_m,
            apice_lateral_m=curva.apice_m,
            apice_velocidad_m=(round(minimo["m"], 1) if minimo else None),
            velocidad_minima_kmh=(minimo["velocidad"] if minimo else None),
            pico_lateral_g=curva.pico_g)
        # Las dos fases se separan en el apice de aceleracion lateral, que es el
        # anclaje con que el catalogo esta construido. Separarlas en el minimo de
        # velocidad daria tramos distintos sobre la misma curva segun el anclaje,
        # y la separacion entre los dos anclajes ya se informa aparte.
        c.fases = [
            _fase("entrada", muestras, curva.desde_m, curva.apice_m),
            _fase("salida", muestras, curva.apice_m, curva.hasta_m),
        ]
        if t.con_frenada:
            c.punto_de_frenada_m = _punto_de_frenada(muestras, curva.desde_m)
        resultado.append(c)
    return resultado


def limpiar_cache() -> None:
    """Vacia el catalogo cacheado. Existe para las pruebas y para forzar una
    rederivacion cuando la sesion recibio filas nuevas."""

    _CACHE.clear()
