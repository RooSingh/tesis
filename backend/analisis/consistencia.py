# -*- coding: utf-8 -*-
"""Consistencia entre vueltas del mismo conductor.

Que se mide, y contra que
-------------------------
Un conductor rapido e inconsistente y otro constante pero medio segundo mas lento
son problemas distintos, y el promedio no los distingue.

Lo que no sirve es la dispersion **alrededor de la media**. Dentro de una tanda el
vehiculo se aligera vuelta a vuelta y los tiempos derivan por eso, de modo que un
conductor perfectamente constante daria dispersion alta sin haber sido
inconsistente ni una vez. Medido sobre la carrera de Spa: la segunda tanda tiene
0,778 s de desvio contra la media y **0,589 s alrededor de su tendencia**. Un
cuarto de la dispersion era combustible.

De ahi que la cifra principal sea la dispersion **alrededor de la tendencia**, y
que la pendiente y la dispersion cruda se informen igual: son tres respuestas a
tres preguntas distintas y ninguna reemplaza a las otras.

Por tanda y no por sesion
-------------------------
La tendencia se ajusta dentro de cada tanda. Ajustarla sobre la sesion entera
mezclaria la caida de tiempos que produce la parada con la deriva propia de la
tanda, y esa mezcla se veria como inconsistencia del conductor.

Sobre vueltas comparables
-------------------------
La dispersion se calcula sobre las vueltas comparables y no sobre las validas. Una
vuelta con paso por boxes es valida para el reglamento y suma quince segundos a la
dispersion, y esos quince segundos no describen al conductor.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.analisis.ajuste import ajustar
from backend.analisis.disponibilidad import IMPOSIBLE, Disponibilidad, evaluar
from backend.analisis.vueltas import SinVueltas, extraer

#: Minimo de vueltas para que una tanda admita ajustarle una tendencia. Con tres
#: puntos la recta pasa casi por todos y la dispersion residual sale artificial.
VUELTAS_MINIMAS_POR_TANDA = 4


def _mediana(valores: list[float]) -> float:
    o = sorted(valores)
    m = len(o) // 2
    return o[m] if len(o) % 2 else (o[m - 1] + o[m]) / 2.0


@dataclass
class Tanda:
    """Una tanda, con las tres cifras que la describen."""

    numero: int
    vueltas: list[int]
    tiempos: list[float]
    media_s: float
    #: Dispersion contra la media. Incluye la deriva, de modo que sobreestima.
    dispersion_cruda_s: float
    #: Deriva por vuelta. Positiva significa que los tiempos empeoran.
    pendiente_s_por_vuelta: float | None = None
    #: Dispersion alrededor de la tendencia. Es la cifra de consistencia.
    dispersion_sobre_tendencia_s: float | None = None
    #: Si la deriva se distingue de cero con las vueltas de esta tanda.
    deriva_significativa: bool | None = None
    mejor_s: float = 0.0
    #: Cuanto se aparta la mediana de la mejor vuelta. Es lo que el conductor
    #: deja sobre la mesa por no repetir su propia mejor vuelta.
    margen_sobre_la_mejor_s: float = 0.0


@dataclass
class Consistencia:
    """Las tandas de una sesion con sus cifras de consistencia."""

    session_id: str
    fuente: str
    disponibilidad: Disponibilidad
    tandas: list[Tanda] = field(default_factory=list)
    #: Por que no se pudo medir, cuando no se pudo.
    impedimento: str | None = None

    def como_dict(self) -> dict:
        return {
            "session_id": self.session_id, "fuente": self.fuente,
            "impedimento": self.impedimento,
            "disponibilidad": self.disponibilidad.como_dict(),
            "tandas": [{
                "numero": t.numero, "vueltas": t.vueltas,
                "media_s": t.media_s,
                "dispersion_cruda_s": t.dispersion_cruda_s,
                "pendiente_s_por_vuelta": t.pendiente_s_por_vuelta,
                "dispersion_sobre_tendencia_s": t.dispersion_sobre_tendencia_s,
                "deriva_significativa": t.deriva_significativa,
                "mejor_s": t.mejor_s,
                "margen_sobre_la_mejor_s": t.margen_sobre_la_mejor_s,
            } for t in self.tandas],
        }


def _desvio(valores: list[float]) -> float:
    n = len(valores)
    if n < 2:
        return 0.0
    media = sum(valores) / n
    return (sum((v - media) ** 2 for v in valores) / (n - 1)) ** 0.5


def _partir_en_tandas(vueltas: list[tuple[int, float]],
                      cortes: set[int]) -> list[list[tuple[int, float]]]:
    """Separa la lista donde hubo una parada.

    Los cortes son numeros de vuelta que **no** son comparables por haber pasado
    por boxes. Una vuelta comparable posterior a un corte abre una tanda nueva.
    """

    tandas: list[list[tuple[int, float]]] = []
    actual: list[tuple[int, float]] = []
    for numero, tiempo in vueltas:
        if actual and any(actual[-1][0] < c < numero for c in cortes):
            tandas.append(actual)
            actual = []
        actual.append((numero, tiempo))
    if actual:
        tandas.append(actual)
    return tandas


def analizar(fuente: str, session_id: str) -> Consistencia:
    """Mide la consistencia por tanda sobre las vueltas comparables."""

    disponible = evaluar("consistencia", fuente, session_id)
    if disponible.estado == IMPOSIBLE:
        raise SinVueltas(disponible)

    sesion = extraer(fuente, session_id)
    comparables = [(v.numero, v.duracion_s) for v in sesion.comparables
                   if v.duracion_s is not None]
    resultado = Consistencia(session_id=session_id, fuente=fuente,
                             disponibilidad=disponible)
    if len(comparables) < 2:
        resultado.impedimento = (
            f"hacen falta al menos dos vueltas comparables y hay "
            f"{len(comparables)}")
        return resultado

    # Las vueltas de boxes son justamente las que separan las tandas, de modo que
    # lo que el filtro descarta para comparar sirve aca para estructurar.
    cortes = {v.numero for v in sesion.vueltas
              if not v.comparable and any("boxes" in m for m in v.motivos)}

    for i, tanda in enumerate(_partir_en_tandas(comparables, cortes), start=1):
        numeros = [n for n, _ in tanda]
        tiempos = [t for _, t in tanda]
        t = Tanda(numero=i, vueltas=numeros, tiempos=tiempos,
                  media_s=round(sum(tiempos) / len(tiempos), 3),
                  dispersion_cruda_s=round(_desvio(tiempos), 3),
                  mejor_s=round(min(tiempos), 3),
                  margen_sobre_la_mejor_s=round(_mediana(tiempos) - min(tiempos), 3))
        if len(tiempos) >= VUELTAS_MINIMAS_POR_TANDA:
            ajuste = ajustar(tiempos, [("vuelta", [float(n) for n in numeros],
                                        "s/vuelta")])
            c = ajuste.por_nombre("vuelta")
            t.pendiente_s_por_vuelta = round(c.valor, 4)
            t.deriva_significativa = c.distinguible(ajuste.grados_de_libertad)
            t.dispersion_sobre_tendencia_s = round(ajuste.dispersion_residual, 3)
        resultado.tandas.append(t)
    return resultado


def resumen(c: Consistencia) -> str:
    """Una linea por tanda, con las tres cifras."""

    if c.impedimento:
        return f"sin medicion: {c.impedimento}"
    lineas = []
    for t in c.tandas:
        partes = [f"tanda {t.numero}: {len(t.vueltas)} vueltas",
                  f"media {t.media_s:,.3f} s",
                  f"dispersion cruda {t.dispersion_cruda_s:,.3f} s"]
        if t.dispersion_sobre_tendencia_s is not None:
            partes.append(f"sobre la tendencia {t.dispersion_sobre_tendencia_s:,.3f} s")
            marca = "" if t.deriva_significativa else " (no significativa)"
            partes.append(f"deriva {t.pendiente_s_por_vuelta:+.4f} s/vuelta{marca}")
        partes.append(f"margen sobre la mejor {t.margen_sobre_la_mejor_s:+.3f} s")
        lineas.append("; ".join(partes))
    return "\n".join(lineas)
