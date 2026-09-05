# -*- coding: utf-8 -*-
"""Pruebas del resumen de sesion a resolucion reducida.

Lo que hay que garantizar no es que reduzca, sino que **reduzca sin mentir**: un
pico que ocurrio tiene que seguir apareciendo despues de reducir, porque es
justamente el instante que una anotacion senala.
"""

import unittest

from backend import resumen_sesion


class ResumenDeSenal(unittest.TestCase):

    def test_agrupa_por_intervalo(self):
        r = resumen_sesion.ResumenDeSenal()
        for i in range(40):
            r.observar(i * 0.05, 10.0)      # dos segundos a veinte por segundo
        serie = r.serie()
        self.assertEqual(len(serie), 2)

    def test_un_pico_de_una_sola_muestra_sobrevive(self):
        """Es la razon de ser del modulo.

        Con un muestreo simple, un pico que dura menos que el intervalo reducido
        desaparece y el grafico queda mas suave que la conduccion que describe.
        """

        r = resumen_sesion.ResumenDeSenal()
        for i in range(20):
            r.observar(i * 0.05, 5.0)
        r.observar(0.5, 300.0)              # el pico, una sola muestra
        _, minimo, maximo, _ = r.serie()[0]
        self.assertEqual(maximo, 300.0)
        self.assertEqual(minimo, 5.0)

    def test_un_valle_tambien_sobrevive(self):
        r = resumen_sesion.ResumenDeSenal()
        for i in range(20):
            r.observar(i * 0.05, 100.0)
        r.observar(0.5, -40.0)
        _, minimo, maximo, _ = r.serie()[0]
        self.assertEqual(minimo, -40.0)
        self.assertEqual(maximo, 100.0)

    def test_el_intervalo_abierto_se_informa(self):
        """Sin esto, lo que pasa ahora aparece con un segundo de retraso."""

        r = resumen_sesion.ResumenDeSenal()
        r.observar(0.1, 7.0)
        self.assertEqual(len(r.serie()), 1)
        self.assertEqual(r.serie()[0][2], 7.0)

    def test_cuenta_las_muestras_de_cada_intervalo(self):
        """Permite distinguir un intervalo completo de uno con un hueco."""

        r = resumen_sesion.ResumenDeSenal()
        for i in range(20):
            r.observar(i * 0.05, 1.0)
        self.assertEqual(r.serie()[0][3], 20)

    def test_ignora_lo_que_no_es_numerico(self):
        r = resumen_sesion.ResumenDeSenal()
        r.observar(0.1, "texto")
        r.observar(0.2, None)
        r.observar(0.3, True)               # booleano no es magnitud
        self.assertEqual(r.serie(), [])

    def test_el_tope_de_intervalos_es_conocido(self):
        """Memoria acotada y declarada, no crecimiento sin fin."""

        r = resumen_sesion.ResumenDeSenal()
        for i in range(resumen_sesion.INTERVALOS_MAXIMOS + 100):
            r.observar(float(i), float(i))
        self.assertLessEqual(len(r.serie()),
                             resumen_sesion.INTERVALOS_MAXIMOS + 1)


class ResumenDeSesion(unittest.TestCase):

    def test_separa_por_vehiculo_y_por_senal(self):
        s = resumen_sesion.ResumenDeSesion()
        s.observar("car:18", "speed", 0.1, 100.0)
        s.observar("car:19", "speed", 0.1, 50.0)
        s.observar("car:18", "brake", 0.1, 1.0)
        v = s.vehiculos()
        self.assertEqual(set(v), {"car:18", "car:19"})
        self.assertEqual(set(v["car:18"]), {"speed", "brake"})
        self.assertEqual(v["car:19"]["speed"][0][2], 50.0)

    def test_el_origen_es_la_primera_muestra_y_no_el_reloj(self):
        """El eje es el tiempo transcurrido de la sesion."""

        s = resumen_sesion.ResumenDeSesion()
        s.observar("car:18", "speed", 1000.0, 10.0)
        s.observar("car:18", "speed", 1002.0, 20.0)
        serie = s.vehiculos()["car:18"]["speed"]
        self.assertEqual(serie[0][0], 0.0)
        self.assertEqual(serie[-1][0], 2.0)

    def test_olvidar_descarta_un_vehiculo(self):
        s = resumen_sesion.ResumenDeSesion()
        s.observar("car:18", "speed", 0.1, 10.0)
        s.observar("car:19", "speed", 0.1, 10.0)
        s.olvidar("car:18")
        self.assertEqual(set(s.vehiculos()), {"car:19"})


if __name__ == "__main__":
    unittest.main()
