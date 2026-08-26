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
    ) -> None:
        self.writer = writer if writer is not None else EscritorTelemetria()
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
        return persisted

    def _drenar_hasta_sin_avance(self, solo_lotes_completos: bool) -> None:
        """Vacia la cola mientras siga achicandose.

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
            if antes == 0 or (solo_lotes_completos and antes < self.batch_size):
                return
            self.flush()
            with self.lock:
                if len(self.pending) >= antes:
                    return

    def _run(self) -> None:
        while not self.stop_event.is_set():
            with self.batch_ready:
                self.batch_ready.wait_for(
                    lambda: self.stop_event.is_set() or len(self.pending) >= self.batch_size,
                    timeout=self.flush_interval,
                )
            if self.stop_event.is_set():
                return
            self._drenar_hasta_sin_avance(solo_lotes_completos=True)

    def close(self) -> None:
        self.stop_event.set()
        with self.batch_ready:
            self.batch_ready.notify_all()
        self.worker.join(timeout=self.flush_interval * 2)
        self._drenar_hasta_sin_avance(solo_lotes_completos=False)
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
    client.subscribe([(MQTT_TOPIC, 0), (MQTT_REPLAY_TOPIC, 1), (MQTT_SYS_DROPPED_TOPIC, 0)])
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
        mensaje_dict = json.loads(payload)
        mensaje = TelemetryMessage.model_validate(mensaje_dict)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
        userdata.record_decode_error()
        _informar_error_acotado("Mensaje descartado por decodificacion o validacion", error)
        return
    except Exception as error:
        userdata.record_processing_error()
        _informar_error_acotado("Error inesperado al procesar mensaje", error)
        return

    try:
        # Se reutiliza el diccionario ya parseado en lugar de `mensaje.model_dump()`.
        # Serializar el modelo completo costaba una vuelta extra por cada mensaje,
        # en el hilo de red, para conservar solo los ultimos veinte: sobre 6,2
        # millones de mensajes ese trabajo se descartaba casi por completo.
        _guardar_mensaje_en_memoria(mensaje_dict)
        userdata.enqueue(mensaje)
    except Exception as error:
        userdata.record_processing_error()
        _informar_error_acotado("Error al encolar mensaje", error)


def on_disconnect(client: mqtt.Client, userdata: TelemetryBatchBuffer, disconnect_flags, reason_code, properties) -> None:
    """Registra cortes MQTT, incluidos los ocurridos durante una prueba controlada."""

    userdata.record_disconnect()
    print(f"[MQTT] Desconectado del broker con codigo={reason_code}")


def crear_cliente_mqtt() -> mqtt.Client:
    """Crea y configura el cliente MQTT del backend."""

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
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
