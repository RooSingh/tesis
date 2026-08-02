"""Pruebas guiadas del escenario demostrativo de 60 segundos."""

from __future__ import annotations

import unittest

from telemetry_generator.main import crear_estado_inicial
from telemetry_generator.signals import aplicar_escenario_demostrativo, actualizar_estado_basico


class EscenarioDemostrativoTests(unittest.TestCase):
    """Verifica una fase del escenario por vez."""

    def test_recta_inicial(self) -> None:
        """Comprueba el estado esperado al comenzar la secuencia."""

        estado = crear_estado_inicial()
        aplicar_escenario_demostrativo(estado, 0)

        self.assertEqual(estado.track_segment_id, "demo_straight_entry")
        self.assertIsNone(estado.curve_id)
        self.assertAlmostEqual(estado.gas_pedal, 65.0)
        self.assertAlmostEqual(estado.brake_intensity, 0.0)
        self.assertFalse(estado.brake_pressed)

    def test_transiciones_de_fase(self) -> None:
        """Comprueba las transiciones representativas despues de la recta inicial."""

        casos = (
            (17_000, "demo_braking_zone", None, 42.5, 75.0, 1.0, True),
            (20_000, "demo_corner_entry", "demo_curve_01", 0.0, 35.0, 2.0, True),
            (27_000, "demo_corner_apex", "demo_curve_01", 12.0, 0.0, 18.0, False),
            (34_000, "demo_corner_exit", "demo_curve_01", 25.0, 0.0, 22.0, False),
            (44_000, "demo_straight_exit", None, 75.0, 0.0, -3.0, False),
        )

        for tiempo_ms, segmento, curva, acelerador, freno, direccion, freno_activo in casos:
            with self.subTest(tiempo_ms=tiempo_ms):
                estado = crear_estado_inicial()
                aplicar_escenario_demostrativo(estado, tiempo_ms)

                self.assertEqual(estado.track_segment_id, segmento)
                self.assertEqual(estado.curve_id, curva)
                self.assertAlmostEqual(estado.gas_pedal, acelerador)
                self.assertAlmostEqual(estado.brake_intensity, freno)
                self.assertAlmostEqual(estado.steer_angle, direccion)
                self.assertEqual(estado.brake_pressed, freno_activo)

    def test_la_intensidad_modula_la_desaceleracion(self) -> None:
        """Comprueba que el freno interno afecte la aceleracion longitudinal."""

        estado = crear_estado_inicial()
        estado.gas_pedal = 0.0
        estado.brake_intensity = 50.0

        actualizar_estado_basico(estado)

        self.assertAlmostEqual(estado.accel_x, -2.25)

    def test_el_escenario_finaliza(self) -> None:
        """Comprueba que la secuencia no se reinicie a los 60 segundos."""

        with self.assertRaises(ValueError):
            aplicar_escenario_demostrativo(crear_estado_inicial(), 60_000)


if __name__ == "__main__":
    unittest.main()
