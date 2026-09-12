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

#: Indexado por el identificador estable de circuito, igual que
#: `track_reference`, para poder crecer a otros circuitos sin cambiar la interfaz.
CATALOGO: dict[str, tuple[Curva, ...]] = {
    "spa-francorchamps": SPA_FRANCORCHAMPS,
    "silverstone": SILVERSTONE,
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


def nombre_en_metro(circuito: str, metro: float, tolerancia_m: float = 60.0) -> str | None:
    """Nombre de la zona mas cercana a un metro de la vuelta, si hay alguna.

    `tolerancia_m` acota cuanto puede alejarse el punto consultado del anclaje
    medido antes de que la respuesta deje de ser defendible. Fuera de esa
    distancia devuelve `None` en vez de estirar el nombre de la curva vecina.
    """
    mejor, distancia = None, tolerancia_m
    for curva in curvas_de(circuito):
        d = abs(curva.metro_medido - metro)
        if d <= distancia:
            mejor, distancia = curva, d
    return mejor.nombre if mejor else None
