# -*- coding: utf-8 -*-
"""Pruebas de la regla que decide que ayudas se archivan.

El caso que motiva el archivo es real: en la primera pasada de la prueba de dos
conductores el antibloqueo se archivo como activo porque la ultima lectura de la
captura llega despues de la bandera a cuadros. La pantalla del juego lo declaraba
apagado y el canal lo mostro en cero durante los cinco giros de carrera.
"""

import unittest

from scripts.capturar_f1_25 import AyudasEnMarcha


def telemetria(velocidad):
    return {"paquete": "car_telemetry", "vehiculo_propio": {"speed_kmh": velocidad}}


def estado(traccion, antibloqueo):
    return {"paquete": "car_status",
            "vehiculo_propio": {"traction_control": traccion,
                                "anti_lock_brakes": antibloqueo}}


class AyudasQueSeArchivan(unittest.TestCase):

    def test_ignora_lo_que_llega_con_el_auto_detenido(self):
        """El caso que rompio: la ultima lectura es de menu, no de carrera."""

        acc = AyudasEnMarcha()
        acc.ver(telemetria(0))
        acc.ver(estado(0, 0))          # menu previo
        acc.ver(telemetria(280))
        for _ in range(100):
            acc.ver(estado(0, 0))      # los cinco giros de carrera
        acc.ver(telemetria(0))
        acc.ver(estado(0, 1))          # despues de la bandera a cuadros

        self.assertEqual(acc.estado()["anti_lock_brakes"], 0)
        self.assertEqual(acc.estado()["marcos_en_marcha"], 100)

    def test_un_marco_suelto_no_cambia_lo_declarado(self):
        """Se archiva la moda, no la ultima lectura ni la primera."""

        acc = AyudasEnMarcha()
        acc.ver(telemetria(200))
        for _ in range(50):
            acc.ver(estado(1, 0))
        acc.ver(estado(0, 1))          # un marco discordante
        self.assertEqual(acc.estado()["traction_control"], 1)
        self.assertEqual(acc.estado()["anti_lock_brakes"], 0)

    def test_declara_de_donde_salio_el_valor(self):
        acc = AyudasEnMarcha()
        acc.ver(telemetria(120))
        acc.ver(estado(2, 1))
        self.assertEqual(acc.estado()["ayudas_desde"],
                         "moda con el auto en marcha, antes de la bandera")

    def test_no_cuenta_lo_que_llega_despues_de_la_bandera(self):
        """Estar en movimiento no alcanza: tras la bandera el auto sigue rodando.

        En la primera pasada de la prueba de dos conductores llegaron 885 marcos
        posteriores a la bandera con el auto en marcha y el antibloqueo en uno.
        La moda resolvio el caso por margen, no por criterio.
        """

        acc = AyudasEnMarcha()
        acc.ver(telemetria(250))
        for _ in range(10):
            acc.ver(estado(0, 0))          # la carrera
        acc.ver({"paquete": "event", "codigo": "CHQF"})
        for _ in range(500):
            acc.ver(estado(0, 1))          # desaceleracion, todavia rodando
        self.assertEqual(acc.estado()["anti_lock_brakes"], 0)
        self.assertEqual(acc.estado()["marcos_en_marcha"], 10)

    def test_el_fin_de_sesion_tambien_cierra_la_cuenta(self):
        acc = AyudasEnMarcha()
        acc.ver(telemetria(250))
        acc.ver(estado(1, 0))
        acc.ver({"paquete": "event", "codigo": "SEND"})
        for _ in range(50):
            acc.ver(estado(2, 1))
        self.assertEqual(acc.estado()["traction_control"], 1)

    def test_un_reinicio_reabre_la_cuenta(self):
        """El juego emite fin de sesion en cada reinicio, sin cambiar el uid.

        Una captura del 2026-09-01 tiene veinticuatro pares de sesion-iniciada y
        sesion-terminada con un unico `session_uid`. Sin reabrir la cuenta, el
        primer reinicio la cerraba para siempre.
        """

        acc = AyudasEnMarcha()
        acc.ver({"paquete": "event", "codigo": "SEND"})   # cola del intento previo
        acc.ver({"paquete": "event", "codigo": "SSTA"})
        acc.ver({"paquete": "event", "codigo": "LGOT"})
        acc.ver(telemetria(240))
        for _ in range(80):
            acc.ver(estado(1, 0))
        self.assertEqual(acc.estado()["traction_control"], 1)
        self.assertEqual(acc.estado()["marcos_en_marcha"], 80)

    def test_un_intento_abandonado_no_borra_el_anterior(self):
        """Si el ultimo intento no llego a rodar, describe la captura el anterior."""

        acc = AyudasEnMarcha()
        acc.ver({"paquete": "event", "codigo": "SSTA"})
        acc.ver(telemetria(200))
        for _ in range(60):
            acc.ver(estado(2, 1))
        acc.ver({"paquete": "event", "codigo": "SSTA"})   # reinicio, y nada mas
        self.assertEqual(acc.estado()["traction_control"], 2)
        self.assertEqual(acc.estado()["marcos_en_marcha"], 60)

    def test_captura_que_solo_toco_el_menu_devuelve_la_ultima_lectura(self):
        """Sin nada mejor se devuelve lo que hay, sin fingir que se midio."""

        acc = AyudasEnMarcha()
        acc.ver(telemetria(0))
        acc.ver(estado(0, 0))
        resultado = acc.estado()
        self.assertEqual(resultado["traction_control"], 0)
        self.assertNotIn("ayudas_desde", resultado)

    def test_sin_ningun_paquete_no_falla(self):
        self.assertIsNone(AyudasEnMarcha().estado())

    def test_la_regla_no_esta_escrita_dos_veces(self):
        """La rederivacion tiene que usar este mismo acumulador.

        Estaba duplicada, y arreglar una sola copia habria dejado que el crudo y
        su rederivacion declararan ayudas distintas sobre el mismo archivo.
        """

        from scripts import rederivar_metadatos
        self.assertIs(rederivar_metadatos.AyudasEnMarcha, AyudasEnMarcha)


if __name__ == "__main__":
    unittest.main()
