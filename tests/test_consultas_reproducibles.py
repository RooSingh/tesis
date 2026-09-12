# -*- coding: utf-8 -*-
"""Ninguna consulta elige «la primera» sin desempate.

EL DEFECTO QUE LO MOTIVA, MEDIDO EL 2026-09-12. El analisis de sectores devolvio
**0,341 s y 0,491 s para el mismo coche en dos corridas seguidas sobre el mismo
dato**. Emparejaba señales que llegan con la misma marca de tiempo, y el orden
entre filas que empatan no esta definido: la base devuelve la que quiere.

Un analisis que no repite su propio numero no es una medicion, y el sintoma es
invisible ---sale un numero plausible, del tamano correcto---.

ESTA PRUEBA MIRA EL TEXTO DE LAS CONSULTAS, y eso tiene un limite que conviene
decir: comprueba que el desempate **este escrito**, no que sea el correcto. Lo
segundo se prueba donde se puede, dandole a la funcion las mismas filas en otro
orden y exigiendo el mismo resultado ---como en `test_analisis_sectores`---. Las
dos hacen falta: una recorre todo el archivo y la otra prueba de verdad.

QUE QUEDO AUDITADO A MANO Y NO ENTRA ACA. Las consultas que eligen la primera
fila con `ORDER BY timestamp LIMIT 1` ---los cuatro anotadores de
`api_sesion`--- agrupan antes por `timestamp`, de modo que en su resultado no
puede haber dos filas con la misma marca. Ahi el empate es imposible por
construccion y no hace falta desempatar. Comprobarlo leyendo el texto exigiria
entender el `GROUP BY`, y una prueba que adivina estructura acusa de mas.
"""

from __future__ import annotations

import pathlib
import re
import unittest

RAIZ = pathlib.Path(__file__).resolve().parents[1]

#: Donde se busca. Son los archivos que consultan la tabla de telemetria.
ARCHIVOS = ("backend/api_sesion.py", "backend/api_analisis.py", "backend/db.py",
            "backend/app.py", "backend/analisis/sectores.py",
            "backend/analisis/delta.py", "backend/analisis/vueltas.py")


def _ordenes_de_los_distinct(texto: str) -> list[str]:
    """El `ORDER BY` de cada `DISTINCT ON`, que es el que sigue.

    SE BUSCA EL QUE SIGUE Y NO CUALQUIERA DEL ARCHIVO. La primera version de
    esta prueba marcaba todos los `ORDER BY` de un archivo que tuviera un
    `DISTINCT ON` en cualquier parte, y acuso once consultas que solo ordenan un
    resultado ---donde un empate no cambia nada, porque salen todas las filas---.
    Una prueba que acusa de mas se desactiva, y entonces no comprueba nada.
    """

    salida = []
    for m in re.finditer(r"DISTINCT ON", texto, flags=re.IGNORECASE):
        siguiente = re.search(r"ORDER BY[^\"')]+", texto[m.end():],
                              flags=re.IGNORECASE)
        if siguiente:
            salida.append(" ".join(siguiente.group(0).split()))
    return salida


class NingunDistinctOnDecidePorEmpate(unittest.TestCase):

    #: Un orden que termina en la marca de tiempo. Es el patron exacto que
    #: fallo: dos filas del mismo instante y la base elige.
    FINAL_EN_TIEMPO = re.compile(r"timestamp( DESC| ASC)?\s*$", flags=re.IGNORECASE)

    def test_cada_distinct_on_desempata(self):
        for relativo in ARCHIVOS:
            texto = (RAIZ / relativo).read_text(encoding="utf-8")
            for orden in _ordenes_de_los_distinct(texto):
                with self.subTest(archivo=relativo, orden=orden):
                    self.assertIsNone(
                        self.FINAL_EN_TIEMPO.search(orden),
                        "este DISTINCT ON ordena hasta la marca de tiempo y "
                        "nada mas: si dos filas empatan ahi, la base elige "
                        "cual sobrevive. Agregale una columna que las "
                        "distinga.")

    def test_hay_distinct_on_que_mirar(self):
        """Si nadie usa `DISTINCT ON`, la prueba de arriba pasa sin comprobar.

        Es la forma silenciosa de que un guardian deje de guardar: el patron se
        renombra, la busqueda no encuentra nada y todo sigue verde.
        """
        cuantos = sum(len(_ordenes_de_los_distinct(
            (RAIZ / r).read_text(encoding="utf-8"))) for r in ARCHIVOS)
        self.assertGreaterEqual(cuantos, 3, "no se encontro ningun DISTINCT ON")

    def test_el_analisis_de_sectores_pide_un_orden_total(self):
        """El que fallo de verdad. Queda fijado para que no vuelva."""
        texto = (RAIZ / "backend/analisis/sectores.py").read_text(encoding="utf-8")
        self.assertIn("order by vehicle_id, timestamp, signal_name", texto)


if __name__ == "__main__":
    unittest.main()
