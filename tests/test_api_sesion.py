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
        self.assertIn("odometro", detalle)
        self.assertIn("can_real_replay", detalle)
        self.assertNotIn("OpenF1", detalle)
        self.assertNotIn("83 m", detalle)

    def test_la_fuente_deportiva_sigue_explicando_sus_huecos(self) -> None:
        with self.assertRaises(HTTPException) as caso:
            api_sesion.series_por_distancia("9939", senales="speed")
        detalle = caso.exception.detail
        self.assertIn("83 m", detalle)
        self.assertNotIn("odometro", detalle)

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
        self.assertIn("odometro", r["motivo"])

    def test_las_posiciones_tambien(self) -> None:
        with self.assertRaises(HTTPException) as caso:
            api_sesion.posiciones_en_pista("can:segmento:sample_01", vuelta=1)
        self.assertIn("odometro", caso.exception.detail)

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
        self.assertIn("83 m", r["motivo"])

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
    """Tres de los cinco campos son codigos de la especificacion del juego que
    el trabajo no cita. Devolverlos como si fueran valores legibles pondria una
    anotacion sin fuente donde hoy hay una medicion."""

    def test_declara_cuales_no_estan_decodificados(self):
        sin = [c for c, m in api_sesion.UNIDADES_PUESTA_A_PUNTO.items()
               if not m["decodificado"]]
        self.assertEqual(sorted(sin),
                         ["compuesto", "mezcla_de_combustible", "modo_de_despliegue_ers"])

    def test_los_decodificados_llevan_unidad_real(self):
        self.assertEqual(
            api_sesion.UNIDADES_PUESTA_A_PUNTO["sesgo_de_freno_pct"]["unidad"], "%")
        self.assertEqual(
            api_sesion.UNIDADES_PUESTA_A_PUNTO["edad_del_neumatico_vueltas"]["unidad"],
            "vueltas")

    def test_cada_campo_del_catalogo_tiene_unidad(self):
        self.assertEqual(sorted(api_sesion.CANALES_PUESTA_A_PUNTO),
                         sorted(api_sesion.UNIDADES_PUESTA_A_PUNTO))


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
