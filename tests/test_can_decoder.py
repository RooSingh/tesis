"""Pruebas del decodificador CAN del Toyota RAV4.

Como se rompe la circularidad
-----------------------------
El riesgo de una prueba de decodificacion es comprobar el lector contra si mismo:
si la ubicacion de un campo estuviera mal, el constructor de la prueba y el lector
se equivocarian igual y la prueba pasaria.

Aca las tramas se arman **ubicando los bytes a mano**, calculados desde la
definicion del catalogo, y se comprueba el valor fisico esperado. Si el lector
contara los bits desde el extremo equivocado, los bytes escritos a mano no
darian el valor esperado.

Es el mismo criterio que el trabajo adopto para el protocolo del simulador
despues de que una prueba escrita contra la misma cadena de formato dejara pasar
un indice corrido.
"""

from __future__ import annotations

import unittest

from backend import can_decoder


def trama(**bytes_por_indice: int) -> bytes:
    """Arma una trama de ocho bytes con los indices indicados."""

    datos = bytearray(8)
    for clave, valor in bytes_por_indice.items():
        datos[int(clave[1:])] = valor
    return bytes(datos)


class VelocidadTests(unittest.TestCase):
    """`SPEED` es `47|16@0+` con escala 0,01, y ocupa los bytes 5 y 6."""

    def test_una_velocidad_conocida_se_lee_como_tal(self):
        # 107,00 km/h -> 10700 crudo -> 0x29CC -> byte 5 = 0x29, byte 6 = 0xCC.
        r = can_decoder.decodificar(180, trama(b5=0x29, b6=0xCC))
        self.assertAlmostEqual(r["senales"]["speed"], 107.00, places=2)

    def test_velocidad_cero(self):
        r = can_decoder.decodificar(180, trama())
        self.assertEqual(r["senales"]["speed"], 0.0)

    def test_los_bytes_vecinos_no_afectan_la_lectura(self):
        """Si el campo estuviera corrido, ensuciar los vecinos lo cambiaria."""

        limpia = can_decoder.decodificar(180, trama(b5=0x29, b6=0xCC))
        sucia = can_decoder.decodificar(
            180, trama(b0=0xFF, b1=0xFF, b2=0xFF, b3=0xFF, b4=0xFF,
                       b5=0x29, b6=0xCC, b7=0xFF))
        self.assertEqual(limpia["senales"]["speed"], sucia["senales"]["speed"])


class RuedasTests(unittest.TestCase):
    """`WHEEL_SPEED_FR` es `6|15@0+`, escala 0,01 y desplazamiento -67,67."""

    def test_el_desplazamiento_se_aplica(self):
        """Con el campo en cero la velocidad no es cero, es el desplazamiento.

        Olvidar el desplazamiento daria valores plausibles y equivocados por
        casi setenta kilometros por hora.
        """

        r = can_decoder.decodificar(170, trama())
        self.assertAlmostEqual(r["senales"]["wheel_speed_fr"], -67.67, places=2)

    def test_las_cuatro_ruedas_ocupan_lugares_distintos(self):
        """Escribir una rueda no debe mover a las otras tres."""

        # La delantera derecha vive en los bytes 0 y 1.
        r = can_decoder.decodificar(170, trama(b0=0x1A, b1=0xF0))
        senales = r["senales"]
        self.assertNotAlmostEqual(senales["wheel_speed_fr"], -67.67, places=2)
        for otra in ("wheel_speed_fl", "wheel_speed_rr", "wheel_speed_rl"):
            with self.subTest(rueda=otra):
                self.assertAlmostEqual(senales[otra], -67.67, places=2)


class CinematicaTests(unittest.TestCase):
    """`KINEMATICS` trae guinada y las dos aceleraciones."""

    def test_el_desplazamiento_centra_la_guinada(self):
        r = can_decoder.decodificar(36, trama())
        self.assertAlmostEqual(r["senales"]["yaw_rate"], -125.0, places=2)

    def test_las_tres_magnitudes_son_independientes(self):
        r = can_decoder.decodificar(36, trama(b2=0xFF))
        senales = r["senales"]
        # El byte 2 pertenece a la aceleracion longitudinal.
        self.assertNotAlmostEqual(senales["accel_x"], -18.375, places=3)
        self.assertAlmostEqual(senales["accel_y"], -18.375, places=3)


class BooleanosTests(unittest.TestCase):
    """Un bit mal ubicado da cero o uno igual, y solo el valor esperado lo delata."""

    def test_el_freno_lee_su_bit(self):
        # `BRAKE_PRESSED` es `37|1@0+`: byte 4, quinto bit desde el bajo.
        suelto = can_decoder.decodificar(550, trama())
        self.assertEqual(suelto["senales"]["brake_pressed"], 0.0)
        pisado = can_decoder.decodificar(550, trama(b4=0b00100000))
        self.assertEqual(pisado["senales"]["brake_pressed"], 1.0)

    def test_el_acelerador_se_invierte_al_publicarse(self):
        """El catalogo declara `GAS_RELEASED`; el contrato publica presionado.

        La inversion se hace en el decodificador y no en cada consumidor: dejarla
        afuera obligaria a recordarla en cada sitio de uso, y olvidarla daria un
        acelerador exactamente al reves sin que nada falle.
        """

        # `GAS_RELEASED` es `4|1@0+`: byte 0, quinto bit desde el bajo.
        liberado = can_decoder.decodificar(466, trama(b0=0b00010000))
        self.assertEqual(liberado["senales"]["gas_pressed"], 0.0)

        pisado = can_decoder.decodificar(466, trama())
        self.assertEqual(pisado["senales"]["gas_pressed"], 1.0)

    def test_el_campo_liberado_no_se_publica(self):
        """Publicar los dos invitaria a usar el equivocado."""

        r = can_decoder.decodificar(466, trama())
        self.assertNotIn("gas_released", r["senales"])


class AlcanceTests(unittest.TestCase):
    """Lo que el decodificador no hace, y por que."""

    def test_un_identificador_no_respaldado_devuelve_nada(self):
        """Son ciento setenta contra seis: es el caso normal, no un error."""

        self.assertIsNone(can_decoder.decodificar(1234, trama()))

    def test_la_marcha_no_se_decodifica(self):
        """Declara estacionado con el vehiculo en movimiento en 28 de 30 segmentos.

        Publicarla seria peor que su ausencia: la ausencia se nota, un valor
        falso no.
        """

        self.assertNotIn(956, can_decoder.IDENTIFICADORES_RESPALDADOS)
        self.assertIsNone(can_decoder.decodificar(956, trama()))
        self.assertEqual(can_decoder.MARCHA_NO_PUBLICADA["estado"], "abierta")

    def test_cada_mensaje_declara_confianza_y_limite(self):
        """El consumidor no puede deducirlas del valor."""

        for identificador in can_decoder.IDENTIFICADORES_RESPALDADOS:
            with self.subTest(identificador=identificador):
                r = can_decoder.decodificar(identificador, trama())
                self.assertIn(r["confianza"],
                              (can_decoder.ALTA, can_decoder.MEDIA_ALTA))
                self.assertTrue(r["limite"])

    def test_una_trama_corta_falla_en_vez_de_inventar(self):
        """Leer fuera de la trama daria ceros con apariencia de medicion."""

        with self.assertRaises(ValueError):
            can_decoder.decodificar(180, bytes(4))


if __name__ == "__main__":
    unittest.main()
