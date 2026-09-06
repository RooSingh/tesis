# -*- coding: utf-8 -*-
"""Arma el manifiesto de lo irremplazable, y de paso lo verifica.

Que es lo irremplazable
-----------------------
La base de datos **es una derivacion**: se reconstruye reproduciendo las
capturas. Las capturas no se reconstruyen desde nada ---exigirian volver a
conducir la sesion, y en el caso de la fuente deportiva volver a pedirle a una
API externa datos que pueden no estar mas---.

Es el principio que el capturador ya declara: *perder la publicacion es
recuperable reproduciendo la captura; perder la captura no lo es.* Este guion lo
lleva a su consecuencia: **lo que se respalda son las capturas**, no la base.

En numeros de este trabajo, la diferencia es de nueve a uno: ochenta gigabytes de
tabla contra nueve de captura.

Que hace ademas de listar
-------------------------
**Contrasta cada huella contra la que su archivo de metadatos ya declaraba.** Esa
huella se calculo cuando la captura se cerro, de modo que compararla ahora
responde una pregunta que ningun listado responde: **si el archivo sigue siendo el
que era**.

Un manifiesto que solo dice que los archivos existen no sirve para lo que un
respaldo necesita, que es poder afirmar despues que lo guardado es lo que habia.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DATASETS = RAIZ / "datasets"

#: Extensiones que no se respaldan: material derivado o de terceros que se
#: vuelve a obtener sin costo.
IGNORADAS = {".pyc"}


def _huella(ruta: Path, bloque: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        while True:
            trozo = f.read(bloque)
            if not trozo:
                break
            h.update(trozo)
    return h.hexdigest()


def _huella_declarada(ruta: Path) -> str | None:
    """La huella que el archivo de metadatos declaro al cerrar la captura."""

    meta = ruta.with_suffix(ruta.suffix + ".meta.json")
    if not meta.exists():
        return None
    try:
        return json.loads(meta.read_text(encoding="utf-8")).get("sha256")
    except (OSError, ValueError):
        return None


def recorrer(raiz: Path) -> list[dict]:
    entradas = []
    for ruta in sorted(raiz.rglob("*")):
        if not ruta.is_file() or ruta.suffix in IGNORADAS:
            continue
        rel = ruta.relative_to(RAIZ).as_posix()
        print(f"  {rel}", flush=True)
        huella = _huella(ruta)
        declarada = _huella_declarada(ruta)
        entradas.append({
            "archivo": rel,
            "bytes": ruta.stat().st_size,
            "sha256": huella,
            # Tres estados y no dos: que coincida, que no coincida, y que no
            # haya con que comparar. El tercero no es un fallo.
            "contra_metadatos": (
                None if declarada is None
                else ("coincide" if declarada == huella else "NO COINCIDE")),
        })
    return entradas


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raiz", type=Path, default=DATASETS)
    ap.add_argument("--salida", type=Path,
                    default=RAIZ / "MANIFIESTO_RESPALDO.md")
    ap.add_argument("--json", type=Path,
                    default=RAIZ / "logs" / "manifiesto_respaldo.json")
    args = ap.parse_args()

    entradas = recorrer(args.raiz)
    total = sum(e["bytes"] for e in entradas)
    verificados = [e for e in entradas if e["contra_metadatos"] is not None]
    malos = [e for e in entradas if e["contra_metadatos"] == "NO COINCIDE"]

    resumen = {
        "generado": datetime.now(timezone.utc).isoformat(),
        "raiz": args.raiz.relative_to(RAIZ).as_posix(),
        "archivos": len(entradas),
        "bytes": total,
        "con_huella_declarada": len(verificados),
        "no_coinciden": len(malos),
        "entradas": entradas,
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(resumen, indent=2, ensure_ascii=False),
                         encoding="utf-8")

    gb = 1024 ** 3
    lineas = [
        "# Manifiesto de respaldo",
        "",
        "Lo que este archivo lista es **lo irremplazable**: las capturas crudas.",
        "La base de datos no esta aca **a proposito**, porque se reconstruye",
        "reproduciendolas. Las capturas no se reconstruyen desde nada.",
        "",
        f"- generado: `{resumen['generado']}`",
        f"- archivos: **{len(entradas)}**",
        f"- tamano: **{total / gb:.2f} GB**",
        f"- con huella declarada al capturar: **{len(verificados)}**",
        f"- huellas que no coinciden: **{len(malos)}**",
        "",
        "## Como verificar despues de subirlo",
        "",
        "Volver a correr `python scripts/manifiesto_capturas.py` y comparar el",
        "`sha256` de cada archivo contra el de esta tabla. Si alguno cambio, el",
        "archivo se corrompio y **el respaldo es el que vale**.",
        "",
        "## Archivos",
        "",
        "| archivo | tamano | sha256 | contra metadatos |",
        "| --- | ---: | --- | --- |",
    ]
    for e in entradas:
        mb = e["bytes"] / (1024 * 1024)
        estado = e["contra_metadatos"] or "sin metadatos"
        lineas.append(f"| `{e['archivo']}` | {mb:,.1f} MB | "
                      f"`{e['sha256'][:16]}...` | {estado} |")
    args.salida.write_text("\n".join(lineas) + "\n", encoding="utf-8")

    print()
    print(f"  archivos: {len(entradas)}   {total / gb:.2f} GB")
    print(f"  con huella declarada: {len(verificados)}")
    if malos:
        print(f"  NO COINCIDEN: {len(malos)}")
        for e in malos:
            print(f"     {e['archivo']}")
    else:
        print("  todas las huellas declaradas coinciden")
    print(f"  manifiesto en {args.salida}")


if __name__ == "__main__":
    main()
