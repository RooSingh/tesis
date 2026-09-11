# -*- coding: utf-8 -*-
"""Una captura puede atravesar varias sesiones, y cada una se nombra.

EL DEFECTO QUE ESTO CUIDA. El juego le da otro `session_uid` a cada sesion nueva
y el capturador sigue escribiendo el mismo archivo. La procedencia se derivaba
una vez por captura, de modo que solo una sesion de cada archivo quedaba
nombrada. Medido el 2026-09-11: de las 222 sesiones de F1 25 del catalogo, 170
sin procedencia; la carrera de Red Bull Ring con Alpine contra McLaren era la
ultima de ocho sesiones de su captura y se veia como «Vehículo 18».
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import procedencia_sesiones as ps
from scripts.capturar_f1_25 import SesionesDeLaCaptura


COLAPINTO = {"indice": 18, "nombre": "COLAPINTO", "numero": 43, "equipo": "Alpine",
             "equipo_id": 5, "es_ia": False, "plataforma": "PlayStation"}


def _procedencia(uid, tipo, parrilla=None, disponible=True):
    return {"disponible": disponible, "session_uid": uid, "tipo_sesion": tipo,
            "circuito": "spielberg", "circuito_id": 17, "longitud_declarada_m": 4323,
            "modo_juego": "pantalla-dividida", "clima": "despejado",
            "temperatura_pista_c": 34, "temperatura_aire_c": 23,
            "vueltas_totales": 5, "dificultad_ia": 10,
            "parrilla": parrilla, "vehiculos_en_carrera_al_leer": 20}


def _meta_con_varias_sesiones():
    """Una captura cuya procedencia principal nombra la primera sesion."""
    return {
        "archivo": "20260902_1848_spielberg_carrera_dos-conductores.f1raw",
        "sha256": "abc",
        "inicio_utc": "2026-09-02T21:48:00+00:00",
        "duracion_s": 800.0,
        "procedencia": _procedencia(111, "carrera"),
        "sesiones_en_la_captura": [
            {"session_uid": 111, "desde_s": 0.0, "hasta_s": 5.0, "datagramas": 250,
             "procedencia": _procedencia(111, "carrera")},
            {"session_uid": 222, "desde_s": 376.5, "hasta_s": 797.4, "datagramas": 67411,
             "procedencia": _procedencia(222, "carrera", parrilla=[COLAPINTO])},
            {"session_uid": 333, "desde_s": 5.0, "hasta_s": 9.0, "datagramas": 20,
             "procedencia": {"disponible": False, "motivo": "sin paquete de sesion"}},
        ],
    }


class IndicePorSesionTests(unittest.TestCase):

    def setUp(self) -> None:
        ps._CACHE = None
        self.dir = tempfile.TemporaryDirectory()
        self.ruta = Path(self.dir.name)
        self.parche = patch.object(ps, "DIRECTORIO", self.ruta)
        self.parche.start()

    def tearDown(self) -> None:
        self.parche.stop()
        self.dir.cleanup()
        ps._CACHE = None

    def _escribir(self, datos, nombre="a.meta.json"):
        (self.ruta / nombre).write_text(json.dumps(datos), encoding="utf-8")

    def test_cada_sesion_de_la_captura_tiene_procedencia(self) -> None:
        self._escribir(_meta_con_varias_sesiones())
        indice = ps.indice()
        self.assertIn("f1_25:session:111", indice)
        self.assertIn("f1_25:session:222", indice,
                      "la ultima sesion de la captura quedo sin nombre")

    def test_una_sesion_que_no_declaro_su_tipo_no_se_inventa(self) -> None:
        self._escribir(_meta_con_varias_sesiones())
        self.assertNotIn("f1_25:session:333", ps.indice())

    def test_la_parrilla_es_la_de_esa_sesion(self) -> None:
        self._escribir(_meta_con_varias_sesiones())
        parrilla = ps.parrilla_de("f1_25:session:222")
        self.assertEqual(parrilla["vehiculos"][0]["nombre"], "COLAPINTO")
        self.assertIsNone(ps.parrilla_de("f1_25:session:111"),
                          "la sesion 111 no declaro parrilla y recibio la de otra")

    def test_la_duracion_es_la_de_la_sesion_y_no_la_del_archivo(self) -> None:
        self._escribir(_meta_con_varias_sesiones())
        ficha = ps.de("f1_25:session:222")
        self.assertAlmostEqual(ficha["duracion_capturada_s"], 420.9, places=1)
        self.assertEqual(ficha["tramo_de_la_captura_s"], [376.5, 797.4])

    def test_la_principal_se_sigue_leyendo_como_antes(self) -> None:
        self._escribir(_meta_con_varias_sesiones())
        ficha = ps.de("f1_25:session:111")
        self.assertEqual(ficha["duracion_capturada_s"], 800.0)
        self.assertNotIn("tramo_de_la_captura_s", ficha)

    def test_la_parrilla_se_ata_con_la_ventana_del_archivo(self) -> None:
        """Las filas entran a la base con el reloj de la captura, no del tramo."""
        self._escribir(_meta_con_varias_sesiones())
        captura = ps.candidatas_de_parrilla("f1_25:session:222")[0]["captura"]
        self.assertEqual(captura["inicio_utc"], "2026-09-02T21:48:00+00:00")
        self.assertEqual(captura["duracion_s"], 800.0)
        self.assertEqual(captura["sha256"], "abc")

    def test_un_metadato_sin_la_lista_declara_lo_mismo_que_antes(self) -> None:
        datos = _meta_con_varias_sesiones()
        datos.pop("sesiones_en_la_captura")
        self._escribir(datos)
        self.assertEqual(list(ps.indice()), ["f1_25:session:111"])


# ---------------------------------------------------------------------------
# El acumulador que usan el capturador y la rederivacion
# ---------------------------------------------------------------------------

def _cabecera(uid, marco=5):
    return {"session_uid": uid, "game_major_version": 1, "game_minor_version": 24,
            "frame_identifier": marco, "secondary_player_car_index": 19}


def _sesion(tipo):
    return {"track_id": 17, "track_length_m": 4323, "session_type": tipo,
            "game_mode": 6, "weather": 0, "track_temperature_c": 34,
            "air_temperature_c": 23, "total_laps": 5, "ai_difficulty": 10,
            "network_game": 0, "equal_car_performance": 0,
            "sector2_lap_distance_start_m": 1500.0,
            "sector3_lap_distance_start_m": 3000.0}


def _participantes(uid, nombre):
    return {"paquete": "participants", "cabecera": _cabecera(uid), "num_active_cars": 20,
            "vehiculos": [{"name": nombre, "race_number": 43, "team": "Alpine",
                           "team_id": 5, "ai_controlled": 0, "platform": 1}]}


class SesionesDeLaCapturaTests(unittest.TestCase):

    def test_separa_las_sesiones_por_su_identificador(self) -> None:
        s = SesionesDeLaCaptura()
        s.anotar(111, 0, {"paquete": "session", "cabecera": _cabecera(111),
                          "sesion": _sesion(15)})
        s.anotar(222, 1_000_000, {"paquete": "session", "cabecera": _cabecera(222),
                                  "sesion": _sesion(13)})
        s.anotar(222, 2_000_000, _participantes(222, "COLAPINTO"))
        resumen = s.resumen()
        self.assertEqual([r["session_uid"] for r in resumen], [111, 222])
        self.assertEqual([r["procedencia"]["tipo_sesion_id"] for r in resumen], [15, 13])
        self.assertEqual(resumen[1]["procedencia"]["session_uid"], 222)

    def test_la_parrilla_no_se_pasa_de_una_sesion_a_otra(self) -> None:
        s = SesionesDeLaCaptura()
        s.anotar(111, 0, {"paquete": "session", "cabecera": _cabecera(111),
                          "sesion": _sesion(15)})
        s.anotar(222, 1_000_000, {"paquete": "session", "cabecera": _cabecera(222),
                                  "sesion": _sesion(15)})
        s.anotar(222, 2_000_000, _participantes(222, "COLAPINTO"))
        primera, segunda = s.resumen()
        self.assertIsNone(primera["procedencia"]["parrilla"])
        self.assertEqual(segunda["procedencia"]["parrilla"][0]["nombre"], "COLAPINTO")

    def test_la_cabecera_sin_llenar_no_es_una_sesion(self) -> None:
        s = SesionesDeLaCaptura()
        s.anotar(0, 0, None)
        self.assertEqual(s.resumen(), [])

    def test_cuenta_el_tramo_aunque_no_decodifique_el_paquete(self) -> None:
        """La rederivacion lee solo la cabecera de los paquetes que no usa."""
        s = SesionesDeLaCaptura()
        s.anotar(111, 1_000_000, None)
        s.anotar(111, 3_500_000, {"paquete": "session", "cabecera": _cabecera(111),
                                  "sesion": _sesion(15)})
        s.anotar(111, 9_000_000, None)
        r = s.resumen()[0]
        self.assertEqual((r["desde_s"], r["hasta_s"], r["datagramas"]), (1.0, 9.0, 3))
        self.assertTrue(r["procedencia"]["disponible"])

    def test_una_sesion_sin_paquete_de_sesion_se_declara_no_disponible(self) -> None:
        s = SesionesDeLaCaptura()
        s.anotar(111, 0, None)
        self.assertFalse(s.resumen()[0]["procedencia"]["disponible"])


if __name__ == "__main__":
    unittest.main()
