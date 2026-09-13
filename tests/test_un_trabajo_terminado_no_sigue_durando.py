# -*- coding: utf-8 -*-
"""Lo que termino duro lo que duro, y no sigue durando.

EL DEFECTO, reportado el 2026-09-13 con las dos pantallas al lado. El tablero
mostro «Procesado en 17 s» al terminar el trabajo, y un rato despues `/trabajos`
decia **101,8 s** del mismo trabajo. Ninguno de los dos mentia sobre lo que
media: `a_dict()` calculaba

    "duracion_s": round(time.monotonic() - self.comienzo_monotono, 1)

o sea **el tiempo desde que arranco hasta ahora**, que para un trabajo en curso
es la duracion y para uno terminado es otra cosa: cuanto hace que empezo. Un
trabajo de la semana pasada informaria dias.

POR QUE IMPORTA MAS DE LO QUE PARECE. `duracion_s` es lo que se usa para decir
cuanto tarda una importacion, y esa cifra es de las que terminan en el informe.
Una medicion que crece sola cuando nadie la mira no es una medicion.

LA FORMA DEL ARREGLO, Y POR QUE NO ES UN CAMPO SUELTO. Hay **cinco** sitios que
marcan el final de un trabajo ---termina una funcion, no arranca el proceso,
termina el proceso, se pide detener sin proceso, se detiene---. Agregar un
campo y acordarse de escribirlo en los cinco funciona hoy y falla el dia que
alguien agregue el sexto, en silencio y sin que ninguna prueba se queje. Por eso
el final se marca en **un solo lugar**, `marcar_fin()`, y hay una prueba
estructural aca abajo que falla si vuelve a aparecer una asignacion suelta.
"""

from __future__ import annotations

import re
import sys
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from backend import ingesta  # noqa: E402
from tests.test_ingesta import ProcesoFalso, _esperar_trabajo  # noqa: E402


class LaDuracionSeCongela(unittest.TestCase):

    def setUp(self) -> None:
        ingesta.trabajos.reiniciar()
        self.addCleanup(ingesta.trabajos.reiniciar)
        self._temporal = TemporaryDirectory()
        self.addCleanup(self._temporal.cleanup)
        bitacoras = Path(self._temporal.name) / "logs"
        bitacoras.mkdir(parents=True)
        parche = patch.object(ingesta, "BITACORAS", bitacoras)
        parche.start()
        self.addCleanup(parche.stop)

    def _proceso(self, codigo: int = 0):
        proceso = ProcesoFalso(codigo=codigo)
        with patch.object(ingesta.subprocess, "Popen", return_value=proceso):
            trabajo = ingesta.trabajos.lanzar_proceso(
                "f1_25_republicar", "de prueba", ["guion", "falso"])
        return trabajo, proceso

    # ---- el caso reportado ----

    def test_dos_miradas_al_mismo_trabajo_terminado_dan_lo_mismo(self) -> None:
        """«Procesado en 17 s» y, un rato despues, 101,8 s del mismo trabajo."""

        trabajo = ingesta.trabajos.lanzar_funcion(
            "openf1_importar", "rapida", lambda: {"ok": True})
        primera = _esperar_trabajo(trabajo.identificador)["duracion_s"]
        time.sleep(0.25)
        segunda = ingesta.trabajos.obtener(trabajo.identificador).a_dict()["duracion_s"]
        self.assertEqual(
            primera, segunda,
            "la duracion de un trabajo terminado cambio entre dos miradas: "
            "%s y despues %s. No esta midiendo cuanto duro, sino cuanto hace "
            "que empezo." % (primera, segunda))

    def test_un_trabajo_en_curso_si_sigue_contando(self) -> None:
        """Congelar al terminar no puede congelar tambien lo que esta corriendo."""

        soltar = threading.Event()
        self.addCleanup(soltar.set)
        trabajo = ingesta.trabajos.lanzar_funcion(
            "openf1_importar", "lenta", lambda: soltar.wait(5) or {"ok": True})
        primera = trabajo.a_dict()["duracion_s"]
        time.sleep(0.25)
        segunda = trabajo.a_dict()["duracion_s"]
        self.assertGreater(
            segunda, primera,
            "un trabajo en curso dejo de avanzar: %s y despues %s" % (primera, segunda))
        soltar.set()
        _esperar_trabajo(trabajo.identificador)

    def test_la_duracion_congelada_se_parece_a_lo_que_duro(self) -> None:
        soltar = threading.Event()
        trabajo = ingesta.trabajos.lanzar_funcion(
            "openf1_importar", "medio segundo",
            lambda: soltar.wait(0.4) or {"ok": True})
        cuerpo = _esperar_trabajo(trabajo.identificador)
        self.assertGreaterEqual(cuerpo["duracion_s"], 0.3)
        self.assertLess(cuerpo["duracion_s"], 3.0,
                        "la duracion congelada no se parece a lo que tardo: %s"
                        % cuerpo["duracion_s"])

    # ---- los cinco finales, no solo el feliz ----

    def test_un_proceso_que_termina_congela(self) -> None:
        trabajo, proceso = self._proceso(codigo=0)
        proceso.send_signal(15)
        primera = _esperar_trabajo(trabajo.identificador)["duracion_s"]
        time.sleep(0.2)
        self.assertEqual(primera, trabajo.a_dict()["duracion_s"])

    def test_un_proceso_que_falla_congela(self) -> None:
        trabajo, proceso = self._proceso(codigo=1)
        proceso.send_signal(15)
        primera = _esperar_trabajo(trabajo.identificador)["duracion_s"]
        time.sleep(0.2)
        self.assertEqual(primera, trabajo.a_dict()["duracion_s"])

    def test_una_funcion_que_revienta_congela(self) -> None:
        def _explotar():
            raise RuntimeError("a proposito")

        trabajo = ingesta.trabajos.lanzar_funcion("openf1_importar", "rota", _explotar)
        cuerpo = _esperar_trabajo(trabajo.identificador)
        self.assertEqual(cuerpo["estado"], "fallido")
        primera = cuerpo["duracion_s"]
        time.sleep(0.2)
        self.assertEqual(primera, trabajo.a_dict()["duracion_s"])

    def test_un_trabajo_detenido_congela(self) -> None:
        trabajo, proceso = self._proceso()
        ingesta.trabajos.detener_proceso(trabajo, espera_s=2)
        primera = trabajo.a_dict()["duracion_s"]
        time.sleep(0.2)
        self.assertEqual(primera, trabajo.a_dict()["duracion_s"],
                         "un trabajo detenido siguio durando")

    def test_un_proceso_que_no_arranca_congela(self) -> None:
        with patch.object(ingesta.subprocess, "Popen",
                          side_effect=OSError("no hay tal guion")):
            trabajo = ingesta.trabajos.lanzar_proceso(
                "f1_25_republicar", "que no arranca", ["no", "existe"])
        self.assertEqual(trabajo.estado, "fallido")
        primera = trabajo.a_dict()["duracion_s"]
        time.sleep(0.2)
        self.assertEqual(primera, trabajo.a_dict()["duracion_s"])

    # ---- la guarda que cuida el sexto sitio ----

    def test_el_final_se_marca_en_un_solo_lugar(self) -> None:
        """Estructural: si vuelve la asignacion suelta, esta prueba falla.

        No comprueba comportamiento sino **forma**, y es a proposito: el defecto
        que viene no es que `marcar_fin` este mal, es que alguien agregue un
        sexto final y no la llame. Eso no lo atrapa ninguna prueba de conducta,
        porque el trabajo que ese sexto final cierre todavia no existe.
        """

        lineas = (RAIZ / "backend" / "ingesta.py").read_text(
            encoding="utf-8").splitlines()

        # El cuerpo de `marcar_fin`: desde su `def` hasta el `def` siguiente al
        # mismo nivel. Ahi adentro la asignacion es la correcta; afuera, no.
        arranca = next(i for i, l in enumerate(lineas)
                       if l.strip().startswith("def marcar_fin("))
        sangria = len(lineas[arranca]) - len(lineas[arranca].lstrip())
        termina = next((i for i in range(arranca + 1, len(lineas))
                        if lineas[i].strip().startswith("def ")
                        and len(lineas[i]) - len(lineas[i].lstrip()) <= sangria),
                       len(lineas))

        sueltas = ["%d: %s" % (i + 1, lineas[i].strip())
                   for i, l in enumerate(lineas)
                   if re.search(r"\bfin_utc\s*=(?!=)", l)
                   and not (arranca <= i < termina)]
        self.assertEqual(
            sueltas, [],
            "hay finales marcados a mano en vez de por `marcar_fin()`:\n  %s\n"
            "Cada uno es un sitio donde alguien puede olvidarse de congelar la "
            "duracion, y la cifra vuelve a crecer sola." % "\n  ".join(sueltas))

        # Y que la guarda siga sirviendo de algo: si `marcar_fin` dejara de
        # escribirlo, arriba no habria nada que encontrar y esto pasaria vacio.
        adentro = [l for l in lineas[arranca:termina]
                   if re.search(r"\bfin_utc\s*=(?!=)", l)]
        self.assertTrue(
            adentro,
            "`marcar_fin()` ya no escribe `fin_utc`: la prueba de arriba pasa "
            "sin comprobar nada")


if __name__ == "__main__":
    unittest.main()
