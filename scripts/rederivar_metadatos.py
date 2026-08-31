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
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import f1_capture, f1_udp
from scripts.capturar_f1_25 import (
    _perfil_declarado, derivar_procedencia, nombre_derivado,
)

CAPTURAS = ROOT / "datasets" / "f1_25" / "capturas"


def releer(ruta: Path) -> dict:
    """Recorre el crudo y devuelve la procedencia segun el decodificador actual."""

    sesion = estado = cabecera = None
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
        elif d["paquete"] == "car_status":
            estado = d["vehiculo_propio"]

    return {
        "procedencia": derivar_procedencia(sesion, estado, cabecera),
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
        return {"archivo": ruta.name, "estado": "sin metadatos previos"}

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

    meta_ruta.write_text(json.dumps(nuevo, indent=2, ensure_ascii=False),
                         encoding="utf-8")
    return resultado


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capturas", nargs="*", type=Path,
                        help="Archivos .f1raw. Por defecto, todos los del repositorio.")
    parser.add_argument("--renombrar", action="store_true",
                        help="Renombra el par si el nombre derivado cambio.")
    args = parser.parse_args()

    rutas = args.capturas or sorted(CAPTURAS.glob("*.f1raw"))
    if not rutas:
        raise SystemExit("No hay capturas para releer.")

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
