# -*- coding: utf-8 -*-
"""Comprueba que las funciones del tablero sigan existiendo.

POR QUE EXISTE
--------------
`node --check` verifica sintaxis y nada mas: en JavaScript, llamar a una funcion
que no existe **no es un error de sintaxis**, falla recien al ejecutarse. Eso dejo
pasar dos veces el mismo defecto en una sola jornada. Un reemplazo por anclas
---sustituir todo lo que hay entre dos puntos del archivo--- se llevo por delante
cuatro funciones enteras del panel de anotaciones; el archivo siguio siendo valido
para el analizador, y el panel quedo roto sin que nada lo declarara.

POR QUE UNA LISTA Y NO UN ANALISIS
----------------------------------
Un analisis general de que nombres se usan sin declarar es la solucion elegante y
requiere entender el lenguaje: parametros, desestructuracion, cierres y metodos.
Un intento aproximado dio veintidos falsos positivos, y **una comprobacion con
veintidos falsos positivos no se mira**, con lo cual deja de proteger.

La lista explicita no tiene ese problema. Cuesta una linea cuando se agrega una
funcion, y a cambio detecta con certeza el unico defecto que ocurrio de verdad:
que una funcion desaparezca.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
TABLERO = RAIZ / "dashboard" / "app.js"

#: Las funciones sin las cuales la vista en vivo deja de funcionar.
#:
#: Estan agrupadas por lo que sostienen, de modo que un fallo diga que parte de
#: la pantalla se rompio y no solo que falta un nombre.
REQUERIDAS = {
    "las trazas": [
        "dibujarTrazas", "dibujarUnaTraza", "entradasDelCatalogo",
        # La vista de sesion completa, que reemplaza el eje que se desplaza.
        "traerResumenDeSesion", "duracionDeLaSesion", "dibujarEjeDeTiempo",
        "dibujarMarcasDeAnotacion",
        "dibujarCatalogo", "rangoDe", "conversionDe", "instanteDe",
    ],
    "las anotaciones": [
        "registrarAnotacion", "dibujarAnotaciones", "sembrarAnotaciones",
        "textoDeUbicacion",
    ],
    "los conductores": [
        "registrarConductor", "dibujarSelectorDeConductor", "vehiculosADibujar",
        "serieDe", "tiemposDe",
    ],
    "el flujo en vivo": [
        "conectarFlujoEnVivo", "desconectarFlujoEnVivo", "sembrarHistoria",
        "registrarMensajeEnVivo", "declararEstadoEnVivo",
    ],
}


def main() -> None:
    texto = TABLERO.read_text(encoding="utf-8")
    # Se ignoran los comentarios: un nombre citado en una explicacion no es una
    # definicion, y contarlo daria por buena una funcion que ya no existe.
    codigo = re.sub(r"//[^\n]*", "", texto)
    codigo = re.sub(r"/\*.*?\*/", "", codigo, flags=re.S)

    faltan: list[tuple[str, str]] = []
    for parte, funciones in REQUERIDAS.items():
        for nombre in funciones:
            declarada = re.search(
                rf"(?:async\s+)?function\s+{re.escape(nombre)}\s*\(", codigo
            ) or re.search(
                rf"(?:const|let|var)\s+{re.escape(nombre)}\s*=", codigo)
            if not declarada:
                faltan.append((parte, nombre))

    total = sum(len(v) for v in REQUERIDAS.values())
    print(f"{total - len(faltan)} de {total} funciones presentes")

    if faltan:
        print(f"\n{len(faltan)} funciones que se llaman y ya no existen:\n")
        for parte, nombre in faltan:
            print(f"  ! {nombre}()  ---  rompe {parte}")
        print("\nEn JavaScript esto no es un error de sintaxis: "
              "el archivo compila y falla al usarse.")
        sys.exit(1)

    print("\nTodas presentes.")


if __name__ == "__main__":
    main()
