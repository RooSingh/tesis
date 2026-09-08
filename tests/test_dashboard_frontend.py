"""Comprobaciones de contrato del dashboard sin dependencias de navegador."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


RAIZ = Path(__file__).resolve().parents[1]
APP = RAIZ / "dashboard" / "app.js"


class DashboardFrontendTests(unittest.TestCase):
    def test_javascript_es_valido_para_el_motor_del_navegador(self) -> None:
        proceso = subprocess.run(
            ["node", "--check", str(APP)], capture_output=True, text=True,
            check=False,
        )
        self.assertEqual(proceso.returncode, 0, proceso.stderr)

    def test_los_contratos_de_escritura_coinciden_con_fastapi(self) -> None:
        codigo = APP.read_text(encoding="utf-8")
        self.assertIn('cuerpo: { session_key: sessionKey, descargar_telemetria: false }', codigo)
        self.assertIn('cuerpo: { segmentos: segmentos, plataforma: "TOYOTA_RAV4_TSS2", etapa: "cargar" }', codigo)
        self.assertIn('"?confirmar=true"', codigo)
        self.assertIn("d.capturas_cerradas", codigo)
        self.assertIn("d.borradas", codigo)
        self.assertNotIn("d.sesiones_cerradas", codigo)
        self.assertNotIn("d.filas_borradas", codigo)

    def test_no_hay_fallback_de_series_entre_vehiculos(self) -> None:
        codigo = APP.read_text(encoding="utf-8")
        self.assertNotIn("bloque.vehiculos[claveVehiculoPropio()]", codigo)
        self.assertNotIn("bloque.vehiculos[Object.keys(bloque.vehiculos)[0]]", codigo)
        self.assertNotIn("(v / 62)", codigo)


class AyudantesDeSerieTests(unittest.TestCase):
    """Comportamiento, no presencia de texto.

    Las pruebas de arriba comprueban que ciertas cadenas esten en el archivo, y
    eso alcanza para un contrato de nombres pero no dice nada de lo que el
    codigo hace. Este arnes **extrae las funciones puras del `app.js` que se
    publica** y las ejecuta en node con casos concretos: cero medido contra
    cero inventado, series de distinto largo, escalas sin muestras.
    """

    def _correr(self, nombre: str) -> None:
        arnes = RAIZ / "tests" / "js" / nombre
        proceso = subprocess.run(
            ["node", str(arnes)], capture_output=True, text=True, check=False,
        )
        self.assertEqual(proceso.returncode, 0,
                         proceso.stdout + "\n" + proceso.stderr)

    def test_los_ayudantes_de_serie_se_comportan_como_se_espera(self) -> None:
        self._correr("ayudantes_de_serie.js")

    def test_el_camino_vivo_aisla_sesiones_y_no_retrocede(self) -> None:
        """Adopcion, duplicados, snapshot atrasado y A -> B -> A."""

        self._correr("aislamiento_de_sesiones.js")

    def test_las_continuaciones_asincronas_no_pisan_la_sesion_vigente(self) -> None:
        """El .then que corre cuando la consulta vuelve, con el tablero en otro estado.

        Comprobar que el contador de aperturas da numeros distintos demuestra
        que la aritmetica funciona, no que una respuesta atrasada no escriba
        encima. Este arnes resuelve las respuestas a mano y mira el estado
        despues.
        """

        self._correr("continuaciones_asincronas.js")


class RepresentacionDeDatosVivosTests(unittest.TestCase):
    """Lo que no puede volver, por como se rompio.

    Cada una de estas cadenas es un defecto que estuvo en el archivo. Se las
    prohibe por texto porque son formas de escribir, no comportamientos: no hay
    entrada que las distinga si alguien las vuelve a introducir en otro sitio.
    """

    def setUp(self) -> None:
        self.codigo = APP.read_text(encoding="utf-8")

    def test_ningun_canal_se_recorta_con_el_indice_de_otro(self) -> None:
        # `series[0].length` era la cantidad de muestras de la velocidad del
        # primer vehiculo, y ese par de indices recortaba todos los canales de
        # todos los vehiculos. Sin velocidad valia cero y no se dibujaba nada.
        self.assertNotIn("const total = series[0].length", self.codigo)
        self.assertNotIn(".slice(desde, hasta)", self.codigo)

    def test_el_vivo_no_exige_una_vuelta_historica(self) -> None:
        self.assertIn("const enVivo = estadoSesion === \"vivo\";", self.codigo)
        self.assertIn("if (!enVivo && !estado.series[vueltaElegida])", self.codigo)

    def test_los_vehiculos_salen_del_modo_vigente(self) -> None:
        self.assertIn("function vehiculosConTraza()", self.codigo)
        self.assertIn("[...vivo.series.keys()]", self.codigo)

    def test_el_camino_vivo_no_convierte_con_Number_a_secas(self) -> None:
        # `Number(null)` y `Number("")` valen cero, y cero es un valor legitimo
        # de estos canales: los ceros inventados no se distinguirian.
        self.assertNotIn("const numero = Number(m.value);", self.codigo)
        self.assertNotIn('typeof m.value === "boolean" ? Number(m.value) : Number(m.value)',
                         self.codigo)
        self.assertIn("const numero = numeroMedido(m.value);", self.codigo)

    def test_la_muestra_viva_conserva_su_reloj(self) -> None:
        self.assertIn("function relojDeMuestra(m)", self.codigo)
        self.assertIn("serie.push([distancia, valor, relojDeMuestra(m)]);", self.codigo)

    def test_el_csv_se_alinea_por_distancia_y_no_por_posicion(self) -> None:
        # Alineado por indice, una fila podia juntar los 100 m de una señal con
        # los 300 m de otra: `serieDeCanal` descarta nulos y las columnas
        # quedan de distinto largo.
        self.assertNotIn("columnas.forEach(col => fila.push(col[i][1].toFixed(3)));",
                         self.codigo)
        self.assertIn("col.has(m) ? col.get(m).toFixed(3) : \"\"", self.codigo)

    def test_el_vivo_construye_su_propio_recorrido(self) -> None:
        """En vivo no hay trazado persistido que consultar: se mide.

        El flujo trae `world_position_x` y `world_position_z`, que son las dos
        senales con las que el backend arma el trazado guardado. Se dibuja eso
        y se declara que esta a medio recorrer; no se usa una geometria de
        catalogo ni se inventa un circuito.
        """

        self.assertIn("function anotarPosicionViva(", self.codigo)
        self.assertIn("function armarTrazadoVivo(", self.codigo)
        self.assertIn("function congelarTrazadoVivo(", self.codigo)
        self.assertIn("recorrido en construcción, medido en vivo", self.codigo)

    def test_el_catalogo_no_pisa_una_sesion_viva(self) -> None:
        """El catalogo llega despues que la primera muestra del flujo.

        Sin esta guarda, abrir el tablero con telemetria entrando dejaba el
        trazado de una carrera historica debajo del coche de la sesion en curso.
        """

        self.assertIn("if (vivo.sesion && !pedida) {", self.codigo)

    def test_el_lienzo_no_se_reasigna_en_cada_dibujo(self) -> None:
        self.assertIn("function ajustarLienzo(cv, w, h)", self.codigo)
        self.assertNotIn("cv.width = w * dpr; cv.height = h * dpr;", self.codigo)


if __name__ == "__main__":
    unittest.main()
