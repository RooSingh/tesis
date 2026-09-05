# -*- coding: utf-8 -*-
"""Mide que se ganaria convirtiendo la telemetria en hipertabla comprimida.

La pregunta, y de donde sale
----------------------------
El capitulo de persistencia declara que la extension temporal esta instalada y
que **la tabla de telemetria no se convirtio en hipertabla**: sin particionado
por fragmentos, sin compresion y sin politicas de retencion. Declara tambien que
la conversion sigue siendo posible sin rehacer indices ni consultas, y termina
con una frase que este guion existe para cerrar:

    «Lo que no puede afirmarse, **porque no se midio**, es que el particionado
    no haga falta.»

Hoy la tabla tiene ochenta y cinco millones de filas y setenta y ocho gigabytes
sobre un disco al noventa y tres por ciento. La pregunta dejo de ser teorica.

Que compara, y que **no** compara
---------------------------------
Compara **dos disenos**, no el mismo diseno dos veces:

- una tabla comun de PostgreSQL con un indice adecuado para la consulta tipica;
- una hipertabla comprimida, segmentada por las columnas que se repiten y
  ordenada por tiempo.

Igualar los indices seria un contraste injusto en la otra direccion: una
hipertabla comprimida **no usa los indices igual**, y su rendimiento viene de la
segmentacion. Comparar cada diseno con lo que le corresponde es lo que responde
la pregunta que importa, que es cual conviene.

Por que sobre una copia
-----------------------
La tabla viva pesa setenta y ocho gigabytes y convertirla en caliente es una
operacion larga y dificil de deshacer. **Nada de lo que hace este guion toca la
tabla de produccion**: copia una porcion a dos tablas nuevas, mide, y las borra.

El costo en disco es aproximadamente el doble del tamano de la porcion mientras
corre, porque las dos copias conviven antes de comprimir.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from backend import db  # noqa: E402

ORIGEN = "telemetry_messages"
PLANA = "medicion_compresion_plana"
HIPER = "medicion_compresion_hiper"

#: Columnas por las que segmentar la compresion.
#:
#: Son las que **se repiten a lo largo de muchas filas seguidas**: el nombre de
#: la senal, la sesion, la fuente y el vehiculo. La compresion por columnas
#: guarda un valor por segmento en lugar de uno por fila, de modo que elegir mal
#: estas columnas es lo que separa una compresion buena de una inutil.
SEGMENTAR_POR = "signal_name, session_id, source_type, vehicle_id"

#: Consultas representativas, con su nombre.
#:
#: No son consultas inventadas para la medicion: son la forma de las que el
#: sistema hace ---una ventana de una senal de una sesion, y una agregacion
#: sobre esa ventana---, que es lo que el capitulo de persistencia ya identifico
#: al construir los indices.
CONSULTAS = {
    "ventana de una senal": (
        "select timestamp, value_numeric from {t} "
        "where source_type = %s and signal_name = %s "
        "order by timestamp limit 5000"
    ),
    "agregacion sobre una senal": (
        "select count(*), avg(value_numeric), max(value_numeric) from {t} "
        "where source_type = %s and signal_name = %s"
    ),
    "recuento por fuente": (
        "select source_type, count(*) from {t} group by source_type"
    ),
}


def _tamano(cur, tabla: str) -> int:
    """Tamano real de una tabla, sea comun o hipertabla.

    **`pg_total_relation_size` no sirve para una hipertabla**: mide la tabla
    padre, que esta vacia, porque los datos viven en los fragmentos. La primera
    version de este guion la uso para las dos y devolvio 0,0 MB para la
    hipertabla y una relacion de compresion de 10.950x.

    No fallo, y por eso vale la pena dejarlo escrito: el numero cerraba, era
    absurdo, y solo se detecta mirandolo. Es la misma clase de error que el
    tamano de un paquete que cierra y significa otra cosa.
    """

    cur.execute("select count(*) from timescaledb_information.hypertables "
                "where hypertable_name = %s", (tabla,))
    if cur.fetchone()[0]:
        cur.execute("select total_bytes from hypertable_detailed_size(%s::regclass)",
                    (tabla,))
        filas = [f[0] for f in cur.fetchall() if f[0] is not None]
        return sum(filas)
    cur.execute("select pg_total_relation_size(%s)", (tabla,))
    return cur.fetchone()[0]


def _cronometrar(cur, sql: str, args: tuple, repeticiones: int = 3) -> float:
    """Devuelve el mejor tiempo de varias corridas, en milisegundos.

    Se toma **el mejor y no el promedio**: lo que se quiere comparar es el costo
    del diseno, y el promedio arrastra el ruido de lo que la maquina este
    haciendo. El peor caso se mide de otra manera y no es esta pregunta.
    """

    mejor = None
    for _ in range(repeticiones):
        t0 = time.perf_counter()
        cur.execute(sql, args)
        cur.fetchall()
        t = (time.perf_counter() - t0) * 1000
        mejor = t if mejor is None else min(mejor, t)
    return round(mejor, 2)


def preparar(cur, filas: int, fuente: str) -> tuple[str, str]:
    """Crea las dos copias y devuelve la senal y la fuente mas frecuentes."""

    cur.execute(f"drop table if exists {PLANA}")
    cur.execute(f"drop table if exists {HIPER}")

    print(f"  copiando {filas:,} filas de {fuente}...", flush=True)
    cur.execute(
        f"create table {PLANA} as "
        f"select * from {ORIGEN} where source_type = %s limit %s",
        (fuente, filas))

    # La hipertabla se crea vacia y con la misma forma, se convierte, y recien
    # despues se llena: `create_hypertable` sobre una tabla con datos exige
    # migrarlos, y hacerlo en dos pasos deja la medicion mas limpia.
    cur.execute(f"create table {HIPER} (like {PLANA} including defaults)")
    # El nombre va **convertido a `regclass`**, no como texto: la forma moderna
    # de `create_hypertable` recibe la tabla y no su nombre, y pasarlo como
    # cadena deja el argumento sin tipo y ninguna sobrecarga resuelve. El
    # intervalo del fragmento viaja dentro de `by_range`, no como argumento
    # suelto.
    cur.execute(
        "select create_hypertable(%s::regclass, "
        "by_range('timestamp', interval '1 day'))", (HIPER,))
    cur.execute(f"insert into {HIPER} select * from {PLANA}")

    # La senal mas frecuente de la porcion, para que la consulta de ventana
    # toque datos de verdad en lugar de devolver vacio.
    cur.execute(f"select signal_name from {PLANA} group by signal_name "
                f"order by count(*) desc limit 1")
    senal = cur.fetchone()[0]
    return senal, fuente


def medir(filas: int, fuente: str, conservar: bool) -> dict:
    resultado: dict = {
        "medido_en": datetime.now(timezone.utc).isoformat(),
        "filas": filas, "fuente": fuente,
    }
    with db.obtener_conexion() as conexion:
        conexion.autocommit = True
        cur = conexion.cursor()

        senal, fuente = preparar(cur, filas, fuente)
        resultado["senal"] = senal

        # El indice que le corresponde al diseno plano: el de la consulta tipica.
        print("  indexando la tabla plana...", flush=True)
        cur.execute(f"create index on {PLANA} "
                    f"(source_type, signal_name, timestamp)")
        cur.execute(f"analyze {PLANA}")

        resultado["plana_bytes"] = _tamano(cur, PLANA)
        resultado["hiper_sin_comprimir_bytes"] = _tamano(cur, HIPER)

        print("  comprimiendo...", flush=True)
        cur.execute(
            f"alter table {HIPER} set (timescaledb.compress, "
            f"timescaledb.compress_segmentby = '{SEGMENTAR_POR}', "
            f"timescaledb.compress_orderby = 'timestamp')")
        t0 = time.perf_counter()
        cur.execute(f"select compress_chunk(c) from show_chunks('{HIPER}') c")
        resultado["compresion_s"] = round(time.perf_counter() - t0, 1)
        cur.execute(f"analyze {HIPER}")

        resultado["hiper_comprimida_bytes"] = _tamano(cur, HIPER)

        # Antes de medir nada mas: **comprobar que no se perdio nada**.
        #
        # La compresion por columnas es exacta, pero afirmarlo por documentacion
        # no es como trabaja este proyecto. La comprobacion es la mas fuerte que
        # el motor permite: **la diferencia de conjuntos en las dos direcciones**.
        # Si alguna fila cambio en cualquiera de sus veinte columnas ---un
        # decimal, un texto, un nulo--- aparece en uno de los dos lados.
        #
        # Se hace en las dos direcciones a proposito: una sola detectaria filas
        # perdidas pero no filas agregadas o alteradas.
        print("  verificando que no se perdio nada...", flush=True)
        cur.execute(f"select count(*) from (select * from {PLANA} "
                    f"except select * from {HIPER}) d")
        faltan = cur.fetchone()[0]
        cur.execute(f"select count(*) from (select * from {HIPER} "
                    f"except select * from {PLANA}) d")
        sobran = cur.fetchone()[0]
        cur.execute(f"select count(*) from {PLANA}")
        n_plana = cur.fetchone()[0]
        cur.execute(f"select count(*) from {HIPER}")
        n_hiper = cur.fetchone()[0]
        resultado["verificacion"] = {
            "filas_plana": n_plana,
            "filas_hipertabla": n_hiper,
            "en_plana_y_no_en_hipertabla": faltan,
            "en_hipertabla_y_no_en_plana": sobran,
            "identicas": faltan == 0 and sobran == 0 and n_plana == n_hiper,
        }
        print(f"    {n_plana:,} filas   faltan {faltan}   sobran {sobran}",
              flush=True)

        print("  cronometrando consultas...", flush=True)
        tiempos = {}
        for nombre, plantilla in CONSULTAS.items():
            args = () if "%s" not in plantilla else (fuente, senal)
            tiempos[nombre] = {
                "plana_ms": _cronometrar(cur, plantilla.format(t=PLANA), args),
                "hiper_ms": _cronometrar(cur, plantilla.format(t=HIPER), args),
            }
        resultado["consultas"] = tiempos

        if not conservar:
            cur.execute(f"drop table if exists {PLANA}")
            cur.execute(f"drop table if exists {HIPER}")
            resultado["copias"] = "borradas"
        else:
            resultado["copias"] = "conservadas"

    p = resultado["plana_bytes"]
    c = resultado["hiper_comprimida_bytes"]
    resultado["relacion"] = round(p / c, 2) if c else None
    return resultado


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--filas", type=int, default=2_000_000)
    ap.add_argument("--fuente", default="f1_25_udp_simulation")
    ap.add_argument("--conservar", action="store_true",
                    help="No borra las copias al terminar.")
    ap.add_argument("--salida", type=Path,
                    default=RAIZ / "logs" / "compresion_hipertabla.json")
    args = ap.parse_args()

    print(f"Midiendo sobre {args.filas:,} filas de {args.fuente}", flush=True)
    r = medir(args.filas, args.fuente, args.conservar)
    args.salida.write_text(json.dumps(r, indent=2, ensure_ascii=False),
                           encoding="utf-8")

    mb = 1024 * 1024
    print()
    print(f"  tabla plana con indice   {r['plana_bytes'] / mb:9.1f} MB")
    print(f"  hipertabla sin comprimir {r['hiper_sin_comprimir_bytes'] / mb:9.1f} MB")
    print(f"  hipertabla comprimida    {r['hiper_comprimida_bytes'] / mb:9.1f} MB")
    print(f"  relacion                 {r['relacion']}x")
    print(f"  comprimir tardo          {r['compresion_s']} s")
    print()
    for nombre, t in r["consultas"].items():
        print(f"  {nombre:<30} plana {t['plana_ms']:8.2f} ms   "
              f"hipertabla {t['hiper_ms']:8.2f} ms")
    print()
    print(f"  copias: {r['copias']}   detalle en {args.salida}")


if __name__ == "__main__":
    main()
