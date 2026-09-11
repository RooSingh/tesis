# -*- coding: utf-8 -*-
"""El instrumento que sigue un mensaje por las cinco etapas de la cadena.

QUE TIENE QUE CUIDAR UNA PRUEBA DE ESTE INSTRUMENTO
---------------------------------------------------
Este guion existe para decir si el dato se transformo en el camino. Un
instrumento asi falla de dos maneras, y las dos son peores que no tenerlo:

- **callar una diferencia real**: comparar de menos ---no mirar la unidad, no
  mirar el instante, normalizar de mas--- y declarar que las cinco etapas
  coinciden cuando no coinciden;
- **inventar una diferencia**: acusar de transformacion a un redondeo declarado,
  a un cambio de formato de fecha, o a un mensaje que no se encontro porque la
  consulta estaba mal armada.

Las pruebas de abajo van contra esas dos cosas. Ninguna necesita broker ni base:
lo que se verifica es la parte que decide, que es donde un defecto pasa
inadvertido.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

import rastrear_un_mensaje as ras  # noqa: E402

from backend.db import _identidad_replay  # noqa: E402
from backend.models import TelemetryMessage  # noqa: E402


INSTANTE = "2026-09-05T00:36:24.774981+00:00"


def _mensaje(valor=231.0, senal="speed", unidad="km/h"):
    """Un mensaje con la forma exacta que produce el adaptador."""

    return {
        "timestamp": INSTANTE,
        "vehicle_id": "f1_25:session:3731090176871608020:car:19",
        "driver_id": "f1_25:car:19",
        "session_id": "f1_25:session:3731090176871608020",
        "lap_id": None,
        "source_type": "f1_25_udp_simulation",
        "quality_flag": "simulated_f1_25",
        "signal_name": senal,
        "value": valor,
        "unit": unidad,
        "metadata": {"reference_type": "f1_25_udp",
                     "extra": {"paquete": "car_telemetry",
                               "desplazamiento_captura_us": 7202073}},
    }


def _etapa(valor=231.0, unidad="km/h", instante=INSTANTE):
    return {"valor": valor, "unidad": unidad, "instante_del_dato": instante}


class ElegirQueMensajeRastrear(unittest.TestCase):
    """Rastrear la muestra equivocada vuelve el resultado no concluyente."""

    def test_un_cero_no_sirve_porque_es_lo_que_deja_una_perdida(self):
        self.assertFalse(ras.es_valor_distinguible(0.0))
        self.assertFalse(ras.es_valor_distinguible(False))
        self.assertFalse(ras.es_valor_distinguible("   "))

    def test_un_valor_que_si_distingue_se_acepta(self):
        self.assertTrue(ras.es_valor_distinguible(231.0))
        self.assertTrue(ras.es_valor_distinguible(True))
        self.assertTrue(ras.es_valor_distinguible("intermedio"))

    def test_toma_el_primero_de_la_senal_pedida_y_no_de_otra(self):
        numerados = [
            (0, _mensaje(valor=300.0, senal="engine_rpm", unidad="rpm")),
            (1, _mensaje(valor=0.0)),
            (2, _mensaje(valor=231.0)),
        ]
        seq, elegido = ras.elegir_mensaje(iter(numerados), senal="speed")
        self.assertEqual(seq, 2)
        self.assertEqual(elegido["signal_name"], "speed")
        self.assertEqual(elegido["value"], 231.0)

    def test_con_un_numero_pedido_se_toma_ese_y_no_se_juzga_su_valor(self):
        """Quien pide una secuencia concreta sabe lo que pide, aunque valga cero."""

        numerados = [(0, _mensaje(valor=231.0)), (7, _mensaje(valor=0.0))]
        seq, elegido = ras.elegir_mensaje(iter(numerados), senal="speed",
                                          secuencia=7)
        self.assertEqual(seq, 7)
        self.assertEqual(elegido["value"], 0.0)

    def test_si_no_hay_ninguno_lo_dice_en_lugar_de_devolver_cualquiera(self):
        numerados = [(0, _mensaje(valor=0.0))]
        self.assertIsNone(ras.elegir_mensaje(iter(numerados), senal="speed"))


class LaIdentidadQueSeLeInyecta(unittest.TestCase):
    """Sin identidad buscable, el mensaje se persiste y no se puede encontrar."""

    def test_la_base_lee_la_identidad_del_lugar_donde_el_guion_la_escribe(self):
        """Ata el guion a `backend/db.py`: si uno cambia de lugar, esto muere."""

        mensaje = ras.marcar_identidad(_mensaje(), "rastreo:abc:5:20260911T000000Z", 5)
        validado = TelemetryMessage(**mensaje)
        self.assertEqual(_identidad_replay(validado.metadata),
                         ("rastreo:abc:5:20260911T000000Z", 5))

    def test_dos_rastreos_del_mismo_mensaje_no_comparten_identidad(self):
        """Repetirla haria que el segundo rastreo leyera la fila del primero.

        La insercion usa `ON CONFLICT DO NOTHING`: con la misma identidad, el
        segundo rastreo no escribiria nada, encontraria la fila vieja y daria
        correcto sin haber probado nada.
        """

        uno = ras.identidad_de_rastreo("1498c22eef8dc001", 2191,
                                       datetime(2026, 9, 11, 20, 0, 0, tzinfo=timezone.utc))
        otro = ras.identidad_de_rastreo("1498c22eef8dc001", 2191,
                                        datetime(2026, 9, 11, 20, 0, 1, tzinfo=timezone.utc))
        self.assertNotEqual(uno, otro)

    def test_la_identidad_dice_de_que_captura_y_de_que_mensaje_salio(self):
        identidad = ras.identidad_de_rastreo("1498c22eef8dc001dab6", 2191,
                                             datetime(2026, 9, 11, tzinfo=timezone.utc))
        self.assertIn("1498c22eef8dc001", identidad)
        self.assertIn("2191", identidad)


class CompararLasEtapasEntreSi(unittest.TestCase):
    """Comparar de menos declara iguales dos etapas que no lo son."""

    def _cinco(self, **cambios):
        etapas = {nombre: _etapa() for nombre in ras.ETAPAS}
        etapas.update(cambios)
        return etapas

    def test_cinco_etapas_iguales_no_dan_ninguna_diferencia(self):
        self.assertEqual(ras.discrepancias(self._cinco()), [])

    def test_un_valor_cambiado_en_el_medio_se_informa(self):
        etapas = self._cinco(consumidor=_etapa(valor=232.0))
        problemas = ras.discrepancias(etapas)
        self.assertEqual(len(problemas), 1)
        self.assertIn("consumidor", problemas[0])
        self.assertIn("valor", problemas[0])

    def test_una_unidad_cambiada_se_informa_aunque_el_numero_coincida(self):
        """Es el defecto que ninguna medicion de latencia podria detectar."""

        etapas = self._cinco(base=_etapa(unidad="m/s"))
        problemas = ras.discrepancias(etapas)
        self.assertEqual(len(problemas), 1)
        self.assertIn("unidad", problemas[0])

    def test_un_instante_corrido_se_informa(self):
        etapas = self._cinco(base=_etapa(instante="2026-09-05T00:36:25.774981+00:00"))
        problemas = ras.discrepancias(etapas)
        self.assertEqual(len(problemas), 1)
        self.assertIn("instante", problemas[0])

    def test_una_etapa_ausente_es_una_diferencia_y_no_un_silencio(self):
        etapas = self._cinco()
        del etapas["base"]
        problemas = ras.discrepancias(etapas)
        self.assertEqual(len(problemas), 1)
        self.assertIn("no aparecio", problemas[0])

    def test_una_etapa_omitida_a_proposito_no_se_cuenta_como_diferencia(self):
        etapas = self._cinco(consulta={"omitida": "pedida con --sin-api"})
        self.assertEqual(ras.discrepancias(etapas), [])

    def test_el_redondeo_declarado_de_la_consulta_no_es_una_transformacion(self):
        """La ruta redondea a cuatro decimales y lo dice en su codigo."""

        etapas = {nombre: _etapa(valor=231.000004) for nombre in ras.ETAPAS}
        etapas["consulta"] = _etapa(valor=231.0)
        self.assertEqual(ras.discrepancias(etapas), [])

    def test_ese_perdon_no_alcanza_a_las_etapas_anteriores(self):
        """El redondeo es de la ruta de consulta: en la base seria una perdida."""

        etapas = {nombre: _etapa(valor=231.000004) for nombre in ras.ETAPAS}
        etapas["base"] = _etapa(valor=231.0)
        problemas = ras.discrepancias(etapas)
        self.assertEqual(len(problemas), 1)
        self.assertIn("base", problemas[0])

    def test_una_diferencia_mayor_que_el_redondeo_si_se_informa(self):
        etapas = self._cinco(consulta=_etapa(valor=231.1))
        self.assertEqual(len(ras.discrepancias(etapas)), 1)

    def test_un_binario_llevado_a_uno_por_la_consulta_no_es_una_diferencia(self):
        """La ruta lleva los canales binarios a 1 y 0 para poder graficarlos."""

        etapas = self._cinco(generador=_etapa(valor=True),
                             intermediario=_etapa(valor=True),
                             consumidor=_etapa(valor=True),
                             base=_etapa(valor=True),
                             consulta=_etapa(valor=1.0))
        self.assertEqual(ras.discrepancias(etapas), [])

    def test_un_binario_invertido_si_es_una_diferencia(self):
        etapas = self._cinco(generador=_etapa(valor=True),
                             intermediario=_etapa(valor=True),
                             consumidor=_etapa(valor=True),
                             base=_etapa(valor=True),
                             consulta=_etapa(valor=0.0))
        self.assertEqual(len(ras.discrepancias(etapas)), 1)

    def test_todo_se_compara_contra_el_generador_y_no_contra_la_etapa_previa(self):
        """Una transformacion que se revierte igual hay que verla.

        Comparando cada etapa con la anterior, un valor que cambia en el
        intermediario y vuelve en el consumidor daria dos diferencias y despues
        ninguna en la base. Contra el generador, las dos etapas afectadas salen
        nombradas y las sanas no.
        """

        etapas = self._cinco(intermediario=_etapa(valor=999.0))
        problemas = ras.discrepancias(etapas)
        self.assertEqual(len(problemas), 1)
        self.assertIn("intermediario", problemas[0])


class LasFechasEscritasDeDistintaForma(unittest.TestCase):
    """Un cambio de formato no es un cambio de instante."""

    def test_la_misma_fecha_escrita_distinto_es_el_mismo_instante(self):
        self.assertTrue(ras.mismo_instante(
            "2026-09-05T00:36:24.774981+00:00",
            "2026-09-05T00:36:24.774981Z"))
        self.assertTrue(ras.mismo_instante(
            "2026-09-05T00:36:24.774981+00:00",
            datetime(2026, 9, 5, 0, 36, 24, 774981, tzinfo=timezone.utc)))

    def test_dos_instantes_distintos_no_se_confunden(self):
        self.assertFalse(ras.mismo_instante(
            "2026-09-05T00:36:24.774981+00:00",
            "2026-09-05T00:36:24.774982+00:00"))

    def test_un_desfase_horario_no_se_toma_por_el_mismo_instante_escrito_distinto(self):
        self.assertFalse(ras.mismo_instante(
            "2026-09-05T00:36:24.774981+00:00",
            "2026-09-05T00:36:24.774981-03:00"))


class LeerLaRespuestaDeLaInterfaz(unittest.TestCase):
    """Leer mal la respuesta informaria una perdida que no ocurrio."""

    def _respuesta(self, marcas=(INSTANTE,), valores=(231.0,)):
        return {
            "vehiculos": {
                "f1_25:session:3731090176871608020:car:19": {
                    "timestamp_utc": list(marcas),
                    "tiempo_s": [0.0] * len(marcas),
                    "speed": list(valores),
                },
            },
            "unidades": {"speed": "km/h"},
            "muestras": len(marcas),
        }

    def test_devuelve_el_valor_del_instante_pedido_y_no_el_primero(self):
        respuesta = self._respuesta(
            marcas=("2026-09-05T00:36:24.000000+00:00", INSTANTE),
            valores=(11.0, 231.0))
        leido = ras.valor_de_la_consulta(
            respuesta, "speed", "f1_25:session:3731090176871608020:car:19",
            INSTANTE)
        self.assertEqual(leido["valor"], 231.0)
        self.assertEqual(leido["unidad"], "km/h")

    def test_si_ese_instante_no_esta_lo_dice_en_lugar_de_devolver_otro(self):
        respuesta = self._respuesta(marcas=("2026-09-05T00:36:24.000000+00:00",),
                                    valores=(11.0,))
        self.assertIsNone(ras.valor_de_la_consulta(
            respuesta, "speed", "f1_25:session:3731090176871608020:car:19",
            INSTANTE))

    def test_un_vehiculo_ausente_no_se_confunde_con_otro(self):
        self.assertIsNone(ras.valor_de_la_consulta(
            self._respuesta(), "speed", "otro:vehiculo", INSTANTE))


class LaDireccionConQueSeConsulta(unittest.TestCase):
    """Una direccion mal armada devuelve vacio y parece una perdida del sistema."""

    def test_el_mas_del_huso_horario_viaja_codificado(self):
        """Sin codificar, el `+` de `+00:00` es un espacio y el instante cambia."""

        url = ras.url_de_consulta("http://127.0.0.1:8000", _mensaje())
        self.assertIn("%2B00%3A00", url)
        self.assertNotIn("+00:00", url)

    def test_pide_el_instante_exacto_por_los_dos_extremos(self):
        url = ras.url_de_consulta("http://127.0.0.1:8000", _mensaje())
        self.assertIn("desde=", url)
        self.assertIn("hasta=", url)
        self.assertEqual(url.count("2026-09-05T00%3A36%3A24.774981"), 2)

    def test_pregunta_por_la_senal_y_el_vehiculo_del_mensaje(self):
        url = ras.url_de_consulta("http://127.0.0.1:8000", _mensaje())
        self.assertIn("senales=speed", url)
        self.assertIn("car%3A19", url)

    def test_una_base_con_barra_al_final_no_duplica_la_barra(self):
        url = ras.url_de_consulta("http://127.0.0.1:8000/", _mensaje())
        self.assertNotIn("8000//", url)


class LeerLaFilaPersistida(unittest.TestCase):
    """El valor vive en tres columnas segun su tipo; leer la que no es lo pierde."""

    def test_un_valor_numerico_se_lee_de_su_columna(self):
        self.assertEqual(ras.valor_de_la_fila(
            {"value_numeric": 231.0, "value_boolean": None, "value_text": None}),
            231.0)

    def test_un_valor_booleano_se_lee_de_la_suya(self):
        self.assertIs(ras.valor_de_la_fila(
            {"value_numeric": None, "value_boolean": True, "value_text": None}),
            True)

    def test_un_falso_persistido_no_se_confunde_con_un_valor_ausente(self):
        """`False` es un valor guardado; tratarlo como nulo lo perderia."""

        self.assertIs(ras.valor_de_la_fila(
            {"value_numeric": None, "value_boolean": False, "value_text": None}),
            False)

    def test_un_texto_se_lee_de_la_suya(self):
        self.assertEqual(ras.valor_de_la_fila(
            {"value_numeric": None, "value_boolean": None, "value_text": "medio"}),
            "medio")

    def test_una_fila_sin_ningun_valor_devuelve_nada(self):
        self.assertIsNone(ras.valor_de_la_fila(
            {"value_numeric": None, "value_boolean": None, "value_text": None}))


if __name__ == "__main__":
    unittest.main()
