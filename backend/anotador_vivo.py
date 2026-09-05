# -*- coding: utf-8 -*-
"""Anota, mientras el vehiculo esta en pista, lo que los canales declaran.

El detector de `scripts/analizar_vueltas_f1_25.py` corre **despues**, sobre una
captura completa, y sirve para interpretar una prueba ya terminada. Este modulo
corre **durante**, y sirve para otra cosa: que quien mira la vista en vivo se
entere de que algo paso en el momento en que pasa, sin tener que reconocerlo en
una traza que se mueve.

Las dos diferencias con el detector fuera de linea son las que importan:

* **el fuera de linea ve marcos completos y este ve senales sueltas.** La captura
  entrega los canales de un instante juntos; el flujo en vivo entrega un mensaje
  por senal, intercalados y a distinta frecuencia. Por eso aca se conserva el
  ultimo valor de cada canal con su marca de tiempo, y una regla no se evalua con
  un valor mas viejo que `TOLERANCIA_VEJEZ_S`: componer un instante con un canal
  de hace dos segundos es inventar un marco que nunca existio;

* **el fuera de linea solo declara incidentes y este tambien declara avisos.**
  Un incidente es algo que ya ocurrio —una salida de pista, un impacto— y se
  interpreta despues. Un aviso es un estado sobre el que todavia se puede
  decidir: la bateria agotada, el combustible que no alcanza. En una lectura
  posterior el aviso no sirve porque la decision ya no existe; en vivo es lo
  unico que sirve.

Cada regla declara su **fundamento**, que es de donde sale su umbral, porque no
todas se sostienen igual. Las mas firmes son las que no tienen umbral propio: el
juego mismo declara la condicion y la regla solo la traduce.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Any, Callable, Iterable

from backend import curvas as mod_curvas, f1_udp


#: Cuanto puede envejecer el valor de un canal antes de dejar de usarse.
#:
#: Las senales llegan intercaladas y a distinta frecuencia; sin este limite una
#: regla podria mezclar la velocidad de ahora con la superficie de hace dos
#: segundos y anotar una salida de pista que ya termino. Medio segundo es mas de
#: diez marcos a la frecuencia del juego: si un canal falta mas que eso, el
#: instante no esta completo y la regla se abstiene.
TOLERANCIA_VEJEZ_S = 0.5

#: Los umbrales son los mismos del detector fuera de linea, y estan calibrados
#: igual: **una regla que se dispara en una vuelta limpia es una regla mala**.
#: Se repiten aca por valor para que este modulo no dependa del paquete de
#: guiones, y una prueba verifica que los dos numeros sigan coincidiendo: si
#: divergen, la lectura en vivo y la posterior dejan de decir lo mismo.
UMBRAL_VERTICAL_G = 1.5
UMBRAL_DESLIZAMIENTO = 0.25
UMBRAL_CAIDA_KMH = 40.0
VENTANA_CAIDA_S = 0.5
UMBRAL_FRENO_SUELTO = 0.3

#: Las superficies se importan del modulo del protocolo y no se copian aca.
#:
#: La primera version de este modulo llevaba su propia tabla, escrita de memoria,
#: y quedo corrida: llamaba "piedra" al codigo 7 donde la especificacion dice
#: "cesped". Las dos lecturas de la misma captura describian entonces superficies
#: distintas, y la que estaba mal era la escrita de memoria, que es el mismo
#: error que ya habia ocurrido con la tabla de tipos de sesion.
SUPERFICIES = f1_udp.SUPERFICIES

#: Codigo de la superficie que **es** pista: el asfalto.
#:
#: Las lineas blancas que delimitan el borde son pista segun el articulo 33.3, y
#: el canal no las distingue del asfalto, de modo que quedan incluidas sin hacer
#: nada. El piano **no** es pista, y por eso no esta aca.
ASFALTO = f1_udp.SUPERFICIE_DE_PISTA

#: Superficies sobre las que el neumatico no tiene el agarre del asfalto.
#:
#: Es una nocion **fisica** y no normativa, y por eso el piano queda adentro: se
#: puede rodar sobre un piano sin perder agarre, y en las vueltas limpias de las
#: dos capturas hay 2.083 muestras de rueda sobre piano. Sirve para la hipotesis
#: de causa —"ya venia fuera del asfalto" describe una perdida de agarre— y **no**
#: para decidir si el vehiculo salio de la pista, que es una condicion que el
#: reglamento define y no una que se mida.
SUPERFICIES_CON_AGARRE = f1_udp.SUPERFICIES_CON_AGARRE

#: Cuanto silencio cierra una anotacion abierta. Un vehiculo sobre el cesped
#: durante dos segundos son cuarenta marcos; anotarlos por separado seria ruido.
CIERRE_POR_SILENCIO_S = 1.0

#: Cuantas anotaciones se conservan para servir a quien abre la vista tarde.
ANOTACIONES_CONSERVADAS = 200

#: Cuanto se mira hacia atras para proponer una causa de lo que acaba de pasar.
#:
#: Tres segundos son unos doscientos metros a velocidad de curva. El caso que fijo
#: la ventana es la vuelta 3 de la captura con control de traccion: el vehiculo
#: toco el muro en el metro 812 y **el eje trasero se le habia ido en el 770**,
#: cuarenta metros antes. Una ventana mas corta habria anotado el golpe y perdido
#: su origen, que es justamente lo que la anotacion tiene que aportar sobre lo que
#: ya se ve en pantalla.
VENTANA_CAUSA_S = 3.0

#: Cuantos instantes de contexto se conservan. A veinte por segundo, la ventana
#: de causa mas un margen.
CONTEXTO_CONSERVADO = 120

#: Cuanto tiene que haber recorrido una vuelta para tomarla como referencia de
#: circuito. Descarta la vuelta de salida de boxes y la que quedo a medias.
MINIMO_VUELTA_M = 1000.0

#: Cuanto tiene que durar un incidente para descalificar a su vuelta como
#: referencia de circuito.
#:
#: Un deslizamiento de dos decimas es una correccion, no un trompo, y no deforma
#: el trazado. Exigir cero incidentes de cualquier duracion dejaba **ninguna**
#: vuelta utilizable en las dos capturas de Hungaroring, que es un criterio
#: inservible por estricto.
DURACION_QUE_DESCALIFICA_S = 0.3

#: Cuantas vueltas de referencia hacen falta antes de nombrar curvas.
#:
#: Una.
#:
#: La version anterior exigia dos, con el argumento de que un trompo en una sola
#: vuelta produciria una curva inexistente. El argumento dejo de valer cuando las
#: vueltas de referencia pasaron a excluir las que tuvieron incidentes: una vuelta
#: sin trompos no puede aportar una curva de trompo.
#:
#: Y exigir dos tenia un costo real. En la captura sin control de traccion hay
#: **una sola** vuelta sin incidentes de las seis, de modo que el requisito dejaba
#: a esa captura entera sin poder nombrar una curva.
MINIMO_VUELTAS_PARA_CURVAS = 1

RUEDAS = ("rear_left", "rear_right", "front_left", "front_right")

#: Canales de dano y como se los nombra al avisar.
PARTES_DANADAS = (
    ("front_left_wing_damage", "aleron delantero izquierdo"),
    ("front_right_wing_damage", "aleron delantero derecho"),
    ("rear_wing_damage", "aleron trasero"),
    ("floor_damage", "piso"),
    ("diffuser_damage", "difusor"),
    ("sidepod_damage", "pontones"),
)

#: Limite de energia electrica almacenada, en julios. Es el del reglamento, que
#: el juego respeta, y no un numero elegido aca.
ENERGIA_MAXIMA_J = 4e6

#: Debajo de que fraccion del limite se considera agotada la bateria.
FRACCION_BATERIA_AGOTADA = 0.05

#: Distancia al vehiculo de adelante, en milisegundos, que habilita el aleron.
#:
#: Un segundo. **No es un umbral elegido aca**: es la condicion reglamentaria, y
#: es la misma en todos los circuitos y todas las carreras. El canal informa la
#: distancia y la regla solo la compara contra el limite publicado.
VENTANA_ALERON_MS = 1000

#: Codigos de bandera del canal: -1 desconocida, 0 ninguna, 1 verde, 2 azul,
#: 3 amarilla, 4 roja. Solo se avisan las que cambian lo que se puede hacer.
BANDERAS = {2: "azul, dejar pasar al que viene doblando",
            3: "amarilla, levantar y prohibido adelantar",
            4: "roja, sesion detenida"}


class Anotador:
    """Mantiene el ultimo valor de cada canal y anota cuando una regla se cumple.

    No conoce el transporte: recibe mensajes ya normalizados y devuelve
    anotaciones. Eso lo hace verificable con mensajes escritos a mano, que es
    como esta probado, y permite correrlo tanto sobre el flujo en vivo como sobre
    una reproduccion sin cambiarle nada.
    """

    def __init__(self, al_anotar: Callable[[dict], None] | None = None) -> None:
        self.ultimos: dict[str, tuple[float, float]] = {}
        self.anotaciones: deque = deque(maxlen=ANOTACIONES_CONSERVADAS)
        self._abierta: dict | None = None
        self._velocidades: deque = deque()   # (t, km/h)
        self._frenos: deque = deque()        # (t, 0..1)
        self._al_anotar = al_anotar
        #: Estados ya avisados, para no repetir un aviso mientras la condicion
        #: dura. Un aviso vuelve a emitirse recien cuando la condicion se fue y
        #: volvio: repetirlo veinte veces por segundo lo haria inservible.
        self._avisados: set[str] = set()
        self._identidades = 0
        self.observados = 0

        # Contexto reciente, para poder mirar hacia atras cuando algo pasa.
        #
        # Sin esto la anotacion solo puede decir **que** paso. Con esto puede
        # decir que venia pasando antes, que es lo que convierte un aviso en una
        # explicacion: el golpe contra el muro y la perdida de eje de cuarenta
        # metros antes son el mismo suceso contado con y sin su origen.
        self._contexto: deque = deque(maxlen=CONTEXTO_CONSERVADO)

        # El circuito se aprende de la propia sesion.
        #
        # La alternativa era escribir el trazado a mano, y este trabajo ya
        # transcribio mal dos tablas de memoria. Ademas, un catalogo escrito
        # obligaria a saber en que circuito se esta corriendo, dato que el flujo
        # normalizado no transporta. Aprendido, **el sistema no necesita que le
        # digan donde esta**: mira dos vueltas limpias y ya puede nombrar curvas.
        self.catalogo = mod_curvas.CatalogoDeCurvas(circuito="aprendido en sesion")
        self._vuelta_en_curso: int | None = None
        self._puntos_vuelta: list[tuple[float, float]] = []
        self._vuelta_invalidada = False
        self._salida_con_agarre = False
        self._vueltas_con_incidente: set[int] = set()
        self._vueltas_limpias: list[list[tuple[float, float]]] = []
        #: La vuelta recien terminada, en espera de que sus incidentes cierren.
        #:
        #: Un incidente se cierra hasta un segundo despues de su ultimo instante,
        #: de modo que uno ocurrido junto a la linea de meta todavia esta abierto
        #: cuando la vuelta cambia. Decidir ahi si la vuelta sirve de referencia
        #: la aceptaria sin saber que tuvo un trompo. Se difiere un giro: cuando
        #: la vuelta siguiente termina, la anterior ya no tiene nada abierto.
        self._vuelta_pendiente: dict | None = None

    # -- entrada ----------------------------------------------------------- #

    def observar(self, mensaje: dict) -> list[dict]:
        """Incorpora un mensaje y devuelve las anotaciones que provoco."""

        nombre = mensaje.get("signal_name")
        if nombre is None:
            return []
        valor = mensaje.get("value")
        if isinstance(valor, bool):
            valor = float(valor)
        if not isinstance(valor, (int, float)):
            return []

        t = _segundos(mensaje.get("timestamp"))
        if t is None:
            return []

        self.observados += 1
        self.ultimos[nombre] = (float(valor), t)

        if nombre == "speed":
            self._velocidades.append((t, float(valor)))
            self._podar(self._velocidades, t)
        elif nombre == "brake":
            self._frenos.append((t, float(valor)))
            self._podar(self._frenos, t)
        elif nombre == "lap_number":
            self._al_cambiar_de_vuelta(int(valor))
        elif nombre == "lap_invalid" and valor:
            self._vuelta_invalidada = True
        elif nombre == "g_force_lateral":
            # El par (distancia, lateral) es lo que el catalogo de curvas
            # consume. Se arma cuando llega el lateral porque es el canal mas
            # lento de los dos.
            distancia = self._fresco("lap_distance", t)
            if distancia is not None:
                self._puntos_vuelta.append((distancia, float(valor)))

        self._registrar_contexto(t)
        return self._evaluar(t, nombre)

    # -- circuito aprendido ------------------------------------------------ #

    def _al_cambiar_de_vuelta(self, numero: int) -> None:
        """Cierra la vuelta anterior y decide sobre la anterior a esa."""

        if self._vuelta_en_curso is None:
            self._vuelta_en_curso = numero
            return
        if numero == self._vuelta_en_curso:
            return

        # Primero se resuelve la que estaba en espera: para ahora, cualquier
        # incidente suyo ya se cerro y quedo contabilizado.
        self._resolver_pendiente()

        self._vuelta_pendiente = {
            "numero": self._vuelta_en_curso,
            "puntos": self._puntos_vuelta,
            "invalidada": self._vuelta_invalidada,
        }
        self._vuelta_en_curso = numero
        self._puntos_vuelta = []
        self._vuelta_invalidada = False

    def _resolver_pendiente(self) -> None:
        """Incorpora la vuelta en espera al catalogo, si sirve de referencia.

        Una vuelta sirve si el juego no la invalido, si el propio anotador no
        encontro incidentes en ella y si recorrio el circuito.

        Exigir solo lo primero no alcanzaba, y se vio en el numero: sobre la
        captura sin control de traccion, cuatro vueltas que el juego declaraba
        validas produjeron **diecisiete** curvas contra las catorce de la captura
        con asistencia. Las tres de mas eran trompos: un vehiculo cruzado genera
        aceleracion lateral sostenida, que es exactamente la firma que el
        catalogo busca.

        El criterio de mayoria entre vueltas existia para eso y no alcanzo,
        porque cuando la mayoria de las vueltas tiene trompos la mayoria deja de
        ser evidencia. Lo que si alcanza es que el anotador **ya sabe** en que
        vueltas encontro incidentes: era informacion disponible y sin usar.
        """

        pendiente = self._vuelta_pendiente
        self._vuelta_pendiente = None
        if pendiente is None:
            return

        recorrido = max((d for d, _ in pendiente["puntos"]), default=0.0)
        if pendiente["invalidada"] or recorrido < MINIMO_VUELTA_M:
            return
        if pendiente["numero"] in self._vueltas_con_incidente:
            return

        self._vueltas_limpias.append(pendiente["puntos"])
        if len(self._vueltas_limpias) >= MINIMO_VUELTAS_PARA_CURVAS:
            self.catalogo = mod_curvas.derivar(
                self._vueltas_limpias, circuito="aprendido en sesion")

    # -- contexto ---------------------------------------------------------- #

    def _registrar_contexto(self, t: float) -> None:
        """Guarda una instantanea de lo que declaran los canales ahora.

        Se guarda una sola por marca temporal: los catorce mensajes de un mismo
        instante describen el mismo instante, y guardarlos por separado llenaria
        la ventana con catorce copias de tres decimas de segundo.
        """

        if self._contexto and self._contexto[-1]["t"] == t:
            return
        superficies = [self._fresco(f"surface_type_{r}", t) for r in RUEDAS]
        deslizamientos = [self._fresco(f"wheel_slip_ratio_{r}", t)
                          for r in ("rear_left", "rear_right")]
        self._contexto.append({
            "t": t,
            "distancia": self._fresco("lap_distance", t, tolerancia=5.0),
            "velocidad": self._fresco("speed", t),
            "acelerador": self._fresco("throttle", t),
            "freno": self._fresco("brake", t),
            "vertical": self._fresco("g_force_vertical", t),
            "superficies": [int(s) for s in superficies if s is not None],
            "deslizamiento": max((abs(d) for d in deslizamientos if d is not None),
                                 default=None),
        })

    # -- reglas ------------------------------------------------------------ #

    def _evaluar(self, t: float, llegada: str) -> list[dict]:
        motivos = self._incidentes(t, llegada)
        salidas: list[dict] = []

        if motivos:
            salidas += self._acumular(motivos, t)
        elif self._abierta and (t - self._abierta["fin_s"]) > CIERRE_POR_SILENCIO_S:
            salidas.append(self._cerrar())

        salidas += self._avisos(t)
        for anotacion in salidas:
            self._registrar(anotacion)
            if self._al_anotar is not None:
                self._al_anotar(anotacion)
        return salidas

    def _registrar(self, anotacion: dict) -> None:
        """Guarda la anotacion, reemplazando la version abierta si ya estaba.

        Una anotacion emitida dos veces —al empezar y al terminar— es **un solo
        incidente**, no dos. Sin esto la lista conservada mostraria el doble de
        incidentes de los que ocurrieron, que es peor que no mostrarlos.
        """

        identidad = anotacion.get("id")
        if identidad is not None:
            for i, previa in enumerate(self.anotaciones):
                if previa.get("id") == identidad:
                    self.anotaciones[i] = anotacion
                    return
        self.anotaciones.append(anotacion)

    def _incidentes(self, t: float, llegada: str) -> list[tuple[str, str]]:
        """Lo que ya ocurrio. Mismas reglas que la lectura posterior.

        `llegada` es la senal que acaba de llegar, y hace falta porque **no todos
        los canales significan lo mismo entre dos muestras**:

        * un **canal de estado** describe una condicion que dura. Que la rueda
          este sobre el cesped, o que el eje trasero venga deslizando, sigue
          siendo cierto en el instante que hay entre dos muestras, de modo que su
          ultimo valor puede usarse mientras sea reciente;

        * un **canal de suceso** describe un pico. Una aceleracion vertical de
          dos g es lo que se midio *en ese instante*, no un estado que persiste.

        La primera version trataba a los dos igual y la diferencia se vio en el
        numero: un impacto que la lectura posterior media en un solo marco
        aparecia en vivo durando cuatro decimas, porque el valor alto seguia
        siendo "reciente" para las decenas de mensajes de otros canales que
        llegaban despues. Un golpe instantaneo declarado como medio segundo de
        golpe no es un redondeo, es otro hecho.
        """

        motivos: list[tuple[str, str]] = []
        self._salida_con_agarre = False

        # Fuera de pista, segun la definicion del reglamento.
        #
        #     "Drivers will be judged to have left the track if no part of the
        #     car remains in contact with it and, for the avoidance of doubt, any
        #     white lines defining the track edges are considered to be part of
        #     the track but the kerbs are not."
        #
        #     -- FIA, 2025 Formula 1 Sporting Regulations, Issue 5, art. 33.3
        #
        # La version anterior de esta regla era propia: tres o mas ruedas sobre
        # una superficie que no fuera asfalto ni piano. Los dos numeros se habian
        # calibrado contra vueltas limpias, que es un metodo razonable para un
        # umbral fisico y no lo es para una definicion normativa: **estar fuera
        # de pista no es una magnitud que se mida, es una condicion que el
        # reglamento define**.
        #
        # Las dos correcciones van en sentidos opuestos, y por eso hubo que medir
        # antes de cambiar nada:
        #
        # * **el piano no es pista.** El criterio propio lo trataba como normal,
        #   de modo que un vehiculo con las cuatro ruedas sobre el piano nunca se
        #   anotaba. Sobre la captura sin control de traccion, eso dejaba sin
        #   explicar la vuelta 9, que el juego invalido y que en el metro 2.415
        #   tiene once metros con las cuatro ruedas sobre el piano;
        #
        # * **tiene que salir todo el vehiculo.** El criterio propio anotaba con
        #   tres ruedas; el reglamento exige que ninguna parte siga en contacto.
        #
        # **Lo que se mide es una aproximacion, y se declara como tal.** El
        # reglamento habla del vehiculo y el canal informa cuatro ruedas: un
        # vehiculo puede tener la carroceria sobre la pista con las cuatro ruedas
        # afuera, y ese caso el canal no lo distingue.
        #
        # Y **no lleva duracion minima porque el articulo no la tiene**. Filtrar
        # las salidas cortas es una decision de presentacion, y vive donde se
        # presenta, no dentro de la regla.
        codigos = [self._fresco(f"surface_type_{r}", t) for r in RUEDAS]
        # Con un canal ausente no se puede afirmar que ninguna rueda toca la
        # pista: podria ser justamente la que falta. La regla se abstiene.
        if all(c is not None for c in codigos):
            enteros = [int(c) for c in codigos]
            if all(c != ASFALTO for c in enteros):
                superficies = "/".join(sorted(
                    {SUPERFICIES.get(c, f"id-{c}") for c in enteros}))
                motivos.append((
                    "fuera de pista",
                    f"ninguna rueda sobre asfalto, las cuatro sobre {superficies}"))
                # Si la salida fue enteramente sobre superficie con agarre —o
                # sea, sobre el piano— el vehiculo dejo la pista sin perder el
                # control. Importa para decidir si la vuelta sirve de referencia
                # de circuito: rodar sobre el piano **es** la trazada normal.
                self._salida_con_agarre = all(
                    c in SUPERFICIES_CON_AGARRE for c in enteros)

        # Impacto vertical. Canal de suceso: solo cuenta cuando el valor acaba
        # de llegar, no mientras se lo conserva.
        vertical = self._fresco("g_force_vertical", t)             if llegada == "g_force_vertical" else None
        if vertical is not None and abs(vertical) > UMBRAL_VERTICAL_G:
            motivos.append(("impacto vertical", f"{vertical:+.2f} g"))

        # Perdida de tren trasero. Solo se evalua si el canal existe: el paquete
        # que lo publica no forma parte del contrato interno todavia, y una regla
        # que no puede evaluarse debe abstenerse y no dar por buena su ausencia.
        acelerador = self._fresco("throttle", t)
        crudos = [self._fresco(f"wheel_slip_ratio_{r}", t)
                  for r in ("rear_left", "rear_right")]
        deslizamientos = [abs(d) for d in crudos if d is not None]
        if deslizamientos and acelerador is not None:
            peor = max(deslizamientos)
            if peor > UMBRAL_DESLIZAMIENTO and acelerador > 0.5:
                motivos.append(("perdida de tren trasero", f"{peor * 100:.0f} %"))

        # Caida de velocidad con el freno suelto **durante toda la ventana**.
        # Verificarlo solo en el instante final convertia cada frenada normal en
        # un incidente: se frena fuerte, se suelta al entrar en la curva, y ahi la
        # regla veia una caida grande con el freno libre.
        caida = self._caida(t)
        if caida is not None and caida > UMBRAL_CAIDA_KMH:
            motivos.append(("caida brusca de velocidad",
                            f"-{caida:.0f} km/h en {VENTANA_CAIDA_S} s sin frenar"))

        return motivos

    def _avisos(self, t: float) -> list[dict]:
        """Estados sobre los que todavia se puede decidir algo.

        Ninguno de estos tiene un umbral inventado aca: o el juego declara la
        condicion, o el limite es el del canal. Es lo que los distingue de una
        recomendacion de conduccion, que esta tesis no esta en condiciones de dar.
        """

        avisos: list[dict] = []

        def resolver(clave: str, activa: bool, titulo: str, detalle: str,
                     fundamento: str) -> None:
            if activa and clave not in self._avisados:
                self._avisados.add(clave)
                avisos.append(self._armar("aviso", titulo, detalle, t,
                                          fundamento=fundamento))
            elif not activa:
                self._avisados.discard(clave)

        # Aleron movil: la fuente declara el permiso y cuantos metros faltan.
        # Es el aviso mas parecido al de un ingeniero de pista, y el que la
        # pantalla no da con antelacion.
        faltan = self._fresco("drs_activation_distance", t, tolerancia=1.0)
        permitido = self._fresco("drs_allowed", t, tolerancia=1.0)
        if faltan is not None and permitido is not None:
            resolver("aleron_por_habilitarse", faltan > 0 and not permitido,
                     "Aleron movil en camino",
                     f"se habilita en {faltan:.0f} m",
                     "el canal declara los metros que faltan")
            resolver("aleron_habilitado", bool(permitido),
                     "Aleron movil habilitado",
                     "el permiso esta concedido",
                     "el canal declara el permiso; no hay umbral elegido")

        # La ventana del de adelante, que es lo que concede ese permiso.
        distancia = self._fresco("delta_to_car_in_front", t, tolerancia=2.0)
        if distancia is not None and distancia > 0:
            resolver("ventana_aleron", distancia <= VENTANA_ALERON_MS,
                     "Dentro de la ventana del de adelante",
                     f"esta a {distancia / 1000:.2f} s",
                     "un segundo es la condicion reglamentaria, no un umbral propio")

        # Banderas: la fuente declara el estado y la regla solo lo traduce.
        bandera = self._fresco("fia_flag", t, tolerancia=5.0)
        if bandera is not None:
            codigo = int(bandera)
            for valor, descripcion in BANDERAS.items():
                resolver(f"bandera_{valor}", codigo == valor,
                         f"Bandera {descripcion.split(',')[0]}",
                         descripcion.split(", ", 1)[-1],
                         "la fuente declara la bandera")

        # Combustible: el propio juego publica cuantas vueltas sobran o faltan.
        # Negativo significa que no alcanza. No hay umbral que elegir.
        combustible = self._fresco("fuel_remaining_laps", t, tolerancia=5.0)
        if combustible is not None:
            resolver("combustible", combustible < 0,
                     "El combustible no alcanza",
                     f"faltan {abs(combustible):.2f} vueltas de autonomia",
                     "el juego publica el saldo; negativo significa deficit")

        # Energia electrica: el limite es el del canal, cuatro megajulios, que es
        # el que fija el reglamento y el juego respeta.
        energia = self._fresco("ers_stored_energy", t, tolerancia=5.0)
        if energia is not None:
            resolver("ers_agotado",
                     energia < FRACCION_BATERIA_AGOTADA * ENERGIA_MAXIMA_J,
                     "Bateria practicamente agotada",
                     f"{energia / 1e6:.2f} MJ de 4,00 disponibles",
                     "limite del canal, 4 MJ, fijado por reglamento")

        # Dano: pasar de cero a distinto de cero es un hecho que el juego declara.
        for canal, parte in PARTES_DANADAS:
            valor = self._fresco(canal, t, tolerancia=5.0)
            if valor is not None:
                resolver(f"dano_{canal}", valor > 0,
                         f"Dano en {parte}",
                         f"{valor:.0f} % declarado por el juego",
                         "el juego declara el porcentaje; cero es sin dano")

        return avisos

    # -- agrupamiento ------------------------------------------------------ #

    def _acumular(self, motivos: list[tuple[str, str]], t: float) -> list[dict]:
        clave = tuple(sorted(m[0] for m in motivos))
        abierta = self._abierta

        if abierta and abierta["clave"] == clave and \
                (t - abierta["fin_s"]) < CIERRE_POR_SILENCIO_S:
            # Un instante del juego llega como catorce mensajes, uno por senal,
            # todos con la misma marca temporal. Contar mensajes en lugar de
            # instantes multiplicaba la duracion por catorce y volvia inutil el
            # criterio de "al menos tres marcos", que es el que separa un
            # incidente de un roce.
            if t > abierta["fin_s"]:
                abierta["marcos"] += 1
            abierta["fin_s"] = t
            velocidad = self._fresco("speed", t)
            if velocidad is not None:
                abierta["velocidad_minima_kmh"] = min(
                    abierta["velocidad_minima_kmh"], velocidad)
            for titulo, detalle in motivos:
                abierta["detalle"].setdefault(titulo, detalle)
            if not self._salida_con_agarre:
                abierta["sin_perder_control"] = False
            return []

        salidas = [self._cerrar()] if abierta else []
        velocidad = self._fresco("speed", t)
        self._identidades += 1
        self._abierta = {
            "id": self._identidades,
            "clave": clave, "inicio_s": t, "fin_s": t, "marcos": 1,
            "detalle": {titulo: detalle for titulo, detalle in motivos},
            "vuelta": self._entero("lap_number", t, tolerancia=5.0),
            "distancia_m": self._fresco("lap_distance", t, tolerancia=5.0),
            "velocidad_entrada_kmh": velocidad,
            "velocidad_minima_kmh": velocidad if velocidad is not None else 0.0,
            # Una salida enteramente sobre superficie con agarre, sin ningun otro
            # motivo, no describe una perdida de control.
            "sin_perder_control": (clave == ("fuera de pista",)
                                   and self._salida_con_agarre),
        }
        # Se avisa **al empezar** y no al terminar.
        #
        # Emitir recien al cerrar daba una anotacion mas exacta —con su duracion
        # y su velocidad minima ya medidas— y llegaba hasta dos segundos tarde.
        # En una lectura posterior eso no importa; en vivo el aviso tardio es
        # justamente el que no sirve, porque llega despues de que quien mira ya
        # vio el trompo en la pantalla.
        #
        # La anotacion se vuelve a emitir al cerrarse, con el mismo `id` y ya
        # completa, y quien la recibe reemplaza la anterior. Es la unica forma de
        # ser puntual y exacto a la vez: primero puntual, despues exacto.
        salidas.append(self._instantanea(self._abierta, cerrada=False))
        return salidas

    def _cerrar(self) -> dict:
        a = self._abierta
        self._abierta = None
        # Recien ahora se conoce su duracion, que es lo que decide si descalifica
        # a su vuelta como referencia de circuito.
        #
        # Una salida de pista **enteramente sobre el piano** no la descalifica.
        # El reglamento dice que ahi el vehiculo dejo la pista, y es cierto; pero
        # la referencia de circuito no pregunta si el vehiculo respeto los
        # limites, pregunta si **su trazada fue la normal**, y rodar sobre el
        # piano en la salida de una curva es la trazada normal. Sin esta
        # distincion, adoptar el articulo 33.3 dejaba a la captura con asistencia
        # con una sola vuelta de referencia en lugar de dos, y el circuito
        # aprendido pasaba de catorce curvas a diecisiete.
        descalifica = (a["fin_s"] - a["inicio_s"] >= DURACION_QUE_DESCALIFICA_S
                       and a["vuelta"] is not None
                       and not a.get("sin_perder_control"))
        if descalifica:
            self._vueltas_con_incidente.add(a["vuelta"])
        return self._instantanea(a, cerrada=True)

    def _instantanea(self, a: dict, cerrada: bool) -> dict:
        """Arma la anotacion con lo que se sabe hasta ahora."""

        titulo = " y ".join(a["detalle"])
        duracion = a["fin_s"] - a["inicio_s"]
        partes = [f"{k}: {v}" for k, v in a["detalle"].items()]
        if duracion > 0:
            partes.append(f"durante {duracion:.1f} s")
        if a["velocidad_entrada_kmh"] is not None:
            perdida = a["velocidad_entrada_kmh"] - a["velocidad_minima_kmh"]
            if perdida > 1:
                entrada = a["velocidad_entrada_kmh"]
                minima = a["velocidad_minima_kmh"]
                partes.append(f"{entrada:.0f} a {minima:.0f} km/h")
        extra = {
            "id": a["id"], "cerrada": cerrada, "vuelta": a["vuelta"],
            "distancia_m": a["distancia_m"],
            "duracion_s": round(duracion, 2), "marcos": a["marcos"],
            "fundamento": "umbral calibrado contra vueltas limpias",
        }
        lugar = self.ubicar(a["distancia_m"])
        if lugar:
            extra["lugar"] = lugar
            # De cuantas vueltas salio la numeracion viaja con ella. Sin esto,
            # "curva 8" se lee como una cita del trazado oficial, y no lo es:
            # es lo que el dato de **esta** sesion declaro.
            if lugar.startswith("curva ") or " curva " in lugar:
                extra["curvas_derivadas_de"] = self.catalogo.vueltas_usadas

        # La sospecha se calcula **una sola vez**, al abrir el incidente, y se
        # conserva. Recalcularla al cerrarlo miraria la ventana equivocada: para
        # entonces lo que precede al incidente es el propio incidente.
        if "sospecha" not in a:
            a["sospecha"] = self._causa_probable(a["inicio_s"])
        if a["sospecha"] is not None:
            extra["sospecha"], extra["sospecha_evidencia"] = a["sospecha"]

        return self._armar("incidente", titulo, "; ".join(partes), a["fin_s"],
                           **extra)

    def cerrar_pendiente(self) -> list[dict]:
        """Cierra la anotacion en curso, si la hay. Se llama al fin de sesion."""

        if self._abierta is None:
            return []
        anotacion = self._cerrar()
        self._registrar(anotacion)
        self._resolver_pendiente()
        if self._al_anotar is not None:
            self._al_anotar(anotacion)
        return [anotacion]

    # -- causa probable ---------------------------------------------------- #

    def _causa_probable(self, inicio_s: float) -> tuple[str, str] | None:
        """Que venia pasando antes de que empezara el incidente.

        Devuelve la sospecha y su evidencia, o `None` si los canales no muestran
        ningun antecedente.

        **Se llama sospecha y no causa a proposito.** Lo que el dato permite
        afirmar es que dos cosas ocurrieron en ese orden y a esa distancia; que
        una haya producido la otra es una lectura, y una lectura puede estar
        equivocada. Escribirlo como causa haria que una correlacion entrara al
        informe con el peso de una medicion.

        El orden de las reglas es el de la evidencia mas especifica primero: un
        piano pisado explica un golpe mejor que "venia frenando fuerte", que le
        pasa a cualquiera en cualquier curva.
        """

        previos = [c for c in self._contexto
                   if inicio_s - VENTANA_CAUSA_S <= c["t"] < inicio_s]
        if not previos:
            return None

        distancia_ahora = next((c["distancia"] for c in reversed(self._contexto)
                                if c["distancia"] is not None), None)

        def antes_de(c: dict) -> str:
            if distancia_ahora is None or c["distancia"] is None:
                return f"{inicio_s - c['t']:.1f} s antes"
            metros = distancia_ahora - c["distancia"]
            # Por debajo de un metro, la distancia no ubica nada y "0 m antes"
            # se lee como un error. En ese caso informa el tiempo.
            if metros < 1.0:
                return f"{inicio_s - c['t']:.2f} s antes"
            return f"{metros:.0f} m antes"

        # 1. Piano pisado, con golpe vertical. Es la explicacion mas concreta que
        #    los canales permiten dar de un impacto o de una perdida repentina.
        pianos = [c for c in previos if 1 in c["superficies"]]
        if pianos:
            golpe = max(pianos, key=lambda c: abs(c["vertical"] or 0.0))
            vertical = golpe["vertical"]
            if vertical is not None and abs(vertical) > 0.653:
                # 0,653 g es el percentil 99 de la aceleracion vertical en
                # vueltas limpias: por debajo de eso, pisar el piano es rutina.
                # El lugar se nombra solo si cae dentro de una curva. "En 15 m
                # antes de la curva 8" es una frase que no se puede leer, y una
                # anotacion ilegible no informa aunque sea exacta.
                lugar = self.ubicar(golpe["distancia"])
                dentro = lugar.startswith("curva ")
                return ("piso un piano",
                        f"{len(pianos)} instantes con rueda sobre piano "
                        f"{antes_de(golpe)}, con {vertical:+.2f} g verticales"
                        + (f" en la {lugar}" if dentro else ""))

        # 2. Venia deslizando el eje motriz. Es el antecedente de la vuelta 3 de
        #    la captura con asistencia: el muro fue la consecuencia.
        deslizando = [c for c in previos
                      if (c["deslizamiento"] or 0.0) > UMBRAL_DESLIZAMIENTO]
        if deslizando:
            peor = max(deslizando, key=lambda c: c["deslizamiento"])
            acelerador = peor["acelerador"]
            evidencia = (f"el eje trasero venia deslizando "
                         f"{peor['deslizamiento'] * 100:.0f} % {antes_de(peor)}")
            if acelerador is not None:
                evidencia += f", con el acelerador al {acelerador * 100:.0f} %"
            # Deslizar con el acelerador cerrado **no es una perdida de
            # traccion**: no hay par que la rueda no pueda transmitir. Es un
            # trompo o una rueda trabada. La regla del incidente ya exige
            # acelerador para llamarla perdida de traccion; la de la sospecha
            # tiene que respetar la misma distincion o afirmaria de mas.
            if acelerador is not None and acelerador > 0.5:
                return ("perdio el tren trasero antes", evidencia)
            return ("el vehiculo ya venia cruzado", evidencia)

        # 3. Ya venia fuera del asfalto. Distinto de salirse ahora: el incidente
        #    es la continuacion de una excursion que empezo antes.
        # Aca la nocion es fisica y no normativa: lo que explica un incidente es
        # haber venido rodando sin agarre, y sobre un piano hay agarre. Por eso
        # esta regla conserva el piano como superficie con agarre mientras la de
        # salida de pista, que responde al articulo 33.3, no lo cuenta como pista.
        fuera = [c for c in previos
                 if any(s not in SUPERFICIES_CON_AGARRE for s in c["superficies"])]
        if len(fuera) >= 3:
            nombres = sorted({SUPERFICIES.get(s, f"id-{s}")
                              for c in fuera for s in c["superficies"]
                              if s not in SUPERFICIES_CON_AGARRE})
            return ("ya venia fuera del asfalto",
                    f"{len(fuera)} instantes sobre {'/'.join(nombres)} "
                    f"desde {antes_de(fuera[0])}")

        # 4. Entro frenando fuerte. La explicacion mas debil de las cuatro, y se
        #    declara como tal: frenar fuerte antes de una curva es conducir.
        frenando = [c for c in previos if (c["freno"] or 0.0) > 0.8]
        if len(frenando) >= 3 and previos[0]["velocidad"] and previos[-1]["velocidad"]:
            caida = previos[0]["velocidad"] - previos[-1]["velocidad"]
            if caida > 50:
                return ("venia de una frenada fuerte",
                        f"freno a fondo durante {len(frenando)} instantes, "
                        f"{previos[0]['velocidad']:.0f} a "
                        f"{previos[-1]['velocidad']:.0f} km/h")

        return None

    def ubicar(self, metro: float | None) -> str:
        """Donde ocurrio, en palabras, si el circuito ya se aprendio."""

        if metro is None:
            return ""
        return self.catalogo.ubicar(metro)

    # -- utilidades -------------------------------------------------------- #

    def _armar(self, nivel: str, titulo: str, detalle: str, t: float,
               **extra: Any) -> dict:
        anotacion = {
            "nivel": nivel, "titulo": titulo, "detalle": detalle,
            "reloj_s": round(t, 3),
        }
        if "vuelta" not in extra:
            extra["vuelta"] = self._entero("lap_number", t, tolerancia=5.0)
        anotacion.update({k: v for k, v in extra.items() if v is not None})
        return anotacion

    def _fresco(self, nombre: str, t: float,
                tolerancia: float = TOLERANCIA_VEJEZ_S) -> float | None:
        """El ultimo valor del canal, si no es mas viejo que la tolerancia."""

        entrada = self.ultimos.get(nombre)
        if entrada is None:
            return None
        valor, marca = entrada
        return valor if (t - marca) <= tolerancia else None

    def _entero(self, nombre: str, t: float,
                tolerancia: float = TOLERANCIA_VEJEZ_S) -> int | None:
        valor = self._fresco(nombre, t, tolerancia)
        return int(valor) if valor is not None else None

    def _caida(self, t: float) -> float | None:
        if len(self._velocidades) < 2:
            return None
        # El freno tiene que haber estado suelto en toda la ventana, no solo
        # ahora: una frenada fuerte que se libera al entrar en la curva deja el
        # freno en cero justo cuando la caida acumulada es mayor.
        frenos = [f for marca, f in self._frenos if marca >= t - VENTANA_CAIDA_S]
        if frenos and max(frenos) >= UMBRAL_FRENO_SUELTO:
            return None
        antigua = self._velocidades[0][1]
        return antigua - self._velocidades[-1][1]

    @staticmethod
    def _podar(serie: deque, t: float) -> None:
        while serie and (t - serie[0][0]) > VENTANA_CAIDA_S:
            serie.popleft()


def _segundos(marca: Any) -> float | None:
    """Pasa la marca temporal del contrato a segundos comparables."""

    if isinstance(marca, (int, float)):
        return float(marca)
    if not isinstance(marca, str):
        return None
    try:
        return datetime.fromisoformat(marca).timestamp()
    except ValueError:
        return None


def anotar_secuencia(mensajes: Iterable[dict]) -> list[dict]:
    """Corre el anotador sobre una secuencia completa. Util para verificarlo."""

    anotador = Anotador()
    salidas: list[dict] = []
    for mensaje in mensajes:
        salidas += anotador.observar(mensaje)
    salidas += anotador.cerrar_pendiente()
    return salidas
