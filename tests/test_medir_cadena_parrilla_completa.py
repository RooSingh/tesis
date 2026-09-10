from __future__ import annotations

import sys
import unittest
from pathlib import Path

from scripts.medir_cadena_parrilla_completa import _comando_capturador


class ComandoCapturadorTests(unittest.TestCase):
    def test_propaga_los_pilotos_y_aisla_el_archivo_de_eleccion(self) -> None:
        comando = _comando_capturador(
            20778,
            "prueba_123",
            Path("logs/capturas_de_prueba"),
            "Norris,Russell,Hamilton",
        )

        self.assertEqual(comando[0], sys.executable)
        self.assertIn("--parrilla-completa", comando)
        self.assertEqual(
            comando[comando.index("--pilotos") + 1],
            "Norris,Russell,Hamilton",
        )
        archivo = comando[comando.index("--archivo-eleccion") + 1]
        self.assertEqual(
            archivo,
            "logs/capturas_de_prueba/.prueba_123.pilotos.json",
        )

    def test_sin_pilotos_no_hereda_la_eleccion_de_produccion(self) -> None:
        comando = _comando_capturador(
            20778,
            "prueba_456",
            Path("logs/capturas_de_prueba"),
            None,
        )

        self.assertNotIn("--pilotos", comando)
        archivo = comando[comando.index("--archivo-eleccion") + 1]
        self.assertIn("prueba_456", archivo)


if __name__ == "__main__":
    unittest.main()
