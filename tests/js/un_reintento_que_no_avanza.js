/* Un reintento se ata a que algo cambie, no a que una promesa se asiente.
 *
 * CRITERIO. Como los demas arneses, las funciones se **extraen del `app.js` que
 * se publica** y se ejecutan; no se copian.
 *
 * EL DEFECTO QUE ESTO CIERRA, Y COLGABA LA PAGINA. La vista ampliada, al no
 * encontrar cargada la vuelta bajo el cabezal, pedia los datos y se volvia a
 * dibujar cuando la promesa se asentaba:
 *
 *     if (faltan) asegurarDatosComparacion().then(() => { ...; dibujarComparacion(); });
 *
 * y `asegurarDatosComparacion` empezaba con
 *
 *     if (fuente !== "f1") return Promise.resolve([]);
 *
 * de cuando comparar era cosa del simulador. Sobre OpenF1 y sobre el bus esa
 * promesa venia ya asentada y sin traer nada, asi que el redibujo encontraba
 * exactamente el mismo estado, volvia a pedir, y otra vez. Son microtareas: se
 * drenan enteras antes de que el navegador pueda pintar o atender un clic, de
 * modo que no es lentitud sino una pagina que no vuelve nunca.
 *
 * MEDIDO el 2026-09-11 en el navegador, arrastrando el cabezal de la sesion
 * OpenF1 9947 con la vista ampliada abierta hasta una vuelta sin cargar:
 *
 *     dibujarComparacion      928.517 llamadas   71.952 ms   y seguia
 *     vistaDeComparacion      928.518 llamadas    9.860 ms
 *     pintarPista                 143 llamadas       60 ms
 *
 * El servidor no recibio ni una consulta de mas: el bucle era entero del
 * navegador. Chrome mostro «Page Unresponsive» y la pestaña quedo muerta.
 *
 * POR QUE NO SE ARREGLA CONTANDO INTENTOS. Un tope elige un numero y deja el
 * caso de al lado colgado un poco menos. Lo que hace falta es que el reintento
 * dependa de que el estado **avance**: `_selloSeries` sube cada vez que
 * `estado.series` cambia de verdad, y es el mismo sello que ya invalida las
 * series armadas. Si despues de pedir el sello no se movio, no llego nada y no
 * hay nada que volver a dibujar.
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

/* La variable de modulo que lleva la espera. Se toma la declaracion real y se
   le cuelga un ajustador, porque un `let` extraido no se puede escribir desde
   afuera y la prueba necesita reiniciarlo entre casos. */
function variable(nombre) {
  const i = fuenteApp.indexOf("let " + nombre + " =");
  if (i === -1) throw new Error("no esta la variable " + nombre);
  const fin = fuenteApp.indexOf(";", i);
  return fuenteApp.slice(i, fin + 1);
}

/* ------------------------------------------------------------------
   El entorno. `asegurarDatosComparacion`, `dibujarComparacion` y
   `pintarPilotosComparacion` se controlan desde aca: lo que se prueba es la
   regla del reintento, no lo que dibuja.
   ------------------------------------------------------------------ */
const ambiente = {
  selloSeries: 0,
  pedidos: 0,
  dibujos: 0,
  /* Cuantas tandas quedan por llegar. En cero la peticion se asienta sin traer
     nada, que es el caso que colgaba. */
  tandasQueFaltan: 0,
  /* Si la peticion pasa por la cola de tareas ---como pasa una consulta de
     red--- o se asienta en la misma vuelta de microtareas. El defecto vivia en
     el segundo caso: una promesa ya asentada no le devuelve el control al
     navegador nunca. */
  porLaRed: false,
  /* Si el redibujo vuelve a encontrar la vuelta sin cargar y pide otra vez.
     Es lo que hace el `dibujarComparacion` de verdad mientras falten datos. */
  redibujoVuelveAPedir: false,
};

const sacadas = new Function("ambiente", `
  ${variable("_selloEsperadoPorLaComparacion")}
  let _selloSeries = 0;
  function asegurarDatosComparacion() {
    ambiente.pedidos++;
    const traer = () => { if (ambiente.tandasQueFaltan > 0) { ambiente.tandasQueFaltan--; _selloSeries++; } };
    if (!ambiente.porLaRed) { traer(); return Promise.resolve([]); }
    return new Promise(r => setTimeout(() => { traer(); r([]); }, 0));
  }
  function pintarPilotosComparacion() {}
  function dibujarComparacion() {
    ambiente.dibujos++;
    if (ambiente.redibujoVuelveAPedir) reintentarComparacionCuandoLleguenLosDatos();
  }
  ${extraer("reintentarComparacionCuandoLleguenLosDatos")}
  return {
    reintentar: reintentarComparacionCuandoLleguenLosDatos,
    reiniciar: () => { _selloEsperadoPorLaComparacion = null; _selloSeries = 0; },
    sello: () => _selloSeries,
  };
`)(ambiente);

let hechas = 0;
function prueba(titulo, fn) {
  ambiente.pedidos = 0;
  ambiente.dibujos = 0;
  ambiente.tandasQueFaltan = 0;
  ambiente.porLaRed = false;
  ambiente.redibujoVuelveAPedir = false;
  sacadas.reiniciar();
  return Promise.resolve()
    .then(fn)
    .then(() => { hechas++; })
    .catch(e => {
      process.exitCode = 1;
      console.error("FALLA  " + titulo + "\n       " + (e && e.message));
    });
}

/* Deja correr todas las microtareas pendientes. Un `await` suelto solo avanza
   una; el bucle que se persigue vive dentro de la cola de microtareas y hay
   que darle sitio para manifestarse. */
const drenar = () => new Promise(r => setTimeout(r, 0));

async function correr() {

  await prueba("una peticion que no trae nada no vuelve a dibujar", async () => {
    sacadas.reintentar();
    await drenar();
    assert.strictEqual(ambiente.pedidos, 1, "no se pidio, o se pidio de mas");
    assert.strictEqual(ambiente.dibujos, 0,
      "se redibujo sin que llegara nada: es el primer paso del bucle");
  });

  await prueba("cuando llega una tanda se dibuja, y una sola vez", async () => {
    ambiente.tandasQueFaltan = 1;
    sacadas.reintentar();
    await drenar();
    assert.strictEqual(ambiente.pedidos, 1);
    assert.strictEqual(ambiente.dibujos, 1);
  });

  await prueba("dos reintentos por el mismo estado son una sola peticion", async () => {
    /* Cada cuadro del arrastre redibuja, y cada redibujo pediria. Mientras la
       peticion anterior no se asiente, la segunda no abre otra. */
    sacadas.reintentar();
    sacadas.reintentar();
    sacadas.reintentar();
    await drenar();
    assert.strictEqual(ambiente.pedidos, 1, "se abrieron " + ambiente.pedidos + " peticiones");
  });

  await prueba("el redibujo que vuelve a pedir no se convierte en un bucle", async () => {
    /* ESTE ES EL CUELGUE, REPRODUCIDO. El redibujo encuentra los datos todavia
       ausentes y pide de nuevo; la peticion se asienta sin traer nada. Antes
       esto giraba hasta que alguien mataba la pestaña. */
    ambiente.redibujoVuelveAPedir = true;
    sacadas.reintentar();
    for (let i = 0; i < 50; i++) await drenar();
    assert.ok(ambiente.pedidos <= 2,
      "el reintento giro " + ambiente.pedidos + " veces sin que llegara nada");
    assert.strictEqual(ambiente.dibujos, 0,
      "se dibujo " + ambiente.dibujos + " veces sobre un estado que no cambio");
  });

  await prueba("si los datos llegan de a poco, cada tanda dibuja una vez y despues para", async () => {
    /* La contracara: el reintento tiene que seguir funcionando cuando el estado
       si avanza. Tres tandas, tres dibujos, y se detiene cuando deja de llegar.

       La peticion pasa por la cola de tareas, como pasa una consulta de red:
       sin eso, una cadena que siempre trae algo tampoco le devolveria el
       control al navegador ---lo comprobe colgando esta misma prueba---, y eso
       diria mas de como esta escrito el arnes que del tablero. */
    ambiente.porLaRed = true;
    ambiente.tandasQueFaltan = 3;
    ambiente.redibujoVuelveAPedir = true;
    sacadas.reintentar();
    for (let i = 0; i < 40; i++) await drenar();
    assert.strictEqual(ambiente.dibujos, 3,
      "dibujo " + ambiente.dibujos + " veces para tres tandas");
    assert.strictEqual(ambiente.pedidos, 4,
      "pidio " + ambiente.pedidos + " veces: tres que traen y una que cierra");
  });

  /* ------------------------------------------------------------------
     Y la otra mitad del defecto: la vista ampliada de una fuente que no es la
     simulacion tiene que **pedir**. Con el retorno temprano, el reintento de
     arriba nunca podia avanzar porque nadie traia nada.
     ------------------------------------------------------------------ */
  await prueba("la vista ampliada pide datos en cualquier fuente", async () => {
    const llamadas = [];
    const entorno = new Function("llamadas", `
      let fuente = "openf1";
      let vueltaElegida = 7;
      let alcanceComparacion = "una";
      const SERIES_A_LA_VEZ = 3;
      function vueltasParaComparar() { return [vueltaElegida]; }
      function puntosParaVueltas(n) { return 300; }
      function asegurarVuelta(v, puntos) { llamadas.push([v, puntos]); return Promise.resolve({}); }
      function enTandas(lista, cuantas, hacer) { return Promise.all(lista.map(hacer)); }
      function pedirPintado() {}
      ${extraer("asegurarDatosComparacion")}
      return { asegurarDatosComparacion, ponerFuente: f => { fuente = f; } };
    `)(llamadas);

    await entorno.asegurarDatosComparacion();
    assert.deepStrictEqual(llamadas.map(x => x[0]), [7],
      "sobre OpenF1 no se pidio la vuelta: la vista se queda cargando para siempre");
    /* Y con una sola vuelta no se le impone la resolucion de la vista espacial:
       la ampliada quedaria mas gruesa que la cabina, que contra el reloj pide
       1.200 puntos. Se deja elegir al que sabe que eje tiene la fuente. */
    assert.strictEqual(llamadas[0][1], undefined,
      "se forzaron " + llamadas[0][1] + " puntos sobre una sola vuelta");

    llamadas.length = 0;
    entorno.ponerFuente("can");
    await entorno.asegurarDatosComparacion();
    assert.deepStrictEqual(llamadas.map(x => x[0]), [7], "sobre el bus tampoco se pidio");
  });

  console.log(hechas + " pruebas de reintentos que no avanzan: " +
              (process.exitCode ? "hubo fallos" : "OK"));
}

correr();
