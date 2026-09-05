# -*- coding: utf-8 -*-
"""El caudal de las tres fuentes, y las figuras de las mediciones.

Por que la unidad importa mas que el numero
-------------------------------------------
Las tasas nativas de las tres fuentes **no son comparables**: una muestra
deportiva describe un vehiculo con seis senales, una trama de bus trae hasta ocho
bytes, y un datagrama de simulacion puede describir veintidos vehiculos por
decenas de canales. Poner 3,74 al lado de 4.012 y concluir algo es comparar cosas
distintas.

La unidad honesta es **mensajes del contrato interno por segundo**, y hay que
medirla pasando datos por cada adaptador, no estimarla multiplicando. Al medirla
la prediccion salio al reves: el bus, que tiene la tasa cruda mas alta, queda
**tercero** en mensajes del contrato.

El defecto que estas pruebas cierran
------------------------------------
La primera version informo **73 datagramas por segundo** para una fuente cuya tasa
ya estaba medida en 143. La muestra arrancaba en el menu previo a la sesion y **el
tiempo muerto entraba entero al divisor**. Fue la tercera aparicion del mismo
error en dos jornadas.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

import generar_figuras_mediciones as fig  # noqa: E402
import medir_caudal_por_fuente as cau  # noqa: E402


class DescuentaElTiempoMuerto(unittest.TestCase):
    """Lo que la fuente no emitio no puede entrar al divisor."""

    def test_una_serie_continua_no_tiene_tiempo_muerto(self):
        vivo, muerto = cau._tiempo_vivo([i * 0.05 for i in range(200)])
        self.assertAlmostEqual(muerto, 0.0, places=6)
        self.assertAlmostEqual(vivo, 199 * 0.05, places=6)

    def test_un_hueco_grande_se_descuenta(self):
        """Es el caso real: la muestra arrancaba en el menu."""

        marcas = [i * 0.05 for i in range(100)]
        marcas += [marcas[-1] + 30.0 + i * 0.05 for i in range(100)]
        vivo, muerto = cau._tiempo_vivo(marcas)
        self.assertAlmostEqual(muerto, 30.0, delta=0.1)
        self.assertLess(vivo, 12.0)

    def test_la_tasa_sobre_lo_vivo_es_la_que_la_fuente_prometio(self):
        """Sobre el tiempo total pareceria la mitad; sobre el vivo, la real."""

        marcas = [i * 0.05 for i in range(100)]
        marcas += [marcas[-1] + 30.0 + i * 0.05 for i in range(100)]
        vivo, _ = cau._tiempo_vivo(marcas)
        self.assertAlmostEqual(len(marcas) / vivo, 20.0, delta=1.0)

    def test_una_serie_de_una_sola_marca_no_inventa_duracion(self):
        self.assertEqual(cau._tiempo_vivo([1.0]), (0.0, 0.0))

    def test_el_umbral_de_hueco_es_enorme_frente_al_periodo(self):
        """Con datagramas cada pocos milisegundos, un segundo de silencio no es
        irregularidad: es que la fuente no estaba emitiendo."""

        self.assertGreaterEqual(cau.HUECO_MUERTO_S, 0.5)


class DeclaraLaEleccionQueCambiaElNumero(unittest.TestCase):
    """El caudal de la simulacion depende de una decision, no solo del flujo."""

    def test_mide_las_dos_formas_del_adaptador(self):
        """Normalizar solo el vehiculo propio o toda la parrilla cambia el
        caudal por un factor de veinte. Dar una sola cifra escondería la
        eleccion detras de un numero."""

        import inspect
        firma = inspect.signature(cau.medir_f1_25)
        self.assertIn("todos_los_vehiculos", firma.parameters)

    def test_cuenta_aparte_los_paquetes_sin_normalizacion(self):
        """Llegan y no producen ningun mensaje del contrato. Esconderlos
        inflaria las senales por unidad al dividir por menos unidades."""

        fuente = Path(cau.__file__).read_text(encoding="utf-8")
        self.assertIn("sin_normalizacion", fuente)

    def test_por_segundo_no_divide_por_cero(self):
        import math
        self.assertTrue(math.isnan(cau._por_segundo(10, 0.0)))


class LasFigurasSonEvidencia(unittest.TestCase):
    """Se escriben como coordenadas dentro del documento, no como imagen.

    Una figura de resultados no es una ilustracion: escrita asi queda auditable
    sin volver a correr nada, sale vectorial y usa la tipografia del texto.
    """

    def test_el_histograma_se_expresa_en_proporcion(self):
        """Las dos capturas tienen distinta cantidad de datagramas: comparar
        cuentas absolutas mostraria esa diferencia y no la forma."""

        h = fig._histograma([10.0] * 30 + [20.0] * 10)
        self.assertAlmostEqual(sum(y for _, y in h), 100.0, places=3)

    def test_el_histograma_recorta_donde_deja_de_haber_flujo(self):
        """Por encima del tope no hay irregularidad sino ranuras perdidas, y
        mezclarlas aplastaria la escala."""

        h = fig._histograma([10.0] * 10 + [fig.TOPE_MS + 500.0] * 10)
        self.assertTrue(all(x <= fig.TOPE_MS + fig.ANCHO_BIN_MS for x, _ in h))

    def test_una_muestra_vacia_no_produce_figura(self):
        self.assertEqual(fig._histograma([]), [])

    def test_el_tope_de_las_series_ignora_las_vacias(self):
        self.assertEqual(fig._tope([(1.0, 5.0)], []), 5.0)

    def test_las_coordenadas_salen_en_el_formato_de_pgfplots(self):
        self.assertEqual(fig._coordenadas([(1.0, 2.0)], "({:.1f},{:.1f})"),
                         "(1.0,2.0)")


if __name__ == "__main__":
    unittest.main()
