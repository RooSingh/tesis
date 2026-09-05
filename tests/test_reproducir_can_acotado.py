# -*- coding: utf-8 -*-
"""El borrado del reproductor de CAN, y por que tiene que ser acotado.

El defecto que estas pruebas cierran
------------------------------------
`--rehacer` borraba **por tipo de fuente**, es decir la fuente entera, y despues
cargaba **solo los segmentos que se le hubieran pedido**.

Con una lista acotada eso destruia lo que no iba a reponer: pedir un segmento y
rehacer se llevaba las **559.016 filas de los diez segmentos cargados** y reponia
unas 55.000. El comentario del codigo decia que lo borrado se reconstruye del
registro crudo, y es cierto en principio, pero **no por esa invocacion**.

La regla que sale de ahi: **rehacer significa rehacer *esto*, no vaciar la
fuente.** El borrado se acota por identidad de corrida, calculada de los mismos
segmentos que se van a reponer, de modo que **no puede alcanzar a un segmento que
no se este recargando**.

Estas pruebas no tocan la base: verifican la forma del borrado y las propiedades
de la identidad que lo hace posible.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

import reproducir_can as rc  # noqa: E402

CAPTURAS = RAIZ / "datasets" / "can" / "capturas"


def _metadatos(nombre: str) -> dict | None:
    ruta = CAPTURAS / f"TOYOTA_RAV4_TSS2_{nombre}.canraw.meta.json"
    if not ruta.exists():
        return None
    return json.loads(ruta.read_text(encoding="utf-8"))


class ElBorradoEsAcotado(unittest.TestCase):
    """Lo que se borra tiene que ser lo que se va a reponer, y nada mas."""

    def test_no_borra_por_tipo_de_fuente(self):
        """Borrar por tipo alcanza a segmentos que la corrida no repone."""

        fuente = Path(rc.__file__).read_text(encoding="utf-8")
        i = fuente.index("if args.rehacer:")
        cuerpo = fuente[i:i + 1800]
        self.assertNotIn("delete from telemetry_messages where source_type",
                         cuerpo)

    def test_borra_por_identidad_de_corrida(self):
        fuente = Path(rc.__file__).read_text(encoding="utf-8")
        i = fuente.index("if args.rehacer:")
        cuerpo = fuente[i:i + 1800]
        self.assertIn("replay_run_id = any(%s)", cuerpo)

    def test_las_identidades_salen_de_los_segmentos_que_se_reponen(self):
        """La misma lista de rutas gobierna el borrado y la carga.

        Si salieran de listas distintas volveria a ser posible borrar de mas.
        """

        fuente = Path(rc.__file__).read_text(encoding="utf-8")
        i = fuente.index("if args.rehacer:")
        cuerpo = fuente[i:i + 1800]
        self.assertIn("for r in rutas", cuerpo)


class LaIdentidadDistingueSegmentos(unittest.TestCase):
    """Sin eso, acotar el borrado no serviria de nada."""

    def setUp(self):
        self.uno = _metadatos("sample_01")
        self.otro = _metadatos("sample_04")
        if self.uno is None or self.otro is None:
            self.skipTest("no estan extraidos los segmentos de referencia")

    def test_dos_segmentos_tienen_identidades_distintas(self):
        self.assertNotEqual(rc.identidad_de_corrida(self.uno),
                            rc.identidad_de_corrida(self.otro))

    def test_la_identidad_es_estable_para_el_mismo_segmento(self):
        self.assertEqual(rc.identidad_de_corrida(self.uno),
                         rc.identidad_de_corrida(self.uno))

    def test_la_identidad_incluye_la_huella_de_la_captura(self):
        """Cambiar de archivo tiene que cambiar la identidad."""

        self.assertIn(self.uno["sha256"][:16], rc.identidad_de_corrida(self.uno))

    def test_la_identidad_cambia_si_cambia_el_adaptador(self):
        """Ya ocurrio: el adaptador paso a emitir la mitad de los mensajes y la
        numeracion cambio por completo sin que la huella lo notara."""

        original = rc.can_rav4.VERSION_ADAPTADOR
        antes = rc.identidad_de_corrida(self.uno)
        try:
            rc.can_rav4.VERSION_ADAPTADOR = original + "-distinta"
            despues = rc.identidad_de_corrida(self.uno)
        finally:
            rc.can_rav4.VERSION_ADAPTADOR = original
        self.assertNotEqual(antes, despues)


class LaEmisionPorIntermediarioSeDejaUbicar(unittest.TestCase):
    """Los tres agregados que la medicion de latencia exigio.

    El camino por intermediario no ponia identidad de reinyeccion ni sello de
    publicacion. Sin lo primero, una segunda corrida duplicaba filas en silencio
    ---el indice unico es parcial y no aplica sin esas dos columnas--- y ninguna
    medicion podia ubicar despues las filas de una corrida. Sin lo segundo,
    cronometrar desde el arranque le suma a cada mensaje el tiempo que tardo en
    llegarle su turno de emision, que es una espera distinta.
    """

    def test_acepta_identidad_de_corrida(self):
        import inspect
        firma = inspect.signature(rc.emitir_por_broker)
        self.assertIn("run_id", firma.parameters)

    def test_acepta_multiplicador_de_velocidad(self):
        import inspect
        firma = inspect.signature(rc.emitir_por_broker)
        self.assertIn("velocidad", firma.parameters)
        self.assertEqual(firma.parameters["velocidad"].default, 1.0)

    def test_sella_el_instante_de_publicacion_de_cada_mensaje(self):
        fuente = Path(rc.__file__).read_text(encoding="utf-8")
        i = fuente.index("def emitir_por_broker")
        cuerpo = fuente[i:i + 3500]
        self.assertIn("published_at_utc", cuerpo)

    def test_el_calendario_se_calcula_contra_el_arranque(self):
        """Sumar esperas relativas acumula el error y corre el reloj."""

        fuente = Path(rc.__file__).read_text(encoding="utf-8")
        i = fuente.index("def emitir_por_broker")
        cuerpo = fuente[i:i + 3500]
        self.assertIn("time.perf_counter() - arranque", cuerpo)

    def test_usa_la_version_vigente_de_la_interfaz_del_cliente(self):
        """La anterior ya emitia aviso de deprecacion."""

        fuente = Path(rc.__file__).read_text(encoding="utf-8")
        i = fuente.index("def emitir_por_broker")
        cuerpo = fuente[i:i + 3500]
        self.assertIn("CallbackAPIVersion", cuerpo)


if __name__ == "__main__":
    unittest.main()
