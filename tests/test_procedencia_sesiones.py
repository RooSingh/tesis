# -*- coding: utf-8 -*-
"""Pruebas de la procedencia de sesion: que es cada sesion, no cuanto pesa."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import procedencia_sesiones as ps


def _meta(uid, tipo="carrera", circuito="spa", duracion=100.0, archivo="a.f1raw"):
    return {
        "archivo": archivo,
        "inicio_utc": "2026-09-01T12:00:00+00:00",
        "duracion_s": duracion,
        "procedencia": {
            "session_uid": uid, "tipo_sesion": tipo, "circuito": circuito,
            "circuito_id": 7, "longitud_declarada_m": 7004,
            "modo_juego": "gran-premio", "clima": "despejado",
            "temperatura_pista_c": 38, "temperatura_aire_c": 23,
            "vueltas_totales": 22, "dificultad_ia": 44,
        },
    }


class IndiceTests(unittest.TestCase):
    def setUp(self) -> None:
        ps._CACHE = None
        self.dir = tempfile.TemporaryDirectory()
        self.ruta = Path(self.dir.name)
        self.parche = patch.object(ps, "DIRECTORIO", self.ruta)
        self.parche.start()

    def tearDown(self) -> None:
        self.parche.stop()
        self.dir.cleanup()
        ps._CACHE = None

    def _escribir(self, nombre, datos):
        (self.ruta / nombre).write_text(json.dumps(datos), encoding="utf-8")

    def test_indexa_por_session_id_y_no_por_nombre_de_archivo(self) -> None:
        """El identificador de la base es `f1_25:session:<uid>`: esa es la union."""
        self._escribir("a.meta.json", _meta(123))
        self.assertIn("f1_25:session:123", ps.indice())

    def test_traduce_el_tipo_a_su_familia(self) -> None:
        """Sprint shootout y carrera sprint son la misma familia; carrera no."""
        self._escribir("a.meta.json", _meta(1, "sprint-shootout-3"))
        self._escribir("b.meta.json", _meta(2, "clasificacion-3"))
        self._escribir("c.meta.json", _meta(3, "contrarreloj"))
        i = ps.indice()
        self.assertEqual(i["f1_25:session:1"]["familia_de_sesion"], "sprint")
        self.assertEqual(i["f1_25:session:2"]["familia_de_sesion"], "clasificacion")
        self.assertEqual(i["f1_25:session:3"]["tipo_sesion_nombre"], "Contrarreloj")

    def test_un_tipo_desconocido_no_se_inventa(self) -> None:
        """Se conserva el valor crudo y se marca la familia como otra."""
        self._escribir("a.meta.json", _meta(9, "modo-nuevo-del-juego"))
        p = ps.de("f1_25:session:9")
        self.assertEqual(p["tipo_sesion"], "modo-nuevo-del-juego")
        self.assertEqual(p["familia_de_sesion"], "otro")

    def test_dos_tramos_de_la_misma_sesion_gana_el_mas_largo(self) -> None:
        """Es el que mejor la describe; el corto puede ser un arranque fallido."""
        self._escribir("corto.meta.json", _meta(5, duracion=30.0, archivo="corto"))
        self._escribir("largo.meta.json", _meta(5, duracion=900.0, archivo="largo"))
        self.assertEqual(ps.de("f1_25:session:5")["archivo"], "largo")

    def test_una_captura_sin_uid_se_ignora_en_vez_de_romper(self) -> None:
        d = _meta(7)
        d["procedencia"].pop("session_uid")
        self._escribir("a.meta.json", d)
        self.assertEqual(ps.indice(), {})

    def test_un_archivo_ilegible_no_tumba_el_indice(self) -> None:
        (self.ruta / "roto.meta.json").write_text("{no es json", encoding="utf-8")
        self._escribir("bueno.meta.json", _meta(4))
        self.assertIn("f1_25:session:4", ps.indice())

    def test_declara_de_donde_sale_cada_ficha(self) -> None:
        """Es dato derivado del flujo, no algo escrito a mano."""
        self._escribir("a.meta.json", _meta(1))
        self.assertIn("derivado del paquete de sesion", ps.de("f1_25:session:1")["origen"])

    def test_una_sesion_desconocida_devuelve_none(self) -> None:
        self.assertIsNone(ps.de("f1_25:session:no-existe"))

    def test_el_resumen_cuenta_por_familia_y_por_circuito(self) -> None:
        self._escribir("a.meta.json", _meta(1, "carrera", "spa"))
        self._escribir("b.meta.json", _meta(2, "carrera", "monza"))
        self._escribir("c.meta.json", _meta(3, "clasificacion-3", "spa"))
        r = ps.resumen()
        self.assertEqual(r["sesiones_con_procedencia"], 3)
        self.assertEqual(r["por_familia"]["carrera"], 2)
        self.assertEqual(r["por_circuito"]["spa"], 2)

    def test_sin_directorio_devuelve_vacio_y_no_falla(self) -> None:
        with patch.object(ps, "DIRECTORIO", self.ruta / "no-existe"):
            ps._CACHE = None
            self.assertEqual(ps.indice(), {})


class ParrillaTests(unittest.TestCase):
    """Quien es cada vehiculo, y que la proyeccion no publique de mas.

    EL HUECO QUE ESTO CIERRA. El nombre del piloto estaba guardado desde el dia
    de la captura ---el paquete de participantes lo declara--- y la proyeccion
    que llegaba a la API lo dejaba afuera. El tablero terminaba usando el sufijo
    del identificador tecnico, que es el indice del vehiculo en el protocolo, y
    mostraba «19» donde tenia que decir NORRIS.
    """

    def setUp(self) -> None:
        ps._CACHE = None
        self.dir = tempfile.TemporaryDirectory()
        self.ruta = Path(self.dir.name)
        self.parche = patch.object(ps, "DIRECTORIO", self.ruta)
        self.parche.start()

    def tearDown(self) -> None:
        self.parche.stop()
        self.dir.cleanup()
        ps._CACHE = None

    def _escribir(self, nombre, datos):
        (self.ruta / nombre).write_text(json.dumps(datos), encoding="utf-8")

    def _con_parrilla(self, uid, parrilla, **extra):
        datos = _meta(uid, **extra)
        datos["procedencia"]["parrilla"] = parrilla
        datos["procedencia"]["vehiculos_en_carrera_al_leer"] = len(parrilla)
        return datos

    #: El participante 19 de la carrera de Spa, tal cual lo escribe el capturador.
    NORRIS = {"indice": 19, "nombre": "NORRIS", "numero": 4, "equipo": "McLaren",
              "equipo_id": 8, "es_ia": False, "plataforma": "PlayStation"}

    def test_el_indice_19_de_spa_es_norris_numero_4_de_mclaren(self) -> None:
        self._escribir("spa.meta.json", self._con_parrilla(1, [self.NORRIS]))
        parrilla = ps.parrilla_de("f1_25:session:1")
        self.assertEqual(parrilla["vehiculos"], [
            {"indice": 19, "nombre": "NORRIS", "numero": 4,
             "equipo": "McLaren", "es_ia": False},
        ])

    def test_no_publica_el_metadato_entero(self) -> None:
        """`equipo_id` es un codigo interno y `plataforma` describe a la persona.

        Devolver el sidecar tal cual seria mas corto de escribir y publicaria por
        descuido cualquier campo que el capturador agregue manana.
        """
        self._escribir("spa.meta.json", self._con_parrilla(1, [self.NORRIS]))
        uno = ps.parrilla_de("f1_25:session:1")["vehiculos"][0]
        self.assertNotIn("equipo_id", uno)
        self.assertNotIn("plataforma", uno)
        self.assertNotIn("archivo", ps.parrilla_de("f1_25:session:1"))

    def test_la_parrilla_no_viaja_en_la_lista_de_sesiones(self) -> None:
        """`/sesiones` adjunta la procedencia a cada una de las cuatrocientas."""
        self._escribir("spa.meta.json", self._con_parrilla(1, [self.NORRIS]))
        self.assertNotIn("parrilla", ps.de("f1_25:session:1"))

    def test_dos_capturas_con_el_mismo_indice_no_se_contaminan(self) -> None:
        """El indice es la posicion en el paquete de **esa** sesion."""
        self._escribir("a.meta.json", self._con_parrilla(1, [self.NORRIS]))
        self._escribir("b.meta.json", self._con_parrilla(2, [
            {"indice": 19, "nombre": "VERSTAPPEN", "numero": 1,
             "equipo": "Red Bull Racing", "equipo_id": 2, "es_ia": True,
             "plataforma": "desconocida"}]))
        self.assertEqual(ps.parrilla_de("f1_25:session:1")["vehiculos"][0]["nombre"],
                         "NORRIS")
        self.assertEqual(ps.parrilla_de("f1_25:session:2")["vehiculos"][0]["nombre"],
                         "VERSTAPPEN")

    def test_una_sesion_sin_parrilla_declarada_devuelve_none(self) -> None:
        self._escribir("a.meta.json", _meta(1))
        self.assertIsNone(ps.parrilla_de("f1_25:session:1"))
        self.assertIsNotNone(ps.de("f1_25:session:1"),
                             "la procedencia se sigue conociendo sin parrilla")

    def test_una_sesion_desconocida_no_inventa_una_parrilla(self) -> None:
        self.assertIsNone(ps.parrilla_de("f1_25:session:no-existe"))

    def test_una_parrilla_vacia_es_no_tenerla(self) -> None:
        self._escribir("a.meta.json", self._con_parrilla(1, []))
        self.assertIsNone(ps.parrilla_de("f1_25:session:1"))

    def test_un_participante_sin_indice_o_sin_nombre_se_descarta(self) -> None:
        """No se puede unir a ningun vehiculo, y completarlo seria inventarlo."""
        self._escribir("a.meta.json", self._con_parrilla(1, [
            {"nombre": "SIN INDICE", "numero": 5, "equipo": "X", "es_ia": True},
            {"indice": 3, "nombre": "", "numero": 6, "equipo": "Y", "es_ia": True},
            {"indice": 4, "nombre": "   ", "numero": 7, "equipo": "Y", "es_ia": True},
            self.NORRIS,
        ]))
        vehiculos = ps.parrilla_de("f1_25:session:1")["vehiculos"]
        self.assertEqual([v["indice"] for v in vehiculos], [19])

    def test_una_parrilla_que_no_es_una_lista_no_rompe_la_lectura(self) -> None:
        datos = _meta(1)
        datos["procedencia"]["parrilla"] = {"19": "NORRIS"}
        self._escribir("a.meta.json", datos)
        self.assertIsNone(ps.parrilla_de("f1_25:session:1"))
        self.assertIsNotNone(ps.de("f1_25:session:1"))

    def test_un_nombre_con_caracteres_especiales_llega_tal_cual(self) -> None:
        """Escapar aca romperia la comparacion: se escapa al mostrarlo."""
        raro = "<b>O'BRIEN</b> & Cía"
        self._escribir("a.meta.json", self._con_parrilla(1, [
            {"indice": 19, "nombre": raro, "numero": 4, "equipo": "A & B",
             "equipo_id": 1, "es_ia": False, "plataforma": "PC"}]))
        uno = ps.parrilla_de("f1_25:session:1")["vehiculos"][0]
        self.assertEqual(uno["nombre"], raro)
        self.assertEqual(uno["equipo"], "A & B")

    def test_la_captura_mas_larga_no_es_prueba_de_a_quien_pertenece_el_nombre(self) -> None:
        """Dos capturas con el mismo UID declarando gente distinta en el slot 19.

        Para describir la sesion ---circuito, tipo, clima--- alcanza con la mas
        larga: esos datos no cambian entre dos capturas de la misma sesion. La
        parrilla si cambia, y ahi «la mas larga» es una preferencia y no una
        prueba de pertenencia: preguntando solo por la sesion, no hay respuesta.
        """
        self._escribir("corta.meta.json", self._con_parrilla(
            1, [self.NORRIS], duracion=10.0, archivo="corta.f1raw"))
        largo = _meta(1, duracion=3000.0, archivo="larga.f1raw")
        largo["procedencia"]["parrilla"] = [
            {"indice": 19, "nombre": "PIASTRI", "numero": 81, "equipo": "McLaren",
             "equipo_id": 8, "es_ia": False, "plataforma": "PC"}]
        self._escribir("larga.meta.json", largo)
        self.assertEqual(ps.de("f1_25:session:1")["archivo"], "larga.f1raw")
        self.assertIsNone(ps.parrilla_de("f1_25:session:1"),
                          "se eligio la parrilla de la captura mas larga")
        self.assertEqual(len(ps.candidatas_de_parrilla("f1_25:session:1")), 2)

    def test_dos_capturas_que_declaran_lo_mismo_no_son_una_ambiguedad(self) -> None:
        """Cual sea da igual: no hay nada que elegir."""
        self._escribir("a.meta.json", self._con_parrilla(
            1, [self.NORRIS], duracion=10.0, archivo="a.f1raw"))
        self._escribir("b.meta.json", self._con_parrilla(
            1, [self.NORRIS], duracion=3000.0, archivo="b.f1raw"))
        self.assertEqual(ps.parrilla_de("f1_25:session:1")["vehiculos"][0]["nombre"],
                         "NORRIS")

    def test_la_unica_captura_que_declara_parrilla_es_la_respuesta(self) -> None:
        """Que la otra no la declare no la vuelve ambigua: hay una sola."""
        self._escribir("corta.meta.json", self._con_parrilla(
            1, [self.NORRIS], duracion=10.0, archivo="corta.f1raw"))
        self._escribir("larga.meta.json",
                       _meta(1, duracion=3000.0, archivo="larga.f1raw"))
        self.assertEqual(ps.parrilla_de("f1_25:session:1")["vehiculos"][0]["nombre"],
                         "NORRIS")

    def test_cada_candidata_lleva_con_que_atarla_a_su_adquisicion(self) -> None:
        self._escribir("a.meta.json", self._con_parrilla(1, [self.NORRIS]))
        c = ps.candidatas_de_parrilla("f1_25:session:1")[0]["captura"]
        self.assertEqual(c["inicio_utc"], "2026-09-01T12:00:00+00:00")
        self.assertEqual(c["duracion_s"], 100.0)
        self.assertIn("sha256", c)

    def test_la_huella_del_archivo_manda_sobre_la_ventana(self) -> None:
        from datetime import datetime, timezone
        cand = {"captura": {"sha256": "abc", "inicio_utc": "2026-09-01T12:00:00+00:00",
                            "duracion_s": 100.0}}
        fuera = datetime(2030, 1, 1, tzinfo=timezone.utc)
        self.assertTrue(ps.pertenece_a(cand, fuera, fuera, ["abc"]))
        self.assertFalse(ps.pertenece_a(cand, fuera, fuera, ["otra"]))

    def test_sin_huella_declarada_se_ata_por_la_ventana_de_captura(self) -> None:
        """El capturador escribe `inicio_utc` con el mismo reloj con el que entra
        la primera fila a la base. Medido en Spa: coinciden al microsegundo."""
        from datetime import datetime, timedelta, timezone
        cand = {"captura": {"sha256": None, "inicio_utc": "2026-09-01T12:00:00+00:00",
                            "duracion_s": 100.0}}
        i = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
        self.assertTrue(ps.pertenece_a(cand, i, i, []))
        self.assertTrue(ps.pertenece_a(cand, i + timedelta(seconds=50), i, []))
        self.assertFalse(ps.pertenece_a(cand, i + timedelta(seconds=400), i, []))
        self.assertFalse(ps.pertenece_a(cand, i - timedelta(seconds=400), i, []))

    def test_sin_ventana_ni_huella_no_se_ata_nada(self) -> None:
        from datetime import datetime, timezone
        cand = {"captura": {"sha256": None, "inicio_utc": None, "duracion_s": None}}
        ahora = datetime(2026, 9, 1, tzinfo=timezone.utc)
        self.assertFalse(ps.pertenece_a(cand, ahora, ahora, []))

    def test_la_parrilla_declara_que_es_una_foto(self) -> None:
        """El paquete de participantes describe un momento, no toda la sesion."""
        self._escribir("a.meta.json", self._con_parrilla(1, [self.NORRIS]))
        self.assertIn("no quien tuvo el control",
                      ps.parrilla_de("f1_25:session:1")["es_una_foto"])

    def test_declara_cuantos_vehiculos_habia_en_carrera(self) -> None:
        self._escribir("a.meta.json", self._con_parrilla(
            1, [self.NORRIS, {"indice": 0, "nombre": "PIASTRI", "numero": 81,
                              "equipo": "McLaren", "equipo_id": 8, "es_ia": True,
                              "plataforma": "desconocida"}]))
        self.assertEqual(ps.parrilla_de("f1_25:session:1")["vehiculos_en_carrera"], 2)

    def test_la_parrilla_declara_de_donde_sale(self) -> None:
        self._escribir("a.meta.json", self._con_parrilla(1, [self.NORRIS]))
        self.assertIn("participantes", ps.parrilla_de("f1_25:session:1")["origen"])


if __name__ == "__main__":
    unittest.main()
