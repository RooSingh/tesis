# -*- coding: utf-8 -*-
"""Los escenarios de frecuencia variable y de llegada irregular.

Que cuidan estas pruebas
------------------------
El escenario escribe en disco y levanta procesos, de modo que lo que se fija aca
no es su salida sino **las decisiones que lo vuelven interpretable**. Cada una
corresponde a un error concreto que se cometio al construirlo:

1. **el receptor no puede ser el que escucha al juego**, porque republicaria
   telemetria real y la duplicaria en la base: las filas de una captura viva no
   llevan identidad de reinyeccion y nada las deduplicaria;
2. **el escenario tiene que conciliar las dos restas**, y no solo contar lo que
   llego: lo leido tiene que ser lo descartado mas lo emitido, y lo recibido
   tiene que ser lo emitido menos lo perdido en el camino;
3. **la velocidad y la degradacion no se mezclan en el mismo escenario**, porque
   entonces un resultado no se puede atribuir a una causa.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

import capturar_f1_25  # noqa: E402
import correr_escenarios_degradacion as esc  # noqa: E402


class NoInterfiereConLaCapturaDeVerdad(unittest.TestCase):
    """La razon por la que el escenario tiene puerto y destino propios."""

    def test_el_escenario_no_usa_el_puerto_del_juego(self):
        self.assertNotEqual(esc.PUERTO_ESCENARIO, capturar_f1_25.PUERTO_JUEGO)

    def test_el_escenario_no_escribe_en_el_directorio_de_capturas(self):
        """Una captura de escenario entre las reales contaminaria las medidas.

        La medicion del intervalo lee todas las capturas del directorio: una
        reproduccion degradada ahi dentro entraria a los promedios como si
        fuera una sesion jugada.
        """

        self.assertNotEqual(esc.DESTINO.resolve(),
                            capturar_f1_25.DESTINO_POR_DEFECTO.resolve())

    def test_el_receptor_del_escenario_no_publica(self):
        """Republicar una sesion real la duplicaria en la base."""

        fuente = Path(esc.__file__).read_text(encoding="utf-8")
        self.assertIn('"--sin-publicar"', fuente)

    def test_el_capturador_conserva_el_puerto_del_juego_por_omision(self):
        """Nada cambia para quien no pase el parametro."""

        self.assertEqual(capturar_f1_25.PUERTO_JUEGO, 20777)


class LosEscenariosAislanUnaVariable(unittest.TestCase):
    """Mezclar dos causas en una corrida impide atribuir el resultado."""

    def test_los_de_frecuencia_no_llevan_degradacion(self):
        for e in esc.ESCENARIOS:
            if e["nombre"].startswith("frecuencia"):
                self.assertEqual(e.get("descarte", 0.0), 0.0, e["nombre"])
                self.assertEqual(e.get("jitter_ms", 0.0), 0.0, e["nombre"])

    def test_los_de_degradacion_corren_a_velocidad_normal(self):
        for e in esc.ESCENARIOS:
            if not e["nombre"].startswith("frecuencia"):
                self.assertEqual(e.get("velocidad", 1.0), 1.0, e["nombre"])

    def test_hay_un_escenario_que_combina_las_dos_degradaciones(self):
        """Uno solo, y declarado: sirve para ver si se componen o no."""

        combinados = [e for e in esc.ESCENARIOS
                      if e.get("descarte") and e.get("jitter_ms")]
        self.assertEqual(len(combinados), 1)

    def test_todos_los_escenarios_fijan_la_semilla(self):
        """Sin semilla fija un escenario no se puede repetir."""

        for e in esc.ESCENARIOS:
            if e.get("descarte") or e.get("jitter_ms"):
                # La semilla por omision del corredor es explicita y fija.
                fuente = Path(esc.__file__).read_text(encoding="utf-8")
                self.assertIn('escenario.get("semilla", 7)', fuente)
                break

    def test_los_nombres_de_escenario_son_unicos(self):
        """Dos escenarios con el mismo nombre se pisan el archivo de salida."""

        nombres = [e["nombre"] for e in esc.ESCENARIOS]
        self.assertEqual(len(nombres), len(set(nombres)))


class ConciliaLasDosRestas(unittest.TestCase):
    """Contar lo que llego no alcanza: hay que cerrar las dos cuentas."""

    def test_declara_si_la_cuenta_del_emisor_cierra(self):
        fuente = Path(esc.__file__).read_text(encoding="utf-8")
        self.assertIn('"cierra_el_emisor"', fuente)

    def test_declara_lo_perdido_en_el_camino(self):
        fuente = Path(esc.__file__).read_text(encoding="utf-8")
        self.assertIn('"perdidos_en_el_camino"', fuente)

    def test_espera_a_que_el_receptor_este_escuchando(self):
        """Emitir antes de que el socket este ligado informaria una perdida
        que no ocurrio en el camino sino en el arranque."""

        fuente = Path(esc.__file__).read_text(encoding="utf-8")
        self.assertIn("time.sleep(2.0)", fuente)

    def test_espera_el_silencio_que_cierra_la_captura(self):
        """Sin esperarlo, el archivo quedaria incompleto y faltarian
        datagramas que si habian llegado."""

        fuente = Path(esc.__file__).read_text(encoding="utf-8")
        self.assertIn("SILENCIO_S + 3.0", fuente)


if __name__ == "__main__":
    unittest.main()
