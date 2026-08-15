"""Aplica una migracion SQL versionada mediante la configuracion local del backend."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.db import obtener_conexion


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("migration", type=Path, help="Ruta de migracion relativa a la raiz.")
    args = parser.parse_args()
    migration = args.migration if args.migration.is_absolute() else ROOT / args.migration
    if not migration.is_file():
        parser.error(f"No existe la migracion: {migration}")
    sql = migration.read_text(encoding="utf-8")
    with obtener_conexion() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql)
    print(f"migration_applied={migration.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
