# -*- coding: utf-8 -*-
"""Nombres de curva declarados como dato externo, no medido.

POR QUE ESTE MODULO EXISTE APARTE
---------------------------------
`backend/analisis/curvas.py` **deriva** las curvas del dato: una curva es donde el vehiculo
sostiene aceleracion lateral, y el canal lo declara. Ese modulo produce curvas
numeradas desde la linea de meta y advierte explicitamente que esa numeracion no
es necesariamente la oficial del trazado.

Lo que ese modulo no puede producir es el **nombre**. "La Source" no esta en
ningun canal: es un dato cultural del circuito que solo puede venir de una
publicacion externa. Este modulo lo trae, separado, y marcado con su origen, por
la misma razon por la que `backend/track_reference.py` mantiene aparte las
longitudes de circuito: para que la distincion entre medicion y anotacion quede
inscripta en la estructura y no solo en un comentario.

QUE PUEDE Y QUE NO PUEDE AFIRMARSE CON ESTO
-------------------------------------------
- **Se puede** rotular un tramo de la vuelta con el nombre por el que se lo conoce,
  declarando que el nombre es anotacion.
- **No se puede** usar este catalogo para afirmar cuantas curvas tiene el circuito,
  ni para validar la deteccion de `curvas.py`. Validar la medicion contra un
  documento externo seria cambiar el patron de medida por el que se quiere
  comprobar. `analisis/curvas.py` se valida contra la repeticion entre vueltas, y eso no
  cambia.

DOS NUMERACIONES QUE NO COINCIDEN, Y ESTA BIEN QUE NO COINCIDAN
---------------------------------------------------------------
El operador del circuito publica **doce zonas con nombre**. La convencion de
cronometraje deportivo cuenta **diecinueve curvas numeradas**, porque desdobla en
dos las dobles ---Raidillon, Les Combes, Pouhon, Fagnes, Blanchimont y la
chicana--- y numera algunas que el operador no nombra.

La deteccion sobre el dato encuentra **quince zonas de frenada** en la vuelta
medida, que es un tercer recuento y tambien es correcto: Kemmel es recta y no
frena, y Malmedy hoy se pasa sin levantar. Los tres recuentos describen cosas
distintas ---zonas con nombre, curvas numeradas y frenadas efectivas--- y el
catalogo declara los tres en vez de forzar uno.

ANCLAJE
-------
Cada entrada lleva el metro de la vuelta donde la deteccion encontro el minimo de
velocidad. **Ese metro es medido**; el nombre que se le adosa es la interpretacion
de este modulo, y `origen` lo dice en cada fila.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Curva:
    """Una zona del circuito con su nombre externo y su anclaje medido."""

    #: Orden de aparicion desde la linea de meta.
    orden: int
    #: Nombre publicado por el operador del circuito.
    nombre: str
    #: Numeros que la convencion de cronometraje deportivo asigna a esta zona.
    numeros_cronometraje: tuple[int, ...]
    #: Metro de la vuelta donde la deteccion encontro el minimo de velocidad.
    #: Medido sobre `f1_25:session:3731090176871608020`, vuelta lanzada completa.
    metro_medido: float
    #: Velocidad minima observada en ese punto, en km/h.
    velocidad_minima_kmh: int
    #: De donde sale cada mitad del dato.
    origen: str = "nombre: catalogo externo citado; metro: medido sobre la vuelta"
    #: CON QUE MEDICION ESTA ANCLADA ESTA FILA. No es decoracion: `metro_medido`
    #: significa cosas distintas segun cual sea, y dos circuitos del mismo
    #: catalogo no coinciden. Ver `ANCLAJES`.
    anclaje: str = "minimo de velocidad"
    #: Hacia donde gira, cuando se midio. Cadena vacia significa no medido, que
    #: es distinto de recto.
    sentido: str = ""


#: LOS DOS ANCLAJES QUE ESTE CATALOGO ADMITE, Y POR QUE HAY DOS.
#:
#: El minimo de velocidad fue el primero, y es el que sostiene a Spa. El apice
#: de aceleracion lateral entro con Silverstone, donde se lo pudo comparar:
#: contra las dos curvas cuya posicion declara el mapa de la FIA, el apice
#: lateral cae a 6,7 m y 11,8 m, y el minimo de velocidad a 74,8 m y 70,3 m.
#:
#: Tiene sentido fisico y conviene dejarlo escrito: la curva esta donde el auto
#: mas gira. El minimo de velocidad cae en algun punto entre el final de la
#: frenada y el comienzo de la traccion, y donde cae depende de como se maneje.
#:
#: Spa no se re-anclo en este trabajo. Re-medirlo cambiaria quince filas que hoy
#: sostienen el tablero, y hacerlo de paso ---sin volver a comprobar cada una---
#: seria cambiar el patron de medida sin querer. Queda declarado y pendiente.
ANCLAJES: frozenset[str] = frozenset({
    "minimo de velocidad",
    "apice de aceleracion lateral",
})


#: Longitud declarada por el operador y por la ficha del campeonato, en metros.
#: La vuelta medida dio 7.006,5 m, una diferencia de 2,5 m sobre 7.004.
SPA_LARGO_DECLARADO_M = 7004.0

#: Desnivel declarado, en metros. La vuelta medida dio 102,2 m: coincide.
SPA_DESNIVEL_DECLARADO_M = 102.2

#: Sentido de giro declarado. Se usa para orientar la proyeccion del trazado:
#: un circuito horario tiene que verse horario en pantalla.
SPA_SENTIDO = "horario"

#: Spa-Francorchamps, trazado de Gran Premio.
#:
#: Nombres: pagina del operador del circuito y articulo oficial del campeonato.
#: Numeracion de cronometraje: ficha del circuito.
#: Metros: medidos, ver el encabezado del modulo.
SPA_FRANCORCHAMPS: tuple[Curva, ...] = (
    Curva(1, "La Source", (1,), 405.0, 55),
    Curva(2, "Eau Rouge / Raidillon", (2, 3, 4), 1333.0, 222),
    Curva(3, "Les Combes", (5,), 2526.0, 114),
    Curva(4, "Les Combes", (6,), 2666.0, 147),
    Curva(5, "Bruxelles", (8,), 3065.0, 98),
    Curva(6, "Speaker Corner", (9,), 3338.0, 124),
    Curva(7, "Pouhon", (10,), 3884.0, 180),
    Curva(8, "Pouhon", (11,), 4109.0, 212),
    Curva(9, "Fagnes", (12,), 4530.0, 122),
    Curva(10, "Fagnes", (13,), 4703.0, 142),
    Curva(11, "Campus", (14,), 4985.0, 120),
    Curva(12, "Paul Frere", (15,), 5216.0, 185),
    Curva(13, "Blanchimont", (16, 17), 6256.0, 277),
    Curva(14, "Chicana", (18,), 6782.0, 50),
    Curva(15, "Chicana", (19,), 6920.0, 78),
)

#: Zona con nombre que el catalogo declara y la deteccion no encuentra, porque
#: no hay frenada: Kemmel es recta, y Malmedy hoy se toma sin levantar. Se
#: registra para que la ausencia sea explicita y no parezca un olvido.
SPA_SIN_FRENADA: tuple[str, ...] = ("Kemmel", "Malmedy")

@dataclass(frozen=True)
class Cobertura:
    """Cuanto del circuito abarca una vuelta, y donde le falta."""

    #: Fraccion del largo que las muestras abarcan, entre 0 y 1.
    fraccion: float
    #: El hueco mas grande sin muestras, en metros. Es la medida que decide:
    #: una vuelta puede cubrir el 80 % y perderse cuatro curvas seguidas.
    hueco_mayor_m: float
    #: Primer y ultimo metro con muestra.
    desde_m: float
    hasta_m: float


def cobertura_de_la_vuelta(metros: Iterable[float], largo_m: float) -> Cobertura:
    """Si una vuelta sirve para anclar curvas, que **no** es si su tiempo sirve.

    POR QUE ESTA FUNCION EXISTE, Y ES UNA CORRECCION. El primer censo de
    circuitos descarto siete de once preguntandole a `analisis/vueltas` cuales
    eran «limpias». Ese filtro decide si el **tiempo** de una vuelta es
    comparable con otro y descarta por entrada a boxes o por no haber
    presenciado el comienzo; una vuelta con entrada a boxes puede describir el
    circuito perfectamente. Austin quedo afuera con dos vueltas que entre las
    dos cubren el 99,8 % del trazado.

    Peor: el segundo sintoma que parecia confirmarlo ---circuitos declarando
    cuatro, cinco o seis sectores donde la Formula 1 tiene tres--- salia de la
    **misma** mala eleccion de vuelta. Pedido por vuelta, todos declaran tres.
    No eran dos senales independientes coincidiendo: era una contada dos veces.

    EL HUECO MAYOR, Y NO SOLO LA FRACCION. Una vuelta a la que le falta un
    kilometro del medio y otra que empieza un kilometro tarde cubren lo mismo y
    no valen lo mismo: la primera se pierde las curvas que estan justo ahi.

    Las distancias negativas se descartan: el simulador las usa antes de la
    linea de largada ---Monaco trae desde -3.573 m, que es la vuelta de
    formacion--- y sumarlas daria una cobertura del 206 %.
    """

    if largo_m <= 0:
        raise ValueError(
            f"largo_m={largo_m}: una cobertura es una fraccion de algo, y de un "
            f"circuito de cero metros no se puede calcular ninguna.")

    dentro = sorted(m for m in metros if 0.0 <= m <= largo_m)
    if not dentro:
        return Cobertura(fraccion=0.0, hueco_mayor_m=largo_m,
                         desde_m=0.0, hasta_m=0.0)

    # El hueco de la largada y el de la meta cuentan igual que los del medio:
    # una curva en el metro 50 se pierde lo mismo si la captura arranco en 120.
    hueco = max(
        [dentro[0], largo_m - dentro[-1]]
        + [b - a for a, b in zip(dentro, dentro[1:])]
    )
    return Cobertura(
        fraccion=(dentro[-1] - dentro[0]) / largo_m,
        hueco_mayor_m=hueco,
        desde_m=dentro[0],
        hasta_m=dentro[-1],
    )


@dataclass(frozen=True)
class DeclaracionDeSector:
    """«El limite de sector esta a N metros antes/despues de la curva C».

    POR QUE ESTO ES UTIL, Y ES LA PARTE QUE SE PUEDE REUSAR. El mapa de
    circuito de la FIA **no publica el metro de ninguna curva**, asi que no
    sirve para anclar. Pero publica los limites de sector dichos en curvas, y
    los limites de sector **si estan medidos** en el dato: el paquete de vuelta
    del simulador declara `sector_index` en cada muestra.

    Cruzando las dos cosas se obtiene la posicion de una curva numerada **sin
    usar el catalogo**, que es exactamente lo que hace falta para comprobarlo.
    Es una fuente independiente y gratuita: ya estaba publicada y ya estaba
    medida, solo que nadie las habia puesto una al lado de la otra.

    Sirve para cualquier circuito cuyo mapa diga los sectores asi.
    """

    #: Numero de curva en la convencion de cronometraje, la del mapa.
    curva: int
    #: Distancia entre el limite de sector y la curva.
    metros: float
    #: De que lado del limite cae la curva. "antes" significa que el limite
    #: esta antes de la curva ---«sector 1, 110 m antes de la curva 6»--- y
    #: entonces la curva esta mas adelante.
    lado: str


#: Los lados que una declaracion admite. Cualquier otra cosa es una lectura
#: dudosa del mapa y se rechaza en vez de resolverse por omision.
LADOS: frozenset[str] = frozenset({"antes", "despues"})


def curva_declarada_en(declaracion: DeclaracionDeSector, limite_medido_m: float) -> float:
    """Donde queda esa curva, segun el mapa y el limite medido.

    No usa el catalogo: ese es el punto. El numero que devuelve se compara
    contra el anclaje del catalogo, y esa comparacion es la comprobacion.
    """

    if declaracion.lado not in LADOS:
        raise ValueError(
            f"lado {declaracion.lado!r}: una declaracion de sector dice «antes» "
            f"o «despues» de la curva. Resolverlo por omision convertiria una "
            f"lectura dudosa del mapa en un numero con dos decimales.")
    if declaracion.lado == "antes":
        return limite_medido_m + declaracion.metros
    return limite_medido_m - declaracion.metros


#: Atajo local: la cadena del anclaje se repite quince veces y escribirla a
#: mano quince veces es quince oportunidades de escribirla distinto.
_LAT = "apice de aceleracion lateral"

#: Longitud de linea central declarada por el mapa de circuito de la FIA del
#: Gran Premio 2025, en metros. La misma cifra publica formula1.com.
SILVERSTONE_LARGO_DECLARADO_M = 5891.0

#: Lo que dio la vuelta medida. 3,4 m de diferencia sobre 5.891, del mismo orden
#: que Spa (2,5 m sobre 7.004). Se guardan los dos numeros porque son dos cosas:
#: uno es la cita, el otro es lo que midio esta sesion.
SILVERSTONE_LARGO_MEDIDO_M = 5887.6

#: Desnivel medido en la misma vuelta, en metros. Silverstone es llano y esto lo
#: dice: Spa, en la misma unidad, da 102,2.
SILVERSTONE_DESNIVEL_MEDIDO_M = 11.5

#: Sentido de giro declarado.
SILVERSTONE_SENTIDO = "horario"

#: Silverstone, trazado de Gran Premio.
#:
#: NOMBRES: nota oficial del campeonato «How every Silverstone corner got its
#: name», que ademas numera las zonas. NUMERACION: mapa de circuito de la FIA
#: del Gran Premio 2025, que numera de 1 a 18.
#:
#: METROS: apice de aceleracion lateral, medidos sobre
#: `f1_25:session:1758301748294876464`, vuelta 2 ---la unica completa de las
#: tres que tiene la sesion---, con `curvas.tramos_de_una_vuelta` a 0,8 g.
#:
#: COMO SE COMPROBO EL MAPEO, QUE ES LO QUE LO HACE DEFENDIBLE. El mapa de la
#: FIA no publica los metros de las curvas, pero declara dos limites de sector
#: **dichos en curvas**: el sector 1 termina 110 m antes de la curva 6 y el
#: sector 2, 50 m despues de la curva 14. Los limites de sector de esta vuelta
#: estan medidos aparte, por `sector_index`, en 1.815,2 m y 4.294,6 m. Cruzando
#: las dos cosas la curva 6 cae en 1.925,2 m y la 14 en 4.244,6 m, **sin usar
#: este catalogo**; los apices medidos dan 1.918,5 m y 4.256,4 m. Dos puntos
#: independientes, uno en cada mitad del trazado, a 6,7 m y 11,8 m.
#:
#: Y las cuentas cierran: diecisiete tramos detectados menos los dos de la recta
#: Hangar que no son curva son quince, y dieciocho curvas numeradas menos las
#: tres fusiones de vecinas del mismo sentido tambien son quince.
#:
#: LO QUE NO SE PUDO COMPROBAR. El sentido de giro de cada zona esta medido
#: ---la senal lo declara--- pero **ninguna de las dos publicaciones oficiales
#: consultadas lista el sentido curva por curva**, asi que el sentido no sirvio
#: para verificar el mapeo: se guarda como medicion, no como comprobacion.
SILVERSTONE: tuple[Curva, ...] = (
    Curva(1, "Abbey", (1,), 372.0, 264, anclaje=_LAT, sentido="derecha"),
    Curva(2, "Farm Curve", (2,), 663.4, 271, anclaje=_LAT, sentido="izquierda"),
    Curva(3, "Village", (3,), 923.5, 103, anclaje=_LAT, sentido="derecha"),
    # The Loop y Aintree giran las dos a izquierda y estan pegadas: la deteccion
    # las da como un solo tramo de 348 m. El minimo de velocidad de ese tramo
    # ---87 km/h--- cae en The Loop, y la nota oficial dice que se toma «a unos
    # 90 km/h, la curva mas lenta del trazado». Coincide.
    Curva(4, "The Loop / Aintree", (4, 5), 1280.3, 87, anclaje=_LAT, sentido="izquierda"),
    Curva(5, "Brooklands", (6,), 1918.5, 136, anclaje=_LAT, sentido="izquierda"),
    # Luffield y Woodcote, las dos a derecha y pegadas: un tramo de 611,5 m.
    Curva(6, "Luffield / Woodcote", (7, 8), 2226.0, 101, anclaje=_LAT, sentido="derecha"),
    Curva(7, "Copse", (9,), 3067.3, 264, anclaje=_LAT, sentido="derecha"),
    Curva(8, "Maggotts", (10,), 3605.4, 299, anclaje=_LAT, sentido="izquierda"),
    Curva(9, "Becketts", (11,), 3740.1, 261, anclaje=_LAT, sentido="derecha"),
    Curva(10, "Becketts", (12,), 3908.0, 233, anclaje=_LAT, sentido="izquierda"),
    Curva(11, "Becketts", (13,), 3996.5, 169, anclaje=_LAT, sentido="derecha"),
    Curva(12, "Chapel", (14,), 4256.4, 210, anclaje=_LAT, sentido="izquierda"),
    Curva(13, "Stowe", (15,), 4972.1, 184, anclaje=_LAT, sentido="derecha"),
    Curva(14, "Vale", (16,), 5545.2, 92, anclaje=_LAT, sentido="izquierda"),
    # Club se numera 17 y 18 y se toma como una sola curva larga a derecha: un
    # tramo de 291,5 m.
    Curva(15, "Club", (17, 18), 5770.6, 107, anclaje=_LAT, sentido="derecha"),
)

#: LO QUE EL MAPA DE LA FIA DECLARA, GUARDADO para poder volver a comprobar.
#: Mapa de circuito del Gran Premio de Gran Bretana 2025, version 2.
#: Los limites medidos de esta vuelta son 1.815,2 m y 4.294,6 m; cruzados con
#: esto dan 1.925,2 m y 4.244,6 m, contra los 1.918,5 m y 4.256,4 m del
#: catalogo. Ver `tests/test_catalogo_curvas.py`.
SILVERSTONE_SECTORES_FIA: tuple[DeclaracionDeSector, ...] = (
    DeclaracionDeSector(curva=6, metros=110.0, lado="antes"),
    DeclaracionDeSector(curva=14, metros=50.0, lado="despues"),
)

#: DOS TRAMOS QUE LA DETECCION ENCUENTRA Y ESTE CATALOGO NO NOMBRA.
#:
#: Estan en la recta Hangar, entre la curva 14 y la 15, y son de 21,9 m y
#: 26,6 m. El mapa de la FIA no numera ninguna curva ahi ---lo unico que marca
#: en ese tramo es la trampa de velocidad, 140 m antes de la curva 15--- y el
#: auto pasa a 315 y 318 km/h.
#:
#: Se declaran, con su metro y su velocidad, por la misma razon que
#: `SPA_SIN_FRENADA`: que la ausencia sea explicita. Sin esto, quince nombres
#: para diecisiete detecciones se lee como dos nombres perdidos.
SILVERSTONE_SIN_NOMBRE: tuple[tuple[float, int], ...] = (
    (4554.4, 315),
    (4594.1, 318),
)

# --------------------------------------------------------------------------
# Spielberg -- Red Bull Ring
# --------------------------------------------------------------------------

#: Longitud de linea central declarada por el mapa de circuito de la FIA del
#: Gran Premio de Austria 2025 ---«Circuit Centreline Length = 4.326 km»--- y
#: por la pagina del operador.
SPIELBERG_LARGO_DECLARADO_M = 4326.0

#: Lo que dio la vuelta medida: 3,8 m de diferencia sobre 4.326, del mismo orden
#: que Silverstone (3,4 m) y Spa (2,5 m). El lazo cierra en 1,89 m.
SPIELBERG_LARGO_MEDIDO_M = 4322.2

#: Desnivel que declara el operador: «the height difference is 65m».
SPIELBERG_DESNIVEL_DECLARADO_M = 65.0

#: Lo que dio la misma vuelta. Se guarda aparte por la misma razon que el largo:
#: uno es la cita y el otro es la medicion.
#:
#: (Silverstone no tiene declarado: su ficha lleva el desnivel MEDIDO en el
#: campo que dice «declarado». Queda anotado como deuda; corregirlo de paso,
#: sin volver a comprobar las dos fichas que hoy sostienen la pantalla, es
#: exactamente la clase de arreglo al voleo que este modulo evita.)
SPIELBERG_DESNIVEL_MEDIDO_M = 63.7

#: SENTIDO MEDIDO, NO DECLARADO, y es el primer circuito del catalogo donde hay
#: que decirlo asi.
#:
#: Ni el mapa de la FIA, ni la pagina del operador, ni la guia de circuito del
#: campeonato publican si Spielberg se corre horario o antihorario. Spa lo tiene
#: declarado y Silverstone tambien; aca no habia a quien citar, y copiar el
#: sentido del circuito vecino habria sido inventarlo.
#:
#: Se midio: una vuelta cerrada es exactamente una revolucion, y el giro
#: acumulado ---la integral de la aceleracion lateral sobre el cuadrado de la
#: velocidad--- tiene el signo de esa revolucion. `analisis/curvas` fija que
#: negativo es derecha.
#:
#: Calibrado contra un circuito de sentido establecido: Silverstone da
#: -363,2 grados, una vuelta entera a derecha con 0,9 % de error. Spielberg da
#: -390,2 y -403,3 sobre dos vueltas distintas. Mismo signo, y el control cae
#: donde tiene que caer.
SPIELBERG_SENTIDO = "horario"

#: Spielberg, Red Bull Ring, trazado de Gran Premio.
#:
#: NOMBRES: pagina de circuito del operador, **tal como estaba en junio de
#: 2025**. La fecha no es un detalle de cita: en el Red Bull Ring los nombres
#: de curva son derechos comerciales anuales y no un dato cultural como «La
#: Source» o «Copse». La pagina de 2026 nombra la curva 3 y la de 2025 no, y
#: fuentes secundarias del mismo periodo le adosan a la curva 2 y a la 3
#: nombres que el operador no publicaba. La temporada que modela F1 25 es la
#: 2025, asi que se toma la pagina de 2025.
#:
#: Es la misma trampa que el proyecto ya habia anotado para los mapas de la
#: FIA: el documento del ano siguiente existe, abre bien y se ve igual.
#:
#: NUMERACION: mapa de circuito de la FIA del Gran Premio de Austria 2025,
#: version 2, que numera de 1 a 10.
#:
#: METROS: apice de aceleracion lateral, medidos sobre
#: `f1_25:session:1994924273811378928`, siete vueltas que cubren el circuito,
#: con `curvas.tramos_de_una_vuelta` a 0,8 g.
#:
#: POR QUE ESTA VUELTA Y NO OTRA. La primera sesion de Spielberg que se miro
#: ---`f1_25:session:3282644824454978680`--- tiene una sola vuelta usable, no
#: cierra el lazo por 124 m y da quince detecciones para diez curvas. Con una
#: sola vuelta no hay repeticion que mirar y un trompo entra al catalogo como
#: curva. La sesion elegida tiene siete vueltas completas y **las diez zonas se
#: repiten en la mayoria**: ocho de las diez en las siete vueltas, las otras dos
#: en cinco y en seis.
#:
#: COMO SE COMPROBO EL MAPEO. El mapa declara dos limites de sector dichos en
#: curvas: «S1 (170m before T3)» y «S2 (60m before T7)». Los limites de esta
#: vuelta estan medidos aparte por `sector_index` en 1.205,2 m y 2.936,2 m.
#: Cruzando las dos cosas la curva 3 cae en 1.375,2 m y la 7 en 2.996,2 m, sin
#: usar este catalogo. **Los dos caen dentro del tramo que el catalogo nombra
#: con ese numero**, y esa ---y no la distancia--- es la comprobacion: ver
#: `tests/test_catalogo_curvas.py`.
#:
#: Y hay un tercer cruce, gratis: de las cinco curvas cuyo sentido publica una
#: fuente externa ---1, 2, 4, 7 y 9---, las cinco coinciden con el sentido
#: medido. Cinco aciertos sobre un mapeo que podria estar corrido no prueban el
#: catalogo, pero lo harian saltar si estuviera corrido en uno.
SPIELBERG: tuple[Curva, ...] = (
    Curva(1, "Niki Lauda", (1,), 467.3, 123, anclaje=_LAT, sentido="derecha"),
    Curva(2, "Munzer", (2,), 1109.5, 251, anclaje=_LAT, sentido="izquierda"),
    # La mas lenta del trazado, 63 km/h, y la que obligo a cambiar la pregunta
    # de la comprobacion: el punto que declara el mapa cae a 30,5 m del apice.
    Curva(3, "", (3,), 1405.7, 63, anclaje=_LAT, sentido="derecha"),
    Curva(4, "Rauch", (4,), 1572.5, 176, anclaje=_LAT, sentido="derecha"),
    Curva(5, "", (5,), 2253.0, 102, anclaje=_LAT, sentido="derecha"),
    Curva(6, "", (6,), 2741.9, 168, anclaje=_LAT, sentido="izquierda"),
    Curva(7, "Graz", (7,), 2996.8, 173, anclaje=_LAT, sentido="izquierda"),
    Curva(8, "", (8,), 3274.1, 224, anclaje=_LAT, sentido="derecha"),
    Curva(9, "Jochen Rindt", (9,), 3775.7, 174, anclaje=_LAT, sentido="derecha"),
    Curva(10, "", (10,), 4017.9, 149, anclaje=_LAT, sentido="derecha"),
)

#: LO QUE EL MAPA DE LA FIA DECLARA, guardado para poder volver a comprobar.
#: Mapa de circuito del Gran Premio de Austria 2025, version 2.
SPIELBERG_SECTORES_FIA: tuple[DeclaracionDeSector, ...] = (
    DeclaracionDeSector(curva=3, metros=170.0, lado="antes"),
    DeclaracionDeSector(curva=7, metros=60.0, lado="antes"),
)


# --------------------------------------------------------------------------
# Monza -- Autodromo Nazionale
# --------------------------------------------------------------------------

#: Longitud de linea central declarada por el mapa de circuito de la FIA del
#: Gran Premio de Italia 2025 ---«Circuit Centreline Length = 5.793km»--- y por
#: el operador, que publica «5793 meters».
MONZA_LARGO_DECLARADO_M = 5793.0

#: Lo que dio la vuelta medida: 4,2 m de diferencia sobre 5.793.
MONZA_LARGO_MEDIDO_M = 5797.2

#: Desnivel medido en la misma vuelta. Ninguna de las dos fuentes consultadas
#: publica el desnivel de Monza, asi que aca no hay cifra declarada que citar:
#: la ficha lleva la medida y esta linea dice que lo es.
MONZA_DESNIVEL_MEDIDO_M = 12.6

#: Sentido medido con el giro acumulado de una vuelta cerrada, igual que
#: Spielberg. Ver `SPIELBERG_SENTIDO` y el documento de anclajes.
MONZA_SENTIDO = "horario"

#: Monza, trazado de Gran Premio.
#:
#: NOMBRES: pagina de circuito del operador ---Autodromo Nazionale Monza--- y
#: la nota oficial del campeonato «How every corner at Monza got its name». Las
#: dos coinciden, incluido el cambio de «Curva Grande» por «Curva Biassono» y
#: el de «Parabolica» por «Curva Alboreto»: el catalogo guarda el nombre
#: vigente y no el historico, por la misma razon por la que toma los mapas de
#: la temporada que se modela.
#:
#: NUMERACION: mapa de la FIA del Gran Premio de Italia 2025, version 2, que
#: numera de 1 a 11.
#:
#: METROS: apice de aceleracion lateral, medidos sobre
#: `f1_25:session:15159024678183568642`, las dos vueltas que cubren el
#: circuito, con `curvas.tramos_de_una_vuelta` a 0,8 g. Las doce zonas se
#: repiten en las dos.
#:
#: UNA DETECCION MAS QUE CURVAS NUMERADAS, Y NO SOBRA. La FIA numera once y la
#: deteccion encuentra doce. La que no lleva numero esta en el metro 3.309, se
#: toma a 295 km/h y gira apenas a izquierda: es la **Curva del Serraglio**, que
#: el operador nombra y el mapa no numera.
#:
#: Esa deteccion **corre el mapeo por orden**, y por eso no se la puede omitir:
#: la curva 8 del mapa es la novena zona de la vuelta. Esta comprobado sin usar
#: este catalogo. El mapa declara «S2 215m before Turn 8» y el limite medido por
#: `sector_index` esta en 3.731,0 m, asi que la curva 8 cae en 3.946,0 m ---y ahi
#: esta la novena zona, con su apice en 3.951,5---. El otro anclaje, «S1 233m
#: before Turn 4» contra el limite de 1.900,0 m, pone la curva 4 en 2.133,0 m
#: contra un apice de 2.142,8.
#:
#: Es el reverso exacto del caso de Abu Dhabi, que sigue sin nombrar: alla
#: faltan dos detecciones y aca sobra una. Lo que las dos tienen en comun es que
#: basta una para que todo lo posterior quede mal.
MONZA: tuple[Curva, ...] = (
    Curva(1, "Prima Variante", (1,), 940.9, 87, anclaje=_LAT, sentido="derecha"),
    Curva(2, "Prima Variante", (2,), 980.3, 52, anclaje=_LAT, sentido="izquierda"),
    Curva(3, "Curva Biassono", (3,), 1543.8, 250, anclaje=_LAT, sentido="derecha"),
    Curva(4, "Seconda Variante", (4,), 2142.8, 98, anclaje=_LAT, sentido="izquierda"),
    Curva(5, "Seconda Variante", (5,), 2192.6, 107, anclaje=_LAT, sentido="derecha"),
    Curva(6, "Curva di Lesmo", (6,), 2526.6, 178, anclaje=_LAT, sentido="derecha"),
    Curva(7, "Curva di Lesmo", (7,), 2872.0, 173, anclaje=_LAT, sentido="derecha"),
    # Nombrada por el operador y sin numero en el mapa. Ver el encabezado.
    Curva(8, "Curva del Serraglio", (), 3309.4, 295, anclaje=_LAT, sentido="izquierda"),
    Curva(9, "Variante Ascari", (8,), 3951.5, 166, anclaje=_LAT, sentido="izquierda"),
    Curva(10, "Variante Ascari", (9,), 4051.6, 174, anclaje=_LAT, sentido="derecha"),
    Curva(11, "Variante Ascari", (10,), 4140.7, 198, anclaje=_LAT, sentido="izquierda"),
    Curva(12, "Curva Alboreto", (11,), 5264.5, 171, anclaje=_LAT, sentido="derecha"),
)

#: LO QUE EL MAPA DE LA FIA DECLARA, guardado para poder volver a comprobar.
MONZA_SECTORES_FIA: tuple[DeclaracionDeSector, ...] = (
    DeclaracionDeSector(curva=4, metros=233.0, lado="antes"),
    DeclaracionDeSector(curva=8, metros=215.0, lado="antes"),
)


# --------------------------------------------------------------------------
# Suzuka -- Suzuka International Racing Course
# --------------------------------------------------------------------------

#: Longitud de linea central declarada por el mapa de la FIA del Gran Premio de
#: Japon 2025 ---«Circuit Centreline Length = 5.807km»---.
SUZUKA_LARGO_DECLARADO_M = 5807.0

#: Lo que dio la vuelta medida: 3,0 m de diferencia. El lazo cierra en 3,1 m.
SUZUKA_LARGO_MEDIDO_M = 5810.0

#: Desnivel medido en la misma vuelta. Ninguna de las fuentes consultadas
#: publica el desnivel de Suzuka, asi que no hay cifra declarada que citar.
SUZUKA_DESNIVEL_MEDIDO_M = 40.5

#: SENTIDO QUE NO SE PUDO MEDIR, y es el primero del catalogo.
#:
#: El giro acumulado de una vuelta cerrada venia acertando nueve de nueve. En
#: Suzuka da -19,2 grados en una vuelta y +17,1 en la otra: cero, con el signo
#: cambiando. No es ruido, es la topologia. Suzuka es el unico circuito del
#: campeonato **en forma de ocho** ---la recta de atras cruza por arriba de la
#: principal--- y en un ocho el giro total se cancela.
#:
#: El area con signo sobrevive, con mucho menos margen: normalizada por el largo
#: al cuadrado da 0,0037 contra 0,0289 de Monza y 0,0237 de Silverstone. Los dos
#: lazos se restan y queda el del mas grande. De ahi sale este valor, que es
#: para lo que la ficha usa el campo: orientar el dibujo.
#:
#: Ninguna fuente consultada ---el mapa de la FIA, la enciclopedia, la guia de
#: circuito del campeonato--- publica el sentido de Suzuka.
SUZUKA_SENTIDO = "horario"

#: Suzuka, trazado de Gran Premio.
#:
#: NOMBRES: guia de circuito del Gran Premio de Japon, que los asigna curva por
#: curva. NUMERACION: mapa de la FIA del Gran Premio de Japon 2025, version 1,
#: que numera de 1 a 18.
#:
#: METROS: apice de aceleracion lateral, medidos sobre
#: `f1_25:session:17211676691250864516`, **vuelta 2**, con
#: `curvas.tramos_de_una_vuelta` a 0,8 g.
#:
#: POR QUE LA VUELTA 2 Y NO LA 1. En la vuelta 1 las dos Degner salen fundidas
#: en una sola zona de 253 m y en la vuelta 2 aparecen separadas. Son dos curvas
#: numeradas y el catalogo necesita las dos: la vuelta que las distingue es la
#: que sirve. Las otras quince zonas coinciden en las dos vueltas.
#:
#: DOS PUBLICACIONES DISCREPAN, Y LAS DESEMPATA EL MAPA. Una guia dice que la
#: curva 7 es la Dunlop y la 8 Degner 1; otra, que la 8 es la Dunlop y la 9
#: Degner 1. El mapa de la FIA no publica ningun nombre, y justamente por eso
#: puede arbitrar: declara que el sector 2 abre 105 m antes de la curva 8, y ese
#: limite esta medido en 2.227,1 m. La curva 8 cae en 2.332,1 m, donde la
#: deteccion encuentra una zona que gira a **derecha**; la Dunlop es una
#: izquierda en las dos guias. Gana la primera numeracion.
#:
#: El otro anclaje ---«S2 270m before Turn 15» contra el limite de 4.690,1 m---
#: pone la 130R en 4.960,1 m, dentro de la zona 4.926,2-5.186,9.
#:
#: Y TRECE SENTIDOS PUBLICADOS COINCIDEN CON LOS TRECE MEDIDOS, sobre esta misma
#: vuelta. No prueban el catalogo, pero lo harian saltar si estuviera corrido.
SUZUKA: tuple[Curva, ...] = (
    # La primera curva: dos numeros y un solo giro de 189 grados a derecha.
    # Ninguna de las guias consultadas le pone nombre.
    Curva(1, "", (1, 2), 640.7, 143, anclaje=_LAT, sentido="derecha"),
    Curva(2, "Curvas S", (3,), 1101.7, 180, anclaje=_LAT, sentido="izquierda"),
    Curva(3, "Curvas S", (4,), 1193.7, 153, anclaje=_LAT, sentido="derecha"),
    Curva(4, "Curvas S", (5,), 1373.9, 192, anclaje=_LAT, sentido="izquierda"),
    Curva(5, "Curvas S", (6,), 1527.7, 149, anclaje=_LAT, sentido="derecha"),
    Curva(6, "Curva Dunlop", (7,), 2045.5, 181, anclaje=_LAT, sentido="izquierda"),
    Curva(7, "Degner 1", (8,), 2305.8, 207, anclaje=_LAT, sentido="derecha"),
    Curva(8, "Degner 2", (9,), 2480.0, 144, anclaje=_LAT, sentido="derecha"),
    Curva(9, "", (10,), 2810.9, 210, anclaje=_LAT, sentido="derecha"),
    # La mas lenta del trazado, 72 km/h, y la que el ocho no alcanza a tapar.
    Curva(10, "Horquilla", (11,), 2916.9, 72, anclaje=_LAT, sentido="izquierda"),
    Curva(11, "", (12,), 3527.2, 195, anclaje=_LAT, sentido="derecha"),
    Curva(12, "Curva Spoon", (13, 14), 3946.5, 153, anclaje=_LAT, sentido="izquierda"),
    Curva(13, "130R", (15,), 4948.9, 253, anclaje=_LAT, sentido="izquierda"),
    Curva(14, "Chicana Casio", (16,), 5409.0, 95, anclaje=_LAT, sentido="derecha"),
    Curva(15, "Chicana Casio", (17,), 5462.6, 84, anclaje=_LAT, sentido="izquierda"),
    Curva(16, "Chicana Casio", (18,), 5693.2, 112, anclaje=_LAT, sentido="derecha"),
)

#: DOS TRAMOS QUE LA DETECCION ENCUENTRA Y EL MAPA NO NUMERA.
#:
#: Estan en la recta de atras, entre la Spoon y la 130R, y se toman a 273 y
#: 291 km/h. Es el mismo caso que los dos de la recta Hangar en Silverstone: se
#: declaran con su metro y su velocidad para que la ausencia sea explicita y no
#: parezca que se perdieron dos nombres.
SUZUKA_SIN_NOMBRE: tuple[tuple[float, int], ...] = (
    (4344.5, 273),
    (4494.7, 291),
)

#: LO QUE EL MAPA DE LA FIA DECLARA, guardado para poder volver a comprobar.
SUZUKA_SECTORES_FIA: tuple[DeclaracionDeSector, ...] = (
    DeclaracionDeSector(curva=8, metros=105.0, lado="antes"),
    DeclaracionDeSector(curva=15, metros=270.0, lado="antes"),
)


#: EL SENTIDO DE GIRO, MEDIDO, Y CON SU CONTROL NEGATIVO.
#:
#: POR QUE HIZO FALTA MEDIRLO. Spa lo tiene declarado por su operador, pero
#: Spielberg no: ni el mapa de la FIA, ni la pagina del circuito, ni la guia del
#: campeonato dicen si se corre horario o antihorario. Copiarlo del vecino
#: habria sido inventarlo, y el sentido no es decorativo ---orienta la
#: proyeccion del trazado, asi que si esta al reves se ve---.
#:
#: COMO SE MIDE. Una vuelta cerrada es exactamente una revolucion. El giro
#: acumulado es la integral de la aceleracion lateral sobre el cuadrado de la
#: velocidad, y `analisis/curvas` fija que **negativo es derecha**.
#:
#: LA MAGNITUD NO SIRVE Y EL SIGNO SI, y conviene decirlo porque la primera
#: lectura de esto fue demasiado optimista. Silverstone da -363,2 grados, que
#: es una revolucion con 0,9 % de error, y eso invita a leer el numero como si
#: midiera la vuelta. No la mide: la vuelta 1 de Monza da -545,0 y la 1 de
#: Monaco -642,7. Lo que se usa es el signo.
#:
#: Y EL SIGNO SE COMPROBO CONTRA UN CONTROL NEGATIVO, que es lo que lo hace
#: defendible. Medido el 2026-09-14 sobre nueve circuitos de sentido conocido:
#:
#:     horario       silverstone  -363,2      antihorario  imola       +194,8
#:                   monza        -376,3                   abu-dhabi   +371,3
#:                   melbourne    -378,9                   austin      +426,2
#:                   spielberg    -390,2                   baku        +440,9
#:                   shanghai     -385,7
#:                   spa          -421,1
#:
#: Nueve de nueve. Los dos grupos no se tocan, y ninguno de los cuatro
#: antihorarios participo de elegir el criterio.
GIRO_NETO_MEDIDO_GRADOS: dict[str, float] = {
    "spa-francorchamps": -421.1,
    "silverstone": -363.2,
    "spielberg": -390.2,
    "monza": -376.3,
}


#: DONDE ESTE INSTRUMENTO NO SE PUEDE USAR, Y POR QUE. Va con el motivo escrito
#: porque un circuito al que se le olvido medir el giro y uno donde la medicion
#: no aplica se ven igual desde afuera: los dos faltan del diccionario de
#: arriba. Una prueba exige que cada circuito del catalogo este en una lista o
#: en la otra.
GIRO_QUE_NO_SE_PUEDE_MEDIR: dict[str, str] = {
    "suzuka":
        "es el unico circuito del campeonato en forma de ocho ---la recta de "
        "atras cruza por arriba de la principal--- y en un ocho el giro total "
        "se cancela: un lazo aporta +360 grados y el otro -360. Medido da "
        "-19,2 en una vuelta y +17,1 en la otra. El sentido de la ficha sale "
        "del area con signo, que sobrevive con mucho menos margen: 0,0037 "
        "normalizada, contra 0,0289 de Monza.",
}


#: Indexado por el identificador estable de circuito, igual que
#: `track_reference`, para poder crecer a otros circuitos sin cambiar la interfaz.
CATALOGO: dict[str, tuple[Curva, ...]] = {
    "spa-francorchamps": SPA_FRANCORCHAMPS,
    "silverstone": SILVERSTONE,
    "spielberg": SPIELBERG,
    "monza": MONZA,
    "suzuka": SUZUKA,
}

#: Como nombra cada circuito el capturador, que deriva la clave del paquete de
#: sesion del juego. Sin esta tabla la consulta por `spa` ---que es lo que trae
#: la procedencia de las capturas--- no encontraba el catalogo, que esta
#: indexado por el nombre completo del circuito, y las curvas volvian vacias.
#: El catalogo se indexa por su nombre propio; los alias son de la fuente.
ALIAS: dict[str, str] = {
    "spa": "spa-francorchamps",
    "silverstone-gp": "silverstone",
    "spa_francorchamps": "spa-francorchamps",
    "francorchamps": "spa-francorchamps",
    "red-bull-ring": "spielberg",
    "autodromo-nazionale-monza": "monza",
    "suzuka-international-racing-course": "suzuka",
    "redbullring": "spielberg",
}


@dataclass(frozen=True)
class Ficha:
    """Lo que se declara de un circuito entero, y no de una curva suya.

    POR QUE EXISTE. Estos cuatro datos estaban escritos a mano en
    `/circuitos/{circuito}/curvas`, tomados de las constantes de Spa, para
    **cualquier** circuito. Con un solo circuito en el catalogo la respuesta
    siempre acertaba; el segundo la habria hecho contestar que Silverstone mide
    7.004 m, tiene 102,2 m de desnivel y que Kemmel no frena.

    Es el mismo defecto de dos escritores que este sistema ya tuvo con
    `estado.clima`, con el pie de avisos y con el constructor del trazado. El
    arreglo es el de siempre: el dato vive en un solo lado, junto al catalogo y
    indexado igual, y quien lo muestre lo lee de ahi.
    """

    #: Longitud declarada por el operador o por la ficha del campeonato.
    largo_declarado_m: float
    #: Desnivel declarado, en metros.
    desnivel_declarado_m: float
    #: Sentido en que se corre. Orienta la proyeccion del trazado.
    sentido: str
    #: Zonas con nombre que el catalogo declara y la deteccion no encuentra
    #: porque no hay frenada. Vacio cuando el circuito no tiene ninguna, que es
    #: distinto de no haberlo mirado.
    sin_frenada: tuple[str, ...] = ()


#: Indexada por la misma clave que `CATALOGO`, y comprobado por prueba: un
#: circuito con curvas y sin ficha obligaria a la ruta a inventar una.
FICHAS: dict[str, Ficha] = {
    "spa-francorchamps": Ficha(
        largo_declarado_m=SPA_LARGO_DECLARADO_M,
        desnivel_declarado_m=SPA_DESNIVEL_DECLARADO_M,
        sentido=SPA_SENTIDO,
        sin_frenada=SPA_SIN_FRENADA,
    ),
    "silverstone": Ficha(
        largo_declarado_m=SILVERSTONE_LARGO_DECLARADO_M,
        desnivel_declarado_m=SILVERSTONE_DESNIVEL_MEDIDO_M,
        sentido=SILVERSTONE_SENTIDO,
        # Vacio a proposito: en Silverstone lo que sobra son detecciones sin
        # nombre ---ver `SILVERSTONE_SIN_NOMBRE`--- y no nombres sin deteccion.
        # Son dos ausencias distintas y copiar la de Spa aca seria afirmar algo
        # que nadie midio.
        sin_frenada=(),
    ),
    "spielberg": Ficha(
        largo_declarado_m=SPIELBERG_LARGO_DECLARADO_M,
        desnivel_declarado_m=SPIELBERG_DESNIVEL_DECLARADO_M,
        sentido=SPIELBERG_SENTIDO,
        # Vacio, y comprobado: las diez curvas que el mapa numera aparecen en
        # la deteccion. Lo que falta en Spielberg no son detecciones sino
        # nombres ---cinco de las diez---, y esa ausencia vive en la fila, con
        # el nombre vacio, no aca.
        sin_frenada=(),
    ),
    "monza": Ficha(
        largo_declarado_m=MONZA_LARGO_DECLARADO_M,
        # MEDIDO, no declarado: ninguna de las dos fuentes publica el desnivel
        # de Monza. Es la misma deuda que ya tiene Silverstone y por ahora se
        # anota en vez de cambiar el nombre del campo en los cuatro circuitos.
        desnivel_declarado_m=MONZA_DESNIVEL_MEDIDO_M,
        sentido=MONZA_SENTIDO,
        # Vacio: en Monza no hay zona con nombre que la deteccion no encuentre.
        # Lo que hay es al reves, una deteccion que el mapa no numera, y esa
        # vive en la fila ---con su nombre y su numero vacio--- no aca.
        sin_frenada=(),
    ),
    "suzuka": Ficha(
        largo_declarado_m=SUZUKA_LARGO_DECLARADO_M,
        # MEDIDO: ninguna fuente consultada publica el desnivel de Suzuka.
        desnivel_declarado_m=SUZUKA_DESNIVEL_MEDIDO_M,
        sentido=SUZUKA_SENTIDO,
        # Vacio y comprobado: las dieciocho curvas que el mapa numera aparecen
        # en la deteccion. Lo que sobra son dos tramos sin numerar, y esos viven
        # en `SUZUKA_SIN_NOMBRE`.
        sin_frenada=(),
    ),
}


def _clave(circuito: str) -> str:
    clave = circuito.strip().lower().replace(" ", "-")
    return ALIAS.get(clave, clave)


def ficha_de(circuito: str) -> Ficha | None:
    """La ficha de un circuito, o `None` si no esta en el catalogo.

    Devolver `None` y no una ficha vacia es deliberado: una ficha con ceros se
    muestra como un circuito de cero metros, y quien la reciba no puede
    distinguir «no lo tenemos» de «mide cero».
    """

    return FICHAS.get(_clave(circuito))


def curvas_de(circuito: str) -> tuple[Curva, ...]:
    """Devuelve el catalogo de un circuito, o una tupla vacia si no esta.

    Devolver vacio y no fallar es deliberado: un circuito sin catalogo debe
    mostrarse sin nombres de curva, no romper la vista.
    """
    return CATALOGO.get(_clave(circuito), ())


def rotulo_de(curva: Curva) -> str:
    """Como se llama a esta curva en pantalla, con nombre publicado o sin el.

    QUIEN RESUELVE EL VACIO ES UNO SOLO, y por eso esto es una funcion y no una
    linea en el tablero. En Spielberg el operador nombra cinco de las diez
    curvas, y las otras cinco se guardan con `nombre` vacio porque **nadie las
    nombra**: el vacio es el hecho. Pero un rotulo en blanco sobre el trazado no
    es un hecho, es un dibujo roto.

    La salida es el numero que publica el mapa de la FIA, que es una fuente
    citada igual que el nombre. No se inventa nada: se dice lo que si se sabe.

    Este sistema ya tuvo cuatro veces el defecto de un dato con dos dueños
    ---`estado.clima`, el pie de avisos, el constructor del trazado, la ficha
    del circuito---. Si el tablero resolviera el vacio por su cuenta, el rotulo
    de la pantalla y el del servidor podrian separarse sin que nada avisara.
    """

    if curva.nombre:
        return curva.nombre
    numeros = "-".join(str(n) for n in curva.numeros_cronometraje)
    return f"Curva {numeros}" if numeros else f"Curva {curva.orden}"


def nombre_en_metro(circuito: str, metro: float, tolerancia_m: float = 60.0) -> str | None:
    """Nombre de la zona nombrada mas cercana a un metro de la vuelta, si hay.

    `tolerancia_m` acota cuanto puede alejarse el punto consultado del anclaje
    medido antes de que la respuesta deje de ser defendible. Fuera de esa
    distancia devuelve `None` en vez de estirar el nombre de la curva vecina.

    LAS CURVAS SIN NOMBRE SE SALTEAN, y no es lo mismo que descartarlas. Esta
    funcion contesta «como se llama lo que hay en este metro», y de una curva
    que nadie nombro la respuesta honesta es que no se sabe: devolver la cadena
    vacia la haria pasar por un nombre, y quien la reciba no puede distinguirla
    de un nombre en blanco. Para rotular el trazado ---donde la curva si esta y
    hay que dibujarla--- esta `rotulo_de`, que contesta otra pregunta.
    """
    mejor, distancia = None, tolerancia_m
    for curva in curvas_de(circuito):
        if not curva.nombre:
            continue
        d = abs(curva.metro_medido - metro)
        if d <= distancia:
            mejor, distancia = curva, d
    return mejor.nombre if mejor else None
