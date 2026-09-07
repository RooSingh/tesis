# -*- coding: utf-8 -*-
"""Modulo de analisis telemetrico.

Opera sobre el **contrato interno** y no sobre ninguna fuente en particular. Es
la afirmacion central del trabajo aplicada al analisis en lugar de a la ingesta:
incorporar una fuente es escribir un adaptador, y el analisis no se entera.

De esa decision se sigue la obligacion que este paquete asume: **cada herramienta
declara que puede hacer con la sesion que se le da**, y lo declara midiendo esa
sesion y no consultando una tabla escrita de antemano. Una fuente que en general
publica el freno puede tener una sesion sin el.

Que ninguna herramienta estime en silencio es la regla que ordena el resto. Si la
resolucion no alcanza o la magnitud no esta, se dice; no se interpola para que el
resultado exista.
Como se usa
-----------
Cada herramienta vive en su modulo y se lo importa por su nombre:

    from backend.analisis import consistencia, degradacion, frenadas, traccion
    resultado = consistencia.analizar(fuente, session_id)

**Los submodulos se declaran abajo a proposito.** Sin declararlos, importarlos
funcionaria igual ---Python los resuelve solo--- pero por accidente de la
maquinaria de importacion y no porque el paquete lo ofrezca. Tres de las siete
entradas se llaman `analizar`, de modo que exponerlas planas obligaria a
renombrarlas y a que el nombre dejara de decir a que herramienta pertenece.
"""

from backend.analisis import (  # noqa: F401
    ajuste,
    consistencia,
    curvas,
    degradacion,
    delta,
    disponibilidad,
    fases,
    frenadas,
    lectura,
    traccion,
    vueltas,
)
from backend.analisis.disponibilidad import (  # noqa: F401
    COMPLETA,
    DEGRADADA,
    IMPOSIBLE,
    Disponibilidad,
    Herramienta,
    Requisito,
    evaluar,
    evaluar_todas,
    herramientas,
)
from backend.analisis.vueltas import (  # noqa: F401
    Sesion,
    SinVueltas,
    Vuelta,
    extraer,
    resumen,
)
from backend.analisis.delta import (  # noqa: F401
    SinTraza,
    Tramo,
    Traza,
    comparar,
    tramos_dominantes,
)
from backend.analisis.fases import (  # noqa: F401
    CurvaEnVuelta,
    Fase,
    Trazado,
    fases_de_vuelta,
    trazado,
)
from backend.analisis.frenadas import (  # noqa: F401
    Frenada,
    Frenadas,
    caracterizar,
)
from backend.analisis.ajuste import Ajuste, Coeficiente, ajustar  # noqa: F401
from backend.analisis.consistencia import Consistencia, Tanda  # noqa: F401
from backend.analisis.degradacion import Degradacion  # noqa: F401
from backend.analisis.traccion import Salida, Traccion  # noqa: F401
