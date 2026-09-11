"""Referencias bibliograficas de reglaje, separadas de la medicion.

Una referencia de comunidad no es un optimo ni una instruccion. Sirve para
declarar contra que condicion externa se compara el reglaje observado. Los
campos sin fuente cuantitativa se omiten: ausente no significa cero.
"""

from __future__ import annotations


REFERENCIAS = {
    ("f1-25", "spa-francorchamps"): {
        "programa": "F1 25",
        "circuito": "Spa-Francorchamps",
        "valores": {
            "aleron_delantero": 3,
            "aleron_trasero": 0,
        },
        "fuente": {
            "titulo": "F1 25 Spa-Francorchamps Car Setup: Full Setup and Guide",
            "autor": "SimRacingSetup",
            "anio": 2025,
            "url": "https://simracingsetup.com/ea-sports-f1/f1-25-belgium-car-setup/",
            "clave_bibliografica": "simracingsetup_f1_25_spa",
        },
        "alcance": (
            "Referencia de comunidad para una configuracion de baja carga; "
            "no demuestra que sea optima ni que cause una mejora."
        ),
    },
}

ALIAS_CIRCUITO = {
    "spa": "spa-francorchamps",
    "spa_francorchamps": "spa-francorchamps",
    "francorchamps": "spa-francorchamps",
}


def referencia_de(circuito: str | None, programa: str = "F1 25") -> dict | None:
    """Devuelve una copia de la referencia aplicable, o ``None``."""

    if not circuito:
        return None
    clave_circuito = circuito.strip().lower().replace(" ", "-")
    clave_circuito = ALIAS_CIRCUITO.get(clave_circuito, clave_circuito)
    clave_programa = programa.strip().lower().replace(" ", "-")
    referencia = REFERENCIAS.get((clave_programa, clave_circuito))
    if referencia is None:
        return None
    return {
        **referencia,
        "valores": dict(referencia["valores"]),
        "fuente": dict(referencia["fuente"]),
    }
