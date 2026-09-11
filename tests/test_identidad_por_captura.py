# -*- coding: utf-8 -*-
"""Dos capturas de la misma sesion son dos adquisiciones, no una.

EL DEFECTO QUE ESTO CUIDA. Las adquisiciones se agrupaban por `replay_run_id`, y
la captura original no lo escribe: **todas las capturas originales caian en una
sola entrada** llamada `original`. Volver a grabar sin terminar la sesion del
juego ---que es lo normal cuando se reinicia una vuelta para no perder tiempo---
producia dos capturas con el mismo `session_uid`, las dos con `replay_run_id`
nulo, indistinguibles.

LO QUE COSTABA. La reproduccion pegaba las dos y el tablero dibujaba una recta
sobre el hueco entre ellas: en la practica de Catalunya, 455,98 s de salto en
mitad de la vuelta 3, con el coche desapareciendo y reapareciendo. Y el catalogo
declaraba a la vez `duracion_s: 925,6` ---reloj de pared, hueco incluido--- y
`duracion_capturada_s: 455,771`, que es solo la primera captura.

MEDIDO el 2026-09-11 en la Pi sobre las catorce sesiones originales de F1 25:
**ocho tienen mas de una captura**. Una de ellas, `12779862468440443157`, tiene
dos capturas completas de 393,7 s y 306,8 s pegadas bajo una sola entrada.

COMO SE DISTINGUEN, SIN INVENTAR NADA. El capturador numera su desplazamiento
desde cero en cada corrida, de modo que **un reinicio de ese reloj es el
comienzo de una captura nueva**. Se lo busca recorriendo por el contador de
cuadros del juego, que es monotonico en la sesion entera y no sabe cuantas veces
se empezo a grabar.

Comprobado que no son fantasmas: en `12768529291760842921` las primeras ochenta
filas llegan con el reloj en 11.025.019 us ---una captura que ya llevaba once
segundos--- y veintidos segundos despues empieza otra en 242.046 us. Ninguna
fila carece de reloj de captura: 0 de 35.012 y 0 de 14.013 en las dos que se
inspeccionaron.

`captura_sha256` no servia: es nula en las 4.145.868 filas de la sesion.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from backend import api_sesion  # noqa: E402

T0 = datetime(2026, 9, 11, 2, 37, 59, tzinfo=timezone.utc)


def cuando(segundos: float) -> datetime:
    return T0 + timedelta(seconds=segundos)


class CursorFalso:
    """Contesta la consulta del reparto con filas escritas a mano.

    Las filas son `(replay_run_id, captura, min(timestamp), max(timestamp))`,
    que es lo que la consulta del reparto tiene que devolver una vez que
    distingue capturas.
    """

    def __init__(self, filas):
        self.filas = filas
        self.consultas: list[str] = []

    def execute(self, consulta, parametros=None):
        self.consultas.append(consulta)

    def fetchall(self):
        return list(self.filas)

    def fetchone(self):
        return self.filas[0] if self.filas else None


# Una sesion como la de Catalunya: una captura larga, un hueco de siete
# minutos y medio, y una cola de quince segundos.
DOS_CAPTURAS = [
    (None, 0, cuando(0), cuando(455.2)),
    (None, 1, cuando(911.5), cuando(926.4)),
]

UNA_SOLA = [(None, 0, cuando(0), cuando(455.2))]

CON_REPRODUCCION = [
    (None, 0, cuando(0), cuando(455.2)),
    (None, 1, cuando(911.5), cuando(926.4)),
    ("corrida-abc", 0, cuando(2000), cuando(2400)),
]


class ElRepartoDistingueCapturasTests(unittest.TestCase):

    def test_dos_capturas_originales_dan_dos_claves(self) -> None:
        reparto = api_sesion._repartir_el_reloj(
            CursorFalso(DOS_CAPTURAS), "f1_25_udp_simulation", "f1_25:session:1")
        claves = [k for k in reparto if k.startswith(api_sesion.ORIGEN_SIN_CORRIDA)]
        self.assertGreaterEqual(
            len(claves), 3,
            "las dos capturas no se distinguen: el reparto solo conoce %r" % claves)
        self.assertIn("original-1", reparto)
        self.assertIn("original-2", reparto)

    def test_cada_captura_ocupa_su_propio_tramo_y_no_el_del_hueco(self) -> None:
        """Las dos ventanas **se tocan** y no se solapan.

        El corte va a mitad de camino entre el final de una captura y el
        principio de la siguiente, igual que ya hacia el reparto entre
        adquisiciones. Que compartan el instante del corte es el diseño: los
        extremos quedan abiertos para que ninguna fila del hueco quede
        huerfana. Lo que no puede pasar es que una ventana entre en el tramo
        donde la otra tiene filas.
        """

        reparto = api_sesion._repartir_el_reloj(
            CursorFalso(DOS_CAPTURAS), "f1_25_udp_simulation", "f1_25:session:1")
        p0, p1 = reparto["original-1"]
        s0, s1 = reparto["original-2"]
        self.assertEqual(p1, s0,
                         "el reparto dejo un hueco o un solape entre las dos "
                         "capturas: %s y %s" % (p1, s0))
        # Y cada captura tiene sus propias filas dentro de su ventana.
        self.assertLess(p0, cuando(0).isoformat())
        self.assertGreater(p1, cuando(455.2).isoformat())
        self.assertLess(s0, cuando(911.5).isoformat())
        self.assertGreater(s1, cuando(926.4).isoformat())

    def test_el_corte_cae_en_el_hueco_y_no_sobre_una_captura(self) -> None:
        reparto = api_sesion._repartir_el_reloj(
            CursorFalso(DOS_CAPTURAS), "f1_25_udp_simulation", "f1_25:session:1")
        corte = reparto["original-1"][1]
        self.assertGreater(corte, cuando(455.2).isoformat(),
                           "el corte cae dentro de la primera captura")
        self.assertLess(corte, cuando(911.5).isoformat(),
                        "el corte cae dentro de la segunda captura")

    def test_original_sigue_significando_todas_las_originales(self) -> None:
        """No se rompe a quien ya pedia `original`; lo que se agrega es poder
        elegir una."""

        reparto = api_sesion._repartir_el_reloj(
            CursorFalso(DOS_CAPTURAS), "f1_25_udp_simulation", "f1_25:session:1")
        entero = reparto[api_sesion.ORIGEN_SIN_CORRIDA]
        p0, _ = reparto["original-1"]
        _, s1 = reparto["original-2"]
        self.assertEqual(entero, (p0, s1),
                         "`original` dejo de abarcar las dos capturas")

    def test_con_una_sola_captura_no_aparece_una_numeracion_inutil(self) -> None:
        reparto = api_sesion._repartir_el_reloj(
            CursorFalso(UNA_SOLA), "f1_25_udp_simulation", "f1_25:session:1")
        self.assertIn(api_sesion.ORIGEN_SIN_CORRIDA, reparto)
        self.assertNotIn("original-2", reparto)

    def test_una_reproduccion_sigue_teniendo_su_propia_clave(self) -> None:
        reparto = api_sesion._repartir_el_reloj(
            CursorFalso(CON_REPRODUCCION), "f1_25_udp_simulation", "f1_25:session:1")
        self.assertIn("corrida-abc", reparto)
        self.assertIn("original-1", reparto)
        self.assertIn("original-2", reparto)

    def test_la_consulta_busca_el_reinicio_por_el_contador_de_cuadros(self) -> None:
        """El reloj de captura dice **donde** corta; el contador de cuadros, en
        que orden mirar. Ordenar por el reloj para buscar su propio reinicio
        seria circular."""

        cursor = CursorFalso(DOS_CAPTURAS)
        api_sesion._repartir_el_reloj(cursor, "f1_25_udp_simulation", "f1_25:session:1")
        consulta = " ".join(cursor.consultas)
        self.assertIn("frame_identifier", consulta)
        self.assertIn("desplazamiento_captura_us", consulta)
        self.assertIn("lag(", consulta,
                      "no se busca el reinicio comparando cada fila con la anterior")


class LaRespuestaDeclaraQueEstaMezcladaTests(unittest.TestCase):

    def test_dos_capturas_originales_cuentan_como_dos_adquisiciones(self) -> None:
        cursor = CursorFalso(DOS_CAPTURAS)
        alcance = api_sesion._declarar_alcance(
            cursor, "f1_25_udp_simulation", "f1_25:session:1", None, None)
        self.assertEqual(
            alcance["adquisiciones_en_la_sesion"], 2,
            "la sesion declara una sola adquisicion teniendo dos capturas: "
            "quien la abra entera va a ver una carrera continua que no existe")

    def test_sin_elegir_y_con_dos_capturas_la_respuesta_avisa(self) -> None:
        cursor = CursorFalso(DOS_CAPTURAS)
        alcance = api_sesion._declarar_alcance(
            cursor, "f1_25_udp_simulation", "f1_25:session:1", None, None)
        self.assertTrue(alcance["mezclada"])
        self.assertTrue(alcance["advertencia"],
                        "no se advierte que la respuesta junta dos capturas")


class ElAlcanceSabeAcotarUnaCapturaTests(unittest.TestCase):

    def test_una_captura_se_acota_a_las_filas_sin_corrida(self) -> None:
        clausula, parametros = api_sesion._clausula_de_adquisicion("original-2")
        self.assertIn("replay_run_id IS NULL", clausula,
                      "una captura original se filtro como si fuera una "
                      "reproduccion: %r" % clausula)
        self.assertEqual(parametros, [])

    def test_una_corrida_que_empieza_como_una_captura_no_se_confunde(self) -> None:
        """Sin exigir digitos, un `replay_run_id` asi devolveria otras filas."""

        clausula, parametros = api_sesion._clausula_de_adquisicion("original-de-prueba")
        self.assertIn("replay_run_id = %s", clausula,
                      "se tomo por captura original algo que es una corrida")
        self.assertEqual(parametros, ["original-de-prueba"])

    def test_una_reproduccion_se_sigue_acotando_por_su_identificador(self) -> None:
        clausula, parametros = api_sesion._clausula_de_adquisicion("corrida-abc")
        self.assertIn("replay_run_id = %s", clausula)
        self.assertEqual(parametros, ["corrida-abc"])

    def test_todas_no_acota(self) -> None:
        self.assertEqual(api_sesion._clausula_de_adquisicion("todas"), ("", []))
        self.assertEqual(api_sesion._clausula_de_adquisicion(None), ("", []))


if __name__ == "__main__":
    unittest.main()
