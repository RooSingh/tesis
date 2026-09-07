# -*- coding: utf-8 -*-
"""Aplicacion de potencia y traccion a la salida de cada curva.

Que responde
------------
Donde se vuelve a abrir el acelerador tras el apice, con que progresion, y cuanto
desliza el eje motriz al hacerlo. Es la diferencia entre **pisar** y **poder
pisar**: dos conductores pueden abrir en el mismo metro y solo uno tener el
vehiculo debajo.

Se apoya en las curvas
----------------------
La pregunta es «tras el apice», de modo que necesita saber donde esta el apice.
Lo toma del catalogo de curvas, que se deriva de la aceleracion lateral y no del
acelerador: las dos mediciones siguen siendo independientes.

El deslizamiento, cuando la fuente no lo publica
------------------------------------------------
La fuente de simulacion publica el deslizamiento por rueda. El bus del vehiculo
real no, **pero publica las cuatro velocidades de rueda**, y de ahi se deriva.

La derivacion se informa marcada como tal. No es lo mismo un canal que el
fabricante calcula con lo que sabe del vehiculo que una resta entre dos
velocidades hecha aca, y confundirlos seria presentar una cuenta propia como
medicion ajena.

Y lleva una advertencia que la resta no puede resolver sola: **comparar el eje
trasero contra el delantero supone que el delantero es libre**. En un vehiculo de
traccion total ---como el del bus de este trabajo--- las cuatro ruedas reciben par
y la diferencia entre ejes ya no mide deslizamiento sino reparto. La derivacion se
ofrece con esa advertencia y no sin ella.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend import db
from backend.analisis.disponibilidad import IMPOSIBLE, Disponibilidad, evaluar
from backend.analisis.fases import fases_de_vuelta
from backend.analisis.lectura import (
    SENAL_DISTANCIA,
    SENAL_NUMERO,
    SENAL_VELOCIDAD,
    leer,
)
from backend.analisis.vueltas import SinVueltas

SENAL_ACELERADOR_CONTINUO = "throttle_position"
SENAL_ACELERADOR_BINARIO = "gas_pressed"
SENALES_DE_ACELERADOR = (SENAL_ACELERADOR_CONTINUO, SENAL_ACELERADOR_BINARIO)

SENAL_DESLIZAMIENTO = "wheel_slip_ratio_rear_left"
RUEDAS_MOTRICES = ("wheel_speed_rear_left", "wheel_speed_rear_right")
RUEDAS_LIBRES = ("wheel_speed_front_left", "wheel_speed_front_right")

#: Apertura a partir de la cual se considera que se volvio a aplicar potencia.
#: Con un acelerador binario cualquier valor positivo la cruza, que es lo
#: correcto: un interruptor solo distingue pisado de no pisado.
APERTURA_MINIMA = 5.0

#: Hasta cuantos metros despues del apice se busca la reapertura. Mas alla, lo
#: que se encuentra pertenece a la recta siguiente y no a la salida de la curva.
VENTANA_SALIDA_M = 250.0


@dataclass
class Salida:
    """La aplicacion de potencia a la salida de una curva."""

    curva: int
    apice_m: float
    #: Donde se cruza la apertura minima. `None` si no se abrio en la ventana.
    reapertura_m: float | None
    #: Metros entre el apice y la reapertura. Cuanto antes, mejor traccion.
    demora_m: float | None
    #: Apertura por metro entre la reapertura y el pleno. `None` con interruptor.
    progresion_por_metro: float | None = None
    #: Donde se llega a la apertura maxima observada en la ventana.
    pleno_m: float | None = None
    deslizamiento_maximo: float | None = None
    #: Si el deslizamiento se derivo de las velocidades de rueda en lugar de
    #: haber sido publicado por la fuente.
    deslizamiento_derivado: bool = False


@dataclass
class Traccion:
    """Las salidas de curva de una vuelta, con lo que la fuente permitio medir."""

    session_id: str
    fuente: str
    vuelta: int
    disponibilidad: Disponibilidad
    acelerador_continuo: bool = False
    deslizamiento_derivado: bool = False
    #: Advertencias que no dependen del dato sino del vehiculo o del metodo.
    advertencias: list[str] = field(default_factory=list)
    salidas: list[Salida] = field(default_factory=list)


def _senal_presente(disponible: Disponibilidad, candidatas) -> str | None:
    for medicion in disponible.mediciones:
        if medicion.presente and medicion.senal in candidatas:
            return medicion.senal
    return None


def _es_continua(disponible: Disponibilidad, senal: str) -> bool:
    for medicion in disponible.mediciones:
        if medicion.senal == senal and medicion.continua is not None:
            return bool(medicion.continua)
    return False


def _agrupar(filas, acelerador: str, deslizamiento: str | None,
             derivar: bool) -> dict[int, list[dict]]:
    """Muestras por vuelta con distancia, acelerador y deslizamiento."""

    por_vuelta: dict[int, list[dict]] = {}
    numero = None
    inicio: dict[int, object] = {}
    ultimo: dict[str, float] = {}
    for marca, nombre, valor in filas:
        if nombre == SENAL_NUMERO:
            numero = int(valor)
            continue
        if nombre != SENAL_DISTANCIA:
            ultimo[nombre] = float(valor)
            continue
        if numero is None:
            continue
        if numero not in inicio:
            inicio[numero] = marca
            por_vuelta[numero] = []

        desliz = None
        if deslizamiento is not None:
            desliz = ultimo.get(deslizamiento)
        elif derivar:
            motrices = [ultimo.get(r) for r in RUEDAS_MOTRICES]
            libres = [ultimo.get(r) for r in RUEDAS_LIBRES]
            if all(v is not None for v in motrices + libres):
                libre = sum(libres) / len(libres)
                motriz = sum(motrices) / len(motrices)
                # Sobre vehiculo detenido la division no significa nada, de modo
                # que no se calcula en lugar de devolver un numero enorme.
                desliz = (motriz - libre) / libre if abs(libre) > 1.0 else None

        por_vuelta[numero].append({
            "s": (marca - inicio[numero]).total_seconds(),
            "m": float(valor),
            "acelerador": ultimo.get(acelerador),
            "deslizamiento": desliz,
        })
    return por_vuelta


def analizar(fuente: str, session_id: str, vuelta: int,
             derivar_deslizamiento: bool = True) -> Traccion:
    """Describe la aplicacion de potencia a la salida de cada curva."""

    disponible = evaluar("potencia_y_traccion", fuente, session_id)
    if disponible.estado == IMPOSIBLE:
        raise SinVueltas(disponible)

    acelerador = _senal_presente(disponible, SENALES_DE_ACELERADOR)
    if acelerador is None:
        raise SinVueltas(disponible)
    continuo = _es_continua(disponible, acelerador)
    deslizamiento = _senal_presente(disponible, (SENAL_DESLIZAMIENTO,))

    resultado = Traccion(session_id=session_id, fuente=fuente, vuelta=vuelta,
                         disponibilidad=disponible, acelerador_continuo=continuo)

    senales = [SENAL_NUMERO, SENAL_DISTANCIA, SENAL_VELOCIDAD, acelerador]
    derivar = False
    if deslizamiento:
        senales.append(deslizamiento)
    elif derivar_deslizamiento:
        senales += list(RUEDAS_MOTRICES) + list(RUEDAS_LIBRES)
        derivar = True
        resultado.deslizamiento_derivado = True
        resultado.advertencias.append(
            "el deslizamiento no lo publica la fuente: se deriva de las cuatro "
            "velocidades de rueda, y la derivacion supone que el eje delantero "
            "es libre, lo cual no vale en un vehiculo de traccion total")

    if not continuo:
        resultado.advertencias.append(
            "el acelerador llega como interruptor: se informa donde se vuelve a "
            "aplicar potencia, pero no con que progresion")

    ctx = disponible.contexto or (None, None, None)
    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        filas = leer(cursor, fuente, session_id, ctx, tuple(senales))
    muestras = _agrupar(filas, acelerador, deslizamiento, derivar).get(vuelta, [])
    if not muestras:
        return resultado

    for curva in fases_de_vuelta(fuente, session_id, vuelta):
        ventana = [m for m in muestras
                   if curva.apice_lateral_m <= m["m"]
                   <= curva.apice_lateral_m + VENTANA_SALIDA_M
                   and m.get("acelerador") is not None]
        if not ventana:
            continue

        reapertura = next((m["m"] for m in ventana
                           if m["acelerador"] >= APERTURA_MINIMA), None)
        salida = Salida(
            curva=curva.numero, apice_m=curva.apice_lateral_m,
            reapertura_m=(round(reapertura, 1) if reapertura is not None else None),
            demora_m=(round(reapertura - curva.apice_lateral_m, 1)
                      if reapertura is not None else None),
            deslizamiento_derivado=derivar)

        if reapertura is not None:
            desde = [m for m in ventana if m["m"] >= reapertura]
            maximo = max(m["acelerador"] for m in desde)
            pleno = next((m["m"] for m in desde if m["acelerador"] >= maximo), None)
            salida.pleno_m = round(pleno, 1) if pleno is not None else None
            if continuo and pleno is not None and pleno > reapertura:
                salida.progresion_por_metro = round(
                    (maximo - APERTURA_MINIMA) / (pleno - reapertura), 3)
            deslizamientos = [m["deslizamiento"] for m in desde
                              if m.get("deslizamiento") is not None]
            if deslizamientos:
                salida.deslizamiento_maximo = round(max(deslizamientos), 4)
        resultado.salidas.append(salida)
    return resultado


def resumen(t: Traccion) -> str:
    """Una linea con las salidas medidas y lo que la fuente no permitio medir."""

    partes = [f"{len(t.salidas)} salidas de curva en la vuelta {t.vuelta}"]
    demoras = [s.demora_m for s in t.salidas if s.demora_m is not None]
    if demoras:
        partes.append(f"reapertura mediana a {sorted(demoras)[len(demoras) // 2]:,.0f} m "
                      f"del apice")
    for aviso in t.advertencias:
        partes.append(f"AVISO: {aviso}")
    return "; ".join(partes)
