-- Trazabilidad aditiva del procesamiento parametrizable de paquetes Nivel B.
-- No modifica telemetria existente ni importa datos por si sola.
CREATE TABLE IF NOT EXISTS session_processing_runs (
    run_id BIGSERIAL PRIMARY KEY,
    package_fingerprint TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL,
    session_key INTEGER NOT NULL,
    package_path TEXT NOT NULL,
    processor_version TEXT NOT NULL,
    inventory JSONB NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'validated', 'running', 'completed', 'partial', 'failed'
    )),
    counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at_utc TIMESTAMPTZ,
    error_summary TEXT
);

CREATE INDEX IF NOT EXISTS session_processing_runs_session_key_idx
    ON session_processing_runs (session_key, started_at_utc DESC);

CREATE TABLE IF NOT EXISTS session_processing_issues (
    issue_id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES session_processing_runs(run_id),
    severity TEXT NOT NULL CHECK (severity IN ('warning', 'error')),
    issue_code TEXT NOT NULL,
    file_path TEXT,
    message TEXT NOT NULL,
    context JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS session_processing_issues_run_id_idx
    ON session_processing_issues (run_id, severity, issue_id);
