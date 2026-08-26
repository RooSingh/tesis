"""Reproduce datos OpenF1 locales por MQTT con filtros explícitos y modo seco seguro."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.openf1 import messages_from_openf1_sample
from backend.config import MQTT_HOST, MQTT_PORT, MQTT_REPLAY_TOPIC


DATA_ROOT = ROOT / "datasets" / "OpenF1" / "raw" / "2025"
SUPPORTED_ENDPOINTS = {"car_data", "location"}


def parse_time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def parse_drivers(value: str, session_path: Path) -> list[tuple[int, str]]:
    drivers = json.loads((session_path / "drivers.json").read_text(encoding="utf-8"))
    acronyms = {row["driver_number"]: row["name_acronym"] for row in drivers}
    selected = sorted(acronyms) if value == "all" else sorted({int(item) for item in value.split(",")})
    unknown = [number for number in selected if number not in acronyms]
    if unknown:
        raise ValueError(f"Pilotos no disponibles en la sesion: {unknown}")
    return [(number, acronyms[number]) for number in selected]


def collect_samples(
    session_path: Path,
    drivers: list[tuple[int, str]],
    endpoints: list[str],
    start: datetime | None,
    end: datetime | None,
) -> list[tuple[dict, str, str, str]]:
    """Filtra archivos crudos por reloj deportivo, sin alterar las muestras."""
    selected = []
    for driver_number, acronym in drivers:
        for endpoint in endpoints:
            path = session_path / f"{endpoint}_driver_{driver_number}_{acronym}.json"
            if not path.is_file():
                raise FileNotFoundError(f"No existe telemetria {endpoint} para piloto {driver_number}: {path}")
            rows = json.loads(path.read_text(encoding="utf-8"))
            for row in rows:
                timestamp = parse_time(row["date"])
                if (start is None or timestamp >= start) and (end is None or timestamp < end):
                    source_url = f"https://api.openf1.org/v1/{endpoint}?session_key={row['session_key']}&driver_number={driver_number}"
                    selected.append((row, endpoint, source_url, str(path)))
    return sorted(selected, key=lambda item: item[0]["date"])


def build_messages(samples: list[tuple[dict, str, str, str]]) -> list[dict]:
    messages = []
    for row, endpoint, source_url, path in samples:
        messages.extend(messages_from_openf1_sample(row, endpoint, source_url, path, datetime.now(timezone.utc).isoformat()))
    return messages


def publish(
    messages: list[dict],
    speed: float,
    max_delay: float,
    max_inflight_messages: int,
    client_factory=mqtt.Client,
) -> dict[str, int]:
    """Publica con QoS 1 y un limite explicito de confirmaciones pendientes."""
    client = client_factory(mqtt.CallbackAPIVersion.VERSION2)
    client.max_inflight_messages_set(max_inflight_messages)
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.loop_start()
    previous = None
    pending = []
    metrics = {"attempted": 0, "acknowledged": 0, "publish_rc_errors": 0}
    try:
        for message in messages:
            current = parse_time(message["timestamp"])
            if previous is not None:
                time.sleep(min((current - previous).total_seconds() / speed, max_delay))
            message["metadata"]["extra"]["published_at_utc"] = datetime.now(timezone.utc).isoformat()
            result = client.publish(MQTT_REPLAY_TOPIC, json.dumps(message), qos=1)
            metrics["attempted"] += 1
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                metrics["publish_rc_errors"] += 1
                raise RuntimeError(f"MQTT rechazo el mensaje {metrics['attempted']} con rc={result.rc}")
            pending.append(result)
            if len(pending) >= max_inflight_messages:
                pending.pop(0).wait_for_publish()
                metrics["acknowledged"] += 1
            previous = current
        for result in pending:
            result.wait_for_publish()
            metrics["acknowledged"] += 1
    except Exception:
        print(json.dumps({"publish_metrics": metrics}, sort_keys=True))
        raise
    finally:
        client.loop_stop()
        client.disconnect()
    return metrics


def iter_stream_messages(
    stream_path: Path,
    replay_run_id: str,
    desde_seq: int = 0,
):
    """Genera `(seq, mensaje)` desde el JSONL preparado, sin materializar listas.

    Es la contraparte de `scripts/prepare_replay_stream.py`. El archivo se lee
    linea por linea y cada muestra se expande en el momento de publicarla, de
    modo que la memoria ocupada no depende del tamano de la carrera.

    `desde_seq` permite reanudar: las muestras integramente anteriores al corte se
    saltean sin expandirse, y dentro de la muestra que contiene el corte se
    descartan solo los mensajes ya confirmados.
    """
    with stream_path.open("r", encoding="utf-8") as archivo:
        for linea in archivo:
            if not linea.strip():
                continue
            registro = json.loads(linea)
            seq_base = registro["seq"]
            if seq_base + registro["n"] <= desde_seq:
                continue
            mensajes = messages_from_openf1_sample(
                registro["sample"],
                registro["endpoint"],
                registro["source_url"],
                registro["raw_payload_path"],
            )
            if len(mensajes) != registro["n"]:
                # Si la expansion no coincide con lo que declaro el preparador,
                # toda la numeracion global queda corrida y la clave de
                # idempotencia deja de ser confiable. Detenerse es obligatorio.
                raise RuntimeError(
                    f"El stream declara {registro['n']} mensajes para seq={seq_base} "
                    f"pero la expansion produjo {len(mensajes)}; regenerar el stream."
                )
            for desplazamiento, mensaje in enumerate(mensajes):
                seq = seq_base + desplazamiento
                if seq < desde_seq:
                    continue
                mensaje["metadata"]["extra"]["replay_run_id"] = replay_run_id
                mensaje["metadata"]["extra"]["replay_seq"] = seq
                yield seq, mensaje


def leer_checkpoint(path: Path, replay_run_id: str, stream_file: str) -> int:
    """Devuelve el `seq` desde el cual reanudar, validando que corresponda.

    Reanudar con un checkpoint de otra corrida o de otro stream produciria huecos
    silenciosos, que es exactamente el fallo que este diseno busca evitar. Ante
    cualquier discrepancia se falla en vez de continuar.
    """
    if not path.is_file():
        return 0
    datos = json.loads(path.read_text(encoding="utf-8"))
    if datos.get("replay_run_id") != replay_run_id:
        raise RuntimeError(
            f"El checkpoint pertenece a replay_run_id={datos.get('replay_run_id')!r} "
            f"y se solicito {replay_run_id!r}."
        )
    if datos.get("stream_file") != stream_file:
        raise RuntimeError(
            f"El checkpoint corresponde al stream {datos.get('stream_file')!r} "
            f"y se solicito {stream_file!r}."
        )
    return int(datos.get("next_seq", 0))


def escribir_checkpoint(path: Path, replay_run_id: str, stream_file: str, next_seq: int, bloques: int) -> None:
    """Persiste el avance confirmado tras cerrar un bloque reconciliado."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "replay_run_id": replay_run_id,
                "stream_file": stream_file,
                "next_seq": next_seq,
                "blocks_completed": bloques,
                "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def esperar_reconciliacion(
    reconciliar,
    replay_run_id: str,
    seq_desde: int,
    seq_hasta: int,
    esperadas: int,
    timeout: float,
    intervalo: float,
    dormir=time.sleep,
    reloj=time.monotonic,
) -> dict:
    """Consulta la base hasta que el bloque este completo o venza el plazo.

    La persistencia es asincronica respecto de la publicacion: el consumidor
    escribe por lotes en su propio hilo. Por eso un bloque no puede darse por
    cerrado en el instante en que el publicador termina de enviarlo.
    """
    limite = reloj() + timeout
    while True:
        resultado = reconciliar(replay_run_id, seq_desde, seq_hasta)
        if resultado["filas"] >= esperadas or reloj() >= limite:
            return resultado
        dormir(intervalo)


def publish_stream(
    stream_path: Path,
    replay_run_id: str,
    speed: float,
    max_delay: float,
    max_inflight_messages: int,
    block_size: int,
    checkpoint_path: Path | None = None,
    desde_seq: int = 0,
    reconciliar=None,
    reconcile_timeout: float = 120.0,
    reconcile_interval: float = 2.0,
    client_factory=mqtt.Client,
    dormir=time.sleep,
) -> dict:
    """Publica el stream por bloques, verificando cada bloque antes de avanzar.

    Este es el cambio de fondo respecto de `publish()`. Alli la unica garantia era
    el PUBACK del broker, que significa "el broker lo acepto" y no "alguien lo
    persistio": una corrida perdio 8.985 mensajes con `acknowledged` completo y
    todos los contadores propios en cero.

    Aqui la garantia la aporta `reconciliar`, que cuenta filas reales en la base
    para el rango de `replay_seq` del bloque. Si el conteo no cierra, la corrida se
    detiene en ese bloque y no tres horas despues.
    """
    client = client_factory(mqtt.CallbackAPIVersion.VERSION2)
    client.max_inflight_messages_set(max_inflight_messages)
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.loop_start()

    metrics = {
        "attempted": 0,
        "acknowledged": 0,
        "publish_rc_errors": 0,
        "blocks_completed": 0,
        "blocks_failed": 0,
        "resumed_from_seq": desde_seq,
        "first_seq": None,
        "last_seq": None,
    }
    bloques = []
    previous = None
    inflight: list = []
    bloque_inicio: int | None = None
    bloque_enviados = 0

    def esperar_confirmaciones() -> None:
        while inflight:
            inflight.pop(0).wait_for_publish()
            metrics["acknowledged"] += 1

    def cerrar_bloque(seq_desde: int, seq_hasta: int, enviados: int) -> None:
        esperar_confirmaciones()
        registro = {
            "seq_desde": seq_desde,
            "seq_hasta": seq_hasta,
            "publicados": enviados,
            "reconciliado": False,
        }
        if reconciliar is not None:
            conteo = esperar_reconciliacion(
                reconciliar,
                replay_run_id,
                seq_desde,
                seq_hasta,
                enviados,
                reconcile_timeout,
                reconcile_interval,
                dormir=dormir,
            )
            registro.update({"filas": conteo["filas"], "unicos": conteo["unicos"]})
            if conteo["filas"] != enviados or conteo["unicos"] != enviados:
                metrics["blocks_failed"] += 1
                bloques.append(registro)
                raise RuntimeError(
                    f"Bloque {seq_desde}-{seq_hasta} no reconcilia: se publicaron {enviados} "
                    f"mensajes y la base informa filas={conteo['filas']}, unicos={conteo['unicos']}."
                )
            registro["reconciliado"] = True
        bloques.append(registro)
        metrics["blocks_completed"] += 1
        if checkpoint_path is not None:
            escribir_checkpoint(
                checkpoint_path,
                replay_run_id,
                str(stream_path),
                seq_hasta + 1,
                metrics["blocks_completed"],
            )

    try:
        for seq, message in iter_stream_messages(stream_path, replay_run_id, desde_seq):
            if bloque_inicio is None:
                bloque_inicio = seq
            if metrics["first_seq"] is None:
                metrics["first_seq"] = seq

            current = parse_time(message["timestamp"])
            if previous is not None:
                dormir(min((current - previous).total_seconds() / speed, max_delay))
            message["metadata"]["extra"]["published_at_utc"] = datetime.now(timezone.utc).isoformat()

            result = client.publish(MQTT_REPLAY_TOPIC, json.dumps(message), qos=1)
            metrics["attempted"] += 1
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                metrics["publish_rc_errors"] += 1
                raise RuntimeError(f"MQTT rechazo el mensaje seq={seq} con rc={result.rc}")
            inflight.append(result)
            if len(inflight) >= max_inflight_messages:
                inflight.pop(0).wait_for_publish()
                metrics["acknowledged"] += 1

            previous = current
            metrics["last_seq"] = seq
            bloque_enviados += 1
            if bloque_enviados >= block_size:
                cerrar_bloque(bloque_inicio, seq, bloque_enviados)
                bloque_inicio = None
                bloque_enviados = 0

        if bloque_enviados:
            cerrar_bloque(bloque_inicio, metrics["last_seq"], bloque_enviados)
        else:
            esperar_confirmaciones()
    except Exception:
        print(json.dumps({"publish_metrics": metrics, "blocks": bloques}, sort_keys=True))
        raise
    finally:
        client.loop_stop()
        client.disconnect()

    metrics["blocks"] = bloques
    return metrics


def leer_manifiesto(stream_path: Path) -> dict:
    """Recupera el manifiesto del preparador si acompana al stream."""
    manifiesto_path = stream_path.with_suffix(stream_path.suffix + ".manifest.json")
    if not manifiesto_path.is_file():
        return {}
    return json.loads(manifiesto_path.read_text(encoding="utf-8"))


def ejecutar_desde_stream(args, parser) -> None:
    """Ruta incremental: publica un stream preparado por bloques verificables."""
    if not args.stream_file.is_file():
        parser.error(f"No existe el stream preparado: {args.stream_file}")

    manifiesto = leer_manifiesto(args.stream_file)
    desde_seq = 0
    if args.resume:
        desde_seq = leer_checkpoint(args.checkpoint_file, args.replay_run_id, str(args.stream_file))

    summary = {
        "mode": "publish" if args.publish else "dry_run",
        "path": "stream",
        "session_key": args.session_key,
        "replay_run_id": args.replay_run_id,
        "stream_file": str(args.stream_file),
        "source_samples": manifiesto.get("source_samples"),
        "expected_messages": manifiesto.get("expected_messages"),
        "block_size": args.block_size,
        "resume_from_seq": desde_seq,
        "max_inflight_messages": args.max_inflight_messages,
        "reconcile": bool(args.reconcile),
        "topic": MQTT_REPLAY_TOPIC,
    }
    print(json.dumps(summary, sort_keys=True))
    if not args.publish:
        return

    reconciliar = None
    if args.reconcile:
        # Import diferido: la ruta clasica y las pruebas locales no necesitan una
        # conexion a TimescaleDB para usar este modulo.
        from backend.db import contar_replay_persistido

        reconciliar = contar_replay_persistido

    metrics = publish_stream(
        stream_path=args.stream_file,
        replay_run_id=args.replay_run_id,
        speed=args.speed,
        max_delay=args.max_delay_seconds,
        max_inflight_messages=args.max_inflight_messages,
        block_size=args.block_size,
        checkpoint_path=args.checkpoint_file,
        desde_seq=desde_seq,
        reconciliar=reconciliar,
        reconcile_timeout=args.reconcile_timeout_seconds,
        reconcile_interval=args.reconcile_interval_seconds,
    )
    print(json.dumps({"publish_metrics": metrics}, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-key", type=int, required=True)
    parser.add_argument("--drivers", required=True, help="Lista CSV de numeros o 'all'.")
    parser.add_argument("--start", help="UTC ISO 8601 inclusivo; omitir para inicio disponible.")
    parser.add_argument("--end", help="UTC ISO 8601 exclusivo; omitir para fin disponible.")
    parser.add_argument("--endpoints", default="car_data,location", help="Subset CSV: car_data,location.")
    parser.add_argument("--replay-run-id", required=True, help="Identificador legible y estable de esta ejecucion.")
    parser.add_argument("--speed", type=float, default=20.0)
    parser.add_argument("--max-delay-seconds", type=float, default=0.25)
    parser.add_argument(
        "--max-inflight-messages",
        type=int,
        default=1,
        help="Maximo de publicaciones MQTT QoS 1 pendientes de confirmacion.",
    )
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--confirm-publish", help="Debe ser exactamente REPLAY_OPENF1.")
    parser.add_argument(
        "--stream-file",
        type=Path,
        help=(
            "JSONL generado por scripts/prepare_replay_stream.py. Activa la ruta "
            "incremental por bloques, sin materializar muestras ni mensajes en memoria. "
            "Es obligatoria para volumenes grandes; sin ella se usa la ruta clasica, "
            "apta solo para ventanas cortas."
        ),
    )
    parser.add_argument("--block-size", type=int, default=50_000, help="Mensajes por bloque verificable.")
    parser.add_argument("--checkpoint-file", type=Path, help="Ruta donde registrar el avance confirmado.")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reanuda desde el checkpoint existente en lugar de empezar en cero.",
    )
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help=(
            "Verifica cada bloque contando filas reales en TimescaleDB. Sin esta "
            "opcion el checkpoint solo refleja confirmaciones del broker, que no "
            "prueban persistencia."
        ),
    )
    parser.add_argument("--reconcile-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--reconcile-interval-seconds", type=float, default=2.0)
    args = parser.parse_args()
    if args.speed <= 0 or args.max_delay_seconds < 0 or args.max_inflight_messages <= 0:
        parser.error("--speed y --max-inflight-messages deben ser positivos; --max-delay-seconds no negativo.")
    if args.publish and args.confirm_publish != "REPLAY_OPENF1":
        parser.error("Publicar exige --confirm-publish REPLAY_OPENF1.")
    if args.start and args.end and parse_time(args.start) >= parse_time(args.end):
        parser.error("--start debe ser anterior a --end.")
    if args.block_size <= 0:
        parser.error("--block-size debe ser positivo.")
    if args.stream_file is None and (args.resume or args.reconcile or args.checkpoint_file):
        parser.error("--resume, --reconcile y --checkpoint-file requieren --stream-file.")
    if args.resume and args.checkpoint_file is None:
        parser.error("--resume requiere --checkpoint-file.")
    endpoints = args.endpoints.split(",")
    if not endpoints or not set(endpoints) <= SUPPORTED_ENDPOINTS:
        parser.error("--endpoints admite solo car_data y location.")

    if args.stream_file is not None:
        ejecutar_desde_stream(args, parser)
        return

    session_path = DATA_ROOT / str(args.session_key)
    drivers = parse_drivers(args.drivers, session_path)
    samples = collect_samples(session_path, drivers, endpoints, parse_time(args.start), parse_time(args.end))
    messages = build_messages(samples)
    for seq, message in enumerate(messages):
        message["metadata"]["extra"]["replay_run_id"] = args.replay_run_id
        # La ruta clasica tambien numera sus mensajes para que las filas que
        # produzca sean idempotentes y reconciliables con el mismo criterio que la
        # ruta incremental. La numeracion es local a esta corrida.
        message["metadata"]["extra"]["replay_seq"] = seq
    summary = {
        "mode": "publish" if args.publish else "dry_run",
        "path": "memoria",
        "session_key": args.session_key,
        "replay_run_id": args.replay_run_id,
        "drivers": [number for number, _ in drivers],
        "endpoints": endpoints,
        "source_samples": len(samples),
        "mqtt_messages": len(messages),
        "max_inflight_messages": args.max_inflight_messages,
        "historical_start": messages[0]["timestamp"] if messages else None,
        "historical_end": messages[-1]["timestamp"] if messages else None,
        "topic": MQTT_REPLAY_TOPIC,
    }
    print(json.dumps(summary, sort_keys=True))
    if args.publish:
        publish_metrics = publish(messages, args.speed, args.max_delay_seconds, args.max_inflight_messages)
        print(json.dumps({"publish_metrics": publish_metrics}, sort_keys=True))
        print(f"published_messages={len(messages)}")


if __name__ == "__main__":
    main()
