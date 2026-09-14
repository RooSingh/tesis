"""El cuadro de un cambio de panel se toma despues del cambio.

Pantalla y dato cambian de panel casi a la vez: en el instante del cambio la
pantalla todavia muestra el panel anterior o esta en blanco. Un extractor que
toma el cuadro en ese instante produce figuras corridas un indice, que es lo
que paso con las del capitulo 12. Aqui se fija que el instante extraido es **el
del cambio mas el retardo**, con el desfase del video aplicado, y que los
instantes que no son cambios de panel no se corren.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend import f1_udp
from backend.f1_capture import Datagrama
from scripts import extraer_cuadros_validacion as extractor

TAMANO_TELEMETRIA = f1_udp.PAQUETES[6]["tamano"]


def _telemetria(panel: int, velocidad: float = 100.0, marcha: int = 5) -> dict:
    return {"mfd_panel": panel,
            "vehiculo_propio": {"speed_kmh": velocidad, "gear": marcha, "drs": 0}}


class _Captura:
    """Sustituye la lectura y la decodificacion por una secuencia fija."""

    def __init__(self, muestras: list[tuple[float, dict]]):
        self.muestras = muestras

    def leer(self, _ruta):
        for i, (segundo, _) in enumerate(self.muestras):
            yield Datagrama(int(segundo * 1_000_000), bytes([i % 256]) * TAMANO_TELEMETRIA)

    def decodificar(self, carga: bytes) -> dict:
        return self.muestras[carga[0]][1]


class InstanteDeVideo(unittest.TestCase):

    def test_suma_retardo_y_desfase(self):
        self.assertAlmostEqual(extractor.instante_de_video(100.0, -26.853, 0.3), 73.447)

    def test_nunca_antes_del_comienzo_del_video(self):
        self.assertEqual(extractor.instante_de_video(1.0, -26.853, 0.3), 0.0)

    def test_el_retardo_por_omision_es_tres_decimas(self):
        self.assertEqual(extractor.RETARDO_PANEL_S, 0.3)


class RetardoEnLaExtraccion(unittest.TestCase):

    def _extraer(self, muestras, retardo, desfase):
        captura = _Captura(muestras)
        llamadas = []

        def ffmpeg_falso(argumentos, **_):
            llamadas.append(argumentos)
            Path(argumentos[-1]).write_bytes(b"png")
            return mock.Mock(returncode=0, stderr="")

        with tempfile.TemporaryDirectory() as carpeta, \
                mock.patch.object(extractor.f1_capture, "leer_captura", captura.leer), \
                mock.patch.object(extractor.f1_udp, "decodificar", captura.decodificar), \
                mock.patch.object(extractor.subprocess, "run", ffmpeg_falso):
            momentos = extractor.momentos_de_interes(Path("x.f1raw"), retardo)
            manifiesto = extractor.extraer("ffmpeg", Path("v.mp4"), momentos, "p",
                                           desfase, Path(carpeta))
        instantes = [float(a[a.index("-ss") + 1]) for a in llamadas]
        return manifiesto, instantes

    def test_el_instante_extraido_es_el_del_cambio_mas_el_retardo(self):
        muestras = [(10.0, _telemetria(1)), (20.0, _telemetria(3)), (20.5, _telemetria(3))]

        manifiesto, instantes = self._extraer(muestras, retardo=0.3, desfase=-5.0)

        paneles = [(m, t) for m, t in zip(manifiesto, instantes)
                   if m["motivo"].startswith("panel")]
        self.assertEqual(len(paneles), 1)
        fila, instante = paneles[0]
        self.assertAlmostEqual(instante, 20.0 + 0.3 - 5.0)
        self.assertEqual(fila["segundo_captura"], 20.0)
        self.assertEqual(fila["retardo_s"], 0.3)
        self.assertIn("temperaturas", fila["motivo"])

    def test_el_retardo_se_puede_cambiar(self):
        muestras = [(10.0, _telemetria(1)), (20.0, _telemetria(4))]

        _, instantes = self._extraer(muestras, retardo=0.5, desfase=0.0)

        self.assertIn(20.5, instantes)

    def test_la_velocidad_maxima_no_se_corre(self):
        muestras = [(10.0, _telemetria(1, velocidad=300.0)), (11.0, _telemetria(1))]

        manifiesto, instantes = self._extraer(muestras, retardo=0.3, desfase=0.0)

        maxima = [t for m, t in zip(manifiesto, instantes) if m["motivo"] == "velocidad-maxima"]
        self.assertEqual(maxima, [10.0])

    def test_la_marcha_atras_se_toma_despues_del_cambio(self):
        """Tomada en el primer instante con marcha -1, la pantalla todavia dice N."""
        muestras = [(10.0, _telemetria(1, marcha=0)), (12.0, _telemetria(1, marcha=-1)),
                    (12.5, _telemetria(1, marcha=-1))]

        manifiesto, instantes = self._extraer(muestras, retardo=0.3, desfase=-2.0)

        atras = [(m, t) for m, t in zip(manifiesto, instantes) if m["motivo"] == "marcha-atras"]
        self.assertEqual(len(atras), 1)
        fila, instante = atras[0]
        self.assertAlmostEqual(instante, 12.0 + 0.3 - 2.0)
        self.assertEqual(fila["segundo_captura"], 12.0)
        self.assertEqual(fila["retardo_s"], 0.3)

    def test_el_cuadro_va_al_destino_pedido(self):
        muestras = [(10.0, _telemetria(1)), (20.0, _telemetria(2))]
        captura = _Captura(muestras)
        escritos = []

        def ffmpeg_falso(argumentos, **_):
            escritos.append(Path(argumentos[-1]))
            Path(argumentos[-1]).write_bytes(b"png")
            return mock.Mock(returncode=0, stderr="")

        with tempfile.TemporaryDirectory() as carpeta, \
                mock.patch.object(extractor.f1_capture, "leer_captura", captura.leer), \
                mock.patch.object(extractor.f1_udp, "decodificar", captura.decodificar), \
                mock.patch.object(extractor.subprocess, "run", ffmpeg_falso):
            momentos = extractor.momentos_de_interes(Path("x.f1raw"))
            extractor.extraer("ffmpeg", Path("v.mp4"), momentos, "p", 0.0, Path(carpeta))
            self.assertTrue(all(p.parent == Path(carpeta) for p in escritos))


class Muestreo(unittest.TestCase):

    def test_tres_puntos_a_un_segundo_de_los_bordes(self):
        puntos = extractor.puntos_de_muestreo(100.0, 110.0)

        self.assertEqual([t for _, t in puntos], [101.0, 105.0, 109.0])

    def test_un_tramo_corto_se_muestrea_solo_a_la_mitad(self):
        self.assertEqual(extractor.puntos_de_muestreo(100.0, 101.5), [("solo-mitad", 100.75)])

    def test_tramos_contiguos_de_un_mismo_panel(self):
        muestras = [(1.0, _telemetria(0)), (2.0, _telemetria(0)), (3.0, _telemetria(3)),
                    (4.0, _telemetria(3))]
        captura = _Captura(muestras)
        with mock.patch.object(extractor.f1_capture, "leer_captura", captura.leer), \
                mock.patch.object(extractor.f1_udp, "decodificar", captura.decodificar):
            tramos = extractor.tramos_de_panel(Path("x.f1raw"))

        self.assertEqual(tramos, [{"panel": 0, "inicio": 1.0, "fin": 3.0},
                                  {"panel": 3, "inicio": 3.0, "fin": 4.0}])


if __name__ == "__main__":
    unittest.main()
