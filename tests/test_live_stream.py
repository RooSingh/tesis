"""Pruebas del camino en vivo.

No abren conexiones al broker: ejercitan el difusor y el formato de evento, que
es donde esta la logica. La conexion real se verifica al levantar el servicio.
"""

from __future__ import annotations

import asyncio
import json
import unittest

from backend import live_stream
from backend.live_stream import DifusorEnVivo, evento_sse


class Mensaje:
    """Imita el mensaje que entrega el cliente MQTT."""

    def __init__(self, cuerpo, crudo=None):
        self.payload = crudo if crudo is not None else json.dumps(cuerpo).encode("utf-8")


class FormatoDeEventoTests(unittest.TestCase):
    """El formato de eventos enviados por el servidor es un protocolo de texto."""

    def test_el_evento_lleva_nombre_y_termina_en_linea_vacia(self):
        salida = evento_sse({"a": 1}, "telemetria")
        self.assertTrue(salida.startswith("event: telemetria\n"))
        self.assertTrue(salida.endswith("\n\n"))
        self.assertIn('"a": 1', salida)

    def test_conserva_los_acentos_sin_escapar(self):
        """Escapar acentos haria ilegible el evento en el navegador."""

        self.assertIn("simulación", evento_sse({"x": "simulación"}))


class DifusorTests(unittest.TestCase):
    """Reparto a suscriptores y comportamiento ante saturacion."""

    def setUp(self):
        self.d = DifusorEnVivo()
        self.bucle = asyncio.new_event_loop()
        self.d._bucle = self.bucle

    def tearDown(self):
        self.bucle.close()

    def _entregar(self, cuerpo):
        """Simula la llegada de un mensaje y procesa el reparto pendiente."""

        self.d._al_recibir(None, None, Mensaje(cuerpo))
        self.bucle.call_soon(self.bucle.stop)
        self.bucle.run_forever()

    def test_reparte_a_todos_los_suscriptores(self):
        a = self.d.suscribir()
        b = self.d.suscribir()
        self._entregar({"signal_name": "speed", "value": 300})
        self.assertEqual(a.get_nowait()["value"], 300)
        self.assertEqual(b.get_nowait()["value"], 300)

    def test_marca_el_instante_de_recepcion(self):
        """Sin esa marca la latencia habria que inferirla."""

        cola = self.d.suscribir()
        self._entregar({"signal_name": "speed"})
        self.assertIn("_recibido_utc", cola.get_nowait())

    def test_desagrupa_un_lote_mqtt(self):
        """El capturador publica lotes; SSE debe entregar una senal por evento."""

        cola = self.d.suscribir()
        self._entregar([
            {"signal_name": "speed", "value": 300},
            {"signal_name": "engine_speed", "value": 12000},
        ])
        recibidos = [cola.get_nowait(), cola.get_nowait()]
        self.assertEqual([m["signal_name"] for m in recibidos],
                         ["speed", "engine_speed"])
        self.assertEqual(self.d.recibidos, 2)

    def test_un_elemento_invalido_no_descarta_el_resto_del_lote(self):
        cola = self.d.suscribir()
        self._entregar(["invalido", {"signal_name": "speed", "value": 280}])
        self.assertEqual(self.d.descartados, 1)
        self.assertEqual(cola.get_nowait()["value"], 280)

    def test_un_mensaje_ilegible_no_interrumpe_el_flujo(self):
        cola = self.d.suscribir()
        self.d._al_recibir(None, None, Mensaje(None, crudo=b"esto no es json"))
        self.assertEqual(self.d.descartados, 1)
        self.assertTrue(cola.empty())
        self._entregar({"signal_name": "speed"})
        self.assertFalse(cola.empty())

    def test_al_saturarse_descarta_lo_mas_viejo(self):
        """En vivo el dato reciente vale mas: acumular anadiria latencia oculta."""

        cola = asyncio.Queue(maxsize=3)
        for i in range(5):
            DifusorEnVivo._encolar(cola, {"n": i})
        self.assertEqual([cola.get_nowait()["n"] for _ in range(3)], [2, 3, 4])

    def test_respeta_el_tope_de_suscriptores(self):
        """Un tope evita que pestanas olvidadas consuman memoria sin limite."""

        colas = [self.d.suscribir() for _ in range(live_stream.MAX_SUSCRIPTORES)]
        self.assertTrue(all(c is not None for c in colas))
        self.assertIsNone(self.d.suscribir())

    def test_desuscribir_libera_el_lugar(self):
        colas = [self.d.suscribir() for _ in range(live_stream.MAX_SUSCRIPTORES)]
        self.d.desuscribir(colas[0])
        self.assertIsNotNone(self.d.suscribir())

    def test_conserva_una_ventana_reciente(self):
        """Permite que un navegador que llega tarde vea algo de inmediato."""

        for i in range(5):
            self.d._al_recibir(None, None, Mensaje({"n": i}))
        self.assertEqual([m["n"] for m in self.d.recientes], [0, 1, 2, 3, 4])

    def test_el_estado_distingue_sin_datos_de_sin_conexion(self):
        """Es lo que permite a la interfaz declarar el motivo en vez de fallar."""

        estado = self.d.estado()
        self.assertIn("conectado", estado)
        self.assertIn("mensajes_recibidos", estado)

    def test_el_estado_declara_los_dos_caminos(self):
        """Anunciar solo este camino se lee como que el dato no se guarda.

        La frase "sin pasar por la base" es cierta sobre la vista y enganosa
        sobre el sistema: la persistencia corre en paralelo. Declarar los dos
        caminos es lo que evita que una decision de diseno se lea como una
        perdida de datos.
        """

        estado = self.d.estado()
        self.assertIn("camino_vista", estado)
        self.assertIn("camino_persistencia", estado)
        self.assertIn("base de datos", estado["camino_persistencia"])

    def test_sin_bucle_no_falla(self):
        """El difusor puede recibir antes de que la aplicacion este lista."""

        d = DifusorEnVivo()
        d._al_recibir(None, None, Mensaje({"n": 1}))
        self.assertEqual(d.recibidos, 1)


if __name__ == "__main__":
    unittest.main()
