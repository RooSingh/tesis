"""Camino en vivo: del broker al navegador, en paralelo a la persistencia.

Por que un camino distinto del historico
----------------------------------------
El escenario experimental que contrasta **modo en vivo contra post-sesion** solo
significa algo si los dos modos recorren caminos realmente distintos. Si ambos
leyeran de la base, la comparacion enfrentaria la misma cosa consigo misma.

Aca el camino en vivo es::

    broker MQTT  ->  este modulo  ->  navegador

mientras el historico sigue siendo::

    base de datos  ->  API  ->  consulta del navegador

**Ambos caminos coexisten y son independientes.** La persistencia no se ve
afectada: el consumidor sigue guardando en paralelo. Este modulo solo observa el
mismo flujo.

Por que eventos enviados por el servidor
----------------------------------------
La telemetria va en una sola direccion: el navegador no le manda nada al vehiculo.
Un canal bidireccional resolveria un problema que no existe. Los eventos enviados
por el servidor son un mecanismo estandar del navegador, unidireccional, con
reconexion automatica, y no requieren dependencias nuevas ni configurar el broker.

Que se declara
--------------
Cada evento llega con la marca temporal de publicacion que el mensaje ya trae y
con la de recepcion en el servidor, de modo que **la latencia sea medible** y no
haya que inferirla.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any

from backend.config import MQTT_HOST, MQTT_PORT, MQTT_TOPIC

from backend import anotador_vivo, resumen_sesion

# Tope de suscriptores simultaneos. El dashboard abre uno; el resto serian
# pestanas olvidadas. Se acota para que una fuga no consuma memoria sin limite.
MAX_SUSCRIPTORES = 16

# Cuantos mensajes se conservan por suscriptor si no consume a tiempo. Al
# llenarse se descarta lo mas viejo: en un flujo en vivo el dato reciente vale
# mas que el atrasado, y acumular introduciria una latencia creciente invisible.
COLA_POR_SUSCRIPTOR = 500

# Cuantas muestras se conservan **por senal** para quien llega tarde.
#
# Sin esto, abrir la pagina a mitad de una vuelta mostraba las trazas vacias y
# dibujando desde ese instante, como si antes no hubiera pasado nada. La vista
# arrancaba en el momento de conectarse y no en el momento en que el vehiculo
# salio a pista, que es lo que quien mira espera ver.
#
# Seiscientas muestras son los treinta segundos que la traza dibuja a la
# frecuencia declarada por el juego. Con noventa y ocho senales son unas sesenta
# mil entradas: memoria acotada y conocida, que es lo que un tope por senal
# garantiza y un tope global no.
MUESTRAS_POR_SENAL = 600


def _segundo_de(marca) -> float | None:
    """Convierte la marca temporal del mensaje en segundos absolutos.

    Devuelve ``None`` si la marca falta o no se puede leer. El resumen se
    saltea ese punto en lugar de inventar un instante: una serie con un valor
    ubicado en el momento equivocado es peor que una serie con un hueco.
    """

    if not marca:
        return None
    try:
        return datetime.fromisoformat(marca).timestamp()
    except (TypeError, ValueError):
        return None


class DifusorEnVivo:
    """Recibe del broker y reparte a los suscriptores conectados.

    El cliente MQTT corre en su propio hilo, de modo que la entrega a las colas
    asincronas se hace a traves del bucle de eventos y no directamente.
    """

    def __init__(self) -> None:
        self._bucle: asyncio.AbstractEventLoop | None = None
        self._cliente = None
        self._suscriptores: list[asyncio.Queue] = []
        self._candado = threading.Lock()
        self.conectado = False
        self.motivo: str | None = None
        self.recibidos = 0
        self.descartados = 0
        self.fallos_anotador = 0
        self.motivo_anotador: str | None = None
        # Se conserva una ventana corta para que un navegador que llega tarde
        # vea algo de inmediato en lugar de una pantalla vacia.
        self.recientes: deque = deque(maxlen=100)
        # Y una historia **por senal**, que es lo que las trazas necesitan: la
        # ventana corta alcanza para llenar las tarjetas y no para dibujar.
        # La historia se indexa **por vehiculo y por senal**, en ese orden.
        #
        # Indexarla solo por senal alcanzaba mientras se normalizaba un unico
        # vehiculo. Con dos conductores en pantalla dividida, las muestras de los
        # dos caian en la misma serie y la traza dibujaba una linea que no
        # describia a ninguno.
        self.historia: dict[str, dict[str, deque]] = {}
        # Y el instante de cada una de esas muestras.
        #
        # Sin el, una anotacion y una traza no se pueden relacionar: la anotacion
        # dice cuando paso algo y la traza es una secuencia sin eje temporal
        # explicito. El tiempo es lo unico que las dos comparten.
        self.historia_tiempos: dict[str, dict[str, deque]] = {}
        # Y la distancia recorrida, que es como las herramientas de telemetria
        # alinean dos vueltas: por lugar del circuito y no por reloj, de modo que
        # la frenada y el apice coincidan aunque uno vaya mas rapido.
        self.historia_distancia: dict[str, deque] = {}
        #: La sesion entera, a un intervalo por segundo con su minimo y su
        #: maximo. Convive con la ventana de arriba y no la reemplaza: una da
        #: el detalle reciente y la otra el recorrido completo.
        self.resumen = resumen_sesion.ResumenDeSesion()
        # El anotador mira el mismo flujo y declara lo que ocurre mientras
        # ocurre. Vive en el difusor y no en el navegador por dos razones: ve
        # **todas** las senales y no solo las que alguien eligio mirar, y su
        # salida queda del lado del servidor, donde puede citarse despues.
        # **Un anotador por vehiculo.** Uno solo compondria instantes con canales
        # de dos autos distintos y podria declarar incidentes que no ocurrieron.
        self.anotadores: dict[str, anotador_vivo.Anotador] = {}

    # -- ciclo de vida ---------------------------------------------------- #

    def iniciar(self, bucle: asyncio.AbstractEventLoop) -> None:
        """Conecta al broker. Un fallo no detiene la aplicacion."""

        self._bucle = bucle
        try:
            import paho.mqtt.client as mqtt

            self._cliente = mqtt.Client()
            self._cliente.on_connect = self._al_conectar
            self._cliente.on_message = self._al_recibir
            self._cliente.connect(MQTT_HOST, MQTT_PORT, 10)
            self._cliente.loop_start()
            self.conectado = True
        except Exception as error:
            self._cliente = None
            self.conectado = False
            self.motivo = f"{type(error).__name__}: {error}"

    def detener(self) -> None:
        if self._cliente is not None:
            self._cliente.loop_stop()
            self._cliente.disconnect()
            self._cliente = None
        self.conectado = False

    # -- callbacks del cliente MQTT, en su propio hilo --------------------- #

    def _al_conectar(self, cliente, _datos, _flags, _rc) -> None:
        cliente.subscribe(MQTT_TOPIC, qos=0)

    def _al_recibir(self, _cliente, _datos, mensaje) -> None:
        try:
            contenido = json.loads(mensaje.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.descartados += 1
            return

        cuerpos = contenido if isinstance(contenido, list) else [contenido]
        recibido_utc = datetime.now(timezone.utc).isoformat()
        for cuerpo in cuerpos:
            if not isinstance(cuerpo, dict):
                self.descartados += 1
                continue
            self._procesar_cuerpo(dict(cuerpo), recibido_utc)

    def _procesar_cuerpo(self, cuerpo: dict, recibido_utc: str) -> None:
        """Registra y reparte una senal de un mensaje MQTT simple o agrupado."""

        cuerpo["_recibido_utc"] = recibido_utc
        self.recibidos += 1
        self.recientes.append(cuerpo)

        senal = cuerpo.get("signal_name")
        vehiculo = cuerpo.get("vehicle_id") or "sin-vehiculo"
        if senal is not None:
            del_vehiculo = self.historia.setdefault(vehiculo, {})
            tiempos = self.historia_tiempos.setdefault(vehiculo, {})
            serie = del_vehiculo.get(senal)
            if serie is None:
                serie = del_vehiculo[senal] = deque(maxlen=MUESTRAS_POR_SENAL)
                tiempos[senal] = deque(maxlen=MUESTRAS_POR_SENAL)
            serie.append(cuerpo.get("value"))
            tiempos[senal].append(cuerpo.get("timestamp"))
            # Y en paralelo, la sesion entera a resolucion reducida.
            #
            # La ventana de arriba conserva treinta segundos y descarta lo
            # anterior, de modo que su eje se desplaza y una anotacion vieja no
            # tiene donde dibujarse. El resumen conserva **toda** la sesion con
            # el minimo y el maximo de cada segundo, que es lo que permite un
            # eje que crece en lugar de correrse.
            segundo = _segundo_de(cuerpo.get("timestamp"))
            if segundo is not None:
                self.resumen.observar(vehiculo, senal, segundo,
                                      cuerpo.get("value"))
            if senal == "lap_distance":
                self.historia_distancia.setdefault(
                    vehiculo, deque(maxlen=MUESTRAS_POR_SENAL)
                ).append(cuerpo.get("value"))

        # Un fallo del anotador no puede cortar el reparto: interpretar es
        # accesorio y transportar no lo es. El mismo criterio vale para el
        # resumen: si el mensaje no trae una marca temporal legible, se pierde
        # ese punto del resumen y no la difusion.
        try:
            anotador = self.anotadores.get(vehiculo)
            if anotador is None:
                anotador = self.anotadores[vehiculo] = anotador_vivo.Anotador(
                    al_anotar=lambda a, v=vehiculo: self._repartir_anotacion(a, v))
            anotador.observar(cuerpo)
        except Exception as error:
            self.fallos_anotador += 1
            self.motivo_anotador = f"{type(error).__name__}: {error}"

        if self._bucle is None:
            return
        with self._candado:
            colas = list(self._suscriptores)
        for cola in colas:
            # Se entrega a traves del bucle porque este hilo no es el suyo.
            self._bucle.call_soon_threadsafe(self._encolar, cola, cuerpo)

    def _repartir_anotacion(self, anotacion: dict, vehiculo: str = "") -> None:
        """Envia una anotacion recien emitida por el mismo canal que los datos.

        Viaja marcada con `_evento` para que el navegador la reconozca sin tener
        que adivinar por su forma.
        """

        cuerpo = dict(anotacion)
        cuerpo["_evento"] = "anotacion"
        # Sin esto, dos conductores producirian una lista mezclada en la que no se
        # podria saber a quien le paso cada cosa.
        cuerpo["vehiculo"] = vehiculo
        if self._bucle is None:
            return
        with self._candado:
            colas = list(self._suscriptores)
        for cola in colas:
            self._bucle.call_soon_threadsafe(self._encolar, cola, cuerpo)

    @staticmethod
    def _encolar(cola: asyncio.Queue, cuerpo: dict) -> None:
        if cola.full():
            # Se descarta lo mas viejo: en vivo, el dato reciente vale mas.
            try:
                cola.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            cola.put_nowait(cuerpo)
        except asyncio.QueueFull:
            pass

    # -- suscripcion ------------------------------------------------------- #

    def suscribir(self) -> asyncio.Queue | None:
        """Registra un suscriptor. Devuelve None si se alcanzo el tope."""

        with self._candado:
            if len(self._suscriptores) >= MAX_SUSCRIPTORES:
                return None
            cola: asyncio.Queue = asyncio.Queue(maxsize=COLA_POR_SUSCRIPTOR)
            self._suscriptores.append(cola)
            return cola

    def desuscribir(self, cola: asyncio.Queue) -> None:
        with self._candado:
            if cola in self._suscriptores:
                self._suscriptores.remove(cola)

    # -- estado ------------------------------------------------------------ #

    def estado(self) -> dict[str, Any]:
        with self._candado:
            suscriptores = len(self._suscriptores)
        return {
            "conectado": self.conectado,
            "motivo": self.motivo,
            "topico": MQTT_TOPIC,
            "broker": f"{MQTT_HOST}:{MQTT_PORT}",
            "suscriptores": suscriptores,
            "maximo_suscriptores": MAX_SUSCRIPTORES,
            "mensajes_recibidos": self.recibidos,
            "mensajes_descartados": self.descartados,
            # Se declaran los dos caminos y no solo este. Anunciar unicamente
            # "sin pasar por la base" es cierto y a la vez enganoso: leido solo,
            # dice que el dato no se guarda. Lo que no pasa por la base es
            # **esta vista**; la persistencia corre en paralelo y no depende de
            # ella.
            "vehiculos": sorted(self.historia),
            "senales_con_historia": sum(len(s) for s in self.historia.values()),
            "anotaciones": sum(len(a.anotaciones) for a in self.anotadores.values()),
            "fallos_anotador": self.fallos_anotador,
            "motivo_anotador": self.motivo_anotador,
            "camino_vista": ("broker -> difusor -> navegador "
                             "(solo esta vista, no pasa por la base)"),
            "camino_persistencia": ("broker -> consumidor -> base de datos "
                                    "(en paralelo, independiente de esta vista)"),
        }


difusor = DifusorEnVivo()


def evento_sse(dato: dict, evento: str = "telemetria") -> str:
    """Formatea un evento segun el protocolo de eventos enviados por el servidor."""

    return f"event: {evento}\ndata: {json.dumps(dato, ensure_ascii=False)}\n\n"


async def flujo_de_eventos(cola: asyncio.Queue, intervalo_latido_s: float = 15.0):
    """Genera el flujo de eventos para un suscriptor.

    Emite un latido periodico cuando no hay telemetria: sin el, un intermediario
    podria cerrar una conexion inactiva y el navegador no distinguiria entre
    "no hay datos" y "se corto".
    """

    yield evento_sse(difusor.estado(), "estado")
    while True:
        try:
            dato = await asyncio.wait_for(cola.get(), timeout=intervalo_latido_s)
        except asyncio.TimeoutError:
            yield evento_sse({"momento": datetime.now(timezone.utc).isoformat(),
                              "recibidos": difusor.recibidos}, "latido")
            continue
        yield evento_sse(dato, dato.get("_evento", "telemetria"))
