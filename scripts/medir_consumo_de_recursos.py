# -*- coding: utf-8 -*-
"""Mide cuanto procesador, memoria y red consume la cadena bajo carga.

QUE METRICA ES ESTA, Y POR QUE FALTABA
--------------------------------------
El anexo adopta el consumo de recursos entre las metricas de rendimiento, y es
**la unica sin ninguna medicion en todo el trabajo**. Caudal, concurrencia,
durabilidad y tiempo de recuperacion estan medidos; la latencia extremo a extremo
esta medida en parte y declarada como tal. Del procesador, de la memoria y de la
red no habia una sola cifra.

No es solo tapar un hueco del anexo. El capitulo de despliegue fundamenta que el
sistema va sobre un computador de placa unica en la red de la fuente, con ocho
gigabytes y cuatro nucleos. **Esa afirmacion se hizo sin medir lo que el sistema
consume**, y sin medirlo no se puede sostener ni desmentir.

QUE SE MIDE Y QUE NO
--------------------
Se miden los procesos y contenedores que **estarian en el equipo de destino**:

    capturador -> intermediario -> consumidor -> base

y ademas el servidor de la interfaz, porque tambien corre alli.

**No se cuenta el reproductor.** Emite los datagramas que en operacion emite el
juego, y el juego no corre en el equipo de destino: cargarlo en la cuenta
inflaria el consumo con un proceso que alli no existe. Se lo mide igual y se lo
informa aparte, porque su costo dice cuanto del procesador de esta maquina estaba
ocupado en algo ajeno mientras se median los demas.

QUE MEMORIA SE INFORMA
----------------------
Windows ofrece tres cifras distintas para el mismo proceso, y eligen respuestas
distintas. Medido sobre el consumidor en reposo: memoria residente 13 MB, privada
comprometida 30,4 y residente no compartible 2,5.

Se informa **la residente**, que es la que responde la pregunta que motiva esta
medicion: cuanta memoria fisica ocupa el sistema en la maquina donde corre. La no
compartible descuenta las paginas del interprete y de las bibliotecas, que en el
equipo de destino tambien hay que tener; informarla haria parecer que el consumidor
entra en dos megabytes y medio. La privada comprometida se informa aparte, porque
un pico de reserva que no llega a residir igual tiene que caber.

Cada pieza aparece con **dos procesos** y no es un error de conteo: el ejecutable
del entorno virtual es un lanzador que vuelve a ejecutar el interprete real como
hijo suyo. Los dos existen y los dos ocupan memoria, de modo que se suman.

LA UNIDAD ES EL NUCLEO, NO EL PORCENTAJE
----------------------------------------
Windows informa el uso de procesador de un proceso como porcentaje **de un
nucleo**, de modo que en una maquina de dieciseis nucleos logicos un proceso puede
declarar 160 %. Docker informa el suyo contra los nucleos que el contenedor ve.
Los dos porcentajes miden lo mismo con denominadores distintos, y compararlos
tal cual llevaria a sumar peras con manzanas.

De ahi que todo se informe en **nucleos ocupados** ---el porcentaje dividido por
cien---, que es la unidad que se traslada a otra maquina: 0,8 nucleos aca son 0,8
nucleos alla, y en un equipo de cuatro nucleos eso es la quinta parte.

POR QUE HAY UNA LINEA DE BASE
-----------------------------
Sin medir la maquina en reposo, el consumo del sistema operativo y de lo que ya
estaba corriendo se le atribuye a la cadena. Se mide antes, durante y despues, y
lo que se informa como costo de la carga es **la diferencia**.

Uso:
    .venv/Scripts/python.exe scripts/medir_consumo_de_recursos.py
    .venv/Scripts/python.exe scripts/medir_consumo_de_recursos.py --segundos 60
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

#: Como se reconoce cada pieza por su linea de comando, y si cuenta o no.
#:
#: El reproductor esta con `cuenta=False` a proposito: es el juego, y el juego no
#: corre en el equipo de destino.
PIEZAS = (
    ("consumidor", "run_mqtt_consumer", True),
    ("servidor de la interfaz", "uvicorn", True),
    ("capturador", "capturar_f1_25", True),
    ("reproductor (no cuenta: es el juego)", "reproducir_captura_f1_25", False),
)

CONTENEDORES = ("tesis-mosquitto", "tesis-timescaledb")

#: Una consulta de procesos y una de contenedores por muestra. `docker stats`
#: sin flujo tarda cerca de un segundo, de modo que muestrear mas seguido no
#: daria mas resolucion: daria muestras solapadas.
PERIODO_S = 3.0


def _ps(comando: str) -> str:
    r = subprocess.run(["powershell", "-NoProfile", "-Command", comando],
                       capture_output=True, text=True, check=False)
    return (r.stdout or "").strip()


def _muestra_de_procesos() -> dict[str, dict]:
    """Procesador y memoria de cada proceso de Python, por linea de comando.

    Se unen dos clases: la de rendimiento, que trae el uso de procesador y no la
    linea de comando, y la de procesos, que trae la linea de comando y no el uso.
    El identificador de proceso es lo que las une.

    Se rehace en cada muestra en lugar de resolverse una vez: la carga levanta
    procesos a mitad de la corrida, y una lista fijada al principio no los veria.
    """

    salida = _ps(
        "$perf = @{}; "
        "Get-CimInstance Win32_PerfFormattedData_PerfProc_Process | "
        "Where-Object { $_.IDProcess -ne 0 } | "
        "ForEach-Object { $perf[[int]$_.IDProcess] = $_ }; "
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe' or "
        "Name='pythonw.exe'\" | ForEach-Object { "
        "  $p = $perf[[int]$_.ProcessId]; "
        "  if ($p) { [pscustomobject]@{ "
        "    pid = $_.ProcessId; "
        "    cmd = $_.CommandLine; "
        "    cpu = [double]$p.PercentProcessorTime; "
        "    mem = [double]$p.WorkingSet; "
        "    memp = [double]$p.WorkingSetPrivate } } "
        "} | ConvertTo-Json -Compress -Depth 3")

    if not salida:
        return {}
    try:
        filas = json.loads(salida)
    except json.JSONDecodeError:
        return {}
    if isinstance(filas, dict):
        filas = [filas]

    acumulado: dict[str, dict] = {}
    for nombre, marca, _cuenta in PIEZAS:
        acumulado[nombre] = {"nucleos": 0.0, "memoria_mb": 0.0,
                             "memoria_privada_mb": 0.0, "procesos": 0}
    for f in filas:
        cmd = f.get("cmd") or ""
        for nombre, marca, _cuenta in PIEZAS:
            if marca in cmd:
                acumulado[nombre]["nucleos"] += float(f.get("cpu") or 0) / 100.0
                acumulado[nombre]["memoria_mb"] += float(f.get("mem") or 0) / (1024 ** 2)
                acumulado[nombre]["memoria_privada_mb"] += float(f.get("memp") or 0) / (1024 ** 2)
                acumulado[nombre]["procesos"] += 1
                break
    return acumulado


def _a_bytes(texto: str) -> float:
    """Convierte lo que `docker stats` escribe para humanos: `1.677GiB`."""

    texto = texto.strip()
    for sufijo, factor in (("GiB", 1024 ** 3), ("MiB", 1024 ** 2),
                           ("KiB", 1024), ("GB", 1000 ** 3), ("MB", 1000 ** 2),
                           ("kB", 1000), ("B", 1)):
        if texto.endswith(sufijo):
            try:
                return float(texto[:-len(sufijo)]) * factor
            except ValueError:
                return 0.0
    return 0.0


def _muestra_de_contenedores() -> dict[str, dict]:
    r = subprocess.run(
        ["docker", "stats", "--no-stream", "--format",
         "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}"],
        capture_output=True, text=True, check=False)
    salida: dict[str, dict] = {}
    for linea in (r.stdout or "").strip().split("\n"):
        partes = linea.split("\t")
        if len(partes) < 4 or partes[0] not in CONTENEDORES:
            continue
        nombre, cpu, mem, red = partes[0], partes[1], partes[2], partes[3]
        entrada, salida_red = (red.split("/") + ["0B"])[:2]
        salida[nombre] = {
            "nucleos": float(cpu.rstrip("%") or 0) / 100.0,
            "memoria_mb": _a_bytes(mem.split("/")[0]) / (1024 ** 2),
            "red_entrada_mb": _a_bytes(entrada) / (1024 ** 2),
            "red_salida_mb": _a_bytes(salida_red) / (1024 ** 2),
        }
    return salida


def muestrear(segundos: float, etiqueta: str) -> list[dict]:
    muestras: list[dict] = []
    fin = time.perf_counter() + segundos
    while time.perf_counter() < fin:
        t0 = time.perf_counter()
        muestras.append({
            "t": round(time.perf_counter(), 2),
            "procesos": _muestra_de_procesos(),
            "contenedores": _muestra_de_contenedores(),
        })
        sobra = PERIODO_S - (time.perf_counter() - t0)
        if sobra > 0:
            time.sleep(sobra)
    print(f"  {etiqueta}: {len(muestras)} muestras")
    return muestras


def _resumir(muestras: list[dict]) -> dict:
    """Media y maximo de cada pieza. La media dice el costo sostenido; el maximo,
    si hay picos que un equipo mas chico no absorberia."""

    piezas: dict[str, dict] = {}
    for nombre, _marca, cuenta in PIEZAS:
        nucleos = [m["procesos"].get(nombre, {}).get("nucleos", 0.0) for m in muestras]
        memoria = [m["procesos"].get(nombre, {}).get("memoria_mb", 0.0) for m in muestras]
        vivos = [n for n, mem in zip(nucleos, memoria) if mem > 0]
        piezas[nombre] = {
            "cuenta_en_el_equipo": cuenta,
            "nucleos_medios": round(sum(vivos) / len(vivos), 3) if vivos else 0.0,
            "nucleos_maximos": round(max(nucleos), 3) if nucleos else 0.0,
            "memoria_mb_media": round(sum(m for m in memoria if m > 0)
                                      / max(1, len([m for m in memoria if m > 0])), 1),
            "memoria_mb_maxima": round(max(memoria), 1) if memoria else 0.0,
            "memoria_privada_mb_maxima": round(max(
                [m["procesos"].get(nombre, {}).get("memoria_privada_mb", 0.0)
                 for m in muestras] or [0.0]), 1),
            "muestras_con_el_proceso_vivo": len(vivos),
        }
    for nombre in CONTENEDORES:
        nucleos = [m["contenedores"].get(nombre, {}).get("nucleos", 0.0) for m in muestras]
        memoria = [m["contenedores"].get(nombre, {}).get("memoria_mb", 0.0) for m in muestras]
        red_e = [m["contenedores"].get(nombre, {}).get("red_entrada_mb", 0.0) for m in muestras]
        red_s = [m["contenedores"].get(nombre, {}).get("red_salida_mb", 0.0) for m in muestras]
        piezas[nombre] = {
            "cuenta_en_el_equipo": True,
            "nucleos_medios": round(sum(nucleos) / len(nucleos), 3) if nucleos else 0.0,
            "nucleos_maximos": round(max(nucleos), 3) if nucleos else 0.0,
            "memoria_mb_media": round(sum(memoria) / len(memoria), 1) if memoria else 0.0,
            "memoria_mb_maxima": round(max(memoria), 1) if memoria else 0.0,
            # Los contadores de red del contenedor son acumulados desde que
            # arranco: lo que interesa es cuanto crecieron durante el tramo.
            "red_entrada_mb_en_el_tramo": round(max(red_e) - min(red_e), 2) if red_e else 0.0,
            "red_salida_mb_en_el_tramo": round(max(red_s) - min(red_s), 2) if red_s else 0.0,
        }
    return piezas


def _capacidad() -> dict:
    salida = _ps(
        "$c = Get-CimInstance Win32_ComputerSystem; "
        "$p = Get-CimInstance Win32_Processor | Select-Object -First 1; "
        "[pscustomobject]@{ modelo = $p.Name.Trim(); "
        "nucleos = $p.NumberOfCores; logicos = $p.NumberOfLogicalProcessors; "
        "ram_gb = [math]::Round($c.TotalPhysicalMemory/1GB,1) } "
        "| ConvertTo-Json -Compress")
    try:
        return json.loads(salida)
    except json.JSONDecodeError:
        return {}


def _condiciones() -> dict:
    """Las dos condiciones que ya invalidaron una corrida en silencio.

    LA PRIMERA: cuantos suscriptores tiene el flujo en vivo. El servidor de la
    interfaz saltea el anotador y el resumen **solo si no hay ninguno**, de modo
    que una pestana del tablero abierta en un navegador ---aunque este en otra
    ventana, aunque nadie la mire--- hace que la medicion recorra el camino caro.
    Paso: una corrida de verificacion dio 0,992 nucleos contra 1,021, es decir
    ningun cambio, y la causa era una pestana abierta y no el codigo.

    LA SEGUNDA: si la maquina esta de verdad en reposo. La corrida anterior
    arranco con la base todavia drenando la carga previa y su linea de base dio
    **4,282 nucleos**, que no es una linea de base sino trabajo pendiente. Una
    diferencia contra esa referencia no significa nada.
    """

    salida = {"suscriptores_en_vivo": None, "base_en_reposo": None}
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:8000/live/status",
                                    timeout=5) as r:
            salida["suscriptores_en_vivo"] = json.load(r).get("suscriptores")
    except Exception:
        pass
    return salida


def _esperar_reposo(umbral: float = 0.30, paciencia_s: float = 180.0) -> bool:
    """No empieza a medir hasta que la maquina se aquiete de verdad."""

    print(f"  esperando reposo real (base por debajo de {umbral} nucleos)...")
    fin = time.perf_counter() + paciencia_s
    while time.perf_counter() < fin:
        c = _muestra_de_contenedores().get("tesis-timescaledb", {})
        n = c.get("nucleos", 0.0)
        if n <= umbral:
            print(f"    en reposo: base a {n:.3f} nucleos")
            return True
        print(f"    base todavia a {n:.3f} nucleos, esperando...")
        time.sleep(10)
    print("    NO se aquieto: la linea de base va a estar contaminada")
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--segundos", type=float, default=180.0,
                    help="duracion de la carga")
    ap.add_argument("--reposo", type=float, default=45.0,
                    help="duracion de cada tramo en reposo")
    ap.add_argument("--salida", type=Path,
                    default=RAIZ / "logs" / "consumo_de_recursos.json")
    args = ap.parse_args()

    capacidad = _capacidad()
    print(f"  maquina: {capacidad.get('modelo', '?')}, "
          f"{capacidad.get('nucleos', '?')} nucleos "
          f"({capacidad.get('logicos', '?')} logicos), "
          f"{capacidad.get('ram_gb', '?')} GB")
    print()

    condiciones = _condiciones()
    suscriptores = condiciones["suscriptores_en_vivo"]
    print(f"  suscriptores del flujo en vivo: {suscriptores}")
    if suscriptores:
        print("    ATENCION: hay una pestana del tablero conectada. El servidor")
        print("    va a recorrer el camino caro, y la medicion NO verifica el")
        print("    ahorro de saltear el anotador cuando nadie mira.")
    print()

    condiciones["se_aquieto"] = _esperar_reposo()
    print()

    print("  --- tramo 1: reposo, antes de la carga ---")
    antes = muestrear(args.reposo, "reposo previo")

    print(f"  --- tramo 2: la cadena bajo la parrilla de veinte, {args.segundos:.0f} s ---")
    carga = subprocess.Popen(
        [sys.executable, "-u", "scripts/medir_cadena_parrilla_completa.py",
         "--segundos", str(args.segundos)],
        cwd=str(RAIZ), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # El capturador tarda unos segundos en atarse al puerto y el reproductor
    # arranca despues: muestrear desde el instante cero mezclaria el arranque
    # con la carga.
    time.sleep(8)
    durante = muestrear(args.segundos - 8, "bajo carga")
    print("  esperando que la carga termine de drenar...")
    carga.wait(timeout=300)

    print("  --- tramo 3: reposo, despues de la carga ---")
    despues = muestrear(args.reposo, "reposo posterior")

    r = {
        "momento": datetime.now(timezone.utc).isoformat(),
        "maquina": capacidad,
        # Sin esto, una corrida invalida es indistinguible de una valida.
        "condiciones": condiciones,
        "reposo_previo": _resumir(antes),
        "bajo_carga": _resumir(durante),
        "reposo_posterior": _resumir(despues),
    }
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps(r, indent=1, ensure_ascii=False),
                           encoding="utf-8")

    print()
    print("  NUCLEOS OCUPADOS Y MEMORIA (media, y maximo entre parentesis)")
    print()
    print(f"  {'pieza':38s} {'reposo':>16s} {'carga':>16s} {'memoria bajo carga':>22s}")
    total_reposo = total_carga = 0.0
    total_mem = 0.0
    for nombre in list(p[0] for p in PIEZAS) + list(CONTENEDORES):
        a = r["reposo_previo"][nombre]
        b = r["bajo_carga"][nombre]
        marca = "" if b["cuenta_en_el_equipo"] else "  *"
        print(f"  {nombre[:38]:38s} "
              f"{a['nucleos_medios']:6.3f} ({a['nucleos_maximos']:5.2f}) "
              f"{b['nucleos_medios']:6.3f} ({b['nucleos_maximos']:5.2f}) "
              f"{b['memoria_mb_media']:9.0f} MB ({b['memoria_mb_maxima']:6.0f}){marca}")
        if b["cuenta_en_el_equipo"]:
            total_reposo += a["nucleos_medios"]
            total_carga += b["nucleos_medios"]
            total_mem += b["memoria_mb_media"]
    print()
    print(f"  {'TOTAL de lo que iria en el equipo':38s} "
          f"{total_reposo:6.3f}          {total_carga:6.3f}         "
          f"{total_mem:9.0f} MB")
    print()
    print("  * el reproductor emite lo que en operacion emite el juego, que no")
    print("    corre en el equipo de destino: se informa y no se suma.")
    print(f"  detalle en {args.salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
