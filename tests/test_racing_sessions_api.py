"""Pruebas de la seleccion de sesion y de corrida, sin TimescaleDB.

El dashboard tenia la sesion `9947` y la corrida `d7_silverstone_full_001`
escritas en el codigo, de modo que Spa-Francorchamps y Suzuka estaban importadas
en la base y no habia forma de verlas. Estas pruebas cubren las dos rutas que
sostienen los selectores y, sobre todo, que una sesion sin telemetria **declare**
esa ausencia en vez de devolver una respuesta indistinguible de un fallo.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from backend.app import _telemetria_declarada, racing_replay_runs, racing_sessions
from backend.db import _session_key_de, obtener_analisis_vueltas


BASE = datetime(2025, 7, 6, 14, 0, 0, tzinfo=timezone.utc)


def sesion(session_key: int, circuito: str) -> dict:
    return {
        "session_key": session_key,
        "meeting_key": 1250,
        "session_name": "Race",
        "session_type": "Race",
        "circuit_key": 2,
        "circuit_short_name": circuito,
        "country_name": "United Kingdom",
        "location": circuito,
        "date_start": BASE,
        "date_end": BASE,
        "drivers": 20,
        "laps": 827,
        "stints": 55,
        "analisis_generados": 1,
    }


def corrida_procesada(session_key: int, pilotos_car_data: int) -> dict:
    return {
        "run_id": session_key,
        "session_key": session_key,
        "inventory": {
            "capabilities": {
                "laps": True,
                "telemetry_drivers": {
                    "car_data": list(range(pilotos_car_data)),
                    "location": list(range(pilotos_car_data)),
                },
            }
        },
    }


class DeclaracionDeTelemetriaTests(unittest.TestCase):
    def test_un_paquete_con_car_data_declara_los_pilotos_disponibles(self) -> None:
        declaracion = _telemetria_declarada(corrida_procesada(9947, 20)["inventory"])

        self.assertTrue(declaracion["disponible"])
        self.assertEqual(declaracion["pilotos_car_data"], 20)
        self.assertNotIn("motivo", declaracion)

    def test_un_paquete_sin_car_data_dice_por_que_no_hay_telemetria(self) -> None:
        """Es el caso de Spa-Francorchamps y Suzuka.

        Sin este motivo la interfaz solo podria mostrar paneles vacios, que no
        distinguen una sesion sin telemetria de una consulta que fallo.
        """
        declaracion = _telemetria_declarada(corrida_procesada(9939, 0)["inventory"])

        self.assertFalse(declaracion["disponible"])
        self.assertEqual(declaracion["pilotos_car_data"], 0)
        self.assertIn("car_data", declaracion["motivo"])

    def test_una_sesion_sin_paquete_procesado_no_afirma_telemetria(self) -> None:
        """Ausencia de inventario no es evidencia de telemetria disponible."""
        declaracion = _telemetria_declarada(None)

        self.assertFalse(declaracion["disponible"])
        self.assertIn("motivo", declaracion)


class ListadoDeSesionesTests(unittest.TestCase):
    def test_cada_sesion_viaja_con_su_telemetria_declarada(self) -> None:
        sesiones = [sesion(9947, "Silverstone"), sesion(9939, "Spa-Francorchamps")]
        runs = [corrida_procesada(9947, 20), corrida_procesada(9939, 0)]
        with patch("backend.app.listar_sesiones_racing", return_value=sesiones):
            with patch("backend.app.listar_ejecuciones_procesamiento", return_value=runs):
                respuesta = racing_sessions()

        self.assertTrue(respuesta[0]["telemetria"]["disponible"])
        self.assertFalse(respuesta[1]["telemetria"]["disponible"])
        # La identidad del circuito viaja con la sesion: elegir por numero de
        # sesion no le dice nada a quien elige.
        self.assertEqual(respuesta[1]["circuit_short_name"], "Spa-Francorchamps")

    def test_de_varias_corridas_de_una_sesion_vale_la_mas_reciente(self) -> None:
        """Silverstone tiene dos procesamientos: uno de 3 pilotos y otro de 20.

        `listar_ejecuciones_procesamiento` devuelve de la mas reciente a la mas
        antigua, de modo que la primera que aparece es la vigente.
        """
        runs = [corrida_procesada(9947, 20), corrida_procesada(9947, 3)]
        with patch("backend.app.listar_sesiones_racing", return_value=[sesion(9947, "Silverstone")]):
            with patch("backend.app.listar_ejecuciones_procesamiento", return_value=runs):
                respuesta = racing_sessions()

        self.assertEqual(respuesta[0]["telemetria"]["pilotos_car_data"], 20)


class ListadoDeCorridasTests(unittest.TestCase):
    """La ruta no debe recorrer la tabla para listar unas pocas corridas.

    ACTUALIZADA EL 2026-09-06. Esta prueba exigia que la ruta llamara a
    `listar_corridas_replay_acotado`, que enumeraba por saltos de indice. La
    intencion era **no exponer un recorrido costoso**, y sigue siendo la misma;
    lo que cambio es cual es hoy la variante barata.

    Al comprimirse la tabla, la enumeracion por saltos dejo de ser barata: se
    midio en 302,3 segundos para devolver una corrida, porque `replay_run_id`
    no es columna de segmentacion de la compresion. La ruta pasa a servirse de
    un catalogo mantenido, y la prueba comprueba eso mismo.
    """

    def test_se_sirve_del_catalogo_y_no_recorre_la_tabla(self) -> None:
        """Ni el agregado exhaustivo ni la enumeracion por saltos se exponen."""
        with patch("backend.app.catalogo_corridas.listar", return_value=[]) as catalogo:
            with patch("backend.app.listar_corridas_replay_acotado") as recorrido:
                racing_replay_runs(9939)

        catalogo.assert_called_once_with(9939)
        recorrido.assert_not_called()

    def test_una_sesion_sin_corridas_devuelve_lista_vacia_y_no_un_error(self) -> None:
        """La sesion existe; lo que no hay es telemetria replicada."""
        with patch("backend.app.catalogo_corridas.listar", return_value=[]):
            self.assertEqual(racing_replay_runs(10006), [])


class IdentidadDeSesionEnTelemetriaTests(unittest.TestCase):
    def test_extrae_la_clave_del_session_id(self) -> None:
        self.assertEqual(_session_key_de("openf1:session:9947"), 9947)

    def test_un_session_id_ajeno_al_replay_no_produce_una_clave_inventada(self) -> None:
        self.assertIsNone(_session_key_de("mqtt_phase_recalibrated_01"))
        self.assertIsNone(_session_key_de(None))


class CursorFalso:
    """Cursor minimo para inspeccionar la consulta emitida sin abrir la base."""

    def __init__(self) -> None:
        self.sql = ""
        self.parametros: dict | None = None
        self.description = [("driver_number",), ("lap_number",)]

    def execute(self, sql: str, parametros=None) -> None:
        self.sql = sql
        self.parametros = parametros

    def fetchall(self) -> list[tuple]:
        return [(1, 5)]

    def __enter__(self) -> "CursorFalso":
        return self

    def __exit__(self, *args) -> bool:
        return False


class ConexionFalsa:
    def __init__(self, cursor: CursorFalso) -> None:
        self._cursor = cursor

    def cursor(self) -> CursorFalso:
        return self._cursor

    def __enter__(self) -> "ConexionFalsa":
        return self

    def __exit__(self, *args) -> bool:
        return False


class AnalisisVigenteTests(unittest.TestCase):
    def test_el_analisis_se_lee_de_una_sola_version(self) -> None:
        """Una corrida puede tener el resultado de varias versiones del analizador.

        La clave unica de `session_analysis_runs` incluye `analyzer_version`, que es
        justamente lo que permite conservar el analisis anterior al parametrizar.
        Filtrar solo por sesion y corrida devolvia las vueltas de todas esas
        versiones mezcladas: 827 vueltas se leian como 1.654.
        """
        cursor = CursorFalso()
        with patch("backend.db.obtener_conexion", return_value=ConexionFalsa(cursor)):
            obtener_analisis_vueltas(9947, "d7_silverstone_full_001")

        self.assertIn("r.analysis_run_id = (", cursor.sql)
        self.assertIn("ORDER BY generated_at_utc DESC", cursor.sql)
        self.assertEqual(cursor.parametros["session_key"], 9947)
        self.assertEqual(cursor.parametros["replay_run_id"], "d7_silverstone_full_001")


if __name__ == "__main__":
    unittest.main()
