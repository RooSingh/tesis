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
