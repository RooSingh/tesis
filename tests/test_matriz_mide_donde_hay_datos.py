# -*- coding: utf-8 -*-
"""Sobre que sesion mide la matriz la frecuencia de una fuente.

QUE ESTABA MAL. `_contexto_reciente` tomaba la sesion **mas reciente** de cada
fuente y medía ahí una ventana de dos minutos. Una captura de prueba de diez
segundos es lo mas reciente que hay, y entonces la frecuencia que la matriz
publica como caracteristica de la fuente es la de un descarte.

Medido sobre la base local el 2026-09-12: el simulador tiene tres sesiones. La
mas reciente ---`1259090092025026157`--- tiene 17.094 filas; la captura de
verdad ---`3731090176871608020`--- tiene 5.641.702, trescientas treinta veces
mas, y es mas vieja. La matriz declaraba **2,9 Hz** para el simulador; lo medido
en este proyecto sobre la captura real es 58,3 Hz. Veinte veces menos, en el
numero que alguien copiaria de una tesis.

EL MODULO YA SABIA DE ESTE ERROR EN OTRA DIMENSION. Su propio comentario cuenta
que contar juntos a veinte conductores dio «noventa hercios donde hay cuatro», y
por eso el contexto incluye al conductor. La sesion es la misma clase de
descuido y quedo sin arreglar.

Y `backend.analisis.disponibilidad` ---que resuelve la misma pregunta para sus
mediciones--- ya tomaba «la terna con mas filas». Dos modulos contestando
distinto a lo mismo.
"""

from __future__ import annotations

import unittest

from backend import matriz_fuentes as mf


class CursorFalso:
    def __init__(self, filas):
        self.filas = filas
        self.consultas = []

    def execute(self, sql, parametros=(), *_a, **_k):
        self.consultas.append(" ".join(sql.split()))
        self.parametros = parametros

    def fetchone(self):
        return self.filas[0] if self.filas else None


class ElContextoSeEligePorDatosTests(unittest.TestCase):

    def test_la_consulta_ordena_por_cuantas_filas_hay(self) -> None:
        """Y no por cual llego ultima.

        Se mira la consulta y no el resultado: con un cursor falso cualquier
        criterio devuelve la fila que se le ponga delante, de modo que aserverar
        sobre el resultado no comprobaria nada.
        """
        cursor = CursorFalso([("sesion", "conductor", "2026-09-12")])
        mf._contexto_reciente(cursor, "f1_25_udp_simulation")
        consulta = cursor.consultas[0]
        self.assertIn("order by count(*) desc", consulta,
                      "la matriz sigue midiendo donde llego el ultimo dato: " + consulta)
        self.assertNotIn("order by max(timestamp) desc", consulta)

    def test_sigue_resolviendo_por_conductor(self) -> None:
        """Lo que el modulo ya habia arreglado no se pierde al arreglar lo otro.

        Contar juntos a los veinte conductores de una sesion deportiva
        multiplica por veinte la frecuencia aparente, y eso ya paso una vez.
        """
        cursor = CursorFalso([("sesion", "conductor", "2026-09-12")])
        mf._contexto_reciente(cursor, "openf1_historical_replay")
        self.assertIn("group by session_id, driver_id", cursor.consultas[0])

    def test_la_matriz_dice_sobre_que_midio(self) -> None:
        """Una medicion que no nombra su recorte no es verificable.

        El texto decia «la sesion y el vehiculo mas recientes de cada fuente», y
        eso dejo de ser cierto: describir mal el recorte es peor que no
        describirlo, porque invita a confiar.
        """
        self.assertNotIn("mas recientes", mf.MEDIDO_SOBRE)
        self.assertIn("filas", mf.MEDIDO_SOBRE)


if __name__ == "__main__":
    unittest.main()
