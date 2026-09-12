# -*- coding: utf-8 -*-
"""Traza de delta acumulado entre dos vueltas.

Que hace, y por que es la herramienta central
---------------------------------------------
Alinea dos vueltas **por posicion en el trazado y no por tiempo**, y muestra el
tiempo ganado o perdido acumulado metro a metro.

Su valor esta en que localiza. Un cronometro dice «perdiste un segundo»; la traza
dice «perdiste 0,7 s entre el metro 2.400 y el 2.500 y los otros 2.100 metros
fueron equivalentes». Lo primero no indica donde trabajar; lo segundo si.

Como se calcula
---------------
Para cada vuelta se arma el tiempo transcurrido en funcion de la distancia,
``t(d)``, a partir de las muestras de distancia y sus marcas de tiempo. El delta
en un punto es la diferencia entre los dos tiempos transcurridos a esa misma
distancia.

Entre muestra y muestra hay que interpolar, y **eso se declara**: no se presenta
como medicion. La interpolacion es lineal, y la separacion entre muestras es de
unos tres metros a doscientos kilometros por hora con una fuente de veinte
hercios.

La verificacion que la traza trae puesta
----------------------------------------
La propiedad que la valida es interna: **el delta al final de la vuelta tiene que
ser igual a la diferencia entre los dos tiempos de vuelta**. Son dos caminos
independientes hacia la misma cifra ---uno acumula diferencias por distancia, el
otro lee el cronometro de la sesion--- y su discrepancia es el residuo, que viaja
con el resultado.

Un residuo grande no se corrige repartiendolo: se informa. Corregirlo seria hacer
que la traza cierre por construccion y perder justamente la unica comprobacion que
tiene.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend import db
from backend.analisis.disponibilidad import IMPOSIBLE, Disponibilidad, evaluar
from backend.analisis.vueltas import SinVueltas

SENAL_NUMERO = "lap_number"
SENAL_DISTANCIA = "lap_distance"
SENAL_VELOCIDAD = "speed"

#: Paso de la rejilla comun sobre la que se evaluan las dos vueltas. Diez metros
#: es del orden de lo que separa un punto de frenada bueno de uno malo ---la
#: referencia del oficio es que diez metros son una decima--- de modo que una
#: rejilla mas fina no agregaria informacion que el muestreo tenga.
PASO_REJILLA_M = 10.0


class SinTraza(Exception):
    """No se puede trazar el delta, y se dice por que."""

    def __init__(self, motivo: str,
                 disponibilidad: Disponibilidad | None = None) -> None:
        self.disponibilidad = disponibilidad
        super().__init__(motivo)


@dataclass
class Tramo:
    """Un tramo del trazado y cuanto tiempo cambio de manos en el."""

    desde_m: float
    hasta_m: float
    #: Positivo: la primera vuelta perdio tiempo contra la segunda.
    delta_s: float


@dataclass
class Traza:
    """El delta acumulado entre dos vueltas, con lo que lo respalda."""

    session_id: str
    fuente: str
    vuelta_a: int
    vuelta_b: int
    paso_m: float
    #: De que vehiculo es cada lado, cuando los lados son dos pilotos distintos.
    #: `None` en la comparacion de siempre, que es un piloto contra si mismo.
    #: Una medicion que no nombra sobre que se hizo no es verificable, y sin
    #: esto dos trazas de dos pares de pilotos se ven iguales.
    vehiculo_a: str | None = None
    vehiculo_b: str | None = None
    #: Pares (distancia, delta acumulado) sobre la rejilla comun.
    puntos: list[tuple[float, float]] = field(default_factory=list)
    disponibilidad: Disponibilidad | None = None
    #: Hasta donde llegan las dos vueltas a la vez.
    largo_comun_m: float = 0.0
    #: Delta al final de la traza.
    delta_final_s: float | None = None
    #: Diferencia entre los cronometros de la sesion, que es el mismo numero por
    #: otro camino.
    diferencia_cronometros_s: float | None = None
    #: Lo que los dos caminos discrepan. Se informa; no se reparte.
    residuo_s: float | None = None

    def como_dict(self) -> dict:
        return {
            "session_id": self.session_id, "fuente": self.fuente,
            "vuelta_a": self.vuelta_a, "vuelta_b": self.vuelta_b,
            "vehiculo_a": self.vehiculo_a, "vehiculo_b": self.vehiculo_b,
            "paso_m": self.paso_m, "largo_comun_m": self.largo_comun_m,
            "delta_final_s": self.delta_final_s,
            "diferencia_cronometros_s": self.diferencia_cronometros_s,
            "residuo_s": self.residuo_s,
            "puntos": [[d, s] for d, s in self.puntos],
            "disponibilidad": (self.disponibilidad.como_dict()
                               if self.disponibilidad else None),
        }


def _leer(cursor, fuente: str, session_id: str,
          contexto: tuple[str | None, str | None, str | None],
          vehiculo_pedido: str | None = None) -> list[tuple]:
    """Las tres señales de un coche en una corrida.

    EL CONDUCTOR DEJA DE FILTRAR CUANDO EL LADO NOMBRA SU VEHICULO, y no es un
    detalle. La terna del contexto trae el conductor **del coche con mas filas**,
    y un `driver_id is not distinct from` con ese valor puesto mientras se pide
    otro `vehicle_id` no devuelve ninguna fila: la traza saldria vacia con los
    dos coches presentes en la base, y nada en el resultado diria por que. Un
    `vehicle_id` ya identifica al coche dentro de la sesion.
    """

    conductor, vehiculo, corrida = contexto
    if vehiculo_pedido is not None:
        vehiculo = vehiculo_pedido
        conductor = None
    condiciones = ["source_type = %s", "session_id = %s"]
    valores: list[object] = [fuente, session_id]
    if vehiculo_pedido is None:
        condiciones.append("driver_id is not distinct from %s")
        valores.append(conductor)
    condiciones += ["vehicle_id is not distinct from %s",
                    "replay_run_id is not distinct from %s",
                    "signal_name in (%s, %s, %s)", "value_numeric is not null"]
    valores += [vehiculo, corrida, SENAL_NUMERO, SENAL_DISTANCIA, SENAL_VELOCIDAD]
    cursor.execute(
        "select timestamp, signal_name, value_numeric from telemetry_messages"
        " where " + " and ".join(condiciones) + " order by timestamp",
        tuple(valores),
    )
    return cursor.fetchall()


def _por_vuelta(filas: list[tuple]) -> dict[int, list[tuple[float, float, float | None]]]:
    """Agrupa en (segundos desde el inicio de la vuelta, distancia, velocidad).

    El tiempo se cuenta **desde la primera muestra de cada vuelta** y no desde el
    origen de la sesion: lo que la traza compara son duraciones, y arrastrar el
    origen comun solo agregaria una constante distinta a cada vuelta.
    """

    if not filas:
        return {}

    por_vuelta: dict[int, list[tuple[float, float, float | None]]] = {}
    numero: int | None = None
    inicio: dict[int, object] = {}
    ultima_velocidad: float | None = None

    for marca, nombre, valor in filas:
        if nombre == SENAL_NUMERO:
            numero = int(valor)
            continue
        if nombre == SENAL_VELOCIDAD:
            ultima_velocidad = float(valor)
            continue
        if numero is None:
            continue
        if numero not in inicio:
            inicio[numero] = marca
            por_vuelta[numero] = []
        segundos = (marca - inicio[numero]).total_seconds()
        por_vuelta[numero].append((segundos, float(valor), ultima_velocidad))
    return por_vuelta


def _tiempo_en(muestras: list[tuple[float, float, float | None]],
               distancia: float) -> float | None:
    """Tiempo transcurrido al pasar por esa distancia, interpolando linealmente.

    Devuelve `None` fuera del tramo cubierto por las muestras en lugar de
    extrapolar: mas alla del ultimo punto medido no hay dato, y estirarlo seria
    inventar el tramo que la traza deberia estar describiendo.
    """

    if not muestras or distancia < muestras[0][1] or distancia > muestras[-1][1]:
        return None

    izquierda, derecha = 0, len(muestras) - 1
    while izquierda < derecha - 1:
        medio = (izquierda + derecha) // 2
        if muestras[medio][1] <= distancia:
            izquierda = medio
        else:
            derecha = medio

    t0, d0, _ = muestras[izquierda]
    t1, d1, _ = muestras[derecha]
    if d1 == d0:
        return t0
    return t0 + (t1 - t0) * (distancia - d0) / (d1 - d0)


def _monotonas(muestras: list[tuple[float, float, float | None]]
               ) -> list[tuple[float, float, float | None]]:
    """Deja la distancia creciente, descartando retrocesos.

    Un retroceso de la distancia dentro de una vuelta no es un error de medicion:
    ocurre al cruzar la linea y al reponer el vehiculo en pista. Interpolar sobre
    una secuencia no monotona daria tiempos que van y vienen.
    """

    limpio: list[tuple[float, float, float | None]] = []
    for muestra in muestras:
        if not limpio or muestra[1] > limpio[-1][1]:
            limpio.append(muestra)
    return limpio


def comparar(fuente: str, session_id: str, vuelta_a: int, vuelta_b: int,
             paso_m: float = PASO_REJILLA_M,
             cronometros: dict[int, float] | None = None,
             vehiculo_a: str | None = None,
             vehiculo_b: str | None = None) -> Traza:
    """Traza el delta acumulado de la vuelta A contra la B.

    Un delta positivo significa que **el lado A iba perdiendo** contra el B en
    ese punto del trazado.

    DOS PILOTOS SON LA MISMA TRAZA CON UN VEHICULO POR LADO. Sin `vehiculo_a` ni
    `vehiculo_b` se comparan dos vueltas del coche que elige el contexto, que es
    lo que esta herramienta hacia: un piloto contra si mismo. Nombrando los dos
    vehiculos se compara la misma vuelta de dos coches, que es donde la pregunta
    «¿donde me saca tiempo?» tiene respuesta.
    """

    disponible = evaluar("delta_acumulado", fuente, session_id)
    if disponible.estado == IMPOSIBLE:
        raise SinVueltas(disponible)

    contexto = disponible.contexto or (None, None, None)
    dos_pilotos = vehiculo_a is not None or vehiculo_b is not None
    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        if dos_pilotos:
            lado_a = _por_vuelta(_leer(cursor, fuente, session_id, contexto,
                                       vehiculo_a))
            lado_b = _por_vuelta(_leer(cursor, fuente, session_id, contexto,
                                       vehiculo_b))
        else:
            # Una sola lectura: dos viajes a la base traerian lo mismo dos veces.
            lado_a = lado_b = _por_vuelta(
                _leer(cursor, fuente, session_id, contexto))

    # El motivo nombra al coche cuando hay dos: «la vuelta 3 no tiene muestras»
    # no dice de cual de los dos, y el que no la tiene es uno solo.
    for numero, lado, quien in ((vuelta_a, lado_a, vehiculo_a),
                                (vuelta_b, lado_b, vehiculo_b)):
        if numero not in lado or len(lado[numero]) < 2:
            de_quien = f" de {quien}" if quien else ""
            raise SinTraza(
                f"la vuelta {numero}{de_quien} no tiene muestras de distancia "
                "suficientes", disponible)

    a = _monotonas(lado_a[vuelta_a])
    b = _monotonas(lado_b[vuelta_b])

    traza = Traza(session_id=session_id, fuente=fuente, vuelta_a=vuelta_a,
                  vuelta_b=vuelta_b, vehiculo_a=vehiculo_a,
                  vehiculo_b=vehiculo_b, paso_m=paso_m,
                  disponibilidad=disponible)

    # Hasta donde las dos vueltas tienen dato. Mas alla, una de las dos no fue
    # medida y el delta no existiria: no se completa.
    desde = max(a[0][1], b[0][1])
    hasta = min(a[-1][1], b[-1][1])
    if hasta <= desde:
        raise SinTraza("las dos vueltas no comparten tramo medido", disponible)
    traza.largo_comun_m = round(hasta - desde, 1)

    distancia = desde
    while distancia <= hasta:
        ta = _tiempo_en(a, distancia)
        tb = _tiempo_en(b, distancia)
        if ta is not None and tb is not None:
            traza.puntos.append((round(distancia, 1), round(ta - tb, 4)))
        distancia += paso_m

    if traza.puntos:
        traza.delta_final_s = traza.puntos[-1][1]

    # La comprobacion interna: el delta al final tiene que coincidir con la
    # diferencia de los cronometros, que es el mismo numero por otro camino.
    if cronometros and vuelta_a in cronometros and vuelta_b in cronometros:
        traza.diferencia_cronometros_s = round(
            cronometros[vuelta_a] - cronometros[vuelta_b], 3)
        if traza.delta_final_s is not None:
            traza.residuo_s = round(
                traza.delta_final_s - traza.diferencia_cronometros_s, 3)
    return traza


def tramos_dominantes(traza: Traza, cuantos: int = 3) -> list[Tramo]:
    """Los tramos donde mas tiempo cambio de manos.

    Es lo que hace util a la herramienta: no el total, que ya lo daba el
    cronometro, sino **donde** se produjo. Se ordenan por magnitud del cambio y no
    por signo, porque un tramo donde se gano medio segundo informa tanto como uno
    donde se perdio.
    """

    if len(traza.puntos) < 2:
        return []
    tramos = [
        Tramo(desde_m=traza.puntos[i][0], hasta_m=traza.puntos[i + 1][0],
              delta_s=round(traza.puntos[i + 1][1] - traza.puntos[i][1], 4))
        for i in range(len(traza.puntos) - 1)
    ]
    tramos.sort(key=lambda t: abs(t.delta_s), reverse=True)
    return tramos[:cuantos]


def resumen(traza: Traza) -> str:
    """Una linea con el total, donde se produjo y cuanto cierra la traza."""

    if traza.delta_final_s is None:
        return "sin traza"
    partes = [f"delta final {traza.delta_final_s:+.3f} s "
              f"sobre {traza.largo_comun_m:,.0f} m"]
    if traza.residuo_s is not None:
        partes.append(f"residuo contra el cronometro {traza.residuo_s:+.3f} s")
    dominantes = tramos_dominantes(traza, 1)
    if dominantes:
        t = dominantes[0]
        partes.append(f"el tramo mas caro va del metro {t.desde_m:,.0f} al "
                      f"{t.hasta_m:,.0f} con {t.delta_s:+.3f} s")
    return "; ".join(partes)
