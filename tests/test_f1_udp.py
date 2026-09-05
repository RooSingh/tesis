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

import re
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

    El tipo se elige **preguntandole al decodificador**, no consultando sus
    registros. Consultar los registros ya fallo dos veces: al implementar Session
    la funcion lo seguia proponiendo como ejemplo de lo no decodificado, y al
    implementar el evento —que se resuelve por una via especial y no figura en
    ningun registro— volvio a proponer uno que si se decodifica.

    Preguntar por el resultado y no por la implementacion es lo unico que no
    puede envejecer.
    """

    for packet_id in sorted(f1_udp.PAQUETES):
        tamano = f1_udp.PAQUETES[packet_id]["tamano"]
        candidato = _cabecera(packet_id) + bytes(tamano - f1_udp.CABECERA_TAMANO)
        if not f1_udp.decodificar(candidato).get("decodificado"):
            return candidato
    raise unittest.SkipTest(
        "ya no queda ningun paquete sin decodificador: la prueba perdio su objeto")


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


class EventoTests(unittest.TestCase):
    """El unico paquete cuya forma depende del contenido, no del identificador.

    Es la clase de estructura donde una prueba de tamano no protege nada: los
    cuarenta y cinco bytes cierran igual se lea el detalle como corresponde o
    con la estructura de otro evento. La proteccion tiene que venir de leer un
    codigo y comprobar que salieron los campos de **ese** codigo.
    """

    @staticmethod
    def _evento(codigo: str, detalle: bytes = b"") -> bytes:
        cuerpo = codigo.encode("ascii") + detalle
        # El detalle ocupa siempre doce bytes; el resto va en cero.
        relleno = f1_udp.EVENTO_TAMANO_DETALLE - len(detalle)
        return _cabecera(3) + cuerpo + b"\x00" * relleno

    def test_el_paquete_mide_lo_que_declara_la_especificacion(self):
        self.assertEqual(len(self._evento("SSTA")), 45)
        self.assertEqual(f1_udp.PAQUETES[3]["tamano"], 45)

    def test_un_codigo_sin_detalle_no_inventa_campos(self):
        """Que no lleve detalle es un hecho, no un dato faltante."""

        r = f1_udp.decodificar(self._evento("CHQF"))
        self.assertEqual(r["codigo"], "CHQF")
        self.assertEqual(r["evento"], "bandera-a-cuadros")
        self.assertEqual(r["detalle"], {})

    def test_el_coche_de_seguridad_declara_tipo_y_fase(self):
        r = f1_udp.decodificar(self._evento("SCAR", struct.pack("<BB", 1, 0)))
        self.assertEqual(r["detalle"]["tipo_nombre"], "coche-de-seguridad")
        self.assertEqual(r["detalle"]["fase_nombre"], "desplegado")

    def test_distingue_el_coche_de_seguridad_de_la_vuelta_de_formacion(self):
        """Confundirlos contaria como neutralizacion el arranque de la carrera."""

        formacion = f1_udp.decodificar(self._evento("SCAR", struct.pack("<BB", 3, 0)))
        self.assertEqual(formacion["detalle"]["tipo_nombre"], "vuelta-de-formacion")

    def test_cada_codigo_lee_su_propia_estructura(self):
        """La prueba que el tamano no puede dar.

        Se arma un adelantamiento y se comprueba que no salgan los campos del
        radar de velocidad, que ocupa los mismos doce bytes.
        """

        r = f1_udp.decodificar(self._evento("OVTK", struct.pack("<BB", 4, 9)))
        self.assertEqual(r["detalle"], {"vehiculo_que_adelanta": 4,
                                        "vehiculo_adelantado": 9})
        self.assertNotIn("velocidad_kmh", r["detalle"])

    def test_el_radar_de_velocidad_lee_sus_seis_campos(self):
        detalle = struct.pack("<BfBBBf", 7, 312.5, 1, 1, 7, 312.5)
        r = f1_udp.decodificar(self._evento("SPTP", detalle))
        self.assertEqual(r["detalle"]["vehiculo"], 7)
        self.assertAlmostEqual(r["detalle"]["velocidad_kmh"], 312.5, places=3)

    def test_un_codigo_desconocido_no_se_descarta_en_silencio(self):
        """Un evento nuevo de una version futura debe quedar contabilizado."""

        r = f1_udp.decodificar(self._evento("ZZZZ"))
        self.assertTrue(r["decodificado"])
        self.assertIn("desconocido", r["evento"])


class OrdenDeRuedasUniformeTests(unittest.TestCase):
    """El mismo concepto fisico se nombra igual en todos los paquetes.

    Mientras la temperatura de neumatico viajaba como lista y el desgaste como
    diccionario, el orden quedaba implicito justo en los canales donde este
    trabajo ya se equivoco una vez.
    """

    def test_la_telemetria_nombra_sus_ruedas(self):
        v = f1_udp.decodificar(_datagrama_relleno(6))["vehiculo_propio"]
        for campo in ("brakes_temperature_c", "tyres_surface_temperature_c",
                      "tyres_inner_temperature_c", "tyres_pressure_psi",
                      "surface_type"):
            with self.subTest(campo=campo):
                self.assertEqual(tuple(v[campo]), f1_udp.ORDEN_RUEDAS)

    def test_el_dano_usa_el_mismo_orden_que_la_telemetria(self):
        telemetria = f1_udp.decodificar(_datagrama_relleno(6))["vehiculo_propio"]
        dano = f1_udp.decodificar(_datagrama_relleno(10))["vehiculo_propio"]
        self.assertEqual(tuple(telemetria["tyres_pressure_psi"]),
                         tuple(dano["tyres_wear_pct"]))


class IndicesDeLaColaDeSesionTests(unittest.TestCase):
    """Fija cada campo de la cola de sesion a su posicion.

    Es la prueba que faltaba cuando el nivel de dano se leia una posicion
    corrida y publicaba la **tasa** de dano en su lugar. El tamano del paquete
    cerraba, el valor era un entero creible, y ninguna prueba existente lo
    tocaba: el defecto solo se vio contrastando contra lo que la autora habia
    configurado en el juego.

    El metodo evita la circularidad de las demas pruebas de estructura: en vez
    de comparar contra la misma cadena de formato que usa el decodificador, se
    arma la cola con **un valor distinto por posicion** y se comprueba que cada
    campo nombrado devuelva su propio marcador. Un desplazamiento de una sola
    posicion cambia el valor y la prueba cae.
    """

    # Posicion de cada campo en la cola, contada del apendice de la
    # especificacion. Cambiar el decodificador sin cambiar la especificacion
    # rompe esta tabla, que es lo que se busca.
    POSICIONES = {
        "forecast_accuracy": 0, "ai_difficulty": 1,
        "season_link_id": 2, "weekend_link_id": 3, "session_link_id": 4,
        "steering_assist": 8, "braking_assist": 9, "gearbox_assist": 10,
        "pit_assist": 11, "pit_release_assist": 12, "ers_assist": 13,
        "drs_assist": 14, "dynamic_racing_line": 15, "dynamic_racing_line_type": 16,
        "game_mode": 17, "rule_set": 18, "time_of_day_min": 19,
        "session_length": 20, "speed_units_lead": 21,
        "num_safety_car_periods": 25, "num_virtual_safety_car_periods": 26,
        "num_red_flag_periods": 27, "equal_car_performance": 28,
        "recovery_mode": 29, "surface_type": 31, "low_fuel_mode": 32,
        "tyre_temperature_model": 34, "pit_lane_tyre_sim": 35,
        "car_damage_setting": 36, "car_damage_rate": 37, "collisions": 38,
        "corner_cutting_stringency": 42, "parc_ferme_rules": 43,
        "pit_stop_experience": 44, "safety_car_setting": 45,
        "formation_lap": 47, "red_flags_setting": 49,
        "num_sessions_in_weekend": 52,
    }

    def _sesion_con_marcadores(self) -> dict:
        """Arma un paquete de sesion donde cada posicion de la cola vale distinto."""

        # Cuantos valores hay antes de la cola.
        antes = (len(f1_udp.SESSION_CABEZA_FMT) + f1_udp.ZONAS_COMISARIO * 2
                 + 3 + f1_udp.MUESTRAS_PRONOSTICO * 8)
        # El formato admite repeticiones como "12B": se expanden para que cada
        # valor tenga su propia posicion.
        letras = []
        for repeticion, letra in re.findall(r"(\d*)([a-zA-Z])", f1_udp.SESSION_FMT[1:]):
            letras.extend([letra] * int(repeticion or 1))
        # Se recorre el formato completo asignando a cada valor su indice, de
        # modo que el valor que devuelva un campo delate su posicion real.
        valores = []
        indice_cola = 0
        for i, letra in enumerate(letras):
            if i < antes:
                valores.append(0.0 if letra == "f" else 0)
            else:
                # Los enteros de un byte no pueden pasar de 255: se usa el
                # indice acotado, que igual distingue posiciones vecinas.
                marcador = indice_cola % 251 + 1
                valores.append(float(marcador) if letra == "f" else marcador)
                indice_cola += 1

        datos = _cabecera(1) + struct.pack(f1_udp.SESSION_FMT, *valores)
        self.assertEqual(len(datos), f1_udp.PAQUETES[1]["tamano"])
        return f1_udp.decodificar(datos)["sesion"]

    def test_cada_campo_de_la_cola_lee_su_propia_posicion(self):
        sesion = self._sesion_con_marcadores()
        for campo, posicion in self.POSICIONES.items():
            with self.subTest(campo=campo):
                self.assertEqual(
                    sesion[campo], posicion % 251 + 1,
                    f"{campo} deberia leer la posicion {posicion} de la cola",
                )

    def test_el_nivel_de_dano_y_su_tasa_son_campos_distintos(self):
        """El defecto concreto: publicar la tasa como si fuera el nivel."""

        sesion = self._sesion_con_marcadores()
        self.assertNotEqual(sesion["car_damage_setting"], sesion["car_damage_rate"])
        self.assertEqual(sesion["car_damage_rate"],
                         sesion["car_damage_setting"] + 1)


class MovimientoTests(unittest.TestCase):
    """El paquete que aporta la aceleracion y la posicion en el mundo.

    Se prueba con la tecnica que este trabajo adopto despues del defecto del
    indice corrido: **un valor distinto por posicion**, de modo que un
    desplazamiento cambie el valor y la prueba caiga. Comparar contra la misma
    cadena de formato que usa el decodificador no detectaria nada.
    """

    def _con_marcadores(self) -> dict:
        """Un paquete donde cada campo del vehiculo cero vale su propia posicion."""

        valores = []
        for indice in range(f1_udp.VEHICULOS):
            for posicion in range(18):
                # Los seis campos de direccion son enteros; el resto, flotantes.
                bruto = posicion if indice == 0 else 0
                valores.append(bruto)
        # Se arma vehiculo por vehiculo para respetar los tipos de cada campo.
        cuerpo = b""
        for indice in range(f1_udp.VEHICULOS):
            campos = [float(p) if indice == 0 else 0.0 for p in range(6)]
            campos += [p if indice == 0 else 0 for p in range(6, 12)]
            campos += [float(p) if indice == 0 else 0.0 for p in range(12, 18)]
            cuerpo += struct.pack(f1_udp.MOTION_FMT, *campos)
        datos = _cabecera(0) + cuerpo
        self.assertEqual(len(datos), f1_udp.PAQUETES[0]["tamano"])
        return f1_udp.decodificar(datos)["vehiculos"][0]

    def test_el_tamano_cierra_contra_la_especificacion(self):
        self.assertEqual(f1_udp.MOTION_TAMANO, 60)
        self.assertEqual(
            f1_udp.CABECERA_TAMANO + f1_udp.MOTION_TAMANO * f1_udp.VEHICULOS,
            f1_udp.PAQUETES[0]["tamano"],
        )

    def test_cada_campo_lee_su_propia_posicion(self):
        v = self._con_marcadores()
        posiciones = {
            "world_position_x_m": 0, "world_position_y_m": 1, "world_position_z_m": 2,
            "world_velocity_x_ms": 3, "world_velocity_y_ms": 4, "world_velocity_z_ms": 5,
            "g_force_lateral": 12, "g_force_longitudinal": 13, "g_force_vertical": 14,
            "yaw_rad": 15, "pitch_rad": 16, "roll_rad": 17,
        }
        for campo, posicion in posiciones.items():
            with self.subTest(campo=campo):
                self.assertEqual(v[campo], float(posicion))

    def test_los_vectores_de_direccion_se_normalizan(self):
        """Sin dividir por 32767 los vectores medirian decenas de miles.

        Es un error que ninguna prueba de tamano puede detectar: los enteros
        entran y salen igual, y solo la escala esta mal.
        """

        v = self._con_marcadores()
        for campo, posicion in (("forward_dir_x", 6), ("right_dir_x", 9)):
            with self.subTest(campo=campo):
                self.assertAlmostEqual(
                    v[campo], posicion / f1_udp.NORMALIZACION_DIRECCION, places=9)
                self.assertLess(abs(v[campo]), 1.0)

    def test_la_aceleracion_y_la_altura_no_comparten_eje(self):
        """El eje vertical es y, verificado por medicion sobre el eje de guinada.

        Si la altura se leyera como z, la aceleracion lateral y la vertical
        quedarian intercambiadas sin que el tamano del paquete cambiara.
        """

        v = self._con_marcadores()
        self.assertNotEqual(v["world_position_y_m"], v["world_position_z_m"])
        self.assertEqual(v["world_position_y_m"], 1.0)


class ParticipantesTests(unittest.TestCase):
    """El paquete que responde quien es cada vehiculo.

    Su modo de falla propio es nuevo en este decodificador: **lleva un campo
    antes del arreglo**. Si ese byte no entra en el calculo del origen, las
    veintidos entradas se leen corridas un byte y el paquete sigue midiendo
    exactamente lo que la especificacion declara.
    """

    @staticmethod
    def _paquete(nombres, activos=20) -> bytes:
        cuerpo = struct.pack(f1_udp.PARTICIPANTS_CABEZA_FMT, activos)
        for indice in range(f1_udp.VEHICULOS):
            nombre = nombres[indice] if indice < len(nombres) else ""
            cuerpo += struct.pack(
                f1_udp.PARTICIPANTE_FMT,
                bytes([1, 10, 0, indice % 10, 0, 44, 3]),   # los siete de un byte
                nombre.encode("utf-8")[:32].ljust(32, b"\x00"),
                bytes([1, 0]),                              # privacidad y nombres
                7,                                          # nivel tecnico
                3,                                          # plataforma
                4,                                          # cantidad de colores
                bytes(12),                                  # colores
            )
        return _cabecera(4) + cuerpo

    def test_el_tamano_cierra_contra_la_especificacion(self):
        self.assertEqual(f1_udp.PARTICIPANTE_TAMANO, 57)
        self.assertEqual(len(self._paquete([])), f1_udp.PAQUETES[4]["tamano"])

    def test_el_campo_previo_al_arreglo_se_lee_y_no_desplaza_las_entradas(self):
        """La prueba del defecto que la cabeza puede introducir.

        Se pone un nombre distinto en cada entrada: si el origen del arreglo
        estuviera corrido, ningun nombre coincidiria con su indice.
        """

        nombres = [f"PILOTO{i:02d}" for i in range(f1_udp.VEHICULOS)]
        r = f1_udp.decodificar(self._paquete(nombres, activos=17))
        self.assertEqual(r["num_active_cars"], 17)
        for i, v in enumerate(r["vehiculos"]):
            with self.subTest(indice=i):
                self.assertEqual(v["name"], f"PILOTO{i:02d}")

    def test_el_nombre_se_recorta_en_el_nulo(self):
        """Sin recortar, el nombre arrastraria los bytes de relleno."""

        r = f1_udp.decodificar(self._paquete(["NORRIS"]))
        self.assertEqual(r["vehiculos"][0]["name"], "NORRIS")
        self.assertNotIn("\x00", r["vehiculos"][0]["name"])

    def test_el_nombre_admite_caracteres_no_ascii(self):
        """Aparecio en la carrera capturada: HULKENBERG lleva U con dieresis.

        El protocolo declara UTF-8 y la captura lo confirma: los bytes del
        nombre son c3 9c, que es U+00DC. Leerlo como Latin-1 daria dos
        caracteres en lugar de uno.
        """

        r = f1_udp.decodificar(self._paquete(["HÜLKENBERG"]))
        nombre = r["vehiculos"][0]["name"]
        self.assertEqual(nombre, "HÜLKENBERG")
        self.assertEqual(len(nombre), 10)
        self.assertEqual(ord(nombre[1]), 0x00DC)

    def test_el_ajuste_de_privacidad_se_expone_sin_interpretar(self):
        """Se informa aunque no haga falta para decidir sobre el nombre.

        En los modos que este trabajo usa el nombre es el del piloto elegido y
        no el de la persona —verificado sobre la carrera capturada, donde la
        conductora humana aparece como VERSTAPPEN—, de modo que este campo no
        gobierna ninguna decision hoy. Se expone igual: esconderlo en la lectura
        lo volveria invisible si el alcance cambiara.
        """

        r = f1_udp.decodificar(self._paquete(["ALGUIEN"]))
        self.assertIn("your_telemetry", r["vehiculos"][0])
        self.assertEqual(r["vehiculos"][0]["your_telemetry"], 1)

    def test_el_equipo_se_traduce_y_el_id_se_conserva(self):
        r = f1_udp.decodificar(self._paquete(["X"]))
        v = r["vehiculos"][0]
        self.assertEqual(v["team_id"], 0)
        self.assertEqual(v["team"], "Mercedes")
