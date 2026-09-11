"""El clima que la base no tiene se completa desde la procedencia, y se dice.

EL DEFECTO QUE ESTO CUIDA. Las temperaturas y el cielo entraron al contrato como
senales el 2026-09-02, y las sesiones guardadas antes no los tienen en la base.
El panel mostraba «—°C sin declarar» sobre la carrera de Red Bull Ring con
Alpine contra McLaren, cuya captura si los declara.

Lo que se comprueba: que se complete solo lo que falta, que la respuesta diga que
salio de la procedencia, y que lo que la base tiene no se pise.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend import api_sesion

SESION = "f1_25:session:1"
PROCEDENCIA = {"clima": "despejado", "temperatura_pista_c": 31,
               "temperatura_aire_c": 22}


class _Conexion:
    def cursor(self, *_, **__):
        c = MagicMock()
        c.__enter__ = lambda *_: MagicMock()
        c.__exit__ = lambda *_: False
        return c

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _contexto(valores: dict, procedencia: dict | None):
    with patch.object(api_sesion.db, "obtener_conexion", return_value=_Conexion()), \
         patch.object(api_sesion, "_ventana_de_alcance", return_value=None), \
         patch.object(api_sesion, "_limites_de_fase", return_value=(None, None)), \
         patch.object(api_sesion, "_vehiculo_propio", return_value=SESION + ":car:18"), \
         patch.object(api_sesion, "_ultimos_valores", return_value=valores), \
         patch.object(api_sesion, "_comparar_con_referencia", return_value=(None, [])), \
         patch.object(api_sesion.procedencia_sesiones, "de", return_value=procedencia):
        return api_sesion.contexto(SESION)


class ClimaDesdeLaProcedenciaTests(unittest.TestCase):

    def test_sin_clima_en_la_base_se_completa_y_se_declara(self) -> None:
        r = _contexto({"fia_flag": {"valor": 0.0}}, PROCEDENCIA)
        clima = r["clima"]
        self.assertEqual(clima["temperatura_aire_c"], 22)
        self.assertEqual(clima["temperatura_pista_c"], 31)
        self.assertEqual(clima["clima"], "despejado")
        self.assertEqual(sorted(clima["de_la_procedencia"]),
                         ["clima", "temperatura_aire_c", "temperatura_pista_c"])
        self.assertIn("toda la sesion", clima["procedencia_nota"])
        self.assertEqual(clima["bandera_texto"], "ninguna",
                         "lo que si llego de la base se perdio")

    def test_lo_que_la_base_tiene_no_se_pisa(self) -> None:
        r = _contexto({"air_temperature": {"valor": 18.0},
                       "track_temperature": {"valor": 27.0},
                       "weather_code": {"valor": 3.0}}, PROCEDENCIA)
        clima = r["clima"]
        self.assertEqual(clima["temperatura_aire_c"], 18.0)
        self.assertEqual(clima["temperatura_pista_c"], 27.0)
        self.assertEqual(clima["clima"], "lluvia ligera")
        self.assertNotIn("de_la_procedencia", clima)

    def test_se_completa_solo_lo_que_falta(self) -> None:
        r = _contexto({"air_temperature": {"valor": 18.0}}, PROCEDENCIA)
        clima = r["clima"]
        self.assertEqual(clima["temperatura_aire_c"], 18.0)
        self.assertEqual(sorted(clima["de_la_procedencia"]),
                         ["clima", "temperatura_pista_c"])

    def test_sin_procedencia_queda_como_antes(self) -> None:
        r = _contexto({"fia_flag": {"valor": 0.0}}, None)
        self.assertNotIn("temperatura_aire_c", r["clima"])
        self.assertNotIn("de_la_procedencia", r["clima"])


if __name__ == "__main__":
    unittest.main()
