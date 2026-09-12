# -*- coding: utf-8 -*-
"""La separacion en vueltas y el filtro de las comparables.

Las filas se inyectan escritas a mano. Lo que se ejercita es **el criterio**: que
cada motivo aparezca cuando el canal lo declara, que ninguno aparezca cuando no, y
que lo que el modulo promete sobre su propia precision sea lo que informa.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from backend.analisis import disponibilidad as disp
from backend.analisis import vueltas as vu

ORIGEN = datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc)
#: Veinte hercios, que es el paso de la fuente de simulacion.
PASO_MS = 50


class CursorFalso:
    def __init__(self, filas):
        self.filas = filas

    def execute(self, *_args, **_kwargs):
        return None

    def fetchall(self):
        return self.filas

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


def _disponibilidad(estado=disp.COMPLETA, presentes=(
        vu.SENAL_NUMERO, vu.SENAL_INVALIDA, vu.SENAL_BOXES, vu.SENAL_BANDERA)):
    d = disp.Disponibilidad(
        herramienta="vueltas_limpias", nombre="Filtrado de vueltas limpias",
        fuente="f1_25_udp_simulation", session_id="s", estado=estado,
        contexto=("c", "v", "r"), medido_sobre="v / r")
    for senal in presentes:
        d.mediciones.append(disp.Medicion(magnitud=senal, senal=senal,
                                          presente=True, hz=20.0))
    return d


def _filas(guion: list[tuple[int, dict]], paso_ms: int = PASO_MS) -> list[tuple]:
    """Convierte un guion de (numero_de_vuelta, canales) en filas de la base.

    Cada entrada del guion es **una muestra**. El numero de vuelta se emite
    siempre; los demas canales, solo cuando el guion los nombra.
    """

    filas = []
    for i, (numero, canales) in enumerate(guion):
        marca = ORIGEN + timedelta(milliseconds=i * paso_ms)
        filas.append((marca, vu.SENAL_NUMERO, float(numero), None))
        for nombre, valor in canales.items():
            if nombre == vu.SENAL_INVALIDA:
                filas.append((marca, nombre, None, bool(valor)))
            else:
                filas.append((marca, nombre, float(valor), None))
    return filas


def _extraer(filas, disponibilidad=None) -> vu.Sesion:
    d = disponibilidad or _disponibilidad()
    cursor = CursorFalso(filas)
    with mock.patch.object(vu, "evaluar", return_value=d), \
            mock.patch.object(vu.db, "obtener_conexion",
                              return_value=ConexionFalsa(cursor)):
        return vu.extraer("f1_25_udp_simulation", "s")


def _guion_limpio(vueltas: int = 4, muestras: int = 6) -> list[tuple[int, dict]]:
    """Vueltas seguidas y sin nada que las ensucie, con su cronometro."""

    guion = []
    for numero in range(1, vueltas + 1):
        for j in range(muestras):
            guion.append((numero, {vu.SENAL_CRONOMETRO: j * PASO_MS}))
    return guion


class SeparacionTest(unittest.TestCase):

    def test_una_vuelta_por_cada_numero(self):
        s = _extraer(_filas(_guion_limpio(4)))
        self.assertEqual([v.numero for v in s.vueltas], [1, 2, 3, 4])

    def test_la_primera_y_la_ultima_quedan_incompletas(self):
        """No se presencio su borde: empiezan o terminan a mitad de camino."""

        s = _extraer(_filas(_guion_limpio(4)))
        self.assertIn(vu.MOTIVO_INCOMPLETA, s.vueltas[0].motivos)
        self.assertIn(vu.MOTIVO_INCOMPLETA, s.vueltas[-1].motivos)
        self.assertEqual(s.vueltas[1].motivos, [])
        self.assertEqual(s.vueltas[2].motivos, [])

    def test_una_vuelta_incompleta_no_se_cronometra(self):
        """Su duracion es desconocida, y se dice; no se informa la parcial."""

        s = _extraer(_filas(_guion_limpio(4)))
        self.assertIsNone(s.vueltas[0].duracion_s)
        self.assertIsNotNone(s.vueltas[1].duracion_s)


class MotivosTest(unittest.TestCase):

    def test_invalidada_por_la_sesion(self):
        guion = _guion_limpio(4)
        guion[8] = (2, {vu.SENAL_CRONOMETRO: 100, vu.SENAL_INVALIDA: True})
        s = _extraer(_filas(guion))
        self.assertIn(vu.MOTIVO_INVALIDADA, s.vueltas[1].motivos)
        self.assertFalse(s.vueltas[1].comparable)

    def test_un_solo_instante_en_boxes_ensucia_la_vuelta(self):
        """Mil instantes fuera de boxes no borran el que estuvo dentro."""

        guion = _guion_limpio(4)
        guion[8] = (2, {vu.SENAL_CRONOMETRO: 100, vu.SENAL_BOXES: 2})
        s = _extraer(_filas(guion))
        self.assertIn(vu.BOXES_QUE_ENSUCIAN[2], s.vueltas[1].motivos)

    def test_bandera_amarilla_ensucia(self):
        guion = _guion_limpio(4)
        guion[8] = (2, {vu.SENAL_CRONOMETRO: 100, vu.SENAL_BANDERA: 3})
        s = _extraer(_filas(guion))
        self.assertTrue(any("amarilla" in m for m in s.vueltas[1].motivos))

    def test_bandera_verde_no_ensucia(self):
        """La verde y la ausencia de bandera no cambian lo que se puede hacer."""

        guion = _guion_limpio(4)
        guion[8] = (2, {vu.SENAL_CRONOMETRO: 100, vu.SENAL_BANDERA: 1})
        guion[9] = (2, {vu.SENAL_CRONOMETRO: 150, vu.SENAL_BANDERA: 0})
        s = _extraer(_filas(guion))
        self.assertEqual(s.vueltas[1].motivos, [])

    def test_los_motivos_se_acumulan(self):
        """Una vuelta puede estar sucia por mas de una cosa, y se dicen todas."""

        guion = _guion_limpio(4)
        guion[8] = (2, {vu.SENAL_CRONOMETRO: 100, vu.SENAL_BOXES: 1,
                        vu.SENAL_INVALIDA: True})
        s = _extraer(_filas(guion))
        self.assertIn(vu.MOTIVO_INVALIDADA, s.vueltas[1].motivos)
        self.assertIn(vu.BOXES_QUE_ENSUCIAN[1], s.vueltas[1].motivos)

    def test_valida_y_comparable_no_son_lo_mismo(self):
        """El informe ya lo establece: son dos preguntas distintas.

        El canal de validez responde «esta vuelta cuenta para el reglamento». Una
        vuelta con paso por boxes no infringe nada ---sigue siendo valida--- y aun
        asi no sirve para comparar ritmo.
        """

        guion = _guion_limpio(4)
        guion[8] = (2, {vu.SENAL_CRONOMETRO: 100, vu.SENAL_BOXES: 2})
        s = _extraer(_filas(guion))
        self.assertTrue(s.vueltas[1].valida)
        self.assertFalse(s.vueltas[1].comparable)

    def test_una_vuelta_invalidada_tampoco_es_comparable(self):
        """La invalidez arrastra: lo que no cuenta tampoco compara."""

        guion = _guion_limpio(4)
        guion[8] = (2, {vu.SENAL_CRONOMETRO: 100, vu.SENAL_INVALIDA: True})
        s = _extraer(_filas(guion))
        self.assertFalse(s.vueltas[1].valida)
        self.assertFalse(s.vueltas[1].comparable)

    def test_una_vuelta_sucia_conserva_por_que(self):
        """Descartar sin decir por que obliga a confiar."""

        guion = _guion_limpio(4)
        guion[8] = (2, {vu.SENAL_CRONOMETRO: 100, vu.SENAL_INVALIDA: True})
        s = _extraer(_filas(guion))
        sucias = [v for v in s.vueltas if not v.comparable]
        self.assertTrue(all(v.motivos for v in sucias))


class DosCochesBajoUnaIdentidadTest(unittest.TestCase):
    """Una vuelta con otro coche adentro no se puede comparar con nada.

    POR QUE ESTO VIVE EN EL CODIGO Y NO EN UN DOCUMENTO. Medido el 2026-09-12,
    la sesion de Spa del conjunto `spa_original` tiene **dos conductores
    escritos bajo el mismo `vehicle_id`** en sus vueltas 1 y 2: dos series de
    20 Hz entrelazadas, con los coches hasta 577 metros separados. De la vuelta
    3 en adelante la serie es de uno solo.

    Quedo escrito en `docs/mediciones/`, y un documento **no impide que el
    proximo analisis use la vuelta 2**. Este modulo ya sabe decir «esta vuelta
    no es comparable, y por esto»; era ahi donde faltaba.

    LA FIRMA ES LA DISTANCIA QUE RETROCEDE Y VUELVE. Un coche solo nunca
    retrocede seiscientos metros; dos coches entrelazados lo hacen en cada
    muestra. El cruce de meta si retrocede ---de siete mil a cero--- y por eso
    un solo retroceso no alcanza para acusar a nadie.
    """

    @staticmethod
    def _con_distancia(vueltas, distancias_por_vuelta):
        """Un guion con `lap_distance` explicito en cada muestra."""
        guion = []
        for numero in range(1, vueltas + 1):
            for j, metro in enumerate(distancias_por_vuelta[numero - 1]):
                guion.append((numero, {vu.SENAL_CRONOMETRO: j * PASO_MS,
                                       vu.SENAL_DISTANCIA: metro}))
        return guion

    def _disp(self):
        return _disponibilidad(presentes=(
            vu.SENAL_NUMERO, vu.SENAL_INVALIDA, vu.SENAL_BOXES,
            vu.SENAL_BANDERA, vu.SENAL_DISTANCIA))

    def test_una_vuelta_de_un_solo_coche_es_comparable(self):
        avance = [[0.0, 100.0, 200.0, 300.0, 400.0, 500.0]] * 4
        s = _extraer(_filas(self._con_distancia(4, avance)), self._disp())
        self.assertEqual([v.numero for v in s.comparables], [2, 3])

    def test_el_cruce_de_meta_no_acusa_a_nadie(self):
        """Un solo retroceso es la vuelta que cierra, no otro coche."""
        con_cruce = [[6800.0, 6900.0, 20.0, 120.0, 220.0, 320.0]] * 4
        s = _extraer(_filas(self._con_distancia(4, con_cruce)), self._disp())
        self.assertEqual([v.numero for v in s.comparables], [2, 3])

    def test_dos_coches_entrelazados_dejan_la_vuelta_fuera(self):
        limpia = [0.0, 100.0, 200.0, 300.0, 400.0, 500.0]
        # El otro coche, quinientos metros mas atras, una muestra si y una no.
        mezclada = [2325.0, 1748.0, 2328.0, 1750.0, 2331.0, 1753.0]
        s = _extraer(_filas(self._con_distancia(
            4, [limpia, mezclada, limpia, limpia])), self._disp())
        self.assertEqual([v.numero for v in s.comparables], [3])
        dos = [v for v in s.vueltas if v.numero == 2][0]
        self.assertFalse(dos.comparable)
        self.assertTrue(any("coche" in m for m in dos.motivos), dos.motivos)

    def test_el_motivo_dice_cuantos_retrocesos_se_vieron(self):
        """Sin la cifra, el motivo se lee como una sospecha y no como una medida."""
        limpia = [0.0, 100.0, 200.0, 300.0, 400.0, 500.0]
        mezclada = [2325.0, 1748.0, 2328.0, 1750.0, 2331.0, 1753.0]
        s = _extraer(_filas(self._con_distancia(
            4, [limpia, mezclada, limpia, limpia])), self._disp())
        dos = [v for v in s.vueltas if v.numero == 2][0]
        self.assertTrue(any("3" in m for m in dos.motivos), dos.motivos)

    def test_sin_distancia_el_criterio_no_se_aplica_ni_se_inventa(self):
        """OpenF1 no publica distancia de vuelta: ahi no se puede mirar esto.

        Es la misma regla que rige para boxes y banderas: solo se aplican los
        criterios que la sesion admite. Acusar a una vuelta con un criterio que
        no se pudo evaluar seria peor que no evaluarlo.
        """
        s = _extraer(_filas(_guion_limpio()))
        for v in s.vueltas:
            self.assertFalse(any("coche" in m for m in v.motivos), v.motivos)


class PrecisionTest(unittest.TestCase):

    def test_la_incerteza_es_el_intervalo_de_muestreo(self):
        s = _extraer(_filas(_guion_limpio(4)))
        self.assertAlmostEqual(s.incerteza_duracion_s, PASO_MS / 1000.0, places=3)

    def test_un_salto_suelto_no_mejora_la_incerteza_declarada(self):
        """Es el error que la corrida real destapo.

        Quedandose con el ultimo intervalo, una sesion de veinte hercios
        declaraba diecisiete milisegundos: **una precision mejor que la real**,
        que es lo contrario de lo que el modulo existe para hacer. Con la mediana,
        un intervalo corto suelto no mueve la cifra.
        """

        filas = _filas(_guion_limpio(4))
        # Un ultimo par de muestras muy juntas, como produce un salto del flujo.
        ultima = filas[-1][0] + timedelta(milliseconds=7)
        filas.append((ultima, vu.SENAL_NUMERO, 4.0, None))
        s = _extraer(filas)
        self.assertAlmostEqual(s.incerteza_duracion_s, PASO_MS / 1000.0, places=3)


class DeclaracionTest(unittest.TestCase):

    def test_la_declaracion_viaja_con_el_resultado(self):
        s = _extraer(_filas(_guion_limpio(4)))
        self.assertEqual(s.disponibilidad.herramienta, "vueltas_limpias")
        self.assertEqual(s.disponibilidad.medido_sobre, "v / r")

    def test_sin_vueltas_se_levanta_y_dice_por_que(self):
        """Una fuente sin vueltas no es una sesion de vueltas sucias."""

        d = _disponibilidad(estado=disp.IMPOSIBLE)
        d.impedimentos.append("el vehiculo no da vueltas a nada")
        with self.assertRaises(vu.SinVueltas) as caja:
            _extraer([], disponibilidad=d)
        self.assertIn("no da vueltas", str(caja.exception))

    def test_sin_canal_de_boxes_no_se_inventa_la_vuelta_de_boxes(self):
        """La limitacion ya quedo declarada; el filtro simplemente no la aplica."""

        d = _disponibilidad(estado=disp.DEGRADADA,
                            presentes=(vu.SENAL_NUMERO, vu.SENAL_INVALIDA))
        d.limitaciones.append("no se puede descartar la vuelta de boxes")
        guion = _guion_limpio(4)
        guion[8] = (2, {vu.SENAL_CRONOMETRO: 100, vu.SENAL_BOXES: 2})
        s = _extraer(_filas(guion), disponibilidad=d)
        self.assertEqual(s.vueltas[1].motivos, [])
        self.assertEqual(s.disponibilidad.estado, disp.DEGRADADA)


class ResumenTest(unittest.TestCase):

    def test_dice_cuantas_quedaron_y_por_que_se_fueron(self):
        s = _extraer(_filas(_guion_limpio(4)))
        texto = vu.resumen(s)
        self.assertIn("2 comparables de 4", texto)
        self.assertIn(vu.MOTIVO_INCOMPLETA, texto)

    def test_avisa_cuando_el_filtro_corrio_degradado(self):
        d = _disponibilidad(estado=disp.DEGRADADA,
                            presentes=(vu.SENAL_NUMERO, vu.SENAL_INVALIDA))
        d.limitaciones.append("no se puede descartar la vuelta de boxes")
        s = _extraer(_filas(_guion_limpio(4)), disponibilidad=d)
        self.assertIn("limitaciones", vu.resumen(s))


if __name__ == "__main__":
    unittest.main()
