"""Descarga el paquete de contexto de **una** sesion de OpenF1, reanudable.

POR QUE HACIA FALTA ESTE Y NO ALCANZABAN LOS QUE HABIA.

Habia dos caminos para traer contexto y ninguno servia para «esta sesion, esta
vez». `day18_openf1_event_matrix.py` recorre **el año entero** para elegir un
evento finalista, y lo hace con medio segundo entre consultas, que sostenido
son ciento veinte por minuto contra un techo de treinta: golpear asi una API
publica y gratuita para traer una sola sesion no se justifica.
`day18_openf1_silverstone_stage1.py` si baja una sola, pero con la sesion
escrita en el codigo, y ademas no escribe `session.json` ni `drivers.json`, que
son lo primero que el importador pide.

QUE BAJA. Exactamente los archivos que `backend/session_processor.py` sabe
leer: el obligatorio `session.json` y los once opcionales de contexto. La lista
no se escribe aca: se **lee** de `OPTIONAL_CONTEXT_FILES`, de modo que el dia
que el importador acepte uno mas, este guion lo trae sin que nadie se acuerde
de tocarlo.

QUE NO BAJA. `car_data` ni `location`: la telemetria por piloto tiene su propio
guion ---`download_openf1_session_telemetry.py`--- que ya sabe recorrer la
grilla y respeta el mismo techo. Repetir ese recorrido aca seria tener dos
sitios donde se decide cuanta telemetria se pide.

EL TECHO POR MINUTO SE RESPETA REUSANDO EL LIMITADOR QUE YA EXISTE. No se
copia: se importa `fetch_openf1`, que lleva la ventana deslizante de treinta
consultas por minuto y los reintentos. Dos limitadores en el mismo proyecto
serian dos techos distintos el dia que alguien cambie uno.

REANUDABLE. Un archivo ya bajado no se vuelve a pedir. Una descarga larga que
se corta no obliga a empezar de nuevo, y correrlo dos veces no cuesta consultas.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from backend.session_processor import OPTIONAL_CONTEXT_FILES  # noqa: E402
from scripts.download_openf1_session_telemetry import fetch_openf1  # noqa: E402

#: Donde el punto de acceso `/openf1/importar` busca los paquetes. Se escribe
#: donde el resto del sistema ya mira, no en un sitio nuevo.
PAQUETES = RAIZ / "datasets" / "OpenF1" / "raw"

#: Los once archivos de contexto se llaman igual que el endpoint que los llena,
#: de modo que no hace falta una tabla de traduccion: escribirla seria un sitio
#: mas que actualizar y once oportunidades de que diga otra cosa.
def _endpoint_de(archivo: str) -> str:
    return archivo.removesuffix(".json")


def _escribir(destino: Path, contenido: Any) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(contenido, indent=2, ensure_ascii=True),
                       encoding="utf-8")


#: Lo que hace que un objeto **sea** una sesion y no una ficha con un numero
#: adentro. SE MIDIO, NO SE INVENTO: los dos paquetes sanos que hay en disco
#: ---9947 y 9955--- traen los mismos quince campos no nulos, y estos tres son
#: los que no pueden faltar sin que deje de describir una sesion. Se exigen
#: tres de los quince a proposito: pedir los quince seria atarse a que OpenF1
#: no agregue ni saque ninguno nunca.
CAMPOS_DE_UNA_SESION = ("session_type", "date_start", "circuit_key")


def _leer_si_se_puede(ruta: Path) -> tuple[bool, Any]:
    """Devuelve `(se pudo leer, contenido)`. Un archivo ilegible no es un dato."""

    try:
        return True, json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, None


def _bajados_la_vez_anterior(destino: Path) -> set[str]:
    """Los archivos que **este** guion declara haber bajado, segun el manifiesto.

    Es el unico registro de procedencia que hay, y sirve para distinguir dos
    vacios que en disco son identicos: una sesion que de verdad no tuvo
    adelantamientos, y un archivo que dejo ahi otra cosa. Sin esta distincion,
    la unica alternativa seria volver a pedir todo vacio en cada corrida, y eso
    son consultas contra una API publica y gratuita que no se justifican.
    """

    manifiesto = destino / "manifiesto_contexto.json"
    if not manifiesto.is_file():
        return set()
    se_pudo, contenido = _leer_si_se_puede(manifiesto)
    if not se_pudo or not isinstance(contenido, dict):
        return set()
    return {r.get("archivo") for r in contenido.get("archivos", [])
            if isinstance(r, dict) and r.get("estado") == "descargado"}


def _la_ficha_sirve(ruta: Path) -> bool:
    """Un `session.json` que describe una sesion, y no solo que existe una."""

    se_pudo, contenido = _leer_si_se_puede(ruta)
    if not se_pudo or not isinstance(contenido, dict):
        return False
    return all(contenido.get(campo) is not None for campo in CAMPOS_DE_UNA_SESION)


def _el_contexto_sirve(ruta: Path, con_procedencia: set[str]) -> bool:
    """Una lista. Y si esta vacia, que alguien declare haberla bajado asi.

    EL VACIO NO SE DECLARA INVALIDO, y es a proposito. Una sesion de
    entrenamientos puede no tener adelantamientos y una corta puede no tener
    paradas: rechazar todo `[]` obligaria a volver a pedir para siempre algo
    que de verdad esta vacio. Lo que se rechaza es el vacio **sin procedencia**,
    que es el que aparecio en el 9939 diciendo que no corrio nadie.
    """

    se_pudo, contenido = _leer_si_se_puede(ruta)
    if not se_pudo or not isinstance(contenido, list):
        return False
    return bool(contenido) or ruta.name in con_procedencia


def descargar_paquete(session_key: int, destino: Path) -> dict[str, Any]:
    """Deja en `destino` el paquete de contexto de la sesion. Idempotente.

    REANUDABLE POR CONTENIDO, NO POR NOMBRE. Un archivo que ya esta no se
    vuelve a pedir **si sirve**. La version anterior preguntaba solo
    `if salida.is_file()`, y el 2026-09-13 eso dejo pasar los restos de una
    prueba que habian sobrescrito el paquete de la sesion 9939: un
    `session.json` con dos campos y un `drivers.json` con `[]`. El guion
    informo «ya estaba» para los dos. Si la API no hubiera estado cerrada esa
    tarde, habria bajado el resto, informado exito, y dejado la sesion
    afirmando para siempre que no corrio nadie.
    """

    ultimo = [0.0]
    registros: list[dict[str, Any]] = []
    con_procedencia = _bajados_la_vez_anterior(destino)

    # `session.json` es el unico obligatorio, y el importador lo exige como
    # **objeto**: OpenF1 contesta una lista de una sesion y hay que abrirla.
    ficha = destino / "session.json"
    if ficha.is_file() and _la_ficha_sirve(ficha):
        registros.append({"archivo": "session.json", "estado": "ya estaba", "filas": 1})
    else:
        payload, registro = fetch_openf1("sessions", {"session_key": session_key}, ultimo)
        if not payload:
            raise SystemExit(
                f"OpenF1 no reconoce la sesion {session_key}: {registro.get('error')}")
        _escribir(ficha, payload[0])
        registros.append({"archivo": "session.json", "estado": "descargado", "filas": 1})

    for archivo in sorted(OPTIONAL_CONTEXT_FILES):
        salida = destino / archivo
        if salida.is_file() and _el_contexto_sirve(salida, con_procedencia):
            registros.append({"archivo": archivo, "estado": "ya estaba", "filas": None})
            continue
        payload, registro = fetch_openf1(_endpoint_de(archivo),
                                         {"session_key": session_key}, ultimo)
        if payload is None:
            # Que un contexto no este no invalida el paquete: el importador
            # declara lo que falta en vez de rechazarlo. Se anota y se sigue.
            registros.append({"archivo": archivo, "estado": "sin respuesta",
                              "filas": 0, "error": registro.get("error")})
            continue
        _escribir(salida, payload)
        registros.append({"archivo": archivo, "estado": "descargado",
                          "filas": len(payload)})

    manifiesto = {
        "corrida_utc": datetime.now(timezone.utc).isoformat(),
        "session_key": session_key,
        "alcance": "contexto de la sesion; car_data y location los trae "
                   "download_openf1_session_telemetry.py",
        "archivos": registros,
    }
    _escribir(destino / "manifiesto_contexto.json", manifiesto)
    return manifiesto


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-key", type=int, required=True,
                        help="Identificador de la sesion en OpenF1.")
    parser.add_argument("--anio", type=int, default=2025,
                        help="Carpeta del año bajo la que se guarda el paquete.")
    argumentos = parser.parse_args()

    destino = PAQUETES / str(argumentos.anio) / str(argumentos.session_key)
    manifiesto = descargar_paquete(argumentos.session_key, destino)

    print(f"paquete en {destino}")
    for registro in manifiesto["archivos"]:
        filas = registro.get("filas")
        print(f"  {registro['archivo']:<22} {registro['estado']:<14}"
              f" {'' if filas is None else str(filas) + ' filas'}"
              f" {registro.get('error') or ''}")


if __name__ == "__main__":
    main()
