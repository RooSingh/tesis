# -*- coding: utf-8 -*-
"""La deriva entre relojes y el retardo sobre el piso.

QUE SE COMPRUEBA. Las dos decisiones del modulo, sobre datos sinteticos con la
respuesta conocida:

- que el ajuste **resista valores atipicos**, que es la unica razon por la que se
  eligio Theil-Sen en vez de minimos cuadrados. Los datagramas tardios son
  justamente lo que se quiere medir, no lo que debe mandar sobre la recta;
- que el piso sea el minimo, de modo que **ningun retardo salga negativo**: un
  retardo negativo diria que un mensaje llego antes de emitirse.

Y una propiedad que no es de calculo sino de citabilidad: **dos corridas sobre la
misma captura tienen que dar lo mismo**. El muestreo de pares lleva semilla fija
por eso; una medicion que cambia entre ejecuciones no se puede poner en un
informe.
"""

from __future__ import annotations

import random
import unittest

from backend.analisis import desfase_de_relojes as dr


class LaPendienteRobustaTests(unittest.TestCase):
    def test_sobre_una_recta_limpia_da_su_pendiente(self) -> None:
        pares = [(float(i), 2.0 * i + 5.0) for i in range(200)]
        self.assertAlmostEqual(dr.pendiente_robusta(pares), 2.0, places=9)

    def test_un_punado_de_tardios_no_arrastra_la_recta(self) -> None:
        """LA PRUEBA QUE JUSTIFICA LA ELECCION DEL AJUSTE.

        Diez de doscientos datagramas llegan un segundo tarde. Con minimos
        cuadrados esa cola corre la pendiente y el retardo de todos los demas se
        mide contra una recta que los tardios movieron. La mediana de pendientes
        no se entera.
        """

        pares = [(float(i), 1.0 * i) for i in range(200)]
        for i in range(0, 200, 20):                 # diez atipicos, +1 s
            pares[i] = (float(i), 1.0 * i + 1.0)

        robusta = dr.pendiente_robusta(pares)
        self.assertAlmostEqual(robusta, 1.0, places=6)

        # Y para que la comparacion no sea una afirmacion sin medir: el ajuste
        # por minimos cuadrados sobre los mismos datos si se mueve.
        n = len(pares)
        mx = sum(x for x, _ in pares) / n
        my = sum(y for _, y in pares) / n
        cuadrados = (sum((x - mx) * (y - my) for x, y in pares) /
                     sum((x - mx) ** 2 for x, _ in pares))
        self.assertGreater(abs(cuadrados - 1.0), abs(robusta - 1.0),
                           "los minimos cuadrados no se movieron: el caso no "
                           "distingue los dos ajustes y no prueba nada")

    def test_una_deriva_de_verdad_si_se_informa(self) -> None:
        """Si los dos relojes corren a ritmos distintos hay que decirlo: un
        retardo medido sobre relojes que derivan crece solo con el tiempo."""

        pares = [(float(i), 1.0005 * i) for i in range(300)]
        self.assertAlmostEqual(dr.pendiente_robusta(pares), 1.0005, places=6)

    def test_sin_dos_instantes_distintos_no_hay_pendiente(self) -> None:
        """Y se dice, en vez de devolver un numero cualquiera. Pasa de verdad:
        con la sesion sin arrancar, `session_time` vale cero en todos."""

        with self.assertRaises(ValueError):
            dr.pendiente_robusta([(5.0, 1.0), (5.0, 2.0), (5.0, 3.0)])
        with self.assertRaises(ValueError):
            dr.pendiente_robusta([(1.0, 1.0)])


class ElRetardoSobreElPisoTests(unittest.TestCase):
    @staticmethod
    def _corrida(retardos_ms: list[float]) -> list[tuple[float, float]]:
        """Una corrida sin deriva donde cada cuadro llega con su retardo."""
        return [(float(i), float(i) + ms / 1000.0)
                for i, ms in enumerate(retardos_ms)]

    def test_el_mas_rapido_define_el_piso_y_queda_en_cero(self) -> None:
        """Un retardo no puede ser negativo: diria que un mensaje llego antes de
        emitirse. El datagrama mas rapido es el que menos camino perdio, y se
        toma como piso.

        LOS RETARDOS NO PUEDEN CRECER CON EL INDICE en un caso de prueba. La
        primera version de esta prueba usaba [3, 1, 5, 1, 9] sobre cinco
        cuadros, y ahi el retardo **esta correlacionado con la abscisa**: el
        ajuste se lo lleva a la pendiente, que es lo que un ajuste debe hacer, y
        el maximo daba 6,75 y no 8. El caso media la absorcion, no el piso.
        """

        retardos = [1.0] * 200
        retardos[137] = 9.0                       # un tardio, sin tendencia
        d = dr.medir(self._corrida(retardos))
        self.assertGreaterEqual(min(0.0, d.mediana_ms), 0.0)
        self.assertAlmostEqual(d.mediana_ms, 0.0, places=2)
        self.assertAlmostEqual(d.maximo_ms, 8.0, places=2)   # 9 menos el piso de 1

    def test_la_mediana_y_el_p99_salen_de_la_distribucion(self) -> None:
        """UN SOLO ATIPICO EN CIEN NO ALCANZA PARA EJERCER EL p99, y la primera
        version de esta prueba lo pedia. Con noventa y nueve valores en cero y
        uno en cincuenta, el percentil 99 cae **entre** los dos ultimos e
        interpola: da 0,5 ms, que es correcto. Para que la cola se vea hace
        falta que la cola tenga mas de un elemento.
        """

        retardos = [1.0] * 195 + [51.0] * 5      # doscientos cuadros, cinco tardios
        d = dr.medir(self._corrida(retardos))
        self.assertAlmostEqual(d.mediana_ms, 0.0, places=2)
        self.assertAlmostEqual(d.maximo_ms, 50.0, places=2)
        self.assertGreater(d.p99_ms, 20.0, "el p99 no ve la cola")

    def test_ningun_retardo_queda_negativo_cuando_el_piso_esta_abajo(self) -> None:
        """EL HUECO QUE ESTA PRUEBA CIERRA. La anterior no distinguia el piso
        real de un cero fijo, porque su mas rapido caia justo en la mediana. El
        caso que los separa es el de siempre en una captura: la mayoria de los
        cuadros tarda lo normal y **unos pocos llegan mas rapido que la
        mediana**. Con un piso fijo en cero esos quedan en negativo, y un
        retardo negativo diria que un mensaje llego antes de emitirse.
        """

        retardos = [5.0] * 200
        for i in (23, 91, 164):
            retardos[i] = 1.0                     # tres mas rapidos que el resto
        d = dr.medir(self._corrida(retardos))
        self.assertGreaterEqual(d.mediana_ms, 0.0, "hay retardos negativos")
        # El piso son esos 1,0 ms, asi que la mediana cae a 4 sobre el piso.
        self.assertAlmostEqual(d.mediana_ms, 4.0, places=2)

    def test_la_medicion_declara_cuantos_y_cuanto_abarca(self) -> None:
        """Sin el conteo y la duracion, una mediana no se puede juzgar: no es lo
        mismo sobre cuarenta cuadros que sobre cuarenta mil."""

        d = dr.medir(self._corrida([1.0] * 50))
        self.assertEqual(d.datagramas, 50)
        self.assertAlmostEqual(d.duracion_s, 49.0, places=3)

    def test_la_misma_captura_da_siempre_lo_mismo(self) -> None:
        """El muestreo de pares es al azar y lleva semilla fija. Una medicion
        que cambia entre ejecuciones no se puede citar en un informe.


        LOS DATOS TIENEN QUE SER IRREGULARES para que el caso sirva. La primera
        version usaba un patron periodico ---`i % 7`--- donde las pendientes
        entre pares toman pocos valores distintos: la mediana caia siempre en el
        mismo aunque el muestreo cambiara, y la prueba pasaba con semilla y sin
        ella. Con valores desparejos, que muestreo se toma si importa.
        """

        az = random.Random(7)
        pares = [(float(i), float(i) * 1.00001 + az.random() / 1000.0)
                 for i in range(1500)]
        a = dr.medir(pares)
        b = dr.medir(pares)
        self.assertEqual(a, b)

    def test_el_texto_se_niega_a_decirlo_sin_la_salvedad(self) -> None:
        """LO QUE NO PUEDE PERDERSE AL CITARLO. El numero solo se lee como un
        retardo absoluto, y no lo es: sin relojes sincronizados el absoluto no
        existe. La salvedad viaja pegada a la cifra, no en una nota al pie que
        se puede copiar sin ella.
        """

        t = dr.medir(self._corrida([2.0, 1.0, 4.0])).como_texto()
        self.assertIn("RELATIVO AL MINIMO OBSERVADO", t)
        self.assertIn("no absoluto", t)
        self.assertIn("deriva", t)

    def test_sin_datagramas_suficientes_se_dice(self) -> None:
        with self.assertRaises(ValueError):
            dr.medir([(1.0, 1.0)])
        with self.assertRaises(ValueError):
            dr.medir([])


if __name__ == "__main__":
    unittest.main()
