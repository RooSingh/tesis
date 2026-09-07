"""Consumidor MQTT del backend.

Este modulo se ejecuta como proceso separado de FastAPI. Su objetivo es:

- conectarse al broker local,
- suscribirse al topic de telemetria del generador,
- recibir mensajes,
- validarlos,
- persistirlos en la base de datos,
- y conservar una pequena memoria de los ultimos mensajes recibidos para
  inspeccion inmediata.
"""

from __future__ import annotations

import json
from collections import deque
import threading

import paho.mqtt.client as mqtt
from pydantic import ValidationError

from backend.config import (
    MQTT_BATCH_SIZE,
    MQTT_FLUSH_INTERVAL_SECONDS,
    MQTT_HOST,
    MQTT_MAX_PENDING_MESSAGES,
    MQTT_PORT,
    MQTT_REPLAY_TOPIC,
    MQTT_SYS_DROPPED_TOPIC,
    MQTT_TOPIC,
    MQTT_CLIENT_ID,
    MQTT_SESION_PERSISTENTE,
    MQTT_QOS_EN_VIVO,
    MQTT_CONFIRMACION_MANUAL,
)
from backend.db import EscritorTelemetria
from backend.models import TelemetryMessage


# Buffer sencillo en memoria para almacenar los ultimos mensajes recibidos.
# No reemplaza la persistencia: complementa la base de datos durante pruebas e
# inspeccion inmediata del flujo recibido.
ULTIMOS_MENSAJES: list[dict] = []
MAX_MENSAJES_EN_MEMORIA = 20
BATCH_SIZE = MQTT_BATCH_SIZE
FLUSH_INTERVAL_SECONDS = MQTT_FLUSH_INTERVAL_SECONDS
MAX_PENDING_MESSAGES = MQTT_MAX_PENDING_MESSAGES


class TelemetryBatchBuffer:
    """Desacopla la recepcion MQTT de la persistencia por lotes en TimescaleDB."""

    def __init__(
        self,
        writer=None,
        batch_size: int = BATCH_SIZE,
        flush_interval: float = FLUSH_INTERVAL_SECONDS,
        max_pending: int = MAX_PENDING_MESSAGES,
        confirmar=None,
    ) -> None:
        self.writer = writer if writer is not None else EscritorTelemetria()
        #: Como se confirma un mensaje al intermediario. Se inyecta, igual que el
        #: escritor, para que el buffer sea verificable sin un cliente real.
        #:
        #: `None` deja el comportamiento anterior: la biblioteca confirma al
        #: volver del callback, antes de escribir. Es lo que se quiere dejar de
        #: hacer, y se mantiene disponible para poder comparar los dos modos.
        self.confirmar = confirmar
        #: Cola de acuses pendientes, en orden de llegada: por cada mensaje del
        #: intermediario, su identificador, su calidad y **cuantas senales
        #: trajo**.
        #:
        #: La unidad de confirmacion es el mensaje y no la senal, y desde que se
        #: agrupa un mensaje trae hasta 560. Los lotes no coinciden con los
        #: mensajes: un lote puede llevar la cola de uno, otro entero y la cabeza
        #: de un tercero. Como la cola de pendientes es FIFO y los lotes se toman
        #: del frente, las senales se escriben en orden de llegada, y basta con
        #: consumir de esta cola la misma cantidad que el lote escribio.
        self.acuses: deque = deque()
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.max_pending = max_pending
        self.pending: list[TelemetryMessage] = []
        self.lock = threading.Lock()
        self.batch_ready = threading.Condition(self.lock)
        self.stop_event = threading.Event()
        self.metrics = {
            "received": 0,
            "persisted": 0,
            "errors": 0,
            "batches": 0,
            "max_pending": 0,
            "decode_errors": 0,
            "processing_errors": 0,
            "disconnects": 0,
            # Filas que `ON CONFLICT DO NOTHING` suprimio por ser repeticiones de
            # una `(replay_run_id, replay_seq)` ya persistida. Es la metrica que
            # distingue un reintento idempotente de una perdida real.
            "duplicates_skipped": 0,
            # Descartes del broker hacia sus clientes. `broker_dropped` es el
            # incremento desde que arranco este consumidor; `broker_dropped_total`
            # es el acumulado que informa Mosquitto desde su propio arranque.
            "broker_dropped": 0,
            "broker_dropped_total": 0,
            # Veces que el hilo de red se freno por alcanzar `max_pending`.
            "backpressure_waits": 0,
        }
        self._broker_dropped_baseline: int | None = None
        self.worker = threading.Thread(target=self._run, daemon=True)
        self.worker.start()

    def enqueue(self, message: TelemetryMessage) -> None:
        with self.batch_ready:
            if self.max_pending and len(self.pending) >= self.max_pending:
                self.metrics["backpressure_waits"] += 1
                self.batch_ready.wait_for(
                    lambda: self.stop_event.is_set() or len(self.pending) < self.max_pending,
                    timeout=self.flush_interval * 4,
                )
            self.pending.append(message)
            self.metrics["received"] += 1
            self.metrics["max_pending"] = max(self.metrics["max_pending"], len(self.pending))
            if len(self.pending) >= self.batch_size:
                self.batch_ready.notify()

    def registrar_mensaje(self, mid: int, qos: int, senales: int) -> None:
        """Anota un mensaje del intermediario a la espera de su acuse.

        Se anota **aunque traiga cero senales validas**: un mensaje cuyas senales
        se rechazaron todas igual hay que confirmarlo, porque el intermediario lo
        va a reenviar indefinidamente si no. Con cero senales se confirma en el
        acto, ya que ningun lote lo va a cubrir nunca.
        """

        if self.confirmar is None:
            return
        if senales <= 0:
            self.confirmar(mid, qos)
            return
        with self.lock:
            self.acuses.append([mid, qos, senales])

    def _confirmar_cubiertos(self, senales_escritas: int) -> int:
        """Confirma los mensajes que el lote escrito cubrio por completo.

        Se consume por **la cantidad de senales del lote** y no por las filas
        persistidas: desde que la insercion usa `ON CONFLICT DO NOTHING`, un lote
        de repeticiones persiste cero filas habiendo consumido mensajes reales de
        la cola. Medir por filas dejaria esos mensajes sin confirmar para siempre.
        """

        if self.confirmar is None or senales_escritas <= 0:
            return 0
        a_confirmar = []
        with self.lock:
            restantes = senales_escritas
            while restantes > 0 and self.acuses:
                entrada = self.acuses[0]
                if entrada[2] > restantes:
                    entrada[2] -= restantes
                    restantes = 0
                else:
                    restantes -= entrada[2]
                    a_confirmar.append((entrada[0], entrada[1]))
                    self.acuses.popleft()
        # Se confirma **fuera del cerrojo**: `ack` escribe en el socket del
        # cliente y retener el cerrojo del buffer mientras se hace bloquearia la
        # recepcion.
        for mid, qos in a_confirmar:
            self.confirmar(mid, qos)
        return len(a_confirmar)

    def record_decode_error(self) -> None:
        with self.lock:
            self.metrics["decode_errors"] += 1

    def record_processing_error(self) -> None:
        with self.lock:
            self.metrics["processing_errors"] += 1

    def record_disconnect(self) -> None:
        with self.lock:
            self.metrics["disconnects"] += 1

    def record_broker_dropped(self, total: int) -> None:
        """Registra el acumulado de descartes que publica Mosquitto en `$SYS`.

        La primera lectura fija la linea base, porque el contador del broker no
        se reinicia entre corridas. Un reinicio del broker haria retroceder el
        acumulado; en ese caso el incremento se acota a cero en vez de informar un
        valor negativo, y la linea base se vuelve a fijar.
        """
        with self.lock:
            if self._broker_dropped_baseline is None or total < self._broker_dropped_baseline:
                self._broker_dropped_baseline = total
            self.metrics["broker_dropped_total"] = total
            self.metrics["broker_dropped"] = total - self._broker_dropped_baseline

    def _take_batch(self) -> list[TelemetryMessage]:
        with self.lock:
            batch = self.pending[:self.batch_size]
            del self.pending[:len(batch)]
            if batch:
                self.batch_ready.notify_all()
        return batch

    def flush(self) -> int:
        batch = self._take_batch()
        if not batch:
            return 0
        try:
            persisted = self.writer(batch)
        except Exception:
            with self.lock:
                self.pending = batch + self.pending
                self.metrics["errors"] += 1
            return 0
        with self.lock:
            self.metrics["persisted"] += persisted
            self.metrics["duplicates_skipped"] += max(0, len(batch) - persisted)
            self.metrics["batches"] += 1
        # **Recien aca se confirma.** Es el cambio entero: antes la biblioteca
        # confirmaba al volver del callback, de modo que un mensaje quedaba
        # confirmado y sin escribir mientras esperaba en la cola, y el
        # intermediario no lo iba a reenviar nunca.
        #
        # Si `self.writer` fallo, esta linea no se alcanza: el lote se reencolo y
        # sus mensajes siguen sin confirmar, que es lo que hace que el
        # intermediario los reenvie.
        confirmados = self._confirmar_cubiertos(len(batch))
        if confirmados:
            with self.lock:
                self.metrics["confirmados"] = (
                    self.metrics.get("confirmados", 0) + confirmados)
        return persisted

    def _drenar_hasta_sin_avance(self) -> None:
        """Vacia la cola por completo mientras siga achicandose.

        Se drena hasta dejar la cola vacia, incluido el ultimo lote incompleto.
        Esperar a que se complete un lote dejaria los mensajes finales de una
        rafaga sin escribir hasta el cierre del proceso: una verificacion por
        bloque los contaria como faltantes aunque estuvieran intactos en memoria.

        El avance se mide por el tamano de `self.pending`, no por las filas
        escritas, por dos motivos:

        1. desde que la insercion usa `ON CONFLICT DO NOTHING`, un lote formado
           solo por repeticiones persiste cero filas aunque haya consumido
           mensajes reales de la cola; medir por filas dejaria esos mensajes
           atrapados al cerrar el consumidor;
        2. si el escritor falla, `flush` reencola el lote completo y la cola no se
           achica. Detenerse ante la falta de avance evita el bucle infinito que
           prohibe el protocolo para operaciones persistentes.
        """
        while True:
            with self.lock:
                antes = len(self.pending)
            if antes == 0:
                return
            self.flush()
            with self.lock:
                if len(self.pending) >= antes:
                    return

    def _run(self) -> None:
        while not self.stop_event.is_set():
            with self.batch_ready:
                # Despierta ante un lote completo o, como maximo, tras
                # `flush_interval`. Ese vencimiento es el que garantiza que una
                # cola parcial no espere indefinidamente a completarse.
                self.batch_ready.wait_for(
                    lambda: self.stop_event.is_set() or len(self.pending) >= self.batch_size,
                    timeout=self.flush_interval,
                )
            if self.stop_event.is_set():
                return
            self._drenar_hasta_sin_avance()

    def close(self) -> None:
        self.stop_event.set()
        with self.batch_ready:
            self.batch_ready.notify_all()
        self.worker.join(timeout=self.flush_interval * 2)
        self._drenar_hasta_sin_avance()
        if hasattr(self.writer, "cerrar"):
            self.writer.cerrar()

    def snapshot(self) -> dict[str, int]:
        with self.lock:
            return {**self.metrics, "pending": len(self.pending)}


def _guardar_mensaje_en_memoria(mensaje: dict) -> None:
    """Guarda un mensaje recibido en un buffer corto en memoria."""

    ULTIMOS_MENSAJES.append(mensaje)

    if len(ULTIMOS_MENSAJES) > MAX_MENSAJES_EN_MEMORIA:
        del ULTIMOS_MENSAJES[0]


# Tope de mensajes de error impresos por categoria. Sin este limite, una corrida
# larga con payloads invalidos escribiria millones de lineas desde el hilo de red
# de Paho, que es justamente el hilo que no puede bloquearse: la propia impresion
# del diagnostico se convertiria en causa de descarte del broker.
MAX_ERRORES_IMPRESOS = 20
_errores_impresos: dict[str, int] = {}


def _informar_error_acotado(categoria: str, error: object) -> None:
    """Imprime las primeras ocurrencias de un error y luego silencia la categoria.

    Los contadores de metricas siguen registrando todas las ocurrencias; lo que
    se acota es solo la salida por consola.
    """
    vistos = _errores_impresos.get(categoria, 0) + 1
    _errores_impresos[categoria] = vistos
    if vistos <= MAX_ERRORES_IMPRESOS:
        print(f"[MQTT] {categoria}: {error}")
    elif vistos == MAX_ERRORES_IMPRESOS + 1:
        print(f"[MQTT] {categoria}: se omiten las siguientes ocurrencias; consultar metricas.")


def on_connect(client: mqtt.Client, userdata, flags, reason_code, properties) -> None:
    """Callback ejecutado al establecer conexion con el broker."""

    print(f"[MQTT] Conectado al broker con codigo={reason_code}")
    # El topico en vivo se suscribe con la calidad configurada y no con cero.
    # La entrega al suscriptor se rige por **el minimo** entre la calidad de la
    # publicacion y la de la suscripcion: publicar con garantia y suscribirse en
    # cero deja el tramo final sin garantia, y con el la sesion persistente sin
    # efecto para ese topico.
    #
    # Las estadisticas del intermediario siguen en cero a proposito: son
    # informativas, se publican periodicamente y perder una no pierde telemetria.
    client.subscribe([(MQTT_TOPIC, MQTT_QOS_EN_VIVO),
                      (MQTT_REPLAY_TOPIC, 1),
                      (MQTT_SYS_DROPPED_TOPIC, 0)])
    print(f"[MQTT] Suscripto a topics: {MQTT_TOPIC}, {MQTT_REPLAY_TOPIC}, {MQTT_SYS_DROPPED_TOPIC}")


def on_sys_dropped(client: mqtt.Client, userdata: TelemetryBatchBuffer, msg: mqtt.MQTTMessage) -> None:
    """Registra los descartes que Mosquitto informa en su topico de estadisticas.

    Este es el unico observador del tramo broker -> consumidor. El proyecto
    demostro perder 8.985 mensajes con todos los contadores propios en cero: sin
    esta lectura, la condicion de aceptacion `broker_dropped == 0` no puede
    verificarse.

    Mosquitto publica este valor cada `sys_interval` segundos, diez por defecto,
    de modo que la ultima lectura de una corrida debe tomarse despues de esa
    ventana y no inmediatamente al terminar de publicar.
    """
    try:
        userdata.record_broker_dropped(int(float(msg.payload.decode("utf-8").strip())))
    except (UnicodeDecodeError, ValueError, AttributeError) as error:
        _informar_error_acotado("Estadistica $SYS ilegible", error)


def on_message(client: mqtt.Client, userdata: TelemetryBatchBuffer, msg: mqtt.MQTTMessage) -> None:
    """Callback ejecutado cuando llega un mensaje desde MQTT."""

    try:
        payload = msg.payload.decode("utf-8")
        contenido = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        userdata.record_decode_error()
        _informar_error_acotado("Mensaje descartado por decodificacion o validacion", error)
        return
    except Exception as error:
        userdata.record_processing_error()
        _informar_error_acotado("Error inesperado al procesar mensaje", error)
        return

    # **Un mensaje suelto y un lote se distinguen por la forma, no por una
    # marca.** Si lo que llega es una lista, son varias senales; si es un
    # objeto, es una.
    #
    # Se aceptan las dos porque hay tres publicadores usando este contrato ---el
    # capturador, la reproduccion del bus y la carga de la fuente deportiva--- y
    # cambiarlos a los tres a la vez volveria imposible ubicar un fallo. Los que
    # no agrupen siguen andando sin tocarlos.
    #
    # Por que existe el lote: cada mensaje con garantia de entrega paga un ida y
    # vuelta con el intermediario, y **el cliente acepta unos 6.578 por segundo
    # sin importar que lleven adentro**. Con una senal por mensaje, la parrilla
    # completa descartaba el 96 % en la cola de salida; con 560 por lote, el
    # caudal util pasa a 3,19 millones de senales por segundo y no se descarta
    # ninguna.
    crudos = contenido if isinstance(contenido, list) else [contenido]

    aceptadas = 0
    for mensaje_dict in crudos:
        try:
            mensaje = TelemetryMessage.model_validate(mensaje_dict)
        except ValidationError as error:
            # **Se cuenta y se sigue con el resto del lote.** Una senal invalida
            # entre quinientas sesenta no puede descartar las otras quinientas
            # cincuenta y nueve, que es lo que pasaria si el error cortara aca.
            userdata.record_decode_error()
            _informar_error_acotado(
                "Mensaje descartado por decodificacion o validacion", error)
            continue
        except Exception as error:
            userdata.record_processing_error()
            _informar_error_acotado("Error inesperado al procesar mensaje", error)
            continue

        try:
            # Se reutiliza el diccionario ya parseado en lugar de `mensaje.model_dump()`.
            # Serializar el modelo completo costaba una vuelta extra por cada mensaje,
            # en el hilo de red, para conservar solo los ultimos veinte: sobre 6,2
            # millones de mensajes ese trabajo se descartaba casi por completo.
            _guardar_mensaje_en_memoria(mensaje_dict)
            userdata.enqueue(mensaje)
            aceptadas += 1
        except Exception as error:
            userdata.record_processing_error()
            _informar_error_acotado("Error al encolar mensaje", error)

    # **Se anota el mensaje del intermediario recien aca**, con la cuenta de
    # senales que efectivamente entraron a la cola. El acuse sale despues, cuando
    # un lote las haya escrito.
    #
    # Se anota siempre, incluso con cero aceptadas: un mensaje cuyas senales se
    # rechazaron todas igual hay que confirmarlo, o el intermediario lo reenvia
    # sin fin. Ese caso se confirma en el acto, porque ningun lote lo va a
    # cubrir.
    userdata.registrar_mensaje(getattr(msg, "mid", 0),
                               getattr(msg, "qos", 0), aceptadas)


def on_disconnect(client: mqtt.Client, userdata: TelemetryBatchBuffer, disconnect_flags, reason_code, properties) -> None:
    """Registra cortes MQTT, incluidos los ocurridos durante una prueba controlada."""

    userdata.record_disconnect()
    print(f"[MQTT] Desconectado del broker con codigo={reason_code}")


def crear_cliente_mqtt() -> mqtt.Client:
    """Crea y configura el cliente MQTT del backend."""

    # La identidad es fija y la sesion se conserva. Las dos cosas van juntas y
    # ninguna sirve sola: el intermediario guarda lo que llega mientras el
    # consumidor no esta, y solo se lo puede entregar a un cliente que reconozca
    # como el mismo.
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                         client_id=MQTT_CLIENT_ID,
                         clean_session=not MQTT_SESION_PERSISTENTE)
    if MQTT_CONFIRMACION_MANUAL:
        # A partir de aca la biblioteca **no confirma sola**: el acuse lo emite
        # el buffer despues de haber escrito en la base. Es lo que hace que un
        # mensaje confirmado sea un mensaje persistido.
        client.manual_ack_set(True)
        client.user_data_set(TelemetryBatchBuffer(
            confirmar=lambda mid, qos: client.ack(mid, qos)))
    else:
        client.user_data_set(TelemetryBatchBuffer())
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect
    # Las estadisticas del broker se enrutan a su propio callback para que
    # `on_message` no intente validarlas como telemetria y las cuente como
    # `decode_errors`.
    client.message_callback_add(MQTT_SYS_DROPPED_TOPIC, on_sys_dropped)
    return client


def iniciar_consumidor_mqtt() -> mqtt.Client:
    """Conecta y deja listo el consumidor MQTT del backend.

    Esta funcion no bloquea indefinidamente el hilo principal porque Paho usa un
    loop de red en segundo plano. Quien la invoque debe mantener vivo su propio
    proceso; FastAPI no inicia este consumidor automaticamente.
    """

    client = crear_cliente_mqtt()
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.loop_start()
    return client


def detener_consumidor_mqtt(client: mqtt.Client) -> dict[str, int]:
    """Detiene red y vacia el buffer antes de finalizar un proceso consumidor."""
    client.loop_stop()
    client.disconnect()
    buffer: TelemetryBatchBuffer = client.user_data_get()
    buffer.close()
    return buffer.snapshot()
