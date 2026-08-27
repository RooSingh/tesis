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

ANALYZER_VERSION = "day22-session-analysis-v1"

# Longitud oficial del circuito de Silverstone, usada como referencia para validar
# la distancia derivada. Se guarda junto al resultado porque otra sesion tendria
# otra referencia y la validacion dejaria de tener sentido.
LONGITUD_SILVERSTONE_M = 5891.0

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
    el cronometraje oficial. No se derivan de las coordenadas, cuyo muestreo a
    3,7 Hz deja huecos de decenas de metros.

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


def evaluar_calidad(muestras_por_senal: dict[str, list], longitud_referencia_m: float | None = None) -> dict:
    """Describe la cobertura de la muestra y el hueco temporal mayor.

    Existe para que ninguna metrica pueda leerse sin saber sobre cuantas muestras
    se apoya. Una vuelta con la mitad de los datos produce agregados con la misma
    forma que una completa, y sin esta declaracion resultarian indistinguibles.
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
    if longitud_referencia_m:
        calidad["longitud_referencia_m"] = longitud_referencia_m
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


def validar_distancia(distancia_m: float | None, longitud_referencia_m: float) -> dict:
    """Compara la distancia derivada contra la longitud conocida del circuito.

    Es la validacion "contra si misma" que recomienda la documentacion de FastF1:
    en vez de presentar la distancia como exacta, se publica su desvio respecto de
    una referencia independiente. Una vuelta de boxes o interrumpida se apartara, y
    ese desvio es informacion util y no un error a ocultar.
    """
    if distancia_m is None or not longitud_referencia_m:
        return {"distancia_validada": False}
    desvio = (distancia_m - longitud_referencia_m) / longitud_referencia_m * 100
    return {
        "distancia_validada": True,
        "distancia_referencia_m": longitud_referencia_m,
        "distancia_desvio_pct": round(desvio, 2),
    }
