# Plataforma de telemetría vehicular para competición

Trabajo Final de Ingeniería en Computación — Facultad de Ciencias Exactas y
Tecnología (FACET), Universidad Nacional de Tucumán.

**Autora:** Rocío Singh

Sistema que adquiere telemetría de un vehículo de competición, la transporta y
la persiste en tiempo real, y la presenta en un tablero web para el análisis
en vivo y posterior. Trabaja con tres fuentes de datos de naturaleza distinta,
normalizadas a un mismo contrato interno:

| fuente | qué es | cómo entra |
| --- | --- | --- |
| **F1 25** | simulador de carreras; emite telemetría por UDP (puerto 20777) | captura en vivo o reproducción de una captura grabada |
| **CAN de un Toyota RAV4** | tramas reales del bus del vehículo (dataset commaCarSegments + DBC de opendbc) | extracción, decodificación y reproducción |
| **OpenF1** | API pública con telemetría de la Fórmula 1 | descarga y reproducción histórica |

Además incluye un **generador sintético** de telemetría, que permite probar la
cadena completa sin ninguna fuente externa.

---

## Arquitectura

```
 fuentes                 transporte              persistencia            presentación
┌──────────────┐
│ F1 25 (UDP)  │──┐
├──────────────┤  │   ┌───────────┐   MQTT   ┌─────────────┐      ┌──────────────┐
│ CAN RAV4     │──┼──▶│ adaptador │────────▶ │  Mosquitto  │──┬─▶ │  consumidor  │
├──────────────┤  │   └───────────┘          └─────────────┘  │   └──────┬───────┘
│ OpenF1       │──┤   (contrato interno)                       │          ▼
├──────────────┤  │                                            │   ┌──────────────┐
│ generador    │──┘                                            │   │ TimescaleDB  │
└──────────────┘                                               │   └──────┬───────┘
                                                               │          ▼
                                                               │   ┌──────────────┐     ┌──────────┐
                                                               └─▶ │ API FastAPI  │───▶ │ tablero  │
                                                     (flujo en vivo)└──────────────┘     │   web    │
                                                                                        └──────────┘
```

1. Cada fuente tiene un **adaptador** (`adapters/`) que traduce su formato al
   contrato interno (`backend/models.py`).
2. Los mensajes viajan por **MQTT** (Mosquitto) con confirmación manual y
   sesión persistente, de modo que un consumidor caído no pierde datos.
3. El **consumidor** (`backend/mqtt_consumer.py`) los escribe por lotes en
   **TimescaleDB** (PostgreSQL con hipertabla comprimida).
4. La **API** (`backend/app.py`, FastAPI) sirve las sesiones guardadas, los
   análisis por vuelta y un flujo en vivo hacia el navegador.
5. El **tablero** (`dashboard/`) es HTML, CSS y JavaScript sin compilación.

---

## Estructura del repositorio

| carpeta | contenido |
| --- | --- |
| `backend/` | núcleo del sistema: API, consumidor MQTT, acceso a la base, decodificadores (UDP de F1 25, CAN), catálogo de sesiones, flujo en vivo, reconstrucción de recorrido |
| `backend/analisis/` | análisis telemétrico: vueltas, sectores, curvas, frenadas, tracción, delta entre conductores, degradación |
| `adapters/` | adaptadores de cada fuente al contrato interno: `f1_25.py`, `can_rav4.py`, `openf1.py` |
| `telemetry_generator/` | generador sintético de telemetría |
| `dashboard/` | tablero web (`index.html`, `styles.css`, `app.js`) |
| `database/` | migraciones SQL, numeradas en orden de aplicación (`000` a `008`) |
| `infra/` | `docker-compose.yml`, `Dockerfile` y configuración de Mosquitto |
| `scripts/` | herramientas de línea de comandos: captura, reproducción, carga de datos, mediciones y verificaciones. Ver [`scripts/README.md`](scripts/README.md) |
| `tests/` | suite de pruebas en Python (`unittest`) y arneses del tablero en JavaScript (`tests/js/`) |
| `informe/` | el informe del trabajo, en LaTeX |

No se versionan (ver `.gitignore`): `datasets/` (capturas y datos crudos),
`external/` (código de terceros), `logs/` (salida de ejecución) y `.env`.

---

## Requisitos

- **Docker** con Docker Compose v2
- **Python 3.12** o superior
- **Node.js** (sólo para los arneses de prueba del tablero)
- Opcional: **F1 25** en una PC o consola de la misma red, para capturar en vivo

---

## Puesta en marcha

Todo se corre desde la raíz del repositorio.

### Opción A — todo en contenedores

Levanta la base, el intermediario, la API y el consumidor:

```bash
mkdir logs
cp .env.example infra/.env      # y en infra/.env cambiar DB_PASSWORD
docker compose -f infra/docker-compose.yml --profile completo up -d --build
```

> La API se niega a arrancar si la base no es local y la contraseña es la de
> ejemplo; por eso hay que definir una propia en `infra/.env`.

Después, crear el esquema (una sola vez):

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt            # Windows: .venv\Scripts\pip
for f in database/*.sql; do .venv/bin/python scripts/apply_database_migration.py "$f"; done
```

El tablero queda en **http://127.0.0.1:8080/** (la API lo sirve desde el mismo
origen). Para capturar F1 25 se agrega el perfil `captura`.

### Opción B — desarrollo local

Sólo la base y el intermediario en contenedores; la aplicación corre en Python.

```bash
# 1. entorno de Python
python -m venv .venv
.venv/bin/pip install -r requirements.txt            # Windows: .venv\Scripts\pip
cp .env.example .env

# 2. base de datos e intermediario
mkdir logs
docker compose -f infra/docker-compose.yml up -d

# 3. esquema, en orden
for f in database/*.sql; do .venv/bin/python scripts/apply_database_migration.py "$f"; done

# 4. servicios (cada uno en su terminal)
.venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
.venv/bin/python scripts/run_mqtt_consumer.py --metrics-file logs/consumidor_metricas.json
cd dashboard && python -m http.server 3000 --bind 127.0.0.1
```

Abrir **http://127.0.0.1:3000/**. El tablero tiene que servirse en el puerto
3000: es el origen que la API admite por omisión (variable `CORS_ORIGENES`).

En PowerShell, las migraciones se aplican con:

```powershell
Get-ChildItem database\*.sql | Sort-Object Name | ForEach-Object {
    .venv\Scripts\python scripts\apply_database_migration.py $_.FullName }
```

En Windows, `scripts\activar_servicios.ps1` registra la API, el capturador y la
cola de cargas como tareas programadas; `scripts\desactivar_servicios.ps1` las
quita.

### Comprobar que anda

| qué | comando | resultado esperado |
| --- | --- | --- |
| API | `curl http://127.0.0.1:8000/health` | `200` |
| intermediario | `curl http://127.0.0.1:8000/live/status` | `"conectado": true` |
| sesiones | `curl "http://127.0.0.1:8000/sesiones?limite=5"` | una lista (vacía al principio) |
| topes de Mosquitto | `python scripts/verificar_topes_intermediario.py` | los topes declarados, medidos |

(Con la opción A el puerto de la API es 8080.)

---

## Cargar datos

La base arranca vacía. Las formas de llenarla:

| para | comando |
| --- | --- |
| probar la cadena sin datos externos | `python -m telemetry_generator.main` |
| capturar F1 25 en vivo | `python scripts/capturar_f1_25.py` y en el juego, *Telemetría UDP* apuntando a esta máquina, puerto 20777 |
| reproducir una captura de F1 25 | con el capturador escuchando, `python scripts/reproducir_captura_f1_25.py <archivo.f1raw>` la reemite por UDP |
| descargar y reproducir una sesión de OpenF1 | `python scripts/descargar_paquete_openf1.py --session-key <n>` y `python scripts/replay_openf1.py --session-key <n> --drivers <números> --replay-run-id <id> --publish` |
| reproducir tramas CAN | `python scripts/extraer_can.py` (requiere openpilot en `external/`) y `python scripts/reproducir_can.py` |

También se puede subir un archivo de captura desde el propio tablero.
Cada script documenta sus opciones con `--help`.

---

## Pruebas

```bash
python -m unittest discover -s tests          # suite de Python
for f in tests/js/*.js; do node "$f"; done    # arneses del tablero
```

Las pruebas que necesitan capturas reales (`datasets/`) se saltean solas
cuando esos archivos no están, y las que necesitan la base o el intermediario
requieren los contenedores levantados.

---

## Configuración

Todas las variables de entorno que lee el código, con su valor por omisión,
están en [`.env.example`](.env.example). Lo que ya está definido en el entorno
tiene prioridad sobre el archivo `.env`.
