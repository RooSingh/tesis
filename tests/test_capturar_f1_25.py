"""Pruebas del capturador: derivacion de procedencia desde el propio flujo.

No abren sockets ni tocan la red: ejercitan la parte que convierte los paquetes
decodificados en la procedencia de la captura, que es donde esta la logica.
"""

from __future__ import annotations

import unittest

from backend import f1_udp
from scripts.capturar_f1_25 import AYUDAS, derivar_procedencia
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

        p = derivar_procedencia(None, None)
        self.assertFalse(p["disponible"])
        self.assertIn("motivo", p)

    def test_traduce_el_identificador_de_circuito(self):
        p = derivar_procedencia(_sesion(track_id=7), None)
        self.assertEqual(p["circuito"], "Silverstone")
        self.assertEqual(p["circuito_id"], 7)

    def test_un_circuito_no_catalogado_no_rompe_la_derivacion(self):
        """Conserva el identificador aunque no tenga nombre conocido."""

        p = derivar_procedencia(_sesion(track_id=99), None)
        self.assertEqual(p["circuito"], "desconocido")
        self.assertEqual(p["circuito_id"], 99)

    def test_detecta_que_no_hay_ninguna_ayuda_activa(self):
        sesion = _sesion(**{n: v for n, v in AYUDAS.items()})
        p = derivar_procedencia(sesion, {"traction_control": 0, "anti_lock_brakes": 0})
        self.assertTrue(p["sin_ayudas"])
        self.assertEqual(p["ayudas_activas"], [])

    def test_detecta_una_ayuda_activa_y_la_nombra(self):
        """Es el caso que motivo derivarlas: se habia capturado sin advertirlo."""

        sesion = _sesion(**{n: v for n, v in AYUDAS.items()})
        p = derivar_procedencia(sesion, {"traction_control": 1, "anti_lock_brakes": 0})
        self.assertFalse(p["sin_ayudas"])
        self.assertIn("traction_control", p["ayudas_activas"])

    def test_la_caja_manual_no_se_cuenta_como_ayuda_activa(self):
        """El valor uno es manual; dos y tres si son asistencias."""

        p = derivar_procedencia(_sesion(gearbox_assist=1), None)
        self.assertNotIn("gearbox_assist", p["ayudas_activas"])
        p = derivar_procedencia(_sesion(gearbox_assist=3), None)
        self.assertIn("gearbox_assist", p["ayudas_activas"])

    def test_declara_si_el_dano_estaba_activado(self):
        """En contrarreloj el dano viene apagado y los canales quedan en cero."""

        self.assertEqual(derivar_procedencia(_sesion(car_damage_setting=0), None)["dano_activado"], 0)
        self.assertEqual(derivar_procedencia(_sesion(car_damage_setting=3), None)["dano_activado"], 3)

    def test_arrastra_el_inicio_de_cada_sector(self):
        """Es un dato que la fuente deportiva no entrega."""

        p = derivar_procedencia(_sesion(sector2_lap_distance_start_m=2225.6,
                                        sector3_lap_distance_start_m=5065.0), None)
        self.assertAlmostEqual(p["inicio_sector2_m"], 2225.6, places=1)
        self.assertAlmostEqual(p["inicio_sector3_m"], 5065.0, places=1)

    def test_funciona_sin_paquete_de_estado(self):
        """El estado del vehiculo puede no haber llegado; la sesion alcanza.

        Las ayudas que declara la sesion se derivan igual; las dos que solo
        declara el estado del vehiculo quedan ausentes en lugar de suponerse
        apagadas, que seria afirmar algo que no se observo.
        """

        p = derivar_procedencia(_sesion(track_id=13), None)
        self.assertTrue(p["disponible"])
        self.assertIn("steering_assist", p["ayudas"])
        self.assertNotIn("traction_control", p["ayudas"])
        self.assertNotIn("anti_lock_brakes", p["ayudas"])


if __name__ == "__main__":
    unittest.main()
