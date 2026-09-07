# -*- coding: utf-8 -*-
"""El declarador de disponibilidad decide si una herramienta puede correr.

Lo que se prueba aca no es que consulte bien la base ---eso lo verifica la
corrida contra las tres fuentes reales--- sino **como clasifica**, que es donde
esta la decision. Las mediciones se inyectan, de modo que cada caso nombra
exactamente la condicion que quiere ejercitar.
"""

from __future__ import annotations

import unittest
from unittest import mock

from backend.analisis import disponibilidad as disp


class CursorFalso:
    """Devuelve mediciones preparadas, en el orden en que el modulo las pide.

    La primera consulta de `evaluar` es la del contexto; el resto son mediciones
    de senal. Se responden por nombre de senal y no por posicion, porque el
    modulo cachea las senales repetidas y contar llamadas ataria la prueba al
    detalle de ese cache.
    """

    def __init__(self, por_senal: dict[str, tuple | None]):
        self.por_senal = por_senal
        self._proxima: tuple | None = None
        self._contexto_pedido = False

    def execute(self, consulta: str, parametros: tuple) -> None:
        if "group by 1, 2, 3" in consulta:
            self._proxima = ("conductor", "vehiculo", "corrida")
            self._contexto_pedido = True
            return
        senal = parametros[2]
        # `count(*)` siempre devuelve una fila. Una senal sin muestras da cero,
        # no ausencia de fila: el simulacro tiene que imitar eso o la prueba
        # ejercitaria un caso que la base no produce.
        self._proxima = self.por_senal.get(senal) or _SIN_MUESTRAS

    def fetchone(self):
        return self._proxima

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class ConexionFalsa:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


#: Lo que la consulta devuelve cuando la senal no tiene muestras en la ventana.
_SIN_MUESTRAS = (0, None, 0, 0)


def _medicion(muestras: int, ventana: float, distintos: int,
              booleanos: int = 0) -> tuple:
    """La forma exacta que la consulta de medicion devuelve."""

    return (muestras, ventana, distintos, booleanos)


def _evaluar(herramienta: str, fuente: str, por_senal: dict) -> disp.Disponibilidad:
    cursor = CursorFalso(por_senal)
    with mock.patch.object(disp.db, "obtener_conexion",
                           return_value=ConexionFalsa(cursor)):
        return disp.evaluar(herramienta, fuente, "sesion-de-prueba")


#: Una sesion del simulador con todo lo que las siete piden, holgado.
COMPLETO_SIMULADOR = {
    senal: _medicion(2400, 120.0, 500)
    for senal in ("lap_number", "lap_invalid", "pit_status", "fia_flag",
                  "lap_distance", "speed", "current_lap_time",
                  "g_force_lateral", "steering_normalized", "brake_position",
                  "throttle_position", "wheel_slip_ratio_rear_left",
                  "tyre_wear_front_left")
}


class EstadoTest(unittest.TestCase):

    def test_todo_presente_es_completa(self):
        d = _evaluar("vueltas_limpias", "f1_25_udp_simulation",
                     COMPLETO_SIMULADOR)
        self.assertEqual(d.estado, disp.COMPLETA)
        self.assertEqual(d.limitaciones, [])
        self.assertEqual(d.impedimentos, [])

    def test_falta_una_esencial_y_es_imposible(self):
        """Sin numero de vuelta no hay vuelta que filtrar."""

        d = _evaluar("vueltas_limpias", "can_real_replay", {})
        self.assertEqual(d.estado, disp.IMPOSIBLE)
        self.assertTrue(d.impedimentos)

    def test_falta_una_accesoria_y_es_degradada(self):
        """La herramienta corre; lo que no puede hacer queda nombrado."""

        sin_boxes = dict(COMPLETO_SIMULADOR)
        del sin_boxes["pit_status"]
        d = _evaluar("vueltas_limpias", "f1_25_udp_simulation", sin_boxes)
        self.assertEqual(d.estado, disp.DEGRADADA)
        self.assertEqual(d.impedimentos, [])
        self.assertTrue(any("boxes" in l for l in d.limitaciones))

    def test_la_limitacion_nombra_el_resultado_y_no_la_senal(self):
        """Es la razon de ser del campo `para`.

        Una limitacion que dice «falta pit_status» obliga a quien lee a saber que
        es pit_status. Una que dice que no se puede descartar la vuelta de boxes
        se entiende sin conocer el protocolo.
        """

        sin_boxes = dict(COMPLETO_SIMULADOR)
        del sin_boxes["pit_status"]
        d = _evaluar("vueltas_limpias", "f1_25_udp_simulation", sin_boxes)
        texto = " ".join(d.limitaciones)
        self.assertIn("boxes", texto)
        self.assertNotIn("pit_status", texto)


class EscalaTest(unittest.TestCase):
    """Un interruptor cumple la presencia y no la escala."""

    def test_freno_booleano_degrada_las_frenadas_sin_impedirlas(self):
        """Lo que un interruptor no da es la presion; el resto si.

        Declararlo no disponible descartaria el punto de frenada, la duracion y
        las velocidades, que un interruptor si permite medir.
        """

        por_senal = {"brake_applied": _medicion(444, 120.0, 2, booleanos=444),
                     "speed": _medicion(2400, 120.0, 500)}
        d = _evaluar("zonas_de_frenada", "openf1_historical_replay", por_senal)
        self.assertEqual(d.estado, disp.DEGRADADA)
        self.assertTrue(any("presion" in l for l in d.limitaciones))

    def test_pocos_valores_distintos_tambien_es_interruptor(self):
        """Un canal guardado como numero que solo toma dos valores lo es igual."""

        por_senal = {"brake_applied": _medicion(444, 120.0, 2),
                     "speed": _medicion(2400, 120.0, 500)}
        d = _evaluar("zonas_de_frenada", "openf1_historical_replay", por_senal)
        self.assertTrue(any("interruptor" in l for l in d.limitaciones))

    def test_escala_continua_no_degrada(self):
        d = _evaluar("zonas_de_frenada", "f1_25_udp_simulation",
                     COMPLETO_SIMULADOR)
        self.assertEqual(d.estado, disp.COMPLETA)


class ResolucionTest(unittest.TestCase):
    """La resolucion se declara en metros, que es la unidad en que decide."""

    def test_muestreo_espaciado_degrada_y_dice_cuantos_metros(self):
        """A 3,7 Hz y 200 km/h hay quince metros entre muestra y muestra."""

        por_senal = {"brake_position": _medicion(2400, 120.0, 500),
                     "speed": _medicion(444, 120.0, 500),
                     "lap_distance": _medicion(2400, 120.0, 500)}
        d = _evaluar("zonas_de_frenada", "f1_25_udp_simulation", por_senal)
        self.assertEqual(d.estado, disp.DEGRADADA)
        texto = " ".join(d.limitaciones)
        self.assertIn("15.0 m", texto)
        self.assertIn("3.7 Hz", texto)

    def test_muestreo_denso_no_degrada(self):
        """A 20 Hz la separacion es de 2,8 m, por debajo de los 5 declarados."""

        d = _evaluar("zonas_de_frenada", "f1_25_udp_simulation",
                     COMPLETO_SIMULADOR)
        self.assertEqual(d.estado, disp.COMPLETA)

    def test_la_limitacion_por_resolucion_lleva_su_fundamento(self):
        """Un umbral sin motivo es una cifra inventada."""

        por_senal = {"brake_position": _medicion(2400, 120.0, 500),
                     "speed": _medicion(444, 120.0, 500),
                     "lap_distance": _medicion(2400, 120.0, 500)}
        d = _evaluar("zonas_de_frenada", "f1_25_udp_simulation", por_senal)
        self.assertTrue(any("decima" in l for l in d.limitaciones))


class MedicionTest(unittest.TestCase):

    def test_se_mide_sobre_un_vehiculo_y_una_corrida(self):
        """Promediar la sesion entera multiplica la frecuencia.

        Es el error que la corrida real destapo dos veces: por vehiculo, la
        fuente deportiva declaraba 84,9 Hz en lugar de 3,7 al sumar sus
        veintitres pilotos; por corrida, 7,4 al sumar dos reinyecciones que
        comparten las marcas de tiempo originales.
        """

        d = _evaluar("vueltas_limpias", "f1_25_udp_simulation",
                     COMPLETO_SIMULADOR)
        self.assertIn("vehiculo", d.medido_sobre)
        self.assertIn("corrida", d.medido_sobre)

    def test_senal_publicada_pero_sin_muestras_no_es_lo_mismo_que_ausente(self):
        """La fuente la tiene y esta sesion no. El motivo lo dice."""

        casi = dict(COMPLETO_SIMULADOR)
        casi["pit_status"] = None
        d = _evaluar("vueltas_limpias", "f1_25_udp_simulation", casi)
        self.assertEqual(d.estado, disp.DEGRADADA)
        self.assertTrue(any("esta sesion no tiene muestras" in l
                            for l in d.limitaciones))


class CatalogoTest(unittest.TestCase):

    def test_son_siete_y_el_filtro_va_primero(self):
        """El orden es de construccion: sin vueltas limpias lo demas es invalido."""

        hs = disp.herramientas()
        self.assertEqual(len(hs), 7)
        self.assertEqual(hs[0].clave, "vueltas_limpias")

    def test_toda_magnitud_pedida_esta_catalogada(self):
        """Un nombre mal escrito seria una limitacion inventada del dato."""

        for h in disp.herramientas():
            for req in h.requisitos:
                self.assertIn(req.magnitud, disp._POR_MAGNITUD,
                              f"{h.clave} pide {req.magnitud!r}")

    def test_todo_requisito_dice_para_que(self):
        """`para` es el texto de la limitacion, no documentacion."""

        for h in disp.herramientas():
            for req in h.requisitos:
                self.assertTrue(req.para.strip())

    def test_todo_umbral_de_resolucion_lleva_motivo(self):
        for h in disp.herramientas():
            for req in h.requisitos:
                if req.resolucion_maxima_m:
                    self.assertTrue(req.motivo_resolucion.strip(),
                                    f"{h.clave}: umbral sin fundamento")

    def test_herramienta_desconocida_falla(self):
        with self.assertRaises(KeyError):
            _evaluar("no_existe", "f1_25_udp_simulation", {})


if __name__ == "__main__":
    unittest.main()
