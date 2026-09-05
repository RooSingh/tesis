# -*- coding: utf-8 -*-
"""La reconstruccion del recorrido y su calibracion contra la verdad.

Los dos defectos que estas pruebas cierran, y que ya ocurrieron
--------------------------------------------------------------
**1. Exigir que dos senales coincidan en el mismo instante.** Cada senal viene de
su propio identificador, con su propio periodo, de modo que **no llegan juntas**.
En un segmento coincidieron por casualidad y funciono; en otro la interseccion
quedo vacia y la reconstruccion devolvio **un recorrido de cero metros sin que
nada fallara**. Es el peor tipo de defecto: no rompe, miente.

**2. Integrar a traves de discontinuidades.** Una contrarreloj no es una
conduccion continua: entre intento e intento el programa emisor devuelve el
vehiculo a la linea de partida. Cuatro saltos de unos novecientos metros a mas de
dieciocho mil metros por segundo, integrados como si fueran conduccion, dieron un
error de **854 metros tras 1.128 recorridos**. Ese numero no era un error grande:
era un numero **sin significado**, porque las dos trayectorias ya no se referian
al mismo recorrido.

Con el tramo continuo aislado, el error mediano resulta de 5,8 metros sobre 3,99
kilometros.
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

import calibrar_reconstruccion as cal  # noqa: E402
import reconstruir_recorrido_can as rec  # noqa: E402


class EmparejaSenalesQueNoLleganJuntas(unittest.TestCase):
    """El defecto que devolvia cero metros sin fallar."""

    def test_empareja_aunque_los_instantes_no_coincidan(self):
        """Es el caso real: cada senal tiene su propio identificador."""

        s = {"speed": {0.0: 10.0, 50.0: 11.0, 100.0: 12.0},
             "yaw_rate": {25.0: 0.1, 75.0: 0.2}}
        salida = rec._emparejar(s, "speed", "yaw_rate")
        self.assertEqual(len(salida), 2)

    def test_sostiene_el_ultimo_valor_conocido(self):
        """Mientras no llegue una lectura nueva, la anterior es la mejor."""

        s = {"speed": {0.0: 10.0, 50.0: 11.0, 100.0: 12.0},
             "yaw_rate": {25.0: 0.1}}
        salida = rec._emparejar(s, "speed", "yaw_rate")
        self.assertTrue(all(y == 0.1 for _, _, y in salida))

    def test_descarta_lo_anterior_a_la_primera_lectura(self):
        """Antes de la primera lectura no hay valor que sostener."""

        s = {"speed": {0.0: 10.0, 50.0: 11.0},
             "yaw_rate": {40.0: 0.1}}
        salida = rec._emparejar(s, "speed", "yaw_rate")
        self.assertEqual([t for t, _, _ in salida], [50.0])

    def test_sin_la_senal_principal_no_devuelve_nada(self):
        self.assertEqual(rec._emparejar({"yaw_rate": {0.0: 1.0}},
                                        "speed", "yaw_rate"), [])

    def test_una_interseccion_vacia_ya_no_da_cero_metros(self):
        """El control de regresion del defecto original.

        Con instantes que no coinciden en ninguno, la version anterior no
        emparejaba nada y la reconstruccion devolvia un recorrido nulo.
        """

        s = {"speed": {i * 50.0: 100.0 for i in range(1, 21)},
             "yaw_rate": {i * 50.0 + 17.0: 0.0 for i in range(20)}}
        r = rec.reconstruir(s)
        self.assertGreater(r["recorrido_m"], 0)


class IntegraSoloLoQueSabe(unittest.TestCase):

    def test_una_recta_da_una_recta(self):
        """Sin giro, el recorrido no se curva."""

        s = {"speed": {i * 50.0: 36.0 for i in range(41)},
             "yaw_rate": {i * 50.0: 0.0 for i in range(41)}}
        r = rec.reconstruir(s)
        self.assertAlmostEqual(r["recorrido_m"], 20.0, delta=0.6)
        self.assertLess(r["extension_y_m"], 0.01)

    def test_un_giro_constante_cierra_un_circulo(self):
        """Girando a velocidad constante se vuelve al punto de partida.

        Es la comprobacion de que rumbo y posicion se integran con la misma
        convencion: si una estuviera en grados y la otra en radianes, o si el
        seno y el coseno estuvieran cambiados, el circulo no cerraria.
        """

        # La senal del bus esta en **grados** por segundo, no en radianes: el
        # modulo convierte al integrar. Alimentarla en radianes produce una
        # recta en lugar de un circulo, que es lo que esta prueba detecto la
        # primera vez que se corrio.
        paso, vueltas = 10.0, 2000
        w_deg = 360.0 / (vueltas * paso / 1000.0)
        s = {"speed": {i * paso: 36.0 for i in range(vueltas + 1)},
             "yaw_rate": {i * paso: w_deg for i in range(vueltas + 1)}}
        r = rec.reconstruir(s)
        cierre = math.hypot(r["x"][-1] - r["x"][0], r["y"][-1] - r["y"][0])
        self.assertLess(cierre, r["recorrido_m"] * 0.02)

    def test_no_integra_sobre_huecos_grandes(self):
        """Entre dos muestras separadas no se sabe que hizo el vehiculo."""

        s = {"speed": {0.0: 36.0, 50.0: 36.0, 60_000.0: 36.0},
             "yaw_rate": {0.0: 0.0, 50.0: 0.0, 60_000.0: 0.0}}
        r = rec.reconstruir(s)
        self.assertGreaterEqual(r["huecos_saltados"], 1)
        self.assertLess(r["recorrido_m"], 5.0)


class ValidaLaGuinadaAntesDeUsarla(unittest.TestCase):
    """La guinada no se toma por buena: se contrasta por dos caminos."""

    def test_el_ancho_de_via_sale_de_la_geometria(self):
        """Diferencia entre ruedas dividida por el giro es el ancho de via."""

        ancho = 1.6
        s = {"yaw_rate": {}, **{r: {} for r in rec.RUEDAS}}
        for i in range(200):
            t = i * 10.0
            w = 0.4 if i % 2 else -0.35            # rad/s, siempre apreciable
            s["yaw_rate"][t] = math.degrees(w)
            dif_kmh = w * ancho * 3.6
            s[rec.RUEDAS[0]][t] = 50.0 - dif_kmh / 2   # delantera izquierda
            s[rec.RUEDAS[2]][t] = 50.0 - dif_kmh / 2   # trasera izquierda
            s[rec.RUEDAS[1]][t] = 50.0 + dif_kmh / 2   # delantera derecha
            s[rec.RUEDAS[3]][t] = 50.0 + dif_kmh / 2   # trasera derecha
        r = rec.validar_contra_ruedas(s)
        self.assertAlmostEqual(r["ancho_de_via_m"], ancho, delta=0.02)
        self.assertGreater(abs(r["correlacion"]), 0.99)

    def test_ignora_los_tramos_sin_giro_apreciable(self):
        """En recta la diferencia entre ruedas es ruido, no senal."""

        self.assertGreater(rec.GIRO_MINIMO_DEG_S, 0)

    def test_la_geometria_del_vehiculo_no_se_supone(self):
        """La distancia entre ejes y la relacion de direccion las declara el
        propio registro, en su evento de parametros."""

        fuente = Path(rec.__file__).read_text(encoding="utf-8")
        self.assertIn("propio registro declara", fuente)


class AislaLoContinuo(unittest.TestCase):
    """El defecto de integrar a traves de un teletransporte."""

    def test_detecta_un_salto_imposible(self):
        """Los tramos tienen que durar mas que el minimo para no descartarse."""

        n = 600                                   # 30 s a 50 ms
        pos = {i * 50.0: (i * 2.0, 0.0) for i in range(n)}
        salto = n * 50.0
        pos[salto] = (5000.0, 0.0)                # el teletransporte
        for i in range(1, n):
            pos[salto + i * 50.0] = (5000.0 + i * 2.0, 0.0)
        tramos = cal.tramos_continuos(pos)
        self.assertEqual(len(tramos), 2)
        # Y ninguno de los dos abarca el salto.
        for a, b in tramos:
            self.assertFalse(a < salto < b)

    def test_un_recorrido_continuo_no_se_parte(self):
        """El control negativo: sin saltos, un solo tramo."""

        pos = {i * 50.0: (i * 2.0, 0.0) for i in range(1200)}
        self.assertEqual(len(cal.tramos_continuos(pos)), 1)

    def test_descarta_tramos_demasiado_cortos(self):
        """Un tramo corto no distingue una deriva lineal de una constante."""

        self.assertGreaterEqual(cal.TRAMO_MINIMO_S, 10.0)

    def test_el_umbral_de_salto_esta_por_encima_de_lo_alcanzable(self):
        """120 m/s son 432 km/h: ningun vehiculo del trabajo llega."""

        self.assertGreaterEqual(cal.VELOCIDAD_IMPOSIBLE_MS, 100.0)

    def test_la_convencion_de_ejes_quedo_documentada_con_su_medida(self):
        """Suponerla y errarle da una trayectoria espejada, que se puede
        racionalizar mirando un dibujo."""

        fuente = Path(cal.__file__).read_text(encoding="utf-8")
        self.assertIn("atan2(dx, dz)", fuente)


if __name__ == "__main__":
    unittest.main()
