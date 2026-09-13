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


def _declarado_en_el_metadato(ruta: Path) -> dict:
    """Lo que la captura dice de si misma, o nada si no lo dice."""

    meta = ruta.with_name(ruta.name + SUFIJO_ACOMPANANTE)
    if not meta.is_file():
        return {}
    try:
        d = json.loads(meta.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return d if isinstance(d, dict) else {}


def como_se_procesa(clase: str, ruta: Path) -> dict:
    """Que hay que pedir para que esto se procese. Lo decide el servidor.

    POR QUE NO LO ARMA QUIEN SUBE. Sin esto, el navegador tiene que partir
    `TOYOTA_RAV4_TSS2_sample_01.canraw` por un prefijo que conoce de memoria
    para reconstruir `{segmentos: ["sample_01"], plataforma: "TOYOTA_RAV4_TSS2"}`.
    Es un acuerdo entre dos lados escrito en uno solo, y se rompe el dia que una
    plataforma lleve un guion bajo de mas.

    Y NO HACE FALTA ADIVINAR NADA. El `.meta.json` de una captura del bus
    **declara** su plataforma y su segmento; el de una del simulador declara su
    procedencia. La derivacion sale del archivo y no del nombre, que es la misma
    regla que gobierna la clasificacion.

    Devuelve siempre un diccionario con `ruta`, `metodo`, `cuerpo` y `motivo`.
    Cuando `ruta` es `None` hay un motivo escrito: **no saber como procesar algo
    es una respuesta, y decirla vale mas que ofrecer un boton que falla.**
    """

    declarado = _declarado_en_el_metadato(ruta)

    if clase == "can_crudo":
        plataforma = declarado.get("plataforma")
        segmento = declarado.get("segmento")
        if not plataforma or not segmento:
            return {"ruta": None, "metodo": None, "cuerpo": None,
                    "motivo": ("la captura no declara plataforma y segmento en su "
                               "`.meta.json`: sin eso no se puede decir que cargar, "
                               "y partir el nombre seria adivinarlo")}
        return {"ruta": "/can/importar", "metodo": "POST",
                "cuerpo": {"segmentos": [segmento], "plataforma": plataforma,
                           "etapa": "cargar"},
                "motivo": "la plataforma y el segmento salen de lo que la captura declara"}

    if clase == "f1_25_crudo":
        return {"ruta": "/f1_25/republicar", "metodo": "POST",
                "cuerpo": {"captura": ruta.name},
                "motivo": "se reinyecta por el mismo camino que la telemetria en vivo"}

    if clase == "paquete_openf1":
        return {"ruta": None, "metodo": None, "cuerpo": None,
                "motivo": ("hay que descomprimirlo para saber que sesion es: la "
                           "`session_key` la declara el `session.json` de adentro")}

    return {"ruta": None, "metodo": None, "cuerpo": None,
            "motivo": "clase sin camino de procesamiento declarado"}


#: Donde la ruta de importacion de OpenF1 busca los paquetes.
PAQUETES_OPENF1 = RAIZ_DE_DATOS / "OpenF1" / "raw"

#: MARCA QUE DISTINGUE UN PAQUETE DE UN RESTO.
#:
#: `abrir_paquete` no pisa un destino ocupado, y esa guarda salvo los 273 MB de
#: Silverstone. Pero no distinguia «hay un paquete de verdad» de «quedo lo que
#: dejo una importacion que no llego»: el 2026-09-13 una importacion fallo por
#: campos faltantes en el `session.json`, los archivos quedaron ocupando el
#: destino, y arreglar el comprimido y volver a subirlo daba 422. Un callejon.
#:
#: La distincion no se adivina: se escribe. Un paquete subido queda marcado
#: hasta que **alguien logra importarlo**, y ese alguien borra la marca
#: ---`session_processor.import_validated_package`---. Un paquete descargado
#: nunca la tuvo, de modo que sigue siendo intocable.
SIN_IMPORTAR = ".subido_sin_importar"


def abrir_paquete(comprimido: Path) -> tuple[bool, dict]:
    """Descomprime un paquete de sesion, mirandolo antes de desparramarlo.

    DESCOMPRIMIR ES ACEPTAR CONTENIDO AJENO. Dos cosas que un comprimido puede
    intentar y que aqui no se le permiten:

    * **escribir fuera de su destino**, con entradas como `../../etc/passwd`. Es
      viejo, conocido, y sigue funcionando en todo codigo que confie en el nombre
      de la entrada. Se comprueban **todas** antes de extraer una sola, y basta
      una para rechazar el paquete entero: un comprimido que intenta salirse no
      es un paquete al que le sobra un archivo, es uno en el que no se confia.
    * **no ser lo que dice.** Sin `session.json` no es un paquete de sesion, y
      darse cuenta despues de haberlo desparramado deja un directorio con nombre
      de sesion y sin sesion adentro.

    Se abre en un area de paso, se mira, y recien entonces se mueve a donde
    `/openf1/importar` lo busca ---`raw/<ano>/<session_key>/`--- de modo que esa
    ruta sigue funcionando sin cambios.
    """

    import shutil
    import tempfile
    import zipfile

    if not zipfile.is_zipfile(comprimido):
        return False, {"motivo": "el archivo no es un comprimido que se pueda abrir"}

    with zipfile.ZipFile(comprimido) as z:
        # TODAS LAS ENTRADAS ANTES DE EXTRAER NINGUNA.
        for entrada in z.namelist():
            limpia = entrada.replace("\\", "/")
            if limpia.startswith("/") or ".." in limpia.split("/"):
                return False, {"motivo": ("una entrada del comprimido apunta fuera "
                                          "de su destino: %r" % entrada)}
        nombres = z.namelist()
        sesiones = [n for n in nombres if n.replace("\\", "/").endswith("session.json")]
        if not sesiones:
            return False, {"motivo": ("el comprimido no trae `session.json`, que es "
                                      "el unico archivo que un paquete de sesion "
                                      "tiene que tener")}
        try:
            declarado = json.loads(z.read(sesiones[0]).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as error:
            return False, {"motivo": "`session.json` no se puede leer: %s" % error}
        if not isinstance(declarado, dict):
            return False, {"motivo": "`session.json` no contiene un objeto"}
        clave = declarado.get("session_key")
        if not isinstance(clave, int) or isinstance(clave, bool):
            return False, {"motivo": ("`session_key` tiene que ser un entero y vale "
                                      "%r" % (clave,))}
        ano = declarado.get("year")
        ano = str(ano) if isinstance(ano, int) else "sin_ano"

        # LA RAIZ DEL COMPRIMIDO SE DESCARTA. Un paquete comprimido desde afuera
        # trae un directorio de mas; uno comprimido desde adentro no. Se toma
        # como raiz el directorio donde esta `session.json`, que es el unico
        # punto de referencia que los dos casos comparten.
        raiz_interna = sesiones[0].replace("\\", "/").rsplit("session.json", 1)[0]

        AREA_DE_PASO.mkdir(parents=True, exist_ok=True)
        provisional = Path(tempfile.mkdtemp(prefix="paquete_", dir=str(AREA_DE_PASO)))
        try:
            for entrada in nombres:
                limpia = entrada.replace("\\", "/")
                if limpia.endswith("/"):
                    continue
                if raiz_interna and not limpia.startswith(raiz_interna):
                    continue
                relativa = limpia[len(raiz_interna):]
                if not relativa:
                    continue
                destino_archivo = provisional / nombre_seguro(relativa)
                with z.open(entrada) as origen, destino_archivo.open("wb") as salida:
                    shutil.copyfileobj(origen, salida)

            destino = PAQUETES_OPENF1 / ano / str(clave)
            # NO SE PISA UN PAQUETE QUE YA ESTA.
            #
            # El destino sale de la `session_key` que declara el comprimido, o
            # sea de contenido que alguien subio. Borrar lo que haya ahi para
            # hacerle lugar convierte una subida en una operacion destructiva
            # gobernada por el archivo: subir un comprimido que diga `9947`
            # bastaria para llevarse los 273 MB de Silverstone.
            #
            # Y no es teorico: **paso el 2026-09-12**. Una prueba de este mismo
            # modulo uso la clave 9939 ---que era un paquete real--- y el
            # `rmtree` que habia aqui se llevo los 60 MB del paquete de Spa. El
            # contexto ya importado sobrevivio en la base; los JSON crudos hubo
            # que volver a descargarlos.
            # Un resto de una subida que nunca llego a importarse no es un
            # paquete: se reemplaza. Lo que no se pisa es lo que alguien
            # descargo o logro importar, que es lo que la guarda protege.
            resto = destino.exists() and (destino / SIN_IMPORTAR).exists()
            if destino.exists() and not resto:
                return False, {"motivo": (
                    "ya hay un paquete para la sesion %s del %s en %s. No se "
                    "pisa: si hay que reemplazarlo, se borra a proposito y se "
                    "vuelve a subir." % (clave, ano, destino))}
            if resto:
                shutil.rmtree(destino, ignore_errors=True)
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(provisional), str(destino))
            (destino / SIN_IMPORTAR).write_text("", encoding="utf-8")
        finally:
            if provisional.exists():
                shutil.rmtree(provisional, ignore_errors=True)

    archivos = sorted(p.name for p in destino.iterdir() if p.is_file())
    return True, {
        "session_key": clave,
        "ano": ano,
        "destino": str(destino),
        "archivos": len(archivos),
        "tiene": archivos[:30],
        "motivo": "se abrio donde la ruta de importacion busca los paquetes",
    }


#: Donde espera lo que llego incompleto. No es una papelera: lo que hay aqui
#: sirve para reintentar, y por eso no se borra.
AREA_DESMENTIDA = AREA_DE_PASO / "desmentido"


def apartar_lo_desmentido(captura: Path) -> str | None:
    """Saca de `datasets/` una captura a la que su metadato desmiente.

    POR QUE HACE FALTA, Y ES UNA CONSECUENCIA DEL ORDEN. El acompanante llega
    **despues** de la captura, por obligacion: sin la captura no tiene donde ir.
    De modo que la captura ya esta guardada cuando recien se la puede comparar
    contra lo que declara. Si la comparacion falla, lo que queda en disco es un
    archivo truncado con nombre de dato ---justo lo que el area de paso existe
    para evitar---.

    NI SE BORRA NI SE QUEDA. No se borra porque los bytes que llegaron sirven
    para reintentar, y una subida de doscientos megabytes cortada al final no se
    tira. No se queda porque en `datasets/` solo vive lo que se puede usar.
    Vuelve al area de paso con su acompanante, y la respuesta dice donde esta.

    Devuelve la ruta nueva, o `None` si no habia nada que apartar: **no
    verificable no es desmentido**, y una captura sin metadatos se queda donde
    esta.
    """

    meta = captura.with_name(captura.name + SUFIJO_ACOMPANANTE)
    if not meta.is_file():
        return None
    acepta, _motivo = verificar(captura)
    if acepta:
        return None

    AREA_DESMENTIDA.mkdir(parents=True, exist_ok=True)
    destino = AREA_DESMENTIDA / captura.name
    captura.replace(destino)
    meta.replace(AREA_DESMENTIDA / meta.name)
    return str(destino)
