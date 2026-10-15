/* El panel «Vehiculo» se actualiza en vivo.
 *
 * CRITERIO. Como los demas arneses, la funcion se **extrae del `app.js` que se
 * publica** y se ejecuta; no se copia.
 *
 * EL DEFECTO QUE ESTO CUIDA. `pintarEsquinas` se salta el repintado cuando su
 * firma no cambia, y la firma solo miraba el avance del cabezal. En vivo el
 * avance vale siempre uno: el panel se pintaba una vez y las temperaturas,
 * presiones, frenos y desgaste de las ruedas quedaban congelados mientras
 * `sincronizarContextoVivo` renovaba `estado.vehiculo` con cada muestra.
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

/* Un documento minimo: una esquina con `innerHTML` y nada mas. */
const esquina = { dataset: { esquina: "front_left" }, innerHTML: "" };
const documento = {
  querySelectorAll: sel => (sel === "[data-esquina]" ? [esquina] : []),
  getElementById: id => (id === "leyenda-dano" ? { innerHTML: "" } : null),
};

const modulo = new Function("document",
  "let _firmaEsquinas = '';\n" +
  "let fuente = 'f1';\n" +
  "let estadoSesion = 'vivo';\n" +
  "const estado = { vehiculo: null };\n" +
  "const instante = () => ({ avance: 1, frenando: 0 });\n" +
  "const tinta = () => '#000';\n" +
  "const cifra = (v, d) => (v === null || v === undefined) ? '—' : Number(v).toFixed(d);\n" +
  "const colorTemp = () => 'x';\n" +
  "const colorVida = () => 'x';\n" +
  extraer("esquinaViva") + "\n" + extraer("pintarEsquinas") + "\n" +
  "return { pintarEsquinas, estado };")(documento);

let hechas = 0, fallidas = 0;
function prueba(nombre, fn) {
  hechas++;
  try { fn(); console.log("  ok  " + nombre); }
  catch (e) { fallidas++; console.log("  NO  " + nombre + "\n      " + e.message); }
}

console.log("el vehiculo en vivo");

const conTemperatura = t => ({
  esquinas: { front_left: { temperatura_superficie_c: t, presion_psi: 22.5 } },
  carroceria: {},
});

prueba("una temperatura nueva se ve aunque el cabezal no se mueva", () => {
  modulo.estado.vehiculo = conTemperatura(90);
  modulo.pintarEsquinas();
  assert.ok(/90&nbsp;°C/.test(esquina.innerHTML), esquina.innerHTML);
  modulo.estado.vehiculo = conTemperatura(97);
  modulo.pintarEsquinas();
  assert.ok(/97&nbsp;°C/.test(esquina.innerHTML),
    "el panel se quedo con la temperatura anterior: " + esquina.innerHTML);
});

prueba("sin cambios no se vuelve a escribir el panel", () => {
  modulo.estado.vehiculo = conTemperatura(97);
  modulo.pintarEsquinas();
  esquina.innerHTML = "sin tocar";
  modulo.pintarEsquinas();
  assert.strictEqual(esquina.innerHTML, "sin tocar");
});

console.log("el_vehiculo_en_vivo: " + hechas + " comprobaciones, " + fallidas + " fallidas");
if (fallidas) process.exit(1);
