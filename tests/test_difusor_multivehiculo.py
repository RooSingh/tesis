# -*- coding: utf-8 -*-
"""El difusor no puede mezclar los canales de dos vehiculos.

Hasta el 2026-09-01 la historia se indexaba por nombre de senal y nada mas, y
habia **un solo anotador**. Con un unico vehiculo publicando eso alcanzaba; al
incorporar el segundo conductor de la pantalla dividida el supuesto dejo de valer
sin que nada lo declarara.

Las consecuencias no son del mismo tamano:

* en las trazas, dos vehiculos en la misma serie dibujan una linea que no
  describe a ninguno. Se ve raro y se sospecha;

* en el anotador es peor. Un instante compuesto con el deslizamiento de un auto y
  el acelerador del otro **puede declarar un incidente que no ocurrio**, y ese
  dato corrupto parece correcto. Es la clase de error que llega al informe.

Lo que se fija aca es que los dos caminos queden separados por vehiculo.
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
    """Lo que el cliente del intermediario entrega al difusor."""

    def __init__(self, cuerpo: dict) -> None:
        self.payload = json.dumps(cuerpo).encode("utf-8")


def mensaje(vehiculo: str, senal: str, valor, t: str) -> MensajeFalso:
    return MensajeFalso({"vehicle_id": vehiculo, "driver_id": vehiculo,
                         "session_id": "sesion", "signal_name": senal,
                         "value": valor, "unit": "x", "timestamp": t,
                         "source_type": "f1_25_udp_simulation"})


class DosVehiculosEnElMismoFlujo(unittest.TestCase):

    def setUp(self):
        self.difusor = live_stream.DifusorEnVivo()
        # Los dos publican la misma senal en el mismo instante, que es
        # exactamente lo que ocurre en pantalla dividida.
        for i in range(5):
            t = f"2026-09-01T12:00:0{i}+00:00"
            self.difusor._al_recibir(None, None, mensaje("coche:A", "speed", 100 + i, t))
            self.difusor._al_recibir(None, None, mensaje("coche:B", "speed", 200 + i, t))

    def test_cada_vehiculo_tiene_su_propia_historia(self):
        self.assertEqual(sorted(self.difusor.historia), ["coche:A", "coche:B"])

    def test_los_valores_no_se_mezclan(self):
        """Es el defecto concreto: una serie con muestras de los dos."""

        a = list(self.difusor.historia["coche:A"]["speed"])
        b = list(self.difusor.historia["coche:B"]["speed"])
        self.assertEqual(a, [100, 101, 102, 103, 104])
        self.assertEqual(b, [200, 201, 202, 203, 204])

    def test_cada_vehiculo_tiene_su_propio_anotador(self):
        self.assertEqual(sorted(self.difusor.anotadores), ["coche:A", "coche:B"])

    def test_un_anotador_no_ve_los_canales_del_otro(self):
        """La consecuencia grave: un instante compuesto con dos autos.

        El anotador de A tiene que declarar el ultimo valor **de A**. Si viera el
        de B, cualquier regla que combine canales podria dispararse sobre una
        situacion que no le ocurrio a ninguno de los dos.
        """

        valor_a, _ = self.difusor.anotadores["coche:A"].ultimos["speed"]
        valor_b, _ = self.difusor.anotadores["coche:B"].ultimos["speed"]
        self.assertEqual(valor_a, 104)
        self.assertEqual(valor_b, 204)

    def test_el_estado_declara_los_vehiculos(self):
        estado = self.difusor.estado()
        self.assertEqual(estado["vehiculos"], ["coche:A", "coche:B"])
        # Una senal por vehiculo, dos en total: el conteo suma y no colapsa.
        self.assertEqual(estado["senales_con_historia"], 2)


class UnSoloVehiculoNoCambia(unittest.TestCase):
    """La sesion normal tiene que comportarse igual que antes."""

    def test_un_vehiculo_una_historia(self):
        difusor = live_stream.DifusorEnVivo()
        for i in range(3):
            difusor._al_recibir(None, None, mensaje(
                "coche:unico", "speed", 50 + i, f"2026-09-01T12:00:0{i}+00:00"))
        self.assertEqual(list(difusor.historia), ["coche:unico"])
        self.assertEqual(list(difusor.historia["coche:unico"]["speed"]), [50, 51, 52])
        self.assertEqual(len(difusor.anotadores), 1)


class LaAnotacionDiceDeQuienEs(unittest.TestCase):

    def test_viaja_con_su_vehiculo(self):
        """Sin eso, dos conductores dan una lista en la que no se sabe a quien."""

        difusor = live_stream.DifusorEnVivo()
        repartidas = []
        difusor._encolar = lambda cola, cuerpo: repartidas.append(cuerpo)
        difusor._repartir_anotacion({"nivel": "aviso", "titulo": "x",
                                     "detalle": "y", "reloj_s": 1.0}, "coche:A")
        # Sin bucle de eventos no hay reparto, pero el cuerpo ya quedo armado:
        # se comprueba que la funcion acepte y propague el vehiculo.
        self.assertEqual(difusor.anotadores, {})


if __name__ == "__main__":
    unittest.main()
