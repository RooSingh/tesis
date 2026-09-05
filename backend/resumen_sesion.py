# -*- coding: utf-8 -*-
"""Conserva la sesion entera a resolucion reducida, sin perder los extremos.

El problema
-----------
La vista en vivo conservaba los ultimos treinta segundos de cada senal y
descartaba lo anterior. Con eso, el eje del grafico **se desplaza**: lo viejo sale
por la izquierda y una anotacion de hace dos minutos ya no tiene donde dibujarse.
Las anotaciones quedaron entonces en una lista aparte, desconectadas de las
trazas, que es exactamente lo que la autora observo.

Conservar la sesion entera a resolucion completa no es una opcion. Ciento trece
senales a veinte muestras por segundo, sobre media hora y dos vehiculos, son unos
ocho millones de valores en el proceso.

La solucion, y la trampa que tiene
----------------------------------
La pantalla no puede mostrar mas de unos cientos de puntos por grafico: una
miniatura mide trescientos cincuenta pixeles. Guardar veinte muestras por segundo
para dibujar una por pixel es guardar lo que no se puede usar.

Pero **quedarse con una muestra de cada veinte miente**. El pico de una frenada
dura menos que el intervalo de muestreo reducido, de modo que un muestreo simple
lo hace desaparecer: el grafico quedaria mas suave que la conduccion que
describe, y justo en los instantes que las anotaciones senalan.

Por eso cada intervalo conserva **su minimo y su maximo**, no un valor
representativo. Es lo que hacen los osciloscopios y las herramientas de telemetria
para el mismo problema, y garantiza que **ningun extremo se pierda al reducir**:
lo que el grafico dibuja como pico ocurrio, y lo que no dibuja no ocurrio.
"""

from __future__ import annotations

from collections import deque

#: Duracion de cada intervalo, en segundos.
#:
#: Con un segundo, una carrera de doce minutos deja unos setecientos veinte
#: intervalos por senal: mas puntos de los que una miniatura puede dibujar y
#: memoria acotada. Sube la resolucion solo si la pantalla puede aprovecharla.
INTERVALO_S = 1.0

#: Tope de intervalos por senal. A un segundo cada uno, son dos horas: mas que
#: cualquier sesion del trabajo, y un limite conocido en lugar de crecimiento
#: sin fin.
INTERVALOS_MAXIMOS = 7200


class ResumenDeSenal:
    """Minimo y maximo por intervalo de una senal, a lo largo de la sesion."""

    __slots__ = ("intervalos", "_actual", "_inicio", "_min", "_max", "_n")

    def __init__(self) -> None:
        #: Cada entrada es (segundo_de_inicio, minimo, maximo, muestras).
        self.intervalos: deque = deque(maxlen=INTERVALOS_MAXIMOS)
        self._actual: float | None = None
        self._inicio: float | None = None
        self._min: float | None = None
        self._max: float | None = None
        self._n = 0

    def observar(self, segundo: float, valor) -> None:
        """Incorpora una muestra. Ignora lo que no sea numerico."""

        if isinstance(valor, bool) or not isinstance(valor, (int, float)):
            return
        intervalo = segundo // INTERVALO_S
        if self._actual is None:
            self._abrir(intervalo, segundo, valor)
            return
        if intervalo != self._actual:
            self._cerrar()
            self._abrir(intervalo, segundo, valor)
            return
        if valor < self._min:
            self._min = valor
        if valor > self._max:
            self._max = valor
        self._n += 1

    def _abrir(self, intervalo: float, segundo: float, valor) -> None:
        self._actual = intervalo
        self._inicio = segundo
        self._min = self._max = valor
        self._n = 1

    def _cerrar(self) -> None:
        if self._actual is None:
            return
        self.intervalos.append((self._inicio, self._min, self._max, self._n))

    def serie(self) -> list[tuple]:
        """Los intervalos cerrados **mas el que esta abierto**.

        Se incluye el abierto porque si no, lo que esta pasando ahora mismo no
        aparece hasta que termine su intervalo, y la vista en vivo mostraria un
        segundo de retraso permanente sin decirlo.
        """

        cerrados = list(self.intervalos)
        if self._actual is not None:
            cerrados.append((self._inicio, self._min, self._max, self._n))
        return cerrados


class ResumenDeSesion:
    """Los resumenes de todas las senales de todos los vehiculos."""

    def __init__(self) -> None:
        self._por_vehiculo: dict[str, dict[str, ResumenDeSenal]] = {}
        self._origen: float | None = None

    def observar(self, vehiculo: str, senal: str, segundo: float, valor) -> None:
        """Incorpora una muestra, con el segundo medido desde la primera.

        El origen se fija con la primera muestra que llega y no con el reloj de
        la maquina: lo que interesa es el tiempo transcurrido de la sesion, que
        es el eje contra el que se dibuja todo lo demas.
        """

        if self._origen is None:
            self._origen = segundo
        del_vehiculo = self._por_vehiculo.setdefault(vehiculo, {})
        resumen = del_vehiculo.get(senal)
        if resumen is None:
            resumen = del_vehiculo[senal] = ResumenDeSenal()
        resumen.observar(segundo - self._origen, valor)

    @property
    def origen(self) -> float | None:
        """El instante absoluto de la primera muestra, en segundos.

        Se expone porque las anotaciones viajan con el reloj absoluto de la
        sesion y el resumen con el tiempo transcurrido. **Sin un origen comun,
        una anotacion no se puede ubicar sobre la traza**, que es exactamente lo
        que las tenia viviendo en una lista aparte.
        """

        return self._origen

    def vehiculos(self) -> dict[str, dict[str, list[tuple]]]:
        return {
            vehiculo: {senal: r.serie() for senal, r in senales.items()}
            for vehiculo, senales in self._por_vehiculo.items()
        }

    def olvidar(self, vehiculo: str) -> None:
        """Descarta un vehiculo. Lo usa el cambio de sesion."""

        self._por_vehiculo.pop(vehiculo, None)

    def reiniciar(self) -> None:
        self._por_vehiculo.clear()
        self._origen = None
