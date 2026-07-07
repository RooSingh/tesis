"""Initial generator configuration.

This module defines the first MVP signal catalog for the telemetry generator.
At this stage, the goal is not to simulate every possible vehicle variable,
but to establish a small, meaningful, and technically justified set of
signals that can be emitted by the first version of the system.

Important note:
- the periods defined here are initial working values,
- they are not claimed as exact OEM CAN cycle times,
- and they remain open to revision after deeper CAN analysis or broader
  multi-segment validation.

Why this file matters:
- it centralizes what the generator emits,
- it gives each signal a unit and an emission period,
- and it preserves traceability with the CAN/DBC analysis already performed.
"""

from __future__ import annotations


# The initial MVP focuses on:
# - vehicle speed and wheel speeds,
# - steering input,
# - basic vehicle kinematics,
# - and two basic driver-input variables: brake and throttle.
#
# The chosen periods are provisional but grounded in the work already done:
# - local evidence from the sample segment,
# - preliminary semantic mapping through openDBC,
# - and bibliography-based frequency bands.
#
# Confidence is not identical for all signals:
# - wheel speeds, steer angle, speed, and kinematics have stronger support,
# - brake_pressed and gas_pedal are included in the MVP because they are
#   highly valuable for driving analysis, but their direct semantic closure on
#   the current sample is still less complete than the core kinematic set.

MVP_SIGNALS = [
    {
        "signal_name": "wheel_speed_fl",
        "unit": "km/h",
        "period_ms": 10,
        "source_type": "can_simulated",
        "required": True,
        "can_id": 170,
        "notes": "Front-left wheel speed. High-confidence high-frequency dynamic signal.",
    },
    {
        "signal_name": "wheel_speed_fr",
        "unit": "km/h",
        "period_ms": 10,
        "source_type": "can_simulated",
        "required": True,
        "can_id": 170,
        "notes": "Front-right wheel speed. High-confidence high-frequency dynamic signal.",
    },
    {
        "signal_name": "wheel_speed_rl",
        "unit": "km/h",
        "period_ms": 10,
        "source_type": "can_simulated",
        "required": True,
        "can_id": 170,
        "notes": "Rear-left wheel speed. High-confidence high-frequency dynamic signal.",
    },
    {
        "signal_name": "wheel_speed_rr",
        "unit": "km/h",
        "period_ms": 10,
        "source_type": "can_simulated",
        "required": True,
        "can_id": 170,
        "notes": "Rear-right wheel speed. High-confidence high-frequency dynamic signal.",
    },
    {
        "signal_name": "steer_angle",
        "unit": "deg",
        "period_ms": 10,
        "source_type": "can_simulated",
        "required": True,
        "can_id": 37,
        "notes": "Steering angle from steering angle sensor family. Strong local and DBC support.",
    },
    {
        "signal_name": "speed",
        "unit": "km/h",
        "period_ms": 20,
        "source_type": "can_simulated",
        "required": True,
        "can_id": 180,
        "notes": "Vehicle speed signal with medium temporal band. Strong local and DBC support.",
    },
    {
        "signal_name": "accel_x",
        "unit": "m/s2",
        "period_ms": 20,
        "source_type": "can_simulated",
        "required": True,
        "can_id": 36,
        "notes": "Longitudinal acceleration from kinematics family. Good support, period remains revisable.",
    },
    {
        "signal_name": "accel_y",
        "unit": "m/s2",
        "period_ms": 20,
        "source_type": "can_simulated",
        "required": True,
        "can_id": 36,
        "notes": "Lateral acceleration from kinematics family. Good support, period remains revisable.",
    },
    {
        "signal_name": "yaw_rate",
        "unit": "deg/s",
        "period_ms": 20,
        "source_type": "can_simulated",
        "required": True,
        "can_id": 36,
        "notes": "Yaw-rate signal from kinematics family. Good support, period remains revisable.",
    },
    {
        "signal_name": "brake_pressed",
        "unit": "bool",
        "period_ms": 20,
        "source_type": "can_simulated",
        "required": True,
        "can_id": 550,
        "notes": "Binary brake state included in the MVP for driver-input analysis. Semantic linkage remains more tentative than core kinematic signals.",
    },
    {
        "signal_name": "gas_pedal",
        "unit": "%",
        "period_ms": 20,
        "source_type": "can_simulated",
        "required": True,
        "can_id": 705,
        "notes": "Throttle / accelerator pedal position signal. Included for analysis value, pending stronger direct closure on the sample.",
    },
]
