"""Comprobaciones de contrato del dashboard sin dependencias de navegador."""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path


RAIZ = Path(__file__).resolve().parents[1]
APP = RAIZ / "dashboard" / "app.js"
ESTILOS = RAIZ / "dashboard" / "styles.css"
INDICE = RAIZ / "dashboard" / "index.html"


class DashboardFrontendTests(unittest.TestCase):
    def test_javascript_es_valido_para_el_motor_del_navegador(self) -> None:
        proceso = subprocess.run(
            ["node", "--check", str(APP)], capture_output=True, text=True,
            check=False,
        )
        self.assertEqual(proceso.returncode, 0, proceso.stderr)

    def test_los_contratos_de_escritura_coinciden_con_fastapi(self) -> None:
        codigo = APP.read_text(encoding="utf-8")
        self.assertIn('"?confirmar=true"', codigo)

    def test_importar_ya_no_compone_un_pedido_de_openf1_a_mano(self) -> None:
        """IMPORTAR DEJO DE SER «PROCESAR LO QUE YA TRAJISTE».

        El boton pedia una `session_key` por `window.prompt` y el servidor
        buscaba el paquete **ya presente en su disco**: quien no lo hubiera
        copiado a mano recibia un 404 sobre una sesion que nunca existio. Ahora
        el archivo entra por la subida, que es el unico sitio donde entra, y el
        servidor decide que es y donde se guarda.

        Se comprueba que la composicion vieja no sobreviva al lado de la nueva:
        dos caminos para importar significan que uno de los dos deja de
        probarse.
        """
        codigo = APP.read_text(encoding="utf-8")
        # La llamada y no el nombre: los comentarios que explican por que ya no
        # esta lo nombran, y un guardian que se rompe con su propia explicacion
        # obliga a borrar la explicacion.
        self.assertNotIn("window.prompt(", codigo,
                         "importar sigue pidiendo un identificador escrito")
        self.assertNotIn("descargar_telemetria", codigo)
        self.assertIn('"/importar/archivo?nombre=" +', codigo)
        self.assertIn("xhr.upload.onprogress", codigo)

    def test_el_panel_de_reglaje_no_vuelca_los_veintitres_valores(self) -> None:
        """VEINTITRES NUMEROS SIN CONTRA QUE COMPARARLOS NO CONTESTAN NADA.

        Un «aleron delantero 3» no dice nada solo, y de los catorce circuitos
        con reglaje capturado **uno** tiene referencia externa. Ocupaban el panel
        entero y lo que si contesta una pregunta ---la comparacion contra las
        otras sesiones de la misma pista--- quedaba abajo.

        LA MEDICION NO SE PIERDE Y ESO TAMBIEN SE COMPRUEBA: sigue viajando
        entera por la API, que es donde se la puede pedir para verificar la
        comparacion. Lo que se dejo de hacer es volcarla en la pantalla.
        """
        indice = INDICE.read_text(encoding="utf-8")
        self.assertNotIn('id="lista-puesta"', indice,
                         "los valores volvieron a ocupar el panel")
        self.assertIn('id="reglajes-circuito"', indice,
                      "se fue tambien la comparacion, que es lo que contesta")
        # La API los sigue publicando: sin eso no habria con que verificar nada.
        api = (RAIZ / "backend" / "api_sesion.py").read_text(encoding="utf-8")
        self.assertIn('"campos": campos', api,
                      "la API dejo de publicar la medicion del reglaje")

    def test_lo_unico_que_esa_lista_decia_se_conserva_y_en_un_cuadro(self) -> None:
        """Cada valor llevaba al lado el de la referencia externa.

        Eso era informacion y no relleno ---el numero solo no dice nada, el
        numero contra otro si--- asi que sobrevivio a que la lista se fuera.

        Y NO COMO UNA FRASE CORRIDA. Quedo como «Alerón delantero 12 en vez de
        3, Alerón trasero 12 en vez de 0, Sesgo de freno 58 en vez de 54...»:
        hay que leerla entera para encontrar un ajuste y no deja comparar dos de
        un vistazo. Lo que alguien quiere saber es **que mover y cuanto**, y eso
        es una columna.
        """
        indice = INDICE.read_text(encoding="utf-8")
        self.assertIn('id="contra-referencia"', indice)
        codigo = APP.read_text(encoding="utf-8")
        self.assertIn("tabla-contra-referencia", codigo,
                      "la comparacion volvio a ser una frase corrida")
        self.assertIn("<th>Cambio</th>", codigo,
                      "el cuadro no dice cuanto hay que mover cada ajuste")
        self.assertIn("x.referencia - x.aplicado", codigo,
                      "el cambio no es el movimiento desde el valor propio")
        self.assertIn("diferencias.filter(x => x.diferencia)", codigo,
                      "dibuja el cuadro aunque no haya diferencia que declarar")

    def test_el_tablero_no_arma_el_pedido_de_importacion_por_su_cuenta(self) -> None:
        """EL PLAN DE PROCESAMIENTO LO DECLARA EL SERVIDOR.

        Para el bus vehicular el tablero reconstruia
        `{segmentos, plataforma, etapa}` partiendo
        `TOYOTA_RAV4_TSS2_sample_01.canraw` por un prefijo que tenia escrito:
        un acuerdo entre dos lados guardado en uno solo, que se rompe el dia que
        una plataforma lleve un guion bajo de mas. Ahora la respuesta de la
        subida trae `procesar` con su ruta, su metodo y su cuerpo, derivados del
        `.meta.json`, **que los declara**.

        Se comprueba que la derivacion no vuelva como respaldo silencioso: un
        `if` que deriva «por las dudas» devuelve el acuerdo implicito y lo
        esconde.
        """
        codigo = APP.read_text(encoding="utf-8")
        self.assertNotIn("PLATAFORMAS_CAN", codigo,
                         "el tablero volvio a conocer las plataformas del bus")
        self.assertNotIn('etapa: "cargar"', codigo,
                         "el tablero volvio a componer el cuerpo de la carga")
        self.assertIn("respuesta.procesar", codigo)
        self.assertIn("d.capturas_cerradas", codigo)
        self.assertIn("d.borradas", codigo)
        self.assertNotIn("d.sesiones_cerradas", codigo)
        self.assertNotIn("d.filas_borradas", codigo)

    def test_el_piso_de_puntos_del_tablero_es_el_que_la_api_acepta(self) -> None:
        """Dos pisos para lo mismo, y el del cliente mas bajo que el del servidor.

        `/series` y `/series-tiempo` declaran `ge=50`. El tablero tenia 20, de
        modo que con el reparto del presupuesto podia construir por su cuenta
        una consulta que la API rechaza: a partir de 49 vueltas el pedido cae
        por debajo de cincuenta. Con las 52 de Silverstone 2025 pedia 46 y la
        vista de carrera entera fallaba con «Input should be greater than or
        equal to 50».

        Se comprueba contra lo que la ruta declara y no contra un 50 escrito
        aca: copiar una cifra sin comprobarla es como no tenerla.
        """
        api = (RAIZ / "backend" / "api_sesion.py").read_text(encoding="utf-8")
        pisos = {
            int(m)
            for m in re.findall(r"puntos:\s*Annotated\[int,\s*Query\(ge=(\d+)", api)
        }
        self.assertTrue(pisos, "ninguna ruta declara un piso para `puntos`")
        codigo = APP.read_text(encoding="utf-8")
        piso = re.search(r"const PUNTOS_MINIMOS_POR_VUELTA = (\d+);", codigo)
        self.assertIsNotNone(piso, "no esta el piso de puntos del tablero")
        self.assertGreaterEqual(
            int(piso.group(1)), max(pisos),
            "el tablero puede pedir menos puntos de los que la API acepta")

    def test_no_hay_fallback_de_series_entre_vehiculos(self) -> None:
        codigo = APP.read_text(encoding="utf-8")
        self.assertNotIn("bloque.vehiculos[claveVehiculoPropio()]", codigo)
        self.assertNotIn("bloque.vehiculos[Object.keys(bloque.vehiculos)[0]]", codigo)
        self.assertNotIn("(v / 62)", codigo)

    def test_ninguna_regla_de_estilo_esconde_un_panel_por_la_fuente(self) -> None:
        """QUINTA VEZ QUE APARECE UN DATO CON DOS ESCRITORES.

        Hasta el 2026-09-12 el estilo escondia paneles segun la fuente. Para el
        bus hacia tres cosas encadenadas: esconder todas las columnas, volver a
        mostrar la izquierda, y dentro de ella esconder todo menos el trazado.
        El resultado era que en el bus solo se veian el trazado y los graficos.

        Pero quien declara que no publica cada fuente es
        `PANELES_QUE_LA_FUENTE_NO_TIENE`, y para el bus dice dos cosas: `puesta`
        y `vehiculos`. El estilo escondia paneles que la tabla afirma que esa
        fuente **si** llena, y sin dar ningun motivo en pantalla.

        Queda un solo dueño: la tabla, que ademas **escribe el motivo** en el
        panel vacio en vez de hacerlo desaparecer. Lo que se esconde sin decir
        por que es `[data-fuera]`, que la pone el guion con su motivo.
        """
        estilos = ESTILOS.read_text(encoding="utf-8")
        self.assertNotIn(
            '.transporte[data-sin-distancia="si"] #mandos-reproduccion { display: none; }',
            estilos,
        )
        sobrevivientes = [
            l for l in estilos.split("\n")
            if "data-fuente=" in l and "display: none" in l
        ]
        self.assertEqual(sobrevivientes, [], "\n".join(sobrevivientes))
        self.assertIn("grid-template-columns: repeat(4, minmax(0, 1fr));", estilos)

    def test_hidden_esconde_y_nada_lo_puede_revertir(self) -> None:
        """`hidden` es lo unico que ese atributo hace, y esta hoja lo anulaba.

        El navegador lo aplica con `[hidden] { display: none }` en su hoja de
        usuario, y cualquier regla de esta con la misma especificidad le gana:
        `.boton { display: flex }` alcanza. Medido en el navegador, dos
        elementos con `hidden` puesto se veian igual: el boton de etapa ---una
        pastilla vacia de 30 px entre dos botones--- y la franja «a quien
        escuchar», de 1.480 px por 27.
        """
        estilos = ESTILOS.read_text(encoding="utf-8")
        self.assertIn("[hidden] { display: none !important; }", estilos)

    def test_un_panel_fuera_se_esconde_y_nada_lo_puede_revertir(self) -> None:
        """La regla que saca un panel no puede depender del orden del archivo.

        `.instrumento` y `.col-cabina` declaran su propio `display` mas abajo en
        la misma hoja y con la misma especificidad: sin la marca, que el panel
        se vaya o se quede lo decide cual de las dos reglas este escrita ultima.
        """
        estilos = ESTILOS.read_text(encoding="utf-8")
        self.assertIn('[data-fuera="si"] { display: none !important; }', estilos)

    def test_una_sola_grilla_y_la_ubicacion_la_decide_la_disposicion(self) -> None:
        """Antes cada fuente tenia su propio acomodo escrito en el estilo.

        Habia tres capas: columnas de proporciones propias por fuente, filas
        numeradas, y paneles colocados a mano con `grid-column` y `grid-row`.
        Las tres competian con lo que quien mira pudiera elegir.

        Ahora hay una sola grilla de cuatro columnas iguales y filas de alto
        fijo, y cuantas ocupa cada panel lo dice la disposicion. Un ancho en
        columnas y un alto en filas son cosas que se pueden guardar y volver a
        aplicar; una proporcion elegida a mano para una fuente, no.
        """
        estilos = ESTILOS.read_text(encoding="utf-8")
        self.assertNotIn("col-cabina", estilos,
                         "quedan reglas de los envoltorios que ya no existen")
        self.assertIn("grid-template-columns: repeat(8, minmax(0, 1fr));", estilos)
        self.assertIn("grid-auto-rows: var(--alto-de-fila,", estilos)
        # Ninguna regla coloca un panel a mano.
        colocan = [
            l for l in estilos.split("\n")
            if "data-panel=" in l and ("grid-column" in l or "grid-row" in l)
        ]
        self.assertEqual(colocan, [], "\n".join(colocan))
        html = (ESTILOS.parent / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("col-cabina", html)
        self.assertEqual(html.count('id="tablero"'), 1,
                         "hay mas de un contenedor de tablero, o ninguno")

    def test_los_circulos_del_diagrama_de_g_dicen_cuanto_valen(self) -> None:
        """Un diagrama con anillos sin numero no es una medicion, es un dibujo.

        La ayuda decia «los círculos marcan 1, 2 y 3 g» y era falso: la escala se
        ajusta a la vuelta por pasos ---de 0,05 a 6 g--- porque un coche de calle
        no llega a 0,1 g en autopista y uno de carrera pasa de 4. Los anillos
        marcaban tercios de esa escala, no gravedades.

        Y el anillo de afuera ni siquiera marcaba el borde: los puntos se
        dibujan a radio 68 y el circulo estaba en 80, de modo que el numero de la
        escala señalaba una circunferencia por la que nunca pasa un dato.

        Se comprueban las dos cosas contra el radio que usa el guion: los tres
        anillos son tercios de **ese** radio, y cada uno tiene su rotulo.
        """
        # EL RADIO SE LEE DE SU CONSTANTE, y antes se sacaba de dos expresiones
        # sueltas del codigo ---la de la estela y la del punto--- porque la
        # cuenta estaba escrita dos veces. Ahora hay una sola funcion que coloca
        # todo lo del diagrama, asi que hay un solo sitio que preguntar.
        codigo = APP.read_text(encoding="utf-8")
        m = re.search(r"^const RADIO_DEL_DIAGRAMA_G = (\d+);", codigo, re.MULTILINE)
        self.assertIsNotNone(m, "no esta la constante del radio del diagrama")
        radio = int(m.group(1))
        # Y nadie vuelve a escribir la cuenta a mano.
        self.assertNotIn("norm(gx)", codigo,
                         "el punto del instante volvio a colocarse por su cuenta")

        html = INDICE.read_text(encoding="utf-8")
        rejilla = re.findall(r'<circle class="rejilla-g"[^>]*r="([\d.]+)"', html)
        self.assertEqual(
            sorted(float(r) for r in rejilla),
            sorted(round(radio * f / 3, 2) for f in (1, 2, 3)),
            "los anillos no son tercios del radio con el que se dibujan los puntos",
        )
        for i in (1, 2, 3):
            self.assertIn(f'id="escala-g-{i}"', html,
                          f"al anillo {i} le falta su rotulo")
        ayuda = html[html.index('id="ayuda-g"'):html.index("</span>", html.index('id="ayuda-g"'))]
        self.assertNotIn("1, 2 y 3 g", ayuda,
                         "la ayuda vuelve a declarar una escala fija que no existe")

    def test_un_panel_quitado_se_va_aunque_otra_regla_le_de_display(self) -> None:
        """Quitar tiene que ganarle a cualquier regla que le de `display` al panel.

        `[data-quitado="si"]` es una clase de especificidad, y
        `.instrumento { display: flex }` tambien: empatan, y entre iguales gana
        **la que este escrita despues**. Esa esta doscientas lineas mas abajo.

        Comprobado en pantalla el 2026-09-12: con el panel marcado como quitado
        seguia ocupando su sitio, y el tablero media 1.462 px con dos paneles
        fuera y 1.462 con ninguno. Y no lo agarro ninguna prueba: quitar un panel
        se veia bien en la lista de quitados y no pasaba nada en la grilla.

        Subir la especificidad arreglaria este par y se romperia con la proxima
        regla que le hable al panel. La afirmacion es «quitado gana siempre», y
        eso en una hoja de estilos se escribe con `!important`.
        """
        estilos = ESTILOS.read_text(encoding="utf-8")
        limpio = re.sub(r"/\*.*?\*/", "", estilos, flags=re.DOTALL)
        reglas = list(re.finditer(r"([^{}]+)\{([^{}]*)\}", limpio))

        quitado = [r for r in reglas
                   if 'data-quitado="si"' in r.group(1) and "display" in r.group(2)]
        self.assertEqual(len(quitado), 1,
                         "no hay exactamente una regla que saque el panel quitado")
        donde = quitado[0].start()
        self.assertIn("!important", quitado[0].group(2),
                      "quitar un panel no se impone sobre las demas reglas de `display`")

        # Y la prueba solo vale si la competencia existe: si algun dia
        # `.instrumento` deja de declarar `display`, esto deja de proteger algo y
        # corresponde enterarse.
        competidoras = [
            r for r in reglas
            if r.start() > donde
            and re.search(r"(^|,)\s*\.instrumento\s*$", r.group(1).strip())
            and re.search(r"(^|;)\s*display\s*:", r.group(2))
        ]
        self.assertTrue(
            competidoras,
            "ya no hay una regla posterior que le de `display` al panel: "
            "esta prueba dejo de proteger nada y hay que revisarla",
        )

    def test_la_hoja_y_el_guion_se_piden_con_version(self) -> None:
        """Una hoja vieja con un guion nuevo es peor que todo viejo.

        El backend manda `Cache-Control: no-cache` y eso alcanza contra el cache
        del navegador. No alcanza contra la red de distribucion que hay delante:
        medido el 2026-09-12 sobre el sitio publico, la respuesta llega con
        `cache-control: max-age=14400`. Cuatro horas de hoja vieja, puestas por
        el intermediario y no por el origen.

        Y las dos mitades no envejecen juntas. El guion ya se pedia con version,
        asi que despues de un despliegue quedaba **guion nuevo sobre hoja
        vieja**: el guion escribe anchos en unidades de ocho columnas y la hoja
        vieja dibuja cuatro. Visto en pantalla, la regla aplicada decia
        «1.02fr 0.88fr 1.22fr 1.1fr» con la hoja nueva ya en el disco de la
        Raspberry y en la respuesta de la API.

        Una direccion que cambia no se puede servir de una entrada vieja.
        """
        html = INDICE.read_text(encoding="utf-8")
        for archivo in ("styles.css", "app.js"):
            self.assertRegex(
                html, re.escape(archivo) + r"\?v=' \+ Date\.now\(\)",
                f"{archivo} se pide sin version: un despliegue no se ve hasta "
                "que el intermediario decida soltarlo",
            )
        # Y ninguno queda enlazado ademas por su nombre pelado, que volveria a
        # traer la copia vieja por la puerta de al lado.
        self.assertNotIn('href="styles.css"', html)
        self.assertNotIn('src="app.js"', html)

    def test_la_tabla_medida_no_pisa_la_tabla_declarada(self) -> None:
        """Son dos preguntas distintas y estaban en el mismo hueco.

        La escrita dice **qué instrumento sostiene cada fuente**, con los matices
        que no son un sí o un no: «continuo / binario», «23 ajustes declarados»,
        «un solo vehículo». La medida dice **qué magnitud física publica cada
        una**, con unidad y frecuencia sacadas de la base.

        `pintarMatriz` escribía sobre `table.disponibilidad` a secas y
        reemplazaba encabezado y cuerpo de la escrita, incluido el título de la
        primera columna. Comprobado en pantalla el 2026-09-12: catorce filas, y
        **ninguna** con `data-panel`. Con ellas se iban cuatro capacidades que
        sólo la escrita declara ---puesta a punto, clima, avisos y comparación
        entre vehículos--- porque no son magnitudes y la medición no las conoce.

        Lo que el atributo ata es cada instrumento con su panel del tablero, y
        esa atadura es la que sostiene la invariante de al lado: un panel que una
        fuente esconde sigue declarado acá.
        """
        html = INDICE.read_text(encoding="utf-8")
        self.assertIn('class="disponibilidad instrumentos"', html)
        self.assertIn('class="disponibilidad magnitudes"', html)

        codigo = APP.read_text(encoding="utf-8")
        inicio = codigo.index("function pintarMatriz(")
        cuerpo = codigo[inicio:codigo.index("\n}", inicio)]
        self.assertIn('table.disponibilidad.magnitudes', cuerpo,
                      "la matriz medida no apunta a su propia tabla")
        # Y no puede volver a agarrar la tabla a secas, que es la declarada.
        self.assertNotIn('querySelector("table.disponibilidad")', cuerpo,
                         "la matriz medida vuelve a escribir sobre la declarada")

        # Las cuatro que sólo la escrita declara: si algún día las trajera la
        # medición, esta prueba pide que alguien lo decida a mano.
        declarada = html[html.index('class="disponibilidad instrumentos"'):
                         html.index('class="disponibilidad magnitudes"')]
        for capacidad in ("Puesta a punto", "Clima y pista", "Avisos de sesión",
                          "Comparación entre vehículos"):
            self.assertIn(capacidad, declarada,
                          f"la tabla declarada dejo de nombrar «{capacidad}»")

    def test_la_grilla_del_estilo_dice_lo_mismo_que_las_constantes(self) -> None:
        """La grilla esta descrita en dos sitios, y tienen que coincidir.

        El guion cuenta en **unidades** ---`ancho: 1` es un cuarto del tablero,
        `alto: 1` son 150 px--- y la hoja dibuja **pistas**, que son el doble:
        asi media unidad es una medida que se puede pedir. Si uno de los dos se
        mueve sin el otro, cada panel mide el doble o la mitad de lo que pidio y
        nada en pantalla dice por que.
        """
        codigo = APP.read_text(encoding="utf-8")

        def constante(nombre: str) -> int:
            m = re.search(rf"^const {nombre} = (\d+);", codigo, re.MULTILINE)
            self.assertIsNotNone(m, f"no esta la constante {nombre}")
            return int(m.group(1))

        columnas = constante("COLUMNAS_DEL_TABLERO")
        alto = constante("ALTO_DE_FILA_PX")
        subdivisiones = constante("SUBDIVISIONES")
        estilos = ESTILOS.read_text(encoding="utf-8")
        self.assertIn(
            f"grid-template-columns: repeat({columnas * subdivisiones}, minmax(0, 1fr));",
            estilos,
            "las pistas de la hoja no son las unidades del guion por las subdivisiones",
        )
        self.assertEqual(alto % subdivisiones, 0,
                         "el alto de unidad no se puede partir en subdivisiones enteras")
        # EL ALTO DE FILA SE MIDE, y el numero de la hoja es solo el respaldo
        # hasta que el guion mida: una celda de 1x1 tiene que ser cuadrada, y el
        # ancho de columna depende de la ventana. Los dos sitios tienen que
        # nombrar el mismo respaldo, porque es lo que se ve al cargar.
        self.assertIn(f"grid-auto-rows: var(--alto-de-fila, {alto // subdivisiones}px);",
                      estilos,
                      "el respaldo de la hoja no es el que declara el guion")
        self.assertIn("--alto-de-fila", APP.read_text(encoding="utf-8"),
                      "nadie mide el alto de fila: la celda nunca sera cuadrada")

        # UNA UNIDAD TIENE QUE MEDIR LO QUE EL MODELO DICE, y partir la grilla no
        # lo respeta solo: un widget de una unidad ocupa `subdivisiones` pistas y
        # los huecos que quedan **entre** esas pistas caen adentro de la unidad.
        #
        # unidad = subdivisiones x (alto / subdivisiones) + (subdivisiones - 1) x hueco
        #        = alto + (subdivisiones - 1) x hueco
        #
        # o sea que solo coincide con `alto` cuando no hay subdivision, o cuando
        # el hueco es cero. Medido en pantalla el 2026-09-12 con dos
        # subdivisiones y catorce pixeles de hueco: una unidad media **164 px**
        # donde el modelo declara 150, dos median 342 contra 314 y tres 520
        # contra 478. El error es de catorce pixeles por unidad y crece con el
        # tamaño, de modo que los paneles grandes son los que mas se corren.
        hueco = int(re.search(r"^const HUECO_DEL_TABLERO_PX = (\d+);", codigo,
                              re.MULTILINE).group(1))
        unidad = alto + (subdivisiones - 1) * hueco
        self.assertEqual(
            unidad, alto,
            f"una unidad mide {unidad} px y el modelo declara {alto}: partir la "
            f"grilla en {subdivisiones} con {hueco} px de hueco mete "
            f"{(subdivisiones - 1) * hueco} px adentro de cada unidad",
        )

    def _reglas(self, estilos: str) -> list[tuple[str, str]]:
        """`(selector, declaraciones)` de cada regla de la hoja, sin comentarios.

        Una regla dentro de `@media` sale con la consulta pegada al frente del
        selector. No molesta: lo que se mira de un selector es su ultimo termino,
        que es el elemento al que la regla le habla.
        """
        limpio = re.sub(r"/\*.*?\*/", "", estilos, flags=re.DOTALL)
        return [
            (m.group(1).strip(), m.group(2))
            for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", limpio)
        ]

    @staticmethod
    def _a_quien_le_habla(parte: str) -> str:
        """El ultimo termino de un selector: el elemento que la regla toca.

        `.cabina .graficos-cabina` le habla a los graficos; `.graficos-cabina
        .grafico-chico`, a lo que tienen adentro. Distinguirlos es la diferencia
        entre clavar una celda del tablero y darle forma a su contenido.
        """
        terminos = parte.replace(">", " ").split()
        return terminos[-1] if terminos else ""

    def test_las_columnas_del_tablero_miden_todas_lo_mismo(self) -> None:
        """Cuatro columnas de proporciones elegidas a mano ya no significan nada.

        Las proporciones `.98 / .86 / 1.24 / .98` venian de cuando cada columna
        tenia dueño fijo: la tercera era mas ancha porque ahi vivia el vehiculo.
        Con el tablero editable el panel ya no sabe en que columna va a caer, de
        modo que una columna mas ancha que las otras le toca a quien pase por
        ahi. Medido en pantalla: la tercera media 1,44 veces la segunda.

        Toda via de la grilla mide `minmax(0, 1fr)` ---y `minmax(0, ...)` porque
        `1fr` a secas se niega a bajar del tamaño de su contenido, y un panel con
        una linea larga ensancha su columna y angosta las demas---.
        """
        estilos = ESTILOS.read_text(encoding="utf-8")
        declaradas = []
        for selector, cuerpo in self._reglas(estilos):
            for parte in selector.split(","):
                if self._a_quien_le_habla(parte) != ".cabina":
                    continue
                for m in re.finditer(r"grid-template-columns\s*:\s*([^;}]+)", cuerpo):
                    declaradas.append((parte.strip(), m.group(1).strip()))
        self.assertTrue(declaradas, "nadie declara las columnas del tablero")
        for donde, valor in declaradas:
            self.assertRegex(
                valor,
                r"^(repeat\(\d+, minmax\(0, 1fr\)\)|minmax\(0, 1fr\))$",
                f"columnas desparejas en «{donde}»: {valor}",
            )

    def test_un_panel_se_aprieta_por_su_tamaño_y_no_por_la_ventana(self) -> None:
        """Quien decide como se reparte un panel es su tamaño, y nada mas.

        Antes lo decidian dos cosas equivocadas: la **ventana** ---el
        cronometraje pedia `clamp(.85rem, 1.9vh, 1.15rem)`, de cuando el alto lo
        repartia la pantalla--- y la **fuente**, con seis reglas
        `:root[data-fuente="openf1"]` que describian la celda que esa fuente le
        daba al panel en la cabina de tamaño fijo. Ninguna de las dos se entera
        de que alguien achico el panel a media unidad.

        Lo que queda es `@container`, y para eso la celda tiene que declararse
        contenedor: sin `container-type` ninguna consulta se evalua y el panel
        se corta igual que antes, sin que nada avise.
        """
        estilos = ESTILOS.read_text(encoding="utf-8")
        self.assertIn("container-type: size;", estilos,
                      "la celda no es un contenedor: ninguna consulta de tamaño corre")
        self.assertIn("container-name: widget;", estilos)
        # El panel mas bajo que la grilla admite es de una unidad ---150 px---,
        # asi que el reparto apretado se declara contra ese alto. Estuvo contra
        # 110 px, de cuando la grilla se partia en dos, y esa consulta no podia
        # dispararse nunca.
        self.assertIn("@container widget (max-height: 200px)", estilos,
                      "no hay reparto para el panel de una unidad de alto")
        self.assertNotIn("max-height: 110px", estilos,
                         "vuelve una consulta para un alto que la grilla no admite")
        # Sin los comentarios: los comentarios cuentan de donde se saco la regla,
        # y esa historia tiene que poder seguir escrita.
        declarado = re.sub(r"/\*.*?\*/", "", estilos, flags=re.DOTALL)
        atadas = re.findall(r"[\w-]+:[^;{}]*\b\d*\.?\d+v[hw]\b[^;{}]*;", declarado)
        atadas = [d for d in atadas if "tira-cronometraje" in declarado[
            max(0, declarado.index(d) - 300):declarado.index(d)]]
        self.assertEqual(atadas, [],
                         f"una cifra atada a la ventana no se entera de que su panel cambio: {atadas}")
        por_fuente = re.findall(
            r':root\[data-fuente="[^"]+"\] \.cabina \.(clima-mini|vertical) [^{]*\{',
            estilos,
        )
        self.assertEqual(por_fuente, [], f"la fuente vuelve a decidir el reparto: {por_fuente}")

    def test_la_tira_de_cronometraje_no_arrastra_el_margen_del_navegador(self) -> None:
        """Un `<dl>` trae `margin: 1em 0` y nadie lo habia reseteado.

        En un panel grande son catorce pixeles arriba y catorce abajo que pasan
        por aire de diseño. Pedido en media fila de alto son **veintiocho de los
        cincuenta y seis** que quedan bajo el encabezado: medido, la tira se
        quedaba en 28 px con 34 de contenido y las cinco cifras se cortaban por
        la mitad. El aire de este panel lo pone su `gap`.
        """
        estilos = ESTILOS.read_text(encoding="utf-8")
        self.assertRegex(
            estilos,
            r"\.cabina \.vertical \.tira-cronometraje \{[^}]*margin: 0;",
            "la tira vuelve a arrastrar el margen por omision del `<dl>`",
        )

    def test_ninguna_celda_del_tablero_esta_clavada_por_la_hoja(self) -> None:
        """Una celda colocada por el estilo no se puede mover ni agrandar.

        La prueba de al lado ya lo exigia, pero solo miraba las reglas escritas
        con `[data-panel=...]`, y los graficos se nombraban por su clase: tenian
        `grid-column: 1 / -1` y, peor, `grid-row: 2`. Una fila declarada saca al
        elemento del acomodo automatico, asi que el bloque se quedaba pegado en
        la segunda fila **y los demas paneles se acomodaban sin contarlo**.
        Reportado el 2026-09-12: «es como que estan anclados».

        Se miran los ganchos con los que la hoja puede nombrar una celda, y solo
        cuando el selector le habla **a la celda**: darle forma a lo que una
        celda tiene adentro es justamente para lo que estan las reglas.
        """
        ganchos = ("data-panel=", "graficos-cabina", "barra-canales")
        estilos = ESTILOS.read_text(encoding="utf-8")
        clavadas = []
        for selector, cuerpo in self._reglas(estilos):
            for parte in selector.split(","):
                destino = self._a_quien_le_habla(parte)
                if not any(g in destino for g in ganchos):
                    continue
                for m in re.finditer(r"\bgrid-(column|row|area)\s*:\s*([^;}]+)", cuerpo):
                    clavadas.append(f"{parte.strip()} -> grid-{m.group(1)}: {m.group(2).strip()}")
        self.assertEqual(clavadas, [], "\n".join(clavadas))

    def test_toda_celda_del_tablero_esta_en_el_catalogo_de_widgets(self) -> None:
        """Lo que es hijo de la grilla es un widget, o no se comporta como uno.

        El bloque de graficos y la barra de señales eran celdas del tablero sin
        estar en el catalogo: no se podian mover, ni agrandar, ni quitar, y
        `aplicarDisposicion` les daba un `order` al final para que al menos no
        saltaran adelante. Media medida. Un hijo de esta grilla que no este
        declarado es un panel que quien mira no puede tocar.
        """
        html = INDICE.read_text(encoding="utf-8")
        codigo = APP.read_text(encoding="utf-8")
        bloque = codigo[codigo.index("const WIDGETS = ["):codigo.index("\n];", codigo.index("const WIDGETS = ["))]
        declarados = set(re.findall(r'id: "([^"]+)"', bloque))
        sin_declarar = [c for c in self._celdas_del_tablero(html) if c not in declarados]
        self.assertEqual(sin_declarar, [], f"celdas fuera del catalogo: {sin_declarar}")

    def test_un_grafico_nace_siendo_una_celda_del_tablero(self) -> None:
        """Los graficos no estan en el HTML: los crea el guion, y son celdas.

        Estaban los cuatro dentro de un `div` que cruzaba el tablero entero: se
        movian y se estiraban juntos, o sea que no se movia ninguno. Ahora cada
        uno se cuelga del tablero con su `data-panel`, que es **todo** lo que el
        modo edicion necesita: sin ese atributo el grafico vuelve a ser una
        celda que el catalogo no nombra, sin mandos y sin sitio en la
        disposicion. La prueba de al lado no lo alcanza porque mira el HTML.
        """
        codigo = APP.read_text(encoding="utf-8")
        self.assertIn("s.dataset.panel = PREFIJO_DE_GRAFICO + id;", codigo,
                      "un grafico creado sin `data-panel` no es un widget")
        html = INDICE.read_text(encoding="utf-8")
        self.assertNotIn('id="graficos-cabina"', html,
                         "volvio el bloque que juntaba a todos los graficos")
        self.assertNotIn("graficos-cabina", ESTILOS.read_text(encoding="utf-8"),
                         "quedan reglas del bloque que ya no existe")

    @staticmethod
    def _celdas_del_tablero(html: str) -> list[str]:
        """Los hijos directos de `#tablero`, por su `data-panel`.

        Un hijo sin `data-panel` se devuelve por su etiqueta y su clase, que es
        lo que hace falta para poder nombrarlo en el mensaje de la falla.
        """
        from html.parser import HTMLParser

        vacios = {"br", "img", "input", "meta", "link", "hr", "source", "area", "col"}

        class Lector(HTMLParser):
            def __init__(self) -> None:
                super().__init__(convert_charrefs=True)
                self.nivel = -1
                self.celdas: list[str] = []

            def handle_starttag(self, tag: str, attrs) -> None:
                if tag in vacios:
                    return
                d = dict(attrs)
                if self.nivel < 0:
                    if d.get("id") == "tablero":
                        self.nivel = 0
                    return
                if self.nivel == 0:
                    self.celdas.append(d.get("data-panel") or f"<{tag} class={d.get('class')}>")
                self.nivel += 1

            def handle_startendtag(self, tag: str, attrs) -> None:
                return

            def handle_endtag(self, tag: str) -> None:
                if tag in vacios or self.nivel < 0:
                    return
                self.nivel -= 1

        lector = Lector()
        lector.feed(html)
        return lector.celdas

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

    def _fuentes_declaradas(self) -> list[str]:
        """Las claves cortas de `FUENTES`, que es la tabla que manda."""
        codigo = APP.read_text(encoding="utf-8")
        inicio = codigo.index("const FUENTES = {")
        bloque = codigo[inicio:codigo.index("\n};", inicio)]
        return re.findall(r"^  (\w+): \{$", bloque, re.MULTILINE)

    def test_toda_fuente_que_el_tablero_ofrece_declara_sus_condiciones(self) -> None:
        """El pie legal se compara contra `FUENTES`, no contra una lista escrita.

        El informe analiza la licencia de las tres fuentes, pero el informe no
        viaja con el tablero: esta pagina se publica sola. Y el riesgo no es que
        el pie se escriba mal hoy, sino que manana entre una cuarta fuente y
        nadie se acuerde de este archivo. Por eso la lista no se copia: se lee
        de `FUENTES` y se exige un bloque por cada una.
        """
        fuentes = self._fuentes_declaradas()
        self.assertEqual(sorted(fuentes), ["can", "f1", "openf1"], fuentes)

        indice = INDICE.read_text(encoding="utf-8")
        bloques = re.findall(r'data-fuente-legal="([^"]+)"', indice)
        self.assertEqual(sorted(bloques), sorted(fuentes),
                         f"declaradas {fuentes}, con condiciones {bloques}")

    def test_el_pie_nombra_cada_fuente_como_la_nombra_el_tablero(self) -> None:
        """Un bloque que nombra una fuente que ya no se llama asi no ampara nada.

        `ETIQUETA_FUENTE` es el nombre que el tablero muestra. Si cambia y el
        pie se queda con el viejo, el aviso queda hablando de un modo que el
        usuario no ve por ningun lado.
        """
        codigo = APP.read_text(encoding="utf-8")
        linea = re.search(r"const ETIQUETA_FUENTE = \{([^}]*)\}", codigo)
        self.assertIsNotNone(linea)
        etiquetas = dict(re.findall(r'(\w+): "([^"]+)"', linea.group(1)))
        self.assertEqual(sorted(etiquetas), sorted(self._fuentes_declaradas()))

        indice = INDICE.read_text(encoding="utf-8")
        for corta, nombre in etiquetas.items():
            bloque = re.search(
                r'data-fuente-legal="' + corta + r'">(.*?)</section>',
                indice, re.DOTALL)
            self.assertIsNotNone(bloque, corta)
            self.assertIn(
                f'<span class="pastilla-fuente {corta}">{nombre}</span>',
                bloque.group(1), corta)

    def test_el_pie_legal_no_depende_de_la_fuente_abierta(self) -> None:
        """Las condiciones son de las tres fuentes, siempre, y el guion no las toca.

        El tablero cambia de fuente sin recargar. Un aviso que apareciera y
        desapareciera con el modo elegido se leeria como una nota de la sesion
        ---«esto vale para lo que estas mirando ahora»--- y no como lo que es.
        Ademas dejaria de existir si el guion no llega a correr.
        """
        indice = INDICE.read_text(encoding="utf-8")
        # Se toma la etiqueta de apertura entera, no solo lo que encierra: la
        # marca que ataria el pie a una fuente iria justamente ahi. Y se busca
        # por la clase y no por la etiqueta exacta, para que agregarle un
        # atributo legitimo ---un `role`, por ejemplo--- no reviente la prueba
        # con un error en lugar de un fallo.
        pie = re.search(r'<footer[^>]*class="pie-legal".*?</footer>',
                        indice, re.DOTALL)
        self.assertIsNotNone(pie)
        pie = pie.group(0)
        for marca in ("hidden", "data-fuera", "capa-ausente", "data-necesita"):
            self.assertNotIn(marca, pie, marca)

        codigo = APP.read_text(encoding="utf-8")
        for marca in ("pie-legal", "fuente-legal", "fuentes-legal"):
            self.assertNotIn(marca, codigo, marca)

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

    def test_todos_los_arneses_de_javascript_corren(self) -> None:
        """NINGUN ARNES SE QUEDA SIN CORRER POR NO ESTAR EN UNA LISTA.

        Cada arnes de `tests/js/` se nombra en un metodo de abajo, y nombrarlo
        es acordarse. El 2026-09-12 tres de veintitres no estaban referenciados
        en ningun archivo, y uno de ellos ---`avisos_que_no_llegaron.js`---
        llevaba cinco de sus diez casos muertos: los que cuidan que el panel
        **no afirme que no ocurrio nada cuando la consulta no volvio**. Se
        habian roto al agregar una funcion que ese arnes no extraia, y no lo
        descubrio ninguna prueba: lo descubrio alguien corriendolos a mano.

        Este recorre el directorio. Un arnes nuevo entra solo, y uno que deja de
        andar se nota el mismo dia. Los metodos con nombre siguen existiendo y
        valen la pena: dicen **que** defiende cada arnes, que es algo que un
        bucle no puede decir.
        """

        arneses = sorted((RAIZ / "tests" / "js").glob("*.js"))
        self.assertGreater(len(arneses), 15, "no se encontraron los arneses")
        rotos = []
        for arnes in arneses:
            proceso = subprocess.run(
                ["node", str(arnes)], capture_output=True, text=True, check=False,
            )
            if proceso.returncode != 0:
                rotos.append(f"--- {arnes.name}\n{proceso.stdout}\n{proceso.stderr}")
        self.assertEqual(rotos, [], "\n".join(rotos))

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

    def test_el_velo_de_arranque_dura_lo_que_tiene_que_durar(self) -> None:
        """El piso compite con la carga, y el techo no depende de app.js."""

        self._correr("el_velo_de_arranque.js")

    def test_las_rayas_de_sector_cruzan_la_pista(self) -> None:
        """Geometria de la marca: cruza, gira con la pista y no da NaN."""

        self._correr("las_rayas_de_sector.js")

    def test_de_cuando_es_cada_valor_del_contexto(self) -> None:
        """Cuatro estados y solo uno se atenua: `held` no es degradado."""

        self._correr("de_cuando_es_este_valor.js")

    def test_el_delta_dice_cuando_no_se_puede_trazar_y_cual_falta(self) -> None:
        """Superponer trazas dice **que** se hizo distinto; el delta, **donde**."""

        self._correr("donde_se_saca_el_tiempo.js")

    def test_una_disposicion_guardada_no_esconde_lo_nuevo(self) -> None:
        """Lo guardado es del pasado; el codigo sigue agregando paneles."""

        self._correr("la_disposicion_de_los_widgets.js")

    def test_antes_de_la_linea_el_coche_no_se_planta_en_la_meta(self) -> None:
        """Un `lap_distance` negativo se recortaba a cero y se declaraba medido."""

        self._correr("antes_de_la_linea_no_es_el_metro_cero.js")

    def test_el_mismo_aviso_se_ve_igual_en_vivo_y_reproducido(self) -> None:
        """En vivo todos entraban con `en: 1` y quedaba el mas viejo arriba."""

        self._correr("el_mismo_aviso_en_vivo_y_en_reproduccion.js")

    def test_en_contrarreloj_no_se_ofrece_a_quien_escuchar(self) -> None:
        """La parrilla de ese modo la llenan fantasmas que no publican nada."""

        self._correr("en_contrarreloj_solo_estoy_yo.js")

    def test_un_salto_del_vehiculo_no_se_dibuja_como_tramo(self) -> None:
        """El coche teletransportado unia dos puntos con una recta."""

        self._correr("un_salto_no_es_un_tramo.js")

    def test_un_trazado_dibujado_no_se_anuncia_como_ausente(self) -> None:
        """El encabezado decidia por el largo y negaba el dibujo sin el."""

        self._correr("lo_que_dice_el_trazado.js")

    def test_el_trazado_grande_es_el_mismo_dibujo_escalado(self) -> None:
        """EL INVARIANTE QUE HACE QUE LA VISTA GRANDE SEA CONFIABLE.

        Las dos vistas comparten `viewBox`, de modo que el circuito grande es
        el mismo camino, la misma proyeccion y las mismas rayas, agrandados por
        el navegador. Si se recalculara la geometria para la vista grande
        habria **dos** circuitos para la misma vuelta, y nada garantizaria que
        coincidan: un limite de sector podria caer en un sitio en el panel y en
        otro en la ampliacion, y las dos afirmaciones no pueden ser ciertas.

        Se comprueba sobre el marcado porque es ahi donde vive la decision.
        """

        indice = INDICE.read_text(encoding="utf-8")
        cajas = re.findall(r'viewBox="([^"]+)"', indice)
        chico = re.search(r'<svg viewBox="([^"]+)"[^>]*\n?[^>]*Trazado real', indice)
        grande = re.search(r'id="trazado-grande"[^>]*viewBox="([^"]+)"', indice)
        self.assertIsNotNone(grande, "no esta el lienzo del trazado grande")
        self.assertIn(grande.group(1), cajas)
        # El del panel chico: el unico `viewBox` que acompaña a `linea-pista`.
        i = indice.index('id="linea-pista"')
        antes = indice[:i]
        del_panel = re.findall(r'viewBox="([^"]+)"', antes)[-1]
        self.assertEqual(grande.group(1), del_panel,
                         "la vista grande usa otro sistema de coordenadas: el mismo "
                         "limite de sector caeria en dos sitios distintos")

    def test_el_trazado_grande_declara_de_donde_sale_cada_cosa(self) -> None:
        """El trazo y las rayas son medicion; el nombre de una curva es
        anotacion externa citada. Verlas juntas sin decirlo le daria a las dos
        el respaldo de una sola."""

        codigo = APP.read_text(encoding="utf-8")
        i = codigo.index("function pintarTrazadoGrande()")
        cuerpo = codigo[i:codigo.index("\n}", i)]
        self.assertIn("sectoresOrigen", cuerpo,
                      "la vista grande no dice de donde salen los sectores")
        self.assertIn("anotaci", cuerpo,
                      "la vista grande no declara que el nombre de curva es anotacion")

    def test_el_trazado_grande_no_escribe_los_nombres_de_curva(self) -> None:
        """Quince nombres escritos tapan la forma del circuito.

        Se probaron escritos y no sirve, y el motivo no era el espacio: lo que
        uno mira en un trazado es la forma y donde esta el coche; el nombre
        solo cuando se pregunta que curva es esta. Va el numero, y el nombre
        aparece al apuntar, que es la decision que el panel chico ya habia
        tomado.
        """

        codigo = APP.read_text(encoding="utf-8")
        i = codigo.index("function pintarTrazadoGrande()")
        cuerpo = codigo[i:codigo.index("\n}", i)]
        self.assertIn("numero-curva-grande", cuerpo)
        self.assertIn("marca-curva", cuerpo,
                      "sin esa clase el globo no escucha y el nombre no aparece nunca")
        self.assertNotIn("nombre-curva-grande", cuerpo,
                         "los nombres volvieron a escribirse sobre el dibujo")

    def test_la_sigla_del_piloto_va_encima_de_todos_los_puntos(self) -> None:
        """EL DEFECTO QUE ESTA PRUEBA FIJA.

        Con la sigla dentro del grupo del coche, el circulo del coche
        **siguiente** la tapaba: con tres pilotos juntos ---y juntos es
        justamente cuando hace falta distinguirlos--- se leian dos siglas de
        tres. El halo del texto solo lo despega de lo que se dibujo antes.

        Asi que las siglas se juntan y se agregan al final, despues de todos
        los puntos, y el que las mueve las busca por la clave del coche.
        """

        codigo = APP.read_text(encoding="utf-8")
        i = codigo.index("function pintarTrazadoGrande()")
        cuerpo = codigo[i:codigo.index("\n}", i)]
        self.assertIn("siglas.forEach(s => svg.appendChild(s));", cuerpo,
                      "las siglas no se agregan al final: un punto puede taparlas")
        self.assertNotIn("grupo.appendChild(rot)", cuerpo,
                         "la sigla volvio adentro del grupo del coche")

    def test_una_posicion_estimada_se_declara_como_en_el_resto_del_tablero(self) -> None:
        """UNA SOLA CONVENCION PARA LA MISMA DISTINCION.

        El tablero ya tenia una forma de decir «esto no se midio, se estimo»:
        `.auto-en-pista[data-estimada]` baja la opacidad de la marca y pone la
        sigla en bastardilla. La vista grande la dibujaba hueca, que era una
        segunda convencion para lo mismo ---y encima peor de ver: el borde fino
        hacia que el coche compitiera en presencia con las curvas, que es
        justamente lo que no hay que confundir con un coche---.

        Dos idiomas para leer la misma distincion en dos paneles del mismo
        tablero es una carga que no compra nada.
        """

        estilos = ESTILOS.read_text(encoding="utf-8")
        i = estilos.index('.auto-grande[data-estimada="si"] .coche-grande')
        regla = estilos[i:estilos.index("}", i)]
        self.assertNotIn("fill: none", regla,
                         "el punto volvio a dibujarse hueco")
        self.assertIn("opacity", regla,
                      "no se declara la estimacion como lo hace el resto del tablero")
        # Y la de la cabina, que es de donde sale la convencion, sigue igual.
        j = estilos.index('.auto-en-pista[data-estimada="si"] .marca-auto')
        self.assertIn("opacity", estilos[j:estilos.index("}", j)])

    def test_el_filtro_de_pilotos_no_puede_dejar_el_trazado_sin_nadie(self) -> None:
        """Un trazado sin ningun coche no dice donde esta nadie, y el boton que
        lo dejo asi parece roto."""

        codigo = APP.read_text(encoding="utf-8")
        i = codigo.index("function pintarEligePilotosDelTrazado()")
        cuerpo = codigo[i:codigo.index("\n}", i)]
        self.assertIn("seleccion.size > 1", cuerpo,
                      "se puede apagar el ultimo piloto y el trazado queda vacio")

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
        """Y AHORA LO HACE EN UN SOLO SITIO, PARA LAS DOS VISTAS.

        Esta comprobacion miraba dentro de `pintarPista`, que es donde vivia la
        rama del vivo. Vivia **solo ahi**, y por eso el 2026-09-13 el coche
        quedaba clavado en la punta del trazo en la vista ampliada mientras el
        widget chico lo movia bien. Se resuelve en `puntoMedidoDelCoche` y las
        dos vistas preguntan ahi; la comprobacion sigue el dato en vez de seguir
        a la funcion donde estaba.
        """
        compartido = self.codigo[
            self.codigo.index("function puntoMedidoDelCoche("):]
        compartido = compartido[:compartido.index("function pintarPista(")]
        self.assertIn("vivo.posicionMundo.get(clave)", compartido,
                      "la posicion viva dejo de leerse")

        cuerpo = self.codigo[self.codigo.index("function pintarPista("):]
        cuerpo = cuerpo[:cuerpo.index("function pintarValidacionDeLaForma(")]
        self.assertIn("puntoMedidoDelCoche(", cuerpo,
                      "el panel chico dejo de usar el sitio compartido")

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
