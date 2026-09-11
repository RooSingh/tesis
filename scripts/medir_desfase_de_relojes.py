#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mide la deriva entre relojes y el retardo sobre el piso de una captura.

    python3 scripts/medir_desfase_de_relojes.py datasets/f1_25/capturas/*.f1raw

El por que del metodo esta en `backend/analisis/desfase_de_relojes.py`. Este
guion solo recorre el archivo, arma los pares y reporta.

TRES DECISIONES DE RECORRIDO QUE VALE DECLARAR
----------------------------------------------
SE MIDE UN TIPO DE PAQUETE POR VEZ, Y ESTO NO ES UN DETALLE. El juego emite
varios paquetes con el **mismo** `session_time`: en un cuadro salen el de
movimiento, el de telemetria, el de estado. Los serializa en orden, de modo que
cada tipo sale a una distancia distinta del comienzo del cuadro.

La primera version de este guion tomaba **el primero de cada cuadro**, creyendo
que marcaba cuando ese cuadro empezo a llegar. No lo marca: cual llega primero
**cambia de cuadro en cuadro**. Medido sobre una captura de Suzuka, el primer
paquete fue de tipo 11 en 190 cuadros, de tipo 10 en 156, de tipo 3 en 73 y de
tipo 1 en 41. Mezclar tipos convierte la distancia entre clases de mensaje en un
retardo que nadie sufrio: cuatro capturas daban **mediana 201 ms con percentil
99 de 201 ms** ---casi todos los cuadros al mismo valor, que no es una
distribucion de retardos sino dos grupos---. Medidas por tipo, esas mismas
capturas dan entre 0,77 y 1,05 ms.

Asi que se agrupa por `packet_id` y se mide cada tipo por separado. La cifra de
referencia es la del paquete que el sistema **consume** para la telemetria; las
demas se informan al lado, porque la diferencia entre ellas es una propiedad
real del emisor y no ruido.

UN PAR POR INSTANTE DENTRO DE CADA TIPO. Un mismo tipo puede repetir
`session_time`; se queda el primero.

LOS DATAGRAMAS ANTERIORES AL ARRANQUE DE LA SESION SE DESCARTAN. Con la sesion
sin empezar, `session_time` vale cero en todos, y un tramo entero con la misma
abscisa no aporta pendiente y si corre el piso.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import f1_capture, f1_udp                       # noqa: E402
from backend.analisis import desfase_de_relojes as dr        # noqa: E402


#: El paquete de telemetria del vehiculo. Es el que alimenta las señales que el
#: sistema publica, asi que es el que corresponde citar como «cuanto tarda un
#: dato». Los demas se informan al lado.
PAQUETE_DE_REFERENCIA = 6

#: Los paquetes que **no** se emiten por cuadro. El propio catalogo del
#: protocolo lo declara en `frecuencia`, asi que no hace falta suponerlo: se lee.
#:
#: POR QUE HAY QUE EXCLUIRLOS. Un retardo se mide contra el instante en que el
#: emisor dijo que ese dato valia, y eso solo tiene sentido si el dato se emite
#: con el cuadro. El paquete de eventos se emite **cuando pasa algo**, y su
#: `session_time` es el del hecho, no el del envio: medido sobre una captura de
#: Suzuka daba 200,74 ms de mediana mientras los periodicos daban menos de 1,2.
#: Esa cifra no es un retardo de nadie.
NO_PERIODICOS = {"evento", "fin"}


def pares_por_tipo(ruta: Path) -> tuple[dict[int, list[tuple[float, float]]], dict]:
    """Los pares `(session_time, llegada)` de cada tipo, y lo que se descarto."""

    por_tipo: dict[int, list[tuple[float, float]]] = {}
    vistos: dict[int, set[float]] = {}
    leidos = cortos = sin_arrancar = repetidos = 0

    for d in f1_capture.leer_captura(ruta):
        leidos += 1
        if len(d.carga) < f1_udp.CABECERA_TAMANO:
            cortos += 1
            continue
        cabecera = f1_udp.decodificar_cabecera(d.carga)
        t = cabecera.get("session_time")
        if t is None or t <= 0:
            sin_arrancar += 1
            continue
        pid = cabecera.get("packet_id")
        visto = vistos.setdefault(pid, set())
        if t in visto:
            repetidos += 1
            continue
        visto.add(t)
        por_tipo.setdefault(pid, []).append(
            (float(t), d.desplazamiento_us / 1_000_000.0))

    return por_tipo, {"leidos": leidos, "cortos": cortos,
                      "sin_arrancar": sin_arrancar, "repetidos": repetidos}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("capturas", nargs="+", type=Path)
    p.add_argument("--paquete", type=int, default=PAQUETE_DE_REFERENCIA,
                   help="que tipo de paquete se cita como referencia")
    p.add_argument("--minimo", type=int, default=50,
                   help="cuantos cuadros hacen falta para medir un tipo")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    salida = []
    for ruta in args.capturas:
        if not ruta.exists():
            print(f"  no existe: {ruta}", file=sys.stderr)
            continue
        por_tipo, cuentas = pares_por_tipo(ruta)

        medidos = {}
        for pid, pares in por_tipo.items():
            cual = f1_udp.PAQUETES.get(pid) or {}
            if cual.get("frecuencia") in NO_PERIODICOS:
                continue
            if len(pares) >= args.minimo:
                medidos[pid] = dr.medir(pares)
        if not medidos:
            print(f"  {ruta.name}: ningun tipo de paquete llega a {args.minimo} "
                  f"cuadros con la sesion arrancada", file=sys.stderr)
            continue

        ref = args.paquete if args.paquete in medidos else min(medidos)
        d = medidos[ref]
        fila = {
            "captura": ruta.name,
            "paquete_de_referencia": ref,
            "deriva": round(d.deriva, 9),
            "retardo_mediano_ms": round(d.mediana_ms, 3),
            "retardo_p99_ms": round(d.p99_ms, 3),
            "retardo_maximo_ms": round(d.maximo_ms, 3),
            "cuadros": d.datagramas,
            "duracion_s": round(d.duracion_s, 1),
            "datagramas_leidos": cuentas["leidos"],
            "por_paquete": {
                str(pid): {"cuadros": m.datagramas,
                           "mediana_ms": round(m.mediana_ms, 3),
                           "p99_ms": round(m.p99_ms, 3),
                           "deriva": round(m.deriva, 9)}
                for pid, m in sorted(medidos.items())
            },
            "relativo_a": "el datagrama mas rapido de esta corrida y de este tipo "
                          "de paquete; no es un retardo absoluto, porque los dos "
                          "relojes nunca se sincronizaron",
        }
        salida.append(fila)
        if not args.json:
            print(f"\n  {ruta.name}   (paquete de referencia: {ref})")
            print(f"    {d.como_texto()}")
            otros = " · ".join(
                f"{(f1_udp.PAQUETES.get(pid) or {}).get('nombre', pid)}"
                f" {m.mediana_ms:.2f}"
                for pid, m in sorted(medidos.items()))
            print(f"    mediana por paquete, en ms — {otros}")

    if args.json:
        for fila in salida:
            print(json.dumps(fila, ensure_ascii=False))
    return 0 if salida else 1


if __name__ == "__main__":
    raise SystemExit(main())
