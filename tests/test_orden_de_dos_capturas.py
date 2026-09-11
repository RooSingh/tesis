# -*- coding: utf-8 -*-
"""Dos capturas de la misma sesion se reproducen en orden, no entrelazadas.

EL DEFECTO QUE ESTO CUIDA. `_avisos_reproducidos` ordenaba por

    COALESCE(replay_seq, <reloj de captura>)

y el reloj de captura **se reinicia en cada captura**. `_orden_dentro_de_la_sesion`
ya documenta por que no sirve para ordenar y ofrece el reemplazo ---el contador
de cuadros que emite el juego, que no sabe cuantas veces se empezo a grabar---
pero esta consulta no lo usaba. Era el unico sitio del modulo que ordenaba por
el reloj crudo; los demas lo usan para limites de fase, que es otra cosa.

MEDIDO el 2026-09-11 en la Pi sobre `f1_25:session:3527452921763583202`, coche
propio, 9.405 muestras de velocidad:

    frame_identifier                    9.405 valores distintos para 9.405 muestras
    ordenando por reloj de captura      el instante retrocede 276 veces, peor -911,8 s
    ordenando por contador de cuadros   retrocede 0 veces

El reloj de captura reinicia exactamente una vez, a las 02:53:11, cayendo de
455.731.590 a 4.265 us: ahi empieza la segunda captura.

LO QUE COSTABA. Las 276 inversiones alimentaban al anotador con el tiempo yendo
hacia atras, y su ventana dejaba de podarse: `/avisos` tardaba 73 s. Eso ya se
corrigio del lado del anotador ---que tiene que aguantar un reloj que salte
venga de donde venga, porque en vivo tambien salta---. Esto corrige el otro
extremo: que la lectura no invente el salto.
"""

from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from backend import api_sesion  # noqa: E402


class ConexionFalsa:
    """Sustituye a `db.obtener_conexion` y recuerda lo que se le pidio."""

    def __init__(self, filas=None):
        self.filas = filas if filas is not None else []
        self.consultas: list[tuple[str, tuple]] = []
        self.cursor_obj = MagicMock()
        self.cursor_obj.execute.side_effect = self._ejecutar
        self.cursor_obj.fetchall.side_effect = lambda: list(self.filas)
        self.cursor_obj.fetchone.side_effect = lambda: (self.filas[0] if self.filas else None)
        self._lotes = [list(self.filas)] if self.filas else []
        self.cursor_obj.fetchmany.side_effect = (
            lambda _: self._lotes.pop(0) if self._lotes else [])

    def _ejecutar(self, consulta, parametros=None):
        self.consultas.append((consulta, parametros))

    def cursor(self, *_, **__):
        contexto = MagicMock()
        contexto.__enter__ = lambda *_: self.cursor_obj
        contexto.__exit__ = lambda *_: False
        return contexto

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class LaLecturaNoOrdenaPorUnRelojQueSeReiniciaTests(unittest.TestCase):

    def _consulta_de_avisos(self) -> str:
        falsa = ConexionFalsa([])
        with patch("backend.api_sesion.db.obtener_conexion", return_value=falsa):
            api_sesion._avisos_reproducidos(
                falsa.cursor_obj, "f1_25_udp_simulation", "f1_25:session:1",
                None, None, (None, None), 60)
        largas = [c for c, _ in falsa.consultas if "ORDER BY" in c]
        self.assertTrue(largas, "la lectura de avisos no ordeno nada")
        return largas[-1]

    def test_ordena_por_el_contador_de_cuadros_y_no_por_el_reloj_de_captura(self) -> None:
        consulta = self._consulta_de_avisos()
        self.assertIn(
            "frame_identifier", consulta,
            "la lectura sigue ordenando por el reloj de captura, que se "
            "reinicia en cada captura y entrelaza dos capturas de la misma "
            "sesion:\n" + consulta)

    def test_una_reproduccion_sigue_mandando_con_su_propia_secuencia(self) -> None:
        """`replay_seq` es del reproductor y no se toca: manda cuando esta."""

        consulta = self._consulta_de_avisos()
        orden = consulta[consulta.index("ORDER BY"):]
        self.assertIn("replay_seq", orden,
                      "la secuencia del reproductor dejo de encabezar el orden")
        self.assertLess(
            orden.index("replay_seq"), orden.index("frame_identifier"),
            "el contador de cuadros paso a mandar sobre `replay_seq`: en una "
            "reproduccion el orden lo da el reproductor")

    def test_usa_el_ayudante_y_no_una_copia_escrita_a_mano(self) -> None:
        """Escrito dos veces, nada obliga a que los dos sitios coincidan.

        El ayudante ya explica por que el contador de cuadros es el orden
        correcto y por que se conserva el `COALESCE` para las fuentes que no lo
        traen. Una copia en la consulta se despegaria de esa explicacion.
        """

        fuente = inspect.getsource(api_sesion._avisos_reproducidos)
        codigo = [r.split("#", 1)[0] for r in fuente.splitlines()]
        self.assertTrue(
            any("_orden_dentro_de_la_sesion()" in r for r in codigo),
            "la consulta no llama a `_orden_dentro_de_la_sesion()`")

    def test_el_ayudante_sigue_prefiriendo_el_contador_de_cuadros(self) -> None:
        orden = api_sesion._orden_dentro_de_la_sesion()
        self.assertIn("frame_identifier", orden)
        self.assertIn("desplazamiento_captura_us", orden,
                      "se perdio el respaldo para las fuentes sin contador de "
                      "cuadros, que son OpenF1 y el bus del vehiculo")


if __name__ == "__main__":
    unittest.main()
