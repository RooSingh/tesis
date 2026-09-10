"""Pruebas de la normalizacion de F1 25 hacia el contrato interno.

Verifican dos cosas distintas: que los mensajes se ajusten al contrato que el
backend valida, y que la procedencia obligatoria viaje completa en cada mensaje.
"""

from __future__ import annotations

import unittest

from adapters import f1_25
from backend import f1_udp
from backend.models import TelemetryMessage
from tests.test_f1_udp import (
    datagrama_sin_decodificador,
    datagrama_telemetria,
    datagrama_vueltas,
)

INICIO = "2026-08-29T14:30:00+00:00"


def paquetes_normalizables() -> list[int]:
    """Los identificadores de los paquetes que el adaptador sabe normalizar.

    Se derivan del adaptador y no se escriben aca. La lista escrita a mano ya
    fallo: al incorporar el paquete de movimiento, estas pruebas seguian
    contrastando cuatro paquetes y el quinto quedaba sin comprobar, que es
    exactamente el defecto de las dos listas que el trabajo viene corrigiendo.
    """

    por_nombre = {p["nombre"]: i for i, p in f1_udp.PAQUETES.items()}
    return sorted(por_nombre[n] for n in f1_25.PAQUETES_NORMALIZABLES)

def _telemetria(indice_propio: int = 3, marcha: int = -1) -> dict:
    return f1_udp.decodificar(datagrama_telemetria(indice_propio, marcha))


class ContratoTests(unittest.TestCase):
    """Los mensajes deben pasar la validacion que aplica el backend."""

    def test_los_mensajes_validan_contra_el_contrato(self):
        for mensaje in f1_25.mensajes_desde_paquete(_telemetria(), INICIO):
            TelemetryMessage(**mensaje)

    def test_declara_el_tipo_de_fuente_y_la_calidad(self):
        mensaje = f1_25.mensajes_desde_paquete(_telemetria(), INICIO)[0]
        self.assertEqual(mensaje["source_type"], "f1_25_udp_simulation")
        self.assertEqual(mensaje["quality_flag"], "simulated_f1_25")
        # Habia ademas un `simulated: True` en el metadato de cada senal. Decia
        # lo mismo que estas dos lineas y lo repetia seis mil veces por segundo:
        # una tercera copia de un hecho no lo hace mas cierto.
        self.assertNotIn("simulated", mensaje["metadata"]["extra"])

    def test_identificadores_derivan_de_la_sesion_del_juego(self):
        mensaje = f1_25.mensajes_desde_paquete(_telemetria(indice_propio=7), INICIO)[0]
        self.assertEqual(mensaje["session_id"], "f1_25:session:3735928559")
        self.assertEqual(mensaje["vehicle_id"], "f1_25:session:3735928559:car:7")

    def test_la_marca_temporal_se_deriva_del_inicio_de_captura(self):
        """El protocolo entrega segundos de sesion, no una fecha."""

        mensaje = f1_25.mensajes_desde_paquete(_telemetria(), INICIO)[0]
        # session_time del datagrama de prueba es 12,5 s.
        self.assertTrue(mensaje["timestamp"].startswith("2026-08-29T14:30:12.5"))

    def test_rechaza_un_inicio_de_captura_no_interpretable(self):
        with self.assertRaises(f1_25.ErrorNormalizacion):
            f1_25.mensajes_desde_paquete(_telemetria(), "el sabado a la tarde")


class LoConstanteSeDeclaraUnaVezTests(unittest.TestCase):
    """Lo que no cambia en toda la sesion no viaja en cada senal.

    Cada mensaje llevaba 554 bytes de metadato y **la mayoria era constante**:
    la version del adaptador, la del decodificador, el formato del paquete, el
    identificador de la sesion. Repetido una vez por senal, y una carrera de
    cuatro coches produce seis mil senales por segundo.

    No es un problema de disco ---el disco sobra--- sino de las tres etapas por
    las que ese metadato pasa: se serializa en el capturador, se encola en el
    intermediario y se interpreta en el consumidor. Medido el 2026-09-10: el
    intermediario descarto 7.873 mensajes de una carrera porque su cola se mide
    en bytes, y esos bytes eran en un 70 % metadato repetido.

    LO QUE SE SACA SIGUE DECLARADO, EN OTRO LADO Y UNA SOLA VEZ. Lo que es de
    la senal ---de que campo sale y como se transformo--- pasa al catalogo de
    senales; lo que es de la captura, a los metadatos del archivo. Una
    procedencia que se declara una vez no es una procedencia perdida; una que
    se repite seis mil veces por segundo tampoco es mas cierta.
    """

    #: Se leen de la fila guardada, en consultas o en Python. Estos se quedan.
    SE_LEEN = {"paquete", "session_time_s", "frame_identifier",
               "player_car_index", "desplazamiento_captura_us",
               "origen_adquisicion", "captura_sha256"}
    #: Nadie los lee de la fila. Se declaran en el catalogo o en el sidecar.
    SE_VAN = {"version_adaptador", "version_decodificador", "packet_format",
              "packet_id", "session_uid", "simulated", "transformation",
              "campo_origen"}

    def _extra(self):
        mensajes = f1_25.mensajes_desde_paquete(_telemetria(), INICIO)
        return mensajes[0]["metadata"]["extra"]

    def test_lo_que_se_lee_de_la_fila_sigue_estando(self) -> None:
        extra = self._extra()
        for clave in self.SE_LEEN:
            with self.subTest(clave=clave):
                self.assertIn(clave, extra)

    def test_lo_constante_ya_no_viaja_en_cada_senal(self) -> None:
        extra = self._extra()
        for clave in self.SE_VAN:
            with self.subTest(clave=clave):
                self.assertNotIn(clave, extra)

    def test_el_catalogo_declara_de_donde_sale_cada_senal_y_como_se_convierte(self) -> None:
        """Es lo de la senal, y es lo mismo para todas sus filas.

        Sin esto, sacar `campo_origen` y `transformation` del mensaje seria
        perder el dato. Con esto, se pregunta una vez.
        """

        catalogo = f1_25.catalogo_de_senales()
        por_nombre = {s["signal_name"]: s for s in catalogo}
        self.assertEqual(por_nombre["speed"]["campo_origen"], "speed_kmh")
        self.assertEqual(por_nombre["speed"]["transformation"], "identity")
        # El acelerador se publica en por ciento: el factor tiene que decirse.
        self.assertEqual(por_nombre["throttle_position"]["transformation"],
                         "escala_x100")
        self.assertEqual(por_nombre["drs_open"]["transformation"], "cast_bool")
        for s in catalogo:
            self.assertIn("campo_origen", s)
            self.assertIn("transformation", s)


class SenalesTests(unittest.TestCase):
    """Conversion de unidades y fidelidad de los valores."""

    def _por_senal(self, mensajes: list[dict]) -> dict:
        return {m["signal_name"]: m for m in mensajes}

    def test_acelerador_y_freno_pasan_a_porcentaje(self):
        """El protocolo los entrega entre cero y uno."""

        senales = self._por_senal(f1_25.mensajes_desde_paquete(_telemetria(), INICIO))
        self.assertAlmostEqual(senales["throttle_position"]["value"], 85.0, places=2)
        self.assertEqual(senales["throttle_position"]["unit"], "%")
        self.assertAlmostEqual(senales["brake_position"]["value"], 0.0, places=2)

    def test_la_velocidad_pasa_sin_alterarse(self):
        senales = self._por_senal(
            f1_25.mensajes_desde_paquete(_telemetria(indice_propio=3), INICIO))
        self.assertEqual(senales["speed"]["value"], 303)
        self.assertEqual(senales["speed"]["unit"], "km/h")

    def test_la_marcha_atras_sobrevive_a_la_normalizacion(self):
        """El signo debe llegar hasta el contrato, no solo hasta el decodificador."""

        senales = self._por_senal(
            f1_25.mensajes_desde_paquete(_telemetria(marcha=-1), INICIO))
        self.assertEqual(senales["gear_selected"]["value"], -1)

    def test_normaliza_el_paquete_de_datos_de_vuelta(self):
        decodificado = f1_udp.decodificar(datagrama_vueltas())
        senales = self._por_senal(
            f1_25.mensajes_desde_paquete(decodificado, INICIO))
        self.assertEqual(senales["lap_number"]["value"], 12)
        self.assertAlmostEqual(senales["lap_distance"]["value"], 1234.5, places=1)
        self.assertEqual(senales["lap_distance"]["unit"], "m")

    def test_el_aleron_movil_se_normaliza_como_booleano(self):
        """Contrasta con la fuente deportiva, donde es un codigo de estado.

        Sale del mismo mapa de senales que el resto: no hay un camino especial
        para este campo.
        """

        senales = self._por_senal(f1_25.mensajes_desde_paquete(_telemetria(), INICIO))
        mensaje = senales["drs_open"]
        self.assertIs(mensaje["value"], True)
        self.assertEqual(mensaje["unit"], "bool")
        # De que campo del protocolo sale es una propiedad de la senal, no del
        # instante: se pregunta una vez al catalogo y no viaja en cada fila.
        catalogo = {s["signal_name"]: s for s in f1_25.catalogo_de_senales()}
        self.assertEqual(catalogo["drs_open"]["campo_origen"], "drs")
        TelemetryMessage(**mensaje)


class ProcedenciaTests(unittest.TestCase):
    """La procedencia es obligatoria y debe permitir reconstruir el origen."""

    def test_cada_mensaje_transporta_lo_que_cambia_con_el_instante(self):
        """La procedencia sigue completa; lo que cambio es donde vive cada parte.

        Antes esta prueba exigia diez campos en cada senal, y ocho de ellos eran
        constantes: la version del adaptador no cambia entre dos muestras
        separadas cincuenta milisegundos. Repetirlos costaba 232 de los 554
        bytes del bloque, y ese costo se paga tres veces ---al serializar, al
        encolar y al interpretar--- porque la cola del intermediario se mide en
        bytes. Con cuatro vehiculos se perdio por eso el 40 % de una carrera.

        Lo que queda en la fila es lo que **solo se sabe mirando esa fila**: en
        que marco y en que segundo de sesion se tomo, de que vehiculo es, de que
        paquete salio y si se adquirio en vivo o reproducida.
        """

        del_instante = {"origen_adquisicion", "paquete", "frame_identifier",
                        "session_time_s", "desplazamiento_captura_us",
                        "player_car_index", "captura_sha256"}
        for mensaje in f1_25.mensajes_desde_paquete(_telemetria(), INICIO):
            self.assertTrue(del_instante <= set(mensaje["metadata"]["extra"]))

    def test_el_identificador_de_sesion_no_se_pierde_al_sacarlo_del_metadato(self):
        """Estaba tres veces en el mismo mensaje y sigue estando dos."""

        mensaje = f1_25.mensajes_desde_paquete(_telemetria(), INICIO)[0]
        self.assertNotIn("session_uid", mensaje["metadata"]["extra"])
        self.assertIn("3735928559", mensaje["session_id"])
        self.assertIn("3735928559", mensaje["metadata"]["reference_id"])

    def test_la_transformacion_se_declara_por_senal(self):
        """Declararla uniforme cuando algunas se convierten vuelve inutil el campo."""

        por_senal = {s["signal_name"]: s["transformation"]
                     for s in f1_25.catalogo_de_senales()}
        self.assertEqual(por_senal["speed"], "identity")
        self.assertEqual(por_senal["gear_selected"], "identity")
        self.assertEqual(por_senal["throttle_position"], "escala_x100")
        self.assertEqual(por_senal["brake_position"], "escala_x100")
        # Convertir a booleano tambien es una transformacion: declararla
        # como identidad seria el mismo defecto que se evita mas arriba.
        self.assertEqual(por_senal["drs_open"], "cast_bool")

    def test_distingue_adquisicion_en_vivo_de_reproduccion(self):
        """Un dato reproducido no sostiene las mismas afirmaciones de latencia."""

        vivo = f1_25.mensajes_desde_paquete(_telemetria(), INICIO)[0]
        repro = f1_25.mensajes_desde_paquete(
            _telemetria(), INICIO, origen=f1_25.ORIGEN_REPRODUCIDO,
            captura_sha256="a" * 64)[0]
        self.assertEqual(vivo["metadata"]["extra"]["origen_adquisicion"],
                         "consola_en_vivo")
        self.assertEqual(repro["metadata"]["extra"]["origen_adquisicion"],
                         "captura_reproducida")
        self.assertEqual(repro["metadata"]["extra"]["captura_sha256"], "a" * 64)

    def test_rechaza_un_origen_desconocido(self):
        with self.assertRaises(f1_25.ErrorNormalizacion):
            f1_25.mensajes_desde_paquete(_telemetria(), INICIO, origen="inventado")


class AlcanceTests(unittest.TestCase):
    """Restricciones de alcance que el adaptador hace cumplir."""

    def test_por_defecto_solo_normaliza_el_vehiculo_propio(self):
        """Los demas vehiculos son terceros; emitirlos contradice el alcance."""

        mensajes = f1_25.mensajes_desde_paquete(_telemetria(indice_propio=5), INICIO)
        vehiculos = {m["vehicle_id"] for m in mensajes}
        self.assertEqual(vehiculos, {"f1_25:session:3735928559:car:5"})

    def test_puede_pedirse_la_grilla_completa_de_forma_explicita(self):
        mensajes = f1_25.mensajes_desde_paquete(
            _telemetria(), INICIO, solo_vehiculo_propio=False)
        vehiculos = {m["vehicle_id"] for m in mensajes}
        self.assertEqual(len(vehiculos), f1_udp.VEHICULOS)

    def test_rechaza_un_paquete_no_decodificado(self):
        decodificado = f1_udp.decodificar(datagrama_sin_decodificador())
        with self.assertRaises(f1_25.ErrorNormalizacion):
            f1_25.mensajes_desde_paquete(decodificado, INICIO)


class EnergiaYDanoTests(unittest.TestCase):
    """Los canales que explican el rendimiento tienen que llegar a la base.

    Sin ellos la persistencia guarda que el vehiculo freno y no por que: una
    parada en boxes, una neutralizacion y una bajada de ritmo por bateria vacia
    se ven todas igual, como una caida de velocidad sin causa.
    """

    def _mensajes(self, packet_id: int) -> dict[str, object]:
        from tests.test_f1_udp import _datagrama_relleno
        decodificado = f1_udp.decodificar(_datagrama_relleno(packet_id))
        mensajes = f1_25.mensajes_desde_paquete(decodificado, INICIO)
        return {m["signal_name"]: m for m in mensajes}

    def test_la_unidad_de_potencia_se_normaliza(self):
        senales = self._mensajes(7)
        for nombre in ("ers_stored_energy", "ers_deployed_lap",
                       "ers_harvested_mguk_lap", "ers_harvested_mguh_lap",
                       "ers_deploy_mode", "fuel_mass"):
            with self.subTest(senal=nombre):
                self.assertIn(nombre, senales)
        self.assertEqual(senales["ers_stored_energy"]["unit"], "J")

    def test_el_dano_llega_desglosado_por_rueda(self):
        senales = self._mensajes(10)
        for rueda in ("rear_left", "rear_right", "front_left", "front_right"):
            with self.subTest(rueda=rueda):
                self.assertIn(f"tyre_wear_{rueda}", senales)
                self.assertIn(f"brake_damage_{rueda}", senales)

    def test_la_rueda_queda_en_el_nombre_y_no_en_un_indice(self):
        """Un indice obligaria a cada consulta a recordar el orden RL, RR, FL, FR."""

        senales = self._mensajes(10)
        self.assertNotIn("tyre_wear_0", senales)
        self.assertNotIn("tyre_wear", senales)

    def test_el_estado_de_boxes_viaja_con_los_datos_de_vuelta(self):
        senales = {m["signal_name"] for m in f1_25.mensajes_desde_paquete(
            f1_udp.decodificar(datagrama_vueltas(0)), INICIO)}
        for nombre in ("pit_status", "pit_stops_completed", "safety_car_delta",
                       "penalty_time", "lap_invalid"):
            with self.subTest(senal=nombre):
                self.assertIn(nombre, senales)

    def test_toda_senal_declara_su_transformacion(self):
        """Es la regla que este trabajo le reclama a la fuente deportiva."""

        for s in f1_25.catalogo_de_senales():
            with self.subTest(senal=s["signal_name"]):
                self.assertTrue(s["transformation"])
                self.assertTrue(s["campo_origen"])


class CatalogoDeSenalesTests(unittest.TestCase):
    """Lo que el adaptador dice que produce y lo que produce tienen que coincidir.

    El catalogo lo consume la vista para ofrecer las senales antes de que llegue
    la primera muestra. Si prometiera una senal que la normalizacion no emite,
    la vista mostraria una traza que nunca se llena; si omitiera una, esa senal
    seria invisible aunque estuviera guardada.

    No se compara contra una lista escrita en esta prueba —seria una tercera
    copia, que es el defecto que se viene corrigiendo— sino contra lo que sale
    de normalizar un paquete de cada clase.
    """

    def _emitidas(self) -> set[str]:
        from tests.test_f1_udp import _datagrama_relleno

        emitidas: set[str] = set()
        for packet_id in paquetes_normalizables():
            decodificado = f1_udp.decodificar(_datagrama_relleno(packet_id))
            for mensaje in f1_25.mensajes_desde_paquete(decodificado, INICIO):
                emitidas.add(mensaje["signal_name"])
        return emitidas

    def test_el_catalogo_es_exactamente_lo_que_se_emite(self):
        declaradas = {s["signal_name"] for s in f1_25.catalogo_de_senales()}
        self.assertEqual(declaradas, self._emitidas())

    def test_cada_entrada_declara_unidad_y_paquete(self):
        """La vista decide el rango por la unidad y agrupa por el paquete."""

        for entrada in f1_25.catalogo_de_senales():
            with self.subTest(senal=entrada["signal_name"]):
                self.assertTrue(entrada["unit"])
                self.assertIn(entrada["paquete"], f1_25.PAQUETES_NORMALIZABLES)

    def test_no_hay_nombres_repetidos(self):
        """Dos senales con el mismo nombre serian indistinguibles en la base."""

        nombres = [s["signal_name"] for s in f1_25.catalogo_de_senales()]
        self.assertEqual(len(nombres), len(set(nombres)))

    def test_las_unidades_del_catalogo_son_las_de_los_mensajes(self):
        """Un rango mal elegido por unidad equivocada deformaria la traza."""

        from tests.test_f1_udp import _datagrama_relleno

        declarada = {s["signal_name"]: s["unit"] for s in f1_25.catalogo_de_senales()}
        for packet_id in paquetes_normalizables():
            decodificado = f1_udp.decodificar(_datagrama_relleno(packet_id))
            for mensaje in f1_25.mensajes_desde_paquete(decodificado, INICIO):
                with self.subTest(senal=mensaje["signal_name"]):
                    self.assertEqual(mensaje["unit"],
                                     declarada[mensaje["signal_name"]])


class DosRelojesTests(unittest.TestCase):
    """El reloj de sesion y el de la captura viajan juntos.

    El reloj de sesion del juego **se detiene mientras los marcos siguen
    avanzando**: en la carrera capturada duro 1.377,86 s sobre 1.537 s reales, y
    207 marcos comparten su marca con el anterior. Eso lo vuelve inservible como
    clave y como medida de tiempo transcurrido, y sigue siendo el unico que
    alinea con el juego.

    Sustituir uno por otro cambiaria un punto ciego por el opuesto, de modo que
    el mensaje transporta los dos y declara cual es cual.
    """

    def test_el_mensaje_declara_el_desplazamiento_de_captura(self):
        mensajes = f1_25.mensajes_desde_paquete(
            _telemetria(), INICIO, desplazamiento_captura_us=1_234_567)
        for mensaje in mensajes:
            with self.subTest(senal=mensaje["signal_name"]):
                self.assertEqual(
                    mensaje["metadata"]["extra"]["desplazamiento_captura_us"],
                    1_234_567)

    def test_los_dos_relojes_son_campos_distintos(self):
        """Confundirlos es lo que haria pasar uno por el otro."""

        extra = f1_25.mensajes_desde_paquete(
            _telemetria(), INICIO,
            desplazamiento_captura_us=9_000_000)[0]["metadata"]["extra"]
        self.assertIn("session_time_s", extra)
        self.assertIn("desplazamiento_captura_us", extra)
        self.assertNotEqual(extra["session_time_s"],
                            extra["desplazamiento_captura_us"])

    def test_sin_desplazamiento_el_campo_se_declara_vacio(self):
        """Ausente y cero son cosas distintas: cero es un instante valido."""

        extra = f1_25.mensajes_desde_paquete(
            _telemetria(), INICIO)[0]["metadata"]["extra"]
        self.assertIsNone(extra["desplazamiento_captura_us"])

    def test_un_desplazamiento_cero_no_se_confunde_con_ausente(self):
        extra = f1_25.mensajes_desde_paquete(
            _telemetria(), INICIO,
            desplazamiento_captura_us=0)[0]["metadata"]["extra"]
        self.assertEqual(extra["desplazamiento_captura_us"], 0)
        self.assertIsNotNone(extra["desplazamiento_captura_us"])


if __name__ == "__main__":
    unittest.main()
