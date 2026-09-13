# -*- coding: utf-8 -*-
"""Carga la telemetria de un paquete OpenF1 a la base, sin transporte.

LA MITAD QUE FALTABA
--------------------
Un paquete de la fuente deportiva son dos mitades. El **contexto** ---vueltas,
paradas, clima, adelantamientos--- lo importa `session_processor` y queda en
`racing_sessions`. La **telemetria** de cada piloto es la que hace que una
sesion se pueda abrir y reproducir, y no tenia forma de llegar a
`telemetry_messages`.

Medido el 2026-09-13 sobre la Pi: tres sesiones OpenF1 registradas ---Spa,
Spielberg y Monaco--- y una sola con telemetria, la que alguien habia cargado a
mano con `scripts/replay_openf1.py`. Las otras dos estaban en la base y no se
podian abrir. Ninguna de las nueve rutas que escriben cargaba telemetria de esta
fuente.

POR QUE INSERTA DIRECTO Y NO PUBLICA
------------------------------------
El unico camino que existia publica por el intermediario y espera que el
consumidor persista. Eso es reproducir, no cargar, y el docstring de
`scripts/reproducir_can.py` ya dejo escrito por que no sirve para esto: «una
carga masiva no tiene restriccion de tiempo real, no tiene dato que envejezca, y
no hay razon para que atraviese un canal disenado para descartar cuando el
consumidor no da abasto. **El trabajo ya perdio datos dos veces por hacer eso**».

Asi que esta carga hace lo mismo que la del bus: valida con el mismo modelo que
usa el consumidor e inserta con la misma funcion de lote, sin transporte.

QUE NO HACE
-----------
No descarga nada. Los archivos tienen que estar en el paquete; traerlos es de
`scripts/download_openf1_session_telemetry.py`, que respeta el techo de treinta
consultas por minuto del proveedor. Dos sitios pidiendole a la API serian dos
techos distintos el dia que alguien cambie uno.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

from adapters import openf1
from backend import db
from backend.models import TelemetryMessage

#: El mismo orden de magnitud que usa el consumidor y que usa la carga del bus.
TAMANO_LOTE = 2000

#: Los dos conjuntos temporales que la fuente publica por piloto. El orden es
#: parte de la numeracion: ver `identidad_de_corrida`.
CONJUNTOS = ("car_data", "location")

#: `car_data_driver_1_VER.json` -> (car_data, 1, VER).
_NOMBRE = re.compile(r"^(car_data|location)_driver_(\d+)_(.+)\.json$")


def identidad_de_corrida(session_key: int) -> str:
    """Identifica la corrida por la sesion **y por lo que determina la numeracion**.

    LA LECCION LA PAGO EL BUS DOS VECES. `replay_seq` es un contador sobre los
    mensajes que el adaptador emite, de modo que agregar o quitar una senal corre
    toda la numeracion. Con la identidad derivada solo de la sesion, dos corridas
    con adaptadores distintos comparten espacio de identidades dandole a cada
    numero un significado diferente, y la insercion suprime las coincidencias
    creyendo que son repeticiones.

    La regla que sale de ahi: la identidad tiene que incluir **todo lo que
    determina la numeracion**. Aqui eso son los dos catalogos de senales y el
    orden en que se recorren los conjuntos.
    """

    catalogo = ",".join(sorted(
        [n for n, _ in openf1.CAR_DATA_SIGNALS.values()] +
        [n for n, _ in openf1.LOCATION_SIGNALS.values()]))
    firma = "%s|%s" % ("|".join(CONJUNTOS), catalogo)
    huella = hashlib.sha256(firma.encode("utf-8")).hexdigest()[:8]
    return "openf1:cargado:%s:%s" % (session_key, huella)


def archivos_de_telemetria(paquete: Path) -> list[tuple[str, int, Path]]:
    """Los archivos temporales del paquete, en un orden que no da el disco.

    EL ORDEN ES PARTE DE LA IDENTIDAD. `replay_seq` se asigna recorriendo, de
    modo que dos corridas que recorran distinto numeran distinto y la misma
    medicion entra dos veces con dos numeros. Se ordena por numero de piloto y
    despues por conjunto: los dos salen del nombre del archivo y no de como el
    sistema de archivos los devuelva.
    """

    hallados = []
    for ruta in paquete.iterdir():
        m = _NOMBRE.match(ruta.name)
        if m:
            hallados.append((m.group(1), int(m.group(2)), ruta))
    return sorted(hallados, key=lambda h: (h[1], CONJUNTOS.index(h[0])))


def _muestras(ruta: Path) -> Iterable[dict]:
    contenido = json.loads(ruta.read_text(encoding="utf-8"))
    return contenido if isinstance(contenido, list) else []


def cargar_telemetria(paquete: str | Path, pilotos: list[int] | None = None,
                      al_avanzar=None) -> dict[str, Any]:
    """Inserta la telemetria del paquete por el camino de validacion.

    `pilotos` acota la carga. Una carrera son veinte pilotos y varios millones de
    muestras: poder traer tres es lo que hace que esto se pueda usar sin
    comprometer media hora y varios gigabytes.
    """

    ruta = Path(paquete)
    todos = archivos_de_telemetria(ruta)
    if pilotos:
        elegidos = [a for a in todos if a[1] in set(pilotos)]
    else:
        elegidos = todos

    vacio = {"paquete": str(ruta), "session_key": None, "corrida": None,
             "archivos": 0, "validados": 0, "insertados": 0, "rechazados": 0,
             "motivo": ""}
    # SIN TELEMETRIA NO HAY NADA QUE IDENTIFICAR, y por eso se mira antes de
    # abrir la ficha de sesion: un paquete que no trae telemetria es una
    # respuesta legitima ---los paquetes de solo contexto lo son--- y pedirle su
    # `session.json` para poder decirlo lo convertiria en un error.
    if not todos:
        vacio["motivo"] = (
            "el paquete no trae telemetria: no hay archivos `car_data_*` ni "
            "`location_*`. El contexto se importa igual, pero sin telemetria la "
            "sesion no se puede abrir.")
        return vacio

    session_key = _session_key_de(ruta)
    corrida = identidad_de_corrida(session_key)
    resumen = {"paquete": str(ruta), "session_key": session_key,
               "corrida": corrida, "archivos": len(elegidos),
               # DE QUIENES, Y NO CUANTOS ARCHIVOS. Quien lea esto no tiene por
               # que saber que cada piloto trae dos conjuntos: derivar «tres
               # pilotos» de «seis archivos» seria una convencion escrita de un
               # solo lado, que es como se rompen los acuerdos entre dos.
               "pilotos": sorted({a[1] for a in elegidos}),
               "validados": 0, "insertados": 0, "rechazados": 0, "motivo": ""}

    if not elegidos:
        presentes = sorted({a[1] for a in todos})
        resumen["motivo"] = (
            "ninguno de los pilotos pedidos (%s) tiene telemetria en este "
            "paquete; los que hay son %s."
            % (", ".join(str(p) for p in pilotos), ", ".join(str(p) for p in presentes)))
        return resumen

    lote: list[TelemetryMessage] = []
    seq = 0

    def descargar() -> None:
        if lote:
            resumen["insertados"] += db.insertar_telemetria_lote(lote)
            lote.clear()

    for conjunto, numero, archivo in elegidos:
        for muestra in _muestras(archivo):
            for mensaje in openf1.messages_from_openf1_sample(
                    muestra, conjunto,
                    "https://api.openf1.org/v1/%s?session_key=%s&driver_number=%s"
                    % (conjunto, session_key, numero),
                    str(archivo)):
                mensaje["metadata"]["extra"]["replay_run_id"] = corrida
                mensaje["metadata"]["extra"]["replay_seq"] = seq
                seq += 1
                try:
                    lote.append(TelemetryMessage.model_validate(mensaje))
                    resumen["validados"] += 1
                except Exception:  # noqa: BLE001 - una muestra rota no corta la carga
                    resumen["rechazados"] += 1
                    continue
                if len(lote) >= TAMANO_LOTE:
                    descargar()
        if al_avanzar:
            al_avanzar(archivo.name, resumen["insertados"])
    descargar()
    return resumen


def _session_key_de(paquete: Path) -> int:
    ficha = paquete / "session.json"
    return int(json.loads(ficha.read_text(encoding="utf-8"))["session_key"])


def conciliar(esperado: int, corrida: str) -> dict[str, int]:
    """Compara lo que la base tiene contra lo que **esta corrida** debe dejar.

    LA PREGUNTA NO ES CUANTO CRECIO LA BASE. Esa formulacion se arreglo el
    2026-09-13 en la carga del bus, despues de que una recarga idempotente se
    informara como perdida de 57.890 filas: el indice unico suprime las
    repeticiones ---que es lo correcto--- y contar el crecimiento lo llama fallo.

    Se cuenta por `replay_run_id`, de modo que la respuesta no depende de cuantas
    veces se cargo lo mismo. Y lo que sobra se declara aparte: mas filas de las
    que esta corrida debe dejar no es «faltan menos de cero», es que la misma
    medicion entro con dos numeraciones distintas.
    """

    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        cursor.execute(
            "select count(*) from telemetry_messages where replay_run_id = %s",
            (corrida,))
        presente = cursor.fetchone()[0]
    return {"esperado": esperado, "presente": presente,
            "faltan": max(0, esperado - presente),
            "sobran": max(0, presente - esperado)}
