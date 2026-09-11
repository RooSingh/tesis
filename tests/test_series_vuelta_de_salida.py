# -*- coding: utf-8 -*-
"""La vuelta de salida tambien es parte de la vuelta.

EL DEFECTO QUE ESTO CUIDA. `series_por_distancia` aplicaba `desde_m` dos veces
y con dos significados distintos:

    if desde_m:                          # en SQL: 0.0 es falso -> sin cota
        filtro_distancia += " AND distancia >= %s"
    ...
    if d is None or d < desde_m:         # en Python: 0.0 es un piso real
        continue

Un parametro sin poner valia «sin limite» en un lado y «piso en cero» en el
otro. Como `lap_distance` es **negativa antes de cruzar la meta**, el segundo
filtro borraba la vuelta de salida entera sin que nadie lo pidiera.

MEDIDO el 2026-09-11 sobre `f1_25:session:3527452921763583202`, coche propio
`car:19`: la vuelta 1 tiene 5.355 muestras de velocidad, de las cuales 3.594
estan en distancia negativa ---02:37:59 a 02:40:59, tres minutos--- y 1.761 en
distancia positiva. Las condiciones de la ruta alcanzaban a las 5.355; la
respuesta declaraba `muestras_originales: 1761`.

LO QUE SE VEIA. `/vueltas` declara la vuelta 1 de 267,715 s porque cuenta la
salida; la serie cubria solo sus ultimos 87,95 s. El reproductor reparte el
cabezal sobre los 267,7 s declarados, de modo que durante **180 segundos** el
instante del cabezal caia antes de la primera muestra de la serie y toda
lectura por tiempo se clavaba en la muestra cero: los relojes congelados, el
pie en «1 m» y los cuatro lienzos con un solo punto, que no dibuja nada.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend import api_sesion


class ConexionFalsa:
    """Sustituye a `db.obtener_conexion` y recuerda lo que se le pidio."""

    def __init__(self, filas=None):
        self.filas = filas if filas is not None else []
        self.consultas: list[tuple[str, tuple]] = []
        self.cursor_obj = MagicMock()
        self.cursor_obj.execute.side_effect = self._ejecutar
        self.cursor_obj.fetchall.side_effect = lambda: list(self.filas)
        self.cursor_obj.fetchone.side_effect = lambda: (self.filas[0] if self.filas else None)

    def _ejecutar(self, consulta, parametros=None):
        self.consultas.append((consulta, parametros))

    def cursor(self, *_, **__):
        contexto = MagicMock()
        contexto.__enter__ = lambda *_: self.cursor_obj
        contexto.__exit__ = lambda *_: False
        return contexto

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _con(filas=None):
    falsa = ConexionFalsa(filas)
    return falsa, patch("backend.api_sesion.db.obtener_conexion", return_value=falsa)


#: (timestamp, vehicle_id, distancia, distancia_sesion, speed)
#: Tres muestras antes de la meta y dos despues, que es la forma de una vuelta
#: de salida: se sale de boxes con distancia negativa y se cruza la meta en
#: cero.
SALIDA_Y_VUELTA = [
    ("t1", "car19", -4628.4, 0.0, 280.0),
    ("t2", "car19", -2100.0, 2528.4, 250.0),
    ("t3", "car19", -50.0, 4578.4, 190.0),
    ("t4", "car19", 1.23, 4629.6, 142.0),
    ("t5", "car19", 942.63, 5571.0, 210.0),
]


class LaVueltaDeSalidaNoSeBorraSolaTests(unittest.TestCase):
    """Sin cota pedida no hay cota: una distancia negativa es una medicion."""

    def test_sin_desde_m_sobreviven_las_distancias_negativas(self) -> None:
        falsa, parche = _con(SALIDA_Y_VUELTA)
        with parche:
            r = api_sesion.series_por_distancia("f1_25:session:1", senales="speed")
        self.assertEqual(r["vehiculos"]["car19"]["distancia_m"],
                         [-4628.4, -2100.0, -50.0, 1.23, 942.63])
        self.assertEqual(r["muestras_originales"], 5)

    def test_sin_desde_m_la_consulta_tampoco_pone_cota(self) -> None:
        """Las dos mitades del filtro tienen que decir lo mismo."""
        falsa, parche = _con(SALIDA_Y_VUELTA)
        with parche:
            api_sesion.series_por_distancia("f1_25:session:1", senales="speed")
        consulta = falsa.consultas[-1][0]
        self.assertNotIn("distancia >= %s", consulta)

    def test_un_cero_pedido_a_proposito_si_es_un_piso(self) -> None:
        """Pedir cero es pedir desde la meta, y entonces se acota en los dos lados."""
        falsa, parche = _con(SALIDA_Y_VUELTA)
        with parche:
            r = api_sesion.series_por_distancia("f1_25:session:1", senales="speed",
                                                desde_m=0.0)
        self.assertEqual(r["vehiculos"]["car19"]["distancia_m"], [1.23, 942.63])
        consulta, parametros = falsa.consultas[-1]
        self.assertIn("distancia >= %s", consulta)
        self.assertIn(0.0, parametros)

    def test_una_cota_positiva_sigue_acotando(self) -> None:
        falsa, parche = _con(SALIDA_Y_VUELTA)
        with parche:
            r = api_sesion.series_por_distancia("f1_25:session:1", senales="speed",
                                                desde_m=100.0)
        self.assertEqual(r["vehiculos"]["car19"]["distancia_m"], [942.63])

    def test_una_cota_negativa_recorta_la_salida_sin_borrarla(self) -> None:
        falsa, parche = _con(SALIDA_Y_VUELTA)
        with parche:
            r = api_sesion.series_por_distancia("f1_25:session:1", senales="speed",
                                                desde_m=-3000.0)
        self.assertEqual(r["vehiculos"]["car19"]["distancia_m"],
                         [-2100.0, -50.0, 1.23, 942.63])

    def test_el_techo_sigue_funcionando_sobre_distancias_negativas(self) -> None:
        falsa, parche = _con(SALIDA_Y_VUELTA)
        with parche:
            r = api_sesion.series_por_distancia("f1_25:session:1", senales="speed",
                                                hasta_m=0.0)
        self.assertEqual(r["vehiculos"]["car19"]["distancia_m"],
                         [-4628.4, -2100.0, -50.0])


class ElEmpateDeDistanciaLoDesempataElTiempoTests(unittest.TestCase):
    """Parado en el box, muchisimas muestras comparten el mismo metro.

    MEDIDO el 2026-09-11 sobre la vuelta 1 de Catalunya, coche propio: entre
    02:37:59 y 02:39:20 hay **1.602 muestras de `lap_distance` con solo 86
    valores distintos**. Son empates de casi veinte muestras cada uno, y
    `ORDER BY vehicle_id, distancia` no dice nada sobre como se ordenan entre
    si: el orden lo elige el plan de la consulta y puede cambiar. Desempatar
    por `timestamp` hace la serie reproducible.

    LO QUE ESTO **NO** ARREGLA, Y CONVIENE DECIRLO. La serie sigue sin ser
    monotona en tiempo, y no puede serlo: un coche detenido ocupa el mismo
    metro durante setenta y cinco segundos, de modo que ordenar por distancia
    necesariamente mezcla instantes. Se comprobo que la unica inversion que
    quedaba ---02:39:15 antes que 02:38:00--- no es un empate sino dos
    distancias distintas, -4628,40185 y otra mayor, que el redondeo a dos
    decimales de la respuesta muestra como el mismo «-4628,4». El orden por
    distancia era correcto; lo que engañaba era la cifra impresa.
    """

    def test_la_consulta_desempata_por_tiempo(self) -> None:
        falsa, parche = _con(SALIDA_Y_VUELTA)
        with parche:
            api_sesion.series_por_distancia("f1_25:session:1", senales="speed")
        consulta = falsa.consultas[-1][0]
        self.assertIn("ORDER BY vehicle_id, distancia, timestamp", consulta,
                      "sin desempate, las casi veinte muestras que comparten "
                      "un metro salen en el orden que elija el plan")


class LasDosMitadesDelFiltroDicenLoMismoTests(unittest.TestCase):
    """Una guarda de codigo: el defecto fue que una mitad usaba la verdad del
    valor y la otra su mera presencia. Mientras la cota se decida por
    `is not None` en los dos sitios, no puede volver a divergir."""

    def test_ninguna_mitad_decide_la_cota_por_verdad(self) -> None:
        import inspect

        # Solo el codigo: el comentario que explica el defecto nombra la forma
        # vieja a proposito, y una guarda que se dispara con su propia
        # documentacion no mide nada.
        codigo = [renglon.split("#", 1)[0]
                  for renglon in inspect.getsource(
                      api_sesion.series_por_distancia).splitlines()]
        culpables = [r.strip() for r in codigo if "if desde_m:" in r]
        self.assertEqual(culpables, [],
                         "la cota se decide por verdad y un cero pedido se "
                         "confunde con una cota no pedida: " + repr(culpables))
        self.assertTrue(any("desde_m is not None" in r for r in codigo),
                        "la cota ya no se decide por presencia declarada")


if __name__ == "__main__":
    unittest.main()
