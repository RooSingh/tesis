"""Los avisos son de un vehiculo, y se puede elegir cual.

EL DEFECTO QUE ESTO CUIDA. `/avisos` se calculaba siempre sobre el vehiculo de
quien conduce, mientras el tablero decia que eran «del piloto que se mira».
Medido el 2026-09-11 sobre Red Bull Ring con dos conductores: con el 19 elegido,
los sesenta avisos eran del 18.

Y lo que no se puede evaluar se dice. De otro vehiculo el protocolo no publica
`motion_ex`, de modo que las reglas de deslizamiento no tienen con que correr:
que falten esos avisos no dice que no hayan ocurrido.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from adapters import f1_25 as adaptador_f1_25
from backend import api_sesion

SESION = "f1_25:session:1"
PROPIO = SESION + ":car:18"
OTRO = SESION + ":car:19"


class CursorQueAnota:
    """Devuelve vacio a todo y recuerda cada consulta con sus parametros."""

    def __init__(self) -> None:
        self.consultas: list[tuple[str, tuple]] = []

    def execute(self, consulta, parametros=None):
        self.consultas.append((consulta, tuple(parametros or ())))

    def fetchall(self):
        return []

    def fetchone(self):
        return None

    def fetchmany(self, *_):
        return []


class ConexionQueAnota:
    def __init__(self, cursor: CursorQueAnota) -> None:
        self.cursor_obj = cursor

    def cursor(self, *_, **__):
        c = MagicMock()
        c.__enter__ = lambda *_: self.cursor_obj
        c.__exit__ = lambda *_: False
        return c

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class AvisosPorVehiculoTests(unittest.TestCase):

    def setUp(self) -> None:
        api_sesion._AVISOS_CACHE.clear()

    def tearDown(self) -> None:
        api_sesion._AVISOS_CACHE.clear()

    def _pedir(self, **pedido):
        cursor = CursorQueAnota()
        with patch.object(api_sesion.db, "obtener_conexion",
                          return_value=ConexionQueAnota(cursor)), \
             patch.object(api_sesion, "_vehiculo_propio", return_value=PROPIO), \
             patch.object(api_sesion, "_ventana_de_alcance", return_value=None), \
             patch.object(api_sesion, "_limites_de_fase", return_value=(None, None)):
            respuesta = api_sesion.avisos(SESION, **pedido)
        return respuesta, cursor

    def _vehiculos_consultados(self, cursor: CursorQueAnota) -> list[str]:
        lecturas = [p for c, p in cursor.consultas if "FROM telemetry_messages" in c]
        self.assertEqual(len(lecturas), 1, "los avisos dejaron de ser una sola pasada")
        return [x for x in lecturas[0] if isinstance(x, str) and ":car:" in x]

    def test_sin_elegir_son_de_quien_conduce(self) -> None:
        """Lo de antes no cambia para quien no elige."""
        r, cursor = self._pedir()
        self.assertEqual(r["vehiculo"], PROPIO)
        self.assertEqual(self._vehiculos_consultados(cursor), [PROPIO])
        self.assertNotIn("canales_sin_dato", r)

    def test_elegido_otro_la_consulta_es_de_ese(self) -> None:
        r, cursor = self._pedir(vehiculo=OTRO)
        self.assertEqual(r["vehiculo"], OTRO)
        self.assertEqual(r["vehiculo_propio"], PROPIO)
        self.assertEqual(self._vehiculos_consultados(cursor), [OTRO])

    def test_de_otro_vehiculo_declara_lo_que_no_se_puede_evaluar(self) -> None:
        r, _ = self._pedir(vehiculo=OTRO)
        self.assertIn("wheel_slip_ratio_rear_left", r["canales_sin_dato"])
        self.assertIn("no dice que no hayan ocurrido", r["motivo_sin_dato"])

    def test_elegir_a_quien_conduce_no_declara_ausencias(self) -> None:
        r, _ = self._pedir(vehiculo=PROPIO)
        self.assertNotIn("canales_sin_dato", r)

    def test_la_cache_no_sirve_los_de_uno_como_de_otro(self) -> None:
        self._pedir(vehiculo=PROPIO)
        r, cursor = self._pedir(vehiculo=OTRO)
        self.assertFalse(r["de_cache"], "se sirvieron los avisos del 18 como del 19")
        self.assertTrue(cursor.consultas)

    def test_un_vehiculo_de_otra_sesion_se_rechaza(self) -> None:
        """Devolver cero avisos lo haria pasar por una sesion sin incidentes."""
        with self.assertRaises(HTTPException) as caso:
            self._pedir(vehiculo="f1_25:session:2:car:19")
        self.assertEqual(caso.exception.status_code, 422)

    def test_los_canales_sin_dato_salen_del_catalogo_y_son_del_anotador(self) -> None:
        canales = api_sesion._canales_solo_del_propio()
        self.assertIn("wheel_slip_ratio_rear_left", canales)
        self.assertIn("wheel_slip_ratio_rear_right", canales)
        privados = {s["signal_name"] for s in adaptador_f1_25.catalogo_de_senales()
                    if s["paquete"] in adaptador_f1_25.PAQUETES_DE_BLOQUE_UNICO}
        for canal in canales:
            self.assertIn(canal, privados)


if __name__ == "__main__":
    unittest.main()
