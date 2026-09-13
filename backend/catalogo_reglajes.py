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
    "Referencia de comunidad publicada para el juego, no una medicion de este "
    "trabajo: no demuestra que sea optima ni que cause una mejora. Sirve para "
    "declarar contra que condicion externa se compara el reglaje observado"
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
    ("f1-25", "melbourne"): {
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
    ("f1-25", "shanghai"): {
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
    ("f1-25", "suzuka"): {
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
    ("f1-25", "sakhir"): {
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
    ("f1-25", "miami"): {
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
    ("f1-25", "imola"): {
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
    ("f1-25", "monte-carlo"): {
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
    ("f1-25", "catalunya"): {
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
    ("f1-25", "spielberg"): {
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
    ("f1-25", "silverstone"): {
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
    ("f1-25", "spa-francorchamps"): {
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
    ("f1-25", "monza"): {
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
    ("f1-25", "baku"): {
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
    ("f1-25", "austin"): {
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
    ("f1-25", "las-vegas"): {
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
    ("f1-25", "lusail"): {
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
    ("f1-25", "abu-dhabi"): {
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


def referencia_de(circuito: str | None, programa: str = "F1 25") -> dict | None:
    """Devuelve una copia de la referencia aplicable, o ``None``."""

    if not circuito:
        return None
    clave_circuito = circuito.strip().lower().replace(" ", "-")
    clave_circuito = ALIAS_CIRCUITO.get(clave_circuito, clave_circuito)
    clave_programa = programa.strip().lower().replace(" ", "-")
    referencia = REFERENCIAS.get((clave_programa, clave_circuito))
    if referencia is None:
        return None
    return {
        **referencia,
        "valores": dict(referencia["valores"]),
        "fuente": dict(referencia["fuente"]),
    }
