/* Donde se dibuja el coche: en el instante en que se lo midio.
 *
 * CRITERIO. Como los demas arneses, las funciones se **extraen del `app.js` que
 * se publica** y se ejecutan; no se copian.
 *
 * EL DEFECTO QUE ESTO CUIDA. La API entrega una distancia por intervalo, y el
 * tablero las repartia en partes iguales dentro de la vuelta. No lo estan: cada
 * una es la primera muestra de su intervalo y cae donde cae. Medido sobre Spa,
 * vueltas 3 a 21: suponer la rejilla pareja corre cada punto 24,9 ms de mediana
 * y hasta 66,6 ms, que a 55,3 m/s son 1,4 y 3,7 m de pista. Y el corrimiento no
 * es constante ---cambia de un punto al siguiente---, que es como se ve el
 * tiron.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");

const APP = path.join(__dirname, "..", "..", "dashboard", "app.js");
const fuente = fs.readFileSync(APP, "utf8");

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

/* El estado del modulo que estas funciones leen, puesto en el ambito global:
   es lo que ve un cuerpo construido con `new Function`. */
globalThis.estado = { posiciones: {} };
globalThis.PISTA = { largo_m: 7000 };
globalThis._huboInterpolacion = false;
globalThis.instante = () => ({ vuelta: 1, fraccion: 0 });

const NOMBRES = ["numeroMedido", "paresDePosicion", "posicionesAhora"];
const sacadas = new Function(NOMBRES.map(extraer).join("\n\n") +
                             "\nreturn { " + NOMBRES.join(", ") + " };")();
const posicionesAhora = sacadas.posicionesAhora;
const paresDePosicion = sacadas.paresDePosicion;

let hechas = 0;
function prueba(titulo, fn) {
  try {
    fn();
    hechas++;
  } catch (e) {
    process.exitCode = 1;
    console.error("FALLA  " + titulo + "\n       " + (e && e.message));
  }
}

/* Arma una respuesta de `/posiciones` como la que devuelve la API. */
function respuesta(distancias, instantes, puntos) {
  const n = puntos === undefined ? distancias.length - 1 : puntos;
  const d = {
    vuelta: 1,
    puntos: n,
    intervalo_ms: 1000,
    vehiculos: { "car:0": distancias },
  };
  if (instantes) d.instantes_ms = { "car:0": instantes };
  return d;
}

function en(fraccion, d) {
  globalThis.estado.posiciones[1] = d;
  globalThis.instante = () => ({ vuelta: 1, fraccion: fraccion });
  const r = posicionesAhora();
  return r ? r["car:0"] : undefined;
}

// ------------------------------------------------ colocar por tiempo real

prueba("con muestras parejas cae donde caia antes", () => {
  /* La correccion no puede mover lo que ya estaba bien. */
  const d = respuesta([0, 50, 100], [0, 1000, 2000], 2);
  assert.strictEqual(en(0.25, d), 25);
  assert.strictEqual(en(0.5, d), 50);
});

prueba("con muestras desparejas usa el instante medido, no la rejilla", () => {
  /* La segunda muestra se tomo a los 100 ms, no a los 1.000. Repartiendo en
     partes iguales, a mitad de vuelta daria 50; midiendo, a los 100 ms ya
     recorrio los 50 y de ahi sigue el tramo largo. */
  const d = respuesta([0, 50, 100], [0, 100, 2000], 2);
  assert.strictEqual(en(0.05, d), 50, "no respeta el instante de la segunda muestra");
  const aMitad = en(0.5, d);
  assert.ok(aMitad > 50 && aMitad < 75,
    "a mitad de vuelta deberia estar poco despues de la segunda muestra, no en 50: " + aMitad);
});

prueba("antes de la primera muestra se queda en la primera", () => {
  const d = respuesta([10, 50], [500, 1500], 1);
  assert.strictEqual(en(0, d), 10);
});

prueba("en el ultimo instante devuelve la ultima medida", () => {
  const d = respuesta([0, 50, 100], [0, 1000, 2000], 2);
  assert.strictEqual(en(1, d), 100);
});

// ------------------------------------------------ huecos

prueba("un hueco es solo dos muestras mas separadas", () => {
  /* Antes el intervalo vacio era un caso especial que buscaba hacia atras. Con
     los instantes, la muestra siguiente esta donde dice su marca y se
     interpola normalmente. */
  const d = respuesta([0, null, 100], [0, null, 2000], 2);
  assert.strictEqual(en(0.5, d), 50);
});

prueba("un hueco al final deja la marca en la ultima medida", () => {
  const d = respuesta([0, 40, null], [0, 1000, null], 2);
  assert.strictEqual(en(1, d), 40);
});

prueba("una vuelta sin ninguna medida no devuelve nada para ese vehiculo", () => {
  const d = respuesta([null, null], [null, null], 1);
  assert.strictEqual(en(0.5, d), undefined);
});

// ------------------------------------------------ el cierre de vuelta

prueba("no se interpola sobre el cierre de vuelta", () => {
  /* Vuelta 22 de Spa: `... 6.978,0 · 2,1`. La distancia de vuelta se reinicia
     porque el coche cruzo la meta. Interpolar entre esos dos haria retroceder
     el coche siete kilometros en pantalla. */
  const d = respuesta([6900, 6978, 2.1], [0, 1000, 2000], 2);
  assert.strictEqual(en(0.75, d), 6978,
    "el coche retrocede sobre el cruce de meta");
});

prueba("tampoco se fuerza que la distancia crezca", () => {
  /* No se recorta el descenso ni se lo reemplaza: la marca se queda quieta
     hasta que haya una muestra contigua. Esconderlo haria que un descenso que
     **si** es un error se viera igual de prolijo. */
  const d = respuesta([6900, 6978, 2.1], [0, 1000, 2000], 2);
  assert.strictEqual(en(0.99, d), 6978);
});

prueba("el tope se mide contra el tiempo que paso, no contra un intervalo supuesto", () => {
  /* Dos muestras separadas 40 ms no pueden estar a 300 m una de otra a ritmo
     de carrera; separadas 4 s, si. Con el tope viejo ---largo/n por tres--- las
     dos daban lo mismo. */
  /* Una vuelta de Spa de verdad: 7.000 m en 127 s, unos 55 m/s de media. */
  const vuelta = d => Object.assign(d, { intervalo_ms: 635, puntos: 200 });
  const cerca = vuelta(respuesta([0, 300], [0, 40], 200));
  assert.strictEqual(en(39 / 127000, cerca), 0,
    "acepto 300 m en 40 ms, que a ritmo de carrera son 2,2");
  const lejos = vuelta(respuesta([0, 300], [0, 8000], 200));
  assert.strictEqual(en(4000 / 127000, lejos), 150,
    "rechazo 300 m en 8 s, que a ritmo de carrera son 441");
});

// ------------------------------------------------ compatibilidad

prueba("sin instantes se cae en la rejilla pareja y se declara", () => {
  /* Una API mas vieja no los manda. Se sigue dibujando, pero el arreglo queda
     marcado como aproximado para no presentar una suposicion como medicion. */
  const d = respuesta([0, 50, 100], null, 2);
  assert.strictEqual(en(0.5, d), 50);
  assert.strictEqual(paresDePosicion(d, "car:0").aproximado, true);
});

prueba("con instantes no se declara aproximado", () => {
  const d = respuesta([0, 50, 100], [0, 1000, 2000], 2);
  assert.strictEqual(paresDePosicion(d, "car:0").aproximado, false);
});

prueba("los pares se arman una sola vez por respuesta", () => {
  const d = respuesta([0, 50, 100], [0, 1000, 2000], 2);
  const a = paresDePosicion(d, "car:0");
  const b = paresDePosicion(d, "car:0");
  assert.strictEqual(a, b, "se rearman en cada cuadro");
});

// ------------------------------------------------ lo que se lee del archivo

prueba("el marcador no se redondea a un escalon mas grande que un cuadro", () => {
  /* Medido sobre el trazado de Spa: el dibujo se escala a 0,0976 unidades por
     metro, asi que una decima de unidad son 1,02 m de pista, y a 55,3 m/s el
     coche recorre 0,92 m en un cuadro de 16,7 ms. Con `toFixed(1)` la marca
     avanzaba cero o un escalon por cuadro. */
  const i = fuente.indexOf("const px = p.x.toFixed(");
  assert.ok(i > 0, "no esta el redondeo del marcador");
  assert.ok(fuente.slice(i, i + 60).indexOf("toFixed(2)") !== -1,
    "el marcador volvio a redondearse a una decima de unidad");
});

prueba("una posicion estimada por tiempo se declara como tal", () => {
  /* Un coche no recorre el circuito a ritmo parejo: la fraccion temporal de la
     vuelta no es la fraccion recorrida, y usarla sin decirlo presenta una
     suposicion como una medicion. */
  const i = fuente.indexOf("const medida = enPistaAhora && enPistaAhora[clave] !== undefined;");
  assert.ok(i > 0, "no se distingue una posicion medida de una estimada");
  const bloque = fuente.slice(i, i + 400);
  assert.ok(bloque.indexOf("dataset.estimada") !== -1,
    "la marca no declara cuando su posicion es estimada");
});

if (process.exitCode) {
  console.error("\n" + hechas + " pruebas pasaron; hubo fallos.");
} else {
  console.log(hechas + " pruebas de posicion en el tiempo: OK");
}
