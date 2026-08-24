"""Importa el contexto disponible de un paquete Nivel B ya validado."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.session_processor import import_validated_package


def main() -> None:
    """Importa contexto sin publicar MQTT ni reproducir telemetria detallada."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package_path", type=Path, help="Directorio local de una sesion Nivel B.")
    args = parser.parse_args()
    result = import_validated_package(args.package_path)
    print(json.dumps(result, default=str, sort_keys=True))


if __name__ == "__main__":
    main()
