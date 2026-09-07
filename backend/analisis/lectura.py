# -*- coding: utf-8 -*-
"""Lectura de series desde el contrato interno, para las herramientas de analisis.

Vive aparte porque **no es de ninguna herramienta**. Traer las muestras de una
sesion acotadas a un vehiculo y una corrida, y agruparlas por vuelta arrastrando
el ultimo valor de cada canal, es lo que necesitan todas: las curvas, las
frenadas, la traccion y la degradacion.

Tenerlo dentro de una de ellas obligaba a las demas a importarle una funcion
privada, que es la senal de que la pieza estaba en el lugar equivocado.

Por que se arrastra el ultimo valor
-----------------------------------
Los canales no llegan juntos: la distancia viene en un paquete y la aceleracion
lateral en otro, con marcas de tiempo que no coinciden. Esperar a que coincidan
descartaria casi todo. Se emite una muestra por cada lectura de **distancia**
---que es el eje sobre el que el analisis trabaja--- arrastrando el ultimo valor
conocido de los demas. Es lo mismo que hace el anotador en vivo, y por lo mismo.
"""

from __future__ import annotations

SENAL_NUMERO = "lap_number"
SENAL_DISTANCIA = "lap_distance"
SENAL_LATERAL = "g_force_lateral"
SENAL_VELOCIDAD = "speed"
SENAL_FRENO = "brake_position"


def leer(cursor, fuente: str, session_id: str,
          contexto: tuple[str | None, str | None, str | None],
          senales: tuple[str, ...]) -> list[tuple]:
    conductor, vehiculo, corrida = contexto
    marcador = ",".join(["%s"] * len(senales))
    cursor.execute(
        f"""select timestamp, signal_name, value_numeric
            from telemetry_messages
            where source_type = %s and session_id = %s
              and driver_id is not distinct from %s
              and vehicle_id is not distinct from %s
              and replay_run_id is not distinct from %s
              and signal_name in ({marcador})
              and value_numeric is not null
            order by timestamp""",
        (fuente, session_id, conductor, vehiculo, corrida, *senales),
    )
    return cursor.fetchall()


def muestras_por_vuelta(filas: list[tuple],
                        freno: str = SENAL_FRENO) -> dict[int, list[dict]]:
    """Agrupa por vuelta las muestras con distancia, lateral, velocidad y freno.

    `freno` nombra la senal con que esa fuente publica el freno, que no es la
    misma en las tres: el resultado la expone siempre bajo la clave `freno` para
    que las herramientas no repartan el nombre de la senal por todos lados.
    """

    por_vuelta: dict[int, list[dict]] = {}
    numero: int | None = None
    inicio: dict[int, object] = {}
    ultimo: dict[str, float] = {}

    for marca, nombre, valor in filas:
        if nombre == SENAL_NUMERO:
            numero = int(valor)
            continue
        if nombre != SENAL_DISTANCIA:
            ultimo[nombre] = float(valor)
            continue
        if numero is None:
            continue
        if numero not in inicio:
            inicio[numero] = marca
            por_vuelta[numero] = []
        por_vuelta[numero].append({
            "s": (marca - inicio[numero]).total_seconds(),
            "m": float(valor),
            "lateral": ultimo.get(SENAL_LATERAL),
            "velocidad": ultimo.get(SENAL_VELOCIDAD),
            "freno": ultimo.get(freno),
        })
    return por_vuelta
