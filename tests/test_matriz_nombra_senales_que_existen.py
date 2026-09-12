# -*- coding: utf-8 -*-
"""La matriz de fuentes solo puede nombrar senales que la fuente publica.

QUE ES LA MATRIZ Y POR QUE IMPORTA QUE NO MIENTA. `backend/matriz_fuentes.py`
sostiene la tabla «Que sostiene cada fuente» del tablero: para cada magnitud
dice con que senal la cubre cada fuente, y cuando no la cubre declara el motivo.
Es la superficie de auditoria del trabajo ---lo que le permite a quien mira
saber que puede afirmar con lo que tiene--- y por eso una fila equivocada no es
un detalle de presentacion: es la auditoria afirmando algo falso.

EL DEFECTO QUE ESTO CUIDA. Dos filas de F1 25 estaban mal, en los dos sentidos
posibles:

* «Velocidad por rueda» declaraba la ausencia con el motivo «el protocolo no
  publica velocidad por rueda». El protocolo la publica: el adaptador declara
  `wheel_speed_front_left`, `..._front_right`, `..._rear_left` y `..._rear_right`,
  y la carrera de Spa tiene 60.663 muestras de cada una.
* «Velocidad de guinada» apuntaba a `yaw_rate_rads`, que **no existe**. El
  adaptador publica `yaw` y `yaw_rate`. Como la medicion busca la senal por
  nombre y no la encuentra, la fila salia en blanco: el tablero decia que F1 25
  no sostiene la guinada mientras la base guardaba 60.663 muestras de ella.

Las dos se veian igual en pantalla ---un «no» donde va un «si»--- y ninguna
prueba las separaba del «no» legitimo, porque nadie comparaba los nombres de la
matriz contra el catalogo que el adaptador declara.

POR QUE SE COMPARA CONTRA EL ADAPTADOR Y NO CONTRA LA BASE. Preguntarle a la
base solo diria que senales llegaron a guardarse en las sesiones que hay, y una
sesion vieja que no las tenga haria «fallar» a una senal que la fuente si
publica. El catalogo del adaptador se deriva de los mismos mapas que usa la
normalizacion, de modo que es la unica respuesta que no puede quedar
desactualizada.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from adapters import f1_25 as adaptador_f1_25  # noqa: E402
from backend import matriz_fuentes  # noqa: E402

F1_25 = "f1_25_udp_simulation"


def senales_de_f1_25() -> set[str]:
    return {s["signal_name"] for s in adaptador_f1_25.catalogo_de_senales()}


class LaMatrizNoNombraSenalesQueNoExistenTests(unittest.TestCase):

    def test_toda_senal_de_f1_25_que_la_matriz_nombra_existe(self) -> None:
        catalogo = senales_de_f1_25()
        inventadas = []
        for fila in matriz_fuentes.MAGNITUDES:
            senal = fila["por_fuente"].get(F1_25)
            if senal and senal not in catalogo:
                inventadas.append((fila["magnitud"], senal))
        self.assertEqual(
            inventadas, [],
            "la matriz nombra senales que el adaptador de F1 25 no publica, de "
            "modo que la fila sale en blanco y el tablero declara una ausencia "
            "que no existe: %r" % (inventadas,))

    def test_ninguna_ausencia_declarada_de_f1_25_es_falsa(self) -> None:
        """Una ausencia declarada es una afirmacion, y tiene que ser cierta."""

        catalogo = senales_de_f1_25()
        # Los nombres que la matriz ya usa para cada magnitud en la otra fuente
        # no sirven de guia: lo que se comprueba es que, si la matriz dice que
        # F1 25 no cubre una magnitud, no haya en el catalogo una senal obvia
        # que la cubra.
        sospechosas = {
            "Velocidad por rueda": "wheel_speed_",
            "Velocidad de guinada": "yaw_rate",
            "Aceleracion longitudinal": "g_force_longitudinal",
            "Aceleracion lateral": "g_force_lateral",
        }
        falsas = []
        for fila in matriz_fuentes.MAGNITUDES:
            if fila["por_fuente"].get(F1_25) is not None:
                continue
            prefijo = sospechosas.get(fila["magnitud"])
            if prefijo and any(n.startswith(prefijo) for n in catalogo):
                falsas.append((fila["magnitud"],
                               sorted(n for n in catalogo if n.startswith(prefijo))))
        self.assertEqual(
            falsas, [],
            "la matriz declara que F1 25 no cubre una magnitud que el adaptador "
            "si publica: %r" % (falsas,))

    def test_una_ausencia_sin_motivo_no_se_puede_declarar(self) -> None:
        sin_motivo = []
        for fila in matriz_fuentes.MAGNITUDES:
            for fuente, senal in fila["por_fuente"].items():
                if senal is None and not (fila.get("ausencias") or {}).get(fuente):
                    sin_motivo.append((fila["magnitud"], fuente))
        self.assertEqual(
            sin_motivo, [],
            "hay ausencias sin motivo declarado: %r" % (sin_motivo,))

    def test_las_cuatro_ruedas_de_f1_25_estan_en_el_catalogo(self) -> None:
        """La guarda contra el motivo que se escribio al reves."""

        catalogo = senales_de_f1_25()
        for esquina in ("front_left", "front_right", "rear_left", "rear_right"):
            self.assertIn("wheel_speed_%s" % esquina, catalogo)
        self.assertIn("yaw_rate", catalogo)
        self.assertNotIn("yaw_rate_rads", catalogo)


if __name__ == "__main__":
    unittest.main()
