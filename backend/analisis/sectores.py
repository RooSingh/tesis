# -*- coding: utf-8 -*-
"""Tiempos por sector, y quien es mejor en cada uno.

QUE CONTESTA
------------
La traza de delta dice **donde** se saca el tiempo, metro a metro. Esto contesta
una pregunta mas gruesa y mas facil de repetir de memoria: **en que tercio del
circuito es mejor cada uno**. Es la forma en que se habla de una vuelta en el
oficio, y es la que permite decir «sos mejor en el 1 y te sacan medio segundo en
el 2» sin mirar una curva.

Y trae **la vuelta ideal**: la suma de los mejores sectores propios. No es una
vuelta que se corrio; es la que se podria haber corrido juntando lo mejor de
cada tercio. La distancia entre la ideal y la mejor real dice cuanto hay sobre
la mesa sin mejorar nada, solo repitiendo lo que ya se hizo.

DE DONDE SALE, Y POR QUE NO ES LA CIFRA DEL JUEGO
-------------------------------------------------
**El simulador publica los tiempos de sector exactos**, con sus banderas de
validez por sector, en el paquete `session_history`. Ese paquete esta
decodificado en `backend/f1_udp.py` y **no cruza a la base**: no figura entre los
que alimentan senales. Lo que hay guardado es el indice de sector muestreado y
el cronometro de la vuelta.

De ahi se deriva el tiempo de cada sector, y **la derivacion se declara**. El
limite se ve en la primera muestra *despues* de cruzarlo, de modo que el error es
a lo sumo un intervalo de muestreo ---cincuenta milisegundos a veinte hercios---.
Eso es un orden de magnitud menor que lo que separa a dos pilotos en un sector,
asi que la respuesta sirve; publicarla sin la incerteza seria declarar una
precision que no se tiene.

EL INDICE QUE REBOTA
--------------------
Una vuelta recorre sus sectores **hacia adelante y una sola vez**. Un indice que
vuelve atras no es un limite: es un rebote, y contarlo partiria la vuelta en
pedazos. Medido sobre la sesion de Spa, donde hay mas de un coche bajo una misma
identidad, el indice cambiaba 3.135 veces en veintidos vueltas contra los 66
limites que existen.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend import db

SENAL_VUELTA = "lap_number"
SENAL_SECTOR = "sector_index"
SENAL_CRONOMETRO = "current_lap_time"
SENAL_INVALIDA = "lap_invalid"

#: Cuantos sectores tiene una vuelta. No se deduce del dato: es la division
#: oficial del circuito, y una vuelta que no los recorre a los tres no tiene
#: tiempos de sector, tiene dos de tres.
SECTORES = 3

ORIGEN = ("derivado del indice de sector y el cronometro de vuelta guardados. "
          "El simulador publica los tiempos exactos en su paquete "
          "`session_history`, que no se persiste")


@dataclass
class VueltaConSectores:
    """Una vuelta y lo que tardo en cada tercio del circuito."""

    vehiculo: str
    numero: int
    #: Por numero de sector (1, 2, 3), en segundos.
    sectores: dict[int, float] = field(default_factory=dict)
    duracion_s: float = 0.0

    def como_dict(self) -> dict:
        return {"vehiculo": self.vehiculo, "numero": self.numero,
                "sectores": {str(k): v for k, v in sorted(self.sectores.items())},
                "duracion_s": self.duracion_s}


@dataclass
class MejorSector:
    """El mejor tiempo de un sector, y de quien y de que vuelta es.

    EL CAMPO SE LLAMA `vuelta` Y NO `numero` PORQUE ASI SALE POR HTTP. La ruta
    serializa recorriendo **campos**, de modo que el nombre del campo es el
    contrato: llamarlo `numero` y traducirlo a `vuelta` en `como_dict` hacia que
    la vista leyera `undefined`, que es exactamente lo que mostro la primera vez
    que se lo miro en pantalla.
    """

    sector: int
    vehiculo: str
    vuelta: int
    duracion_s: float

    def como_dict(self) -> dict:
        return {"sector": self.sector, "vehiculo": self.vehiculo,
                "vuelta": self.vuelta, "duracion_s": self.duracion_s}


@dataclass
class Piloto:
    """Lo que un vehiculo hizo, resumido por sector."""

    vehiculo: str
    vueltas: list[VueltaConSectores] = field(default_factory=list)
    mejor_por_sector: dict[int, MejorSector] = field(default_factory=dict)
    mejor_vuelta_s: float | None = None
    #: La suma de los mejores sectores propios. No se corrio nunca.
    vuelta_ideal_s: float | None = None
    #: Cuanto se gana repitiendo lo ya hecho, sin mejorar nada.
    #:
    #: ES UN CAMPO Y NO UNA PROPIEDAD CALCULADA, y la razon es la frontera: la
    #: ruta serializa recorriendo los **campos** de la estructura, de modo que
    #: una propiedad se calcula bien y **no sale por HTTP**. Un resultado que
    #: existe en Python y no llega a quien pregunta es un resultado que no
    #: existe.
    sobre_la_mesa_s: float | None = None

    def como_dict(self) -> dict:
        return {
            "vehiculo": self.vehiculo,
            "vueltas": [v.como_dict() for v in self.vueltas],
            "mejor_por_sector": {str(k): v.como_dict()
                                 for k, v in sorted(self.mejor_por_sector.items())},
            "mejor_vuelta_s": self.mejor_vuelta_s,
            "vuelta_ideal_s": self.vuelta_ideal_s,
            "sobre_la_mesa_s": self.sobre_la_mesa_s,
        }


@dataclass
class Contraste:
    """Los sectores de una sesion, con quien manda en cada uno."""

    session_id: str
    fuente: str
    pilotos: list[Piloto] = field(default_factory=list)
    #: Cuanto vale la precision de estos tiempos, en segundos.
    incerteza_s: float | None = None
    origen: str = ORIGEN
    #: Quien manda en cada sector, entre todos. Campo por la misma razon que
    #: `sobre_la_mesa_s`: lo calculado en una propiedad no cruza la frontera.
    duenos: dict[int, MejorSector] = field(default_factory=dict)

    def piloto(self, vehiculo: str) -> Piloto | None:
        return next((p for p in self.pilotos if p.vehiculo == vehiculo), None)

    def vueltas_de(self, vehiculo: str) -> list[VueltaConSectores]:
        p = self.piloto(vehiculo)
        return p.vueltas if p else []

    def dueno_del_sector(self, sector: int) -> MejorSector | None:
        """Quien tiene el mejor tiempo de ese sector, entre todos."""

        return self.duenos.get(sector)

    def como_dict(self) -> dict:
        return {
            "session_id": self.session_id, "fuente": self.fuente,
            "incerteza_s": self.incerteza_s, "origen": self.origen,
            "sectores": SECTORES,
            "pilotos": [p.como_dict() for p in self.pilotos],
            "duenos": {str(s): (m.como_dict() if m else None)
                       for s, m in sorted(self.duenos.items())},
        }


CONSULTA = """
select timestamp, vehicle_id, signal_name, value_numeric, value_boolean
  from telemetry_messages
 where source_type = %s and session_id = %s
   and signal_name = any(%s){acotado}
 order by vehicle_id, timestamp, signal_name
"""


def _leer(cursor, fuente: str, session_id: str,
          vehiculos: tuple[str, ...] | None = None) -> list[tuple]:
    """Las cuatro señales que arman los sectores, de quien se pida.

    EL ACOTADO VA EN LA CONSULTA Y NO DESPUES. Estaba en el bucle: se traian
    las filas de los veintidos coches y se descartaban en Python las de los
    veintiuno que nadie habia pedido. Para pintar el panel de un solo vehiculo
    eso es leer veinte veces lo que hace falta, y se nota: la comparacion de
    reglajes de Spielberg ---tres sesiones, una de ellas una carrera--- tardaba
    16,4 s, casi toda en filas que se tiraban.
    """

    condicion = " and vehicle_id = any(%s)" if vehiculos else ""
    parametros = [fuente, session_id,
                  [SENAL_VUELTA, SENAL_SECTOR, SENAL_CRONOMETRO, SENAL_INVALIDA]]
    if vehiculos:
        parametros.append(list(vehiculos))
    cursor.execute(CONSULTA.format(acotado=condicion), tuple(parametros))
    return cursor.fetchall()


def _mediana(valores: list[float]) -> float:
    ordenados = sorted(valores)
    n = len(ordenados)
    if not n:
        return 0.0
    mitad = n // 2
    return (ordenados[mitad] if n % 2
            else (ordenados[mitad - 1] + ordenados[mitad]) / 2.0)


def _sectores_de(muestras: list[tuple[int, float]],
                 duracion_ms: float) -> dict[int, float] | None:
    """Los tres tiempos, de una lista de (indice_de_sector, cronometro_ms).

    SE AVANZA Y NO SE VUELVE. El indice mas alto visto es el sector en el que se
    esta; uno mas bajo se descarta. Es lo que hace que un rebote no parta la
    vuelta, y ademas es cierto: nadie recorre el sector 1 despues del 2.
    """

    cruces: dict[int, float] = {}
    mas_alto = 0
    for indice, ms in muestras:
        if indice > mas_alto:
            # La primera muestra ya dentro del sector nuevo. El limite quedo
            # entre esta y la anterior: de ahi sale la incerteza.
            cruces[indice] = ms
            mas_alto = indice

    if mas_alto < SECTORES - 1 or duracion_ms <= 0:
        return None

    s1 = cruces.get(1)
    s2 = cruces.get(2)
    if s1 is None or s2 is None or not (0 < s1 < s2 < duracion_ms):
        return None
    return {1: round(s1 / 1000.0, 3),
            2: round((s2 - s1) / 1000.0, 3),
            3: round((duracion_ms - s2) / 1000.0, 3)}


def extraer(fuente: str, session_id: str,
            vehiculos: tuple[str, ...] | None = None) -> Contraste:
    """Los tiempos por sector de cada vehiculo de la sesion."""

    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        filas = _leer(cursor, fuente, session_id, vehiculos)

    contraste = Contraste(session_id=session_id, fuente=fuente)
    if not filas:
        return contraste

    # (vehiculo, vuelta) -> estado mientras se recorre.
    acumulado: dict[tuple[str, int], dict] = {}
    orden: list[tuple[str, int]] = []
    intervalos_ms: list[float] = []
    vuelta_actual: dict[str, int] = {}

    # SE AGRUPA POR INSTANTE Y NO SE PROCESA FILA POR FILA.
    #
    # Las tres señales de una muestra viajan en el mismo paquete y llegan con la
    # misma marca de tiempo, pero **la base no garantiza en que orden devuelve
    # filas que empatan**. Procesandolas de a una, emparejar el sector con el
    # cronometro dependia de cual llegaba primero, y el resultado **cambiaba
    # entre dos corridas del mismo dato**: medido sobre Shanghai, el «sobre la
    # mesa» de un coche daba 0,341 s en una corrida y 0,491 en la siguiente.
    #
    # Un analisis que no repite su propio numero no es una medicion.
    instante: dict | None = None
    marca_actual = None
    vehiculo_actual = None

    def cerrar(inst):
        """Vuelca un instante completo sobre la vuelta a la que pertenece."""
        if inst is None or inst["vuelta"] is None:
            return
        clave = (inst["vehiculo"], inst["vuelta"])
        if clave not in acumulado:
            acumulado[clave] = {"muestras": [], "duracion_ms": 0.0,
                                "invalida": False}
            orden.append(clave)
        v = acumulado[clave]
        if inst["invalida"]:
            v["invalida"] = True
        ms = inst["ms"]
        if ms is not None:
            if ms > v["duracion_ms"]:
                v["duracion_ms"] = ms
            if inst["sector"] is not None:
                v["muestras"].append((inst["sector"], ms))

    for marca, vehiculo, nombre, numerico, booleano in filas:
        if marca != marca_actual or vehiculo != vehiculo_actual:
            cerrar(instante)
            if vehiculo == vehiculo_actual and marca_actual is not None:
                delta = (marca - marca_actual).total_seconds() * 1000.0
                if delta > 0:
                    intervalos_ms.append(delta)
            marca_actual, vehiculo_actual = marca, vehiculo
            instante = {"vehiculo": vehiculo, "vuelta": vuelta_actual.get(vehiculo),
                        "sector": None, "ms": None, "invalida": False}

        if nombre == SENAL_VUELTA and numerico is not None:
            vuelta_actual[vehiculo] = int(numerico)
            instante["vuelta"] = int(numerico)
        elif nombre == SENAL_INVALIDA and booleano:
            instante["invalida"] = True
        elif nombre == SENAL_SECTOR and numerico is not None:
            instante["sector"] = int(numerico)
        elif nombre == SENAL_CRONOMETRO and numerico is not None:
            instante["ms"] = float(numerico)

    cerrar(instante)

    por_vehiculo: dict[str, Piloto] = {}
    for vehiculo, numero in orden:
        v = acumulado[(vehiculo, numero)]
        if v["invalida"]:
            continue
        sectores = _sectores_de(v["muestras"], v["duracion_ms"])
        if sectores is None:
            continue
        piloto = por_vehiculo.setdefault(vehiculo, Piloto(vehiculo=vehiculo))
        piloto.vueltas.append(VueltaConSectores(
            vehiculo=vehiculo, numero=numero, sectores=sectores,
            duracion_s=round(v["duracion_ms"] / 1000.0, 3)))

    for piloto in por_vehiculo.values():
        for vuelta in piloto.vueltas:
            for sector, duracion in vuelta.sectores.items():
                mejor = piloto.mejor_por_sector.get(sector)
                if mejor is None or duracion < mejor.duracion_s:
                    piloto.mejor_por_sector[sector] = MejorSector(
                        sector=sector, vehiculo=piloto.vehiculo,
                        vuelta=vuelta.numero, duracion_s=duracion)
        piloto.mejor_vuelta_s = min(v.duracion_s for v in piloto.vueltas)
        if len(piloto.mejor_por_sector) == SECTORES:
            piloto.vuelta_ideal_s = round(
                sum(m.duracion_s for m in piloto.mejor_por_sector.values()), 3)
            piloto.sobre_la_mesa_s = round(
                piloto.mejor_vuelta_s - piloto.vuelta_ideal_s, 3)

    contraste.pilotos = [por_vehiculo[k] for k in sorted(por_vehiculo)]
    for sector in range(1, SECTORES + 1):
        candidatos = [p.mejor_por_sector[sector] for p in contraste.pilotos
                      if sector in p.mejor_por_sector]
        if candidatos:
            contraste.duenos[sector] = min(candidatos,
                                           key=lambda m: m.duracion_s)
    if intervalos_ms:
        contraste.incerteza_s = round(_mediana(intervalos_ms) / 1000.0, 3)
    return contraste
