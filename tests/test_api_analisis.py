# -*- coding: utf-8 -*-
"""Pruebas de las rutas del modulo de analisis.

CRITERIO. Las herramientas de analisis ya tienen sus propias pruebas: aca no
se vuelve a comprobar que midan bien. Lo que se comprueba es **la frontera**:
que la fuente se deduzca del identificador, que las estructuras del analisis
lleguen enteras al cliente, y que una negativa de la herramienta ---«esta
fuente no sostiene este analisis»--- llegue como respuesta con su motivo y no
como un error del servidor ni como un numero inventado.
"""

from __future__ import annotations

import dataclasses
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from backend import api_analisis


@dataclasses.dataclass
class TramoFalso:
    desde_m: float
    hasta_m: float
    delta_s: float


@dataclasses.dataclass
class TrazaFalsa:
    session_id: str
    fuente: str
    tramos: list
    vuelta_a: int = 3
    vuelta_b: int = 4


class DeduccionDeFuenteTests(unittest.TestCase):
    def test_reconoce_las_tres_fuentes(self) -> None:
        self.assertEqual(api_analisis._fuente_de("f1_25:session:9"), "f1_25_udp_simulation")
        self.assertEqual(api_analisis._fuente_de("can:segmento:s"), "can_real_replay")
        self.assertEqual(api_analisis._fuente_de("9947"), "openf1_historical_replay")


class SerializacionTests(unittest.TestCase):
    """El vocabulario del analisis no se traduce en la frontera."""

    def test_una_estructura_anidada_llega_entera(self) -> None:
        traza = TrazaFalsa("s1", "f1_25_udp_simulation",
                           [TramoFalso(0.0, 10.0, 0.12), TramoFalso(10.0, 20.0, -0.03)])
        d = api_analisis._serializar(traza)
        self.assertEqual(d["session_id"], "s1")
        self.assertEqual(len(d["tramos"]), 2)
        self.assertEqual(d["tramos"][0]["delta_s"], 0.12)
        # Los nombres son los del modulo, no unos nuevos inventados aca.
        self.assertIn("desde_m", d["tramos"][0])

    def test_los_tipos_simples_pasan_sin_tocar(self) -> None:
        self.assertEqual(api_analisis._serializar(3.5), 3.5)
        self.assertEqual(api_analisis._serializar(None), None)
        self.assertEqual(api_analisis._serializar(True), True)
        self.assertEqual(api_analisis._serializar((1, 2)), [1, 2])
        self.assertEqual(api_analisis._serializar({"a": 1}), {"a": 1})

    def test_un_tipo_inesperado_no_rompe_la_respuesta(self) -> None:
        """Preferible un texto que una excepcion en mitad de una serializacion."""
        class Raro:
            def __str__(self):
                return "raro"
        self.assertEqual(api_analisis._serializar(Raro()), "raro")


class NegativaDeLaHerramientaTests(unittest.TestCase):
    """Que la fuente no sostenga un analisis es una respuesta, no un fallo."""

    def test_una_negativa_llega_como_422_con_su_motivo(self) -> None:
        @dataclasses.dataclass
        class SinTrazaFalsa:
            motivo: str = "La fuente no declara distancia recorrida."

        with self.assertRaises(HTTPException) as caso:
            api_analisis._correr(lambda *_: SinTrazaFalsa())
        self.assertEqual(caso.exception.status_code, 422)
        self.assertIn("no declara distancia", caso.exception.detail["motivo"])

    def test_un_resultado_con_motivo_y_con_datos_no_se_toma_por_negativa(self) -> None:
        """Una traza puede traer un motivo informativo y aun asi tener tramos."""
        traza = TrazaFalsa("s1", "f1_25_udp_simulation", [TramoFalso(0.0, 10.0, 0.1)])
        d = api_analisis._correr(lambda: traza)
        self.assertEqual(len(d["tramos"]), 1)

    def test_un_fallo_real_sale_como_500_y_no_se_disfraza(self) -> None:
        def revienta():
            raise RuntimeError("la base no responde")

        with self.assertRaises(HTTPException) as caso:
            api_analisis._correr(revienta)
        self.assertEqual(caso.exception.status_code, 500)
        self.assertIn("la base no responde", caso.exception.detail)


class RutasTests(unittest.TestCase):
    """Cada ruta llama a su herramienta con la fuente deducida."""

    def test_delta_pasa_las_dos_vueltas_y_el_paso(self) -> None:
        traza = TrazaFalsa("s", "f1_25_udp_simulation", [TramoFalso(0.0, 5.0, 0.01)])
        with patch("backend.api_analisis.delta.comparar", return_value=traza) as fn:
            api_analisis.analisis_delta("f1_25:session:7", vuelta_a=3, vuelta_b=4, paso_m=25.0)
        fn.assert_called_once_with("f1_25_udp_simulation", "f1_25:session:7",
                                   3, 4, 25.0, None, None, None)

    def test_delta_entre_dos_pilotos_pasa_los_dos_vehiculos(self) -> None:
        """Sin esto la ruta acepta los vehiculos y no se los da a nadie.

        Es la unica forma de equivocarse que no se ve en la respuesta: la traza
        sale igual de bien formada, comparando al mismo piloto consigo mismo.
        """
        traza = TrazaFalsa("s", "f1_25_udp_simulation", [TramoFalso(0.0, 5.0, 0.01)])
        with patch("backend.api_analisis.delta.comparar", return_value=traza) as fn:
            api_analisis.analisis_delta("f1_25:session:7", vuelta_a=3, vuelta_b=3,
                                        vehiculo_a="veh:a", vehiculo_b="veh:b")
        fn.assert_called_once_with("f1_25_udp_simulation", "f1_25:session:7",
                                   3, 3, 10.0, None, "veh:a", "veh:b")

    def test_frenadas_pasa_la_vuelta(self) -> None:
        @dataclasses.dataclass
        class FrenadasFalsas:
            frenadas: list

        with patch("backend.api_analisis.frenadas.caracterizar",
                   return_value=FrenadasFalsas([])) as fn:
            api_analisis.analisis_frenadas("f1_25:session:7", vuelta=12)
        fn.assert_called_once_with("f1_25_udp_simulation", "f1_25:session:7", 12)

    def test_degradacion_y_consistencia_solo_piden_la_sesion(self) -> None:
        @dataclasses.dataclass
        class Vacio:
            tandas: list

        for nombre, ruta in [("degradacion", api_analisis.analisis_degradacion),
                             ("consistencia", api_analisis.analisis_consistencia)]:
            with patch("backend.api_analisis.%s.analizar" % nombre,
                       return_value=Vacio([])) as fn:
                ruta("can:segmento:sample_30")
            fn.assert_called_once_with("can_real_replay", "can:segmento:sample_30")

    def test_traccion_respeta_la_derivacion_de_deslizamiento(self) -> None:
        @dataclasses.dataclass
        class Vacio:
            salidas: list

        with patch("backend.api_analisis.traccion.analizar", return_value=Vacio([])) as fn:
            api_analisis.analisis_traccion("f1_25:session:7", vuelta=5,
                                           derivar_deslizamiento=False)
        fn.assert_called_once_with("f1_25_udp_simulation", "f1_25:session:7", 5, False)


class HerramientasTests(unittest.TestCase):
    def test_lista_las_herramientas_con_sus_requisitos(self) -> None:
        """Que habilita cada fuente es una conclusion del trabajo, no ayuda."""
        r = api_analisis.listar_herramientas()
        self.assertGreater(r["cantidad"], 0)
        primera = r["herramientas"][0]
        self.assertIn("clave", primera)
        self.assertIn("requisitos", primera)


class VigilanciaTests(unittest.TestCase):
    """La ruta que no mira el valor del dato sino su ausencia."""

    def setUp(self) -> None:
        # Desde el 2026-09-08 esta ruta guarda su respuesta: costaba 29,77 s en
        # frio y era una de las dos consultas que hacian que el primer grafico
        # del tablero tardara veintiseis segundos en aparecer. Cada prueba
        # arranca con la cache vacia, porque lo que se comprueba aca es lo que
        # la ruta **calcula**, no lo que recuerda.
        api_analisis._VIGILANCIA_CACHE.clear()

    def tearDown(self) -> None:
        api_analisis._VIGILANCIA_CACHE.clear()

    def _vigilada(self, vigilancias):
        from backend.analisis import criticidad as cr
        return cr.Vigilada(fuente="f1_25_udp_simulation", session_id="s1",
                           vigilancias=vigilancias,
                           medido_sobre="vehiculo / corrida",
                           conteo={"critica": 1, "atencion": 0,
                                   "informativa": 0})

    def _una(self, **kw):
        from backend.analisis import criticidad as cr
        base = dict(magnitud="Velocidad del vehiculo",
                    nivel_seguridad=cr.ATENCION, nivel_analisis=cr.CRITICA,
                    senal="speed", hz=20.0, silencio_para_alarmar_s=0.2,
                    aviso_perdido="el ritmo", percepcion_del_conductor="la ve",
                    cita="", herramientas_que_inhabilita=3)
        base.update(kw)
        return cr.Vigilancia(**base)

    def test_cada_fila_llega_con_su_nivel_y_con_su_eje(self) -> None:
        """Sin el eje, un tablero pintaria de rojo la velocidad del vehiculo
        ---critica porque inhabilita tres herramientas--- y se leeria como un
        peligro que no es."""

        with patch.object(api_analisis.criticidad, "vigilar",
                          return_value=self._vigilada([self._una()])):
            d = api_analisis.analisis_vigilancia("f1_25:session:1")

        fila = d["vigilancias"][0]
        self.assertEqual(fila["nivel"], "critica")
        self.assertEqual(fila["eje"], "analisis")
        # Los dos ejes siguen viajando por separado, no solo el peor.
        self.assertEqual(fila["nivel_seguridad"], "atencion")
        self.assertEqual(fila["nivel_analisis"], "critica")

    def test_la_terna_medida_viaja_con_la_respuesta(self) -> None:
        with patch.object(api_analisis.criticidad, "vigilar",
                          return_value=self._vigilada([self._una()])):
            d = api_analisis.analisis_vigilancia("f1_25:session:1")
        self.assertEqual(d["medido_sobre"], "vehiculo / corrida")

    def test_una_sesion_sin_muestras_es_422_con_su_motivo(self) -> None:
        """No un 500 ni una tabla vacia: la sesion existe, lo que no hay es
        con que derivar cuanto silencio tolera cada canal."""

        with patch.object(api_analisis.criticidad, "vigilar",
                          return_value=self._vigilada([])):
            with self.assertRaises(HTTPException) as caja:
                api_analisis.analisis_vigilancia("f1_25:session:1")
        self.assertEqual(caja.exception.status_code, 422)
        self.assertIn("silencio", caja.exception.detail["motivo"])

    def test_por_omision_no_pide_las_ausentes(self) -> None:
        """Una magnitud que la fuente nunca entrega no es una alarma sino una
        ausencia declarada."""

        with patch.object(api_analisis.criticidad, "vigilar",
                          return_value=self._vigilada([self._una()])) as espia:
            api_analisis.analisis_vigilancia("f1_25:session:1")
        self.assertFalse(espia.call_args.kwargs["incluir_ausentes"])


if __name__ == "__main__":
    unittest.main()
