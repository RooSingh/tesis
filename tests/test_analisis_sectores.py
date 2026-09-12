# -*- coding: utf-8 -*-
"""Tiempos por sector, derivados de lo que ya esta guardado.

QUE SE ESTA PROBANDO, Y POR QUE IMPORTA EL «DERIVADO». El simulador **emite**
los tiempos de sector exactos en su paquete de historial, y ese paquete no se
persiste. Lo que hay en la base es el indice de sector muestreado a 20 Hz y el
cronometro de la vuelta. De ahi se puede sacar el tiempo de cada sector, y el
resultado **no es la cifra del juego**: es una derivacion con una incerteza que
vale un intervalo de muestreo. Esa distincion viaja con el resultado o el
numero miente sobre lo que es.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from backend.analisis import sectores as se

ORIGEN = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)
PASO_MS = 50


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


def _filas(guion):
    """Cada entrada es (vehiculo, vuelta, sector, ms_de_vuelta, invalida)."""
    filas = []
    for i, (veh, vuelta, sector, ms, invalida) in enumerate(guion):
        marca = ORIGEN + timedelta(milliseconds=i * PASO_MS)
        filas.append((marca, veh, se.SENAL_VUELTA, float(vuelta), None))
        filas.append((marca, veh, se.SENAL_SECTOR, float(sector), None))
        filas.append((marca, veh, se.SENAL_CRONOMETRO, float(ms), None))
        if invalida is not None:
            filas.append((marca, veh, se.SENAL_INVALIDA, None, bool(invalida)))
    return filas


def _una_vuelta(veh, vuelta, s1_ms, s2_ms, total_ms, invalida=False, paso=500):
    """Una vuelta con sus tres sectores, muestreada cada `paso` milisegundos."""
    guion, t = [], 0
    while t <= total_ms:
        sector = 0 if t < s1_ms else (1 if t < s1_ms + s2_ms else 2)
        guion.append((veh, vuelta, sector, t, invalida))
        t += paso
    return guion


def _extraer(guion, **kw):
    cursor = CursorFalso(_filas(guion))
    with mock.patch.object(se.db, "obtener_conexion",
                           return_value=ConexionFalsa(cursor)):
        return se.extraer("f1_25_udp_simulation", "s", **kw)


class LosTresSectoresSalenDelIndice(unittest.TestCase):

    def test_una_vuelta_da_sus_tres_sectores(self):
        r = _extraer(_una_vuelta("a", 1, 30_000, 40_000, 100_000))
        v = r.vueltas_de("a")[0]
        self.assertAlmostEqual(v.sectores[1], 30.0, delta=0.6)
        self.assertAlmostEqual(v.sectores[2], 40.0, delta=0.6)
        self.assertAlmostEqual(v.sectores[3], 30.0, delta=0.6)

    def test_los_tres_suman_la_vuelta(self):
        """La comprobacion que la derivacion trae puesta."""
        r = _extraer(_una_vuelta("a", 1, 30_000, 40_000, 100_000))
        v = r.vueltas_de("a")[0]
        self.assertAlmostEqual(sum(v.sectores.values()), v.duracion_s, delta=0.01)

    def test_el_indice_que_rebota_no_inventa_sectores(self):
        """El indice de sector rebota cuando hay dos coches mezclados.

        Medido sobre Spa: 3.135 cambios de indice en una sesion de 22 vueltas,
        contra 66 limites reales. Una vuelta recorre sus sectores **hacia
        adelante y una sola vez**: un indice que vuelve atras es un rebote, no
        un limite, y contarlo partiria la vuelta en pedazos.
        """
        guion = _una_vuelta("a", 1, 30_000, 40_000, 100_000)
        # El rebote real **alterna**: 0, 1, 0, 1... alrededor del limite. Un
        # bloque entero puesto en 0 no seria un rebote sino una transicion
        # tardia, y el tiempo de sector correcto ahi **si** seria mas largo.
        for i, (veh, vu, sec, ms, inv) in enumerate(guion):
            if sec == 1 and ms < 32_000 and (ms // 500) % 2 == 1:
                guion[i] = (veh, vu, 0, ms, inv)
        r = _extraer(guion)
        v = r.vueltas_de("a")[0]
        self.assertEqual(sorted(v.sectores), [1, 2, 3])
        self.assertAlmostEqual(v.sectores[1], 30.0, delta=0.6)

    def test_una_vuelta_sin_los_tres_sectores_no_se_publica(self):
        """Media vuelta no tiene tiempos de sector: tiene dos de tres."""
        guion = [("a", 1, 0, t, False) for t in range(0, 20_000, 500)]
        r = _extraer(guion)
        self.assertEqual(r.vueltas_de("a"), [])

    def test_una_vuelta_invalidada_no_entra(self):
        r = _extraer(_una_vuelta("a", 1, 30_000, 40_000, 100_000, invalida=True))
        self.assertEqual(r.vueltas_de("a"), [])


class ElResultadoNoDependeDelOrdenDeLasFilas(unittest.TestCase):
    """El defecto que hizo que el mismo dato diera dos numeros.

    Las tres señales de una muestra viajan en el mismo paquete y llegan con la
    misma marca de tiempo. **La base no garantiza en que orden devuelve filas
    que empatan**, y procesandolas de a una el emparejamiento del sector con el
    cronometro dependia de cual llegara primero.

    Se vio corriendo el analisis dos veces sobre la sesion de Shanghai: el
    «sobre la mesa» de un mismo coche dio 0,341 s y despues 0,491. **Un analisis
    que no repite su propio numero no es una medicion.**
    """

    def test_dar_vuelta_las_senales_de_un_instante_no_cambia_nada(self):
        guion = _una_vuelta("a", 1, 30_000, 40_000, 100_000)
        derecho = _filas(guion)
        # Las mismas filas, con las de cada instante al reves.
        al_reves = []
        for i in range(0, len(derecho), 3):
            al_reves.extend(reversed(derecho[i:i + 3]))

        def correr(filas):
            cursor = CursorFalso(filas)
            with mock.patch.object(se.db, "obtener_conexion",
                                   return_value=ConexionFalsa(cursor)):
                return se.extraer("f1_25_udp_simulation", "s")

        a = correr(derecho).vueltas_de("a")[0]
        b = correr(al_reves).vueltas_de("a")[0]
        self.assertEqual(a.sectores, b.sectores)
        self.assertEqual(a.duracion_s, b.duracion_s)

    def test_la_consulta_pide_un_orden_total(self):
        """Sin `signal_name` en el orden, dos corridas leen distinto.

        La agrupacion por instante ya lo resuelve; el orden total lo deja
        ademas reproducible al depurar, que es cuando hace falta.
        """
        self.assertIn("order by vehicle_id, timestamp, signal_name", se.CONSULTA)


class LaIncertezaSeDeclara(unittest.TestCase):

    def test_el_resultado_dice_cuanto_vale_su_propia_precision(self):
        """Un tiempo de sector derivado a 20 Hz no vale una milesima.

        El limite se ve en la primera muestra **despues** de cruzarlo, asi que
        el error es a lo sumo un intervalo de muestreo. Publicar tres decimales
        sin decirlo seria declarar una precision que no se tiene.
        """
        r = _extraer(_una_vuelta("a", 1, 30_000, 40_000, 100_000, paso=50))
        self.assertAlmostEqual(r.incerteza_s, 0.05, places=3)
        self.assertIn("derivado", r.origen)

    def test_el_origen_dice_que_el_juego_publica_la_cifra_exacta(self):
        """Callarlo haria pasar la derivacion por la medicion del juego."""
        r = _extraer(_una_vuelta("a", 1, 30_000, 40_000, 100_000))
        self.assertIn("session_history", r.origen)


class QuienEsMejorEnCadaSector(unittest.TestCase):

    @staticmethod
    def _dos_pilotos():
        guion = []
        # «a» es mejor en el 1; «b», en el 2 y el 3.
        guion += _una_vuelta("a", 1, 30_000, 42_000, 102_000)
        guion += _una_vuelta("a", 2, 29_000, 41_000, 100_000)
        guion += _una_vuelta("b", 1, 31_000, 39_000, 100_000)
        guion += _una_vuelta("b", 2, 32_000, 40_000, 101_000)
        return guion

    def test_cada_sector_tiene_dueno(self):
        r = _extraer(self._dos_pilotos())
        self.assertEqual(r.dueno_del_sector(1).vehiculo, "a")
        self.assertEqual(r.dueno_del_sector(2).vehiculo, "b")

    def test_la_vuelta_ideal_suma_los_mejores_propios(self):
        """No es una vuelta que se corrio: es la que se podria haber corrido."""
        r = _extraer(self._dos_pilotos())
        a = r.piloto("a")
        self.assertAlmostEqual(a.vuelta_ideal_s,
                               sum(a.mejor_por_sector[s].duracion_s
                                   for s in (1, 2, 3)), delta=0.01)

    def test_la_vuelta_ideal_nunca_es_peor_que_la_mejor_corrida(self):
        """Si lo fuera, la derivacion se contradice a si misma."""
        r = _extraer(self._dos_pilotos())
        for p in r.pilotos:
            self.assertLessEqual(p.vuelta_ideal_s, p.mejor_vuelta_s + 0.01)

    def test_sin_dos_pilotos_no_se_inventa_una_comparacion(self):
        r = _extraer(_una_vuelta("a", 1, 30_000, 40_000, 100_000))
        self.assertEqual(len(r.pilotos), 1)
        self.assertEqual(r.dueno_del_sector(1).vehiculo, "a")


if __name__ == "__main__":
    unittest.main()
