"""Modelos internos del backend.

Este modulo define las estructuras de datos principales que el backend espera
recibir o manejar. En esta primera etapa, el foco esta en el mensaje
telemetrico que llega desde el generador por MQTT.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class TelemetryMetadata(BaseModel):
    """Metadatos auxiliares del mensaje telemetrico.

    En esta etapa se mantienen flexibles porque distintas fuentes futuras
    (simulacion, CAN real, adaptadores de equipo, senales derivadas) pueden
    requerir campos distintos.
    """

    can_id: int | None = None
    src: int | None = None
    warning: str | None = None
    reference_type: str | None = None
    reference_id: str | None = None
    extra: dict[str, Any] | None = None


class TelemetryMessage(BaseModel):
    """Modelo base del mensaje telemetrico interno del sistema."""

    timestamp: str
    vehicle_id: str
    driver_id: str
    session_id: str
    lap_id: str | None

    source_type: str
    signal_name: str
    value: Any
    unit: str
    quality_flag: str

    track_segment_id: str | None = None
    sector_id: str | None = None
    curve_id: str | None = None

    metadata: TelemetryMetadata
