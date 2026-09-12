# -*- coding: utf-8 -*-
"""Que puede afirmar el catalogo de curvas, y contra que se comprueba.

EL PROBLEMA QUE ESTE ARNES RESUELVE. El nombre de una curva es anotacion
externa y el metro es medicion. Una prueba que compare el nombre contra la
fuente que lo publica no comprueba nada ---seria copiar la cita dos veces--- y
una que compare el metro contra el mismo dato del que salio, tampoco.

Lo que si se puede comprobar es el **anclaje**: que el metro que el catalogo le
adosa a un nombre caiga donde una fuente independiente dice que esta esa curva.

Y para Silverstone esa fuente existe y es rara: el mapa de circuito de la FIA
del Gran Premio 2025 no publica los metros de las curvas, pero **publica dos
limites de sector dichos en curvas**:

    Sector 1 -- 110 m antes de la curva 6
    Sector 2 -- 50 m despues de la curva 14

Y los limites de sector de esta sesion estan **medidos** por `sector_index`, que
el paquete de vuelta del simulador declara en cada muestra. Cruzando las dos
cosas se obtiene la posicion de dos curvas numeradas sin usar el catalogo, y el
catalogo tiene que caer ahi. Son dos puntos de un trazado de 5.887,6 m, uno en
cada mitad, y ninguno de los dos participo de armar el catalogo.
"""

from __future__ import annotations

import unittest

from backend import catalogo_curvas as cat


#: Limites de sector medidos sobre `f1_25:session:1758301748294876464`, vuelta 2,
#: por `sector_index`. Ver `/sesiones/{id}/trazado`, campo `sectores`.
SILVERSTONE_SECTOR_2_M = 1815.2
SILVERSTONE_SECTOR_3_M = 4294.6

#: Lo que el mapa de la FIA declara, en curvas y no en metros.
#: https://www.fia.com/ -- Circuit Map, British Grand Prix 2025, version 2.
FIA_S1_ANTES_DE_LA_6_M = 110.0
FIA_S2_DESPUES_DE_LA_14_M = 50.0

#: Longitud de linea central que declara el mismo mapa.
FIA_LARGO_DECLARADO_M = 5891.0


class ElAnclajeSeComprubaContraLaFIA(unittest.TestCase):
    """Las dos curvas cuya posicion se puede derivar sin tocar el catalogo."""

    #: Cuanto puede alejarse el anclaje del punto derivado antes de que la
    #: afirmacion deje de ser defendible. El trazado se dibuja con muestras cada
    #: ~3 m y la curva 6 se toma a 136 km/h: 15 m es medio segundo de auto.
    TOLERANCIA_M = 15.0

    def _anclaje_de_la_numerada(self, numero: int) -> float:
        curvas = [c for c in cat.curvas_de("silverstone")
                  if numero in c.numeros_cronometraje]
        self.assertEqual(len(curvas), 1,
                         f"la curva {numero} tiene {len(curvas)} zonas y debe tener una")
        return curvas[0].metro_medido

    def test_la_curva_6_cae_donde_la_fia_la_pone(self) -> None:
        """Brooklands, derivada del limite de sector 1 y no del catalogo."""

        derivado = SILVERSTONE_SECTOR_2_M + FIA_S1_ANTES_DE_LA_6_M
        self.assertAlmostEqual(self._anclaje_de_la_numerada(6), derivado,
                               delta=self.TOLERANCIA_M)

    def test_la_curva_14_cae_donde_la_fia_la_pone(self) -> None:
        """Chapel, derivada del limite de sector 2."""

        derivado = SILVERSTONE_SECTOR_3_M - FIA_S2_DESPUES_DE_LA_14_M
        self.assertAlmostEqual(self._anclaje_de_la_numerada(14), derivado,
                               delta=self.TOLERANCIA_M)


class DeDondeSaleLaPosicionDeUnaCurvaDeclarada(unittest.TestCase):
    """La aritmetica del cruce, aislada, porque es donde un signo se da vuelta.

    El mapa de la FIA dice «Sector 1 -- 110 m antes de la curva 6». El limite de
    sector esta medido. La curva esta 110 m **despues** del limite. Invertir esa
    resta da un punto a 220 m del verdadero y la comprobacion sigue pareciendo
    una comprobacion: por eso se ejerce con los dos casos de Silverstone, cuya
    respuesta se conoce.
    """

    def test_un_limite_antes_de_la_curva_la_pone_mas_adelante(self) -> None:
        decl = cat.DeclaracionDeSector(curva=6, metros=110.0, lado="antes")
        self.assertAlmostEqual(
            cat.curva_declarada_en(decl, SILVERSTONE_SECTOR_2_M), 1925.2, places=1)

    def test_un_limite_despues_de_la_curva_la_pone_mas_atras(self) -> None:
        decl = cat.DeclaracionDeSector(curva=14, metros=50.0, lado="despues")
        self.assertAlmostEqual(
            cat.curva_declarada_en(decl, SILVERSTONE_SECTOR_3_M), 4244.6, places=1)

    def test_los_dos_lados_no_dan_lo_mismo(self) -> None:
        """Si dieran lo mismo, `lado` no estaria haciendo nada y la prueba de
        arriba pasaria por casualidad."""

        antes = cat.curva_declarada_en(
            cat.DeclaracionDeSector(curva=6, metros=110.0, lado="antes"), 1000.0)
        despues = cat.curva_declarada_en(
            cat.DeclaracionDeSector(curva=6, metros=110.0, lado="despues"), 1000.0)
        self.assertEqual(antes - despues, 220.0)

    def test_un_lado_que_no_existe_no_se_adivina(self) -> None:
        """«a la altura de la curva 6» no es ni antes ni despues, y resolverlo
        por omision convertiria una lectura dudosa del mapa en un numero."""

        with self.assertRaises(ValueError):
            cat.curva_declarada_en(
                cat.DeclaracionDeSector(curva=6, metros=110.0, lado="cerca"), 1000.0)

    def test_silverstone_guarda_las_declaraciones_que_lo_verifican(self) -> None:
        """No alcanza con haber hecho la comprobacion una vez: si el anclaje se
        re-mide, tiene que volver a comprobarse contra lo mismo."""

        self.assertEqual(len(cat.SILVERSTONE_SECTORES_FIA), 2)
        for decl in cat.SILVERSTONE_SECTORES_FIA:
            self.assertIn(decl.lado, ("antes", "despues"))


class QueHaceQueUNAVUELTASIRVAPARAANCLAR(unittest.TestCase):
    """La pregunta que hay que hacerle a una vuelta, y la que yo le hacia.

    EL ERROR, ESCRITO PARA QUE NO SE REPITA. El primer censo de circuitos
    descarto siete de los once usando `analisis/vueltas` ---el filtro de
    «vueltas limpias»--- y el `cierre_m` del trazado pedido **sin decir que
    vuelta**. Las dos cosas responden otra pregunta:

    - «vuelta limpia» decide si el **tiempo** de esa vuelta es comparable con
      otro, y descarta por entrada a boxes o por no haber presenciado el
      comienzo. Una vuelta con entrada a boxes puede describir el circuito
      perfectamente;
    - el trazado sin `vuelta=` deja que el punto de acceso elija, y cuando
      elige mal el lazo no cierra y `sector_index` parece declarar cuatro,
      cinco o seis sectores.

    Yo tome ese segundo sintoma como una **senal independiente** que confirmaba
    al primero. No lo era: las dos salian de la misma mala eleccion de vuelta.
    Pedida por vuelta, cada circuito declara tres sectores, incluso las vueltas
    con 684 m de cierre.

    LA PREGUNTA CORRECTA es de cobertura: que fraccion del largo abarcan las
    muestras y cual es el hueco mas grande. Una vuelta que cubre el circuito
    sirve para anclar aunque su tiempo no sirva para comparar.
    """

    def test_una_vuelta_entera_cubre_todo_y_no_tiene_huecos(self) -> None:
        metros = [float(m) for m in range(0, 5000, 5)]
        c = cat.cobertura_de_la_vuelta(metros, 5000.0)
        self.assertAlmostEqual(c.fraccion, 1.0, places=2)
        self.assertLessEqual(c.hueco_mayor_m, 5.0)

    def test_una_vuelta_que_empieza_tarde_lo_dice(self) -> None:
        """Austin: la captura arranco en el metro 126 de 5.513. Eso no la
        invalida, pero tiene que estar dicho."""

        metros = [float(m) for m in range(126, 5502, 4)]
        c = cat.cobertura_de_la_vuelta(metros, 5513.0)
        self.assertGreater(c.fraccion, 0.97)
        self.assertAlmostEqual(c.desde_m, 126.0, places=1)
        self.assertAlmostEqual(c.hasta_m, 5498.0, places=1)
        # EL HUECO DE LA LARGADA CUENTA COMO HUECO. Una mutacion que lo sacaba
        # del calculo no mataba ninguna prueba, y es exactamente el caso de
        # Austin: sin esto, la vuelta se anuncia sin huecos y los 126 m que le
        # faltan ---donde podria haber una curva--- no se declaran en ningun
        # lado.
        self.assertAlmostEqual(c.hueco_mayor_m, 126.0, places=1)

    def test_el_hueco_de_la_meta_tambien_cuenta(self) -> None:
        """El otro extremo del mismo defecto: una vuelta que corta antes de la
        linea se pierde lo que haya entre el ultimo metro y el largo."""

        metros = [float(m) for m in range(0, 4800, 5)]
        c = cat.cobertura_de_la_vuelta(metros, 5000.0)
        self.assertAlmostEqual(c.hueco_mayor_m, 205.0, places=1)

    def test_un_hueco_en_el_medio_no_se_disimula_con_la_fraccion(self) -> None:
        """LO QUE DISTINGUE ESTA MEDIDA DE UN PORCENTAJE. Una vuelta a la que
        le falta un kilometro del medio y otra que empieza un kilometro tarde
        cubren la misma fraccion y no valen lo mismo: la del medio se pierde
        curvas que estan justo ahi."""

        metros = ([float(m) for m in range(0, 2000, 5)]
                  + [float(m) for m in range(3000, 5000, 5)])
        c = cat.cobertura_de_la_vuelta(metros, 5000.0)
        self.assertGreater(c.hueco_mayor_m, 900.0)

    def test_las_distancias_negativas_no_cuentan(self) -> None:
        """Monaco: la vuelta 1 trae metros desde -3.573, que es la vuelta de
        formacion antes de la linea. Sumarlos daria una cobertura del 206 %."""

        metros = [float(m) for m in range(-3573, 3322, 5)]
        c = cat.cobertura_de_la_vuelta(metros, 3337.0)
        self.assertLessEqual(c.fraccion, 1.0)
        self.assertGreaterEqual(c.desde_m, 0.0)

    def test_sin_muestras_la_cobertura_es_cero_y_no_revienta(self) -> None:
        c = cat.cobertura_de_la_vuelta([], 5000.0)
        self.assertEqual(c.fraccion, 0.0)
        self.assertEqual(c.hueco_mayor_m, 5000.0)

    def test_un_largo_invalido_no_se_divide(self) -> None:
        with self.assertRaises(ValueError):
            cat.cobertura_de_la_vuelta([1.0, 2.0], 0.0)


class LoQueElCatalogoDeclaraDeSiMismo(unittest.TestCase):

    def test_cada_fila_declara_con_que_medicion_esta_anclada(self) -> None:
        """DOS CIRCUITOS CON DOS ANCLAJES DISTINTOS NO PUEDEN CALLARSELO.

        Spa quedo anclado en el minimo de velocidad; Silverstone en el apice de
        aceleracion lateral, porque contra los dos puntos que declara la FIA el
        apice lateral cae seis veces mas cerca ---6,7 m y 11,8 m contra 74,8 m y
        70,3 m---. Mezclar los dos sin decirlo haria que `metro_medido`
        significara una cosa en una fila y otra en la de al lado.
        """

        for circuito in ("spa-francorchamps", "silverstone"):
            for curva in cat.curvas_de(circuito):
                self.assertIn(curva.anclaje, cat.ANCLAJES,
                              f"{circuito}/{curva.nombre} no declara su anclaje")

    def test_los_dos_circuitos_no_comparten_anclaje(self) -> None:
        """Si algun dia coinciden, es porque uno se volvio a medir: que la
        prueba lo diga en vez de que el cambio pase inadvertido."""

        spa = {c.anclaje for c in cat.curvas_de("spa-francorchamps")}
        silver = {c.anclaje for c in cat.curvas_de("silverstone")}
        self.assertEqual(spa, {"minimo de velocidad"})
        self.assertEqual(silver, {"apice de aceleracion lateral"})

    def test_las_curvas_numeradas_se_cubren_enteras_y_sin_repetir(self) -> None:
        """Silverstone tiene dieciocho, y el catalogo declara quince zonas: tres
        pares vecinos del mismo sentido que la deteccion no separa. Si una
        numerada falta o aparece dos veces, el mapeo esta mal."""

        numeros = [n for c in cat.curvas_de("silverstone")
                   for n in c.numeros_cronometraje]
        self.assertEqual(sorted(numeros), list(range(1, 19)))
        self.assertEqual(len(numeros), len(set(numeros)))

    def test_los_anclajes_avanzan_con_la_vuelta(self) -> None:
        for circuito in ("spa-francorchamps", "silverstone"):
            metros = [c.metro_medido for c in cat.curvas_de(circuito)]
            self.assertEqual(metros, sorted(metros), circuito)

    def test_ningun_anclaje_se_va_de_la_vuelta_medida(self) -> None:
        for c in cat.curvas_de("silverstone"):
            self.assertLess(c.metro_medido, cat.SILVERSTONE_LARGO_MEDIDO_M)
            self.assertGreater(c.metro_medido, 0.0)

    def test_el_largo_medido_no_se_confunde_con_el_declarado(self) -> None:
        """Son dos numeros distintos y el modulo tiene que tener los dos: el
        declarado es la cita, el medido es lo que dio esta vuelta."""

        self.assertEqual(cat.SILVERSTONE_LARGO_DECLARADO_M, FIA_LARGO_DECLARADO_M)
        self.assertNotEqual(cat.SILVERSTONE_LARGO_MEDIDO_M,
                            cat.SILVERSTONE_LARGO_DECLARADO_M)
        self.assertLess(
            abs(cat.SILVERSTONE_LARGO_DECLARADO_M - cat.SILVERSTONE_LARGO_MEDIDO_M),
            10.0, "la vuelta medida no describe este circuito")

    def test_los_tramos_que_no_son_curva_quedan_declarados(self) -> None:
        """DOS DETECCIONES QUE NO SE NOMBRARON, Y POR QUE.

        En la recta Hangar, entre la curva 14 y la 15, la deteccion encuentra
        dos tramos de giro de 21,9 m y 26,6 m. El mapa de la FIA no numera
        ninguna curva ahi y el auto pasa a 315 y 318 km/h. Se declaran para que
        la ausencia sea explicita y no parezca que se perdieron dos nombres."""

        self.assertTrue(cat.SILVERSTONE_SIN_NOMBRE)
        for metro, _ in cat.SILVERSTONE_SIN_NOMBRE:
            for curva in cat.curvas_de("silverstone"):
                self.assertNotAlmostEqual(curva.metro_medido, metro, delta=1.0)


class ComoSeLoConsulta(unittest.TestCase):

    def test_el_alias_de_la_captura_encuentra_el_catalogo(self) -> None:
        """La procedencia de las capturas dice `silverstone`, en minuscula."""

        self.assertTrue(cat.curvas_de("silverstone"))
        self.assertTrue(cat.curvas_de("  SILVERSTONE  "))

    def test_un_metro_cualquiera_devuelve_la_zona_mas_cercana(self) -> None:
        self.assertEqual(cat.nombre_en_metro("silverstone", 1920.0), "Brooklands")
        self.assertEqual(cat.nombre_en_metro("silverstone", 4256.0), "Chapel")

    def test_lejos_de_toda_zona_no_se_estira_el_nombre_vecino(self) -> None:
        """En plena recta Hangar no hay curva, y decir «Chapel» ahi seria
        mentir por cercania."""

        self.assertIsNone(cat.nombre_en_metro("silverstone", 4600.0))

    def test_un_circuito_sin_catalogo_no_rompe(self) -> None:
        self.assertEqual(cat.curvas_de("interlagos"), ())
        self.assertIsNone(cat.nombre_en_metro("interlagos", 100.0))


class LaFichaEsDelCircuitoQueSePide(unittest.TestCase):
    """UN SEGUNDO CIRCUITO DESTAPO QUE LA FICHA ESTABA ESCRITA A MANO.

    `/circuitos/{circuito}/curvas` devolvia las constantes de Spa para
    cualquier circuito: pedir Silverstone habria contestado 7.004 m de largo,
    102,2 m de desnivel y que Kemmel no frena. Mientras hubo un solo circuito
    en el catalogo nada de eso se veia, porque siempre acertaba.

    Es la tercera vez que este sistema tiene un dato con dos dueños. Aca el
    arreglo es que la ficha viva junto al catalogo, indexada igual.
    """

    def test_cada_circuito_declara_su_propia_ficha(self) -> None:
        spa = cat.ficha_de("spa-francorchamps")
        silver = cat.ficha_de("silverstone")
        self.assertNotEqual(spa.largo_declarado_m, silver.largo_declarado_m)
        self.assertEqual(silver.largo_declarado_m, FIA_LARGO_DECLARADO_M)
        self.assertEqual(spa.largo_declarado_m, cat.SPA_LARGO_DECLARADO_M)

    def test_el_desnivel_no_se_hereda_del_otro_circuito(self) -> None:
        """Silverstone es llano y Spa no: 11,5 m contra 102,2 m. Si estos dos
        numeros se parecen, uno de los dos esta copiado."""

        self.assertGreater(cat.ficha_de("spa-francorchamps").desnivel_declarado_m,
                           5 * cat.ficha_de("silverstone").desnivel_declarado_m)

    def test_lo_que_la_deteccion_no_encuentra_es_de_cada_circuito(self) -> None:
        """Spa declara dos zonas con nombre donde no se frena; Silverstone
        declara dos detecciones que no son curva. No son lo mismo y ninguna de
        las dos vale para el otro circuito."""

        self.assertEqual(cat.ficha_de("spa-francorchamps").sin_frenada,
                         cat.SPA_SIN_FRENADA)
        self.assertEqual(cat.ficha_de("silverstone").sin_frenada, ())

    def test_la_ruta_contesta_la_ficha_del_circuito_pedido(self) -> None:
        """SE COMPRUEBA SOBRE LA RUTA Y NO SOLO SOBRE EL MODULO.

        La primera version de este arnes comprobaba `ficha_de` y daba verde con
        la ruta todavia devolviendo las constantes de Spa: la mutacion que
        reponia `SPA_LARGO_DECLARADO_M` en el punto de acceso no mataba ninguna
        prueba. El defecto estaba en quien muestra el dato, no en quien lo
        guarda, y hay que comprobarlo ahi.
        """

        from backend import api_sesion

        silver = api_sesion.curvas_del_circuito("silverstone")
        self.assertEqual(silver["largo_declarado_m"], FIA_LARGO_DECLARADO_M)
        self.assertEqual(silver["sin_frenada"], [])
        self.assertNotEqual(silver["desnivel_declarado_m"],
                            cat.SPA_DESNIVEL_DECLARADO_M)

        spa = api_sesion.curvas_del_circuito("spa")
        self.assertEqual(spa["largo_declarado_m"], cat.SPA_LARGO_DECLARADO_M)
        self.assertEqual(spa["sin_frenada"], list(cat.SPA_SIN_FRENADA))

    def test_la_ruta_dice_con_que_esta_anclada_cada_curva(self) -> None:
        """Sin esto, un tablero que dibuje los dos circuitos no puede saber que
        `metro_medido` no significa lo mismo en los dos."""

        from backend import api_sesion

        for c in api_sesion.curvas_del_circuito("silverstone")["curvas"]:
            self.assertEqual(c["anclaje"], "apice de aceleracion lateral")
            self.assertIn(c["sentido"], ("derecha", "izquierda"))
        for c in api_sesion.curvas_del_circuito("spa")["curvas"]:
            self.assertEqual(c["anclaje"], "minimo de velocidad")

    def test_un_circuito_sin_catalogo_no_tiene_ficha(self) -> None:
        self.assertIsNone(cat.ficha_de("interlagos"))

    def test_la_ficha_y_el_catalogo_se_indexan_igual(self) -> None:
        """Si un circuito tiene curvas y no tiene ficha, la ruta vuelve a
        inventar una."""

        for clave in cat.CATALOGO:
            self.assertIsNotNone(cat.ficha_de(clave), clave)


if __name__ == "__main__":
    unittest.main()
