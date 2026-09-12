# -*- coding: utf-8 -*-
"""El puente entre la pista del simulador y el circuito de la fuente deportiva.

POR QUE SE PRUEBA CON LONGITUDES Y NO CON NOMBRES. El puente une dos
identificadores de dos proveedores distintos ---`track_id` de F1 25 y
`circuit_key` de OpenF1--- y un nombre escrito a mano en el medio no prueba
nada: si esta mal, sigue estando mal en las dos puntas. La longitud declarada
por el juego, contrastada contra la ficha externa del circuito, es una
comprobacion **independiente** de las dos tablas, y es la que encontro que la
pista 30 no era la que el proyecto decia.
"""

from __future__ import annotations

import unittest

from backend import procedencia_sesiones as ps
from backend import track_reference as tr


class ElPuenteEstaCompleto(unittest.TestCase):
    def test_cada_pista_apunta_a_un_circuito_que_existe(self):
        """Un puente a una clave inexistente es peor que no tener puente."""
        for pista, entrada in tr.CIRCUITO_POR_PISTA_F1_25.items():
            clave = entrada["clave_openf1"]
            self.assertIn(clave, tr.LONGITUDES_CIRCUITO,
                          f"la pista {pista} apunta a circuit_key={clave}, "
                          "que no figura en la tabla de longitudes")

    def test_ningun_circuito_recibe_dos_pistas(self):
        """Dos pistas del juego no pueden ser el mismo circuito real.

        Es exactamente el sintoma que dejo el defecto: con `30` llamada
        «las-vegas» y `29` llamada «miami», corregir una sin la otra habria
        dejado dos pistas apuntando a Miami.
        """
        claves = [e["clave_openf1"] for e in tr.CIRCUITO_POR_PISTA_F1_25.values()]
        self.assertEqual(len(claves), len(set(claves)), "hay un circuito repetido")

    def test_cada_entrada_declara_como_se_verifico(self):
        for pista, entrada in tr.CIRCUITO_POR_PISTA_F1_25.items():
            self.assertTrue(entrada.get("verificacion"),
                            f"la pista {pista} no declara como se comprobo")


class LoQueSeMidioEnLasCapturas(unittest.TestCase):
    """Las diez pistas con captura, con la longitud que el juego declaro.

    Tomadas de los metadatos de las veinticuatro capturas al 2026-09-12. No se
    escriben de memoria: son el dato que el capturador anoto del paquete de
    sesion.
    """

    MEDIDO = {
        2: 5441, 4: 4664, 5: 3323, 10: 7007, 11: 5798,
        13: 5809, 15: 5514, 17: 4323, 20: 5994, 27: 4910, 30: 5410,
    }

    def test_todas_concuerdan_con_la_ficha_externa(self):
        for pista, largo in self.MEDIDO.items():
            with self.subTest(pista=pista):
                r = tr.contrastar_longitud_declarada(pista, largo)
                self.assertTrue(r["concuerda"],
                                f"pista {pista}: el juego declara {largo} m y la "
                                f"ficha de {r.get('circuito')} dice "
                                f"{r.get('longitud_referencia_m')} m "
                                f"({r.get('diferencia_m')} m de diferencia)")

    def test_la_pista_27_es_imola(self):
        """No tenia nombre en el proyecto: se la llamaba «id-27»."""
        r = tr.contrastar_longitud_declarada(27, 4910)
        self.assertEqual(r["circuito"], "Imola")
        self.assertEqual(r["diferencia_m"], 1.0)

    def test_la_pista_30_no_es_las_vegas(self):
        """El defecto, escrito como prueba.

        Si alguien vuelve a apuntar la pista 30 a Las Vegas, este contraste da
        791 m de diferencia y la prueba cae. Es la unica de las once que se
        aparta mas de veinte metros, y por eso se la pudo ver.
        """
        r = tr.contrastar_longitud_declarada(30, 5410)
        self.assertEqual(r["circuito"], "Miami")
        vegas = tr.LONGITUDES_CIRCUITO[152]["longitud_m"]
        self.assertEqual(abs(5410 - vegas), 791.0)


class CuandoNoSeSabe(unittest.TestCase):
    def test_una_pista_sin_puente_declara_la_ausencia(self):
        r = tr.contrastar_longitud_declarada(999, 5000)
        self.assertFalse(r["concuerda"])
        self.assertIn("999", r["motivo"])
        self.assertIsNone(r.get("longitud_referencia_m"))

    def test_sin_longitud_declarada_no_se_inventa_un_veredicto(self):
        """Resolver la identidad y comprobarla son dos cosas distintas."""
        r = tr.contrastar_longitud_declarada(10, None)
        self.assertEqual(r["circuito"], "Spa-Francorchamps")
        self.assertIsNone(r["concuerda"])
        self.assertIsNone(r["diferencia_m"])


class LaFichaDeLaSesionDiceElCircuitoCorregido(unittest.TestCase):
    """La captura guardo un nombre; la identidad sale del identificador.

    Las veinticuatro capturas ya hechas llevan escrito el nombre que el
    capturador les puso, y una lo lleva **mal**. Reescribir el metadato seria
    tocar el registro de lo capturado. Resolver el nombre desde `circuito_id`
    ---que es el dato que el paquete de sesion emitio--- corrige las que existen
    y las que vengan, sin tocar ninguna.
    """

    def test_la_captura_de_la_pista_30_ya_no_se_llama_las_vegas(self):
        ficha = ps.identidad_del_circuito({
            "circuito_id": 30,
            "circuito": "las-vegas",
            "longitud_declarada_m": 5410,
        })
        self.assertEqual(ficha["circuito"], "miami")
        self.assertEqual(ficha["circuito_openf1"], "Miami")

    def test_lo_que_escribio_la_captura_no_se_pierde(self):
        """Corregir en silencio es la unica cosa peor que no corregir."""
        ficha = ps.identidad_del_circuito({
            "circuito_id": 30,
            "circuito": "las-vegas",
            "longitud_declarada_m": 5410,
        })
        self.assertEqual(ficha["circuito_segun_la_captura"], "las-vegas")

    def test_una_captura_que_ya_estaba_bien_no_declara_correccion(self):
        ficha = ps.identidad_del_circuito({
            "circuito_id": 10,
            "circuito": "spa",
            "longitud_declarada_m": 7007,
        })
        self.assertEqual(ficha["circuito"], "spa")
        self.assertIsNone(ficha["circuito_segun_la_captura"])

    def test_una_pista_sin_puente_conserva_el_nombre_de_la_captura(self):
        """Sin puente no hay con que corregir: se deja lo que hay y se dice."""
        ficha = ps.identidad_del_circuito({
            "circuito_id": 999,
            "circuito": "id-999",
            "longitud_declarada_m": 5000,
        })
        self.assertEqual(ficha["circuito"], "id-999")
        self.assertIsNone(ficha["clave_openf1"])


if __name__ == "__main__":
    unittest.main()
