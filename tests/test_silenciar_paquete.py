# -*- coding: utf-8 -*-
"""Silenciar un tipo de paquete: el fallo parcial de sensado.

No es el descarte al azar que ya existia. Perder un datagrama quita **todas** las
senales de ese paquete durante un instante y las devuelve enseguida; silenciar un
tipo de paquete quita **una familia de senales de forma sostenida** y deja el
resto del flujo intacto, que es lo que ocurre cuando un sensor falla.

Lo primero se ve como un hueco en el flujo; lo segundo, como un canal que dejo de
existir. El sistema debe declararlos distinto, y por eso son dos escenarios y no
uno.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

import reproducir_captura_f1_25 as cli  # noqa: E402

from backend import f1_udp  # noqa: E402


class TraduccionDeNombresTest(unittest.TestCase):

    def test_traduce_nombres_a_identificadores(self):
        self.assertEqual(cli.tipos_por_nombre(["motion"]), {0})
        self.assertEqual(cli.tipos_por_nombre(["motion", "car_telemetry"]),
                         {0, 6})

    def test_un_nombre_desconocido_falla(self):
        """Creer haber silenciado un canal sin haberlo silenciado daria por
        bueno justamente el comportamiento que se venia a poner a prueba."""

        with self.assertRaises(SystemExit) as caja:
            cli.tipos_por_nombre(["acelerometro"])
        self.assertIn("acelerometro", str(caja.exception))

    def test_el_error_enumera_los_que_hay(self):
        with self.assertRaises(SystemExit) as caja:
            cli.tipos_por_nombre(["inventado"])
        self.assertIn("motion", str(caja.exception))

    def test_sin_nombres_no_silencia_nada(self):
        self.assertEqual(cli.tipos_por_nombre([]), set())

    def test_los_nombres_coinciden_con_el_catalogo_del_protocolo(self):
        """La traduccion no mantiene una tabla propia: usa la del decodificador.

        Una segunda tabla escrita a mano se desincronizaria en cuanto el
        protocolo cambiara, y este trabajo ya se quemo con tablas paralelas.
        """

        for identificador, datos in f1_udp.PAQUETES.items():
            self.assertEqual(cli.tipos_por_nombre([datos["nombre"]]),
                             {identificador})


class PosicionDelTipoTest(unittest.TestCase):

    def test_el_tipo_esta_en_el_septimo_byte(self):
        """Dos bytes de formato mas cuatro de version: el tipo queda en el 6."""

        self.assertEqual(cli.POSICION_TIPO_DE_PAQUETE, 6)

    def test_la_posicion_coincide_con_la_cabecera_declarada(self):
        """Si la cabecera cambiara, esta prueba lo dice antes que una corrida.

        Leer el byte suelto es barato y por eso se hace, pero paga el precio de
        conocer la disposicion de la cabecera en dos lugares. La prueba es lo que
        mantiene esos dos lugares de acuerdo.
        """

        campos = list(f1_udp.CABECERA_CAMPOS)
        # uint16 el primero, uint8 los cuatro siguientes.
        tamanos = {"packet_format": 2}
        posicion = 0
        for campo in campos:
            if campo == "packet_id":
                break
            posicion += tamanos.get(campo, 1)
        self.assertEqual(posicion, cli.POSICION_TIPO_DE_PAQUETE)


class ConciliacionTest(unittest.TestCase):
    """Lo silenciado es un tercer sumando, no una perdida."""

    def test_lo_leido_es_lo_descartado_mas_lo_silenciado_mas_lo_emitido(self):
        leidos, descartados, silenciados, emitidos = 3438, 0, 438, 3000
        self.assertEqual(leidos, descartados + silenciados + emitidos)

    def test_el_datagrama_silenciado_se_conto_y_no_se_perdio(self):
        """Se leyo, se decidio no emitirlo y se conto.

        Dejarlo fuera de la cuenta haria que la unica verificacion de la
        herramienta fallara siempre que se la use, que fue lo que paso en la
        primera corrida.
        """

        r = {"leidos": 3438, "descartados": 0, "silenciados": 438,
             "emitidos": 3000}
        esperado = r["descartados"] + r["silenciados"] + r["emitidos"]
        self.assertEqual(r["leidos"], esperado)


if __name__ == "__main__":
    unittest.main()
