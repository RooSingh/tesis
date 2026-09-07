"""Smoke test real del flujo principal del dashboard en Chrome."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


RAIZ = Path(__file__).resolve().parents[1]
DASHBOARD = RAIZ / "dashboard"


class ApiDashboardFalsa(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DASHBOARD), **kwargs)

    def log_message(self, _formato, *_args):
        pass

    def _json(self, cuerpo, estado=200):
        datos = json.dumps(cuerpo).encode("utf-8")
        self.send_response(estado)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def do_GET(self):  # noqa: N802 - nombre exigido por BaseHTTPRequestHandler
        pedido = urlparse(self.path)
        ruta = pedido.path
        if ruta == "/sesiones":
            return self._json({"sesiones": [{
                "session_id": "f1_25:session:prueba", "fuente": "f1_25_udp_simulation",
                "filas": 24, "senales": 2, "vehiculos": 2,
                "desde": "2026-09-07T10:00:00+00:00", "hasta": "2026-09-07T10:01:30+00:00",
                "duracion_s": 90, "procedencia": {"circuito": "Circuito de prueba"},
            }], "cantidad": 1})
        if ruta.endswith("/vueltas"):
            return self._json({"vueltas": [{"numero": 1, "muestras": 2, "desde_m": 0,
                "hasta_m": 1000, "largo_m": 1000, "duracion_s": 90,
                "desde_utc": "2026-09-07T10:00:00+00:00",
                "hasta_utc": "2026-09-07T10:01:30+00:00", "completa": True}]})
        if ruta.endswith("/series"):
            senales = parse_qs(pedido.query).get("senales", ["speed"])[0].split(",")
            vehiculo = {"distancia_m": [0, 1000], "distancia_sesion_m": [0, 1000],
                        "timestamp_utc": ["2026-09-07T10:00:00+00:00", "2026-09-07T10:01:30+00:00"]}
            vehiculo.update({s: [100, 200] for s in senales})
            segundo = dict(vehiculo)
            segundo["speed"] = [98, 198]
            return self._json({"vehiculos": {
                                   "f1_25:session:prueba:car:0": vehiculo,
                                   "f1_25:session:prueba:car:1": segundo,
                               },
                               "muestras": 2, "submuestreado": False})
        if ruta.endswith("/posiciones"):
            return self._json({"vehiculos": {"f1_25:session:prueba:car:0": [0, 1000]}})
        if ruta.endswith("/trazado"):
            return self._json({"puntos": [[0, 0], [1, 0], [1, 1]], "largo_m": 1000,
                               "desnivel_m": 5, "muestras_originales": 3})
        if ruta.endswith("/clima"):
            return self._json({"clima": {}, "motivo_ausencia": "Sin clima de prueba."})
        if ruta.endswith("/vehiculo"):
            return self._json({"esquinas": {}, "motivo_ausencia": "Sin estado de vehículo."})
        if ruta.endswith("/puesta-a-punto"):
            return self._json({"puesta_a_punto": None})
        if ruta.endswith("/avisos"):
            return self._json({"avisos": [], "motivo": "Sin avisos."})
        if ruta.startswith("/circuitos/"):
            return self._json({"curvas": []})
        if ruta == "/fuentes/matriz":
            return self._json({"fuentes": [], "magnitudes": []})
        if ruta == "/sesion/activa":
            return self._json({"estado": "cargado"})
        if ruta == "/live/status":
            return self._json({"conectado": False, "mensajes_recibidos": 0})
        if ruta == "/live/recent":
            return self._json([])
        if ruta == "/live/stream":
            self.send_response(204)
            self.end_headers()
            return
        return super().do_GET()


class DashboardBrowserTests(unittest.TestCase):
    def test_abre_el_catalogo_y_dibuja_una_sesion(self) -> None:
        chrome = shutil.which("chrome") or Path(
            r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        if not Path(chrome).is_file():
            self.skipTest("Chrome no esta instalado")
        servidor = ThreadingHTTPServer(("127.0.0.1", 0), ApiDashboardFalsa)
        servidor.daemon_threads = True
        hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
        hilo.start()
        puerto = servidor.server_address[1]
        try:
            url = f"http://127.0.0.1:{puerto}/index.html?api=http://127.0.0.1:{puerto}"
            with tempfile.TemporaryDirectory() as perfil:
                proceso = subprocess.run([
                    str(chrome), "--headless=new", "--disable-gpu", "--no-first-run",
                    "--disable-background-networking", "--disable-extensions",
                    "--user-data-dir=" + perfil, "--virtual-time-budget=3000",
                    "--dump-dom", url,
                ], capture_output=True, text=True, timeout=20, check=False)
        finally:
            servidor.shutdown()
            servidor.server_close()
        self.assertEqual(proceso.returncode, 0, proceso.stderr)
        self.assertIn("Circuito de prueba", proceso.stdout)
        self.assertIn('id="aviso-descarga"', proceso.stdout)
        self.assertIn('data-visible="si" data-error="no"', proceso.stdout)
        comparar = re.search(
            r'<button class="boton secundario" id="btn-comparar"([^>]*)>',
            proceso.stdout,
        )
        self.assertIsNotNone(comparar)
        self.assertNotIn("disabled", comparar.group(1))


if __name__ == "__main__":
    unittest.main()
