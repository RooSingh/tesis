"""Comprobaciones de contrato del dashboard sin dependencias de navegador."""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path


RAIZ = Path(__file__).resolve().parents[1]
APP = RAIZ / "dashboard" / "app.js"
ESTILOS = RAIZ / "dashboard" / "styles.css"


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

    def test_can_muestra_el_reproductor_y_reserva_la_cabina_para_sus_graficos(self) -> None:
        estilos = ESTILOS.read_text(encoding="utf-8")
        self.assertNotIn(
            '.transporte[data-sin-distancia="si"] #mandos-reproduccion { display: none; }',
            estilos,
        )
        self.assertIn(
            ':root[data-fuente="can"] .cabina .col-cabina { display: none; }',
            estilos,
        )
        self.assertIn(
            ':root[data-fuente="can"] .cabina .graficos-cabina {',
            estilos,
        )
        self.assertIn("grid-template-columns: repeat(4, minmax(0, 1fr));", estilos)

    def test_un_panel_fuera_se_esconde_y_nada_lo_puede_revertir(self) -> None:
        """La regla que saca un panel no puede depender del orden del archivo.

        `.instrumento` y `.col-cabina` declaran su propio `display` mas abajo en
        la misma hoja y con la misma especificidad: sin la marca, que el panel
        se vaya o se quede lo decide cual de las dos reglas este escrita ultima.
        """
        estilos = ESTILOS.read_text(encoding="utf-8")
        self.assertIn('[data-fuera="si"] { display: none !important; }', estilos)

    def test_openf1_ordena_la_cabina_para_lo_que_esa_fuente_si_entrega(self) -> None:
        """Sin el panel del vehiculo, la cabina pasa de cuatro columnas a tres.

        Con la columna del medio escondida y la rejilla todavia en cuatro, la
        cuarta queda reservada y vacia: el hueco se ve igual que se veia el
        panel y encima no dice nada.
        """
        estilos = ESTILOS.read_text(encoding="utf-8")
        inicio = estilos.index(':root[data-fuente="openf1"] .cabina {')
        bloque = estilos[inicio:estilos.index("}", inicio)]
        columnas = re.search(r"grid-template-columns:([^;]+);", bloque)
        self.assertIsNotNone(columnas, bloque)
        # Cuatro: trazado, motor, cronometraje con avisos, y clima. Ninguno
        # comparte, porque compartir columna era repartir el alto y los cuatro
        # necesitan alto.
        self.assertEqual(columnas.group(1).count("minmax(0,"), 4, bloque)
        # El envoltorio de la izquierda se disuelve para que sus dos paneles
        # sean celdas de la cabina y no mitades de una columna.
        self.assertIn(
            ':root[data-fuente="openf1"] .cabina .col-cabina.izquierda,\n'
            '  :root[data-fuente="openf1"] .cabina .col-cabina.derecha'
            ' { display: contents; }',
            estilos,
        )
        # Y al apilar se deshace, o quedarian huecos donde habia paneles.
        self.assertIn(
            ':root[data-fuente="openf1"] .cabina .col-cabina.izquierda,\n'
            '    :root[data-fuente="openf1"] .cabina .col-cabina.derecha {\n'
            '      display: flex; grid-column: auto; grid-row: auto;\n    }',
            estilos,
        )
        # Y la lista de pilotos se queda con la fila de abajo entera, porque los
        # dos paneles que la acompañaban ---puesta a punto y aceleraciones---
        # esta fuente no los sostiene.
        self.assertIn(
            ':root[data-fuente="openf1"] .tablero [data-panel="vehiculos"] {',
            estilos,
        )

    def test_ninguna_fuente_esconde_paneles_desde_la_hoja_de_estilos(self) -> None:
        """El selector por atributo no distingue el panel de su fila en el pie.

        Las dos llevan `data-panel`: la `<section>` del instrumento y la `<tr>`
        de la tabla «Que sostiene cada fuente», que es el registro que queda
        cuando el panel se va. Escondiendo por atributo se borraban las dos, de
        modo que la fuente que escondia un panel borraba ademas la constancia de
        por que no estaba. La decision vive ahora en
        `PANELES_QUE_LA_FUENTE_NO_TIENE`, que ademas lleva el motivo.
        """
        estilos = ESTILOS.read_text(encoding="utf-8")
        sobrantes = re.findall(
            r':root\[data-fuente="([^"]+)"\]\s*\[data-panel="([^"]+)"\]'
            r'\s*[,{][^{}]*display:\s*none',
            estilos,
        )
        self.assertEqual(sobrantes, [], sobrantes)

    def test_can_mapea_las_trece_senales_reales(self) -> None:
        codigo = APP.read_text(encoding="utf-8")
        for senal in (
            'steerRate: "steer_rate"',
            'steerFraction: "steer_angle_fraction"',
            'wheelFL: "wheel_speed_front_left"',
            'wheelFR: "wheel_speed_front_right"',
            'wheelRL: "wheel_speed_rear_left"',
            'wheelRR: "wheel_speed_rear_right"',
        ):
            self.assertIn(senal, codigo)

        inicio = codigo.index("const PRINCIPALES_POR_FUENTE")
        bloque = codigo[inicio:codigo.index("};", inicio)]
        for metrica in ("speed", "throttle", "glong", "steer",
                        "brake", "glat", "steerRate", "yaw"):
            self.assertIn('"' + metrica + '"', bloque)


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

    def test_el_contexto_historico_habilita_la_puesta_a_punto(self) -> None:
        codigo = APP.read_text(encoding="utf-8")
        self.assertGreaterEqual(
            codigo.count('if (estado.puesta) estado.disponibles.add("setup_front_wing");'),
            2,
        )
        self.assertGreaterEqual(codigo.count("aplicarDisponibilidad();"), 3)

    def test_las_continuaciones_asincronas_no_pisan_la_sesion_vigente(self) -> None:
        """El .then que corre cuando la consulta vuelve, con el tablero en otro estado.

        Comprobar que el contador de aperturas da numeros distintos demuestra
        que la aritmetica funciona, no que una respuesta atrasada no escriba
        encima. Este arnes resuelve las respuestas a mano y mira el estado
        despues.
        """

        self._correr("continuaciones_asincronas.js")

    def test_la_posicion_del_coche_sale_del_instante_en_que_se_midio(self) -> None:
        """Instantes medidos contra rejilla pareja, huecos y cruce de meta."""

        self._correr("posicion_en_el_tiempo.js")

    def test_la_adquisicion_y_la_fase_se_eligen_como_las_declara_la_api(self) -> None:
        self._correr("eleccion_de_adquisicion.js")

    def test_todo_el_tablero_muestra_el_mismo_instante(self) -> None:
        """Un solo tiempo de presentacion para instrumentos, coche y graficos.

        Interpolacion con reloj irregular, canales de distinta frecuencia con
        nulos, senales discretas en escalon, huecos, extremos, marcas
        repetidas, pausa, seek, cambio de velocidad, vueltas de distinta
        duracion, cruce de meta, bordes de la ventana movil e inmutabilidad de
        las muestras.
        """

        self._correr("tiempo_de_presentacion.js")

    def test_la_identidad_y_el_cronometraje_salen_de_lo_medido(self) -> None:
        """Quien conduce, en que puesto va, cuanto lleva y a cuanto del lider.

        Identidad declarada contra indice interno del protocolo, cobertura
        contra parrilla, conversion de unidades exactamente una vez, formato con
        cero valido distinguido de la ausencia, puesto discreto y cronometro
        medido resuelto en el instante compartido.
        """

        self._correr("identidad_y_cronometraje.js")

    def test_un_reintento_se_ata_a_que_algo_cambie(self) -> None:
        """El bucle de microtareas que dejaba la pagina sin volver.

        La vista ampliada pedia los datos que le faltaban y se redibujaba al
        asentarse la promesa; sobre una fuente que no era la simulacion esa
        promesa venia asentada y sin traer nada, de modo que el redibujo
        encontraba lo mismo y volvia a pedir. Medido en el navegador:
        928.517 llamadas a `dibujarComparacion` en 72 s, y seguia.
        """

        self._correr("un_reintento_que_no_avanza.js")

    def test_el_contexto_de_carrera_muestra_lo_que_la_fuente_trae(self) -> None:
        """Clima, puesto y diferencia al lider de OpenF1, que ya estaban en la base.

        El panel de clima tenia cuatro casillas escritas a mano porque son las
        que publica el simulador; OpenF1 publica otras seis. Y el puesto, que en
        OpenF1 se publica al cambiar, se sostiene entre cambios en vez de
        presentarse como una medicion del instante.
        """

        self._correr("el_contexto_de_carrera.js")

    def test_las_banderas_declaradas_no_se_confunden_con_las_derivadas(self) -> None:
        """Dos listas en un panel, y cada entrada dice de donde sale.

        `/avisos` declara que cada entrada salio de aplicar una regla con un
        umbral sobre la telemetria. Una bandera de control de carrera no se
        derivo de nada: la fuente la declaro. Viajan por rutas distintas y se
        juntan al dibujar, sin perder la procedencia.
        """

        self._correr("las_banderas_que_declara_la_fuente.js")


class IdentidadYUnidadesTests(unittest.TestCase):
    """Lo que no puede volver, por como se rompio.

    Las tres cadenas de abajo son formas de escribir que fueron el defecto. Se
    las prohibe por texto porque no hay entrada que las distinga si alguien las
    vuelve a introducir en otro sitio; el comportamiento se comprueba aparte, en
    `tests/js/identidad_y_cronometraje.js`.
    """

    def setUp(self) -> None:
        self.codigo = APP.read_text(encoding="utf-8")

    def test_el_nombre_no_es_el_sufijo_del_identificador_tecnico(self) -> None:
        # `nombre: claveCorta(c)` ponia «19» ---el indice del vehiculo en el
        # protocolo--- donde la captura declara NORRIS.
        self.assertNotIn("nombre: claveCorta(c)", self.codigo)
        self.assertIn("function identidadDeVehiculo(", self.codigo)
        self.assertIn("function anotarParrillas(", self.codigo)

    def test_la_diferencia_al_lider_no_se_imprime_cruda(self) -> None:
        # `Number(dif).toFixed(3)` sobre milisegundos daba «2937.000» bajo un
        # rotulo que hablaba de una diferencia de carrera.
        self.assertNotIn("Number(dif).toFixed(3)", self.codigo)
        self.assertIn("function diferenciaEnSegundos(", self.codigo)
        self.assertIn("function divisorDePresentacion(", self.codigo)

    def test_la_conversion_no_es_una_division_escrita_a_mano(self) -> None:
        """Dividir «los canales de tiempo» rompe los que ya vienen en segundos.

        `penalty_time` y `safety_car_delta` viajan en la misma respuesta en
        segundos. La unidad la declara la API por senal y el tablero solo
        convierte los pares que conoce.
        """
        self.assertNotIn("delta_to_race_leader / 1000", self.codigo)
        self.assertNotIn("current_lap_time / 1000", self.codigo)
        self.assertIn("function divisorDeUnidad(", self.codigo)

    def test_el_tiempo_de_vuelta_no_es_la_fraccion_del_cabezal(self) -> None:
        """El cronometro medido es una senal; el cabezal decide que instante mirar.

        El respaldo por tiempo de reproduccion sigue existiendo ---una fuente
        puede no traer el canal--- pero se declara como tal en vez de pasar por
        una medicion.
        """
        self.assertIn("cronometroS: leer(\"cronometro\")", self.codigo)
        self.assertIn("cronometroMedido", self.codigo)
        self.assertIn('data-medido', self.codigo)

    def test_sin_parrilla_no_se_decide_contando_las_series(self) -> None:
        """Un vehiculo con telemetria no es una sesion sin participantes."""
        # La celda que lo escribia, no la palabra: el comentario que explica el
        # defecto la nombra, y prohibirla ahi chocaria con la explicacion.
        self.assertNotIn(">sin parrilla<", self.codigo)
        self.assertIn("function vehiculosConTelemetriaGuardada(", self.codigo)
        self.assertIn("con telemetría guardada", self.codigo)

    def test_los_nombres_se_escapan_antes_de_entrar_en_marcado(self) -> None:
        self.assertIn("function textoSeguro(", self.codigo)
        self.assertIn("textoSeguro(yo.nombre)", self.codigo)

    def test_el_encuadre_del_trazado_reserva_sitio_para_el_rotulo(self) -> None:
        """El nombre se cortaba cuando el coche pasaba por lo mas alto del circuito.

        El margen del `viewBox` era el mismo en los cuatro lados, y arriba tiene
        que caber ademas el rotulo del vehiculo: la marca lo lleva diez unidades
        por encima y la tinta sube otro tanto desde la linea base. Cuanto sube
        se **mide** sobre el rotulo dibujado en vez de deducirlo del cuerpo de
        la letra: la ascendente depende de la fuente, y si la pedida todavia no
        cargo manda la de respaldo, con otras metricas.
        """
        self.assertIn("function reservaDeArriba(", self.codigo)
        self.assertIn("function encuadrarTrazado(", self.codigo)
        self.assertIn("_ascendenteDelRotulo = y - caja.y", self.codigo)
        # Y se vuelve a medir cuando la fuente pedida termina de cargar.
        self.assertIn("document.fonts.ready", self.codigo)
        # El encuadre viejo: el mismo margen en los cuatro lados.
        self.assertNotIn("(caja.y - m) + \" \"", self.codigo)
        self.assertNotIn("caja.height + m * 2", self.codigo)

    def test_la_exportacion_conserva_su_contrato(self) -> None:
        """El CSV exporta lo que la fuente mando, en su unidad y sin sufijo.

        Convertir el bloque guardado hizo que empezara a decir 2,937 donde la
        base guarda 2937, y con un «(s)» que nadie pidio. Un archivo que se
        lleva a otro lado no cambia de contrato porque un panel cambio de
        rotulo. El comportamiento se comprueba corriendo el exportador real en
        `tests/js/identidad_y_cronometraje.js`; aca solo se prohibe la forma.
        """
        self.assertIn('cab.push((a ? a.nombre : id) + "_" + nombreDeSenal(c));',
                      self.codigo)
        self.assertIn("serieCrudaDeCanal(c, vueltaElegida, id)", self.codigo)
        self.assertNotIn('(unidad ? " (" + unidad + ")" : "")', self.codigo)

    def test_convertir_no_reescribe_lo_que_llego(self) -> None:
        """La conversion es una vista, no una reescritura del bloque guardado.

        Reescribirlo dejaba al vivo sin con que comparar ---el panel preguntaba
        por la unidad a una cache historica vacia--- y cambiaba lo exportado.
        """
        self.assertNotIn("function convertirUnidades(", self.codigo)
        self.assertIn("function unidadDeclaradaDe(", self.codigo)
        self.assertIn("function divisorDePresentacion(", self.codigo)
        self.assertIn("function serieCrudaDeCanal(", self.codigo)

    def test_lo_escalonado_se_dibuja_como_escalon(self) -> None:
        """Los cuatro renderizadores pasan por el mismo trazador.

        `esCanalEscalonado` clasificaba bien y las curvas seguian uniendo con
        diagonales: a mitad de camino entre dos observaciones el grafico
        mostraba un valor que el lector numerico no mostraba.
        """
        self.assertIn("function trazarSerie(", self.codigo)
        self.assertNotIn("i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);", self.codigo)
        llamadas = (self.codigo.count("trazarSerie(ctx,")
                    - self.codigo.count("function trazarSerie(ctx,"))
        self.assertEqual(llamadas, 4,
                         "los cuatro renderizadores tienen que pasar por el mismo trazador")

    def test_la_identidad_no_se_borra_al_anular_consultas(self) -> None:
        """Elegir una etapa llamaba a `nuevaSesionEnCurso`, que la ponia en null.

        Son dos cosas distintas: anular lo que este en vuelo, y saber a que
        alcance pertenece un nombre. Lo segundo se guarda con su alcance y se
        lee comprobandolo.
        """
        self.assertIn("function parrillaVigente(", self.codigo)
        self.assertIn("function anotarParrillas(", self.codigo)
        inicio = self.codigo.index("function nuevaSesionEnCurso(")
        cuerpo = self.codigo[inicio:self.codigo.index("\n}", inicio)]
        self.assertNotIn("PARRILLA = null", cuerpo)

    def test_el_control_del_vehiculo_conserva_los_tres_estados(self) -> None:
        self.assertIn("function quienConduce(", self.codigo)
        self.assertIn("function camposDeIdentidad(", self.codigo)
        self.assertIn("esIA: quien.esIA", self.codigo)

    def test_el_metro_de_la_curva_se_lee_de_un_solo_sitio(self) -> None:
        """Cuatro sitios leian `cu.metro`, un campo que el catalogo no publica.

        `undefined < d0` es `false` y `undefined > d1` tambien: ninguna curva se
        descartaba por estar fuera del tramo y todas terminaban en `x = NaN`. El
        navegador no dibuja con NaN y no se queja, asi que la comparacion y las
        dos exportaciones de imagen quedaron sin una sola marca, en silencio.
        """
        self.assertIn("function metroDeCurva(", self.codigo)
        self.assertNotIn("cu.metro <", self.codigo)
        self.assertNotIn("cv2.metro <", self.codigo)

    def test_las_franjas_de_circuito_se_pintan_en_pantalla_y_en_la_lamina(self) -> None:
        """Una imagen que se pega en otro lado tiene que decir lo mismo."""
        self.assertIn("function zonasDeCurva(", self.codigo)
        self.assertIn("function bandasParaElTramo(", self.codigo)
        llamadas = (self.codigo.count("pintarZonas(ctx,")
                    - self.codigo.count("function pintarZonas(ctx,"))
        self.assertEqual(llamadas, 2, "la pantalla y la lámina tienen que pintar lo mismo")

    def test_el_nombre_se_escapa_tambien_en_la_leyenda_del_trazado(self) -> None:
        """Se comprueba lo que la leyenda hace, no como se llama su variable.

        Fijaba el literal `textoSeguro(n)`, y eso ata la prueba al nombre de una
        variable: al pasar la leyenda a llevar el color del vehiculo ---y no el
        de su lugar en la lista--- la variable dejo de llamarse `n` y la prueba
        fallo sin que nada de lo que afirma hubiera cambiado.
        """

        import re
        cuerpo = self.codigo[self.codigo.index("function pintarLeyendaTraza("):]
        cuerpo = cuerpo[:cuerpo.index("\nfunction ")]
        self.assertIn("textoSeguro(", cuerpo,
                      "la leyenda del trazado tiene que escapar el nombre")
        # Y que no haya ninguna concatenacion del nombre sin escapar.
        self.assertFalse(
            re.search(r"\+ *(?:a\.)?nombre *\+", cuerpo),
            "hay un nombre concatenado sin pasar por `textoSeguro`")


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
        """El vivo dibuja lo que llega por el flujo, sin bloque de vuelta.

        La condicion cambio de forma cuando la ventana movil paso a cubrirse
        con varias vueltas ---al cruzar la meta, la anterior alcanza para
        dibujar y borrar los lienzos seria tirar lo que hay en memoria---, pero
        lo que esta prueba cuida es lo mismo: que `enVivo` entre primero y que
        una sesion en vivo nunca caiga en la espera por no tener historico.
        """
        self.assertIn("const enVivo = estadoSesion === \"vivo\";", self.codigo)
        self.assertIn("const hayAlgoQueDibujar = enVivo ||", self.codigo)
        self.assertIn("if (!hayAlgoQueDibujar) { pintarEsperando(); return; }",
                      self.codigo)
        self.assertNotIn("if (!enVivo && !estado.series[vueltaElegida])", self.codigo)

    def test_la_ventana_movil_se_corre_sobre_la_distancia_acumulada(self) -> None:
        """Al cruzar la meta la de vuelta vuelve a cero y la ventana se corta.

        Medido sobre Spa cruzando de la vuelta 3 a la 4, con las dos cargadas:
        el trazo pasaba de 52 puntos abarcando 1.200 m a 2 puntos abarcando 9.
        """
        self.assertIn("metroSesion", self.codigo)
        self.assertIn("function serieAcumuladaDeCanal(", self.codigo)
        self.assertIn("function trazaContinua(", self.codigo)
        # Que la acumulada salga de lo medido y no de multiplicar por el largo
        # del circuito se comprueba por comportamiento, no por texto: la
        # prohibicion escrita aca chocaria con el comentario que la explica.
        # Ver `tests/js/tiempo_de_presentacion.js`, «la acumulada sale de la
        # medida, no de multiplicar por el largo».

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

    def test_el_vivo_acepta_lotes_sse(self) -> None:
        """Agrupar el transporte no puede convertir el lote en una sola senal."""

        cuerpo = self.codigo[self.codigo.index(
            'canal.addEventListener("telemetria"'):]
        cuerpo = cuerpo[:cuerpo.index("});") + 3]
        self.assertIn("Array.isArray(recibido)", cuerpo)
        self.assertIn("lote.forEach", cuerpo)
        self.assertIn("incorporarTelemetriaViva(m)", cuerpo)

    def test_detener_la_escucha_cierra_el_flujo_antes_de_abrir_el_historico(self) -> None:
        cuerpo = self.codigo[self.codigo.index("function terminarEscucha("):]
        cuerpo = cuerpo[:cuerpo.index("\n}")]
        self.assertIn("cerrarFlujoEnVivo();", cuerpo)
        self.assertIn("vaciarVivo(null);", cuerpo)
        self.assertLess(cuerpo.index("cerrarFlujoEnVivo();"),
                        cuerpo.index("abrirCuandoEste"))

    def test_el_contexto_inicial_se_acota_al_instante_visible(self) -> None:
        cuerpo = self.codigo[self.codigo.index("function cargarDatosDeSesion("):]
        cuerpo = cuerpo[:cuerpo.index("function instanteUtc(")]
        self.assertIn('"?hasta=" + encodeURIComponent(cuando)', cuerpo)

    def test_la_marca_viva_lee_la_posicion_movil_y_no_el_circuito_congelado(self) -> None:
        cuerpo = self.codigo[self.codigo.index("function pintarPista("):]
        cuerpo = cuerpo[:cuerpo.index("function pintarValidacionDeLaForma(")]
        self.assertIn("vivo.posicionMundo.get(clave)", cuerpo)

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
