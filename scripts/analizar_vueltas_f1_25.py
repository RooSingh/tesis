"""Analiza vuelta por vuelta una captura, detectando incidentes desde los canales.

Que hace distinto del analizador de carrera
-------------------------------------------
El analizador de carrera reconstruye la sesion: coche de seguridad, paradas,
penalizaciones. Este mira **cada vuelta** y responde por que salio como salio.

Los incidentes no se leen del registro de eventos sino que **se detectan en los
canales**. Es deliberado: el juego declara que una vuelta fue invalidada, pero no
que ocurrio. Una salida de pista, un golpe y una perdida de tren trasero producen
la misma invalidacion y son cosas distintas.

Cada regla declara en que canal se apoya y con que umbral. Esa transparencia no
es adorno: **una anotacion es una afirmacion**, y una que no puede justificarse
vale menos que su ausencia. Una condicion que no se cumple con claridad no se
anota.

Es ademas el prototipo de las anotaciones en vivo que el cronograma tiene
previstas: la misma logica, aplicada al flujo en lugar de al archivo.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import f1_capture, f1_udp

#: Transcrita del apendice "Surface types" y definida en el modulo del
#: protocolo, que es donde vive la especificacion. Se importa y no se copia: la
#: copia escrita de memoria del anotador en vivo ya quedo corrida una vez.
SUPERFICIES = f1_udp.SUPERFICIES

#: Umbrales, calibrados contra las vueltas que el propio juego declara validas.
#:
#: El criterio de calibracion es el que hace verificable a una regla: **una regla
#: que se dispara en una vuelta limpia es una regla mala**. Las vueltas limpias
#: son la referencia porque el juego ya afirmo que no tuvieron incidente, de modo
#: que cualquier anotacion sobre ellas es un falso positivo por definicion.
#:
#: La primera version de este modulo fijo los umbrales a ojo y anoto 156
#: incidentes en una captura de siete vueltas, 96 de ellos por pisar un piano a
#: doscientos kilometros por hora sin perder velocidad. Eso no es un incidente:
#: es como se conduce.

#: Aceleracion vertical. Medida sobre las vueltas limpias de las dos capturas de
#: Hungaroring: mediana 0,058 g, percentil 99 en 0,653 g y maximo 2,556 g. El
#: umbral se pone por encima del percentil 99,9 —1,313 g— porque por debajo se
#: confunde con un piano tomado con fuerza, que es conduccion normal.
UMBRAL_VERTICAL_G = 1.5

#: Deslizamiento del eje motriz. El techo que la asistencia impone se midio en
#: 14 % sobre dos capturas independientes; el umbral lo excede con holgura para
#: que solo entren las perdidas reales y no la traccion al limite.
UMBRAL_DESLIZAMIENTO = 0.25

#: Caida de velocidad con el freno suelto. A 5 g, que es la frenada maxima
#: observada, medio segundo da unos 88 km/h **sostenidos**: una caida de 40 con
#: el freno liberado no la explica la frenada.
UMBRAL_CAIDA_KMH = 40.0
VENTANA_CAIDA_S = 0.5

#: Que es pista, y que solo tiene agarre. Se importan del modulo del protocolo.
#:
#: La distincion no es un detalle: **estar fuera de pista no es una magnitud que
#: se mida, es una condicion que el reglamento define**, y el articulo 33.3
#: declara que el piano no es pista. Que sobre un piano haya agarre es otra cosa,
#: y es la que importa para explicar por que se perdio el control.
SUPERFICIE_DE_PISTA = f1_udp.SUPERFICIE_DE_PISTA
SUPERFICIES_CON_AGARRE = f1_udp.SUPERFICIES_CON_AGARRE

#: Duracion minima de una excursion para considerarla tal, y perdida de velocidad
#: minima para anotar una que sea mas corta.
MINIMO_EXCURSION_S = 0.4
MINIMA_PERDIDA_EXCURSION_KMH = 15.0


#: Eventos que abren un intento. El juego los emite en cada reinicio de carrera
#: sin cambiar el identificador de sesion.
INICIO_DE_INTENTO = frozenset({"SSTA", "LGOT"})


def _ultimo_intento(ruta: Path) -> int:
    """Indice del datagrama donde arranca la ultima largada de la captura.

    Devuelve cero si no hay ninguna, que es el caso de una contrarreloj.
    """

    ultimo = 0
    for indice, d in enumerate(f1_capture.leer_captura(ruta)):
        try:
            r = f1_udp.decodificar(d.carga)
        except f1_udp.ErrorDecodificacion:
            continue
        if (r.get("decodificado") and r["paquete"] == "event"
                and r.get("codigo") in INICIO_DE_INTENTO):
            ultimo = indice
    return ultimo


def leer(ruta: Path) -> tuple[dict, list, int, dict, dict | None]:
    propio = None
    marcos: dict = defaultdict(dict)
    eventos = []
    historial: dict = {}
    posiciones = None
    # Solo el ultimo intento.
    #
    # Una captura puede contener varias largadas con un unico identificador de
    # sesion. Agrupar por numero de vuelta sin separarlas mezcla vueltas de
    # carreras distintas y produce tiempos que no son de nadie.
    desde = _ultimo_intento(ruta)
    for indice, d in enumerate(f1_capture.leer_captura(ruta)):
        if indice < desde:
            continue
        try:
            r = f1_udp.decodificar(d.carga)
        except f1_udp.ErrorDecodificacion:
            continue
        if propio is None:
            propio = r["cabecera"]["player_car_index"]
        f = r["cabecera"]["frame_identifier"]
        p = r["paquete"]
        if p == "car_telemetry":
            marcos[f]["tel"] = r["vehiculo_propio"]
            marcos[f]["us"] = d.desplazamiento_us
        elif p == "lap_data" and r.get("decodificado"):
            marcos[f]["lap"] = r["vehiculos"][propio]
        elif p == "motion" and r.get("decodificado"):
            marcos[f]["mov"] = r["vehiculo_propio"]
        elif p == "motion_ex" and r.get("decodificado"):
            marcos[f]["dyn"] = r["sesion"]
        elif p == "event":
            eventos.append((d.desplazamiento_us, r))
        elif p == "session_history" and r.get("decodificado"):
            # El paquete describe **un** vehiculo por vez y el juego rota entre
            # ellos, de modo que la parrilla completa se arma acumulando. Se
            # conserva el ultimo de cada uno: es el mas completo.
            historial[r["historial"]["car_idx"]] = r["historial"]
        elif p == "lap_positions" and r.get("decodificado"):
            posiciones = r["posiciones"]
    completos = {f: v for f, v in marcos.items()
                 if {"tel", "lap", "mov", "us"} <= v.keys()}
    return completos, eventos, propio, historial, posiciones


def detectar(completos: dict) -> list[dict]:
    """Recorre los marcos y anota lo que los canales declaran.

    Se agrupan los marcos consecutivos de una misma condicion en un solo
    incidente: un vehiculo sobre el cesped durante dos segundos son cuarenta
    marcos, y anotarlos por separado seria ruido.
    """

    orden = sorted(completos)
    anotaciones: list[dict] = []
    abierto: dict | None = None

    for i, f in enumerate(orden):
        v = completos[f]
        tel, mov, lap = v["tel"], v["mov"], v["lap"]

        fuera = {r: SUPERFICIES.get(s, f"id-{s}")
                 for r, s in tel["surface_type"].items() if s != 0}
        vertical = abs(mov["g_force_vertical"])

        desliz = 0.0
        if "dyn" in v:
            traseras = ("trasera_izquierda", "trasera_derecha")
            desliz = max(abs(v["dyn"]["wheel_slip_ratio"][r]) for r in traseras)

        # Caida de velocidad en la ventana, con el freno suelto **durante toda
        # la ventana** y no solo al final.
        #
        # Verificarlo solo en el ultimo instante convertia cada frenada normal en
        # un incidente: se frena fuerte, se suelta al entrar en la curva, y en
        # ese marco la regla veia una caida grande con el freno libre. Diez de
        # las anotaciones sobre vueltas limpias venian de ahi.
        caida = 0.0
        j = i
        freno_maximo = tel["brake"]
        while j > 0 and (v["us"] - completos[orden[j]]["us"]) < VENTANA_CAIDA_S * 1e6:
            j -= 1
            freno_maximo = max(freno_maximo, completos[orden[j]]["tel"]["brake"])
        if j < i and freno_maximo < 0.3:
            caida = completos[orden[j]]["tel"]["speed_kmh"] - tel["speed_kmh"]

        motivos = []
        # Fuera de pista segun el articulo 33.3 del reglamento deportivo: se
        # juzga que el vehiculo dejo la pista cuando **ninguna parte** sigue en
        # contacto con ella, y el piano no es pista. El criterio anterior de este
        # guion era propio —tres ruedas fuera de asfalto y piano— y tiene que
        # decir lo mismo que el anotador en vivo o las dos lecturas de la tesis
        # divergen.
        codigos = list(tel["surface_type"].values())
        if codigos and all(c != SUPERFICIE_DE_PISTA for c in codigos):
            superficies = sorted({SUPERFICIES.get(c, f"id-{c}") for c in codigos})
            motivos.append(("fuera de pista", "/".join(superficies), len(codigos)))
        if vertical > UMBRAL_VERTICAL_G:
            motivos.append(("impacto vertical", f"{mov['g_force_vertical']:+.2f} g", 0))
        if desliz > UMBRAL_DESLIZAMIENTO and tel["throttle"] > 0.5:
            motivos.append(("perdida de tren trasero", f"{desliz*100:.0f} %", 0))
        if caida > UMBRAL_CAIDA_KMH:
            motivos.append(("caida brusca de velocidad",
                            f"-{caida:.0f} km/h en {VENTANA_CAIDA_S} s", 0))

        if motivos:
            clave = tuple(sorted(m[0] for m in motivos))
            if abierto and abierto["clave"] == clave and \
                    (v["us"] - abierto["fin_us"]) < 1_000_000:
                abierto["fin_us"] = v["us"]
                abierto["marcos"] += 1
                abierto["vel_min"] = min(abierto["vel_min"], tel["speed_kmh"])
                abierto["vert_max"] = max(abierto["vert_max"], vertical)
                abierto["desliz_max"] = max(abierto["desliz_max"], desliz)
                for m in motivos:
                    abierto["detalle"].setdefault(m[0], m[1])
            else:
                if abierto:
                    anotaciones.append(abierto)
                abierto = {
                    "clave": clave, "vuelta": lap["current_lap_num"],
                    "inicio_us": v["us"], "fin_us": v["us"], "marcos": 1,
                    "distancia_m": lap["lap_distance_m"],
                    "vel_entrada": tel["speed_kmh"], "vel_min": tel["speed_kmh"],
                    "vert_max": vertical, "desliz_max": desliz,
                    "detalle": {m[0]: m[1] for m in motivos},
                }
        elif abierto and (v["us"] - abierto["fin_us"]) > 1_000_000:
            anotaciones.append(abierto)
            abierto = None

    if abierto:
        anotaciones.append(abierto)
    return anotaciones


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captura", type=Path)
    parser.add_argument("--minimo-marcos", type=int, default=3,
                        help="Ignora anotaciones mas cortas que esto.")
    args = parser.parse_args()

    completos, eventos, propio, historial, posiciones = leer(args.captura)
    intentos = sum(1 for _, r in eventos if r["codigo"] in INICIO_DE_INTENTO)
    print(f"{args.captura.name}")
    print(f"marcos completos: {len(completos):,}"
          f"   (solo el ultimo intento de la captura)\n")

    # Vueltas: tiempo, validez y motivo declarado por el juego.
    por_vuelta: dict = {}
    for f in sorted(completos):
        l = completos[f]["lap"]
        n = l["current_lap_num"]
        d = por_vuelta.setdefault(n, {"inval": 0, "boxes": 0, "tiempo": None})
        d["inval"] |= l["current_lap_invalid"]
        d["boxes"] |= 1 if l["pit_status"] else 0
    orden = sorted(por_vuelta)

    # Cuando empezo cada vuelta, para poder conciliar lo que el juego declara.
    inicio_s: dict = {}
    for f in sorted(completos):
        n = completos[f]["lap"]["current_lap_num"]
        inicio_s.setdefault(n, completos[f]["us"] / 1e6)

    for n in orden:
        siguientes = [f for f in sorted(completos)
                      if completos[f]["lap"]["current_lap_num"] == n + 1]
        if not siguientes:
            continue
        # El **primer** marco de la vuelta siguiente, no el ultimo.
        #
        # El canal se reescribe despues de la bandera a cuadros: en la primera
        # pasada de la prueba de dos conductores, el tiempo de la cuarta vuelta
        # del conductor rapido paso de 117.553 a 76.216 ms en el segundo 423,72,
        # cuatro segundos despues de la bandera del 419,68. Leer el ultimo valor
        # archivaba el numero de despues de la carrera.
        declarado = completos[siguientes[0]]["lap"]["last_lap_time_ms"] / 1000
        por_vuelta[n]["tiempo"] = declarado

        # Y se concilia contra el reloj, que el propio dato ofrece. Es la misma
        # disciplina de siempre: una cifra se verifica contra lo que deberia
        # dar, no contra la impresion de que es razonable.
        if n in inicio_s and (n + 1) in inicio_s:
            transcurrido = inicio_s[n + 1] - inicio_s[n]
            por_vuelta[n]["transcurrido"] = transcurrido
            # Un decimo y medio de segundo cubre el intervalo entre marcos a
            # 20 Hz sin tolerar una diferencia que signifique algo.
            #
            # La primera vuelta queda fuera: el reloj de la vuelta arranca cuando
            # se apagan las luces y los primeros marcos son de la parrilla, de
            # modo que la diferencia es la espera de la largada y no un error.
            # Marcarla como discrepancia haria que el aviso perdiera sentido por
            # aparecer siempre.
            if n > 1 and abs(declarado - transcurrido) > 0.15:
                por_vuelta[n]["discrepancia"] = round(declarado - transcurrido, 3)
            elif n == 1:
                por_vuelta[n]["espera_de_largada_s"] = round(
                    transcurrido - declarado, 3)

    anotaciones = [a for a in detectar(completos) if a["marcos"] >= args.minimo_marcos]
    por_vuelta_anot: dict = defaultdict(list)
    for a in anotaciones:
        por_vuelta_anot[a["vuelta"]].append(a)

    penalizaciones: dict = defaultdict(list)
    for us, r in eventos:
        if r["codigo"] == "PENA" and r["detalle"]["vehiculo"] == propio:
            penalizaciones[r["detalle"]["vuelta"]].append(r["detalle"])

    # Colisiones, atribuidas a la vuelta que corria el auto en ese instante.
    #
    # **La bandera de vuelta invalida del juego no las marca.** En la primera
    # pasada de la prueba de dos conductores hubo diecinueve colisiones entre los
    # dos conductores y el juego no invalido ninguna vuelta: una colision no
    # infringe el reglamento de la pista, de modo que el juego no tiene por que
    # anular la vuelta. Pero un golpe cuesta velocidad, y una vuelta con un golpe
    # no es comparable contra una sin golpe.
    #
    # Es la misma leccion que el articulo 33.3 sobre los limites de pista: el
    # criterio del juego responde una pregunta y el nuestro responde otra.
    colisiones: dict = defaultdict(list)
    marcos_ordenados = sorted(completos)
    for us, r in eventos:
        if r["codigo"] != "COLL":
            continue
        det = r["detalle"]
        if propio not in (det["vehiculo_1"], det["vehiculo_2"]):
            continue
        otro = det["vehiculo_2"] if det["vehiculo_1"] == propio else det["vehiculo_1"]
        if not marcos_ordenados:
            continue
        # Por tiempo y no por numero de marco: el evento trae microsegundos y la
        # clave del marco es un contador. Compararlos entre si mandaba las doce
        # colisiones a la ultima vuelta y dejaba las cuatro primeras como
        # comparables, que es justo la conclusion que este criterio existe para
        # evitar.
        cercano = min(marcos_ordenados,
                      key=lambda f: abs(completos[f]["us"] - us))
        colisiones[completos[cercano]["lap"]["current_lap_num"]].append(
            {"us": us, "otro": otro})

    print("=" * 78)
    print("VUELTA POR VUELTA")
    print("=" * 78)
    for n in orden:
        d = por_vuelta[n]
        tiempo = f"{d['tiempo']:.3f} s" if d["tiempo"] else "sin cerrar"
        golpes = colisiones.get(n, [])
        if d["inval"]:
            estado = "INVALIDA"
        elif d["boxes"]:
            estado = "boxes"
        elif golpes:
            estado = f"CON COLISION ({len(golpes)})"
        else:
            estado = "limpia"
        print(f"\n  Vuelta {n}: {tiempo}   {estado}")
        if d.get("discrepancia") is not None:
            print(f"    ATENCION: el juego declara {d['tiempo']:.3f} s y el reloj"
                  f" da {d['transcurrido']:.3f} s"
                  f" (diferencia {d['discrepancia']:+.3f} s)")
        if d.get("espera_de_largada_s") is not None:
            print(f"    espera en la parrilla: {d['espera_de_largada_s']:.3f} s")
        for p in penalizaciones.get(n, []):
            print(f"    el juego declara: "
                  f"{p.get('tipo_penalizacion_nombre', '?')} por "
                  f"{p.get('tipo_infraccion_nombre', p['tipo_infraccion'])}")
        for c in golpes:
            print(f"    colision con el vehiculo {c['otro']} "
                  f"(segundo {c['us'] / 1e6:.2f})")
        anot = por_vuelta_anot.get(n, [])
        if not anot:
            print("    sin incidentes detectados en los canales")
            continue
        for a in anot:
            dur = (a["fin_us"] - a["inicio_us"]) / 1e6
            print(f"    metro {a['distancia_m']:>6.0f}  {', '.join(a['clave'])}"
                  f"   ({dur:.1f} s, {a['marcos']} marcos)")
            for clave, valor in a["detalle"].items():
                print(f"        {clave:<28}{valor}")
            print(f"        velocidad{'':<19}{a['vel_entrada']} -> {a['vel_min']} km/h")

    # --- Sectores y rivales, del historial de sesion ---------------------- #
    #
    # Es lo unico que este paquete habilita y ninguna otra via daba: el tiempo
    # por sector, la validez **de cada sector** por separado, y los tiempos de
    # los otros diecinueve. Antes el analisis solo podia hablar del vehiculo
    # propio y sin sectores.
    if historial:
        print()
        print("=" * 78)
        print("SECTORES, DEL HISTORIAL DE SESION")
        print("=" * 78)
        mio = historial.get(propio)
        if mio:
            print(f"\n  vehiculo propio ({propio}), mejor vuelta la "
                  f"{mio['mejor_vuelta_num']}")
            for v in mio["vueltas"]:
                if not v["lap_time_ms"]:
                    continue
                # La validez viaja por sector: una vuelta invalida puede tener
                # dos sectores validos, y eso dice donde se perdio.
                banderas = "".join(
                    ("V" if v[f"sector{i}_valido"] else "x") for i in (1, 2, 3))
                print(f"     v{v['numero']}: {v['lap_time_ms'] / 1000:8.3f} s   "
                      f"s1 {v['sector1_ms'] / 1000:7.3f}  "
                      f"s2 {v['sector2_ms'] / 1000:7.3f}  "
                      f"s3 {v['sector3_ms'] / 1000:7.3f}   "
                      f"sectores {banderas}"
                      f"{'' if v['vuelta_valida'] else '   VUELTA INVALIDA'}")
            for tanda in mio["tandas"]:
                fin = ("en curso" if tanda["vuelta_final"] == 255
                       else f"hasta la vuelta {tanda['vuelta_final']}")
                print(f"     tanda: compuesto {tanda['compuesto_real']}, {fin}")

        # La mejor vuelta de cada vehiculo, que es la referencia contra la que
        # se lee la propia.
        mejores = []
        for idx, x in historial.items():
            validas = [v["lap_time_ms"] for v in x["vueltas"]
                       if v["lap_time_ms"] and v["vuelta_valida"]]
            if validas:
                mejores.append((min(validas), idx))
        if mejores:
            mejores.sort()
            print(f"\n  mejor vuelta de cada vehiculo, {len(mejores)} con vuelta valida:")
            for ms, idx in mejores[:8]:
                marca = "  <- propio" if idx == propio else ""
                print(f"     {ms / 1000:8.3f} s   vehiculo {idx:2d}{marca}")
            if mio and mejores[0][1] != propio:
                mias = [v["lap_time_ms"] for v in mio["vueltas"]
                        if v["lap_time_ms"] and v["vuelta_valida"]]
                if mias:
                    print(f"\n     diferencia contra el mejor: "
                          f"{(min(mias) - mejores[0][0]) / 1000:+.3f} s")

    if posiciones and posiciones.get("por_vuelta"):
        print()
        print("  posicion del vehiculo propio, vuelta a vuelta:")
        recorrido = [fila[propio] for fila in posiciones["por_vuelta"]
                     if propio < len(fila)]
        # Un cero significa "sin registro" y no "puesto cero".
        legibles = [f"v{i + 1}={x}" for i, x in enumerate(recorrido) if x]
        print("     " + "  ".join(legibles))

    print()
    print("=" * 78)
    print("RESUMEN")
    print("=" * 78)
    # El criterio del juego responde "esta vuelta cuenta para el reglamento". El
    # nuestro responde "esta vuelta se puede comparar contra otra". Son preguntas
    # distintas y dan listas distintas, de modo que se informan las dos: publicar
    # solo la del juego haria pasar por comparable una vuelta que un golpe
    # arruino.
    validas = [n for n in orden if not por_vuelta[n]["inval"]
               and not por_vuelta[n]["boxes"] and por_vuelta[n]["tiempo"]]
    comparables = [n for n in validas if not colisiones.get(n)]
    aviso = "" if comparables else "   <- ninguna: no hay par de vueltas limpias"
    print(f"  vueltas               : {len(orden)}")
    print(f"  validas para el juego : {validas}")
    print(f"  comparables entre si  : {comparables}{aviso}")
    print(f"  colisiones            : {sum(len(v) for v in colisiones.values())}")
    print(f"  incidentes         : {len(anotaciones)}")
    tipos: dict = defaultdict(int)
    for a in anotaciones:
        for k in a["clave"]:
            tipos[k] += 1
    for k, v in sorted(tipos.items(), key=lambda x: -x[1]):
        print(f"    {k:<30}{v}")


if __name__ == "__main__":
    main()
