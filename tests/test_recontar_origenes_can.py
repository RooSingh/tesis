"""El recuento de origenes del bus y el emparejado de ecos.

Lo que aqui se fija no es el total de una captura concreta ---eso lo comprueba
la corrida--- sino la **regla de emparejado**: una trama del eco solo cuenta
como gemela si encuentra en el origen una trama con el mismo identificador, los
mismos bytes y dentro de la tolerancia, y **cada trama del origen se consume una
sola vez**. Sin esa ultima condicion un solo origen podria explicar diez ecos y
el recuento dejaria de significar nada.
"""

import unittest

from backend.can_capture import Trama
from scripts.recontar_origenes_can import contar_por_origen, emparejar_eco

MS = 1_000_000


def trama(ms: float, identificador: int, bus: int, datos: bytes = b"\x01\x02") -> Trama:
    return Trama(instante_ns=int(ms * MS), identificador=identificador,
                 bus=bus, datos=datos)


class ContarPorOrigen(unittest.TestCase):

    def test_cuenta_tramas_e_identificadores_distintos_por_origen(self):
        tramas = [
            trama(0, 0x100, 0), trama(1, 0x100, 0), trama(2, 0x200, 0),
            trama(3, 0x100, 130),
        ]

        recuento = contar_por_origen(tramas)

        self.assertEqual(recuento[0].tramas, 3)
        self.assertEqual(recuento[0].identificadores, {0x100: 2, 0x200: 1})
        self.assertEqual(recuento[130].tramas, 1)


class EmparejarEco(unittest.TestCase):

    def test_una_gemela_exacta_se_empareja(self):
        origen = [trama(0, 0x100, 0)]
        eco = [trama(1, 0x100, 130)]

        self.assertEqual(emparejar_eco(origen, eco, tolerancia_ms=5), 1)

    def test_cada_trama_del_origen_se_consume_una_sola_vez(self):
        """Dos ecos y un solo origen: una gemela, no dos."""
        origen = [trama(0, 0x100, 0)]
        eco = [trama(1, 0x100, 130), trama(2, 0x100, 130)]

        self.assertEqual(emparejar_eco(origen, eco, tolerancia_ms=5), 1)

    def test_fuera_de_tolerancia_no_es_gemela(self):
        origen = [trama(0, 0x100, 0)]
        eco = [trama(5.1, 0x100, 130)]

        self.assertEqual(emparejar_eco(origen, eco, tolerancia_ms=5), 0)

    def test_mismos_bytes_o_no_hay_gemela(self):
        origen = [trama(0, 0x100, 0, b"\xaa")]
        eco = [trama(1, 0x100, 130, b"\xbb")]

        self.assertEqual(emparejar_eco(origen, eco, tolerancia_ms=5), 0)

    def test_la_gemela_puede_venir_antes_que_el_eco(self):
        """El eco no siempre llega despues: la tolerancia es de valor absoluto."""
        origen = [trama(3, 0x100, 0)]
        eco = [trama(0, 0x100, 130)]

        self.assertEqual(emparejar_eco(origen, eco, tolerancia_ms=5), 1)

    def test_elige_la_mas_cercana_y_no_la_primera(self):
        """Con dos candidatas en tolerancia, gastar la lejana perderia un par.

        El eco de 0 ms y el de 9 ms solo se emparejan los dos si el primero toma
        la de 0 ms. Si tomara la de 6 ms, el segundo se quedaria sin gemela.
        """
        origen = [trama(0, 0x100, 0), trama(6, 0x100, 0)]
        eco = [trama(0.5, 0x100, 130), trama(9, 0x100, 130)]

        self.assertEqual(emparejar_eco(origen, eco, tolerancia_ms=5), 2)


if __name__ == "__main__":
    unittest.main()
