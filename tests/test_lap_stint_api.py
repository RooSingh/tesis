"""Pruebas de los endpoints de seleccion por vuelta y stint, sin TimescaleDB."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import HTTPException

from backend.app import (
    LIMITE_MUESTRAS_POR_DEFECTO,
    racing_driver_laps,
    racing_lap_telemetry,
    racing_stint_telemetry,
)


BASE = datetime(2025, 7, 6, 14, 0, 0, tzinfo=timezone.utc)


def ventana(completa: bool = True, estimado: bool = False) -> dict:
    return {
        "lap_number": 12,
        "inicio": BASE,
        "fin": BASE + timedelta(seconds=90) if completa else None,
        "fin_estimado": estimado,
        "completa": completa,
    }


def muestra(indice: int) -> dict:
    return {
        "timestamp": BASE + timedelta(seconds=indice),
        "signal_name": "speed",
        "value_numeric": 200.0 + indice,
    }


class ListadoDeVueltasTests(unittest.TestCase):
    def test_devuelve_las_ventanas_derivadas(self) -> None:
        vueltas = [{"lap_number": 1, "date_start": BASE, "lap_duration_seconds": 90.0}]
        with patch("backend.app.obtener_vueltas_piloto", return_value=vueltas):
            with patch("backend.app.calcular_ventanas_vueltas", return_value=[ventana()]) as calcular:
                respuesta = racing_driver_laps(9947, 1)

        calcular.assert_called_once_with(vueltas)
        self.assertEqual(respuesta[0]["lap_number"], 12)

    def test_404_cuando_el_piloto_no_tiene_vueltas(self) -> None:
        with patch("backend.app.obtener_vueltas_piloto", return_value=[]):
            with self.assertRaises(HTTPException) as error:
                racing_driver_laps(9947, 99)

        self.assertEqual(error.exception.status_code, 404)


class TelemetriaPorVueltaTests(unittest.TestCase):
    def test_devuelve_ventana_y_muestras(self) -> None:
        """La ventana viaja con los datos para que el recorte sea auditable."""
        with patch("backend.app.resolver_ventana_vuelta", return_value=ventana()):
            with patch("backend.app.obtener_telemetria_en_ventana", return_value=[muestra(0), muestra(1)]):
                respuesta = racing_lap_telemetry(9947, 1, 12)

        self.assertEqual(respuesta["ventana"]["lap_number"], 12)
        self.assertEqual(respuesta["total_devuelto"], 2)
        self.assertFalse(respuesta["truncado"])
        self.assertNotIn("advertencia", respuesta)

    def test_404_cuando_la_vuelta_no_existe(self) -> None:
        with patch("backend.app.resolver_ventana_vuelta", return_value=None):
            with self.assertRaises(HTTPException) as error:
                racing_lap_telemetry(9947, 1, 999)

        self.assertEqual(error.exception.status_code, 404)

    def test_una_ventana_incompleta_no_consulta_telemetria_y_lo_declara(self) -> None:
        """Devolver muestras de una ventana sin fin seria devolver un recorte falso."""
        with patch("backend.app.resolver_ventana_vuelta", return_value=ventana(completa=False)):
            with patch("backend.app.obtener_telemetria_en_ventana") as consulta:
                respuesta = racing_lap_telemetry(9947, 1, 52)

        consulta.assert_not_called()
        self.assertEqual(respuesta["muestras"], [])
        self.assertIn("advertencia", respuesta)

    def test_un_fin_estimado_queda_declarado_en_la_respuesta(self) -> None:
        """La ultima vuelta se cierra por duracion: quien consume debe saberlo."""
        with patch("backend.app.resolver_ventana_vuelta", return_value=ventana(estimado=True)):
            with patch("backend.app.obtener_telemetria_en_ventana", return_value=[muestra(0)]):
                respuesta = racing_lap_telemetry(9947, 1, 52)

        self.assertTrue(respuesta["ventana"]["fin_estimado"])
        self.assertIn("estimado", respuesta["advertencia"])

    def test_el_truncamiento_se_declara_en_vez_de_recortar_en_silencio(self) -> None:
        """Una lista recortada sin aviso se leeria como una vuelta incompleta."""
        with patch("backend.app.resolver_ventana_vuelta", return_value=ventana()):
            with patch("backend.app.obtener_telemetria_en_ventana", return_value=[muestra(i) for i in range(5)]):
                respuesta = racing_lap_telemetry(9947, 1, 12, limite=5)

        self.assertTrue(respuesta["truncado"])
        self.assertIn("advertencia_truncado", respuesta)

    def test_los_filtros_llegan_a_la_consulta(self) -> None:
        with patch("backend.app.resolver_ventana_vuelta", return_value=ventana()):
            with patch("backend.app.obtener_telemetria_en_ventana", return_value=[]) as consulta:
                racing_lap_telemetry(9947, 1, 12, signal="speed", replay_run_id="corrida_001")

        _, kwargs = consulta.call_args
        self.assertEqual(kwargs["signal_name"], "speed")
        self.assertEqual(kwargs["replay_run_id"], "corrida_001")
        self.assertEqual(kwargs["limite"], LIMITE_MUESTRAS_POR_DEFECTO)

    def test_un_limite_fuera_de_rango_se_rechaza(self) -> None:
        with self.assertRaises(HTTPException) as error:
            racing_lap_telemetry(9947, 1, 12, limite=0)
        self.assertEqual(error.exception.status_code, 400)

        with self.assertRaises(HTTPException):
            racing_lap_telemetry(9947, 1, 12, limite=999999)


class TelemetriaPorStintTests(unittest.TestCase):
    def test_devuelve_ventana_y_muestras(self) -> None:
        stint = {
            "stint_number": 2,
            "compound": "INTERMEDIATE",
            "lap_start": 12,
            "lap_end": 41,
            "tyre_age_at_start": 0,
            "inicio": BASE,
            "fin": BASE + timedelta(minutes=45),
            "fin_estimado": False,
            "completa": True,
        }
        with patch("backend.app.resolver_ventana_stint", return_value=stint):
            with patch("backend.app.obtener_telemetria_en_ventana", return_value=[muestra(0)]):
                respuesta = racing_stint_telemetry(9947, 1, 2)

        self.assertEqual(respuesta["ventana"]["compound"], "INTERMEDIATE")
        self.assertEqual(respuesta["ventana"]["lap_start"], 12)
        self.assertEqual(respuesta["total_devuelto"], 1)

    def test_404_cuando_el_stint_no_existe(self) -> None:
        with patch("backend.app.resolver_ventana_stint", return_value=None):
            with self.assertRaises(HTTPException) as error:
                racing_stint_telemetry(9947, 1, 99)

        self.assertEqual(error.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
