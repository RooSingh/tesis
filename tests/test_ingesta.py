"""Pruebas de los endpoints de escritura, sin base ni guiones de verdad.

Nada de lo que se prueba aca toca TimescaleDB ni lanza un proceso real: la
conexion y `subprocess.Popen` estan sustituidos. Lo que se comprueba es lo que
puede fallar en silencio y costar datos:

- que un estado **desconocido** (base caida) no se confunda con **vacio**, que es
  la clase de error que hace que un tablero declare vacia una sesion con
  millones de filas;
- que el capturador se lance como proceso aparte con los argumentos que el guion
  entiende, y que no se pueda levantar un segundo escuchando el mismo puerto;
- que el resumen de lo capturado salga de los metadatos escritos en disco y
  declare lo que quedo sin cerrar;
- y que **borrar exija confirmacion, cuente antes y deje rastro**.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi import HTTPException

from backend import ingesta, live_stream


class ConexionFalsa:
    """Hace de conexion y de cursor a la vez, que es como los usa el modulo.

    Cada `execute` consume una respuesta de la lista y la deja lista para el
    `fetchone` siguiente. Se conservan las sentencias ejecutadas porque en las
    pruebas destructivas lo que importa no es solo lo que se devuelve sino
    **cuantas sentencias llegaron a correr**.
    """

    def __init__(self, respuestas: list, rowcount: int = 0) -> None:
        self.respuestas = list(respuestas)
        self.rowcount = rowcount
        self.ejecutadas: list[tuple[str, tuple | None]] = []
        self.commits = 0
        self._actual = None

    # -- protocolo de contexto, tanto de conexion como de cursor ----------- #

    def __enter__(self) -> "ConexionFalsa":
        return self

    def __exit__(self, *_excepcion) -> bool:
        return False

    def cursor(self) -> "ConexionFalsa":
        return self

    # -- protocolo de cursor ----------------------------------------------- #

    def execute(self, sentencia: str, parametros=None) -> None:
        self.ejecutadas.append((" ".join(sentencia.split()), parametros))
        self._actual = self.respuestas.pop(0) if self.respuestas else None

    def fetchone(self):
        return self._actual

    def commit(self) -> None:
        self.commits += 1

    @property
    def sentencias(self) -> list[str]:
        return [s for s, _ in self.ejecutadas]


class ProcesoFalso:
    """Un proceso hijo que no existe, pero que responde como uno."""

    def __init__(self, codigo: int = 0) -> None:
        self.pid = 4242
        self.codigo = codigo
        self.senales: list[int] = []
        self.terminado = False
        self.matado = False
        self._fin = threading.Event()

    def poll(self):
        return self.codigo if self._fin.is_set() else None

    def wait(self, timeout=None):
        if not self._fin.wait(timeout if timeout is not None else 10):
            raise subprocess.TimeoutExpired("falso", timeout)
        return self.codigo

    def send_signal(self, senal) -> None:
        self.senales.append(senal)
        self._fin.set()

    def terminate(self) -> None:
        self.terminado = True
        self._fin.set()

    def kill(self) -> None:
        self.matado = True
        self._fin.set()


def _esperar_trabajo(identificador: str, segundos: float = 5.0) -> dict:
    """Espera a que un trabajo deje de estar en curso, o falla la prueba."""

    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        estado = ingesta.trabajos.obtener(identificador)
        if estado is not None and not estado.en_curso():
            return estado.a_dict()
        time.sleep(0.02)
    raise AssertionError(f"El trabajo {identificador} no termino en {segundos} s.")


class PruebaDeIngesta(unittest.TestCase):
    """Base comun: registro de trabajos limpio y directorios de mentira."""

    def setUp(self) -> None:
        ingesta.trabajos.reiniciar()
        ingesta._CACHE_ESTADO = None
        live_stream.difusor.recientes.clear()
        self._temporal = TemporaryDirectory()
        self.temporal = Path(self._temporal.name)
        self.addCleanup(self._temporal.cleanup)
        self.addCleanup(ingesta.trabajos.reiniciar)
        self.addCleanup(live_stream.difusor.recientes.clear)

    def parchear_directorios(self):
        """Manda todo lo que se escribe en disco al directorio temporal."""

        capturas = self.temporal / "capturas"
        bitacoras = self.temporal / "logs"
        capturas.mkdir(parents=True, exist_ok=True)
        bitacoras.mkdir(parents=True, exist_ok=True)
        parches = [
            patch.object(ingesta, "CAPTURAS_F1", capturas),
            patch.object(ingesta, "BITACORAS", bitacoras),
            patch.object(ingesta, "REGISTRO_DESTRUCTIVO",
                         bitacoras / "ingesta_destructiva.jsonl"),
        ]
        for parche in parches:
            parche.start()
            self.addCleanup(parche.stop)
        return capturas, bitacoras


class EstadoDeLaSesionTests(PruebaDeIngesta):
    def test_sin_telemetria_persistida_declara_vacio(self) -> None:
        conexion = ConexionFalsa([None])
        with patch.object(ingesta.db, "obtener_conexion", return_value=conexion):
            respuesta = ingesta.sesion_activa()

        self.assertEqual(respuesta["estado"], "vacio")
        self.assertEqual(respuesta["filas"], 0)
        self.assertTrue(respuesta["disponible"])

    def test_sesion_persistida_declara_filas_y_senales(self) -> None:
        ultima = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
        conexion = ConexionFalsa([
            ("f1_25_udp", "f1_25:session:123"),   # ultima sesion de la base
            (2770, 89, ultima),                    # conteo de esa sesion
        ])
        with patch.object(ingesta.db, "obtener_conexion", return_value=conexion):
            respuesta = ingesta.sesion_activa()

        self.assertEqual(respuesta["estado"], "cargado")
        self.assertEqual(respuesta["fuente"], "f1_25_udp")
        self.assertEqual(respuesta["sesion"], "f1_25:session:123")
        self.assertEqual(respuesta["filas"], 2770)
        self.assertEqual(respuesta["senales"], 89)
        self.assertEqual(respuesta["ultimo_dato"], ultima.isoformat())
        # El conteo se acota por fuente y sesion: sin eso la consulta recorre la
        # tabla entera, que es el error que este endpoint no puede cometer
        # porque el tablero lo llama cada pocos segundos.
        self.assertIn("source_type = %s and session_id = %s",
                      conexion.sentencias[1])

    def test_flujo_en_vivo_convierte_cargado_en_recibiendo(self) -> None:
        conexion = ConexionFalsa([
            ("f1_25_udp", "f1_25:session:123"),
            (10, 4, None),
        ])
        live_stream.difusor.recientes.append({
            "source_type": "f1_25_udp",
            "session_id": "f1_25:session:123",
            "_recibido_utc": datetime.now(timezone.utc).isoformat(),
        })
        with patch.object(ingesta.db, "obtener_conexion", return_value=conexion):
            respuesta = ingesta.sesion_activa()

        self.assertEqual(respuesta["estado"], "recibiendo")
        self.assertIsNotNone(respuesta["en_vivo"])
        self.assertEqual(respuesta["filas"], 10)

    def test_un_mensaje_viejo_no_alcanza_para_recibiendo(self) -> None:
        conexion = ConexionFalsa([
            ("f1_25_udp", "f1_25:session:123"),
            (10, 4, None),
        ])
        viejo = datetime.now(timezone.utc) - timedelta(
            seconds=ingesta.SILENCIO_EN_VIVO_S + 30)
        live_stream.difusor.recientes.append({
            "source_type": "f1_25_udp",
            "session_id": "f1_25:session:123",
            "_recibido_utc": viejo.isoformat(),
        })
        with patch.object(ingesta.db, "obtener_conexion", return_value=conexion):
            respuesta = ingesta.sesion_activa()

        self.assertEqual(respuesta["estado"], "cargado")
        self.assertIsNone(respuesta["en_vivo"])

    def test_base_caida_no_se_confunde_con_sesion_vacia(self) -> None:
        with patch.object(ingesta.db, "obtener_conexion",
                          side_effect=OSError("conexion rechazada")):
            respuesta = ingesta.sesion_activa()

        self.assertFalse(respuesta["disponible"])
        self.assertEqual(respuesta["estado"], "desconocido")
        self.assertNotIn("filas", respuesta)
        self.assertIn("conexion rechazada", respuesta["motivo"])

    def test_el_conteo_se_guarda_y_no_se_repite(self) -> None:
        conexion = ConexionFalsa([
            ("f1_25_udp", "f1_25:session:123"),
            (7, 2, None),
        ])
        with patch.object(ingesta.db, "obtener_conexion", return_value=conexion):
            ingesta.sesion_activa()
            segunda = ingesta.sesion_activa()

        # Dos consultas en total, no cuatro: la segunda lectura sale de lo
        # guardado y lo declara con la edad del dato.
        self.assertEqual(len(conexion.ejecutadas), 2)
        self.assertEqual(segunda["filas"], 7)
        self.assertIn("edad_del_conteo_s", segunda)


class CapturaTests(PruebaDeIngesta):
    def test_iniciar_lanza_el_guion_y_devuelve_el_trabajo(self) -> None:
        self.parchear_directorios()
        proceso = ProcesoFalso()
        with patch.object(ingesta.subprocess, "Popen", return_value=proceso) as popen:
            respuesta = ingesta.captura_iniciar(
                ingesta.PeticionCaptura(puerto=20999, sesion="prueba_dia_23"))

        comando = popen.call_args[0][0]
        self.assertIn("capturar_f1_25.py", comando[1])
        self.assertIn("--puerto", comando)
        self.assertIn("20999", comando)
        # El nombre de sesion viaja como identidad de reinyeccion y no como
        # nombre de archivo: el archivo lo nombra el capturador desde el flujo.
        self.assertIn("--run-id", comando)
        self.assertIn("prueba_dia_23", comando)
        self.assertEqual(respuesta["estado"], "en_curso")
        self.assertEqual(respuesta["puerto"], 20999)
        self.assertIn("advertencia", respuesta)
        proceso.terminate()

    def test_los_pilotos_elegidos_viajan_al_capturador(self) -> None:
        """Se pasan por la linea de comandos, y el capturador los escribe.

        No los escribe esta ruta: los escribe el capturador, para que haya **una
        sola** fuente de a quien se escucha. Si los escribieran los dos, un
        arranque y una eleccion simultanea podrian dejar el archivo diciendo una
        cosa y el proceso usando otra.
        """

        self.parchear_directorios()
        proceso = ProcesoFalso()
        with patch.object(ingesta.subprocess, "Popen", return_value=proceso) as popen:
            ingesta.captura_iniciar(ingesta.PeticionCaptura(
                puerto=20999, pilotos=["Norris", "Leclerc"]))

        comando = popen.call_args[0][0]
        self.assertIn("--pilotos", comando)
        self.assertEqual(comando[comando.index("--pilotos") + 1], "Norris,Leclerc")
        proceso.terminate()

    def test_sin_pilotos_no_se_toca_lo_que_habia_elegido(self) -> None:
        """`None` es «no dije nada», no «borra la eleccion».

        La eleccion sobrevive entre sesiones a proposito: quien sigue a los
        mismos rivales no tiene que volver a marcarlos cada vez. Para vaciarla
        esta la lista vacia, que si es una decision.
        """

        self.parchear_directorios()
        proceso = ProcesoFalso()
        with patch.object(ingesta.subprocess, "Popen", return_value=proceso) as popen:
            ingesta.captura_iniciar(ingesta.PeticionCaptura(puerto=20999))
        self.assertNotIn("--pilotos", popen.call_args[0][0])
        proceso.terminate()

    def test_no_se_aceptan_mas_pilotos_de_los_que_la_cadena_sostiene(self) -> None:
        """El tope se explica, no se recorta en silencio.

        Recortar sin decirlo dejaria al tablero mostrando seis nombres marcados
        mientras el capturador escucha cuatro, y no habria forma de notarlo
        salvo contando filas.
        """

        self.parchear_directorios()
        with self.assertRaises(HTTPException) as fallo:
            ingesta.captura_iniciar(ingesta.PeticionCaptura(
                puerto=20999,
                pilotos=["a", "b", "c", "d", "e", "f", "g"]))
        self.assertEqual(fallo.exception.status_code, 422)
        self.assertIn("1.511", fallo.exception.detail)


class EleccionDePilotosEnVivoTests(PruebaDeIngesta):
    """Cambiar a quien se escucha sin cortar la captura."""

    def test_escribir_la_eleccion_la_deja_donde_el_capturador_la_lee(self) -> None:
        capturas, _ = self.parchear_directorios()
        respuesta = ingesta.captura_pilotos(
            ingesta.PeticionPilotos(pilotos=["Verstappen", "Norris"]))

        archivo = capturas / ".pilotos_elegidos.json"
        self.assertTrue(archivo.is_file())
        self.assertEqual(json.loads(archivo.read_text(encoding="utf-8")),
                         {"pilotos": ["Verstappen", "Norris"]})
        self.assertEqual(respuesta["pilotos"], ["Verstappen", "Norris"])
        self.assertEqual(respuesta["maximo"], 6)

    def test_una_lista_vacia_vacia_la_eleccion(self) -> None:
        """Es la unica forma de volver a escuchar solo el coche propio."""

        capturas, _ = self.parchear_directorios()
        ingesta.captura_pilotos(ingesta.PeticionPilotos(pilotos=["Norris"]))
        ingesta.captura_pilotos(ingesta.PeticionPilotos(pilotos=[]))
        archivo = capturas / ".pilotos_elegidos.json"
        self.assertEqual(json.loads(archivo.read_text(encoding="utf-8")),
                         {"pilotos": []})

    def test_leer_devuelve_lo_elegido_y_el_tope(self) -> None:
        capturas, _ = self.parchear_directorios()
        self.assertEqual(ingesta.captura_pilotos_actuales()["pilotos"], [])
        ingesta.captura_pilotos(ingesta.PeticionPilotos(pilotos=["Norris"]))
        leido = ingesta.captura_pilotos_actuales()
        self.assertEqual(leido["pilotos"], ["Norris"])
        self.assertEqual(leido["maximo"], 6)

    def test_un_archivo_ilegible_se_lee_como_sin_eleccion(self) -> None:
        """Y no como un error: el tablero tiene que poder dibujar la lista igual."""

        capturas, _ = self.parchear_directorios()
        (capturas / ".pilotos_elegidos.json").write_text("{roto", encoding="utf-8")
        self.assertEqual(ingesta.captura_pilotos_actuales()["pilotos"], [])

    def test_tampoco_aca_se_aceptan_mas_de_los_que_entran(self) -> None:
        self.parchear_directorios()
        with self.assertRaises(HTTPException) as fallo:
            ingesta.captura_pilotos(ingesta.PeticionPilotos(
                pilotos=["a", "b", "c", "d", "e", "f", "g"]))
        self.assertEqual(fallo.exception.status_code, 422)


    def test_no_se_admiten_dos_capturas_a_la_vez(self) -> None:
        self.parchear_directorios()
        proceso = ProcesoFalso()
        with patch.object(ingesta.subprocess, "Popen", return_value=proceso):
            ingesta.captura_iniciar(ingesta.PeticionCaptura(puerto=20999))
            with self.assertRaises(HTTPException) as fallo:
                ingesta.captura_iniciar(ingesta.PeticionCaptura(puerto=20999))

        self.assertEqual(fallo.exception.status_code, 409)
        self.assertIn("trabajo_en_curso", fallo.exception.detail)
        proceso.terminate()

    def test_detener_sin_captura_en_curso_es_un_conflicto(self) -> None:
        with self.assertRaises(HTTPException) as fallo:
            ingesta.captura_detener()
        self.assertEqual(fallo.exception.status_code, 409)

    def test_detener_resume_lo_capturado_desde_los_metadatos(self) -> None:
        capturas, _ = self.parchear_directorios()
        proceso = ProcesoFalso()
        with patch.object(ingesta.subprocess, "Popen", return_value=proceso):
            ingesta.captura_iniciar(ingesta.PeticionCaptura(puerto=20999))

        meta = capturas / "20260906_silverstone_carrera.f1raw.meta.json"
        meta.write_text(json.dumps({
            "archivo": "20260906_silverstone_carrera.f1raw",
            "duracion_s": 612.5,
            "frecuencia_telemetria_hz_medida": 19.9,
            "procedencia": {"circuito": "Silverstone", "tipo_sesion": "Carrera",
                            "session_uid": 123456789},
            "publicacion": {"mensajes": 25000, "descartados": 0},
        }), encoding="utf-8")
        # El instante del archivo se fija adelante para no depender de la
        # granularidad con la que el sistema de archivos guarda la hora.
        futuro = time.time() + 5
        os.utime(meta, (futuro, futuro))
        # Y una sesion que quedo a medio grabar cuando se apreto detener.
        (capturas / ".captura_en_curso_120000.f1raw").write_bytes(b"crudo")

        resumen = ingesta.captura_detener()

        self.assertEqual(resumen["estado"], "detenido")
        self.assertEqual(resumen["cierre"], "cierre_pedido")
        self.assertEqual(resumen["capturas_cerradas"], 1)
        self.assertEqual(resumen["capturas"][0]["circuito"], "Silverstone")
        self.assertEqual(resumen["capturas"][0]["sesion"], "f1_25:session:123456789")
        self.assertEqual(resumen["mensajes_publicados"], 25000)
        # Lo que quedo sin cerrar se declara en vez de callarse.
        self.assertEqual(resumen["provisionales_sin_cerrar"],
                         [".captura_en_curso_120000.f1raw"])
        self.assertIn("advertencia", resumen)
        self.assertTrue(proceso.senales)

    def test_un_proceso_que_no_arranca_no_queda_como_en_curso(self) -> None:
        self.parchear_directorios()
        with patch.object(ingesta.subprocess, "Popen",
                          side_effect=FileNotFoundError("no esta el interprete")):
            with self.assertRaises(HTTPException) as fallo:
                ingesta.captura_iniciar(ingesta.PeticionCaptura())

        self.assertEqual(fallo.exception.status_code, 500)
        self.assertIsNone(ingesta.trabajos.en_curso_de_tipo("captura_f1_25"))


class ImportacionOpenF1Tests(PruebaDeIngesta):
    def test_sesion_sin_paquete_descargado_es_404(self) -> None:
        with patch.object(ingesta, "PAQUETES_OPENF1", self.temporal / "openf1"):
            with self.assertRaises(HTTPException) as fallo:
                ingesta.openf1_importar(ingesta.PeticionOpenF1(session_key=1))
        self.assertEqual(fallo.exception.status_code, 404)

    def test_importar_delega_en_el_procesador_de_paquetes(self) -> None:
        raiz = self.temporal / "openf1"
        paquete = raiz / "2025" / "9947"
        paquete.mkdir(parents=True)
        resultado = {"status": "completed", "run": {"run_id": 3},
                     "counts": {"laps": 827}}

        with patch.object(ingesta, "PAQUETES_OPENF1", raiz):
            with patch("backend.session_processor.import_validated_package",
                       return_value=resultado) as importar:
                respuesta = ingesta.openf1_importar(
                    ingesta.PeticionOpenF1(session_key=9947))
                terminado = _esperar_trabajo(respuesta["trabajo"])

        self.assertEqual(respuesta["session_key"], 9947)
        self.assertEqual(terminado["estado"], "terminado")
        self.assertEqual(terminado["detalle"]["importacion"]["status"], "completed")
        self.assertEqual(importar.call_args[0][0], paquete)
        # Sin pedirlo, no se descarga nada: la descarga esta limitada por el
        # proveedor y no es un efecto que deba ocurrir de arrastre.
        self.assertNotIn("descarga", terminado["detalle"])

    def test_un_fallo_del_procesador_queda_declarado_en_el_trabajo(self) -> None:
        raiz = self.temporal / "openf1"
        (raiz / "2025" / "9947").mkdir(parents=True)

        with patch.object(ingesta, "PAQUETES_OPENF1", raiz):
            with patch("backend.session_processor.import_validated_package",
                       side_effect=ValueError("session.json invalido")):
                respuesta = ingesta.openf1_importar(
                    ingesta.PeticionOpenF1(session_key=9947))
                terminado = _esperar_trabajo(respuesta["trabajo"])

        self.assertEqual(terminado["estado"], "fallido")
        self.assertIn("session.json invalido", terminado["error"])

    def test_no_se_admiten_dos_importaciones_a_la_vez(self) -> None:
        raiz = self.temporal / "openf1"
        (raiz / "2025" / "9947").mkdir(parents=True)
        soltar = threading.Event()
        self.addCleanup(soltar.set)

        def _lenta(_paquete):
            soltar.wait(5)
            return {"status": "completed"}

        with patch.object(ingesta, "PAQUETES_OPENF1", raiz):
            with patch("backend.session_processor.import_validated_package",
                       side_effect=_lenta):
                primera = ingesta.openf1_importar(
                    ingesta.PeticionOpenF1(session_key=9947))
                with self.assertRaises(HTTPException) as fallo:
                    ingesta.openf1_importar(ingesta.PeticionOpenF1(session_key=9947))
                soltar.set()
                _esperar_trabajo(primera["trabajo"])

        self.assertEqual(fallo.exception.status_code, 409)


class ImportarOpenF1TraeLaTelemetriaTests(PruebaDeIngesta):
    """Importar un paquete es traer lo que el paquete tiene, y son dos mitades.

    HASTA EL 2026-09-13 ERA UNA SOLA. `/openf1/importar` registraba el contexto
    ---vueltas, paradas, clima--- y la telemetria de cada piloto no tenia forma
    de llegar a `telemetry_messages`. Medido sobre la Pi: tres sesiones OpenF1
    registradas y una sola que se podia abrir, la que alguien habia cargado a
    mano con un guion que publica por el intermediario.

    QUIEN LO NOTO FUE QUIEN LO USO. El usuario subio el paquete de Monaco, el
    tablero conto bien lo que entro, y despues la sesion no estaba en «Abrir
    sesion guardada». La lista tenia razon: no habia telemetria.
    """

    def _peticion(self, **kw):
        return ingesta.PeticionOpenF1(session_key=9979, **kw)

    def test_la_carga_de_telemetria_viene_encendida(self) -> None:
        """La subida manda `{session_key, descargar_telemetria}` y nada mas.

        Si hubiera que pedirla, el camino que la persona recorre ---subir y
        apretar--- seguiria terminando en una sesion que no se puede abrir.
        """
        self.assertTrue(self._peticion().cargar_telemetria)

    def test_se_puede_acotar_por_piloto(self) -> None:
        """Una carrera son veinte pilotos y varios millones de muestras."""
        self.assertEqual(self._peticion(pilotos=[1, 16]).pilotos, [1, 16])
        self.assertEqual(self._peticion().pilotos, [])

    def test_EL_TRABAJO_DECLARA_LA_SESION_QUE_DEJA(self) -> None:
        """Sin eso el catalogo no se entera y la sesion no aparece en la lista.

        Es el mismo defecto que dejo 57.890 filas del bus sin catalogar el
        2026-09-13: el refresco se dispara con lo que el trabajo deja en
        `detalle`, y un trabajo que no declara su sesion no refresca nada.
        """
        import inspect
        fuente = inspect.getsource(ingesta.openf1_importar)
        self.assertIn('"session_id"', fuente,
                      "el trabajo no declara la sesion que deja en la base")

    def _correr_importacion(self, carga, conciliacion):
        """Corre el trabajo con la carga y la conciliacion bajo control."""
        from backend import carga_openf1
        raiz = self.temporal / "openf1"
        paquete = raiz / "2025" / "9979"
        paquete.mkdir(parents=True, exist_ok=True)
        with patch.object(ingesta, "PAQUETES_OPENF1", raiz), \
             patch("backend.session_processor.import_validated_package",
                   return_value={"status": "completed", "run": {"run_id": 1},
                                 "counts": {"laps": 10}}), \
             patch.object(carga_openf1, "cargar_telemetria", return_value=carga), \
             patch.object(carga_openf1, "conciliar",
                          return_value=conciliacion) as concilia:
            respuesta = ingesta.openf1_importar(self._peticion())
            return _esperar_trabajo(respuesta["trabajo"]), concilia

    def test_LA_CARGA_SE_CONCILIA_CONTRA_LA_BASE(self) -> None:
        """Publicar no es guardar: entre la confirmacion de una escritura y el
        estado del destino cabe una perdida entera."""
        carga = {"validados": 900, "insertados": 900, "corrida": "c", "motivo": ""}
        terminado, concilia = self._correr_importacion(
            carga, {"esperado": 900, "presente": 900, "faltan": 0, "sobran": 0})
        concilia.assert_called_once_with(900, "c")
        self.assertEqual(terminado["estado"], "terminado")

    def test_UN_FALTANTE_HACE_FALLAR_EL_TRABAJO(self) -> None:
        """Un trabajo que termina bien sobre una carga incompleta es peor que
        uno que falla: el fallo se mira."""
        carga = {"validados": 900, "insertados": 400, "corrida": "c", "motivo": ""}
        terminado, _ = self._correr_importacion(
            carga, {"esperado": 900, "presente": 400, "faltan": 500, "sobran": 0})
        self.assertEqual(terminado["estado"], "fallido")
        self.assertIn("500", terminado["error"])
        self.assertIn("contexto quedo importado", terminado["error"],
                      "no dice que la primera mitad si entro")

    def test_sin_nada_que_cargar_no_se_concilia_ni_se_falla(self) -> None:
        """Un paquete de solo contexto es una respuesta legitima."""
        carga = {"validados": 0, "insertados": 0, "corrida": None,
                 "motivo": "el paquete no trae telemetria"}
        terminado, concilia = self._correr_importacion(carga, {})
        concilia.assert_not_called()
        self.assertEqual(terminado["estado"], "terminado")


class ImportacionCanTests(PruebaDeIngesta):
    def test_extraer_lanza_el_guion_de_extraccion(self) -> None:
        self.parchear_directorios()
        proceso = ProcesoFalso()
        with patch.object(ingesta.subprocess, "Popen", return_value=proceso) as popen:
            respuesta = ingesta.can_importar(
                ingesta.PeticionCan(segmentos=["sample_01", "sample_04"]))

        comando = popen.call_args[0][0]
        self.assertIn("extraer_can.py", comando[1])
        self.assertIn("--plataforma", comando)
        self.assertIn("TOYOTA_RAV4_TSS2", comando)
        self.assertIn("sample_04", comando)
        self.assertEqual(respuesta["etapa"], "extraer")
        proceso.terminate()

    def test_sin_segmentos_no_se_dispara_nada(self) -> None:
        with self.assertRaises(HTTPException) as fallo:
            ingesta.can_importar(ingesta.PeticionCan(segmentos=[]))
        self.assertEqual(fallo.exception.status_code, 400)

    def test_etapa_desconocida_se_rechaza(self) -> None:
        with self.assertRaises(HTTPException) as fallo:
            ingesta.can_importar(
                ingesta.PeticionCan(segmentos=["sample_01"], etapa="borrar"))
        self.assertEqual(fallo.exception.status_code, 400)

    def test_cargar_exige_que_el_segmento_este_extraido(self) -> None:
        with patch.object(ingesta, "CAPTURAS_CAN", self.temporal / "can"):
            with self.assertRaises(HTTPException) as fallo:
                ingesta.can_importar(
                    ingesta.PeticionCan(segmentos=["sample_99"], etapa="cargar"))

        self.assertEqual(fallo.exception.status_code, 409)
        self.assertEqual(fallo.exception.detail["faltantes"], ["sample_99"])

    def test_una_carga_declara_la_sesion_que_va_a_dejar_en_la_base(self) -> None:
        """EL DEFECTO QUE ESTO CIERRA, medido el 2026-09-13 sobre la Pi.

        Una carga CAN disparada desde el tablero termino bien, dejo 57.890
        filas de `can:segmento:sample_01` en la base, **y la sesion no aparecio
        en ninguna lista**: el catalogo nunca se entero. La causa es que el
        refresco se dispara con lo que el trabajo deja en `detalle`, y un
        trabajo lanzado como proceso aparte solo deja ahi el comando y el codigo
        de salida. El guion sabe que sesion toco; el servidor que lo lanzo, no.

        La sesion no se adivina ni se saca del registro del proceso: se
        **declara al lanzar**, porque el nombre se deriva del segmento y quien
        pide la carga ya lo tiene en la mano.
        """
        from adapters import can_rav4
        self.parchear_directorios()
        capturas_can = self.temporal / "can"
        capturas_can.mkdir()
        (capturas_can / "TOYOTA_RAV4_TSS2_sample_01.canraw").write_bytes(b"crudo")
        (capturas_can / "TOYOTA_RAV4_TSS2_sample_04.canraw").write_bytes(b"crudo")
        proceso = ProcesoFalso()
        with patch.object(ingesta, "CAPTURAS_CAN", capturas_can):
            with patch.object(ingesta.subprocess, "Popen", return_value=proceso):
                respuesta = ingesta.can_importar(ingesta.PeticionCan(
                    segmentos=["sample_01", "sample_04"], etapa="cargar"))

        self.assertEqual(
            respuesta["detalle"]["sesiones"],
            [can_rav4.identidad_de_sesion("sample_01"),
             can_rav4.identidad_de_sesion("sample_04")],
            "la carga no declaro las sesiones que va a dejar en la base")
        proceso.terminate()

    def test_la_extraccion_no_declara_ninguna_sesion(self) -> None:
        """No toca la base. Declarar una haria recontar por nada."""
        self.parchear_directorios()
        proceso = ProcesoFalso()
        with patch.object(ingesta.subprocess, "Popen", return_value=proceso):
            respuesta = ingesta.can_importar(
                ingesta.PeticionCan(segmentos=["sample_01"]))
        self.assertNotIn("sesiones", respuesta["detalle"])
        proceso.terminate()

    def test_cargar_lanza_el_reproductor_cuando_el_crudo_esta(self) -> None:
        self.parchear_directorios()
        capturas_can = self.temporal / "can"
        capturas_can.mkdir()
        (capturas_can / "TOYOTA_RAV4_TSS2_sample_01.canraw").write_bytes(b"crudo")
        proceso = ProcesoFalso()
        with patch.object(ingesta, "CAPTURAS_CAN", capturas_can):
            with patch.object(ingesta.subprocess, "Popen",
                              return_value=proceso) as popen:
                respuesta = ingesta.can_importar(
                    ingesta.PeticionCan(segmentos=["sample_01"], etapa="cargar"))

        comando = popen.call_args[0][0]
        self.assertIn("reproducir_can.py", comando[1])
        self.assertEqual(respuesta["etapa"], "cargar")
        proceso.terminate()


class BorradoDeSesionTests(PruebaDeIngesta):
    def test_sin_confirmar_no_borra_y_dice_cuanto_borraria(self) -> None:
        conexion = ConexionFalsa([(2770, 89, 1)])
        with patch.object(ingesta.db, "obtener_conexion", return_value=conexion):
            with self.assertRaises(HTTPException) as fallo:
                ingesta.borrar_sesion("f1_25:session:123")

        self.assertEqual(fallo.exception.status_code, 409)
        self.assertEqual(fallo.exception.detail["filas_a_borrar"], 2770)
        self.assertTrue(fallo.exception.detail["irreversible"])
        # Una sola sentencia, y de conteo: nada se borro.
        self.assertEqual(len(conexion.ejecutadas), 1)
        self.assertNotIn("delete", conexion.sentencias[0].lower())

    def test_confirmado_borra_concilia_y_deja_rastro(self) -> None:
        _, bitacoras = self.parchear_directorios()
        conexion = ConexionFalsa([(2770, 89, 1), None], rowcount=2770)
        # El refresco del catalogo se aisla: usa la misma conexion simulada y
        # su `commit` se contaria como si fuera del borrado. Esta prueba es
        # sobre el borrado, y el refresco tiene la suya.
        with patch.object(ingesta.db, "obtener_conexion", return_value=conexion),              patch.object(ingesta.catalogo_sesiones, "refrescar_sesion"):
            respuesta = ingesta.borrar_sesion("f1_25:session:123", confirmar=True)

        self.assertEqual(respuesta["borradas"], 2770)
        # Se concilia contra lo que debia quedar y no contra la ausencia de error.
        self.assertTrue(respuesta["conciliado"])
        self.assertEqual(conexion.commits, 1)
        self.assertIn("delete from telemetry_messages", conexion.sentencias[1])

        registro = bitacoras / "ingesta_destructiva.jsonl"
        lineas = registro.read_text(encoding="utf-8").strip().splitlines()
        asentado = json.loads(lineas[-1])
        self.assertEqual(asentado["session_id"], "f1_25:session:123")
        self.assertEqual(asentado["borradas"], 2770)
        self.assertEqual(asentado["operacion"], "borrar_sesion")
        self.assertIn("momento_utc", asentado)

    def test_borrado_parcial_no_se_declara_conciliado(self) -> None:
        self.parchear_directorios()
        conexion = ConexionFalsa([(2770, 89, 1), None], rowcount=2700)
        with patch.object(ingesta.db, "obtener_conexion", return_value=conexion):
            respuesta = ingesta.borrar_sesion("f1_25:session:123", confirmar=True)

        self.assertEqual(respuesta["borradas"], 2700)
        self.assertFalse(respuesta["conciliado"])

    def test_sesion_inexistente_es_404_aunque_este_confirmada(self) -> None:
        conexion = ConexionFalsa([(0, 0, 0)])
        with patch.object(ingesta.db, "obtener_conexion", return_value=conexion):
            with self.assertRaises(HTTPException) as fallo:
                ingesta.borrar_sesion("no:existe", confirmar=True)

        self.assertEqual(fallo.exception.status_code, 404)
        self.assertEqual(len(conexion.ejecutadas), 1)

    def test_un_borrado_que_falla_igual_queda_asentado(self) -> None:
        _, bitacoras = self.parchear_directorios()

        class ConexionQueFallaAlBorrar(ConexionFalsa):
            def execute(self, sentencia, parametros=None):
                if "delete" in sentencia.lower():
                    raise RuntimeError("chunk comprimido")
                super().execute(sentencia, parametros)

        conexion = ConexionQueFallaAlBorrar([(10, 2, 1)])
        with patch.object(ingesta.db, "obtener_conexion", return_value=conexion):
            with self.assertRaises(HTTPException) as fallo:
                ingesta.borrar_sesion("f1_25:session:123", confirmar=True)

        self.assertEqual(fallo.exception.status_code, 500)
        self.assertIn("chunk comprimido", fallo.exception.detail["error"])
        asentado = json.loads((bitacoras / "ingesta_destructiva.jsonl")
                              .read_text(encoding="utf-8").strip().splitlines()[-1])
        self.assertIsNone(asentado["borradas"])
        self.assertIn("chunk comprimido", asentado["error"])

    def test_base_inaccesible_no_borra_y_lo_dice(self) -> None:
        with patch.object(ingesta.db, "obtener_conexion",
                          side_effect=OSError("sin conexion")):
            with self.assertRaises(HTTPException) as fallo:
                ingesta.borrar_sesion("f1_25:session:123", confirmar=True)

        self.assertEqual(fallo.exception.status_code, 503)


class TrabajosTests(PruebaDeIngesta):
    def test_trabajo_inexistente_es_404(self) -> None:
        with self.assertRaises(HTTPException) as fallo:
            ingesta.obtener_trabajo("no-existe")
        self.assertEqual(fallo.exception.status_code, 404)

    def test_el_listado_va_del_mas_nuevo_al_mas_viejo(self) -> None:
        primero = ingesta.trabajos.lanzar_funcion(
            "openf1_importar", "primera", lambda: {"ok": 1})
        _esperar_trabajo(primero.identificador)
        segundo = ingesta.trabajos.lanzar_funcion(
            "openf1_importar", "segunda", lambda: {"ok": 2})
        _esperar_trabajo(segundo.identificador)

        listado = ingesta.listar_trabajos()["trabajos"]
        self.assertEqual([t["descripcion"] for t in listado], ["segunda", "primera"])

    def test_las_familias_no_se_estorban_entre_si(self) -> None:
        """Una captura y una importacion pueden convivir; dos importaciones no."""

        self.parchear_directorios()
        proceso = ProcesoFalso()
        soltar = threading.Event()
        self.addCleanup(soltar.set)
        with patch.object(ingesta.subprocess, "Popen", return_value=proceso):
            ingesta.captura_iniciar(ingesta.PeticionCaptura(puerto=20999))
            importacion = ingesta.trabajos.lanzar_funcion(
                "openf1_importar", "contexto", lambda: soltar.wait(5) or {"ok": True})

        self.assertTrue(importacion.en_curso())
        soltar.set()
        _esperar_trabajo(importacion.identificador)
        proceso.terminate()


if __name__ == "__main__":
    unittest.main()


class CatalogoAlDiaTests(unittest.TestCase):
    """La ingesta pone al dia el catalogo al terminar, sin rehacerlo entero.

    Es lo que evita que una sesion recien cargada no figure en ninguna lista
    hasta que alguien reconstruya el catalogo a mano.
    """

    def _trabajo(self, estado="terminado", detalle=None, tipo="captura_iniciar"):
        # `familia` se deriva del tipo y no se asigna: el tipo es el dato.
        from backend.ingesta import Trabajo
        t = Trabajo("id1", tipo, "prueba")
        t.estado = estado
        t.detalle = detalle or {}
        return t

    def test_al_terminar_refresca_solo_esa_sesion(self) -> None:
        from backend.ingesta import RegistroDeTrabajos
        t = self._trabajo(detalle={"session_id": "f1_25:session:9"})
        with patch("backend.ingesta.catalogo_sesiones.refrescar_en_segundo_plano") as ref:
            RegistroDeTrabajos._poner_al_dia_el_catalogo(t)
        ref.assert_called_once_with("f1_25:session:9")

    def test_refresca_cada_sesion_declarada_y_no_solo_la_primera(self) -> None:
        """Una carga CAN puede traer varios segmentos, y cada uno es una sesion.

        Con una sola refrescada, el primer segmento aparecia en la lista y los
        demas quedaban invisibles con sus filas ya en la base.
        """
        from backend.ingesta import RegistroDeTrabajos
        t = self._trabajo(tipo="can_cargar",
                          detalle={"comando": ["x"], "codigo_salida": 0,
                                   "sesiones": ["can:segmento:sample_01",
                                                "can:segmento:sample_04"]})
        with patch("backend.ingesta.catalogo_sesiones.refrescar_en_segundo_plano") as ref:
            RegistroDeTrabajos._poner_al_dia_el_catalogo(t)
        self.assertEqual([c.args[0] for c in ref.call_args_list],
                         ["can:segmento:sample_01", "can:segmento:sample_04"])

    def test_una_carga_que_no_declara_su_sesion_no_refresca_nada(self) -> None:
        """Es lo que pasaba, y sigue siendo lo correcto cuando no se sabe.

        Rehacer el catalogo entero ---149 s--- porque un trabajo no dijo que
        toco no es un arreglo: es castigar a toda la base por una omision.
        """
        from backend.ingesta import RegistroDeTrabajos
        t = self._trabajo(tipo="can_cargar",
                          detalle={"comando": ["x"], "codigo_salida": 0})
        with patch("backend.ingesta.catalogo_sesiones.refrescar_en_segundo_plano") as ref:
            RegistroDeTrabajos._poner_al_dia_el_catalogo(t)
        ref.assert_not_called()

    def test_un_trabajo_fallido_no_toca_el_catalogo(self) -> None:
        """Si la carga fallo, los numeros de antes siguen siendo los correctos."""
        from backend.ingesta import RegistroDeTrabajos
        t = self._trabajo(estado="fallido", detalle={"session_id": "s"})
        with patch("backend.ingesta.catalogo_sesiones.refrescar_en_segundo_plano") as ref:
            RegistroDeTrabajos._poner_al_dia_el_catalogo(t)
        ref.assert_not_called()

    def test_un_fallo_del_refresco_no_rompe_la_ingesta(self) -> None:
        """El dato ya esta cargado: el catalogo se puede rehacer a mano."""
        from backend.ingesta import RegistroDeTrabajos
        t = self._trabajo(detalle={"session_id": "s"})
        with patch("backend.ingesta.catalogo_sesiones.refrescar_en_segundo_plano",
                   side_effect=RuntimeError("sin base")):
            RegistroDeTrabajos._poner_al_dia_el_catalogo(t)  # no debe levantar


class BorradoQuitaDelCatalogoTests(unittest.TestCase):
    """Una sesion borrada no puede seguir figurando en la lista.

    Sin esto, la sesion recien borrada aparecia con sus millones de filas:
    alguien la elegia, todo llegaba vacio, y nada explicaba por que.
    """

    def test_el_borrado_refresca_esa_sesion_del_catalogo(self) -> None:
        import inspect
        from backend import ingesta
        fuente = inspect.getsource(ingesta.borrar_sesion)
        self.assertIn("catalogo_sesiones.refrescar_sesion(session_id)", fuente)

    def test_el_refresco_va_protegido_para_no_deshacer_el_borrado(self) -> None:
        """El dato ya no esta: si el catalogo falla, se rehace a mano."""
        import inspect
        from backend import ingesta
        fuente = inspect.getsource(ingesta.borrar_sesion)
        despues = fuente.split("catalogo_sesiones.refrescar_sesion(session_id)")[1]
        self.assertIn("except Exception", despues[:160])

    def test_refrescar_una_sesion_sin_filas_la_quita(self) -> None:
        """Es el mecanismo por el que el borrado la saca de la lista."""
        from backend import catalogo_sesiones
        consultas = []

        class Cur:
            def execute(self, c, p=None):
                consultas.append(c)
            def fetchall(self):
                return []
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False

        class Con:
            def cursor(self):
                return Cur()
            def commit(self):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False

        with patch("backend.catalogo_sesiones.db.obtener_conexion", return_value=Con()):
            quedo = catalogo_sesiones.refrescar_sesion("borrada")
        self.assertFalse(quedo)
        self.assertTrue(any("DELETE FROM sesiones_catalogo" in c for c in consultas))
