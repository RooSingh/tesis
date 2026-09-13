/* Que dice el tablero mientras escucha y no entra nada.
 *
 * CRITERIO. Como los demas arneses, las funciones se **extraen del `app.js`
 * que se publica** y se ejecutan; no se copian.
 *
 * QUE PASABA, MEDIDO EL 2026-09-12. Se le corto la corriente a la Pi con una
 * contrarreloj de Spa corriendo. Los valores se congelaron ---bien--- y los
 * graficos se vaciaron ---bien---, pero dos minutos despues el transporte
 * seguia diciendo «sin telemetria todavia · en cuanto el juego emita, el
 * tablero se llena solo» y el boton seguia ofreciendo «Detener escucha». La
 * persona recargo la pagina y volvio a empezar, que era lo unico que quedaba,
 * sin que nada en pantalla se lo dijera.
 *
 * LAS DOS AFIRMACIONES NO SON LA MISMA. «Todavia no llego ninguna» es cierta
 * antes de la primera muestra. Despues de un corte es falsa: llego telemetria,
 * lo que se ve es de antes del corte, y nada se va a llenar solo si el
 * capturador murio. El dato que las separa ya existia ---`vivo.ultimaLlegada`,
 * que el camino vivo escribe en cada muestra--- y esta linea no lo miraba.
 *
 * Y EL TEXTO NO SE REFRESCABA SOLO. La linea del transporte se escribe al
 * pintar, y pintar lo dispara una muestra: sin muestras no se pintaba nunca.
 * De modo que aunque hubiera dicho la verdad, la habria dicho una sola vez.
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

function constante(nombre) {
  const marca = "const " + nombre + " = ";
  const desde = fuenteApp.indexOf(marca);
  if (desde === -1) throw new Error("no esta la constante " + nombre);
  return fuenteApp.slice(desde, fuenteApp.indexOf(";", desde) + 1);
}

/* El banco: las tres funciones publicadas, con el estado de modulo del que
   dependen puesto desde afuera. `edadDelFlujo` lee `vivo` en tiempo de
   llamada, que es justo lo que permite moverlo entre casos. */
function banco(estadoDelModulo) {
  return new Function(
    "estado", "vivo", "ahora",
    [constante("HUECO_DE_CAPTURA_MS"),
     constante("SILENCIO_QUE_APAGA_MS"),
     extraer("comoSeVeElFlujo"),
     "function edadDelFlujo() {" +
     "  if (!vivo.ultimaLlegada) return null;" +
     "  return (ahora - vivo.ultimaLlegada) / 1000; }",
     extraer("loQueDiceLaEspera"),
     "return loQueDiceLaEspera;"].join("\n"))(
    estadoDelModulo.estado || {},
    estadoDelModulo.vivo || {},
    estadoDelModulo.ahora || 0);
}

let hechas = 0;
function prueba(nombre, fn) { fn(); hechas++; }

prueba("antes de la primera muestra, la espera se declara como espera", () => {
  const texto = banco({ vivo: { ultimaLlegada: null } })();
  assert.ok(/sin telemetría todavía/.test(texto), texto);
  assert.ok(/se llena solo/.test(texto), texto);
});

prueba("EL DEFECTO: despues de un corte ya no es «todavia»", () => {
  /* Los dos minutos reales del 2026-09-12. */
  const texto = banco({
    vivo: { ultimaLlegada: 1000 },
    ahora: 1000 + 120000,
  })();
  assert.ok(!/todavía/.test(texto),
    "sigue diciendo que nunca llego telemetria: " + texto);
  assert.ok(/se cortó/.test(texto), texto);
});

prueba("y dice que hacer, que es lo que faltaba", () => {
  const texto = banco({
    vivo: { ultimaLlegada: 1000 },
    ahora: 1000 + 120000,
  })();
  assert.ok(/detené la escucha/.test(texto),
    "no dice como volver a empezar: " + texto);
});

prueba("recibiendo con normalidad no se avisa nada", () => {
  /* Por debajo del umbral con el que todo el archivo decide que una captura se
     corto, un silencio es la cadencia del flujo y no un corte. */
  const texto = banco({
    vivo: { ultimaLlegada: 1000 },
    ahora: 1000 + 500,
  })();
  assert.strictEqual(texto, "recibiendo…");
});

prueba("si el difusor se declara caido, eso se dice en los dos casos", () => {
  /* Es una afirmacion distinta de las otras dos: no es que el juego no emita
     ni que el flujo se haya cortado en el camino, es que del otro lado no hay
     quien reparta. La declara `/live/status`. */
  const sinNada = banco({
    estado: { vivo: { conectado: false, motivo: "MQTT sin conexión" } },
    vivo: { ultimaLlegada: null },
  })();
  assert.ok(/difusor desconectado: MQTT sin conexión/.test(sinNada), sinNada);

  const trasElCorte = banco({
    estado: { vivo: { conectado: false } },
    vivo: { ultimaLlegada: 1000 },
    ahora: 1000 + 120000,
  })();
  assert.ok(/difusor desconectado/.test(trasElCorte), trasElCorte);
});

prueba("un difusor conectado no agrega ruido", () => {
  const texto = banco({
    estado: { vivo: { conectado: true } },
    vivo: { ultimaLlegada: null },
  })();
  assert.ok(!/difusor/.test(texto), texto);
});

/* -------- y el texto tiene que refrescarse sin muestras nuevas -------- */

prueba("EL SEGUNDO DEFECTO: la linea se escribia solo al pintar", () => {
  /* El reloj de un segundo existia y solo movia la marca de frescura. La linea
     del transporte quedaba con lo que decia en el ultimo dibujo, y el ultimo
     dibujo lo habia disparado la ultima muestra: la de antes del corte. */
  const i = fuenteApp.indexOf("function latidoDeFrescura(");
  assert.notStrictEqual(i, -1, "no esta el latido");
  const cuerpo = fuenteApp.slice(i, fuenteApp.indexOf("\n}", i));
  assert.ok(/marcarFrescuraDelFlujo\(\)/.test(cuerpo),
    "el latido dejo de mover la marca de frescura");
  assert.ok(/loQueDiceLaEspera\(\)/.test(cuerpo),
    "el latido no reescribe la linea del transporte");
  assert.ok(/setInterval\(latidoDeFrescura, 1000\)/.test(fuenteApp),
    "el reloj de un segundo no llama al latido");
});

prueba("y el vigia no se apaga por no haber sesion abierta", () => {
  /* `prepararEscucha` deja `estado.abierta` en nulo a proposito. El vigia
     salia por esa puerta, de modo que durante toda la espera nadie preguntaba
     por el difusor: el unico que puede decir que se cayo. */
  const i = fuenteApp.indexOf("function vigilarEnVivo(");
  assert.notStrictEqual(i, -1, "no esta vigilarEnVivo");
  const cuerpo = fuenteApp.slice(i, i + 1800);
  assert.ok(!/if \(!estado\.abierta\) \{ _relojVivo = null; return; \}/.test(cuerpo),
    "el vigia sigue apagandose en cuanto se empieza a escuchar");
  assert.ok(/estadoSesion === "escuchando"/.test(cuerpo),
    "el vigia no contempla la escucha");
});

console.log("ok " + hechas + " pruebas de escuchar sin recibir");
