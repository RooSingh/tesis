"""Pruebas locales del buffer MQTT sin broker ni TimescaleDB."""

from __future__ import annotations

import unittest
from time import monotonic, sleep

from backend.models import TelemetryMessage
from backend.mqtt_consumer import TelemetryBatchBuffer


# Estado inicial de todas las metricas del buffer. Las pruebas declaran solo lo
# que cambia respecto de esta linea base, de modo que agregar una metrica nueva
# no obliga a reescribir cada asercion, pero una metrica que cambie sin que la
# prueba lo declare sigue haciendo fallar la comparacion.
METRICAS_BASE = {
    "received": 0,
    "persisted": 0,
    "errors": 0,
    "batches": 0,
    "max_pending": 0,
    "decode_errors": 0,
    "processing_errors": 0,
    "disconnects": 0,
    "duplicates_skipped": 0,
    "broker_dropped": 0,
    "broker_dropped_total": 0,
    "backpressure_waits": 0,
    "pending": 0,
}


def esperado(**cambios) -> dict:
    return {**METRICAS_BASE, **cambios}


def message(index: int) -> TelemetryMessage:
    return TelemetryMessage.model_validate({
        "timestamp": f"2025-07-06T15:18:{index:02d}+00:00",
        "vehicle_id": "test:vehicle",
        "driver_id": "test:driver",
        "session_id": "test:session",
        "lap_id": None,
        "source_type": "test",
        "signal_name": "speed",
        "value": index,
        "unit": "km/h",
        "quality_flag": "test",
        "metadata": {},
    })


class TelemetryBatchBufferTests(unittest.TestCase):
    def test_flushes_full_batch_without_waiting_for_interval(self) -> None:
        written = []
        buffer = TelemetryBatchBuffer(
            lambda batch: written.append(len(batch)) or len(batch),
            batch_size=2,
            flush_interval=60,
        )
        try:
            buffer.enqueue(message(1))
            buffer.enqueue(message(2))
            deadline = monotonic() + 1
            while buffer.snapshot()["persisted"] != 2 and monotonic() < deadline:
                sleep(0.01)
            self.assertEqual(written, [2])
            self.assertEqual(
                buffer.snapshot(),
                esperado(received=2, persisted=2, batches=1, max_pending=2),
            )
        finally:
            buffer.close()

    def test_flushes_in_configured_batches(self) -> None:
        written = []
        buffer = TelemetryBatchBuffer(lambda batch: written.append(len(batch)) or len(batch), batch_size=2, flush_interval=60)
        try:
            buffer.stop_event.set()
            with buffer.batch_ready:
                buffer.batch_ready.notify_all()
            buffer.worker.join()
            for index in range(5):
                buffer.enqueue(message(index))
            self.assertEqual(buffer.flush(), 2)
            self.assertEqual(buffer.flush(), 2)
            self.assertEqual(buffer.flush(), 1)
            self.assertEqual(written, [2, 2, 1])
            self.assertEqual(
                buffer.snapshot(),
                esperado(received=5, persisted=5, batches=3, max_pending=5),
            )
        finally:
            buffer.close()

    def test_requeues_failed_batch(self) -> None:
        buffer = TelemetryBatchBuffer(lambda batch: (_ for _ in ()).throw(RuntimeError("db unavailable")), batch_size=2, flush_interval=60)
        try:
            buffer.enqueue(message(1))
            self.assertEqual(buffer.flush(), 0)
            self.assertEqual(
                buffer.snapshot(),
                esperado(received=1, errors=1, max_pending=1, pending=1),
            )
        finally:
            buffer.writer = lambda batch: len(batch)
            buffer.close()

    def test_el_worker_escribe_un_lote_incompleto_dentro_del_intervalo(self) -> None:
        """Regresion detectada en la validacion D2 contra servicios reales.

        El worker solo drenaba cuando la cola alcanzaba `batch_size`, de modo que
        los mensajes finales de una rafaga quedaban en memoria hasta el cierre del
        proceso. La verificacion por bloque los conto como faltantes aunque
        estuvieran intactos: `received=40740`, `persisted=40000`, `pending=740`.

        El vencimiento de `flush_interval` debe bastar para escribir el resto sin
        que llegue ningun mensaje nuevo y sin cerrar el consumidor.
        """
        escritos = []
        buffer = TelemetryBatchBuffer(
            lambda batch: escritos.append(len(batch)) or len(batch),
            batch_size=1000,
            flush_interval=0.05,
        )
        try:
            for index in range(740):
                buffer.enqueue(message(index % 60))

            deadline = monotonic() + 3
            while buffer.snapshot()["pending"] != 0 and monotonic() < deadline:
                sleep(0.01)

            self.assertEqual(buffer.snapshot()["pending"], 0)
            self.assertEqual(buffer.snapshot()["persisted"], 740)
            self.assertEqual(sum(escritos), 740)
        finally:
            buffer.close()

    def test_cuenta_duplicados_suprimidos_por_la_base(self) -> None:
        """Un lote parcialmente duplicado no debe leerse como perdida.

        Con `ON CONFLICT DO NOTHING`, el escritor devuelve filas realmente
        insertadas. La diferencia con el tamano del lote son repeticiones
        suprimidas, que es el resultado correcto al reintentar un bloque.
        """
        buffer = TelemetryBatchBuffer(lambda batch: len(batch) - 1, batch_size=3, flush_interval=60)
        try:
            buffer.stop_event.set()
            with buffer.batch_ready:
                buffer.batch_ready.notify_all()
            buffer.worker.join()
            for index in range(3):
                buffer.enqueue(message(index))

            self.assertEqual(buffer.flush(), 2)
            self.assertEqual(
                buffer.snapshot(),
                esperado(received=3, persisted=2, batches=1, max_pending=3, duplicates_skipped=1),
            )
        finally:
            buffer.writer = lambda batch: len(batch)
            buffer.close()

    def test_close_vacia_la_cola_aunque_no_se_inserte_ninguna_fila(self) -> None:
        """Regresion: el drenaje debe medirse por mensajes tomados, no por filas.

        Si un lote entero resulta duplicado, el escritor devuelve cero. Un bucle
        de cierre que dependa de las filas escritas se detendria creyendo que ya
        no queda nada, dejando mensajes atrapados en memoria y `pending` distinto
        de cero al terminar la corrida.
        """
        buffer = TelemetryBatchBuffer(lambda batch: 0, batch_size=2, flush_interval=0.05)
        for index in range(5):
            buffer.enqueue(message(index))

        buffer.close()

        self.assertEqual(buffer.snapshot()["pending"], 0)
        self.assertEqual(buffer.snapshot()["duplicates_skipped"], 5)

    def test_close_no_gira_en_bucle_si_el_escritor_siempre_falla(self) -> None:
        """El cierre debe terminar aunque la base este caida.

        `flush` reencola el lote fallido, de modo que la cola no se achica. Sin
        una condicion de progreso, el cierre giraria indefinidamente, que es lo
        que el protocolo prohibe para operaciones persistentes.
        """
        buffer = TelemetryBatchBuffer(
            lambda batch: (_ for _ in ()).throw(RuntimeError("db unavailable")),
            batch_size=2,
            flush_interval=0.05,
        )
        for index in range(4):
            buffer.enqueue(message(index))

        inicio = monotonic()
        buffer.close()
        transcurrido = monotonic() - inicio

        self.assertLess(transcurrido, 5)
        self.assertEqual(buffer.snapshot()["pending"], 4)
        self.assertGreaterEqual(buffer.snapshot()["errors"], 1)

    def test_broker_dropped_informa_incremento_desde_la_linea_base(self) -> None:
        """El contador de Mosquitto es acumulativo desde su propio arranque.

        Lo relevante para una corrida es el incremento, no el absoluto: el
        consumidor puede iniciarse con un broker que ya venia descartando.
        """
        buffer = TelemetryBatchBuffer(lambda batch: len(batch), batch_size=10, flush_interval=60)
        try:
            buffer.record_broker_dropped(120)
            self.assertEqual(buffer.snapshot()["broker_dropped"], 0)
            self.assertEqual(buffer.snapshot()["broker_dropped_total"], 120)

            buffer.record_broker_dropped(137)
            self.assertEqual(buffer.snapshot()["broker_dropped"], 17)

            # Un reinicio del broker hace retroceder el acumulado; se refija la
            # linea base en vez de informar un incremento negativo.
            buffer.record_broker_dropped(4)
            self.assertEqual(buffer.snapshot()["broker_dropped"], 0)
            self.assertEqual(buffer.snapshot()["broker_dropped_total"], 4)
        finally:
            buffer.close()


if __name__ == "__main__":
    unittest.main()
