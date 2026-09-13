# -*- coding: utf-8 -*-
"""Un motivo que vive dentro del contenedor es un motivo que nadie lee.

EL DEFECTO, REPORTADO CON EVIDENCIA DE PANTALLA el 2026-09-13. El usuario
reinyecto una captura, el guion se nego ---bien--- a duplicarla, y el tablero
mostro esto:

    El procesamiento termino como «fallido»: El proceso termino con codigo 1.
    Ver /app/logs/tablero_f1_25_republicar_77418cba96ce.log.

Esa ruta esta **adentro del contenedor**. Quien mira el tablero no puede
abrirla, ni desde el navegador ni entrando a la Raspberry: `/app` no existe
fuera de la imagen. Antes de mover la aplicacion a contenedor la ruta al menos
era abrible por quien tuviera la maquina; desde el 2026-09-13 no lo es para
nadie. La migracion no creo el defecto, lo dejo sin salida.

Y EL MOTIVO DE VERDAD ERA BUENO. Estaba en la ultima linea util del registro:

    No se pueden completar reinsertando: lo presente se guardo sin identidad de
    corrida, de modo que no chocaria contra nada y se duplicaria.
    Para rehacerlas hay que borrar primero lo incompleto. Volver a ejecutar con
    --limpiar-parciales.

Eso no es un fallo tecnico: es una **negativa razonada** que ademas dice como
resolverla. El usuario tenia que leer eso, y en vez de eso leyo una ruta.

LO QUE ESTAS PRUEBAS EXIGEN. Que cuando un proceso hijo termina, el desenlace
del registro viaje en la respuesta del trabajo ---no la ruta al registro, el
registro---. Quien dibuje la pantalla tiene entonces algo que mostrar sin
pedirle permiso a nadie ni abrir un archivo que no puede abrir.

LO QUE NO EXIGEN, y es a proposito: que viaje el registro entero. Una captura
de dos horas escribe un archivo que no tiene por que atravesar una respuesta
HTTP. Viaja **el final**, acotado por lineas y por bytes, que es donde un
proceso dice por que se detuvo.
"""

from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from backend import ingesta  # noqa: E402
from tests.test_ingesta import ProcesoFalso, _esperar_trabajo  # noqa: E402

#: El final exacto del registro que el usuario no pudo leer, tomado de
#: `logs/tablero_f1_25_republicar_77418cba96ce.log` en la Raspberry.
FINAL_DE_VERDAD = """\
filas con identidad de esta corrida: 0
No se pueden completar reinsertando: lo presente se guardo sin identidad de \
corrida, de modo que no chocaria contra nada y se duplicaria.

Para rehacerlas hay que borrar primero lo incompleto. Volver a ejecutar con \
--limpiar-parciales.
"""


class ElFinalDelRegistroViaja(unittest.TestCase):

    def setUp(self) -> None:
        ingesta.trabajos.reiniciar()
        self.addCleanup(ingesta.trabajos.reiniciar)
        self._temporal = TemporaryDirectory()
        self.addCleanup(self._temporal.cleanup)
        self.bitacoras = Path(self._temporal.name) / "logs"
        self.bitacoras.mkdir(parents=True)
        parche = patch.object(ingesta, "BITACORAS", self.bitacoras)
        parche.start()
        self.addCleanup(parche.stop)

    def _correr(self, texto: str | bytes, codigo: int = 1) -> dict:
        """Lanza un proceso de mentira que deja `texto` en su registro."""

        proceso = ProcesoFalso(codigo=codigo)
        escrito = threading.Event()

        def _popen(*_a, **kwargs):
            # El registro lo escribe el hijo; aca se imita escribiendo por el
            # mismo descriptor que `lanzar_proceso` le paso.
            salida = kwargs.get("stdout")
            if salida is not None:
                if isinstance(texto, bytes):
                    salida.buffer.write(texto) if hasattr(salida, "buffer") else None
                else:
                    salida.write(texto)
                salida.flush()
            escrito.set()
            return proceso

        with patch.object(ingesta.subprocess, "Popen", side_effect=_popen):
            trabajo = ingesta.trabajos.lanzar_proceso(
                "f1_25_republicar", "reinyeccion de prueba", ["guion", "falso"])
        escrito.wait(5)
        proceso.send_signal(15)          # lo hace terminar con su codigo
        return _esperar_trabajo(trabajo.identificador)

    # ---- lo que el usuario tenia que leer ----

    def test_el_motivo_real_llega_a_la_respuesta(self) -> None:
        """El caso reportado, con su texto exacto."""

        cuerpo = self._correr(FINAL_DE_VERDAD)
        entero = repr(cuerpo)
        self.assertIn(
            "se duplicaria", entero,
            "la negativa razonada no cruzo: la respuesta no dice por que fallo,\n"
            "y quien mira el tablero no puede abrir el archivo que la tiene.\n"
            "Respuesta: %r" % (cuerpo,))

    def test_tambien_llega_como_resolverlo(self) -> None:
        cuerpo = self._correr(FINAL_DE_VERDAD)
        self.assertIn(
            "--limpiar-parciales", repr(cuerpo),
            "el registro decia como resolverlo y esa linea no viajo")

    def test_el_error_deja_de_ser_solo_una_ruta(self) -> None:
        """`error` es lo primero que se muestra: tiene que decir algo."""

        cuerpo = self._correr(FINAL_DE_VERDAD)
        self.assertIsNotNone(cuerpo["error"])
        self.assertNotEqual(
            cuerpo["error"].strip().endswith(".log."), True,
            "el error sigue terminando en una ruta a un archivo: %r" % cuerpo["error"])

    # ---- que no se pase de largo ----

    def test_un_registro_enorme_no_viaja_entero(self) -> None:
        """Una captura de dos horas no tiene por que atravesar una respuesta."""

        enorme = "".join("linea %d de relleno larga y aburrida\n" % i
                         for i in range(50000))
        cuerpo = self._correr(enorme)
        self.assertLess(
            len(repr(cuerpo)), 20000,
            "la respuesta del trabajo se llevo el registro entero: %d bytes"
            % len(repr(cuerpo)))

    def test_del_registro_enorme_llega_el_final_y_no_el_principio(self) -> None:
        lineas = ["principio que no importa\n"]
        lineas += ["relleno %d\n" % i for i in range(5000)]
        lineas.append("ESTE ES EL MOTIVO\n")
        cuerpo = self._correr("".join(lineas))
        self.assertIn("ESTE ES EL MOTIVO", repr(cuerpo),
                      "no llego el final, que es donde un proceso dice por que paro")
        self.assertNotIn("principio que no importa", repr(cuerpo))

    # ---- que no rompa con lo raro ----

    def test_un_registro_vacio_no_rompe(self) -> None:
        cuerpo = self._correr("")
        self.assertEqual(cuerpo["estado"], "fallido")

    def test_un_registro_que_no_existe_no_rompe(self) -> None:
        cuerpo = self._correr(FINAL_DE_VERDAD)
        # Se borra el archivo antes de volver a serializar el trabajo.
        for archivo in self.bitacoras.glob("*.log"):
            archivo.unlink()
        trabajo = ingesta.trabajos.obtener(cuerpo["trabajo"])
        self.assertEqual(trabajo.a_dict()["estado"], "fallido")

    def test_las_lineas_vacias_del_final_no_se_llevan_el_motivo(self) -> None:
        """Un proceso que cierra con saltos de linea sigue teniendo motivo."""

        cuerpo = self._correr("EL MOTIVO\n\n\n\n\n")
        self.assertIn("EL MOTIVO", repr(cuerpo),
                      "los saltos de linea del final desplazaron al motivo")

    def test_un_proceso_que_termina_bien_no_se_marca_fallido(self) -> None:
        cuerpo = self._correr("todo salio bien\n", codigo=0)
        self.assertEqual(cuerpo["estado"], "terminado")
        self.assertIsNone(cuerpo["error"])

    def test_leer_el_registro_no_puede_matar_al_vigia(self) -> None:
        """El docstring promete «no levanta nunca». La promesa se comprueba.

        Lo escribi atrapando `(OSError, ValueError)`, que es lo que se me
        ocurrio que podia fallar al leer un archivo. Es la misma forma del
        defecto que tesis-48 encontro en el `app.js` ---un `catch` que solo
        mira `TypeError` y se come todo lo demas---: la lista de lo previsto
        nunca es la lista de lo que pasa.

        Y aqui la consecuencia es concreta y fea: `_final_del_registro()` la
        llama el hilo que vigila al proceso, **antes** de escribir el estado.
        Si levanta, el hilo muere y el trabajo queda «en curso» para siempre,
        sin proceso detras y sin forma de cerrarlo. Es peor que no leer el
        registro, que era el problema que esta funcion vino a resolver.
        """

        class RotaDeOtraForma(Exception):
            pass

        with patch.object(ingesta.Path, "stat", side_effect=RotaDeOtraForma("boom")):
            devuelto = ingesta._final_del_registro("/lo/que/sea.log")
        self.assertEqual(devuelto, [],
                         "la lectura del registro dejo escapar una excepcion: "
                         "el vigia muere y el trabajo no se cierra nunca")

    def test_un_trabajo_se_cierra_aunque_su_registro_sea_ilegible(self) -> None:
        """La misma promesa, pero mirada desde donde importa."""

        with patch.object(ingesta, "_final_del_registro",
                          side_effect=RuntimeError("ilegible")):
            cuerpo = self._correr(FINAL_DE_VERDAD)
        self.assertIn(cuerpo["estado"], {"fallido", "terminado"},
                      "el trabajo quedo sin cerrar porque fallo leer su registro")

    def test_la_ruta_sigue_estando_para_quien_pueda_abrirla(self) -> None:
        """Esto agrega; no saca. Quien tenga la maquina sigue teniendo el archivo."""

        cuerpo = self._correr(FINAL_DE_VERDAD)
        self.assertTrue(cuerpo["bitacora"].endswith(".log"),
                        "se perdio la ruta al registro: %r" % cuerpo["bitacora"])


if __name__ == "__main__":
    unittest.main()
