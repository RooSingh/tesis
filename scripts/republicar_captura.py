"""Vuelve a publicar una captura para completar lo que falte en la base.

Para que sirve
--------------
Cuando el adaptador aprende a normalizar canales nuevos, las capturas ya
grabadas siguen persistidas con el alcance viejo. El dato existe en el registro
crudo; lo que falta es haberlo convertido al contrato interno.

Esta herramienta relee el crudo, lo normaliza con el adaptador actual y lo
publica al broker, de modo que el consumidor lo persista por el mismo camino que
usaria una sesion en vivo. **No se escribe en la base directamente**: pasar por
el consumidor es lo que garantiza que el dato reprocesado atraviese la misma
validacion que el dato original.

Por que no pasa por el intermediario
------------------------------------
Esta herramienta perdio datos dos veces antes de llegar a esta forma, y las dos
por el mismo motivo.

La primera version publico al topico en vivo, suscripto con calidad de servicio
cero: **107.265 filas no llegaron**, el 5,9 %. La segunda publico al topico de
reproduccion con calidad de servicio uno, esperando que el intermediario encolara
en lugar de descartar: **perdio 301.755, el 16,6 %**. El intermediario declaro
889.741 mensajes descartados en su propia estadistica.

La conclusion no es que falte ajustar la calidad de servicio. **Un intermediario
de mensajeria acota lo que retiene por un consumidor lento, y esa es su conducta
correcta**: existe para transportar un flujo en vivo, donde el dato viejo no
sirve y descartarlo es lo que hay que hacer. Es la misma politica que el difusor
aplica a sus colas llenas.

Un relleno no tiene ninguna de esas restricciones. No hay nada en vivo que
proteger, no hay dato que envejezca, y no hay razon para tolerar perdida.
Forzarlo por un canal disenado para descartar es **usar la herramienta de un
problema para resolver el opuesto**.

De modo que el relleno **escribe por el mismo camino de validacion y persistencia
que usa el consumidor, sin el transporte**: valida cada mensaje con el mismo
modelo y lo inserta con la misma funcion de lote. Lo que garantizaba el paso por
el consumidor era que el dato reprocesado atravesara la misma validacion, y eso
se conserva entero. Lo que se deja de lado es un tramo que solo puede restar.

Queda `--por-broker` para el caso en que se quiera **ejercitar el transporte a
proposito**, que es una prueba del sistema y no un relleno.

Por que no puede duplicar
-------------------------
Cada mensaje viaja con una identidad `(replay_run_id, replay_seq)` y la
insercion la ignora si esa identidad ya existe. La identidad se deriva del hash
de la captura, de modo que **es la misma en cada corrida**: volver a ejecutar la
herramienta completa lo que falte y no repite lo que ya esta.

Ademas, antes de publicar se le pregunta a la base **que senales ya tiene** para
esa sesion. Eso protege un caso que la identidad no cubre: las senales
persistidas en vivo se guardaron sin identidad de reproduccion, de modo que
volver a enviarlas no chocaria con nada y se duplicarian.

Que informa
-----------
Antes de publicar declara cuantas filas va a agregar y que senales. Con
`--simular` hace solo eso, sin publicar nada.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters import f1_25
from backend import db, f1_capture, f1_udp
from backend.config import MQTT_HOST, MQTT_PORT, MQTT_REPLAY_TOPIC
from backend.models import TelemetryMessage

# Cuantos mensajes se dejan sin confirmar antes de esperar, cuando se publica
# por el intermediario. Acota la memoria del cliente sin pagar una ida y vuelta
# por mensaje.
VENTANA_SIN_CONFIRMAR = 1000

# Tamano del lote de escritura directa. Es el mismo orden de magnitud que usa el
# consumidor: suficientemente grande para amortizar la ida a la base, y chico
# para que un fallo no obligue a rehacer mucho trabajo.
TAMANO_LOTE = 2000


def conteos_persistidos(session_id: str) -> dict[str, int]:
    """Cuantas filas tiene la base por senal para esa sesion.

    Se piden **conteos y no nombres**. Preguntar solo que senales existen fue lo
    que dejo pasar una perdida del 5,9 %: las senales estaban todas, incompletas
    todas, y una consulta por nombre las declaraba presentes.

    El indice de la tabla empieza por fuente y sesion, de modo que la consulta
    se resuelve sin recorrer el resto de los datos.
    """

    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        cursor.execute(
            """select signal_name, count(*) from telemetry_messages
               where source_type = %s and session_id = %s
               group by 1""",
            (f1_25.SOURCE_TYPE, session_id),
        )
        return dict(cursor.fetchall())


def borrar_reproducidas(session_id: str, senales: set[str]) -> int:
    """Borra las filas que una reproduccion anterior dejo incompletas.

    Es la unica operacion destructiva de la herramienta y esta detras de un
    parametro explicito, nunca por defecto.

    Solo alcanza a filas cuyo origen declarado es una reproduccion: las que
    llegaron de la consola en vivo no se tocan. Esa distincion no la pone esta
    funcion, la trae cada mensaje en su procedencia, que es lo que permite
    separar el dato original del reconstruido sin depender de recordar cual era
    cual.

    Es reversible en el sentido que importa: lo borrado se reconstruye del
    registro crudo, que no se modifica nunca.
    """

    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        cursor.execute(
            """delete from telemetry_messages
               where source_type = %s and session_id = %s
                 and signal_name = any(%s)
                 and metadata->'extra'->>'origen_adquisicion' = %s""",
            (f1_25.SOURCE_TYPE, session_id, list(senales),
             f1_25.ORIGEN_REPRODUCIDO),
        )
        borradas = cursor.rowcount
        conexion.commit()
    return borradas


def leer_metadatos(ruta: Path) -> dict:
    meta = ruta.with_suffix(ruta.suffix + ".meta.json")
    if not meta.exists():
        raise SystemExit(f"Falta el archivo de metadatos de {ruta.name}. "
                         "El inicio de captura no puede inventarse: sin el, las "
                         "marcas temporales serian falsas.")
    return json.loads(meta.read_text(encoding="utf-8"))


def inventariar(ruta: Path, inicio_utc: str, sha256: str | None) -> tuple[Counter, str]:
    """Recorre la captura contando cuantos mensajes daria cada senal."""

    conteo: Counter = Counter()
    session_id = None
    for datagrama in f1_capture.leer_captura(ruta):
        try:
            decodificado = f1_udp.decodificar(datagrama.carga)
        except f1_udp.ErrorDecodificacion:
            continue
        if decodificado["paquete"] not in f1_25.PAQUETES_NORMALIZABLES:
            continue
        for mensaje in f1_25.mensajes_desde_paquete(
                decodificado, inicio_utc, origen=f1_25.ORIGEN_REPRODUCIDO,
                captura_sha256=sha256):
            conteo[mensaje["signal_name"]] += 1
            session_id = mensaje["session_id"]
    return conteo, session_id


def identidad_de_corrida(meta: dict, ruta: Path) -> str:
    """Identifica la corrida a partir de la captura, no del momento de correrla.

    Que se derive del hash y no de un reloj es lo que vuelve repetible la
    operacion: dos ejecuciones sobre la misma captura producen las mismas
    identidades, de modo que la segunda completa lo que falte en lugar de
    duplicar lo que ya esta.
    """

    hash_captura = meta.get("sha256")
    if not hash_captura:
        raise SystemExit(
            f"Los metadatos de {ruta.name} no declaran el hash de la captura. "
            "Sin el, la identidad de la corrida dependeria del momento de "
            "ejecutarla y la operacion dejaria de ser repetible."
        )
    return f"f1_25:recompletado:{hash_captura[:16]}"


def escribir(ruta: Path, inicio_utc: str, sha256: str | None,
             faltantes: set[str], total: int, run_id: str) -> dict:
    """Valida y persiste directamente, sin pasar por el intermediario.

    Usa **el mismo modelo de validacion y la misma funcion de insercion** que el
    consumidor, de modo que el dato reprocesado recibe exactamente el mismo
    tratamiento que el dato en vivo. Lo unico que no atraviesa es el transporte,
    que es el tramo donde se perdio dos veces.

    Devuelve el conteo de lo validado, lo insertado y lo rechazado. Que un
    mensaje sea rechazado por validacion es un hecho a informar, no un mensaje a
    saltear en silencio.
    """

    lote: list[TelemetryMessage] = []
    validados = insertados = rechazados = 0
    seq = 0
    inicio = time.perf_counter()

    def descargar() -> None:
        nonlocal insertados
        if lote:
            insertados += db.insertar_telemetria_lote(lote)
            lote.clear()

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
            mensaje_seq = seq
            seq += 1
            if mensaje["signal_name"] not in faltantes:
                continue
            mensaje["metadata"]["extra"]["replay_run_id"] = run_id
            mensaje["metadata"]["extra"]["replay_seq"] = mensaje_seq
            try:
                lote.append(TelemetryMessage.model_validate(mensaje))
                validados += 1
            except Exception as error:
                rechazados += 1
                if rechazados <= 3:
                    print(f"  rechazado por validacion: {type(error).__name__}")
                continue
            if len(lote) >= TAMANO_LOTE:
                descargar()
                if insertados % 100_000 < TAMANO_LOTE:
                    transcurrido = time.perf_counter() - inicio
                    print(f"  {insertados:>9,} de {total:,}  "
                          f"({insertados / transcurrido:,.0f} por segundo)")
    descargar()

    return {"validados": validados, "insertados": insertados,
            "rechazados": rechazados,
            "duracion_s": time.perf_counter() - inicio}


def publicar(ruta: Path, inicio_utc: str, sha256: str | None,
             faltantes: set[str], total: int, run_id: str) -> int:
    import paho.mqtt.client as mqtt

    cliente = mqtt.Client()
    # Sin ampliar la ventana, el cliente admite veinte mensajes sin confirmar y
    # el resto espera: a un millon ochocientas mil filas eso son horas de ida y
    # vuelta. Con la ventana ancha se confirma de a bloques.
    cliente.max_inflight_messages_set(VENTANA_SIN_CONFIRMAR)
    cliente.connect(MQTT_HOST, MQTT_PORT, 10)
    cliente.loop_start()

    publicados = 0
    ultimo = None
    # El numero de secuencia cuenta **todos** los mensajes normalizables, no
    # solo los que se publican. Contar solo los publicados haria que el
    # numero de un mismo mensaje cambiara segun que senales faltaran, y la
    # identidad dejaria de identificar nada.
    seq = 0
    inicio = time.perf_counter()
    try:
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
                mensaje_seq = seq
                seq += 1
                if mensaje["signal_name"] not in faltantes:
                    continue
                mensaje["metadata"]["extra"]["replay_run_id"] = run_id
                mensaje["metadata"]["extra"]["replay_seq"] = mensaje_seq
                ultimo = cliente.publish(MQTT_REPLAY_TOPIC, json.dumps(mensaje), qos=1)
                publicados += 1
                # Se confirma de a bloques y no mensaje por mensaje: alcanza
                # para que la cola del cliente no crezca sin limite, que es el
                # motivo real de esperar.
                if publicados % VENTANA_SIN_CONFIRMAR == 0:
                    ultimo.wait_for_publish(timeout=30)
                if publicados % 100_000 == 0:
                    transcurrido = time.perf_counter() - inicio
                    print(f"  {publicados:>9,} de {total:,}  "
                          f"({publicados / transcurrido:,.0f} por segundo)")
    finally:
        # La ultima confirmacion importa: sin ella el proceso podria terminar
        # antes de que el broker reciba la cola pendiente.
        if ultimo is not None:
            ultimo.wait_for_publish(timeout=60)
        cliente.loop_stop()
        cliente.disconnect()
    return publicados


def filas_con_identidad(session_id: str, run_id: str) -> int:
    """Cuantas filas de esa sesion llevan la identidad de esta corrida.

    Determina si una senal incompleta se puede completar sin borrar. Una fila
    con identidad choca contra el indice unico y se ignora sola; una sin
    identidad no choca contra nada y se duplicaria. La diferencia decide entre
    una operacion aditiva y una destructiva, de modo que se comprueba en lugar
    de suponerse.
    """

    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        cursor.execute(
            """select count(*) from telemetry_messages
               where source_type = %s and session_id = %s
                 and replay_run_id = %s""",
            (f1_25.SOURCE_TYPE, session_id, run_id),
        )
        return cursor.fetchone()[0]


def clasificar(esperado: dict[str, int],
               presente: dict[str, int]) -> dict[str, object]:
    """Separa las senales en completas, ausentes e incompletas.

    Son **tres** estados y no dos. La version anterior de esta herramienta
    distinguia solo presente de ausente, y por eso declaro exito con setenta y
    seis senales presentes e incompletas: cada una existia, ninguna estaba
    entera, y una consulta por nombre las daba por buenas.

    La distincion importa porque los tres estados piden acciones distintas: la
    completa no se toca, la ausente se publica, y la incompleta **no se puede
    completar publicando** —sus filas se guardaron sin identidad de
    reproduccion, de modo que reenviarlas no chocaria con nada y duplicaria—.
    Hay que borrarla y rehacerla, que es una operacion destructiva y por lo
    tanto explicita.
    """

    completas = {s for s, n in esperado.items() if presente.get(s, 0) == n}
    ausentes = {s for s in esperado if presente.get(s, 0) == 0}
    incompletas = {s: (presente.get(s, 0), esperado[s]) for s in esperado
                   if s not in completas and s not in ausentes}
    return {
        "completas": completas,
        "ausentes": ausentes,
        "incompletas": incompletas,
        "filas_faltantes": sum(esp - hay for hay, esp in incompletas.values()),
    }


def conciliar(session_id: str, esperado_por_senal: dict[str, int],
              espera_maxima_s: float = 180.0) -> dict:
    """Compara lo que la base tiene contra lo que la operacion debia dejar.

    Existe porque la version anterior de esta herramienta informo exito habiendo
    perdido el 5,9 % de las filas. La verificacion de entonces se hizo contra el
    riesgo que se estaba evitando —duplicar— y no contra el total esperado, de
    modo que no podia detectar una perdida.

    **La conciliacion es parte de la operacion y no un paso posterior que haya
    que acordarse de hacer.** Una operacion masiva que no se concilia no esta
    terminada: esta sin verificar.

    El consumidor persiste por lotes y a su propio ritmo, de modo que se espera
    a que el conteo deje de crecer antes de comparar. Un conteo que todavia sube
    no es un faltante.
    """

    anterior = -1
    estable_desde = None
    inicio = time.perf_counter()

    while True:
        with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
            cursor.execute(
                """select signal_name, count(*) from telemetry_messages
                   where source_type = %s and session_id = %s
                   group by 1""",
                (f1_25.SOURCE_TYPE, session_id),
            )
            presente = dict(cursor.fetchall())

        total = sum(presente.values())
        if total == anterior:
            if estable_desde is None:
                estable_desde = time.perf_counter()
            # Dos lecturas iguales separadas por unos segundos: el consumidor
            # termino de drenar.
            elif time.perf_counter() - estable_desde > 5:
                break
        else:
            estable_desde = None
            print(f"  el consumidor sigue guardando: {total:,} filas")
        anterior = total

        if time.perf_counter() - inicio > espera_maxima_s:
            print(f"  se corto la espera a los {espera_maxima_s:.0f} s")
            break
        time.sleep(4)

    faltantes = {
        senal: esperadas - presente.get(senal, 0)
        for senal, esperadas in esperado_por_senal.items()
        if presente.get(senal, 0) != esperadas
    }
    return {
        "esperado": sum(esperado_por_senal.values()),
        "presente": sum(presente.get(s, 0) for s in esperado_por_senal),
        "senales_incompletas": faltantes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captura", type=Path)
    parser.add_argument("--simular", action="store_true",
                        help="Informa que se publicaria, sin publicar nada.")
    parser.add_argument("--por-broker", action="store_true",
                        help="Publica por el intermediario en lugar de escribir "
                             "directo. Sirve para ejercitar el transporte a "
                             "proposito; no es la forma de rellenar.")
    parser.add_argument("--limpiar-parciales", action="store_true",
                        help="Borra las filas de reproducciones anteriores que "
                             "quedaron incompletas, para poder rehacerlas. No "
                             "toca las filas capturadas en vivo.")
    args = parser.parse_args()

    if not args.captura.exists():
        raise SystemExit(f"No existe: {args.captura}")

    meta = leer_metadatos(args.captura)
    inicio_utc = meta.get("inicio_utc")
    if not inicio_utc:
        raise SystemExit("Los metadatos no declaran el inicio de captura.")

    print(f"Captura : {args.captura.name}")
    print(f"Inicio  : {inicio_utc}")
    print("Recorriendo el crudo para inventariar...\n")

    conteo, session_id = inventariar(args.captura, inicio_utc, meta.get("sha256"))
    if session_id is None:
        raise SystemExit("La captura no produjo ningun mensaje normalizable.")

    presentes = conteos_persistidos(session_id)

    estado = clasificar(conteo, presentes)
    completas = estado["completas"]
    vacias = estado["ausentes"]
    parciales = estado["incompletas"]

    print(f"Sesion             : {session_id}")
    print(f"Senales en el crudo: {len(conteo)}")
    print(f"  completas        : {len(completas)}")
    print(f"  ausentes         : {len(vacias)}")
    print(f"  incompletas      : {len(parciales)}")

    run_id = identidad_de_corrida(meta, args.captura)

    if parciales:
        faltan = sum(esp - hay for hay, esp in parciales.values())
        print(f"\nHay {faltan:,} filas faltantes en senales que ya tienen datos.")
        for senal, (hay, esperadas) in sorted(parciales.items())[:6]:
            print(f"  {senal:<34} {hay:>8,} de {esperadas:,}")
        if len(parciales) > 6:
            print(f"  ... y {len(parciales) - 6} senales mas")

        # Que se pueda completar sin borrar no depende de cuantas filas falten,
        # sino de si las presentes llevan identidad de corrida. Con identidad,
        # reinsertarlas choca contra el indice unico y se ignoran solas.
        con_identidad = filas_con_identidad(session_id, run_id)
        completables = con_identidad > 0

        print(f"\nfilas con identidad de esta corrida: {con_identidad:,}")
        if completables:
            print("Se pueden completar sin borrar: reinsertar lo que falta no "
                  "duplica, porque lo presente choca contra el indice unico.")
            vacias |= set(parciales)
            parciales = {}
        else:
            print("No se pueden completar reinsertando: lo presente se guardo "
                  "sin identidad de corrida, de modo que no chocaria contra "
                  "nada y se duplicaria.")
            if not args.limpiar_parciales:
                print("\nPara rehacerlas hay que borrar primero lo incompleto. "
                      "Volver a ejecutar con --limpiar-parciales.")
                if not vacias:
                    raise SystemExit(1)
            elif not args.simular:
                borradas = borrar_reproducidas(session_id, set(parciales))
                print(f"\nborradas {borradas:,} filas de reproducciones anteriores")
                vacias |= set(parciales)
                parciales = {}

    faltantes = vacias
    total = sum(conteo[senal] for senal in faltantes)
    print(f"\nFilas a publicar   : {total:,}\n")

    if not faltantes:
        print("Nada que publicar.")
        # Se concilia igual: que no haya nada que publicar no es lo mismo que
        # que la base este completa, y confundirlos fue el defecto original.
    else:
        if args.simular:
            for senal in sorted(faltantes):
                print(f"  {senal:<34} {conteo[senal]:>8,}")
            print("\n(simulacion: no se publico nada)")
            return

        print(f"identidad de corrida: {run_id}")

        if args.por_broker:
            print(f"Publicando a {MQTT_HOST}:{MQTT_PORT} en {MQTT_REPLAY_TOPIC}")
            print("AVISO: el intermediario descarta cuando el consumidor no da "
                  "abasto. Este camino sirve para ejercitar el transporte, no "
                  "para rellenar.\n")
            inicio = time.perf_counter()
            publicados = publicar(args.captura, inicio_utc, meta.get("sha256"),
                                  faltantes, total, run_id)
            transcurrido = time.perf_counter() - inicio
            print(f"\npublicados : {publicados:,}")
            print(f"duracion   : {transcurrido / 60:.1f} min "
                  f"({publicados / transcurrido:,.0f} por segundo)")
        else:
            print("Escribiendo por el camino de validacion del consumidor, "
                  "sin transporte\n")
            r = escribir(args.captura, inicio_utc, meta.get("sha256"),
                         faltantes, total, run_id)
            print(f"\nvalidados  : {r['validados']:,}")
            print(f"insertados : {r['insertados']:,}")
            print(f"rechazados : {r['rechazados']:,}")
            print(f"duracion   : {r['duracion_s'] / 60:.1f} min "
                  f"({r['insertados'] / r['duracion_s']:,.0f} por segundo)")

    if args.simular:
        return

    # Publicar no es guardar. La confirmacion del broker dice que el broker
    # recibio, no que el consumidor haya persistido: entre esas dos
    # afirmaciones cabe una perdida entera, y esta conciliacion existe para que
    # no quepa en silencio. Corre siempre, tambien cuando no hubo nada que
    # publicar.
    print("\nConciliando contra la base...")
    resultado = conciliar(session_id, conteo)

    print(f"\nesperado : {resultado['esperado']:,}")
    print(f"presente : {resultado['presente']:,}")

    if not resultado["senales_incompletas"]:
        print("\nCONCILIADO: la base tiene exactamente lo que la captura contiene.")
        return

    perdidas = sum(resultado["senales_incompletas"].values())
    print(f"\nNO CONCILIA: faltan {perdidas:,} filas en "
          f"{len(resultado['senales_incompletas'])} senales.")
    for senal, falta in sorted(resultado["senales_incompletas"].items(),
                               key=lambda x: -x[1])[:10]:
        print(f"  {senal:<34} faltan {falta:,}")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
