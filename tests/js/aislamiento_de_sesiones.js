/* Pruebas de comportamiento del camino vivo del tablero.
 *
 * CRITERIO. Igual que `ayudantes_de_serie.js`: el codigo se **extrae del
 * `app.js` que se publica** y se ejecuta con muestras armadas a mano. Lo que
 * se ejercita aca es lo que no se puede ver mirando el archivo: que pasa
 * cuando dos sesiones publican a la vez, cuando un snapshot llega tarde, y
 * cuando alguien esta mirando una carrera guardada mientras entra telemetria
 * de otra cosa.
 *
 * Lo que rodea a `incorporarTelemetriaViva` ---dibujar, avisar, tocar el
 * documento--- se sustituye por piezas mudas: no es lo que se prueba, y no
 * existe fuera de un navegador.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");

const APP = path.join(__dirname, "..", "..", "dashboard", "app.js");
const fuenteJs = fs.readFileSync(APP, "utf8");

/* Saca un bloque por su encabezado, contando llaves. Sirve igual para una
   funcion (`function x(`) que para un objeto (`const x = {`). */
function extraerDesde(marca, cierre) {
  const desde = fuenteJs.indexOf(marca);
  if (desde === -1) throw new Error("no esta en app.js: " + marca);
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

function extraerFuncion(nombre) {
  return extraerDesde("function " + nombre + "(");
}

function extraerConstanteNumerica(nombre) {
  const re = new RegExp("const\\s+" + nombre + "\\s*=\\s*(\\d+)\\s*;");
  const m = fuenteJs.match(re);
  if (!m) throw new Error("no esta la constante " + nombre);
  return "const " + nombre + " = " + m[1] + ";";
}

/* ------------------------------------------------------------------
   El entorno: lo minimo para que el camino vivo corra
   ------------------------------------------------------------------ */
const avisos = [];
const capasPedidas = [];
const preludio = `
  const FUENTE_CORTA = { f1_25_udp_simulation: "f1", openf1_historical_replay: "openf1",
                         can_real_replay: "can", can_simulated: "can" };
  let fuente = "f1";
  let sesionAbierta = null;
  let estadoSesion = "cargado";
  let AUTOS = [];
  let seleccion = new Set();
  let SESIONES = [];
  const estado = { abierta: null, series: {}, pidiendo: {}, posiciones: {},
                   pidiendoPos: {}, disponibles: new Set(), vehiculoClave: null };
  function avisar(texto, esError) { AVISOS.push({ texto, esError }); }
  function pintarTransporte() {}
  function render() {}
  /* La adopcion de una sesion viva le pide su procedencia al backend. Aca no
     hay backend: se devuelve una promesa que nunca resuelve, de modo que el
     camino se ejerce entero y no se inventa una procedencia que el banco no
     tiene con que dar. */
  function pedir() { return new Promise(function () {}); }
  function marcar() {}
  function armarAutos(ids) { AUTOS = ids.map(id => ({ id, propio: false, nombre: id })); }
  const document = { getElementById: () => null };
  function requestAnimationFrame(fn) { return 0; }
  let PISTA = { path: "", curvas: [], largo_m: null, desnivel_m: null, muestras: null };
  let CURVAS = [];
  let _selloSeries = 0;
  function cambiaronLasSeries() { _selloSeries++; }
  // Se anota que capa se pidio, para poder comprobar que una muestra en vivo
  // no rehace la estructura.
  function pedirPintado(capas) {
    (Array.isArray(capas) ? capas : [capas]).forEach(c => CAPAS.push(c));
  }
  function setTimeout() { return 0; }
  function clearTimeout() {}
`;

const PIEZAS = [
  extraerConstanteNumerica("MAX_MUESTRAS_VIVO"),
  extraerConstanteNumerica("MUESTRAS_RECORDADAS"),
  extraerConstanteNumerica("LATENCIAS_RECORDADAS"),
  extraerDesde("const TESTIGO = {", ";"),
  extraerFuncion("anotarLatencia"),
  extraerDesde("const vivo = {", ";"),
  extraerFuncion("vaciarVivo"),
  extraerFuncion("identidadDeMuestra"),
  extraerFuncion("recordarVista"),
  extraerFuncion("puedeAdoptarVivo"),
  extraerFuncion("relojDeMuestra"),
  extraerFuncion("mapaVivo"),
  extraerFuncion("numeroMedido"),
  extraerConstanteNumerica("MAX_PUNTOS_DE_RECORRIDO"),
  extraerConstanteNumerica("PUNTOS_ENTRE_REDIBUJOS"),
  extraerFuncion("trazadoAPath"),
  extraerFuncion("anotarPosicionViva"),
  extraerFuncion("armarTrazadoVivo"),
  extraerFuncion("congelarTrazadoVivo"),
  extraerFuncion("claveVehiculoPropio"),
  extraerFuncion("incorporarTelemetriaViva"),
  // Adoptar una sesion viva le pide su procedencia al backend. Se trae la pieza
  // igual y el preludio da un `pedir` que nunca resuelve, de modo que la
  // adopcion se ejerce entera sin salir a la red.
  extraerFuncion("pedirProcedenciaViva"),
  extraerFuncion("nuevaSesionEnCurso"),
  extraerFuncion("aperturaVigente"),
  extraerFuncion("sigueVigente"),
  "let _mandoSesion = null; let _aperturaActual = 0;",
];

function nuevoBanco() {
  globalThis.AVISOS = avisos;
  globalThis.CAPAS = capasPedidas;
  const devolver = `return { vivo, estado, TESTIGO, anotarLatencia,
                             armarTrazadoVivo, congelarTrazadoVivo,
                             leerPista: () => PISTA, fijarPista: (p) => { PISTA = p; },
                             incorporarTelemetriaViva, puedeAdoptarVivo,
                             identidadDeMuestra, vaciarVivo, nuevaSesionEnCurso,
                             aperturaVigente, sigueVigente,
                             leerEstadoSesion: () => estadoSesion,
                             leerAutos: () => AUTOS };`;
  return new Function(preludio + "\n" + PIEZAS.join("\n\n") + "\n" + devolver)();
}

let hechas = 0;
function prueba(titulo, fn) {
  try {
    avisos.length = 0;
    capasPedidas.length = 0;
    fn(nuevoBanco());
    hechas++;
  } catch (error) {
    console.error("FALLO: " + titulo);
    console.error("  " + (error && error.stack ? error.stack : error));
    process.exitCode = 1;
  }
}

/* Una muestra con la forma que publica el capturador. */
function muestra(sesion, vehiculo, senal, valor, t) {
  return {
    source_type: "f1_25_udp_simulation", session_id: sesion, vehicle_id: vehiculo,
    signal_name: senal, value: valor, unit: "x", timestamp: t,
  };
}

const T = (s) => "2026-09-07T12:00:" + String(s).padStart(2, "0") + ".000+00:00";

/* ==================================================================
   Adopcion: una sesion viva no se apropia de la pantalla
   ================================================================== */
prueba("sin nada abierto se adopta la primera, y queda fijada", (b) => {
  b.incorporarTelemetriaViva(muestra("S1", "car:1", "lap_distance", 10, T(1)));
  assert.strictEqual(b.vivo.sesion, "S1");
  assert.strictEqual(b.vivo.objetivo, "S1", "la eleccion tiene que quedar fija");
  assert.strictEqual(b.vivo.aceptaNueva, false,
    "despues de elegir no se puede seguir adoptando cualquiera");
});

prueba("mirando una sesion guardada, otra sesion viva NO se apropia", (b) => {
  b.estado.abierta = { session_id: "GUARDADA" };
  b.vivo.aceptaNueva = false;
  b.incorporarTelemetriaViva(muestra("OTRA", "car:1", "speed", 200, T(1)));
  assert.strictEqual(b.vivo.sesion, null, "adopto una sesion que nadie pidio");
  assert.strictEqual(b.estado.abierta.session_id, "GUARDADA");
  // Y ni siquiera aprende sus señales: no es la sesion que se esta mirando.
  assert.strictEqual(b.estado.disponibles.has("speed"), false);
});

prueba("la sesion viva que si se esta mirando se adopta sola", (b) => {
  b.estado.abierta = { session_id: "S9" };
  b.vivo.aceptaNueva = false;
  b.incorporarTelemetriaViva(muestra("S9", "car:1", "speed", 200, T(1)));
  assert.strictEqual(b.vivo.sesion, "S9");
});

prueba("se declara una sola vez que hay otra sesion emitiendo", (b) => {
  b.estado.abierta = { session_id: "GUARDADA" };
  b.vivo.aceptaNueva = false;
  for (let i = 0; i < 20; i++) {
    b.incorporarTelemetriaViva(muestra("OTRA", "car:1", "speed", 200, T(i)));
  }
  assert.strictEqual(avisos.length, 1, "un aviso por muestra seria un diluvio");
  assert.ok(avisos[0].texto.indexOf("OTRA") !== -1);
});

prueba("dos productores a la vez no hacen oscilar la sesion elegida", (b) => {
  b.estado.abierta = { session_id: "A" };
  b.vivo.aceptaNueva = false;
  for (let i = 0; i < 10; i++) {
    b.incorporarTelemetriaViva(muestra("A", "car:1", "speed", 100 + i, T(i)));
    b.incorporarTelemetriaViva(muestra("B", "car:2", "speed", 200 + i, T(i)));
  }
  // Adoptar por mensaje haria que la sesion cambiara veinte veces y vaciara
  // la serie en cada cambio.
  assert.strictEqual(b.vivo.sesion, "A");
  assert.strictEqual(b.vivo.series.has("car:2"), false, "entro un vehiculo de otra sesion");
});

prueba("dos productores no oscilan tampoco cuando SI se sigue el vivo", (b) => {
  /* Este era el agujero: con un booleano, «seguir el vivo» significaba seguir
     a cualquiera, y el tablero cambiaba de sesion en cada mensaje. */
  b.incorporarTelemetriaViva(muestra("A", "car:1", "lap_distance", 10, T(0)));
  assert.strictEqual(b.vivo.objetivo, "A");
  for (let i = 1; i < 10; i++) {
    b.incorporarTelemetriaViva(muestra("A", "car:1", "speed", 100 + i, T(i)));
    b.incorporarTelemetriaViva(muestra("B", "car:2", "speed", 200 + i, T(i)));
  }
  assert.strictEqual(b.vivo.sesion, "A", "la sesion elegida cambio sola");
  assert.strictEqual(b.vivo.series.has("car:2"), false);
});

prueba("un snapshot de recuperacion nunca elige sesion", (b) => {
  /* `/live/recent` describe lo que el difusor tenia guardado, que puede ser de
     otra sesion y de hace rato. */
  b.incorporarTelemetriaViva(muestra("VIEJA", "car:9", "speed", 10, T(1)), true);
  assert.strictEqual(b.vivo.sesion, null, "un snapshot cambio la sesion del tablero");
  assert.strictEqual(b.vivo.objetivo, null);
});

prueba("adoptar una sesion viva invalida el trabajo historico en vuelo", (b) => {
  const antes = b.aperturaVigente();
  b.incorporarTelemetriaViva(muestra("S1", "car:1", "lap_distance", 10, T(1)));
  assert.notStrictEqual(b.aperturaVigente(), antes,
    "una consulta historica en vuelo volveria y escribiria sobre la sesion nueva");
  assert.strictEqual(b.sigueVigente(antes), false);
});

/* ==================================================================
   Duplicados e identidad
   ================================================================== */
prueba("la identidad no es la marca temporal sola", (b) => {
  const a = muestra("S", "car:1", "speed", 1, T(1));
  const c = muestra("S", "car:2", "speed", 1, T(1));
  const d = muestra("S", "car:1", "engine_speed", 1, T(1));
  assert.notStrictEqual(b.identidadDeMuestra(a), b.identidadDeMuestra(c));
  assert.notStrictEqual(b.identidadDeMuestra(a), b.identidadDeMuestra(d));
});

prueba("la misma muestra dos veces aporta un punto, no dos", (b) => {
  b.incorporarTelemetriaViva(muestra("S", "car:1", "lap_distance", 100, T(1)));
  const m = muestra("S", "car:1", "speed", 200, T(2));
  b.incorporarTelemetriaViva(m);
  b.incorporarTelemetriaViva(m);
  b.incorporarTelemetriaViva(Object.assign({}, m));
  assert.strictEqual(b.vivo.series.get("car:1").get("speed").length, 1);
});

/* ==================================================================
   Snapshot retrasado
   ================================================================== */
prueba("un snapshot atrasado no hace retroceder el ultimo valor", (b) => {
  b.incorporarTelemetriaViva(muestra("S", "car:1", "lap_distance", 500, T(9)));
  b.incorporarTelemetriaViva(muestra("S", "car:1", "speed", 300, T(9)));
  // Llega tarde la recuperacion, con una muestra de hace ocho segundos.
  b.incorporarTelemetriaViva(muestra("S", "car:1", "speed", 50, T(1)), true);
  const ultimo = b.vivo.ultimos.get("car:1").get("speed");
  assert.strictEqual(ultimo.value, 300, "un valor viejo piso al nuevo");
});

prueba("un snapshot atrasado no borra las muestras recientes", (b) => {
  b.incorporarTelemetriaViva(muestra("S", "car:1", "lap_distance", 900, T(9)));
  b.incorporarTelemetriaViva(muestra("S", "car:1", "speed", 300, T(9)));
  assert.strictEqual(b.vivo.series.get("car:1").get("speed").length, 1);
  // Una distancia vieja y mucho menor: sin proteccion dispara el corte por
  // vuelta nueva y borra la serie viva entera.
  b.incorporarTelemetriaViva(muestra("S", "car:1", "lap_distance", 20, T(1)), true);
  assert.ok(b.vivo.series.has("car:1"), "la recuperacion borro la serie viva");
  assert.strictEqual(b.vivo.series.get("car:1").get("speed").length, 1);
  assert.strictEqual(b.vivo.distancia.get("car:1"), 900, "la distancia retrocedio");
});

prueba("un snapshot atrasado no abre una vuelta nueva", (b) => {
  b.incorporarTelemetriaViva(muestra("S", "car:1", "lap_number", 5, T(9)));
  b.incorporarTelemetriaViva(muestra("S", "car:1", "lap_distance", 100, T(9)));
  b.incorporarTelemetriaViva(muestra("S", "car:1", "speed", 300, T(9)));
  b.incorporarTelemetriaViva(muestra("S", "car:1", "lap_number", 4, T(1)), true);
  assert.strictEqual(b.vivo.series.get("car:1").get("speed").length, 1);
});

prueba("una vuelta nueva de verdad si corta la serie", (b) => {
  b.incorporarTelemetriaViva(muestra("S", "car:1", "lap_number", 5, T(1)));
  b.incorporarTelemetriaViva(muestra("S", "car:1", "lap_distance", 100, T(1)));
  b.incorporarTelemetriaViva(muestra("S", "car:1", "speed", 300, T(2)));
  assert.strictEqual(b.vivo.series.get("car:1").get("speed").length, 1);
  b.incorporarTelemetriaViva(muestra("S", "car:1", "lap_number", 6, T(3)));
  // `lap_number` es una señal mas y se guarda como tal, asi que la clave del
  // vehiculo vuelve a existir enseguida. Lo que tiene que haber desaparecido
  // es la traza de la vuelta anterior.
  const tras = b.vivo.series.get("car:1");
  assert.ok(!tras || !tras.has("speed"), "quedo la traza de la vuelta anterior");
});

/* ==================================================================
   Ceros inventados en el camino vivo
   ================================================================== */
prueba("una distancia nula no se toma como el metro cero", (b) => {
  b.incorporarTelemetriaViva(muestra("S", "car:1", "lap_distance", null, T(1)));
  assert.strictEqual(b.vivo.distancia.has("car:1"), false);
  // Y sin distancia conocida, ninguna señal entra a la serie: no se sabe donde.
  b.incorporarTelemetriaViva(muestra("S", "car:1", "speed", 200, T(2)));
  assert.strictEqual(b.vivo.series.has("car:1"), false);
});

prueba("una vuelta nula no se toma como la vuelta cero", (b) => {
  b.incorporarTelemetriaViva(muestra("S", "car:1", "lap_number", "", T(1)));
  assert.strictEqual(b.vivo.vuelta.has("car:1"), false);
});

prueba("un valor nulo no entra a la serie como cero", (b) => {
  b.incorporarTelemetriaViva(muestra("S", "car:1", "lap_distance", 100, T(1)));
  b.incorporarTelemetriaViva(muestra("S", "car:1", "brake_position", null, T(2)));
  const s = b.vivo.series.get("car:1");
  assert.ok(!s || !s.has("brake_position"), "un freno nulo se dibujo como freno suelto");
});

prueba("un cero medido si entra", (b) => {
  b.incorporarTelemetriaViva(muestra("S", "car:1", "lap_distance", 100, T(1)));
  b.incorporarTelemetriaViva(muestra("S", "car:1", "brake_position", 0, T(2)));
  assert.deepStrictEqual(
    b.vivo.series.get("car:1").get("brake_position").map(p => [p[0], p[1]]),
    [[100, 0]]);
});

/* ==================================================================
   Aislamiento entre vehiculos y reloj conservado
   ================================================================== */
prueba("cada vehiculo tiene su serie y no se mezclan", (b) => {
  b.incorporarTelemetriaViva(muestra("S", "car:1", "lap_distance", 100, T(1)));
  b.incorporarTelemetriaViva(muestra("S", "car:2", "lap_distance", 700, T(1)));
  b.incorporarTelemetriaViva(muestra("S", "car:1", "speed", 100, T(2)));
  b.incorporarTelemetriaViva(muestra("S", "car:2", "speed", 200, T(2)));
  assert.deepStrictEqual(
    b.vivo.series.get("car:1").get("speed").map(p => [p[0], p[1]]), [[100, 100]]);
  assert.deepStrictEqual(
    b.vivo.series.get("car:2").get("speed").map(p => [p[0], p[1]]), [[700, 200]]);
});

prueba("la muestra guarda el reloj de la fuente, no el de llegada", (b) => {
  b.incorporarTelemetriaViva(muestra("S", "car:1", "lap_distance", 100, T(1)));
  b.incorporarTelemetriaViva(muestra("S", "car:1", "speed", 200, T(2)));
  const punto = b.vivo.series.get("car:1").get("speed")[0];
  assert.strictEqual(punto[2], Date.parse(T(2)));
  assert.notStrictEqual(punto[2], null);
});

prueba("una marca ilegible no inventa un reloj", (b) => {
  b.incorporarTelemetriaViva(muestra("S", "car:1", "lap_distance", 100, T(1)));
  const m = muestra("S", "car:1", "speed", 200, "no es una fecha");
  b.incorporarTelemetriaViva(m);
  assert.strictEqual(b.vivo.series.get("car:1").get("speed")[0][2], null);
});

prueba("la ventana viva no crece sin limite", (b) => {
  b.incorporarTelemetriaViva(muestra("S", "car:1", "lap_distance", 1, T(1)));
  for (let i = 0; i < 2000; i++) {
    b.incorporarTelemetriaViva({
      source_type: "f1_25_udp_simulation", session_id: "S", vehicle_id: "car:1",
      signal_name: "speed", value: i, unit: "x",
      timestamp: "2026-09-07T12:00:00." + String(i).padStart(6, "0") + "+00:00",
    });
  }
  const serie = b.vivo.series.get("car:1").get("speed");
  assert.ok(serie.length <= 600, "la serie viva llego a " + serie.length);
  assert.ok(b.vivo.vistos.size <= 600, "el conjunto de vistos llego a " + b.vivo.vistos.size);
});

/* ==================================================================
   El trazado en vivo: se mide, no se supone
   ================================================================== */

/* Un par de posiciones del mundo con la misma marca, como llega del flujo. */
function posicion(sesion, vehiculo, x, z, t) {
  return [
    muestra(sesion, vehiculo, "world_position_x", x, t),
    muestra(sesion, vehiculo, "world_position_z", z, t),
  ];
}

/* Un tramo con forma de arco, para que la nube tenga dos ejes distintos. */
function alimentarRecorrido(b, sesion, vehiculo, cuantos, desde) {
  for (let i = 0; i < cuantos; i++) {
    const a = ((desde || 0) + i) * 0.05;
    const t = "2026-09-07T12:00:00." + String(i).padStart(6, "0") + "+00:00";
    posicion(sesion, vehiculo, Math.cos(a) * 100, Math.sin(a) * 60, t)
      .forEach(m => b.incorporarTelemetriaViva(m));
  }
}

prueba("sin ninguna posicion no hay trazado: no se inventa uno", (b) => {
  b.incorporarTelemetriaViva(muestra("S", "car:1", "speed", 200, T(1)));
  assert.strictEqual(b.armarTrazadoVivo(), false);
  assert.strictEqual(b.leerPista().path, "", "se dibujo un circuito sin haberlo medido");
});

prueba("con dos posiciones tampoco: un camino necesita al menos tres puntos", (b) => {
  alimentarRecorrido(b, "S", "car:1", 2);
  assert.strictEqual(b.armarTrazadoVivo(), false);
  assert.strictEqual(b.leerPista().path, "");
});

prueba("desde cero, las posiciones que llegan arman el recorrido", (b) => {
  /* No hace falta llamar a `armarTrazadoVivo`: lo llama el propio camino de
     incorporacion. Comprobar su valor de retorno mediria si quedaba algo nuevo
     por dibujar, que es otra cosa. */
  alimentarRecorrido(b, "S", "car:1", 40);
  const p = b.leerPista();
  assert.ok(p.path.length > 10, "no se armo ningun camino");
  assert.strictEqual(p.enConstruccion, true, "no se declaro que esta a medio medir");
  /* Se redibuja cada veinticinco puntos, no en cada uno: rehacer el dibujo
     recalcula la orientacion de la nube entera y con cada punto el trazado
     salta de sitio. Asi que lo dibujado va por detras de lo medido, y por
     menos de un intervalo. */
  assert.ok(p.muestras >= 25 && p.muestras <= 40,
    'dibujados ' + p.muestras + ' de 40 medidos');
  assert.strictEqual(b.vivo.recorrido.get('car:1').length, 40,
    'se midieron menos puntos de los que llegaron');
});

prueba("el recorrido a medio medir NO se cierra", (b) => {
  alimentarRecorrido(b, "S", "car:1", 40);
  b.armarTrazadoVivo();
  assert.ok(b.leerPista().path.indexOf("Z") === -1,
    "se cerro un tramo que no se recorrio: seria una cuerda inventada");
});

prueba("al cerrar la vuelta el recorrido pasa a ser el circuito", (b) => {
  alimentarRecorrido(b, "S", "car:1", 60);
  b.armarTrazadoVivo();
  assert.strictEqual(b.leerPista().enConstruccion, true);
  b.congelarTrazadoVivo(5891);
  const p = b.leerPista();
  assert.strictEqual(p.enConstruccion, false);
  assert.strictEqual(p.medidoEnVivo, true, "no se declaro de donde salio la geometria");
  assert.strictEqual(p.largo_m, 5891);
  assert.ok(p.path.trim().endsWith("Z"), "un circuito cerrado tiene que cerrar");
});

prueba("congelado, el recorrido deja de crecer", (b) => {
  alimentarRecorrido(b, "S", "car:1", 60);
  b.armarTrazadoVivo();
  b.congelarTrazadoVivo(5891);
  const antes = b.leerPista().path;
  alimentarRecorrido(b, "S", "car:1", 60, 60);
  assert.strictEqual(b.armarTrazadoVivo(), false, "siguio reescribiendo el circuito");
  assert.strictEqual(b.leerPista().path, antes);
});

prueba("una posicion a medias no entra al recorrido", (b) => {
  // Solo la x, sin su z: no hay punto que dibujar.
  b.incorporarTelemetriaViva(muestra("S", "car:1", "world_position_x", 10, T(1)));
  const r = b.vivo.recorrido.get("car:1");
  assert.ok(!r || r.length === 0, "se anoto un punto con una sola coordenada");
});

prueba("no se aparea la x de una muestra con la z de la siguiente", (b) => {
  b.incorporarTelemetriaViva(muestra("S", "car:1", "world_position_x", 10, T(1)));
  b.incorporarTelemetriaViva(muestra("S", "car:1", "world_position_z", 20, T(2)));
  const r = b.vivo.recorrido.get("car:1");
  assert.ok(!r || r.length === 0,
    "se armo un punto mezclando dos instantes distintos");
});

prueba("un vehiculo detenido no engorda el recorrido", (b) => {
  for (let i = 0; i < 50; i++) {
    const t = "2026-09-07T12:00:00." + String(i).padStart(6, "0") + "+00:00";
    posicion("S", "car:1", 100, 60, t).forEach(m => b.incorporarTelemetriaViva(m));
  }
  assert.strictEqual(b.vivo.recorrido.get("car:1").length, 1,
    "cincuenta muestras de la misma posicion son un punto, no cincuenta");
});

prueba("el recorrido no crece sin limite", (b) => {
  alimentarRecorrido(b, "S", "car:1", 4500);
  assert.ok(b.vivo.recorrido.get("car:1").length <= 4000,
    "quedaron " + b.vivo.recorrido.get("car:1").length + " puntos");
});

prueba("cambiar de sesion no reutiliza el recorrido de la anterior", (b) => {
  alimentarRecorrido(b, "S1", "car:1", 40);
  const deLaPrimera = b.leerPista().path;
  assert.ok(deLaPrimera.length > 10);

  // Se habilita adoptar otra: es lo que pasa al encender una captura nueva.
  b.vivo.objetivo = null;
  b.vivo.aceptaNueva = true;
  b.estado.abierta = null;
  alimentarRecorrido(b, "S2", "car:9", 5);

  assert.strictEqual(b.vivo.sesion, "S2");
  assert.strictEqual(b.vivo.recorrido.has("car:1"), false,
    "quedo el recorrido del vehiculo de la sesion anterior");
  assert.notStrictEqual(b.leerPista().path, deLaPrimera,
    "quedo el circuito de la sesion anterior debajo del coche de la nueva");
});

prueba("una posicion no finita no entra", (b) => {
  posicion("S", "car:1", NaN, 60, T(1)).forEach(m => b.incorporarTelemetriaViva(m));
  posicion("S", "car:1", 10, null, T(2)).forEach(m => b.incorporarTelemetriaViva(m));
  const r = b.vivo.recorrido.get("car:1");
  assert.ok(!r || r.length === 0);
});

/* ==================================================================
   El testigo cuenta lo que dice contar
   ================================================================== */
prueba("cada muestra incorporada abre la cuenta de latencia una sola vez", (b) => {
  b.incorporarTelemetriaViva(muestra("S", "car:1", "lap_distance", 10, T(1)));
  const t0 = b.TESTIGO.pendienteDesde;
  assert.ok(typeof t0 === "number", "no se abrio la cuenta al llegar la primera");
  for (let i = 2; i < 8; i++) {
    b.incorporarTelemetriaViva(muestra("S", "car:1", "speed", 100 + i, T(i)));
  }
  // Se conserva el instante de la PRIMERA no reflejada: lo que interesa es
  // cuanto espera el dato mas viejo, no el mas nuevo.
  assert.strictEqual(b.TESTIGO.pendienteDesde, t0,
    "se reinicio con cada muestra: mediria siempre casi cero");
  assert.strictEqual(b.TESTIGO.pendientes, 7);
  assert.strictEqual(b.TESTIGO.muestrasIncorporadas, 7);
});

prueba("una muestra descartada por duplicado no cuenta como incorporada", (b) => {
  const m = muestra("S", "car:1", "lap_distance", 10, T(1));
  b.incorporarTelemetriaViva(m);
  b.incorporarTelemetriaViva(m);
  b.incorporarTelemetriaViva(m);
  assert.strictEqual(b.TESTIGO.muestrasIncorporadas, 1,
    "contar duplicados inflaria el caudal que se informa");
});

prueba("el anillo de latencias no crece sin limite", (b) => {
  /* Una instrumentacion que crece con lo que mide termina midiendose a si
     misma. Se comprueba con la funcion que usa el tablero, no escribiendo
     directamente en el arreglo. */
  for (let i = 0; i < 3000; i++) b.anotarLatencia(i);
  assert.strictEqual(b.TESTIGO.latencias.length, 1000);
  // Y conserva las ultimas, que son las que describen el estado actual.
  assert.strictEqual(b.TESTIGO.latencias[999], 2999);
});

prueba("una muestra de una sesion no adoptada no abre latencia", (b) => {
  b.estado.abierta = { session_id: "GUARDADA" };
  b.vivo.aceptaNueva = false;
  b.incorporarTelemetriaViva(muestra("OTRA", "car:1", "speed", 200, T(1)));
  assert.strictEqual(b.TESTIGO.muestrasIncorporadas, 0);
  assert.strictEqual(b.TESTIGO.pendienteDesde, null);
});

/* ==================================================================
   Trabajo de dibujo por muestra
   ================================================================== */
prueba("una muestra no rehace la estructura del tablero", (b) => {
  b.incorporarTelemetriaViva(muestra("S", "car:1", "lap_distance", 100, T(1)));
  capasPedidas.length = 0;                    // el primer vehiculo si es estructura
  for (let i = 0; i < 50; i++) {
    b.incorporarTelemetriaViva(muestra("S", "car:1", "speed", 100 + i, T(i)));
  }
  assert.strictEqual(capasPedidas.indexOf("estructura"), -1,
    "cincuenta muestras rehicieron las listas desplegables");
  assert.ok(capasPedidas.indexOf("valores") !== -1);
  assert.ok(capasPedidas.indexOf("trazas") !== -1);
});

prueba("un vehiculo nuevo si es un cambio de estructura", (b) => {
  b.incorporarTelemetriaViva(muestra("S", "car:1", "speed", 100, T(1)));
  assert.ok(capasPedidas.indexOf("estructura") !== -1,
    "hay una lista mas: eso si es estructura");
});

/* ==================================================================
   Vigencia por apertura: A -> B -> A
   ================================================================== */
prueba("dos aperturas de la misma sesion son distintas", (b) => {
  const a1 = b.nuevaSesionEnCurso();          // abre A
  const b1 = b.nuevaSesionEnCurso();          // pasa a B
  const a2 = b.nuevaSesionEnCurso();          // vuelve a A
  assert.notStrictEqual(a1, a2, "A -> B -> A dio la misma apertura");
  assert.strictEqual(b.sigueVigente(a2), true);
  assert.strictEqual(b.sigueVigente(a1), false,
    "una respuesta de la primera A se aplicaria sobre la segunda A");
  assert.strictEqual(b.sigueVigente(b1), false);
});

prueba("la apertura vigente es la ultima que se abrio", (b) => {
  b.nuevaSesionEnCurso();
  const ultima = b.nuevaSesionEnCurso();
  assert.strictEqual(b.aperturaVigente(), ultima);
  assert.strictEqual(b.sigueVigente(ultima), true);
});

if (process.exitCode) {
  console.error("\n" + hechas + " pruebas pasaron; hubo fallos.");
} else {
  console.log(hechas + " pruebas de aislamiento de sesiones: OK");
}
