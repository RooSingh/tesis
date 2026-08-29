"""Capturador de telemetria F1 25: graba el flujo crudo y opcionalmente lo publica.

Patron de derivacion
--------------------
El flujo entrante se escribe **crudo a disco** tal como llega, y en paralelo se
decodifica, se normaliza al contrato interno y se publica por MQTT. Son dos
salidas del mismo flujo, no dos corridas distintas: si se grabara en una corrida
y se publicara en otra, no serian los mismos datos y la comparacion entre
operacion en vivo y reproduccion perderia sentido.

La publicacion se puede apagar. Grabar nunca.

Por que el crudo se guarda antes de interpretarlo
-------------------------------------------------
Una captura depende de una sesion efectivamente conducida y **no se puede
repetir a voluntad**. Guardar los datagramas antes de interpretarlos permite
volver a decodificar la misma sesion con un decodificador corregido, o leer un
paquete que hoy no se decodifica, sin volver a conducir.

Es el mismo criterio con que el trabajo conserva los registros crudos del bus
CAN en lugar de guardar solo las senales ya decodificadas.

Procedencia
-----------
Casi toda la procedencia de una captura **esta en el propio flujo**: circuito,
longitud declarada, tipo de sesion, modo de juego, clima, temperaturas y las diez
ayudas de conduccion. Se deriva de ahi y no se pregunta.

Un metadato leido del flujo no puede contradecir a los datos; uno tipeado a mano
si. Solo se preguntan las tres cosas que el protocolo no puede saber, que son de
contexto humano.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters import f1_25
from backend import f1_capture, f1_udp
from backend.config import MQTT_HOST, MQTT_PORT, MQTT_TOPIC

DESTINO_POR_DEFECTO = ROOT / "datasets" / "f1_25" / "capturas"

# Se corta cuando dejan de llegar datagramas por este lapso, es decir cuando se
# sale de la sesion. Evita tener que volver a la computadora para detenerla.
SILENCIO_POR_DEFECTO_S = 8.0

CIRCUITOS = {
    0: "Melbourne", 2: "Shanghai", 3: "Sakhir", 4: "Catalunya", 5: "Monte Carlo",
    6: "Montreal", 7: "Silverstone", 9: "Hungaroring", 10: "Spa-Francorchamps",
    11: "Monza", 12: "Singapore", 13: "Suzuka", 14: "Abu Dhabi", 15: "Austin",
    16: "Interlagos", 17: "Spielberg", 19: "Mexico City", 20: "Baku",
    26: "Zandvoort", 29: "Miami", 30: "Las Vegas", 31: "Lusail", 32: "Jeddah",
}
MODOS_JUEGO = {5: "contrarreloj", 6: "pantalla dividida"}
CLIMA = {0: "despejado", 1: "nubes ligeras", 2: "cubierto",
         3: "lluvia ligera", 4: "lluvia fuerte", 5: "tormenta"}

# Ayudas que alteran la senal, con el valor que significa "apagada".
AYUDAS = {
    "steering_assist": 0, "braking_assist": 0, "gearbox_assist": 1,
    "pit_assist": 0, "pit_release_assist": 0, "ers_assist": 0,
    "drs_assist": 0, "dynamic_racing_line": 0,
}


def preguntar_contexto_humano() -> dict:
    """Pregunta lo unico que el protocolo no puede declarar.

    Son tres datos de contexto humano. Todo lo demas se deriva del flujo, de modo
    que no puede quedar en desacuerdo con los datos.
    """

    print("Contexto que el flujo no puede declarar:")
    etiqueta = input("  etiqueta de la captura (por ejemplo C1, o una descripcion): ").strip()
    video = input("  se esta grabando video de la pantalla? (s/n): ").strip().lower()
    segundo = input("  hay un segundo conductor? si lo hay, indique su conformidad (enter si no): ").strip()
    return {
        "etiqueta": etiqueta or None,
        "video_grabado": video.startswith("s"),
        "segundo_conductor": segundo or None,
    }


def derivar_procedencia(sesion: dict | None, estado: dict | None) -> dict:
    """Construye la procedencia leyendola del propio flujo."""

    if sesion is None:
        return {"disponible": False,
                "motivo": "no se recibio ningun paquete de sesion durante la captura"}

    ayudas = {nombre: sesion.get(nombre) for nombre in AYUDAS}
    if estado is not None:
        ayudas["traction_control"] = estado.get("traction_control")
        ayudas["anti_lock_brakes"] = estado.get("anti_lock_brakes")

    activas = [n for n, v in ayudas.items()
               if v is not None and v != AYUDAS.get(n, 0)]

    return {
        "disponible": True,
        "circuito_id": sesion["track_id"],
        "circuito": CIRCUITOS.get(sesion["track_id"], "desconocido"),
        "longitud_declarada_m": sesion["track_length_m"],
        "tipo_sesion": sesion["session_type"],
        "modo_juego_id": sesion["game_mode"],
        "modo_juego": MODOS_JUEGO.get(sesion["game_mode"], "otro"),
        "clima": CLIMA.get(sesion["weather"], "desconocido"),
        "temperatura_pista_c": sesion["track_temperature_c"],
        "temperatura_aire_c": sesion["air_temperature_c"],
        "vueltas_totales": sesion["total_laps"],
        "dificultad_ia": sesion["ai_difficulty"],
        "juego_en_red": sesion["network_game"],
        "dano_activado": sesion["car_damage_setting"],
        "inicio_sector2_m": sesion["sector2_lap_distance_start_m"],
        "inicio_sector3_m": sesion["sector3_lap_distance_start_m"],
        "ayudas": ayudas,
        "ayudas_activas": activas,
        "sin_ayudas": not activas,
    }


def capturar(ruta: Path, contexto: dict, publicar: bool,
             duracion_s: float | None, silencio_s: float) -> dict:
    """Escucha el socket, graba el crudo y opcionalmente publica al contrato."""

    cliente = None
    if publicar:
        import paho.mqtt.client as mqtt
        cliente = mqtt.Client()
        cliente.connect(MQTT_HOST, MQTT_PORT, 60)
        cliente.loop_start()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 20777))
    sock.settimeout(silencio_s)

    conteo: dict[int, int] = {}
    sesion = estado = None
    publicados = descartados = 0
    inicio_utc = datetime.now(timezone.utc).isoformat()
    inicio = time.perf_counter()
    limite = inicio + duracion_s if duracion_s else None
    motivo_corte = "duracion cumplida"

    print(f"\nEscuchando el puerto 20777. Entre a pista para que el juego emita.")
    print(f"Se corta solo tras {silencio_s:.0f} s sin datagramas, o con Ctrl+C.\n")

    try:
        with f1_capture.EscritorCaptura(ruta) as escritor:
            while limite is None or time.perf_counter() < limite:
                try:
                    datos, _ = sock.recvfrom(4096)
                except socket.timeout:
                    motivo_corte = "silencio: se dejo de recibir"
                    break

                escritor.escribir(int((time.perf_counter() - inicio) * 1_000_000), datos)
                conteo[len(datos)] = conteo.get(len(datos), 0) + 1

                # La procedencia se toma del primer paquete de cada tipo.
                if sesion is None and len(datos) == f1_udp.PAQUETES[1]["tamano"]:
                    sesion = f1_udp.decodificar(datos)["sesion"]
                elif estado is None and len(datos) == f1_udp.PAQUETES[7]["tamano"]:
                    estado = f1_udp.decodificar(datos)["vehiculo_propio"]

                if not publicar:
                    continue
                try:
                    decodificado = f1_udp.decodificar(datos)
                except f1_udp.ErrorDecodificacion:
                    descartados += 1
                    continue
                if decodificado["paquete"] not in ("car_telemetry", "lap_data"):
                    continue
                for mensaje in f1_25.mensajes_desde_paquete(decodificado, inicio_utc):
                    cliente.publish(MQTT_TOPIC, json.dumps(mensaje), qos=1)
                    publicados += 1
    except KeyboardInterrupt:
        motivo_corte = "interrumpida por el operador"
    finally:
        sock.close()
        if cliente is not None:
            cliente.loop_stop()
            cliente.disconnect()

    transcurrido = time.perf_counter() - inicio
    datagramas = sum(conteo.values())

    # La frecuencia se mide, no se declara: es la unica forma de que no mienta.
    tasa_telemetria = conteo.get(f1_udp.PAQUETES[6]["tamano"], 0) / transcurrido

    extra = {
        "inicio_utc": inicio_utc,
        "duracion_s": round(transcurrido, 3),
        "motivo_corte": motivo_corte,
        "tasa_total_por_s": round(datagramas / transcurrido, 2) if transcurrido else 0,
        "frecuencia_telemetria_hz_medida": round(tasa_telemetria, 3),
        "tipos_recibidos": {
            f1_udp.PAQUETES[i]["nombre"]: conteo[t]
            for i, p in f1_udp.PAQUETES.items()
            for t in [p["tamano"]] if t in conteo
        },
        "tamanos_fuera_de_especificacion": [
            t for t in conteo
            if not any(p["tamano"] == t for p in f1_udp.PAQUETES.values())
        ],
        "procedencia": derivar_procedencia(sesion, estado),
        "contexto_humano": contexto,
        "publicacion": {"activa": publicar, "mensajes": publicados,
                        "datagramas_descartados": descartados},
        "version_decodificador": f1_udp.VERSION_DECODIFICADOR,
        "formato_udp_admitido": f1_udp.FORMATO_ADMITIDO,
    }
    return extra


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nombre", help="Nombre del archivo, sin extension.")
    parser.add_argument("--destino", type=Path, default=DESTINO_POR_DEFECTO)
    parser.add_argument("--duracion", type=float, default=None,
                        help="Segundos a capturar. Sin esto, corta por silencio.")
    parser.add_argument("--silencio", type=float, default=SILENCIO_POR_DEFECTO_S,
                        help="Segundos sin datagramas que cortan la captura.")
    parser.add_argument("--publicar", action="store_true",
                        help="Ademas de grabar, publica al contrato por MQTT.")
    parser.add_argument("--sin-preguntas", action="store_true",
                        help="Omite el contexto humano. Se puede completar despues.")
    args = parser.parse_args()

    contexto = {} if args.sin_preguntas else preguntar_contexto_humano()

    args.destino.mkdir(parents=True, exist_ok=True)
    nombre = args.nombre or f"captura_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    ruta = args.destino / f"{nombre}.f1raw"

    extra = capturar(ruta, contexto, args.publicar, args.duracion, args.silencio)
    meta = f1_capture.escribir_metadatos(ruta, extra)

    p = extra["procedencia"]
    print(f"\narchivo    : {ruta}")
    print(f"corte      : {extra['motivo_corte']}")
    print(f"duracion   : {extra['duracion_s']:.1f} s")
    print(f"datagramas : {sum(extra['tipos_recibidos'].values())}")
    print(f"tamano     : {ruta.stat().st_size / 1_000_000:.2f} MB")
    print(f"frecuencia medida de telemetria: {extra['frecuencia_telemetria_hz_medida']} Hz")
    if extra["tamanos_fuera_de_especificacion"]:
        print(f"ATENCION: tamanos fuera de la especificacion: "
              f"{extra['tamanos_fuera_de_especificacion']}")
    if p["disponible"]:
        print(f"\nprocedencia derivada del flujo:")
        print(f"  circuito   : {p['circuito']} ({p['longitud_declarada_m']} m)")
        print(f"  modo       : {p['modo_juego']}")
        print(f"  clima      : {p['clima']}, pista {p['temperatura_pista_c']} C")
        print(f"  dano       : {'activado' if p['dano_activado'] else 'DESACTIVADO'}")
        print(f"  ayudas     : {'ninguna activa' if p['sin_ayudas'] else ', '.join(p['ayudas_activas'])}")
    else:
        print(f"\nprocedencia no derivable: {p['motivo']}")
    if extra["publicacion"]["activa"]:
        print(f"\npublicados : {extra['publicacion']['mensajes']} mensajes al contrato")
    print(f"\nmetadatos  : {meta.name}")


if __name__ == "__main__":
    main()
