# -*- coding: utf-8 -*-
"""Degradacion a lo largo de una tanda, atribuida a sus causas medidas.

El problema, y por que parece irresoluble
----------------------------------------
Dentro de una tanda, tres cosas empujan el tiempo de vuelta a la vez: el
neumatico se gasta (mas lento), el combustible se quema (mas rapido) y la pista
evoluciona. Las tres avanzan **con el numero de vuelta**, de modo que dentro de
una tanda son la misma variable disfrazada. Ningun metodo las separa, porque no
hay nada que las separe: cuando el combustible bajo diez kilos, el neumatico
tiene siempre cinco vueltas mas.

Lo que si las separa
--------------------
**La parada en boxes.** Al cambiar el neumatico, su edad vuelve a cero de golpe;
el combustible no da ningun salto y la pista tampoco. Despues de la parada, el
mismo nivel de combustible aparece con un neumatico nuevo, y una edad de
neumatico parecida aparece con mucho menos combustible.

Medido sobre la carrera de Spa: en la vuelta 11 hay 32,7 kg con un neumatico de
diez vueltas; en la vuelta 14 hay 26,6 kg con uno de **una**. Las dos variables
dejan de moverse juntas, y el ajuste puede repartir el efecto entre ellas.

De modo que **la atribucion es posible**, y lo que la hace posible es la parada.
Una tanda sola no alcanza, y el modulo lo dice en lugar de devolver numeros que
el dato no sostiene.

La tercera causa
----------------
La evolucion de la pista no se ajusta: se **verifica que no haya cambiado**. La
fuente publica el estado del tiempo y las temperaturas, y el modulo los informa
junto con el resultado. En la carrera de Spa el codigo de clima fue el mismo de
punta a punta y las temperaturas se movieron un grado, de modo que la tercera
causa esta acotada por observacion y no por suposicion.

Si el clima **si** cambio durante la sesion, el ajuste sigue corriendo y la
advertencia viaja con el: lo que el reparto atribuya al neumatico incluira, en
ese caso, lo que la pista haya aportado.

Que se informa
--------------
El coeficiente de cada causa **con su intervalo**, y si se distingue de cero. Que
un coeficiente no se distinga es un resultado: significa que con las vueltas
disponibles la degradacion no se puede demostrar, y decirlo es mas util que
publicar una cifra que el error tipico se come.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend import db
from backend.analisis.ajuste import Ajuste, ajustar
from backend.analisis.disponibilidad import IMPOSIBLE, Disponibilidad, evaluar
from backend.analisis.vueltas import SinVueltas, extraer

SENAL_NUMERO = "lap_number"
SENAL_COMBUSTIBLE = "fuel_mass"
SENAL_EDAD = "tyre_age"
SENAL_COMPUESTO = "tyre_compound"
SENAL_CLIMA = "weather_code"
SENAL_TEMPERATURA_PISTA = "track_temperature"

#: Cuantas tandas distintas hacen falta para poder repartir el efecto. Con una
#: sola, combustible y edad avanzan juntos y el reparto no existe.
TANDAS_MINIMAS = 2


@dataclass
class Contexto:
    """Lo que rodea a la sesion y el ajuste no modela."""

    codigos_de_clima: list[float] = field(default_factory=list)
    temperaturas_de_pista: list[float] = field(default_factory=list)
    compuestos: list[float] = field(default_factory=list)

    @property
    def clima_constante(self) -> bool:
        return len(self.codigos_de_clima) <= 1

    @property
    def compuesto_unico(self) -> bool:
        return len(self.compuestos) <= 1

    def advertencias(self) -> list[str]:
        avisos = []
        if not self.clima_constante:
            avisos.append(
                "el estado del tiempo cambio durante la sesion: lo que el "
                "reparto atribuya al neumatico incluye lo que haya aportado la "
                "evolucion de la pista")
        if len(self.temperaturas_de_pista) > 1:
            rango = max(self.temperaturas_de_pista) - min(self.temperaturas_de_pista)
            if rango >= 5:
                avisos.append(
                    f"la temperatura de pista se movio {rango:,.0f} grados, que "
                    "afecta al agarre y no esta en el ajuste")
        if not self.compuesto_unico:
            avisos.append(
                "hubo mas de un compuesto: parte de la diferencia entre tandas "
                "es del compuesto y no de la edad del neumatico")
        return avisos


@dataclass
class Degradacion:
    """El reparto del tiempo de vuelta entre sus causas medidas."""

    session_id: str
    fuente: str
    disponibilidad: Disponibilidad
    contexto: Contexto
    tandas: int
    vueltas: list[tuple[int, float, float, float]] = field(default_factory=list)
    ajuste: Ajuste | None = None
    #: Por que no se pudo repartir, cuando no se pudo.
    impedimento: str | None = None

    @property
    def efecto_del_combustible_s(self) -> float | None:
        """Cuanto tiempo explica el combustible en el rango observado."""

        if self.ajuste is None or not self.vueltas:
            return None
        c = self.ajuste.por_nombre("combustible")
        if c is None:
            return None
        valores = [v[2] for v in self.vueltas]
        return round(c.valor * (max(valores) - min(valores)), 3)

    def efecto_del_neumatico_s(self, vueltas_de_tanda: int) -> float | None:
        if self.ajuste is None:
            return None
        c = self.ajuste.por_nombre("edad_neumatico")
        return None if c is None else round(c.valor * vueltas_de_tanda, 3)


def _series(cursor, fuente: str, session_id: str,
            contexto: tuple[str | None, str | None, str | None]) -> list[tuple]:
    conductor, vehiculo, corrida = contexto
    cursor.execute(
        """select timestamp, signal_name, value_numeric
           from telemetry_messages
           where source_type = %s and session_id = %s
             and driver_id is not distinct from %s
             and vehicle_id is not distinct from %s
             and replay_run_id is not distinct from %s
             and signal_name in (%s, %s, %s, %s, %s, %s)
             and value_numeric is not null
           order by timestamp""",
        (fuente, session_id, conductor, vehiculo, corrida, SENAL_NUMERO,
         SENAL_COMBUSTIBLE, SENAL_EDAD, SENAL_COMPUESTO, SENAL_CLIMA,
         SENAL_TEMPERATURA_PISTA),
    )
    return cursor.fetchall()


def analizar(fuente: str, session_id: str) -> Degradacion:
    """Reparte el tiempo de vuelta entre combustible y edad de neumatico."""

    disponible = evaluar("degradacion_por_tanda", fuente, session_id)
    if disponible.estado == IMPOSIBLE:
        raise SinVueltas(disponible)

    sesion = extraer(fuente, session_id)
    tiempos = {v.numero: v.duracion_s for v in sesion.comparables if v.duracion_s}

    ctx = disponible.contexto or (None, None, None)
    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        filas = _series(cursor, fuente, session_id, ctx)

    numero = None
    por_vuelta: dict[int, dict[str, list[float]]] = {}
    contexto = Contexto()
    for _marca, nombre, valor in filas:
        v = float(valor)
        if nombre == SENAL_NUMERO:
            numero = int(v)
            por_vuelta.setdefault(numero, {})
            continue
        if nombre == SENAL_CLIMA:
            if v not in contexto.codigos_de_clima:
                contexto.codigos_de_clima.append(v)
            continue
        if nombre == SENAL_TEMPERATURA_PISTA:
            if v not in contexto.temperaturas_de_pista:
                contexto.temperaturas_de_pista.append(v)
            continue
        if nombre == SENAL_COMPUESTO:
            if v not in contexto.compuestos:
                contexto.compuestos.append(v)
            continue
        if numero is not None:
            por_vuelta[numero].setdefault(nombre, []).append(v)

    datos: list[tuple[int, float, float, float]] = []
    for n in sorted(tiempos):
        canales = por_vuelta.get(n, {})
        combustible = canales.get(SENAL_COMBUSTIBLE)
        edad = canales.get(SENAL_EDAD)
        if not combustible or not edad:
            continue
        datos.append((n, tiempos[n],
                      sum(combustible) / len(combustible),
                      sum(edad) / len(edad)))

    # Una tanda nueva empieza cuando la edad del neumatico **baja**: es el unico
    # indicio del cambio que no depende de haber visto la parada.
    tandas = 1
    for anterior, actual in zip(datos, datos[1:]):
        if actual[3] < anterior[3]:
            tandas += 1

    resultado = Degradacion(session_id=session_id, fuente=fuente,
                            disponibilidad=disponible, contexto=contexto,
                            tandas=tandas, vueltas=datos)

    if len(datos) < 6:
        resultado.impedimento = (
            f"hacen falta al menos seis vueltas comparables y hay {len(datos)}")
        return resultado
    if tandas < TANDAS_MINIMAS:
        resultado.impedimento = (
            "hay una sola tanda: dentro de una tanda el combustible y la edad "
            "del neumatico avanzan juntos, de modo que no hay nada que permita "
            "repartir el efecto entre los dos")
        return resultado

    try:
        resultado.ajuste = ajustar(
            [d[1] for d in datos],
            [("combustible", [d[2] for d in datos], "s/kg"),
             ("edad_neumatico", [d[3] for d in datos], "s/vuelta")])
    except ValueError as error:
        resultado.impedimento = str(error)
    return resultado


def resumen(d: Degradacion) -> str:
    """Una linea con el reparto, o con el motivo de que no lo haya."""

    if d.impedimento:
        return f"sin reparto: {d.impedimento}"
    if d.ajuste is None:
        return "sin reparto"
    partes = [f"{len(d.vueltas)} vueltas en {d.tandas} tandas"]
    gl = d.ajuste.grados_de_libertad
    for nombre in ("combustible", "edad_neumatico"):
        c = d.ajuste.por_nombre(nombre)
        if c is None:
            continue
        lo, hi = c.intervalo(gl)
        marca = "" if c.distinguible(gl) else "  (no se distingue de cero)"
        partes.append(f"{nombre} {c.valor:+.4f} {c.unidad} "
                      f"[{lo:+.4f}, {hi:+.4f}]{marca}")
    for aviso in d.contexto.advertencias():
        partes.append(f"AVISO: {aviso}")
    return "; ".join(partes)
