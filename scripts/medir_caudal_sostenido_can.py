# -*- coding: utf-8 -*-
"""Mide si la cadena **mantiene el ritmo** durante media hora de bus vehicular.

La pregunta, y por que no la contesta ninguna medicion anterior
---------------------------------------------------------------
Ya se midio cuanto aguanta la cadena: 1.804 mensajes por segundo antes de la
primera perdida. Y ya se midio una sesion prolongada, que fue **carga masiva sin
restriccion de tiempo real**: se empuja todo lo que se pueda y se mira si algo se
rompe.

Esta es la pregunta inversa y no la responde ninguna de las dos. La carga es
moderada ---unas 3.850 tramas por segundo--- pero **no se puede atrasar**, porque
un bus emite cuando emite y no espera a nadie. Lo que se busca no es una perdida:

    **es que se acumule atraso.**

Un sistema puede no perder un solo mensaje y ser inservible en vivo si procesa un
uno por ciento mas lento de lo que recibe: a los veinte minutos va tres minutos
atras, y cada panel muestra el pasado sin decirlo.

Que se observa
--------------
Tres cosas, y las tres son necesarias:

1. **el atraso del consumidor** (`pending`), que es la respuesta directa. Si
   crece de forma sostenida, la cadena no mantiene el ritmo;
2. **el descarte del intermediario**, que es la otra forma de no mantener el
   ritmo: en vez de acumularse, se tira;
3. **la deriva del propio emisor.** Si publicar sesenta segundos de grabacion
   tarda mas de sesenta segundos, **la prueba fallo antes de la cadena** y
   medir el atraso del consumidor no significaria nada. Se mide primero porque
   invalida todo lo demas.

Por que un identificador por segmento
-------------------------------------
Cada mensaje lleva `replay_run_id` y `replay_seq`, y la segunda **se reinicia en
cada llamada**. Encadenar treinta segmentos bajo un mismo identificador haria
colisionar las claves, y el indice unico descartaria filas **en silencio**: la
medicion mostraria una cadena comodisima porque la mitad del trabajo no se
estaria haciendo. Cada segmento va con su propio identificador.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from scripts.reproducir_can import emitir_por_broker  # noqa: E402

CAPTURAS = RAIZ / "datasets" / "can" / "capturas"
METRICAS = RAIZ / "logs" / "consumidor_metricas.json"

#: Cada segmento del conjunto dura sesenta segundos de grabacion.
SEGUNDOS_POR_SEGMENTO = 60.0

#: Cada cuanto se toma una muestra del estado del consumidor. Cinco segundos da
#: unas trescientas sesenta muestras en media hora: suficiente para ver una
#: tendencia y poco para estorbar.
INTERVALO_MUESTREO_S = 5.0


def _leer_metricas() -> dict | None:
    """Lee el archivo de metricas del consumidor, tolerando lecturas parciales.

    El consumidor lo reescribe entero cada pocos segundos, de modo que una
    lectura puede caer en el medio. Un JSON incompleto no es un error de la
    medicion: es una muestra que se saltea.
    """

    try:
        return json.loads(METRICAS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class Muestreador(threading.Thread):
    """Toma muestras del consumidor mientras el emisor trabaja."""

    def __init__(self, salida: Path) -> None:
        super().__init__(daemon=True)
        self.salida = salida
        self.muestras: list[dict] = []
        self._parar = threading.Event()

    def run(self) -> None:
        inicio = time.perf_counter()
        while not self._parar.is_set():
            m = _leer_metricas()
            if m is not None:
                self.muestras.append({
                    "t_s": round(time.perf_counter() - inicio, 2),
                    "recibidos": m.get("received"),
                    "persistidos": m.get("persisted"),
                    "pendientes": m.get("pending"),
                    "pendiente_maximo": m.get("max_pending"),
                    "esperas_por_contrapresion": m.get("backpressure_waits"),
                    "descartados_por_broker": m.get("broker_dropped"),
                    "lotes": m.get("batches"),
                })
            self._parar.wait(INTERVALO_MUESTREO_S)

    def detener(self) -> None:
        self._parar.set()


def correr(segmentos: list[str], velocidad: float, salida: Path) -> dict:
    marca = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    muestreador = Muestreador(salida)
    muestreador.start()

    emision = []
    total = 0
    comienzo = time.perf_counter()
    for i, seg in enumerate(segmentos, 1):
        ruta = CAPTURAS / f"{seg}.canraw"
        t0 = time.perf_counter()
        publicados = emitir_por_broker(
            ruta,
            datetime.now(timezone.utc).isoformat(),
            SEGUNDOS_POR_SEGMENTO,
            run_id=f"caudal_sostenido_{marca}_{i:02d}",
            velocidad=velocidad,
        )
        transcurrido = time.perf_counter() - t0
        esperado = SEGUNDOS_POR_SEGMENTO / velocidad
        emision.append({
            "segmento": seg,
            "publicados": publicados,
            "esperado_s": round(esperado, 2),
            "real_s": round(transcurrido, 2),
            # Positivo significa que el emisor tardo de mas: no llego a publicar
            # al ritmo del bus, y la prueba fallo antes de la cadena.
            "deriva_s": round(transcurrido - esperado, 2),
        })
        total += publicados
        print(f"  [{i:2d}/{len(segmentos)}] {seg}: {publicados} publicados en "
              f"{transcurrido:.1f} s (esperado {esperado:.0f}, deriva "
              f"{transcurrido - esperado:+.1f} s)", flush=True)

    duracion = time.perf_counter() - comienzo
    # Se deja correr el muestreo un poco mas: el consumidor puede seguir
    # drenando despues de que el emisor termino, y **ese drenaje es parte de la
    # respuesta**. Cortar en seco mostraria un atraso que en realidad se resolvia.
    time.sleep(30)
    muestreador.detener()
    muestreador.join(timeout=10)

    return {
        "marca": marca,
        "segmentos": len(segmentos),
        "velocidad": velocidad,
        "publicados_total": total,
        "duracion_total_s": round(duracion, 1),
        "deriva_total_s": round(
            duracion - len(segmentos) * SEGUNDOS_POR_SEGMENTO / velocidad, 1),
        "emision": emision,
        "muestras": muestreador.muestras,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--segmentos", nargs="*", default=None,
                    help="Nombres de segmento. Por defecto, los treinta.")
    ap.add_argument("--velocidad", type=float, default=1.0,
                    help="A uno, emite como emitiria el bus. Cambiarlo "
                         "responde otra pregunta.")
    ap.add_argument("--salida", type=Path,
                    default=RAIZ / "logs" / "caudal_sostenido_can.json")
    args = ap.parse_args()

    segmentos = args.segmentos or sorted(
        p.stem for p in CAPTURAS.glob("*.canraw"))
    if not segmentos:
        raise SystemExit("no hay segmentos en datasets/can/capturas")

    print(f"Encadenando {len(segmentos)} segmentos a {args.velocidad:g}x "
          f"({len(segmentos) * SEGUNDOS_POR_SEGMENTO / args.velocidad / 60:.0f} "
          f"minutos de reloj)", flush=True)

    resultado = correr(segmentos, args.velocidad, args.salida)
    args.salida.write_text(json.dumps(resultado, indent=2, ensure_ascii=False),
                           encoding="utf-8")

    ms = resultado["muestras"]
    pend = [m["pendientes"] for m in ms if m["pendientes"] is not None]
    print()
    print(f"publicados: {resultado['publicados_total']}")
    print(f"duracion:   {resultado['duracion_total_s']} s  "
          f"(deriva {resultado['deriva_total_s']:+.1f} s)")
    if pend:
        print(f"pendientes: minimo {min(pend)}  maximo {max(pend)}  "
              f"ultimo {pend[-1]}")
    print(f"serie completa en {args.salida}")


if __name__ == "__main__":
    main()
