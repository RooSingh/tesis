# -*- coding: utf-8 -*-
"""Que es cada sesion: circuito, tipo, clima y vueltas.

EL HUECO QUE CIERRA
-------------------
La base guarda la procedencia **tecnica** de cada mensaje ---identificador de
sesion, paquete, marco, los dos relojes--- y nada que diga **que es** esa
sesion. Una clasificacion y una carrera se ven iguales en la lista: dos
identificadores numericos con muchas filas.

El dato existe y esta derivado. El capturador lo lee del propio flujo ---del
paquete de sesion--- y lo escribe en el archivo de metadatos de cada captura:
circuito, tipo de sesion, modo de juego, clima, temperaturas, vueltas totales y
dificultad. Al 2026-09-07 hay **69 capturas y las 69 lo declaran**.

Lo que faltaba era que ese archivo cruzara a la consulta. Es la misma clase de
hueco que dejo trece senales de ochenta y nueve fuera de la persistencia:
informacion derivada correctamente que no atraviesa una frontera.

COMO SE UNE
-----------
Por `session_uid`. El identificador de la base es `f1_25:session:<uid>` y el
metadato de captura declara ese mismo `uid` en su procedencia. No hace falta
adivinar por fecha ni por nombre de archivo.

QUE NO HACE
-----------
No copia nada a la base. Lee los archivos, que son la fuente, y los deja donde
estan. Persistir la procedencia es una decision de esquema que corresponde a
otra jornada; esto la hace consultable mientras tanto, sin adelantarse.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

#: Donde viven los metadatos de captura.
DIRECTORIO = Path(__file__).resolve().parent.parent / "datasets" / "f1_25" / "capturas"

#: Cuanto se conserva el indice antes de releer el directorio.
#:
#: La razon original era que los archivos solo cambian al capturar, y que eso no
#: ocurre mientras alguien consulta. **Dejo de ser cierto**: el capturador ahora
#: anota la procedencia apenas el flujo la declara, en vez de esperar al cierre,
#: de modo que los metadatos aparecen y se reescriben justo mientras se mira.
#: Con cinco minutos de vigencia, una sesion en vivo se seguia llamando «sin
#: procedencia declarada» hasta bastante despues de que el juego hubiera dicho
#: que era Monte Carlo.
#:
#: El plazo se conserva ---releer el directorio en cada consulta seria caro--- y
#: se le agrega la comprobacion de abajo, que cuesta un `stat` por archivo.
VIGENCIA_S = 300.0

#: Cuanto puede separarse el arranque de una adquisicion del de su captura.
TOLERANCIA_S = 1.0

#: Como se lee cada tipo de sesion. Las claves son las que escribe el
#: capturador, derivadas del identificador oficial del paquete de sesion.
LECTURA_DEL_TIPO = {
    "practica-corta": ("Práctica", "practica"),
    "practica-1": ("Práctica 1", "practica"),
    "practica-2": ("Práctica 2", "practica"),
    "practica-3": ("Práctica 3", "practica"),
    "clasificacion-1": ("Clasificación 1", "clasificacion"),
    "clasificacion-2": ("Clasificación 2", "clasificacion"),
    "clasificacion-3": ("Clasificación 3", "clasificacion"),
    "clasificacion-corta": ("Clasificación corta", "clasificacion"),
    "sprint-shootout-1": ("Sprint shootout 1", "sprint"),
    "sprint-shootout-2": ("Sprint shootout 2", "sprint"),
    "sprint-shootout-3": ("Sprint shootout 3", "sprint"),
    "carrera": ("Carrera", "carrera"),
    "carrera-2": ("Carrera 2", "carrera"),
    "carrera-sprint": ("Carrera sprint", "sprint"),
    "contrarreloj": ("Contrarreloj", "contrarreloj"),
}

#: (cuando se armo, procedencias, parrillas, mtime mas reciente al armarlo).
#: El cuarto es lo que permite notar que un metadato cambio sin releerlos.
_CACHE: tuple[float, dict[str, dict], dict[str, list[dict]], float] | None = None


#: Los campos de cada participante que salen de este modulo, y ningun otro.
#:
#: LO QUE QUEDA AFUERA, A PROPOSITO. `equipo_id` es el codigo interno del
#: paquete y no dice nada que `equipo` no diga mejor. `plataforma` ---PlayStation,
#: PC--- describe **a la persona que sostiene el control**, no al piloto que la
#: sesion declara: es de otra naturaleza que el resto y no hace falta para
#: identificar un vehiculo.
#:
#: Devolver el metadato entero seria mas corto de escribir y peor: publicaria
#: por descuido cualquier campo que el capturador agregue manana.
CAMPOS_DE_LA_PARRILLA = ("indice", "nombre", "numero", "equipo", "es_ia")


def _parrilla_legible(proc: dict) -> dict | None:
    """La parrilla del metadato, proyectada a lo que la consulta necesita.

    QUE ES Y QUE NO ES. Es **quien es cada vehiculo de la sesion**, derivado del
    paquete de participantes: nombre, numero de carrera, equipo, y si lo conduce
    la maquina. No es telemetria: conocer el nombre de un rival no implica tener
    una sola de sus señales, y las dos cosas se declaran por separado.

    Una entrada sin `indice` no se puede unir a ningun vehiculo y una sin
    `nombre` no identifica a nadie: las dos se descartan en vez de completarse
    con un valor inventado.
    """
    crudas = proc.get("parrilla")
    if not isinstance(crudas, list) or not crudas:
        return None

    vehiculos = []
    for v in crudas:
        if not isinstance(v, dict):
            continue
        indice = v.get("indice")
        nombre = v.get("nombre")
        if not isinstance(indice, int) or not isinstance(nombre, str) or not nombre.strip():
            continue
        vehiculos.append({c: v.get(c) for c in CAMPOS_DE_LA_PARRILLA})
    if not vehiculos:
        return None

    return {
        "vehiculos": vehiculos,
        "vehiculos_en_carrera": proc.get("vehiculos_en_carrera_al_leer"),
        "origen": "metadato de captura, derivado del paquete de participantes",
        "es_una_foto": (
            "el paquete de participantes describe el momento en que se lo leyo, "
            "no quien tuvo el control durante toda la sesion"),
    }


def _ventana_de_captura(datos: dict) -> tuple[str | None, float | None]:
    """Cuando empezo la captura y cuanto duro, para poder ubicarla en el tiempo.

    Es lo que permite decir a que adquisicion pertenece un sidecar cuando hay
    mas de uno con el mismo `session_uid`: el instante en que el capturador
    empezo a escribir es el mismo con el que entra la primera fila a la base.
    """
    inicio = datos.get("inicio_utc")
    duracion = datos.get("duracion_s")
    return (inicio if isinstance(inicio, str) else None,
            float(duracion) if isinstance(duracion, (int, float)) else None)


def _leer_uno(ruta: Path) -> list[tuple[str, dict, dict | None]]:
    """Lee un metadato de captura y devuelve **cada** sesion que declara.

    UNA CAPTURA NO ES UNA SESION. El juego le da otro `session_uid` a cada
    sesion nueva y el capturador sigue escribiendo el mismo archivo. La
    procedencia se derivaba una vez por captura, de modo que solo la sesion de
    esa lectura quedaba nombrada. Medido el 2026-09-11: de las 222 sesiones de
    F1 25 del catalogo, **170 sin procedencia**, y 168 de ellas con su
    identificador dentro de algun crudo. Pasa en los dos modos: 7 de 26 capturas
    de un conductor y 25 de 43 de dos conductores atraviesan mas de una sesion.

    `sesiones_en_la_captura` trae la procedencia de cada una, derivada de sus
    propios paquetes: el tipo de sesion y la parrilla pueden cambiar de una a
    otra. La procedencia principal se sigue leyendo como antes, de modo que un
    metadato sin la lista nueva declara exactamente lo mismo que declaraba.
    """
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []

    salida = []
    proc = datos.get("procedencia") or {}
    principal = _una_sesion(datos, proc, datos.get("duracion_s"))
    if principal is not None:
        salida.append(principal)

    vistos = {proc.get("session_uid")}
    for tramo in datos.get("sesiones_en_la_captura") or []:
        if not isinstance(tramo, dict):
            continue
        propia = tramo.get("procedencia") or {}
        uid = tramo.get("session_uid", propia.get("session_uid"))
        # Una sesion que no declaro su tipo ---un menu, un arranque vacio--- no
        # tiene nada que describir, y la principal ya describe la suya.
        if uid is None or uid in vistos or not propia.get("disponible"):
            continue
        vistos.add(uid)
        desde, hasta = tramo.get("desde_s"), tramo.get("hasta_s")
        duracion = (hasta - desde if isinstance(desde, (int, float))
                    and isinstance(hasta, (int, float)) else None)
        una = _una_sesion(datos, dict(propia, session_uid=uid), duracion,
                          tramo=(desde, hasta))
        if una is not None:
            salida.append(una)
    return salida


def _una_sesion(datos: dict, proc: dict, duracion: Any,
                tramo: tuple | None = None) -> tuple[str, dict, dict | None] | None:
    """La procedencia y la parrilla de una sesion de la captura.

    `duracion` es la de la sesion y no la del archivo: con varias sesiones en
    una captura, «gana la mas larga» tiene que comparar lo que duro cada una.
    La ventana con que la parrilla se ata a una adquisicion sigue siendo la del
    archivo, porque es con ese reloj que entran sus filas a la base.
    """
    uid = proc.get("session_uid")
    if uid is None:
        return None

    crudo = proc.get("tipo_sesion")
    nombre, familia = LECTURA_DEL_TIPO.get(crudo, (crudo or "sin declarar", "otro"))

    parrilla = _parrilla_legible(proc)
    if parrilla is not None:
        # Nombres propios y no `duracion`: con ese nombre esta linea pisaba la
        # duracion de la sesion con la del archivo, y la ficha de una sesion de
        # siete minutos declaraba los catorce de su captura.
        inicio_captura, duracion_captura = _ventana_de_captura(datos)
        # Con que se la puede atar a una adquisicion. Ninguno de los tres es
        # una ruta local: el nombre del archivo ya viajaba en la procedencia.
        parrilla["captura"] = {
            "archivo": datos.get("archivo"),
            "sha256": datos.get("sha256"),
            "inicio_utc": inicio_captura,
            "duracion_s": duracion_captura,
        }

    return "f1_25:session:%s" % uid, {
        "circuito": proc.get("circuito"),
        "circuito_id": proc.get("circuito_id"),
        "longitud_declarada_m": proc.get("longitud_declarada_m"),
        "tipo_sesion": crudo,
        "tipo_sesion_nombre": nombre,
        "familia_de_sesion": familia,
        "modo_juego": proc.get("modo_juego"),
        "clima": proc.get("clima"),
        "temperatura_pista_c": proc.get("temperatura_pista_c"),
        "temperatura_aire_c": proc.get("temperatura_aire_c"),
        "vueltas_totales": proc.get("vueltas_totales"),
        "dificultad_ia": proc.get("dificultad_ia"),
        # SI REGIA EL PARC FERME. Es la regla que impide tocar la puesta a punto
        # entre la clasificacion y la carrera, y sin ella un reglaje que no
        # cambia no se distingue de uno que **no se podia** cambiar.
        #
        # El capturador ya lo guardaba ---viaja en `ajustes`, medido sobre las
        # veinticuatro capturas: activadas en 23 y desactivadas en 1--- y esta
        # proyeccion lo tiraba. Sin ajuste declarado va `None` y no
        # «desactivadas»: la diferencia entre «no regia» y «no se sabe» es, en
        # este campo, el dato entero.
        "parc_ferme": ((proc.get("ajustes") or {}).get("parc_ferme_rules")
                       or {}).get("nombre"),
        "capturado_utc": datos.get("inicio_utc"),
        "duracion_capturada_s": duracion,
        "archivo": datos.get("archivo"),
        "origen": "metadato de captura, derivado del paquete de sesion",
        # En que parte del archivo esta esta sesion, en segundos de captura. Solo
        # la declaran las que salen de la lista por sesion.
        **({"tramo_de_la_captura_s": list(tramo)} if tramo is not None else {}),
    }, parrilla


def _releer() -> tuple[dict[str, dict], dict[str, list[dict]]]:
    """Recorre el directorio una vez y arma los dos indices a la par.

    LA PROCEDENCIA ELIGE UNA CAPTURA; LA PARRILLA NO PUEDE.
    Para describir la sesion ---circuito, tipo, clima--- alcanza con la captura
    mas larga, porque esos datos no cambian entre dos capturas de la misma
    sesion. La parrilla si puede cambiar: dos capturas con el mismo
    `session_uid` pueden declarar participantes distintos en el mismo indice, y
    ahi «la mas larga» no es una prueba de pertenencia sino una preferencia.

    Por eso se guardan **todas** las candidatas con la ventana de su captura, y
    quien conoce la adquisicion elige. Si no se puede elegir, no se elige: se
    devuelve identidad ausente, que en el tablero es «Vehículo 19».
    """
    procedencias: dict[str, dict] = {}
    candidatas: dict[str, list[dict]] = {}
    if not DIRECTORIO.is_dir():
        return procedencias, candidatas

    for ruta in sorted(DIRECTORIO.glob("*.meta.json")):
        for sesion, proc, parrilla in _leer_uno(ruta):
            previo = procedencias.get(sesion)
            if not (previo and (previo.get("duracion_capturada_s") or 0) >= (
                    proc.get("duracion_capturada_s") or 0)):
                procedencias[sesion] = proc
            if parrilla is not None:
                candidatas.setdefault(sesion, []).append(parrilla)
    return procedencias, candidatas


def _mas_reciente() -> float:
    """Cuando se toco por ultima vez alguno de los metadatos, o cero.

    Es un `stat` por archivo sobre un directorio que tiene unas pocas capturas.
    Comparado con releer y parsear cada JSON ---que es lo que evita--- no se
    mide.
    """
    if not DIRECTORIO.is_dir():
        return 0.0
    try:
        return max((r.stat().st_mtime for r in DIRECTORIO.glob("*.meta.json")),
                   default=0.0)
    except OSError:
        return 0.0


def _indices(refrescar: bool = False) -> tuple[dict[str, dict], dict[str, list[dict]]]:
    global _CACHE
    ahora = time.monotonic()
    # Vale mientras no haya vencido **y** ningun metadato se haya tocado desde
    # que se armo. Lo segundo es lo que deja ver una captura en curso: su
    # procedencia se reescribe cada vez que el flujo se redeclara.
    if (_CACHE and not refrescar and ahora - _CACHE[0] < VIGENCIA_S
            and _mas_reciente() <= _CACHE[3]):
        return _CACHE[1], _CACHE[2]
    tocado = _mas_reciente()
    procedencias, parrillas = _releer()
    _CACHE = (ahora, procedencias, parrillas, tocado)
    return procedencias, parrillas


def indice(refrescar: bool = False) -> dict[str, dict]:
    """Procedencia de cada sesion de simulacion, indexada por `session_id`.

    Si dos capturas comparten `session_uid` ---dos tramos de la misma sesion---
    gana la mas larga, que es la que mejor la describe.

    LA PARRILLA NO VIENE ACA. La lista de sesiones adjunta esta procedencia a
    **cada** una de las cuatrocientas que devuelve, y veinte participantes por
    sesion serian ocho mil objetos para dibujar una lista de nombres de
    circuito. Se pide aparte, por sesion, con `parrilla_de`.
    """
    return _indices(refrescar)[0]


def candidatas_de_parrilla(session_id: str, refrescar: bool = False) -> list[dict]:
    """Todas las parrillas que declaran capturas de esta sesion, con su ventana.

    Mas de una significa que hay que elegir con algo mas que el `session_uid`;
    quien conoce las adquisiciones lo hace con `pertenece_a`.
    """
    return list(_indices(refrescar)[1].get(session_id) or [])


def de(session_id: str) -> dict[str, Any] | None:
    """Procedencia de una sesion, o `None` si no se conoce."""
    return indice().get(session_id)


def mismos_participantes(a: dict, b: dict) -> bool:
    """Si dos parrillas declaran exactamente la misma gente en los mismos indices."""
    return a.get("vehiculos") == b.get("vehiculos")


def parrilla_de(session_id: str) -> dict[str, Any] | None:
    """Parrilla de una sesion cuando no hay nada que elegir, y `None` si lo hay.

    Se busca **por sesion**. Dos capturas distintas tienen dos parrillas
    distintas aunque las dos numeren un `car:19`: el indice es la posicion del
    vehiculo en el paquete de esa sesion y no identifica a nadie fuera de ella.

    Y dentro de una misma sesion puede haber mas de una captura. Si todas
    declaran los mismos participantes, cual sea es indistinto y se devuelve; si
    no, no hay una parrilla «de la sesion» y hace falta saber la adquisicion.
    """
    candidatas = candidatas_de_parrilla(session_id)
    if not candidatas:
        return None
    if all(mismos_participantes(candidatas[0], c) for c in candidatas[1:]):
        return candidatas[0]
    return None


def pertenece_a(candidata: dict, desde_utc, hasta_utc, shas) -> bool:
    """Si esta captura es de la que salio una adquisicion.

    DOS PRUEBAS, Y NINGUNA ES «LA MAS LARGA».

    La huella del archivo, cuando las filas la declaran: es la unica que no
    admite discusion. En las capturas viejas `captura_sha256` viaja en nulo, y
    entonces queda la segunda.

    La ventana: el capturador escribe `inicio_utc` con el reloj de la maquina en
    el mismo momento en que entra la primera fila a la base, de modo que el
    arranque de la adquisicion cae dentro de la ventana de su captura. Medido
    sobre la carrera de Spa: los dos instantes coinciden al microsegundo.
    """
    captura = candidata.get("captura") or {}
    sha = captura.get("sha256")
    declarados = [x for x in (shas or []) if x]
    if declarados:
        return sha is not None and sha in declarados

    inicio, duracion = captura.get("inicio_utc"), captura.get("duracion_s")
    if not inicio or duracion is None or desde_utc is None:
        return False
    try:
        i = datetime.fromisoformat(inicio)
    except ValueError:
        return False
    if i.tzinfo is None:
        i = i.replace(tzinfo=timezone.utc)
    d = desde_utc if desde_utc.tzinfo else desde_utc.replace(tzinfo=timezone.utc)
    # Un segundo de holgura: el primer paquete no entra en el mismo microsegundo
    # en que se abre el archivo.
    return -TOLERANCIA_S <= (d - i).total_seconds() <= duracion + TOLERANCIA_S


def resumen() -> dict[str, Any]:
    """Cuantas sesiones se conocen y de que tipo son."""
    todas = indice()
    por_familia: dict[str, int] = {}
    por_circuito: dict[str, int] = {}
    for p in todas.values():
        por_familia[p["familia_de_sesion"]] = por_familia.get(p["familia_de_sesion"], 0) + 1
        c = p.get("circuito") or "sin declarar"
        por_circuito[c] = por_circuito.get(c, 0) + 1
    return {
        "sesiones_con_procedencia": len(todas),
        "por_familia": por_familia,
        "por_circuito": por_circuito,
        "origen": str(DIRECTORIO),
    }
