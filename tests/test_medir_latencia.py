# -*- coding: utf-8 -*-
"""El instrumento que mide la latencia de la cadena.

El defecto que estas pruebas cierran, y que ya ocurrio
------------------------------------------------------
La primera corrida informo **cero de cuarenta mensajes detectados**. Las cuarenta
filas estaban escritas en la base. Lo que fallaba era el instrumento: su consulta
de deteccion tardaba **110.664 ms** ---recorria la tabla entera de cincuenta
millones de filas--- y la medicion esperaba cinco segundos antes de dar por
perdido lo que no veia.

Un instrumento mas lento que el fenomeno que mide no mide el fenomeno: se mide a
si mismo, y ademas informa como perdida lo que solo no alcanzo a ver. Eso es peor
que no medir, porque el numero sale con la misma cara de confiable que uno bueno.

La causa era precisa y vale como regla general: el indice de trazabilidad del
replay es **parcial**, y su predicado exige `replay_run_id IS NOT NULL` **y**
`replay_seq IS NOT NULL`. Una consulta que solo establece la primera no le permite
al planificador probar que el indice cubre el resultado, de modo que lo descarta y
recorre todo. Agregar la segunda condicion ---que no descarta ni una fila--- bajo
la consulta de 110.664 ms a **4,7 ms**.
"""

from __future__ import annotations

import statistics
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

import medir_latencia_cadena as med  # noqa: E402

from backend.models import TelemetryMessage  # noqa: E402


class ElMensajeEsValido(unittest.TestCase):
    """Si el consumidor lo rechaza, la medicion mide la validacion y no la red."""

    def test_el_mensaje_cumple_el_contrato_interno(self):
        m = med._mensaje("corrida", 7)
        validado = TelemetryMessage(**m)
        self.assertEqual(validado.session_id, med.SESION)
        self.assertEqual(validado.signal_name, "speed")
        self.assertEqual(validado.unit, "km/h")

    def test_lleva_la_identidad_de_replay_que_permite_reconocerlo(self):
        """Sin las dos claves la fila no entra al indice y no se puede buscar."""

        m = med._mensaje("corrida", 7)
        extra = m["metadata"]["extra"]
        self.assertEqual(extra["replay_run_id"], "corrida")
        self.assertEqual(extra["replay_seq"], 7)

    def test_la_sesion_es_reconocible_para_poder_apartar_estas_filas(self):
        """Van a la tabla real: tienen que poder distinguirse y borrarse."""

        self.assertEqual(med._mensaje("c", 0)["session_id"], "medicion_latencia")
        self.assertEqual(med._mensaje("c", 0)["source_type"], "instrumentacion")


class ConsultaQueUsaElIndiceParcial(unittest.TestCase):
    """El predicado completo del indice, o la consulta recorre todo."""

    def test_la_consulta_de_deteccion_exige_las_dos_columnas_no_nulas(self):
        fuente = Path(med.__file__).read_text(encoding="utf-8")
        self.assertIn("replay_seq IS NOT NULL", fuente)

    def test_la_consulta_filtra_por_corrida(self):
        fuente = Path(med.__file__).read_text(encoding="utf-8")
        self.assertIn("WHERE replay_run_id = %s", fuente)


class SeNiegaAMedirSiEsElLento(unittest.TestCase):
    """La comprobacion que faltaba la primera vez."""

    class _CursorFalso:
        def __init__(self, demora_s: float) -> None:
            self.demora_s = demora_s

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, *_a, **_k):
            # Simula el costo de la consulta sin necesitar una base.
            fin = _reloj() + self.demora_s
            while _reloj() < fin:
                pass

        def fetchall(self):
            return []

    class _ConexionFalsa:
        def __init__(self, demora_s: float) -> None:
            self.demora_s = demora_s

        def cursor(self):
            return SeNiegaAMedirSiEsElLento._CursorFalso(self.demora_s)

        def commit(self):
            pass

    def test_una_consulta_mas_lenta_que_el_muestreo_aborta(self):
        vigia = med.Vigia("corrida", muestreo_s=0.005)
        with self.assertRaises(RuntimeError) as ctx:
            vigia._verificar_que_la_consulta_no_domine(
                self._ConexionFalsa(0.020))
        self.assertIn("latencia de la cadena", str(ctx.exception))

    def test_una_consulta_rapida_deja_medir(self):
        vigia = med.Vigia("corrida", muestreo_s=0.050)
        vigia._verificar_que_la_consulta_no_domine(self._ConexionFalsa(0.001))
        self.assertLess(vigia.consulta_vacia_s, 0.050)

    def test_juzga_por_el_estado_de_regimen_y_no_por_la_primera(self):
        """La primera consulta de una conexion cuesta el triple.

        Juzgar por ella rechazaria el instrumento por un costo que no vuelve a
        pagar. Se descarta la primera y se toma la mediana de las siguientes.
        """

        fuente = Path(med.__file__).read_text(encoding="utf-8")
        self.assertIn("medidos[1:]", fuente)


class LimpiezaDeLasFilasQueEscribe(unittest.TestCase):
    """La medicion escribe en la tabla real, y tiene que poder deshacerlo.

    El borrado nombra **las dos** columnas de la marca y no solo la sesion. Una
    condicion mas laxa que la que se uso al escribir se lleva puestas filas que
    no son de la medicion; una mas estricta deja filas atras. Que las dos partes
    salgan de la misma constante es lo que impide que se separen.
    """

    def test_el_borrado_usa_las_dos_columnas_de_la_marca(self):
        fuente = Path(med.__file__).read_text(encoding="utf-8")
        i = fuente.index("def limpiar_filas_de_la_medicion")
        cuerpo = fuente[i:i + 900]
        self.assertIn("DELETE FROM telemetry_messages", cuerpo)
        self.assertIn("source_type = %s AND session_id = %s", cuerpo)

    def test_lo_que_borra_es_lo_mismo_que_escribe(self):
        """La marca del mensaje y la del borrado salen de la misma constante."""

        m = med._mensaje("c", 0)
        self.assertEqual(m["source_type"], med.ORIGEN)
        self.assertEqual(m["session_id"], med.SESION)

    def test_el_conteo_nombra_primero_la_columna_que_encabeza_el_indice(self):
        """Buscando solo por sesion la consulta tarda diecisiete segundos.

        Es el mismo defecto que dejo la primera medicion en cero: una consulta
        que no puede aprovechar el indice recorre la tabla entera.
        """

        fuente = Path(med.__file__).read_text(encoding="utf-8")
        i = fuente.index("def contar_filas_de_la_medicion")
        cuerpo = fuente[i:i + 900]
        self.assertIn("WHERE source_type = %s AND session_id = %s", cuerpo)

    def test_la_limpieza_es_opcional_y_no_se_hace_sola(self):
        """Borrar de la base no puede ser el comportamiento por omision."""

        fuente = Path(med.__file__).read_text(encoding="utf-8")
        self.assertIn('"--limpiar", action="store_true"', fuente)


class Percentiles(unittest.TestCase):

    def test_devuelve_el_extremo_pedido(self):
        datos = [float(x) for x in range(1, 101)]
        self.assertAlmostEqual(med._percentil(datos, 0.50), 50.0, delta=1.0)
        self.assertAlmostEqual(med._percentil(datos, 0.99), 100.0, delta=1.0)

    def test_una_lista_vacia_no_devuelve_cero(self):
        """Un cero se leeria como "la latencia fue nula"."""

        self.assertNotEqual(med._percentil([], 0.5), 0.0)


class ElSesgoDelMuestreoSeDeclara(unittest.TestCase):
    """La base no guarda cuando escribio: la llegada se detecta consultando.

    Eso agrega un sesgo positivo acotado por el intervalo de muestreo. Se
    informa en lugar de descontarse: descontar un promedio supuesto seria
    inventar precision.
    """

    def test_el_intervalo_por_omision_deja_el_sesgo_chico_frente_a_la_latencia(self):
        # La latencia medida esta en el orden de los 300 ms; un muestreo de
        # 25 ms deja el sesgo por debajo del diez por ciento.
        self.assertLessEqual(med.MUESTREO_MS, 30.0)

    def test_el_resultado_informa_el_intervalo_usado(self):
        fuente = Path(med.__file__).read_text(encoding="utf-8")
        self.assertIn('"muestreo_ms"', fuente)


class CantidadDerivadaDeLaDuracion(unittest.TestCase):
    """Comparar tasas exige que cada corrida dure lo mismo.

    Con una cantidad fija, cuatrocientos mensajes son veinte segundos a veinte
    por segundo y dos decimas a dos mil, y una corrida de dos decimas no llega a
    llenar un lote ni una vez: las dos tasas no serian comparables.
    """

    def test_la_cantidad_sale_de_la_duracion_y_no_es_fija(self):
        fuente = Path(med.__file__).read_text(encoding="utf-8")
        self.assertIn("duracion-s", fuente)
        self.assertIn("minimo_mensajes", fuente)
        self.assertIn("maximo_mensajes", fuente)


def _reloj() -> float:
    import time
    return time.perf_counter()


if __name__ == "__main__":
    unittest.main()
