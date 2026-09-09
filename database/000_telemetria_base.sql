-- La tabla de telemetria, que hasta ahora no estaba en ninguna migracion.
--
-- POR QUE FALTABA, Y POR QUE ESO ERA UN PROBLEMA
-- ----------------------------------------------
-- `telemetry_messages` se creo a mano al principio del trabajo y nunca se
-- asento. Las seis migraciones que existian la daban por hecha: 001, 003 y 006
-- solo le agregan columnas, y 004 solo indices. En esta maquina eso nunca se
-- noto porque la tabla ya estaba.
--
-- Se noto al preguntarse que hace falta para levantar el trabajo en otra
-- computadora. Clonar el repositorio, levantar los contenedores y aplicar las
-- migraciones en orden **falla en la primera**, porque `ALTER TABLE
-- telemetry_messages` no encuentra que alterar. La tabla que guarda los
-- ochenta y nueve millones de filas era la unica pieza del sistema sin
-- procedencia escrita.
--
-- Esta migracion lleva el numero 000 y no 007 a proposito: tiene que correr
-- **antes** que las que la alteran.
--
-- QUE FORMA TIENE ESTA TABLA
-- --------------------------
-- La de origen, la anterior a las migraciones: diecisiete columnas. Las cuatro
-- que faltan ---`metadata`, `replay_run_id`, `replay_seq` y
-- `desplazamiento_captura_us`--- las agregan 001, 003 y 006, cada una con su
-- motivo escrito. Reproducirlas aca dejaria dos fuentes para lo mismo.
--
-- POR QUE NO HAY CLAVE PRIMARIA
-- -----------------------------
-- Esta explicado en la migracion 004 y se conserva como limite aceptado: la
-- tabla solo recibe inserciones y la identidad de las filas que podrian
-- repetirse la garantizan los dos indices unicos parciales de 003 y 006.
--
-- Esa nota menciona ademas una restriccion CHECK que **hoy no existe**: se
-- perdio al convertir la tabla en hipertabla, y no se la reconstruye aca porque
-- no quedo asentado que comprobaba. Queda dicho para que la ausencia sea un
-- hecho conocido y no una sorpresa.
--
-- Aplicada el 2026-09-08 sobre una base nueva; en la base existente no cambia
-- nada.

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS telemetry_messages (
    -- Instante de la muestra en UTC. Es la dimension por la que la tabla se
    -- particiona, de modo que toda consulta que no acote por aca recorre todo.
    timestamp        TIMESTAMPTZ      NOT NULL,

    -- De quien es la muestra. `vehicle_id` es el vehiculo dentro de la sesion;
    -- `driver_id`, quien lo conduce; `lap_id` puede faltar porque no todas las
    -- fuentes numeran las vueltas en el mismo mensaje.
    vehicle_id       TEXT             NOT NULL,
    driver_id        TEXT             NOT NULL,
    session_id       TEXT             NOT NULL,
    lap_id           TEXT,

    -- Que se midio, y cuanto. El valor va en la columna de su tipo y las otras
    -- dos quedan nulas: una sola columna de texto obligaria a convertir en cada
    -- lectura y perderia la aritmetica en la base.
    signal_name      TEXT             NOT NULL,
    value_numeric    DOUBLE PRECISION,
    value_boolean    BOOLEAN,
    value_text       TEXT,
    unit             TEXT             NOT NULL,
    quality_flag     TEXT             NOT NULL,

    -- Procedencia en el bus, cuando la fuente es CAN.
    can_id           INTEGER,
    src              INTEGER,

    -- Que fuente la produjo. Es columna de segmentacion de la compresion.
    source_type      TEXT,

    -- Ubicacion en el circuito, cuando la fuente la declara.
    track_segment_id TEXT,
    sector_id        TEXT,
    curve_id         TEXT
);

COMMENT ON TABLE telemetry_messages IS
    'Una fila por senal y por instante. Es la unica tabla de serie temporal del '
    'trabajo: todo lo demas es contexto o catalogo. Se convierte en hipertabla y '
    'se comprime en la migracion 007.';
