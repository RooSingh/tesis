# -*- coding: utf-8 -*-
"""Historial de sesion y posiciones por vuelta, decodificados.

Que agregan
-----------
Los demas paquetes describen **un instante** del vehiculo propio. Estos dos
describen **hechos cerrados de los veintidos**: cuanto tardo cada vuelta y cada
sector, y en que puesto iba cada auto al empezar cada vuelta.

Como se verifica una decodificacion binaria
-------------------------------------------
El significado no viaja en el paquete: vive en la especificacion del fabricante,
que ademas declara que no garantiza su exactitud. De modo que transcribir la
estructura no alcanza, y hay tres controles:

1. **el tamano**: los campos tienen que sumar el tamano que la tabla de paquetes
   declara. Con 1.460 y 1.131 bytes, un desplazamiento de una sola posicion
   ---el defecto que ya aparecio una vez--- se detecta en el acto;
2. **contra otro paquete**: el tiempo de vuelta tambien viaja en `lap_data`, por
   una via completamente distinta. Si los dos no coinciden, uno esta mal;
3. **la coherencia interna**: los tres sectores tienen que sumar la vuelta.

El tercero descubrio algo que no es un defecto: la suma queda entre cero y dos
milisegundos por debajo del tiempo de vuelta, **siempre**. Es la firma de tres
valores truncados al milisegundo, y no un error de lectura.
"""

from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from backend import f1_capture, f1_udp  # noqa: E402

CAPTURAS = RAIZ / "datasets" / "f1_25" / "capturas"


def _capturas_con(paquete: str):
    """Devuelve el historial acumulado y el ultimo paquete de posiciones."""

    for ruta in sorted(CAPTURAS.glob("*_carrera*.f1raw"), reverse=True):
        historial: dict[int, dict] = {}
        posiciones = None
        try:
            for dg in f1_capture.leer_captura(ruta):
                try:
                    d = f1_udp.decodificar(dg.carga)
                except Exception:
                    continue
                if not d.get("decodificado"):
                    continue
                if d["paquete"] == "session_history":
                    x = d["historial"]
                    historial[x["car_idx"]] = x
                elif d["paquete"] == "lap_positions":
                    posiciones = d["posiciones"]
        except Exception:
            continue
        if historial and posiciones:
            return historial, posiciones
    return None, None


class TamanoDeclarado(unittest.TestCase):
    """El primer control, y el que no depende de tener una captura."""

    def test_el_historial_suma_el_tamano_declarado(self):
        esperado = f1_udp.PAQUETES[11]["tamano"]
        calculado = (f1_udp.CABECERA_TAMANO
                     + f1_udp.SESSION_HISTORY_CABEZA_TAMANO
                     + f1_udp.LAP_HISTORY_VUELTAS * f1_udp.LAP_HISTORY_TAMANO
                     + f1_udp.TYRE_STINT_MAXIMO * f1_udp.TYRE_STINT_TAMANO)
        self.assertEqual(calculado, esperado)

    def test_las_posiciones_suman_el_tamano_declarado(self):
        """Es lo que determina cuantos vehiculos trae la matriz.

        La especificacion declara el ancho con una constante que no escribe en
        ninguna parte. El tamano la fija: con veinte o con veinticuatro no
        cerraria.
        """

        esperado = f1_udp.PAQUETES[15]["tamano"]
        calculado = (f1_udp.CABECERA_TAMANO
                     + f1_udp.LAP_POSITIONS_CABEZA_TAMANO
                     + f1_udp.LAP_POSITIONS_VUELTAS * f1_udp.VEHICULOS)
        self.assertEqual(calculado, esperado)

    def test_una_vuelta_del_historial_mide_catorce_bytes(self):
        self.assertEqual(f1_udp.LAP_HISTORY_TAMANO, 14)

    def test_una_tanda_mide_tres_bytes(self):
        self.assertEqual(f1_udp.TYRE_STINT_TAMANO, 3)


class ComposicionDeTiempos(unittest.TestCase):
    """Los sectores viajan partidos y ninguna mitad significa nada sola."""

    def test_compone_minutos_y_milisegundos(self):
        self.assertEqual(f1_udp._milisegundos(1, 23456), 83456)

    def test_sin_minutos_devuelve_los_milisegundos(self):
        self.assertEqual(f1_udp._milisegundos(0, 41428), 41428)


@unittest.skipIf(_capturas_con("session_history")[0] is None,
                 "no hay captura de carrera con estos paquetes en disco")
class ContraCapturaReal(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.historial, cls.posiciones = _capturas_con("session_history")

    def test_acumula_los_veinte_vehiculos(self):
        """El paquete describe uno por vez; la parrilla se arma acumulando."""

        self.assertGreaterEqual(len(self.historial), 20)

    def test_los_sectores_suman_la_vuelta_con_dos_milisegundos_de_holgura(self):
        """La holgura es truncamiento, no error: nunca supera los dos ms."""

        examinadas = 0
        for x in self.historial.values():
            for v in x["vueltas"]:
                if not v["lap_time_ms"]:
                    continue
                suma = v["sector1_ms"] + v["sector2_ms"] + v["sector3_ms"]
                diferencia = v["lap_time_ms"] - suma
                self.assertGreaterEqual(diferencia, 0)
                self.assertLessEqual(diferencia, 2)
                examinadas += 1
        self.assertGreater(examinadas, 0)

    def test_no_devuelve_vueltas_vacias(self):
        """El arreglo trae cien entradas y solo las primeras tienen dato.

        Sin recortar, un promedio de tiempos de vuelta incluiria decenas de
        ceros y daria cualquier cosa.
        """

        for x in self.historial.values():
            self.assertEqual(len(x["vueltas"]), x["num_vueltas"])
            self.assertLessEqual(len(x["vueltas"]), f1_udp.LAP_HISTORY_VUELTAS)

    def test_no_devuelve_tandas_vacias(self):
        for x in self.historial.values():
            self.assertEqual(len(x["tandas"]), x["num_tandas"])

    def test_la_validez_por_sector_se_expone_por_separado(self):
        """Una vuelta invalida puede tener sectores validos, y eso informa."""

        alguna = next(iter(self.historial.values()))["vueltas"][0]
        for clave in ("vuelta_valida", "sector1_valido",
                      "sector2_valido", "sector3_valido"):
            self.assertIn(clave, alguna)
            self.assertIsInstance(alguna[clave], bool)

    def test_las_posiciones_traen_una_fila_por_vuelta_declarada(self):
        self.assertEqual(len(self.posiciones["por_vuelta"]),
                         self.posiciones["num_vueltas"])

    def test_cada_fila_de_posiciones_cubre_la_parrilla(self):
        for fila in self.posiciones["por_vuelta"]:
            self.assertEqual(len(fila), f1_udp.VEHICULOS)


class CoincideConOtroPaquete(unittest.TestCase):
    """El control mas fuerte: dos vias distintas del mismo dato."""

    def test_el_tiempo_de_vuelta_coincide_con_lap_data(self):
        historial, _ = _capturas_con("session_history")
        if historial is None:
            self.skipTest("no hay captura con estos paquetes")

        # Se recorre la misma captura leyendo el tiempo por la otra via.
        ruta = None
        for candidata in sorted(CAPTURAS.glob("*_carrera*.f1raw"), reverse=True):
            ruta = candidata
            break
        self.assertIsNotNone(ruta)

        propio = None
        declarado: dict[int, int] = {}
        previa = None
        for dg in f1_capture.leer_captura(ruta):
            try:
                d = f1_udp.decodificar(dg.carga)
            except Exception:
                continue
            if not d.get("decodificado"):
                continue
            if propio is None:
                propio = d["cabecera"]["player_car_index"]
            if d["paquete"] == "lap_data":
                v = d["vehiculos"][propio]
                n = v.get("current_lap_num")
                if n != previa:
                    if previa and v.get("last_lap_time_ms"):
                        declarado[previa] = v["last_lap_time_ms"]
                    previa = n

        propio_hist = historial.get(propio)
        if not propio_hist or not declarado:
            self.skipTest("la captura no cerro ninguna vuelta")

        comparadas = 0
        for numero, ms in declarado.items():
            del_historial = next(
                (v["lap_time_ms"] for v in propio_hist["vueltas"]
                 if v["numero"] == numero), None)
            if del_historial is None:
                continue
            self.assertEqual(del_historial, ms,
                             f"la vuelta {numero} difiere entre los dos paquetes")
            comparadas += 1
        self.assertGreater(comparadas, 0)


if __name__ == "__main__":
    unittest.main()
