"""Formato de captura cruda de telemetria F1 25 y reproduccion con fallos.

Por que se guarda el flujo crudo
--------------------------------
La captura desde la consola depende de hardware y de una sesion jugada: no se
puede repetir a voluntad. Guardar los datagramas **tal como llegaron**, antes de
interpretarlos, es lo que vuelve repetible un experimento que de otro modo
costaria otra sesion de pista cada vez que hubiera que corregir el
decodificador.

Es el mismo criterio con que el proyecto conserva los registros crudos del bus
CAN en lugar de guardar solo las senales ya decodificadas.

Formato del archivo
-------------------
Cabecera de archivo, 16 bytes::

    magia        8 bytes   b"F1RAWCAP"
    version      uint16    version del formato de archivo
    reservado    6 bytes   ceros

Despues, un registro por datagrama, sin relleno::

    desplazamiento  uint64   microsegundos desde el inicio de la captura
    longitud        uint32   bytes del datagrama
    carga util      N bytes  el datagrama tal como llego

El desplazamiento se guarda **relativo al inicio** y no como marca absoluta
para que la reproduccion no dependa de la fecha en que se capturo, y para que
dos capturas distintas sean comparables entre si.

Cada archivo lleva un archivo de metadatos al lado, con la huella `sha256` del
crudo, la version del juego, el formato UDP, la frecuencia configurada y el modo
de sesion. Sin esos datos la captura no es reproducible por un tercero.
"""

from __future__ import annotations

import hashlib
import json
import random
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

MAGIA = b"F1RAWCAP"
VERSION_FORMATO = 1
CABECERA_ARCHIVO_FMT = "<8sH6x"
CABECERA_ARCHIVO_TAMANO = struct.calcsize(CABECERA_ARCHIVO_FMT)
REGISTRO_FMT = "<QI"
REGISTRO_TAMANO = struct.calcsize(REGISTRO_FMT)


class ErrorCaptura(Exception):
    """Archivo de captura ilegible o de formato desconocido."""


@dataclass
class Datagrama:
    """Un datagrama con su desplazamiento desde el inicio de la captura."""

    desplazamiento_us: int
    carga: bytes


# --------------------------------------------------------------------------- #
# Escritura
# --------------------------------------------------------------------------- #

class EscritorCaptura:
    """Escribe una captura cruda de forma incremental.

    Se usa como contexto para que el archivo quede cerrado aunque la captura se
    interrumpa: una sesion cortada a la mitad sigue siendo una captura valida
    hasta el ultimo registro completo.
    """

    def __init__(self, ruta: str | Path) -> None:
        self.ruta = Path(ruta)
        self._archivo = None
        self.datagramas = 0
        self.bytes_carga = 0

    def __enter__(self) -> "EscritorCaptura":
        self._archivo = self.ruta.open("wb")
        self._archivo.write(struct.pack(CABECERA_ARCHIVO_FMT, MAGIA, VERSION_FORMATO))
        return self

    def __exit__(self, *_) -> None:
        if self._archivo is not None:
            self._archivo.close()
            self._archivo = None

    def escribir(self, desplazamiento_us: int, carga: bytes) -> None:
        """Agrega un datagrama a la captura."""

        if self._archivo is None:
            raise ErrorCaptura("El escritor debe usarse como contexto.")
        self._archivo.write(struct.pack(REGISTRO_FMT, desplazamiento_us, len(carga)))
        self._archivo.write(carga)
        self.datagramas += 1
        self.bytes_carga += len(carga)


def huella_sha256(ruta: str | Path) -> str:
    """Huella del archivo crudo, para citarlo con trazabilidad."""

    resumen = hashlib.sha256()
    with Path(ruta).open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(65536), b""):
            resumen.update(bloque)
    return resumen.hexdigest()


def escribir_metadatos(ruta_captura: str | Path, extra: dict | None = None) -> Path:
    """Escribe el archivo de metadatos junto a la captura.

    Incluye siempre la huella del crudo y el recuento de datagramas. Los datos
    de procedencia que solo conoce el operador —version del juego, formato UDP,
    frecuencia configurada, modo de sesion, circuito— se pasan en `extra` y
    quedan registrados sin interpretarse.
    """

    ruta = Path(ruta_captura)
    datos = {
        "formato_archivo": VERSION_FORMATO,
        "archivo": ruta.name,
        "bytes": ruta.stat().st_size,
        "sha256": huella_sha256(ruta),
        "datagramas": sum(1 for _ in leer_captura(ruta)),
    }
    datos.update(extra or {})
    destino = ruta.with_suffix(ruta.suffix + ".meta.json")
    destino.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")
    return destino


# --------------------------------------------------------------------------- #
# Lectura
# --------------------------------------------------------------------------- #

def leer_captura(ruta: str | Path) -> Iterator[Datagrama]:
    """Recorre una captura cruda sin cargarla entera en memoria.

    Un registro incompleto al final del archivo **se descarta en silencio**: es
    el resultado esperado de una captura interrumpida, y no una corrupcion. Lo
    que si es un error es que la cabecera no corresponda.
    """

    ruta = Path(ruta)
    with ruta.open("rb") as archivo:
        cabecera = archivo.read(CABECERA_ARCHIVO_TAMANO)
        if len(cabecera) < CABECERA_ARCHIVO_TAMANO:
            raise ErrorCaptura(f"Archivo demasiado corto para ser una captura: {ruta}")
        magia, version = struct.unpack(CABECERA_ARCHIVO_FMT, cabecera)
        if magia != MAGIA:
            raise ErrorCaptura(f"El archivo no es una captura F1 25: {ruta}")
        if version != VERSION_FORMATO:
            raise ErrorCaptura(
                f"Version de formato {version} desconocida; esta implementacion "
                f"lee la {VERSION_FORMATO}."
            )

        while True:
            encabezado = archivo.read(REGISTRO_TAMANO)
            if len(encabezado) < REGISTRO_TAMANO:
                return
            desplazamiento_us, longitud = struct.unpack(REGISTRO_FMT, encabezado)
            carga = archivo.read(longitud)
            if len(carga) < longitud:
                return
            yield Datagrama(desplazamiento_us, carga)


# --------------------------------------------------------------------------- #
# Reproduccion con inyeccion de fallos
# --------------------------------------------------------------------------- #

@dataclass
class PerfilDegradacion:
    """Degradacion controlada que se aplica sobre una captura real.

    A diferencia del generador propio, que produce datos sinteticos, esto
    degrada **trafico real capturado**. El escenario resultante conserva la
    forma del trafico verdadero y agrega solo la falla que se quiere estudiar.

    La semilla vuelve el resultado reproducible: la misma captura con la misma
    semilla produce exactamente la misma degradacion. Sin eso, un escenario
    experimental no se puede repetir, y repetirlo es la mitad de su valor.
    """

    probabilidad_descarte: float = 0.0   # 0,0 a 1,0
    jitter_us: int = 0                   # desviacion maxima, en mas o en menos
    retraso_us: int = 0                  # desplazamiento fijo de todo el flujo
    semilla: int = 0

    def validar(self) -> None:
        if not 0.0 <= self.probabilidad_descarte <= 1.0:
            raise ValueError("La probabilidad de descarte debe estar entre 0 y 1.")
        if self.jitter_us < 0:
            raise ValueError("El jitter no puede ser negativo; es una desviacion.")
        if self.retraso_us < 0:
            raise ValueError("El retraso no puede ser negativo.")


@dataclass
class MetricasReproduccion:
    """Recuento de lo que la reproduccion hizo con cada datagrama."""

    leidos: int = 0
    emitidos: int = 0
    descartados: int = 0

    def como_dict(self) -> dict:
        return {
            "leidos": self.leidos,
            "emitidos": self.emitidos,
            "descartados": self.descartados,
            "tasa_descarte": (self.descartados / self.leidos) if self.leidos else 0.0,
        }


def reproducir(
    ruta: str | Path,
    perfil: PerfilDegradacion | None = None,
    metricas: MetricasReproduccion | None = None,
) -> Iterator[Datagrama]:
    """Recorre una captura aplicando la degradacion indicada.

    Devuelve datagramas con su desplazamiento ya corregido. **No abre ningun
    socket**: emitir por red es responsabilidad de quien consuma este iterador,
    de modo que la reproduccion pueda probarse sin tocar la red.

    El orden se preserva incluso con jitter: el jitter altera el instante de
    cada datagrama, pero no los reordena. Reordenar es una falla distinta y
    mezclarlas impediria atribuir un efecto observado a una causa.
    """

    perfil = perfil or PerfilDegradacion()
    perfil.validar()
    metricas = metricas if metricas is not None else MetricasReproduccion()
    azar = random.Random(perfil.semilla)

    for datagrama in leer_captura(ruta):
        metricas.leidos += 1

        # El sorteo se consume siempre, aunque la probabilidad sea cero, para que
        # la secuencia de azar dependa solo de la semilla y de la cantidad de
        # datagramas, y no de los valores del perfil. Asi dos corridas con la
        # misma semilla y distinto descarte siguen siendo comparables.
        sorteo = azar.random()
        if perfil.probabilidad_descarte > 0.0 and sorteo < perfil.probabilidad_descarte:
            metricas.descartados += 1
            continue

        desvio = azar.randint(-perfil.jitter_us, perfil.jitter_us) if perfil.jitter_us else 0
        desplazamiento = max(0, datagrama.desplazamiento_us + perfil.retraso_us + desvio)

        metricas.emitidos += 1
        yield Datagrama(desplazamiento, datagrama.carga)
