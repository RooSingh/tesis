"""Recuenta las tramas de una captura CAN por origen y mide cuanto es eco.

Para que sirve
--------------
El capitulo 7 declara que dos de los origenes del bus ---el 0 y el 130---
traen exactamente la misma cantidad de tramas, y que el segundo es el **eco**
del primero: la misma trama vista por la otra punta del adaptador. Esa
afirmacion se habia comprobado a mano. Aqui queda en el repositorio, con el
recuento y con la prueba del eco.

Por que no alcanza con contar
-----------------------------
Que dos origenes tengan la misma cantidad de tramas no prueba que uno sea el
eco del otro: podrian ser dos flujos distintos del mismo tamano. Lo que lo
prueba es **emparejar**: para cada trama del supuesto eco, buscar en el origen
una con el mismo identificador, los mismos bytes y dentro de una tolerancia de
tiempo.

Y ahi hay una condicion que es facil pasar por alto: **cada trama del origen se
consume una sola vez**. Sin eso, un identificador que se repite cada pocos
milisegundos haria que una sola trama del origen explicara muchas del eco, y el
recuento daria casi el cien por ciento sin significar nada.

Cuando hay dos candidatas dentro de la tolerancia se toma **la mas cercana en el
tiempo**, no la primera. Gastar la lejana puede dejar sin gemela a un eco
posterior que solo esa alcanzaba.

Uso
---
    python -B scripts/recontar_origenes_can.py datasets/can/capturas/ARCHIVO.canraw
    python -B scripts/recontar_origenes_can.py ARCHIVO.canraw --par 0 130 --par 2 128
"""

from __future__ import annotations

import argparse
import bisect
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.can_capture import Trama, leer_captura  # noqa: E402

MS_EN_NS = 1_000_000


def _miles(n: int) -> str:
    """Separador de miles del pais. Se aplica al numero, no a la frase."""
    return f"{n:,}".replace(",", ".")


@dataclass
class RecuentoDeOrigen:
    """Lo que se sabe de un origen del bus."""

    tramas: int = 0
    identificadores: Counter = field(default_factory=Counter)

    @property
    def identificadores_distintos(self) -> int:
        return len(self.identificadores)


def contar_por_origen(tramas: Iterable[Trama]) -> dict[int, RecuentoDeOrigen]:
    """Cuenta tramas e identificadores distintos de cada origen."""
    recuento: dict[int, RecuentoDeOrigen] = defaultdict(RecuentoDeOrigen)
    for t in tramas:
        r = recuento[t.bus]
        r.tramas += 1
        r.identificadores[t.identificador] += 1
    return dict(recuento)


def emparejar_eco(origen: Sequence[Trama], eco: Sequence[Trama],
                  tolerancia_ms: float) -> int:
    """Cuantas tramas del eco tienen gemela en el origen.

    Gemela es misma trama: identificador y bytes iguales, dentro de la
    tolerancia. Cada trama del origen se consume una sola vez.
    """
    tolerancia_ns = int(tolerancia_ms * MS_EN_NS)

    # Las candidatas se agrupan por lo que tiene que coincidir exactamente, y
    # quedan ordenadas en el tiempo para poder buscar por cercania.
    candidatas: dict[tuple[int, bytes], list[int]] = defaultdict(list)
    for t in origen:
        candidatas[(t.identificador, t.datos)].append(t.instante_ns)
    for instantes in candidatas.values():
        instantes.sort()

    gastadas: dict[tuple[int, bytes], set[int]] = defaultdict(set)
    emparejadas = 0

    for t in sorted(eco, key=lambda x: x.instante_ns):
        clave = (t.identificador, t.datos)
        instantes = candidatas.get(clave)
        if not instantes:
            continue

        usadas = gastadas[clave]
        # Se abre desde la posicion mas cercana hacia los dos lados, y se toma
        # la primera libre: como se avanza por distancia creciente, esa es la
        # mas cercana.
        centro = bisect.bisect_left(instantes, t.instante_ns)
        izquierda, derecha = centro - 1, centro
        mejor_indice = None
        mejor_distancia = tolerancia_ns + 1

        while izquierda >= 0 or derecha < len(instantes):
            distancia_izq = (t.instante_ns - instantes[izquierda]
                             if izquierda >= 0 else None)
            distancia_der = (instantes[derecha] - t.instante_ns
                             if derecha < len(instantes) else None)

            if distancia_izq is None and distancia_der is None:
                break
            if distancia_der is None or (distancia_izq is not None
                                         and distancia_izq <= distancia_der):
                indice, distancia = izquierda, distancia_izq
                izquierda -= 1
            else:
                indice, distancia = derecha, distancia_der
                derecha += 1

            if distancia > tolerancia_ns:
                break
            if indice not in usadas:
                mejor_indice, mejor_distancia = indice, distancia
                break

        if mejor_indice is not None and mejor_distancia <= tolerancia_ns:
            usadas.add(mejor_indice)
            emparejadas += 1

    return emparejadas


def _informar(ruta: Path, pares: list[tuple[int, int]], tolerancia_ms: float) -> None:
    tramas = list(leer_captura(ruta))
    recuento = contar_por_origen(tramas)

    print(f"Captura: {ruta}")
    print(f"Tramas totales: {_miles(len(tramas))}")
    print()
    print(f"{'origen':>8} {'tramas':>10} {'ids distintos':>14}")
    for bus in sorted(recuento):
        r = recuento[bus]
        print(f"{bus:>8} {_miles(r.tramas):>10} "
              f"{r.identificadores_distintos:>14}")

    por_bus: dict[int, list[Trama]] = defaultdict(list)
    for t in tramas:
        por_bus[t.bus].append(t)

    for origen_bus, eco_bus in pares:
        print()
        print(f"--- par {origen_bus} / {eco_bus} ---")
        origen = por_bus.get(origen_bus, [])
        eco = por_bus.get(eco_bus, [])
        r_origen = recuento.get(origen_bus, RecuentoDeOrigen())
        r_eco = recuento.get(eco_bus, RecuentoDeOrigen())

        mismos = r_origen.identificadores == r_eco.identificadores
        print(f"tramas: {_miles(len(origen))} contra {_miles(len(eco))}")
        print(f"identificadores identicos y con el mismo conteo: "
              f"{'si' if mismos else 'NO'}")
        if not mismos:
            solo_origen = set(r_origen.identificadores) - set(r_eco.identificadores)
            solo_eco = set(r_eco.identificadores) - set(r_origen.identificadores)
            if solo_origen:
                print(f"  solo en {origen_bus}: {sorted(solo_origen)[:10]}")
            if solo_eco:
                print(f"  solo en {eco_bus}: {sorted(solo_eco)[:10]}")
            distintos = [(i, r_origen.identificadores[i], r_eco.identificadores[i])
                         for i in sorted(set(r_origen.identificadores)
                                         & set(r_eco.identificadores))
                         if r_origen.identificadores[i] != r_eco.identificadores[i]]
            for identificador, a, b in distintos[:10]:
                print(f"  id {identificador}: {a} en {origen_bus}, {b} en {eco_bus}")

        emparejadas = emparejar_eco(origen, eco, tolerancia_ms)
        total = len(eco)
        porcentaje = (100.0 * emparejadas / total) if total else 0.0
        print(f"tramas de {eco_bus} con gemela en {origen_bus} "
              f"(+-{tolerancia_ms:g} ms, cada una consumida una vez): "
              f"{_miles(emparejadas)} de {_miles(total)} ({porcentaje:.3f} %)")


def main(argv: Sequence[str] | None = None) -> int:
    analizador = argparse.ArgumentParser(
        description="Recuenta tramas por origen y mide cuanto de un origen es eco de otro.")
    analizador.add_argument("captura", type=Path)
    analizador.add_argument(
        "--par", nargs=2, type=int, action="append", metavar=("ORIGEN", "ECO"),
        help="par origen/eco a emparejar; se puede repetir (por omision: 0 130 y 2 128)")
    analizador.add_argument("--tolerancia-ms", type=float, default=5.0)
    argumentos = analizador.parse_args(argv)

    if not argumentos.captura.exists():
        print(f"No existe la captura: {argumentos.captura}", file=sys.stderr)
        return 2

    pares = [tuple(p) for p in (argumentos.par or [[0, 130], [2, 128]])]
    _informar(argumentos.captura, pares, argumentos.tolerancia_ms)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
