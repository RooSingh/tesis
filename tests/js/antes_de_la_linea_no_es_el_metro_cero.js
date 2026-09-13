/* Donde esta el coche cuando todavia no cruzo la linea de largada.
 *
 * CRITERIO. La funcion se **extrae del `app.js` que se publica** y se ejecuta.
 *
 * QUE PASABA. En la reproduccion, los primeros segundos de la vuelta 1 el coche
 * no se movia: quedaba clavado en la linea de meta.
 *
 * POR QUE. El protocolo publica `lap_distance` **negativa antes de cruzar la
 * linea** ---`backend/f1_udp.py:462`---. La colocacion preguntaba
 * `enPistaAhora[clave] !== undefined`, que un negativo cumple, y despues
 * recortaba con `Math.max(0, metro / largo)`: **fraccion cero constante** hasta
 * que el metro se volvia positivo.
 *
 * Y LO PEOR NO ERA QUE NO SE MOVIERA. El coche quedaba marcado como
 * `seUbicoMidiendo`, sin `data-estimada`, de modo que el tablero **afirmaba una
 * posicion medida que en realidad era un recorte**. El comentario que esta
 * justo encima de ese codigo declara la regla que el codigo rompia: «una
 * posicion supuesta y una medida no pueden verse igual».
 *
 * Medido sobre `f1_25:session:16227589096132074312` el 2026-09-12: la sesion
 * arranca en el metro **-5.342,3** y el salto de la vuelta lanzada la deja en
 * **-911,1**. Son miles de metros de sesion antes de la linea.
 *
 * UN METRO NEGATIVO NO ES UN DATO FALTANTE. La fuente esta diciendo donde esta
 * el coche: **antes de la linea**. Lo que no puede hacer es ubicarlo dentro de
 * la vuelta, porque la vuelta todavia no empezo. Por eso esta funcion devuelve
 * `null` ---no hay fraccion--- y no cero, que seria una posicion inventada.
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

const fraccionDelMetro = new Function(
  `${extraer("fraccionDelMetro")} return fraccionDelMetro;`)();

let hechas = 0;
function prueba(nombre, fn) { fn(); hechas++; }

prueba("EL DEFECTO: un metro negativo no ubica en la vuelta", () => {
  assert.strictEqual(fraccionDelMetro(-5342.3, 5441), null,
    "un metro de antes de la linea se convirtio en una posicion de la vuelta");
  assert.strictEqual(fraccionDelMetro(-911.1, 5441), null);
  assert.strictEqual(fraccionDelMetro(-0.1, 5441), null);
});

prueba("y no se lo confunde con el metro cero", () => {
  /* La diferencia entera del defecto: cero es un sitio del circuito ---la
     linea--- y negativo es «todavia no llego». Devolver cero para los dos hace
     que el coche se plante en la meta y que ademas se lo declare medido. */
  assert.strictEqual(fraccionDelMetro(0, 5441), 0);
  assert.notStrictEqual(fraccionDelMetro(-1, 5441), 0);
});

prueba("un metro de la vuelta da su fraccion", () => {
  assert.strictEqual(fraccionDelMetro(2720.5, 5441), 0.5);
  assert.strictEqual(fraccionDelMetro(5441, 5441), 1);
});

prueba("pasarse de largo si se recorta, porque ahi el coche esta", () => {
  /* El extremo de arriba si se recorta: una muestra unos metros pasada la
     linea sigue ubicando al coche sobre el circuito. El de abajo no, porque
     antes de la linea no hay circuito que recorrer todavia. Los dos extremos
     no son simetricos y por eso se tratan distinto. */
  assert.strictEqual(fraccionDelMetro(5450, 5441), 1);
});

prueba("sin metro no se inventa una fraccion", () => {
  assert.strictEqual(fraccionDelMetro(undefined, 5441), null);
  assert.strictEqual(fraccionDelMetro(null, 5441), null);
  assert.strictEqual(fraccionDelMetro(NaN, 5441), null);
  assert.strictEqual(fraccionDelMetro("1200", 5441), null);
});

prueba("sin largo de vuelta tampoco", () => {
  /* Dividir por cero da infinito y el recorte lo convierte en 1: el coche
     aparecería en la meta con aire de medido. */
  assert.strictEqual(fraccionDelMetro(1200, 0), null);
  assert.strictEqual(fraccionDelMetro(1200, null), null);
});

prueba("la colocacion consulta esta funcion y no recorta por su cuenta", () => {
  /* Se comprueba sobre el `app.js` publicado: el recorte viejo
     ---`Math.max(0, Math.min(1, ... / largoVuelta))`--- es justo lo que
     convertia un negativo en cero, y si sobrevive al lado el defecto vuelve. */
  /* Se ancla en `let medidaDeVerdad`, que es marca propia de la colocacion y
     no la linea que este arreglo cambia: anclar en lo que uno modifica hace
     que la prueba deje de encontrar su objeto en cuanto el arreglo entra. */
  const i = fuenteApp.indexOf("let medidaDeVerdad = false;");
  assert.notStrictEqual(i, -1, "no esta la colocacion del coche");
  const bloque = fuenteApp.slice(Math.max(0, i - 400), i + 400);
  assert.ok(/fraccionDelMetro\(/.test(bloque),
    "la colocacion no consulta fraccionDelMetro");
  assert.ok(!/Math\.max\(0, Math\.min\(1, enPistaAhora/.test(bloque),
    "sigue el recorte que convertia un negativo en cero");
});

/* -------- y de donde sale la posicion cuando el metro no ubica -------- */

prueba("EL SIMULADOR TAMBIEN PIDE SU POSICION MEDIDA", () => {
  /* LO QUE FALTABA, Y SE VIO REPRODUCIENDO. Con el metro devolviendo `null`
     antes de la linea, la colocacion cae en `puntoMedidoDe`, que necesita las
     series `posX`/`posY`. Esas dos estaban declaradas **solo para OpenF1**, de
     modo que en el simulador nunca se piden y `puntoMedidoDe` no puede
     funcionar jamas: el coche terminaba repartido por **tiempo** sobre el
     contorno dibujado, y por eso parecia recorrer tramos por los que no paso.

     La posicion esta medida ---`world_position_x` y `world_position_z` son las
     mismas dos señales con las que el backend arma el trazado--- y lo unico
     que faltaba era pedirla. Se comprueba sobre el `app.js` publicado porque
     es una declaracion, no una rama de codigo: una prueba de comportamiento no
     la alcanza. */
  const i = fuenteApp.indexOf('{ id: "posX"');
  assert.notStrictEqual(i, -1, "no esta la declaracion de posX");
  const bloque = fuenteApp.slice(i, i + 200);
  assert.ok(/"f1"/.test(bloque),
    "el simulador no pide su posicion medida: " + bloque.split("\n")[0]);
});

prueba("y con el nombre que esa fuente usa", () => {
  /* En el simulador el plano del circuito son `x` y **`z`**: la `y` es la
     altura. Mapearla a `world_position_y` dibujaria el desnivel como si fuera
     una coordenada del mapa. */
  const i = fuenteApp.indexOf("const SENAL_F1 = ");
  assert.notStrictEqual(i, -1, "no esta la tabla de nombres del simulador");
  const bloque = fuenteApp.slice(i, i + 300);
  assert.ok(/posX:\s*"world_position_x"/.test(bloque), "posX mal mapeada");
  assert.ok(/posY:\s*"world_position_z"/.test(bloque),
    "posY tiene que ser world_position_z: la `y` del simulador es la altura");
});

/* -------- y la misma regla en vivo, al congelar el circuito -------- */

const soloDesdeLaLinea = new Function(
  `${extraer("soloDesdeLaLinea")} return soloDesdeLaLinea;`)();

prueba("EN VIVO, EL CIRCUITO TAMPOCO INCLUYE LA APROXIMACION", () => {
  /* `congelarTrazadoVivo` toma lo acumulado y lo declara **el circuito**. Si
     ahi entra lo recorrido antes de la linea, el circuito en vivo queda con la
     misma cuña y la misma falsa chicana que tenia la sesion guardada: son dos
     trayectorias distintas superpuestas.

     Mientras se construye se dibuja todo, y esta bien: ahi el encabezado
     declara «recorrido en construccion, medido en vivo» y lo que se muestra es
     lo que el coche recorrio. Lo que no puede pasar es que eso se congele
     **como el circuito**. */
  const puntos = [[0, 0], [1, 1], [2, 2], [3, 3], [4, 4]];
  const metros = [-900, -10, 0, 120, 240];
  assert.deepStrictEqual(soloDesdeLaLinea(puntos, metros),
                         [[2, 2], [3, 3], [4, 4]]);
});

prueba("el metro cero es la largada y entra", () => {
  const puntos = [[0, 0], [1, 1]];
  assert.deepStrictEqual(soloDesdeLaLinea(puntos, [0, 10]), puntos);
});

prueba("una vuelta que nunca estuvo antes de la linea no se toca", () => {
  const puntos = [[0, 0], [1, 1], [2, 2]];
  assert.strictEqual(soloDesdeLaLinea(puntos, [10, 20, 30]), puntos);
});

prueba("sin metros no se recorta nada", () => {
  /* Una fuente que no publique distancia de vuelta ---el bus--- no declara
     nada sobre la linea, y recortarle el recorrido lo dejaria sin circuito. */
  const puntos = [[0, 0], [1, 1]];
  assert.strictEqual(soloDesdeLaLinea(puntos, null), puntos);
  assert.strictEqual(soloDesdeLaLinea(puntos, [null, null]), puntos);
});

prueba("arreglos desalineados no recortan", () => {
  const puntos = [[0, 0], [1, 1], [2, 2]];
  assert.strictEqual(soloDesdeLaLinea(puntos, [-5, 0]), puntos);
});

prueba("si todo es anterior a la linea no queda circuito", () => {
  /* Y esta bien que quede vacio: `congelarTrazadoVivo` exige veinte puntos
     para congelar, asi que no congela nada y sigue en construccion. */
  assert.deepStrictEqual(soloDesdeLaLinea([[0, 0], [1, 1]], [-90, -10]), []);
});

prueba("el que congela el circuito usa esta regla", () => {
  const i = fuenteApp.indexOf("function congelarTrazadoVivo(");
  assert.notStrictEqual(i, -1, "no esta congelarTrazadoVivo");
  const cuerpo = fuenteApp.slice(i, i + 700);
  assert.ok(/soloDesdeLaLinea\(/.test(cuerpo),
    "congela el recorrido entero, con la aproximacion adentro");
});

/* -------- y un pedazo de vuelta no es un circuito -------- */

const CONSTANTES_DEL_RECORRIDO = ["RECORRIDO_EMPIEZA_ANTES_DE_M"];

function extraerConstante(nombre) {
  const marca = "const " + nombre + " = ";
  const desde = fuenteApp.indexOf(marca);
  if (desde === -1) throw new Error("no esta la constante " + nombre);
  const fin = fuenteApp.indexOf(";", desde);
  return fuenteApp.slice(desde, fin + 1);
}

const bancoDeVueltaEntera = new Function(
  "vivo",
  [CONSTANTES_DEL_RECORRIDO.map(extraerConstante).join("\n"),
   extraer("cerroUnaVueltaEntera"),
   "return cerroUnaVueltaEntera;"].join("\n"))(
  { metroDeArranque: new Map() });

function conArranque(metro) {
  const vivo = { metroDeArranque: new Map() };
  if (metro !== undefined) vivo.metroDeArranque.set("coche", metro);
  return new Function(
    "vivo",
    [CONSTANTES_DEL_RECORRIDO.map(extraerConstante).join("\n"),
     extraer("cerroUnaVueltaEntera"),
     "return cerroUnaVueltaEntera;"].join("\n"))(vivo)("coche");
}

prueba("EL DEFECTO: escuchar a mitad de vuelta no mide el circuito", () => {
  /* El 2026-09-13, en Spa: se empezo a escuchar a mitad de la tercera vuelta y
     al cerrarla se congelo el arco acumulado ---1.313 posiciones, sesenta y
     cinco segundos--- como si fuera el circuito. La polilinea se cierra uniendo
     la punta con el arranque por donde el coche nunca paso: ese es el trazado
     cruzado que se vio en pantalla. */
  assert.strictEqual(conArranque(3200), false,
    "un arco de media vuelta se congelo como circuito");
  assert.strictEqual(conArranque(600), false);
});

prueba("y una vuelta medida desde la linea si lo es", () => {
  assert.strictEqual(conArranque(0), true);
  assert.strictEqual(conArranque(3.4), true,
    "la primera muestra cae unos metros pasada la linea, no en el cero exacto");
  assert.strictEqual(conArranque(-900), true,
    "antes de la linea tambien: de eso se ocupa soloDesdeLaLinea");
});

prueba("el umbral es el que la constante declara, no otro", () => {
  const umbral = new Function(
    extraerConstante("RECORRIDO_EMPIEZA_ANTES_DE_M") +
    " return RECORRIDO_EMPIEZA_ANTES_DE_M;")();
  assert.strictEqual(conArranque(umbral), true);
  assert.strictEqual(conArranque(umbral + 0.1), false);
});

prueba("no saber desde donde se midio no autoriza a congelar", () => {
  assert.strictEqual(conArranque(undefined), false);
  assert.strictEqual(conArranque(NaN), false);
});

prueba("el banco se arma sobre la funcion publicada", () => {
  assert.strictEqual(typeof bancoDeVueltaEntera, "function");
});

prueba("EL LARGO SE CONGELA CON EL MAYOR, NO CON EL ULTIMO", () => {
  /* El paquete de vuelta trae `lap_distance` **antes** que `lap_number`: para
     cuando se detecta el cruce, el cuentakilometros ya volvio a cero. Leer el
     ultimo declaraba el circuito de Spa con «3 m» de largo, que es lo que se
     vio el 2026-09-13. Es una linea de la incorporacion en vivo y no una rama
     aislable: se comprueba sobre el `app.js` publicado. */
  const i = fuenteApp.indexOf("if (cerroUnaVueltaEntera(");
  assert.notStrictEqual(i, -1, "no esta la decision de congelar");
  const bloque = fuenteApp.slice(i, i + 300);
  assert.ok(/congelarTrazadoVivo\(vivo\.metroMayorDeLaVuelta\.get\(/.test(bloque),
    "congela con el ultimo metro, que en la meta son tres: " + bloque.split("\n")[1]);
});

prueba("y el arco descartado no se mezcla con la vuelta que arranca", () => {
  const i = fuenteApp.indexOf("function olvidarRecorridoParcial(");
  assert.notStrictEqual(i, -1, "no esta olvidarRecorridoParcial");
  const cuerpo = fuenteApp.slice(i, fuenteApp.indexOf("\n}", i));
  assert.ok(/vivo\.recorrido\.delete\(/.test(cuerpo), "no suelta el recorrido");
  assert.ok(/vivo\.metroDePosicion\.delete\(/.test(cuerpo),
    "deja los metros desalineados con los puntos, y ahi soloDesdeLaLinea se abstiene");
  assert.ok(/vivo\.recorridoDibujado = 0/.test(cuerpo),
    "sin reiniciar el contador el dibujo no se rehace hasta dentro de cien puntos");
});

console.log("ok " + hechas + " pruebas del metro antes de la linea");
