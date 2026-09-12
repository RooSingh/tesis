/* Cuando dos posiciones seguidas no describen un camino recorrido.
 *
 * CRITERIO. Como los demas arneses, las funciones se **extraen del `app.js` que
 * se publica** y se ejecutan; no se copian.
 *
 * QUE PASO. En una contrarreloj de Shanghai, al empezar la vuelta lanzada el
 * simulador **teletransporta el coche** a la linea. El recorrido en vivo se
 * acumula como una sola polilinea, de modo que se dibujo un segmento recto
 * cruzando el circuito entre el sitio donde estaba y el sitio donde aparecio.
 * El tablero afirmaba un camino que nadie recorrio.
 *
 * LA REGLA NO ES DEL MODO, ES DEL VEHICULO. Un salto tambien ocurre con un
 * `flashback` o con un reinicio en boxes, y en cualquier modo. Lo que separa un
 * salto de un movimiento es que **el vehiculo publica su propia velocidad**, y
 * con ella dice cuanto pudo haberse movido en el tiempo que paso.
 *
 * MEDIDO sobre `f1_25:session:16227589096132074312` el 2026-09-12, 4.592
 * muestras a 10 Hz:
 *
 *   - el salto: **479,3 m en 0,094 s**, con el coche declarando **0,0 km/h**
 *     antes y 332,0 despues. El maximo posible con la velocidad previa era
 *     **0,00 m**;
 *   - los otros 4.590: mediana 4,96 m, percentil 99 9,13 m, **maximo 10,72 m**.
 *
 * Y la cota es exacta, que es lo que hace creible la regla: ese maximo de
 * 10,72 m ocurrio en 0,117 s a 330 km/h, y 330 km/h durante 0,117 s son
 * **10,73 m**. El movimiento real roza su cota; el salto la supera treinta y
 * cuatro veces.
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
  const m = new RegExp("const " + nombre + " = ([\\d.]+);").exec(fuenteApp);
  if (!m) throw new Error("no esta " + nombre + " en app.js");
  return m[0];
}

const pudoRecorrer = new Function(`
  ${constante("MARGEN_DE_MOVIMIENTO")}
  ${constante("PISO_DE_MOVIMIENTO_M")}
  ${extraer("pudoRecorrer")}
  return pudoRecorrer;
`)();

const trazadoAPath = new Function(`
  ${extraer("trazadoAPath")}
  return trazadoAPath;
`)();

let hechas = 0;
function prueba(nombre, fn) { fn(); hechas++; }

prueba("el salto medido se rechaza", () => {
  assert.strictEqual(pudoRecorrer(479.3, 0.094, 0.0, 332.0), false,
    "479 m en 94 ms con el coche declarando 0 km/h se acepta como movimiento");
});

prueba("el mayor movimiento real se acepta, y roza su cota", () => {
  assert.strictEqual(pudoRecorrer(10.72, 0.117, 330.0, 330.0), true,
    "se rechaza un movimiento que ocurrio de verdad: la regla es demasiado " +
    "estricta y va a cortar el trazado en pedazos");
});

prueba("los saltos tipicos se aceptan", () => {
  for (const s of [4.96, 9.13, 9.2, 10.7]) {
    assert.strictEqual(pudoRecorrer(s, 0.100, 330.0, 330.0), true, "salto " + s);
  }
});

prueba("arrancar desde detenido no se confunde con un salto", () => {
  /* Al soltar el freno la velocidad previa es cero y el coche igual se mueve
     unos centimetros. Sin un piso, cada arranque cortaria el trazado. */
  assert.strictEqual(pudoRecorrer(0.4, 0.100, 0.0, 15.0), true);
});

prueba("un coche detenido que tiembla no corta el trazado", () => {
  /* EL CASO QUE EJERCE EL PISO, y que faltaba. La prueba de arriba pasaba con
     el piso quitado ---15 km/h ya permiten 0,6 m--- asi que la mutacion que
     lo borraba no mataba nada. Con las dos velocidades en cero, lo unico que
     permite un movimiento es el piso: un coche parado publica posiciones que
     difieren por centesimas, y sin piso cada una seria un salto. */
  assert.strictEqual(pudoRecorrer(0.3, 0.100, 0.0, 0.0), true);
  assert.strictEqual(pudoRecorrer(0.9, 0.100, 0.0, 0.0), true);
  // Pero el piso es un piso, no una licencia: dos metros parado no pasan.
  assert.strictEqual(pudoRecorrer(2.0, 0.100, 0.0, 0.0), false);
});

prueba("sin velocidad declarada no se corta", () => {
  /* No poder decidir no es lo mismo que haber decidido que fue un salto.
     Cortar ante la duda desarmaria el trazado de cualquier fuente que no
     publique velocidad. */
  assert.strictEqual(pudoRecorrer(500.0, 0.1, null, null), true);
  assert.strictEqual(pudoRecorrer(500.0, 0.1, undefined, undefined), true);
});

prueba("sin tiempo entre muestras tampoco se decide", () => {
  assert.strictEqual(pudoRecorrer(500.0, 0, 0, 0), true);
  assert.strictEqual(pudoRecorrer(500.0, -1, 0, 0), true);
});

prueba("la velocidad que manda es la mayor de las dos", () => {
  /* En el salto medido la velocidad previa era 0 y la siguiente 332 km/h.
     Tomar solo la previa daria cero y cortaria tambien cada arranque; tomar la
     mayor es lo prudente y aun asi rechaza el salto por treinta y cuatro
     veces. */
  assert.strictEqual(pudoRecorrer(8.0, 0.1, 0.0, 330.0), true);
  assert.strictEqual(pudoRecorrer(479.3, 0.094, 0.0, 332.0), false);
});

prueba("un camino sin cortes sigue siendo una sola figura", () => {
  const p = [[0, 0], [10, 0], [10, 10], [0, 10]];
  const d = trazadoAPath(p, false, false).path;
  assert.strictEqual((d.match(/M/g) || []).length, 1,
    "aparecio un corte donde no hay salto: " + d);
});

prueba("un punto marcado como corte abre una figura nueva", () => {
  /* El corte se marca en el punto, no se borra el punto: la posicion se midio
     y sigue siendo cierta. Lo que deja de afirmarse es el camino entre ella y
     la anterior. */
  const p = [[0, 0], [10, 0], [10, 10, true], [0, 10]];
  const d = trazadoAPath(p, false, false).path;
  assert.strictEqual((d.match(/M/g) || []).length, 2,
    "el corte no abrio una figura nueva: " + d);
  assert.strictEqual((d.match(/[ML]/g) || []).length, 4,
    "se perdio o se duplico un punto: " + d);
});

prueba("el punto del corte no se borra del dibujo", () => {
  const conCorte = trazadoAPath([[0, 0], [10, 0], [10, 10, true], [0, 10]],
                                false, false).path;
  const sinCorte = trazadoAPath([[0, 0], [10, 0], [10, 10], [0, 10]],
                                false, false).path;
  assert.strictEqual(conCorte.replace(/M/g, "L"), sinCorte.replace(/M/g, "L"),
    "el corte movio o perdio coordenadas; solo debe cambiar M por L");
});

/* -------- el mismo salto, pero en una sesion guardada -------- */

const marcarSaltos = new Function(`
  ${constante("MARGEN_DE_MOVIMIENTO")}
  ${constante("PISO_DE_MOVIMIENTO_M")}
  ${extraer("pudoRecorrer")}
  ${extraer("marcarSaltos")}
  return marcarSaltos;
`)();

prueba("EL CASO QUE FALTABA: la sesion guardada traia el salto igual", () => {
  /* El primer arreglo cubrio solo el camino **en vivo**, donde el tablero
     acumula las posiciones. Una sesion guardada dibuja lo que devuelve
     `/trazado`, y ahi el salto seguia. Medido el 2026-09-12 sobre
     `f1_25:session:16227589096132074312`: **476 m entre los puntos 11 y 12**,
     con una mediana de 12 m. Se reproduce la forma de esa respuesta. */
  const puntos = [[0, 0], [12, 0], [24, 0], [500, 0], [512, 0]];
  const dt = [null, 0.5, 0.5, 0.5, 0.5];
  const kmh = [300, 300, 0, 332, 330];
  const marcados = marcarSaltos(puntos, dt, kmh);
  assert.strictEqual(marcados[3][2], true,
    "el salto de 476 m no quedo marcado");
  assert.ok(!marcados[1][2] && !marcados[2][2] && !marcados[4][2],
    "se marco un tramo que si se recorrio");
});

prueba("sin los datos del paso no se marca nada", () => {
  /* Una fuente que no publique velocidad, o una respuesta vieja sin estos
     campos, tiene que seguir dibujando su trazado entero. */
  const puntos = [[0, 0], [500, 0]];
  assert.ok(!marcarSaltos(puntos, null, null)[1][2]);
  assert.ok(!marcarSaltos(puntos, [null, null], [null, null])[1][2]);
});

prueba("los arreglos desalineados no corrompen el dibujo", () => {
  /* Si llegaran con largos distintos, marcar por indice desplazaria el corte a
     otro tramo: un defecto peor que el que se esta arreglando, porque partiria
     el circuito en un sitio donde el coche si paso.

     EL CASO TIENE QUE LLEGAR A MARCAR. La primera version usaba arreglos
     cortos, y ahi el indice sobrante da `undefined`, `pudoRecorrer` no puede
     decidir y no marca igual: la guarda se podia borrar sin que ninguna prueba
     se quejara. Aca el desalineado **si** produciria un corte. */
  const puntos = [[0, 0], [500, 0], [512, 0]];
  const salida = marcarSaltos(puntos, [null, 0.1, 0.1, 0.1], [0, 0, 0]);
  assert.deepStrictEqual(salida.map(p => !!p[2]), [false, false, false],
    "se marco con los arreglos desalineados");
});

prueba("el constructor del trazado guardado la usa", () => {
  /* Se comprueba sobre el `app.js` publicado. La funcion podia existir, estar
     probada y no llamarla nadie: quitarla de `armarPista` no mataba ninguna
     prueba, que es como quedan los arreglos a medias. */
  const i = fuenteApp.indexOf("function armarPista(");
  assert.notStrictEqual(i, -1, "no esta armarPista");
  const cuerpo = fuenteApp.slice(i, i + 800);
  assert.ok(/marcarSaltos\(/.test(cuerpo),
    "armarPista no marca los saltos: la sesion guardada vuelve a dibujarlos");
});

prueba("no se modifica el arreglo que llego", () => {
  const puntos = [[0, 0], [500, 0]];
  marcarSaltos(puntos, [null, 0.1], [0, 0]);
  assert.strictEqual(puntos[1].length, 2,
    "se escribio sobre los puntos originales, que son el dato medido");
});

console.log("ok " + hechas + " pruebas de saltos y cortes");
