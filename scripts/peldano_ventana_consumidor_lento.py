"""El peldano de quinientos en vuelo, corrido contra un consumidor lento.

Que pregunta contesta
---------------------
En una corrida vieja se perdio el 22,02 % de las filas con la ventana del
publicador en quinientos mensajes sin confirmar. La pregunta es si la ventana
**causa** la perdida o la **amplifica** cuando el consumidor no alcanza. Para
separarlas hay que poder frenar al consumidor a proposito, y nada del
repositorio lo hace: `scripts/provocar_fallas.py` detiene contenedores o corta la
red, y los ajustes del consumidor cambian el loteo, no la capacidad de escribir.

Cada celda del barrido es (ventana del publicador, freno del consumidor,
repeticion).

De donde sale cada mitad
------------------------
- **Publicador**: `scripts/republicar_captura.publicar()`, el camino
  `--por-broker` con ritmo acotado. Su ventana es la constante de modulo
  `VENTANA_SIN_CONFIRMAR` (1000, `republicar_captura.py:85`); aca se la cambia
  **solo en memoria** por la de cada celda.
- **Consumidor**: `scripts/run_mqtt_consumer.main()` sin cambios, en **otro
  proceso** (este mismo archivo con `--rol consumidor`). Se sustituye una sola
  pieza: el escritor de lotes (`backend/mqtt_consumer.py:157` resuelve
  `EscritorTelemetria` al construir el buffer), por uno que despues de escribir
  cada lote espera lo necesario para no pasar de `--freno` filas por segundo. La
  espera cae **antes** del acuse manual (`mqtt_consumer.py:374-382`), de modo que
  el intermediario ve un consumidor lento de verdad: acuses que tardan.
- **Conciliacion**: `scripts/provocar_fallas.filas_de_la_corrida()` (filas y
  secuencias distintas), restada contra lo publicado.

El freno es un reloj de lote, no un promedio
--------------------------------------------
El turno de cada lote se cuenta desde el turno del anterior, no desde el
arranque. Si el consumidor estuvo ocioso mas que `GRACIA_FRENO_S`, el reloj se
reinicia en el comienzo del lote: un rato sin trabajo no acumula credito para
una rafaga despues. Dentro de esa gracia si se compensa, para que la
imprecision de `time.sleep` no convierta el tope en un ritmo menor.

Solo contra una pila aislada
----------------------------
Se niega (codigo distinto de cero) si el intermediario es el 1883, si la base se
llama `tesis_db` o esta en el 5432, o si la base destino tiene mas de un millon
de filas en `telemetry_messages`. El destino de los argumentos se fija en el
entorno **antes** de importar `backend.config`, y le gana a cualquier `.env`
(`backend/config.py:24-47` solo completa lo que el entorno no trae).

Entre celdas
------------
- se borran las filas de la corrida anterior: la identidad de corrida sale del
  hash de la captura y se repite, y sin borrar la idempotencia descartaria la
  celda siguiente entera;
- cada consumidor usa una identidad de cliente MQTT propia, y al terminar se
  limpia su sesion conservada: una sesion huerfana seguiria encolando y
  descartando mensajes de las celdas siguientes, y ese descarte contaminaria su
  `broker_dropped`.

Uso
---
    python -B scripts/peldano_ventana_consumidor_lento.py CAPTURA.f1raw --solo-inventario
    python -B scripts/peldano_ventana_consumidor_lento.py CAPTURA.f1raw \\
        --mqtt-puerto 1884 --db-puerto 5433 --db-nombre tesis_peldano \\
        --ventanas 1000 500 --frenos 0 1804 1000 --por-segundo 2000 \\
        --repeticiones 1 --salida logs/peldano_minima.json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
ESTE_ARCHIVO = Path(__file__).resolve()

#: Mosquitto publica su contador de descartes cada `sys_interval` (10 s por
#: omision). Terminar antes pierde la ultima lectura.
MARGEN_SYS_S = 12.0

#: Segundos sin avance de lo persistido para dar una celda por drenada.
QUIETUD_S = 10.0

#: Retraso del reloj del freno que todavia se compensa. Mas que esto es un rato
#: ocioso, y no genera credito.
GRACIA_FRENO_S = 0.05

#: Tope de filas de la base destino; mas que esto no parece la aislada.
TOPE_FILAS_BASE_AISLADA = 1_000_000

PUERTO_MQTT_PRINCIPAL = 1883
PUERTO_DB_PRINCIPAL = 5432
NOMBRE_DB_PRINCIPAL = "tesis_db"


def argumentos(argv: Sequence[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("captura", type=Path, nargs="?",
                    help="archivo .f1raw con su .f1raw.meta.json al lado")
    ap.add_argument("--ventanas", type=int, nargs="+", default=[1000, 500],
                    help="mensajes sin confirmar del publicador, por celda")
    ap.add_argument("--frenos", type=float, nargs="+", default=[0.0, 1804.0, 1000.0],
                    help="tope de escritura del consumidor en filas/s; 0 = sin freno")
    ap.add_argument("--por-segundo", type=float, default=2000.0,
                    help="ritmo pedido al publicador, en mensajes por segundo")
    ap.add_argument("--repeticiones", type=int, default=1)
    ap.add_argument("--mqtt-host", default="127.0.0.1")
    ap.add_argument("--mqtt-puerto", type=int, default=1884)
    ap.add_argument("--db-host", default="127.0.0.1")
    ap.add_argument("--db-puerto", type=int, default=5433)
    ap.add_argument("--db-nombre", default="tesis_peldano")
    ap.add_argument("--db-usuario", default="tesis_user")
    ap.add_argument("--db-clave", default="tesis_pass")
    ap.add_argument("--espera-maxima", type=float, default=900.0,
                    help="segundos maximos de drenaje despues de publicar")
    ap.add_argument("--salida", type=Path, default=Path("logs/peldano_ventana_consumidor_lento.json"))
    ap.add_argument("--borrar-al-final", action="store_true",
                    help="borra las filas de la corrida en la base aislada al terminar")
    ap.add_argument("--solo-inventario", action="store_true",
                    help="cuenta filas, sesion e identidad sin intermediario ni base")
    # Rol interno: el mismo archivo hace de consumidor frenado en otro proceso.
    ap.add_argument("--rol", choices=["orquestador", "consumidor"], default="orquestador",
                    help=argparse.SUPPRESS)
    ap.add_argument("--freno", type=float, default=0.0, help=argparse.SUPPRESS)
    ap.add_argument("--metrics-file", type=Path, help=argparse.SUPPRESS)
    return ap.parse_args(argv)


# --------------------------------------------------------------------------- #
# Protecciones
# --------------------------------------------------------------------------- #

def negar_destino_principal(args: argparse.Namespace) -> None:
    """Se niega a apuntar al intermediario o a la base principales.

    Es una comprobacion de argumentos y corre antes de conectarse a nada.
    """
    if args.mqtt_puerto == PUERTO_MQTT_PRINCIPAL:
        raise SystemExit(f"NEGADO: {PUERTO_MQTT_PRINCIPAL} es el puerto del intermediario principal.")
    if args.db_nombre == NOMBRE_DB_PRINCIPAL:
        raise SystemExit(f"NEGADO: {NOMBRE_DB_PRINCIPAL} es la base principal.")
    if args.db_puerto == PUERTO_DB_PRINCIPAL:
        raise SystemExit(f"NEGADO: {PUERTO_DB_PRINCIPAL} es el puerto de la base principal.")


def fijar_entorno(args: argparse.Namespace) -> None:
    """Fija el destino en el entorno ANTES de importar `backend.config`.

    Si `backend.config` ya estaba importado con otro destino ---por ejemplo, en
    un proceso de pruebas--- no hay forma segura de seguir, y se niega.
    """
    destino = {
        "MQTT_HOST": args.mqtt_host, "MQTT_PORT": str(args.mqtt_puerto),
        "DB_HOST": args.db_host, "DB_PORT": str(args.db_puerto), "DB_NAME": args.db_nombre,
        "DB_USER": args.db_usuario, "DB_PASSWORD": args.db_clave,
    }
    os.environ.update(destino)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    config = sys.modules.get("backend.config")
    if config is not None and (config.MQTT_PORT != args.mqtt_puerto
                               or config.DB_PORT != args.db_puerto
                               or config.DB_NAME != args.db_nombre):
        raise SystemExit("NEGADO: backend.config ya estaba importado con otro destino.")


def negar_base_grande() -> int:
    """Cuenta hasta un millon y una filas de la base destino; se niega si las hay."""
    from backend import db
    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        cursor.execute("select count(*) from (select 1 from telemetry_messages limit %s) t",
                       (TOPE_FILAS_BASE_AISLADA + 1,))
        filas = cursor.fetchone()[0]
    if filas > TOPE_FILAS_BASE_AISLADA:
        raise SystemExit("NEGADO: la base destino tiene mas de un millon de filas; "
                         "no parece la aislada.")
    return filas


# --------------------------------------------------------------------------- #
# El freno
# --------------------------------------------------------------------------- #

def frenar(escritor_base: type, tope_filas_s: float,
           reloj=time.perf_counter, dormir=time.sleep) -> type:
    """Devuelve una subclase de `escritor_base` que no pasa de `tope_filas_s`.

    Con tope cero devuelve la clase sin tocar.
    """
    if not tope_filas_s or tope_filas_s <= 0:
        return escritor_base

    class EscritorFrenado(escritor_base):
        """El escritor de siempre, con un tope sostenido de filas por segundo."""

        def __init__(self, *a, **k) -> None:
            super().__init__(*a, **k)
            self._turno = None

        def __call__(self, mensajes):
            comienzo = reloj()
            escritas = super().__call__(mensajes)
            if mensajes:
                base = self._turno
                if base is None or comienzo - base > GRACIA_FRENO_S:
                    base = comienzo
                self._turno = base + len(mensajes) / tope_filas_s
                espera = self._turno - reloj()
                if espera > 0:
                    dormir(espera)
            return escritas

    return EscritorFrenado


def rol_consumidor(args: argparse.Namespace) -> int:
    from backend import db, mqtt_consumer
    mqtt_consumer.EscritorTelemetria = frenar(db.EscritorTelemetria, args.freno)
    from scripts import run_mqtt_consumer
    sys.argv = ["run_mqtt_consumer.py", "--metrics-file", str(args.metrics_file)]
    run_mqtt_consumer.main()
    return 0


# --------------------------------------------------------------------------- #
# Orquestador
# --------------------------------------------------------------------------- #

def inventario(captura: Path) -> dict:
    from scripts import republicar_captura as rc
    meta = rc.leer_metadatos(captura)
    inicio_utc = meta.get("inicio_utc")
    if not inicio_utc:
        raise SystemExit("los metadatos no declaran inicio_utc")
    t0 = time.perf_counter()
    conteo, session_id, vehiculos = rc.inventariar(captura, inicio_utc, meta.get("sha256"))
    return {
        "meta": meta, "inicio_utc": inicio_utc, "conteo": conteo,
        "session_id": session_id, "vehiculos": sorted(vehiculos),
        "total": sum(conteo.values()),
        "run_id": rc.identidad_de_corrida(meta, captura),
        "inventario_s": time.perf_counter() - t0,
    }


def borrar_corrida(session_id: str, run_id: str) -> int:
    from backend import db
    with db.obtener_conexion() as conexion:
        with conexion.cursor() as cursor:
            cursor.execute("""delete from telemetry_messages
                               where session_id = %s
                                 and metadata->'extra'->>'replay_run_id' = %s""",
                           (session_id, run_id))
            borradas = cursor.rowcount
        conexion.commit()
    return borradas


def estado_de_la_tabla() -> dict:
    """Fragmentos comprimidos y filas totales: la compresion cambia la escritura."""
    from backend import db
    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        cursor.execute("select count(*) from telemetry_messages")
        filas = cursor.fetchone()[0]
        try:
            cursor.execute("""select count(*) filter (where is_compressed), count(*)
                                from timescaledb_information.chunks
                               where hypertable_name = 'telemetry_messages'""")
            comprimidos, fragmentos = cursor.fetchone()
        except Exception:  # noqa: BLE001 - sin TimescaleDB no hay fragmentos
            conexion.rollback()
            comprimidos = fragmentos = None
    return {"filas": filas, "fragmentos": fragmentos, "fragmentos_comprimidos": comprimidos}


def limpiar_sesion(args: argparse.Namespace, client_id: str) -> bool:
    """Reconecta con la misma identidad y sesion limpia, y se desconecta."""
    import paho.mqtt.client as mqtt
    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id,
                          clean_session=True)
    try:
        cliente.connect(args.mqtt_host, args.mqtt_puerto, 10)
        cliente.loop_start()
        time.sleep(1.0)
        cliente.disconnect()
        cliente.loop_stop()
        return True
    except OSError:
        return False


def leer_metricas(ruta: Path) -> dict:
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def correr_celda(args, inv: dict, ventana: int, freno: float, rep: int) -> dict:
    from scripts import provocar_fallas, republicar_captura as rc

    session_id, run_id = inv["session_id"], inv["run_id"]
    previas = borrar_corrida(session_id, run_id)
    tabla_antes = estado_de_la_tabla()

    marca = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    nombre = f"v{ventana}_f{int(freno)}_r{rep}_{marca}"
    carpeta = args.salida.parent
    metricas = carpeta / f"peldano_metricas_{nombre}.json"
    registro = carpeta / f"peldano_consumidor_{nombre}.log"
    client_id = f"peldano-{nombre}"
    entorno = dict(os.environ, MQTT_CLIENT_ID=client_id)

    # La salida del consumidor va a un archivo y no a una tuberia: una tuberia que
    # nadie lee se llena y bloquea al consumidor en un print.
    with registro.open("w", encoding="utf-8") as archivo_registro:
        consumidor = subprocess.Popen(
            [sys.executable, "-B", str(ESTE_ARCHIVO), "--rol", "consumidor",
             "--freno", str(freno), "--metrics-file", str(metricas),
             "--mqtt-host", args.mqtt_host, "--mqtt-puerto", str(args.mqtt_puerto),
             "--db-host", args.db_host, "--db-puerto", str(args.db_puerto),
             "--db-nombre", args.db_nombre, "--db-usuario", args.db_usuario,
             "--db-clave", args.db_clave],
            cwd=str(ROOT), env=entorno, stdout=archivo_registro, stderr=subprocess.STDOUT)
        try:
            time.sleep(6.0)  # suscripcion antes de publicar
            if consumidor.poll() is not None:
                raise SystemExit("el consumidor murio al arrancar; ver " + str(registro))

            rc.VENTANA_SIN_CONFIRMAR = ventana
            t0 = time.perf_counter()
            publicados = rc.publicar(args.captura, inv["inicio_utc"], inv["meta"].get("sha256"),
                                     set(inv["conteo"]), inv["total"], run_id, args.por_segundo)
            t_publicacion = time.perf_counter() - t0

            fin_publicacion = time.perf_counter()
            ultimo_cambio, anterior, avance = fin_publicacion, None, []
            drenado = False
            while time.perf_counter() - fin_publicacion < args.espera_maxima:
                time.sleep(2.5)
                m = leer_metricas(metricas)
                persistidas = m.get("persisted")
                avance.append((round(time.perf_counter() - t0, 1), persistidas, m.get("pending")))
                if persistidas != anterior:
                    anterior, ultimo_cambio = persistidas, time.perf_counter()
                    continue
                if (time.perf_counter() - ultimo_cambio >= QUIETUD_S
                        and m.get("pending") == 0
                        and time.perf_counter() - fin_publicacion >= MARGEN_SYS_S):
                    drenado = True
                    break
            t_celda = time.perf_counter() - t0
            m = leer_metricas(metricas)
        finally:
            consumidor.terminate()
            try:
                consumidor.wait(timeout=30)
            except subprocess.TimeoutExpired:
                consumidor.kill()
    sesion_limpia = limpiar_sesion(args, client_id)

    base = provocar_fallas.filas_de_la_corrida(session_id, run_id)
    faltantes = publicados - base["secuencias_distintas"]
    return {
        "repeticion": rep, "ventana": ventana, "freno_filas_s": freno,
        "por_segundo_pedido": args.por_segundo,
        "publicados": publicados,
        "ritmo_publicador_real": round(publicados / max(t_publicacion, 1e-9), 1),
        "publicacion_s": round(t_publicacion, 1), "celda_s": round(t_celda, 1),
        "drenado": drenado,
        "filas_previas_borradas": previas,
        "tabla_antes": tabla_antes, "tabla_despues": estado_de_la_tabla(),
        "filas": base["filas"], "secuencias_distintas": base["secuencias_distintas"],
        "repetidas": base["repetidas"], "huecos_en_rango": base["huecos"],
        "faltantes": faltantes,
        "perdida_pct": round(100.0 * faltantes / publicados, 3) if publicados else None,
        "consumidor": {k: m.get(k) for k in (
            "received", "persisted", "pending", "errors", "broker_dropped",
            "broker_dropped_total", "max_pending", "batches", "confirmados",
            "backpressure_waits", "disconnects", "duplicates_skipped")},
        "escritura_media_filas_s": (round(m["persisted"] / t_celda, 1)
                                    if m.get("persisted") else None),
        "sesion_mqtt_limpiada": sesion_limpia,
        "avance_persistidas": avance,
        "metricas": str(metricas), "registro_consumidor": str(registro),
    }


def maquina() -> dict:
    return {"sistema": platform.platform(), "procesador": platform.processor(),
            "python": platform.python_version(), "nucleos_logicos": os.cpu_count()}


def main(argv: Sequence[str] | None = None) -> int:
    args = argumentos(argv)
    negar_destino_principal(args)
    fijar_entorno(args)

    if args.rol == "consumidor":
        return rol_consumidor(args)

    if args.captura is None:
        raise SystemExit("falta la captura")
    args.captura = args.captura.resolve()
    if not args.captura.is_file():
        raise SystemExit(f"no existe: {args.captura}")
    if not args.salida.is_absolute():
        args.salida = (Path.cwd() / args.salida).resolve()

    inv = inventario(args.captura)
    celdas = [(v, f) for v in args.ventanas for f in args.frenos]
    print(f"  captura    : {args.captura.name}")
    print(f"  sesion     : {inv['session_id']}")
    print(f"  identidad  : {inv['run_id']}")
    print(f"  filas      : {inv['total']} en {len(inv['conteo'])} senales")
    print(f"  inventario : {inv['inventario_s']:.1f} s")
    print(f"  celdas     : {len(celdas)} x {args.repeticiones} repeticiones")
    if args.solo_inventario:
        return 0

    filas_iniciales = negar_base_grande()
    from backend import config
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    corrida = {
        "comienzo_utc": datetime.now(timezone.utc).isoformat(),
        "maquina": maquina(),
        "captura": args.captura.name, "session_id": inv["session_id"],
        "run_id": inv["run_id"], "filas_en_la_captura": inv["total"],
        "destino": {"mqtt": f"{args.mqtt_host}:{args.mqtt_puerto}",
                    "db": f"{args.db_host}:{args.db_puerto}/{args.db_nombre}"},
        "filas_iniciales_base": filas_iniciales,
        "consumidor_config": {
            "MQTT_BATCH_SIZE": config.MQTT_BATCH_SIZE,
            "MQTT_FLUSH_INTERVAL_SECONDS": config.MQTT_FLUSH_INTERVAL_SECONDS,
            "MQTT_MAX_PENDING_MESSAGES": config.MQTT_MAX_PENDING_MESSAGES,
            "MQTT_SESION_PERSISTENTE": config.MQTT_SESION_PERSISTENTE,
            "MQTT_CONFIRMACION_MANUAL": config.MQTT_CONFIRMACION_MANUAL,
            "MQTT_QOS_EN_VIVO": config.MQTT_QOS_EN_VIVO,
        },
        "argumentos": {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()},
        "celdas": [],
    }
    t_corrida = time.perf_counter()
    for rep in range(1, args.repeticiones + 1):
        for ventana, freno in celdas:
            print(f"\n  rep {rep} · ventana {ventana} · freno "
                  f"{'ninguno' if not freno else f'{freno:.0f} filas/s'} ...", flush=True)
            r = correr_celda(args, inv, ventana, freno, rep)
            corrida["celdas"].append(r)
            corrida["duracion_s"] = round(time.perf_counter() - t_corrida, 1)
            args.salida.write_text(json.dumps(corrida, indent=1, ensure_ascii=False, default=str),
                                   encoding="utf-8")
            c = r["consumidor"]
            print(f"     publicados {r['publicados']} a {r['ritmo_publicador_real']:.0f}/s · "
                  f"filas {r['filas']} · distintas {r['secuencias_distintas']} · "
                  f"repetidas {r['repetidas']} · faltan {r['faltantes']} "
                  f"({r['perdida_pct']} %) · broker_dropped {c['broker_dropped']} · "
                  f"batches {c['batches']} · max_pending {c['max_pending']} · "
                  f"drenado {r['drenado']}", flush=True)

    if args.borrar_al_final:
        print(f"\n  borradas {borrar_corrida(inv['session_id'], inv['run_id'])} filas")
    corrida["fin_utc"] = datetime.now(timezone.utc).isoformat()
    args.salida.write_text(json.dumps(corrida, indent=1, ensure_ascii=False, default=str),
                           encoding="utf-8")
    print(f"\n  detalle en {args.salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
