# -*- coding: utf-8 -*-
"""La medicion del intervalo de llegada, y las tres cosas que separa.

Por que este modulo necesita pruebas propias
--------------------------------------------
Es una **medicion**, y una medicion mal construida no falla: informa un numero
equivocado con la misma cara que uno correcto. El defecto concreto que estas
pruebas cierran ya aparecio al construirla: contar como perdida los ochenta y
nueve segundos en que el juego estaba en pausa daba una entrega del 88 %, y la
entrega real era del 99,6 %. Un instrumento que confunde *no lo enviaron* con
*se perdio* atribuye a la cadena un defecto de la fuente.

Las tres poblaciones que un intervalo grande puede pertenecer a
--------------------------------------------------------------
1. **llego tarde**: jitter, y entra en la distribucion;
2. **falto una ranura**: perdida, y se cuenta aparte;
3. **el emisor se detuvo**: tiempo muerto, y no se cuenta como ninguna de las
   dos.

Cada prueba de abajo construye una serie sintetica donde se sabe de antemano
cual es cual, que es la unica forma de comprobar que el instrumento las separa.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

sys.path.insert(0, str(RAIZ / "scripts"))

import medir_intervalo_de_emision as med  # noqa: E402

MS = 1000  # el modulo trabaja en microsegundos
PERIODO = 50 * MS


def _serie(intervalos_ms: list[float]) -> list[int]:
    """Marcas de llegada a partir de los intervalos que se quieren provocar."""

    marcas = [0]
    for x in intervalos_ms:
        marcas.append(marcas[-1] + int(x * MS))
    return marcas


class SeparaLasTresPoblaciones(unittest.TestCase):

    def test_una_serie_perfecta_no_tiene_jitter_ni_perdida(self):
        m = med.medir(_serie([50.0] * 100), PERIODO)
        self.assertAlmostEqual(m["p50_ms"], 50.0, places=3)
        self.assertAlmostEqual(m["jitter_p99_ms"], 0.0, places=3)
        self.assertEqual(m["ranuras_faltantes"], 0)
        self.assertEqual(m["entrega"], 1.0)
        self.assertEqual(m["tiempo_muerto_s"], 0.0)

    def test_una_llegada_tarde_es_jitter_y_no_perdida(self):
        """Sesenta donde se prometian cincuenta: llego, tarde."""

        m = med.medir(_serie([50.0] * 50 + [60.0] + [50.0] * 50), PERIODO)
        self.assertEqual(m["ranuras_faltantes"], 0)
        self.assertEqual(m["entrega"], 1.0)
        # Y quedo dentro de la distribucion, del lado de los que pasan el
        # periodo: es lo que la vuelve jitter y no perdida.
        self.assertAlmostEqual(m["mediana_de_los_altos_ms"], 60.0, places=3)

    def test_una_ranura_salteada_es_perdida_y_no_jitter(self):
        """Cien donde se prometian cincuenta: falto una."""

        m = med.medir(_serie([50.0] * 50 + [100.0] + [50.0] * 50), PERIODO)
        self.assertEqual(m["ranuras_faltantes"], 1)
        self.assertLess(m["entrega"], 1.0)
        # No debe contaminar la distribucion del jitter.
        self.assertAlmostEqual(m["p99_ms"], 50.0, places=3)

    def test_un_tramo_muerto_no_se_cuenta_como_perdida(self):
        """Es el defecto que la medicion tuvo: catorce segundos de pausa.

        Con el tramo contado como perdida, la entrega de una captura real caia
        al 88 % sin que se hubiera perdido nada.
        """

        m = med.medir(_serie([50.0] * 50 + [14_000.0] + [50.0] * 50), PERIODO)
        self.assertEqual(m["tramos_muertos"], 1)
        self.assertAlmostEqual(m["tiempo_muerto_s"], 14.0, places=3)
        self.assertEqual(m["ranuras_faltantes"], 0)
        self.assertEqual(m["entrega"], 1.0)

    def test_la_tasa_alcanzada_descuenta_el_tiempo_muerto(self):
        """Cien entregas a veinte por segundo, con diez segundos de pausa.

        Sobre el tiempo total la tasa parece de diez por segundo; sobre el
        tiempo vivo es de veinte, que es lo que el emisor prometio.
        """

        m = med.medir(_serie([50.0] * 100 + [10_000.0] + [50.0] * 100), PERIODO)
        self.assertAlmostEqual(m["tasa_sobre_lo_vivo"], 20.0, delta=0.3)
        self.assertGreater(m["tiempo_total_s"], 19.0)


class DescribeLaAlternancia(unittest.TestCase):
    """La forma de la distribucion, que la dispersion sola no muestra.

    El hallazgo que motiva esto: en el flujo real, la mediana del intervalo no
    es el periodo prometido, porque el emisor alterna entre uno corto y uno
    largo. Cumple la tasa promedio sin cumplirla nunca en un solo intervalo, y
    un promedio o un desvio solos no lo dejan ver.
    """

    def test_una_alternancia_estricta_queda_anticorrelacionada(self):
        m = med.medir(_serie([33.3, 66.7] * 100), PERIODO)
        self.assertLess(m["correlacion_consecutivos"], -0.9)

    def test_una_alternancia_no_cae_sobre_el_periodo_prometido(self):
        """Y sin embargo la media es el periodo prometido."""

        m = med.medir(_serie([33.3, 66.7] * 100), PERIODO)
        self.assertAlmostEqual(m["fraccion_sobre_el_periodo"], 0.0, places=3)
        self.assertAlmostEqual(m["media_viva_ms"], 50.0, delta=0.1)

    def test_declara_las_dos_modas(self):
        m = med.medir(_serie([33.3, 66.7] * 100), PERIODO)
        self.assertAlmostEqual(m["mediana_de_los_bajos_ms"], 33.3, delta=0.1)
        self.assertAlmostEqual(m["mediana_de_los_altos_ms"], 66.7, delta=0.1)
        self.assertAlmostEqual(m["fraccion_bajo_el_periodo"], 0.5, delta=0.01)

    def test_una_serie_regular_no_se_declara_alternante(self):
        """El control negativo: sin alternancia no debe aparecer una."""

        m = med.medir(_serie([50.0] * 200), PERIODO)
        self.assertGreater(m["fraccion_sobre_el_periodo"], 0.99)


class VariacionDelRetardo(unittest.TestCase):
    """IPDV: la metrica normalizada, que es la que el informe define y cita.

    Con un solo reloj el retardo absoluto no se puede medir. Su **variacion**
    si, porque el termino desconocido se cancela al restar dos retardos
    consecutivos, y eso deja la diferencia entre intervalos de llegada.
    """

    def test_un_flujo_regular_no_tiene_variacion_del_retardo(self):
        m = med.medir(_serie([50.0] * 100), PERIODO)
        self.assertAlmostEqual(m["ipdv_p50_ms"], 0.0, places=3)
        self.assertAlmostEqual(m["ipdv_p99_ms"], 0.0, places=3)

    def test_una_alternancia_da_un_ipdv_del_tamano_del_salto(self):
        """Alternar 33,3 y 66,7 es saltar 33,4 ms en cada entrega."""

        m = med.medir(_serie([33.3, 66.7] * 100), PERIODO)
        self.assertAlmostEqual(m["ipdv_p50_ms"], 33.4, delta=0.1)

    def test_la_media_del_ipdv_da_cero_y_es_el_control_interno(self):
        """Cada adelanto se paga con un atraso.

        Una media corrida de cero no seria variacion del retardo sino deriva
        entre los relojes, que es un defecto de la medicion y no del flujo.
        """

        for serie in ([33.3, 66.7] * 100, [50.0] * 100, [40.0, 55.0, 55.0] * 50):
            m = med.medir(_serie(serie), PERIODO)
            self.assertAlmostEqual(m["ipdv_media_ms"], 0.0, delta=0.5)


class TasaDeclarada(unittest.TestCase):
    """El periodo contra el que se mide sale de la tabla de paquetes."""

    def test_los_paquetes_de_menu_siguen_la_tasa_configurada(self):
        # car_telemetry: la tabla dice "menu", de modo que el periodo no viaja
        # en el flujo y hay que pasarlo.
        self.assertEqual(med._tasa_declarada(6, 20.0), 20.0)
        self.assertEqual(med._tasa_declarada(6, 60.0), 60.0)

    def test_los_paquetes_de_tasa_fija_no_dependen_del_menu(self):
        self.assertEqual(med._tasa_declarada(1, 60.0), 2.0)    # session, 2/s
        self.assertEqual(med._tasa_declarada(10, 60.0), 10.0)  # car_damage
        self.assertEqual(med._tasa_declarada(15, 60.0), 1.0)   # lap_positions

    def test_participants_declara_su_periodo_en_segundos(self):
        self.assertAlmostEqual(med._tasa_declarada(4, 20.0), 0.2)

    def test_los_paquetes_sin_periodo_no_tienen_intervalo_que_medir(self):
        """Un evento no promete cadencia: medirle jitter es un sinsentido."""

        self.assertIsNone(med._tasa_declarada(3, 20.0))   # event
        self.assertIsNone(med._tasa_declarada(8, 20.0))   # final_classification


class PaquetesQueRotan(unittest.TestCase):
    """El historial y los juegos de neumaticos describen un auto por envio.

    Su tasa declarada de veinte por segundo es de datagramas. La de **un**
    vehiculo es esa dividida por la cantidad de autos, y es la unica que
    responde a cada cuanto se refresca lo que un tablero muestra.
    """

    def test_estan_declarados_los_dos_que_rotan(self):
        self.assertEqual(med.PAQUETES_QUE_ROTAN, {11, 12})

    def test_el_periodo_por_vehiculo_es_el_de_la_ranura_por_la_parrilla(self):
        """Veinte por segundo repartidos entre veinte autos es uno por auto."""

        propio = med._tasa_declarada(11, 20.0) / 20
        self.assertAlmostEqual(propio, 1.0)
        m = med.medir(_serie([1000.0] * 30), 1_000_000 / propio)
        self.assertAlmostEqual(m["tasa_sobre_lo_vivo"], 1.0, delta=0.05)


class NoInventaLoQueNoVio(unittest.TestCase):
    """Los casos degenerados, que son donde una medicion miente mas facil."""

    def test_una_sola_marca_no_produce_intervalos(self):
        m = med.medir([0], PERIODO)
        self.assertEqual(m["intervalos"], 0)

    def test_sin_marcas_no_produce_intervalos(self):
        m = med.medir([], PERIODO)
        self.assertEqual(m["intervalos"], 0)

    def test_una_sola_moda_deja_la_otra_en_none_y_no_en_cero(self):
        """Un cero se leeria como "medi cero"; None dice "no habia"."""

        m = med.medir(_serie([40.0] * 50), PERIODO)
        self.assertIsNotNone(m["mediana_de_los_bajos_ms"])
        self.assertIsNone(m["mediana_de_los_altos_ms"])


if __name__ == "__main__":
    unittest.main()
