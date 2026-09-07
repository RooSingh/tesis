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


if __name__ == "__main__":
    unittest.main()
