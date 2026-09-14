/* Con que vuelta se dibuja el circuito.
 *
 * CRITERIO. Como los demas arneses, la funcion se **extrae del `app.js` que se
 * publica** y se ejecuta; no se copia.
 *
 * QUE PASABA, REPORTADO EL 2026-09-13. Cargada la carrera de Spa, el circuito
 * salia con un hueco: un tramo recto que nadie recorrio, atravesando el dibujo.
 *
 * MEDIDO CONTRA LA API, vuelta por vuelta, con el cierre que la propia respuesta
 * declara ---la distancia entre el primer punto y el ultimo---:
 *
 *     vuelta  1    cierre 2.122,6 m
 *     vuelta  2    cierre   113,2 m
 *     vuelta  3    cierre   137,8 m
 *     vuelta 10    cierre   155,0 m
 *     vuelta 25    cierre    49,9 m
 *
 * LA VUELTA 1 DE UNA CARRERA NO ES UNA VUELTA AL CIRCUITO. Los coches arrancan
 * **desde la parrilla**, de modo que ese giro va de la parrilla a la meta y le
 * falta el tramo que va de la meta a la parrilla. No es un dato malo: es un dato
 * que describe otra cosa. Lo mismo pasa en una contrarreloj, donde la primera
 * sale de boxes.
 *
 * Y EL TABLERO ELEGIA JUSTO ESA: pedia «la primera vuelta completa y continua»,
 * y la vuelta 1 cumple las dos condiciones. Estaba bien medida y era la
 * equivocada.
 *
 * POR QUE ESTA REGLA Y NO UN UMBRAL DE CIERRE. Descartar por «cierra mal» obliga
 * a elegir cuanto es mal, y ese numero habria que justificarlo contra cada
 * fuente y cada frecuencia de muestreo. Lo que se sabe sin medir nada es mas
 * fuerte: **la vuelta 1 es la unica que puede empezar en otro sitio**; de la
 * segunda en adelante, cada una empieza donde termino la anterior, que es la
 * linea. La regla no es sobre carreras: es sobre lo que una vuelta es.
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

const conQueVuelta = new Function(
  extraer("conQueVueltaSeDibuja") + "\nreturn conQueVueltaSeDibuja;")();

const v = (numero, extra) => Object.assign(
  { numero, completa: true, continua: true }, extra || {});

let hechas = 0;
function prueba(nombre, fn) {
  try { fn(); hechas++; } catch (e) {
    process.exitCode = 1;
    console.error("FALLA  " + nombre + "\n       " + (e && e.message));
  }
}

prueba("EL DEFECTO: con varias vueltas no se dibuja con la primera", () => {
  const elegida = conQueVuelta([v(1), v(2), v(3)]);
  assert.strictEqual(elegida && elegida.numero, 2,
    "sigue dibujando el circuito con la vuelta que arranca en la parrilla");
});

prueba("y se salta las rotas igual que antes", () => {
  const elegida = conQueVuelta([v(1), v(2, { continua: false }),
                                v(3, { completa: false }), v(4)]);
  assert.strictEqual(elegida.numero, 4);
});

prueba("SI LA UNICA VUELTA ES LA PRIMERA, SE USA ESA", () => {
  /* Una contrarreloj de una sola vuelta, o una sesion que se corto. No dibujar
     nada seria peor que dibujar el giro que hay, que es real aunque no cierre. */
  assert.strictEqual(conQueVuelta([v(1)]).numero, 1);
});

prueba("y si las demas no sirven, tambien", () => {
  const elegida = conQueVuelta([v(1), v(2, { continua: false })]);
  assert.strictEqual(elegida.numero, 1);
});

prueba("sin ninguna vuelta usable no se inventa una", () => {
  /* Quien llama pide sin elegir y **lo declara**, que es lo que ya hacia. */
  assert.strictEqual(conQueVuelta([]), null);
  assert.strictEqual(conQueVuelta([v(1, { completa: false })]), null);
  assert.strictEqual(conQueVuelta(null), null);
});

prueba("LA REGLA NO MIRA EL TIPO DE SESION", () => {
  /* Podria haberse escrito «si es una carrera, saltear la primera». Seria mas
     estrecho y ademas falso: en una contrarreloj la primera sale de boxes y
     tampoco cierra. Lo que decide es que la vuelta 1 es la unica que puede
     empezar en otro sitio. */
  const cuerpo = extraer("conQueVueltaSeDibuja")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .split("\n").map(r => r.split("//")[0]).join("\n");
  assert.ok(!/carrera|Race|tipo|familia/i.test(cuerpo),
    "la eleccion se ato al tipo de sesion: " + cuerpo);
});

prueba("no se reordena la lista de quien llama", () => {
  /* `estado.vueltas` la usan la linea de tiempo y el cronometraje. */
  const lista = [v(3), v(1), v(2)];
  const copia = lista.map(x => x.numero);
  conQueVuelta(lista);
  assert.deepStrictEqual(lista.map(x => x.numero), copia);
});

console.log("ok " + hechas + " pruebas de con que vuelta se dibuja");
