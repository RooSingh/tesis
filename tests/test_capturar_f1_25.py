"""Pruebas del capturador: derivacion de procedencia desde el propio flujo.

No abren sockets ni tocan la red: ejercitan la parte que convierte los paquetes
decodificados en la procedencia de la captura, que es donde esta la logica.
"""

from __future__ import annotations

import unittest

from backend import f1_udp
from scripts.capturar_f1_25 import AYUDAS, derivar_procedencia, nombre_derivado
from tests.test_f1_udp import _cabecera


def _sesion(**cambios):
    """Sesion decodificada de un datagrama de relleno, con campos alterados."""

    tamano = f1_udp.PAQUETES[1]["tamano"]
    datos = _cabecera(1) + bytes(tamano - f1_udp.CABECERA_TAMANO)
    sesion = f1_udp.decodificar(datos)["sesion"]
    sesion.update(cambios)
    return sesion


class ProcedenciaDerivadaTests(unittest.TestCase):
    """La procedencia sale del flujo, no de lo que declare el operador."""

    def test_sin_paquete_de_sesion_se_declara_no_disponible(self):
        """No se inventa: se dice que no se pudo derivar y por que."""

        p = derivar_procedencia(None, None, None)
        self.assertFalse(p["disponible"])
        self.assertIn("motivo", p)

    def test_traduce_el_identificador_de_circuito(self):
        p = derivar_procedencia(_sesion(track_id=7), None, None)
        self.assertEqual(p["circuito"], "silverstone")
        self.assertEqual(p["circuito_id"], 7)

    def test_un_circuito_no_catalogado_conserva_su_identificador(self):
        """No se etiqueta como desconocido: se conserva el identificador.

        Un circuito nuevo que el catalogo no tenga sigue siendo trazable, y el
        nombre derivado del archivo lo refleja en lugar de perderlo.
        """

        p = derivar_procedencia(_sesion(track_id=99), None, None)
        self.assertEqual(p["circuito"], "id-99")
        self.assertEqual(p["circuito_id"], 99)

    def test_detecta_que_no_hay_ninguna_ayuda_activa(self):
        sesion = _sesion(**{n: v for n, v in AYUDAS.items()})
        p = derivar_procedencia(sesion, {"traction_control": 0, "anti_lock_brakes": 0}, None)
        self.assertTrue(p["sin_ayudas"])
        self.assertEqual(p["ayudas_activas"], [])

    def test_detecta_una_ayuda_activa_y_la_nombra(self):
        """Es el caso que motivo derivarlas: se habia capturado sin advertirlo."""

        sesion = _sesion(**{n: v for n, v in AYUDAS.items()})
        p = derivar_procedencia(sesion, {"traction_control": 1, "anti_lock_brakes": 0}, None)
        self.assertFalse(p["sin_ayudas"])
        self.assertIn("traction_control", p["ayudas_activas"])

    def test_la_caja_manual_no_se_cuenta_como_ayuda_activa(self):
        """El valor uno es manual; dos y tres si son asistencias."""

        p = derivar_procedencia(_sesion(gearbox_assist=1), None, None)
        self.assertNotIn("gearbox_assist", p["ayudas_activas"])
        p = derivar_procedencia(_sesion(gearbox_assist=3), None, None)
        self.assertIn("gearbox_assist", p["ayudas_activas"])

    def test_declara_si_el_dano_estaba_activado(self):
        """En contrarreloj el dano viene apagado y los canales quedan en cero."""

        self.assertEqual(derivar_procedencia(_sesion(car_damage_setting=0), None, None)["dano_activado"], 0)
        self.assertEqual(derivar_procedencia(_sesion(car_damage_setting=3), None, None)["dano_activado"], 3)

    def test_arrastra_el_inicio_de_cada_sector(self):
        """Es un dato que la fuente deportiva no entrega."""

        p = derivar_procedencia(_sesion(sector2_lap_distance_start_m=2225.6,
                                        sector3_lap_distance_start_m=5065.0), None, None)
        self.assertAlmostEqual(p["inicio_sector2_m"], 2225.6, places=1)
        self.assertAlmostEqual(p["inicio_sector3_m"], 5065.0, places=1)

    def test_funciona_sin_paquete_de_estado(self):
        """El estado del vehiculo puede no haber llegado; la sesion alcanza.

        Las ayudas que declara la sesion se derivan igual; las dos que solo
        declara el estado del vehiculo quedan ausentes en lugar de suponerse
        apagadas, que seria afirmar algo que no se observo.
        """

        p = derivar_procedencia(_sesion(track_id=13), None, None)
        self.assertTrue(p["disponible"])
        self.assertIn("steering_assist", p["ayudas"])
        self.assertNotIn("traction_control", p["ayudas"])
        self.assertNotIn("anti_lock_brakes", p["ayudas"])


if __name__ == "__main__":
    unittest.main()


class NombreDerivadoTests(unittest.TestCase):
    """El nombre del archivo sale del flujo, no de lo que escriba el operador.

    Un nombre derivado no puede estar equivocado respecto del contenido; uno
    escrito a mano si.
    """

    def setUp(self):
        from datetime import datetime
        self.momento = datetime(2026, 8, 29, 17, 12)

    def test_incluye_circuito_y_tipo_de_sesion(self):
        p = derivar_procedencia(_sesion(track_id=7, session_type=10), None, None)
        nombre = nombre_derivado(p, self.momento)
        self.assertIn("silverstone", nombre)
        self.assertIn("carrera", nombre)
        self.assertTrue(nombre.startswith("20260829_1712"))

    def test_marca_cuando_no_hubo_ninguna_ayuda(self):
        sesion = _sesion(track_id=13, session_type=18, **dict(AYUDAS))
        p = derivar_procedencia(sesion, {"traction_control": 0, "anti_lock_brakes": 0}, None)
        self.assertIn("sin-ayudas", nombre_derivado(p, self.momento))

    def test_no_marca_sin_ayudas_si_alguna_quedo_activa(self):
        sesion = _sesion(track_id=13, session_type=18, **dict(AYUDAS))
        p = derivar_procedencia(sesion, {"traction_control": 1, "anti_lock_brakes": 0}, None)
        self.assertNotIn("sin-ayudas", nombre_derivado(p, self.momento))

    def test_marca_la_sesion_de_dos_conductores(self):
        p = derivar_procedencia(_sesion(track_id=7, game_mode=6), None, None)
        self.assertTrue(p["pantalla_dividida"])
        self.assertIn("dos-conductores", nombre_derivado(p, self.momento))

    def test_un_circuito_no_catalogado_conserva_su_identificador(self):
        p = derivar_procedencia(_sesion(track_id=99), None, None)
        self.assertIn("id-99", nombre_derivado(p, self.momento))

    def test_sin_procedencia_el_nombre_lo_declara(self):
        """No inventa un circuito: dice que la sesion no se declaro."""

        nombre = nombre_derivado(derivar_procedencia(None, None, None), self.momento)
        self.assertIn("no-declarada", nombre)


class SegundoConductorTests(unittest.TestCase):
    """La conformidad se asume; solo se registra que la sesion fue de dos."""

    def test_detecta_pantalla_dividida_por_modo_de_juego(self):
        p = derivar_procedencia(_sesion(game_mode=6), None, None)
        self.assertTrue(p["pantalla_dividida"])

    def test_detecta_pantalla_dividida_por_indice_del_segundo(self):
        """Segunda via independiente: la cabecera declara el indice del segundo."""

        cabecera = {"secondary_player_car_index": 1, "session_uid": 1,
                    "game_major_version": 1, "game_minor_version": 24}
        p = derivar_procedencia(_sesion(game_mode=5), None, cabecera)
        self.assertTrue(p["pantalla_dividida"])

    def test_un_solo_conductor_no_se_marca(self):
        cabecera = {"secondary_player_car_index": 255, "session_uid": 1,
                    "game_major_version": 1, "game_minor_version": 24}
        p = derivar_procedencia(_sesion(game_mode=5), None, cabecera)
        self.assertFalse(p["pantalla_dividida"])
