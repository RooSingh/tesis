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


class ElPicoNoLoDecideUnGolpe(unittest.TestCase):
    """UN IMPACTO NO ES UN APICE DE CURVA.

    Medido el 2026-09-13 sobre las 390.139 muestras de aceleracion guardadas:
    la mediana del modulo es 0,542 g y el percentil 99 es 3,807 g, pero
    **49 muestras pasan de 6 g** y el maximo cae exactamente en 32,768, el tope
    de un entero de 16 bits. No son un error de decodificacion: son golpes.

    Con el maximo, la curva 6 de Spielberg publicaba `18,503 g` sobre treinta y
    tres vueltas. Es la misma razon por la que los bordes ya se tomaban como
    mediana y no como envolvente.
    """

    @staticmethod
    def _vuelta(lateral):
        """Una vuelta con una sola curva, con el pico que se le diga."""
        puntos = [(float(m), 0.0) for m in range(0, 200, 5)]
        puntos += [(float(m), lateral) for m in range(200, 260, 5)]
        puntos += [(float(m), 0.0) for m in range(260, 600, 5)]
        return puntos

    def test_una_vuelta_con_un_golpe_no_arrastra_el_pico(self) -> None:
        vueltas = [self._vuelta(4.2) for _ in range(9)] + [self._vuelta(18.5)]
        catalogo = mod.derivar(vueltas, circuito="prueba")
        self.assertEqual(len(catalogo.curvas), 1)
        self.assertAlmostEqual(catalogo.curvas[0].pico_g, 4.2, places=3,
                               msg="un solo golpe decidio el pico de la curva")

    def test_y_el_apice_y_los_bordes_no_se_mueven(self) -> None:
        """Lo unico que el golpe corrompia era la cifra publicada."""

        limpias = [self._vuelta(4.2) for _ in range(10)]
        con_golpe = [self._vuelta(4.2) for _ in range(9)] + [self._vuelta(18.5)]
        a = mod.derivar(limpias, circuito="prueba").curvas[0]
        b = mod.derivar(con_golpe, circuito="prueba").curvas[0]
        self.assertAlmostEqual(a.apice_m, b.apice_m, places=6)
        self.assertAlmostEqual(a.desde_m, b.desde_m, places=6)
        self.assertAlmostEqual(a.hasta_m, b.hasta_m, places=6)

    def test_el_signo_se_conserva(self) -> None:
        """Hacia que lado gira no se pierde al tomar la mediana."""

        vueltas = [self._vuelta(-3.5) for _ in range(10)]
        self.assertLess(mod.derivar(vueltas, circuito="prueba").curvas[0].pico_g, 0)


if __name__ == "__main__":
    unittest.main()


class UnaCurvaLargaNoSePARTE(unittest.TestCase):
    """Los tramos se agrupan por donde caen, no por donde esta su maximo.

    QUE PASABA. `derivar` agrupaba los tramos de distintas vueltas por su
    **apice**, con 60 m de tolerancia. En una curva corta el pico de aceleracion
    lateral es agudo y cae siempre en el mismo sitio; en una larga la lateral es
    casi constante durante cientos de metros, de modo que **cual de todas las
    muestras resulta la maxima lo deciden el ruido y la linea que se manejo esa
    vuelta**.

    Medido el 2026-09-12 sobre `f1_25:session:1535856705959104755`, entre los
    metros 3.300 y 4.000 de Yas Marina:

        vuelta 3:  3.575,4 -> 3.920,4     apice 3.709,0
        vuelta 4:  3.599,4 -> 3.920,3     apice 3.872,8
        vuelta 5:  3.610,5 -> 3.914,3     apice 3.870,4
        vuelta 6:  3.562,2 -> 3.934,3     apice 3.849,7
        vuelta 7:  3.615,8 -> 3.921,7     apice 3.751,8

    Es UNA curva, detectada en las CINCO vueltas, que empieza siempre alrededor
    del metro 3.590 y termina siempre alrededor del 3.922. Su apice se movio
    163 m. Con 60 m de tolerancia eso fueron dos grupos ---uno de tres vueltas y
    uno de dos--- y el criterio de mayoria descarto el segundo. El circuito
    quedo con catorce curvas de dieciseis, y la 9 que declara el mapa de la FIA
    cayo justo en el hueco.

    Dispersion entre vueltas, mediana sobre todas las curvas del circuito:

        circuito     apice   entrada   salida
        abu-dhabi    104 m     36 m     31 m
        spielberg     54 m     34 m     43 m

    NO SE CAMBIO EL ANCLAJE, que era lo primero que se penso. El apice sigue
    siendo lo que el catalogo publica: medido contra el mapa de la FIA da 6,7 m
    y 11,8 m en Silverstone, y la entrada da 49,2 m y 70,3 m. Lo que estaba mal
    no era **donde se ancla** sino **como se agrupa**.
    """

    @staticmethod
    def _vuelta(tramos):
        """Arma una vuelta cuyos tramos de giro caen donde se pide.

        Cada tramo es (desde, hasta, metro_del_pico): entre `desde` y `hasta` la
        lateral esta sobre el umbral, y en `metro_del_pico` es mayor que en el
        resto, que es lo que `tramos_de_una_vuelta` toma como apice.
        """

        puntos = []
        for metro in range(0, 5300, 5):
            lat = 0.0
            for desde, hasta, pico in tramos:
                if desde <= metro <= hasta:
                    lat = 2.0 if abs(metro - pico) > 7 else 3.0
            puntos.append((float(metro), lat))
        return puntos

    def test_el_apice_que_se_corre_no_parte_la_curva(self) -> None:
        """Los metros son los medidos en Yas Marina, no inventados."""

        vueltas = [
            self._vuelta([(3575, 3920, 3709)]),
            self._vuelta([(3599, 3920, 3873)]),
            self._vuelta([(3610, 3914, 3870)]),
            self._vuelta([(3562, 3934, 3850)]),
            self._vuelta([(3615, 3921, 3752)]),
        ]
        catalogo = mod.derivar(vueltas, circuito="yas-marina")
        self.assertEqual(len(catalogo.curvas), 1,
                         "una curva larga se conto como dos, o se perdio")
        self.assertEqual(catalogo.curvas[0].vueltas_en_que_aparece, 5,
                         "no se reconocio que aparece en las cinco vueltas")

    def test_el_punto_declarado_cae_dentro_de_la_curva(self) -> None:
        """LA COMPROBACION QUE DE VERDAD SIRVE. El mapa declara un **punto** y la
        deteccion encuentra un **intervalo**. Preguntar a cuantos metros esta el
        punto del anclaje es la pregunta equivocada: la buena es si cae adentro
        de la curva que se nombra con ese numero. Asi pasa 6 de 6 sobre los tres
        circuitos medidos, incluida la curva 9 de Yas Marina, que con la
        distancia al apice fallaba por 211 m."""

        vueltas = [self._vuelta([(3575, 3920, 3709)]),
                   self._vuelta([(3599, 3920, 3873)]),
                   self._vuelta([(3610, 3914, 3870)])]
        c = mod.derivar(vueltas, circuito="yas-marina").curvas[0]
        self.assertTrue(c.contiene(3638.1),
                        "la curva 9 declarada por la FIA quedo fuera del tramo")

    def test_dos_curvas_vecinas_de_verdad_no_se_funden(self) -> None:
        """El agrupamiento por solape no puede juntar lo que esta separado: si
        lo hiciera, el arreglo cambiaria un defecto por otro peor."""

        vueltas = [self._vuelta([(1000, 1100, 1050), (1400, 1500, 1450)])] * 3
        catalogo = mod.derivar(vueltas, circuito="dos")
        self.assertEqual(len(catalogo.curvas), 2)

    def test_curvas_pegadas_no_se_encadenan(self) -> None:
        """EL ERROR QUE LOS DATOS REALES AGARRARON Y ESTA PRUEBA NO.

        El primer arreglo unia un tramo al grupo si empezaba antes del final del
        grupo **mas una tolerancia**. Eso encadena: cada tramo que entra estira
        el final, el grupo alcanza al siguiente, y una vuelta entera termina en
        cinco o seis curvas. Silverstone paso de 17 a 6.

        La prueba de arriba no lo vio porque usaba curvas separadas trescientos
        metros. Aca estan pegadas ---veinte metros entre una y la siguiente, que
        es lo que pasa en una chicana--- y encadenar se nota.
        """

        # Separadas 60 m: por encima de `UNION_M`, que une los tramos del
        # mismo sentido a menos de 45 m **antes** de que se agrupen. La primera
        # version las puso a 20 m y estaba probando la union, no el
        # agrupamiento: fallaba sin que hubiera nada roto.
        seguidas = [(1000, 1100, 1050), (1160, 1260, 1210),
                    (1320, 1420, 1370), (1480, 1580, 1530)]
        catalogo = mod.derivar([self._vuelta(seguidas)] * 3, circuito="pegadas")
        self.assertEqual(len(catalogo.curvas), 4,
                         "las curvas pegadas se encadenaron en una sola")

    @staticmethod
    def _chicana(tramos):
        """Como `_vuelta`, pero cada tramo lleva su sentido.

        Hace falta para poder poner dos tramos que **se pisan**: dos del mismo
        sentido a menos de `UNION_M` los une `tramos_de_una_vuelta` antes de que
        lleguen a agruparse, asi que con una sola direccion el caso no se puede
        construir. Una chicana si: derecha e izquierda, y en la transicion los
        dos tramos comparten unos metros.
        """

        puntos = []
        for metro in range(0, 5300, 5):
            lat = 0.0
            for desde, hasta, pico, signo in tramos:
                if desde <= metro <= hasta:
                    v = 2.0 if abs(metro - pico) > 7 else 3.0
                    if abs(v) > abs(lat):
                        lat = v * signo
            puntos.append((float(metro), lat))
        return puntos

    def test_compartir_una_punta_no_vuelve_dos_curvas_en_una(self) -> None:
        """LA QUE SOBREVIVIA A TODAS LAS DEMAS, Y ES LA QUE ROMPIO DE VERDAD.

        Bajar `FRACCION_DE_SOLAPE` hasta que baste con tocarse encadena: cada
        tramo que entra estira el grupo, el grupo alcanza al siguiente, y el
        circuito entero termina en cinco o seis curvas. Eso paso sobre los tres
        circuitos medidos ---Silverstone de 17 a 6--- y ninguna prueba de este
        archivo lo veia, porque todas usaban tramos que no se solapan nunca.

        Aca los dos tramos de una chicana comparten veinte metros en la
        transicion. Con la fraccion en su valor son dos curvas; con «basta con
        tocarse», una sola.
        """

        # DOS TRAMOS DE LA MISMA VUELTA NUNCA SE SOLAPAN: `tramos_de_una_vuelta`
        # los produce disjuntos, recorriendo las muestras en orden. El solape
        # solo puede venir de vueltas DISTINTAS, y por eso el caso necesita una
        # vuelta donde la primera curva se tomo mas larga: ahi el tramo
        # representativo del grupo alcanza al comienzo del tramo siguiente.
        largas = [(1000, 1300, 1150, +1), (1310, 1500, 1400, -1)]
        corta  = [(1000, 1150, 1075, +1), (1160, 1500, 1330, -1)]
        catalogo = mod.derivar(
            [self._chicana(largas), self._chicana(largas), self._chicana(corta)],
            circuito="chicana")
        self.assertEqual(len(catalogo.curvas), 2,
                         "los dos tramos de la chicana se fundieron en uno")
        # NO ALCANZA CON CONTAR. Encadenando, el grupo de la primera curva se
        # traga el tramo de la vuelta corta y ese tramo le falta a la segunda:
        # siguen siendo dos curvas, pero una de ellas pierde una vuelta de
        # evidencia. Con muchas vueltas eso es exactamente lo que hace caer una
        # curva por debajo de la mayoria, que es como se perdia la curva 9 de
        # Yas Marina.
        self.assertEqual([c.vueltas_en_que_aparece for c in catalogo.curvas],
                         [3, 3],
                         "una curva perdio evidencia: su tramo se lo quedo la "
                         "curva anterior")

    def test_un_tramo_que_se_estira_sobre_el_siguiente_no_los_funde(self) -> None:
        """En las vueltas donde dos curvas se toman sin levantar, el tramo de
        una se extiende unos metros sobre la otra. Compartir una punta no las
        vuelve la misma curva: por eso el solape se exige como **fraccion del
        mas corto** y no como «se tocan»."""

        limpia = [(1000, 1100, 1050), (1160, 1260, 1210)]
        pegada = [(1000, 1180, 1050), (1160, 1260, 1210)]   # la primera invade
        catalogo = mod.derivar(
            [self._vuelta(limpia), self._vuelta(limpia), self._vuelta(pegada)],
            circuito="sin-levantar")
        self.assertEqual(len(catalogo.curvas), 2)

    def test_un_incidente_de_una_sola_vuelta_se_sigue_descartando(self) -> None:
        """La mayoria es lo que distingue una curva de un trompo, y cambiar el
        agrupamiento no puede costar eso."""

        vueltas = [self._vuelta([(1000, 1100, 1050)]),
                   self._vuelta([(1000, 1100, 1050)]),
                   self._vuelta([(1000, 1100, 1050), (2500, 2600, 2550)])]
        catalogo = mod.derivar(vueltas, circuito="con-trompo")
        self.assertEqual(len(catalogo.curvas), 1,
                         "el trompo de una sola vuelta entro al catalogo")
