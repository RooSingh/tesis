# -*- coding: utf-8 -*-
"""La procedencia declara la transformacion que cada senal recibio de verdad.

El defecto que esto cierra
--------------------------
El adaptador de la fuente ya procesada declaraba `identity` para las seis senales,
y al canal de freno le aplicaba una conversion de entero a booleano. **El valor era
correcto y la procedencia mentia.**

Es peor que un valor equivocado. Un valor mal calculado suele delatarse al
graficarlo; una procedencia que afirma no haber transformado nada **cierra la
pregunta antes de que alguien la haga**: quien audite la cadena lee "identity" y
descarta esa hipotesis.
"""

import unittest

from adapters.openf1 import messages_from_openf1_sample

MUESTRA = {
    "date": "2025-07-06T14:00:00+00:00",
    "driver_number": 4,
    "session_key": 9947,
    "meeting_key": 1,
    "speed": 250,
    "throttle": 100,
    "brake": 100,
    "rpm": 11000,
    "n_gear": 7,
    "drs": 12,
}


def _por_senal(muestra=None):
    mensajes = messages_from_openf1_sample(
        muestra or MUESTRA, "car_data", "http://x", "p",
        "2026-09-03T00:00:00+00:00")
    return {m["signal_name"]: m for m in mensajes}


class TransformacionDeclarada(unittest.TestCase):

    def test_el_freno_declara_su_conversion(self):
        m = _por_senal()["brake_applied"]
        self.assertEqual(m["metadata"]["extra"]["transformation"], "int_a_bool")

    def test_el_freno_se_publica_como_booleano(self):
        """La conversion existe: es lo que la procedencia tiene que declarar."""

        self.assertIsInstance(_por_senal()["brake_applied"]["value"], bool)

    def test_las_demas_senales_siguen_declarando_identidad(self):
        por_senal = _por_senal()
        for nombre in ("speed", "throttle_position", "engine_speed",
                       "gear_selected", "drs_state_code"):
            with self.subTest(senal=nombre):
                self.assertEqual(
                    por_senal[nombre]["metadata"]["extra"]["transformation"],
                    "identity")

    def test_las_demas_senales_conservan_su_valor(self):
        por_senal = _por_senal()
        self.assertEqual(por_senal["speed"]["value"], 250)
        self.assertEqual(por_senal["engine_speed"]["value"], 11000)
        self.assertEqual(por_senal["gear_selected"]["value"], 7)

    def test_el_freno_en_cero_tambien_declara_la_conversion(self):
        """La transformacion es del canal y no del valor que llego."""

        m = _por_senal({**MUESTRA, "brake": 0})["brake_applied"]
        self.assertEqual(m["metadata"]["extra"]["transformation"], "int_a_bool")
        self.assertIs(m["value"], False)

    def test_ninguna_senal_declara_identidad_si_fue_transformada(self):
        """La regla general, que es la que el defecto violaba."""

        for nombre, m in _por_senal().items():
            declarada = m["metadata"]["extra"]["transformation"]
            es_booleano = isinstance(m["value"], bool)
            if es_booleano:
                self.assertNotEqual(
                    declarada, "identity",
                    f"{nombre} se publica como booleano y declara identidad")


if __name__ == "__main__":
    unittest.main()
