"""El peldano contra un consumidor lento: protecciones, freno e inventario.

Se fija lo que tiene que valer **antes** de levantar ninguna infraestructura:

- que se niega a apuntar al intermediario o a la base principales, con codigo
  distinto de cero y sin conectarse a nada;
- que el freno es un tope sostenido: un escritor falso frenado a 2.000 filas
  por segundo escribe entre 1.990 y 2.010, y un rato ocioso no le da credito
  para una rafaga;
- que la ayuda se imprime y que el inventario de la captura de Catalunya da las
  432.062 filas que el encargo declara (solo si la captura esta en la maquina).
"""

import contextlib
import io
import subprocess
import sys
import time
import unittest
from pathlib import Path

from scripts import peldano_ventana_consumidor_lento as peldano

ROOT = Path(__file__).resolve().parents[1]
CATALUNYA = ROOT / "datasets" / "f1_25" / "capturas" / "20260831_2139_catalunya_contrarreloj.f1raw"


class EscritorFalso:
    def __init__(self):
        self.filas = 0

    def __call__(self, mensajes):
        self.filas += len(mensajes)
        return len(mensajes)


class Protecciones(unittest.TestCase):

    def _negado(self, *extra):
        with self.assertRaises(SystemExit) as salida:
            peldano.negar_destino_principal(peldano.argumentos(["x.f1raw", *extra]))
        self.assertNotEqual(salida.exception.code, 0)
        self.assertIn("NEGADO", str(salida.exception.code))

    def test_se_niega_al_intermediario_principal(self):
        self._negado("--mqtt-puerto", "1883")

    def test_se_niega_a_la_base_por_nombre(self):
        self._negado("--db-nombre", "tesis_db")

    def test_se_niega_a_la_base_por_puerto(self):
        self._negado("--db-puerto", "5432")

    def test_la_pila_aislada_pasa(self):
        peldano.negar_destino_principal(peldano.argumentos(["x.f1raw"]))

    def test_desde_la_linea_de_ordenes_sale_con_codigo_distinto_de_cero(self):
        proceso = subprocess.run(
            [sys.executable, "-B", str(ROOT / "scripts" / "peldano_ventana_consumidor_lento.py"),
             "x.f1raw", "--mqtt-puerto", "1883"],
            capture_output=True, text=True, cwd=str(ROOT), timeout=60)
        self.assertNotEqual(proceso.returncode, 0)
        self.assertIn("NEGADO", proceso.stderr)

    def test_la_ayuda_se_imprime(self):
        proceso = subprocess.run(
            [sys.executable, "-B", str(ROOT / "scripts" / "peldano_ventana_consumidor_lento.py"),
             "--help"], capture_output=True, text=True, cwd=str(ROOT), timeout=60)
        self.assertEqual(proceso.returncode, 0)
        self.assertIn("--espera-maxima", proceso.stdout)
        self.assertIn("--solo-inventario", proceso.stdout)


class Freno(unittest.TestCase):

    def test_sin_freno_devuelve_la_misma_clase(self):
        self.assertIs(peldano.frenar(EscritorFalso, 0), EscritorFalso)

    def test_un_escritor_falso_a_dos_mil_filas_por_segundo(self):
        escritor = peldano.frenar(EscritorFalso, 2000.0)()
        lote = [None] * 200
        comienzo = time.perf_counter()
        for _ in range(20):  # 4.000 filas: dos segundos
            escritor(lote)
        ritmo = escritor.filas / (time.perf_counter() - comienzo)
        self.assertGreaterEqual(ritmo, 1990.0)
        self.assertLessEqual(ritmo, 2010.0)

    def test_un_rato_ocioso_no_acumula_credito(self):
        """Tras un segundo sin trabajo, el lote siguiente espera su turno entero."""
        ahora = [0.0]
        esperas = []

        def reloj():
            return ahora[0]

        def dormir(segundos):
            esperas.append(segundos)
            ahora[0] += segundos

        escritor = peldano.frenar(EscritorFalso, 1000.0, reloj=reloj, dormir=dormir)()
        escritor([None] * 100)          # turno de 0,1 s
        ahora[0] += 1.0                 # ocioso
        escritor([None] * 100)

        self.assertAlmostEqual(esperas[0], 0.1)
        self.assertAlmostEqual(esperas[1], 0.1)

    def test_un_retraso_chico_se_compensa(self):
        ahora = [0.0]
        esperas = []

        def dormir(segundos):
            esperas.append(segundos)
            ahora[0] += segundos + 0.01  # el sistema se pasa 10 ms

        escritor = peldano.frenar(EscritorFalso, 1000.0, reloj=lambda: ahora[0], dormir=dormir)()
        escritor([None] * 100)
        escritor([None] * 100)

        self.assertAlmostEqual(esperas[1], 0.09)


@unittest.skipUnless(CATALUNYA.exists(), "la captura de Catalunya no esta en esta maquina")
class Inventario(unittest.TestCase):

    def test_catalunya_da_432062_filas(self):
        proceso = subprocess.run(
            [sys.executable, "-B", str(ROOT / "scripts" / "peldano_ventana_consumidor_lento.py"),
             str(CATALUNYA), "--solo-inventario"],
            capture_output=True, text=True, cwd=str(ROOT), timeout=600)
        self.assertEqual(proceso.returncode, 0, proceso.stderr[-500:])
        self.assertIn("filas      : 432062 ", proceso.stdout)


if __name__ == "__main__":
    unittest.main()
