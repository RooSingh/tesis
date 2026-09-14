"""Energia del ERS por vuelta de una captura F1 25, con los dos canales separados.

Para que sirve
--------------
El capitulo 15 tuvo dos tablas de energia recuperada que no se parecen: una de
Silverstone con 4,02 a 4,69 MJ por vuelta y otra de Spa con 2.000 a 2.001 kJ
fijos. No se contradicen. La de Silverstone **suma** los dos canales de
recuperacion ---MGU-K y MGU-H--- y la de Spa es **solo el MGU-K**, que el juego
satura en 2 MJ por vuelta. Este guion deja el calculo en el repositorio, sobre
la captura cruda y sin la base, con los dos canales en columnas separadas para
que ninguna suma quede implicita.

Que calcula
-----------
Para el vehiculo propio y cada vuelta (`current_lap_num` del ultimo paquete de
vuelta recibido) recorre los paquetes de estado del vehiculo (Car Status,
paquete 7) y guarda:

- la carga minima de la bateria, en porcentaje de la franja util de 4 MJ;
- el MGU-K, el MGU-H, su suma y lo desplegado, en kJ, **del ultimo paquete de
  la vuelta** ---el criterio de `scripts/analizar_carrera_f1_25.py`---;
- los mismos cuatro contadores tomados como **maximo dentro de la vuelta**.

Por que hay dos criterios
-------------------------
Los contadores son "de esta vuelta": suben durante la vuelta y vuelven a cero
al cruzar la linea. El ultimo paquete de la vuelta los lee justo antes del
reinicio, salvo cuando el paquete de vuelta y el de estado no cambian a la vez:
si el de estado ya viene reiniciado mientras el de vuelta todavia no cambio de
numero, el ultimo paquete da un contador casi nulo. El maximo no tiene ese
problema, pero tiene otro: en una vuelta donde el contador se reinicia a mitad
(la ultima de la carrera, por ejemplo) mezcla dos tramos. Por eso se informan
los dos y no se elige en silencio.

Que vehiculo es el propio
-------------------------
El **mas frecuente** de `player_car_index` entre todas las cabeceras, y se
declara. No el de la primera cabecera: en la carrera 2 de Spa las primeras 14
cabeceras dicen 0 y el resto dice 19, de modo que tomar la primera analiza el
vehiculo equivocado (es lo que hace `analizar_carrera_f1_25.py:134`).

Uso
---
    python -B scripts/energia_recuperada_por_vuelta.py CAPTURA.f1raw [CAPTURA2.f1raw ...]
    python -B scripts/energia_recuperada_por_vuelta.py CAPTURA.f1raw --vehiculo 19
    python -B scripts/energia_recuperada_por_vuelta.py A.f1raw B.f1raw --csv salida.csv
"""

from __future__ import annotations

import argparse
import csv
import struct
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import f1_capture, f1_udp  # noqa: E402

#: Franja util de la bateria: la misma que usa `analizar_carrera_f1_25.py:105`.
ERS_FRANJA_UTIL_J = 4_000_000.0

PAQUETE_VUELTA = 2
PAQUETE_ESTADO = 7

CONTADORES = ("mguk", "mguh", "kh", "desplegado")


@dataclass
class EnergiaDeVuelta:
    """Lo que se acumula de una vuelta del vehiculo propio."""

    vuelta: int
    paquetes: int = 0
    carga_min_j: float = float("inf")
    ultimo: dict = field(default_factory=dict)
    maximo: dict = field(default_factory=lambda: {c: 0.0 for c in CONTADORES})

    def agregar(self, estado: dict) -> None:
        """Incorpora un paquete de estado del vehiculo propio."""
        valores = {
            "mguk": estado["ers_harvested_this_lap_mguk_j"],
            "mguh": estado["ers_harvested_this_lap_mguh_j"],
            "desplegado": estado["ers_deployed_this_lap_j"],
        }
        valores["kh"] = valores["mguk"] + valores["mguh"]
        self.paquetes += 1
        self.carga_min_j = min(self.carga_min_j, estado["ers_store_energy_j"])
        self.ultimo = valores
        for c in CONTADORES:
            self.maximo[c] = max(self.maximo[c], valores[c])

    @property
    def carga_min_pct(self) -> float:
        return 100.0 * self.carga_min_j / ERS_FRANJA_UTIL_J


def vehiculo_mas_frecuente(cabeceras: Iterable[int]) -> tuple[int, Counter]:
    """El indice de vehiculo propio mas frecuente y el recuento completo."""
    recuento = Counter(cabeceras)
    if not recuento:
        raise ValueError("la captura no tiene cabeceras legibles")
    return recuento.most_common(1)[0][0], recuento


def energia_por_vuelta(paquetes: Iterable[dict], propio: int) -> dict[int, EnergiaDeVuelta]:
    """Asigna cada paquete de estado a la vuelta vigente y acumula.

    `paquetes` son resultados de `f1_udp.decodificar` en orden de llegada; se
    ignora todo lo que no sea vuelta (2) o estado (7). Un paquete de estado que
    llega antes del primer paquete de vuelta no tiene vuelta y se descarta.
    """
    vuelta_vigente: int | None = None
    vueltas: dict[int, EnergiaDeVuelta] = {}
    for r in paquetes:
        if not r.get("decodificado"):
            continue
        if r["packet_id"] == PAQUETE_VUELTA:
            vuelta_vigente = r["vehiculos"][propio]["current_lap_num"]
        elif r["packet_id"] == PAQUETE_ESTADO and vuelta_vigente is not None:
            vueltas.setdefault(vuelta_vigente, EnergiaDeVuelta(vuelta_vigente)) \
                .agregar(r["vehiculos"][propio])
    return dict(sorted(vueltas.items()))


def _cabeceras(ruta: Path) -> Iterable[int]:
    for d in f1_capture.leer_captura(ruta):
        try:
            yield f1_udp.decodificar_cabecera(d.carga)["player_car_index"]
        except f1_udp.ErrorDecodificacion:
            continue


def _paquetes_de_energia(ruta: Path) -> Iterable[dict]:
    # Solo se decodifican los dos paquetes que interesan: decodificar los
    # veintidos vehiculos del resto triplica el tiempo sin aportar nada.
    for d in f1_capture.leer_captura(ruta):
        if len(d.carga) < f1_udp.CABECERA_TAMANO:
            continue
        packet_id = struct.unpack_from("<B", d.carga, 6)[0]
        if packet_id not in (PAQUETE_VUELTA, PAQUETE_ESTADO):
            continue
        try:
            yield f1_udp.decodificar(d.carga)
        except f1_udp.ErrorDecodificacion:
            continue


def analizar(ruta: Path, vehiculo: int | None = None) -> dict:
    """Recorre una captura y devuelve el vehiculo, su recuento y las vueltas."""
    mas_frecuente, recuento = vehiculo_mas_frecuente(_cabeceras(ruta))
    propio = mas_frecuente if vehiculo is None else vehiculo
    return {
        "captura": ruta,
        "vehiculo": propio,
        "vehiculo_mas_frecuente": mas_frecuente,
        "cabeceras_por_vehiculo": dict(recuento),
        "vueltas": energia_por_vuelta(_paquetes_de_energia(ruta), propio),
    }


def _kj(j: float) -> str:
    return f"{j / 1000:>7.0f}"


def informar(a: dict) -> None:
    print(f"Captura: {a['captura']}")
    print(f"player_car_index en las cabeceras: {a['cabeceras_por_vehiculo']}")
    print(f"vehiculo analizado: {a['vehiculo']} "
          f"(el mas frecuente es {a['vehiculo_mas_frecuente']})")
    print(f"{'v':>3} {'paq':>5} {'carga':>7} | {'K ult':>7} {'H ult':>7} {'K+H ult':>7} "
          f"{'despl ult':>9} | {'K max':>7} {'H max':>7} {'K+H max':>7} {'despl max':>9}  (kJ)")
    for n, e in a["vueltas"].items():
        u, m = e.ultimo, e.maximo
        print(f"{n:>3} {e.paquetes:>5} {e.carga_min_pct:>6.1f}% | "
              f"{_kj(u['mguk'])} {_kj(u['mguh'])} {_kj(u['kh'])} {_kj(u['desplegado']):>9} | "
              f"{_kj(m['mguk'])} {_kj(m['mguh'])} {_kj(m['kh'])} {_kj(m['desplegado']):>9}")
    print()


def filas_csv(a: dict) -> list[dict]:
    filas = []
    for n, e in a["vueltas"].items():
        fila = {
            "captura": Path(a["captura"]).name,
            "vehiculo": a["vehiculo"],
            "vuelta": n,
            "paquetes_estado": e.paquetes,
            "carga_min_pct": f"{e.carga_min_pct:.1f}",
        }
        for criterio, valores in (("ultimo", e.ultimo), ("maximo", e.maximo)):
            for c in CONTADORES:
                fila[f"{c}_{criterio}_kj"] = f"{valores[c] / 1000:.1f}"
        filas.append(fila)
    return filas


def main(argv: Sequence[str] | None = None) -> int:
    analizador = argparse.ArgumentParser(
        description="Energia del ERS por vuelta, con MGU-K y MGU-H separados.")
    analizador.add_argument("capturas", type=Path, nargs="+")
    analizador.add_argument("--vehiculo", type=int, default=None,
                            help="indice de vehiculo; por omision, el mas frecuente")
    analizador.add_argument("--csv", type=Path, default=None,
                            help="archivo CSV donde escribir todas las vueltas")
    argumentos = analizador.parse_args(argv)

    filas: list[dict] = []
    for ruta in argumentos.capturas:
        if not ruta.exists():
            print(f"No existe la captura: {ruta}", file=sys.stderr)
            return 2
        a = analizar(ruta, argumentos.vehiculo)
        informar(a)
        filas.extend(filas_csv(a))

    if argumentos.csv is not None and filas:
        argumentos.csv.parent.mkdir(parents=True, exist_ok=True)
        with argumentos.csv.open("w", newline="", encoding="utf-8") as archivo:
            escritor = csv.DictWriter(archivo, fieldnames=list(filas[0]))
            escritor.writeheader()
            escritor.writerows(filas)
        print(f"CSV: {argumentos.csv} ({len(filas)} vueltas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
