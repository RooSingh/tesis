# -*- coding: utf-8 -*-
"""El alcance ---adquisicion y fase--- resuelto una vez y barato.

CRITERIO. No se comprueba que PostgreSQL sepa agrupar: se comprueba **lo que
este modulo decide**. Que reparta el reloj sin dejar huecos, que no vuelva a
preguntar lo que ya pregunto, y que dos aperturas simultaneas no paguen dos
veces la misma resolucion. Las tres cosas se rompieron de verdad esta jornada.
"""

from __future__ import annotations

import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from backend import api_sesion


def _t(segundos: float) -> datetime:
    """Un instante, contado desde una base fija y arbitraria."""
    return datetime(2026, 9, 5, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=segundos)


class CursorConGuion:
    """Devuelve, en orden, lo que se le indique, y recuerda que se le pidio."""

    def __init__(self, respuestas: list[list]):
        self.respuestas = list(respuestas)
        self.consultas: list[str] = []
        self._ultimo: list = []

    def execute(self, consulta, parametros=None):
        self.consultas.append(consulta)
        self._ultimo = self.respuestas.pop(0) if self.respuestas else []

    def fetchall(self):
        return list(self._ultimo)

    def fetchone(self):
        return self._ultimo[0] if self._ultimo else None


class RepartoDelRelojTests(unittest.TestCase):
    """Las ventanas de las adquisiciones parten el reloj sin dejar huecos."""

    def setUp(self) -> None:
        api_sesion._ALCANCE_CACHE.clear()

    def _reparto(self, tramos):
        return api_sesion._repartir_el_reloj(CursorConGuion([tramos]), "f", "s")

    def test_los_extremos_quedan_abiertos(self) -> None:
        """Una fila de otra senal puede caer antes o despues de `lap_number`.

        Acotar a los extremos medidos sobre una sola senal recortaria las otras
        112. La primera adquisicion empieza en `-infinity` y la ultima termina
        en `infinity`: asi no se pierde ninguna fila.
        """
        r = self._reparto([(None, _t(10), _t(20)),
                           ("replay_a", _t(100), _t(110))])
        self.assertEqual(r["original"][0], "-infinity")
        self.assertEqual(r["replay_a"][1], "infinity")

    def test_el_corte_va_a_mitad_de_camino(self) -> None:
        """Entre el final de una adquisicion y el principio de la siguiente."""
        r = self._reparto([(None, _t(10), _t(20)),
                           ("replay_a", _t(100), _t(110))])
        medio = _t(60).isoformat()          # (20 + 100) / 2
        self.assertEqual(r["original"][1], medio)
        self.assertEqual(r["replay_a"][0], medio)

    def test_las_ventanas_se_tocan_y_no_dejan_hueco(self) -> None:
        """El final de una es exactamente el principio de la siguiente."""
        r = self._reparto([(None, _t(0), _t(10)),
                           ("a", _t(50), _t(60)),
                           ("b", _t(200), _t(300))])
        self.assertEqual(r["original"][1], r["a"][0])
        self.assertEqual(r["a"][1], r["b"][0])

    def test_una_sola_adquisicion_no_acota_nada(self) -> None:
        """Sin vecinos, la ventana es todo el reloj."""
        r = self._reparto([(None, _t(0), _t(10))])
        self.assertEqual(r["original"], ("-infinity", "infinity"))

    def test_una_adquisicion_que_no_esta_es_un_404(self) -> None:
        cursor = CursorConGuion([[(None, _t(0), _t(10))]])
        with self.assertRaises(HTTPException) as caso:
            api_sesion._ventana_de_alcance(cursor, "f", "s", "no_existe")
        self.assertEqual(caso.exception.status_code, 404)

    def test_sin_adquisicion_no_hay_ventana_ni_consulta(self) -> None:
        """Por omision se devuelve todo junto: no se paga por preguntarlo."""
        cursor = CursorConGuion([])
        self.assertIsNone(api_sesion._ventana_de_alcance(cursor, "f", "s", None))
        self.assertIsNone(api_sesion._ventana_de_alcance(cursor, "f", "s", "todas"))
        self.assertEqual(cursor.consultas, [])


class MemoriaDelAlcanceTests(unittest.TestCase):
    """Resolverlo una vez, no seis.

    Al abrir el tablero salen seis consultas y las seis necesitan el mismo
    alcance. Medido sobre Spa: la ventana por adquisicion, tomada sobre las 113
    senales, tarda 18,04 s. Repetirla seis veces era el costo de la apertura.
    """

    def setUp(self) -> None:
        api_sesion._ALCANCE_CACHE.clear()

    def test_lo_resuelto_se_reutiliza(self) -> None:
        veces = []
        for _ in range(5):
            api_sesion._memorizado(("p",), lambda: veces.append(1) or "v")
        self.assertEqual(len(veces), 1)

    def test_cada_clave_es_suya(self) -> None:
        api_sesion._memorizado(("a",), lambda: "primera")
        self.assertEqual(api_sesion._memorizado(("b",), lambda: "segunda"), "segunda")
        self.assertEqual(api_sesion._memorizado(("a",), lambda: "otra"), "primera")

    def test_caduca(self) -> None:
        """Una sesion que se esta capturando crece: lo guardado envejece."""
        clave = ("p",)
        api_sesion._memorizado(clave, lambda: "vieja")
        instante, valor = api_sesion._ALCANCE_CACHE[clave]
        api_sesion._ALCANCE_CACHE[clave] = (
            instante - api_sesion.VIGENCIA_DEL_ALCANCE_S - 1, valor)
        self.assertEqual(api_sesion._memorizado(clave, lambda: "nueva"), "nueva")

    def test_seis_a_la_vez_lo_resuelven_una_sola_vez(self) -> None:
        """Guardar el resultado no alcanzaba: las seis fallaban la cache juntas.

        Sin cerrojo, las seis consultas de una apertura resolvian el mismo
        alcance en paralelo contra la misma base. Medido: `/vueltas` y
        `/contexto` pasaron de 3,1 y 2,6 s ---de a una--- a agotar los 30 s de
        espera del navegador, y no se dibujo nada.
        """
        veces = []
        arrancar = threading.Event()

        def calcular():
            veces.append(1)
            time.sleep(0.05)
            return "v"

        def hilo():
            arrancar.wait()
            api_sesion._memorizado(("comun",), calcular)

        hilos = [threading.Thread(target=hilo) for _ in range(6)]
        for h in hilos:
            h.start()
        arrancar.set()
        for h in hilos:
            h.join()
        self.assertEqual(len(veces), 1)

    def test_no_crece_sin_limite(self) -> None:
        for i in range(api_sesion.ALCANCES_EN_CACHE + 20):
            api_sesion._memorizado(("k", i), lambda: i)
        self.assertLessEqual(len(api_sesion._ALCANCE_CACHE),
                             api_sesion.ALCANCES_EN_CACHE)


class FasesDeTodasTests(unittest.TestCase):
    """Las fases de las tres adquisiciones, en dos consultas y no en seis."""

    def setUp(self) -> None:
        api_sesion._ALCANCE_CACHE.clear()

    def test_agrupa_los_cortes_por_adquisicion(self) -> None:
        cursor = CursorConGuion([
            [(None, 200), (None, 300)],                       # cortes del reloj
            [(None, 0, 1000), ("replay_a", 5000, 6000)],      # extremos
        ])
        fases = api_sesion._medir_fases_de_todas(cursor, "f", "s")
        self.assertEqual([f["orden"] for f in fases["original"]], [1, 2, 3])
        self.assertEqual(fases["original"][0]["desde_us"], 0)
        self.assertEqual(fases["original"][2]["hasta_us"], 1000)
        # La que no tiene reinicios tiene una sola fase.
        self.assertEqual(len(fases["replay_a"]), 1)

    def test_solo_la_primera_fase_no_reinicia_el_reloj(self) -> None:
        cursor = CursorConGuion([[(None, 200)], [(None, 0, 1000)]])
        fases = api_sesion._medir_fases_de_todas(cursor, "f", "s")["original"]
        self.assertFalse(fases[0]["reloj_del_juego_reinicia_al_entrar"])
        self.assertTrue(fases[1]["reloj_del_juego_reinicia_al_entrar"])

    def test_dos_consultas_para_todas_las_adquisiciones(self) -> None:
        cursor = CursorConGuion([
            [(None, 200)],
            [(None, 0, 1000), ("a", 2000, 3000), ("b", 4000, 5000)],
        ])
        api_sesion._medir_fases_de_todas(cursor, "f", "s")
        self.assertEqual(len(cursor.consultas), 2)

    def test_una_adquisicion_sin_reloj_de_captura_no_inventa_fases(self) -> None:
        cursor = CursorConGuion([[], [("a", None, None)]])
        self.assertEqual(api_sesion._medir_fases_de_todas(cursor, "f", "s")["a"], [])


class ClausulaDeAdquisicionTests(unittest.TestCase):
    """El filtro exacto del que se deriva la ventana."""

    def test_el_original_es_el_que_no_declara_reproduccion(self) -> None:
        cond, par = api_sesion._clausula_de_adquisicion("original")
        self.assertIn("replay_run_id IS NULL", cond)
        self.assertEqual(par, [])

    def test_una_reproduccion_se_filtra_por_su_identificador(self) -> None:
        cond, par = api_sesion._clausula_de_adquisicion("corrida_7")
        self.assertIn("replay_run_id = %s", cond)
        self.assertEqual(par, ["corrida_7"])

    def test_por_omision_no_filtra(self) -> None:
        for pedido in (None, "", "todas"):
            self.assertEqual(api_sesion._clausula_de_adquisicion(pedido), ("", []))


class RelojDeLasFasesTests(unittest.TestCase):
    """Las fases se acotan por el reloj de captura, nunca por UTC."""

    def test_lee_la_columna_y_el_metadato(self) -> None:
        """La columna se agrego despues: las capturas viejas lo llevan dentro.

        Mirar solo la columna dejaria al original de Spa sin reloj de captura,
        que es justamente el que separa formacion de carrera.
        """
        expresion = api_sesion._captura_us()
        self.assertIn("desplazamiento_captura_us", expresion)
        self.assertIn("metadata", expresion)
        self.assertIn("COALESCE", expresion)

    def test_una_fase_que_no_existe_se_rechaza_diciendo_cuales_hay(self) -> None:
        with patch.object(api_sesion, "_fases_de",
                          return_value=[{"orden": 1}, {"orden": 2}]):
            with self.assertRaises(HTTPException) as caso:
                api_sesion._limites_de_fase(MagicMock(), "f", "s", "original", 9)
        self.assertEqual(caso.exception.status_code, 422)
        self.assertEqual(caso.exception.detail["fases_disponibles"], [1, 2])

    def test_sin_fase_no_hay_limites(self) -> None:
        self.assertEqual(
            api_sesion._limites_de_fase(MagicMock(), "f", "s", "original", None),
            (None, None))


if __name__ == "__main__":
    unittest.main()
