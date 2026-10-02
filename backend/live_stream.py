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

#: Cuantas sesiones recuerda el difusor. Ocho cubre una tarde de trabajo y no
#: crece sin techo si alguien lo deja corriendo una semana.
MAXIMO_SESIONES_ANOTADAS = 8

from backend import anotador_vivo, resumen_sesion

# Tope de suscriptores simultaneos. El dashboard abre uno; el resto serian
# pestanas olvidadas. Se acota para que una fuga no consuma memoria sin limite.
MAX_SUSCRIPTORES = 16

# Cuantas senales se conservan por suscriptor si no consume a tiempo. Al
# llenarse se descarta lo mas viejo: en un flujo en vivo el dato reciente vale
# mas que el atrasado, y acumular introduciria una latencia creciente invisible.
#
# ERAN 500, Y ESO SON CUARENTA Y SIETE MILISEGUNDOS.
#
# A las 10.600 senales/s que produce una carrera de seis vehiculos, quinientas
# ranuras se llenan en 47 ms: menos de lo que tarda un cuadro lento del
# navegador. Cualquier pausa ---una recoleccion de basura, una pestana que pasa
# a segundo plano--- vaciaba la cola entera. Medido en esa carrera: el difusor
# recibio 1.416.819 senales y entrego 89.250, un 6,3 %, con 3.044.945 descartes.
#
# Doce mil cubren algo mas de un segundo de esa misma carrera, que es margen
# para un parpadeo sin volverse una latencia que se note: mas alla de un segundo
# lo que se entrega ya no es «en vivo». Ocupan unos cinco megabytes por
# suscriptor con el contrato de vista adelgazado, sobre los 8 GB de la Pi.
COLA_POR_SUSCRIPTOR = 12000

# Cuantas senales viajan dentro de un evento SSE. El flujo MQTT ya llega
# agrupado, pero se desarmaba y se enviaba una respuesta HTTP por senal. Con
# seis vehiculos la sesion de Spa produjo unas 10.600 senales/s y cada
# suscriptor solo alcanzo a retirar unas 670/s: la cola descartaba alrededor del
# 94 %, independientemente del camino de persistencia. Agrupar reduce el trabajo
# de transporte sin cambiar las muestras ni su orden.
SENALES_POR_EVENTO = 250

# El navegador no consulta procedencia CAN ni el bloque ``metadata`` para
# pintar el vivo. En la carrera de seis vehiculos, repetirlos en cada senal
# ocupaba 765 bytes por muestra; este contrato de vista ocupa 336, un 56 %
# menos. La historia y ``/live/recent`` conservan el mensaje completo: solo se
# adelgaza la copia que cruza SSE.
CAMPOS_DE_VISTA = (
    "timestamp", "vehicle_id", "session_id", "source_type", "signal_name",
    "value", "unit", "_recibido_utc",
)


def _para_vista(cuerpo: dict) -> dict:
    """Proyecta una senal al contrato que consume el dashboard en vivo."""

    return {campo: cuerpo[campo] for campo in CAMPOS_DE_VISTA if campo in cuerpo}


#: CUANTAS ANOTACIONES ESPERAN POR SUSCRIPTOR.
#:
#: Las anotaciones tienen su propia cola, y no por orden sino por supervivencia.
#: Repartirlas primero dentro de una cola compartida no las conserva: la cola
#: descarta lo mas viejo al llenarse, asi que quinientas muestras detras de una
#: anotacion la empujan afuera antes de que el navegador llegue a leerla. Entrar
#: primero y sobrevivir son cosas distintas.
#:
#: Doscientas son muchas para lo que son: en la sesion mas cargada que se midio
#: se emitieron unas pocas decenas. El tope existe igual, porque una cola sin
#: limite es una fuga de memoria con otro nombre; si se llena, se descarta y
#: **se declara aparte**, y la lista completa sigue disponible en
#: `/live/anotaciones`, que no depende de este transporte.
EVENTOS_POR_SUSCRIPTOR = 200

#: TRABAJO PENDIENTE ENTRE EL HILO DE MQTT Y EL BUCLE.
#:
#: La cola de cada suscriptor tiene tope, pero lo que estaba **antes** de ella
#: no lo tenia. Cada señal programaba un `call_soon_threadsafe` por suscriptor:
#: con la parrilla completa ---35.186 señales normalizadas por segundo, medido
#: con `scripts/medir_caudal_por_fuente.py`--- y tres navegadores mirando,
#: son mas de cien mil funciones por segundo entrando a la cola de tareas del
#: bucle. Esa cola es una `deque` sin limite: si el bucle no llega a
#: vaciarla ---y a esa frecuencia no llega--- crece hasta que se acaba la
#: memoria, y ningun contador lo dice.
#:
#: Ahora el hilo de MQTT deposita en este buffer y programa **una sola**
#: funcion mientras haya una pendiente. El trabajo pendiente pasa de ser
#: proporcional al caudal a ser uno.
PENDIENTES_DE_TELEMETRIA = 4000


def recortar_por_instante(cola: deque, tope: int) -> int:
    """Deja la cola en el tope tirando **instantes enteros**. Devuelve cuantas.

    EL TABLERO NO DIBUJA SENALES: DIBUJA MOMENTOS. Para colocar un coche
    necesita `world_position_x` y `world_position_z` **de la misma marca**, y lo
    dice en su propio contador: «una perdida del 50 % en cada una deja un cuarto
    de los pares: el emparejamiento amplifica la perdida al cuadrado».

    `deque(maxlen=N)` descartaba la senal mas vieja sin mirar a que instante
    pertenecia. Con eso, conservar el 6 % de las senales deja alrededor del
    0,4 % de los pares completos: la pantalla no queda incompleta, queda **en
    blanco**, que es lo que se vio en la carrera de seis vehiculos ---el difusor
    recibio 1.416.819 senales y entrego 89.250---.

    Esto no entrega mas senales: con un consumidor mas lento que el productor
    algo hay que tirar. Lo que promete es que lo que sobreviva sea coherente:
    menos momentos, pero completos y dibujables. Un coche a siete cuadros por
    segundo se ve moverse; un coche con el 6 % de sus senales sueltas no.

    SE USA EN LOS DOS SITIOS QUE SE SATURAN ---el puente del difusor y la cola
    de cada suscriptor--- porque recortar bien en uno y mal en el otro deja el
    instante partido igual.

    Las senales de un mismo instante llegan juntas y en orden, de modo que
    comparten el frente de la cola y alcanza con mirar el primero.
    """

    tirados = 0
    while len(cola) > tope:
        marca = cola[0].get("timestamp")
        if cola[-1].get("timestamp") == marca:
            # UN SOLO INSTANTE QUE NO ENTRA. Pasa con una fuente que no declare
            # marca temporal ---y entonces todo es un mismo instante--- o con un
            # instante absurdamente grande. Se lo recorta por la izquierda
            # aunque quede partido: **una cola sin tope es una fuga de memoria
            # con otro nombre**, y ese tope es justamente lo que este recorte
            # esta para sostener. Conservar la coherencia no puede costar la
            # memoria de la maquina.
            while len(cola) > tope:
                cola.popleft()
                tirados += 1
            break
        while cola and cola[0].get("timestamp") == marca:
            cola.popleft()
            tirados += 1
    return tirados

#: Las anotaciones van por su propio camino y con mucho mas margen. Son eventos
#: ---un bloqueo de rueda, un despiste--- de los que hay unos pocos por sesion,
#: y perder uno no es perder resolucion: es perder el hecho. Mezclarlas con la
#: telemetria las dejaria detras de miles de muestras y se descartarian
#: primero, que es exactamente al reves de lo que corresponde.
PENDIENTES_DE_EVENTOS = 1000

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


class Suscriptor:
    """Lo que recibe un navegador conectado al flujo.

    Dos colas y no una. La de datos descarta lo mas viejo al llenarse ---en vivo
    el dato reciente vale mas, y acumular anadiria latencia oculta---; la de
    eventos no puede ser desalojada por datos, porque perder una muestra es
    perder resolucion y perder un aviso es perder el hecho.

    Las dos se leen y se escriben **solo desde el bucle de asyncio**: el hilo de
    MQTT deposita en el puente del difusor y el bucle reparte desde ahi. Por eso
    no hacen falta candados aca.
    """

    def __init__(self) -> None:
        self.eventos: deque = deque(maxlen=EVENTOS_POR_SUSCRIPTOR)
        # Sin `maxlen`: el recorte no puede ser senal por senal. Ver
        # `_descartar_instantes_viejos`.
        self.datos: deque = deque()
        self._hay = asyncio.Event()
        #: Descartes en el ultimo tramo del transporte, separados por tipo.
        self.descartes_datos = 0
        self.descartes_eventos = 0
        #: Lo que entro y lo que salio de esta cola. Con los dos se cierra la
        #: cuenta: recibidos por el difusor -> encolados aca -> entregados al
        #: generador. Sin el segundo no se puede saber si lo que falta se
        #: descarto o se quedo esperando.
        self.encolados = 0
        self.entregados = 0

    def poner_evento(self, cuerpo: dict) -> None:
        if len(self.eventos) == self.eventos.maxlen:
            # Saturacion de eventos: es otra cosa que la saturacion de datos y
            # se cuenta aparte. Aca si se pierde un hecho, no resolucion.
            self.descartes_eventos += 1
        self.eventos.append(cuerpo)
        self._hay.set()

    def poner_dato(self, cuerpo: dict) -> None:
        self.encolados += 1
        self.datos.append(cuerpo)
        if len(self.datos) > COLA_POR_SUSCRIPTOR:
            self._descartar_instantes_viejos()
        self._hay.set()

    def _descartar_instantes_viejos(self) -> None:
        self.descartes_datos += recortar_por_instante(
            self.datos, COLA_POR_SUSCRIPTOR)

    async def obtener(self) -> dict:
        """Devuelve lo proximo a enviar. Los eventos salen antes que los datos."""

        while True:
            if self.eventos:
                self.entregados += 1
                return self.eventos.popleft()
            if self.datos:
                self.entregados += 1
                return self.datos.popleft()
            self._hay.clear()
            # Se vuelve a mirar despues de limpiar: algo pudo entrar entre la
            # comprobacion y el `clear`, y esperar entonces seria dormirse con
            # trabajo pendiente.
            if self.eventos or self.datos:
                continue
            await self._hay.wait()

    def get_nowait(self) -> dict:
        """Lo proximo, sin esperar. Levanta `QueueEmpty` si no hay nada.

        Mantiene el vocabulario de `asyncio.Queue`, que es el que habla el resto
        del modulo y con el que estan escritas las pruebas. Respeta la misma
        prioridad que `obtener`: primero los eventos.
        """

        if self.eventos:
            return self.eventos.popleft()
        if self.datos:
            return self.datos.popleft()
        raise asyncio.QueueEmpty

    def extraer_datos(self, maximo: int) -> list[dict]:
        """Retira hasta ``maximo`` datos sin consumir eventos prioritarios."""

        lote = []
        while self.datos and len(lote) < maximo:
            lote.append(self.datos.popleft())
        self.entregados += len(lote)
        return lote

    def empty(self) -> bool:
        return not self.eventos and not self.datos

    def pendientes(self) -> int:
        return len(self.eventos) + len(self.datos)


class DifusorEnVivo:
    """Recibe del broker y reparte a los suscriptores conectados.

    El cliente MQTT corre en su propio hilo, de modo que la entrega a las colas
    asincronas se hace a traves del bucle de eventos y no directamente.
    """

    def __init__(self) -> None:
        self._bucle: asyncio.AbstractEventLoop | None = None
        self._cliente = None
        self._suscriptores: list["Suscriptor"] = []
        #: Cuantos hay, para poder preguntarlo **sin tomar el candado**.
        #:
        #: La lista es la verdad; este entero la espeja. Se lo lee una vez por
        #: mensaje y a la carga medida eso son decenas de miles de veces por
        #: segundo: tomar un candado para contar costaria mas que el trabajo que
        #: la cuenta permite evitar. Leer y escribir un entero es atomico en este
        #: interprete, y el peor caso de leerlo desactualizado es procesar un
        #: mensaje de mas o de menos en el instante en que alguien se conecta.
        self._cuantos_suscriptores = 0
        #: El puente: lo que el hilo de MQTT dejo y el bucle todavia no repartio.
        # Sin `maxlen`: el recorte es por instante, no senal por senal.
        # Ver `recortar_por_instante`.
        self._pendientes: deque = deque()
        self._pendientes_eventos: deque = deque()
        self._despacho_pedido = False
        #: Que se perdio y donde. Sin esto la saturacion es invisible: se
        #: descartaba en silencio y el estado seguia diciendo cuantos mensajes
        #: entraron, que es otra cosa.
        self.descartes_puente = 0
        self.descartes_eventos = 0
        self.pendientes_maximos_vistos = 0
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
        #: Las sesiones de las que **llego telemetria** por este difusor, de la
        #: mas vieja a la mas nueva.
        #:
        #: Existe por un caso concreto: al detener una captura hay que poner al
        #: dia el catalogo, y refrescar **una** sesion cuesta segundos mientras
        #: que rehacerlo entero cuesta minutos. El identificador no esta en
        #: ningun otro lado ---el sidecar de la captura declara circuito y tipo
        #: de sesion, no el `session_uid`--- y aca pasa cada mensaje de todos
        #: modos, de modo que anotarlo no cuesta nada.
        #:
        #: Acotado a proposito: es una ayuda para refrescar, no un registro.
        self.sesiones_vistas: list[str] = []
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

    def _anotar_sesion(self, session_id) -> None:
        """Deja constancia de que esta sesion emitio, sin repetir ni crecer."""
        if not isinstance(session_id, str) or not session_id:
            return
        if self.sesiones_vistas and self.sesiones_vistas[-1] == session_id:
            return
        if session_id in self.sesiones_vistas:
            self.sesiones_vistas.remove(session_id)
        self.sesiones_vistas.append(session_id)
        del self.sesiones_vistas[:-MAXIMO_SESIONES_ANOTADAS]

    def _procesar_cuerpo(self, cuerpo: dict, recibido_utc: str) -> None:
        """Registra y reparte una señal de un mensaje MQTT simple o agrupado."""

        self._anotar_sesion(cuerpo.get("session_id"))

        # LO CARO SOLO SE HACE SI ALGUIEN MIRA.
        #
        # Medido en banco sobre sesenta mil senales con la forma real que publica
        # el capturador: el anotador se lleva el 51,6 % del manejador y el resumen
        # el 10,1 %. Interpretar el JSON ---34,4 %--- hay que hacerlo igual para
        # saber que trae el mensaje, y las series por senal cuestan 3,9 % y son
        # justamente lo que un suscriptor nuevo necesita para no ver un grafico
        # vacio. De modo que se saltean **esas dos** y no las otras dos.
        #
        # Medido antes de esto: el servidor ocupaba 1,021 nucleos **con cero
        # suscriptores**, y era la pieza propia que mas procesador gastaba.
        #
        # LO QUE ESTO CUESTA, Y HAY QUE DECIRLO. El resumen conserva la sesion
        # entera; si nadie mira durante los primeros minutos, quien se conecte
        # despues no vera esa parte del eje que crece. Es una perdida de historia
        # previa, no de dato: la telemetria se persiste por el consumidor, que es
        # otro proceso y no se entera de esto.
        mira_alguien = self._cuantos_suscriptores > 0

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
            if mira_alguien:
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
        if mira_alguien:
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
        # Se entrega a traves del bucle porque este hilo no es el suyo, pero
        # se programa una funcion por lote y no una por señal y suscriptor.
        self._depositar(self._pendientes, _para_vista(cuerpo), "telemetria")

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
        self._depositar(self._pendientes_eventos, cuerpo, "evento")

    def _depositar(self, buffer: deque, cuerpo: dict, clase: str) -> None:
        """Deja algo para repartir y pide **una** pasada del bucle.

        La condicion de carrera que importa es la de `_despacho_pedido`: se lee
        y se escribe dentro del candado, de modo que dos mensajes simultaneos no
        pueden programar dos pasadas ni dejar el buffer sin nadie que lo vacie.
        """

        with self._candado:
            if not self._suscriptores:
                return
            buffer.append(cuerpo)
            if clase == "evento":
                # Un evento es un hecho, no resolucion: se lo recorta de a uno y
                # se lo cuenta aparte. Perder uno es perder el hecho.
                if len(buffer) > PENDIENTES_DE_EVENTOS:
                    buffer.popleft()
                    self.descartes_eventos += 1
            elif len(buffer) > PENDIENTES_DE_TELEMETRIA:
                # EL PUENTE TAMBIEN TIENE QUE RECORTAR POR INSTANTE. Recortar
                # bien en la cola del suscriptor y mal aca dejaria el instante
                # partido igual, solo que un paso antes. Se cuenta, porque un
                # descarte silencioso es una perdida que nadie puede ver.
                self.descartes_puente += recortar_por_instante(
                    buffer, PENDIENTES_DE_TELEMETRIA)
            hondura = len(self._pendientes) + len(self._pendientes_eventos)
            if hondura > self.pendientes_maximos_vistos:
                self.pendientes_maximos_vistos = hondura
            pedir = not self._despacho_pedido
            self._despacho_pedido = True
        if pedir:
            self._bucle.call_soon_threadsafe(self._despachar)

    def _despachar(self) -> None:
        """Corre en el bucle. Vacia lo pendiente y lo reparte.

        Los eventos van primero: son pocos y no pueden quedar detras de miles de
        muestras. `_despacho_pedido` se baja **antes** de repartir, de modo que
        lo que llegue durante el reparto programa la pasada siguiente en vez de
        quedarse esperando a que alguien la pida.
        """

        with self._candado:
            eventos = list(self._pendientes_eventos)
            datos = list(self._pendientes)
            self._pendientes_eventos.clear()
            self._pendientes.clear()
            colas = list(self._suscriptores)
            self._despacho_pedido = False
        for cuerpo in eventos:
            for sus in colas:
                sus.poner_evento(cuerpo)
        for cuerpo in datos:
            for sus in colas:
                sus.poner_dato(cuerpo)

    # -- suscripcion ------------------------------------------------------- #

    def suscribir(self) -> "Suscriptor | None":
        """Registra un suscriptor. Devuelve None si se alcanzo el tope."""

        with self._candado:
            if len(self._suscriptores) >= MAX_SUSCRIPTORES:
                return None
            cola = Suscriptor()
            self._suscriptores.append(cola)
            self._cuantos_suscriptores = len(self._suscriptores)
            return cola

    def desuscribir(self, cola: "Suscriptor") -> None:
        with self._candado:
            if cola in self._suscriptores:
                self._suscriptores.remove(cola)
            self._cuantos_suscriptores = len(self._suscriptores)

    # -- estado ------------------------------------------------------------ #

    def estado(self) -> dict[str, Any]:
        with self._candado:
            suscriptores = len(self._suscriptores)
            descartes_datos = sum(s.descartes_datos for s in self._suscriptores)
            descartes_eventos = sum(s.descartes_eventos for s in self._suscriptores)
            pendientes = [s.pendientes() for s in self._suscriptores]
            encolados = [s.encolados for s in self._suscriptores]
            entregados = [s.entregados for s in self._suscriptores]
        return {
            "conectado": self.conectado,
            "motivo": self.motivo,
            "topico": MQTT_TOPIC,
            "broker": f"{MQTT_HOST}:{MQTT_PORT}",
            "suscriptores": suscriptores,
            "maximo_suscriptores": MAX_SUSCRIPTORES,
            "mensajes_recibidos": self.recibidos,
            "mensajes_descartados": self.descartados,
            # LO QUE SE PIERDE DE VISTA, SEPARADO DE LO QUE SE PERSISTE.
            # Estas tres cifras son perdidas **de esta vista**: el consumidor
            # que escribe en la base es otro proceso, lee del mismo topico y no
            # descarta nada. Sin declararlas, la saturacion se veia como un
            # grafico con menos puntos y nada mas.
            # LO QUE SE PERDIO, POR TIPO Y POR PUNTO DEL TRANSPORTE.
            # Son dos puntos distintos y dos tipos distintos, y mezclarlos
            # esconde justo lo que hay que ver: un descarte de muestras es
            # perdida de resolucion y uno de anotaciones es perdida de un hecho.
            "descartes_de_vista": {
                "puente_datos": self.descartes_puente,
                "puente_eventos": self.descartes_eventos,
                "suscriptor_datos": descartes_datos,
                "suscriptor_eventos": descartes_eventos,
                "que_significa": ("no llegaron al navegador por saturacion; la "
                                  "persistencia corre por otro proceso y no "
                                  "depende de esto"),
                "recuperacion_de_anotaciones": (
                    "GET /live/anotaciones devuelve la lista completa por "
                    "vehiculo: una anotacion descartada en el transporte no se "
                    "pierde, se vuelve a pedir"),
            },
            "pendientes_por_suscriptor": pendientes,
            # LA CUENTA COMPLETA, POR SUSCRIPTOR.
            # `recibidos` es lo que entro al difusor; `encolados` lo que se le
            # puso a este suscriptor; `entregados` lo que el generador saco para
            # mandarlo. La diferencia entre encolados y entregados es lo que
            # todavia espera o se descarto; sin los tres numeros no se puede
            # decir donde se pierde una señal.
            "encolados_por_suscriptor": encolados,
            "entregados_por_suscriptor": entregados,
            "pendientes_maximos_vistos": self.pendientes_maximos_vistos,
            "tope_pendientes": PENDIENTES_DE_TELEMETRIA,
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


async def flujo_de_eventos(cola: "Suscriptor", intervalo_latido_s: float = 15.0):
    """Genera el flujo de eventos para un suscriptor.

    Emite un latido periodico cuando no hay telemetria: sin el, un intermediario
    podria cerrar una conexion inactiva y el navegador no distinguiria entre
    "no hay datos" y "se corto".
    """

    yield evento_sse(difusor.estado(), "estado")
    while True:
        try:
            dato = await asyncio.wait_for(cola.obtener(), timeout=intervalo_latido_s)
        except asyncio.TimeoutError:
            yield evento_sse({"momento": datetime.now(timezone.utc).isoformat(),
                              "recibidos": difusor.recibidos}, "latido")
            continue
        evento = dato.get("_evento")
        if evento:
            yield evento_sse(dato, evento)
            continue

        # UNA RESPUESTA POR LOTE, NO UNA POR SENAL. Las senales siguen siendo
        # objetos independientes dentro del JSON y conservan su orden. Los
        # eventos no se mezclan: si aparece una anotacion, sale antes del lote
        # siguiente por la prioridad de ``Suscriptor.obtener``.
        lote = [dato]
        lote.extend(cola.extraer_datos(SENALES_POR_EVENTO - 1))
        yield evento_sse(lote, "telemetria")
