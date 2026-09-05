# -*- coding: utf-8 -*-
"""El recolector respeta el techo por minuto que el proveedor declara.

El proveedor publica dos techos para el plan gratuito, no uno: tres solicitudes
por segundo y treinta por minuto. El recolector cumplia el primero ---media
segundo de espera entre consultas--- y por eso mismo violaba el segundo, porque
sostenido ese ritmo son ciento veinte por minuto.
"""

import time
import unittest
from unittest import mock

from scripts import download_openf1_session_telemetry as recolector


class TechoPorMinuto(unittest.TestCase):

    def setUp(self):
        recolector._ventana.clear()

    def tearDown(self):
        recolector._ventana.clear()

    def test_las_primeras_treinta_no_esperan(self):
        """Dentro del techo no se introduce ninguna demora."""

        with mock.patch.object(time, "sleep") as dormir:
            for _ in range(recolector.LIMITE_POR_MINUTO):
                recolector._esperar_turno()
        dormir.assert_not_called()
        self.assertEqual(len(recolector._ventana), recolector.LIMITE_POR_MINUTO)

    def test_la_solicitud_treinta_y_uno_espera(self):
        """Al llenarse la ventana, la siguiente aguarda a que venza la mas vieja."""

        dormidas = []

        def falsa_espera(segundos):
            # Se simula el paso del tiempo corriendo la marca mas antigua fuera
            # de la ventana, que es lo que ocurriria si se hubiera dormido.
            dormidas.append(segundos)
            recolector._ventana[:] = [m - segundos for m in recolector._ventana]

        for _ in range(recolector.LIMITE_POR_MINUTO):
            recolector._esperar_turno()
        with mock.patch.object(time, "sleep", falsa_espera):
            recolector._esperar_turno()

        self.assertEqual(len(dormidas), 1)
        self.assertGreater(dormidas[0], 0)
        self.assertLessEqual(dormidas[0], recolector.VENTANA_S + 0.1)

    def test_lo_que_salio_de_la_ventana_no_cuenta(self):
        """Una consulta de hace mas de un minuto ya no ocupa lugar."""

        viejas = time.monotonic() - recolector.VENTANA_S - 1
        recolector._ventana[:] = [viejas] * recolector.LIMITE_POR_MINUTO
        with mock.patch.object(time, "sleep") as dormir:
            recolector._esperar_turno()
        dormir.assert_not_called()
        self.assertEqual(len(recolector._ventana), 1)

    def test_los_dos_techos_son_los_declarados(self):
        """Las cifras del codigo son las que el informe cita del proveedor."""

        self.assertEqual(recolector.LIMITE_POR_MINUTO, 30)
        self.assertEqual(recolector.VENTANA_S, 60.0)
        # Media segundo entre consultas son dos por segundo, bajo el techo de tres.
        self.assertLessEqual(1 / recolector.ESPERA_ENTRE_CONSULTAS_S, 3)


if __name__ == "__main__":
    unittest.main()
