"""Reproduce tramas CAN grabadas hacia el contrato interno.

Dos modos, y la diferencia importa
----------------------------------
**Carga (por defecto).** Valida cada mensaje con el mismo modelo que usa el
consumidor y lo inserta con la misma funcion de lote, sin pasar por el
intermediario. Es una carga masiva: no tiene restriccion de tiempo real, no tiene
dato que envejezca, y no hay razon para que atraviese un canal disenado para
descartar cuando el consumidor no da abasto. El trabajo ya perdio datos dos veces
por hacer eso.

**Transporte (`--por-broker`).** Emite por el intermediario **respetando la
temporizacion original de las tramas**, que es como se comportaria un bus
conectado. No es una forma de cargar: es la demostracion de que el Nivel A
atraviesa el mismo camino que las otras dos fuentes, y por eso emite un
subconjunto y no los millones de mensajes de la carga.

Que se declara
--------------
`source_type` es `can_real_replay`. Las tramas son **reales**, de un vehiculo que
circulaba; la emision es una **reproduccion**. La arquitectura es la misma que
aceptaria un bus en vivo, y eso es lo que se demuestra, pero no hay un vehiculo
conectado y afirmarlo seria falso.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters import can_rav4
from backend import can_capture, can_decoder, db
from backend.config import MQTT_HOST, MQTT_PORT, MQTT_REPLAY_TOPIC
from backend.models import TelemetryMessage

CAPTURAS = ROOT / "datasets" / "can" / "capturas"

#: Tamano del lote de escritura. El mismo orden de magnitud que usa el consumidor.
TAMANO_LOTE = 2000


def identidad_de_corrida(meta: dict) -> str:
    """Identifica la corrida por la captura **y por el catalogo de senales**.

    Incluir el catalogo no es adorno: el numero de secuencia es un contador sobre
    los mensajes que el adaptador emite, de modo que agregar o quitar una senal
    corre toda la numeracion. Con la identidad derivada solo del archivo, dos
    corridas con adaptadores distintos comparten espacio de identidades dandole a
    cada numero un significado diferente, y la insercion suprime las
    coincidencias creyendo que son repeticiones. Ya ocurrio con la otra fuente.

    La huella incluye tambien **la version del adaptador**, y esa parte se agrego
    despues de un segundo caso. Al descartar las tramas transmitidas por el
    sistema de asistencia, el catalogo de senales quedo exactamente igual y el
    adaptador paso a emitir **la mitad** de los mensajes: la numeracion cambio
    por completo sin que la huella del catalogo lo notara.

    La regla que sale de ahi: **la identidad tiene que incluir todo lo que
    determina la numeracion**, y el comportamiento del adaptador la determina
    tanto como la lista de senales que declara producir.
    """

    catalogo = ",".join(sorted(s["signal_name"]
                               for s in can_rav4.catalogo_de_senales()))
    firma = f"{can_rav4.VERSION_ADAPTADOR}|{catalogo}"
    huella = hashlib.sha256(firma.encode("utf-8")).hexdigest()[:8]
    return f"can:reproducido:{meta['sha256'][:16]}:{huella}"


def leer_metadatos(ruta: Path) -> dict:
    meta = ruta.with_suffix(ruta.suffix + ".meta.json")
    if not meta.exists():
        raise SystemExit(f"Falta el archivo de metadatos de {ruta.name}.")
    return json.loads(meta.read_text(encoding="utf-8"))


def inicio_del_segmento(meta: dict, base: str) -> str:
    """Instante absoluto que se le asigna al comienzo del segmento.

    El registro guarda nanosegundos relativos: **no contiene la fecha**, porque el
    conjunto es anonimo y no la publica. Se asigna un inicio declarado y se deja
    dicho que es asignado, en lugar de inventar una fecha con apariencia de real.
    """

    return base


def tramas_unicas(ruta: Path):
    """Recorre las tramas descartando las que el vehiculo reenvia entre buses.

    Un registrador que escucha varios buses ve la misma trama mas de una vez: la
    pasarela del vehiculo reenvia entre buses fisicos, y el sistema de asistencia
    reenvia hacia el suyo. **Ninguna de esas copias es una medicion nueva.**

    Verificado sobre la captura: 1.062 instantes traen la misma trama en el bus 0
    y en el 2 con bytes identicos, ademas de las 57.414 que el sistema de
    asistencia reenvia. Contarlas todas inflaria la frecuencia declarada sin que
    nada falle.

    El criterio es la **identidad de la medicion** —mismo identificador, mismo
    instante, mismos bytes— y no el numero de bus. Privilegiar un bus concreto
    seria una convencion; esto es lo que el dato significa.

    **El orden importa y costo una recarga.** La primera version quitaba las
    copias y dejaba que el adaptador descartara despues las transmitidas. Como el
    descarte de copias conserva la primera que aparece sin mirar el bus, en 15.621
    casos esa primera era una trama transmitida: el adaptador la tiraba y **la
    medicion se perdia entera**, aunque su copia en un bus fisico existiera.

    Se descarta primero lo transmitido y recien despues las copias. Asi lo que
    sobrevive es siempre una trama de bus fisico.
    """

    vistas: set[tuple[int, int, bytes]] = set()
    for tramo in can_capture.leer_captura(ruta):
        if tramo.bus >= can_rav4.BUS_TRANSMITIDO_DESDE:
            continue
        clave = (tramo.instante_ns, tramo.identificador, tramo.datos)
        if clave in vistas:
            continue
        vistas.add(clave)
        yield tramo


def cargar(ruta: Path, inicio_utc: str, run_id: str, seq_inicial: int) -> dict:
    """Valida e inserta por el camino del consumidor, sin transporte."""

    meta = leer_metadatos(ruta)
    lote: list[TelemetryMessage] = []
    validados = insertados = rechazados = 0
    seq = seq_inicial

    def descargar() -> None:
        nonlocal insertados
        if lote:
            insertados += db.insertar_telemetria_lote(lote)
            lote.clear()

    for tramo in tramas_unicas(ruta):
        if tramo.identificador not in can_decoder.IDENTIFICADORES_RESPALDADOS:
            continue
        for mensaje in can_rav4.mensajes_desde_trama(
                tramo.identificador, tramo.datos, tramo.instante_ns,
                inicio_utc, meta["segmento"], tramo.bus, meta["sha256"]):
            mensaje["metadata"]["extra"]["replay_run_id"] = run_id
            mensaje["metadata"]["extra"]["replay_seq"] = seq
            seq += 1
            try:
                lote.append(TelemetryMessage.model_validate(mensaje))
                validados += 1
            except Exception:
                rechazados += 1
                continue
            if len(lote) >= TAMANO_LOTE:
                descargar()
    descargar()
    return {"validados": validados, "insertados": insertados,
            "rechazados": rechazados, "seq_final": seq}


def emitir_por_broker(ruta: Path, inicio_utc: str, limite_s: float,
                      run_id: str | None = None, velocidad: float = 1.0) -> int:
    """Emite por el intermediario respetando la temporizacion de las tramas.

    Es la demostracion de que el Nivel A atraviesa el mismo transporte que las
    otras fuentes. Respetar los intervalos originales no es un detalle: **es lo
    que hace que la demostracion se parezca a un bus conectado** en lugar de a
    una descarga.

    Identidad de reinyeccion
    ------------------------
    Cada mensaje lleva `replay_run_id` y `replay_seq`, igual que en el camino de
    carga. **Antes no los llevaba**, y eso tenia dos consecuencias que no se
    notaban: sin esas dos claves el indice unico no aplica, de modo que **una
    segunda corrida duplicaba filas en silencio**; y ninguna medicion podia
    ubicar despues las filas de una corrida concreta. Se agregaron al medir la
    latencia con esta fuente, que necesitaba lo segundo, pero lo primero valia
    por si solo.

    Velocidad
    ---------
    `velocidad` multiplica el ritmo de emision sin alterar que se envia. Sirve
    para medir la cadena a distintas tasas con el mismo contenido; a uno, emite
    como emitiria el bus.
    """

    import paho.mqtt.client as mqtt

    meta = leer_metadatos(ruta)
    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    cliente.connect(MQTT_HOST, MQTT_PORT, 10)
    cliente.loop_start()

    publicados = 0
    seq = 0
    arranque = time.perf_counter()
    try:
        for tramo in tramas_unicas(ruta):
            transcurrido_grabacion = tramo.instante_ns / 1e9
            if transcurrido_grabacion > limite_s:
                break
            # Se espera hasta que el reloj real alcance al de la grabacion. Con
            # velocidad distinta de uno, el calendario se comprime o se estira,
            # pero se calcula siempre contra el arranque y no contra la trama
            # anterior: sumar esperas relativas acumula el error.
            objetivo = transcurrido_grabacion / velocidad
            atraso = objetivo - (time.perf_counter() - arranque)
            if atraso > 0:
                time.sleep(atraso)
            if tramo.identificador not in can_decoder.IDENTIFICADORES_RESPALDADOS:
                continue
            for mensaje in can_rav4.mensajes_desde_trama(
                    tramo.identificador, tramo.datos, tramo.instante_ns,
                    inicio_utc, meta["segmento"], tramo.bus, meta["sha256"]):
                if run_id is not None:
                    mensaje["metadata"]["extra"]["replay_run_id"] = run_id
                    mensaje["metadata"]["extra"]["replay_seq"] = seq
                # Instante en que **este** mensaje se entrega al intermediario,
                # con el reloj de esta maquina. Es lo que permite medir la
                # latencia de la cadena sin mezclarla con la espera del mensaje
                # en la emision: sin este sello, cronometrar desde el arranque
                # de la corrida le sumaria a cada mensaje el tiempo que tardo en
                # llegarle su turno. El reproductor de la fuente deportiva ya lo
                # sellaba; este no.
                mensaje["metadata"]["extra"]["published_at_utc"] = (
                    datetime.now(timezone.utc).isoformat())
                seq += 1
                cliente.publish(MQTT_REPLAY_TOPIC, json.dumps(mensaje), qos=1)
                publicados += 1
    finally:
        cliente.loop_stop()
        cliente.disconnect()
    return publicados


def conciliar(esperado: int, espera_maxima_s: float = 180.0) -> dict:
    """Compara lo que la base tiene contra lo que la operacion debia dejar.

    Corre siempre. Publicar no es guardar, y entre la confirmacion de una
    escritura y el estado del destino cabe una perdida entera.
    """

    anterior = -1
    estable_desde = None
    inicio = time.perf_counter()
    while True:
        with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
            cursor.execute(
                "select count(*) from telemetry_messages where source_type = %s",
                (can_rav4.SOURCE_TYPE,))
            presente = cursor.fetchone()[0]
        if presente == anterior:
            if estable_desde is None:
                estable_desde = time.perf_counter()
            elif time.perf_counter() - estable_desde > 5:
                break
        else:
            estable_desde = None
        anterior = presente
        if time.perf_counter() - inicio > espera_maxima_s:
            break
        time.sleep(3)
    return {"esperado": esperado, "presente": presente,
            "faltan": esperado - presente}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--segmentos", nargs="*", default=None,
                        help="Nombres de segmento. Por defecto, diez espaciados.")
    parser.add_argument("--inicio", default="2026-08-31T12:00:00+00:00",
                        help="Instante asignado al comienzo del primer segmento.")
    parser.add_argument("--por-broker", action="store_true",
                        help="Emite por el intermediario con la temporizacion "
                             "original. Es la demostracion del transporte, no "
                             "una forma de cargar.")
    parser.add_argument("--rehacer", action="store_true",
                        help="Borra lo cargado por esta fuente antes de cargar. "
                             "Es la unica operacion destructiva y solo alcanza a "
                             "can_real_replay: las otras fuentes no se tocan.")
    parser.add_argument("--segundos", type=float, default=30.0,
                        help="Duracion de la demostracion por transporte.")
    parser.add_argument("--velocidad", type=float, default=1.0,
                        help="Multiplica el ritmo de emision sin cambiar que se "
                             "envia. A uno, emite como emitiria el bus.")
    parser.add_argument("--run-id", default=None,
                        help="Identidad de reinyeccion de la corrida por "
                             "intermediario. Sin ella los mensajes no se pueden "
                             "ubicar despues ni deduplicar.")
    args = parser.parse_args()

    if args.segmentos:
        nombres = args.segmentos
    else:
        # Diez espaciados, para cubrir rutas y dispositivos distintos en lugar de
        # diez tramos consecutivos del mismo vehiculo.
        nombres = [f"sample_{i:02d}" for i in range(1, 31, 3)]

    rutas = [CAPTURAS / f"TOYOTA_RAV4_TSS2_{n}.canraw" for n in nombres]
    faltantes = [r.name for r in rutas if not r.exists()]
    if faltantes:
        raise SystemExit(f"No estan extraidos: {', '.join(faltantes)}")

    if args.por_broker:
        print(f"Demostracion de transporte: {rutas[0].name}, "
              f"{args.segundos:.0f} s de grabacion a {args.velocidad:g}x")
        print(f"  hacia {MQTT_HOST}:{MQTT_PORT} en {MQTT_REPLAY_TOPIC}\n")
        inicio = time.perf_counter()
        publicados = emitir_por_broker(rutas[0], args.inicio, args.segundos,
                                       run_id=args.run_id,
                                       velocidad=args.velocidad)
        print(f"  publicados : {publicados:,} mensajes")
        print(f"  duracion   : {time.perf_counter() - inicio:.1f} s")
        print("\nEl Nivel A atraveso el mismo transporte que las otras fuentes.")
        return

    if args.rehacer:
        # Unica operacion destructiva del reproductor, y acotada **a los
        # segmentos que esta misma corrida va a reponer**.
        #
        # Antes borraba por `source_type`, es decir la fuente entera. Con una
        # lista de segmentos acotada eso destruia lo que no iba a reponer:
        # `--segmentos sample_01 --rehacer` se llevaba las filas de los diez
        # segmentos cargados ---559.016 medidas--- y reponia las de uno solo.
        # El comentario anterior decia que lo borrado se reconstruye del registro
        # crudo, y es cierto en principio, pero **no por esta invocacion**: hacia
        # falta acordarse de correr aparte los otros nueve.
        #
        # Rehacer significa rehacer *esto*, no vaciar la fuente. Borrar por
        # identidad de corrida hace que la operacion no pueda alcanzar nunca a un
        # segmento que no se este recargando.
        identidades = [identidad_de_corrida(leer_metadatos(r)) for r in rutas]
        with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
            cursor.execute(
                "delete from telemetry_messages "
                "where replay_run_id = any(%s) and replay_seq is not null",
                (identidades,))
            borradas = cursor.rowcount
            conexion.commit()
        print(f"borradas {borradas:,} filas de {len(rutas)} segmentos "
              f"que esta corrida repone\n")

    print(f"Carga de {len(rutas)} segmentos por el camino de validacion\n")
    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        cursor.execute("select count(*) from telemetry_messages where source_type = %s",
                       (can_rav4.SOURCE_TYPE,))
        antes = cursor.fetchone()[0]

    totales: Counter = Counter()
    seq = 0
    arranque = time.perf_counter()
    for ruta in rutas:
        meta = leer_metadatos(ruta)
        run_id = identidad_de_corrida(meta)
        resultado = cargar(ruta, inicio_del_segmento(meta, args.inicio),
                           run_id, seq)
        seq = resultado["seq_final"]
        totales.update({k: v for k, v in resultado.items() if k != "seq_final"})
        print(f"  {meta['segmento']}: {resultado['insertados']:>8,} insertados, "
              f"{resultado['rechazados']} rechazados")

    transcurrido = time.perf_counter() - arranque
    print(f"\nvalidados  : {totales['validados']:,}")
    print(f"insertados : {totales['insertados']:,}")
    print(f"rechazados : {totales['rechazados']:,}")
    print(f"duracion   : {transcurrido / 60:.1f} min "
          f"({totales['insertados'] / transcurrido:,.0f} por segundo)")

    print("\nConciliando contra la base...")
    r = conciliar(antes + totales["validados"])
    print(f"  esperado : {r['esperado']:,}")
    print(f"  presente : {r['presente']:,}")
    if r["faltan"] == 0:
        print("\nCONCILIADO: la base tiene exactamente lo que la carga debia dejar.")
        return
    print(f"\nNO CONCILIA: faltan {r['faltan']:,} filas.")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
