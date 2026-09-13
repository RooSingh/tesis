/* Quien conduce, en que puesto va, cuanto lleva de vuelta y a cuanto del lider.
 *
 * CRITERIO. Como los demas arneses, las funciones se **extraen del `app.js`
 * que se publica** y se ejecutan; no se copian. Probar una reimplementacion
 * comprueba que la reimplementacion anda, que es justo lo que no interesa.
 *
 * LOS CUATRO DEFECTOS QUE ESTO CUIDA.
 *
 * 1. El marcador decia «19», que es el indice del vehiculo en el protocolo. El
 *    nombre ---NORRIS, numero 4, McLaren--- estaba guardado desde el dia de la
 *    captura y no cruzaba a la consulta.
 * 2. «sin parrilla» se decidia con `AUTOS.length <= 1`, de modo que una carrera
 *    de veinte de la que se guardo la telemetria de uno se leia como una sesion
 *    sin participantes. Son dos cosas distintas.
 * 3. `delta_to_race_leader` viaja en milisegundos y se imprimia crudo bajo un
 *    rotulo que decia segundos: 2.937 ms se leian como «2937.000».
 * 4. «Actual» era `fraccion del cabezal x duracion de la vuelta`, que es el
 *    tiempo de reproduccion y no el cronometro que midio el juego.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");

const APP = path.join(__dirname, "..", "..", "dashboard", "app.js");
const fuenteApp = fs.readFileSync(APP, "utf8");

function extraer(nombre) {
  const marca = "function " + nombre + "(";
  const desde = fuenteApp.indexOf(marca);
  if (desde === -1) throw new Error("no esta la funcion " + nombre + " en app.js");
  let i = fuenteApp.indexOf("{", desde);
  let nivel = 0;
  for (; i < fuenteApp.length; i++) {
    if (fuenteApp[i] === "{") nivel++;
    else if (fuenteApp[i] === "}") {
      nivel--;
      if (nivel === 0) return fuenteApp.slice(desde, i + 1);
    }
  }
  throw new Error("no cierra la funcion " + nombre);
}

/* EL ESTADO EN VIVO SE EXTRAE DE `app.js`, NO SE COPIA.

   POR QUE SE CONVIRTIO. Este arnes tenia una copia a mano de `const vivo`, con
   los cinco o seis campos que sus pruebas tocaban. Cada campo nuevo del objeto
   real la dejaba vieja, y el reset de produccion ---que los limpia todos---
   fallaba con «Cannot read properties of undefined (reading 'clear')»: un error
   que **apunta al arnes y no al cambio**, de modo que cuesta encontrarlo.

   Paso tres veces el 2026-09-12, con `marcaDePosicion`, `velocidadAnterior` y
   `metroDePosicion`. `tests/js/aislamiento_de_sesiones.js` extraia el objeto en
   vez de copiarlo y no tuvo el problema ninguna de las tres.

   Se corta por el `\n};` de cierre y no contando llaves: los comentarios del
   objeto tienen llaves adentro. */
function nuevoVivo() {
  const marca = "const vivo = {";
  const desde = fuenteApp.indexOf(marca);
  if (desde === -1) throw new Error("no esta `const vivo` en app.js");
  const fin = fuenteApp.indexOf("\n};", desde);
  if (fin === -1) throw new Error("no cierra `const vivo` en app.js");
  const vivo = new Function(
    "return " + fuenteApp.slice(desde + marca.length - 1, fin + 2))();
  /* Si la extraccion se rompiera, un objeto vacio pasaria por bueno y las
     pruebas dirian que todo anda. Son veintitres campos: se exige que sean
     muchos, no cuantos, para no atarse al numero del dia. */
  if (Object.keys(vivo).length < 10) {
    throw new Error("se extrajo un `vivo` con " + Object.keys(vivo).length +
                    " campos: la extraccion esta rota");
  }
  return vivo;
}

/* Las tablas de unidades tambien se sacan del archivo: escribirlas aca de nuevo
   dejaria pasar el dia en que alguien agregue un canal en milisegundos al
   `app.js` y no a la prueba.

   EL PUNTO Y COMA QUE CIERRA, NO EL PRIMERO QUE APARECE. Esto cortaba en el
   primer `;` del archivo despues del nombre, y un `;` dentro de un comentario o
   de una cadena ---«lo contesta la API sesion por sesion;»--- partia la
   declaracion al medio. El resultado no era un error legible: era la constante
   siguiente pegada a media declaracion. Se cuenta la profundidad de llaves,
   corchetes y parentesis, y se saltean comentarios y cadenas. */
function constante(nombre) {
  const i = fuenteApp.indexOf("const " + nombre + " =");
  if (i === -1) throw new Error("no esta la constante " + nombre);
  return fuenteApp.slice(i, finDeDeclaracion(i) + 1);
}

function finDeDeclaracion(desde) {
  let hondo = 0;
  for (let i = desde; i < fuenteApp.length; i++) {
    const c = fuenteApp[i], dos = fuenteApp.slice(i, i + 2);
    if (dos === "//") { i = fuenteApp.indexOf("\n", i); if (i === -1) break; continue; }
    if (dos === "/*") { i = fuenteApp.indexOf("*/", i + 2) + 1; continue; }
    if (c === '"' || c === "'" || c === "`") {
      for (i++; i < fuenteApp.length; i++) {
        if (fuenteApp[i] === "\\") i++;
        else if (fuenteApp[i] === c) break;
      }
      continue;
    }
    if (c === "{" || c === "[" || c === "(") hondo++;
    else if (c === "}" || c === "]" || c === ")") hondo--;
    else if (c === ";" && hondo === 0) return i;
  }
  throw new Error("no cierra la declaracion que empieza en " + desde);
}

function variable(nombre) {
  const i = fuenteApp.indexOf("let " + nombre + " =");
  if (i === -1) throw new Error("no esta la variable " + nombre);
  return fuenteApp.slice(i, finDeDeclaracion(i) + 1);
}

/* El estado del modulo que estas funciones leen. */
globalThis.estadoSesion = "cargado";
globalThis.fuente = "f1";
globalThis.cabezal = 0;
globalThis.vueltaElegida = 1;
globalThis.corrida = { adquisicion: null, fase: null, disponibles: null, mezclada: false };
globalThis.AUTOS = [];
/* A quien se eligio a mano gana a lo que la parrilla declara, y por eso
   `armarAutos` lo consulta. Sin declararlo aca, la funcion extraida no
   encuentra la variable y falla en la primera llamada. */
globalThis.propioAMano = null;
globalThis.TINTAS_DE_AUTO = ["--auto-1", "--auto-2", "--auto-3",
                             "--auto-4", "--auto-5", "--auto-6"];
globalThis._tintaPorVehiculo = new Map();
globalThis.vivo = nuevoVivo();
globalThis.document = { getElementById: () => null };
globalThis.seleccion = new Set();
globalThis.CURVAS = [];
globalThis.tinta = () => "#000";
globalThis.PISTA = { largo_m: 7000 };
globalThis.HUECO_DE_CAPTURA_MS = 2000;
globalThis.EJE_DISTANCIA = " distancia";
globalThis.EJE_DISTANCIA_SESION = " distancia de sesion";
globalThis.EJE_TIEMPO = " tiempo";
globalThis._selloSeries = 0;
globalThis._selloDeLoArmado = -1;
globalThis._seriesArmadas = new Map();
globalThis._selloDeLoTemporal = -1;
globalThis._temporales = new Map();
globalThis._huboInterpolacion = false;
globalThis.SENAL_CAN = { throttle: "gas_pressed", brake: "brake_pressed" };
globalThis.SENAL_OPENF1 = { brake: "brake_applied", drs: "drs_state_code" };
/* `nombreDeSenal` tambien consulta la tabla del simulador. Copia a mano, como
   las demas de este arnes: ver la nota de `vivo` mas arriba. */
globalThis.SENAL_F1 = { posX: "world_position_x", posY: "world_position_z" };
globalThis.estado = { series: {}, posiciones: {}, vueltas: [], abierta: null,
                      puesta: null, vehiculoClave: "car:19" };

const NOMBRES = [
  "numeroMedido", "nombreDeSenal", "recortarPorDominio",
  "textoSeguro", "claveCorta", "identidadDeVehiculo",
  "renombrarAutos", "armarAutos", "camposDeIdentidad",
  // El color es del vehiculo y no de su lugar en la lista: `armarAutos` se lo
  // pregunta a esta, que recuerda el que le dio la primera vez.
  "tintaDeVehiculo",
  "anotarParrillas", "parrillaVigente",
  "secundarioDeVehiculo", "quienConduce",
  "vehiculosConTelemetriaGuardada", "autoPropio",
  "unidadDeCanal", "sinCambiosEnElTramo",
  "divisorDeUnidad", "unidadDeclaradaDe", "divisorDePresentacion",
  "estaEnLaUnidadQueSeMuestra", "serieCrudaDeCanal", "_armarSerieDeCanal",
  "_enUnidad", "trazarSerie", "_cruzaUnHueco", "huecosDeLaSerie", "huecoDeLaSerie",
  "comoSeVeElFlujo",
  "tiempoDeVuelta", "diferenciaEnSegundos",
  "reservaDeArriba", "encuadrarTrazado",
  "metroDeCurva", "zonasDeCurva", "bandasDeVuelta", "bandasParaElTramo",
  "pintarZonas", "partirEnRenglones", "vistaDeComparacion",
  "segmentosComparacion", "vueltasParaComparar", "nombreDeLaLamina",
  "pieDeExportacion", "exportarComparacion", "extremosDeDistancia",
  "reducirAAncho", "escalaDe", "dominioAmpliado",
  "pintarLeyendaTraza", "exportarCsv", "elegirCorrida",
  "alcanceElegidoEsValido", "adquisicionSeSolapa", "sonUnaSolaCarrera",
  "huecosEnLaLinea", "comoSeLeeElHueco",
  "parrillaComun",
  "faseDeLaDireccion",
  "olvidarLoDeLaCorrida", "nuevaSesionEnCurso", "aperturaVigente", "sigueVigente",
  "cambiaronLasSeries",
  "esCanalEscalonado", "_cacheTemporal", "serieTemporal", "_serieTemporalCruda",
  "continuidadDeVuelta", "_umbralDeVuelta", "tiempoEfectivoEntre", "hayCorteEntre",
  "huecoQueContiene",
  "_antesDe", "valorContinuoEn", "valorEscalonadoEn", "abscisaContinua",
  "loQueSeSabeDelVehiculo", "faltanVehiculosPorAprender", "nombreCortoDeVehiculo",
  "muestrasQueAporta", "idsParaComparar", "sePuedeComparar",
  "poblarPropio",
  "relojDeVuelta", "_armarRelojDeVuelta", "_tramosContinuos", "_tramosDeMuestras",
  "tiempoDePresentacion", "recortarConBordes",
  "serieDeCanal", "serieAcumuladaDeCanal", "tramoAcumuladoDeVuelta",
  "vueltasEnTramoAcumulado", "claveVehiculoPropio", "duracionDeVuelta", "duracionSesionS",
  "huecosQueSeAtraviesan", "_vueltaQueVeniaRodando", "duracionEnLaLinea",
  "_conLosCortesAdentro",
  "vueltasDeLaSesion", "iniciosDeVuelta", "calcularInstante",
  "vueltaEnFraccion", "trazadoAPath",
  "tramoDeLaVuelta",
  "pedirTrazado",
  "senalesParaElRecorrido",
  "pieDelRecorrido",
  "extremosDeLaTraza", "_rgbDe",
  "nombreDeSenal",
  "panelEstaPresente",
  "renglonesDelPanelG",
  "escalaDelDiagramaG",
  "puntoDelDiagramaG", "escalaDeLaVuelta",
  "cifra",
  "hayCoordenadasMedidas", "porQueNoHayCoordenadas", "hayEjeDeDistancia",
  "ejeQueLaFuenteSostiene", "porQueNoHayDistancia", "hayVueltas",
  "ejeVigente", "motivoDelEjeEspacial", "coberturaDeLaVista",
  "explicacionDelTrazado",
  "textoDeLaValidacion",
  "claveDeSesionOpenF1", "parrillaDesdePilotos",
  "puntoDelBusEn", "_indiceEnElRecorrido", "valoresSobreElRecorrido",
  "tramosDelRecorrido", "tintaDelValor",
];

const CONSTANTES = ["SENAL_DE", "SENAL_CAN", "SENAL_OPENF1",
                    "VECES_EL_PASO_HABITUAL", "SILENCIO_QUE_APAGA_MS",
                    "TODAS_LAS_CAPTURAS",
                    "HUECO_DE_CAPTURA_MS",
                    "UNIDAD_QUE_MUESTRA_EL_TABLERO",
                    "DIVISOR_ENTRE_UNIDADES", "SIN_VEHICULO",
                    "UNIDAD_POR_FUENTE",
                    "MARGEN_DEL_TRAZADO", "ALTURA_DEL_ROTULO", "CUERPO_DEL_ROTULO",
                    "TRAMOS_DE_LA_TRAZA",
                    "COORDENADAS_POR_FUENTE", "EJE_DE_DISTANCIA_POR_FUENTE",
                    "FUENTES",
                    "CANALES_POR_FUENTE",
                    "PASOS_DE_LA_ESCALA_G",
                    "CENTRO_DEL_DIAGRAMA_G", "RADIO_DEL_DIAGRAMA_G",
                    "MUESTRAS_PARA_CONTRASTAR", "CORRELACION_QUE_CONVENCE",
                    "METRICAS"];

const sacadas = new Function(
  CONSTANTES.map(constante).join("\n") + "\n" +
  variable("_ascendenteDelRotulo") + "\n" +
  "let PARRILLAS = null;\n" +
  "let _contextoDeCorrida = null;\n" +
  "let _aperturaActual = 0;\n" +
  "let _mandoSesion = null;\n" +
  "let PISTA = {};\n" +
  "let CURVAS = [];\n" +
  "let _esencialResuelta = false;\n" +
  "let _vueltasEnPantalla = [];\n" +
  "let _instanteClave = null;\n" +
  "let _rutas = [];\n" +
  "function pedirRecorridoDelBus() { _rutas.push('/can/recorrido'); }\n" +
  "function conCarga(cual, fn) { return fn(); }\n" +
  "function pedir(u) { _rutas.push(u); return Promise.resolve(null); }\n" +
  "function sufijoDeCorrida() { return ''; }\n" +
  "function senalDeSesion() { return null; }\n" +
  "const TESTIGO = { trazadosPedidos: 0, trazadosDescartados: 0, trazadosAplicados: 0 };\n" +
  "let _selloDeIdentidad = 0;\n" +
  "const _vistasVivas = new Map();\n" +
  'let ejeComparacion = "distancia";\n' +
  'let alcanceComparacion = "una";\n' +
  "let zoom = null;\n" +
  "let modoDetalle = true;\n" +
  constante("ZONA_MINIMA_PX") + "\n" + constante("ZONA_CON_ROTULO_PX") + "\n" +
  "const _fijar = { eje: v => { ejeComparacion = v; }," +
  "  alcance: v => { alcanceComparacion = v; }," +
  "  curvas: v => { CURVAS = v; }," +
  "  pista: v => { PISTA = v; }," +
  "  zoom: v => { zoom = v; }," +
  "  detalle: v => { modoDetalle = v; },\n};\n" +
  NOMBRES.map(extraer).join("\n\n") +
  "\nreturn Object.assign({ " + NOMBRES.concat(CONSTANTES).join(", ") + " }, {" +
  /* Dos ganchos sobre el estado de modulo. Las variables del preludio son
     `let` dentro del ambito de la funcion construida: escribirlas desde afuera
     con `globalThis` no las toca, y leerlas asi devuelve otra cosa. */
  "  rutasPedidas: () => { const r = _rutas; _rutas = []; return r; }," +
  "  fijarContextoDeCorrida: v => { _contextoDeCorrida = v; }," +
  "  _enUnidad," +
  "  selloDeIdentidad: () => _selloDeIdentidad," +
  "  _fijar," +
  "});")();

const {
  textoSeguro, identidadDeVehiculo, anotarParrillas, parrillaVigente,
  loQueSeSabeDelVehiculo, faltanVehiculosPorAprender, nombreCortoDeVehiculo,
  muestrasQueAporta, idsParaComparar, sePuedeComparar,
  poblarPropio,
  renombrarAutos, armarAutos, tintaDeVehiculo,
  secundarioDeVehiculo, vehiculosConTelemetriaGuardada, autoPropio,
  camposDeIdentidad, quienConduce,
  unidadDeCanal, sinCambiosEnElTramo,
  divisorDeUnidad, unidadDeclaradaDe, divisorDePresentacion,
  estaEnLaUnidadQueSeMuestra, serieCrudaDeCanal, trazarSerie, _cruzaUnHueco, huecosDeLaSerie,
  huecoDeLaSerie, comoSeVeElFlujo, huecoQueContiene, _enUnidad,
  serieDeCanal, serieAcumuladaDeCanal,
  tiempoDeVuelta, diferenciaEnSegundos, esCanalEscalonado, serieTemporal,
  valorEscalonadoEn, valorContinuoEn, calcularInstante,
  reservaDeArriba, encuadrarTrazado, metroDeCurva, zonasDeCurva,
  partirEnRenglones, vistaDeComparacion, segmentosComparacion,
  nombreDeLaLamina, pieDeExportacion, exportarComparacion,
  bandasDeVuelta, bandasParaElTramo, pintarZonas,
  pintarLeyendaTraza, exportarCsv,
  elegirCorrida, nuevaSesionEnCurso, fijarContextoDeCorrida, selloDeIdentidad,
  sonUnaSolaCarrera, parrillaComun, huecosEnLaLinea, comoSeLeeElHueco,
  _fijar,
  trazadoAPath, puntoDelBusEn, _indiceEnElRecorrido,
  hayCoordenadasMedidas, porQueNoHayCoordenadas, hayEjeDeDistancia,
  ejeQueLaFuenteSostiene, porQueNoHayDistancia, hayVueltas,
  ejeVigente, motivoDelEjeEspacial, coberturaDeLaVista,
  explicacionDelTrazado,
  textoDeLaValidacion,
  claveDeSesionOpenF1, parrillaDesdePilotos,
  pedirTrazado, rutasPedidas,
  tramoDeLaVuelta,
  senalesParaElRecorrido,
  pieDelRecorrido,
  extremosDeLaTraza, _rgbDe,
  nombreDeSenal,
  panelEstaPresente,
  renglonesDelPanelG,
  escalaDelDiagramaG,
  escalaDeLaVuelta, puntoDelDiagramaG,
  cifra,
  COORDENADAS_POR_FUENTE, EJE_DE_DISTANCIA_POR_FUENTE,
  valoresSobreElRecorrido, tramosDelRecorrido, tintaDelValor,
  UNIDAD_QUE_MUESTRA_EL_TABLERO, MARGEN_DEL_TRAZADO, ALTURA_DEL_ROTULO,
  CUERPO_DEL_ROTULO, METRICAS, TRAMOS_DE_LA_TRAZA,
  FUENTES: FUENTES_REALES,
  CANALES_POR_FUENTE,
  PASOS_DE_LA_ESCALA_G, CENTRO_DEL_DIAGRAMA_G, RADIO_DEL_DIAGRAMA_G,

  MUESTRAS_PARA_CONTRASTAR, CORRELACION_QUE_CONVENCE,
} = sacadas;

globalThis.instante = () => calcularInstante();

let hechas = 0;
function prueba(titulo, fn) {
  try { fn(); hechas++; }
  catch (e) {
    process.exitCode = 1;
    console.error("FALLA  " + titulo + "\n       " + (e && e.message));
  }
}

// ------------------------------------------------------------------ utilidad

const SESION = "f1_25:session:3731090176871608020";
const CAR19 = SESION + ":car:19";
const T0 = Date.parse("2026-09-05T00:38:00.000Z");
const iso = ms => new Date(ms).toISOString();

/* La parrilla tal como la devuelve `/sesiones/{id}/adquisiciones`. */
function parrillaDeSpa(extra) {
  return Object.assign({
    disponible: true,
    con_telemetria: 1,
    vehiculos_en_carrera: 20,
    origen: "metadato de captura, derivado del paquete de participantes",
    vehiculos: [
      { indice: 0, vehicle_id: SESION + ":car:0", nombre: "PIASTRI",
        numero: 81, equipo: "McLaren", es_ia: true, con_telemetria: false },
      { indice: 19, vehicle_id: CAR19, nombre: "NORRIS",
        numero: 4, equipo: "McLaren", es_ia: false, con_telemetria: true },
    ],
  }, extra || {});
}

function reiniciar() {
  globalThis.estado = { series: {}, posiciones: {}, vueltas: [],
                        abierta: { session_id: SESION, fuente: "f1_25_udp_simulation" },
                        puesta: null, vehiculoClave: CAR19 };
  anotarParrillas(null, []);
  globalThis.corrida = { adquisicion: "original", fase: 3, disponibles: null, mezclada: false };
  globalThis.AUTOS = [];
  globalThis.vivo = nuevoVivo();
  globalThis.estadoSesion = "cargado";
  globalThis._selloSeries++;
  globalThis.cabezal = 0;
  globalThis.fuente = "f1";
}

/* Deja la parrilla como la deja el tablero: por la respuesta de
   `/adquisiciones`, con su sesion y su adquisicion. No se asigna a mano la
   variable de modulo, que es justamente lo que ocultaba el ciclo de vida. */
function ponerParrilla(parrilla, clave) {
  anotarParrillas(SESION, [{ clave: clave || "original", parrilla: parrilla }]);
}

/* Una vuelta como la entrega `/series`, con su mapa de unidades tal cual llega
   ---en milisegundos--- para que la conversion sea la de produccion. */
function cargarVuelta(numero, marcas, columnas, unidades) {
  const veh = { timestamp_utc: marcas.map(m => iso(T0 + m)) };
  Object.keys(columnas).forEach(c => { veh[c] = columnas[c]; });
  const bloque = {
    vuelta: numero, puntos_pedidos: 600,
    vehiculos: { [CAR19]: veh },
    unidades: Object.assign({ speed: "km/h", lap_distance: "m" }, unidades || {}),
  };
  globalThis.estado.series[numero] = bloque;
  globalThis._selloSeries++;
  return bloque;
}

/* Dos vueltas seguidas de Spa a escala: veinte muestras cada 100 ms, el
   cronometro del juego corriendo con ellas y reiniciando en la meta. */
function dosVueltasConCronometro() {
  reiniciar();
  ponerParrilla(parrillaDeSpa());
  for (const v of [1, 2]) {
    const marcas = [], dist = [], vel = [], crono = [], puesto = [], gap = [];
    for (let i = 0; i < 20; i++) {
      marcas.push((v - 1) * 2000 + i * 100);
      dist.push(i * 5);
      vel.push(200 + i);
      crono.push(i * 100 + 16);                  // ms, reinicia en cada vuelta
      puesto.push(i < 10 ? 5 : 4);               // adelanta a la mitad
      gap.push(i < 10 ? 2653 : 2336);            // ms, en escalon
    }
    cargarVuelta(v, marcas, {
      distancia_m: dist, speed: vel, current_lap_time: crono,
      track_position_order: puesto, delta_to_race_leader: gap,
    }, { current_lap_time: "ms", track_position_order: "position",
         delta_to_race_leader: "ms" });
  }
  globalThis.estado.vueltas = [
    { numero: 1, duracion_s: 1.9, desde_utc: iso(T0), hasta_utc: iso(T0 + 1900) },
    { numero: 2, duracion_s: 1.9, desde_utc: iso(T0 + 2000), hasta_utc: iso(T0 + 3900) },
  ];
  armarAutos([CAR19]);
}

/* ==================================================================
   1. LA IDENTIDAD SALE DEL METADATO, NO DEL SUFIJO DE LA CLAVE
   ================================================================== */

prueba("el vehiculo 19 de Spa es NORRIS, numero 4, McLaren", () => {
  reiniciar();
  ponerParrilla(parrillaDeSpa());
  const q = identidadDeVehiculo(CAR19);
  assert.strictEqual(q.nombre, "NORRIS");
  assert.strictEqual(q.numero, 4);
  assert.strictEqual(q.equipo, "McLaren");
  assert.strictEqual(q.esIA, false);
  assert.strictEqual(q.completa, "NORRIS · #4 · McLaren");
  assert.strictEqual(q.declarada, true);
});

prueba("la clave tecnica no cambia al ponerle nombre", () => {
  /* El defecto contrario del que se corrige: renombrar tocando la clave
     rompería la seleccion, las caches y las peticiones. */
  reiniciar();
  ponerParrilla(parrillaDeSpa());
  armarAutos([CAR19]);
  assert.strictEqual(globalThis.AUTOS[0].id, CAR19);
  assert.strictEqual(globalThis.AUTOS[0].nombre, "NORRIS");
  assert.strictEqual(globalThis.AUTOS[0].indiceInterno, "19");
});

prueba("la etiqueta de la pista son tres letras y el titulo la identidad entera", () => {
  reiniciar();
  ponerParrilla(parrillaDeSpa());
  const q = identidadDeVehiculo(CAR19);
  assert.strictEqual(q.etiqueta, "NOR");
  assert.strictEqual(q.completa, "NORRIS · #4 · McLaren");
});

prueba("un nombre mas corto que tres letras va entero", () => {
  reiniciar();
  ponerParrilla(parrillaDeSpa({ vehiculos: [
    { indice: 19, vehicle_id: CAR19, nombre: "HO", numero: 7, equipo: "Alpine",
      es_ia: false, con_telemetria: true }] }));
  assert.strictEqual(identidadDeVehiculo(CAR19).etiqueta, "HO");
});

prueba("sin metadato el respaldo dice que es un indice, no un numero de carrera", () => {
  reiniciar();
  const q = identidadDeVehiculo(CAR19);
  assert.strictEqual(q.nombre, "Vehículo 19");
  assert.strictEqual(q.numero, null, "un indice no se presenta como dorsal");
  assert.strictEqual(q.declarada, false);
  assert.ok(/índice interno/.test(q.completa), q.completa);
});

prueba("otra captura con el mismo indice no hereda el nombre", () => {
  /* El indice es la posicion del vehiculo en el paquete de **esa** sesion: que
     dos capturas tengan un `car:19` no las relaciona. */
  reiniciar();
  ponerParrilla(parrillaDeSpa());
  const otra = "f1_25:session:999:car:19";
  assert.strictEqual(identidadDeVehiculo(otra).nombre, "Vehículo 19");
  assert.strictEqual(identidadDeVehiculo(otra).declarada, false);
  assert.strictEqual(identidadDeVehiculo(CAR19).nombre, "NORRIS");
});

prueba("una parrilla que la API declara no disponible no nombra a nadie", () => {
  reiniciar();
  ponerParrilla({ disponible: false, motivo: "ninguna captura cerrada la declara" });
  assert.strictEqual(parrillaVigente(), null);
  assert.strictEqual(identidadDeVehiculo(CAR19).nombre, "Vehículo 19");
});

prueba("un participante sin nombre cae al respaldo y no a una cadena vacia", () => {
  reiniciar();
  ponerParrilla(parrillaDeSpa({ vehiculos: [
    { indice: 19, vehicle_id: CAR19, nombre: "", numero: 4, equipo: "McLaren",
      es_ia: false, con_telemetria: true }] }));
  assert.strictEqual(identidadDeVehiculo(CAR19).nombre, "Vehículo 19");
});

prueba("un nombre con marcado se escribe, no se interpreta", () => {
  const suelto = '<img src=x onerror="alerta()"> O\'BRIEN & <b>';
  const seguro = textoSeguro(suelto);
  assert.ok(seguro.indexOf("<") === -1, seguro);
  assert.ok(seguro.indexOf(">") === -1, seguro);
  assert.ok(seguro.indexOf('"') === -1, seguro);
  assert.ok(seguro.indexOf("'") === -1, seguro);
  assert.ok(seguro.indexOf("&lt;img") !== -1, seguro);
  assert.ok(seguro.indexOf("O&#39;BRIEN") !== -1, seguro);
  // El ampersand del propio nombre se escapa una vez y no dos.
  assert.ok(seguro.indexOf("&amp;amp;") === -1, seguro);
});

prueba("el nombre con marcado llega intacto al modelo y se escapa al mostrarlo", () => {
  /* Escapar en el modelo romperia la comparacion y el titulo accesible: se
     conserva el texto medido y se escapa en el borde de la presentacion. */
  reiniciar();
  ponerParrilla(parrillaDeSpa({ vehiculos: [
    { indice: 19, vehicle_id: CAR19, nombre: "<b>X</b>", numero: 1,
      equipo: "Equipo & Cia", es_ia: false, con_telemetria: true }] }));
  const q = identidadDeVehiculo(CAR19);
  assert.strictEqual(q.nombre, "<b>X</b>");
  assert.strictEqual(textoSeguro(q.equipo), "Equipo &amp; Cia");
});

prueba("la identidad que llega tarde renombra sin tocar claves ni propio", () => {
  reiniciar();
  armarAutos([CAR19]);
  assert.strictEqual(globalThis.AUTOS[0].nombre, "Vehículo 19");
  const antesId = globalThis.AUTOS[0].id;
  const antesPropio = globalThis.AUTOS[0].propio;
  const selloAntes = selloDeIdentidad();

  ponerParrilla(parrillaDeSpa());
  assert.strictEqual(renombrarAutos(), true);
  assert.strictEqual(globalThis.AUTOS[0].nombre, "NORRIS");
  assert.strictEqual(globalThis.AUTOS[0].numero, 4);
  assert.strictEqual(globalThis.AUTOS[0].id, antesId, "la clave tecnica cambio");
  assert.strictEqual(globalThis.AUTOS[0].propio, antesPropio);
  assert.ok(selloDeIdentidad() > selloAntes,
            "el sello no subio: las marcas ya dibujadas no se rehacen");
});

prueba("renombrar dos veces con la misma parrilla no declara un cambio", () => {
  reiniciar();
  ponerParrilla(parrillaDeSpa());
  armarAutos([CAR19]);
  const sello = selloDeIdentidad();
  assert.strictEqual(renombrarAutos(), false);
  assert.strictEqual(selloDeIdentidad(), sello);
});

prueba("la identidad que llega tarde no mueve el cabezal ni las series", () => {
  dosVueltasConCronometro();
  globalThis.PARRILLAS = null;
globalThis.corrida = { adquisicion: null, fase: null, disponibles: null, mezclada: false };
  armarAutos([CAR19]);
  globalThis.cabezal = 0.37;
  const antes = JSON.stringify(calcularInstante());
  const seriesAntes = globalThis.estado.series[1].vehiculos[CAR19].speed.slice();
  ponerParrilla(parrillaDeSpa());
  renombrarAutos();
  assert.strictEqual(globalThis.cabezal, 0.37);
  assert.strictEqual(JSON.stringify(calcularInstante()), antes);
  assert.deepStrictEqual(globalThis.estado.series[1].vehiculos[CAR19].speed, seriesAntes);
});

/* ==================================================================
   2. IDENTIDAD, COBERTURA Y PUESTO SON TRES COSAS
   ================================================================== */

prueba("un solo vehiculo con telemetria no es una sesion sin parrilla", () => {
  reiniciar();
  ponerParrilla(parrillaDeSpa());
  armarAutos([CAR19]);
  assert.strictEqual(globalThis.AUTOS.length, 1);
  assert.strictEqual(parrillaVigente().vehiculos.length, 20 - 18,
                     "el ejemplar de prueba trae dos participantes");
  assert.strictEqual(vehiculosConTelemetriaGuardada(), 1);
});

prueba("la cobertura la declara la API y no el largo de la lista dibujada", () => {
  reiniciar();
  ponerParrilla(parrillaDeSpa({ con_telemetria: 2 }));
  armarAutos([CAR19]);
  assert.strictEqual(vehiculosConTelemetriaGuardada(), 2,
                     "se conto lo que hay en pantalla y no lo que hay guardado");
});

prueba("sin parrilla la cobertura cae en lo unico que se sabe", () => {
  reiniciar();
  armarAutos([CAR19, SESION + ":car:0"]);
  assert.strictEqual(vehiculosConTelemetriaGuardada(), 2);
});

prueba("el equipo es identidad y lo que aporta el vehiculo es otra cosa", () => {
  reiniciar();
  ponerParrilla(parrillaDeSpa());
  armarAutos([CAR19]);
  const a = globalThis.AUTOS[0];
  assert.strictEqual(a.equipo, "McLaren");
  assert.strictEqual(a.aporta, "telemetría completa");
  assert.strictEqual(secundarioDeVehiculo(a), "McLaren");
});

prueba("sin equipo declarado, debajo del nombre se dice lo que aporta", () => {
  reiniciar();
  armarAutos([CAR19]);
  assert.strictEqual(secundarioDeVehiculo(globalThis.AUTOS[0]), "telemetría completa");
});

prueba("el puesto es discreto: no hay un P4,5", () => {
  assert.strictEqual(esCanalEscalonado("posicion"), true);
  dosVueltasConCronometro();
  const st = serieTemporal("posicion", 1, CAR19);
  // Entre la muestra 9 (P5) y la 10 (P4) no hay nada en el medio.
  assert.strictEqual(valorEscalonadoEn(st, T0 + 950), 5);
  assert.strictEqual(valorEscalonadoEn(st, T0 + 1000), 4);
  for (let t = 900; t <= 1000; t += 5) {
    const v = valorEscalonadoEn(st, T0 + t);
    assert.ok(v === 4 || v === 5, "puesto intermedio " + v + " en " + t);
  }
});

prueba("antes de la primera muestra no hay puesto, y no es P0", () => {
  dosVueltasConCronometro();
  const st = serieTemporal("posicion", 1, CAR19);
  assert.strictEqual(valorEscalonadoEn(st, T0 - 1), null);
});

prueba("el puesto no se anticipa a la observacion que lo declara", () => {
  /* Con el redondeo por indice el cambio se adelantaba medio intervalo: el
     adelantamiento se veia antes de que el dato dijera que ocurrio. */
  dosVueltasConCronometro();
  const st = serieTemporal("posicion", 1, CAR19);
  assert.strictEqual(valorEscalonadoEn(st, T0 + 999), 5);
});

prueba("un puesto nulo no se rellena con el de al lado en la serie", () => {
  reiniciar();
  cargarVuelta(1, [0, 100, 200],
               { distancia_m: [0, 5, 10], track_position_order: [3, null, 3] },
               { track_position_order: "position" });
  const st = serieTemporal("posicion", 1, CAR19);
  assert.deepStrictEqual(st.t.map(t => t - T0), [0, 200],
                         "el nulo entro a la serie como un valor");
});

/* ==================================================================
   3. LAS UNIDADES: UNA POLITICA, Y NO SE TOCA LO QUE LLEGO
   ================================================================== */

/* Un vehiculo vivo con su ultimo mensaje de cada senal, como lo guarda el
   flujo: el mensaje entero, con su unidad. */
function vivoCon(mensajes) {
  reiniciar();
  globalThis.estadoSesion = "vivo";
  const ultimos = new Map();
  const series = new Map();
  Object.keys(mensajes).forEach(senal => {
    const m = mensajes[senal];
    ultimos.set(senal, m);
    series.set(senal, [[0, m.value, 0], [10, m.value, 10]]);
  });
  globalThis.vivo.ultimos.set(CAR19, ultimos);
  globalThis.vivo.series.set(CAR19, series);
  globalThis.vivo.vuelta.set(CAR19, 1);
  globalThis.vivo.distancia.set(CAR19, 10);
}

prueba("la diferencia al lider viene en milisegundos y se muestra en segundos", () => {
  assert.strictEqual(UNIDAD_QUE_MUESTRA_EL_TABLERO.delta_to_race_leader, "s");
  assert.strictEqual(divisorDeUnidad("delta_to_race_leader", "ms"), 1000);
});

prueba("dividir por mil y no multiplicar por milesimas: la cola se ve", () => {
  /* `2937 * 0.001` es 2,9370000000000003 en coma flotante binaria. */
  reiniciar();
  cargarVuelta(1, [0, 100], { distancia_m: [0, 5], delta_to_race_leader: [2937, 2937] },
               { delta_to_race_leader: "ms" });
  assert.strictEqual(serieDeCanal("gap", 1, CAR19)[0][1], 2.937);
});

/* ---- el vivo se resuelve con sus mensajes, sin bloque historico ---- */

prueba("en vivo sin historico, 2937 ms se leen como 2,937 s", () => {
  /* EL DEFECTO. `calcularInstante` convertia bien y el panel preguntaba
     «¿esta en segundos?» a `estado.series`, que en vivo esta vacio: contestaba
     que no y escribia una raya sobre un valor correcto. */
  vivoCon({ delta_to_race_leader: { value: 2937, unit: "ms" },
            speed: { value: 210, unit: "km/h" } });
  assert.deepStrictEqual(globalThis.estado.series, {}, "el vivo no tiene bloque");
  const t = calcularInstante();
  assert.strictEqual(t.diferencia, 2.937);
  assert.strictEqual(estaEnLaUnidadQueSeMuestra("gap", null, CAR19), true);
  assert.strictEqual(diferenciaEnSegundos(t.diferencia), "+2,937");
});

prueba("en vivo el grafico tambien va en segundos, no en milisegundos", () => {
  /* El grafico no preguntaba nada y dibujaba los 2.937 crudos bajo un eje que
     decia segundos. */
  vivoCon({ delta_to_race_leader: { value: 2937, unit: "ms" } });
  const serie = serieDeCanal("gap", null, CAR19);
  assert.ok(serie.length, "sin serie viva no hay nada que comprobar");
  serie.forEach(p => assert.strictEqual(p[1], 2.937, "el grafico quedo en ms"));
});

prueba("en vivo, una senal que ya viene en segundos no se divide", () => {
  vivoCon({ penalty_time: { value: 5, unit: "s" } });
  assert.strictEqual(divisorDePresentacion("penalty_time", null, CAR19), 1);
});

prueba("en vivo con unidad desconocida no se dibuja ni se lee un numero", () => {
  vivoCon({ delta_to_race_leader: { value: 2937000, unit: "us" } });
  assert.strictEqual(calcularInstante().diferencia, null);
  assert.deepStrictEqual(serieDeCanal("gap", null, CAR19), [],
                         "se dibujo bajo una unidad que no es la del rotulo");
  assert.strictEqual(estaEnLaUnidadQueSeMuestra("gap", null, CAR19), false);
});

prueba("en vivo sin unidad declarada tampoco se supone milisegundos", () => {
  vivoCon({ delta_to_race_leader: { value: 2937 } });
  assert.strictEqual(calcularInstante().diferencia, null);
  assert.strictEqual(unidadDeclaradaDe("delta_to_race_leader", null, CAR19), null);
});

prueba("la vista viva convertida no se rehace mientras no llegan muestras", () => {
  vivoCon({ delta_to_race_leader: { value: 2937, unit: "ms" } });
  const a = serieDeCanal("gap", null, CAR19);
  const b = serieDeCanal("gap", null, CAR19);
  assert.strictEqual(a, b, "se armo una copia por llamada");
});

prueba("la vista viva no toca la serie que guarda el flujo", () => {
  vivoCon({ delta_to_race_leader: { value: 2937, unit: "ms" } });
  serieDeCanal("gap", null, CAR19);
  const cruda = globalThis.vivo.series.get(CAR19).get("delta_to_race_leader");
  cruda.forEach(p => assert.strictEqual(p[1], 2937, "se muto lo que guarda el vivo"));
});

/* ---- el historico, con la misma politica ---- */

prueba("en historico, 2937 ms se leen igual que en vivo", () => {
  reiniciar();
  cargarVuelta(1, [0, 100], { distancia_m: [0, 5], delta_to_race_leader: [2937, 2937] },
               { delta_to_race_leader: "ms" });
  globalThis.estado.vueltas = [{ numero: 1, duracion_s: 0.1,
                                 desde_utc: iso(T0), hasta_utc: iso(T0 + 100) }];
  globalThis.cabezal = 0.5;
  assert.strictEqual(calcularInstante().diferencia, 2.937);
  assert.strictEqual(serieDeCanal("gap", 1, CAR19)[0][1], 2.937);
});

prueba("una senal que ya viene en segundos no se divide", () => {
  /* `penalty_time` y `safety_car_delta` viajan en la misma respuesta y estan en
     segundos: una lista de nombres escrita a mano los rompia. */
  reiniciar();
  cargarVuelta(1, [0, 100], { distancia_m: [0, 5], penalty_time: [5, 5] },
               { penalty_time: "s" });
  assert.strictEqual(divisorDePresentacion("penalty_time", 1, CAR19), 1);
  assert.deepStrictEqual(serieDeCanal("penalty_time", 1, CAR19).map(x => x[1]), [5, 5]);
  assert.deepStrictEqual(serieCrudaDeCanal("penalty_time", 1, CAR19).map(x => x[1]), [5, 5]);
});

prueba("con unidad desconocida no se dibuja el numero bajo la unidad del rotulo", () => {
  /* EL DEFECTO. El panel rechazaba el valor y los graficos y la comparacion lo
     dibujaban igual, bajo la unidad fija que declara `METRICAS`. */
  reiniciar();
  cargarVuelta(1, [0, 100], { distancia_m: [0, 5], delta_to_race_leader: [2937000, 2937000] },
               { delta_to_race_leader: "us" });
  globalThis.estado.vueltas = [{ numero: 1, duracion_s: 0.1,
                                 desde_utc: iso(T0), hasta_utc: iso(T0 + 100) }];
  globalThis.cabezal = 0.5;
  assert.strictEqual(estaEnLaUnidadQueSeMuestra("gap", 1, CAR19), false);
  assert.deepStrictEqual(serieDeCanal("gap", 1, CAR19), []);
  assert.strictEqual(serieTemporal("gap", 1, CAR19), null);
  assert.strictEqual(calcularInstante().diferencia, null);
  // Y lo crudo sigue estando, que es lo que exporta el CSV.
  assert.strictEqual(serieCrudaDeCanal("gap", 1, CAR19)[0][1], 2937000);
});

prueba("sin unidad declarada no se supone que este en milisegundos", () => {
  reiniciar();
  cargarVuelta(1, [0, 100], { distancia_m: [0, 5], delta_to_race_leader: [2937, 2937] }, {});
  assert.strictEqual(unidadDeclaradaDe("delta_to_race_leader", 1, CAR19), null);
  assert.strictEqual(divisorDePresentacion("gap", 1, CAR19), null);
  assert.deepStrictEqual(serieDeCanal("gap", 1, CAR19), []);
});

/* ---- exactamente una vez, y sin tocar lo que llego ---- */

prueba("mostrar, comparar y releer no convierten dos veces", () => {
  reiniciar();
  cargarVuelta(1, [0, 100, 200],
               { distancia_m: [0, 5, 10], delta_to_race_leader: [2937, 2937, 2937] },
               { delta_to_race_leader: "ms" });
  globalThis.estado.vueltas = [{ numero: 1, duracion_s: 0.2,
                                 desde_utc: iso(T0), hasta_utc: iso(T0 + 200) }];
  for (let i = 0; i < 5; i++) {
    serieDeCanal("gap", 1, CAR19);
    serieAcumuladaDeCanal("gap", 1, CAR19);
    serieTemporal("gap", 1, CAR19);
    globalThis.cabezal = i / 10; calcularInstante();
  }
  serieDeCanal("gap", 1, CAR19).forEach(p => assert.strictEqual(p[1], 2.937));
  assert.strictEqual(serieTemporal("gap", 1, CAR19).v[0], 2.937);
});

prueba("lo que llego no se toca: ni valores ni unidades declaradas", () => {
  /* Es la raiz de los tres sintomas: convertir el bloque guardado cambiaba lo
     que se exporta y dejaba al vivo sin con que comparar. */
  reiniciar();
  cargarVuelta(1, [0, 100], { distancia_m: [0, 5], delta_to_race_leader: [2937, 2986] },
               { delta_to_race_leader: "ms" });
  globalThis.estado.vueltas = [{ numero: 1, duracion_s: 0.1,
                                 desde_utc: iso(T0), hasta_utc: iso(T0 + 100) }];
  globalThis.cabezal = 0.5;
  calcularInstante();
  serieDeCanal("gap", 1, CAR19);
  serieAcumuladaDeCanal("gap", 1, CAR19);
  const veh = globalThis.estado.series[1].vehiculos[CAR19];
  assert.deepStrictEqual(veh.delta_to_race_leader, [2937, 2986]);
  assert.strictEqual(globalThis.estado.series[1].unidades.delta_to_race_leader, "ms");
});

prueba("la serie cruda y la de presentacion no comparten casillero", () => {
  reiniciar();
  cargarVuelta(1, [0, 100], { distancia_m: [0, 5], delta_to_race_leader: [2937, 2937] },
               { delta_to_race_leader: "ms" });
  assert.strictEqual(serieCrudaDeCanal("gap", 1, CAR19)[0][1], 2937);
  assert.strictEqual(serieDeCanal("gap", 1, CAR19)[0][1], 2.937);
  assert.strictEqual(serieCrudaDeCanal("gap", 1, CAR19)[0][1], 2937,
                     "la cruda quedo pisada por la de presentacion");
});

prueba("los nulos no se convierten en ceros al cambiar de unidad", () => {
  reiniciar();
  cargarVuelta(1, [0, 100, 200, 300],
               { distancia_m: [0, 5, 10, 15],
                 delta_to_race_leader: [1000, null, 3000, undefined] },
               { delta_to_race_leader: "ms" });
  const v = serieDeCanal("gap", 1, CAR19);
  assert.deepStrictEqual(v.map(x => x[1]), [1, 3], "un nulo entro como cero");
});

prueba("la conversion alcanza a todos los vehiculos", () => {
  const otro = SESION + ":car:0";
  reiniciar();
  cargarVuelta(1, [0, 100], { distancia_m: [0, 5], delta_to_race_leader: [2937, 2937] },
               { delta_to_race_leader: "ms" });
  globalThis.estado.series[1].vehiculos[otro] =
    { timestamp_utc: [iso(T0), iso(T0 + 100)], distancia_m: [0, 5],
      delta_to_race_leader: [1000, 1000] };
  globalThis._selloSeries++;
  assert.strictEqual(serieDeCanal("gap", 1, otro)[0][1], 1);
});

prueba("mientras no haya bloque no se afirma la unidad", () => {
  reiniciar();
  assert.strictEqual(unidadDeclaradaDe("delta_to_race_leader", 1, CAR19), null);
  assert.strictEqual(estaEnLaUnidadQueSeMuestra("gap", 1, CAR19), false);
});

prueba("con el bloque cargado la unidad de la diferencia es la que se muestra", () => {
  dosVueltasConCronometro();
  assert.strictEqual(unidadDeclaradaDe("delta_to_race_leader", 1, CAR19), "ms");
  assert.strictEqual(estaEnLaUnidadQueSeMuestra("gap", 1, CAR19), true);
  assert.strictEqual(estaEnLaUnidadQueSeMuestra("speed", 1, CAR19), true,
                     "una senal que se muestra como viene siempre esta en su unidad");
});

/* ==================================================================
   4. EL FORMATO DICE LA UNIDAD, Y DISTINGUE EL CERO DE LA AUSENCIA
   ================================================================== */

prueba("136.153 ms se leen 2:16,153", () => {
  assert.strictEqual(tiempoDeVuelta(136.153), "2:16,153");
});

prueba("un tiempo de menos de un minuto lleva su cero", () => {
  assert.strictEqual(tiempoDeVuelta(55.113), "0:55,113");
  assert.strictEqual(tiempoDeVuelta(9.5), "0:09,500");
  assert.strictEqual(tiempoDeVuelta(0), "0:00,000");
});

prueba("2.937 ms son +2,937 s y 65.000 ms son +65,000 s", () => {
  assert.strictEqual(diferenciaEnSegundos(2.937), "+2,937");
  assert.strictEqual(diferenciaEnSegundos(65), "+65,000");
});

prueba("el cero valido se escribe, y la ausencia es otra cosa", () => {
  assert.strictEqual(diferenciaEnSegundos(0), "+0,000");
  assert.strictEqual(diferenciaEnSegundos(null), null);
  assert.strictEqual(diferenciaEnSegundos(undefined), null);
  assert.strictEqual(diferenciaEnSegundos(NaN), null);
  assert.strictEqual(tiempoDeVuelta(null), null);
});

prueba("una diferencia negativa lleva el signo menos, no un guion", () => {
  assert.strictEqual(diferenciaEnSegundos(-1.075), "−1,075");
});

prueba("un milisegundo no se pierde al redondear", () => {
  assert.strictEqual(diferenciaEnSegundos(0.001), "+0,001");
  assert.strictEqual(tiempoDeVuelta(59.999), "0:59,999");
  assert.strictEqual(tiempoDeVuelta(60), "1:00,000");
});

/* ==================================================================
   5. EL CRONOMETRO MEDIDO, RESUELTO EN EL INSTANTE COMPARTIDO
   ================================================================== */

prueba("el cronometro sale de la senal y no de la fraccion del cabezal", () => {
  dosVueltasConCronometro();
  globalThis.cabezal = 0.25;                       // mitad de la vuelta 1
  const t = calcularInstante();
  assert.strictEqual(t.vuelta, 1);
  assert.strictEqual(t.cronometroMedido, true);
  /* La senal dice 16 ms en la primera muestra y sube 100 por muestra: a la
     mitad de la vuelta vale 0,966 s, no `0,5 x 1,9 = 0,95`. */
  assert.ok(Math.abs(t.cronometroS - 0.966) < 0.02,
            "cronometro " + t.cronometroS);
  assert.notStrictEqual(+t.cronometroS.toFixed(3), +(t.fraccion * 1.9).toFixed(3));
});

prueba("el cronometro se lee en el mismo instante que todo lo demas", () => {
  dosVueltasConCronometro();
  globalThis.cabezal = 0.31;
  const t = calcularInstante();
  const st = serieTemporal("cronometro", t.vuelta, CAR19);
  assert.strictEqual(t.cronometroS, valorContinuoEn(st, t.tUtcMs));
});

prueba("al cruzar la meta el cronometro reinicia y no interpola el salto", () => {
  dosVueltasConCronometro();
  let previo = null, retrocesosDentro = 0, vueltaPrevia = null, hayReinicio = false;
  for (let k = 0; k <= 400; k++) {
    globalThis.cabezal = k / 400;
    const t = calcularInstante();
    if (t.cronometroS === null) continue;
    if (vueltaPrevia === t.vuelta && previo !== null && t.cronometroS < previo) {
      retrocesosDentro++;
    }
    if (vueltaPrevia !== null && vueltaPrevia !== t.vuelta) {
      hayReinicio = true;
      assert.ok(t.cronometroS < 0.2,
                "la vuelta nueva arranca en " + t.cronometroS + " s");
    }
    previo = t.cronometroS; vueltaPrevia = t.vuelta;
  }
  assert.ok(hayReinicio, "no se llego a cruzar la meta");
  assert.strictEqual(retrocesosDentro, 0);
});

prueba("el cronometro no se interpola a traves de un hueco de captura", () => {
  reiniciar();
  cargarVuelta(1, [0, 100, 3100, 3200],
               { distancia_m: [0, 5, 10, 15],
                 current_lap_time: [0, 100, 3100, 3200] },
               { current_lap_time: "ms" });
  globalThis.estado.vueltas = [{
    numero: 1, duracion_s: 0.2, desde_utc: iso(T0), hasta_utc: iso(T0 + 3200),
    huecos: [{ desde_utc: iso(T0 + 100), hasta_utc: iso(T0 + 3100), duracion_s: 3 }],
  }];
  const st = serieTemporal("cronometro", 1, CAR19);
  // Dentro del corte se sostiene la ultima medida, no se traza una recta.
  assert.strictEqual(valorContinuoEn(st, T0 + 1600), 0.1);
  assert.strictEqual(valorContinuoEn(st, T0 + 3100), 3.1);
});

prueba("pausa y seek dan el mismo cronometro para el mismo cabezal", () => {
  dosVueltasConCronometro();
  globalThis.cabezal = 0.62;
  const a = calcularInstante();
  globalThis.cabezal = 0.05;
  calcularInstante();
  globalThis.cabezal = 0.62;
  const b = calcularInstante();
  assert.strictEqual(a.cronometroS, b.cronometroS);
  assert.strictEqual(a.posicion, b.posicion);
  assert.strictEqual(a.diferencia, b.diferencia);
  assert.strictEqual(a.tUtcMs, b.tUtcMs);
});

prueba("sin la senal del cronometro el instante lo declara ausente", () => {
  reiniciar();
  cargarVuelta(1, [0, 100, 200], { distancia_m: [0, 5, 10], speed: [200, 201, 202] });
  globalThis.estado.vueltas = [{ numero: 1, duracion_s: 0.2,
                                 desde_utc: iso(T0), hasta_utc: iso(T0 + 200) }];
  globalThis.cabezal = 0.5;
  const t = calcularInstante();
  assert.strictEqual(t.cronometroS, null);
  assert.strictEqual(t.cronometroMedido, false,
                     "sin unidad declarada no se puede afirmar que sea el medido");
});

/* ==================================================================
   6. LA DIFERENCIA AL LIDER, EN EL INSTANTE Y EN SU UNIDAD
   ================================================================== */

prueba("la diferencia se lee en segundos en el instante compartido", () => {
  dosVueltasConCronometro();
  globalThis.cabezal = 0.1;
  const t = calcularInstante();
  assert.strictEqual(t.diferencia, 2.653);
  assert.strictEqual(diferenciaEnSegundos(t.diferencia), "+2,653");
});

prueba("la diferencia al lider es un escalon y no se interpola", () => {
  /* Medido sobre la vuelta 1 de Spa a resolucion completa ---2.735 muestras sin
     submuestrear---: el canal cambia 80 veces y se sostiene entre cambios.
     Interpolar daba 2,721 s donde la fuente dice 2,653 durante todo el segundo
     que lo rodea. */
  assert.strictEqual(esCanalEscalonado("gap"), true);
  dosVueltasConCronometro();
  const st = serieTemporal("gap", 1, CAR19);
  for (let t = 900; t <= 1000; t += 5) {
    const v = valorEscalonadoEn(st, T0 + t);
    assert.ok(v === 2.653 || v === 2.336, "valor intermedio " + v);
  }
});

prueba("la diferencia no se confunde con la del coche de adelante", () => {
  const SENAL_DE = sacadas.SENAL_DE;
  assert.strictEqual(SENAL_DE.gap, "delta_to_race_leader");
  assert.notStrictEqual(SENAL_DE.gap, "delta_to_car_in_front");
  // Y las dos se declaran en la misma unidad, para que ninguna quede sin convertir.
  assert.strictEqual(UNIDAD_QUE_MUESTRA_EL_TABLERO.delta_to_car_in_front, "s");
});

prueba("cero de diferencia no se confunde con no tener diferencia", () => {
  reiniciar();
  cargarVuelta(1, [0, 100], { distancia_m: [0, 5], delta_to_race_leader: [0, 0] },
               { delta_to_race_leader: "ms" });
  globalThis.estado.vueltas = [{ numero: 1, duracion_s: 0.1,
                                 desde_utc: iso(T0), hasta_utc: iso(T0 + 100) }];
  globalThis.cabezal = 0.5;
  assert.strictEqual(calcularInstante().diferencia, 0);
  reiniciar();
  cargarVuelta(1, [0, 100], { distancia_m: [0, 5] });
  globalThis.estado.vueltas = [{ numero: 1, duracion_s: 0.1,
                                 desde_utc: iso(T0), hasta_utc: iso(T0 + 100) }];
  globalThis.cabezal = 0.5;
  assert.strictEqual(calcularInstante().diferencia, null);
});

/* ==================================================================
   7. LAS SENALES DE CRONOMETRAJE SE PIDEN, Y SIN AGREGAR GRAFICOS
   ================================================================== */

prueba("el cronometro y el puesto tienen nombre de contrato", () => {
  const SENAL_DE = sacadas.SENAL_DE;
  assert.strictEqual(SENAL_DE.cronometro, "current_lap_time");
  assert.strictEqual(SENAL_DE.posicion, "track_position_order");
});

prueba("las dos lecturas nuevas no entran en la lista de graficos", () => {
  const metricas = fuenteApp.slice(fuenteApp.indexOf("const METRICAS = ["),
                                   fuenteApp.indexOf("const SENAL_DE = {"));
  assert.ok(metricas.indexOf('id: "cronometro"') === -1,
            "el cronometro quedo como un grafico mas");
  assert.ok(metricas.indexOf('id: "posicion"') === -1,
            "el puesto quedo como un grafico mas");
});

/* ==================================================================
   8. EL NOMBRE NO SE CORTA EN EL TRAZADO
   ------------------------------------------------------------------
   EL DEFECTO. El `viewBox` se encuadraba con el mismo margen en los cuatro
   lados, y arriba tiene que caber ademas el rotulo del vehiculo: la marca lo
   lleva diez unidades por encima y la tinta sube otro tanto desde la linea
   base. Cada vez que el coche pasaba por el punto mas alto del circuito ---en
   Spa, la recta de Kemmel--- el nombre quedaba cortado por la mitad.

   Y el primer arreglo tampoco alcanzo: reservar `cuerpo x 0,8` ---la altura de
   las mayusculas--- se quedaba corto 2,25 unidades, porque la caja de un texto
   llega hasta la **ascendente** de la fuente. Por eso se mide.
   ================================================================== */

/* Un SVG de mentira con lo justo: `encuadrarTrazado` le pide el rotulo, le lee
   la caja al recorrido y le escribe el `viewBox`. */
function svgDePrueba(cajaDelRecorrido, rotulo) {
  const atributos = {};
  return {
    dataset: {},
    atributos: atributos,
    setAttribute: (k, v) => { atributos[k] = v; },
    getAttribute: k => atributos[k],
    querySelector: sel => (sel === ".auto-en-pista text" ? rotulo : null),
    linea: { getBBox: () => cajaDelRecorrido },
  };
}

/* Un rotulo cuya tinta sube `sube` por encima de su linea base. */
function rotuloEn(y, sube, ancho) {
  return {
    getAttribute: k => (k === "y" ? String(y) : null),
    getBBox: () => ({ x: -(ancho || 17) / 2, y: y - sube,
                      width: ancho || 17, height: sube + CUERPO_DEL_ROTULO * 0.28 }),
  };
}

function encuadrar(caja, rotulo) {
  const svg = svgDePrueba(caja, rotulo);
  sacadas._reiniciarAscendente ? sacadas._reiniciarAscendente() : null;
  encuadrarTrazado(svg, svg.linea);
  const vb = (svg.getAttribute("viewBox") || "").split(" ").map(Number);
  return { svg, x: vb[0], y: vb[1], ancho: vb[2], alto: vb[3] };
}

prueba("arriba se reserva mas que a los costados, y por el rotulo", () => {
  const caja = { x: 0, y: 0, width: 200, height: 100 };
  const e = encuadrar(caja, rotuloEn(-ALTURA_DEL_ROTULO, 9.66));
  const arriba = caja.y - e.y;
  const abajo = (e.y + e.alto) - (caja.y + caja.height);
  const lado = caja.x - e.x;
  assert.strictEqual(lado, MARGEN_DEL_TRAZADO);
  assert.strictEqual(abajo, MARGEN_DEL_TRAZADO);
  assert.ok(arriba > lado, "arriba se reservo lo mismo que a los costados: " + arriba);
});

prueba("el rotulo del coche en lo mas alto del circuito entra entero", () => {
  /* Es el caso exacto que se veia: el coche en el punto de menor `y` del
     recorrido, que es donde el rotulo se sale por arriba. */
  const caja = { x: 0, y: 0, width: 200, height: 100 };
  const sube = 9.66;                       // ascendente medida de IBM Plex Mono
  const rotulo = rotuloEn(caja.y - ALTURA_DEL_ROTULO, sube);
  const e = encuadrar(caja, rotulo);
  const cimaDeLaTinta = rotulo.getBBox().y;
  assert.ok(cimaDeLaTinta >= e.y,
            "el rotulo se sale " + (e.y - cimaDeLaTinta).toFixed(2) + " unidades");
});

prueba("reservar la altura de las mayusculas no alcanza, y por eso se mide", () => {
  /* Con `cuerpo x 0,8` la reserva daba 18 y hacian falta 20: el defecto que
     quedaba despues del primer arreglo. */
  const caja = { x: 0, y: 0, width: 200, height: 100 };
  const sube = 9.66;
  const conMedida = reservaDeArriba(svgDePrueba(caja, rotuloEn(-ALTURA_DEL_ROTULO, sube)));
  const suponiendoMayusculas = Math.ceil(ALTURA_DEL_ROTULO + CUERPO_DEL_ROTULO * 0.8);
  assert.ok(conMedida > suponiendoMayusculas,
            "la reserva medida (" + conMedida + ") no supera a la supuesta (" +
            suponiendoMayusculas + "): se volvio a deducirla del cuerpo de la letra");
  assert.ok(conMedida >= ALTURA_DEL_ROTULO + sube, "reserva " + conMedida);
});

prueba("sin un rotulo que medir todavia, la cota tampoco corta", () => {
  /* El primer cuadro se dibuja antes de que exista una marca. */
  const caja = { x: 0, y: 0, width: 200, height: 100 };
  const e = encuadrar(caja, null);
  const cimaDeLaTinta = caja.y - ALTURA_DEL_ROTULO - 9.66;
  assert.ok(cimaDeLaTinta >= e.y,
            "con la cota provisional el rotulo se sale " +
            (e.y - cimaDeLaTinta).toFixed(2));
});

prueba("no se reencuadra en cada cuadro", () => {
  /* Mover el `viewBox` sesenta veces por segundo hace temblar todo el dibujo. */
  const caja = { x: 0, y: 0, width: 200, height: 100 };
  const svg = svgDePrueba(caja, rotuloEn(-ALTURA_DEL_ROTULO, 9.66));
  let escrituras = 0;
  const real = svg.setAttribute;
  svg.setAttribute = (k, v) => { if (k === "viewBox") escrituras++; real(k, v); };
  for (let i = 0; i < 50; i++) encuadrarTrazado(svg, svg.linea);
  assert.strictEqual(escrituras, 1);
});

prueba("un recorrido sin caja no borra el encuadre que habia", () => {
  const svg = svgDePrueba({ x: 0, y: 0, width: 0, height: 0 }, null);
  encuadrarTrazado(svg, svg.linea);
  assert.strictEqual(svg.getAttribute("viewBox"), undefined);
  assert.strictEqual(svg.dataset.reserva, undefined);
});

/* ==================================================================
   9. EL NOMBRE ES UN DATO EN TODOS LOS RENDERIZADORES
   ------------------------------------------------------------------
   El panel de cronometraje lo escapaba y la leyenda del trazado no: seguia
   concatenandolo en `innerHTML`. Mientras `nombre` era «19» eso no podia ser
   otra cosa que digitos; desde que sale de la captura es texto que escribio
   otro. Se prueba **el renderizador de la leyenda**, no el ayudante de escape.
   ================================================================== */

const MALICIOSO = '<img src=x onerror="window.__nombreEjecutado=true">';

/* Un documento de mentira que recuerda lo que cada renderizador escribio. */
function documentoDePrueba() {
  const nodos = {};
  const nuevo = () => ({
    innerHTML: "", textContent: "", title: "", dataset: {},
    className: "", style: {},
    setAttribute(k, v) { this[k] = v; },
    removeAttribute(k) { delete this[k]; },
    querySelectorAll: () => [], closest: () => null,
  });
  globalThis.document = {
    getElementById: id => (nodos[id] = nodos[id] || nuevo()),
    querySelector: () => null,
    querySelectorAll: () => [],
    createElement: nuevo,
  };
  return nodos;
}

prueba("la leyenda del trazado escribe el nombre, no lo interpreta", () => {
  reiniciar();
  ponerParrilla(parrillaDeSpa({ vehiculos: [
    { indice: 19, vehicle_id: CAR19, nombre: MALICIOSO, numero: 4,
      equipo: "McLaren", es_ia: false, con_telemetria: true }] }));
  armarAutos([CAR19]);
  globalThis.seleccion = new Set([CAR19]);
  globalThis.contarCanales = () => {};
  const nodos = documentoDePrueba();
  pintarLeyendaTraza();
  const html = nodos["leyenda-traza"].innerHTML;
  assert.ok(html.indexOf("<img") === -1, "la leyenda crea un img: " + html);
  assert.ok(html.indexOf("onerror") === -1 || html.indexOf("&quot;") !== -1, html);
  assert.ok(html.indexOf("&lt;img") !== -1, "el nombre no llego literal: " + html);
  assert.strictEqual(globalThis.__nombreEjecutado, undefined);
});

prueba("la leyenda no altera el nombre que guarda el modelo", () => {
  /* Escapar en el dato para compensar un renderizador inseguro romperia la
     comparacion, el titulo accesible y el CSV. */
  assert.strictEqual(globalThis.AUTOS[0].nombre, MALICIOSO);
});

prueba("no se escapa dos veces", () => {
  reiniciar();
  ponerParrilla(parrillaDeSpa({ vehiculos: [
    { indice: 19, vehicle_id: CAR19, nombre: "A & B", numero: 1, equipo: "X",
      es_ia: null, con_telemetria: true }] }));
  armarAutos([CAR19]);
  globalThis.seleccion = new Set([CAR19]);
  globalThis.contarCanales = () => {};
  const nodos = documentoDePrueba();
  pintarLeyendaTraza();
  const html = nodos["leyenda-traza"].innerHTML;
  assert.ok(html.indexOf("A &amp; B") !== -1, html);
  assert.ok(html.indexOf("&amp;amp;") === -1, "se escapo dos veces: " + html);
});

/* ==================================================================
   10. IA, PERSONA Y NO DECLARADO SON TRES
   ------------------------------------------------------------------
   `identidadDeVehiculo` devolvia `esIA` y los dos copiadores no lo llevaban a
   `AUTOS`: el rotulo leia `undefined`, que no es `null`, y afirmaba «conducido
   por una persona» de un vehiculo del que el metadato no dice nada.
   ================================================================== */

function conControl(es_ia) {
  reiniciar();
  ponerParrilla(parrillaDeSpa({ vehiculos: [
    Object.assign({ indice: 19, vehicle_id: CAR19, nombre: "NORRIS", numero: 4,
                    equipo: "McLaren", con_telemetria: true },
                  es_ia === undefined ? {} : { es_ia: es_ia })] }));
  armarAutos([CAR19]);
  return autoPropio();
}

prueba("la maquina se declara maquina", () => {
  assert.strictEqual(conControl(true).esIA, true);
  assert.ok(/la máquina/.test(quienConduce(true)), quienConduce(true));
});

prueba("la persona se declara persona", () => {
  assert.strictEqual(conControl(false).esIA, false);
  assert.ok(/una persona/.test(quienConduce(false)), quienConduce(false));
});

prueba("sin declarar no se afirma ninguna de las dos", () => {
  const a = conControl(undefined);
  assert.strictEqual(a.esIA, null, "llego " + a.esIA + ", que no es «no informado»");
  const texto = quienConduce(a.esIA);
  assert.ok(/no declara/.test(texto), texto);
  assert.ok(!/^según/.test(texto) || /no declara/.test(texto), texto);
});

prueba("el control se atribuye a la parrilla capturada, no a la carrera", () => {
  [true, false, null].forEach(v => {
    assert.ok(/parrilla capturada/.test(quienConduce(v)), quienConduce(v));
  });
});

prueba("el renombrado tardio tambien trae el control", () => {
  reiniciar();
  armarAutos([CAR19]);
  assert.strictEqual(autoPropio().esIA, null);
  ponerParrilla(parrillaDeSpa());
  assert.strictEqual(renombrarAutos(), true);
  assert.strictEqual(autoPropio().esIA, false);
});

prueba("un cambio solo de control se propaga igual", () => {
  /* La comparacion miraba el nombre y si estaba declarada: con el mismo nombre
     y otro control no actualizaba nada. */
  reiniciar();
  ponerParrilla(parrillaDeSpa({ vehiculos: [
    { indice: 19, vehicle_id: CAR19, nombre: "NORRIS", numero: 4,
      equipo: "McLaren", es_ia: true, con_telemetria: true }] }));
  armarAutos([CAR19]);
  assert.strictEqual(autoPropio().esIA, true);
  ponerParrilla(parrillaDeSpa());
  assert.strictEqual(renombrarAutos(), true);
  assert.strictEqual(autoPropio().esIA, false);
});

/* ==================================================================
   11. LO ESCALONADO SE DIBUJA COMO ESCALON
   ------------------------------------------------------------------
   `esCanalEscalonado` clasificaba bien y los cuatro renderizadores seguian
   uniendo con diagonales. Se comprueban **los comandos de dibujo**.
   ================================================================== */

function lienzoDePrueba() {
  const ordenes = [];
  return {
    ordenes: ordenes,
    beginPath: () => ordenes.push(["begin"]),
    moveTo: (x, y) => ordenes.push(["moveTo", +x.toFixed(3), +y.toFixed(3)]),
    lineTo: (x, y) => ordenes.push(["lineTo", +x.toFixed(3), +y.toFixed(3)]),
    stroke: () => ordenes.push(["stroke"]),
  };
}

prueba("una continua se une con una recta", () => {
  const ctx = lienzoDePrueba();
  trazarSerie(ctx, [[100, 200], [200, 250]], x => x, y => y, false);
  assert.deepStrictEqual(ctx.ordenes,
    [["moveTo", 100, 200], ["lineTo", 200, 250]]);
});

prueba("dentro de un hueco el valor esta sostenido y se sabe cual hueco", () => {
  /* LO QUE EL USUARIO PIDIO, Y LO QUE YA ESTABA. Dentro de un hueco los
     valores **no caen a cero**: `valorContinuoEn` devuelve el ultimo medido en
     vez de interpolar. Lo que faltaba era decirlo: 295 km/h sostenidos y 295
     km/h de ahora se ven iguales.

     Para poder decirlo hay que saber **en que hueco** se esta, no solo que se
     esta en uno: sin eso no se puede escribir cuanto dura. */
  const cont = { huecos: [[1000, 3000], [8000, 8500]] };
  assert.deepStrictEqual(huecoQueContiene(cont, 2000), [1000, 3000]);
  assert.deepStrictEqual(huecoQueContiene(cont, 8100), [8000, 8500]);
  assert.strictEqual(huecoQueContiene(cont, 5000), null);
});

prueba("en los bordes del hueco todavia hay medicion", () => {
  /* El instante en que se corto y aquel en que volvio **son muestras**: el
     hueco es lo de en medio. Marcarlos como sostenidos diria que dos valores
     medidos no lo estan. */
  const cont = { huecos: [[1000, 3000]] };
  assert.strictEqual(huecoQueContiene(cont, 1000), null);
  assert.strictEqual(huecoQueContiene(cont, 3000), null);
});

prueba("sin cortes declarados no se inventa un hueco", () => {
  assert.strictEqual(huecoQueContiene(null, 2000), null);
  assert.strictEqual(huecoQueContiene({ huecos: [] }, 2000), null);
});

prueba("un hueco largo con el coche andando SI es telemetria perdida", () => {
  /* EL DEFECTO QUE ESTO CORRIGE. La regla decidia **solo por la duracion**:
     `mayor < 2` era telemetria perdida y todo lo demas, «el coche detenido o
     el juego fuera de pista». Sobre Barcelona esa lectura es correcta ---456 s
     parado--- y sobre un corte de red de dos minutos con el coche dando vueltas
     es exactamente al reves, que es la prueba que el usuario esta por hacer.

     Lo que los separa es si el coche **avanzo**. */
  const conCorte = [{ numero: 3, hueco_mayor_s: 120, huecos: [
    { duracion_s: 120, metros: 3200, se_movio: true }] }];
  assert.strictEqual(comoSeLeeElHueco(conCorte).esPerdida, true);
  assert.ok(/3\.200 m/.test(comoSeLeeElHueco(conCorte).texto),
            comoSeLeeElHueco(conCorte).texto);
});

prueba("un hueco largo con el coche parado no es un problema", () => {
  const enBoxes = [{ numero: 3, hueco_mayor_s: 456, huecos: [
    { duracion_s: 456, metros: 0, se_movio: false }] }];
  assert.strictEqual(comoSeLeeElHueco(enBoxes).esPerdida, false);
});

prueba("un hueco corto sigue siendo muestras que no llegaron", () => {
  /* Un coche a doscientos por hora recorre cinco metros en cien milisegundos:
     por debajo del umbral de movimiento aunque estuviera andando. La duracion
     corta sigue siendo evidencia por si sola. */
  const corto = [{ numero: 2, hueco_mayor_s: 0.1, huecos: [
    { duracion_s: 0.1, metros: 5.4, se_movio: false }] }];
  assert.strictEqual(comoSeLeeElHueco(corto).esPerdida, true);
});

prueba("sin saber si se movio se dice que no se sabe", () => {
  /* Una respuesta de antes de este campo. No se puede leer como «parado»: eso
     convierte una ignorancia en una medicion. */
  const viejo = [{ numero: 3, hueco_mayor_s: 120, huecos: [
    { duracion_s: 120, metros: null, se_movio: null }] }];
  const r = comoSeLeeElHueco(viejo);
  assert.ok(/no se sabe|no declara/i.test(r.texto), r.texto);
});

/* Declara las vueltas de la sesion abierta. `huecosEnLaLinea` ya no las recibe
   por parametro: las lee de `estado`, que es donde viven. */
function conVueltas(vueltas) {
  globalThis.estado.vueltas = vueltas;
  return vueltas;
}

prueba("EL CORTE SE MARCA DE PUNTA A PUNTA, NO COMO UN PUNTO", () => {
  /* EL CASO REAL, MEDIDO EN BARCELONA-CATALUNYA.

       vuelta 1  267,715 s   02:37:59,895 - 02:42:27,610
       vuelta 2   82,548 s   02:42:27,610 - 02:43:50,158
       vuelta 3  119,785 s   02:43:50,259 - 02:45:50,044
                 con un corte de 455,977 s que arranca a las 02:45:35,097

     Mientras la reproduccion saltaba el corte, este no ocupaba tiempo y lo
     unico marcable era el instante del salto: caia al 96,8 % de una barra de
     470,0 s, con quince segundos despues, y era invisible.

     Atravesandolo, la barra dura 926,0 s ---los 470,0 rodados mas los 456,0
     caidos--- y el corte ocupa desde los 455,1 s hasta los 911,1: del 49,1 %
     al 98,4 %. La mitad de la barra, que es lo que el corte fue. */
  const h = huecosEnLaLinea(conVueltas([
    { numero: 1, duracion_s: 267.715, desde_utc: "2026-09-11T02:37:59.895Z",
      hasta_utc: "2026-09-11T02:42:27.610Z", huecos: [] },
    { numero: 2, duracion_s: 82.548, desde_utc: "2026-09-11T02:42:27.610Z",
      hasta_utc: "2026-09-11T02:43:50.158Z", huecos: [] },
    { numero: 3, duracion_s: 119.785, desde_utc: "2026-09-11T02:43:50.259Z",
      hasta_utc: "2026-09-11T02:45:50.044Z", huecos: [
        { desde_utc: "2026-09-11T02:45:35.097Z",
          hasta_utc: "2026-09-11T02:53:11.074Z", duracion_s: 455.977 }] },
  ]));
  assert.strictEqual(h.length, 1);
  assert.strictEqual(h[0].vuelta, 3);
  assert.ok(Math.abs(h[0].fraccion - 0.491) < 0.002, "empieza en " + h[0].fraccion);
  assert.ok(Math.abs(h[0].hasta - 0.984) < 0.002, "termina en " + h[0].hasta);
  assert.ok(h[0].hasta > h[0].fraccion, "la banda no tiene ancho");
});

prueba("un corte entre dos vueltas lo vive la que venia rodando", () => {
  /* LA CONTRARRELOJ DE SPA DEL 2026-09-13. `/vueltas` cuelga el corte de la
     vuelta 3 ---es la que encontro rota--- pero va de las 00:27:50,938, que es
     el `hasta_utc` de la vuelta 2, a las 00:35:10,011, que es su `desde_utc`:
     cae entero entre las dos.

     Quien lo vive es la 2, y eso decide algo concreto: los valores que se
     sostienen durante el corte son los ultimos medidos, y estan en la serie de
     la 2. Colgado de la 3, el cabezal caeria antes de su primera muestra y se
     sostendria un valor del futuro. */
  const h = huecosEnLaLinea(conVueltas([
    { numero: 1, duracion_s: 130.646, desde_utc: "2026-09-13T00:25:24.793Z",
      hasta_utc: "2026-09-13T00:27:35.440Z", huecos: [] },
    { numero: 2, duracion_s: 15.499, desde_utc: "2026-09-13T00:27:35.490Z",
      hasta_utc: "2026-09-13T00:27:50.938Z", huecos: [] },
    { numero: 3, duracion_s: 65.598, desde_utc: "2026-09-13T00:35:10.011Z",
      hasta_utc: "2026-09-13T00:36:15.609Z", huecos: [
        { desde_utc: "2026-09-13T00:27:50.938Z",
          hasta_utc: "2026-09-13T00:35:10.011Z", duracion_s: 439.072 }] },
  ]));
  assert.strictEqual(h.length, 1);
  assert.strictEqual(h[0].vuelta, 2, "el corte quedo colgado de la vuelta que lo declara");
  /* 130,646 + 15,499 = 146,145 s de los 651,815 de linea: el 22,4 %. */
  assert.ok(Math.abs(h[0].fraccion - 0.2242) < 0.002, "empieza en " + h[0].fraccion);
  assert.ok(Math.abs(h[0].hasta - 0.8979) < 0.002, "termina en " + h[0].hasta);
});

prueba("dos cortes en la misma vuelta no se pisan", () => {
  /* Uno detras del otro, cada uno en su sitio de reloj. La vuelta dura 20 s
     rodados y lleva 160 de corte: 180 de linea. */
  const h = huecosEnLaLinea(conVueltas([
    { numero: 1, duracion_s: 20, desde_utc: "2026-09-11T00:00:00.000Z",
      hasta_utc: "2026-09-11T00:03:00.000Z",
      huecos: [{ desde_utc: "2026-09-11T00:00:10.000Z",
                 hasta_utc: "2026-09-11T00:01:50.000Z", duracion_s: 100 },
               { desde_utc: "2026-09-11T00:01:55.000Z",
                 hasta_utc: "2026-09-11T00:02:55.000Z", duracion_s: 60 }] },
  ]));
  assert.strictEqual(h.length, 2);
  assert.ok(Math.abs(h[0].fraccion - 10 / 180) < 0.001, String(h[0].fraccion));
  assert.ok(Math.abs(h[0].hasta - 110 / 180) < 0.001, String(h[0].hasta));
  assert.ok(Math.abs(h[1].fraccion - 115 / 180) < 0.001, String(h[1].fraccion));
  assert.ok(Math.abs(h[1].hasta - 175 / 180) < 0.001, String(h[1].hasta));
  assert.ok(h[0].hasta <= h[1].fraccion, "las dos bandas se superponen");
});

prueba("sin huecos no hay marcas que poner", () => {
  assert.deepStrictEqual(huecosEnLaLinea(conVueltas(
    [{ numero: 1, duracion_s: 60, desde_utc: "2026-09-11T00:00:00.000Z",
       hasta_utc: "2026-09-11T00:01:00.000Z", huecos: [] }])), []);
  assert.deepStrictEqual(huecosEnLaLinea(conVueltas([])), []);
});

prueba("con las capturas unidas los pilotos siguen teniendo nombre", () => {
  /* EL DEFECTO QUE INTRODUJE AL UNIRLAS. Al unir se fija el alcance en
     «original», y la parrilla se buscaba por clave exacta: existen
     `original-1` y `original-2`, no `original`. Devolvia `null` y **nadie
     quedaba nombrado**: el tablero paso a decir «Vehiculo 19» donde antes
     decia el apellido.

     Visto en pantalla sobre Barcelona-Catalunya, cinco vehiculos, todos sin
     nombre. */
  const uno = { disponible: true, vehiculos: [
    { vehicle_id: "s:car:19", nombre: "NORRIS" },
    { vehicle_id: "s:car:0", nombre: "HADJAR" }] };
  const otro = { disponible: true, vehiculos: [
    { vehicle_id: "s:car:19", nombre: "NORRIS" },
    { vehicle_id: "s:car:0", nombre: "HADJAR" }] };
  assert.deepStrictEqual(parrillaComun({ "original-1": uno, "original-2": otro }),
                         uno);
});

prueba("si las dos capturas nombran distinto, no se elige una", () => {
  /* Es la cautela que ya estaba escrita y que hay que conservar: con dos
     capturas que declaran gente distinta en el mismo indice, tomar cualquiera
     seria inventar. */
  const uno = { disponible: true, vehiculos: [
    { vehicle_id: "s:car:19", nombre: "NORRIS" }] };
  const otro = { disponible: true, vehiculos: [
    { vehicle_id: "s:car:19", nombre: "VERSTAPPEN" }] };
  assert.strictEqual(parrillaComun({ "original-1": uno, "original-2": otro }), null);
});

prueba("una reproduccion no cuenta para la parrilla comun", () => {
  /* Solo se unen capturas, asi que solo las capturas deciden el nombre. */
  const cap = { disponible: true, vehiculos: [{ vehicle_id: "s:car:19", nombre: "NORRIS" }] };
  const rep = { disponible: true, vehiculos: [{ vehicle_id: "s:car:19", nombre: "OTRO" }] };
  assert.deepStrictEqual(parrillaComun({ "original-1": cap, "corrida-x": rep }), cap);
});

prueba("dos capturas de la misma carrera son una sola carrera", () => {
  /* EL CASO: se corta la corriente en plena carrera, el usuario vuelve a
     escuchar, y quedan dos capturas bajo el mismo identificador del juego ---que
     no cambia, porque lo pone el juego---. Medido en la Pi: cinco sesiones asi,
     una con tres capturas.

     El tablero preguntaba cual mirar, con el motivo «juntas no son una carrera
     continua». Para Spa eso es cierto: son una captura y dos **reproducciones**
     separadas por tres dias. Para dos capturas separadas por treinta y un
     segundos es falso: son la misma carrera con un agujero. */
  const dos = [{ clave: "original-1", es_reproduccion: false, fases: [] },
               { clave: "original-2", es_reproduccion: false, fases: [] }];
  assert.strictEqual(sonUnaSolaCarrera(dos), true);
});

prueba("una reproduccion nunca se une a su captura", () => {
  /* Es la misma sesion grabada y despues reproducida: unirlas mostraria cada
     vuelta dos veces. Que sea el mismo identificador es justamente el problema,
     no el permiso. */
  const conReproduccion = [
    { clave: "original-1", es_reproduccion: false, fases: [] },
    { clave: "corrida-de-prueba", es_reproduccion: true, fases: [] }];
  assert.strictEqual(sonUnaSolaCarrera(conReproduccion), false);
});

prueba("si el reloj del juego se reinicia adentro, no se unen", () => {
  /* La formacion y la carrera llevan el mismo reloj puesto a cero, de modo que
     sus ventanas se solapan aunque en orden de captura no lo hagan. Unirlas
     apilaria dos lineas de tiempo. */
  const conReinicio = [
    { clave: "original-1", es_reproduccion: false,
      fases: [{ orden: 1 }, { orden: 2, reloj_del_juego_reinicia_al_entrar: true }] },
    { clave: "original-2", es_reproduccion: false, fases: [] }];
  assert.strictEqual(sonUnaSolaCarrera(conReinicio), false);
});

prueba("una sola captura no es una union", () => {
  assert.strictEqual(sonUnaSolaCarrera(
    [{ clave: "original-1", es_reproduccion: false, fases: [] }]), false);
});

prueba("con el flujo caido los valores dicen que son viejos", () => {
  /* EL CASO REAL, FOTOGRAFIADO EL 2026-09-12. Se corto la corriente de la Pi
     en plena sesion. La maquina volvio sola en 58 s, pero el capturador esta
     `disabled` a proposito y no rearranca, de modo que el tablero quedo sin
     flujo. La pantalla mostraba **a la vez** 11.819 rpm, 295 km/h y marcha 7
     ---congelados desde antes del corte--- y abajo «sin telemetria todavia».
     Las dos cosas no pueden ser ciertas.

     Nada en los paneles decia que esos valores eran viejos. */
  assert.strictEqual(comoSeVeElFlujo(0.4).estado, "");
  assert.strictEqual(comoSeVeElFlujo(4).estado, "held");
  assert.strictEqual(comoSeVeElFlujo(30).estado, "aged");
});

prueba("el vocabulario de frescura es el que ya existia", () => {
  /* La hoja ya define `aged` al 62 % con un comentario que dice que es **una
     sola convencion** para «esto no describe el ahora con la misma autoridad»,
     en vez de una por panel. Inventar otra palabra seria la segunda. */
  assert.ok(["", "held", "aged"].indexOf(comoSeVeElFlujo(4).estado) !== -1);
  assert.ok(["", "held", "aged"].indexOf(comoSeVeElFlujo(99).estado) !== -1);
});

prueba("el aviso dice cuanto hace, no solo que pasa algo", () => {
  /* «Sin telemetria» no le sirve a nadie parado frente a una pantalla que
     marca 295 km/h: lo que decide es **hace cuanto**. */
  assert.ok(/4 s/.test(comoSeVeElFlujo(4.2).texto), comoSeVeElFlujo(4.2).texto);
  assert.ok(/2 min/.test(comoSeVeElFlujo(125).texto), comoSeVeElFlujo(125).texto);
});

prueba("sin saber la edad no se afirma que el dato es fresco", () => {
  /* `null` es «no se sabe», y no se puede tratar como cero: eso convertiria
     una ignorancia en una afirmacion. */
  assert.strictEqual(comoSeVeElFlujo(null).estado, "");
  assert.strictEqual(comoSeVeElFlujo(null).texto, "");
});

prueba("un hueco de captura corta la linea en vez de cruzarlo", () => {
  /* EL DEFECTO DEL PUNTO 6, Y NO ES DECORACION. Con el flujo caido treinta
     segundos, unir la ultima muestra con la primera de la vuelta dibuja una
     recta sobre un tramo donde **no hubo dato**: la curva afirma que el coche
     estuvo ahi. Una linea que no se corta es una medicion inventada. */
  const ctx = lienzoDePrueba();
  trazarSerie(ctx, [[0, 10], [100, 20], [9000, 30], [9100, 40]],
              x => x, y => y, false, [[100, 9000]]);
  assert.deepStrictEqual(ctx.ordenes, [
    ["moveTo", 0, 10], ["lineTo", 100, 20],
    ["moveTo", 9000, 30],            // el hueco no se cruza: se levanta la pluma
    ["lineTo", 9100, 40],
  ]);
});

prueba("sin huecos declarados se une todo, como siempre", () => {
  /* La correccion no puede cambiar lo que dibujan los que no declaran huecos:
     una vuelta reproducida entera no tiene cortes de flujo. */
  const ctx = lienzoDePrueba();
  trazarSerie(ctx, [[0, 10], [9000, 30]], x => x, y => y, false);
  assert.deepStrictEqual(ctx.ordenes,
    [["moveTo", 0, 10], ["lineTo", 9000, 30]]);
});

prueba("una escalonada tambien corta, y no arrastra el valor viejo", () => {
  /* Es el caso peor: una escalonada sostiene el valor anterior hasta la
     muestra siguiente, de modo que sin cortar dibujaria treinta segundos de
     linea plana afirmando que el dato no cambio. No es que no cambio: es que
     no llego. */
  const ctx = lienzoDePrueba();
  trazarSerie(ctx, [[0, 5], [9000, 8]], x => x, y => y, true, [[0, 9000]]);
  assert.deepStrictEqual(ctx.ordenes,
    [["moveTo", 0, 5], ["moveTo", 9000, 8]]);
});

prueba("el corte se decide por lo medido y no por lo dibujado", () => {
  /* EL CASO QUE OBLIGO A CAMBIAR EL DISENO. La serie que llega al dibujo viene
     reducida al ancho del lienzo: sobre una vuelta de Shanghai son dieciocho
     metros por punto contra dos y medio medidos. Un umbral deducido de lo
     dibujado deja pasar los cortes de dos segundos ---ciento diez metros---,
     que estan justo por debajo de ese paso grueso y son cortes de verdad.

     Aca se dibujan dos puntos separados por ciento veinte metros, que para lo
     dibujado es normal, y el hueco declarado cae en el medio: tiene que
     cortar igual. */
  const ctx = lienzoDePrueba();
  trazarSerie(ctx, [[0, 10], [120, 20]], x => x, y => y, false, [[30, 90]]);
  assert.deepStrictEqual(ctx.ordenes, [["moveTo", 0, 10], ["moveTo", 120, 20]]);
});

prueba("donde estan los huecos se puede preguntar", () => {
  /* Cortar la linea deja un blanco, y un blanco se lee igual que el borde de
     los datos. Quien dibuja necesita saber **donde** estuvieron para poder
     decirlo. */
  const huecos = huecosDeLaSerie([[0, 1], [100, 2], [9000, 3]], 2000);
  assert.deepStrictEqual(huecos, [[100, 9000]]);
});

prueba("el umbral sale del paso habitual de la propia serie", () => {
  /* No puede ser una cifra fija: el eje se lee en metros cuando la fuente mide
     distancia y en segundos cuando no. Medido sobre una vuelta limpia de
     Shanghai: paso mediano 2,47 m, mayor legitimo 6,07. */
  const paso = [];
  for (let i = 0; i < 40; i++) paso.push([i * 2.5, 100]);
  assert.ok(Math.abs(huecoDeLaSerie(paso) - 15) < 0.01, huecoDeLaSerie(paso));
});

prueba("la frenada mas fuerte no se toma por un corte", () => {
  /* El salto legitimo mas grande medido es 2,46 veces la mediana. El umbral
     esta en seis: si esta prueba cae, el tablero empezo a partir curvas
     buenas, que es peor que unir de mas. */
  const puntos = [];
  for (let i = 0; i < 40; i++) puntos.push([i * 2.5, 100]);
  puntos.push([puntos[puntos.length - 1][0] + 6.1, 100]);   // la frenada
  assert.deepStrictEqual(huecosDeLaSerie(puntos, huecoDeLaSerie(puntos)), []);
});

prueba("con pocas muestras no se deduce un umbral", () => {
  /* Preferible unir de mas que partir una curva por una mediana de dos
     puntos. */
  assert.strictEqual(huecoDeLaSerie([[0, 1], [5, 2], [10, 3]]), 0);
});

prueba("sin umbral no hay huecos que declarar", () => {
  assert.deepStrictEqual(huecosDeLaSerie([[0, 1], [9000, 3]], 0), []);
});

prueba("una escalonada se sostiene y cambia en la muestra siguiente", () => {
  /* [100 m, 2,653] -> [200 m, 2,336]: a los 150 m la curva dibujaba 2,49
     mientras el lector numerico decia 2,653. */
  const ctx = lienzoDePrueba();
  trazarSerie(ctx, [[100, 2.653], [200, 2.336]], x => x, y => y, true);
  assert.deepStrictEqual(ctx.ordenes, [
    ["moveTo", 100, 2.653],
    ["lineTo", 200, 2.653],   // plana hasta donde se midio el cambio
    ["lineTo", 200, 2.336],   // y ahi baja de una vez
  ]);
});

prueba("el escalon no adelanta el cambio", () => {
  /* El vertice va en la x de la muestra nueva. Ponerlo antes mostraria el
     adelantamiento en un metro donde nadie lo midio. */
  const ctx = lienzoDePrueba();
  trazarSerie(ctx, [[0, 5], [100, 4]], x => x, y => y, true);
  const xs = ctx.ordenes.filter(o => o[0] !== "begin").map(o => o[1]);
  assert.ok(xs.every(x => x === 0 || x === 100), "vertice fuera de una muestra: " + xs);
  const bajada = ctx.ordenes.find(o => o[2] === 4);
  assert.strictEqual(bajada[1], 100);
});

prueba("a mitad de camino la curva escalonada vale lo que el lector numerico", () => {
  /* Se recorre el camino dibujado y se lo evalua en 150 m. */
  const ctx = lienzoDePrueba();
  trazarSerie(ctx, [[100, 2.653], [200, 2.336]], x => x, y => y, true);
  const pts = ctx.ordenes.filter(o => o[0] !== "begin").map(o => [o[1], o[2]]);
  const enX = x => {
    for (let i = 1; i < pts.length; i++) {
      if (x <= pts[i][0]) {
        const dx = pts[i][0] - pts[i - 1][0];
        if (!dx) return pts[i][1];
        return pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * ((x - pts[i - 1][0]) / dx);
      }
    }
    return pts[pts.length - 1][1];
  };
  assert.strictEqual(enX(150), 2.653);
  assert.strictEqual(enX(199.999), 2.653);
});

prueba("un solo punto no dibuja ningun segmento", () => {
  const ctx = lienzoDePrueba();
  trazarSerie(ctx, [[10, 3]], x => x, y => y, true);
  assert.deepStrictEqual(ctx.ordenes, [["moveTo", 10, 3]]);
});

prueba("el escalon no agrega puntos a los datos", () => {
  const datos = [[100, 2.653], [200, 2.336]];
  const copia = JSON.stringify(datos);
  trazarSerie(lienzoDePrueba(), datos, x => x, y => y, true);
  assert.strictEqual(JSON.stringify(datos), copia);
});

/* ==================================================================
   12. ELEGIR UNA ETAPA NO BORRA LA IDENTIDAD
   ------------------------------------------------------------------
   EL DEFECTO. `/adquisiciones` cargaba la parrilla y `elegirCorrida()` llamaba
   despues a `nuevaSesionEnCurso()`, que la ponia en `null`; `cargarDatosDeSesion`
   no la volvia a pedir. Abrir con el enlace completo mostraba NORRIS y abrir
   desde el catalogo y elegir Carrera terminaba en «Vehículo 19». Cambiar de
   etapa hacia lo mismo.

   Se corre `elegirCorrida` **de verdad**, con la respuesta de `/adquisiciones`
   tal como la manda la API.
   ================================================================== */

/* Una respuesta de `/adquisiciones` con las tres etapas de la carrera de Spa. */
function respuestaDeAdquisiciones(parrillaPorClave) {
  const fases = [
    { orden: 1, duracion_de_captura_s: 120 },
    { orden: 2, duracion_de_captura_s: 60 },
    { orden: 3, duracion_de_captura_s: 2800 },
  ];
  return {
    session_id: SESION,
    adquisiciones: Object.keys(parrillaPorClave).map(clave => ({
      clave: clave, replay_run_id: clave === "original" ? null : clave,
      es_reproduccion: clave !== "original",
      muestras_de_vuelta: 60468, vehiculos: 1,
      desde_utc: iso(T0), hasta_utc: iso(T0 + 3000000),
      parrilla: parrillaPorClave[clave], fases: fases,
    })),
    mezclada: Object.keys(parrillaPorClave).length > 1,
  };
}

let _cargasPedidas = [];
function prepararElector(resp) {
  reiniciar();
  globalThis.estadoSesion = "cargado";
  globalThis.corrida = { adquisicion: null, fase: null,
                         disponibles: resp.adquisiciones, mezclada: resp.mezclada };
  anotarParrillas(resp.session_id, resp.adquisiciones);
  fijarContextoDeCorrida({ ruta: "/sesiones/" + SESION, s: estado.abierta });
  _cargasPedidas = [];
  globalThis.cargarDatosDeSesion = (ruta, apertura) => _cargasPedidas.push(apertura);
  globalThis.declararAlcance = () => {};
  globalThis.pintarBotonDeCorrida = () => {};
  globalThis.abrirElectorDeCorrida = () => {};
  globalThis.decirEstadoApi = () => {};
  globalThis.etiquetaDeCorrida = () => "x";
  globalThis.senalDeSesion = () => null;
  globalThis.render = () => {};
  globalThis.detener = () => {};
  globalThis.olvidarCaches = () => {};
  globalThis.document = { getElementById: () => null, querySelector: () => null };
  globalThis.location = { href: "http://x/", search: "" };
  globalThis.history = { replaceState: () => {} };
  globalThis.URL = URL;
}

prueba("catalogo, elector, Original y Carrera: el nombre sobrevive", () => {
  const resp = respuestaDeAdquisiciones({ original: parrillaDeSpa() });
  prepararElector(resp);
  armarAutos([CAR19]);
  assert.strictEqual(autoPropio().nombre, "NORRIS", "no llego con la respuesta");

  elegirCorrida("original", 3);
  assert.strictEqual(globalThis.corrida.fase, 3);
  assert.strictEqual(_cargasPedidas.length, 1, "no se volvieron a pedir los datos");
  /* `olvidarLoDeLaCorrida` vacio la lista, como en produccion: lo que importa
     es que al rearmarla con las series nuevas el nombre siga estando. */
  armarAutos([CAR19]);
  assert.strictEqual(autoPropio().nombre, "NORRIS",
                     "elegir la etapa borro la identidad");
  assert.strictEqual(autoPropio().numero, 4);
});

prueba("Formacion y despues Carrera: las etapas comparten participantes", () => {
  const resp = respuestaDeAdquisiciones({ original: parrillaDeSpa() });
  prepararElector(resp);
  elegirCorrida("original", 1);
  armarAutos([CAR19]);
  assert.strictEqual(autoPropio().nombre, "NORRIS");
  elegirCorrida("original", 3);
  armarAutos([CAR19]);
  assert.strictEqual(autoPropio().nombre, "NORRIS");
});

prueba("cambiar de adquisicion trae la identidad de esa adquisicion", () => {
  const otra = parrillaDeSpa({ vehiculos: [
    { indice: 19, vehicle_id: CAR19, nombre: "PIASTRI", numero: 81,
      equipo: "McLaren", es_ia: false, con_telemetria: true }] });
  const resp = respuestaDeAdquisiciones({ original: parrillaDeSpa(), corrida7: otra });
  prepararElector(resp);
  elegirCorrida("original", 3);
  armarAutos([CAR19]);
  assert.strictEqual(autoPropio().nombre, "NORRIS");
  elegirCorrida("corrida7", 3);
  armarAutos([CAR19]);
  assert.strictEqual(autoPropio().nombre, "PIASTRI",
                     "se quedo con la parrilla de la adquisicion anterior");
});

prueba("sin elegir, con dos parrillas distintas no se nombra a nadie", () => {
  /* Tomar cualquiera seria ponerle a un vehiculo el nombre del de otra carrera. */
  const otra = parrillaDeSpa({ vehiculos: [
    { indice: 19, vehicle_id: CAR19, nombre: "PIASTRI", numero: 81,
      equipo: "McLaren", es_ia: false, con_telemetria: true }] });
  const resp = respuestaDeAdquisiciones({ original: parrillaDeSpa(), corrida7: otra });
  prepararElector(resp);
  assert.strictEqual(globalThis.corrida.adquisicion, null);
  assert.strictEqual(parrillaVigente(), null);
  armarAutos([CAR19]);
  assert.strictEqual(autoPropio().nombre, "Vehículo 19");
});

prueba("la parrilla de otra sesion no nombra a los vehiculos de esta", () => {
  /* A -> B -> A con una respuesta atrasada: la de A llega con la B abierta. */
  const resp = respuestaDeAdquisiciones({ original: parrillaDeSpa() });
  prepararElector(resp);
  armarAutos([CAR19]);
  assert.strictEqual(autoPropio().nombre, "NORRIS");

  globalThis.estado.abierta = { session_id: "f1_25:session:999" };
  assert.strictEqual(parrillaVigente(), null, "la parrilla de A nombra en B");
  armarAutos([CAR19]);
  assert.strictEqual(autoPropio().nombre, "Vehículo 19");

  globalThis.estado.abierta = { session_id: SESION };
  armarAutos([CAR19]);
  assert.strictEqual(autoPropio().nombre, "NORRIS", "al volver a A se perdio");
});

prueba("anular consultas no es olvidar quien es cada uno", () => {
  /* Es la separacion que faltaba: `nuevaSesionEnCurso` anula lo que este en
     vuelo y no toca la identidad. */
  const resp = respuestaDeAdquisiciones({ original: parrillaDeSpa() });
  prepararElector(resp);
  globalThis.corrida.adquisicion = "original";
  const antes = parrillaVigente();
  nuevaSesionEnCurso();
  assert.strictEqual(parrillaVigente(), antes);
});

prueba("un alcance a medias no carga nada", () => {
  const resp = respuestaDeAdquisiciones({ original: parrillaDeSpa() });
  prepararElector(resp);
  elegirCorrida("no-existe", 3);
  assert.strictEqual(_cargasPedidas.length, 0);
  assert.strictEqual(globalThis.corrida.adquisicion, null);
});

prueba("una adquisicion que no existe no toma la parrilla de la que si", () => {
  /* Con dos adquisiciones y una eleccion invalida no hay a quien nombrar. */
  const otra = parrillaDeSpa({ vehiculos: [
    { indice: 19, vehicle_id: CAR19, nombre: "PIASTRI", numero: 81,
      equipo: "McLaren", es_ia: false, con_telemetria: true }] });
  const resp = respuestaDeAdquisiciones({ original: parrillaDeSpa(), corrida7: otra });
  prepararElector(resp);
  elegirCorrida("no-existe", 3);
  armarAutos([CAR19]);
  assert.strictEqual(autoPropio().nombre, "Vehículo 19");
});

/* ==================================================================
   13. EL CSV EXPORTA LO QUE LA FUENTE MANDO
   ------------------------------------------------------------------
   Convertir el bloque guardado hizo que este archivo empezara a decir 2,937
   donde la base guarda 2937, y con un sufijo de unidad que nadie pidio. Se
   corre **el exportador real** y se compara su salida.
   ================================================================== */

function exportar() {
  let salida = null;
  globalThis.guardar = (nombre, texto) => { salida = { nombre: nombre, texto: texto }; };
  globalThis.avisar = () => {};
  globalThis.canalesDeLaFuente = () => ["speed", "gap"];
  globalThis.elegidos = () => ({ speed: true, gap: true });
  exportarCsv();
  return salida;
}

function conDosVehiculos() {
  reiniciar();
  ponerParrilla(parrillaDeSpa());
  cargarVuelta(1, [0, 100, 200],
               { distancia_m: [0, 10, 20], speed: [100, null, 120],
                 delta_to_race_leader: [2937, 2986, null] },
               { speed: "km/h", delta_to_race_leader: "ms" });
  const otro = SESION + ":car:0";
  globalThis.estado.series[1].vehiculos[otro] = {
    timestamp_utc: [iso(T0), iso(T0 + 100)], distancia_m: [0, 10],
    speed: [98, 99], delta_to_race_leader: [0, 0],
  };
  globalThis._selloSeries++;
  globalThis.vueltaElegida = 1;
  armarAutos([CAR19, otro]);
  globalThis.seleccion = new Set([CAR19]);
}

prueba("el gap se exporta en milisegundos, como lo guarda la base", () => {
  conDosVehiculos();
  const csv = exportar();
  assert.strictEqual(csv.nombre, "traza-vuelta.csv");
  const filas = csv.texto.split("\n");
  assert.ok(filas[1].indexOf("2937.000") !== -1, filas[1]);
  assert.ok(csv.texto.indexOf("2.937") === -1, "se exporto convertido");
});

prueba("el encabezado no lleva sufijo de unidad", () => {
  conDosVehiculos();
  const cab = exportar().texto.split("\n")[0];
  assert.strictEqual(cab,
    "distancia_m,NORRIS_speed,NORRIS_delta_to_race_leader");
  assert.ok(cab.indexOf("(") === -1, "el encabezado gano un sufijo: " + cab);
});

prueba("un nulo se exporta vacio y no como cero", () => {
  conDosVehiculos();
  const filas = exportar().texto.split("\n");
  // 10 m: la velocidad es nula y el gap no.
  const f = filas.find(x => x.indexOf("10,") === 0);
  assert.strictEqual(f, "10,,2986.000", f);
});

prueba("varios vehiculos, cada uno con su columna", () => {
  conDosVehiculos();
  globalThis.seleccion = new Set([CAR19, SESION + ":car:0"]);
  const cab = exportar().texto.split("\n")[0];
  assert.strictEqual(cab.split(",").length, 5, cab);
  assert.ok(cab.indexOf("Vehículo 0_speed") !== -1 || cab.indexOf("PIASTRI_speed") !== -1, cab);
});

prueba("exportar no muta lo que llego", () => {
  conDosVehiculos();
  const antes = JSON.stringify(globalThis.estado.series[1]);
  exportar();
  assert.strictEqual(JSON.stringify(globalThis.estado.series[1]), antes);
});

prueba("mostrar y exportar conviven: el panel en segundos, el archivo en ms", () => {
  conDosVehiculos();
  globalThis.estado.vueltas = [{ numero: 1, duracion_s: 0.2,
                                 desde_utc: iso(T0), hasta_utc: iso(T0 + 200) }];
  globalThis.cabezal = 0;
  assert.strictEqual(calcularInstante().diferencia, 2.937);
  assert.ok(exportar().texto.indexOf("2937.000") !== -1);
  assert.strictEqual(calcularInstante().diferencia, 2.937,
                     "exportar dejo el panel en otra unidad");
});

/* ==================================================================
   14. QUE PARTE DEL CIRCUITO ES CADA PARTE DE LA GRAFICA
   ------------------------------------------------------------------
   Sobre la carrera entera el eje va de 76 a 154.163 m y la grafica es una
   sucesion de dientes: se ve que paso y no donde. Las marcas que habia leian
   `cu.metro`, un campo que el catalogo **no publica**: `undefined < d0` es
   `false` y `undefined > d1` tambien, de modo que ninguna curva se descartaba y
   todas terminaban en `x = NaN`. No se dibujaba una sola, en silencio.
   ================================================================== */

/* El catalogo de Spa como lo devuelve `/circuitos/spa/curvas`. */
const CURVAS_DE_SPA = [
  { orden: 1, nombre: "La Source", numeros_cronometraje: [1], metro_medido: 405 },
  { orden: 2, nombre: "Eau Rouge / Raidillon", numeros_cronometraje: [2, 3, 4], metro_medido: 1333 },
  { orden: 3, nombre: "Les Combes", numeros_cronometraje: [5], metro_medido: 2526 },
  { orden: 4, nombre: "Les Combes", numeros_cronometraje: [6], metro_medido: 2666 },
  { orden: 5, nombre: "Pouhon", numeros_cronometraje: [10, 11], metro_medido: 3900 },
  { orden: 6, nombre: "Blanchimont", numeros_cronometraje: [17], metro_medido: 6100 },
];

/* Las franjas ya no leen el modo global: se lo pasa quien las pide, igual que
   hace `vistaDeComparacion`. */
let _modo = { eje: "distancia", alcance: "una" };
const zonas = (a, b, clave) => zonasDeCurva(a, b, clave, _modo.eje, _modo.alcance);
const bandasVuelta = (a, b, clave) => bandasDeVuelta(a, b, clave, _modo.eje, _modo.alcance);
const bandas = (a, b, clave, ancho) =>
  bandasParaElTramo(a, b, clave, ancho, _modo.eje, _modo.alcance);

function conCircuito(alcance, eje) {
  reiniciar();
  _fijar.curvas(CURVAS_DE_SPA.slice());
  _fijar.pista({ largo_m: 7004, curvas: CURVAS_DE_SPA.slice() });
  _modo = { eje: eje || "distancia", alcance: alcance || "una" };
  _fijar.alcance(_modo.alcance);
  _fijar.eje(_modo.eje);
}

/* Dos vueltas con acumulada medida: la 7 arranca en 42.000 m y la 8 en 49.000. */
function dosVueltasAcumuladas() { _vueltasAcumuladas([7, 8]); }
function tresVueltasAcumuladas() { _vueltasAcumuladas([7, 8, 9]); }

function _vueltasAcumuladas(cuales) {
  cuales.forEach((v, i) => {
    const base = 42000 + i * 7000;
    const marcas = [], dl = [], ds = [], vel = [];
    for (let k = 0; k < 30; k++) {
      marcas.push((v - 7) * 200000 + k * 100);
      dl.push(k * 240); ds.push(base + k * 240); vel.push(200);
    }
    globalThis.estado.series[v] = {
      vuelta: v, puntos_pedidos: 600, unidades: { speed: "km/h" },
      vehiculos: { [CAR19]: { timestamp_utc: marcas.map(m => iso(T0 + m)),
                              distancia_m: dl, distancia_sesion_m: ds, speed: vel } },
    };
  });
  globalThis._selloSeries++;
}

prueba("el metro de la curva sale del campo que el catalogo publica", () => {
  /* `metro_medido`, no `metro`. Con el nombre equivocado daba NaN y el
     navegador no dibuja con NaN ni se queja. */
  assert.strictEqual(metroDeCurva(CURVAS_DE_SPA[0]), 405);
  assert.strictEqual(metroDeCurva({ nombre: "x" }), null);
  assert.strictEqual(metroDeCurva(null), null);
});

prueba("sobre una vuelta, las zonas cubren el circuito sin huecos", () => {
  conCircuito("una");
  const z = zonas(0, 7004, CAR19);
  assert.strictEqual(z.length, CURVAS_DE_SPA.length);
  assert.strictEqual(z[0].ini, 405);
  assert.strictEqual(z[0].nombre, "La Source");
  for (let i = 1; i < z.length; i++) {
    assert.strictEqual(z[i].ini, z[i - 1].fin, "hueco entre franjas en " + i);
  }
  assert.strictEqual(z[z.length - 1].fin, 7004);
});

prueba("cada zona empieza en su curva y termina donde empieza la siguiente", () => {
  /* No es «la curva»: el catalogo publica un metro, no un ancho. */
  conCircuito("una");
  const z = zonas(0, 7004, CAR19);
  assert.strictEqual(z[1].ini, 1333);
  assert.strictEqual(z[1].fin, 2526);
  assert.strictEqual(z[1].nombre, "Eau Rouge / Raidillon");
});

prueba("dos curvas con el mismo nombre se distinguen por su numero", () => {
  conCircuito("una");
  const nombres = zonas(0, 7004, CAR19).map(x => x.nombre);
  assert.ok(nombres.indexOf("Les Combes 5") !== -1, nombres.join(" | "));
  assert.ok(nombres.indexOf("Les Combes 6") !== -1, nombres.join(" | "));
  // Las que no se repiten no ganan un numero que nadie pidio.
  assert.ok(nombres.indexOf("La Source") !== -1, nombres.join(" | "));
});

prueba("sobre la carrera las zonas se repiten con el desplazamiento medido", () => {
  /* Nada de `(vuelta - 1) x largo del circuito`: el desplazamiento sale de
     comparar las dos distancias que la fuente publica. */
  conCircuito("carrera");
  dosVueltasAcumuladas();
  const z = zonas(42000, 56000, CAR19);
  const laSource = z.filter(x => x.nombre === "La Source");
  assert.strictEqual(laSource.length, 2, "una por vuelta cargada");
  assert.strictEqual(laSource[0].ini, 42405);
  assert.strictEqual(laSource[1].ini, 49405);
  assert.deepStrictEqual(laSource.map(x => x.vuelta), [7, 8]);
});

prueba("el tramo que cruza la meta no deja un hueco sin nombre", () => {
  /* De la ultima curva de una vuelta a la primera de la siguiente hay
     cuatrocientos metros: cortando en el fin de la vuelta quedaban sin franja. */
  conCircuito("carrera");
  dosVueltasAcumuladas();
  const z = zonas(42000, 56000, CAR19).sort((a, b) => a.ini - b.ini);
  for (let i = 1; i < z.length; i++) {
    assert.strictEqual(z[i].ini, z[i - 1].fin,
      "hueco entre " + z[i - 1].nombre + " y " + z[i].nombre);
  }
  const cruza = z.find(x => x.vuelta === 7 && x.fin > 49000);
  assert.ok(cruza, "ninguna franja cruza la meta");
  assert.strictEqual(cruza.nombre, "Blanchimont");
});

prueba("con una vuelta sin cargar, ninguna franja tapa el hueco", () => {
  /* Tres vueltas y la del medio sin traer: una sola franja de la 7 a la 9
     afirmaria un recorrido de catorce kilometros que nadie miro. */
  conCircuito("carrera");
  tresVueltasAcumuladas();
  delete globalThis.estado.series[8];
  globalThis._selloSeries++;
  const z = zonas(42000, 70000, CAR19);
  const masLarga = z.reduce((m, x) => Math.max(m, x.fin - x.ini), 0);
  assert.ok(masLarga < 7004,
            "una franja de " + Math.round(masLarga) + " m cruza la vuelta que falta");
  // Y la ultima de la vuelta 7 termina donde termina lo medido de la 7.
  const ultimaDe7 = z.filter(x => x.vuelta === 7).sort((a, b) => a.ini - b.ini).pop();
  assert.ok(Math.abs(ultimaDe7.fin - (42000 + 29 * 240)) < 1, ultimaDe7.fin);
});

prueba("en el eje de tiempo no se ubican, y se dice", () => {
  /* Una curva esta en un metro; el segundo en que cada piloto la cruza es otro
     y cambia vuelta a vuelta. */
  conCircuito("una", "tiempo");
  /* Los mismos numeros que sobre el eje de distancia dan seis franjas: si aca
     tambien las diera, estaria leyendo segundos como metros. */
  assert.ok(zonas(0, 7004, CAR19) === null,
            "se ubicaron curvas sobre un eje de segundos");
  _modo.eje = "distancia"; _fijar.eje("distancia");
  assert.strictEqual(zonas(0, 7004, CAR19).length, 6);
  _modo.eje = "tiempo"; _fijar.eje("tiempo");
  const [b, nota] = bandas(0, 130, CAR19, 1400);
  assert.strictEqual(b, null);
  assert.ok(/eje de distancia/.test(nota), nota);
});

prueba("sin catalogo de curvas no se inventan franjas", () => {
  conCircuito("una");
  _fijar.curvas([]);
  assert.strictEqual(zonas(0, 7004, CAR19), null);
});

/* ---- que se pinta a cada escala ---- */

prueba("a escala de carrera se pintan las vueltas, no las curvas", () => {
  /* Lo que decide es la relacion entre el tramo visible y el ancho del lienzo:
     en Spa, veintidos vueltas por quince curvas sobre 1.400 px son diez
     pixeles y medio por franja, un rayado que tapa la traza. El ejemplar tiene
     dos vueltas, asi que se reproduce la misma relacion con un lienzo angosto:
     1.170 m de franja sobre 14.000 visibles en 120 px son diez pixeles. */
  conCircuito("carrera");
  dosVueltasAcumuladas();
  const [b, nota] = bandas(42000, 56000, CAR19, 120);
  assert.ok(b, "no se pinto nada");
  assert.deepStrictEqual(b.map(x => x.nombre), ["V7", "V8"]);
  assert.ok(/una por vuelta cargada/.test(nota), nota);
});

prueba("acercandose aparecen las curvas", () => {
  conCircuito("carrera");
  dosVueltasAcumuladas();
  const [b, nota] = bandas(42000, 49000, CAR19, 1400);
  assert.ok(b.some(x => x.nombre === "La Source"), b.map(x => x.nombre).join("|"));
  assert.ok(/intervalos entre puntos de referencia/.test(nota), nota);
});

prueba("la decision se toma con la franja tipica y no con la mas angosta", () => {
  /* El minimo lo decide siempre una franja **cortada por el borde de la
     ventana**: basta con que un tramo empiece dos metros antes del final del
     zoom. Eso no dice si las franjas se leen, dice donde cayo el recorte. */
  conCircuito("carrera");
  dosVueltasAcumuladas();
  /* El borde cae dos metros despues de donde empieza «La Source» de la vuelta
     8: esa franja queda de dos metros. Con la regla del minimo, esos dos
     metros apagaban el detalle de todo el tramo. */
  const [b] = bandas(42000, 49407, CAR19, 1400);
  assert.ok(b.some(x => x.nombre === "La Source"),
            "una franja recortada por el borde apago el detalle de curva");
});

/* ---- el rotulo se mide ---- */

function lienzoConTexto(anchoPorLetra) {
  const puestos = [];
  return {
    puestos: puestos, font: "",
    save(){}, restore(){}, beginPath(){}, rect(){}, clip(){},
    fillRect(){}, measureText: t => ({ width: t.length * anchoPorLetra }),
    fillText: (t, x) => puestos.push([t, Math.round(x)]),
  };
}

prueba("el nombre se escribe solo si entra en su franja", () => {
  /* Con un ancho minimo fijo, «Les Combes 5» se montaba sobre la franja de al
     lado. Se mide el texto con la fuente que se va a usar. */
  /* «Les Combes 5» son doce letras: 72 px con esta fuente, mas ocho de margen.
     En una franja de sesenta no entra; en la de al lado, de novecientos, si. */
  const bandas = [{ ini: 0, fin: 60, nombre: "Les Combes 5", orden: 1 },
                  { ini: 60, fin: 1000, nombre: "Blanchimont", orden: 2 }];
  const ctx = lienzoConTexto(6);
  pintarZonas(ctx, bandas, 0, 1000, 0, 1000, 0, 50);
  assert.deepStrictEqual(ctx.puestos.map(x => x[0]), ["Blanchimont"],
                         "se escribio un nombre que no entra");
});

prueba("con sitio de sobra se escriben todos", () => {
  const bandas = [{ ini: 0, fin: 500, nombre: "Les Combes 5", orden: 1 },
                  { ini: 500, fin: 1000, nombre: "Blanchimont", orden: 2 }];
  const ctx = lienzoConTexto(6);
  pintarZonas(ctx, bandas, 0, 1000, 0, 1000, 0, 50);
  assert.strictEqual(ctx.puestos.length, 2);
});

prueba("las franjas no se salen de su panel", () => {
  /* Van recortadas: una franja que empieza antes del borde visible no puede
     pintar sobre el rotulo del eje. */
  const recortes = [];
  const ctx = lienzoConTexto(6);
  ctx.rect = (x, y, w, h) => recortes.push([x, y, w, h]);
  pintarZonas(ctx, [{ ini: -500, fin: 500, nombre: "X", orden: 1 }],
              0, 1000, 62, 1000, 10, 90);
  assert.deepStrictEqual(recortes, [[62, 10, 1000, 80]]);
});

/* ==================================================================
   15. LA LAMINA EXPORTA LO QUE HAY EN PANTALLA
   ------------------------------------------------------------------
   EL DEFECTO. La pantalla lee `segmentosComparacion`, que respeta el eje y el
   alcance elegidos; la lamina llamaba a `derivar(..., vueltaElegida, ...)`, que
   es siempre la distancia local de **una** vuelta. Con la carrera abierta y las
   vueltas 7 y 8 entre los 42.000 y los 56.000 m acumulados, el PNG salia con un
   eje de 0 a 7.000 m mientras las franjas ---que si preguntaban por el alcance
   global--- esperaban coordenadas acumuladas. Y sobre el eje de tiempo la
   lamina seguia rotulando metros.

   Se corre **el exportador de verdad** sobre un lienzo que anota lo que se le
   dibuja, y se compara con la vista que usa la pantalla.
   ================================================================== */

/* Un lienzo que recuerda cada texto y cada rectangulo, y que entrega un blob de
   mentira cuando le piden la imagen. */
function lienzoQueAnota() {
  const textos = [], rects = [];
  const ctx = {
    canvas: null, font: "", fillStyle: "", strokeStyle: "", lineWidth: 1,
    lineJoin: "", globalAlpha: 1, textAlign: "left",
    save(){}, restore(){}, translate(){}, rotate(){}, beginPath(){}, closePath(){},
    moveTo(){}, lineTo(){}, stroke(){}, clip(){}, setLineDash(){}, clearRect(){},
    strokeRect(){}, rect(){}, setTransform(){},
    fillRect: (x, y, w, h) => rects.push([x, y, w, h]),
    measureText: t => ({ width: String(t).length * 8 }),
    fillText: (t, x, y) => textos.push({ t: String(t), x: Math.round(x), y: Math.round(y) }),
  };
  return { ctx: ctx, textos: textos, rects: rects };
}

let _lamina = null, _guardado = null, _avisos = [];
function prepararExportacion() {
  _lamina = lienzoQueAnota();
  _guardado = null; _avisos = [];
  globalThis.document = {
    getElementById: () => null,
    querySelector: () => null,
    createElement: etiqueta => {
      if (etiqueta !== "canvas") return { style: {} };
      const cv = { width: 0, height: 0, style: {},
        getContext: () => _lamina.ctx,
        toBlob: fn => fn({ tipo: "png", alto: cv.height, ancho: cv.width }) };
      _lamina.ctx.canvas = cv;
      return cv;
    },
  };
  globalThis.tinta = () => "#000";
  globalThis.fechaAr = () => "09/09/2026";
  globalThis.nombreDeSesion = () => "Spa-Francorchamps";
  globalThis.cifra = (n) => String(Math.round(n));
  globalThis.avisar = (t, e) => _avisos.push({ t: t, error: !!e });
  globalThis.guardar = (nombre, datos) => { _guardado = { nombre: nombre, datos: datos }; };
  globalThis.FUENTES = { f1: { nombre: "F1 25" } };
  globalThis.ajustarLienzo = () => _lamina.ctx;
  globalThis.hayVueltas = () => (globalThis.estado.vueltas || []).length > 0;
}

const textoDeLaLamina = () => _lamina.textos.map(x => x.t).join(" | ");

/* Una sesion de comparacion: dos vueltas con acumulada **muy distinta** de la
   local, para que una exportacion que use la local no pueda pasar por
   casualidad. */
function sesionParaExportar() {
  conCircuito("carrera");
  dosVueltasAcumuladas();
  globalThis.estado.vueltas = [{ numero: 7, duracion_s: 120 }, { numero: 8, duracion_s: 120 }];
  globalThis.estado.disponibles = new Set(["speed"]);
  globalThis.estado.abierta = { session_id: SESION, fuente: "f1_25_udp_simulation" };
  globalThis.seleccion = new Set([CAR19]);
  globalThis.vueltaElegida = 7;
  ponerParrilla(parrillaDeSpa());
  armarAutos([CAR19]);
  METRICAS.forEach(m => { m.activa = m.id === "speed"; });
  prepararExportacion();
}

prueba("carrera: la lamina usa la distancia acumulada, no la de una vuelta", () => {
  /* La local va de 0 a 6.960 y la acumulada de 42.000 a 56.960: si la lamina
     usara la local, el eje empezaria en cero. */
  sesionParaExportar();
  const vista = vistaDeComparacion();
  assert.ok(vista.xMin > 41000, "la vista ya no es la acumulada: " + vista.xMin);
  exportarComparacion();
  const t = textoDeLaLamina();
  assert.ok(/42\.000|42000/.test(t.replace(/\s/g, "")), "el eje no arranca en la acumulada: " + t);
  assert.ok(!/\| 0 \|/.test(t), "el eje arranca en cero, que es la distancia local");
});

prueba("carrera: el eje se rotula como distancia de sesion", () => {
  sesionParaExportar();
  exportarComparacion();
  assert.ok(/DISTANCIA DE SESIÓN/.test(textoDeLaLamina()), textoDeLaLamina());
});

prueba("carrera: no se llama «vuelta N» a la carrera entera", () => {
  sesionParaExportar();
  exportarComparacion();
  const t = textoDeLaLamina();
  assert.ok(/2 vueltas/.test(t), t);
  assert.ok(!/· vuelta 7 ·/.test(t), "el subtitulo dice una vuelta: " + t);
  assert.strictEqual(_guardado.nombre, "senales-carrera-distancia.png");
});

prueba("una vuelta: la lamina usa la distancia de vuelta", () => {
  sesionParaExportar();
  _modo.alcance = "una"; _fijar.alcance("una");
  const vista = vistaDeComparacion();
  assert.ok(vista.xMax < 8000, "no es la distancia local: " + vista.xMax);
  exportarComparacion();
  const t = textoDeLaLamina();
  assert.ok(/DISTANCIA DE VUELTA/.test(t), t);
  assert.ok(/vuelta 7/.test(t), t);
  assert.strictEqual(_guardado.nombre, "senales-vuelta-7-distancia.png");
});

prueba("el zoom se aplica al mismo dominio que en pantalla", () => {
  sesionParaExportar();
  const completo = vistaDeComparacion();
  _fijar.zoom([0.25, 0.5]);
  const conZoom = vistaDeComparacion();
  const amplitud = completo.xMax - completo.xMin;
  assert.ok(Math.abs(conZoom.xMin - (completo.xMin + amplitud * 0.25)) < 0.01);
  assert.ok(Math.abs(conZoom.xMax - (completo.xMin + amplitud * 0.50)) < 0.01);
  exportarComparacion();
  assert.strictEqual(_guardado.nombre, "senales-carrera-distancia-tramo.png");
  const t = textoDeLaLamina();
  assert.ok(/tramo ampliado/.test(t), t);
  _fijar.zoom(null);
});

prueba("tiempo: el eje se rotula en segundos y no en metros", () => {
  sesionParaExportar();
  _modo.eje = "tiempo"; _fijar.eje("tiempo");
  const vista = vistaDeComparacion();
  assert.strictEqual(vista.unidad, "s");
  exportarComparacion();
  const t = textoDeLaLamina();
  assert.ok(/TIEMPO DE SESIÓN · SEGUNDOS/.test(t), t);
  assert.ok(!/METROS/.test(t), "sigue rotulando metros sobre el eje de tiempo: " + t);
  assert.strictEqual(_guardado.nombre, "senales-carrera-tiempo.png");
});

prueba("tiempo: el dominio de la lamina es el de la pantalla", () => {
  sesionParaExportar();
  _modo.eje = "tiempo"; _fijar.eje("tiempo");
  const vista = vistaDeComparacion();
  exportarComparacion();
  /* Los extremos del eje se escriben con una decima. */
  const t = textoDeLaLamina();
  assert.ok(t.indexOf(vista.xMin.toFixed(1)) !== -1, "falta " + vista.xMin.toFixed(1) + ": " + t);
  assert.ok(t.indexOf(vista.xMax.toFixed(1)) !== -1, "falta " + vista.xMax.toFixed(1) + ": " + t);
});

/* ---- la explicacion viaja con el archivo ---- */

prueba("la explicacion de las franjas se dibuja en la lamina", () => {
  /* No alcanza con que el exportador llame al ayudante: el archivo se abre sin
     el tablero al lado. */
  sesionParaExportar();
  exportarComparacion();
  assert.ok(/Franjas:/.test(textoDeLaLamina()), textoDeLaLamina());
});

prueba("la lamina distingue franjas por vuelta de intervalos entre referencias", () => {
  sesionParaExportar();
  exportarComparacion();
  const anchas = textoDeLaLamina();
  assert.ok(/una por vuelta cargada|intervalos entre puntos de referencia/.test(anchas), anchas);
});

prueba("con el eje temporal la lamina dice que no hay franjas y por que", () => {
  sesionParaExportar();
  _modo.eje = "tiempo"; _fijar.eje("tiempo");
  exportarComparacion();
  const t = textoDeLaLamina();
  assert.ok(/Sin franjas de circuito/.test(t), t);
  assert.ok(/eje de distancia/.test(t), t);
});

prueba("la explicacion se parte en renglones que entran en el ancho", () => {
  const ctx = { font: "", measureText: t => ({ width: t.length * 10 }) };
  const r = partirEnRenglones(ctx, "uno dos tres cuatro cinco seis", 100);
  assert.ok(r.length > 1, "no se partio");
  r.forEach(l => assert.ok(l.length * 10 <= 100 || l.split(" ").length === 1, l));
  assert.strictEqual(r.join(" "), "uno dos tres cuatro cinco seis");
});

prueba("el alto de la lamina reserva sitio para la explicacion", () => {
  /* Sin reservarlo, el ultimo renglon caia fuera de la imagen: medido, con dos
     renglones «aparecen.» quedaba cortado por abajo. */
  sesionParaExportar();
  exportarComparacion();
  const alto = _guardado.datos.alto;
  const ultimo = _lamina.textos.reduce((m, x) => Math.max(m, x.y), 0);
  assert.ok(ultimo <= alto - 8,
            "el ultimo texto cae en " + ultimo + " y la imagen mide " + alto);
});

/* ---- lo que la lamina conserva ---- */

prueba("la lamina conserva los vehiculos y las señales elegidas", () => {
  sesionParaExportar();
  exportarComparacion();
  const t = textoDeLaLamina();
  assert.ok(/NORRIS/.test(t), t);
  assert.ok(/VELOCIDAD/.test(t), t);
  assert.ok(/1 métricas|1 metricas/.test(t), t);
});

prueba("exportar no toca lo que llego ni lo que muestra la pantalla", () => {
  sesionParaExportar();
  const antes = JSON.stringify(globalThis.estado.series);
  const vistaAntes = vistaDeComparacion();
  exportarComparacion();
  assert.strictEqual(JSON.stringify(globalThis.estado.series), antes);
  const vistaDespues = vistaDeComparacion();
  assert.strictEqual(vistaDespues.xMin, vistaAntes.xMin);
  assert.strictEqual(vistaDespues.xMax, vistaAntes.xMax);
});

prueba("con cobertura parcial no se la presenta como completa", () => {
  /* La sesion declara cuatro vueltas y solo dos estan traidas: decir «4
     vueltas» seria afirmar que se ve algo que no esta. */
  sesionParaExportar();
  globalThis.estado.vueltas = [{ numero: 7 }, { numero: 8 }, { numero: 9 }, { numero: 10 }];
  const vista = vistaDeComparacion();
  assert.deepStrictEqual(vista.vueltas, [7, 8]);
  const pie = pieDeExportacion(vista);
  assert.ok(/2 de 4 vueltas cargadas/.test(pie), pie);
});

prueba("sin nada que dibujar se avisa en vez de exportar una lamina vacia", () => {
  sesionParaExportar();
  globalThis.estado.series = {};
  globalThis._selloSeries++;
  exportarComparacion();
  assert.strictEqual(_guardado, null);
  assert.ok(_avisos.some(a => a.error), JSON.stringify(_avisos));
});

prueba("las franjas obedecen el eje que se les pasa, no el modo global", () => {
  /* Es lo que impedia que las dos mitades del dibujo hablaran de cosas
     distintas: la lamina tomaba sus datos de un modo y las franjas de otro. */
  conCircuito("carrera");
  dosVueltasAcumuladas();
  _fijar.eje("tiempo");                       // el global dice tiempo
  const [conDistancia] = bandasParaElTramo(42000, 49000, CAR19, 1400, "distancia", "carrera");
  /* Y que sean las **de curva**: si `zonasDeCurva` leyera el global diria que
     el eje es temporal, se caeria a las franjas por vuelta y esta prueba
     pasaria igual sin haber comprobado nada. */
  assert.ok(conDistancia && conDistancia.some(b => b.nombre === "La Source"),
            "no son las franjas de referencia: " +
            (conDistancia || []).map(b => b.nombre).join("|"));
  _fijar.eje("distancia");                    // el global dice distancia
  const [conTiempo, nota] = bandasParaElTramo(0, 130, CAR19, 1400, "tiempo", "carrera");
  assert.strictEqual(conTiempo, null, "ignoro el eje que se le paso");
  assert.ok(/eje de distancia/.test(nota), nota);
});

prueba("el alcance tambien llega como argumento", () => {
  conCircuito("una");
  dosVueltasAcumuladas();
  _fijar.alcance("una");                      // el global dice una vuelta
  const b = bandasDeVuelta(42000, 56000, CAR19, "distancia", "carrera");
  assert.ok(b && b.length === 2, "ignoro el alcance que se le paso");
});

prueba("la explicacion y la leyenda no se pisan con el eje", () => {
  /* Sin reservar el alto, la leyenda subia sobre el rotulo del eje: el texto
     entraba en la imagen pero encima de otra cosa. */
  sesionParaExportar();
  exportarComparacion();
  const rotuloEje = _lamina.textos.find(x => /DISTANCIA DE SESIÓN/.test(x.t));
  const leyenda = _lamina.textos.find(x => x.t === "NORRIS");
  const explicacion = _lamina.textos.filter(x => /^Franjas:|^Sin franjas/.test(x.t))[0];
  assert.ok(rotuloEje && leyenda && explicacion, "falta alguno de los tres");
  assert.ok(leyenda.y - rotuloEje.y >= 50,
    "la leyenda quedo a " + (leyenda.y - rotuloEje.y) + " px del rótulo del eje");
  assert.ok(explicacion.y > leyenda.y,
    "la explicación quedó encima de la leyenda");
  const ultimo = _lamina.textos.reduce((m, x) => Math.max(m, x.y), 0);
  assert.ok(ultimo <= _guardado.datos.alto - 8, "el último texto se sale");
});

prueba("la explicacion describe los extremos como son", () => {
  /* Decia que **toda** franja termina en la curva siguiente, y la ultima
     termina donde termina la vuelta o la cobertura. */
  conCircuito("una");
  const [, nota] = bandas(0, 7004, CAR19, 1400);
  assert.ok(/la última llega hasta donde termina la vuelta o la cobertura/.test(nota), nota);
  assert.ok(/queda sin franja/.test(nota), "no dice que el tramo inicial no tiene franja");
});

prueba("no se llama «curva» a lo que el catalogo publica como referencia", () => {
  conCircuito("una");
  const [, nota] = bandas(0, 7004, CAR19, 1400);
  assert.ok(/puntos de referencia del catálogo/.test(nota), nota);
  assert.ok(!/entrada de curva/.test(nota), nota);
  assert.ok(/el ancho de la curva no se declara/.test(nota), nota);
});

/* ==================================================================
   16. LA UNIDAD Y LA QUIETUD SON DE LA FUENTE, NO DE LA TABLA
   ------------------------------------------------------------------
   `METRICAS` declara la unidad del simulador, donde el acelerador es un
   porcentaje de recorrido del pedal. En el bus esas dos casillas son
   `gas_pressed` y `brake_pressed`, que la base guarda con unidad `bool`: el
   panel escribia «%» con «mín 0 · máx 1» debajo, un porcentaje imposible.

   Y una raya plana en cero no dice si el canal esta roto o si no paso nada. Con
   el simulador daba igual; con el bus, medio conjunto de datos son tramos de
   autopista con los pedales sueltos el minuto entero.
   ================================================================== */

prueba("en el bus los pedales no se miden en por ciento", () => {
  globalThis.fuente = "can";
  assert.strictEqual(unidadDeCanal("throttle"), "pisado");
  assert.strictEqual(unidadDeCanal("brake"), "pisado");
});

prueba("en la simulacion siguen siendo por ciento", () => {
  globalThis.fuente = "f1";
  assert.strictEqual(unidadDeCanal("throttle"), "%");
  assert.strictEqual(unidadDeCanal("brake"), "%");
});

prueba("la direccion son grados en el bus y una razon en la simulacion", () => {
  /* Es la misma casilla y dos señales distintas: `steer_angle` en grados contra
     `steering_normalized`, que va de -1 a 1. */
  globalThis.fuente = "can";
  assert.strictEqual(unidadDeCanal("steer"), "°");
  globalThis.fuente = "f1";
  assert.strictEqual(unidadDeCanal("steer"), "norm.");
});

prueba("un canal sin excepcion usa la unidad de la tabla en las dos fuentes", () => {
  ["f1", "can"].forEach(f => {
    globalThis.fuente = f;
    assert.strictEqual(unidadDeCanal("speed"), "km/h");
    assert.strictEqual(unidadDeCanal("glong"), "g");
  });
});

prueba("un canal que no existe no rompe ni inventa unidad", () => {
  globalThis.fuente = "f1";
  assert.strictEqual(unidadDeCanal("no-existe"), "");
});

prueba("un pedal suelto todo el tramo se dice, no se deja mudo", () => {
  globalThis.fuente = "can";
  assert.strictEqual(sinCambiosEnElTramo("brake", 0), "sin pisadas en este tramo");
  assert.strictEqual(sinCambiosEnElTramo("throttle", 0), "sin pisadas en este tramo");
});

prueba("y un pedal pisado todo el tramo tambien", () => {
  globalThis.fuente = "can";
  assert.strictEqual(sinCambiosEnElTramo("throttle", 1), "pisado todo el tramo");
});

prueba("de una magnitud quieta solo se puede decir su valor", () => {
  /* «Sin pisadas» no aplica a una velocidad: de una magnitud constante lo unico
     que se puede afirmar es cuanto valia. */
  globalThis.fuente = "can";
  assert.strictEqual(sinCambiosEnElTramo("speed", 107.5), "sin cambios · 107,50 km/h");
});

prueba("el pie escribe la quietud solo cuando el minimo iguala al maximo", () => {
  /* La condicion es del dibujo y se comprueba donde se dibuja; aca se fija que
     el texto exista para las dos formas. */
  globalThis.fuente = "can";
  assert.notStrictEqual(sinCambiosEnElTramo("brake", 0), "");
  assert.notStrictEqual(sinCambiosEnElTramo("speed", 0), "");
});

/* ==================================================================
   17. EL RECORRIDO DERIVADO: UBICAR POR INSTANTE, PINTAR POR SEÑAL
   ------------------------------------------------------------------
   El bus no publica coordenadas. La forma del recorrido sale de integrar
   velocidad y velocidad de guiñada, y cada punto trae el instante en que el
   vehiculo estuvo ahi. Eso permite dos cosas que un trazado sin marcas no
   permite: colocar el coche por su instante ---el mismo que ya comparten los
   instrumentos--- y pintar el recorrido con lo que se estaba midiendo.

   LOS DEFECTOS QUE ESTO CUIDA.

   1. Colocar el coche por la fraccion del cabezal sobre la longitud del camino.
      La fraccion es de tiempo y el camino esta parametrizado por longitud: las
      dos coinciden **solo** con velocidad constante. En un tramo de autopista
      casi lo es, que es justo lo que haria pasar el error por bueno.
   2. Cerrar el camino con `Z`. Un circuito vuelve a su largada; un tramo de
      ruta no. Cerrarlo dibuja una recta del final al principio que nadie
      recorrio.
   3. Interpolar una señal escalonada sobre el recorrido: entre pisado y suelto
      no hay medio pisado.
   4. Dejar el cabo final sin pintar, porque los tramos se cortaban en el ultimo
      multiplo del paso y no en el ultimo punto.
   ================================================================== */

/* Un recorrido derivado a escala: `n` puntos con su instante, la forma armada
   con la misma funcion que usa el tablero y sin cerrar. */
function recorridoDerivado(mundo, marcas) {
  const armado = trazadoAPath(mundo, false, false);
  const pista = {
    path: armado.path,
    proyectar: armado.proyectar,
    proyectarMundo: armado.proyectarMundo,
    mundo: mundo,
    marcas_ms: marcas,
    origen_utc: iso(T0),
    derivado: true,
    muestras: mundo.length,
    curvas: [],
  };
  /* `PISTA` vive dentro de la funcion construida: se fija por el gancho y se
     devuelve, porque leerla desde `globalThis` devolveria otra cosa. */
  _fijar.pista(pista);
  return { armado: armado, pista: pista };
}

/* Veinte puntos cada 100 ms sobre una ese, con las series de las dos vueltas
   ya cargadas: es el mismo tramo que `dosVueltasConCronometro` describe. */
function tramoDelBus() {
  dosVueltasConCronometro();
  const mundo = [], marcas = [];
  for (let i = 0; i < 20; i++) {
    mundo.push([i * 10, Math.sin(i / 4) * 30]);
    marcas.push(i * 100);
  }
  return recorridoDerivado(mundo, marcas);
}

prueba("antes del primer punto medido el vehiculo no esta en ningun lado", () => {
  tramoDelBus();
  assert.strictEqual(puntoDelBusEn(T0 - 1), null,
                     "ubico el coche en un instante anterior al recorrido");
  assert.strictEqual(_indiceEnElRecorrido(-1), null);
});

prueba("en el primer instante medido ya esta, y esta en el primer punto", () => {
  tramoDelBus();
  assert.strictEqual(_indiceEnElRecorrido(0), 0);
});

prueba("la busqueda binaria da lo mismo que recorrer la lista", () => {
  /* Marcas irregulares a proposito: un bus pierde tramas y los saltos no son
     todos iguales. */
  const marcas = [0, 7, 90, 91, 400, 1200, 1201, 1600, 1900];
  const mundo = marcas.map((m, i) => [i * 10, i * i]);
  recorridoDerivado(mundo, marcas);
  for (let t = -50; t <= 2000; t += 3) {
    let esperado = null;
    for (let k = 0; k < marcas.length; k++) if (marcas[k] <= t) esperado = k;
    assert.strictEqual(_indiceEnElRecorrido(t), esperado, "en t=" + t);
  }
});

prueba("el coche va por su instante y no por la longitud del camino", () => {
  /* Un tramo donde el vehiculo se detiene: la primera mitad del tiempo cubre
     casi todo el trazo y la segunda casi nada. Colocarlo por la fraccion de
     longitud lo pondria en el medio del dibujo; su instante dice que ya estaba
     al final. */
  const mundo = [], marcas = [];
  for (let i = 0; i < 10; i++) { mundo.push([i * 100, 0]); marcas.push(i * 100); }
  for (let i = 0; i < 10; i++) { mundo.push([900 + i, 0]); marcas.push(1000 + i * 100); }
  recorridoDerivado(mundo, marcas);
  const mitadDelTiempo = puntoDelBusEn(T0 + 950);
  assert.strictEqual(mitadDelTiempo.indice, 9,
                     "a mitad de tiempo no estaba en el punto que midio el reloj");
  /* Y en el mundo ya recorrio 900 de los 909 metros: la mitad del tiempo es el
     97 % del camino, no el 50 %. */
  const total = 909, hecho = 900;
  assert.ok(hecho / total > 0.95, "el tramo de prueba no distingue las dos cosas");
});

prueba("el punto se proyecta con la transformacion del camino dibujado", () => {
  const armado = tramoDelBus();
  const p = puntoDelBusEn(T0 + 700);
  const q = armado.armado.proyectarMundo(70, Math.sin(7 / 4) * 30);
  assert.ok(Math.abs(p.x - q[0]) < 1e-9 && Math.abs(p.y - q[1]) < 1e-9,
            "la marca no cae sobre el punto que dibuja el camino");
});

prueba("sin origen declarado no se ubica nada, y no se inventa uno", () => {
  const pista = tramoDelBus().pista;
  _fijar.pista(Object.assign({}, pista, { origen_utc: null }));
  assert.strictEqual(puntoDelBusEn(T0 + 500), null);
  _fijar.pista(Object.assign({}, pista, { origen_utc: "no es una fecha" }));
  assert.strictEqual(puntoDelBusEn(T0 + 500), null);
});

prueba("un tramo de ruta no se cierra: no vuelve a donde empezo", () => {
  const mundo = [[0, 0], [10, 1], [20, 0], [30, 2]];
  assert.ok(!/ Z$/.test(trazadoAPath(mundo, false, false).path),
            "el camino del bus cierra con Z y dibuja una recta que nadie hizo");
  assert.ok(/ Z$/.test(trazadoAPath(mundo, false, true).path),
            "un circuito dejo de cerrarse");
});

prueba("hay un valor de la señal por cada punto del recorrido", () => {
  const pista = tramoDelBus().pista;
  const v = valoresSobreElRecorrido("speed");
  assert.strictEqual(v.length, pista.marcas_ms.length);
  assert.ok(v.every(x => x !== null && Number.isFinite(x)),
            "quedaron puntos sin valor sobre un tramo con dato en todos");
});

prueba("la señal se lee en el instante del punto, no en su indice", () => {
  tramoDelBus();
  const v = valoresSobreElRecorrido("speed");
  /* La vuelta 1 va de 200 km/h a 219, una muestra cada 100 ms, y el recorrido
     tiene sus puntos en las mismas marcas. */
  assert.strictEqual(v[0], 200);
  assert.strictEqual(v[7], 207);
  assert.strictEqual(v[19], 219);
});

prueba("una señal escalonada no se degrada sobre el recorrido", () => {
  /* El puesto salta de P5 a P4 a los 1000 ms. Los puntos del recorrido caen
     **entre** muestras ---a mitad de camino, que es el caso general: la
     reconstruccion tiene su propia cadencia y no la del canal--- de modo que
     interpolar daria un P4,5 justo donde se produjo el adelantamiento. */
  dosVueltasConCronometro();
  const mundo = [], marcas = [];
  for (let i = 0; i < 19; i++) { mundo.push([i * 10, i * 2]); marcas.push(i * 100 + 50); }
  recorridoDerivado(mundo, marcas);
  const v = valoresSobreElRecorrido("posicion");
  assert.ok(v.every(x => x === null || x === 4 || x === 5),
            "aparecio un puesto intermedio sobre el recorrido: " + v.join(","));
  assert.strictEqual(v[9], 5, "a los 950 ms el adelantamiento todavia no ocurrio");
  assert.strictEqual(v[10], 4);
});

prueba("sin recorrido o sin serie no hay valores, y no hay ceros", () => {
  const pista = tramoDelBus().pista;
  assert.strictEqual(valoresSobreElRecorrido("no-existe"), null);
  _fijar.pista(Object.assign({}, pista, { marcas_ms: null }));
  assert.strictEqual(valoresSobreElRecorrido("speed"), null);
});

prueba("los tramos cubren el recorrido entero, hasta el ultimo punto", () => {
  /* Con mas puntos que tramos el paso es mayor que uno y el cabo final se caia:
     el bucle cortaba en el ultimo multiplo del paso. */
  const n = TRAMOS_DE_LA_TRAZA * 5 + 7;
  const mundo = [], marcas = [];
  for (let i = 0; i < n; i++) { mundo.push([i, Math.sin(i / 30) * 40]); marcas.push(i); }
  const armado = recorridoDerivado(mundo, marcas).armado;
  const tramos = tramosDelRecorrido(mundo.map(() => 1));
  /* Del orden de `TRAMOS_DE_LA_TRAZA`: el paso es entero, asi que sobra algun
     tramo, y el cabo final agrega uno mas. Lo que no puede es haber uno por
     punto ---seiscientos nodos que nadie distingue--- ni faltar la mitad. */
  assert.ok(tramos.length >= TRAMOS_DE_LA_TRAZA &&
            tramos.length <= TRAMOS_DE_LA_TRAZA + 2,
            "se dibujaron " + tramos.length + " tramos");
  const ultimo = armado.proyectarMundo(mundo[n - 1][0], mundo[n - 1][1]);
  const cierre = "L" + ultimo[0].toFixed(1) + " " + ultimo[1].toFixed(1);
  assert.ok(tramos[tramos.length - 1].d.endsWith(cierre),
            "el ultimo punto del recorrido se quedo sin pintar");
});

prueba("los tramos se encadenan sin agujeros entre uno y el siguiente", () => {
  const n = 617;
  const mundo = [], marcas = [];
  for (let i = 0; i < n; i++) { mundo.push([i, (i % 17) * 3]); marcas.push(i); }
  recorridoDerivado(mundo, marcas);
  const tramos = tramosDelRecorrido(mundo.map(() => 1));
  for (let k = 1; k < tramos.length; k++) {
    const arranca = tramos[k].d.slice(1).split(" ").slice(0, 2).join(" ");
    const termina = tramos[k - 1].d.split("L").pop();
    assert.strictEqual(arranca, termina,
                       "hay un salto entre el tramo " + (k - 1) + " y el " + k);
  }
});

prueba("con menos puntos que tramos se dibuja un tramo por punto", () => {
  const pista = tramoDelBus().pista;
  const tramos = tramosDelRecorrido(pista.mundo.map(() => 1));
  assert.strictEqual(tramos.length, pista.mundo.length - 1);
});

prueba("el valor de un tramo es el del punto donde termina", () => {
  tramoDelBus();
  const valores = valoresSobreElRecorrido("speed");
  const tramos = tramosDelRecorrido(valores);
  assert.strictEqual(tramos[0].valor, 201);
  assert.strictEqual(tramos[tramos.length - 1].valor, 219);
});

prueba("un recorrido de menos de dos puntos no da tramos", () => {
  recorridoDerivado([[0, 0]], [0]);
  assert.deepStrictEqual(tramosDelRecorrido([1]), []);
  assert.deepStrictEqual(tramosDelRecorrido(null), []);
});

/* Los dos extremos del tema oscuro, escritos aca solo para no depender de un
   `getComputedStyle` que en node no existe. Lo que se comprueba es la mezcla. */
const EXTREMOS = { baja: [109, 139, 161], alta: [216, 180, 254] };

prueba("un tramo sin valor se pinta con la tinta de lo que no se sabe", () => {
  const nada = tintaDelValor(null, 0, 10, EXTREMOS);
  assert.strictEqual(nada, tintaDelValor(undefined, 0, 10, EXTREMOS));
  assert.strictEqual(nada, tintaDelValor(NaN, 0, 10, EXTREMOS));
  assert.ok(!/^rgb\(/.test(nada),
            "un tramo sin dato entro en la escala de color como si tuviera uno");
});

prueba("la escala llega a sus dos extremos, y se satura", () => {
  assert.strictEqual(tintaDelValor(0, 0, 10, EXTREMOS), "rgb(109, 139, 161)");
  assert.strictEqual(tintaDelValor(10, 0, 10, EXTREMOS), "rgb(216, 180, 254)");
  /* Fuera de los extremos no se sale de la escala ni se envuelve. */
  assert.strictEqual(tintaDelValor(-5, 0, 10, EXTREMOS), "rgb(109, 139, 161)");
  assert.strictEqual(tintaDelValor(99, 0, 10, EXTREMOS), "rgb(216, 180, 254)");
});

prueba("la escala se resuelve en color y no en un color-mix con variables", () => {
  /* Un `color-mix(... var(--acento) ...)` dentro de un atributo de presentacion
     depende de que el navegador resuelva variables ahi. Si no lo hace, el valor
     es invalido y el trazo no se dibuja: se ve exactamente igual que si el
     tablero no hubiera hecho nada. */
  const c = tintaDelValor(5, 0, 10, EXTREMOS);
  assert.ok(/^rgb\(\d+, \d+, \d+\)$/.test(c), c);
  assert.ok(!/var\(|color-mix/.test(c));
});

prueba("los extremos que elige la escala se separan en el tema real", () => {
  /* Esto corre `extremosDeLaTraza` contra la paleta que la hoja de estilos
     declara: si alguien vuelve a elegir dos fichas que son el mismo color con
     distinta opacidad, la escala deja de ordenar nada y esto lo dice. */
  const PALETA = {
    "--texto-tenue": "#6d8ba1", "--acento-vivo": "#d8b4fe",
    "--acento": "#b794f6", "--linea-fuerte": "rgba(183,148,246,.34)",
    "--linea": "rgba(183,148,246,.18)",
  };
  const antes = globalThis.tinta;
  globalThis.tinta = n => PALETA[n];
  try {
    const e = extremosDeLaTraza();
    const separacion = Math.round(Math.hypot(
      e.baja[0] - e.alta[0], e.baja[1] - e.alta[1], e.baja[2] - e.alta[2]));
    assert.ok(separacion > 100,
              "los dos extremos de la escala son casi el mismo color: " + separacion);
    assert.notDeepStrictEqual(e.baja, e.alta);
  } finally { globalThis.tinta = antes; }
});

prueba("los dos extremos de la escala son colores distintos de verdad", () => {
  /* El defecto: la escala iba de `--linea-fuerte` a `--acento`, y en el tema
     oscuro `--linea-fuerte` **es** el acento al 34 % de opacidad. Era un solo
     color cambiando de transparencia sobre un fondo oscuro, en una linea de
     tres pixeles: no se distinguia nada. */
  const baja = _rgbDe("rgba(183,148,246,.34)"), alta = _rgbDe("#b794f6");
  assert.deepStrictEqual(baja, alta,
                         "esta prueba dejo de describir el defecto que cuida");
  const distancia = [0, 1, 2].reduce(
    (s, i) => s + Math.abs(EXTREMOS.baja[i] - EXTREMOS.alta[i]), 0);
  assert.ok(distancia > 150, "los extremos de la escala casi no se diferencian: " + distancia);
});

prueba("una señal quieta no pinta el recorrido de un extremo", () => {
  /* Con minimo igual a maximo la razon seria 0/0. Se pinta a medio camino: la
     señal existe y no se movio, que no es lo mismo que estar en el minimo. */
  const medio = tintaDelValor(7, 7, 7, EXTREMOS);
  assert.strictEqual(medio, tintaDelValor(5, 0, 10, EXTREMOS));
  assert.notStrictEqual(medio, tintaDelValor(0, 0, 10, EXTREMOS));
});

prueba("un color de la hoja de estilos se lee en cualquiera de sus formas", () => {
  assert.deepStrictEqual(_rgbDe("#b794f6"), [183, 148, 246]);
  assert.deepStrictEqual(_rgbDe("#fff"), [255, 255, 255]);
  assert.deepStrictEqual(_rgbDe("rgb(109, 139, 161)"), [109, 139, 161]);
  /* La opacidad se descarta: la rampa se hace con color, no con transparencia. */
  assert.deepStrictEqual(_rgbDe("rgba(183, 148, 246, .34)"), [183, 148, 246]);
  assert.deepStrictEqual(_rgbDe("rgb(183 148 246 / 34%)"), [183, 148, 246]);
});

prueba("un color ilegible no rompe el dibujo", () => {
  assert.deepStrictEqual(_rgbDe(""), [128, 128, 128]);
  assert.deepStrictEqual(_rgbDe(null), [128, 128, 128]);
});

prueba("tener posicion medida y tener metro medido son dos preguntas", () => {
  /* El defecto: pedir el recorrido reconstruido cuando falta el **eje de
     distancia**. OpenF1 no tiene metro medido y si publica `track_position_*`,
     de modo que esa condicion le habria quitado el trazado que si tiene. */
  globalThis.fuente = "openf1";
  assert.strictEqual(hayEjeDeDistancia(), false, "OpenF1 no declara distancia");
  assert.strictEqual(hayCoordenadasMedidas(), true,
                     "a OpenF1 se le quito el trazado que si publica");
});

prueba("el elector dice cual señal se movio antes de que la elijan", () => {
  /* En un minuto de autopista casi ninguna cambia. Sin esto hay que probar las
     trece pastillas para descubrir cuales tres tienen algo que mostrar. */
  reiniciar();
  globalThis.fuente = "can";
  globalThis.canalesDeLaFuente = () => CANALES_POR_FUENTE.can;
  cargarVuelta(1, [0, 100, 200, 300],
               { distancia_m: [0, 5, 10, 15], speed: [107, 108, 109, 108],
                 gas_pressed: [0, 0, 0, 0], brake_pressed: [0, 0, 1, 0] },
               { gas_pressed: "bool", brake_pressed: "bool" });
  globalThis.estado.vueltas = [{ numero: 1, duracion_s: 0.3,
                                 desde_utc: iso(T0), hasta_utc: iso(T0 + 300) }];
  armarAutos([CAR19]);
  const por = {};
  senalesParaElRecorrido().forEach(s => { por[s.id] = s; });
  assert.ok(por.speed, "la velocidad no llego al elector");
  assert.strictEqual(por.speed.quieta, false, "una velocidad que cambio se dio por quieta");
  assert.strictEqual(por.throttle.quieta, true, "un pedal nunca pisado se ofrecio como si tuviera algo");
  assert.strictEqual(por.brake.quieta, false, "una pisada en el tramo se perdio");
});

prueba("de una señal quieta se guarda el valor, para poder decirlo", () => {
  reiniciar();
  globalThis.fuente = "can";
  globalThis.canalesDeLaFuente = () => CANALES_POR_FUENTE.can;
  cargarVuelta(1, [0, 100], { distancia_m: [0, 5], speed: [107, 107] }, {});
  globalThis.estado.vueltas = [{ numero: 1, duracion_s: 0.1,
                                 desde_utc: iso(T0), hasta_utc: iso(T0 + 100) }];
  armarAutos([CAR19]);
  const s = senalesParaElRecorrido().find(x => x.id === "speed");
  assert.strictEqual(s.quieta, true);
  assert.strictEqual(sinCambiosEnElTramo(s.id, s.valor), "sin cambios · 107,00 km/h");
});

prueba("una señal sin dato no se ofrece en el elector", () => {
  reiniciar();
  globalThis.fuente = "can";
  globalThis.canalesDeLaFuente = () => CANALES_POR_FUENTE.can;
  cargarVuelta(1, [0, 100], { distancia_m: [0, 5], speed: [107, 108] }, {});
  globalThis.estado.vueltas = [{ numero: 1, duracion_s: 0.1,
                                 desde_utc: iso(T0), hasta_utc: iso(T0 + 100) }];
  armarAutos([CAR19]);
  const ids = senalesParaElRecorrido().map(s => s.id);
  assert.ok(ids.includes("speed"));
  assert.ok(!ids.includes("throttle"), "se ofrecio una señal que la sesion no trajo");
});

prueba("un pedal que nunca se piso no se cuenta como un rango", () => {
  /* «Acelerador · de 0.00 a 0.00 pisado» son dos cifras iguales que el ojo lee
     como un rango, y deja creyendo que el tablero no hizo nada. */
  globalThis.fuente = "can";
  assert.strictEqual(pieDelRecorrido("throttle", 0, 0),
                     "Acelerador · sin pisadas en este tramo");
  assert.ok(!/0\.00 a 0\.00/.test(pieDelRecorrido("throttle", 0, 0)));
});

prueba("una magnitud quieta dice cuanto valia, no un rango de cero", () => {
  globalThis.fuente = "can";
  assert.strictEqual(pieDelRecorrido("speed", 107.5, 107.5),
                     "Velocidad · sin cambios · 107,50 km/h");
});

prueba("una señal que se movio escribe sus dos extremos y su unidad", () => {
  globalThis.fuente = "can";
  assert.strictEqual(pieDelRecorrido("speed", 106.59, 108.51),
                     "Velocidad · de 106,59 a 108,51 km/h");
});

prueba("sin dato sobre el recorrido se dice eso y no un cero", () => {
  globalThis.fuente = "can";
  assert.strictEqual(pieDelRecorrido("speed", Infinity, -Infinity),
                     "Velocidad · sin dato sobre este recorrido");
});

prueba("una columna que llego entera en nulos no se ofrece", () => {
  /* No es lo mismo que la sesion no traiga la casilla: la casilla vino y sin un
     solo valor. La serie existe y esta vacia. */
  reiniciar();
  globalThis.fuente = "can";
  globalThis.canalesDeLaFuente = () => CANALES_POR_FUENTE.can;
  cargarVuelta(1, [0, 100], { distancia_m: [0, 5], speed: [107, 108],
                              gas_pressed: [null, null] },
               { gas_pressed: "bool" });
  globalThis.estado.vueltas = [{ numero: 1, duracion_s: 0.1,
                                 desde_utc: iso(T0), hasta_utc: iso(T0 + 100) }];
  armarAutos([CAR19]);
  /* El contrato de `serieTemporal`: o hay serie con muestras, o no hay serie.
     Una columna sin un solo valor cae del lado del `null`. */
  assert.strictEqual(serieTemporal("throttle", 1, CAR19), null);
  assert.ok(!senalesParaElRecorrido().some(s => s.id === "throttle"),
            "se ofrecio pintar el recorrido con una columna sin un solo valor");
});

prueba("una forma derivada la explica quien la calculo", () => {
  /* El texto viajaba en la respuesta, se guardaba en `PISTA.advertencia` y no
     se mostraba en ningun lado: la explicacion existia y no se daba. */
  globalThis.fuente = "can";
  _fijar.pista({ derivado: true, advertencia: "reconstruido por integracion de velocidad y guiñada" });
  assert.strictEqual(explicacionDelTrazado(),
                     "reconstruido por integracion de velocidad y guiñada");
});

prueba("si el punto de acceso no explico nada, lo explica la fuente", () => {
  globalThis.fuente = "can";
  _fijar.pista({ derivado: true, advertencia: "" });
  assert.strictEqual(explicacionDelTrazado(), porQueNoHayCoordenadas("can"));
});

prueba("un circuito medido sigue explicandose por su fuente", () => {
  globalThis.fuente = "f1";
  _fijar.pista({ derivado: false });
  /* `FUENTES_REALES` y no `FUENTES`: una prueba de mas arriba deja un doble en
     `globalThis` y la funcion extraida lee el del archivo. */
  assert.strictEqual(explicacionDelTrazado(), FUENTES_REALES.f1.pista);
  assert.ok(/world_position/.test(explicacionDelTrazado()),
            "un trazado medido dejo de nombrar la señal que lo declara");
});

prueba("a OpenF1 se le sigue pidiendo su trazado declarado", () => {
  /* La consulta que sale es la comprobacion: `/trazado` para las fuentes con
     posicion medida, `/can/recorrido` solo para el bus. */
  globalThis.estado.vueltas = [];
  rutasPedidas();
  globalThis.fuente = "openf1";
  pedirTrazado("/sesiones/x");
  const r = rutasPedidas();
  assert.strictEqual(r.length, 1);
  assert.ok(r[0].startsWith("/sesiones/x/trazado"),
            "OpenF1 termino pidiendo el recorrido reconstruido: " + r[0]);
});

prueba("al bus se le pide la forma reconstruida y no un trazado vacio", () => {
  globalThis.estado.vueltas = [];
  rutasPedidas();
  globalThis.fuente = "can";
  pedirTrazado("/sesiones/x");
  assert.deepStrictEqual(rutasPedidas(), ["/can/recorrido"]);
});

prueba("la simulacion no cambio de camino", () => {
  globalThis.estado.vueltas = [];
  rutasPedidas();
  globalThis.fuente = "f1";
  pedirTrazado("/sesiones/x");
  assert.ok(rutasPedidas()[0].startsWith("/sesiones/x/trazado"));
});

prueba("solo el bus necesita que la forma se reconstruya", () => {
  assert.strictEqual(hayCoordenadasMedidas("f1"), true);
  assert.strictEqual(hayCoordenadasMedidas("openf1"), true);
  assert.strictEqual(hayCoordenadasMedidas("can"), false);
});

prueba("las dos tablas cubren las mismas fuentes", () => {
  /* Una fuente nueva sin fila en una de las dos se leeria como «tiene de todo»,
     que es el fallo silencioso. */
  assert.deepStrictEqual(Object.keys(COORDENADAS_POR_FUENTE).sort(),
                         Object.keys(EJE_DE_DISTANCIA_POR_FUENTE).sort());
});

prueba("la fuente que no publica posicion dice por que", () => {
  const porque = porQueNoHayCoordenadas("can");
  assert.ok(porque.length > 20, "el motivo esta vacio");
  assert.strictEqual(porQueNoHayCoordenadas("f1"), "esta fuente no declara posición medida",
                     "una fuente con posicion no tiene motivo que dar");
});

/* ==================================================================
   18. LA SEÑAL QUE HABILITA UN PANEL SE LLAMA DISTINTO EN CADA FUENTE
   ------------------------------------------------------------------
   El panel de aceleraciones se tapaba con «sin acelerometro» sobre una sesion
   del bus que trae las dos aceleraciones y la guiñada completas ---cincuenta de
   cincuenta muestras en las tres---. La razon: `data-necesita` traia
   `g_force_lateral`, que es como se llama la señal en el simulador. El bus
   publica `accel_lateral`.

   El propio panel si sabia leer el bus: su encabezado escribia «2 ejes +
   guiñada» al lado del cartel que decia que no habia acelerometro, y sus tres
   renglones nombran `accel_longitudinal`, `accel_lateral` y `yaw_rate`. Lo
   unico que no sabia era la compuerta que decide si se muestra.
   ================================================================== */

const HTML = fs.readFileSync(
  path.join(__dirname, "..", "..", "dashboard", "index.html"), "utf8");

/* Lo que cada panel del HTML publicado declara necesitar. Se lee del archivo:
   escribirlo aca dejaria pasar el dia en que alguien agregue un panel. */
function loQuePidenLosPaneles() {
  const pide = {};
  const re = /data-panel="([^"]+)"[^>]*data-necesita="([^"]+)"/g;
  let m;
  while ((m = re.exec(HTML))) pide[m[1]] = m[2];
  return pide;
}

prueba("el bus habilita las aceleraciones con el nombre que el bus publica", () => {
  const pide = loQuePidenLosPaneles();
  assert.ok(pide.aceleraciones, "el panel de aceleraciones dejo de declarar que necesita");
  globalThis.fuente = "can";
  assert.strictEqual(nombreDeSenal(pide.aceleraciones), "accel_lateral",
                     "el panel pide una señal que el bus no publica: se tapa con «sin acelerometro»");
  globalThis.fuente = "f1";
  assert.strictEqual(nombreDeSenal(pide.aceleraciones), "g_force_lateral",
                     "la simulacion perdio su acelerometro");
});

prueba("el bus con acelerometro enciende el panel de aceleraciones", () => {
  /* La comprobacion de punta a punta: lo que el HTML declara, contra lo que la
     API devolvio. Sobre sample_01 son 50 de 50 muestras en las tres señales. */
  const pide = loQuePidenLosPaneles();
  globalThis.estadoSesion = "cargado";
  globalThis.fuente = "can";
  globalThis.estado.disponibles = new Set(
    ["speed", "accel_lateral", "accel_longitudinal", "yaw_rate", "gas_pressed"]);
  assert.strictEqual(panelEstaPresente(pide.aceleraciones), true,
                     "el panel se tapa con «sin acelerometro» sobre una sesion que lo trae");
});

prueba("y no lo enciende sobre lo que el bus no publica", () => {
  const pide = loQuePidenLosPaneles();
  globalThis.estadoSesion = "cargado";
  globalThis.fuente = "can";
  globalThis.estado.disponibles = new Set(["speed", "accel_lateral", "yaw_rate"]);
  assert.strictEqual(panelEstaPresente(pide.puesta), false,
                     "se prometio una puesta a punto que el bus no manda");
  assert.strictEqual(panelEstaPresente(pide.motor), false);
  assert.strictEqual(panelEstaPresente(pide.clima), false);
});

prueba("la simulacion enciende el mismo panel con su propio nombre", () => {
  const pide = loQuePidenLosPaneles();
  globalThis.estadoSesion = "cargado";
  globalThis.fuente = "f1";
  globalThis.estado.disponibles = new Set(["g_force_lateral", "setup_front_wing"]);
  assert.strictEqual(panelEstaPresente(pide.aceleraciones), true);
  assert.strictEqual(panelEstaPresente(pide.puesta), true);
});

prueba("sin sesion abierta no hay panel presente, aunque quede algo colgado", () => {
  const pide = loQuePidenLosPaneles();
  globalThis.estadoSesion = "vacio";
  globalThis.fuente = "can";
  globalThis.estado.disponibles = new Set(["accel_lateral"]);
  assert.strictEqual(panelEstaPresente(pide.aceleraciones), false);
  globalThis.estadoSesion = "cargado";
});

prueba("lo que pide cada panel se resuelve en las tres fuentes", () => {
  /* Ninguna tiene que quedar como `undefined`: un panel que pide una señal
     inexistente se apaga en silencio y parece que la carga fallo. */
  const pide = loQuePidenLosPaneles();
  ["f1", "openf1", "can"].forEach(f => {
    globalThis.fuente = f;
    Object.keys(pide).forEach(panel => {
      const n = nombreDeSenal(pide[panel]);
      assert.ok(typeof n === "string" && n.length,
                "el panel " + panel + " no resuelve su señal en " + f);
    });
  });
});

prueba("una señal cruda que no es un canal atraviesa la traduccion intacta", () => {
  /* Los paneles que ya nombraban la señal de la base ---clima, motor, puesta---
     no se pueden romper por traducir los que si son canales. */
  ["f1", "openf1", "can"].forEach(f => {
    globalThis.fuente = f;
    ["air_temperature", "setup_front_wing",
     "tyre_temperature_surface_front_left", "engine_speed"].forEach(n => {
      assert.strictEqual(nombreDeSenal(n), n, n + " se tradujo en " + f);
    });
  });
});

prueba("el bus no publica puesta a punto, y eso no cambio", () => {
  /* La comprobacion complementaria: lo que si esta ausente de verdad tiene que
     seguir ausente. `setup_front_wing` no viaja en un bus de serie. */
  const pide = loQuePidenLosPaneles();
  globalThis.fuente = "can";
  assert.strictEqual(nombreDeSenal(pide.puesta), "setup_front_wing");
});

/* ==================================================================
   19. ESCONDER UN PANEL NO PUEDE BORRAR EL HECHO
   ------------------------------------------------------------------
   En el bus, «puesta a punto» y «vehiculos» no tienen nada que dar nunca: un
   bus de serie no publica configuracion del vehiculo, y una captura de un
   vehiculo no tiene con quien compararse. En OpenF1 pasa lo mismo con clima,
   neumaticos, puesta a punto, aceleraciones y avisos. Sacarlos de la vista esta
   bien; que con ellos desaparezca el dato de que esa fuente no los sostiene, no.

   El registro que se ve mientras se usa el tablero es el bloque «lo que esta
   fuente no sostiene», que se escribe desde la **misma** tabla que saca los
   paneles: no puede discrepar con lo que falta en pantalla porque es la misma
   declaracion leida dos veces. Eso se comprueba sobre el DOM, en
   `tests/test_dashboard_browser.py`, que es donde se puede.

   Lo que se comprueba aca es lo otro: la tabla del pie ---«Que sostiene cada
   fuente»--- compara las tres fuentes de un vistazo, y un panel que alguna saca
   tiene que tener ahi su fila. Es la constancia escrita, la que queda en el
   repositorio y en las capturas del informe; sin ella, sacar un panel es perder
   la comparacion que ese panel permitia hacer.

   LA DECLARACION SE LEE DEL GUION, NO DE LA HOJA DE ESTILOS. Estaba escrita como
   reglas `display: none` por fuente, y ahi no cabe el motivo. Peor: el selector
   por atributo alcanzaba **tambien a las filas de la tabla del pie**, que llevan
   el mismo `data-panel` justamente para ser el registro. La fuente que escondia
   un panel escondia con el la unica constancia de por que no estaba, que es lo
   que estas pruebas existen para impedir. La ultima de la seccion comprueba que
   esas reglas no vuelvan.
   ================================================================== */

const CSS = fs.readFileSync(
  path.join(__dirname, "..", "..", "dashboard", "styles.css"), "utf8");

/* Los paneles que cada fuente declara no sostener, con su motivo. */
const PANELES_QUE_LA_FUENTE_NO_TIENE = new Function(
  constante("PANELES_QUE_LA_FUENTE_NO_TIENE") +
  "\nreturn PANELES_QUE_LA_FUENTE_NO_TIENE;")();

function panelesEscondidosPorFuente() {
  const escondidos = {};
  Object.keys(PANELES_QUE_LA_FUENTE_NO_TIENE).forEach(f => {
    const paneles = Object.keys(PANELES_QUE_LA_FUENTE_NO_TIENE[f]);
    if (paneles.length) escondidos[f] = paneles;
  });
  return escondidos;
}

/* Los paneles que la tabla del pie declara. */
function panelesEnLaTabla() {
  const filas = [];
  const re = /<tr data-panel="([^"]+)">/g;
  let m;
  while ((m = re.exec(HTML))) filas.push(m[1]);
  return filas;
}

prueba("el bus esconde puesta a punto y la comparacion entre vehiculos", () => {
  const escondidos = panelesEscondidosPorFuente();
  assert.deepStrictEqual((escondidos.can || []).sort(), ["puesta", "vehiculos"]);
});

prueba("openf1 saca lo que no publica y se queda con lo que si", () => {
  const escondidos = panelesEscondidosPorFuente();
  /* Lo que esta fuente no entrega nunca: el estado del vehiculo ---de la
     telemetria llegan seis canales y ninguno lo es---, la puesta a punto y las
     aceleraciones. */
  assert.deepStrictEqual((escondidos.openf1 || []).sort(),
    ["aceleraciones", "puesta", "vehiculo"]);
  /* Y lo que si: el trazado sale de las coordenadas medidas, el motor del
     regimen y la marcha, el cronometraje de la parrilla y las vueltas, y la
     comparacion entre vehiculos de que hay mas de uno. Sacar alguno de esos
     seria esconder algo medido. */
  ["trazado", "motor", "cronometraje", "vehiculos"].forEach(panel => {
    assert.ok(!(escondidos.openf1 || []).includes(panel),
              "openf1 sostiene «" + panel + "» y lo esta sacando de la vista");
  });
});

prueba("comparar se habilita por lo que hay, no por de donde viene", () => {
  /* La condicion llevaba `fuente !== "f1"`, de cuando comparar era cosa del
     simulador: sobre OpenF1 el boton quedaba apagado con tres pilotos cargados
     y telemetria de los tres. Lo que hace falta son dos vehiculos. */
  const antesFuente = globalThis.fuente, antesEstado = globalThis.estadoSesion;
  const antesAutos = globalThis.AUTOS;
  try {
    globalThis.estadoSesion = "cargado";
    globalThis.AUTOS = [{ id: "a" }, { id: "b" }, { id: "c" }];
    ["openf1", "can", "f1"].forEach(f => {
      globalThis.fuente = f;
      assert.strictEqual(sePuedeComparar(), true,
        "con tres vehiculos no se puede comparar en " + f);
    });
    /* Con uno no hay con quien comparar, venga de donde venga. */
    globalThis.AUTOS = [{ id: "a" }];
    globalThis.fuente = "f1";
    assert.strictEqual(sePuedeComparar(), false);
    /* Y sin sesion abierta tampoco, aunque queden vehiculos de la anterior. */
    globalThis.AUTOS = [{ id: "a" }, { id: "b" }];
    globalThis.estadoSesion = "vacio";
    assert.strictEqual(sePuedeComparar(), false);
  } finally {
    globalThis.fuente = antesFuente;
    globalThis.estadoSesion = antesEstado;
    globalThis.AUTOS = antesAutos;
  }
});

prueba("las muestras se cuentan sobre el eje que el bloque declara", () => {
  /* La leyenda decia «sin datos» al lado de tres lineas dibujadas: contaba
     `distancia_m`, que OpenF1 no tiene. Su abscisa es el reloj del tramo, y es
     la misma regla que el armado de series ya usa. */
  globalThis.estado.series = {
    7: { vehiculos: {
      conReloj: { tiempo_s: new Array(401).fill(0), speed: [] },
      conMetro: { distancia_m: new Array(300).fill(0), speed: [] },
      sinNada: { speed: [] },
    } },
  };
  assert.strictEqual(muestrasQueAporta("conReloj", [7]), 401);
  assert.strictEqual(muestrasQueAporta("conMetro", [7]), 300);
  assert.strictEqual(muestrasQueAporta("sinNada", [7]), 0);
  assert.strictEqual(muestrasQueAporta("noEsta", [7]), 0);
  /* Y suma las vueltas que se le pidan, sin romperse con las que no estan. */
  assert.strictEqual(muestrasQueAporta("conReloj", [7, 99]), 401);
  assert.strictEqual(muestrasQueAporta("conReloj", []), 0);
  globalThis.estado.series = {};
});

prueba("la leyenda nombra a los mismos que el grafico dibuja", () => {
  /* Eran dos reglas distintas: el dibujo tomaba los primeros cuatro de la
     seleccion y la leyenda **uno solo** en la vista de detalle. La pantalla
     mostraba tres lineas y la leyenda nombraba a una, de modo que no habia
     como saber de quien era cada color. El detalle es de una señal, no de un
     piloto: que se vea una magnitud no dice cuantos vehiculos se comparan. */
  globalThis.seleccion = new Set(["a", "b", "c"]);
  globalThis.modoDetalle = true;
  assert.deepStrictEqual(idsParaComparar(), ["a", "b", "c"]);
  globalThis.modoDetalle = false;
  assert.deepStrictEqual(idsParaComparar(), ["a", "b", "c"]);
  /* El tope de cuatro sigue: mas lineas no se distinguen entre si. */
  globalThis.seleccion = new Set(["a", "b", "c", "d", "e", "f"]);
  assert.deepStrictEqual(idsParaComparar(), ["a", "b", "c", "d"]);
  globalThis.seleccion = new Set();
});

prueba("el selector de piloto no repite lo que el panel ya dice", () => {
  /* Llevaba la identidad entera y el panel de cronometraje ya escribe el
     nombre completo. En una columna de 365
     px compartida con el titulo eso se cortaba en «· McLa...»: un rotulo
     truncado justo debajo del mismo rotulo entero. */
  assert.strictEqual(
    nombreCortoDeVehiculo({ nombre: "Oscar PIASTRI", numero: 81 }), "PIASTRI · #81");
  assert.strictEqual(
    nombreCortoDeVehiculo({ nombre: "Max VERSTAPPEN", numero: 1 }), "VERSTAPPEN · #1");
});

prueba("sin dorsal declarado el selector no inventa uno", () => {
  /* Una captura que no declara la parrilla no tiene numeros de carrera: lo que
     hay es el nombre, y eso se muestra. */
  assert.strictEqual(nombreCortoDeVehiculo({ nombre: "Vehículo 19" }), "19");
  assert.strictEqual(
    nombreCortoDeVehiculo({ nombre: "Sauber", numero: null }), "Sauber");
});

prueba("el selector emite el nombre corto, y la identidad entera en el titulo", () => {
  /* Comprobar la funcion del nombre corto no alcanza: lo que se rompio fue el
     selector usando otra cosa. Aca se ejerce `poblarPropio` con un `select` de
     mentira y se mira el HTML que emite, que es lo que el navegador muestra. */
  const select = {
    dataset: {}, innerHTML: "",
    closest: () => ({ style: {} }),
  };
  const antesDoc = globalThis.document;
  const antesAutos = globalThis.AUTOS;
  globalThis.document = { getElementById: () => select };
  globalThis.AUTOS = [
    { id: "a", nombre: "Max VERSTAPPEN", numero: 1, propio: true,
      completa: "Max VERSTAPPEN · #1 · Red Bull Racing" },
    { id: "b", nombre: "Oscar PIASTRI", numero: 81, propio: false,
      completa: "Oscar PIASTRI · #81 · McLaren" },
  ];
  try {
    poblarPropio();
    assert.ok(/>VERSTAPPEN · #1</.test(select.innerHTML),
      "el selector no emite el nombre corto: " + select.innerHTML);
    assert.ok(!/>Max VERSTAPPEN · #1 · Red Bull Racing</.test(select.innerHTML),
      "el selector repite la identidad entera, que el panel ya escribe debajo");
    /* Y la identidad completa no se pierde: queda a un puntero de distancia. */
    assert.ok(/title="Max VERSTAPPEN · #1 · Red Bull Racing"/.test(select.innerHTML),
      "la identidad completa no quedo en el titulo de la opcion");
    assert.ok(/selected/.test(select.innerHTML), "no se marco el propio");
  } finally {
    globalThis.document = antesDoc;
    globalThis.AUTOS = antesAutos;
  }
});

prueba("con un solo vehiculo el selector no se ofrece", () => {
  /* Elegir entre uno no es elegir. */
  const caja = { style: {} };
  const select = { dataset: {}, innerHTML: "", closest: () => caja };
  const antesDoc = globalThis.document, antesAutos = globalThis.AUTOS;
  globalThis.document = { getElementById: () => select };
  globalThis.AUTOS = [{ id: "a", nombre: "Uno", numero: 1, propio: true, completa: "Uno" }];
  try {
    poblarPropio();
    assert.strictEqual(caja.style.display, "none");
  } finally { globalThis.document = antesDoc; globalThis.AUTOS = antesAutos; }
});

prueba("cada vehiculo se rotula por lo que tiene, no por el papel que cumple", () => {
  /* EL DEFECTO. La lista decia «propio · N señales» para uno y «cronometraje»
     para todos los demas. Es cierto en la simulacion ---la telemetria privada
     es la del coche que se conduce, y de los rivales llega posicion--- y falso
     en OpenF1, donde los tres pilotos cargados traen las mismas nueve señales:
     el rotulo decia «cronometraje» sobre dos vehiculos con 310.881 filas. */
  const conSerie = ["a", "b"];
  assert.deepStrictEqual(
    loQueSeSabeDelVehiculo({ id: "a", propio: true }, conSerie, 9),
    { clase: "propio", texto: "propio · 9 señales" });
  assert.deepStrictEqual(
    loQueSeSabeDelVehiculo({ id: "b", propio: false }, conSerie, 9),
    { clase: "senales", texto: "9 señales" });
  /* Y de quien solo aporta posicion se sigue diciendo lo que hay. */
  assert.deepStrictEqual(
    loQueSeSabeDelVehiculo({ id: "c", propio: false }, conSerie, 9),
    { clase: "senales", texto: "cronometraje" });
});

prueba("el propio se rotula por sus señales aunque la vuelta no haya llegado", () => {
  /* Es el que la sesion declara mas muestreado: tiene serie por definicion.
     Sin esto el rotulo parpadeaba a «cronometraje» mientras la vuelta viajaba. */
  assert.deepStrictEqual(
    loQueSeSabeDelVehiculo({ id: "a", propio: true }, [], 113),
    { clase: "propio", texto: "propio · 113 señales" });
});

prueba("se aprende quienes son mientras falten, y despues no", () => {
  /* El catalogo declara cuantos vehiculos con telemetria tiene la sesion. */
  globalThis.estado.abierta = { vehiculos: 3 };
  globalThis.AUTOS = [{ id: "a" }];
  assert.strictEqual(faltanVehiculosPorAprender(), true);
  globalThis.AUTOS = [{ id: "a" }, { id: "b" }, { id: "c" }];
  assert.strictEqual(faltanVehiculosPorAprender(), false);
  /* Con uno declarado ---la simulacion y el bus--- no hay nada que aprender:
     los rivales de F1 25 viajan por posiciones, no por telemetria. */
  globalThis.estado.abierta = { vehiculos: 1 };
  globalThis.AUTOS = [];
  assert.strictEqual(faltanVehiculosPorAprender(), false);
  /* Y una sesion que no declara cuantos son no dispara consultas abiertas. */
  globalThis.estado.abierta = {};
  assert.strictEqual(faltanVehiculosPorAprender(), false);
  globalThis.AUTOS = [];
});

prueba("lo que la fuente publica y el tablero todavia no trae no se declara ausente", () => {
  /* LA CORRECCION QUE ESTO FIJA. `clima` y `avisos` estaban declarados como
     ausencias de OpenF1, y el motivo de avisos lo copie de lo que contesta
     `/avisos`, que decide por fuente ---`if fuente != "f1_25_udp_simulation"`---
     y da el mismo texto para el bus y para OpenF1. Para el bus es cierto.

     Para OpenF1 es falso, y el dato esta en esta misma base: el propio backend
     cuenta 155 muestras de clima y 158 eventos de control de carrera para la
     sesion 9947, y `context-at` ya los devuelve resueltos en un instante.

     Esta tabla dice «nunca». Decir «nunca» sobre algo que esta guardado es
     esconderlo, que es justo lo que la seccion entera existe para impedir. */
  const escondidos = panelesEscondidosPorFuente();
  ["clima", "avisos"].forEach(panel => {
    assert.ok(!(escondidos.openf1 || []).includes(panel),
      "openf1 declara «" + panel + "» como ausencia de la fuente, y la fuente " +
      "lo publica: lo que falta es que el tablero lo pida");
  });
});

prueba("cada panel sacado dice por que, y no con una cadena vacia", () => {
  Object.keys(PANELES_QUE_LA_FUENTE_NO_TIENE).forEach(f => {
    const tabla = PANELES_QUE_LA_FUENTE_NO_TIENE[f];
    Object.keys(tabla).forEach(panel => {
      assert.strictEqual(typeof tabla[panel], "string");
      assert.ok(tabla[panel].trim().length > 20,
                "la fuente " + f + " saca «" + panel + "» sin decir por que");
    });
  });
});

prueba("la hoja de estilos no esconde paneles por fuente", () => {
  /* El selector por atributo no distingue la `<section>` del panel de la `<tr>`
     de la tabla del pie: las dos llevan `data-panel`. Volver a escribirlo aca
     borraria el registro junto con el panel. */
  const re = /:root\[data-fuente="([^"]+)"\]\s*\[data-panel="([^"]+)"\]\s*[,{][^{}]*display:\s*none/g;
  const halladas = [];
  let m;
  while ((m = re.exec(CSS))) halladas.push(m[1] + "/" + m[2]);
  assert.deepStrictEqual(halladas, [],
    "la hoja de estilos esconde paneles por fuente: " + halladas.join(", "));
});

prueba("todo panel escondido por fuente sigue declarado en la tabla del pie", () => {
  const escondidos = panelesEscondidosPorFuente();
  const enLaTabla = panelesEnLaTabla();
  Object.keys(escondidos).forEach(f => {
    escondidos[f].forEach(panel => {
      assert.ok(enLaTabla.indexOf(panel) !== -1,
                "la fuente " + f + " esconde «" + panel + "» y la tabla del pie no " +
                "dice que esa fuente no lo sostiene: el hecho se perdio con el panel");
    });
  });
});

prueba("la fila de un panel escondido tiene una columna por fuente", () => {
  /* Cinco celdas: el instrumento, las tres fuentes y la señal que lo habilita.
     Una fila corta diria de menos justo donde se la va a leer. */
  const re = /<tr data-panel="[^"]+">(.*?)<\/tr>/g;
  let m, filas = 0;
  while ((m = re.exec(HTML))) {
    filas++;
    const celdas = m[1].match(/<td[^>]*>/g) || [];
    assert.strictEqual(celdas.length, 5, "la fila tiene " + celdas.length + " celdas");
  }
  assert.ok(filas >= 2, "no se encontraron las filas de los paneles escondidos");
});

prueba("la tabla dice que el bus no sostiene ninguno de los dos", () => {
  const re = /<tr data-panel="(puesta|vehiculos)">(.*?)<\/tr>/g;
  let m;
  while ((m = re.exec(HTML))) {
    const celdas = m[2].match(/<td[^>]*>.*?<\/td>/g);
    /* La ultima columna es la señal; la del bus es la cuarta. */
    assert.ok(/class="no"/.test(celdas[3]),
              "la tabla declara que el bus sostiene «" + m[1] + "», y el tablero lo esconde");
  }
});

/* ==================================================================
   20. EL TERCER EJE DEL BUS ES LA GUIÑADA, Y SE LEE DE LA GUIÑADA
   ------------------------------------------------------------------
   El panel de aceleraciones tiene tres renglones. En el simulador son las tres
   aceleraciones; en el bus, que no tiene acelerometro vertical, el tercero es
   la velocidad de guiñada, y el propio renglon la nombra: `yaw_rate`.

   Leia `gVert`, que sale de `g_force_vertical` ---una señal que solo publica el
   simulador---. En el bus la casilla nunca se llenaba, asi que el renglon
   mostraba una raya sobre una sesion que trae la guiñada completa: 600 de 600
   muestras en `sample_01`. Decia el nombre correcto y traia el valor de otra
   cosa, que es la unica combinacion que no se nota mirando.
   ================================================================== */

prueba("la guiñada del bus llega al instante con su propio nombre", () => {
  globalThis.fuente = "can";
  assert.strictEqual(nombreDeSenal("yaw"), "yaw_rate");
  /* Y no es la casilla del acelerometro vertical, que el bus no tiene. */
  assert.strictEqual(nombreDeSenal("gvert"), "g_force_vertical");
  assert.notStrictEqual(nombreDeSenal("yaw"), nombreDeSenal("gvert"));
});

prueba("el bus ofrece guiñada y no ofrece acelerometro vertical", () => {
  assert.ok(CANALES_POR_FUENTE.can.indexOf("yaw") !== -1,
            "el bus dejo de ofrecer la guiñada");
  assert.strictEqual(CANALES_POR_FUENTE.can.indexOf("gvert"), -1,
                     "el bus dice tener un acelerometro vertical que no publica");
  assert.ok(CANALES_POR_FUENTE.f1.indexOf("gvert") !== -1,
            "la simulacion perdio su tercer eje");
});

prueba("en vivo la guiñada tambien llega al instante", () => {
  /* El instante se arma por dos caminos ---sesion guardada y flujo en vivo--- y
     el panel lee el mismo campo en los dos. Arreglar uno solo dejaba la raya
     puesta en el otro. */
  vivoCon({ yaw_rate: { value: -0.32, unit: "deg/s" },
            accel_lateral: { value: -0.13, unit: "g" } });
  globalThis.fuente = "can";      // `vivoCon` reinicia, y el reinicio vuelve a f1
  const i = calcularInstante();
  assert.strictEqual(i.yaw, -0.32, "en vivo la guiñada no llega al instante");
  assert.strictEqual(renglonesDelPanelG(i)[2][1], "-0,3 °/s");
  globalThis.estadoSesion = "cargado";
});

prueba("el tercer renglon del bus trae la guiñada y no una raya", () => {
  /* El defecto exacto: el renglon decia `yaw_rate` y el valor salia de la
     casilla del acelerometro vertical, que en el bus esta siempre vacia. */
  globalThis.fuente = "can";
  const r = renglonesDelPanelG({ gLong: -0.004, gLat: -0.13, gVert: null, yaw: -0.32 });
  assert.strictEqual(r[2][0], "yaw_rate");
  assert.strictEqual(r[2][1], "-0,3 °/s",
                     "el tercer eje muestra una raya sobre una sesion que trae la guiñada");
});

prueba("el bus nombra sus dos aceleraciones como las publica", () => {
  globalThis.fuente = "can";
  const r = renglonesDelPanelG({ gLong: 0.4, gLat: -0.13, gVert: null, yaw: 0 });
  assert.deepStrictEqual(r.map(x => x[0]),
                         ["accel_longitudinal", "accel_lateral", "yaw_rate"]);
  assert.strictEqual(r[0][1], "+0,40 g");
  assert.strictEqual(r[1][1], "-0,13 g");
});

prueba("la simulacion sigue mostrando sus tres aceleraciones", () => {
  globalThis.fuente = "f1";
  const r = renglonesDelPanelG({ gLong: 1.2, gLat: -2.5, gVert: 0.8, yaw: 99 });
  assert.deepStrictEqual(r.map(x => x[0]),
                         ["g_force_longitudinal", "g_force_lateral", "g_force_vertical"]);
  assert.strictEqual(r[2][1], "+0,80 g",
                     "el tercer eje de la simulacion dejo de ser el acelerometro vertical");
});

prueba("una guiñada que no llego es una raya y no un cero", () => {
  globalThis.fuente = "can";
  assert.strictEqual(renglonesDelPanelG({ gLong: 0, gLat: 0, yaw: null })[2][1], "—");
  assert.strictEqual(renglonesDelPanelG({ gLong: 0, gLat: 0 })[2][1], "—");
  /* Y una guiñada de cero es cero: el vehiculo iba derecho. */
  assert.strictEqual(renglonesDelPanelG({ gLong: 0, gLat: 0, yaw: 0 })[2][1], "0,0 °/s");
});

prueba("el instante trae la guiñada de la sesion del bus", () => {
  reiniciar();
  globalThis.fuente = "can";
  globalThis.canalesDeLaFuente = () => CANALES_POR_FUENTE.can;
  cargarVuelta(1, [0, 100, 200],
               { distancia_m: [0, 5, 10], speed: [107, 108, 109],
                 yaw_rate: [-0.8, 0.0, 0.66] }, {});
  globalThis.estado.vueltas = [{ numero: 1, duracion_s: 0.2,
                                 desde_utc: iso(T0), hasta_utc: iso(T0 + 200) }];
  armarAutos([CAR19]);
  const st = serieTemporal("yaw", 1, CAR19);
  assert.ok(st && st.t.length === 3, "la guiñada no llego como serie");
  assert.strictEqual(valorContinuoEn(st, T0 + 200), 0.66);
  /* Y la casilla del eje vertical sigue vacia: no se rellena con la guiñada. */
  assert.strictEqual(serieTemporal("gvert", 1, CAR19), null);

  /* Y llega hasta el instante, que es de donde lo lee el panel. Sin esto la
     serie existe, el panel la nombra, y el renglon muestra una raya. */
  globalThis.vueltaElegida = 1;
  globalThis.cabezal = 1;
  const i = calcularInstante();
  assert.strictEqual(i.yaw, 0.66,
                     "la guiñada no llega al instante: el panel la nombra y no la tiene");
  assert.strictEqual(i.gVert, null, "el eje vertical se lleno con algo que el bus no manda");
  globalThis.cabezal = 0;
});

/* ==================================================================
   21. EL BUS MANDA METROS POR SEGUNDO AL CUADRADO, NO g
   ------------------------------------------------------------------
   El adaptador declara `m/s^2` para `accel_x` y `accel_y`: es lo que publica el
   vehiculo. El tablero rotulaba esas cifras con la unidad de la tabla, que es
   la del simulador, y un minuto de autopista se leia con ±0,6 g de aceleracion
   lateral ---lo que hace un coche de carrera en una curva rapida---.

   COMPROBADO CONTRA LA FISICA, NO SUPUESTO. En un giro plano `a_lat = velocidad
   x velocidad de guiñada`, y la guiñada ya esta validada contra las cuatro
   ruedas. Ajustando lo medido contra lo predicho en seis segmentos con curvas
   ---ciudad, ruta y detenciones--- la pendiente da 9,1 / 10,0 / 10,0 / 10,3 /
   8,8 / 5,4 con correlaciones de 0,76 a 0,98. Esa pendiente es la gravedad.

   Y AL CONVERTIR, EL TRAMO CIERRA. En `sample_01` la variacion medida pasa de
   ser doce veces la que la guiñada explica a ser 1,18 veces, y el corrimiento
   que quedaba ---0,02 g--- es la peraltadura de 1,1 grados que tiene una
   autopista.
   ================================================================== */

prueba("las aceleraciones del bus se muestran en g", () => {
  assert.strictEqual(UNIDAD_QUE_MUESTRA_EL_TABLERO.accel_lateral, "g");
  assert.strictEqual(UNIDAD_QUE_MUESTRA_EL_TABLERO.accel_longitudinal, "g");
});

prueba("y se convierten dividiendo por la gravedad", () => {
  assert.strictEqual(divisorDeUnidad("accel_lateral", "m/s^2"), 9.80665);
  assert.strictEqual(divisorDeUnidad("accel_longitudinal", "m/s^2"), 9.80665);
  /* Una lateral de 0,611 en el bus son 0,062 g: un minuto de autopista. */
  assert.ok(Math.abs(0.611 / 9.80665 - 0.0623) < 1e-4);
});

prueba("una aceleracion que ya viene en g no se toca", () => {
  assert.strictEqual(divisorDeUnidad("accel_lateral", "g"), 1);
  /* Y la del simulador no entra en esta politica: se llama distinto. */
  assert.strictEqual(divisorDeUnidad("g_force_lateral", "g"), 1);
  assert.strictEqual(divisorDeUnidad("g_force_lateral", "m/s^2"), 1,
                     "la señal del simulador entro en la conversion del bus");
});

prueba("una unidad que no se sabe convertir no se convierte con un numero supuesto", () => {
  assert.strictEqual(divisorDeUnidad("accel_lateral", "cm/s^2"), null);
  assert.strictEqual(divisorDeUnidad("accel_lateral", ""), null);
});

/* ==================================================================
   22. EL BORDE DEL DIAGRAMA VALE ALGO, Y LO DICE
   ------------------------------------------------------------------
   El borde valia `max(1, lo mas grande de la vuelta)`. Ese piso de 1 g es del
   simulador; sobre un coche de calle deja la nube en un punto. Y una escala que
   se estira sola sin decir cuanto vale miente por omision: el mismo dibujo para
   0,06 g y para 5.
   ================================================================== */

prueba("un coche de calle no se dibuja en la escala de uno de carrera", () => {
  /* En autopista la lateral no llega a 0,07 g: con el piso de 1 g la vuelta
     entera cabia en el 6 % del radio. */
  assert.strictEqual(escalaDelDiagramaG(0.062), 0.1);
  assert.ok(escalaDelDiagramaG(0.062) < 1,
            "la escala se queda en el piso del simulador y la nube es un punto");
});

prueba("un pico aislado no se pierde al medir el borde", () => {
  /* El defecto medido cuando habia estela: tomando una muestra de cada tantas,
     los siete tramos del bus perdian entre el 9 y el 32 % del extremo, y en
     `sample_27` la escala bajaba de 0,30 a 0,20 g. Ya no hay decimacion ---se
     recorre la vuelta entera--- y por eso mismo esta prueba se queda: es la que
     dice que el borde sale de **todas** las muestras y no de algunas. */
  reiniciar();
  globalThis.fuente = "can";
  globalThis.canalesDeLaFuente = () => CANALES_POR_FUENTE.can;
  const marcas = [], lat = [], lon = [], dist = [];
  for (let i = 0; i < 3000; i++) {
    marcas.push(i * 20); dist.push(i);
    /* Un pico aislado, en un sitio que un paso fijo se saltea. */
    const pico = (i === 1501);
    lat.push((pico ? 4.45 : 0.5) * (i % 2 ? 1 : -1));
    lon.push(pico ? 1.0 : 0.3);
  }
  cargarVuelta(1, marcas,
               { distancia_m: dist, accel_lateral: lat, accel_longitudinal: lon },
               { accel_lateral: "m/s^2", accel_longitudinal: "m/s^2" });
  globalThis.estado.vueltas = [{ numero: 1, duracion_s: 60,
                                 desde_utc: iso(T0), hasta_utc: iso(T0 + 60000) }];
  armarAutos([CAR19]);

  const h = escalaDeLaVuelta(1);
  /* 4,45 m/s2 son 0,454 g: la escala tiene que ser 0,5 y no 0,1. */
  assert.strictEqual(h.maximo, 0.5,
                     "el borde se midio sobre algunas muestras y no sobre la vuelta: " + h.maximo);
});

prueba("el borde lo declara la vuelta entera, no los puntos que se dibujaron", () => {
  /* El extremo por modulo y el extremo por componente pueden ser dos puntos
     distintos: de un tramo con (2,06 · 0) y (1,57 · 1,57) sobrevive el segundo,
     que esta mas lejos del centro, y con el se pierde la lateral mas grande de
     la vuelta. Midiendo la escala sobre lo dibujado el borde sale 0,2 g cuando
     la vuelta llego a 0,21: el pico queda **fuera** del dibujo. */
  reiniciar();
  globalThis.fuente = "can";
  globalThis.canalesDeLaFuente = () => CANALES_POR_FUENTE.can;
  const marcas = [], lat = [], lon = [], dist = [];
  for (let i = 0; i < 600; i++) {
    marcas.push(i * 100); dist.push(i);
    lat.push(i === 0 ? 2.06 : i === 1 ? 1.57 : 0.1);
    lon.push(i === 1 ? 1.57 : 0.1);
  }
  cargarVuelta(1, marcas,
               { distancia_m: dist, accel_lateral: lat, accel_longitudinal: lon },
               { accel_lateral: "m/s^2", accel_longitudinal: "m/s^2" });
  globalThis.estado.vueltas = [{ numero: 1, duracion_s: 60,
                                 desde_utc: iso(T0), hasta_utc: iso(T0 + 60000) }];
  armarAutos([CAR19]);
  const h = escalaDeLaVuelta(1);
  assert.strictEqual(h.maximo, 0.3,
                     "el borde se midio sobre lo dibujado: dice " + h.maximo +
                     " g y la vuelta llego a " + (2.06 / 9.80665).toFixed(3));
});

prueba("el punto del instante no queda sujeto al borde por una escala corta", () => {
  /* Con la escala medida sobre la vuelta entera, el valor mas grande cabe
     dentro del dibujo en vez de aplastarse contra el anillo exterior. */
  reiniciar();
  globalThis.fuente = "can";
  globalThis.canalesDeLaFuente = () => CANALES_POR_FUENTE.can;
  const marcas = [], lat = [], lon = [], dist = [];
  for (let i = 0; i < 600; i++) {
    marcas.push(i * 100); dist.push(i);
    lat.push(i === 401 ? 2.05 : 0.4);
    lon.push(0.2);
  }
  cargarVuelta(1, marcas,
               { distancia_m: dist, accel_lateral: lat, accel_longitudinal: lon },
               { accel_lateral: "m/s^2", accel_longitudinal: "m/s^2" });
  globalThis.estado.vueltas = [{ numero: 1, duracion_s: 60,
                                 desde_utc: iso(T0), hasta_utc: iso(T0 + 60000) }];
  armarAutos([CAR19]);
  const h = escalaDeLaVuelta(1);
  const pico = 2.05 / 9.80665;                 // 0,209 g
  assert.ok(h.maximo >= pico,
            "el borde vale " + h.maximo + " g y la vuelta llego a " + pico.toFixed(3));
});

prueba("una vuelta quieta no divide por cero ni se dibuja en escala de carrera", () => {
  reiniciar();
  globalThis.fuente = "can";
  globalThis.canalesDeLaFuente = () => CANALES_POR_FUENTE.can;
  cargarVuelta(1, [0, 100, 200],
               { distancia_m: [0, 1, 2], accel_lateral: [0, 0, 0],
                 accel_longitudinal: [0, 0, 0] },
               { accel_lateral: "m/s^2", accel_longitudinal: "m/s^2" });
  globalThis.estado.vueltas = [{ numero: 1, duracion_s: 1,
                                 desde_utc: iso(T0), hasta_utc: iso(T0 + 200) }];
  armarAutos([CAR19]);
  const h = escalaDeLaVuelta(1);
  assert.ok(h.maximo > 0, "el borde vale cero y todo se divide por el");
});

prueba("sin aceleraciones el borde toma el paso mas chico y no rompe", () => {
  reiniciar();
  globalThis.fuente = "can";
  globalThis.canalesDeLaFuente = () => CANALES_POR_FUENTE.can;
  cargarVuelta(1, [0, 100], { distancia_m: [0, 1], speed: [10, 11] }, {});
  globalThis.estado.vueltas = [{ numero: 1, duracion_s: 1,
                                 desde_utc: iso(T0), hasta_utc: iso(T0 + 100) }];
  armarAutos([CAR19]);
  const h = escalaDeLaVuelta(1);
  assert.strictEqual(h.maximo, PASOS_DE_LA_ESCALA_G[0],
    "sin aceleraciones el borde no tomo el paso mas chico: " + h.maximo);
});

prueba("el borde del bus sale en la escala del bus", () => {
  /* De punta a punta: la vuelta entra en m/s2, se convierte a g y el diagrama
     se ajusta a lo que hubo. Con el piso de 1 g heredado del simulador, la
     estela entera cabia en el 6 % del radio: un punto en el centro. */
  reiniciar();
  globalThis.fuente = "can";
  globalThis.canalesDeLaFuente = () => CANALES_POR_FUENTE.can;
  cargarVuelta(1, [0, 100, 200, 300],
               { distancia_m: [0, 5, 10, 15],
                 accel_lateral: [0.0, 0.611, -0.215, 0.3],
                 accel_longitudinal: [0.0, 0.4, -0.18, 0.1] },
               { accel_lateral: "m/s^2", accel_longitudinal: "m/s^2" });
  globalThis.estado.vueltas = [{ numero: 1, duracion_s: 0.3,
                                 desde_utc: iso(T0), hasta_utc: iso(T0 + 300) }];
  armarAutos([CAR19]);
  const h = escalaDeLaVuelta(1);
  assert.strictEqual(h.maximo, 0.1,
                     "el diagrama se dibujo en la escala de un coche de carrera: " + h.maximo);
  /* Y el dibujo usa su radio entero: una fuerza igual al borde cae en el anillo
     de afuera. Antes esto se comprobaba sobre los puntos de la estela; sin
     estela, la afirmacion es la misma sobre la funcion que coloca. */
  const q = puntoDelDiagramaG(h.maximo, 0, h.maximo);
  const radio = Math.hypot(q.x - CENTRO_DEL_DIAGRAMA_G, q.y - CENTRO_DEL_DIAGRAMA_G);
  assert.ok(Math.abs(radio - RADIO_DEL_DIAGRAMA_G) < 0.01,
            "la vuelta del bus quedo apretada en el centro: radio " + radio.toFixed(1) +
            " de " + RADIO_DEL_DIAGRAMA_G);
});

prueba("la escala sube por pasos redondos, para poder comparar dos vueltas", () => {
  assert.strictEqual(escalaDelDiagramaG(0.04), 0.05);
  assert.strictEqual(escalaDelDiagramaG(0.35), 0.5);
  assert.strictEqual(escalaDelDiagramaG(0.5), 0.5);
  assert.strictEqual(escalaDelDiagramaG(1.2), 1.5);
  PASOS_DE_LA_ESCALA_G.forEach(p => assert.strictEqual(escalaDelDiagramaG(p), p,
    "un valor que es exactamente un paso no salta al siguiente: " + p));
});

prueba("un coche de carrera no se sale del dibujo", () => {
  /* La escala tiene que seguir creciendo mas alla del ultimo paso. */
  assert.ok(escalaDelDiagramaG(5.4) >= 5.4);
  assert.ok(escalaDelDiagramaG(9.2) >= 9.2);
});

prueba("una vuelta sin aceleracion no divide por cero", () => {
  assert.ok(escalaDelDiagramaG(0) > 0);
  assert.ok(escalaDelDiagramaG(-Infinity) > 0);
  assert.ok(escalaDelDiagramaG(NaN) > 0);
});

prueba("los pasos de la escala estan ordenados", () => {
  for (let i = 1; i < PASOS_DE_LA_ESCALA_G.length; i++) {
    assert.ok(PASOS_DE_LA_ESCALA_G[i] > PASOS_DE_LA_ESCALA_G[i - 1],
              "los pasos no suben: la escala elegiria uno mas chico que el valor");
  }
});

/* ==================================================================
   23. LA VISTA AMPLIADA SE ABRE CON EL EJE QUE LA FUENTE TIENE
   ------------------------------------------------------------------
   Se abria siempre en distancia, que es el eje del simulador, y sobre el bus
   dejaba la pantalla entera en un cartel: «esta vista espacial requiere
   distancia medida y solo esta disponible para F1 25». El boton que si
   funciona ---tiempo--- estaba al lado y nada decia que estuviera ahi.

   Y el corte era por fuente, no por eje: `fuente !== "f1"` dejaba fuera al bus
   entero. Lo que al bus le falta es **metro medido**; contra el reloj tiene sus
   trece señales y las marcas de tiempo con las que dibujarlas.
   ================================================================== */

prueba("el bus abre la vista contra el reloj, que es lo que tiene", () => {
  assert.strictEqual(ejeQueLaFuenteSostiene("can"), "tiempo");
  assert.strictEqual(ejeQueLaFuenteSostiene("openf1"), "tiempo",
                     "OpenF1 tampoco tiene metro medido");
  assert.strictEqual(ejeQueLaFuenteSostiene("f1"), "distancia");
});

prueba("el eje que se ofrece es el que la fuente sostiene, sin excepciones", () => {
  Object.keys(EJE_DE_DISTANCIA_POR_FUENTE).forEach(f => {
    const eje = ejeQueLaFuenteSostiene(f);
    assert.ok(eje === "distancia" || eje === "tiempo", f + " -> " + eje);
    assert.strictEqual(eje === "distancia", hayEjeDeDistancia(f),
                       "la fuente " + f + " abre en un eje que no tiene");
  });
});

prueba("la fuente sin metro explica por que, para poder decirlo en el boton", () => {
  const porque = porQueNoHayDistancia("can");
  assert.ok(porque.length > 20 && /odómetro|odometro|distancia/.test(porque), porque);
  assert.notStrictEqual(porQueNoHayDistancia("openf1"), porQueNoHayDistancia("can"),
                        "las dos fuentes dan el mismo motivo y no es el mismo");
});

prueba("elegir distancia y despues abrir el bus no deja la vista pidiendo metros", () => {
  /* `ejeComparacion` sobrevive al cambio de sesion: es lo que la persona
     eligio. Fijarlo al abrir habria sido acordarse en los tres sitios que abren
     la vista y olvidarse en el cuarto. */
  _fijar.eje("distancia");
  globalThis.fuente = "f1";
  assert.strictEqual(ejeVigente(), "distancia");
  globalThis.fuente = "can";
  assert.strictEqual(ejeVigente(), "tiempo",
                     "la vista quedo pidiendo un metro que el bus no mide");
  globalThis.fuente = "f1";
  assert.strictEqual(ejeVigente(), "distancia", "no se respeto lo elegido");
});

prueba("lo elegido manda cuando la fuente lo sostiene", () => {
  globalThis.fuente = "f1";
  _fijar.eje("tiempo");
  assert.strictEqual(ejeVigente(), "tiempo");
  _fijar.eje("distancia");
  assert.strictEqual(ejeVigente(), "distancia");
});

prueba("sobre el bus nada impide dibujar contra el reloj", () => {
  globalThis.fuente = "can";
  _fijar.eje("tiempo");
  assert.strictEqual(motivoDelEjeEspacial(), "",
                     "el bus se queda sin vista sobre un eje que si tiene");
  /* Y aunque quede elegida la distancia, el eje vigente es el tiempo. */
  _fijar.eje("distancia");
  assert.strictEqual(motivoDelEjeEspacial(), "");
});

prueba("el cartel del eje espacial dice el motivo y la salida", () => {
  /* Antes decia «solo esta disponible para F1 25», que es una puerta cerrada.
     El eje que si funciona estaba al lado y nada lo decia. */
  globalThis.fuente = "f1";
  _fijar.eje("distancia");
  assert.strictEqual(motivoDelEjeEspacial(), "",
                     "la simulacion perdio su vista espacial");
});

prueba("el subtitulo del bus habla de un tramo, no de una vuelta", () => {
  globalThis.fuente = "can";
  globalThis.estado.vueltas = [{ numero: 1, duracion_s: 61.6, tramo_temporal: true }];
  globalThis.vueltaElegida = 1;
  const texto = coberturaDeLaVista(globalThis.estado.vueltas[0]);
  assert.ok(/tramo/.test(texto), texto);
  assert.ok(!/vuelta/.test(texto), "se le dijo «vuelta» a un minuto de ruta: " + texto);
});

prueba("y la carrera sigue contando vueltas y metros", () => {
  globalThis.fuente = "f1";
  globalThis.estado.vueltas = [{ numero: 3, duracion_s: 105.2, largo_m: 7004.0 }];
  globalThis.vueltaElegida = 3;
  _fijar.alcance("una");
  assert.strictEqual(coberturaDeLaVista(globalThis.estado.vueltas[0]),
                     "vuelta 3 · 7.004,0 m observados");
  _fijar.alcance("carrera");
  assert.strictEqual(coberturaDeLaVista(globalThis.estado.vueltas[0]), "1 vueltas observadas");
  _fijar.alcance("una");
});

prueba("un tramo de bus no se cuenta en vueltas", () => {
  /* «Vuelta 1» sobre un minuto de ruta fuerza el vocabulario del circuito sobre
     un dato de calle, y ademas promete que hay una vuelta 2. El tramo unico se
     lo arma este tablero para compartir cabezal e interpolacion, y lo declara
     con `tramo_temporal`: eso no es una vuelta en ninguna fuente. */
  globalThis.estado.vueltas = [{ numero: 1, duracion_s: 61.6, tramo_temporal: true }];
  globalThis.fuente = "can";
  assert.strictEqual(hayVueltas(), false);
  globalThis.fuente = "f1";
  assert.strictEqual(hayVueltas(), false,
    "un tramo armado por el tablero se conto como vuelta por venir de la simulación");
});

prueba("una vuelta declarada es una vuelta aunque la fuente no mida metros", () => {
  /* EL DEFECTO QUE ESTO CIERRA. `hayVueltas` exigia ademas eje de distancia, de
     modo que OpenF1 ---que declara sus cincuenta y dos vueltas por reloj, con
     instante de inicio, fin y duracion medida--- se presentaba como «tramo» en
     el reproductor y en el cronometraje mientras el encabezado de la misma
     pantalla decia «VUELTA 1 DE 52».

     Que la fuente declare vueltas y que mida metros son dos preguntas, y la
     segunda gobierna escribir un metro, no contar vueltas. */
  globalThis.estado.vueltas = [
    { numero: 1, duracion_s: 106.1, desde_utc: "2025-07-06T14:03:49.615Z" },
    { numero: 2, duracion_s: 135.6, desde_utc: "2025-07-06T14:05:35.748Z" },
  ];
  globalThis.fuente = "openf1";
  assert.strictEqual(hayEjeDeDistancia(), false, "el supuesto de la prueba cambio");
  assert.strictEqual(hayVueltas(), true);
  globalThis.fuente = "can";
  assert.strictEqual(hayVueltas(), true,
    "una vuelta declarada deja de serlo segun quien la declare");
});

prueba("sin ninguna vuelta declarada tampoco hay vueltas", () => {
  globalThis.fuente = "f1";
  globalThis.estado.vueltas = [];
  assert.strictEqual(hayVueltas(), false);
});

/* ==================================================================
   24. LA COMPROBACION QUE VIAJABA Y NO LEIA NADIE
   ------------------------------------------------------------------
   El recorrido del bus es una integracion, y una integracion no se comprueba
   sola: acumula lo que le den. Pero hay una comprobacion, y es la mas fuerte
   que esta fuente admite.

   En una curva las ruedas de afuera recorren mas que las de adentro, y esa
   diferencia dividida por la velocidad de guiñada da el **ancho de via**. Es
   geometria pura. Y ese numero **no viaja en el bus**: que la guiñada y las
   cuatro ruedas ---decodificadas por separado--- coincidan en una dimension
   fisica del vehiculo es lo mas fuerte que se puede afirmar sobre un
   decodificado.

   Medido sobre los tramos cargados: 1,57 m con r 0,99 en `sample_16`, 1,57 con
   0,96 en `sample_20`, 1,54 con 0,98 en `sample_12`. Tres tramos
   independientes sobre la misma cifra.

   El punto de acceso ya la calculaba y la mandaba en cada respuesta. No la leia
   nadie: el resultado principal de esta fuente vivia en un campo que la
   pantalla nunca abria.
   ================================================================== */

prueba("cuando la guiñada y las ruedas coinciden, se dice y con sus cifras", () => {
  /* Los numeros son los de `sample_16`, medidos. */
  globalThis.fuente = "can";
  const texto = textoDeLaValidacion({ muestras: 822, ancho_de_via_m: 1.5719,
                                      correlacion: 0.9903 });
  assert.ok(/coinciden/.test(texto), texto);
  assert.ok(/1,57 m de vía/.test(texto), texto);
  assert.ok(/r 0,99/.test(texto), texto);
  assert.ok(/822 muestras/.test(texto), "no se dice sobre cuantas muestras: " + texto);
});

prueba("un tramo recto no deja con que contrastar, y eso no es una falla", () => {
  /* `sample_01` da cero muestras porque la comprobacion descarta lo que gira
     menos de un grado por segundo. Es ausencia de evidencia, no un fallo, y
     hay que declararla en vez de esconderla. */
  const texto = textoDeLaValidacion({ muestras: 0, ancho_de_via_m: null,
                                      correlacion: null });
  assert.ok(/sin curvas/.test(texto), texto);
  assert.ok(!/coinciden/.test(texto), "se afirmo una coincidencia sin muestras");
});

prueba("con un puñado de muestras no se presenta una correlacion perfecta", () => {
  /* `sample_28` da r = 1,00 con SIETE muestras. Un uno coma cero sobre siete
     puntos no es un acuerdo: es una recta entre dos nubes que casi no se
     mueven. Presentarlo seria prestarle a la cifra una autoridad que no tiene. */
  const texto = textoDeLaValidacion({ muestras: 7, ancho_de_via_m: 1.58,
                                      correlacion: 1.0 });
  assert.ok(/pocas curvas/.test(texto), texto);
  assert.ok(!/1,58/.test(texto), "se mostro el ancho de via de siete muestras: " + texto);
  assert.ok(!/coinciden/.test(texto));
});

prueba("si las dos señales no coinciden, tampoco se afirma que si", () => {
  /* El caso que el propio backend documenta: sin el piso de velocidad, un
     segmento con paradas daba 0,44 m con correlacion 0,25. */
  const texto = textoDeLaValidacion({ muestras: 400, ancho_de_via_m: 0.44,
                                      correlacion: 0.25 });
  assert.ok(/no coinciden/.test(texto), texto);
  assert.ok(/0,44 m de vía/.test(texto), "se escondio la cifra que no cierra: " + texto);
});

prueba("el umbral de muestras y el de correlacion son los que se aplican", () => {
  const justo = { muestras: MUESTRAS_PARA_CONTRASTAR, ancho_de_via_m: 1.57,
                  correlacion: CORRELACION_QUE_CONVENCE };
  assert.ok(/coinciden en/.test(textoDeLaValidacion(justo)),
            "en el umbral exacto se rechaza lo que se declara aceptar");
  const unaMenos = Object.assign({}, justo, { muestras: MUESTRAS_PARA_CONTRASTAR - 1 });
  assert.ok(/pocas curvas/.test(textoDeLaValidacion(unaMenos)));
});

prueba("sin comprobacion en la respuesta no se inventa una", () => {
  assert.strictEqual(textoDeLaValidacion(null), "");
  assert.strictEqual(textoDeLaValidacion(undefined), "");
  assert.strictEqual(textoDeLaValidacion({ muestras: 900, ancho_de_via_m: null,
                                           correlacion: null }), "");
});

prueba("el titulo del panel explica por que ese numero vale algo", () => {
  /* Un «1,57 m» suelto no dice nada. Lo que lo hace evidencia es que el ancho
     de via no viaja en el bus. */
  globalThis.fuente = "can";
  _fijar.pista({ derivado: true, advertencia: "Forma reconstruida por integracion.",
                 validacion: { muestras: 822, ancho_de_via_m: 1.57, correlacion: 0.99 } });
  const texto = explicacionDelTrazado();
  assert.ok(/Forma reconstruida/.test(texto), texto);
  assert.ok(/sin que el bus lo publique/.test(texto),
            "no se dice por que la coincidencia es evidencia: " + texto);
  assert.ok(/1,57 m de vía/.test(texto));
});

prueba("y sin comprobacion el titulo no promete una", () => {
  globalThis.fuente = "can";
  _fijar.pista({ derivado: true, advertencia: "Forma reconstruida por integracion.",
                 validacion: null });
  assert.strictEqual(explicacionDelTrazado(), "Forma reconstruida por integracion.");
});

/* ==================================================================
   25. LA PARRILLA DE OPENF1 EXISTIA Y NADIE LA PEDIA
   ------------------------------------------------------------------
   El tablero rotulaba «Vehículo 1, índice interno del protocolo» sobre una
   sesion donde la API contesta «Max VERSTAPPEN · VER · Red Bull Racing» con el
   color del equipo. El dato estaba entero en el contexto deportivo desde que se
   importo; lo que faltaba era la consulta.

   La identidad de una sesion guardada venia de `/adquisiciones`, que la declara
   por captura. Esa ruta es del simulador: para OpenF1 contesta la lista vacia,
   **correctamente**, porque esta fuente no se capturo, se importo. Su parrilla
   vive en otro sitio.
   ================================================================== */

/* Los tres pilotos de la sesion 9947, tal como los devuelve la API. */
const PILOTOS_9947 = [
  { driver_number: 1, full_name: "Max VERSTAPPEN", name_acronym: "VER",
    team_name: "Red Bull Racing", team_colour: "4781D7" },
  { driver_number: 4, full_name: "Lando NORRIS", name_acronym: "NOR",
    team_name: "McLaren", team_colour: "F47600" },
  { driver_number: 81, full_name: "Oscar PIASTRI", name_acronym: "PIA",
    team_name: "McLaren", team_colour: "F47600" },
];

prueba("la parrilla se pide por donde pasan todos los caminos", () => {
  /* EL DEFECTO, QUE NO SE VE MIRANDO EL CODIGO DE LA CONSULTA.
     Estaba en `abrirSesionGuardada`, que es **uno** de los caminos y no el
     unico: `elegirCorrida` vuelve a cargar la sesion por `cargarDatosDeSesion`
     sin pasar por ella, y ese es el que corre al elegir adquisicion o fase, o
     al recargar la pagina con una eleccion en la direccion. Por ese camino la
     consulta no salia nunca ---comprobado en el registro del servidor: cero
     pedidos a `/racing/sessions/.../drivers`--- y los pilotos seguian siendo
     «Vehículo 1» con la API contestando bien.

     Se comprueba sobre el archivo publicado porque es una condicion de **donde
     esta escrita** una llamada, y eso no se observa llamandola. */
  const desde = fuenteApp.indexOf("function cargarDatosDeSesion");
  assert.ok(desde !== -1, "no esta `cargarDatosDeSesion`");
  const cuerpo = fuenteApp.slice(desde, fuenteApp.indexOf("\nfunction ", desde + 10));
  assert.ok(cuerpo.indexOf("pedirParrillaDeOpenF1(") !== -1,
            "la parrilla no se pide desde `cargarDatosDeSesion`, que es por " +
            "donde pasan todos los caminos que abren una sesion");
});

prueba("la parrilla usa la apertura que le dan, no la que encuentre", () => {
  /* Tomar `aperturaVigente()` adentro ataba la consulta al orden en que se la
     invoque: llamada antes de `nuevaSesionEnCurso()`, su respuesta llegaba con
     la apertura anterior y `sigueVigente` la descartaba por vieja. */
  const desde = fuenteApp.indexOf("function pedirParrillaDeOpenF1");
  const cuerpo = fuenteApp.slice(desde, fuenteApp.indexOf("\nfunction ", desde + 10));
  assert.ok(/function pedirParrillaDeOpenF1\(sessionId, apertura\)/.test(cuerpo),
            "la apertura no es un argumento: la consulta queda atada al orden");
});

prueba("la clave de sesion sale del identificador y no se pide aparte", () => {
  assert.strictEqual(claveDeSesionOpenF1("openf1:session:9947"), "9947");
  /* Y no se inventa una para lo que no la tiene. */
  assert.strictEqual(claveDeSesionOpenF1("can:segmento:sample_28"), null);
  assert.strictEqual(claveDeSesionOpenF1("f1_25:session:3731090176871608020"), "3731090176871608020");
  assert.strictEqual(claveDeSesionOpenF1(""), null);
  assert.strictEqual(claveDeSesionOpenF1(null), null);
});

prueba("cada piloto queda atado al vehiculo que la telemetria nombra", () => {
  /* Si la clave no coincide con `vehicle_id`, la parrilla nombra a gente que
     no esta y nadie queda identificado. */
  const p = parrillaDesdePilotos("openf1:session:9947", PILOTOS_9947);
  assert.strictEqual(p.disponible, true);
  assert.deepStrictEqual(p.vehiculos.map(v => v.vehicle_id), [
    "openf1:session:9947:driver:1",
    "openf1:session:9947:driver:4",
    "openf1:session:9947:driver:81",
  ]);
});

prueba("el nombre, el numero y el equipo llegan tal como la fuente los da", () => {
  const v = parrillaDesdePilotos("openf1:session:9947", PILOTOS_9947).vehiculos[0];
  assert.strictEqual(v.nombre, "Max VERSTAPPEN");
  assert.strictEqual(v.numero, 1);
  assert.strictEqual(v.equipo, "Red Bull Racing");
});

prueba("son personas, y eso es un no y no una casilla vacia", () => {
  /* `esIA` tiene tres estados: si, no, y no se sabe. Un piloto de OpenF1 es un
     no declarado, no un desconocido. */
  const v = parrillaDesdePilotos("openf1:session:9947", PILOTOS_9947).vehiculos[0];
  assert.strictEqual(v.es_ia, false);
  assert.notStrictEqual(v.es_ia, null);
});

prueba("la sigla es la que publica la fuente, no tres letras del nombre", () => {
  /* De «Max VERSTAPPEN» recortando salen «MAX», que no es como se lo rotula en
     ningun cronometraje. OpenF1 publica `name_acronym`. */
  reiniciar();
  globalThis.fuente = "openf1";
  globalThis.estado.abierta = { session_id: "openf1:session:9947" };
  /* Una sesion importada no declara adquisiciones ---`/adquisiciones` contesta
     la lista vacia--- y entonces `corrida.adquisicion` queda en `null` y manda
     la parrilla unica. Es la situacion real de esta fuente. */
  globalThis.corrida.adquisicion = null;
  /* La parrilla se ata a **esta** sesion: `parrillaVigente` descarta la que
     quedo de otra, y ese cuidado no se puede saltear en la prueba. */
  anotarParrillas("openf1:session:9947",
                  [{ clave: "contexto",
                     parrilla: parrillaDesdePilotos("openf1:session:9947", PILOTOS_9947) }]);
  const i = identidadDeVehiculo("openf1:session:9947:driver:1");
  assert.strictEqual(i.etiqueta, "VER",
                     "la marca del trazado dice «" + i.etiqueta + "» en vez de VER");
  assert.strictEqual(i.nombre, "Max VERSTAPPEN");
  assert.strictEqual(i.declarada, true);
  assert.ok(/Red Bull/.test(i.completa), i.completa);
});

prueba("con una sola parrilla y sin adquisicion elegida, manda esa", () => {
  /* Es lo que permite que la parrilla del contexto sirva sin inventar una
     adquisicion: una sesion importada no tiene dos capturas que puedan nombrar
     gente distinta en el mismo indice, que es la ambiguedad que este cuidado
     existe para atajar. */
  reiniciar();
  globalThis.fuente = "openf1";
  globalThis.estado.abierta = { session_id: "openf1:session:9947" };
  globalThis.corrida.adquisicion = null;
  anotarParrillas("openf1:session:9947",
                  [{ clave: "contexto",
                     parrilla: parrillaDesdePilotos("openf1:session:9947", PILOTOS_9947) }]);
  assert.ok(parrillaVigente(), "la parrilla del contexto no llego a aplicarse");
  /* Y con una adquisicion elegida que no es la suya, no se la fuerza. */
  globalThis.corrida.adquisicion = "otra";
  assert.strictEqual(parrillaVigente(), null);
  globalThis.corrida.adquisicion = null;
});

prueba("sin sigla declarada se sigue recortando el nombre", () => {
  /* El simulador no publica siglas: ese camino no se puede romper. */
  reiniciar();
  globalThis.fuente = "f1";
  ponerParrilla({ disponible: true, vehiculos: [
    { vehicle_id: CAR19, nombre: "NORRIS", numero: 4, equipo: "McLaren" }] });
  assert.strictEqual(identidadDeVehiculo(CAR19).etiqueta, "NOR");
});

prueba("un piloto sin nombre no entra a la parrilla", () => {
  /* Nombrar a medias es peor que no nombrar: `identidadDeVehiculo` ya tiene su
     respaldo explicito para el que no se conoce. */
  const p = parrillaDesdePilotos("openf1:session:9947", [
    { driver_number: 7, full_name: null, name_acronym: "XXX" },
    { driver_number: 1, full_name: "Max VERSTAPPEN", name_acronym: "VER" },
  ]);
  assert.strictEqual(p.vehiculos.length, 1);
  assert.strictEqual(p.vehiculos[0].numero, 1);
});

prueba("una parrilla vacia se declara no disponible", () => {
  assert.strictEqual(parrillaDesdePilotos("openf1:session:9947", []).disponible, false);
  assert.strictEqual(parrillaDesdePilotos("openf1:session:9947", null).disponible, false);
});

/* ==================================================================
   26. PEDIR UNA VUELTA, NO LA CARRERA ENTERA
   ------------------------------------------------------------------
   `/series-tiempo` reparte los puntos que se le piden sobre lo que abarca la
   consulta. Sin acotar, en una carrera de OpenF1 eso son dos horas y media: mil
   doscientos puntos dan **una muestra cada 7,8 segundos**, de modo que una
   ventana de veinte segundos se dibuja con dos o tres puntos y el grafico sale
   como una recta quebrada. La fuente publica a 3,7 Hz ---unas treinta y cuatro
   mil muestras por piloto--- asi que se tiraba el 96 % de lo medido.

   Acotando a la vuelta, los mismos puntos caen sobre noventa segundos.
   ================================================================== */

prueba("la consulta se acota al tramo de la vuelta que se mira", () => {
  reiniciar();
  globalThis.fuente = "openf1";
  globalThis.estado.vueltas = [
    { numero: 1, duracion_s: 106.134, desde_utc: "2025-07-06T14:03:49.615000+00:00",
      hasta_utc: "2025-07-06T14:05:35.749000+00:00" },
    { numero: 2, duracion_s: 91.2, desde_utc: "2025-07-06T14:05:35.749000+00:00",
      hasta_utc: "2025-07-06T14:07:06.949000+00:00" },
  ];
  const tramo = tramoDeLaVuelta(2);
  assert.ok(/desde=/.test(tramo) && /hasta=/.test(tramo), tramo);
  assert.ok(tramo.indexOf(encodeURIComponent("2025-07-06T14:05:35.749000+00:00")) !== -1,
            "no se pide desde donde empieza esa vuelta: " + tramo);
  assert.ok(tramo.indexOf(encodeURIComponent("2025-07-06T14:07:06.949000+00:00")) !== -1,
            "no se pide hasta donde termina: " + tramo);
});

prueba("los dos instantes van escapados, que es una direccion", () => {
  /* Un `+` sin escapar en una consulta se lee como un espacio, y el instante
     llega una hora corrido. */
  reiniciar();
  globalThis.estado.vueltas = [
    { numero: 1, desde_utc: "2025-07-06T14:03:49+00:00", hasta_utc: "2025-07-06T14:05:35+00:00" }];
  const tramo = tramoDeLaVuelta(1);
  assert.ok(tramo.indexOf("+00:00") === -1,
            "el desplazamiento horario viaja sin escapar: " + tramo);
  assert.ok(tramo.indexOf("%2B00%3A00") !== -1, tramo);
});

prueba("una vuelta sin sus dos instantes se pide como antes", () => {
  /* Pedir un tramo inventado seria peor que pedir la sesion entera. */
  reiniciar();
  globalThis.estado.vueltas = [
    { numero: 1, duracion_s: 60, desde_utc: null, hasta_utc: null },
    { numero: 2, duracion_s: 60, desde_utc: "2025-07-06T14:00:00+00:00", hasta_utc: null }];
  assert.strictEqual(tramoDeLaVuelta(1), "");
  assert.strictEqual(tramoDeLaVuelta(2), "");
  assert.strictEqual(tramoDeLaVuelta(9), "", "una vuelta que no existe no da tramo");
});

prueba("una fuente sin metro medido ya puede tener mas de una vuelta", () => {
  /* `asegurarVuelta` rechazaba cualquier vuelta que no fuera la 1 cuando la
     fuente no tiene distancia. OpenF1 declara cincuenta y dos por reloj, y esa
     restriccion dejaba cincuenta y una sin poder pedirse. Lo que decide es si
     la vuelta existe, no de que fuente viene. */
  const desde = fuenteApp.indexOf("function asegurarVuelta");
  const cuerpo = fuenteApp.slice(desde, fuenteApp.indexOf("\nfunction ", desde + 10));
  assert.ok(cuerpo.indexOf("temporal && numero !== 1") === -1,
            "sigue rechazando toda vuelta que no sea la 1 en las fuentes " +
            "sin metro medido");
  assert.ok(/estado\.vueltas\.some\(v => v\.numero === numero\)/.test(cuerpo),
            "no comprueba que la vuelta exista: " +
            "pedir una que no esta no devuelve nada y se reintenta sin fin");
});

console.log("identidad_y_cronometraje: " + hechas + " comprobaciones");

/* ============================================================
   SEIS VEHICULOS, Y QUE EL COLOR NO SE MUEVA
   ============================================================ */

prueba("el color es del vehiculo y no de su lugar en la lista", () => {
  reiniciar();
  globalThis._tintaPorVehiculo = new Map();
  const A = "f1_25:session:1:car:3";
  const B = "f1_25:session:1:car:7";

  armarAutos([A, B]);
  const colorA = globalThis.AUTOS.find(v => v.id === A).tinta;
  const colorB = globalThis.AUTOS.find(v => v.id === B).tinta;
  assert.notStrictEqual(colorA, colorB, "dos vehiculos, dos colores");

  /* Aparece uno nuevo **adelante**: con la asignacion por posicion, A y B se
     corrian un lugar y cambiaban de color. */
  armarAutos(["f1_25:session:1:car:0", A, B]);
  assert.strictEqual(globalThis.AUTOS.find(v => v.id === A).tinta, colorA);
  assert.strictEqual(globalThis.AUTOS.find(v => v.id === B).tinta, colorB);

  // Y desaparecer y volver tampoco lo cambia.
  armarAutos([B]);
  armarAutos([A, B]);
  assert.strictEqual(globalThis.AUTOS.find(v => v.id === A).tinta, colorA);
});

prueba("seis vehiculos tienen seis colores distintos", () => {
  reiniciar();
  globalThis._tintaPorVehiculo = new Map();
  const claves = [0, 3, 7, 11, 15, 19].map(i => "f1_25:session:1:car:" + i);
  armarAutos(claves);
  const colores = new Set(globalThis.AUTOS.map(a => a.tinta));
  assert.strictEqual(globalThis.AUTOS.length, 6);
  assert.strictEqual(colores.size, 6, "dos pilotos compartirian trazo");
});

/* ============================================================
   LA VENTANA MOVIL DEJA DE CRECER Y EL CONTENIDO SIGUE CAMBIANDO
   ============================================================ */

prueba("la vista convertida avanza aunque el largo se clave en el tope", () => {
  /* El largo era la identidad de la vista memorizada, con el argumento de que
     «el arreglo solo crece». Deja de crecer al llenarse la ventana: desde ahi
     cada muestra nueva saca la mas vieja y el contenido cambia sin que el largo
     se mueva. */
  const serie = [];
  for (let i = 0; i < 600; i++) serie.push([i, 1000, i]);
  serie.rev = 600;

  const primera = _enUnidad(serie, 10, "vivo|c|presion|" + serie.rev);
  assert.strictEqual(primera[599][1], 100);

  // Entra una muestra nueva: el largo sigue en 600 y el contenido no.
  serie.shift();
  serie.push([600, 2000, 600]);
  serie.rev = 601;

  const segunda = _enUnidad(serie, 10, "vivo|c|presion|" + serie.rev);
  assert.strictEqual(segunda.length, 600, "la ventana movil se conserva");
  assert.strictEqual(segunda[599][1], 200,
                     "la vista convertida se quedo con el contenido viejo");
});
