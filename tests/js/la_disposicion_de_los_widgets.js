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
  ${extraerDesde("const SUBDIVISIONES", ";")}
  ${extraerDesde("const PASO_DE_MEDIDA", ";")}
  ${extraerDesde("const WIDGETS = [", "\n];")}
  ${extraerDesde("const PREFIJO_DE_GRAFICO", ";")}
  ${extraerDesde("const MEDIDA_DE_UN_GRAFICO", ";")}
  ${extraerDesde("let GRAFICOS_EN_EL_TABLERO", ";")}
  ${extraer("esGrafico")}
  ${extraer("catalogoDeWidgets")}
  ${extraer("disposicionPorOmision")}
  ${extraer("medidaAcotada")}
  ${extraer("anchoAcotado")}
  ${extraer("altoAcotado")}
  ${extraer("reconciliarDisposicion")}
  ${extraer("moverWidget")}
  ${extraer("redimensionarWidget")}
  ${extraer("mostrarWidget")}
  return { COLUMNAS_DEL_TABLERO, ALTO_DE_FILA_PX, FILAS_MAXIMAS_DE_UN_WIDGET,
           SUBDIVISIONES, PASO_DE_MEDIDA, WIDGETS,
           PREFIJO_DE_GRAFICO, MEDIDA_DE_UN_GRAFICO, esGrafico, catalogoDeWidgets,
           disposicionPorOmision, reconciliarDisposicion, moverWidget, redimensionarWidget, mostrarWidget };
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

prueba("y aparece donde el codigo lo declara, sin tocar lo que el usuario ordeno", () => {
  /* Lo que el usuario ordeno no se toca: los dos guardados siguen como estaban,
     al reves de como los declara el codigo. Lo nuevo se acomoda alrededor. */
  const alReves = JSON.stringify(
    m.WIDGETS.slice(0, 2).reverse().map(w => ({ id: w.id, ancho: 1, visible: true })));
  const d = m.reconciliarDisposicion(alReves);
  const a = ids(d).indexOf(m.WIDGETS[1].id), b = ids(d).indexOf(m.WIDGETS[0].id);
  assert.ok(a >= 0 && b >= 0 && a < b,
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
    assert.ok(w.ancho >= m.PASO_DE_MEDIDA && w.ancho <= m.COLUMNAS_DEL_TABLERO,
      w.id + " quedo con ancho " + w.ancho);
    assert.ok(Number.isInteger(w.ancho * m.SUBDIVISIONES),
      w.id + " tiene un ancho que la grilla no puede dibujar: " + w.ancho);
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
    assert.ok(w.alto >= m.PASO_DE_MEDIDA && w.alto <= m.FILAS_MAXIMAS_DE_UN_WIDGET,
      w.id + " quedo con alto " + w.alto);
    assert.ok(Number.isInteger(w.alto * m.SUBDIVISIONES),
      w.id + " tiene un alto que la grilla no puede dibujar: " + w.alto);
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

/* -------- los graficos, que son widgets que el catalogo no puede declarar ----- */

const CAT = g => m.catalogoDeWidgets(g);
const G = c => m.PREFIJO_DE_GRAFICO + c;

prueba("cada grafico encendido es un widget mas", () => {
  /* Estaban los cuatro dentro de un bloque unico que cruzaba el tablero: se
     movian y se estiraban juntos, o sea que no se movia ninguno. */
  const cat = CAT(["speed", "gas"]);
  assert.strictEqual(cat.length, m.WIDGETS.length + 2);
  assert.ok(cat.some(w => w.id === G("speed")));
  assert.ok(cat.some(w => w.id === G("gas")));
});

prueba("el prefijo evita que un canal se llame igual que un panel", () => {
  /* Si un canal se llamara «clima», sin prefijo pisaria al panel declarado y
     uno de los dos desapareceria del tablero sin que nadie sepa por que. */
  const cat = CAT(m.WIDGETS.map(w => w.id));
  assert.strictEqual(new Set(cat.map(w => w.id)).size, cat.length,
    "dos widgets distintos comparten identidad");
});

prueba("un grafico apagado no pierde su sitio", () => {
  /* Apagar un canal saca su grafico del tablero. Volver a encenderlo tiene que
     devolverlo **donde estaba**: si su fila se descartara, cada ida y vuelta
     por el panel de señales lo mandaria al final y ordenar el tablero seria
     trabajo que se pierde solo. */
  const conElGrafico = m.reconciliarDisposicion(null, CAT(["speed"]));
  const lugar = conElGrafico.findIndex(w => w.id === G("speed"));
  assert.ok(lugar >= 0, "el grafico no entro en la disposicion");
  const movido = m.moverWidget(conElGrafico, G("speed"), 0);
  assert.strictEqual(movido[0].id, G("speed"));

  // se apaga el canal: el catalogo ya no lo nombra
  const apagado = m.reconciliarDisposicion(JSON.stringify(movido), CAT([]));
  assert.strictEqual(apagado[0].id, G("speed"), "perdio su sitio al apagarse");

  // y se vuelve a encender
  const vuelto = m.reconciliarDisposicion(JSON.stringify(apagado), CAT(["speed"]));
  assert.strictEqual(vuelto[0].id, G("speed"), "no volvio a su sitio");
  assert.strictEqual(new Set(vuelto.map(w => w.id)).size, vuelto.length,
    "quedo duplicado al volver");
});

prueba("un panel declarado que ya no existe si se descarta", () => {
  /* La otra cara de la regla de arriba, y la que la hace mordible: un grafico
     apagado vuelve, un panel borrado del codigo no. Sin esta, «conservar lo que
     el catalogo no nombra» seria conservar cualquier cosa para siempre. */
  const d = m.reconciliarDisposicion(
    JSON.stringify([{ id: "panel-que-ya-no-existe", ancho: 1, alto: 1, visible: true }]),
    CAT([]));
  assert.ok(!d.some(w => w.id === "panel-que-ya-no-existe"));
});

prueba("quitar un grafico no hace nada, ni siquiera en la operacion", () => {
  /* La puerta se cierra en `mostrarWidget` y no solo en el boton. Con la
     operacion abierta, la bandeja de quitados podia listar un grafico que la
     reconciliacion vuelve a mostrar en la proxima lectura: un boton que promete
     algo que se deshace solo. */
  const cat = CAT(["speed"]);
  const d = m.reconciliarDisposicion(null, cat);
  const tras = m.mostrarWidget(d, G("speed"), false);
  assert.strictEqual(tras.find(w => w.id === G("speed")).visible, true,
    "la operacion escondio un grafico");
  // Y a un panel declarado si lo esconde: si no, esta prueba pasaria con
  // `mostrarWidget` devolviendo siempre lo que recibe.
  const panel = m.mostrarWidget(d, m.WIDGETS[0].id, false);
  assert.strictEqual(panel.find(w => w.id === m.WIDGETS[0].id).visible, false,
    "dejo de poder quitarse un panel declarado");
});

prueba("una disposicion guardada no puede dejar un grafico escondido", () => {
  /* La segunda puerta, y hace falta aunque la operacion ya se niegue: lo
     guardado viene del pasado. Una disposicion escrita por una version que si
     dejaba esconderlos ---o editada a mano--- traeria `visible: false` sobre un
     grafico, y entonces el canal estaria encendido en el panel «Señales» y su
     grafico no estaria en ningun lado, sin forma de traerlo desde ninguno de
     los dos sitios. */
  const cat = CAT(["speed"]);
  const guardada = m.reconciliarDisposicion(null, cat)
    .map(w => w.id === G("speed") ? { ...w, visible: false } : w);
  assert.strictEqual(guardada.find(w => w.id === G("speed")).visible, false,
    "el caso de prueba no tiene el grafico escondido, y entonces no prueba nada");
  const releido = m.reconciliarDisposicion(JSON.stringify(guardada), cat);
  assert.strictEqual(releido.find(w => w.id === G("speed")).visible, true,
    "un grafico quedo escondido por la disposicion");
  // Y un panel declarado si conserva su «quitado»: esconder no es olvidar.
  const panel = m.reconciliarDisposicion(JSON.stringify(
    guardada.map(w => w.id === m.WIDGETS[0].id ? { ...w, visible: false } : w)), cat);
  assert.strictEqual(panel.find(w => w.id === m.WIDGETS[0].id).visible, false,
    "la reconciliacion dejo de recordar un panel quitado");
});

prueba("un grafico nuevo entra con los graficos, no debajo de la barra de señales", () => {
  /* Encender un canal crea su grafico. Pegado al final de la disposicion caia
     **debajo de la barra de señales**, que es el pie del tablero y ocupa las
     cuatro columnas: el grafico quedaba solo al fondo y habia que arrastrarlo
     cada vez. Un panel que la disposicion no nombra entra donde el catalogo lo
     declara, no siempre ultimo. */
  const conDos = m.reconciliarDisposicion(null, CAT(["speed", "gas"]));
  const guardado = JSON.stringify(conDos);
  const conTres = m.reconciliarDisposicion(guardado, CAT(["speed", "gas", "drs"]));
  const puestos = ids(conTres);
  const pie = puestos.indexOf("senales");
  assert.ok(pie >= 0, "no esta la barra de señales");
  assert.ok(puestos.indexOf(G("drs")) < pie,
    "el grafico nuevo quedo debajo del pie del tablero");
  assert.strictEqual(puestos[puestos.length - 1], "senales",
    "el pie del tablero dejo de ser el ultimo");
});

prueba("un grafico nace de una columna y dos filas", () => {
  /* Mas bajo que eso el trazo queda en una tira donde no se lee la forma, que
     es lo unico que un grafico tiene para decir de un vistazo. */
  const d = m.reconciliarDisposicion(null, CAT(["speed"]));
  const g = d.find(w => w.id === G("speed"));
  assert.strictEqual(g.ancho, m.MEDIDA_DE_UN_GRAFICO.ancho);
  assert.strictEqual(g.alto, m.MEDIDA_DE_UN_GRAFICO.alto);
});

prueba("restablecer devuelve exactamente la disposicion de fabrica", () => {
  /* El boton «Restablecer» es esto y nada mas: el borrador vuelve a lo que el
     codigo declara, incluidos los graficos que haya encendidos ahora ---que no
     estan en `WIDGETS` y se perderian si se restableciera contra la lista
     escrita en vez de contra el catalogo vigente---. */
  const cat = CAT(["speed", "gas"]);
  const fabrica = m.disposicionPorOmision(cat);
  assert.deepStrictEqual(fabrica.map(w => w.id), cat.map(w => w.id));
  for (const w of fabrica) assert.strictEqual(w.visible, true);
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
  assert.strictEqual(chico.ancho, m.PASO_DE_MEDIDA);
  assert.strictEqual(chico.alto, m.PASO_DE_MEDIDA);
});

prueba("el salto es de una unidad, y el mismo a lo ancho que a lo alto", () => {
  /* La grilla estuvo partida en dos y se volvio atras: con dos pistas por
     unidad, los catorce pixeles de hueco que quedan **entre** esas dos pistas
     caen adentro de la unidad, y una unidad medía 164 px contra los 150 que el
     modelo declara. Los tamaños dejaban de ser multiplos de lo declarado. */
  const d = orig(); const id = d[0].id;
  const r = m.redimensionarWidget(d, id, 2, 3).find(w => w.id === id);
  assert.strictEqual(r.ancho, 2);
  assert.strictEqual(r.alto, 3);
  assert.strictEqual(m.PASO_DE_MEDIDA, 1, "el salto dejo de ser de una unidad");
});

prueba("una medida fraccionaria se lleva a la unidad mas cercana", () => {
  /* El tirador entrega fracciones: arrastrar da 1,3 columnas, no 1. Un ancho de
     1,3 seria un panel colocado a un tercio de columna, con todos los de al lado
     corridos a la nada. Y las disposiciones guardadas mientras la grilla estuvo
     partida traen medios: se acotan al leerse, sin que nadie migre nada. */
  const d = orig(); const id = d[0].id;
  for (const [pedido, esperado] of [[1.3, 1], [1.6, 2], [0.5, 1], [2.26, 2], [0.2, 1]]) {
    const r = m.redimensionarWidget(d, id, pedido, pedido).find(w => w.id === id);
    assert.strictEqual(r.ancho, esperado, "pedi " + pedido + " y dio " + r.ancho);
    assert.strictEqual(r.alto, esperado);
    assert.ok(Number.isInteger(r.ancho), "quedo una medida que no es entera");
  }
});

prueba("una disposicion guardada con medios se lee en unidades enteras", () => {
  /* Quien haya ordenado su tablero mientras la grilla estuvo partida tiene
     medios guardados. No hay migracion: la reconciliacion los acota, y lo unico
     que se pierde es la media unidad que ya no existe. */
  const guardada = m.WIDGETS.map(w => ({ id: w.id, ancho: 1.5, alto: 0.5, visible: true }));
  const d = m.reconciliarDisposicion(JSON.stringify(guardada));
  for (const w of d) {
    assert.ok(Number.isInteger(w.ancho) && Number.isInteger(w.alto),
      w.id + " quedo en " + w.ancho + "x" + w.alto);
    assert.ok(w.ancho >= 1 && w.alto >= 1, w.id + " quedo por debajo de una unidad");
  }
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
