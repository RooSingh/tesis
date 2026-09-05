# -*- coding: utf-8 -*-
"""El estado de la pista se publica como canal y no solo como metadato.

Motivo, encontrado en la verificacion previa de la prueba de lluvia: el clima y
las dos temperaturas se decodificaban y no llegaban al contrato interno. Iban a
la procedencia, que guarda un valor por captura, de modo que una carrera que
empieza seca y termina mojada habria quedado descrita por la condicion del final.

El paquete de prueba se toma de una captura real y no se arma a mano. Armarlo
exigiria reproducir una cabecera de veintinueve bytes y una carga de mas de
seiscientos, y una cabecera escrita a mano prueba que el codigo funciona sobre
una cabecera escrita a mano.
"""

import unittest
from pathlib import Path

from adapters import f1_25
from backend import f1_capture, f1_udp

RAIZ = Path(__file__).resolve().parents[1]
CAPTURAS = RAIZ / "datasets" / "f1_25" / "capturas"
INICIO = "2026-09-02T00:00:00+00:00"


def _paquete_de_sesion_real() -> dict | None:
    """Primer paquete de sesion de la captura mas reciente que haya en disco."""

    for ruta in sorted(CAPTURAS.glob("*.f1raw"), reverse=True):
        try:
            for datagrama in f1_capture.leer_captura(ruta):
                try:
                    d = f1_udp.decodificar(datagrama.carga)
                except Exception:
                    continue
                if d.get("decodificado") and d["paquete"] == "session":
                    return d
        except Exception:
            continue
    return None


class ClimaEnElCatalogo(unittest.TestCase):

    def test_las_tres_senales_estan_publicadas(self):
        nombres = {s["signal_name"] for s in f1_25.catalogo_de_senales()}
        self.assertIn("weather_code", nombres)
        self.assertIn("track_temperature", nombres)
        self.assertIn("air_temperature", nombres)

    def test_las_temperaturas_declaran_su_unidad(self):
        unidades = {s["signal_name"]: s["unit"] for s in f1_25.catalogo_de_senales()}
        self.assertEqual(unidades["track_temperature"], "C")
        self.assertEqual(unidades["air_temperature"], "C")

    def test_el_clima_viaja_como_codigo_y_no_como_texto(self):
        """Traducirlo pondria texto en una tabla de valores medidos.

        El significado de cada codigo vive en la tabla del capturador, que es
        donde vive la transcripcion de la especificacion.
        """

        unidades = {s["signal_name"]: s["unit"] for s in f1_25.catalogo_de_senales()}
        self.assertEqual(unidades["weather_code"], "codigo")

    def test_el_paquete_de_sesion_es_normalizable(self):
        self.assertIn("session", f1_25.PAQUETES_NORMALIZABLES)

    def test_el_paquete_de_sesion_describe_un_solo_vehiculo(self):
        """No lleva arreglo de veintidos: se ata al vehiculo propio.

        Pedirlo para todos los vehiculos tiene que fallar en lugar de devolver
        el propio en silencio, igual que el paquete de dinamica extendida.
        """

        self.assertIn("session", f1_25.PAQUETES_DE_BLOQUE_UNICO)


class ClimaNormalizado(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.paquete = _paquete_de_sesion_real()

    def setUp(self):
        if self.paquete is None:
            self.skipTest("no hay ninguna captura con paquete de sesion en disco")

    def test_produce_las_tres_senales(self):
        nombres = {m["signal_name"]
                   for m in f1_25.mensajes_desde_paquete(self.paquete, INICIO)}
        self.assertEqual(
            nombres, {"weather_code", "track_temperature", "air_temperature"})

    def test_los_valores_son_los_del_paquete(self):
        mensajes = f1_25.mensajes_desde_paquete(self.paquete, INICIO)
        por_nombre = {m["signal_name"]: m["value"] for m in mensajes}
        sesion = self.paquete["sesion"]
        self.assertEqual(por_nombre["weather_code"], sesion["weather"])
        self.assertEqual(por_nombre["track_temperature"], sesion["track_temperature_c"])
        self.assertEqual(por_nombre["air_temperature"], sesion["air_temperature_c"])

    def test_la_lluvia_se_distingue_del_tiempo_seco(self):
        """Es la condicion que la prueba de lluvia necesita poder afirmar."""

        def valor(clima):
            copia = dict(self.paquete)
            copia["sesion"] = dict(self.paquete["sesion"], weather=clima)
            mensajes = f1_25.mensajes_desde_paquete(copia, INICIO)
            return next(m["value"] for m in mensajes
                        if m["signal_name"] == "weather_code")

        self.assertNotEqual(valor(0), valor(4))

    def test_pedirlo_para_todos_los_vehiculos_falla(self):
        with self.assertRaises(f1_25.ErrorNormalizacion):
            f1_25.mensajes_desde_paquete(
                self.paquete, INICIO, solo_vehiculo_propio=False)


if __name__ == "__main__":
    unittest.main()
