# -*- coding: utf-8 -*-
"""Rutas del modulo de analisis telemetrico.

QUE EXPONE Y POR QUE NO EXPONIA NADA
------------------------------------
`backend/analisis` reune once modulos ---delta, degradacion, consistencia,
frenadas, fases, traccion, curvas, ajuste, vueltas, disponibilidad y la
lectura comun--- y hasta aqui **no tenia una sola ruta**. El analisis es, por
decision de la autora, una pieza principal del trabajo y no un apendice; un
analisis que solo corre desde un interprete de Python no lo es.

DOS REGLAS QUE ESTAS RUTAS RESPETAN
-----------------------------------
1. **La disponibilidad se consulta antes que el resultado.** Cada herramienta
   declara que magnitudes necesita y con que resolucion; `/analisis/herramientas`
   responde que puede correrse sobre cada fuente. Pedir un analisis que la
   fuente no sostiene devuelve el motivo, no un numero inventado.

2. **No se traduce el vocabulario del analisis.** Los modulos devuelven
   estructuras con nombres pensados; aca se serializan tal cual. Renombrar en
   la frontera obligaria a mantener dos vocabularios y a que el informe elija
   uno.
"""

from __future__ import annotations

import dataclasses
import threading
from collections import OrderedDict
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.analisis import (
    consistencia,
    criticidad,
    degradacion,
    delta,
    disponibilidad,
    frenadas,
    traccion,
    vueltas,
)

router = APIRouter()

#: Cuantos sitios del trazado se devuelven con la traza.
#:
#: Tres es lo que entra en una frase que alguien pueda repetir de memoria
#: mirando la pista. Con diez, la lista deja de ser un resumen y vuelve a ser
#: la curva, que ya viaja entera al lado.
ZONAS_QUE_SE_DEVUELVEN = 3

#: La fuente se deduce del identificador, igual que en `api_sesion`.
def _fuente_de(session_id: str) -> str:
    if session_id.startswith("f1_25:"):
        return "f1_25_udp_simulation"
    if session_id.startswith("can:"):
        return "can_real_replay"
    return "openf1_historical_replay"


def _serializar(objeto: Any) -> Any:
    """Convierte las estructuras del analisis a algo que viaje por HTTP.

    Los modulos devuelven `dataclass` anidadas, tuplas y valores simples.
    `dataclasses.asdict` cubre casi todo; el resto se recorre a mano para no
    perder nada por el camino ni fallar por un tipo inesperado.
    """
    if dataclasses.is_dataclass(objeto) and not isinstance(objeto, type):
        return {k: _serializar(v) for k, v in dataclasses.asdict(objeto).items()}
    if isinstance(objeto, dict):
        return {str(k): _serializar(v) for k, v in objeto.items()}
    if isinstance(objeto, (list, tuple, set)):
        return [_serializar(v) for v in objeto]
    if isinstance(objeto, (str, int, float, bool)) or objeto is None:
        return objeto
    return str(objeto)


def _correr(fn, *args) -> Any:
    """Corre una herramienta y convierte su negativa en una respuesta clara.

    Cuando la fuente no sostiene el analisis, los modulos devuelven una
    estructura que lo explica en vez de fallar. Eso se respeta: llega al
    cliente como 422 con el motivo, que es una respuesta y no un error del
    servidor.
    """
    try:
        resultado = fn(*args)
    except vueltas.SinVueltas as negativa:
        # NO ES UN FALLO: ES LA HERRAMIENTA CONTESTANDO QUE NO PUEDE.
        #
        # Las herramientas declaran su negativa de dos maneras ---devolviendo
        # una estructura con el motivo, o levantando esto--- y las dos dicen lo
        # mismo. Atraparla con el `except` general convertia «esta fuente no
        # tiene vueltas» en «algo se rompio», que ademas le pide a quien
        # consulta que reintente algo que nunca va a andar.
        raise HTTPException(
            status_code=422,
            detail={"disponibilidad": _serializar(negativa.disponibilidad)},
        ) from negativa
    except Exception as error:  # pragma: no cover - depende del estado de la base
        raise HTTPException(status_code=500, detail=str(error)) from error

    datos = _serializar(resultado)
    if isinstance(datos, dict) and datos.get("motivo") and not datos.get("tramos"):
        raise HTTPException(status_code=422, detail=datos)
    return datos


@router.get("/analisis/herramientas")
def listar_herramientas(fuente: str | None = None) -> dict[str, Any]:
    """Que analisis existen y que necesita cada uno.

    **Esta tabla es en si misma una conclusion del trabajo.** Decir que
    herramienta habilita cada fuente es lo que separa un modulo de analisis de
    un conjunto de graficos: no es documentacion de la interfaz, es el
    resultado de haber medido las tres fuentes.
    """
    hs = disponibilidad.herramientas()
    salida = []
    for h in hs:
        salida.append({
            "clave": h.clave,
            "nombre": getattr(h, "nombre", h.clave),
            "requisitos": [_serializar(r) for r in getattr(h, "requisitos", ())],
        })
    return {"herramientas": salida, "cantidad": len(salida), "fuente_consultada": fuente}


@router.get("/analisis/{session_id}/vueltas")
def analisis_vueltas(session_id: str) -> Any:
    """Vueltas de la sesion con su validez y su comparabilidad.

    Distingue **valida** de **comparable**: una vuelta puede ser valida y aun
    asi no servir para comparar ---por trafico, por entrada a boxes, por
    neumatico frio---, y esa distincion es lo que evita conclusiones sacadas
    de vueltas que no se parecen entre si.
    """
    return _correr(vueltas.extraer, _fuente_de(session_id), session_id)


@router.get("/analisis/{session_id}/delta")
def analisis_delta(session_id: str, vuelta_a: int, vuelta_b: int,
                   paso_m: float = 10.0,
                   vehiculo_a: str | None = None,
                   vehiculo_b: str | None = None) -> Any:
    """Diferencia de tiempo acumulada entre dos vueltas, metro a metro.

    Sin vehiculos son dos vueltas del coche que elige el contexto ---un piloto
    contra si mismo---. Nombrandolos, la misma vuelta de dos coches distintos,
    que es donde la pregunta «¿donde me saca tiempo?» tiene respuesta.

    LAS ZONAS VIAJAN CON LA TRAZA, y hasta aqui no viajaban. El modulo sabia
    calcular donde cambio de manos el tiempo y **nadie se lo pedia**: la curva
    llegaba entera al tablero y la respuesta en una frase ---«perdes seis
    decimas entre el metro 6.750 y el 6.790»--- se quedaba en el backend. Es la
    misma clase de hueco que dejo trece señales fuera de la persistencia.

    Se calculan aca y no en `comparar` porque cuantas se quieren es una
    decision de quien pregunta, no de la medicion.
    """
    def con_sus_zonas():
        traza = delta.comparar(_fuente_de(session_id), session_id,
                               vuelta_a, vuelta_b, paso_m, None,
                               vehiculo_a, vehiculo_b)
        return {
            **_serializar(traza),
            "zonas": [_serializar(z) for z in
                      delta.zonas_dominantes(traza, ZONAS_QUE_SE_DEVUELVEN)],
        }

    return _correr(con_sus_zonas)


@router.get("/analisis/{session_id}/degradacion")
def analisis_degradacion(session_id: str) -> Any:
    """Degradacion por tanda: cuanto se pierde por vuelta y con que dispersion."""
    return _correr(degradacion.analizar, _fuente_de(session_id), session_id)


@router.get("/analisis/{session_id}/consistencia")
def analisis_consistencia(session_id: str) -> Any:
    """Consistencia entre vueltas, separando la dispersion de la tendencia.

    Separarlas importa: un piloto que baja un decimo por vuelta de forma
    regular es consistente aunque sus tiempos varien, y uno que repite la
    media dando tumbos no lo es.
    """
    return _correr(consistencia.analizar, _fuente_de(session_id), session_id)


@router.get("/analisis/{session_id}/frenadas")
def analisis_frenadas(session_id: str, vuelta: int) -> Any:
    """Zonas de frenada de una vuelta: donde empieza, cuanto dura, que velocidad."""
    return _correr(frenadas.caracterizar, _fuente_de(session_id), session_id, vuelta)


@router.get("/analisis/{session_id}/traccion")
def analisis_traccion(session_id: str, vuelta: int,
                      derivar_deslizamiento: bool = True) -> Any:
    """Aplicacion de potencia a la salida de curva y deslizamiento asociado."""
    return _correr(traccion.analizar, _fuente_de(session_id), session_id,
                   vuelta, derivar_deslizamiento)


#: La vigilancia de una sesion guardada no cambia: deriva de las frecuencias de
#: toda la sesion, que ya estan medidas. Costo 29,77 s en frio el 2026-09-08, y
#: es una de las dos consultas que hacian que el primer grafico tardara
#: veintiseis segundos en aparecer.
#:
#: Con tope y por desuso, igual que los avisos: sin tope, un proceso largo con
#: 258 sesiones en el catalogo terminaria guardandolas todas.
_VIGILANCIA_CACHE: OrderedDict = OrderedDict()
VIGILANCIAS_EN_CACHE = 24
_CANDADO_VIGILANCIA = threading.Lock()


@router.get("/analisis/{session_id}/vigilancia")
def analisis_vigilancia(session_id: str, incluir_ausentes: bool = False) -> Any:
    """Que senales, si se pierden, merecen alarma y cuales solo aviso.

    ES LA UNICA RUTA QUE NO MIRA EL VALOR DEL DATO
    ----------------------------------------------
    Las demas responden que dice la telemetria. Esta responde **que pasa si
    deja de decir algo**, que es una pregunta que un vehiculo no tiene: alli el
    sensor y el tablero estan cableados juntos y un canal que no llega significa
    que el vehiculo se apago. En una plataforma el canal puede desaparecer con
    el vehiculo perfectamente bien, y entonces la ausencia de dato se parece a
    un dato tranquilo.

    DOS EJES, Y EL CLIENTE TIENE QUE PODER DISTINGUIRLOS
    ----------------------------------------------------
    Cada senal viaja con `nivel_seguridad` y `nivel_analisis`, y ademas con el
    peor de los dos ya resuelto en `nivel` **acompanado de `eje`**. Sin el eje,
    un tablero pintaria de rojo la velocidad del vehiculo ---critica porque
    inhabilita tres herramientas--- y se leeria como un peligro que no es.

    Por omision devuelve solo lo que la fuente publica: una magnitud que nunca
    entrega no es una alarma sino una ausencia declarada.
    """
    clave = (session_id, bool(incluir_ausentes))
    with _CANDADO_VIGILANCIA:
        # El candado ademas evita que dos peticiones simultaneas de la misma
        # sesion arranquen dos recorridos de treinta segundos.
        if clave in _VIGILANCIA_CACHE:
            _VIGILANCIA_CACHE.move_to_end(clave)
            return dict(_VIGILANCIA_CACHE[clave], de_cache=True)

    fuente = _fuente_de(session_id)
    try:
        vigilada = criticidad.vigilar(fuente, session_id,
                                      incluir_ausentes=incluir_ausentes)
    except Exception as error:  # pragma: no cover - depende del estado de la base
        raise HTTPException(status_code=500, detail=str(error)) from error

    if not vigilada.vigilancias:
        raise HTTPException(status_code=422, detail={
            "motivo": "la sesion no tiene muestras sobre las que medir "
                      "frecuencias, de modo que no se puede derivar cuanto "
                      "silencio tolera cada canal",
            "fuente": fuente, "session_id": session_id})
    respuesta = vigilada.como_dict()
    with _CANDADO_VIGILANCIA:
        _VIGILANCIA_CACHE[clave] = respuesta
        _VIGILANCIA_CACHE.move_to_end(clave)
        while len(_VIGILANCIA_CACHE) > VIGILANCIAS_EN_CACHE:
            _VIGILANCIA_CACHE.popitem(last=False)
    return dict(respuesta, de_cache=False)
