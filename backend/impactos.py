# -*- coding: utf-8 -*-
"""Caracteriza una colision ya declarada: hacia donde empujo y cuanto costo.

Que hace y que no
-----------------
**No detecta colisiones.** El propio juego las declara con el evento ``COLL``,
que nombra los dos vehiculos involucrados. Lo que falta ---y lo que este modulo
resuelve--- es que clase de colision fue, porque el evento no lo dice: la
especificacion declara "primer vehiculo involucrado" y "segundo vehiculo
involucrado", sin ninguna nocion de quien la provoco.

El planteo importa. Si tuvieramos que **descubrir** el golpe en la telemetria
harian falta umbrales de deteccion, y la perdida de velocidad no alcanza para
eso: sobre la primera pasada de la prueba de dos conductores, el 3,4 % de los
segundos sin frenar ya pierde mas de 30 km/h, porque levantar el pie en una curva
tambien frena. Como el golpe ya viene declarado, el problema pasa a ser
**caracterizar un instante conocido**, que es mucho mas facil de sostener.

De donde salen los umbrales
---------------------------
De medir lo que el auto puede hacer **por si solo**, en la propia captura y sobre
los dos conductores, con el auto por encima de 30 km/h:

===========================  ==========  =========================
condicion                    muestras    aceleracion longitudinal
===========================  ==========  =========================
frenando (freno > 0,5)          601      mediana -3,13 g, minimo **-4,31 g**
acelerando (acelerador > 0,9)  4.392     mediana +0,64 g, maximo **+2,03 g**
===========================  ==========  =========================

Los frenos nunca pasaron de 4,31 g de desaceleracion y el motor nunca de 2,03 g
de empuje. En los mismos giros se midieron picos de **-15,89 g** y **+10,65 g**,
los dos con los pedales sin tocar. Un valor asi no lo produce el auto: viene de
afuera.

Por eso la envolvente es **direccional** y no un unico numero. El motor empuja
mucho menos de lo que los frenos retienen, de modo que un empuje de +3 g ya es
imposible mientras una desaceleracion de -3 g es una frenada comun.

Lo que esto **no** dice
-----------------------
La culpa. Que a uno lo empujen desde atras suele significar que el otro es
responsable, salvo que haya frenado de golpe delante de el; llevarse por delante
al de adelante suele ser responsabilidad propia, salvo que el de adelante haya
frenado sin motivo. **La responsabilidad es un juicio de comisarios y no una
magnitud fisica**, y este modulo no la calcula. Se queda en la direccion y el
tamano del impulso, que si se miden.

El juego tiene su propio veredicto, en el evento ``PENA``, y viaja aparte: es un
dato distinto y se cita como lo que es.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Empuje maximo que se midio con el acelerador a fondo. Por encima de esto, un
#: impulso hacia adelante no lo puede estar dando el motor.
ENVOLVENTE_MOTOR_G = 2.1

#: Desaceleracion maxima que se midio con el freno aplicado. Por debajo de esto,
#: una desaceleracion no la pueden estar dando los frenos.
ENVOLVENTE_FRENOS_G = 4.4

#: Ventana alrededor del instante declarado en la que se busca el pico.
#:
#: El evento y los canales no llegan en el mismo paquete, de modo que el instante
#: declarado y la muestra del pico no coinciden exactamente. Medio segundo cubre
#: diez muestras a 20 Hz sin alcanzar a tomar el frenado de la curva siguiente.
VENTANA_S = 0.5

#: Clasificaciones posibles. Se nombran por lo que se midio y no por la causa.
EMPUJADO_DESDE_ATRAS = "empujado-desde-atras"
FRENADO_POR_ALGO_ADELANTE = "frenado-por-algo-adelante"
SIN_IMPULSO_MEDIBLE = "sin-impulso-medible"


@dataclass(frozen=True)
class Muestra:
    """Un instante de los canales que la caracterizacion necesita."""

    tiempo_s: float
    aceleracion_longitudinal_g: float | None
    velocidad_kmh: float | None
    freno: float | None
    acelerador: float | None


@dataclass
class Impacto:
    """Como fue una colision que el juego ya declaro."""

    tiempo_s: float
    #: Una de las tres constantes de clasificacion.
    clasificacion: str
    #: El pico de aceleracion longitudinal en la ventana, con su signo.
    pico_g: float | None
    #: Cuanto excede el pico a lo que los pedales pueden dar en esa direccion.
    #: Es la evidencia de que el impulso vino de afuera, y viaja con el impacto.
    veces_la_envolvente: float | None
    velocidad_antes_kmh: float | None
    velocidad_despues_kmh: float | None
    freno_aplicado: float | None
    acelerador_aplicado: float | None
    #: Por que se clasifico asi, en una linea, para que la anotacion pueda
    #: mostrarla sin que nadie tenga que reconstruir el razonamiento.
    fundamento: str = ""

    @property
    def velocidad_perdida_kmh(self) -> float | None:
        if self.velocidad_antes_kmh is None or self.velocidad_despues_kmh is None:
            return None
        return self.velocidad_antes_kmh - self.velocidad_despues_kmh


@dataclass
class Envolvente:
    """Lo que el auto puede hacer solo, medido en una captura concreta.

    Se mide y no se hereda: un auto distinto, un circuito distinto o un reglaje
    distinto mueven estos numeros, y usar los de otra captura seria afirmar algo
    que no se comprobo aca.
    """

    empuje_maximo_g: float = ENVOLVENTE_MOTOR_G
    desaceleracion_maxima_g: float = ENVOLVENTE_FRENOS_G
    muestras_acelerando: int = 0
    muestras_frenando: int = 0
    #: Verdadero cuando los valores son los medidos y no los de referencia.
    medida: bool = False


def medir_envolvente(muestras: list[Muestra],
                     velocidad_minima_kmh: float = 30.0) -> Envolvente:
    """Mide cuanto empuja el motor y cuanto retienen los frenos.

    Se descartan las muestras por debajo de una velocidad minima: con el auto
    detenido o casi, el canal longitudinal no informa sobre lo que el auto puede.
    """

    frenando: list[float] = []
    acelerando: list[float] = []
    for m in muestras:
        if m.aceleracion_longitudinal_g is None or m.velocidad_kmh is None:
            continue
        if m.velocidad_kmh < velocidad_minima_kmh:
            continue
        if (m.freno or 0) > 0.5:
            frenando.append(m.aceleracion_longitudinal_g)
        elif (m.acelerador or 0) > 0.9:
            acelerando.append(m.aceleracion_longitudinal_g)

    if not frenando or not acelerando:
        # Sin material para medir se devuelven los valores de referencia, y se
        # declara que son de referencia: callarlo haria pasar por medido algo
        # que no se midio.
        return Envolvente(muestras_acelerando=len(acelerando),
                          muestras_frenando=len(frenando))

    return Envolvente(
        empuje_maximo_g=max(acelerando),
        desaceleracion_maxima_g=abs(min(frenando)),
        muestras_acelerando=len(acelerando),
        muestras_frenando=len(frenando),
        medida=True,
    )


def combinar_envolventes(envolventes: list[Envolvente]) -> Envolvente:
    """Combina las envolventes de varios conductores **del mismo auto**.

    Por que hace falta. La envolvente es una propiedad **del auto** y no del
    conductor, pero se mide a traves de lo que el conductor hizo: quien nunca
    frena a fondo deja sin medir cuanto pueden los frenos. En la primera pasada
    de la prueba de dos conductores, el rapido dio +2,03 y -4,31 g sobre 3.858 y
    453 muestras, y el que le cuesta dio +1,38 y -3,79 g sobre 534 y 148.

    La consecuencia va en la direccion equivocada. Cuanto mas chica la
    envolvente, mas facil es superarla, de modo que **al conductor que menos
    exige el auto se le atribuyen mas impactos externos** solo por no haber
    exigido el auto. Con las dos envolventes de esa pasada, un impulso entre
    1,38 y 2,03 g cambia de clase segun cual se use, y ese margen cubre los
    contactos leves, que son la mayoria.

    Cuando aplicarla. Solo con **rendimiento igualado declarado en los
    metadatos**: ahi los dos autos rinden lo mismo y las medidas se refieren al
    mismo objeto. Sin igualar, los autos son distintos y combinarlos mezclaria
    dos envolventes que no describen la misma cosa.
    """

    medidas = [e for e in envolventes if e.medida]
    if not medidas:
        return Envolvente()
    return Envolvente(
        empuje_maximo_g=max(e.empuje_maximo_g for e in medidas),
        desaceleracion_maxima_g=max(e.desaceleracion_maxima_g for e in medidas),
        muestras_acelerando=sum(e.muestras_acelerando for e in medidas),
        muestras_frenando=sum(e.muestras_frenando for e in medidas),
        medida=True,
    )


def caracterizar(instante_s: float, muestras: list[Muestra],
                 envolvente: Envolvente | None = None,
                 ventana_s: float = VENTANA_S) -> Impacto | None:
    """Caracteriza la colision que el juego declaro en ``instante_s``.

    Devuelve ``None`` si no hay ninguna muestra en la ventana: no se inventa un
    impacto sin canales que lo describan.
    """

    env = envolvente or Envolvente()
    cerca = [m for m in muestras if abs(m.tiempo_s - instante_s) <= ventana_s]
    if not cerca:
        return None

    con_g = [m for m in cerca if m.aceleracion_longitudinal_g is not None]
    pico = None
    if con_g:
        pico = max((m.aceleracion_longitudinal_g for m in con_g), key=abs)

    antes = [m for m in cerca if m.tiempo_s < instante_s and m.velocidad_kmh is not None]
    despues = [m for m in cerca if m.tiempo_s >= instante_s and m.velocidad_kmh is not None]
    v_antes = max((m.velocidad_kmh for m in antes), default=None)
    v_despues = min((m.velocidad_kmh for m in despues), default=None)

    freno = max((m.freno for m in antes if m.freno is not None), default=None)
    acelerador = max((m.acelerador for m in antes if m.acelerador is not None), default=None)

    clasificacion = SIN_IMPULSO_MEDIBLE
    veces = None
    fundamento = ""

    if pico is not None and pico > env.empuje_maximo_g:
        clasificacion = EMPUJADO_DESDE_ATRAS
        veces = pico / env.empuje_maximo_g
        fundamento = (f"impulso de {pico:+.2f} g hacia adelante, "
                      f"{veces:.1f} veces lo que da el motor a fondo "
                      f"({env.empuje_maximo_g:.2f} g)")
    elif pico is not None and pico < -env.desaceleracion_maxima_g:
        clasificacion = FRENADO_POR_ALGO_ADELANTE
        veces = abs(pico) / env.desaceleracion_maxima_g
        fundamento = (f"desaceleracion de {pico:.2f} g, "
                      f"{veces:.1f} veces lo que dan los frenos "
                      f"({env.desaceleracion_maxima_g:.2f} g)")
    else:
        # No es prueba de que no hubo golpe.
        #
        # A 20 Hz hay 50 ms entre muestras y el pico de un impacto dura menos que
        # eso, de modo que puede caer entre dos muestras y no aparecer en ninguna.
        # Es el mismo problema que tiene la aceleracion vertical: un suceso no se
        # comporta como un estado y no se puede dar por ausente porque no se vio.
        perdida = (v_antes - v_despues) if (v_antes is not None and v_despues is not None) else None
        if perdida is not None and perdida > 0:
            fundamento = (f"sin pico por encima de la envolvente; "
                          f"perdio {perdida:.0f} km/h. El pico puede haber caido "
                          f"entre dos muestras: a 20 Hz no se puede distinguir un "
                          f"roce de un golpe corto")
        else:
            fundamento = ("sin pico por encima de la envolvente y sin perdida de "
                          "velocidad: compatible con un roce")

    return Impacto(
        tiempo_s=instante_s,
        clasificacion=clasificacion,
        pico_g=pico,
        veces_la_envolvente=veces,
        velocidad_antes_kmh=v_antes,
        velocidad_despues_kmh=v_despues,
        freno_aplicado=freno,
        acelerador_aplicado=acelerador,
        fundamento=fundamento,
    )
