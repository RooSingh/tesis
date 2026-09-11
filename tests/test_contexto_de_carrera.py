"""El contexto de carrera de un instante no se adelanta ni se vence parejo.

`obtener_contexto_racing_en_instante` resuelve, para un instante UTC, el puesto,
la diferencia al lider, el neumatico y el clima de una sesion OpenF1. Tenia tres
defectos que compartian causa: leer las tres magnitudes con la misma regla,
cuando las tres tienen naturalezas distintas.

MEDIDO sobre la sesion 9947 de Silverstone 2025, carrera entera:

    racing_positions       28 muestras en 9.084 s   una cada 336,5 s
    racing_intervals    1.153 muestras en 9.213 s   una cada   8,0 s
    racing_weather        155 muestras en 9.241 s   una cada  60,0 s

1. LA MAS CERCANA PUEDE SER POSTERIOR. `ORDER BY ABS(date - t)` no mira hacia
   que lado. Sobre 193 instantes repartidos cada treinta segundos, en **110** la
   muestra elegida caia en el futuro del instante pedido: el puesto de carrera
   se mostraba antes de que ocurriera el adelantamiento que lo produjo.

2. UN VENCIMIENTO PAREJO NO SIRVE PARA TRES CADENCIAS DISTINTAS. El puesto se
   publica al cambiar, y a los treinta segundos quedaba en nulo en cincuenta y
   uno de sesenta instantes; el clima llega una vez por minuto, de modo que con
   la regla correcta su edad mediana es 49 s y ese corte lo habria borrado
   siempre.

3. EL NEUMATICO NO SE FILTRABA POR PILOTO. La consulta de `racing_stints` no
   nombraba `driver_number`: con `LIMIT 1` devolvia el stint de cualquiera.
   Comprobado en la vuelta 45, donde LEC y STR iban en SOFT y el resto en
   MEDIUM: a los cuatro se les informaba MEDIUM.

Las pruebas de la politica de frescura corren siempre, porque son de una funcion
pura. Las que comprueban lo que la consulta trae **necesitan la base**, y se
saltan cuando no esta: una comprobacion de texto sobre el SQL diria donde esta
escrita la condicion y no que devuelve.
"""

from __future__ import annotations

import unittest

from backend.db import CONTEXTOS_DE_CARRERA, _clasificar_frescura_contexto


class PoliticaDeFrescuraTests(unittest.TestCase):
    """Cuando un valor describe el instante, cuando se sostiene y cuando no esta."""

    def test_un_puesto_se_sostiene_por_viejo_que_sea(self) -> None:
        """Entre dos cambios el puesto no se desconoce: es el mismo.

        Veintiocho muestras para cincuenta y dos vueltas. Vencerlo por reloj
        afirmaba que no se sabe algo que la fuente declaro.
        """
        ctx = {"position": 2, "position_age_seconds": 636.8}
        _clasificar_frescura_contexto(ctx, "position", "position_age_seconds")
        self.assertEqual(ctx["position_freshness"], "held")
        self.assertEqual(ctx["position"], 2)

    def test_sin_ninguna_muestra_previa_el_puesto_no_se_inventa(self) -> None:
        """Antes del primer dato no hay estado que sostener."""
        ctx = {"position": None, "position_age_seconds": None}
        _clasificar_frescura_contexto(ctx, "position", "position_age_seconds")
        self.assertEqual(ctx["position_freshness"], "unavailable")
        self.assertIsNone(ctx["position"])

    def test_el_intervalo_se_mide_contra_su_propia_cadencia(self) -> None:
        """Una muestra cada ocho segundos: diez es una cadencia, treinta casi cuatro."""
        for edad, esperado in ((1.3, "current"), (10.0, "current"),
                               (10.1, "aged"), (30.0, "aged"), (30.1, "unavailable")):
            with self.subTest(edad=edad):
                ctx = {"gap_to_leader_seconds": 13.2, "gap_to_leader_text": None,
                       "interval_seconds": 0.5, "interval_text": None,
                       "interval_age_seconds": edad}
                _clasificar_frescura_contexto(ctx, "interval", "interval_age_seconds")
                self.assertEqual(ctx["interval_freshness"], esperado)

    def test_un_intervalo_vencido_no_deja_el_numero_a_mano(self) -> None:
        """No se entrega con la edad al lado esperando que alguien la lea."""
        ctx = {"gap_to_leader_seconds": 13.2, "gap_to_leader_text": "+13.2",
               "interval_seconds": 0.5, "interval_text": "+0.5",
               "interval_age_seconds": 105.6}
        _clasificar_frescura_contexto(ctx, "interval", "interval_age_seconds")
        self.assertEqual(ctx["interval_freshness"], "unavailable")
        self.assertIsNone(ctx["gap_to_leader_seconds"])
        self.assertIsNone(ctx["gap_to_leader_text"])
        self.assertIsNone(ctx["interval_seconds"])
        self.assertIsNone(ctx["interval_text"])

    def test_el_clima_de_hace_cuarenta_y_nueve_segundos_es_el_clima(self) -> None:
        """Llega una por minuto: esa es su edad mediana con la regla correcta.

        Con el corte de treinta segundos que compartia con el intervalo, el
        clima quedaba en nulo en todos los instantes de la carrera.
        """
        ctx = {"air_temperature_c": 17.8, "track_temperature_c": 20.5,
               "rainfall": True, "humidity_percent": 77.0,
               "pressure_mbar": 988.8, "wind_speed_mps": 3.9,
               "wind_direction_degrees": 65.0, "weather_age_seconds": 49.4}
        _clasificar_frescura_contexto(ctx, "weather", "weather_age_seconds")
        self.assertEqual(ctx["weather_freshness"], "current")
        self.assertEqual(ctx["air_temperature_c"], 17.8)

    def test_el_clima_se_vence_cuando_deja_de_describir_el_instante(self) -> None:
        for edad, esperado in ((90.0, "current"), (90.1, "aged"),
                               (150.0, "aged"), (150.1, "unavailable")):
            with self.subTest(edad=edad):
                ctx = {"air_temperature_c": 17.8, "track_temperature_c": 20.5,
                       "rainfall": True, "humidity_percent": 77.0,
                       "pressure_mbar": 988.8, "wind_speed_mps": 3.9,
                       "wind_direction_degrees": 65.0, "weather_age_seconds": edad}
                _clasificar_frescura_contexto(ctx, "weather", "weather_age_seconds")
                self.assertEqual(ctx["weather_freshness"], esperado)

    def test_cada_magnitud_declara_por_que_envejece_como_envejece(self) -> None:
        """Un umbral sin motivo escrito es un numero que nadie puede discutir."""
        for nombre, regla in CONTEXTOS_DE_CARRERA.items():
            with self.subTest(magnitud=nombre):
                self.assertGreater(len(regla["porque"]), 30, nombre)
                if regla["sostiene"]:
                    self.assertIsNone(regla["vigente_s"])
                    self.assertIsNone(regla["viejo_s"])
                else:
                    self.assertLess(regla["vigente_s"], regla["viejo_s"])


SESION = 9947


def hay_base_con_la_sesion() -> bool:
    """Si la sesion de referencia esta importada en la base que este configurada."""
    try:
        from backend import db
        with db.obtener_conexion() as conexion:
            with conexion.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM racing_stints WHERE session_key = %s", (SESION,))
                return (cursor.fetchone() or [0])[0] > 0
    except Exception:
        return False


@unittest.skipUnless(
    hay_base_con_la_sesion(),
    "hace falta la base con la sesion 9947 importada; sin ella esto solo podria "
    "comprobar donde esta escrita la condicion, no que devuelve",
)
class LoQueLaConsultaTraeTests(unittest.TestCase):
    """Los tres defectos, sobre los datos que los revelaron."""

    #: Vuelta 45, con LEC y STR en SOFT y el resto en MEDIUM. El instante cae
    #: dentro de esa vuelta para los cuatro pilotos que se comparan.
    INSTANTE_VUELTA_45 = "2025-07-06T15:30:30+00:00"

    def _contexto(self, instante: str, pilotos: list[int]) -> dict:
        from backend.db import obtener_contexto_racing_en_instante
        return obtener_contexto_racing_en_instante(SESION, instante, pilotos)

    def test_el_neumatico_es_el_del_piloto_que_se_pregunta(self) -> None:
        """La consulta no filtraba por piloto y devolvia el stint de cualquiera."""
        por_piloto = {d["name_acronym"]: d["compound"]
                      for d in self._contexto(self.INSTANTE_VUELTA_45, [1, 4, 16, 18])["drivers"]}
        self.assertEqual(por_piloto, {"VER": "MEDIUM", "NOR": "MEDIUM",
                                      "LEC": "SOFT", "STR": "SOFT"})

    def test_no_se_devuelve_una_muestra_posterior_al_instante(self) -> None:
        """La edad de lo que se entrega nunca puede ser negativa.

        Con `ORDER BY ABS(date - t)` lo era en 110 de 193 instantes, y en el
        puesto de carrera eso es mostrar un adelantamiento antes de que ocurra.
        """
        from datetime import datetime, timedelta, timezone
        arranque = datetime(2025, 7, 6, 14, 3, 50, tzinfo=timezone.utc)
        for paso in range(0, 40):
            instante = arranque + timedelta(seconds=paso * 120)
            datos = self._contexto(instante.isoformat(), [1])
            piloto = datos["drivers"][0]
            for clave in ("position_age_seconds", "interval_age_seconds"):
                if piloto.get(clave) is None:
                    continue
                with self.subTest(instante=instante.isoformat(), magnitud=clave):
                    self.assertGreaterEqual(
                        float(piloto[clave]), 0,
                        "se entrego una muestra del futuro del instante pedido")
            clima = datos.get("weather") or {}
            if clima.get("weather_age_seconds") is not None:
                self.assertGreaterEqual(float(clima["weather_age_seconds"]), 0)

    def test_el_puesto_esta_en_todos_los_instantes_de_la_carrera(self) -> None:
        """Se sostiene entre cambios, asi que no puede faltar a mitad de carrera.

        Con el vencimiento de treinta segundos quedaba en nulo en cincuenta y
        uno de sesenta instantes, sobre un dato que la fuente declaro.
        """
        from datetime import datetime, timedelta, timezone
        arranque = datetime(2025, 7, 6, 14, 10, 0, tzinfo=timezone.utc)
        con_puesto = 0
        total = 30
        for paso in range(total):
            instante = arranque + timedelta(seconds=paso * 150)
            piloto = self._contexto(instante.isoformat(), [1])["drivers"][0]
            if piloto["position"] is not None:
                con_puesto += 1
                self.assertEqual(piloto["position_freshness"], "held")
        self.assertEqual(con_puesto, total,
                         f"el puesto falto en {total - con_puesto} de {total} instantes")

    def test_de_las_muestras_anteriores_se_toma_la_mas_reciente(self) -> None:
        """No alcanza con no adelantarse: hay que tomar la ultima, no la primera.

        `date <= t` deja pasar toda la carrera anterior. Ordenando al reves se
        entregaria la muestra de la largada en la vuelta cuarenta, y su edad
        seria positiva ---no se adelanta nada--- pero no describiria el instante.
        El intervalo llega cada ocho segundos, asi que en marcha lo que se
        entrega tiene que ser de hace segundos, no de hace media hora.
        """
        from datetime import datetime, timedelta, timezone
        arranque = datetime(2025, 7, 6, 14, 10, 0, tzinfo=timezone.utc)
        edades = []
        for paso in range(20):
            instante = arranque + timedelta(seconds=paso * 150)
            piloto = self._contexto(instante.isoformat(), [1])["drivers"][0]
            if piloto.get("interval_age_seconds") is not None:
                edades.append(float(piloto["interval_age_seconds"]))
        self.assertGreaterEqual(len(edades), 15, "casi no hubo intervalos que medir")
        edades.sort()
        mediana = edades[len(edades) // 2]
        self.assertLess(mediana, 30, f"la edad mediana del intervalo es {mediana:.1f} s")

    def test_el_clima_llega_en_todos_los_instantes_de_la_carrera(self) -> None:
        """Una muestra por minuto: con el corte de treinta segundos no llegaba nunca."""
        from datetime import datetime, timedelta, timezone
        arranque = datetime(2025, 7, 6, 14, 10, 0, tzinfo=timezone.utc)
        con_clima = 0
        total = 20
        for paso in range(total):
            instante = arranque + timedelta(seconds=paso * 210)
            clima = self._contexto(instante.isoformat(), [1])["weather"]
            if clima and clima["air_temperature_c"] is not None:
                con_clima += 1
        self.assertEqual(con_clima, total,
                         f"el clima falto en {total - con_clima} de {total} instantes")

    def test_el_clima_trae_las_siete_magnitudes_que_la_fuente_publica(self) -> None:
        """Presion y viento estaban en la base y ningun punto de acceso los leia."""
        clima = self._contexto(self.INSTANTE_VUELTA_45, [1])["weather"]
        for campo in ("air_temperature_c", "track_temperature_c", "rainfall",
                      "humidity_percent", "pressure_mbar", "wind_speed_mps",
                      "wind_direction_degrees"):
            with self.subTest(campo=campo):
                self.assertIn(campo, clima)
                self.assertIsNotNone(clima[campo])


if __name__ == "__main__":
    unittest.main()
