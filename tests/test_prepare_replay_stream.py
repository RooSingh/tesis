"""Pruebas del preparador de stream de replay, sin broker ni base de datos."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "prepare_replay_stream", ROOT / "scripts" / "prepare_replay_stream.py"
)
assert SPEC is not None and SPEC.loader is not None
prepare_replay_stream = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare_replay_stream)

from adapters.openf1 import messages_from_openf1_sample


def muestra_car_data(fecha: str, driver_number: int = 1, **campos) -> dict:
    base = {
        "date": fecha,
        "session_key": 9947,
        "meeting_key": 1277,
        "driver_number": driver_number,
        "speed": 250,
        "throttle": 90,
        "brake": 0,
        "rpm": 11000,
        "n_gear": 7,
        "drs": 12,
    }
    base.update(campos)
    return base


def muestra_location(fecha: str, driver_number: int = 1) -> dict:
    return {
        "date": fecha,
        "session_key": 9947,
        "meeting_key": 1277,
        "driver_number": driver_number,
        "x": 100,
        "y": 200,
        "z": 5,
    }


class ContarMensajesTests(unittest.TestCase):
    def test_coincide_con_la_expansion_real(self) -> None:
        """El conteo debe replicar exactamente lo que produce el adaptador.

        Si difiriera, la secuencia global quedaria corrida y la clave de
        idempotencia dejaria de identificar al mensaje correcto.
        """
        sample = muestra_car_data("2025-07-06T14:00:00.000000+00:00")

        self.assertEqual(
            prepare_replay_stream.contar_mensajes(sample, "car_data"),
            len(messages_from_openf1_sample(sample, "car_data", "url", "path")),
        )

    def test_ignora_senales_ausentes(self) -> None:
        sample = muestra_car_data("2025-07-06T14:00:00.000000+00:00")
        del sample["drs"]
        del sample["n_gear"]

        self.assertEqual(prepare_replay_stream.contar_mensajes(sample, "car_data"), 4)
        self.assertEqual(
            prepare_replay_stream.contar_mensajes(sample, "car_data"),
            len(messages_from_openf1_sample(sample, "car_data", "url", "path")),
        )

    def test_location_produce_tres_mensajes(self) -> None:
        sample = muestra_location("2025-07-06T14:00:00.000000+00:00")

        self.assertEqual(prepare_replay_stream.contar_mensajes(sample, "location"), 3)


class ClaveOrdenTests(unittest.TestCase):
    def test_ordena_por_instante_real_y_no_por_texto(self) -> None:
        """La clave normalizada elimina la dependencia del formato de fecha.

        `collect_samples()` ordena comparando el campo `date` como texto crudo.
        Sobre los archivos actuales eso funciona, porque todos usan el mismo
        formato con desplazamiento `+00:00`; pero es una suposicion no declarada.

        Con un desplazamiento horario distinto el orden de texto y el cronologico
        dejan de coincidir: las 15:00 en `+01:00` son las 14:00 UTC, anteriores a
        las 14:30 UTC, y sin embargo `'2025-07-06T15:...'` es mayor como texto que
        `'2025-07-06T14:...'`.
        """
        texto_temprano = "2025-07-06T15:00:00.000000+01:00"
        texto_tardio = "2025-07-06T14:30:00.000000+00:00"

        temprano = prepare_replay_stream.parse_time(texto_temprano)
        tardio = prepare_replay_stream.parse_time(texto_tardio)
        self.assertLess(temprano, tardio)

        # El orden de texto crudo invierte el orden real...
        self.assertGreater(texto_temprano, texto_tardio)
        # ...y la clave normalizada lo conserva.
        self.assertLess(
            prepare_replay_stream.clave_orden(temprano, "car_data", 1),
            prepare_replay_stream.clave_orden(tardio, "car_data", 1),
        )

    def test_conserva_el_orden_de_los_microsegundos(self) -> None:
        temprano = datetime(2025, 7, 6, 14, 0, 0, 100000, tzinfo=timezone.utc)
        tardio = datetime(2025, 7, 6, 14, 0, 0, 900000, tzinfo=timezone.utc)

        self.assertLess(
            prepare_replay_stream.clave_orden(temprano, "car_data", 1),
            prepare_replay_stream.clave_orden(tardio, "car_data", 1),
        )

    def test_desempata_de_forma_estable(self) -> None:
        """Dos ejecuciones sobre los mismos archivos deben dar la misma secuencia."""
        fecha = datetime(2025, 7, 6, 14, 0, 0, tzinfo=timezone.utc)

        self.assertLess(
            prepare_replay_stream.clave_orden(fecha, "car_data", 1),
            prepare_replay_stream.clave_orden(fecha, "car_data", 44),
        )
        self.assertLess(
            prepare_replay_stream.clave_orden(fecha, "car_data", 1),
            prepare_replay_stream.clave_orden(fecha, "location", 1),
        )


class FusionTests(unittest.TestCase):
    def _preparar(self, directorio: Path) -> Path:
        origen_car = directorio / "car.json"
        origen_loc = directorio / "loc.json"
        origen_car.write_text(
            json.dumps([
                muestra_car_data("2025-07-06T14:00:02.000000+00:00"),
                muestra_car_data("2025-07-06T14:00:00.000000+00:00"),
            ]),
            encoding="utf-8",
        )
        origen_loc.write_text(
            json.dumps([muestra_location("2025-07-06T14:00:01.000000+00:00")]),
            encoding="utf-8",
        )

        parte_car = directorio / "car.part"
        parte_loc = directorio / "loc.part"
        prepare_replay_stream.escribir_particion(origen_car, "car_data", 1, None, None, parte_car)
        prepare_replay_stream.escribir_particion(origen_loc, "location", 1, None, None, parte_loc)

        salida = directorio / "stream.jsonl"
        prepare_replay_stream.fusionar([parte_car, parte_loc], salida)
        return salida

    def test_mezcla_en_orden_temporal_con_secuencia_acumulada(self) -> None:
        with tempfile.TemporaryDirectory() as directorio:
            salida = self._preparar(Path(directorio))
            registros = [json.loads(linea) for linea in salida.read_text(encoding="utf-8").splitlines()]

        fechas = [registro["sample"]["date"] for registro in registros]
        self.assertEqual(fechas, sorted(fechas))
        self.assertEqual([registro["endpoint"] for registro in registros], ["car_data", "location", "car_data"])
        # car_data aporta 6 senales y location 3: 0, 6 y 9.
        self.assertEqual([registro["seq"] for registro in registros], [0, 6, 9])
        self.assertEqual([registro["n"] for registro in registros], [6, 3, 6])

    def test_la_secuencia_no_deja_huecos_ni_solapamientos(self) -> None:
        with tempfile.TemporaryDirectory() as directorio:
            salida = self._preparar(Path(directorio))
            registros = [json.loads(linea) for linea in salida.read_text(encoding="utf-8").splitlines()]

        siguiente = 0
        for registro in registros:
            self.assertEqual(registro["seq"], siguiente)
            siguiente += registro["n"]
        self.assertEqual(siguiente, 15)

    def test_la_ventana_temporal_filtra_las_muestras(self) -> None:
        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio)
            origen = ruta / "car.json"
            origen.write_text(
                json.dumps([
                    muestra_car_data("2025-07-06T14:00:00.000000+00:00"),
                    muestra_car_data("2025-07-06T14:00:05.000000+00:00"),
                    muestra_car_data("2025-07-06T14:00:10.000000+00:00"),
                ]),
                encoding="utf-8",
            )
            parte = ruta / "car.part"

            escritas = prepare_replay_stream.escribir_particion(
                origen,
                "car_data",
                1,
                prepare_replay_stream.parse_time("2025-07-06T14:00:03+00:00"),
                prepare_replay_stream.parse_time("2025-07-06T14:00:10+00:00"),
                parte,
            )

        # El inicio es inclusivo y el fin exclusivo, igual que en la ruta clasica.
        self.assertEqual(escritas, 1)


if __name__ == "__main__":
    unittest.main()
