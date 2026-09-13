# -*- coding: utf-8 -*-
"""Los reglajes que se corrieron en un mismo circuito, puestos uno al lado del otro.

QUE CONTESTA, Y QUE NO. Contesta **con que reglaje se corrio cada vez en este
circuito y que cambio entre uno y otro**. No contesta cual conviene: para eso
haria falta que dos vueltas difirieran en el reglaje y en nada mas, y una sesion
de un videojuego conducida otro dia, con otro combustible y otro trafico, no es
ese experimento. Lo que se publica es la comparacion; la conclusion la saca
quien mira, y con lo que `no_autoriza` declara a la vista.

POR QUE NACIO ASI Y NO COMO UN RECOMENDADOR. Se midio antes de escribirlo, sobre
las catorce sesiones de la base que tienen reglaje (2026-09-13). En los tres
circuitos con mas de una ---Spielberg con tres, Baku y Shanghai con dos--- los
veintitres ejes coinciden: **cero diferencias**. Lo unico que cambia es el
combustible inicial, que no es una eleccion de reglaje sino la carga que el
juego reparte segun el tipo de sesion: 10 kg en contrarreloj, 11 y 14 en
carrera.

De modo que un recomendador habria sido un panel que siempre dice «usaste el
mismo». Lo que si es util, y es cierto, es poder afirmarlo: **si el reglaje no
cambio, ninguna diferencia de tiempo entre esas sesiones es del reglaje**. Eso
descarta una hipotesis entera, que es mas de lo que hace una recomendacion
inventada.

EL COMBUSTIBLE SE SEPARA DEL RESTO. Va en el mismo paquete y no es lo mismo: los
otros veintidos ejes los elige quien arma el auto y este lo impone el modo. Un
panel que lo mezclara diria «cambiaste el reglaje» cuando lo unico que cambio
fue entrar a una carrera en vez de a una contrarreloj.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend import db, procedencia_sesiones
from backend.analisis import sectores


#: La unica fuente que declara reglaje. Ni OpenF1 ni el bus lo publican.
FUENTE = "f1_25_udp_simulation"

#: El prefijo con el que el adaptador nombra las señales de reglaje.
PREFIJO = "setup_"

#: El eje que **no** elige quien arma el auto. Ver la cabecera del modulo.
CARGA_DEL_MODO = "combustible_inicial_kg"

#: Lo que esta comparacion no autoriza a concluir, escrito una vez y publicado
#: con cada respuesta. Son las diferencias que quedan **sin controlar** entre
#: dos sesiones del mismo circuito.
NO_AUTORIZA = (
    "dos sesiones del mismo circuito no son un experimento: cambian el tipo de "
    "sesión, la carga de combustible que el modo impone, la dificultad de la "
    "máquina, el clima, el tráfico y el estado de quien conduce. Una diferencia "
    "de tiempo entre ellas no queda atribuida al reglaje por figurar en esta "
    "tabla"
)

#: Y lo que si autoriza, que es lo contrario y vale igual.
LO_QUE_SI = (
    "cuando ningun eje difiere, la diferencia de tiempo **no es del reglaje**: "
    "esa hipotesis queda descartada sin necesidad de medir nada mas"
)


@dataclass
class ReglajeDeUnaSesion:
    """Con que se corrio una vez en este circuito."""

    session_id: str
    tipo_sesion: str | None
    familia_de_sesion: str | None
    parc_ferme: str | None
    capturado_utc: str | None
    #: Los veintitres ejes, tal como el paquete los declara.
    valores: dict = field(default_factory=dict)
    #: Si se puede afirmar que este reglaje se llevo a la pista.
    asentada: bool = False
    #: La mejor vuelta valida medida con el cronometro del juego, o `None`.
    mejor_vuelta_s: float | None = None
    vueltas_validas: int = 0
    #: Y POR QUE NO HAY TIEMPO, CUANDO NO LO HAY. Una raya sola no distingue
    #: «no hay datos» de «invalidaste las seis vueltas», y la segunda es la
    #: unica cosa util que esa fila tiene para decir.
    sin_tiempo_porque: str | None = None
    #: En que se aparta de la sesion de referencia, eje por eje.
    difiere_en: list = field(default_factory=list)
    #: Cuantos ejes de reglaje difieren, sin contar la carga del modo.
    cuantos_difieren: int = 0

    def como_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "tipo_sesion": self.tipo_sesion,
            "familia_de_sesion": self.familia_de_sesion,
            "parc_ferme": self.parc_ferme,
            "capturado_utc": self.capturado_utc,
            "valores": self.valores,
            "asentada": self.asentada,
            "mejor_vuelta_s": self.mejor_vuelta_s,
            "vueltas_validas": self.vueltas_validas,
            "sin_tiempo_porque": self.sin_tiempo_porque,
            "difiere_en": self.difiere_en,
            "cuantos_difieren": self.cuantos_difieren,
        }


@dataclass
class Comparacion:
    """Los reglajes de un circuito, ordenados alrededor de uno de referencia."""

    session_id: str
    circuito: str | None
    referencia: str | None = None
    sesiones: list = field(default_factory=list)
    #: Por que no hay nada que comparar, cuando no lo hay.
    motivo: str | None = None
    no_autoriza: str = NO_AUTORIZA
    lo_que_si_autoriza: str = LO_QUE_SI
    #: Que se puede afirmar con esta tabla concreta, en una linea.
    lectura: str | None = None

    def como_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "circuito": self.circuito,
            "referencia": self.referencia,
            "sesiones": [s.como_dict() for s in self.sesiones],
            "motivo": self.motivo,
            "no_autoriza": self.no_autoriza,
            "lo_que_si_autoriza": self.lo_que_si_autoriza,
            "lectura": self.lectura,
        }


def sesiones_con_reglaje() -> list[str]:
    """Las sesiones de la base que declaran el paquete de reglaje.

    Se pregunta por el prefijo y no por los veintitres nombres: la lista de
    canales vive en la ruta que arma el panel, y repetirla aca seria tener el
    mismo dato en dos sitios.
    """

    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        cursor.execute(
            """SELECT DISTINCT session_id FROM telemetry_messages
                WHERE source_type = %s AND signal_name LIKE %s""",
            (FUENTE, PREFIJO + "%"))
        return sorted(f[0] for f in cursor.fetchall())


def _porque_no_hay_tiempo(piloto) -> str | None:
    """Por que esta sesion no aporta una vuelta que comparar.

    Son tres cosas distintas y la diferencia importa. Que **todas** se hayan
    invalidado dice algo de como se condujo; que ninguna se haya corrido entera
    dice donde empezo y donde se corto la captura; que no haya vueltas dice que
    no hay nada. Una raya sola las cuenta como la misma.
    """

    if piloto is None or not piloto.vueltas_vistas:
        return "esta sesión no declara vueltas"
    if piloto.vueltas:
        return None
    partes = []
    if piloto.invalidadas:
        partes.append("%d invalidada%s por el juego"
                      % (piloto.invalidadas, "s" if piloto.invalidadas > 1 else ""))
    if piloto.incompletas:
        # La vuelta de salida de una contrarreloj arranca dentro del tercer
        # sector, y la ultima de cualquier captura se corta sin cerrar.
        partes.append("%d sin correrse entera" % piloto.incompletas)
    return ("de %d vuelta%s: %s"
            % (piloto.vueltas_vistas, "s" if piloto.vueltas_vistas > 1 else "",
               " y ".join(partes) if partes else "ninguna cronometrable"))


def _mejor_vuelta(session_id: str, vehiculo: str | None):
    """La mejor vuelta valida y cuantas hubo, con el cronometro del juego.

    NO SE USA `duracion_s` DE `/vueltas`. Aquella es tiempo de conduccion
    continua ---le descuenta los cortes--- y ademas incluye la vuelta de salida.
    Lo que compara un reglaje contra otro es un tiempo de vuelta, y el tiempo de
    vuelta lo declara el propio juego. `sectores` ya lo deriva y **descarta las
    invalidas**, que es justo lo que hay que descartar.
    """

    # ACOTADO AL VEHICULO EN LA CONSULTA. En una carrera son veintidos coches y
    # solo interesa uno: sin acotar, esta comparacion leia veinte veces lo que
    # necesitaba. Medido en Spielberg ---tres sesiones, una de ellas carrera---
    # el panel entero bajo de 16,4 s a lo que la tabla de abajo declare.
    contraste = sectores.extraer(FUENTE, session_id,
                                 (vehiculo,) if vehiculo else None)
    piloto = contraste.piloto(vehiculo) if vehiculo else (
        contraste.pilotos[0] if contraste.pilotos else None)
    if piloto is None:
        return None, 0, "esta sesión no declara vueltas"
    return (piloto.mejor_vuelta_s, len(piloto.vueltas),
            _porque_no_hay_tiempo(piloto))


def _diferencias(referencia: dict, otro: dict) -> list[dict]:
    """En que ejes se apartan dos reglajes, y por cuanto.

    Se recorren los ejes de la referencia: un eje que una de las dos no declare
    no es una diferencia sino una ausencia, y anotarlo como «cambio de X a nada»
    seria inventar un cambio.
    """

    salida = []
    for clave in sorted(referencia):
        if clave not in otro:
            continue
        a, b = referencia[clave], otro[clave]
        if a == b:
            continue
        diferencia = None
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            diferencia = round(b - a, 6)
        salida.append({
            "clave": clave,
            "referencia": a,
            "aplicado": b,
            "diferencia": diferencia,
            # El unico eje que no elige quien arma el auto. Ver la cabecera.
            "lo_impone_el_modo": clave == CARGA_DEL_MODO,
        })
    return salida


def _lectura(sesiones: list[ReglajeDeUnaSesion]) -> str:
    """Que se puede afirmar con esta tabla, en una linea y sin adornos."""

    otras = sesiones[1:]
    if not otras:
        return "no hay otra sesión en este circuito con la que comparar"
    cambian = [s for s in otras if s.cuantos_difieren]
    if not cambian:
        return ("el reglaje es el mismo en las %d sesiones de este circuito: "
                "cualquier diferencia de tiempo entre ellas no es del reglaje"
                % len(sesiones))
    ejes = sorted({d["clave"] for s in cambian for d in s.difiere_en
                   if not d["lo_impone_el_modo"]})
    return ("de las %d sesiones de este circuito, %d corrieron con otro "
            "reglaje; cambia %s"
            % (len(sesiones), len(cambian), ", ".join(ejes)))


def comparar(session_id: str, valores_de, vehiculo_de) -> Comparacion:
    """Los reglajes del circuito de esta sesion, alrededor del de esta sesion.

    `valores_de` y `vehiculo_de` se reciben en vez de importarse porque viven en
    la ruta que ya sabe leer el paquete ---con su lista de canales, su acotado al
    vehiculo propio y su criterio de «asentada»--- y duplicar eso aca seria
    tener dos lecturas del mismo dato que el dia de manana no coinciden.
    """

    propia = procedencia_sesiones.de(session_id) or {}
    circuito = propia.get("circuito")
    comparacion = Comparacion(session_id=session_id, circuito=circuito)
    if not circuito:
        comparacion.motivo = ("esta sesión no declara circuito: sin él no hay "
                              "con qué agrupar los reglajes")
        return comparacion

    candidatas = [s for s in sesiones_con_reglaje()
                  if (procedencia_sesiones.de(s) or {}).get("circuito") == circuito]
    # La propia va primero y es la referencia: el panel compara **contra lo que
    # se esta mirando**, no contra una sesion elegida por antiguedad.
    candidatas = ([session_id] if session_id in candidatas else []) + \
                 [s for s in candidatas if s != session_id]
    if not candidatas:
        comparacion.motivo = ("ninguna sesión de %s declara el paquete de "
                              "reglaje" % circuito)
        return comparacion

    for sesion in candidatas:
        proc = procedencia_sesiones.de(sesion) or {}
        vehiculo = vehiculo_de(sesion)
        valores, asentada = valores_de(sesion, vehiculo)
        mejor, cuantas, porque = _mejor_vuelta(sesion, vehiculo)
        comparacion.sesiones.append(ReglajeDeUnaSesion(
            session_id=sesion,
            tipo_sesion=proc.get("tipo_sesion_nombre"),
            familia_de_sesion=proc.get("familia_de_sesion"),
            parc_ferme=proc.get("parc_ferme"),
            capturado_utc=proc.get("capturado_utc"),
            valores=valores,
            asentada=asentada,
            mejor_vuelta_s=mejor,
            vueltas_validas=cuantas,
            sin_tiempo_porque=porque,
        ))

    referencia = comparacion.sesiones[0]
    comparacion.referencia = referencia.session_id
    for otra in comparacion.sesiones[1:]:
        otra.difiere_en = _diferencias(referencia.valores, otra.valores)
        otra.cuantos_difieren = sum(
            1 for d in otra.difiere_en if not d["lo_impone_el_modo"])
    comparacion.lectura = _lectura(comparacion.sesiones)
    return comparacion
