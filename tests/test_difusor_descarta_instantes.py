# -*- coding: utf-8 -*-
"""Saturado, el difusor descarta instantes enteros y no señales sueltas.

POR QUE IMPORTA, Y NO ES UNA PREFERENCIA. El tablero no dibuja señales: dibuja
**momentos**. Para colocar un coche necesita `world_position_x` y
`world_position_z` **de la misma marca temporal**, y lo dice en su propio
contador:

    llegaronX / llegaronZ / paresRotos
    «una perdida del 50 % en cada una deja un cuarto de los pares:
     el emparejamiento amplifica la perdida al cuadrado»

`deque(maxlen=N)` descarta la señal mas vieja, una por una, sin mirar a que
instante pertenece. Con eso, conservar el 6 % de las señales deja alrededor del
0,4 % de los pares completos: **la pantalla no queda incompleta, queda en
blanco**, que es exactamente lo que se vio en la carrera de seis vehiculos.

MEDIDO antes de este cambio, con seis vehiculos: el difusor recibio 1.416.819
señales y entrego 89.250 ---un 6,3 %--- con 3.044.945 descartes por suscriptor.
Y la cola de 500 señales, a las 10.600 señales/s que produce esa carrera, son
**47 milisegundos** de margen: cualquier pausa del navegador la vacia.

LO QUE ESTE CAMBIO PROMETE, Y LO QUE NO. No promete entregar mas señales: con
un consumidor mas lento que el productor, algo hay que tirar. Promete que lo que
sobreviva sea **coherente**: menos momentos, pero completos y dibujables. Un
coche a siete cuadros por segundo se ve moverse; un coche con el 6 % de sus
señales sueltas no se ve.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from backend import live_stream  # noqa: E402

#: Un instante de seis vehiculos, como el que produce la carrera que fallo.
SENALES_POR_INSTANTE = 12


def instante(marca: str) -> list[dict]:
    """Las señales que comparten una marca temporal, incluido el par de posicion."""

    cuerpos = []
    for coche in range(3):
        vehiculo = "car:%d" % coche
        for senal in ("world_position_x", "world_position_z",
                      "speed", "brake_position"):
            cuerpos.append({"timestamp": marca, "vehicle_id": vehiculo,
                            "signal_name": senal, "value": 1.0})
    return cuerpos


def marcas_presentes(sus) -> list[str]:
    vistas = []
    for c in sus.datos:
        if not vistas or vistas[-1] != c["timestamp"]:
            vistas.append(c["timestamp"])
    return vistas


def completos(sus) -> dict:
    """Cuantas señales quedaron de cada instante."""

    cuenta: dict = {}
    for c in sus.datos:
        cuenta[c["timestamp"]] = cuenta.get(c["timestamp"], 0) + 1
    return cuenta


class LoQueSobreviveEsCoherenteTests(unittest.TestCase):

    def _llenar(self, cuantos: int):
        sus = live_stream.Suscriptor()
        for i in range(cuantos):
            for cuerpo in instante("t%04d" % i):
                sus.poner_dato(cuerpo)
        return sus

    def test_no_queda_ningun_instante_partido(self) -> None:
        """El que dibuja necesita el par, no una de las dos coordenadas."""

        cabe = live_stream.COLA_POR_SUSCRIPTOR // SENALES_POR_INSTANTE
        sus = self._llenar(cabe * 3)
        partidos = {m: n for m, n in completos(sus).items()
                    if n != SENALES_POR_INSTANTE}
        self.assertEqual(
            partidos, {},
            "quedaron instantes con algunas de sus señales y no todas: %r. "
            "Un instante partido no se puede dibujar y ocupa lugar igual"
            % partidos)

    def test_sobreviven_los_mas_nuevos(self) -> None:
        """Tirar lo viejo sigue siendo lo correcto: en vivo lo reciente vale mas."""

        cabe = live_stream.COLA_POR_SUSCRIPTOR // SENALES_POR_INSTANTE
        sus = self._llenar(cabe * 3)
        marcas = marcas_presentes(sus)
        self.assertTrue(marcas, "no quedo nada en la cola")
        ultima = "t%04d" % (cabe * 3 - 1)
        self.assertEqual(marcas[-1], ultima,
                         "se perdio el instante mas nuevo, que es el que el "
                         "tablero esta por dibujar")
        self.assertEqual(marcas, sorted(marcas),
                         "los instantes quedaron desordenados")

    def test_el_par_de_posicion_sobrevive_entero(self) -> None:
        cabe = live_stream.COLA_POR_SUSCRIPTOR // SENALES_POR_INSTANTE
        sus = self._llenar(cabe * 3)
        por_instante: dict = {}
        for c in sus.datos:
            clave = (c["timestamp"], c["vehicle_id"])
            por_instante.setdefault(clave, set()).add(c["signal_name"])
        for clave, senales in por_instante.items():
            self.assertIn("world_position_x", senales,
                          "falta la X de %r: el coche no se puede colocar" % (clave,))
            self.assertIn("world_position_z", senales,
                          "falta la Z de %r: el coche no se puede colocar" % (clave,))

    def test_la_cola_no_crece_sin_limite(self) -> None:
        sus = self._llenar(500)
        self.assertLessEqual(
            len(sus.datos), live_stream.COLA_POR_SUSCRIPTOR + SENALES_POR_INSTANTE,
            "la cola dejo de estar acotada: %d" % len(sus.datos))

    def test_un_instante_mas_grande_que_la_cola_no_la_deja_vacia(self) -> None:
        """Si no entra ni uno, se conserva ese: entregar nada no es una opcion."""

        sus = live_stream.Suscriptor()
        enorme = live_stream.COLA_POR_SUSCRIPTOR + 50
        for i in range(enorme):
            sus.poner_dato({"timestamp": "unico", "vehicle_id": "car:0",
                            "signal_name": "s%d" % i, "value": 1.0})
        self.assertGreater(len(sus.datos), 0,
                           "un instante que no entra vacio la cola entera")

    def test_una_fuente_sin_marca_temporal_no_hace_crecer_la_cola(self) -> None:
        """Si todo es un mismo instante, la coherencia no puede costar la RAM.

        Una fuente que no declare `timestamp` deja a todas las señales en el
        mismo instante, y conservarlo entero seria una cola sin tope: una fuga
        de memoria con otro nombre. Ahi se recorta por la izquierda aunque
        quede partido, que es el unico caso en que eso es lo correcto.
        """

        sus = live_stream.Suscriptor()
        for i in range(live_stream.COLA_POR_SUSCRIPTOR * 2):
            sus.poner_dato({"vehicle_id": "car:0", "signal_name": "s", "value": i})
        self.assertLessEqual(
            len(sus.datos), live_stream.COLA_POR_SUSCRIPTOR,
            "sin marca temporal la cola crecio hasta %d" % len(sus.datos))
        self.assertGreater(sus.descartes_datos, 0)

    def test_las_cuentas_cierran(self) -> None:
        """Encolados = entregados + descartados + lo que sigue esperando."""

        cabe = live_stream.COLA_POR_SUSCRIPTOR // SENALES_POR_INSTANTE
        sus = self._llenar(cabe * 3)
        self.assertEqual(
            sus.encolados, sus.descartes_datos + len(sus.datos),
            "las cuentas no cierran: encolados=%d descartes=%d en cola=%d"
            % (sus.encolados, sus.descartes_datos, len(sus.datos)))

    def test_sin_saturacion_no_se_descarta_nada(self) -> None:
        sus = self._llenar(3)
        self.assertEqual(sus.descartes_datos, 0)
        self.assertEqual(len(sus.datos), 3 * SENALES_POR_INSTANTE)


class LaColaAguantaUnParpadeoDelNavegadorTests(unittest.TestCase):
    """A 10.600 señales/s, 500 ranuras eran 47 ms: menos que un cuadro lento."""

    def test_la_cola_cubre_al_menos_medio_segundo_de_carrera(self) -> None:
        POR_SEGUNDO = 10600          # medido con seis vehiculos
        segundos = live_stream.COLA_POR_SUSCRIPTOR / POR_SEGUNDO
        self.assertGreaterEqual(
            segundos, 0.5,
            "la cola cubre %.0f ms de una carrera de seis vehiculos: cualquier "
            "pausa del navegador la vacia" % (segundos * 1000))


if __name__ == "__main__":
    unittest.main()
