# -*- coding: utf-8 -*-
"""Mide la latencia de la cadena, desde publicar hasta poder consultar.

Que mide exactamente
--------------------
El instante en que el publicador entrega el mensaje al intermediario, y el
instante en que la fila **ya se puede consultar** en la base. Entre los dos hay
tres cosas: el intermediario, el consumidor con su acumulacion por lotes, y la
escritura en la base.

**Los dos instantes salen del mismo reloj de la misma maquina**, de modo que no
hay sincronizacion que resolver. Eso es lo que la vuelve medible hoy: la latencia
de punta a punta ---desde que el juego genera la muestra--- exige comparar el
reloj del juego contra el nuestro, y ese problema sigue abierto.

Lo que **no** mide, entonces: el tramo entre la fuente y el publicador. Lo que
mide es el tramo que el proyecto construyo, que es el que las decisiones de
diseno pueden mejorar o empeorar.

Por que se mide contra varias tasas
-----------------------------------
El consumidor escribe cuando junta mil mensajes **o** cuando pasa medio segundo,
lo que ocurra primero. Eso predice algo que conviene comprobar antes de
afirmarlo: a **poca** carga la latencia deberia ser **mayor**, porque el mensaje
espera el temporizador; a mucha carga el lote se llena solo y no espera. La
latencia no crece con la carga de forma monotona, y medir una sola tasa daria un
numero que no representa a las demas.

Como se detecta la llegada, y el sesgo que eso introduce
--------------------------------------------------------
La base no guarda cuando escribio cada fila, de modo que la llegada se detecta
consultando. Consultar cada `muestreo` milisegundos significa que una fila se
detecta **hasta un intervalo de muestreo despues** de haber quedado disponible.
El sesgo es conocido, positivo y acotado por ese intervalo, y se informa junto
con el resultado en lugar de descontarse: descontar un promedio supuesto seria
inventar precision que la medicion no tiene.

Las filas que escribe
---------------------
Van a la tabla real, porque medir contra una tabla de juguete no mediria nada. Se
marcan con un identificador de corrida y una sesion propios, de modo que ninguna
consulta del analisis las alcanza y se pueden borrar por esa marca. La cantidad
se informa al terminar.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import paho.mqtt.client as mqtt  # noqa: E402

from backend.config import MQTT_HOST, MQTT_PORT, MQTT_REPLAY_TOPIC  # noqa: E402
from backend.db import obtener_conexion  # noqa: E402

# La sesion con que se marcan las filas de la medicion. Es deliberadamente
# reconocible: ninguna consulta del analisis la nombra, y alcanza para borrarlas.
SESION = "medicion_latencia"

# El origen con que se marcan estas filas. Va aparte y no escrito a mano en cada
# lugar porque lo usan tres cosas distintas ---el mensaje, el conteo y el
# borrado--- y un borrado que no coincida con lo escrito deja filas atras o se
# lleva puestas otras.
ORIGEN = "instrumentacion"

# Cada cuanto se consulta la base buscando las filas ya escritas. Tiene que ser
# **mayor** que lo que tarda la consulta ---si no, el instrumento se mide a si
# mismo--- y lo mas chico posible frente a la latencia esperada, porque el sesgo
# que introduce esta acotado por este valor. Con la consulta en el orden de los
# cinco milisegundos y latencias esperadas de cientos, veinticinco deja las dos
# condiciones satisfechas con margen.
MUESTREO_MS = 25.0

# Cuanto se espera despues de publicar el ultimo mensaje antes de dar por
# perdido lo que no llego. Diez veces el intervalo de vaciado del consumidor.
ESPERA_FINAL_S = 5.0


def _mensaje(corrida: str, seq: int) -> dict:
    """Un mensaje minimo pero conforme al contrato interno.

    La senal es real y la unidad es la que le corresponde: un mensaje que el
    consumidor rechazara por invalido no mide la cadena, mide la validacion.
    """

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "vehicle_id": "medicion",
        "driver_id": "0",
        "session_id": SESION,
        "lap_id": None,
        "source_type": ORIGEN,
        "signal_name": "speed",
        "value": float(seq % 300),
        "unit": "km/h",
        "quality_flag": "ok",
        "metadata": {"extra": {"replay_run_id": corrida, "replay_seq": seq}},
    }


class Vigia(threading.Thread):
    """Consulta la base en un hilo aparte y anota cuando aparece cada fila.

    Va en un hilo porque tiene que observar **mientras** se publica: si se
    esperara a terminar de publicar, la latencia de los primeros mensajes ya
    seria imposible de medir.
    """

    def __init__(self, corrida: str, muestreo_s: float) -> None:
        super().__init__(daemon=True)
        self.corrida = corrida
        self.muestreo_s = muestreo_s
        self.detectado: dict[int, float] = {}
        self.parar = threading.Event()
        self.consultas = 0
        self.consulta_vacia_s = float("nan")
        self.error: Exception | None = None

    def _verificar_que_la_consulta_no_domine(self, conn) -> None:
        """Se niega a medir si la consulta tarda mas que el intervalo pedido.

        Es la comprobacion que faltaba la primera vez. La consulta tardaba
        110 segundos, la medicion esperaba 5, y el resultado fue "no llego
        ninguna de las cuarenta" cuando las cuarenta estaban escritas. Un
        instrumento mas lento que el fenomeno no mide el fenomeno: se mide a si
        mismo, y ademas informa como perdida lo que solo no alcanzo a ver.
        """

        # La primera consulta de una conexion paga el plan y el catalogo, y
        # cuesta el triple que las siguientes. Juzgar el instrumento por ella lo
        # rechazaria por un costo que no va a volver a pagar, de modo que se
        # calienta y se mide el estado de regimen, que es el que va a regir
        # durante toda la medicion.
        medidos = []
        for _ in range(4):
            t = time.perf_counter()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT replay_seq FROM telemetry_messages "
                    "WHERE replay_run_id = %s AND replay_seq IS NOT NULL",
                    (self.corrida,))
                cur.fetchall()
            medidos.append(time.perf_counter() - t)
        conn.commit()
        tardo = statistics.median(medidos[1:])
        self.consulta_vacia_s = tardo
        if tardo > self.muestreo_s:
            raise RuntimeError(
                f"la consulta de deteccion tarda {tardo * 1000:.0f} ms y el "
                f"intervalo de muestreo es de {self.muestreo_s * 1000:.0f} ms: "
                f"la medicion informaria la lentitud de la consulta como "
                f"latencia de la cadena")

    def run(self) -> None:
        try:
            with obtener_conexion() as conn:
                self._verificar_que_la_consulta_no_domine(conn)
                while not self.parar.is_set():
                    with conn.cursor() as cur:
                        # `replay_seq IS NOT NULL` no descarta ninguna fila
                        # ---todas las de una corrida la tienen--- pero es
                        # imprescindible: el indice de trazabilidad es
                        # **parcial**, y su predicado exige las dos columnas no
                        # nulas. Sin la segunda condicion el planificador no
                        # puede probar que el indice cubre la consulta, la
                        # descarta, y recorre la tabla entera. Medido sobre
                        # cincuenta millones de filas: 110.664 ms sin ella y
                        # 4,7 ms con ella, para las mismas cuarenta filas.
                        cur.execute(
                            "SELECT replay_seq FROM telemetry_messages "
                            "WHERE replay_run_id = %s "
                            "  AND replay_seq IS NOT NULL",
                            (self.corrida,))
                        vistos = {f[0] for f in cur.fetchall()}
                    ahora = time.perf_counter()
                    self.consultas += 1
                    # Solo los que aparecen por primera vez: reanotar corre el
                    # instante de deteccion hacia adelante y agranda la latencia.
                    for s in vistos - self.detectado.keys():
                        self.detectado[s] = ahora
                    conn.commit()
                    self.parar.wait(self.muestreo_s)
        except Exception as e:  # pragma: no cover - depende de la base
            self.error = e


def contar_filas_de_la_medicion() -> int:
    """Cuantas filas de instrumentacion hay hoy en la tabla.

    Nombra `source_type` primero **a proposito**: es la columna que encabeza el
    indice, y con ella la consulta tarda decimas de segundo. Buscando solo por
    `session_id`, que va segunda, la misma consulta tarda diecisiete segundos.
    """

    with obtener_conexion() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM telemetry_messages "
            "WHERE source_type = %s AND session_id = %s", (ORIGEN, SESION))
        return cur.fetchone()[0]


def limpiar_filas_de_la_medicion() -> int:
    """Borra lo que la medicion escribio, y solo eso.

    Las dos condiciones juntas, y no solo la sesion: el borrado tiene que poder
    leerse y verificarse sin conocer el resto del esquema.
    """

    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM telemetry_messages "
                "WHERE source_type = %s AND session_id = %s", (ORIGEN, SESION))
            borradas = cur.rowcount
        conn.commit()
    return borradas


def _percentil(ordenados: list[float], p: float) -> float:
    if not ordenados:
        return float("nan")
    i = min(len(ordenados) - 1, int(round(p * (len(ordenados) - 1))))
    return ordenados[i]


def medir_una_tasa(corrida: str, mensajes: int, tasa: float,
                   muestreo_s: float) -> dict:
    """Publica a la tasa pedida y devuelve la distribucion de latencias."""

    vigia = Vigia(corrida, muestreo_s)
    vigia.start()

    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    # Holgado a proposito: limitar las confirmaciones en vuelo frenaria al
    # publicador y la tasa medida no seria la pedida.
    cliente.max_inflight_messages_set(max(20, int(tasa)))
    cliente.connect(MQTT_HOST, MQTT_PORT, 60)
    cliente.loop_start()

    publicado: dict[int, float] = {}
    periodo = 1.0 / tasa if tasa > 0 else 0.0
    arranque = time.perf_counter()
    try:
        for i in range(mensajes):
            if periodo:
                # Contra el arranque y no contra la iteracion anterior: sumar
                # esperas relativas acumula el error y la tasa real se corre.
                objetivo = arranque + i * periodo
                falta = objetivo - time.perf_counter()
                if falta > 0:
                    time.sleep(falta)
            m = _mensaje(corrida, i)
            m["metadata"]["extra"]["published_at_utc"] = (
                datetime.now(timezone.utc).isoformat())
            publicado[i] = time.perf_counter()
            cliente.publish(MQTT_REPLAY_TOPIC, json.dumps(m), qos=1)
        transcurrido = time.perf_counter() - arranque
    finally:
        cliente.loop_stop()
        cliente.disconnect()

    # Se sigue observando: el ultimo mensaje todavia esta esperando su lote.
    time.sleep(ESPERA_FINAL_S)
    vigia.parar.set()
    vigia.join(timeout=10)
    if vigia.error is not None:
        raise vigia.error

    latencias = sorted((vigia.detectado[s] - publicado[s]) * 1000
                       for s in vigia.detectado if s in publicado)
    faltantes = mensajes - len(latencias)
    return {
        "tasa_pedida": tasa,
        "tasa_lograda": mensajes / transcurrido if transcurrido else float("nan"),
        "publicados": mensajes,
        "detectados": len(latencias),
        "faltantes": faltantes,
        "consultas": vigia.consultas,
        "consulta_vacia_ms": vigia.consulta_vacia_s * 1000,
        "muestreo_ms": muestreo_s * 1000,
        "p50_ms": _percentil(latencias, 0.50),
        "p95_ms": _percentil(latencias, 0.95),
        "p99_ms": _percentil(latencias, 0.99),
        "minimo_ms": latencias[0] if latencias else float("nan"),
        "maximo_ms": latencias[-1] if latencias else float("nan"),
        "media_ms": statistics.mean(latencias) if latencias else float("nan"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tasas", type=float, nargs="+",
                    default=[1, 20, 200, 2000],
                    help="mensajes por segundo a medir, una corrida por tasa")
    # La cantidad se deriva de la duracion y no se fija igual para todas las
    # tasas: cuatrocientos mensajes son veinte segundos a veinte por segundo y
    # dos decimas a dos mil, y una corrida de dos decimas no alcanza a llenar un
    # lote ni una vez. Comparar tasas exige que cada corrida dure lo mismo.
    ap.add_argument("--duracion-s", type=float, default=20.0,
                    help="cuanto dura cada corrida; la cantidad sale de aca")
    ap.add_argument("--minimo-mensajes", type=int, default=40,
                    help="piso, para que las tasas bajas den percentiles")
    ap.add_argument("--maximo-mensajes", type=int, default=5000,
                    help="techo, para no escribir mas filas de las necesarias")
    ap.add_argument("--muestreo-ms", type=float, default=MUESTREO_MS,
                    help="cada cuanto se consulta la base")
    ap.add_argument("--etiqueta", default=None,
                    help="sufijo del identificador de corrida")
    ap.add_argument("--json", type=Path, help="escribe el resultado crudo")
    ap.add_argument("--limpiar", action="store_true",
                    help="borra al terminar las filas que la medicion escribio")
    args = ap.parse_args()

    sello = args.etiqueta or datetime.now().strftime("%Y%m%d_%H%M%S")
    resultados = []
    print(f"El consumidor escribe al juntar 1.000 mensajes o cada 0,5 s.")
    print(f"Sesgo del muestreo: hasta +{args.muestreo_ms:.0f} ms, "
          f"positivo y acotado.")
    print()
    print(f"  {'tasa pedida':>12}{'lograda':>10}{'detect':>8}{'faltan':>7}"
          f"{'p50':>9}{'p95':>9}{'p99':>9}{'min':>9}{'max':>9}")
    print("  " + "-" * 82)

    for tasa in args.tasas:
        cuantos = min(args.maximo_mensajes,
                      max(args.minimo_mensajes, int(tasa * args.duracion_s)))
        corrida = f"latencia_{sello}_{tasa:g}hz"
        r = medir_una_tasa(corrida, cuantos, tasa,
                           args.muestreo_ms / 1000.0)
        r["corrida"] = corrida
        resultados.append(r)
        print(f"  {tasa:>10.0f}/s{r['tasa_lograda']:>9.1f}/s"
              f"{r['detectados']:>8,}{r['faltantes']:>7}"
              f"{r['p50_ms']:>8.0f}m{r['p95_ms']:>8.0f}m{r['p99_ms']:>8.0f}m"
              f"{r['minimo_ms']:>8.0f}m{r['maximo_ms']:>8.0f}m")

    total = sum(r["detectados"] for r in resultados)
    print()
    print(f"  filas escritas por la medicion: {total:,}, marcadas con "
          f"session_id = '{SESION}'.")
    if args.limpiar:
        borradas = limpiar_filas_de_la_medicion()
        print(f"  borradas: {borradas:,}")
        # Se concilia contra lo que debia quedar ---cero--- y no contra lo que
        # se creia haber escrito: las corridas de prueba anteriores tambien
        # dejaron filas con esta misma marca, y contarlas de menos daria por
        # incompleta una limpieza que si termino.
        quedan = contar_filas_de_la_medicion()
        print(f"  quedan: {quedan:,}" if quedan
              else "  quedan: 0, la tabla vuelve a tener solo telemetria")
    else:
        print("  quedan en la tabla. Se borran con --limpiar, o con:")
        print(f"    DELETE FROM telemetry_messages "
              f"WHERE session_id = '{SESION}' AND source_type = '{ORIGEN}';")

    if args.json:
        args.json.write_text(json.dumps(resultados, indent=1), encoding="utf-8")
        print(f"\n  crudo en {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
