"""Pruebas de la identidad de replay y del conteo real de filas insertadas.

No abren conexion a TimescaleDB: verifican las funciones puras que traducen un
mensaje a parametros de insercion y que interpretan `cur.rowcount`.
"""

from __future__ import annotations

import json
import unittest

from backend.db import _filas_insertadas, _identidad_replay, _parametros_telemetria
from backend.models import TelemetryMessage


def mensaje(extra: dict | None = None) -> TelemetryMessage:
    return TelemetryMessage.model_validate({
        "timestamp": "2025-07-06T14:00:00.000000+00:00",
        "vehicle_id": "openf1:session:9947:driver:1",
        "driver_id": "openf1:driver:1",
        "session_id": "openf1:session:9947",
        "lap_id": None,
        "source_type": "openf1_historical_replay",
        "signal_name": "speed",
        "value": 250,
        "unit": "km/h",
        "quality_flag": "observed_openf1",
        "metadata": {"extra": extra} if extra is not None else {},
    })


class IdentidadReplayTests(unittest.TestCase):
    def test_promueve_la_identidad_desde_metadata(self) -> None:
        identidad = _identidad_replay(mensaje({"replay_run_id": "corrida_001", "replay_seq": 42}).metadata)

        self.assertEqual(identidad, ("corrida_001", 42))

    def test_los_mensajes_ajenos_al_replay_quedan_en_nulo(self) -> None:
        """La telemetria CAN simulada no participa del indice unico parcial."""
        self.assertEqual(_identidad_replay(mensaje().metadata), (None, None))
        self.assertEqual(_identidad_replay(mensaje({"replay_mode": True}).metadata), (None, None))

    def test_una_identidad_incompleta_no_se_persiste_a_medias(self) -> None:
        """Sin ambos campos la clave no identifica nada y debe quedar nula."""
        self.assertEqual(_identidad_replay(mensaje({"replay_run_id": "corrida_001"}).metadata), (None, None))
        self.assertEqual(_identidad_replay(mensaje({"replay_seq": 42}).metadata), (None, None))

    def test_los_parametros_incluyen_las_columnas_de_trazabilidad(self) -> None:
        parametros = _parametros_telemetria(mensaje({"replay_run_id": "corrida_001", "replay_seq": 7}))

        self.assertEqual(parametros["replay_run_id"], "corrida_001")
        self.assertEqual(parametros["replay_seq"], 7)
        # La metadata completa se conserva ademas como JSONB: promover la
        # identidad a columnas no debe hacer perder trazabilidad.
        self.assertEqual(json.loads(parametros["metadata"])["extra"]["replay_seq"], 7)


class FilasInsertadasTests(unittest.TestCase):
    def test_devuelve_las_filas_realmente_escritas(self) -> None:
        """Este es el cambio que convierte `persisted` en evidencia.

        Antes se devolvia `len(mensajes)`, de modo que la metrica reflejaba la
        intencion de escribir y no el efecto: una insercion parcial daba el mismo
        numero que una completa.
        """
        self.assertEqual(_filas_insertadas(998, 1000), 998)

    def test_cero_filas_es_un_resultado_valido(self) -> None:
        """Un lote integramente duplicado inserta cero y no es un fallo."""
        self.assertEqual(_filas_insertadas(0, 1000), 0)

    def test_sin_dato_del_driver_no_se_inventa_una_perdida(self) -> None:
        """Suponer una perdida sin evidencia seria tan incorrecto como suponer exito."""
        self.assertEqual(_filas_insertadas(None, 1000), 1000)
        self.assertEqual(_filas_insertadas(-1, 1000), 1000)


if __name__ == "__main__":
    unittest.main()
