/* Pruebas de comportamiento de los ayudantes de serie del tablero.
 *
 * CRITERIO. No se copia el codigo aca: se **extrae del `app.js` que se
 * publica** y se lo ejecuta. Una prueba contra una copia comprueba que la
 * copia funciona, que es justo lo que no interesa saber.
 *
 * Solo se extraen funciones puras ---las que reciben datos y devuelven datos---
 * porque el resto de `app.js` toca el documento y no existe fuera de un
 * navegador. Lo que se ejercita aca es la aritmetica de series: que decide que
 * un valor esta medido, como se recorta un dominio y como se arma una escala.
 * Es donde estaban los defectos que se corrigieron el 2026-09-07.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");

const APP = path.join(__dirname, "..", "..", "dashboard", "app.js");
const fuente = fs.readFileSync(APP, "utf8");

/* Saca una funcion por nombre, contando llaves desde su apertura. */
function extraer(nombre) {
  const marca = "function " + nombre + "(";
  const desde = fuente.indexOf(marca);
  if (desde === -1) throw new Error("no esta la funcion " + nombre + " en app.js");
  let i = fuente.indexOf("{", desde);
  let nivel = 0;
  for (; i < fuente.length; i++) {
    if (fuente[i] === "{") nivel++;
    else if (fuente[i] === "}") {
      nivel--;
      if (nivel === 0) return fuente.slice(desde, i + 1);
    }
  }
  throw new Error("no cierra la funcion " + nombre);
}

const NOMBRES = ["numeroMedido", "extremosDeDistancia", "recortarPorDominio",
                 "escalaDe", "dominioAmpliado", "reducirAAncho"];

/* `ampliado` es una variable del modulo del tablero, y `dominioAmpliado` la
   lee de su entorno. Aca se la pone en el ambito global, que es lo que ve el
   cuerpo de una funcion construida con `new Function`.

   Se usa `new Function` y no `eval` porque este archivo corre en modo estricto
   y ahi `eval` no publica sus declaraciones fuera de si mismo. */
globalThis.ampliado = false;
const codigo = NOMBRES.map(extraer).join("\n\n");
const sacadas = new Function(codigo + "\nreturn { " + NOMBRES.join(", ") + " };")();
const numeroMedido = sacadas.numeroMedido;
const extremosDeDistancia = sacadas.extremosDeDistancia;
const recortarPorDominio = sacadas.recortarPorDominio;
const escalaDe = sacadas.escalaDe;
const dominioAmpliado = sacadas.dominioAmpliado;
const reducirAAncho = sacadas.reducirAAncho;

let hechas = 0;
function prueba(titulo, fn) {
  try {
    fn();
    hechas++;
  } catch (error) {
    console.error("FALLO: " + titulo);
    console.error("  " + error.message);
    process.exitCode = 1;
  }
}

/* ------------------------------------------------------------------
   numeroMedido: cero medido y cero inventado no son lo mismo
   ------------------------------------------------------------------ */
prueba("null, cadena vacia e indefinido no son cero", () => {
  assert.strictEqual(numeroMedido(null), null, "null daba 0 con Number()");
  assert.strictEqual(numeroMedido(""), null, "la cadena vacia daba 0");
  assert.strictEqual(numeroMedido("   "), null);
  assert.strictEqual(numeroMedido(undefined), null);
  assert.strictEqual(numeroMedido([]), null, "el arreglo vacio daba 0");
  assert.strictEqual(numeroMedido({}), null);
});

prueba("un cero medido sigue siendo cero", () => {
  assert.strictEqual(numeroMedido(0), 0);
  assert.strictEqual(numeroMedido("0"), 0);
  assert.strictEqual(numeroMedido(-0), -0);
});

prueba("un booleano es una bandera, y vale por definicion de la fuente", () => {
  assert.strictEqual(numeroMedido(true), 1);
  assert.strictEqual(numeroMedido(false), 0);
});

prueba("no entra nada que no sea finito", () => {
  assert.strictEqual(numeroMedido(NaN), null);
  assert.strictEqual(numeroMedido(Infinity), null);
  assert.strictEqual(numeroMedido(-Infinity), null);
  assert.strictEqual(numeroMedido("no es un numero"), null);
});

prueba("un numero escrito se acepta; uno con coma decimal no se adivina", () => {
  assert.strictEqual(numeroMedido("12.5"), 12.5);
  assert.strictEqual(numeroMedido(" 12.5 "), 12.5);
  // Interpretar "12,5" como 12,5 seria adivinar la convencion de la fuente.
  assert.strictEqual(numeroMedido("12,5"), null);
});

/* ------------------------------------------------------------------
   extremosDeDistancia: de todas las series, no de la primera
   ------------------------------------------------------------------ */
prueba("sin ninguna muestra no hay extremos, y se dice con null", () => {
  assert.strictEqual(extremosDeDistancia([]), null);
  assert.strictEqual(extremosDeDistancia([[], []]), null);
});

prueba("la primera serie vacia no anula a las demas", () => {
  // Era el defecto: `series[0].length` valia 0 y recortaba todo a nada.
  const r = extremosDeDistancia([[], [[10, 1], [90, 2]]]);
  assert.deepStrictEqual(r, [10, 90]);
});

prueba("dos vehiculos con distinta cantidad de muestras no se truncan", () => {
  const a = [[0, 1], [100, 2]];
  const b = [[0, 1], [50, 2], [150, 3], [300, 4]];
  assert.deepStrictEqual(extremosDeDistancia([a, b]), [0, 300]);
  assert.deepStrictEqual(extremosDeDistancia([b, a]), [0, 300]);
});

prueba("una distancia no finita no corre los extremos", () => {
  const r = extremosDeDistancia([[[NaN, 1], [10, 2], [Infinity, 3], [20, 4]]]);
  assert.deepStrictEqual(r, [10, 20]);
});

/* ------------------------------------------------------------------
   recortarPorDominio: metros, no posiciones
   ------------------------------------------------------------------ */
prueba("recorta por el valor del eje", () => {
  const s = [[0, 1], [100, 2], [200, 3], [300, 4]];
  assert.deepStrictEqual(recortarPorDominio(s, 100, 200), [[100, 2], [200, 3]]);
});

prueba("sin dominio pasa todo lo finito", () => {
  const s = [[0, 1], [100, 2]];
  assert.deepStrictEqual(recortarPorDominio(s, null, null), s);
});

prueba("suelta los puntos que no se pueden ubicar", () => {
  const s = [[0, 1], [NaN, 2], [100, NaN], [200, Infinity], [300, 4]];
  assert.deepStrictEqual(recortarPorDominio(s, null, null), [[0, 1], [300, 4]]);
});

prueba("el mismo dominio recorta igual dos señales de distinto largo", () => {
  const densa = [];
  for (let m = 0; m <= 1000; m += 10) densa.push([m, m]);
  const rala = [[0, 0], [500, 5], [1000, 10]];
  const a = recortarPorDominio(densa, 400, 600);
  const b = recortarPorDominio(rala, 400, 600);
  // Lo que importa no es cuantos puntos quedan sino que sean del mismo tramo.
  assert.ok(a.every(p => p[0] >= 400 && p[0] <= 600));
  assert.ok(b.every(p => p[0] >= 400 && p[0] <= 600));
  assert.deepStrictEqual(b, [[500, 5]]);
});

/* ------------------------------------------------------------------
   escalaDe: sin dato no hay escala, y no hay NaN
   ------------------------------------------------------------------ */
prueba("sin muestras devuelve null en vez de NaN", () => {
  // Antes daba mn=Infinity, mx=-Infinity, pad=NaN, y el pie del grafico
  // terminaba escribiendo «NaN» como si fuera una medicion.
  assert.strictEqual(escalaDe([]), null);
  assert.strictEqual(escalaDe([[], []]), null);
});

prueba("ninguna escala contiene NaN ni Infinity", () => {
  const e = escalaDe([[[0, 10], [1, 90]]], 0.1);
  [e.mn, e.mx, e.minReal, e.maxReal].forEach(v => {
    assert.ok(Number.isFinite(v), "valor no finito en la escala: " + v);
  });
});

prueba("declara el minimo y el maximo medidos, no los de la holgura", () => {
  const e = escalaDe([[[0, 10], [1, 90]]], 0.1);
  assert.strictEqual(e.minReal, 10);
  assert.strictEqual(e.maxReal, 90);
  assert.ok(e.mn < 10 && e.mx > 90, "la holgura tiene que abrir el eje");
});

prueba("una señal constante no divide por cero", () => {
  const e = escalaDe([[[0, 5], [1, 5], [2, 5]]], 0.1);
  assert.ok(Number.isFinite(e.mn) && Number.isFinite(e.mx));
  assert.ok(e.mx > e.mn, "un eje de alto cero manda la traza al infinito");
  assert.strictEqual(e.minReal, 5);
});

prueba("un valor no finito no contamina la escala", () => {
  const e = escalaDe([[[0, 10], [1, NaN], [2, 90], [3, Infinity]]], 0.1);
  assert.strictEqual(e.minReal, 10);
  assert.strictEqual(e.maxReal, 90);
});

prueba("una serie vacia junto a una con datos no rompe la escala", () => {
  const e = escalaDe([[], [[0, 10], [1, 20]]], 0.1);
  assert.strictEqual(e.minReal, 10);
  assert.strictEqual(e.maxReal, 20);
});

/* ------------------------------------------------------------------
   dominioAmpliado: un tramo de la vuelta
   ------------------------------------------------------------------ */
prueba("sin ampliar no hay recorte", () => {
  globalThis.ampliado = false;
  assert.deepStrictEqual(dominioAmpliado([0, 1000]), [null, null]);
});

prueba("ampliado recorta el mismo tramo de metros para cualquier señal", () => {
  globalThis.ampliado = true;
  const [a, b] = dominioAmpliado([0, 1000]);
  assert.strictEqual(a, 340);
  assert.strictEqual(b, 580);
  // Y sobre una vuelta que no empieza en cero, el tramo se corre con ella.
  const [c, d] = dominioAmpliado([1000, 2000]);
  assert.strictEqual(c, 1340);
  assert.strictEqual(d, 1580);
  globalThis.ampliado = false;
});

prueba("sin extremos no se inventa un tramo", () => {
  globalThis.ampliado = true;
  assert.deepStrictEqual(dominioAmpliado(null), [null, null]);
  globalThis.ampliado = false;
});

/* ------------------------------------------------------------------
   reducirAAncho: menos puntos que pixeles, sin perder los extremos
   ------------------------------------------------------------------ */
prueba("con pocas muestras no interviene", () => {
  const s = [[0, 1], [10, 2], [20, 3]];
  assert.strictEqual(reducirAAncho(s, 0, 20, 240), s, "toco una serie que ya cabia");
});

prueba("un pico de una sola muestra sobrevive a la reduccion", () => {
  /* Es el caso que el muestreo uniforme borra: 2.000 muestras en 200 pixeles
     son diez por columna, y quedarse con una tira nueve de cada diez. Si el
     pico esta entre las descartadas, desaparece del grafico sin dejar rastro
     ---y es justo lo que una anotacion de bloqueo de rueda señala. */
  const serie = [];
  for (let i = 0; i < 2000; i++) serie.push([i, 10]);
  serie[777] = [777, 999];                     // el pico
  const r = reducirAAncho(serie, 0, 1999, 200);
  const maximo = Math.max.apply(null, r.map(p => p[1]));
  assert.strictEqual(maximo, 999, "el pico se perdio al reducir");
  // Y sigue estando donde estaba, no en cualquier lado.
  const donde = r.find(p => p[1] === 999)[0];
  assert.strictEqual(donde, 777, "el pico se movio de sitio");
});

prueba("un valle de una sola muestra tambien sobrevive", () => {
  const serie = [];
  for (let i = 0; i < 2000; i++) serie.push([i, 100]);
  serie[1234] = [1234, -50];
  const r = reducirAAncho(serie, 0, 1999, 200);
  assert.strictEqual(Math.min.apply(null, r.map(p => p[1])), -50);
});

prueba("la reduccion respeta el ancho pedido", () => {
  const serie = [];
  for (let i = 0; i < 5000; i++) serie.push([i, Math.sin(i)]);
  const r = reducirAAncho(serie, 0, 4999, 240);
  // Como mucho dos puntos por columna: el minimo y el maximo.
  assert.ok(r.length <= 240 * 2, "quedaron " + r.length + " puntos para 240 columnas");
  assert.ok(r.length > 100, "se redujo de mas: " + r.length);
});

prueba("los puntos reducidos salen en orden creciente de distancia", () => {
  const serie = [];
  for (let i = 0; i < 3000; i++) serie.push([i, (i % 17) - 8]);
  const r = reducirAAncho(serie, 0, 2999, 150);
  for (let i = 1; i < r.length; i++) {
    assert.ok(r[i][0] >= r[i - 1][0],
      "el trazo retrocede en el eje: " + r[i - 1][0] + " -> " + r[i][0]);
  }
});

prueba("un dominio de ancho cero no rompe", () => {
  const serie = [];
  for (let i = 0; i < 1000; i++) serie.push([5, i]);
  const r = reducirAAncho(serie, 5, 5, 240);
  assert.ok(Array.isArray(r));
});

if (process.exitCode) {
  console.error("\n" + hechas + " pruebas pasaron; hubo fallos.");
} else {
  console.log(hechas + " pruebas de ayudantes de serie: OK");
}
