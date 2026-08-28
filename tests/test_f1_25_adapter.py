"""Pruebas de la normalizacion de F1 25 hacia el contrato interno.

Verifican dos cosas distintas: que los mensajes se ajusten al contrato que el
backend valida, y que la procedencia obligatoria viaje completa en cada mensaje.
"""

from __future__ import annotations

import unittest

from adapters import f1_25
from backend import f1_udp
from backend.models import TelemetryMessage
from tests.test_f1_udp import (
    datagrama_sin_decodificador,
    datagrama_telemetria,
    datagrama_vueltas,
)

INICIO = "2026-08-29T14:30:00+00:00"


def _telemetria(indice_propio: int = 3, marcha: int = -1) -> dict:
    return f1_udp.decodificar(datagrama_telemetria(indice_propio, marcha))


class ContratoTests(unittest.TestCase):
    """Los mensajes deben pasar la validacion que aplica el backend."""

    def test_los_mensajes_validan_contra_el_contrato(self):
        for mensaje in f1_25.mensajes_desde_paquete(_telemetria(), INICIO):
            TelemetryMessage(**mensaje)

    def test_declara_el_tipo_de_fuente_y_la_calidad(self):
        mensaje = f1_25.mensajes_desde_paquete(_telemetria(), INICIO)[0]
        self.assertEqual(mensaje["source_type"], "f1_25_udp_simulation")
        self.assertEqual(mensaje["quality_flag"], "simulated_f1_25")
        self.assertTrue(mensaje["metadata"]["extra"]["simulated"])

    def test_identificadores_derivan_de_la_sesion_del_juego(self):
        mensaje = f1_25.mensajes_desde_paquete(_telemetria(indice_propio=7), INICIO)[0]
        self.assertEqual(mensaje["session_id"], "f1_25:session:3735928559")
        self.assertEqual(mensaje["vehicle_id"], "f1_25:session:3735928559:car:7")

    def test_la_marca_temporal_se_deriva_del_inicio_de_captura(self):
        """El protocolo entrega segundos de sesion, no una fecha."""

        mensaje = f1_25.mensajes_desde_paquete(_telemetria(), INICIO)[0]
        # session_time del datagrama de prueba es 12,5 s.
        self.assertTrue(mensaje["timestamp"].startswith("2026-08-29T14:30:12.5"))

    def test_rechaza_un_inicio_de_captura_no_interpretable(self):
        with self.assertRaises(f1_25.ErrorNormalizacion):
            f1_25.mensajes_desde_paquete(_telemetria(), "el sabado a la tarde")


class SenalesTests(unittest.TestCase):
    """Conversion de unidades y fidelidad de los valores."""

    def _por_senal(self, mensajes: list[dict]) -> dict:
        return {m["signal_name"]: m for m in mensajes}

    def test_acelerador_y_freno_pasan_a_porcentaje(self):
        """El protocolo los entrega entre cero y uno."""

        senales = self._por_senal(f1_25.mensajes_desde_paquete(_telemetria(), INICIO))
        self.assertAlmostEqual(senales["throttle_position"]["value"], 85.0, places=2)
        self.assertEqual(senales["throttle_position"]["unit"], "%")
        self.assertAlmostEqual(senales["brake_position"]["value"], 0.0, places=2)

    def test_la_velocidad_pasa_sin_alterarse(self):
        senales = self._por_senal(
            f1_25.mensajes_desde_paquete(_telemetria(indice_propio=3), INICIO))
        self.assertEqual(senales["speed"]["value"], 303)
        self.assertEqual(senales["speed"]["unit"], "km/h")

    def test_la_marcha_atras_sobrevive_a_la_normalizacion(self):
        """El signo debe llegar hasta el contrato, no solo hasta el decodificador."""

        senales = self._por_senal(
            f1_25.mensajes_desde_paquete(_telemetria(marcha=-1), INICIO))
        self.assertEqual(senales["gear_selected"]["value"], -1)

    def test_normaliza_el_paquete_de_datos_de_vuelta(self):
        decodificado = f1_udp.decodificar(datagrama_vueltas())
        senales = self._por_senal(
            f1_25.mensajes_desde_paquete(decodificado, INICIO))
        self.assertEqual(senales["lap_number"]["value"], 12)
        self.assertAlmostEqual(senales["lap_distance"]["value"], 1234.5, places=1)
        self.assertEqual(senales["lap_distance"]["unit"], "m")

    def test_el_aleron_movil_se_normaliza_como_booleano(self):
        """Contrasta con la fuente deportiva, donde es un codigo de estado."""

        mensaje = f1_25.mensaje_drs(_telemetria(), INICIO)
        self.assertEqual(mensaje["signal_name"], "drs_open")
        self.assertIs(mensaje["value"], True)
        self.assertEqual(mensaje["unit"], "bool")
        TelemetryMessage(**mensaje)


class ProcedenciaTests(unittest.TestCase):
    """La procedencia es obligatoria y debe permitir reconstruir el origen."""

    def test_cada_mensaje_transporta_la_procedencia_completa(self):
        obligatorias = {
            "origen_adquisicion", "version_adaptador", "version_decodificador",
            "packet_format", "packet_id", "session_uid", "frame_identifier",
            "player_car_index", "campo_origen", "transformation",
        }
        for mensaje in f1_25.mensajes_desde_paquete(_telemetria(), INICIO):
            self.assertTrue(obligatorias <= set(mensaje["metadata"]["extra"]))

    def test_la_transformacion_se_declara_por_senal(self):
        """Declararla uniforme cuando algunas se convierten vuelve inutil el campo."""

        por_senal = {m["signal_name"]: m["metadata"]["extra"]["transformation"]
                     for m in f1_25.mensajes_desde_paquete(_telemetria(), INICIO)}
        self.assertEqual(por_senal["speed"], "identity")
        self.assertEqual(por_senal["gear_selected"], "identity")
        self.assertEqual(por_senal["throttle_position"], "escala_x100")
        self.assertEqual(por_senal["brake_position"], "escala_x100")

    def test_distingue_adquisicion_en_vivo_de_reproduccion(self):
        """Un dato reproducido no sostiene las mismas afirmaciones de latencia."""

        vivo = f1_25.mensajes_desde_paquete(_telemetria(), INICIO)[0]
        repro = f1_25.mensajes_desde_paquete(
            _telemetria(), INICIO, origen=f1_25.ORIGEN_REPRODUCIDO,
            captura_sha256="a" * 64)[0]
        self.assertEqual(vivo["metadata"]["extra"]["origen_adquisicion"],
                         "consola_en_vivo")
        self.assertEqual(repro["metadata"]["extra"]["origen_adquisicion"],
                         "captura_reproducida")
        self.assertEqual(repro["metadata"]["extra"]["captura_sha256"], "a" * 64)

    def test_rechaza_un_origen_desconocido(self):
        with self.assertRaises(f1_25.ErrorNormalizacion):
            f1_25.mensajes_desde_paquete(_telemetria(), INICIO, origen="inventado")


class AlcanceTests(unittest.TestCase):
    """Restricciones de alcance que el adaptador hace cumplir."""

    def test_por_defecto_solo_normaliza_el_vehiculo_propio(self):
        """Los demas vehiculos son terceros; emitirlos contradice el alcance."""

        mensajes = f1_25.mensajes_desde_paquete(_telemetria(indice_propio=5), INICIO)
        vehiculos = {m["vehicle_id"] for m in mensajes}
        self.assertEqual(vehiculos, {"f1_25:session:3735928559:car:5"})

    def test_puede_pedirse_la_grilla_completa_de_forma_explicita(self):
        mensajes = f1_25.mensajes_desde_paquete(
            _telemetria(), INICIO, solo_vehiculo_propio=False)
        vehiculos = {m["vehicle_id"] for m in mensajes}
        self.assertEqual(len(vehiculos), f1_udp.VEHICULOS)

    def test_rechaza_un_paquete_no_decodificado(self):
        decodificado = f1_udp.decodificar(datagrama_sin_decodificador())
        with self.assertRaises(f1_25.ErrorNormalizacion):
            f1_25.mensajes_desde_paquete(decodificado, INICIO)


if __name__ == "__main__":
    unittest.main()
