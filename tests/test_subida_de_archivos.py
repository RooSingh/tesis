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


class ElServidorDiceQueHayQuePedirDespuesTests(unittest.TestCase):
    """Quien sube no tiene que reconstruir lo que el servidor ya sabe.

    EL ACUERDO QUE ESTO EVITA. Sin esto, el navegador tiene que partir
    `TOYOTA_RAV4_TSS2_sample_01.canraw` por un prefijo que conoce de memoria para
    armar `{segmentos: ["sample_01"], plataforma: "TOYOTA_RAV4_TSS2"}`. Es un
    acuerdo tacito entre dos lados, escrito en uno solo, que se rompe el dia que
    una plataforma lleve un guion bajo de mas.

    Y NO HACE FALTA ADIVINAR: el propio `.meta.json` **declara** `plataforma` y
    `segmento`. La derivacion sale del archivo, no del nombre.
    """

    def test_una_captura_del_bus_dice_como_se_carga(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            ruta = Path(t) / "TOYOTA_RAV4_TSS2_sample_01.canraw"
            ruta.write_bytes(b"CANRAWCP" + b"\x00" * 8)
            ruta.with_name(ruta.name + ".meta.json").write_text(json.dumps(
                {"plataforma": "TOYOTA_RAV4_TSS2", "segmento": "sample_01"}))
            p = subida.como_se_procesa("can_crudo", ruta)
            self.assertIsNotNone(p, "no dice como procesarla")
            self.assertEqual(p["ruta"], "/can/importar")
            self.assertEqual(p["metodo"], "POST")
            self.assertEqual(p["cuerpo"]["segmentos"], ["sample_01"])
            self.assertEqual(p["cuerpo"]["plataforma"], "TOYOTA_RAV4_TSS2")
            self.assertEqual(p["cuerpo"]["etapa"], "cargar")

    def test_lo_saca_del_metadato_y_no_de_partir_el_nombre(self) -> None:
        """Un nombre que no sigue la convencion se resuelve igual."""

        import tempfile
        with tempfile.TemporaryDirectory() as t:
            ruta = Path(t) / "cualquier_cosa.canraw"
            ruta.write_bytes(b"CANRAWCP" + b"\x00" * 8)
            ruta.with_name(ruta.name + ".meta.json").write_text(json.dumps(
                {"plataforma": "OTRA_PLATAFORMA", "segmento": "tramo_9"}))
            p = subida.como_se_procesa("can_crudo", ruta)
            self.assertEqual(p["cuerpo"]["segmentos"], ["tramo_9"])
            self.assertEqual(p["cuerpo"]["plataforma"], "OTRA_PLATAFORMA")

    def test_sin_metadato_no_se_inventa_como_procesarla(self) -> None:
        """Es la misma regla que el resto: no verificable no es verificado."""

        import tempfile
        with tempfile.TemporaryDirectory() as t:
            ruta = Path(t) / "TOYOTA_RAV4_TSS2_sample_01.canraw"
            ruta.write_bytes(b"CANRAWCP" + b"\x00" * 8)
            p = subida.como_se_procesa("can_crudo", ruta)
            self.assertIsNone(p["ruta"] if p else None,
                              "adivino como procesar sin que el archivo lo declare")
            self.assertIn("declara", p["motivo"])

    def test_una_captura_del_simulador_dice_su_ruta(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            ruta = Path(t) / "20260912_1854_shanghai_carrera.f1raw"
            ruta.write_bytes(b"F1RAWCAP" + b"\x00" * 8)
            p = subida.como_se_procesa("f1_25_crudo", ruta)
            self.assertEqual(p["ruta"], "/f1_25/republicar")
            self.assertEqual(p["cuerpo"]["captura"], ruta.name)

    def test_un_paquete_comprimido_todavia_no_dice_nada(self) -> None:
        """Hasta descomprimirlo no se sabe que sesion es: se dice, no se inventa."""

        import tempfile
        with tempfile.TemporaryDirectory() as t:
            ruta = Path(t) / "9939.zip"
            ruta.write_bytes(b"PK\x03\x04")
            p = subida.como_se_procesa("paquete_openf1", ruta)
            self.assertIsNone(p["ruta"])
            self.assertTrue(p["motivo"].strip())


class UnPaqueteComprimidoSeAbreYSeMiraTests(unittest.TestCase):
    """Descomprimir es aceptar contenido ajeno: hay que mirarlo antes.

    DOS COSAS QUE UN `.zip` PUEDE HACER Y NO SE LE PERMITE:

    * **escribir fuera de su destino**, con entradas como `../../etc/passwd`.
      Es viejo y conocido, y sigue funcionando en todo codigo que confie en el
      nombre de la entrada.
    * **no ser lo que dice**: un comprimido sin `session.json` no es un paquete
      de sesion, y darse cuenta despues de haberlo desparramado en `datasets/`
      deja un directorio con nombre de sesion y sin sesion adentro.
    """

    def _zip(self, carpeta: Path, entradas: dict) -> Path:
        import zipfile
        ruta = carpeta / "paquete.zip"
        with zipfile.ZipFile(ruta, "w") as z:
            for nombre, contenido in entradas.items():
                z.writestr(nombre, contenido)
        return ruta

    def test_un_paquete_valido_se_abre_donde_la_ruta_de_importacion_lo_busca(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            z = self._zip(Path(t), {
                "999999/session.json": json.dumps({"session_key": 999999, "year": 1999}),
                "999999/drivers.json": "[]"})
            ok, detalle = subida.abrir_paquete(z)
            destino = Path(detalle.get("destino", ""))
            try:
                self.assertTrue(ok, detalle.get("motivo"))
                self.assertEqual(detalle["session_key"], 999999)
                self.assertTrue((destino / "session.json").is_file())
                self.assertIn("1999", str(destino))
                self.assertIn("999999", str(destino))
            finally:
                # UNA PRUEBA QUE ESCRIBE EN EL ARBOL LO DEJA COMO LO ENCONTRO.
                # Sin esto, la corrida siguiente encuentra el paquete puesto y
                # falla con «ya hay un paquete», que es la conducta correcta
                # contestando a un estado que dejo la prueba anterior. Le paso
                # a la otra sesion en el arbol compartido.
                import shutil as _sh
                if destino.parent.name == "1999":
                    _sh.rmtree(destino.parent, ignore_errors=True)

    def test_sin_session_json_no_es_un_paquete_y_no_se_desparrama(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            z = self._zip(Path(t), {"999999/drivers.json": "[]"})
            ok, detalle = subida.abrir_paquete(z)
            self.assertFalse(ok)
            self.assertIn("session.json", detalle["motivo"])

    def test_una_session_key_que_no_es_entera_se_rechaza(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            z = self._zip(Path(t), {
                "x/session.json": json.dumps({"session_key": "novecientos"})})
            ok, detalle = subida.abrir_paquete(z)
            self.assertFalse(ok)
            self.assertIn("entero", detalle["motivo"])

    def test_una_entrada_que_intenta_salirse_se_rechaza_entera(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            z = self._zip(Path(t), {
                "999999/session.json": json.dumps({"session_key": 999999, "year": 1999}),
                "../../escapado.json": "{}"})
            ok, detalle = subida.abrir_paquete(z)
            self.assertFalse(ok)
            self.assertIn("fuera", detalle["motivo"].lower())

    def test_lo_que_no_es_un_comprimido_se_dice_y_no_se_abre(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            ruta = Path(t) / "mentira.zip"
            ruta.write_bytes(b"no soy un zip")
            ok, detalle = subida.abrir_paquete(ruta)
            self.assertFalse(ok)
            self.assertTrue(detalle["motivo"].strip())


class UnPaqueteNoPisaOtroTests(unittest.TestCase):
    """El destino sale de contenido subido: no puede ser destructivo.

    EL DEFECTO QUE ESTO CUIDA, Y OCURRIO. `abrir_paquete` hacia `rmtree` sobre el
    destino para hacerle lugar al comprimido. El destino sale de la `session_key`
    que **declara el propio archivo**, de modo que subir un comprimido que dijera
    `9947` bastaba para llevarse los 273 MB de Silverstone.

    El 2026-09-12 se llevo los 60 MB del paquete de Spa: una prueba de este mismo
    archivo uso la clave `9939`, que era real. El contexto ya importado
    sobrevivio en la base; los JSON crudos hubo que volver a descargarlos.

    De ahi la regla: **una subida agrega, no reemplaza.** Reemplazar es una
    decision de quien opera, y se toma borrando a proposito.
    """

    def test_no_se_pisa_un_paquete_que_ya_esta(self) -> None:
        import tempfile, zipfile
        with tempfile.TemporaryDirectory() as t:
            destino = subida.PAQUETES_OPENF1 / "1998" / "999998"
            destino.mkdir(parents=True, exist_ok=True)
            testigo = destino / "no_me_borres.json"
            testigo.write_text('{"soy": "el paquete que ya estaba"}')
            try:
                z = Path(t) / "p.zip"
                with zipfile.ZipFile(z, "w") as f:
                    f.writestr("999998/session.json",
                               json.dumps({"session_key": 999998, "year": 1998}))
                ok, detalle = subida.abrir_paquete(z)
                self.assertFalse(ok, "piso un paquete que ya estaba")
                self.assertIn("ya hay un paquete", detalle["motivo"])
                self.assertTrue(testigo.is_file(), "se llevo el archivo que estaba")
                self.assertIn("el paquete que ya estaba", testigo.read_text())
            finally:
                import shutil as _sh
                _sh.rmtree(destino.parent, ignore_errors=True)

    def test_el_modulo_no_vuelve_a_tener_un_borrado_del_destino(self) -> None:
        """Guarda estructural: `rmtree` sobre el destino no puede reaparecer."""

        fuente = (Path(__file__).resolve().parents[1] / "backend" / "subida.py"
                  ).read_text(encoding="utf-8")
        sin_comentarios = "\n".join(
            r.split("#", 1)[0] for r in fuente.splitlines())
        self.assertNotIn("shutil.rmtree(destino)", sin_comentarios,
                         "volvio el borrado del destino, que ya se llevo un "
                         "paquete real una vez")


class UnaCapturaDesmentidaNoSeQuedaConNombreDeDatoTests(unittest.TestCase):
    """Si el metadato desmiente a la captura, la captura sale de `datasets/`.

    EL DEFECTO. El acompanante llega **despues** de la captura, por obligacion:
    sin la captura no tiene donde ir. De modo que la captura ya esta en
    `datasets/` cuando recien se la puede comparar contra lo que declara. Si la
    comparacion falla, lo que queda en disco es **un archivo truncado con nombre
    de dato**, que es exactamente lo que el area de paso existe para evitar.

    Y no es un caso raro: una subida cortada a la mitad ---una red domestica y un
    paquete de doscientos megabytes--- produce justo eso.

    LA REGLA. Lo que no paso la verificacion **no se borra y no se queda**: vuelve
    al area de paso, con su acompanante, y la respuesta dice donde esta. No se
    borra porque los bytes que llegaron sirven para reintentar; no se queda
    porque en `datasets/` solo vive lo que se puede usar.
    """

    def _par(self, carpeta: Path, cuerpo: bytes, declara: dict) -> Path:
        ruta = carpeta / "x.canraw"
        ruta.write_bytes(cuerpo)
        (carpeta / "x.canraw.meta.json").write_text(json.dumps(declara))
        return ruta

    def test_lo_desmentido_sale_de_datasets_y_conserva_los_bytes(self) -> None:
        import hashlib as _h, tempfile
        with tempfile.TemporaryDirectory() as t:
            destino = Path(t) / "capturas"
            destino.mkdir()
            entero = b"CANRAWCP" + b"\x00" * 500
            ruta = self._par(destino, entero[:120], {
                "bytes": len(entero), "sha256": _h.sha256(entero).hexdigest()})
            movido = subida.apartar_lo_desmentido(ruta)
            self.assertIsNotNone(movido, "no lo aparto")
            self.assertFalse(ruta.is_file(), "la captura desmentida se quedo")
            self.assertFalse(ruta.with_name(ruta.name + ".meta.json").is_file(),
                             "el acompanante se quedo solo, describiendo a nadie")
            self.assertTrue(Path(movido).is_file(), "se perdieron los bytes")
            self.assertEqual(Path(movido).stat().st_size, 120,
                             "no conservo lo que habia llegado")
            import shutil as _sh
            _sh.rmtree(Path(movido).parent, ignore_errors=True)

    def test_lo_verificado_no_se_toca(self) -> None:
        import hashlib as _h, tempfile
        with tempfile.TemporaryDirectory() as t:
            destino = Path(t) / "capturas"
            destino.mkdir()
            entero = b"CANRAWCP" + b"\x00" * 500
            ruta = self._par(destino, entero, {
                "bytes": len(entero), "sha256": _h.sha256(entero).hexdigest()})
            self.assertIsNone(subida.apartar_lo_desmentido(ruta))
            self.assertTrue(ruta.is_file(), "aparto una captura que estaba bien")

    def test_lo_que_no_declara_nada_tampoco_se_toca(self) -> None:
        """No verificable no es desmentido."""

        import tempfile
        with tempfile.TemporaryDirectory() as t:
            destino = Path(t) / "capturas"
            destino.mkdir()
            ruta = destino / "x.canraw"
            ruta.write_bytes(b"CANRAWCP" + b"\x00" * 8)
            self.assertIsNone(subida.apartar_lo_desmentido(ruta))
            self.assertTrue(ruta.is_file())
