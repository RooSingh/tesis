"""Prueba del lote MQTT acotado sin publicar en el broker."""

from __future__ import annotations

import unittest

from scripts.day18_openf1_technical_batch import DRIVERS, RAW_PATH, build_batch


def _muestras_ausentes() -> list[str]:
    """Cuales de las seis muestras que el lote necesita no estan en disco.

    `datasets/` esta ignorado por git y no viaja al clonar. Las demas pruebas
    que dependen de una captura se saltean solas cuando no la encuentran; esta
    no lo hacia y **reventaba con FileNotFoundError**, que es una afirmacion
    distinta: dice que el codigo esta roto cuando lo unico que falta son los
    datos. Se declara la ausencia con los nombres, para que saltear no se
    confunda con no tener nada que probar.
    """

    return [f"{punto}_driver_{numero}_{sigla}.json"
            for numero, sigla in DRIVERS.items()
            for punto in ("car_data", "location")
            if not (RAW_PATH / f"{punto}_driver_{numero}_{sigla}.json").exists()]


class OpenF1TechnicalBatchTests(unittest.TestCase):
    def test_builds_exactly_the_authorized_messages(self) -> None:
        ausentes = _muestras_ausentes()
        if ausentes:
            self.skipTest(f"muestras ausentes en {RAW_PATH.name}: "
                          f"{', '.join(ausentes)}")
        messages = build_batch()
        self.assertEqual(len(messages), 27)
        self.assertEqual({message["driver_id"] for message in messages}, {"openf1:driver:1", "openf1:driver:4", "openf1:driver:81"})
        self.assertTrue(all(message["metadata"]["extra"]["replay_mode"] for message in messages))


if __name__ == "__main__":
    unittest.main()
