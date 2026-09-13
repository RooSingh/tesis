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
import hashlib
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


def conteos_persistidos(session_id: str,
                        vehiculos: set[str] | frozenset[str]) -> dict[str, int]:
    """Cuantas filas tiene la base por senal, **para esos vehiculos**.

    Se piden **conteos y no nombres**. Preguntar solo que senales existen fue lo
    que dejo pasar una perdida del 5,9 %: las senales estaban todas, incompletas
    todas, y una consulta por nombre las declaraba presentes.

    Y SE PIDEN PARA UNOS VEHICULOS EN CONCRETO, que es lo que faltaba. Sin ese
    filtro esta consulta sumaba todos los de la sesion contra un esperado que es
    de uno solo ---el propio, porque es lo unico que la herramienta reinyecta---
    y el resultado no era una diferencia sino un sinsentido. Medido el
    2026-09-13 sobre shanghai: «brake_position 53.445 de 10.689», cinco coches
    contra uno, con un faltante total de -3.690.012.

    Un faltante negativo no es un faltante grande: es una comparacion que no
    significa nada. Que esta herramienta exista para atrapar perdidas
    silenciosas y se equivocara de poblacion es lo que hace que valga arreglarlo
    y no redondear el numero.

    El indice de la tabla empieza por fuente y sesion, de modo que la consulta
    se resuelve sin recorrer el resto de los datos.
    """

    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        cursor.execute(
            """select signal_name, count(*) from telemetry_messages
               where source_type = %s and session_id = %s
                 and vehicle_id = any(%s)
               group by 1""",
            (f1_25.SOURCE_TYPE, session_id, list(vehiculos)),
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


def inventariar(ruta: Path, inicio_utc: str,
                sha256: str | None) -> tuple[Counter, str, set[str]]:
    """Recorre la captura contando cuantos mensajes daria cada senal.

    DEVUELVE TAMBIEN **DE QUE VEHICULOS** SON ESOS CONTEOS, y esa tercera cosa
    no es un extra: es lo que permite que la conciliacion compare poblaciones
    comparables.

    `mensajes_desde_paquete()` trae por defecto solo el vehiculo propio, y aqui
    se deja asi a proposito, porque `publicar()` y `escribir()` usan el mismo
    defecto: la herramienta entera reinyecta un vehiculo. Lo que estaba mal era
    que del otro lado se contaban todos los de la sesion. Declarando el
    conjunto, el filtro de alla lo sigue solo ---tambien el dia que alguien
    decida reinyectar la parrilla entera---.
    """

    conteo: Counter = Counter()
    session_id = None
    vehiculos: set[str] = set()
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
            vehiculos.add(mensaje["vehicle_id"])
            session_id = mensaje["session_id"]
    return conteo, session_id, vehiculos


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

    # La identidad incluye **el catalogo de senales**, y no solo la captura.
    #
    # El numero de secuencia es un contador sobre todos los mensajes que el
    # adaptador emite, de modo que **agregar una familia de senales corre toda la
    # numeracion**. Con la identidad derivada solo del archivo, dos corridas con
    # adaptadores distintos compartian espacio de identidades dandole a cada
    # numero un significado diferente, y el indice unico suprimia las
    # coincidencias creyendo que eran repeticiones.
    #
    # Ocurrio: al incorporar los nueve canales de movimiento, 34 filas quedaron
    # sin insertar porque sus numeros ya estaban ocupados por senales de neumatico
    # y de estado de la corrida anterior, con la misma marca temporal.
    #
    # La huella cambia sola cuando cambia lo que se emite, y no cambia cuando no.
    catalogo = ",".join(sorted(s["signal_name"] for s in f1_25.catalogo_de_senales()))
    huella = hashlib.sha256(catalogo.encode("utf-8")).hexdigest()[:8]
    return f"f1_25:recompletado:{hash_captura[:16]}:{huella}"


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
             faltantes: set[str], total: int, run_id: str,
             por_segundo: float = 0.0) -> int:
    """Publica por el intermediario, opcionalmente a un ritmo acotado.

    POR QUE EXISTE EL LIMITE DE RITMO. Sin el, este camino publica mas rapido de
    lo que el consumidor escribe, el intermediario descarta, y **la corrida sin
    ninguna falla ya pierde**. Medido el 2026-09-11 sobre una captura de 404.972
    filas: llegaron 100.490 una vez y 271.982 otra, con la misma captura y el
    mismo equipo. Esa varianza es el aviso de arriba hecho numero.

    Para rellenar no importa ---se reintenta y `ON CONFLICT DO NOTHING` hace el
    resto---. Importa para **medir**: sin una corrida limpia que pierda cerca de
    cero no se le puede atribuir a una falla provocada la diferencia de filas,
    porque la diferencia se pierde dentro de la variacion normal.

    Cero deja el comportamiento de siempre: publicar tan rapido como se pueda.
    """

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
                # EL RITMO SE MIDE CONTRA EL COMIENZO, NO ENTRE MENSAJES. Un
                # `sleep` fijo por mensaje acumula el error de cada espera y el
                # ritmo real termina siendo menor que el pedido. Contra el
                # comienzo, lo que se atrasa un mensaje lo recupera el siguiente.
                if por_segundo > 0:
                    debido = publicados / por_segundo
                    atraso = debido - (time.perf_counter() - inicio)
                    if atraso > 0:
                        time.sleep(atraso)
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
    resto = {s: (presente.get(s, 0), esperado[s]) for s in esperado
             if s not in completas and s not in ausentes}
    # SON CUATRO ESTADOS Y NO TRES, por el mismo motivo por el que antes fueron
    # tres y no dos. Una senal con **mas** filas de las esperadas no es una
    # senal incompleta con un faltante negativo: es otra cosa, y meterla entre
    # las incompletas fue lo que produjo «Hay -3.690.012 filas faltantes».
    #
    # Hoy la causa conocida de un exceso ---comparar contra todos los vehiculos
    # de la sesion--- esta arreglada aguas arriba, en `conteos_persistidos()`.
    # Esto es la segunda linea: si las poblaciones vuelven a separarse por otro
    # motivo, el guion lo dice en vez de restar y mostrar un numero imposible.
    incompletas = {s: par for s, par in resto.items() if par[0] < par[1]}
    excedidas = {s: par for s, par in resto.items() if par[0] > par[1]}
    return {
        "completas": completas,
        "ausentes": ausentes,
        "incompletas": incompletas,
        "excedidas": excedidas,
        "filas_faltantes": sum(esp - hay for hay, esp in incompletas.values()),
    }


def conciliar(session_id: str, esperado_por_senal: dict[str, int],
              vehiculos: set[str] | frozenset[str],
              espera_maxima_s: float = 180.0) -> dict:
    """Compara lo que la base tiene contra lo que la operacion debia dejar.

    `vehiculos` ES OBLIGATORIO, y ese es el arreglo. Antes esta consulta hacia
    `group by signal_name` sin filtrar, de modo que sumaba **todos** los
    vehiculos de la sesion contra un esperado que era de uno solo ---el propio,
    porque es lo unico que la herramienta reinyecta---. Medido el 2026-09-13
    sobre shanghai: «brake_position 53.445 de 10.689», que son exactamente
    cinco coches contra uno, y un faltante total de -3.690.012.

    Un faltante negativo no es un faltante grande: es una comparacion que no
    significa nada. Y esta comparacion existe porque una version anterior de la
    herramienta informo exito habiendo perdido el 5,9 % de las filas, asi que
    una guarda que puede equivocarse de poblacion no guarda.

    Se pide como argumento y no se adivina de la base: lo que hay que comparar
    es contra lo que **esta operacion** produce, y eso lo sabe quien recorrio la
    captura, no quien consulta la tabla.

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
                     and vehicle_id = any(%s)
                   group by 1""",
                (f1_25.SOURCE_TYPE, session_id, list(vehiculos)),
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

    # Solo cuenta como faltante lo que falta. Un exceso se declara aparte: ver
    # el comentario de los cuatro estados en `clasificar()`.
    faltantes = {
        senal: esperadas - presente.get(senal, 0)
        for senal, esperadas in esperado_por_senal.items()
        if presente.get(senal, 0) < esperadas
    }
    excesos = {
        senal: presente.get(senal, 0) - esperadas
        for senal, esperadas in esperado_por_senal.items()
        if presente.get(senal, 0) > esperadas
    }
    return {
        "esperado": sum(esperado_por_senal.values()),
        "presente": sum(presente.get(s, 0) for s in esperado_por_senal),
        "senales_incompletas": faltantes,
        "senales_excedidas": excesos,
    }


def vehiculos_persistidos(session_id: str) -> dict[str, int]:
    """Cuantas filas tiene la base **por vehiculo** para esa sesion.

    El criterio por senal no sirve para la parrilla, y confundirlos habria hecho
    que esta herramienta no escribiera nada. `signal_name` es el mismo para los
    veintidos autos ---lo que los distingue es `vehicle_id`--- de modo que
    preguntar por senal declara presente a `throttle` porque lo tiene el auto
    propio, y saltea a los veinte rivales enteros.
    """

    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        cursor.execute(
            """select vehicle_id, count(*) from telemetry_messages
               where source_type = %s and session_id = %s
               group by 1""",
            (f1_25.SOURCE_TYPE, session_id),
        )
        return dict(cursor.fetchall())


def inventariar_parrilla(
    ruta: Path, inicio_utc: str, sha256: str | None,
) -> tuple[Counter, str | None, frozenset[int]]:
    """Recorre el crudo contando por vehiculo, y de paso arma la parrilla.

    La parrilla sale del paquete de participantes, que **no se normaliza** ---no
    trae mediciones, trae identidad--- pero es el unico que dice quienes corren.
    Sin el, los veintidos lugares del arreglo se emiten enteros y los que no
    tienen piloto entran como vehiculos fantasma.

    Se recorre el archivo completo antes de escribir, y eso da algo que el
    capturador en vivo no puede tener: **la parrilla rige desde el primer
    datagrama y no desde el primer paquete de participantes**. En vivo hay que
    esperar a que llegue; sobre una captura cerrada, ya llego.
    """

    conteo: Counter = Counter()
    session_id: str | None = None
    validos: set[int] = set()

    for datagrama in f1_capture.leer_captura(ruta):
        try:
            decodificado = f1_udp.decodificar(datagrama.carga)
        except f1_udp.ErrorDecodificacion:
            continue
        if decodificado["paquete"] == "participants":
            validos |= {i for i, v in enumerate(decodificado["vehiculos"])
                        if v.get("name")}
        if decodificado["paquete"] not in f1_25.PAQUETES_NORMALIZABLES:
            continue
        solo_propio = decodificado["paquete"] in f1_25.PAQUETES_DE_BLOQUE_UNICO
        for mensaje in f1_25.mensajes_desde_paquete(
                decodificado, inicio_utc, origen=f1_25.ORIGEN_REPRODUCIDO,
                captura_sha256=sha256,
                solo_vehiculo_propio=solo_propio,
                desplazamiento_captura_us=datagrama.desplazamiento_us):
            conteo[mensaje["vehicle_id"]] += 1
            if session_id is None:
                session_id = mensaje["session_id"]

    # Los fantasmas se descuentan aca y no durante el recorrido, porque la
    # parrilla recien esta completa cuando el archivo termino.
    parrilla = frozenset(validos)
    sufijos = {f":car:{i}" for i in parrilla}
    conteo = Counter({v: n for v, n in conteo.items()
                      if any(v.endswith(s) for s in sufijos)})
    return conteo, session_id, parrilla


def clasificar_vehiculos(
    esperado: dict[str, int], presente: dict[str, int],
) -> tuple[set[str], dict[str, tuple[int, int]], set[str]]:
    """Separa los vehiculos en vacios, parciales y completos.

    Tres estados y no dos. Un vehiculo con filas **no** es un vehiculo escrito:
    contar solo si existe fue lo que dejo pasar una perdida del 5,9 % cuando el
    criterio era por senal, y el mismo error cabe aca.
    """

    vacios, parciales, completos = set(), {}, set()
    for vehiculo, esperadas in esperado.items():
        hay = presente.get(vehiculo, 0)
        if hay == 0:
            vacios.add(vehiculo)
        elif hay < esperadas:
            parciales[vehiculo] = (hay, esperadas)
        else:
            completos.add(vehiculo)
    return vacios, parciales, completos


def escribir_parrilla(ruta: Path, inicio_utc: str, sha256: str | None,
                      vehiculos: set[str], parrilla: frozenset[int],
                      total: int, run_id: str) -> dict:
    """Persiste los vehiculos pedidos, directo y sin transporte.

    Es el mismo camino que `escribir`, con el filtro corrido de senal a
    vehiculo. El auto propio queda afuera solo porque su `vehicle_id` ya figura
    persistido, no por una regla aparte: si por algun motivo faltara, se
    escribiria como cualquier otro.
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
        # Los paquetes de bloque unico describen la sesion o al vehiculo propio
        # y no admiten normalizarse para todos: pedirselo es un error, no una
        # opcion.
        solo_propio = decodificado["paquete"] in f1_25.PAQUETES_DE_BLOQUE_UNICO
        for mensaje in f1_25.mensajes_desde_paquete(
                decodificado, inicio_utc, origen=f1_25.ORIGEN_REPRODUCIDO,
                captura_sha256=sha256,
                solo_vehiculo_propio=solo_propio,
                vehiculos_validos=parrilla,
                desplazamiento_captura_us=datagrama.desplazamiento_us):
            mensaje_seq = seq
            seq += 1
            if mensaje["vehicle_id"] not in vehiculos:
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


def completar_parrilla(captura: Path, meta: dict, inicio_utc: str,
                       simular: bool, elegidos: set[int] | None = None) -> None:
    """Escribe los rivales de una sesion ya capturada.

    Por que diferido y no en vivo
    -----------------------------
    La parrilla completa produce 35.186 senales por segundo y la base absorbe
    2.770: **doce veces mas de lo que puede escribir**. Medido, no estimado. En
    vivo la cola crece sin techo y no vuelve a bajar mientras la sesion siga.

    El vehiculo propio si entra en vivo ---1.776 por segundo, comodo dentro de
    los 2.770---, que es lo que el uso pide: el conductor mira lo suyo mientras
    conduce, y a los rivales los mira despues. Un rival diferido sigue sirviendo
    para comparar; un dato propio diferido, no.

    Aca no hay restriccion de tiempo real, de modo que se escribe directo a la
    base por el mismo camino de validacion del consumidor, sin transporte. El
    intermediario es justamente el tramo donde esta herramienta perdio datos dos
    veces.
    """

    print(f"Captura : {captura.name}")
    print(f"Inicio  : {inicio_utc}")
    print("Recorriendo el crudo para inventariar la parrilla...\n")

    esperado, session_id, parrilla = inventariar_parrilla(
        captura, inicio_utc, meta.get("sha256"))
    if session_id is None:
        raise SystemExit("La captura no produjo mensajes normalizables.")

    print(f"Sesion    : {session_id}")
    print(f"Parrilla  : {len(parrilla)} vehiculos con piloto "
          f"de {len(esperado)} con telemetria")

    presente = vehiculos_persistidos(session_id)
    vacios, parciales, completos = clasificar_vehiculos(esperado, presente)

    print(f"completos : {len(completos)}")
    print(f"parciales : {len(parciales)}")
    print(f"vacios    : {len(vacios)}")

    if parciales:
        # Un vehiculo a medias no se completa reinsertando: sus filas presentes
        # no llevan la identidad de esta corrida, de modo que no chocarian
        # contra el indice unico y se duplicarian.
        print("\nHay vehiculos con filas incompletas. No se tocan: reinsertar "
              "los duplicaria. Se informan para resolverlos aparte.")
        for vehiculo, (hay, esperadas) in sorted(parciales.items())[:6]:
            print(f"  {vehiculo[-24:]:<24} {hay:>9,} de {esperadas:,}")

    if elegidos is not None:
        # El filtro se aplica **despues** de clasificar y no antes. Clasificar
        # sobre la parrilla entera es lo que permite decir cuantos quedan
        # afuera; filtrando antes, un vehiculo omitido y uno inexistente se
        # verian igual.
        sufijos = tuple(f":car:{i}" for i in sorted(elegidos))
        descartados = {v for v in vacios if not v.endswith(sufijos)}
        vacios = vacios - descartados
        print(f"\nElegidos  : {len(vacios)} de {len(vacios) + len(descartados)} "
              f"vacios ({', '.join('car:' + str(i) for i in sorted(elegidos))})")
        faltantes = {i for i in elegidos
                     if not any(v.endswith(f":car:{i}") for v in vacios)}
        if faltantes:
            print(f"  ATENCION: pedidos y no disponibles como vacios: "
                  f"{', '.join('car:' + str(i) for i in sorted(faltantes))}")

    total = sum(esperado[v] for v in vacios)
    print(f"\nFilas a escribir : {total:,}\n")

    if not vacios:
        print("Nada que escribir.")
        return
    if simular:
        for vehiculo in sorted(vacios):
            print(f"  {vehiculo[-24:]:<24} {esperado[vehiculo]:>9,}")
        print("\n(simulacion: no se escribio nada)")
        return

    run_id = identidad_de_corrida(meta, captura)
    print(f"identidad de corrida: {run_id}")
    print("Escribiendo por el camino de validacion del consumidor, "
          "sin transporte\n")

    r = escribir_parrilla(captura, inicio_utc, meta.get("sha256"),
                          vacios, parrilla, total, run_id)
    print(f"\nvalidados  : {r['validados']:,}")
    print(f"insertados : {r['insertados']:,}")
    print(f"rechazados : {r['rechazados']:,}")
    print(f"duracion   : {r['duracion_s'] / 60:.1f} min "
          f"({r['insertados'] / max(r['duracion_s'], 1):,.0f} por segundo)")

    # Se concilia contra lo que debia quedar, y no contra el error que se
    # evitaba. Que la escritura no informe fallas no dice que la base quedo
    # completa.
    print("\nConciliando contra lo esperado...")
    presente = vehiculos_persistidos(session_id)
    faltan = {v: (presente.get(v, 0), esperado[v]) for v in vacios
              if presente.get(v, 0) < esperado[v]}
    if faltan:
        print(f"  QUEDARON INCOMPLETOS {len(faltan)} de {len(vacios)}:")
        for vehiculo, (hay, esperadas) in sorted(faltan.items())[:6]:
            print(f"    {vehiculo[-24:]:<24} {hay:>9,} de {esperadas:,}")
        raise SystemExit(1)
    print(f"  los {len(vacios)} vehiculos quedaron completos")


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
    parser.add_argument("--parrilla-completa", action="store_true",
                        help="Escribe los rivales de la sesion, diferidos. "
                             "Es el complemento de capturar en vivo solo el "
                             "vehiculo propio.")
    parser.add_argument("--por-segundo", type=float, default=0.0,
                        help="Acota el ritmo de publicacion, en mensajes por "
                             "segundo. Cero ---por omision--- publica tan "
                             "rapido como se pueda. Solo aplica a --por-broker, "
                             "y sirve para medir: sin una corrida limpia que no "
                             "pierda, ninguna perdida se puede atribuir.")
    parser.add_argument("--vehiculos", default=None,
                        help="Indices separados por coma ---por ejemplo "
                             "`13,0,3,11,7`--- para escribir solo esos rivales "
                             "en lugar de todos. Los indices son los del "
                             "arreglo por auto del protocolo, que es como los "
                             "nombra el identificador de vehiculo.")
    args = parser.parse_args()

    if not args.captura.exists():
        raise SystemExit(f"No existe: {args.captura}")

    meta = leer_metadatos(args.captura)
    inicio_utc = meta.get("inicio_utc")
    if not inicio_utc:
        raise SystemExit("Los metadatos no declaran el inicio de captura.")

    if args.parrilla_completa:
        elegidos = None
        if args.vehiculos:
            try:
                elegidos = {int(x) for x in args.vehiculos.split(",") if x.strip()}
            except ValueError:
                raise SystemExit("--vehiculos espera indices enteros separados "
                                 "por coma")
        completar_parrilla(args.captura, meta, inicio_utc, args.simular, elegidos)
        return

    print(f"Captura : {args.captura.name}")
    print(f"Inicio  : {inicio_utc}")
    print("Recorriendo el crudo para inventariar...\n")

    conteo, session_id, vehiculos = inventariar(
        args.captura, inicio_utc, meta.get("sha256"))
    if session_id is None:
        raise SystemExit("La captura no produjo ningun mensaje normalizable.")

    presentes = conteos_persistidos(session_id, vehiculos)

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
                                  faltantes, total, run_id, args.por_segundo)
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
    resultado = conciliar(session_id, conteo, vehiculos)

    print(f"\nesperado : {resultado['esperado']:,}")
    print(f"presente : {resultado['presente']:,}")

    # UN EXCESO SE DICE, Y NO CONCILIA. Si la base tiene mas filas de las que la
    # captura contiene para esos vehiculos, callarlo seria el mismo error que
    # esta herramienta existe para evitar ---informar exito sobre algo sin
    # comprobar---, solo que en la otra direccion.
    if resultado.get("senales_excedidas"):
        de_mas = sum(resultado["senales_excedidas"].values())
        print(f"\nNO CONCILIA: sobran {de_mas:,} filas en "
              f"{len(resultado['senales_excedidas'])} senales.")
        for senal, sobra in sorted(resultado["senales_excedidas"].items(),
                                   key=lambda p: -p[1])[:10]:
            print(f"  {senal:<34} {sobra:>9,} de mas")
        print("\nUn exceso no se arregla reinyectando. Significa que lo contado "
              "y lo guardado no son la misma poblacion, o que hay filas "
              "repetidas: hay que averiguar cual de las dos antes de tocar nada.")
        return

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
