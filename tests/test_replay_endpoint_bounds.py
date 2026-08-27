"""Pruebas de las cotas del endpoint de replay, sin base de datos.

Regresion del defecto detectado en la revision del 2026-08-27: la ruta
`/racing/sessions/{key}/replay` no exigia corrida ni tenia tope, de modo que una
llamada sin parametros pedia 10.079.006 filas, del orden de 13 GB de objetos en
memoria del backend. El dashboard la invocaba asi en su vista principal.

Ninguna prueba cubria ese endpoint antes de que fallara en produccion local.
"""

from __future__ import annotations

import inspect
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from backend.app import (
    LIMITE_FILAS_REPLAY,
    racing_analysis_laps,
    racing_analysis_stints,
    racing_replay,
    racing_session_analysis,
)


def muestra(indice: int) -> dict:
    return {"timestamp": f"2025-07-06T14:00:{indice:02d}+00:00", "signal_name": "speed"}


class CorridaObligatoriaTests(unittest.TestCase):
    def test_la_corrida_no_tiene_valor_por_defecto(self) -> None:
        """Sin corrida obligatoria se mezclan repeticiones de las mismas vueltas.

        La sesion 9947 acumula el replay definitivo junto a mas de una decena de
        sondeos de carga bajo el mismo `session_id`. Una estadistica calculada sin
        filtrar por corrida queda promediada entre copias solapadas.
        """
        parametro = inspect.signature(racing_replay).parameters["replay_run_id"]

        self.assertIs(parametro.default, inspect.Parameter.empty)

    def test_el_limite_tiene_valor_por_defecto_acotado(self) -> None:
        parametro = inspect.signature(racing_replay).parameters["limite"]

        self.assertEqual(parametro.default, LIMITE_FILAS_REPLAY)
        self.assertLessEqual(LIMITE_FILAS_REPLAY, 50000)


class RespuestaAcotadaTests(unittest.TestCase):
    def test_declara_el_truncamiento_en_vez_de_recortar_en_silencio(self) -> None:
        with patch("backend.app.obtener_replay_openf1", return_value=([muestra(i) for i in range(10)], True)):
            respuesta = racing_replay(9947, "d7_silverstone_full_001", limite=10)

        self.assertTrue(respuesta["truncado"])
        self.assertIn("advertencia_truncado", respuesta)
        self.assertEqual(respuesta["total_devuelto"], 10)

    def test_un_lote_completo_no_lleva_advertencia(self) -> None:
        with patch("backend.app.obtener_replay_openf1", return_value=([muestra(0)], False)):
            respuesta = racing_replay(9947, "d7_silverstone_full_001")

        self.assertFalse(respuesta["truncado"])
        self.assertNotIn("advertencia_truncado", respuesta)

    def test_el_limite_se_traslada_a_la_consulta(self) -> None:
        with patch("backend.app.obtener_replay_openf1", return_value=([], False)) as consulta:
            racing_replay(9947, "corrida_001", driver_number=44, limite=500)

        consulta.assert_called_once_with(9947, "corrida_001", 44, 500)

    def test_un_limite_fuera_de_rango_se_rechaza(self) -> None:
        with self.assertRaises(HTTPException) as error:
            racing_replay(9947, "corrida_001", limite=0)
        self.assertEqual(error.exception.status_code, 400)

        with self.assertRaises(HTTPException):
            racing_replay(9947, "corrida_001", limite=10_000_000)


class AnalisisTests(unittest.TestCase):
    def test_lista_los_analisis_de_una_sesion(self) -> None:
        corridas = [{"replay_run_id": "d7_silverstone_full_001", "counts": {"vueltas": 1040}}]
        with patch("backend.app.listar_analisis_sesion", return_value=corridas):
            self.assertEqual(racing_session_analysis(9947)[0]["counts"]["vueltas"], 1040)

    def test_404_cuando_la_corrida_no_tiene_analisis_generado(self) -> None:
        """El mensaje indica como generarlo en vez de devolver una lista vacia.

        Una lista vacia se confundiria con una corrida analizada sin resultados.
        """
        with patch("backend.app.obtener_analisis_vueltas", return_value=[]):
            with self.assertRaises(HTTPException) as error:
                racing_analysis_laps(9947, "corrida_inexistente")

        self.assertEqual(error.exception.status_code, 404)
        self.assertIn("generate_session_analysis", error.exception.detail)

    def test_404_tambien_para_stints(self) -> None:
        with patch("backend.app.obtener_analisis_stints", return_value=[]):
            with self.assertRaises(HTTPException) as error:
                racing_analysis_stints(9947, "corrida_inexistente")

        self.assertEqual(error.exception.status_code, 404)

    def test_conserva_la_separacion_por_nivel_de_evidencia(self) -> None:
        """Aplanar las metricas borraria el aporte metodologico del analisis."""
        fila = {
            "driver_number": 1,
            "lap_number": 20,
            "metricas_oficiales": {"lap_duration_seconds": 162.616},
            "metricas_derivadas": {"velocidad_max_kph": 246.0},
            "calidad": {"muestras_velocidad": 609},
        }
        with patch("backend.app.obtener_analisis_vueltas", return_value=[fila]):
            respuesta = racing_analysis_laps(9947, "d7_silverstone_full_001", driver_number=1)

        self.assertIn("metricas_oficiales", respuesta[0])
        self.assertIn("metricas_derivadas", respuesta[0])
        self.assertIn("calidad", respuesta[0])


if __name__ == "__main__":
    unittest.main()
