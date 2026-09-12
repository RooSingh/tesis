# -*- coding: utf-8 -*-
"""Deriva el catalogo de curvas de un circuito a partir de vueltas ya capturadas.

**Por que se deriva y no se escribe.** Una anotacion que dice "metro 812" obliga a
quien la lee a saber donde queda el metro 812. Una que dice "curva 4" se entiende
sola. Para decir "curva 4" hace falta saber donde estan las curvas, y hay dos
formas de saberlo:

* **escribir el trazado a mano**, que es transcribir un documento externo. Este
  trabajo ya cometio dos veces el mismo error de esa familia —la tabla de tipos
  de sesion y la de superficies, ambas escritas de memoria y ambas corridas— y no
  hay motivo para creer que la tercera saldria bien;

* **derivarlo del dato**, que es lo que hace este modulo. Una curva es donde el
  vehiculo sostiene aceleracion lateral, y eso el canal lo declara.

**Como se valida.** No contra el numero oficial de curvas, que seria volver a
depender de un documento externo, sino **contra la repeticion**: si el metodo es
correcto, vueltas distintas del mismo circuito tienen que encontrar las curvas en
los mismos metros. Una curva que aparece en una sola vuelta no es una curva: es
un incidente de esa vuelta.

**Que numeracion es esta.** La que sale de recorrer el circuito desde la linea de
meta. **No es necesariamente la numeracion oficial del trazado**, y este modulo no
afirma que lo sea: dos curvas muy juntas que el trazado numera por separado
pueden aparecer aca como una sola, y una curva muy suave puede no aparecer. Se
declara asi en la salida para que nadie lea "curva 4" como una cita del circuito.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable

#: Aceleracion lateral por encima de la cual el vehiculo esta girando.
#:
#: Medida sobre las vueltas limpias de Hungaroring: la mediana del valor absoluto
#: en recta es de centesimas, y el percentil 95 por vuelta ronda los 3 g. Ocho
#: decimas separa el giro sostenido de la correccion de trayectoria en recta.
UMBRAL_LATERAL_G = 0.8

#: Cuanto puede bajar la aceleracion dentro de una misma curva sin que se la
#: considere terminada. Una curva larga tiene un tramo intermedio mas suave, y
#: cortarla ahi la contaria dos veces.
UNION_M = 45.0

#: Largo minimo para que un tramo sea una curva y no un golpe de volante.
MINIMO_M = 20.0

#: A que distancia dos apices de vueltas distintas son la misma curva.
#:
#: Es el ancho de la ventana de agrupamiento, y sale de lo observado: los apices
#: de una misma curva se repiten dentro de unas decenas de metros entre vueltas,
#: porque el trazado que se elige cambia poco.
TOLERANCIA_AGRUPAMIENTO_M = 60.0

#: En que fraccion de las vueltas tiene que aparecer un tramo para ser una curva.
#:
#: Es el criterio que separa una curva de un incidente. En la captura sin control
#: de traccion, las vueltas con trompos producen tramos de aceleracion lateral
#: alta que no corresponden a ninguna curva: aparecen en una vuelta y en ninguna
#: otra. Exigir mayoria los elimina sin tener que saber cuales son.
FRACCION_MINIMA_DE_VUELTAS = 0.6

#: Cuanto tienen que compartir dos tramos de vueltas distintas para ser la misma
#: curva, como fraccion del mas corto de los dos. No es un umbral de distancia:
#: es una proporcion, y por eso no hay que elegirla distinta para un circuito de
#: curvas largas y otro de curvas cortas.
FRACCION_DE_SOLAPE = 0.5


@dataclass
class Curva:
    """Una curva del circuito, tal como el dato la declara."""

    numero: int
    apice_m: float
    desde_m: float
    hasta_m: float
    #: Positivo o negativo segun el sentido del giro. Se conserva el signo del
    #: pico y no se lo traduce aca, porque este modulo es una funcion pura sobre
    #: pares de numeros y la traduccion depende de la fuente.
    #:
    #: LA RELACION CON EL SENTIDO REAL YA ESTA VERIFICADA, para `g_force_lateral`
    #: de F1 25: **negativo es derecha**. Estuvo sin verificar hasta el
    #: 2026-09-12, y se comprobo contra casos cuyo sentido publica una fuente
    #: externa, no por inspeccion del dibujo:
    #:
    #: - La Source, horquilla a derecha, da -1,70 a 399,7 m, contra los 405 m
    #:   donde `catalogo_curvas` la ancla;
    #: - The Loop, horquilla a izquierda, da positivo, con un minimo medido de
    #:   87 km/h contra los «unos 90 km/h, la curva mas lenta del trazado» que
    #:   publica la nota oficial del campeonato;
    #: - Eau Rouge, cuya primera mitad es a izquierda, da positivo.
    #:
    #: Tres casos, dos sentidos, y coinciden los tres. Quien traduzca el signo
    #: ---`catalogo_curvas`, el guion de medicion--- lo hace con esto escrito.
    pico_g: float
    #: En cuantas de las vueltas usadas aparecio. Es la evidencia de que es una
    #: curva y no un incidente, y viaja con ella.
    vueltas_en_que_aparece: int
    vueltas_examinadas: int

    def contiene(self, metro: float) -> bool:
        return self.desde_m <= metro <= self.hasta_m

    def __str__(self) -> str:
        return f"curva {self.numero}"


@dataclass
class CatalogoDeCurvas:
    """Las curvas de un circuito, con la evidencia de como se obtuvieron."""

    circuito: str
    curvas: list[Curva] = field(default_factory=list)
    vueltas_usadas: int = 0
    largo_vuelta_m: float = 0.0

    def ubicar(self, metro: float) -> str:
        """Donde queda un metro del circuito, en palabras.

        Devuelve la curva si el metro cae dentro de una, y si no, la relacion con
        la curva mas cercana. Nunca devuelve una cadena vacia: una anotacion sin
        lugar es peor que una con el lugar aproximado.
        """

        if not self.curvas:
            return f"metro {metro:,.0f}"

        for curva in self.curvas:
            if curva.contiene(metro):
                return f"curva {curva.numero}"

        anterior = [c for c in self.curvas if c.hasta_m < metro]
        siguiente = [c for c in self.curvas if c.desde_m > metro]
        if anterior and siguiente:
            a, s = anterior[-1], siguiente[0]
            # Se nombra la mas cercana de las dos, porque decir "entre la 3 y la
            # 4" en una recta de un kilometro no ubica nada.
            if metro - a.hasta_m <= s.desde_m - metro:
                return f"{metro - a.hasta_m:,.0f} m despues de la curva {a.numero}"
            return f"{s.desde_m - metro:,.0f} m antes de la curva {s.numero}"
        if siguiente:
            return f"{siguiente[0].desde_m - metro:,.0f} m antes de la curva {siguiente[0].numero}"
        return f"{metro - anterior[-1].hasta_m:,.0f} m despues de la curva {anterior[-1].numero}"


def _mediana(valores: list[float]) -> float:
    ordenados = sorted(valores)
    medio = len(ordenados) // 2
    if len(ordenados) % 2:
        return ordenados[medio]
    return (ordenados[medio - 1] + ordenados[medio]) / 2


def _separar_solapadas(curvas: list[Curva]) -> None:
    """Corta el solape entre dos curvas consecutivas por el punto medio.

    Aun con la mediana, dos curvas muy juntas pueden quedar superpuestas por unos
    metros. Se reparte la zona en disputa por la mitad: es arbitrario, y
    cualquier reparto lo es, pero **deja cada metro en una sola curva**, que es lo
    que hace utilizable al catalogo.
    """

    for anterior, siguiente in zip(curvas, curvas[1:]):
        if anterior.hasta_m <= siguiente.desde_m:
            continue
        medio = (anterior.apice_m + siguiente.apice_m) / 2
        anterior.hasta_m = min(anterior.hasta_m, medio)
        siguiente.desde_m = max(siguiente.desde_m, medio)


def tramos_de_una_vuelta(
    puntos: Iterable[tuple[float, float]],
    umbral: float = UMBRAL_LATERAL_G,
    union_m: float = UNION_M,
    minimo_m: float = MINIMO_M,
) -> list[dict]:
    """Los tramos de giro sostenido de una vuelta.

    `puntos` son pares (distancia recorrida, aceleracion lateral), ordenados.
    """

    tramos: list[dict] = []
    abierto: dict | None = None
    for distancia, lateral in puntos:
        if abs(lateral) <= umbral:
            continue
        mismo_sentido = abierto is not None and (lateral > 0) == (abierto["pico"] > 0)
        if abierto is not None and mismo_sentido \
                and distancia - abierto["hasta"] < union_m:
            abierto["hasta"] = distancia
            if abs(lateral) > abs(abierto["pico"]):
                abierto["pico"] = lateral
                abierto["apice"] = distancia
            continue
        if abierto is not None:
            tramos.append(abierto)
        abierto = {"desde": distancia, "hasta": distancia,
                   "apice": distancia, "pico": lateral}
    if abierto is not None:
        tramos.append(abierto)
    return [t for t in tramos if t["hasta"] - t["desde"] >= minimo_m]


def derivar(
    vueltas: list[list[tuple[float, float]]],
    circuito: str,
    tolerancia_m: float = TOLERANCIA_AGRUPAMIENTO_M,
    fraccion_minima: float = FRACCION_MINIMA_DE_VUELTAS,
) -> CatalogoDeCurvas:
    """Deriva el catalogo agrupando los tramos que se repiten entre vueltas.

    Cada vuelta es una lista de pares (distancia, aceleracion lateral). Se
    esperan vueltas limpias: una vuelta con un trompo aporta tramos de giro que
    no son curvas, y el criterio de mayoria existe justamente para descartarlos,
    pero si la mayoria de las vueltas tiene trompos el criterio deja de servir.
    """

    if not vueltas:
        return CatalogoDeCurvas(circuito=circuito)

    por_vuelta = [tramos_de_una_vuelta(v) for v in vueltas]

    # SE AGRUPA POR DONDE CAE EL TRAMO, NO POR DONDE ESTA SU MAXIMO.
    #
    # Antes se agrupaban los **apices** por cercania, con la tolerancia de
    # abajo. En una curva corta el pico de aceleracion lateral es agudo y cae
    # siempre en el mismo sitio, asi que funcionaba. En una larga la lateral es
    # casi constante durante cientos de metros, de modo que **cual de todas las
    # muestras resulta la maxima lo deciden el ruido y la linea que se manejo
    # esa vuelta**.
    #
    # Medido el 2026-09-12 sobre `f1_25:session:1535856705959104755`, la misma
    # curva de Yas Marina en cinco vueltas: empieza siempre alrededor del metro
    # 3.590 y termina siempre alrededor del 3.922, y su **apice se movio 163 m**.
    # Con 60 m de tolerancia eso eran dos grupos ---tres vueltas y dos--- y el
    # criterio de mayoria descartaba el segundo: el circuito quedaba con catorce
    # curvas de dieciseis.
    #
    # Dispersion entre vueltas del mismo tramo, mediana sobre todas las curvas:
    #
    #     circuito     apice   entrada   salida
    #     abu-dhabi    104 m     36 m      31 m
    #     spielberg     54 m     34 m      43 m
    #
    # Dos tramos son la misma curva si **se solapan**: ocupan metros en comun.
    # Eso no depende de donde cayo el maximo ni de cuanta tolerancia se elija.
    #
    # NO SE CAMBIO EL ANCLAJE, que fue lo primero que se penso. El apice sigue
    # siendo lo que se publica: contra el mapa de la FIA da 6,7 m y 11,8 m en
    # Silverstone, y la entrada da 49,2 m y 70,3 m. Lo que estaba mal no era
    # donde se ancla sino como se agrupa.
    marcas: list[tuple[float, int, dict]] = sorted(
        (t["desde"], i, t)
        for i, tramos in enumerate(por_vuelta) for t in tramos
    )

    # EL SOLAPE TIENE QUE SER REAL Y PROPORCIONAL, NO «ESTAR CERCA».
    #
    # El primer intento unia un tramo al grupo si empezaba antes del final del
    # grupo mas la tolerancia. Eso **encadena**: cada tramo que entra estira el
    # final del grupo, el grupo alcanza al siguiente, y una vuelta entera
    # termina en cinco o seis curvas. Se vio sobre los tres circuitos medidos
    # ---Silverstone paso de 17 a 6--- y no lo agarro la prueba unitaria, que
    # usaba curvas separadas trescientos metros.
    #
    # Dos tramos son la misma curva cuando comparten **la mitad del mas corto**.
    # Asi, un tramo que se estira unos metros sobre el siguiente ---lo que pasa
    # en las vueltas donde dos curvas se toman sin levantar--- no los funde.
    def _mismo(a: dict, b: dict) -> bool:
        comun = min(a["hasta"], b["hasta"]) - max(a["desde"], b["desde"])
        if comun <= 0:
            return False
        corto = min(a["hasta"] - a["desde"], b["hasta"] - b["desde"])
        return corto <= 0 or comun >= corto * FRACCION_DE_SOLAPE

    grupos: list[list[tuple[float, int, dict]]] = []
    for marca in marcas:
        # Se compara contra el tramo **representativo** del grupo ---la mediana
        # de sus bordes--- y no contra el ultimo que entro ni contra la
        # envolvente: lo primero hace que el orden decida, y lo segundo vuelve a
        # encadenar en cuanto una vuelta trae un tramo largo de mas.
        if grupos:
            miembros = [t for _, _, t in grupos[-1]]
            representativo = {"desde": _mediana([t["desde"] for t in miembros]),
                              "hasta": _mediana([t["hasta"] for t in miembros])}
            if _mismo(representativo, marca[2]):
                grupos[-1].append(marca)
                continue
        grupos.append([marca])

    # Se redondea **hacia arriba**, no al mas cercano.
    #
    # Con `round`, dos vueltas daban 1,2 -> 1, y la mayoria dejaba de ser
    # mayoria: bastaba que un tramo apareciera en una sola de las dos. Sobre las
    # vueltas limpias de Hungaroring eso producia dieciocho curvas donde con tres
    # vueltas salian catorce, y las cuatro de mas eran ruido de una sola vuelta.
    minimo_vueltas = max(1, math.ceil(len(vueltas) * fraccion_minima))
    curvas: list[Curva] = []
    for grupo in grupos:
        vueltas_presentes = {i for _, i, _ in grupo}
        if len(vueltas_presentes) < minimo_vueltas:
            continue
        tramos = [t for _, _, t in grupo]
        pico = max(tramos, key=lambda t: abs(t["pico"]))["pico"]
        curvas.append(Curva(
            numero=0,
            apice_m=sum(t["apice"] for t in tramos) / len(tramos),
            # Los bordes se toman como la **mediana** de las vueltas y no como la
            # envolvente.
            #
            # La envolvente parecia mas segura —una anotacion cerca del borde
            # cae adentro y no se queda afuera por un metro— y producia un
            # defecto peor: en las vueltas donde dos curvas seguidas se toman sin
            # levantar, el tramo de una se extiende sobre la otra, y la
            # envolvente hacia que **dos curvas ocuparan los mismos metros**. Un
            # catalogo donde el metro 600 pertenece a la curva 1 y a la 2 a la
            # vez no ubica nada.
            desde_m=_mediana([t["desde"] for t in tramos]),
            hasta_m=_mediana([t["hasta"] for t in tramos]),
            pico_g=pico,
            vueltas_en_que_aparece=len(vueltas_presentes),
            vueltas_examinadas=len(vueltas),
        ))

    curvas.sort(key=lambda c: c.apice_m)
    _separar_solapadas(curvas)
    for numero, curva in enumerate(curvas, start=1):
        curva.numero = numero

    largo = max((max(d for d, _ in v) for v in vueltas if v), default=0.0)
    return CatalogoDeCurvas(circuito=circuito, curvas=curvas,
                            vueltas_usadas=len(vueltas), largo_vuelta_m=largo)
