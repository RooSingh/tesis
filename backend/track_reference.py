"""Longitudes de circuito declaradas como dato externo, no medido.

POR QUE ESTE MODULO EXISTE APARTE
---------------------------------
La longitud del circuito es la unica referencia independiente contra la cual el
proyecto puede validar la distancia que deriva por integracion de velocidad. No
la mide este sistema ni viene en los datos: es un dato tomado de una publicacion
externa. Mantenerla en un modulo propio, separado de `session_analysis`, hace que
esa distincion quede inscripta en la estructura y no solo en un comentario. Todo
lo que sale de aca esta marcado con su origen para que nunca pueda leerse como si
fuera una medicion del proyecto.

POR QUE NO SALE DE LOS DATOS
----------------------------
Se reviso `session.json` de los paquetes OpenF1 de las tres sesiones importadas
(`9939` Spa-Francorchamps, `9947` Silverstone y `10006` Suzuka) y la tabla
`racing_sessions`. Ambos traen `circuit_key`, `circuit_short_name`, `location` y
`country_name`, pero **ninguno publica la longitud del circuito**: OpenF1 no la
expone en ningun endpoint. Por eso hace falta una tabla de referencia declarada.

CRITERIO DE LA TABLA
--------------------
- Se indexa por `circuit_key`, el identificador estable de OpenF1, y no por el
  nombre, que es texto libre y cambia de grafia entre fuentes.
- Cada entrada lleva su fuente citable y la temporada a la que corresponde. Un
  circuito remodelado cambia de longitud sin cambiar de nombre: Marina Bay pasa de
  4,940 km a 4,927 km entre configuraciones, y la temporada es lo que permite
  saber cual se esta usando.
- Cubre los 24 circuitos del calendario 2025, que son los de los paquetes
  descargados en `datasets/OpenF1/raw/2025/`.
- Si un circuito no figura, este modulo **no estima ni interpola**: declara la
  ausencia, igual que el procesador de sesiones declara los archivos que faltan.
  Una validacion contra una longitud inventada es peor que ninguna validacion.

FUENTE
------
Las cifras se tomaron de las fichas de circuito del sitio oficial de la Formula 1
para la temporada 2025 (`https://www.formula1.com/en/racing/2025/<gran-premio>/circuit`),
que publican el campo "Circuit Length" de cada evento. Se eligio la ficha por
evento y no una tabla historica general porque la ficha corresponde a la
configuracion efectivamente corrida ese anio, que es la que produjo la telemetria
que se esta validando. Cada entrada guarda su URL exacta.
"""

from __future__ import annotations

# Naturaleza del dato, replicada en cada resultado para que viaje con el numero.
REFERENCIA_TIPO = "externa declarada, no medida por este proyecto"

# Temporada a la que corresponden las longitudes de la tabla.
REFERENCIA_TEMPORADA = 2025

_BASE_F1 = "https://www.formula1.com/en/racing/2025"


def _entrada(circuito: str, longitud_m: float, gran_premio: str) -> dict:
    return {
        "circuito": circuito,
        "longitud_m": longitud_m,
        "fuente": f"{_BASE_F1}/{gran_premio}/circuit",
        "temporada": REFERENCIA_TEMPORADA,
    }


# Indexada por `circuit_key` de OpenF1. El nombre replica `circuit_short_name` tal
# como lo entrega OpenF1, para poder resolver tambien por nombre cuando la clave
# no esta disponible.
LONGITUDES_CIRCUITO: dict[int, dict] = {
    2: _entrada("Silverstone", 5891.0, "great-britain"),
    4: _entrada("Hungaroring", 4381.0, "hungary"),
    6: _entrada("Imola", 4909.0, "emiliaromagna"),
    7: _entrada("Spa-Francorchamps", 7004.0, "belgium"),
    9: _entrada("Austin", 5513.0, "united-states"),
    10: _entrada("Melbourne", 5278.0, "australia"),
    14: _entrada("Interlagos", 4309.0, "brazil"),
    15: _entrada("Catalunya", 4657.0, "spain"),
    19: _entrada("Spielberg", 4326.0, "austria"),
    22: _entrada("Monte Carlo", 3337.0, "monaco"),
    23: _entrada("Montreal", 4361.0, "canada"),
    39: _entrada("Monza", 5793.0, "italy"),
    46: _entrada("Suzuka", 5807.0, "japan"),
    49: _entrada("Shanghai", 5451.0, "china"),
    55: _entrada("Zandvoort", 4259.0, "netherlands"),
    61: _entrada("Singapore", 4927.0, "singapore"),
    63: _entrada("Sakhir", 5412.0, "bahrain"),
    65: _entrada("Mexico City", 4304.0, "mexico"),
    70: _entrada("Yas Marina Circuit", 5281.0, "united-arab-emirates"),
    144: _entrada("Baku", 6003.0, "azerbaijan"),
    149: _entrada("Jeddah", 6174.0, "saudi-arabia"),
    150: _entrada("Lusail", 5419.0, "qatar"),
    151: _entrada("Miami", 5412.0, "miami"),
    152: _entrada("Las Vegas", 6201.0, "las-vegas"),
}

# Indice secundario por nombre normalizado, para resolver sesiones cuyo
# `circuit_key` no llego. Es un respaldo, no el camino principal.
_POR_NOMBRE: dict[str, int] = {
    entrada["circuito"].strip().casefold(): clave
    for clave, entrada in LONGITUDES_CIRCUITO.items()
}


def referencia_no_disponible(motivo: str) -> dict:
    """Arma la declaracion de ausencia de referencia.

    Existe como funcion propia para que la forma del resultado sea la misma se
    haya buscado por clave, por nombre o no se haya buscado nada: quien lee el
    analisis encuentra siempre las mismas llaves.
    """

    return {
        "referencia_disponible": False,
        "longitud_referencia_m": None,
        "referencia_motivo": motivo,
    }


def resolver_referencia_circuito(
    circuit_key: int | None = None,
    circuit_short_name: str | None = None,
    longitud_declarada_m: float | None = None,
) -> dict:
    """Devuelve la longitud de referencia de un circuito con su procedencia.

    Nunca estima: si el circuito no figura en la tabla, devuelve la declaracion de
    ausencia y el analisis debe seguir adelante sin validar la distancia.

    `longitud_declarada_m` permite que el operador imponga un valor a mano, por
    ejemplo para un circuito nuevo todavia sin entrada. Ese caso queda marcado
    como `operador` en la procedencia para que no se confunda con la tabla: si
    alguien lo usa mal, el resultado lo dice.
    """

    if longitud_declarada_m is not None:
        if longitud_declarada_m <= 0:
            return referencia_no_disponible(
                "la longitud indicada a mano no es positiva; no se valida la distancia"
            )
        return {
            "referencia_disponible": True,
            "longitud_referencia_m": float(longitud_declarada_m),
            "referencia_circuito": circuit_short_name,
            "referencia_fuente": "indicada a mano al ejecutar el analisis",
            "referencia_origen": "operador",
            "referencia_tipo": REFERENCIA_TIPO,
        }

    entrada = LONGITUDES_CIRCUITO.get(circuit_key) if circuit_key is not None else None
    if entrada is None and circuit_short_name:
        clave = _POR_NOMBRE.get(circuit_short_name.strip().casefold())
        entrada = LONGITUDES_CIRCUITO.get(clave) if clave is not None else None

    if entrada is None:
        identidad = f"circuit_key={circuit_key} circuit_short_name={circuit_short_name!r}"
        return referencia_no_disponible(
            f"no hay longitud de circuito declarada para {identidad}; "
            "la validacion de distancia no esta disponible para esta sesion"
        )

    return {
        "referencia_disponible": True,
        "longitud_referencia_m": entrada["longitud_m"],
        "referencia_circuito": entrada["circuito"],
        "referencia_fuente": entrada["fuente"],
        "referencia_origen": "tabla declarada del proyecto",
        "referencia_temporada": entrada["temporada"],
        "referencia_tipo": REFERENCIA_TIPO,
    }


# ============================================================================
# QUE CIRCUITO DE LA FUENTE DEPORTIVA ES CADA PISTA DEL SIMULADOR
# ============================================================================
#
# POR QUE HACE FALTA UN PUENTE. Las dos fuentes nombran el circuito con el
# identificador de su proveedor y ninguno de los dos significa nada para el
# otro: F1 25 emite `track_id` en el paquete de sesion y OpenF1 publica
# `circuit_key`. Compararlas «en el mismo circuito» exige decir cual es cual, y
# eso no se deduce de los datos: es una correspondencia escrita a mano, igual
# que la de magnitudes en la matriz de fuentes.
#
# COMO SE COMPRUEBA, QUE ES LO QUE HACE QUE VALGA. Un puente escrito a mano se
# revisa leyendolo, y leerlo no encuentra nada: si el nombre esta mal, se lee
# igual de bien en las dos puntas. Pero el juego **declara la longitud de la
# pista** en el mismo paquete de sesion, y este modulo ya guarda la longitud que
# publica la ficha oficial del circuito. Son dos cifras de dos origenes que no
# se hablan: si el puente esta bien, coinciden.
#
# Contrastadas las once pistas con captura al 2026-09-12, diez coinciden dentro
# de catorce metros ---la mayor separacion es Monte Carlo, 3323 declarados
# contra 3337 de ficha--- y **una se apartaba 791**. Esa era la pista 30, que el
# proyecto llamaba «las-vegas»: 5410 m declarados contra 6201 de Las Vegas, y
# contra 5412 de Miami. La tabla del capturador tenia el tramo final corrido.
#
# LO QUE ESTA MEDIDO Y LO QUE NO. Once pistas tienen captura y su contraste esta
# escrito en la entrada. Las demas no la tienen: su nombre viene de la tabla del
# capturador y se declara asi, sin ascenderlo a comprobado. Las tres que el
# desplazamiento arrastra ---29, 31 y 32--- se reubican por la misma razon que
# hizo caer a la 30 y lo dicen: es la lectura mejor sostenida, no una medicion.

#: Cuanto puede separarse la longitud que declara el juego de la ficha externa
#: antes de que se lea como otro circuito.
#:
#: Sale de lo observado y no de una regla: sobre las once pistas con captura la
#: mayor separacion legitima es de catorce metros. Veinticinco deja margen y
#: sigue a cincuenta y seis veces de distancia del error que se encontro. El
#: veredicto es una comodidad; **la cifra de la diferencia viaja siempre**, para
#: que quien lea juzgue por su cuenta.
TOLERANCIA_LONGITUD_M = 25.0


def _pista(clave_openf1: int, nombre_f1_25: str, verificacion: str) -> dict:
    return {
        "clave_openf1": clave_openf1,
        "nombre_f1_25": nombre_f1_25,
        "verificacion": verificacion,
    }


_MEDIDA = "captura propia: el juego declaro {} m y la ficha externa {} m"
_SIN_CAPTURA = "sin captura todavia: el nombre viene de la tabla del capturador"
_REUBICADA = ("sin captura todavia: reubicada por el mismo desplazamiento que "
              "dejo ver la pista 30, que si esta medida")

#: Indexada por `track_id` de F1 25.
CIRCUITO_POR_PISTA_F1_25: dict[int, dict] = {
    0: _pista(10, "melbourne", _SIN_CAPTURA),
    2: _pista(49, "shanghai", _MEDIDA.format(5441, 5451)),
    3: _pista(63, "sakhir", _SIN_CAPTURA),
    4: _pista(15, "catalunya", _MEDIDA.format(4664, 4657)),
    5: _pista(22, "monte-carlo", _MEDIDA.format(3323, 3337)),
    6: _pista(23, "montreal", _SIN_CAPTURA),
    7: _pista(2, "silverstone", _SIN_CAPTURA),
    9: _pista(4, "hungaroring", _SIN_CAPTURA),
    10: _pista(7, "spa", _MEDIDA.format(7007, 7004)),
    11: _pista(39, "monza", _MEDIDA.format(5798, 5793)),
    12: _pista(61, "singapur", _SIN_CAPTURA),
    13: _pista(46, "suzuka", _MEDIDA.format(5809, 5807)),
    14: _pista(70, "abu-dhabi", _SIN_CAPTURA),
    15: _pista(9, "austin", _MEDIDA.format(5514, 5513)),
    16: _pista(14, "interlagos", _SIN_CAPTURA),
    17: _pista(19, "spielberg", _MEDIDA.format(4323, 4326)),
    19: _pista(65, "mexico", _SIN_CAPTURA),
    20: _pista(144, "baku", _MEDIDA.format(5994, 6003)),
    26: _pista(55, "zandvoort", _SIN_CAPTURA),
    27: _pista(6, "imola", _MEDIDA.format(4910, 4909)),
    29: _pista(149, "jeddah", _REUBICADA),
    30: _pista(151, "miami", _MEDIDA.format(5410, 5412)),
    31: _pista(152, "las-vegas", _REUBICADA),
    32: _pista(150, "lusail", _REUBICADA),
}


def circuito_de_la_pista(track_id: int | None) -> dict | None:
    """El circuito de OpenF1 que corresponde a una pista del simulador."""

    if track_id is None:
        return None
    return CIRCUITO_POR_PISTA_F1_25.get(int(track_id))


def contrastar_longitud_declarada(
    track_id: int | None,
    longitud_declarada_m: float | None,
) -> dict:
    """Compara la longitud que declara el juego contra la ficha del circuito.

    Es la comprobacion independiente del puente. Devuelve siempre la diferencia
    en metros cuando se la puede calcular, porque el veredicto resume y la cifra
    informa: un dia la tolerancia va a quedar corta para un circuito remodelado
    y quien lea la diferencia va a poder verlo.

    `concuerda` vale `None` ---y no `False`--- cuando no hay con que comparar.
    No es lo mismo «no coincide» que «no se comprobo», y el tablero tiene que
    poder decir cual de las dos cosas pasa.
    """

    pista = circuito_de_la_pista(track_id)
    if pista is None:
        return {
            "concuerda": False,
            "circuito": None,
            "clave_openf1": None,
            "longitud_referencia_m": None,
            "longitud_declarada_m": longitud_declarada_m,
            "diferencia_m": None,
            "motivo": f"la pista track_id={track_id} no tiene circuito declarado "
                      "en el puente entre el simulador y la fuente deportiva",
        }

    referencia = LONGITUDES_CIRCUITO[pista["clave_openf1"]]
    base = {
        "circuito": referencia["circuito"],
        "clave_openf1": pista["clave_openf1"],
        "nombre_f1_25": pista["nombre_f1_25"],
        "verificacion": pista["verificacion"],
        "longitud_referencia_m": referencia["longitud_m"],
        "longitud_declarada_m": longitud_declarada_m,
        "referencia_fuente": referencia["fuente"],
        "referencia_tipo": REFERENCIA_TIPO,
    }

    if longitud_declarada_m is None:
        return {**base, "concuerda": None, "diferencia_m": None,
                "motivo": "la captura no declaro longitud de pista: se resuelve "
                          "la identidad y no se la comprueba"}

    diferencia = float(longitud_declarada_m) - referencia["longitud_m"]
    concuerda = abs(diferencia) <= TOLERANCIA_LONGITUD_M
    return {
        **base,
        "concuerda": concuerda,
        "diferencia_m": round(diferencia, 1),
        "tolerancia_m": TOLERANCIA_LONGITUD_M,
        "motivo": "" if concuerda else
                  f"el juego declara {longitud_declarada_m:g} m y la ficha de "
                  f"{referencia['circuito']} publica "
                  f"{referencia['longitud_m']:g}: {abs(diferencia):g} m de "
                  "diferencia, muy por encima de lo que separa a las pistas "
                  "que si concuerdan",
    }
