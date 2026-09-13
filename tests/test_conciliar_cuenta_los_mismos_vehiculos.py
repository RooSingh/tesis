# -*- coding: utf-8 -*-
"""Las dos mitades de una comparacion tienen que hablar de la misma poblacion.

EL DEFECTO, MEDIDO el 2026-09-13 sobre `f1_25:session:8393851191739547781`
(shanghai). El guion de reinyeccion informo esto:

    Hay -3,690,012 filas faltantes en senales que ya tienen datos.
      brake_bias_front    53,445 de 10,689
      brake_position      53,445 de 10,689

Un faltante **en negativo**, y «hay mas de lo que se espera» en cada renglon.
La sospecha razonable era que la base tuviera filas duplicadas ---lo que seria
serio, porque es una sesion cargada---. **No las tiene.** 53.445 son exactamente
5 vehiculos x 10.689, y una consulta por corrida devuelve una sola, sin
reproducciones.

LO QUE PASABA. Las dos mitades contaban poblaciones distintas:

  - `inventariar()` recorre la captura con `mensajes_desde_paquete()`, que por
    defecto trae **solo el vehiculo propio** (`solo_vehiculo_propio=True`). Y
    esta bien que sea asi: `publicar()` y `escribir()` usan el mismo defecto, de
    modo que la herramienta entera reinyecta un vehiculo.
  - La consulta de `conciliar()` hacia `group by signal_name` **sin filtrar por
    vehiculo**, de modo que sumaba los cinco que la captura en vivo habia
    dejado.

O sea: lo esperado era de un coche y lo presente de cinco. La resta no podia dar
otra cosa.

POR QUE EL SIGNO IMPORTA MAS QUE EL NUMERO. Un faltante negativo no es un
faltante grande: es una comparacion que no significa nada. Y esta comparacion
existe justamente porque **una version anterior de esta herramienta informo
exito habiendo perdido el 5,9 % de las filas**. Una guarda que se puede
equivocar de poblacion no guarda.

EL ARREGLO: `inventariar()` declara **de que vehiculos** conto, y `conciliar()`
filtra por esos. No se cambia el defecto de un vehiculo, que es deliberado; se
hace que el otro lado lo respete. Si algun dia la herramienta reinyecte la
parrilla entera, el conjunto crece y el filtro lo sigue solo.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from scripts import republicar_captura as guion  # noqa: E402

#: Los numeros exactos del caso, tomados del registro de la Raspberry.
PROPIO = "f1_25:session:8393851191739547781:car:2"
LOS_CINCO = [PROPIO] + [
    "f1_25:session:8393851191739547781:car:%d" % i for i in (6, 7, 13, 19)]
POR_VEHICULO = 10_689
LOS_CINCO_JUNTOS = 53_445          # 5 x 10.689, comprobado en la base


class ConexionFalsa:
    """Una base que responde el conteo que se le dijo, y guarda la consulta."""

    def __init__(self, filas, registro):
        self._filas = filas
        self._registro = registro

    def cursor(self):
        return self

    def execute(self, sql, parametros=()):
        self._registro.append((" ".join(sql.split()), parametros))

    def fetchall(self):
        return list(self._filas)

    def fetchone(self):
        return (0,)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class LaComparacionHablaDeLosMismosVehiculos(unittest.TestCase):

    def _conciliar(self, filas, esperado, vehiculos):
        registro: list = []
        conexion = ConexionFalsa(filas, registro)
        with patch.object(guion.db, "obtener_conexion", return_value=conexion), \
                patch.object(guion.time, "sleep"):
            resultado = guion.conciliar(
                "f1_25:session:8393851191763583202", esperado,
                vehiculos=vehiculos, espera_maxima_s=0)
        return resultado, registro

    # ---- el caso reportado ----

    def test_no_sobran_filas_por_contar_cinco_coches_contra_uno(self) -> None:
        """Con el filtro puesto, lo presente es del mismo coche que lo esperado."""

        filas = [("brake_bias_front", POR_VEHICULO),
                 ("brake_position", POR_VEHICULO)]
        esperado = {"brake_bias_front": POR_VEHICULO,
                    "brake_position": POR_VEHICULO}
        resultado, _ = self._conciliar(filas, esperado, {PROPIO})
        self.assertEqual(
            resultado["senales_incompletas"], {},
            "se declararon incompletas senales que estaban enteras: %r"
            % (resultado["senales_incompletas"],))
        self.assertEqual(resultado["esperado"], resultado["presente"])

    def test_la_consulta_filtra_por_vehiculo(self) -> None:
        """Sin el filtro en el SQL, cualquier otra guarda es cosmetica."""

        _, registro = self._conciliar(
            [("speed", POR_VEHICULO)], {"speed": POR_VEHICULO}, {PROPIO})
        self.assertTrue(registro, "no se ejecuto ninguna consulta")
        sql, parametros = registro[0]
        self.assertIn(
            "vehicle_id", sql,
            "la consulta sigue sumando todos los vehiculos de la sesion:\n  %s" % sql)
        self.assertIn(PROPIO, str(parametros),
                      "el vehiculo contado no llego a la consulta: %r" % (parametros,))

    def test_un_faltante_nunca_sale_negativo(self) -> None:
        """La invariante de la que salio todo esto."""

        filas = [("brake_bias_front", LOS_CINCO_JUNTOS)]
        esperado = {"brake_bias_front": POR_VEHICULO}
        resultado, _ = self._conciliar(filas, esperado, {PROPIO})
        negativos = {s: n for s, n in resultado["senales_incompletas"].items() if n < 0}
        self.assertEqual(
            negativos, {},
            "el faltante volvio a ser negativo: %r. Un faltante negativo no es "
            "un faltante grande, es una comparacion que no significa nada."
            % negativos)

    def test_un_exceso_se_declara_aparte_y_no_como_faltante(self) -> None:
        """La segunda linea de defensa, por si las poblaciones se separan otra vez."""

        filas = [("brake_bias_front", LOS_CINCO_JUNTOS)]
        resultado, _ = self._conciliar(
            filas, {"brake_bias_front": POR_VEHICULO}, {PROPIO})
        self.assertEqual(resultado["senales_incompletas"], {},
                         "un exceso se conto como si faltara algo")
        self.assertEqual(
            resultado["senales_excedidas"],
            {"brake_bias_front": LOS_CINCO_JUNTOS - POR_VEHICULO},
            "el exceso no quedo declarado, de modo que seria silencioso")

    def test_clasificar_tambien_separa_el_exceso(self) -> None:
        estado = guion.clasificar({"speed": POR_VEHICULO},
                                  {"speed": LOS_CINCO_JUNTOS})
        self.assertEqual(estado["incompletas"], {})
        self.assertEqual(estado["excedidas"],
                         {"speed": (LOS_CINCO_JUNTOS, POR_VEHICULO)})
        self.assertEqual(
            estado["filas_faltantes"], 0,
            "«filas_faltantes» volvio a incluir un exceso, que es de donde "
            "salia el -3.690.012")

    def test_una_perdida_de_verdad_se_sigue_viendo(self) -> None:
        """Lo que no puede pasar es que el arreglo tape lo que la guarda cuida."""

        filas = [("speed", 9_000)]
        resultado, _ = self._conciliar(filas, {"speed": POR_VEHICULO}, {PROPIO})
        self.assertEqual(resultado["senales_incompletas"],
                         {"speed": POR_VEHICULO - 9_000})

    def test_una_senal_ausente_se_sigue_viendo(self) -> None:
        resultado, _ = self._conciliar([], {"speed": POR_VEHICULO}, {PROPIO})
        self.assertEqual(resultado["senales_incompletas"], {"speed": POR_VEHICULO})
        self.assertEqual(resultado["presente"], 0)

    def test_con_varios_vehiculos_se_esperan_varios(self) -> None:
        """Si algun dia se reinyecta la parrilla, el filtro la sigue solo."""

        _, registro = self._conciliar(
            [("speed", LOS_CINCO_JUNTOS)], {"speed": LOS_CINCO_JUNTOS},
            set(LOS_CINCO))
        _, parametros = registro[0]
        for vehiculo in LOS_CINCO:
            self.assertIn(vehiculo, str(parametros),
                          "falto %s en la consulta" % vehiculo)

    # ---- el que de verdad imprimio «53.445 de 10.689» ----

    def test_conteos_persistidos_tambien_filtra(self) -> None:
        """El renglon del registro no salia de `conciliar` sino de aqui.

        Las dos funciones tenian la misma consulta sin filtrar, y arreglar solo
        una habria dejado el sintoma en pantalla intacto. Esta es la que
        alimenta `clasificar()`, que es lo que imprime «N de M».
        """

        registro: list = []
        conexion = ConexionFalsa([("brake_position", POR_VEHICULO)], registro)
        with patch.object(guion.db, "obtener_conexion", return_value=conexion):
            presentes = guion.conteos_persistidos(
                "f1_25:session:8393851191739547781", {PROPIO})

        sql, parametros = registro[0]
        self.assertIn(
            "vehicle_id", sql,
            "`conteos_persistidos` sigue sumando todos los vehiculos:\n  %s" % sql)
        self.assertIn(PROPIO, str(parametros))
        self.assertEqual(presentes, {"brake_position": POR_VEHICULO})

    def test_el_renglon_del_caso_real_ya_no_dice_cinco_contra_uno(self) -> None:
        """De punta a punta: lo que se imprimiria con los numeros de shanghai."""

        conexion = ConexionFalsa([("brake_position", POR_VEHICULO)], [])
        with patch.object(guion.db, "obtener_conexion", return_value=conexion):
            presentes = guion.conteos_persistidos(
                "f1_25:session:8393851191739547781", {PROPIO})
        estado = guion.clasificar({"brake_position": POR_VEHICULO}, presentes)
        self.assertEqual(estado["incompletas"], {})
        self.assertEqual(
            estado["filas_faltantes"], 0,
            "seguiria imprimiendo un faltante donde no falta nada")

    # ---- la mitad que cuenta la captura ----

    def test_inventariar_declara_de_que_vehiculos_conto(self) -> None:
        """Sin esto, `conciliar` no tiene por donde filtrar."""

        import inspect
        firma = inspect.signature(guion.inventariar)
        fuente = inspect.getsource(guion.inventariar)
        self.assertIn(
            "vehicle_id", fuente,
            "`inventariar` no mira el vehiculo de los mensajes que cuenta, de "
            "modo que no puede decir de quienes son esos conteos")
        del firma  # la forma exacta del retorno la comprueba el llamador

    def test_conciliar_exige_saber_de_quien_cuenta(self) -> None:
        """Llamarla sin vehiculos es el defecto de antes: no debe poder hacerse."""

        self.assertIn(
            "vehiculos", guion.conciliar.__code__.co_varnames,
            "`conciliar` no recibe los vehiculos: volveria a sumar toda la sesion")


if __name__ == "__main__":
    unittest.main()
