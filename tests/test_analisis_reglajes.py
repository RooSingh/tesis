# -*- coding: utf-8 -*-
"""Los reglajes de un circuito, puestos uno al lado del otro.

POR QUE ESTE MODULO NO ES UN RECOMENDADOR, y esta escrito aca porque es la
decision que gobierna todo lo demas. Se midio antes de escribirlo, sobre las
catorce sesiones con reglaje de la base (2026-09-13): en los tres circuitos con
mas de una ---Spielberg con tres, Baku y Shanghai con dos--- los veintitres ejes
coinciden. Lo unico que cambia es el combustible, que lo impone el modo.

De modo que lo que se publica es la comparacion y su lectura, y la lectura mas
util con estos datos es la negativa: **si el reglaje no cambio, la diferencia de
tiempo no es del reglaje**.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.analisis import reglajes


def _proc(circuito, tipo="Contrarreloj", familia="contrarreloj"):
    return {"circuito": circuito, "tipo_sesion_nombre": tipo,
            "familia_de_sesion": familia, "parc_ferme": "activadas",
            "capturado_utc": "2026-09-12T22:54:38+00:00"}


#: Los veintitres ejes, reducidos a los que hacen falta para la prueba. El
#: modulo no exige la lista completa: compara los que las dos declaren.
BASE = {"aleron_delantero": 3, "aleron_trasero": 1, "presion_de_freno_pct": 95.0,
        "combustible_inicial_kg": 10.0}


class ComparacionDeReglajes(unittest.TestCase):
    def _comparar(self, propia, otras, valores, mejores=None, asentadas=None):
        """Arma la comparacion con el circuito y los valores que se le digan."""

        todas = [propia] + otras
        procedencias = {s: _proc(c) for s, c in valores["circuitos"].items()}

        def valores_de(sesion, vehiculo):
            return (valores["reglajes"][sesion],
                    (asentadas or {}).get(sesion, True))

        def vehiculo_de(sesion):
            return sesion + ":car:0"

        def mejor(sesion, vehiculo):
            return (mejores or {}).get(sesion, (None, 0))

        with patch.object(reglajes, "sesiones_con_reglaje", return_value=todas), \
             patch.object(reglajes.procedencia_sesiones, "de",
                          side_effect=lambda s: procedencias.get(s)), \
             patch.object(reglajes, "_mejor_vuelta", side_effect=mejor):
            return reglajes.comparar(propia, valores_de, vehiculo_de).como_dict()

    def test_el_caso_medido_el_reglaje_no_cambia_y_eso_se_dice(self) -> None:
        """LA LECTURA QUE VALE ES LA NEGATIVA, y es la que los datos sostienen.

        Descartar una hipotesis entera ---«no fue el reglaje»--- es mas de lo
        que hace una recomendacion inventada sobre datos que no varian.
        """
        r = self._comparar("s1", ["s2", "s3"], {
            "circuitos": {"s1": "spielberg", "s2": "spielberg", "s3": "spielberg"},
            "reglajes": {"s1": dict(BASE), "s2": dict(BASE), "s3": dict(BASE)},
        })
        self.assertEqual(len(r["sesiones"]), 3)
        self.assertEqual([s["cuantos_difieren"] for s in r["sesiones"]], [0, 0, 0])
        self.assertIn("no es del reglaje", r["lectura"])

    def test_el_combustible_no_cuenta_como_reglaje_cambiado(self) -> None:
        """Lo impone el modo, no lo elige quien arma el auto.

        Medido: 10 kg en contrarreloj, 11 y 14 en carrera. Contarlo diria
        «cambiaste el reglaje» cuando lo unico que cambio fue el modo de juego.
        """
        r = self._comparar("s1", ["s2"], {
            "circuitos": {"s1": "spielberg", "s2": "spielberg"},
            "reglajes": {"s1": dict(BASE),
                         "s2": dict(BASE, combustible_inicial_kg=11.0)},
        })
        otra = r["sesiones"][1]
        self.assertEqual(otra["cuantos_difieren"], 0,
                         "el combustible se contó como un cambio de reglaje")
        self.assertEqual(len(otra["difiere_en"]), 1, "y tampoco se escondió")
        self.assertTrue(otra["difiere_en"][0]["lo_impone_el_modo"])
        self.assertIn("no es del reglaje", r["lectura"])

    def test_un_eje_que_si_cambia_se_nombra(self) -> None:
        r = self._comparar("s1", ["s2"], {
            "circuitos": {"s1": "baku", "s2": "baku"},
            "reglajes": {"s1": dict(BASE), "s2": dict(BASE, aleron_trasero=6)},
        })
        otra = r["sesiones"][1]
        self.assertEqual(otra["cuantos_difieren"], 1)
        self.assertEqual(otra["difiere_en"], [{
            "clave": "aleron_trasero", "referencia": 1, "aplicado": 6,
            "diferencia": 5, "lo_impone_el_modo": False}])
        self.assertIn("aleron_trasero", r["lectura"])

    def test_la_referencia_es_la_sesion_que_se_esta_mirando(self) -> None:
        """Y no la mas vieja ni la mas larga.

        El panel acompana a una sesion abierta: comparar contra otra obligaria a
        leer al reves lo que la pantalla muestra al derecho.
        """
        r = self._comparar("s2", ["s1", "s3"], {
            "circuitos": {"s1": "baku", "s2": "baku", "s3": "baku"},
            "reglajes": {"s1": dict(BASE), "s2": dict(BASE, aleron_trasero=6),
                         "s3": dict(BASE)},
        })
        self.assertEqual(r["referencia"], "s2")
        self.assertEqual(r["sesiones"][0]["session_id"], "s2")
        # Los otros dos se apartan de s2, no al reves.
        self.assertEqual(r["sesiones"][1]["difiere_en"][0]["referencia"], 6)
        self.assertEqual(r["sesiones"][1]["difiere_en"][0]["aplicado"], 1)

    def test_otro_circuito_no_entra_en_la_comparacion(self) -> None:
        """Un reglaje de Monza no dice nada sobre uno de Monaco."""

        r = self._comparar("s1", ["s2"], {
            "circuitos": {"s1": "baku", "s2": "monte-carlo"},
            "reglajes": {"s1": dict(BASE), "s2": dict(BASE, aleron_trasero=9)},
        })
        self.assertEqual([s["session_id"] for s in r["sesiones"]], ["s1"])
        self.assertIn("no hay otra sesión", r["lectura"])

    def test_un_eje_que_una_de_las_dos_no_declara_no_es_un_cambio(self) -> None:
        """Una ausencia no es una diferencia, y anotarla inventaria un cambio."""

        r = self._comparar("s1", ["s2"], {
            "circuitos": {"s1": "imola", "s2": "imola"},
            "reglajes": {"s1": dict(BASE),
                         "s2": {k: v for k, v in BASE.items()
                                if k != "presion_de_freno_pct"}},
        })
        self.assertEqual(r["sesiones"][1]["difiere_en"], [])

    def test_sin_circuito_no_se_agrupa_nada(self) -> None:
        with patch.object(reglajes.procedencia_sesiones, "de", return_value={}):
            r = reglajes.comparar("s1", lambda s, v: ({}, False),
                                  lambda s: None).como_dict()
        self.assertEqual(r["sesiones"], [])
        self.assertIn("no declara circuito", r["motivo"])

    def test_cada_respuesta_declara_lo_que_no_autoriza(self) -> None:
        """La cautela viaja con el dato y no en la cabeza de quien lo leyo.

        Dos sesiones del mismo circuito no son un experimento: cambia el tipo,
        el combustible, la dificultad, el clima y el trafico.
        """
        r = self._comparar("s1", ["s2"], {
            "circuitos": {"s1": "spielberg", "s2": "spielberg"},
            "reglajes": {"s1": dict(BASE), "s2": dict(BASE)},
        })
        self.assertIn("no son un experimento", r["no_autoriza"])
        self.assertIn("no es del reglaje", r["lo_que_si_autoriza"])

    def test_la_mejor_vuelta_y_cuantas_hubo_viajan_por_sesion(self) -> None:
        r = self._comparar("s1", ["s2"], {
            "circuitos": {"s1": "shanghai", "s2": "shanghai"},
            "reglajes": {"s1": dict(BASE), "s2": dict(BASE)},
        }, mejores={"s1": (102.547, 5), "s2": (99.863, 2)})
        self.assertEqual([(s["mejor_vuelta_s"], s["vueltas_validas"])
                          for s in r["sesiones"]], [(102.547, 5), (99.863, 2)])

    def test_una_sesion_sin_vuelta_valida_no_inventa_un_tiempo(self) -> None:
        """Pasa de verdad: varias contrarrelojes de la base no cierran una.

        Poner cero, o la duracion de la captura, seria un tiempo de vuelta que
        nadie corrio.
        """
        r = self._comparar("s1", [], {
            "circuitos": {"s1": "imola"}, "reglajes": {"s1": dict(BASE)},
        }, mejores={"s1": (None, 0)})
        self.assertIsNone(r["sesiones"][0]["mejor_vuelta_s"])
        self.assertEqual(r["sesiones"][0]["vueltas_validas"], 0)

    def test_si_no_se_puede_afirmar_que_corrio_se_dice(self) -> None:
        """`asentada` viaja por sesion: una tabla de reglajes que no se sabe si
        llegaron a la pista es una tabla de intenciones."""

        r = self._comparar("s1", ["s2"], {
            "circuitos": {"s1": "baku", "s2": "baku"},
            "reglajes": {"s1": dict(BASE), "s2": dict(BASE)},
        }, asentadas={"s2": False})
        self.assertTrue(r["sesiones"][0]["asentada"])
        self.assertFalse(r["sesiones"][1]["asentada"])


class LecturaDeLaTabla(unittest.TestCase):
    """`_lectura` es lo unico que afirma algo, y por eso se prueba aparte."""

    def _con(self, cuantos):
        return [reglajes.ReglajeDeUnaSesion(
            session_id="s%d" % i, tipo_sesion=None, familia_de_sesion=None,
            parc_ferme=None, capturado_utc=None, cuantos_difieren=c,
            difiere_en=([{"clave": "aleron_trasero", "lo_impone_el_modo": False}]
                        if c else []))
            for i, c in enumerate(cuantos)]

    def test_una_sola_sesion_no_afirma_nada(self) -> None:
        self.assertIn("no hay otra sesión",
                      reglajes._lectura(self._con([0])))

    def test_ninguna_difiere(self) -> None:
        texto = reglajes._lectura(self._con([0, 0, 0]))
        self.assertIn("el mismo en las 3", texto)
        self.assertIn("no es del reglaje", texto)

    def test_alguna_difiere_y_se_nombran_los_ejes(self) -> None:
        texto = reglajes._lectura(self._con([0, 1, 0]))
        self.assertIn("1 corrieron con otro reglaje", texto)
        self.assertIn("aleron_trasero", texto)
        self.assertNotIn("no es del reglaje", texto)


class ElAcotadoAlVehiculoVaEnLaConsulta(unittest.TestCase):
    """Se leian las filas de los veintidos coches para mirar uno.

    Medido el 2026-09-13: la comparacion de Spielberg ---tres sesiones, una de
    ellas una carrera--- traia filas de todos y descartaba en Python las que no
    hacian falta.
    """

    def test_la_consulta_de_sectores_acota_cuando_se_le_dan_vehiculos(self) -> None:
        from unittest.mock import MagicMock

        from backend.analisis import sectores

        cursor = MagicMock()
        cursor.fetchall.return_value = []
        sectores._leer(cursor, "f1_25_udp_simulation", "s1", ("s1:car:0",))
        consulta, parametros = cursor.execute.call_args[0]
        self.assertIn("vehicle_id = any(%s)", consulta)
        self.assertIn(["s1:car:0"], list(parametros))
        self.assertEqual(consulta.count("%s"), len(parametros))

    def test_y_sin_vehiculos_no_agrega_la_clausula(self) -> None:
        from unittest.mock import MagicMock

        from backend.analisis import sectores

        cursor = MagicMock()
        cursor.fetchall.return_value = []
        sectores._leer(cursor, "f1_25_udp_simulation", "s1")
        consulta, parametros = cursor.execute.call_args[0]
        # `vehicle_id` figura como columna y en el orden; lo que no tiene que
        # estar es la clausula que acota.
        self.assertNotIn("vehicle_id = any(%s)", consulta)
        self.assertEqual(consulta.count("%s"), len(parametros))


if __name__ == "__main__":
    unittest.main()
