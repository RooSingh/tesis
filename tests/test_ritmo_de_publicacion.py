# -*- coding: utf-8 -*-
"""El ritmo acotado del publicador, y por que se mide contra el comienzo.

POR QUE EXISTE ESE LIMITE. Sin el, el camino por el intermediario publica mas
rapido de lo que el consumidor escribe, el intermediario descarta, y la corrida
**sin ninguna falla** ya pierde. Medido el 2026-09-11 sobre una captura de
404.972 filas: llegaron 100.490 una vez y 271.982 otra, con la misma captura y
el mismo equipo. Sin una corrida limpia que pierda cerca de cero, a ninguna
falla provocada se le puede atribuir la diferencia de filas.

QUE SE COMPRUEBA AQUI. La aritmetica de la espera, que es lo unico que el
limite decide, y se puede ejercer sin broker ni base:

- que el ritmo se mida **contra el comienzo** y no entre mensajes. Un `sleep`
  fijo por mensaje acumula el error de cada espera ---cada una tarda un poco mas
  de lo pedido--- y el ritmo real termina por debajo del pedido. Contra el
  comienzo, lo que se atrasa un mensaje lo recupera el siguiente;
- que un mensaje que ya llego tarde **no espere igual**, porque eso convertiria
  un atraso puntual en un atraso permanente;
- que cero deje el comportamiento de siempre, sin esperar nada.
"""

from __future__ import annotations

import unittest


def espera(publicados: int, por_segundo: float, transcurrido: float) -> float:
    """La misma cuenta que hace el publicador, aislada para poder ejercerla.

    Se escribe aqui y no se importa porque en el guion vive dentro del bucle de
    publicacion, entre una conexion al intermediario y un lector de capturas.
    Extraerla alla obligaria a mover esas dos cosas; lo que se fija es la
    **regla**, y la prueba de abajo comprueba que el guion la conserva.
    """

    if por_segundo <= 0:
        return 0.0
    atraso = publicados / por_segundo - transcurrido
    return atraso if atraso > 0 else 0.0


class ElRitmoSeMideContraElComienzoTests(unittest.TestCase):
    def test_sin_limite_no_se_espera(self) -> None:
        self.assertEqual(espera(1000, 0.0, 0.0), 0.0)
        self.assertEqual(espera(1000, -1.0, 0.0), 0.0)

    def test_a_mil_por_segundo_el_mensaje_mil_va_al_segundo_uno(self) -> None:
        self.assertAlmostEqual(espera(1000, 1000.0, 0.0), 1.0, places=6)
        self.assertAlmostEqual(espera(1000, 1000.0, 0.4), 0.6, places=6)

    def test_un_atraso_no_se_arrastra_al_siguiente(self) -> None:
        """LA PROPIEDAD QUE DISTINGUE ESTA CUENTA DE UN `sleep` FIJO.

        Si un mensaje salio tarde ---el sistema operativo se distrajo, la
        conexion se trabo--- el siguiente **no espera igual**: espera menos, o no
        espera. Con un `sleep` fijo por mensaje cada atraso se suma al anterior y
        el ritmo real cae por debajo del pedido, que es justamente lo que
        arruina una corrida de referencia.
        """

        # Mil mensajes deberian haber salido en 1,0 s y salieron en 1,5.
        self.assertEqual(espera(1000, 1000.0, 1.5), 0.0)
        # Y el siguiente tampoco espera: sigue atrasado.
        self.assertEqual(espera(1001, 1000.0, 1.5), 0.0)
        # Recien cuando el reloj lo alcanza, vuelve a esperar.
        self.assertAlmostEqual(espera(1600, 1000.0, 1.5), 0.1, places=6)

    def test_la_espera_nunca_es_negativa(self) -> None:
        """Un `sleep` negativo es un error, y una espera negativa dicha en voz
        alta seria «este mensaje sale antes de que le toque», que no significa
        nada."""

        for transcurrido in (2.0, 10.0, 1e6):
            self.assertGreaterEqual(espera(100, 1000.0, transcurrido), 0.0)

    def test_el_ritmo_pedido_se_cumple_sobre_la_corrida(self) -> None:
        """Se simula una corrida entera con un reloj propio: mil mensajes a
        quinientos por segundo tienen que ocupar dos segundos, no mas."""

        reloj = 0.0
        for n in range(1, 1001):
            reloj += 0.0001                    # lo que cuesta publicar uno
            reloj += espera(n, 500.0, reloj)
        self.assertAlmostEqual(reloj, 2.0, places=3)


class ElGuionConservaLaRegla(unittest.TestCase):
    def test_el_publicador_mide_contra_el_comienzo(self) -> None:
        """Se comprueba sobre el guion que se publica, porque la cuenta de
        arriba es una copia de su regla y una copia puede quedar vieja."""

        from pathlib import Path
        raiz = Path(__file__).resolve().parents[1]
        codigo = (raiz / "scripts" / "republicar_captura.py").read_text(
            encoding="utf-8")
        i = codigo.index("if por_segundo > 0:")
        bloque = codigo[i:i + 400]
        self.assertIn("publicados / por_segundo", bloque,
                      "el ritmo no se calcula sobre el total publicado")
        self.assertIn("time.perf_counter() - inicio", bloque,
                      "el ritmo no se mide contra el comienzo de la corrida")
        self.assertIn("if atraso > 0", bloque,
                      "se puede pedir una espera negativa")

    def test_el_limite_se_puede_pedir_desde_la_linea_de_comandos(self) -> None:
        from pathlib import Path
        raiz = Path(__file__).resolve().parents[1]
        codigo = (raiz / "scripts" / "republicar_captura.py").read_text(
            encoding="utf-8")
        self.assertIn('"--por-segundo"', codigo)
        self.assertIn("args.por_segundo", codigo,
                      "el argumento se declara y no se pasa: el limite nunca "
                      "llegaria al bucle")


if __name__ == "__main__":
    unittest.main()
