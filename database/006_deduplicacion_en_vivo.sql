-- Deduplicacion de la telemetria en vivo.
--
-- POR QUE HACE FALTA
-- ------------------
-- El consumidor confirma cada mensaje despues de haberlo escrito, de modo que un
-- mensaje muerto en la cola nunca fue confirmado y el intermediario lo reenvia.
-- Esa garantia es **al menos una vez**: si el proceso muere entre el `insert` y
-- el acuse, el reenvio escribe la fila dos veces.
--
-- El indice unico que suprime duplicados ---`hiper_replay_identity`, de la
-- migracion 003--- es parcial y cubre solo las filas con identidad de
-- reinyeccion. La telemetria en vivo no tenia con que deduplicarse.
--
-- POR QUE NO ALCANZA LA CLAVE NATURAL
-- -----------------------------------
-- La terna vehiculo, senal e instante **no es unica**, y no por un defecto que
-- se pueda corregir. La marca de tiempo se deriva del reloj de sesion del juego,
-- y ese reloj no avanza mientras la sesion no arranco: el vehiculo quieto en el
-- box emite durante minutos con el mismo `session_time`.
--
-- Medido sobre una carrera de Spa: 21.047 filas comparten clave, concentradas en
-- **dos instantes** que reunen las ciento trece senales que la sesion publica.
-- En uno de ellos hay ciento cincuenta y ocho muestras con velocidad cero en el
-- metro 76 y el acelerador variando entre 0 y 80,4: son mediciones reales y
-- distintas, y un indice unico sobre esa clave las borraria.
--
-- LA CLAVE QUE SI ES UNICA YA SE ESCRIBIA
-- ---------------------------------------
-- Cada fila lleva en `metadata.extra` el `desplazamiento_captura_us`: el
-- desplazamiento monotono del datagrama dentro de la captura. Medido sobre la
-- misma sesion de 5.641.702 filas, la terna vehiculo, senal y desplazamiento
-- **no repite ninguna vez**.
--
-- De modo que no se inventa una identidad: se promueve a columna la que ya se
-- escribe, por el mismo motivo por el que se promovieron las de reinyeccion en la
-- migracion 003 ---un campo dentro de JSONB no se indexa de forma economica, y una
-- clave de idempotencia tiene que poder expresarse como indice unico---.
--
-- POR QUE NO HACE FALTA RELLENAR LO YA ESCRITO
-- --------------------------------------------
-- El indice es parcial y solo cubre las filas donde la columna no es nula. Las ya
-- escritas quedan fuera, y esta bien: la deduplicacion protege contra el reenvio
-- futuro, y lo ya persistido no se va a reenviar.
--
-- Medido sobre una hipertabla de prueba con la misma forma y compresion: agregar
-- la columna toma 0,02 s por ser una operacion de metadatos, y el indice se crea
-- de forma instantanea porque nace vacio.
--
-- POR QUE EL INSTANTE FORMA PARTE DE LA CLAVE
-- -------------------------------------------
-- Porque una hipertabla lo exige: todo indice unico debe incluir la columna de
-- particionado. No debilita la clave, porque **un reenvio trae el mismo
-- instante**: la marca se deriva del reloj de sesion de forma determinista, y el
-- mismo datagrama reprocesado produce exactamente la misma marca.
--
-- Verificado sobre la hipertabla de prueba: el reenvio se rechaza con el trozo sin
-- comprimir y tambien con el original ya comprimido.

ALTER TABLE telemetry_messages
    ADD COLUMN IF NOT EXISTS desplazamiento_captura_us BIGINT;

COMMENT ON COLUMN telemetry_messages.desplazamiento_captura_us IS
    'Desplazamiento monotono del datagrama dentro de su captura, en microsegundos. '
    'Promovido desde metadata.extra para poder indexarlo. Es la clave de '
    'idempotencia de la telemetria en vivo, que el instante no puede ser porque '
    'el reloj de sesion de la fuente puede detenerse.';

CREATE UNIQUE INDEX IF NOT EXISTS hiper_identidad_en_vivo
    ON telemetry_messages (vehicle_id, signal_name,
                           desplazamiento_captura_us, "timestamp")
    WHERE desplazamiento_captura_us IS NOT NULL;
