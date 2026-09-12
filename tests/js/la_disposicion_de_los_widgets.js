/* Como se guarda y se reconcilia la disposicion de los paneles.
 *
 * CRITERIO. Como los demas arneses, las funciones se **extraen del `app.js` que
 * se publica** y se ejecutan; no se copian.
 *
 * LA AFIRMACION QUE ESTE ARNES DEFIENDE, Y ES LA UNICA QUE IMPORTA DE VERDAD:
 * **una disposicion guardada es un dato del pasado, y el codigo sigue
 * avanzando.** Se escribio con los paneles que habia el dia que el usuario
 * ordeno su tablero, y se lee meses despues, cuando puede haber paneles nuevos
 * y paneles que ya no existen.
 *
 * De ahi salen las dos reglas que todo lo demas obedece:
 *
 * - un panel que la disposicion nombra y el codigo ya no tiene **se ignora**;
 * - un panel que el codigo tiene y la disposicion no nombra **aparece**. Esta
 *   es la que cuesta: lo comodo seria mostrar exactamente lo guardado, y
 *   entonces cada panel nuevo nace invisible para todo el que haya ordenado su
 *   tablero alguna vez ---o sea, invisible y sin que nadie sepa por que---.
 *
 * Y una tercera, que es de otra clase: **esconder no es olvidar**. Un panel que
 * el usuario quito se recuerda quitado, porque si no, volver a mostrarlo
 * significaria adivinar que existia.
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

function extraerDesde(marca, cierre) {
  const desde = fuenteApp.indexOf(marca);
  if (desde === -1) throw new Error("no esta " + marca);
  const fin = fuenteApp.indexOf(cierre, desde);
  if (fin === -1) throw new Error("no cierra " + marca);
  return fuenteApp.slice(desde, fin + cierre.length);
}

const m = new Function(`
  ${extraerDesde("const COLUMNAS_DEL_TABLERO", ";")}
  ${extraerDesde("const ALTO_DE_FILA_PX", ";")}
  ${extraerDesde("const FILAS_MAXIMAS_DE_UN_WIDGET", ";")}
  ${extraerDesde("const WIDGETS = [", "\n];")}
  ${extraer("disposicionPorOmision")}
  ${extraer("medidaAcotada")}
  ${extraer("anchoAcotado")}
  ${extraer("altoAcotado")}
  ${extraer("reconciliarDisposicion")}
  ${extraer("moverWidget")}
  ${extraer("redimensionarWidget")}
  ${extraer("mostrarWidget")}
  return { COLUMNAS_DEL_TABLERO, ALTO_DE_FILA_PX, FILAS_MAXIMAS_DE_UN_WIDGET, WIDGETS, disposicionPorOmision, reconciliarDisposicion, moverWidget, redimensionarWidget, mostrarWidget };
`)();

let hechas = 0;
function prueba(titulo, fn) { fn(); hechas++; }

const ids = d => d.map(w => w.id);

prueba("sin nada guardado, la disposicion es la que declara el codigo", () => {
  const d = m.reconciliarDisposicion(null);
  assert.deepStrictEqual(ids(d), m.WIDGETS.map(w => w.id));
  assert.ok(d.every(w => w.visible), "algun panel nace escondido");
});

prueba("una disposicion rota no deja el tablero vacio", () => {
  /* El almacenamiento puede devolver cualquier cosa: una version vieja, algo a
     medio escribir, o nada. Ninguna de esas es razon para quedarse sin
     tablero. */
  for (const basura of [undefined, "", "no es json", "[1,2,3]", "{}", '"texto"', "null"]) {
    const d = m.reconciliarDisposicion(basura);
    assert.deepStrictEqual(ids(d), m.WIDGETS.map(w => w.id), "con " + basura);
  }
});

prueba("un panel que ya no existe en el codigo se ignora", () => {
  const guardado = JSON.stringify([
    { id: "panel-que-se-borro", ancho: 2, visible: true },
    { id: m.WIDGETS[0].id, ancho: 1, visible: true },
  ]);
  const d = m.reconciliarDisposicion(guardado);
  assert.ok(!ids(d).includes("panel-que-se-borro"));
  assert.strictEqual(ids(d).length, m.WIDGETS.length);
});

prueba("UN PANEL NUEVO APARECE, aunque la disposicion guardada no lo nombre", () => {
  /* La regla que cuesta. Mostrar exactamente lo guardado seria mas simple y
     haria que cada panel que se agregue nazca invisible para todo el que haya
     ordenado su tablero alguna vez. */
  const soloElPrimero = JSON.stringify([{ id: m.WIDGETS[0].id, ancho: 1, visible: true }]);
  const d = m.reconciliarDisposicion(soloElPrimero);
  assert.strictEqual(d.length, m.WIDGETS.length, "se perdieron paneles");
  for (const w of m.WIDGETS) {
    const hay = d.find(x => x.id === w.id);
    assert.ok(hay, "falta " + w.id);
    if (w.id !== m.WIDGETS[0].id) {
      assert.ok(hay.visible, "un panel nuevo nacio escondido: " + w.id);
    }
  }
});

prueba("y aparece al final, no en el medio de lo que el usuario ordeno", () => {
  const alReves = JSON.stringify(
    m.WIDGETS.slice(0, 2).reverse().map(w => ({ id: w.id, ancho: 1, visible: true })));
  const d = m.reconciliarDisposicion(alReves);
  assert.deepStrictEqual(ids(d).slice(0, 2), [m.WIDGETS[1].id, m.WIDGETS[0].id],
    "no se respeto el orden que el usuario habia guardado");
});

prueba("esconder no es olvidar", () => {
  /* Un panel quitado se recuerda quitado. Si se lo tratara como ausente, la
     reconciliacion lo volveria a mostrar en cada recarga y no habria forma de
     sacarlo. */
  const conUnoEscondido = JSON.stringify(
    m.WIDGETS.map((w, i) => ({ id: w.id, ancho: 1, visible: i !== 1 })));
  const d = m.reconciliarDisposicion(conUnoEscondido);
  assert.strictEqual(d.find(x => x.id === m.WIDGETS[1].id).visible, false,
    "el panel que se quito volvio solo");
});

prueba("un ancho imposible se acota, no se acepta ni se descarta el panel", () => {
  /* Un ancho de siete columnas en una grilla de cuatro rompe el dibujo, y un
     cero lo hace desaparecer sin decirlo. Se acota a lo que la grilla admite. */
  const d = m.reconciliarDisposicion(JSON.stringify([
    { id: m.WIDGETS[0].id, ancho: 99, visible: true },
    { id: m.WIDGETS[1].id, ancho: 0, visible: true },
    { id: m.WIDGETS[2].id, ancho: -3, visible: true },
    { id: m.WIDGETS[3].id, ancho: "dos", visible: true },
  ]));
  for (const w of d) {
    assert.ok(w.ancho >= 1 && w.ancho <= m.COLUMNAS_DEL_TABLERO,
      w.id + " quedo con ancho " + w.ancho);
    assert.ok(Number.isInteger(w.ancho), w.id + " tiene un ancho que no es entero");
  }
});

prueba("lo que se guarda se vuelve a leer igual", () => {
  /* Ida y vuelta: si reconciliar cambiara algo de una disposicion que ya es
     valida, el tablero se movería solo entre recargas. */
  const d1 = m.reconciliarDisposicion(null);
  const d2 = m.reconciliarDisposicion(JSON.stringify(d1));
  assert.deepStrictEqual(d2, d1);
});

prueba("cada panel declarado existe en el HTML", () => {
  /* Un widget que el catalogo nombra y la pagina no tiene es un hueco en la
     grilla que nadie puede llenar. Se comprueba contra el `index.html` que se
     publica. */
  const html = fs.readFileSync(
    path.join(__dirname, "..", "..", "dashboard", "index.html"), "utf8");
  for (const w of m.WIDGETS) {
    assert.ok(html.includes('data-panel="' + w.id + '"'),
      "el catalogo declara «" + w.id + "» y el HTML no lo tiene");
  }
});

prueba("ningun panel del catalogo esta repetido", () => {
  const vistos = new Set(m.WIDGETS.map(w => w.id));
  assert.strictEqual(vistos.size, m.WIDGETS.length);
});

/* -------- el alto tambien es del widget -------- */

prueba("cada panel declara su alto en filas", () => {
  /* POR QUE EL ALTO NO PUEDE QUEDAR LIBRE, Y ESTA MEDIDO.
     De las reglas de estilo que viven dentro de los paneles, muchas dicen
     `flex: 1`, `min-height: 0` o `height: 100%`: son la forma de escribir
     «lleno el alto que me den». Estan asi porque la cabina **imponia** un alto,
     repartido contra la ventana.

     Con filas de alto libre ese alto no existe, y esas reglas colapsan o
     desbordan: medido el 2026-09-12, el trazado pedia 313 px en una fila de
     145 y se derramaba sobre el panel de abajo. Un panel hecho para llenar un
     alto impuesto no se puede soltar en una grilla de alto libre.

     Asi que el alto se sigue imponiendo ---la grilla tiene filas de tamaño
     fijo--- y lo que cambia es **quien lo decide**: el widget declara cuantas
     filas ocupa, igual que declara cuantas columnas. */
  const d = m.reconciliarDisposicion(null);
  for (const w of d) {
    assert.ok(Number.isInteger(w.alto) && w.alto >= 1,
      w.id + " no declara un alto en filas: " + w.alto);
  }
});

prueba("un alto imposible se acota igual que el ancho", () => {
  const d = m.reconciliarDisposicion(JSON.stringify([
    { id: m.WIDGETS[0].id, ancho: 1, alto: 0, visible: true },
    { id: m.WIDGETS[1].id, ancho: 1, alto: -2, visible: true },
    { id: m.WIDGETS[2].id, ancho: 1, alto: 99, visible: true },
    { id: m.WIDGETS[3].id, ancho: 1, alto: "tres", visible: true },
  ]));
  for (const w of d) {
    assert.ok(w.alto >= 1 && w.alto <= m.FILAS_MAXIMAS_DE_UN_WIDGET,
      w.id + " quedo con alto " + w.alto);
    assert.ok(Number.isInteger(w.alto), w.id + " tiene un alto que no es entero");
  }
});

prueba("una disposicion vieja sin alto toma el de fabrica", () => {
  /* Lo guardado antes de que el alto existiera no nombra el campo. Leerlo como
     cero dejaria el panel sin alto; leerlo como ausente le da el suyo. */
  const sinAlto = JSON.stringify(
    m.WIDGETS.map(w => ({ id: w.id, ancho: w.ancho, visible: true })));
  const d = m.reconciliarDisposicion(sinAlto);
  for (const w of m.WIDGETS) {
    assert.strictEqual(d.find(x => x.id === w.id).alto, w.alto,
      "el panel " + w.id + " no tomo su alto de fabrica");
  }
});

/* -------- lo que el modo edicion puede hacerle a una disposicion -------- */

const orig = () => m.reconciliarDisposicion(null);

prueba("mover un panel no pierde ninguno ni duplica", () => {
  /* LA INVARIANTE QUE TODO LO DEMAS APOYA. Reordenar es la operacion que mas
     veces se hace ---una por arrastre--- y un panel perdido en el medio de
     veinte arrastres no se atribuye a nada. */
  let d = orig();
  const antes = d.map(w => w.id).sort();
  for (const [de, a] of [[0, 3], [3, 0], [8, 1], [1, 8], [4, 4]]) {
    d = m.moverWidget(d, d[de].id, a);
    assert.deepStrictEqual(d.map(w => w.id).sort(), antes, `moviendo ${de}->${a}`);
    assert.strictEqual(new Set(d.map(w => w.id)).size, d.length, "hay repetidos");
  }
});

prueba("mover pone el panel donde se pidio", () => {
  const d = orig();
  const id = d[0].id;
  assert.strictEqual(m.moverWidget(d, id, 2).findIndex(w => w.id === id), 2);
  assert.strictEqual(m.moverWidget(d, id, 0).findIndex(w => w.id === id), 0);
});

prueba("un destino imposible se acota, no se ignora", () => {
  /* Soltar fuera de la grilla es soltar al principio o al final, que es lo que
     el gesto quiso decir. Ignorarlo dejaria el panel donde estaba y se leeria
     como que el arrastre no funciono. */
  const d = orig(); const id = d[3].id;
  assert.strictEqual(m.moverWidget(d, id, -5).findIndex(w => w.id === id), 0);
  assert.strictEqual(m.moverWidget(d, id, 99).findIndex(w => w.id === id), d.length - 1);
});

prueba("mover un panel que no existe no rompe nada", () => {
  const d = orig();
  assert.deepStrictEqual(m.moverWidget(d, "no-existe", 2), d);
});

prueba("no se escribe sobre la disposicion que llego", () => {
  /* Cancelar tiene que poder volver a lo de antes, y eso solo funciona si las
     operaciones devuelven una disposicion nueva en vez de modificar la vieja. */
  const d = orig();
  const copia = JSON.parse(JSON.stringify(d));
  m.moverWidget(d, d[0].id, 4);
  m.redimensionarWidget(d, d[0].id, 3, 3);
  m.mostrarWidget(d, d[0].id, false);
  assert.deepStrictEqual(d, copia, "una operacion modifico su entrada");
});

prueba("redimensionar acota a la grilla", () => {
  const d = orig(); const id = d[0].id;
  const grande = m.redimensionarWidget(d, id, 99, 99).find(w => w.id === id);
  assert.strictEqual(grande.ancho, m.COLUMNAS_DEL_TABLERO);
  assert.strictEqual(grande.alto, m.FILAS_MAXIMAS_DE_UN_WIDGET);
  const chico = m.redimensionarWidget(d, id, 0, -3).find(w => w.id === id);
  assert.strictEqual(chico.ancho, 1);
  assert.strictEqual(chico.alto, 1);
});

prueba("QUITAR NO ES BORRAR", () => {
  /* El panel se queda en la lista, escondido. Si se lo sacara, el modo edicion
     no tendria como ofrecer traerlo de vuelta: habria que adivinar que existio.
     Y la reconciliacion lo repondria visible en la proxima recarga, de modo que
     quitarlo no duraria nada. */
  const d = orig(); const id = d[2].id;
  const sin = m.mostrarWidget(d, id, false);
  assert.strictEqual(sin.length, d.length, "el panel se borro de la lista");
  assert.strictEqual(sin.find(w => w.id === id).visible, false);
  assert.strictEqual(m.mostrarWidget(sin, id, true).find(w => w.id === id).visible, true);
});

prueba("quitar no mueve a los demas", () => {
  const d = orig(); const id = d[2].id;
  assert.deepStrictEqual(m.mostrarWidget(d, id, false).map(w => w.id), d.map(w => w.id));
});

console.log("ok " + hechas + " pruebas de la disposicion de los widgets");
