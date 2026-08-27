-- Resultados de analisis automatico por sesion, vuelta y stint.
-- Migracion aditiva, aplicada el 2026-08-27.
--
-- POR QUE UNA TABLA Y NO CALCULO A DEMANDA
--
-- Los resultados son unas 1.100 filas por corrida (20 pilotos por 52 vueltas, mas
-- los stints), frente a los 6.217.506 mensajes de telemetria que los originan:
-- cinco ordenes de magnitud menos. Recalcularlos en cada carga de pantalla
-- significaria recorrer millones de filas por request, que es exactamente el
-- defecto detectado en `obtener_replay_openf1` y corregido en esta misma jornada.
--
-- POR QUE LAS METRICAS SE GUARDAN EN TRES COMPARTIMENTOS
--
-- El proyecto sostiene la distincion entre dato observado, derivado y estimado. Si
-- todas las metricas compartieran las mismas columnas, esa distincion viviria solo
-- en la documentacion y se perderia en cuanto alguien consultara la tabla. Al
-- separarlas en `metricas_oficiales`, `metricas_derivadas` y `calidad`, el nivel de
-- evidencia queda inscripto en la estructura: no se puede guardar una metrica
-- derivada entre las oficiales sin notarlo.
--
--   metricas_oficiales -> proviene de OpenF1 sin transformar: tiempos por sector,
--                         velocidades de intermedios y trampa, minisectores.
--   metricas_derivadas -> calculada por el proyecto a partir de la telemetria
--                         replicada: agregados de velocidad, acelerador, freno,
--                         marcha, DRS, y distancia por integracion de velocidad.
--   calidad            -> cobertura de la muestra y limites del propio resultado:
--                         cantidad de muestras, hueco temporal maximo, si el fin de
--                         la ventana fue estimado.

CREATE TABLE IF NOT EXISTS session_analysis_runs (
    analysis_run_id BIGSERIAL PRIMARY KEY,
    session_key INTEGER NOT NULL,
    -- Corrida de replay analizada. Es obligatoria porque una misma sesion acumula
    -- varias corridas, incluidas pruebas de carga, y un analisis sin declarar su
    -- origen no es reproducible.
    replay_run_id TEXT NOT NULL,
    analyzer_version TEXT NOT NULL,
    generated_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Longitud oficial del circuito usada para validar la distancia derivada.
    -- Se guarda con el resultado porque cambiar de circuito cambia la referencia.
    track_length_m DOUBLE PRECISION,
    counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    limits JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (session_key, replay_run_id, analyzer_version)
);

CREATE TABLE IF NOT EXISTS session_lap_analysis (
    analysis_run_id BIGINT NOT NULL
        REFERENCES session_analysis_runs(analysis_run_id) ON DELETE CASCADE,
    driver_number INTEGER NOT NULL,
    lap_number INTEGER NOT NULL,
    window_start TIMESTAMPTZ,
    window_end TIMESTAMPTZ,
    metricas_oficiales JSONB NOT NULL DEFAULT '{}'::jsonb,
    metricas_derivadas JSONB NOT NULL DEFAULT '{}'::jsonb,
    calidad JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (analysis_run_id, driver_number, lap_number)
);

CREATE TABLE IF NOT EXISTS session_stint_analysis (
    analysis_run_id BIGINT NOT NULL
        REFERENCES session_analysis_runs(analysis_run_id) ON DELETE CASCADE,
    driver_number INTEGER NOT NULL,
    stint_number INTEGER NOT NULL,
    compound TEXT,
    lap_start INTEGER,
    lap_end INTEGER,
    window_start TIMESTAMPTZ,
    window_end TIMESTAMPTZ,
    metricas_oficiales JSONB NOT NULL DEFAULT '{}'::jsonb,
    metricas_derivadas JSONB NOT NULL DEFAULT '{}'::jsonb,
    calidad JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (analysis_run_id, driver_number, stint_number)
);

-- Consultas previstas: recuperar el analisis de un piloto ordenado por vuelta.
CREATE INDEX IF NOT EXISTS session_lap_analysis_driver_idx
    ON session_lap_analysis (analysis_run_id, driver_number, lap_number);

-- Listado de corridas analizadas por sesion, que reemplaza el agregado sobre
-- `telemetry_messages`: ese recorre 10 millones de filas y tarda mas de 17
-- segundos medidos, mientras que aqui son unas pocas filas.
CREATE INDEX IF NOT EXISTS session_analysis_runs_session_idx
    ON session_analysis_runs (session_key, generated_at_utc DESC);
