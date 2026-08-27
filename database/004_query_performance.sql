-- Indices de rendimiento para consultas que quedaron inviables al crecer
-- `telemetry_messages` a 10 millones de filas y 9,4 GB.
--
-- Migracion aditiva: no altera datos ni columnas. Solo agrega indices.
-- Aplicada el 2026-08-27.

-- 1. Ultima muestra por senal.
--
-- `obtener_ultimos_por_senal()` resuelve un DISTINCT ON (signal_name) ordenado por
-- tiempo descendente. Sin indice, PostgreSQL recorria la tabla completa y ordenaba
-- 45 MB a disco por cada uno de ocho procesos paralelos: 32,7 segundos medidos
-- para devolver 19 filas.
--
-- Con este indice la consulta se resuelve saltando al primer elemento de cada
-- grupo, sin recorrer ni ordenar.
CREATE INDEX IF NOT EXISTS telemetry_messages_signal_timestamp_idx
    ON telemetry_messages (signal_name, timestamp DESC);

-- 2. Identificacion de corridas de replay anteriores a la migracion 003.
--
-- Las corridas previas guardaron su identificador dentro de `metadata->'extra'`,
-- en JSONB sin indexar. Son 3.416.805 filas de pruebas de carga que comparten
-- `session_id` con el replay definitivo, de modo que distinguirlas exigia recorrer
-- los 9,4 GB completos.
--
-- Se indexa la expresion en lugar de copiar el valor a la columna nueva: un UPDATE
-- sobre 3,4 millones de filas reescribiria y esponjaria la tabla, mientras que este
-- indice permite filtrarlas y auditarlas sin tocar una sola fila.
CREATE INDEX IF NOT EXISTS telemetry_messages_legacy_replay_run_idx
    ON telemetry_messages ((metadata -> 'extra' ->> 'replay_run_id'))
    WHERE replay_run_id IS NULL;

-- Nota sobre la ausencia de clave primaria.
--
-- `telemetry_messages` no tiene clave primaria: solo una restriccion CHECK y los
-- indices declarados. Agregarla exigiria una columna nueva de identidad y la
-- reescritura completa de 9,4 GB, sin beneficio real para una tabla que solo
-- recibe inserciones y nunca actualiza ni borra por fila. La identidad de las filas
-- de replay ya esta garantizada por el indice unico de la migracion 003.
-- Se documenta como limite aceptado y no como pendiente.
