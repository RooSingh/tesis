#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sigue **un** mensaje por las cinco etapas de la cadena y las imprime.

    DB_PORT=5434 DB_NAME=spa_original .venv/bin/python \\
        scripts/rastrear_un_mensaje.py \\
        datasets/f1_25/capturas/20260904_2136_spa_carrera-2_dos-conductores.f1raw

QUE PRUEBA Y POR QUE HACE FALTA
-------------------------------
El sistema tiene medido cuanto tarda cada tramo y cuanto caudal aguanta, pero
ninguna de esas mediciones dice **que lo que entra es lo que sale**. Un tramo
puede ser rapido y puntual y aun asi cambiar una unidad, redondear un valor o
perder un metadato, y las cifras de latencia saldrian iguales.

Esta herramienta toma un mensaje concreto ---uno, identificable por su numero de
secuencia--- y lo muestra en las cinco etapas por las que pasa:

  1. la salida del generador        (el adaptador normaliza el datagrama crudo)
  2. la suscripcion al intermediario (lo que el broker entrega a un suscriptor)
  3. el registro del consumidor      (lo que el consumidor real acepto y anoto)
  4. la consulta directa a la base   (la fila persistida, buscada por identidad)
  5. la respuesta de la consulta     (lo que la interfaz de consulta devuelve)

y compara valor, unidad e instante del dato entre las cinco. Si alguna difiere,
lo dice y termina con codigo distinto de cero.

COMO SE IDENTIFICA EL MENSAJE
-----------------------------
Por `(replay_run_id, replay_seq)`, que es la identidad que ya viaja por la
cadena: el publicador la inyecta en `metadata.extra`, la base la promueve a
columnas propias y su indice unico parcial la vuelve buscable. No se inventa
nada para esta herramienta; se usa lo que el sistema ya usa para poder
reconciliar una reproduccion.

El numero de secuencia se cuenta **igual que en `republicar_captura.py`**: sobre
todos los mensajes normalizables de la captura, se publiquen o no. Contarlo de
otra forma daria un numero que no significa lo mismo en las dos herramientas, y
la identidad dejaria de identificar.

POR QUE LA IDENTIDAD DE CORRIDA LLEVA EL INSTANTE DE LA CORRIDA
---------------------------------------------------------------
En `republicar_captura.py` la identidad se deriva del hash de la captura **a
proposito**: dos corridas sobre el mismo archivo tienen que producir las mismas
identidades para que la segunda complete en lugar de duplicar.

Aca hace falta lo contrario. La insercion usa `ON CONFLICT DO NOTHING`, de modo
que una identidad repetida no escribiria nada y la etapa 4 encontraria **la fila
de la corrida anterior**: el rastreo daria correcto sin haber probado nada. Con
el instante adentro, cada rastreo escribe su propia fila o falla a la vista.

LAS FILAS QUE ESCRIBE, Y POR QUE SE BORRAN POR OMISION
-------------------------------------------------------
Escribe **una** fila en la tabla real, porque rastrear contra una tabla de
juguete no rastrearia la cadena. Esa fila es una repeticion de un dato que la
sesion ya tiene ---sale de la misma captura--- pero con `replay_run_id` propio,
de modo que **cuenta como una adquisicion aparte** para las rutas que agrupan
por esa columna. Dejarla cambiaria lo que el tablero dice de la sesion a cambio
de nada, asi que se borra al terminar y se informa cuantas filas se borraron.
`--conservar` la deja, para poder mirarla a mano.

EL RELOJ DEL MENSAJE, Y POR QUE POR OMISION ES EL DE AHORA
-----------------------------------------------------------
El adaptador sella cada mensaje con el inicio de la captura mas el reloj de
sesion. Sellado con el inicio original, el mensaje cae en un tramo de tiempo
**ya comprimido**, y ahi la base **se niega a escribirlo**. Medido el
2026-09-11 sobre `spa_original`:

    ConfigurationLimitExceeded: tuple decompression limit exceeded by operation
    current limit: 100000, tuples decompressed: 110000

No es un capricho del motor: para respetar los dos indices unicos de la tabla
hay que descomprimir lo que podria chocar, y uno de ellos ---el de identidad de
reinyeccion--- no es columna de segmentacion, de modo que no hay segmento chico
que alcance. Con el sello de ahora la fila cae en un tramo nuevo, sin comprimir,
y entra sin tocar nada de lo comprimido.

Hay que decir el precio de sellar con el reloj de ahora: el sello es el inicio
**mas el reloj de sesion**, y la captura se recorre sin esperar, de modo que un
mensaje del segundo 21,9 de la sesion queda sellado 21,9 segundos **adelante**
del reloj de pared. No afecta a lo que esta herramienta compara ---las cinco
etapas miran el mismo sello--- pero se informa al lado del sello para que nadie
lea ese instante como si fuera el momento en que paso algo.

Por eso `--reloj ahora` es lo que se hace por omision: es el mismo sellado que
usa una captura en vivo ---el unico camino que el sistema recorre a diario--- y
es el que llega hasta la quinta etapa. `--reloj captura` conserva el sello
original y sirve para **ver ese rechazo**, que es una propiedad real del sistema
y no un defecto de esta herramienta: el rastreo lo informa con el motivo que dio
la base, en lugar de contarlo como una perdida de la cadena.

QUE NO MIDE
-----------
El instante de la etapa 4 se **observa consultando**, porque la base no guarda
cuando escribio cada fila. Una observacion por muestreo llega hasta un intervalo
tarde: el sesgo es conocido, positivo y acotado por ese intervalo, y se informa
al lado del instante en lugar de descontarse ---descontar un promedio supuesto
seria inventar precision que la observacion no tiene---.

Lo que esta herramienta afirma es **que el mensaje esta en las cinco etapas y
con que contenido**. Los desfases van como referencia de una sola corrida, sobre
una maquina con lo que sea que este andando en ella: la medicion de latencia,
con sus repeticiones y su distribucion, sigue siendo la de
`medir_latencia_cadena.py`.

EL CONSUMIDOR QUE LEVANTA, Y POR QUE CON OTRA IDENTIDAD DE CLIENTE
-------------------------------------------------------------------
La etapa 3 es la memoria en proceso del consumidor, de modo que hay que tener un
consumidor **en este proceso**: el registro del servicio vive en el suyo y no se
puede mirar desde afuera. Es el consumidor real ---misma fabrica, mismos
callbacks, misma validacion, misma escritura---, y lo unico que se le cambia es
la identidad de cliente.

Ese cambio no es cosmetico. La identidad del consumidor es fija y su sesion es
persistente, las dos cosas a proposito. Dos clientes con la misma identidad no
conviven: el intermediario le quita la sesion a uno cada vez que el otro entra.
Medido el 2026-09-11 con el servicio consumidor andando, el registro del broker
mostro `disconnected: session taken over` **una vez por segundo**, el mismo
mensaje reentregado dieciseis veces y **cero filas persistidas**. Con identidad
propia los dos conviven, los dos reciben, y la fila se escribe una sola vez
porque la identidad de reinyeccion la deduplica.

Junto a la identidad se le cambian otras dos cosas, las dos de configuracion y
ninguna de conducta: escucha el topico de reproduccion y no el de vivo, y no
conserva su sesion entre corridas. Las dos estan razonadas donde se fijan, y las
dos salen del mismo hecho medido: un consumidor de rastreo que ademas carga con
el trafico ajeno ---en vivo o acumulado--- no llega a ver su propio mensaje.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

#: La identidad de cliente del consumidor que levanta el rastreo. Se fija
#: **antes** de importar la configuracion porque esta la lee del entorno al
#: cargarse, y es fija ---y no una por corrida--- para no dejarle al
#: intermediario una sesion persistente nueva cada vez que se corre esto.
#: `setdefault` deja que el entorno mande, por si hace falta forzar otra.
os.environ.setdefault("MQTT_CLIENT_ID", "tesis-rastreo-de-un-mensaje")

#: El topico en vivo, para el consumidor de este rastreo, apunta a un topico sin
#: uso. NO es una simplificacion del consumidor: es su configuracion, y la
#: configuracion dice a que escucha.
#:
#: POR QUE. El rastreo sigue un mensaje del topico de reproduccion. Con el
#: topico en vivo suscripto, el consumidor de este proceso ademas se come todo
#: lo que este publicando una captura en curso, y eso arruina la observacion por
#: dos caminos medidos el 2026-09-11 con una captura en vivo andando: el
#: registro en memoria guarda **veinte** mensajes, de modo que el rastreado se
#: cae de la lista en milisegundos ---6.501 mensajes en vivo entraron durante
#: una corrida---, y la ventana de mensajes sin confirmar se llena con trafico
#: ajeno, de modo que el mensaje rastreado espera detras de una cola que no
#: tiene nada que ver con el.
#:
#: Lo que el consumidor **hace** con un mensaje no cambia en nada.
os.environ.setdefault("MQTT_TOPIC", "tesis/telemetry/sin-uso-durante-el-rastreo")

#: La sesion del consumidor de este rastreo **no** se conserva entre corridas.
#:
#: POR QUE, SI PARA EL SERVICIO ES AL REVES. El servicio conserva su sesion
#: porque tiene que hacerse cargo de lo que se publico mientras no estaba: es su
#: trabajo. Este consumidor vive lo que dura un rastreo, y hacerse cargo de una
#: cola vieja es justamente lo que le impide ver su propio mensaje: el
#: intermediario entrega **en orden**, de modo que el mensaje rastreado queda
#: detras de todo lo acumulado. Medido el 2026-09-11, dos corridas seguidas
#: recibieron 6.501 y 1.502 mensajes de cola atrasada, y el mensaje rastreado no
#: alcanzo a llegar en treinta segundos en ninguna de las dos.
#:
#: Sin sesion conservada tampoco queda una suscripcion vieja viva en el
#: intermediario acumulando trafico entre corridas, que es de donde salia esa
#: cola. Lo que el consumidor hace con un mensaje sigue sin cambiar.
os.environ.setdefault("MQTT_SESION_PERSISTENTE", "0")

import paho.mqtt.client as mqtt  # noqa: E402

from adapters import f1_25  # noqa: E402
from backend import db, f1_capture, f1_udp, mqtt_consumer  # noqa: E402
from backend.config import MQTT_HOST, MQTT_PORT, MQTT_REPLAY_TOPIC  # noqa: E402
from backend.models import TelemetryMessage  # noqa: E402

#: Las cinco etapas, en el orden en que el mensaje las atraviesa.
#:
#: Entre la 2 y la 3 ese orden **no significa nada**: son dos suscriptores de la
#: misma entrega, y cual vea primero su copia depende del intermediario. Se
#: miden las dos ---y se las ve cruzarse--- justamente porque son observaciones
#: independientes. Lo que si seria un sintoma es que la base o la consulta
#: precedieran a la publicacion.
ETAPAS = ("generador", "intermediario", "consumidor", "base", "consulta")

TITULOS = {
    "generador": "la salida del generador",
    "intermediario": "la suscripcion al intermediario",
    "consumidor": "el registro del consumidor",
    "base": "la consulta directa a la base",
    "consulta": "la respuesta de la interfaz de consulta",
}

#: Cada cuanto se consulta la base. Es el mismo valor que usan las mediciones de
#: latencia y por el mismo motivo: tiene que ser mayor que lo que tarda la
#: consulta ---si no, el instrumento se mide a si mismo--- y chico frente a lo
#: que se espera observar.
MUESTREO_BASE_MS = 25.0

#: Cuanto se espera cada etapa antes de declararla perdida. El consumidor vacia
#: su cola cada medio segundo, asi que treinta segundos son sesenta vaciados: lo
#: que no aparecio en ese lapso no es lentitud, es ausencia.
ESPERA_MAXIMA_S = 30.0

#: Decimales con que la ruta de series devuelve un valor. No es una perdida
#: silenciosa: la ruta lo hace para poder graficar y esta escrito en su codigo.
#: Se declara aca para que la comparacion de la etapa 5 use la misma precision
#: que la ruta promete, en lugar de acusar de transformacion a un redondeo
#: declarado.
DECIMALES_DE_LA_CONSULTA = 4


# --------------------------------------------------------------------------
# Eleccion del mensaje a rastrear
# --------------------------------------------------------------------------

def mensajes_numerados(ruta: Path, inicio_utc: str, sha256: str | None):
    """Los mensajes de la captura con su numero de secuencia, como los publica.

    Replica exactamente el recorrido de `republicar_captura.publicar`: mismo
    decodificador, mismos paquetes normalizables, mismo adaptador y mismo
    contador. Si esta funcion contara distinto, el numero de secuencia de un
    rastreo no seria el mismo numero que el de una reproduccion, y las dos
    herramientas hablarian de mensajes distintos con la misma palabra.
    """

    seq = 0
    for datagrama in f1_capture.leer_captura(ruta):
        try:
            decodificado = f1_udp.decodificar(datagrama.carga)
        except f1_udp.ErrorDecodificacion:
            continue
        if decodificado["paquete"] not in f1_25.PAQUETES_NORMALIZABLES:
            continue
        for mensaje in f1_25.mensajes_desde_paquete(
                decodificado, inicio_utc, origen=f1_25.ORIGEN_REPRODUCIDO,
                captura_sha256=sha256,
                desplazamiento_captura_us=datagrama.desplazamiento_us):
            yield seq, mensaje
            seq += 1


def es_valor_distinguible(valor: object, minimo: float = 0.0) -> bool:
    """Si ese valor sirve para notar que el mensaje llego entero.

    POR QUE NO SIRVE CUALQUIER MENSAJE. Un cero, un falso o un texto vacio son
    exactamente lo que aparece cuando un dato **se pierde**: un campo sin
    completar, un valor por omision, una conversion fallida. Rastrear una
    muestra asi no distinguiria un dato conservado de un dato perdido, que es
    justo lo unico que esta herramienta existe para distinguir.
    """

    if isinstance(valor, bool):
        return valor is True
    if isinstance(valor, (int, float)):
        return float(valor) > minimo
    if isinstance(valor, str):
        return valor.strip() != ""
    return valor is not None


def elegir_mensaje(numerados, senal: str | None = None,
                   secuencia: int | None = None,
                   minimo: float = 0.0) -> tuple[int, dict] | None:
    """El mensaje a rastrear: el pedido por numero, o el primero que sirva.

    Con `secuencia` se toma **ese** mensaje y no se juzga su valor: quien pide
    un numero concreto sabe lo que pide. Sin ella se busca el primero de la
    senal cuyo valor permita notar una perdida.
    """

    for seq, mensaje in numerados:
        if secuencia is not None:
            if seq == secuencia:
                return seq, mensaje
            continue
        if mensaje["signal_name"] != senal:
            continue
        if not es_valor_distinguible(mensaje["value"], minimo):
            continue
        return seq, mensaje
    return None


def identidad_de_rastreo(sha256: str | None, seq: int, ahora: datetime) -> str:
    """La identidad de corrida de este rastreo.

    Lleva la huella de la captura para decir de donde salio el mensaje, el
    numero de secuencia para que se lea a simple vista de cual se trata, y el
    instante de la corrida por el motivo explicado arriba: sin el, un segundo
    rastreo del mismo mensaje no escribiria nada y leeria la fila del primero.
    """

    huella = (sha256 or "sin-hash")[:16]
    marca = ahora.strftime("%Y%m%dT%H%M%SZ")
    return f"rastreo:{huella}:{seq}:{marca}"


def marcar_identidad(mensaje: dict, run_id: str, seq: int) -> dict:
    """Inyecta la identidad de reinyeccion donde el resto del sistema la busca.

    Va en `metadata.extra` y no en la raiz del mensaje porque ese es el lugar
    del que `backend/db.py` la lee para promoverla a columnas. Escribirla en
    cualquier otro lado daria un mensaje valido, persistido y **no
    encontrable**: la etapa 4 informaria una perdida que no ocurrio.
    """

    extra = mensaje.setdefault("metadata", {}).setdefault("extra", {})
    extra["replay_run_id"] = run_id
    extra["replay_seq"] = seq
    return mensaje


# --------------------------------------------------------------------------
# Comparacion entre etapas
# --------------------------------------------------------------------------

def valor_comparable(valor: object, decimales: int | None = None) -> object:
    """El valor en la forma en que la etapa puede expresarlo.

    Dos transformaciones son declaradas y no defectos, asi que se contemplan en
    lugar de denunciarse:

    - la ruta de series lleva los canales binarios a 1 y 0 para poder
      graficarlos junto a los numericos;
    - y redondea a `DECIMALES_DE_LA_CONSULTA`.

    Contemplarlas aca es lo que permite que una diferencia informada sea una
    diferencia real. Todo lo demas ---una unidad cambiada, un valor movido mas
    alla del redondeo, un instante corrido--- sale como discrepancia.

    NO HAY UNA RAMA PARA LOS BINARIOS, Y NO ES UN OLVIDO. En Python un booleano
    **es** un entero, de modo que cae solo en la rama numerica y sale 1,0 o 0,0,
    que es exactamente lo que hace la ruta. Una rama aparte seria codigo que no
    cambia el resultado: se probo quitarla y ninguna prueba lo nota, que es la
    definicion de sobrar.
    """

    if isinstance(valor, (int, float)):
        numero = float(valor)
        return round(numero, decimales) if decimales is not None else numero
    return valor


def mismo_instante(uno: object, otro: object) -> bool:
    """Si dos marcas temporales son el mismo instante, escritas como sea.

    Se comparan como instantes y no como texto porque las cinco etapas los
    escriben distinto: el generador con `isoformat`, la base desde un
    `timestamptz` y la ruta de consulta desde su propio `isoformat`. Comparar
    texto contra texto acusaria de transformacion a un cambio de formato.
    """

    a = _como_instante(uno)
    b = _como_instante(otro)
    if a is None or b is None:
        return False
    return a == b


def _como_instante(valor: object) -> datetime | None:
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
    if isinstance(valor, str):
        try:
            leido = datetime.fromisoformat(valor.replace("Z", "+00:00"))
        except ValueError:
            return None
        return leido if leido.tzinfo else leido.replace(tzinfo=timezone.utc)
    return None


def discrepancias(etapas: dict[str, dict]) -> list[str]:
    """Que difiere entre la etapa 1 y cada una de las demas.

    La referencia es siempre el generador: es el unico punto de la cadena donde
    el contenido todavia no atraveso nada, de modo que comparar cada etapa
    contra la anterior esconderia una transformacion que despues se revierte.

    Una etapa ausente es una discrepancia y no un silencio: un mensaje que no
    llego es exactamente lo que hay que informar.
    """

    salida: list[str] = []
    origen = etapas.get("generador")
    if not origen:
        return ["No hay etapa de generador contra la cual comparar."]

    for nombre in ETAPAS[1:]:
        etapa = etapas.get(nombre)
        if etapa is None:
            salida.append(f"{nombre}: el mensaje no aparecio.")
            continue
        if etapa.get("ausente"):
            salida.append(f"{nombre}: el mensaje no aparecio. {etapa['ausente']}")
            continue
        if etapa.get("omitida"):
            continue
        decimales = (DECIMALES_DE_LA_CONSULTA if nombre == "consulta" else None)
        esperado = valor_comparable(origen.get("valor"), decimales)
        obtenido = valor_comparable(etapa.get("valor"), decimales)
        if esperado != obtenido:
            salida.append(
                f"{nombre}: el valor cambio, {esperado!r} contra {obtenido!r}.")
        if etapa.get("unidad") != origen.get("unidad"):
            salida.append(
                f"{nombre}: la unidad cambio, {origen.get('unidad')!r} contra "
                f"{etapa.get('unidad')!r}.")
        if not mismo_instante(origen.get("instante_del_dato"),
                              etapa.get("instante_del_dato")):
            salida.append(
                f"{nombre}: el instante del dato cambio, "
                f"{origen.get('instante_del_dato')} contra "
                f"{etapa.get('instante_del_dato')}.")
    return salida


def valor_de_la_consulta(respuesta: dict, senal: str, vehiculo: str,
                         instante: object) -> dict | None:
    """Lo que la ruta de consulta devolvio **para ese instante exacto**.

    Devuelve tambien cuantas muestras trajo la respuesta: pedir un instante y
    recibir mas de una muestra significaria que el recorte no acoto, y eso hay
    que verlo y no suponerlo.
    """

    serie = (respuesta.get("vehiculos") or {}).get(vehiculo)
    if not serie:
        return None
    marcas = serie.get("timestamp_utc") or []
    valores = serie.get(senal) or []
    for indice, marca in enumerate(marcas):
        if not mismo_instante(marca, instante):
            continue
        return {
            "valor": valores[indice] if indice < len(valores) else None,
            "unidad": (respuesta.get("unidades") or {}).get(senal),
            "instante_del_dato": marca,
            "muestras_en_la_respuesta": respuesta.get("muestras"),
        }
    return None


def valor_de_la_fila(fila: dict) -> object:
    """El valor de una fila persistida, que vive en tres columnas segun su tipo.

    La base separa numerico, booleano y texto en columnas distintas. Reunirlo
    aca es lo que permite comparar contra el valor unico que traia el mensaje.
    """

    for columna in ("value_numeric", "value_boolean", "value_text"):
        if fila.get(columna) is not None:
            valor = fila[columna]
            return float(valor) if columna == "value_numeric" else valor
    return None


# --------------------------------------------------------------------------
# Las cinco etapas, contra el sistema real
# --------------------------------------------------------------------------

class Observador:
    """Un suscriptor propio, aparte del consumidor, para ver la etapa 2.

    POR QUE NO ALCANZA CON MIRAR AL CONSUMIDOR. El consumidor **valida** lo que
    recibe: si mirara la cadena solo desde el, no podria distinguir lo que el
    intermediario entrego de lo que la validacion dejo pasar. Este suscriptor no
    valida nada y guarda los bytes crudos, de modo que la comparacion entre la
    etapa 1 y la 2 es una comparacion de huellas: o son los mismos bytes o no.
    """

    def __init__(self, run_id: str, seq: int) -> None:
        self.run_id = run_id
        self.seq = seq
        self.payload: bytes | None = None
        self.instante: float | None = None
        self.visto = threading.Event()
        self.suscripto = threading.Event()
        self.cliente = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"rastreo-observador-{int(time.time() * 1000)}",
            clean_session=True)
        self.cliente.on_connect = self._al_conectar
        self.cliente.on_subscribe = lambda *_a, **_k: self.suscripto.set()
        self.cliente.on_message = self._al_llegar

    def _al_conectar(self, cliente, userdata, flags, reason_code, properties):
        # Se suscribe con calidad uno porque la entrega se rige por el minimo
        # entre publicacion y suscripcion: suscribirse en cero dejaria el tramo
        # observado sin la garantia que el publicador si pide.
        cliente.subscribe(MQTT_REPLAY_TOPIC, qos=1)

    def _al_llegar(self, cliente, userdata, mensaje):
        # El topico es compartido: puede haber otra cosa publicando. Se guarda
        # solo el mensaje cuya identidad coincide con la que se rastrea.
        try:
            contenido = json.loads(mensaje.payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        extra = ((contenido or {}).get("metadata") or {}).get("extra") or {}
        if extra.get("replay_run_id") != self.run_id:
            return
        if extra.get("replay_seq") != self.seq:
            return
        self.payload = mensaje.payload
        self.instante = time.time()
        self.visto.set()

    def arrancar(self, espera_s: float = 10.0) -> None:
        self.cliente.connect(MQTT_HOST, MQTT_PORT, 30)
        self.cliente.loop_start()
        # Se espera el acuse de suscripcion antes de dejar publicar. Sin esa
        # espera el mensaje puede salir antes de que el intermediario sepa que
        # hay que entregarselo a nadie, y una etapa faltante por esa carrera se
        # leeria como una perdida del sistema.
        if not self.suscripto.wait(espera_s):
            raise SystemExit("El observador no logro suscribirse al "
                             "intermediario; sin el no hay etapa 2 que mirar.")

    def parar(self) -> None:
        self.cliente.loop_stop()
        self.cliente.disconnect()


def arrancar_consumidor(testigo: "TestigoDelRegistro | None" = None,
                        espera_s: float = 10.0) -> mqtt.Client:
    """Levanta el consumidor real, esperando su acuse de suscripcion.

    Se arma con la misma fabrica que usa el servicio ---mismos callbacks, mismo
    buffer, misma validacion, misma escritura--- porque un consumidor de
    mentira no probaria nada del consumidor. Lo unico que se agrega es el aviso
    de suscripcion, por el mismo motivo que en el observador.
    """

    suscripto = threading.Event()
    cliente = mqtt_consumer.crear_cliente_mqtt()
    cliente.on_subscribe = lambda *_a, **_k: suscripto.set()
    # El testigo se engancha **antes** de conectar: enganchado despues, un
    # mensaje que llegara en el medio pasaria por el callback real sin que nadie
    # mirara el registro, y la etapa 3 saldria ausente habiendo ocurrido.
    if testigo is not None:
        testigo.envolver(cliente)
    cliente.connect(MQTT_HOST, MQTT_PORT, 60)
    cliente.loop_start()
    if not suscripto.wait(espera_s):
        mqtt_consumer.detener_consumidor_mqtt(cliente)
        raise SystemExit("El consumidor no logro suscribirse al intermediario.")
    return cliente


def publicar(mensaje: dict) -> tuple[bytes, float]:
    """Publica el mensaje como lo publica el reproductor, y devuelve que salio.

    Se devuelve el payload exacto que se entrego al intermediario, no el
    diccionario: la comparacion con la etapa 2 es entre bytes, y serializar dos
    veces podria dar dos textos distintos del mismo contenido.
    """

    payload = json.dumps(mensaje).encode("utf-8")
    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                          client_id=f"rastreo-publicador-{int(time.time() * 1000)}",
                          clean_session=True)
    cliente.connect(MQTT_HOST, MQTT_PORT, 30)
    cliente.loop_start()
    try:
        entrega = cliente.publish(MQTT_REPLAY_TOPIC, payload, qos=1)
        instante = time.time()
        # Se espera la confirmacion del intermediario: sin ella, un fallo de
        # publicacion se leeria mas adelante como una perdida del consumidor.
        entrega.wait_for_publish(timeout=30)
    finally:
        cliente.loop_stop()
        cliente.disconnect()
    return payload, instante


class TestigoDelRegistro:
    """Mira el registro del consumidor **en cuanto** el consumidor lo escribe.

    `ULTIMOS_MENSAJES` es la memoria corta del consumidor real: guarda lo que
    **acepto** como valido, ya convertido al contrato interno. Es el unico punto
    de la cadena donde se ve el mensaje despues de la validacion y antes de la
    base.

    POR QUE NO SE MIRA POR MUESTREO. Ese registro conserva **veinte** mensajes.
    Mirarlo cada tantos milisegundos es una carrera contra el flujo: con trafico,
    el mensaje rastreado entra y sale de la lista entre dos miradas, y el rastreo
    informaria una etapa ausente que si ocurrio. Reproducido el 2026-09-11.

    Asi que en lugar de mirar cada tanto se mira **una vez, en el momento
    exacto**: se envuelve el callback del consumidor, se lo deja hacer su
    trabajo entero, y al volver se lee el registro que acaba de escribir. Corre
    en el mismo hilo que lo escribio, de modo que no hay carrera, no hay
    muestreo y no hay sesgo que declarar. Y no cambia lo que el consumidor hace:
    lo llama igual, con los mismos argumentos, y no toca lo que devuelve.
    """

    def __init__(self, run_id: str, seq: int) -> None:
        self.run_id = run_id
        self.seq = seq
        self.anotado: dict | None = None
        self.instante: float | None = None
        self.visto = threading.Event()

    def envolver(self, cliente: mqtt.Client) -> None:
        real = cliente.on_message

        def observado(c, u, m):
            real(c, u, m)
            if self.visto.is_set():
                return
            for anotado in reversed(mqtt_consumer.ULTIMOS_MENSAJES):
                extra = ((anotado or {}).get("metadata") or {}).get("extra") or {}
                if (extra.get("replay_run_id") == self.run_id
                        and extra.get("replay_seq") == self.seq):
                    self.anotado = anotado
                    self.instante = time.time()
                    self.visto.set()
                    return

        cliente.on_message = observado


def esperar_en_la_base(run_id: str, seq: int,
                       espera_s: float = ESPERA_MAXIMA_S) -> tuple[dict | None, float | None]:
    """Consulta la base por identidad hasta que la fila aparece.

    La consulta nombra `replay_seq IS NOT NULL` aunque la igualdad ya lo
    implique. No es redundante: el indice de trazabilidad es **parcial** y sin
    esa condicion el planificador no puede probar que lo cubre, de modo que
    recorre la tabla entera. Medido en su momento sobre cincuenta millones de
    filas, la diferencia fue de 110 segundos a 5 milisegundos.
    """

    consulta = """
        SELECT timestamp, vehicle_id, driver_id, session_id, source_type,
               signal_name, value_numeric, value_boolean, value_text, unit,
               quality_flag, replay_run_id, replay_seq,
               desplazamiento_captura_us, metadata
          FROM telemetry_messages
         WHERE replay_run_id = %s AND replay_seq = %s AND replay_seq IS NOT NULL
    """
    limite = time.time() + espera_s
    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        while time.time() < limite:
            cursor.execute(consulta, (run_id, seq))
            fila = cursor.fetchone()
            if fila is not None:
                instante = time.time()
                columnas = [d[0] for d in cursor.description]
                return dict(zip(columnas, fila)), instante
            time.sleep(MUESTREO_BASE_MS / 1000.0)
    return None, None


def url_de_consulta(base_url: str, mensaje: dict) -> str:
    """La direccion con que se le pregunta a la interfaz por ese unico instante.

    POR QUE ESTA RUTA. `series-tiempo` es la que el tablero usa para dibujar una
    senal contra el reloj, o sea la forma en que el dato **se consume**. Se le
    pide el tramo de un solo instante, que es lo mas cerca que la interfaz puede
    estar de responder por un mensaje: sus rutas hablan de series y de sesiones,
    no de numeros de secuencia.

    POR QUE SE ARMA CON EL CODIFICADOR Y NO CON UN TEXTO. Las marcas temporales
    terminan en `+00:00`, y en una cadena de consulta el signo mas **es un
    espacio**. Pegado a mano, el instante llegaria corrido o ilegible, la
    respuesta vendria vacia y el rastreo informaria una perdida que no ocurrio.
    El identificador de sesion, por su parte, lleva dos puntos y va como un
    segmento entero de la ruta.
    """

    sesion = urllib.parse.quote(mensaje["session_id"], safe="")
    consulta = urllib.parse.urlencode({
        "senales": mensaje["signal_name"],
        "vehiculos": mensaje["vehicle_id"],
        "desde": mensaje["timestamp"],
        "hasta": mensaje["timestamp"],
        # El minimo que la ruta acepta. Pedir mas puntos que muestras no agrega
        # nada: lo que acota de verdad es el tramo.
        "puntos": 50,
    })
    return f"{base_url.rstrip('/')}/sesiones/{sesion}/series-tiempo?{consulta}"


def consultar_la_interfaz(base_url: str, mensaje: dict,
                          espera_s: float = 15.0) -> tuple[dict | None, float | None, str | None]:
    """Le pregunta a la interfaz de consulta por ese instante y esa senal."""

    url = url_de_consulta(base_url, mensaje)
    try:
        with urllib.request.urlopen(url, timeout=espera_s) as respuesta:
            cuerpo = json.loads(respuesta.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        return None, None, f"{type(error).__name__}: {error}"
    return cuerpo, time.time(), None


def filas_que_chocarian(mensaje: dict) -> int:
    """Cuantas filas ya ocupan la clave de deduplicacion en vivo de este mensaje.

    POR QUE SE PREGUNTA ANTES. La insercion usa `ON CONFLICT DO NOTHING` y la
    tabla tiene un indice unico por `(vehicle_id, signal_name,
    desplazamiento_captura_us, timestamp)`. Si un rastreo anterior dejo su fila,
    este mensaje **no se escribiria** y la etapa 4 lo informaria como perdido:
    un defecto inventado por la herramienta. Se comprueba antes y se dice.
    """

    extra = (mensaje.get("metadata") or {}).get("extra") or {}
    desplazamiento = extra.get("desplazamiento_captura_us")
    if desplazamiento is None:
        return 0
    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        cursor.execute(
            """SELECT count(*) FROM telemetry_messages
                WHERE vehicle_id = %s AND signal_name = %s
                  AND desplazamiento_captura_us = %s AND timestamp = %s""",
            (mensaje["vehicle_id"], mensaje["signal_name"],
             int(desplazamiento), mensaje["timestamp"]))
        return cursor.fetchone()[0]


def filas_en_el_mismo_instante(mensaje: dict) -> list[tuple]:
    """Que otras filas comparten instante, senal y vehiculo con esta.

    Hace falta para leer la etapa 5 sin exagerar lo que prueba. La ruta de
    series agrupa por instante y vehiculo, de modo que si la sesion ya tuviera
    otra fila en ese instante la respuesta no distinguiria cual de las dos leyo.
    Con el sello de ahora no las hay ---el instante es nuevo---, pero con
    `--reloj captura` si, porque el mensaje sale de una captura ya cargada. Lo
    que se comprueba aca es **cuantos valores distintos** hay detras de esa
    respuesta: con uno solo, la respuesta es la misma mire la fila que mire.
    """

    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        cursor.execute(
            """SELECT replay_run_id, value_numeric, value_boolean, value_text,
                      unit, count(*)
                 FROM telemetry_messages
                WHERE source_type = %s AND session_id = %s AND vehicle_id = %s
                  AND signal_name = %s AND timestamp = %s
             GROUP BY 1, 2, 3, 4, 5""",
            (mensaje["source_type"], mensaje["session_id"],
             mensaje["vehicle_id"], mensaje["signal_name"],
             mensaje["timestamp"]))
        return cursor.fetchall()


def diagnosticar_escritura(mensaje: dict) -> str:
    """Repite la insercion en una transaccion que se deshace, para ver el motivo.

    POR QUE HACE FALTA. El buffer del consumidor atrapa la excepcion de
    escritura, suma uno a su contador de errores y reencola el lote. Para el
    consumidor esta bien ---no puede caerse por una fila--- pero deja al rastreo
    con una etapa ausente y **sin motivo**, que es exactamente lo que no hay que
    informar: un `NO APARECIO` pelado invita a suponer una perdida de la cadena
    cuando puede ser una negativa de la base.

    Repite la misma insercion, por el mismo camino ---mismo lote temporal, mismo
    `COPY`, mismo `ON CONFLICT`--- y la deshace. No escribe nada, y devuelve el
    motivo tal como lo dio la base.
    """

    try:
        fila = db._fila_telemetria(TelemetryMessage(**mensaje))
    except Exception as error:
        return (f"el mensaje ni siquiera valida contra el contrato interno: "
                f"{type(error).__name__}: {error}")

    with db.obtener_conexion() as conexion:
        try:
            with conexion.cursor() as cursor:
                cursor.execute(db.CREAR_LOTE_TEMPORAL_SQL)
                with cursor.copy(db.COPY_TELEMETRY_SQL) as copia:
                    copia.write_row(fila)
                cursor.execute(db.INSERT_TELEMETRY_FROM_BATCH_SQL)
        except Exception as error:
            conexion.rollback()
            return f"la base rechaza la escritura: {type(error).__name__}: {error}"
        conexion.rollback()
    return ("la insercion no falla al repetirla, de modo que la ausencia no es "
            "de la base: mirar el tramo anterior")


def borrar_lo_escrito(run_id: str, instante: str) -> int:
    """Borra las filas de este rastreo, por su identidad de corrida y su instante.

    Se borra por `replay_run_id`, que ninguna otra corrida comparte, de modo que
    la operacion no puede alcanzar una fila que no haya escrito esta.

    POR QUE TAMBIEN VA EL INSTANTE, SI LA IDENTIDAD YA ALCANZA PARA ELEGIR.
    Porque no alcanza para **no mirar**. La tabla esta particionada por
    `timestamp`, y un borrado que no lo nombra tiene que visitar todas las
    particiones, comprimidas incluidas. Medido el 2026-09-11 sobre
    `spa_original`: sin la condicion de instante, el borrado de **una** fila
    llevaba mas de 82 segundos y seguia corriendo. Con ella, el motor descarta
    todas las particiones menos una antes de empezar.
    """

    with db.obtener_conexion() as conexion:
        with conexion.cursor() as cursor:
            cursor.execute(
                "DELETE FROM telemetry_messages "
                "WHERE timestamp = %s AND replay_run_id = %s "
                "  AND replay_seq IS NOT NULL", (instante, run_id))
            borradas = cursor.rowcount
        conexion.commit()
    return borradas


# --------------------------------------------------------------------------
# Presentacion
# --------------------------------------------------------------------------

def _utc(instante: float | None) -> str:
    if instante is None:
        return "---"
    return datetime.fromtimestamp(instante, tz=timezone.utc).isoformat()


def _huella(payload: bytes | None) -> str:
    if payload is None:
        return "---"
    return hashlib.sha256(payload).hexdigest()[:16]


def imprimir_traza(etapas: dict[str, dict], mensaje: dict, run_id: str,
                   seq: int) -> None:
    print()
    print("=" * 78)
    print(f"RECORRIDO DE UN MENSAJE   {run_id}  seq {seq}")
    print("=" * 78)

    origen = etapas["generador"]["instante_observado"]
    for numero, nombre in enumerate(ETAPAS, start=1):
        etapa = etapas.get(nombre)
        print()
        print(f"ETAPA {numero}  {TITULOS[nombre]}")
        if etapa is None:
            print("  NO APARECIO")
            continue
        if etapa.get("ausente"):
            print("  NO APARECIO")
            print(f"  motivo             : {etapa['ausente']}")
            continue
        if etapa.get("omitida"):
            print(f"  omitida: {etapa['omitida']}")
            continue
        observado = etapa.get("instante_observado")
        desfase = ("---" if observado is None or origen is None
                   else f"{(observado - origen) * 1000:+.1f} ms")
        print(f"  instante observado : {_utc(observado)}   ({desfase})")
        if etapa.get("sesgo_ms"):
            print(f"  sesgo de la observacion: hasta {etapa['sesgo_ms']:.0f} ms "
                  f"tarde, por muestreo")
        print(f"  identidad          : replay_run_id={etapa.get('run_id')}  "
              f"replay_seq={etapa.get('seq')}")
        print(f"  senal y valor      : {etapa.get('senal')} = "
              f"{etapa.get('valor')!r} {etapa.get('unidad')}")
        print(f"  instante del dato  : {etapa.get('instante_del_dato')}")
        if etapa.get("huella") is not None:
            print(f"  huella del payload : sha256 {etapa['huella']}")
        for linea in etapa.get("notas", []):
            print(f"  nota               : {linea}")

    print()
    print("-" * 78)
    print(f"{'etapa':<16}{'instante observado':<34}{'desfase':>12}   valor")
    for nombre in ETAPAS:
        etapa = etapas.get(nombre)
        if etapa is None or etapa.get("ausente"):
            print(f"{nombre:<16}{'no aparecio':<34}{'---':>12}   ---")
            continue
        if etapa.get("omitida"):
            print(f"{nombre:<16}{'omitida':<34}{'---':>12}   ---")
            continue
        observado = etapa.get("instante_observado")
        desfase = ("---" if observado is None or origen is None
                   else f"{(observado - origen) * 1000:+.1f} ms")
        print(f"{nombre:<16}{_utc(observado):<34}{desfase:>12}   "
              f"{etapa.get('valor')!r} {etapa.get('unidad')}")
    print("-" * 78)


# --------------------------------------------------------------------------

def rastrear(args) -> int:
    meta_ruta = args.captura.with_suffix(args.captura.suffix + ".meta.json")
    if not meta_ruta.exists():
        raise SystemExit(
            f"Falta {meta_ruta.name}. El inicio de captura no puede inventarse: "
            "sin el, el instante del mensaje seria falso y no habria contra que "
            "compararlo.")
    meta = json.loads(meta_ruta.read_text(encoding="utf-8"))
    inicio_grabado = meta.get("inicio_utc")
    if not inicio_grabado:
        raise SystemExit("Los metadatos no declaran el inicio de captura.")

    # El sello del mensaje sale de este inicio mas el reloj de sesion. Cual de
    # los dos se usa esta razonado arriba, y se **declara en la salida**: un
    # instante del dato que no es el de la grabacion tiene que decirse, o la
    # traza se leeria como si el dato fuera de otro momento.
    if args.reloj == "ahora":
        inicio_utc = datetime.now(timezone.utc).isoformat()
    else:
        inicio_utc = inicio_grabado

    print(f"Captura   : {args.captura.name}")
    print(f"Grabada   : {inicio_grabado}")
    print(f"Reloj     : {args.reloj}  ---el mensaje se sella desde {inicio_utc}"
          + ("; es el sellado de una captura en vivo, y es el que la base "
             "acepta sobre un tramo ya comprimido---"
             if args.reloj == "ahora" else "---"))
    print("Buscando el mensaje a rastrear en el crudo...")

    elegido = elegir_mensaje(
        mensajes_numerados(args.captura, inicio_utc, meta.get("sha256")),
        senal=args.senal, secuencia=args.secuencia, minimo=args.valor_minimo)
    if elegido is None:
        raise SystemExit(
            "La captura no tiene ningun mensaje que cumpla lo pedido "
            f"(senal={args.senal!r}, secuencia={args.secuencia}, "
            f"valor minimo={args.valor_minimo}).")
    seq, mensaje = elegido

    run_id = identidad_de_rastreo(meta.get("sha256"), seq,
                                  datetime.now(timezone.utc))
    marcar_identidad(mensaje, run_id, seq)

    chocan = filas_que_chocarian(mensaje)
    if chocan:
        raise SystemExit(
            f"Ya hay {chocan} fila(s) con la clave de deduplicacion en vivo de "
            "este mensaje ---seguramente de un rastreo anterior corrido con "
            "`--conservar`---. La insercion las ignoraria en silencio y la "
            "etapa 4 informaria una perdida que no ocurrio. Borrarlas, o "
            "rastrear otro mensaje con `--secuencia`.")

    etapas: dict[str, dict] = {}
    consumidor = None
    observador = Observador(run_id, seq)
    testigo = TestigoDelRegistro(run_id, seq)
    try:
        consumidor = arrancar_consumidor(testigo=testigo)
        observador.arrancar()

        payload, instante_publicacion = publicar(mensaje)
        etapas["generador"] = {
            "instante_observado": instante_publicacion,
            "run_id": run_id, "seq": seq,
            "senal": mensaje["signal_name"], "valor": mensaje["value"],
            "unidad": mensaje["unit"],
            "instante_del_dato": mensaje["timestamp"],
            "huella": _huella(payload),
            "notas": [
                f"paquete {mensaje['metadata']['extra'].get('paquete')}, "
                f"desplazamiento de captura "
                f"{mensaje['metadata']['extra'].get('desplazamiento_captura_us')} us",
                f"el mensaje esta a "
                f"{mensaje['metadata']['extra'].get('session_time_s')} s del "
                f"comienzo de la sesion, y el sello los lleva sumados",
            ],
        }

        if observador.visto.wait(args.espera):
            recibido = json.loads(observador.payload)
            etapas["intermediario"] = {
                "instante_observado": observador.instante,
                "run_id": run_id, "seq": seq,
                "senal": recibido["signal_name"], "valor": recibido["value"],
                "unidad": recibido["unit"],
                "instante_del_dato": recibido["timestamp"],
                "huella": _huella(observador.payload),
                "notas": ["bytes identicos a los publicados"
                          if observador.payload == payload
                          else "LOS BYTES NO SON LOS PUBLICADOS"],
            }

        # SE ESPERA LA BASE, Y RECIEN DESPUES SE LEE EL REGISTRO DEL CONSUMIDOR.
        #
        # El orden de las etapas no es el orden en que conviene esperarlas. El
        # consumidor anota en su registro **antes** de escribir, de modo que una
        # fila en la base implica que el testigo ya disparo: esperar primero al
        # testigo y despues a la base seria gastar dos esperas donde alcanza una,
        # y con la cadena cargada la primera se agota antes de que el mensaje
        # llegue. Ocurrio el 2026-09-11: la espera del registro vencio a los 30 s
        # y la fila aparecio a los 35, de modo que el rastreo informo el
        # consumidor ausente habiendo pasado por el.
        fila, instante_base = esperar_en_la_base(run_id, seq, args.espera)

        if testigo.visto.is_set():
            anotado = testigo.anotado
            etapas["consumidor"] = {
                "instante_observado": testigo.instante,
                "run_id": run_id, "seq": seq,
                "senal": anotado["signal_name"], "valor": anotado["value"],
                "unidad": anotado["unit"],
                "instante_del_dato": anotado["timestamp"],
                "notas": ["leido de `ULTIMOS_MENSAJES` al volver del callback "
                          "del consumidor, ya validado contra el contrato "
                          "interno"],
            }

        if fila is not None:
            etapas["base"] = {
                "instante_observado": instante_base,
                "run_id": fila["replay_run_id"], "seq": fila["replay_seq"],
                "senal": fila["signal_name"], "valor": valor_de_la_fila(fila),
                "unidad": fila["unit"],
                "instante_del_dato": fila["timestamp"],
                "sesgo_ms": MUESTREO_BASE_MS,
                "notas": [f"columnas propias: replay_run_id y replay_seq; "
                          f"desplazamiento_captura_us="
                          f"{fila['desplazamiento_captura_us']}"],
            }
        else:
            # Una etapa ausente sin motivo invita a suponer una perdida de la
            # cadena. Se le pregunta a la base por que, antes de informar.
            etapas["base"] = {"ausente": diagnosticar_escritura(mensaje)}

        if args.sin_api:
            etapas["consulta"] = {"omitida": "pedida con --sin-api"}
        elif fila is None:
            etapas["consulta"] = {
                "omitida": "la fila no llego a la base, no hay que consultar"}
        else:
            cuerpo, instante_api, error = consultar_la_interfaz(args.api, mensaje)
            if error is not None:
                etapas["consulta"] = {"omitida": f"la interfaz no respondio: {error}"}
            else:
                leido = valor_de_la_consulta(
                    cuerpo, mensaje["signal_name"], mensaje["vehicle_id"],
                    mensaje["timestamp"])
                if leido is not None:
                    companeras = filas_en_el_mismo_instante(mensaje)
                    distintos = {(f[1], f[2], f[3], f[4]) for f in companeras}
                    etapas["consulta"] = {
                        "instante_observado": instante_api,
                        "run_id": run_id, "seq": seq,
                        "senal": mensaje["signal_name"],
                        "valor": leido["valor"], "unidad": leido["unidad"],
                        "instante_del_dato": leido["instante_del_dato"],
                        "notas": [
                            f"muestras en la respuesta: "
                            f"{leido['muestras_en_la_respuesta']}",
                            f"filas de la base en ese instante: "
                            f"{len(companeras)}, con {len(distintos)} valor(es) "
                            f"distinto(s)"
                            + ("; la respuesta es la misma mire la fila que "
                               "mire" if len(distintos) == 1 else
                               "; LA RESPUESTA DEPENDE DE CUAL MIRE"),
                            f"redondeada a {DECIMALES_DE_LA_CONSULTA} decimales "
                            f"por la ruta, que lo declara",
                        ],
                    }
    finally:
        if consumidor is not None:
            metricas = mqtt_consumer.detener_consumidor_mqtt(consumidor)
            print()
            print(f"Metricas del consumidor: recibidos={metricas.get('received')} "
                  f"persistidos={metricas.get('persisted')} "
                  f"duplicados={metricas.get('duplicates_skipped')} "
                  f"errores={metricas.get('errors')}")
        observador.parar()
        if args.conservar:
            # El instante va en la ayuda por el mismo motivo que va en el
            # borrado: sin el, el motor recorre todas las particiones.
            print(f"Se conserva la fila escrita. Borrarla con: "
                  f"delete from telemetry_messages where timestamp = "
                  f"'{mensaje['timestamp']}' and replay_run_id = '{run_id}';")
        else:
            borradas = borrar_lo_escrito(run_id, mensaje["timestamp"])
            print(f"Filas borradas al terminar: {borradas}")

    imprimir_traza(etapas, mensaje, run_id, seq)

    problemas = discrepancias(etapas)
    print()
    if problemas:
        print("VEREDICTO: hay diferencias entre etapas.")
        for problema in problemas:
            print(f"  - {problema}")
    else:
        print("VEREDICTO: las cinco etapas coinciden en valor, unidad e "
              "instante del dato.")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({
            "run_id": run_id, "seq": seq,
            "captura": args.captura.name,
            "mensaje_publicado": mensaje,
            "etapas": etapas,
            "discrepancias": problemas,
        }, indent=2, default=str), encoding="utf-8")
        print(f"Traza escrita en {args.json}")

    return 1 if problemas else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captura", type=Path)
    parser.add_argument("--senal", default="speed",
                        help="Senal del mensaje a rastrear. Por omision `speed`, "
                             "que es numerica, tiene unidad y se lee sola.")
    parser.add_argument("--secuencia", type=int, default=None,
                        help="Numero de secuencia exacto a rastrear. Sin esto se "
                             "toma el primero de la senal con valor utilizable.")
    parser.add_argument("--valor-minimo", type=float, default=0.0,
                        help="Valor por encima del cual la muestra sirve para "
                             "notar una perdida. Por omision, cualquiera mayor "
                             "que cero.")
    parser.add_argument("--espera", type=float, default=ESPERA_MAXIMA_S,
                        help="Segundos que se espera cada etapa antes de darla "
                             "por ausente. Subirlo sirve cuando la cadena esta "
                             "cargada con trafico ajeno: el mensaje llega igual, "
                             "pero detras de una cola.")
    parser.add_argument("--reloj", choices=("ahora", "captura"), default="ahora",
                        help="Desde que instante se sella el mensaje. `ahora` "
                             "sella como una captura en vivo y es lo que la "
                             "base acepta; `captura` conserva el sello original "
                             "y sirve para ver como la base rechaza escribir "
                             "sobre un tramo ya comprimido.")
    parser.add_argument("--api", default="http://127.0.0.1:8000",
                        help="Base de la interfaz de consulta.")
    parser.add_argument("--sin-api", action="store_true",
                        help="No consulta la interfaz. La etapa 5 se informa "
                             "omitida, nunca como correcta.")
    parser.add_argument("--conservar", action="store_true",
                        help="No borra la fila escrita al terminar.")
    parser.add_argument("--json", type=Path, default=None,
                        help="Escribe la traza completa en ese archivo.")
    args = parser.parse_args()

    if not args.captura.exists():
        raise SystemExit(f"No existe: {args.captura}")
    return rastrear(args)


if __name__ == "__main__":
    sys.exit(main())
