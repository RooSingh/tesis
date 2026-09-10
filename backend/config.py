"""Configuracion local del backend.

Este modulo centraliza los parametros que usan el consumidor MQTT, la API y la
capa de persistencia para conectarse a los servicios locales de la tesis.

Todo sale del entorno y **todo tiene un valor por omision igual al que tenia
cuando estaba escrito en el codigo**: sin definir una sola variable, el proyecto
se comporta exactamente como antes. Definirlas es lo que permite correrlo en
otra parte ---otra base, otro intermediario, detras de un tunel--- sin tocar una
linea.

`docs/ENTORNO.env.example` enumera todas con su valor por omision.

Lo que sigue sin estar aca, a proposito: la autenticacion. El proyecto no la
tiene y no la finge. Mientras todo escucha en `127.0.0.1` la maquina es el
limite; publicado hacia afuera, ese limite lo tiene que poner algo delante ---en
el despliegue documentado, Cloudflare Access---. Ver `docs/DESPLIEGUE.md`.
"""

import os
from pathlib import Path


def _cargar_env(ruta: "os.PathLike | str") -> None:
    """Lee un archivo `.env` y lo vuelca al entorno, sin pisar lo ya definido.

    POR QUE A MANO Y NO CON UNA BIBLIOTECA
    --------------------------------------
    Son diez lineas. Agregar una dependencia para esto obligaria a instalarla en
    el equipo de destino, a fijarla en el manifiesto y a explicarla en el
    informe, y lo unico que hace es partir por el primer signo igual.

    NO PISA LO YA DEFINIDO, y ese orden importa: una variable puesta en el
    entorno ---por el motor de contenedores, por el servicio del sistema, o a
    mano para una prueba--- tiene que ganarle al archivo. Al reves, un `.env`
    olvidado en el directorio se impondria en silencio sobre la configuracion
    del despliegue.
    """

    try:
        with open(ruta, "r", encoding="utf-8") as archivo:
            for linea in archivo:
                linea = linea.strip()
                if not linea or linea.startswith("#") or "=" not in linea:
                    continue
                clave, valor = linea.split("=", 1)
                os.environ.setdefault(clave.strip(), valor.strip())
    except FileNotFoundError:
        pass


#: El archivo vive en la raiz del repositorio y **no se versiona**. El que si se
#: versiona es `.env.example`, que dice que variables existen sin decir sus
#: valores.
_cargar_env(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), ".env"))

#: Direccion del intermediario. **Numerica y no `localhost`**, a proposito.
#:
#: `localhost` no es una direccion sino una busqueda, y en Windows resuelve
#: primero a `::1`. Se lo diagnostico despues de un reinicio del contenedor: un
#: relay de WSL huerfano quedo escuchando en `::1:1883` y **aceptaba el socket
#: sin reenviarlo al intermediario**, de modo que la conexion se establecia y el
#: CONNACK no llegaba nunca.
#:
#: El sintoma era el peor posible: `connect()` no levantaba excepcion, el
#: consumidor informaba `consumer_ready=true` y no recibia nada, y el
#: intermediario no registraba la conexion porque nunca le llego. Probado con las
#: tres direcciones, `127.0.0.1` respondia y las otras dos no.
MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
#: El puerto y los topicos salen del entorno, con los mismos valores de
#: siempre por omision: sin definir nada, todo se comporta igual que antes.
#:
#: Estan asi para poder levantar una pila aislada ---otro intermediario, en otro
#: puerto, sin consumidor--- y ejercitar el camino en vivo **sin escribir en la
#: base**. El consumidor esta suscripto a los dos topicos, de modo que cualquier
#: prueba contra el intermediario de siempre persiste una sesion nueva; con un
#: intermediario aparte no hay nada que persista y no hay dato real en riesgo.
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "tesis/telemetry/live")
MQTT_REPLAY_TOPIC = os.getenv("MQTT_REPLAY_TOPIC", "tesis/telemetry/replay")
#: Identidad del consumidor ante el intermediario.
#:
#: Es **fija a proposito**. Un cliente sin identidad recibe una distinta en cada
#: conexion, y el intermediario no puede reconocerlo: lo que hubiera guardado para
#: el mientras estaba caido queda huerfano, porque el que vuelve es, para el
#: intermediario, otro cliente.
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "tesis-consumidor-telemetria")

#: Si el intermediario conserva la sesion del consumidor entre conexiones.
#:
#: Con la sesion conservada, el intermediario mantiene la suscripcion y **encola
#: lo que llega mientras el consumidor no esta**, y se lo entrega al reconectar.
#: Sin ella, todo lo publicado durante una caida se pierde sin registro.
#:
#: El costo es que la cola vive en el intermediario y ocupa memoria alli: una
#: caida larga la hace crecer, y el intermediario tiene su propio limite. Es un
#: intercambio deliberado y no una opcion gratuita.
MQTT_SESION_PERSISTENTE = os.getenv("MQTT_SESION_PERSISTENTE", "1") != "0"

#: Calidad de servicio con que el consumidor **se suscribe** al topico en vivo.
#:
#: No alcanza con que el publicador publique con garantia: la entrega al
#: suscriptor se rige por el minimo entre la calidad de la publicacion y la de la
#: suscripcion. Suscripto en cero, nada se encola ni se reenvia, y la sesion
#: persistente no sirve de nada para ese topico.
#:
#: Que se pueda subir a uno es **consecuencia de agrupar la publicacion**: cada
#: mensaje con garantia paga un ida y vuelta, y el cliente acepta unos 6.578 por
#: segundo. Sin agrupar, la parrilla completa produce 35.186 senales por segundo y
#: no habria margen; agrupadas por paquete son unos 63 mensajes por segundo.
MQTT_QOS_EN_VIVO = int(os.getenv("MQTT_QOS_EN_VIVO", "1"))

#: Si el consumidor confirma cada mensaje **despues** de haberlo escrito.
#:
#: Con la confirmacion automatica de la biblioteca, el acuse sale al volver del
#: callback: el mensaje queda confirmado mientras espera en la cola de memoria, y
#: si el proceso muere ahi el intermediario no lo reenvia porque ya lo dio por
#: entregado. La cola se midio llegando a 621.690 mensajes.
#:
#: Con la confirmacion manual el acuse sale tras el `insert`, de modo que un
#: mensaje confirmado es un mensaje escrito. El costo es que el intermediario
#: deja de mandar cuando acumula mensajes sin confirmar: eso convierte un
#: descarte invisible en una contrapresion visible, y ata el caudal al limite del
#: intermediario, medido en 100 mensajes.
#:
#: Y trae duplicados posibles: si el proceso muere entre el `insert` y el acuse,
#: el intermediario reenvia y la fila se escribe dos veces. El indice unico que
#: los suprime cubre solo las filas con identidad de reinyeccion, de modo que
#: **la telemetria en vivo no tiene hoy clave de deduplicacion**.
MQTT_CONFIRMACION_MANUAL = os.getenv("MQTT_CONFIRMACION_MANUAL", "1") != "0"

MQTT_BATCH_SIZE = int(os.getenv("MQTT_BATCH_SIZE", "1000"))
MQTT_FLUSH_INTERVAL_SECONDS = float(os.getenv("MQTT_FLUSH_INTERVAL_SECONDS", "0.5"))

# Cota superior de la cola en memoria del consumidor. En `0` el buffer crece sin
# limite, que es el comportamiento historico y el que se conserva por defecto
# para no alterar corridas ya validadas. Un valor positivo activa contrapresion:
# el hilo de red se frena antes de agotar la RAM, a costa de dejar de confirmar
# mensajes al broker. Solo debe activarse en una prueba controlada.
MQTT_MAX_PENDING_MESSAGES = int(os.getenv("MQTT_MAX_PENDING_MESSAGES", "0"))

# Estadistica interna que publica Mosquitto con la cantidad acumulada de mensajes
# descartados hacia sus clientes. Es el unico observador del tramo
# broker -> consumidor, donde el proyecto demostro perder mensajes sin que ningun
# contador propio lo reflejara.
MQTT_SYS_DROPPED_TOPIC = "$SYS/broker/publish/messages/dropped"

BACKEND_APP_NAME = "tesis-telemetry-backend"

#: La base, tambien desde el entorno y con los mismos valores por omision: sin
#: definir nada, todo se comporta igual que antes.
#:
#: Estan asi por el mismo motivo que `MQTT_PORT`: poder levantar una pila
#: aparte ---otra base, en otro puerto--- y comprobar contra ella sin tocar la
#: de siempre. Es lo que permitio verificar que las migraciones reconstruyen el
#: esquema en una base virgen, que era la unica forma de saberlo sin arriesgar
#: los ochenta y nueve millones de filas.
#:
#: La contrasena por omision **se deja**, y el razonamiento sigue valiendo: es la
#: de un servicio local que solo escucha en esta maquina, y sacarla a una variable
#: sin sacarla del historial de git no la volveria secreta.
#:
#: Lo que se agrega es la otra mitad, que el despliegue vuelve necesaria:
#: `verificar_secretos()` impide arrancar con ese valor **contra una base que no
#: sea local**. Ahi si hay algo que proteger, y ahi el valor publico no sirve.
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "tesis_db")
DB_USER = os.getenv("DB_USER", "tesis_user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "tesis_pass")

#: La contrasena que este repositorio publica. Se la nombra para poder
#: reconocerla, no para ocultarla: **esta en el historial de git desde el primer
#: dia** y sacarla ahora no la volveria secreta.
CONTRASENA_PUBLICA = "tesis_pass"

#: Direcciones que significan «la base corre en esta misma maquina».
_ANFITRIONES_LOCALES = ("localhost", "127.0.0.1", "::1", "timescaledb")


def verificar_secretos() -> None:
    """Impide arrancar con la contrasena publica contra una base que no es local.

    QUE PROTEGE Y QUE NO
    --------------------
    No protege la contrasena actual: es publica y seguira siendolo. Protege el
    caso que el despliegue introduce, que hasta ahora no existia: **una base
    alcanzable desde fuera de esta maquina**, con la clave que cualquiera puede
    leer en el repositorio.

    Renombrar el valor a una variable de entorno y dejarlo igual habria dado la
    sensacion de haber resuelto algo. Lo que resuelve algo es que el sistema se
    niegue a usarlo donde importa.

    Se llama desde el arranque del servicio y no al importar el modulo: importar
    la configuracion tiene que poder hacerse siempre ---las pruebas lo hacen--- y
    fallar en la importacion volveria imposible hasta leer el valor para
    corregirlo.
    """

    if DB_HOST in _ANFITRIONES_LOCALES:
        return
    if DB_PASSWORD == CONTRASENA_PUBLICA:
        raise RuntimeError(
            f"La base apunta a {DB_HOST!r}, que no es esta maquina, con la "
            f"contrasena que el repositorio publica. Defini DB_PASSWORD en el "
            f"archivo .env o en el entorno antes de arrancar."
        )

#: LOS ORIGENES QUE EL NAVEGADOR TIENE PERMITIDO LEER, desde el entorno.
#:
#: Estaban escritos a mano en `backend/app.py` y por eso el tablero solo podia
#: servirse desde `localhost:3000`. Servido en cualquier otro origen ---otro
#: puerto, otra maquina, un dominio detras de un tunel--- las peticiones llegan
#: a la API, la API responde, y **el navegador descarta la respuesta al
#: recibirla**. El tablero se ve, no muestra datos y no dice por que; ya paso
#: dos veces en este proyecto y las dos costo diagnosticarlo.
#:
#: Se escriben separados por coma. Los dos por omision son los mismos que
#: estaban en el codigo, de modo que sin definir nada no cambia nada.
#:
#: En el despliegue con un solo nombre esta lista **no se usa**: el tablero sale
#: del mismo origen que la API y no hay peticion de origen cruzado que permitir.
#: Sigue haciendo falta en desarrollo, donde el tablero vive en el 3000 y la API
#: en otro puerto.
CORS_ORIGENES = [
    origen.strip()
    for origen in os.getenv(
        "CORS_ORIGENES",
        "http://127.0.0.1:3000,http://localhost:3000",
    ).split(",")
    if origen.strip()
]

#: Si la API sirve tambien los archivos del tablero.
#:
#: POR QUE EXISTE
#: --------------
#: En desarrollo son dos servidores ---`python -m http.server` en el 3000 y la
#: API en el 8000--- y esta bien que lo sean: se reinicia uno sin tocar el otro.
#:
#: Hacia afuera esa division cuesta cara. Dos servidores son dos nombres, y dos
#: nombres detras de Cloudflare Access son dos cookies de autorizacion, de las
#: cuales el navegador manda **una sola** en una peticion de origen cruzado: la
#: consulta a la API vuelve como un redirect a la pantalla de login que el
#: `fetch` ve como un error opaco de CORS. Servidos del mismo origen, ni Access
#: ni CORS tienen nada que resolver.
#:
#: Ademas, `python -m http.server` es un servidor de desarrollo ---monohilo, sin
#: endurecer--- y su propia documentacion desaconseja exponerlo.
#:
#: Por omision esta **apagado**: en desarrollo nada cambia.
SERVIR_TABLERO = os.getenv("SERVIR_TABLERO", "0") == "1"

#: De donde salen esos archivos. Por omision, el `dashboard/` del repositorio.
DIRECTORIO_TABLERO = os.getenv(
    "DIRECTORIO_TABLERO",
    str(Path(__file__).resolve().parent.parent / "dashboard"),
)


#: Si la captura se limita al vehiculo propio, ignorando lo que pida quien la
#: inicie.
#:
#: POR QUE EXISTE, Y CON QUE MEDICION
#: ----------------------------------
#: Publicar la parrilla completa multiplica por veintidos las senales que la
#: cadena tiene que llevar, y hay maquinas donde eso no entra. Medido sobre la
#: Raspberry el 2026-09-09, con una contrarreloj real de 250,5 s que el
#: simulador entrego a 20 Hz limpios:
#:
#:     con la parrilla completa   25.591 senales/s pedidas
#:     el consumidor sostuvo       3.811 senales/s
#:     solo el vehiculo propio     1.866 senales/s pedidas
#:
#: Se le pidio 6,7 veces su techo: el intermediario descarto el 87 % de los
#: envios y llego el 14,9 %. **No se perdieron los rivales: se perdio casi todo,
#: tambien del coche propio.** Limitado al vehiculo propio entra con el doble de
#: margen y no se descarta nada.
#:
#: Por omision esta apagado y la captura hace lo que le pidan, de modo que donde
#: la cadena da abasto no cambia nada. Encendido, `POST /captura/iniciar`
#: **lo declara en su respuesta**: una peticion ignorada en silencio seria peor
#: que el problema que evita.
CAPTURA_SOLO_VEHICULO_PROPIO = os.getenv("CAPTURA_SOLO_VEHICULO_PROPIO", "0") == "1"
