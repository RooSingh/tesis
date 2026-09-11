/* Dos capturas de la misma sesion tienen que poder distinguirse por el nombre.
 *
 * CRITERIO. Como los demas arneses, las funciones se **extraen del `app.js` que
 * se publica** y se ejecutan; no se copian.
 *
 * EL DEFECTO QUE ESTO CUIDA. Desde que la API separa las capturas originales
 * ---`original-1`, `original-2`--- el elector muestra una fila por cada una,
 * pero las dos decian «Original» con la misma fecha:
 *
 *     Original   captura original · 10/09/2026   5 vehiculos   45.525 muestras
 *     Original   captura original · 10/09/2026   5 vehiculos    1.500 muestras
 *
 * Comprobado en el navegador contra el backend real. Se distinguian solo por la
 * cantidad de muestras y la duracion, que es pedirle a quien mira que deduzca
 * cual es cual. Elegir mal es reproducir la captura equivocada.
 *
 * El nombre se decide en **un solo sitio**: el elector y el encabezado lo
 * escribian cada uno por su cuenta y nada obligaba a que coincidieran.
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

const UNA = [{ clave: "original", es_reproduccion: false }];
const DOS = [{ clave: "original-1", es_reproduccion: false },
             { clave: "original-2", es_reproduccion: false }];
const TRES = [{ clave: "original-1", es_reproduccion: false },
              { clave: "original-2", es_reproduccion: false },
              { clave: "original-3", es_reproduccion: false }];
const CON_CORRIDA = [{ clave: "original-1", es_reproduccion: false },
                     { clave: "original-2", es_reproduccion: false },
                     { clave: "corrida-abc", es_reproduccion: true }];

const modulo = new Function(
  extraer("nombreDeAdquisicion") + "\nreturn { nombreDeAdquisicion };")();

let hechas = 0, fallidas = 0;
function prueba(nombre, fn) {
  hechas++;
  try { fn(); console.log("  ok  " + nombre); }
  catch (e) { fallidas++; console.log("  NO  " + nombre + "\n      " + e.message); }
}

console.log("como se llama una captura");

prueba("con una sola captura sigue diciendo Original", () => {
  assert.strictEqual(modulo.nombreDeAdquisicion(UNA[0], UNA), "Original");
});

prueba("con dos capturas, cada una dice cual es", () => {
  const a = modulo.nombreDeAdquisicion(DOS[0], DOS);
  const b = modulo.nombreDeAdquisicion(DOS[1], DOS);
  assert.notStrictEqual(a, b, "las dos capturas se llaman igual: " + a);
  assert.ok(/1/.test(a) && /2/.test(a),
            "la primera no dice cual es de cuantas: " + a);
  assert.ok(/2/.test(b), "la segunda no se identifica: " + b);
});

prueba("con tres, la del medio tambien se identifica", () => {
  const nombres = TRES.map(x => modulo.nombreDeAdquisicion(x, TRES));
  assert.strictEqual(new Set(nombres).size, 3, "se repiten: " + nombres.join(" / "));
});

prueba("una reproduccion conserva su identificador", () => {
  assert.strictEqual(
    modulo.nombreDeAdquisicion(CON_CORRIDA[2], CON_CORRIDA), "corrida-abc");
});

prueba("las corridas no cuentan como capturas al numerar", () => {
  const a = modulo.nombreDeAdquisicion(CON_CORRIDA[0], CON_CORRIDA);
  assert.ok(!/de 3/.test(a),
            "conto la reproduccion como si fuera una captura: " + a);
});

prueba("sin lista de disponibles no se rompe", () => {
  assert.ok(modulo.nombreDeAdquisicion({ clave: "original", es_reproduccion: false }, null));
  assert.ok(modulo.nombreDeAdquisicion({ clave: "original-1", es_reproduccion: false }, []));
});

/* ---- que el nombre se decida en un solo sitio ---- */

prueba("el elector y el encabezado usan el mismo nombre", () => {
  for (const donde of ["filaDeCorrida", "etiquetaDeCorrida"]) {
    const cuerpo = extraer(donde);
    const codigo = cuerpo.split("\n")
      .filter(r => !/^\s*(\/\/|\*|\/\*)/.test(r)).join("\n");
    assert.ok(codigo.indexOf("nombreDeAdquisicion") !== -1,
              donde + " escribe el nombre por su cuenta en vez de pedirlo");
    assert.ok(codigo.indexOf('"Original"') === -1,
              donde + ' sigue teniendo "Original" escrito a mano');
  }
});

console.log(hechas + " casos, " + fallidas + " fallidos");
process.exit(fallidas ? 1 : 0);
