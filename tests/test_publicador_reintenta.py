# -*- coding: utf-8 -*-
"""El publicador reintenta en lugar de rendirse para siempre.

El caso que lo motiva es real. El capturador paso a correr como servicio
permanente, y la tarea lo lanzaba con el interprete del sistema en vez del
entorno del proyecto: `paho-mqtt` no estaba, la importacion fallo, y el
publicador quedo mudo para toda la vida del proceso. Una carrera entera de Spa
quedo grabada sin publicar un solo mensaje.

Dos defectos distintos, y este archivo cubre el segundo:

1. el interprete equivocado, que se corrigio en el `.bat`;
2. **rendirse en el primer fallo**, que era del disenio: con un proceso de vida
   corta era tolerable, con uno que arranca al iniciar sesion ---posiblemente
   antes que el broker--- deja de serlo.
"""

import time
import unittest
from unittest import mock

from scripts.capturar_f1_25 import Publicador


class ReintentoDeConexion(unittest.TestCase):

    def test_un_fallo_al_arrancar_no_es_definitivo(self):
        """Es exactamente el caso de Spa: falla al inicio y despues se puede."""

        intentos = []

        def conectar_falla_la_primera(self):
            self._proximo_intento = 0.0
            self._intentos += 1
            intentos.append(self._intentos)
            if self._intentos == 1:
                self.cliente = None
                self.motivo = "broker no disponible: ModuleNotFoundError"
            else:
                self.cliente = mock.Mock()
                self.motivo = None

        with mock.patch.object(Publicador, "_conectar", conectar_falla_la_primera):
            pub = Publicador(activo=True)
            self.assertIsNone(pub.cliente)
            self.assertIn("ModuleNotFoundError", pub.motivo)

            pub._reintentar_si_toca()
            self.assertIsNotNone(pub.cliente)
            self.assertIsNone(pub.motivo)

        self.assertEqual(intentos, [1, 2])

    def test_no_reintenta_antes_de_que_pase_el_intervalo(self):
        """Reintentar en cada paquete inundaria de intentos a 160 por segundo."""

        with mock.patch.object(Publicador, "_conectar") as conectar:
            pub = Publicador(activo=True)
            conectar.reset_mock()
            pub.cliente = None
            pub._proximo_intento = time.monotonic() + 60
            pub._reintentar_si_toca()
            conectar.assert_not_called()

    def test_no_reintenta_si_la_publicacion_esta_desactivada(self):
        """Desactivada por parametro es una decision, no un fallo."""

        with mock.patch.object(Publicador, "_conectar") as conectar:
            pub = Publicador(activo=False)
            pub._reintentar_si_toca()
            conectar.assert_not_called()
            self.assertEqual(pub.motivo, "desactivada por parametro")

    def test_el_motivo_nombra_el_error_concreto(self):
        """Un motivo generico no habria permitido encontrar la causa.

        Lo que resolvio el caso de Spa fue leer `ModuleNotFoundError` en los
        metadatos: nombra el defecto sin ambiguedad.
        """

        def falla(self):
            self._proximo_intento = 0.0
            self._intentos += 1
            self.cliente = None
            self.motivo = "broker no disponible: ModuleNotFoundError: No module named 'paho'"

        with mock.patch.object(Publicador, "_conectar", falla):
            pub = Publicador(activo=True)
        self.assertIn("ModuleNotFoundError", pub.motivo)
        self.assertIn("paho", pub.motivo)

    def test_una_conexion_exitosa_deja_el_motivo_vacio(self):
        with mock.patch("paho.mqtt.client.Client") as Cliente:
            Cliente.return_value.connect.return_value = None
            pub = Publicador(activo=True)
        self.assertIsNotNone(pub.cliente)
        self.assertIsNone(pub.motivo)
        self.assertTrue(pub.activa)


if __name__ == "__main__":
    unittest.main()
