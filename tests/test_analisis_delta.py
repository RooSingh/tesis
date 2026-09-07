# -*- coding: utf-8 -*-
"""La traza de delta acumulado entre dos vueltas.

Las vueltas se construyen a mano con un perfil conocido, de modo que **el delta
correcto se sabe de antemano** y la prueba compara contra el, y no contra otra
corrida del mismo codigo.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from backend.analisis import delta as dl
from backend.analisis import disponibilidad as disp
from backend.analisis.vueltas import SinVueltas

ORIGEN = datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc)
LARGO_M = 1000.0


class CursorFalso:
    def __init__(self, filas):
        self.filas = filas

    def execute(self, *_a, **_k):
        return None

    def fetchall(self):
        return self.filas

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class ConexionFalsa:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _disponibilidad(estado=disp.COMPLETA):
    return disp.Disponibilidad(
        herramienta="delta_acumulado", nombre="Traza de delta acumulado",
        fuente="f1_25_udp_simulation", session_id="s", estado=estado,
        contexto=("c", "v", "r"), medido_sobre="v / r")


def _vuelta(numero: int, velocidad_ms: float, desde_s: float,
            paso_ms: int = 50, largo_m: float = LARGO_M) -> list[tuple]:
    """Una vuelta a velocidad constante, con su distancia y su marca de tiempo."""

    filas = [(ORIGEN + timedelta(seconds=desde_s), dl.SENAL_NUMERO,
              float(numero))]
    t = 0.0
    distancia = 0.0
    while distancia <= largo_m:
        marca = ORIGEN + timedelta(seconds=desde_s + t)
        filas.append((marca, dl.SENAL_VELOCIDAD, velocidad_ms * 3.6))
        filas.append((marca, dl.SENAL_DISTANCIA, distancia))
        t += paso_ms / 1000.0
        distancia = velocidad_ms * t
    return filas


def _comparar(filas, vuelta_a=1, vuelta_b=2, disponibilidad=None, **kw):
    d = disponibilidad or _disponibilidad()
    cursor = CursorFalso(filas)
    with mock.patch.object(dl, "evaluar", return_value=d), \
            mock.patch.object(dl.db, "obtener_conexion",
                              return_value=ConexionFalsa(cursor)):
        return dl.comparar("f1_25_udp_simulation", "s", vuelta_a, vuelta_b, **kw)


class TrazaTest(unittest.TestCase):

    def test_dos_vueltas_iguales_dan_delta_cero(self):
        filas = _vuelta(1, 50.0, 0.0) + _vuelta(2, 50.0, 100.0)
        t = _comparar(filas)
        self.assertTrue(t.puntos)
        self.assertTrue(all(abs(s) < 1e-6 for _, s in t.puntos))

    def test_una_vuelta_mas_lenta_pierde_tiempo_de_forma_creciente(self):
        """A velocidad constante el delta crece linealmente con la distancia."""

        filas = _vuelta(1, 40.0, 0.0) + _vuelta(2, 50.0, 100.0)
        t = _comparar(filas)
        deltas = [s for _, s in t.puntos]
        self.assertGreater(deltas[-1], 0)
        self.assertEqual(deltas, sorted(deltas))

    def test_el_delta_final_es_el_que_la_fisica_predice(self):
        """Mil metros a 40 m/s son 25 s; a 50 m/s, 20 s. La diferencia es 5 s."""

        filas = _vuelta(1, 40.0, 0.0) + _vuelta(2, 50.0, 100.0)
        t = _comparar(filas, paso_m=10.0)
        self.assertAlmostEqual(t.delta_final_s, 5.0, places=1)

    def test_el_signo_dice_quien_perdia(self):
        """Positivo significa que la primera vuelta iba perdiendo."""

        lenta_primero = _comparar(_vuelta(1, 40.0, 0.0) + _vuelta(2, 50.0, 100.0))
        rapida_primero = _comparar(_vuelta(1, 50.0, 0.0) + _vuelta(2, 40.0, 100.0))
        self.assertGreater(lenta_primero.delta_final_s, 0)
        self.assertLess(rapida_primero.delta_final_s, 0)


class ResiduoTest(unittest.TestCase):
    """El cierre contra los cronometros es la comprobacion interna."""

    def test_el_residuo_compara_los_dos_caminos(self):
        filas = _vuelta(1, 40.0, 0.0) + _vuelta(2, 50.0, 100.0)
        t = _comparar(filas, cronometros={1: 25.0, 2: 20.0})
        self.assertAlmostEqual(t.diferencia_cronometros_s, 5.0, places=3)
        self.assertLess(abs(t.residuo_s), 0.1)

    def test_sin_cronometros_no_se_inventa_un_residuo(self):
        filas = _vuelta(1, 40.0, 0.0) + _vuelta(2, 50.0, 100.0)
        t = _comparar(filas)
        self.assertIsNone(t.residuo_s)
        self.assertIsNone(t.diferencia_cronometros_s)

    def test_el_residuo_no_se_reparte_en_la_traza(self):
        """Corregirlo haria que la traza cierre por construccion.

        Con un cronometro deliberadamente falso, el delta final no cambia: lo que
        cambia es el residuo, que es donde la discrepancia queda a la vista.
        """

        filas = _vuelta(1, 40.0, 0.0) + _vuelta(2, 50.0, 100.0)
        honesto = _comparar(filas, cronometros={1: 25.0, 2: 20.0})
        falso = _comparar(filas, cronometros={1: 25.0, 2: 18.0})
        self.assertAlmostEqual(honesto.delta_final_s, falso.delta_final_s,
                               places=6)
        self.assertNotAlmostEqual(honesto.residuo_s, falso.residuo_s, places=3)


class InterpolacionTest(unittest.TestCase):

    def test_no_se_extrapola_fuera_de_lo_medido(self):
        muestras = [(0.0, 0.0, None), (1.0, 50.0, None)]
        self.assertIsNone(dl._tiempo_en(muestras, 80.0))
        self.assertIsNone(dl._tiempo_en(muestras, -10.0))

    def test_interpola_linealmente_entre_dos_muestras(self):
        muestras = [(0.0, 0.0, None), (1.0, 50.0, None)]
        self.assertAlmostEqual(dl._tiempo_en(muestras, 25.0), 0.5, places=6)

    def test_la_traza_no_pasa_del_tramo_comun(self):
        """Mas alla de donde una de las dos deja de tener dato, no hay delta."""

        filas = _vuelta(1, 40.0, 0.0, largo_m=1000.0) + \
            _vuelta(2, 50.0, 100.0, largo_m=600.0)
        t = _comparar(filas)
        self.assertLessEqual(t.puntos[-1][0], 610.0)
        self.assertLessEqual(t.largo_comun_m, 610.0)

    def test_los_retrocesos_de_distancia_se_descartan(self):
        """La distancia retrocede al cruzar la linea y al reponer en pista."""

        muestras = [(0.0, 0.0, None), (1.0, 50.0, None), (2.0, 20.0, None),
                    (3.0, 100.0, None)]
        limpio = dl._monotonas(muestras)
        self.assertEqual([m[1] for m in limpio], [0.0, 50.0, 100.0])


class TramosTest(unittest.TestCase):

    def test_encuentra_donde_cambio_de_manos_el_tiempo(self):
        traza = dl.Traza(session_id="s", fuente="f", vuelta_a=1, vuelta_b=2,
                         paso_m=10.0)
        traza.puntos = [(0.0, 0.0), (10.0, 0.01), (20.0, 0.71), (30.0, 0.72)]
        peor = dl.tramos_dominantes(traza, 1)[0]
        self.assertEqual((peor.desde_m, peor.hasta_m), (10.0, 20.0))
        self.assertAlmostEqual(peor.delta_s, 0.70, places=3)

    def test_un_tramo_ganado_pesa_tanto_como_uno_perdido(self):
        """Se ordena por magnitud y no por signo: los dos informan."""

        traza = dl.Traza(session_id="s", fuente="f", vuelta_a=1, vuelta_b=2,
                         paso_m=10.0)
        traza.puntos = [(0.0, 0.0), (10.0, -0.90), (20.0, -0.85)]
        peor = dl.tramos_dominantes(traza, 1)[0]
        self.assertAlmostEqual(peor.delta_s, -0.90, places=3)

    def test_sin_puntos_no_hay_tramos(self):
        traza = dl.Traza(session_id="s", fuente="f", vuelta_a=1, vuelta_b=2,
                         paso_m=10.0)
        self.assertEqual(dl.tramos_dominantes(traza), [])


class NegativasTest(unittest.TestCase):

    def test_una_fuente_sin_vueltas_se_rechaza_con_su_motivo(self):
        d = _disponibilidad(estado=disp.IMPOSIBLE)
        d.impedimentos.append("el vehiculo no da vueltas a nada")
        with self.assertRaises(SinVueltas):
            _comparar([], disponibilidad=d)

    def test_una_vuelta_sin_muestras_se_rechaza(self):
        filas = _vuelta(1, 40.0, 0.0)
        with self.assertRaises(dl.SinTraza) as caja:
            _comparar(filas, vuelta_a=1, vuelta_b=2)
        self.assertIn("vuelta 2", str(caja.exception))

    def test_dos_vueltas_sin_tramo_comun_se_rechazan(self):
        """No se completa el tramo que una de las dos no recorrio."""

        filas = _vuelta(1, 40.0, 0.0, largo_m=100.0)
        segunda = [(ORIGEN + timedelta(seconds=100), dl.SENAL_NUMERO, 2.0)]
        for i in range(4):
            marca = ORIGEN + timedelta(seconds=100 + i * 0.05)
            segunda.append((marca, dl.SENAL_DISTANCIA, 500.0 + i * 10))
        with self.assertRaises(dl.SinTraza) as caja:
            _comparar(filas + segunda)
        self.assertIn("tramo", str(caja.exception))


if __name__ == "__main__":
    unittest.main()
