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
    """Un paquete valido de un tipo que este trabajo no decodifica.

    El tipo se elige dinamicamente entre los que no tienen decodificador, para
    que la prueba no envejezca cada vez que se implementa uno nuevo: al agregar
    Session, esta funcion lo seguia usando como ejemplo de lo no decodificado.
    """

    implementados = set(f1_udp._DECODIFICADORES) | set(f1_udp._DECODIFICADORES_UNICOS)
    packet_id = next(i for i in sorted(f1_udp.PAQUETES) if i not in implementados)
    tamano = f1_udp.PAQUETES[packet_id]["tamano"]
    relleno = bytes(tamano - f1_udp.CABECERA_TAMANO)
    return _cabecera(packet_id) + relleno


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
        self.assertFalse(r["decodificado"])
        self.assertIn("motivo", r)
        self.assertNotIn("vehiculos", r)
        self.assertNotIn("sesion", r)
        # Se reconoce por su nombre aunque no se interprete su contenido.
        self.assertEqual(r["paquete"], f1_udp.PAQUETES[r["packet_id"]]["nombre"])
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


# --------------------------------------------------------------------------- #
# Grupo 6: paquetes de contexto y estado
# --------------------------------------------------------------------------- #

def _datagrama_relleno(packet_id: int) -> bytes:
    """Paquete valido en tamano, con carga util en cero.

    Sirve para ejercitar el despacho y la aritmetica sin fijar ningun valor
    concreto: las pruebas verifican el mecanismo, no un circuito ni una sesion.
    """

    tamano = f1_udp.PAQUETES[packet_id]["tamano"]
    return _cabecera(packet_id) + b"\x00" * (tamano - f1_udp.CABECERA_TAMANO)


class SessionYEstadoTests(unittest.TestCase):
    """Session describe la sesion; Car Status describe cada vehiculo."""

    def test_session_cierra_en_el_tamano_declarado(self):
        total = f1_udp.CABECERA_TAMANO + f1_udp.SESSION_TAMANO
        self.assertEqual(total, f1_udp.PAQUETES[1]["tamano"])
        self.assertEqual(total, 753)

    def test_car_status_cierra_en_el_tamano_declarado(self):
        self.assertEqual(f1_udp.CAR_STATUS_TAMANO, 55)
        total = f1_udp.CABECERA_TAMANO + f1_udp.VEHICULOS * f1_udp.CAR_STATUS_TAMANO
        self.assertEqual(total, f1_udp.PAQUETES[7]["tamano"])
        self.assertEqual(total, 1239)

    def test_session_se_decodifica_como_bloque_unico(self):
        """No lleva arreglo por vehiculo: describe la sesion, no a los autos."""

        r = f1_udp.decodificar(_datagrama_relleno(1))
        self.assertTrue(r["decodificado"])
        self.assertIn("sesion", r)
        self.assertNotIn("vehiculos", r)
        self.assertNotIn("vehiculo_propio", r)

    def test_session_nombra_los_campos_de_contexto(self):
        """Verifica que los campos existan, sin fijar ningun valor concreto."""

        s = f1_udp.decodificar(_datagrama_relleno(1))["sesion"]
        for campo in ("track_id", "track_length_m", "session_type", "game_mode",
                      "weather", "track_temperature_c", "air_temperature_c",
                      "sector2_lap_distance_start_m", "sector3_lap_distance_start_m"):
            self.assertIn(campo, s)

    def test_session_declara_las_diez_ayudas(self):
        """Permite verificar contra el archivo si una sesion corrio sin ayudas."""

        s = f1_udp.decodificar(_datagrama_relleno(1))["sesion"]
        ayudas = ("steering_assist", "braking_assist", "gearbox_assist",
                  "pit_assist", "pit_release_assist", "ers_assist", "drs_assist",
                  "dynamic_racing_line", "dynamic_racing_line_type")
        for ayuda in ayudas:
            self.assertIn(ayuda, s)

    def test_car_status_decodifica_los_veintidos_vehiculos(self):
        """Se decodifican todos; normalizar solo el propio es decision del adaptador."""

        r = f1_udp.decodificar(_datagrama_relleno(7))
        self.assertTrue(r["decodificado"])
        self.assertEqual(len(r["vehiculos"]), f1_udp.VEHICULOS)
        self.assertIn("fuel_in_tank_kg", r["vehiculo_propio"])
        self.assertIn("actual_tyre_compound", r["vehiculo_propio"])
        self.assertIn("ers_store_energy_j", r["vehiculo_propio"])

    def test_la_verificacion_incluye_siempre_la_cabecera(self):
        """La cabecera se verifica aparte porque no pertenece a ningun paquete."""

        nombres = {f["estructura"] for f in f1_udp.verificar_estructuras()}
        self.assertIn("cabecera", nombres)

    def test_ningun_paquete_decodificable_queda_sin_verificar(self):
        """Toda estructura implementada debe tener su comprobacion de tamano."""

        implementados = set(f1_udp._DECODIFICADORES) | set(f1_udp._DECODIFICADORES_UNICOS)
        verificados = {f1_udp.PAQUETES[i]["nombre"] for i in implementados}
        nombres = {f["estructura"] for f in f1_udp.verificar_estructuras()}
        self.assertTrue(verificados <= nombres)


class DanoYDinamicaTests(unittest.TestCase):
    """Car Damage describe el estado mecanico; Motion Ex la dinamica del vehiculo."""

    def test_car_damage_cierra_en_el_tamano_declarado(self):
        self.assertEqual(f1_udp.CAR_DAMAGE_TAMANO, 46)
        total = f1_udp.CABECERA_TAMANO + f1_udp.VEHICULOS * f1_udp.CAR_DAMAGE_TAMANO
        self.assertEqual(total, f1_udp.PAQUETES[10]["tamano"])
        self.assertEqual(total, 1041)

    def test_motion_ex_cierra_en_el_tamano_declarado(self):
        """Sesenta y un flotantes consecutivos, solo del vehiculo propio."""

        self.assertEqual(f1_udp.MOTION_EX_TAMANO, 244)
        total = f1_udp.CABECERA_TAMANO + f1_udp.MOTION_EX_TAMANO
        self.assertEqual(total, f1_udp.PAQUETES[13]["tamano"])
        self.assertEqual(total, 273)

    def test_el_orden_de_ruedas_es_el_que_declara_la_especificacion(self):
        """Leerlas al reves intercambia el eje sin alterar el tamano.

        Es el mismo tipo de error que el campo de marcha con signo: la
        verificacion aritmetica no puede detectarlo.
        """

        self.assertEqual(f1_udp.ORDEN_RUEDAS,
                         ("trasera_izquierda", "trasera_derecha",
                          "delantera_izquierda", "delantera_derecha"))

    def test_car_damage_nombra_las_ruedas_en_lugar_de_indices(self):
        v = f1_udp.decodificar(_datagrama_relleno(10))["vehiculo_propio"]
        for campo in ("tyres_wear_pct", "brakes_damage_pct", "tyre_blisters_pct"):
            self.assertEqual(set(v[campo]), set(f1_udp.ORDEN_RUEDAS))

    def test_car_damage_cubre_el_desgaste_del_motor_por_componente(self):
        v = f1_udp.decodificar(_datagrama_relleno(10))["vehiculo_propio"]
        for campo in ("engine_ice_wear_pct", "engine_mguk_wear_pct",
                      "engine_mguh_wear_pct", "engine_es_wear_pct",
                      "engine_ce_wear_pct", "engine_tc_wear_pct"):
            self.assertIn(campo, v)

    def test_motion_ex_se_decodifica_como_bloque_unico(self):
        """La especificacion lo declara como datos del vehiculo propio unicamente."""

        r = f1_udp.decodificar(_datagrama_relleno(13))
        self.assertTrue(r["decodificado"])
        self.assertIn("sesion", r)
        self.assertNotIn("vehiculos", r)

    def test_motion_ex_expone_las_senales_equivalentes_al_bus_can(self):
        """Es el puente con el conjunto minimo derivado del analisis CAN real."""

        v = f1_udp.decodificar(_datagrama_relleno(13))["sesion"]
        self.assertEqual(set(v["wheel_speed"]), set(f1_udp.ORDEN_RUEDAS))
        self.assertIn("z", v["angular_velocity_rads"])   # equivalente de yaw_rate
        self.assertIn("front_wheels_angle_rad", v)       # equivalente de steer_angle
        self.assertEqual(set(v["wheel_slip_ratio"]), set(f1_udp.ORDEN_RUEDAS))

    def test_la_verificacion_no_cubre_paquetes_no_implementados(self):
        """Complementa la invariante inversa: no debe verificar lo que no decodifica.

        Junto con `test_ningun_paquete_decodificable_queda_sin_verificar`, fija la
        correspondencia exacta sin enumerar nombres, de modo que agregar un
        decodificador nuevo no invalide la prueba.
        """

        implementados = set(f1_udp._DECODIFICADORES) | set(f1_udp._DECODIFICADORES_UNICOS)
        esperados = {f1_udp.PAQUETES[i]["nombre"] for i in implementados} | {"cabecera"}
        nombres = {f["estructura"] for f in f1_udp.verificar_estructuras()}
        self.assertEqual(nombres, esperados)


class EjesDelVehiculoTests(unittest.TestCase):
    """La guinada es la rotacion alrededor del eje vertical.

    Una version anterior la atribuia al eje longitudinal. El error se detecto
    integrando cada eje sobre una captura real y no por lectura del codigo: es
    un error de interpretacion semantica, no de desplazamiento de bytes, de modo
    que ninguna verificacion aritmetica podia detectarlo.
    """

    def test_expone_la_guinada_como_campo_propio(self):
        v = f1_udp.decodificar(_datagrama_relleno(13))["sesion"]
        self.assertIn("yaw_rate_rads", v)

    def test_la_guinada_corresponde_al_eje_vertical(self):
        """Debe ser el mismo valor que el componente vertical, no otro eje."""

        v = f1_udp.decodificar(_datagrama_relleno(13))["sesion"]
        self.assertEqual(v["yaw_rate_rads"], v["angular_velocity_rads"]["y"])


class ReglajeTests(unittest.TestCase):
    """El reglaje del vehiculo forma parte del registro, no de una anotacion."""

    def test_car_setups_cierra_en_el_tamano_declarado(self):
        self.assertEqual(f1_udp.CAR_SETUP_TAMANO, 50)
        total = (f1_udp.CABECERA_TAMANO
                 + f1_udp.VEHICULOS * f1_udp.CAR_SETUP_TAMANO
                 + f1_udp.CAR_SETUP_COLA_TAMANO)
        self.assertEqual(total, f1_udp.PAQUETES[5]["tamano"])
        self.assertEqual(total, 1133)

    def test_declara_la_aerodinamica_y_el_diferencial(self):
        v = f1_udp.decodificar(_datagrama_relleno(5))["vehiculo_propio"]
        for campo in ("front_wing", "rear_wing",
                      "differential_on_throttle_pct", "differential_off_throttle_pct"):
            self.assertIn(campo, v)

    def test_declara_la_geometria_de_suspension(self):
        v = f1_udp.decodificar(_datagrama_relleno(5))["vehiculo_propio"]
        for campo in ("front_camber_deg", "rear_camber_deg", "front_toe_deg",
                      "rear_toe_deg", "front_anti_roll_bar", "front_ride_height"):
            self.assertIn(campo, v)

    def test_las_presiones_van_nombradas_por_rueda(self):
        v = f1_udp.decodificar(_datagrama_relleno(5))["vehiculo_propio"]
        self.assertEqual(set(v["tyre_pressure_psi"]), set(f1_udp.ORDEN_RUEDAS))
