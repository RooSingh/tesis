/* Una consulta que no contesto no es una sesion sin incidentes.
 *
 * CRITERIO. Como los demas arneses, las funciones se **extraen del `app.js`
 * que se publica** y se ejecutan; no se copian.
 *
 * EL DEFECTO QUE ESTO CUIDA. Medido el 2026-09-11 sobre
 * `f1_25:session:3527452921763583202` (4.140.744 filas), `/avisos` en frio
 * tardo 76,0 / 73,4 / 72,6 s en tres sondas. El cliente aborta a los 30 s
 * (`LIMITE_ESPERA_MS`), y el corte por tiempo llega como `TiempoAgotado`: no es
 * `AbortError` ni `TypeError`. El `catch` de `cargarDatosDeSesion` solo
 * anotaba los `TypeError`, de modo que el fallo desaparecia sin dejar rastro:
 * ni consola, ni motivo, ni marca. `estado.avisos` quedaba en `[]`.
 *
 * Y entonces el panel escribia «Todavia no ocurrio nada en esta sesion hasta el
 * punto que estas mirando» sobre una sesion cuya API devolvia **veinticuatro
 * avisos**, cuatro de ellos alertas. Un panel vacio se lee como un panel vacio;
 * un panel que afirma que no hubo incidentes tranquiliza. El fallo se
 * disfrazaba de hallazgo, que es la unica forma de error que no se puede ver.
 *
 * Es el mismo caso que `estado.fallo` ya resuelve para las vueltas: «llego
 * vacia» y «no llego» no son el mismo estado y no pueden decir lo mismo.
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

/* Un documento de mentira que recuerda lo que cada renderizador escribio. */
function documentoDePrueba() {
  const nodos = {};
  const nuevo = () => ({ innerHTML: "", textContent: "", dataset: {} });
  globalThis.document = {
    getElementById: id => (nodos[id] = nodos[id] || nuevo()),
    querySelector: () => null,
    querySelectorAll: () => [],
  };
  return nodos;
}

globalThis.estado = { avisos: [], avisosMotivo: "", avisosFallo: "" };
globalThis.estadoSesion = "cargado";
globalThis.fuente = "f1_25_udp_simulation";
globalThis.cabezal = 1;
globalThis.tinta = () => "#fff";
globalThis.cifra = (v) => String(v);
globalThis.hayVueltas = () => true;
globalThis._firmaAvisos = "";
globalThis._cuantosAvisos = 0;

/* `pintarAvisos` lee dos contadores de modulo. Se los da el ambito global y se
   los reinicia entre casos: sin eso, la firma del caso anterior hace que el
   segundo dibujo se saltee y la prueba mida el HTML de otro caso. */
const cuerpo = [
  extraer("textoSeguro"),
  extraer("fueAnulada"),
  extraer("avisosDeLaFuente"),
  /* Cada entrada declara de donde sale: una medicion con umbral o un hecho
     que la fuente declaro. Va en el titulo y lo arma esta funcion. */
  extraer("procedenciaDelAviso"),
  /* Lo que `pintarAvisos` consulta para ordenar y rotular. Se agregaron el
     2026-09-12 y este arnes quedo sin ellas: cinco de sus diez casos morian con
     «masNuevoPrimero is not defined», **y eran los que cuidan que el panel no
     afirme que no ocurrio nada cuando la consulta no volvio**. Los descubrio
     otra sesion corriendo los arneses a mano, porque no hay quien los corra. */
  extraer("cuandoOcurrio"),
  extraer("masNuevoPrimero"),
  extraer("rotuloDeCuando"),
  extraer("conMayusculaInicial"),
  extraer("pintarAvisos"),
  extraer("anotarFalloDeAvisos"),
  "return { pintarAvisos, anotarFalloDeAvisos };",
].join("\n");
const modulo = new Function(cuerpo)();

function reiniciar() {
  globalThis.estado.avisos = [];
  globalThis.estado.avisosMotivo = "";
  globalThis.estado.avisosFallo = "";
  globalThis._firmaAvisos = "";
  globalThis._cuantosAvisos = 0;
  _consola = [];
}

/* El anotador escribe en consola a proposito: es la mitad del arreglo. Se lo
   recoge en vez de dejarlo ensuciar la salida del arnes, y de paso se puede
   afirmar que efectivamente escribio. */
let _consola = [];
const _errorReal = console.error;
console.error = (...a) => { _consola.push(a.map(String).join(" ")); };
process.on("exit", () => { console.error = _errorReal; });

let hechas = 0, fallidas = 0;
function prueba(nombre, fn) {
  hechas++;
  try { fn(); console.log("  ok  " + nombre); }
  catch (e) { fallidas++; console.log("  NO  " + nombre + "\n      " + e.message); }
}

console.log("avisos que no llegaron");

/* ---- lo que se anota cuando la consulta no vuelve ---- */

prueba("un corte por tiempo queda anotado y no se pierde", () => {
  reiniciar();
  const t = new Error("la consulta no contestó en 30 s");
  t.name = "TiempoAgotado";
  t.porTiempo = true;
  modulo.anotarFalloDeAvisos(t);
  assert.ok(globalThis.estado.avisosFallo,
            "el corte por tiempo no dejo rastro: " +
            JSON.stringify(globalThis.estado.avisosFallo));
  assert.strictEqual(_consola.length, 1,
                     "el fallo no se anoto en consola: " + JSON.stringify(_consola));
});

prueba("una cancelacion a proposito no es un fallo", () => {
  reiniciar();
  const a = new Error("cancelada");
  a.name = "AbortError";
  modulo.anotarFalloDeAvisos(a);
  assert.strictEqual(globalThis.estado.avisosFallo, "",
                     "cerrar una sesion se anoto como fallo de los avisos");
  assert.strictEqual(_consola.length, 0,
                     "una cancelacion ensucio la consola: " + JSON.stringify(_consola));
});

prueba("un 500 de la API tambien queda anotado", () => {
  reiniciar();
  const e = new Error("500 Internal Server Error");
  e.estado = 500;
  modulo.anotarFalloDeAvisos(e);
  assert.ok(globalThis.estado.avisosFallo, "un fallo de la API se perdio");
});

/* ---- lo que el panel puede afirmar ---- */

prueba("el pie dice de quien son los avisos, que no es lo mismo para los dos", () => {
  /* Los derivados de la telemetria son del piloto que se mira y cambian al
     cambiar de piloto; los declarados en el control de carrera son de la
     sesion y no cambian, lo cual se ve como que el panel no reacciona. Medido
     sobre la carrera cargada: de 158 eventos, 157 no nombran piloto. */
  reiniciar();
  const nodos = documentoDePrueba();
  try {
    globalThis.estado.controlDeCarrera = [
      { que: "YELLOW", nivel: "alerta", en: 0.1, origen: "declarado", canal: "race_control" },
    ];
    modulo.pintarAvisos();
    assert.ok(/De la carrera, no del piloto/.test(nodos["motivo-avisos"].textContent),
      "el pie no dice de quien son: " + nodos["motivo-avisos"].textContent);

    /* Con las dos clases mezcladas, se dice cuantas hay de cada una. */
    globalThis.estado.avisos = [
      { que: "derrape", nivel: "alerta", en: 0.2, canal: "wheel_slip_ratio_rear_left" },
    ];
    globalThis._firmaAvisos = "";
    modulo.pintarAvisos();
    const pie = nodos["motivo-avisos"].textContent;
    assert.ok(/1 del piloto/.test(pie) && /1 de la carrera/.test(pie), pie);
  } finally {
    /* Se limpia pase lo que pase: una lista que sobrevive al caso se la
       encuentra el siguiente y lo hace fallar por algo que no es suyo. */
    globalThis.estado.controlDeCarrera = [];
    reiniciar();
  }
});

prueba("sin respuesta, el panel no afirma que no ocurrio nada", () => {
  reiniciar();
  const t = new Error("la consulta no contestó en 30 s");
  t.name = "TiempoAgotado";
  modulo.anotarFalloDeAvisos(t);
  const nodos = documentoDePrueba();
  modulo.pintarAvisos();
  const html = nodos["lista-avisos"].innerHTML;
  assert.ok(html.indexOf("Todavía no ocurrió nada") === -1,
            "el panel afirma que no hubo incidentes sobre una consulta que " +
            "nunca contesto: " + html);
  assert.ok(/no (se pudieron|pudieron|pude)|no llegaron|no contest/i.test(html),
            "el panel no dice que los avisos no llegaron: " + html);
});

prueba("con respuesta vacia, el panel sigue diciendo lo de siempre", () => {
  reiniciar();
  const nodos = documentoDePrueba();
  modulo.pintarAvisos();
  const html = nodos["lista-avisos"].innerHTML;
  assert.ok(html.indexOf("Todavía no ocurrió nada") !== -1,
            "una sesion que de verdad no trajo avisos dejo de decirlo: " + html);
});

prueba("el recuento no inventa un cero cuando no hubo respuesta", () => {
  reiniciar();
  const t = new Error("la consulta no contestó en 30 s");
  t.name = "TiempoAgotado";
  modulo.anotarFalloDeAvisos(t);
  const nodos = documentoDePrueba();
  modulo.pintarAvisos();
  assert.notStrictEqual(nodos["canal-avisos"].textContent, "0/0",
                        "el encabezado declara «0/0», que es una medicion que " +
                        "nadie hizo");
});

prueba("cuando la consulta llega, el fallo deja de mostrarse", () => {
  reiniciar();
  const t = new Error("la consulta no contestó en 30 s");
  t.name = "TiempoAgotado";
  modulo.anotarFalloDeAvisos(t);
  globalThis.estado.avisosFallo = "";
  globalThis.estado.avisos = [
    { en: 0.1, nivel: "alerta", que: "fuera de pista", detalle: "cuatro ruedas",
      vuelta: 3, metro: 2704, canal: "umbral calibrado", umbral: "umbral calibrado" },
  ];
  const nodos = documentoDePrueba();
  modulo.pintarAvisos();
  const html = nodos["lista-avisos"].innerHTML;
  /* Con mayuscula inicial: el panel capitaliza al mostrar ---el backend escribe
     los incidentes en minuscula y ahi el titulo es ademas clave de
     agrupamiento---. Se busca el texto tal como se ve. */
  assert.ok(html.indexOf("Fuera de pista") !== -1, "no se dibujo el aviso: " + html);
  assert.ok(!/no (se pudieron|pudieron|pude)|no llegaron/i.test(html),
            "sigue mostrando el fallo ya resuelto: " + html);
});

/* ---- que el arreglo no se pueda esquivar ---- */

prueba("la carga de avisos enruta su fallo por el anotador", () => {
  const i = fuenteApp.indexOf('conCarga("avisos"');
  assert.ok(i !== -1, "no esta la carga de avisos en app.js");
  const bloque = fuenteApp.slice(i, i + 900);
  const catchDeAvisos = bloque.slice(bloque.indexOf(".catch("));
  assert.ok(catchDeAvisos.indexOf("anotarFalloDeAvisos") !== -1,
            "el `catch` de los avisos no pasa por `anotarFalloDeAvisos`, de " +
            "modo que un fallo vuelve a desaparecer sin rastro: " + catchDeAvisos);
});

prueba("la marca de fallo se limpia al abrir otra sesion", () => {
  const veces = (fuenteApp.match(/estado\.avisos = \[\]/g) || []).length;
  const limpiezas = (fuenteApp.match(/estado\.avisosFallo = ""/g) || []).length;
  assert.ok(limpiezas >= veces,
            "hay " + veces + " sitios que vacian `estado.avisos` y solo " +
            limpiezas + " que limpian la marca de fallo: una sesion nueva " +
            "heredaria el fallo de la anterior");
});

console.log(hechas + " casos, " + fallidas + " fallidos");
process.exit(fallidas ? 1 : 0);
