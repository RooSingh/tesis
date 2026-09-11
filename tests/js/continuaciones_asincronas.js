/* Las continuaciones que escriben el estado, con respuestas controladas.
 *
 * CRITERIO. Comprobar que `nuevaSesionEnCurso` devuelve numeros distintos
 * demuestra que la aritmetica del contador funciona, no que una respuesta
 * atrasada no pise la sesion vigente. Lo que puede romperse es la
 * **continuacion**: el `.then` que corre cuando la consulta vuelve, minutos
 * despues, con el tablero en otro estado.
 *
 * Asi que aca se extrae `asegurarVuelta` del `app.js` que se publica y se la
 * ejerce con un `pedir` de mentira cuyas respuestas se resuelven a mano, en el
 * orden que haga falta. Se comprueba el estado **despues** de resolverlas.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");

const APP = path.join(__dirname, "..", "..", "dashboard", "app.js");
const fuenteJs = fs.readFileSync(APP, "utf8");

function extraerDesde(marca, cierre) {
  let desde = fuenteJs.indexOf(marca);
  if (desde === -1) throw new Error("no esta en app.js: " + marca);
  /* `async function pedir(` empieza seis caracteres antes que `function`.
     Cortando por `function` a secas, el cuerpo pierde el `async` y sus `await`
     dejan de ser validos: la funcion extraida no seria la que se publica. */
  if (fuenteJs.slice(desde - 6, desde) === "async ") desde -= 6;
  let i = fuenteJs.indexOf("{", desde);
  let nivel = 0;
  for (; i < fuenteJs.length; i++) {
    if (fuenteJs[i] === "{") nivel++;
    else if (fuenteJs[i] === "}") {
      nivel--;
      if (nivel === 0) return fuenteJs.slice(desde, i + 1) + (cierre || "");
    }
  }
  throw new Error("no cierra: " + marca);
}
const fn = (nombre) => extraerDesde("function " + nombre + "(");

function constanteNumerica(nombre) {
  const m = fuenteJs.match(new RegExp("const\\s+" + nombre + "\\s*=\\s*(\\d+)\\s*;"));
  if (!m) throw new Error("no esta la constante " + nombre);
  return "const " + nombre + " = " + m[1] + ";";
}

/* Algunas constantes se calculan a partir de otras: se toma la declaracion
   entera y se la evalua aca, para que la prueba use **el mismo valor** que el
   tablero en vez de una copia que puede quedar vieja. */
function constanteCalculada(nombre) {
  const i = fuenteJs.indexOf("const " + nombre + " =");
  if (i === -1) throw new Error("no esta la constante " + nombre);
  const fin = fuenteJs.indexOf(";", i);
  return fuenteJs.slice(i, fin + 1);
}

/* ------------------------------------------------------------------
   El entorno. Todo lo que no se prueba queda mudo; `pedir` se controla.
   ------------------------------------------------------------------ */
const preludio = `
  let AUTOS = [];
  let seleccion = new Set(["car:1"]);
  let vueltaElegida = 1;
  let estadoSesion = "cargado";
  let alcanceComparacion = "vuelta";
  let velocidadRep = 1;
  let _mandoSesion = null;
  let _aperturaActual = 0;
  let _selloSeries = 0;
  let _selloDeLoArmado = -1;
  const _seriesArmadas = new Map();
  let _ultimaTraza = 0;
  const estado = { abierta: null, series: {}, pidiendo: {}, posiciones: {},
                   pidiendoPos: {}, disponibles: new Set(), vehiculoClave: "car:1",
                   vueltas: [], avisos: [], cargando: false, fallo: {} };
  function senalesCandidatas() { return ["speed", "throttle_position"]; }
  // El alcance de adquisicion/fase viaja en cada consulta; aca no se elige
  // ninguno, que es el comportamiento por omision. \`disponibles\` es una lista
  // vacia y no \`null\` a proposito: significa «ya se pregunto y no hay nada que
  // elegir», que es el estado en el que estas pruebas ocurren. Con \`null\`
  // ---todavia no se pregunto--- la compuerta no deja pedir nada, y eso se
  // comprueba aparte.
  const corrida = { adquisicion: null, fase: null, disponibles: [], mezclada: false };
  function sufijoDeCorrida() { return ""; }
  function armarAutos(ids) { AUTOS = ids.map(id => ({ id, propio: false, nombre: id })); }
  function avisar(texto, esError) { AVISOS.push({ texto, esError }); }
  function render() {}
  function pedirPintado() {}
  function dibujarTraza() {}
  function moverCabezalesGraficos() {}
  /* La vuelta sale del cabezal, como en el tablero: con un instante que
     devuelve siempre la vuelta elegida, mover el cabezal nunca produce un
     cambio de vuelta y la prueba comprobaria otra cosa. Sin vueltas
     declaradas se cae en la elegida, que es lo que hacen las pruebas que no
     las declaran. */
  function instante() {
    return { vuelta: (estado.vueltas && estado.vueltas.length)
      ? vueltaEnFraccion(cabezal) : vueltaElegida };
  }
  function compAbierta() { return false; }
  function vueltasParaComparar() { return [vueltaElegida]; }
  function requestAnimationFrame() { return 0; }
  function setInterval() { return 0; }
  function clearInterval() {}
  /* El pintado de cargas se extrae de verdad: comprobar la marca del vale y no
     el velo que enciende dejaria pasar una condicion escrita y neutralizada.
     Se le da un documento de mentira que anota que paneles quedaron
     encendidos. */
  const VELOS = {};
  globalThis.VELOS = VELOS;
  const document = {
    getElementById: () => null,
    querySelectorAll: (sel) => {
      if (sel === "[data-panel]") {
        return ["motor", "cronometraje", "trazado", "graficos"].map(nombre => ({
          dataset: { panel: nombre, set cargando(v) { VELOS[nombre] = v; },
                     get cargando() { return VELOS[nombre]; } },
        }));
      }
      return [{ dataset: { set cargando(v) { VELOS.graficos = v; },
                           get cargando() { return VELOS.graficos; } } }];
    },
  };
  /* Lo que la carga de datos toca y no se prueba aca. La carga corre de
     verdad: sustituirla por un ayudante que invalide bien seria comprobar el
     ayudante. */
  const TESTIGO = { cortes: { vigencia: 0, vueltasNulas: 0, excepcion: 0 },
                    ultimoCorte: null, aperturas: 0 };
  function asegurarPosiciones() {}
  function cuandoHayaGrafico(hacer) { hacer(); }
  function decirEstadoApi() {}
  function laEsencialTermino() {}
  function nombreDeSesion() { return "sesion"; }
  function pedirCurvas() {}
  function pedirTrazado() {}
  /* El control de carrera es otra consulta y otra lista: lo que este arnes
     persigue es que una respuesta atrasada no pise la sesion vigente, y esa
     ruta tiene la suya. Queda muda para no meter una segunda respuesta en un
     banco que resuelve las suyas a mano. */
  function pedirControlDeCarrera() {}
  /* La usa el aviso del hueco mayor de una vuelta cortada, dentro de la carga
     de sesion. Sin ella ese aviso lanzaba ReferenceError y el catch de la
     apertura lo anotaba como «apertura interrumpida»: la prueba pasaba igual y
     el fallo quedaba en la consola. Una excepcion que el arnes se traga es
     exactamente lo que esconde la proxima. */
  function cifra(v, d) { return Number(v).toFixed(d === undefined ? 1 : d); }
  function ubicarControlDeCarrera() {}
  function pintarClima() {}
  function pintarEsquinas() {}
  function pintarPuestaAPunto() {}
  function poblarVueltas() {}
  function anotarDisponibles() {}
  function olvidarCaches() { _instanteClave = null; }
  function pintarTitulo() {}
  function pintarTransporte() {}
  function pintarMedidores() {}
  function pintarG() {}
  function pintarPista() {}
  function pintarCronometraje() {}
  function pintarAvisos() {}
  function refrescarContexto() {}
  function dibujarComparacion() {}
  function instanteUtc() { return null; }
  let _ultimaComparacion = 0;
  let _ultimaVueltaDibujada = -1;
  let _relojPedidos = null;
  let cabezal = 0;
  let ventanaTraza = 1200;
  const performance = { now: () => Date.now() };
  function trazadoAPath() { return { path: "" }; }
  function ubicarAvisos() {}
  let PISTA = { path: "", curvas: [], largo_m: null };
  /* Y lo que hace falta para leer el reloj. */
  let fuente = "f1";
  const SENAL_DE = { speed: "speed", throttle: "throttle_position" };
  const SENAL_CAN = {}, SENAL_OPENF1 = {};
  let _selloDeLoTemporal = -1;
  const _temporales = new Map();
  let _instanteClave = null;
  let _vueltasEnPantalla = [];
  let _esperandoVuelta = null;
  const AVISOS_ESTADO = [];
  function decirEstadoApi(texto) { AVISOS_ESTADO.push(texto); }
  globalThis.AVISOS_ESTADO = AVISOS_ESTADO;
  function etiquetaDeCorrida() { return "Original · Carrera"; }
  const SESIONES = [];
  const API = "";
  /* Una peticion de red de mentira para el camino real de la consulta: no contesta
     nunca y solo se entera de que la abortaron. Con eso se puede ejercer el
     corte por tiempo de verdad ---el mismo controlador de aborto que usa el
     tablero--- sin esperar los treinta segundos del limite real. */
  function fetch(url, opciones) {
    return new Promise((_, rechazar) => {
      const senal = opciones && opciones.signal;
      const cortar = () => {
        const e = new Error("The operation was aborted.");
        e.name = "AbortError";
        rechazar(e);
      };
      if (senal) {
        if (senal.aborted) cortar();
        else senal.addEventListener("abort", cortar, { once: true });
      }
      FETCHS.push({ url: url, senal: senal });
    });
  }
`;

/* La consulta de mentira: registra y deja que la prueba resuelva cuando
   quiera. Es lo que usan casi todas; las del corte por tiempo usan la real. */
const PEDIR_DE_MENTIRA = `
  function pedir(ruta, opciones) {
    let resolver, rechazar;
    const p = new Promise((a, b) => { resolver = a; rechazar = b; });
    PEDIDOS.push({ ruta, opciones: opciones || {}, resolver, rechazar });
    return p;
  }
`;

const PIEZAS = [
  constanteNumerica("PUNTOS_POR_VUELTA"),
  constanteNumerica("PRESUPUESTO_DE_PUNTOS"),
  constanteNumerica("PUNTOS_MINIMOS_POR_VUELTA"),
  constanteNumerica("SERIES_A_LA_VEZ"),
  constanteNumerica("VUELTAS_EN_MEMORIA"),
  constanteCalculada("LIMITE_DE_DETALLE_PUNTOS"),
  constanteNumerica("LIMITE_ESPERA_MS"),
  "const _vales = new Map(); let _proximoVale = 0; let _relojVales = null;",
  constanteCalculada("PANELES_DE"),
  fn("conCarga"),
  fn("pintarCargas"),
  fn("vigilarVales"),
  fn("fueAnulada"),
  fn("nuevaSesionEnCurso"),
  fn("aperturaVigente"),
  fn("sigueVigente"),
  fn("senalDeSesion"),
  fn("cambiaronLasSeries"),
  fn("puntosGuardados"),
  fn("podarVueltas"),
  fn("puntosParaVueltas"),
  fn("enTandas"),
  fn("asegurarVuelta"),
  fn("tramoDeLaVuelta"),
  /* La compuerta que decide si se puede pedir historico. Se extrae de verdad y
     no se sustituye por un `true`: lo que estas pruebas miran es justamente
     cuando sale una consulta y cuando no. */
  /* La compuerta mira ademas si la fuente tiene eje de distancia: se extrae de
     verdad, con su tabla, porque una fuente sin ese eje no tiene que pedir. */
  constanteCalculada("EJE_DE_DISTANCIA_POR_FUENTE"),
  fn("hayEjeDeDistancia"),
  fn("porQueNoHayDistancia"),
  fn("adquisicionSeSolapa"),
  fn("alcanceEsAmbiguo"),
  fn("alcanceElegidoEsValido"),
  fn("alcanceResuelto"),
  fn("alcancePermitePedir"),
  fn("vueltaSiguienteDeclarada"),
  constanteNumerica("HORIZONTE_PRECARGA_S"),
  fn("vueltasParaPrecargar"),
  fn("precargarVueltas"),
  fn("anotarEnPantalla"),
  fn("moverCabezal"),
  fn("vueltaEnFraccion"),
  fn("faltaLoImprescindible"),
  fn("anotarEspera"),
  fn("soltarEspera"),
  fn("duracionSesionS"),
  fn("iniciosDeVuelta"),
  fn("duracionDeVuelta"),
  fn("hayVueltas"),
  /* El reloj, entero, para poder leerlo despues de cada continuacion. */
  constanteNumerica("HUECO_DE_CAPTURA_MS"),
  'const EJE_DISTANCIA = " distancia";',
  'const EJE_DISTANCIA_SESION = " distancia de sesion";',
  'const EJE_TIEMPO = " tiempo";',
  fn("numeroMedido"),
  fn("nombreDeSenal"),
  fn("claveVehiculoPropio"),
  fn("_cacheTemporal"),
  fn("serieTemporal"),
  fn("_serieTemporalCruda"),
  fn("continuidadDeVuelta"),
  fn("_umbralDeVuelta"),
  fn("tiempoEfectivoEntre"),
  fn("hayCorteEntre"),
  fn("_antesDe"),
  fn("relojDeVuelta"),
  fn("_tramosContinuos"),
  fn("_tramosDeMuestras"),
  fn("_armarRelojDeVuelta"),
  fn("tiempoDePresentacion"),
  /* Y la carga de verdad: es la que instala `estado.vueltas`. */
  fn("cargarDatosDeSesion"),
  /* Decide si la consulta de series sale acotada a un vehiculo o abierta. Va la
     de verdad y no un doble: lo que se comprueba es su efecto sobre la URL. */
  fn("faltanVehiculosPorAprender"),
];

const pedidos = [];
const avisos = [];
const capas = [];
const fetchs = [];

function nuevoBanco(opciones) {
  const o = opciones || {};
  globalThis.PEDIDOS = pedidos;
  globalThis.AVISOS = avisos;
  globalThis.CAPAS = capas;
  globalThis.FETCHS = fetchs;
  /* Con `pedirReal` se extraen `pedir` y `pedirCrudo` del `app.js` que se
     publica y se los deja correr contra el `fetch` de mentira: es la unica
     forma de ejercer el corte por tiempo tal como ocurre. El limite se acorta
     para no esperar treinta segundos en cada prueba. */
  const consulta = o.pedirReal ? [fn("pedir"), fn("pedirCrudo")] : [PEDIR_DE_MENTIRA];
  /* El limite real son treinta segundos. Con la consulta de verdad se lo
     acorta para no esperarlos en cada prueba; lo que se ejerce es el mismo
     camino, no otro. */
  const piezas = o.pedirReal
    ? PIEZAS.map(t => (t.indexOf("const LIMITE_ESPERA_MS") === 0
        ? "const LIMITE_ESPERA_MS = " + (o.limiteMs || 40) + ";" : t))
    : PIEZAS;
  const devolver = `return { estado, asegurarVuelta, nuevaSesionEnCurso,
                             /* Para poder poner el tablero en «ya aprendi
                                quienes son» y en «todavia no». */
                             fijarAutos: (ids) => { armarAutos(ids); },
                             cuantosAutos: () => AUTOS.length,
                             aperturaVigente, sigueVigente, puntosParaVueltas,
                             enTandas, podarVueltas,
                             fijarVuelta: (v) => { vueltaElegida = v; },
                             corrida, alcancePermitePedir, vueltaSiguienteDeclarada,
                             vueltasParaPrecargar,
                             conCarga, vales: () => [..._vales.values()],
                             faltaLoImprescindible, vueltaEnFraccion,
                             anotarEspera, soltarEspera,
                             espera: () => _esperandoVuelta,
                             fijarEnPantalla: (vs) => { _vueltasEnPantalla = vs; },
                             enPantalla: () => _vueltasEnPantalla,
                             anotarEnPantalla, limiteDeDetalle: () => LIMITE_DE_DETALLE_PUNTOS,
                             limpiarLoDeLaCorrida: () => { _vueltasEnPantalla = []; },
                             asegurarPosiciones, moverCabezal,
                             fijarVelocidad: (v) => { velocidadRep = v; },
                             fijarCabezal: (f) => { cabezal = f; },
                             leerCabezal: () => cabezal,
                             cargarDatosDeSesion, relojDeVuelta, tiempoDePresentacion,
                             leerVales: () => _vales.size,
                             hayEjeDeDistancia, porQueNoHayDistancia,
                             fijarFuente: (f) => { fuente = f; } };`;
  return new Function(preludio + "\n" + consulta.join("\n") + "\n" +
                      piezas.join("\n\n") + "\n" + devolver)();
}

let hechas = 0;
const pendientes = [];
function prueba(titulo, fn, opcionesBanco) {
  pendientes.push(async () => {
    pedidos.length = 0; avisos.length = 0; capas.length = 0; fetchs.length = 0;
    try {
      await fn(nuevoBanco(opcionesBanco));
      hechas++;
    } catch (error) {
      console.error("FALLO: " + titulo);
      console.error("  " + (error && error.stack ? error.stack : error));
      process.exitCode = 1;
    }
  });
}

/* Deja correr las continuaciones pendientes de las promesas ya resueltas. */
const asentar = () => new Promise(r => setTimeout(r, 0));

/* Una respuesta con la forma que devuelve /series. */
function respuesta(vehiculo, puntos, marca) {
  return {
    vehiculos: { [vehiculo]: {
      distancia_m: [0, 100, 200],
      speed: [marca, marca + 1, marca + 2],
      throttle_position: [1, 2, 3],
    } },
    puntos_pedidos: puntos || 300,
    submuestreado: false,
  };
}

/* ==================================================================
   A -> B -> A con respuestas controladas
   ================================================================== */
prueba("una respuesta de la primera A no escribe sobre la segunda A", async (b) => {
  b.estado.abierta = { session_id: "A" };
  const aperturaA1 = b.nuevaSesionEnCurso();
  b.asegurarVuelta(3);
  const deA1 = pedidos.slice();
  assert.ok(deA1.length, "no se pidio nada");

  // Se pasa a B y se vuelve a A. La misma sesion, dos aperturas.
  b.estado.abierta = { session_id: "B" };
  b.nuevaSesionEnCurso();
  b.estado.abierta = { session_id: "A" };
  const aperturaA2 = b.nuevaSesionEnCurso();
  assert.notStrictEqual(aperturaA1, aperturaA2);

  // Recien ahora contesta la consulta de la PRIMERA A.
  deA1.forEach(p => p.resolver(respuesta("car:1", 300, 999)));
  await asentar();

  assert.strictEqual(b.estado.series[3], undefined,
    "la respuesta de la apertura vieja escribio las series de la nueva");
});

prueba("mientras falte aprender quienes son, la consulta no se acota", async (b) => {
  /* EL DEFECTO. La consulta salia acotada al vehiculo propio en cuanto se sabia
     cual era, y en OpenF1 se sabe desde el principio ---`/vueltas` declara el
     mas muestreado---. De modo que las otras dos telemetrias de la sesion no
     aparecian nunca: para poder ofrecerlas en la lista primero hay que saber
     que existen, y para saberlo hay que pedirlas al menos una vez.

     El catalogo dice cuantas hay. Mientras lo aprendido sea menos, se pide
     abierto y la respuesta ensena el resto. */
  b.estado.abierta = { session_id: "A", vehiculos: 3 };
  b.estado.vehiculoClave = "car:1";
  b.fijarAutos(["car:1"]);
  b.nuevaSesionEnCurso();
  b.asegurarVuelta(3);
  const rutas = PEDIDOS.map(p => p.ruta);
  assert.ok(rutas.length > 0, "no salio ninguna consulta");
  assert.ok(rutas.every(r => r.indexOf("vehiculos=") === -1),
    "la consulta salio acotada antes de conocer a los tres: " + rutas[0]);
});

prueba("una vez aprendidos, la consulta vuelve a acotarse", async (b) => {
  /* Lo abierto es para aprender, no un modo de trabajo: con los tres conocidos,
     pedir los tres en cada vuelta seria triplicar cada respuesta para dibujar
     uno. */
  b.estado.abierta = { session_id: "A", vehiculos: 3 };
  b.estado.vehiculoClave = "car:1";
  b.fijarAutos(["car:1", "car:4", "car:81"]);
  b.nuevaSesionEnCurso();
  b.asegurarVuelta(3);
  const rutas = PEDIDOS.map(p => p.ruta);
  assert.ok(rutas.length > 0, "no salio ninguna consulta");
  assert.ok(rutas.every(r => r.indexOf("vehiculos=") !== -1),
    "la consulta siguio abierta con los tres ya conocidos: " + rutas[0]);
});

prueba("con un solo vehiculo declarado nada cambia", async (b) => {
  /* La simulacion y el bus declaran uno: los rivales de F1 25 viajan por
     `/posiciones` y no por telemetria. Ahi la consulta se acota como siempre. */
  b.estado.abierta = { session_id: "A", vehiculos: 1 };
  b.estado.vehiculoClave = "car:1";
  b.fijarAutos([]);
  b.nuevaSesionEnCurso();
  b.asegurarVuelta(3);
  const rutas = PEDIDOS.map(p => p.ruta);
  assert.ok(rutas.every(r => r.indexOf("vehiculos=") !== -1),
    "se abrio la consulta sobre una sesion de un solo vehiculo: " + rutas[0]);
});

prueba("la respuesta de la apertura vigente si se aplica", async (b) => {
  b.estado.abierta = { session_id: "A" };
  b.nuevaSesionEnCurso();
  b.asegurarVuelta(3);
  pedidos.forEach(p => p.resolver(respuesta("car:1", 300, 10)));
  await asentar();
  assert.ok(b.estado.series[3], "no se guardo la vuelta de la apertura vigente");
  assert.deepStrictEqual(b.estado.series[3].vehiculos["car:1"].speed, [10, 11, 12]);
});

prueba("una consulta anulada no avisa de un error que no hubo", async (b) => {
  b.estado.abierta = { session_id: "A" };
  b.nuevaSesionEnCurso();
  b.asegurarVuelta(4);
  const err = new Error("The operation was aborted.");
  err.name = "AbortError";
  pedidos.forEach(p => p.rechazar(err));
  await asentar();
  assert.strictEqual(avisos.length, 0,
    "una anulacion se reporto como fallo: " + JSON.stringify(avisos));
});

prueba("un fallo de verdad si se declara", async (b) => {
  b.estado.abierta = { session_id: "A" };
  b.nuevaSesionEnCurso();
  b.asegurarVuelta(4);
  pedidos.forEach(p => p.rechazar(new Error("la base no contesta")));
  await asentar();
  assert.strictEqual(avisos.length, 1);
  assert.ok(avisos[0].texto.indexOf("la base no contesta") !== -1);
});

/* ==================================================================
   La marca de "se esta pidiendo" y las esperas
   ================================================================== */
prueba("una peticion vieja no borra la marca de la nueva", async (b) => {
  b.estado.abierta = { session_id: "A" };
  b.nuevaSesionEnCurso();
  b.asegurarVuelta(7);
  const vieja = pedidos.slice();

  // Se cierra la sesion y se abre otra; la vuelta 7 se pide de nuevo.
  b.nuevaSesionEnCurso();
  delete b.estado.pidiendo[7];
  pedidos.length = 0;
  b.asegurarVuelta(7);
  const nueva = pedidos.slice();
  const marcaNueva = b.estado.pidiendo[7];
  assert.ok(marcaNueva, "no quedo marca de la peticion nueva");

  // Ahora contesta la vieja, tarde.
  vieja.forEach(p => p.resolver(respuesta("car:1", 300, 1)));
  await asentar();
  assert.strictEqual(b.estado.pidiendo[7], marcaNueva,
    "la peticion vieja borro la marca de la nueva");

  nueva.forEach(p => p.resolver(respuesta("car:1", 300, 2)));
  await asentar();
  assert.strictEqual(b.estado.pidiendo[7], undefined,
    "la peticion nueva no limpio su propia marca");
});

prueba("ninguna espera queda colgada, ni al fallar ni al anularse", async (b) => {
  b.estado.abierta = { session_id: "A" };
  b.nuevaSesionEnCurso();
  b.asegurarVuelta(2);
  assert.ok(b.leerVales() > 0, "no se marco la espera");
  const err = new Error("abortada"); err.name = "AbortError";
  pedidos.forEach(p => p.rechazar(err));
  await asentar();
  assert.strictEqual(b.leerVales(), 0,
    "quedo un panel diciendo que espera algo que ya no espera");
});

prueba("las series reciben la señal de cancelacion de la sesion", async (b) => {
  b.estado.abierta = { session_id: "A" };
  b.nuevaSesionEnCurso();
  b.asegurarVuelta(5);
  assert.ok(pedidos.length, "no se pidio nada");
  pedidos.forEach(p => {
    assert.ok(p.opciones.senal, "una consulta de series salio sin señal: " + p.ruta);
  });
  // Y esa señal se dispara al cambiar de sesion.
  const senal = pedidos[0].opciones.senal;
  assert.strictEqual(senal.aborted, false);
  b.nuevaSesionEnCurso();
  assert.strictEqual(senal.aborted, true, "cambiar de sesion no anulo lo anterior");
});

/* ==================================================================
   Resolucion: lo grueso no se hace pasar por lo fino
   ================================================================== */
prueba("una vuelta guardada con menos puntos se vuelve a pedir", async (b) => {
  b.estado.abierta = { session_id: "A" };
  b.nuevaSesionEnCurso();
  b.asegurarVuelta(9, 109);                       // resolucion de carrera
  pedidos.forEach(p => p.resolver(respuesta("car:1", 109, 1)));
  await asentar();
  assert.strictEqual(b.estado.series[9].puntos_pedidos, 109);

  pedidos.length = 0;
  b.asegurarVuelta(9, 300);                       // ahora se quiere el detalle
  assert.ok(pedidos.length, "se reuso una copia mas gruesa como si fuera la fina");
  assert.ok(pedidos[0].ruta.indexOf("puntos=300") !== -1, pedidos[0].ruta);
  pedidos.forEach(p => p.resolver(respuesta("car:1", 300, 5)));
  await asentar();
  assert.strictEqual(b.estado.series[9].puntos_pedidos, 300);
});

prueba("con el detalle ya cargado no se vuelve a pedir la version gruesa", async (b) => {
  b.estado.abierta = { session_id: "A" };
  b.nuevaSesionEnCurso();
  b.asegurarVuelta(9, 300);
  pedidos.forEach(p => p.resolver(respuesta("car:1", 300, 1)));
  await asentar();
  pedidos.length = 0;
  b.asegurarVuelta(9, 109);
  assert.strictEqual(pedidos.length, 0, "se volvio a pedir lo que ya estaba mejor");
});

/* ==================================================================
   Concurrencia acotada
   ================================================================== */
prueba("enTandas no pone mas de N en vuelo a la vez", async (b) => {
  let vivas = 0, maximo = 0;
  const sueltas = [];
  const p = b.enTandas([1, 2, 3, 4, 5, 6, 7, 8], 3, (x) => {
    vivas++; maximo = Math.max(maximo, vivas);
    return new Promise(r => sueltas.push(() => { vivas--; r(x); }));
  });
  await asentar();
  assert.strictEqual(maximo, 3, "hubo " + maximo + " consultas en vuelo");
  while (sueltas.length) { sueltas.shift()(); await asentar(); }
  const salida = await p;
  assert.deepStrictEqual(salida, [1, 2, 3, 4, 5, 6, 7, 8],
    "el resultado tiene que conservar el orden de entrada");
});

/* ==================================================================
   El presupuesto de la carrera es un limite, no una aspiracion
   ================================================================== */
prueba("la resolucion objetivo nunca supera el presupuesto", async (b) => {
  /* `Math.max(60, floor(2400 / vueltas))` no acotaba: el piso le ganaba a la
     division y el total se disparaba. Con 100 vueltas daba 6.000 puntos para
     un presupuesto declarado de 2.400. */
  [2, 8, 22, 40, 60, 78, 100, 120].forEach(n => {
    const porVuelta = b.puntosParaVueltas(n);
    assert.ok(porVuelta >= 20, n + " vueltas dieron " + porVuelta + " puntos");
    assert.ok(n * porVuelta <= 2400,
      n + " vueltas x " + porVuelta + " puntos = " + (n * porVuelta) + ", sobre 2400");
  });
});

prueba("una vuelta sola conserva toda su resolucion", async (b) => {
  assert.strictEqual(b.puntosParaVueltas(1), 300);
});

prueba("el piso solo le gana al presupuesto por encima de 120 vueltas", async (b) => {
  // Es el limite declarado, y ninguna carrera de F1 lo alcanza: el maximo
  // historico son 78 vueltas.
  assert.ok(120 * b.puntosParaVueltas(120) <= 2400);
  assert.ok(200 * b.puntosParaVueltas(200) > 2400,
    "por encima del limite el piso manda, y eso hay que poder afirmarlo");
});

prueba("abrir la carrera despues de recorrer vueltas en detalle no crece sin fin", async (b) => {
  b.estado.abierta = { session_id: "A" };
  b.nuevaSesionEnCurso();
  // Veinte vueltas visitadas de a una, a resolucion completa.
  for (let v = 1; v <= 20; v++) {
    b.fijarVuelta(v);
    b.asegurarVuelta(v, 300);
    pedidos.forEach(p => p.resolver(respuesta("car:1", 300, v)));
    pedidos.length = 0;
    await asentar();
  }
  const guardadas = Object.keys(b.estado.series).length;
  assert.ok(guardadas * 300 <= 2400 + 300 * 4,
    "quedaron " + guardadas + " vueltas de 300 puntos = " + (guardadas * 300));
});

prueba("la carrera completa entra sin desalojar lo que acaba de llegar", async (b) => {
  b.estado.abierta = { session_id: "A" };
  b.nuevaSesionEnCurso();
  const VUELTAS = 22;
  const puntos = b.puntosParaVueltas(VUELTAS);
  for (let v = 1; v <= VUELTAS; v++) {
    b.asegurarVuelta(v, puntos);
    pedidos.forEach(p => p.resolver(respuesta("car:1", puntos, v)));
    pedidos.length = 0;
    await asentar();
  }
  const cargadas = Object.keys(b.estado.series).map(Number).sort((a, c) => a - c);
  assert.strictEqual(cargadas.length, VUELTAS,
    "la carrera no entera: quedaron " + cargadas.length + " de " + VUELTAS);
  // Y no hay ciclo: pedirlas otra vez no dispara ninguna consulta.
  pedidos.length = 0;
  for (let v = 1; v <= VUELTAS; v++) b.asegurarVuelta(v, puntos);
  assert.strictEqual(pedidos.length, 0,
    "se volvieron a pedir " + pedidos.length + " vueltas que ya estaban");
});

prueba("una carrera de 60 vueltas tambien entra entera", async (b) => {
  b.estado.abierta = { session_id: "A" };
  b.nuevaSesionEnCurso();
  const VUELTAS = 60;
  const puntos = b.puntosParaVueltas(VUELTAS);
  for (let v = 1; v <= VUELTAS; v++) {
    b.asegurarVuelta(v, puntos);
    pedidos.forEach(p => p.resolver(respuesta("car:1", puntos, v)));
    pedidos.length = 0;
    await asentar();
  }
  assert.strictEqual(Object.keys(b.estado.series).length, VUELTAS);
  assert.ok(VUELTAS * puntos <= 2400);
});

prueba("una carrera de 100 vueltas tambien, y sigue dentro del limite", async (b) => {
  b.estado.abierta = { session_id: "A" };
  b.nuevaSesionEnCurso();
  const VUELTAS = 100;
  const puntos = b.puntosParaVueltas(VUELTAS);
  for (let v = 1; v <= VUELTAS; v++) {
    b.asegurarVuelta(v, puntos);
    pedidos.forEach(p => p.resolver(respuesta("car:1", puntos, v)));
    pedidos.length = 0;
    await asentar();
  }
  assert.strictEqual(Object.keys(b.estado.series).length, VUELTAS);
  assert.ok(VUELTAS * puntos <= 2400, VUELTAS * puntos + " puntos");
});

prueba("las posiciones se podan aparte y no las protege la comparacion", async (b) => {
  b.estado.abierta = { session_id: "A" };
  b.fijarVuelta(1);
  for (let v = 1; v <= 30; v++) b.estado.posiciones[v] = { vehiculos: {} };
  b.podarVueltas();
  const quedan = Object.keys(b.estado.posiciones).length;
  assert.ok(quedan <= 8, "quedaron " + quedan + " vueltas de posiciones");
  assert.ok(b.estado.posiciones[1], "se podo la vuelta que se esta mirando");
});

prueba("no sale una consulta con el alcance sin resolver", async (b) => {
  /* EL CASO REAL, QUE ES DE ORDEN DE LLEGADA. El transporte pide la vuelta que
     hay bajo el cabezal con 200 ms de retardo desde que arranca la pagina, y
     `/adquisiciones` tarda mas: medido en Spa, la vuelta 1 se pedia a los
     582 ms y las adquisiciones llegaban a los 953. La consulta salia con la
     mezcla de etapas aunque el elector estuviera abierto esperando.

     `disponibles = null` es «todavia no se pregunto». */
  b.estado.abierta = { session_id: "A" };
  b.corrida.disponibles = null;
  /* Sin `await`: si la compuerta dejara pasar, la consulta de mentira devuelve
     una promesa que nadie resuelve y esperarla colgaria la prueba en vez de
     hacerla fallar. Se deja asentar la cola y se mira si salio algo. */
  b.asegurarVuelta(1);
  await asentar();
  assert.strictEqual(PEDIDOS.length, 0,
    "se pidio la vuelta antes de saber que se esta mirando");

  /* Llegan las adquisiciones y hay que elegir etapa: sigue sin pedirse. */
  b.corrida.disponibles = [{ clave: "original", fases: [
    { orden: 1, reloj_del_juego_reinicia_al_entrar: false },
    { orden: 3, reloj_del_juego_reinicia_al_entrar: true }] }];
  b.asegurarVuelta(1);
  await asentar();
  assert.strictEqual(PEDIDOS.length, 0, "se pidio con la etapa sin elegir");

  /* Elegida la etapa, la consulta sale. */
  b.corrida.adquisicion = "original";
  b.corrida.fase = 3;
  b.asegurarVuelta(1);
  await asentar();
  assert.ok(PEDIDOS.length > 0, "no se pide ni con el alcance completo");
});

/* ==================================================================
   `/vueltas` llega despues que las series
   ================================================================== */

/* La captura del fixture de `tiempo_de_presentacion.js`: 4.000 muestras cada
   50 ms con un corte de 2,05 s entre los 99.950 y los 102.000, reducida a la
   resolucion que se pida. Aca se la usa para leer el reloj, no para probar la
   interpolacion. */
const T0 = Date.parse("2026-09-05T00:38:00.000Z");
function capturaConCorte(puntos) {
  const marcas = [], dist = [];
  let t = 0, d = 0;
  for (let i = 0; i < 4000; i++) {
    if (i === 2000) t += 2050; else if (i) t += 50;
    marcas.push(t); dist.push(d); d += 2.5;
  }
  const paso = Math.max(1, Math.ceil(marcas.length / puntos));
  const mT = [], mD = [];
  for (let i = 0; i < marcas.length; i += paso) { mT.push(marcas[i]); mD.push(dist[i]); }
  if (mT[mT.length - 1] !== marcas[marcas.length - 1]) {
    mT.push(marcas[marcas.length - 1]); mD.push(dist[dist.length - 1]);
  }
  return { marcas: mT, dist: mD, corte: [marcas[1999], marcas[2000]],
           efectivo: marcas[marcas.length - 1] - marcas[0] - 2050,
           bruto: marcas[marcas.length - 1] - marcas[0] };
}

const iso = (ms) => new Date(T0 + ms).toISOString();

function serieDelFixture(vehiculo, c) {
  return { vehiculos: { [vehiculo]: {
             distancia_m: c.dist,
             timestamp_utc: c.marcas.map(m => iso(m)),
             speed: c.dist.map(() => 200),
             throttle_position: c.dist.map(() => 50),
           } },
           puntos_pedidos: 300, submuestreado: true, muestras_originales: 4000 };
}

function vueltasDelFixture(vehiculo, c) {
  return { vehiculo: vehiculo, vueltas: [{
    numero: 1, duracion_s: c.efectivo / 1000, duracion_bruta_s: c.bruto / 1000,
    hueco_mayor_s: 2.05, continua: false,
    huecos: [{ desde_utc: iso(c.corte[0]), hasta_utc: iso(c.corte[1]), duracion_s: 2.05 }],
    desde_utc: iso(0), hasta_utc: iso(c.bruto),
  }] };
}

/* Deja el alcance resuelto: sin eso la compuerta no deja pedir nada. */
function conAlcance(b) {
  b.estado.abierta = { session_id: "A" };
  b.corrida.disponibles = [{ clave: "original", fases: [
    { orden: 1, reloj_del_juego_reinicia_al_entrar: false },
    { orden: 3, reloj_del_juego_reinicia_al_entrar: true }] }];
  b.corrida.adquisicion = "original";
  b.corrida.fase = 3;
}

const deRuta = (r) => (PEDIDOS.find(p => p.ruta.indexOf("/" + r) !== -1));

prueba("las vueltas que llegan tarde reemplazan al reloj provisional", async (b) => {
  /* EL DEFECTO. Con el alcance ya elegido, el transporte pide la vuelta bajo el
     cabezal por su cuenta. Si `/series` contesta antes que `/vueltas`, el
     primer render arma un reloj **provisional**: sin la ventana ni los cortes
     autoritativos, apoyado en los extremos de la serie submuestreada y con un
     umbral deducido. Al llegar `/vueltas`, `cargarDatosDeSesion` instalaba
     `estado.vueltas` y el vehiculo propio y no invalidaba las vistas
     temporales, de modo que ese reloj provisional se seguia usando: mismo
     numero de vuelta y mismo vehiculo, misma clave de cache. */
  const c = capturaConCorte(300);
  conAlcance(b);

  // 1. Arranca la carga: `/vueltas` sale y queda pendiente.
  b.cargarDatosDeSesion("/sesiones/A", b.aperturaVigente(), "s", { session_id: "A" });
  await asentar();
  assert.ok(deRuta("vueltas"), "no salio la consulta de vueltas");

  // 2. El transporte pide la vuelta 1 y su respuesta llega primero.
  b.asegurarVuelta(1);
  await asentar();
  const series = deRuta("series");
  assert.ok(series, "no salio la consulta de series");
  series.resolver(serieDelFixture("car:1", c));
  await asentar();

  // 3. Alguien lee el reloj: queda guardado el provisional.
  const provisional = b.relojDeVuelta(1);
  assert.ok(provisional, "no hay reloj con las series ya cargadas");
  assert.strictEqual(provisional.aproximado, true,
    "sin las vueltas, el reloj no puede declararse medido");

  // 4. Llega `/vueltas`, con la ventana y el corte autoritativos.
  deRuta("vueltas").resolver(vueltasDelFixture("car:1", c));
  await asentar();

  // 5. Se vuelve a leer, sin recargar, sin mover el cabezal y sin otra serie.
  const definitivo = b.relojDeVuelta(1);
  assert.strictEqual(definitivo.aproximado, false,
    "se sigue usando el reloj provisional despues de llegar las vueltas");
  assert.strictEqual(Math.round(definitivo.total), 199900,
    "la duracion efectiva no es la que declara la API");
  const enUtc = b.tiempoDePresentacion(1, 100000 / c.efectivo) - T0;
  assert.strictEqual(Math.round(enUtc), 102050,
    "a 100.000 ms de tiempo rodado el instante no es el de despues del corte");
  assert.ok(!(enUtc > c.corte[0] + 1e-9 && enUtc < c.corte[1] - 1e-9),
    "el instante cae dentro del corte: " + enUtc);
});

prueba("da lo mismo que las vueltas lleguen antes que las series", async (b) => {
  const c = capturaConCorte(300);
  conAlcance(b);
  b.cargarDatosDeSesion("/sesiones/A", b.aperturaVigente(), "s", { session_id: "A" });
  await asentar();
  deRuta("vueltas").resolver(vueltasDelFixture("car:1", c));
  await asentar();
  b.asegurarVuelta(1);
  await asentar();
  const series = deRuta("series");
  if (series) { series.resolver(serieDelFixture("car:1", c)); await asentar(); }

  const r = b.relojDeVuelta(1);
  assert.strictEqual(r.aproximado, false);
  assert.strictEqual(Math.round(r.total), 199900);
  assert.strictEqual(Math.round(b.tiempoDePresentacion(1, 100000 / c.efectivo) - T0), 102050,
    "el orden de llegada cambia el instante");
});

prueba("el reloj toma los limites de la vuelta y no los de las senales", async (b) => {
  /* Una vuelta continua cuya ventana declarada empieza antes y termina despues
     que las muestras. Los limites autoritativos son los de la vuelta: en Spa la
     serie arranca 250 ms mas tarde que la vuelta, y con el reloj apoyado en la
     serie el cabezal en cero caia en otro sitio. */
  conAlcance(b);
  b.cargarDatosDeSesion("/sesiones/A", b.aperturaVigente(), "s", { session_id: "A" });
  await asentar();
  b.asegurarVuelta(1);
  await asentar();
  deRuta("series").resolver({ vehiculos: { "car:1": {
      distancia_m: [0, 50, 100],
      timestamp_utc: [iso(1000), iso(2000), iso(3000)],
      speed: [200, 210, 220], throttle_position: [1, 2, 3] } },
      puntos_pedidos: 300, submuestreado: false });
  await asentar();
  assert.strictEqual(Math.round(b.relojDeVuelta(1).total), 2000,
    "el reloj provisional deberia medir lo que abarcan las muestras");

  deRuta("vueltas").resolver({ vehiculo: "car:1", vueltas: [{
    numero: 1, duracion_s: 4, duracion_bruta_s: 4, hueco_mayor_s: 0.05,
    continua: true, huecos: [],
    desde_utc: iso(0), hasta_utc: iso(4000) }] });
  await asentar();

  const r = b.relojDeVuelta(1);
  assert.strictEqual(r.aproximado, false);
  assert.strictEqual(Math.round(r.total), 4000,
    "el reloj no adopto la ventana declarada de la vuelta");
  assert.strictEqual(Math.round(b.tiempoDePresentacion(1, 0) - T0), 0,
    "el cabezal en cero no cae en el arranque declarado de la vuelta");
  assert.strictEqual(Math.round(b.tiempoDePresentacion(1, 1) - T0), 4000);
});

/* ==================================================================
   PRECARGA DE FONDO Y ESPERA AL CRUZAR LA META
   ================================================================== */

prueba("la precarga de fondo no enciende el velo de los paneles", async (b) => {
  /* Los paneles que estan en pantalla tienen dato valido; taparlos con un
     shimmer mientras se trae lo que todavia no se mira dice que no lo tienen.
     La consulta se registra igual ---cuenta para el limite de espera y para la
     deduplicacion--- pero no se declara como carga visible. */
  conAlcance(b);
  b.estado.vueltas = [{ numero: 1 }, { numero: 2 }];
  Object.keys(VELOS).forEach(k => delete VELOS[k]);
  b.asegurarVuelta(2, undefined, true);
  await asentar();
  assert.ok(PEDIDOS.length > 0, "la precarga no salio");
  assert.deepStrictEqual(
    Object.keys(VELOS).filter(k => VELOS[k] === "si"), [],
    "una precarga encendio el velo de: " +
    Object.keys(VELOS).filter(k => VELOS[k] === "si").join(", "));
});

prueba("una consulta que si se espera para mirar declara su carga", async (b) => {
  /* No se elimino toda indicacion de carga: la inicial sigue estando. */
  conAlcance(b);
  Object.keys(VELOS).forEach(k => delete VELOS[k]);
  b.asegurarVuelta(1);
  await asentar();
  assert.ok(Object.keys(VELOS).some(k => VELOS[k] === "si"),
    "la carga que se esta esperando para mirar dejo de declararse");
});

prueba("una respuesta de fondo no reinicia el panel actual", async (b) => {
  conAlcance(b);
  b.estado.vueltas = [{ numero: 1 }, { numero: 2 }];
  b.asegurarVuelta(1);
  await asentar();
  PEDIDOS.forEach(p => p.resolver(respuesta("car:1", 300, 10)));
  PEDIDOS.length = 0;
  await asentar();
  const antes = JSON.stringify(b.estado.series[1]);
  b.asegurarVuelta(2, undefined, true);
  await asentar();
  PEDIDOS.forEach(p => p.resolver(respuesta("car:1", 300, 20)));
  await asentar();
  assert.strictEqual(JSON.stringify(b.estado.series[1]), antes,
    "la respuesta de fondo escribio sobre la vuelta que se esta mirando");
  assert.ok(b.estado.series[2], "la precarga no quedo guardada");
});

/* Dos vueltas declaradas de cien segundos cada una, para poder hablar de
   fracciones del cabezal. */
function dosVueltasDeclaradas(b) {
  b.estado.vueltas = [
    { numero: 1, duracion_s: 100, desde_utc: "2026-09-05T00:00:00Z", hasta_utc: "2026-09-05T00:01:40Z" },
    { numero: 2, duracion_s: 100, desde_utc: "2026-09-05T00:01:40Z", hasta_utc: "2026-09-05T00:03:20Z" },
  ];
}

prueba("a 10x se precargan las vueltas que entran en los proximos veinte segundos", (b) => {
  b.estado.vueltas = [1, 2, 3, 4].map(numero => ({ numero, duracion_s: 100 }));
  b.fijarVelocidad(1);
  assert.deepStrictEqual(b.vueltasParaPrecargar(1), [2],
    "a velocidad normal se pidio mas de una vuelta futura");
  b.fijarVelocidad(10);
  assert.deepStrictEqual(b.vueltasParaPrecargar(1), [2, 3],
    "a 10x no se cubrieron los veinte segundos siguientes");
});

prueba("sin duraciones medidas la precarga queda acotada a la siguiente", (b) => {
  b.estado.vueltas = [1, 2, 3, 4].map(numero => ({ numero }));
  b.fijarVelocidad(10);
  assert.deepStrictEqual(b.vueltasParaPrecargar(1), [2],
    "sin plazo medido se intento traer la carrera entera");
});

prueba("se pregunta por donde se va a pisar, no por donde se piso", async (b) => {
  /* EL DEFECTO QUE ESTO CUIDA. Comprobandolo despues de mover, el cabezal ya
     habia entrado en la vuelta sin datos y el cuadro ya se habia pintado
     vacio: los cuatro graficos decian «sin dato en esta vuelta» y los
     medidores, rayas. */
  conAlcance(b); dosVueltasDeclaradas(b);
  b.estado.series[1] = respuesta("car:1", 300, 10);
  assert.strictEqual(b.vueltaEnFraccion(0.25), 1);
  assert.strictEqual(b.vueltaEnFraccion(0.75), 2);
  /* Parado en la vuelta 1, que esta: no falta nada. */
  assert.strictEqual(b.faltaLoImprescindible(0.25), false);
  /* Pero un paso mas adelante entra en la 2, que no esta. */
  assert.strictEqual(b.faltaLoImprescindible(0.75), true,
    "no se mira la vuelta a la que se va a entrar");
});

prueba("una vuelta que fallo no se espera para siempre", async (b) => {
  conAlcance(b); dosVueltasDeclaradas(b);
  assert.strictEqual(b.faltaLoImprescindible(0.75), true);
  b.estado.fallo[2] = "la red se cayo";
  assert.strictEqual(b.faltaLoImprescindible(0.75), false,
    "la reproduccion se queda esperando una vuelta que no va a venir");
});

prueba("una respuesta valida sin datos no es una espera", async (b) => {
  /* «Todavia no llego» y «llego y no tiene nada» se ven igual desde afuera si
     nadie las distingue. La segunda se guarda como bloque vacio y se sigue. */
  conAlcance(b); dosVueltasDeclaradas(b);
  b.asegurarVuelta(2);
  await asentar();
  PEDIDOS.forEach(p => p.resolver({ vehiculos: {}, puntos_pedidos: 300 }));
  await asentar();
  assert.ok(b.estado.series[2], "la respuesta vacia no quedo registrada");
  assert.strictEqual(b.faltaLoImprescindible(0.75), false,
    "se sigue esperando una vuelta que ya contesto");
});

prueba("un fallo queda anotado y una respuesta buena lo borra", async (b) => {
  conAlcance(b); dosVueltasDeclaradas(b);
  b.asegurarVuelta(2);
  await asentar();
  PEDIDOS.forEach(p => p.rechazar(new Error("500")));
  await asentar();
  assert.ok(b.estado.fallo[2], "el fallo no quedo anotado");
  assert.ok(AVISOS.some(a => a.esError), "el fallo no se declaro");
  PEDIDOS.length = 0;
  b.asegurarVuelta(2);
  await asentar();
  assert.ok(PEDIDOS.length > 0, "no se volvio a pedir la vuelta que fallo");
  PEDIDOS.forEach(p => p.resolver(respuesta("car:1", 300, 30)));
  await asentar();
  await asentar();
  assert.ok(!b.estado.fallo[2],
    "el fallo sobrevivio a una respuesta buena: " + JSON.stringify(b.estado.fallo));
});

prueba("la espera se declara y se suelta sola", async (b) => {
  conAlcance(b); dosVueltasDeclaradas(b);
  AVISOS_ESTADO.length = 0;
  b.anotarEspera(2);
  assert.strictEqual(b.espera(), 2);
  assert.ok(AVISOS_ESTADO.some(t => /Preparando la vuelta 2/.test(t)),
    "no se aviso de la espera: " + JSON.stringify(AVISOS_ESTADO));
  b.anotarEspera(2);
  assert.strictEqual(AVISOS_ESTADO.filter(t => /Preparando/.test(t)).length, 1,
    "se repite el aviso en cada cuadro");
  b.soltarEspera();
  assert.strictEqual(b.espera(), null);
});

prueba("una pausa cancela la espera, y una respuesta tardia no la reanuda", async (b) => {
  /* Una respuesta que llega despues no puede deshacer lo que una persona
     decidio. `detener` suelta la espera; lo que llegue despues se guarda y no
     vuelve a poner en marcha nada. */
  conAlcance(b); dosVueltasDeclaradas(b);
  b.anotarEspera(2);
  b.asegurarVuelta(2);
  await asentar();
  b.soltarEspera();                       // es lo que hace `detener`
  assert.strictEqual(b.espera(), null);
  PEDIDOS.forEach(p => p.resolver(respuesta("car:1", 300, 40)));
  await asentar();
  assert.strictEqual(b.espera(), null,
    "una respuesta tardia volvio a poner el tablero en espera");
  assert.ok(b.estado.series[2], "la respuesta igual se guarda");
});

prueba("cambiar de alcance durante la carga no deja la espera colgada", async (b) => {
  conAlcance(b); dosVueltasDeclaradas(b);
  b.anotarEspera(2);
  b.asegurarVuelta(2);
  await asentar();
  const apertura = b.nuevaSesionEnCurso();   // otra apertura: la anterior queda vieja
  b.soltarEspera();
  PEDIDOS.forEach(p => p.resolver(respuesta("car:1", 300, 50)));
  await asentar();
  assert.strictEqual(b.espera(), null);
  assert.ok(!b.estado.series[2],
    "la respuesta de la apertura vieja escribio sobre la nueva");
  void apertura;
});

prueba("la poda no suelta una vuelta que todavia esta en pantalla", async (b) => {
  /* Con la ventana movil sobre el eje acumulado, la vuelta anterior sigue
     aportando muestras despues de cruzar la meta. Podarla porque el cabezal ya
     no esta en ella vaciaria la mitad izquierda del grafico justo cuando se la
     puso a servir para algo. */
  b.estado.abierta = { session_id: "A" };
  /* El cabezal esta en la 1 y lo que se ve son la 19 y la 20: sin proteccion
     serian de las primeras en soltarse, porque la poda va por lejania. */
  b.fijarVuelta(1);
  for (let v = 1; v <= 30; v++) {
    b.estado.series[v] = { puntos_pedidos: 300, vehiculos: {} };
  }
  b.fijarEnPantalla([19, 20]);
  b.podarVueltas();
  assert.ok(b.estado.series[1], "se podo la vuelta que se esta mirando");
  assert.ok(b.estado.series[19] && b.estado.series[20],
    "se podaron vueltas que todavia aportan a la ventana");
  assert.ok(Object.keys(b.estado.series).length < 30,
    "no se podo nada: la prueba no comprueba la proteccion");
  b.fijarEnPantalla([]);
});

/* ==================================================================
   EL CICLO DE ERRORES DE LAS CONSULTAS
   ================================================================== */

const esperar = (ms) => new Promise(r => setTimeout(r, ms));

prueba("un corte por tiempo se registra como fallo, no como cancelacion", async (b) => {
  /* EL DEFECTO. `pedir` corta por tiempo con el mismo controlador de aborto
     que usa la cancelacion voluntaria, asi que el error llega con
     `name === "AbortError"` y `fueAnulada` lo daba por cancelado: no se
     anotaba fallo, el reproductor seguia creyendo que la vuelta venia en
     camino y la volvia a pedir en cada cuadro.

     Esto ejerce el camino real ---`pedir` y su controlador--- con el limite
     acortado, no una promesa rechazada con un error inventado. */
  conAlcance(b);
  b.estado.vueltas = [{ numero: 1 }, { numero: 2 }];
  b.asegurarVuelta(2);
  await esperar(5);
  assert.ok(FETCHS.length > 0, "no salio la consulta de verdad");
  await esperar(120);                       // el limite del banco son 40 ms
  assert.ok(b.estado.fallo[2],
    "un corte por tiempo quedo como cancelacion: la espera no termina nunca");
  assert.ok(AVISOS.some(a => a.esError), "el corte por tiempo no se declaro");
  assert.strictEqual(b.faltaLoImprescindible(0.75), false,
    "el reproductor sigue esperando una vuelta que ya no va a venir");
}, { pedirReal: true, limiteMs: 40 });

prueba("una cancelacion intencional no deja fallo ni aviso", async (b) => {
  /* Cambiar de sesion aborta lo que quedo en vuelo. Eso no es un error y no
     puede terminar en `estado.fallo`, ni reanudar nada despues. */
  conAlcance(b);
  b.estado.vueltas = [{ numero: 1 }, { numero: 2 }];
  b.asegurarVuelta(2);
  await esperar(5);
  b.nuevaSesionEnCurso();                   // aborta la señal de la sesion
  await esperar(15);
  assert.ok(!b.estado.fallo[2], "una cancelacion voluntaria quedo como fallo");
  assert.ok(!AVISOS.some(a => a.esError), "una cancelacion voluntaria se declaro como error");
}, { pedirReal: true, limiteMs: 400 });

prueba("un error de la apertura anterior no ensucia la nueva", async (b) => {
  /* EL DEFECTO. La continuacion feliz comprueba `sigueVigente(apertura)`; la
     de error escribia sobre el estado de turno sin esa guarda. Se pedia la
     vuelta 2 en el alcance A, se cambiaba a B, y el error de A terminaba en
     `B.fallo[2]` cambiando su decision de esperar datos. */
  conAlcance(b);
  b.estado.vueltas = [{ numero: 1 }, { numero: 2 }];
  b.asegurarVuelta(2);
  await asentar();
  const deA = deRuta("series");
  assert.ok(deA, "no salio la consulta de A");
  /* Se cambia de alcance: otra apertura y el estado limpio. */
  b.nuevaSesionEnCurso();
  b.estado.fallo = {};
  deA.rechazar(new Error("500 desde A"));
  await asentar();
  assert.ok(!b.estado.fallo[2],
    "el error de la apertura anterior quedo anotado en la nueva");
  assert.ok(!AVISOS.some(a => a.esError),
    "el error de la apertura anterior se declaro sobre la nueva");
});

prueba("A -> B -> A: el error de la primera A no ensucia la segunda", async (b) => {
  /* Comparar el identificador de sesion no alcanza: A y A son la misma sesion
     y dos aperturas distintas. */
  conAlcance(b);
  b.estado.vueltas = [{ numero: 1 }, { numero: 2 }];
  b.asegurarVuelta(2);
  await asentar();
  const primeraA = deRuta("series");
  PEDIDOS.length = 0;
  b.nuevaSesionEnCurso();                   // se va a B
  b.nuevaSesionEnCurso();                   // y se vuelve a A
  b.estado.fallo = {};
  primeraA.rechazar(new Error("500 de la primera A"));
  await asentar();
  assert.ok(!b.estado.fallo[2],
    "el error de la primera apertura de A ensucio la segunda");
});

prueba("un corte por tiempo viejo tampoco ensucia el alcance nuevo", async (b) => {
  conAlcance(b);
  b.estado.vueltas = [{ numero: 1 }, { numero: 2 }];
  b.asegurarVuelta(2);
  await esperar(5);
  b.nuevaSesionEnCurso();                   // se cambia de alcance
  b.estado.fallo = {};
  await esperar(120);                       // y recien despues vence el limite
  assert.ok(!b.estado.fallo[2],
    "un corte por tiempo de la apertura anterior quedo anotado en la nueva");
}, { pedirReal: true, limiteMs: 40 });

prueba("un fallo de la apertura vigente si se registra", async (b) => {
  /* La guarda no puede tragarse los errores que si son de lo que se mira. */
  conAlcance(b);
  b.estado.vueltas = [{ numero: 1 }, { numero: 2 }];
  b.asegurarVuelta(2);
  await asentar();
  deRuta("series").rechazar(new Error("500 de verdad"));
  await asentar();
  assert.ok(b.estado.fallo[2], "el fallo de la apertura vigente no se registro");
  assert.ok(AVISOS.some(a => a.esError), "el fallo de la apertura vigente no se declaro");
});

prueba("la marca de pedido la borra su dueña, tambien al fallar", async (b) => {
  /* La proteccion que ya habia: una peticion vieja que termina tarde no puede
     borrar la marca de la peticion nueva de la misma vuelta. */
  conAlcance(b);
  b.estado.vueltas = [{ numero: 1 }, { numero: 2 }];
  b.asegurarVuelta(2);
  await asentar();
  const vieja = deRuta("series");
  PEDIDOS.length = 0;
  const marcaVieja = b.estado.pidiendo[2];
  delete b.estado.pidiendo[2];              // como si hubiera terminado
  b.asegurarVuelta(2);
  await asentar();
  const marcaNueva = b.estado.pidiendo[2];
  assert.notStrictEqual(marcaNueva, marcaVieja, "no se registro una peticion nueva");
  vieja.rechazar(new Error("500 vieja"));
  await asentar();
  assert.strictEqual(b.estado.pidiendo[2], marcaNueva,
    "la peticion vieja borro la marca de la nueva al fallar");
});

/* ==================================================================
   LA PROTECCION DE LA VENTANA ENTRA EN EL PRESUPUESTO
   ================================================================== */

prueba("trece vueltas visibles no rompen el presupuesto", async (b) => {
  /* EL DEFECTO. Las vueltas que aportan a la ventana quedaban **excluidas** de
     la poda sin limite. Con una ventana de tres kilometros sobre vueltas
     cortas o parciales, trece bloques de 300 puntos sobreviven: 3.900 contra
     un presupuesto de 3.600. La memoria visible no puede declararse ilimitada.

     Cuando la ventana no entra con este detalle, se suelta cobertura por el
     extremo mas viejo ---se ve menos historia--- y no se inventan puntos ni se
     falsean extremos. */
  b.estado.abierta = { session_id: "A" };
  b.fijarVuelta(13);
  for (let v = 1; v <= 13; v++) {
    b.estado.series[v] = { puntos_pedidos: 300, vehiculos: {} };
  }
  b.fijarEnPantalla([1,2,3,4,5,6,7,8,9,10,11,12,13]);
  b.podarVueltas();
  const quedan = Object.keys(b.estado.series).length;
  assert.ok(quedan * 300 <= b.limiteDeDetalle(),
    "quedaron " + (quedan * 300) + " puntos contra un presupuesto de " +
    b.limiteDeDetalle());
  assert.ok(b.estado.series[13], "se solto la vuelta que se esta mirando");
  /* Y lo que se suelta es lo mas viejo, no lo de al lado del cabezal. */
  assert.ok(b.estado.series[12], "se solto la vuelta contigua antes que la mas vieja");
  assert.ok(!b.estado.series[1], "no se solto la mas lejana");
});

prueba("una ventana que si cabe conserva toda su historia", async (b) => {
  b.estado.abierta = { session_id: "A" };
  b.fijarVuelta(3);
  for (let v = 1; v <= 3; v++) {
    b.estado.series[v] = { puntos_pedidos: 300, vehiculos: {} };
  }
  b.fijarEnPantalla([2, 3]);
  b.podarVueltas();
  assert.ok(b.estado.series[2] && b.estado.series[3],
    "se solto historia que entraba en el presupuesto");
});

prueba("pasar a vuelta completa libera la proteccion anterior", async (b) => {
  /* La proteccion solo se reemplazaba cuando la lista nueva tenia elementos,
     asi que al pasar a «vuelta completa» ---donde la ventana es de una sola
     vuelta y no aporta acumuladas--- quedaban protegidas vueltas que ya no se
     ven, para siempre. */
  b.estado.abierta = { session_id: "A" };
  b.fijarVuelta(20);
  for (let v = 1; v <= 30; v++) {
    b.estado.series[v] = { puntos_pedidos: 300, vehiculos: {} };
  }
  b.fijarEnPantalla([2, 3]);
  b.podarVueltas();
  assert.ok(b.estado.series[2] && b.estado.series[3], "no se protegio lo visible");
  /* Se cambia a una vista que no aporta acumuladas: la lista queda vacia. */
  b.anotarEnPantalla([]);
  for (let v = 1; v <= 30; v++) {
    if (!b.estado.series[v]) b.estado.series[v] = { puntos_pedidos: 300, vehiculos: {} };
  }
  b.podarVueltas();
  assert.ok(!b.estado.series[2] && !b.estado.series[3],
    "quedaron protegidas vueltas que ya no se ven");
});

prueba("el cuadro retenido durante la espera conserva su proteccion", async (b) => {
  /* Una ventana vacia de verdad y un cuadro anterior retenido mientras se
     espera la vuelta siguiente no son lo mismo: el segundo todavia necesita
     sus datos para seguir dibujado. */
  /* Las protegidas van lejos del cabezal: pegadas a el sobrevivirian por
     cercania y la prueba pasaria por el motivo equivocado. */
  const llenar = () => {
    for (let v = 1; v <= 30; v++) {
      if (!b.estado.series[v]) b.estado.series[v] = { puntos_pedidos: 300, vehiculos: {} };
    }
  };
  b.estado.abierta = { session_id: "A" };
  b.fijarVuelta(28);
  llenar();
  b.fijarEnPantalla([2, 3]);
  b.anotarEspera(29);                       // se esta esperando la siguiente
  b.anotarEnPantalla([]);                   // y en ese cuadro no hubo aportes
  b.podarVueltas();
  assert.ok(b.estado.series[2] && b.estado.series[3],
    "se solto el cuadro que se esta reteniendo durante la espera");
  b.soltarEspera();
  llenar();
  b.anotarEnPantalla([]);
  b.podarVueltas();
  assert.ok(!b.estado.series[2] && !b.estado.series[3],
    "al terminar la espera la proteccion no se solto");
});

prueba("podar dos veces seguidas no suelta nada mas", async (b) => {
  /* Si cada poda dejara el estado por encima del presupuesto, la siguiente
     volveria a soltar y el ciclo de descargar y expulsar no terminaria nunca.
     Despues de una poda el estado tiene que estar dentro del limite y quieto. */
  b.estado.abierta = { session_id: "A" };
  b.fijarVuelta(13);
  for (let v = 1; v <= 13; v++) {
    b.estado.series[v] = { puntos_pedidos: 300, vehiculos: {} };
  }
  b.fijarEnPantalla([1,2,3,4,5,6,7,8,9,10,11,12,13]);
  b.podarVueltas();
  const primera = Object.keys(b.estado.series).sort().join(",");
  b.podarVueltas();
  assert.strictEqual(Object.keys(b.estado.series).sort().join(","), primera,
    "la segunda poda solto mas: el ciclo no converge");
});

prueba("cambiar de alcance suelta la proteccion", async (b) => {
  b.fijarEnPantalla([5, 6]);
  b.limpiarLoDeLaCorrida();
  assert.deepStrictEqual(b.enPantalla(), [],
    "la proteccion sobrevivio al cambio de alcance");
});

/* ==================================================================
   EL REINTENTO A MANO DENTRO DE UNA VUELTA QUE FALLO
   ================================================================== */

/* El debounce de `moverCabezal` son 200 ms de reloj de verdad. */
const trasElDebounce = () => esperar(320);

function listaParaMover(b) {
  conAlcance(b);
  b.estado.vueltas = [
    { numero: 1, duracion_s: 100 },
    { numero: 2, duracion_s: 100 },
  ];
}

prueba("dentro de la vuelta que fallo, mover el cabezal a mano vuelve a pedir", async (b) => {
  /* EL DEFECTO. El aviso del fallo dice «mové el cabezal a esa vuelta para
     volver a pedirla», y `moverCabezal` solo pedia **al cambiar de vuelta**.
     Quien ya estaba dentro de la vuelta fallida movia el cabezal y no pasaba
     nada: la instruccion del mensaje no se podia cumplir. */
  listaParaMover(b);
  b.fijarCabezal(0.75);
  b.moverCabezal(0.75);                       // se entra en la vuelta 2
  await trasElDebounce();
  assert.ok(deRuta("series"), "no se pidio al entrar en la vuelta");
  deRuta("series").rechazar(new Error("500"));
  await asentar();
  assert.ok(b.estado.fallo[2], "el fallo no quedo anotado");
  PEDIDOS.length = 0;

  /* Se mueve **dentro de la misma vuelta**, a mano. */
  b.moverCabezal(0.80, true);
  await trasElDebounce();
  assert.ok(deRuta("series"),
    "moverse dentro de la vuelta que fallo no volvio a pedirla");
});

prueba("el avance automatico no vuelve a pedir dentro de la misma vuelta", async (b) => {
  /* La correccion no puede convertir el bucle de animacion en una tormenta:
     sin la marca de que la accion es de una persona, moverse dentro de la
     vuelta no pide nada. */
  listaParaMover(b);
  b.fijarCabezal(0.75);
  b.moverCabezal(0.75);
  await trasElDebounce();
  deRuta("series").rechazar(new Error("500"));
  await asentar();
  PEDIDOS.length = 0;
  for (let i = 0; i < 30; i++) b.moverCabezal(0.75 + i * 0.0001);   // como el reproductor
  await trasElDebounce();
  assert.strictEqual(PEDIDOS.length, 0,
    "el avance automatico pidio " + PEDIDOS.length + " veces dentro de la misma vuelta");
});

prueba("varios seek seguidos son una sola consulta", async (b) => {
  /* Arrastrar la barra dispara decenas de movimientos: el debounce los junta
     en uno. */
  listaParaMover(b);
  b.fijarCabezal(0.75);
  b.moverCabezal(0.75);
  await trasElDebounce();
  deRuta("series").rechazar(new Error("500"));
  await asentar();
  PEDIDOS.length = 0;
  for (let i = 0; i < 20; i++) b.moverCabezal(0.76 + i * 0.001, true);
  /* Todavia no: el retardo existe para distinguir un arrastre de una parada, y
     sin el cada movimiento del cursor saldria como consulta. */
  await esperar(60);
  assert.strictEqual(PEDIDOS.length, 0,
    "se pidio en el acto, sin esperar a que el cabezal se quedara quieto");
  await trasElDebounce();
  const series = PEDIDOS.filter(p => p.ruta.indexOf("/series") !== -1);
  assert.strictEqual(series.length, 1,
    "un arrastre dejo " + series.length + " consultas de series en vuelo");
});

prueba("con una consulta en vuelo, el seek no duplica", async (b) => {
  /* La deduplicacion por `estado.pidiendo` sigue valiendo: mientras la
     consulta viaja, moverse no lanza otra. */
  listaParaMover(b);
  b.fijarCabezal(0.75);
  b.moverCabezal(0.75);
  await trasElDebounce();
  const enVuelo = PEDIDOS.filter(p => p.ruta.indexOf("/series") !== -1).length;
  assert.ok(enVuelo > 0, "no salio la primera consulta");
  assert.ok(b.estado.pidiendo[2], "no quedo la marca de peticion en curso");
  PEDIDOS.length = 0;
  b.moverCabezal(0.80, true);
  await trasElDebounce();
  assert.strictEqual(PEDIDOS.filter(p => p.ruta.indexOf("/series") !== -1).length, 0,
    "se duplico la consulta que ya estaba en vuelo");
});

prueba("con la vuelta ya cargada, moverse a mano no pide de nuevo", async (b) => {
  listaParaMover(b);
  b.fijarCabezal(0.75);
  b.moverCabezal(0.75);
  await trasElDebounce();
  deRuta("series").resolver(respuesta("car:1", 300, 10));
  await asentar();
  assert.ok(b.estado.series[2], "la vuelta no quedo cargada");
  PEDIDOS.length = 0;
  b.moverCabezal(0.80, true);
  await trasElDebounce();
  assert.strictEqual(PEDIDOS.filter(p => p.ruta.indexOf("/series") !== -1).length, 0,
    "se volvio a pedir una vuelta que ya estaba");
});

/* ------------------------------------------------------------------ */
(async () => {
/* ------------------------------------------------------------------
   UNA FUENTE SIN EJE DE DISTANCIA PIDE HISTORICO TEMPORAL
   ------------------------------------------------------------------
   La reproduccion historica va contra distancia recorrida. El bus del vehiculo
   publica velocidad de rueda y no publica odometro ni distancia de vuelta, de
   modo que ese eje no existe para el. Eso no impide reproducir el reloj de la
   captura: el historico sale por `/series-tiempo`, sin fabricar metros.
   ------------------------------------------------------------------ */

prueba("el bus no tiene eje de distancia, y se sabe por que", async (b) => {
  b.fijarFuente("can");
  assert.strictEqual(b.hayEjeDeDistancia(), false);
  assert.ok(/odómetro/.test(b.porQueNoHayDistancia()), b.porQueNoHayDistancia());
  b.fijarFuente("openf1");
  assert.strictEqual(b.hayEjeDeDistancia(), false);
  assert.ok(/83 m/.test(b.porQueNoHayDistancia()), b.porQueNoHayDistancia());
  b.fijarFuente("f1");
  assert.strictEqual(b.hayEjeDeDistancia(), true);
});

prueba("con el bus abierto el historico sale por tiempo", async (b) => {
  conAlcance(b); dosVueltasDeclaradas(b);
  b.fijarFuente("can");
  b.asegurarVuelta(1);
  b.asegurarPosiciones(1);
  await asentar();
  assert.strictEqual(PEDIDOS.length, 1);
  assert.ok(PEDIDOS[0].ruta.indexOf("/series-tiempo?") !== -1, PEDIDOS[0].ruta);
  assert.ok(PEDIDOS[0].ruta.indexOf("/series?vuelta=") === -1, PEDIDOS[0].ruta);
  assert.strictEqual(b.alcancePermitePedir(), false);
});

prueba("la consulta por tiempo se acota a la vuelta que se pide", async (b) => {
  /* Sin acotar, `/series-tiempo` reparte los puntos pedidos sobre la sesion
     entera. En una carrera de dos horas y media eso son mil doscientos puntos
     para 9.197 segundos ---una muestra cada 7,8--- y una ventana de veinte
     segundos se dibuja con dos o tres puntos. */
  conAlcance(b); dosVueltasDeclaradas(b);
  b.fijarFuente("openf1");
  b.asegurarVuelta(2);
  await asentar();
  assert.strictEqual(PEDIDOS.length, 1);
  const ruta = PEDIDOS[0].ruta;
  assert.ok(ruta.indexOf("desde=") !== -1, "no acota el comienzo: " + ruta);
  assert.ok(ruta.indexOf("hasta=") !== -1, "no acota el final: " + ruta);
  assert.ok(ruta.indexOf(encodeURIComponent("2026-09-05T00:01:40Z")) !== -1,
            "no pide desde donde empieza la vuelta 2: " + ruta);
});

prueba("una fuente por tiempo puede pedir cualquiera de sus vueltas", async (b) => {
  /* `asegurarVuelta` rechazaba todo lo que no fuera la vuelta 1 cuando la
     fuente no tiene metro medido. OpenF1 declara sus vueltas por reloj, y esa
     restriccion dejaba fuera a todas menos la primera. */
  conAlcance(b); dosVueltasDeclaradas(b);
  b.fijarFuente("openf1");
  b.asegurarVuelta(2);
  await asentar();
  assert.strictEqual(PEDIDOS.length, 1, "la vuelta 2 no llego a pedirse");
});

prueba("y no pide una vuelta que la sesion no declara", async (b) => {
  /* Pedir lo que no existe devuelve vacio y se reintenta sin fin. */
  conAlcance(b); dosVueltasDeclaradas(b);
  b.fijarFuente("openf1");
  b.asegurarVuelta(9);
  await asentar();
  assert.strictEqual(PEDIDOS.length, 0);
});

prueba("la misma sesion en una fuente con eje si pide", async (b) => {
  conAlcance(b); dosVueltasDeclaradas(b);
  b.fijarFuente("f1");
  b.asegurarVuelta(1);
  await asentar();
  assert.ok(PEDIDOS.length, "no pidió nada con una fuente que sí tiene el eje");
});

prueba("el reproductor espera el tramo temporal mientras esta en camino", async (b) => {
  conAlcance(b); dosVueltasDeclaradas(b);
  b.fijarFuente("f1");
  assert.strictEqual(b.faltaLoImprescindible(0), true);
  b.fijarFuente("can");
  assert.strictEqual(b.faltaLoImprescindible(0), true);
});

prueba("un 422 no invita a reintentar", async (b) => {
  /* El consejo se escribio para fallos pasajeros. Con un 422 ---«esta consulta
     no se puede responder para esta fuente»--- mover el cabezal mil veces
     devuelve lo mismo. */
  conAlcance(b); dosVueltasDeclaradas(b);
  b.asegurarVuelta(2);
  await asentar();
  const permanente = new Error("La fuente can_real_replay no tiene eje de distancia");
  permanente.estado = 422;
  PEDIDOS.forEach(p => p.rechazar(permanente));
  await asentar();
  assert.strictEqual(b.estado.fallo[2].permanente, true);
  assert.ok(!/reintentar/.test(JSON.stringify(AVISOS)),
    "invitó a reintentar algo permanente: " + JSON.stringify(AVISOS));
});

prueba("un fallo pasajero sigue invitando a reintentar", async (b) => {
  conAlcance(b); dosVueltasDeclaradas(b);
  b.asegurarVuelta(2);
  await asentar();
  PEDIDOS.forEach(p => p.rechazar(new Error("500")));
  await asentar();
  assert.strictEqual(b.estado.fallo[2].permanente, false);
  assert.ok(/reintentar/.test(JSON.stringify(AVISOS)),
    "no ofreció reintentar un fallo pasajero: " + JSON.stringify(AVISOS));
});

  for (const t of pendientes) await t();
  if (process.exitCode) {
    console.error("\n" + hechas + " pruebas pasaron; hubo fallos.");
  } else {
    console.log(hechas + " pruebas de continuaciones asincronas: OK");
  }
})();
