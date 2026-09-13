"""Punto de entrada del MVP del generador de telemetria.

Este modulo orquesta una primera cadena funcional del modo simulacion:

1. crea un estado inicial del vehiculo,
2. avanza el tiempo en pasos simples,
3. actualiza el estado del vehiculo,
4. consulta al scheduler que senales toca emitir,
5. construye los mensajes correspondientes,
6. los imprime por consola,
7. y los publica por MQTT.

La ejecucion requiere un broker MQTT accesible en la configuracion local. El
generador sigue siendo una fuente simulada: MQTT solo transporta los mensajes
hacia el resto de la arquitectura.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

import paho.mqtt.client as mqtt

from backend.config import MQTT_HOST, MQTT_PORT, MQTT_TOPIC

from telemetry_generator.message_builder import construir_mensaje_senal
from telemetry_generator.scheduler import SignalScheduler
from telemetry_generator.signals import aplicar_escenario_demostrativo, actualizar_estado_basico
from telemetry_generator.state import TelemetryState


# EL DESTINO SALE DE `backend.config` Y NO SE ESCRIBE AQUI.
#
# Estaba puesto a mano: host `localhost`, puerto y topico literales. Mientras
# todo corria suelto en una maquina eso coincidia con la realidad por
# casualidad. Desde que la aplicacion corre en contenedor el intermediario se
# llama `mosquitto`, de modo que el generador **no se conecta**: es la unica
# pieza del proyecto que no lee la configuracion comun.

#: Calidad de servicio. UNO, como los otros cuatro publicadores del proyecto.
#:
#: Estaba en cero, que es el valor por omision de `publish()` cuando nadie lo
#: pide. Es exactamente la configuracion que le costo a esta tesis 107.265
#: filas ---el 5,9 %--- y que `scripts/republicar_captura.py` documenta en su
#: cabecera. Medido el 2026-09-13 sobre la Raspberry, aqui costaba mas: de
#: 51.000 mensajes llegaron 42.889, un 15,9 % perdido.
CALIDAD_DE_SERVICIO = 1

#: Cada cuantos mensajes se espera la confirmacion. Ni por mensaje ---seria una
#: ida y vuelta por cada uno--- ni nunca ---la cola del cliente creceria sin
#: limite---. Es el mismo criterio y el mismo numero que `republicar_captura`.
VENTANA_SIN_CONFIRMAR = 1000


def crear_estado_inicial() -> TelemetryState:
    """Crea un estado inicial simple para el modo simulacion."""

    return TelemetryState(
        timestamp="2026-07-01T15:30:12.120000Z",
        vehicle_id="demo_car_01",
        driver_id="demo_driver_01",
        session_id="demo_session_01",
        lap_id="demo_sequence_01",
        sector_id="demo_sector_01",
        speed=100.0,
        wheel_speed_fl=100.0,
        wheel_speed_fr=100.0,
        wheel_speed_rl=100.0,
        wheel_speed_rr=100.0,
        steer_angle=0.0,
        accel_x=0.0,
        accel_y=0.0,
        yaw_rate=0.0,
        brake_pressed=False,
        gas_pedal=65.0,
    )


def _sumar_milisegundos_a_timestamp(timestamp_iso: str, delta_ms: int) -> str:
    """Suma milisegundos a un timestamp ISO 8601 en UTC.

    Esta funcion permite que el tiempo visible del mensaje acompañe el avance
    del scheduler y del estado interno, evitando que la simulacion muestre un
    reloj fijo mientras el tiempo logico del generador si avanza.
    """

    base = datetime.fromisoformat(timestamp_iso.replace("Z", "+00:00"))
    nuevo = base + timedelta(milliseconds=delta_ms)
    return nuevo.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _formatear_mensaje_resumido(mensaje: dict) -> str:
    """Devuelve una representacion mas legible del mensaje para consola."""

    timestamp = mensaje["timestamp"]
    signal_name = mensaje["signal_name"]
    value = mensaje["value"]
    unit = mensaje["unit"]
    can_id = mensaje["metadata"]["can_id"]

    if isinstance(value, bool):
        value = str(value)
    elif isinstance(value, float):
        value = round(value, 3)

    return f"- {signal_name:<15} | t={timestamp} | valor={value:<8} {unit:<6} | can_id={can_id}"


def ejecutar_ciclos_simulados(cantidad_ciclos: int = 6_000, paso_ms: int = 10) -> None:
    """Ejecuta la secuencia demostrativa de 60 segundos del generador MVP.

    Parametros:
    - cantidad_ciclos: cantidad de iteraciones del flujo. Por defecto cubre
      los 60 segundos completos de la demostracion.
    - paso_ms: tamano del paso temporal por ciclo.
    """

    estado = crear_estado_inicial()
    scheduler = SignalScheduler()
    cliente_mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    cliente_mqtt.connect(MQTT_HOST, MQTT_PORT, 60)
    # EL BUCLE DE RED HACE FALTA PARA QUE LA CALIDAD UNO SIGNIFIQUE ALGO. Sin
    # un hilo que atienda el zocalo no hay confirmaciones que recibir, y lo que
    # se pidio con calidad uno queda esperando a nadie.
    cliente_mqtt.loop_start()

    tiempo_actual_ms = 0
    publicados = 0
    ultimo_envio = None
    comienzo = time.perf_counter()

    for ciclo in range(cantidad_ciclos):

        # Actualizamos el timestamp visible del estado para que refleje el
        # tiempo actual de simulacion.
        estado.timestamp = _sumar_milisegundos_a_timestamp(
            "2026-07-01T15:30:12.120000Z", tiempo_actual_ms
        )

        # 1. Aplicamos la fase temporal y actualizamos el estado del vehiculo.
        aplicar_escenario_demostrativo(estado, tiempo_actual_ms)
        actualizar_estado_basico(estado, paso_ms=paso_ms)

        # 2. Preguntamos al scheduler que senales toca emitir ahora.
        senales = scheduler.obtener_senales_a_emitir(tiempo_actual_ms)

        # 3. Construimos y publicamos los mensajes correspondientes.
        for signal_name in senales:
            mensaje = construir_mensaje_senal(estado, signal_name)
            ultimo_envio = cliente_mqtt.publish(
                MQTT_TOPIC, json.dumps(mensaje), qos=CALIDAD_DE_SERVICIO)
            publicados += 1
            if publicados % VENTANA_SIN_CONFIRMAR == 0:
                ultimo_envio.wait_for_publish(timeout=30)

        tiempo_actual_ms += paso_ms

        # 4. EL TIEMPO LOGICO TIENE QUE DURAR LO QUE DICE DURAR.
        #
        # Sin esta espera el bucle corria a la velocidad de la maquina: los
        # sesenta segundos de la maniobra salieron en 1,886 s sobre la
        # Raspberry, y cada señal se emitio **treinta y dos veces** mas rapido
        # que su frecuencia declarada ---las velocidades de rueda a 3.181 Hz en
        # lugar de 100---. Un bus CAN de chasis a 500 kbit/s transporta unas
        # 3.846 tramas por segundo en total; esto emitia 27.041.
        #
        # Lo que se perdia no era solo el 15,9 % de los mensajes que el
        # intermediario descartaba ---y hacia bien, porque su trabajo es
        # proteger a un consumidor mas lento---: se perdia **la frecuencia**,
        # que es lo que la tabla A.1 del informe declara señal por señal y lo
        # que el planificador de la seccion 8.4 existe para respetar.
        #
        # SE CUENTA CONTRA EL COMIENZO Y NO SE DUERME UN RATO FIJO POR CICLO.
        # Un `sleep(paso)` acumula el error de cada espera y el ritmo real
        # termina por debajo del pedido. Es la misma correccion que ya lleva
        # `scripts/republicar_captura.py`: lo que se atrasa un ciclo lo
        # recupera el siguiente.
        debido = (tiempo_actual_ms / 1000.0)
        atraso = debido - (time.perf_counter() - comienzo)
        if atraso > 0:
            time.sleep(atraso)

    # La ultima confirmacion importa: sin ella el proceso puede terminar antes
    # de que el intermediario reciba la cola pendiente.
    if ultimo_envio is not None:
        ultimo_envio.wait_for_publish(timeout=60)
    cliente_mqtt.loop_stop()
    cliente_mqtt.disconnect()
    print(f"\npublicados : {publicados:,} mensajes en "
          f"{time.perf_counter() - comienzo:.1f} s")


if __name__ == "__main__":
    ejecutar_ciclos_simulados()
