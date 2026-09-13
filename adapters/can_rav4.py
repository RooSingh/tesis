"""Normalizacion de tramas CAN reales al contrato interno.

Que hace, y por que importa
---------------------------
Convierte las tramas del bus de un Toyota RAV4 en los mismos mensajes canonicos
que producen el simulador y la fuente deportiva. Es lo que hace que el trabajo
sea una arquitectura y no tres programas: **dos protocolos binarios sin nada en
comun —UDP de un simulador y CAN de un vehiculo— entran por el mismo contrato, se
guardan en la misma tabla y se ven en el mismo tablero.**

Lo que se declara con precision
-------------------------------
`source_type` es `can_real_replay`, y hay que leerlo entero:

* **`real`** porque las tramas salieron del bus de un vehiculo que circulaba, y no
  de un generador. Se distingue de `can_simulated`, que es lo que produce el
  generador del propio trabajo;
* **`replay`** porque **no hay un vehiculo en marcha**. Son tramas grabadas que se
  vuelven a emitir. La arquitectura es la misma que aceptaria un bus en vivo, y
  eso es lo que el trabajo demuestra, pero afirmar que hay un vehiculo conectado
  seria falso.

Que se publica
--------------
Solo lo que `docs/research/matriz_evidencia_senales.md` respalda con confianza
alta o media-alta. **Cada mensaje viaja con su confianza y con su limite**, porque
una velocidad de rueda con escala declarada y una posicion de acelerador sin
unidad del fabricante no valen lo mismo, y el consumidor no puede distinguirlas
mirando el numero.

La marcha quedo fuera: se releyo sobre los treinta segmentos y declara estacionado
con el vehiculo en movimiento en veintiocho de ellos.

Tampoco se publican las tramas **transmitidas por el sistema de asistencia**, que
el registrador distingue de las leidas del bus. Verificado: son reenvio byte a
byte de las que ya se publican, y tratarlas como medicion duplicaria cada muestra
ademas de confundir lo que el vehiculo mide con lo que un sistema agregado emite.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from backend import can_decoder

VERSION_ADAPTADOR = "can-rav4-adapter-v3"

#: Numero de bus a partir del cual la trama **no** es una medicion del vehiculo.
#:
#: El registrador marca con valores altos las tramas que **el propio sistema de
#: asistencia transmitio**, y no las que leyo del bus. Verificado sobre la
#: captura: 57.414 tramas aparecen a la vez en el bus 0 y en el 130 —que es
#: 128 mas 2— con **bytes identicos en el 100 % de los casos**, y los dos buses
#: comparten los mismos 82 identificadores. Es un reenvio, no una segunda
#: medicion.
#:
#: Publicarlas tendria dos consecuencias, y la segunda es la grave: duplicaria
#: cada muestra —llevando la frecuencia aparente al doble de la real— y, sobre
#: todo, **presentaria como medicion del vehiculo lo que emitio un sistema
#: agregado**. Esta tesis distingue con cuidado el dato medido del generado; esa
#: distincion se perderia aca.
BUS_TRANSMITIDO_DESDE = 128

#: Origen del dato. `real` por las tramas, `replay` por como se emiten.
SOURCE_TYPE = "can_real_replay"

#: Marca de calidad que acompana a cada mensaje. Dice de un vistazo que el dato
#: es de un vehiculo real y que su emision es una reproduccion.
QUALITY_FLAG = "real_can_replayed"

#: Nombre canonico y unidad de cada senal decodificada. El nombre coincide con el
#: que usan las otras fuentes cuando miden la misma magnitud, que es lo que
#: permite que un mismo analisis corra sobre las tres.
SENALES: dict[str, tuple[str, str]] = {
    "speed": ("speed", "km/h"),
    "wheel_speed_fl": ("wheel_speed_front_left", "km/h"),
    "wheel_speed_fr": ("wheel_speed_front_right", "km/h"),
    "wheel_speed_rl": ("wheel_speed_rear_left", "km/h"),
    "wheel_speed_rr": ("wheel_speed_rear_right", "km/h"),
    # Aceleracion en metros por segundo al cuadrado. El simulador la entrega en
    # unidades de g: **son la misma magnitud en distinta unidad**, y convertir
    # aca cual de las dos es "la correcta" seria una decision de analisis
    # disfrazada de normalizacion. Cada fuente publica lo que mide, con su
    # unidad declarada.
    "accel_x": ("accel_longitudinal", "m/s^2"),
    "accel_y": ("accel_lateral", "m/s^2"),
    "yaw_rate": ("yaw_rate", "deg/s"),
    "steer_angle": ("steer_angle", "deg"),
    "steer_rate": ("steer_rate", "deg/s"),
    "steer_fraction": ("steer_angle_fraction", "deg"),
    "brake_pressed": ("brake_pressed", "bool"),
    "gas_pressed": ("gas_pressed", "bool"),
}


class ErrorNormalizacion(Exception):
    """La trama decodificada no permite construir mensajes canonicos."""


def catalogo_de_senales() -> list[dict[str, str]]:
    """Todas las senales que este adaptador produce, con unidad y confianza.

    Se deriva del decodificador y del mapa, no de una lista aparte: es el mismo
    criterio que el adaptador del simulador adopto despues de que una lista
    escrita a mano dejara canales sin publicar.
    """

    por_senal = {}
    for definicion in can_decoder.MENSAJES.values():
        for campo in definicion["campos"]:
            por_senal[campo.nombre] = definicion
    # El acelerador se deriva invirtiendo el campo declarado como liberado.
    por_senal["gas_pressed"] = can_decoder.MENSAJES[466]

    catalogo = []
    for cruda, (canonica, unidad) in SENALES.items():
        definicion = por_senal.get(cruda)
        if definicion is None:
            continue
        catalogo.append({
            "signal_name": canonica,
            "unit": unidad,
            "mensaje": definicion["nombre"],
            "confianza": definicion["confianza"],
        })
    return sorted(catalogo, key=lambda s: s["signal_name"])


def _marca_temporal(inicio_utc: str, instante_ns: int) -> str:
    """Convierte el instante relativo del segmento en una marca absoluta.

    El registro guarda nanosegundos desde el inicio del segmento, no una fecha:
    saber cuando ocurrio exige el instante de inicio, que es un dato de la
    captura y no de las tramas. Por eso es un parametro obligatorio y no un valor
    por defecto: inventarlo produciria una marca falsa con apariencia de cierta.
    """

    try:
        inicio = datetime.fromisoformat(inicio_utc)
    except ValueError as error:
        raise ErrorNormalizacion(
            f"Inicio de segmento no interpretable: {inicio_utc!r}") from error
    if inicio.tzinfo is None:
        inicio = inicio.replace(tzinfo=timezone.utc)
    return (inicio + timedelta(microseconds=instante_ns / 1000)).isoformat()


def identidad_de_sesion(segmento: str) -> str:
    """Como se llama en la base la sesion que deja un segmento de grabacion.

    POR QUE ES UNA FUNCION Y NO UN TEXTO ADENTRO DEL MENSAJE. El nombre lo
    necesita tambien quien **lanza** la carga, antes de que el guion escriba una
    sola fila: el catalogo de sesiones se pone al dia por identificador, y sin
    saber cual no se pone al dia nada. Eso fue exactamente lo que paso el
    2026-09-13: una carga entro con 57.890 filas y la sesion no figuro en
    ninguna lista.

    La alternativa ---repetir la formula en la ingesta--- deja dos duenos del
    mismo dato, que es el defecto que este tablero ya arrastro cinco veces.
    """

    return f"can:segmento:{segmento}"


def mensajes_desde_trama(
    identificador: int,
    datos: bytes,
    instante_ns: int,
    inicio_utc: str,
    segmento: str,
    bus: int = 0,
    captura_sha256: str | None = None,
) -> list[dict[str, Any]]:
    """Convierte una trama en mensajes canonicos, uno por senal.

    Devuelve una lista vacia si el identificador no esta respaldado. Es el caso
    normal —ciento setenta identificadores contra seis— y tratarlo como error
    obligaria a filtrar antes en cada sitio de uso.
    """

    # Las tramas transmitidas por el sistema de asistencia no son mediciones del
    # vehiculo. Se descartan antes de decodificar: decodificarlas y filtrar
    # despues invitaria a que algun camino las dejara pasar.
    if bus >= BUS_TRANSMITIDO_DESDE:
        return []

    decodificada = can_decoder.decodificar(identificador, datos)
    if decodificada is None:
        return []

    marca = _marca_temporal(inicio_utc, instante_ns)
    vehiculo = f"can:rav4:{segmento}"

    # El contrato exige un conductor y esta fuente no lo tiene: el conjunto es
    # anonimo por diseno, sin identidad del conductor ni del vehiculo concreto.
    #
    # Se declara **la ausencia** en lugar de reutilizar el identificador del
    # segmento, que seria nombrar conductor a lo que es un tramo de grabacion.
    # Un campo obligatorio relleno con algo que no es lo que dice es peor que un
    # campo que declara no saberlo.
    conductor = "can:conductor-no-identificado"

    mensajes: list[dict[str, Any]] = []
    for cruda, valor in decodificada["senales"].items():
        destino = SENALES.get(cruda)
        if destino is None:
            continue
        canonica, unidad = destino
        mensajes.append({
            "timestamp": marca,
            "vehicle_id": vehiculo,
            "driver_id": conductor,
            "session_id": identidad_de_sesion(segmento),
            "lap_id": None,
            "signal_name": canonica,
            "value": bool(valor) if unidad == "bool" else round(float(valor), 6),
            "unit": unidad,
            "source_type": SOURCE_TYPE,
            "quality_flag": QUALITY_FLAG,
            "track_segment_id": None,
            "sector_id": None,
            "curve_id": None,
            "metadata": {
                # El identificador CAN y el bus **son** la trazabilidad de esta
                # fuente, del mismo modo que el identificador de paquete lo es
                # en el protocolo del simulador.
                "can_id": identificador,
                "src": bus,
                "reference_type": "opendbc",
                "reference_id": f"{decodificada['mensaje']}.{cruda}",
                "extra": {
                    "simulated": False,
                    # Lo que separa esta fuente de un vehiculo conectado.
                    "origen_adquisicion": "tramas_grabadas_reproducidas",
                    "version_adaptador": VERSION_ADAPTADOR,
                    "mensaje_can": decodificada["mensaje"],
                    # La confianza viaja con el dato porque no se deduce del
                    # valor: dos numeros del mismo tipo pueden tener respaldos
                    # muy distintos.
                    "confianza": decodificada["confianza"],
                    "limite": decodificada["limite"],
                    "segmento": segmento,
                    "instante_segmento_ns": instante_ns,
                    "campo_origen": cruda,
                    "transformation": (
                        "cast_bool" if unidad == "bool"
                        else "escala y desplazamiento del catalogo opendbc"
                    ),
                    "captura_sha256": captura_sha256,
                },
            },
        })
    return mensajes
