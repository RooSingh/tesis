# -*- coding: utf-8 -*-
"""Declara que puede hacer cada herramienta de analisis con cada sesion.

Que responde
------------
No «que senales tiene la fuente» ---eso lo responde `backend.matriz_fuentes`---
sino **que herramienta puede correr sobre esta sesion, y con que limitacion**.

Son preguntas distintas y la diferencia importa: una fuente que en general publica
el freno puede tener una sesion sin el, y una fuente que lo publica puede
entregarlo como interruptor en lugar de como presion. La segunda no es una
ausencia y tampoco es una disponibilidad completa.

Tres estados y no dos
---------------------
Un declarador binario obliga a mentir en uno de los dos sentidos. Si la
caracterizacion de frenadas exige presion y la fuente entrega un booleano,
declararla disponible haria que informe «presion maxima: 1,0» ---que es estimar en
silencio, justo lo que el trabajo no hace en ninguna otra parte--- y declararla no
disponible descartaria el punto de frenada, la duracion y las velocidades de
entrada y salida, que **si** se pueden medir con un interruptor.

De modo que:

``COMPLETA``
    la sesion entrega todo lo que la herramienta necesita.
``DEGRADADA``
    la herramienta corre, y **nombra que resultado no va a dar**. La limitacion
    viaja con el resultado y no en una nota al pie.
``IMPOSIBLE``
    falta algo sin lo cual el resultado no significaria nada.

Se mide, no se declara
----------------------
La evaluacion consulta **la sesion concreta**. Una tabla escrita de antemano seria
mas barata y afirmaria de cada sesion lo que es cierto de su fuente en promedio,
que es precisamente el error que este modulo existe para no cometer.

La correspondencia entre magnitud y senal
-----------------------------------------
Se reusa la de `backend.matriz_fuentes`, que es la unica parte escrita a mano de
aquel modulo y esta justificada alli. Este modulo la **extiende** con lo que el
analisis necesita y la matriz no cubre: la matriz describe magnitudes fisicas del
vehiculo, y el analisis necesita ademas la estructura de la sesion ---vuelta,
distancia recorrida, validez--- que no es una magnitud fisica sino una division
del recorrido.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend import db
from backend.matriz_fuentes import MAGNITUDES

#: Los tres estados. Son cadenas y no un enumerado porque viajan al tablero y a
#: los registros tal cual, y un enumerado obligaria a traducirlos en cada borde.
COMPLETA = "completa"
DEGRADADA = "degradada"
IMPOSIBLE = "imposible"

#: Ventana del final de la sesion sobre la que se mide. Es la misma que emplea la
#: matriz de fuentes, para que las dos cifras sean comparables.
VENTANA_MEDICION_S = 120

#: Velocidad de referencia para traducir hercios a metros. No es un promedio de
#: nada: es la velocidad a la que un error de ubicacion importa, y sirve para
#: expresar la resolucion en la unidad en que el analisis decide.
VELOCIDAD_DE_REFERENCIA_KMH = 200.0

#: A partir de cuantos valores distintos se considera que una escala es continua.
#: Un interruptor toma dos; un canal de presion en tanto por ciento toma decenas.
#: El corte esta lejos de ambos a proposito, para que ni el ruido de un booleano
#: ni un canal continuo muy quieto caigan del lado equivocado.
VALORES_PARA_ESCALA_CONTINUA = 8


#: Lo que el analisis necesita y la matriz de magnitudes fisicas no cubre.
#:
#: Que la fuente deportiva y el bus del vehiculo tengan **cero filas** de todas
#: estas no es un descuido de la captura: la interfaz publica de la primera no las
#: expone, y el segundo es un vehiculo de calle que no recorre un circuito. La
#: ausencia es del objeto y del acceso, no del registro.
MAGNITUDES_DE_SESION: list[dict[str, Any]] = [
    {
        "magnitud": "Distancia en la vuelta",
        "familia": "estructura",
        "por_fuente": {
            "can_real_replay": None,
            "openf1_historical_replay": None,
            "f1_25_udp_simulation": "lap_distance",
        },
        "ausencias": {
            "can_real_replay": "el vehiculo no recorre un circuito: no hay vuelta "
                               "sobre la cual medir distancia",
            "openf1_historical_replay": "la interfaz publica entrega coordenadas "
                                        "del trazado, no distancia recorrida",
        },
    },
    {
        "magnitud": "Numero de vuelta",
        "familia": "estructura",
        "por_fuente": {
            "can_real_replay": None,
            "openf1_historical_replay": None,
            "f1_25_udp_simulation": "lap_number",
        },
        "ausencias": {
            "can_real_replay": "el vehiculo no da vueltas a nada",
            "openf1_historical_replay": "la interfaz publica no la expone en el "
                                        "flujo de telemetria",
        },
    },
    {
        "magnitud": "Validez de la vuelta",
        "familia": "estructura",
        "por_fuente": {
            "can_real_replay": None,
            "openf1_historical_replay": None,
            "f1_25_udp_simulation": "lap_invalid",
        },
        "ausencias": {
            "can_real_replay": "no hay vuelta que validar",
            "openf1_historical_replay": "la interfaz publica no la expone",
        },
    },
    {
        "magnitud": "Tiempo de vuelta",
        "familia": "estructura",
        "por_fuente": {
            "can_real_replay": None,
            "openf1_historical_replay": None,
            "f1_25_udp_simulation": "current_lap_time",
        },
        "ausencias": {
            "can_real_replay": "no hay vuelta que cronometrar",
            "openf1_historical_replay": "la interfaz publica no la expone en el "
                                        "flujo de telemetria",
        },
    },
    {
        "magnitud": "Estado de boxes",
        "familia": "estructura",
        "por_fuente": {
            "can_real_replay": None,
            "openf1_historical_replay": None,
            "f1_25_udp_simulation": "pit_status",
        },
        "ausencias": {
            "can_real_replay": "no hay boxes",
            "openf1_historical_replay": "la interfaz publica no la expone",
        },
    },
    {
        "magnitud": "Bandera de carrera",
        "familia": "estructura",
        "por_fuente": {
            "can_real_replay": None,
            "openf1_historical_replay": None,
            "f1_25_udp_simulation": "fia_flag",
        },
        "ausencias": {
            "can_real_replay": "no hay direccion de carrera",
            "openf1_historical_replay": "la interfaz publica no la expone en el "
                                        "flujo de telemetria",
        },
    },
    {
        "magnitud": "Deslizamiento de rueda",
        "familia": "traccion",
        "por_fuente": {
            "can_real_replay": None,
            "openf1_historical_replay": None,
            "f1_25_udp_simulation": "wheel_slip_ratio_rear_left",
        },
        "ausencias": {
            "can_real_replay": "el bus no publica deslizamiento, aunque publica "
                               "las cuatro velocidades de rueda de las que se "
                               "derivaria",
            "openf1_historical_replay": "la interfaz publica no la expone",
        },
    },
]

_POR_MAGNITUD: dict[str, dict[str, Any]] = {
    m["magnitud"]: m for m in list(MAGNITUDES) + MAGNITUDES_DE_SESION
}


@dataclass(frozen=True)
class Requisito:
    """Una magnitud que una herramienta necesita, y para que la necesita.

    `para` no es documentacion: es **el texto de la limitacion** que se le informa
    a quien lea el resultado cuando la magnitud falta o llega degradada. Una
    limitacion que dice «falta el freno» no le sirve a nadie; una que dice «no se
    puede informar la presion maxima de cada frenada» si.
    """

    magnitud: str
    para: str
    #: Sin ella el resultado no significa nada, y la herramienta no corre.
    esencial: bool = True
    #: Exige una escala continua. Un interruptor cumple la presencia y no esto.
    continua: bool = False
    #: Resolucion espacial maxima admitida, en metros a la velocidad de
    #: referencia. Cero significa que la herramienta no depende de la resolucion.
    resolucion_maxima_m: float = 0.0
    #: Por que ese numero y no otro. Va en el codigo porque un umbral sin
    #: fundamento es una cifra inventada, y este trabajo no las admite.
    motivo_resolucion: str = ""


@dataclass(frozen=True)
class Herramienta:
    """Una de las herramientas del analisis, con lo que necesita para correr."""

    clave: str
    nombre: str
    proposito: str
    requisitos: tuple[Requisito, ...]


@dataclass
class Medicion:
    """Lo que la sesion entrega de una magnitud, medido y no supuesto."""

    magnitud: str
    senal: str | None
    presente: bool
    hz: float | None = None
    continua: bool | None = None
    muestras: int = 0
    resolucion_m: float | None = None
    ausencia: str | None = None


@dataclass
class Disponibilidad:
    """El veredicto de una herramienta sobre una sesion."""

    herramienta: str
    nombre: str
    fuente: str
    session_id: str
    estado: str
    #: Sobre que vehiculo y que corrida se midio. Una medicion que no lo nombra
    #: no es verificable, y promediar la sesion entera falsea la frecuencia: la
    #: sesion puede tener varios vehiculos y varias reinyecciones superpuestas.
    medido_sobre: str | None = None
    #: La misma terna, sin formatear: (conductor, vehiculo, corrida). La usa
    #: quien va a leer el dato, para acotar su consulta al mismo recorte sobre el
    #: que se declaro. Leer de un recorte distinto del declarado haria que la
    #: declaracion no describa al resultado.
    contexto: tuple[str | None, str | None, str | None] | None = None
    #: Lo que la herramienta no va a poder informar, dicho en terminos del
    #: resultado y no de la senal que falta.
    limitaciones: list[str] = field(default_factory=list)
    #: Por que es imposible, cuando lo es.
    impedimentos: list[str] = field(default_factory=list)
    mediciones: list[Medicion] = field(default_factory=list)

    def como_dict(self) -> dict[str, Any]:
        return {
            "herramienta": self.herramienta,
            "nombre": self.nombre,
            "fuente": self.fuente,
            "session_id": self.session_id,
            "estado": self.estado,
            "medido_sobre": self.medido_sobre,
            "limitaciones": list(self.limitaciones),
            "impedimentos": list(self.impedimentos),
            "mediciones": [vars(m) for m in self.mediciones],
        }


#: Las siete herramientas que el plan de analisis define.
#:
#: El orden es el de construccion y no el de importancia: el filtrado de vueltas
#: limpias va primero porque **todo lo demas es invalido si se comparan vueltas no
#: comparables**, y construirlo al final seria levantar conclusiones sobre dato
#: sin filtrar para tener que revisarlas despues.
HERRAMIENTAS: tuple[Herramienta, ...] = (
    Herramienta(
        clave="vueltas_limpias",
        nombre="Filtrado de vueltas limpias",
        proposito="Decide que vueltas son comparables entre si. Precede a "
                  "cualquier conclusion.",
        requisitos=(
            Requisito("Numero de vuelta",
                      "separar una vuelta de la siguiente"),
            Requisito("Validez de la vuelta",
                      "descartar las vueltas que la sesion invalido"),
            Requisito("Estado de boxes",
                      "descartar la vuelta de entrada y la de salida de boxes",
                      esencial=False),
            Requisito("Bandera de carrera",
                      "descartar las vueltas corridas bajo bandera",
                      esencial=False),
        ),
    ),
    Herramienta(
        clave="delta_acumulado",
        nombre="Traza de delta acumulado",
        proposito="Alinea dos vueltas por posicion en el trazado y muestra donde "
                  "se gano o se perdio tiempo, metro a metro.",
        requisitos=(
            Requisito("Distancia en la vuelta",
                      "alinear las dos vueltas por posicion y no por tiempo, que "
                      "es lo que hace que el resultado localice"),
            Requisito("Numero de vuelta",
                      "separar las vueltas que se comparan"),
            # No es esencial, y decir que lo era habria sido inexacto: el tiempo
            # transcurrido sale de las marcas de tiempo, no de integrar la
            # velocidad. Lo que la velocidad aporta es **una verificacion
            # independiente** de la traza, que es distinto de ser su insumo.
            Requisito("Velocidad del vehiculo",
                      "contrastar el tiempo transcurrido contra la integral de "
                      "la velocidad, que es una comprobacion de la traza que no "
                      "usa las marcas de tiempo",
                      esencial=False),
        ),
    ),
    Herramienta(
        clave="curvas_y_fases",
        nombre="Deteccion de curvas y fases",
        proposito="Separa entrada, apice y salida de cada curva como tramos "
                  "distintos, con su velocidad y su duracion.",
        requisitos=(
            Requisito("Aceleracion lateral",
                      "encontrar los apices, que es donde el giro es maximo"),
            Requisito("Distancia en la vuelta",
                      "ubicar cada curva en el trazado y reconocerla entre vueltas"),
            Requisito("Velocidad del vehiculo",
                      "medir la velocidad de paso de cada fase"),
            Requisito("Direccion",
                      "distinguir la entrada por el giro del volante y no solo "
                      "por la aceleracion resultante",
                      esencial=False),
            # El punto de frenada es un enriquecimiento y no una definicion: la
            # curva se detecta por aceleracion lateral, que es lo que la hace
            # funcionar en fuentes sin freno util. Pero **el enriquecimiento
            # tambien se declara**, porque si no su ausencia no se nombra en
            # ninguna parte y el resultado sale sin el sin que nada lo explique.
            Requisito("Freno",
                      "ubicar el punto de frenada que precede a cada curva",
                      esencial=False),
        ),
    ),
    Herramienta(
        clave="zonas_de_frenada",
        nombre="Caracterizacion de zonas de frenada",
        proposito="Por cada frenada: donde empieza, cuanto dura, con que "
                  "velocidad se entra y con cual se sale.",
        requisitos=(
            Requisito("Freno",
                      "encontrar el comienzo y el fin de cada frenada"),
            Requisito("Velocidad del vehiculo",
                      "medir la velocidad de entrada y la minima alcanzada",
                      resolucion_maxima_m=5.0,
                      motivo_resolucion="un punto de frenada diez metros mas "
                                        "tarde es una decima de segundo, de modo "
                                        "que una resolucion del orden de esos "
                                        "diez metros no distingue lo que la "
                                        "herramienta existe para distinguir"),
            Requisito("Freno",
                      "informar la presion maxima y la modulacion de la frenada",
                      esencial=False, continua=True),
            Requisito("Distancia en la vuelta",
                      "ubicar la frenada en el trazado en lugar de en el tiempo",
                      esencial=False),
        ),
    ),
    Herramienta(
        clave="potencia_y_traccion",
        nombre="Aplicacion de potencia y traccion",
        proposito="Donde se abre el acelerador tras el apice, con que progresion, "
                  "y cuanto desliza el eje motriz al hacerlo.",
        requisitos=(
            Requisito("Acelerador",
                      "encontrar donde se vuelve a aplicar potencia"),
            Requisito("Velocidad del vehiculo",
                      "relacionar la apertura con la velocidad de salida"),
            Requisito("Acelerador",
                      "informar la progresion de apertura, que es la diferencia "
                      "entre pisar y poder pisar",
                      esencial=False, continua=True),
            Requisito("Deslizamiento de rueda",
                      "informar cuanto desliza el eje motriz al aplicar potencia",
                      esencial=False),
        ),
    ),
    Herramienta(
        clave="consistencia",
        nombre="Consistencia entre vueltas",
        proposito="La variacion entre vueltas del mismo conductor. Un conductor "
                  "rapido e inconsistente y otro constante pero mas lento son "
                  "problemas distintos.",
        requisitos=(
            Requisito("Numero de vuelta",
                      "separar las vueltas que se comparan"),
            Requisito("Tiempo de vuelta",
                      "medir la variacion, que es sobre los tiempos"),
            Requisito("Validez de la vuelta",
                      "excluir las vueltas invalidas antes de medir la variacion, "
                      "sin lo cual la dispersion mide incidentes y no consistencia",
                      esencial=False),
        ),
    ),
    Herramienta(
        clave="degradacion_por_tanda",
        nombre="Degradacion a lo largo de una tanda",
        proposito="Como evolucionan los tiempos con el desgaste del neumatico y "
                  "la carga de combustible.",
        requisitos=(
            Requisito("Dano y desgaste",
                      "relacionar la evolucion del tiempo con el estado del "
                      "neumatico"),
            Requisito("Numero de vuelta",
                      "ordenar la tanda"),
            Requisito("Tiempo de vuelta",
                      "medir la evolucion, que es sobre los tiempos"),
        ),
    ),
)

_POR_CLAVE: dict[str, Herramienta] = {h.clave: h for h in HERRAMIENTAS}


def herramientas() -> tuple[Herramienta, ...]:
    """Las siete, en orden de construccion."""

    return HERRAMIENTAS


def _senal_de(magnitud: str, fuente: str) -> tuple[str | None, str | None]:
    """Devuelve la senal que esa fuente usa para la magnitud, y si no, el motivo.

    Que la magnitud no exista en el catalogo es un error de programacion y no una
    ausencia de la fuente: se distingue, porque confundirlos haria que un nombre
    mal escrito se informara como una limitacion del dato.
    """

    entrada = _POR_MAGNITUD.get(magnitud)
    if entrada is None:
        raise KeyError(f"magnitud no catalogada: {magnitud!r}")
    senal = entrada["por_fuente"].get(fuente)
    if senal:
        return senal, None
    return None, (entrada.get("ausencias") or {}).get(
        fuente, "la fuente no publica esta magnitud")


def _contexto(cursor, fuente: str,
              session_id: str) -> tuple[str | None, str | None, str | None]:
    """Elige **un vehiculo y una corrida** de la sesion sobre los cuales medir.

    Sin esta eleccion la frecuencia sale multiplicada por la cantidad de
    vehiculos de la sesion, y el error no se nota porque el numero resultante es
    plausible. Medido: la fuente deportiva, que publica a 3,7 Hz, declaraba
    **84,9 Hz** al contar juntas las muestras de sus veintitres pilotos.

    La consecuencia no era cosmetica. Con 84,9 Hz la resolucion espacial daba
    0,7 metros y la caracterizacion de frenadas se declaraba completa; la real es
    de quince metros y corresponde declararla degradada. El declarador que existe
    para que nada se estime en silencio estaba afirmando una resolucion
    veintitres veces mejor que la que el dato tiene.

    El vehiculo no alcanza: una misma sesion puede tener **varias reinyecciones
    de los mismos datos**, y sus filas comparten las marcas de tiempo originales.
    Una ventana de dos minutos las cuenta todas. Medido sobre la sesion 9947 de la
    fuente deportiva, que conserva cuatro corridas: **7,4 Hz** contra los 3,7 que
    la fuente publica, exactamente el doble por las dos corridas completas que
    coinciden.

    Es el mismo descuido que el del vehiculo, en otra dimension, y el sintoma es
    igual de discreto: el numero resultante sigue siendo plausible. De ahi que la
    eleccion sea de la terna entera ---conductor, vehiculo y corrida--- y no de
    una parte.

    Se toma la terna con mas filas, y **se informa cual fue**: una medicion sobre
    un recorte que no se nombra no es verificable.
    """

    cursor.execute(
        """select driver_id, vehicle_id, replay_run_id, count(*) as n
           from telemetry_messages
           where source_type = %s and session_id = %s
           group by 1, 2, 3 order by n desc limit 1""",
        (fuente, session_id),
    )
    fila = cursor.fetchone()
    if fila is None:
        return None, None, None
    return fila[0], fila[1], fila[2]


def _medir(cursor, fuente: str, session_id: str, senal: str,
           contexto: tuple[str | None, str | None, str | None]) -> Medicion | None:
    """Mide una senal sobre una ventana del final, para un vehiculo y una corrida."""

    conductor, vehiculo, corrida = contexto
    cursor.execute(
        """select count(*),
                  extract(epoch from (max(timestamp) - min(timestamp))),
                  count(distinct value_numeric),
                  count(*) filter (where value_boolean is not null)
           from telemetry_messages
           where source_type = %s and session_id = %s and signal_name = %s
             and driver_id is not distinct from %s
             and vehicle_id is not distinct from %s
             and replay_run_id is not distinct from %s
             and timestamp > (
                 select max(timestamp) - make_interval(secs => %s)
                 from telemetry_messages
                 where source_type = %s and session_id = %s
                   and driver_id is not distinct from %s
                   and vehicle_id is not distinct from %s
                   and replay_run_id is not distinct from %s)""",
        (fuente, session_id, senal, conductor, vehiculo, corrida,
         VENTANA_MEDICION_S, fuente, session_id, conductor, vehiculo, corrida),
    )
    fila = cursor.fetchone()
    if fila is None:
        return None
    muestras, ventana, distintos, booleanos = fila
    if not muestras:
        return None

    hz = None
    resolucion = None
    if ventana and float(ventana) > 0:
        hz = round(muestras / float(ventana), 1)
        if hz > 0:
            # Metros entre muestra y muestra a la velocidad de referencia. Es la
            # forma de expresar la resolucion en la unidad en que el analisis
            # decide: los hercios no dicen si una frenada se ubica o no.
            resolucion = round(VELOCIDAD_DE_REFERENCIA_KMH / 3.6 / hz, 1)

    # Un canal que llega como booleano es un interruptor aunque su valor se
    # guarde como numero: se pregunta por las dos representaciones.
    continua = bool(booleanos) is False and (distintos or 0) >= VALORES_PARA_ESCALA_CONTINUA

    return Medicion(magnitud="", senal=senal, presente=True, hz=hz,
                    continua=continua, muestras=muestras,
                    resolucion_m=resolucion)


def evaluar(herramienta: str, fuente: str, session_id: str) -> Disponibilidad:
    """Declara que puede hacer una herramienta con una sesion concreta.

    Mide la sesion. No consulta una tabla escrita de antemano, porque lo que es
    cierto de una fuente en promedio puede ser falso de una de sus sesiones.
    """

    h = _POR_CLAVE.get(herramienta)
    if h is None:
        raise KeyError(f"herramienta desconocida: {herramienta!r}")

    resultado = Disponibilidad(herramienta=h.clave, nombre=h.nombre, fuente=fuente,
                               session_id=session_id, estado=COMPLETA)
    cache: dict[str, Medicion | None] = {}

    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        contexto = _contexto(cursor, fuente, session_id)
        resultado.contexto = contexto
        resultado.medido_sobre = " / ".join(
            p for p in (contexto[1] or contexto[0], contexto[2]) if p)

        for req in h.requisitos:
            senal, ausencia = _senal_de(req.magnitud, fuente)

            if senal is None:
                medicion = Medicion(magnitud=req.magnitud, senal=None,
                                    presente=False, ausencia=ausencia)
            else:
                if senal not in cache:
                    cache[senal] = _medir(cursor, fuente, session_id,
                                         senal, contexto)
                medida = cache[senal]
                if medida is None:
                    medicion = Medicion(
                        magnitud=req.magnitud, senal=senal, presente=False,
                        ausencia="la fuente la publica, pero esta sesion no tiene "
                                 "muestras de ella")
                else:
                    medicion = Medicion(magnitud=req.magnitud, senal=medida.senal,
                                        presente=True, hz=medida.hz,
                                        continua=medida.continua,
                                        muestras=medida.muestras,
                                        resolucion_m=medida.resolucion_m)
            resultado.mediciones.append(medicion)

            # Ausente. Esencial impide; accesorio limita.
            if not medicion.presente:
                if req.esencial:
                    resultado.impedimentos.append(
                        f"{req.para}: {medicion.ausencia}")
                else:
                    resultado.limitaciones.append(
                        f"no se puede {req.para} ({medicion.ausencia})")
                continue

            # Presente pero como interruptor donde se pedia una escala.
            if req.continua and not medicion.continua:
                texto = (f"no se puede {req.para}: la fuente entrega "
                         f"{medicion.senal} como interruptor y no como escala")
                if req.esencial:
                    resultado.impedimentos.append(texto)
                else:
                    resultado.limitaciones.append(texto)
                continue

            # Presente, pero demasiado espaciada para lo que se pretende ubicar.
            if req.resolucion_maxima_m and medicion.resolucion_m is not None \
                    and medicion.resolucion_m > req.resolucion_maxima_m:
                resultado.limitaciones.append(
                    f"{req.para}, con una resolucion de {medicion.resolucion_m:,.1f} m "
                    f"a {VELOCIDAD_DE_REFERENCIA_KMH:,.0f} km/h "
                    f"({medicion.hz:,.1f} Hz), por encima de los "
                    f"{req.resolucion_maxima_m:,.1f} m que la herramienta declara "
                    f"necesarios: {req.motivo_resolucion}")

    if resultado.impedimentos:
        resultado.estado = IMPOSIBLE
    elif resultado.limitaciones:
        resultado.estado = DEGRADADA
    return resultado


def evaluar_todas(fuente: str, session_id: str) -> list[Disponibilidad]:
    """Las siete herramientas contra una sesion, en orden de construccion."""

    return [evaluar(h.clave, fuente, session_id) for h in HERRAMIENTAS]
