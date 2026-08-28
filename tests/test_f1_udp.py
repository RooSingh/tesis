"""Pruebas del decodificador del protocolo UDP de F1 25.

Que prueban y que no
--------------------
Los datagramas de prueba se construyen con `struct.pack` usando **las mismas
cadenas de formato que el decodificador**. Eso es circular en un sentido que
conviene declarar: si una cadena de formato estuviera equivocada, el constructor
y el decodificador fallarian del mismo modo y la prueba pasaria igual.

Lo que rompe la circularidad son las pruebas del primer grupo, que comparan
contra **29, 1285 y 1352**. Esos numeros salen de la especificacion oficial de
EA, no de este codigo. Un campo de mas o de menos hace que no cierren.

Queda un tercer nivel de verificacion que estas pruebas **no** cubren: que los
valores signifiquen lo que la especificacion dice que significan. Eso exige
contrastar contra el tablero del propio juego durante una captura real. Hasta
entonces el decodificador esta **verificado pero no validado**.
"""

from __future__ import annotations

import struct
import unittest

from backend import f1_udp


# --------------------------------------------------------------------------- #
# Constructores de datagramas de prueba
# --------------------------------------------------------------------------- #

def _cabecera(packet_id: int, packet_format: int = 2025, indice_propio: int = 0) -> bytes:
    """Arma una cabecera valida de 29 bytes."""

    return struct.pack(
        f1_udp.CABECERA_FMT,
        packet_format,   # m_packetFormat
        25,              # m_gameYear
        1,               # m_gameMajorVersion
        5,               # m_gameMinorVersion
        1,               # m_packetVersion
        packet_id,       # m_packetId
        0xDEADBEEF,      # m_sessionUID
        12.5,            # m_sessionTime
        100,             # m_frameIdentifier
        100,             # m_overallFrameIdentifier
        indice_propio,   # m_playerCarIndex
        255,             # m_secondaryPlayerCarIndex
    )


def _vehiculo_telemetria(velocidad: int, marcha: int) -> bytes:
    """Arma los 60 bytes de telemetria de un vehiculo."""

    return struct.pack(
        f1_udp.CAR_TELEMETRY_FMT,
        velocidad, 0.85, -0.12, 0.0, 0, marcha, 11500, 1, 62, 0b101,
        420, 415, 410, 405,          # temperaturas de freno
        95, 94, 93, 92,              # temperatura de superficie de neumatico
        105, 104, 103, 102,          # temperatura interna de neumatico
        108,                         # temperatura de motor
        23.5, 23.4, 21.9, 21.8,      # presiones
        0, 0, 0, 0,                  # tipo de superficie
    )


def datagrama_telemetria(indice_propio: int = 3, marcha_propia: int = -1) -> bytes:
    """Paquete 6 completo, con velocidad distinta por vehiculo.

    La velocidad es `300 + indice` a proposito: permite detectar que los
    desplazamientos por vehiculo esten bien calculados. Si estuvieran corridos,
    los tamanos cerrarian igual y los datos apareceran mezclados entre autos.
    """

    cuerpo = b"".join(
        _vehiculo_telemetria(300 + i, marcha_propia if i == indice_propio else 7)
        for i in range(f1_udp.VEHICULOS)
    )
    cola = struct.pack(f1_udp.CAR_TELEMETRY_COLA_FMT, 255, 255, 8)
    return _cabecera(6, indice_propio=indice_propio) + cuerpo + cola


def datagrama_vueltas(indice_propio: int = 0) -> bytes:
    """Paquete 2 completo, con numero de vuelta distinto por vehiculo."""

    cuerpo = b""
    for i in range(f1_udp.VEHICULOS):
        cuerpo += struct.pack(
            f1_udp.LAP_DATA_FMT,
            90123, 45678,        # ultima vuelta, vuelta actual, en ms
            28500, 0,            # sector 1
            31200, 0,            # sector 2
            1500, 0,             # delta al de adelante
            4200, 0,             # delta al lider
            1234.5, 56789.0, 0.0,  # distancias y delta de coche de seguridad
            i + 1,               # posicion
            12,                  # vuelta actual
            0, 1, 1, 0, 0, 0, 0, 0, 0,  # estado de boxes, sector, sanciones
            i + 1,               # posicion de grilla
            4, 2, 0,             # estado del piloto, resultado, cronometro de boxes
            0, 0, 0,             # tiempos de boxes y sancion pendiente
            318.4,               # velocidad de trampa
            9,                   # vuelta de la trampa
        )
    cola = struct.pack(f1_udp.LAP_DATA_COLA_FMT, 255, 255)
    return _cabecera(2, indice_propio=indice_propio) + cuerpo + cola


def datagrama_sin_decodificador() -> bytes:
    """Paquete 1, Session: reconocido y validado por tamano, no decodificado."""

    tamano = f1_udp.PAQUETES[1]["tamano"]
    relleno = b"\x00" * (tamano - f1_udp.CABECERA_TAMANO)
    return _cabecera(1) + relleno


# --------------------------------------------------------------------------- #
# Grupo 1: aritmetica contra la especificacion
# --------------------------------------------------------------------------- #

class TamanoDeEstructurasTests(unittest.TestCase):
    """Contrasta las cadenas de formato contra los tamanos que declara EA.

    Es el unico grupo anclado en datos externos a este codigo, y por lo tanto
    el que puede detectar un campo mal transcripto de la especificacion.
    """

    def test_cabecera_mide_29_bytes(self):
        self.assertEqual(f1_udp.CABECERA_TAMANO, 29)

    def test_car_telemetry_cierra_en_el_tamano_declarado(self):
        por_vehiculo = f1_udp.CAR_TELEMETRY_TAMANO
        self.assertEqual(por_vehiculo, 60)
        total = (f1_udp.CABECERA_TAMANO
                 + f1_udp.VEHICULOS * por_vehiculo
                 + f1_udp.CAR_TELEMETRY_COLA_TAMANO)
        self.assertEqual(total, f1_udp.PAQUETES[6]["tamano"])
        self.assertEqual(total, 1352)

    def test_lap_data_cierra_en_el_tamano_declarado(self):
        por_vehiculo = f1_udp.LAP_DATA_TAMANO
        self.assertEqual(por_vehiculo, 57)
        total = (f1_udp.CABECERA_TAMANO
                 + f1_udp.VEHICULOS * por_vehiculo
                 + f1_udp.LAP_DATA_COLA_TAMANO)
        self.assertEqual(total, f1_udp.PAQUETES[2]["tamano"])
        self.assertEqual(total, 1285)

    def test_verificar_estructuras_no_reporta_desajustes(self):
        """La funcion de autodiagnostico del modulo no debe reportar diferencias."""

        filas = f1_udp.verificar_estructuras()
        desajustadas = [f["estructura"] for f in filas if not f["coincide"]]
        self.assertEqual(desajustadas, [], f"estructuras desajustadas: {desajustadas}")

    def test_tabla_declara_los_dieciseis_paquetes(self):
        """La tabla valida el tamano de cualquier datagrama, se decodifique o no.

        Un tamano mal transcripto rechazaria paquetes validos o aceptaria
        corruptos, incluso para los paquetes que este trabajo no decodifica.
        """

        self.assertEqual(sorted(f1_udp.PAQUETES), list(range(16)))
        declarados = {i: f1_udp.PAQUETES[i]["tamano"] for i in range(16)}
        self.assertEqual(declarados, {
            0: 1349, 1: 753, 2: 1285, 3: 45, 4: 1284, 5: 1133, 6: 1352, 7: 1239,
            8: 1042, 9: 954, 10: 1041, 11: 1460, 12: 231, 13: 273, 14: 101, 15: 1131,
        })


# --------------------------------------------------------------------------- #
# Grupo 2: lo que la aritmetica no puede atrapar
# --------------------------------------------------------------------------- #

class ValoresQueElTamanoNoDetectaTests(unittest.TestCase):
    """Errores que dejan el tamano intacto y corrompen igual el resultado."""

    def test_marcha_atras_devuelve_menos_uno(self):
        """`m_gear` es int8: tipearlo sin signo devolveria 255 y mediria igual.

        Es el caso que justifica que la prueba de tamano sea necesaria pero no
        suficiente. Un byte mide un byte con signo o sin el, de modo que toda la
        aritmetica del grupo anterior seguiria cerrando.
        """

        r = f1_udp.decodificar(datagrama_telemetria(indice_propio=3, marcha_propia=-1))
        self.assertEqual(r["vehiculo_propio"]["gear"], -1)
        self.assertNotEqual(r["vehiculo_propio"]["gear"], 255)

    def test_los_valores_no_se_corren_entre_vehiculos(self):
        """Detecta un desplazamiento por vehiculo mal calculado.

        Con el tamano por vehiculo correcto pero el desplazamiento equivocado,
        los totales cerrarian y los datos apareceran mezclados entre autos.
        """

        r = f1_udp.decodificar(datagrama_telemetria())
        velocidades = [v["speed_kmh"] for v in r["vehiculos"]]
        self.assertEqual(velocidades, [300 + i for i in range(f1_udp.VEHICULOS)])

    def test_vehiculo_propio_es_el_del_indice_declarado(self):
        r = f1_udp.decodificar(datagrama_telemetria(indice_propio=7, marcha_propia=-1))
        self.assertEqual(r["vehiculo_propio"]["speed_kmh"], 307)
        self.assertEqual(r["vehiculo_propio"], r["vehiculos"][7])

    def test_lap_data_nombra_sus_campos(self):
        """Comprueba el nombrado y que la posicion siga al indice del vehiculo."""

        r = f1_udp.decodificar(datagrama_vueltas())
        self.assertTrue(r["decodificado"])
        primero = r["vehiculos"][0]
        self.assertEqual(primero["car_position"], 1)
        self.assertEqual(primero["current_lap_num"], 12)
        self.assertAlmostEqual(primero["lap_distance_m"], 1234.5, places=1)
        self.assertEqual([v["car_position"] for v in r["vehiculos"]],
                         list(range(1, f1_udp.VEHICULOS + 1)))


# --------------------------------------------------------------------------- #
# Grupo 3: rechazos
# --------------------------------------------------------------------------- #

class RechazosTests(unittest.TestCase):
    """El decodificador debe fallar de forma visible, no entregar basura."""

    def test_rechaza_formato_distinto_del_congelado(self):
        """Es la proteccion ante una actualizacion automatica del juego."""

        malo = _cabecera(6, packet_format=2024) + datagrama_telemetria()[29:]
        with self.assertRaises(f1_udp.FormatoNoAdmitido):
            f1_udp.decodificar(malo)

    def test_rechaza_datagrama_mas_corto_que_la_cabecera(self):
        with self.assertRaises(f1_udp.TamanoInvalido):
            f1_udp.decodificar(b"\x00" * 10)

    def test_rechaza_tamano_que_no_corresponde_al_tipo(self):
        """Cabecera bien formada declarando telemetria, con longitud equivocada."""

        truncado = datagrama_telemetria()[:900]
        with self.assertRaises(f1_udp.TamanoInvalido):
            f1_udp.decodificar(truncado)

    def test_rechaza_identificador_de_paquete_desconocido(self):
        """`m_packetId` es un byte: puede llegar cualquier valor de 0 a 255."""

        malo = _cabecera(200) + b"\x00" * 100
        with self.assertRaises(f1_udp.PaqueteNoDecodificable):
            f1_udp.decodificar(malo)


# --------------------------------------------------------------------------- #
# Grupo 4: contabilidad de lo no decodificado
# --------------------------------------------------------------------------- #

class PaquetesNoDecodificadosTests(unittest.TestCase):
    """Un paquete sin decodificador queda registrado, no descartado."""

    def test_paquete_sin_decodificador_queda_contabilizado(self):
        r = f1_udp.decodificar(datagrama_sin_decodificador())
        self.assertEqual(r["paquete"], "session")
        self.assertFalse(r["decodificado"])
        self.assertIn("motivo", r)
        self.assertNotIn("vehiculos", r)
        # La cabecera si se decodifica: permite contabilizarlo por sesion y marco.
        self.assertEqual(r["cabecera"]["packet_id"], 1)
        self.assertEqual(r["cabecera"]["session_uid"], 0xDEADBEEF)


# --------------------------------------------------------------------------- #
# Grupo 5: trazabilidad
# --------------------------------------------------------------------------- #

class TrazabilidadTests(unittest.TestCase):
    """Permite saber con que version se decodifico un dato ya guardado."""

    def test_resultado_declara_la_version_del_decodificador(self):
        r = f1_udp.decodificar(datagrama_telemetria())
        self.assertEqual(r["version_decodificador"], f1_udp.VERSION_DECODIFICADOR)
        self.assertEqual(f1_udp.FORMATO_ADMITIDO, 2025)


if __name__ == "__main__":
    unittest.main()
