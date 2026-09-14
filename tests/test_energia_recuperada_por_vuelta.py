"""La energia del ERS por vuelta: que vehiculo, que vuelta y que criterio.

Lo que aqui se fija no son las cifras de una carrera ---eso lo comprueba la
corrida sobre la captura--- sino tres reglas que ya fallaron una vez:

- el vehiculo propio es **el mas frecuente** de las cabeceras, no el primero;
- los dos canales de recuperacion **no se suman en silencio**: la suma es una
  columna mas, al lado de cada canal;
- con un contador reiniciado al final de la vuelta, el **ultimo** paquete y el
  **maximo** dan cosas distintas, y se informan los dos.
"""

import unittest

from scripts.energia_recuperada_por_vuelta import (
    energia_por_vuelta,
    vehiculo_mas_frecuente,
)

PROPIO = 1


def vuelta(n: int) -> dict:
    vehiculos = [{"current_lap_num": 99}, {"current_lap_num": n}]
    return {"decodificado": True, "packet_id": 2, "vehiculos": vehiculos}


def estado(k: float, h: float, desplegado: float, carga: float = 2e6) -> dict:
    ajeno = {"ers_harvested_this_lap_mguk_j": 9e9, "ers_harvested_this_lap_mguh_j": 9e9,
             "ers_deployed_this_lap_j": 9e9, "ers_store_energy_j": 0.0}
    propio = {"ers_harvested_this_lap_mguk_j": k, "ers_harvested_this_lap_mguh_j": h,
              "ers_deployed_this_lap_j": desplegado, "ers_store_energy_j": carga}
    return {"decodificado": True, "packet_id": 7, "vehiculos": [ajeno, propio]}


class VehiculoPropio(unittest.TestCase):

    def test_gana_el_mas_frecuente_y_no_el_primero(self):
        """La carrera 2 de Spa empieza con cabeceras que dicen 0."""
        propio, recuento = vehiculo_mas_frecuente([0] * 7 + [19] * 100 + [0] * 7)

        self.assertEqual(propio, 19)
        self.assertEqual(recuento[0], 14)


class EnergiaPorVuelta(unittest.TestCase):

    def test_separa_los_canales_y_la_suma_es_una_columna_aparte(self):
        vueltas = energia_por_vuelta([vuelta(3), estado(2_000_000, 3_000_000, 1_500_000)],
                                     PROPIO)

        e = vueltas[3]
        self.assertEqual(e.ultimo["mguk"], 2_000_000)
        self.assertEqual(e.ultimo["mguh"], 3_000_000)
        self.assertEqual(e.ultimo["kh"], 5_000_000)

    def test_lee_el_vehiculo_pedido_y_no_otro(self):
        vueltas = energia_por_vuelta([vuelta(1), estado(1, 2, 3)], PROPIO)

        self.assertEqual(vueltas[1].ultimo["mguk"], 1)

    def test_el_estado_va_a_la_vuelta_vigente(self):
        paquetes = [vuelta(1), estado(100, 0, 0), vuelta(2), estado(50, 0, 0)]

        vueltas = energia_por_vuelta(paquetes, PROPIO)

        self.assertEqual(vueltas[1].ultimo["mguk"], 100)
        self.assertEqual(vueltas[2].ultimo["mguk"], 50)

    def test_un_estado_anterior_a_la_primera_vuelta_se_descarta(self):
        vueltas = energia_por_vuelta([estado(7, 7, 7), vuelta(1), estado(1, 1, 1)], PROPIO)

        self.assertEqual(vueltas[1].paquetes, 1)

    def test_contador_reiniciado_al_final_separa_ultimo_de_maximo(self):
        """Lo que pasa en la ultima vuelta de Spa: el ultimo paquete viene en cero."""
        paquetes = [vuelta(22), estado(2_000_000, 2_100_000, 2_650_000),
                    estado(0, 0, 1_000)]

        e = energia_por_vuelta(paquetes, PROPIO)[22]

        self.assertEqual(e.ultimo["desplegado"], 1_000)
        self.assertEqual(e.maximo["desplegado"], 2_650_000)
        self.assertEqual(e.maximo["kh"], 4_100_000)

    def test_carga_minima_en_porcentaje_de_la_franja_de_cuatro_megajulios(self):
        paquetes = [vuelta(1), estado(0, 0, 0, carga=3_000_000),
                    estado(0, 0, 0, carga=1_000_000), estado(0, 0, 0, carga=2_000_000)]

        e = energia_por_vuelta(paquetes, PROPIO)[1]

        self.assertAlmostEqual(e.carga_min_pct, 25.0)


if __name__ == "__main__":
    unittest.main()
