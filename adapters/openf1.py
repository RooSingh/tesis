"""Construye mensajes MQTT de replay historico desde respuestas crudas OpenF1."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


SOURCE_TYPE = "openf1_historical_replay"
QUALITY_FLAG = "observed_openf1"
CAR_DATA_SIGNALS = {
    "speed": ("speed", "km/h"),
    "throttle": ("throttle_position", "%"),
    "brake": ("brake_applied", "bool"),
    "rpm": ("engine_speed", "rpm"),
    "n_gear": ("gear_selected", "gear"),
    "drs": ("drs_state_code", "openf1_code"),
}
LOCATION_SIGNALS = {
    "x": ("track_position_x", "openf1_coordinate"),
    "y": ("track_position_y", "openf1_coordinate"),
    "z": ("track_position_z", "openf1_coordinate"),
}


def messages_from_openf1_sample(
    sample: dict[str, Any],
    endpoint: str,
    source_url: str,
    raw_payload_path: str,
    published_at_utc: str | None = None,
) -> list[dict[str, Any]]:
    """Convierte una muestra car_data/location en mensajes canonicos por senal."""
    if endpoint == "car_data":
        signal_map = CAR_DATA_SIGNALS
    elif endpoint == "location":
        signal_map = LOCATION_SIGNALS
    else:
        raise ValueError(f"Endpoint temporal no admitido: {endpoint}")

    required = ("date", "meeting_key", "session_key", "driver_number")
    missing = [field for field in required if sample.get(field) is None]
    if missing:
        raise ValueError(f"Muestra OpenF1 incompleta: faltan {', '.join(missing)}.")

    meeting_key = sample["meeting_key"]
    session_key = sample["session_key"]
    driver_number = sample["driver_number"]
    published_at_utc = published_at_utc or datetime.now(timezone.utc).isoformat()
    common = {
        "timestamp": sample["date"],
        "vehicle_id": f"openf1:session:{session_key}:driver:{driver_number}",
        "driver_id": f"openf1:driver:{driver_number}",
        "session_id": f"openf1:session:{session_key}",
        "lap_id": None,
        "source_type": SOURCE_TYPE,
        "quality_flag": QUALITY_FLAG,
        "track_segment_id": None,
        "sector_id": None,
        "curve_id": None,
    }
    messages = []
    for raw_field, (signal_name, unit) in signal_map.items():
        if raw_field not in sample:
            continue
        value = bool(sample[raw_field]) if raw_field == "brake" else sample[raw_field]
        messages.append(
            {
                **common,
                "signal_name": signal_name,
                "value": value,
                "unit": unit,
                "metadata": {
                    "can_id": None,
                    "src": None,
                    "reference_type": "openf1",
                    "reference_id": f"meeting:{meeting_key}/session:{session_key}/driver:{driver_number}",
                    "extra": {
                        "replay_mode": True,
                        "source_endpoint": endpoint,
                        "raw_field": raw_field,
                        "meeting_key": meeting_key,
                        "session_key": session_key,
                        "driver_number": driver_number,
                        "source_url": source_url,
                        "raw_payload_path": raw_payload_path,
                        "source_sample_rate_hz": 3.7,
                        "published_at_utc": published_at_utc,
                        "transformation": "identity",
                    },
                },
            }
        )
    return messages
