"""Pruebas del publicador de replay OpenF1 sin broker ni base de datos.

Cubren las dos rutas del script: la clasica en memoria, apta solo para ventanas
cortas, y la incremental por bloques que habilita la carrera completa.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("replay_openf1", ROOT / "scripts" / "replay_openf1.py")
assert SPEC is not None and SPEC.loader is not None
replay_openf1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay_openf1)


class FakePublishResult:
    def __init__(self, index: int, waited: list[int], rc: int = 0) -> None:
        self.index = index
        self.waited = waited
        self.rc = rc

    def wait_for_publish(self) -> None:
        self.waited.append(self.index)


class FakeMqttClient:
    def __init__(self, publish_rc: int = 0) -> None:
        self.inflight_limit = None
        self.published = []
        self.waited = []
        self.connected = False
        self.loop_started = False
        self.disconnected = False
        self.publish_rc = publish_rc

    def max_inflight_messages_set(self, limit: int) -> None:
        self.inflight_limit = limit

    def connect(self, host: str, port: int, keepalive: int) -> None:
        self.connected = True

    def loop_start(self) -> None:
        self.loop_started = True

    def publish(self, topic: str, payload: str, qos: int) -> FakePublishResult:
        self.published.append((topic, json.loads(payload), qos))
        return FakePublishResult(len(self.published), self.waited, self.publish_rc)

    def loop_stop(self) -> None:
        self.loop_started = False

    def disconnect(self) -> None:
        self.disconnected = True


def muestra_car_data(segundo: int) -> dict:
    return {
        "date": f"2025-07-06T14:00:{segundo:02d}.000000+00:00",
        "session_key": 9947,
        "meeting_key": 1277,
        "driver_number": 1,
        "speed": 250,
        "throttle": 90,
        "brake": 0,
        "rpm": 11000,
        "n_gear": 7,
        "drs": 12,
    }


def escribir_stream(directorio: Path, muestras: int = 3) -> Path:
    """Genera un stream con `muestras` registros de 6 mensajes cada uno."""
    ruta = directorio / "stream.jsonl"
    with ruta.open("w", encoding="utf-8") as archivo:
        for indice in range(muestras):
            registro = {
                "seq": indice * 6,
                "n": 6,
                "endpoint": "car_data",
                "source_url": "https://api.openf1.org/v1/car_data",
                "raw_payload_path": "datasets/prueba.json",
                "sample": muestra_car_data(indice),
            }
            archivo.write(json.dumps(registro, sort_keys=True) + "\n")
    return ruta


class ReplayOpenF1Tests(unittest.TestCase):
    def test_publish_limits_confirmations_in_flight(self) -> None:
        client = FakeMqttClient()
        messages = [
            {"timestamp": f"2025-07-06T14:05:0{index}+00:00", "metadata": {"extra": {}}}
            for index in range(3)
        ]

        metrics = replay_openf1.publish(
            messages,
            speed=1,
            max_delay=0,
            max_inflight_messages=2,
            client_factory=lambda _: client,
        )

        self.assertEqual(client.inflight_limit, 2)
        self.assertEqual(len(client.published), 3)
        self.assertEqual(client.waited, [1, 2, 3])
        self.assertEqual(metrics, {"attempted": 3, "acknowledged": 3, "publish_rc_errors": 0})
        self.assertTrue(client.connected)
        self.assertTrue(client.disconnected)
        self.assertFalse(client.loop_started)

    def test_publish_stops_on_mqtt_error_code(self) -> None:
        client = FakeMqttClient(publish_rc=1)
        messages = [{"timestamp": "2025-07-06T14:05:00+00:00", "metadata": {"extra": {}}}]

        with self.assertRaisesRegex(RuntimeError, "rc=1"):
            replay_openf1.publish(
                messages,
                speed=1,
                max_delay=0,
                max_inflight_messages=1,
                client_factory=lambda _: client,
            )

        self.assertEqual(len(client.published), 1)
        self.assertEqual(client.waited, [])
        self.assertTrue(client.disconnected)


class IterStreamMessagesTests(unittest.TestCase):
    def test_numera_los_mensajes_y_marca_la_corrida(self) -> None:
        with tempfile.TemporaryDirectory() as directorio:
            ruta = escribir_stream(Path(directorio), muestras=2)

            resultados = list(replay_openf1.iter_stream_messages(ruta, "prueba_001"))

        self.assertEqual([seq for seq, _ in resultados], list(range(12)))
        for seq, mensaje in resultados:
            self.assertEqual(mensaje["metadata"]["extra"]["replay_run_id"], "prueba_001")
            self.assertEqual(mensaje["metadata"]["extra"]["replay_seq"], seq)

    def test_reanuda_en_el_medio_de_una_muestra(self) -> None:
        """Reanudar no puede exigir que el corte caiga en un limite de muestra.

        El bloque se corta por cantidad de mensajes, de modo que el checkpoint
        puede apuntar al interior de una muestra ya expandida parcialmente.
        """
        with tempfile.TemporaryDirectory() as directorio:
            ruta = escribir_stream(Path(directorio), muestras=3)

            resultados = list(replay_openf1.iter_stream_messages(ruta, "prueba_001", desde_seq=8))

        self.assertEqual([seq for seq, _ in resultados], list(range(8, 18)))

    def test_no_expande_las_muestras_previas_al_corte(self) -> None:
        with tempfile.TemporaryDirectory() as directorio:
            ruta = escribir_stream(Path(directorio), muestras=3)

            resultados = list(replay_openf1.iter_stream_messages(ruta, "prueba_001", desde_seq=12))

        self.assertEqual([seq for seq, _ in resultados], list(range(12, 18)))

    def test_detiene_la_corrida_si_el_stream_declara_un_conteo_incorrecto(self) -> None:
        """Un `n` erroneo corre toda la numeracion posterior.

        Continuar significaria persistir filas con una clave de idempotencia que
        no corresponde al mensaje, que es peor que fallar.
        """
        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio) / "stream.jsonl"
            registro = {
                "seq": 0,
                "n": 99,
                "endpoint": "car_data",
                "source_url": "u",
                "raw_payload_path": "p",
                "sample": muestra_car_data(0),
            }
            ruta.write_text(json.dumps(registro) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "regenerar el stream"):
                list(replay_openf1.iter_stream_messages(ruta, "prueba_001"))


class CheckpointTests(unittest.TestCase):
    def test_sin_archivo_previo_arranca_desde_cero(self) -> None:
        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio) / "no_existe.json"

            self.assertEqual(replay_openf1.leer_checkpoint(ruta, "prueba_001", "stream.jsonl"), 0)

    def test_recupera_el_avance_confirmado(self) -> None:
        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio) / "checkpoint.json"
            replay_openf1.escribir_checkpoint(ruta, "prueba_001", "stream.jsonl", 5000, 2)

            self.assertEqual(replay_openf1.leer_checkpoint(ruta, "prueba_001", "stream.jsonl"), 5000)

    def test_rechaza_un_checkpoint_de_otra_corrida(self) -> None:
        """Reanudar con el checkpoint equivocado produciria huecos silenciosos."""
        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio) / "checkpoint.json"
            replay_openf1.escribir_checkpoint(ruta, "otra_corrida", "stream.jsonl", 5000, 2)

            with self.assertRaisesRegex(RuntimeError, "replay_run_id"):
                replay_openf1.leer_checkpoint(ruta, "prueba_001", "stream.jsonl")

    def test_rechaza_un_checkpoint_de_otro_stream(self) -> None:
        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio) / "checkpoint.json"
            replay_openf1.escribir_checkpoint(ruta, "prueba_001", "otro_stream.jsonl", 5000, 2)

            with self.assertRaisesRegex(RuntimeError, "stream"):
                replay_openf1.leer_checkpoint(ruta, "prueba_001", "stream.jsonl")


class PublishStreamTests(unittest.TestCase):
    def _publicar(self, directorio: str, **overrides):
        ruta = escribir_stream(Path(directorio), muestras=3)
        checkpoint = Path(directorio) / "checkpoint.json"
        client = FakeMqttClient()
        parametros = {
            "stream_path": ruta,
            "replay_run_id": "prueba_001",
            "speed": 1,
            "max_delay": 0,
            "max_inflight_messages": 1,
            "block_size": 6,
            "checkpoint_path": checkpoint,
            "client_factory": lambda _: client,
            "dormir": lambda _segundos: None,
        }
        parametros.update(overrides)
        return client, checkpoint, replay_openf1.publish_stream(**parametros)

    def test_publica_todo_el_stream_en_bloques(self) -> None:
        with tempfile.TemporaryDirectory() as directorio:
            client, checkpoint, metrics = self._publicar(directorio)

        self.assertEqual(len(client.published), 18)
        self.assertEqual(metrics["attempted"], 18)
        self.assertEqual(metrics["acknowledged"], 18)
        self.assertEqual(metrics["publish_rc_errors"], 0)
        self.assertEqual(metrics["blocks_completed"], 3)
        self.assertEqual(metrics["first_seq"], 0)
        self.assertEqual(metrics["last_seq"], 17)
        self.assertTrue(client.disconnected)

    def test_el_checkpoint_registra_el_siguiente_seq(self) -> None:
        with tempfile.TemporaryDirectory() as directorio:
            _, checkpoint, _ = self._publicar(directorio)
            datos = json.loads(checkpoint.read_text(encoding="utf-8"))

        self.assertEqual(datos["next_seq"], 18)
        self.assertEqual(datos["blocks_completed"], 3)
        self.assertEqual(datos["replay_run_id"], "prueba_001")

    def test_reconcilia_cada_bloque_contra_la_base(self) -> None:
        consultas = []

        def reconciliar(run_id, desde, hasta):
            consultas.append((run_id, desde, hasta))
            return {"filas": hasta - desde + 1, "unicos": hasta - desde + 1}

        with tempfile.TemporaryDirectory() as directorio:
            _, _, metrics = self._publicar(directorio, reconciliar=reconciliar)

        self.assertEqual(consultas, [
            ("prueba_001", 0, 5),
            ("prueba_001", 6, 11),
            ("prueba_001", 12, 17),
        ])
        self.assertEqual(metrics["blocks_completed"], 3)
        self.assertTrue(all(bloque["reconciliado"] for bloque in metrics["blocks"]))

    def test_se_detiene_en_el_bloque_que_no_reconcilia(self) -> None:
        """El fallo debe cortar en el bloque, no al final de la corrida.

        Es la diferencia entre descubrir una perdida a los pocos minutos y
        descubrirla despues de tres horas de publicacion.
        """
        def reconciliar(run_id, desde, hasta):
            if desde == 0:
                return {"filas": hasta - desde + 1, "unicos": hasta - desde + 1}
            return {"filas": 2, "unicos": 2}

        with tempfile.TemporaryDirectory() as directorio:
            with self.assertRaisesRegex(RuntimeError, "no reconcilia"):
                self._publicar(directorio, reconciliar=reconciliar, reconcile_timeout=0)

            checkpoint = Path(directorio) / "checkpoint.json"
            datos = json.loads(checkpoint.read_text(encoding="utf-8"))

        # Solo el primer bloque quedo confirmado: reanudar repetira desde el sexto
        # mensaje y no dara por buenos los que nunca se verificaron.
        self.assertEqual(datos["next_seq"], 6)
        self.assertEqual(datos["blocks_completed"], 1)

    def test_detecta_duplicados_aunque_la_cantidad_de_filas_cierre(self) -> None:
        """`filas == esperadas` no alcanza si hay repeticiones.

        Una fila duplicada mas una faltante da el mismo total; solo el conteo de
        `replay_seq` distintos distingue ambos casos.
        """
        def reconciliar(run_id, desde, hasta):
            return {"filas": hasta - desde + 1, "unicos": hasta - desde}

        with tempfile.TemporaryDirectory() as directorio:
            with self.assertRaisesRegex(RuntimeError, "no reconcilia"):
                self._publicar(directorio, reconciliar=reconciliar, reconcile_timeout=0)

    def test_reanuda_desde_el_seq_indicado(self) -> None:
        with tempfile.TemporaryDirectory() as directorio:
            client, _, metrics = self._publicar(directorio, desde_seq=12)

        self.assertEqual(len(client.published), 6)
        self.assertEqual(metrics["first_seq"], 12)
        self.assertEqual(metrics["last_seq"], 17)
        self.assertEqual(metrics["resumed_from_seq"], 12)

    def test_un_bloque_final_incompleto_se_cierra_igual(self) -> None:
        with tempfile.TemporaryDirectory() as directorio:
            _, checkpoint, metrics = self._publicar(directorio, block_size=8)
            datos = json.loads(checkpoint.read_text(encoding="utf-8"))

        # 18 mensajes con bloques de 8: 8, 8 y un resto de 2.
        self.assertEqual(metrics["blocks_completed"], 3)
        self.assertEqual([bloque["publicados"] for bloque in metrics["blocks"]], [8, 8, 2])
        self.assertEqual(datos["next_seq"], 18)

    def test_espera_a_que_la_persistencia_alcance_al_publicador(self) -> None:
        """La persistencia es asincronica: el bloque no cierra al primer intento.

        Verificar una sola vez, justo al terminar de publicar, reportaria un
        faltante que en realidad todavia estaba en la cola del consumidor.
        """
        intentos = []

        def reconciliar(run_id, desde, hasta):
            intentos.append(desde)
            if len(intentos) < 3:
                return {"filas": 0, "unicos": 0}
            return {"filas": hasta - desde + 1, "unicos": hasta - desde + 1}

        with tempfile.TemporaryDirectory() as directorio:
            ruta = escribir_stream(Path(directorio), muestras=1)
            client = FakeMqttClient()
            metrics = replay_openf1.publish_stream(
                stream_path=ruta,
                replay_run_id="prueba_001",
                speed=1,
                max_delay=0,
                max_inflight_messages=1,
                block_size=6,
                checkpoint_path=None,
                reconciliar=reconciliar,
                reconcile_timeout=30,
                reconcile_interval=0,
                client_factory=lambda _: client,
                dormir=lambda _segundos: None,
            )

        self.assertEqual(len(intentos), 3)
        self.assertEqual(metrics["blocks_completed"], 1)


if __name__ == "__main__":
    unittest.main()
