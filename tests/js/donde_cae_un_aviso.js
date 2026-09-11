/* Un aviso va donde ocurrio, y la fuente ya dice cuando.
 *
 * CRITERIO. Como los demas arneses, la funcion se **extrae del `app.js` que se
 * publica** y se ejecuta; no se copia.
 *
 * EL DEFECTO QUE ESTO CUIDA. `ubicarAvisos()` reconstruia el momento de cada
 * aviso a partir de `vuelta` y `metro`, ignorando el `instante` que `/avisos`
 * manda en **cada** aviso:
 *
 *     en = ini + parte * clamp((a.metro || 0) / largo)
 *
 * `a.metro || 0` no distingue «en el metro cero» de «no se donde». Es la misma
 * familia que `Number(null)` dando cero donde el cero es un valor legitimo, y
 * aca el cero no es un relleno inocente: es una posicion de la pista.
 *
 * MEDIDO el 2026-09-11 sobre `f1_25:session:3527452921763583202`: de los 24
 * avisos que devuelve la API, **20 vienen con `metro: null`** ---los seis del
 * aleron movil de la vuelta 1, los de la 2 y la 3, la bandera amarilla---.
 * Los catorce de la vuelta 1 terminaban apilados en la fraccion 0, todos
 * juntos en el arranque. Comprobado en el navegador contra el tablero
 * desplegado: los ocho primeros de `estado.avisos` salian con `en: 0`.
 *
 * LO QUE ESO ROMPIA. El panel muestra `todos.filter(a => a.en <= cabezal)`, de
 * modo que un aviso mal ubicado aparece antes o despues de cuando ocurrio. Es
 * la explicacion mas probable del reporte de que los avisos de la reproduccion
 * no coinciden con los del vivo: en vivo llegan en orden de llegada y en la
 * reproduccion se ordenaban por un metro que la mayoria no tiene.
 *
 * EL RELOJ QUE SE USA ES EL QUE YA ESTABA. Dentro de una vuelta, el tablero ya
 * convierte fraccion a UTC repartiendo linealmente sobre `[desde_utc,
 * hasta_utc]`. Aca se hace la cuenta inversa, con la misma aproximacion
 * declarada, para no introducir un segundo reloj que pueda desfasarse del
 * primero.
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

/* Las tres vueltas reales de la practica de Catalunya, con sus duraciones y
   sus ventanas UTC tal como las devuelve `/vueltas`. La tercera declara el
   hueco de 455,977 s: su `duracion_s` lo excluye y su ventana UTC lo incluye. */
const VUELTAS = [
  { numero: 1, duracion_s: 267.715, duracion_bruta_s: 267.715, continua: true,
    desde_utc: "2026-09-11T02:37:59.895808+00:00",
    hasta_utc: "2026-09-11T02:42:27.611079+00:00" },
  { numero: 2, duracion_s: 82.548, duracion_bruta_s: 82.548, continua: true,
    desde_utc: "2026-09-11T02:42:27.661097+00:00",
    hasta_utc: "2026-09-11T02:43:50.209498+00:00" },
  { numero: 3, duracion_s: 119.785, duracion_bruta_s: 575.762, continua: false,
    desde_utc: "2026-09-11T02:43:50.259547+00:00",
    hasta_utc: "2026-09-11T02:53:26.021697+00:00" },
];

globalThis.estado = { avisos: [], vueltas: VUELTAS.slice(), abierta: { duracion_s: 925.6 } };
globalThis.PISTA = { largo_m: 4660.5 };

const cuerpo = [
  extraer("duracionDeVuelta"),
  extraer("duracionSesionS"),
  extraer("iniciosDeVuelta"),
  extraer("numeroMedido"),
  extraer("fraccionDentroDeLaVuelta"),
  extraer("ubicarAvisos"),
  "return { ubicarAvisos, iniciosDeVuelta, duracionSesionS, duracionDeVuelta };",
].join("\n");
const modulo = new Function(cuerpo)();

let hechas = 0, fallidas = 0;
function prueba(nombre, fn) {
  hechas++;
  try { fn(); console.log("  ok  " + nombre); }
  catch (e) { fallidas++; console.log("  NO  " + nombre + "\n      " + e.message); }
}

console.log("donde cae un aviso");

/* ---- los avisos sin metro, que son la mayoria ---- */

prueba("dos avisos sin metro en instantes distintos no caen en el mismo sitio", () => {
  modulo.ubicarAvisos([
    { que: "Aleron movil en camino", vuelta: 1, metro: null,
      instante: "2026-09-11T02:40:20.202000+00:00" },
    { que: "Bandera amarilla", vuelta: 1, metro: null,
      instante: "2026-09-11T02:41:57.098000+00:00" },
  ]);
  const [a, b] = globalThis.estado.avisos;
  assert.notStrictEqual(a.en, b.en,
    "los dos avisos sin metro cayeron en la misma fraccion: " + a.en + " y " + b.en);
  assert.ok(b.en > a.en, "el posterior no quedo despues: " + a.en + " -> " + b.en);
});

prueba("un aviso sin metro no se apila en el arranque de su vuelta", () => {
  const inicios = modulo.iniciosDeVuelta();
  modulo.ubicarAvisos([
    { que: "Aleron movil habilitado", vuelta: 1, metro: null,
      instante: "2026-09-11T02:41:00.108000+00:00" },
  ]);
  const a = globalThis.estado.avisos[0];
  assert.ok(a.en > inicios[0] + 1e-6,
    "el aviso quedo pegado al inicio de la vuelta 1 (" + a.en + ")");
});

prueba("los catorce de la vuelta 1 quedan repartidos, no amontonados", () => {
  const instantes = ["02:40:20.202", "02:40:26.308", "02:40:54.452", "02:40:58.706",
                     "02:41:00.108", "02:41:00.909", "02:41:01.409", "02:41:02.910",
                     "02:41:05.513", "02:41:10.201", "02:41:51.108", "02:41:57.098",
                     "02:42:03.000", "02:42:20.000"];
  modulo.ubicarAvisos(instantes.map((h, i) => ({
    que: "aviso " + i, vuelta: 1, metro: null,
    instante: "2026-09-11T" + h + "000+00:00",
  })));
  const distintos = new Set(globalThis.estado.avisos.map(a => a.en.toFixed(6)));
  assert.strictEqual(distintos.size, instantes.length,
    "de " + instantes.length + " avisos solo hay " + distintos.size +
    " posiciones distintas");
});

/* ---- que el instante mande, y el metro sea el respaldo ---- */

prueba("con instante y metro, manda el instante", () => {
  modulo.ubicarAvisos([
    // El metro dice «arrancando la vuelta»; el instante dice «casi terminandola».
    { que: "fuera de pista", vuelta: 1, metro: 10,
      instante: "2026-09-11T02:42:20.000000+00:00" },
  ]);
  const a = globalThis.estado.avisos[0];
  const inicios = modulo.iniciosDeVuelta();
  const finVuelta1 = inicios[0] + modulo.duracionDeVuelta(1) / modulo.duracionSesionS();
  assert.ok(a.en > inicios[0] + (finVuelta1 - inicios[0]) * 0.8,
    "gano el metro sobre el instante: quedo en " + a.en);
});

prueba("sin instante, el metro sigue sirviendo", () => {
  modulo.ubicarAvisos([
    { que: "fuera de pista", vuelta: 1, metro: 2330.25, instante: null },
  ]);
  const a = globalThis.estado.avisos[0];
  const inicios = modulo.iniciosDeVuelta();
  const parte = modulo.duracionDeVuelta(1) / modulo.duracionSesionS();
  assert.ok(Math.abs(a.en - (inicios[0] + parte * 0.5)) < 0.02,
    "el respaldo por metro dejo de ubicar a media vuelta: " + a.en);
});

prueba("sin instante y sin metro no se inventa una posicion de pista", () => {
  modulo.ubicarAvisos([{ que: "sin nada", vuelta: 2, metro: null, instante: null }]);
  const a = globalThis.estado.avisos[0];
  const inicios = modulo.iniciosDeVuelta();
  assert.ok(Number.isFinite(a.en), "la fraccion dejo de ser un numero: " + a.en);
  assert.ok(Math.abs(a.en - inicios[1]) < 1e-9,
    "sin nada que decir, el aviso tiene que quedar al comienzo de su vuelta, " +
    "no en un metro inventado: " + a.en);
});

/* ---- que siga siendo una fraccion valida ---- */

prueba("un instante fuera de su vuelta no se sale de la vuelta", () => {
  modulo.ubicarAvisos([
    { que: "tarde", vuelta: 1, metro: null,
      instante: "2026-09-11T02:53:00.000000+00:00" },
    { que: "temprano", vuelta: 3, metro: null,
      instante: "2026-09-11T02:30:00.000000+00:00" },
  ]);
  const inicios = modulo.iniciosDeVuelta();
  const total = modulo.duracionSesionS();
  for (const a of globalThis.estado.avisos) {
    const v = a.vuelta;
    const lo = inicios[v - 1];
    const hi = lo + modulo.duracionDeVuelta(v) / total;
    assert.ok(a.en >= lo - 1e-9 && a.en <= hi + 1e-9,
      "el aviso de la vuelta " + v + " cayo en " + a.en + ", fuera de [" + lo + "," + hi + "]");
  }
});

prueba("la lista sigue saliendo ordenada", () => {
  modulo.ubicarAvisos([
    { que: "c", vuelta: 3, metro: null, instante: "2026-09-11T02:44:40.860000+00:00" },
    { que: "a", vuelta: 1, metro: null, instante: "2026-09-11T02:40:20.202000+00:00" },
    { que: "b", vuelta: 2, metro: null, instante: "2026-09-11T02:43:19.696000+00:00" },
  ]);
  assert.deepStrictEqual(globalThis.estado.avisos.map(a => a.que), ["a", "b", "c"]);
});

prueba("una sesion sin vueltas no rompe ni produce NaN", () => {
  const guardadas = globalThis.estado.vueltas;
  globalThis.estado.vueltas = [];
  try {
    modulo.ubicarAvisos([
      { que: "suelto", vuelta: 1, metro: null,
        instante: "2026-09-11T02:40:20.202000+00:00" },
    ]);
    const a = globalThis.estado.avisos[0];
    assert.ok(Number.isFinite(a.en), "la fraccion salio NaN: " + a.en);
  } finally {
    globalThis.estado.vueltas = guardadas;
  }
});

console.log(hechas + " casos, " + fallidas + " fallidos");
process.exit(fallidas ? 1 : 0);
