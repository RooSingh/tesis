-- La conversion a hipertabla y su compresion, asentadas.
--
-- POR QUE FALTABA
-- ---------------
-- La conversion se hizo con `scripts/convertir_a_hipertabla.py`, que la ejecuta
-- sobre la tabla que ya tiene datos. Ese guion sirve para convertir una tabla
-- viva ---copia, verifica y recien entonces intercambia--- pero **no deja el
-- esquema escrito**: una base nueva no sabe que fragmentos usar, ni por que
-- columnas comprimir. Sin esto la tabla funciona, y ocupa treinta veces mas.
--
-- LO QUE ESTA MIGRACION REPRODUCE, MEDIDO SOBRE LA BASE EN USO
-- ------------------------------------------------------------
-- * fragmentos de **una hora**;
-- * compresion segmentada por `signal_name, session_id, source_type,
--   vehicle_id` y ordenada por `timestamp` ascendente;
-- * los nombres de indice que la conversion dejo.
--
-- Con esos ajustes, 89,7 millones de filas ocupan 2,59 GB en lugar de 75,7:
-- veintinueve veces menos. Las columnas de segmentacion son las que se filtran
-- en toda consulta del tablero, y son justamente las que **no** hay que
-- descomprimir para mirar.
--
-- POR QUE LOS INDICES SE RENOMBRAN
-- --------------------------------
-- 001, 003 y 004 los crearon con nombres largos. La conversion copio la tabla a
-- una llamada `..._hiper`, cuyos indices heredaron nombres acortados, y al
-- intercambiar las tablas quedaron esos. Renombrarlos aca deja el esquema de una
-- base nueva igual al de la que esta en uso, que es la unica forma de que
-- comparar las dos signifique algo.
--
-- La migracion 006 es posterior a la conversion y ya usa el nombre corto, asi
-- que no figura en la lista.
--
-- En la base existente esto no cambia nada: cada paso comprueba primero si ya
-- esta hecho.
--
-- Aplicada el 2026-09-08.

-- ---------------------------------------------------------------------------
-- 1. La hipertabla
-- ---------------------------------------------------------------------------
--
-- `create_default_indexes => FALSE` y el indice creado a mano debajo: el
-- automatico se llamaria `telemetry_messages_timestamp_idx` y el que hay se
-- llama `..._hiper_timestamp_idx`. Es el mismo indice con otro nombre, y dos
-- esquemas que difieren solo en eso son dos esquemas que hay que comparar a
-- mano cada vez.
--
-- Sobre una tabla que ya tiene filas esto falla a proposito, sin `migrate_data`:
-- mover ochenta y nueve millones de filas dentro de una migracion, en una sola
-- transaccion, no es algo que deba pasar sin que alguien lo pida. Para eso esta
-- `scripts/convertir_a_hipertabla.py`.
SELECT create_hypertable(
    'telemetry_messages'::regclass,
    by_range('timestamp', INTERVAL '1 hour'),
    create_default_indexes => FALSE,
    if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS telemetry_messages_hiper_timestamp_idx
    ON telemetry_messages (timestamp DESC);

-- ---------------------------------------------------------------------------
-- 2. Los nombres que dejo la conversion
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    par TEXT[][] := ARRAY[
        ['telemetry_messages_source_session_driver_timestamp_idx',
         'hiper_source_session_driver_ts'],
        ['telemetry_messages_replay_identity_uidx', 'hiper_replay_identity'],
        ['telemetry_messages_signal_timestamp_idx', 'hiper_signal_ts']
    ];
    i INT;
BEGIN
    FOR i IN 1 .. array_length(par, 1) LOOP
        IF to_regclass(par[i][1]) IS NOT NULL
           AND to_regclass(par[i][2]) IS NULL THEN
            EXECUTE format('ALTER INDEX %I RENAME TO %I', par[i][1], par[i][2]);
        END IF;
    END LOOP;
END $$;

-- El indice de las corridas de reinyeccion anteriores a la migracion 003 no
-- sobrevivio a la conversion, y no se lo repone: buscaba el identificador
-- dentro de `metadata->'extra'` para poder auditar 3,4 millones de filas de
-- pruebas de carga que ya no se auditan. Se lo quita en una base nueva para que
-- las dos tengan los mismos cinco indices y no seis.
DROP INDEX IF EXISTS telemetry_messages_legacy_replay_run_idx;

-- ---------------------------------------------------------------------------
-- 3. La compresion
-- ---------------------------------------------------------------------------
--
-- Se aplica solo si no esta puesta: cambiarla sobre una tabla que ya tiene
-- fragmentos comprimidos exige descomprimirlos, y eso no es trabajo de una
-- migracion.
--
-- Esto **configura** la compresion; no comprime. Los fragmentos se comprimen
-- con `scripts/verificar_hipertabla_comprimida.py`, que ademas comprueba que la
-- vuelta completa ---comprimir y descomprimir--- devuelva las mismas filas.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM timescaledb_information.compression_settings
                    WHERE hypertable_name = 'telemetry_messages') THEN
        ALTER TABLE telemetry_messages SET (
            timescaledb.compress,
            timescaledb.compress_segmentby =
                'signal_name, session_id, source_type, vehicle_id',
            timescaledb.compress_orderby = 'timestamp ASC');
    END IF;
END $$;
