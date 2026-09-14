"""El contraste del panel del juego contra la captura: ancla, lectura y resumen.

Lo que se fija aqui es la parte del metodo que decide que dato se compara con
que lectura: como se convierte el tiempo de vuelta de la pantalla, cuando un
tiempo ancla el cuadro y cuando no (un parcial congelado no debe anclar), que
muestra se toma y como se resumen las diferencias. Las cifras de la carrera las
da la corrida.
"""

import unittest

from scripts.contrastar_panel_contra_dato import (
    COMPONENTES,
    Vuelta,
    anclar,
    filas_de_plantilla,
    muestra_cercana,
    pts_de_showinfo,
    resumir,
    tiempo_de_vuelta_a_segundos,
)


def vueltas_cada_16_ms(desde_s: float, tiempo_inicial_ms: int, cuantas: int) -> list[Vuelta]:
    """Paquetes de vuelta a 60 Hz con el tiempo avanzando como el reloj."""
    return [Vuelta(desde_s + i / 60, 3, tiempo_inicial_ms + round(1000 * i / 60))
            for i in range(cuantas)]


class TiempoDeVuelta(unittest.TestCase):

    def test_con_minutos(self):
        self.assertAlmostEqual(tiempo_de_vuelta_a_segundos("1:12.845"), 72.845)

    def test_sin_minutos(self):
        self.assertAlmostEqual(tiempo_de_vuelta_a_segundos("50.268"), 50.268)


class Showinfo(unittest.TestCase):

    def test_toma_el_pts_time_del_primer_cuadro(self):
        salida = ("[Parsed_showinfo_0 @ 0x1] n:   0 pts:19502483 pts_time:325.041383 duration: 1001\n"
                  "[Parsed_showinfo_0 @ 0x1] n:   1 pts:19503484 pts_time:325.058067\n")
        self.assertAlmostEqual(pts_de_showinfo(salida), 325.041383)

    def test_sin_pts_time_es_un_error(self):
        with self.assertRaises(ValueError):
            pts_de_showinfo("nada")


class Ancla(unittest.TestCase):

    def test_despeja_el_instante_que_reproduce_el_tiempo(self):
        # En 100,000 s el tiempo de vuelta es 50,000 s; la pantalla muestra 50,100.
        vueltas = vueltas_cada_16_ms(100.0, 50_000, 60)

        instante = anclar(vueltas, 50.100, instante_global=100.140)

        self.assertAlmostEqual(instante, 100.100, places=3)

    def test_un_parcial_congelado_no_ancla(self):
        """La pantalla sigue mostrando 50,100 cuando la vuelta ya va por 51 s."""
        vueltas = vueltas_cada_16_ms(100.0, 50_000, 120)

        self.assertIsNone(anclar(vueltas, 50.100, instante_global=101.0))

    def test_fuera_de_los_paquetes_no_ancla(self):
        vueltas = vueltas_cada_16_ms(100.0, 50_000, 10)

        self.assertIsNone(anclar(vueltas, 10.0, instante_global=100.05))


class MuestraCercana(unittest.TestCase):

    def test_elige_la_mas_cercana_a_los_dos_lados(self):
        segundos = [1.0, 2.0, 3.0]
        self.assertEqual(muestra_cercana(segundos, 1.4), 0)
        self.assertEqual(muestra_cercana(segundos, 1.6), 1)
        self.assertEqual(muestra_cercana(segundos, 9.0), 2)
        self.assertEqual(muestra_cercana(segundos, 0.0), 0)


class Resumen(unittest.TestCase):

    def test_pares_exactos_distribucion_y_maximo(self):
        r = resumir([0, 1, 1, -1, 0, 2])

        self.assertEqual(r["pares"], 6)
        self.assertEqual(r["exactos"], 2)
        self.assertEqual(r["distribucion"], {-1: 1, 0: 2, 1: 2, 2: 1})
        self.assertEqual(r["maximo_absoluto"], 2)


class Plantilla(unittest.TestCase):

    def test_trece_temperaturas_y_siete_componentes_mas_el_ancla(self):
        filas = filas_de_plantilla([{"paso": "t1", "magnitud": "temperatura"},
                                    {"paso": "c1", "magnitud": "componente"}])

        temperatura = [f for f in filas if f["paso"] == "t1"]
        componente = [f for f in filas if f["paso"] == "c1"]
        self.assertEqual(sum(f["magnitud"] == "temperatura" for f in temperatura), 13)
        self.assertEqual(sum(f["magnitud"] == "ancla" for f in temperatura), 2)
        self.assertEqual([f["canal"] for f in componente if f["magnitud"] == "componente"],
                         list(COMPONENTES))
        self.assertTrue(all(f["pantalla"] == "" for f in filas))


if __name__ == "__main__":
    unittest.main()
