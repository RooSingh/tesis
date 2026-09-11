# -*- coding: utf-8 -*-
"""Mide la cadena completa bajo la carga de una parrilla de veinte vehiculos.

Que falta medir, y que no
-------------------------
Del adaptador ya se sabe que procesa 356.414 mensajes por segundo contra los
35.186 que la parrilla completa produce: **diez veces de margen**. El adaptador
es la parte rapida y la que menos preocupa.

Lo que no esta medido es todo lo que viene despues: **el intermediario, el
consumidor y la base** bajo esa carga.

El camino que recorre
---------------------
El reproductor de F1 25 **no publica al intermediario**: emite datagramas UDP,
como el juego. De modo que el camino es el completo y real:

    reproduccion UDP -> capturador -> adaptador -> intermediario -> consumidor -> base

Por eso hace falta un capturador propio para la prueba, en **otro puerto**: si se
reprodujera contra el de produccion, tomaria la reproduccion por una sesion real,
abriria un archivo de captura y mezclaria telemetria de prueba con la verdadera.

Por que las filas van marcadas
------------------------------
Las filas que esta prueba genera salen con el mismo `source_type` y el mismo
`session_id` que las de la carrera de verdad, porque **son** esa carrera
reproducida. Sin una identidad de reinyeccion no habria forma de separarlas
despues, y el indice unico de trazabilidad ---que es parcial y solo aplica
cuando esa columna no es nula--- tampoco protegeria contra una segunda corrida.

El capturador acepta `--run-id` justamente para esto, y esta prueba lo usa y
**borra sus filas al terminar**.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from backend import db  # noqa: E402

METRICAS = RAIZ / "logs" / "consumidor_metricas.json"
CAPTURA_POR_DEFECTO = (RAIZ / "datasets" / "f1_25" / "capturas"
                       / "20260904_2136_spa_carrera-2_dos-conductores.f1raw")
INTERVALO_MUESTREO_S = 5.0


def _leer_metricas() -> dict | None:
    try:
        return json.loads(METRICAS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class Muestreador(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True)
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
                })
            self._parar.wait(INTERVALO_MUESTREO_S)

    def detener(self) -> None:
        self._parar.set()


def _matar_arbol(proc: subprocess.Popen) -> None:
    """Termina el proceso **y sus hijos**.

    En Windows el lanzador del entorno virtual arranca un hijo con el
    interprete real, de modo que terminar solo el padre deja al hijo escuchando
    el puerto. Se comprobo por la via contraria: matar cuatro padres
    creyendolos duplicados bajo los ocho procesos de los servicios.

    EN LINUX NO HAY `taskkill`, Y ESTA MEDICION VIVE EN LA RASPBERRY. El guion
    se escribio en Windows y ahi se quedo: corrido en la maquina de despliegue
    fallaba con `FileNotFoundError: taskkill` **en la limpieza**, o sea despues
    de haber lanzado el capturador y el reproductor, que quedaban sueltos. Se
    usa el grupo de procesos, que es el equivalente de `/T` y no necesita un
    programa externo.
    """

    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       capture_output=True, check=False)
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()


def _contar(run_id: str) -> int:
    with db.obtener_conexion() as c:
        cur = c.cursor()
        cur.execute("select count(*) from telemetry_messages "
                    "where replay_run_id = %s", (run_id,))
        return cur.fetchone()[0]


def _comando_capturador(
    puerto: int,
    run_id: str,
    destino: Path,
    pilotos: str | None,
) -> list[str]:
    """Construye una captura de prueba aislada de la seleccion de produccion."""
    archivo_eleccion = destino / f".{run_id}.pilotos.json"
    comando = [
        sys.executable, "-u", "scripts/capturar_f1_25.py",
        "--puerto", str(puerto), "--run-id", run_id,
        "--parrilla-completa",
        "--archivo-eleccion", str(archivo_eleccion),
        "--destino", str(destino),
    ]
    if pilotos is not None:
        comando.extend(["--pilotos", pilotos])
    return comando


def correr(captura: Path, segundos: float, puerto: int, pilotos: str | None,
           borrar: bool) -> dict:
    marca = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    run_id = f"parrilla_completa_{marca}"
    destino = RAIZ / "logs" / "capturas_de_prueba"
    destino.mkdir(parents=True, exist_ok=True)

    r: dict = {"run_id": run_id, "captura": captura.name,
               "segundos_pedidos": segundos, "puerto": puerto}

    # EL PUERTO TIENE QUE ESTAR LIBRE, Y SI NO SE DICE.
    #
    # Una corrida anterior que murio en la limpieza dejo su capturador
    # escuchando este mismo puerto. La siguiente arranco igual, el capturador
    # viejo se quedo con los datagramas ---y con `--parrilla-completa`, que era
    # lo que aquella corrida pedia--- y el nuevo no recibio ninguno. El banco
    # informo "0 filas escritas" como si la cadena no hubiera entregado nada,
    # cuando lo que pasaba es que estaba midiendo a otro proceso. Ademas dejo
    # 1.455.855 filas en la base bajo la marca vieja.
    #
    # Un banco que mide sin saber a quien mide es peor que uno que no corre.
    sonda = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sonda.bind(("0.0.0.0", puerto))
    except OSError:
        raise SystemExit(
            f"El puerto {puerto} ya esta ocupado. Casi seguro es un capturador "
            "de una corrida anterior que no se limpio: buscalo con\n"
            "  ps -eo pid,cmd | grep capturar_f1_25\n"
            "y terminalo antes de repetir. Sus filas quedan en la base bajo su "
            "propia marca `parrilla_completa_*` y se borran por ahi.")
    finally:
        sonda.close()

    print(f"  capturador de prueba en el puerto {puerto}, marca {run_id}",
          flush=True)
    capturador = subprocess.Popen(
        _comando_capturador(puerto, run_id, destino, pilotos),
        cwd=str(RAIZ), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=(os.name != "nt"))
    # El capturador tarda un instante en atarse al puerto. Emitir antes de que
    # escuche perderia los primeros datagramas sin avisar.
    time.sleep(4)

    muestreador = Muestreador()
    muestreador.start()
    antes = _contar(run_id)

    print(f"  reproduciendo {segundos:.0f} s a velocidad real...", flush=True)
    reproductor = subprocess.Popen(
        [sys.executable, "-u", "scripts/reproducir_captura_f1_25.py",
         str(captura), "--puerto", str(puerto), "--velocidad", "1"],
        cwd=str(RAIZ), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=(os.name != "nt"))
    t0 = time.perf_counter()
    time.sleep(segundos)
    r["duracion_real_s"] = round(time.perf_counter() - t0, 1)
    _matar_arbol(reproductor)

    # El consumidor puede seguir drenando despues de que la emision paro, y ese
    # drenaje es parte de la respuesta: cortar en seco mostraria un atraso que
    # en realidad se resolvia.
    print("  esperando el drenaje...", flush=True)
    time.sleep(30)
    _matar_arbol(capturador)
    time.sleep(5)
    muestreador.detener()
    muestreador.join(timeout=10)

    r["filas_escritas"] = _contar(run_id) - antes
    r["muestras"] = muestreador.muestras

    if borrar:
        print("  borrando las filas de la prueba...", flush=True)
        with db.obtener_conexion() as c:
            c.autocommit = True
            cur = c.cursor()
            cur.execute("delete from telemetry_messages "
                        "where replay_run_id = %s", (run_id,))
            r["filas_borradas"] = cur.rowcount
        # Se cuenta despues de borrar, contra el total esperado, y no se da por
        # hecho que el borrado alcanzo lo que debia.
        r["filas_restantes"] = _contar(run_id)
    return r


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--captura", type=Path, default=CAPTURA_POR_DEFECTO)
    ap.add_argument("--segundos", type=float, default=180.0)
    ap.add_argument("--pilotos", default=None,
                    help="Nombres separados por coma. Mide el coche propio "
                         "mas esos, que es la carga real; sin esto mide la "
                         "parrilla entera, que es el techo que no entra.")
    ap.add_argument("--puerto", type=int, default=20778)
    ap.add_argument("--conservar", action="store_true",
                    help="No borra las filas de la prueba al terminar.")
    ap.add_argument("--salida", type=Path,
                    default=RAIZ / "logs" / "cadena_parrilla_completa.json")
    args = ap.parse_args()

    if not args.captura.exists():
        raise SystemExit(f"no existe {args.captura}")

    r = correr(args.captura, args.segundos, args.puerto, args.pilotos,
               not args.conservar)
    args.salida.write_text(json.dumps(r, indent=2, ensure_ascii=False),
                           encoding="utf-8")

    ms = [m for m in r["muestras"] if m["pendientes"] is not None]
    print()
    print(f"  filas escritas: {r['filas_escritas']:,} en "
          f"{r['duracion_real_s']} s  -> "
          f"{r['filas_escritas'] / max(r['duracion_real_s'], 1):,.0f} filas/s")
    if ms:
        pend = [m["pendientes"] for m in ms]
        desc = [m["descartados_por_broker"] or 0 for m in ms]
        esp = [m["esperas_por_contrapresion"] or 0 for m in ms]
        print(f"  pendientes: minimo {min(pend)}  maximo {max(pend)}  "
              f"ultimo {pend[-1]}")
        print(f"  descartes del intermediario durante la prueba: "
              f"{max(desc) - min(desc)}")
        print(f"  esperas por contrapresion: {max(esp) - min(esp)}")
    if "filas_borradas" in r:
        print(f"  borradas: {r['filas_borradas']:,}   "
              f"restantes: {r['filas_restantes']}")
    print(f"  detalle en {args.salida}")


if __name__ == "__main__":
    main()
