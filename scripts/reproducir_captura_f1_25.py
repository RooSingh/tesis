# -*- coding: utf-8 -*-
"""Reproduce una captura de F1 25 por UDP, con degradacion controlada.

Para que sirve
--------------
El modulo `backend.f1_capture` sabe recorrer una captura y degradarla, pero
**deliberadamente no abre ningun socket**: emitir por red es responsabilidad de
quien lo use, para que la degradacion se pueda probar sin tocar la red. Este
script es esa responsabilidad.

Al emitir al mismo puerto en que escucha el capturador, la captura vuelve a
recorrer **la cadena real completa** ---capturador, adaptador, intermediario,
consumidor, base--- sin que el juego este abierto y sin que nadie tenga que
manejar. Eso es lo que vuelve ejecutables los escenarios de frecuencia variable
y de llegada irregular, que hasta ahora dependian de una persona jugando.

La diferencia con el generador propio
-------------------------------------
El generador produce datos sinteticos: medir el sistema contra el es
parcialmente circular. Esto degrada **trafico real ya capturado**, de modo que el
escenario conserva la forma del trafico verdadero y agrega solo la falla que se
quiere estudiar.

Los tiempos, y la unica forma honesta de tratarlos
--------------------------------------------------
Cada datagrama trae el instante en que llego. Reproducir es esperar hasta ese
instante y emitir. Pero con jitter el instante de un datagrama puede quedar
**antes** del instante en que ya se emitio el anterior, y ahi no hay espera
posible: la unica opcion es emitir en el acto.

Esos casos se cuentan, pero **contra una tolerancia declarada y no contra cero**.
Los datagramas de un mismo instante salen uno detras del otro y el segundo llega
tarde por microsegundos: contarlo como incumplimiento informaba un 84 % de
atrasos sobre un calendario que en realidad se respetaba con un desvio mediano de
0,32 ms. Con la tolerancia en un milisegundo ---cincuenta veces mas chica que la
irregularidad que la propia fuente ya tiene--- los atrasos reales quedan visibles
y el ruido de la forma del trafico no se disfraza de defecto.

Sin ese numero uno creeria haber reproducido un perfil que no se respeto.
"""

from __future__ import annotations

import argparse
import json
import socket
import statistics
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from backend import f1_capture, f1_udp  # noqa: E402

# El puerto en que escucha el capturador. Emitir aca es lo que hace que la
# reproduccion recorra la cadena real y no una maqueta.
PUERTO_CAPTURADOR = 20777

# Por debajo de esto no se duerme: el sistema operativo no garantiza esperas tan
# cortas y pedirlas cuesta mas que el error que evitan.
ESPERA_MINIMA_S = 0.0005

# Cuanto puede correrse una emision de su instante previsto antes de contar como
# incumplimiento del calendario.
#
# El valor sale de la fuente y no del gusto: la propia F1 25 entrega sus
# datagramas con una irregularidad medida de decenas de milisegundos ---alterna
# intervalos de 34 y 66 ms donde promete 50---. Un reproductor que se corre menos
# de un milisegundo es, frente a eso, exacto. Contar como atraso una desviacion de
# microsegundos informaria un 84 % de incumplimiento sobre un calendario que en
# realidad se respeto.
TOLERANCIA_MS = 1.0


#: Posicion del tipo de paquete dentro de la cabecera: dos bytes de formato mas
#: cuatro de version. Se lee ese byte suelto en lugar de decodificar el datagrama
#: entero, porque silenciar es una decision por paquete y decodificar cada uno
#: costaria mas que emitirlo.
POSICION_TIPO_DE_PAQUETE = 6


def tipos_por_nombre(nombres: list[str]) -> set[int]:
    """Traduce nombres de paquete a sus identificadores.

    Falla ante un nombre desconocido en lugar de ignorarlo: una prueba que cree
    haber silenciado un canal y no lo haya silenciado daria por bueno el
    comportamiento que venia a poner a prueba.
    """

    por_nombre = {d["nombre"]: i for i, d in f1_udp.PAQUETES.items()}
    ids = set()
    for nombre in nombres:
        if nombre not in por_nombre:
            conocidos = ", ".join(sorted(por_nombre))
            raise SystemExit(f"paquete desconocido: {nombre!r}. "
                             f"Los que hay son: {conocidos}")
        ids.add(por_nombre[nombre])
    return ids


def reproducir_por_udp(ruta: Path, destino: tuple[str, int],
                       perfil: f1_capture.PerfilDegradacion,
                       velocidad: float = 1.0,
                       sin_red: bool = False,
                       limite: int | None = None,
                       tolerancia_ms: float = TOLERANCIA_MS,
                       silenciar: set[int] | None = None) -> dict:
    """Emite la captura respetando sus tiempos y devuelve lo que hizo."""

    metricas = f1_capture.MetricasReproduccion()
    sock = None
    if not sin_red:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    atrasados = 0
    desvios_us: list[int] = []
    enviados = 0
    silenciados = 0
    silenciar = silenciar or set()
    arranque = time.perf_counter()
    try:
        for dg in f1_capture.reproducir(ruta, perfil, metricas):
            # El calendario se calcula siempre contra el arranque, no contra el
            # datagrama anterior: acumular esperas relativas corre el reloj y la
            # reproduccion termina durando distinto que la captura.
            objetivo = arranque + (dg.desplazamiento_us / 1e6) / velocidad
            falta = objetivo - time.perf_counter()
            if falta > ESPERA_MINIMA_S:
                time.sleep(falta)

            ahora = time.perf_counter()
            desvio_us = int((ahora - objetivo) * 1e6)
            desvios_us.append(desvio_us)
            # Atrasado es haberse corrido **mas que la tolerancia**, no haberse
            # corrido. Los datagramas de un mismo instante salen uno detras del
            # otro y el segundo siempre llega tarde por microsegundos: eso es la
            # forma del trafico, no un incumplimiento.
            if desvio_us > tolerancia_ms * 1000:
                atrasados += 1
            # El silencio va **despues** de haber respetado el calendario: un
            # sensor que deja de emitir no acelera a los demas, y adelantar los
            # datagramas restantes cambiaria la prueba por otra.
            if silenciar and len(dg.carga) > POSICION_TIPO_DE_PAQUETE                     and dg.carga[POSICION_TIPO_DE_PAQUETE] in silenciar:
                silenciados += 1
                continue
            if sock is not None:
                sock.sendto(dg.carga, destino)
            enviados += 1
            if limite is not None and enviados >= limite:
                break
    finally:
        if sock is not None:
            sock.close()

    transcurrido = time.perf_counter() - arranque
    resultado = metricas.como_dict()
    resultado.update({
        "enviados": enviados,
        "silenciados": silenciados,
        "duracion_s": transcurrido,
        "atrasados": atrasados,
        # Cuanto se corrio cada emision respecto de su instante previsto. Es la
        # fidelidad del calendario, y hay que informarla porque la degradacion
        # que se quiso inyectar solo vale si el resto se respeto.
        "desvio_mediano_us": statistics.median(desvios_us) if desvios_us else 0,
        "desvio_maximo_us": max(desvios_us) if desvios_us else 0,
        "desvio_p99_us": (sorted(desvios_us)[min(len(desvios_us) - 1,
                                                 int(0.99 * (len(desvios_us) - 1)))]
                          if desvios_us else 0),
        "tolerancia_ms": tolerancia_ms,
        "velocidad": velocidad,
        "sin_red": sin_red,
        "perfil": {
            "probabilidad_descarte": perfil.probabilidad_descarte,
            "jitter_us": perfil.jitter_us,
            "retraso_us": perfil.retraso_us,
            "semilla": perfil.semilla,
        },
    })
    return resultado


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("captura", type=Path, help="archivo .f1raw a reproducir")
    ap.add_argument("--destino", default="127.0.0.1",
                    help="a donde emitir (por omision, esta maquina)")
    ap.add_argument("--puerto", type=int, default=PUERTO_CAPTURADOR,
                    help="puerto del receptor")
    ap.add_argument("--velocidad", type=float, default=1.0,
                    help="multiplicador del tiempo; 2 reproduce al doble")
    ap.add_argument("--silenciar", action="append", default=[], metavar="PAQUETE",
                    help="deja de emitir ese tipo de paquete, de forma sostenida. "
                         "Es el fallo parcial de sensado: no se pierde un "
                         "datagrama suelto sino que un canal deja de existir. "
                         "Se puede repetir.")
    ap.add_argument("--descarte", type=float, default=0.0,
                    help="probabilidad de descartar cada datagrama, 0 a 1")
    ap.add_argument("--jitter-ms", type=float, default=0.0,
                    help="desviacion maxima del instante, en mas o en menos")
    ap.add_argument("--retraso-ms", type=float, default=0.0,
                    help="desplazamiento fijo de todo el flujo")
    ap.add_argument("--semilla", type=int, default=0,
                    help="fija el azar; la misma semilla repite la degradacion")
    ap.add_argument("--limite", type=int, default=None,
                    help="corta despues de esta cantidad de datagramas")
    ap.add_argument("--tolerancia-ms", type=float, default=TOLERANCIA_MS,
                    help="desde cuanto desvio se cuenta un atraso")
    ap.add_argument("--sin-red", action="store_true",
                    help="recorre y mide sin emitir, para verificar el perfil")
    ap.add_argument("--json", type=Path, help="escribe el resultado")
    args = ap.parse_args()

    if not args.captura.exists():
        print(f"no existe la captura: {args.captura}")
        return 1
    if args.velocidad <= 0:
        print("la velocidad tiene que ser positiva")
        return 1

    perfil = f1_capture.PerfilDegradacion(
        probabilidad_descarte=args.descarte,
        jitter_us=int(args.jitter_ms * 1000),
        retraso_us=int(args.retraso_ms * 1000),
        semilla=args.semilla,
    )
    try:
        perfil.validar()
    except ValueError as e:
        print(f"perfil invalido: {e}")
        return 1

    destino = (args.destino, args.puerto)
    print(f"reproduciendo {args.captura.name}")
    if args.sin_red:
        print("  sin emitir: solo se recorre y se mide el perfil")
    else:
        print(f"  hacia {destino[0]}:{destino[1]}")
    if args.silenciar:
        print(f"  silenciando: {', '.join(sorted(args.silenciar))}")
    print(f"  velocidad {args.velocidad:g}x, descarte {args.descarte:.1%}, "
          f"jitter {args.jitter_ms:g} ms, retraso {args.retraso_ms:g} ms, "
          f"semilla {args.semilla}")
    print()

    r = reproducir_por_udp(args.captura, destino, perfil, args.velocidad,
                           args.sin_red, args.limite, args.tolerancia_ms,
                           silenciar=tipos_por_nombre(args.silenciar))

    print(f"  leidos       {r['leidos']:>10,}")
    print(f"  descartados  {r['descartados']:>10,}  "
          f"({r['tasa_descarte']:.2%} pedido {args.descarte:.2%})")
    if r.get("silenciados"):
        print(f"  silenciados  {r['silenciados']:>10,}")
    print(f"  emitidos     {r['enviados']:>10,}")
    print(f"  duracion     {r['duracion_s']:>10.1f} s")
    print(f"  desvio del calendario: mediano {r['desvio_mediano_us'] / 1000:.2f} ms, "
          f"p99 {r['desvio_p99_us'] / 1000:.2f} ms, "
          f"maximo {r['desvio_maximo_us'] / 1000:.2f} ms")
    print(f"  atrasados    {r['atrasados']:>10,}  "
          f"({r['atrasados'] / max(1, r['enviados']):.2%} se corrio mas de "
          f"{r['tolerancia_ms']:g} ms)")

    # La conciliacion, contra lo que debia quedar y no contra lo que se evito.
    # Lo silenciado es un tercer sumando y no una perdida: el datagrama se leyo,
    # se decidio no emitirlo y se conto. Dejarlo fuera de la cuenta haria que la
    # unica verificacion de la herramienta fallara siempre que se la use.
    esperado = r["descartados"] + r.get("silenciados", 0) + r["emitidos"]
    if r["leidos"] != esperado and args.limite is None:
        print()
        print(f"  ATENCION: leidos ({r['leidos']:,}) no es descartados "
              f"({r['descartados']:,}) mas silenciados "
              f"({r.get('silenciados', 0):,}) mas emitidos ({r['enviados']:,})")
        return 1

    if args.json:
        args.json.write_text(json.dumps(r, indent=1), encoding="utf-8")
        print(f"\n  crudo en {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
