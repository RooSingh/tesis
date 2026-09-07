# -*- coding: utf-8 -*-
"""Curvas con sus fases, y caracterizacion de zonas de frenada.

Las muestras se construyen a mano con un recorrido conocido: una recta, una curva
y otra recta. Lo que se ejercita es el criterio de cada herramienta, y sobre todo
**que ninguna complete con un valor por defecto lo que la fuente no da**.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from backend.analisis import disponibilidad as disp
from backend.analisis import fases as fs
from backend.analisis import frenadas as fr
from backend.analisis import lectura as lec

ORIGEN = datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc)


class CursorFalso:
    def __init__(self, filas):
        self.filas = filas

    def execute(self, *_a, **_k):
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


def _disponibilidad(herramienta, senales, continua_freno=True,
                    estado=disp.COMPLETA):
    d = disp.Disponibilidad(herramienta=herramienta, nombre=herramienta,
                            fuente="f", session_id="s", estado=estado,
                            contexto=("c", "v", "r"), medido_sobre="v / r")
    for senal in senales:
        continua = continua_freno if senal in fr.SENALES_DE_FRENO else True
        d.mediciones.append(disp.Medicion(magnitud=senal, senal=senal,
                                          presente=True, hz=20.0,
                                          continua=continua))
    return d


def _recorrido(vuelta: int, guion: list[dict], paso_s: float = 0.05):
    """Construye filas de base a partir de un guion de muestras.

    Cada entrada del guion es un diccionario con `m` y opcionalmente `lateral`,
    `velocidad` y `freno`.
    """

    filas = [(ORIGEN, lec.SENAL_NUMERO, float(vuelta))]
    for i, punto in enumerate(guion):
        marca = ORIGEN + timedelta(seconds=i * paso_s)
        for clave, senal in (("lateral", lec.SENAL_LATERAL),
                             ("velocidad", lec.SENAL_VELOCIDAD),
                             ("freno", punto.get("_senal_freno", lec.SENAL_FRENO))):
            if clave in punto:
                filas.append((marca, senal, float(punto[clave])))
        filas.append((marca, lec.SENAL_DISTANCIA, float(punto["m"])))
    return filas


def _vuelta_con_una_curva(freno_desde=None, freno_hasta=None,
                          presion=0.8, senal_freno=lec.SENAL_FRENO):
    """Recta, una curva de 100 m con pico de lateral, y recta.

    El minimo de velocidad se coloca **despues** del pico de lateral, que es lo
    que hace que los dos anclajes de apice no coincidan.
    """

    guion = []
    for metro in range(0, 601, 10):
        lateral = 0.0
        velocidad = 250.0
        if 300 <= metro <= 400:
            # Pico de lateral en 340; minimo de velocidad en 370.
            lateral = 2.0 if metro == 340 else 1.2
            velocidad = 120.0 if metro == 370 else 150.0
        punto = {"m": float(metro), "lateral": lateral, "velocidad": velocidad}
        if freno_desde is not None and freno_desde <= metro <= freno_hasta:
            punto["freno"] = presion
            punto["_senal_freno"] = senal_freno
        elif freno_desde is not None:
            punto["freno"] = 0.0
            punto["_senal_freno"] = senal_freno
        guion.append(punto)
    return guion


def _con_base(filas, disponibilidad, funcion, *args, modulo=fs):
    cursor = CursorFalso(filas)
    with mock.patch.object(modulo, "evaluar", return_value=disponibilidad), \
            mock.patch.object(modulo.db, "obtener_conexion",
                              return_value=ConexionFalsa(cursor)):
        return funcion(*args)


class TrazadoTest(unittest.TestCase):

    def setUp(self):
        fs.limpiar_cache()

    def _trazado(self, con_freno=True):
        senales = [lec.SENAL_NUMERO, lec.SENAL_DISTANCIA, lec.SENAL_LATERAL,
                   lec.SENAL_VELOCIDAD]
        if con_freno:
            senales.append(lec.SENAL_FRENO)
        d = _disponibilidad("curvas_y_fases", senales)
        filas = []
        for n in (1, 2, 3):
            filas += _recorrido(n, _vuelta_con_una_curva(200, 300))
        sesion = mock.Mock()
        sesion.comparables = [mock.Mock(numero=n) for n in (1, 2, 3)]
        with mock.patch.object(fs, "extraer", return_value=sesion):
            return _con_base(filas, d, fs.trazado, "f", "s")

    def test_deriva_la_curva_del_dato(self):
        t = self._trazado()
        self.assertEqual(len(t.catalogo.curvas), 1)

    def test_la_curva_aparece_en_todas_las_vueltas(self):
        """Es el criterio con que el modulo se valida: la repeticion."""

        t = self._trazado()
        curva = t.catalogo.curvas[0]
        self.assertEqual(curva.vueltas_en_que_aparece, curva.vueltas_examinadas)

    def test_el_catalogo_se_cachea(self):
        """Derivarlo recorre varias vueltas; no se rehace en cada consulta."""

        primero = self._trazado()
        cursor = CursorFalso([])
        with mock.patch.object(fs.db, "obtener_conexion",
                               return_value=ConexionFalsa(cursor)):
            segundo = fs.trazado("f", "s")
        self.assertIs(primero, segundo)

    def test_el_enriquecimiento_por_frenada_se_declara(self):
        """Sin el canal declarado, la herramienta no lo usa y lo dice."""

        self.assertTrue(self._trazado(con_freno=True).con_frenada)
        fs.limpiar_cache()
        self.assertFalse(self._trazado(con_freno=False).con_frenada)


class FasesTest(unittest.TestCase):

    def setUp(self):
        fs.limpiar_cache()

    def _curvas(self, freno=(200, 300)):
        senales = [lec.SENAL_NUMERO, lec.SENAL_DISTANCIA, lec.SENAL_LATERAL,
                   lec.SENAL_VELOCIDAD, lec.SENAL_FRENO]
        d = _disponibilidad("curvas_y_fases", senales)
        filas = []
        for n in (1, 2, 3):
            filas += _recorrido(n, _vuelta_con_una_curva(*freno))
        sesion = mock.Mock()
        sesion.comparables = [mock.Mock(numero=n) for n in (1, 2, 3)]
        cursor = CursorFalso(filas)
        with mock.patch.object(fs, "extraer", return_value=sesion), \
                mock.patch.object(fs, "evaluar", return_value=d), \
                mock.patch.object(fs.db, "obtener_conexion",
                                  return_value=ConexionFalsa(cursor)):
            return fs.fases_de_vuelta("f", "s", 1)

    def test_dos_fases_entrada_y_salida(self):
        curva = self._curvas()[0]
        self.assertEqual([f.nombre for f in curva.fases], ["entrada", "salida"])

    def test_las_fases_se_separan_en_el_apice_de_lateral(self):
        curva = self._curvas()[0]
        entrada, salida = curva.fases
        self.assertEqual(entrada.hasta_m, curva.apice_lateral_m)
        self.assertEqual(salida.desde_m, curva.apice_lateral_m)

    def test_se_informan_los_dos_anclajes_de_apice(self):
        """Elegir uno en silencio borraria una magnitud observable."""

        curva = self._curvas()[0]
        self.assertNotEqual(curva.apice_lateral_m, curva.apice_velocidad_m)
        self.assertEqual(curva.separacion_de_apices_m,
                         round(curva.apice_velocidad_m - curva.apice_lateral_m, 1))

    def test_la_entrada_no_empieza_en_el_punto_de_frenada(self):
        """La curva se define por la lateral, que es lo que la hace portable.

        El freno de esta vuelta termina en el metro 300 y la curva empieza ahi
        mismo por la lateral; lo que la prueba fija es que la fase de entrada
        arranca en el borde de la curva y no en el metro 200 donde se freno.
        """

        curva = self._curvas(freno=(200, 300))[0]
        self.assertEqual(curva.fases[0].desde_m, curva.desde_m)
        self.assertGreater(curva.fases[0].desde_m, 200.0)

    def test_el_punto_de_frenada_se_agrega_como_dato_adicional(self):
        curva = self._curvas(freno=(200, 300))[0]
        self.assertEqual(curva.punto_de_frenada_m, 200.0)

    def test_una_frenada_que_termina_lejos_igual_se_encuentra(self):
        """Soltar el freno antes de girar es lo normal, no la excepcion.

        La primera version exigia que el freno siguiera pisado al llegar a la
        curva y encontraba el punto de frenada de una sola de veinte.
        """

        curva = self._curvas(freno=(180, 240))[0]
        self.assertEqual(curva.punto_de_frenada_m, 180.0)


class FrenadasTest(unittest.TestCase):

    def _frenadas(self, guion, continua=True, senal=lec.SENAL_FRENO):
        # El guion se arma con el nombre de senal por defecto; la fuente que la
        # prueba simula puede usar otro, y el modulo pide **el que la
        # disponibilidad declara**. Atarlos aca es lo que hace que la prueba
        # ejercite esa correspondencia en lugar de saltearla.
        for punto in guion:
            if "freno" in punto:
                punto["_senal_freno"] = senal
        d = _disponibilidad("zonas_de_frenada",
                            [lec.SENAL_NUMERO, lec.SENAL_DISTANCIA,
                             lec.SENAL_VELOCIDAD, senal],
                            continua_freno=continua)
        filas = _recorrido(1, guion)
        return _con_base(filas, d, fr.caracterizar, "f", "s", 1, modulo=fr)

    def test_encuentra_la_zona_de_frenada(self):
        f = self._frenadas(_vuelta_con_una_curva(200, 300))
        self.assertEqual(len(f.frenadas), 1)
        self.assertEqual(f.frenadas[0].desde_m, 200.0)

    def test_informa_la_caida_de_velocidad(self):
        f = self._frenadas(_vuelta_con_una_curva(200, 400))
        self.assertEqual(f.frenadas[0].velocidad_entrada_kmh, 250.0)
        self.assertEqual(f.frenadas[0].velocidad_minima_kmh, 120.0)
        self.assertEqual(f.frenadas[0].caida_kmh, 130.0)

    def test_con_escala_informa_la_presion(self):
        f = self._frenadas(_vuelta_con_una_curva(200, 300, presion=0.9))
        self.assertAlmostEqual(f.frenadas[0].presion_maxima, 0.9)
        self.assertTrue(f.freno_continuo)

    def test_con_interruptor_la_presion_queda_sin_informar(self):
        """No se completa con un uno, que pasaria por medicion."""

        f = self._frenadas(_vuelta_con_una_curva(200, 300, presion=1.0),
                           continua=False, senal="brake_applied")
        self.assertIsNone(f.frenadas[0].presion_maxima)
        self.assertFalse(f.freno_continuo)

    def test_con_interruptor_lo_demas_si_se_mide(self):
        """Declararla no disponible descartaria lo que un interruptor si da."""

        f = self._frenadas(_vuelta_con_una_curva(200, 400, presion=1.0),
                           continua=False, senal="brake_pressed")
        self.assertEqual(f.frenadas[0].desde_m, 200.0)
        self.assertEqual(f.frenadas[0].caida_kmh, 130.0)

    def test_el_resumen_avisa_que_no_hay_presion(self):
        f = self._frenadas(_vuelta_con_una_curva(200, 300, presion=1.0),
                           continua=False, senal="brake_applied")
        self.assertIn("interruptor", fr.resumen(f))

    def test_un_alivio_corto_no_parte_la_frenada_en_dos(self):
        """Modulacion, no dos frenadas: cortarla ahi la contaria dos veces."""

        guion = _vuelta_con_una_curva(200, 320)
        for punto in guion:
            if punto["m"] == 260:
                punto["freno"] = 0.0
        f = self._frenadas(guion)
        self.assertEqual(len(f.frenadas), 1)

    def test_dos_frenadas_separadas_son_dos(self):
        guion = _vuelta_con_una_curva(200, 560)
        for punto in guion:
            if 260 <= punto["m"] <= 480:
                punto["freno"] = 0.0
        f = self._frenadas(guion)
        self.assertEqual(len(f.frenadas), 2)

    def test_un_roce_del_pedal_no_es_una_frenada(self):
        f = self._frenadas(_vuelta_con_una_curva(200, 200))
        self.assertEqual(f.frenadas, [])


if __name__ == "__main__":
    unittest.main()
