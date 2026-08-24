"""Valida y registra la trazabilidad de un paquete local Nivel B."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.session_processor import register_package_validation


def main() -> None:
    """Registra una validacion idempotente sin importar telemetria aun."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package_path", type=Path, help="Directorio local de una sesion Nivel B.")
    args = parser.parse_args()
    result = register_package_validation(args.package_path)
    run = result["run"]
    print(
        json.dumps(
            {
                "status": result["status"],
                "run_id": run["run_id"],
                "session_key": result["inventory"]["session_key"],
                "package_fingerprint": result["inventory"]["package_fingerprint"],
                "warnings": result["inventory"]["warnings"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
