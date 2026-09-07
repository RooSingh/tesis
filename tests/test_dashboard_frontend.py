"""Comprobaciones de contrato del dashboard sin dependencias de navegador."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


RAIZ = Path(__file__).resolve().parents[1]
APP = RAIZ / "dashboard" / "app.js"


class DashboardFrontendTests(unittest.TestCase):
    def test_javascript_es_valido_para_el_motor_del_navegador(self) -> None:
        proceso = subprocess.run(
            ["node", "--check", str(APP)], capture_output=True, text=True,
            check=False,
        )
        self.assertEqual(proceso.returncode, 0, proceso.stderr)

    def test_los_contratos_de_escritura_coinciden_con_fastapi(self) -> None:
        codigo = APP.read_text(encoding="utf-8")
        self.assertIn('cuerpo: { session_key: sessionKey, descargar_telemetria: false }', codigo)
        self.assertIn('cuerpo: { segmentos: segmentos, plataforma: "TOYOTA_RAV4_TSS2", etapa: "cargar" }', codigo)
        self.assertIn('"?confirmar=true"', codigo)
        self.assertIn("d.capturas_cerradas", codigo)
        self.assertIn("d.borradas", codigo)
        self.assertNotIn("d.sesiones_cerradas", codigo)
        self.assertNotIn("d.filas_borradas", codigo)

    def test_no_hay_fallback_de_series_entre_vehiculos(self) -> None:
        codigo = APP.read_text(encoding="utf-8")
        self.assertNotIn("bloque.vehiculos[claveVehiculoPropio()]", codigo)
        self.assertNotIn("bloque.vehiculos[Object.keys(bloque.vehiculos)[0]]", codigo)
        self.assertNotIn("(v / 62)", codigo)


if __name__ == "__main__":
    unittest.main()
