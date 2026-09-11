# -*- coding: utf-8 -*-
"""La ventana del anotador cuando el tiempo no avanza.

EL DEFECTO QUE ESTO CUIDA. `_podar` recorta la serie con

    while serie and (t - serie[0][0]) > VENTANA_CAIDA_S:
        serie.popleft()

y eso da por sentado que `t` **siempre crece**. Si llega una muestra anterior a
la que abrio la serie, la resta es negativa, la condicion es falsa y **no se
poda nunca mas**: la cola crece sin limite. `_caida` la recorre entera en cada
muestra, de modo que el costo por muestra crece con la sesion y el recorrido
completo se vuelve cuadratico.

MEDIDO el 2026-09-11 sobre `f1_25:session:3527452921763583202` en la Pi, coche
propio, 216.318 muestras:

    muestra       len(_frenos)   instante del anotador     salto
          0                  0            1789095191,1
     20.000                303            1789094308,4    -882,7 s
     40.000              1.172            1789094351,9     +43,5 s
    200.000              8.129            1789094699,6     +43,5 s

Ocho mil ochocientas treinta y ocho entradas para una ventana de **0,5 s**. El
costo por muestra crecia 30 -> 155 -> 297 -> 459 us a lo largo de la sesion, y
`_caida` se llevaba el **85 %** del tiempo. Los 73 s de `/avisos` eran eso: la
consulta entera tarda 0,9 s.

DE DONDE SALE EL RETROCESO. La lectura ordena por desplazamiento de captura y
esta sesion tiene **dos capturas pegadas**; la segunda empieza su reloj de
captura casi en cero y por eso sus filas salen primero, con instantes
posteriores. 302 de las 216.318 muestras van hacia atras, la mayor por 911,9 s.

Y NO ES SOLO LENTITUD. Con la serie sin podar, `_caida` comparaba la velocidad
de ahora contra una de **minutos** antes en vez de la de hace medio segundo, y
el maximo de freno se tomaba sobre toda la sesion: la regla de caida brusca
quedaba efectivamente muerta. Esto no es una optimizacion: es una regla que
volvio a funcionar.

VALE PARA EL VIVO TAMBIEN. El mismo anotador observa el flujo en directo, donde
un reloj que se corre o una captura que se reinicia producen el mismo salto.
"""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from backend import anotador_vivo  # noqa: E402


def mensaje(senal: str, valor: float, t: float) -> dict:
    return {"signal_name": senal, "value": valor, "timestamp": t}


def marco(t: float, **canales: float) -> list[dict]:
    return [mensaje(nombre, valor, t) for nombre, valor in canales.items()]


def asfalto(t: float) -> list[dict]:
    return marco(t, **{f"surface_type_{r}": 0 for r in anotador_vivo.RUEDAS})


def rodando(desde: float, marcos: int, paso: float = 0.05) -> list[dict]:
    salida: list[dict] = []
    for i in range(marcos):
        t = desde + i * paso
        salida += asfalto(t)
        salida += marco(t, speed=200.0, throttle_position=90.0, brake_position=0.0,
                        g_force_vertical=0.06, lap_number=1,
                        lap_distance=100.0 + i * 5,
                        wheel_slip_ratio_rear_left=0.02,
                        wheel_slip_ratio_rear_right=0.02)
    return salida


class LaVentanaNoCreceAunqueElTiempoRetrocedaTests(unittest.TestCase):

    def test_un_salto_hacia_atras_no_deja_la_serie_sin_podar(self) -> None:
        anotador = anotador_vivo.Anotador()
        # Primero una muestra tardia, como la que la segunda captura pone
        # adelante al ordenar por desplazamiento de captura.
        for m in marco(1000.0, speed=200.0, brake_position=0.0):
            anotador.observar(m)
        # Y despues la sesion entera, que ocurre antes.
        for m in rodando(0.0, 400):
            anotador.observar(m)

        ventana = anotador_vivo.VENTANA_CAIDA_S
        self.assertLessEqual(
            len(anotador._velocidades), 40,
            "la serie de velocidades quedo con %d entradas para una ventana de "
            "%s s: no se poda cuando el tiempo retrocede"
            % (len(anotador._velocidades), ventana))
        self.assertLessEqual(
            len(anotador._frenos), 40,
            "la serie de frenos quedo con %d entradas para una ventana de %s s"
            % (len(anotador._frenos), ventana))

    def test_la_serie_solo_conserva_lo_que_cae_en_la_ventana(self) -> None:
        anotador = anotador_vivo.Anotador()
        for m in rodando(0.0, 200):
            anotador.observar(m)
        ultimo = anotador._velocidades[-1][0]
        for marca, _ in anotador._velocidades:
            self.assertLessEqual(
                ultimo - marca, anotador_vivo.VENTANA_CAIDA_S + 1e-9,
                "quedo en la serie una muestra de hace %.2f s, fuera de la "
                "ventana de %s s" % (ultimo - marca, anotador_vivo.VENTANA_CAIDA_S))
            self.assertGreaterEqual(
                ultimo - marca, -1e-9,
                "quedo en la serie una muestra posterior al instante actual")

    def test_el_costo_por_muestra_no_crece_con_la_sesion(self) -> None:
        """Lo cuadratico se ve como un tramo que tarda mucho mas que el anterior.

        Se comparan dos tramos del mismo largo, uno al principio y otro al
        final. Con la serie sin podar el segundo tardaba varias veces mas; con
        la ventana acotada tienen que parecerse. El margen es amplio a
        proposito: lo que se persigue es un crecimiento con la cantidad de
        muestras, no unos milisegundos de diferencia.
        """

        anotador = anotador_vivo.Anotador()
        for m in marco(1000.0, speed=200.0, brake_position=0.0):
            anotador.observar(m)

        def tramo(desde: float) -> float:
            mensajes = rodando(desde, 300)
            comienzo = time.perf_counter()
            for m in mensajes:
                anotador.observar(m)
            return time.perf_counter() - comienzo

        primero = tramo(0.0)
        for _ in range(6):                      # se alarga la sesion
            tramo(100.0 + _ * 20.0)
        ultimo = tramo(500.0)

        self.assertLess(
            ultimo, primero * 4 + 0.05,
            "el ultimo tramo tardo %.3f s contra %.3f s del primero: el costo "
            "por muestra crece con la sesion" % (ultimo, primero))


class LaReglaDeCaidaSigueDiciendoLoMismoTests(unittest.TestCase):
    """Podar bien no puede cambiar lo que la regla afirma."""

    def test_una_caida_sin_frenar_se_sigue_anotando(self) -> None:
        anotador = anotador_vivo.Anotador()
        for m in rodando(0.0, 10):
            anotador.observar(m)
        velocidad = 300.0
        for i in range(10):
            t = 1.0 + i * 0.05
            velocidad -= 12.0
            for m in asfalto(t):
                anotador.observar(m)
            for m in marco(t, speed=velocidad, throttle_position=0.0,
                           brake_position=0.0, g_force_vertical=0.1):
                anotador.observar(m)
        anotador.cerrar_pendiente()
        self.assertTrue(
            any("caida brusca" in (a.get("titulo") or "") for a in anotador.anotaciones),
            "la caida sin frenar dejo de anotarse: " +
            repr([a.get("titulo") for a in anotador.anotaciones]))

    def test_una_frenada_fuerte_sigue_sin_ser_una_caida(self) -> None:
        anotador = anotador_vivo.Anotador()
        for m in rodando(0.0, 10):
            anotador.observar(m)
        velocidad = 300.0
        for i in range(10):
            t = 1.0 + i * 0.05
            velocidad -= 12.0
            for m in asfalto(t):
                anotador.observar(m)
            for m in marco(t, speed=velocidad, throttle_position=0.0,
                           brake_position=0.0 if i == 9 else 100.0,
                           g_force_vertical=0.1):
                anotador.observar(m)
        anotador.cerrar_pendiente()
        self.assertFalse(
            any("caida brusca" in (a.get("titulo") or "") for a in anotador.anotaciones),
            "una frenada normal volvio a contarse como caida brusca")

    def test_despues_del_salto_la_regla_vuelve_a_verse(self) -> None:
        """Con la serie sucia de la muestra tardia, la caida no se detectaba."""

        anotador = anotador_vivo.Anotador()
        for m in marco(1000.0, speed=200.0, brake_position=0.0):
            anotador.observar(m)
        for m in rodando(0.0, 10):
            anotador.observar(m)
        velocidad = 300.0
        for i in range(10):
            t = 1.0 + i * 0.05
            velocidad -= 12.0
            for m in asfalto(t):
                anotador.observar(m)
            for m in marco(t, speed=velocidad, throttle_position=0.0,
                           brake_position=0.0, g_force_vertical=0.1):
                anotador.observar(m)
        anotador.cerrar_pendiente()
        self.assertTrue(
            any("caida brusca" in (a.get("titulo") or "") for a in anotador.anotaciones),
            "despues de un salto hacia atras la regla de caida quedo muda")


if __name__ == "__main__":
    unittest.main()
