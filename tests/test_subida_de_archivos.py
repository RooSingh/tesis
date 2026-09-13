# -*- coding: utf-8 -*-
"""Un archivo que sube se clasifica y se verifica **antes** de aceptarse.

EL PROBLEMA QUE ESTO RESUELVE. Los botones de importar del tablero no suben
nada: piden un identificador y procesan lo que ya esta en el disco del servidor.
De modo que para incorporar una sesion hay que copiar el archivo a mano a la
maquina y recien despues apretar el boton, y el boton dice «importar» mientras
hace «procesar lo que ya trajiste».

LAS DOS REGLAS QUE ESTE MODULO SOSTIENE, y son las que distinguen una subida de
un `scp`:

1. **Se decide que es antes de guardarlo donde va.** Un archivo que no se
   reconoce no llega a `datasets/`: se rechaza con el motivo, en el area de
   paso. Guardarlo primero y mirarlo despues deja basura con nombre de dato.
2. **Lo que llega se compara contra lo que el propio archivo declara.** Las
   capturas de este proyecto traen un `.meta.json` con `bytes` y `sha256`. Una
   subida truncada tiene exactamente el aspecto de una subida completa hasta que
   alguien compara, y comparar es gratis porque la huella ya viaja.

POR QUE SE CLASIFICA POR CONTENIDO Y NO POR NOMBRE. El nombre lo elige quien
sube. `carrera.canraw` puede ser cualquier cosa, y aceptar por extension es
aceptar la palabra de quien manda el archivo. Los formatos de este proyecto
empiezan con un numero magico ---`CANRAWCP` y `F1RAWCAP`--- y eso si es del
archivo.
"""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from backend import subida  # noqa: E402


class QueSeAceptaYSeDeclaraTests(unittest.TestCase):

    def test_los_formatos_se_declaran_antes_de_pedir_el_archivo(self) -> None:
        """La pantalla tiene que poder decir que acepta sin intentarlo."""

        d = subida.formatos()
        self.assertTrue(d["formatos"], "no declara ningun formato")
        for f in d["formatos"]:
            for clave in ("clase", "fuente", "extension", "que_es", "como_se_obtiene"):
                self.assertIn(clave, f, "al formato %r le falta %r" % (f.get("clase"), clave))
            self.assertTrue(f["que_es"].strip())

    def test_estan_las_tres_fuentes_del_trabajo(self) -> None:
        clases = {f["clase"] for f in subida.formatos()["formatos"]}
        self.assertIn("can_crudo", clases)
        self.assertIn("f1_25_crudo", clases)
        self.assertIn("paquete_openf1", clases)


class SeClasificaPorContenidoYNoPorNombreTests(unittest.TestCase):

    def test_reconoce_una_captura_del_bus(self) -> None:
        self.assertEqual(
            subida.clasificar("lo_que_sea.canraw", b"CANRAWCP\x01\x00\x00\x00"),
            "can_crudo")

    def test_reconoce_una_captura_del_simulador(self) -> None:
        self.assertEqual(
            subida.clasificar("x.f1raw", b"F1RAWCAP\x01\x00\x00\x00"), "f1_25_crudo")

    def test_reconoce_un_paquete_comprimido(self) -> None:
        self.assertEqual(subida.clasificar("9939.zip", b"PK\x03\x04rest"),
                         "paquete_openf1")

    def test_el_nombre_no_alcanza_para_que_algo_sea_lo_que_dice(self) -> None:
        """La extension la elige quien sube; el numero magico es del archivo."""

        self.assertIsNone(subida.clasificar("carrera.canraw", b"no soy una captura"))
        self.assertIsNone(subida.clasificar("paquete.zip", b"tampoco"))

    def test_un_contenido_valido_con_la_extension_cambiada_se_reconoce_igual(self) -> None:
        self.assertEqual(subida.clasificar("sinextension", b"CANRAWCP\x01\x00\x00\x00"),
                         "can_crudo")

    def test_un_archivo_vacio_no_es_nada(self) -> None:
        self.assertIsNone(subida.clasificar("x.canraw", b""))


class LoQueLlegaSeComparaConLoQueDeclaraTests(unittest.TestCase):
    """Una subida truncada se ve igual que una completa hasta que se compara."""

    def _con_meta(self, carpeta: Path, cuerpo: bytes, declara: dict) -> Path:
        ruta = carpeta / "x.canraw"
        ruta.write_bytes(cuerpo)
        (carpeta / "x.canraw.meta.json").write_text(json.dumps(declara))
        return ruta

    def test_una_subida_completa_pasa(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            c = Path(t)
            cuerpo = b"CANRAWCP" + b"\x00" * 120
            ruta = self._con_meta(c, cuerpo, {
                "bytes": len(cuerpo),
                "sha256": hashlib.sha256(cuerpo).hexdigest()})
            ok, motivo = subida.verificar(ruta)
            self.assertTrue(ok, motivo)

    def test_una_subida_truncada_se_rechaza_y_dice_cuanto_falta(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            c = Path(t)
            entero = b"CANRAWCP" + b"\x00" * 120
            ruta = self._con_meta(c, entero[:60], {
                "bytes": len(entero),
                "sha256": hashlib.sha256(entero).hexdigest()})
            ok, motivo = subida.verificar(ruta)
            self.assertFalse(ok)
            self.assertIn("60", motivo)
            self.assertIn("128", motivo)

    def test_un_archivo_cambiado_del_mismo_largo_tambien_se_rechaza(self) -> None:
        """Por eso se compara la huella y no solo el tamano."""

        import tempfile
        with tempfile.TemporaryDirectory() as t:
            c = Path(t)
            entero = b"CANRAWCP" + b"\x00" * 120
            otro = b"CANRAWCP" + b"\x01" * 120
            ruta = self._con_meta(c, otro, {
                "bytes": len(entero),
                "sha256": hashlib.sha256(entero).hexdigest()})
            ok, motivo = subida.verificar(ruta)
            self.assertFalse(ok)
            self.assertIn("huella", motivo.lower())

    def test_sin_metadatos_no_se_puede_verificar_y_se_dice(self) -> None:
        """No verificable no es lo mismo que verificado."""

        import tempfile
        with tempfile.TemporaryDirectory() as t:
            ruta = Path(t) / "x.canraw"
            ruta.write_bytes(b"CANRAWCP" + b"\x00" * 8)
            ok, motivo = subida.verificar(ruta)
            self.assertTrue(ok, "sin metadatos no hay nada que contradiga")
            self.assertIn("no declara", motivo)


class DondeCaeCadaCosaEstaDeclaradoTests(unittest.TestCase):

    def test_cada_clase_tiene_un_destino_y_esta_bajo_datasets(self) -> None:
        for clase in ("can_crudo", "f1_25_crudo", "paquete_openf1"):
            destino = subida.destino_de(clase, "ejemplo.bin")
            self.assertIn("datasets", str(destino),
                          "%s cae fuera de datasets/: %s" % (clase, destino))

    def test_un_nombre_con_rutas_no_escapa_del_destino(self) -> None:
        """El nombre lo elige quien sube: no puede elegir donde escribir."""

        for malicioso in ("../../etc/passwd", "/etc/passwd", "a/b/c.canraw",
                          "..\\..\\windows", "x/../../../y.canraw"):
            destino = subida.destino_de("can_crudo", malicioso)
            raiz = subida.RAIZ_DE_DATOS.resolve()
            self.assertTrue(str(destino.resolve()).startswith(str(raiz)),
                            "%r escapo a %s" % (malicioso, destino))

    def test_una_clase_desconocida_no_tiene_destino(self) -> None:
        with self.assertRaises(ValueError):
            subida.destino_de("lo_que_sea", "x.bin")


if __name__ == "__main__":
    unittest.main()


class LosMetadatosNoSonUnaCapturaTests(unittest.TestCase):
    """Un `.meta.json` no tiene numero magico: se acepta por su compania.

    No se clasifican por contenido porque son JSON y cualquier JSON lo pareceria.
    La regla es otra y es mas fuerte: **solo se aceptan si la captura que
    describen ya esta subida**. Un acompanante suelto no describe nada.
    """

    def test_se_reconoce_como_acompanante(self) -> None:
        self.assertTrue(subida.es_acompanante("x.canraw.meta.json"))
        self.assertFalse(subida.es_acompanante("x.canraw"))

    def test_se_le_saca_la_captura_que_describe(self) -> None:
        self.assertEqual(subida.raiz_del_acompanante("x.canraw.meta.json"), "x.canraw")
        self.assertEqual(
            subida.raiz_del_acompanante("20260912_1854_shanghai.f1raw.meta.json"),
            "20260912_1854_shanghai.f1raw")

    def test_uno_suelto_no_tiene_donde_ir(self) -> None:
        self.assertIsNone(
            subida.donde_espera_su_captura("no_subi_nada.canraw.meta.json"))

    def test_tampoco_escapa_del_destino(self) -> None:
        self.assertIsNone(
            subida.donde_espera_su_captura("../../x.canraw.meta.json"))
