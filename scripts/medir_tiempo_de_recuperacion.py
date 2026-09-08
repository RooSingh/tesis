# -*- coding: utf-8 -*-
"""Mide cuanto tarda el sistema en recuperarse de un corte del consumidor.

Que metrica es esta
-------------------
El anexo adopta `recovery time` entre las metricas de robustez. Que el sistema se
recupere ya estaba demostrado ---la sesion conservada y la confirmacion manual no
pierden nada--- pero **cuanto tarda no estaba medido**, y son dos preguntas
distintas.

Tres tramos, y hay que separarlos
---------------------------------
«Recuperado» no es un solo instante, porque el servicio y el dato se recuperan en
momentos distintos:

``arranque``
    desde que el proceso muere hasta que hay un proceso vivo otra vez.
``reconexion``
    desde que el proceso vive hasta que el intermediario lo reconoce y le entrega.
    Antes de esto el proceso esta arriba y no sirve para nada.
``drenaje``
    desde la primera entrega hasta que la cola acumulada durante el corte quedo
    escrita. Es lo que tarda el **dato** en ponerse al dia, y depende de cuanto se
    acumulo.

Informar solo el primero diria que el sistema se recupera en segundos cuando el
dato puede tardar minutos. Informar solo el ultimo escondería que el arranque es
inmediato. Se informan los tres.

Por que el drenaje se mide contra la base
-----------------------------------------
No contra los contadores del consumidor, que se reinician con el proceso. La unica
medida que sobrevive al corte es contar filas.
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


def _mensaje(run_id: str, i: int) -> dict:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "vehicle_id": "prueba:recuperacion", "driver_id": "d",
        "session_id": f"prueba:sesion:{run_id}", "lap_id": None,
        "signal_name": "speed", "value": float(i), "unit": "km/h",
        "source_type": "can_simulated", "quality_flag": "ok",
        "metadata": {"can_id": None, "src": None, "reference_type": "p",
                     "reference_id": run_id,
                     "extra": {"replay_run_id": run_id, "replay_seq": i}},
    }


def medir(cantidad: int) -> dict:
    run_id = "recuperacion_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")

    print("  preparando: el consumidor arranca y registra su sesion")
    _detener()
    while _vivo():
        time.sleep(1.0)
    _levantar()
    while not _vivo():
        time.sleep(1.0)
    time.sleep(10.0)

    print("  cortando el consumidor")
    t_corte = time.perf_counter()
    _detener()
    while _vivo():
        time.sleep(0.2)

    print(f"  publicando {cantidad} mensajes durante el corte")
    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                          client_id=f"prueba-recup-{run_id}")
    cliente.connect(MQTT_HOST, MQTT_PORT, 60)
    cliente.loop_start()
    ultimo = None
    encolados = 0
    for i in range(cantidad):
        info = cliente.publish(MQTT_TOPIC, json.dumps(_mensaje(run_id, i)), qos=1)
        if info.rc == 0:
            encolados += 1
            ultimo = info
    if ultimo is not None:
        ultimo.wait_for_publish(timeout=60)
    cliente.loop_stop()
    cliente.disconnect()

    print("  levantando el consumidor y cronometrando")
    t_levantar = time.perf_counter()
    _levantar()
    while not _vivo():
        time.sleep(0.2)
    t_arriba = time.perf_counter()

    # Primera entrega: la primera fila escrita de esta corrida. Es lo que marca
    # que el intermediario reconocio al cliente y empezo a entregarle.
    t_primera = None
    while time.perf_counter() - t_arriba < 180.0:
        if _contar(run_id) > 0:
            t_primera = time.perf_counter()
            break
        time.sleep(0.2)

    t_completo = None
    while time.perf_counter() - t_arriba < 300.0:
        if _contar(run_id) >= encolados:
            t_completo = time.perf_counter()
            break
        time.sleep(0.5)

    escritas = _contar(run_id)
    borradas = _borrar(run_id)

    return {
        "run_id": run_id,
        "publicados": encolados,
        "escritas": escritas,
        "faltantes": encolados - escritas,
        "borradas": borradas,
        # El arranque se mide desde que se pide levantar, no desde el corte: el
        # corte lo provoca esta prueba y su duracion es artificial.
        "arranque_s": round(t_arriba - t_levantar, 2),
        "reconexion_s": (round(t_primera - t_arriba, 2)
                         if t_primera else None),
        "drenaje_s": (round(t_completo - t_primera, 2)
                      if t_completo and t_primera else None),
        "total_s": (round(t_completo - t_levantar, 2) if t_completo else None),
        "duracion_del_corte_s": round(t_levantar - t_corte, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cantidad", type=int, default=5000)
    ap.add_argument("--salida", type=Path,
                    default=RAIZ / "logs" / "tiempo_de_recuperacion.json")
    args = ap.parse_args()

    r = medir(args.cantidad)
    args.salida.write_text(json.dumps(r, indent=1, ensure_ascii=False),
                           encoding="utf-8")

    print()
    print(f"  acumulado durante el corte : {r['publicados']:,} mensajes")
    print(f"  duracion del corte         : {r['duracion_del_corte_s']} s")
    print()
    print(f"  arranque del proceso       : {r['arranque_s']} s")
    print(f"  hasta la primera entrega   : {r['reconexion_s']} s")
    print(f"  drenaje de lo acumulado    : {r['drenaje_s']} s")
    print(f"  TOTAL hasta ponerse al dia : {r['total_s']} s")
    print()
    print(f"  escritas {r['escritas']:,} de {r['publicados']:,}, "
          f"faltantes {r['faltantes']}")
    if r["drenaje_s"] and r["publicados"]:
        print(f"  ritmo de puesta al dia     : "
              f"{r['publicados'] / r['drenaje_s']:,.0f} mensajes/s")
    print(f"  detalle en {args.salida}")
    return 0 if r["faltantes"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
