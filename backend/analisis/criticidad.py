# -*- coding: utf-8 -*-
"""Que significa perder una senal, y cuando eso merece una alarma.

La pregunta que no es la de la industria
----------------------------------------
Los tableros de competicion alarman sobre **valores anomalos**: presion de aceite
por debajo de tal umbral, temperatura de agua por encima de tal otra. Este modulo
responde una pregunta distinta: **que pasa cuando la senal deja de llegar**.

Nadie la trata asi en un vehiculo, y con razon: alli el sensor y el tablero estan
cableados juntos, de modo que un canal que no llega significa que el vehiculo se
apago. En una plataforma de telemetria no: el canal puede desaparecer con el
vehiculo perfectamente bien, porque se corto el enlace, fallo el sensor o el
consumidor dejo de persistir.

Y ahi aparece un problema que el vehiculo no tiene: **la ausencia de dato se parece
a un dato tranquilo**. Una presion de aceite que deja de llegar se ve, en un panel
que no lo distinga, igual que una presion de aceite estable.

El criterio que ordena la clasificacion
---------------------------------------
No es cuan importante es la magnitud, sino **cuanto aviso se pierde con ella**:

    Una senal perdida es critica cuando era el unico aviso que el conductor no
    puede darse a si mismo.

Lo contrario tambien ordena: el conductor **si** siente el agarre, la traccion y la
frenada, de modo que perder los canales que los describen cuesta analisis y no
seguridad.

Que sostiene la bibliografia, y que no
--------------------------------------
La bibliografia verificada sostiene **la premisa** de este modulo, y no el reparto
fila por fila. Dos registradores comerciales de competicion declaran alarmas, y las
dos veces son alarmas **de valor**: RaceCapture ofrece «alarmas y advertencias
configurables» sobre umbrales de presion de aceite, temperatura de motor y tension
de bateria; RT Live enumera «alarmas, por ejemplo presion de aceite baja». Ninguno
de los dos declara una alarma para un canal que **deja de llegar**, que es
justamente la pregunta que este modulo responde.

El reparto de cada magnitud entre los tres niveles, en cambio, **es criterio propio
de este trabajo**, y asi queda declarado: el campo de cita de cada fila esta vacio
a proposito. Se intento fundarlo con literatura sobre percepcion del conductor ---la
degradacion de frenos, la perdida lenta de presion de neumatico--- y las fuentes,
abiertas y leidas, no dicen lo que el resumen de busqueda les atribuia. Ponerles una
cita habria sido peor que no tener ninguna.

El segundo eje esta medido, no opinado
--------------------------------------
A la consecuencia de seguridad se le suma **cuanto analisis inhabilita la perdida**,
que el escenario de fallos parciales de sensado midio: perder los datos de vuelta
deja sin insumo a cinco de las siete herramientas; perder el acelerometro, a una.

De modo que el color sale de cruzar dos ejes, y **uno de los dos es una medicion de
este trabajo**.

Cuando una senal esta perdida
-----------------------------
No se elige un umbral. Cada canal tiene su propia frecuencia, ya medida por el
declarador de disponibilidad, y **el silencio se juzga contra el periodo del propio
canal**: un canal de veinte hercios que no llega en medio segundo perdio diez
muestras; uno de 3,7 hercios, en ese mismo medio segundo, no perdio ninguna.

Un instante suelto no alcanza, porque un datagrama se pierde sin que nada este mal
y el transporte no lo retransmite. De modo que lo que se juzga es una **duracion de
silencio**; y a diferencia de un umbral de valor, esa duracion **se deriva del dato
en lugar de elegirse**.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.analisis.disponibilidad import (
    _POR_MAGNITUD,
    _senal_de,
    herramientas,
)

#: Los tres niveles. Cadenas y no un enumerado, por el mismo motivo que los
#: estados de disponibilidad: viajan al tablero tal cual.
CRITICA = "critica"
ATENCION = "atencion"
INFORMATIVA = "informativa"

#: Cuantos periodos del propio canal tienen que pasar en silencio para darlo por
#: perdido.
#:
#: Tres muestras perdidas, mas **uno de margen por el ruido del sistema
#: operativo**. Los tres primeros son criterio: un datagrama suelto se pierde sin
#: que nada este mal ---el transporte no retransmite--- y alarmar por eso
#: convertiria la alarma en ruido.
#:
#: El cuarto no es criterio sino medicion. Este trabajo midio el piso de ruido de
#: la maquina: **un `sleep` de 50 ms llego a tardar 90,27**, un desvio de
#: +40,27 ms, es decir cerca de un periodo entero a veinte hercios. Sin ese margen
#: la alarma se disparia por planificacion del sistema y no por perdida de senal.
PERIODOS_PARA_DARLO_POR_PERDIDO = 4

#: Piso absoluto del umbral, en segundos.
#:
#: Para un canal muy rapido, cuatro periodos pueden quedar por debajo del desvio
#: que la maquina misma introduce: a cien hercios son cuarenta milisegundos, y el
#: desvio medido llego a cuarenta. Se toma el mayor de los dos.
PISO_DE_SILENCIO_S = 0.040


@dataclass(frozen=True)
class Criterio:
    """Que se pierde al perder una magnitud, y con que fundamento."""

    magnitud: str
    #: Lo que su perdida pone en riesgo. Sale de la bibliografia, no del codigo.
    nivel_seguridad: str
    #: Que aviso deja de existir. Se enuncia en terminos de lo que puede pasar,
    #: no del nombre del canal.
    aviso_perdido: str
    #: Por que el conductor no puede suplirlo, o por que si puede.
    percepcion_del_conductor: str
    #: Clave bibliografica que sostiene la asignacion de nivel.
    #:
    #: **Hoy esta vacia en todas las filas, y no por olvido.** La bibliografia
    #: verificada sostiene la premisa del modulo ---que la industria alarma sobre
    #: valores y no sobre ausencias--- pero no reparte magnitud por magnitud. El
    #: campo existe para poder llenarlo si aparece una fuente que lo haga; vacio
    #: declara que el reparto es criterio propio.
    cita: str = ""


#: El catalogo. Cada entrada dice que aviso se pierde y por que el conductor no
#: puede reemplazarlo, con su fuente.
#:
#: **Solo estan las magnitudes que el contrato interno define.** Presion de aceite y
#: temperatura de frenos, que la bibliografia nombra como los canales de alarma por
#: excelencia, **no figuran**: ninguna de las tres fuentes las publica, de modo que
#: catalogarlas seria prometer una vigilancia que el sistema no puede prestar.
#:
#: Que una fuente concreta no tenga una magnitud que el contrato si define lo
#: resuelve la disponibilidad, no este catalogo.
CRITERIOS: tuple[Criterio, ...] = (
    Criterio(
        magnitud="Dano y desgaste",
        nivel_seguridad=ATENCION,
        aviso_perdido="la evolucion del desgaste a lo largo de una tanda",
        percepcion_del_conductor="el conductor percibe la perdida de agarre, de "
                                 "modo que la telemetria confirma lo que el ya "
                                 "nota en lugar de avisarlo primero",
    ),
    Criterio(
        magnitud="Freno",
        nivel_seguridad=ATENCION,
        aviso_perdido="donde y cuanto se frena",
        percepcion_del_conductor="el conductor tiene el pedal bajo el pie: es la "
                                 "señal que menos necesita que le informen",
    ),
    Criterio(
        magnitud="Velocidad del vehiculo",
        nivel_seguridad=ATENCION,
        aviso_perdido="el ritmo y toda comparacion que dependa de el",
        percepcion_del_conductor="la ve en su propio tablero",
    ),
    Criterio(
        magnitud="Acelerador",
        nivel_seguridad=INFORMATIVA,
        aviso_perdido="la aplicacion de potencia a la salida de curva",
        percepcion_del_conductor="es una entrada suya, no una medicion sobre el "
                                 "vehiculo",
    ),
    Criterio(
        magnitud="Direccion",
        nivel_seguridad=INFORMATIVA,
        aviso_perdido="la entrada de volante y la deteccion de curvas",
        percepcion_del_conductor="es una entrada suya",
    ),
    Criterio(
        magnitud="Aceleracion lateral",
        nivel_seguridad=INFORMATIVA,
        aviso_perdido="la deteccion de curvas y sus fases",
        percepcion_del_conductor="el conductor siente la aceleracion lateral "
                                 "mejor que ningun sensor",
    ),
    Criterio(
        magnitud="Aceleracion longitudinal",
        nivel_seguridad=INFORMATIVA,
        aviso_perdido="el analisis de frenada y traccion por dinamica",
        percepcion_del_conductor="la siente",
    ),
    Criterio(
        magnitud="Velocidad de guinada",
        nivel_seguridad=INFORMATIVA,
        aviso_perdido="la caracterizacion del comportamiento en curva",
        percepcion_del_conductor="la siente",
    ),
    Criterio(
        magnitud="Velocidad por rueda",
        nivel_seguridad=ATENCION,
        aviso_perdido="el deslizamiento derivado y el bloqueo de una rueda",
        percepcion_del_conductor="un bloqueo se siente, pero una diferencia "
                                 "sostenida entre ruedas no",
    ),
    Criterio(
        magnitud="Deslizamiento de rueda",
        nivel_seguridad=ATENCION,
        aviso_perdido="cuanto desliza el eje motriz al aplicar potencia",
        percepcion_del_conductor="el deslizamiento grande se siente; el pequeño "
                                 "y sostenido, que es el que cuesta tiempo, no",
    ),
    Criterio(
        magnitud="Regimen del motor",
        nivel_seguridad=ATENCION,
        aviso_perdido="el regimen, y con el cualquier condicion que lo use como "
                      "calificador",
        percepcion_del_conductor="lo ve y lo oye, pero muchas alarmas de valor lo "
                                 "usan como condicion y sin el no pueden evaluarse",
    ),
    Criterio(
        magnitud="Marcha",
        nivel_seguridad=INFORMATIVA,
        aviso_perdido="la marcha seleccionada",
        percepcion_del_conductor="es una entrada suya",
    ),
    Criterio(
        magnitud="Energia y unidad de potencia",
        nivel_seguridad=INFORMATIVA,
        aviso_perdido="el estado de la energia desplegada y recuperada",
        percepcion_del_conductor="lo administra desde el volante",
    ),
    Criterio(
        magnitud="Posicion en el trazado",
        nivel_seguridad=INFORMATIVA,
        aviso_perdido="la ubicacion espacial de lo que se mide",
        percepcion_del_conductor="sabe donde esta",
    ),
    Criterio(
        magnitud="Aleron movil",
        nivel_seguridad=INFORMATIVA,
        aviso_perdido="el estado del aleron movil",
        percepcion_del_conductor="lo acciona el",
    ),
    # --- estructura de la sesion -------------------------------------------
    # Ninguna de estas mide nada del vehiculo, y sin embargo su perdida es la mas
    # cara del conjunto. Es el resultado que el escenario de fallos parciales de
    # sensado dejo, y no se habria adivinado.
    Criterio(
        magnitud="Numero de vuelta",
        nivel_seguridad=CRITICA,
        aviso_perdido="toda comparacion entre vueltas: sin numero de vuelta no "
                      "hay sujeto que comparar",
        percepcion_del_conductor="no es una magnitud del vehiculo, de modo que el "
                                 "conductor no puede suplirla ni notar su ausencia",
    ),
    Criterio(
        magnitud="Distancia en la vuelta",
        nivel_seguridad=CRITICA,
        aviso_perdido="la ubicacion de todo lo medido sobre el trazado, y con "
                      "ella la traza de delta y la deteccion de curvas",
        percepcion_del_conductor="no puede suplirla",
    ),
    Criterio(
        magnitud="Tiempo de vuelta",
        nivel_seguridad=ATENCION,
        aviso_perdido="el ritmo y la consistencia",
        percepcion_del_conductor="lo ve en su tablero",
    ),
    Criterio(
        magnitud="Validez de la vuelta",
        nivel_seguridad=ATENCION,
        aviso_perdido="el control de calidad que precede a cualquier "
                      "comparacion: sin el se comparan vueltas no comparables",
        percepcion_del_conductor="no puede suplirla",
    ),
    Criterio(
        magnitud="Estado de boxes",
        nivel_seguridad=INFORMATIVA,
        aviso_perdido="descartar la vuelta de entrada y salida de boxes",
        percepcion_del_conductor="el equipo sabe cuando entro a boxes por otras "
                                 "vias",
    ),
    Criterio(
        magnitud="Bandera de carrera",
        nivel_seguridad=ATENCION,
        aviso_perdido="saber que una vuelta corrio bajo bandera",
        percepcion_del_conductor="el conductor ve las banderas, pero quien "
                                 "analiza despues no",
    ),
)

_POR_NOMBRE: dict[str, Criterio] = {c.magnitud: c for c in CRITERIOS}

#: Orden de severidad, para poder ordenar y comparar.
_ORDEN = {CRITICA: 0, ATENCION: 1, INFORMATIVA: 2}


@dataclass
class Vigilancia:
    """Que se vigila de una magnitud sobre una fuente concreta."""

    magnitud: str
    #: Lo que su perdida pone en riesgo, segun la bibliografia.
    nivel_seguridad: str
    #: Cuanto analisis deja sin insumo, segun lo medido por el escenario de
    #: fallos parciales de sensado. **Es un eje distinto y no se fusiona con el
    #: anterior**: una magnitud que el conductor percibe perfectamente puede
    #: sostener media herramienta de analisis, y colapsar las dos en un solo
    #: color haria que un tablero mostrara en rojo algo que no es un peligro.
    nivel_analisis: str
    senal: str | None
    #: Hercios medidos sobre la sesion. `None` si la magnitud no esta.
    hz: float | None
    #: Cuanto silencio la da por perdida, derivado de su propia frecuencia.
    silencio_para_alarmar_s: float | None
    aviso_perdido: str
    percepcion_del_conductor: str
    cita: str
    #: Cuantas de las siete herramientas quedan sin insumo si se pierde.
    herramientas_que_inhabilita: int = 0
    #: Por que la fuente no la tiene, cuando no la tiene.
    ausencia: str | None = None

    def como_dict(self) -> dict[str, Any]:
        return dict(vars(self))


def _herramientas_que_dependen(magnitud: str) -> int:
    """Cuantas herramientas quedan **imposibles** sin esa magnitud.

    Se cuentan solo las que la declaran esencial. Las que la usan como
    enriquecimiento siguen corriendo degradadas, y contarlas igual inflaria la
    severidad de magnitudes que solo recortan un resultado.
    """

    total = 0
    for h in herramientas():
        if any(r.magnitud == magnitud and r.esencial for r in h.requisitos):
            total += 1
    return total


def _nivel_por_analisis(inhabilita: int) -> str:
    """Cuanto analisis se pierde, en la misma escala pero en su propio eje.

    Los cortes salen de la medicion y no de una preferencia: perder los datos de
    vuelta dejo sin insumo a cinco de las siete herramientas, la telemetria a
    tres, y el movimiento a una. Tres o mas es perder la mitad del analisis.
    """

    if inhabilita >= 3:
        return CRITICA
    if inhabilita >= 1:
        return ATENCION
    return INFORMATIVA


def peor(vigilancia: "Vigilancia") -> tuple[str, str]:
    """El nivel mas alto de los dos, **y por que eje**.

    Devolver solo el nivel seria volver a fusionarlos. Quien muestre esto tiene
    que poder decir «critica para el analisis» y no dejar que se lea como un
    peligro.
    """

    if _ORDEN[vigilancia.nivel_seguridad] <= _ORDEN[vigilancia.nivel_analisis]:
        return vigilancia.nivel_seguridad, "seguridad"
    return vigilancia.nivel_analisis, "analisis"


def vigilancias(fuente: str, mediciones: dict[str, float | None] | None = None,
                ) -> list[Vigilancia]:
    """Que vigilar en esa fuente, ordenado por severidad.

    `mediciones` asocia cada nombre de senal con su frecuencia medida. Si se
    omite, las vigilancias salen sin frecuencia y sin umbral de silencio: se
    puede decir **que** vigilar sin haber medido, pero no **cuanto silencio**
    tolera cada canal.
    """

    mediciones = mediciones or {}
    salida: list[Vigilancia] = []
    for criterio in CRITERIOS:
        if criterio.magnitud not in _POR_MAGNITUD:
            continue
        senal, ausencia = _senal_de(criterio.magnitud, fuente)
        inhabilita = _herramientas_que_dependen(criterio.magnitud)
        hz = mediciones.get(senal) if senal else None
        salida.append(Vigilancia(
            magnitud=criterio.magnitud,
            nivel_seguridad=criterio.nivel_seguridad,
            nivel_analisis=_nivel_por_analisis(inhabilita),
            senal=senal,
            hz=hz,
            silencio_para_alarmar_s=(
                round(max(PERIODOS_PARA_DARLO_POR_PERDIDO / hz,
                          PISO_DE_SILENCIO_S), 3)
                if hz else None),
            aviso_perdido=criterio.aviso_perdido,
            percepcion_del_conductor=criterio.percepcion_del_conductor,
            cita=criterio.cita,
            herramientas_que_inhabilita=inhabilita,
            ausencia=ausencia if senal is None else None,
        ))
    salida.sort(key=lambda v: (_ORDEN[peor(v)[0]],
                               -v.herramientas_que_inhabilita, v.magnitud))
    return salida


def vigilancias_presentes(fuente: str,
                          mediciones: dict[str, float | None] | None = None,
                          ) -> list[Vigilancia]:
    """Solo lo que esa fuente publica.

    Una magnitud que la fuente **nunca** entrega no es una alarma: es una
    ausencia declarada, y confundirlas haria que el bus de un vehiculo de calle
    encendiera una alarma critica en cada arranque por no tener datos de vuelta.
    """

    return [v for v in vigilancias(fuente, mediciones) if v.senal is not None]


@dataclass
class Vigilada:
    """Que vigilar en una sesion concreta, ya medida."""

    fuente: str
    session_id: str
    vigilancias: list[Vigilancia] = field(default_factory=list)
    #: Sobre que conductor, vehiculo y corrida se midieron las frecuencias.
    #: **Viaja con el resultado**, porque un umbral de silencio derivado de una
    #: frecuencia medida sobre un recorte que no se nombra no es verificable.
    medido_sobre: str = ""
    #: Cuantas hay en cada nivel, ya cruzados los dos ejes.
    conteo: dict[str, int] = field(default_factory=dict)

    def como_dict(self) -> dict[str, Any]:
        return {
            "fuente": self.fuente,
            "session_id": self.session_id,
            "medido_sobre": self.medido_sobre,
            "conteo": self.conteo,
            "vigilancias": [
                dict(v.como_dict(), nivel=peor(v)[0], eje=peor(v)[1])
                for v in self.vigilancias
            ],
        }


def vigilar(fuente: str, session_id: str, incluir_ausentes: bool = False,
            ) -> Vigilada:
    """Mide la sesion y clasifica que merece alarma y que merece aviso.

    Es la entrada que usa el tablero. Mide **una vez** y clasifica sobre esa
    medicion, en lugar de pedir la frecuencia canal por canal.

    Por omision devuelve solo lo que la fuente publica. Una magnitud que la
    fuente nunca entrega no es una alarma sino una ausencia declarada, y
    mezclarlas haria que el bus de un vehiculo de calle encendiera una alarma
    critica en cada arranque por no tener datos de vuelta.
    """

    from backend.analisis import disponibilidad as disp

    medidas = disp.frecuencias(fuente, session_id,
                               tuple(c.magnitud for c in CRITERIOS))
    vistas = (vigilancias(fuente, medidas.por_senal) if incluir_ausentes
              else vigilancias_presentes(fuente, medidas.por_senal))

    conteo: dict[str, int] = {n: 0 for n in (CRITICA, ATENCION, INFORMATIVA)}
    for v in vistas:
        conteo[peor(v)[0]] += 1

    return Vigilada(fuente=fuente, session_id=session_id, vigilancias=vistas,
                    medido_sobre=medidas.medido_sobre, conteo=conteo)


def resumen(fuente: str, vistas: list[Vigilancia]) -> str:
    """Una linea por nivel, con cuantas magnitudes hay en cada uno."""

    conteo: dict[str, int] = {}
    for v in vistas:
        nivel, _ = peor(v)
        conteo[nivel] = conteo.get(nivel, 0) + 1
    partes = [f"{conteo.get(n, 0)} {n}" for n in (CRITICA, ATENCION, INFORMATIVA)]
    return f"{fuente}: " + ", ".join(partes)
