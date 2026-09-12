/* De que lado del dibujo va una fuerza lateral, y con que forma se pinta.
 *
 * CRITERIO. Como los demas arneses, las funciones se **extraen del `app.js` que
 * se publica** y se ejecutan; no se copian.
 *
 * EL DEFECTO QUE ESTO CUIDA, Y ESTUVO A LA VISTA TODO EL TIEMPO.
 * `g_force_lateral` de F1 25 declara **negativo a la derecha** ---verificado
 * contra tres curvas cuyo sentido publica una fuente externa, ver
 * `backend/analisis/curvas.py`--- y el diagrama colocaba el punto en
 * `90 + lateral`, o sea positivo a la derecha, debajo de un rotulo que dice
 * «DER». Cada curva a derecha se dibujaba del lado que dice izquierda.
 *
 * Medido sobre la sesion de Spa el 2026-09-12, con 885 y 400 muestras:
 *   La Source, horquilla a DERECHA: lateral medio -1,33 (de -2,36 a -0,05)
 *   Eau Rouge, entrada a IZQUIERDA: lateral medio +0,18 (hasta +1,25)
 *
 * Un dibujo espejado no se nota mirandolo ---es simetrico--- y por eso hace
 * falta una prueba que lo afirme en palabras y no en pixeles.
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

function constante(nombre) {
  const i = fuenteApp.indexOf("const " + nombre + " =");
  if (i === -1) throw new Error("no esta la constante " + nombre);
  return fuenteApp.slice(i, fuenteApp.indexOf(";", i) + 1);
}

const m = new Function(
  constante("CENTRO_DEL_DIAGRAMA_G") + "\n" +
  constante("RADIO_DEL_DIAGRAMA_G") + "\n" +
  constante("APERTURA_DEL_SECTOR_G") + "\n" +
  extraer("puntoDelDiagramaG") + "\n" +
  extraer("sectorDeFuerzaG") + "\n" +
  "return { CENTRO_DEL_DIAGRAMA_G, RADIO_DEL_DIAGRAMA_G, puntoDelDiagramaG, sectorDeFuerzaG };")();

let hechas = 0;
function prueba(titulo, fn) {
  try { fn(); hechas++; }
  catch (e) {
    process.exitCode = 1;
    console.error("FALLA  " + titulo + "\n       " + e.message);
  }
}

const C = () => m.CENTRO_DEL_DIAGRAMA_G;

prueba("una fuerza a la derecha se dibuja a la derecha", () => {
  /* La Source: lateral -1,33 sobre una escala de 2. El signo de la fuente dice
     derecha, y el dibujo tiene que decir lo mismo. */
  const p = m.puntoDelDiagramaG(-1.33, 0, 2);
  assert.ok(p.x > C(), "una curva a derecha se dibujo a la izquierda: x=" + p.x);
});

prueba("una fuerza a la izquierda se dibuja a la izquierda", () => {
  const p = m.puntoDelDiagramaG(1.25, 0, 2);
  assert.ok(p.x < C(), "una curva a izquierda se dibujo a la derecha: x=" + p.x);
});

prueba("frenar va arriba y acelerar abajo", () => {
  /* El eje vertical no estaba mal y se afirma igual: sin esto, arreglar el
     horizontal podria invertir el otro sin que nadie lo note. */
  assert.ok(m.puntoDelDiagramaG(0, 1, 2).y < C(), "frenar no va arriba");
  assert.ok(m.puntoDelDiagramaG(0, -1, 2).y > C(), "acelerar no va abajo");
});

prueba("el centro es la ausencia de fuerza", () => {
  const p = m.puntoDelDiagramaG(0, 0, 2);
  assert.strictEqual(p.x, C());
  assert.strictEqual(p.y, C());
});

prueba("una fuerza mayor que la escala se sujeta al borde, no se sale", () => {
  /* La estela esta diezmada y puede haber perdido el pico: si el instante se
     saliera del recuadro, se dibujaria encima del panel de al lado. */
  const p = m.puntoDelDiagramaG(-9, 0, 2);
  const d = Math.hypot(p.x - C(), p.y - C());
  assert.ok(d <= m.RADIO_DEL_DIAGRAMA_G + 0.01, "el punto se salio: " + d);
});

prueba("sin fuerza no se pinta ningun sector", () => {
  /* Un sector de radio cero sigue siendo una figura, y dibujada queda una mancha
     en el centro que se lee como una fuerza que no existe. */
  assert.strictEqual(m.sectorDeFuerzaG(0, 0, 2), null);
  assert.strictEqual(m.sectorDeFuerzaG(null, 1, 2), null);
});

const radioDelArco = d =>
  Math.max(...[...d.matchAll(/A\s*([\d.]+)/g)].map(x => Number(x[1])));

prueba("el bloque se aleja del centro a medida que crece la fuerza", () => {
  /* Es la lectura entera del indicador: hacia donde esta el bloque es de donde
     empuja, y cuan lejos del centro esta es cuanta. Con el radio fijo seria una
     brujula; con el angulo fijo, un medidor mas. */
  const chico = m.sectorDeFuerzaG(-0.5, 0, 2);
  const grande = m.sectorDeFuerzaG(-2, 0, 2);
  assert.ok(chico && grande, "no se pinto el bloque");
  assert.ok(radioDelArco(grande) > radioDelArco(chico),
    "el bloque no se aleja con la fuerza: " + radioDelArco(chico) +
    " contra " + radioDelArco(grande));
});

prueba("con la fuerza al tope el bloque llega al anillo de afuera", () => {
  /* El anillo de afuera es el borde de la escala, y la escala sale del maximo de
     la vuelta: el pico tiene que tocarlo. Si se quedara corto, el dibujo diria
     que sobro margen donde no sobro. */
  const tope = m.sectorDeFuerzaG(-2, 0, 2);
  assert.ok(Math.abs(radioDelArco(tope) - m.RADIO_DEL_DIAGRAMA_G) < 0.01,
    "el pico no llega al borde: " + radioDelArco(tope));
});

prueba("el bloque esta del lado que corresponde", () => {
  /* La misma afirmacion que la del punto, sobre la figura que ahora se mira: una
     fuerza a derecha pone el bloque a la derecha del centro. */
  /* El camino es `M x1 y1 A r r 0 0 1 x2 y2`: los dos extremos son los dos
     primeros numeros y los dos ultimos. Sacarlos con un patron de «dos numeros
     seguidos» agarraba tambien el `r r` del arco y la prueba fallaba con un
     radio disfrazado de coordenada. */
  const aDerecha = m.sectorDeFuerzaG(-1.5, 0, 2);
  const n = aDerecha.match(/[\d.]+/g).map(Number);
  const equis = [n[0], n[n.length - 2]];
  assert.ok(equis.every(v => v > m.CENTRO_DEL_DIAGRAMA_G),
    "el bloque de una fuerza a derecha quedo a la izquierda: " + JSON.stringify(equis));
});

if (process.exitCode) {
  console.error("\n" + hechas + " pruebas pasaron; hubo fallos.");
} else {
  console.log(hechas + " pruebas de de que lado empuja: OK");
}
