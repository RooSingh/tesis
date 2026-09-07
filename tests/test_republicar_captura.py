"""Pruebas de la re-publicacion de capturas.

Lo que protegen
---------------
La primera version de esta herramienta declaro exito habiendo perdido el 5,9 %
de las filas. No fue un error de calculo: **fue verificar contra el riesgo que
se estaba evitando —duplicar— en lugar de contra el total esperado**. Las dos
comprobaciones son distintas y solo la segunda detecta una perdida.

Estas pruebas fijan esa diferencia.
"""

from __future__ import annotations

import unittest

from scripts.republicar_captura import clasificar, clasificar_vehiculos


class ClasificacionTests(unittest.TestCase):
    """Una senal presente e incompleta no es una senal presente."""

    def test_una_senal_entera_esta_completa(self):
        estado = clasificar({"speed": 100}, {"speed": 100})
        self.assertEqual(estado["completas"], {"speed"})
        self.assertEqual(estado["incompletas"], {})
        self.assertEqual(estado["filas_faltantes"], 0)

    def test_una_senal_sin_filas_esta_ausente(self):
        estado = clasificar({"speed": 100}, {})
        self.assertEqual(estado["ausentes"], {"speed"})
        self.assertEqual(estado["incompletas"], {})

    def test_una_senal_a_medias_no_cuenta_como_presente(self):
        """El defecto exacto: existir no es estar entera.

        Con la clasificacion anterior esta senal caia del lado de las presentes
        y la herramienta informaba que no habia nada que hacer.
        """

        estado = clasificar({"speed": 100}, {"speed": 94})
        self.assertNotIn("speed", estado["completas"])
        self.assertNotIn("speed", estado["ausentes"])
        self.assertEqual(estado["incompletas"], {"speed": (94, 100)})
        self.assertEqual(estado["filas_faltantes"], 6)

    def test_reproduce_la_forma_del_fallo_real(self):
        """Trece senales enteras y setenta y seis a medias, como ocurrio."""

        esperado = {f"vieja_{i}": 30728 for i in range(13)}
        esperado.update({f"nueva_{i}": 30728 for i in range(76)})
        presente = {s: n for s, n in esperado.items() if s.startswith("vieja")}
        presente.update({s: int(n * 0.941) for s, n in esperado.items()
                         if s.startswith("nueva")})

        estado = clasificar(esperado, presente)
        self.assertEqual(len(estado["completas"]), 13)
        self.assertEqual(len(estado["incompletas"]), 76)
        # Lo que importa: ninguna cae en ausentes, que es donde una
        # comprobacion por nombre las habria dejado invisibles.
        self.assertEqual(estado["ausentes"], set())
        self.assertGreater(estado["filas_faltantes"], 100_000)

    def test_las_tres_categorias_son_excluyentes(self):
        esperado = {"a": 10, "b": 10, "c": 10}
        estado = clasificar(esperado, {"a": 10, "b": 4})
        self.assertEqual(
            len(estado["completas"]) + len(estado["ausentes"])
            + len(estado["incompletas"]),
            len(esperado),
        )


if __name__ == "__main__":
    unittest.main()


class ClasificarVehiculosTest(unittest.TestCase):
    """El criterio de completitud de la parrilla es por vehiculo, no por senal.

    Distinguirlos importa porque `signal_name` es identico para los veintidos
    autos: preguntar por senal declara presente a `throttle` porque lo tiene el
    vehiculo propio, y saltearia a los veinte rivales enteros.
    """

    def test_vehiculo_ausente_va_a_vacios(self):
        vacios, parciales, completos = clasificar_vehiculos(
            {"car:1": 100}, {})
        self.assertEqual(vacios, {"car:1"})
        self.assertEqual(parciales, {})
        self.assertEqual(completos, set())

    def test_vehiculo_a_medias_no_cuenta_como_escrito(self):
        """Tres estados y no dos: tener filas no es estar completo."""

        vacios, parciales, completos = clasificar_vehiculos(
            {"car:1": 100}, {"car:1": 40})
        self.assertEqual(vacios, set())
        self.assertEqual(parciales, {"car:1": (40, 100)})
        self.assertEqual(completos, set())

    def test_vehiculo_propio_ya_persistido_queda_afuera(self):
        """El auto propio se excluye por estar completo, no por una regla aparte.

        Es lo que hace que la herramienta sea el complemento exacto de capturar
        en vivo solo el vehiculo propio: lo que ya entro no se reescribe.
        """

        esperado = {"car:19": 100, "car:0": 100, "car:1": 100}
        vacios, _, completos = clasificar_vehiculos(
            esperado, {"car:19": 4_586_014})
        self.assertEqual(completos, {"car:19"})
        self.assertEqual(vacios, {"car:0", "car:1"})

    def test_un_vehiculo_no_esperado_no_inventa_faltante(self):
        """Lo presente que la captura no espera no se reporta como faltante."""

        vacios, parciales, completos = clasificar_vehiculos(
            {"car:0": 10}, {"car:0": 10, "car:7": 999})
        self.assertEqual(completos, {"car:0"})
        self.assertEqual(vacios, set())
        self.assertEqual(parciales, {})
