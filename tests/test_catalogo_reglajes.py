"""Pruebas del catalogo externo de reglajes.

LO QUE ESTE ARCHIVO CUIDA, Y ES UNA SOLA COSA: que ninguna cifra entre sin
fuente. El catalogo pasó el 2026-09-13 de **una** entrada a diecisiete,
transcritas de la fuente una por una, y una transcripcion masiva es justo donde
se cuela un numero inventado.
"""

from __future__ import annotations

import unittest

from backend import catalogo_reglajes


#: Los circuitos que el catalogo de sesiones declara hoy. Es la lista contra la
#: que vale preguntarse si falta alguno.
CIRCUITOS_CAPTURADOS = (
    "abu-dhabi", "austin", "baku", "catalunya", "imola", "las-vegas", "lusail",
    "melbourne", "miami", "monte-carlo", "monza", "sakhir", "shanghai",
    "silverstone", "spa", "spielberg", "suzuka",
)


class CatalogoReglajesTests(unittest.TestCase):
    def test_spa_tiene_solo_los_valores_respaldados(self) -> None:
        referencia = catalogo_reglajes.referencia_de("spa")
        self.assertEqual(referencia["valores"]["aleron_delantero"], 3)
        self.assertEqual(referencia["valores"]["aleron_trasero"], 0)
        self.assertEqual(
            referencia["fuente"]["clave_bibliografica"],
            "simracingsetup_f1_25_spa_francorchamps")
        self.assertIn("no demuestra", referencia["alcance"])

    def test_un_circuito_que_la_fuente_no_cubre_no_recibe_valores(self) -> None:
        """Ausente no significa cero, y tampoco significa «como el de al lado»."""

        self.assertIsNone(catalogo_reglajes.referencia_de("jeddah"))
        self.assertIsNone(catalogo_reglajes.referencia_de("zandvoort"))
        self.assertIsNone(catalogo_reglajes.referencia_de(None))

    def test_quien_llama_no_puede_mutar_el_catalogo(self) -> None:
        referencia = catalogo_reglajes.referencia_de("spa")
        referencia["valores"]["aleron_delantero"] = 99
        self.assertEqual(
            catalogo_reglajes.referencia_de("spa")["valores"]["aleron_delantero"], 3)

    def test_cada_circuito_capturado_tiene_su_referencia(self) -> None:
        faltan = [c for c in CIRCUITOS_CAPTURADOS
                  if catalogo_reglajes.referencia_de(c) is None]
        self.assertEqual(faltan, [], "circuitos sin referencia: %s" % faltan)

    def test_ninguna_cifra_entra_sin_su_frase_textual(self) -> None:
        """LA CITA ES LO QUE HACE VERIFICABLE A LA CIFRA.

        Cada ficha se leyo pidiendo la frase que enuncia cada valor. No es una
        formalidad: leyendo Monaco, el resumen automatico agrego por su cuenta
        «(the front would be 46 %)» sobre un sesgo que la pagina da como 54 %.
        La frase citada lo desmiente sola; un numero suelto, no.
        """
        for clave, ficha in catalogo_reglajes.REFERENCIAS.items():
            with self.subTest(circuito=clave[1]):
                self.assertTrue(ficha.get("cita", "").strip(),
                                "sin frase textual que respalde las cifras")
                self.assertIn("«", ficha["cita"],
                              "la cita no transcribe la frase de la fuente")
                self.assertTrue(ficha["fuente"]["url"].startswith("https://"))
                self.assertTrue(ficha["fuente"]["clave_bibliografica"])

    def test_cada_ficha_declara_para_que_modo_y_clima_vale(self) -> None:
        """UN REGLAJE DE CARRERA NO ES UNO DE CONTRARRELOJ.

        Y casi todas las sesiones capturadas son contrarreloj, de modo que sin
        declararlo el panel compararia contra algo que no le corresponde.
        """
        for clave, ficha in catalogo_reglajes.REFERENCIAS.items():
            with self.subTest(circuito=clave[1]):
                self.assertIn(ficha["modo"], ("carrera", "contrarreloj",
                                              "clasificacion"))
                self.assertIn(ficha["clima"], ("seco", "lluvia"))

    def test_los_valores_son_numeros_y_estan_en_rango(self) -> None:
        """Un guardian contra el dedo, no contra la fuente.

        Los alerones del juego van de 0 a 50 y los porcentajes de 0 a 100. Un
        numero fuera de eso es un error de transcripcion, no una opinion de
        quien publico el reglaje.
        """
        rangos = {
            "aleron_delantero": (0, 50), "aleron_trasero": (0, 50),
            "sesgo_de_freno_pct": (50, 70),
            "diferencial_con_acelerador_pct": (0, 100),
            "diferencial_sin_acelerador_pct": (0, 100),
        }
        for clave, ficha in catalogo_reglajes.REFERENCIAS.items():
            for eje, valor in ficha["valores"].items():
                with self.subTest(circuito=clave[1], eje=eje):
                    self.assertIsInstance(valor, (int, float))
                    piso, techo = rangos[eje]
                    self.assertGreaterEqual(valor, piso)
                    self.assertLessEqual(valor, techo)

    def test_no_entra_ningun_eje_que_la_fuente_da_en_palabras(self) -> None:
        """«All the way left» y «maximum» no son cifras.

        Convertirlos a un numero seria inventar el dato que falta, y son
        justamente los ejes que la fuente nunca cuantifica: caida, convergencia
        y, en varias pistas, las presiones.
        """
        prohibidos = {"caida_delantera_deg", "caida_trasera_deg",
                      "convergencia_delantera_deg", "convergencia_trasera_deg",
                      "presion_neumatico_delantero_izq_psi",
                      "presion_neumatico_delantero_der_psi",
                      "presion_neumatico_trasero_izq_psi",
                      "presion_neumatico_trasero_der_psi"}
        for clave, ficha in catalogo_reglajes.REFERENCIAS.items():
            colados = prohibidos & set(ficha["valores"])
            with self.subTest(circuito=clave[1]):
                self.assertEqual(colados, set(),
                                 "ejes que la fuente no cuantifica: %s" % colados)

    def test_el_clima_elige_la_ficha_y_cubierto_no_es_lluvia(self) -> None:
        """CUBIERTO ES SECO, Y NO ES UN DETALLE.

        La pista puede estar nublada y la goma seguir siendo la de seco: lo que
        cambia el reglaje es el agua, no la luz. De las veintisiete sesiones
        capturadas **tres son cubiertas**; contadas como lluvia se compararian
        contra un reglaje que nadie usaria ahi.
        """
        self.assertIs(catalogo_reglajes.es_lluvia("cubierto"), False)
        self.assertIs(catalogo_reglajes.es_lluvia("despejado"), False)
        self.assertIs(catalogo_reglajes.es_lluvia("lluvia fuerte"), True)
        self.assertIs(catalogo_reglajes.es_lluvia("tormenta"), True)
        # No saberlo no es «no llueve»: es no saberlo.
        self.assertIsNone(catalogo_reglajes.es_lluvia(None))
        self.assertIsNone(catalogo_reglajes.es_lluvia("un clima nuevo"))

        seco = catalogo_reglajes.referencia_de("spa", clima="cubierto")
        agua = catalogo_reglajes.referencia_de("spa", clima="lluvia fuerte")
        self.assertEqual(seco["clima"], "seco")
        self.assertEqual(agua["clima"], "lluvia")
        self.assertGreater(agua["valores"]["aleron_trasero"],
                           seco["valores"]["aleron_trasero"],
                           "el reglaje de agua no lleva mas carga que el de seco")

    def test_sin_referencia_de_agua_se_muestra_la_de_seco_y_se_dice(self) -> None:
        """No mostrar nada esconderia tambien lo que si se sabe.

        Lo que no se hace nunca es presentar una por la otra.
        """
        r = catalogo_reglajes.referencia_de("monza", clima="lluvia fuerte")
        self.assertEqual(r["clima"], "seco")
        self.assertIn("no hay referencia de lluvia", r["otro_clima"])
        # Y con la que corresponde no se avisa nada: seria ruido.
        self.assertNotIn("otro_clima",
                         catalogo_reglajes.referencia_de("monza", clima="despejado"))

    def test_monaco_es_carga_maxima_y_monza_minima(self) -> None:
        """LA PRUEBA DE QUE LA TRANSCRIPCION DISTINGUE PISTAS.

        Si el extractor hubiera arrastrado el mismo reglaje de una pagina a la
        siguiente, estos dos circuitos ---los extremos de carga aerodinamica del
        calendario--- tendrian los mismos alerones. Monaco da 50 y 50; Monza,
        0 y 0. Son los dos limites del rango del juego.
        """
        monaco = catalogo_reglajes.referencia_de("monte-carlo")["valores"]
        monza = catalogo_reglajes.referencia_de("monza")["valores"]
        self.assertEqual((monaco["aleron_delantero"], monaco["aleron_trasero"]),
                         (50, 50))
        self.assertEqual((monza["aleron_delantero"], monza["aleron_trasero"]),
                         (0, 0))


if __name__ == "__main__":
    unittest.main()
