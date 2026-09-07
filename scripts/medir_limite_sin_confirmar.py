# -*- coding: utf-8 -*-
"""Mide cuantos mensajes entrega el intermediario sin que se le confirmen.

Que decide esta medicion
------------------------
La confirmacion manual solo es viable si ese limite deja pasar el caudal que el
sistema necesita. Con confirmacion manual, el acuse se emite **despues de haber
escrito en la base**, de modo que el limite del intermediario y la latencia de
escritura se multiplican para fijar el techo:

    caudal maximo = limite sin confirmar / latencia de escritura de un lote

Si el limite fuera veinte y un lote tardara trescientos milisegundos, el techo
seria de unos sesenta y seis mensajes por segundo, y la parrilla completa necesita
sesenta y tres. Es demasiado al filo para suponerlo: hay que medirlo.

Como se mide
------------
Un suscriptor con confirmacion manual que **no confirma nada**. Se publica una
cantidad conocida y se cuenta cuantos llegan antes de que la entrega se detenga.
Ese numero es el limite.

Despues se confirman todos y se comprueba que el resto llegue: eso distingue «el
intermediario dejo de mandar» de «los mensajes nunca se publicaron», que son dos
cosas con el mismo sintoma.

Por que un topico propio
------------------------
Se usa un topico de prueba y no el de telemetria. Un suscriptor que no confirma
retiene mensajes en el intermediario, y hacerlo sobre el topico real dejaria al
consumidor de produccion compitiendo por la misma cola.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
import sys

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

import paho.mqtt.client as mqtt  # noqa: E402

from backend.config import MQTT_HOST, MQTT_PORT  # noqa: E402

TOPICO = "tesis/prueba/limite-sin-confirmar"

#: Cuanto se espera sin recibir nada nuevo para dar la entrega por detenida. El
#: intermediario no avisa que dejo de mandar: simplemente deja de mandar, de modo
#: que la unica senal es el silencio.
SILENCIO_S = 6.0


def medir(cantidad: int, identidad: str) -> dict:
    recibidos: list[tuple[int, int]] = []
    ultimo = {"t": time.perf_counter()}

    def al_llegar(cliente, datos, mensaje):
        recibidos.append((mensaje.mid, mensaje.qos))
        ultimo["t"] = time.perf_counter()

    suscriptor = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                             client_id=identidad, clean_session=False)
    # La confirmacion manual es lo que se esta midiendo: sin ella la biblioteca
    # confirma al volver del callback y el limite nunca se alcanza.
    suscriptor.manual_ack_set(True)
    suscriptor.on_message = al_llegar
    suscriptor.connect(MQTT_HOST, MQTT_PORT, 60)
    suscriptor.loop_start()
    suscriptor.subscribe(TOPICO, 1)
    time.sleep(2.0)

    publicador = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                             client_id=identidad + "-pub")
    publicador.connect(MQTT_HOST, MQTT_PORT, 60)
    publicador.loop_start()
    publicados = 0
    for i in range(cantidad):
        info = publicador.publish(TOPICO, f"m{i}", qos=1)
        info.wait_for_publish(timeout=10)
        if info.is_published():
            publicados += 1

    # Se espera el silencio: la entrega detenida no se anuncia.
    ultimo["t"] = time.perf_counter()
    while time.perf_counter() - ultimo["t"] < SILENCIO_S:
        time.sleep(0.5)
    sin_confirmar = len(recibidos)

    # Ahora se confirman todos. Si el resto llega, el limite era del
    # intermediario; si no llega nada, el problema estaba en la publicacion.
    for mid, qos in list(recibidos):
        suscriptor.ack(mid, qos)
    ultimo["t"] = time.perf_counter()
    while time.perf_counter() - ultimo["t"] < SILENCIO_S:
        time.sleep(0.5)
    despues_de_confirmar = len(recibidos)

    publicador.loop_stop()
    publicador.disconnect()
    suscriptor.loop_stop()
    suscriptor.disconnect()

    return {
        "publicados": publicados,
        "entregados_sin_confirmar": sin_confirmar,
        "entregados_tras_confirmar": despues_de_confirmar - sin_confirmar,
        "total_entregados": despues_de_confirmar,
        "faltantes": publicados - despues_de_confirmar,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cantidad", type=int, default=200)
    ap.add_argument("--salida", type=Path,
                    default=RAIZ / "logs" / "limite_sin_confirmar.json")
    args = ap.parse_args()

    identidad = "prueba-limite-" + datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%S")
    print(f"  publicando {args.cantidad} sin confirmar ninguno...")
    r = medir(args.cantidad, identidad)
    r["identidad"] = identidad
    args.salida.write_text(json.dumps(r, indent=1, ensure_ascii=False),
                           encoding="utf-8")

    print()
    print(f"  publicados                  : {r['publicados']}")
    print(f"  entregados SIN confirmar    : {r['entregados_sin_confirmar']}")
    print(f"  entregados tras confirmar   : {r['entregados_tras_confirmar']}")
    print(f"  total entregados            : {r['total_entregados']}")
    print(f"  faltantes                   : {r['faltantes']}")
    print()
    limite = r["entregados_sin_confirmar"]
    if r["entregados_tras_confirmar"] > 0:
        print(f"  EL LIMITE ES {limite}: el intermediario retuvo el resto hasta "
              "recibir los acuses")
        print()
        for latencia_ms in (50, 100, 300, 500):
            techo = limite / (latencia_ms / 1000.0)
            print(f"    con lotes de {latencia_ms:>3} ms el techo seria "
                  f"{techo:>8,.0f} mensajes/s")
    elif limite >= r["publicados"]:
        print("  NO SE ALCANZO EL LIMITE: entregó todo sin confirmar. Hay que "
              "repetir con mas mensajes.")
    else:
        print("  RESULTADO AMBIGUO: no llego el resto al confirmar, de modo que "
              "el corte pudo no ser del intermediario.")
    print(f"  detalle en {args.salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
