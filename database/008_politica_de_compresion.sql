-- ---------------------------------------------------------------------------
-- LA COMPRESION ESTABA CONFIGURADA Y NO LA EJECUTABA NADIE
-- ---------------------------------------------------------------------------
--
-- La migracion 007 deja la compresion **configurada** ---con que se agrupa cada
-- segmento y en que orden--- y lo dice con todas las letras: «esto configura la
-- compresion; no comprime». Comprimir quedaba para
-- `scripts/verificar_hipertabla_comprimida.py`, que es una comprobacion de que
-- la vuelta completa es posible y reversible, no una tarea que corra sola.
--
-- El resultado es que nadie comprimia. Medido el 2026-09-10 sobre la base de
-- esta maquina: seis fragmentos, **cero comprimidos**, con la compresion
-- habilitada desde que se aplico la 007. Y en la Pi lo mismo, con la base en
-- 8,7 GB.
--
-- CUANTO CUESTA NO TENERLA. Los tres fragmentos de OpenF1 pasaron de 966 MB a
-- 28 MB comprimidos a mano: treinta y cuatro veces, en veinticinco segundos de
-- reloj. Y no es solo disco: la consulta temporal del tablero sobre esa sesion
-- pasa de **26,1 s a 1,3 s**, porque `compress_segmentby` incluye
-- `signal_name` y `session_id` y entonces el motor lee los segmentos que
-- importan en vez de recorrer el fragmento. Los de F1 25 ---2.690 y 2.370 MB---
-- y el del bus ---463 MB--- siguen sin comprimir.
--
-- COMPRIMIR A MANO NO ALCANZA, Y POR ESO ESTA MIGRACION EXISTE. Un fragmento
-- comprimido a mano se queda comprimido, pero los que entren despues nacen sin
-- comprimir. Sin una tarea que lo haga sola, el ahorro se pierde con la
-- siguiente carga y alguien tiene que acordarse cada vez. Acordarse cada vez no
-- es una politica.
--
-- ---------------------------------------------------------------------------
-- POR QUE UN DIA, Y NO UNA HORA
-- ---------------------------------------------------------------------------
--
-- `compress_after` dice cuanta antigüedad tiene que tener un fragmento para que
-- la tarea lo tome. El numero no es una preferencia: **un fragmento comprimido
-- puede rechazar inserciones en su rango de tiempo**, segun la version del
-- motor, y el sistema captura en vivo. Si la tarea alcanzara al fragmento que
-- se esta escribiendo, la captura empezaria a fallar.
--
-- Los fragmentos de esta hipertabla son de **una hora** ---declarado en la 007 y
-- comprobado en las dos maquinas---. Un dia deja veintitres horas de margen
-- entre lo que se escribe y lo que se comprime, que es holgura de sobra incluso
-- si una captura larga cruza la medianoche o si el reloj de la maquina se
-- corre. Y no cuesta nada de lo que se recupera: lo que ocupa es lo viejo, no
-- la ultima hora.
--
-- Un intervalo mas corto ---una hora, tres--- ahorraria lo mismo y pondria la
-- tarea a competir con la captura por el fragmento en curso. No se gana nada y
-- se arriesga lo unico que no se puede perder, que es el dato entrando.
--
-- MEDIDO DESPUES, Y ACOTA LO DE ARRIBA SIN CONTRADECIRLO. En la Pi, con
-- TimescaleDB 2.28.3, una insercion dentro del rango de un fragmento **ya
-- comprimido** fue aceptada: la fila quedo legible, se borro, y el fragmento
-- siguio comprimido. O sea que en esta version el rechazo no ocurre. El texto
-- de arriba dice «segun la version del motor» justamente por esto, y el dia de
-- margen se sostiene igual por el otro motivo, que es no poner la tarea a
-- competir con la captura por el fragmento que se esta escribiendo.
--
-- Y UNA TRAMPA DE ESA MISMA MEDICION, PORQUE COSTO DOS INTENTOS: las dos
-- primeras pruebas parecieron decir «rechazada» y era falso. Fallaban por
-- columnas NOT NULL sin llenar ---`driver_id`, despues `quality_flag`---, no
-- por la compresion. Contar la excepcion en vez de leer su texto respondia que
-- no a una pregunta que nadie habia hecho.
--
-- ---------------------------------------------------------------------------
-- QUE NO HACE ESTA MIGRACION
-- ---------------------------------------------------------------------------
--
-- No comprime nada al aplicarse. Registra la tarea y la deja programada; el
-- primer pase lo hace el planificador. Comprimir dentro de una migracion
-- bloquearia el despliegue por el tiempo que tarde ---veinticinco segundos por
-- cada 966 MB--- sobre una base que puede tener varios gigabytes, y un
-- despliegue que tarda lo que tarde la compresion es un despliegue que nadie
-- sabe cuanto dura.
--
-- Para comprimir lo que ya esta, sin esperar al planificador:
--     SELECT compress_chunk(c) FROM show_chunks('telemetry_messages',
--            older_than => INTERVAL '1 day') c
--      WHERE NOT (SELECT is_compressed FROM timescaledb_information.chunks
--                  WHERE format('%I.%I', chunk_schema, chunk_name)::regclass = c);
--
-- Y para deshacerla, que es lo que la hace una decision y no un camino de ida:
--     SELECT remove_compression_policy('telemetry_messages');
--     SELECT decompress_chunk(c) FROM show_chunks('telemetry_messages') c;
-- ---------------------------------------------------------------------------

DO $$
BEGIN
    -- La tarea se registra una sola vez. `add_compression_policy` con
    -- `if_not_exists` avisa en vez de fallar, pero la comprobacion explicita
    -- deja dicho en el codigo que aplicar dos veces es correcto: estas
    -- migraciones se corren enteras sobre bases que ya estan al dia.
    IF NOT EXISTS (
        SELECT 1 FROM timescaledb_information.jobs
         WHERE proc_name = 'policy_compression'
           AND hypertable_name = 'telemetry_messages'
    ) THEN
        -- Falla a proposito si la compresion no esta configurada: sin la 007
        -- aplicada, una politica no tendria por que agrupar y comprimiria peor
        -- que a mano. Es mejor que el despliegue se detenga a que quede una
        -- tarea que hace algo distinto de lo que este archivo dice.
        PERFORM add_compression_policy('telemetry_messages', INTERVAL '1 day');
    END IF;
END $$;
