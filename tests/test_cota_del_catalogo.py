"""La ventana de una vuelta se busca entre los extremos que ya sabe el catalogo.

EL DEFECTO QUE ESTO CUIDA. `posiciones_en_pista` y `series_por_distancia` con
vuelta buscaban la ventana con `min/max(timestamp)` sin cota de tiempo. La
hipertabla esta particionada por `timestamp`, de modo que el motor recorria el
indice de tiempo desde un extremo de la tabla hasta dar con la sesion. Medido el
2026-09-11 sobre Red Bull Ring, con 43 GB sin comprimir de por medio: ninguna de
las dos contestaba en 60 s, y el tablero corta a los 30. La comparacion entre
pilotos no llegaba a dibujar.

Lo que se comprueba es la forma de la consulta, que es donde vivia el defecto:
que lleve la cota, que cada `%s` tenga su parametro en el orden correcto, y que
la cota no agregue una ida mas a la base.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend import api_sesion


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


SESION = "f1_25:session:1"


def _ventana_de_la_vuelta(cursor: CursorQueAnota) -> tuple[str, tuple]:
    candidatas = [c for c in cursor.consultas
                  if "min(timestamp)" in c[0] and "lap_number" in c[0]]
    assert len(candidatas) == 1, "se esperaba una sola consulta de ventana"
    return candidatas[0]


class PosicionesTests(unittest.TestCase):

    def _correr(self, ventana=None, limites=(None, None)) -> CursorQueAnota:
        cursor = CursorQueAnota()
        with patch.object(api_sesion.db, "obtener_conexion",
                          return_value=ConexionQueAnota(cursor)), \
             patch.object(api_sesion, "_ventana_de_alcance", return_value=ventana), \
             patch.object(api_sesion, "_limites_de_fase", return_value=limites):
            api_sesion.posiciones_en_pista(SESION, vuelta=2, puntos=20)
        return cursor

    def test_la_ventana_lleva_la_cota_del_catalogo(self) -> None:
        consulta, _ = _ventana_de_la_vuelta(self._correr())
        self.assertIn("sesiones_catalogo", consulta)
        self.assertIn("'-infinity'", consulta,
                      "sin sesion catalogada tiene que quedar como antes, sin cota")

    def test_cada_marcador_tiene_su_parametro(self) -> None:
        consulta, parametros = _ventana_de_la_vuelta(self._correr())
        self.assertEqual(consulta.count("%s"), len(parametros))

    def test_la_sesion_viaja_para_las_dos_mitades_de_la_cota(self) -> None:
        _, parametros = _ventana_de_la_vuelta(self._correr())
        self.assertEqual(parametros[-2:], (SESION, SESION))

    def test_con_fase_el_limite_de_la_fase_sigue_al_final(self) -> None:
        """La cota va antes que el tramo, y los parametros en ese mismo orden."""
        consulta, parametros = _ventana_de_la_vuelta(
            self._correr(ventana=("-infinity", "infinity"), limites=(200, None)))
        self.assertEqual(consulta.count("%s"), len(parametros))
        self.assertEqual(parametros[-3:], (SESION, SESION, 200))

    def test_la_cota_no_agrega_una_consulta(self) -> None:
        """Sin muestras de la vuelta, la ruta sigue consultando una sola vez."""
        cursor = self._correr()
        self.assertEqual(len(cursor.consultas), 1)


class SeriesDeUnaVueltaTests(unittest.TestCase):

    def _correr(self, vuelta=2) -> CursorQueAnota:
        cursor = CursorQueAnota()
        with patch.object(api_sesion.db, "obtener_conexion",
                          return_value=ConexionQueAnota(cursor)), \
             patch.object(api_sesion, "_ventana_de_alcance", return_value=None), \
             patch.object(api_sesion, "_limites_de_fase", return_value=(None, None)):
            api_sesion.series_por_distancia(SESION, senales="speed", vuelta=vuelta)
        return cursor

    def test_la_ventana_lleva_la_cota_del_catalogo(self) -> None:
        consulta, parametros = _ventana_de_la_vuelta(self._correr())
        self.assertIn("sesiones_catalogo", consulta)
        self.assertEqual(consulta.count("%s"), len(parametros))
        self.assertEqual(parametros[-2:], (SESION, SESION))

    def test_sin_vuelta_no_se_busca_ventana(self) -> None:
        """La serie de la sesion entera no pasa por esta consulta."""
        cursor = self._correr(vuelta=None)
        self.assertFalse([c for c in cursor.consultas if "sesiones_catalogo" in c[0]])


if __name__ == "__main__":
    unittest.main()
