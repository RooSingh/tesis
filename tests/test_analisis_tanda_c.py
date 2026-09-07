# -*- coding: utf-8 -*-
"""Ajuste con incerteza, consistencia, degradacion y traccion.

El ajuste se prueba contra datos de coeficiente conocido: se construye la
respuesta con una recta exacta y se verifica que el ajuste la recupere. Lo demas
se prueba por su criterio, y sobre todo por **lo que se niega a afirmar**.
"""

from __future__ import annotations

import unittest
from unittest import mock

from backend.analisis import ajuste as aj
from backend.analisis import consistencia as co
from backend.analisis import degradacion as dg
from backend.analisis import disponibilidad as disp
from backend.analisis import traccion as tr


class AjusteTest(unittest.TestCase):

    def test_recupera_una_recta_exacta(self):
        x = [float(i) for i in range(10)]
        y = [3.0 + 2.0 * v for v in x]
        a = aj.ajustar(y, [("x", x, "u")])
        self.assertAlmostEqual(a.por_nombre("constante").valor, 3.0, places=6)
        self.assertAlmostEqual(a.por_nombre("x").valor, 2.0, places=6)
        self.assertAlmostEqual(a.r2, 1.0, places=6)

    def test_recupera_dos_variables(self):
        f = [50.0, 45.0, 40.0, 35.0, 30.0, 25.0, 20.0, 15.0]
        e = [1.0, 2.0, 3.0, 4.0, 1.0, 2.0, 3.0, 4.0]
        y = [100.0 + 0.05 * a + 0.2 * b for a, b in zip(f, e)]
        a = aj.ajustar(y, [("f", f, ""), ("e", e, "")])
        self.assertAlmostEqual(a.por_nombre("f").valor, 0.05, places=6)
        self.assertAlmostEqual(a.por_nombre("e").valor, 0.2, places=6)

    def test_variables_que_se_mueven_juntas_no_se_pueden_separar(self):
        """Es el caso de una tanda sola: combustible y edad son la misma cosa."""

        f = [50.0, 45.0, 40.0, 35.0, 30.0, 25.0]
        e = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]   # exactamente -f/5 + constante
        y = [100.0 + 0.05 * a for a in f]
        with self.assertRaises(ValueError):
            aj.ajustar(y, [("f", f, ""), ("e", e, "")])

    def test_un_coeficiente_ahogado_en_ruido_no_se_distingue_de_cero(self):
        x = [float(i) for i in range(8)]
        ruido = [0.9, -1.1, 1.0, -0.8, 1.2, -1.0, 0.7, -0.9]
        y = [100.0 + 0.01 * a + r for a, r in zip(x, ruido)]
        a = aj.ajustar(y, [("x", x, "")])
        self.assertFalse(a.por_nombre("x").distinguible(a.grados_de_libertad))

    def test_el_valor_critico_es_mas_exigente_con_pocos_datos(self):
        """Con cinco grados el valor real es 2,571; usar 1,96 declararia
        significativo lo que no lo es."""

        self.assertGreater(aj.t_critico(5), aj.t_critico(60))
        self.assertAlmostEqual(aj.t_critico(5), 2.571, places=3)

    def test_el_intervalo_contiene_al_valor(self):
        x = [float(i) for i in range(10)]
        y = [3.0 + 2.0 * v for v in x]
        a = aj.ajustar(y, [("x", x, "")])
        lo, hi = a.por_nombre("x").intervalo(a.grados_de_libertad)
        self.assertLessEqual(lo, 2.0)
        self.assertGreaterEqual(hi, 2.0)

    def test_hacen_falta_mas_observaciones_que_variables(self):
        with self.assertRaises(ValueError):
            aj.ajustar([1.0, 2.0], [("x", [1.0, 2.0], "")])


def _disponibilidad(herramienta, senales=(), continuas=None, estado=disp.COMPLETA):
    d = disp.Disponibilidad(herramienta=herramienta, nombre=herramienta,
                            fuente="f", session_id="s", estado=estado,
                            contexto=("c", "v", "r"), medido_sobre="v / r")
    for senal in senales:
        continua = True if continuas is None else continuas.get(senal, True)
        d.mediciones.append(disp.Medicion(magnitud=senal, senal=senal,
                                          presente=True, hz=20.0,
                                          continua=continua))
    return d


def _sesion(vueltas):
    """Una sesion falsa: lista de (numero, duracion, comparable, motivos)."""

    s = mock.Mock()
    s.disponibilidad = _disponibilidad("vueltas_limpias")
    s.vueltas = []
    for numero, duracion, comparable, motivos in vueltas:
        v = mock.Mock(numero=numero, duracion_s=duracion,
                      comparable=comparable, motivos=motivos)
        s.vueltas.append(v)
    s.comparables = [v for v in s.vueltas if v.comparable]
    return s


class ConsistenciaTest(unittest.TestCase):

    def _analizar(self, vueltas):
        d = _disponibilidad("consistencia")
        with mock.patch.object(co, "evaluar", return_value=d), \
                mock.patch.object(co, "extraer", return_value=_sesion(vueltas)):
            return co.analizar("f", "s")

    def test_una_parada_separa_dos_tandas(self):
        vueltas = [(n, 100.0, True, []) for n in range(1, 6)]
        vueltas.append((6, 120.0, False, ["entrada a boxes"]))
        vueltas += [(n, 99.0, True, []) for n in range(7, 12)]
        c = self._analizar(vueltas)
        self.assertEqual(len(c.tandas), 2)
        self.assertEqual(c.tandas[0].vueltas, [1, 2, 3, 4, 5])

    def test_la_deriva_no_cuenta_como_inconsistencia(self):
        """Un conductor exacto sobre una tanda que deriva da dispersion cero.

        Es la razon de ser de la cifra: contra la media, esos mismos tiempos dan
        una dispersion que no describe al conductor.
        """

        vueltas = [(n, 100.0 - 0.5 * n, True, []) for n in range(1, 9)]
        c = self._analizar(vueltas)
        t = c.tandas[0]
        self.assertAlmostEqual(t.dispersion_sobre_tendencia_s, 0.0, places=3)
        self.assertGreater(t.dispersion_cruda_s, 1.0)

    def test_se_informan_las_tres_cifras(self):
        vueltas = [(n, 100.0 + (n % 2) * 0.4 - 0.1 * n, True, [])
                   for n in range(1, 9)]
        t = self._analizar(vueltas).tandas[0]
        self.assertIsNotNone(t.dispersion_cruda_s)
        self.assertIsNotNone(t.dispersion_sobre_tendencia_s)
        self.assertIsNotNone(t.pendiente_s_por_vuelta)

    def test_una_tanda_corta_no_recibe_tendencia(self):
        """Con tres puntos la recta pasa casi por todos y el residuo es falso."""

        vueltas = [(n, 100.0, True, []) for n in range(1, 4)]
        t = self._analizar(vueltas).tandas[0]
        self.assertIsNone(t.dispersion_sobre_tendencia_s)

    def test_sin_vueltas_suficientes_lo_dice(self):
        c = self._analizar([(1, 100.0, True, [])])
        self.assertIsNotNone(c.impedimento)


class DegradacionTest(unittest.TestCase):

    def _analizar(self, filas, vueltas):
        d = _disponibilidad("degradacion_por_tanda")
        cursor = mock.Mock()
        cursor.fetchall.return_value = filas
        cursor.__enter__ = lambda s: s
        cursor.__exit__ = lambda *a: False
        conexion = mock.Mock()
        conexion.cursor.return_value = cursor
        conexion.__enter__ = lambda s: s
        conexion.__exit__ = lambda *a: False
        with mock.patch.object(dg, "evaluar", return_value=d), \
                mock.patch.object(dg, "extraer", return_value=_sesion(vueltas)), \
                mock.patch.object(dg.db, "obtener_conexion", return_value=conexion):
            return dg.analizar("f", "s")

    def _filas(self, n_vueltas, edades, combustibles, clima=(3.0,)):
        from datetime import datetime, timedelta, timezone
        origen = datetime(2026, 9, 6, tzinfo=timezone.utc)
        filas = []
        for i, (n, e, c) in enumerate(zip(n_vueltas, edades, combustibles)):
            t = origen + timedelta(seconds=i)
            filas.append((t, dg.SENAL_NUMERO, float(n)))
            filas.append((t, dg.SENAL_EDAD, float(e)))
            filas.append((t, dg.SENAL_COMBUSTIBLE, float(c)))
            filas.append((t, dg.SENAL_CLIMA, float(clima[i % len(clima)])))
        return filas

    def test_una_sola_tanda_no_admite_reparto(self):
        """Es la explicacion, no una excusa: dentro de una tanda son la misma
        variable disfrazada."""

        ns = list(range(1, 9))
        filas = self._filas(ns, list(range(1, 9)), [50 - 2 * i for i in range(8)])
        vueltas = [(n, 100.0, True, []) for n in ns]
        d = self._analizar(filas, vueltas)
        self.assertEqual(d.tandas, 1)
        self.assertIn("una sola tanda", d.impedimento)

    def test_la_parada_habilita_el_reparto(self):
        """Al reiniciarse la edad, las dos variables dejan de moverse juntas."""

        ns = list(range(1, 13))
        edades = [1, 2, 3, 4, 5, 6, 1, 2, 3, 4, 5, 6]
        combustible = [50 - 3 * i for i in range(12)]
        tiempos = [100.0 + 0.05 * c + 0.2 * e
                   for c, e in zip(combustible, edades)]
        filas = self._filas(ns, edades, combustible)
        vueltas = [(n, t, True, []) for n, t in zip(ns, tiempos)]
        d = self._analizar(filas, vueltas)
        self.assertEqual(d.tandas, 2)
        self.assertIsNone(d.impedimento)
        self.assertAlmostEqual(d.ajuste.por_nombre("combustible").valor,
                               0.05, places=4)
        self.assertAlmostEqual(d.ajuste.por_nombre("edad_neumatico").valor,
                               0.2, places=4)

    def test_un_clima_que_cambia_se_advierte(self):
        """Lo que se atribuya al neumatico incluira lo que aporto la pista."""

        ns = list(range(1, 13))
        edades = [1, 2, 3, 4, 5, 6, 1, 2, 3, 4, 5, 6]
        combustible = [50 - 3 * i for i in range(12)]
        filas = self._filas(ns, edades, combustible, clima=(3.0, 1.0))
        vueltas = [(n, 100.0, True, []) for n in ns]
        d = self._analizar(filas, vueltas)
        self.assertFalse(d.contexto.clima_constante)
        self.assertTrue(any("pista" in a for a in d.contexto.advertencias()))

    def test_un_clima_constante_no_advierte(self):
        ns = list(range(1, 13))
        edades = [1, 2, 3, 4, 5, 6, 1, 2, 3, 4, 5, 6]
        filas = self._filas(ns, edades, [50 - 3 * i for i in range(12)])
        vueltas = [(n, 100.0 + 0.1 * n, True, []) for n in ns]
        d = self._analizar(filas, vueltas)
        self.assertTrue(d.contexto.clima_constante)
        self.assertEqual(d.contexto.advertencias(), [])


class TraccionTest(unittest.TestCase):

    def test_un_acelerador_binario_no_informa_progresion(self):
        d = _disponibilidad("potencia_y_traccion",
                            senales=(tr.SENAL_ACELERADOR_BINARIO,),
                            continuas={tr.SENAL_ACELERADOR_BINARIO: False})
        self.assertFalse(tr._es_continua(d, tr.SENAL_ACELERADOR_BINARIO))

    def test_se_elige_la_senal_de_acelerador_que_la_fuente_tenga(self):
        d = _disponibilidad("potencia_y_traccion",
                            senales=(tr.SENAL_ACELERADOR_BINARIO,))
        self.assertEqual(tr._senal_presente(d, tr.SENALES_DE_ACELERADOR),
                         tr.SENAL_ACELERADOR_BINARIO)

    def test_el_deslizamiento_derivado_lleva_su_advertencia(self):
        """La resta entre ejes supone que el delantero es libre."""

        from datetime import datetime, timedelta, timezone
        origen = datetime(2026, 9, 6, tzinfo=timezone.utc)
        d = _disponibilidad("potencia_y_traccion",
                            senales=(tr.SENAL_ACELERADOR_CONTINUO,))
        filas = [(origen, tr.SENAL_NUMERO, 1.0)]
        cursor = mock.Mock()
        cursor.fetchall.return_value = filas
        cursor.__enter__ = lambda s: s
        cursor.__exit__ = lambda *a: False
        conexion = mock.Mock()
        conexion.cursor.return_value = cursor
        conexion.__enter__ = lambda s: s
        conexion.__exit__ = lambda *a: False
        with mock.patch.object(tr, "evaluar", return_value=d), \
                mock.patch.object(tr, "fases_de_vuelta", return_value=[]), \
                mock.patch.object(tr.db, "obtener_conexion", return_value=conexion):
            t = tr.analizar("f", "s", 1)
        self.assertTrue(t.deslizamiento_derivado)
        self.assertTrue(any("traccion total" in a for a in t.advertencias))

    def test_deriva_el_deslizamiento_de_las_cuatro_ruedas(self):
        from datetime import datetime, timedelta, timezone
        origen = datetime(2026, 9, 6, tzinfo=timezone.utc)
        filas = [(origen, tr.SENAL_NUMERO, 1.0)]
        for i, rueda in enumerate(tr.RUEDAS_LIBRES):
            filas.append((origen, rueda, 20.0))
        for rueda in tr.RUEDAS_MOTRICES:
            filas.append((origen, rueda, 22.0))
        filas.append((origen, tr.SENAL_ACELERADOR_CONTINUO, 80.0))
        filas.append((origen, tr.SENAL_DISTANCIA, 100.0))
        m = tr._agrupar(filas, tr.SENAL_ACELERADOR_CONTINUO, None, True)
        self.assertAlmostEqual(m[1][0]["deslizamiento"], 0.1, places=6)

    def test_no_se_deriva_con_el_vehiculo_detenido(self):
        """Dividir por una velocidad casi nula daria un numero enorme."""

        from datetime import datetime, timezone
        origen = datetime(2026, 9, 6, tzinfo=timezone.utc)
        filas = [(origen, tr.SENAL_NUMERO, 1.0)]
        for rueda in tr.RUEDAS_LIBRES:
            filas.append((origen, rueda, 0.2))
        for rueda in tr.RUEDAS_MOTRICES:
            filas.append((origen, rueda, 3.0))
        filas.append((origen, tr.SENAL_ACELERADOR_CONTINUO, 80.0))
        filas.append((origen, tr.SENAL_DISTANCIA, 100.0))
        m = tr._agrupar(filas, tr.SENAL_ACELERADOR_CONTINUO, None, True)
        self.assertIsNone(m[1][0]["deslizamiento"])


if __name__ == "__main__":
    unittest.main()
