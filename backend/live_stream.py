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

# Tope de suscriptores simultaneos. El dashboard abre uno; el resto serian
# pestanas olvidadas. Se acota para que una fuga no consuma memoria sin limite.
MAX_SUSCRIPTORES = 16

# Cuantos mensajes se conservan por suscriptor si no consume a tiempo. Al
# llenarse se descarta lo mas viejo: en un flujo en vivo el dato reciente vale
# mas que el atrasado, y acumular introduciria una latencia creciente invisible.
COLA_POR_SUSCRIPTOR = 500


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
        # Se conserva una ventana corta para que un navegador que llega tarde
        # vea algo de inmediato en lugar de una pantalla vacia.
        self.recientes: deque = deque(maxlen=100)

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
            cuerpo = json.loads(mensaje.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.descartados += 1
            return

        cuerpo["_recibido_utc"] = datetime.now(timezone.utc).isoformat()
        self.recibidos += 1
        self.recientes.append(cuerpo)

        if self._bucle is None:
            return
        with self._candado:
            colas = list(self._suscriptores)
        for cola in colas:
            # Se entrega a traves del bucle porque este hilo no es el suyo.
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
        yield evento_sse(dato)
