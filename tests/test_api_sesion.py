# -*- coding: utf-8 -*-
"""Pruebas de las rutas de lectura de una sesion persistida.

CRITERIO. Ninguna prueba necesita la base: la conexion se sustituye. Lo que se
comprueba no es que PostgreSQL sepa agrupar, sino **lo que este modulo decide**:
que consulta arma, como acota, que devuelve cuando falta el dato y que declara
en cada caso. Esa es la parte que puede romperse al editar.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from backend import api_sesion, catalogo_curvas


class ConexionFalsa:
    """Sustituye a `db.obtener_conexion` y recuerda lo que se le pidio."""

    def __init__(self, filas=None):
        self.filas = filas if filas is not None else []
        self.consultas: list[tuple[str, tuple]] = []
        self.cursor_obj = MagicMock()
        self.cursor_obj.execute.side_effect = self._ejecutar
        self.cursor_obj.fetchall.side_effect = lambda: list(self.filas)
        self.cursor_obj.fetchone.side_effect = lambda: (self.filas[0] if self.filas else None)

    def _ejecutar(self, consulta, parametros=None):
        self.consultas.append((consulta, parametros))

    def cursor(self):
        contexto = MagicMock()
        contexto.__enter__ = lambda *_: self.cursor_obj
        contexto.__exit__ = lambda *_: False
        return contexto

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _con(filas=None):
    falsa = ConexionFalsa(filas)
    return falsa, patch("backend.api_sesion.db.obtener_conexion", return_value=falsa)


class DeduccionDeFuenteTests(unittest.TestCase):
    """El identificador ya dice de donde viene: no hay que repetirlo."""

    def test_reconoce_las_tres_fuentes(self) -> None:
        self.assertEqual(api_sesion._fuente_de("f1_25:session:123"), "f1_25_udp_simulation")
        self.assertEqual(api_sesion._fuente_de("can:segmento:sample_30"), "can_real_replay")
        self.assertEqual(api_sesion._fuente_de("9939"), "openf1_historical_replay")


class SeriesPorDistanciaTests(unittest.TestCase):
    """El endpoint que sostiene el tablero."""

    def test_una_fuente_sin_distancia_no_devuelve_un_eje_inventado(self) -> None:
        """OpenF1 no tiene eje espacial defendible: el motivo va en la respuesta."""
        with self.assertRaises(HTTPException) as caso:
            api_sesion.series_por_distancia("9939", senales="speed")
        self.assertEqual(caso.exception.status_code, 422)
        self.assertIn("83 m", caso.exception.detail)

    def test_exige_al_menos_una_senal(self) -> None:
        with self.assertRaises(HTTPException) as caso:
            api_sesion.series_por_distancia("f1_25:session:1", senales="  , ")
        self.assertEqual(caso.exception.status_code, 422)

    def test_acota_la_cantidad_de_senales(self) -> None:
        """Trece senales por cuatro vehiculos serian cincuenta mil puntos."""
        muchas = ",".join("s%d" % i for i in range(13))
        with self.assertRaises(HTTPException) as caso:
            api_sesion.series_por_distancia("f1_25:session:1", senales=muchas)
        self.assertEqual(caso.exception.status_code, 422)

    def test_la_consulta_acota_por_fuente_y_sesion(self) -> None:
        """Sin acotar por columnas de segmentacion, la consulta descomprime todo."""
        falsa, parche = _con([])
        with parche:
            api_sesion.series_por_distancia("f1_25:session:1", senales="speed")
        consulta, parametros = falsa.consultas[0]
        self.assertIn("source_type = %s", consulta)
        self.assertIn("session_id = %s", consulta)
        self.assertIn("f1_25_udp_simulation", parametros)
        self.assertIn("f1_25:session:1", parametros)

    def test_devuelve_las_series_por_vehiculo(self) -> None:
        # (timestamp, vehicle_id, distancia, distancia_sesion, speed)
        filas = [("t1", "car1", 10.0, 7014.0, 100.0),
                 ("t2", "car1", 20.0, 7024.0, 120.0),
                 ("t3", "car2", 10.0, 7012.0, 98.0)]
        falsa, parche = _con(filas)
        with parche:
            r = api_sesion.series_por_distancia("f1_25:session:1", senales="speed")
        self.assertEqual(set(r["vehiculos"]), {"car1", "car2"})
        self.assertEqual(r["vehiculos"]["car1"]["distancia_m"], [10.0, 20.0])
        self.assertEqual(r["vehiculos"]["car1"]["speed"], [100.0, 120.0])
        self.assertEqual(r["vehiculos"]["car1"]["distancia_sesion_m"], [7014.0, 7024.0])
        self.assertEqual(r["vehiculos"]["car1"]["timestamp_utc"], ["t1", "t2"])
        self.assertIn("tiempo", r["ejes_disponibles"])
        self.assertEqual(r["eje"], "distancia recorrida, en metros")

    def test_respeta_el_rango_de_distancia(self) -> None:
        filas = [("t1", "car1", 10.0, 10.0, 100.0),
                 ("t2", "car1", 900.0, 900.0, 120.0)]
        falsa, parche = _con(filas)
        with parche:
            r = api_sesion.series_por_distancia("f1_25:session:1", senales="speed",
                                                desde_m=100.0, hasta_m=1000.0)
        self.assertEqual(r["vehiculos"]["car1"]["distancia_m"], [900.0])

    def test_declara_cuando_submuestrea(self) -> None:
        """Callar el submuestreo haria pasar por completa una serie recortada."""
        filas = [("t%d" % i, "car1", float(i), float(i), float(i)) for i in range(400)]
        falsa, parche = _con(filas)
        with parche:
            r = api_sesion.series_por_distancia("f1_25:session:1", senales="speed", puntos=50)
        self.assertTrue(r["submuestreado"])
        self.assertLessEqual(len(r["vehiculos"]["car1"]["distancia_m"]), 60)


class VueltasTests(unittest.TestCase):
    def test_una_fuente_sin_distancia_lo_dice_y_no_falla(self) -> None:
        r = api_sesion.listar_vueltas("9939")
        self.assertEqual(r["vueltas"], [])
        self.assertIn("no declara distancia", r["motivo"])

    def test_marca_como_incompleta_una_vuelta_que_no_arranca_en_cero(self) -> None:
        """Un tramo no es una vuelta, y ofrecerlo para comparar seria enganoso."""
        from datetime import datetime, timezone
        t0 = datetime(2026, 9, 6, tzinfo=timezone.utc)
        t1 = datetime(2026, 9, 6, 0, 1, 44, tzinfo=timezone.utc)
        # (vuelta, muestras, desde, hasta, inicio, fin, vmin, vmax, invalida)
        filas = [(3, 2000, 5.0, 7000.0, t0, t1, 50.0, 330.0, 0.0),
                 (4, 400, 3500.0, 7000.0, t0, t1, 60.0, 300.0, 0.0)]
        falsa, parche = _con(filas)
        with parche:
            r = api_sesion.listar_vueltas("f1_25:session:1")
        self.assertTrue(r["vueltas"][0]["completa"])
        self.assertFalse(r["vueltas"][1]["completa"])
        self.assertEqual(r["vueltas"][0]["largo_m"], 6995.0)


class TrazadoTests(unittest.TestCase):
    def test_el_bus_no_declara_posicion_y_lo_explica(self) -> None:
        r = api_sesion.trazado("can:segmento:sample_30")
        self.assertEqual(r["puntos"], [])
        self.assertIn("reconstruye por integracion", r["motivo"])

    def test_el_sentido_de_giro_se_calcula_y_no_se_supone(self) -> None:
        """Un cuadrado recorrido en un sentido conocido debe dar ese sentido."""
        # Cuadrado antihorario en el plano matematico.
        filas = [(0.0, 0.0, 1.0, 0.0, 1.0), (10.0, 0.0, 1.0, 10.0, 1.0),
                 (10.0, 10.0, 2.0, 20.0, 1.0), (0.0, 10.0, 3.0, 30.0, 1.0)]
        falsa, parche = _con(filas)
        with parche:
            r = api_sesion.trazado("f1_25:session:1")
        # Es el sentido en el plano de la fuente, no el del circuito: el juego
        # usa coordenadas propias y Spa, que se corre horario, da antihorario.
        self.assertEqual(r["sentido_en_el_plano_crudo"], "antihorario")
        self.assertNotIn("sentido", r)
        self.assertIn("no se deduce de aca", r["metodo"])
        self.assertEqual(r["desnivel_m"], 2.0)

    def test_sin_posicion_persistida_lo_declara(self) -> None:
        falsa, parche = _con([])
        with parche:
            r = api_sesion.trazado("f1_25:session:1")
        self.assertEqual(r["puntos"], [])
        self.assertIn("no tiene posicion persistida", r["motivo"])


class EstadoDelVehiculoTests(unittest.TestCase):
    def test_los_canales_ausentes_se_declaran_en_vez_de_omitirse(self) -> None:
        """Saber que algo no se midio es tan util como el valor de lo que si."""
        falsa, parche = _con([])
        with parche:
            r = api_sesion.estado_del_vehiculo("can:segmento:sample_30")
        self.assertEqual(r["esquinas"], {})
        self.assertTrue(len(r["ausentes"]) > 30)
        self.assertIn("no publica estado de neumaticos", r["motivo_ausencia"])

    def test_arma_las_cuatro_esquinas(self) -> None:
        from datetime import datetime, timezone
        t = datetime(2026, 9, 6, tzinfo=timezone.utc)
        filas = [("tyre_temperature_surface_front_left", 105.0, None, None, "C", t),
                 ("tyre_pressure_front_left", 23.0, None, None, "psi", t),
                 ("floor_damage", 12.0, None, None, "%", t)]
        falsa, parche = _con(filas)
        with parche:
            r = api_sesion.estado_del_vehiculo("f1_25:session:1")
        self.assertEqual(r["esquinas"]["front_left"]["temperatura_superficie_c"], 105.0)
        self.assertEqual(r["esquinas"]["front_left"]["presion_psi"], 23.0)
        self.assertEqual(r["carroceria"]["piso_pct"], 12.0)
        self.assertIsNone(r["motivo_ausencia"])


class ClimaTests(unittest.TestCase):
    def test_traduce_los_codigos_a_texto(self) -> None:
        from datetime import datetime, timezone
        t = datetime(2026, 9, 6, tzinfo=timezone.utc)
        filas = [("air_temperature", 23.4, None, None, "C", t),
                 ("weather_code", 0.0, None, None, "", t),
                 ("fia_flag", 1.0, None, None, "", t)]
        falsa, parche = _con(filas)
        with parche:
            r = api_sesion.clima("f1_25:session:1")
        self.assertEqual(r["clima"]["temperatura_aire_c"], 23.4)
        self.assertEqual(r["clima"]["clima"], "despejado")
        self.assertEqual(r["clima"]["bandera_texto"], "verde")

    def test_sin_clima_explica_por_que(self) -> None:
        falsa, parche = _con([])
        with parche:
            r = api_sesion.clima("9939")
        self.assertEqual(r["clima"], {})
        self.assertIn("contexto de sesion", r["motivo_ausencia"])


class AvisosTests(unittest.TestCase):
    def test_una_fuente_sin_banderas_ni_dano_no_inventa_avisos(self) -> None:
        r = api_sesion.avisos("9939")
        self.assertEqual(r["avisos"], [])
        self.assertIn("no hay con que levantar un aviso", r["motivo"])

    def test_el_piano_no_cuenta_como_salida_de_pista(self) -> None:
        """Se puede rodar sobre un piano sin perder agarre: es la trazada normal."""
        self.assertNotIn(1, api_sesion.SUPERFICIES_FUERA)
        self.assertIn(2, api_sesion.SUPERFICIES_FUERA)

    def test_cada_regla_declara_su_canal_y_su_umbral(self) -> None:
        """Un aviso sin origen ni umbral es una afirmacion que no se puede discutir."""
        for regla in api_sesion.REGLAS_DE_AVISO:
            self.assertTrue(regla["canal"])
            self.assertIsInstance(regla["umbral"], float)
            self.assertIn(regla["nivel"], {"critico", "alerta", "info"})


class CurvasTests(unittest.TestCase):
    def test_devuelve_el_catalogo_declarando_que_es_anotacion(self) -> None:
        r = api_sesion.curvas_del_circuito("spa-francorchamps")
        self.assertEqual(len(r["curvas"]), 15)
        self.assertEqual(r["sentido"], "horario")
        self.assertIn("nombre: catalogo externo", r["curvas"][0]["origen"])
        self.assertIn("Kemmel", r["sin_frenada"])

    def test_un_circuito_sin_catalogo_no_falla(self) -> None:
        r = api_sesion.curvas_del_circuito("monza")
        self.assertEqual(r["curvas"], [])
        self.assertIn("No hay catalogo", r["motivo"])


if __name__ == "__main__":
    unittest.main()


class AliasDeCircuito(unittest.TestCase):
    """El catalogo de curvas se indexa por el nombre propio del circuito; la
    procedencia de las capturas lo nombra corto. Sin alias, la consulta que
    hace el tablero ---con lo que trae la procedencia--- volvia vacia."""

    def test_la_clave_corta_encuentra_el_catalogo(self):
        largo = catalogo_curvas.curvas_de("spa-francorchamps")
        corto = catalogo_curvas.curvas_de("spa")
        self.assertTrue(largo, "el catalogo de Spa deberia existir")
        self.assertEqual(corto, largo)

    def test_no_distingue_mayusculas_ni_espacios(self):
        self.assertTrue(catalogo_curvas.curvas_de("  SPA  "))
        self.assertTrue(catalogo_curvas.curvas_de("Spa Francorchamps"))

    def test_un_circuito_sin_catalogo_sigue_devolviendo_vacio(self):
        self.assertEqual(catalogo_curvas.curvas_de("spielberg"), ())


class UltimosValoresAcotados(unittest.TestCase):
    """Un panel que acompana una reproduccion no puede contestar con el ultimo
    valor de la sesion: una carrera que termina en tormenta mostraria tormenta
    desde la primera vuelta. La consulta se acota al instante que se mira."""

    def _cursor(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        return cursor

    def test_sin_instante_no_agrega_condicion(self):
        cursor = self._cursor()
        api_sesion._ultimos_valores(cursor, "f1_25_udp_simulation", "s", ["speed"])
        consulta, parametros = cursor.execute.call_args[0]
        self.assertNotIn("timestamp <=", consulta)
        self.assertEqual(len(parametros), 3)

    def test_con_instante_acota_por_marca_de_tiempo(self):
        cursor = self._cursor()
        api_sesion._ultimos_valores(cursor, "f1_25_udp_simulation", "s", ["speed"],
                                    "2026-09-05T00:40:00+00:00")
        consulta, parametros = cursor.execute.call_args[0]
        self.assertIn("timestamp <=", consulta)
        self.assertEqual(parametros[-1], "2026-09-05T00:40:00+00:00")

    def test_sin_senales_no_consulta(self):
        cursor = self._cursor()
        self.assertEqual(api_sesion._ultimos_valores(cursor, "f", "s", []), {})
        cursor.execute.assert_not_called()
