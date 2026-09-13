/* Como se nombra de donde viene una sesion.
 *
 * CRITERIO. Como los demas arneses, lo que se prueba se **extrae del `app.js`
 * que se publica** y se ejecuta; no se copia.
 *
 * QUE PASABA, MEDIDO EL 2026-09-13 SOBRE LA BASE DE LA PI. El generador del
 * capitulo 8 dejo `demo_session_01`, 42.889 filas, `source_type`
 * `can_simulated`. El tablero la mostraba ---esta en el catalogo--- con la
 * pastilla **«CAN real»**, y abrirla ponia «CAN real · captura del bus» en el
 * encabezado. Dos sitios afirmando que datos generados salieron del bus de un
 * vehiculo que circulaba.
 *
 * POR QUE. El rotulo salia de la **clave corta**, que es un agrupamiento de
 * comportamiento: `can_real_replay` y `can_simulated` comparten `can` porque el
 * tablero los trata igual ---mismo filtro, mismos paneles--- y de ahi se
 * leia el nombre. Agrupar dos cosas para tratarlas igual no autoriza a
 * llamarlas igual.
 *
 * Y HABIA UN SEGUNDO AGUJERO AL LADO: el filtro decia
 * `FUENTE_CORTA[s.fuente] || "can"`. Cualquier fuente que el tablero no
 * conociera caia por omision en la del bus real. Un valor por omision no puede
 * ser la afirmacion mas especifica y mas cara de equivocar.
 *
 * EN ESTE TRABAJO ES EL PEOR ROTULO POSIBLE. Lo que el trabajo aporta es
 * separar tres niveles de procedencia; el nivel A es el unico medido sobre un
 * vehiculo real. Que ese rotulo cubra datos generados vacia el aporte.
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
  const marca = "const " + nombre + " = ";
  const desde = fuenteApp.indexOf(marca);
  if (desde === -1) throw new Error("no esta la constante " + nombre);
  //: Una tabla se cierra en su llave, no en el primer punto y coma.
  let i = fuenteApp.indexOf("{", desde);
  let nivel = 0;
  for (; i < fuenteApp.length; i++) {
    if (fuenteApp[i] === "{") nivel++;
    else if (fuenteApp[i] === "}") {
      nivel--;
      if (nivel === 0) return fuenteApp.slice(desde, i + 1) + ";";
    }
  }
  throw new Error("no cierra la constante " + nombre);
}

/* Solo el codigo, sin los comentarios. Una guarda que busca un texto en el
   archivo se rompe con el comentario que explica por que ese texto no debe
   estar: la frase nombra el defecto y la busqueda no distingue nombrarlo de
   cometerlo. Paso cinco veces el 2026-09-13. */
function soloCodigo(js) {
  return js.replace(/\/\*[\s\S]*?\*\//g, " ")
           .split("\n").map(r => r.split("//")[0]).join("\n");
}

const banco = new Function(
  [constante("ETIQUETA_DE_ORIGEN"),
   extraer("etiquetaDeOrigen"),
   "return { ETIQUETA_DE_ORIGEN, etiquetaDeOrigen };"].join("\n"))();
const { ETIQUETA_DE_ORIGEN, etiquetaDeOrigen } = banco;

const FUENTE_CORTA = new Function(
  constante("FUENTE_CORTA") + "\nreturn FUENTE_CORTA;")();

let hechas = 0;
function prueba(nombre, fn) {
  try { fn(); hechas++; } catch (e) {
    process.exitCode = 1;
    console.error("FALLA  " + nombre + "\n       " + (e && e.message));
  }
}

prueba("EL DEFECTO: una sesion generada no se llama «CAN real»", () => {
  const etiqueta = etiquetaDeOrigen("can_simulated");
  assert.notStrictEqual(etiqueta, "CAN real");
  assert.ok(/simulad/i.test(etiqueta),
    "no dice que es simulada: «" + etiqueta + "»");
});

prueba("y el bus de verdad se sigue llamando por su nombre", () => {
  assert.strictEqual(etiquetaDeOrigen("can_real_replay"), "CAN real");
  assert.strictEqual(etiquetaDeOrigen("f1_25_udp_simulation"), "F1 25");
  assert.strictEqual(etiquetaDeOrigen("openf1_historical_replay"), "OpenF1");
});

prueba("NINGUNA FUENTE COMPARTE ROTULO CON OTRA", () => {
  /* Dos procedencias con el mismo nombre son una sola para quien mira, y es
     exactamente el defecto que se esta cerrando. */
  const vistos = Object.values(ETIQUETA_DE_ORIGEN);
  assert.strictEqual(new Set(vistos).size, vistos.length,
    "hay rotulos repetidos: " + vistos.join(", "));
});

prueba("UNA FUENTE DESCONOCIDA NO CAE EN LA DEL BUS REAL", () => {
  /* El valor por omision no puede ser la afirmacion mas cara de equivocar. Se
     muestra lo que la base declara, que es un dato y no un nombre inventado. */
  const etiqueta = etiquetaDeOrigen("fuente_que_todavia_no_existe");
  assert.notStrictEqual(etiqueta, "CAN real");
  assert.ok(etiqueta.indexOf("fuente_que_todavia_no_existe") !== -1,
    "no dice que fuente es: «" + etiqueta + "»");
});

prueba("y una sesion sin fuente declarada lo dice, en vez de elegir una", () => {
  /* `sesiones_catalogo.source_type` admite nulos a proposito: hay sesiones
     cargadas antes de que existiera la columna de procedencia. */
  [null, undefined, ""].forEach(sin => {
    const etiqueta = etiquetaDeOrigen(sin);
    assert.notStrictEqual(etiqueta, "CAN real");
    assert.ok(/sin fuente declarada/i.test(etiqueta), etiqueta);
  });
});

prueba("TODA FUENTE QUE EL TABLERO SABE AGRUPAR, SABE NOMBRAR", () => {
  /* `FUENTE_CORTA` decide comportamiento y `ETIQUETA_DE_ORIGEN` decide nombre.
     Una fuente nueva que entre en la primera y no en la segunda se mostraria
     con su clave cruda, que no es un rotulo. */
  const faltan = Object.keys(FUENTE_CORTA).filter(f => !ETIQUETA_DE_ORIGEN[f]);
  assert.deepStrictEqual(faltan, [], "sin rotulo: " + faltan.join(", "));
});

/* -------- y los sitios que muestran el rotulo tienen que pedirlo aca -------- */

prueba("LA LISTA DE SESIONES ROTULA POR LA FUENTE DE LA SESION", () => {
  /* Si vuelve a leer el rotulo de la clave corta, vuelve el defecto entero. */
  const codigo = soloCodigo(fuenteApp);
  const i = codigo.indexOf("pastilla-fuente");
  assert.notStrictEqual(i, -1, "no esta la pastilla de la lista");
  const alrededor = codigo.slice(i, i + 260);
  assert.ok(/etiquetaDeOrigen\(/.test(alrededor),
    "la pastilla volvio a sacar el nombre del agrupamiento de comportamiento");
  assert.ok(!/ETIQUETA_FUENTE\[corta\]/.test(alrededor), alrededor);
});

prueba("EL ENCABEZADO NOMBRA LA SESION ABIERTA, NO EL MODO", () => {
  /* Abrir la sesion generada ponia «CAN real · captura del bus» arriba de
     todo. El modo es en cual de los tres esta parado el tablero; con una sesion
     abierta, lo que hay que nombrar es de donde salio esa sesion. */
  const cuerpo = soloCodigo(extraer("pintarTitulo"));
  assert.ok(/etiquetaDeOrigen\(/.test(cuerpo),
    "el encabezado sigue nombrando el modo y no la procedencia de la sesion");
});

prueba("EL FILTRO NO MANDA LO DESCONOCIDO AL CAJON DEL BUS REAL", () => {
  const cuerpo = soloCodigo(extraer("sesionesFiltradas"));
  assert.ok(!/FUENTE_CORTA\[s\.fuente\]\s*\|\|\s*"can"/.test(cuerpo),
    "una fuente que el tablero no conoce sigue contando como CAN real");
});

prueba("el modo sigue teniendo sus tres nombres, que son otra cosa", () => {
  /* `ETIQUETA_FUENTE` nombra los tres modos de adquisicion y esta atado al pie
     legal ---hay una prueba que lo exige---. No se toca: lo que se separo es el
     nombre de **una sesion** del nombre de **un modo**. */
  const etiquetas = new Function(
    constante("ETIQUETA_FUENTE") + "\nreturn ETIQUETA_FUENTE;")();
  assert.deepStrictEqual(Object.keys(etiquetas).sort(), ["can", "f1", "openf1"]);
});

/* ==================================================================
   Y EL NOMBRE DE LA SESION, QUE ES EL ROTULO MAS GRANDE DE LA FILA
   ------------------------------------------------------------------
   La pastilla decia «CAN real» y se arreglo; pero el titulo de la fila decia
   «Segmento del bus» y el subtitulo «Captura de transito», los dos derivados de
   la misma clave corta y los dos falsos sobre datos generados: no hay segmento,
   no hay bus y no hubo transito. Un rotulo chico corregido al lado de dos
   grandes que siguen mintiendo no arregla nada.

   LOS NOMBRES SALEN DE COMO SE LLAMA EL GENERADOR A SI MISMO: un «escenario
   demostrativo» de sesenta segundos que, dice su propio codigo, «no representa
   una vuelta fisica exacta».
   ================================================================== */

const nombrar = new Function(
  [constante("CIRCUITOS"), constante("FUENTE_CORTA"),
   constante("NOMBRE_POR_ORIGEN"), constante("TIPO_POR_ORIGEN"),
   constante("FAMILIAS"),
   extraer("nombreDeSesion"), extraer("tipoDeSesion"),
   "return { nombreDeSesion, tipoDeSesion };"].join("\n"))();

prueba("EL DEFECTO GRANDE: la sesion generada no es un segmento del bus", () => {
  const nombre = nombrar.nombreDeSesion({ fuente: "can_simulated" });
  assert.notStrictEqual(nombre, "Segmento del bus");
  assert.ok(/gener/i.test(nombre), "no dice que esta generada: «" + nombre + "»");
});

prueba("ni lo que hizo fue capturar transito", () => {
  const tipo = nombrar.tipoDeSesion({ fuente: "can_simulated" });
  assert.notStrictEqual(tipo, "Captura de tránsito");
  assert.ok(/escenario|maniobra|simulad/i.test(tipo), tipo);
});

prueba("y la captura real conserva sus dos nombres", () => {
  assert.strictEqual(nombrar.nombreDeSesion({ fuente: "can_real_replay" }),
                     "Segmento del bus");
  assert.strictEqual(nombrar.tipoDeSesion({ fuente: "can_real_replay" }),
                     "Captura de tránsito");
});

prueba("UNA FUENTE DESCONOCIDA NO SE LLAMA COMO EL BUS", () => {
  /* Los dos tenian `FUENTE_CORTA[s.fuente] || "can"`, de modo que cualquier
     fuente nueva entraba al tablero llamandose «Segmento del bus · Captura de
     transito» sin que nadie lo hubiera decidido. */
  assert.strictEqual(nombrar.nombreDeSesion({ fuente: "vaya_uno_a_saber" }),
                     "Sesión sin procedencia declarada");
  assert.strictEqual(nombrar.tipoDeSesion({ fuente: "vaya_uno_a_saber" }),
                     "Sin declarar");
});

prueba("lo que la sesion declara de si misma sigue mandando", () => {
  /* El circuito y el tipo declarados ganan sobre cualquier tabla: son lo que la
     sesion dice de si misma, y las tablas son el respaldo para cuando calla. */
  assert.strictEqual(
    nombrar.nombreDeSesion({ fuente: "can_simulated", circuito: "monza" }),
    nombrar.nombreDeSesion({ fuente: "f1_25_udp_simulation", circuito: "monza" }));
  assert.strictEqual(
    nombrar.tipoDeSesion({ fuente: "can_simulated", tipo: "Carrera" }), "Carrera");
});

console.log("ok " + hechas + " pruebas del rotulo de la procedencia");
