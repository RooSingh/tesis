"""Escritura desde el tablero: arrancar, importar y borrar sin abrir una consola.

Por que existe
--------------
Hasta aca la aplicacion solo sabia **leer**: todos sus endpoints eran de
consulta, y cada dato que entro a la base entro por un guion ejecutado a mano.
Eso alcanza mientras quien opera tiene el repositorio abierto, y deja al tablero
mirando: puede mostrar lo que ya esta, no puede hacer que algo entre ni sacarlo.

Este modulo expone por HTTP las tres operaciones que faltaban ---capturar,
importar y borrar--- **envolviendo los guiones que ya existen**.

Envolver y no duplicar
----------------------
Ninguna de las operaciones esta reimplementada aca. Un guion que se copia se
bifurca: se corrige un lado y el otro queda con el error, y en este trabajo lo
que decide que es cierto es lo que corrio y no lo que esta escrito dos veces. De
modo que:

- ``scripts/capturar_f1_25.py`` se lanza como proceso aparte, porque su forma es
  un bucle que escucha un puerto hasta que lo interrumpen: no hay funcion que
  llamar y que devuelva.
- ``backend.session_processor.import_validated_package`` ---lo mismo que corre
  ``scripts/import_session_package.py``--- se llama directamente, porque si es
  una funcion.
- ``scripts/download_openf1_session_telemetry.py`` se usa por sus funciones
  (``plan_downloads``, ``execute_downloads`` y ``write_manifest``), que son
  importables.
- ``scripts/extraer_can.py`` y ``scripts/reproducir_can.py`` se lanzan como
  proceso aparte: el primero depende de openpilot y de dos rutas agregadas al
  camino de importacion, y meter esa dependencia dentro del servidor web ataria
  el arranque de la API a una biblioteca de 1,8 GB que hace falta una vez por
  segmento y nunca mas.

Por que un trabajo y no una respuesta
-------------------------------------
Ninguna de estas operaciones termina en el tiempo de una peticion: una captura
dura lo que dure la sesion, una importacion de contexto recorre archivos de
decenas de megabytes, y una descarga de OpenF1 esta limitada a treinta consultas
por minuto por el propio proveedor. Sostener la conexion abierta mientras tanto
convertiria cualquier corte de red en una operacion de resultado desconocido.

Cada endpoint de escritura devuelve entonces un **identificador de trabajo**, y
el estado se consulta aparte en ``/trabajos/{id}``. Es el mismo criterio que el
camino en vivo: lo que tarda corre en su propio hilo o proceso, y la vista
pregunta cuando quiere.

Que se serializa y por que
--------------------------
Se admite **una captura por vez** ---dos procesos no pueden escuchar el mismo
puerto--- y **una importacion por vez**. Lo segundo no es una limitacion tecnica
sino la misma conclusion que ya sostiene ``scripts/encolar_cargas_openf1.py``:
todas las cargas terminan en la misma base, correr dos no las acelera porque el
cuello es la persistencia, y el escenario de concurrencia del trabajo midio un
22,02 % de perdida al aumentar los mensajes en vuelo.

Lo destructivo se registra
--------------------------
El unico endpoint que borra exige confirmacion explicita, cuenta antes de borrar
y deja una linea en ``logs/ingesta_destructiva.jsonl`` con que se borro, cuantas
filas y cuando. Una operacion que destruye y no deja rastro no se puede auditar
despues, que es justamente cuando alguien pregunta por que faltan filas.
"""

from __future__ import annotations

import itertools
import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend import catalogo_corridas
from backend import config
from backend import catalogo_sesiones
from backend import db
from backend import live_stream


RAIZ = Path(__file__).resolve().parents[1]

#: Donde el capturador deja sus archivos crudos y sus metadatos.
CAPTURAS_F1 = RAIZ / "datasets" / "f1_25" / "capturas"

#: Donde viven los paquetes OpenF1 descargados, un directorio por sesion.
PAQUETES_OPENF1 = RAIZ / "datasets" / "OpenF1" / "raw"

#: Donde quedan las capturas CAN ya extraidas al formato propio.
CAPTURAS_CAN = RAIZ / "datasets" / "can" / "capturas"

#: Salida de los procesos lanzados desde aca. No se descarta: si una captura
#: falla, lo que dijo antes de morir es la unica evidencia de por que.
BITACORAS = RAIZ / "logs"

#: Registro de lo destructivo. Una linea JSON por borrado.
REGISTRO_DESTRUCTIVO = BITACORAS / "ingesta_destructiva.jsonl"

#: Cuanto vale una lectura del estado antes de volver a preguntarle a la base.
#: El tablero consulta cada pocos segundos y el estado cambia despacio: contar
#: las filas de una sesion en cada refresco le costaria a la base mas que
#: guardar el resultado.
VIGENCIA_ESTADO_S = 5.0

#: Cuanto puede hacer que llego el ultimo mensaje en vivo para que la sesion se
#: considere **recibiendo**. El juego emite a decenas de hercios: diez segundos
#: de silencio no son una pausa, son que dejo de emitir.
SILENCIO_EN_VIVO_S = 10.0

#: Cuanto se espera a que el capturador cierre solo antes de forzarlo.
ESPERA_CIERRE_S = 15.0

#: Cuantos trabajos terminados se conservan. Los que siguen en curso no se
#: descartan nunca, sin importar cuantos sean.
TRABAJOS_CONSERVADOS = 50

#: Familia de cada tipo de trabajo. Dos trabajos de la misma familia no corren a
#: la vez: ver el encabezado del modulo.
FAMILIAS = {
    "captura_f1_25": "captura",
    "openf1_importar": "importacion",
    "can_extraer": "importacion",
    "can_cargar": "importacion",
}


router = APIRouter(tags=["ingesta"])

#: Orden de llegada de los trabajos. Se lleva aparte del reloj porque el reloj
#: monotono de Windows avanza de a unos quince milisegundos: dos trabajos
#: lanzados uno detras del otro comparten instante y no se pueden ordenar por el.
_ORDEN = itertools.count()


def _ahora_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _puerto_por_defecto() -> int:
    """El puerto que el capturador usa por omision, leido del propio guion.

    Se lee tarde y no al importar. Copiarlo aca como numero suelto haria que el
    dia que el guion cambie de puerto la API siguiera ofreciendo el viejo, y el
    tablero mostraria un valor que no es el que el capturador escucha.
    """

    try:
        from scripts.capturar_f1_25 import PUERTO_JUEGO  # noqa: PLC0415

        return int(PUERTO_JUEGO)
    except Exception:  # noqa: BLE001
        # Que no se pueda leer la constante del guion no es razon para que el
        # tablero no arranque: se cae al valor documentado del protocolo.
        return 20777


# --------------------------------------------------------------------------- #
# Trabajos
# --------------------------------------------------------------------------- #


@dataclass
class Trabajo:
    """Una operacion larga, en curso o terminada, con lo que se sabe de ella."""

    identificador: str
    tipo: str
    descripcion: str
    orden: int = field(default_factory=lambda: next(_ORDEN))
    estado: str = "en_curso"          # en_curso | terminado | fallido | detenido
    comienzo_utc: str = field(default_factory=_ahora_utc)
    comienzo_monotono: float = field(default_factory=time.monotonic)
    fin_utc: str | None = None
    detalle: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    bitacora: str | None = None
    proceso: Any = None               # subprocess.Popen, si el trabajo es un proceso

    @property
    def familia(self) -> str:
        return FAMILIAS.get(self.tipo, self.tipo)

    def en_curso(self) -> bool:
        return self.estado == "en_curso"

    def a_dict(self) -> dict[str, Any]:
        """Vista serializable. El proceso no viaja: viaja lo que se sabe de el."""

        cuerpo = {
            "trabajo": self.identificador,
            "tipo": self.tipo,
            "familia": self.familia,
            "descripcion": self.descripcion,
            "estado": self.estado,
            "comienzo_utc": self.comienzo_utc,
            "fin_utc": self.fin_utc,
            "duracion_s": round(time.monotonic() - self.comienzo_monotono, 1),
            "detalle": self.detalle,
            "error": self.error,
            "bitacora": self.bitacora,
        }
        if self.proceso is not None:
            cuerpo["pid"] = getattr(self.proceso, "pid", None)
            cuerpo["codigo_salida"] = self.proceso.poll()
        return cuerpo


class RegistroDeTrabajos:
    """Lleva los trabajos lanzados desde la API y garantiza que no se pisen.

    El candado protege el diccionario, que lo tocan tres clases de hilo: el que
    atiende la peticion, el que ejecuta el trabajo y el que vigila un proceso
    hijo. Es la misma forma que usa el difusor en vivo con sus suscriptores.
    """

    def __init__(self) -> None:
        self._trabajos: dict[str, Trabajo] = {}
        self._candado = threading.Lock()

    # -- consulta ---------------------------------------------------------- #

    def obtener(self, identificador: str) -> Trabajo | None:
        with self._candado:
            return self._trabajos.get(identificador)

    def listar(self) -> list[dict[str, Any]]:
        with self._candado:
            trabajos_actuales = list(self._trabajos.values())
        return [t.a_dict() for t in sorted(trabajos_actuales,
                                           key=lambda t: t.orden, reverse=True)]

    def en_curso_de_familia(self, familia: str) -> Trabajo | None:
        with self._candado:
            for trabajo in self._trabajos.values():
                if trabajo.familia == familia and trabajo.en_curso():
                    return trabajo
        return None

    def en_curso_de_tipo(self, tipo: str) -> Trabajo | None:
        with self._candado:
            for trabajo in self._trabajos.values():
                if trabajo.tipo == tipo and trabajo.en_curso():
                    return trabajo
        return None

    # -- alta -------------------------------------------------------------- #

    def _registrar(self, trabajo: Trabajo) -> Trabajo:
        with self._candado:
            self._trabajos[trabajo.identificador] = trabajo
            terminados = sorted(
                (t for t in self._trabajos.values() if not t.en_curso()),
                key=lambda t: t.orden)
            sobran = len(terminados) - TRABAJOS_CONSERVADOS
            for viejo in terminados[:max(sobran, 0)]:
                self._trabajos.pop(viejo.identificador, None)
        return trabajo

    @staticmethod
    def _poner_al_dia_el_catalogo(trabajo: "Trabajo") -> None:
        """Actualiza el catalogo con la sesion que este trabajo acaba de tocar.

        POR QUE ACA Y NO EN LOS GUIONES DE CARGA. Los catalogos ---de sesiones
        y de corridas--- se calculan una vez y se guardan, porque derivarlos en
        cada consulta cuesta minutos sobre la tabla comprimida. El precio de esa
        decision es que quedan viejos: una sesion recien cargada no figuraba en
        ninguna lista hasta que alguien reconstruia el catalogo entero.

        Este es el punto donde eso se cierra. La ingesta **sabe** cuando termina
        una carga y que sesion toco, de modo que puede poner al dia esa fila y
        nada mas: 0,65 s sobre una sesion chica y 7,2 s sobre la mas grande,
        contra los 149 s de rehacerlo todo.

        Corre por detras y no puede hacer fallar al trabajo: si el refresco no
        sale, el dato igual esta cargado y el catalogo se puede rehacer a mano.
        """
        if trabajo.estado != "terminado":
            return
        detalle = trabajo.detalle or {}
        sesion = (detalle.get("session_id") or detalle.get("sesion")
                  or detalle.get("run_id"))
        try:
            catalogo_sesiones.refrescar_en_segundo_plano(sesion)
            if trabajo.familia == "importacion":
                catalogo_corridas.pedir_reconstruccion()
        except Exception:  # noqa: BLE001 - el refresco nunca rompe la ingesta
            pass

    def _exigir_familia_libre(self, tipo: str) -> None:
        ocupado = self.en_curso_de_familia(FAMILIAS.get(tipo, tipo))
        if ocupado is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "mensaje": ("Ya hay un trabajo de la misma familia en curso. "
                                "Se admite uno por vez: dos no terminan antes y "
                                "comparten la misma base."),
                    "trabajo_en_curso": ocupado.a_dict(),
                },
            )

    def lanzar_funcion(self, tipo: str, descripcion: str,
                       funcion: Callable[[], dict]) -> Trabajo:
        """Corre `funcion` en su propio hilo y guarda lo que devuelva."""

        self._exigir_familia_libre(tipo)
        trabajo = self._registrar(Trabajo(uuid.uuid4().hex[:12], tipo, descripcion))

        def _correr() -> None:
            try:
                resultado = funcion()
                trabajo.detalle = (resultado if isinstance(resultado, dict)
                                   else {"resultado": resultado})
                trabajo.estado = "terminado"
            except Exception as error:  # noqa: BLE001
                # Un fallo del trabajo no puede tumbar el servidor: queda
                # declarado en el trabajo, que es donde alguien va a mirarlo.
                trabajo.estado = "fallido"
                trabajo.error = f"{type(error).__name__}: {error}"
            finally:
                trabajo.fin_utc = _ahora_utc()
                self._poner_al_dia_el_catalogo(trabajo)

        threading.Thread(target=_correr, name=f"ingesta-{tipo}", daemon=True).start()
        return trabajo

    def lanzar_proceso(self, tipo: str, descripcion: str,
                       comando: list[str]) -> Trabajo:
        """Lanza un guion como proceso aparte y vigila su salida."""

        self._exigir_familia_libre(tipo)
        trabajo = self._registrar(Trabajo(uuid.uuid4().hex[:12], tipo, descripcion))
        trabajo.detalle = {"comando": comando}

        salida = None
        try:
            BITACORAS.mkdir(parents=True, exist_ok=True)
            ruta_bitacora = BITACORAS / f"tablero_{tipo}_{trabajo.identificador}.log"
            trabajo.bitacora = str(ruta_bitacora)
            salida = ruta_bitacora.open("w", encoding="utf-8", errors="replace")
            # En Windows hace falta un grupo de procesos propio para poder
            # pedirle despues que se cierre: sin el, la senal alcanzaria tambien
            # al servidor que lo lanzo.
            creacion = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            proceso = subprocess.Popen(  # noqa: S603
                comando,
                cwd=str(RAIZ),
                stdout=salida,
                stderr=subprocess.STDOUT,
                creationflags=creacion,
            )
        except Exception as error:  # noqa: BLE001
            # El archivo se cierra aca y no en el vigia: si el proceso no llego a
            # arrancar, no hay vigia que lo cierre y el descriptor queda abierto
            # hasta que muera el servidor.
            if salida is not None:
                salida.close()
            trabajo.estado = "fallido"
            trabajo.error = f"{type(error).__name__}: {error}"
            trabajo.fin_utc = _ahora_utc()
            return trabajo

        trabajo.proceso = proceso

        def _vigilar() -> None:
            codigo = proceso.wait()
            try:
                salida.close()
            except OSError:
                pass
            trabajo.fin_utc = _ahora_utc()
            trabajo.detalle = {**trabajo.detalle, "codigo_salida": codigo}
            if trabajo.estado == "en_curso":
                trabajo.estado = "terminado" if codigo == 0 else "fallido"
                if codigo != 0:
                    trabajo.error = (f"El proceso termino con codigo {codigo}. "
                                     f"Ver {trabajo.bitacora}.")
            self._poner_al_dia_el_catalogo(trabajo)

        threading.Thread(target=_vigilar, name=f"vigia-{tipo}", daemon=True).start()
        return trabajo

    def detener_proceso(self, trabajo: Trabajo,
                        espera_s: float = ESPERA_CIERRE_S) -> str:
        """Pide el cierre y, si no llega, lo fuerza. Devuelve como termino.

        Se pide primero por senal porque el capturador tiene un cierre ordenado
        ---informa cuantas sesiones grabo y cierra el publicador--- y matarlo de
        entrada se lo saltea.

        **El cierre ordenado no esta garantizado en Windows**, donde la senal
        disponible para un proceso de otro grupo es la de interrupcion del
        entorno y no la que el interprete convierte en excepcion. Por eso el
        resumen de `/captura/detener` se lee de los metadatos que ya estan en
        disco y no de lo que el proceso alcance a decir al morir.
        """

        proceso = trabajo.proceso
        if proceso is None:
            trabajo.estado = "detenido"
            trabajo.fin_utc = _ahora_utc()
            return "sin_proceso"
        if proceso.poll() is not None:
            return "ya_habia_terminado"

        try:
            if os.name == "nt":
                proceso.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                proceso.send_signal(signal.SIGINT)
        except Exception:  # noqa: BLE001
            proceso.terminate()

        try:
            proceso.wait(timeout=espera_s)
            forma = "cierre_pedido"
        except subprocess.TimeoutExpired:
            proceso.terminate()
            try:
                proceso.wait(timeout=5)
                forma = "terminado"
            except subprocess.TimeoutExpired:
                proceso.kill()
                forma = "forzado"

        trabajo.estado = "detenido"
        trabajo.fin_utc = _ahora_utc()
        return forma

    def reiniciar(self) -> None:
        """Vacia el registro. Existe para las pruebas, no para la operacion."""

        with self._candado:
            self._trabajos.clear()


trabajos = RegistroDeTrabajos()


def _exigir_trabajo(identificador: str) -> Trabajo:
    trabajo = trabajos.obtener(identificador)
    if trabajo is None:
        raise HTTPException(status_code=404,
                            detail=f"No existe el trabajo {identificador!r}.")
    return trabajo


@router.get("/trabajos")
def listar_trabajos() -> dict:
    """Los trabajos lanzados desde esta aplicacion, del mas nuevo al mas viejo.

    **Viven en memoria del proceso.** Reiniciar el backend los pierde, y eso es
    deliberado: lo que hay que poder reconstruir despues es el dato ---que queda
    en disco y en la base con su procedencia--- y no la lista de veces que
    alguien apreto un boton.
    """

    return {"conservados": TRABAJOS_CONSERVADOS, "trabajos": trabajos.listar()}


@router.get("/trabajos/{trabajo_id}")
def obtener_trabajo(trabajo_id: str) -> dict:
    """Estado de un trabajo concreto, con su resultado si ya termino."""

    return _exigir_trabajo(trabajo_id).a_dict()


# --------------------------------------------------------------------------- #
# Estado de la sesion cargada
# --------------------------------------------------------------------------- #

_CACHE_ESTADO: tuple[float, tuple, dict] | None = None
#: Sin el, la cache caducada dispara tantos recorridos de la tabla como
#: peticiones simultaneas haya.
_CANDADO_ESTADO = threading.Lock()


def _contar_sesion(fuente: str, sesion: str) -> tuple[int, int, Any]:
    """Filas, senales distintas y ultima marca de una sesion persistida.

    Se cuenta acotando por fuente y sesion porque el indice de la tabla empieza
    por ahi. Contar sin acotar recorre la tabla entera, que ya paso de los diez
    millones de filas.
    """

    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        cursor.execute(
            """select count(*), count(distinct signal_name), max(timestamp)
               from telemetry_messages
               where source_type = %s and session_id = %s""",
            (fuente, sesion),
        )
        fila = cursor.fetchone()
    if fila is None:
        return 0, 0, None
    return fila[0] or 0, fila[1] or 0, fila[2]


def _ultima_sesion_persistida() -> tuple[str, str] | None:
    """La fuente y la sesion de la fila mas reciente de la base.

    Se pide **una sola fila ordenada por tiempo** y no un agregado por sesion: lo
    segundo agrupa millones de filas y ya se midio en decenas de segundos, y lo
    primero lo resuelve el orden temporal de la hipertabla.
    """

    with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
        cursor.execute(
            """select source_type, session_id from telemetry_messages
               order by timestamp desc limit 1""")
        fila = cursor.fetchone()
    if fila is None or fila[1] is None:
        return None
    return fila[0], fila[1]


def _recibiendo_en_vivo() -> dict | None:
    """Lo ultimo que llego por el flujo en vivo, si llego hace poco.

    Es lo que distingue **recibiendo** de **cargado**: la base no sabe si algo
    esta entrando ahora mismo, solo sabe lo que ya entro.
    """

    recientes = list(live_stream.difusor.recientes)
    if not recientes:
        return None
    ultimo = recientes[-1]
    marca = ultimo.get("_recibido_utc")
    if not marca:
        return None
    try:
        recibido = datetime.fromisoformat(marca)
    except (TypeError, ValueError):
        return None
    edad = (datetime.now(timezone.utc) - recibido).total_seconds()
    if edad > SILENCIO_EN_VIVO_S:
        return None
    return {
        "fuente": ultimo.get("source_type"),
        "sesion": ultimo.get("session_id"),
        "edad_s": round(edad, 1),
    }


def _estado_persistido(fuente: str | None, sesion: str | None) -> dict:
    """Lo que la base sabe de la sesion pedida, o de la mas reciente."""

    try:
        if fuente is None or sesion is None:
            encontrada = _ultima_sesion_persistida()
            if encontrada is None:
                return {
                    "disponible": True,
                    "estado": "vacio",
                    "fuente": fuente,
                    "sesion": sesion,
                    "senales": 0,
                    "filas": 0,
                    "ultimo_dato": None,
                    "motivo": "no hay telemetria persistida en la base",
                }
            fuente, sesion = encontrada
        filas, senales, ultimo = _contar_sesion(fuente, sesion)
    except Exception as error:  # noqa: BLE001
        # Que la base no responda es una respuesta, y distinta de "no hay nada".
        # Devolver cero filas aca haria que el tablero declarara vacia una sesion
        # que puede tener millones.
        return {
            "disponible": False,
            "estado": "desconocido",
            "fuente": fuente,
            "sesion": sesion,
            "motivo": f"{type(error).__name__}: {error}",
        }

    return {
        "disponible": True,
        "estado": "cargado" if filas else "vacio",
        "fuente": fuente,
        "sesion": sesion,
        "senales": senales,
        "filas": filas,
        "ultimo_dato": ultimo.isoformat() if hasattr(ultimo, "isoformat") else ultimo,
        "conteo": "exacto, acotado por fuente y sesion",
    }


@router.get("/sesion/activa")
def sesion_activa(fuente: str | None = None, sesion: str | None = None) -> dict:
    """Que fuente y que sesion tiene cargada el sistema, y en que estado.

    Es el endpoint que el tablero consulta para pintar su estado, y por eso
    distingue tres cosas que en un panel vacio se ven igual:

    - ``vacio``: no hay ninguna sesion persistida de esa fuente;
    - ``cargado``: hay una sesion persistida y nadie esta emitiendo;
    - ``recibiendo``: ademas esta entrando dato ahora mismo.

    La diferencia entre las dos ultimas no la puede dar la base: la base sabe lo
    que ya entro, no si algo esta entrando. Se resuelve mirando el flujo en vivo,
    que es el unico que observa el presente.

    Sin parametros informa la sesion mas reciente de la base. Con `fuente` y
    `sesion` informa la que se le pida, que es lo que permite al tablero seguir
    mostrando una sesion vieja mientras entra otra.
    """

    global _CACHE_ESTADO

    en_vivo = _recibiendo_en_vivo()
    captura = trabajos.en_curso_de_tipo("captura_f1_25")
    clave = (fuente, sesion)
    ahora = time.monotonic()

    if (_CACHE_ESTADO and _CACHE_ESTADO[1] == clave
            and ahora - _CACHE_ESTADO[0] < VIGENCIA_ESTADO_S):
        base = dict(_CACHE_ESTADO[2])
        base["edad_del_conteo_s"] = round(ahora - _CACHE_ESTADO[0], 1)
    else:
        # SE CALCULA UNA VEZ, AUNQUE LO PIDAN VARIOS A LA VEZ.
        #
        # En frio esto tarda quince segundos. Sin candado, cinco peticiones
        # simultaneas arrancan cinco recorridos identicos de la tabla: es la
        # estampida clasica de una cache que caduca, y ocurre justo al abrir el
        # tablero, que es cuando mas molesta. Con el candado, el primero calcula
        # y los que llegan detras usan lo que dejo.
        with _CANDADO_ESTADO:
            ahora = time.monotonic()
            if (_CACHE_ESTADO and _CACHE_ESTADO[1] == clave
                    and ahora - _CACHE_ESTADO[0] < VIGENCIA_ESTADO_S):
                base = dict(_CACHE_ESTADO[2])
                base["edad_del_conteo_s"] = round(ahora - _CACHE_ESTADO[0], 1)
            else:
                base = _estado_persistido(fuente, sesion)
                _CACHE_ESTADO = (time.monotonic(), clave, dict(base))
                base["edad_del_conteo_s"] = 0.0

    respuesta = dict(base)
    respuesta["en_vivo"] = en_vivo
    respuesta["captura_en_curso"] = captura.a_dict() if captura is not None else None
    if en_vivo is not None and respuesta.get("estado") in {"vacio", "cargado"}:
        # El flujo manda sobre la base para decidir el estado: si esta llegando
        # dato, la sesion esta recibiendo aunque el conteo sea de hace un rato.
        respuesta["estado"] = "recibiendo"
        if respuesta.get("fuente") is None:
            respuesta["fuente"] = en_vivo["fuente"]
        if respuesta.get("sesion") is None:
            respuesta["sesion"] = en_vivo["sesion"]
    return respuesta


# --------------------------------------------------------------------------- #
# Captura F1 25
# --------------------------------------------------------------------------- #


class PeticionCaptura(BaseModel):
    """Lo poco que el capturador admite que se le diga desde afuera.

    El resto de la procedencia ---circuito, tipo de sesion, clima, ayudas--- la
    deriva el guion del propio flujo y no de un formulario, deliberadamente: un
    metadato tipeado a mano puede contradecir a los datos, uno leido del flujo no.
    """

    puerto: int | None = Field(default=None, ge=1, le=65535)
    sesion: str | None = None
    publicar: bool = True
    parrilla_completa: bool = False


def _capturas_desde(momento: float) -> list[dict]:
    """Los metadatos de las capturas cerradas despues de `momento`."""

    if not CAPTURAS_F1.is_dir():
        return []
    cerradas = []
    for meta in sorted(CAPTURAS_F1.glob("*.meta.json")):
        try:
            if meta.stat().st_mtime < momento:
                continue
            datos = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        procedencia = datos.get("procedencia") or {}
        publicacion = datos.get("publicacion") or {}
        cerradas.append({
            "archivo": datos.get("archivo") or meta.name.replace(".meta.json", ""),
            "duracion_s": datos.get("duracion_s"),
            "circuito": procedencia.get("circuito"),
            "tipo_sesion": procedencia.get("tipo_sesion"),
            "sesion": (f"f1_25:session:{procedencia['session_uid']}"
                       if procedencia.get("session_uid") is not None else None),
            "frecuencia_telemetria_hz_medida": datos.get(
                "frecuencia_telemetria_hz_medida"),
            "mensajes_publicados": publicacion.get("mensajes"),
            "mensajes_descartados": publicacion.get("descartados"),
        })
    return cerradas


@router.post("/captura/iniciar")
def captura_iniciar(peticion: PeticionCaptura) -> dict:
    """Pone a escuchar el capturador de F1 25 y devuelve el trabajo que lo lleva.

    **El nombre de sesion no nombra el archivo.** El capturador deriva el nombre
    del archivo del propio flujo ---fecha, circuito y modo---, que es mas trazable
    que uno escrito a mano porque no puede estar equivocado. Lo que se hace con
    `sesion` es pasarlo como identidad de reinyeccion (`--run-id`), que es el
    campo previsto para distinguir una corrida que no es una sesion real de la
    telemetria verdadera. Sin `sesion` no se pasa nada y el capturador se comporta
    igual que lanzado a mano.

    No se espera a que capture: devuelve enseguida. Una captura dura lo que dure
    la sesion de juego, y no hay peticion HTTP que aguante eso.
    """

    puerto = peticion.puerto or _puerto_por_defecto()
    comando = [sys.executable, str(RAIZ / "scripts" / "capturar_f1_25.py"),
               "--puerto", str(puerto)]
    if not peticion.publicar:
        comando.append("--sin-publicar")
    # La parrilla completa se puede limitar por entorno, y **si se limita se
    # dice**. Ignorar en silencio lo que pidio quien llama seria peor que el
    # problema que esto evita: el tablero seguiria creyendo que captura los
    # veintidos coches y no habria forma de notarlo hasta contar las filas. El
    # motivo y las mediciones estan en `backend/config.py`.
    parrilla = peticion.parrilla_completa and not config.CAPTURA_SOLO_VEHICULO_PROPIO
    limitada = peticion.parrilla_completa and not parrilla
    if parrilla:
        comando.append("--parrilla-completa")
    if peticion.sesion:
        comando += ["--run-id", peticion.sesion]

    trabajo = trabajos.lanzar_proceso(
        "captura_f1_25", f"captura F1 25 en el puerto {puerto}", comando)
    if trabajo.estado == "fallido":
        raise HTTPException(status_code=500, detail=trabajo.error)

    respuesta = trabajo.a_dict()
    respuesta["puerto"] = puerto
    respuesta["run_id"] = peticion.sesion
    respuesta["parrilla_completa"] = parrilla
    if limitada:
        respuesta["parrilla_limitada_porque"] = (
            "Esta instalacion captura solo el vehiculo propio "
            "(CAPTURA_SOLO_VEHICULO_PROPIO). La parrilla completa multiplica "
            "por veintidos las senales, y en esta maquina se descartaba el 87 % "
            "---tambien las del coche propio---.")
    respuesta["destino"] = str(CAPTURAS_F1)
    respuesta["advertencia"] = (
        "El nombre del archivo lo deriva el capturador del flujo. `sesion` viaja "
        "como identidad de reinyeccion (--run-id), no como nombre de archivo.")
    return respuesta


@router.post("/captura/detener")
def captura_detener(trabajo_id: str | None = None) -> dict:
    """Detiene el capturador y devuelve el resumen de lo capturado.

    El resumen **no se le pregunta al proceso**: se lee de los metadatos que el
    capturador ya escribio junto a cada archivo al cerrar cada sesion. Es la
    misma fuente que usa `/live/parrilla`, y es la unica que sobrevive a que el
    proceso muera de mala manera.

    **Limite declarado.** Una sesion que estaba grabando en el momento de la
    detencion no llega a cerrarse: su archivo provisional
    (`.captura_en_curso_*.f1raw`) queda en el directorio sin metadatos, porque la
    procedencia se deriva y se escribe recien al terminar. La respuesta los lista
    en vez de callarlos. Para detener sin perder nada hay que hacerlo entre
    sesiones, con el juego fuera de pista.
    """

    trabajo = (_exigir_trabajo(trabajo_id) if trabajo_id
               else trabajos.en_curso_de_tipo("captura_f1_25"))
    if trabajo is None:
        raise HTTPException(status_code=409,
                            detail="No hay ninguna captura en curso para detener.")

    # El disco se mide con el reloj de pared y el trabajo con el monotono. Se
    # traduce uno al otro en vez de guardar dos relojes: el monotono es el unico
    # que no se mueve si alguien ajusta la hora del equipo a mitad de una sesion.
    momento_disco = time.time() - (time.monotonic() - trabajo.comienzo_monotono)
    forma = trabajos.detener_proceso(trabajo)
    capturas = _capturas_desde(momento_disco)
    provisionales = ([p.name for p in CAPTURAS_F1.glob(".captura_en_curso_*.f1raw")]
                     if CAPTURAS_F1.is_dir() else [])

    resumen = trabajo.a_dict()
    resumen["cierre"] = forma
    resumen["capturas"] = capturas
    resumen["capturas_cerradas"] = len(capturas)
    resumen["mensajes_publicados"] = sum(c.get("mensajes_publicados") or 0
                                         for c in capturas)
    resumen["provisionales_sin_cerrar"] = provisionales
    if provisionales:
        resumen["advertencia"] = (
            "Quedaron capturas sin cerrar. Se detuvo mientras el juego seguia "
            "emitiendo: el archivo crudo esta en disco pero sin metadatos, "
            "porque la procedencia se escribe al terminar la sesion.")
    return resumen


# --------------------------------------------------------------------------- #
# Importacion OpenF1
# --------------------------------------------------------------------------- #


class PeticionOpenF1(BaseModel):
    """Una sesion OpenF1 a importar, identificada como la identifica el proveedor."""

    session_key: int
    descargar_telemetria: bool = False


def _paquete_openf1(session_key: int) -> Path:
    """Ubica el directorio del paquete de una sesion, o dice que no esta."""

    for candidato in sorted(PAQUETES_OPENF1.glob(f"*/{session_key}")):
        if candidato.is_dir():
            return candidato
    raise HTTPException(
        status_code=404,
        detail=(f"No hay paquete descargado para la sesion {session_key} en "
                f"{PAQUETES_OPENF1}. Descargarlo antes de importarlo."),
    )


@router.post("/openf1/importar")
def openf1_importar(peticion: PeticionOpenF1) -> dict:
    """Importa el contexto de una sesion OpenF1 ya descargada, por `session_key`.

    Llama a `import_validated_package`, que es exactamente lo que corre
    `scripts/import_session_package.py`: valida el paquete, registra la corrida de
    procesamiento y persiste el contexto disponible declarando lo que falta.

    Con `descargar_telemetria` se completa antes la telemetria faltante usando las
    funciones de `scripts/download_openf1_session_telemetry.py`. Es larga por
    decision del proveedor ---treinta consultas por minuto--- y por eso, mas que
    ninguna otra, tiene que correr como trabajo y no dentro de la peticion.
    """

    paquete = _paquete_openf1(peticion.session_key)

    def _trabajo() -> dict:
        from backend.session_processor import import_validated_package  # noqa: PLC0415

        resultado: dict[str, Any] = {"paquete": str(paquete),
                                     "session_key": peticion.session_key}
        if peticion.descargar_telemetria:
            from scripts import download_openf1_session_telemetry as descargador  # noqa: PLC0415

            plan = descargador.plan_downloads(paquete)
            descarga = descargador.execute_downloads(paquete, plan)
            manifiesto = descargador.write_manifest(paquete, descarga, "download")
            resultado["descarga"] = {
                clave: descarga.get(clave, 0)
                for clave in ("cached", "missing", "downloaded", "errors")}
            resultado["manifiesto"] = str(manifiesto)

        importacion = import_validated_package(paquete)
        # La corrida trae objetos de base ---fechas, sobre todo--- que no siempre
        # son serializables tal cual. Se pasan por el mismo codificador que usa
        # el guion de consola.
        resultado["importacion"] = json.loads(
            json.dumps(importacion, default=str, sort_keys=True))
        return resultado

    trabajo = trabajos.lanzar_funcion(
        "openf1_importar",
        f"importacion OpenF1 de la sesion {peticion.session_key}", _trabajo)
    respuesta = trabajo.a_dict()
    respuesta["session_key"] = peticion.session_key
    respuesta["paquete"] = str(paquete)
    return respuesta


# --------------------------------------------------------------------------- #
# Importacion CAN
# --------------------------------------------------------------------------- #


class PeticionCan(BaseModel):
    """Que segmentos de bus vehicular traer, y hasta donde.

    Las dos etapas estan separadas porque son dos cosas distintas:

    - `extraer` convierte el registro de openpilot al formato propio del
      proyecto. Escribe en disco y no toca la base.
    - `cargar` inserta lo ya extraido por el camino de validacion del consumidor.
      Es la que llega a la base.
    """

    segmentos: list[str] = Field(default_factory=list)
    plataforma: str = "TOYOTA_RAV4_TSS2"
    etapa: str = "extraer"


@router.post("/can/importar")
def can_importar(peticion: PeticionCan) -> dict:
    """Dispara la extraccion o la carga de segmentos de captura CAN.

    Se lanza como proceso aparte a proposito. La extraccion es **el unico lugar
    del proyecto que depende de openpilot**: 1,8 GB de biblioteca y dos rutas
    agregadas al camino de importacion. Meter eso dentro del servidor web ataria
    el arranque de toda la API a una dependencia que hace falta una vez por
    segmento y nunca mas.
    """

    if peticion.etapa not in {"extraer", "cargar"}:
        raise HTTPException(
            status_code=400,
            detail=("`etapa` debe ser 'extraer' (al formato propio) o 'cargar' "
                    "(a la base)."))
    if not peticion.segmentos:
        raise HTTPException(
            status_code=400,
            detail=("Hay que nombrar al menos un segmento. Sin lista, los guiones "
                    "toman un conjunto por omision, y una importacion disparada "
                    "desde un boton no deberia decidir sola cuanto trae."))

    if peticion.etapa == "extraer":
        comando = [sys.executable, str(RAIZ / "scripts" / "extraer_can.py"),
                   "--plataforma", peticion.plataforma,
                   "--segmentos", *peticion.segmentos]
        tipo = "can_extraer"
    else:
        faltantes = [
            s for s in peticion.segmentos
            if not (CAPTURAS_CAN / f"{peticion.plataforma}_{s}.canraw").is_file()]
        if faltantes:
            raise HTTPException(
                status_code=409,
                detail={"mensaje": "Hay segmentos que todavia no estan extraidos.",
                        "faltantes": faltantes,
                        "como_resolver": "Correr antes la etapa 'extraer'."})
        comando = [sys.executable, str(RAIZ / "scripts" / "reproducir_can.py"),
                   "--segmentos", *peticion.segmentos]
        tipo = "can_cargar"

    trabajo = trabajos.lanzar_proceso(
        tipo, f"{peticion.etapa} CAN: {', '.join(peticion.segmentos)}", comando)
    if trabajo.estado == "fallido":
        raise HTTPException(status_code=500, detail=trabajo.error)
    respuesta = trabajo.a_dict()
    respuesta["etapa"] = peticion.etapa
    respuesta["plataforma"] = peticion.plataforma
    respuesta["segmentos"] = peticion.segmentos
    return respuesta


# --------------------------------------------------------------------------- #
# Borrado de una sesion
# --------------------------------------------------------------------------- #


def _asentar_borrado(registro: dict) -> dict:
    """Deja una linea del borrado en la bitacora destructiva."""

    try:
        BITACORAS.mkdir(parents=True, exist_ok=True)
        with REGISTRO_DESTRUCTIVO.open("a", encoding="utf-8") as archivo:
            archivo.write(json.dumps(registro, ensure_ascii=False, sort_keys=True) + "\n")
        return {"escrito": True, "ruta": str(REGISTRO_DESTRUCTIVO)}
    except OSError as error:
        # No se oculta: un borrado que no pudo asentarse es un borrado que nadie
        # va a poder explicar despues, y quien lo pidio tiene que enterarse.
        return {"escrito": False, "ruta": str(REGISTRO_DESTRUCTIVO),
                "motivo": f"{type(error).__name__}: {error}"}


@router.delete("/sesion/{session_id}")
def borrar_sesion(
    session_id: str,
    confirmar: bool = False,
    fuente: str | None = None,
) -> dict:
    """Borra de la base la telemetria de una sesion. Exige confirmacion explicita.

    Sin `confirmar=true` **no toca nada**: cuenta lo que se llevaria y devuelve
    ese numero. Que la primera llamada no borre es deliberado. El borrado no se
    deshace desde la base ---se repone reproduciendo el registro crudo, que
    existe para F1 25 y para CAN y no para el contexto OpenF1 ya normalizado---
    de modo que quien aprieta el boton tiene que poder ver el tamano de lo que va
    a perder antes de perderlo.

    **Alcance.** Se borran filas de `telemetry_messages` y nada mas. Las tablas de
    contexto de una sesion historica ---vueltas, stints, clima, analisis
    generados--- no se tocan: son de otra naturaleza, no se reponen reproduciendo
    un crudo, y ninguna de ellas es lo que llena el disco.

    Todo borrado queda asentado en `logs/ingesta_destructiva.jsonl` con que se
    borro, cuantas filas y cuando.
    """

    global _CACHE_ESTADO

    comienzo = time.monotonic()
    try:
        with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
            if fuente is None:
                cursor.execute(
                    """select count(*), count(distinct signal_name),
                              count(distinct source_type)
                       from telemetry_messages where session_id = %s""",
                    (session_id,))
            else:
                cursor.execute(
                    """select count(*), count(distinct signal_name),
                              count(distinct source_type)
                       from telemetry_messages
                       where session_id = %s and source_type = %s""",
                    (session_id, fuente))
            filas, senales, fuentes = cursor.fetchone()
    except Exception as error:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail=(f"No se pudo consultar la base antes de borrar: "
                    f"{type(error).__name__}: {error}")) from error

    if not filas:
        raise HTTPException(
            status_code=404,
            detail=(f"La sesion {session_id!r} no tiene filas persistidas"
                    + (f" para la fuente {fuente!r}." if fuente else ".")))

    if not confirmar:
        raise HTTPException(
            status_code=409,
            detail={
                "mensaje": "Borrado no confirmado. No se toco nada.",
                "session_id": session_id,
                "fuente": fuente,
                "filas_a_borrar": filas,
                "senales": senales,
                "fuentes_alcanzadas": fuentes,
                "como_confirmar": f"DELETE /sesion/{session_id}?confirmar=true",
                "irreversible": True,
            },
        )

    try:
        with db.obtener_conexion() as conexion, conexion.cursor() as cursor:
            if fuente is None:
                cursor.execute("delete from telemetry_messages where session_id = %s",
                               (session_id,))
            else:
                cursor.execute(
                    "delete from telemetry_messages "
                    "where session_id = %s and source_type = %s",
                    (session_id, fuente))
            borradas = cursor.rowcount
            conexion.commit()
    except Exception as error:  # noqa: BLE001
        # Un fallo aca es informacion y no ruido: sobre una hipertabla comprimida
        # el borrado puede rechazarse fragmento por fragmento, y eso hay que
        # decirlo con su motivo en vez de devolver un 500 mudo. El intento queda
        # asentado igual, porque un borrado que fallo a la mitad tambien es un
        # borrado que hay que poder rastrear.
        fallo = {"momento_utc": _ahora_utc(), "operacion": "borrar_sesion",
                 "session_id": session_id, "fuente": fuente,
                 "filas_esperadas": filas, "borradas": None,
                 "error": f"{type(error).__name__}: {error}"}
        _asentar_borrado(fallo)
        raise HTTPException(status_code=500, detail=fallo) from error

    registro = {
        "momento_utc": _ahora_utc(),
        "operacion": "borrar_sesion",
        "session_id": session_id,
        "fuente": fuente,
        "filas_esperadas": filas,
        "borradas": borradas,
        "senales": senales,
        "duracion_s": round(time.monotonic() - comienzo, 2),
    }
    asentado = _asentar_borrado(registro)

    # El estado guardado quedo describiendo filas que ya no existen.
    _CACHE_ESTADO = None

    # Y el catalogo tambien. Sin esto, la sesion recien borrada seguiria
    # figurando en la lista con sus millones de filas: alguien la elegiria y
    # todo llegaria vacio, sin explicacion. `refrescar_sesion` la quita del
    # catalogo al no encontrarle ninguna fila.
    #
    # Va sincronico y no por detras, a diferencia del refresco tras una carga:
    # cuesta menos de medio segundo, el borrado ya es una accion deliberada y
    # confirmada, y quien la pidio tiene que poder ver el resultado sin que la
    # lista mienta un rato.
    try:
        catalogo_sesiones.refrescar_sesion(session_id)
    except Exception:  # noqa: BLE001 - el dato ya se borro; el catalogo se rehace
        pass

    return {
        **registro,
        # Se concilia contra lo que debia quedar y no contra la ausencia de
        # error: si se borraron menos filas que las contadas, algo entro entre el
        # conteo y el borrado, o algo no se pudo borrar.
        "conciliado": borradas == filas,
        "registro": asentado,
    }
