"""Exportacion selectiva de Spa y restauracion exclusivamente en una DB vacia."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from datetime import datetime, timezone

import psycopg
from psycopg import sql


SESSION = "f1_25:session:3731090176871608020"
SOURCE = "f1_25_udp_simulation"
VEHICLE = SESSION + ":car:19"
EXPECTED_ROWS = 5641702
RAW = "20260904_2136_spa_carrera-2_dos-conductores.f1raw"
RAW_HASH = "1498c22eef8dc001dab6e79afef94b279331099e83f1ff3d3017923ef04a4e0a"
COLUMNS = (
    "timestamp", "vehicle_id", "driver_id", "session_id", "lap_id",
    "signal_name", "value_numeric", "value_boolean", "value_text", "unit",
    "quality_flag", "can_id", "src", "source_type", "track_segment_id",
    "sector_id", "curve_id", "metadata", "replay_run_id", "replay_seq",
    "desplazamiento_captura_us",
)
PREDICATE = """
source_type = %s AND session_id = %s AND vehicle_id = %s
AND replay_run_id IS NULL
AND timestamp >= TIMESTAMPTZ '2026-09-05 00:00:00+00'
AND timestamp < TIMESTAMPTZ '2026-09-06 00:00:00+00'
"""
PARAMS = (SOURCE, SESSION, VEHICLE)
CATALOG_SCHEMA = """
CREATE TABLE sesiones_catalogo (
    session_id text PRIMARY KEY, source_type text, filas bigint,
    senales integer, vehiculos integer, desde timestamptz, hasta timestamptz,
    actualizado_utc timestamptz NOT NULL
);
CREATE TABLE replay_runs_catalogo (
    replay_run_id text PRIMARY KEY, session_id text, source_type text,
    desde timestamptz, hasta timestamptz, mensajes bigint,
    actualizado_utc timestamptz NOT NULL
);
"""


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def inventory(cursor):
    cursor.execute("""
        SELECT signal_name, count(*), min(timestamp), max(timestamp),
               count(value_numeric), count(value_boolean), count(value_text),
               count(metadata), count(replay_run_id), count(replay_seq),
               count(desplazamiento_captura_us)
        FROM telemetry_messages WHERE """ + PREDICATE + " GROUP BY signal_name ORDER BY signal_name", PARAMS)
    return [[v.isoformat() if isinstance(v, datetime) else v for v in row]
            for row in cursor.fetchall()]


def phase_summary(cursor):
    cursor.execute("""
        SELECT value_numeric, metadata->'extra'->>'session_time_s',
               COALESCE(desplazamiento_captura_us,
                 (metadata->'extra'->>'desplazamiento_captura_us')::bigint)
        FROM telemetry_messages WHERE """ + PREDICATE + """
          AND signal_name = 'lap_number' ORDER BY 3
    """, PARAMS)
    phases = []
    previous = None
    for lap, seconds, offset in cursor:
        if seconds is None or offset is None:
            raise ValueError("Falta procedencia temporal en lap_number")
        seconds = float(seconds)
        if previous is None or seconds < previous:
            phases.append({"from_capture_us": offset, "rows": 0, "laps": []})
        phase = phases[-1]
        phase["to_capture_us"] = offset
        phase["rows"] += 1
        if int(lap) not in phase["laps"]:
            phase["laps"].append(int(lap))
        previous = seconds
    return phases


def export_package(output):
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from backend import config

    output = output.resolve()
    if output.exists():
        raise ValueError("El destino ya existe; no se sobrescribe")
    raw_source = root / "datasets" / "f1_25" / "capturas" / RAW
    if digest(raw_source) != RAW_HASH:
        raise ValueError("El hash del crudo no coincide con el respaldo auditado")
    print("Crudo original verificado. Consultando instantanea READ ONLY...", flush=True)
    output.mkdir(parents=True, exist_ok=False)
    manifest = {"format": "spa-copy-csv-gzip-v1", "session_id": SESSION,
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "columns": list(COLUMNS), "predicate": PREDICATE,
                "parameters": list(PARAMS), "files": {}}
    options = ("-c default_transaction_read_only=on -c statement_timeout=900000 "
               "-c search_path=public,pg_catalog "
               "-c lock_timeout=2000 -c timezone=UTC -c max_parallel_workers_per_gather=0")
    with psycopg.connect(host=config.DB_HOST, port=config.DB_PORT,
                        dbname=config.DB_NAME, user=config.DB_USER,
                        password=config.DB_PASSWORD, options=options) as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cur.execute("SELECT current_setting('server_version'), "
                        "(SELECT extversion FROM pg_extension WHERE extname='timescaledb'), "
                        "transaction_timestamp(), pg_current_snapshot()::text")
            pg, timescale, started, snapshot = cur.fetchone()
            manifest.update(postgresql=pg, timescaledb=timescale,
                            snapshot_utc=started.isoformat(), snapshot=snapshot)
            cur.execute("SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema='public' AND table_name='telemetry_messages' "
                        "ORDER BY ordinal_position")
            actual = [r[0] for r in cur.fetchall()]
            if set(actual) != set(COLUMNS):
                raise ValueError("Cambio de esquema: revisar columnas antes de exportar")
            cur.execute("SELECT 1 FROM telemetry_messages WHERE source_type=%s "
                        "AND session_id=%s AND replay_run_id IS NULL AND NOT "
                        "(vehicle_id=%s AND timestamp >= '2026-09-05 00:00+00' "
                        "AND timestamp < '2026-09-06 00:00+00') LIMIT 1", PARAMS)
            if cur.fetchone():
                raise ValueError("Hay filas originales fuera del alcance auditado")
            manifest["signals"] = inventory(cur)
            rows = sum(r[1] for r in manifest["signals"])
            if rows != EXPECTED_ROWS or len(manifest["signals"]) != 113:
                raise ValueError(f"Inventario inesperado: {rows} filas")
            manifest["rows"] = rows
            manifest["phases"] = phase_summary(cur)
            if len(manifest["phases"]) != 3:
                raise ValueError("El original no conserva las tres fases esperadas")
            print(f"Confirmadas {rows} filas, 113 senales y 3 fases. Exportando...", flush=True)
            columns = sql.SQL(", ").join(map(sql.Identifier, COLUMNS))
            query = sql.SQL("COPY (SELECT {} FROM telemetry_messages WHERE ").format(columns)
            query += sql.SQL(PREDICATE + ") TO STDOUT WITH (FORMAT CSV, HEADER TRUE, ENCODING 'UTF8')")
            raw_digest = hashlib.sha256()
            raw_bytes = 0
            partial = output / "telemetry.csv.gz.partial"
            with gzip.open(partial, "wb", compresslevel=6) as dest:
                with cur.copy(query, PARAMS) as copy:
                    for block in copy:
                        raw_digest.update(block)
                        raw_bytes += len(block)
                        dest.write(block)
            partial.rename(output / "telemetry.csv.gz")
            manifest["csv_uncompressed_bytes"] = raw_bytes
            manifest["csv_uncompressed_sha256"] = raw_digest.hexdigest()
        conn.rollback()

    migrations = output / "database"
    migrations.mkdir()
    for source in sorted((root / "database").glob("*.sql")):
        shutil.copy2(source, migrations / source.name)
    capture_dir = output / "datasets" / "f1_25" / "capturas"
    capture_dir.mkdir(parents=True)
    for name in (RAW, RAW + ".meta.json"):
        shutil.copy2(raw_source.parent / name, capture_dir / name)
    shutil.copy2(__file__, output / "respaldo_spa.py")
    shutil.copy2(root / "docs" / "restaurar_spa.md", output / "LEEME.md")
    for path in sorted(output.rglob("*")):
        if path.is_file():
            manifest["files"][path.relative_to(output).as_posix()] = {
                "bytes": path.stat().st_size, "sha256": digest(path)}
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps({"package": str(output), "rows": rows,
                      "bytes": sum(f["bytes"] for f in manifest["files"].values())}), flush=True)


def verify_package(package):
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    if manifest["format"] != "spa-copy-csv-gzip-v1" or manifest["columns"] != list(COLUMNS):
        raise ValueError("Formato o columnas desconocidas")
    for name, expected in manifest["files"].items():
        path = package / name
        if path.stat().st_size != expected["bytes"] or digest(path) != expected["sha256"]:
            raise ValueError(f"Archivo incompleto o alterado: {name}")
    h = hashlib.sha256()
    size = 0
    with gzip.open(package / "telemetry.csv.gz", "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
            size += len(block)
    if h.hexdigest() != manifest["csv_uncompressed_sha256"] or size != manifest["csv_uncompressed_bytes"]:
        raise ValueError("El contenido descomprimido no coincide")
    print("Hashes y descompresion completos: OK", flush=True)
    return manifest


def restore_package(package, dsn_env):
    manifest = verify_package(package)
    dsn = os.environ.get(dsn_env)
    if not dsn:
        raise ValueError(f"Definir {dsn_env} con el DSN de una base NUEVA y VACIA")
    with psycopg.connect(dsn, options="-c timezone=UTC -c lock_timeout=2000 "
                          "-c search_path=public,pg_catalog") as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT c.relname FROM pg_catalog.pg_class c
                JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname NOT LIKE 'pg_%'
                  AND n.nspname <> 'information_schema'
                  AND c.relkind IN ('r', 'p', 'f', 'm', 'v') LIMIT 1
            """)
            if cur.fetchone():
                raise ValueError("Destino NO vacio; no se permite mezclar ni sobrescribir")
            cur.execute("SHOW server_version_num")
            if int(cur.fetchone()[0]) // 10000 != 16:
                raise ValueError("Este paquete se verifica con PostgreSQL 16")
            for path in sorted((package / "database").glob("*.sql")):
                cur.execute(path.read_text(encoding="utf-8"))
            cur.execute("SELECT extversion FROM pg_extension WHERE extname='timescaledb'")
            if cur.fetchone()[0] != manifest["timescaledb"]:
                raise ValueError("Usar la version TimescaleDB del manifiesto")
            cur.execute(CATALOG_SCHEMA)
            # Solo en el destino nuevo: construir indices al final evita
            # mantenerlos fila por fila durante la importacion masiva.
            cur.execute("SELECT indexname, indexdef FROM pg_indexes "
                        "WHERE schemaname='public' AND tablename='telemetry_messages'")
            indexes = cur.fetchall()
            for name, _definition in indexes:
                cur.execute(sql.SQL("DROP INDEX {}").format(sql.Identifier("public", name)))
            columns = sql.SQL(", ").join(map(sql.Identifier, COLUMNS))
            query = sql.SQL("COPY telemetry_messages ({}) FROM STDIN "
                            "WITH (FORMAT CSV, HEADER TRUE, ENCODING 'UTF8')").format(columns)
            print("Destino vacio verificado. Restaurando filas...", flush=True)
            sent = 0
            next_report = 256 * 1024 * 1024
            with gzip.open(package / "telemetry.csv.gz", "rb") as source:
                with cur.copy(query) as copy:
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        copy.write(block)
                        sent += len(block)
                        if sent >= next_report:
                            print(f"COPY enviado: {sent / 1e9:.2f} GB", flush=True)
                            next_report += 256 * 1024 * 1024
            print("COPY terminado. Construyendo indices...", flush=True)
            for name, definition in indexes:
                print(name, flush=True)
                cur.execute(definition)
            print("Indices terminados. Comparando inventario y fases...", flush=True)
            cur.execute("SELECT count(*) FROM telemetry_messages")
            total = cur.fetchone()[0]
            if total != manifest["rows"] or inventory(cur) != manifest["signals"]:
                raise ValueError("Inventario restaurado diferente; se revierte la transaccion")
            if phase_summary(cur) != manifest["phases"]:
                raise ValueError("Fases restauradas diferentes; se revierte la transaccion")
            cur.execute("""
                INSERT INTO sesiones_catalogo
                SELECT session_id, source_type, count(*), count(DISTINCT signal_name),
                       count(DISTINCT vehicle_id), min(timestamp), max(timestamp), now()
                FROM telemetry_messages GROUP BY session_id, source_type
            """)
            cur.execute("ANALYZE telemetry_messages")
        conn.commit()
    print(f"Restauracion verificada: {total} filas, 113 senales, 1 vehiculo, 3 fases.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("export", "verify", "restore"))
    parser.add_argument("package", type=Path)
    parser.add_argument("--dsn-env", default="SPA_RESTORE_DSN")
    args = parser.parse_args()
    if args.action == "export":
        export_package(args.package)
    elif args.action == "verify":
        verify_package(args.package)
    else:
        restore_package(args.package, args.dsn_env)


if __name__ == "__main__":
    main()
