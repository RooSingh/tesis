/* El velo que tapa mientras el tablero no tiene nada que mostrar.
 *
 * CRITERIO. Como los demas arneses, las funciones se **extraen del `app.js` que
 * se publica** y se ejecutan; no se copian.
 *
 * QUE CIERRA ESTO. Dos decisiones, y las dos se toman sin tocar el DOM
 * justamente para poder ejercerlas.
 *
 * UNA. CUANTO DURA EL VELO. El piso **compite** con la carga, no se le suma.
 * Medido el 2026-09-11 sobre Spa: en frio lo que hace falta para dibujar entra
 * en 1,1 s y tibio el primer trazo aparece a los 657 ms. Con un velo que durase
 * piso mas carga, cada recarga costaria cinco segundos de mas sobre lo que ya
 * estaba listo. Y al reves: una carga que tarde mas que el piso no se corta a
 * los cinco segundos para mostrar un tablero a medio armar.
 *
 * DOS. QUE SE ABRE SOLA. Antes, sin nada recordado, el tablero abria la sesion
 * mas grande de F1 25. Ahora no abre nada: abrir de prepo una carrera que nadie
 * pidio hace creer que eso es «lo suyo» cuando es la que mas filas tiene.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");

const APP = path.join(__dirname, "..", "..", "dashboard", "app.js");
const INDICE = path.join(__dirname, "..", "..", "dashboard", "index.html");
const fuenteApp = fs.readFileSync(APP, "utf8");
const indice = fs.readFileSync(INDICE, "utf8");

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

/* La cifra del piso se extrae tambien: la prueba tiene que medir el piso que se
   publica y no uno parecido escrito aca. */
const lineaDelPiso = /const PISO_DEL_VELO_MS = (\d+);/.exec(fuenteApp);
if (!lineaDelPiso) throw new Error("no esta PISO_DEL_VELO_MS en app.js");
const PISO = Number(lineaDelPiso[1]);

const m = new Function(`
  ${lineaDelPiso[0]}
  ${extraer("esperaDelVelo")}
  ${extraer("sesionQueSeAbreSola")}
  return { esperaDelVelo, sesionQueSeAbreSola };
`)();

let hechas = 0;
function prueba(titulo, fn) {
  try { fn(); hechas++; }
  catch (e) {
    process.exitCode = 1;
    console.error("FALLA  " + titulo + "\n       " + (e && e.message));
  }
}

// ------------------------------------------------------ cuanto dura el velo

prueba("una carga mas rapida que el piso espera hasta el piso, y nada mas", () => {
  /* Los 657 ms medidos tibio: el velo completa hasta el piso. */
  assert.strictEqual(m.esperaDelVelo(657), PISO - 657);
  assert.strictEqual(m.esperaDelVelo(1100), PISO - 1100);
  assert.strictEqual(m.esperaDelVelo(0), PISO);
});

prueba("el piso compite con la carga, no se le suma", () => {
  /* La distincion entera. Si se sumara, una carga de 1,3 s daria 5 s de espera
     **adicionales** y el total serian 6,3. Lo que se quiere es que el total sea
     el piso, o sea 5 s desde que arranco la pagina. */
  const cuandoArranco = 1300;
  assert.strictEqual(cuandoArranco + m.esperaDelVelo(cuandoArranco), PISO);
});

prueba("una carga mas lenta que el piso no espera nada de mas", () => {
  /* Con el backend en frio `/avisos` tarda 16,9 s. Si lo esencial llegara a
     tardar mas que el piso, el velo se va apenas termina: agregarle el piso
     encima seria castigar justamente a la carga que ya fue lenta. */
  assert.strictEqual(m.esperaDelVelo(PISO), 0);
  assert.strictEqual(m.esperaDelVelo(PISO + 1), 0);
  assert.strictEqual(m.esperaDelVelo(17000), 0);
});

prueba("la espera nunca es negativa", () => {
  /* Un numero negativo en `setTimeout` corre enseguida, asi que el efecto
     seria el mismo; pero una funcion que devuelve «menos tres segundos» de
     espera no se puede leer, y la proxima persona que la use en una resta va a
     obtener algo que no espera. */
  assert.ok(m.esperaDelVelo(99999) >= 0);
  assert.ok(m.esperaDelVelo(PISO * 3) >= 0);
});

// ------------------------------------------------------- que se abre sola

const catalogo = [
  { session_id: "f1_25:session:1", fuente: "f1_25_udp_simulation", filas: 5000000 },
  { session_id: "can:segmento:sample_28", fuente: "can_real_replay", filas: 59405 },
];

prueba("sin nada recordado no se abre nada, ni la mas grande", () => {
  /* El cambio. Antes esto devolvia la sesion de F1 25 por ser la de mas filas. */
  assert.strictEqual(m.sesionQueSeAbreSola(catalogo, null), null);
  assert.strictEqual(m.sesionQueSeAbreSola(catalogo, undefined), null);
  assert.strictEqual(m.sesionQueSeAbreSola(catalogo, ""), null);
});

prueba("la que se estaba mirando se reabre", () => {
  assert.strictEqual(m.sesionQueSeAbreSola(catalogo, "can:segmento:sample_28"),
                     "can:segmento:sample_28");
});

prueba("una recordada que ya no esta no arrastra a otra en su lugar", () => {
  /* Sustituirla por la mas grande seria contestar una pregunta que nadie hizo:
     quien vuelve espera **su** sesion, y si no esta hay que decirlo. */
  assert.strictEqual(m.sesionQueSeAbreSola(catalogo, "f1_25:session:borrada"), null);
});

prueba("un catalogo vacio no rompe la eleccion", () => {
  assert.strictEqual(m.sesionQueSeAbreSola([], "f1_25:session:1"), null);
  assert.strictEqual(m.sesionQueSeAbreSola(null, "f1_25:session:1"), null);
});

// --------------------------------------------------- el velo y su salvaguarda

prueba("el velo viene tapado en el marcado y no lo abre el guion", () => {
  /* Si naciera abierto habria un destello de tablero vacio entre el primer
     pintado y la primera linea de `app.js`, que es lo que el velo evita. */
  assert.ok(/<div class="velo-arranque" id="velo-de-arranque"\s+data-abierto="si"/
            .test(indice), "el velo no nace tapado");
});

prueba("el techo no depende de que app.js cargue", () => {
  /* LA PRUEBA QUE IMPORTA. Un velo que solo `app.js` sabe levantar deja la
     pagina tapada para siempre el dia que ese archivo no cargue, y una pagina
     tapada es peor que una rota porque no se ve que esta rota. El techo tiene
     que estar en un guion en linea del propio HTML. */
  const enLinea = indice.slice(indice.indexOf('id="velo-de-arranque"'));
  const guion = enLinea.slice(enLinea.indexOf("<script>"),
                              enLinea.indexOf("</script>"));
  assert.ok(guion.indexOf("velo-de-arranque") !== -1,
            "el guion en linea no toca el velo");
  /* Las dos formas de escribirlo valen; lo que no vale es que no lo destape. */
  assert.ok(/dataset\.abierto\s*=\s*["']no["']/.test(guion) ||
            /setAttribute\(\s*["']data-abierto["']\s*,\s*["']no["']/.test(guion),
            "el guion en linea no lo destapa");
  assert.ok(/setTimeout/.test(guion) && /\d{4,}/.test(guion),
            "el guion en linea no tiene un techo por reloj");
  assert.ok(guion.indexOf("src=") === -1,
            "el techo se fue a un archivo aparte: vuelve a depender de que cargue");
  assert.ok(/\.hidden\s*=\s*true/.test(guion),
            "el techo se apoya en la transicion, que en una pestaña de fondo no corre");
});

prueba("el velo se va aunque la transicion no corra nunca", () => {
  /* LA PRUEBA QUE MAS IMPORTA DE ESTE ARCHIVO. Una transicion de CSS no avanza
     en una pestaña que no se ve: el navegador no pinta cuadros ahi. Y abrir el
     tablero y cambiar de pestaña mientras carga es lo normal. Visto el
     2026-09-11: con la pestaña de fondo el velo quedaba a medio desvanecer,
     con el giro dando vueltas sobre el tablero ya cargado.

     Asi que la desaparicion no puede colgar de que la transicion termine ---ni
     de `transitionend`, que en ese caso no llega--- sino de un atributo, que no
     necesita que se pinte un solo cuadro. */
  const i = fuenteApp.indexOf("function levantarElVelo()");
  const cuerpo = fuenteApp.slice(i, fuenteApp.indexOf("\n}", i));
  assert.ok(/\.hidden\s*=\s*true/.test(cuerpo),
            "el velo solo se apaga por CSS: en una pestaña de fondo se queda");
  assert.ok(cuerpo.indexOf("transitionend") === -1,
            "la desaparicion cuelga de un evento que en una pestaña de fondo no llega");
  /* Y la regla que hace que `hidden` gane de verdad. `.velo-arranque` declara
     su propio `display` y sin el `!important` le ganaria por orden de archivo. */
  const hoja = fs.readFileSync(
    path.join(__dirname, "..", "..", "dashboard", "styles.css"), "utf8");
  assert.ok(hoja.indexOf("[hidden] { display: none !important; }") !== -1,
            "sin esa regla, `hidden` no alcanza contra el display del velo");
});

prueba("las cuatro situaciones de listo levantan el mismo velo", () => {
  /* Lo esencial resuelto, el elector esperando, el catalogo vacio y la API
     caida. Las dos ultimas son las que no se pueden olvidar: tapar un error es
     dejar a alguien mirando un giro eterno sin saber que paso. */
  const veces = (fuenteApp.match(/levantarElVelo\(\);/g) || []).length;
  assert.ok(veces >= 5, "se llama " + veces + " veces, y son cuatro situaciones " +
                        "mas la definicion");
  const i = fuenteApp.indexOf("function levantarElVelo()");
  const cuerpo = fuenteApp.slice(i, fuenteApp.indexOf("\n}", i));
  assert.ok(cuerpo.indexOf("_veloLevantado") !== -1,
            "sin guarda, cada situacion programa su propia levantada");
});

console.log(hechas + " pruebas del velo de arranque: " +
            (process.exitCode ? "hubo fallos" : "OK"));
