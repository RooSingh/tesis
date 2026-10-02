# Respaldo selectivo de Spa original

Este paquete es una exportacion logica selectiva, NO un archivo de pg_restore.
Contiene CSV UTF-8 comprimido mediante gzip, las 21 columnas originales sin
renormalizar, migraciones SQL, restaurador, captura cruda y sidecar.

## Contenido y alcance

- Sesion `f1_25:session:3731090176871608020`.
- 5.641.702 filas del original del 5 de septiembre de 2026, coche 19.
- 113 senales. Conserva formacion, luces y carrera (tres fases).
- Excluye las corridas de prueba posteriores con replay_run_id.
- El crudo completo se conserva para auditoria o futuras normalizaciones; eso
  NO significa que la telemetria persistida incluya todos los coches.
- `manifest.json` contiene inventario, predicado, instantanea, versiones y hashes.
- `database/` conserva las migraciones usadas por el restaurador.

El paquete no incluye credenciales, el codigo completo del dashboard, un dump
del cluster, tablas internas de TimescaleDB ni datos de otras sesiones.
Trasladar tambien la version correspondiente del proyecto mediante el proceso
de migracion habitual. Mantener una copia de este paquete en otra unidad/PC:
`datasets/` esta ignorado por Git y no viaja al clonar el repositorio.

## Requisitos

- Python con `psycopg[binary]` (version usada: 3.3.4).
- Una base NUEVA y VACIA en PostgreSQL 16 con TimescaleDB de la version exacta
  indicada en manifest.json. La extension debe estar disponible y precargada.
- Espacio para los datos descomprimidos e indices. El tamano del gzip no es una
  estimacion del espacio necesario al restaurar; dejar varios GB libres.
- Usuario con permisos para crear extension, tablas e hipertabla.

La imagen documentada del proyecto es:

```text
timescale/timescaledb@sha256:61f891691050da6032023c01ea885730eeeba06b7c17b403e7d0b9c49c37dfe9
```

No recrear/eliminar el contenedor que contiene datos existentes. Si se usa
Compose, hacerlo en la nueva PC y revisar recursos y volumenes previamente.

## Verificar antes de restaurar

Desde la carpeta del paquete:

```powershell
python -B respaldo_spa.py verify .
```

Verifica hashes de todos los archivos y el contenido descomprimido completo.
No conecta a la base. El manifiesto es una comprobacion de integridad, no una
firma criptografica de autenticidad.

## Restaurar

Primero crear una base vacia desde template0 (la imagen de TimescaleDB puede
preinstalar la extension en su base inicial y en template1):

```sql
CREATE DATABASE spa_original WITH TEMPLATE template0;
```

No ejecutar ese CREATE si el nombre ya existe; elegir un nombre nuevo. Configurar
el DSN con las credenciales elegidas en
la nueva PC, no copiar literalmente los marcadores de este ejemplo:

```powershell
$env:SPA_RESTORE_DSN = 'host=127.0.0.1 port=5432 dbname=spa_original user=USUARIO password=CLAVE'
python -B respaldo_spa.py restore .
```

El restaurador rehusa destinos con tablas o vistas fuera de los esquemas del
sistema, incluso una base donde TimescaleDB ya creo sus tablas internas. Crear
una base nueva sin instalarle previamente la extension: el script lo hace. Fija
el esquema de trabajo en public. Aplica
las migraciones incluidas, carga las filas en una transaccion, compara recuentos
por senal, tipos de valor, extremos y fases, y genera solo el catalogo de Spa.
Si falla antes del commit, revierte la carga. No deduplica ni corrige timestamps.
No configura politicas de compresion automatica ni arranca consumidores.

La compresion de los chunks puede aplicarse posteriormente en el DESTINO,
despues de validar. El formato logico no conserva la compresion fisica del origen.

No ejecutar el restore sobre una base ya poblada. No reproducir el crudo por
UDP/MQTT ni republicarlo encima de esta restauracion: eso no es restaurar el
respaldo y puede duplicar o mezclar adquisiciones.

## Integrar con el dashboard

1. Configurar DB_HOST, DB_PORT, DB_NAME, DB_USER y DB_PASSWORD de la API para
   apuntar a la base restaurada.
2. Copiar la carpeta `datasets/f1_25/capturas/` del paquete a esa misma ruta
   relativa dentro del proyecto. Conservar nombres y sidecar intactos.
3. Arrancar el proyecto siguiendo sus instrucciones de migracion.
4. Verificar que el catalogo muestre Spa y 5.641.702 filas, 113 senales y un coche.
5. Seleccionar Original / Carrera (fase 3). Deben aparecer 22 vueltas; la primera
   vuelta de carrera dura aproximadamente 136,7 segundos entre muestras.

El restore preserva datos; la presentacion de adquisiciones/fases depende de la
version del backend y frontend trasladados. Los defectos pendientes de graficas
no se corrigen restaurando o renormalizando la telemetria.
