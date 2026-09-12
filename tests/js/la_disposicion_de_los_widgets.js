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
  ${extraerDesde("const WIDGETS = [", "\n];")}
  ${extraer("disposicionPorOmision")}
  ${extraer("anchoAcotado")}
  ${extraer("reconciliarDisposicion")}
  return { COLUMNAS_DEL_TABLERO, WIDGETS, disposicionPorOmision, reconciliarDisposicion };
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

console.log("ok " + hechas + " pruebas de la disposicion de los widgets");
