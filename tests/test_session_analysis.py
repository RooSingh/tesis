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
    DRS_CODIGO_MINIMO_ABIERTO,
    MINISECTOR_AMARILLO,
    MINISECTOR_PURPURA,
    MINISECTOR_VERDE,
    UMBRAL_ACELERADOR_A_FONDO,
    contar_minisectores_vuelta,
    evaluar_calidad,
    integrar_distancia_m,
    resolver_referencia_circuito,
    resolver_resolucion_minisector,
    resumir_minisectores,
    resumir_telemetria,
    validar_distancia,
)
from backend.track_reference import LONGITUDES_CIRCUITO

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
        resultado = validar_distancia(None, 5891.0)

        self.assertFalse(resultado["distancia_validada"])
        self.assertIn("distancia_validacion_motivo", resultado)

    def test_la_validacion_arrastra_la_fuente_de_la_referencia(self) -> None:
        """El desvio sin decir contra que se midio no es defendible."""
        referencia = resolver_referencia_circuito(circuit_key=2)

        resultado = validar_distancia(5832.0, referencia)

        self.assertTrue(resultado["distancia_validada"])
        self.assertEqual(resultado["distancia_referencia_m"], 5891.0)
        self.assertIn("formula1.com", resultado["distancia_referencia_fuente"])
        self.assertIn("no medida", resultado["distancia_referencia_tipo"])

    def test_cada_circuito_se_valida_contra_su_propia_longitud(self) -> None:
        """Regresion del defecto corregido el 2026-08-28.

        La referencia era la constante `LONGITUD_SILVERSTONE_M`. Una vuelta de
        Spa-Francorchamps de 6.950 m se comparaba contra 5.891 m y salia con un
        desvio de +18 % que no describia nada real.
        """
        spa = resolver_referencia_circuito(circuit_key=7)
        silverstone = resolver_referencia_circuito(circuit_key=2)

        contra_spa = validar_distancia(6950.0, spa)
        contra_silverstone = validar_distancia(6950.0, silverstone)

        self.assertEqual(spa["longitud_referencia_m"], 7004.0)
        self.assertAlmostEqual(contra_spa["distancia_desvio_pct"], -0.77, places=2)
        self.assertAlmostEqual(contra_silverstone["distancia_desvio_pct"], 17.98, places=2)


class ReferenciaCircuitoTests(unittest.TestCase):
    """La longitud del circuito es dato externo declarado, no medido aqui."""

    def test_resuelve_por_circuit_key_las_sesiones_importadas(self) -> None:
        esperado = {2: 5891.0, 7: 7004.0, 46: 5807.0}

        for circuit_key, longitud in esperado.items():
            with self.subTest(circuit_key=circuit_key):
                referencia = resolver_referencia_circuito(circuit_key=circuit_key)

                self.assertTrue(referencia["referencia_disponible"])
                self.assertEqual(referencia["longitud_referencia_m"], longitud)

    def test_toda_entrada_declara_su_fuente_citable(self) -> None:
        """Una referencia externa sin fuente no se puede defender."""
        for circuit_key, entrada in LONGITUDES_CIRCUITO.items():
            with self.subTest(circuit_key=circuit_key):
                self.assertTrue(entrada["fuente"].startswith("https://"))
                self.assertEqual(entrada["temporada"], 2025)
                self.assertGreater(entrada["longitud_m"], 0)

    def test_resuelve_por_nombre_cuando_falta_la_clave(self) -> None:
        referencia = resolver_referencia_circuito(circuit_short_name="Spa-Francorchamps")

        self.assertEqual(referencia["longitud_referencia_m"], 7004.0)

    def test_un_circuito_sin_longitud_conocida_no_se_inventa(self) -> None:
        """El analisis declara la ausencia en vez de asumir una longitud."""
        referencia = resolver_referencia_circuito(circuit_key=99999, circuit_short_name="Nuevo")

        self.assertFalse(referencia["referencia_disponible"])
        self.assertIsNone(referencia["longitud_referencia_m"])
        self.assertIn("no hay longitud de circuito declarada", referencia["referencia_motivo"])

    def test_sin_referencia_la_distancia_no_se_valida_y_se_dice_por_que(self) -> None:
        referencia = resolver_referencia_circuito(circuit_key=99999)

        resultado = validar_distancia(6950.0, referencia)

        self.assertFalse(resultado["distancia_validada"])
        self.assertNotIn("distancia_desvio_pct", resultado)
        self.assertIn(
            "no hay longitud de circuito declarada", resultado["distancia_validacion_motivo"]
        )

    def test_la_longitud_indicada_a_mano_queda_marcada_como_tal(self) -> None:
        """Un valor del operador no puede confundirse con la tabla declarada."""
        referencia = resolver_referencia_circuito(
            circuit_key=99999, circuit_short_name="Nuevo", longitud_declarada_m=4000.0
        )

        self.assertTrue(referencia["referencia_disponible"])
        self.assertEqual(referencia["longitud_referencia_m"], 4000.0)
        self.assertEqual(referencia["referencia_origen"], "operador")

    def test_una_longitud_a_mano_no_positiva_no_habilita_la_validacion(self) -> None:
        referencia = resolver_referencia_circuito(circuit_key=2, longitud_declarada_m=0.0)

        self.assertFalse(referencia["referencia_disponible"])


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
        """El histograma es dato observado y permite auditar la clasificacion."""
        resumen = resumir_telemetria({
            "speed": muestras([100.0] * 4),
            "drs_state_code": muestras([12.0, 12.0, 1.0, 1.0]),
        })

        self.assertEqual(resumen["drs_abierto_pct"], 50.0)
        self.assertEqual(resumen["drs_codigos"], {"1": 2, "12": 2})
        self.assertTrue(resumen["drs_interpretacion_validada"])

    def test_los_codigos_9_y_11_cuentan_como_aleron_abierto(self) -> None:
        """Regresion del error corregido el 2026-08-27.

        La primera implementacion uso el conjunto {10, 12, 14} tomado de
        documentacion comunitaria. Cruzar `drs_state_code` con `speed` sobre las
        683.720 muestras de la carrera mostro que los codigos 9 y 11 promedian
        289,7 y 276,5 km/h, es decir el grupo de aleron abierto, mientras que el
        codigo 8 promedia 126,7. El umbral correcto es 9.
        """
        resumen = resumir_telemetria({
            "speed": muestras([100.0] * 4),
            "drs_state_code": muestras([9.0, 11.0, 8.0, 1.0]),
        })

        self.assertEqual(DRS_CODIGO_MINIMO_ABIERTO, 9)
        self.assertEqual(resumen["drs_abierto_pct"], 50.0)


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

    def test_guarda_la_referencia_de_circuito_con_su_fuente(self) -> None:
        referencia = resolver_referencia_circuito(circuit_key=7)

        calidad = evaluar_calidad({"speed": muestras([1.0, 2.0])}, referencia)

        self.assertEqual(calidad["longitud_referencia_m"], 7004.0)
        self.assertEqual(calidad["longitud_referencia"]["referencia_circuito"], "Spa-Francorchamps")
        self.assertIn("formula1.com", calidad["longitud_referencia"]["referencia_fuente"])

    def test_declara_la_ausencia_de_referencia_en_vez_de_omitirla(self) -> None:
        """Un campo faltante se confunde con un descuido; la ausencia se dice."""
        referencia = resolver_referencia_circuito(circuit_key=99999)

        calidad = evaluar_calidad({"speed": muestras([1.0, 2.0])}, referencia)

        self.assertNotIn("longitud_referencia_m", calidad)
        self.assertFalse(calidad["longitud_referencia"]["referencia_disponible"])
        self.assertIn("referencia_motivo", calidad["longitud_referencia"])


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



class ResolucionMinisectorTests(unittest.TestCase):
    """Cuantos minisectores tiene una vuelta es un dato de cada circuito.

    Estaba fijo en 26, que es el conteo de Silverstone. Contado sobre los propios
    `laps.json` importados, Spa-Francorchamps declara 28: con la longitud ya
    parametrizada pero el 26 en el denominador, Spa habria persistido 269,4 m de
    resolucion cuando su valor real es 250,1 m.
    """

    def _vuelta(self, s1: int, s2: int, s3: int) -> dict:
        return {
            "segments_sector_1": [MINISECTOR_AMARILLO] * s1,
            "segments_sector_2": [MINISECTOR_AMARILLO] * s2,
            "segments_sector_3": [MINISECTOR_AMARILLO] * s3,
        }

    def test_cuenta_los_tres_sectores_de_una_vuelta(self) -> None:
        self.assertEqual(contar_minisectores_vuelta(self._vuelta(7, 11, 10)), 28)

    def test_una_vuelta_sin_alguno_de_los_tres_sectores_no_aporta_conteo(self) -> None:
        """Sumar los sectores presentes daria un total menor y creible.

        Una vuelta a la que le falta el sector 3 se leeria como un circuito mas
        corto, y ese numero entraria en la moda como si fuera una observacion.
        """
        vuelta = self._vuelta(7, 11, 10)
        vuelta["segments_sector_3"] = None
        self.assertIsNone(contar_minisectores_vuelta(vuelta))
        vuelta["segments_sector_3"] = []
        self.assertIsNone(contar_minisectores_vuelta(vuelta))

    def test_usa_la_moda_y_no_la_primera_vuelta(self) -> None:
        """La primera vuelta puede ser una de las incompletas."""
        conteos = [24] + [26] * 40 + [25] * 3
        resolucion = resolver_resolucion_minisector(conteos, 5891.0)

        self.assertTrue(resolucion["disponible"])
        self.assertEqual(resolucion["minisectores_por_vuelta"], 26)
        self.assertEqual(resolucion["resolucion_m"], 226.6)

    def test_usa_la_moda_y_no_el_maximo(self) -> None:
        """Una sola vuelta anomala no debe fijar la resolucion de la sesion."""
        resolucion = resolver_resolucion_minisector([28] * 50 + [31], 7004.0)

        self.assertEqual(resolucion["minisectores_por_vuelta"], 28)
        self.assertEqual(resolucion["resolucion_m"], 250.1)

    def test_cada_circuito_da_su_propia_resolucion(self) -> None:
        """Los tres circuitos importados, con sus conteos observados."""
        silverstone = resolver_resolucion_minisector([26] * 760 + [25] * 58 + [24] * 6, 5891.0)
        spa = resolver_resolucion_minisector([28] * 862 + [27] * 17, 7004.0)
        suzuka = resolver_resolucion_minisector([26] * 1030 + [25] * 29, 5807.0)

        self.assertEqual(silverstone["resolucion_m"], 226.6)
        self.assertEqual(spa["resolucion_m"], 250.1)
        self.assertEqual(suzuka["resolucion_m"], 223.3)
        # El 26 aplicado a Spa daba 269,4 m: casi 8 % de error persistido como si
        # fuera un hecho medido de la sesion.
        self.assertNotEqual(spa["resolucion_m"], round(7004.0 / 26, 1))

    def test_el_resultado_declara_sobre_cuantas_vueltas_se_derivo(self) -> None:
        """Sin esto el numero no es auditable: se sabria el cuanto y no el sobre que."""
        resolucion = resolver_resolucion_minisector([28] * 862 + [27] * 17 + [None], 7004.0)

        self.assertEqual(resolucion["vueltas_consideradas"], 879)
        self.assertEqual(resolucion["vueltas_en_la_moda"], 862)
        self.assertEqual(resolucion["vueltas_descartadas_sin_tres_sectores"], 1)
        self.assertEqual(resolucion["distribucion_observada"], {"27": 17, "28": 862})
        self.assertIn("moda", resolucion["derivacion"])

    def test_sin_vueltas_completas_no_se_inventa_una_resolucion(self) -> None:
        resolucion = resolver_resolucion_minisector([None, None], 5891.0)

        self.assertFalse(resolucion["disponible"])
        self.assertIsNone(resolucion["resolucion_m"])
        self.assertIn("tres sectores completos", resolucion["motivo"])

    def test_sin_longitud_declarada_se_conserva_el_conteo_y_se_declara_el_faltante(self) -> None:
        """El circuito sin longitud no borra lo que si se pudo observar."""
        resolucion = resolver_resolucion_minisector([26] * 10, None)

        self.assertFalse(resolucion["disponible"])
        self.assertIsNone(resolucion["resolucion_m"])
        self.assertEqual(resolucion["minisectores_por_vuelta"], 26)
        self.assertIn("longitud de circuito", resolucion["motivo"])



if __name__ == "__main__":
    unittest.main()
