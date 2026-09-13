# -*- coding: utf-8 -*-
"""Cada fuente lleva su prefijo, y lo desconocido no se llama OpenF1.

EL DEFECTO, VISTO EN PANTALLA el 2026-09-13. Se genero una sesion con el
generador del capitulo 8 y el tablero la abrio con **todos los paneles
vacios** ---«sin dato en este tramo» en velocidad, acelerador, freno,
direccion, guiñada---, incluso en las señales cuyo nombre coincide exactamente
con el que el panel pide. El cabezal avanzaba: «0:26.8 de 1:00.0 grabados».

LA CAUSA. `_fuente_de()` deducia la fuente del **prefijo del identificador**:

    if session_id.startswith("f1_25:"): return "f1_25_udp_simulation"
    if session_id.startswith("can:"):   return "can_real_replay"
    return "openf1_historical_replay"

La sesion del generador se llama `demo_session_01`, sin prefijo, de modo que
caia en el `return` final y **el backend la trataba como OpenF1**. Comprobado:
`/sesiones/demo_session_01/vueltas` contestaba `"fuente":
"openf1_historical_replay"` y el motivo del muestreo a 3,7 Hz, que es de la
fuente deportiva y no tiene nada que ver con un bus CAN.

POR QUE ES LA MISMA FAMILIA QUE UN DEFECTO QUE YA SE ARREGLO HOY. En el tablero
habia un `|| "can"` que hacia que cualquier fuente desconocida se llamara
«Segmento del bus · Captura de transito». Aqui el valor por omision es
«OpenF1». En los dos casos **lo desconocido recibe la afirmacion mas especifica
y mas cara de equivocar**, en lugar de recibir un «no se».

Y el `return` final es ademas un resto: cuando se escribio, los identificadores
de la fuente deportiva eran la clave numerica pelada. Hoy son
`openf1:session:9955`. O sea que ese renglon ya no sirve a quien decia servir y
solo captura a los demas.

LO QUE SE PROBO PRIMERO Y SE DESCARTO. Preguntarle el `source_type` al
catalogo, que es donde esta el dato. Parece mas correcto y es peor:
`_fuente_de()` se llama en treinta sitios, dentro de manejadores que **ya
tienen una conexion abierta**, de modo que cada llamada abriria una segunda
conexion en medio de una peticion que no la necesita. Ocho pruebas de
`test_api_sesion` lo dijeron enseguida, y tenian razon.

LA REGLA QUE SE ADOPTA, que es mas barata y alcanza: **cada fuente lleva su
prefijo**, incluido el generador, que era el unico que no lo llevaba y pasa a
llamarse `can_sim:maniobra:demo_01`. Y lo que no se reconoce se devuelve tal
cual, para que quien lo reciba pueda decir «no se» en lugar de afirmar una
fuente que nadie comprobo.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from backend import api_sesion  # noqa: E402


class LaFuenteSaleDelPrefijo(unittest.TestCase):
    """La funcion es pura: no toca la base y no puede fallar.

    EL PRIMER INTENTO FUE PEOR Y SE DESCARTO. Consultar el `source_type` al
    catalogo parece mas correcto ---ahi esta el dato--- pero `_fuente_de()` se
    llama en treinta sitios, dentro de manejadores que **ya tienen una conexion
    abierta**: cada llamada abriria una segunda conexion en medio de una
    peticion que no la necesita. Lo destaparon ocho pruebas de
    `test_api_sesion` que fallaron enseguida.

    Lo suficiente es que cada fuente lleve su prefijo, incluido el generador,
    que era el unico que no lo llevaba.
    """

    # ---- el caso visto en pantalla ----

    def test_una_sesion_generada_no_se_confunde_con_openf1(self) -> None:
        """El defecto entero: la maniobra generada se trataba como OpenF1."""

        self.assertEqual(
            api_sesion._fuente_de("can_sim:maniobra:demo_01"), "can_simulated",
            "la sesion generada se sigue tratando como OpenF1, y por eso todos "
            "los paneles salen vacios")

    def test_el_prefijo_del_generador_no_pisa_al_del_bus_real(self) -> None:
        """`can_sim:` y `can:` se parecen: que no se confundan."""

        self.assertEqual(api_sesion._fuente_de("can:segmento:sample_01"),
                         "can_real_replay")
        self.assertEqual(api_sesion._fuente_de("can_sim:maniobra:demo_01"),
                         "can_simulated")

    # ---- y lo de siempre sigue andando ----

    def test_las_cuatro_fuentes_reales_se_reconocen(self) -> None:
        for sesion, fuente in (
                ("f1_25:session:10702872875127733007", "f1_25_udp_simulation"),
                ("openf1:session:9955", "openf1_historical_replay"),
                ("can:segmento:sample_01", "can_real_replay"),
                ("can_sim:maniobra:demo_01", "can_simulated")):
            self.assertEqual(api_sesion._fuente_de(sesion), fuente, sesion)

    def test_no_toca_la_base(self) -> None:
        """Si vuelve a consultar, esta prueba lo dice antes que ocho ajenas."""

        with patch.object(api_sesion.db, "obtener_conexion",
                          side_effect=AssertionError("_fuente_de abrio una conexion")):
            self.assertEqual(api_sesion._fuente_de("f1_25:session:9"),
                             "f1_25_udp_simulation")

    def test_una_clave_numerica_pelada_sigue_siendo_openf1(self) -> None:
        """Eso SI es una regla: `9939` es como OpenF1 nombra sus sesiones.

        Lo que estaba mal no era reconocerla, era que el mismo renglon
        capturaba **todo** lo que no se reconocia y lo afirmaba igual.
        """

        self.assertEqual(api_sesion._fuente_de("9939"),
                         "openf1_historical_replay")

    # ---- lo desconocido no recibe una afirmacion ----

    def test_lo_desconocido_deja_de_llamarse_openf1(self) -> None:
        """El renglon que capturaba todo lo que no reconocia.

        Cuando se escribio, los identificadores de la fuente deportiva eran la
        clave numerica pelada y ese `return` los servia. Hoy son
        `openf1:session:...`: ya no sirve a quien decia servir, y sigue
        afirmando «OpenF1» sobre cualquier cosa que aparezca.
        """

        self.assertNotEqual(
                api_sesion._fuente_de("algo_que_nadie_conoce"),
                "openf1_historical_replay",
                "una sesion desconocida y sin catalogar se sigue afirmando "
                "como OpenF1, que es la afirmacion mas cara de equivocar")


if __name__ == "__main__":
    unittest.main()
