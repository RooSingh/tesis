"""Referencias bibliograficas de reglaje, separadas de la medicion.

Una referencia de comunidad no es un optimo ni una instruccion. Sirve para
declarar contra que condicion externa se compara el reglaje observado. Los
campos sin fuente cuantitativa se omiten: ausente no significa cero.

DE QUE DEPENDE UNA REFERENCIA, Y DE QUE NO
------------------------------------------
La pregunta natural es si el reglaje recomendado depende de la pista, del
clima, del auto y de quien conduce. Verificado contra la fuente el 2026-09-13:

* **De la pista, si.** Es el eje principal: hay una entrada por circuito.
* **Del clima, si.** La fuente publica un reglaje seco y uno de lluvia.
* **Del modo, si, y esto pesa mas de lo que parece.** Un reglaje de carrera no
  es uno de contrarreloj, y las paginas lo dicen con todas las letras: «this
  isn't a time trial setup, and is designed specifically for races». Casi todas
  las sesiones capturadas de este trabajo son contrarreloj.
* **Del auto, NO.** La fuente publica **un reglaje por pista para todos los
  autos**: «usable with any team in F1 25 and in any mode». En el juego los
  rangos de ajuste son los mismos para los veinte coches.
* **De quien conduce, NO.** En la Formula 1 de verdad el reglaje se adapta al
  estilo de cada piloto ---los equipos lo declaran asi--- pero una referencia
  publicada no puede depender de quien la lea. Lo que la fuente si da son
  ajustes condicionados a un **sintoma** («si tenes subviraje, hace X»), que es
  otra cosa: depende de lo que el coche hace, no de quien es.

LO NUMERICO Y LO DECLARADO VIVEN SEPARADOS
------------------------------------------
La fuente publica algunos ejes como numeros ---alerones, diferencial, sesgo de
freno--- y otros como instrucciones: «all the way left» para la caida y la
convergencia, «maximum» para las presiones en varias pistas. Los primeros van
en `valores` y se comparan restando. Los segundos no entran: convertir «todo a
la izquierda» en un numero seria inventar el dato que falta.
"""

from __future__ import annotations


#: Lo que una referencia no autoriza a concluir, escrito una vez.
#:
#: Se repetia palabra por palabra en cada entrada, y con diecisiete entradas eso
#: son diecisiete sitios donde corregir la misma frase.
ALCANCE = (
    "Referencia de comunidad publicada para el juego, no una medición de este "
    "trabajo: no demuestra que sea óptima ni que cause una mejora. Sirve para "
    "declarar contra qué condición externa se compara el reglaje observado"
)


#: LO QUE LA FUENTE PUBLICA PARA CADA PISTA, TRANSCRITO Y CITADO.
#:
#: COMO SE TRANSCRIBIO, Y POR QUE ASI. Cada ficha se leyo de su propia pagina
#: pidiendo la **frase textual** que enuncia cada valor, y `cita` la conserva.
#: No es una formalidad: leyendo Monaco, el resumen automatico agrego por su
#: cuenta «(the front would be 46 %)» sobre un sesgo de freno que la pagina da
#: como 54 %. La frase citada lo desmiente sola; un numero suelto, no.
#:
#: LO QUE NO ENTRA. La fuente enuncia la caida, la convergencia y ---en varias
#: pistas--- las presiones como instrucciones y no como cifras: «all the way
#: left», «maximum». Eso no se convierte a un numero, porque el numero no
#: existe. Y lo que una pagina enuncia de forma ambigua se omite y se dice en
#: `cita`, en vez de elegir una lectura.
#:
#: TODAS SON DE CARRERA EN SECO, y esa es la limitacion que mas pesa: casi
#: todas las sesiones capturadas en este trabajo son contrarreloj, y la propia
#: fuente repite que «this isn't a time trial setup».
REFERENCIAS = {
    ("f1-25", "melbourne", "seco"): {
        "programa": "F1 25",
        "circuito": "Melbourne",
        "modo": "carrera",
        "clima": "seco",
        "valores": {
            "aleron_delantero": 21,
            "aleron_trasero": 17,
            "sesgo_de_freno_pct": 54,
            "diferencial_sin_acelerador_pct": 45,
        },
        "cita": (
            "«21 at the front and 17 at the rear»; «a bias of 54 % and pressure "
            "de 100 %»; «45 % off throttle differential». El diferencial con "
            "acelerador queda afuera: la pagina lo enuncia de forma ambigua"),
        "fuente": {
            "titulo": "F1 25 Melbourne Car Setup: Full Setup & Guide",
            "autor": "SimRacingSetup",
            "anio": 2025,
            "url": "https://simracingsetup.com/ea-sports-f1/f1-25-australia-car-setup/",
            "clave_bibliografica": "simracingsetup_f1_25_melbourne",
        },
        "alcance": ALCANCE,
    },
    ("f1-25", "shanghai", "seco"): {
        "programa": "F1 25",
        "circuito": "Shanghai",
        "modo": "carrera",
        "clima": "seco",
        "valores": {
            "aleron_delantero": 24,
            "aleron_trasero": 21,
            "sesgo_de_freno_pct": 56,
            "diferencial_con_acelerador_pct": 90,
            "diferencial_sin_acelerador_pct": 45,
        },
        "cita": (
            "«I have gone with an aero setup of 24 on the front wing and 21 on "
            "the rear»; «I've set the bias to 56 % which is actually pretty high»"),
        "fuente": {
            "titulo": "F1 25 Shanghai Car Setup: Full Setup & Guide",
            "autor": "SimRacingSetup",
            "anio": 2025,
            "url": "https://simracingsetup.com/ea-sports-f1/f1-25-china-car-setup/",
            "clave_bibliografica": "simracingsetup_f1_25_shanghai",
        },
        "alcance": ALCANCE,
    },
    ("f1-25", "suzuka", "seco"): {
        "programa": "F1 25",
        "circuito": "Suzuka",
        "modo": "carrera",
        "clima": "seco",
        "valores": {
            "aleron_delantero": 30,
            "aleron_trasero": 32,
            "sesgo_de_freno_pct": 55,
            "diferencial_con_acelerador_pct": 90,
            "diferencial_sin_acelerador_pct": 40,
        },
        "cita": (
            "«I have set the aero to 30 at the front and 32 at the rear»; «I have "
            "set the brake bias to 55 %»"),
        "fuente": {
            "titulo": "F1 25 Suzuka Car Setup: Full Setup & Guide",
            "autor": "SimRacingSetup",
            "anio": 2025,
            "url": "https://simracingsetup.com/ea-sports-f1/f1-25-japan-car-setup/",
            "clave_bibliografica": "simracingsetup_f1_25_suzuka",
        },
        "alcance": ALCANCE,
    },
    ("f1-25", "sakhir", "seco"): {
        "programa": "F1 25",
        "circuito": "Sakhir",
        "modo": "carrera",
        "clima": "seco",
        "valores": {
            "aleron_delantero": 34,
            "aleron_trasero": 29,
            "sesgo_de_freno_pct": 55,
            "diferencial_con_acelerador_pct": 75,
            "diferencial_sin_acelerador_pct": 40,
        },
        "cita": (
            "«34 at the front and 29 at the rear»; «55 %»"),
        "fuente": {
            "titulo": "F1 25 Sakhir Car Setup: Full Setup & Guide",
            "autor": "SimRacingSetup",
            "anio": 2025,
            "url": "https://simracingsetup.com/ea-sports-f1/f1-25-bahrain-car-setup/",
            "clave_bibliografica": "simracingsetup_f1_25_sakhir",
        },
        "alcance": ALCANCE,
    },
    ("f1-25", "miami", "seco"): {
        "programa": "F1 25",
        "circuito": "Miami",
        "modo": "carrera",
        "clima": "seco",
        "valores": {
            "aleron_delantero": 9,
            "aleron_trasero": 9,
            "sesgo_de_freno_pct": 55,
            "diferencial_con_acelerador_pct": 70,
            "diferencial_sin_acelerador_pct": 45,
        },
        "cita": (
            "«I have to front set exactly the same as at Jeddah with a setting of "
            "9. However, I have increased the rear wing aero compared to Jeddah, "
            "bringing it level with the front, also at 9»"),
        "fuente": {
            "titulo": "F1 25 Miami Car Setup: Full Setup & Guide",
            "autor": "SimRacingSetup",
            "anio": 2025,
            "url": "https://simracingsetup.com/ea-sports-f1/f1-25-miami-car-setup/",
            "clave_bibliografica": "simracingsetup_f1_25_miami",
        },
        "alcance": ALCANCE,
    },
    ("f1-25", "imola", "seco"): {
        "programa": "F1 25",
        "circuito": "Imola",
        "modo": "carrera",
        "clima": "seco",
        "valores": {
            "aleron_delantero": 39,
            "aleron_trasero": 36,
            "sesgo_de_freno_pct": 55,
            "diferencial_con_acelerador_pct": 65,
            "diferencial_sin_acelerador_pct": 40,
        },
        "cita": (
            "«39 on the front wing and 36 on the rear»; «Set the brake bias to 55 "
            "%»"),
        "fuente": {
            "titulo": "F1 25 Imola Car Setup: Full Setup & Guide",
            "autor": "SimRacingSetup",
            "anio": 2025,
            "url": "https://simracingsetup.com/ea-sports-f1/f1-25-imola-car-setup/",
            "clave_bibliografica": "simracingsetup_f1_25_imola",
        },
        "alcance": ALCANCE,
    },
    ("f1-25", "monte-carlo", "seco"): {
        "programa": "F1 25",
        "circuito": "Monte-Carlo",
        "modo": "carrera",
        "clima": "seco",
        "valores": {
            "aleron_delantero": 50,
            "aleron_trasero": 50,
            "sesgo_de_freno_pct": 54,
        },
        "cita": (
            "«I have gone for 50 on both front and rear wings»; «a slightly more "
            "rearward brake bias of 54 %». Los diferenciales quedan afuera: no se "
            "transcribieron de esta pagina"),
        "fuente": {
            "titulo": "F1 25 Monte-Carlo Car Setup: Full Setup & Guide",
            "autor": "SimRacingSetup",
            "anio": 2025,
            "url": "https://simracingsetup.com/ea-sports-f1/f1-25-monaco-car-setup/",
            "clave_bibliografica": "simracingsetup_f1_25_monte_carlo",
        },
        "alcance": ALCANCE,
    },
    ("f1-25", "catalunya", "seco"): {
        "programa": "F1 25",
        "circuito": "Catalunya",
        "modo": "carrera",
        "clima": "seco",
        "valores": {
            "aleron_delantero": 31,
            "aleron_trasero": 29,
            "sesgo_de_freno_pct": 54,
            "diferencial_con_acelerador_pct": 70,
            "diferencial_sin_acelerador_pct": 35,
        },
        "cita": (
            "«an aero of 31 and 29»; «54 % once again»"),
        "fuente": {
            "titulo": "F1 25 Catalunya Car Setup: Full Setup & Guide",
            "autor": "SimRacingSetup",
            "anio": 2025,
            "url": "https://simracingsetup.com/ea-sports-f1/f1-25-spain-car-setup/",
            "clave_bibliografica": "simracingsetup_f1_25_catalunya",
        },
        "alcance": ALCANCE,
    },
    ("f1-25", "spielberg", "seco"): {
        "programa": "F1 25",
        "circuito": "Spielberg",
        "modo": "carrera",
        "clima": "seco",
        "valores": {
            "aleron_delantero": 24,
            "aleron_trasero": 21,
            "sesgo_de_freno_pct": 54,
            "diferencial_con_acelerador_pct": 75,
            "diferencial_sin_acelerador_pct": 40,
        },
        "cita": (
            "«an incredibly low downforce 24 and 21»; «a setup of 54 or 55 % bias "
            "is good» ---se toma el menor de los dos que la pagina ofrece---"),
        "fuente": {
            "titulo": "F1 25 Spielberg Car Setup: Full Setup & Guide",
            "autor": "SimRacingSetup",
            "anio": 2025,
            "url": "https://simracingsetup.com/ea-sports-f1/f1-25-austria-car-setup/",
            "clave_bibliografica": "simracingsetup_f1_25_spielberg",
        },
        "alcance": ALCANCE,
    },
    ("f1-25", "silverstone", "seco"): {
        "programa": "F1 25",
        "circuito": "Silverstone",
        "modo": "carrera",
        "clima": "seco",
        "valores": {
            "aleron_delantero": 19,
            "aleron_trasero": 21,
            "sesgo_de_freno_pct": 55,
            "diferencial_con_acelerador_pct": 60,
            "diferencial_sin_acelerador_pct": 40,
        },
        "cita": (
            "«19 at the front and 21 for the rear wing aero»; «Set the brake bias "
            "to 55 % and the pressure to 100 %»"),
        "fuente": {
            "titulo": "F1 25 Silverstone Car Setup: Full Setup & Guide",
            "autor": "SimRacingSetup",
            "anio": 2025,
            "url": "https://simracingsetup.com/ea-sports-f1/f1-25-british-car-setup/",
            "clave_bibliografica": "simracingsetup_f1_25_silverstone",
        },
        "alcance": ALCANCE,
    },
    #: LA UNICA DE AGUA, Y DE OTRA PROCEDENCIA QUE LAS DE SECO.
    #:
    #: Las de seco salen de las paginas de guia que el sitio escribe. Esta sale
    #: de una **ficha enviada por un usuario**, etiquetada con un equipo y un
    #: tiempo de vuelta. Es mas debil como fuente y por eso se dice: quien la
    #: mira tiene que poder distinguirla de la otra.
    #:
    #: POR QUE HAY UNA SOLA. De las veintisiete sesiones capturadas, **ninguna
    #: tiene lluvia** ---veinticuatro despejadas y tres cubiertas--- de modo que
    #: hoy esta referencia no se muestra en ninguna pantalla. Se carga porque el
    #: eje ya existe y porque la primera sesion con agua la va a encontrar
    #: puesta; llenar las diecisiete sin poder contrastar ninguna habria sido
    #: transcribir a ciegas. Las paginas de guia no publican reglaje de agua, y
    #: las fichas de usuario que dicen «Dry & Wet» son **un solo reglaje** que se
    #: ofrece para las dos cosas: eso no es una referencia de lluvia.
    ("f1-25", "spa-francorchamps", "lluvia"): {
        "programa": "F1 25",
        "circuito": "Spa-Francorchamps",
        "modo": "carrera",
        "clima": "lluvia",
        "valores": {
            "aleron_delantero": 18,
            "aleron_trasero": 18,
            "sesgo_de_freno_pct": 58,
            "diferencial_con_acelerador_pct": 80,
            "diferencial_sin_acelerador_pct": 40,
        },
        "cita": (
            "Ficha de usuario etiquetada «Wet» y «Race Setup»: «Front Wing "
            "Aero 18», «Rear Wing Aero 18», «Differential Adjustment On "
            "Throttle 80», «Differential Adjustment Off Throttle 40», «Brake "
            "Bias 58». Contra la de seco de la misma pista ---3 y 0--- son "
            "quince y dieciocho puntos mas de carga"),
        "fuente": {
            "titulo": "Belgian Grand Prix 2025 Ferrari Wet 1:47:856",
            "autor": "SimRacingSetup (ficha enviada por un usuario)",
            "anio": 2025,
            "url": "https://simracingsetup.com/setups/f1-25-setups/belgian-grand-prix-2025-ferrari-wet-147856/",
            "clave_bibliografica": "simracingsetup_f1_25_spa_lluvia",
        },
        "alcance": ALCANCE,
    },
    ("f1-25", "spa-francorchamps", "seco"): {
        "programa": "F1 25",
        "circuito": "Spa-Francorchamps",
        "modo": "carrera",
        "clima": "seco",
        "valores": {
            "aleron_delantero": 3,
            "aleron_trasero": 0,
            "sesgo_de_freno_pct": 54,
            "diferencial_con_acelerador_pct": 85,
            "diferencial_sin_acelerador_pct": 45,
        },
        "cita": (
            "«Front Wing 3, Rear Wing 0»; «Brake Bias 54 %»"),
        "fuente": {
            "titulo": "F1 25 Spa-Francorchamps Car Setup: Full Setup & Guide",
            "autor": "SimRacingSetup",
            "anio": 2025,
            "url": "https://simracingsetup.com/ea-sports-f1/f1-25-belgium-car-setup/",
            "clave_bibliografica": "simracingsetup_f1_25_spa_francorchamps",
        },
        "alcance": ALCANCE,
    },
    ("f1-25", "monza", "seco"): {
        "programa": "F1 25",
        "circuito": "Monza",
        "modo": "carrera",
        "clima": "seco",
        "valores": {
            "aleron_delantero": 0,
            "aleron_trasero": 0,
            "sesgo_de_freno_pct": 55,
            "diferencial_con_acelerador_pct": 75,
            "diferencial_sin_acelerador_pct": 25,
        },
        "cita": (
            "«There is really no other way to go than 0 on both front and rear "
            "wings»; «A pretty neutral brake bias of 55 % is ideal at Monza»"),
        "fuente": {
            "titulo": "F1 25 Monza Car Setup: Full Setup & Guide",
            "autor": "SimRacingSetup",
            "anio": 2025,
            "url": "https://simracingsetup.com/ea-sports-f1/f1-25-italy-car-setup/",
            "clave_bibliografica": "simracingsetup_f1_25_monza",
        },
        "alcance": ALCANCE,
    },
    ("f1-25", "baku", "seco"): {
        "programa": "F1 25",
        "circuito": "Baku",
        "modo": "carrera",
        "clima": "seco",
        "valores": {
            "aleron_delantero": 10,
            "aleron_trasero": 9,
            "sesgo_de_freno_pct": 54,
            "diferencial_con_acelerador_pct": 65,
            "diferencial_sin_acelerador_pct": 25,
        },
        "cita": (
            "«aerodynamics to 10 at the front and 9 for the rear wing»; «54 % on "
            "the brake bias»"),
        "fuente": {
            "titulo": "F1 25 Baku Car Setup: Full Setup & Guide",
            "autor": "SimRacingSetup",
            "anio": 2025,
            "url": "https://simracingsetup.com/ea-sports-f1/f1-25-azerbaijan-car-setup/",
            "clave_bibliografica": "simracingsetup_f1_25_baku",
        },
        "alcance": ALCANCE,
    },
    ("f1-25", "austin", "seco"): {
        "programa": "F1 25",
        "circuito": "Austin",
        "modo": "carrera",
        "clima": "seco",
        "valores": {
            "aleron_delantero": 35,
            "aleron_trasero": 35,
            "sesgo_de_freno_pct": 53,
            "diferencial_con_acelerador_pct": 65,
            "diferencial_sin_acelerador_pct": 30,
        },
        "cita": (
            "«I have the aero set to 35 at both front and rear»; «For the brakes "
            "bias, I have opted for 53 %»"),
        "fuente": {
            "titulo": "F1 25 Austin Car Setup: Full Setup & Guide",
            "autor": "SimRacingSetup",
            "anio": 2025,
            "url": "https://simracingsetup.com/ea-sports-f1/f1-25-united-states-car-setup/",
            "clave_bibliografica": "simracingsetup_f1_25_austin",
        },
        "alcance": ALCANCE,
    },
    ("f1-25", "las-vegas", "seco"): {
        "programa": "F1 25",
        "circuito": "Las Vegas",
        "modo": "carrera",
        "clima": "seco",
        "valores": {
            "aleron_delantero": 0,
            "aleron_trasero": 3,
            "sesgo_de_freno_pct": 55,
            "diferencial_con_acelerador_pct": 45,
            "diferencial_sin_acelerador_pct": 25,
        },
        "cita": (
            "«0 at the front and 3 at the rear»; «55 % bias will keep the car "
            "stable under braking»"),
        "fuente": {
            "titulo": "F1 25 Las Vegas Car Setup: Full Setup & Guide",
            "autor": "SimRacingSetup",
            "anio": 2025,
            "url": "https://simracingsetup.com/ea-sports-f1/f1-25-las-vegas-car-setup/",
            "clave_bibliografica": "simracingsetup_f1_25_las_vegas",
        },
        "alcance": ALCANCE,
    },
    ("f1-25", "lusail", "seco"): {
        "programa": "F1 25",
        "circuito": "Lusail",
        "modo": "carrera",
        "clima": "seco",
        "valores": {
            "aleron_delantero": 36,
            "aleron_trasero": 35,
            "sesgo_de_freno_pct": 53,
            "diferencial_con_acelerador_pct": 75,
            "diferencial_sin_acelerador_pct": 35,
        },
        "cita": (
            "«36 and 35»; «53 %»"),
        "fuente": {
            "titulo": "F1 25 Lusail Car Setup: Full Setup & Guide",
            "autor": "SimRacingSetup",
            "anio": 2025,
            "url": "https://simracingsetup.com/ea-sports-f1/f1-25-qatar-car-setup/",
            "clave_bibliografica": "simracingsetup_f1_25_lusail",
        },
        "alcance": ALCANCE,
    },
    ("f1-25", "abu-dhabi", "seco"): {
        "programa": "F1 25",
        "circuito": "Abu Dhabi",
        "modo": "carrera",
        "clima": "seco",
        "valores": {
            "aleron_delantero": 24,
            "aleron_trasero": 25,
            "sesgo_de_freno_pct": 54,
            "diferencial_con_acelerador_pct": 80,
            "diferencial_sin_acelerador_pct": 35,
        },
        "cita": (
            "«I've gone with 24 and 25»; «A brake bias of 54 % is pretty perfect "
            "for the majority of the lap»"),
        "fuente": {
            "titulo": "F1 25 Abu Dhabi Car Setup: Full Setup & Guide",
            "autor": "SimRacingSetup",
            "anio": 2025,
            "url": "https://simracingsetup.com/ea-sports-f1/f1-25-abu-dhabi-car-setup/",
            "clave_bibliografica": "simracingsetup_f1_25_abu_dhabi",
        },
        "alcance": ALCANCE,
    },
}


ALIAS_CIRCUITO = {
    "spa": "spa-francorchamps",
    "spa_francorchamps": "spa-francorchamps",
    "francorchamps": "spa-francorchamps",
}


#: Que clima del juego cae de que lado. La fuente publica «seco» y «lluvia»; el
#: paquete de sesion distingue seis estados.
#:
#: CUBIERTO ES SECO, Y NO ES UN DETALLE. La pista puede estar nublada y la
#: goma seguir siendo la de seco: lo que cambia el reglaje es el agua, no la
#: luz. De las veintisiete sesiones capturadas, veinticuatro son despejadas y
#: **tres cubiertas**; con «cubierto» del lado de la lluvia, esas tres se
#: compararian contra un reglaje que nadie usaria ahi.
CLIMA_ES_LLUVIA = {
    "lluvia ligera": True, "lluvia fuerte": True, "tormenta": True,
    "despejado": False, "nubes": False, "cubierto": False,
}


def es_lluvia(clima: str | None) -> bool | None:
    """Si este clima pide un reglaje de agua. `None` cuando no se sabe."""

    if not clima:
        return None
    return CLIMA_ES_LLUVIA.get(clima.strip().lower())


def referencia_de(circuito: str | None, programa: str = "F1 25",
                  clima: str | None = None) -> dict | None:
    """La referencia aplicable a esta pista y este clima, o ``None``.

    ELIGE POR CLIMA Y, SI NO HAY, DEVUELVE LA QUE HAY DECLARANDOLO. Una pista
    sin referencia de agua no se queda sin nada: se muestra la de seco y se
    dice que lo es, porque la alternativa ---no mostrar nada--- esconde tambien
    lo que si se sabe. Lo que no se hace nunca es presentar una por la otra.
    """

    if not circuito:
        return None
    clave_circuito = circuito.strip().lower().replace(" ", "-")
    clave_circuito = ALIAS_CIRCUITO.get(clave_circuito, clave_circuito)
    clave_programa = programa.strip().lower().replace(" ", "-")

    fichas = [f for (prog, circ, _clima), f in REFERENCIAS.items()
              if prog == clave_programa and circ == clave_circuito]
    if not fichas:
        return None

    llueve = es_lluvia(clima)
    quiere = "lluvia" if llueve else "seco"
    elegida = next((f for f in fichas if f["clima"] == quiere), None)
    otro_clima = None
    if elegida is None:
        elegida = fichas[0]
        if llueve is not None and elegida["clima"] != quiere:
            otro_clima = ("No hay referencia de %s para esta pista: la que se "
                          "muestra es de %s" % (quiere, elegida["clima"]))

    copia = {
        **elegida,
        "valores": dict(elegida["valores"]),
        "fuente": dict(elegida["fuente"]),
    }
    if otro_clima:
        copia["otro_clima"] = otro_clima
    return copia
