"""Reconstruye una carrera a partir de una captura cruda.

Que reconstruye y por que asi
-----------------------------
Una carrera no se explica con canales continuos. La velocidad muestra que el
vehiculo freno; no dice si fue por bandera amarilla, por una parada en boxes o
por un error de conduccion. Este analisis cruza tres cosas que el flujo entrega
por vias distintas:

* **el registro de eventos**, que declara el coche de seguridad, las
  penalizaciones, los abandonos y los adelantamientos;
* **los datos de vuelta**, que declaran la posicion, las paradas y el estado en
  pista de cada vehiculo;
* **el estado y el dano**, que declaran la energia recuperada y desplegada, el
  desgaste de neumaticos y el deterioro acumulado.

Cruzarlos no es una comodidad: hay hechos que **ningun paquete declara solo**.
El motivo de un abandono llega vacio en el evento de abandono y completo en la
penalizacion que lo acompana; el motivo del coche de seguridad no esta en el
evento del coche de seguridad sino en el abandono que ocurre segundos antes.

Es generico
-----------
Nada esta atado a una sesion, un circuito ni un piloto. El vehiculo de interes
se lee de la cabecera y la duracion, del propio archivo.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import f1_capture, f1_udp

TIPOS_PENALIZACION = {
    0: "paso por boxes", 1: "detencion obligatoria", 2: "penalizacion de parrilla",
    3: "recordatorio", 4: "penalizacion de tiempo", 5: "aviso", 6: "descalificacion",
    7: "excluido de la vuelta de formacion", 8: "detenido demasiado tiempo",
    9: "reglamento de neumaticos", 10: "vuelta invalidada",
    11: "vuelta actual y siguiente invalidadas", 12: "vuelta invalidada sin motivo",
    13: "vuelta actual y siguiente invalidadas sin motivo",
    14: "vuelta actual y anterior invalidadas",
    15: "vuelta actual y anterior invalidadas sin motivo",
    16: "abandono", 17: "temporizador de bandera negra",
}
INFRACCIONES = {
    0: "bloqueo por marcha lenta", 1: "bloqueo en contramano",
    2: "marcha atras en la largada", 3: "colision fuerte", 4: "colision leve",
    5: "no devolvio la posicion", 6: "no devolvio varias posiciones",
    7: "recorte de curva con ventaja", 8: "adelantamiento recortando curva",
    9: "varios adelantamientos recortando curva", 10: "cruce del carril de boxes",
    11: "ignoro banderas azules", 12: "ignoro banderas amarillas",
    13: "ignoro el paso por boxes", 14: "demasiados pasos por boxes",
    15: "recordatorio de paso por boxes", 16: "paso por boxes en esta vuelta",
    17: "exceso de velocidad en boxes", 18: "detenido demasiado tiempo",
    19: "ignoro reglamento de neumaticos", 20: "demasiadas penalizaciones",
    21: "varios avisos", 22: "cerca de la descalificacion",
    23: "seleccion de neumaticos", 24: "seleccion multiple de neumaticos",
    25: "vuelta invalidada por recorte", 26: "vuelta invalidada por salirse",
    27: "recorte con ventaja menor", 28: "recorte con ventaja significativa",
    29: "recorte con ventaja extrema", 30: "vuelta invalidada por rozar el muro",
    31: "vuelta invalidada por retroceso", 32: "vuelta invalidada por reposicion",
    33: "bloqueo del carril de boxes", 34: "largada anticipada",
    35: "colision con el coche de seguridad",
    36: "adelantamiento ilegal tras el coche de seguridad",
    37: "ritmo excesivo tras el coche de seguridad",
    38: "ritmo excesivo con coche de seguridad virtual",
    39: "velocidad insuficiente en la vuelta de formacion",
    40: "detencion en la vuelta de formacion", 41: "abandono por falla mecanica",
    42: "abandono por dano terminal",
    43: "quedo demasiado atras del coche de seguridad",
    44: "temporizador de bandera negra", 45: "detencion obligatoria no cumplida",
}
COMPUESTOS = {16: "blando", 17: "medio", 18: "duro", 7: "intermedio",
              8: "lluvia", 20: "blando", 21: "medio", 22: "duro"}
MODOS_ERS = {0: "ninguno", 1: "medio", 2: "acumulacion", 3: "vuelta rapida",
             4: "maximo"}

# Los 4 MJ **no son la capacidad** del acumulador: el reglamento no fija ninguna.
# Son el maximo admitido de **diferencia entre la carga maxima y la minima**
# mientras el vehiculo esta en pista, art. 5.3.2. Llamarlo capacidad seria
# afirmar algo que la norma no dice, y el porcentaje que se calcula con el valor
# es sobre la franja utilizable, no sobre un deposito.
ERS_FRANJA_UTIL_J = 4_000_000.0


def _minuto(us: int) -> str:
    return f"{us / 6e7:6.2f}"


def analizar(ruta: Path) -> dict:
    eventos: list[dict] = []
    propio: int | None = None

    vueltas: dict[int, dict] = {}
    ers_por_vuelta: dict[int, dict] = {}
    dano_final = None
    estado_final = None
    vuelta_actual = None
    paradas: list[dict] = []
    en_boxes = False
    duracion_us = 0
    periodos_sc: list[tuple[int, int]] = []
    sc_desde = None

    for d in f1_capture.leer_captura(ruta):
        duracion_us = d.desplazamiento_us
        try:
            r = f1_udp.decodificar(d.carga)
        except f1_udp.ErrorDecodificacion:
            continue
        if propio is None:
            propio = r["cabecera"]["player_car_index"]

        clase = r["paquete"]

        if clase == "event":
            eventos.append({"us": d.desplazamiento_us, **r})
            det = r["detalle"]
            # Solo el coche de seguridad real; la vuelta de formacion es tipo 3.
            if r["codigo"] == "SCAR" and det.get("tipo") == 1:
                if det.get("fase") == 0:
                    sc_desde = d.desplazamiento_us
                elif det.get("fase") == 3 and sc_desde is not None:
                    periodos_sc.append((sc_desde, d.desplazamiento_us))
                    sc_desde = None

        elif clase == "lap_data" and r.get("decodificado"):
            v = r["vehiculos"][propio]
            n = v["current_lap_num"]
            if vuelta_actual is not None and n != vuelta_actual:
                anterior = vueltas.get(vuelta_actual)
                if anterior is not None:
                    # El tiempo de la vuelta que termina lo declara el paquete
                    # siguiente, no el ultimo de la vuelta que cierra.
                    anterior["tiempo_ms"] = v["last_lap_time_ms"]
            vuelta_actual = n
            vueltas.setdefault(n, {"vuelta": n, "us_inicio": d.desplazamiento_us,
                                   "invalida": 0})
            vueltas[n]["posicion"] = v["car_position"]
            vueltas[n]["invalida"] |= v["current_lap_invalid"]
            vueltas[n]["penalizaciones_s"] = v["penalties_s"]
            vueltas[n]["avisos"] = v["total_warnings"]
            vueltas[n]["paradas"] = v["num_pit_stops"]
            vueltas[n]["retraso_coche_seguridad_s"] = round(v["safety_car_delta_s"], 2)

            ahora_en_boxes = v["pit_status"] != 0
            if ahora_en_boxes and not en_boxes:
                paradas.append({"vuelta": n, "us_entrada": d.desplazamiento_us,
                                "detenido_ms": 0})
            elif ahora_en_boxes and paradas:
                # El cronometro de la detencion vuelve a cero al salir, de modo
                # que leerlo en la salida da siempre 0: hay que conservar el
                # maximo alcanzado mientras el vehiculo estuvo en boxes.
                paradas[-1]["detenido_ms"] = max(paradas[-1]["detenido_ms"],
                                                 v["pit_stop_timer_ms"])
            elif not ahora_en_boxes and en_boxes and paradas:
                paradas[-1]["us_salida"] = d.desplazamiento_us
                paradas[-1]["duracion_s"] = round(
                    (d.desplazamiento_us - paradas[-1]["us_entrada"]) / 1e6, 2)
                paradas[-1]["tiempo_detenido_s"] = round(
                    paradas[-1]["detenido_ms"] / 1000, 2)
            en_boxes = ahora_en_boxes

        elif clase == "car_status" and r.get("decodificado"):
            e = r["vehiculos"][propio]
            estado_final = e
            if vuelta_actual is not None:
                c = ers_por_vuelta.setdefault(vuelta_actual, {
                    "carga_min_j": e["ers_store_energy_j"],
                    "carga_max_j": e["ers_store_energy_j"], "modos": set(),
                })
                c["carga_min_j"] = min(c["carga_min_j"], e["ers_store_energy_j"])
                c["carga_max_j"] = max(c["carga_max_j"], e["ers_store_energy_j"])
                c["modos"].add(MODOS_ERS.get(e["ers_deploy_mode"], "?"))
                c["recuperado_mguk_j"] = e["ers_harvested_this_lap_mguk_j"]
                c["recuperado_mguh_j"] = e["ers_harvested_this_lap_mguh_j"]
                c["desplegado_j"] = e["ers_deployed_this_lap_j"]
                c["compuesto"] = COMPUESTOS.get(e["visual_tyre_compound"], "?")
                c["edad_neumatico_vueltas"] = e["tyres_age_laps"]
                c["combustible_kg"] = round(e["fuel_in_tank_kg"], 2)

        elif clase == "car_damage" and r.get("decodificado"):
            dano_final = r["vehiculos"][propio]

    for c in ers_por_vuelta.values():
        c["modos"] = sorted(c["modos"])

    return {
        "vehiculo_propio": propio,
        "duracion_s": round(duracion_us / 1e6, 2),
        "eventos": eventos,
        "vueltas": [vueltas[k] for k in sorted(vueltas)],
        "ers": {k: ers_por_vuelta[k] for k in sorted(ers_por_vuelta)},
        "paradas": paradas,
        "dano_final": dano_final,
        "estado_final": estado_final,
        "coche_de_seguridad": periodos_sc,
    }


def informar(a: dict) -> None:
    propio = a["vehiculo_propio"]
    print(f"Vehiculo propio: indice {propio}   duracion {a['duracion_s'] / 60:.1f} min")

    print()
    print("=" * 78)
    print("COCHE DE SEGURIDAD")
    print("=" * 78)
    if not a["coche_de_seguridad"]:
        print("  no hubo periodos de coche de seguridad")
    for desde, hasta in a["coche_de_seguridad"]:
        print(f"  de {_minuto(desde)} min a {_minuto(hasta)} min "
              f"-> {(hasta - desde) / 6e7:.2f} min neutralizados")
        # El motivo no lo declara el evento del coche de seguridad.
        for e in a["eventos"]:
            if e["codigo"] in ("RTMT", "COLL") and 0 <= desde - e["us"] <= 60_000_000:
                print(f"    causa a {_minuto(e['us'])} min: {e['evento']} {e['detalle']}")

    print()
    print("=" * 78)
    print("PENALIZACIONES DEL VEHICULO PROPIO")
    print("=" * 78)
    hubo = False
    for e in a["eventos"]:
        if e["codigo"] != "PENA" or e["detalle"]["vehiculo"] != propio:
            continue
        hubo = True
        d = e["detalle"]
        tiempo = f", {d['tiempo_s']} s" if d["tiempo_s"] != 255 else ""
        print(f"  {_minuto(e['us'])} min  vuelta {d['vuelta']:>2}  "
              f"{TIPOS_PENALIZACION.get(d['tipo_penalizacion'], '?')}: "
              f"{INFRACCIONES.get(d['tipo_infraccion'], '?')}{tiempo}")
    if not hubo:
        print("  ninguna")

    print()
    print("=" * 78)
    print("PARADAS EN BOXES")
    print("=" * 78)
    if not a["paradas"]:
        print("  ninguna")
    for p in a["paradas"]:
        print(f"  vuelta {p['vuelta']:>2}  entrada {_minuto(p['us_entrada'])} min  "
              f"en el carril {p.get('duracion_s', '?')} s  "
              f"detenido {p.get('tiempo_detenido_s', '?')} s")

    print()
    print("=" * 78)
    print("ENERGIA, COMBUSTIBLE Y NEUMATICO POR VUELTA")
    print("=" * 78)
    print(f"  {'v':>2} {'carga min':>10} {'carga max':>10} {'recuperado':>12} "
          f"{'desplegado':>12} {'comb':>8} {'neum':>10} {'edad':>5}  modos")
    for n, c in a["ers"].items():
        rec = c.get("recuperado_mguk_j", 0) + c.get("recuperado_mguh_j", 0)
        print(f"  {n:>2} {c['carga_min_j'] / ERS_FRANJA_UTIL_J * 100:>9.1f}% "
              f"{c['carga_max_j'] / ERS_FRANJA_UTIL_J * 100:>9.1f}% "
              f"{rec / 1e6:>9.2f} MJ {c.get('desplegado_j', 0) / 1e6:>9.2f} MJ "
              f"{c.get('combustible_kg', 0):>6.1f}kg {c.get('compuesto', '?'):>10} "
              f"{c.get('edad_neumatico_vueltas', 0):>5}  {', '.join(c['modos'])}")

    print()
    print("=" * 78)
    print("DANO AL FINAL DE LA CARRERA (solo lo distinto de cero)")
    print("=" * 78)
    d = a["dano_final"]
    if d is None:
        print("  el paquete de dano no llego")
    else:
        for campo, valor in sorted(d.items()):
            if isinstance(valor, dict):
                if any(valor.values()):
                    print(f"  {campo:<32} {valor}")
            elif isinstance(valor, (list, tuple)):
                if any(valor):
                    print(f"  {campo:<32} {list(valor)}")
            elif valor:
                print(f"  {campo:<32} {valor}")

    print()
    print("=" * 78)
    print("VUELTA A VUELTA")
    print("=" * 78)
    print(f"  {'v':>2} {'pos':>4} {'tiempo':>10} {'inval':>6} {'penal s':>8} "
          f"{'avisos':>7} {'paradas':>8}")
    for v in a["vueltas"]:
        t = v.get("tiempo_ms")
        texto = f"{t / 1000:.3f}" if t else "-"
        print(f"  {v['vuelta']:>2} {v.get('posicion', '?'):>4} {texto:>10} "
              f"{v['invalida']:>6} {v.get('penalizaciones_s', 0):>8} "
              f"{v.get('avisos', 0):>7} {v.get('paradas', 0):>8}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captura", type=Path)
    parser.add_argument("--json", type=Path, default=None,
                        help="Escribe el analisis completo en este archivo.")
    args = parser.parse_args()

    a = analizar(args.captura)
    informar(a)
    if args.json:
        args.json.write_text(json.dumps(a, indent=2, ensure_ascii=False, default=str),
                             encoding="utf-8")
        print(f"\nanalisis completo: {args.json}")


if __name__ == "__main__":
    main()
