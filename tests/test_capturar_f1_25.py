"""Pruebas del capturador: derivacion de procedencia desde el propio flujo.

No abren sockets ni tocan la red: ejercitan la parte que convierte los paquetes
decodificados en la procedencia de la captura, que es donde esta la logica.
"""

from __future__ import annotations

import unittest

import scripts.capturar_f1_25 as capturar_f1_25

from backend import f1_udp
from scripts.capturar_f1_25 import AYUDAS, derivar_procedencia, nombre_derivado
from tests.test_f1_udp import _cabecera


def _sesion(**cambios):
    """Sesion decodificada de un datagrama de relleno, con campos alterados."""

    tamano = f1_udp.PAQUETES[1]["tamano"]
    datos = _cabecera(1) + bytes(tamano - f1_udp.CABECERA_TAMANO)
    sesion = f1_udp.decodificar(datos)["sesion"]
    sesion.update(cambios)
    return sesion


class ProcedenciaDerivadaTests(unittest.TestCase):
    """La procedencia sale del flujo, no de lo que declare el operador."""

    def test_sin_paquete_de_sesion_se_declara_no_disponible(self):
        """No se inventa: se dice que no se pudo derivar y por que."""

        p = derivar_procedencia(None, None, None)
        self.assertFalse(p["disponible"])
        self.assertIn("motivo", p)

    def test_traduce_el_identificador_de_circuito(self):
        p = derivar_procedencia(_sesion(track_id=7), None, None)
        self.assertEqual(p["circuito"], "silverstone")
        self.assertEqual(p["circuito_id"], 7)

    def test_un_circuito_no_catalogado_conserva_su_identificador(self):
        """No se etiqueta como desconocido: se conserva el identificador.

        Un circuito nuevo que el catalogo no tenga sigue siendo trazable, y el
        nombre derivado del archivo lo refleja en lugar de perderlo.
        """

        p = derivar_procedencia(_sesion(track_id=99), None, None)
        self.assertEqual(p["circuito"], "id-99")
        self.assertEqual(p["circuito_id"], 99)

    def test_detecta_que_no_hay_ninguna_ayuda_activa(self):
        sesion = _sesion(**{n: v for n, v in AYUDAS.items()})
        p = derivar_procedencia(sesion, {"traction_control": 0, "anti_lock_brakes": 0}, None)
        self.assertTrue(p["sin_ayudas"])
        self.assertEqual(p["ayudas_activas"], [])

    def test_detecta_una_ayuda_activa_y_la_nombra(self):
        """Es el caso que motivo derivarlas: se habia capturado sin advertirlo."""

        sesion = _sesion(**{n: v for n, v in AYUDAS.items()})
        p = derivar_procedencia(sesion, {"traction_control": 1, "anti_lock_brakes": 0}, None)
        self.assertFalse(p["sin_ayudas"])
        self.assertIn("traction_control", p["ayudas_activas"])

    def test_la_caja_manual_no_se_cuenta_como_ayuda_activa(self):
        """El valor uno es manual; dos y tres si son asistencias."""

        p = derivar_procedencia(_sesion(gearbox_assist=1), None, None)
        self.assertNotIn("gearbox_assist", p["ayudas_activas"])
        p = derivar_procedencia(_sesion(gearbox_assist=3), None, None)
        self.assertIn("gearbox_assist", p["ayudas_activas"])

    def test_declara_el_dano_con_su_valor_y_su_nombre(self):
        """En contrarreloj el dano viene apagado y los canales quedan en cero.

        Se comprueba tambien el nombre, porque el valor crudo solo no distingue
        una captura util de una en la que los 34 canales de desgaste estan
        congelados: eso es lo que separa "3" de "simulacion".
        """

        apagado = derivar_procedencia(_sesion(car_damage_setting=0), None, None)
        self.assertEqual(apagado["ajustes"]["car_damage_setting"]["valor"], 0)
        self.assertEqual(apagado["ajustes"]["car_damage_setting"]["nombre"], "desactivado")

        simulacion = derivar_procedencia(_sesion(car_damage_setting=3), None, None)
        self.assertEqual(simulacion["ajustes"]["car_damage_setting"]["valor"], 3)
        self.assertEqual(simulacion["ajustes"]["car_damage_setting"]["nombre"], "simulacion")

    def test_los_tipos_de_sesion_siguen_a_la_especificacion(self):
        """Fija la tabla contra el apendice, no contra lo que se recuerde.

        La version anterior nombraba "sprint-2" al tipo 15, que es Carrera. El
        error no se veia en el dato —era correcto— sino en como se lo archivaba,
        de modo que solo una prueba escrita contra la especificacion lo atrapa.
        """

        esperado = {5: "clasificacion-1", 10: "sprint-shootout-1",
                    15: "carrera", 16: "carrera-2", 18: "contrarreloj"}
        for identificador, nombre in esperado.items():
            with self.subTest(tipo=identificador):
                p = derivar_procedencia(_sesion(session_type=identificador), None, None)
                self.assertEqual(p["tipo_sesion"], nombre)

    def test_arrastra_el_inicio_de_cada_sector(self):
        """Es un dato que la fuente deportiva no entrega."""

        p = derivar_procedencia(_sesion(sector2_lap_distance_start_m=2225.6,
                                        sector3_lap_distance_start_m=5065.0), None, None)
        self.assertAlmostEqual(p["inicio_sector2_m"], 2225.6, places=1)
        self.assertAlmostEqual(p["inicio_sector3_m"], 5065.0, places=1)

    def test_funciona_sin_paquete_de_estado(self):
        """El estado del vehiculo puede no haber llegado; la sesion alcanza.

        Las ayudas que declara la sesion se derivan igual; las dos que solo
        declara el estado del vehiculo quedan ausentes en lugar de suponerse
        apagadas, que seria afirmar algo que no se observo.
        """

        p = derivar_procedencia(_sesion(track_id=13), None, None)
        self.assertTrue(p["disponible"])
        self.assertIn("steering_assist", p["ayudas"])
        self.assertNotIn("traction_control", p["ayudas"])
        self.assertNotIn("anti_lock_brakes", p["ayudas"])


class SinListaDuplicadaTests(unittest.TestCase):
    """El capturador no puede tener su propia idea de que se normaliza.

    El defecto que esta prueba impide ya ocurrio: el capturador llevaba escrita
    a mano la lista `("car_telemetry", "lap_data")`. Cuando el adaptador aprendio
    a normalizar energia y dano, esos canales quedaron sin publicar. Existian en
    el registro crudo y no llegaban a la base, de modo que la persistencia
    guardaba **que** el vehiculo freno y no **por que**.

    Ninguna prueba lo detectaba porque cada mitad era correcta por separado. Lo
    que estaba mal era que hubiera dos mitades.
    """

    def test_el_capturador_publica_todo_lo_que_el_adaptador_normaliza(self):
        import inspect

        from adapters import f1_25

        fuente = inspect.getsource(capturar_f1_25.Publicador.publicar)
        # No se compara contra una lista escrita aca —seria una tercera copia—
        # sino que se verifica que el capturador consulte al adaptador.
        self.assertIn("f1_25.PAQUETES_NORMALIZABLES", fuente)
        for paquete in f1_25.PAQUETES_NORMALIZABLES:
            with self.subTest(paquete=paquete):
                self.assertNotIn(f'"{paquete}"', fuente)

    def test_el_adaptador_declara_senales_para_cada_paquete(self):
        """Cada paquete normalizable aporta senales, y ninguno sobra.

        La version anterior de esta prueba exigia que las senales estuvieran en
        el mapa raiz del paquete, y `motion_ex` la hizo fallar: sus cinco senales
        entran cuatro por el mapa por rueda y una por el de campos anidados, de
        modo que su mapa raiz esta vacio y aun asi el paquete aporta.

        El defecto estaba en la prueba y no en el adaptador: la invariante que
        importa es **que ningun paquete declarado normalizable produzca cero
        senales**, no por que camino las produce. La version anterior habria
        dejado pasar un paquete que aportara solo por rueda y estuviera roto.
        """

        from adapters import f1_25

        self.assertEqual(set(f1_25.PAQUETES_NORMALIZABLES),
                         set(f1_25.MAPAS_POR_PAQUETE))

        # Se cuenta sobre el catalogo, que es lo que el adaptador afirma
        # producir, y no sumando los tres mapas a mano: sumarlos a mano seria
        # repetir aca la logica que se quiere verificar.
        por_paquete: dict[str, int] = {}
        for senal in f1_25.catalogo_de_senales():
            por_paquete[senal["paquete"]] = por_paquete.get(senal["paquete"], 0) + 1

        for paquete in f1_25.PAQUETES_NORMALIZABLES:
            with self.subTest(paquete=paquete):
                self.assertGreater(
                    por_paquete.get(paquete, 0), 0,
                    f"{paquete} es normalizable y no produce ninguna senal")

    def test_el_catalogo_declara_todo_lo_que_la_normalizacion_produce(self):
        """Lo que el catalogo promete y lo que un paquete real entrega coinciden.

        Es la prueba que atrapa una senal agregada a la normalizacion y olvidada
        en el catalogo: la vista mostraria un canal que no puede elegirse, o
        elegiria uno que nunca llega.
        """

        from adapters import f1_25

        prometidas = {s["signal_name"] for s in f1_25.catalogo_de_senales()}

        # Un paquete de bloque unico, que es el camino nuevo y el menos
        # transitado. Los campos van escritos aca a mano, sin leerlos del
        # adaptador, para que la prueba no herede su error.
        decodificado = {
            "decodificado": True,
            "paquete": "motion_ex",
            "packet_id": 13,
            "version_decodificador": "prueba",
            "cabecera": {
                "session_uid": 1, "player_car_index": 0, "session_time": 1.0,
                "packet_format": 2025, "frame_identifier": 1,
            },
            "sesion": {
                "wheel_slip_ratio": {
                    "trasera_izquierda": 0.1, "trasera_derecha": 0.2,
                    "delantera_izquierda": 0.3, "delantera_derecha": 0.4,
                },
                "angular_velocity_rads": {"x": 1.0, "y": 2.0, "z": 3.0},
            },
        }
        mensajes = f1_25.mensajes_desde_paquete(
            decodificado, "2026-08-31T00:00:00+00:00")
        producidas = {m["signal_name"] for m in mensajes}

        self.assertEqual(producidas, {
            "wheel_slip_ratio_rear_left", "wheel_slip_ratio_rear_right",
            "wheel_slip_ratio_front_left", "wheel_slip_ratio_front_right",
            "yaw_rate",
        })
        self.assertTrue(producidas <= prometidas,
                        f"produce sin declarar: {producidas - prometidas}")

        # Y el eje correcto: la guinada es el `y`, verificado por integracion
        # sobre una vuelta completa. Tomar el `z` daria 3,0 en lugar de 2,0.
        guinada = next(m for m in mensajes if m["signal_name"] == "yaw_rate")
        self.assertEqual(guinada["value"], 2.0)

    def test_un_paquete_de_bloque_unico_no_finge_tener_veintidos_vehiculos(self):
        """Pedirle todos los vehiculos tiene que fallar, no devolver uno.

        Devolver el propio en silencio haria creer que se devolvieron los
        veintidos, que es la clase de error que no deja rastro.
        """

        from adapters import f1_25

        decodificado = {
            "decodificado": True, "paquete": "motion_ex", "packet_id": 13,
            "version_decodificador": "prueba",
            "cabecera": {"session_uid": 1, "player_car_index": 0,
                         "session_time": 1.0, "packet_format": 2025,
                         "frame_identifier": 1},
            "sesion": {"angular_velocity_rads": {"x": 0.0, "y": 0.0, "z": 0.0}},
        }
        with self.assertRaises(f1_25.ErrorNormalizacion):
            f1_25.mensajes_desde_paquete(
                decodificado, "2026-08-31T00:00:00+00:00",
                solo_vehiculo_propio=False)


if __name__ == "__main__":
    unittest.main()


class NombreDerivadoTests(unittest.TestCase):
    """El nombre del archivo sale del flujo, no de lo que escriba el operador.

    Un nombre derivado no puede estar equivocado respecto del contenido; uno
    escrito a mano si.
    """

    def setUp(self):
        from datetime import datetime
        self.momento = datetime(2026, 8, 29, 17, 12)

    def test_incluye_circuito_y_tipo_de_sesion(self):
        p = derivar_procedencia(_sesion(track_id=7, session_type=15), None, None)
        nombre = nombre_derivado(p, self.momento)
        self.assertIn("silverstone", nombre)
        self.assertIn("carrera", nombre)
        self.assertTrue(nombre.startswith("20260829_1712"))

    def test_marca_cuando_no_hubo_ninguna_ayuda(self):
        sesion = _sesion(track_id=13, session_type=18, **dict(AYUDAS))
        p = derivar_procedencia(sesion, {"traction_control": 0, "anti_lock_brakes": 0}, None)
        self.assertIn("sin-ayudas", nombre_derivado(p, self.momento))

    def test_no_marca_sin_ayudas_si_alguna_quedo_activa(self):
        sesion = _sesion(track_id=13, session_type=18, **dict(AYUDAS))
        p = derivar_procedencia(sesion, {"traction_control": 1, "anti_lock_brakes": 0}, None)
        self.assertNotIn("sin-ayudas", nombre_derivado(p, self.momento))

    def test_marca_la_sesion_de_dos_conductores(self):
        p = derivar_procedencia(_sesion(track_id=7, game_mode=6), None, None)
        self.assertTrue(p["pantalla_dividida"])
        self.assertIn("dos-conductores", nombre_derivado(p, self.momento))

    def test_un_circuito_no_catalogado_conserva_su_identificador(self):
        p = derivar_procedencia(_sesion(track_id=99), None, None)
        self.assertIn("id-99", nombre_derivado(p, self.momento))

    def test_sin_procedencia_el_nombre_lo_declara(self):
        """No inventa un circuito: dice que la sesion no se declaro."""

        nombre = nombre_derivado(derivar_procedencia(None, None, None), self.momento)
        self.assertIn("no-declarada", nombre)


class SegundoConductorTests(unittest.TestCase):
    """La conformidad se asume; solo se registra que la sesion fue de dos."""

    def test_detecta_pantalla_dividida_por_modo_de_juego(self):
        p = derivar_procedencia(_sesion(game_mode=6), None, None)
        self.assertTrue(p["pantalla_dividida"])

    def test_detecta_pantalla_dividida_por_indice_del_segundo(self):
        """Segunda via independiente del modo de juego: el indice del segundo.

        La version anterior de esta prueba pasaba **una cabecera** y daba por
        buena una sola lectura. Eso era exactamente el defecto: en los primeros
        paquetes de una captura, y al reiniciarse una sesion, el emisor publica
        la cabecera todavia en cero, y un cero es un indice legitimo. La via
        sigue siendo independiente; lo que cambia es que ahora exige que el
        indice **se sostenga** en el recuento de cabeceras ya pobladas.
        """

        cabecera = {"secondary_player_car_index": 1, "session_uid": 1,
                    "game_major_version": 1, "game_minor_version": 24}
        p = derivar_procedencia(_sesion(game_mode=5), None, cabecera,
                                secundarios={1: 3169})
        self.assertTrue(p["pantalla_dividida"])

    def test_un_solo_conductor_no_se_marca(self):
        cabecera = {"secondary_player_car_index": 255, "session_uid": 1,
                    "game_major_version": 1, "game_minor_version": 24}
        p = derivar_procedencia(_sesion(game_mode=5), None, cabecera,
                                secundarios={255: 6652})
        self.assertFalse(p["pantalla_dividida"])

    def test_una_cabecera_suelta_ya_no_declara_dos_conductores(self):
        """La regresion concreta que este cambio impide.

        La cabecera declara un segundo participante y el recuento dice que no se
        sostuvo. Antes alcanzaba con la cabecera, y tres capturas del fin de
        semana de Spa quedaron nombradas como de dos conductores sin haberlos.
        """

        from datetime import datetime

        cabecera = {"secondary_player_car_index": 0, "session_uid": 1,
                    "game_major_version": 1, "game_minor_version": 24}
        p = derivar_procedencia(_sesion(game_mode=4), None, cabecera,
                                secundarios={0: 18, 255: 49519})
        self.assertFalse(p["pantalla_dividida"])
        self.assertNotIn("dos-conductores",
                         nombre_derivado(p, datetime(2026, 9, 4, 18, 39)))


class DescarteDeNoSesionTests(unittest.TestCase):
    """Navegar por los menus no es una sesion, dure lo que dure.

    El filtro original era por duracion, y dejo pasar diez capturas de entre
    diez y setenta y tres segundos: todas mas largas que el minimo, ninguna con
    un solo paquete de sesion. El criterio por reloj no podia distinguirlas.
    """

    def test_una_captura_sin_sesion_no_es_conservable(self):
        p = derivar_procedencia(None, None, None)
        self.assertFalse(p["disponible"])
        self.assertIn("motivo", p)

    def test_el_nombre_derivado_declara_que_no_hubo_sesion(self):
        """Aunque se conservara, el archivo diria que no sabe de que es."""

        from datetime import datetime

        p = derivar_procedencia(None, None, None)
        nombre = nombre_derivado(p, datetime(2026, 8, 30, 21, 8))
        self.assertIn("sesion-no-declarada", nombre)


class ParrillaTests(unittest.TestCase):
    """La parrilla se arma por nombre, no por el contador de vehiculos activos.

    Son dos cosas distintas y confundirlas costo la entrada del propio conductor:
    `num_active_cars` cuenta los que siguen en carrera, mientras que el arreglo
    conserva sus veintidos posiciones indexadas por vehiculo. En la carrera
    capturada el contador bajo de 20 a 18 por dos abandonos y las veinte entradas
    seguian teniendo nombre; recortar por el contador descartaba las posiciones
    18 y 19, y el vehiculo propio era el 19.
    """

    @staticmethod
    def _participantes(nombres, activos):
        vehiculos = []
        for i in range(22):
            nombre = nombres[i] if i < len(nombres) else ""
            vehiculos.append({
                "name": nombre, "race_number": i + 1, "team": "Mercedes",
                "team_id": 0, "ai_controlled": 0 if i == len(nombres) - 1 else 1,
                "platform": "PlayStation",
            })
        return {"num_active_cars": activos, "vehiculos": vehiculos}

    def test_un_abandono_no_borra_a_nadie_de_la_parrilla(self):
        nombres = [f"P{i:02d}" for i in range(20)]
        parrilla = capturar_f1_25.derivar_parrilla(
            self._participantes(nombres, activos=18))
        self.assertEqual(len(parrilla), 20)
        self.assertEqual(parrilla[-1]["indice"], 19)
        self.assertEqual(parrilla[-1]["nombre"], "P19")

    def test_las_posiciones_vacias_no_entran(self):
        parrilla = capturar_f1_25.derivar_parrilla(
            self._participantes(["UNO", "DOS"], activos=2))
        self.assertEqual([v["nombre"] for v in parrilla], ["UNO", "DOS"])

    def test_el_indice_es_el_del_vehiculo_y_no_el_de_la_lista(self):
        """Es el indice con el que el resto del protocolo nombra al vehiculo."""

        nombres = [f"P{i:02d}" for i in range(20)]
        parrilla = capturar_f1_25.derivar_parrilla(
            self._participantes(nombres, activos=20))
        for entrada in parrilla:
            with self.subTest(indice=entrada["indice"]):
                self.assertEqual(entrada["nombre"], f"P{entrada['indice']:02d}")

    def test_sin_paquete_de_participantes_no_se_inventa_parrilla(self):
        self.assertIsNone(capturar_f1_25.derivar_parrilla(None))


class SegundoConductorSostenidoTests(unittest.TestCase):
    """El segundo conductor se decide por la moda, no por una cabecera.

    Tres capturas quedaron nombradas como de dos conductores sin haberlos. El
    nombre salia de la **primera** cabecera de la captura, y en los primeros
    paquetes ---y tambien al reiniciarse una sesion--- el emisor publica
    estructura valida con la cabecera todavia en cero. Un cero es un indice
    legitimo, de modo que el error no fallaba: producia un experimento mal
    rotulado, y en este trabajo **el nombre del archivo es la condicion
    declarada**.

    Los numeros de estas pruebas salen de las capturas reales. Con dos
    conductores el indice secundario vale 19 en las 3.169 cabeceras utiles de la
    captura mas larga; con la cabecera sin poblar, 255 en las 6.652 de la carrera
    del fin de semana de Spa.
    """

    def test_dos_conductores_reales_se_reconocen(self):
        self.assertTrue(capturar_f1_25._segundo_sostenido({19: 3169}))

    def test_sin_segundo_conductor_no_se_declara(self):
        self.assertFalse(capturar_f1_25._segundo_sostenido({255: 6652}))

    def test_un_punado_de_cabeceras_en_cero_no_alcanza(self):
        """El caso exacto que produjo los tres nombres equivocados.

        Dieciocho paquetes con la cabecera sin poblar contra casi cincuenta mil
        que la declaran ausente. La lectura por moda los ignora; la lectura de un
        instante los tomaba por buenos.
        """

        self.assertFalse(capturar_f1_25._segundo_sostenido({0: 18, 255: 49519}))

    def test_sin_cabeceras_no_se_inventa_un_segundo_conductor(self):
        self.assertFalse(capturar_f1_25._segundo_sostenido({}))
        self.assertFalse(capturar_f1_25._segundo_sostenido(None))

    def test_el_valor_ausente_tampoco_declara_segundo_conductor(self):
        """`None` aparece cuando la cabecera no trae el campo, y no es un indice."""

        self.assertFalse(capturar_f1_25._segundo_sostenido({None: 500}))

    def test_hace_falta_mayoria_y_no_una_simple_aparicion(self):
        """Un indice valido en minoria no alcanza.

        Es la diferencia entre "aparecio" y "se sostuvo", que es justamente la
        distincion que el defecto original no hacia.
        """

        self.assertFalse(capturar_f1_25._segundo_sostenido({19: 400, 255: 600}))
        self.assertTrue(capturar_f1_25._segundo_sostenido({19: 600, 255: 400}))


class IdentidadDeReinyeccionTests(unittest.TestCase):
    """El capturador puede marcar lo que publica como corrida de prueba.

    Sin esa marca, una reproduccion **contra** el capturador entra a la base con
    el mismo `source_type` y el mismo `session_id` que la sesion verdadera, y no
    hay forma de separarlas. Y el indice unico de trazabilidad es parcial ---solo
    aplica cuando `replay_run_id` no es nulo--- de modo que una segunda corrida
    duplicaria filas **en silencio**.

    Es el mismo defecto que el camino del bus vehicular ya habia corregido. Aca
    no se habia notado porque solo aparece al reproducir contra el capturador,
    que es algo que empezo a hacerse al medir la cadena completa.
    """

    class _ClienteFalso:
        def __init__(self):
            self.publicados = []
            self.envios = 0

        def publish(self, topico, carga, qos=0):
            import json as _json
            import types
            # **Llega un envio por paquete, con la lista de senales adentro.**
            # El falso la desarma para que las pruebas sigan mirando senales,
            # que es de lo que hablan, y no envios.
            contenido = _json.loads(carga)
            self.envios += 1
            self.publicados.extend(
                contenido if isinstance(contenido, list) else [contenido])
            # El cliente real devuelve un objeto con el codigo de resultado, y
            # el publicador lo mira: un falso que devuelva None ya no sirve.
            return types.SimpleNamespace(rc=0)

    def _publicar(self, run_id):
        pub = capturar_f1_25.Publicador(activo=False, run_id=run_id)
        cliente = self._ClienteFalso()
        pub.cliente = cliente
        paquete = {"paquete": "car_telemetry", "decodificado": True}
        mensajes = [{"signal_name": "speed_kmh", "value_numeric": 1.0},
                    {"signal_name": "speed_kmh", "value_numeric": 2.0}]
        original = capturar_f1_25.f1_25.mensajes_desde_paquete
        capturar_f1_25.f1_25.mensajes_desde_paquete = (
            lambda *a, **k: iter(mensajes))
        try:
            pub.publicar(paquete, "2026-09-05T00:00:00+00:00")
        finally:
            capturar_f1_25.f1_25.mensajes_desde_paquete = original
        return cliente.publicados

    def test_sin_identidad_no_se_agrega_nada(self):
        """Una sesion real no lleva identidad de reinyeccion y no debe llevarla."""

        for m in self._publicar(None):
            self.assertNotIn("replay_run_id", m.get("metadata", {}).get("extra", {}))

    def test_la_marca_va_donde_el_contrato_la_espera(self):
        """Dentro de `metadata.extra`, no en el nivel superior del mensaje.

        La primera version la puso arriba y **no fallo**: el mensaje se publico,
        se persistio, y la columna quedo en nulo. Las filas de la prueba entraron
        sin marca, que es exactamente lo que la marca existia para impedir.
        """

        publicados = self._publicar("prueba_d")
        self.assertTrue(publicados)
        for m in publicados:
            self.assertNotIn("replay_run_id", m)
            self.assertEqual(m["metadata"]["extra"]["replay_run_id"], "prueba_d")

    def test_la_secuencia_avanza_y_no_se_repite(self):
        """Es lo que hace aplicable el indice unico parcial.

        Con la secuencia repetida, el indice no distingue una fila de otra y la
        proteccion contra duplicados no serviria de nada.
        """

        publicados = self._publicar("prueba_d")
        secuencias = [m["metadata"]["extra"]["replay_seq"] for m in publicados]
        self.assertEqual(secuencias, sorted(secuencias))
        self.assertEqual(len(set(secuencias)), len(secuencias))


class ParrillaCompletaTests(unittest.TestCase):
    """Normalizar los veintidos vehiculos, y no solo el propio.

    Existe porque el destinatario amateur usa el sistema para medir su propio
    desempeno **comparandose contra los demas**, y en un simulador ese dato le
    pertenece. La restriccion de no tener telemetria de rivales es la de un
    ingeniero de equipo, no la de cualquier usuario.

    Va apagado por omision: multiplica por unas veinte lo que se escribe en la
    base, y eso conviene que sea una decision y no un descuido.
    """

    class _ClienteFalso:
        def __init__(self):
            self.publicados = []
            self.envios = 0

        def publish(self, topico, carga, qos=0):
            import json as _json
            import types
            # **Llega un envio por paquete, con la lista de senales adentro.**
            # El falso la desarma para que las pruebas sigan mirando senales,
            # que es de lo que hablan, y no envios.
            contenido = _json.loads(carga)
            self.envios += 1
            self.publicados.extend(
                contenido if isinstance(contenido, list) else [contenido])
            # El cliente real devuelve un objeto con el codigo de resultado, y
            # el publicador lo mira: un falso que devuelva None ya no sirve.
            return types.SimpleNamespace(rc=0)

    def _publicar(self, paquete, parrilla_completa, con_participantes=True):
        """Publica un paquete y devuelve con que argumentos se llamo al adaptador."""

        pub = capturar_f1_25.Publicador(activo=False,
                                        parrilla_completa=parrilla_completa)
        pub.cliente = self._ClienteFalso()
        llamadas = []
        original = capturar_f1_25.f1_25.mensajes_desde_paquete

        def espia(decodificado, inicio, **kw):
            llamadas.append(kw)
            return iter([])

        capturar_f1_25.f1_25.mensajes_desde_paquete = espia
        try:
            if con_participantes:
                pub.publicar({"paquete": "participants", "decodificado": True,
                              "vehiculos": [{"name": "UNO"}, {"name": "DOS"},
                                            {"name": ""}]},
                             "2026-09-06T00:00:00+00:00")
                llamadas.clear()
            pub.publicar({"paquete": paquete, "decodificado": True},
                         "2026-09-06T00:00:00+00:00")
        finally:
            capturar_f1_25.f1_25.mensajes_desde_paquete = original
        return llamadas

    def test_apagada_por_omision(self):
        """Veinte veces mas filas no puede ser el comportamiento accidental."""

        kw = self._publicar("car_telemetry", parrilla_completa=False)
        self.assertTrue(kw[0]["solo_vehiculo_propio"])

    def test_encendida_normaliza_a_todos(self):
        kw = self._publicar("car_telemetry", parrilla_completa=True)
        self.assertFalse(kw[0]["solo_vehiculo_propio"])

    def test_los_paquetes_de_bloque_unico_siguen_en_modo_propio(self):
        """Pedirles todos los vehiculos es un error, no una opcion.

        El paquete de sesion describe la sesion y el de movimiento extendido al
        vehiculo propio: el adaptador levanta excepcion si se le piden los
        veintidos. Encender la parrilla no puede romperlos.
        """

        for paquete in sorted(capturar_f1_25.f1_25.PAQUETES_DE_BLOQUE_UNICO):
            with self.subTest(paquete=paquete):
                kw = self._publicar(paquete, parrilla_completa=True)
                self.assertTrue(kw[0]["solo_vehiculo_propio"])

    def test_solo_se_publican_los_vehiculos_con_nombre(self):
        """El arreglo tiene veintidos lugares y no siempre corren veintidos.

        Sin filtrar, una carrera de veinte autos producia mensajes para los
        indices 20 y 21: filas describiendo vehiculos que no existieron. No
        fallaba, porque sus campos vienen en cero.
        """

        kw = self._publicar("car_telemetry", parrilla_completa=True)
        self.assertEqual(kw[0]["vehiculos_validos"], frozenset({0, 1}))

    def test_sin_paquete_de_participantes_no_se_inventa_una_parrilla(self):
        """Mejor no filtrar que filtrar con una lista adivinada."""

        kw = self._publicar("car_telemetry", parrilla_completa=True,
                            con_participantes=False)
        self.assertIsNone(kw[0]["vehiculos_validos"])


class EleccionDePilotosTests(unittest.TestCase):
    """Elegir a quien escuchar, por nombre, sin pedir la parrilla entera.

    POR QUE POR NOMBRE Y NO POR INDICE. El indice del arreglo de vehiculos no
    significa nada para quien conduce: no es la posicion en la carrera ni el
    numero del coche, es el lugar que el juego le dio en una lista. Quien mira
    el tablero elige a Verstappen, no al indice 4.

    POR QUE ES UNA ELECCION Y NO LA PARRILLA COMPLETA. Medido sobre la carrera
    de Spa: cada coche pide 1.511 senales/s y el propio 1.673. Los veintidos
    piden 33.250, y la cadena sobre la Raspberry no los sostiene. Seis piden
    9.228, que si entra. La eleccion es lo que convierte un objetivo imposible
    en uno medido.
    """

    PARRILLA = {0: "Mauricio", 1: "Max Verstappen", 2: "Lando Norris",
                3: "Charles Leclerc", 4: "George Russell"}

    def test_el_coche_propio_va_siempre_aunque_no_se_lo_nombre(self):
        """No es una cortesia: es de quien conduce, y es el que tiene `motion_ex`.

        Una eleccion que lo dejara afuera dejaria la sesion sin el unico
        vehiculo del que el protocolo entrega los datos completos.
        """

        elegidos = capturar_f1_25.indices_elegidos(
            self.PARRILLA, ["Lando Norris"], propio=0)
        self.assertIn(0, elegidos)
        self.assertEqual(elegidos, frozenset({0, 2}))

    def test_no_distingue_mayusculas_ni_acentos_ni_espacios(self):
        """El nombre se escribe a mano o se copia de una lista; las dos formas valen."""

        elegidos = capturar_f1_25.indices_elegidos(
            self.PARRILLA, ["  max VERSTAPPEN ", "charles leclerc"], propio=0)
        self.assertEqual(elegidos, frozenset({0, 1, 3}))

    def test_el_apellido_solo_alcanza(self):
        """Es como se los nombra en la television y en el propio juego."""

        elegidos = capturar_f1_25.indices_elegidos(
            self.PARRILLA, ["Norris", "Russell"], propio=0)
        self.assertEqual(elegidos, frozenset({0, 2, 4}))

    def test_un_nombre_que_no_corre_se_ignora_sin_romper(self):
        """La lista puede venir de una sesion anterior con otra parrilla.

        Fallar dejaria la captura sin arrancar por un nombre viejo; publicar un
        indice inventado escribiria filas de un vehiculo que no existio.
        """

        elegidos = capturar_f1_25.indices_elegidos(
            self.PARRILLA, ["Fernando Alonso", "Norris"], propio=0)
        self.assertEqual(elegidos, frozenset({0, 2}))

    def test_se_acota_a_lo_que_la_cadena_sostiene(self):
        """El tope no es un numero de gusto: es lo que la medicion permite.

        Cada coche pide 1.511 senales/s y el consumidor sostiene alrededor de
        9.900 en serie. Aceptar una lista de veinte nombres seria prometer algo
        que se sabe que no se cumple, y el modo en que no se cumple es el peor
        posible: no falla, se pierden muestras de todos, tambien del propio.

        Se recorta respetando el orden pedido, que es el orden de interes de
        quien eligio.
        """

        elegidos = capturar_f1_25.indices_elegidos(
            self.PARRILLA, ["Russell", "Leclerc", "Norris", "Verstappen"],
            propio=0, tope=3)
        self.assertEqual(elegidos, frozenset({0, 4, 3}))

    def test_sin_eleccion_no_se_filtra_nada(self):
        """`None` y una lista vacia no son lo mismo que una lista con nombres.

        Sin eleccion, quien decide sigue siendo `parrilla_completa`: esta
        funcion no debe convertir «no elegi» en «solo mi coche».
        """

        self.assertIsNone(capturar_f1_25.indices_elegidos(self.PARRILLA, [], propio=0))
        self.assertIsNone(capturar_f1_25.indices_elegidos(self.PARRILLA, None, propio=0))


class DescartesDelPublicadorTests(unittest.TestCase):
    """Lo que el cliente no llega a enviar se cuenta aparte, no como enviado.

    La version anterior ignoraba lo que `publish` devolvia y sumaba uno al
    contador igual. Bajo la carga de una parrilla completa **el 95,6 % de los
    envios devolvia cola llena** y el mensaje se descartaba: el capturador
    informaba haber publicado un millon y medio de mensajes de los que salieron
    sesenta y seis mil.

    No hay excepcion, no hay registro y nada falla. El unico sintoma es que a la
    base llega el cuatro por ciento, y para verlo hay que estar buscandolo.
    """

    class _ClienteFalso:
        """Cliente que acepta unos mensajes y rechaza el resto."""

        def __init__(self, acepta_envios):
            self.acepta_envios = acepta_envios
            self.enviados = 0

        def publish(self, topico, carga, qos=0):
            import types
            if self.enviados < self.acepta_envios:
                self.enviados += 1
                return types.SimpleNamespace(rc=0)
            # 15 es el codigo con que el cliente avisa que su cola esta llena.
            return types.SimpleNamespace(rc=15)

    def _publicar(self, cuantos, envios_aceptados, paquetes=1):
        """Publica `paquetes` paquetes de `cuantos` senales cada uno.

        Como ahora va **un envio por paquete**, para probar el descarte hacen
        falta varios paquetes: uno solo se acepta o se rechaza entero.
        """

        pub = capturar_f1_25.Publicador(activo=False)
        pub.cliente = self._ClienteFalso(envios_aceptados)
        mensajes = [{"signal_name": f"s{i}"} for i in range(cuantos)]
        original = capturar_f1_25.f1_25.mensajes_desde_paquete
        capturar_f1_25.f1_25.mensajes_desde_paquete = lambda *a, **k: iter(list(mensajes))
        try:
            for _ in range(paquetes):
                pub.publicar({"paquete": "car_telemetry", "decodificado": True},
                             "2026-09-06T00:00:00+00:00")
        finally:
            capturar_f1_25.f1_25.mensajes_desde_paquete = original
        return pub

    def test_solo_se_cuentan_como_enviados_los_que_salieron(self):
        """Diez paquetes de cien senales; el cliente acepta tres envios."""

        pub = self._publicar(cuantos=100, envios_aceptados=3, paquetes=10)
        self.assertEqual(pub.mensajes, 300)
        self.assertEqual(pub.descartados, 700)

    def test_el_motivo_del_descarte_queda_registrado(self):
        """Sin el motivo, un descarte no se distingue de otro.

        Cola llena y sin conexion piden respuestas distintas, y el numero solo
        no permite elegir.
        """

        pub = self._publicar(cuantos=10, envios_aceptados=4, paquetes=10)
        # Seis envios rechazados de diez senales cada uno: se cuenta **por
        # senal**, porque lo que se perdio son las senales.
        self.assertEqual(pub.motivos_descarte, {15: 60})

    def test_sin_descartes_el_contador_queda_limpio(self):
        pub = self._publicar(cuantos=10, envios_aceptados=1)
        self.assertEqual(pub.mensajes, 10)
        self.assertEqual(pub.descartados, 0)
        self.assertEqual(pub.motivos_descarte, {})

    def test_enviados_y_descartados_no_se_suman_en_una_sola_cifra(self):
        """La cifra unica era la que mentia.

        Que sean dos contadores no es un detalle de presentacion: es lo que
        permite afirmar cuanto se publico **y** cuanto se perdio, en lugar de
        afirmar mal una sola cosa.
        """

        pub = self._publicar(cuantos=50, envios_aceptados=2, paquetes=5)
        self.assertNotEqual(pub.mensajes, 250)
        self.assertEqual(pub.mensajes + pub.descartados, 250)


class PublicacionPorLoteTests(unittest.TestCase):
    """Un envio por paquete, con todas sus senales adentro.

    Cada mensaje con garantia de entrega paga un ida y vuelta con el
    intermediario, y **el cliente acepta unos 6.578 por segundo sin importar
    que lleven adentro**: uno de 560 senales pesa quinientas sesenta veces mas y
    se envia al mismo ritmo.

    De a una senal por mensaje, la parrilla completa descartaba el 96 % en la
    cola de salida. Agrupadas, el caudal util pasa de 6.578 a 3,19 millones de
    senales por segundo.
    """

    class _ClienteFalso:
        def __init__(self):
            self.cargas = []

        def publish(self, topico, carga, qos=0):
            import json as _json
            import types
            self.cargas.append(_json.loads(carga))
            return types.SimpleNamespace(rc=0)

    def _publicar(self, cuantas):
        pub = capturar_f1_25.Publicador(activo=False)
        pub.cliente = self._ClienteFalso()
        mensajes = [{"signal_name": f"s{i}"} for i in range(cuantas)]
        original = capturar_f1_25.f1_25.mensajes_desde_paquete
        capturar_f1_25.f1_25.mensajes_desde_paquete = lambda *a, **k: iter(mensajes)
        try:
            pub.publicar({"paquete": "car_telemetry", "decodificado": True},
                         "2026-09-06T00:00:00+00:00")
        finally:
            capturar_f1_25.f1_25.mensajes_desde_paquete = original
        return pub.cliente.cargas, pub

    def test_un_paquete_produce_un_solo_envio(self):
        """Es toda la ganancia: 560 senales en un envio y no en 560."""

        cargas, _ = self._publicar(560)
        self.assertEqual(len(cargas), 1)
        self.assertEqual(len(cargas[0]), 560)

    def test_el_contador_sigue_hablando_de_senales(self):
        """Contar envios haria parecer chico el trabajo y chico el descarte."""

        _, pub = self._publicar(560)
        self.assertEqual(pub.mensajes, 560)

    def test_una_sola_senal_no_viaja_envuelta_en_una_lista(self):
        """Un paquete que produce una senal manda esa senal, no un lote de uno.

        Envolver siempre obligaria a todos los consumidores a desarmar, incluso
        cuando no hay nada que desarmar, y romperia a los que hoy leen el
        contrato de a un mensaje.
        """

        cargas, _ = self._publicar(1)
        self.assertIsInstance(cargas[0], dict)
        self.assertEqual(cargas[0]["signal_name"], "s0")

    def test_un_paquete_sin_senales_no_publica_nada(self):
        cargas, pub = self._publicar(0)
        self.assertEqual(cargas, [])
        self.assertEqual(pub.mensajes, 0)


class DosSesionesSeguidasTests(unittest.TestCase):
    """La parrilla de una sesion no puede nombrar a los coches de la siguiente.

    EL DEFECTO. El publicador vive lo que vive el proceso, y el proceso atraviesa
    varias sesiones de juego: se arranca al iniciar sesion en la maquina y se
    queda. Los indices y los nombres se llenan con el paquete de participantes y
    **no se limpiaban al cambiar de sesion**.

    Entre el primer paquete de la sesion nueva y su paquete de participantes
    ---que llega cada cinco segundos--- hay una ventana en la que el capturador
    resuelve los nombres elegidos contra la parrilla vieja. Los indices del
    arreglo se reusan: el 3 de la sesion anterior es otro piloto en esta. Se
    publicarian datos de un rival que en esta sesion es otro, y quedarian
    guardados como suyos.

    LO QUE SE CONSERVA. Los nombres que la persona eligio, que son una decision
    suya y no un dato de la sesion. Se vuelven a resolver cuando llegue la
    parrilla nueva.
    """

    def _publicador(self):
        p = capturar_f1_25.Publicador(activo=False)
        p._parrilla_completa = False
        return p

    def _participantes(self, session_uid, nombres):
        return {"paquete": "participants",
                "cabecera": {"session_uid": session_uid, "player_car_index": 0},
                "vehiculos": [{"name": n} for n in nombres]}

    def test_al_cambiar_de_sesion_se_olvida_la_parrilla_vieja(self):
        p = self._publicador()
        p.publicar(self._participantes(111, ["Yo", "Norris", "Leclerc"]), "x", 0)
        self.assertEqual(p._nombres, {0: "Yo", 1: "Norris", 2: "Leclerc"})

        # Llega un paquete cualquiera de OTRA sesion, antes de su parrilla.
        p.publicar({"paquete": "car_telemetry",
                       "cabecera": {"session_uid": 222, "player_car_index": 0}},
                      "x", 0)
        self.assertEqual(p._nombres, {},
                         "los nombres de la sesion anterior siguen en pie")
        self.assertIsNone(p._validos,
                          "los indices de la sesion anterior siguen en pie")

    def test_la_eleccion_de_la_persona_sobrevive_al_cambio(self):
        """Es una decision suya, no un dato de la sesion que termino."""

        p = self._publicador()
        p._pilotos = ["Norris"]
        p.publicar(self._participantes(111, ["Yo", "Norris"]), "x", 0)
        p.publicar({"paquete": "car_telemetry",
                       "cabecera": {"session_uid": 222, "player_car_index": 0}},
                      "x", 0)
        self.assertEqual(p._pilotos, ["Norris"])

    def test_el_mismo_indice_no_publica_al_piloto_de_la_sesion_anterior(self):
        """Los indices se reusan: el 1 de una sesion es otro en la siguiente."""

        p = self._publicador()
        p._pilotos = ["Norris"]
        p.publicar(self._participantes(111, ["Yo", "Norris"]), "x", 0)
        elegidos_antes = capturar_f1_25.indices_elegidos(p._nombres, p._pilotos, propio=0)
        self.assertEqual(elegidos_antes, frozenset({0, 1}))

        p.publicar({"paquete": "car_telemetry",
                       "cabecera": {"session_uid": 222, "player_car_index": 0}},
                      "x", 0)
        # Sin parrilla nueva, no hay a quien resolver: solo el coche propio.
        self.assertEqual(
            capturar_f1_25.indices_elegidos(p._nombres, p._pilotos, propio=0),
            frozenset({0}))

        p.publicar(self._participantes(222, ["Yo", "Hamilton", "Norris"]), "x", 0)
        self.assertEqual(
            capturar_f1_25.indices_elegidos(p._nombres, p._pilotos, propio=0),
            frozenset({0, 2}), "Norris ahora es el indice 2, no el 1")
