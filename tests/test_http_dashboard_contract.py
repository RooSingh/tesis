"""Prueba HTTP minima de los contratos que usa el dashboard.

Se llama a la aplicacion ASGI real para cubrir parseo JSON, validacion de
FastAPI, enrutado y serializacion sin agregar httpx al entorno del proyecto.
"""

from __future__ import annotations

import asyncio
import json
import unittest

from backend.app import app


async def pedir(metodo: str, ruta: str, cuerpo=None):
    enviados = []
    contenido = b"" if cuerpo is None else json.dumps(cuerpo).encode("utf-8")
    pendiente = True

    async def recibir():
        nonlocal pendiente
        if pendiente:
            pendiente = False
            return {"type": "http.request", "body": contenido, "more_body": False}
        return {"type": "http.disconnect"}

    async def enviar(mensaje):
        enviados.append(mensaje)

    await app({
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": metodo, "scheme": "http", "path": ruta,
        "raw_path": ruta.encode("ascii"), "query_string": b"",
        "root_path": "", "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 1), "server": ("test", 80),
    }, recibir, enviar)
    inicio = next(m for m in enviados if m["type"] == "http.response.start")
    datos = b"".join(m.get("body", b"") for m in enviados
                     if m["type"] == "http.response.body")
    return inicio["status"], json.loads(datos or b"null")


class CacheDelTableroTests(unittest.TestCase):
    """Que un despliegue se vea sin tener que vaciar el cache a mano.

    `StaticFiles` manda `ETag` y `Last-Modified` pero no manda `Cache-Control`,
    y sin esa cabecera el navegador no pregunta: aplica una frescura heuristica
    ---una fraccion del tiempo transcurrido desde la ultima modificacion--- y
    sirve lo que tiene sin ir al servidor. Delante hay ademas una red de
    distribucion que trata a un `.css` como un archivo estatico cualquiera.

    El resultado es que subir el tablero a la Raspberry no alcanza para verlo:
    paso, con una hoja de estilos que en el disco de la Raspberry y en la
    respuesta de la API ya era la nueva. `no-cache` no significa no guardar
    ---eso es `no-store`---: significa preguntar antes de usar lo guardado, y
    la respuesta a esa pregunta suele ser un 304 sin cuerpo.
    """

    def test_los_archivos_del_tablero_se_revalidan(self) -> None:
        import os
        from backend import app as modulo

        archivo = os.path.join("dashboard", "index.html")
        estaticos = modulo.TableroQueSeRevalida(directory="dashboard", html=True)
        respuesta = estaticos.file_response(
            archivo, os.stat(archivo),
            {"type": "http", "method": "GET", "headers": []})
        self.assertEqual(respuesta.headers["cache-control"], "no-cache")

    def test_la_raiz_tambien_se_revalida(self) -> None:
        """La raiz no pasa por el montaje: la sirve su propia ruta.

        Es la peor de todas para quedarse pegada, porque es la que trae los
        nombres de los demas archivos.
        """

        from backend import app as modulo
        respuesta = modulo._tablero_revalidado(modulo.Path("dashboard") / "index.html")
        self.assertEqual(respuesta.headers["cache-control"], "no-cache")


class ContratoHttpDashboardTests(unittest.TestCase):
    def test_health_pasa_por_la_aplicacion_asgi(self) -> None:
        estado, cuerpo = asyncio.run(pedir("GET", "/health"))
        self.assertEqual(estado, 200)
        self.assertEqual(cuerpo, {"status": "ok"})

    def test_openf1_rechaza_el_cuerpo_vacio_que_el_frontend_ya_no_envia(self) -> None:
        estado, _ = asyncio.run(pedir("POST", "/openf1/importar", {}))
        self.assertEqual(estado, 422)

    def test_can_rechaza_una_lista_vacia_que_el_frontend_ya_no_envia(self) -> None:
        estado, cuerpo = asyncio.run(pedir("POST", "/can/importar", {"segmentos": []}))
        self.assertEqual(estado, 400)
        self.assertIn("al menos un segmento", cuerpo["detail"])


if __name__ == "__main__":
    unittest.main()
