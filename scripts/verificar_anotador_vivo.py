# -*- coding: utf-8 -*-
"""Confronta el anotador en vivo con la lectura posterior sobre la misma captura.

Los dos leen los mismos canales con los mismos umbrales, pero por caminos
distintos: el posterior arma marcos completos desde el archivo, y el de vivo
recibe senales sueltas e intercaladas y tiene que reconstruir el instante. **Si
los dos no coinciden sobre una captura ya interpretada, uno de los dos esta
mal**, y este guion es lo que lo detecta.

Sirve ademas para medir que se pierde por un canal ausente: el deslizamiento de
rueda se decodifica pero todavia no forma parte del contrato interno, de modo que
en vivo esa regla no puede evaluarse. Corriendo con `--sin-deslizamiento` se ve
exactamente cuantas anotaciones deja de haber, que es el numero que hace
discutible si vale la pena publicar ese paquete.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adapters import f1_25 as adaptador_f1_25  # noqa: E402
from backend import anotador_vivo, f1_capture, f1_udp  # noqa: E402


#: Que campo de que paquete alimenta alguna regla. Es un subconjunto deliberado:
#: solo lo que alguna regla mira.
#:
#: EL NOMBRE Y LA ESCALA DE CADA SENAL SALEN DEL ADAPTADOR, NO DE ESTA TABLA.
#: Aca vivian escritos a mano ---`throttle` y `brake`, en fraccion de uno--- y el
#: 2026-09-10 el anotador paso a leer los del contrato, `throttle_position` y
#: `brake_position` en porcentaje, que es lo que llega en vivo. Esta tabla siguio
#: emitiendo los viejos. Sin acelerador, la regla de perdida de tren trasero no se
#: evaluaba nunca; sin freno, cada frenada parecia una caida brusca de velocidad.
#: Las pruebas sobre las capturas reales pasaron de 9 y 15 incidentes a 32 y 37, y
#: la de control de traccion a cero contra cero. Tomando nombre y factor del
#: adaptador, lo que se reproduce es lo que el anotador recibe en vivo.
CANALES = {
    "car_telemetry": ("speed_kmh", "throttle", "brake"),
    "lap_data": ("lap_distance_m", "current_lap_num", "current_lap_invalid"),
    # El lateral no alimenta ninguna regla: alimenta el aprendizaje del
    # circuito, que es lo que permite decir "curva 7" en lugar de "metro 2.105".
    "motion": ("g_force_vertical", "g_force_lateral"),
}

POR_RUEDA = {
    "car_telemetry": ("surface_type",),
    "motion_ex": ("wheel_slip_ratio",),
}

SUFIJO = {
    "trasera_izquierda": "rear_left", "trasera_derecha": "rear_right",
    "delantera_izquierda": "front_left", "delantera_derecha": "front_right",
}


def mensajes(ruta: Path, con_deslizamiento: bool = True):
    """Convierte la captura en la misma clase de mensajes que viajan en vivo."""

    origen = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()
    for datagrama in f1_capture.leer_captura(ruta):
        try:
            decodificado = f1_udp.decodificar(datagrama.carga)
        except Exception:
            continue
        if not decodificado.get("decodificado"):
            continue
        nombre = decodificado["paquete"]
        marca = origen + decodificado["cabecera"]["session_time"]

        # Los paquetes de bloque unico —`motion_ex` entre ellos— describen al
        # vehiculo propio y no llevan arreglo por vehiculo, de modo que sus
        # campos quedan bajo otra clave.
        propio = decodificado.get("vehiculo_propio") or decodificado.get("sesion")
        if propio is None:
            continue

        mapa = adaptador_f1_25.MAPAS_POR_PAQUETE.get(nombre, {})
        for campo in CANALES.get(nombre, ()):
            if campo not in propio or campo not in mapa:
                continue
            senal, unidad, factor = mapa[campo]
            crudo = propio[campo]
            # La misma conversion que hace el adaptador al publicar.
            if unidad == "bool":
                valor = bool(crudo)
            elif factor == 1.0:
                valor = crudo
            else:
                valor = round(crudo * factor, 4)
            yield {"signal_name": senal, "value": valor, "timestamp": marca}

        for campo in POR_RUEDA.get(nombre, ()):
            if campo not in propio:
                continue
            base = adaptador_f1_25.SENALES_POR_RUEDA[campo][0]
            if base == "wheel_slip_ratio" and not con_deslizamiento:
                continue
            for rueda, valor in propio[campo].items():
                yield {"signal_name": f"{base}_{SUFIJO.get(rueda, rueda)}",
                       "value": valor, "timestamp": marca}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captura", type=Path)
    parser.add_argument("--sin-deslizamiento", action="store_true",
                        help="Corre como corria antes en vivo: sin ese canal.")
    parser.add_argument("--minimo-duracion", type=float, default=0.0,
                        help="Ignora incidentes mas cortos que esto, en segundos.")
    args = parser.parse_args()

    anotador = anotador_vivo.Anotador()
    for m in mensajes(args.captura, con_deslizamiento=not args.sin_deslizamiento):
        anotador.observar(m)
    anotador.cerrar_pendiente()

    # Se lee la lista conservada y no las emisiones: un incidente se emite dos
    # veces —al empezar y al cerrarse— y son el mismo incidente.
    incidentes = [a for a in anotador.anotaciones
                  if a["nivel"] == "incidente"
                  and a["duracion_s"] >= args.minimo_duracion]

    print(f"{args.captura.name}")
    print(f"deslizamiento disponible: "
          f"{'no' if args.sin_deslizamiento else 'si'}")
    catalogo = anotador.catalogo
    print(f"circuito aprendido: {len(catalogo.curvas)} curvas de "
          f"{catalogo.vueltas_usadas} vueltas limpias")
    print(f"incidentes: {len(incidentes)}\n")

    for a in incidentes:
        lugar = a.get("lugar") or (
            f"metro {a['distancia_m']:,.0f}" if a.get("distancia_m") else "sin ubicar")
        print(f"  vuelta {a.get('vuelta', '?')}, {lugar}: {a['titulo']}")
        print(f"      {a['detalle']}")
        if "sospecha" in a:
            print(f"      se sospecha que {a['sospecha']}: "
                  f"{a['sospecha_evidencia']}")
        else:
            print("      sin antecedente en los canales")


if __name__ == "__main__":
    main()
