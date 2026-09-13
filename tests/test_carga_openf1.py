# -*- coding: utf-8 -*-
"""La telemetria de OpenF1 entra a la base sin pasar por el intermediario.

POR QUE HACIA FALTA ESTO. Un paquete de la fuente deportiva son dos mitades. El
**contexto** ---vueltas, paradas, clima, adelantamientos--- entra por
`import_available_context` y se registra en `racing_sessions`. La **telemetria**
de cada piloto es la que hace que una sesion se pueda abrir y reproducir, y
hasta hoy no tenia forma de llegar a `telemetry_messages`: las nueve rutas que
escriben no la cargan, y el unico camino era `scripts/replay_openf1.py`, que
**publica por el intermediario** y espera que el consumidor persista.

MEDIDO EL 2026-09-13 sobre la Pi: `racing_sessions` tenia tres sesiones OpenF1
---Spa, Spielberg y Monaco--- y `telemetry_messages` una sola, la que alguien
habia cargado a mano por ese guion. Las otras dos estaban registradas y no se
podian abrir.

POR QUE INSERTA DIRECTO Y NO PUBLICA. Lo dice el docstring de
`scripts/reproducir_can.py`, que ya recorrio este camino: «una carga masiva no
tiene restriccion de tiempo real, no tiene dato que envejezca, y no hay razon
para que atraviese un canal disenado para descartar cuando el consumidor no da
abasto. El trabajo ya perdio datos dos veces por hacer eso». Lo mismo vale aqui,
y por eso esta carga usa la misma funcion de lote que el consumidor, sin
transporte.

LA IDENTIDAD INCLUYE TODO LO QUE DETERMINA LA NUMERACION. Es la leccion que el
bus pago dos veces: el numero de secuencia es un contador sobre los mensajes que
el adaptador emite, de modo que cambiar el adaptador corre toda la numeracion y
la insercion suprime coincidencias creyendo que son repeticiones.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from backend import carga_openf1  # noqa: E402

#: Una muestra de `car_data` como la entrega OpenF1, con sus seis canales.
MUESTRA_CAR = {
    "date": "2025-05-25T13:00:00.000000+00:00", "meeting_key": 1262,
    "session_key": 9979, "driver_number": 1, "speed": 210, "throttle": 99,
    "brake": 0, "rpm": 11500, "n_gear": 7, "drs": 12,
}
#: Y una de `location`, con las tres coordenadas.
MUESTRA_POS = {
    "date": "2025-05-25T13:00:00.000000+00:00", "meeting_key": 1262,
    "session_key": 9979, "driver_number": 1, "x": 100, "y": 200, "z": 30,
}


def paquete_de_prueba(destino: Path, pilotos=((1, "VER"),)) -> Path:
    """Un paquete con lo minimo: la ficha de sesion y la telemetria de un piloto."""

    destino.mkdir(parents=True, exist_ok=True)
    (destino / "session.json").write_text(json.dumps({
        "session_key": 9979, "year": 2025, "meeting_key": 1262,
        "session_name": "Race", "session_type": "Race"}), encoding="utf-8")
    for numero, sigla in pilotos:
        (destino / f"car_data_driver_{numero}_{sigla}.json").write_text(
            json.dumps([dict(MUESTRA_CAR, driver_number=numero)]), encoding="utf-8")
        (destino / f"location_driver_{numero}_{sigla}.json").write_text(
            json.dumps([dict(MUESTRA_POS, driver_number=numero)]), encoding="utf-8")
    return destino


class LoteFalso:
    """Se queda con lo que se le manda insertar, y dice cuantas filas acepto."""

    def __init__(self, acepta_todo=True):
        self.recibidos = []
        self.acepta_todo = acepta_todo

    def __call__(self, lote):
        self.recibidos.extend(lote)
        return len(lote) if self.acepta_todo else 0


class QueSeInsertaTests(unittest.TestCase):

    def setUp(self):
        self._dir = TemporaryDirectory()
        self.paquete = paquete_de_prueba(Path(self._dir.name) / "9979")

    def tearDown(self):
        self._dir.cleanup()

    def _cargar(self, **kw):
        lote = LoteFalso()
        with patch.object(carga_openf1.db, "insertar_telemetria_lote", lote):
            resultado = carga_openf1.cargar_telemetria(self.paquete, **kw)
        return resultado, lote

    def test_NO_PASA_POR_EL_INTERMEDIARIO(self) -> None:
        """La leccion que el bus ya pago: una carga masiva no se publica.

        Se comprueba sobre el modulo: si vuelve a importar un cliente de MQTT,
        alguien reabrio el camino que pierde datos bajo carga.
        """
        fuente = Path(carga_openf1.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import paho", fuente)
        self.assertNotIn("mqtt", fuente.lower().replace("intermediario", ""))

    def test_entran_las_nueve_senales_de_las_dos_familias(self) -> None:
        """Seis de `car_data` y tres de `location`, que es lo que la fuente da."""
        resultado, lote = self._cargar()
        nombres = sorted({m.signal_name for m in lote.recibidos})
        self.assertEqual(len(nombres), 9, nombres)
        self.assertIn("speed", nombres)
        self.assertIn("track_position_x", nombres)
        self.assertEqual(resultado["insertados"], 9)

    def test_cada_mensaje_declara_de_que_sesion_y_de_que_piloto_es(self) -> None:
        _, lote = self._cargar()
        for m in lote.recibidos:
            self.assertEqual(m.session_id, "openf1:session:9979")
            self.assertEqual(m.vehicle_id, "openf1:session:9979:driver:1")

    def test_LA_IDENTIDAD_DE_CORRIDA_VIAJA_CON_CADA_MENSAJE(self) -> None:
        """Sin ella no hay idempotencia: recargar duplicaria todo."""
        _, lote = self._cargar()
        corridas = {m.metadata.extra["replay_run_id"] for m in lote.recibidos}
        self.assertEqual(len(corridas), 1)
        self.assertTrue(next(iter(corridas)).startswith("openf1:cargado:9979:"))
        seqs = sorted(m.metadata.extra["replay_seq"] for m in lote.recibidos)
        self.assertEqual(seqs, list(range(9)), "la numeracion tiene huecos o repite")

    def test_LA_IDENTIDAD_CAMBIA_SI_CAMBIA_LO_QUE_NUMERA(self) -> None:
        """La leccion que el bus pago dos veces.

        El numero de secuencia cuenta los mensajes que el adaptador emite. Si el
        adaptador cambia y la identidad no, dos corridas distintas comparten
        espacio de numeros y la insercion suprime coincidencias creyendo que son
        repeticiones.
        """
        antes = carga_openf1.identidad_de_corrida(9979)
        with patch.object(carga_openf1.openf1, "CAR_DATA_SIGNALS",
                          {"speed": ("speed", "km/h")}):
            despues = carga_openf1.identidad_de_corrida(9979)
        self.assertNotEqual(antes, despues,
                            "el catalogo de senales cambio y la identidad no")

    def test_dos_sesiones_no_comparten_identidad(self) -> None:
        self.assertNotEqual(carga_openf1.identidad_de_corrida(9979),
                            carga_openf1.identidad_de_corrida(9955))

    def test_LA_NUMERACION_NO_DEPENDE_DEL_ORDEN_DEL_SISTEMA_DE_ARCHIVOS(self) -> None:
        """Si el disco decide, dos corridas numeran distinto y nada es idempotente.

        SE FUERZA EL DESORDEN. Comparar dos corridas seguidas en la misma
        maquina prueba que el resultado es estable, no que el orden sea el
        declarado: el disco devuelve lo mismo las dos veces. Aca se le da la
        vuelta a lo que `iterdir` entrega y se comprueba que la numeracion sale
        igual, que es la unica forma de ver la diferencia.
        """
        paquete = paquete_de_prueba(Path(self._dir.name) / "otro",
                                    pilotos=((44, "HAM"), (1, "VER"), (16, "LEC")))

        def numeros(al_reves):
            original = Path.iterdir
            def ordenado(self):
                hijos = sorted(original(self), key=lambda r: r.name,
                               reverse=al_reves)
                return iter(hijos)
            lote = LoteFalso()
            with patch.object(Path, "iterdir", ordenado), \
                 patch.object(carga_openf1.db, "insertar_telemetria_lote", lote):
                carga_openf1.cargar_telemetria(paquete)
            return [(m.vehicle_id, m.signal_name, m.metadata.extra["replay_seq"])
                    for m in lote.recibidos]

        self.assertEqual(numeros(False), numeros(True),
                         "el orden del disco cambio la numeracion")
        #: Y el orden declarado es por numero de piloto: el 1 va antes que el 16.
        primeros = [v for v, _, seq in numeros(True) if seq < 9]
        self.assertTrue(all("driver:1" in v for v in primeros), primeros)

    def test_un_paquete_sin_telemetria_lo_dice_y_no_inserta_nada(self) -> None:
        vacio = Path(self._dir.name) / "vacio"
        vacio.mkdir()
        (vacio / "session.json").write_text('{"session_key": 9979}', encoding="utf-8")
        lote = LoteFalso()
        with patch.object(carga_openf1.db, "insertar_telemetria_lote", lote):
            r = carga_openf1.cargar_telemetria(vacio)
        self.assertEqual(r["insertados"], 0)
        self.assertEqual(lote.recibidos, [])
        self.assertIn("telemetr", r["motivo"])

    def test_un_paquete_sin_nada_no_exige_una_ficha_para_decirlo(self) -> None:
        """Un paquete de solo contexto es una respuesta legitima, no un error.

        Se miraba `session.json` antes de saber si habia algo que cargar, de modo
        que un directorio sin ficha hacia fallar el trabajo entero en vez de
        contestar «no trae telemetria».
        """
        pelado = Path(self._dir.name) / "pelado"
        pelado.mkdir()
        lote = LoteFalso()
        with patch.object(carga_openf1.db, "insertar_telemetria_lote", lote):
            r = carga_openf1.cargar_telemetria(pelado)
        self.assertEqual(r["insertados"], 0)
        self.assertIn("telemetr", r["motivo"])

    def test_declara_de_que_pilotos_es_y_no_cuantos_archivos(self) -> None:
        """Quien lea el resumen no tiene por que saber que cada piloto trae dos
        conjuntos: derivar «tres pilotos» de «seis archivos» seria una convencion
        escrita de un solo lado."""
        paquete = paquete_de_prueba(Path(self._dir.name) / "tres",
                                    pilotos=((44, "HAM"), (1, "VER"), (16, "LEC")))
        lote = LoteFalso()
        with patch.object(carga_openf1.db, "insertar_telemetria_lote", lote):
            r = carga_openf1.cargar_telemetria(paquete)
        self.assertEqual(r["pilotos"], [1, 16, 44])
        self.assertEqual(r["archivos"], 6)

    def test_SE_PUEDE_ACOTAR_POR_PILOTO(self) -> None:
        """Una carrera son veinte pilotos y millones de muestras.

        Poder traer tres es lo que hace que esto se pueda usar sin comprometer
        media hora y varios gigabytes.
        """
        paquete = paquete_de_prueba(Path(self._dir.name) / "varios",
                                    pilotos=((1, "VER"), (16, "LEC"), (44, "HAM")))
        lote = LoteFalso()
        with patch.object(carga_openf1.db, "insertar_telemetria_lote", lote):
            carga_openf1.cargar_telemetria(paquete, pilotos=[16])
        vistos = {m.vehicle_id for m in lote.recibidos}
        self.assertEqual(vistos, {"openf1:session:9979:driver:16"})

    def test_acotar_por_un_piloto_que_no_esta_no_inventa_una_carga_vacia(self) -> None:
        lote = LoteFalso()
        with patch.object(carga_openf1.db, "insertar_telemetria_lote", lote):
            r = carga_openf1.cargar_telemetria(self.paquete, pilotos=[99])
        self.assertEqual(r["insertados"], 0)
        self.assertIn("99", r["motivo"])


class ConciliarTests(unittest.TestCase):
    """Misma pregunta que la del bus: que debe haber, no cuanto crecio.

    Se arreglo esta misma tarde en `reproducir_can.py` despues de que una
    recarga idempotente se informara como perdida de 57.890 filas. Esta carga
    nace con la pregunta ya bien formulada.
    """

    def _conciliar(self, presente, esperado, corrida="openf1:cargado:9979:ab"):
        class Cursor:
            def __init__(self): self.consultas = []
            def cursor(self): return self
            def execute(self, sql, p=None): self.consultas.append((" ".join(sql.split()), p))
            def fetchone(self): return (presente,)
            def __enter__(self): return self
            def __exit__(self, *a): return False
        c = Cursor()
        with patch.object(carga_openf1.db, "obtener_conexion", return_value=c):
            return carga_openf1.conciliar(esperado, corrida), c

    def test_una_carga_completa_concilia(self) -> None:
        r, _ = self._conciliar(presente=900, esperado=900)
        self.assertEqual((r["faltan"], r["sobran"]), (0, 0))

    def test_VOLVER_A_CARGAR_LO_MISMO_SIGUE_CONCILIANDO(self) -> None:
        """La base no crece porque ya tiene esas mediciones."""
        r, _ = self._conciliar(presente=900, esperado=900)
        self.assertEqual(r["faltan"], 0)

    def test_una_perdida_de_verdad_se_delata(self) -> None:
        r, _ = self._conciliar(presente=400, esperado=900)
        self.assertEqual(r["faltan"], 500)

    def test_lo_que_sobra_se_declara_aparte(self) -> None:
        r, _ = self._conciliar(presente=1800, esperado=900)
        self.assertEqual((r["faltan"], r["sobran"]), (0, 900))

    def test_se_cuenta_por_la_corrida_y_no_por_la_fuente(self) -> None:
        _, c = self._conciliar(presente=900, esperado=900)
        sql, parametros = c.consultas[-1]
        self.assertIn("replay_run_id", sql)
        self.assertNotIn("source_type", sql)
        self.assertEqual(parametros, ("openf1:cargado:9979:ab",))


if __name__ == "__main__":
    unittest.main()
