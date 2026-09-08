# -*- coding: utf-8 -*-
"""Reproduce una captura real contra un intermediario **aislado**.

PARA QUE SIRVE
--------------
Medir el camino en vivo del tablero ---intermediario, difusor, eventos enviados
por el servidor, navegador--- con trafico verdadero y con su temporizacion
original, sin escribir una sola fila en la base.

POR QUE NO SE USA EL INTERMEDIARIO DE SIEMPRE
---------------------------------------------
El consumidor esta suscripto a los **dos** topicos de produccion, el de vivo y
el de reproduccion. Cualquier prueba contra ese intermediario persiste una
sesion nueva junto a las reales, con una identidad que no distingue lo medido de
lo capturado. No es un riesgo teorico: el trabajo ya encontro una sesion con dos
capturas conviviendo bajo un mismo identificador, y volver a mezclar seria
repetir a proposito el problema que costo dias entender.

De modo que esto publica en **otro intermediario, en otro puerto, sin
consumidor**. Nada persiste. El backend que se mide se levanta apuntando ahi con
`MQTT_PORT`.

POR QUE NO SE USA EL CAPTURADOR
-------------------------------
Porque escribe una captura nueva en `datasets/f1_25/capturas/`, y ensuciar el
conjunto de datos reales para hacer una medicion es exactamente lo que no
corresponde. Este guion **relee una captura ya grabada**, la decodifica y la
normaliza con el mismo adaptador que usa el capturador, de modo que lo que viaja
tiene el contrato de verdad y no una forma inventada para la prueba.

QUE NO ES
---------
No es una captura en curso: es una reproducida. Lo que mide es el camino desde
el intermediario hacia adelante, no la recepcion por UDP ni el decodificado en
tiempo real, que ya estan medidos en otra parte.

USO
---
    python -B scripts/carga_viva_aislada.py CAPTURA --puerto 1884 --segundos 120
    python -B scripts/carga_viva_aislada.py CAPTURA --parrilla-completa
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import paho.mqtt.client as mqtt  # noqa: E402

from adapters import f1_25  # noqa: E402
from backend import f1_capture, f1_udp  # noqa: E402

TOPICO = "tesis/telemetry/live"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("captura", type=Path, help="archivo .f1raw ya grabado")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--puerto", type=int, default=1884,
                    help="intermediario AISLADO; 1883 es el de produccion y "
                         "tiene consumidor: no se admite por omision")
    ap.add_argument("--desde", type=float, default=60.0,
                    help="desde que segundo de la captura. Los primeros "
                         "treinta suelen ser el menu, con tres datagramas por "
                         "segundo: medir ahi no mide nada")
    ap.add_argument("--segundos", type=float, default=120.0,
                    help="cuanto reproducir, en segundos de la captura")
    ap.add_argument("--velocidad", type=float, default=1.0)
    ap.add_argument("--parrilla-completa", action="store_true",
                    help="normaliza los veinte vehiculos, no solo el propio")
    ap.add_argument("--topico", default=TOPICO)
    ap.add_argument("--json", type=Path, help="escribe el resumen")
    ap.add_argument("--acepto-escribir-en-produccion", action="store_true",
                    help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.puerto == 1883 and not args.acepto_escribir_en_produccion:
        print("NEGADO: el puerto 1883 es el intermediario de produccion y su "
              "consumidor persiste todo lo que pase por ahi.\n"
              "Levantar uno aislado:\n"
              "  docker run -d --rm --name tesis-mosquitto-aislado -p 1884:1883 \\\n"
              "    eclipse-mosquitto:2.1.2 mosquitto -c /mosquitto-no-auth.conf")
        return 2

    if not args.captura.is_file():
        print("no existe la captura: %s" % args.captura)
        return 2

    inicio_utc = _inicio_de(args.captura)

    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    cliente.connect(args.host, args.puerto, keepalive=30)
    cliente.loop_start()

    desde_us = int(args.desde * 1_000_000)
    tope_us = desde_us + int(args.segundos * 1_000_000)
    sin_normalizacion = {}
    paquetes = 0
    publicados = 0
    senales = 0
    bytes_publicados = 0
    ilegibles = 0
    arranque = time.perf_counter()
    ultimo_informe = arranque

    try:
        for dg in f1_capture.leer_captura(args.captura):
            if dg.desplazamiento_us < desde_us:
                continue
            if dg.desplazamiento_us > tope_us:
                break

            # LA TEMPORIZACION ES LA DE LA CAPTURA.
            # Cada datagrama trae cuando llego. Se espera hasta ese instante;
            # si ya paso ---porque el trabajo de normalizar tardo mas que el
            # hueco--- se emite en el acto y se sigue, que es la unica opcion
            # honesta: adelantar el reloj falsearia el caudal.
            objetivo = ((dg.desplazamiento_us - desde_us) / 1_000_000.0
                        / max(0.01, args.velocidad))
            espera = objetivo - (time.perf_counter() - arranque)
            if espera > 0:
                time.sleep(espera)

            try:
                decodificado = f1_udp.decodificar(dg.carga)
            except Exception:
                ilegibles += 1
                continue
            if not decodificado.get("decodificado"):
                continue
            paquetes += 1

            solo_propio = (not args.parrilla_completa
                           or decodificado["paquete"] in f1_25.PAQUETES_DE_BLOQUE_UNICO)
            try:
                mensajes = f1_25.mensajes_desde_paquete(
                    decodificado, inicio_utc,
                    origen=f1_25.ORIGEN_REPRODUCIDO,
                    solo_vehiculo_propio=solo_propio,
                    desplazamiento_captura_us=dg.desplazamiento_us)
            except f1_25.ErrorNormalizacion as e:
                # Hay paquetes que el adaptador no normaliza a proposito
                # ---tyre_sets, session_history, event---. Se cuentan por tipo
                # en vez de tragarse en silencio: un cero de senales sin
                # explicacion es lo que hizo perder la primera corrida.
                clave = str(e)[:70]
                sin_normalizacion[clave] = sin_normalizacion.get(clave, 0) + 1
                continue
            except Exception as e:
                clave = type(e).__name__ + ": " + str(e)[:50]
                sin_normalizacion[clave] = sin_normalizacion.get(clave, 0) + 1
                continue

            # UN ENVIO POR PAQUETE, NO UNO POR SENAL.
            #
            # Es lo que hace el capturador de verdad, y su propio codigo explica
            # por que: el cliente acepta unos 6.578 envios por segundo **sin
            # importar que lleven adentro**, de modo que mandar una senal por
            # envio topa el caudal en esa cifra y descarta el resto en la cola
            # de salida.
            #
            # Este guion publicaba de a una, y por eso medimos que el difusor
            # recibia 748 de las 1.852 senales por segundo emitidas: **el 60 %
            # que faltaba era de este generador, no del producto**. Con una
            # carga de prueba que no se parece a la real, lo que se mide es la
            # carga de prueba.
            if mensajes:
                carga = json.dumps(mensajes if len(mensajes) > 1 else mensajes[0])
                carga = carga.encode("utf-8")
                cliente.publish(args.topico, carga, qos=1)
                publicados += 1
                senales += len(mensajes)
                bytes_publicados += len(carga)

            ahora = time.perf_counter()
            if ahora - ultimo_informe >= 10.0:
                t = ahora - arranque
                print("  %5.0f s  %8d senales  %6.0f senales/s  %6.0f publicaciones/s  "
                      "%6.1f KB/s"
                      % (t, senales, senales / t, publicados / t,
                         bytes_publicados / t / 1024))
                ultimo_informe = ahora
    except KeyboardInterrupt:
        print("  interrumpido")
    finally:
        cliente.loop_stop()
        cliente.disconnect()

    t = max(0.001, time.perf_counter() - arranque)
    resumen = {
        "captura": str(args.captura),
        "clase_de_carga": "captura real reproducida con su temporizacion original",
        "alcance": "parrilla completa" if args.parrilla_completa else "solo vehiculo propio",
        "intermediario": "%s:%d" % (args.host, args.puerto),
        "aislado": args.puerto != 1883,
        "duracion_s": round(t, 1),
        "paquetes": paquetes,
        "paquetes_ilegibles": ilegibles,
        "senales": senales,
        "senales_por_s": round(senales / t, 1),
        "publicaciones_mqtt_por_s": round(publicados / t, 1),
        "senales_por_publicacion": round(senales / max(1, publicados), 1),
        "calidad_de_servicio": 1,
        "bytes_por_s": round(bytes_publicados / t, 1),
        "desde_s_de_la_captura": args.desde,
        "paquetes_sin_normalizacion": sin_normalizacion,
        "persistencia": ("ninguna: este intermediario no tiene consumidor suscripto"
                         if args.puerto != 1883 else "SE PERSISTIO en produccion"),
    }
    print()
    print(json.dumps(resumen, indent=2, ensure_ascii=False))
    if args.json:
        args.json.write_text(json.dumps(resumen, indent=2, ensure_ascii=False),
                             encoding="utf-8")
    return 0


def _inicio_de(captura: Path) -> str:
    """El instante en que empezo la captura, de sus metadatos si estan."""

    meta = captura.with_suffix(captura.suffix + ".meta.json")
    if not meta.is_file():
        meta = Path(str(captura) + ".meta.json")
    if meta.is_file():
        try:
            d = json.loads(meta.read_text(encoding="utf-8"))
            for clave in ("inicio_utc", "inicio", "comienzo_utc"):
                if d.get(clave):
                    return str(d[clave])
        except Exception:
            pass
    # Sin metadatos se usa el instante de ahora: la temporizacion **relativa**
    # es la de la captura igual, que es lo que se mide. Se declara en el
    # resumen para que nadie lea las marcas como si fueran las originales.
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
