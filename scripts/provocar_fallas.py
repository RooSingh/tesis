#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Provoca tres fallas sobre la cadena y reporta que pasa con los datos.

    python3 scripts/provocar_fallas.py <captura.f1raw> --falla base
    python3 scripts/provocar_fallas.py <captura.f1raw> --falla intermediario
    python3 scripts/provocar_fallas.py <captura.f1raw> --falla red

El punto 7 de «Lo que falta del sistema». De cada falla se reportan siempre las
mismas tres cosas: que se pierde, que se conserva, y en que condiciones el
sistema vuelve a operar ---con duplicados o con huecos, si los hubiera---.

SE CUENTA CONTRA LA BASE, NO CONTRA LOS CONTADORES DEL PUBLICADOR, y el punto lo
pide asi por un motivo concreto: **una fila duplicada mas una faltante cierran el
balance en falso**. Por eso se cuentan dos cosas distintas ---filas y numeros de
secuencia distintos--- y se comparan entre si. Si difieren, hubo repeticion.

NUNCA CORRE CONTRA PRODUCCION. Se comprueba antes de empezar que los
contenedores sean los locales; si el objetivo no es local, el guion se niega.
Tumbar la base de la Raspberry con una sesion en marcha no es un experimento,
es un incidente.

QUE FALLA CADA MODO
-------------------
- `base`: se detiene el contenedor de la base mientras la corrida avanza. El
  consumidor sigue recibiendo del intermediario y acumulando en memoria.
- `intermediario`: se detiene el contenedor del intermediario. El publicador
  pierde su conexion y el consumidor su suscripcion.
- `red`: se desconecta al intermediario de su red sin detenerlo. Es distinto de
  apagarlo: el proceso sigue vivo y los clientes no reciben un cierre limpio,
  que es lo que pasa cuando se corta un cable.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import config, db                                  # noqa: E402

CONTENEDOR_BASE = "tesis-timescaledb"
CONTENEDOR_INTERMEDIARIO = "tesis-mosquitto"
RAIZ = Path(__file__).resolve().parents[1]


def _docker(*args: str) -> str:
    return subprocess.run(["docker", *args], capture_output=True,
                          text=True).stdout.strip()


def exigir_entorno_local() -> None:
    """Se niega a correr si el objetivo no es la maquina de trabajo.

    No alcanza con que quien lo invoca tenga cuidado: el guion detiene servicios,
    y un guion que detiene servicios tiene que saber sobre cual esta parado.
    """

    host = (config.DB_HOST or "").lower()
    if host not in {"localhost", "127.0.0.1", "::1"}:
        raise SystemExit(f"la base apunta a «{host}», que no es local. No se corre.")
    mqtt = (config.MQTT_HOST or "").lower()
    if mqtt not in {"localhost", "127.0.0.1", "::1"}:
        raise SystemExit(f"el intermediario apunta a «{mqtt}». No se corre.")
    for c in (CONTENEDOR_BASE, CONTENEDOR_INTERMEDIARIO):
        if not _docker("ps", "--filter", f"name=^{c}$", "--format", "{{.Names}}"):
            raise SystemExit(f"no esta corriendo el contenedor local {c}")


def filas_de_la_corrida(session_id: str, run_id: str) -> dict:
    """Lo que la base tiene de esta corrida. Es la unica fuente de verdad.

    Se piden **las dos cuentas**: filas y secuencias distintas. Iguales, no hubo
    repeticion; distintas, la diferencia es exactamente cuantas filas se
    escribieron dos veces.
    """

    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        cursor.execute(
            """select count(*),
                      count(distinct (metadata->'extra'->>'replay_seq')),
                      min((metadata->'extra'->>'replay_seq')::bigint),
                      max((metadata->'extra'->>'replay_seq')::bigint)
                 from telemetry_messages
                where session_id = %s
                  and metadata->'extra'->>'replay_run_id' = %s""",
            (session_id, run_id))
        filas, distintas, menor, mayor = cursor.fetchone()
        cursor.execute(
            """select count(*) from (
                   select distinct (metadata->'extra'->>'replay_seq')::bigint as s
                     from telemetry_messages
                    where session_id = %s
                      and metadata->'extra'->>'replay_run_id' = %s) t""",
            (session_id, run_id))
    return {
        "filas": filas or 0,
        "secuencias_distintas": distintas or 0,
        "secuencia_menor": menor,
        "secuencia_mayor": mayor,
        # Un hueco es una secuencia que el publicador emitio y la base no tiene.
        # Se deduce del rango: entre la menor y la mayor deberia estar todo.
        "huecos": ((mayor - menor + 1) - (distintas or 0))
                  if (menor is not None and mayor is not None) else None,
        "repetidas": (filas or 0) - (distintas or 0),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("captura", type=Path)
    p.add_argument("--falla", required=True,
                   choices=["base", "intermediario", "red", "ninguna"])
    p.add_argument("--esperar-antes", type=float, default=6.0,
                   help="segundos de corrida limpia antes de provocar la falla")
    p.add_argument("--dura", type=float, default=8.0,
                   help="cuanto dura la falla")
    p.add_argument("--por-segundo", type=float, default=2000.0,
                   help="ritmo del publicador. Sin acotarlo, la corrida limpia "
                        "ya pierde y ninguna falla se puede atribuir.")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    exigir_entorno_local()
    if not args.captura.exists():
        raise SystemExit(f"no existe: {args.captura}")

    # LA IDENTIDAD DE CORRIDA SE DERIVA DE LA CAPTURA, asi que dos reproducciones
    # de la misma captura comparten `replay_run_id` y la segunda se suprime
    # entera por `ON CONFLICT DO NOTHING`. Es lo correcto para rellenar ---un
    # reintento no duplica--- y es exactamente lo que arruina un experimento:
    # la segunda corrida informa la union de las dos y ninguna falla se puede
    # atribuir. Se borra lo de la corrida anterior antes de empezar.
    identidad = subprocess.run(
        [sys.executable, str(RAIZ / "scripts" / "republicar_captura.py"),
         str(args.captura), "--simular"],
        capture_output=True, text=True).stdout
    previo_sesion = previo_run = None
    for linea in identidad.splitlines():
        if linea.startswith("Sesion") and ":" in linea:
            previo_sesion = linea.split(":", 1)[1].strip()
    if previo_sesion:
        with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
            cursor.execute(
                """delete from telemetry_messages
                    where session_id = %s
                      and metadata->'extra'->>'replay_run_id' is not null""",
                (previo_sesion,))
            borradas = cursor.rowcount
            conexion.commit()
        print(f"  se borraron {borradas} filas de reproducciones anteriores")


    consumidor = subprocess.Popen(
        [sys.executable, str(RAIZ / "scripts" / "run_mqtt_consumer.py")],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    # El consumidor tarda en suscribirse. Publicar antes perderia los primeros
    # mensajes y el experimento informaria una perdida que no ocurrio en la
    # falla sino en el arranque.
    time.sleep(4.0)

    publicador = subprocess.Popen(
        [sys.executable, str(RAIZ / "scripts" / "republicar_captura.py"),
         str(args.captura), "--por-broker",
         "--por-segundo", str(args.por_segundo)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    linea_tiempo = []
    def anotar(que: str) -> None:
        linea_tiempo.append({"t": round(time.time() - t0, 2), "que": que})

    t0 = time.time()
    anotar("arranca la corrida")
    time.sleep(args.esperar_antes)

    if args.falla == "base":
        _docker("stop", CONTENEDOR_BASE); anotar("se detiene la base")
    elif args.falla == "intermediario":
        _docker("stop", CONTENEDOR_INTERMEDIARIO); anotar("se detiene el intermediario")
    elif args.falla == "red":
        red = _docker("inspect", "-f",
                      "{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}",
                      CONTENEDOR_INTERMEDIARIO)
        _docker("network", "disconnect", red, CONTENEDOR_INTERMEDIARIO)
        anotar(f"se desconecta el intermediario de la red {red}")

    if args.falla != "ninguna":
        time.sleep(args.dura)
        if args.falla == "base":
            _docker("start", CONTENEDOR_BASE)
        elif args.falla == "intermediario":
            _docker("start", CONTENEDOR_INTERMEDIARIO)
        elif args.falla == "red":
            _docker("network", "connect", red, CONTENEDOR_INTERMEDIARIO)
        anotar("se restablece")

    salida_pub = ""
    try:
        salida_pub = publicador.communicate(timeout=240)[0] or ""
    except subprocess.TimeoutExpired:
        publicador.kill()
        salida_pub = (publicador.communicate()[0] or "") + "\n[el publicador no termino]"
    anotar("termina el publicador")

    run_id = session_id = None
    for linea in salida_pub.splitlines():
        if linea.startswith("identidad de corrida:"):
            run_id = linea.split(":", 1)[1].strip()
        elif linea.startswith("Sesion") and ":" in linea:
            session_id = linea.split(":", 1)[1].strip()
    publicadas = None
    for linea in salida_pub.splitlines():
        if linea.startswith("publicados"):
            publicadas = linea.split(":", 1)[1].strip()

    # SE ESPERA A QUE LA BASE DEJE DE CRECER, NO UN NUMERO FIJO DE SEGUNDOS.
    #
    # La primera version esperaba seis segundos y mataba al consumidor ahi. Con
    # lotes de cinco mil y trescientas mil filas en cola, seis segundos lo cortan
    # a mitad del vaciado: la corrida **sin falla** informaba 100.490 de 404.972
    # filas, un setenta y cinco por ciento de perdida que no era del transporte
    # sino de este guion. Una medicion que corta el experimento antes de que
    # termine no mide el sistema: mide su propia impaciencia.
    anterior, quieto, esperado = -1, 0, time.time() + 300
    while time.time() < esperado:
        time.sleep(3.0)
        try:
            ahora = filas_de_la_corrida(session_id, run_id)["filas"] if (
                session_id and run_id) else -1
        except Exception:                          # noqa: BLE001
            ahora = -1                             # la base puede estar caida
        if ahora >= 0 and ahora == anterior:
            quieto += 1
            if quieto >= 3:                        # nueve segundos sin moverse
                break
        else:
            quieto = 0
        anterior = ahora
    anotar("la base dejo de crecer")
    consumidor.terminate()
    salida_cons = ""
    try:
        salida_cons = consumidor.communicate(timeout=30)[0] or ""
    except subprocess.TimeoutExpired:
        consumidor.kill()
    anotar("se detiene el consumidor")

    # Las dos identidades salen del propio publicador, con el formato exacto con
    # el que las imprime. Adivinarlo fue el primer error de este guion: tomaba
    # cualquier linea con «session_id» y se quedaba con el nombre de una funcion.
    conteo = {}
    if run_id and session_id:
        try:
            conteo = filas_de_la_corrida(session_id, run_id)
        except Exception as e:                     # noqa: BLE001
            conteo = {"error": str(e)}

    informe = {
        "falla": args.falla,
        "run_id": run_id,
        "session_id": session_id,
        "linea_tiempo": linea_tiempo,
        "en_la_base": conteo,
        "publicadas_dice_el_publicador": publicadas,
        "publicador": salida_pub[-1500:],
        "consumidor": salida_cons[-1500:],
    }
    print(json.dumps(informe, ensure_ascii=False, indent=2) if args.json
          else _legible(informe))
    return 0


def _legible(i: dict) -> str:
    lineas = [f"\n  == falla: {i['falla']} ==",
              f"  corrida {i['run_id']} · sesion {i['session_id']}",
              f"  el publicador dice haber publicado: {i.get('publicadas_dice_el_publicador')}"]
    for m in i["linea_tiempo"]:
        lineas.append(f"    {m['t']:7.2f} s  {m['que']}")
    b = i["en_la_base"]
    if "error" in b:
        lineas.append(f"    no se pudo contar: {b['error']}")
    elif b:
        lineas.append(f"    en la base: {b['filas']} filas · "
                      f"{b['secuencias_distintas']} secuencias distintas · "
                      f"rango {b['secuencia_menor']}..{b['secuencia_mayor']} · "
                      f"huecos {b['huecos']} · repetidas {b['repetidas']}")
    return "\n".join(lineas)


if __name__ == "__main__":
    raise SystemExit(main())
