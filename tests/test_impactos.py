# -*- coding: utf-8 -*-
"""Pruebas de la caracterizacion de colisiones."""

import unittest

from backend import impactos


def serie(valores):
    """Construye muestras a 20 Hz desde tuplas (g, velocidad, freno, acelerador)."""

    return [impactos.Muestra(tiempo_s=i * 0.05,
                             aceleracion_longitudinal_g=g,
                             velocidad_kmh=v,
                             freno=f,
                             acelerador=a)
            for i, (g, v, f, a) in enumerate(valores)]


class MedirEnvolvente(unittest.TestCase):

    def test_toma_los_extremos_de_cada_direccion(self):
        muestras = serie([(-3.0, 200, 1.0, 0.0), (-4.3, 200, 0.9, 0.0),
                          (+0.6, 200, 0.0, 1.0), (+2.0, 200, 0.0, 1.0)])
        env = impactos.medir_envolvente(muestras)
        self.assertTrue(env.medida)
        self.assertAlmostEqual(env.desaceleracion_maxima_g, 4.3)
        self.assertAlmostEqual(env.empuje_maximo_g, 2.0)

    def test_descarta_el_auto_detenido(self):
        """Con el auto quieto el canal no informa sobre lo que el auto puede."""

        muestras = serie([(-9.0, 5, 1.0, 0.0), (+9.0, 5, 0.0, 1.0)])
        env = impactos.medir_envolvente(muestras)
        self.assertFalse(env.medida)
        self.assertEqual(env.muestras_frenando, 0)

    def test_sin_material_declara_que_no_midio(self):
        """Los valores de referencia se devuelven, pero marcados como tales."""

        env = impactos.medir_envolvente([])
        self.assertFalse(env.medida)
        self.assertEqual(env.empuje_maximo_g, impactos.ENVOLVENTE_MOTOR_G)


class Caracterizar(unittest.TestCase):

    def setUp(self):
        self.env = impactos.Envolvente(empuje_maximo_g=2.0,
                                       desaceleracion_maxima_g=4.3,
                                       medida=True)

    def test_empuje_mayor_que_el_motor_es_desde_atras(self):
        muestras = serie([(+0.5, 163, 0.0, 0.65), (+10.65, 163, 0.0, 0.65),
                          (+0.4, 164, 0.0, 0.65)])
        imp = impactos.caracterizar(0.05, muestras, self.env)
        self.assertEqual(imp.clasificacion, impactos.EMPUJADO_DESDE_ATRAS)
        self.assertAlmostEqual(imp.veces_la_envolvente, 10.65 / 2.0, places=3)

    def test_desaceleracion_mayor_que_los_frenos_es_algo_adelante(self):
        muestras = serie([(-2.0, 43, 1.0, 0.0), (-15.89, 30, 1.0, 0.0),
                          (-1.0, 19, 1.0, 0.0)])
        imp = impactos.caracterizar(0.05, muestras, self.env)
        self.assertEqual(imp.clasificacion, impactos.FRENADO_POR_ALGO_ADELANTE)
        self.assertEqual(imp.velocidad_perdida_kmh, 43 - 19)

    def test_una_frenada_fuerte_no_es_un_impacto(self):
        """Cuatro g de desaceleracion los dan los frenos: no hay impulso externo."""

        muestras = serie([(-4.0, 300, 1.0, 0.0), (-4.2, 250, 1.0, 0.0),
                          (-4.1, 200, 1.0, 0.0)])
        imp = impactos.caracterizar(0.05, muestras, self.env)
        self.assertEqual(imp.clasificacion, impactos.SIN_IMPULSO_MEDIBLE)

    def test_acelerar_a_fondo_no_es_un_empuje(self):
        muestras = serie([(+1.9, 100, 0.0, 1.0), (+2.0, 110, 0.0, 1.0)])
        imp = impactos.caracterizar(0.0, muestras, self.env)
        self.assertEqual(imp.clasificacion, impactos.SIN_IMPULSO_MEDIBLE)

    def test_sin_pico_declara_que_pudo_caer_entre_muestras(self):
        """La ausencia de pico no se presenta como ausencia de golpe."""

        muestras = serie([(-1.6, 207, 0.0, 0.0), (-1.5, 150, 0.0, 0.0),
                          (-1.0, 116, 0.0, 0.0)])
        imp = impactos.caracterizar(0.05, muestras, self.env)
        self.assertEqual(imp.clasificacion, impactos.SIN_IMPULSO_MEDIBLE)
        self.assertIn("entre dos muestras", imp.fundamento)
        self.assertEqual(imp.velocidad_perdida_kmh, 207 - 116)

    def test_sin_muestras_no_inventa_un_impacto(self):
        self.assertIsNone(impactos.caracterizar(99.0, serie([(0.0, 100, 0.0, 0.0)])))

    def test_el_fundamento_nombra_la_envolvente_usada(self):
        """La anotacion tiene que poder mostrar contra que se comparo."""

        muestras = serie([(+5.0, 91, 0.0, 0.88), (+1.0, 79, 0.0, 0.88)])
        imp = impactos.caracterizar(0.0, muestras, self.env)
        self.assertIn("2.00 g", imp.fundamento)
        self.assertIn("motor", imp.fundamento)


class CombinarEnvolventes(unittest.TestCase):
    """La envolvente es del auto, y se mide a traves de lo que cada uno exigio."""

    def test_toma_el_extremo_de_cada_direccion(self):
        rapido = impactos.Envolvente(empuje_maximo_g=2.03,
                                     desaceleracion_maxima_g=4.31,
                                     muestras_acelerando=3858,
                                     muestras_frenando=453, medida=True)
        lento = impactos.Envolvente(empuje_maximo_g=1.38,
                                    desaceleracion_maxima_g=3.79,
                                    muestras_acelerando=534,
                                    muestras_frenando=148, medida=True)
        combinada = impactos.combinar_envolventes([rapido, lento])
        self.assertAlmostEqual(combinada.empuje_maximo_g, 2.03)
        self.assertAlmostEqual(combinada.desaceleracion_maxima_g, 4.31)
        self.assertEqual(combinada.muestras_acelerando, 3858 + 534)

    def test_evita_atribuir_impactos_al_que_menos_exige_el_auto(self):
        """Un impulso entre las dos envolventes cambia de clase segun cual se use.

        Se prueba con 1,9 g, que esta entre los 1,38 g medidos al conductor que
        exige poco el auto y los 2,03 g medidos al que lo exige a fondo. Ese
        margen es justamente el que cubre los contactos leves.
        """

        muestras = [impactos.Muestra(0.0, +1.0, 175, 0.0, 0.78),
                    impactos.Muestra(0.05, +1.9, 168, 0.0, 0.78),
                    impactos.Muestra(0.10, +0.9, 165, 0.0, 0.78)]
        propia = impactos.Envolvente(empuje_maximo_g=1.38,
                                     desaceleracion_maxima_g=3.79, medida=True)
        del_auto = impactos.Envolvente(empuje_maximo_g=2.03,
                                       desaceleracion_maxima_g=4.31, medida=True)
        self.assertEqual(impactos.caracterizar(0.05, muestras, propia).clasificacion,
                         impactos.EMPUJADO_DESDE_ATRAS)
        self.assertEqual(impactos.caracterizar(0.05, muestras, del_auto).clasificacion,
                         impactos.SIN_IMPULSO_MEDIBLE)

    def test_sin_ninguna_medida_devuelve_la_referencia_marcada(self):
        combinada = impactos.combinar_envolventes(
            [impactos.Envolvente(), impactos.Envolvente()])
        self.assertFalse(combinada.medida)


class NoAtribuyeCulpa(unittest.TestCase):
    """La clasificacion nunca nombra responsabilidad, que es un juicio."""

    def test_ninguna_clasificacion_habla_de_culpa(self):
        for c in (impactos.EMPUJADO_DESDE_ATRAS,
                  impactos.FRENADO_POR_ALGO_ADELANTE,
                  impactos.SIN_IMPULSO_MEDIBLE):
            for palabra in ("culpa", "responsab", "provoco", "causo"):
                self.assertNotIn(palabra, c)


if __name__ == "__main__":
    unittest.main()
