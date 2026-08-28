"""Pruebas del formato de captura cruda y del reproductor con inyeccion de fallos.

Las capturas de prueba se arman en un directorio temporal con datagramas
sinteticos validos, construidos con las mismas herramientas que
`tests/test_f1_udp.py`. No se abre ningun socket ni se toca la red.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend import f1_capture
from backend.f1_capture import (
    Datagrama,
    ErrorCaptura,
    EscritorCaptura,
    MetricasReproduccion,
    PerfilDegradacion,
    leer_captura,
    reproducir,
)
from tests.test_f1_udp import datagrama_telemetria, datagrama_vueltas


def _escribir_captura(ruta: Path, cantidad: int = 40, paso_us: int = 50_000) -> None:
    """Captura sintetica: alterna telemetria y datos de vuelta a intervalo fijo."""

    with EscritorCaptura(ruta) as escritor:
        for i in range(cantidad):
            carga = datagrama_telemetria() if i % 2 == 0 else datagrama_vueltas()
            escritor.escribir(i * paso_us, carga)


class FormatoDeCapturaTests(unittest.TestCase):
    """Ida y vuelta del archivo crudo."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.ruta = Path(self._dir.name) / "sesion.f1raw"

    def tearDown(self):
        self._dir.cleanup()

    def test_lo_escrito_se_recupera_intacto(self):
        _escribir_captura(self.ruta, cantidad=10)
        leidos = list(leer_captura(self.ruta))
        self.assertEqual(len(leidos), 10)
        self.assertEqual([d.desplazamiento_us for d in leidos],
                         [i * 50_000 for i in range(10)])
        # Los datagramas se recuperan byte por byte, no reinterpretados.
        self.assertEqual(leidos[0].carga, datagrama_telemetria())
        self.assertEqual(leidos[1].carga, datagrama_vueltas())

    def test_admite_datagramas_de_distinto_tamano(self):
        """Telemetria y datos de vuelta miden distinto: el formato no asume uno."""

        _escribir_captura(self.ruta, cantidad=4)
        tamanos = {len(d.carga) for d in leer_captura(self.ruta)}
        self.assertEqual(tamanos, {1352, 1285})

    def test_rechaza_un_archivo_que_no_es_captura(self):
        self.ruta.write_bytes(b"esto no es una captura" * 10)
        with self.assertRaises(ErrorCaptura):
            list(leer_captura(self.ruta))

    def test_rechaza_archivo_mas_corto_que_la_cabecera(self):
        self.ruta.write_bytes(b"F1RAW")
        with self.assertRaises(ErrorCaptura):
            list(leer_captura(self.ruta))

    def test_captura_interrumpida_conserva_los_registros_completos(self):
        """Una sesion cortada no es una corrupcion: es lo esperado.

        Se trunca el archivo a la mitad de un datagrama y se comprueba que los
        registros anteriores siguen siendo legibles.
        """

        _escribir_captura(self.ruta, cantidad=10)
        crudo = self.ruta.read_bytes()
        self.ruta.write_bytes(crudo[:-600])   # corta el ultimo datagrama
        leidos = list(leer_captura(self.ruta))
        self.assertEqual(len(leidos), 9)


class MetadatosTests(unittest.TestCase):
    """La captura no es reproducible por un tercero sin su procedencia."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.ruta = Path(self._dir.name) / "sesion.f1raw"
        _escribir_captura(self.ruta, cantidad=6)

    def tearDown(self):
        self._dir.cleanup()

    def test_los_metadatos_declaran_huella_y_recuento(self):
        destino = f1_capture.escribir_metadatos(self.ruta, {
            "version_juego": "1.05",
            "formato_udp": 2025,
            "frecuencia_hz": 20,
            "modo": "time_trial",
        })
        datos = json.loads(destino.read_text(encoding="utf-8"))
        self.assertEqual(datos["datagramas"], 6)
        self.assertEqual(len(datos["sha256"]), 64)
        self.assertEqual(datos["formato_udp"], 2025)
        self.assertEqual(datos["frecuencia_hz"], 20)

    def test_la_huella_cambia_si_cambia_el_crudo(self):
        antes = f1_capture.huella_sha256(self.ruta)
        with EscritorCaptura(self.ruta) as escritor:
            escritor.escribir(0, datagrama_telemetria())
        self.assertNotEqual(antes, f1_capture.huella_sha256(self.ruta))


class ReproduccionTests(unittest.TestCase):
    """Degradacion controlada sobre trafico real capturado."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.ruta = Path(self._dir.name) / "sesion.f1raw"
        _escribir_captura(self.ruta, cantidad=100)

    def tearDown(self):
        self._dir.cleanup()

    def test_sin_perfil_reproduce_identico(self):
        """El caso base no debe alterar nada."""

        original = list(leer_captura(self.ruta))
        reproducido = list(reproducir(self.ruta))
        self.assertEqual(len(original), len(reproducido))
        self.assertEqual([d.desplazamiento_us for d in reproducido],
                         [d.desplazamiento_us for d in original])
        self.assertEqual([d.carga for d in reproducido], [d.carga for d in original])

    def test_la_misma_semilla_produce_la_misma_degradacion(self):
        """Sin esto un escenario experimental no se puede repetir."""

        perfil = PerfilDegradacion(probabilidad_descarte=0.3, jitter_us=5000, semilla=42)
        primera = [(d.desplazamiento_us, len(d.carga)) for d in reproducir(self.ruta, perfil)]
        segunda = [(d.desplazamiento_us, len(d.carga)) for d in reproducir(self.ruta, perfil)]
        self.assertEqual(primera, segunda)

    def test_semillas_distintas_producen_degradaciones_distintas(self):
        a = [d.desplazamiento_us for d in reproducir(
            self.ruta, PerfilDegradacion(probabilidad_descarte=0.3, semilla=1))]
        b = [d.desplazamiento_us for d in reproducir(
            self.ruta, PerfilDegradacion(probabilidad_descarte=0.3, semilla=2))]
        self.assertNotEqual(a, b)

    def test_el_descarte_se_aproxima_a_la_probabilidad_pedida(self):
        metricas = MetricasReproduccion()
        perfil = PerfilDegradacion(probabilidad_descarte=0.25, semilla=7)
        list(reproducir(self.ruta, perfil, metricas))
        self.assertEqual(metricas.leidos, 100)
        self.assertEqual(metricas.emitidos + metricas.descartados, 100)
        self.assertAlmostEqual(metricas.como_dict()["tasa_descarte"], 0.25, delta=0.12)

    def test_el_descarte_total_no_emite_nada(self):
        metricas = MetricasReproduccion()
        list(reproducir(self.ruta, PerfilDegradacion(probabilidad_descarte=1.0), metricas))
        self.assertEqual(metricas.emitidos, 0)
        self.assertEqual(metricas.descartados, 100)

    def test_el_jitter_altera_los_instantes_pero_no_las_cargas(self):
        perfil = PerfilDegradacion(jitter_us=3000, semilla=5)
        original = list(leer_captura(self.ruta))
        reproducido = list(reproducir(self.ruta, perfil))
        self.assertEqual(len(reproducido), len(original))
        self.assertEqual([d.carga for d in reproducido], [d.carga for d in original])
        self.assertNotEqual([d.desplazamiento_us for d in reproducido],
                            [d.desplazamiento_us for d in original])

    def test_el_jitter_respeta_su_cota(self):
        cota = 3000
        perfil = PerfilDegradacion(jitter_us=cota, semilla=5)
        original = list(leer_captura(self.ruta))
        for antes, despues in zip(original, reproducir(self.ruta, perfil)):
            self.assertLessEqual(abs(despues.desplazamiento_us - antes.desplazamiento_us), cota)

    def test_el_jitter_no_reordena(self):
        """Jitter y reordenamiento son fallas distintas y no deben mezclarse."""

        perfil = PerfilDegradacion(jitter_us=3000, semilla=11)
        desplazamientos = [d.desplazamiento_us for d in reproducir(self.ruta, perfil)]
        self.assertEqual(desplazamientos, sorted(desplazamientos))

    def test_el_retraso_desplaza_todo_el_flujo_por_igual(self):
        retraso = 250_000
        original = list(leer_captura(self.ruta))
        reproducido = list(reproducir(self.ruta, PerfilDegradacion(retraso_us=retraso)))
        self.assertEqual([d.desplazamiento_us for d in reproducido],
                         [d.desplazamiento_us + retraso for d in original])

    def test_las_cargas_reproducidas_siguen_siendo_decodificables(self):
        """La degradacion afecta cuando llega cada dato, no que dice."""

        from backend import f1_udp
        for datagrama in reproducir(self.ruta, PerfilDegradacion(jitter_us=4000, semilla=3)):
            resultado = f1_udp.decodificar(datagrama.carga)
            self.assertTrue(resultado["decodificado"])

    def test_rechaza_un_perfil_invalido(self):
        for perfil in (
            PerfilDegradacion(probabilidad_descarte=1.5),
            PerfilDegradacion(probabilidad_descarte=-0.1),
            PerfilDegradacion(jitter_us=-1),
            PerfilDegradacion(retraso_us=-1),
        ):
            with self.assertRaises(ValueError):
                list(reproducir(self.ruta, perfil))


if __name__ == "__main__":
    unittest.main()
