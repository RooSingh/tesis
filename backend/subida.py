# -*- coding: utf-8 -*-
"""Recibir un archivo por la interfaz, decidir que es y verificarlo.

POR QUE EXISTE. Los botones de importar del tablero no suben nada: piden un
identificador ---una `session_key`, unos nombres de segmento--- y procesan lo que
**ya esta** en el disco del servidor. De modo que incorporar una sesion exige
copiar el archivo a mano a la maquina y recien despues apretar el boton. El
boton dice «importar» y hace «procesar lo que ya trajiste».

Este modulo es la mitad que faltaba: la que va del navegador al disco.

LAS DOS REGLAS QUE SOSTIENE, y son las que distinguen una subida de un `scp`:

1. **Se decide que es antes de guardarlo donde va.** Lo que no se reconoce no
   llega a `datasets/`: se rechaza con el motivo, desde el area de paso.
   Guardarlo primero y mirarlo despues deja basura con nombre de dato, y despues
   nadie sabe si ese archivo es una captura o un intento fallido.
2. **Lo que llega se compara contra lo que el propio archivo declara.** Las
   capturas de este proyecto traen un `.meta.json` con `bytes` y `sha256`. Una
   subida truncada tiene **exactamente el aspecto** de una completa hasta que
   alguien compara, y comparar es gratis porque la huella ya viaja.

POR QUE SE CLASIFICA POR CONTENIDO Y NO POR NOMBRE. El nombre lo elige quien
sube. Aceptar por extension es aceptar su palabra. Los formatos propios de este
proyecto empiezan con un numero magico ---`CANRAWCP`, `F1RAWCAP`--- y eso si es
del archivo.

Y POR QUE NO SE USA `multipart`. FastAPI recibe archivos con `UploadFile`, que
exige la dependencia `python-multipart`, que no esta en `requirements.txt`.
Agregarla obliga a un `pip install` en cada despliegue y a reconstruir la imagen
del contenedor. El cuerpo crudo de un `POST` alcanza para lo mismo: el navegador
lo manda con `fetch(url, {method: "POST", body: archivo})` y **sigue teniendo la
barra de progreso**, porque la progresion de subida la da el objeto de peticion
del navegador y no el formato del cuerpo. Una dependencia menos por una linea
distinta en el cliente.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

#: Todo lo que se suba cae bajo este arbol y no puede salirse de el.
RAIZ_DE_DATOS = Path(__file__).resolve().parent.parent / "datasets"

#: Donde espera cada subida antes de que se decida si se acepta. Lo que se
#: rechaza muere aca y nunca entra a `datasets/`.
AREA_DE_PASO = RAIZ_DE_DATOS / ".subiendo"

#: Cuanto se lee para clasificar. Los numeros magicos de este proyecto son de
#: ocho bytes; se leen dieciseis por si alguno crece.
BYTES_PARA_CLASIFICAR = 16

#: LAS CLASES QUE SE ACEPTAN, CON SU EVIDENCIA Y SU DESTINO.
#:
#: `magico` es lo unico que decide. La extension figura para poder ofrecerla en
#: el dialogo de archivos del navegador, no para aceptar por ella.
FORMATOS: tuple[dict, ...] = (
    {
        "clase": "can_crudo",
        "fuente": "can_real_replay",
        "extension": ".canraw",
        "magico": b"CANRAWCP",
        "carpeta": RAIZ_DE_DATOS / "can" / "capturas",
        "que_es": "Una captura del bus de un vehiculo real, ya convertida al "
                  "formato de este proyecto.",
        "como_se_obtiene": "Extrayendo un registro de openpilot con la etapa "
                           "`extraer` de la importacion CAN. El archivo viene "
                           "acompanado de su `.meta.json`.",
        "acompana": ".meta.json",
    },
    {
        "clase": "f1_25_crudo",
        "fuente": "f1_25_udp_simulation",
        "extension": ".f1raw",
        "magico": b"F1RAWCAP",
        "carpeta": RAIZ_DE_DATOS / "f1_25" / "capturas",
        "que_es": "Una captura cruda de los datagramas que emite el simulador, "
                  "tal como llegaron y sin interpretar.",
        "como_se_obtiene": "La escribe el capturador al conducir una sesion. "
                           "Viene acompanada de su `.meta.json`, que declara "
                           "circuito, modo, ayudas y dificultad.",
        "acompana": ".meta.json",
    },
    {
        "clase": "paquete_openf1",
        "fuente": "openf1_historical_replay",
        "extension": ".zip",
        "magico": b"PK\x03\x04",
        "carpeta": RAIZ_DE_DATOS / "OpenF1" / "subidos",
        "que_es": "Un paquete de sesion de la fuente deportiva, comprimido: "
                  "`session.json` y los archivos de contexto y telemetria que "
                  "esa sesion tenga.",
        "como_se_obtiene": "Comprimiendo el directorio de la sesion. El unico "
                           "archivo obligatorio es `session.json`; los once de "
                           "contexto son opcionales y su ausencia se declara.",
        "acompana": None,
    },
)

_POR_CLASE = {f["clase"]: f for f in FORMATOS}


def formatos() -> dict:
    """Que se puede subir, para que la pantalla lo diga antes de pedir nada.

    Sin esto el dialogo de archivos acepta cualquier cosa y el motivo del
    rechazo llega despues de haber subido seiscientos megabytes.
    """

    return {
        "formatos": [
            {k: v for k, v in f.items() if k not in ("magico", "carpeta")}
            for f in FORMATOS
        ],
        "criterio": ("se reconoce por el contenido y no por el nombre: la "
                     "extension la elige quien sube"),
    }


def clasificar(nombre: str, primeros_bytes: bytes) -> str | None:
    """Que es esto, mirando el archivo y no como se llama.

    `nombre` entra solo para poder informarlo en el rechazo; no participa de la
    decision. Un `.canraw` con cualquier otro contenido no es una captura, y un
    archivo sin extension que empieza con el numero magico si lo es.
    """

    if not primeros_bytes:
        return None
    for f in FORMATOS:
        if primeros_bytes.startswith(f["magico"]):
            return f["clase"]
    return None


def verificar(ruta: Path) -> tuple[bool, str]:
    """Compara lo que llego contra lo que el propio archivo declara.

    Devuelve `(acepta, motivo)`. **Sin metadatos acepta y lo dice**: no
    verificable no es lo mismo que verificado, y tratar la ignorancia como un
    fallo rechazaria archivos legitimos que no traen huella.
    """

    meta = ruta.with_name(ruta.name + ".meta.json")
    if not meta.is_file():
        return True, ("el archivo no declara tamano ni huella: se acepta sin "
                      "verificar, y eso queda dicho")
    try:
        declarado = json.loads(meta.read_text(encoding="utf-8"))
    except (ValueError, OSError) as error:
        return False, "los metadatos no se pueden leer: %s" % error

    bytes_declarados = declarado.get("bytes")
    reales = ruta.stat().st_size
    if isinstance(bytes_declarados, int) and bytes_declarados != reales:
        faltan = bytes_declarados - reales
        return False, ("llegaron %d bytes de los %d que el archivo declara: %s"
                       % (reales, bytes_declarados,
                          "faltan %d" % faltan if faltan > 0
                          else "sobran %d" % -faltan))

    huella_declarada = declarado.get("sha256")
    if isinstance(huella_declarada, str) and huella_declarada:
        h = hashlib.sha256()
        with ruta.open("rb") as f:
            for bloque in iter(lambda: f.read(1024 * 1024), b""):
                h.update(bloque)
        if h.hexdigest() != huella_declarada:
            return False, ("el tamano coincide y la huella no: el contenido "
                           "cambio en el camino")
        return True, "tamano y huella coinciden con lo que el archivo declara"
    return True, "el tamano coincide; el archivo no declara huella"


#: Lo que se admite en un nombre de archivo. Todo lo demas se reemplaza.
_NOMBRE_LIMPIO = re.compile(r"[^A-Za-z0-9._-]")


def nombre_seguro(nombre: str) -> str:
    """Un nombre que no puede elegir donde escribir.

    Quien sube elige el nombre, y un nombre es una ruta si uno lo deja serlo.
    Se descarta todo lo que sea directorio y se limpia el resto; `..` deja de
    significar nada al quedarse sin barras.
    """

    base = nombre.replace("\\", "/").rsplit("/", 1)[-1]
    base = _NOMBRE_LIMPIO.sub("_", base).lstrip(".")
    return base or "sin_nombre"


#: Sufijo del archivo que acompana a una captura y declara lo que hay dentro.
SUFIJO_ACOMPANANTE = ".meta.json"


def es_acompanante(nombre: str) -> bool:
    """Si esto son los metadatos de una captura y no una captura."""

    return nombre_seguro(nombre).endswith(SUFIJO_ACOMPANANTE)


def raiz_del_acompanante(nombre: str) -> str:
    """De `x.canraw.meta.json` saca `x.canraw`."""

    limpio = nombre_seguro(nombre)
    return limpio[: -len(SUFIJO_ACOMPANANTE)] if es_acompanante(limpio) else limpio


def donde_espera_su_captura(nombre: str) -> Path | None:
    """Junto a que captura ya subida va este acompanante, si alguna.

    Los metadatos no tienen numero magico ---son JSON--- y por eso no se
    clasifican por contenido: se aceptan **solo** si la captura que describen ya
    esta. Un `.meta.json` suelto no es nada y no se guarda.
    """

    raiz = raiz_del_acompanante(nombre)
    for formato in FORMATOS:
        candidata = formato["carpeta"] / raiz
        if candidata.is_file():
            return candidata
    return None


def destino_de(clase: str, nombre: str) -> Path:
    """Donde cae esta clase de archivo. El servidor decide, no quien sube."""

    formato = _POR_CLASE.get(clase)
    if formato is None:
        raise ValueError("clase desconocida: %r" % clase)
    return formato["carpeta"] / nombre_seguro(nombre)
