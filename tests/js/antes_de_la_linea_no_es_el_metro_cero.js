/* Donde esta el coche cuando todavia no cruzo la linea de largada.
 *
 * CRITERIO. La funcion se **extrae del `app.js` que se publica** y se ejecuta.
 *
 * QUE PASABA. En la reproduccion, los primeros segundos de la vuelta 1 el coche
 * no se movia: quedaba clavado en la linea de meta.
 *
 * POR QUE. El protocolo publica `lap_distance` **negativa antes de cruzar la
 * linea** ---`backend/f1_udp.py:462`---. La colocacion preguntaba
 * `enPistaAhora[clave] !== undefined`, que un negativo cumple, y despues
 * recortaba con `Math.max(0, metro / largo)`: **fraccion cero constante** hasta
 * que el metro se volvia positivo.
 *
 * Y LO PEOR NO ERA QUE NO SE MOVIERA. El coche quedaba marcado como
 * `seUbicoMidiendo`, sin `data-estimada`, de modo que el tablero **afirmaba una
 * posicion medida que en realidad era un recorte**. El comentario que esta
 * justo encima de ese codigo declara la regla que el codigo rompia: «una
 * posicion supuesta y una medida no pueden verse igual».
 *
 * Medido sobre `f1_25:session:16227589096132074312` el 2026-09-12: la sesion
 * arranca en el metro **-5.342,3** y el salto de la vuelta lanzada la deja en
 * **-911,1**. Son miles de metros de sesion antes de la linea.
 *
 * UN METRO NEGATIVO NO ES UN DATO FALTANTE. La fuente esta diciendo donde esta
 * el coche: **antes de la linea**. Lo que no puede hacer es ubicarlo dentro de
 * la vuelta, porque la vuelta todavia no empezo. Por eso esta funcion devuelve
 * `null` ---no hay fraccion--- y no cero, que seria una posicion inventada.
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

const fraccionDelMetro = new Function(
  `${extraer("fraccionDelMetro")} return fraccionDelMetro;`)();

let hechas = 0;
function prueba(nombre, fn) { fn(); hechas++; }

prueba("EL DEFECTO: un metro negativo no ubica en la vuelta", () => {
  assert.strictEqual(fraccionDelMetro(-5342.3, 5441), null,
    "un metro de antes de la linea se convirtio en una posicion de la vuelta");
  assert.strictEqual(fraccionDelMetro(-911.1, 5441), null);
  assert.strictEqual(fraccionDelMetro(-0.1, 5441), null);
});

prueba("y no se lo confunde con el metro cero", () => {
  /* La diferencia entera del defecto: cero es un sitio del circuito ---la
     linea--- y negativo es «todavia no llego». Devolver cero para los dos hace
     que el coche se plante en la meta y que ademas se lo declare medido. */
  assert.strictEqual(fraccionDelMetro(0, 5441), 0);
  assert.notStrictEqual(fraccionDelMetro(-1, 5441), 0);
});

prueba("un metro de la vuelta da su fraccion", () => {
  assert.strictEqual(fraccionDelMetro(2720.5, 5441), 0.5);
  assert.strictEqual(fraccionDelMetro(5441, 5441), 1);
});

prueba("pasarse de largo si se recorta, porque ahi el coche esta", () => {
  /* El extremo de arriba si se recorta: una muestra unos metros pasada la
     linea sigue ubicando al coche sobre el circuito. El de abajo no, porque
     antes de la linea no hay circuito que recorrer todavia. Los dos extremos
     no son simetricos y por eso se tratan distinto. */
  assert.strictEqual(fraccionDelMetro(5450, 5441), 1);
});

prueba("sin metro no se inventa una fraccion", () => {
  assert.strictEqual(fraccionDelMetro(undefined, 5441), null);
  assert.strictEqual(fraccionDelMetro(null, 5441), null);
  assert.strictEqual(fraccionDelMetro(NaN, 5441), null);
  assert.strictEqual(fraccionDelMetro("1200", 5441), null);
});

prueba("sin largo de vuelta tampoco", () => {
  /* Dividir por cero da infinito y el recorte lo convierte en 1: el coche
     aparecería en la meta con aire de medido. */
  assert.strictEqual(fraccionDelMetro(1200, 0), null);
  assert.strictEqual(fraccionDelMetro(1200, null), null);
});

prueba("la colocacion consulta esta funcion y no recorta por su cuenta", () => {
  /* Se comprueba sobre el `app.js` publicado: el recorte viejo
     ---`Math.max(0, Math.min(1, ... / largoVuelta))`--- es justo lo que
     convertia un negativo en cero, y si sobrevive al lado el defecto vuelve. */
  /* Se ancla en `let medidaDeVerdad`, que es marca propia de la colocacion y
     no la linea que este arreglo cambia: anclar en lo que uno modifica hace
     que la prueba deje de encontrar su objeto en cuanto el arreglo entra. */
  const i = fuenteApp.indexOf("let medidaDeVerdad = false;");
  assert.notStrictEqual(i, -1, "no esta la colocacion del coche");
  const bloque = fuenteApp.slice(Math.max(0, i - 400), i + 400);
  assert.ok(/fraccionDelMetro\(/.test(bloque),
    "la colocacion no consulta fraccionDelMetro");
  assert.ok(!/Math\.max\(0, Math\.min\(1, enPistaAhora/.test(bloque),
    "sigue el recorte que convertia un negativo en cero");
});

console.log("ok " + hechas + " pruebas del metro antes de la linea");
