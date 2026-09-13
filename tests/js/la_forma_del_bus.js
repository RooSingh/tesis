/* La forma del recorrido del bus, que se reconstruye y se dibuja.
 *
 * CRITERIO. Como los demas arneses, la funcion se **extrae del `app.js` que se
 * publica** y se ejecuta; no se copia.
 *
 * QUE PASABA, MEDIDO EL 2026-09-13 SOBRE LA SESION `can:segmento:sample_01`.
 * El panel de trazado mostraba su rotulo ---«recorrido reconstruido»--- y
 * debajo, nada. El `path` del dibujo era la cadena vacia. Y sin embargo el
 * testigo del propio tablero decia `trazadosAplicados: 1`: contaba un exito que
 * no habia ocurrido.
 *
 * LA CAUSA. El commit 32e387d ---el que puso los sectores sobre el circuito---
 * borro las veintidos lineas que armaban esta pista y las reemplazo por las dos
 * que arman la **otra**: `estado.trazado = t; PISTA = armarPista(t, CURVAS)`.
 * En esa continuacion no existe ninguna `t`: el parametro se llama `r`. Cada
 * respuesta del bus lanzaba un `ReferenceError`.
 *
 * POR QUE NADIE LO VIO EN DOS DIAS. El `.catch` de esa cadena dice
 * `if (e instanceof TypeError) console.error(e)`. Fue escrito para avisar de un
 * fallo de red, y de paso **se come todos los defectos propios**: un
 * `ReferenceError` no es un `TypeError`, asi que la consola quedaba limpia.
 * Un `catch` que solo reconoce una clase de error silencia todas las demas.
 *
 * Y POR QUE `armarPista` NO SIRVE ACA, que es lo que hay que dejar escrito para
 * que no vuelva a pasar. `armarPista` arma una pista desde una respuesta de
 * `/trazado`: circuito cerrado, con sectores, con largo declarado y con eje de
 * distancia. Esto es una respuesta de `/can/recorrido`: un tramo de ruta que no
 * vuelve a su principio ---cerrarlo dibuja una recta que nadie recorrio---, sin
 * sectores, y parametrizado por **tiempo** y no por metro. Unificar los dos
 * constructores no era simplificar: era afirmar que son la misma cosa.
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

/* La respuesta real de `/can/recorrido/can:segmento:sample_01`, recortada a
   cinco puntos. Las claves son las que contesta la API, no las de `/trazado`:
   `recorrido_m` y no `largo_m`, `t_ms` por punto y no eje de distancia. */
const RESPUESTA = {
  session_id: "can:segmento:sample_01",
  puntos: [
    { x: 0.0, y: 0.0, t_ms: 21 },
    { x: 0.56, y: 0.01, t_ms: 40 },
    { x: 1.16, y: 0.04, t_ms: 60 },
    { x: 1.75, y: 0.09, t_ms: 80 },
    { x: 2.37, y: 0.16, t_ms: 101 },
  ],
  recorrido_m: 1795.6,
  eje_temporal: { origen_utc: "2026-08-31T12:00:00+00:00" },
  naturaleza: "derivado",
  advertencia: "Forma reconstruida por integracion, sin coordenadas.",
  validacion_guinada: { cierre_deg: 1.2 },
};

/* El banco: la continuacion publicada, con todo lo que no se prueba mudo y
   `pedir` bajo control. `PISTA` se declara adentro porque la funcion la
   escribe, y se lee al terminar. */
function banco(responder) {
  const visto = { render: 0, consola: [] };
  const cuerpo = `
    let PISTA = {};
    const CURVAS = [];
    const estado = { abierta: { session_id: "can:segmento:sample_01" }, trazado: null };
    const TESTIGO = { trazadosPedidos: 0, trazadosAplicados: 0, trazadosDescartados: 0 };
    const aperturaVigente = () => 1;
    const sigueVigente = () => true;
    const senalDeSesion = () => null;
    const render = () => { visto.render++; };
    const console = { error: e => visto.consola.push(String(e && e.name || e)) };
    const document = { getElementById: () => null };
    let ultima = null;
    const conCarga = (_, f) => { ultima = f(); return ultima; };
    ${extraer("fueAnulada")}
    ${extraer("convieneAvisar")}
    ${extraer("trazadoAPath")}
    ${extraer("pedirRecorridoDelBus")}
    pedirRecorridoDelBus();
    return { espera: ultima, pista: () => PISTA, estado, TESTIGO };
  `;
  return [new Function("pedir", "visto", cuerpo)(responder, visto), visto];
}

let hechas = 0;
const pendientes = [];
function prueba(nombre, fn) {
  pendientes.push(Promise.resolve().then(fn).then(() => { hechas++; }, e => {
    process.exitCode = 1;
    console.error("FALLA  " + nombre + "\n       " + (e && e.message));
  }));
}

prueba("EL DEFECTO: con una respuesta del bus, el panel queda con un dibujo", async () => {
  const [b] = banco(() => Promise.resolve(RESPUESTA));
  await b.espera;
  const p = b.pista();
  assert.ok(p.path && p.path.length > 0,
    "el recorrido del bus no dejo ningun camino que dibujar");
  assert.ok(/^M/.test(p.path), "el camino no empieza con un desplazamiento");
});

prueba("y el tramo NO se cierra: una ruta no vuelve a su principio", async () => {
  /* `trazadoAPath` cierra con `Z` porque un circuito vuelve a la largada. Un
     tramo de ruta no: la recta del final al principio no la recorrio nadie, y
     en un tramo casi recto esa recta es todo el dibujo otra vez. */
  const [b] = banco(() => Promise.resolve(RESPUESTA));
  await b.espera;
  assert.ok(!/Z\s*$/.test(b.pista().path),
    "el recorrido del bus se cerro como si fuera un circuito");
});

/* Un tramo que dobla de verdad, para poder preguntarle hacia donde dobla. La
   recta casi perfecta de `RESPUESTA` no sirve: espejada se ve igual. */
const CURVA = {
  ...RESPUESTA,
  puntos: [
    { x: 0, y: 0, t_ms: 0 }, { x: 10, y: 0, t_ms: 100 },
    { x: 20, y: 3, t_ms: 200 }, { x: 28, y: 10, t_ms: 300 },
    { x: 33, y: 20, t_ms: 400 }, { x: 34, y: 32, t_ms: 500 },
  ],
};

//: Hacia que lado gira el camino en tres puntos seguidos. El signo es lo unico
//: que interesa: espejar el dibujo lo da vuelta.
function giro(a, b, c) {
  return Math.sign((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]));
}

prueba("EL DIBUJO NO SE ESPEJA: una curva a la derecha no sale a la izquierda", async () => {
  /* `trazadoAPath` sabe invertir el eje vertical porque la simulacion publica
     su mundo al reves. La reconstruccion del bus ya entrega el plano en el
     sentido en que se recorrio: invertirlo espejaria cada curva del tramo, y
     el dibujo seguiria pareciendo razonable. */
  const [b] = banco(() => Promise.resolve(CURVA));
  await b.espera;
  const p = b.pista();
  const w = CURVA.puntos.map(q => [q.x, q.y]);
  for (let i = 2; i < w.length; i++) {
    const enElMundo = giro(w[i - 2], w[i - 1], w[i]);
    const enElDibujo = giro(p.proyectarMundo(w[i - 2][0], w[i - 2][1]),
                            p.proyectarMundo(w[i - 1][0], w[i - 1][1]),
                            p.proyectarMundo(w[i][0], w[i][1]));
    assert.strictEqual(enElDibujo, enElMundo,
      "la curva " + i + " salio hacia el otro lado");
  }
});

prueba("LO QUE UBICA AL COCHE EN EL TIEMPO VIAJA CON LA FORMA", async () => {
  /* Aca no hay metro recorrido: el coche se coloca por el instante de cada
     punto. Sin `marcas_ms`, sin `mundo` y sin origen declarado, `puntoDelBusEn`
     devuelve nulo y el coche no se dibuja nunca. */
  const [b] = banco(() => Promise.resolve(RESPUESTA));
  await b.espera;
  const p = b.pista();
  assert.deepStrictEqual(p.marcas_ms, [21, 40, 60, 80, 101]);
  assert.strictEqual(p.mundo.length, RESPUESTA.puntos.length);
  assert.deepStrictEqual(p.mundo[0], [0.0, 0.0]);
  assert.strictEqual(p.origen_utc, "2026-08-31T12:00:00+00:00");
  assert.strictEqual(typeof p.proyectarMundo, "function");
});

prueba("SE DECLARA DERIVADO, que es lo que separa esta forma de una medida", async () => {
  const [b] = banco(() => Promise.resolve(RESPUESTA));
  await b.espera;
  const p = b.pista();
  assert.strictEqual(p.derivado, true);
  assert.ok(/no son recuperables|sin coordenadas/.test(p.advertencia || ""),
    "la forma derivada se muestra sin decir que lo es");
  assert.deepStrictEqual(p.validacion, RESPUESTA.validacion_guinada,
    "la comprobacion de guinada viajaba sin que nadie la leyera");
});

prueba("el largo sale de `recorrido_m`, que es como lo llama esta API", async () => {
  const [b] = banco(() => Promise.resolve(RESPUESTA));
  await b.espera;
  assert.strictEqual(b.pista().largo_m, 1795.6);
  assert.strictEqual(b.pista().muestras, RESPUESTA.puntos.length);
});

prueba("EL TESTIGO NO CUENTA UN EXITO ANTES DE TENERLO", async () => {
  /* Contarlo antes del armado fue lo que hizo invisible el defecto: el tablero
     informaba `trazadosAplicados: 1` con el panel vacio. */
  const [b] = banco(() => Promise.resolve(RESPUESTA));
  await b.espera;
  assert.strictEqual(b.TESTIGO.trazadosAplicados, 1);
  assert.ok(b.pista().path, "conto un trazado aplicado sin camino");
});

prueba("una respuesta sin puntos suficientes se descarta y no se cuenta", async () => {
  const [b] = banco(() => Promise.resolve({ ...RESPUESTA, puntos: RESPUESTA.puntos.slice(0, 2) }));
  await b.espera;
  assert.strictEqual(b.TESTIGO.trazadosDescartados, 1);
  assert.strictEqual(b.TESTIGO.trazadosAplicados, 0);
});

prueba("UN DEFECTO PROPIO SE AVISA, no se come el `catch`", async () => {
  /* Es la mitad que dejo el fallo invisible dos dias. Un fallo de red o una
     consulta cortada no se avisan ---no son defectos---; cualquier otra cosa,
     si. */
  const [b, visto] = banco(() => Promise.reject(
    Object.assign(new ReferenceError("t is not defined"), {})));
  await b.espera;
  assert.deepStrictEqual(visto.consola, ["ReferenceError"],
    "un defecto del tablero se perdio en silencio");
});

prueba("una consulta anulada o un corte por tiempo no se avisan como fallo", async () => {
  const anulada = Object.assign(new Error("cortada"), { name: "AbortError" });
  const [b1, v1] = banco(() => Promise.reject(anulada));
  await b1.espera;
  assert.deepStrictEqual(v1.consola, [], "una consulta anulada se anuncio como defecto");
  const tarde = Object.assign(new Error("no contesto"), { name: "TiempoAgotado", porTiempo: true });
  const [b2, v2] = banco(() => Promise.reject(tarde));
  await b2.espera;
  assert.deepStrictEqual(v2.consola, [], "un corte por tiempo se anuncio como defecto");
});

prueba("un fallo de la API tampoco es un defecto del tablero", async () => {
  const http = Object.assign(new Error("500 Internal Server Error"), { estado: 500 });
  const [b, visto] = banco(() => Promise.reject(http));
  await b.espera;
  assert.deepStrictEqual(visto.consola, [],
    "un fallo del servidor se anuncio como defecto del navegador");
});

Promise.all(pendientes).then(() => {
  console.log("ok " + hechas + " pruebas de la forma del bus");
});
