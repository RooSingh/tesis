# -*- coding: utf-8 -*-
"""La fase acota las filas que se devuelven, no solo el calculo de los limites.

EL DEFECTO QUE ESTAS PRUEBAS CUIDAN.

`/posiciones` resolvia los limites de la fase, los usaba para acotar la ventana
de la vuelta y despues **seleccionaba las distancias sin volver a filtrar**.
Como el reloj del juego se reinicia en la largada, el `timestamp` derivado
retrocede con el y **la formacion y la carrera se solapan en UTC a proposito**:
acotar por ventana no implica que las filas de esa ventana sean de esa fase.

Medido sobre Spa, adquisicion original, fase 3, antes de corregirlo: la vuelta 1
tenia 62 retrocesos ---el peor de 1.591,4 m--- y la vuelta 2 saltaba de 0,2 a
5.676,2 m entre dos cubos seguidos. Despues: cero retrocesos en las dos.

CRITERIO. Estas pruebas no necesitan la base. Lo que comprueban es **que
consulta arma este modulo**: que la condicion de fase este en la consulta que
devuelve el dato, con el reloj de captura y no con el UTC. Que PostgreSQL sepa
filtrar no esta en discusion.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from backend import api_sesion


def _t(segundos: float) -> datetime:
    return datetime(2026, 9, 5, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=segundos)


class CursorQueAnota:
    """Devuelve lo que se le indique y recuerda cada consulta con su parametro."""

    def __init__(self, respuestas: list[list]):
        self.respuestas = list(respuestas)
        self.consultas: list[tuple[str, tuple]] = []
        self._ultimo: list = []

    def execute(self, consulta, parametros=None):
        self.consultas.append((consulta, tuple(parametros or ())))
        self._ultimo = self.respuestas.pop(0) if self.respuestas else []

    def fetchall(self):
        return list(self._ultimo)

    def fetchone(self):
        return self._ultimo[0] if self._ultimo else None


class ConexionQueAnota:
    def __init__(self, cursor):
        self.cursor_obj = cursor

    def cursor(self):
        c = MagicMock()
        c.__enter__ = lambda *_: self.cursor_obj
        c.__exit__ = lambda *_: False
        return c

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


# ---------------------------------------------------------------------------
# Los bordes de una fase
# ---------------------------------------------------------------------------

class BordesDeFaseTests(unittest.TestCase):
    """Medio abiertos, y abiertos en los extremos."""

    def test_el_ultimo_tramo_no_termina_en_la_ultima_muestra_de_lap_number(self) -> None:
        """El caso que costo una coordenada valida.

        En el cuadro 64.494 de Spa, `lap_number` llega con desplazamiento
        3.030.179.999 y la posicion del mismo cuadro 757 microsegundos despues.
        Un limite superior tomado del ultimo `lap_number` la deja afuera.
        """
        fases = api_sesion._armar_fases([100, 500, 3030179999])
        self.assertIsNone(fases[-1]["limite_hasta_us"],
                          "el ultimo tramo se cierra en la ultima muestra de una senal")
        # Y lo medido se conserva aparte, para poder decir cuanto dura.
        self.assertEqual(fases[-1]["hasta_us"], 3030179999)

    def test_el_primer_tramo_empieza_abierto(self) -> None:
        fases = api_sesion._armar_fases([100, 500, 900])
        self.assertIsNone(fases[0]["limite_desde_us"])
        self.assertEqual(fases[0]["desde_us"], 100)

    def test_los_tramos_del_medio_se_tocan_sin_repetir(self) -> None:
        """Medio abiertos: el final de uno es el principio del siguiente."""
        fases = api_sesion._armar_fases([0, 200, 700, 900])
        self.assertEqual(fases[0]["limite_hasta_us"], fases[1]["limite_desde_us"])
        self.assertEqual(fases[1]["limite_hasta_us"], fases[2]["limite_desde_us"])

    def test_una_sola_fase_no_acota_por_ningun_lado(self) -> None:
        fases = api_sesion._armar_fases([10, 900])
        self.assertEqual(len(fases), 1)
        self.assertIsNone(fases[0]["limite_desde_us"])
        self.assertIsNone(fases[0]["limite_hasta_us"])


class ClausulaDeTramoTests(unittest.TestCase):
    """La condicion que acota, escrita una sola vez para todas las consultas."""

    def test_es_medio_abierta(self) -> None:
        cond, par = api_sesion._clausula_de_tramo(100, 900)
        self.assertIn(">= %s", cond)
        self.assertIn("< %s", cond)
        self.assertNotIn("BETWEEN", cond)
        self.assertEqual(par, [100, 900])

    def test_usa_el_reloj_de_captura_y_no_el_utc(self) -> None:
        """En UTC no se puede: la formacion y la carrera se solapan."""
        cond, _ = api_sesion._clausula_de_tramo(1, 2)
        self.assertIn("desplazamiento_captura_us", cond)
        self.assertIn("metadata", cond)
        self.assertNotIn("timestamp", cond)

    def test_un_extremo_abierto_no_emite_su_lado(self) -> None:
        cond, par = api_sesion._clausula_de_tramo(100, None)
        self.assertIn(">= %s", cond)
        self.assertNotIn("< %s", cond)
        self.assertEqual(par, [100])

    def test_sin_fase_no_emite_nada(self) -> None:
        """Por omision la consulta queda igual que antes de que esto existiera."""
        self.assertEqual(api_sesion._clausula_de_tramo(None, None), ("", []))


# ---------------------------------------------------------------------------
# Que la condicion llegue a la consulta que devuelve el dato
# ---------------------------------------------------------------------------

class LaFaseLlegaALasFilasTests(unittest.TestCase):
    """Fases que se solapan en UTC: la unica defensa es el reloj de captura."""

    #: Dos fases cuyas ventanas UTC **se pisan**, como en Spa: la formacion
    #: ocupa 00:00-00:03 y la carrera vuelve a empezar en 00:00 porque el reloj
    #: del juego se reinicio. En captura no se pisan: 0-200 y 200-3000.
    FASES = [
        {"orden": 1, "desde_us": 0, "hasta_us": 200,
         "limite_desde_us": None, "limite_hasta_us": 200,
         "duracion_de_captura_s": 0.0002, "reloj_del_juego_reinicia_al_entrar": False},
        {"orden": 2, "desde_us": 200, "hasta_us": 3000,
         "limite_desde_us": 200, "limite_hasta_us": None,
         "duracion_de_captura_s": 0.0028, "reloj_del_juego_reinicia_al_entrar": True},
    ]

    def _correr_posiciones(self, cursor):
        with patch.object(api_sesion.db, "obtener_conexion",
                          return_value=ConexionQueAnota(cursor)), \
             patch.object(api_sesion, "_ventana_de_alcance",
                          return_value=(_t(0).isoformat(), _t(180).isoformat())), \
             patch.object(api_sesion, "_fases_de", return_value=self.FASES):
            return api_sesion.posiciones_en_pista(
                "f1_25:session:1", vuelta=2, puntos=4,
                adquisicion="original", fase=2)

    def test_la_consulta_final_de_posiciones_lleva_la_fase(self) -> None:
        cursor = CursorQueAnota([
            [(_t(10), _t(70))],                       # ventana de la vuelta
            [("car:0", 1, 10.0, _t(10)),              # las filas del dato
             ("car:0", 2, 40.0, _t(25))],
        ])
        self._correr_posiciones(cursor)
        final = cursor.consultas[-1]
        self.assertIn("width_bucket", final[0], "no es la consulta que devuelve el dato")
        self.assertIn("desplazamiento_captura_us", final[0],
                      "la consulta que devuelve las distancias no acota por fase")
        self.assertIn(200, final[1], "no viaja el limite inferior de la fase 2")

    def test_el_limite_superior_abierto_no_viaja(self) -> None:
        """La ultima fase llega hasta donde llegue la adquisicion."""
        cursor = CursorQueAnota([[(_t(10), _t(70))], []])
        self._correr_posiciones(cursor)
        final = cursor.consultas[-1]
        # Un predicado por cada extremo acotado. El nombre de la columna
        # aparece dos veces en cada uno ---la columna y el metadato--- asi que
        # se cuenta el comienzo del COALESCE, que va una vez por predicado.
        self.assertEqual(final[0].count("COALESCE(desplazamiento_captura_us"), 1,
                         "se emitio un limite superior que deberia quedar abierto")

    def test_la_ventana_de_la_vuelta_tambien_se_acota(self) -> None:
        cursor = CursorQueAnota([[(_t(10), _t(70))], []])
        self._correr_posiciones(cursor)
        ventana = cursor.consultas[0]
        self.assertIn("lap_number", ventana[0])
        self.assertIn("desplazamiento_captura_us", ventana[0],
                      "la ventana de la vuelta se calcula sin acotar por fase")

    def test_sin_fase_la_consulta_no_cambia(self) -> None:
        cursor = CursorQueAnota([[(_t(10), _t(70))], []])
        with patch.object(api_sesion.db, "obtener_conexion",
                          return_value=ConexionQueAnota(cursor)), \
             patch.object(api_sesion, "_ventana_de_alcance", return_value=None), \
             patch.object(api_sesion, "_fases_de", return_value=self.FASES):
            api_sesion.posiciones_en_pista("f1_25:session:1", vuelta=1, puntos=4)
        self.assertNotIn("desplazamiento_captura_us", cursor.consultas[-1][0])

    def test_el_trazado_aplica_la_fase_y_no_solo_la_acepta(self) -> None:
        """Declaraba `fase` en su firma y devolvia la geometria sin filtrar."""
        cursor = CursorQueAnota([[
            (0.0, 0.0, 1.0, 0.0, 3.0), (10.0, 0.0, 1.0, 100.0, 3.0),
            (10.0, 10.0, 1.0, 200.0, 3.0), (0.0, 0.0, 1.0, 300.0, 3.0),
        ]])
        with patch.object(api_sesion.db, "obtener_conexion",
                          return_value=ConexionQueAnota(cursor)), \
             patch.object(api_sesion, "_ventana_de_alcance", return_value=None), \
             patch.object(api_sesion, "_fases_de", return_value=self.FASES):
            api_sesion.trazado("f1_25:session:1", puntos=50,
                               adquisicion="original", fase=2)
        self.assertIn("desplazamiento_captura_us", cursor.consultas[0][0],
                      "el trazado sigue sin aplicar la fase")


# ---------------------------------------------------------------------------
# Que vuelta dibuja el circuito
# ---------------------------------------------------------------------------

class VueltaDelTrazadoTests(unittest.TestCase):
    """La que cierra, no la que tiene mas muestras: esa es la mas lenta."""

    @staticmethod
    def _lazo(n: int, cierra: float, d0: float = 0.0, d1: float = 7000.0) -> list:
        """Un cuadrado que vuelve a su origen con `cierra` metros de sobra."""
        filas = []
        for i in range(n):
            u = i / (n - 1)
            filas.append((u * 10.0, 0.0, 0.0, d0 + u * (d1 - d0), 1.0))
        # El ultimo punto queda a `cierra` del primero.
        filas[-1] = (cierra, 0.0, 0.0, d1, 1.0)
        return filas

    def test_gana_la_que_cierra_aunque_tenga_menos_muestras(self) -> None:
        por_vuelta = {
            13.0: self._lazo(2809, cierra=14.19),   # la de la parada en boxes
            20.0: self._lazo(2534, cierra=1.49),
        }
        elegida = api_sesion._vuelta_que_mejor_dibuja(por_vuelta)
        self.assertEqual(len(elegida), 2534)

    def test_se_descarta_media_vuelta_aunque_cierre_perfecto(self) -> None:
        por_vuelta = {
            1.0: self._lazo(500, cierra=0.0, d0=0.0, d1=2000.0),   # un tercio
            7.0: self._lazo(500, cierra=5.0, d0=0.0, d1=7000.0),
        }
        elegida = api_sesion._vuelta_que_mejor_dibuja(por_vuelta)
        self.assertAlmostEqual(elegida[-1][3], 7000.0)

    def test_sin_distancias_no_se_rompe(self) -> None:
        f = [(0.0, 0.0, None, None, 1.0), (1.0, 1.0, None, None, 1.0)]
        self.assertEqual(api_sesion._vuelta_que_mejor_dibuja({1.0: f}), f)


# ---------------------------------------------------------------------------
# El cierre de vuelta
# ---------------------------------------------------------------------------

class DescensosExplicadosTests(unittest.TestCase):
    """Una distancia que baja se explica; no se recorta ni se fuerza a crecer."""

    def _con_acumulada(self, filas):
        cursor = CursorQueAnota([filas])
        return patch.object(api_sesion.db, "obtener_conexion",
                            return_value=ConexionQueAnota(cursor))

    def test_el_cruce_de_meta_se_reconoce_por_la_distancia_de_sesion(self) -> None:
        """Vuelta 22 de Spa: la de vuelta se reinicia, la de sesion sigue."""
        vehiculos = {"car:0": [6948.5, 6978.0, 2.1]}
        sellos = {"car:0": [_t(1), _t(2), _t(3)]}
        with self._con_acumulada([("car:0", _t(2), 154134.5),
                                  ("car:0", _t(3), 154166.1)]):
            d = api_sesion._explicar_descensos("f", "s", vehiculos, sellos)
        self.assertEqual(len(d), 1)
        self.assertTrue(d[0]["session_distance_crece"])
        self.assertIn("la vuelta se cierra", d[0]["motivo"])
        self.assertEqual(d[0]["distancia_de_vuelta_m"], [6978.0, 2.1])

    def test_un_descenso_sin_respaldo_se_declara_sin_explicar(self) -> None:
        """No se lo esconde: si la de sesion no crece, no hay cruce de meta."""
        vehiculos = {"car:0": [100.0, 20.0]}
        sellos = {"car:0": [_t(1), _t(2)]}
        with self._con_acumulada([("car:0", _t(1), 5000.0),
                                  ("car:0", _t(2), 4990.0)]):
            d = api_sesion._explicar_descensos("f", "s", vehiculos, sellos)
        self.assertFalse(d[0]["session_distance_crece"])
        self.assertIn("sin explicar", d[0]["motivo"])

    def test_una_vuelta_sin_descensos_no_consulta_nada(self) -> None:
        cursor = CursorQueAnota([])
        with patch.object(api_sesion.db, "obtener_conexion",
                          return_value=ConexionQueAnota(cursor)):
            d = api_sesion._explicar_descensos(
                "f", "s", {"car:0": [1.0, 2.0, 3.0]}, {"car:0": [_t(1), _t(2), _t(3)]})
        self.assertEqual(d, [])
        self.assertEqual(cursor.consultas, [])

    def test_los_huecos_no_cuentan_como_descenso(self) -> None:
        vehiculos = {"car:0": [10.0, None, 40.0]}
        sellos = {"car:0": [_t(1), None, _t(3)]}
        with patch.object(api_sesion.db, "obtener_conexion",
                          return_value=ConexionQueAnota(CursorQueAnota([]))):
            self.assertEqual(
                api_sesion._explicar_descensos("f", "s", vehiculos, sellos), [])


# ---------------------------------------------------------------------------
# El contrato temporal
# ---------------------------------------------------------------------------

class ContratoTemporalTests(unittest.TestCase):
    """Se dice cuando se midio cada punto, en vez de suponerlo."""

    def _respuesta(self):
        cursor = CursorQueAnota([
            [(_t(0), _t(4))],
            [("car:0", 1, 0.0, _t(0)),
             ("car:0", 2, 55.0, _t(1.05)),
             ("car:0", 5, 220.0, _t(4))],
        ])
        with patch.object(api_sesion.db, "obtener_conexion",
                          return_value=ConexionQueAnota(cursor)), \
             patch.object(api_sesion, "_ventana_de_alcance", return_value=None), \
             patch.object(api_sesion, "_fases_de", return_value=[]):
            return api_sesion.posiciones_en_pista("f1_25:session:1", vuelta=1, puntos=4)

    def test_no_queda_un_hueco_artificial_al_principio(self) -> None:
        """`width_bucket` empieza en 1 y el indice 0 no se usaba nunca."""
        d = self._respuesta()
        self.assertEqual(len(d["vehiculos"]["car:0"]), 5)   # puntos + 1
        self.assertEqual(d["vehiculos"]["car:0"][0], 0.0)

    def test_el_instante_final_exacto_entra_en_el_ultimo_indice(self) -> None:
        d = self._respuesta()
        self.assertEqual(d["vehiculos"]["car:0"][4], 220.0)

    def test_se_devuelve_cuando_se_midio_cada_punto(self) -> None:
        """Sin esto no queda otra que suponerlos equiespaciados, y no lo estan.

        Medido sobre Spa, vueltas 3 a 21: suponer la rejilla pareja corre cada
        punto 24,9 ms de mediana y hasta 66,6 ms, que a 55,3 m/s son 1,4 y
        3,7 m de pista.
        """
        d = self._respuesta()
        self.assertEqual(d["instantes_ms"]["car:0"][0], 0.0)
        self.assertEqual(d["instantes_ms"]["car:0"][1], 1050.0)
        self.assertIsNone(d["instantes_ms"]["car:0"][2])
        self.assertEqual(d["intervalo_ms"], 1000.0)


if __name__ == "__main__":
    unittest.main()
