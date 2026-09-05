# -*- coding: utf-8 -*-
"""Corre varias cargas de telemetria OpenF1 una detras de otra, sin supervision.

Por que en serie y no en paralelo
---------------------------------
Todas las cargas pasan por el mismo intermediario y la misma base. Correr dos a
la vez no las acelera ---el cuello es la persistencia--- y si multiplica el
riesgo: el escenario de concurrencia del capitulo de pruebas midio un 22,02 % de
perdida al aumentar los mensajes en vuelo. Este guion existe para que la cola
avance sola sin pagar ese riesgo.

Por que es seguro dejarlo solo
------------------------------
Cada carga se lanza con reconciliacion obligatoria y punto de control. Si el
proceso muere, la siguiente ejecucion retoma donde iba en lugar de empezar de
nuevo o de duplicar: la reanudacion se apoya en el numero de secuencia que el
flujo preparado asigna de antemano.

Uso
---
    python scripts/encolar_cargas_openf1.py

Cada entrada de la cola declara que carga es y cuantos mensajes espera, de modo
que el registro dice en todo momento por donde va.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

PYTHON = sys.executable
REPLAY = RAIZ / "scripts" / "replay_openf1.py"

#: Cuanto se espera entre revisiones de la carga que esta en curso.
ESPERA_S = 30.0


def _terminada(checkpoint: Path, esperados: int) -> bool:
    """Una carga esta terminada cuando su punto de control llego al total."""

    checkpoint = RAIZ / checkpoint if not checkpoint.is_absolute() else checkpoint
    if not checkpoint.is_file():
        return False
    try:
        estado = json.loads(checkpoint.read_text(encoding="utf-8"))
    except Exception:
        return False
    return int(estado.get("next_seq") or 0) >= esperados


def esperar(nombre: str, checkpoint: Path, esperados: int) -> None:
    """Bloquea hasta que la carga en curso alcance su total."""

    while not _terminada(checkpoint, esperados):
        try:
            estado = json.loads(checkpoint.read_text(encoding="utf-8"))
            hechos = int(estado.get("next_seq") or 0)
        except Exception:
            hechos = 0
        print(f"[cola] esperando a {nombre}: {hechos:,} de {esperados:,}",
              flush=True)
        time.sleep(ESPERA_S)
    print(f"[cola] {nombre} terminada", flush=True)


#: Cuantas veces se reintenta una carga que no concilia antes de rendirse.
#:
#: Una carga larga se corta por perdida en rafaga del intermediario, no por un
#: defecto del dato: en la carga de Spa se perdieron quince mensajes de diez mil
#: en el bloque dos millones cincuenta mil. El replay hace lo correcto al fallar
#: ---confirmar no es persistir, y por eso reconcilia--- pero rendirse ahi
#: desperdicia el trabajo hecho: al reanudar, el bloque se republica y suele
#: conciliar. Antes la cola pasaba a la carga siguiente y dejaba la anterior a
#: medias sin decir que faltaba terminarla.
REINTENTOS = 20


def cargar(nombre: str, sesion: int, pilotos: str, punto: str,
           flujo: Path, checkpoint: Path, run_id: str, esperados: int) -> bool:
    """Lanza una carga, reintentando mientras avance, y dice si concilio."""

    for intento in range(1, REINTENTOS + 1):
        if _terminada(checkpoint, esperados):
            print(f"[cola] {nombre}: completa", flush=True)
            return True
        antes = _avance(checkpoint)
        _lanzar(nombre, sesion, pilotos, punto, flujo, checkpoint, run_id,
                esperados, intento)
        despues = _avance(checkpoint)
        if despues <= antes and not _terminada(checkpoint, esperados):
            # No avanzo ni un bloque: reintentar otra vez daria lo mismo.
            print(f"[cola] {nombre}: no avanza, se abandona en {despues:,}",
                  flush=True)
            return False
    print(f"[cola] {nombre}: agotados los {REINTENTOS} reintentos", flush=True)
    return _terminada(checkpoint, esperados)


def _avance(checkpoint: Path) -> int:
    """Hasta que numero de secuencia llego una carga."""

    checkpoint = RAIZ / checkpoint if not checkpoint.is_absolute() else checkpoint
    if not checkpoint.is_file():
        return 0
    try:
        return int(json.loads(checkpoint.read_text(encoding="utf-8"))
                   .get("next_seq") or 0)
    except Exception:
        return 0


def _lanzar(nombre: str, sesion: int, pilotos: str, punto: str,
            flujo: Path, checkpoint: Path, run_id: str, esperados: int,
            intento: int) -> bool:
    """Una ejecucion del replay, reanudando donde haya quedado."""

    print(f"[cola] {nombre}: intento {intento}, desde {_avance(checkpoint):,}"
          f" de {esperados:,}", flush=True)
    resultado = subprocess.run(
        [PYTHON, str(REPLAY),
         "--session-key", str(sesion),
         "--drivers", pilotos,
         "--endpoints", punto,
         "--replay-run-id", run_id,
         "--publish", "--confirm-publish", "REPLAY_OPENF1",
         "--stream-file", str(flujo),
         "--checkpoint-file", str(checkpoint),
         "--max-inflight-messages", "1",
         "--block-size", "10000",
         "--reconcile", "--resume"],
        cwd=str(RAIZ),
    )
    ok = resultado.returncode == 0
    if not ok:
        print(f"[cola] {nombre}: bloque sin conciliar, se reintenta desde el"
              f" punto de control", flush=True)
    return ok


def main() -> None:
    # Rutas **relativas a la raiz**, no absolutas.
    #
    # El replay guarda en el punto de control la ruta del flujo tal como se la
    # paso, y se niega a reanudar si la ruta solicitada no coincide. Es una
    # salvaguarda correcta ---evita reanudar un punto de control sobre otro
    # flujo--- pero significa que la forma de la ruta es parte de la identidad.
    # Como las cargas originales se lanzaron con rutas relativas, aca se usan
    # relativas: pasar la absoluta de la misma carpeta rompia la reanudacion.
    crudo = Path("datasets") / "OpenF1" / "raw" / "2025"

    # Spa va como primera entrada de la cola y no como espera.
    #
    # La version anterior esperaba a que otro proceso la terminara. Cuando ese
    # proceso murio ---y en esta maquina los procesos de fondo mueren--- la cola
    # quedo esperando a alguien que ya no existia, sin avanzar y sin decirlo.
    # Lanzarla desde aca la vuelve reanudable como las demas: si ya esta
    # completa se saltea, y si esta a medias retoma en su punto de control.
    cola = [
        ("Spa, veinte pilotos", 9939, "all", "car_data",
         crudo / "9939" / "stream_car_data.jsonl",
         crudo / "9939" / "checkpoint_car_data.json",
         "spa_20pilotos_20260902", 5_783_760),
        ("Red Bull Ring, quince pilotos restantes", 9955,
         "1,5,6,10,12,14,18,22,23,27,30,31,55,63,87", "car_data",
         crudo / "9955" / "stream_15restantes.jsonl",
         crudo / "9955" / "checkpoint_15restantes.json",
         "spielberg_15restantes_20260902", 3_213_540),
        ("Red Bull Ring, posicion de los veinte", 9955,
         "all", "location",
         crudo / "9955" / "stream_location.jsonl",
         crudo / "9955" / "checkpoint_location.json",
         "spielberg_location_20260902", 2_192_520),
    ]

    for nombre, sesion, pilotos, punto, flujo, checkpoint, run_id, esperados in cola:
        if not (RAIZ / flujo).is_file():
            print(f"[cola] {nombre}: falta el flujo preparado, se saltea",
                  flush=True)
            continue
        cargar(nombre, sesion, pilotos, punto, flujo, checkpoint, run_id, esperados)

    print("[cola] terminada", flush=True)


if __name__ == "__main__":
    main()
