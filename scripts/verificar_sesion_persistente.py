# -*- coding: utf-8 -*-
"""Verifica que lo publicado mientras el consumidor esta caido no se pierda.

Que se prueba, y por que asi
----------------------------
Con la sesion conservada, el intermediario mantiene la suscripcion del consumidor
y **encola lo que llega mientras no esta**, para entregarselo al reconectar. Sin
ella, todo lo publicado durante una caida se pierde y ningun contador lo refleja.

La unica forma de comprobarlo es provocar la caida:

    1. el consumidor conecta y se suscribe, de modo que el intermediario
       registre su sesion;
    2. se lo detiene;
    3. se publica con garantia de entrega, con identidad de reinyeccion propia;
    4. se lo vuelve a levantar;
    5. se cuentan las filas en la base.

Si la sesion se conserva, aparecen todas. Si no, aparecen cero, y el resultado no
es ambiguo en ninguno de los dos casos.

Por que hacen falta las dos cosas a la vez
------------------------------------------
La identidad fija sin sesion conservada no guarda nada; la sesion conservada sin
identidad fija guarda para un cliente que no vuelve, porque el que reconecta
recibe otra identidad y es, para el intermediario, otro.

Y ninguna de las dos sirve si la **suscripcion** es de calidad cero: en cero no se
encola ni se reenvia nada. Los tres ajustes son un solo mecanismo.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

import paho.mqtt.client as mqtt  # noqa: E402

from backend import db  # noqa: E402
from backend.config import (  # noqa: E402
    MQTT_HOST,
    MQTT_PORT,
    MQTT_TOPIC,
)

METRICAS = RAIZ / "logs" / "consumidor_metricas.json"
INTERPRETE = RAIZ / ".venv" / "Scripts" / "python.exe"


def _mensaje(run_id: str, i: int) -> dict:
    """Un mensaje minimo que el modelo del consumidor acepte."""

    ahora = datetime.now(timezone.utc).isoformat()
    return {
        "timestamp": ahora,
        "vehicle_id": "prueba:sesion-persistente",
        "driver_id": "prueba:conductor",
        "session_id": f"prueba:sesion:{run_id}",
        "lap_id": None,
        "signal_name": "speed",
        "value": float(i),
        "unit": "km/h",
        "source_type": "can_simulated",
        "quality_flag": "ok",
        "metadata": {
            "can_id": None, "src": None,
            "reference_type": "prueba", "reference_id": run_id,
            "extra": {"replay_run_id": run_id, "replay_seq": i},
        },
    }


def _detener_consumidor() -> None:
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
         "Where-Object { $_.CommandLine -like '*run_mqtt_consumer*' } | "
         "ForEach-Object { taskkill /PID $_.ProcessId /T /F }"],
        capture_output=True, check=False)


def _levantar_consumidor() -> None:
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"Start-Process -FilePath '{INTERPRETE}' -ArgumentList "
         "'scripts/run_mqtt_consumer.py','--metrics-file',"
         "'logs/consumidor_metricas.json','--metrics-history-file',"
         f"'logs/consumidor_historial.jsonl' -WorkingDirectory '{RAIZ}' "
         "-WindowStyle Hidden"],
        capture_output=True, check=False)


def _consumidor_vivo() -> bool:
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "@(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
         "Where-Object { $_.CommandLine -like '*run_mqtt_consumer*' }).Count"],
        capture_output=True, text=True, check=False)
    return (r.stdout or "0").strip().isdigit() and int(r.stdout.strip()) > 0


def _esperar(condicion, limite_s: float, paso_s: float = 3.0) -> bool:
    inicio = time.perf_counter()
    while time.perf_counter() - inicio < limite_s:
        if condicion():
            return True
        time.sleep(paso_s)
    return False


def _contar(run_id: str) -> int:
    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        cursor.execute("select count(*) from telemetry_messages "
                       "where replay_run_id = %s", (run_id,))
        return cursor.fetchone()[0]


def _borrar(run_id: str) -> int:
    with db.obtener_conexion() as conexion:
        conexion.autocommit = True
        with conexion.cursor() as cursor:
            cursor.execute("delete from telemetry_messages "
                           "where replay_run_id = %s", (run_id,))
            return cursor.rowcount


def publicar(run_id: str, cantidad: int) -> int:
    """Publica con garantia de entrega y espera el acuse de cada mensaje."""

    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                          client_id=f"prueba-publicador-{run_id}")
    cliente.connect(MQTT_HOST, MQTT_PORT, 60)
    cliente.loop_start()
    acusados = 0
    try:
        for i in range(cantidad):
            info = cliente.publish(MQTT_TOPIC, json.dumps(_mensaje(run_id, i)),
                                   qos=1)
            # Se espera el acuse de cada uno: publicar sin esperar dejaria en
            # duda si el intermediario los recibio, y la prueba dejaria de
            # distinguir «no se encolo» de «no se publico».
            info.wait_for_publish(timeout=10)
            if info.is_published():
                acusados += 1
    finally:
        cliente.loop_stop()
        cliente.disconnect()
    return acusados


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cantidad", type=int, default=500)
    ap.add_argument("--conservar", action="store_true",
                    help="No borra las filas de la prueba al terminar.")
    ap.add_argument("--salida", type=Path,
                    default=RAIZ / "logs" / "sesion_persistente.json")
    args = ap.parse_args()

    run_id = "sesion_persistente_" + datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%S")
    r: dict = {"run_id": run_id, "cantidad_pedida": args.cantidad}

    # Se **reinicia** y no se comprueba que este vivo. La diferencia importa: un
    # consumidor que ya estaba corriendo arrancó con la configuracion anterior, y
    # el intermediario registro su sesion con la identidad de entonces. La prueba
    # mediria si se conserva una sesion que nunca se registro con la
    # configuracion que se quiere probar, y daria perdida total sin que el
    # mecanismo tenga nada que ver.
    #
    # Es la misma condicion que ya costo una corrida al verificar el agrupamiento:
    # un proceso de larga vida ejecuta el codigo que habia cuando arranco.
    print("  1. reiniciando el consumidor para que registre su sesion")
    _detener_consumidor()
    _esperar(lambda: not _consumidor_vivo(), 60.0)
    time.sleep(3.0)
    _levantar_consumidor()
    if not _esperar(_consumidor_vivo, 60.0):
        raise SystemExit("el consumidor no arranco")
    # Se le da tiempo a conectar y suscribirse: es lo que hace que el
    # intermediario registre su sesion, y sin ese registro no hay nada que
    # conservar.
    time.sleep(12.0)

    print("  2. deteniendo el consumidor")
    _detener_consumidor()
    if not _esperar(lambda: not _consumidor_vivo(), 60.0):
        raise SystemExit("el consumidor no se detuvo")
    time.sleep(4.0)
    r["consumidor_detenido"] = True

    print(f"  3. publicando {args.cantidad} mensajes con el consumidor caido")
    r["acusados_por_el_intermediario"] = publicar(run_id, args.cantidad)
    print(f"     acusados por el intermediario: "
          f"{r['acusados_por_el_intermediario']}")

    print("  4. levantando el consumidor")
    _levantar_consumidor()
    if not _esperar(_consumidor_vivo, 60.0):
        raise SystemExit("el consumidor no volvio")

    # Los contadores del consumidor se leen **antes y despues**, porque contar
    # solo filas no distingue dos cosas muy distintas: que el intermediario no
    # haya encolado, y que haya encolado y el consumidor haya rechazado los
    # mensajes por validacion. La primera version de esta prueba informo perdida
    # total cuando los quinientos habian llegado y el rechazo era de la prueba,
    # que armaba un mensaje sin uno de los campos obligatorios.
    print("  5. esperando la entrega de lo encolado")
    _esperar(lambda: _contar(run_id) >= args.cantidad, 120.0)
    r["persistidos"] = _contar(run_id)
    r["faltantes"] = args.cantidad - r["persistidos"]
    metricas = {}
    try:
        metricas = json.loads(METRICAS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    r["recibidos_por_el_consumidor"] = metricas.get("received")
    r["rechazados_por_validacion"] = metricas.get("decode_errors")

    if not args.conservar:
        r["borradas"] = _borrar(run_id)
        r["restantes"] = _contar(run_id)

    args.salida.write_text(json.dumps(r, indent=1, ensure_ascii=False),
                           encoding="utf-8")
    print()
    print(f"  publicados con el consumidor caido : {args.cantidad}")
    print(f"  acusados por el intermediario      : "
          f"{r['acusados_por_el_intermediario']}")
    print(f"  persistidos al reconectar          : {r['persistidos']}")
    print(f"  faltantes                          : {r['faltantes']}")
    if "borradas" in r:
        print(f"  borradas {r['borradas']}, restantes {r['restantes']}")
    print()
    print(f"  recibidos por el consumidor        : "
          f"{r['recibidos_por_el_consumidor']}")
    print(f"  rechazados por validacion          : "
          f"{r['rechazados_por_validacion']}")
    print()
    if r["rechazados_por_validacion"]:
        print("  AVISO: hubo rechazos por validacion. La entrega puede haber "
              "funcionado y el problema estar en la forma del mensaje.")
    if r["faltantes"] == 0 and args.cantidad > 0:
        print("  LA SESION SE CONSERVA: nada de lo publicado durante la caida "
              "se perdio")
    else:
        print(f"  SE PERDIERON {r['faltantes']} de {args.cantidad}")
    print(f"  detalle en {args.salida}")
    return 0 if r["faltantes"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
