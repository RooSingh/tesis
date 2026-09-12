# -*- coding: utf-8 -*-
"""Los hechos que estan escritos dos veces tienen que decir lo mismo.

POR QUE HAY DOS COPIAS. El tablero necesita explicar por que una fuente no
tiene metro medido **sin esperar a que la API conteste**: el panel de trazado
lo dice antes de pedir nada. El backend la necesita para negar el eje espacial
cuando se lo piden. Unificarlas de verdad ---que el guion pida la declaracion
al arrancar--- es trabajo aparte.

POR QUE ESTA PRUEBA EXISTE. El 2026-09-12 se corrigio una cifra que estaba mal
en **tres** sitios: la separacion entre muestras de la fuente deportiva, que se
declaraba como «hasta 83 m» sin derivacion en ningun archivo y sin cerrar
---83 m en 1,100 s son 272 km/h, y esa vuelta pica a 312---. Dos de las tres
copias estaban atadas por esta prueba y cayeron juntas; la tercera no lo estaba
y se podia haber quedado diciendo lo viejo. Esa tercera se elimino componiendola
a partir del hecho.

Una duplicacion vigilada no es lo mismo que una duplicacion.
"""

from __future__ import annotations

import pathlib
import re
import unittest

from backend import api_sesion, matriz_fuentes


def _hasta_la_llave_que_cierra(texto: str, abre: int) -> str:
    """El trozo entre una llave y la suya, contando las de adentro."""
    nivel = 0
    for i in range(abre, len(texto)):
        if texto[i] == "{":
            nivel += 1
        elif texto[i] == "}":
            nivel -= 1
            if nivel == 0:
                return texto[abre:i + 1]
    raise AssertionError("llave sin cerrar")


class ElEjeDeDistancia(unittest.TestCase):

    #: Como se llama cada fuente en el tablero.
    EQUIVALENCIAS = {"f1": "f1_25_udp_simulation",
                     "openf1": "openf1_historical_replay",
                     "can": "can_real_replay"}

    @staticmethod
    def _declaracion_del_tablero():
        """Saca `EJE_DE_DISTANCIA_POR_FUENTE` del guion, sin copiarla aca."""
        texto = (pathlib.Path(__file__).resolve().parents[1]
                 / "dashboard" / "app.js").read_text(encoding="utf-8")
        inicio = texto.index("const EJE_DE_DISTANCIA_POR_FUENTE = {")
        cuerpo = texto[inicio:texto.index("\n};", inicio)]
        salida = {}
        for clave in ("f1", "openf1", "can"):
            # Con `index` a secas, buscar «f1: {» encontraria «openf1: {» segun
            # el orden en que esten escritas. El limite de palabra lo evita.
            m = re.search(r"\b" + clave + r": \{", cuerpo)
            entrada = _hasta_la_llave_que_cierra(cuerpo, m.end() - 1)
            salida[clave] = {
                "hay": "hay: true" in entrada,
                # Las cadenas del guion vienen partidas con `+`: se vuelven a unir.
                "porque": "".join(re.findall(r'"([^"]*)"', entrada)),
            }
        return salida

    def test_el_tablero_y_la_matriz_dicen_lo_mismo(self):
        tablero = self._declaracion_del_tablero()
        for clave, fuente in self.EQUIVALENCIAS.items():
            with self.subTest(fuente=fuente):
                aca = matriz_fuentes.EJE_DE_DISTANCIA[fuente]
                self.assertEqual(tablero[clave]["hay"], aca["hay"])
                self.assertEqual(" ".join(tablero[clave]["porque"].split()),
                                 " ".join(aca["porque"].split()))

    def test_la_api_no_escribe_su_propia_version_del_hecho(self):
        """La tercera copia se elimino componiendola: esto lo mantiene asi.

        Si alguien vuelve a escribir el motivo a mano en `api_sesion`, el texto
        deja de empezar por el de la matriz y esta prueba cae.
        """
        for fuente, mensaje in api_sesion.SIN_DISTANCIA_PORQUE.items():
            with self.subTest(fuente=fuente):
                hecho = matriz_fuentes.EJE_DE_DISTANCIA[fuente]["porque"]
                self.assertTrue(mensaje.startswith(hecho),
                                f"{fuente}: el mensaje no sale del hecho")

    def test_solo_se_explican_las_fuentes_que_no_tienen_metro(self):
        """Explicar una ausencia que no existe manda a buscar donde no hay."""
        for fuente, declaracion in matriz_fuentes.EJE_DE_DISTANCIA.items():
            if declaracion["hay"]:
                self.assertNotIn(fuente, api_sesion.SIN_DISTANCIA_PORQUE)
            else:
                self.assertIn(fuente, api_sesion.SIN_DISTANCIA_PORQUE)


if __name__ == "__main__":
    unittest.main()
