#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mide las curvas de un circuito para poder nombrarlas, y dice cuanto confiar.

POR QUE ES UN GUION Y NO UNA RUTA
---------------------------------
Lo que produce no es una respuesta del sistema: es **material para escribir una
fila de `backend/catalogo_curvas.py` a mano**. El nombre de una curva no se
deriva del dato y nunca se va a derivar; lo que se puede derivar es donde
ponerlo y con cuanta evidencia. Un punto de acceso que devolviera «curvas del
circuito» invitaria a creer que el sistema las nombra.

QUE MIDE, Y POR QUE CADA COSA
-----------------------------
1. **Si la vuelta describe el circuito.** `cierre_m` es cuanto le falta al lazo
   para cerrar. Medido el 2026-09-12 sobre las dieciseis sesiones de la Pi, ese
   numero separa limpio: los circuitos con cierre chico declaran **tres**
   sectores y los de cierre grande declaran cuatro, cinco o seis. La Formula 1
   tiene tres. Son dos senales independientes diciendo lo mismo, y la segunda
   explica a la primera: cuando la vuelta no cierra, abarca pedazos de dos y
   `sector_index` cambia de mas.

2. **Que tramos se repiten entre vueltas.** Es la validacion que el proyecto ya
   declaraba para `analisis/curvas.py` y que en Silverstone no se pudo hacer,
   porque esa sesion tiene una sola vuelta completa. Un trompo produce un tramo
   de giro alto que aparece en una vuelta y en ninguna otra.

3. **Los dos anclajes posibles, juntos.** El apice de aceleracion lateral y el
   minimo de velocidad no caen en el mismo sitio, y la separacion entre ellos
   llega a doscientos metros. Cual usar es una decision con consecuencias, y
   para tomarla hay que ver los dos.

4. **El cruce contra el mapa de la FIA**, cuando se le pasan las declaraciones
   de sector. Es lo unico de esta salida que es **verificacion** y no medicion:
   compara el anclaje contra una posicion derivada de una fuente que no
   participo de medirlo.

COMO SE LO CORRE
----------------
    python3 scripts/medir_curvas_de_un_circuito.py \\
        --sesion f1_25:session:1758301748294876464 \\
        --api http://127.0.0.1:8080 \\
        --sector 2=6,110,antes --sector 3=14,50,despues

`--sector` se lee «el limite que abre el sector N esta a M metros antes/despues
de la curva C», que es como lo escribe el mapa.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analisis.curvas import (  # noqa: E402
    UMBRAL_LATERAL_G, derivar, tramos_de_una_vuelta,
)
from backend.catalogo_curvas import (  # noqa: E402
    DeclaracionDeSector, cobertura_de_la_vuelta, curva_declarada_en,
)

SENAL_LATERAL = "g_force_lateral"
SENAL_VELOCIDAD = "speed"

#: El tope que la ruta admite (`Query(ge=50, le=5000)`). Se pide el maximo
#: porque **si la API reduce, la deteccion parte los tramos distinto**: medido
#: sobre Spa el 2026-09-12, la misma vuelta da 39 tramos a 60 Hz, 35 a 20 Hz y
#: 29 a 10 Hz. Una vuelta de 60 Hz de mas de 83 s pasa las 5.000 muestras y se
#: reduce igual; por eso la respuesta trae `submuestreado` y aca se avisa. Sin
#: ese aviso, dos circuitos medidos con este guion podrian no ser comparables
#: sin que nada lo dijera.
PUNTOS_MAXIMOS = 5000

#: LA COMPROBACION ES DE PERTENENCIA, NO DE DISTANCIA, y esto es lo que se
#: aprendio midiendo tres circuitos.
#:
#: El mapa declara un **punto** y la deteccion encuentra un **intervalo**.
#: Preguntar a cuantos metros esta el punto del anclaje es la pregunta
#: equivocada: una curva de trescientos metros no tiene una posicion, y cual de
#: sus metros es «la curva» depende de una convencion que el mapa no publica.
#:
#: Medido el 2026-09-12, la distancia del punto declarado al apice: Silverstone
#: 6,7 y 11,8 m; Spielberg 0,7 y 30,5; Abu Dhabi 48,8 y 135,1. Con un umbral de
#: distancia, la mitad «falla» sin que el mapeo tenga nada malo.
#:
#: La pregunta buena ---si el punto cae DENTRO del tramo que se nombra con ese
#: numero--- da **6 de 6** sobre los mismos tres circuitos. Y es la que importa:
#: lo que se quiere comprobar es que la curva numerada X sea esta y no la de al
#: lado, no ubicarla al metro.
#:
#: Se conserva un margen chico para el punto que cae justo afuera por el
#: muestreo: a 250 km/h dos muestras consecutivas distan siete metros.
MARGEN_DE_PERTENENCIA_M = 15.0

#: Fraccion del circuito que una vuelta tiene que abarcar para servir de
#: anclaje. Es un criterio de cobertura y no de limpieza: una vuelta con entrada
#: a boxes describe el circuito igual.
COBERTURA_MINIMA = 0.95

#: A partir de aca el hueco se avisa. NO se rechaza la vuelta por el hueco, y
#: eso es deliberado: un hueco de 126 m en la recta de largada ---Austin--- no
#: esconde ninguna curva, y uno de 126 m en el medio se come una entera. La
#: diferencia esta en **donde** cae, que la herramienta no puede decidir sin el
#: catalogo que se esta tratando de escribir. Se declara y lo mira quien
#: escriba la fila. Rechazarlo por regla fue el error del primer censo.
HUECO_QUE_SE_AVISA_M = 40.0


def _pedir(api: str, ruta: str) -> dict:
    with urllib.request.urlopen(api.rstrip("/") + ruta, timeout=180) as r:
        return json.loads(r.read().decode("utf-8"))


def _serie(api: str, sesion: str, senal: str,
           vuelta: int) -> tuple[dict[float, float], bool]:
    """La serie y **si vino reducida**, que es lo que hace o no comparables dos
    mediciones de este guion."""

    d = _pedir(api, f"/sesiones/{sesion}/series?senales={senal}"
                    f"&vuelta={vuelta}&puntos={PUNTOS_MAXIMOS}")
    veh = d.get("vehiculos") or {}
    if not veh:
        return {}, False
    v = next(iter(veh.values()))
    return ({m: x for m, x in zip(v["distancia_m"], v[senal]) if x is not None},
            bool(d.get("submuestreado")))


def _declaracion(texto: str) -> tuple[int, DeclaracionDeSector]:
    """Lee «3=14,50,despues» como «el sector 3 abre 50 m despues de la curva 14»."""

    sector, resto = texto.split("=", 1)
    curva, metros, lado = resto.split(",")
    return int(sector), DeclaracionDeSector(
        curva=int(curva), metros=float(metros), lado=lado.strip())


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sesion", required=True)
    p.add_argument("--api", default="http://127.0.0.1:8000")
    p.add_argument("--sector", action="append", default=[],
                   help="N=curva,metros,antes|despues")
    args = p.parse_args()

    trazado = _pedir(args.api, f"/sesiones/{args.sesion}/trazado?puntos=600")
    vueltas = _pedir(args.api, f"/analisis/{args.sesion}/vueltas").get("vueltas") or []
    # QUE VUELTAS SE USAN, Y POR QUE NO SE LE PREGUNTA A «VUELTAS LIMPIAS».
    #
    # Ese filtro decide si el **tiempo** de una vuelta es comparable con otro, y
    # descarta por entrada a boxes o por no haber presenciado el comienzo. Aca
    # la pregunta es otra: si la vuelta **cubre el circuito**. Preguntando lo
    # primero para decidir lo segundo, el censo del 2026-09-12 descarto siete de
    # once circuitos, entre ellos uno cuyas dos vueltas cubren el 99,8 %.
    #
    # El numero de vuelta se lee del registro y no se cuenta por posicion.
    candidatas = [int(v["numero"]) for v in vueltas if v.get("numero") is not None]

    print(f"== {args.sesion}")
    print(f"   largo medido      {trazado.get('largo_m')} m")
    print(f"   desnivel          {trazado.get('desnivel_m')} m")
    print(f"   cierre del lazo   {trazado.get('cierre_m')} m"
          f"{'   <-- la vuelta no cierra' if (trazado.get('cierre_m') or 0) > 20 else ''}")
    sectores = trazado.get("sectores") or []
    print(f"   sectores medidos  {len(sectores)}"
          f"{'   <-- deberian ser tres' if len(sectores) != 3 else ''}")
    for s in sectores:
        print(f"       sector {s['sector']} abre en {s['desde_m']} m")
    largo = trazado.get("largo_m") or 0.0
    completas, coberturas = [], {}
    for n in candidatas:
        lat, reducida = _serie(args.api, args.sesion, SENAL_LATERAL, n)
        if not lat:
            continue
        c = cobertura_de_la_vuelta(lat.keys(), largo) if largo else None
        coberturas[n] = (c, lat, reducida)
        if c and c.fraccion >= COBERTURA_MINIMA:
            completas.append(n)

    print(f"\n   cobertura de cada vuelta (minima {100 * COBERTURA_MINIMA:.0f} %):")
    for n, (c, lat, _) in sorted(coberturas.items()):
        if c is None:
            continue
        aviso = ""
        if c.hueco_mayor_m >= HUECO_QUE_SE_AVISA_M:
            donde = ("al principio" if c.desde_m >= c.hueco_mayor_m - 0.5
                     else "al final" if largo - c.hasta_m >= c.hueco_mayor_m - 0.5
                     else "EN EL MEDIO")
            aviso = f"  hueco de {c.hueco_mayor_m:.0f} m {donde}"
        print(f"       vuelta {n:>3}: {100 * c.fraccion:5.1f} %  de {c.desde_m:7.1f} "
              f"a {c.hasta_m:7.1f} m"
              f"{'   sirve' if c.fraccion >= COBERTURA_MINIMA else '          '}"
              f"{aviso}")
    if not completas:
        print("   ninguna vuelta cubre el circuito: no hay nada que anclar.")
        return 1

    # Los tramos de cada vuelta, y cuales se repiten.
    por_vuelta, reducidas = [], 0
    for n in completas:
        _c, lat, reducida = coberturas[n]
        reducidas += reducida
        # Solo el tramo de la vuelta: el simulador publica metros negativos
        # antes de la linea de largada y esos son de la vuelta de formacion.
        dentro = sorted((m, x) for m, x in lat.items() if 0.0 <= m <= largo)
        if len(dentro) > 1:
            por_vuelta.append(dentro)
    if reducidas:
        print(f"\n   AVISO: {reducidas} de {len(completas)} vueltas vinieron "
              f"reducidas por la API. La deteccion parte los tramos distinto "
              f"segun la densidad, asi que esta medicion no es comparable con "
              f"otra que no se haya reducido.")
    print(f"\n   deteccion a {UMBRAL_LATERAL_G} g, por vuelta: "
          f"{[len(tramos_de_una_vuelta(v)) for v in por_vuelta]}")

    catalogo = derivar(por_vuelta, circuito=args.sesion)
    print(f"   tramos que se repiten en la mayoria: {len(catalogo.curvas)} "
          f"(sobre {catalogo.vueltas_usadas} vueltas)")

    vel, _ = _serie(args.api, args.sesion, SENAL_VELOCIDAD, completas[0])
    print(f"\n{'#':>3} {'ap.lateral':>11} {'ap.velocidad':>13} {'sep':>7} "
          f"{'v_min':>6} {'sentido':>10} {'vueltas':>8}")
    for c in catalogo.curvas:
        dentro = [(m, v) for m, v in vel.items() if c.desde_m <= m <= c.hasta_m]
        mv, vmin = min(dentro, key=lambda x: x[1]) if dentro else (float("nan"),) * 2
        # El signo esta verificado: negativo es derecha. Ver `analisis/curvas.py`.
        print(f"{c.numero:>3} {c.apice_m:>11.1f} {mv:>13.1f} {mv - c.apice_m:>7.1f} "
              f"{vmin:>6.0f} {'derecha' if c.pico_g < 0 else 'izquierda':>10} "
              f"{c.vueltas_en_que_aparece:>4}/{c.vueltas_examinadas}")

    # La comprobacion, si hay con que hacerla.
    por_sector = {s["sector"]: s["desde_m"] for s in sectores if s.get("desde_m")}
    if args.sector:
        print("\n   contra el mapa de la FIA:")
    fallas = 0
    for texto in args.sector:
        sector, decl = _declaracion(texto)
        limite = por_sector.get(sector)
        if limite is None:
            print(f"       sector {sector}: no esta medido en esta vuelta")
            fallas += 1
            continue
        esperado = curva_declarada_en(decl, limite)
        dentro = [c for c in catalogo.curvas
                  if c.desde_m - MARGEN_DE_PERTENENCIA_M <= esperado
                  <= c.hasta_m + MARGEN_DE_PERTENENCIA_M]
        if len(dentro) == 1:
            c = dentro[0]
            print(f"       curva {decl.curva}: el mapa la pone en {esperado:.1f} m "
                  f"y cae dentro del tramo {c.desde_m:.0f}-{c.hasta_m:.0f} m "
                  f"(curva {c.numero}, apice {c.apice_m:.0f}) -- ok")
        elif not dentro:
            cer = min(catalogo.curvas,
                      key=lambda c: min(abs(c.desde_m - esperado),
                                        abs(c.hasta_m - esperado)))
            fallas += 1
            print(f"       curva {decl.curva}: el mapa la pone en {esperado:.1f} m "
                  f"y NO cae en ningun tramo; el mas cercano es "
                  f"{cer.desde_m:.0f}-{cer.hasta_m:.0f} m -- NO COINCIDE")
        else:
            # Dos tramos reclamando el mismo metro es un catalogo que no ubica.
            fallas += 1
            print(f"       curva {decl.curva}: el mapa la pone en {esperado:.1f} m "
                  f"y cae en {len(dentro)} tramos a la vez -- AMBIGUO")
    return 1 if fallas else 0


if __name__ == "__main__":
    raise SystemExit(main())
