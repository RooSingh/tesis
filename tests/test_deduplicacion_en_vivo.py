# -*- coding: utf-8 -*-
"""La clave de idempotencia de la telemetria en vivo.

Con la confirmacion manual la entrega es **al menos una vez**: si el proceso muere
entre el `insert` y el acuse, el intermediario reenvia y la fila se escribiria dos
veces. El indice unico que lo impide necesita una clave, y la clave no puede ser el
instante.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from backend.db import _desplazamiento_de_captura, _parametros_telemetria
from backend.models import TelemetryMessage


def _mensaje(extra: dict | None) -> TelemetryMessage:
    return TelemetryMessage.model_validate({
        "timestamp": datetime(2026, 9, 7, tzinfo=timezone.utc).isoformat(),
        "vehicle_id": "v", "driver_id": "d", "session_id": "s", "lap_id": None,
        "signal_name": "speed", "value": 1.0, "unit": "km/h",
        "source_type": "can_simulated", "quality_flag": "ok",
        "metadata": {"can_id": None, "src": None, "reference_type": "p",
                     "reference_id": "r", "extra": extra or {}},
    })


class ExtraccionTest(unittest.TestCase):

    def test_promueve_el_desplazamiento_del_metadato(self):
        self.assertEqual(
            _desplazamiento_de_captura(
                _mensaje({"desplazamiento_captura_us": 6075583}).metadata),
            6075583)

    def test_acepta_el_valor_como_texto(self):
        """Lo que llega por la red viaja en JSON y puede venir como cadena."""

        self.assertEqual(
            _desplazamiento_de_captura(
                _mensaje({"desplazamiento_captura_us": "42"}).metadata),
            42)

    def test_sin_desplazamiento_devuelve_nulo(self):
        """Las fuentes que no capturan datagramas quedan fuera del indice."""

        self.assertIsNone(_desplazamiento_de_captura(_mensaje({}).metadata))

    def test_un_valor_ilegible_se_trata_como_ausencia(self):
        """Deja la fila sin deduplicar, que es peor que deduplicarla y mucho
        mejor que rechazar telemetria valida por un metadato mal formado."""

        self.assertIsNone(
            _desplazamiento_de_captura(
                _mensaje({"desplazamiento_captura_us": "no-es-un-numero"}).metadata))

    def test_el_cero_es_un_desplazamiento_valido(self):
        """El primer datagrama de una captura tiene desplazamiento cero, y no
        debe confundirse con la ausencia del campo."""

        self.assertEqual(
            _desplazamiento_de_captura(
                _mensaje({"desplazamiento_captura_us": 0}).metadata), 0)


class ParametrosTest(unittest.TestCase):

    def test_la_columna_viaja_en_los_parametros(self):
        p = _parametros_telemetria(_mensaje({"desplazamiento_captura_us": 99}))
        self.assertEqual(p["desplazamiento_captura_us"], 99)

    def test_sin_desplazamiento_la_columna_va_nula(self):
        p = _parametros_telemetria(_mensaje({}))
        self.assertIsNone(p["desplazamiento_captura_us"])

    def test_convive_con_la_identidad_de_reinyeccion(self):
        """Son dos claves distintas y ninguna reemplaza a la otra: una protege
        las reproducciones y la otra la telemetria en vivo."""

        p = _parametros_telemetria(_mensaje({
            "desplazamiento_captura_us": 5,
            "replay_run_id": "corrida", "replay_seq": 7}))
        self.assertEqual(p["desplazamiento_captura_us"], 5)
        self.assertEqual(p["replay_run_id"], "corrida")
        self.assertEqual(p["replay_seq"], 7)


if __name__ == "__main__":
    unittest.main()
