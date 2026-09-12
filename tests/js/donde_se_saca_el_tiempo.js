/* Cuando se puede trazar el delta entre dos pilotos, y por que no cuando no.
 *
 * CRITERIO. Como los demas arneses, la funcion se **extrae del `app.js` que se
 * publica** y se ejecuta; no se copia.
 *
 * LO QUE ESTE ARNES DEFIENDE. La pantalla de comparacion superpone trazas: eso
 * dice **que** hizo distinto cada piloto. El delta dice **cuanto tiempo cambio
 * de manos y donde**, que es la pregunta con la que alguien abre esa pantalla.
 * Pero el delta tiene tres condiciones ---eje en distancia, una sola vuelta,
 * exactamente dos vehiculos--- y un panel que aparece y desaparece sin
 * explicarse se lee como un defecto del tablero.
 *
 * De ahi la regla: **cuando no se puede, se dice cual de las tres falta**.
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

const m = new Function(
  extraer("porQueNoHayDelta") + "\n" +
  extraer("claveDelDelta") + "\n" +
  "return { porQueNoHayDelta, claveDelDelta };")();

let hechas = 0;
function prueba(titulo, fn) {
  try { fn(); hechas++; }
  catch (e) {
    process.exitCode = 1;
    console.error("FALLA  " + titulo + "\n       " + e.message);
  }
}

prueba("con dos vehiculos, una vuelta y el eje en distancia, se traza", () => {
  assert.strictEqual(m.porQueNoHayDelta(2, "distancia", "una"), null);
});

prueba("contra el reloj no hay nada que alinear, y se dice", () => {
  /* El delta alinea las dos vueltas por el metro del circuito. Sobre el eje de
     tiempo las dos vueltas empiezan juntas por construccion y la diferencia en
     cada instante es la diferencia de **lo que llevan recorrido**, que es otra
     magnitud y no se mide en segundos. */
  const motivo = m.porQueNoHayDelta(2, "tiempo", "una");
  assert.ok(motivo, "no dijo por que no se puede");
  assert.ok(/metro|posici|reloj/i.test(motivo), "el motivo no nombra el eje: " + motivo);
});

prueba("con la carrera entera no hay dos vueltas que enfrentar", () => {
  const motivo = m.porQueNoHayDelta(2, "distancia", "carrera");
  assert.ok(motivo, "no dijo por que no se puede");
  assert.ok(/vuelta/i.test(motivo), "el motivo no nombra la vuelta: " + motivo);
});

prueba("con uno solo se pide otro, y con tres se pide quitar", () => {
  /* Los dos son «no son dos», y la salida es la contraria en cada caso: decirle
     «elegi un vehiculo mas» a quien tiene tres lo manda para el lado que no es. */
  const conUno = m.porQueNoHayDelta(1, "distancia", "una");
  const conTres = m.porQueNoHayDelta(3, "distancia", "una");
  assert.ok(/m[aá]s/i.test(conUno), "con uno no se pide otro: " + conUno);
  assert.ok(/3/.test(conTres), "con tres no se dice cuantos hay: " + conTres);
  assert.notStrictEqual(conUno, conTres, "los dos casos dicen lo mismo");
});

prueba("el eje manda sobre el resto", () => {
  /* Con el eje en tiempo **y** cinco vehiculos elegidos hay dos cosas mal, y la
     que corresponde decir es la que bloquea de verdad: cambiar de vehiculos no
     va a hacer aparecer el panel mientras el eje sea el reloj. */
  const motivo = m.porQueNoHayDelta(5, "tiempo", "carrera");
  assert.ok(/metro|posici|reloj/i.test(motivo),
    "con varias condiciones sin cumplir no se nombra la que bloquea: " + motivo);
});

prueba("la traza se identifica por sesion, vuelta y los dos pilotos", () => {
  /* La clave es lo que decide si un pedido se reusa. Si dejara fuera cualquiera
     de los cuatro, cambiar de piloto mostraria la traza del anterior: un dibujo
     correcto de otra cosa, que es la forma de equivocarse que no se ve. */
  const base = m.claveDelDelta("s1", 3, "a", "b");
  assert.notStrictEqual(base, m.claveDelDelta("s2", 3, "a", "b"), "no distingue la sesion");
  assert.notStrictEqual(base, m.claveDelDelta("s1", 4, "a", "b"), "no distingue la vuelta");
  assert.notStrictEqual(base, m.claveDelDelta("s1", 3, "c", "b"), "no distingue el primer piloto");
  assert.notStrictEqual(base, m.claveDelDelta("s1", 3, "a", "c"), "no distingue el segundo piloto");
  assert.notStrictEqual(base, m.claveDelDelta("s1", 3, "b", "a"),
    "no distingue el orden: el signo del delta depende de cual va primero");
});

if (process.exitCode) {
  console.error("\n" + hechas + " pruebas pasaron; hubo fallos.");
} else {
  console.log(hechas + " pruebas de donde se saca el tiempo: OK");
}
