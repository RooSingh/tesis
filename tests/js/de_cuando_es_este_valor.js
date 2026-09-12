/* Que tan fresco es un valor del contexto, y como se dice en pantalla.
 *
 * CRITERIO. Como los demas arneses, las funciones se **extraen del `app.js` que
 * se publica** y se ejecutan; no se copian.
 *
 * QUE CIERRA ESTO. El punto 1 de la lista pendiente pedia tres estados con
 * umbrales fijos de 10 y 30 segundos. Esa regla no existe: se reemplazo por una
 * tabla donde cada magnitud declara su cadencia, porque las de esta fuente se
 * publican cada 8, 60 y 336 segundos y un corte unico de treinta habria borrado
 * el clima **siempre** ---edad mediana 49 s--- y el puesto en cincuenta y uno de
 * cada sesenta instantes.
 *
 * De ahi salen cuatro estados y no tres, y el cuarto es el que el pliego
 * original no podia expresar: `held`. Una magnitud que la fuente publica **al
 * cambiar** no envejece entre cambios; entre dos publicaciones el valor no se
 * desconoce, es el mismo.
 *
 * LA AFIRMACION QUE ESTE ARNES DEFIENDE: **`held` no se atenua**. Atenuar
 * significa «desconfia un poco de esto», y un puesto sostenido no merece
 * desconfianza. Merece una aclaracion de cuando es.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");

const APP = path.join(__dirname, "..", "..", "dashboard", "app.js");
const ESTILOS = path.join(__dirname, "..", "..", "dashboard", "styles.css");
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
  const fin = fuenteApp.indexOf("\n};", i);
  if (fin === -1) throw new Error("no cierra la constante " + nombre);
  return fuenteApp.slice(i, fin + 3);
}

const m = new Function(`
  ${constante("FRESCURAS")}
  ${extraer("edadEnPalabras")}
  ${extraer("comoSeVe")}
  return { FRESCURAS, comoSeVe };
`)();

let hechas = 0;
function prueba(titulo, fn) {
  try { fn(); hechas++; }
  catch (e) {
    process.exitCode = 1;
    console.error("FALLA  " + titulo + "\n       " + (e && e.message));
  }
}

// ------------------------------------------------- lo que no se atenua

prueba("un valor sostenido NO se atenua", () => {
  /* LA PRUEBA QUE DEFIENDE LA DECISION. El puesto lo publica la fuente al
     cambiar: veintiocho muestras para cincuenta y dos vueltas. Entre dos
     cambios el puesto no se desconoce, es el mismo. Atenuarlo diria
     «desconfia», y no hay de que. */
  const v = m.comoSeVe("held", 222.6);
  assert.strictEqual(v.atenua, false, "se atenuo un dato que la fuente declaro");
  assert.strictEqual(v.estado, "held");
});

prueba("un valor actual no se atenua ni escribe su edad", () => {
  /* En el caso normal una edad al lado de cada numero es ruido permanente para
     decir que todo esta bien, y el tablero tiene ocho paneles. */
  const v = m.comoSeVe("current", 2.7);
  assert.strictEqual(v.atenua, false);
  assert.strictEqual(v.sufijo, "");
});

prueba("un valor viejo SI se atenua", () => {
  const v = m.comoSeVe("aged", 18);
  assert.strictEqual(v.atenua, true);
});

// ------------------------------------------------- cuando se dice la edad

prueba("el sostenido y el viejo dicen de cuando son", () => {
  /* Un estado sin su edad obliga a creerle al umbral sin poder juzgarlo. */
  assert.ok(/18/.test(m.comoSeVe("aged", 18).sufijo),
            "el viejo no dice su edad: " + m.comoSeVe("aged", 18).sufijo);
  assert.ok(/min|s/.test(m.comoSeVe("held", 222.6).sufijo),
            "el sostenido no dice su edad");
});

prueba("una edad que no se sabe no deja un texto a medias", () => {
  ["held", "aged"].forEach(e => {
    const v = m.comoSeVe(e, null);
    assert.ok(!/hace\s*$|,\s*$|·\s*$/.test(v.sufijo),
              e + " dejo un sufijo colgado: «" + v.sufijo + "»");
  });
});

prueba("el sostenido se distingue de un simple viejo sin leer el texto", () => {
  /* Un tablero se mira de reojo. Si los dos se vieran igual habria que leer
     para saber cual de los dos es, que es justamente lo que no se hace. */
  const h = m.comoSeVe("held", 100);
  const a = m.comoSeVe("aged", 20);
  assert.notStrictEqual(h.atenua, a.atenua);
});

prueba("el sostenido se marca aunque no se sepa su edad", () => {
  /* Y la marca no puede vivir en el texto: con la edad desconocida quedaba
     « ·» solo, un caracter suelto que no dice nada. Una marca que depende de
     que haya otro dato al lado no es una marca. La pone la hoja sobre
     `data-frescura`, que esta siempre. */
  const hoja = fs.readFileSync(ESTILOS, "utf8");
  assert.ok(/\[data-frescura="held"\]::after[^{]*\{[^}]*content/.test(hoja),
            "el sostenido no se marca desde la hoja");
});

// ------------------------------------------------- lo que no se dibuja

prueba("un valor no disponible no se atenua: no se muestra", () => {
  /* No se atenua porque no hay nada que atenuar: va una raya y el motivo.
     Nunca un cero, que afirmaria una medicion que nadie hizo. */
  const v = m.comoSeVe("unavailable", null);
  assert.strictEqual(v.atenua, false);
  assert.strictEqual(v.sufijo, "");
});

prueba("un estado que este tablero no conoce no se pinta de nada", () => {
  /* Ante algo que no sabe leer, lo unico defendible es mostrarlo sin afirmar
     nada sobre su frescura. */
  const v = m.comoSeVe("algo_nuevo", 5);
  assert.strictEqual(v.atenua, false);
  assert.strictEqual(v.sufijo, "");
  assert.strictEqual(m.comoSeVe(undefined, 5).atenua, false);
});

// ------------------------------------------------- la tabla y su estilo

prueba("los cuatro estados de la API estan contemplados", () => {
  /* Si la API declara un estado que esta tabla no tiene, ese valor se dibuja
     como si fuera actual y nadie se entera. */
  ["current", "aged", "held", "unavailable"].forEach(e => {
    assert.ok(Object.prototype.hasOwnProperty.call(m.FRESCURAS, e),
              "falta el estado " + e);
  });
});

prueba("solo uno de los cuatro atenua", () => {
  const atenuan = Object.keys(m.FRESCURAS).filter(k => m.FRESCURAS[k].atenua);
  assert.deepStrictEqual(atenuan, ["aged"],
    "atenuan " + JSON.stringify(atenuan) + ": el unico que corresponde es «aged»");
});

prueba("la hoja atenua por el atributo, y solo al viejo", () => {
  /* La marca la pone el guion en `data-frescura`; el que la dibuja es el estilo.
     Sin la regla, el estado viaja al DOM y no se ve. */
  const hoja = fs.readFileSync(ESTILOS, "utf8");
  assert.ok(/\[data-frescura="aged"\][^{]*\{[^}]*opacity/.test(hoja),
            "el viejo no se atenua en la hoja");
  assert.ok(!/\[data-frescura="held"\][^{]*\{[^}]*opacity/.test(hoja),
            "la hoja atenua el sostenido");
});

/* -------- el clima siempre dice de cuando es -------- */

prueba("un clima fresco tambien dice su edad", () => {
  /* POR QUE EL CLIMA ES LA EXCEPCION, Y ESTA MEDIDO. La regla general de
     `comoSeVe` es que la edad se escribe **solo cuando deja de ser obvia**: una
     edad al lado de cada numero es ruido permanente para decir que todo esta
     bien, y el tablero tiene ocho paneles.

     Pero el clima declara `vigente_s = 90` ---`CONTEXTOS_DE_CARRERA` en
     `backend/db.py`, «una muestra por minuto; noventa es una cadencia y
     media»---, de modo que un clima **`current` puede tener noventa segundos**
     y el panel no decia nada. Es la magnitud con el umbral mas flojo de las
     tres y la unica que nunca mostraba su edad: el puesto se publica al cambiar
     y siempre la dice, y el intervalo esta vigente solo diez segundos.

     Y la razon por la que ahi no es ruido: el panel de clima lo dice **una vez
     para las siete magnitudes**, no en cada casilla. Las siete vienen de la
     misma muestra. */
  const v = m.comoSeVe("current", 42, true);
  assert.ok(/42 s/.test(v.aclara), "un clima fresco no dice de cuando es: " + v.aclara);
  assert.strictEqual(v.estado, "current");
  assert.strictEqual(v.atenua, false, "decir la edad no es desconfiar del dato");
});

prueba("sin pedirlo, la regla general no cambia", () => {
  /* Los demas paneles siguen callando la edad cuando el valor esta vigente. Si
     esto cambiara, la edad aparecería junto a cada numero del tablero. */
  const v = m.comoSeVe("current", 42);
  assert.strictEqual(v.aclara, "");
  assert.strictEqual(v.sufijo, "");
});

prueba("una edad que no se sabe no se inventa", () => {
  /* `Number(null)` es cero: sin cuidado, un clima sin edad se anunciaria como
     «hace 0 s», que es la afirmacion contraria a no saber. */
  assert.strictEqual(m.comoSeVe("current", null, true).aclara, "");
  assert.strictEqual(m.comoSeVe("current", undefined, true).aclara, "");
  assert.strictEqual(m.comoSeVe("current", "", true).aclara, "");
});

prueba("los estados que ya decian su edad no cambian", () => {
  const a = m.comoSeVe("aged", 200), b = m.comoSeVe("aged", 200, true);
  assert.strictEqual(a.aclara, b.aclara);
  const h = m.comoSeVe("held", 3400), i = m.comoSeVe("held", 3400, true);
  assert.strictEqual(h.aclara, i.aclara);
});

prueba("sin dato no hay edad que declarar", () => {
  assert.strictEqual(m.comoSeVe("unavailable", 42, true).aclara, "");
});

prueba("el panel de clima lo pide", () => {
  /* Se comprueba sobre el `app.js` publicado: la opcion podia existir y el
     panel no usarla. */
  const i = fuenteApp.indexOf("const fClima = comoSeVe(");
  assert.notStrictEqual(i, -1, "no esta la frescura del clima");
  assert.ok(/true\s*\)/.test(fuenteApp.slice(i, i + 120)),
    "el clima no pide que se diga siempre de cuando es");
});


console.log(hechas + " pruebas de la frescura del contexto: " +
            (process.exitCode ? "hubo fallos" : "OK"));
