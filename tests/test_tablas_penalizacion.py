# -*- coding: utf-8 -*-
"""Las tablas de penalizacion se concilian contra la especificacion archivada.

No se comprueba que digan lo que uno recuerda, sino que tengan **los mismos
identificadores que el documento**. La tabla de superficies ya se escribio de
memoria una vez y quedo corrida un lugar: declaraba piedra donde la
especificacion dice cesped.
"""

import re
import unittest
from pathlib import Path

from backend import f1_udp

SPEC = Path(__file__).resolve().parents[1] / "datasets" / "f1_25" / "spec" / "spec.txt"


def _tabla_del_spec(desde: str, hasta: str) -> dict[int, str]:
    texto = SPEC.read_text(encoding="utf-8", errors="replace")
    i = texto.index(desde)
    j = texto.index(hasta, i)
    filas = {}
    for linea in texto[i:j].split("\n"):
        m = re.match(r"\s*(\d+)\s+(\S.*?)\s*$", linea)
        if m:
            filas[int(m.group(1))] = m.group(2)
    return filas


@unittest.skipUnless(SPEC.exists(), "la especificacion no esta archivada")
class ConciliacionConLaEspecificacion(unittest.TestCase):

    def test_las_penalizaciones_son_las_declaradas(self):
        spec = _tabla_del_spec("Penalty types", "Infringement types")
        self.assertEqual(sorted(f1_udp.TIPOS_PENALIZACION), sorted(spec))
        self.assertEqual(len(f1_udp.TIPOS_PENALIZACION), 18)

    def test_las_infracciones_son_las_declaradas(self):
        spec = _tabla_del_spec("Infringement types", "Legal Notice")
        self.assertEqual(sorted(f1_udp.TIPOS_INFRACCION), sorted(spec))
        self.assertEqual(len(f1_udp.TIPOS_INFRACCION), 55)

    def test_los_identificadores_son_contiguos_desde_cero(self):
        """Un hueco delataria una fila salteada al transcribir."""

        for tabla in (f1_udp.TIPOS_PENALIZACION, f1_udp.TIPOS_INFRACCION):
            self.assertEqual(sorted(tabla), list(range(len(tabla))))

    def test_ninguna_etiqueta_esta_vacia_ni_repetida(self):
        for tabla in (f1_udp.TIPOS_PENALIZACION, f1_udp.TIPOS_INFRACCION):
            self.assertTrue(all(tabla.values()))
            self.assertEqual(len(set(tabla.values())), len(tabla))


class TraduccionEnElEvento(unittest.TestCase):

    def test_las_dos_colisiones_se_distinguen(self):
        """El juego separa colision grande de colision chica y se conserva."""

        self.assertEqual(f1_udp.TIPOS_INFRACCION[3], "colision-grande")
        self.assertEqual(f1_udp.TIPOS_INFRACCION[4], "colision-chica")

    def test_la_penalizacion_de_tiempo_no_se_confunde_con_la_advertencia(self):
        """Una cuesta segundos y la otra no: mezclarlas cambia el resultado."""

        self.assertEqual(f1_udp.TIPOS_PENALIZACION[4], "penalizacion-de-tiempo")
        self.assertEqual(f1_udp.TIPOS_PENALIZACION[5], "advertencia")


if __name__ == "__main__":
    unittest.main()
