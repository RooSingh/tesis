"""Vuelve a derivar los metadatos de capturas ya grabadas.

Para que sirve
--------------
Los metadatos de una captura no son un dato: son una **lectura** del flujo, y
por lo tanto pueden estar mal aunque el flujo este bien. Cuando se corrige el
decodificador o la tabla con la que se nombra un campo, las capturas viejas
quedan descritas con la lectura vieja.

Que el registro crudo se conserve byte a byte es lo que permite arreglarlo sin
volver a correr nada: **se vuelve a leer el mismo archivo con el decodificador
corregido**. Una captura no se pierde por un error de interpretacion.

Que corrige en concreto
-----------------------
Ademas de aplicar el decodificador actual, cambia **de que paquete se leen** los
metadatos. La version anterior tomaba el primer paquete de sesion, que el juego
emite antes de tener cargada la configuracion y que declara todo en cero. De ahi
venia que una carrera con dano en simulacion se archivara como sin dano.

Se conserva el ultimo paquete que declara un tipo de sesion conocido, y se
informa a partir de que segundo el flujo se describio de forma estable.

Que no toca
-----------
El `.f1raw` no se modifica nunca. Se reescribe el archivo de metadatos y, si el
nombre derivado cambio, se renombra el par —dejando constancia del nombre
anterior dentro de los metadatos, para que la correccion sea rastreable.
"""

from __future__ import annotations

import argparse
import json
import shutil
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import f1_capture, f1_udp
from scripts.capturar_f1_25 import (
    AyudasEnMarcha, SesionesDeLaCaptura, _perfil_declarado, derivar_procedencia,
    nombre_derivado,
)

CAPTURAS = ROOT / "datasets" / "f1_25" / "capturas"

#: Los numeros de paquete que la procedencia por sesion lee. Se filtra por la
#: cabecera antes de decodificar: recorrer 4,75 GB de capturas decodificando
#: movimiento y danos que la procedencia no usa seria pagar por nada.
_PAQUETES_DE_PROCEDENCIA = frozenset(
    i for i, p in f1_udp.PAQUETES.items()
    if p["nombre"] in SesionesDeLaCaptura.PAQUETES)

#: Hasta el identificador de sesion: formato, tres versiones, version de
#: paquete, numero de paquete y `session_uid`.
_CABECERA = struct.Struct("<HBBBBBQ")


def releer_sesiones(ruta: Path) -> list[dict]:
    """Cada sesion que atraviesa la captura, con su propia procedencia.

    Cuenta **todos** los datagramas para el tramo de cada sesion, leyendo solo
    la cabecera, y decodifica unicamente los paquetes que la procedencia usa.
    """
    sesiones = SesionesDeLaCaptura()
    for datagrama in f1_capture.leer_captura(ruta):
        carga = datagrama.carga
        if len(carga) < _CABECERA.size:
            continue
        cabecera = _CABECERA.unpack_from(carga)
        decodificado = None
        if cabecera[5] in _PAQUETES_DE_PROCEDENCIA:
            try:
                decodificado = f1_udp.decodificar(carga)
            except f1_udp.ErrorDecodificacion:
                decodificado = None
        sesiones.anotar(cabecera[6], datagrama.desplazamiento_us, decodificado)
    return sesiones.resumen()


def releer(ruta: Path) -> dict:
    """Recorre el crudo y devuelve la procedencia segun el decodificador actual."""

    sesion = cabecera = participantes = None
    # El mismo acumulador que usa el capturador en vivo. La regla estaba escrita
    # dos veces y las dos tomaban la ultima lectura: arreglar una sola habria
    # dejado que el crudo y su rederivacion declararan cosas distintas.
    ayudas_vistas = AyudasEnMarcha()
    sesion_inicial = None
    sesiones = 0
    perfil = None
    estable_us: int | None = None
    ultimo_us = 0

    for datagrama in f1_capture.leer_captura(ruta):
        ultimo_us = datagrama.desplazamiento_us
        try:
            d = f1_udp.decodificar(datagrama.carga)
        except f1_udp.ErrorDecodificacion:
            continue
        if cabecera is None:
            cabecera = d["cabecera"]
        if d["paquete"] == "session":
            sesiones += 1
            if sesion_inicial is None:
                sesion_inicial = d["sesion"]
            if d["sesion"]["session_type"] != 0:
                sesion = d["sesion"]
                actual = _perfil_declarado(sesion)
                if actual != perfil:
                    perfil = actual
                    estable_us = datagrama.desplazamiento_us
        elif d["paquete"] == "participants":
            participantes = d
        ayudas_vistas.ver(d)

    return {
        "procedencia": derivar_procedencia(
            sesion, ayudas_vistas.estado(), cabecera, participantes),
        "paquetes_sesion": sesiones,
        "metadatos_desde": "ultimo paquete de sesion con tipo declarado",
        "metadatos_estables_desde_s": (round(estable_us / 1e6, 3)
                                       if estable_us is not None else None),
        "primer_paquete_sesion_vacio": (
            sesion_inicial is not None and sesion_inicial["session_type"] == 0),
        "duracion_recorrida_s": round(ultimo_us / 1e6, 3),
    }


def procesar(ruta: Path, renombrar: bool) -> dict:
    meta_ruta = ruta.with_suffix(ruta.suffix + ".meta.json")
    if not meta_ruta.exists():
        # Una captura sin metadatos no es un caso raro: es lo que queda cuando el
        # capturador se interrumpe antes de cerrar el archivo. Tres capturas del
        # 02/09 quedaron asi, y una de ellas resulto ser el unico registro de una
        # sesion de pantalla dividida con dos conductores reales.
        #
        # Negarse a procesarla obligaba a escribir un guion suelto para cada
        # rescate. La procedencia se deriva del crudo igual que en cualquier otro
        # archivo, de modo que **generarla es el mismo trabajo que releerla**, y
        # queda declarado que se genero aqui y no en la captura.
        previo = {
            "metadatos_generados_en_rescate": True,
            "nota_rescate": ("la captura no tenia metadatos: quedo interrumpida "
                             "antes de cerrarse y se la recupero despues"),
        }
    else:
        previo = json.loads(meta_ruta.read_text(encoding="utf-8"))
    nuevo = dict(previo)
    nuevo.update(releer(ruta))
    nuevo["version_decodificador"] = f1_udp.VERSION_DECODIFICADOR

    antes = previo.get("procedencia", {})
    ahora = nuevo["procedencia"]
    cambios = {c: [antes.get(c), ahora.get(c)]
               for c in ("tipo_sesion", "modo_juego", "dificultad_ia", "circuito")
               if antes.get(c) != ahora.get(c)}
    if antes.get("dano_activado") is not None:
        cambios["dano"] = [antes["dano_activado"],
                           ahora.get("ajustes", {}).get("car_damage_setting", {}).get("nombre")]

    resultado = {"archivo": ruta.name, "cambios": cambios, "renombrado": None}

    if renombrar and ahora.get("disponible"):
        # La marca temporal se toma del nombre previo para no inventar una nueva.
        marca = ruta.stem.split("_")[0] + "_" + ruta.stem.split("_")[1]
        try:
            momento = datetime.strptime(marca, "%Y%m%d_%H%M")
        except ValueError:
            momento = None
        if momento is not None:
            destino = ruta.with_name(f"{nombre_derivado(ahora, momento)}.f1raw")
            if destino != ruta and not destino.exists():
                nuevo["nombre_anterior"] = ruta.name
                nuevo["motivo_renombrado"] = (
                    "metadatos releidos con el decodificador corregido")
                nuevo["archivo"] = destino.name
                meta_ruta.unlink()
                ruta.rename(destino)
                meta_ruta = destino.with_suffix(destino.suffix + ".meta.json")
                resultado["renombrado"] = destino.name

    if nuevo.get("metadatos_generados_en_rescate"):
        # En un rescate no hay metadatos previos de los que heredar los hechos
        # del archivo ---huella, tamano, recuento de datagramas---, y sin la
        # huella la captura **no es verificable por un tercero**, que es
        # justamente lo que los metadatos existen para permitir. Se los calcula
        # desde el crudo con la misma funcion que usa el capturador, de modo que
        # una captura rescatada queda indistinguible de una bien cerrada salvo
        # por la nota que declara que lo fue.
        f1_capture.escribir_metadatos(ruta, nuevo)
        return resultado

    meta_ruta.write_text(json.dumps(nuevo, indent=2, ensure_ascii=False),
                         encoding="utf-8")
    return resultado


def agregar_sesiones(ruta: Path, respaldo: Path) -> dict:
    """Agrega a los metadatos la procedencia de cada sesion, **y nada mas**.

    POR QUE UN MODO APARTE. `procesar` vuelve a derivar la procedencia principal
    con el decodificador de hoy y puede renombrar el par. Para nombrar las
    sesiones que faltaban no hace falta ninguna de las dos cosas, y hacerlas de
    paso cambiaria metadatos que nadie pidio revisar. Este modo lee el crudo,
    escribe `sesiones_en_la_captura` y deja intacto el resto del archivo.

    Antes de escribir copia el metadato a `respaldo`. Los metadatos no estan en
    el control de versiones, y reescribirlos sin copia seria un camino de ida. Si
    la copia ya existe no se pisa: la que vale es la anterior a la primera
    pasada.
    """
    meta_ruta = ruta.with_suffix(ruta.suffix + ".meta.json")
    if not meta_ruta.exists():
        return {"archivo": ruta.name, "estado": "sin metadatos: no se toca"}
    datos = json.loads(meta_ruta.read_text(encoding="utf-8"))

    respaldo.mkdir(parents=True, exist_ok=True)
    copia = respaldo / meta_ruta.name
    if not copia.exists():
        shutil.copy2(meta_ruta, copia)

    sesiones = releer_sesiones(ruta)
    datos["sesiones_en_la_captura"] = sesiones
    datos["sesiones_derivadas"] = {
        "utc": datetime.now(timezone.utc).isoformat(),
        "version_decodificador": f1_udp.VERSION_DECODIFICADOR,
        "como": ("el tramo, de la cabecera de cada datagrama; la procedencia, de "
                 "los paquetes de sesion, participantes, eventos, telemetria y "
                 "estado de esa sesion"),
    }
    meta_ruta.write_text(json.dumps(datos, indent=2, ensure_ascii=False),
                         encoding="utf-8")
    nombradas = sum(1 for s in sesiones if s["procedencia"].get("disponible"))
    return {"archivo": ruta.name, "sesiones": len(sesiones),
            "con_procedencia": nombradas}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capturas", nargs="*", type=Path,
                        help="Archivos .f1raw. Por defecto, todos los del repositorio.")
    parser.add_argument("--renombrar", action="store_true",
                        help="Renombra el par si el nombre derivado cambio.")
    parser.add_argument("--solo-sesiones", action="store_true",
                        help="Solo agrega la procedencia de cada sesion de la "
                             "captura. No toca la procedencia principal ni renombra.")
    parser.add_argument("--respaldo", type=Path,
                        default=(ROOT / "datasets" / "f1_25" / "respaldos" /
                                 ("metadatos_" + datetime.now().strftime("%Y%m%d_%H%M"))),
                        help="Donde copiar cada metadato antes de reescribirlo.")
    args = parser.parse_args()

    rutas = args.capturas or sorted(CAPTURAS.glob("*.f1raw"))
    if not rutas:
        raise SystemExit("No hay capturas para releer.")

    if args.solo_sesiones:
        for ruta in rutas:
            r = agregar_sesiones(ruta, args.respaldo)
            if r.get("estado"):
                print(f"{r['archivo']}: {r['estado']}", flush=True)
            else:
                print(f"{r['archivo']}: {r['sesiones']} sesiones, "
                      f"{r['con_procedencia']} con procedencia", flush=True)
        print(f"\nrespaldo de los metadatos: {args.respaldo}")
        return

    for ruta in rutas:
        r = procesar(ruta, args.renombrar)
        print(f"\n{r['archivo']}")
        if r.get("estado"):
            print(f"  {r['estado']}")
            continue
        if not r["cambios"]:
            print("  sin cambios de interpretacion")
        for campo, (antes, ahora) in r["cambios"].items():
            print(f"  {campo:<16} {str(antes):<20} -> {ahora}")
        if r["renombrado"]:
            print(f"  renombrado -> {r['renombrado']}")


if __name__ == "__main__":
    main()
