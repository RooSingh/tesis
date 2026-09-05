"""Formato propio para tramas CAN grabadas.

Por que existe
--------------
Las tramas del conjunto `commaCarSegments` vienen en `rlog.zst`, que solo se lee
con la biblioteca de openpilot: **1,8 GB de dependencia**, mas el repositorio de
`opendbc`, mas dos rutas agregadas a mano al camino de importacion. Se comprobo
ademas que el esquema no se puede cargar por fuera de ese entorno: el proceso
muere sin excepcion.

Depender de eso para **leer** el dato ata todo lo que se construya encima. Si la
carpeta se mueve o la biblioteca cambia, el adaptador deja de funcionar y las
pruebas dejan de correr, aunque las tramas sigan intactas.

De modo que se extrae **una sola vez** a un formato que este trabajo controla, y
todo lo demas lee de ahi. La dependencia se necesita en la extraccion y en
ningun otro lugar.

Es el mismo criterio que el trabajo ya aplico a la fuente simulada con `.f1raw`,
donde probo su valor dos veces: permitio rehacer la interpretacion de una captura
sin volver a medirla. Aplicarlo a un segundo protocolo lo convierte de una
decision conveniente en un criterio de arquitectura.

Que guarda, y que no
--------------------
Guarda **la trama tal como se recibio**: instante, identificador, bus de origen y
bytes. No guarda nada interpretado. Decodificar es tarea del adaptador, y
mantenerlo asi es lo que permite corregir una interpretacion equivocada sin
tocar el registro, que es exactamente lo que hizo falta con la fuente simulada.
"""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

#: Marca del formato. Ocho bytes, como en el formato de la fuente simulada, para
#: que un archivo truncado o de otro tipo se rechace en la primera lectura.
MAGIA = b"CANRAWCP"
VERSION_FORMATO = 1

CABECERA_ARCHIVO_FMT = "<8sH6x"
CABECERA_ARCHIVO_TAMANO = struct.calcsize(CABECERA_ARCHIVO_FMT)

#: Instante en nanosegundos desde el inicio del segmento, identificador de la
#: trama, bus de origen y longitud de los datos.
#:
#: El instante va en nanosegundos y no en microsegundos porque **es la unidad en
#: que el origen lo entrega**: convertirlo aca perderia resolucion antes de que
#: nadie decida que no la necesita.
REGISTRO_FMT = "<QIBB"
REGISTRO_TAMANO = struct.calcsize(REGISTRO_FMT)


@dataclass(frozen=True)
class Trama:
    """Una trama CAN tal como se grabo."""

    instante_ns: int
    identificador: int
    bus: int
    datos: bytes


class ErrorCaptura(Exception):
    """El archivo no es una captura CAN legible."""


class EscritorCaptura:
    """Escribe tramas en el formato propio.

    Se usa como contexto para que el archivo quede cerrado incluso si la
    extraccion falla a la mitad: media captura legible vale mas que ninguna.
    """

    def __init__(self, ruta: str | Path) -> None:
        self.ruta = Path(ruta)
        self.tramas = 0
        self._archivo = None

    def __enter__(self) -> "EscritorCaptura":
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self._archivo = self.ruta.open("wb")
        self._archivo.write(struct.pack(CABECERA_ARCHIVO_FMT, MAGIA, VERSION_FORMATO))
        return self

    def __exit__(self, *_excepcion) -> None:
        if self._archivo is not None:
            self._archivo.close()
            self._archivo = None

    def escribir(self, instante_ns: int, identificador: int, bus: int,
                 datos: bytes) -> None:
        if self._archivo is None:
            raise ErrorCaptura("el escritor no esta abierto")
        if len(datos) > 255:
            raise ErrorCaptura(
                f"trama de {len(datos)} bytes: excede lo que el formato declara"
            )
        self._archivo.write(
            struct.pack(REGISTRO_FMT, instante_ns, identificador, bus, len(datos))
        )
        self._archivo.write(datos)
        self.tramas += 1


def leer_captura(ruta: str | Path) -> Iterator[Trama]:
    """Recorre las tramas de una captura, sin cargarla entera en memoria.

    Un segmento son cientos de miles de tramas: materializarlas en una lista
    haria que el consumo dependiera del tamano del archivo y no del trabajo.
    """

    ruta = Path(ruta)
    with ruta.open("rb") as archivo:
        cabecera = archivo.read(CABECERA_ARCHIVO_TAMANO)
        if len(cabecera) < CABECERA_ARCHIVO_TAMANO:
            raise ErrorCaptura(f"{ruta.name}: archivo mas corto que su cabecera")
        magia, version = struct.unpack(CABECERA_ARCHIVO_FMT, cabecera)
        if magia != MAGIA:
            raise ErrorCaptura(f"{ruta.name}: no es una captura CAN de este trabajo")
        if version != VERSION_FORMATO:
            raise ErrorCaptura(
                f"{ruta.name}: formato version {version}; este lector lee "
                f"la {VERSION_FORMATO}."
            )
        while True:
            encabezado = archivo.read(REGISTRO_TAMANO)
            if not encabezado:
                return
            if len(encabezado) < REGISTRO_TAMANO:
                raise ErrorCaptura(f"{ruta.name}: registro truncado al final")
            instante_ns, identificador, bus, longitud = struct.unpack(
                REGISTRO_FMT, encabezado)
            datos = archivo.read(longitud)
            if len(datos) < longitud:
                raise ErrorCaptura(f"{ruta.name}: datos truncados al final")
            yield Trama(instante_ns, identificador, bus, datos)


def huella_sha256(ruta: str | Path) -> str:
    """Hash del archivo, para que una captura pueda citarse sin ambiguedad."""

    resumen = hashlib.sha256()
    with Path(ruta).open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
            resumen.update(bloque)
    return resumen.hexdigest()


def escribir_metadatos(ruta_captura: str | Path, extra: dict | None = None) -> Path:
    """Escribe el archivo de procedencia junto a la captura.

    La procedencia acompana al archivo y no se guarda aparte: separarlos permite
    que uno se pierda o quede desactualizado respecto del otro.
    """

    ruta_captura = Path(ruta_captura)
    metadatos = {
        "formato_archivo": VERSION_FORMATO,
        "archivo": ruta_captura.name,
        "bytes": ruta_captura.stat().st_size,
        "sha256": huella_sha256(ruta_captura),
    }
    metadatos.update(extra or {})
    destino = ruta_captura.with_suffix(ruta_captura.suffix + ".meta.json")
    destino.write_text(json.dumps(metadatos, indent=2, ensure_ascii=False),
                       encoding="utf-8")
    return destino
