-- Trazabilidad e idempotencia del replay historico por bloques.
-- Extension aditiva: no altera filas existentes ni cambia el significado de la
-- telemetria ya persistida. Las filas que no provienen de un replay conservan
-- ambas columnas en NULL y quedan fuera del indice unico parcial.

ALTER TABLE telemetry_messages
    ADD COLUMN IF NOT EXISTS replay_run_id TEXT,
    ADD COLUMN IF NOT EXISTS replay_seq BIGINT;

-- Clave de idempotencia del replay.
--
-- Se incluye `timestamp` deliberadamente por dos razones:
--   1. si `telemetry_messages` es un hypertable de TimescaleDB, todo indice
--      unico DEBE contener la columna de particionado; sin `timestamp` la
--      creacion fallaria;
--   2. no debilita la clave, porque `replay_seq` ya es unica dentro de un
--      `replay_run_id` y determina un unico `timestamp`.
--
-- El indice es parcial para no crecer con la telemetria CAN simulada, que no
-- participa del replay y mantiene ambas columnas en NULL.
CREATE UNIQUE INDEX IF NOT EXISTS telemetry_messages_replay_identity_uidx
    ON telemetry_messages (replay_run_id, replay_seq, timestamp)
    WHERE replay_run_id IS NOT NULL AND replay_seq IS NOT NULL;

-- Nota operativa: este indice es prerequisito del INSERT del consumidor, que usa
-- `ON CONFLICT (replay_run_id, replay_seq, timestamp) DO NOTHING`. Si la
-- migracion no se aplica, el consumidor fallara de forma visible al primer lote
-- en lugar de degradarse en silencio. Es intencional.
