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

#: Indexado por el identificador estable de circuito, igual que
#: `track_reference`, para poder crecer a otros circuitos sin cambiar la interfaz.
CATALOGO: dict[str, tuple[Curva, ...]] = {
    "spa-francorchamps": SPA_FRANCORCHAMPS,
}

#: Como nombra cada circuito el capturador, que deriva la clave del paquete de
#: sesion del juego. Sin esta tabla la consulta por `spa` ---que es lo que trae
#: la procedencia de las capturas--- no encontraba el catalogo, que esta
#: indexado por el nombre completo del circuito, y las curvas volvian vacias.
#: El catalogo se indexa por su nombre propio; los alias son de la fuente.
ALIAS: dict[str, str] = {
    "spa": "spa-francorchamps",
    "spa_francorchamps": "spa-francorchamps",
    "francorchamps": "spa-francorchamps",
}


def curvas_de(circuito: str) -> tuple[Curva, ...]:
    """Devuelve el catalogo de un circuito, o una tupla vacia si no esta.

    Devolver vacio y no fallar es deliberado: un circuito sin catalogo debe
    mostrarse sin nombres de curva, no romper la vista.
    """
    clave = circuito.strip().lower().replace(" ", "-")
    return CATALOGO.get(ALIAS.get(clave, clave), ())


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
