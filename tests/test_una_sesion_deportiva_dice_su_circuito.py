# -*- coding: utf-8 -*-
"""Una carrera de la fuente deportiva se llama por su circuito, no por su numero.

QUE PASABA, REPORTADO EL 2026-09-13. Cargada la carrera de Spa, el tablero la
titulaba **«Sesion OpenF1 9939»**. El dato estaba: la importacion de contexto
deja `circuit_short_name = 'Spa-Francorchamps'` en `racing_sessions`.

POR QUE NO LLEGABA. `/sesiones` enriquece cada fila con
`procedencia_sesiones.de()`, que lee los metadatos que el **capturador** escribe
junto a cada captura del simulador. Una sesion de la fuente deportiva no pasa
por el capturador y no tiene esos metadatos, de modo que su procedencia era
`None` y con ella el circuito, el tipo y la familia.

DOS FUENTES DE PROCEDENCIA PARA DOS ORIGENES DISTINTOS, y esta bien que sean
dos: la del simulador la declara el paquete de sesion que el juego emite; la de
la fuente deportiva la declara su propio `session.json`. Lo que faltaba era
leer la segunda.

SE LEEN TODAS DE UNA VEZ. `/sesiones` lista treinta: una consulta por sesion
serian treinta viajes a la base para llenar una columna.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from backend import procedencia_openf1  # noqa: E402

#: Lo que `racing_sessions` guarda de Spa, tal cual.
FILAS = [
    (9939, "Spa-Francorchamps", "Belgium", "Race", "Race"),
    (9947, "Silverstone", "United Kingdom", "Race", "Race"),
    (9955, "Spielberg", "Austria", "Qualifying", "Qualifying"),
]


class ConexionFalsa:
    def __init__(self, filas):
        self.filas = filas
        self.consultas = []

    def cursor(self):
        return self

    def execute(self, sql, parametros=None):
        self.consultas.append((" ".join(sql.split()), parametros))

    def fetchall(self):
        return self.filas

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class UnaSesionDeportivaDiceSuCircuitoTests(unittest.TestCase):

    def _indice(self, filas=None):
        conexion = ConexionFalsa(FILAS if filas is None else filas)
        with patch.object(procedencia_openf1.db, "obtener_conexion",
                          return_value=conexion):
            return procedencia_openf1.indice(), conexion

    def test_EL_DEFECTO_la_carrera_de_spa_declara_su_circuito(self) -> None:
        indice, _ = self._indice()
        self.assertEqual(indice["openf1:session:9939"]["circuito"],
                         "Spa-Francorchamps")

    def test_la_clave_es_la_que_usa_el_catalogo_y_no_el_numero(self) -> None:
        """`racing_sessions` guarda 9939; el catalogo, `openf1:session:9939`."""
        indice, _ = self._indice()
        self.assertEqual(sorted(indice), ["openf1:session:9939",
                                          "openf1:session:9947",
                                          "openf1:session:9955"])

    def test_dice_tambien_que_clase_de_sesion_es(self) -> None:
        """Una clasificacion y una carrera se ven iguales sin esto."""
        indice, _ = self._indice()
        self.assertEqual(indice["openf1:session:9939"]["tipo_sesion_nombre"], "Race")
        self.assertEqual(indice["openf1:session:9955"]["tipo_sesion_nombre"],
                         "Qualifying")

    def test_SE_LEEN_TODAS_DE_UNA_VEZ(self) -> None:
        """Treinta sesiones no pueden costar treinta viajes a la base."""
        _, conexion = self._indice()
        self.assertEqual(len(conexion.consultas), 1, conexion.consultas)

    def test_una_sesion_sin_circuito_declarado_no_inventa_uno(self) -> None:
        """La columna admite nulos: hay paquetes viejos sin ese campo."""
        indice, _ = self._indice([(9939, None, None, "Race", "Race")])
        self.assertIsNone(indice["openf1:session:9939"]["circuito"])

    def test_si_la_base_no_contesta_no_se_cae_el_listado(self) -> None:
        """El circuito es un adorno del listado; la lista tiene que salir igual.

        Es la misma regla que el resto del enriquecimiento: lo que decora no
        puede tumbar lo que informa.
        """
        with patch.object(procedencia_openf1.db, "obtener_conexion",
                          side_effect=RuntimeError("sin base")):
            self.assertEqual(procedencia_openf1.indice(), {})


if __name__ == "__main__":
    unittest.main()
