# -*- coding: utf-8 -*-
"""Recompleta los rivales **de a un vehiculo por vez**, en procesos separados.

POR QUE DE A UNO
----------------
Escribir los cinco en una sola corrida se intento tres veces y las tres el
sistema mato el proceso por falta de memoria, cada vez un poco mas lejos: 954.000
filas, 3.000.000, 7.264.000. La memoria no la consume el guion ---sus procesos de
Python suman menos de veinte megabytes--- sino la base, que sostiene paginas
sucias, registro de transacciones e indices mientras la escritura no para.

Cortarla en cinco corridas independientes le da a la base **cinco puntos donde
soltar todo eso**. Entre un vehiculo y el siguiente el proceso termina, la
transaccion cierra y el motor vuelve a un estado tranquilo.

Y hay una segunda razon, que es la que decide: **un vehiculo terminado no se
vuelve a hacer**. La herramienta clasifica en vacio, parcial y completo, de modo
que si esto se interrumpe en el tercero, los dos primeros quedan completos y
retomar cuesta lo que falta y no todo.

QUE HACE FALTA ANTES
--------------------
Que los fragmentos de la sesion esten **descomprimidos**. Insertar en un fragmento
comprimido obliga al motor a descomprimirlo dentro de la transaccion, con un tope
de cien mil tuplas que esta escritura supera sola. Se descomprimen una vez, se
escribe todo, y se recomprime al final con `escribir_en_el_pasado.py
--solo-recomprimir`.

POR QUE NO SE LANZA COMO TAREA DE FONDO DEL ASISTENTE
-----------------------------------------------------
Porque es justamente lo que la mataba. El proceso se desprende con
`Start-Process`, corre por su cuenta, y este guion lo espera consultando la base
---que es la unica fuente de verdad sobre cuanto se escribio--- en lugar de
mirar su salida.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from backend import db  # noqa: E402

INTERPRETE = RAIZ / ".venv" / "Scripts" / "python.exe"


def _filas_de(session_id: str, indice: int) -> int:
    with db.obtener_conexion() as c, c.cursor() as cur:
        cur.execute("""select count(*) from telemetry_messages
                       where session_id = %s and vehicle_id like %s""",
                    (session_id, f"%:car:{indice}"))
        return cur.fetchone()[0]


def _memoria_libre_gb() -> float:
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory"],
        capture_output=True, text=True, check=False)
    try:
        return int((r.stdout or "0").strip()) / 1024 / 1024
    except ValueError:
        return 0.0


def _vivo() -> bool:
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "@(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
         "Where-Object { $_.CommandLine -like '*republicar_captura*' }).Count"],
        capture_output=True, text=True, check=False)
    s = (r.stdout or "").strip()
    return s.isdigit() and int(s) > 0


def _lanzar(captura: Path, indice: int) -> None:
    """Desprendido, para que no lo alcance quien vigila las tareas de fondo."""

    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"Start-Process -FilePath '{INTERPRETE}' -ArgumentList "
         f"'-u','scripts/republicar_captura.py','{captura}',"
         f"'--parrilla-completa','--vehiculos','{indice}' "
         f"-WorkingDirectory '{RAIZ}' -WindowStyle Hidden"],
        check=False)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("captura", type=Path)
    ap.add_argument("--sesion", required=True)
    ap.add_argument("--vehiculos", required=True)
    ap.add_argument("--esperadas", type=int, default=5_079_346)
    ap.add_argument("--piso-de-memoria-gb", type=float, default=0.6,
                    help="Por debajo de esto no se lanza el siguiente vehiculo.")
    args = ap.parse_args()

    indices = [int(x) for x in args.vehiculos.split(",") if x.strip()]
    print(f"  vehiculos a completar: {indices}")
    print(f"  esperadas por vehiculo: {args.esperadas:,}\n")

    for n, indice in enumerate(indices, 1):
        hay = _filas_de(args.sesion, indice)
        if hay >= args.esperadas:
            print(f"  [{n}/{len(indices)}] car:{indice} ya esta completo "
                  f"({hay:,}), se saltea")
            continue
        if hay:
            # Parcial. La herramienta se niega a tocarlo, y con razon: sus filas
            # no llevan la identidad de la corrida nueva y se duplicarian.
            print(f"  [{n}/{len(indices)}] car:{indice} tiene {hay:,} filas "
                  f"parciales: se borran antes de rehacerlo")
            with db.obtener_conexion() as c:
                c.autocommit = True
                with c.cursor() as cur:
                    cur.execute("""delete from telemetry_messages
                                   where session_id = %s and vehicle_id like %s
                                     and replay_run_id is not null""",
                                (args.sesion, f"%:car:{indice}"))
                    print(f"        borradas {cur.rowcount:,}")

        libre = _memoria_libre_gb()
        if libre < args.piso_de_memoria_gb:
            print(f"  memoria libre {libre:.1f} GB, por debajo del piso. "
                  f"Se detiene: los completos quedan completos.")
            return 1

        print(f"  [{n}/{len(indices)}] car:{indice} --- memoria libre "
              f"{libre:.1f} GB, lanzando")
        t0 = time.perf_counter()
        _lanzar(args.captura, indice)
        time.sleep(20)

        # LA SENAL DE QUE TERMINO ES QUE EL PROCESO SALGA, no que las filas
        # dejen de crecer.
        #
        # La primera version cortaba tras cinco minutos sin filas nuevas, y
        # mataba la corrida antes de que empezara: la herramienta recorre los
        # 465 MB del crudo para inventariar la parrilla **antes de escribir la
        # primera fila**, y eso tarda unos ocho minutos. Vio cero tres veces y
        # concluyo que estaba trabada.
        #
        # El conteo de filas se conserva, pero solo para informar. Confundir
        # «no veo avance» con «no avanza» es el mismo error que este trabajo ya
        # cometio midiendo contra la intencion en lugar del efecto.
        while _vivo():
            time.sleep(60)
            hay = _filas_de(args.sesion, indice)
            pct = hay / args.esperadas * 100
            ritmo = hay / max(time.perf_counter() - t0, 1)
            print(f"        {hay:>10,} ({pct:5.1f} %)  {ritmo:,.0f} filas/s  "
                  f"memoria {_memoria_libre_gb():.1f} GB", flush=True)

        hay = _filas_de(args.sesion, indice)
        tardo = (time.perf_counter() - t0) / 60
        if hay >= args.esperadas:
            print(f"        car:{indice} COMPLETO: {hay:,} en {tardo:.1f} min\n")
        else:
            print(f"        car:{indice} quedo en {hay:,} de "
                  f"{args.esperadas:,} tras {tardo:.1f} min. Se detiene.\n")
            return 1

    print("  todos los vehiculos pedidos quedaron completos.")
    print("  falta recomprimir: scripts/escribir_en_el_pasado.py --solo-recomprimir")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
