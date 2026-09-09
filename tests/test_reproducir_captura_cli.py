# -*- coding: utf-8 -*-
"""La interfaz de linea de comandos del reproductor de capturas.

Que agrega sobre el modulo que ya estaba probado
------------------------------------------------
`backend.f1_capture.reproducir` sabe recorrer y degradar, y **no abre ningun
socket**: corrige el instante de cada datagrama y lo devuelve. Lo que falta y esta
script aporta es respetar esos instantes en el tiempo real y emitir.

Eso introduce dos cosas nuevas que pueden fallar en silencio:

1. **el calendario**: si las esperas se acumulan una sobre la otra en lugar de
   calcularse contra el arranque, el reloj se corre y la reproduccion dura
   distinto que la captura, sin que nada avise;
2. **la definicion de atraso**: contar como incumplimiento un desvio de
   microsegundos informaba un 84 % de atrasos sobre un calendario que en realidad
   se respetaba con un desvio mediano de 0,32 ms. Los datagramas de un mismo
   instante salen uno detras del otro, y el segundo **siempre** llega tarde por
   microsegundos. Eso es la forma del trafico, no un defecto.

Todas las pruebas corren con `sin_red=True`: emitir no es lo que hay que
verificar, y abrir un socket volveria las pruebas dependientes del entorno.
"""

from __future__ import annotations

import statistics
import sys
import time
import unittest
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

import reproducir_captura_f1_25 as cli  # noqa: E402

from backend import f1_capture  # noqa: E402

DESTINO = ("127.0.0.1", 20777)


@lru_cache(maxsize=None)
def _piso_del_planificador(objetivo_us: int, muestras: int = 15) -> float:
    """Cuanto se pasa de largo un `sleep` en esta maquina, en microsegundos.

    POR QUE HAY QUE MEDIRLO Y NO ALCANZA CON UN NUMERO
    --------------------------------------------------
    Las pruebas del calendario tienen que distinguir **un atraso sistematico
    del reproductor** del temblor del planificador del sistema operativo. Los
    umbrales de este archivo se calibraron midiendo ese temblor sobre Windows,
    donde la mediana de desvio ronda los 350 microsegundos, y quedaron escritos
    como numeros absolutos.

    Ese piso no es una constante del universo sino de la maquina. Medido sobre
    macOS con Apple Silicon el 2026-09-08, con el equipo ocioso: un `sleep` de
    50 ms se pasa **4,0 ms de mediana** y uno de 10 ms se pasa 2,3 ms. Contra
    un piso de cuatro milisegundos, un techo de uno no lo puede cruzar ningun
    reproductor, por bien que respete el calendario: la prueba deja de hablar
    del codigo y pasa a hablar del sistema operativo.

    Asi que se mide, y los umbrales se expresan contra lo medido. La prueba
    conserva exactamente lo que sabia detectar ---un defecto acumula el error
    en **todos** los datagramas y mueve la mediana un orden de magnitud, no un
    factor de dos--- y deja de fallar por algo que el codigo no gobierna.

    Se mide una sola vez por intervalo, y por eso esta cacheada: la suite
    completa paga menos de un segundo por las dos mediciones que usa.
    """

    objetivo_s = objetivo_us / 1e6
    desvios_us = []
    for _ in range(muestras):
        antes = time.perf_counter()
        time.sleep(objetivo_s)
        desvios_us.append((time.perf_counter() - antes - objetivo_s) * 1e6)
    return max(0.0, statistics.median(desvios_us))


def _captura(directorio: Path, intervalos_us: list[int],
             carga: bytes = b"x" * 40) -> Path:
    """Arma una captura sintetica con los intervalos pedidos."""

    ruta = directorio / "sintetica.f1raw"
    with f1_capture.EscritorCaptura(ruta) as w:
        t = 0
        for dt in intervalos_us:
            t += dt
            w.escribir(t, carga)
    return ruta


class ConciliaLoQueHizo(unittest.TestCase):
    """Lo leido tiene que ser lo descartado mas lo emitido, siempre."""

    def test_sin_degradacion_emite_todo(self):
        with TemporaryDirectory() as d:
            ruta = _captura(Path(d), [1000] * 50)
            r = cli.reproducir_por_udp(ruta, DESTINO,
                                       f1_capture.PerfilDegradacion(),
                                       velocidad=1000.0, sin_red=True)
        self.assertEqual(r["leidos"], 50)
        self.assertEqual(r["enviados"], 50)
        self.assertEqual(r["descartados"], 0)

    def test_con_descarte_la_cuenta_cierra(self):
        with TemporaryDirectory() as d:
            ruta = _captura(Path(d), [1000] * 400)
            perfil = f1_capture.PerfilDegradacion(
                probabilidad_descarte=0.25, semilla=11)
            r = cli.reproducir_por_udp(ruta, DESTINO, perfil,
                                       velocidad=1000.0, sin_red=True)
        self.assertEqual(r["leidos"], r["descartados"] + r["enviados"])
        self.assertEqual(r["leidos"], 400)

    def test_el_descarte_se_acerca_al_pedido(self):
        """Con cuatrocientos sorteos, un cuarto pedido cae cerca de un cuarto."""

        with TemporaryDirectory() as d:
            ruta = _captura(Path(d), [1000] * 400)
            perfil = f1_capture.PerfilDegradacion(
                probabilidad_descarte=0.25, semilla=11)
            r = cli.reproducir_por_udp(ruta, DESTINO, perfil,
                                       velocidad=1000.0, sin_red=True)
        self.assertAlmostEqual(r["tasa_descarte"], 0.25, delta=0.06)

    def test_la_misma_semilla_repite_exactamente_la_degradacion(self):
        """Sin esto un escenario experimental no se puede repetir."""

        with TemporaryDirectory() as d:
            ruta = _captura(Path(d), [1000] * 300)
            salidas = []
            for _ in range(2):
                perfil = f1_capture.PerfilDegradacion(
                    probabilidad_descarte=0.3, semilla=99)
                salidas.append(cli.reproducir_por_udp(
                    ruta, DESTINO, perfil, velocidad=1000.0, sin_red=True))
        self.assertEqual(salidas[0]["descartados"], salidas[1]["descartados"])

    def test_semillas_distintas_dan_degradaciones_distintas(self):
        """El control negativo de la prueba anterior."""

        with TemporaryDirectory() as d:
            ruta = _captura(Path(d), [1000] * 300)
            salidas = []
            for semilla in (1, 2):
                perfil = f1_capture.PerfilDegradacion(
                    probabilidad_descarte=0.3, semilla=semilla)
                salidas.append(cli.reproducir_por_udp(
                    ruta, DESTINO, perfil, velocidad=1000.0, sin_red=True))
        self.assertNotEqual(salidas[0]["descartados"], salidas[1]["descartados"])


class RespetaElCalendario(unittest.TestCase):
    """La duracion tiene que salir de la captura, no de lo que tarde el codigo."""

    def test_reproduce_en_el_tiempo_de_la_captura(self):
        # Veinte datagramas cada 50 ms es un segundo de captura. A velocidad
        # cuatro tiene que tardar alrededor de un cuarto de segundo.
        with TemporaryDirectory() as d:
            ruta = _captura(Path(d), [50_000] * 20)
            r = cli.reproducir_por_udp(ruta, DESTINO,
                                       f1_capture.PerfilDegradacion(),
                                       velocidad=4.0, sin_red=True)
        self.assertAlmostEqual(r["duracion_s"], 0.25, delta=0.12)

    def test_la_velocidad_acorta_proporcionalmente(self):
        with TemporaryDirectory() as d:
            ruta = _captura(Path(d), [20_000] * 25)
            lento = cli.reproducir_por_udp(ruta, DESTINO,
                                           f1_capture.PerfilDegradacion(),
                                           velocidad=1.0, sin_red=True)
            rapido = cli.reproducir_por_udp(ruta, DESTINO,
                                            f1_capture.PerfilDegradacion(),
                                            velocidad=5.0, sin_red=True)
        self.assertGreater(lento["duracion_s"], rapido["duracion_s"] * 2)

    def test_el_desvio_no_crece_a_lo_largo_de_la_reproduccion(self):
        """La prueba del error acumulado.

        Si el calendario se calculara contra el datagrama anterior en lugar de
        contra el arranque, cada espera agregaria su propio error y el desvio
        del ultimo datagrama seria mucho mayor que el del primero.

        Se mira **la mediana y no el maximo**, y el motivo se midio
        -----------------------------------------------------------
        La version anterior exigia un maximo por debajo de 20 ms y fallaba tres
        de cada cuatro corridas **con la maquina al uno por ciento de CPU**. No
        era un defecto del reproductor: sobre este sistema operativo un
        `sleep` de 50 ms tarda a veces 90, y la resolucion del temporizador
        ---comprobada en un milisegundo, la fina--- no lo evita.

        La prueba le estaba reclamando al codigo algo que hace el planificador
        del sistema. Y una prueba que falla por ruido tres de cada cuatro veces
        **es peor que no tenerla**: ensena a ignorar los fallos.

        La mediana separa las dos responsabilidades. El temblor del sistema
        operativo es esporadico y no la mueve; **la acumulacion la moveria
        entera**, porque afectaria a todos los datagramas y no a unos pocos. En
        corridas normales la mediana es de unos 400 microsegundos.
        """

        with TemporaryDirectory() as d:
            ruta = _captura(Path(d), [10_000] * 60)
            r = cli.reproducir_por_udp(ruta, DESTINO,
                                       f1_capture.PerfilDegradacion(),
                                       velocidad=1.0, sin_red=True)
        # Sesenta datagramas de 10 ms: si el error se acumulara, la mediana
        # llegaria al orden de cientos de milisegundos, no a medio milisegundo.
        #
        # El techo es el mayor entre el valor calibrado y el doble del piso
        # medido, de modo que **en la maquina donde se calibro no cambia nada**
        # ---alli el piso es chico y gana el 5.000--- y en una con el
        # planificador mas grueso deja de reclamarle al codigo lo que hace el
        # sistema operativo. Un factor de dos sobre el piso sigue estando dos
        # ordenes de magnitud por debajo de lo que produciria la acumulacion.
        techo_us = max(5_000, 2 * _piso_del_planificador(10_000))
        self.assertLess(r["desvio_mediano_us"], techo_us)
        # Y un techo generoso, por si el reproductor se volviera lento de forma
        # pareja: eso la mediana **si** lo detectaria, pero el techo lo declara
        # sin ambiguedad. El valor sale del ruido medido ---decenas de
        # milisegundos--- con un factor de cinco, no de una intuicion.
        self.assertLess(r["desvio_maximo_us"], 200_000)


class DefinicionDeAtraso(unittest.TestCase):
    """Atraso es pasarse de la tolerancia, no correrse un microsegundo."""

    def test_a_velocidad_real_los_atrasos_son_la_excepcion(self):
        """A ritmo real el reproductor no se atrasa de forma sistematica.

        No se exige **cero**, y no por indulgencia: la tolerancia declarada es
        de un milisegundo y el piso de ruido del sistema operativo esta por
        encima. Un `sleep` de 50 ms tarda a veces 90 con la maquina ociosa, de
        modo que exigir cero atrasos es exigir que Windows no tiemble.

        Lo que la prueba tiene que distinguir es **un atraso sistematico de uno
        esporadico**. Un reproductor que no respeta el calendario los produce en
        casi todos los datagramas; el temblor del sistema, en uno de cada
        tantos. Con veinte datagramas, un atraso es ruido y quince son un
        defecto.
        """

        # LA TOLERANCIA TIENE QUE ESTAR POR ENCIMA DEL PISO DEL SISTEMA, o la
        # palabra «atraso» deja de significar algo. Con la tolerancia fija en
        # un milisegundo y un planificador que se pasa cuatro, los veinte
        # datagramas son «atrasados» sin que el reproductor haya hecho nada
        # mal: el conteo mediria el sistema operativo y no el calendario.
        piso_us = _piso_del_planificador(50_000)
        tolerancia_ms = max(1.0, 2 * piso_us / 1000)

        with TemporaryDirectory() as d:
            ruta = _captura(Path(d), [50_000] * 20)
            r = cli.reproducir_por_udp(ruta, DESTINO,
                                       f1_capture.PerfilDegradacion(),
                                       velocidad=1.0, sin_red=True,
                                       tolerancia_ms=tolerancia_ms)
        # **La mediana es la que detecta; el conteo es solo el respaldo.**
        #
        # Un atraso sistematico mueve la mediana entera, porque afecta a todos
        # los datagramas. En corridas normales ronda los 350 microsegundos,
        # menos de la mitad de la tolerancia declarada: si el reproductor
        # dejara de respetar el calendario, esto salta sin ambiguedad.
        #
        # El techo se expresa contra el piso medido por el mismo motivo que la
        # tolerancia. En la maquina donde se calibro gana el 1.000 y la prueba
        # queda **identica**; en una mas gruesa sigue detectando lo que tiene
        # que detectar, porque un reproductor que no respeta el calendario se
        # atrasa los 50 ms enteros de cada datagrama y no cuatro.
        self.assertLess(r["desvio_mediano_us"], max(1_000, 2 * piso_us))
        # El conteo va holgado a proposito. Un primer umbral de dos sobre veinte
        # todavia fallaba una de cada diez corridas: estaba ajustado a lo
        # observado en unas pocas y no al ruido real. Cinco sobre veinte sigue
        # estando cuatro veces por debajo de lo que produciria un defecto, que
        # atrasaria casi todos.
        self.assertLessEqual(r["atrasados"], 5)

    def test_una_velocidad_imposible_declara_los_atrasos(self):
        """Es la senal que hay que ver: el perfil pedido no se respeto."""

        with TemporaryDirectory() as d:
            ruta = _captura(Path(d), [1000] * 500)
            r = cli.reproducir_por_udp(ruta, DESTINO,
                                       f1_capture.PerfilDegradacion(),
                                       velocidad=10_000.0, sin_red=True,
                                       tolerancia_ms=0.05)
        self.assertGreater(r["atrasados"], 0)

    def test_la_tolerancia_queda_registrada_en_el_resultado(self):
        """Un conteo de atrasos sin su umbral no se puede interpretar."""

        with TemporaryDirectory() as d:
            ruta = _captura(Path(d), [1000] * 20)
            r = cli.reproducir_por_udp(ruta, DESTINO,
                                       f1_capture.PerfilDegradacion(),
                                       velocidad=100.0, sin_red=True,
                                       tolerancia_ms=3.0)
        self.assertEqual(r["tolerancia_ms"], 3.0)

    def test_la_tolerancia_por_omision_es_menor_que_el_jitter_de_la_fuente(self):
        """El umbral sale de la fuente y no del gusto.

        La propia F1 25 alterna intervalos de 34 y 66 ms donde promete 50: su
        irregularidad es de decenas de milisegundos. Una tolerancia de un
        milisegundo es, frente a eso, exigente.
        """

        self.assertLessEqual(cli.TOLERANCIA_MS, 2.0)


class RechazaLoQueNoPuedeReproducir(unittest.TestCase):

    def test_una_probabilidad_fuera_de_rango_no_se_acepta(self):
        with self.assertRaises(ValueError):
            f1_capture.PerfilDegradacion(probabilidad_descarte=1.5).validar()

    def test_un_jitter_negativo_no_se_acepta(self):
        """El jitter es una desviacion: su signo no significa nada."""

        with self.assertRaises(ValueError):
            f1_capture.PerfilDegradacion(jitter_us=-1).validar()

    def test_el_limite_corta_sin_romper_el_recuento(self):
        with TemporaryDirectory() as d:
            ruta = _captura(Path(d), [1000] * 200)
            r = cli.reproducir_por_udp(ruta, DESTINO,
                                       f1_capture.PerfilDegradacion(),
                                       velocidad=1000.0, sin_red=True,
                                       limite=30)
        self.assertEqual(r["enviados"], 30)
        self.assertLessEqual(r["leidos"], 200)


if __name__ == "__main__":
    unittest.main()
