"""Smoke test real del flujo principal del dashboard en Chrome."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import time
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


RAIZ = Path(__file__).resolve().parents[1]
DASHBOARD = RAIZ / "dashboard"


def chrome_disponible() -> Path | None:
    candidatos = [
        shutil.which("chrome"),
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    ]
    return next((Path(ruta) for ruta in candidatos if ruta and Path(ruta).is_file()), None)


def volcar_dom(chrome: Path, url: str, perfil: str, presupuesto_ms: int) -> str:
    comando = [
        str(chrome), "--headless=new", "--disable-gpu", "--no-first-run",
        "--disable-background-networking", "--disable-extensions",
        "--user-data-dir=" + perfil, f"--virtual-time-budget={presupuesto_ms}",
        "--dump-dom", url,
    ]
    try:
        proceso = subprocess.run(
            comando, capture_output=True, text=True, timeout=10, check=False)
    except subprocess.TimeoutExpired as error:
        # Chrome en macOS vuelca el DOM pero puede conservar procesos auxiliares.
        if not error.stdout:
            raise
        return error.stdout.decode() if isinstance(error.stdout, bytes) else error.stdout
    if proceso.returncode != 0:
        raise AssertionError(proceso.stderr)
    return proceso.stdout


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
            # LAS SERIES CONTESTAN ULTIMAS, A PROPOSITO.
            #
            # Las series traen dos vehiculos y las posiciones, uno. Con las
            # posiciones ganando la carrera, el tablero armaba la lista con ese
            # uno y ya no la ampliaba: quedaba conociendo un vehiculo de los dos
            # que tenia el dato en la mano, y «Comparar pilotos» apagado. Se
            # veia como una prueba intermitente ---fallaba una de cada veinte
            # corridas--- porque dependia de cual respuesta llegara primero.
            # Con este retardo el orden malo es el unico posible, y la prueba
            # cubre el caso en vez de tropezarselo de vez en cuando.
            time.sleep(0.15)
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
        if ruta.endswith("/adquisiciones"):
            # Una sola adquisicion: la sesion no esta mezclada y el tablero
            # sigue de largo. El caso mezclado tiene su propia prueba.
            return self._json({
                "adquisiciones": [{"clave": "original", "replay_run_id": None,
                                    "es_reproduccion": False,
                                    "muestras_de_vuelta": 100, "vehiculos": 1,
                                    "desde_utc": None, "hasta_utc": None,
                                    "fases": [{"orden": 1, "desde_us": 0,
                                                "hasta_us": 1000}]}],
                "mezclada": False})
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


class ApiDashboardCanFalsa(ApiDashboardFalsa):
    """Contrato minimo de una captura temporal sin vueltas ni metros."""

    def do_GET(self):  # noqa: N802 - nombre exigido por BaseHTTPRequestHandler
        pedido = urlparse(self.path)
        ruta = pedido.path
        if ruta == "/sesiones":
            return self._json({"sesiones": [{
                "session_id": "can:segmento:sample_01", "fuente": "can_real_replay",
                "filas": 12, "senales": 3, "vehiculos": 1,
                "desde": "2026-09-09T12:00:00+00:00",
                "hasta": "2026-09-09T12:01:00+00:00", "duracion_s": 60,
            }], "cantidad": 1})
        if ruta.endswith("/adquisiciones"):
            return self._json({"adquisiciones": [], "mezclada": False})
        if ruta.endswith("/vueltas"):
            return self._json({"vueltas": [], "motivo": "Sin distancia medida."})
        if ruta.endswith("/series-tiempo"):
            senales = parse_qs(pedido.query).get("senales", ["speed"])[0].split(",")
            vehiculo = {
                "tiempo_s": [0, 60],
                "timestamp_utc": ["2026-09-09T12:00:00+00:00",
                                  "2026-09-09T12:01:00+00:00"],
            }
            vehiculo.update({senal: [0, 1] if "pressed" in senal else [100, 110]
                              for senal in senales})
            return self._json({
                "vehiculos": {"can:sample_01": vehiculo},
                "unidades": {senal: ("bool" if "pressed" in senal else "km/h")
                              for senal in senales},
                "muestras": 2, "puntos_pedidos": 1200, "submuestreado": False,
                "duracion_s": 60, "eje": "tiempo desde el inicio del tramo, en segundos",
            })
        return super().do_GET()


class DashboardBrowserTests(unittest.TestCase):
    def test_abre_el_catalogo_y_dibuja_una_sesion(self) -> None:
        chrome = chrome_disponible()
        if chrome is None:
            self.skipTest("Chrome no esta instalado")
        servidor = ThreadingHTTPServer(("127.0.0.1", 0), ApiDashboardFalsa)
        servidor.daemon_threads = True
        hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
        hilo.start()
        puerto = servidor.server_address[1]
        try:
            url = f"http://127.0.0.1:{puerto}/index.html?api=http://127.0.0.1:{puerto}"
            with tempfile.TemporaryDirectory() as perfil:
                dom = volcar_dom(chrome, url, perfil, 3000)
        finally:
            servidor.shutdown()
            servidor.server_close()
        self.assertIn("Circuito de prueba", dom)
        self.assertIn('id="aviso-descarga"', dom)
        # QUE EL AVISO **DIGA** LO QUE CORRESPONDE, NO QUE SIGA EN PANTALLA.
        #
        # Antes se exigia `data-visible="si"`, y eso es una carrera contra el
        # temporizador que lo esconde a los 4,2 s. El volcado ocurre cuando se
        # agota `--virtual-time-budget`, que **no** es un reloj fiable para
        # esto: medido, con 3.000 ms el aviso aparecia visible 8 de 8 veces y
        # con 6.000, 0 de 8; y con la maquina cargada, el mismo presupuesto de
        # 3.000 fallaba 3 de 12 porque el tiempo virtual se adelanta cuando hay
        # tareas reales pendientes. La prueba fallaba sin que el tablero se
        # portara mal.
        #
        # Lo que importa es que la apertura **se anuncie**, y el texto lo
        # demuestra igual: solo lo escribe `avisar()`, y sobrevive a que el
        # aviso se esconda. La condicion de error si es estable.
        aviso = re.search(r'id="aviso-descarga"[^>]*data-error="(\w+)"[^>]*>([^<]*)<',
                          dom)
        self.assertIsNotNone(aviso, "no esta el aviso en el DOM")
        self.assertEqual(aviso.group(1), "no", "la apertura se anuncio como error")
        self.assertIn("Circuito de prueba", aviso.group(2),
                      "la apertura no se anuncio: el aviso quedo vacio")
        comparar = re.search(
            r'<button class="boton secundario" id="btn-comparar"([^>]*)>',
            dom,
        )
        self.assertIsNotNone(comparar)
        self.assertNotIn("disabled", comparar.group(1))

    def test_can_reproduce_el_tramo_por_tiempo_sin_pedir_una_vuelta(self) -> None:
        chrome = chrome_disponible()
        if chrome is None:
            self.skipTest("Chrome no esta instalado")
        servidor = ThreadingHTTPServer(("127.0.0.1", 0), ApiDashboardCanFalsa)
        servidor.daemon_threads = True
        hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
        hilo.start()
        puerto = servidor.server_address[1]
        try:
            url = (f"http://127.0.0.1:{puerto}/index.html"
                   f"?api=http://127.0.0.1:{puerto}"
                   "&sesion=can%3Asegmento%3Asample_01")
            with tempfile.TemporaryDirectory() as perfil:
                dom = volcar_dom(chrome, url, perfil, 4000)
        finally:
            servidor.shutdown()
            servidor.server_close()

        self.assertIn("Reproducción temporal de CAN real", dom)
        self.assertIn("20 s", dom)
        self.assertRegex(dom, r'<html[^>]+data-fuente="can"')
        self.assertIn('aria-label="Velocidad a lo largo del tiempo"', dom)
        self.assertNotIn("La vuelta 1 no se pudo traer", dom)

        # Dos paneles que el bus no puede llenar nunca salen del tablero, y la
        # marca la pone el guion.
        for panel in ("puesta", "vehiculos"):
            seccion = re.search(rf'<section[^>]*data-panel="{panel}"[^>]*>', dom)
            self.assertIsNotNone(seccion, f"no esta la seccion de «{panel}»")
            self.assertIn('data-fuera="si"', seccion.group(0), panel)

        # Y lo que el bus si entrega no se saca: el trazado se reconstruye
        # integrando velocidad y guiñada, y esta a la vista.
        trazado = re.search(r'<section[^>]*data-panel="trazado"[^>]*>', dom)
        self.assertIsNotNone(trazado)
        self.assertNotIn("data-fuera", trazado.group(0))

        # SACAR UN PANEL NO PUEDE BORRAR EL HECHO, Y ESTO LO COMPRUEBA SOBRE EL
        # DOM DE VERDAD. La constancia se escribe desde la misma tabla que saca
        # los paneles, de modo que lo que falta en pantalla y lo que se lee al
        # pie son la misma declaracion. Se comprueba aca y no sobre el archivo
        # porque el bloque lo llena el guion: un `index.html` con el hueco no
        # demuestra que alguien lo complete.
        bloque = re.search(
            r'<div class="ausencias-declaradas"[^>]*>(.*?)</div>\s*</div>',
            dom, re.S)
        self.assertIsNotNone(bloque, "no esta el bloque de ausencias declaradas")
        self.assertNotIn("hidden", bloque.group(0).split(">", 1)[0],
                         "el bus saca dos paneles y el bloque quedo escondido")
        self.assertIn("Puesta a punto", bloque.group(1))
        self.assertIn("Vehículos", bloque.group(1))
        self.assertIn("no hay con quién comparar", bloque.group(1))


if __name__ == "__main__":
    unittest.main()
