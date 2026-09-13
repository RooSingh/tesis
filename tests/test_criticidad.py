# -*- coding: utf-8 -*-
"""Que significa perder una senal, y cuando eso merece alarma.

Lo que se ejercita es el criterio, no la consulta. Dos cosas concentran el riesgo
de este modulo: que los dos ejes se fusionen en uno, y que el umbral de silencio
sea un numero elegido en lugar de derivado.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from backend.analisis import criticidad as cr


class DosEjesTest(unittest.TestCase):
    """Seguridad y analisis son ejes distintos y no se colapsan."""

    def test_cada_criterio_declara_su_nivel_de_seguridad(self):
        for c in cr.CRITERIOS:
            self.assertIn(c.nivel_seguridad,
                          (cr.CRITICA, cr.ATENCION, cr.INFORMATIVA))

    def test_la_vigilancia_informa_los_dos_niveles(self):
        v = cr.vigilancias("f1_25_udp_simulation")[0]
        self.assertTrue(hasattr(v, "nivel_seguridad"))
        self.assertTrue(hasattr(v, "nivel_analisis"))

    def test_el_peor_dice_por_que_eje(self):
        """Devolver solo el nivel volveria a fusionarlos.

        Quien lo muestre tiene que poder decir «critica para el analisis» y no
        dejar que se lea como un peligro.
        """

        for v in cr.vigilancias("f1_25_udp_simulation"):
            nivel, eje = cr.peor(v)
            self.assertIn(eje, ("seguridad", "analisis"))
            self.assertIn(nivel, (cr.CRITICA, cr.ATENCION, cr.INFORMATIVA))

    def test_la_velocidad_no_es_critica_por_seguridad(self):
        """El conductor la ve en su tablero.

        Que su perdida inhabilite tres herramientas la vuelve critica **para el
        analisis**, y esa distincion es la razon de ser de los dos ejes: en un
        solo color, un tablero mostraria en rojo algo que no es un peligro.
        """

        v = next(x for x in cr.vigilancias("f1_25_udp_simulation")
                 if x.magnitud == "Velocidad del vehiculo")
        self.assertNotEqual(v.nivel_seguridad, cr.CRITICA)
        self.assertEqual(v.nivel_analisis, cr.CRITICA)
        self.assertEqual(cr.peor(v)[1], "analisis")

    def test_la_estructura_de_sesion_es_critica_sin_medir_nada_del_vehiculo(self):
        """El resultado que el escenario de sensado dejo y nadie habria adivinado."""

        v = next(x for x in cr.vigilancias("f1_25_udp_simulation")
                 if x.magnitud == "Numero de vuelta")
        self.assertEqual(v.nivel_seguridad, cr.CRITICA)


class UmbralDeSilencioTest(unittest.TestCase):
    """El umbral se deriva del canal, no se elige."""

    def test_un_canal_lento_tolera_mas_silencio_que_uno_rapido(self):
        rapido = cr.vigilancias("f1_25_udp_simulation", {"speed": 20.0})
        lento = cr.vigilancias("openf1_historical_replay", {"speed": 3.7})
        u_rapido = next(v.silencio_para_alarmar_s for v in rapido
                        if v.magnitud == "Velocidad del vehiculo")
        u_lento = next(v.silencio_para_alarmar_s for v in lento
                       if v.magnitud == "Velocidad del vehiculo")
        self.assertLess(u_rapido, u_lento)

    def test_el_umbral_son_cuatro_periodos(self):
        v = next(x for x in cr.vigilancias("f1_25_udp_simulation",
                                           {"speed": 20.0})
                 if x.magnitud == "Velocidad del vehiculo")
        self.assertAlmostEqual(v.silencio_para_alarmar_s, 4 / 20.0, places=3)

    def test_un_canal_muy_rapido_no_baja_del_piso_de_ruido(self):
        """Cuatro periodos a cien hercios son cuarenta milisegundos, y el desvio
        que la maquina misma introduce llego a cuarenta."""

        v = next(x for x in cr.vigilancias("can_real_replay",
                                           {"wheel_speed_front_left": 500.0})
                 if x.magnitud == "Velocidad por rueda")
        self.assertEqual(v.silencio_para_alarmar_s, cr.PISO_DE_SILENCIO_S)

    def test_sin_medicion_no_se_inventa_umbral(self):
        """Se puede decir que vigilar sin haber medido; cuanto silencio tolera,
        no."""

        v = cr.vigilancias("f1_25_udp_simulation")[0]
        self.assertIsNone(v.silencio_para_alarmar_s)


class PorFuenteTest(unittest.TestCase):

    def test_lo_que_la_fuente_nunca_publica_no_es_una_alarma(self):
        """Es una ausencia declarada.

        Sin esta distincion, el bus de un vehiculo de calle encenderia una alarma
        critica en cada arranque por no tener datos de vuelta.
        """

        presentes = cr.vigilancias_presentes("can_real_replay")
        self.assertFalse(any(v.magnitud == "Numero de vuelta"
                             for v in presentes))
        todas = cr.vigilancias("can_real_replay")
        ausente = next(v for v in todas if v.magnitud == "Numero de vuelta")
        self.assertIsNotNone(ausente.ausencia)

    def test_cada_fuente_tiene_su_propia_lista(self):
        n = {f: len(cr.vigilancias_presentes(f))
             for f in ("f1_25_udp_simulation", "can_real_replay",
                       "openf1_historical_replay")}
        self.assertGreater(n["f1_25_udp_simulation"], n["can_real_replay"])
        self.assertGreater(n["f1_25_udp_simulation"],
                           n["openf1_historical_replay"])


class FundamentoTest(unittest.TestCase):

    def test_cada_criterio_dice_que_aviso_se_pierde(self):
        """En terminos de lo que puede pasar, no del nombre del canal."""

        for c in cr.CRITERIOS:
            self.assertTrue(c.aviso_perdido.strip())
            self.assertNotIn("_", c.aviso_perdido)

    def test_cada_criterio_dice_si_el_conductor_puede_suplirlo(self):
        """Es el criterio que ordena toda la clasificacion."""

        for c in cr.CRITERIOS:
            self.assertTrue(c.percepcion_del_conductor.strip())

    def test_ninguna_cita_apunta_a_una_clave_inexistente(self):
        """El guardian que faltaba, escrito despues de fallar la verificacion.

        Al fundar el criterio se atribuyo a una pagina sobre medicion de
        temperatura de frenos una frase que esa pagina no dice: venia de otro
        resultado de busqueda y se mezclo al resumir. Abrirla lo desmintio.

        Una clave inventada es peor que un campo vacio, porque el informe la
        compila igual y la afirmacion queda pareciendo respaldada. De modo que
        toda cita tiene que resolver contra la bibliografia real.
        """

        import re
        bib = (Path(__file__).resolve().parents[1] / "informe" / "tesis"
               / "bibliografia.bib").read_text(encoding="utf-8")
        claves = set(re.findall(r"@\w+\{([^,\s]+)\s*,", bib))
        # EL GUARDIAN NO CUENTA ENTRADAS, PRUEBA EL PATRON.
        #
        # Exigia mas de cien y se puso rojo el 2026-09-13 con 53, porque la
        # bibliografia se podo a proposito (`f491dff`). Un guardian que se
        # rompe cuando el trabajo se hace ensena a bajarle el numero, y bajarlo
        # solo mueve la fecha del proximo rojo. Lo que hay que proteger es que
        # el patron siga sabiendo leer una clave: si deja de hacerlo, el bucle
        # de abajo no comprueba nada.
        muestra = "@article{una_clave_2025,\n  title = {X},\n}"
        self.assertEqual(set(re.findall(r"@\w+\{([^,\s]+)\s*,", muestra)),
                         {"una_clave_2025"}, "el patron dejo de leer una clave")
        self.assertTrue(claves, "no se leyo la bibliografia")
        for c in cr.CRITERIOS:
            if c.cita:
                self.assertIn(c.cita, claves,
                              f"{c.magnitud}: cita inexistente {c.cita!r}")

    def test_el_reparto_se_declara_como_criterio_propio(self):
        """Mientras las filas no tengan cita, el modulo tiene que decirlo.

        No es una prueba sobre el codigo sino sobre lo que el codigo afirma de
        si mismo: si alguien llenara las citas sin tocar la explicacion, o al
        reves, quedarian contradiciendose.
        """

        sin_citar = [c.magnitud for c in cr.CRITERIOS if not c.cita]
        if sin_citar:
            self.assertIn("criterio propio", cr.__doc__)

    def test_toda_magnitud_del_catalogo_existe(self):
        """Un nombre mal escrito seria una alarma que nunca se evalua."""

        from backend.analisis import disponibilidad as disp
        for c in cr.CRITERIOS:
            self.assertIn(c.magnitud, disp._POR_MAGNITUD, c.magnitud)


if __name__ == "__main__":
    unittest.main()
