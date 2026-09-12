/* Cuando ofrecer elegir a quien escuchar, y cuando no hay a quien.
 *
 * CRITERIO. La funcion se **extrae del `app.js` que se publica** y se ejecuta.
 *
 * QUE PASABA. El selector recorria la parrilla declarada **sin ningun filtro**.
 * En una contrarreloj de Shanghai eso ofrecia catorce vehiculos que no existen:
 * la parrilla de ese modo la llenan los fantasmas de la tabla de tiempos en
 * linea ---«Fantasma predeterminado», «Mejor tiempo personal» y el resto--- y
 * ninguno publica telemetria. La respuesta lo decia sin ambiguedad:
 * `vehiculos: 15` y `vehiculos_en_carrera: 1`.
 *
 * Y no es solo ruido. `backend/f1_udp.py:233` ya declara que en contrarreloj la
 * parrilla trae **identificadores de otras personas**. Ofrecer «escuchar» a
 * catorce entradas que no publican nada, algunas con el nombre de alguien, es
 * peor que inutil.
 *
 * POR QUE ESTA VEZ SI SE MIRA EL MODO. En el caso del salto del vehiculo ---ver
 * `tests/js/un_salto_no_es_un_tramo.js`--- la regla explicitamente **no** es del
 * modo, porque un salto ocurre en cualquiera. Aca es al reves: que no haya
 * rivales es una propiedad del contrarreloj y de ningun otro modo, y la fuente
 * la declara en `familia_de_sesion`. Distinguir los dos casos es el punto.
 *
 * ANTE LA DUDA SE OFRECE. Mientras la procedencia no llegue no se sabe que modo
 * es, y esconder el selector por las dudas lo haria parpadear al arrancar cada
 * sesion.
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

const hayAQuienEscuchar = new Function(`
  ${extraer("hayAQuienEscuchar")}
  return hayAQuienEscuchar;
`)();

let hechas = 0;
function prueba(nombre, fn) { fn(); hechas++; }

/* La procedencia real de la captura, tal como la devolvio la API el
   2026-09-12 para `f1_25:session:16227589096132074312`. */
const SHANGHAI = {
  circuito: "shanghai", tipo_sesion: "contrarreloj",
  tipo_sesion_nombre: "Contrarreloj", familia_de_sesion: "contrarreloj",
  modo_juego: "contrarreloj", vueltas_totales: 1,
};

prueba("en contrarreloj no hay a quien escuchar", () => {
  assert.strictEqual(hayAQuienEscuchar(SHANGHAI), false);
});

prueba("en una carrera si lo hay", () => {
  assert.strictEqual(hayAQuienEscuchar(
    { tipo_sesion: "carrera", familia_de_sesion: "carrera" }), true);
});

prueba("en practica y clasificacion tambien", () => {
  for (const f of ["practica", "clasificacion", "sprint"]) {
    assert.strictEqual(hayAQuienEscuchar({ familia_de_sesion: f }), true, f);
  }
});

prueba("sin procedencia todavia, se ofrece", () => {
  /* No saber el modo no es saber que es contrarreloj. Esconderlo por las dudas
     lo haria parpadear al arrancar cada sesion, que es un defecto visible por
     evitar uno que no se sabe si existe. */
  assert.strictEqual(hayAQuienEscuchar(null), true);
  assert.strictEqual(hayAQuienEscuchar(undefined), true);
  assert.strictEqual(hayAQuienEscuchar({}), true);
});

prueba("la familia manda sobre el resto de los campos", () => {
  /* Tres campos dicen lo mismo ---`tipo_sesion`, `familia_de_sesion` y
     `modo_juego`--- y uno solo tiene que decidir, o el dia que difieran habra
     dos respuestas para una pregunta. La familia es la que agrupa, y es la que
     el catalogo de sesiones ya usa. */
  assert.strictEqual(hayAQuienEscuchar(
    { familia_de_sesion: "contrarreloj", tipo_sesion: "carrera" }), false);
  assert.strictEqual(hayAQuienEscuchar(
    { familia_de_sesion: "carrera", tipo_sesion: "contrarreloj" }), true);
});

prueba("se compara sin importar mayusculas ni espacios", () => {
  assert.strictEqual(hayAQuienEscuchar({ familia_de_sesion: " Contrarreloj " }), false);
});

prueba("el selector consulta esta funcion y no la parrilla a secas", () => {
  /* Se comprueba sobre el `app.js` publicado: la funcion podria existir y
     nadie llamarla, que es como quedan los arreglos a medias. */
  const i = fuenteApp.indexOf("function pintarEligeEscucha(");
  assert.notStrictEqual(i, -1, "no esta pintarEligeEscucha");
  const cuerpo = fuenteApp.slice(i, i + 1400);
  assert.ok(/hayAQuienEscuchar\(/.test(cuerpo),
    "pintarEligeEscucha no consulta hayAQuienEscuchar");
});

console.log("ok " + hechas + " pruebas de a quien escuchar");
