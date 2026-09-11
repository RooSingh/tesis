"""Pruebas del catalogo externo de reglajes."""

from __future__ import annotations

import unittest

from backend import catalogo_reglajes


class CatalogoReglajesTests(unittest.TestCase):
    def test_spa_tiene_solo_los_valores_respaldados(self) -> None:
        referencia = catalogo_reglajes.referencia_de("spa")
        self.assertEqual(referencia["valores"], {
            "aleron_delantero": 3,
            "aleron_trasero": 0,
        })
        self.assertEqual(
            referencia["fuente"]["clave_bibliografica"],
            "simracingsetup_f1_25_spa")
        self.assertIn("no demuestra", referencia["alcance"])

    def test_un_circuito_sin_fuente_no_recibe_valores_inventados(self) -> None:
        self.assertIsNone(catalogo_reglajes.referencia_de("spielberg"))

    def test_quien_llama_no_puede_mutar_el_catalogo(self) -> None:
        referencia = catalogo_reglajes.referencia_de("spa")
        referencia["valores"]["aleron_delantero"] = 99
        self.assertEqual(
            catalogo_reglajes.referencia_de("spa")["valores"]["aleron_delantero"], 3)


if __name__ == "__main__":
    unittest.main()
