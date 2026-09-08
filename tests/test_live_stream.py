"""Pruebas del camino en vivo.

No abren conexiones al broker: ejercitan el difusor y el formato de evento, que
es donde esta la logica. La conexion real se verifica al levantar el servicio.
"""

from __future__ import annotations

import asyncio
from collections import deque
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


class _BucleFalso:
    """Un bucle de asyncio que solo cuenta lo que se le pide y lo ejecuta.

    Lo que interesa medir es **cuantas** funciones se programan, que es el
    trabajo pendiente del puente entre el hilo de MQTT y el bucle.
    """

    def __init__(self):
        self.pedidas = 0

    def call_soon_threadsafe(self, fn, *args):
        self.pedidas += 1
        return None


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
        """En vivo el dato reciente vale mas: acumular anadiria latencia oculta.

        `_encolar` dejo de ser estatico el 2026-09-07: lleva la cuenta de lo que
        descarta, y para eso necesita el difusor. La cuenta es la parte nueva
        ---antes se descartaba en silencio--- y es lo que permite distinguir un
        grafico con menos puntos de un grafico saturado.
        """

        sus = live_stream.Suscriptor()
        sus.datos = deque(maxlen=3)
        for i in range(5):
            sus.poner_dato({"n": i})
        self.assertEqual([sus.get_nowait()["n"] for _ in range(3)], [2, 3, 4])
        self.assertEqual(sus.descartes_datos, 2)

    def test_el_trabajo_pendiente_del_puente_tiene_tope(self):
        """La cola de cada suscriptor tenia tope; lo que estaba antes, no.

        Cada señal programaba una funcion en el bucle por cada suscriptor. Esa
        cola de tareas no tiene limite: a la carga de la parrilla completa
        crecia hasta agotar la memoria, y ningun contador lo decia.
        """

        self.d._bucle = _BucleFalso()
        self.d.suscribir()
        for i in range(live_stream.PENDIENTES_DE_TELEMETRIA + 500):
            self.d._depositar(self.d._pendientes, {"n": i}, "telemetria")
        self.assertLessEqual(len(self.d._pendientes),
                             live_stream.PENDIENTES_DE_TELEMETRIA)
        self.assertEqual(self.d.descartes_puente, 500)

    def test_una_sola_pasada_pedida_por_mas_que_llegue(self):
        """Es el punto: el trabajo pendiente deja de crecer con el caudal."""

        bucle = _BucleFalso()
        self.d._bucle = bucle
        self.d.suscribir()
        for i in range(5000):
            self.d._depositar(self.d._pendientes, {"n": i}, "telemetria")
        self.assertEqual(bucle.pedidas, 1,
                         "se programaron %d funciones para 5000 señales" % bucle.pedidas)

    def test_los_eventos_no_quedan_detras_de_la_telemetria(self):
        """Perder una muestra es perder resolucion; perder un aviso es perder el hecho."""

        self.d._bucle = _BucleFalso()
        cola = self.d.suscribir()
        for i in range(200):
            self.d._depositar(self.d._pendientes, {"n": i}, "telemetria")
        self.d._depositar(self.d._pendientes_eventos,
                          {"_evento": "anotacion", "titulo": "bloqueo"}, "evento")
        self.d._despachar()
        primero = cola.get_nowait()
        self.assertEqual(primero.get("_evento"), "anotacion")

    def test_el_estado_declara_lo_que_se_perdio_de_vista(self):
        """Un descarte silencioso es una perdida que nadie puede ver."""

        estado = self.d.estado()
        d = estado["descartes_de_vista"]
        # Cuatro cifras: dos puntos del transporte por dos tipos de elemento.
        # Una sola cifra escondería justo lo que hay que ver.
        for clave in ("puente_datos", "puente_eventos",
                      "suscriptor_datos", "suscriptor_eventos"):
            self.assertIn(clave, d)
        # Y se declara que es una perdida de vista, no de persistencia.
        self.assertIn("persistencia", d["que_significa"])
        # Y que una anotacion descartada se puede volver a pedir.
        self.assertIn("/live/anotaciones", d["recuperacion_de_anotaciones"])

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


class TrabajoSoloSiAlguienMiraTest(unittest.TestCase):
    """Lo caro del manejador no corre con cero suscriptores.

    Medido en banco: el anotador se lleva el 51,6 % del manejador y el resumen
    el 10,1 %. Antes de esto el servidor ocupaba 1,021 nucleos **sin que nadie
    mirara**.
    """

    def _cuerpo(self, valor=100.0):
        return {
            "timestamp": "2026-09-07T12:00:00+00:00",
            "vehicle_id": "v1", "signal_name": "speed", "value": valor,
        }

    def test_sin_suscriptores_no_se_alimenta_el_resumen(self):
        d = live_stream.DifusorEnVivo()
        for i in range(5):
            d._procesar_cuerpo(self._cuerpo(float(i)), "2026-09-07T12:00:00Z")
        self.assertEqual(d._cuantos_suscriptores, 0)
        self.assertFalse(d.anotadores,
                         "no deberia haberse creado ningun anotador")

    def test_la_ventana_por_senal_se_mantiene_igual(self):
        """Es el 3,9 % del costo y es lo unico que un suscriptor nuevo necesita
        para no ver un grafico vacio: saltearla ahorraria poco y costaria eso."""

        d = live_stream.DifusorEnVivo()
        for i in range(5):
            d._procesar_cuerpo(self._cuerpo(float(i)), "2026-09-07T12:00:00Z")
        self.assertEqual(list(d.historia["v1"]["speed"]),
                         [0.0, 1.0, 2.0, 3.0, 4.0])
        self.assertEqual(d.recibidos, 5)

    def test_con_un_suscriptor_vuelve_a_hacerse_todo(self):
        d = live_stream.DifusorEnVivo()
        d._cuantos_suscriptores = 1          # como si alguien se hubiera atado
        d._procesar_cuerpo(self._cuerpo(), "2026-09-07T12:00:00Z")
        self.assertIn("v1", d.anotadores)

    def test_el_contador_sigue_a_la_lista(self):
        """La lista es la verdad y el entero la espeja. Si se desincronizan, el
        manejador decide con un dato viejo."""

        d = live_stream.DifusorEnVivo()
        colas = [d.suscribir() for _ in range(3)]
        self.assertEqual(d._cuantos_suscriptores, 3)
        d.desuscribir(colas[0])
        self.assertEqual(d._cuantos_suscriptores, 2)
        for c in colas[1:]:
            d.desuscribir(c)
        self.assertEqual(d._cuantos_suscriptores, 0)


class EntregaDeAnotacionesTests(unittest.IsolatedAsyncioTestCase):
    """Que una anotacion llegue, no que entre primero.

    Hasta el 2026-09-08 anotaciones y muestras compartian la cola del
    suscriptor. Se repartian las anotaciones primero, y eso parecia suficiente:
    no lo era. La cola descarta lo mas viejo al llenarse, de modo que las
    quinientas muestras que venian detras empujaban la anotacion afuera antes de
    que el navegador llegara a leerla. **Entrar primero y sobrevivir son cosas
    distintas.**

    Estas pruebas corren sobre un bucle de asyncio de verdad: el reparto ocurre
    en una funcion programada con `call_soon_threadsafe`, y comprobarlo con un
    bucle falso solo demuestra que se la programo.
    """

    async def _difusor_con(self, cuantos: int = 1):
        d = live_stream.DifusorEnVivo()
        d._bucle = asyncio.get_running_loop()
        suscriptores = [d.suscribir() for _ in range(cuantos)]
        return d, suscriptores

    @staticmethod
    def _anotacion(titulo: str) -> dict:
        return {"_evento": "anotacion", "titulo": titulo, "nivel": "aviso"}

    async def _repartir(self, d):
        """Deja correr la funcion que el puente programo en el bucle."""

        await asyncio.sleep(0.02)

    async def test_una_anotacion_sobrevive_a_seiscientas_muestras(self):
        d, (sus,) = await self._difusor_con()
        d._depositar(d._pendientes_eventos, self._anotacion("bloqueo"), "evento")
        for i in range(600):
            d._depositar(d._pendientes, {"n": i}, "telemetria")
        await self._repartir(d)

        recibidos = []
        while not sus.empty():
            recibidos.append(sus.get_nowait())
        anotaciones = [x for x in recibidos if x.get("_evento") == "anotacion"]
        self.assertEqual(len(anotaciones), 1,
                         "la anotacion se perdio detras de las muestras")
        self.assertEqual(recibidos[0].get("_evento"), "anotacion",
                         "y tiene que salir antes que las muestras")
        # Las muestras si se descartan, y eso esta bien: es resolucion.
        self.assertGreater(sus.descartes_datos, 0)
        self.assertEqual(sus.descartes_eventos, 0)

    async def test_varias_anotaciones_intercaladas_con_rafagas(self):
        d, (sus,) = await self._difusor_con()
        for k in range(5):
            d._depositar(d._pendientes_eventos, self._anotacion("aviso %d" % k), "evento")
            for i in range(300):
                d._depositar(d._pendientes, {"n": k * 1000 + i}, "telemetria")
            await self._repartir(d)

        titulos = []
        while not sus.empty():
            x = sus.get_nowait()
            if x.get("_evento") == "anotacion":
                titulos.append(x["titulo"])
        self.assertEqual(titulos, ["aviso %d" % k for k in range(5)],
                         "faltaron anotaciones, o llegaron desordenadas")

    async def test_la_saturacion_de_eventos_se_declara_aparte(self):
        """Si los eventos saturan su propia capacidad, es otra perdida.

        Y tiene recuperacion: la lista completa vive en `/live/anotaciones`, que
        no pasa por este transporte.
        """

        d, (sus,) = await self._difusor_con()
        cuantas = live_stream.EVENTOS_POR_SUSCRIPTOR + 50
        for k in range(cuantas):
            d._depositar(d._pendientes_eventos, self._anotacion("a%d" % k), "evento")
        await self._repartir(d)

        self.assertEqual(len(sus.eventos), live_stream.EVENTOS_POR_SUSCRIPTOR,
                         "la cola de eventos tiene que tener tope")
        self.assertEqual(sus.descartes_eventos, 50)
        self.assertEqual(sus.descartes_datos, 0,
                         "saturar eventos no puede contarse como perdida de datos")

    async def test_un_suscriptor_lento_no_le_saca_nada_al_rapido(self):
        d, (rapido, lento) = await self._difusor_con(2)
        d._depositar(d._pendientes_eventos, self._anotacion("bloqueo"), "evento")
        for i in range(200):
            d._depositar(d._pendientes, {"n": i}, "telemetria")
        await self._repartir(d)

        # El rapido vacia; el lento no lee nada y sigue recibiendo.
        leidos_rapido = []
        while not rapido.empty():
            leidos_rapido.append(rapido.get_nowait())
        # La rafaga entra de una sola vez, asi que tiene que caber en la cola:
        # con 600 sobre un tope de 500 perderia tambien el rapido, y eso no
        # diria nada sobre el lento.
        for i in range(400):
            d._depositar(d._pendientes, {"n": 1000 + i}, "telemetria")
        await self._repartir(d)

        # El rapido vuelve a vaciar y no pierde nada: cada suscriptor tiene su
        # propia cola, de modo que el atraso de uno no se le cobra al otro.
        segunda_tanda = []
        while not rapido.empty():
            segunda_tanda.append(rapido.get_nowait())

        self.assertEqual(leidos_rapido[0].get("_evento"), "anotacion")
        self.assertEqual(len(leidos_rapido), 201, "el rapido perdio algo")
        self.assertEqual(len(segunda_tanda), 400, "el rapido perdio de la segunda tanda")
        self.assertEqual(rapido.descartes_datos, 0,
                         "el lento le hizo perder datos al rapido")

        # El lento si descarta muestras ---son 600 para una cola de 500--- y eso
        # es lo que corresponde: pierde resolucion. Pero conserva su anotacion,
        # porque un consumidor lento no puede perder hechos.
        pendientes_lento = list(lento.eventos)
        self.assertEqual(len(pendientes_lento), 1)
        self.assertEqual(pendientes_lento[0]["titulo"], "bloqueo")
        self.assertEqual(lento.descartes_datos, 100)
        self.assertEqual(lento.descartes_eventos, 0)

    async def test_el_flujo_sse_entrega_la_anotacion_primero(self):
        """Extremo a extremo del transporte, con el generador que sirve el SSE."""

        d, (sus,) = await self._difusor_con()
        anterior = live_stream.difusor
        live_stream.difusor = d          # `flujo_de_eventos` consulta el estado
        try:
            for i in range(400):
                d._depositar(d._pendientes, {"n": i, "signal_name": "speed"}, "telemetria")
            d._depositar(d._pendientes_eventos, self._anotacion("despiste"), "evento")
            await self._repartir(d)

            generador = live_stream.flujo_de_eventos(sus, intervalo_latido_s=5.0)
            primero = await generador.__anext__()      # el estado inicial
            self.assertIn("event: estado", primero)
            segundo = await generador.__anext__()
            self.assertIn("event: anotacion", segundo,
                          "la anotacion no salio antes que las muestras")
            self.assertIn("despiste", segundo)
            tercero = await generador.__anext__()
            self.assertIn("event: telemetria", tercero)
            await generador.aclose()
        finally:
            live_stream.difusor = anterior

    async def test_el_puente_sigue_acotado_con_un_bucle_real(self):
        """El tope del puente no depende de que el bucle sea falso."""

        d, (sus,) = await self._difusor_con()
        for i in range(live_stream.PENDIENTES_DE_TELEMETRIA + 300):
            d._depositar(d._pendientes, {"n": i}, "telemetria")
        self.assertLessEqual(len(d._pendientes), live_stream.PENDIENTES_DE_TELEMETRIA)
        self.assertEqual(d.descartes_puente, 300)
        await self._repartir(d)
        self.assertEqual(len(d._pendientes), 0, "el bucle no vacio el puente")
