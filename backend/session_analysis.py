"""Analisis automatico por vuelta y por stint sobre una corrida de replay.

Estructura del modulo
---------------------
Las funciones de calculo son puras: reciben listas de muestras y devuelven
metricas, sin tocar la base. Estan separadas a proposito, porque las reglas que
definen cada metrica son decisiones metodologicas de la tesis y deben poder
leerse, explicarse y probarse en un solo lugar en vez de quedar dentro de una
consulta SQL.

Niveles de evidencia
--------------------
El resultado separa las metricas en tres compartimentos, igual que la tabla que
las guarda:

- `metricas_oficiales`: proviene de OpenF1 sin transformar. Tiempos por sector,
  velocidades de intermedios y trampa, y estado de los minisectores.
- `metricas_derivadas`: la calcula este proyecto a partir de la telemetria
  replicada.
- `calidad`: describe los limites del propio resultado, para que ninguna metrica
  se lea sin saber sobre cuantas muestras se apoya.
"""

from __future__ import annotations

from datetime import datetime

from backend.track_reference import (  # noqa: F401  (reexportado a proposito)
    REFERENCIA_TIPO,
    referencia_no_disponible,
    resolver_referencia_circuito,
)

ANALYZER_VERSION = "day23-session-analysis-v2"

# La longitud del circuito contra la que se valida la distancia derivada ya no es
# una constante de este modulo. Vive en `backend/track_reference.py`, indexada por
# `circuit_key`, porque es un dato externo declarado y no una medicion del
# proyecto: una constante unica ataba el analisis a Silverstone y habria validado
# Spa-Francorchamps, 1.113 metros mas largo, contra la referencia equivocada.
# Se reexporta el resolvedor para que quien importe el analisis encuentre aqui la
# puerta de entrada.

# Codigos de estado de minisector de la senal de cronometraje oficial.
#
# El mapeo se valido contra los propios datos y no se tomo de documentacion
# externa: sobre las 827 vueltas de Silverstone `9947`, las 40 vueltas mas rapidas
# promedian 4,6 % de codigo 2051 y 38,8 % de 2049, mientras que las 40 mas lentas
# tienen exactamente 0 % de ambos. La vuelta mas rapida de la carrera alcanza 20 %
# de 2051. Esa relacion monotona con el tiempo de vuelta sostiene la lectura.
MINISECTOR_PURPURA = 2051   # mejor tiempo de la sesion en ese tramo
MINISECTOR_VERDE = 2049     # mejor tiempo personal en ese tramo
MINISECTOR_AMARILLO = 2048  # ni uno ni otro

# Umbral para considerar el acelerador a fondo. OpenF1 entrega `throttle` en
# porcentaje; se usa 95 en lugar de 100 porque el pedal rara vez marca el maximo
# exacto de forma sostenida.
UMBRAL_ACELERADOR_A_FONDO = 95.0

# Umbral de codigo de DRS a partir del cual el aleron esta abierto.
#
# Validado contra los propios datos, cruzando cada muestra de `drs_state_code` con
# la de `speed` del mismo instante sobre las 683.720 muestras de la carrera:
#
#   codigo 0 -> 109,7 km/h de media    codigo  9 -> 289,7 km/h
#   codigo 1 ->  99,2                  codigo 10 -> 296,0
#   codigo 2 ->  31,8                  codigo 11 -> 276,5
#   codigo 3 ->   3,9                  codigo 12 -> 294,3
#   codigo 8 -> 126,7                  codigo 14 -> 248,8
#
# La distribucion es bimodal con una frontera nitida: entre el codigo 8 y el 9 hay
# un salto de 163 km/h en la velocidad media. Eso identifica el limite sin depender
# de documentacion externa.
#
# Relacion con la documentacion de origen.
#
# La documentacion de OpenF1 (https://openf1.org/docs/) publica una tabla del campo
# `drs` y aclara que la tomo de FastF1. Esa tabla documenta 0 y 1 como apagado, 8
# como "Detected, eligible once in activation zone", y 10, 12 y 14 como encendido,
# pero **deja los valores 2, 3 y 9 marcados con "?"** y no menciona el 11.
#
# La medicion realizada aqui resuelve esos cuatro casos:
#
#   codigo  2 -> 31,8 km/h de media, mediana 0    => cerrado
#   codigo  3 ->  3,9 km/h de media, mediana 0    => cerrado
#   codigo  9 -> 289,7 km/h, mediana 298          => ABIERTO
#   codigo 11 -> 276,5 km/h, mediana 277          => ABIERTO
#
# Por eso el criterio se expresa como umbral y no como el conjunto {10, 12, 14} que
# figura en la documentacion: ese conjunto habria clasificado los codigos 9 y 11
# como aleron cerrado pese a su velocidad. El umbral cubre ademas cualquier codigo
# no documentado que aparezca en otra sesion.
DRS_CODIGO_MINIMO_ABIERTO = 9


def _valores(muestras: list[tuple[datetime, float | None, bool | None]]) -> list[float]:
    return [valor for _, valor, _ in muestras if valor is not None]


def resumir_minisectores(segmentos: list[int | None]) -> dict:
    """Cuenta el estado de los minisectores de una vuelta.

    Los minisectores son la unica fuente espacial de resolucion fina disponible:
    26 por vuelta en Silverstone, es decir unos 227 metros cada uno, informados por
    el cronometraje oficial. Ese numero es propio de cada circuito y no una
    constante del proyecto; `resolver_resolucion_minisector` lo deriva de la propia
    sesion. No se derivan de las coordenadas, cuyo muestreo a 3,7 Hz deja huecos de
    decenas de metros.

    Los valores nulos se cuentan aparte en vez de descartarse: un minisector sin
    dato no es un minisector amarillo.
    """
    presentes = [s for s in segmentos if s is not None]
    return {
        "minisectores_total": len(segmentos),
        "minisectores_con_dato": len(presentes),
        "minisectores_sin_dato": len(segmentos) - len(presentes),
        "minisectores_purpura": sum(1 for s in presentes if s == MINISECTOR_PURPURA),
        "minisectores_verde": sum(1 for s in presentes if s == MINISECTOR_VERDE),
        "minisectores_amarillo": sum(1 for s in presentes if s == MINISECTOR_AMARILLO),
    }


# Resolucion espacial de los minisectores
# ---------------------------------------
# Cuantos minisectores tiene una vuelta NO es una constante del proyecto: es un
# dato de cada circuito. Contando los propios `laps.json` importados, Silverstone
# declara 26 minisectores por vuelta, Suzuka tambien 26 y Spa-Francorchamps 28.
# Fijar el 26 dejaba a Spa con 7004/26 = 269,4 m de resolucion declarada cuando su
# valor real es 7004/28 = 250,1 m: un 7,7 % de error persistido como si fuera un
# hecho medido de la sesion.
#
# A diferencia de la longitud del circuito, este dato no necesita tabla externa
# alguna: la propia sesion lo publica en `segments_sector_1..3` de cada vuelta.
# Por eso vive aca, junto al analisis, y no en `track_reference`, que reune lo que
# el proyecto tuvo que declarar desde fuera.


def contar_minisectores_vuelta(vuelta: dict) -> int | None:
    """Cuenta los minisectores que declara una vuelta oficial.

    Devuelve `None` cuando alguno de los tres sectores no trae su lista de
    segmentos. Sumar solo los sectores presentes daria un total menor y creible:
    una vuelta a la que le falta el sector 3 se leeria como un circuito mas corto.
    """
    total = 0
    for sector in (1, 2, 3):
        segmentos = vuelta.get(f"segments_sector_{sector}")
        if not isinstance(segmentos, (list, tuple)) or not segmentos:
            return None
        total += len(segmentos)
    return total


def resolucion_minisector_no_disponible(motivo: str) -> dict:
    """Arma la declaracion de ausencia de resolucion espacial.

    Misma forma que el caso disponible, igual que hace `track_reference` con la
    longitud: quien lee el analisis encuentra siempre las mismas llaves y la
    ausencia se declara en vez de omitirse.
    """
    return {"disponible": False, "resolucion_m": None, "motivo": motivo}


def resolver_resolucion_minisector(
    conteos_por_vuelta: list[int | None],
    longitud_referencia_m: float | None,
) -> dict:
    """Deriva la resolucion espacial de los minisectores de la propia sesion.

    Se usa la MODA de los conteos por vuelta y no la primera vuelta ni el maximo.
    Los datos muestran vueltas con menos segmentos de los que tiene el circuito
    (Silverstone tiene 58 vueltas con 25 y 6 con 24 sobre 824 utiles), que son
    vueltas incompletas o con incidentes. La moda es robusta frente a esa cola; la
    primera vuelta puede caer justo en ella y el maximo se dispararia con cualquier
    vuelta anomala.

    El resultado publica el conteo detectado, cuantas vueltas se consideraron,
    cuantas sostienen la moda y la distribucion completa observada, para que el
    numero sea auditable sin volver a la base.

    Nunca se estima: sin vueltas con los tres sectores completos, o sin longitud de
    circuito declarada, se devuelve la declaracion de ausencia con su motivo.
    """
    utiles = [conteo for conteo in conteos_por_vuelta if conteo]
    if not utiles:
        return resolucion_minisector_no_disponible(
            "no hay vueltas con los tres sectores completos en esta sesion; "
            "no se puede derivar cuantos minisectores tiene el circuito"
        )

    distribucion: dict[int, int] = {}
    for conteo in utiles:
        distribucion[conteo] = distribucion.get(conteo, 0) + 1
    # Desempate determinista por el conteo menor. Un empate es patologico y queda
    # visible en `distribucion_observada`, que se publica entera.
    moda, vueltas_en_la_moda = sorted(
        distribucion.items(), key=lambda par: (-par[1], par[0])
    )[0]

    detalle = {
        "minisectores_por_vuelta": moda,
        "vueltas_consideradas": len(utiles),
        "vueltas_en_la_moda": vueltas_en_la_moda,
        "vueltas_descartadas_sin_tres_sectores": len(conteos_por_vuelta) - len(utiles),
        "distribucion_observada": {str(k): distribucion[k] for k in sorted(distribucion)},
        "derivacion": (
            "moda de len(segments_sector_1)+len(segments_sector_2)+len(segments_sector_3) "
            "sobre las vueltas de la propia sesion"
        ),
    }

    if not longitud_referencia_m:
        return {
            **resolucion_minisector_no_disponible(
                "hay minisectores detectados pero no hay longitud de circuito "
                "declarada para esta sesion; la resolucion en metros no se calcula"
            ),
            **detalle,
        }

    return {
        "disponible": True,
        "resolucion_m": round(longitud_referencia_m / moda, 1),
        "longitud_referencia_m": longitud_referencia_m,
        **detalle,
    }


def integrar_distancia_m(muestras_velocidad: list[tuple[datetime, float | None, bool | None]]) -> float | None:
    """Calcula la distancia recorrida integrando la velocidad sobre el tiempo.

    Se integra la velocidad en vez de sumar las distancias entre coordenadas
    consecutivas. Sumar cuerdas subestima el arco real porque a 3,7 Hz las muestras
    quedan a unos 10 metros y hasta 83 en los huecos, de modo que el recorrido se
    "corta" en cada curva. Medido sobre 30 vueltas de seis pilotos, ese metodo
    arroja 9,84 unidades por metro frente a los 10 de una escala decimetrica: un
    sesgo sistematico del 1,6 %.

    Se usa la regla del trapecio, que promedia la velocidad entre dos muestras.

    ADVERTENCIA: la documentacion de FastF1 desaconseja apoyar calculos posteriores
    en valores obtenidos por integracion, porque el error se acumula. El resultado
    es adecuado para comparar y graficar, y este modulo lo valida contra la
    longitud conocida del circuito en vez de presentarlo como exacto.
    """
    puntos = [(t, v) for t, v, _ in muestras_velocidad if v is not None]
    if len(puntos) < 2:
        return None
    metros = 0.0
    for (t0, v0), (t1, v1) in zip(puntos, puntos[1:]):
        dt = (t1 - t0).total_seconds()
        if dt <= 0:
            continue
        # Velocidad media del tramo, de km/h a m/s.
        metros += ((v0 + v1) / 2.0) / 3.6 * dt
    return metros


def evaluar_calidad(muestras_por_senal: dict[str, list], referencia_circuito: dict | None = None) -> dict:
    """Describe la cobertura de la muestra y el hueco temporal mayor.

    Existe para que ninguna metrica pueda leerse sin saber sobre cuantas muestras
    se apoya. Una vuelta con la mitad de los datos produce agregados con la misma
    forma que una completa, y sin esta declaracion resultarian indistinguibles.

    `referencia_circuito` es el bloque que devuelve
    `resolver_referencia_circuito`. Se copia entero, incluida la fuente, para que
    el resultado guarde contra que se valido y de donde salio esa cifra. Cuando la
    referencia no esta disponible tambien se copia: la ausencia se declara en vez
    de omitirse, porque un campo faltante se confunde con un descuido.
    """
    velocidad = muestras_por_senal.get("speed", [])
    tiempos = [t for t, _, _ in velocidad]
    hueco_max = 0.0
    for t0, t1 in zip(tiempos, tiempos[1:]):
        hueco_max = max(hueco_max, (t1 - t0).total_seconds())
    calidad = {
        "muestras_por_senal": {senal: len(v) for senal, v in sorted(muestras_por_senal.items())},
        "muestras_velocidad": len(velocidad),
        "hueco_maximo_segundos": round(hueco_max, 3),
    }
    if referencia_circuito is not None:
        calidad["longitud_referencia"] = dict(referencia_circuito)
        if referencia_circuito.get("referencia_disponible"):
            calidad["longitud_referencia_m"] = referencia_circuito.get("longitud_referencia_m")
    return calidad


def resumir_telemetria(muestras_por_senal: dict[str, list]) -> dict:
    """Agrega la telemetria de una ventana en metricas por senal.

    Devuelve `{}` si no hay muestras de velocidad: preferir un resultado vacio a
    uno construido sobre una ventana sin datos, que se leeria como una vuelta real
    con valores nulos.
    """
    velocidad = _valores(muestras_por_senal.get("speed", []))
    if not velocidad:
        return {}

    resumen: dict = {
        "velocidad_min_kph": min(velocidad),
        "velocidad_max_kph": max(velocidad),
        "velocidad_media_kph": round(sum(velocidad) / len(velocidad), 2),
    }

    acelerador = _valores(muestras_por_senal.get("throttle_position", []))
    if acelerador:
        a_fondo = sum(1 for v in acelerador if v >= UMBRAL_ACELERADOR_A_FONDO)
        resumen["acelerador_medio_pct"] = round(sum(acelerador) / len(acelerador), 2)
        resumen["acelerador_a_fondo_pct"] = round(a_fondo / len(acelerador) * 100, 2)
        resumen["acelerador_umbral_a_fondo"] = UMBRAL_ACELERADOR_A_FONDO

    freno = [b for _, _, b in muestras_por_senal.get("brake_applied", []) if b is not None]
    if freno:
        resumen["freno_aplicado_pct"] = round(sum(1 for b in freno if b) / len(freno) * 100, 2)

    marcha = _valores(muestras_por_senal.get("gear_selected", []))
    if marcha:
        resumen["marcha_maxima"] = int(max(marcha))
        resumen["marcha_media"] = round(sum(marcha) / len(marcha), 2)

    rpm = _valores(muestras_por_senal.get("engine_speed", []))
    if rpm:
        resumen["rpm_max"] = int(max(rpm))
        resumen["rpm_medio"] = int(sum(rpm) / len(rpm))

    drs = _valores(muestras_por_senal.get("drs_state_code", []))
    if drs:
        codigos: dict[str, int] = {}
        for valor in drs:
            clave = str(int(valor))
            codigos[clave] = codigos.get(clave, 0) + 1
        # Se conserva el histograma completo aunque la interpretacion este validada:
        # es el dato observado del que se deriva el porcentaje, y permite auditar la
        # clasificacion sin volver a la telemetria.
        resumen["drs_codigos"] = dict(sorted(codigos.items(), key=lambda par: int(par[0])))
        resumen["drs_abierto_pct"] = round(
            sum(1 for v in drs if int(v) >= DRS_CODIGO_MINIMO_ABIERTO) / len(drs) * 100, 2
        )
        resumen["drs_interpretacion_validada"] = True

    distancia = integrar_distancia_m(muestras_por_senal.get("speed", []))
    if distancia is not None:
        resumen["distancia_m"] = round(distancia, 1)
        resumen["distancia_metodo"] = "integracion de velocidad, regla del trapecio"
    return resumen


def validar_distancia(
    distancia_m: float | None,
    referencia_circuito: dict | float | None,
) -> dict:
    """Compara la distancia derivada contra la longitud declarada del circuito.

    Es la validacion "contra si misma" que recomienda la documentacion de FastF1:
    en vez de presentar la distancia como exacta, se publica su desvio respecto de
    una referencia independiente. Una vuelta de boxes o interrumpida se apartara, y
    ese desvio es informacion util y no un error a ocultar.

    `referencia_circuito` es el bloque de `resolver_referencia_circuito`. Se acepta
    tambien un numero suelto por comodidad de las pruebas.

    Cuando no hay longitud declarada para el circuito, la validacion **no se hace y
    se dice por que**. Antes bastaba con un `distancia_validada: False` mudo, que
    no distingue una vuelta sin muestras de un circuito sin referencia. Inventar
    una longitud seria peor todavia: el desvio saldria numerico y creible sobre una
    base falsa.
    """
    if isinstance(referencia_circuito, (int, float)):
        referencia_circuito = {
            "referencia_disponible": bool(referencia_circuito),
            "longitud_referencia_m": float(referencia_circuito) or None,
            "referencia_fuente": None,
        }
    referencia = referencia_circuito or referencia_no_disponible(
        "no se resolvio ninguna referencia de circuito para esta sesion"
    )

    if not referencia.get("referencia_disponible") or not referencia.get("longitud_referencia_m"):
        return {
            "distancia_validada": False,
            "distancia_validacion_motivo": referencia.get(
                "referencia_motivo", "longitud de circuito no declarada para esta sesion"
            ),
        }
    if distancia_m is None:
        return {
            "distancia_validada": False,
            "distancia_validacion_motivo": "sin distancia derivada en esta ventana",
        }

    longitud_referencia_m = referencia["longitud_referencia_m"]
    desvio = (distancia_m - longitud_referencia_m) / longitud_referencia_m * 100
    resultado = {
        "distancia_validada": True,
        "distancia_referencia_m": longitud_referencia_m,
        "distancia_desvio_pct": round(desvio, 2),
    }
    # La fuente viaja con el desvio: un porcentaje sin decir contra que se midio no
    # es defendible, y quien lea solo `metricas_derivadas` no vera la `calidad`.
    if referencia.get("referencia_fuente"):
        resultado["distancia_referencia_fuente"] = referencia["referencia_fuente"]
        resultado["distancia_referencia_tipo"] = referencia.get("referencia_tipo", REFERENCIA_TIPO)
    return resultado
