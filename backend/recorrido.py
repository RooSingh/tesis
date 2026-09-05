# -*- coding: utf-8 -*-
"""Reconstruye el recorrido de un vehiculo a partir de velocidad y guinada.

Por que vive aca y no en un script
----------------------------------
Lo usan dos consumidores: el script que genera la figura del informe y la
interfaz que lo dibuja en el tablero. Tenerlo en un solo lugar es lo que evita
que las dos versiones se separen y terminen mostrando recorridos distintos para
el mismo dato.

Que es y que no es
------------------
Es una **derivacion**: el rumbo se obtiene integrando la velocidad de guinada, y
la posicion integrando la velocidad proyectada sobre ese rumbo. La forma
resultante es la real; **la orientacion absoluta y la ubicacion en el mundo no**,
porque el registro del vehiculo de calle no trae coordenadas.

Cuanto se equivoca, medido
--------------------------
El metodo se calibro contra una fuente que si transmite su posicion: sobre 3,99
kilometros continuos, la mediana del apartamiento es de **5,8 metros**, el 0,15 %
de la distancia, y no crece de forma sostenida. Ese numero caracteriza al metodo
y **no se transfiere entre vehiculos**: lo transferible es la forma en que el
error se comporta, no su magnitud.
"""

from __future__ import annotations

import math

# Hueco a partir del cual no se integra. Entre dos muestras muy separadas no se
# sabe que hizo el vehiculo, y suponer que mantuvo rumbo y velocidad inventaria
# recorrido.
HUECO_MAXIMO_S = 1.0

# Giro por debajo del cual la diferencia entre ruedas es ruido de cuantizacion y
# no senal. Sin este piso, los tramos rectos ---que son la mayoria--- dominan el
# ajuste con puntos que no contienen informacion sobre el giro.
GIRO_MINIMO_DEG_S = 1.0

# Velocidad por debajo de la cual la comprobacion contra las ruedas **no aplica**.
#
# La relacion entre el giro y la diferencia de ruedas es geometrica y supone las
# ruedas girando. Con el vehiculo detenido o casi, esa diferencia es ruido de
# cuantizacion mientras el sensor de guinada sigue informando, y el ajuste sale
# cualquier cosa.
#
# No es una precaucion teorica. Sin este piso, un segmento con paradas daba un
# ancho de via de **0,44 metros** con correlacion 0,25; con el piso da **1,55
# metros con correlacion 0,99**. Un segmento que nunca se detuvo daba bien en los
# dos casos, de modo que el defecto solo aparecia en algunos datos ---que es la
# peor forma de que aparezca---.
VELOCIDAD_MINIMA_KMH = 5.0

RUEDAS = ("wheel_speed_front_left", "wheel_speed_front_right",
          "wheel_speed_rear_left", "wheel_speed_rear_right")


def emparejar(series: dict, principal: str, *acompanantes: str) -> list[tuple]:
    """Alinea senales que **no llegan en el mismo instante**.

    Cada senal viene de su propio identificador, con su propio periodo, de modo
    que exigir que dos coincidan exactamente en el milisegundo es un error de
    metodo: en un segmento coincidieron por casualidad y en otro la interseccion
    quedo **vacia**, y la reconstruccion devolvio un recorrido de cero metros sin
    que nada fallara.

    Se alinean sosteniendo el ultimo valor conocido de cada acompanante, que es
    lo que un consumidor puede hacer con un flujo asincronico y lo unico que no
    inventa datos. Se descartan los instantes previos a la primera lectura de
    cada senal, porque ahi no hay valor que sostener.
    """

    if principal not in series:
        return []
    eventos = sorted((t, principal, v) for t, v in series[principal].items())
    for nombre in acompanantes:
        eventos += [(t, nombre, v) for t, v in series.get(nombre, {}).items()]
    eventos.sort()

    ultimo: dict[str, float] = {}
    salida = []
    for t, nombre, v in eventos:
        ultimo[nombre] = v
        if nombre != principal:
            continue
        if any(a not in ultimo for a in acompanantes):
            continue
        salida.append((t, v, *(ultimo[a] for a in acompanantes)))
    return salida


def reconstruir(series: dict) -> dict:
    """Integra rumbo y posicion desde `speed` (km/h) y `yaw_rate` (deg/s).

    Los instantes se esperan en milisegundos. La guinada viene en **grados** por
    segundo, que es la unidad del catalogo de senales: alimentarla en radianes
    produce una recta en lugar de una curva, sin que nada falle.
    """

    emparejado = emparejar(series, "speed", "yaw_rate")
    xs, ys = [0.0], [0.0]
    marcas = [emparejado[0][0]] if emparejado else []
    rumbo = 0.0
    recorrido = 0.0
    saltados = 0
    for (t1, v1, g1), (t2, _, _) in zip(emparejado, emparejado[1:]):
        dt = (t2 - t1) / 1000.0
        if dt <= 0 or dt > HUECO_MAXIMO_S:
            saltados += 1
            continue
        rumbo += math.radians(g1) * dt
        d = v1 / 3.6 * dt
        recorrido += d
        xs.append(xs[-1] + d * math.cos(rumbo))
        ys.append(ys[-1] + d * math.sin(rumbo))
        marcas.append(t2)
    return {
        "x": xs, "y": ys, "marcas_ms": marcas, "puntos": len(xs),
        "recorrido_m": recorrido, "huecos_saltados": saltados,
        "extension_x_m": (max(xs) - min(xs)) if xs else 0.0,
        "extension_y_m": (max(ys) - min(ys)) if ys else 0.0,
        "rumbo_final_deg": math.degrees(rumbo),
    }


def _ajuste(pares: list[tuple[float, float]]) -> tuple[float, float]:
    """Pendiente y correlacion de una nube de puntos."""

    if len(pares) < 3:
        return float("nan"), float("nan")
    n = len(pares)
    mx = sum(a for a, _ in pares) / n
    my = sum(b for _, b in pares) / n
    sxy = sum((a - mx) * (b - my) for a, b in pares)
    sxx = sum((a - mx) ** 2 for a, _ in pares)
    syy = sum((b - my) ** 2 for _, b in pares)
    if not sxx or not syy:
        return float("nan"), float("nan")
    return sxy / sxx, sxy / math.sqrt(sxx * syy)


def validar_contra_ruedas(series: dict) -> dict:
    """El ancho de via que se deduce de la guinada y las cuatro ruedas.

    En una curva las ruedas de afuera recorren mas que las de adentro, y la
    diferencia dividida por la velocidad de guinada da el ancho de via. Es
    geometria pura, sin ningun supuesto sobre el neumatico.

    Ese numero **no viaja en el bus**: nadie transmite el ancho de via. Que dos
    senales decodificadas por separado coincidan en una dimension fisica del
    vehiculo es la comprobacion mas fuerte disponible de que las dos estan bien
    decodificadas, con la escala y las unidades correctas.
    """

    comunes = set(series.get("yaw_rate", {})) & set(series.get("speed", {}))
    for r in RUEDAS:
        comunes &= set(series.get(r, {}))
    pares = []
    for t in sorted(comunes):
        if series["speed"][t] < VELOCIDAD_MINIMA_KMH:
            continue
        grados = series["yaw_rate"][t]
        if abs(grados) < GIRO_MINIMO_DEG_S:
            continue
        derecha = (series[RUEDAS[1]][t] + series[RUEDAS[3]][t]) / 2
        izquierda = (series[RUEDAS[0]][t] + series[RUEDAS[2]][t]) / 2
        pares.append((math.radians(grados), (derecha - izquierda) / 3.6))
    ancho, r = _ajuste(pares)
    return {"muestras": len(pares), "ancho_de_via_m": ancho, "correlacion": r}
