# -*- coding: utf-8 -*-
"""Mide la variacion del intervalo de llegada sobre capturas ya en disco.

Que metrica es
--------------
El anexo pide *jitter* en los escenarios 15.1 y 15.2. Jitter es la variacion
del intervalo entre entregas consecutivas, medida contra el intervalo que la
fuente promete: si el emisor declara veinte por segundo, promete cincuenta
milisegundos y toda desviacion respecto de ese valor es jitter.

Que se puede medir aca y que no
-------------------------------
Se mide sobre archivos, sin el juego y sin el broker, porque el capturador ya
sello cada datagrama con un reloj monotono de alta resolucion en el instante de
recibirlo. Eso alcanza para el intervalo **de llegada**.

Lo que **no** puede hacer es atribuirlo: el intervalo observado acumula el
planificador del emisor, la pila de red del sistema operativo y el propio
capturador, y un unico punto de observacion no los separa. Hay que declararlo
donde se use.

Las tres cosas distintas que un intervalo grande puede ser
----------------------------------------------------------
Confundirlas es lo que vuelve inservible la medida, porque las tres inflan el
promedio y solo una es un defecto de la cadena:

1. **llego tarde** ---sesenta milisegundos donde se prometian cincuenta---, que
   es jitter;
2. **falto una** ---cien donde se prometian cincuenta---, que es perdida de una
   ranura;
3. **el emisor dejo de emitir** ---catorce segundos---, que no es ninguna de las
   dos: el juego en pausa, en un menu o en una repeticion no genera telemetria,
   y contar ese hueco como perdida atribuye a la cadena algo que la fuente
   nunca envio.

El tercero se aparta por su tamano y se informa por separado como tiempo muerto.
La tasa alcanzada se calcula **sobre el tiempo vivo**, que es el unico intervalo
en que la fuente prometio algo.
"""

from __future__ import annotations

import argparse
import json
import statistics
import struct
import sys
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from backend import f1_capture, f1_udp  # noqa: E402

CAPTURAS = RAIZ / "datasets" / "f1_25" / "capturas"

# El id de paquete vive en la cabecera y no hace falta desempaquetar la carga
# para leerlo. Sobre cientos de miles de datagramas eso importa: decodificar
# entero cada uno tarda minutos y aca solo se necesita el id.
_ID_EN_CABECERA = 6

# La tabla de paquetes declara la frecuencia. Las que dicen "menu" siguen la
# tasa que se configura en la consola del juego, y esa no viaja en el flujo.
TASA_DE_MENU = 20.0

# Un intervalo por encima de esta fraccion del prometido cuenta como ranura
# perdida y no como llegada tarde. Uno y medio deja pasar media ranura de
# tolerancia, que es lo maximo que un retraso puede acumular sin solaparse con
# la entrega siguiente.
UMBRAL_DE_HUECO = 1.5

# Por encima de esto el hueco ya no se lee como ranuras perdidas sino como
# emisor detenido. Cuatro periodos es deliberadamente generoso: deja del lado
# de la perdida todo lo que podria ser una racha de ranuras salteadas, y solo
# aparta lo que no admite esa lectura.
MULTIPLO_DE_TRAMO_MUERTO = 4.0

# Dos paquetes no describen el mismo vehiculo en cada envio: el emisor rota
# entre los de la parrilla, uno por ranura. La tasa declarada de veinte por
# segundo es de **datagramas**, y la de cada vehiculo es esa dividida por la
# cantidad de autos. Medir su intervalo por id de paquete responde una pregunta
# que nadie hizo: lo que importa es cada cuanto se refresca **un** vehiculo.
#
# Los dos llevan el indice de vehiculo en el primer byte despues de la
# cabecera, de modo que agruparlos no exige desempaquetar la carga entera.
PAQUETES_QUE_ROTAN = {11, 12}


def _tasa_declarada(id_paquete: int, tasa_de_menu: float) -> float | None:
    """Intervalos por segundo que el emisor promete para este paquete."""

    declarada = f1_udp.PAQUETES.get(id_paquete, {}).get("frecuencia")
    if declarada == "menu":
        return tasa_de_menu
    if declarada and declarada.endswith("/s"):
        return float(declarada[:-2])
    if declarada == "5 s":
        return 0.2
    # "evento" y "fin" no prometen periodo: no tienen intervalo que medir.
    return None


def _marcas_por_paquete(ruta: Path) -> tuple[dict[int, list[int]],
                                             dict[int, dict[int, list[int]]]]:
    """Marcas de llegada por id de paquete, y por vehiculo si el paquete rota."""

    marcas: dict[int, list[int]] = defaultdict(list)
    por_vehiculo: dict[int, dict[int, list[int]]] = defaultdict(
        lambda: defaultdict(list))
    for dg in f1_capture.leer_captura(ruta):
        if len(dg.carga) <= _ID_EN_CABECERA:
            continue
        id_paquete = dg.carga[_ID_EN_CABECERA]
        marcas[id_paquete].append(dg.desplazamiento_us)
        if (id_paquete in PAQUETES_QUE_ROTAN
                and len(dg.carga) > f1_udp.CABECERA_TAMANO):
            vehiculo = dg.carga[f1_udp.CABECERA_TAMANO]
            por_vehiculo[id_paquete][vehiculo].append(dg.desplazamiento_us)
    return marcas, por_vehiculo


def _percentil(ordenados: list[float], p: float) -> float:
    if not ordenados:
        return float("nan")
    i = min(len(ordenados) - 1, int(round(p * (len(ordenados) - 1))))
    return ordenados[i]


def medir(marcas: list[int], prometido_us: float) -> dict:
    """Reduce una serie de marcas de llegada a las metricas del anexo."""

    intervalos = [b - a for a, b in zip(marcas, marcas[1:])]
    if not intervalos:
        return {"datagramas": len(marcas), "intervalos": 0}

    muerto = prometido_us * MULTIPLO_DE_TRAMO_MUERTO
    tope = prometido_us * UMBRAL_DE_HUECO

    # Tres poblaciones, apartadas de mayor a menor.
    tramos_muertos = [x for x in intervalos if x > muerto]
    huecos = [x for x in intervalos if tope < x <= muerto]
    normales = sorted(x for x in intervalos if x <= tope)

    # Solo las ranuras dentro del tiempo vivo se cuentan como perdidas.
    ranuras_faltantes = sum(max(1, int(round(x / prometido_us)) - 1) for x in huecos)

    tiempo_total_us = marcas[-1] - marcas[0]
    tiempo_vivo_us = tiempo_total_us - sum(tramos_muertos)
    ranuras_vivas = len(normales) + len(huecos) + ranuras_faltantes

    p50 = _percentil(normales, 0.50)
    p99 = _percentil(normales, 0.99)

    # La estructura del jitter: cuantos intervalos caen a cada lado del periodo
    # prometido, y cuantos caen efectivamente sobre el. Un emisor que alterna
    # entre corto y largo cumple la tasa promedio sin cumplirla nunca en un
    # solo intervalo, y eso solo se ve mirando la forma y no la dispersion.
    # El que cae exactamente sobre el periodo no esta ni por debajo ni por
    # encima: ponerlo en una de las dos modas la corre hacia el periodo y hace
    # parecer que la alternancia es menor de lo que es.
    bajos = [x for x in normales if x < prometido_us]
    altos = [x for x in normales if x > prometido_us]
    cerca = [x for x in normales if abs(x - prometido_us) <= 0.1 * prometido_us]

    # Si la alternancia es estricta, los intervalos consecutivos estan
    # anticorrelacionados y cada par suma dos periodos.
    consecutivos = [x for x in intervalos if x <= tope]
    pares = list(zip(consecutivos, consecutivos[1:]))

    # IPDV, la metrica normalizada de variacion del retardo de paquetes: la
    # diferencia entre los retardos de dos entregas consecutivas. Con un solo
    # reloj no se puede medir el retardo absoluto, pero si su variacion, porque
    # el desconocido se cancela al restar: si el emisor manda a intervalos
    # iguales, la diferencia entre retardos consecutivos es la diferencia entre
    # intervalos de llegada consecutivos.
    #
    # Su media debe dar cero. Es la comprobacion interna de la medicion: cada
    # adelanto se paga con un atraso, y una media que se corriera de cero
    # delataria una deriva entre los relojes en lugar de variacion del retardo.
    ipdv = sorted(abs(b - a) for a, b in pares)
    media_ipdv = (statistics.mean(b - a for a, b in pares) / 1000
                  if pares else float("nan"))
    correlacion = None
    if len(pares) > 2:
        mx = statistics.mean(x for x, _ in pares)
        my = statistics.mean(y for _, y in pares)
        sx = statistics.pstdev([x for x, _ in pares])
        sy = statistics.pstdev([y for _, y in pares])
        if sx and sy:
            cov = sum((x - mx) * (y - my) for x, y in pares) / len(pares)
            correlacion = cov / (sx * sy)

    return {
        "datagramas": len(marcas),
        "intervalos": len(intervalos),
        "prometido_ms": prometido_us / 1000,
        "tiempo_total_s": tiempo_total_us / 1e6,
        "tiempo_muerto_s": sum(tramos_muertos) / 1e6,
        "tramos_muertos": len(tramos_muertos),
        "mayor_tramo_muerto_s": (max(tramos_muertos) / 1e6) if tramos_muertos else 0.0,
        # La tasa alcanzada se mide sobre el tiempo vivo: es el unico lapso en
        # que la fuente prometio emitir.
        "tasa_sobre_lo_vivo": (len(marcas) / (tiempo_vivo_us / 1e6)
                               if tiempo_vivo_us > 0 else float("nan")),
        "media_viva_ms": statistics.mean(normales) / 1000 if normales else float("nan"),
        "p50_ms": p50 / 1000,
        "p95_ms": _percentil(normales, 0.95) / 1000,
        "p99_ms": p99 / 1000,
        # El jitter se declara como la cola menos la mediana: es cuanto se corre
        # la entrega tardia respecto de la tipica, y no depende de que la mediana
        # coincida con el valor prometido.
        "jitter_p99_ms": (p99 - p50) / 1000,
        "desvio_ms": (statistics.pstdev(normales) / 1000) if len(normales) > 1 else 0.0,
        "fraccion_bajo_el_periodo": len(bajos) / len(normales) if normales else 0.0,
        "mediana_de_los_bajos_ms": (statistics.median(bajos) / 1000) if bajos else None,
        "mediana_de_los_altos_ms": (statistics.median(altos) / 1000) if altos else None,
        "fraccion_sobre_el_periodo": len(cerca) / len(normales) if normales else 0.0,
        "correlacion_consecutivos": correlacion,
        "ipdv_p50_ms": (_percentil(ipdv, 0.50) / 1000) if ipdv else float("nan"),
        "ipdv_p95_ms": (_percentil(ipdv, 0.95) / 1000) if ipdv else float("nan"),
        "ipdv_p99_ms": (_percentil(ipdv, 0.99) / 1000) if ipdv else float("nan"),
        "ipdv_media_ms": media_ipdv,
        "huecos": len(huecos),
        "ranuras_faltantes": ranuras_faltantes,
        # Entrega: ranuras que llegaron sobre las que el emisor prometia,
        # descontado el tiempo en que no prometio nada.
        "entrega": ((ranuras_vivas - ranuras_faltantes) / ranuras_vivas
                    if ranuras_vivas else 1.0),
    }


def _informar(nombre_archivo: str, marcas: dict[int, list[int]],
              por_vehiculo: dict[int, dict[int, list[int]]],
              tasa_de_menu: float) -> dict:
    print()
    print("=" * 98)
    print(nombre_archivo)
    print("=" * 98)
    span = max(m[-1] for m in marcas.values() if m) / 1e6
    total = sum(len(m) for m in marcas.values())
    print(f"  {total:,} datagramas en {span:,.1f} s = {total / span:,.0f} por segundo")
    print()
    print(f"  {'paquete':<18}{'promet':>7}{'p50':>7}{'p95':>7}{'p99':>7}{'jitter':>8}"
          f"{'sobre':>7}{'faltan':>8}{'entrega':>9}{'muerto':>9}{'tasa viva':>11}")
    print("  " + "-" * 96)

    por_paquete: dict[str, dict] = {}
    for id_paquete in sorted(marcas):
        nombre = f1_udp.PAQUETES.get(id_paquete, {}).get("nombre", f"id{id_paquete}")
        tasa = _tasa_declarada(id_paquete, tasa_de_menu)
        if tasa is None:
            print(f"  {nombre:<18}{'--':>7}   sin periodo declarado"
                  f"{len(marcas[id_paquete]):>10,} datagramas")
            continue

        if id_paquete in PAQUETES_QUE_ROTAN:
            # Se mide cada vehiculo por separado contra el periodo que le toca
            # ---la tasa de datagramas repartida entre los autos--- y se
            # informa la mediana de los vehiculos. Medirlo por id de paquete
            # daria el periodo de la ranura y no el refresco de un auto, que es
            # la magnitud que un tablero necesita.
            vehiculos = por_vehiculo.get(id_paquete, {})
            if not vehiculos:
                continue
            propio = tasa / len(vehiculos)
            medidas = [medir(v, 1_000_000 / propio)
                       for v in vehiculos.values() if len(v) > 1]
            if not medidas:
                continue
            m = max(medidas, key=lambda x: x["datagramas"])
            m["vehiculos"] = len(vehiculos)
            m["rota"] = True
            por_paquete[nombre] = m
            print(f"  {nombre:<18}{m['prometido_ms']:>7.0f}{m['p50_ms']:>7.0f}"
                  f"{m['p95_ms']:>7.0f}{m['p99_ms']:>7.0f}"
                  f"{m['jitter_p99_ms']:>8.1f}"
                  f"{m['fraccion_sobre_el_periodo'] * 100:>6.1f}%"
                  f"{m['ranuras_faltantes']:>8,}{m['entrega'] * 100:>8.2f}%"
                  f"{m['tiempo_muerto_s']:>8.1f}s"
                  f"{m['tasa_sobre_lo_vivo']:>10.2f}/s"
                  f"   rota entre {len(vehiculos)}")
            continue

        m = medir(marcas[id_paquete], 1_000_000 / tasa)
        por_paquete[nombre] = m
        if not m.get("intervalos"):
            continue
        print(f"  {nombre:<18}{m['prometido_ms']:>7.1f}{m['p50_ms']:>7.1f}"
              f"{m['p95_ms']:>7.1f}{m['p99_ms']:>7.1f}{m['jitter_p99_ms']:>8.1f}"
              f"{m['fraccion_sobre_el_periodo'] * 100:>6.1f}%"
              f"{m['ranuras_faltantes']:>8,}{m['entrega'] * 100:>8.2f}%"
              f"{m['tiempo_muerto_s']:>8.1f}s{m['tasa_sobre_lo_vivo']:>10.2f}/s")

    # La columna "sobre" es la que sostiene la afirmacion mas util de la
    # medicion, y merece leerse explicita.
    for nombre, m in por_paquete.items():
        if (m.get("intervalos") and not m.get("rota")
                and m["fraccion_sobre_el_periodo"] < 0.05):
            print()
            print(f"  {nombre}: solo el {m['fraccion_sobre_el_periodo'] * 100:.2f} % de "
                  f"los intervalos cae dentro del 10 % del periodo prometido "
                  f"({m['prometido_ms']:.1f} ms).")
            bajo = m["mediana_de_los_bajos_ms"]
            alto = m["mediana_de_los_altos_ms"]
            if bajo is None or alto is None:
                # Una sola moda: no hay alternancia que describir, y decir
                # "dos modas" con una sola seria describir lo que no se vio.
                print(f"    una sola moda, mediana {m['p50_ms']:.1f} ms: "
                      f"corrida respecto del periodo pero sin alternancia.")
            else:
                print(f"    la distribucion es de dos modas: "
                      f"{m['fraccion_bajo_el_periodo'] * 100:.1f} % por debajo, "
                      f"mediana {bajo:.1f} ms, y el resto por encima, "
                      f"mediana {alto:.1f} ms.")
            if m["correlacion_consecutivos"] is not None:
                print(f"    correlacion entre intervalos consecutivos: "
                      f"{m['correlacion_consecutivos']:+.3f}; la media viva es "
                      f"{m['media_viva_ms']:.2f} ms contra "
                      f"{m['prometido_ms']:.1f} prometidos.")
            print(f"    IPDV: mediana {m['ipdv_p50_ms']:.2f} ms, "
                  f"p95 {m['ipdv_p95_ms']:.2f}, p99 {m['ipdv_p99_ms']:.2f}; "
                  f"media {m['ipdv_media_ms']:+.3f} ms (debe dar cero).")
            break

    return {"duracion_s": span, "datagramas": total, "paquetes": por_paquete}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("capturas", nargs="*", type=Path,
                    help="capturas a medir; por omision, todas las de disco")
    ap.add_argument("--tasa-de-menu", type=float, default=TASA_DE_MENU,
                    help="tasa configurada en la consola del juego, en Hz")
    ap.add_argument("--json", type=Path, help="escribe el resultado crudo")
    args = ap.parse_args()

    rutas = args.capturas or sorted(CAPTURAS.glob("*.f1raw"))
    if not rutas:
        print("no hay capturas para medir")
        return 1

    todo: dict[str, dict] = {}
    for ruta in rutas:
        try:
            marcas, por_vehiculo = _marcas_por_paquete(ruta)
        except (OSError, struct.error, ValueError) as e:
            print(f"  {ruta.name}: ilegible ({e})")
            continue
        if not marcas:
            continue
        todo[ruta.name] = _informar(ruta.name, marcas, por_vehiculo,
                                    args.tasa_de_menu)

    if args.json:
        args.json.write_text(json.dumps(todo, indent=1), encoding="utf-8")
        print(f"\ncrudo en {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
