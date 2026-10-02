"""La cobertura de vehiculos se declara para la sesion entera.

Sobre la carrera de dos conductores de Spa el tablero decia a la vez
«6 con telemetría» y «5 vehículos con telemetría guardada». El coche propio esta
en la captura original y los otros cinco en el recompletado: cada adquisicion
contaba lo suyo y ninguna cifra decia que contaba. `/adquisiciones` declara ahora
la union, que es lo que la base tiene para la sesion.
"""

from __future__ import annotations

import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest import mock

from backend import api_sesion

SESION = "f1_25:session:3731090176871608020"
T = datetime(2026, 9, 4, 21, 36, tzinfo=timezone.utc)


class _Cursor:
    def __init__(self, filas):
        self._filas = filas

    def execute(self, *_a, **_k):
        pass

    def fetchall(self):
        return self._filas

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class _Conexion:
    def __init__(self, filas):
        self._filas = filas

    def cursor(self):
        return _Cursor(self._filas)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _fila(run, vehiculos, captura=0):
    return (run, 100, len(vehiculos), T, T, list(vehiculos), [], captura)


class LaCoberturaEsDeLaSesionTests(unittest.TestCase):

    def _responder(self, filas):
        with mock.patch.object(api_sesion.db, "obtener_conexion",
                               return_value=_Conexion(filas)), \
             mock.patch.object(api_sesion, "_fuente_de",
                               return_value="f1_25_udp_simulation"), \
             mock.patch.object(api_sesion, "_parrilla_de_la_adquisicion",
                               side_effect=lambda s, f, d, h, sh, suyos, p=None:
                               {"disponible": False, "con_telemetria": len(suyos)}), \
             mock.patch.object(api_sesion, "_vehiculo_propio", return_value=None), \
             mock.patch.object(api_sesion, "_fases_de", return_value=[]):
            return api_sesion.adquisiciones(SESION)

    def test_el_propio_en_la_original_y_cinco_en_el_recompletado_son_seis(self):
        propio = SESION + ":car:19"
        rivales = [SESION + ":car:%d" % i for i in (0, 3, 7, 11, 13)]
        r = self._responder([_fila("f1_25:recompletado:x:y", rivales),
                             _fila(None, [propio])])
        self.assertEqual(r["con_telemetria_en_la_sesion"], 6,
                         "se declaro la cobertura de una adquisicion y no la de la sesion")
        por_adquisicion = sorted(a["parrilla"]["con_telemetria"] for a in r["adquisiciones"])
        self.assertEqual(por_adquisicion, [1, 5],
                         "cada adquisicion tiene que seguir declarando lo suyo")

    def test_un_vehiculo_en_dos_adquisiciones_se_cuenta_una_vez(self):
        propio = SESION + ":car:19"
        r = self._responder([_fila("corrida-abc", [propio]), _fila(None, [propio])])
        self.assertEqual(r["con_telemetria_en_la_sesion"], 1)


if __name__ == "__main__":
    unittest.main()
