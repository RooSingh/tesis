"""Decodificador de las tramas CAN respaldadas del Toyota RAV4.

Que decodifica, y por que solo eso
----------------------------------
El bus del vehiculo publica cerca de ciento setenta identificadores distintos.
Este modulo decodifica **siete**, que son los que
`docs/research/matriz_evidencia_senales.md` respalda con evidencia: referencia en
el catalogo de definiciones, muestra observada sobre treinta rutas y veinticinco
dispositivos, y comportamiento coherente.

Decodificar el resto seria facil y no estaria justificado. Una definicion de la
comunidad no es lo mismo que una medicion verificada, y publicar un canal sin
respaldo lo volveria indistinguible de los que si lo tienen.

Como se leen los campos
-----------------------
El catalogo declara cada campo con la forma `inicio|largo@orden signo`, donde el
inicio es la posicion del **bit mas significativo** contada desde el byte cero.
El orden `@0` es big-endian, que es lo que usa este vehiculo en todos los
mensajes que aca se leen.

Esa convencion es la parte delicada. Contar el bit desde el extremo equivocado
produce numeros que siguen entrando en el rango declarado, de modo que **el
resultado parece valido y no lo es**. Es el mismo tipo de error que este trabajo
ya encontro tres veces en el protocolo del simulador, y por eso las pruebas se
escriben contra tramas de valor conocido y no contra esta misma funcion.

Lo que se declara y no se afirma
-------------------------------
Cada senal viaja con su **nivel de confianza** y con su **limite**, tomados de la
matriz de evidencia. Una posicion de acelerador sin unidad del fabricante no es
lo mismo que una velocidad de rueda con escala declarada, y el contrato tiene que
poder distinguirlas.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Confianza declarada en la matriz de evidencia. Se transporta con cada senal
#: porque el consumidor no puede inferirla del valor.
ALTA = "alta"
MEDIA_ALTA = "media-alta"


@dataclass(frozen=True)
class Campo:
    """Un campo del catalogo de definiciones.

    `bit_inicio` es la posicion del bit mas significativo en la convencion
    big-endian del catalogo, tal como aparece en la definicion.
    """

    nombre: str
    bit_inicio: int
    largo: int
    escala: float
    desplazamiento: float
    unidad: str
    con_signo: bool = False


def _leer_big_endian(datos: bytes, campo: Campo) -> int:
    """Lee el campo segun la convencion del catalogo, sin escalar."""

    total_bits = len(datos) * 8
    # Se arma el entero de la trama completa y se recorta la ventana del campo.
    # El bit de inicio del catalogo es el mas significativo, y el recorrido
    # continua hacia el bit menos significativo del mismo byte y luego al
    # siguiente byte, que es el orden natural del entero grande.
    completo = int.from_bytes(datos, "big")
    inicio_msb = (campo.bit_inicio // 8) * 8 + (7 - campo.bit_inicio % 8)
    desde = total_bits - inicio_msb - campo.largo
    if desde < 0:
        raise ValueError(
            f"{campo.nombre}: el campo excede los {len(datos)} bytes de la trama"
        )
    crudo = (completo >> desde) & ((1 << campo.largo) - 1)
    if campo.con_signo and crudo >= (1 << (campo.largo - 1)):
        crudo -= 1 << campo.largo
    return crudo


def valor_de(datos: bytes, campo: Campo) -> float:
    """Devuelve el campo ya escalado a su unidad fisica."""

    crudo = _leer_big_endian(datos, campo)
    return crudo * campo.escala + campo.desplazamiento


# --------------------------------------------------------------------------- #
# Los siete mensajes respaldados
# --------------------------------------------------------------------------- #
#
# Cada uno cita el identificador y la definicion del catalogo tal como figura en
# `opendbc`, para que la correspondencia pueda revisarse sin abrir este archivo.

MENSAJES: dict[int, dict[str, Any]] = {
    36: {
        "nombre": "KINEMATICS",
        "confianza": ALTA,
        "limite": "la dinamica proviene del vehiculo; el catalogo declara la escala, no el fabricante",
        "campos": [
            Campo("yaw_rate", 1, 10, 0.244, -125.0, "deg/s"),
            Campo("accel_x", 17, 10, 0.03589, -18.375, "m/s^2"),
            Campo("accel_y", 33, 10, 0.03589, -18.375, "m/s^2"),
        ],
    },
    37: {
        "nombre": "STEER_ANGLE_SENSOR",
        "confianza": MEDIA_ALTA,
        "limite": "falta orientar el signo izquierda/derecha y confirmar la escala del fabricante",
        "campos": [
            Campo("steer_angle", 3, 12, 1.5, 0.0, "deg", con_signo=True),
            Campo("steer_fraction", 39, 4, 0.1, 0.0, "deg", con_signo=True),
            Campo("steer_rate", 35, 12, 1.0, 0.0, "deg/s", con_signo=True),
        ],
    },
    170: {
        "nombre": "WHEEL_SPEEDS",
        "confianza": ALTA,
        "limite": "no se verifico rueda por rueda en multiples segmentos",
        "campos": [
            Campo("wheel_speed_fr", 6, 15, 0.01, -67.67, "km/h"),
            Campo("wheel_speed_fl", 22, 15, 0.01, -67.67, "km/h"),
            Campo("wheel_speed_rr", 38, 15, 0.01, -67.67, "km/h"),
            Campo("wheel_speed_rl", 54, 15, 0.01, -67.67, "km/h"),
        ],
    },
    180: {
        "nombre": "SPEED",
        "confianza": ALTA,
        "limite": "velocidad del vehiculo segun el catalogo, sin contraste contra referencia externa",
        "campos": [Campo("speed", 47, 16, 0.01, 0.0, "km/h")],
    },
    466: {
        "nombre": "PCM_CRUISE",
        "confianza": MEDIA_ALTA,
        "limite": "el campo se declara liberado y se invierte; el catalogo es alternativo al principal",
        "campos": [Campo("gas_released", 4, 1, 1.0, 0.0, "bool")],
    },
    550: {
        "nombre": "BRAKE_MODULE",
        "confianza": ALTA,
        "limite": "el booleano es solido; presion y posicion no tienen unidad del fabricante",
        "campos": [Campo("brake_pressed", 37, 1, 1.0, 0.0, "bool")],
    },
}

# --------------------------------------------------------------------------- #
# Lo que NO se decodifica, y por que
# --------------------------------------------------------------------------- #
#
# **La marcha (identificador 956, campo `GEAR` en 13|6).** La matriz de evidencia
# la calificaba media-alta sobre 3.534 tramas del Dia 16, con los estados D, N, R
# y P coherentes con la velocidad.
#
# Al leerla sobre los treinta segmentos aparecio otra cosa: **en 28 de 30 el campo
# vale cero mientras el vehiculo circula**, y cero corresponde a estacionado. No
# es un error de lectura —en los dos segmentos donde el campo esta poblado da 0,
# 16 y 32, que son P, N y D, y cambian cuando el vehiculo arranca— sino que el
# campo **no esta poblado en la mayoria de los vehiculos**. El conjunto tiene 25
# dispositivos distintos, o sea variantes distintas del mismo modelo, y la propia
# matriz anotaba que otro identificador complementa en el subconjunto hibrido.
#
# La medicion original era correcta y no era representativa: conto tramas, no en
# cuantos vehiculos el campo significa algo. Publicar un canal que declara
# estacionado en el 93 % de los segmentos seria peor que no tenerlo.
#
# Queda **abierta**: es una candidata valiosa que necesita identificar cual es el
# campo poblado en cada variante antes de poder publicarse.
MARCHA_NO_PUBLICADA = {
    "identificador": 956,
    "campo": "GEAR 13|6@0+",
    "motivo": "vale cero con el vehiculo en movimiento en 28 de 30 segmentos",
    "segmentos_con_valor": 2,
    "segmentos_totales": 30,
    "estado": "abierta",
}

#: Identificadores que este modulo decodifica. Se expone para que quien consuma
#: pueda filtrar antes de decodificar, en lugar de decodificar y descartar.
IDENTIFICADORES_RESPALDADOS = frozenset(MENSAJES)

def decodificar(identificador: int, datos: bytes) -> dict[str, Any] | None:
    """Convierte una trama en sus senales, o devuelve None si no esta respaldada.

    Devolver `None` y no lanzar una excepcion es deliberado: que un identificador
    no este respaldado es el caso normal —son ciento setenta contra siete— y
    tratarlo como error obligaria a filtrar antes en cada sitio de uso.
    """

    definicion = MENSAJES.get(identificador)
    if definicion is None:
        return None

    senales: dict[str, Any] = {}
    for campo in definicion["campos"]:
        senales[campo.nombre] = valor_de(datos, campo)

    # El acelerador se publica como presionado y el catalogo lo declara liberado.
    # La inversion se hace aca y se declara, en lugar de dejar que cada consumidor
    # recuerde invertirlo.
    if "gas_released" in senales:
        senales["gas_pressed"] = float(not bool(senales.pop("gas_released")))

    return {
        "mensaje": definicion["nombre"],
        "identificador": identificador,
        "confianza": definicion["confianza"],
        "limite": definicion["limite"],
        "senales": senales,
    }
