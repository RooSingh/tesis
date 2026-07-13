"""Logica de planificacion de emision por senal.

Este modulo decide cuando debe emitirse cada senal del generador segun el
periodo configurado para el MVP. En esta primera version, el scheduler no
resuelve aun problemas avanzados de jitter, prioridad o reintentos; solo se
encarga de decidir si una senal ya cumplio el tiempo minimo para volver a
emitirse.
"""

from __future__ import annotations

from telemetry_generator.config import MVP_SIGNALS


class SignalScheduler:
    """Scheduler basico por senal individual.

    Idea central:
    - cada senal tiene su propio `period_ms`,
    - el scheduler recuerda cuando fue emitida por ultima vez,
    - y decide si corresponde volver a emitirla en el instante actual.
    """

    def __init__(self) -> None:
        # Guarda el ultimo instante (en ms) en que cada senal fue emitida.
        # Se inicializa vacio para que en el primer ciclo todas las senales
        # puedan emitirse si se desea.
        self._ultimo_emitido_ms: dict[str, int] = {}

    def obtener_senales_a_emitir(self, tiempo_actual_ms: int) -> list[str]:
        """Devuelve la lista de senales que deben emitirse ahora.

        Parametros:
        - tiempo_actual_ms: instante actual del ciclo de simulacion, medido en
          milisegundos desde el arranque del generador.
        """

        senales_a_emitir: list[str] = []

        for signal in MVP_SIGNALS:
            nombre = signal["signal_name"]
            periodo = signal["period_ms"]
            ultimo = self._ultimo_emitido_ms.get(nombre)

            # Si la senal nunca fue emitida, se habilita su emision inmediata.
            if ultimo is None:
                senales_a_emitir.append(nombre)
                self._ultimo_emitido_ms[nombre] = tiempo_actual_ms
                continue

            # Si ya paso al menos un periodo completo desde la ultima emision,
            # la senal vuelve a estar lista para salir.
            if (tiempo_actual_ms - ultimo) >= periodo:
                senales_a_emitir.append(nombre)
                self._ultimo_emitido_ms[nombre] = tiempo_actual_ms

        return senales_a_emitir
