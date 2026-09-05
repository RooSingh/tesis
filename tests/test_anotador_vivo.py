# -*- coding: utf-8 -*-
"""Pruebas del anotador en vivo.

Se verifican tres cosas distintas, y conviene no confundirlas:

1. **que cada regla se dispare cuando debe y no cuando no debe**, con mensajes
   escritos a mano donde el valor que hace disparar la regla esta puesto por
   quien escribe la prueba. Es lo que evita que la prueba herede el error del
   codigo que verifica;

2. **que el anotador y la lectura posterior digan lo mismo**. Son dos caminos
   distintos hacia la misma conclusion, y si divergen, una de las dos lecturas de
   la tesis esta mal. Esta comparacion atrapo dos defectos reales: una tabla de
   superficies escrita de memoria, que llamaba "piedra" a lo que la
   especificacion llama "cesped", y un impacto instantaneo declarado como si
   durara medio segundo;

3. **que los umbrales de los dos modulos sigan siendo los mismos numeros**. Estan
   escritos dos veces y nada obliga a que coincidan, salvo esto.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from backend import anotador_vivo, f1_udp  # noqa: E402

CAPTURAS = RAIZ / "datasets" / "f1_25" / "capturas"


# --------------------------------------------------------------------------- #
# Utilidades de construccion de mensajes
# --------------------------------------------------------------------------- #

def mensaje(senal: str, valor: float, t: float) -> dict:
    return {"signal_name": senal, "value": valor, "timestamp": t}


def marco(t: float, **canales: float) -> list[dict]:
    """Un instante completo, con todos sus canales a la misma marca temporal."""

    return [mensaje(nombre, valor, t) for nombre, valor in canales.items()]


def asfalto(t: float) -> list[dict]:
    return marco(t, **{f"surface_type_{r}": 0 for r in anotador_vivo.RUEDAS})


def conduccion_normal(desde: float, marcos: int, paso: float = 0.05) -> list[dict]:
    """Una conduccion sin nada que anotar: en asfalto, sin deslizar, sin golpes.

    Es la referencia contra la que se calibraron los umbrales, y sirve de control
    negativo: **si una regla se dispara aca, la regla esta mal**.
    """

    salida: list[dict] = []
    for i in range(marcos):
        t = desde + i * paso
        salida += asfalto(t)
        salida += marco(t, speed=200.0, throttle=0.9, brake=0.0,
                        g_force_vertical=0.06, lap_number=1,
                        lap_distance=100.0 + i * 5,
                        wheel_slip_ratio_rear_left=0.02,
                        wheel_slip_ratio_rear_right=0.02)
    return salida


def incidentes_de(mensajes: list[dict], solo_cerradas: bool = False) -> list[dict]:
    salidas = anotador_vivo.anotar_secuencia(mensajes)
    return [a for a in salidas
            if a["nivel"] == "incidente" and (not solo_cerradas or a["cerrada"])]


def desde_captura(captura: Path):
    """Convierte una captura real en la misma clase de mensajes que van en vivo."""

    ruta = RAIZ / "scripts" / "verificar_anotador_vivo.py"
    especificacion = importlib.util.spec_from_file_location("_verificador", ruta)
    modulo = importlib.util.module_from_spec(especificacion)
    especificacion.loader.exec_module(modulo)
    return modulo.mensajes(captura)


def anotar_captura(captura: Path) -> list[dict]:
    anotador = anotador_vivo.Anotador()
    for m in desde_captura(captura):
        anotador.observar(m)
    anotador.cerrar_pendiente()
    return list(anotador.anotaciones)


# --------------------------------------------------------------------------- #
# 1. Cada regla, por separado
# --------------------------------------------------------------------------- #

class ReglasDeIncidente(unittest.TestCase):

    def test_la_conduccion_normal_no_produce_ninguna_anotacion(self):
        """El control negativo: el criterio con que se calibraron los umbrales."""

        self.assertEqual(incidentes_de(conduccion_normal(0.0, 60)), [])

    def test_las_cuatro_ruedas_sobre_el_piano_son_una_salida_de_pista(self):
        """El piano no es pista, y con las cuatro ruedas ahi el vehiculo salio.

            "Drivers will be judged to have left the track if no part of the car
            remains in contact with it and, for the avoidance of doubt, any white
            lines defining the track edges are considered to be part of the track
            but the kerbs are not."

            -- FIA, 2025 Formula 1 Sporting Regulations, Issue 5, art. 33.3

        Una version anterior de esta prueba afirmaba lo contrario: que pisar el
        piano nunca era salirse. El criterio era propio y estaba calibrado contra
        vueltas limpias, que es un metodo razonable para un umbral fisico y no lo
        es para una condicion que el reglamento define.
        """

        mensajes = conduccion_normal(0.0, 10)
        for i in range(6):
            t = 1.0 + i * 0.05
            mensajes += marco(t, **{f"surface_type_{r}": 1
                                    for r in anotador_vivo.RUEDAS})
            mensajes += marco(t, speed=200.0, throttle=0.9, brake=0.0)
        mensajes += conduccion_normal(3.0, 30)

        incidentes = incidentes_de(mensajes, solo_cerradas=True)
        self.assertEqual(len(incidentes), 1)
        self.assertEqual(incidentes[0]["titulo"], "fuera de pista")
        self.assertIn("piano", incidentes[0]["detalle"])

    def test_una_rueda_sobre_el_asfalto_alcanza_para_seguir_en_pista(self):
        """Basta que **una parte** siga en contacto: tres ruedas fuera no bastan.

        Es la otra mitad de la correccion, y va en sentido contrario a la
        anterior: el criterio propio anotaba con tres ruedas fuera, y el articulo
        33.3 exige que ninguna parte del vehiculo siga en contacto con la pista.
        """

        mensajes = conduccion_normal(0.0, 10)
        for i in range(6):
            t = 1.0 + i * 0.05
            mensajes += marco(t, surface_type_rear_left=7,
                              surface_type_rear_right=7,
                              surface_type_front_left=7,
                              surface_type_front_right=0)
            mensajes += marco(t, speed=90.0, throttle=0.2, brake=0.0)
        mensajes += conduccion_normal(3.0, 30)

        salidas = [a for a in incidentes_de(mensajes, solo_cerradas=True)
                   if "fuera de pista" in a["titulo"]]
        self.assertEqual(salidas, [])

    def test_las_cuatro_ruedas_fuera_del_asfalto_se_anotan(self):
        mensajes = conduccion_normal(0.0, 10)
        for i in range(6):
            t = 1.0 + i * 0.05
            mensajes += marco(t, **{f"surface_type_{r}": 7
                                    for r in anotador_vivo.RUEDAS})
            mensajes += marco(t, speed=90.0, throttle=0.2, brake=0.0)
        mensajes += conduccion_normal(3.0, 30)

        incidentes = incidentes_de(mensajes, solo_cerradas=True)
        self.assertEqual(len(incidentes), 1)
        self.assertEqual(incidentes[0]["titulo"], "fuera de pista")
        # El nombre de la superficie sale de la especificacion, no de la prueba.
        self.assertIn("cesped", incidentes[0]["detalle"])

    def test_un_canal_de_superficie_ausente_hace_que_la_regla_se_abstenga(self):
        """Con tres ruedas fuera y una sin dato, no se puede afirmar la salida.

        La que falta podria ser justamente la que sigue tocando la pista.
        """

        anotador = anotador_vivo.Anotador()
        for i in range(6):
            t = 1.0 + i * 0.05
            for m in marco(t, surface_type_rear_left=7,
                           surface_type_rear_right=7,
                           surface_type_front_left=7):
                anotador.observar(m)
            for m in marco(t, speed=90.0, throttle=0.2, brake=0.0):
                anotador.observar(m)
        anotador.cerrar_pendiente()
        self.assertEqual(list(anotador.anotaciones), [])

    def test_el_impacto_vertical_dura_lo_que_duro(self):
        """Un golpe de un marco no puede declararse como medio segundo de golpe.

        La aceleracion vertical es un pico y no un estado: entre dos muestras el
        vehiculo no sigue recibiendo dos g. Antes de distinguirlo, el valor alto
        seguia contando durante las decenas de mensajes de otros canales que
        llegaban despues, y un golpe instantaneo aparecia durando cuatro decimas.
        """

        mensajes = conduccion_normal(0.0, 10)
        mensajes += marco(1.0, g_force_vertical=2.4)
        # Muchos mensajes de otros canales despues del golpe, todos dentro de la
        # tolerancia de vejez. Antes, cada uno reabria el mismo golpe.
        for i in range(8):
            t = 1.0 + (i + 1) * 0.02
            mensajes += asfalto(t)
            mensajes += marco(t, speed=200.0, throttle=0.9, brake=0.0)
        mensajes += conduccion_normal(3.0, 30)

        incidentes = incidentes_de(mensajes, solo_cerradas=True)
        self.assertEqual(len(incidentes), 1)
        self.assertEqual(incidentes[0]["titulo"], "impacto vertical")
        self.assertEqual(incidentes[0]["duracion_s"], 0.0)

    def test_la_perdida_de_tren_trasero_requiere_acelerador(self):
        """Deslizar con el acelerador suelto es frenar, no perder el eje."""

        mensajes = conduccion_normal(0.0, 10)
        for i in range(6):
            t = 1.0 + i * 0.05
            mensajes += asfalto(t)
            mensajes += marco(t, speed=90.0, throttle=0.0, brake=0.0,
                              wheel_slip_ratio_rear_left=0.6,
                              wheel_slip_ratio_rear_right=0.6)
        self.assertEqual(incidentes_de(mensajes), [])

    def test_una_frenada_fuerte_no_es_una_caida_brusca(self):
        """Se frena fuerte y se suelta al entrar en la curva.

        Verificar el freno solo en el instante final convertia cada frenada
        normal en un incidente: en ese marco la regla veia una caida grande con
        el freno libre. Diez de las anotaciones sobre vueltas limpias venian
        de ahi.
        """

        mensajes = conduccion_normal(0.0, 10)
        velocidad = 300.0
        for i in range(10):
            t = 1.0 + i * 0.05
            velocidad -= 12.0
            mensajes += asfalto(t)
            # Se frena en toda la ventana salvo en el ultimo instante.
            mensajes += marco(t, speed=velocidad, throttle=0.0,
                              brake=0.0 if i == 9 else 1.0,
                              g_force_vertical=0.1)
        self.assertEqual(incidentes_de(mensajes), [])

    def test_una_caida_sin_frenar_si_se_anota(self):
        mensajes = conduccion_normal(0.0, 10)
        velocidad = 300.0
        for i in range(10):
            t = 1.0 + i * 0.05
            velocidad -= 12.0
            mensajes += asfalto(t)
            mensajes += marco(t, speed=velocidad, throttle=0.0, brake=0.0,
                              g_force_vertical=0.1)
        self.assertTrue(any("caida brusca" in a["titulo"]
                            for a in incidentes_de(mensajes)))


class AusenciaYVejez(unittest.TestCase):

    def test_un_canal_ausente_no_dispara_ni_silencia_una_regla(self):
        """Sin el canal, la regla se abstiene. No decide que no paso nada.

        El deslizamiento de rueda todavia no forma parte del contrato interno.
        Que una regla no pueda evaluarse no es lo mismo que que no haya pasado
        nada, y confundir las dos cosas es como se construye una conclusion
        falsa.
        """

        anotador = anotador_vivo.Anotador()
        for m in conduccion_normal(0.0, 10):
            if "wheel_slip_ratio" in m["signal_name"]:
                continue
            anotador.observar(m)
        self.assertFalse(any(f"wheel_slip_ratio_{r}" in anotador.ultimos
                             for r in ("rear_left", "rear_right")))
        self.assertEqual(list(anotador.anotaciones), [])

    def test_un_valor_viejo_no_se_junta_con_uno_nuevo(self):
        """Componer un instante con un canal de hace dos segundos inventa un marco.

        Dos ruedas sobre el cesped ahora y una tercera dos segundos despues no
        son tres ruedas fuera: son dos momentos distintos. Sin la tolerancia de
        vejez, el anotador los sumaria y declararia una salida de pista que nunca
        existio.
        """

        anotador = anotador_vivo.Anotador()
        for m in marco(0.0, surface_type_rear_left=7, surface_type_rear_right=7,
                       surface_type_front_left=0, surface_type_front_right=0):
            anotador.observar(m)
        # Dos ruedas no alcanzan: hasta aca no hay nada anotado.
        self.assertEqual(list(anotador.anotaciones), [])

        # Dos segundos despues llega la tercera. Las dos primeras ya vencieron.
        salidas = anotador.observar(mensaje("surface_type_front_left", 7, 2.0))
        self.assertEqual([a for a in salidas if a["nivel"] == "incidente"], [])


# --------------------------------------------------------------------------- #
# 2. Puntualidad: el aviso llega al empezar, no al terminar
# --------------------------------------------------------------------------- #

class Puntualidad(unittest.TestCase):

    def test_el_incidente_se_avisa_al_empezar_y_se_corrige_al_terminar(self):
        """En vivo, el aviso exacto que llega tarde es el que no sirve."""

        mensajes = conduccion_normal(0.0, 10)
        for i in range(20):
            t = 1.0 + i * 0.05
            mensajes += marco(t, **{f"surface_type_{r}": 7
                                    for r in anotador_vivo.RUEDAS})
            mensajes += marco(t, speed=90.0, throttle=0.2, brake=0.0)
        mensajes += conduccion_normal(4.0, 30)

        emitidas: list[dict] = []
        anotador = anotador_vivo.Anotador(al_anotar=emitidas.append)
        for m in mensajes:
            anotador.observar(m)
        anotador.cerrar_pendiente()

        incidentes = [a for a in emitidas if a["nivel"] == "incidente"]
        # Dos emisiones: el aviso inmediato y la correccion final.
        self.assertEqual(len(incidentes), 2)
        self.assertFalse(incidentes[0]["cerrada"])
        self.assertTrue(incidentes[1]["cerrada"])
        self.assertEqual(incidentes[0]["id"], incidentes[1]["id"])
        # La final es mas larga que la inmediata: por eso hay dos.
        self.assertGreater(incidentes[1]["duracion_s"],
                           incidentes[0]["duracion_s"])
        # Y la lista conservada guarda **un** incidente, no dos.
        self.assertEqual(len([a for a in anotador.anotaciones
                              if a["nivel"] == "incidente"]), 1)


# --------------------------------------------------------------------------- #
# 3. Avisos: los que el juego mismo declara
# --------------------------------------------------------------------------- #

class Avisos(unittest.TestCase):

    def test_el_combustible_negativo_avisa_una_sola_vez(self):
        anotador = anotador_vivo.Anotador()
        salidas: list[dict] = []
        for i in range(10):
            salidas += anotador.observar(
                mensaje("fuel_remaining_laps", -0.4, i * 0.05))
        avisos = [a for a in salidas if a["nivel"] == "aviso"]
        self.assertEqual(len(avisos), 1)
        self.assertIn("no alcanza", avisos[0]["titulo"])

    def test_el_aviso_vuelve_si_la_condicion_se_fue_y_volvio(self):
        anotador = anotador_vivo.Anotador()
        salidas: list[dict] = []
        salidas += anotador.observar(mensaje("fuel_remaining_laps", -0.4, 0.0))
        salidas += anotador.observar(mensaje("fuel_remaining_laps", 1.2, 1.0))
        salidas += anotador.observar(mensaje("fuel_remaining_laps", -0.2, 2.0))
        self.assertEqual(len([a for a in salidas if a["nivel"] == "aviso"]), 2)

    def test_el_dano_se_avisa_cuando_aparece(self):
        anotador = anotador_vivo.Anotador()
        salidas = anotador.observar(mensaje("front_left_wing_damage", 0.0, 0.0))
        self.assertEqual([a for a in salidas if a["nivel"] == "aviso"], [])
        salidas = anotador.observar(mensaje("front_left_wing_damage", 12.0, 1.0))
        avisos = [a for a in salidas if a["nivel"] == "aviso"]
        self.assertEqual(len(avisos), 1)
        self.assertIn("aleron delantero izquierdo", avisos[0]["titulo"])


# --------------------------------------------------------------------------- #
# 4. Los dos modulos tienen que decir lo mismo
# --------------------------------------------------------------------------- #

class AcuerdoConLaLecturaPosterior(unittest.TestCase):

    #: Los mismos incidentes que la lectura posterior encuentra sobre la misma
    #: captura, contados con el mismo criterio de duracion minima. Los numeros no
    #: se eligieron: se midieron una vez que las dos lecturas coincidieron suceso
    #: por suceso, y estan aca para que una no pueda cambiar sin la otra.
    #:
    #: Eran 7 y 10 mientras la salida de pista se decidia con un criterio propio
    #: —tres ruedas fuera de asfalto y piano—. Al adoptar la definicion del
    #: articulo 33.3, que no cuenta al piano como pista y exige que salga todo el
    #: vehiculo, pasaron a 9 y 15. **Las dos vueltas que el juego invalido y el
    #: criterio propio no explicaba quedaron explicadas.**
    ESPERADOS = {
        "20260831_2022_hungaroring_contrarreloj": 9,   # con control de traccion
        "20260831_2041_hungaroring_contrarreloj": 15,  # sin control de traccion
    }

    def test_los_umbrales_coinciden_con_los_de_la_lectura_posterior(self):
        """Estan escritos dos veces y nada mas que esto obliga a que coincidan."""

        ruta = RAIZ / "scripts" / "analizar_vueltas_f1_25.py"
        especificacion = importlib.util.spec_from_file_location("_detector", ruta)
        detector = importlib.util.module_from_spec(especificacion)
        especificacion.loader.exec_module(detector)

        self.assertEqual(detector.UMBRAL_VERTICAL_G,
                         anotador_vivo.UMBRAL_VERTICAL_G)
        self.assertEqual(detector.UMBRAL_DESLIZAMIENTO,
                         anotador_vivo.UMBRAL_DESLIZAMIENTO)
        self.assertEqual(detector.UMBRAL_CAIDA_KMH,
                         anotador_vivo.UMBRAL_CAIDA_KMH)
        self.assertEqual(detector.VENTANA_CAIDA_S,
                         anotador_vivo.VENTANA_CAIDA_S)
        # Y la tabla de superficies tiene que ser **el mismo objeto**, no una
        # copia con los mismos valores: fue una copia lo que quedo corrido.
        self.assertIs(detector.SUPERFICIES, f1_udp.SUPERFICIES)
        self.assertIs(anotador_vivo.SUPERFICIES, f1_udp.SUPERFICIES)

    def test_coincide_con_la_lectura_posterior_sobre_las_capturas_reales(self):
        for nombre, esperados in self.ESPERADOS.items():
            with self.subTest(captura=nombre):
                captura = CAPTURAS / f"{nombre}.f1raw"
                if not captura.exists():
                    self.skipTest(f"captura ausente: {captura.name}")
                incidentes = [a for a in anotar_captura(captura)
                              if a["nivel"] == "incidente"
                              and a["duracion_s"] >= 0.15]
                self.assertEqual(len(incidentes), esperados)

    def test_la_definicion_reglamentaria_explica_lo_que_el_juego_invalido(self):
        """La validacion externa: el reglamento contra el arbitro.

        El juego invalida vueltas por exceder los limites de pista, y lo hace con
        su propio criterio, que no publica. Si la regla de este trabajo implementa
        bien el articulo 33.3, tiene que encontrar una salida en las vueltas que
        el juego invalido por ese motivo.

        Es el mismo tipo de verificacion que ya se hizo con los limites de energia
        del reglamento tecnico: **contrastar el dato contra una fuente externa al
        trabajo**, y no contra otra parte del propio trabajo.

        El criterio propio anterior explicaba **una** de las cuatro vueltas
        invalidadas de las dos capturas. El del articulo 33.3 explica **tres**.

        La cuarta —la vuelta 5 de la captura sin control de traccion— se captura
        entera, empieza valida, y los canales de superficie no muestran ninguna
        rueda fuera del asfalto en toda la vuelta. Queda declarada como no
        explicada, y esta prueba la excluye por nombre para que la excepcion sea
        visible en lugar de estar escondida en un umbral.
        """

        SIN_EXPLICAR = {("20260831_2041_hungaroring_contrarreloj", 5)}

        for nombre in ("20260831_2022_hungaroring_contrarreloj",
                       "20260831_2041_hungaroring_contrarreloj"):
            captura = CAPTURAS / f"{nombre}.f1raw"
            if not captura.exists():
                self.skipTest(f"captura ausente: {captura.name}")

            anotador = anotador_vivo.Anotador()
            invalidadas: set[int] = set()
            for m in desde_captura(captura):
                if m["signal_name"] == "lap_invalid" and m["value"]:
                    vuelta = anotador.ultimos.get("lap_number")
                    if vuelta is not None:
                        invalidadas.add(int(vuelta[0]))
                anotador.observar(m)
            anotador.cerrar_pendiente()

            con_salida = {a["vuelta"] for a in anotador.anotaciones
                          if "fuera de pista" in a["titulo"]
                          and a.get("vuelta") is not None}

            for vuelta in sorted(invalidadas):
                if (nombre, vuelta) in SIN_EXPLICAR:
                    continue
                with self.subTest(captura=nombre, vuelta=vuelta):
                    self.assertIn(
                        vuelta, con_salida,
                        f"el juego invalido la vuelta {vuelta} y la regla del "
                        f"articulo 33.3 no encuentra ninguna salida en ella")

    def test_sin_control_de_traccion_hay_mas_perdidas_que_con_el(self):
        """El resultado que separa las dos condiciones sin decirle cual es cual.

        Es la afirmacion que sostiene el capitulo de analisis: el detector
        distingue una conduccion asistida de una sin asistir mirando solo los
        canales. Si algun dia dejara de distinguirlas, esa afirmacion habria que
        retirarla del informe.
        """

        conteos = {}
        for etiqueta, nombre in (
                ("con", "20260831_2022_hungaroring_contrarreloj"),
                ("sin", "20260831_2041_hungaroring_contrarreloj")):
            captura = CAPTURAS / f"{nombre}.f1raw"
            if not captura.exists():
                self.skipTest(f"captura ausente: {captura.name}")
            conteos[etiqueta] = len([
                a for a in anotar_captura(captura)
                if a["nivel"] == "incidente"
                and "perdida de tren trasero" in a["titulo"]
                and a["duracion_s"] >= 0.15])

        self.assertGreater(conteos["sin"], conteos["con"])


# --------------------------------------------------------------------------- #
# 5. La sospecha: no solo que paso, sino que venia pasando antes
# --------------------------------------------------------------------------- #

class Sospecha(unittest.TestCase):
    """La parte que convierte un aviso en una explicacion.

    Todas estas pruebas construyen la secuencia a mano, con el antecedente
    puesto por quien escribe la prueba, de modo que lo que se verifica es que el
    anotador lo encuentre y no que coincida consigo mismo.
    """

    def test_un_golpe_precedido_de_un_piano_lo_atribuye_al_piano(self):
        mensajes = conduccion_normal(0.0, 20)

        # Medio segundo sobre el piano, con golpe vertical, antes del incidente.
        for i in range(10):
            t = 1.0 + i * 0.05
            mensajes += marco(t, **{f"surface_type_{r}": 1
                                    for r in anotador_vivo.RUEDAS})
            mensajes += marco(t, speed=200.0, throttle=0.9, brake=0.0,
                              g_force_vertical=1.1, lap_distance=1000.0 + i * 5)
        # Y ahora el golpe.
        mensajes += asfalto(1.6)
        mensajes += marco(1.6, speed=200.0, throttle=0.9, brake=0.0,
                          lap_distance=1055.0)
        mensajes += marco(1.6, g_force_vertical=2.9)
        mensajes += conduccion_normal(3.0, 40)

        # El piano genera ademas su propia salida de pista, que es correcto:
        # con las cuatro ruedas ahi el vehiculo dejo la pista. Lo que esta
        # prueba verifica es el golpe posterior y a que se lo atribuye.
        golpes = [a for a in incidentes_de(mensajes, solo_cerradas=True)
                  if "impacto vertical" in a["titulo"]]
        self.assertEqual(len(golpes), 1)
        self.assertEqual(golpes[0]["sospecha"], "piso un piano")
        self.assertIn("piano", golpes[0]["sospecha_evidencia"])

    def test_un_piano_pisado_sin_golpe_no_es_la_explicacion(self):
        """Pisar el piano es rutina: en vueltas limpias hay 2.083 muestras.

        Solo cuenta como antecedente si vino con un golpe por encima del
        percentil 99 de la aceleracion vertical normal. Sin eso, atribuirle el
        incidente al piano seria atribuirselo a como se conduce.
        """

        mensajes = conduccion_normal(0.0, 20)
        for i in range(10):
            t = 1.0 + i * 0.05
            mensajes += marco(t, **{f"surface_type_{r}": 1
                                    for r in anotador_vivo.RUEDAS})
            # Piano tomado con suavidad: por debajo del percentil 99.
            mensajes += marco(t, speed=200.0, throttle=0.9, brake=0.0,
                              g_force_vertical=0.3, lap_distance=1000.0 + i * 5)
        mensajes += asfalto(1.6)
        mensajes += marco(1.6, speed=200.0, throttle=0.9, brake=0.0,
                          lap_distance=1055.0)
        mensajes += marco(1.6, g_force_vertical=2.9)
        mensajes += conduccion_normal(3.0, 40)

        golpes = [a for a in incidentes_de(mensajes, solo_cerradas=True)
                  if "impacto vertical" in a["titulo"]]
        self.assertEqual(len(golpes), 1)
        self.assertNotEqual(golpes[0].get("sospecha"), "piso un piano")

    def test_una_salida_precedida_de_deslizamiento_lo_atribuye_al_eje(self):
        """Es la vuelta 3 de la captura con asistencia, en miniatura.

        El vehiculo toco el muro en el metro 812 y el eje trasero se le habia ido
        en el 770. Anotar el golpe sin su origen es contar la mitad del suceso.
        """

        mensajes = conduccion_normal(0.0, 20)
        # Deslizamiento con el acelerador a fondo, cuarenta metros antes.
        for i in range(8):
            t = 1.0 + i * 0.05
            mensajes += asfalto(t)
            mensajes += marco(t, speed=160.0, throttle=1.0, brake=0.0,
                              lap_distance=770.0 + i * 5,
                              wheel_slip_ratio_rear_left=0.30,
                              wheel_slip_ratio_rear_right=0.30)
        # Y la salida al cesped.
        for i in range(8):
            t = 1.5 + i * 0.05
            mensajes += marco(t, **{f"surface_type_{r}": 7
                                    for r in anotador_vivo.RUEDAS})
            mensajes += marco(t, speed=110.0, throttle=0.0, brake=0.0,
                              lap_distance=812.0 + i * 3,
                              wheel_slip_ratio_rear_left=0.0,
                              wheel_slip_ratio_rear_right=0.0)
        mensajes += conduccion_normal(4.0, 40)

        incidentes = incidentes_de(mensajes, solo_cerradas=True)
        salidas = [a for a in incidentes if "fuera de pista" in a["titulo"]]
        self.assertTrue(salidas)
        self.assertEqual(salidas[0]["sospecha"], "perdio el tren trasero antes")
        self.assertIn("100 %", salidas[0]["sospecha_evidencia"])

    def test_deslizar_con_el_acelerador_cerrado_no_es_perder_traccion(self):
        """Sin par no hay traccion que perder: es un trompo o una rueda trabada.

        La regla del incidente ya exige acelerador para llamarlo perdida de
        traccion. La de la sospecha tiene que respetar la misma distincion, o
        afirmaria mas de lo que el canal sostiene.
        """

        mensajes = conduccion_normal(0.0, 20)
        for i in range(8):
            t = 1.0 + i * 0.05
            mensajes += asfalto(t)
            mensajes += marco(t, speed=60.0, throttle=0.0, brake=0.0,
                              lap_distance=770.0 + i * 2,
                              wheel_slip_ratio_rear_left=0.9,
                              wheel_slip_ratio_rear_right=0.9)
        for i in range(8):
            t = 1.5 + i * 0.05
            mensajes += marco(t, **{f"surface_type_{r}": 7
                                    for r in anotador_vivo.RUEDAS})
            mensajes += marco(t, speed=40.0, throttle=0.0, brake=0.0,
                              lap_distance=790.0 + i * 2,
                              wheel_slip_ratio_rear_left=0.0,
                              wheel_slip_ratio_rear_right=0.0)
        mensajes += conduccion_normal(4.0, 40)

        salidas = [a for a in incidentes_de(mensajes, solo_cerradas=True)
                   if "fuera de pista" in a["titulo"]]
        self.assertTrue(salidas)
        self.assertEqual(salidas[0]["sospecha"], "el vehiculo ya venia cruzado")

    def test_sin_antecedente_no_inventa_uno(self):
        """Callarse es una respuesta valida y una sospecha falsa no lo es."""

        mensajes = conduccion_normal(0.0, 30)
        mensajes += marco(2.0, g_force_vertical=2.9)
        mensajes += conduccion_normal(3.5, 40)

        incidentes = incidentes_de(mensajes, solo_cerradas=True)
        self.assertEqual(len(incidentes), 1)
        self.assertNotIn("sospecha", incidentes[0])


# --------------------------------------------------------------------------- #
# 6. El circuito aprendido de la propia sesion
# --------------------------------------------------------------------------- #

class CircuitoAprendido(unittest.TestCase):

    @staticmethod
    def vuelta(anotador, numero, curvas_en, largo=3000.0, invalida=False,
               desde_t=0.0, paso=0.05):
        """Corre una vuelta entera por el anotador, con sus curvas donde se diga."""

        t = desde_t
        distancia = 0.0
        while distancia < largo:
            lateral = 0.05
            for centro, ancho, pico in curvas_en:
                if abs(distancia - centro) <= ancho:
                    lateral = pico
            for m in asfalto(t):
                anotador.observar(m)
            for m in marco(t, lap_number=numero, lap_distance=distancia,
                           lap_invalid=1.0 if invalida else 0.0,
                           speed=200.0, throttle=0.9, brake=0.0,
                           g_force_vertical=0.06, g_force_lateral=lateral,
                           wheel_slip_ratio_rear_left=0.02,
                           wheel_slip_ratio_rear_right=0.02):
                anotador.observar(m)
            distancia += 5.0
            t += paso
        return t

    def test_aprende_las_curvas_y_las_nombra(self):
        anotador = anotador_vivo.Anotador()
        puestas = [(500.0, 60.0, 3.0), (1500.0, 80.0, -4.0), (2500.0, 50.0, 2.5)]

        t = 0.0
        for numero in (1, 2, 3):
            t = self.vuelta(anotador, numero, puestas, desde_t=t)
        # La decision sobre una vuelta se difiere un giro, de modo que hacen
        # falta tres para que la primera este incorporada.
        self.assertGreaterEqual(len(anotador.catalogo.curvas), 1)
        self.assertTrue(anotador.ubicar(500.0).startswith("curva"))

    def test_antes_de_aprender_ubica_por_metro_y_no_calla(self):
        anotador = anotador_vivo.Anotador()
        self.assertEqual(anotador.ubicar(812.0), "metro 812")

    def test_una_vuelta_invalidada_no_sirve_de_referencia(self):
        anotador = anotador_vivo.Anotador()
        puestas = [(500.0, 60.0, 3.0)]
        t = self.vuelta(anotador, 1, puestas, invalida=True)
        t = self.vuelta(anotador, 2, puestas, invalida=True, desde_t=t)
        self.vuelta(anotador, 3, puestas, invalida=True, desde_t=t)
        self.assertEqual(anotador.catalogo.curvas, [])


if __name__ == "__main__":
    unittest.main()
