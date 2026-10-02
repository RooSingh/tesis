# -*- coding: utf-8 -*-
"""Separa una sesion en vueltas y decide cuales son comparables entre si.

Por que va primero
------------------
Es la unica de las siete herramientas que no produce una conclusion, y es la que
decide si las otras seis valen. **Todo analisis comparativo es invalido si se
comparan vueltas no comparables**, y el trabajo ya pago esa cuenta: sin este
filtro, la lectura de dos capturas del Hungaroring concluyo que quitar el control
de traccion costaba once segundos por vuelta. Era falso; la vuelta lenta tenia un
trompo.

Construirla al final habria significado levantar conclusiones sobre dato sin
filtrar para tener que revisarlas despues.

Que la ensucia, y por que cada motivo
-------------------------------------
Cuatro condiciones, y ninguna es un criterio propio: las cuatro las declara el
dato o el reglamento.

``invalidada``
    La sesion misma la invalido. El canal lo dice; no se recalcula.
``boxes``
    El canal de estado de boxes declara que el vehiculo entraba o estaba en
    ellos. Una vuelta de entrada o de salida no mide ritmo, mide una maniobra.
``bandera``
    Amarilla obliga a levantar y prohibe adelantar; roja detiene la sesion; azul
    obliga a ceder el paso. Las tres cambian lo que se puede hacer, de modo que
    el tiempo deja de describir al conductor.
``incompleta``
    No se presencio su comienzo o su final. Es el caso de la primera y la ultima
    vuelta de cualquier captura, que empiezan o terminan a mitad de camino.

Dos listas y no una
-------------------
Las cuatro condiciones no responden la misma pregunta, y confundirlas seria repetir
un error que este trabajo ya identifico: **el canal de validez de la fuente
responde «esta vuelta cuenta para el reglamento», que no es «esta vuelta se puede
comparar contra otra»**. Una colision no infringe los limites de pista, de modo que
la fuente no anula la vuelta ---y con razon---, pero esa vuelta no sirve para
comparar ritmo.

De ahi que cada vuelta lleve dos veredictos:

``valida``
    lo que la sesion declara. No se recalcula ni se discute.
``comparable``
    valida **y ademas** sin boxes, sin bandera y con sus dos bordes presenciados.

Cada vuelta no comparable **conserva sus motivos**. Descartar sin decir por que
obliga a confiar; con el motivo, quien lee puede discrepar del criterio y volver a
filtrar.

Lo que declara y no estima
--------------------------
La duracion sale del cronometro de la propia sesion, leido en la ultima muestra
antes de cruzar la linea. Eso la **subestima por hasta un intervalo de muestreo**
---cincuenta milisegundos a veinte hercios--- y esa cota viaja con el resultado en
lugar de corregirse con una interpolacion que nadie midio.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend import db
from backend.analisis.disponibilidad import (
    DEGRADADA,
    IMPOSIBLE,
    Disponibilidad,
    evaluar,
)

#: Codigos de bandera que hacen que el tiempo deje de describir al conductor.
#: El catalogo del canal es -1 desconocida, 0 ninguna, 1 verde, 2 azul,
#: 3 amarilla, 4 roja. La verde y la ausencia de bandera no ensucian nada.
BANDERAS_QUE_ENSUCIAN = {
    2: "azul: obligacion de ceder el paso",
    3: "amarilla: obligacion de levantar y prohibicion de adelantar",
    4: "roja: sesion detenida",
}

#: Estados del canal de boxes: 0 ninguno, 1 entrando, 2 en boxes.
BOXES_QUE_ENSUCIAN = {1: "entrada a boxes", 2: "paso por boxes"}

#: Senales que la herramienta lee, en el orden en que se declaran sus requisitos.
SENAL_NUMERO = "lap_number"

#: Con que se detecta que una vuelta tiene mas de un coche adentro.
#:
#: EL CASO QUE LO MOTIVA, MEDIDO EL 2026-09-12. La sesion de Spa del conjunto
#: `spa_original` tiene **dos conductores escritos bajo el mismo `vehicle_id`**
#: en sus vueltas 1 y 2: dos series de 20 Hz entrelazadas, desfasadas 17 ms, con
#: los coches hasta 577 metros separados. De la vuelta 3 en adelante la serie es
#: de un solo coche. Quedo documentado, y **un documento no impide que el
#: proximo analisis use la vuelta 2**: por eso el criterio vive aca, donde ya
#: viven los de boxes y bandera, y no solo en un documento.
#:
#: LA FIRMA. Un coche solo nunca retrocede seiscientos metros; dos coches
#: entrelazados lo hacen en cada muestra. Lo que se cuenta son retrocesos
#: grandes de la distancia de vuelta.
SENAL_DISTANCIA = "lap_distance"

#: Cuanto tiene que retroceder la distancia para que no pueda ser un coche solo.
#:
#: Doscientos metros a doscientos por hora son tres segundos y medio de marcha
#: atras. La separacion medida entre los dos coches de Spa era de 577 m; el
#: ruido de la señal, de centimetros. Entre esas dos escalas hay sitio de sobra.
SALTO_IMPOSIBLE_M = 200.0

#: Cuantos retrocesos se toleran antes de acusar a la vuelta.
#:
#: UNO ES EL CRUCE DE META, que es un retroceso legitimo: de siete mil metros a
#: cero. Con cero de tolerancia, **todas** las vueltas quedarian fuera y el
#: criterio no distinguiria nada, que es la manera silenciosa de que una
#: comprobacion deje de comprobar. Medido sobre las veinte vueltas limpias de
#: Spa: exactamente uno cada una.
RETROCESOS_TOLERADOS = 1

MOTIVO_DOS_COCHES = ("la distancia de vuelta retrocede {n} veces mas de "
                     "{m:,.0f} m: hay mas de un coche bajo esta identidad")
SENAL_INVALIDA = "lap_invalid"
SENAL_BOXES = "pit_status"
SENAL_BANDERA = "fia_flag"
SENAL_CRONOMETRO = "current_lap_time"

MOTIVO_INVALIDADA = "invalidada por la sesion"
MOTIVO_INCOMPLETA = "no se presencio su comienzo o su final"


class SinVueltas(Exception):
    """La sesion no admite separarse en vueltas, y se dice por que.

    Se levanta en lugar de devolver una lista vacia porque las dos situaciones
    ---una sesion sin vueltas limpias y una fuente sin vueltas--- son distintas y
    confundirlas haria que un bus de vehiculo de calle se lea como una sesion
    entera de vueltas sucias.
    """

    def __init__(self, disponibilidad: Disponibilidad) -> None:
        self.disponibilidad = disponibilidad
        super().__init__("; ".join(disponibilidad.impedimentos))


@dataclass
class Vuelta:
    """Una vuelta, con el veredicto y su fundamento."""

    numero: int
    desde_ms: float
    hasta_ms: float
    #: Del cronometro de la sesion. `None` cuando la vuelta no llego a cerrarse.
    duracion_s: float | None
    #: Lo que la sesion declara: si la vuelta cuenta para el reglamento.
    valida: bool
    #: Si ademas sirve para comparar contra otra vuelta.
    comparable: bool
    #: Por que no es comparable. Vacio cuando lo es.
    motivos: list[str] = field(default_factory=list)
    muestras: int = 0

    def como_dict(self) -> dict:
        return {"numero": self.numero, "desde_ms": self.desde_ms,
                "hasta_ms": self.hasta_ms, "duracion_s": self.duracion_s,
                "valida": self.valida, "comparable": self.comparable,
                "motivos": list(self.motivos),
                "muestras": self.muestras}


@dataclass
class Sesion:
    """Las vueltas de una sesion, con la declaracion que las describe."""

    session_id: str
    fuente: str
    #: Viaja con el resultado y no en una nota al pie: quien lea las vueltas
    #: tiene que poder ver con que limitaciones se obtuvieron.
    disponibilidad: Disponibilidad
    vueltas: list[Vuelta] = field(default_factory=list)
    #: Cota de la duracion, en segundos. Es el intervalo de muestreo: el
    #: cronometro se lee en la ultima muestra antes de cruzar.
    incerteza_duracion_s: float | None = None

    @property
    def validas(self) -> list[Vuelta]:
        """Las que cuentan para el reglamento, segun la propia sesion."""

        return [v for v in self.vueltas if v.valida]

    @property
    def comparables(self) -> list[Vuelta]:
        """Las que ademas sirven para comparar contra otra."""

        return [v for v in self.vueltas if v.comparable]

    def como_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "fuente": self.fuente,
            "disponibilidad": self.disponibilidad.como_dict(),
            "incerteza_duracion_s": self.incerteza_duracion_s,
            "vueltas": [v.como_dict() for v in self.vueltas],
            "validas": len(self.validas),
            "comparables": len(self.comparables),
            "total": len(self.vueltas),
        }


def _leer(cursor, fuente: str, session_id: str,
          contexto: tuple[str | None, str | None, str | None],
          senales: tuple[str, ...]) -> list[tuple]:
    """Trae las senales de vuelta de **un** vehiculo y **una** corrida.

    El recorte es el mismo sobre el que se declaro la disponibilidad. Leer de uno
    distinto haria que la declaracion no describa al resultado, que es la clase de
    desajuste que ya multiplico por veintitres una frecuencia.
    """

    conductor, vehiculo, corrida = contexto
    marcador = ",".join(["%s"] * len(senales))
    cursor.execute(
        f"""select timestamp, signal_name, value_numeric, value_boolean
            from telemetry_messages
            where source_type = %s and session_id = %s
              and driver_id is not distinct from %s
              and vehicle_id is not distinct from %s
              and replay_run_id is not distinct from %s
              and signal_name in ({marcador})
            order by timestamp""",
        (fuente, session_id, conductor, vehiculo, corrida, *senales),
    )
    return cursor.fetchall()


def _mediana(valores: list[float]) -> float:
    """La mediana, que no la mueve un intervalo suelto.

    El promedio si la moveria: un unico salto en el flujo ---y los hay, porque el
    sistema operativo no garantiza el paso--- corre la cifra que despues se
    declara como precision del resultado.
    """

    ordenados = sorted(valores)
    mitad = len(ordenados) // 2
    if len(ordenados) % 2:
        return ordenados[mitad]
    return (ordenados[mitad - 1] + ordenados[mitad]) / 2.0


def _valor(numerico, booleano) -> float | None:
    """Un canal puede llegar por cualquiera de las dos columnas."""

    if booleano is not None:
        return 1.0 if booleano else 0.0
    if numerico is None:
        return None
    return float(numerico)


def extraer(fuente: str, session_id: str) -> Sesion:
    """Separa la sesion en vueltas y marca cuales son comparables.

    Solo aplica los criterios que la sesion admite. Si el canal de boxes no
    esta, no se inventa una vuelta de boxes: la limitacion ya quedo declarada y
    el resultado la lleva encima.
    """

    disponible = evaluar("vueltas_limpias", fuente, session_id)
    if disponible.estado == IMPOSIBLE:
        raise SinVueltas(disponible)

    contexto = disponible.contexto or (None, None, None)
    # Se piden solo las senales que esta sesion tiene. Pedir una ausente no
    # falla, pero recorrer sus filas inexistentes en cada vuelta si confunde.
    presentes = {m.senal for m in disponible.mediciones if m.presente and m.senal}
    senales = tuple(s for s in (SENAL_NUMERO, SENAL_INVALIDA, SENAL_BOXES,
                                SENAL_BANDERA, SENAL_DISTANCIA, SENAL_CRONOMETRO)
                    if s in presentes or s == SENAL_CRONOMETRO)
    #: El mismo conjunto rige **dentro del recorrido** y no solo en la consulta.
    #: Acotar solo la consulta bastaria mientras las dos cosas coincidan, y dejan
    #: de coincidir en cuanto un canal existe en la base pero no llega a
    #: declararse presente ---por ejemplo, sin muestras en la ventana de
    #: medicion---. Ahi el resultado aplicaria un criterio que la declaracion dice
    #: no poder aplicar, y el desajuste no seria visible desde ninguno de los dos
    #: lados.
    usables = set(senales)

    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        filas = _leer(cursor, fuente, session_id, contexto, senales)

    sesion = Sesion(session_id=session_id, fuente=fuente,
                    disponibilidad=disponible)
    if not filas:
        return sesion

    origen = filas[0][0]
    #: Estado por vuelta mientras se recorre. Se acumula lo peor visto: una
    #: vuelta que toco boxes en un instante es una vuelta de boxes aunque los
    #: otros mil instantes digan que no.
    acumulado: dict[int, dict] = {}
    orden: list[int] = []
    numero_actual: int | None = None
    intervalos_ms: list[float] = []
    marca_anterior = None

    for marca, nombre, numerico, booleano in filas:
        ms = (marca - origen).total_seconds() * 1000.0
        valor = _valor(numerico, booleano)
        if valor is None:
            continue

        if nombre == SENAL_NUMERO:
            numero_actual = int(valor)
            if numero_actual not in acumulado:
                acumulado[numero_actual] = {
                    "desde_ms": ms, "hasta_ms": ms, "muestras": 0,
                    "invalida": False, "boxes": set(), "banderas": set(),
                    "cronometro_ms": None,
                    "retrocesos": 0, "metro_anterior": None,
                }
                orden.append(numero_actual)
            # El intervalo de muestreo sale de este canal, que es el que marca
            # el paso de la sesion. Se juntan todos y despues se toma la mediana:
            # quedarse con el ultimo declaraba diecisiete milisegundos sobre una
            # sesion de veinte hercios, es decir **una precision mejor que la
            # real**, que es justamente lo que este modulo existe para no hacer.
            if marca_anterior is not None:
                delta = (marca - marca_anterior).total_seconds() * 1000.0
                if delta > 0:
                    intervalos_ms.append(delta)
            marca_anterior = marca

        if numero_actual is None or numero_actual not in acumulado:
            continue
        v = acumulado[numero_actual]
        v["hasta_ms"] = ms
        v["muestras"] += 1

        if nombre not in usables:
            continue
        if nombre == SENAL_INVALIDA and valor:
            v["invalida"] = True
        elif nombre == SENAL_BOXES and int(valor) in BOXES_QUE_ENSUCIAN:
            v["boxes"].add(int(valor))
        elif nombre == SENAL_BANDERA and int(valor) in BANDERAS_QUE_ENSUCIAN:
            v["banderas"].add(int(valor))
        elif nombre == SENAL_DISTANCIA:
            previo = v["metro_anterior"]
            if previo is not None and previo - valor > SALTO_IMPOSIBLE_M:
                v["retrocesos"] += 1
            v["metro_anterior"] = valor
        elif nombre == SENAL_CRONOMETRO:
            anterior = v["cronometro_ms"]
            v["cronometro_ms"] = valor if anterior is None else max(anterior, valor)

    for posicion, numero in enumerate(orden):
        v = acumulado[numero]
        motivos: list[str] = []
        if v["invalida"]:
            motivos.append(MOTIVO_INVALIDADA)
        for codigo in sorted(v["boxes"]):
            motivos.append(BOXES_QUE_ENSUCIAN[codigo])
        for codigo in sorted(v["banderas"]):
            motivos.append(BANDERAS_QUE_ENSUCIAN[codigo])
        # Solo cuando la sesion publica distancia. El mismo criterio que rige
        # para boxes y bandera: no se acusa a una vuelta con una comprobacion
        # que no se pudo hacer.
        if SENAL_DISTANCIA in usables and v["retrocesos"] > RETROCESOS_TOLERADOS:
            motivos.append(MOTIVO_DOS_COCHES.format(n=v["retrocesos"],
                                                    m=SALTO_IMPOSIBLE_M))
        # La primera y la ultima de la captura empiezan o terminan a mitad de
        # camino. No se presencio su borde, y una vuelta cuyo borde no se vio no
        # se puede cronometrar ni comparar.
        if posicion == 0 or posicion == len(orden) - 1:
            motivos.append(MOTIVO_INCOMPLETA)

        cronometro = v["cronometro_ms"]
        sesion.vueltas.append(Vuelta(
            numero=numero, desde_ms=round(v["desde_ms"], 1),
            hasta_ms=round(v["hasta_ms"], 1),
            duracion_s=(round(cronometro / 1000.0, 3)
                        if cronometro is not None and MOTIVO_INCOMPLETA not in motivos
                        else None),
            valida=not v["invalida"], comparable=not motivos,
            motivos=motivos, muestras=v["muestras"]))

    if intervalos_ms:
        sesion.incerteza_duracion_s = round(_mediana(intervalos_ms) / 1000.0, 3)
    return sesion


def resumen(sesion: Sesion) -> str:
    """Una linea que dice cuantas quedaron y por que se fueron las demas."""

    total = len(sesion.vueltas)
    validas = len(sesion.validas)
    comparables = len(sesion.comparables)
    conteo: dict[str, int] = {}
    for v in sesion.vueltas:
        for m in v.motivos:
            conteo[m] = conteo.get(m, 0) + 1
    if not conteo:
        return f"{validas} validas y {comparables} comparables de {total}"
    detalle = ", ".join(f"{n} por {m}" for m, n in
                        sorted(conteo.items(), key=lambda p: -p[1]))
    aviso = ""
    if sesion.disponibilidad.estado == DEGRADADA:
        aviso = (f"  [con limitaciones: "
                 f"{len(sesion.disponibilidad.limitaciones)}]")
    return (f"{validas} validas y {comparables} comparables de {total} "
            f"({detalle}){aviso}")
