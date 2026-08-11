"""Amplia el analisis CAN RAV4 como anexo extraordinario del Dia 16.

Selecciona rutas distintas de TOYOTA_RAV4_TSS2, descarga solo las muestras que
faltan y resume evidencia estructural para brake_pressed, gas_pressed,
steer_angle y candidatos de gas_pedal. Los logs y resultados quedan en datasets/
y no forman parte del control de versiones.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlretrieve

import zstandard as zstd


ROOT = Path(__file__).resolve().parents[1]
PLATFORM = "TOYOTA_RAV4_TSS2"
MANIFEST_PATH = ROOT / "datasets" / "commaCarSegments" / "raw" / "database.json"
SAMPLES_PATH = ROOT / "datasets" / "commaCarSegments" / "raw" / PLATFORM
SUMMARY_PATH = (
    ROOT
    / "datasets"
    / "commaCarSegments"
    / "summaries"
    / PLATFORM
    / "day16_expanded_30"
)
OPENPILOT_PATH = ROOT / "external" / "openpilot"
OPENDBC_PATH = ROOT / "datasets" / "openDBC" / "raw" / "opendbc"
DATASET_BASE_URL = "https://huggingface.co/datasets/commaai/commaCarSegments/resolve/main/segments"

# Las cinco muestras iniciales se eligieron antes del anexo. Se preservan para
# ampliar evidencia, no para reemplazar ni reescribir el analisis anterior.
EXISTING_SAMPLES = (
    ("sample_01", "d0e756c10c7adf7a/00000004--a4e9cb8af7/36/s"),
    ("sample_02", "df5ad9d9ae9fd6cd/00000470--cb630a6b9d/46/s"),
    ("sample_03", "ccc74bf50752879f/0000039b--e0c51bb840/5/s"),
    ("sample_04", "a7ffb3ced3b2bb43/0000006e--68ba448e82/3/s"),
    ("sample_05", "d9cf33d2c1af7eae/00000362--6d3a6f4834/10/s"),
)

# El benchmark inicial verifico descarga, lectura y analisis sobre cinco rutas
# nuevas. Se conserva como evidencia tecnica y las muestras posteriores se
# distribuyen entre dispositivos distintos antes de repetir uno.
BENCHMARK_SAMPLES = (
    ("sample_06", "00261c4594824c45/0000016f--c246d21f63/8/s"),
    ("sample_07", "00261c4594824c45/0000017c--877c9274bb/4/s"),
    ("sample_08", "00261c4594824c45/000001ab--d714c6caff/3/s"),
    ("sample_09", "00261c4594824c45/000001ad--30f6fbd1b3/19/s"),
    ("sample_10", "00261c4594824c45/000001cc--797b7ef373/0/s"),
)

CAN_ID_STEER_ANGLE = 37
CAN_ID_BRAKE_MODULE = 550
CAN_ID_PCM_CRUISE = 466
CAN_ID_GAS_PEDAL_PRIMARY = 881
CAN_ID_GAS_PEDAL_ALTERNATIVE = 705


def route_key(reference: str) -> str:
    """Devuelve dispositivo/ruta para evitar cortes repetidos de un viaje."""
    device_id, route_id, *_ = reference.split("/")
    return f"{device_id}/{route_id}"


def local_rlog_path(sample_name: str) -> Path:
    """Devuelve la ubicacion local prevista para un segmento seleccionado."""
    return SAMPLES_PATH / sample_name / "rlog.zst"


def build_selection(new_count: int) -> list[dict[str, str]]:
    """Selecciona rutas sin elegir por resultado y diversifica dispositivos."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    references = sorted(manifest[PLATFORM])
    selected = [
        {
            "sample_name": sample_name,
            "reference": reference,
            "route_key": route_key(reference),
        }
        for sample_name, reference in EXISTING_SAMPLES
    ]
    for sample_name, reference in BENCHMARK_SAMPLES[:new_count]:
        selected.append(
            {
                "sample_name": sample_name,
                "reference": reference,
                "route_key": route_key(reference),
            }
        )
    used_routes = {item["route_key"] for item in selected}
    missing_count = new_count - min(new_count, len(BENCHMARK_SAMPLES))
    candidates_by_device: dict[str, list[str]] = {}

    for reference in references:
        candidate_route = route_key(reference)
        if candidate_route in used_routes:
            continue
        device_id = reference.split("/", 1)[0]
        candidates_by_device.setdefault(device_id, []).append(reference)

    device_ids = sorted(candidates_by_device)
    candidate_index = {device_id: 0 for device_id in device_ids}

    while missing_count:
        added_this_round = 0
        for device_id in device_ids:
            entries = candidates_by_device[device_id]
            index = candidate_index[device_id]
            while index < len(entries) and route_key(entries[index]) in used_routes:
                index += 1
            candidate_index[device_id] = index
            if index == len(entries):
                continue

            reference = entries[index]
            candidate_index[device_id] += 1
            sample_index = len(selected) + 1
            selected.append(
                {
                    "sample_name": f"sample_{sample_index:02d}",
                    "reference": reference,
                    "route_key": route_key(reference),
                }
            )
            used_routes.add(route_key(reference))
            missing_count -= 1
            added_this_round += 1
            if not missing_count:
                break

        if not added_this_round:
            raise RuntimeError("No se encontraron suficientes rutas RAV4 distintas.")

    if len(selected) != len(EXISTING_SAMPLES) + new_count:
        raise RuntimeError("No se encontraron suficientes rutas RAV4 distintas.")

    return selected


def download_if_missing(sample: dict[str, str]) -> tuple[int, bool, float]:
    """Descarga un rlog.zst faltante y mide la operacion de disponibilidad."""
    destination = local_rlog_path(sample["sample_name"])
    started = time.perf_counter()
    downloaded = False
    if not destination.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        reference_without_suffix = sample["reference"].removesuffix("/s")
        urlretrieve(f"{DATASET_BASE_URL}/{reference_without_suffix}/rlog.zst", destination)
        downloaded = True
    return destination.stat().st_size, downloaded, time.perf_counter() - started


def raw_gas_pedal(payload: bytes, can_id: int) -> int | None:
    """Extrae los campos de ocho bits evaluados como candidatos de gas_pedal."""
    if can_id == CAN_ID_GAS_PEDAL_PRIMARY and len(payload) > 1:
        return payload[1]
    if can_id == CAN_ID_GAS_PEDAL_ALTERNATIVE and len(payload) > 6:
        return payload[6]
    return None


def analyze_rlog(sample: dict[str, str], capnp_log) -> dict:
    """Resume un rlog sin guardar frames individuales ni exponerlos en Git."""
    rlog_path = local_rlog_path(sample["sample_name"])
    started = time.perf_counter()
    compressed = rlog_path.read_bytes()
    data = zstd.ZstdDecompressor().decompress(compressed)

    event_counts: Counter[str] = Counter()
    address_counts: Counter[int] = Counter()
    source_counts: Counter[int] = Counter()
    payloads_by_id: dict[int, Counter[bytes]] = {
        CAN_ID_STEER_ANGLE: Counter(),
        CAN_ID_BRAKE_MODULE: Counter(),
        CAN_ID_PCM_CRUISE: Counter(),
        CAN_ID_GAS_PEDAL_PRIMARY: Counter(),
        CAN_ID_GAS_PEDAL_ALTERNATIVE: Counter(),
    }
    times_by_id: dict[int, list[int]] = {
        CAN_ID_STEER_ANGLE: [],
        CAN_ID_BRAKE_MODULE: [],
        CAN_ID_PCM_CRUISE: [],
    }
    brake_states: Counter[int] = Counter()
    gas_released_states: Counter[int] = Counter()
    gas_raw_values: dict[int, Counter[int]] = {
        CAN_ID_GAS_PEDAL_PRIMARY: Counter(),
        CAN_ID_GAS_PEDAL_ALTERNATIVE: Counter(),
    }
    can_frames = 0

    for event in capnp_log.Event.read_multiple_bytes(data):
        event_type = event.which()
        event_counts[event_type] += 1
        if event_type != "can":
            continue

        seen_target_ids: set[int] = set()
        for frame in event.can:
            can_frames += 1
            can_id = frame.address
            payload = bytes(frame.dat)
            address_counts[can_id] += 1
            source_counts[frame.src] += 1

            if can_id in payloads_by_id:
                payloads_by_id[can_id][payload] += 1
                seen_target_ids.add(can_id)

            if can_id == CAN_ID_BRAKE_MODULE and len(payload) > 4:
                brake_states[(payload[4] >> 5) & 1] += 1
            elif can_id == CAN_ID_PCM_CRUISE and payload:
                gas_released_states[(payload[0] >> 4) & 1] += 1
            elif can_id in gas_raw_values:
                raw_value = raw_gas_pedal(payload, can_id)
                if raw_value is not None:
                    gas_raw_values[can_id][raw_value] += 1

        for can_id in seen_target_ids:
            if can_id in times_by_id:
                times_by_id[can_id].append(event.logMonoTime)

    periodicity_ms = {}
    for can_id, timestamps in times_by_id.items():
        deltas = [later - earlier for earlier, later in zip(timestamps, timestamps[1:])]
        periodicity_ms[str(can_id)] = {
            "events": len(timestamps),
            "mean": round(statistics.mean(deltas) / 1_000_000, 6) if deltas else None,
            "median": round(statistics.median(deltas) / 1_000_000, 6) if deltas else None,
        }

    gas_candidates = {}
    for can_id, values in gas_raw_values.items():
        gas_candidates[str(can_id)] = {
            "frames": sum(values.values()),
            "unique_raw_values": len(values),
            "raw_min": min(values) if values else None,
            "raw_max": max(values) if values else None,
        }

    return {
        "sample_name": sample["sample_name"],
        "route_key": sample["route_key"],
        "reference": sample["reference"],
        "compressed_bytes": len(compressed),
        "decompressed_bytes": len(data),
        "processing_seconds": round(time.perf_counter() - started, 6),
        "event_counts": dict(event_counts),
        "can_frames": can_frames,
        "unique_can_ids": len(address_counts),
        "top_can_ids": address_counts.most_common(15),
        "top_sources": source_counts.most_common(),
        "target_payload_counts": {
            str(can_id): {
                "frames": sum(payloads.values()),
                "unique_payloads": len(payloads),
            }
            for can_id, payloads in payloads_by_id.items()
        },
        "brake_pressed_states": dict(brake_states),
        "gas_released_states": dict(gas_released_states),
        "periodicity_ms": periodicity_ms,
        "gas_pedal_candidates": gas_candidates,
    }


def aggregate_results(results: list[dict]) -> dict:
    """Construye resultados agregados sin publicar rutas o dispositivos."""
    total_events: Counter[str] = Counter()
    brake_states: Counter[int] = Counter()
    gas_states: Counter[int] = Counter()
    target_presence: Counter[str] = Counter()
    target_frame_counts: Counter[str] = Counter()
    gas_candidate_ranges: dict[str, list[int]] = {
        str(CAN_ID_GAS_PEDAL_PRIMARY): [],
        str(CAN_ID_GAS_PEDAL_ALTERNATIVE): [],
    }
    gas_candidate_frames: Counter[str] = Counter()

    for result in results:
        total_events.update(result["event_counts"])
        brake_states.update({int(key): value for key, value in result["brake_pressed_states"].items()})
        gas_states.update({int(key): value for key, value in result["gas_released_states"].items()})
        for can_id, detail in result["target_payload_counts"].items():
            if detail["frames"]:
                target_presence[can_id] += 1
                target_frame_counts[can_id] += detail["frames"]
        for can_id, detail in result["gas_pedal_candidates"].items():
            if detail["raw_min"] is not None:
                gas_candidate_ranges[can_id].extend([detail["raw_min"], detail["raw_max"]])
                gas_candidate_frames[can_id] += detail["frames"]

    return {
        "platform": PLATFORM,
        "samples_processed": len(results),
        "unique_routes_processed": len({result["route_key"] for result in results}),
        "unique_devices_processed": len(
            {result["route_key"].split("/", 1)[0] for result in results}
        ),
        "total_compressed_bytes": sum(result["compressed_bytes"] for result in results),
        "total_decompressed_bytes": sum(result["decompressed_bytes"] for result in results),
        "total_processing_seconds": round(sum(result["processing_seconds"] for result in results), 6),
        "total_can_frames": sum(result["can_frames"] for result in results),
        "event_counts": dict(total_events),
        "target_id_presence_by_sample": dict(target_presence),
        "target_id_frame_counts": dict(target_frame_counts),
        "brake_pressed_states": dict(brake_states),
        "gas_released_states": dict(gas_states),
        "gas_pedal_candidate_ranges": {
            can_id: {
                "raw_min": min(values) if values else None,
                "raw_max": max(values) if values else None,
            }
            for can_id, values in gas_candidate_ranges.items()
        },
        "gas_pedal_candidate_frame_counts": dict(gas_candidate_frames),
    }


def main() -> None:
    """Descarga y analiza una cantidad indicada de nuevas muestras RAV4."""
    parser = argparse.ArgumentParser(
        description="Amplia el analisis RAV4 del Dia 16 sin procesar el corpus completo."
    )
    parser.add_argument(
        "--new-count",
        type=int,
        default=5,
        help="Cantidad de muestras nuevas a incluir ademas de las cinco existentes.",
    )
    parser.add_argument(
        "--run-label",
        default="",
        help="Etiqueta ASCII opcional para no sobrescribir otro resumen del mismo lote.",
    )
    args = parser.parse_args()

    if args.new_count < 0 or args.new_count > 25:
        raise ValueError("new-count debe estar entre 0 y 25.")
    if not MANIFEST_PATH.is_file():
        raise FileNotFoundError(f"No se encontro el manifiesto: {MANIFEST_PATH}")

    sys.path.extend([str(OPENPILOT_PATH), str(OPENDBC_PATH)])
    from openpilot.cereal import log as capnp_log

    if args.run_label and not args.run_label.replace("_", "").isalnum():
        raise ValueError("run-label solo admite letras, numeros y guiones bajos.")

    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()
    selection = build_selection(args.new_count)
    SUMMARY_PATH.mkdir(parents=True, exist_ok=True)
    download_details = []
    for sample in selection:
        compressed_bytes, downloaded, availability_seconds = download_if_missing(sample)
        download_details.append(
            {
                "sample_name": sample["sample_name"],
                "downloaded": downloaded,
                "availability_seconds": round(availability_seconds, 6),
            }
        )
        print(
            f"ready={sample['sample_name']} compressed_bytes={compressed_bytes} "
            f"downloaded={downloaded} availability_seconds={availability_seconds:.6f}"
        )

    results = []
    for sample in selection:
        result = analyze_rlog(sample, capnp_log)
        results.append(result)
        print(
            f"processed={sample['sample_name']} can_frames={result['can_frames']} "
            f"seconds={result['processing_seconds']}"
        )

    finished_at = datetime.now(timezone.utc)
    output = {
        "run": {
            "started_at_utc": started_at.isoformat(),
            "finished_at_utc": finished_at.isoformat(),
            "total_elapsed_seconds": round(time.perf_counter() - started, 6),
            "downloaded_samples": sum(item["downloaded"] for item in download_details),
            "download_availability_seconds": round(
                sum(item["availability_seconds"] for item in download_details), 6
            ),
            "download_details": download_details,
        },
        "selection": selection,
        "aggregate": aggregate_results(results),
        "samples": results,
    }
    suffix = f"_{args.run_label}" if args.run_label else ""
    output_path = SUMMARY_PATH / f"summary_{len(selection):02d}_segments{suffix}.json"
    output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"summary_written={output_path}")


if __name__ == "__main__":
    main()
