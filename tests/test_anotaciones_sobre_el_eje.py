# -*- coding: utf-8 -*-
"""Las anotaciones se pueden ubicar sobre la traza, y no solo listar.

El problema que esto cierra
---------------------------
La vista en vivo conservaba treinta segundos por senal. Su eje **se desplazaba**:
lo viejo salia por la izquierda, de modo que una anotacion de hace dos minutos no
tenia una abscisa donde dibujarse. Por eso las anotaciones vivian en una lista
aparte, desconectadas de las trazas, que fue el reparo que la autora repitio.

Que hace falta para cerrarlo
----------------------------
Dos cosas, y las dos se verifican aca:

1. que el resumen conserve **la sesion entera** y no una ventana;
2. que resumen y anotaciones compartan **un origen comun**, porque las
   anotaciones viajan con el reloj de la sesion y el resumen con el tiempo
   transcurrido. Sin ese origen la traduccion no existe y la marca cae en el
   lugar equivocado, que es peor que no dibujarla.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from backend import live_stream  # noqa: E402


class MensajeFalso:
    def __init__(self, cuerpo: dict) -> None:
        self.payload = json.dumps(cuerpo).encode("utf-8")


def _mensaje(vehiculo: str, senal: str, valor, marca: str) -> MensajeFalso:
    return MensajeFalso({
        "timestamp": marca,
        "vehicle_id": vehiculo,
        "driver_id": vehiculo,
        "session_id": "s",
        "signal_name": senal,
        "value": valor,
        "unit": "u",
        "quality_flag": "simulated_f1_25",
        "source_type": "f1_25_udp_simulation",
        "metadata": {},
    })


class ResumenDelDifusor(unittest.TestCase):

    def setUp(self):
        self.difusor = live_stream.DifusorEnVivo()
        # El resumen solo se arma si hay alguien mirando: ver el comentario de
        # `SinNadieMirandoNoSeAnota` en test_difusor_multivehiculo.py.
        self.cola = self.difusor.suscribir()

    def _alimentar(self, segundos: int, vehiculo="car:19", senal="speed"):
        for s in range(segundos):
            for i in range(20):                      # veinte por segundo
                marca = f"2026-09-03T00:{s // 60:02d}:{s % 60:02d}.{i * 50:03d}000+00:00"
                self.difusor._al_recibir(
                    None, None, _mensaje(vehiculo, senal, float(s * 20 + i), marca))

    def test_conserva_mas_alla_de_la_ventana(self):
        """La ventana guarda 600 muestras; el resumen tiene que ir mas lejos."""

        self._alimentar(90)                          # noventa segundos
        ventana = self.difusor.historia["car:19"]["speed"]
        self.assertEqual(len(ventana), live_stream.MUESTRAS_POR_SENAL)

        resumen = self.difusor.resumen.vehiculos()["car:19"]["speed"]
        # Un intervalo por segundo: la sesion entera, no los ultimos treinta.
        self.assertGreaterEqual(len(resumen), 89)

    def test_declara_un_origen_para_traducir_el_reloj(self):
        """Sin origen comun, una anotacion no se puede ubicar sobre la traza."""

        self._alimentar(5)
        self.assertIsNotNone(self.difusor.resumen.origen)

    def test_una_anotacion_cae_en_su_lugar_del_eje(self):
        """La traduccion de reloj absoluto a segundo de sesion tiene que cerrar."""

        self._alimentar(30)
        origen = self.difusor.resumen.origen
        serie = self.difusor.resumen.vehiculos()["car:19"]["speed"]
        duracion = serie[-1][0]

        # Una anotacion emitida a los diez segundos de empezar.
        reloj_de_la_anotacion = origen + 10.0
        segundo = reloj_de_la_anotacion - origen
        self.assertAlmostEqual(segundo, 10.0, places=3)
        self.assertGreater(duracion, segundo)
        # Y su posicion relativa sobre el eje es la esperada.
        self.assertAlmostEqual(segundo / duracion, 10.0 / duracion, places=6)

    def test_los_dos_vehiculos_comparten_el_mismo_origen(self):
        """Si cada uno tuviera el suyo, el mismo instante caeria en dos abscisas."""

        self._alimentar(5, vehiculo="car:18")
        self._alimentar(5, vehiculo="car:19")
        # El origen es de la sesion y no del vehiculo: uno solo, compartido.
        self.assertIsNotNone(self.difusor.resumen.origen)
        v = self.difusor.resumen.vehiculos()
        self.assertEqual(set(v), {"car:18", "car:19"})

    def test_un_pico_dentro_de_un_segundo_sobrevive_al_resumen(self):
        """Es lo que una anotacion senala, y no puede desaparecer al reducir."""

        for i in range(20):
            marca = f"2026-09-03T00:00:00.{i * 50:03d}000+00:00"
            valor = 900.0 if i == 7 else 10.0
            self.difusor._al_recibir(
                None, None, _mensaje("car:19", "wheel_slip_ratio_rear_left",
                                     valor, marca))
        serie = self.difusor.resumen.vehiculos()["car:19"]["wheel_slip_ratio_rear_left"]
        _, minimo, maximo, _ = serie[0]
        self.assertEqual(maximo, 900.0)
        self.assertEqual(minimo, 10.0)

    def test_una_marca_ilegible_no_corta_la_difusion(self):
        """Transportar no puede depender de que el resumen entienda la marca."""

        self.difusor._al_recibir(
            None, None, _mensaje("car:19", "speed", 100.0, "no-es-una-fecha"))
        self.assertEqual(self.difusor.recibidos, 1)
        self.assertEqual(self.difusor.resumen.vehiculos(), {})


if __name__ == "__main__":
    unittest.main()
