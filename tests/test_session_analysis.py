"""Pruebas del analisis automatico por vuelta y stint, sin base de datos.

Las reglas que definen cada metrica son decisiones metodologicas de la tesis: se
prueban aqui, sobre funciones puras, para que puedan revisarse sin levantar
servicios.
"""

from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.session_analysis import (
    CODIGOS_DRS_ABIERTO,
    MINISECTOR_AMARILLO,
    MINISECTOR_PURPURA,
    MINISECTOR_VERDE,
    UMBRAL_ACELERADOR_A_FONDO,
    evaluar_calidad,
    integrar_distancia_m,
    resumir_minisectores,
    resumir_telemetria,
    validar_distancia,
)

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "generate_session_analysis", ROOT / "scripts" / "generate_session_analysis.py"
)
assert SPEC is not None and SPEC.loader is not None
generador = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generador)


BASE = datetime(2025, 7, 6, 14, 0, 0, tzinfo=timezone.utc)


def muestras(valores: list[float | None], paso: float = 1.0, booleano: bool | None = None) -> list[tuple]:
    return [(BASE + timedelta(seconds=i * paso), v, booleano) for i, v in enumerate(valores)]


class MinisectoresTests(unittest.TestCase):
    def test_cuenta_cada_estado(self) -> None:
        resumen = resumir_minisectores(
            [MINISECTOR_PURPURA, MINISECTOR_VERDE, MINISECTOR_VERDE, MINISECTOR_AMARILLO]
        )

        self.assertEqual(resumen["minisectores_purpura"], 1)
        self.assertEqual(resumen["minisectores_verde"], 2)
        self.assertEqual(resumen["minisectores_amarillo"], 1)
        self.assertEqual(resumen["minisectores_total"], 4)

    def test_un_minisector_sin_dato_no_se_cuenta_como_amarillo(self) -> None:
        """Ausencia de dato y peor tiempo son cosas distintas.

        Contar los nulos como amarillos inflaria el peor estado con tramos donde
        simplemente no llego la senal de cronometraje.
        """
        resumen = resumir_minisectores([MINISECTOR_VERDE, None, None])

        self.assertEqual(resumen["minisectores_sin_dato"], 2)
        self.assertEqual(resumen["minisectores_amarillo"], 0)
        self.assertEqual(resumen["minisectores_con_dato"], 1)


class DistanciaTests(unittest.TestCase):
    def test_integra_velocidad_constante(self) -> None:
        """100 km/h durante 10 segundos son 277,8 metros."""
        distancia = integrar_distancia_m(muestras([100.0] * 11))

        self.assertAlmostEqual(distancia, 100 / 3.6 * 10, places=6)

    def test_usa_la_velocidad_media_entre_muestras(self) -> None:
        """La regla del trapecio evita subestimar durante una aceleracion."""
        distancia = integrar_distancia_m(muestras([0.0, 100.0]))

        self.assertAlmostEqual(distancia, 50 / 3.6, places=6)

    def test_sin_muestras_suficientes_no_inventa_un_valor(self) -> None:
        self.assertIsNone(integrar_distancia_m([]))
        self.assertIsNone(integrar_distancia_m(muestras([100.0])))

    def test_ignora_muestras_sin_avance_temporal(self) -> None:
        repetidas = [(BASE, 100.0, None), (BASE, 100.0, None), (BASE + timedelta(seconds=1), 100.0, None)]

        self.assertAlmostEqual(integrar_distancia_m(repetidas), 100 / 3.6, places=6)

    def test_la_validacion_declara_el_desvio_contra_la_referencia(self) -> None:
        """No se presenta la distancia como exacta: se publica su desvio."""
        resultado = validar_distancia(5832.0, 5891.0)

        self.assertTrue(resultado["distancia_validada"])
        self.assertAlmostEqual(resultado["distancia_desvio_pct"], -1.0, places=1)

    def test_sin_distancia_la_validacion_se_declara_no_realizada(self) -> None:
        self.assertFalse(validar_distancia(None, 5891.0)["distancia_validada"])


class ResumenTelemetriaTests(unittest.TestCase):
    def test_una_ventana_sin_velocidad_no_produce_metricas(self) -> None:
        """Un resumen construido sobre una ventana vacia se leeria como real."""
        self.assertEqual(resumir_telemetria({}), {})
        self.assertEqual(resumir_telemetria({"speed": []}), {})

    def test_agrega_velocidad(self) -> None:
        resumen = resumir_telemetria({"speed": muestras([100.0, 200.0, 300.0])})

        self.assertEqual(resumen["velocidad_min_kph"], 100.0)
        self.assertEqual(resumen["velocidad_max_kph"], 300.0)
        self.assertEqual(resumen["velocidad_media_kph"], 200.0)

    def test_el_acelerador_a_fondo_usa_el_umbral_declarado(self) -> None:
        resumen = resumir_telemetria({
            "speed": muestras([100.0] * 4),
            "throttle_position": muestras([100.0, 96.0, 50.0, 0.0]),
        })

        self.assertEqual(resumen["acelerador_a_fondo_pct"], 50.0)
        self.assertEqual(resumen["acelerador_umbral_a_fondo"], UMBRAL_ACELERADOR_A_FONDO)

    def test_el_freno_se_mide_sobre_el_valor_booleano(self) -> None:
        freno = [(BASE + timedelta(seconds=i), None, v) for i, v in enumerate([True, True, False, False])]
        resumen = resumir_telemetria({"speed": muestras([100.0] * 4), "brake_applied": freno})

        self.assertEqual(resumen["freno_aplicado_pct"], 50.0)

    def test_el_drs_publica_el_histograma_ademas_de_la_interpretacion(self) -> None:
        """El histograma es dato observado; el porcentaje depende de un mapeo.

        Ese mapeo proviene de documentacion externa y no fue validado contra estos
        datos, a diferencia del de minisectores. Por eso la respuesta lo declara.
        """
        codigo_abierto = sorted(CODIGOS_DRS_ABIERTO)[0]
        resumen = resumir_telemetria({
            "speed": muestras([100.0] * 4),
            "drs_state_code": muestras([float(codigo_abierto), float(codigo_abierto), 1.0, 1.0]),
        })

        self.assertEqual(resumen["drs_abierto_pct"], 50.0)
        self.assertEqual(resumen["drs_codigos"], {"1": 2, str(codigo_abierto): 2})
        self.assertFalse(resumen["drs_interpretacion_validada"])


class CalidadTests(unittest.TestCase):
    def test_informa_el_hueco_temporal_mayor(self) -> None:
        """Un hueco grande invalida cualquier lectura fina de esa ventana."""
        con_hueco = [
            (BASE, 100.0, None),
            (BASE + timedelta(seconds=0.25), 100.0, None),
            (BASE + timedelta(seconds=3.0), 100.0, None),
        ]
        calidad = evaluar_calidad({"speed": con_hueco})

        self.assertAlmostEqual(calidad["hueco_maximo_segundos"], 2.75, places=3)
        self.assertEqual(calidad["muestras_velocidad"], 3)

    def test_declara_las_muestras_de_cada_senal(self) -> None:
        calidad = evaluar_calidad({"speed": muestras([1.0, 2.0]), "engine_speed": muestras([1.0])})

        self.assertEqual(calidad["muestras_por_senal"], {"engine_speed": 1, "speed": 2})


class RepartoPorVentanaTests(unittest.TestCase):
    def _ventanas(self) -> list[dict]:
        return [
            {"lap_number": 1, "inicio": BASE, "fin": BASE + timedelta(seconds=10), "completa": True, "fin_estimado": False},
            {"lap_number": 2, "inicio": BASE + timedelta(seconds=10), "fin": BASE + timedelta(seconds=20), "completa": True, "fin_estimado": False},
        ]

    def test_el_limite_pertenece_a_una_sola_vuelta(self) -> None:
        """El intervalo es cerrado al inicio y abierto al final."""
        filas = [(BASE + timedelta(seconds=10), "speed", 100.0, None)]

        reparto = generador.repartir_por_ventana(filas, self._ventanas())

        self.assertEqual(len(reparto[1].get("speed", [])), 0)
        self.assertEqual(len(reparto[2]["speed"]), 1)

    def test_reparte_cada_muestra_en_su_ventana(self) -> None:
        filas = [
            (BASE + timedelta(seconds=1), "speed", 100.0, None),
            (BASE + timedelta(seconds=9), "speed", 200.0, None),
            (BASE + timedelta(seconds=11), "speed", 300.0, None),
        ]

        reparto = generador.repartir_por_ventana(filas, self._ventanas())

        self.assertEqual(len(reparto[1]["speed"]), 2)
        self.assertEqual(len(reparto[2]["speed"]), 1)

    def test_las_muestras_fuera_de_toda_ventana_se_descartan(self) -> None:
        filas = [
            (BASE - timedelta(seconds=5), "speed", 100.0, None),
            (BASE + timedelta(seconds=99), "speed", 100.0, None),
        ]

        reparto = generador.repartir_por_ventana(filas, self._ventanas())

        self.assertEqual(sum(len(v) for senales in reparto.values() for v in senales.values()), 0)

    def test_las_ventanas_incompletas_quedan_excluidas(self) -> None:
        ventanas = self._ventanas()
        ventanas[1] = {**ventanas[1], "completa": False, "fin": None}
        filas = [(BASE + timedelta(seconds=11), "speed", 100.0, None)]

        reparto = generador.repartir_por_ventana(filas, ventanas)

        self.assertNotIn(2, reparto)


if __name__ == "__main__":
    unittest.main()
