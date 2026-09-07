# -*- coding: utf-8 -*-
"""Ajuste lineal por minimos cuadrados, con la incerteza de cada coeficiente.

Por que la incerteza no es opcional
-----------------------------------
Un coeficiente sin su error no dice nada. Una pendiente de 0,17 segundos por
vuelta puede ser una degradacion real o el ruido de diecisiete vueltas, y **las
dos se ven igual** hasta que se calcula cuanto puede haberse movido por azar.

Este trabajo ya vio la version barata del error: dos corridas de una prueba
inestable parecieron demostrar una diferencia que con cuatro corridas por lado
resulto no existir. La conclusion de aquello ---que una diferencia se afirma
contra su dispersion y no contra si misma--- es la que este modulo implementa.

De ahi que el ajuste devuelva, por cada coeficiente, **su valor, su error
tipico** y si se distingue de cero con la cantidad de datos que hay.

Que no hace
-----------
No decide por el que lo llama. Devuelve las cifras; que un coeficiente no se
distinga de cero es un hecho a informar, no un motivo para ocultarlo ni para
redondearlo a cero.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: Valor critico de la distribucion t de Student al 95 % de dos colas.
#:
#: Se tabula en lugar de aproximarse porque con pocos grados de libertad la
#: aproximacion normal (1,96) es demasiado indulgente: con cinco grados el valor
#: real es 2,571, y usar 1,96 declararia significativo lo que no lo es.
_T_95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447,
         7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179,
         13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101,
         19: 2.093, 20: 2.086, 25: 2.060, 30: 2.042, 40: 2.021, 60: 2.000,
         120: 1.980}


def t_critico(grados: int) -> float:
    """El valor critico al 95 % para esa cantidad de grados de libertad."""

    if grados <= 0:
        return float("inf")
    if grados in _T_95:
        return _T_95[grados]
    disponibles = sorted(g for g in _T_95 if g <= grados)
    if not disponibles:
        return _T_95[1]
    # Se toma el valor de menos grados, que es **mas exigente**. Redondear hacia
    # el lado indulgente convertiria un limite de tabla en un resultado.
    return _T_95[disponibles[-1]]


@dataclass
class Coeficiente:
    """Un coeficiente estimado, con lo que hace falta para creerle."""

    nombre: str
    valor: float
    error: float
    unidad: str = ""

    @property
    def t(self) -> float:
        if self.error == 0:
            return float("inf")
        return self.valor / self.error

    def distinguible(self, grados: int) -> bool:
        """Si el coeficiente se distingue de cero con los datos que hay."""

        return abs(self.t) > t_critico(grados)

    def intervalo(self, grados: int) -> tuple[float, float]:
        margen = t_critico(grados) * self.error
        return (round(self.valor - margen, 4), round(self.valor + margen, 4))


@dataclass
class Ajuste:
    """El resultado de un ajuste, con su calidad y su dispersion residual."""

    coeficientes: list[Coeficiente]
    n: int
    grados_de_libertad: int
    #: Cuanta de la variacion queda explicada. Entre cero y uno.
    r2: float
    #: Lo que el ajuste no explica, en las unidades de la variable ajustada.
    dispersion_residual: float
    residuos: list[float]

    def por_nombre(self, nombre: str) -> Coeficiente | None:
        for c in self.coeficientes:
            if c.nombre == nombre:
                return c
        return None


def _resolver(matriz: list[list[float]],
              vector: list[float]) -> tuple[list[float], list[list[float]]]:
    """Resuelve el sistema y devuelve tambien la inversa, que da los errores.

    Se usa eliminacion de Gauss-Jordan sobre la matriz aumentada con la
    identidad. Es directo y suficiente: el sistema tiene tantas filas como
    variables ajustadas, que son dos o tres.
    """

    k = len(matriz)
    a = [list(fila) + [1.0 if i == j else 0.0 for j in range(k)] + [vector[i]]
         for i, fila in enumerate(matriz)]
    for col in range(k):
        pivote = max(range(col, k), key=lambda f: abs(a[f][col]))
        if abs(a[pivote][col]) < 1e-12:
            raise ValueError("el sistema no tiene solucion unica: las variables "
                             "ajustadas se mueven juntas")
        a[col], a[pivote] = a[pivote], a[col]
        divisor = a[col][col]
        a[col] = [x / divisor for x in a[col]]
        for fila in range(k):
            if fila == col:
                continue
            factor = a[fila][col]
            if factor:
                a[fila] = [x - factor * y for x, y in zip(a[fila], a[col])]
    beta = [a[i][-1] for i in range(k)]
    inversa = [[a[i][k + j] for j in range(k)] for i in range(k)]
    return beta, inversa


def ajustar(y: list[float], variables: list[tuple[str, list[float], str]],
            ) -> Ajuste:
    """Ajusta `y` contra las variables dadas, con constante.

    Cada variable es una terna de nombre, valores y unidad. La constante se
    agrega sola y se informa como un coeficiente mas.

    Levanta `ValueError` si las variables no se pueden separar ---que es lo que
    ocurre cuando dos de ellas se mueven juntas--- en lugar de devolver
    coeficientes que el dato no sostiene.
    """

    n = len(y)
    nombres = ["constante"] + [v[0] for v in variables]
    unidades = [""] + [v[2] for v in variables]
    columnas = [[1.0] * n] + [list(v[1]) for v in variables]
    k = len(columnas)
    if n <= k:
        raise ValueError(f"hacen falta mas de {k} observaciones y hay {n}")

    xtx = [[sum(columnas[i][r] * columnas[j][r] for r in range(n))
            for j in range(k)] for i in range(k)]
    xty = [sum(columnas[i][r] * y[r] for r in range(n)) for i in range(k)]
    beta, inversa = _resolver(xtx, xty)

    residuos = [y[r] - sum(beta[j] * columnas[j][r] for j in range(k))
                for r in range(n)]
    grados = n - k
    s2 = sum(e * e for e in residuos) / grados
    media = sum(y) / n
    total = sum((v - media) ** 2 for v in y)
    r2 = 1.0 - sum(e * e for e in residuos) / total if total else 0.0

    coeficientes = [
        Coeficiente(nombre=nombres[j], valor=beta[j],
                    error=math.sqrt(max(s2 * inversa[j][j], 0.0)),
                    unidad=unidades[j])
        for j in range(k)
    ]
    return Ajuste(coeficientes=coeficientes, n=n, grados_de_libertad=grados,
                  r2=r2, dispersion_residual=math.sqrt(s2), residuos=residuos)
