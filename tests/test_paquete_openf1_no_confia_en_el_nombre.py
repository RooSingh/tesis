# -*- coding: utf-8 -*-
"""Un archivo que ya esta no es lo mismo que un archivo que sirve.

EL DEFECTO QUE ESTO CUIDA, y es uno que ya ocurrio. `descargar_paquete_openf1`
es reanudable: una descarga cortada por la red no obliga a empezar de nuevo.
Para eso preguntaba `if salida.is_file()` y anotaba «ya estaba». Decide **por el
nombre del archivo y no por su contenido**, y esa distincion no es teorica.

MEDIDO el 2026-09-13 al intentar rescatar el paquete de la sesion 9939, que una
prueba de subida habia sobrescrito el dia anterior. De los ~60 MB quedaban dos
archivos, y los dos mentian:

    session.json   {"session_key": 9939, "year": 2025}
    drivers.json   []

El guion informo «ya estaba» para los dos y no los volvio a pedir. Si la API de
OpenF1 no hubiera estado cerrada esa tarde, el rescate habria bajado los once
archivos de contexto, **habria informado exito**, y habria dejado la sesion
afirmando para siempre que no corrio nadie. Un exito informado sobre datos
falsos es peor que un fallo: el fallo se mira.

EL `[]` ES EL PELIGROSO, Y NO POR SU TAMAÑO. No dice «no se quienes corrieron».
Dice «no corrio nadie». Es la misma familia que `Number(null)` dando cero donde
el cero es un valor legitimo.

LO QUE ESTA GUARDA **NO** HACE, y es a proposito. No declara que una lista vacia
sea invalida. Una sesion de entrenamientos puede no tener adelantamientos y una
sesion corta puede no tener paradas: exigir contenido obligaria a volver a pedir
para siempre algo que de verdad esta vacio, y eso son consultas contra una API
publica y gratuita que no se justifican. La distincion la da la **procedencia**:
un vacio que este guion declara haber bajado se respeta; un vacio que apareció
sin que nadie declare haberlo bajado, no.

LOS CAMPOS EXIGIDOS A `session.json` SE MIDIERON, NO SE INVENTARON. Los dos
paquetes sanos que hay en disco ---9947 y 9955--- traen exactamente los mismos
quince campos no nulos. Se exigen tres de esos quince, los que hacen que un
objeto **sea** una sesion y no una ficha con un numero adentro. Exigir los
quince seria atarse a que OpenF1 no agregue ni saque ninguno nunca.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from scripts import descargar_paquete_openf1 as guion  # noqa: E402

#: Un `session.json` como los que OpenF1 devuelve de verdad, recortado a lo que
#: importa aqui. Tomado de `datasets/OpenF1/raw/2025/9955/session.json`.
SESION_DE_VERDAD = {
    "session_key": 9939, "session_type": "Race", "session_name": "Race",
    "date_start": "2025-06-29T13:00:00+00:00",
    "date_end": "2025-06-29T15:00:00+00:00",
    "meeting_key": 1264, "circuit_key": 19, "circuit_short_name": "Spielberg",
    "country_key": 17, "country_code": "AUT", "country_name": "Austria",
    "location": "Spielberg", "gmt_offset": "02:00:00", "year": 2025,
    "is_cancelled": False,
}

#: Lo que de verdad quedo en disco tras la prueba que piso el paquete.
SESION_DE_MENTIRA = {"session_key": 9939, "year": 2025}


class FuenteFalsa:
    """Cuenta a quien se le pidio algo, para poder afirmar que no se pidio."""

    def __init__(self, respuestas: dict | None = None) -> None:
        self.pedidos: list[str] = []
        self.respuestas = respuestas or {}

    def __call__(self, endpoint, parametros, ultimo):
        self.pedidos.append(endpoint)
        if endpoint in self.respuestas:
            return self.respuestas[endpoint], {}
        if endpoint == "sessions":
            return [SESION_DE_VERDAD], {}
        return [{"fila": 1}], {}


class GuardaDeProcedencia(unittest.TestCase):

    def setUp(self) -> None:
        self.temporal = tempfile.TemporaryDirectory()
        self.destino = Path(self.temporal.name) / "9939"
        self.destino.mkdir(parents=True)
        self.fuente = FuenteFalsa()
        self.original = guion.fetch_openf1
        guion.fetch_openf1 = self.fuente

    def tearDown(self) -> None:
        guion.fetch_openf1 = self.original
        self.temporal.cleanup()

    def _escribir(self, nombre: str, contenido) -> None:
        (self.destino / nombre).write_text(json.dumps(contenido), encoding="utf-8")

    def _correr(self) -> dict:
        return guion.descargar_paquete(9939, self.destino)

    def _estado_de(self, manifiesto: dict, archivo: str) -> str:
        for registro in manifiesto["archivos"]:
            if registro["archivo"] == archivo:
                return registro["estado"]
        raise AssertionError("el manifiesto no menciona %s" % archivo)

    # ---- session.json ----

    def test_una_ficha_con_un_numero_adentro_no_es_una_sesion(self) -> None:
        """El caso exacto del 9939: se vuelve a pedir en vez de darlo por bueno."""

        self._escribir("session.json", SESION_DE_MENTIRA)
        manifiesto = self._correr()
        self.assertIn(
            "sessions", self.fuente.pedidos,
            "no se volvio a pedir `sessions`: un objeto con `session_key` y "
            "`year` y nada mas se dio por un paquete bueno")
        guardado = json.loads((self.destino / "session.json").read_text())
        self.assertEqual(
            guardado["circuit_short_name"], "Spielberg",
            "el archivo en disco sigue siendo el que mentia")
        self.assertNotEqual(self._estado_de(manifiesto, "session.json"), "ya estaba")

    def test_una_sesion_completa_no_se_vuelve_a_pedir(self) -> None:
        """La reanudabilidad sigue existiendo: esto no es volver a bajar todo."""

        self._escribir("session.json", SESION_DE_VERDAD)
        manifiesto = self._correr()
        self.assertNotIn(
            "sessions", self.fuente.pedidos,
            "se volvio a pedir una sesion que ya estaba completa: la guarda "
            "rompio la reanudabilidad, que es lo que venia a proteger")
        self.assertEqual(self._estado_de(manifiesto, "session.json"), "ya estaba")

    def test_un_json_roto_no_cuenta_como_que_ya_estaba(self) -> None:
        (self.destino / "session.json").write_text("{esto no es", encoding="utf-8")
        self._correr()
        self.assertIn("sessions", self.fuente.pedidos,
                      "un archivo ilegible se dio por bueno")

    def test_una_lista_donde_iba_un_objeto_no_cuenta(self) -> None:
        """OpenF1 contesta una lista; el importador exige el objeto de adentro."""

        self._escribir("session.json", [SESION_DE_VERDAD])
        self._correr()
        self.assertIn("sessions", self.fuente.pedidos,
                      "se acepto una lista donde el importador espera un objeto")

    # ---- los contextos, y el vacio ----

    def test_un_vacio_que_nadie_declara_haber_bajado_se_vuelve_a_pedir(self) -> None:
        """El `drivers.json` con `[]` que afirmaba que no corrio nadie."""

        self._escribir("session.json", SESION_DE_VERDAD)
        self._escribir("drivers.json", [])
        self._correr()
        self.assertIn(
            "drivers", self.fuente.pedidos,
            "un `[]` sin procedencia se dio por bueno: la sesion habria quedado "
            "diciendo que no corrio nadie")

    def test_un_vacio_con_procedencia_se_respeta(self) -> None:
        """Una sesion sin adelantamientos no se vuelve a pedir para siempre.

        Esta es la prueba que evita que la guarda se pase de celosa y queme
        consultas contra una API publica cada vez que alguien corra el guion.
        """

        self._escribir("session.json", SESION_DE_VERDAD)
        self._escribir("overtakes.json", [])
        self._escribir("manifiesto_contexto.json", {
            "session_key": 9939,
            "archivos": [{"archivo": "overtakes.json", "estado": "descargado",
                          "filas": 0}],
        })
        self._correr()
        self.assertNotIn(
            "overtakes", self.fuente.pedidos,
            "se volvio a pedir un vacio que este guion declara haber bajado: "
            "una sesion sin adelantamientos costaria consultas en cada corrida")

    def test_un_contexto_con_datos_no_se_vuelve_a_pedir(self) -> None:
        self._escribir("session.json", SESION_DE_VERDAD)
        self._escribir("laps.json", [{"lap_number": 1}])
        manifiesto = self._correr()
        self.assertNotIn("laps", self.fuente.pedidos)
        self.assertEqual(self._estado_de(manifiesto, "laps.json"), "ya estaba")

    def test_un_contexto_roto_se_vuelve_a_pedir(self) -> None:
        self._escribir("session.json", SESION_DE_VERDAD)
        (self.destino / "weather.json").write_text("[[[", encoding="utf-8")
        self._correr()
        self.assertIn("weather", self.fuente.pedidos)

    def test_un_objeto_donde_iba_una_lista_se_vuelve_a_pedir(self) -> None:
        self._escribir("session.json", SESION_DE_VERDAD)
        self._escribir("pit.json", {"no": "soy una lista"})
        self._correr()
        self.assertIn("pit", self.fuente.pedidos)

    # ---- que el manifiesto siga diciendo la verdad ----

    def test_el_manifiesto_distingue_lo_rehecho_de_lo_conservado(self) -> None:
        self._escribir("session.json", SESION_DE_VERDAD)
        self._escribir("laps.json", [{"lap_number": 1}])
        self._escribir("drivers.json", [])
        manifiesto = self._correr()
        self.assertEqual(self._estado_de(manifiesto, "laps.json"), "ya estaba")
        self.assertEqual(self._estado_de(manifiesto, "drivers.json"), "descargado")

    def test_el_caso_real_del_9939_entero(self) -> None:
        """Los dos archivos que quedaron, tal cual estaban en disco."""

        self._escribir("session.json", SESION_DE_MENTIRA)
        self._escribir("drivers.json", [])
        self._correr()
        ficha = json.loads((self.destino / "session.json").read_text())
        pilotos = json.loads((self.destino / "drivers.json").read_text())
        self.assertIn("session_type", ficha,
                      "la sesion sigue sin decir que clase de sesion es")
        self.assertTrue(pilotos, "la sesion sigue afirmando que no corrio nadie")


if __name__ == "__main__":
    unittest.main()
