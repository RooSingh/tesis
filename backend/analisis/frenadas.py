# -*- coding: utf-8 -*-
"""Caracterizacion de las zonas de frenada de una vuelta.

Que informa
-----------
Por cada frenada: donde empieza, cuanto dura, con que velocidad se entra y cual es
la minima alcanzada. Es donde mas tiempo se gana y se pierde.

Que informa **solo a veces**, y por que se dice
-----------------------------------------------
La presion maxima y la modulacion de la frenada exigen que el freno llegue como
escala. Dos de las tres fuentes del trabajo lo entregan como interruptor, y esa
diferencia no se puede tapar: informar «presion maxima: 1,0» para un interruptor
seria presentar como medicion algo que nadie midio.

Con un interruptor **si** se miden el comienzo, la duracion y las velocidades. De
ahi que la herramienta corra igual sobre las tres fuentes y **declare** cual de sus
resultados no va a dar en cada una.

La resolucion tambien decide
----------------------------
Una fuente puede tener el canal y aun asi no ubicar la frenada. La referencia del
oficio es que diez metros de diferencia en el punto de frenada valen una decima de
segundo, de modo que una fuente cuyas muestras disten quince metros no distingue lo
que la herramienta existe para distinguir. Esa limitacion la declara el evaluador
de disponibilidad, y llega hasta aca junto con el resultado.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend import db
from backend.analisis.disponibilidad import IMPOSIBLE, Disponibilidad, evaluar
from backend.analisis.lectura import (
    SENAL_DISTANCIA,
    SENAL_NUMERO,
    SENAL_VELOCIDAD,
    leer,
    muestras_por_vuelta,
)
from backend.analisis.vueltas import SinVueltas

#: Los tres nombres que las fuentes le dan al freno. La correspondencia ya vive en
#: el catalogo de magnitudes; aca se listan para pedirlas a la base.
SENALES_DE_FRENO = ("brake_position", "brake_applied", "brake_pressed")

#: Cuanto puede soltarse el freno dentro de una misma frenada sin que se la
#: considere terminada. Un instante de alivio en mitad de una frenada larga es
#: modulacion, no dos frenadas: cortarla ahi la contaria dos veces.
#:
#: Es el mismo criterio con que `curvas.py` une tramos de giro, y el mismo valor,
#: por el mismo motivo: los dos separan un fenomeno sostenido de uno repetido.
UNION_M = 45.0

#: Largo minimo para que un tramo sea una frenada y no un roce del pedal.
MINIMO_M = 10.0


@dataclass
class Frenada:
    """Una zona de frenada, con lo que la fuente permitio medir."""

    desde_m: float
    hasta_m: float
    duracion_s: float | None
    velocidad_entrada_kmh: float | None
    velocidad_minima_kmh: float | None
    #: Solo cuando el freno llega como escala. `None` cuando es interruptor, y esa
    #: ausencia esta declarada en la disponibilidad, no escondida en un cero.
    presion_maxima: float | None = None
    muestras: int = 0

    @property
    def largo_m(self) -> float:
        return round(self.hasta_m - self.desde_m, 1)

    @property
    def caida_kmh(self) -> float | None:
        if self.velocidad_entrada_kmh is None or self.velocidad_minima_kmh is None:
            return None
        return round(self.velocidad_entrada_kmh - self.velocidad_minima_kmh, 1)


@dataclass
class Frenadas:
    """Las frenadas de una vuelta, con la declaracion que las describe."""

    session_id: str
    fuente: str
    vuelta: int
    disponibilidad: Disponibilidad
    #: Si el freno llego como escala. Decide si hay presion que informar.
    freno_continuo: bool = False
    frenadas: list[Frenada] = field(default_factory=list)

    def como_dict(self) -> dict:
        return {
            "session_id": self.session_id, "fuente": self.fuente,
            "vuelta": self.vuelta, "freno_continuo": self.freno_continuo,
            "disponibilidad": self.disponibilidad.como_dict(),
            "frenadas": [
                {"desde_m": f.desde_m, "hasta_m": f.hasta_m,
                 "largo_m": f.largo_m, "duracion_s": f.duracion_s,
                 "velocidad_entrada_kmh": f.velocidad_entrada_kmh,
                 "velocidad_minima_kmh": f.velocidad_minima_kmh,
                 "caida_kmh": f.caida_kmh, "presion_maxima": f.presion_maxima}
                for f in self.frenadas
            ],
        }


def _senal_de_freno(disponible: Disponibilidad) -> str | None:
    for medicion in disponible.mediciones:
        if medicion.presente and medicion.senal in SENALES_DE_FRENO:
            return medicion.senal
    return None


def _freno_es_continuo(disponible: Disponibilidad, senal: str) -> bool:
    for medicion in disponible.mediciones:
        if medicion.senal == senal and medicion.continua is not None:
            return bool(medicion.continua)
    return False


def _tramos(muestras: list[dict], clave: str) -> list[list[dict]]:
    """Separa las tandas continuas en que el freno esta aplicado."""

    tramos: list[list[dict]] = []
    abierto: list[dict] = []
    for m in muestras:
        valor = m.get(clave)
        if valor is None:
            continue
        if valor > 0:
            if abierto and m["m"] - abierto[-1]["m"] > UNION_M:
                tramos.append(abierto)
                abierto = []
            abierto.append(m)
        elif abierto and m["m"] - abierto[-1]["m"] > UNION_M:
            tramos.append(abierto)
            abierto = []
    if abierto:
        tramos.append(abierto)
    return [t for t in tramos if t[-1]["m"] - t[0]["m"] >= MINIMO_M]


def caracterizar(fuente: str, session_id: str, vuelta: int) -> Frenadas:
    """Encuentra y describe las frenadas de una vuelta.

    Lo que no se puede medir con la fuente dada no se completa con un valor por
    defecto: queda en `None`, y el motivo esta en la disponibilidad que viaja con
    el resultado.
    """

    disponible = evaluar("zonas_de_frenada", fuente, session_id)
    if disponible.estado == IMPOSIBLE:
        raise SinVueltas(disponible)

    senal_freno = _senal_de_freno(disponible)
    if senal_freno is None:
        raise SinVueltas(disponible)
    continuo = _freno_es_continuo(disponible, senal_freno)

    contexto = disponible.contexto or (None, None, None)
    senales = (SENAL_NUMERO, SENAL_DISTANCIA, SENAL_VELOCIDAD, senal_freno)
    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        filas = leer(cursor, fuente, session_id, contexto, senales)

    # `_muestras_por_vuelta` arrastra el freno bajo la clave con que se pidio, de
    # modo que se lo renombra a una clave estable para no repartir el nombre de
    # la senal por todo el modulo.
    por_vuelta = muestras_por_vuelta(filas, freno=senal_freno)
    muestras = por_vuelta.get(vuelta, [])

    resultado = Frenadas(session_id=session_id, fuente=fuente, vuelta=vuelta,
                         disponibilidad=disponible, freno_continuo=continuo)
    for tramo in _tramos(muestras, "freno"):
        velocidades = [m["velocidad"] for m in tramo if m.get("velocidad") is not None]
        presiones = [m["freno"] for m in tramo if m.get("freno") is not None]
        resultado.frenadas.append(Frenada(
            desde_m=round(tramo[0]["m"], 1), hasta_m=round(tramo[-1]["m"], 1),
            duracion_s=round(tramo[-1]["s"] - tramo[0]["s"], 3),
            velocidad_entrada_kmh=(velocidades[0] if velocidades else None),
            velocidad_minima_kmh=(min(velocidades) if velocidades else None),
            # La presion solo existe si la escala existe. Con un interruptor el
            # maximo seria siempre uno, y publicarlo lo haria pasar por medicion.
            presion_maxima=(max(presiones) if continuo and presiones else None),
            muestras=len(tramo)))
    return resultado


def resumen(f: Frenadas) -> str:
    """Una linea con cuantas frenadas hubo y que no se pudo medir."""

    partes = [f"{len(f.frenadas)} frenadas en la vuelta {f.vuelta}"]
    if f.frenadas:
        caidas = [x.caida_kmh for x in f.frenadas if x.caida_kmh is not None]
        if caidas:
            partes.append(f"la mas fuerte baja {max(caidas):,.0f} km/h")
    if not f.freno_continuo:
        partes.append("sin presion: la fuente entrega el freno como interruptor")
    if f.disponibilidad.limitaciones:
        partes.append(f"{len(f.disponibilidad.limitaciones)} limitaciones declaradas")
    return "; ".join(partes)
