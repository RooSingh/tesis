# -*- coding: utf-8 -*-
"""Pruebas de la derivacion de curvas desde el dato.

El modulo existe para no escribir el trazado a mano. Estas pruebas verifican que
lo derivado sea utilizable, y hay dos criterios distintos:

* **con recorridos construidos aca**, donde quien escribe la prueba sabe cuantas
  curvas puso y donde. Es lo que evita que la prueba herede el error del codigo;

* **con las capturas reales**, donde el criterio no es el numero oficial de
  curvas del circuito —eso seria volver a depender de un documento externo— sino
  **la repeticion**: vueltas distintas del mismo circuito tienen que encontrar las
  curvas en los mismos metros.
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from backend.analisis import curvas as mod  # noqa: E402


def recorrido(curvas_en: list[tuple[float, float, float]],
              largo: float = 4000.0, paso: float = 5.0) -> list[tuple[float, float]]:
    """Una vuelta inventada, con las curvas puestas donde dice el argumento.

    Cada curva es (centro, medio ancho, pico). Fuera de ellas el vehiculo va
    derecho, con una aceleracion lateral chica que imita la correccion de
    trayectoria en recta.
    """

    puntos = []
    distancia = 0.0
    while distancia < largo:
        lateral = 0.05
        for centro, ancho, pico in curvas_en:
            if abs(distancia - centro) <= ancho:
                # Forma de campana: cero en los bordes, pico en el centro.
                lateral = pico * math.cos((distancia - centro) / ancho * math.pi / 2)
        puntos.append((distancia, lateral))
        distancia += paso
    return puntos


class DerivacionSobreRecorridoConstruido(unittest.TestCase):

    def test_encuentra_las_curvas_que_se_pusieron(self):
        puesto = [(500.0, 60.0, 3.0), (1500.0, 80.0, -4.0), (3000.0, 50.0, 2.5)]
        catalogo = mod.derivar([recorrido(puesto)] * 3, circuito="inventado")

        self.assertEqual(len(catalogo.curvas), 3)
        for curva, (centro, _, _) in zip(catalogo.curvas, puesto):
            self.assertAlmostEqual(curva.apice_m, centro, delta=20.0)

    def test_no_inventa_curvas_en_la_recta(self):
        """Una vuelta sin curvas no produce ninguna."""

        catalogo = mod.derivar([recorrido([])] * 3, circuito="recta")
        self.assertEqual(catalogo.curvas, [])

    def test_dos_curvas_no_ocupan_los_mismos_metros(self):
        """Un metro pertenece a una sola curva, o el catalogo no ubica nada.

        La version anterior tomaba los bordes como la envolvente de todas las
        vueltas, y en las vueltas donde dos curvas seguidas se toman sin levantar
        el tramo de una se extendia sobre la otra.
        """

        # Dos curvas pegadas: en una vuelta se toman juntas, en otras separadas.
        juntas = recorrido([(500.0, 130.0, 3.0)])
        separadas = recorrido([(430.0, 45.0, 3.0), (580.0, 45.0, 3.0)])
        catalogo = mod.derivar([separadas, separadas, juntas], circuito="pegadas")

        for anterior, siguiente in zip(catalogo.curvas, catalogo.curvas[1:]):
            self.assertLessEqual(
                anterior.hasta_m, siguiente.desde_m,
                f"la curva {anterior.numero} invade a la {siguiente.numero}")

    def test_un_tramo_de_una_sola_vuelta_no_es_una_curva(self):
        """Es el criterio que separa una curva de un trompo.

        Un vehiculo cruzado genera aceleracion lateral sostenida, que es
        exactamente la firma que este modulo busca. Lo que lo distingue de una
        curva es que **no esta ahi la vuelta siguiente**.
        """

        normales = [(500.0, 60.0, 3.0), (1500.0, 80.0, -4.0)]
        con_trompo = recorrido(normales + [(2500.0, 40.0, 5.0)])
        catalogo = mod.derivar(
            [recorrido(normales), recorrido(normales), con_trompo],
            circuito="con trompo")

        self.assertEqual(len(catalogo.curvas), 2)
        self.assertTrue(all(abs(c.apice_m - 2500.0) > 200 for c in catalogo.curvas))

    def test_la_mayoria_no_colapsa_con_dos_vueltas(self):
        """Con dos vueltas, una mayoria de una vuelta no es una mayoria.

        Con redondeo al mas cercano, dos vueltas daban 1,2 -> 1 y bastaba que un
        tramo apareciera en una sola de las dos. Sobre las capturas reales eso
        producia dieciocho curvas donde con tres vueltas salian catorce.
        """

        normales = [(500.0, 60.0, 3.0)]
        catalogo = mod.derivar(
            [recorrido(normales), recorrido(normales + [(2500.0, 40.0, 5.0)])],
            circuito="dos vueltas")
        self.assertEqual(len(catalogo.curvas), 1)


class Ubicacion(unittest.TestCase):

    def setUp(self):
        puesto = [(500.0, 60.0, 3.0), (1500.0, 80.0, -4.0), (3000.0, 50.0, 2.5)]
        self.catalogo = mod.derivar([recorrido(puesto)] * 3, circuito="inventado")

    def test_dentro_de_una_curva_la_nombra(self):
        self.assertEqual(self.catalogo.ubicar(500.0), "curva 1")
        self.assertEqual(self.catalogo.ubicar(1500.0), "curva 2")

    def test_fuera_de_toda_curva_se_ubica_respecto_de_la_mas_cercana(self):
        texto = self.catalogo.ubicar(1000.0)
        self.assertIn("curva", texto)
        self.assertTrue("antes" in texto or "despues" in texto, texto)

    def test_sin_catalogo_devuelve_el_metro_y_no_una_cadena_vacia(self):
        """Una anotacion sin lugar es peor que una con el lugar aproximado."""

        vacio = mod.CatalogoDeCurvas(circuito="sin aprender")
        self.assertEqual(vacio.ubicar(812.0), "metro 812")


class SobreLasCapturasReales(unittest.TestCase):
    """El criterio es la repeticion entre vueltas, no un numero externo."""

    CAPTURA = (RAIZ / "datasets" / "f1_25" / "capturas"
               / "20260831_2022_hungaroring_contrarreloj.f1raw")

    def vueltas(self):
        from backend import f1_capture, f1_udp

        marcos: dict[int, dict] = {}
        for datagrama in f1_capture.leer_captura(self.CAPTURA):
            try:
                d = f1_udp.decodificar(datagrama.carga)
            except Exception:
                continue
            propio = d.get("vehiculo_propio")
            if not d.get("decodificado") or propio is None:
                continue
            e = marcos.setdefault(d["cabecera"]["frame_identifier"], {})
            if d["paquete"] == "motion":
                e["lat"] = propio["g_force_lateral"]
            elif d["paquete"] == "lap_data":
                e["dist"] = propio["lap_distance_m"]
                e["vuelta"] = propio["current_lap_num"]
                e["invalida"] = propio["current_lap_invalid"]

        completos = [e for e in marcos.values()
                     if {"lat", "dist", "vuelta", "invalida"} <= e.keys()]
        salida = []
        for numero in sorted({e["vuelta"] for e in completos}):
            de_la_vuelta = [e for e in completos if e["vuelta"] == numero]
            if any(e["invalida"] for e in de_la_vuelta):
                continue
            puntos = sorted((e["dist"], e["lat"]) for e in de_la_vuelta
                            if e["dist"] > 0)
            if puntos and puntos[-1][0] > 4000:
                salida.append(puntos)
        return salida

    def test_cada_vuelta_encuentra_las_curvas_en_los_mismos_metros(self):
        if not self.CAPTURA.exists():
            self.skipTest(f"captura ausente: {self.CAPTURA.name}")
        vueltas = self.vueltas()
        if len(vueltas) < 2:
            self.skipTest("hacen falta al menos dos vueltas limpias")

        catalogo = mod.derivar(vueltas, circuito="hungaroring")
        self.assertGreater(len(catalogo.curvas), 8,
                           "un circuito de 4,4 km no tiene ocho curvas o menos")

        # Se vuelve a contar aca, desde los tramos crudos, en cuantas vueltas
        # aparece cada curva del catalogo. No se lee `vueltas_en_que_aparece`:
        # eso seria preguntarle al catalogo si esta de acuerdo consigo mismo.
        minimo = math.ceil(len(vueltas) * mod.FRACCION_MINIMA_DE_VUELTAS)
        por_vuelta = [mod.tramos_de_una_vuelta(v) for v in vueltas]
        en_todas = 0
        for curva in catalogo.curvas:
            presentes = sum(
                1 for tramos in por_vuelta
                if min((abs(t["apice"] - curva.apice_m) for t in tramos),
                       default=1e9) <= mod.TOLERANCIA_AGRUPAMIENTO_M
            )
            with self.subTest(curva=curva.numero):
                self.assertGreaterEqual(
                    presentes, minimo,
                    f"la curva {curva.numero} aparece en {presentes} de "
                    f"{len(vueltas)} vueltas, y hacen falta {minimo}")
            if presentes == len(vueltas):
                en_todas += 1

        # Y la mayor parte tiene que aparecer en **todas**. Que algunas falten en
        # alguna vuelta es esperable —la vuelta de salida de boxes se conduce
        # distinto— pero si la mayoria fallara, lo que el metodo encuentra no
        # seria el circuito.
        self.assertGreaterEqual(
            en_todas, len(catalogo.curvas) * 0.7,
            f"solo {en_todas} de {len(catalogo.curvas)} curvas aparecen en "
            f"todas las vueltas")

    def test_ninguna_curva_del_catalogo_invade_a_la_siguiente(self):
        if not self.CAPTURA.exists():
            self.skipTest(f"captura ausente: {self.CAPTURA.name}")
        vueltas = self.vueltas()
        if len(vueltas) < 2:
            self.skipTest("hacen falta al menos dos vueltas limpias")

        catalogo = mod.derivar(vueltas, circuito="hungaroring")
        for anterior, siguiente in zip(catalogo.curvas, catalogo.curvas[1:]):
            with self.subTest(curva=anterior.numero):
                self.assertLessEqual(anterior.hasta_m, siguiente.desde_m)


if __name__ == "__main__":
    unittest.main()
