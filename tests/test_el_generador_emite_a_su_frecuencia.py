# -*- coding: utf-8 -*-
"""El generador emite a la frecuencia que declara, y no a la que corre el bucle.

EL DEFECTO, MEDIDO EN LA RASPBERRY el 2026-09-13. Se corrio el generador del
capitulo 8 y dejo una sesion de verdad, pero:

    emitidos  51.000 mensajes
    guardados 42.889
    perdidos   8.111  (15,9 %)

La primera lectura ---«hay que arreglar la perdida»--- es la equivocada. El
intermediario no fallo: `errors=0`. Hizo lo que debe hacer un intermediario
frente a un productor mas rapido que su consumidor, que es descartar lo viejo.
Eso ya esta escrito en la cabecera de `scripts/republicar_captura.py`, que lo
aprendio perdiendo datos dos veces.

LO QUE DE VERDAD PASABA. El bucle de `main.py` **no esperaba nunca**: avanzaba
`tiempo_actual_ms += paso_ms`, que es tiempo logico, y corria tan rapido como
pudiera la maquina. Los sesenta segundos de la maniobra salieron en 1,886 s.

    señal                declarada    salio de verdad
    wheel_speed x4          100 Hz          3.181 Hz
    steer_angle             100 Hz          3.181 Hz
    speed                    50 Hz          1.591 Hz

Treinta y dos veces. Para tener escala: un bus CAN de chasis a 500 kbit/s
transporta unas 3.846 tramas por segundo **en total**; el generador emitio
27.041 mensajes por segundo, siete veces la capacidad entera del bus que dice
imitar.

POR QUE ESO IMPORTA MAS QUE LA PERDIDA. La tabla A.1 del informe declara, señal
por señal, la banda temporal del bus real: 50-100 Hz para las velocidades de
rueda y el angulo de direccion, 20-50 Hz para la velocidad, 20-100 Hz para los
pedales. `telemetry_generator/config.py` las respeta: **las doce señales caen
dentro de su banda**. O sea que el ritmo correcto no hay que elegirlo, ya esta
declarado; lo unico que faltaba era que el tiempo logico durara lo que dice.

Y arreglando eso la perdida se va sola: a 850 mensajes por segundo el consumidor
no necesita que nadie descarte nada.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from telemetry_generator import config as gen_config  # noqa: E402
from telemetry_generator import main as gen  # noqa: E402

#: Las bandas de la TABLA A.1 del informe, en Hz. Se copian aqui a proposito:
#: si alguien cambia un periodo del generador, esta prueba es la que tiene que
#: recordarle contra que evidencia se eligio.
BANDAS_A1 = {
    "speed": (20, 50), "wheel_speed_fl": (50, 100), "wheel_speed_fr": (50, 100),
    "wheel_speed_rl": (50, 100), "wheel_speed_rr": (50, 100),
    "steer_angle": (50, 100), "accel_x": (50, 100), "accel_y": (50, 100),
    "yaw_rate": (50, 100), "brake_pressed": (20, 100),
    "gas_pressed": (20, 100), "gas_pedal": (20, 100),
}


class ClienteFalso:
    """Un cliente MQTT que anota que se le pidio, sin red de por medio."""

    def __init__(self) -> None:
        self.publicados: list[tuple] = []
        self.conectado_a = None
        self.bucle_arrancado = False
        self.bucle_detenido = False
        self.desconectado = False
        self.esperas = 0

    def connect(self, host, port, keepalive=60):
        self.conectado_a = (host, port)

    def loop_start(self):
        self.bucle_arrancado = True

    def loop_stop(self):
        self.bucle_detenido = True

    def publish(self, topic, payload, qos=0):
        self.publicados.append((topic, payload, qos))
        return self

    def wait_for_publish(self, timeout=None):
        self.esperas += 1

    def disconnect(self):
        self.desconectado = True


class RelojFalso:
    """Cuenta cuanto se pidio dormir sin dormir nada."""

    def __init__(self) -> None:
        self.dormido_s = 0.0
        self.ahora = 0.0

    def sleep(self, segundos: float) -> None:
        self.dormido_s += segundos
        self.ahora += segundos

    def perf_counter(self) -> float:
        # El trabajo de cada ciclo se considera instantaneo: lo unico que avanza
        # el reloj es lo que el propio bucle decide dormir. Asi se mide la
        # intencion del ritmo y no la velocidad de esta maquina.
        return self.ahora


class ElRitmoEsElDeclarado(unittest.TestCase):

    def setUp(self) -> None:
        self.cliente = ClienteFalso()
        self.reloj = RelojFalso()
        parches = [
            patch.object(gen.mqtt, "Client", return_value=self.cliente),
            patch.object(gen.time, "sleep", self.reloj.sleep),
            patch.object(gen.time, "perf_counter", self.reloj.perf_counter),
            patch.object(gen, "print"),        # el bucle no imprime en la prueba
        ]
        for p in parches:
            p.start()
            self.addCleanup(p.stop)

    def _correr(self, ciclos: int = 1000, paso_ms: int = 10) -> None:
        gen.ejecutar_ciclos_simulados(cantidad_ciclos=ciclos, paso_ms=paso_ms)

    # ---- el ritmo ----

    def test_mil_ciclos_de_diez_milisegundos_tardan_diez_segundos(self) -> None:
        """El defecto entero, en una linea: el tiempo logico tiene que durar."""

        self._correr(ciclos=1000, paso_ms=10)
        self.assertAlmostEqual(
            self.reloj.dormido_s, 10.0, delta=0.2,
            msg="mil ciclos de 10 ms pidieron dormir %.3f s en vez de 10. El "
                "bucle sigue corriendo a la velocidad de la maquina y las "
                "frecuencias del informe no salen por el cable."
                % self.reloj.dormido_s)

    def test_la_maniobra_entera_dura_sus_sesenta_segundos(self) -> None:
        self._correr(ciclos=6000, paso_ms=10)
        self.assertAlmostEqual(self.reloj.dormido_s, 60.0, delta=1.0)

    def test_cada_senal_sale_a_la_frecuencia_que_declara(self) -> None:
        """Y esa frecuencia es la de la tabla A.1, no una elegida aqui."""

        import json
        from adapters import can_rav4
        self._correr(ciclos=1000, paso_ms=10)          # diez segundos

        # Se cuenta por el nombre que el generador conoce, no por el que
        # publica: desde que toma el mapa del adaptador, `wheel_speed_fl` sale
        # como `wheel_speed_front_left`. Las bandas de A.1 estan escritas con
        # los nombres del analisis del bus, que son los primeros, y esta
        # prueba tiene que poder leerse contra la tabla del informe.
        crudo_de = {canonico: crudo
                    for crudo, (canonico, _u) in can_rav4.SENALES.items()}
        cuenta: dict = {}
        for _tema, carga, _qos in self.cliente.publicados:
            publicado = json.loads(carga)["signal_name"]
            n = crudo_de.get(publicado, publicado)
            cuenta[n] = cuenta.get(n, 0) + 1

        for s in gen_config.MVP_SIGNALS:
            n = s["signal_name"]
            hz_medido = cuenta.get(n, 0) / 10.0
            lo, hi = BANDAS_A1[n]
            self.assertTrue(
                lo <= hz_medido <= hi,
                "%s salio a %.0f Hz y la tabla A.1 declara %d-%d Hz"
                % (n, hz_medido, lo, hi))

    def test_el_ritmo_no_se_desfasa_acumulando_esperas(self) -> None:
        """Se cuenta contra el comienzo, no sumando un `sleep` fijo por ciclo.

        Es la misma correccion que ya lleva `republicar_captura.py`: dormir un
        rato fijo por mensaje acumula el error de cada espera y el ritmo real
        termina por debajo del pedido.
        """

        self._correr(ciclos=3000, paso_ms=10)
        self.assertAlmostEqual(
            self.reloj.dormido_s, 30.0, delta=0.5,
            msg="a los 3000 ciclos el desfase ya es de %.2f s"
                % abs(self.reloj.dormido_s - 30.0))

    # ---- el transporte ----

    def test_publica_con_calidad_de_servicio_uno(self) -> None:
        """Los otros cuatro publicadores del proyecto usan 1. Este usaba 0."""

        self._correr(ciclos=10)
        calidades = {q for _t, _c, q in self.cliente.publicados}
        self.assertEqual(
            calidades, {1},
            "sigue publicando con calidad %r: es la configuracion que le costo "
            "al proyecto 107.265 filas en republicar_captura.py" % calidades)

    def test_el_destino_sale_de_la_configuracion_del_proyecto(self) -> None:
        """Estaba escrito `localhost` a mano: en contenedor no se conecta."""

        from backend import config as cfg
        self._correr(ciclos=10)
        self.assertEqual(
            self.cliente.conectado_a, (cfg.MQTT_HOST, cfg.MQTT_PORT),
            "el generador se conecta a %r en vez de a lo que declara "
            "backend.config" % (self.cliente.conectado_a,))
        temas = {t for t, _c, _q in self.cliente.publicados}
        self.assertEqual(temas, {cfg.MQTT_TOPIC})

    def test_hay_bucle_de_red_y_se_espera_antes_de_cerrar(self) -> None:
        """Sin bucle, la calidad 1 no confirma nada; sin espera, se corta."""

        self._correr(ciclos=10)
        self.assertTrue(self.cliente.bucle_arrancado,
                        "no se arranco el bucle de red: con qos 1 los mensajes "
                        "quedan esperando un hilo que nadie corre")
        self.assertGreater(self.cliente.esperas, 0,
                           "se desconecto sin esperar la confirmacion del ultimo "
                           "bloque")
        self.assertTrue(self.cliente.desconectado)


class LoQueDeclaraElCatalogo(unittest.TestCase):
    """El catalogo del generador tiene que decir lo mismo que la tabla A.1."""

    def _por_nombre(self, nombre):
        return next(s for s in gen_config.MVP_SIGNALS
                    if s["signal_name"] == nombre)

    def test_las_doce_senales_caen_dentro_de_su_banda(self) -> None:
        for s in gen_config.MVP_SIGNALS:
            n = s["signal_name"]
            hz = 1000 / s["period_ms"]
            lo, hi = BANDAS_A1[n]
            self.assertTrue(lo <= hz <= hi,
                            "%s declara %.0f Hz y A.1 dice %d-%d Hz" % (n, hz, lo, hi))

    def test_el_acelerador_declara_el_identificador_que_el_analisis_encontro(self) -> None:
        """El generador decia «no posee un ID CAN validado». A.1 dice ID 865.

        Cuando se escribio el generador era cierto. Despues el analisis del
        capitulo 7 evaluo cuatro candidatos y adopto el 865, el unico que
        responde en las dos variantes de la plataforma: 55.904 pares
        temporales, varia en 26 de 30 segmentos y correlacion de Pearson 0,829.
        El 705, que A.1 declaraba antes, varia en 9 de 30. Un catalogo que dice
        «no hay evidencia» sobre algo que ya tiene evidencia no es prudente:
        esta desactualizado, que es distinto.
        """

        self.assertEqual(
            self._por_nombre("gas_pedal")["can_id"], 865,
            "el acelerador no declara el ID 865 que la tabla A.1 "
            "sostiene con 55.904 pares temporales")


if __name__ == "__main__":
    unittest.main()
