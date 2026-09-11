# -*- coding: utf-8 -*-
"""Pruebas del catalogo de sesiones persistidas."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from backend import catalogo_sesiones


class ConexionFalsa:
    def __init__(self, filas=None, una=None):
        self.filas = filas if filas is not None else []
        self.una = una
        self.consultas: list[str] = []
        self.cursor_obj = MagicMock()
        self.cursor_obj.execute.side_effect = lambda c, p=None: self.consultas.append(c)
        self.cursor_obj.fetchall.side_effect = lambda: list(self.filas)
        self.cursor_obj.fetchone.side_effect = lambda: self.una

    def cursor(self):
        c = MagicMock()
        c.__enter__ = lambda *_: self.cursor_obj
        c.__exit__ = lambda *_: False
        return c

    def commit(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _con(filas=None, una=None):
    f = ConexionFalsa(filas, una)
    return f, patch("backend.catalogo_sesiones.db.obtener_conexion", return_value=f)


T0 = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 9, 6, 12, 30, tzinfo=timezone.utc)


class ListarTests(unittest.TestCase):
    def setUp(self) -> None:
        catalogo_sesiones._RECONSTRUYENDO = False

    def test_arma_la_ficha_de_cada_sesion(self) -> None:
        filas = [("f1_25:session:1", "f1_25_udp_simulation", 5641702, 113, 1, T0, T1, T1)]
        falsa, parche = _con(filas)
        with parche:
            r = catalogo_sesiones.listar()
        s = r["sesiones"][0]
        self.assertEqual(s["session_id"], "f1_25:session:1")
        self.assertEqual(s["filas"], 5641702)
        self.assertEqual(s["duracion_s"], 1800.0)
        self.assertTrue(s["fuente_declarada"])
        self.assertFalse(r["calculando"])

    def test_una_sesion_sin_fuente_declarada_igual_figura(self) -> None:
        """Prohibir la fuente nula habria dejado fuera del catalogo justo lo que
        el catalogo existe para hacer descubrible."""
        filas = [("session_01", None, 43, 11, 1, T0, T1, T1)]
        falsa, parche = _con(filas)
        with parche:
            r = catalogo_sesiones.listar()
        s = r["sesiones"][0]
        self.assertIsNone(s["fuente"])
        self.assertFalse(s["fuente_declarada"])

    def test_vacio_y_calculando_no_es_lo_mismo_que_vacio_y_listo(self) -> None:
        """Confundirlos haria concluir que no hay nada guardado."""
        falsa, parche = _con([])
        with parche, patch("backend.catalogo_sesiones.pedir_reconstruccion",
                           return_value=True) as pedir:
            r = catalogo_sesiones.listar()
        self.assertEqual(r["sesiones"], [])
        self.assertTrue(r["calculando"])
        self.assertIn("se esta calculando", r["vacio_porque"])
        pedir.assert_called_once()

    def test_filtra_por_fuente_en_la_consulta_y_no_en_memoria(self) -> None:
        falsa, parche = _con([])
        with parche, patch("backend.catalogo_sesiones.pedir_reconstruccion",
                           return_value=False):
            catalogo_sesiones.listar(fuente="can_real_replay")
        self.assertTrue(any("WHERE source_type = %s" in c for c in falsa.consultas))


class ReconstruccionTests(unittest.TestCase):
    def setUp(self) -> None:
        catalogo_sesiones._RECONSTRUYENDO = False

    def test_una_sola_pasada_sobre_la_tabla(self) -> None:
        """Una consulta por sesion serian doscientas cincuenta y ocho consultas."""
        filas = [("f1_25_udp_simulation", "s1", 10, 3, 1, T0, T1),
                 ("can_real_replay", "s2", 20, 5, 1, T0, T1)]
        falsa, parche = _con(filas)
        with parche:
            n = catalogo_sesiones.reconstruir()
        self.assertEqual(n, 2)
        recuentos = [c for c in falsa.consultas if "GROUP BY source_type, session_id" in c]
        self.assertEqual(len(recuentos), 1)

    def test_agrupa_por_las_columnas_de_segmentacion(self) -> None:
        """Agrupar por otra columna obligaria a descomprimir la tabla entera."""
        self.assertIn("GROUP BY source_type, session_id", catalogo_sesiones._RECUENTO)

    def test_no_lanza_dos_reconstrucciones_a_la_vez(self) -> None:
        with patch("backend.catalogo_sesiones.threading.Thread") as hilo:
            primera = catalogo_sesiones.pedir_reconstruccion()
            segunda = catalogo_sesiones.pedir_reconstruccion()
        self.assertTrue(primera)
        self.assertFalse(segunda)
        self.assertEqual(hilo.call_count, 1)
        catalogo_sesiones._RECONSTRUYENDO = False


class EstadoTests(unittest.TestCase):
    def test_declara_si_esta_vacio(self) -> None:
        falsa, parche = _con(una=(0, None))
        with parche:
            e = catalogo_sesiones.estado()
        self.assertTrue(e["vacio"])
        self.assertEqual(e["sesiones"], 0)



class RefrescoPuntualTests(unittest.TestCase):
    """Actualizar una sesion en vez de rehacer el catalogo entero."""

    def test_acota_por_session_id_que_es_columna_de_segmentacion(self) -> None:
        """Sin acotar asi, el recuento descomprimiria la tabla entera."""
        self.assertIn("WHERE session_id = %s", catalogo_sesiones._RECUENTO_DE_UNA)
        self.assertNotIn("GROUP BY source_type, session_id\n\"\"\"",
                         catalogo_sesiones._RECUENTO_DE_UNA.replace(
                             "GROUP BY source_type, session_id", "", 1))

    def test_registra_la_sesion_con_upsert(self) -> None:
        filas = [("f1_25_udp_simulation", "s1", 100, 5, 1, T0, T1)]
        falsa, parche = _con(filas)
        with parche:
            ok = catalogo_sesiones.refrescar_sesion("s1")
        self.assertTrue(ok)
        self.assertTrue(any("ON CONFLICT (session_id) DO UPDATE" in c
                            for c in falsa.consultas))

    def test_una_sesion_sin_filas_se_borra_en_vez_de_quedar_vieja(self) -> None:
        """Dejar los numeros de antes seria afirmar algo que ya no es cierto."""
        falsa, parche = _con([])
        with parche:
            ok = catalogo_sesiones.refrescar_sesion("se-borro")
        self.assertFalse(ok)
        self.assertTrue(any("DELETE FROM sesiones_catalogo WHERE session_id" in c
                            for c in falsa.consultas))

    def test_sin_identificador_no_recorre_la_tabla_entera(self) -> None:
        """Una carga que no declara su sesion no justifica 149 segundos."""
        with patch("backend.catalogo_sesiones.threading.Thread") as hilo:
            catalogo_sesiones.refrescar_en_segundo_plano(None)
        hilo.assert_not_called()

    def test_con_identificador_refresca_por_detras(self) -> None:
        with patch("backend.catalogo_sesiones.threading.Thread") as hilo:
            catalogo_sesiones.refrescar_en_segundo_plano("s1")
        hilo.assert_called_once()

if __name__ == "__main__":
    unittest.main()


class ExtremosDeUnaSesionTests(unittest.TestCase):
    """Los dos extremos salen del catalogo, y salen los dos.

    `rango_de` devolvia solo el comienzo porque era lo unico que hacia falta
    para alinear el recorrido del bus. `/contexto` necesita tambien el final:
    devolver `None` ahi lo dejaba sin tope y la busqueda por ventana no podia
    armarse, de modo que todo caia en el recorrido completo ---que es justo lo
    que este atajo existe para evitar---.
    """

    class _Cursor:
        def __init__(self, filas):
            self.filas = list(filas)
            self.consultas = []

        def execute(self, consulta, parametros=None):
            self.consultas.append(consulta)

        def fetchone(self):
            return self.filas.pop(0) if self.filas else None

    def test_devuelve_los_dos_extremos_del_catalogo(self) -> None:
        from datetime import datetime, timezone
        a = datetime(2025, 7, 6, 13, 7, 43, tzinfo=timezone.utc)
        b = datetime(2025, 7, 6, 15, 42, 53, tzinfo=timezone.utc)
        cur = self._Cursor([(a, b)])
        desde, hasta = catalogo_sesiones.extremos_de(
            "openf1:session:9947", "openf1_historical_replay", cur)
        self.assertEqual(desde, a.isoformat())
        self.assertEqual(hasta, b.isoformat(),
                         "el extremo de arriba se perdio: sin tope no hay ventana")
        self.assertEqual(len(cur.consultas), 1,
                         "se consulto la tabla grande teniendo la fila del catalogo")

    def test_una_sesion_sin_catalogar_se_mide(self) -> None:
        from datetime import datetime, timezone
        a = datetime(2026, 9, 9, tzinfo=timezone.utc)
        cur = self._Cursor([None, (a, a)])
        desde, hasta = catalogo_sesiones.extremos_de("x", "can_real_replay", cur)
        self.assertEqual(desde, a.isoformat())
        self.assertEqual(hasta, a.isoformat())
        self.assertEqual(len(cur.consultas), 2)

    def test_una_sesion_que_no_esta_en_ningun_lado_no_inventa_extremos(self) -> None:
        cur = self._Cursor([None, None])
        self.assertEqual(
            catalogo_sesiones.extremos_de("x", "can_real_replay", cur), (None, None))

    def test_el_comienzo_sigue_saliendo_por_donde_salia(self) -> None:
        """`rango_de` es ahora la primera mitad de esto y no puede cambiar."""
        from datetime import datetime, timezone
        a = datetime(2025, 7, 6, tzinfo=timezone.utc)
        cur = self._Cursor([(a, a)])
        self.assertEqual(
            catalogo_sesiones.extremos_de("s", "f", cur)[0], a.isoformat())
