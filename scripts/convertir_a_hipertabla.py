# -*- coding: utf-8 -*-
"""Convierte la telemetria a hipertabla comprimida, por lotes y sin riesgo.

Por que no se usa la conversion directa
---------------------------------------
`create_hypertable(..., migrate_data => true)` mueve las filas a los fragmentos
con la tabla original todavia en pie: **hacen falta unos ochenta gigabytes libres**
y hay cuarenta y uno.

La conversion por lotes no los necesita. Se copia **un dia por vez** a una tabla
nueva y **se comprime cada dia al terminarlo**, de modo que la tabla nueva nunca
pasa de unos pocos gigabytes. La original queda intacta durante todo el proceso.

El orden de los pasos, y por que ese
------------------------------------
1. **crear y llenar**, sin tocar nada de lo que ya funciona;
2. **verificar**, contra el total esperado y no contra la ausencia de errores;
3. **intercambiar nombres**, que es reversible en un segundo;
4. **borrar la original**, que no lo es, y va aparte.

Este guion **no ejecuta el paso 4**. Deja la tabla original con otro nombre y la
informa. Borrarla es una decision que se toma mirando el sistema andar, no al
final de un guion.

La regla de conciliacion
------------------------
Una operacion masiva se concilia **contra lo que debia quedar**, no contra el
error que se evitaba. Aca eso significa comparar fila por fila y dia por dia, y
no conformarse con que ningun paso haya fallado.
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

import shutil  # noqa: E402

from backend import db  # noqa: E402

#: Piso de disco libre por debajo del cual la conversion se detiene sola.
#:
#: No es una precaucion teorica. El primer intento se corto a mano mirando caer
#: el disco, y llego a 5,4 GB antes de que se pudiera reaccionar. Un guion que
#: depende de que alguien lo este mirando no es una salvaguarda.
PISO_DISCO_GB = 6.0

ORIGEN = "telemetry_messages"
NUEVA = "telemetry_messages_hiper"
RESPALDO = "telemetry_messages_plana_respaldo"

SEGMENTAR_POR = "signal_name, session_id, source_type, vehicle_id"

#: Los indices que la tabla tiene hoy y que hay que recrear.
#:
#: El de identidad de reinyeccion es **parcial y unico**: es la garantia de
#: trazabilidad que impide que una segunda corrida duplique filas, y perderlo en
#: la conversion seria perder una proteccion sin que nada avise.
INDICES = [
    ("hiper_source_session_driver_ts",
     "(source_type, session_id, driver_id, \"timestamp\")", False),
    ("hiper_signal_ts",
     "(signal_name, \"timestamp\" desc)", False),
    ("hiper_replay_identity",
     "(replay_run_id, replay_seq, \"timestamp\") "
     "where replay_run_id is not null and replay_seq is not null", True),
]


def _tramos(cur) -> list:
    """Los tramos a copiar, **por hora y no por dia**.

    El corte por dia fallo por una razon medible: mientras un tramo esta copiado
    y todavia sin comprimir ocupa su tamano completo, y el dia mas grande del
    conjunto son 27,5 millones de filas, unos 23 GB de transito. Con trece
    gigabytes libres eso no entra.

    Por hora, ningun tramo pasa de unos pocos millones de filas. El transito baja
    a menos de dos gigabytes, que **entra sobrado y ademas se puede frenar a
    tiempo** si el disco empieza a ceder.
    """

    # **Se copia por cuartos de hora y se comprime por hora.**
    #
    # Los dos tamanos responden a cosas distintas. La compresion quiere
    # fragmentos grandes, porque agrupa por columnas repetidas y un fragmento
    # chico desperdicia la agrupacion. La copia quiere pedazos chicos, porque
    # cada pedazo tiene que caber entero en una corrida: el tramo mayor de una
    # hora son 5,65 millones de filas y no termina en una sola llamada, de modo
    # que se cortaba a la mitad una y otra vez sin avanzar nunca.
    cur.execute(f"select date_trunc('hour', timestamp) h, "
                f"       date_trunc('hour', timestamp) "
                f"       + make_interval(mins => 15 * (extract(minute from timestamp)::int / 15)) c, "
                f"       count(*) "
                f"from {ORIGEN} group by 1, 2 order by 2")
    return cur.fetchall()


def convertir(intervalo_horas: int, minutos_max: float) -> dict:
    r: dict = {"empezado": datetime.now(timezone.utc).isoformat(), "lotes": []}
    with db.obtener_conexion() as c:
        c.autocommit = True
        cur = c.cursor()

        cur.execute(f"select count(*) from {ORIGEN}")
        r["filas_origen"] = cur.fetchone()[0]
        tramos = _tramos(cur)
        r["tramos_origen"] = {str(c): n for _, c, n in tramos}
        mayor = max(n for _, _, n in tramos)
        horas = sorted({str(h) for h, _, _ in tramos})
        print(f"  origen: {r['filas_origen']:,} filas en {len(tramos)} cuartos "
              f"de hora ({len(horas)} horas); el mayor tiene {mayor:,}",
              flush=True)

        # **Se retoma en lugar de empezar de nuevo.**
        #
        # La conversion completa lleva horas y cualquier interrupcion ---un tope
        # de tiempo, un corte, una decision de frenar por disco--- tiraba a la
        # basura todo lo copiado. Ya paso: quince tramos de treinta y seis se
        # perdieron por un tope de diez minutos.
        #
        # Un tramo se considera hecho cuando **su recuento coincide** con el del
        # origen, no cuando existe: un tramo copiado a medias tiene que rehacerse.
        cur.execute("select count(*) from information_schema.tables "
                    "where table_name = %s", (NUEVA,))
        existe = cur.fetchone()[0] > 0
        hechos: dict[str, int] = {}
        if existe:
            cur.execute(f"select date_trunc('hour', timestamp) "
                        f"       + make_interval(mins => 15 * (extract(minute from timestamp)::int / 15)) c, "
                        f"       count(*) from {NUEVA} group by 1")
            hechos = {str(c): n for c, n in cur.fetchall()}
            print(f"  retomando: {len(hechos)} tramos ya presentes", flush=True)
        else:
            cur.execute(f"create table {NUEVA} (like {ORIGEN} including defaults)")
        # El intervalo **no se puede pasar como parametro**: PostgreSQL no
        # admite `interval $2`. Se construye la cadena y se convierte con un
        # cast explicito, que es la unica forma que el motor acepta.
        if not existe:
            cur.execute("select create_hypertable(%s::regclass, "
                        "by_range('timestamp', (%s || ' hours')::interval))",
                        (NUEVA, str(intervalo_horas)))
            cur.execute(f"alter table {NUEVA} set (timescaledb.compress, "
                        f"timescaledb.compress_segmentby = '{SEGMENTAR_POR}', "
                        f"timescaledb.compress_orderby = 'timestamp')")

        comienzo = time.perf_counter()
        for i, (hora, tramo, esperadas) in enumerate(tramos, 1):
            if hechos.get(str(tramo)) == esperadas:
                continue
            # Se corta **antes** del tope que impone quien lo llama, para
            # terminar el tramo en curso y dejar el estado consistente en lugar
            # de que lo maten a mitad de una copia.
            if (time.perf_counter() - comienzo) / 60 >= minutos_max:
                r["pausada_por_tiempo"] = {"tramo": str(tramo),
                                           "tramos_hechos": i - 1,
                                           "tramos_totales": len(tramos)}
                print(f"  PAUSADA por tiempo en el tramo {i} de {len(tramos)}. "
                      f"Volver a correr para retomar.", flush=True)
                break
            # **Un tramo a medias se borra antes de rehacerlo.**
            #
            # Si la corrida anterior se corto en mitad de una copia, ese tramo
            # tiene filas pero no todas. Volver a insertarlo sin borrar primero
            # **duplicaria** lo ya copiado, y el recuento final daria de mas sin
            # que nada fallara. Es el mismo defecto que el indice unico parcial
            # cubre en el camino de reinyeccion, aca por otra via.
            parcial = hechos.get(str(tramo))
            if parcial:
                cur.execute(
                    f"delete from {NUEVA} where timestamp >= %s "
                    f"and timestamp < %s + interval '15 minutes'", (tramo, tramo))
                print(f"  tramo {i} estaba a medias ({parcial:,} filas): "
                      f"borradas {cur.rowcount:,} para rehacerlo", flush=True)

            libre_gb = shutil.disk_usage(RAIZ).free / 1024 ** 3
            if libre_gb < PISO_DISCO_GB:
                r["detenida_por_disco"] = {
                    "tramo": str(tramo), "libre_gb": round(libre_gb, 1),
                    "tramos_hechos": i - 1, "tramos_totales": len(tramos),
                }
                print(f"  DETENIDA: quedan {libre_gb:.1f} GB, por debajo del "
                      f"piso de {PISO_DISCO_GB} GB. Van {i - 1} de "
                      f"{len(tramos)} tramos.", flush=True)
                break
            t0 = time.perf_counter()
            cur.execute(
                f"insert into {NUEVA} select * from {ORIGEN} "
                f"where timestamp >= %s and timestamp < %s + interval '15 minutes'",
                (tramo, tramo))
            copiadas = cur.rowcount
            copiado_s = time.perf_counter() - t0

            # Se comprime **inmediatamente**, antes de copiar el dia siguiente.
            # Es lo que mantiene la tabla nueva pequena durante todo el proceso
            # y lo que vuelve viable la conversion con poco espacio libre.
            # Se comprime **solo cuando la hora quedo completa**, porque el
            # fragmento es de una hora: comprimirlo antes dejaria los cuartos
            # siguientes fuera de la compresion sin que nada avisara.
            comprimido_s = 0.0
            ultimo_de_la_hora = (i == len(tramos)
                                 or tramos[i][0] != hora)
            if ultimo_de_la_hora:
                t1 = time.perf_counter()
                cur.execute(
                    f"select compress_chunk(c, if_not_compressed => true) "
                    f"from show_chunks(%s, older_than => %s + interval '1 hour') c",
                    (NUEVA, hora))
                comprimido_s = time.perf_counter() - t1

            lote = {"tramo": str(tramo), "esperadas": esperadas,
                    "copiadas": copiadas,
                    "coinciden": copiadas == esperadas,
                    "copiado_s": round(copiado_s, 1),
                    "comprimido_s": round(comprimido_s, 1)}
            r["lotes"].append(lote)
            marca = "ok " if lote["coinciden"] else "NO COINCIDE"
            print(f"  {marca} [{i:3d}/{len(tramos)}] {tramo}: {copiadas:,} de "
                  f"{esperadas:,}  {copiado_s:.0f}s + {comprimido_s:.0f}s",
                  flush=True)

        if r.get("detenida_por_disco") or r.get("pausada_por_tiempo"):
            cur.execute(f"select count(*) from {NUEVA}")
            r["filas_nueva"] = cur.fetchone()[0]
            print(f"  incompleta: {r['filas_nueva']:,} de "
                  f"{r['filas_origen']:,} filas. No se crean indices.",
                  flush=True)
            return r

        print("  creando indices...", flush=True)
        for nombre, definicion, unico in INDICES:
            t0 = time.perf_counter()
            cur.execute(f"create {'unique ' if unico else ''}index {nombre} "
                        f"on {NUEVA} {definicion}")
            print(f"    {nombre}: {time.perf_counter() - t0:.0f} s", flush=True)
        cur.execute(f"analyze {NUEVA}")

        # --- conciliacion ---------------------------------------------------
        cur.execute(f"select count(*) from {NUEVA}")
        r["filas_nueva"] = cur.fetchone()[0]
        cur.execute(f"select date_trunc('hour', timestamp) "
                    f"       + make_interval(mins => 15 * (extract(minute from timestamp)::int / 15)) c, "
                    f"       count(*) from {NUEVA} group by 1 order by 1")
        r["tramos_nueva"] = {str(c): n for c, n in cur.fetchall()}
        r["total_coincide"] = r["filas_nueva"] == r["filas_origen"]
        r["tramos_coinciden"] = r["tramos_nueva"] == r["tramos_origen"]

        cur.execute("select total_bytes from hypertable_detailed_size(%s::regclass)",
                    (NUEVA,))
        r["bytes_nueva"] = sum(f[0] for f in cur.fetchall() if f[0] is not None)
        cur.execute(f"select pg_total_relation_size('{ORIGEN}')")
        r["bytes_origen"] = cur.fetchone()[0]
    return r


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--minutos-max", type=float, default=8.0,
                    help="Se pausa limpio despues de este tiempo, para retomar.")
    ap.add_argument("--intervalo-horas", type=int, default=1,
                    help="Ancho de cada fragmento, en horas.")
    ap.add_argument("--salida", type=Path,
                    default=RAIZ / "logs" / "conversion_hipertabla.json")
    args = ap.parse_args()

    r = convertir(args.intervalo_horas, args.minutos_max)
    args.salida.write_text(json.dumps(r, indent=2, ensure_ascii=False),
                           encoding="utf-8")

    gb = 1024 ** 3
    print()
    print(f"  origen: {r['filas_origen']:,} filas, {r['bytes_origen'] / gb:.1f} GB")
    print(f"  nueva:  {r['filas_nueva']:,} filas, {r['bytes_nueva'] / gb:.2f} GB")
    print(f"  relacion: {r['bytes_origen'] / max(r['bytes_nueva'], 1):.1f}x")
    print()
    print(f"  total coincide: {r['total_coincide']}")
    print(f"  cada tramo coincide: {r['tramos_coinciden']}")
    malos = [l for l in r["lotes"] if not l["coinciden"]]
    if malos:
        print(f"  TRAMOS QUE NO COINCIDEN: {[l['tramo'] for l in malos]}")
    print()
    print("  La tabla original NO se toco. El intercambio de nombres y el")
    print("  borrado son pasos aparte, y este guion no los hace.")
    print(f"  detalle en {args.salida}")


if __name__ == "__main__":
    main()
