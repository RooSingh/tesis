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
  let _mandoSesion = null;
  let _aperturaActual = 0;
  let _selloSeries = 0;
  let _selloDeLoArmado = -1;
  const _seriesArmadas = new Map();
  let _ultimaTraza = 0;
  const estado = { abierta: null, series: {}, pidiendo: {}, posiciones: {},
                   pidiendoPos: {}, disponibles: new Set(), vehiculoClave: "car:1",
                   vueltas: [] };
  function senalesCandidatas() { return ["speed", "throttle_position"]; }
  // El alcance de adquisicion/fase viaja en cada consulta; aca no se elige
  // ninguno, que es el comportamiento por omision.
  const corrida = { adquisicion: null, fase: null, disponibles: null, mezclada: false };
  function sufijoDeCorrida() { return ""; }
  function armarAutos(ids) { AUTOS = ids.map(id => ({ id, propio: false, nombre: id })); }
  function avisar(texto, esError) { AVISOS.push({ texto, esError }); }
  function render() {}
  function pedirPintado() {}
  function dibujarTraza() {}
  function moverCabezalesGraficos() {}
  function instante() { return { vuelta: vueltaElegida }; }
  function compAbierta() { return false; }
  function vueltasParaComparar() { return [vueltaElegida]; }
  const document = { getElementById: () => null };
  function requestAnimationFrame() { return 0; }
  function setInterval() { return 0; }
  function clearInterval() {}
  function pintarCargas() { CAPAS.push("cargas"); }
  const PANELES_DE = {};
  // \`pedir\` de mentira: registra la consulta y devuelve una promesa que las
  // pruebas resuelven cuando quieren, en el orden que quieren.
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
  fn("conCarga"),
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
];

const pedidos = [];
const avisos = [];
const capas = [];

function nuevoBanco() {
  globalThis.PEDIDOS = pedidos;
  globalThis.AVISOS = avisos;
  globalThis.CAPAS = capas;
  const devolver = `return { estado, asegurarVuelta, nuevaSesionEnCurso,
                             aperturaVigente, sigueVigente, puntosParaVueltas,
                             enTandas, podarVueltas,
                             fijarVuelta: (v) => { vueltaElegida = v; },
                             leerVales: () => _vales.size };`;
  return new Function(preludio + "\n" + PIEZAS.join("\n\n") + "\n" + devolver)();
}

let hechas = 0;
const pendientes = [];
function prueba(titulo, fn) {
  pendientes.push(async () => {
    pedidos.length = 0; avisos.length = 0; capas.length = 0;
    try {
      await fn(nuevoBanco());
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

/* ------------------------------------------------------------------ */
(async () => {
  for (const t of pendientes) await t();
  if (process.exitCode) {
    console.error("\n" + hechas + " pruebas pasaron; hubo fallos.");
  } else {
    console.log(hechas + " pruebas de continuaciones asincronas: OK");
  }
})();
