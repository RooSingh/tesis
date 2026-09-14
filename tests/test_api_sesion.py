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

from adapters import f1_25 as adaptador_f1_25
from backend import anotador_vivo, api_sesion, catalogo_curvas, f1_udp


class ConexionFalsa:
    """Sustituye a `db.obtener_conexion` y recuerda lo que se le pidio."""

    def __init__(self, filas=None):
        self.filas = filas if filas is not None else []
        self.consultas: list[tuple[str, tuple]] = []
        self.cursor_obj = MagicMock()
        self.cursor_obj.execute.side_effect = self._ejecutar
        self.cursor_obj.fetchall.side_effect = lambda: list(self.filas)
        self.cursor_obj.fetchone.side_effect = lambda: (self.filas[0] if self.filas else None)
        self._lotes = [list(self.filas)] if self.filas else []
        self.cursor_obj.fetchmany.side_effect = (
            lambda _: self._lotes.pop(0) if self._lotes else [])

    def _ejecutar(self, consulta, parametros=None):
        self.consultas.append((consulta, parametros))

    def cursor(self, *_, **__):
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
        self.assertIn("1,3 s", caso.exception.detail)

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


class SeriesPorTiempoTests(unittest.TestCase):
    """La ruta historica de las fuentes que no publican distancia."""

    def test_can_devuelve_segundos_sin_inventar_metros(self) -> None:
        from datetime import datetime, timedelta, timezone

        inicio = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)
        # timestamp, vehicle_id, speed, brake_pressed, unit speed, unit brake
        filas = [
            (inicio, "can:sample_01", 100.0, 0.0, "km/h", "boolean"),
            (inicio + timedelta(seconds=2), "can:sample_01", 110.0, 1.0,
             "km/h", "boolean"),
        ]
        falsa, parche = _con(filas)
        with parche:
            r = api_sesion.series_por_tiempo(
                "can:segmento:sample_01",
                senales="speed,brake_pressed",
                puntos=50,
            )

        serie = r["vehiculos"]["can:sample_01"]
        self.assertEqual(serie["tiempo_s"], [0.0, 2.0])
        self.assertEqual(serie["speed"], [100.0, 110.0])
        self.assertEqual(serie["brake_pressed"], [0.0, 1.0])
        self.assertNotIn("distancia_m", serie)
        self.assertEqual(r["duracion_s"], 2.0)
        self.assertEqual(r["unidades"]["speed"], "km/h")

    def test_ninguna_senal_del_bus_desaparece_al_submuestrear(self) -> None:
        """El defecto que dejaba el tablero en blanco sobre una sesion entera.

        Un bus intercala sus tramas: agrupando por instante exacto, cada fila
        trae **una** señal. Salteando una de cada N, una señal cuyas filas caen
        en un patron que comparte factor con el paso desaparece entera.

        Medido sobre `sample_28`: 6.158 filas, 3.079 con `speed`, todas en los
        indices pares. Pidiendo las trece señales del bus, `speed` volvia con
        cero muestras de tres mil. El grafico de velocidad decia «sin dato en
        esta vuelta» y, como el eje temporal se apoya en esa señal, los otros
        doce se quedaban sin ventana y tampoco dibujaban.
        """

        from datetime import datetime, timedelta, timezone

        inicio = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)
        senales = ["speed", "yaw_rate", "accel_lateral"]
        filas = []
        for i in range(3000):
            valores = [None] * len(senales)
            valores[i % len(senales)] = float(i)
            filas.append((inicio + timedelta(milliseconds=10 * i), "can:rav4:sample_28",
                          *valores, "km/h", "deg/s", "m/s^2"))

        falsa, parche = _con(filas)
        with parche:
            r = api_sesion.series_por_tiempo(
                "can:segmento:sample_28",
                senales=",".join(senales),
                puntos=600,
            )

        serie = r["vehiculos"]["can:rav4:sample_28"]
        self.assertTrue(r["submuestreado"])
        for senal in senales:
            con = sum(1 for x in serie[senal] if x is not None)
            self.assertGreater(
                con, 0,
                "la señal %s volvio con cero muestras de mil: el grafico dice "
                "«sin dato» sobre una sesion completa" % senal)
        # Y no una sobreviviendo a costa de las otras.
        cuantas = [sum(1 for x in serie[s] if x is not None) for s in senales]
        self.assertEqual(min(cuantas), max(cuantas),
                         "unas señales sobrevivieron mas que otras: %s" % cuantas)

    def test_la_muestra_que_vuelve_es_la_que_se_midio(self) -> None:
        """Plegar no es promediar: cada valor sigue siendo una medicion."""

        from datetime import datetime, timedelta, timezone

        inicio = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)
        filas = []
        for i in range(200):
            valores = [float(i) if i % 2 == 0 else None,
                       float(i) if i % 2 == 1 else None]
            filas.append((inicio + timedelta(milliseconds=10 * i), "veh",
                          *valores, "km/h", "deg/s"))
        falsa, parche = _con(filas)
        with parche:
            r = api_sesion.series_por_tiempo(
                "can:segmento:sample_28", senales="speed,yaw_rate", puntos=50)

        serie = r["vehiculos"]["veh"]
        # Paso 4: el primer tramo son las filas 0..3, con `speed` en 0 y 2.
        self.assertEqual(serie["speed"][0], 0.0)
        self.assertEqual(serie["yaw_rate"][0], 1.0)
        self.assertEqual(serie["tiempo_s"][0], 0.0)
        self.assertEqual(serie["speed"][1], 4.0)
        # Los valores son los medidos, no promedios ni interpolaciones.
        for x in serie["speed"]:
            if x is not None:
                self.assertEqual(x % 2, 0.0, "aparecio un valor que nadie midio")

    def test_consulta_booleanos_y_acota_fuente_sesion(self) -> None:
        falsa, parche = _con([])
        with parche:
            api_sesion.series_por_tiempo(
                "can:segmento:sample_01", senales="brake_pressed")
        consulta, parametros = falsa.consultas[-1]
        self.assertIn("value_boolean", consulta)
        self.assertIn("source_type = %s", consulta)
        self.assertIn("session_id = %s", consulta)
        self.assertIn("can_real_replay", parametros)

    def test_el_nombre_de_senal_no_se_interpola_como_identificador_sql(self) -> None:
        falsa, parche = _con([])
        nombre = 'speed"; DROP TABLE telemetry_messages; --'
        with parche:
            api_sesion.series_por_tiempo(
                "can:segmento:sample_01", senales=nombre)
        consulta, parametros = falsa.consultas[-1]
        self.assertNotIn(nombre, consulta)
        self.assertIn(nombre, parametros)

    def test_exige_senales_y_respeta_el_tope_temporal(self) -> None:
        with self.assertRaises(HTTPException) as vacia:
            api_sesion.series_por_tiempo("can:segmento:sample_01", senales=" , ")
        self.assertEqual(vacia.exception.status_code, 422)
        with self.assertRaises(HTTPException) as muchas:
            api_sesion.series_por_tiempo(
                "can:segmento:sample_01",
                senales=",".join("s%d" % i for i in range(21)),
            )
        self.assertEqual(muchas.exception.status_code, 422)


class SinEjeDeDistanciaTests(unittest.TestCase):
    """Cada fuente sin eje espacial explica **su** motivo, no el de otra.

    El mensaje era uno solo, escrito para OpenF1 ---los huecos de 83 m entre
    muestras--- y se devolvia igual para cualquier fuente sin distancia. Quien
    abria una captura del bus leia una explicacion sobre una fuente que no
    estaba usando, y ademas equivocada: en el bus el problema no es que el
    muestreo sea pobre, es que la senal no existe.
    """

    def test_el_bus_explica_que_no_publica_odometro(self) -> None:
        with self.assertRaises(HTTPException) as caso:
            api_sesion.series_por_distancia("can:segmento:sample_01", senales="speed")
        detalle = caso.exception.detail
        self.assertEqual(caso.exception.status_code, 422)
        self.assertIn("odómetro", detalle)
        self.assertIn("can_real_replay", detalle)
        self.assertNotIn("OpenF1", detalle)
        self.assertNotIn("1,3 s", detalle)

    def test_la_fuente_deportiva_sigue_explicando_sus_huecos(self) -> None:
        with self.assertRaises(HTTPException) as caso:
            api_sesion.series_por_distancia("9939", senales="speed")
        detalle = caso.exception.detail
        self.assertIn("1,3 s", detalle)
        self.assertNotIn("odómetro", detalle)

    def test_se_declara_que_no_es_un_fallo_reintentable(self) -> None:
        """Mover el cabezal mil veces no hace que el bus declare distancia."""
        for sesion in ("can:segmento:sample_01", "9939"):
            with self.assertRaises(HTTPException) as caso:
                api_sesion.series_por_distancia(sesion, senales="speed")
            self.assertIn("no es un fallo que se pueda reintentar",
                          caso.exception.detail.lower())

    def test_las_vueltas_dan_el_mismo_motivo_que_las_series(self) -> None:
        """Tres rutas contestaban lo mismo con tres textos distintos."""
        r = api_sesion.listar_vueltas("can:segmento:sample_01")
        self.assertEqual(r["vueltas"], [])
        self.assertIn("odómetro", r["motivo"])

    def test_las_posiciones_tambien(self) -> None:
        with self.assertRaises(HTTPException) as caso:
            api_sesion.posiciones_en_pista("can:segmento:sample_01", vuelta=1)
        self.assertIn("odómetro", caso.exception.detail)

    def test_una_fuente_sin_motivo_escrito_no_inventa_uno(self) -> None:
        self.assertIn("no declara distancia recorrida",
                      api_sesion._sin_distancia("una_fuente_nueva"))


class UnidadesDeLaSerieTests(unittest.TestCase):
    """La respuesta declara en que unidad viene cada senal.

    EL DEFECTO QUE ESTO CIERRA. `delta_to_race_leader` se compone en
    milisegundos y el tablero lo imprimia crudo bajo un rotulo que decia
    segundos. El navegador no tenia como saberlo: la respuesta no declaraba la
    unidad de nada, y una lista de nombres escrita a mano en el tablero habria
    roto `penalty_time` y `safety_car_delta`, que viajan en la misma consulta y
    **ya estan en segundos**.
    """

    def test_declara_la_unidad_de_cada_senal_pedida(self) -> None:
        # (timestamp, vehicle_id, distancia, distancia_sesion, gap, castigo,
        #  unidad del gap, unidad del castigo)
        filas = [("t1", "car1", 10.0, 10.0, 2937.0, 5.0, "ms", "s"),
                 ("t2", "car1", 20.0, 20.0, 2986.0, 5.0, "ms", "s")]
        falsa, parche = _con(filas)
        with parche:
            r = api_sesion.series_por_distancia(
                "f1_25:session:1", senales="delta_to_race_leader,penalty_time")
        self.assertEqual(r["unidades"],
                         {"delta_to_race_leader": "ms", "penalty_time": "s"})

    def test_los_valores_viajan_en_su_unidad_de_origen(self) -> None:
        """Convertir aca cambiaria lo que la base guarda de lo que dice la API."""
        filas = [("t1", "car1", 10.0, 10.0, 2937.0, "ms")]
        falsa, parche = _con(filas)
        with parche:
            r = api_sesion.series_por_distancia(
                "f1_25:session:1", senales="delta_to_race_leader")
        self.assertEqual(r["vehiculos"]["car1"]["delta_to_race_leader"], [2937.0])
        self.assertEqual(r["unidades"]["delta_to_race_leader"], "ms")

    def test_la_unidad_sale_de_la_primera_fila_que_la_declare(self) -> None:
        """Una fila sin esa senal la deja nula; no es que la senal no tenga unidad."""
        filas = [("t1", "car1", 10.0, 10.0, None, None),
                 ("t2", "car1", 20.0, 20.0, 2937.0, "ms")]
        falsa, parche = _con(filas)
        with parche:
            r = api_sesion.series_por_distancia(
                "f1_25:session:1", senales="delta_to_race_leader")
        self.assertEqual(r["unidades"]["delta_to_race_leader"], "ms")

    def test_una_senal_sin_una_sola_fila_no_declara_unidad_inventada(self) -> None:
        filas = [("t1", "car1", 10.0, 10.0, 100.0, None, "km/h", None)]
        falsa, parche = _con(filas)
        with parche:
            r = api_sesion.series_por_distancia(
                "f1_25:session:1", senales="speed,current_lap_time")
        self.assertEqual(r["unidades"], {"speed": "km/h"})
        self.assertNotIn("current_lap_time", r["unidades"])

    def test_sin_filas_la_respuesta_igual_trae_el_mapa_de_unidades(self) -> None:
        """Quien lo lee no tiene que distinguir «vacio» de «no vino el campo»."""
        falsa, parche = _con([])
        with parche:
            r = api_sesion.series_por_distancia("f1_25:session:1", senales="speed")
        self.assertEqual(r["unidades"], {})

    def test_la_unidad_se_pide_sobre_las_mismas_filas_y_no_en_otra_consulta(self) -> None:
        """Una pasada mas sobre cinco millones de filas para leer un texto fijo."""
        filas = [("t1", "car1", 10.0, 10.0, 2937.0, "ms")]
        falsa, parche = _con(filas)
        with parche:
            api_sesion.series_por_distancia("f1_25:session:1",
                                            senales="delta_to_race_leader")
        principales = [c for c, _ in falsa.consultas if "FILTER" in c]
        self.assertEqual(len(principales), 1)
        self.assertIn("max(unit) FILTER", principales[0])


class ParrillaDeLaSesionTests(unittest.TestCase):
    """Quien es cada vehiculo, y de cuantos hay telemetria: dos cosas.

    `AUTOS.length <= 1` en el tablero confundia «un solo vehiculo con telemetria
    guardada» con «esta sesion no tiene participantes». En la carrera de Spa la
    parrilla declara veinte y la base tiene uno.
    """

    PARRILLA = {
        "vehiculos": [
            {"indice": 0, "nombre": "PIASTRI", "numero": 81,
             "equipo": "McLaren", "es_ia": True},
            {"indice": 19, "nombre": "NORRIS", "numero": 4,
             "equipo": "McLaren", "es_ia": False},
        ],
        "vehiculos_en_carrera": 20,
        "origen": "metadato de captura, derivado del paquete de participantes",
    }

    def _armar(self, session_id="f1_25:session:1", con_telemetria=(), parrilla=None,
               candidatas=None, desde=None, hasta=None, shas=()):
        cands = candidatas if candidatas is not None else ([parrilla] if parrilla else [])
        with patch.object(api_sesion.procedencia_sesiones, "candidatas_de_parrilla",
                          return_value=cands):
            return api_sesion._parrilla_de_la_adquisicion(
                session_id, api_sesion._fuente_de(session_id), desde, hasta,
                list(shas), set(con_telemetria))

    def test_une_cada_participante_con_su_clave_tecnica(self) -> None:
        r = self._armar(con_telemetria={"f1_25:session:1:car:19"},
                        parrilla=self.PARRILLA)
        self.assertTrue(r["disponible"])
        norris = [v for v in r["vehiculos"] if v["indice"] == 19][0]
        self.assertEqual(norris["vehicle_id"], "f1_25:session:1:car:19")
        self.assertEqual(norris["nombre"], "NORRIS")
        self.assertEqual(norris["numero"], 4)
        self.assertEqual(norris["equipo"], "McLaren")
        self.assertTrue(norris["con_telemetria"])

    def test_conocer_el_nombre_no_es_tener_las_senales(self) -> None:
        r = self._armar(con_telemetria={"f1_25:session:1:car:19"},
                        parrilla=self.PARRILLA)
        piastri = [v for v in r["vehiculos"] if v["indice"] == 0][0]
        self.assertEqual(piastri["nombre"], "PIASTRI")
        self.assertFalse(piastri["con_telemetria"])
        self.assertEqual(r["con_telemetria"], 1)
        self.assertEqual(len(r["vehiculos"]), 2)

    def test_la_cobertura_es_de_la_base_y_no_de_la_parrilla(self) -> None:
        r = self._armar(con_telemetria={"f1_25:session:1:car:19",
                                        "f1_25:session:1:car:5"},
                        parrilla=self.PARRILLA)
        self.assertEqual(r["con_telemetria"], 2,
                         "se conto lo que la parrilla nombra y no lo que hay guardado")

    def test_sin_metadato_lo_declara_y_no_inventa_nombres(self) -> None:
        r = self._armar(con_telemetria={"f1_25:session:1:car:19"}, parrilla=None)
        self.assertFalse(r["disponible"])
        self.assertNotIn("vehiculos", r)
        self.assertIn("motivo", r)
        self.assertEqual(r["con_telemetria"], 1)

    def test_una_fuente_que_no_declara_participantes_lo_dice(self) -> None:
        r = self._armar(session_id="can:segmento:sample_30",
                        con_telemetria={"can:vehicle:rav4"}, parrilla=self.PARRILLA)
        self.assertFalse(r["disponible"])
        self.assertIn("simulacion", r["motivo"])

    def test_la_forma_de_la_clave_es_la_que_acuna_el_adaptador(self) -> None:
        """`adapters/f1_25.py` compone `<session_id>:car:<indice>`.

        Escrita dos veces, un cambio en el adaptador dejaria la union rota sin
        que nada lo dijera; esta prueba la ata al formato que este modulo declara.
        """
        self.assertEqual(api_sesion.FORMA_DEL_VEHICULO % ("f1_25:session:7", 19),
                         "f1_25:session:7:car:19")

    def test_dos_capturas_con_gente_distinta_no_nombran_a_nadie(self) -> None:
        """Antes ganaba la mas larga, que no es una prueba de pertenencia."""
        otra = {"vehiculos": [{"indice": 19, "nombre": "PIASTRI", "numero": 81,
                               "equipo": "McLaren", "es_ia": False}],
                "origen": "x", "captura": {"sha256": "bbb"}}
        propia = dict(self.PARRILLA, captura={"sha256": "aaa"})
        r = self._armar(con_telemetria={"f1_25:session:1:car:19"},
                        candidatas=[propia, otra])
        self.assertFalse(r["disponible"])
        self.assertTrue(r["ambigua"])
        self.assertNotIn("vehiculos", r)
        self.assertIn("no permiten decir", r["motivo"])

    def test_la_huella_del_archivo_desambigua(self) -> None:
        otra = {"vehiculos": [{"indice": 19, "nombre": "PIASTRI", "numero": 81,
                               "equipo": "McLaren", "es_ia": False}],
                "origen": "x", "captura": {"sha256": "bbb"}}
        propia = dict(self.PARRILLA, captura={"sha256": "aaa"})
        r = self._armar(con_telemetria={"f1_25:session:1:car:19"},
                        candidatas=[propia, otra], shas=["aaa"])
        self.assertTrue(r["disponible"])
        self.assertEqual([v["nombre"] for v in r["vehiculos"] if v["indice"] == 19],
                         ["NORRIS"])

    def test_dos_capturas_que_declaran_lo_mismo_no_son_ambiguas(self) -> None:
        r = self._armar(con_telemetria={"f1_25:session:1:car:19"},
                        candidatas=[self.PARRILLA, dict(self.PARRILLA)])
        self.assertTrue(r["disponible"])

    def test_no_se_publica_la_ruta_ni_el_sidecar_entero(self) -> None:
        propia = dict(self.PARRILLA,
                      captura={"sha256": "aaa", "archivo": "spa.f1raw",
                               "inicio_utc": "2026-09-01T12:00:00+00:00",
                               "duracion_s": 10.0})
        r = self._armar(con_telemetria=set(), parrilla=propia)
        self.assertEqual(r["captura"], "spa.f1raw")
        self.assertNotIn("sha256", str(r))
        self.assertNotIn("/", str(r["captura"]))

    def test_se_busca_por_sesion_y_no_por_indice_suelto(self) -> None:
        r = self._armar(session_id="f1_25:session:2",
                        con_telemetria={"f1_25:session:2:car:19"},
                        parrilla=self.PARRILLA)
        norris = [v for v in r["vehiculos"] if v["indice"] == 19][0]
        self.assertEqual(norris["vehicle_id"], "f1_25:session:2:car:19")
        self.assertTrue(norris["con_telemetria"])


class VueltasTests(unittest.TestCase):
    def test_una_fuente_sin_distancia_lo_dice_y_no_falla(self) -> None:
        r = api_sesion.listar_vueltas("9939")
        self.assertEqual(r["vueltas"], [])
        self.assertIn("no tiene eje de distancia", r["motivo"])
        self.assertIn("1,3 s", r["motivo"])

    def test_marca_como_incompleta_una_vuelta_que_no_arranca_en_cero(self) -> None:
        """Un tramo no es una vuelta, y ofrecerlo para comparar seria enganoso."""
        from datetime import datetime, timezone
        t0 = datetime(2026, 9, 6, tzinfo=timezone.utc)
        t1 = datetime(2026, 9, 6, 0, 1, 44, tzinfo=timezone.utc)
        # (vuelta, muestras, desde, hasta, inicio, fin, vmin, vmax, invalida,
        #  duracion efectiva, hueco mayor)
        filas = [(3, 2000, 5.0, 7000.0, t0, t1, 50.0, 330.0, 0.0, 104.0, 0.1),
                 (4, 400, 3500.0, 7000.0, t0, t1, 60.0, 300.0, 0.0, 104.0, 0.1)]
        falsa, parche = _con(filas)
        with parche:
            r = api_sesion.listar_vueltas("f1_25:session:1")
        self.assertTrue(r["vueltas"][0]["completa"])
        self.assertFalse(r["vueltas"][1]["completa"])
        self.assertEqual(r["vueltas"][0]["largo_m"], 6995.0)

    def test_un_fragmento_que_pasa_el_metro_mil_no_es_una_vuelta(self) -> None:
        """El caso medido: la captura se corto 20 s despues de cruzar la meta.

        `f1_25:session:3282644824454978680`, Spielberg, dos pilotos en pantalla
        dividida. La captura empezo 124 m despues de la largada, de modo que la
        vuelta 1 cubre del metro 123,9 al 4.323,0 y la 2 del 1,0 al 1.195,9.

        Con el piso fijo de mil metros la **segunda** pasaba por completa y la
        primera no, y el tablero ---que le pide el trazado a la primera completa
        que encuentra--- dibujaba el contorno del circuito con un fragmento de
        1,2 km sobre una pista de 4,3 km. Ninguna de las dos es una vuelta
        entera: declararlo deja que el trazado elija por cuerda de cierre, que
        es lo que `_vuelta_que_mejor_dibuja` sabe hacer.
        """
        from datetime import datetime, timezone
        t0 = datetime(2026, 9, 11, 23, 53, 53, tzinfo=timezone.utc)
        t1 = datetime(2026, 9, 11, 23, 55, 29, tzinfo=timezone.utc)
        t2 = datetime(2026, 9, 11, 23, 55, 49, tzinfo=timezone.utc)
        filas = [(1, 1924, 123.9, 4323.0, t0, t1, 0.0, 298.0, 0.0, 96.1, 0.067),
                 (2, 412, 1.0, 1195.9, t1, t2, 75.0, 308.0, 0.0, 20.5, 0.067)]
        falsa, parche = _con(filas)
        with parche:
            r = api_sesion.listar_vueltas("f1_25:session:3282644824454978680")
        self.assertFalse(r["vueltas"][0]["completa"],
                         "arranca en el metro 124: le falta el comienzo")
        self.assertFalse(r["vueltas"][1]["completa"],
                         "1.194,9 m contra los 4.199,1 de la vuelta mas larga: "
                         "es un fragmento, y se dibujaba como si fuera el circuito")


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

    def test_dice_de_cuando_es_el_clima_que_devuelve(self) -> None:
        """La consulta trae el instante de cada muestra y esto lo tiraba.

        `_ultimos_valores` devuelve `{valor, unidad, instante}` por señal, y este
        punto de acceso se quedaba solo con el valor. Un clima sin su instante no
        se puede situar: en una carrera que empieza seca y termina en tormenta,
        «lluvia ligera» sin decir de cuando no dice nada sobre la vuelta que se
        esta mirando.
        """
        from datetime import datetime, timezone
        t = datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc)
        filas = [("air_temperature", 23.4, None, None, "C", t),
                 ("weather_code", 0.0, None, None, "", t)]
        falsa, parche = _con(filas)
        with parche:
            r = api_sesion.clima("f1_25:session:1")
        self.assertEqual(r["medido_utc"], t.isoformat())
        self.assertEqual(r["instantes"]["temperatura_aire_c"], t.isoformat())

    def test_con_muestras_de_distinto_momento_declara_la_mas_nueva(self) -> None:
        """Y conserva la de cada una, porque no todas tienen por que coincidir.

        El panel dice una sola fecha ---las magnitudes del clima suelen venir de
        la misma muestra--- pero «suelen» no es «siempre», y quedarse solo con la
        mas nueva haria pasar por reciente a una bandera de hace media hora.
        """
        from datetime import datetime, timedelta, timezone
        t = datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc)
        viejo = t - timedelta(minutes=30)
        filas = [("air_temperature", 23.4, None, None, "C", t),
                 ("fia_flag", 1.0, None, None, "", viejo)]
        falsa, parche = _con(filas)
        with parche:
            r = api_sesion.clima("f1_25:session:1")
        self.assertEqual(r["medido_utc"], t.isoformat(),
                         "no declara la muestra mas nueva")
        self.assertEqual(r["instantes"]["bandera"], viejo.isoformat(),
                         "se perdio de cuando es cada magnitud")

    def test_sin_clima_no_se_inventa_un_instante(self) -> None:
        falsa, parche = _con([])
        with parche:
            r = api_sesion.clima("9939")
        self.assertIsNone(r["medido_utc"])
        self.assertEqual(r["instantes"], {})


class SinVueltasPeroConAlguienConduciendoTests(unittest.TestCase):
    """`/vueltas` es donde se declara el vehiculo propio, y es autoritativa.

    El tablero la trata asi y ninguna otra la pisa. Devolverla sin vehiculo
    dejaba a las fuentes sin metro medido sin nadie elegido en el momento en que
    se pide el trazado, que es enseguida. Con un vehiculo capturado no se
    notaba; con los tres pilotos de una sesion de OpenF1, el trazado se pedia de
    nadie y salia la sesion entera superpuesta.
    """

    def test_declara_el_mas_muestreado(self) -> None:
        falsa, parche = _con([("openf1:session:9947:driver:1",)])
        with parche:
            r = api_sesion.listar_vueltas("openf1:session:9947")
        self.assertEqual(r["vehiculo"], "openf1:session:9947:driver:1")
        self.assertEqual(r["vueltas"], [])
        # La del vehiculo, no la ultima: despues va la de las vueltas.
        deVehiculo = [c for c, _ in falsa.consultas if "GROUP BY vehicle_id" in c]
        self.assertTrue(deVehiculo, "no se consulto quien conduce")
        self.assertIn("count(*) DESC, vehicle_id", deVehiculo[0],
                      "el desempate por identificador es lo que hace que dos "
                      "llamadas seguidas contesten lo mismo")

    def test_sigue_explicando_por_que_no_hay_vueltas(self) -> None:
        falsa, parche = _con([("openf1:session:9947:driver:1",)])
        with parche:
            r = api_sesion.listar_vueltas("openf1:session:9947")
        self.assertIn("no hay vueltas que delimitar", r["motivo"])

    def test_una_base_caida_no_se_lleva_puesta_la_explicacion(self) -> None:
        """El motivo sale de una tabla escrita, no de una medicion.

        Esta rama contestaba sin tocar la base. Convertir la consulta en
        obligatoria haria que una base caida deje de explicar por que no hay
        vueltas, que es lo unico que esta respuesta tiene para dar.
        """

        with patch("backend.api_sesion.db.obtener_conexion",
                   side_effect=RuntimeError("sin base")):
            r = api_sesion.listar_vueltas("openf1:session:9947")
        self.assertIsNone(r["vehiculo"])
        self.assertIn("no hay vueltas que delimitar", r["motivo"])


class LasVueltasDeUnaFuenteSinMetroTests(unittest.TestCase):
    """No hay distancia, pero hay vueltas: el contexto las trae por reloj."""

    @staticmethod
    def _filas():
        from datetime import datetime, timezone
        t0 = datetime(2025, 7, 6, 14, 3, 49, 615000, tzinfo=timezone.utc)
        return [(1, t0, 106.134)]

    def test_las_declara_con_sus_dos_instantes(self) -> None:
        falsa, _ = _con(self._filas())
        v = api_sesion._vueltas_del_contexto(
            falsa.cursor_obj, "openf1:session:9947",
            "openf1:session:9947:driver:1")
        self.assertEqual(v[0]["numero"], 1)
        self.assertEqual(v[0]["duracion_s"], 106.134)
        self.assertEqual(v[0]["desde_utc"], "2025-07-06T14:03:49.615000+00:00")
        self.assertEqual(v[0]["hasta_utc"], "2025-07-06T14:05:35.749000+00:00",
                         "el final sale del comienzo mas la duracion declarada")

    def test_la_duracion_es_la_declarada_y_no_se_recalcula(self) -> None:
        """Es la que midio la fuente; deducirla de las muestras da otra."""
        falsa, _ = _con(self._filas())
        v = api_sesion._vueltas_del_contexto(
            falsa.cursor_obj, "openf1:session:9947",
            "openf1:session:9947:driver:1")
        self.assertEqual(v[0]["duracion_s"], 106.134)

    def test_sin_piloto_o_sin_clave_no_se_consulta_nada(self) -> None:
        falsa, _ = _con([])
        for sesion, veh in [("openf1:session:9947", None),
                            ("openf1:session:9947", "openf1:session:9947"),
                            ("can:segmento:sample_28", "can:rav4:sample_28")]:
            self.assertEqual(
                api_sesion._vueltas_del_contexto(falsa.cursor_obj, sesion, veh), [])
        self.assertEqual(falsa.consultas, [],
                         "se consulto el contexto sin saber de quien")

    def test_la_consulta_pide_solo_las_que_declaran_comienzo_y_duracion(self) -> None:
        """Delimitar lo que no se sabe donde empieza seria inventarlo."""
        falsa, _ = _con(self._filas())
        api_sesion._vueltas_del_contexto(
            falsa.cursor_obj, "openf1:session:9947",
            "openf1:session:9947:driver:1")
        consulta, _ = falsa.consultas[-1]
        self.assertIn("date_start IS NOT NULL", consulta)
        self.assertIn("lap_duration_seconds IS NOT NULL", consulta)


class ElPuntoDeAccesoDevuelveLasVueltasDelContextoTests(unittest.TestCase):
    """De punta a punta: que `/vueltas` las declare, no solo que sepa buscarlas."""

    @staticmethod
    def _con_dos_respuestas():
        from datetime import datetime, timezone
        t0 = datetime(2025, 7, 6, 14, 3, 49, 615000, tzinfo=timezone.utc)
        vehiculo = [("openf1:session:9947:driver:1",)]
        vueltas = [(1, t0, 106.134), (2, t0, 91.2)]

        falsa = ConexionFalsa(vehiculo)
        original = falsa._ejecutar

        def _ejecutar(consulta, parametros=None):
            original(consulta, parametros)
            falsa.filas = vueltas if "racing_laps" in consulta else vehiculo

        falsa.cursor_obj.execute.side_effect = _ejecutar
        return falsa, patch("backend.api_sesion.db.obtener_conexion", return_value=falsa)

    def test_las_devuelve_y_dice_de_donde_salen(self) -> None:
        falsa, parche = self._con_dos_respuestas()
        with parche:
            r = api_sesion.listar_vueltas("openf1:session:9947")
        self.assertEqual(len(r["vueltas"]), 2,
                         "el punto de acceso sabe buscarlas y no las devuelve")
        self.assertEqual(r["vueltas"][0]["numero"], 1)
        self.assertIn("contexto", r.get("medidas_por", ""),
                      "no se declara que no salen de la telemetria")
        self.assertNotIn("motivo", r,
                         "hay vueltas y sigue explicando por que no las hay")

    def test_sin_vueltas_en_el_contexto_explica_por_que(self) -> None:
        """Una fuente sin metro medido y sin contexto sigue diciendo lo suyo."""
        falsa, parche = _con([("can:rav4:sample_28",)])
        with parche:
            r = api_sesion.listar_vueltas("can:segmento:sample_28")
        self.assertEqual(r["vueltas"], [])
        self.assertIn("no hay vueltas que delimitar", r["motivo"])


class SeriesPorTiempoAcotadasTests(unittest.TestCase):
    """Pedir un tramo y no la sesion entera.

    Sin acotar, mil doscientos puntos sobre una carrera de dos horas y media son
    una muestra cada 7,8 segundos: una ventana de veinte segundos se dibuja con
    dos o tres puntos. La fuente publica a 3,7 Hz, asi que se tiraba el 96 % de
    lo medido.
    """

    def test_el_tramo_pedido_entra_en_la_consulta(self) -> None:
        falsa, parche = _con([])
        with parche:
            api_sesion.series_por_tiempo(
                "openf1:session:9947", senales="speed",
                desde="2025-07-06T14:03:49+00:00",
                hasta="2025-07-06T14:05:35+00:00")
        consulta, parametros = falsa.consultas[-1]
        self.assertIn("timestamp >= %s", consulta)
        self.assertIn("timestamp <= %s", consulta)
        self.assertIn("2025-07-06T14:03:49+00:00", [str(x) for x in parametros])

    def test_sin_tramo_sigue_devolviendo_la_sesion_entera(self) -> None:
        """El camino de siempre no puede cambiar: CAN lo usa asi."""
        falsa, parche = _con([])
        with parche:
            api_sesion.series_por_tiempo("can:segmento:sample_28", senales="speed")
        consulta, _ = falsa.consultas[-1]
        self.assertNotIn("timestamp >= %s", consulta)


class LosExtremosDeLaSesionLosSabeElCatalogoTests(unittest.TestCase):
    """Preguntarle a la tabla de mediciones cuando empieza una sesion la recorre.

    `min(timestamp), max(timestamp)` acotado por `session_id` no acota nada: la
    hipertabla esta particionada por `timestamp`, de modo que sin un limite en
    esa dimension hay que mirar todos los trozos. Medido sobre
    `openf1:session:9947` ---932.625 filas, dos horas y media--- esa sola
    consulta tardaba **26,3 s**, mientras las que de verdad buscan los valores
    tardan treinta milisegundos. El navegador corta a los treinta segundos, asi
    que la sesion no terminaba de abrirse y el clima quedaba en «la consulta no
    contesto».

    El catalogo ya tiene esos dos extremos escritos. Esta prueba fija que se le
    pregunten a el.
    """

    @staticmethod
    def _consultas(falsa) -> str:
        return "\n".join(c for c, _ in falsa.consultas)

    def test_no_le_pide_los_extremos_a_la_tabla_de_mediciones(self) -> None:
        from datetime import datetime, timezone
        t = datetime(2026, 9, 6, tzinfo=timezone.utc)
        falsa, parche = _con([("air_temperature", 23.4, None, None, "C", t)])
        with parche:
            api_sesion.clima("openf1:session:9947")
        consultas = self._consultas(falsa)
        self.assertIn("sesiones_catalogo", consultas,
                      "no se consulto el catalogo por los extremos de la sesion")
        self.assertNotIn(
            "min(timestamp), max(timestamp) FROM telemetry_messages", consultas,
            "se le pidieron los extremos a la tabla de mediciones: eso recorre "
            "la particion entera de la sesion")

    def test_con_alcance_elegido_si_acota_por_tiempo(self) -> None:
        """Los extremos del catalogo son los de la sesion, no los de un alcance.

        Con una adquisicion elegida hay que medirlos, pero entonces la consulta
        lleva un limite en la dimension de particion y es barata.
        """

        from datetime import datetime, timezone
        t = datetime(2026, 9, 6, tzinfo=timezone.utc)
        falsa, parche = _con([("air_temperature", 23.4, None, None, "C", t)])
        with parche:
            api_sesion._ultimos_valores(
                falsa.cursor_obj, "f1_25_udp_simulation", "f1_25:session:1",
                ["air_temperature"], None,
                ventana_alcance=(t.isoformat(), t.isoformat()), vehiculo=None)
        # No alcanza con que «timestamp BETWEEN» aparezca en alguna consulta:
        # aparece en las que buscan valores. Tiene que estar **en la que mide
        # los extremos**, que es la que sin acotar recorreria la particion.
        extremos = [c for c, _ in falsa.consultas
                    if "min(timestamp), max(timestamp)" in c]
        self.assertTrue(extremos, "no se midieron los extremos del alcance")
        self.assertIn("timestamp BETWEEN", extremos[0],
                      "la consulta de extremos no acota por tiempo: sin un "
                      "limite en la dimension de particion recorre todo")


class SinNumeroDeVueltaElRelojLaDiceTests(unittest.TestCase):
    """Un trazado sin vueltas es la sesion entera superpuesta.

    El trazado agrupa por `lap_number`, que viaja en la telemetria del
    simulador. OpenF1 no lo publica: sus nueve señales describen el coche y
    ninguna dice en que vuelta va. Sin numero, **todas las filas caen en un solo
    grupo** y el dibujo sale con las cincuenta y dos vueltas de la carrera
    superpuestas, mas la de formacion y el regreso a boxes. Se vio en pantalla:
    un ovillo donde tenia que haber un circuito.

    Las vueltas existen igual, como ventanas de tiempo, en el contexto
    deportivo.
    """

    @staticmethod
    def _vueltas():
        from datetime import datetime, timedelta, timezone
        t0 = datetime(2025, 7, 6, 14, 0, tzinfo=timezone.utc)
        return [(1, t0, t0 + timedelta(seconds=90)),
                (2, t0 + timedelta(seconds=90), t0 + timedelta(seconds=180))]

    @staticmethod
    def _fila(segundos, vuelta=None):
        from datetime import datetime, timedelta, timezone
        t0 = datetime(2025, 7, 6, 14, 0, tzinfo=timezone.utc)
        return (1.0, 2.0, None, None, vuelta, t0 + timedelta(seconds=segundos))

    def test_cada_fila_recibe_la_vuelta_de_su_instante(self) -> None:
        filas = [self._fila(10), self._fila(100), self._fila(170)]
        salida = api_sesion._numerar_por_reloj(filas, self._vueltas())
        self.assertEqual([f[4] for f in salida], [1, 2, 2])

    def test_lo_que_cae_fuera_de_toda_vuelta_no_se_numera(self) -> None:
        """La formacion y el regreso a boxes no son parte del circuito."""

        filas = [self._fila(-30), self._fila(10), self._fila(400)]
        salida = api_sesion._numerar_por_reloj(filas, self._vueltas())
        self.assertEqual([f[4] for f in salida], [None, 1, None])

    def test_sin_vueltas_declaradas_no_se_inventa_ninguna(self) -> None:
        filas = [self._fila(10), self._fila(100)]
        self.assertEqual(api_sesion._numerar_por_reloj(filas, []), filas)

    def test_no_pisa_un_numero_que_la_telemetria_ya_traia(self) -> None:
        """`_numerar_por_reloj` solo se llama cuando no hay ninguno, pero si
        alguna vez se lo llamara con datos del simulador, no puede cambiarlos."""

        filas = [self._fila(10, vuelta=7)]
        salida = api_sesion._numerar_por_reloj(filas, [])
        self.assertEqual(salida[0][4], 7)

    def test_la_ventana_de_una_vuelta_sale_del_contexto_deportivo(self) -> None:
        from datetime import datetime, timezone
        t0 = datetime(2025, 7, 6, 14, 0, tzinfo=timezone.utc)
        falsa, _ = _con([(1, t0, t0)])
        vueltas = api_sesion._vueltas_por_reloj(
            falsa.cursor_obj, "openf1:session:9947",
            "openf1:session:9947:driver:1")
        self.assertEqual(vueltas[0][0], 1)
        consulta, parametros = falsa.consultas[-1]
        self.assertIn("racing_laps", consulta)
        self.assertIn("driver_number = %s", consulta,
                      "la consulta no acota por piloto: traeria las vueltas de "
                      "los veinte y el lazo se cortaria por donde no va")
        self.assertEqual(parametros, (9947, 1),
                         "las vueltas se piden de la sesion y del piloto que se "
                         "esta dibujando: dos pilotos cruzan la meta en "
                         "instantes distintos")

    def test_sin_piloto_en_el_identificador_no_se_consulta_nada(self) -> None:
        falsa, _ = _con([])
        self.assertEqual(
            api_sesion._vueltas_por_reloj(falsa.cursor_obj, "openf1:session:9947", None), [])
        self.assertEqual(
            api_sesion._vueltas_por_reloj(falsa.cursor_obj, "can:segmento:sample_28",
                                          "can:rav4:sample_28"), [])
        self.assertEqual(falsa.consultas, [],
                         "se consulto el contexto sin saber de quien")


class UnaVueltaSonLosMetrosDeLaVuelta(unittest.TestCase):
    """Lo de antes de la linea no es parte de la vuelta, y se dibujaba igual.

    QUE SE VIO. En la contrarreloj de Shanghai el trazado salia con una cuña
    angosta y una chicana que el circuito no tiene, y el lazo no cerraba
    ---107,3 m---. La firma estaba en los sectores: el punto de acceso declaraba
    **CINCO**, en -5.342,3 / -916,4 / 1,2 / 1.419,4 / 2.986,2 m. La Formula 1
    tiene tres.

    POR QUE. El protocolo publica `lap_distance` negativa antes de cruzar la
    linea ---`backend/f1_udp.py:462`--- y esas muestras entraban en la vuelta.
    El dibujo abarcaba de -5.342 m a 5.438 m: casi once kilometros, dos
    trayectorias distintas superpuestas. `sector_index` recorre sus tres
    valores en la aproximacion y otra vez en la vuelta, y de ahi los cinco.

    ES LA MISMA REGLA QUE YA ESTA ESCRITA EN EL TABLERO, en `fraccionDelMetro`:
    un metro negativo no es el metro cero ni es un dato faltante. La fuente esta
    diciendo algo cierto ---el coche esta antes de la linea--- y lo que no puede
    es ubicarlo **dentro de la vuelta**, porque la vuelta no empezo.

    LO QUE NO SE HACE: descartar por no tener distancia. Una fuente que no
    publica `lap_distance` ---OpenF1--- no declara nada sobre la linea, y
    tirarle las muestras la dejaria sin trazado.
    """

    @staticmethod
    def _fila(distancia, vuelta=1):
        from datetime import datetime, timezone
        return (1.0, 2.0, None, distancia, vuelta,
                datetime(2025, 7, 6, tzinfo=timezone.utc), 1, 100.0)

    def test_lo_de_antes_de_la_linea_no_entra_en_la_vuelta(self) -> None:
        filas = [self._fila(-5342.3), self._fila(-916.4),
                 self._fila(1.2), self._fila(1419.4)]
        quedan = api_sesion._solo_dentro_de_la_vuelta(filas)
        self.assertEqual([f[3] for f in quedan], [1.2, 1419.4])

    def test_el_metro_cero_si_entra(self) -> None:
        """Cero es la linea, que es un sitio del circuito. Descartarlo por
        estar «en el borde» borraria la largada."""

        quedan = api_sesion._solo_dentro_de_la_vuelta([self._fila(0.0)])
        self.assertEqual(len(quedan), 1)

    def test_sin_distancia_no_se_descarta_nada(self) -> None:
        """OpenF1 no publica `lap_distance`: no declara nada sobre la linea y
        tirarle las muestras la dejaria sin trazado."""

        filas = [self._fila(None), self._fila(None)]
        self.assertEqual(len(api_sesion._solo_dentro_de_la_vuelta(filas)), 2)

    def test_una_fuente_mixta_conserva_lo_que_no_declara(self) -> None:
        filas = [self._fila(-100.0), self._fila(None), self._fila(50.0)]
        self.assertEqual([f[3] for f in api_sesion._solo_dentro_de_la_vuelta(filas)],
                         [None, 50.0])

    def test_si_todo_es_anterior_a_la_linea_no_se_inventa_una_vuelta(self) -> None:
        """Mejor un trazado vacio, que el punto de acceso ya sabe declarar, que
        uno dibujado con una trayectoria que no es la vuelta."""

        filas = [self._fila(-500.0), self._fila(-100.0)]
        self.assertEqual(api_sesion._solo_dentro_de_la_vuelta(filas), [])

    def test_sin_filas_no_revienta(self) -> None:
        self.assertEqual(api_sesion._solo_dentro_de_la_vuelta([]), [])

    def test_el_trazado_lo_usa_de_verdad(self) -> None:
        """SE COMPRUEBA SOBRE EL CODIGO QUE SE PUBLICA.

        La funcion podia existir, estar probada seis veces y no llamarla nadie:
        la mutacion que la desconectaba del trazado no mataba ninguna prueba.
        Es la tercera vez en el dia que aparece este hueco ---la ficha del
        circuito y `marcarSaltos` tuvieron el mismo---, y siempre por lo mismo:
        las pruebas miran a quien consume el dato y el defecto esta en quien lo
        emite.

        Y se exige que se aplique **antes** de agrupar por vuelta: si se
        aplicara despues, `_vuelta_que_mejor_dibuja` ya habria elegido
        comparando trayectorias mezcladas con vueltas limpias.
        """

        import inspect
        fuente = inspect.getsource(api_sesion)
        i = fuente.index("_solo_dentro_de_la_vuelta(filas)")
        self.assertGreater(i, 0)
        j = fuente.index("_vuelta_que_mejor_dibuja(por_vuelta)")
        self.assertLess(i, j,
                        "el filtro corre despues de elegir la vuelta: la eleccion "
                        "ya se hizo con trayectorias mezcladas")


class LoQueElTrazadoNecesitaParaNoInventarUnTramo(unittest.TestCase):
    """Por que la respuesta del trazado lleva el tiempo y la velocidad.

    EL DEFECTO. El simulador teletransporta el coche ---al empezar una vuelta
    lanzada, con un `flashback`, al reiniciar en boxes--- y los puntos del
    trazado se dibujan como una sola polilinea. Medido el 2026-09-12 sobre
    `f1_25:session:16227589096132074312`: entre dos puntos consecutivos de la
    respuesta hay **476 m**, con una mediana de 12 m y un segundo mayor de 39 m.
    Esa recta cruza el circuito y nadie la recorrio. Y en la reproduccion el
    coche se ubica **sobre el camino dibujado**, de modo que la recorre toda.

    POR QUE LA REGLA NO SE ESCRIBE ACA. Ya existe y esta probada en el tablero
    ---`pudoRecorrer`, ver `tests/js/un_salto_no_es_un_tramo.js`---: un
    vehiculo no pudo moverse mas de lo que su velocidad declarada permite en el
    tiempo transcurrido. Escribirla de nuevo en Python daria **dos
    implementaciones de una misma fisica**, que es el defecto que este tablero
    ya tuvo con `estado.clima`, con el pie de avisos, con el constructor del
    trazado y con la ficha del circuito.

    Asi que el punto de acceso no decide: **entrega lo que hace falta para
    decidir**. Y tiene que entregarlo por punto devuelto y no por muestra,
    porque la respuesta viene reducida ---2.478 muestras en 497 puntos--- y
    entre dos puntos vecinos de la respuesta el coche recorrio mucho mas que
    entre dos muestras.
    """

    @staticmethod
    def _filas(velocidades, dt=1.0):
        from datetime import datetime, timedelta, timezone
        t0 = datetime(2025, 7, 6, 14, 0, tzinfo=timezone.utc)
        return [(float(i), float(i), None, float(i) * 10, 1,
                 t0 + timedelta(seconds=i * dt), None, v)
                for i, v in enumerate(velocidades)]

    def test_el_primer_punto_no_tiene_tramo_anterior(self) -> None:
        pasos = api_sesion._pasos_del_trazado(self._filas([100.0, 200.0]))
        self.assertIsNone(pasos["dt_s"][0])
        self.assertEqual(pasos["velocidad_kmh"][0], 100.0)

    def test_el_tiempo_es_entre_puntos_devueltos_y_no_entre_muestras(self) -> None:
        """Con la respuesta reducida, dos puntos vecinos estan a varios
        segundos. Usar el periodo de muestreo daria una cota diez veces mas
        chica y todo tramo pareceria un salto."""

        pasos = api_sesion._pasos_del_trazado(self._filas([300.0] * 4, dt=0.5))
        self.assertEqual(pasos["dt_s"][1:], [0.5, 0.5, 0.5])

    def test_cada_punto_lleva_su_velocidad(self) -> None:
        pasos = api_sesion._pasos_del_trazado(self._filas([0.0, 332.0, 330.0]))
        self.assertEqual(pasos["velocidad_kmh"], [0.0, 332.0, 330.0])

    def test_una_velocidad_ausente_se_dice_y_no_se_rellena(self) -> None:
        """Sin velocidad no se puede acotar nada, y poner cero convertiria cada
        tramo en un salto. Va `null` y quien dibuje decide ---el tablero, ante
        la duda, dibuja."""

        pasos = api_sesion._pasos_del_trazado(self._filas([100.0, None, 200.0]))
        self.assertEqual(pasos["velocidad_kmh"], [100.0, None, 200.0])

    def test_sin_instante_no_se_inventa_un_tramo(self) -> None:
        filas = [(0.0, 0.0, None, 0.0, 1, None, None, 100.0),
                 (1.0, 1.0, None, 10.0, 1, None, None, 100.0)]
        self.assertEqual(api_sesion._pasos_del_trazado(filas)["dt_s"], [None, None])

    def test_el_largo_coincide_con_los_puntos(self) -> None:
        """Dos arreglos paralelos que no midan lo mismo desalinean todo el
        dibujo, y en silencio."""

        filas = self._filas([1.0] * 7)
        pasos = api_sesion._pasos_del_trazado(filas)
        self.assertEqual(len(pasos["dt_s"]), len(filas))
        self.assertEqual(len(pasos["velocidad_kmh"]), len(filas))

    def test_sin_filas_no_revienta(self) -> None:
        self.assertEqual(api_sesion._pasos_del_trazado([]),
                         {"dt_s": [], "velocidad_kmh": []})


class LosSectoresDelTrazadoTests(unittest.TestCase):
    """Donde empieza cada sector, y de donde sale ese limite.

    LOS SECTORES NO SE ANOTAN: SE MIDEN. Es la diferencia con el nombre de una
    curva, que no esta en ningun canal y por eso vive en `catalogo_curvas` con
    su origen declarado. Cada fuente alcanza el limite por una dimension
    distinta y la respuesta tiene que decir por cual.
    """

    @staticmethod
    def _filas(sectores, desde=0):
        """Geometria cruda: x, z, y, distancia, vuelta, instante, sector."""
        from datetime import datetime, timedelta, timezone
        t0 = datetime(2025, 7, 6, 14, 0, tzinfo=timezone.utc)
        return [(float(i), float(i), None, float(i) * 10, 1,
                 t0 + timedelta(seconds=i), s)
                for i, s in enumerate(sectores, start=desde)]

    def test_el_limite_es_donde_el_indice_de_sector_cambia(self) -> None:
        filas = self._filas([0] * 10 + [1] * 10 + [2] * 10)
        d = api_sesion._sectores_del_trazado(
            MagicMock(), "f1_25_udp_simulation", "f1_25:session:1", None, filas, filas)
        self.assertEqual([s["sector"] for s in d["sectores"]], [1, 2, 3])
        self.assertEqual([s["desde_m"] for s in d["sectores"]], [0.0, 100.0, 200.0])

    def test_el_metro_es_el_de_la_muestra_cruda_y_no_el_del_dibujo(self) -> None:
        """EL DEFECTO QUE ESTA PRUEBA FIJA, y que la primera version tuvo.

        El trazado devuelve como mucho `puntos` posiciones, que salen de tomar
        una de cada N. Buscar el limite directamente en esa lista reducida
        parece lo mismo y no lo es: con 60.468 filas en 363 puntos se toma una
        de cada 167, que a esa velocidad son unos once metros, y el metro
        declarado habria quedado cuantizado al paso del dibujo.

        El dibujo puede redondear. El metro que la respuesta declara como
        medido, no.
        """

        filas = self._filas([0] * 10 + [1] * 10)     # el limite cae en el metro 100
        recorte = filas[::7]                          # el dibujo solo tiene 0, 70, 140...
        d = api_sesion._sectores_del_trazado(
            MagicMock(), "f1_25_udp_simulation", "f1_25:session:1", None, filas, recorte)
        metros = [s["desde_m"] for s in d["sectores"]]
        self.assertEqual(metros, [0.0, 100.0],
                         "el metro salio del recorte: quedo cuantizado al paso del dibujo")
        # Y el indice si es del dibujo, porque es donde hay que marcar.
        self.assertTrue(all(0 <= s["indice"] < len(recorte) for s in d["sectores"]))

    def test_una_fuente_sin_metro_no_inventa_uno(self) -> None:
        """OpenF1 ubica el limite en el tiempo. Escribirle un metro seria darle
        a esa posicion el respaldo de una medicion que nadie hizo."""

        from datetime import datetime, timedelta, timezone
        t0 = datetime(2025, 7, 6, 14, 0, tzinfo=timezone.utc)
        filas = [(float(i), float(i), None, None, 1, t0 + timedelta(seconds=i), None)
                 for i in range(30)]
        cursor = MagicMock()
        cursor.fetchone.return_value = (t0, 10.0, 10.0)
        d = api_sesion._sectores_del_trazado(
            cursor, "openf1_historical_replay", "openf1:session:9947",
            "openf1:session:9947:driver:1", filas, filas)
        self.assertEqual([s["sector"] for s in d["sectores"]], [1, 2, 3])
        self.assertEqual([s["desde_m"] for s in d["sectores"]], [None, None, None])
        self.assertEqual([s["indice"] for s in d["sectores"]], [0, 10, 20])

    def test_sin_con_que_ubicarlos_no_se_devuelven_sectores(self) -> None:
        """Tres marcas inventadas sobre un circuito son peores que ninguna."""

        from datetime import datetime, timedelta, timezone
        t0 = datetime(2025, 7, 6, 14, 0, tzinfo=timezone.utc)
        filas = [(float(i), float(i), None, None, 1, t0 + timedelta(seconds=i), None)
                 for i in range(30)]
        cursor = MagicMock()
        cursor.fetchone.return_value = None          # el contexto no tiene esa vuelta
        d = api_sesion._sectores_del_trazado(
            cursor, "openf1_historical_replay", "openf1:session:9947",
            "openf1:session:9947:driver:1", filas, filas)
        self.assertEqual(d["sectores"], [])
        self.assertEqual(d["sectores_origen"], "")
        # Y una fuente cuya geometria no trae sector tampoco los inventa.
        sin_sector = self._filas([None] * 20)
        d2 = api_sesion._sectores_del_trazado(
            MagicMock(), "f1_25_udp_simulation", "f1_25:session:1", None,
            sin_sector, sin_sector)
        self.assertEqual(d2["sectores"], [])

    def test_un_solo_limite_no_es_un_sector(self) -> None:
        """Un tramo que no cambia de sector da **un** limite, y una marca sola
        rotulada «sector 1» afirma que hay un sector 2 y un sector 3 en algun
        lado. No los hay en lo que se dibujo: un circuito con una raya y nada
        mas dice menos que uno sin rayas, porque ademas confunde.
        """

        un_tramo = self._filas([1] * 20)
        d = api_sesion._sectores_del_trazado(
            MagicMock(), "f1_25_udp_simulation", "f1_25:session:1", None,
            un_tramo, un_tramo)
        self.assertEqual(d["sectores"], [])
        self.assertEqual(d["sectores_origen"], "",
                         "se declara el origen de una lista vacia")

    def test_dos_limites_en_el_mismo_punto_no_son_dos_marcas(self) -> None:
        """Con pocos puntos de dibujo dos limites pueden caer en el mismo, y dos
        marcas encimadas se leen como una sola mal puesta."""

        filas = self._filas([0] * 2 + [1] * 2 + [2] * 16)
        recorte = [filas[0], filas[10], filas[19]]
        d = api_sesion._sectores_del_trazado(
            MagicMock(), "f1_25_udp_simulation", "f1_25:session:1", None, filas, recorte)
        indices = [s["indice"] for s in d["sectores"]]
        self.assertEqual(len(indices), len(set(indices)), indices)

    def test_si_hay_sectores_la_respuesta_dice_de_donde_salen(self) -> None:
        """Las dos fuentes los alcanzan por dimensiones distintas ---una por
        muestra, la otra por duracion declarada--- y quien los dibuje tiene que
        poder decir cual esta mirando."""

        filas = self._filas([0] * 10 + [1] * 10)
        d = api_sesion._sectores_del_trazado(
            MagicMock(), "f1_25_udp_simulation", "f1_25:session:1", None, filas, filas)
        self.assertIn("sector_index", d["sectores_origen"])
        self.assertIn("medido", d["sectores_origen"])

        from datetime import datetime, timedelta, timezone
        t0 = datetime(2025, 7, 6, 14, 0, tzinfo=timezone.utc)
        of1 = [(float(i), float(i), None, None, 1, t0 + timedelta(seconds=i), None)
               for i in range(30)]
        cursor = MagicMock()
        cursor.fetchone.return_value = (t0, 10.0, 10.0)
        d2 = api_sesion._sectores_del_trazado(
            cursor, "openf1_historical_replay", "openf1:session:9947",
            "openf1:session:9947:driver:1", of1, of1)
        self.assertIn("duraciones de sector", d2["sectores_origen"])
        self.assertNotIn("medido:", d2["sectores_origen"],
                         "una posicion alcanzada por tiempo no se declara igual que "
                         "una que la muestra trae")


class ElTrazadoDeUnaFuenteSinVueltasTests(unittest.TestCase):
    """De punta a punta: que el punto de acceso vaya a buscar las vueltas.

    Las piezas se prueban aparte; esto fija que esten conectadas. Sin la
    conexion, cada una anda bien y el dibujo sigue siendo la sesion entera.
    """

    @staticmethod
    def _filas():
        from datetime import datetime, timedelta, timezone
        t0 = datetime(2025, 7, 6, 14, 0, tzinfo=timezone.utc)
        # x, z, y, distancia, vuelta, timestamp, sector
        return [(float(i), float(i), None, None, None, t0 + timedelta(seconds=i), None)
                for i in range(60)]

    @classmethod
    def _con_dos_respuestas(cls, geometria):
        """Un doble que contesta segun que se le pregunte.

        `ConexionFalsa` devuelve las mismas filas a toda consulta, y aca hay
        tres con formas distintas: la geometria trae siete columnas, las
        ventanas de vuelta tres, y los cortes de sector tres de otra clase. Un
        doble que contesta lo mismo a todas no puede distinguir cual se hizo,
        que es justo lo que se quiere fijar.

        NO ALCANZA CON ENRUTAR POR EL NOMBRE DE LA TABLA. Dos de las tres
        preguntan a `racing_laps` y piden cosas distintas: una las ventanas de
        cada vuelta, la otra las duraciones de sector de una sola. Enrutar por
        «racing_laps» le daba a la segunda las filas de la primera, y el primer
        campo ---un numero de vuelta donde se esperaba un instante--- reventaba
        al sumarle la duracion. Se enruta por la columna que cada una pide.
        """

        from datetime import datetime, timedelta, timezone
        t0 = datetime(2025, 7, 6, 14, 0, tzinfo=timezone.utc)
        vueltas = [(1, t0, t0 + timedelta(seconds=30)),
                   (2, t0 + timedelta(seconds=30), t0 + timedelta(seconds=60))]
        # Una vuelta de 30 s partida en tres sectores de 10.
        sectores = [(t0, 10.0, 10.0)]

        falsa = ConexionFalsa(geometria)
        original = falsa._ejecutar

        def _ejecutar(consulta, parametros=None):
            original(consulta, parametros)
            if "duration_sector_1_seconds" in consulta:
                falsa.filas = sectores
            elif "lap_duration_seconds" in consulta:
                falsa.filas = vueltas
            else:
                falsa.filas = geometria

        falsa.cursor_obj.execute.side_effect = _ejecutar
        return falsa, patch("backend.api_sesion.db.obtener_conexion", return_value=falsa)

    def test_sin_numeros_de_vuelta_va_a_buscarlas_al_contexto(self) -> None:
        falsa, parche = self._con_dos_respuestas(self._filas())
        with parche:
            api_sesion.trazado("openf1:session:9947", puntos=50,
                               vehiculo="openf1:session:9947:driver:1")
        consultas = "\n".join(c for c, _ in falsa.consultas)
        self.assertIn("lap_duration_seconds", consultas,
                      "no se fue a buscar las ventanas de vuelta: el trazado sale "
                      "con la sesion entera superpuesta. Se nombra la columna y no "
                      "la tabla porque los cortes de sector preguntan a la misma")

    def test_el_vehiculo_que_pide_quien_consulta_acota_la_geometria(self) -> None:
        """Sin esto se dibuja la caja que contiene a los tres, no el recorrido
        de ninguno."""

        falsa, parche = self._con_dos_respuestas(self._filas())
        with parche:
            api_sesion.trazado("openf1:session:9947", puntos=50,
                               vehiculo="openf1:session:9947:driver:4")
        parametros = [p for _, p in falsa.consultas if p]
        planos = [str(x) for tupla in parametros for x in tupla]
        self.assertIn("openf1:session:9947:driver:4", planos,
                      "el vehiculo pedido no acoto ninguna consulta")

    def test_si_la_telemetria_ya_trae_la_vuelta_no_se_busca_en_el_contexto(self) -> None:
        """El contexto es el respaldo, no el primer sitio donde mirar.

        Una fuente puede publicar `lap_number` y estar en el contexto igual:
        preguntarle al contexto teniendo el numero en la propia telemetria seria
        una consulta de mas por cada trazado.
        """

        from datetime import datetime, timedelta, timezone
        t0 = datetime(2025, 7, 6, 14, 0, tzinfo=timezone.utc)
        filas = [(float(i), float(i), None, None, 3.0, t0 + timedelta(seconds=i), None)
                 for i in range(60)]
        falsa, parche = self._con_dos_respuestas(filas)
        with parche:
            api_sesion.trazado("openf1:session:9947", puntos=50,
                               vehiculo="openf1:session:9947:driver:1")
        consultas = "\n".join(c for c, _ in falsa.consultas)
        # Se nombra la columna de las ventanas y no la tabla: los cortes de
        # sector preguntan a `racing_laps` tambien, y son otra pregunta ---esta
        # fuente no publica sector por muestra, asi que ese si es el unico sitio
        # donde estan---. Prohibir la tabla entera prohibiria las dos.
        self.assertNotIn("lap_duration_seconds", consultas)

    def test_con_vueltas_en_la_telemetria_no_consulta_el_contexto(self) -> None:
        """El simulador trae `lap_number`: ese camino no puede cambiar."""

        from datetime import datetime, timedelta, timezone
        t0 = datetime(2025, 7, 6, 14, 0, tzinfo=timezone.utc)
        filas = [(float(i), float(i), None, float(i), 1.0, t0 + timedelta(seconds=i))
                 for i in range(60)]
        falsa, parche = _con(filas)
        with parche:
            api_sesion.trazado("f1_25:session:1", puntos=50)
        consultas = "\n".join(c for c, _ in falsa.consultas)
        self.assertNotIn("racing_laps", consultas)


class AvisosTests(unittest.TestCase):
    def test_una_fuente_sin_banderas_ni_dano_no_inventa_avisos(self) -> None:
        r = api_sesion.avisos("9939")
        self.assertEqual(r["avisos"], [])
        self.assertIn("no hay con que levantar un aviso", r["motivo"])

    def test_el_historico_usa_los_mismos_avisos_que_el_anotador_vivo(self) -> None:
        from datetime import datetime, timedelta, timezone

        t0 = datetime(2026, 9, 10, tzinfo=timezone.utc)
        filas = [
            ("lap_number", 1.0, None, None, "", t0),
            ("lap_distance", 120.0, None, None, "m", t0),
            ("fuel_remaining_laps", -0.5, None, None, "vueltas", t0),
            ("floor_damage", 12.0, None, None, "%", t0 + timedelta(milliseconds=10)),
        ]
        mensajes = [{
            "signal_name": nombre,
            "value": numero,
            "unit": unidad,
            "timestamp": instante.isoformat(),
        } for nombre, numero, _, _, unidad, instante in filas]
        esperadas = anotador_vivo.anotar_secuencia(mensajes)
        falsa, _ = _con(filas)
        falsa.cursor_obj.fetchmany.side_effect = [filas, []]

        recibidas = api_sesion._avisos_reproducidos(
            falsa.cursor_obj, "f1_25_udp_simulation", "s", None,
            None, (None, None), 60)

        self.assertEqual([a["que"] for a in recibidas],
                         [a["titulo"] for a in esperadas])
        self.assertEqual([a["detalle"] for a in recibidas],
                         [a["detalle"] for a in esperadas])
        self.assertEqual([a["nivel"] for a in recibidas],
                         ["alerta" if a["nivel"] == "incidente" else "info"
                          for a in esperadas])

    def test_el_piano_deja_la_pista_pero_no_el_agarre(self) -> None:
        """Dos afirmaciones distintas que esta prueba antes mezclaba en una.

        Fijaba una tabla propia de este modulo ---`SUPERFICIES_FUERA`--- que
        estaba corrida y no se usaba en ninguna parte: daba el 2 por grava
        cuando el 2 es hormigon, y le faltaba el 7, que es el cesped y es la
        superficie sobre la que se sale de pista casi siempre.

        Lo que la prueba queria decir sigue siendo cierto y se dice contra la
        tabla del decodificador, que es la unica: **rodar sobre un piano no es
        perder el agarre**, porque en muchas curvas la trazada normal lo pisa.

        Y no es lo mismo que la otra: para el reglamento el piano **no es
        pista** ---articulo 33.3--- de modo que las cuatro ruedas sobre piano si
        son una salida. Una nocion es fisica y la otra normativa, y el aviso las
        declara por separado.
        """

        self.assertIn(1, f1_udp.SUPERFICIES_CON_AGARRE)
        self.assertNotEqual(1, f1_udp.SUPERFICIE_DE_PISTA)
        self.assertEqual("piano", f1_udp.SUPERFICIES[1])
        self.assertEqual("cesped", f1_udp.SUPERFICIES[7])

    def test_la_salida_de_pista_se_evalua_y_se_cuenta(self) -> None:
        """La regla de superficie existe y entra en el recuento que se declara.

        Vivia solo en el anotador en vivo, de modo que una sesion mirada
        mientras corria anotaba salidas que la misma sesion reproducida no
        mostraba. Medido sobre Abu Dabi: veintitres cuadros con las cuatro
        ruedas fuera y cero avisos en la respuesta.
        """

        self.assertTrue(api_sesion.REGLA_FUERA_DE_PISTA["canal"])
        self.assertIn(api_sesion.REGLA_FUERA_DE_PISTA["nivel"],
                      {"critico", "alerta", "info"})

    def test_cada_regla_declara_su_canal_y_su_umbral(self) -> None:
        """Un aviso sin origen ni umbral es una afirmacion que no se puede discutir."""
        for regla in api_sesion.REGLAS_DE_AVISO:
            self.assertTrue(regla["canal"])
            self.assertIsInstance(regla["umbral"], float)
            self.assertIn(regla["nivel"], {"critico", "alerta", "info"})

    def test_los_umbrales_van_en_la_unidad_en_que_la_senal_se_guarda(self) -> None:
        """El anotador en vivo mira la senal cruda; estas reglas miran la guardada.

        No son la misma escala y esa es toda la trampa. El adaptador publica el
        acelerador y el freno **multiplicados por cien**, porque los declara en
        por ciento; el anotador en vivo los evalua antes de eso, en la fraccion
        de cero a uno que entrega el juego. Importar el umbral del anotador y
        compararlo contra la columna guardada ---que fue exactamente lo que se
        hizo--- convierte "acelerador sobre el 50 %" en "acelerador sobre el
        0,5 %", que no excluye nada: es practicamente "el pedal no esta del todo
        suelto".

        Por eso los umbrales de estos dos canales viven aca con el sufijo de su
        unidad, y esta prueba fija la conversion. Los otros ---deslizamiento,
        giro, fuerza vertical--- se guardan con factor 1,0 y se siguen
        importando tal cual.
        """

        factores = adaptador_f1_25.SENALES_TELEMETRIA
        self.assertEqual(factores["throttle"][2], 100.0)
        self.assertEqual(factores["brake"][2], 100.0)

        self.assertEqual(api_sesion.UMBRAL_ACELERADOR_PCT,
                         0.5 * factores["throttle"][2])
        self.assertEqual(api_sesion.UMBRAL_FRENO_SUELTO_PCT,
                         anotador_vivo.UMBRAL_FRENO_SUELTO * factores["brake"][2])

    def test_la_caida_brusca_de_velocidad_tambien_existe_sobre_lo_guardado(self) -> None:
        """La tercera regla del anotador, que solo vivia sobre el flujo.

        Las otras dos ---tren trasero e impacto vertical--- son una condicion
        sobre un instante. Esta es sobre una ventana: cuanto cayo la velocidad
        en medio segundo, con el freno suelto en **toda** esa ventana. Por eso
        quedo afuera cuando se trajeron las demas, y por eso una sesion mirada
        en vivo anotaba caidas que la misma sesion reproducida no mostraba.
        """

        nombres = [r["que"] for r in api_sesion.REGLAS_FISICAS]
        self.assertIn("Caida brusca de velocidad", nombres)

    def test_la_caida_se_mide_con_los_numeros_calibrados_en_el_anotador(self) -> None:
        """Que la consulta lleve los valores del anotador y no unos propios.

        Se comprueba sobre los parametros que el modulo le pasa a la base, que
        es lo que este modulo decide. Que PostgreSQL sepa correr una ventana no
        es lo que puede romperse al editar; que alguien escriba aca un 40
        distinto del 40 del anotador, si.
        """

        falsa, parche = _con([])
        with parche:
            api_sesion._primera_caida_brusca(
                falsa.cursor_obj, "f1_25_udp_simulation", "f1_25:session:1")

        consulta, parametros = falsa.consultas[-1]
        self.assertIn(anotador_vivo.UMBRAL_CAIDA_KMH, parametros)
        self.assertIn(api_sesion.UMBRAL_FRENO_SUELTO_PCT, parametros)
        self.assertIn("%d milliseconds" % (anotador_vivo.VENTANA_CAIDA_S * 1000),
                      consulta)


class UnAvisoEsDeUnVehiculoTests(unittest.TestCase):
    """Ninguna regla puede mezclar vehiculos, y con uno solo no se notaba.

    Todas estas consultas giran la tabla larga a una fila por instante con
    `max(value_numeric) FILTER (WHERE signal_name = ...)`. Con **un** vehiculo
    capturado ese `max` es el unico valor que hay y la consulta es correcta. Con
    cuatro, toma el mayor de los cuatro por cada canal por separado: el giro de
    uno con el volante de otro y el deslizamiento de un tercero. Eso no describe
    a ningun coche, y el aviso que sale de ahi afirma algo que no ocurrio.

    Estuvo latente desde siempre y aparecio el 2026-09-10, la primera carrera
    con la parrilla acotada a cuatro. **Un defecto que solo se ve con datos que
    todavia no existian es un defecto igual.**

    La prueba es de la clase entera y no de cada regla: lo que hay que impedir
    es que se agregue la proxima consulta sin acotar.
    """

    REGLAS = ("_primera_perdida_de_tren_trasero", "_primer_trompo",
              "_primer_impacto_vertical", "_primera_caida_brusca",
              "_primera_salida_de_pista")

    def test_toda_regla_acota_a_un_vehiculo(self) -> None:
        for nombre in self.REGLAS:
            with self.subTest(regla=nombre):
                falsa, parche = _con([])
                with parche:
                    getattr(api_sesion, nombre)(
                        falsa.cursor_obj, "f1_25_udp_simulation",
                        "f1_25:session:1", "f1_25:session:1:car:0")
                consulta, parametros = falsa.consultas[-1]
                self.assertIn("vehicle_id", consulta,
                              "%s gira la tabla sin acotar el vehiculo" % nombre)
                self.assertIn("f1_25:session:1:car:0", parametros)

    def test_sin_saber_cual_es_el_propio_no_se_acota_y_se_dice(self) -> None:
        """Con una sesion vieja de un solo vehiculo no hay a quien acotar.

        Devolver cero avisos seria peor que devolverlos sin acotar: con un unico
        vehiculo el `max` no mezcla nada y la lectura sigue siendo correcta. Lo
        que no puede pasar es que se calle.
        """

        falsa, parche = _con([])
        with parche:
            api_sesion._primer_trompo(
                falsa.cursor_obj, "f1_25_udp_simulation", "f1_25:session:1", None)
        consulta, _ = falsa.consultas[-1]
        self.assertNotIn("vehicle_id", consulta)


class NingunaConsultaLeeVariosVehiculosSinDecirloTests(unittest.TestCase):
    """La prueba que existe para que este defecto no vuelva una sexta vez.

    El 2026-09-10, en un solo dia, el mismo error aparecio en cinco lugares:
    las ocho consultas de avisos y trazado, las marcas sobre la pista, la
    eleccion del coche propio en el tablero, `/vueltas` y el estado del
    vehiculo. Todos compartian la misma forma: una lectura **correcta mientras
    se capturaba un vehiculo** y arbitraria en cuanto hubo cuatro.

    Buscarlos de a uno los encontraba despues de que molestaran. Esta prueba
    los busca antes: recorre las consultas del modulo y exige que toda la que
    lea una senal de vehiculo diga de cual.

    LO QUE NO CUENTA COMO SENAL DE VEHICULO. `lap_number` sirve tambien para
    delimitar adquisiciones y fases, que son hechos de la sesion y no de un
    coche; el clima y las banderas son de la pista. Esos se leen sin acotar a
    proposito.
    """

    #: Prefijos de las senales que describen a **un** coche.
    DE_VEHICULO = ("tyre_", "wheel_", "brake_", "engine_", "wing_", "floor_",
                   "diffuser_", "sidepod_", "gearbox_", "surface_type",
                   "g_force", "yaw_rate", "world_position", "throttle_position",
                   "brake_position", "steering_normalized", "gear_selected",
                   "ers_", "fuel_", "drs_")

    def test_toda_consulta_de_senales_de_vehiculo_declara_el_vehiculo(self) -> None:
        import inspect
        import re

        fuente = inspect.getsource(api_sesion)
        cortes = [(m.start(), m.group(1))
                  for m in re.finditer(r"\ndef ([a-zA-Z_]+)\(", fuente)]
        cortes.append((len(fuente), None))

        sin_acotar = []
        for (i, nombre), (j, _) in zip(cortes, cortes[1:]):
            cuerpo = fuente[i:j]
            if "FROM telemetry_messages" not in cuerpo:
                continue
            if not any(p in cuerpo for p in self.DE_VEHICULO):
                continue
            # Acotada si nombra la columna o usa el ayudante que la agrega.
            if "vehicle_id" in cuerpo or "_acotar_al_vehiculo" in cuerpo:
                continue
            # La unica excepcion, y por definicion: es la funcion que **responde**
            # cual es el vehiculo. No puede acotarse por su propia respuesta.
            if nombre == "_vehiculo_propio":
                continue
            sin_acotar.append(nombre)

        self.assertEqual(
            sin_acotar, [],
            "estas funciones leen senales de un vehiculo sin decir de cual, "
            "que con varios capturados mezcla los canales de todos: %s"
            % ", ".join(sin_acotar))


class ElEstadoDelVehiculoEsDeUnVehiculoTests(unittest.TestCase):
    """El panel pedia el ultimo valor de cada senal sin decir de que coche.

    `DISTINCT ON (signal_name)` sobre la sesion entera devuelve, para cada
    canal, la fila mas reciente **de cualquier vehiculo**. Con uno solo eso era
    su estado. Con cuatro es el del que publico ultimo, canal por canal: la
    temperatura de una goma de uno junto al dano de otro.

    Medido el 2026-09-10 en Red Bull Ring: Hamilton termino con los dos
    alerones delanteros al 100 % de dano, 2.974 muestras lo declaran, y el
    panel decia «sin dano, ninguna pieza lo declara».
    """

    def test_el_estado_se_pide_de_un_vehiculo(self) -> None:
        falsa, parche = _con([])
        with parche, patch.object(api_sesion, "_vehiculo_propio",
                                  return_value="f1_25:session:1:car:19"):
            api_sesion.estado_del_vehiculo("f1_25:session:1")
        for consulta, parametros in falsa.consultas:
            if "DISTINCT ON (signal_name)" in consulta:
                self.assertIn("vehicle_id", consulta)
                self.assertIn("f1_25:session:1:car:19", parametros)

    def test_se_puede_pedir_el_de_otro_piloto(self) -> None:
        """Mirar a un rival es una pregunta legitima, y hoy hay datos suyos.

        Con otra sesion que la prueba de arriba: la cache de canales ausentes es
        por sesion, y reusar el identificador haria que esta no consultara nada
        y pasara sin comprobar lo que dice comprobar.
        """

        falsa, parche = _con([])
        with parche:
            api_sesion.estado_del_vehiculo("f1_25:session:2",
                                           vehiculo="f1_25:session:2:car:3")
        pedidos = [p for c, p in falsa.consultas if "DISTINCT ON (signal_name)" in c]
        self.assertTrue(pedidos)
        for parametros in pedidos:
            self.assertIn("f1_25:session:2:car:3", parametros)


class LasVueltasSonDeQuienConduceTests(unittest.TestCase):
    """`/vueltas` elegia el vehiculo con mas filas, y el tablero le hacia caso.

    Su razonamiento estaba escrito y era correcto **cuando se capturaba un solo
    coche**: «de los rivales la fuente publica cronometraje y no telemetria, de
    modo que el que tiene mas filas es siempre el que se conduce». Desde que se
    puede elegir a quien escuchar, los rivales traen exactamente las mismas
    senales y con la misma frecuencia: el mas muestreado vuelve a ser cualquiera.

    El tablero lo tomaba como autoritativo ---«ninguna otra la pisa», decia su
    comentario--- de modo que abria en Russell una sesion corrida con Hamilton,
    y volvia a Russell cada vez que se lo cambiaba a mano.

    Se pregunta primero quien conduce. El mas muestreado queda de respaldo para
    cuando la sesion no lo declara.
    """

    def test_prefiere_a_quien_declara_el_flujo(self) -> None:
        falsa, parche = _con([])
        with parche, patch.object(api_sesion, "_vehiculo_propio",
                                  return_value="f1_25:session:7:car:19") as declarado:
            api_sesion.listar_vueltas("f1_25:session:7")
        self.assertTrue(declarado.called)
        # Sabiendo quien conduce, no hace falta contar filas para adivinarlo.
        consultas = [c for c, _ in falsa.consultas]
        self.assertFalse([c for c in consultas if "ORDER BY 2 DESC" in c])

    def test_sin_declaracion_vuelve_a_contar_filas(self) -> None:
        """Es lo que habia, y con una captura de un vehiculo sigue acertando."""

        falsa, parche = _con([])
        with parche:
            api_sesion.listar_vueltas("f1_25:session:7")
        consultas = [c for c, _ in falsa.consultas]
        self.assertTrue([c for c in consultas if "ORDER BY 2 DESC" in c])


class LaParrillaDiceQuienConduceTests(unittest.TestCase):
    """El tablero adivinaba quien es el coche propio. Con cuatro, adivinaba mal.

    Lo tomaba del vehiculo cuya serie devolvia primero la consulta. Con **un**
    vehiculo capturado eso acertaba por construccion: habia uno solo. Con
    cuatro es arbitrario, y el 2026-09-10 la sesion de Red Bull Ring, corrida
    con Hamilton, abrio mostrando a Russell ---y el panel de vehiculo en ceros,
    porque de un rival el protocolo no publica ni temperaturas ni presiones---.

    Es el mismo defecto que se corrigio en las reglas de aviso el mismo dia:
    **deducir del sintoma lo que la fuente declara**. `player_car_index` viene
    en la cabecera de cada paquete y dice quien conduce.
    """

    def test_la_parrilla_marca_cual_es_el_propio(self) -> None:
        declarada = {"vehiculos": [
            {"indice": 3, "nombre": "Russell", "numero": 63,
             "equipo": "Mercedes", "es_ia": True},
            {"indice": 19, "nombre": "Hamilton", "numero": 44,
             "equipo": "Ferrari", "es_ia": False}]}
        salida = api_sesion._vehiculos_nombrados(
            "f1_25:session:1", declarada, propio="f1_25:session:1:car:19")
        por_nombre = {v["nombre"]: v for v in salida}
        self.assertTrue(por_nombre["Hamilton"]["es_propio"])
        self.assertFalse(por_nombre["Russell"]["es_propio"])

    def test_sin_declaracion_no_se_marca_a_ninguno(self) -> None:
        """Marcar al primero seria volver a adivinar, con otra excusa."""

        declarada = {"vehiculos": [
            {"indice": 0, "nombre": "Verstappen", "numero": 33,
             "equipo": "Red Bull Racing", "es_ia": False}]}
        salida = api_sesion._vehiculos_nombrados("f1_25:session:1", declarada)
        self.assertFalse(salida[0]["es_propio"])


class VehiculoPropioTests(unittest.TestCase):
    """De quien son los avisos: de quien conduce, y lo declara el flujo."""

    def test_lo_saca_del_indice_que_declara_el_paquete(self) -> None:
        """No se infiere de que senales tiene: se lee de lo que el juego dijo."""

        falsa, parche = _con([("3",)])
        with parche:
            clave = api_sesion._vehiculo_propio(
                falsa.cursor_obj, "f1_25_udp_simulation", "f1_25:session:99")
        self.assertEqual(clave, "f1_25:session:99:car:3")

    def test_sin_declaracion_devuelve_nada_en_vez_de_adivinar(self) -> None:
        falsa, parche = _con([])
        with parche:
            self.assertIsNone(api_sesion._vehiculo_propio(
                falsa.cursor_obj, "f1_25_udp_simulation", "f1_25:session:99"))


class CurvasTests(unittest.TestCase):
    def test_devuelve_el_catalogo_declarando_que_es_anotacion(self) -> None:
        r = api_sesion.curvas_del_circuito("spa-francorchamps")
        self.assertEqual(len(r["curvas"]), 15)
        self.assertEqual(r["sentido"], "horario")
        self.assertIn("nombre: catalogo externo", r["curvas"][0]["origen"])
        self.assertIn("Kemmel", r["sin_frenada"])

    def test_un_circuito_sin_catalogo_no_falla(self) -> None:
        """EL EJEMPLO DE «CIRCUITO AUSENTE» NO PUEDE SER UN CIRCUITO REAL.

        Esta guarda uso Spielberg primero y Monza despues, y las dos veces se
        puso roja el dia que ese circuito entro al catalogo ---por un motivo que
        no es el suyo---. Lo que comprueba es que un circuito que no esta vuelva
        vacio en vez de romper la vista, y para eso el ejemplo tiene que ser uno
        que no vaya a estar nunca.

        Es la forma de envejecer de una guarda que nombra un caso concreto: el
        caso deja de serlo y la guarda no se entera sola."""

        r = api_sesion.curvas_del_circuito("circuito-que-no-existe")
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
        """ESTA PRUEBA USABA SPIELBERG DE EJEMPLO Y SPIELBERG YA TIENE CATALOGO.

        Lo que comprueba es que un circuito ausente vuelva vacio en vez de
        romper la vista, y para eso hace falta un circuito **que siga
        ausente**. Dejarla apuntando a Spielberg la habria puesto roja por un
        motivo que no es el suyo; cambiarle el ejemplo a uno que el catalogo no
        tiene la conserva midiendo lo mismo.

        Es la forma de envejecer de una guarda que nombra un caso concreto: el
        caso deja de serlo y la guarda no se entera sola."""

        self.assertEqual(catalogo_curvas.curvas_de("circuito-que-no-existe"), ())


class UltimosValoresAcotados(unittest.TestCase):
    """Un panel que acompana una reproduccion no puede contestar con el ultimo
    valor de la sesion: una carrera que termina en tormenta mostraria tormenta
    desde la primera vuelta. La consulta se acota al instante que se mira."""

    def _cursor(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        return cursor

    def test_sin_instante_la_ultima_consulta_no_acota(self):
        """Sin instante, el ultimo intento tiene que mirar la sesion entera.

        Los intentos anteriores **si** acotan ---la ventana reciente y la del
        comienzo, que son la optimizacion--- pero el ultimo no puede: si acotara,
        una senal publicada a mitad de sesion y nunca mas se perderia. Antes esta
        prueba miraba «ninguna consulta acota», que dejo de ser cierto al agregar
        las ventanas y no era lo que habia que garantizar.
        """

        cursor = self._cursor()
        api_sesion._AUSENTES_CACHE.clear()
        api_sesion._ultimos_valores(cursor, "f1_25_udp_simulation", "s", ["speed"])
        consulta, parametros = cursor.execute.call_args[0]
        self.assertNotIn("timestamp <=", consulta)
        self.assertNotIn("timestamp >=", consulta)
        self.assertEqual(len(parametros), 3)
        api_sesion._AUSENTES_CACHE.clear()

    def test_sin_instante_se_intenta_primero_acotado(self):
        """Y antes de eso se prueba con ventanas: es de donde sale la mejora."""

        cursor = self._cursor()
        api_sesion._AUSENTES_CACHE.clear()
        api_sesion._ultimos_valores(cursor, "f1_25_udp_simulation", "s", ["speed"])
        acotadas = [c[0][0] for c in cursor.execute.call_args_list
                    if "timestamp >=" in c[0][0]]
        self.assertGreaterEqual(len(acotadas), 1,
                                "no se intento ninguna ventana antes del recorrido completo")
        api_sesion._AUSENTES_CACHE.clear()

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


class PuestaAPuntoDeclarada(unittest.TestCase):
    """El reglaje aplicado se separa del menu y de una referencia externa."""

    @staticmethod
    def _valores(instante="2026-09-10T12:00:00+00:00"):
        return {
            canal: {"valor": i, "unidad": "", "instante": instante}
            for i, canal in enumerate(api_sesion.CANALES_PUESTA_A_PUNTO.values())
        }

    def test_el_reglaje_es_completo_solo_si_todo_viene_del_mismo_paquete(self):
        _, campos, instante, completa = api_sesion._armar_puesta_a_punto(
            self._valores())
        self.assertEqual(len(campos), 23)
        self.assertEqual(instante, "2026-09-10T12:00:00+00:00")
        self.assertTrue(completa)

        mezclados = self._valores()
        mezclados["setup_rear_wing"]["instante"] = "2026-09-10T12:00:01+00:00"
        _, _, instante, completa = api_sesion._armar_puesta_a_punto(mezclados)
        self.assertIsNone(instante)
        self.assertFalse(completa)

    def test_el_reglaje_se_asienta_con_rodaje_desde_su_instante(self):
        """DESDE Y NO DESPUES, y no es una sutileza.

        Preguntaba por una muestra **estrictamente posterior** al paquete de
        reglaje, y el juego publica los dos en el mismo instante muchas veces.
        Medido el 2026-09-13 sobre las catorce sesiones con reglaje de la base:
        **diez** declaraban «no asentada» con el paquete completo, por
        milisegundos. Una muestra que comparte instante con el paquete se midio
        con ese reglaje puesto.
        """
        cursor = MagicMock()
        cursor.fetchone.return_value = (True,)
        self.assertTrue(api_sesion._hubo_rodaje_desde(
            cursor, "f1_25_udp_simulation", "f1_25:session:1",
            "f1_25:session:1:car:0", "2026-09-10T12:00:00+00:00"))
        consulta, parametros = cursor.execute.call_args[0]
        self.assertIn("signal_name = 'speed'", consulta)
        self.assertIn("value_numeric > 0", consulta)
        self.assertIn("timestamp >= %s", consulta)
        self.assertNotIn("timestamp > %s", consulta)
        self.assertIn("vehicle_id = %s", consulta)
        self.assertEqual(consulta.count("%s"), len(parametros))

    def test_el_reglaje_que_se_muestra_es_el_que_estaba_puesto_al_rodar(self):
        """EL ULTIMO PAQUETE DE LA SESION PUEDE SER DEL MENU.

        El juego sigue publicando el reglaje con la sesion abierta despues de
        dejar de conducir. Medido en `12239226036560891185`: la ultima muestra
        rodando es de las 23:50:21 y el reglaje se siguio publicando hasta las
        00:01:32, once minutos mas tarde. Este panel describe lo que se llevo a
        la pista, asi que lee el paquete vigente en la ultima muestra en marcha.
        """
        cursor = MagicMock()
        cursor.fetchone.return_value = ("2026-09-10T12:00:00+00:00",)
        instante = api_sesion._instante_de_rodaje(
            cursor, "f1_25_udp_simulation", "f1_25:session:1",
            "f1_25:session:1:car:0")
        consulta, parametros = cursor.execute.call_args[0]
        self.assertIn("max(timestamp)", consulta)
        self.assertIn("signal_name = 'speed'", consulta)
        self.assertIn("value_numeric > 0", consulta)
        self.assertEqual(consulta.count("%s"), len(parametros))
        self.assertEqual(instante, "2026-09-10T12:00:00+00:00")

        # Sin una sola muestra en marcha no hay instante que devolver, y eso es
        # lo que deja `asentada` en falso sin que el criterio sea una tautologia.
        cursor.fetchone.return_value = (None,)
        self.assertIsNone(api_sesion._instante_de_rodaje(
            cursor, "f1_25_udp_simulation", "f1_25:session:1", None))

    def test_la_referencia_solo_se_compara_con_un_reglaje_asentado(self):
        puesta = {"aleron_delantero": 4, "aleron_trasero": 1}
        with patch.object(api_sesion.procedencia_sesiones, "de",
                          return_value={"circuito": "spa"}):
            referencia, diferencias = api_sesion._comparar_con_referencia(
                "f1_25:session:1", puesta, False)
            self.assertIsNotNone(referencia)
            self.assertEqual(diferencias, [])
            _, diferencias = api_sesion._comparar_con_referencia(
                "f1_25:session:1", puesta, True)
        self.assertEqual(diferencias, [
            {"clave": "aleron_delantero", "aplicado": 4,
             "referencia": 3, "diferencia": 1},
            {"clave": "aleron_trasero", "aplicado": 1,
             "referencia": 0, "diferencia": 1},
        ])

    def test_contexto_entrega_reglaje_asentado_y_referencia(self) -> None:
        valores = self._valores()
        falsa, parche_db = _con([])
        with parche_db, \
             patch.object(api_sesion, "_ultimos_valores", return_value=valores), \
             patch.object(api_sesion, "_vehiculo_propio", return_value="car:0"), \
             patch.object(api_sesion, "_ventana_de_alcance", return_value=None), \
             patch.object(api_sesion, "_limites_de_fase", return_value=(None, None)), \
             patch.object(api_sesion, "_hubo_rodaje_desde", return_value=True), \
             patch.object(api_sesion.procedencia_sesiones, "de",
                          return_value={"circuito": "spa"}):
            respuesta = api_sesion.contexto("f1_25:session:1")

        self.assertTrue(respuesta["puesta_completa"])
        self.assertTrue(respuesta["puesta_asentada"])
        self.assertEqual(
            respuesta["referencia_puesta"]["valores"]["aleron_delantero"], 3)
        self.assertEqual(len(respuesta["campos"]), 23)

    def test_cada_campo_del_catalogo_tiene_unidad(self):
        self.assertEqual(sorted(api_sesion.CANALES_PUESTA_A_PUNTO),
                         sorted(api_sesion.UNIDADES_PUESTA_A_PUNTO))

    def test_una_captura_antigua_no_se_confunde_con_una_fuente_incapaz(self):
        self.assertIn("necesitan reinyectarse", api_sesion._motivo_sin_puesta(
            "f1_25_udp_simulation"))
        self.assertIn("no publica", api_sesion._motivo_sin_puesta(
            "can_real_replay"))


class VueltaConSalto(unittest.TestCase):
    """Una vuelta con un salto de horas entre dos muestras seguidas no se rodo
    de corrido: son dos cargas de la misma sesion pegadas. La duracion que sirve
    es la de conduccion continua, y la bruta se declara porque la diferencia
    entre las dos **es** el hallazgo."""

    def test_la_duracion_util_es_la_continua_y_la_bruta_queda_declarada(self):
        from datetime import datetime, timezone
        t0 = datetime(2026, 9, 2, tzinfo=timezone.utc)
        t1 = datetime(2026, 9, 5, tzinfo=timezone.utc)   # tres dias despues
        filas = [(1, 6796, 1.2, 7007.2, t0, t1, 0.0, 317.0, 0.0, 209.0, 258215.5)]
        falsa, parche = _con(filas)
        with parche:
            r = api_sesion.listar_vueltas("f1_25:session:1")
        v = r["vueltas"][0]
        self.assertEqual(v["duracion_s"], 209.0)
        self.assertGreater(v["duracion_bruta_s"], 200000)
        self.assertEqual(v["hueco_mayor_s"], 258215.5)
        self.assertFalse(v["continua"])

    def test_una_vuelta_sin_saltos_se_declara_continua(self):
        from datetime import datetime, timezone
        t0 = datetime(2026, 9, 2, tzinfo=timezone.utc)
        t1 = datetime(2026, 9, 2, 0, 2, 10, tzinfo=timezone.utc)
        filas = [(2, 2604, 0.2, 7006.2, t0, t1, 40.0, 320.0, 0.0, 130.1, 0.1)]
        falsa, parche = _con(filas)
        with parche:
            r = api_sesion.listar_vueltas("f1_25:session:1")
        self.assertTrue(r["vueltas"][0]["continua"])
        self.assertEqual(r["vueltas"][0]["duracion_s"], 130.1)

    def test_una_vuelta_continua_declara_que_no_tuvo_cortes(self):
        """Lista vacia, no `None`: «no hubo» es una afirmacion."""
        from datetime import datetime, timezone
        t0 = datetime(2026, 9, 2, tzinfo=timezone.utc)
        t1 = datetime(2026, 9, 2, 0, 2, 10, tzinfo=timezone.utc)
        filas = [(2, 2604, 0.2, 7006.2, t0, t1, 40.0, 320.0, 0.0, 130.1, 0.1, None)]
        falsa, parche = _con(filas)
        with parche:
            r = api_sesion.listar_vueltas("f1_25:session:1")
        self.assertEqual(r["vueltas"][0]["huecos"], [])

    def test_los_limites_de_cada_hueco_se_devuelven_con_sus_dos_extremos(self):
        """POR QUE HIZO FALTA ESTE DATO.

        `hueco_mayor_s` dice si la vuelta se corto; no dice cuando. El tablero
        lo deducia de la serie que recibe, que llega submuestreada: cuatro mil
        muestras a 50 ms con un corte de 2,05 s, reducidas a 300 puntos, quedan
        con intervalos de 700 ms y el umbral heuristico sube a 2,8 s, de modo
        que el corte deja de contar y el reloj reproduce una pausa que este
        mismo endpoint excluyo de `duracion_s`. La misma captura daba dos
        relojes segun cuantos puntos se pidieran.

        Los limites salen de la resolucion completa, que es la unica que los
        tiene, y no cambian al reducir.
        """
        from datetime import datetime, timezone
        t0 = datetime(2026, 9, 2, tzinfo=timezone.utc)
        t1 = datetime(2026, 9, 2, 0, 2, 10, tzinfo=timezone.utc)
        corte_a = datetime(2026, 9, 2, 0, 0, 30, tzinfo=timezone.utc).timestamp()
        corte_b = datetime(2026, 9, 2, 0, 0, 35, tzinfo=timezone.utc).timestamp()
        # La bruta son 130 s; con un corte de 5 s, lo rodado son 125.
        filas = [(2, 2604, 0.2, 7006.2, t0, t1, 40.0, 320.0, 0.0, 125.0, 5.0,
                  [[corte_a, corte_b]])]
        falsa, parche = _con(filas)
        with parche:
            r = api_sesion.listar_vueltas("f1_25:session:1")
        v = r["vueltas"][0]
        self.assertEqual(len(v["huecos"]), 1)
        self.assertEqual(v["huecos"][0]["duracion_s"], 5.0)
        self.assertTrue(v["huecos"][0]["desde_utc"].startswith("2026-09-02T00:00:30"))
        self.assertTrue(v["huecos"][0]["hasta_utc"].startswith("2026-09-02T00:00:35"))
        # Y lo que declaran suma exactamente la diferencia entre las dos
        # duraciones: si no cerrara, una de las dos cuentas estaria mal.
        self.assertAlmostEqual(v["duracion_bruta_s"] - v["duracion_s"],
                               sum(h["duracion_s"] for h in v["huecos"]), places=3)

    def test_un_limite_ilegible_se_descarta_en_vez_de_tumbar_la_respuesta(self):
        from datetime import datetime, timezone
        t0 = datetime(2026, 9, 2, tzinfo=timezone.utc)
        t1 = datetime(2026, 9, 2, 0, 2, 10, tzinfo=timezone.utc)
        filas = [(2, 2604, 0.2, 7006.2, t0, t1, 40.0, 320.0, 0.0, 130.1, 5.0,
                  [["no es un numero", 1], [10, 5], [1, 2]])]
        falsa, parche = _con(filas)
        with parche:
            r = api_sesion.listar_vueltas("f1_25:session:1")
        # Se queda solo con el par que se puede leer y que avanza.
        self.assertEqual(len(r["vueltas"][0]["huecos"]), 1)

    def test_una_respuesta_sin_la_columna_de_huecos_no_se_rompe(self):
        """Una fila mas corta ---otra version de la consulta--- no debe tumbar
        la respuesta, que es el mismo cuidado que ya tenian `efectiva` y
        `hueco`."""
        from datetime import datetime, timezone
        t0 = datetime(2026, 9, 2, tzinfo=timezone.utc)
        t1 = datetime(2026, 9, 2, 0, 2, 10, tzinfo=timezone.utc)
        filas = [(2, 2604, 0.2, 7006.2, t0, t1, 40.0, 320.0, 0.0, 130.1, 0.1)]
        falsa, parche = _con(filas)
        with parche:
            r = api_sesion.listar_vueltas("f1_25:session:1")
        self.assertEqual(r["vueltas"][0]["huecos"], [])

    def test_el_umbral_de_la_consulta_y_el_de_la_lectura_son_el_mismo(self):
        """Escrito en dos sitios, tarde o temprano uno queda en otro numero."""
        import inspect
        fuente = inspect.getsource(api_sesion.listar_vueltas)
        self.assertIn('"%g seconds" % HUECO_MAXIMO_S', fuente)
        self.assertNotIn("interval '2 seconds'", fuente)


class MemoriaAcotadaTests(unittest.TestCase):
    """Una cache sin tope es una fuga de memoria con otro nombre.

    Este backend esta pensado para correr semanas seguidas en una Raspberry con
    258 sesiones en el catalogo. Guardar la respuesta de avisos de cada una que
    alguien abra ---sin soltar ninguna--- es exactamente la forma en que un
    proceso largo se queda sin memoria.
    """

    def setUp(self) -> None:
        api_sesion._AVISOS_CACHE.clear()

    def tearDown(self) -> None:
        api_sesion._AVISOS_CACHE.clear()

    def test_no_guarda_mas_del_tope(self) -> None:
        for i in range(api_sesion.AVISOS_EN_CACHE + 10):
            falsa, parche = _con([])
            with parche:
                api_sesion.avisos("f1_25:session:%d" % i)
        self.assertEqual(len(api_sesion._AVISOS_CACHE), api_sesion.AVISOS_EN_CACHE)

    def test_suelta_la_menos_usada_no_la_ultima(self) -> None:
        """Se descarta por desuso: la primera se conserva si se la sigue mirando."""
        for i in range(api_sesion.AVISOS_EN_CACHE):
            falsa, parche = _con([])
            with parche:
                api_sesion.avisos("f1_25:session:%d" % i)
        # Se vuelve a mirar la primera: deja de ser la mas vieja.
        falsa, parche = _con([])
        with parche:
            primera = api_sesion.avisos("f1_25:session:0")
        self.assertTrue(primera["de_cache"])

        falsa, parche = _con([])
        with parche:
            api_sesion.avisos("f1_25:session:nueva")

        claves = [c[0] for c in api_sesion._AVISOS_CACHE]
        self.assertIn("f1_25:session:0", claves)
        self.assertNotIn("f1_25:session:1", claves)

    def test_la_segunda_consulta_no_toca_la_base(self) -> None:
        falsa, parche = _con([])
        with parche:
            api_sesion.avisos("f1_25:session:7")
        consultas_primera = len(falsa.consultas)
        self.assertGreater(consultas_primera, 0)

        falsa2, parche2 = _con([])
        with parche2:
            segunda = api_sesion.avisos("f1_25:session:7")
        self.assertTrue(segunda["de_cache"])
        self.assertEqual(falsa2.consultas, [])


class RespuestasComprimidasTests(unittest.TestCase):
    """Lo que viaja son listas de numeros: la forma que mejor comprime.

    Se comprueba que el middleware este declarado, no que zlib funcione. Lo
    que puede romperse al editar es que alguien reordene los middlewares o
    saque este; el ahorro medido ---206.910 a 34.629 bytes sobre las ocho
    consultas de abrir una sesion--- depende de que siga puesto.
    """

    def test_la_aplicacion_declara_gzip(self) -> None:
        from fastapi.middleware.gzip import GZipMiddleware

        from backend.app import app

        clases = [m.cls for m in app.user_middleware]
        self.assertIn(GZipMiddleware, clases)

    def test_no_comprime_respuestas_diminutas(self) -> None:
        """Comprimir doscientos bytes cuesta mas de lo que ahorra."""
        from fastapi.middleware.gzip import GZipMiddleware

        from backend.app import app

        gzip = next(m for m in app.user_middleware if m.cls is GZipMiddleware)
        self.assertGreaterEqual(gzip.kwargs["minimum_size"], 512)


class SubmuestreoAcotadoTests(unittest.TestCase):
    """El limite de puntos tiene que ser un limite.

    `max(1, len // puntos)` no acota: la division entera da 1 para todo lo que
    este por debajo del doble, y ahi el paso queda en 1 y se devuelve todo. El
    peor caso son `2*puntos - 1` filas, donde se devolvia casi el doble de lo
    pedido y ademas se declaraba que no se habia reducido nada.
    """

    def test_division_exacta(self) -> None:
        filas = list(range(600))
        recorte, reducida = api_sesion._reducir(filas, 300)
        self.assertEqual(len(recorte), 300)
        self.assertTrue(reducida)

    def test_uno_mas_que_el_limite(self) -> None:
        filas = list(range(301))
        recorte, reducida = api_sesion._reducir(filas, 300)
        self.assertLessEqual(len(recorte), 300)
        self.assertTrue(reducida)

    def test_el_peor_caso_de_la_division_entera(self) -> None:
        """599 filas con puntos=300: la division entera daba paso 1."""

        filas = list(range(599))
        recorte, reducida = api_sesion._reducir(filas, 300)
        self.assertLessEqual(len(recorte), 300,
                             "se devolvieron %d filas para un limite de 300" % len(recorte))
        self.assertTrue(reducida, "se redujo y se declaraba que no")

    def test_justo_el_limite_no_se_reduce(self) -> None:
        filas = list(range(300))
        recorte, reducida = api_sesion._reducir(filas, 300)
        self.assertEqual(recorte, filas)
        self.assertFalse(reducida)

    def test_por_debajo_del_limite_no_se_toca(self) -> None:
        filas = list(range(17))
        recorte, reducida = api_sesion._reducir(filas, 300)
        self.assertEqual(recorte, filas)
        self.assertFalse(reducida)

    def test_los_dos_extremos_sobreviven_siempre(self) -> None:
        """Sin la ultima, la serie termina antes que el dato.

        El ultimo tramo de una vuelta es la frenada de meta: que no se dibuje
        no es un detalle de resolucion.
        """

        for total in (301, 599, 600, 601, 602, 1000, 1201, 5641):
            filas = list(range(total))
            recorte, _ = api_sesion._reducir(filas, 300)
            self.assertEqual(recorte[0], filas[0], "total=%d" % total)
            self.assertEqual(recorte[-1], filas[-1], "total=%d" % total)
            self.assertLessEqual(len(recorte), 300, "total=%d" % total)

    def test_conserva_el_orden(self) -> None:
        filas = list(range(1000))
        recorte, _ = api_sesion._reducir(filas, 300)
        self.assertEqual(recorte, sorted(recorte))


class ReducirNoPuedeBorrarUnCanalTests(unittest.TestCase):
    """Saltear filas es borrar señales cuando cada fila trae una sola.

    En el simulador un paquete publica todas sus magnitudes con el mismo sello y
    cada fila trae todas las columnas: saltear filas adelgaza. En un bus
    vehicular cada trama lleva lo suyo y llega cuando le toca, de modo que
    agrupando por instante exacto **cada fila tiene una sola señal**.

    Medido sobre `sample_28`: 6.158 filas, de las cuales 3.079 traen `speed` y
    estan exactamente en los indices pares. Con `paso` par sobrevivian todas y
    se borraban las de al lado; con `paso` impar sobrevivia la mitad; pidiendo
    las trece señales del bus, `speed` desaparecia entera. El tablero decia «sin
    dato en esta vuelta» sobre una sesion completa, y como el eje temporal se
    apoya en esa señal, los otros doce graficos se quedaban sin ventana.
    """

    @staticmethod
    def _bus(total: int, cuantas: int = 2) -> list:
        """Filas como las arma la consulta temporal: una señal por instante.

        `cuantas` señales intercaladas con regularidad, que es como publica un
        bus. La columna 0 es el instante y la 1 el vehiculo.
        """

        filas = []
        for i in range(total):
            valores = [None] * cuantas
            valores[i % cuantas] = float(i)
            filas.append((i, "veh", *valores))
        return filas

    def test_ninguna_senal_desaparece_sea_cual_sea_el_paso(self) -> None:
        for cuantas in (2, 3, 5, 13):
            filas = self._bus(6158, cuantas)
            for puntos in (300, 600, 800, 1000, 1200, 2000):
                recorte, _ = api_sesion._reducir(filas, puntos, (2, 2 + cuantas))
                for c in range(cuantas):
                    con = sum(1 for f in recorte if f[2 + c] is not None)
                    self.assertGreater(
                        con, 0,
                        "con %d señales y puntos=%d, la señal %d quedo en cero "
                        "muestras de %d filas" % (cuantas, puntos, c, len(filas)))

    def test_no_se_pierde_ninguna_muestra_cuando_el_tramo_es_corto(self) -> None:
        """Trece señales, 6.158 filas y 1.200 puntos: no se tira nada.

        El tramo son seis filas y cada señal aporta una de cada trece, de modo
        que ninguna aparece en todos los tramos. Pero cada señal tiene 474
        muestras en total y las 474 salen: reducir de 6.158 filas a 1.027 no le
        costo una sola muestra a ninguna. Es la diferencia entre plegar y
        saltear.
        """

        cuantas = 13
        filas = self._bus(6158, cuantas)
        recorte, _ = api_sesion._reducir(filas, 1200, (2, 2 + cuantas))
        self.assertLessEqual(len(recorte), 1200)
        for c in range(cuantas):
            tenia = sum(1 for f in filas if f[2 + c] is not None)
            quedan = sum(1 for f in recorte if f[2 + c] is not None)
            self.assertEqual(quedan, tenia,
                             "la señal %d tenia %d muestras y quedaron %d"
                             % (c, tenia, quedan))

    def test_con_tramos_largos_cada_senal_pierde_lo_mismo(self) -> None:
        """Cuando hay que tirar, se tira parejo y no una señal entera."""

        cuantas = 13
        filas = self._bus(6158, cuantas)
        recorte, _ = api_sesion._reducir(filas, 200, (2, 2 + cuantas))
        quedan = [sum(1 for f in recorte if f[2 + c] is not None)
                  for c in range(cuantas)]
        self.assertEqual(min(quedan), max(quedan),
                         "unas señales sobrevivieron mas que otras: %s" % quedan)

    def test_el_valor_plegado_es_el_primero_del_tramo(self) -> None:
        """Se pliega, no se promedia: lo que queda es una muestra medida."""

        filas = self._bus(600, 2)
        recorte, _ = api_sesion._reducir(filas, 100, (2, 4))
        # paso = 6: el primer tramo son las filas 0..5, con `speed` en 0, 2 y 4.
        self.assertEqual(recorte[0][2], 0.0)
        self.assertEqual(recorte[0][3], 1.0)
        self.assertEqual(recorte[1][2], 6.0)

    def test_el_instante_es_el_de_la_fila_que_abre_el_tramo(self) -> None:
        filas = self._bus(600, 2)
        recorte, _ = api_sesion._reducir(filas, 100, (2, 4))
        self.assertEqual(recorte[0][0], 0)
        self.assertEqual(recorte[1][0], 6)
        self.assertEqual([f[0] for f in recorte], sorted(f[0] for f in recorte))

    def test_el_ultimo_tramo_entra_entero(self) -> None:
        """La ultima muestra medida no se puede perder por el redondeo."""

        for total in (601, 999, 1201, 6158):
            filas = self._bus(total, 3)
            recorte, _ = api_sesion._reducir(filas, 300, (2, 5))
            self.assertLessEqual(len(recorte), 300, "total=%d" % total)
            ultimo = max(v for f in recorte for v in f[2:] if v is not None)
            self.assertGreaterEqual(
                ultimo, float(total - 3),
                "se perdio el final del tramo: total=%d" % total)

    def test_sin_plegables_no_cambia_lo_que_hacia(self) -> None:
        """El camino espacial no se toca: ahi cada fila trae todas sus columnas."""

        filas = list(range(1000))
        # Uno de cada cuatro, y la ultima fila repuesta: la regla de siempre.
        esperado = list(range(1000))[::4]
        esperado.append(999)
        self.assertEqual(api_sesion._reducir(filas, 300)[0], esperado)

    def test_por_debajo_del_limite_tampoco_pliega(self) -> None:
        filas = self._bus(120, 3)
        recorte, reducida = api_sesion._reducir(filas, 300, (2, 5))
        self.assertEqual(recorte, filas)
        self.assertFalse(reducida)


class SenalesAusentesRecordadasTests(unittest.TestCase):
    """Concluir que una senal no esta cuesta recorrer la sesion entera.

    Y esa conclusion no cambia: a una carrera guardada no se le agregan filas.
    Repetir el recorrido en cada consulta era el grueso de los 31,42 s que
    medimos el 2026-09-08 en `/contexto` de una sesion sin temperatura de pista
    ---y ese numero estaba justo por encima del corte de 30 s del navegador, de
    modo que la sesion no terminaba de abrirse nunca.
    """

    def setUp(self) -> None:
        api_sesion._AUSENTES_CACHE.clear()

    def tearDown(self) -> None:
        api_sesion._AUSENTES_CACHE.clear()

    def test_lo_ausente_se_recuerda_y_no_se_vuelve_a_buscar(self) -> None:
        falsa, parche = _con([])          # la base no devuelve ninguna senal
        with parche:
            api_sesion._ultimos_valores(falsa.cursor_obj, "f1_25_udp_simulation",
                                        "s1", ["air_temperature"])
        primera = len(falsa.consultas)
        self.assertGreater(primera, 0)

        falsa2, parche2 = _con([])
        with parche2:
            api_sesion._ultimos_valores(falsa2.cursor_obj, "f1_25_udp_simulation",
                                        "s1", ["air_temperature"])
        # La segunda hace menos consultas: no repite el recorrido sin acotar.
        self.assertLess(len(falsa2.consultas), primera,
                        "se volvio a recorrer la sesion para lo que ya se sabia ausente")

    def test_cada_sesion_recuerda_lo_suyo(self) -> None:
        falsa, parche = _con([])
        with parche:
            api_sesion._ultimos_valores(falsa.cursor_obj, "f1_25_udp_simulation",
                                        "s1", ["air_temperature"])
        # Otra sesion no hereda la ausencia: podria tener la senal.
        falsa2, parche2 = _con([])
        with parche2:
            api_sesion._ultimos_valores(falsa2.cursor_obj, "f1_25_udp_simulation",
                                        "s2", ["air_temperature"])
        self.assertGreater(len(falsa2.consultas), 0)

    def test_la_cache_de_ausentes_tiene_tope(self) -> None:
        for i in range(api_sesion.AUSENTES_EN_CACHE + 12):
            falsa, parche = _con([])
            with parche:
                api_sesion._ultimos_valores(falsa.cursor_obj, "f1_25_udp_simulation",
                                            "s%d" % i, ["air_temperature"])
        self.assertLessEqual(len(api_sesion._AUSENTES_CACHE),
                             api_sesion.AUSENTES_EN_CACHE)


class UnHuecoDiceSiElCocheSeMovio(unittest.TestCase):
    """Cuanto duro un hueco no dice si se perdio telemetria.

    EL DEFECTO, VISTO ANTES DE QUE MORDIERA. El tablero clasificaba un hueco
    **solo por su duracion**: menos de dos segundos eran «muestras que no
    llegaron» y mas, «el coche detenido o el juego fuera de pista». Sobre la
    captura de Barcelona esa lectura es correcta ---456 s con el coche parado---
    y sobre un corte de red de dos minutos con el coche dando vueltas es
    exactamente al reves.

    Lo que los separa no es cuanto duro: es **si el coche avanzo**. Detenido no
    avanza; dando vueltas avanza cientos de metros. El dato estaba en la base y
    la respuesta no lo traia.
    """

    def test_el_hueco_declara_cuantos_metros_avanzo_el_coche(self):
        crudos = [[1000.0, 1120.0, 3200.0]]
        h = api_sesion._huecos_legibles(crudos)[0]
        self.assertEqual(h["duracion_s"], 120.0)
        self.assertEqual(h["metros"], 3200.0)

    def test_un_coche_detenido_declara_cero(self):
        h = api_sesion._huecos_legibles([[1000.0, 1456.0, 0.0]])[0]
        self.assertEqual(h["metros"], 0.0)

    def test_cruzar_la_meta_cuenta_como_movimiento_y_no_como_retroceso(self):
        """La distancia de vuelta vuelve a cero al cruzar: la resta da negativa.

        Leerlo como «avanzo menos cero metros» diria que el coche estaba quieto
        justo cuando dio una vuelta entera. Se declara lo que se sabe ---que se
        movio--- sin inventar cuanto.
        """
        h = api_sesion._huecos_legibles([[1000.0, 1120.0, -6800.0]])[0]
        self.assertIsNone(h["metros"])
        self.assertTrue(h["se_movio"])

    def test_sin_distancia_no_se_afirma_nada(self):
        """`None` es «no se sabe» y no se puede leer como «estaba quieto»."""
        h = api_sesion._huecos_legibles([[1000.0, 1120.0, None]])[0]
        self.assertIsNone(h["metros"])
        self.assertIsNone(h["se_movio"])

    def test_un_hueco_viejo_sin_la_tercera_cifra_no_rompe(self):
        """Las respuestas guardadas de antes traen pares, no ternas."""
        h = api_sesion._huecos_legibles([[1000.0, 1120.0]])[0]
        self.assertEqual(h["duracion_s"], 120.0)
        self.assertIsNone(h["metros"])

