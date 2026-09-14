# -*- coding: utf-8 -*-
"""Los giros de una vuelta leidos de la FORMA, y por que hacia falta otro instrumento.

EL PROBLEMA QUE RESUELVE. `tramos_de_una_vuelta` encuentra zonas de giro
sostenido en la aceleracion lateral, y esas zonas **funden las curvas vecinas
del mismo sentido**: en Silverstone da un solo tramo donde el mapa numera tres
curvas, y en Monaco da uno solo de 178 m donde el mapa numera dos.

Fundidas, el catalogo no puede decir cual numero va en cual zona, y ese es el
obstaculo que dejo trece circuitos sin nombrar. Mirando la aceleracion lateral
no se sale: el canal declara *cuanto* gira, no *cuantas veces*.

La forma del recorrido si lo dice. Dos curvas del mismo sentido separadas por un
tramo recto son dos acumulaciones de rumbo separadas, aunque el auto no suelte
la aceleracion lateral entre las dos. En Monaco eso mostro **dos giros de +119
grados** ---Mirabeau Inferior y Portier--- dentro de una sola deteccion.

LO QUE ESTA FUNCION NO DICE, A PROPOSITO. No dice izquierda ni derecha. El
plano en que el simulador publica las coordenadas **esta espejado** ---Spa, que
se corre horario, da antihorario ahi--- y traducir el signo a un sentido del
mundo es una decision que depende de la fuente. La funcion informa el signo en
el plano que recibio, y quien la llame pone el nombre.
"""

from __future__ import annotations

import math
import unittest

from backend.analisis.curvas import giros_de_la_vuelta


def _camino(tramos, paso_m: float = 2.0) -> list[tuple[float, float]]:
    """Un recorrido armado con rectas y arcos TANGENTES entre si.

    POR QUE UN CONSTRUCTOR Y NO FIGURAS A MANO. La primera version de este
    arnes pegaba un circulo despues de una recta calculando los puntos por
    separado, y las dos piezas no quedaban tangentes: en la union habia un
    quiebre de rumbo que el instrumento informaba ---con razon--- como un giro
    mas. Tres giros donde la prueba esperaba uno, y el defecto estaba en la
    figura, no en lo que se estaba midiendo.

    Aca cada tramo arranca con el rumbo con que termino el anterior, asi que la
    unica forma de que aparezca un giro es que el tramo lo tenga.

    `tramos` son ("recta", metros) o ("arco", grados, radio); grados positivos
    giran en el sentido creciente del angulo del plano. Cualquiera de los dos
    admite un elemento mas con el paso de muestreo de ESE tramo, para armar un
    recorrido desparejo ---denso en las curvas y ralo en las rectas--- como el
    que llega de verdad.

    NO SE CONCATENAN DOS LLAMADAS. Cada una arranca en el origen y con rumbo
    cero, asi que pegar sus salidas mete un salto y un giro de 180 grados que no
    esta en ninguna de las dos. Un tramo desparejo se pide en UNA sola llamada.
    """

    x, y, rumbo = 0.0, 0.0, 0.0
    pts = [(x, y)]
    for tramo in tramos:
        if tramo[0] == "recta":
            largo = tramo[1]
            propio = tramo[2] if len(tramo) > 2 else paso_m
            pasos = max(1, int(largo / propio))
            for _ in range(pasos):
                x += (largo / pasos) * math.cos(rumbo)
                y += (largo / pasos) * math.sin(rumbo)
                pts.append((x, y))
        else:
            grados, radio = tramo[1], tramo[2]
            propio = tramo[3] if len(tramo) > 3 else paso_m
            arco = abs(math.radians(grados)) * radio
            pasos = max(1, int(arco / propio))
            for _ in range(pasos):
                rumbo += math.radians(grados) / pasos
                x += (arco / pasos) * math.cos(rumbo)
                y += (arco / pasos) * math.sin(rumbo)
                pts.append((x, y))
    return pts


def _circulo(vueltas: float = 1.0, radio: float = 100.0,
             sentido: int = 1) -> list[tuple[float, float]]:
    return _camino([("arco", sentido * 360.0 * vueltas, radio)])


def _recta(metros: float) -> list[tuple[float, float]]:
    return _camino([("recta", metros)])


#: CUANTO QUEDA CORTO EL TOTAL, Y POR QUE NO ES UN DEFECTO.
#:
#: El rumbo se mide ENTRE pasos consecutivos, asi que N pasos dan N-1 cambios:
#: el primero y el ultimo no tienen con quien compararse. Sobre una
#: circunferencia de 628 m leida cada 8 m eso son unos 7 grados de 360, un 2 %.
#:
#: Se declara con un numero en vez de aflojar la tolerancia sin decir nada: si
#: algun dia el faltante crece, estas pruebas lo dicen.
FALTANTE_DE_LOS_EXTREMOS = 0.03


class UnGiroConocidoSeMideBien(unittest.TestCase):
    """Contra figuras cuyo angulo no se mide: se sabe."""

    def test_una_circunferencia_entera_da_una_revolucion(self) -> None:
        giros = giros_de_la_vuelta(_circulo())
        self.assertEqual(len(giros), 1)
        self.assertAlmostEqual(giros[0]["grados"], 360.0,
                               delta=360.0 * FALTANTE_DE_LOS_EXTREMOS)

    def test_el_sentido_contrario_da_el_signo_contrario(self) -> None:
        giros = giros_de_la_vuelta(_circulo(sentido=-1))
        self.assertEqual(len(giros), 1)
        self.assertAlmostEqual(giros[0]["grados"], -360.0,
                               delta=360.0 * FALTANTE_DE_LOS_EXTREMOS)

    def test_media_circunferencia_da_media_revolucion(self) -> None:
        """Es la forma de una horquilla, que es justo lo que hay que distinguir
        de una curva normal."""

        giros = giros_de_la_vuelta(_circulo(vueltas=0.5))
        self.assertEqual(len(giros), 1)
        self.assertAlmostEqual(giros[0]["grados"], 180.0,
                               delta=180.0 * FALTANTE_DE_LOS_EXTREMOS + 2)

    def test_una_recta_no_tiene_ningun_giro(self) -> None:
        self.assertEqual(giros_de_la_vuelta(_recta(1000.0)), [])


class DOSCURVASSEPARADASSONDOS(unittest.TestCase):
    """LA RAZON DE SER DE ESTE INSTRUMENTO.

    Dos curvas del mismo sentido con una recta en el medio son dos giros. La
    deteccion por aceleracion lateral las da como uno solo cuando el auto no
    suelta el volante entre las dos, y ahi se pierde cual numero va en cual.
    """

    def _dos_curvas_del_mismo_sentido(self, recta_m: float):
        return _camino([("recta", 100.0), ("arco", 90.0, 80.0),
                        ("recta", recta_m), ("arco", 90.0, 80.0),
                        ("recta", 100.0)])

    def test_con_una_recta_larga_en_el_medio_son_dos(self) -> None:
        giros = giros_de_la_vuelta(self._dos_curvas_del_mismo_sentido(300.0))
        self.assertEqual(len(giros), 2, [g["grados"] for g in giros])
        for g in giros:
            self.assertGreater(g["grados"], 0.0)

    def test_sin_recta_en_el_medio_es_uno_solo(self) -> None:
        """Y esta bien que lo sea: dos curvas pegadas del mismo sentido son un
        solo giro tambien para el que maneja. El instrumento no inventa
        separaciones, informa las que la forma tiene."""

        giros = giros_de_la_vuelta(self._dos_curvas_del_mismo_sentido(0.0))
        self.assertEqual(len(giros), 1, [g["grados"] for g in giros])
        self.assertAlmostEqual(giros[0]["grados"], 180.0,
                               delta=180.0 * FALTANTE_DE_LOS_EXTREMOS + 2)

    def test_dos_sentidos_opuestos_siempre_son_dos(self) -> None:
        """Aunque esten pegadas. Una ese es dos curvas."""

        giros = giros_de_la_vuelta(_camino([
            ("recta", 100.0), ("arco", 90.0, 80.0), ("arco", -90.0, 80.0),
            ("recta", 100.0)]))
        self.assertEqual(len(giros), 2, [g["grados"] for g in giros])
        self.assertLess(giros[0]["grados"] * giros[1]["grados"], 0.0)


class LOQUESEDESCARTAYPORQUE(unittest.TestCase):

    #: Temblor perpendicular, en metros, alternando de signo muestra a muestra.
    #: Es MUCHO mas de lo que trae el recorrido del simulador ---las coordenadas
    #: llegan con dos decimales--- y sirve para acotar hasta donde aguanta.
    TEMBLOR_M = 0.15

    def _con_temblor(self, pts, cuanto=None):
        j = self.TEMBLOR_M if cuanto is None else cuanto
        return [(x, y + (j if k % 2 else -j)) for k, (x, y) in enumerate(pts)]

    def test_una_recta_temblorosa_no_produce_giros(self) -> None:
        self.assertEqual(giros_de_la_vuelta(self._con_temblor(_recta(1000.0))), [])

    def test_una_curva_temblorosa_sigue_siendo_una(self) -> None:
        """HASTA DONDE AGUANTA, MEDIDO, en vez de supuesto.

        El remuestreo a paso fijo es lo que sostiene esto: leido muestra a
        muestra, un temblor de quince centimetros cada dos metros es un
        zigzag de varios grados por paso y parte la curva en pedazos.

        Medido el 2026-09-14 sobre arcos de 180 grados, el tope de temblor que
        aguanta sin partirse va de 0,20 m ---en un arco de 400 m de radio, donde
        el giro real por paso es de un grado--- a 0,75 m en uno de 40 m. La
        precision del recorrido del simulador es de un centimetro, dos ordenes
        por debajo.
        """

        for radio in (60.0, 100.0, 400.0):
            entera = giros_de_la_vuelta(
                self._con_temblor(_circulo(vueltas=0.5, radio=radio)))
            self.assertEqual(len(entera), 1,
                             f"radio {radio}: {[g['grados'] for g in entera]}")
            self.assertAlmostEqual(entera[0]["grados"], 180.0, delta=20.0)

    def test_el_piso_de_ruido_NO_esta_guardado_por_abajo(self) -> None:
        """LO QUE ESTA PRUEBA DICE ES QUE NO HAY PRUEBA, y esta escrito asi a
        proposito.

        `RUIDO_DE_RUMBO_GRADOS` existe para que un temblor de signo contrario no
        parta una curva. Subirlo a 25 grados rompe el arnes ---la guarda de
        arriba lo atrapa--- pero **bajarlo a cero no cambia nada** a ningun nivel
        de temblor probado: el remuestreo ya se comio ese ruido antes.

        O sea que el piso es un margen de seguridad, no un valor afinado, y su
        limite inferior no esta comprobado. Dejarlo sin decir seria peor: quien
        lo lea supondria que el numero salio de una medicion.

        Si alguna vez esta prueba se pone roja, es una buena noticia: significa
        que el piso empezo a hacer algo y hay que darle una guarda de verdad.

        Hay un segundo lugar sin guarda, anotado donde vive: el avance del
        origen dentro de `_a_paso_fijo`. Romperlo desplaza muestras **sobre la
        misma cuerda**, que no cambia ningun rumbo salvo en las uniones, y ahi
        queda por debajo de los umbrales. Son dos, y estan los dos dichos.
        """

        for radio in (60.0, 100.0, 400.0):
            temblorosa = self._con_temblor(_circulo(vueltas=0.5, radio=radio))
            self.assertEqual(
                len(giros_de_la_vuelta(temblorosa, ruido_grados=0.0)),
                len(giros_de_la_vuelta(temblorosa)),
                f"radio {radio}: el piso de ruido empezo a cambiar el resultado")

    def test_un_giro_por_debajo_del_umbral_no_se_informa(self) -> None:
        chico = _circulo(vueltas=0.02, radio=400.0)   # ~7 grados
        self.assertEqual(giros_de_la_vuelta(chico, umbral_grados=18.0), [])
        self.assertEqual(len(giros_de_la_vuelta(chico, umbral_grados=5.0)), 1)

    def test_el_umbral_se_puede_bajar_sin_tocar_el_codigo(self) -> None:
        """El tunel de Monaco gira 34,9 grados en 115 m y es una curva numerada.
        Con un umbral alto desaparece, y la que desaparece corre el mapeo."""

        suave = _circulo(vueltas=0.1, radio=300.0)    # ~36 grados
        self.assertEqual(len(giros_de_la_vuelta(suave, umbral_grados=18.0)), 1)
        self.assertEqual(giros_de_la_vuelta(suave, umbral_grados=90.0), [])


class DONDEEMPIEZAYTERMINACADAGIRO(unittest.TestCase):

    def test_cada_giro_dice_desde_donde_y_hasta_donde(self) -> None:
        camino = _camino([("recta", 200.0), ("arco", 90.0, 80.0)])
        giros = giros_de_la_vuelta(camino)
        self.assertEqual(len(giros), 1, [g["grados"] for g in giros])
        self.assertGreater(giros[0]["desde_m"], 150.0)
        self.assertGreater(giros[0]["hasta_m"], giros[0]["desde_m"])

    def test_la_distancia_es_de_cuerdas_y_queda_por_debajo(self) -> None:
        """ES UNA ADVERTENCIA Y NO UN DEFECTO, y hay que tenerla escrita.

        La distancia se acumula sumando las cuerdas entre puntos consecutivos, y
        una cuerda corta la curva: el largo que sale es MENOR que el recorrido
        real, y la diferencia se concentra justo en las curvas cerradas. En
        Monaco el poligono da 3.258 m contra los 3.320 que declara la ruta.

        Quien compare estos metros contra los de la telemetria tiene que
        escalarlos, y es el llamador el que sabe contra que largo escalar.
        """

        circulo = _circulo(radio=100.0)
        giros = giros_de_la_vuelta(circulo)
        largo_real = 2 * math.pi * 100.0
        self.assertLess(giros[0]["hasta_m"], largo_real)


class UNRECORRIDOPUEDEVENIRMASGRUESOQUEELPASO(unittest.TestCase):
    """LA MUTACION QUE SOBREVIVIO A LA PRIMERA VERSION DE ESTE ARNES.

    Todas las figuras de arriba se muestrean cada dos metros, y el rumbo se lee
    cada ocho: cada tramo de entrada es mas corto que un paso, asi que el
    remuestreo nunca tiene que partir un tramo en varios. Rompiendo justo esa
    parte, el arnes seguia verde.

    Pero el recorrido real llega mas grueso de lo que uno supone: la ruta del
    trazado reduce a los puntos que se piden ---600 por omision--- y en un
    circuito de seis kilometros eso son diez metros entre puntos. Ahi el
    remuestreo si tiene que partir, y si lo hace mal las distancias salen
    cualquier cosa sin que nada avise.
    """

    def test_con_puntos_cada_veinticinco_metros_el_giro_sigue_ENTERO(self) -> None:
        """LO QUE IMPORTA ES QUE NO SE PARTA. La magnitud se degrada y esta
        medido cuanto; lo que no puede pasar es que una curva salga como dos,
        porque ahi el recuento de curvas ---que es para lo que sirve este
        instrumento--- da mal."""

        giros = giros_de_la_vuelta(_camino([("arco", 180.0, 120.0)], paso_m=25.0))
        self.assertEqual(len(giros), 1, [g["grados"] for g in giros])

    def test_cuanto_se_pierde_con_el_recorrido_grueso(self) -> None:
        """MEDIDO, PARA QUE NADIE LO CONFUNDA CON PRECISION.

        El paso de lectura se adapta al espaciado de entrada ---no puede ser mas
        fino que la poligonal que llega--- asi que un recorrido grueso se lee con
        pasos grandes, y el faltante de los extremos, que son dos pasos, pesa
        mucho mas.

        Un arco de 180 grados medido cada dos metros da 174; medido cada
        veinticinco da 144, un 20 % menos. Sirve igual para CONTAR curvas y no
        sirve para afirmar cuanto gira cada una: para eso hay que pedirle mas
        puntos al trazado.
        """

        fino = giros_de_la_vuelta(_camino([("arco", 180.0, 120.0)], paso_m=2.0))
        grueso = giros_de_la_vuelta(_camino([("arco", 180.0, 120.0)], paso_m=25.0))
        self.assertGreater(fino[0]["grados"], grueso[0]["grados"])
        self.assertGreater(grueso[0]["grados"], 180.0 * 0.70)
        self.assertLess(grueso[0]["grados"], 180.0)

    def test_el_comienzo_se_adelanta_a_lo_sumo_un_paso(self) -> None:
        """El primer paso que pisa la union entre la recta y el arco ya gira, y
        el giro se informa desde ahi: con un recorrido cada 30 m el comienzo se
        adelanta unos 90 m sobre los 400 de recta. Es una consecuencia del paso
        grueso y no un corrimiento del instrumento."""

        espaciado, recta = 30.0, 400.0
        giros = giros_de_la_vuelta(
            _camino([("recta", recta), ("arco", 90.0, 200.0)], paso_m=espaciado))
        self.assertEqual(len(giros), 1)
        self.assertLess(giros[0]["desde_m"], recta)
        self.assertGreater(giros[0]["desde_m"], recta - 4 * espaciado)


class LOSVALORESPOROMISIONTAMBIENSEVIGILAN(unittest.TestCase):
    """TRES MUTACIONES SOBREVIVIERON A LA PRIMERA VERSION DE ESTE ARNES, y las
    tres por el mismo motivo: las pruebas pasaban los parametros a mano, asi que
    cambiar el valor por omision no rompia nada. Una constante que nadie vigila
    se puede mover sin que el arnes se entere.
    """

    def test_el_umbral_POR_OMISION_descarta_un_giro_chico(self) -> None:
        chico = _circulo(vueltas=0.02, radio=400.0)      # ~7 grados
        self.assertEqual(giros_de_la_vuelta(chico), [])

    def test_la_union_POR_OMISION_no_parte_una_curva_con_una_recta_corta(self) -> None:
        """CUANTA RECTA HACE FALTA, MEDIDO. El rumbo se lee cada ocho metros,
        asi que una recta de diez no deja ningun paso limpio: los que la pisan
        traen algo de curva de los dos lados. Veinticinco metros si dejan dos
        pasos rectos ---dentro de la union por omision, que son veinte--- y con
        la union en cero esos dos pasos ya parten la curva."""

        con_recta_corta = _camino([("recta", 60.0), ("arco", 90.0, 70.0),
                                   ("recta", 25.0), ("arco", 90.0, 70.0),
                                   ("recta", 60.0)])
        self.assertEqual(len(giros_de_la_vuelta(con_recta_corta)), 1)
        self.assertEqual(len(giros_de_la_vuelta(con_recta_corta, union_m=0.0)), 2)


class ELRECORRIDOPUEDELLEGARDESPAREJO(unittest.TestCase):
    """Tramos largos mezclados con cortos, que es como llega el recorrido real:
    la ruta reduce por cantidad de puntos y no por distancia, asi que entre dos
    puntos puede haber un metro o cincuenta.

    Rompiendo la interpolacion del remuestreo, un arnes con puntos parejos sigue
    verde: cuando todos los tramos son mas cortos que el paso, no hay ningun
    tramo que partir y esa linea no se ejecuta nunca.
    """

    def _desparejo(self):
        """COMO LLEGA DE VERDAD, y no como se me ocurrio al principio.

        La ruta del trazado reduce quedandose con una muestra cada tantas, y las
        muestras son por tiempo: en una horquilla a 40 km/h caen cada metro y en
        una recta a 300 km/h cada quince. O sea que el recorrido llega **denso
        en las curvas y ralo en las rectas**, que es justo el reparto que le
        conviene a este instrumento.

        La primera version de este arnes hizo lo contrario ---la curva rala y la
        recta densa--- y el instrumento partia el arco en cinco. Es cierto que lo
        parte, y no describe ningun dato que exista: era una figura inventada
        para un caso que la fuente no produce.
        """

        return _camino([("recta", 600.0, 40.0),
                        ("arco", 180.0, 150.0, 2.0),
                        ("recta", 600.0, 40.0)])

    def test_el_giro_se_mide_igual_con_puntos_desparejos(self) -> None:
        giros = giros_de_la_vuelta(self._desparejo())
        self.assertEqual(len(giros), 1, [g["grados"] for g in giros])
        self.assertGreater(abs(giros[0]["grados"]), 180.0 * 0.80)

    def test_el_giro_cae_DONDE_CORRESPONDE_y_no_solo_dentro(self) -> None:
        """LA GUARDA FLOJA NO ATRAPABA NADA, y vale contarlo.

        La primera version pedia que ningun giro terminara mas alla del largo
        del recorrido. Rompiendo la interpolacion del remuestreo seguia verde:
        la acumulada salia mal pero seguia cayendo dentro del rango, que es un
        rango de dos kilometros.

        Lo que si aprieta es DONDE empieza el giro. La figura tiene 600 m de
        recta rala antes del arco, y esos 600 m se acumulan interpolando: si la
        interpolacion avanza mal, el arco se informa en otro metro.
        """

        pts = self._desparejo()
        largo = sum(math.dist(pts[i - 1], pts[i]) for i in range(1, len(pts)))
        giros = giros_de_la_vuelta(pts)
        self.assertEqual(len(giros), 1)
        self.assertLessEqual(giros[0]["hasta_m"], largo + 1.0)
        self.assertAlmostEqual(giros[0]["desde_m"], 600.0, delta=90.0)


class LOQUENODICE(unittest.TestCase):
    """El instrumento informa el signo EN EL PLANO QUE RECIBE."""

    def test_no_habla_de_izquierda_ni_de_derecha(self) -> None:
        """Si algun dia esta funcion devuelve «derecha», estaria afirmando algo
        sobre el mundo a partir de un plano que puede venir espejado. El
        simulador publica uno que lo esta: Spa se corre horario y ahi da
        antihorario. La traduccion es del llamador."""

        for g in giros_de_la_vuelta(_circulo()):
            self.assertNotIn("sentido", g)
            self.assertNotIn("derecha", str(g).lower())
            self.assertNotIn("izquierda", str(g).lower())

    def test_dos_puntos_no_alcanzan_para_un_rumbo(self) -> None:
        self.assertEqual(giros_de_la_vuelta([(0.0, 0.0), (1.0, 1.0)]), [])
        self.assertEqual(giros_de_la_vuelta([]), [])


if __name__ == "__main__":
    unittest.main()
