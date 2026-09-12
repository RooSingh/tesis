/* El panel de reglaje dice por que no hay reglaje, y no se lo inventa.
 *
 * CRITERIO. Como los demas arneses, la funcion se **extrae del `app.js` que se
 * publica** y se ejecuta; no se copia.
 *
 * EL DEFECTO QUE ESTO CUIDA. La interfaz de consulta distingue con cuidado dos
 * ausencias que no son la misma (`backend/api_sesion.py:2729`):
 *
 *   * de F1 25: «Esta sesion no contiene el paquete de reglaje normalizado; las
 *     capturas anteriores necesitan reinyectarse» ---la fuente si lo publica, y
 *     es esta captura la que es anterior---;
 *   * de las demas fuentes: «Esta fuente no publica configuracion del
 *     vehiculo».
 *
 * El tablero tiraba esa distincion por dos motivos a la vez. Leia
 * `d.motivo_ausencia`, que es el nombre del campo en la ruta
 * `/puesta-a-punto` ---que el tablero no consulta--- y no en `/contexto`, que
 * lo manda como `puesta_motivo`. Y ademas `estado.puesta` solo se asignaba
 * **cuando habia campos**, de modo que justo en el caso en que hace falta un
 * motivo no habia de donde sacarlo. El resultado era que el panel imprimia
 * siempre el texto de respaldo.
 *
 * MEDIDO el 2026-09-12 sobre `f1_25:session:3731090176871608020`, la carrera de
 * Spa: `/contexto` devuelve el motivo correcto ---el de la captura anterior--- y
 * la pantalla decia «Esta fuente no publica configuracion del vehiculo». Es
 * falso: F1 25 la publica, y las dos sesiones de esta base que si tienen
 * `setup_*` lo demuestran. El tablero le atribuia a la fuente lo que era de la
 * captura, que es la confusion que este trabajo declara evitar.
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

const modulo = new Function(
  extraer("motivoDeLaPuesta") + "\nreturn { motivoDeLaPuesta };")();

let hechas = 0, fallidas = 0;
function prueba(nombre, fn) {
  hechas++;
  try { fn(); console.log("  ok  " + nombre); }
  catch (e) { fallidas++; console.log("  NO  " + nombre + "\n      " + e.message); }
}

console.log("por que no hay puesta a punto");

/* El texto exacto que la interfaz de consulta devuelve para cada caso. */
const DE_F1_25 = "Esta sesion no contiene el paquete de reglaje normalizado; " +
                 "las capturas anteriores necesitan reinyectarse.";
const DE_OTRA_FUENTE = "Esta fuente no publica configuracion del vehiculo.";

prueba("el motivo de /contexto llega tal cual", () => {
  assert.strictEqual(
    modulo.motivoDeLaPuesta({ puesta_motivo: DE_F1_25 }), DE_F1_25);
});

prueba("no se confunde la captura vieja con una fuente que no publica reglaje", () => {
  const dicho = modulo.motivoDeLaPuesta({ puesta_motivo: DE_F1_25 });
  assert.ok(!/no publica/.test(dicho),
    "el panel le atribuye a la fuente lo que es de la captura: " + dicho);
});

prueba("el motivo de /puesta-a-punto tambien sirve", () => {
  assert.strictEqual(
    modulo.motivoDeLaPuesta({ motivo_ausencia: DE_OTRA_FUENTE }), DE_OTRA_FUENTE);
});

prueba("si vienen los dos, manda el de la ruta que se consulto", () => {
  assert.strictEqual(
    modulo.motivoDeLaPuesta({ puesta_motivo: DE_F1_25,
                              motivo_ausencia: DE_OTRA_FUENTE }), DE_F1_25);
});

prueba("sin respuesta no se inventa un motivo", () => {
  assert.strictEqual(modulo.motivoDeLaPuesta(null), "");
  assert.strictEqual(modulo.motivoDeLaPuesta(undefined), "");
  assert.strictEqual(modulo.motivoDeLaPuesta({}), "");
});

prueba("un motivo vacio no es un motivo", () => {
  assert.strictEqual(modulo.motivoDeLaPuesta({ puesta_motivo: "" }), "");
  assert.strictEqual(
    modulo.motivoDeLaPuesta({ puesta_motivo: "", motivo_ausencia: DE_OTRA_FUENTE }),
    DE_OTRA_FUENTE);
});

/* ---- la guarda estructural: que nadie vuelva a leer el campo que no viene ---- */

prueba("el tablero no lee motivo_ausencia de la respuesta de contexto", () => {
  /* `/contexto` manda `puesta_motivo`. Buscar `motivo_ausencia` sobre esa
     respuesta daba siempre `undefined`, y de ahi salia el texto de respaldo. */
  const sinComentarios = fuenteApp
    .split("\n")
    .map(r => r.split("//")[0])
    .join("\n");
  const pintar = extraer("pintarPuestaAPunto");
  const pintarSinComentarios = pintar.split("\n").map(r => r.split("//")[0]).join("\n");
  assert.ok(!/d\s*&&\s*d\.motivo_ausencia/.test(pintarSinComentarios),
    "pintarPuestaAPunto vuelve a leer el motivo del objeto que solo existe " +
    "cuando hay campos, que es justo cuando no hace falta un motivo");
  assert.ok(/estado\.puestaMotivo/.test(sinComentarios),
    "el motivo del reglaje no se guarda en el estado como el del clima y el " +
    "del vehiculo");
});

prueba("el estado declara el motivo del reglaje, como los otros dos", () => {
  const sinComentarios = fuenteApp.split("\n").map(r => r.split("//")[0]).join("\n");
  assert.ok(/puestaMotivo\s*:\s*""/.test(sinComentarios),
    "falta `puestaMotivo` entre los campos del estado");
});

console.log(hechas + " casos, " + fallidas + " fallidos");
process.exit(fallidas ? 1 : 0);
