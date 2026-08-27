"""Pruebas de la derivacion de ventanas de vuelta, sin base de datos.

`calcular_ventanas_vueltas` es una funcion pura precisamente para poder
verificarla aqui: la regla que decide a que vuelta pertenece una muestra es una
decision metodologica y debe quedar auditable, no enterrada en una consulta SQL.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from backend.db import calcular_ventanas_vueltas, identificadores_openf1


BASE = datetime(2025, 7, 6, 14, 0, 0, tzinfo=timezone.utc)


def vuelta(numero: int, offset_segundos: float, duracion: float | None) -> dict:
    return {
        "lap_number": numero,
        "date_start": BASE + timedelta(seconds=offset_segundos),
        "lap_duration_seconds": duracion,
    }


class VentanasContiguasTests(unittest.TestCase):
    def test_el_fin_es_el_inicio_de_la_vuelta_siguiente(self) -> None:
        ventanas = calcular_ventanas_vueltas([
            vuelta(1, 0, 90.0),
            vuelta(2, 90, 91.0),
            vuelta(3, 181, 92.0),
        ])

        self.assertEqual(ventanas[0]["fin"], ventanas[1]["inicio"])
        self.assertEqual(ventanas[1]["fin"], ventanas[2]["inicio"])
        self.assertFalse(ventanas[0]["fin_estimado"])
        self.assertTrue(all(v["completa"] for v in ventanas))

    def test_la_duracion_declarada_no_manda_cuando_contradice_al_siguiente(self) -> None:
        """Este es el caso real que motivo la regla.

        En Silverstone `9947`, 25 de 827 vueltas presentan una discrepancia mayor a
        medio segundo entre `date_start + lap_duration_seconds` y el inicio de la
        vuelta siguiente, con un maximo de 11,802 segundos. Cerrar por duracion
        dejaria ese intervalo sin asignar a ninguna vuelta.
        """
        # La vuelta 1 declara 90 s pero la siguiente arranca 11,8 s despues.
        ventanas = calcular_ventanas_vueltas([
            vuelta(1, 0, 90.0),
            vuelta(2, 101.802, 92.0),
        ])

        self.assertEqual(ventanas[0]["fin"], BASE + timedelta(seconds=101.802))
        self.assertNotEqual(ventanas[0]["fin"], BASE + timedelta(seconds=90.0))
        # Sin huecos: el fin de una es exactamente el inicio de la otra.
        self.assertEqual(ventanas[0]["fin"], ventanas[1]["inicio"])

    def test_no_quedan_huecos_ni_solapamientos(self) -> None:
        ventanas = calcular_ventanas_vueltas([
            vuelta(1, 0, 90.0), vuelta(2, 95, 91.0), vuelta(3, 200, 92.0), vuelta(4, 260, 93.0),
        ])

        for anterior, siguiente in zip(ventanas, ventanas[1:]):
            self.assertEqual(anterior["fin"], siguiente["inicio"])


class VentanasConExcepcionTests(unittest.TestCase):
    def test_la_ultima_vuelta_se_cierra_con_la_duracion_y_se_marca_estimada(self) -> None:
        """Decision metodologica acordada: se estima, y se declara que se estimo."""
        ventanas = calcular_ventanas_vueltas([vuelta(1, 0, 90.0), vuelta(2, 90, 91.5)])

        ultima = ventanas[-1]
        self.assertEqual(ultima["fin"], BASE + timedelta(seconds=181.5))
        self.assertTrue(ultima["fin_estimado"])
        self.assertTrue(ultima["completa"])

    def test_un_salto_en_la_numeracion_no_absorbe_la_vuelta_faltante(self) -> None:
        """Si falta la vuelta 2, la 1 no puede extenderse hasta el inicio de la 3.

        Hacerlo le atribuiria a la vuelta 1 toda la telemetria de una vuelta que no
        se registro, inflando su recorte sin ninguna advertencia.
        """
        ventanas = calcular_ventanas_vueltas([vuelta(1, 0, 90.0), vuelta(3, 200, 92.0)])

        self.assertEqual(ventanas[0]["fin"], BASE + timedelta(seconds=90.0))
        self.assertTrue(ventanas[0]["fin_estimado"])
        self.assertLess(ventanas[0]["fin"], ventanas[1]["inicio"])

    def test_sin_duracion_ni_siguiente_la_ventana_queda_incompleta(self) -> None:
        """No se inventa un limite: se declara que no se pudo determinar.

        Cinco vueltas de Silverstone carecen de `lap_duration_seconds`.
        """
        ventanas = calcular_ventanas_vueltas([vuelta(1, 0, None)])

        self.assertIsNone(ventanas[0]["fin"])
        self.assertFalse(ventanas[0]["completa"])
        self.assertFalse(ventanas[0]["fin_estimado"])

    def test_una_vuelta_sin_inicio_no_produce_ventana_utilizable(self) -> None:
        ventanas = calcular_ventanas_vueltas([
            {"lap_number": 1, "date_start": None, "lap_duration_seconds": 90.0},
        ])

        self.assertFalse(ventanas[0]["completa"])

    def test_lista_vacia(self) -> None:
        self.assertEqual(calcular_ventanas_vueltas([]), [])


class IdentificadoresTests(unittest.TestCase):
    def test_coinciden_con_los_que_emite_el_adaptador_openf1(self) -> None:
        """Si divergieran, el filtro no encontraria ninguna fila y no habria error."""
        session_id, driver_id = identificadores_openf1(9947, 1)

        self.assertEqual(session_id, "openf1:session:9947")
        self.assertEqual(driver_id, "openf1:driver:1")


if __name__ == "__main__":
    unittest.main()
