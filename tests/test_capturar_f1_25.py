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

        def publish(self, topico, carga, qos=0):
            import json as _json
            self.publicados.append(_json.loads(carga))

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
