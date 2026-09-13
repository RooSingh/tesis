# -*- coding: utf-8 -*-
"""Una sesion se declara cuando empieza a llegar, no cuando termina.

EL DEFECTO, MEDIDO DOS VECES EN DOS DIAS. El catalogo de sesiones se escribe en
`backend/ingesta.py`, y lo primero que hace es:

    if trabajo.estado != "terminado":
        return

Un corte de corriente **no tiene final**. El 2026-09-12 la Raspberry perdio la
corriente en plena captura y dejo `f1_25:session:10998240251769839758` con
393.128 filas en la base y fuera del catalogo: no se podia abrir. El 2026-09-13,
en el experimento repetido a proposito, volvio a pasar exactamente igual:
579.548 filas, catalogo sin moverse de 29.

No es un defecto de implementacion, es **la forma del diseño**: cualquier cosa
que se escriba al cerrar la pierde quien no llega a cerrar. Y no se arregla
aguantando mas: se arregla escribiendo antes.

QUIEN LO DECLARA, Y POR QUE NO EL CAPTURADOR. El capturador sabe la sesion en
cuanto la detecta ---lo imprime: «sesion detectada, grabando...»--- pero solo
cubre **un** camino, el de F1 25 en vivo. El consumidor es el unico que ve
aterrizar cada fila venga de donde venga: captura, reinyeccion, importacion o
archivo subido. Un solo sitio cierra los cuatro.

POR QUE ESCRIBIR TEMPRANO NO ESCRIBE UNA MENTIRA. `refrescar_sesion()` no
guarda lo que le pasen: **recuenta desde la tabla**. De modo que llamarla a los
diez segundos de sesion no deja una promesa vacia, deja lo que es cierto a los
diez segundos, y cada llamada posterior lo corrige sola. Una sesion cortada
queda catalogada con los numeros de hace un minuto ---visible y abrible--- en
lugar de invisible con los numeros exactos.

LO QUE ESTAS PRUEBAS CUIDAN SOBRE TODO ES EL COSTO. Recontar una sesion cuesta
entre 0,65 s y 7,2 s. Llamarlo por cada lote seria varias veces por segundo
durante una carrera: convertiria el arreglo en un problema peor que el que
resuelve. Se declara **una vez al aparecer** y despues **como mucho cada tanto**.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from backend import mqtt_consumer  # noqa: E402


class Reloj:
    """Un reloj que no avanza solo, para poder medir el ritmo sin esperar."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def avanzar(self, segundos: float) -> None:
        self.t += segundos


class LasSesionesSeDeclaranAlLlegar(unittest.TestCase):

    def setUp(self) -> None:
        self.declaradas: list[str] = []
        self.reloj = Reloj()
        mqtt_consumer.declaracion.olvidar_todo()
        self.addCleanup(mqtt_consumer.declaracion.olvidar_todo)
        parches = [
            patch.object(mqtt_consumer.catalogo_sesiones,
                         "refrescar_en_segundo_plano",
                         side_effect=self.declaradas.append),
            patch.object(mqtt_consumer.declaracion, "_ahora", self.reloj),
        ]
        for p in parches:
            p.start()
            self.addCleanup(p.stop)

    def _llegan(self, *session_ids: str) -> None:
        mqtt_consumer.declaracion.vieron(list(session_ids))

    # ---- que se declare ----

    def test_una_sesion_nueva_se_declara_enseguida(self) -> None:
        """Es todo el arreglo: no se espera al cierre, que puede no llegar."""

        self._llegan("f1_25:session:18356838876920639459")
        self.assertEqual(self.declaradas, ["f1_25:session:18356838876920639459"])

    def test_un_corte_a_los_cinco_minutos_deja_la_sesion_catalogada(self) -> None:
        """El caso del 2026-09-13, reproducido con el reloj en la mano."""

        sesion = "f1_25:session:18356838876920639459"
        self._llegan(sesion)                 # primer lote
        for _ in range(20):                  # cinco minutos de carrera
            self.reloj.avanzar(15)
            self._llegan(sesion)
        # Aqui se corta la corriente: nadie cierra nada, nunca.
        self.assertIn(
            sesion, self.declaradas,
            "la sesion quedaria huerfana otra vez: 579.548 filas en la base y "
            "fuera del catalogo")

    def test_varias_sesiones_a_la_vez_se_declaran_todas(self) -> None:
        self._llegan("a", "b", "c")
        self.assertEqual(sorted(self.declaradas), ["a", "b", "c"])

    # ---- y que no cueste una fortuna ----

    def test_el_mismo_lote_repetido_no_recuenta_cada_vez(self) -> None:
        """Recontar cuesta entre 0,65 s y 7,2 s. Por lote seria insostenible."""

        for _ in range(500):
            self._llegan("una")
        self.assertEqual(
            len(self.declaradas), 1,
            "se pidio el recuento %d veces para la misma sesion: a 0,65 s cada "
            "uno son %.0f segundos de base por nada"
            % (len(self.declaradas), len(self.declaradas) * 0.65))

    def test_pasado_el_intervalo_se_vuelve_a_declarar(self) -> None:
        """Pero tampoco una sola vez: los numeros tienen que ponerse al dia."""

        self._llegan("una")
        self.reloj.avanzar(mqtt_consumer.declaracion.CADA_CUANTO_S + 1)
        self._llegan("una")
        self.assertEqual(len(self.declaradas), 2,
                         "la sesion se declaro al principio y nunca mas: el "
                         "catalogo se quedaria con los numeros del primer lote")

    def test_justo_antes_del_intervalo_todavia_no(self) -> None:
        self._llegan("una")
        self.reloj.avanzar(mqtt_consumer.declaracion.CADA_CUANTO_S - 1)
        self._llegan("una")
        self.assertEqual(len(self.declaradas), 1)

    def test_el_intervalo_es_de_a_minuto_y_no_de_a_segundo(self) -> None:
        """Un numero elegido, no heredado de un ejemplo."""

        self.assertGreaterEqual(
            mqtt_consumer.declaracion.CADA_CUANTO_S, 30,
            "el intervalo quedo tan corto que el recuento vuelve a ser continuo")

    def test_la_memoria_de_lo_visto_no_crece_sin_limite(self) -> None:
        """Una instalacion larga no puede acumular una entrada por sesion vista."""

        for i in range(5000):
            self._llegan("sesion-%d" % i)
        self.assertLessEqual(
            mqtt_consumer.declaracion.cuantas_recuerda(),
            mqtt_consumer.declaracion.TOPE_RECORDADAS,
            "la tabla de sesiones vistas crece sin tope: es una fuga de memoria "
            "en un proceso que corre para siempre")

    # ---- y que no pueda tumbar al consumidor ----

    def test_si_el_catalogo_falla_el_consumidor_sigue(self) -> None:
        """Persistir es obligatorio; catalogar es deseable. No pueden colgarse."""

        with patch.object(mqtt_consumer.catalogo_sesiones,
                          "refrescar_en_segundo_plano",
                          side_effect=RuntimeError("la base no esta")):
            mqtt_consumer.declaracion.vieron(["una"])  # no debe levantar

    def test_una_sesion_sin_nombre_no_se_declara(self) -> None:
        self._llegan("", None)  # type: ignore[arg-type]
        self.assertEqual(self.declaradas, [])


def mensaje(indice: int, sesion: str):
    """Un mensaje como los que el consumidor persiste, con su sesion."""

    from backend.models import TelemetryMessage
    return TelemetryMessage.model_validate({
        "timestamp": "2026-09-13T20:36:%02d+00:00" % indice,
        "vehicle_id": "f1_25:%s:car:0" % sesion,
        "driver_id": "f1_25:driver:propio",
        "session_id": sesion,
        "lap_id": None,
        "source_type": "f1_25_udp_simulation",
        "signal_name": "speed",
        "value": 210.0,
        "unit": "km/h",
        "quality_flag": "ok",
        "metadata": {},
    })


class DeVerdadPorElCaminoQueUsaElConsumidor(unittest.TestCase):
    """Las pruebas de arriba leen el codigo; esta lo ejecuta.

    Una prueba estructural dice que la llamada esta escrita. Solo esta dice que
    al escribir un lote la sesion termina declarada, que es lo que se prometio.
    """

    def setUp(self) -> None:
        mqtt_consumer.declaracion.olvidar_todo()
        self.addCleanup(mqtt_consumer.declaracion.olvidar_todo)

    def test_escribir_un_lote_declara_su_sesion(self) -> None:
        declaradas: list[str] = []
        sesion = "f1_25:session:18356838876920639459"
        buffer = mqtt_consumer.TelemetryBatchBuffer(
            writer=lambda lote: len(lote), batch_size=2)
        with patch.object(mqtt_consumer.catalogo_sesiones,
                          "refrescar_en_segundo_plano",
                          side_effect=declaradas.append):
            buffer.enqueue(mensaje(1, sesion))
            buffer.enqueue(mensaje(2, sesion))
            escritas = buffer.flush()

        self.assertEqual(escritas, 2, "el lote no se escribio")
        self.assertEqual(
            declaradas, [sesion],
            "se escribieron filas y la sesion no quedo declarada: un corte "
            "ahora mismo la dejaria huerfana igual que el 2026-09-13")

    def test_un_lote_sin_session_id_no_rompe_el_flush(self) -> None:
        """Catalogar no puede hacer fallar a escribir, y casi lo hace.

        La primera version hacia `m.session_id` directo y reventaba con un lote
        de cualquier otra cosa. Eso no es un detalle de arnes: la llamada vive
        **entre escribir y confirmar**, de modo que una excepcion ahi salta por
        encima de `_confirmar_cubiertos()`, el lote queda escrito y sin
        confirmar, y el intermediario lo reenvia entero.
        """

        escritos: list[int] = []
        buffer = mqtt_consumer.TelemetryBatchBuffer(
            writer=lambda lote: escritos.append(len(lote)) or len(lote),
            batch_size=2)
        with buffer.lock:
            buffer.pending.extend(["no soy un mensaje", "yo tampoco"])
        self.assertEqual(buffer.flush(), 2,
                         "el flush fallo por culpa de la declaracion")
        self.assertEqual(escritos, [2])

    def test_si_la_escritura_falla_no_se_declara_nada(self) -> None:
        """Declarar una sesion que no se escribio la BORRA del catalogo.

        `refrescar_sesion()` recuenta, no encuentra filas y hace `DELETE`. O
        sea que declarar de mas sobre una escritura fallida no es inocuo: se
        lleva por delante lo que hubiera catalogado antes.
        """

        declaradas: list[str] = []

        def _explotar(_lote):
            raise RuntimeError("la base no esta")

        buffer = mqtt_consumer.TelemetryBatchBuffer(
            writer=_explotar, batch_size=2)
        with patch.object(mqtt_consumer.catalogo_sesiones,
                          "refrescar_en_segundo_plano",
                          side_effect=declaradas.append):
            buffer.enqueue(mensaje(1, "f1_25:session:1"))
            buffer.enqueue(mensaje(2, "f1_25:session:1"))
            buffer.flush()

        self.assertEqual(declaradas, [],
                         "se declaro una sesion cuya escritura fallo")


class ElConsumidorLoLlama(unittest.TestCase):
    """Que la pieza exista no sirve si nadie la usa desde donde llegan los datos."""

    def test_flush_declara_lo_que_acaba_de_escribir(self) -> None:
        fuente = (RAIZ / "backend" / "mqtt_consumer.py").read_text(encoding="utf-8")
        cuerpo = fuente.split("def flush(")[1].split("\n    def ")[0]
        self.assertIn(
            "declaracion.vieron", cuerpo,
            "`flush()` escribe en la base y no declara la sesion: el catalogo "
            "sigue dependiendo de que alguien cierre el trabajo")

    def test_se_declara_despues_de_escribir_y_no_antes(self) -> None:
        """Declarar lo que todavia no se escribio es declarar un deseo."""

        fuente = (RAIZ / "backend" / "mqtt_consumer.py").read_text(encoding="utf-8")
        cuerpo = fuente.split("def flush(")[1].split("\n    def ")[0]
        self.assertLess(
            cuerpo.index("self.writer(batch)"), cuerpo.index("declaracion.vieron"),
            "se declara antes de escribir: si la escritura falla, el catalogo "
            "afirma una sesion que no existe")


if __name__ == "__main__":
    unittest.main()
