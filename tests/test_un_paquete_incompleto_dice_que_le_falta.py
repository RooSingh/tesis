# -*- coding: utf-8 -*-
"""Negarse a importar esta bien; negarse con un nombre de Python, no.

QUE PASO, EL 2026-09-13. El usuario subio `openf1_sesion_9939.zip` desde el
tablero, que era la ultima de las cinco pruebas de subida. El comprimido se
reconocio por contenido, se abrio, y la `session_key` se leyo del `session.json`
de adentro ---todo bien---. Despues el tablero mostro:

    El procesamiento termino como «fallido»: KeyError: 'meeting_key'

NEGARSE ES CORRECTO, Y SE COMPROBO CONTRA EL ESQUEMA. `racing_sessions` declara
`meeting_key`, `session_name` y `session_type` como `NOT NULL`: sin esos tres no
hay sesion que registrar. Por eso `import_available_context` los lee con
indexado directo mientras todos los demas campos usan `.get()`, y eso es
deliberado: el codigo espeja el esquema.

LO QUE ESTA MAL ES COMO SE NIEGA. `KeyError: 'meeting_key'` es el nombre interno
de una excepcion de Python. No dice que archivo mirar, no dice que los tres son
obligatorios, ni por que. Es la misma familia que «El proceso termino con codigo
1. Ver /app/logs/...»: un error que nombra un mecanismo en vez de una causa.

Y SE PARA ANTES DE TOCAR LA BASE. Un paquete que no puede registrarse no tiene
por que abrir una conexion para descubrirlo.

POR QUE ESTOS TRES Y NO LOS QUINCE. `scripts/descargar_paquete_openf1.py` ya
exige tres campos para decidir si un `session.json` **es** una sesion, y son
otros tres ---`session_type`, `date_start`, `circuit_key`---. No son la misma
pregunta y por eso no son la misma lista: aquella pregunta si el archivo
describe una sesion; esta, si la tabla la puede aceptar. La lista de aqui sale
del esquema y no de una opinion.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from backend import session_context  # noqa: E402

#: El `session.json` que traia el comprimido de prueba, tal cual.
EL_DE_LA_PRUEBA = {"session_key": 9939, "year": 2025}


class UnPaqueteIncompletoDiceQueLeFaltaTests(unittest.TestCase):

    def _fallo_de(self, session):
        with self.assertRaises(Exception) as caido:
            session_context.import_available_context("/paquetes/2025/9939",
                                                     session, {})
        return caido.exception

    def test_EL_DEFECTO_el_motivo_no_puede_ser_un_nombre_de_python(self) -> None:
        self.assertNotIsInstance(
            self._fallo_de(EL_DE_LA_PRUEBA), KeyError,
            "sigue saliendo el nombre interno de la excepcion")

    def test_dice_QUE_campos_faltan_y_no_solo_el_primero(self) -> None:
        """Enterarse de a uno obliga a subir tres veces para saber que falta."""
        texto = str(self._fallo_de(EL_DE_LA_PRUEBA))
        for campo in ("meeting_key", "session_name", "session_type"):
            self.assertIn(campo, texto, "no nombra %s: %s" % (campo, texto))

    def test_dice_DONDE_mirar(self) -> None:
        texto = str(self._fallo_de(EL_DE_LA_PRUEBA))
        self.assertIn("session.json", texto, texto)
        self.assertIn("9939", texto, "no dice de que paquete habla: %s" % texto)

    def test_y_dice_POR_QUE_hacen_falta(self) -> None:
        """Sin el motivo, «falta X» se lee como un capricho del programa."""
        texto = str(self._fallo_de(EL_DE_LA_PRUEBA)).lower()
        self.assertTrue(
            "no acepta" in texto or "obligator" in texto or "not null" in texto,
            "no explica por que son obligatorios: %s" % texto)

    def test_lo_que_falta_se_mira_ANTES_de_abrir_la_base(self) -> None:
        """Si abriera la conexion, esta prueba fallaria por no tener base."""
        import inspect
        fuente = inspect.getsource(session_context.import_available_context)
        antes = fuente.split("obtener_conexion")[0]
        self.assertIn("CAMPOS_QUE_LA_TABLA_EXIGE", antes,
                      "la comprobacion quedo despues de abrir la conexion")

    def test_UN_PAQUETE_SANO_NO_SE_FRENA_ACA(self) -> None:
        """La guarda no puede volverse un filtro que rechace lo que servia.

        Con los tres campos presentes tiene que pasar de largo y llegar a la
        base; aca no hay base, asi que lo que se comprueba es que **no** falle
        por los campos.
        """
        sano = {"session_key": 9955, "meeting_key": 1264,
                "session_name": "Race", "session_type": "Race"}
        fallo = self._fallo_de(sano)
        self.assertNotIsInstance(fallo, session_context.PaqueteSinSesion,
                                 "freno un paquete que trae los tres campos")

    def test_un_campo_presente_pero_nulo_cuenta_como_ausente(self) -> None:
        """`NOT NULL` no admite un nulo declarado, y `"meeting_key": null` lo es."""
        con_nulo = dict(EL_DE_LA_PRUEBA,
                        meeting_key=None, session_name="Race", session_type="Race")
        texto = str(self._fallo_de(con_nulo))
        self.assertIn("meeting_key", texto, texto)


if __name__ == "__main__":
    unittest.main()
