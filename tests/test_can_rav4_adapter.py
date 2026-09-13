"""Pruebas de la normalizacion de tramas CAN al contrato interno.

Lo que protegen no es la conversion sino **lo que se declara con ella**. Una
velocidad de rueda con escala del catalogo y una posicion de acelerador sin
unidad del fabricante son numeros del mismo tipo con respaldos muy distintos, y
el contrato tiene que poder distinguirlas sin mirar el valor.
"""

from __future__ import annotations

import unittest

from adapters import can_rav4
from backend import can_decoder
from backend.models import TelemetryMessage

INICIO = "2026-08-31T12:00:00+00:00"
SEGMENTO = "sample_01"


def trama(**bytes_por_indice: int) -> bytes:
    datos = bytearray(8)
    for clave, valor in bytes_por_indice.items():
        datos[int(clave[1:])] = valor
    return bytes(datos)


def mensajes(identificador: int, datos: bytes = None, instante_ns: int = 0):
    return can_rav4.mensajes_desde_trama(
        identificador, datos if datos is not None else trama(),
        instante_ns, INICIO, SEGMENTO, bus=0, captura_sha256="ab" * 32)


class ContratoTests(unittest.TestCase):
    """Los mensajes pasan la misma validacion que aplica el backend."""

    def test_validan_contra_el_contrato(self):
        for identificador in can_decoder.IDENTIFICADORES_RESPALDADOS:
            for mensaje in mensajes(identificador):
                with self.subTest(senal=mensaje["signal_name"]):
                    TelemetryMessage.model_validate(mensaje)

    def test_un_identificador_no_respaldado_no_produce_mensajes(self):
        self.assertEqual(mensajes(1234), [])

    def test_el_instante_se_suma_al_inicio_del_segmento(self):
        """El registro guarda nanosegundos relativos, no una fecha."""

        uno = mensajes(180, instante_ns=0)[0]
        otro = mensajes(180, instante_ns=1_500_000_000)[0]
        self.assertLess(uno["timestamp"], otro["timestamp"])
        self.assertIn("12:00:01.5", otro["timestamp"])

    def test_un_inicio_no_interpretable_falla_en_vez_de_inventar(self):
        with self.assertRaises(can_rav4.ErrorNormalizacion):
            can_rav4.mensajes_desde_trama(180, trama(), 0, "ayer", SEGMENTO)


class ProcedenciaTests(unittest.TestCase):
    """Lo que cada mensaje declara sobre de donde viene."""

    def test_declara_que_es_real_y_reproducido(self):
        """Las dos mitades del nombre dicen cosas distintas y las dos importan."""

        mensaje = mensajes(180)[0]
        self.assertEqual(mensaje["source_type"], "can_real_replay")
        self.assertFalse(mensaje["metadata"]["extra"]["simulated"])
        self.assertEqual(mensaje["metadata"]["extra"]["origen_adquisicion"],
                         "tramas_grabadas_reproducidas")

    def test_no_se_confunde_con_la_fuente_simulada_del_propio_trabajo(self):
        """El generador publica `can_simulated`; esto es otra cosa."""

        self.assertNotEqual(can_rav4.SOURCE_TYPE, "can_simulated")

    def test_el_identificador_can_y_el_bus_viajan_con_el_dato(self):
        """Son la trazabilidad de esta fuente, como el paquete lo es en la otra."""

        mensaje = mensajes(170)[0]
        self.assertEqual(mensaje["metadata"]["can_id"], 170)
        self.assertEqual(mensaje["metadata"]["reference_type"], "opendbc")
        self.assertIn("WHEEL_SPEEDS", mensaje["metadata"]["reference_id"])

    def test_la_confianza_viaja_con_cada_mensaje(self):
        """No se deduce del valor: dos numeros iguales pueden tener respaldos distintos."""

        alta = mensajes(170)[0]["metadata"]["extra"]
        media = mensajes(37)[0]["metadata"]["extra"]
        self.assertEqual(alta["confianza"], can_decoder.ALTA)
        self.assertEqual(media["confianza"], can_decoder.MEDIA_ALTA)
        self.assertTrue(media["limite"])

    def test_el_conductor_se_declara_ausente_y_no_se_inventa(self):
        """El conjunto es anonimo; rellenar el campo con el segmento seria falso."""

        mensaje = mensajes(180)[0]
        self.assertIn("no-identificado", mensaje["driver_id"])
        self.assertNotIn(SEGMENTO, mensaje["driver_id"])

    def test_toda_senal_declara_su_transformacion(self):
        for identificador in can_decoder.IDENTIFICADORES_RESPALDADOS:
            for mensaje in mensajes(identificador):
                with self.subTest(senal=mensaje["signal_name"]):
                    self.assertTrue(mensaje["metadata"]["extra"]["transformation"])


class NombresCanonicosTests(unittest.TestCase):
    """Las magnitudes que las tres fuentes comparten se llaman igual.

    Es lo que permite que un mismo analisis corra sobre las tres. Si cada
    adaptador nombrara la velocidad a su manera, el contrato seria un formato
    comun sin vocabulario comun, que no sirve de nada.
    """

    def test_la_velocidad_se_llama_como_en_las_otras_fuentes(self):
        self.assertEqual(mensajes(180)[0]["signal_name"], "speed")

    def test_las_ruedas_usan_el_mismo_sufijo_que_el_simulador(self):
        nombres = {m["signal_name"] for m in mensajes(170)}
        for sufijo in ("front_left", "front_right", "rear_left", "rear_right"):
            with self.subTest(rueda=sufijo):
                self.assertIn(f"wheel_speed_{sufijo}", nombres)

    def test_el_catalogo_es_lo_que_se_emite(self):
        """Igual que en el adaptador del simulador: una sola fuente de verdad."""

        declaradas = {s["signal_name"] for s in can_rav4.catalogo_de_senales()}
        emitidas = set()
        for identificador in can_decoder.IDENTIFICADORES_RESPALDADOS:
            emitidas.update(m["signal_name"] for m in mensajes(identificador))
        self.assertEqual(declaradas, emitidas)

    def test_el_catalogo_declara_confianza_por_senal(self):
        for entrada in can_rav4.catalogo_de_senales():
            with self.subTest(senal=entrada["signal_name"]):
                self.assertIn(entrada["confianza"],
                              (can_decoder.ALTA, can_decoder.MEDIA_ALTA))


class UnidadesTests(unittest.TestCase):
    """Cada fuente publica lo que mide, en la unidad en que lo mide."""

    def test_la_aceleracion_va_en_metros_por_segundo_al_cuadrado(self):
        """El simulador la entrega en unidades de g.

        Convertir aca cual de las dos es la correcta seria una decision de
        analisis disfrazada de normalizacion. La unidad se declara y la
        conversion queda donde corresponde.
        """

        por_nombre = {m["signal_name"]: m for m in mensajes(36)}
        self.assertEqual(por_nombre["accel_lateral"]["unit"], "m/s^2")
        self.assertEqual(por_nombre["accel_longitudinal"]["unit"], "m/s^2")

    def test_los_booleanos_se_publican_como_booleanos(self):
        mensaje = mensajes(550)[0]
        self.assertEqual(mensaje["unit"], "bool")
        self.assertIsInstance(mensaje["value"], bool)
        self.assertEqual(mensaje["metadata"]["extra"]["transformation"], "cast_bool")


if __name__ == "__main__":
    unittest.main()


class BusTransmitidoTests(unittest.TestCase):
    """Lo que el sistema de asistencia transmite no es medicion del vehiculo.

    El registrador marca con valores altos las tramas que el propio sistema
    emitio. Sobre la captura se verifico que 57.414 aparecen a la vez en el bus 0
    y en el 130 con bytes identicos en el cien por ciento de los casos: es
    reenvio, no una segunda medicion.

    Publicarlas duplicaria cada muestra —llevando la frecuencia aparente al doble
    de la real— y presentaria como medida del vehiculo lo que emitio un sistema
    agregado, que es justo la distincion que esta tesis cuida.
    """

    def test_las_tramas_transmitidas_no_producen_mensajes(self):
        self.assertEqual(
            can_rav4.mensajes_desde_trama(180, trama(b5=0x29, b6=0xCC), 0,
                                          INICIO, SEGMENTO, bus=130),
            [])

    def test_el_umbral_deja_pasar_los_buses_fisicos(self):
        for bus in (0, 1, 2):
            with self.subTest(bus=bus):
                self.assertTrue(
                    can_rav4.mensajes_desde_trama(180, trama(b5=0x29, b6=0xCC), 0,
                                                  INICIO, SEGMENTO, bus=bus))

    def test_el_descarte_ocurre_antes_de_decodificar(self):
        """Decodificar y filtrar despues invitaria a que un camino las deje pasar."""

        self.assertEqual(can_rav4.BUS_TRANSMITIDO_DESDE, 128)
        self.assertEqual(
            can_rav4.mensajes_desde_trama(170, trama(b0=0x1A, b1=0xF0), 0,
                                          INICIO, SEGMENTO, bus=128),
            [])


class IdentidadDeSesionTests(unittest.TestCase):
    """QUIEN SABE COMO SE LLAMA UNA SESION CAN, Y TIENE QUE SER UNO SOLO.

    El nombre `can:segmento:<segmento>` vivia unicamente dentro del texto que
    arma cada mensaje. La ingesta necesita ese mismo nombre **antes** de lanzar
    la carga, para poder poner al dia el catalogo cuando el proceso termine, y
    copiar la formula alli habria dejado dos duenos del mismo dato ---que es el
    defecto que este tablero ya arrastro cinco veces---.

    Esta prueba ata las dos puntas: lo que la funcion devuelve tiene que ser
    exactamente lo que el adaptador escribe en cada mensaje. Cambiar una sin la
    otra rompe aca, que es justamente para lo que sirve.
    """

    def test_es_exactamente_el_que_viaja_en_cada_mensaje(self):
        emitidos = {m["session_id"]
                    for identificador in can_decoder.IDENTIFICADORES_RESPALDADOS
                    for m in mensajes(identificador)}
        self.assertTrue(emitidos, "el adaptador no emitio ningun mensaje")
        self.assertEqual(emitidos, {can_rav4.identidad_de_sesion(SEGMENTO)})

    def test_dos_segmentos_distintos_no_comparten_sesion(self):
        """Si compartieran nombre, dos cargas se sumarian en una sola fila."""
        self.assertNotEqual(can_rav4.identidad_de_sesion("sample_01"),
                            can_rav4.identidad_de_sesion("sample_04"))
