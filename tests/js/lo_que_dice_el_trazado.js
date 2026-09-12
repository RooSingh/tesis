/* Que declara el encabezado del panel de trazado, y con que lo decide.
 *
 * CRITERIO. Como los demas arneses, la funcion se **extrae del `app.js` que se
 * publica** y se ejecuta; no se copia.
 *
 * POR QUE ESTE ARNES EXISTE. El encabezado decidia con `if (PISTA.largo_m)`:
 * preguntaba «¿se cuantos metros mide?» y, si no lo sabia, respondia «sin
 * trazado» ---con el circuito dibujado debajo---. Se vio el 2026-09-11 sobre
 * `openf1:session:9947`, pidiendo el trazado como lo pide el tablero ---con la
 * clave del vehiculo, `openf1:session:9947:driver:1`---: vuelta 21, 641
 * muestras, 321 puntos y `largo_m: null`. No es un descuido de esa vuelta: esa
 * fuente guarda nueve señales y `lap_distance` no es una de ellas, asi que el
 * largo **nunca** se puede calcular ahi.
 *
 * LA PRIMERA CIFRA QUE ANOTE ERA OTRA, Y POR ESO QUEDA ESCRITO. Sin la clave
 * del vehiculo la misma ruta devuelve 35.255 muestras, y anote esa. No filtra
 * a nadie: son los tres pilotos mezclados a lo largo de la sesion entera,
 * porque OpenF1 no publica nada equivalente a `player_car_index` y sin que se
 * lo digan el punto de acceso no sabe de cual dibujar ---lo advierte el
 * comentario de `_vehiculo_propio`---. La cifra existia y describia una
 * consulta degenerada.
 *
 * Y el propio `app.js` ya tenia la distincion escrita, en el comentario de
 * `COORDENADAS_POR_FUENTE`: una fuente puede no tener metro medido y si tener
 * posicion, `/trazado` sale de la posicion, y decidirlo por el eje de distancia
 * le quitaria el trazado a OpenF1, que lo tiene. El encabezado hacia justamente
 * eso.
 *
 * QUE SE COMPRUEBA.
 *
 * - que un trazado dibujado nunca se anuncie como ausente, tenga largo o no;
 * - que la falta de largo se **declare** cuando la fuente no publica distancia,
 *   en vez de callarse o de negar el dibujo;
 * - que no se declare cuando la fuente si publica distancia: ahi el largo falta
 *   por esta vuelta, y afirmar lo otro seria concluir sobre la fuente desde un
 *   solo trazado;
 * - que sin dibujo se siga distinguiendo «todavia se esta midiendo» de «no hay».
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

const queDiceElTrazado = new Function(`
  ${extraer("cifra")}
  ${extraer("queDiceElTrazado")}
  return queDiceElTrazado;
`)();

/* Lo que devuelve `/trazado` para esa sesion de OpenF1, con los numeros
   medidos el 2026-09-11 ---un piloto, una vuelta--- y no inventados. */
const OPENF1 = { path: "M0,0 L1,1", largo_m: null, desnivel_m: null, muestras: 641 };
/* Y lo que devuelve para la sesion del simulador, misma fecha. */
const F1_25 = { path: "M0,0 L1,1", largo_m: 7007.2, desnivel_m: 102.3, muestras: 6435 };

const sinDistancia = { hayDistancia: false, estadoSesion: "grabada", fuente: "openf1" };
const conDistancia = { hayDistancia: true, estadoSesion: "grabada", fuente: "f1" };

let hechas = 0;
function prueba(nombre, fn) { fn(); hechas++; }

prueba("un trazado dibujado sin largo no se anuncia como ausente", () => {
  const dice = queDiceElTrazado(OPENF1, sinDistancia);
  assert.ok(!/sin trazado/i.test(dice),
    "dice «sin trazado» con el circuito dibujado: " + dice);
});

prueba("y dice cuantas muestras hay detras del dibujo", () => {
  assert.ok(/641 muestras/.test(queDiceElTrazado(OPENF1, sinDistancia)),
    "no declara las muestras que si midio");
});

prueba("la falta de metro medido se declara, no se calla", () => {
  assert.ok(/sin metro medido/i.test(queDiceElTrazado(OPENF1, sinDistancia)),
    "omite en silencio que no hay largo");
});

prueba("con largo medido se dice el largo y no se declara ausencia", () => {
  const dice = queDiceElTrazado(F1_25, conDistancia);
  assert.ok(/7\.007 m/.test(dice), "no dice el largo medido: " + dice);
  assert.ok(/102,3 m de desnivel/.test(dice), "no dice el desnivel: " + dice);
  assert.ok(!/sin metro medido/i.test(dice), "declara una ausencia que no existe");
});

prueba("si la fuente publica distancia, un trazado sin largo no acusa a la fuente", () => {
  /* La vuelta elegida puede no traer distancia por su propio motivo. Decir
     «sin metro medido» ahi seria concluir sobre la fuente desde un trazado. */
  const dice = queDiceElTrazado({ ...F1_25, largo_m: null }, conDistancia);
  assert.ok(!/sin metro medido/i.test(dice), "concluye sobre la fuente: " + dice);
  assert.ok(!/sin trazado/i.test(dice), "niega el dibujo: " + dice);
});

prueba("en vivo y sin dibujo todavia, se dice que se esta midiendo", () => {
  assert.ok(/midiendo el recorrido: 12 posiciones/.test(
    queDiceElTrazado({ path: "" },
      { hayDistancia: false, estadoSesion: "vivo", fuente: "openf1", posiciones: 12 })),
    "no distingue «se esta midiendo» de «no hay»");
  assert.ok(/esperando la primera posición/.test(
    queDiceElTrazado({ path: "" },
      { hayDistancia: false, estadoSesion: "vivo", fuente: "openf1", posiciones: 0 })));
});

prueba("sin dibujo y sin sesion en vivo, recien ahi no hay trazado", () => {
  assert.strictEqual(queDiceElTrazado({ path: "" }, sinDistancia), "sin trazado");
  assert.strictEqual(
    queDiceElTrazado({ path: "" },
      { hayDistancia: false, estadoSesion: "grabada", fuente: "can" }),
    "recorrido reconstruido");
});

prueba("un trazado ausente del todo no revienta", () => {
  assert.strictEqual(queDiceElTrazado(null, sinDistancia), "sin trazado");
  assert.strictEqual(queDiceElTrazado(undefined, sinDistancia), "sin trazado");
});

prueba("la procedencia del dibujo se sigue declarando", () => {
  assert.ok(/recorrido en construcción/.test(
    queDiceElTrazado({ ...OPENF1, enConstruccion: true }, sinDistancia)));
  assert.ok(/primera vuelta cerrada/.test(
    queDiceElTrazado({ ...OPENF1, medidoEnVivo: true }, sinDistancia)));
  assert.ok(/derivada por integración/.test(
    queDiceElTrazado({ ...OPENF1, derivado: true }, sinDistancia)));
  assert.ok(/interpolada entre muestras/.test(
    queDiceElTrazado(OPENF1, { ...sinDistancia, interpolada: true })));
});

/* UN SOLO CONSTRUCTOR DE `PISTA`, COMPROBADO Y NO PROMETIDO.
   `armarPista` se extrajo porque habia dos copias y la que ganaba no traia los
   sectores. Quedaron **tres** sitios: dos llamaban a la funcion y `pedirTrazado`
   seguia armando el objeto a mano, con el comentario de `armarPista` afirmando
   que ya no quedaba ninguno. Un comentario no sostiene una invariante; esto si.
   Los campos coincidian uno a uno cuando se encontro, asi que nunca llego a
   divergir ---pero es la misma posicion desde la que ya se rompio---. */
prueba("solo `armarPista` construye el objeto del trazado", () => {
  assert.ok(/function armarPista\(/.test(fuenteApp), "falta armarPista en app.js");
  /* Se busca el armado **desde la respuesta de la API**, no el reinicio a
     vacio: `muestras_originales` es un campo que solo trae esa respuesta. Se
     saca antes el cuerpo de `armarPista`, que es el unico que puede leerlo. */
  const sinLaFuncion = fuenteApp.replace(extraer("armarPista"), "");
  const constructores =
    sinLaFuncion.match(/PISTA\s*=\s*\{[\s\S]{0,2000}?muestras_originales/g) || [];
  assert.strictEqual(constructores.length, 0,
    "hay " + constructores.length + " sitio(s) armando PISTA desde la respuesta " +
    "de la API en vez de llamar a armarPista(); es el defecto de dos escritores " +
    "que este tablero ya tuvo tres veces");
});

console.log("ok " + hechas + " pruebas de lo que dice el trazado");
