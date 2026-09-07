# -*- coding: utf-8 -*-
"""Comprueba que el intermediario tenga en efecto los topes que se le declararon.

Por que existe
--------------
Dos topes del intermediario deciden si la telemetria se pierde bajo carga, y **los
dos descartan en silencio en su valor por omision**:

- cuantos mensajes con garantia entrega sin que se los confirmen, que con la
  confirmacion manual fija el techo de caudal;
- cuantos retiene para un suscriptor ausente, que es hasta donde protege la sesion
  conservada.

Se los subio y se dejo la configuracion versionada en `infra/mosquitto.conf`. Pero
el contenedor se creo sin un archivo de composicion y su configuracion vive
adentro: **recrearlo devuelve los dos topes a su valor por omision y nada avisa**.

Este guion no impide esa vuelta atras. La hace visible, que es lo unico que se
puede garantizar mientras la configuracion no este montada desde el repositorio.

Como lo comprueba
-----------------
No leyendo el archivo de configuracion ---eso diria lo que se pidio, no lo que
rige--- sino **midiendo la conducta**:

- se abre un suscriptor con confirmacion manual que no confirma nada, se publica
  de mas, y se cuenta cuantos llegan antes de que la entrega se detenga. Ese numero
  es el tope de mensajes sin confirmar;
- se comprueba, ademas, que al confirmarlos llegue el resto. Si no llegara, el
  corte pudo no ser del tope sino de la publicacion, y son dos causas con el mismo
  sintoma.

El tope de la cola para un ausente **no se mide aca**: hacerlo exigiria publicar
mas de cien mil mensajes y dejarlos encolados, lo que tarda y ocupa memoria del
intermediario. Se lo declara como comprobacion pendiente en lugar de fingir que se
comprobo.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

import paho.mqtt.client as mqtt  # noqa: E402

from backend.config import MQTT_HOST, MQTT_PORT  # noqa: E402

CONFIGURACION = RAIZ / "infra" / "mosquitto.conf"
TOPICO = "tesis/prueba/topes"

#: Cuanto silencio se toma como entrega detenida. El intermediario no anuncia que
#: dejo de mandar: simplemente deja de mandar.
SILENCIO_S = 6.0


def declarado(nombre: str) -> int | None:
    """Lo que `infra/mosquitto.conf` declara para ese tope."""

    if not CONFIGURACION.exists():
        return None
    for linea in CONFIGURACION.read_text(encoding="utf-8").splitlines():
        limpia = linea.strip()
        if limpia.startswith("#") or not limpia:
            continue
        m = re.match(rf"^{nombre}\s+(\d+)$", limpia)
        if m:
            return int(m.group(1))
    return None


def medir_sin_confirmar(margen: int = 3) -> dict:
    """Cuantos mensajes entrega el intermediario sin recibir un solo acuse."""

    esperado = declarado("max_inflight_messages")
    cantidad = (esperado or 20) * margen

    recibidos: list[tuple[int, int]] = []
    ultimo = {"t": time.perf_counter()}
    identidad = "verifica-topes-" + datetime.now(timezone.utc).strftime("%H%M%S")

    def al_llegar(cliente, datos, mensaje):
        recibidos.append((mensaje.mid, mensaje.qos))
        ultimo["t"] = time.perf_counter()

    suscriptor = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                             client_id=identidad, clean_session=False)
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
    encolados = 0
    for i in range(cantidad):
        info = publicador.publish(TOPICO, f"m{i}", qos=1)
        info.wait_for_publish(timeout=10)
        # Se mira el codigo de retorno: un publicador que descarta en su cola de
        # salida haria pasar su propio limite por el del intermediario.
        if info.rc == 0 and info.is_published():
            encolados += 1

    ultimo["t"] = time.perf_counter()
    while time.perf_counter() - ultimo["t"] < SILENCIO_S:
        time.sleep(0.5)
    sin_confirmar = len(recibidos)

    for mid, qos in list(recibidos):
        suscriptor.ack(mid, qos)
    ultimo["t"] = time.perf_counter()
    while time.perf_counter() - ultimo["t"] < SILENCIO_S:
        time.sleep(0.5)
    tras_confirmar = len(recibidos) - sin_confirmar

    publicador.loop_stop()
    publicador.disconnect()
    suscriptor.loop_stop()
    suscriptor.disconnect()

    return {
        "declarado": esperado,
        "publicados": encolados,
        "entregados_sin_confirmar": sin_confirmar,
        "entregados_tras_confirmar": tras_confirmar,
        # La medicion solo concluye si al confirmar llego mas: eso descarta que el
        # corte haya sido de la publicacion y no del tope.
        "concluyente": tras_confirmar > 0 and sin_confirmar < encolados,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--salida", type=Path,
                    default=RAIZ / "logs" / "topes_intermediario.json")
    args = ap.parse_args()

    print(f"  configuracion declarada: {CONFIGURACION}")
    en_cola = declarado("max_queued_messages")
    print(f"  max_queued_messages declarado : {en_cola}"
          "   (no se mide aca, ver el encabezado)")
    print()
    print("  midiendo max_inflight_messages...")
    r = medir_sin_confirmar()
    r["max_queued_messages_declarado"] = en_cola
    r["medido"] = datetime.now(timezone.utc).isoformat()
    args.salida.write_text(json.dumps(r, indent=1, ensure_ascii=False),
                           encoding="utf-8")

    print()
    print(f"  declarado en la configuracion : {r['declarado']}")
    print(f"  medido sobre el intermediario : {r['entregados_sin_confirmar']}")
    print(f"  entregados al confirmar       : {r['entregados_tras_confirmar']}")
    print()

    if not r["concluyente"]:
        print("  MEDICION NO CONCLUYENTE: al confirmar no llego mas, de modo que "
              "el corte pudo no ser del tope. Repetir con mas mensajes.")
        return 2
    if r["declarado"] is None:
        print("  AVISO: la configuracion versionada no declara el tope; no hay "
              "contra que comparar.")
        return 2
    if r["entregados_sin_confirmar"] == r["declarado"]:
        print(f"  COINCIDE: el intermediario rige con {r['declarado']}.")
        return 0

    print(f"  NO COINCIDE. Declarado {r['declarado']}, en efecto "
          f"{r['entregados_sin_confirmar']}.")
    print()
    print("  El caso mas probable es que el contenedor se haya recreado y su")
    print("  configuracion haya vuelto al valor por omision. Se corrige copiando")
    print("  la configuracion versionada y **reiniciando** el contenedor: estos")
    print("  topes no se aplican en una recarga, y la recarga informa exito igual.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
