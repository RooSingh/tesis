# -*- coding: utf-8 -*-
"""Mata el consumidor con la cola llena y verifica que nada se pierda.

Que se prueba
-------------
Con la confirmacion automatica de la biblioteca, el acuse sale al volver del
callback: el mensaje queda **confirmado y sin escribir** mientras espera en la
cola de memoria. Si el proceso muere ahi, el intermediario no lo reenvia porque ya
lo dio por entregado, y la perdida no queda registrada en ninguna parte.

Con la confirmacion manual el acuse sale tras el `insert`. Un mensaje muerto en la
cola nunca fue confirmado, de modo que el intermediario lo reenvia al reconectar.

Como se provoca
---------------
    1. reiniciar el consumidor, para que arranque con la configuracion vigente;
    2. publicar una rafaga con garantia de entrega, sin esperar acuses;
    3. **matar el proceso de inmediato**, antes de que el vencimiento del lote
       haya podido descargar la cola;
    4. levantarlo y contar.

El paso tres es el que hace la prueba. Esperar aunque sea medio segundo dejaria
que el lote se escriba y la prueba no probaria nada: mediria el camino feliz.

Por que la comparacion es contra lo publicado
---------------------------------------------
No contra lo que el consumidor diga haber recibido. Sus contadores se reinician
con el proceso, y ademas el punto de la prueba es justamente que **lo que el
consumidor creia haber resuelto podia no estar escrito**. La unica medida que vale
es contar filas en la base.
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
from backend.config import MQTT_HOST, MQTT_PORT, MQTT_TOPIC  # noqa: E402

INTERPRETE = RAIZ / ".venv" / "Scripts" / "python.exe"
METRICAS = RAIZ / "logs" / "consumidor_metricas.json"


def _mensaje(run_id: str, i: int) -> dict:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "vehicle_id": "prueba:confirmacion-manual",
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


def _ps(comando: str) -> str:
    r = subprocess.run(["powershell", "-NoProfile", "-Command", comando],
                       capture_output=True, text=True, check=False)
    return (r.stdout or "").strip()


def _detener() -> None:
    _ps("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Where-Object { $_.CommandLine -like '*run_mqtt_consumer*' } | "
        "ForEach-Object { taskkill /PID $_.ProcessId /T /F }")


def _levantar() -> None:
    _ps(f"Start-Process -FilePath '{INTERPRETE}' -ArgumentList "
        "'scripts/run_mqtt_consumer.py','--metrics-file',"
        "'logs/consumidor_metricas.json','--metrics-history-file',"
        f"'logs/consumidor_historial.jsonl' -WorkingDirectory '{RAIZ}' "
        "-WindowStyle Hidden")


def _vivo() -> bool:
    s = _ps("@(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
            "Where-Object { $_.CommandLine -like '*run_mqtt_consumer*' }).Count")
    return s.isdigit() and int(s) > 0


def _esperar(cond, limite_s: float, paso: float = 2.0) -> bool:
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < limite_s:
        if cond():
            return True
        time.sleep(paso)
    return False


def _contar(run_id: str) -> int:
    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        cursor.execute("select count(*) from telemetry_messages "
                       "where replay_run_id = %s", (run_id,))
        return cursor.fetchone()[0]


def _contar_distintos(run_id: str) -> int:
    """Cuantas secuencias distintas hay. Distingue reenvio de duplicado."""

    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        cursor.execute("select count(distinct replay_seq) from telemetry_messages "
                       "where replay_run_id = %s", (run_id,))
        return cursor.fetchone()[0]


def _borrar(run_id: str) -> int:
    with db.obtener_conexion() as conexion:
        conexion.autocommit = True
        with conexion.cursor() as cursor:
            cursor.execute("delete from telemetry_messages "
                           "where replay_run_id = %s", (run_id,))
            return cursor.rowcount


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cantidad", type=int, default=3000)
    ap.add_argument("--matar-tras-ms", type=float, default=120.0,
                    help="cuanto se espera antes de matar; debe ser menor que el "
                         "vencimiento del lote")
    ap.add_argument("--conservar", action="store_true")
    ap.add_argument("--salida", type=Path,
                    default=RAIZ / "logs" / "confirmacion_manual.json")
    args = ap.parse_args()

    run_id = "confirmacion_manual_" + datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%S")
    r: dict = {"run_id": run_id, "cantidad": args.cantidad,
               "matar_tras_ms": args.matar_tras_ms}

    print("  1. reiniciando el consumidor")
    _detener()
    _esperar(lambda: not _vivo(), 60.0)
    time.sleep(2.0)
    _levantar()
    if not _esperar(_vivo, 60.0):
        raise SystemExit("el consumidor no arranco")
    time.sleep(10.0)

    print(f"  2. publicando {args.cantidad} en rafaga")
    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                          client_id=f"prueba-pub-{run_id}")
    cliente.connect(MQTT_HOST, MQTT_PORT, 60)
    cliente.loop_start()
    ultimo = None
    encolados = 0
    rechazados: dict[int, int] = {}
    for i in range(args.cantidad):
        info = cliente.publish(MQTT_TOPIC, json.dumps(_mensaje(run_id, i)),
                               qos=1)
        # **Se mira el codigo de retorno de cada publicacion.** La primera
        # version de esta prueba no lo hacia y declaro perdidos 1.697 mensajes
        # que nunca habian salido: la cola de salida del publicador los habia
        # rechazado en silencio. Es el mismo defecto que la prueba D encontro en
        # el capturador, cometido aca al escribir la prueba.
        if info.rc == 0:
            encolados += 1
            ultimo = info
        else:
            rechazados[info.rc] = rechazados.get(info.rc, 0) + 1
    if ultimo is not None:
        ultimo.wait_for_publish(timeout=30)
    r["publicados"] = encolados
    r["rechazados_por_el_publicador"] = rechazados
    if rechazados:
        print(f"     el publicador rechazo {sum(rechazados.values())}: "
              f"{rechazados}")
    print(f"     encolados de verdad: {encolados}")

    print(f"  3. matando el consumidor tras {args.matar_tras_ms:.0f} ms")
    time.sleep(args.matar_tras_ms / 1000.0)
    escritas_antes = _contar(run_id)
    _detener()
    _esperar(lambda: not _vivo(), 60.0)
    r["escritas_antes_de_matar"] = escritas_antes
    print(f"     ya estaban escritas: {escritas_antes}")
    cliente.loop_stop()
    cliente.disconnect()

    print("  4. levantando el consumidor")
    time.sleep(3.0)
    _levantar()
    if not _esperar(_vivo, 60.0):
        raise SystemExit("el consumidor no volvio")

    print("  5. esperando el reenvio")
    _esperar(lambda: _contar_distintos(run_id) >= r["publicados"], 180.0)
    r["filas"] = _contar(run_id)
    r["distintas"] = _contar_distintos(run_id)
    r["faltantes"] = r["publicados"] - r["distintas"]
    r["duplicadas"] = r["filas"] - r["distintas"]

    if not args.conservar:
        r["borradas"] = _borrar(run_id)

    args.salida.write_text(json.dumps(r, indent=1, ensure_ascii=False),
                           encoding="utf-8")
    print()
    print(f"  pedidos                       : {args.cantidad}")
    print(f"  encolados por el publicador   : {r['publicados']}")
    print(f"  escritas antes de matar       : {escritas_antes}")
    print(f"  senales distintas al final    : {r['distintas']}")
    print(f"  faltantes                     : {r['faltantes']}")
    print(f"  filas duplicadas              : {r['duplicadas']}")
    if "borradas" in r:
        print(f"  borradas                      : {r['borradas']}")
    print()
    if r["faltantes"] == 0:
        recuperadas = r["distintas"] - escritas_antes
        print(f"  NADA SE PERDIO. El intermediario reenvio {recuperadas} "
              "mensajes que estaban en la cola al morir el proceso.")
    else:
        print(f"  SE PERDIERON {r['faltantes']} de {r['publicados']}")
    return 0 if r["faltantes"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
