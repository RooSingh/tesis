"""Capturador continuo de telemetria F1 25.

Queda escuchando el puerto y **captura solo lo que vaya pasando**. Cuando el
juego empieza a emitir, abre una captura; cuando se sale de la sesion y llega el
silencio, la cierra y vuelve a esperar la siguiente. Una sesion, un archivo, sin
intervencion del operador.

Por que no pregunta nada
------------------------
Un metadato tipeado a mano puede contradecir a los datos; uno leido del flujo no.
Casi toda la procedencia de una captura esta en el propio protocolo: circuito,
longitud declarada, tipo de sesion, modo de juego, clima, temperaturas, ajuste de
dano y las diez ayudas de conduccion.

Incluso **el nombre del archivo se deriva del flujo** —fecha, circuito y modo—,
que es mas trazable que uno escrito a mano porque no puede estar equivocado.

Lo unico que el protocolo no puede declarar es el contexto humano. Se resuelve
sin preguntar: la conformidad de un segundo conductor se asume, igual que en una
partida compartida, y se registra unicamente que hubo pantalla dividida, cosa que
el flujo si declara. Si mas adelante hace falta agregar una nota, los metadatos
se regeneran desde el crudo sin volver a conducir.

Patron de derivacion
--------------------
El flujo se escribe crudo a disco tal como llega, y en paralelo se decodifica, se
normaliza al contrato interno y se publica. Son dos salidas del mismo flujo. Si
el broker no esta disponible, **la grabacion continua igual** y queda registrado
que no se publico: perder la publicacion es recuperable, perder la captura no.
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

# Silencio que cierra una captura: se salio de la sesion o se pauso el juego.
SILENCIO_CIERRA_S = 8.0
# Duracion minima para conservar un archivo. Por debajo es un roce accidental
# del menu y no una sesion.
MINIMO_UTIL_S = 5.0

CIRCUITOS = {
    0: "melbourne", 2: "shanghai", 3: "sakhir", 4: "catalunya", 5: "monte-carlo",
    6: "montreal", 7: "silverstone", 9: "hungaroring", 10: "spa", 11: "monza",
    12: "singapur", 13: "suzuka", 14: "abu-dhabi", 15: "austin", 16: "interlagos",
    17: "spielberg", 19: "mexico", 20: "baku", 26: "zandvoort", 29: "miami",
    30: "las-vegas", 31: "lusail", 32: "jeddah",
}
MODOS_JUEGO = {5: "contrarreloj", 6: "pantalla-dividida"}
TIPOS_SESION = {
    1: "practica-1", 2: "practica-2", 3: "practica-3", 4: "practica-corta",
    5: "clasificacion-1", 6: "clasificacion-2", 7: "clasificacion-3",
    8: "clasificacion-corta", 9: "clasificacion-unica", 10: "carrera",
    11: "carrera-2", 12: "carrera-3", 13: "vuelta-de-instalacion",
    14: "sprint", 15: "sprint-2", 16: "sprint-3", 18: "contrarreloj",
}
CLIMA = {0: "despejado", 1: "nubes ligeras", 2: "cubierto",
         3: "lluvia ligera", 4: "lluvia fuerte", 5: "tormenta"}

# Ayudas que alteran la senal, con el valor que significa "apagada".
AYUDAS = {
    "steering_assist": 0, "braking_assist": 0, "gearbox_assist": 1,
    "pit_assist": 0, "pit_release_assist": 0, "ers_assist": 0,
    "drs_assist": 0, "dynamic_racing_line": 0,
}


def derivar_procedencia(sesion: dict | None, estado: dict | None,
                        cabecera: dict | None) -> dict:
    """Construye la procedencia leyendola del propio flujo."""

    if sesion is None:
        return {"disponible": False,
                "motivo": "no se recibio ningun paquete de sesion en la captura"}

    ayudas = {nombre: sesion.get(nombre) for nombre in AYUDAS}
    if estado is not None:
        ayudas["traction_control"] = estado.get("traction_control")
        ayudas["anti_lock_brakes"] = estado.get("anti_lock_brakes")
    activas = [n for n, v in ayudas.items() if v is not None and v != AYUDAS.get(n, 0)]

    # La pantalla dividida se declara en el flujo por dos vias independientes.
    segundo = cabecera is not None and cabecera.get("secondary_player_car_index", 255) != 255
    pantalla_dividida = sesion.get("game_mode") == 6 or segundo

    return {
        "disponible": True,
        "circuito_id": sesion["track_id"],
        "circuito": CIRCUITOS.get(sesion["track_id"], f"id-{sesion['track_id']}"),
        "longitud_declarada_m": sesion["track_length_m"],
        "tipo_sesion_id": sesion["session_type"],
        "tipo_sesion": TIPOS_SESION.get(sesion["session_type"], f"id-{sesion['session_type']}"),
        "modo_juego_id": sesion["game_mode"],
        "modo_juego": MODOS_JUEGO.get(sesion["game_mode"], f"id-{sesion['game_mode']}"),
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
        # La conformidad del segundo conductor se asume, como en una partida
        # compartida. Solo se registra que la sesion fue de dos.
        "pantalla_dividida": pantalla_dividida,
        "version_juego": (f"{cabecera['game_major_version']}."
                          f"{cabecera['game_minor_version']:02d}") if cabecera else None,
        "session_uid": cabecera["session_uid"] if cabecera else None,
    }


def nombre_derivado(procedencia: dict, inicio: datetime) -> str:
    """Nombre de archivo derivado del flujo, no escrito a mano."""

    marca = inicio.strftime("%Y%m%d_%H%M")
    if not procedencia.get("disponible"):
        return f"{marca}_sesion-no-declarada"
    partes = [marca, procedencia["circuito"], procedencia["tipo_sesion"]]
    if procedencia["sin_ayudas"]:
        partes.append("sin-ayudas")
    if procedencia["pantalla_dividida"]:
        partes.append("dos-conductores")
    return "_".join(partes)


class Publicador:
    """Publica al contrato si el broker esta disponible; si no, no estorba.

    Perder la publicacion es recuperable reproduciendo la captura; perder la
    captura no lo es. Por eso un broker ausente nunca detiene la grabacion.
    """

    def __init__(self, activo: bool) -> None:
        self.cliente = None
        self.mensajes = 0
        self.motivo = None
        if not activo:
            self.motivo = "desactivada por parametro"
            return
        try:
            import paho.mqtt.client as mqtt
            self.cliente = mqtt.Client()
            self.cliente.connect(MQTT_HOST, MQTT_PORT, 5)
            self.cliente.loop_start()
        except Exception as error:
            self.cliente = None
            self.motivo = f"broker no disponible: {type(error).__name__}"

    @property
    def activa(self) -> bool:
        return self.cliente is not None

    def publicar(self, decodificado: dict, inicio_utc: str) -> None:
        if self.cliente is None or decodificado["paquete"] not in ("car_telemetry", "lap_data"):
            return
        for mensaje in f1_25.mensajes_desde_paquete(decodificado, inicio_utc):
            self.cliente.publish(MQTT_TOPIC, json.dumps(mensaje), qos=1)
            self.mensajes += 1

    def cerrar(self) -> None:
        if self.cliente is not None:
            self.cliente.loop_stop()
            self.cliente.disconnect()


def capturar_sesion(sock: socket.socket, primer_datagrama: bytes,
                    destino: Path, publicador: Publicador) -> dict:
    """Graba una sesion completa, desde el primer datagrama hasta el silencio."""

    inicio_dt = datetime.now()
    inicio_utc = datetime.now(timezone.utc).isoformat()
    inicio = time.perf_counter()

    provisional = destino / f".captura_en_curso_{inicio_dt.strftime('%H%M%S')}.f1raw"
    conteo: dict[int, int] = {}
    sesion = estado = cabecera = None
    descartados = 0
    motivo = "silencio: se dejo de recibir"

    with f1_capture.EscritorCaptura(provisional) as escritor:
        datos = primer_datagrama
        while True:
            escritor.escribir(int((time.perf_counter() - inicio) * 1_000_000), datos)
            conteo[len(datos)] = conteo.get(len(datos), 0) + 1

            try:
                decodificado = f1_udp.decodificar(datos)
            except f1_udp.ErrorDecodificacion:
                descartados += 1
                decodificado = None

            if decodificado is not None:
                if cabecera is None:
                    cabecera = decodificado["cabecera"]
                if sesion is None and decodificado["paquete"] == "session":
                    sesion = decodificado["sesion"]
                elif estado is None and decodificado["paquete"] == "car_status":
                    estado = decodificado["vehiculo_propio"]
                publicador.publicar(decodificado, inicio_utc)

            try:
                datos, _ = sock.recvfrom(4096)
            except socket.timeout:
                break

    transcurrido = time.perf_counter() - inicio
    procedencia = derivar_procedencia(sesion, estado, cabecera)

    if transcurrido < MINIMO_UTIL_S:
        provisional.unlink(missing_ok=True)
        return {"conservada": False, "duracion_s": round(transcurrido, 2),
                "motivo": f"menos de {MINIMO_UTIL_S:.0f} s: no es una sesion"}

    ruta = destino / f"{nombre_derivado(procedencia, inicio_dt)}.f1raw"
    sufijo = 1
    while ruta.exists():
        sufijo += 1
        ruta = destino / f"{nombre_derivado(procedencia, inicio_dt)}_{sufijo}.f1raw"
    provisional.replace(ruta)

    extra = {
        "inicio_utc": inicio_utc,
        "duracion_s": round(transcurrido, 3),
        "motivo_corte": motivo,
        "tasa_total_por_s": round(sum(conteo.values()) / transcurrido, 2),
        # La frecuencia se mide, no se declara.
        "frecuencia_telemetria_hz_medida": round(
            conteo.get(f1_udp.PAQUETES[6]["tamano"], 0) / transcurrido, 3),
        "tipos_recibidos": {
            f1_udp.PAQUETES[i]["nombre"]: conteo[p["tamano"]]
            for i, p in f1_udp.PAQUETES.items() if p["tamano"] in conteo
        },
        "tamanos_fuera_de_especificacion": [
            t for t in conteo if not any(p["tamano"] == t for p in f1_udp.PAQUETES.values())
        ],
        "datagramas_no_decodificables": descartados,
        "procedencia": procedencia,
        "publicacion": {"activa": publicador.activa, "mensajes": publicador.mensajes,
                        "motivo": publicador.motivo},
        "version_decodificador": f1_udp.VERSION_DECODIFICADOR,
        "formato_udp_admitido": f1_udp.FORMATO_ADMITIDO,
    }
    f1_capture.escribir_metadatos(ruta, extra)
    extra["conservada"] = True
    extra["archivo"] = ruta.name
    return extra


def informar(r: dict) -> None:
    """Muestra el resultado de una sesion capturada."""

    if not r.get("conservada"):
        print(f"  descartada: {r['motivo']}")
        return
    p = r["procedencia"]
    print(f"  archivo    : {r['archivo']}")
    print(f"  duracion   : {r['duracion_s']:.1f} s   "
          f"datagramas: {sum(r['tipos_recibidos'].values())}   "
          f"telemetria: {r['frecuencia_telemetria_hz_medida']} Hz")
    if p["disponible"]:
        print(f"  sesion     : {p['circuito']} / {p['tipo_sesion']} / {p['clima']}, "
              f"pista {p['temperatura_pista_c']} C")
        print(f"  dano       : {'activado' if p['dano_activado'] else 'DESACTIVADO'}"
              f"   ayudas: {'ninguna' if p['sin_ayudas'] else ', '.join(p['ayudas_activas'])}")
        if p["pantalla_dividida"]:
            print(f"  conductores: dos, en pantalla dividida")
    else:
        print(f"  procedencia: no derivable, {p['motivo']}")
    if r["tamanos_fuera_de_especificacion"]:
        print(f"  ATENCION   : tamanos fuera de la especificacion: "
              f"{r['tamanos_fuera_de_especificacion']}")
    pub = r["publicacion"]
    print(f"  publicacion: {pub['mensajes']} mensajes" if pub["activa"]
          else f"  publicacion: no, {pub['motivo']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destino", type=Path, default=DESTINO_POR_DEFECTO)
    parser.add_argument("--sin-publicar", action="store_true",
                        help="Solo graba. Por defecto publica si el broker responde.")
    parser.add_argument("--silencio", type=float, default=SILENCIO_CIERRA_S,
                        help="Segundos sin datagramas que cierran una captura.")
    args = parser.parse_args()

    args.destino.mkdir(parents=True, exist_ok=True)
    publicador = Publicador(not args.sin_publicar)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 20777))
    sock.settimeout(args.silencio)

    print("Capturador en marcha. Escuchando el puerto 20777.")
    print("Jugue normalmente: cada sesion se graba en su propio archivo.")
    print(f"Publicacion: {'activa' if publicador.activa else publicador.motivo}")
    print("Ctrl+C para detener el capturador.\n")

    capturadas = 0
    try:
        while True:
            sock.settimeout(None)          # esperar indefinidamente una sesion
            datos, _ = sock.recvfrom(4096)
            sock.settimeout(args.silencio)  # dentro de la sesion, el silencio corta
            capturadas += 1
            print(f"[{datetime.now().strftime('%H:%M:%S')}] sesion detectada, grabando...")
            informar(capturar_sesion(sock, datos, args.destino, publicador))
            print()
    except KeyboardInterrupt:
        print(f"\nCapturador detenido. Sesiones grabadas en esta corrida: {capturadas}.")
    finally:
        sock.close()
        publicador.cerrar()


if __name__ == "__main__":
    main()
