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
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters import f1_25
from backend import f1_capture, f1_udp
from backend.config import MQTT_HOST, MQTT_PORT, MQTT_TOPIC

DESTINO_POR_DEFECTO = ROOT / "datasets" / "f1_25" / "capturas"

#: Donde vive la eleccion de pilotos. Junto a las capturas y no en una
#: carpeta de configuracion: describe que se esta escuchando ahora mismo,
#: igual que el archivo provisional de la sesion en curso, y se mira en el
#: mismo lugar donde ya se mira todo lo demas de la escucha.
SELECCION_POR_DEFECTO = DESTINO_POR_DEFECTO / ".pilotos_elegidos.json"

# El puerto en que el juego emite su telemetria.
PUERTO_JUEGO = 20777

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
# Transcritos del apendice "Game Mode IDs".
MODOS_JUEGO = {
    4: "gran-premio", 5: "contrarreloj", 6: "pantalla-dividida",
    7: "online-personalizado", 15: "evento-semanal-online",
    17: "modo-historia", 27: "carrera-mi-equipo", 28: "carrera-piloto",
    29: "carrera-online", 30: "carrera-desafio", 75: "modo-historia-apxgp",
    127: "banco-de-pruebas",
}

# Transcrita del apendice "Session types" de la especificacion, no de memoria.
# La version anterior de esta tabla estaba corrida: nombraba "sprint-2" al 15,
# que es Carrera. El dato capturado era correcto; el nombre que se le ponia, no.
TIPOS_SESION = {
    0: "desconocida",
    1: "practica-1", 2: "practica-2", 3: "practica-3", 4: "practica-corta",
    5: "clasificacion-1", 6: "clasificacion-2", 7: "clasificacion-3",
    8: "clasificacion-corta", 9: "clasificacion-unica",
    10: "sprint-shootout-1", 11: "sprint-shootout-2", 12: "sprint-shootout-3",
    13: "sprint-shootout-corto", 14: "sprint-shootout-unico",
    15: "carrera", 16: "carrera-2", 17: "carrera-3", 18: "contrarreloj",
}

# Ajustes de realismo, con el nombre de cada valor. Se traducen porque la
# condicion experimental de una captura tiene que poder leerse sin la tabla al
# lado: lo que define a una captura no es el numero 3, es "simulacion".
AJUSTES = {
    "car_damage_setting": {0: "desactivado", 1: "reducido", 2: "estandar", 3: "simulacion"},
    "car_damage_rate": {0: "reducido", 1: "estandar", 2: "simulacion"},
    "collisions": {0: "desactivadas", 1: "sin-piloto-a-piloto", 2: "activadas"},
    "recovery_mode": {0: "ninguno", 1: "retrocesos", 2: "recuperacion-automatica"},
    "surface_type": {0: "simplificada", 1: "realista"},
    "low_fuel_mode": {0: "facil", 1: "dificil"},
    "tyre_temperature_model": {0: "solo-superficie", 1: "superficie-y-carcasa"},
    "pit_lane_tyre_sim": {0: "activada", 1: "desactivada"},
    "corner_cutting_stringency": {0: "regular", 1: "estricta"},
    "parc_ferme_rules": {0: "desactivadas", 1: "activadas"},
    "safety_car_setting": {0: "desactivado", 1: "reducido", 2: "estandar", 3: "aumentado"},
    "formation_lap": {0: "desactivada", 1: "activada"},
    "red_flags_setting": {0: "desactivadas", 1: "reducidas", 2: "estandar", 3: "aumentadas"},
    "equal_car_performance": {0: "cada-auto-como-es", 1: "rendimiento-igualado"},
}
CLIMA = {0: "despejado", 1: "nubes ligeras", 2: "cubierto",
         3: "lluvia ligera", 4: "lluvia fuerte", 5: "tormenta"}

# Ayudas que alteran la senal, con el valor que significa "apagada".
AYUDAS = {
    "steering_assist": 0, "braking_assist": 0, "gearbox_assist": 1,
    "pit_assist": 0, "pit_release_assist": 0, "ers_assist": 0,
    "drs_assist": 0, "dynamic_racing_line": 0,
}


def derivar_parrilla(participantes: dict | None) -> list[dict] | None:
    """Quien es cada vehiculo, leido del flujo.

    Va en la procedencia y **no en el contrato de telemetria**, porque no es una
    medicion: es identidad, y no cambia durante la sesion. Publicarla como senal
    guardaria el mismo nombre casi siete mil veces para decir veintidos cosas que
    nunca varian, y pondria texto en una tabla pensada para valores medidos.

    Los nombres son de piloto y no de persona. La especificacion lo declara por
    plataforma —en PlayStation el nombre es el del piloto salvo en partida LAN— y
    se verifico sobre la carrera capturada: la conductora humana aparece con
    `ai_controlled` en cero y el nombre del piloto que eligio.
    """

    if participantes is None:
        return None
    # Se recorren las veintidos posiciones y se conservan las que tienen nombre.
    #
    # **No se recorta por `num_active_cars`.** Ese campo cuenta los vehiculos que
    # siguen en carrera, no la longitud del arreglo: la especificacion declara que
    # el arreglo se indexa por indice de vehiculo, y las posiciones se mantienen
    # aunque un vehiculo abandone. En la carrera capturada el contador bajo de 20
    # a 18 mientras las veinte entradas conservaban su nombre, de modo que
    # recortar descartaba las dos ultimas posiciones —entre ellas la del vehiculo
    # propio, que era el indice 19— y la parrilla perdia justo al conductor.
    return [
        {
            "indice": indice,
            "nombre": v["name"],
            "numero": v["race_number"],
            "equipo": v["team"],
            "equipo_id": v["team_id"],
            "es_ia": bool(v["ai_controlled"]),
            "plataforma": v["platform"],
        }
        for indice, v in enumerate(participantes["vehiculos"])
        if v["name"]
    ]


class AyudasEnMarcha:
    """Acumula el control de traccion y el antibloqueo **del auto en marcha**.

    Estas dos ayudas no viajan en el paquete de sesion como las otras ocho: hay
    que leerlas del estado del auto, que llega muchas veces por segundo. Tomar la
    ultima lectura parecia resolver que en el menu llegan en cero, pero la ultima
    lectura de una captura tambien es de menu, porque llega despues de la bandera
    a cuadros.

    En la primera pasada de la prueba de dos conductores eso archivo el
    antibloqueo como activo. El canal lo mostro en cero durante los cinco giros
    de carrera y salto a uno en el segundo 423,82, cuatro segundos despues de la
    bandera a cuadros del 419,68. La pantalla de configuracion del juego decia
    "desactivado", y la pantalla tenia razon.

    Lo destapo una fotografia del menu, no el dato. Sin esa imagen el informe
    habria declarado que los dos conductores manejaron con ayudas distintas, que
    es justo la afirmacion que invalidaria la comparacion.

    Se archiva la **moda** y no la ultima lectura: un marco suelto no alcanza
    para cambiar lo que se declara que se condujo.
    """

    #: Eventos que cierran el intento en curso. Despues de cualquiera de los dos,
    #: lo que declaren los canales ya no es lo que se condujo.
    FIN_DE_LO_CONDUCIDO = frozenset({"CHQF", "SEND"})

    #: Eventos que abren un intento. Una captura puede contener varios.
    #:
    #: El juego emite sesion-iniciada y largada **en cada reinicio**, sin cambiar
    #: el identificador de sesion: una captura del 2026-09-01 tiene veinticuatro
    #: pares de estos con un unico `session_uid`. Sin reabrir la cuenta, el primer
    #: reinicio la cerraba para siempre y una carrera entera quedaba sin medir.
    INICIO_DE_INTENTO = frozenset({"SSTA", "LGOT"})

    def __init__(self) -> None:
        self._conteo: dict[tuple, int] = {}
        #: El ultimo intento que llego a tener marcos conducidos. Se conserva
        #: aparte porque el intento final puede haberse abandonado enseguida, y
        #: entonces lo que describe la captura es el anterior.
        self._ultimo_intento: dict[tuple, int] = {}
        self._en_marcha = False
        self._termino = False
        self._ultimo: dict | None = None

    def _cerrar_intento(self) -> None:
        if self._conteo:
            self._ultimo_intento = self._conteo
        self._conteo = {}

    def ver(self, decodificado: dict) -> None:
        paquete = decodificado.get("paquete")
        if paquete == "event":
            # Estar en movimiento no alcanza para excluir el despues.
            #
            # En la primera pasada de la prueba de dos conductores, 885 marcos
            # posteriores a la bandera a cuadros llegaron con el auto todavia
            # rodando y declarando el antibloqueo activo. La moda resolvio el
            # caso por 90,5 % contra 9,5 %, pero por margen y no por criterio:
            # con una vuelta de desaceleracion mas larga habria dado vuelta el
            # resultado. La bandera es lo que separa la carrera de lo que sigue.
            codigo = decodificado.get("codigo")
            if codigo in self.FIN_DE_LO_CONDUCIDO:
                self._termino = True
                self._cerrar_intento()
            elif codigo in self.INICIO_DE_INTENTO:
                self._termino = False
                self._cerrar_intento()
        elif paquete == "car_telemetry":
            propio = decodificado.get("vehiculo_propio")
            if propio is not None:
                # Cualquier velocidad distinta de cero: no interesa cuanto corria
                # sino que no estaba detenido en un menu.
                self._en_marcha = bool(propio.get("speed_kmh"))
        elif paquete == "car_status":
            propio = decodificado.get("vehiculo_propio")
            if propio is not None:
                self._ultimo = propio
                if self._en_marcha and not self._termino:
                    clave = (propio.get("traction_control"),
                             propio.get("anti_lock_brakes"))
                    self._conteo[clave] = self._conteo.get(clave, 0) + 1

    def estado(self) -> dict | None:
        """El estado del auto con las dos ayudas corregidas por la moda.

        Si nunca se vio el auto en movimiento ---una captura que solo toco el
        menu--- se devuelve la ultima lectura sin corregir, porque no hay nada
        mejor y ocultarla seria peor que declararla.
        """

        conteo = self._conteo or self._ultimo_intento
        if not conteo:
            return self._ultimo
        traccion, antibloqueo = max(conteo.items(), key=lambda par: par[1])[0]
        estado = dict(self._ultimo or {})
        estado["traction_control"] = traccion
        estado["anti_lock_brakes"] = antibloqueo
        estado["ayudas_desde"] = "moda con el auto en marcha, antes de la bandera"
        estado["marcos_en_marcha"] = sum(conteo.values())
        return estado


class SesionesDeLaCaptura:
    """Cada sesion que atraviesa una captura, con su propia procedencia.

    UNA CAPTURA NO ES UNA SESION. El juego le da otro `session_uid` a cada
    sesion nueva y el capturador sigue escribiendo el mismo archivo hasta el
    silencio. La procedencia se derivaba una vez por captura, y solo la sesion
    de esa lectura quedaba nombrada. Medido el 2026-09-11 sobre las 69 capturas:
    224 identificadores con datos y 54 declarados; de las 222 sesiones de F1 25
    del catalogo, 170 sin procedencia. No es cosa de un modo de juego: 7 de 26
    capturas de un conductor y 25 de 43 de dos conductores atraviesan mas de
    una sesion.

    Va **por sesion** todo lo que puede cambiar entre ellas: el tipo, la
    parrilla ---quien ocupa cada asiento, que en las pruebas de dos conductores
    cambio de una pasada a otra--- y las ayudas, con su propio acumulador.

    Recibe la cabecera y, cuando lo hay, el paquete decodificado. Asi la
    rederivacion puede contar cada datagrama leyendo solo la cabecera y
    decodificar unicamente los paquetes que la procedencia usa.
    """

    #: Los paquetes que la procedencia lee. El resto solo cuenta para el tramo.
    PAQUETES = frozenset({"session", "participants", "event",
                          "car_telemetry", "car_status"})

    def __init__(self) -> None:
        self._por_uid: dict[int, dict] = {}

    def anotar(self, session_uid: int | None, desplazamiento_us: int,
               decodificado: dict | None = None) -> None:
        # El cero es la cabecera que el emisor todavia no lleno: no es una sesion.
        if not session_uid:
            return
        s = self._por_uid.get(session_uid)
        if s is None:
            s = self._por_uid[session_uid] = {
                "desde_us": desplazamiento_us, "hasta_us": desplazamiento_us,
                "datagramas": 0, "cabecera": None, "sesion": None,
                "participantes": None, "ayudas": AyudasEnMarcha(),
                "secundarios": {},
            }
        s["hasta_us"] = desplazamiento_us
        s["datagramas"] += 1
        if decodificado is None:
            return

        cabecera = decodificado.get("cabecera") or {}
        if s["cabecera"] is None:
            s["cabecera"] = cabecera
        # El mismo criterio que la captura entera: ver `_segundo_sostenido`.
        if cabecera.get("frame_identifier"):
            sec = cabecera.get("secondary_player_car_index")
            s["secundarios"][sec] = s["secundarios"].get(sec, 0) + 1
        paquete = decodificado.get("paquete")
        # El ultimo que declara un tipo, como la procedencia principal: el
        # primero llega antes de que el juego cargue la configuracion.
        if paquete == "session" and decodificado["sesion"]["session_type"] != 0:
            s["sesion"] = decodificado["sesion"]
        elif paquete == "participants":
            s["participantes"] = decodificado
        s["ayudas"].ver(decodificado)

    def resumen(self) -> list[dict]:
        """Una entrada por sesion, en el orden en que aparecen en la captura."""
        salida = []
        for uid, s in sorted(self._por_uid.items(), key=lambda par: par[1]["desde_us"]):
            salida.append({
                "session_uid": uid,
                "desde_s": round(s["desde_us"] / 1e6, 3),
                "hasta_s": round(s["hasta_us"] / 1e6, 3),
                "datagramas": s["datagramas"],
                "procedencia": derivar_procedencia(
                    s["sesion"], s["ayudas"].estado(), s["cabecera"],
                    s["participantes"], s["secundarios"]),
            })
        return salida


#: Fraccion de cabeceras que tiene que declarar el mismo segundo participante
#: para darlo por real. No es un umbral calibrado: con dos conductores el valor
#: aparece en **todas** las cabeceras utiles, y con la cabecera sin poblar en un
#: punado. Cualquier corte entre ambos extremos separa los dos casos, y se elige
#: la mayoria simple por ser el mas facil de justificar.
FRACCION_SEGUNDO = 0.5


def _segundo_sostenido(secundarios: dict | None) -> bool:
    """Decide si hubo un segundo conductor, por la moda y no por un instante.

    Recibe el recuento de valores del indice del segundo participante sobre las
    cabeceras **ya pobladas**. Devuelve verdadero solo si un indice valido es
    mayoria, que es lo que distingue a un segundo conductor de un campo que
    todavia no se lleno.
    """

    if not secundarios:
        return False
    total = sum(secundarios.values())
    validos = {i: n for i, n in secundarios.items() if i not in (255, None)}
    if not validos:
        return False
    return max(validos.values()) > total * FRACCION_SEGUNDO


def derivar_procedencia(sesion: dict | None, estado: dict | None,
                        cabecera: dict | None,
                        participantes: dict | None = None,
                        secundarios: dict | None = None) -> dict:
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
    #
    # La segunda **no se lee de una cabecera**, se lee de la moda sostenida.
    # Leerla de la primera cabecera de la captura fue un error real: en los
    # primeros paquetes ---y tambien al reiniciarse una sesion--- el emisor
    # publica estructura valida con la cabecera todavia en cero, y un cero en el
    # indice del segundo participante es un indice legitimo. Tres capturas
    # quedaron nombradas como de dos conductores sin haberlos.
    #
    # El contraste que fija el criterio esta disponible en el propio conjunto de
    # capturas. Con dos conductores reales el flujo declara indice propio 18 y
    # secundario 19 **en todos los paquetes**, con modo de juego 6 y dos
    # participantes humanos con nombre. Con la cabecera sin poblar, el indice
    # propio y el secundario valen cero **a la vez** y solo en un punado de
    # paquetes sobre decenas de miles.
    segundo = _segundo_sostenido(secundarios)
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
        # Que comparacion habilita la captura, declarado por el propio flujo.
        #
        # Con el rendimiento igualado, la diferencia observada entre dos
        # conductores es atribuible a **quien conduce**. Sin igualar, incluye el
        # material. Son dos preguntas distintas y confundirlas invalida el
        # resultado, de modo que la captura tiene que decir por si misma cual de
        # las dos responde.
        "rendimiento_igualado": bool(sesion["equal_car_performance"]),
        "comparacion_habilitada": (
            "entre pilotos" if sesion["equal_car_performance"]
            else "entre autos, incluye el material"),
        # Cada ajuste con su valor crudo y su nombre, para que la condicion
        # experimental quede legible en el archivo de metadatos.
        "ajustes": {nombre: {"valor": sesion.get(nombre),
                             "nombre": tabla.get(sesion.get(nombre), "desconocido")}
                    for nombre, tabla in AJUSTES.items()},
        # Quien es cada vehiculo. Sin esto, todo el resto habla de indices.
        "parrilla": derivar_parrilla(participantes),
        # Nombre explicito: no es cuantos corrieron, es cuantos seguian en
        # carrera cuando se leyo el paquete. Llamarlo "activos" a secas fue lo
        # que hizo confundirlo con la longitud de la parrilla.
        "vehiculos_en_carrera_al_leer": (participantes.get("num_active_cars")
                                         if participantes else None),
        "inicio_sector2_m": sesion["sector2_lap_distance_start_m"],
        "inicio_sector3_m": sesion["sector3_lap_distance_start_m"],
        "ayudas": ayudas,
        "ayudas_activas": activas,
        "sin_ayudas": not activas,
        # De donde salieron el control de traccion y el antibloqueo.
        #
        # Las otras ocho ayudas vienen del paquete de sesion y no admiten duda.
        # Estas dos se resuelven con un criterio, y el criterio tiene que viajar
        # con el dato: en la primera pasada de la prueba de dos conductores el
        # valor archivado y el que mostraba la pantalla del juego no coincidian,
        # y sin saber como se habia derivado el numero no habia manera de decidir
        # cual de los dos estaba mal.
        "ayudas_pedales_desde": (estado or {}).get(
            "ayudas_desde", "ultima lectura, sin criterio de marcha"),
        "ayudas_pedales_marcos": (estado or {}).get("marcos_en_marcha"),
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


#: Cuantos vehiculos como maximo acepta una eleccion, el propio incluido.
#:
#: NO ES UN NUMERO DE GUSTO: ES LO QUE LA MEDICION PERMITE. Sobre la carrera de
#: Spa con la parrilla entera, cada coche pide 1.511 senales/s y el propio 1.673,
#: porque suma `motion_ex`. Los veintidos piden 33.250. Cronometrado sobre la
#: Raspberry, la cadena corregida sostuvo 10.240 senales/s durante dos minutos
#: con seis coches: 1.228.842 recibidas y persistidas, cero descartes del broker
#: y una cola acotada a 6.836. Seis entran; no se extrapola ese resultado a ocho.
#:
#: El tope existe porque el modo en que esto se rompe es el peor posible: no
#: falla, se pierden muestras **de todos**, tambien del coche propio. Aceptar una
#: lista de veinte nombres seria prometer algo que ya se sabe que no se cumple.
MAXIMO_VEHICULOS_ELEGIDOS = 6


def _clave_de_nombre(texto: str) -> str:
    """Un nombre reducido a lo que permite compararlo: sin acentos ni mayusculas."""

    plano = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in plano if not unicodedata.combining(c)).casefold().strip()


def indices_elegidos(nombres: dict[int, str], pedidos: list[str] | None,
                     propio: int, tope: int = MAXIMO_VEHICULOS_ELEGIDOS
                     ) -> frozenset[int] | None:
    """Los indices que hay que publicar para escuchar a los pilotos pedidos.

    POR NOMBRE Y NO POR INDICE. El indice del arreglo de vehiculos no significa
    nada para quien conduce: no es la posicion en carrera ni el numero del coche,
    es el lugar que el juego le dio en una lista. Quien mira el tablero elige a
    Verstappen, no al indice 4.

    EL COCHE PROPIO VA SIEMPRE. No es una cortesia: es de quien conduce, y es el
    unico del que el protocolo entrega los datos completos ---`motion_ex` describe
    solo a ese---. Una eleccion que lo dejara afuera dejaria la sesion sin su
    pieza mas rica.

    UN NOMBRE QUE NO CORRE SE IGNORA. La lista puede venir de una sesion anterior
    con otra parrilla. Fallar dejaria la captura sin arrancar por un nombre viejo,
    y publicar el indice igual escribiria filas de un vehiculo que no existio.

    Devuelve `None` cuando no hay eleccion, que **no es lo mismo** que elegir
    solo el coche propio: sin eleccion sigue decidiendo `parrilla_completa`.
    """

    if not pedidos:
        return None
    por_nombre: dict[str, int] = {}
    for indice, nombre in nombres.items():
        clave = _clave_de_nombre(nombre)
        if not clave:
            continue
        por_nombre.setdefault(clave, indice)
        # El apellido solo alcanza: es como se los nombra en la television y en
        # el propio juego. Se registra sin pisar un nombre completo que ya este.
        apellido = clave.rsplit(" ", 1)[-1]
        por_nombre.setdefault(apellido, indice)

    elegidos = [propio]
    for pedido in pedidos:
        indice = por_nombre.get(_clave_de_nombre(pedido))
        if indice is not None and indice not in elegidos:
            elegidos.append(indice)
        # Se recorta respetando el orden pedido, que es el orden de interes de
        # quien eligio: los primeros nombres son los que mas le importan.
        if len(elegidos) >= tope:
            break
    return frozenset(elegidos)


class Publicador:
    """Publica al contrato si el broker esta disponible; si no, no estorba.

    Perder la publicacion es recuperable reproduciendo la captura; perder la
    captura no lo es. Por eso un broker ausente nunca detiene la grabacion.
    """

    #: Cada cuanto se vuelve a intentar la conexion al broker.
    #:
    #: Antes se intentaba **una sola vez, al arrancar el proceso**. Con el
    #: capturador convertido en servicio permanente eso dejo de ser aceptable:
    #: arranca al iniciar sesion, posiblemente antes que el broker, y un fallo
    #: en ese instante lo dejaba mudo durante dias. El 2026-09-02 una carrera
    #: entera quedo grabada sin publicar un solo mensaje.
    REINTENTO_S = 30.0

    def __init__(self, activo: bool, run_id: str | None = None,
                 parrilla_completa: bool = False,
                 archivo_seleccion: Path | None = None) -> None:
        self.cliente = None
        self.mensajes = 0
        #: Mensajes que el cliente **no llego a enviar**, con el motivo que
        #: devolvio. Van separados de `mensajes` a proposito: uno cuenta lo que
        #: salio y el otro lo que se perdio, y sumarlos seria volver a la cifra
        #: unica que mentia.
        self.descartados = 0
        self.motivos_descarte: dict[int, int] = {}
        self.motivo = None
        self._activo = activo
        # Identidad de reinyeccion, para las corridas que **no son una sesion
        # real**: una reproduccion contra el capturador, hecha para medir.
        #
        # Sin ella, esas filas entran a la base con el mismo `source_type` y el
        # mismo `session_id` que las de la sesion verdadera, y **no hay forma de
        # separarlas despues**. Peor: el indice unico de trazabilidad es parcial
        # ---solo aplica cuando esta columna no es nula--- de modo que una
        # segunda corrida duplica filas en silencio.
        #
        # Es el mismo defecto que el camino de reproduccion del bus vehicular ya
        # habia corregido, por el mismo motivo. Aca no se habia notado porque
        # solo aparece al reproducir **contra** el capturador, que es algo que
        # empezo a hacerse al medir la cadena completa.
        self._run_id = run_id
        self._seq = 0
        # Normalizar los veintidos vehiculos y no solo el propio.
        #
        # **Es una opcion y no el comportamiento por omision.** Multiplica por
        # unas veinte lo que se escribe en la base, y eso conviene que sea una
        # decision tomada a proposito y no un descuido.
        #
        # Por que existe: el destinatario amateur usa el sistema para medir su
        # propio desempeno **comparandose contra los demas** ---la maquina o un
        # companero---, y en un simulador ese dato le pertenece. La restriccion
        # de no tener datos de rivales es la de un ingeniero de equipo, no la de
        # cualquier usuario, y aplicarla a todos era un error de alcance.
        self._parrilla_completa = parrilla_completa
        #: Indices que efectivamente corren, derivados del paquete de
        #: participantes. Sin esto se publicarian los lugares vacios del arreglo.
        self._validos: frozenset[int] | None = None
        #: Nombre de cada indice, del mismo paquete. Es lo que permite elegir por
        #: nombre: el indice del arreglo no significa nada para quien conduce.
        self._nombres: dict[int, str] = {}
        #: De que sesion son los indices y los nombres de arriba.
        #:
        #: El publicador vive lo que vive el proceso, y el proceso atraviesa
        #: varias sesiones de juego: arranca al iniciar sesion en la maquina y se
        #: queda. Sin esto, entre el primer paquete de una sesion nueva y su
        #: paquete de participantes ---que llega cada cinco segundos--- los
        #: nombres elegidos se resuelven contra la parrilla vieja. **Los indices
        #: del arreglo se reusan**: el 1 de una sesion es otro piloto en la
        #: siguiente, y se publicarian sus datos como si fueran de aquel.
        self._sesion_de_la_parrilla: int | None = None
        #: LA ELECCION SE LEE DE UN ARCHIVO Y NO DE UN ARGUMENTO.
        #:
        #: Los nombres de la parrilla recien se conocen cuando llega el paquete
        #: de participantes, unos segundos despues de que la sesion arranca, de
        #: modo que **no se pueden elegir antes de empezar a escuchar**. Y el
        #: capturador es un subproceso: no hay forma de decirle nada nuevo sin
        #: matarlo, y matarlo pierde la sesion que esta grabando.
        #:
        #: Un archivo resuelve las dos cosas. Se relee cuando cambia su fecha
        #: ---un `stat` por paquete, que es gratis al lado de decodificarlo--- de
        #: modo que quien mira el tablero puede cambiar a quien escucha en mitad
        #: de la carrera, y lo que eligio sobrevive a que el proceso se reinicie.
        self._archivo_seleccion = archivo_seleccion
        self._pilotos: list[str] | None = None
        self._marca_seleccion: float | None = None
        self._proximo_intento = 0.0
        self._intentos = 0
        if not activo:
            self.motivo = "desactivada por parametro"
            return
        self._conectar()

    def _conectar(self) -> None:
        """Intenta conectar. No propaga el fallo: la grabacion no se detiene."""

        self._proximo_intento = time.monotonic() + self.REINTENTO_S
        self._intentos += 1
        try:
            import paho.mqtt.client as mqtt
            cliente = mqtt.Client()
            cliente.connect(MQTT_HOST, MQTT_PORT, 5)
            cliente.loop_start()
        except Exception as error:
            self.cliente = None
            self.motivo = (f"broker no disponible: {type(error).__name__}: "
                           f"{error} (intento {self._intentos})")
            # Se escribe, y no solo se guarda.
            #
            # Que el motivo quedara unicamente en los metadatos del archivo
            # significaba enterarse recien al terminar de conducir. Un aviso en
            # el registro permite verlo mientras todavia se puede corregir.
            print(f"[capturador] sin publicacion: {self.motivo}", flush=True)
            return
        self.cliente = cliente
        self.motivo = None
        print(f"[capturador] publicando en {MQTT_HOST}:{MQTT_PORT}"
              f" (intento {self._intentos})", flush=True)

    def _releer_seleccion(self) -> None:
        """Vuelve a leer la eleccion si el archivo cambio desde la ultima vez.

        Un `stat` por paquete, que al lado de decodificarlo es gratis. Se compara
        la fecha y no el contenido para no leer sesenta veces por segundo un
        archivo que casi nunca cambia.

        **Un archivo ilegible no detiene la captura ni cambia lo que se venia
        publicando.** Puede estar a medio escribir en el instante en que se lo
        mira, y descartar la eleccion vigente por eso seria pasar a publicar la
        parrilla entera en medio de una carrera, que es justo lo que la eleccion
        existe para evitar.
        """

        if self._archivo_seleccion is None:
            return
        try:
            marca = self._archivo_seleccion.stat().st_mtime
        except OSError:
            # Que el archivo no exista es la ausencia de eleccion, no un error.
            if self._marca_seleccion is not None:
                self._pilotos = None
                self._marca_seleccion = None
            return
        if marca == self._marca_seleccion:
            return
        try:
            leido = json.loads(self._archivo_seleccion.read_text(encoding="utf-8"))
            pilotos = leido.get("pilotos") if isinstance(leido, dict) else leido
            if not isinstance(pilotos, list):
                return
            self._pilotos = [str(p) for p in pilotos]
            self._marca_seleccion = marca
        except (OSError, json.JSONDecodeError, AttributeError):
            return

    def _reintentar_si_toca(self) -> None:
        if (self._activo and self.cliente is None
                and time.monotonic() >= self._proximo_intento):
            self._conectar()

    @property
    def activa(self) -> bool:
        return self.cliente is not None

    def publicar(self, decodificado: dict, inicio_utc: str,
                 desplazamiento_us: int | None = None) -> None:
        # La lista de paquetes la declara el adaptador, no este archivo. Cuando
        # estaba escrita aca, ampliar el adaptador dejaba los canales nuevos sin
        # publicar: la energia y el dano existian en el crudo y no llegaban a la
        # base, de modo que la persistencia guardaba que el vehiculo freno y no
        # por que.
        # La parrilla se anota **antes** del filtro de normalizables.
        #
        # El paquete de participantes no se normaliza ---no trae mediciones, trae
        # identidad--- de modo que el filtro lo descarta. Pero es el unico que
        # dice **quienes corren**, y sin el la parrilla completa publicaria
        # tambien los lugares vacios del arreglo.
        # LA PARRILLA VIEJA SE OLVIDA AL CAMBIAR DE SESION, NO AL LLEGAR LA NUEVA.
        #
        # Esperar al paquete de participantes deja una ventana de hasta cinco
        # segundos ---su frecuencia--- en la que los nombres elegidos se
        # resuelven contra la parrilla anterior. Se olvida en cuanto la cabecera
        # dice otro `session_uid`: es preferible no publicar rivales durante esos
        # segundos a publicarlos mal.
        #
        # Lo que **no** se olvida son los nombres que la persona eligio: son una
        # decision suya y no un dato de la sesion que termino. Se vuelven a
        # resolver solos cuando llegue la parrilla nueva.
        uid = (decodificado.get("cabecera") or {}).get("session_uid")
        if uid is not None and uid != self._sesion_de_la_parrilla:
            self._sesion_de_la_parrilla = uid
            self._validos = None
            self._nombres = {}

        if decodificado["paquete"] == "participants":
            self._validos = frozenset(
                i for i, v in enumerate(decodificado["vehiculos"]) if v.get("name"))
            self._nombres = {i: v["name"]
                             for i, v in enumerate(decodificado["vehiculos"])
                             if v.get("name")}

        if decodificado["paquete"] not in f1_25.PAQUETES_NORMALIZABLES:
            return
        if self.cliente is None:
            self._reintentar_si_toca()
            if self.cliente is None:
                return
        # Los paquetes de bloque unico describen la sesion o al vehiculo propio
        # y **no admiten** normalizarse para todos: pedirselo es un error, no una
        # opcion. Se les pasa siempre el modo propio, aunque la parrilla completa
        # este encendida.
        self._releer_seleccion()
        elegidos = None
        if self._pilotos:
            # La cabecera se mira **solo si hay eleccion**: sin ella no hace
            # falta saber cual es el coche propio, y pedirsela a un paquete que
            # no la trae seria romper por un dato que no se iba a usar.
            propio = (decodificado.get("cabecera") or {}).get("player_car_index", 0)
            elegidos = indices_elegidos(self._nombres, self._pilotos, propio=propio)
        # Con una eleccion no se pide el modo propio: se piden esos vehiculos. Y
        # se intersecta con quienes corren, porque un nombre resuelto sigue
        # siendo un indice que puede haber quedado vacio.
        de_bloque_unico = decodificado["paquete"] in f1_25.PAQUETES_DE_BLOQUE_UNICO
        solo_propio = de_bloque_unico or (not self._parrilla_completa
                                          and elegidos is None)
        validos = self._validos
        if elegidos is not None and not de_bloque_unico:
            validos = elegidos if validos is None else frozenset(validos & elegidos)
        lote: list[dict] = []
        for mensaje in f1_25.mensajes_desde_paquete(
                decodificado, inicio_utc,
                solo_vehiculo_propio=solo_propio,
                vehiculos_validos=validos,
                desplazamiento_captura_us=desplazamiento_us):
            if self._run_id is not None:
                # Va **dentro de `metadata.extra`**, no en el nivel superior del
                # mensaje. Es donde el contrato lo espera y donde ya lo pone el
                # camino de reproduccion del bus vehicular; el consumidor lo
                # promueve desde ahi a la columna.
                #
                # La primera version lo puso arriba. No fallo: el mensaje se
                # publico, se persistio, y la columna quedo en nulo, de modo que
                # las filas de la prueba entraron **sin marca**. Se detecto
                # porque la prueba conto cero filas propias mientras el
                # consumidor mostraba trafico.
                extra = mensaje.setdefault("metadata", {}).setdefault("extra", {})
                extra["replay_run_id"] = self._run_id
                extra["replay_seq"] = self._seq
                self._seq += 1
            lote.append(mensaje)
        # **Un envio por paquete, no uno por senal.**
        #
        # Cada mensaje con garantia de entrega paga un ida y vuelta con el
        # intermediario, y el cliente acepta unos 6.578 por segundo **sin
        # importar que lleven adentro**: el de 560 senales pesa quinientas
        # sesenta veces mas y se envia al mismo ritmo.
        #
        # De a una, la parrilla completa descartaba el 96 % en la cola de
        # salida. Agrupadas, el caudal util pasa de 6.578 a 3.193.566 senales
        # por segundo y no se descarta ninguna.
        if not lote:
            return
        carga = json.dumps(lote if len(lote) > 1 else lote[0])
        info = self.cliente.publish(MQTT_TOPIC, carga, qos=1)
        if info.rc == 0:
            self.mensajes += len(lote)
        else:
            # Se cuenta **por senal y no por envio**: lo que se perdio son las
            # senales, y contarlas como uno haria parecer chico un descarte
            # grande.
            self.descartados += len(lote)
            self.motivos_descarte[info.rc] = (
                self.motivos_descarte.get(info.rc, 0) + len(lote))

    def cerrar(self) -> None:
        if self.cliente is not None:
            self.cliente.loop_stop()
            self.cliente.disconnect()


def _perfil_declarado(sesion: dict) -> tuple:
    """Los campos que describen la condicion experimental de la captura.

    Sirve para detectar el instante a partir del cual el flujo se describe a si
    mismo de forma estable: mientras estos valores todavia cambian, cualquier
    metadato leido seria provisional.
    """

    return tuple(sesion.get(nombre) for nombre in
                 (*AJUSTES, *AYUDAS, "track_id", "session_type", "total_laps"))


def _ruta_de_metadatos(captura: Path) -> Path:
    """Donde vive el archivo de metadatos de una captura."""
    return captura.with_name(captura.name + ".meta.json")


def _borrar_anotacion_en_curso(provisional: Path) -> None:
    """Saca la anotacion provisional cuando su captura deja de serlo."""
    _ruta_de_metadatos(provisional).unlink(missing_ok=True)


def _anotar_en_curso(provisional: Path, inicio_utc: str, procedencia: dict) -> None:
    """Deja la procedencia escrita mientras la captura sigue abierta.

    Lo que se sabe **ya se puede decir**. El circuito y el tipo de sesion los
    declara el flujo en sus primeros segundos; esperar al cierre para anotarlos
    hacia que el tablero llamara «sesion sin procedencia declarada» a una
    captura cuya procedencia estaba a la vista, y que una escucha detenida con
    el coche en pista dejara el crudo mudo.

    Lleva `en_curso` en verdadero para que nada confunda esto con una captura
    terminada: la duracion, el recuento por tipo y lo publicado se saben recien
    al final, y aca no estan.
    """

    if not procedencia.get("disponible"):
        return
    # SE ESCRIBE A MANO Y NO CON `escribir_metadatos`, A PROPOSITO.
    #
    # Esa funcion calcula la huella del crudo **y vuelve a recorrer todos sus
    # datagramas** para contarlos: dos pasadas por un archivo que en una sesion
    # larga pasa de los treinta megabytes. Hacerlo aca frenaria el bucle que
    # esta recibiendo por UDP, y lo que se pierde en un socket parado no vuelve.
    # La huella y el recuento son del archivo terminado; este todavia crece.
    try:
        _ruta_de_metadatos(provisional).write_text(
            json.dumps({
                "en_curso": True,
                "archivo": provisional.name,
                "inicio_utc": inicio_utc,
                "procedencia": procedencia,
            }, indent=2, ensure_ascii=False),
            encoding="utf-8")
    except Exception:  # noqa: BLE001 - anotar de mas nunca debe cortar la captura
        pass


def capturar_sesion(sock: socket.socket, primer_datagrama: bytes,
                    destino: Path, publicador: Publicador) -> dict:
    """Graba una sesion completa, desde el primer datagrama hasta el silencio."""

    inicio_dt = datetime.now()
    inicio_utc = datetime.now(timezone.utc).isoformat()
    inicio = time.perf_counter()

    provisional = destino / f".captura_en_curso_{inicio_dt.strftime('%H%M%S')}.f1raw"
    conteo: dict[int, int] = {}
    sesion = cabecera = participantes = None
    secundarios: dict = {}
    ayudas_vistas = AyudasEnMarcha()
    # La procedencia de cada sesion que atraviese la captura, ademas de la
    # principal: ver `SesionesDeLaCaptura`.
    sesiones_de_la_captura = SesionesDeLaCaptura()
    # El primer paquete de sesion llega antes de que el juego tenga cargada la
    # configuracion: declara todo en cero. Tomar ese es lo que hacia que una
    # carrera con dano en simulacion se archivara como "dano desactivado".
    # Se conserva el ultimo que declara un tipo de sesion conocido, y se mide
    # cuanto tardo el flujo en describirse de forma estable.
    sesion_inicial = None
    sesiones_vistas = 0
    estable_desde_s: float | None = None
    ultimo_perfil = None
    descartados = 0
    anotada_la_parrilla = False
    motivo = "silencio: se dejo de recibir"

    with f1_capture.EscritorCaptura(provisional) as escritor:
        datos = primer_datagrama
        while True:
            # El mismo desplazamiento que se graba en el crudo viaja en el
            # mensaje, de modo que el dato en vivo y el reproducido comparten
            # referencia temporal y son comparables entre si.
            desplazamiento = int((time.perf_counter() - inicio) * 1_000_000)
            escritor.escribir(desplazamiento, datos)
            conteo[len(datos)] = conteo.get(len(datos), 0) + 1

            try:
                decodificado = f1_udp.decodificar(datos)
            except f1_udp.ErrorDecodificacion:
                descartados += 1
                decodificado = None

            if decodificado is not None:
                if cabecera is None:
                    cabecera = decodificado["cabecera"]
                # El marco en cero identifica las cabeceras que el emisor
                # todavia no lleno. Se las descarta para el recuento, y el
                # recuento decide por moda: ver `_segundo_sostenido`.
                _cab = decodificado["cabecera"]
                if _cab.get("frame_identifier"):
                    _sec = _cab.get("secondary_player_car_index")
                    secundarios[_sec] = secundarios.get(_sec, 0) + 1
                if decodificado["paquete"] == "session":
                    candidata = decodificado["sesion"]
                    sesiones_vistas += 1
                    if sesion_inicial is None:
                        sesion_inicial = candidata
                    if candidata["session_type"] != 0:
                        sesion = candidata
                        perfil = _perfil_declarado(candidata)
                        if perfil != ultimo_perfil:
                            ultimo_perfil = perfil
                            estable_desde_s = time.perf_counter() - inicio
                            # LA PROCEDENCIA SE DECLARA APENAS SE SABE, NO AL
                            # CERRAR.
                            #
                            # Se escribia solo al terminar la sesion, y de ahi
                            # salian dos problemas con la misma raiz: en vivo el
                            # tablero mostraba «sesion sin procedencia
                            # declarada» aunque el flujo ya hubiera dicho que
                            # era Monza, y una escucha detenida con el juego en
                            # pista dejaba el crudo sin metadatos ---habia que
                            # rederivarlos a mano---.
                            #
                            # Se escribe cada vez que el perfil cambia, que son
                            # unas pocas veces por sesion, y se reescribe entero
                            # al cerrar. Un metadato provisional declara que lo
                            # es: la duracion todavia no se sabe.
                            _anotar_en_curso(provisional, inicio_utc,
                                             derivar_procedencia(
                                                 sesion, ayudas_vistas.estado(),
                                                 cabecera, participantes,
                                                 secundarios))
                elif decodificado["paquete"] == "participants":
                    # El ultimo, como el resto: la parrilla se completa cuando la
                    # sesion arranca, no en el menu.
                    participantes = decodificado
                    # Y se vuelve a anotar, porque la parrilla llega **despues**
                    # que el paquete de sesion. Anotando solo al cambiar el
                    # perfil, el metadato provisional quedaba con circuito y sin
                    # nombres, y el tablero mostraba «Vehiculo 0» durante toda
                    # la escucha. Una sola vez: la parrilla no cambia dentro de
                    # una sesion, y reescribir en cada paquete seria escribir
                    # sesenta veces por minuto para decir lo mismo.
                    if sesion is not None and not anotada_la_parrilla:
                        anotada_la_parrilla = True
                        _anotar_en_curso(provisional, inicio_utc,
                                         derivar_procedencia(
                                             sesion, ayudas_vistas.estado(),
                                             cabecera, participantes,
                                             secundarios))
                ayudas_vistas.ver(decodificado)
                sesiones_de_la_captura.anotar(
                    decodificado["cabecera"].get("session_uid"), desplazamiento,
                    decodificado)
                publicador.publicar(decodificado, inicio_utc, desplazamiento)

            try:
                datos, _ = sock.recvfrom(4096)
            except socket.timeout:
                break
            except KeyboardInterrupt:
                # Detener la escucha no invalida lo ya recibido. Si SIGINT sale
                # de esta funcion, el bloque de cierre no renombra el provisional
                # ni escribe sus metadatos y el tablero queda esperando una
                # captura terminada que nunca aparece.
                motivo = "detencion solicitada mientras la sesion seguia activa"
                break

    transcurrido = time.perf_counter() - inicio
    procedencia = derivar_procedencia(
        sesion, ayudas_vistas.estado(), cabecera, participantes, secundarios)

    if transcurrido < MINIMO_UTIL_S:
        _borrar_anotacion_en_curso(provisional)
        provisional.unlink(missing_ok=True)
        return {"conservada": False, "duracion_s": round(transcurrido, 2),
                "motivo": f"menos de {MINIMO_UTIL_S:.0f} s: no es una sesion"}

    # El minimo por duracion no alcanza. Navegar por los menus emite telemetria
    # durante minutos sin que haya sesion alguna: la primera version del filtro
    # dejo pasar diez capturas de entre diez y setenta y tres segundos, cada una
    # de ellas mas larga que el minimo y ninguna con dato util.
    #
    # El criterio correcto no es cuanto duro sino **si el flujo declaro una
    # sesion**. Es el mismo principio que rige el resto del capturador: se le
    # pregunta al dato, no al reloj.
    if not procedencia.get("disponible"):
        _borrar_anotacion_en_curso(provisional)
        provisional.unlink(missing_ok=True)
        return {"conservada": False, "duracion_s": round(transcurrido, 2),
                "motivo": "el flujo no declaro ninguna sesion: navegacion de menus"}

    ruta = destino / f"{nombre_derivado(procedencia, inicio_dt)}.f1raw"
    sufijo = 1
    while ruta.exists():
        sufijo += 1
        ruta = destino / f"{nombre_derivado(procedencia, inicio_dt)}_{sufijo}.f1raw"
    # El provisional se va con su nombre; su anotacion tambien. Dejarla
    # convertiria una captura ya cerrada en dos: la de verdad y un fantasma con
    # el nombre viejo, que el tablero listaria igual porque lee los metadatos.
    _borrar_anotacion_en_curso(provisional)
    provisional.replace(ruta)

    extra = {
        "inicio_utc": inicio_utc,
        "duracion_s": round(transcurrido, 3),
        "motivo_corte": motivo,
        "paquetes_sesion": sesiones_vistas,
        # Evidencia de que el metadato no se leyo antes de tiempo.
        "metadatos_desde": "ultimo paquete de sesion con tipo declarado",
        "metadatos_estables_desde_s": (round(estable_desde_s, 3)
                                       if estable_desde_s is not None else None),
        "primer_paquete_sesion_vacio": (
            sesion_inicial is not None and sesion_inicial["session_type"] == 0),
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
        # La procedencia de cada sesion que atraveso la captura. La principal de
        # arriba nombra una sola; sin esta lista, las otras quedaban como
        # «Sesión sin procedencia declarada». Ver `SesionesDeLaCaptura`.
        "sesiones_en_la_captura": sesiones_de_la_captura.resumen(),
        # Lo descartado va **en los metadatos de la captura**, no solo en la
        # pantalla: una captura cuyos mensajes no llegaron a la base tiene que
        # poder decirlo despues, cuando alguien se pregunte por que faltan filas.
        "publicacion": {"activa": publicador.activa,
                        "mensajes": publicador.mensajes,
                        "descartados": publicador.descartados,
                        "motivos_descarte": publicador.motivos_descarte,
                        "motivo": publicador.motivo},
        "version_decodificador": f1_udp.VERSION_DECODIFICADOR,
        "formato_udp_admitido": f1_udp.FORMATO_ADMITIDO,
        # LO QUE ANTES VIAJABA EN CADA SENAL, DECLARADO UNA VEZ.
        #
        # La version del adaptador iba en el metadato de cada mensaje, con lo
        # que una carrera de cuatro coches la repetia unas seis mil veces por
        # segundo. Es de la captura entera, y aca es donde la captura se
        # describe: junto a la version del decodificador, que ya vivia aca por
        # el mismo motivo.
        #
        # `simulated` no hace falta declararlo: el `source_type` de cada fila
        # es `f1_25_udp_simulation` y su `quality_flag` es `simulated_f1_25`.
        # Ya estaba dicho dos veces.
        "version_adaptador": f1_25.VERSION_ADAPTADOR,
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
        # Los ajustes se leen del diccionario que la procedencia declara, no de
        # un campo suelto. El campo suelto existia y se renombro; el resumen
        # quedo apuntando al viejo y el capturador se caia **despues** de
        # escribir el archivo, de modo que la captura se salvaba y el proceso
        # moria sin quedar escuchando la siguiente.
        ajustes = p.get("ajustes", {})
        dano = ajustes.get("car_damage_setting", {}).get("nombre", "no declarado")
        print(f"  dano       : {dano}"
              f"   ayudas: {'ninguna' if p['sin_ayudas'] else ', '.join(p['ayudas_activas'])}")
        parrilla = p.get("parrilla") or []
        if parrilla:
            humanos = [v["nombre"] for v in parrilla if not v["es_ia"]]
            print(f"  parrilla   : {len(parrilla)} vehiculos"
                  f"{', conductor: ' + ', '.join(humanos) if humanos else ''}")
        if p["pantalla_dividida"]:
            print(f"  conductores: dos, en pantalla dividida")
    else:
        print(f"  procedencia: no derivable, {p['motivo']}")
    if r["tamanos_fuera_de_especificacion"]:
        print(f"  ATENCION   : tamanos fuera de la especificacion: "
              f"{r['tamanos_fuera_de_especificacion']}")
    pub = r["publicacion"]
    if not pub["activa"]:
        print(f"  publicacion: no, {pub['motivo']}")
    elif pub["descartados"]:
        total = pub["mensajes"] + pub["descartados"]
        print(f"  publicacion: {pub['mensajes']} mensajes, "
              f"**{pub['descartados']} DESCARTADOS** "
              f"({100 * pub['descartados'] / total:.1f} %) "
              f"motivos {pub['motivos_descarte']}")
    else:
        print(f"  publicacion: {pub['mensajes']} mensajes, ninguno descartado")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destino", type=Path, default=DESTINO_POR_DEFECTO)
    parser.add_argument("--sin-publicar", action="store_true",
                        help="Solo graba. Por defecto publica si el broker responde.")
    parser.add_argument("--silencio", type=float, default=SILENCIO_CIERRA_S,
                        help="Segundos sin datagramas que cierran una captura.")
    # El puerto se puede cambiar para levantar una segunda instancia sin
    # molestar a la que esta escuchando el juego. Es lo que permite correr los
    # escenarios de degradacion contra una captura reproducida ---en su propio
    # directorio y sin publicar--- mientras el capturador de verdad sigue en
    # marcha. Por omision es el del juego, de modo que nada cambia para quien
    # no lo pase.
    parser.add_argument("--puerto", type=int, default=PUERTO_JUEGO,
                        help="Puerto UDP donde escuchar.")
    parser.add_argument("--parrilla-completa", action="store_true",
                        help="Normaliza los veintidos vehiculos y no solo "
                             "el propio. La base absorbe 2.770 filas por "
                             "segundo y esto produce 35.186: la cola crece "
                             "y no vuelve a bajar. Sirve para medir la "
                             "carga, no para capturar. Para los rivales, "
                             "republicar_captura.py --parrilla-completa "
                             "al terminar la sesion.")
    parser.add_argument("--pilotos", default=None,
                        help="Nombres de los pilotos a escuchar, separados por "
                             "coma, ademas del coche propio. Se escriben en el "
                             "archivo de eleccion antes de arrancar; el tablero "
                             "puede reescribirlo en mitad de la sesion.")
    parser.add_argument("--archivo-eleccion", type=Path,
                        default=SELECCION_POR_DEFECTO,
                        help="De donde se relee a quien escuchar mientras corre.")
    parser.add_argument("--run-id", default=None,
                        help="Identidad de reinyeccion para una corrida que no "
                             "es una sesion real. Sin ella, lo que se reproduzca "
                             "contra el capturador entra a la base mezclado con "
                             "la telemetria verdadera y no se puede separar.")
    args = parser.parse_args()

    args.destino.mkdir(parents=True, exist_ok=True)
    if args.pilotos is not None:
        # Lo pedido en la linea de comandos se escribe en el archivo, no se
        # guarda aparte: asi hay **una sola** fuente de a quien se escucha, y lo
        # que el tablero muestre despues es lo que el capturador esta usando.
        nombres = [p.strip() for p in args.pilotos.split(",") if p.strip()]
        args.archivo_eleccion.parent.mkdir(parents=True, exist_ok=True)
        args.archivo_eleccion.write_text(
            json.dumps({"pilotos": nombres}, ensure_ascii=False), encoding="utf-8")
    publicador = Publicador(not args.sin_publicar, run_id=args.run_id,
                            parrilla_completa=args.parrilla_completa,
                            archivo_seleccion=args.archivo_eleccion)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", args.puerto))
    sock.settimeout(args.silencio)

    print(f"Capturador en marcha. Escuchando el puerto {args.puerto}.")
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
            resultado = capturar_sesion(sock, datos, args.destino, publicador)
            try:
                informar(resultado)
            except Exception as error:  # noqa: BLE001
                # El resumen es para la persona, no para el dato. Si falla,
                # la captura ya esta en disco con su procedencia: seguir
                # escuchando vale mas que imprimir bien.
                print(f"  ATENCION   : no se pudo resumir la captura "
                      f"({type(error).__name__}: {error}). El archivo esta guardado.")
            print()
    except KeyboardInterrupt:
        print(f"\nCapturador detenido. Sesiones grabadas en esta corrida: {capturadas}.")
    finally:
        sock.close()
        publicador.cerrar()


if __name__ == "__main__":
    main()
