# -*- coding: utf-8 -*-
"""Cuanto tarda un datagrama por encima del mas rapido de su corrida.

POR QUE NO SE PUEDE MEDIR UN RETARDO ABSOLUTO
---------------------------------------------
Cada paquete de F1 25 trae `session_time`, el reloj del **juego**, que arranca en
cero al comenzar la sesion. El capturador sella cada datagrama con el reloj de la
**maquina** al recibirlo. Los dos relojes son independientes y nunca se
sincronizaron: la diferencia entre los dos sellos incluye un desfase constante
que no se puede despejar sin sincronizarlos.

Lo que si se puede medir, y es honesto declarar, es **cuanto tardo cada mensaje
por encima del mas rapido de la corrida**. Es una cota inferior: el retardo real
de cada mensaje es ese numero mas el retardo del datagrama mas rapido, que no se
conoce y no puede ser negativo.

COMO
----
1. Cada datagrama aporta el par `(session_time, hora_de_llegada)`.
2. Se ajusta `llegada = a * session_time + b` con **Theil-Sen**, que toma la
   mediana de las pendientes entre pares. Se elige robusto a proposito: un
   ajuste por minimos cuadrados deja que un punado de datagramas tardios
   arrastre la recta, y son justamente los que se quieren medir, no los que
   deben mandar.
3. La pendiente `a` es la **deriva entre relojes**. Si no da 1, los dos relojes
   corren a ritmos distintos, y hay que decirlo: un retardo medido sobre relojes
   que derivan crece solo con el tiempo aunque la red no cambie.
4. El residuo de cada datagrama menos el residuo minimo de la corrida es su
   **retardo sobre el piso**. El minimo se toma como piso porque un retardo no
   puede ser negativo: el datagrama mas rapido es el que menos camino perdio.

QUE NO ES ESTO
--------------
- **No es un retardo absoluto.** Sin sincronizar relojes, el absoluto no existe.
- **No mide la red sola.** Entre el `session_time` que el juego escribe y el
  sello del capturador hay serializacion, red, y el propio planificador del
  sistema operativo. Lo medido es el tramo completo entre los dos sellos.
- **No hace falta hardware ni instrumentar el emisor.** Es procesar una captura
  que ya esta tomada.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


#: Cuantos pares se muestrean para la mediana de pendientes. Theil-Sen exacto es
#: cuadratico ---con cien mil datagramas serian cinco mil millones de pares--- y
#: la mediana de una muestra grande al azar converge a la misma pendiente. Se
#: fija la semilla para que dos corridas sobre la misma captura den lo mismo:
#: una medicion que cambia entre ejecuciones no se puede citar.
PARES_PARA_LA_PENDIENTE = 200_000
SEMILLA = 20260911


@dataclass(frozen=True)
class Desfase:
    """Lo que una corrida permite afirmar sobre sus dos relojes."""

    #: Pendiente del ajuste. 1,0 significa que los dos relojes corren igual.
    deriva: float
    #: Ordenada al origen, en segundos. No se interpreta: absorbe el desfase.
    origen_s: float
    #: Retardo sobre el piso, en milisegundos.
    mediana_ms: float
    p99_ms: float
    maximo_ms: float
    #: Cuantos datagramas entraron en el ajuste.
    datagramas: int
    #: Cuanto abarca la corrida, en segundos del reloj del juego.
    duracion_s: float

    def como_texto(self) -> str:
        """La afirmacion completa, con su salvedad pegada."""
        return (
            f"deriva {self.deriva:.9f} · "
            f"retardo sobre el piso: mediana {self.mediana_ms:.2f} ms, "
            f"p99 {self.p99_ms:.2f} ms, maximo {self.maximo_ms:.2f} ms · "
            f"{self.datagramas} datagramas en {self.duracion_s:.1f} s · "
            "RELATIVO AL MINIMO OBSERVADO, no absoluto"
        )


def _mediana(valores: list[float]) -> float:
    if not valores:
        raise ValueError("no hay valores")
    orden = sorted(valores)
    n = len(orden)
    medio = n // 2
    return orden[medio] if n % 2 else (orden[medio - 1] + orden[medio]) / 2


def _percentil(valores_ordenados: list[float], p: float) -> float:
    """Percentil por interpolacion lineal sobre una lista ya ordenada."""
    if not valores_ordenados:
        raise ValueError("no hay valores")
    if len(valores_ordenados) == 1:
        return valores_ordenados[0]
    pos = p * (len(valores_ordenados) - 1)
    bajo = int(pos)
    alto = min(bajo + 1, len(valores_ordenados) - 1)
    resto = pos - bajo
    return valores_ordenados[bajo] * (1 - resto) + valores_ordenados[alto] * resto


def pendiente_robusta(pares: list[tuple[float, float]],
                      pares_muestreados: int = PARES_PARA_LA_PENDIENTE,
                      semilla: int = SEMILLA) -> float:
    """Mediana de las pendientes entre pares de puntos ---Theil-Sen---.

    Se separa del recorrido del archivo para poder ejercerla: sobre datos
    sinteticos con valores atipicos conocidos se puede comprobar que la
    pendiente no se mueve, que es justamente la propiedad por la que se la
    eligio.
    """

    n = len(pares)
    if n < 2:
        raise ValueError("hacen falta al menos dos datagramas")

    az = random.Random(semilla)
    pendientes: list[float] = []
    total_posibles = n * (n - 1) // 2

    if total_posibles <= pares_muestreados:
        for i in range(n):
            xi, yi = pares[i]
            for j in range(i + 1, n):
                xj, yj = pares[j]
                if xj != xi:
                    pendientes.append((yj - yi) / (xj - xi))
    else:
        intentos = 0
        tope = pares_muestreados * 4          # por si hay muchos x repetidos
        while len(pendientes) < pares_muestreados and intentos < tope:
            intentos += 1
            i, j = az.randrange(n), az.randrange(n)
            if i == j:
                continue
            xi, yi = pares[i]
            xj, yj = pares[j]
            if xj != xi:
                pendientes.append((yj - yi) / (xj - xi))

    if not pendientes:
        raise ValueError("todos los datagramas comparten el mismo instante del "
                         "juego: no hay pendiente que ajustar")
    return _mediana(pendientes)


def medir(pares: list[tuple[float, float]],
          pares_muestreados: int = PARES_PARA_LA_PENDIENTE,
          semilla: int = SEMILLA) -> Desfase:
    """Deriva y retardo sobre el piso, a partir de los pares de la corrida.

    `pares` son `(session_time del juego, hora de llegada)`, los dos en segundos
    y cada uno en su propio reloj.
    """

    if len(pares) < 2:
        raise ValueError("hacen falta al menos dos datagramas")

    a = pendiente_robusta(pares, pares_muestreados, semilla)
    # LA ORDENADA NO CAMBIA NINGUNA CIFRA REPORTADA, y conviene decirlo en vez de
    # dejar creer que si: desplaza **todos** los residuos por igual, y el paso
    # siguiente les resta su minimo, que absorbe cualquier desplazamiento comun.
    # Se toma la mediana igual, para que `origen_s` ---que solo se declara, no se
    # interpreta--- sea robusta como el resto del ajuste y no la corra un tardio.
    b = _mediana([y - a * x for x, y in pares])

    residuos = [(y - (a * x + b)) for x, y in pares]
    piso = min(residuos)
    sobre_el_piso = sorted((r - piso) * 1000.0 for r in residuos)

    xs = [x for x, _ in pares]
    return Desfase(
        deriva=a,
        origen_s=b,
        mediana_ms=_percentil(sobre_el_piso, 0.50),
        p99_ms=_percentil(sobre_el_piso, 0.99),
        maximo_ms=sobre_el_piso[-1],
        datagramas=len(pares),
        duracion_s=max(xs) - min(xs),
    )
