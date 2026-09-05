"""Pruebas del formato propio de tramas CAN.

Que protegen
------------
El formato existe para que leer el dato **no dependa de 1,8 GB de openpilot**.
Ese objetivo se cumple solo si el archivo es autosuficiente y si un archivo
danado se rechaza en vez de leerse a medias: una captura que devuelve tramas
plausibles de un archivo truncado es peor que una que falla.

Estas pruebas no usan el conjunto de datos ni la biblioteca de openpilot, que es
en si mismo la comprobacion de que la dependencia quedo contenida en la
extraccion.
"""

from __future__ import annotations

import struct
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backend import can_capture

TRAMAS = [
    (0, 170, 0, bytes.fromhex("4436444f44324410")),
    (10_165_989, 37, 0, bytes.fromhex("0000000000000000")),
    (20_331_978, 550, 2, bytes.fromhex("00002a0000000000")),
    (30_497_967, 956, 0, bytes.fromhex("0000200000000000")),
]


class IdaYVueltaTests(unittest.TestCase):
    """Lo que se escribe es exactamente lo que se lee."""

    def setUp(self):
        self._dir = TemporaryDirectory()
        self.ruta = Path(self._dir.name) / "prueba.canraw"

    def tearDown(self):
        self._dir.cleanup()

    def _escribir(self, tramas=TRAMAS) -> None:
        with can_capture.EscritorCaptura(self.ruta) as escritor:
            for instante, identificador, bus, datos in tramas:
                escritor.escribir(instante, identificador, bus, datos)

    def test_cada_trama_vuelve_identica(self):
        self._escribir()
        leidas = [(t.instante_ns, t.identificador, t.bus, t.datos)
                  for t in can_capture.leer_captura(self.ruta)]
        self.assertEqual(leidas, TRAMAS)

    def test_el_instante_conserva_los_nanosegundos(self):
        """La periodicidad medida del sensor de direccion es 10,165989 ms.

        Guardar el instante en microsegundos perderia los tres ultimos digitos,
        que son justamente los que distinguen una periodicidad medida de una
        redondeada.
        """

        self._escribir()
        segunda = list(can_capture.leer_captura(self.ruta))[1]
        self.assertEqual(segunda.instante_ns, 10_165_989)

    def test_una_captura_vacia_es_legible(self):
        """Un segmento sin tramas CAN no es un archivo roto."""

        self._escribir(tramas=[])
        self.assertEqual(list(can_capture.leer_captura(self.ruta)), [])

    def test_el_escritor_cuenta_lo_que_escribio(self):
        with can_capture.EscritorCaptura(self.ruta) as escritor:
            for t in TRAMAS:
                escritor.escribir(*t)
            self.assertEqual(escritor.tramas, len(TRAMAS))


class RechazosTests(unittest.TestCase):
    """Un archivo que no es una captura se rechaza, no se interpreta."""

    def setUp(self):
        self._dir = TemporaryDirectory()
        self.ruta = Path(self._dir.name) / "prueba.canraw"

    def tearDown(self):
        self._dir.cleanup()

    def test_rechaza_un_archivo_de_otro_tipo(self):
        self.ruta.write_bytes(b"esto no es una captura CAN, para nada")
        with self.assertRaises(can_capture.ErrorCaptura):
            list(can_capture.leer_captura(self.ruta))

    def test_rechaza_un_archivo_mas_corto_que_su_cabecera(self):
        self.ruta.write_bytes(can_capture.MAGIA[:4])
        with self.assertRaises(can_capture.ErrorCaptura):
            list(can_capture.leer_captura(self.ruta))

    def test_rechaza_una_version_de_formato_futura(self):
        """Un lector viejo no debe adivinar un formato que no conoce."""

        self.ruta.write_bytes(
            struct.pack(can_capture.CABECERA_ARCHIVO_FMT, can_capture.MAGIA, 99))
        with self.assertRaises(can_capture.ErrorCaptura) as caso:
            list(can_capture.leer_captura(self.ruta))
        self.assertIn("99", str(caso.exception))

    def test_rechaza_un_registro_truncado(self):
        """Media cabecera de registro no se completa con ceros."""

        with can_capture.EscritorCaptura(self.ruta) as escritor:
            escritor.escribir(*TRAMAS[0])
        with self.ruta.open("ab") as archivo:
            archivo.write(b"\x00\x00\x00")
        with self.assertRaises(can_capture.ErrorCaptura):
            list(can_capture.leer_captura(self.ruta))

    def test_rechaza_datos_truncados(self):
        """El caso peligroso: la cabecera anuncia mas bytes de los que hay.

        Sin esta comprobacion, la ultima trama volveria con datos incompletos y
        con apariencia de valida.
        """

        with can_capture.EscritorCaptura(self.ruta) as escritor:
            escritor.escribir(*TRAMAS[0])
        crudo = self.ruta.read_bytes()
        self.ruta.write_bytes(crudo[:-3])
        with self.assertRaises(can_capture.ErrorCaptura):
            list(can_capture.leer_captura(self.ruta))

    def test_rechaza_una_trama_mas_larga_que_el_formato(self):
        """La longitud va en un byte: 256 bytes no entran y hay que decirlo."""

        with can_capture.EscritorCaptura(self.ruta) as escritor:
            with self.assertRaises(can_capture.ErrorCaptura):
                escritor.escribir(0, 170, 0, bytes(256))

    def test_no_se_puede_escribir_con_el_escritor_cerrado(self):
        escritor = can_capture.EscritorCaptura(self.ruta)
        with self.assertRaises(can_capture.ErrorCaptura):
            escritor.escribir(*TRAMAS[0])


class ProcedenciaTests(unittest.TestCase):
    """La captura viaja con su hash, para que pueda citarse sin ambiguedad."""

    def setUp(self):
        self._dir = TemporaryDirectory()
        self.ruta = Path(self._dir.name) / "prueba.canraw"
        with can_capture.EscritorCaptura(self.ruta) as escritor:
            for t in TRAMAS:
                escritor.escribir(*t)

    def tearDown(self):
        self._dir.cleanup()

    def test_los_metadatos_acompanan_al_archivo(self):
        destino = can_capture.escribir_metadatos(self.ruta, {"plataforma": "X"})
        self.assertEqual(destino.parent, self.ruta.parent)
        self.assertIn(self.ruta.name, destino.name)

    def test_declara_hash_tamano_y_lo_que_se_le_pase(self):
        import json

        destino = can_capture.escribir_metadatos(
            self.ruta, {"plataforma": "TOYOTA_RAV4_TSS2", "tramas": len(TRAMAS)})
        datos = json.loads(destino.read_text(encoding="utf-8"))
        self.assertEqual(len(datos["sha256"]), 64)
        self.assertEqual(datos["bytes"], self.ruta.stat().st_size)
        self.assertEqual(datos["plataforma"], "TOYOTA_RAV4_TSS2")
        self.assertEqual(datos["formato_archivo"], can_capture.VERSION_FORMATO)

    def test_el_hash_cambia_si_el_archivo_cambia(self):
        antes = can_capture.huella_sha256(self.ruta)
        with self.ruta.open("ab") as archivo:
            archivo.write(b"\x00")
        self.assertNotEqual(antes, can_capture.huella_sha256(self.ruta))


if __name__ == "__main__":
    unittest.main()
