# -*- coding: utf-8 -*-
"""Mide el caudal de las tres fuentes en una misma unidad.

La pregunta
-----------
Cuanto exige cada fuente a la cadena. El capitulo de resultados tiene cifras de
caudal dispersas, en unidades distintas, y **la fuente de bus vehicular no
aparece**, que resulta ser la de mayor caudal de las tres.

Por que las cifras crudas no sirven
-----------------------------------
Las tasas nativas de las tres fuentes **no son comparables entre si**, porque una
unidad de cada una contiene una cantidad distinta de informacion:

- una muestra de la fuente deportiva describe **un** vehiculo con seis senales;
- una trama del bus vehicular trae hasta ocho bytes, que segun el identificador
  pueden ser una senal o varias;
- un datagrama de la simulacion puede describir **veintidos** vehiculos por
  decenas de canales.

Poner 3,74 al lado de 4.012 y sacar una conclusion seria comparar cosas
distintas. La unidad honesta es **mensajes del contrato interno por segundo**,
que es en lo que las tres se convierten y lo que la cadena efectivamente
transporta.

Como se mide
------------
No se estima multiplicando. Se toma una muestra acotada de datos **que ya estan
en disco**, se la pasa por **el adaptador que le corresponde**, y se cuentan los
mensajes que salen. Despues se divide por el tiempo real que esa muestra
representa, que es el que la fuente hubiera tardado en producirla.

Una decision que hay que declarar
---------------------------------
El adaptador de la simulacion normaliza **solo el vehiculo propio** por omision,
porque los demas son terceros. Eso hace que su caudal dependa de una eleccion y
no solo de la fuente, de modo que se miden **las dos formas** y se informan por
separado. Dar una sola escondería la eleccion detras de un numero.

Esta medicion no abre sockets, no consulta la base y no toca ningun servicio.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from adapters import can_rav4, f1_25 as adaptador_f1, openf1  # noqa: E402
from backend import can_capture, f1_capture, f1_udp  # noqa: E402

CAPTURAS_F1 = RAIZ / "datasets" / "f1_25" / "capturas"
CAPTURAS_CAN = RAIZ / "datasets" / "can" / "capturas"
OPENF1 = RAIZ / "datasets" / "OpenF1" / "raw" / "2025" / "9955"

# Cuantas unidades de entrada se toman de cada fuente. Acotado para que la
# medicion sea rapida; el caudal es una tasa y no depende del tamano de la
# muestra mientras sea representativa.
MUESTRA = 20000


def _por_segundo(mensajes: int, span_s: float) -> float:
    return mensajes / span_s if span_s > 0 else float("nan")


# Hueco a partir del cual se considera que la fuente **no estaba emitiendo**. Con
# datagramas que llegan cada pocos milisegundos, un segundo entero de silencio no
# es irregularidad: es el juego en un menu, en pausa o en una repeticion.
#
# Descontarlo no es un refinamiento opcional. Sin descontarlo, la primera version
# de esta medicion dio 73 datagramas por segundo para una fuente cuya tasa ya
# estaba medida en 143: la muestra arrancaba en el menu previo a la sesion y el
# tiempo muerto entraba entero al divisor. Es el mismo error que ya habia
# aparecido al medir la tasa de entrega.
HUECO_MUERTO_S = 1.0


def _tiempo_vivo(marcas_s: list[float]) -> tuple[float, float]:
    """Devuelve (tiempo vivo, tiempo muerto) de una serie de instantes."""

    if len(marcas_s) < 2:
        return 0.0, 0.0
    muerto = sum(b - a for a, b in zip(marcas_s, marcas_s[1:])
                 if b - a > HUECO_MUERTO_S)
    return (marcas_s[-1] - marcas_s[0]) - muerto, muerto


def medir_can(limite: int) -> dict:
    """Bus vehicular real: una trama por vez, muchas por segundo."""

    ruta = sorted(CAPTURAS_CAN.glob("*.canraw"))[0]
    meta = json.loads((ruta.with_suffix(ruta.suffix + ".meta.json"))
                      .read_text(encoding="utf-8"))
    inicio = meta.get("inicio_utc") or "2025-01-01T00:00:00+00:00"

    unidades = 0
    mensajes = 0
    respaldadas = 0
    marcas: list[float] = []
    for trama in can_capture.leer_captura(ruta):
        if unidades >= limite:
            break
        unidades += 1
        marcas.append(trama.instante_ns / 1e9)
        salida = can_rav4.mensajes_desde_trama(
            trama.identificador, trama.datos, trama.instante_ns, inicio,
            meta.get("segmento", "?"), trama.bus)
        if salida:
            respaldadas += 1
        mensajes += len(salida)

    span, muerto = _tiempo_vivo(marcas)
    return {
        "fuente": "Bus vehicular (CAN real)",
        "tiempo_muerto_s": muerto,
        "archivo": ruta.name,
        "unidad": "trama",
        "unidades": unidades,
        "span_s": span,
        "unidades_por_s": _por_segundo(unidades, span),
        "mensajes": mensajes,
        "mensajes_por_s": _por_segundo(mensajes, span),
        # La proporcion de tramas que el catalogo respalda. Es la que explica por
        # que el caudal en mensajes puede ser menor que el de tramas: la mayoria
        # de los identificadores de un bus no tiene semantica documentada.
        "unidades_con_significado": respaldadas,
        "senales_por_unidad": (mensajes / respaldadas) if respaldadas else 0.0,
    }


def medir_openf1(limite: int) -> dict:
    """Fuente deportiva ya procesada: una muestra por vehiculo."""

    from datetime import datetime

    ruta = OPENF1 / "car_data_driver_1_VER.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))[:limite]

    mensajes = 0
    for m in datos:
        mensajes += len(openf1.messages_from_openf1_sample(
            m, "car_data", "https://api.openf1.org/v1/car_data", str(ruta)))

    ordenadas = sorted(datetime.fromisoformat(m["date"]) for m in datos)
    base = ordenadas[0] if ordenadas else None
    span, muerto = _tiempo_vivo([(m - base).total_seconds() for m in ordenadas])
    return {
        "fuente": "Fuente deportiva (OpenF1)",
        "tiempo_muerto_s": muerto,
        "archivo": ruta.name,
        "unidad": "muestra de un vehiculo",
        "unidades": len(datos),
        "span_s": span,
        "unidades_por_s": _por_segundo(len(datos), span),
        "mensajes": mensajes,
        "mensajes_por_s": _por_segundo(mensajes, span),
        "unidades_con_significado": len(datos),
        "senales_por_unidad": mensajes / len(datos) if datos else 0.0,
    }


def medir_f1_25(limite: int, todos_los_vehiculos: bool) -> dict:
    """Simulacion en vivo: un datagrama puede describir a toda la parrilla."""

    ruta = max(CAPTURAS_F1.glob("*carrera*.f1raw"), key=lambda p: p.stat().st_size)
    inicio = "2026-01-01T00:00:00+00:00"

    unidades = 0
    mensajes = 0
    decodificados = 0
    sin_normalizacion = 0
    marcas: list[float] = []
    for dg in f1_capture.leer_captura(ruta):
        if unidades >= limite:
            break
        unidades += 1
        marcas.append(dg.desplazamiento_us / 1e6)
        try:
            d = f1_udp.decodificar(dg.carga)
        except Exception:
            continue
        if not d.get("decodificado"):
            continue
        # Un paquete puede decodificarse y aun asi no tener normalizacion
        # definida ---los eventos, por caso---. El adaptador lo rechaza a
        # proposito. Se cuentan aparte y no se tapan: son datagramas que llegan y
        # no producen ningun mensaje del contrato, y esconderlos inflaria las
        # senales por unidad al dividir por menos unidades de las que llegaron.
        try:
            salida = adaptador_f1.mensajes_desde_paquete(
                d, inicio, solo_vehiculo_propio=not todos_los_vehiculos)
        except adaptador_f1.ErrorNormalizacion:
            sin_normalizacion += 1
            continue
        decodificados += 1
        mensajes += len(salida)

    span, muerto = _tiempo_vivo(marcas)
    cual = "toda la parrilla" if todos_los_vehiculos else "vehiculo propio"
    return {
        "fuente": f"Simulacion (F1 25, {cual})",
        "archivo": ruta.name,
        "unidad": "datagrama",
        "unidades": unidades,
        "span_s": span,
        "unidades_por_s": _por_segundo(unidades, span),
        "mensajes": mensajes,
        "mensajes_por_s": _por_segundo(mensajes, span),
        "unidades_con_significado": decodificados,
        "sin_normalizacion": sin_normalizacion,
        "tiempo_muerto_s": muerto,
        "senales_por_unidad": (mensajes / decodificados) if decodificados else 0.0,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--muestra", type=int, default=MUESTRA,
                    help="unidades de entrada por fuente")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    filas = [
        medir_openf1(args.muestra),
        medir_f1_25(args.muestra, todos_los_vehiculos=False),
        medir_f1_25(args.muestra, todos_los_vehiculos=True),
        medir_can(args.muestra),
    ]

    print("Caudal de cada fuente, medido pasando datos reales por su adaptador.")
    print("La ultima columna es la unica comparable entre fuentes.")
    print()
    print(f"  {'fuente':<38}{'unidad/s':>11}{'senales':>9}{'utiles':>9}"
          f"{'MENSAJES/s':>13}")
    print("  " + "-" * 80)
    for f in filas:
        utiles = (f["unidades_con_significado"] / f["unidades"] * 100
                  if f["unidades"] else 0.0)
        print(f"  {f['fuente']:<38}{f['unidades_por_s']:>11,.0f}"
              f"{f['senales_por_unidad']:>9.1f}{utiles:>8.0f}%"
              f"{f['mensajes_por_s']:>13,.0f}")

    caudales = [f["mensajes_por_s"] for f in filas]
    print()
    print(f"  entre la mas baja y la mas alta: "
          f"{max(caudales) / min(caudales):,.0f} veces")

    if args.json:
        args.json.write_text(json.dumps(filas, indent=1), encoding="utf-8")
        print(f"\n  crudo en {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
