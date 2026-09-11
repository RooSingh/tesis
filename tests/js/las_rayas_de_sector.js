/* Donde y como cruza cada raya de sector sobre el trazado.
 *
 * CRITERIO. Como los demas arneses, la funcion se **extrae del `app.js` que se
 * publica** y se ejecuta; no se copia.
 *
 * POR QUE ESTE ARNES EXISTE. La primera version leia el resultado de
 * `proyectarMundo` como `.x` y `.y`, y esa funcion devuelve un **arreglo**
 * `[x, y]`. La resta daba `NaN`, `Math.hypot` daba `NaN`, y la guarda
 * `if (!largo) return` lo descartaba en silencio: cero rayas dibujadas, ningun
 * error en consola, y el resto del trazado ---las quince curvas--- pintandose
 * perfecto al lado. Hicieron falta tres vueltas de instrumentar el navegador
 * para encontrarlo. Una prueba que ejecute la funcion lo agarra en una.
 *
 * QUE SE COMPRUEBA. Geometria, que es lo unico que esta funcion decide:
 *
 * - que la raya **cruce** la pista y no corra a lo largo de ella. Puesta en
 *   cualquier direccion se lee como un tramo del circuito y no como un limite;
 * - que el limite que cae en el comienzo del dibujo no lleve raya, y que el
 *   motivo sea **donde cae** y no que sea el sector 1;
 * - que ninguna coordenada salga `NaN`, que es la forma que tuvo el defecto.
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

const linea = /const LARGO_RAYA_SECTOR = ([\d.]+);/.exec(fuenteApp);
if (!linea) throw new Error("no esta LARGO_RAYA_SECTOR en app.js");

const marcasDeSector = new Function(`
  ${linea[0]}
  ${extraer("marcasDeSector")}
  return marcasDeSector;
`)();

let hechas = 0;
function prueba(titulo, fn) {
  try { fn(); hechas++; }
  catch (e) {
    process.exitCode = 1;
    console.error("FALLA  " + titulo + "\n       " + (e && e.message));
  }
}

/* La proyeccion de verdad devuelve un arreglo `[x, y]`, y este doble tambien.
   Devolver un objeto aca habria hecho pasar la version defectuosa: un doble que
   no tiene la forma del original no comprueba nada. */
const proyectar = (px, py) => [px, py];

/* Una recta horizontal de cien puntos: la pista va hacia la derecha, asi que
   una raya que la cruce tiene que ser vertical. */
const rectaHorizontal = Array.from({ length: 100 }, (_, i) => [i, 50]);
const sectores = [
  { sector: 1, indice: 0, desde_m: 0 },
  { sector: 2, indice: 40, desde_m: 400 },
  { sector: 3, indice: 70, desde_m: 700 },
];

// ------------------------------------------------------- la raya cruza

prueba("la raya cruza la pista, no corre a lo largo de ella", () => {
  /* LA COMPROBACION QUE HABRIA AGARRADO EL DEFECTO. Con la lectura como objeto
     esto devolvia cero marcas y el `length` de abajo ya fallaba. */
  const m = marcasDeSector(sectores, rectaHorizontal, proyectar);
  assert.strictEqual(m.length, 2, "no se dibujo ninguna raya");
  m.forEach(r => {
    // Pista horizontal: la raya tiene que ser vertical.
    assert.ok(Math.abs(r.x2 - r.x1) < 1e-9,
              "la raya no es perpendicular a la pista: " + JSON.stringify(r));
    assert.ok(Math.abs(r.y2 - r.y1) > 0, "la raya tiene largo cero");
  });
});

prueba("ninguna coordenada sale NaN", () => {
  /* La forma exacta que tuvo el defecto: no explotaba, devolvia NaN y se
     descartaba solo. Un numero que no es un numero tiene que fallar la prueba,
     no desaparecer del dibujo. */
  const m = marcasDeSector(sectores, rectaHorizontal, proyectar);
  m.forEach(r => {
    ["x1", "y1", "x2", "y2", "tx", "ty"].forEach(k => {
      assert.ok(Number.isFinite(r[k]), k + " salio " + r[k] + " en " + JSON.stringify(r));
    });
  });
});

prueba("la raya queda centrada sobre el punto del limite", () => {
  const m = marcasDeSector(sectores, rectaHorizontal, proyectar);
  m.forEach(r => {
    assert.ok(Math.abs((r.x1 + r.x2) / 2 - 40) < 1e-9 ||
              Math.abs((r.x1 + r.x2) / 2 - 70) < 1e-9,
              "la raya no esta sobre su limite: " + JSON.stringify(r));
  });
});

prueba("la raya sigue el giro de la pista", () => {
  /* Una pista vertical pide una raya horizontal. Sin esto, una raya con
     direccion fija acierta en las rectas y miente en todo lo demas. */
  const vertical = Array.from({ length: 100 }, (_, i) => [50, i]);
  const m = marcasDeSector(sectores, vertical, proyectar);
  assert.strictEqual(m.length, 2);
  m.forEach(r => {
    assert.ok(Math.abs(r.y2 - r.y1) < 1e-9,
              "la raya no giro con la pista: " + JSON.stringify(r));
  });
});

// --------------------------------------------------- que no se dibuja

prueba("el limite que cae en el comienzo del dibujo no lleva raya", () => {
  /* Y el motivo es el comienzo, no el numero de sector: ahi el trazado empieza
     y termina, de modo que una raya marcaria el corte del lazo y no un limite.
     La distincion importa: si una fuente declarara el primer sector empezando
     en otro sitio, ahi si corresponde la raya. */
  const m = marcasDeSector(sectores, rectaHorizontal, proyectar);
  assert.deepStrictEqual(m.map(r => r.sector), [2, 3]);

  const corridos = [{ sector: 1, indice: 20, desde_m: 200 },
                    { sector: 2, indice: 60, desde_m: 600 }];
  assert.deepStrictEqual(
    marcasDeSector(corridos, rectaHorizontal, proyectar).map(r => r.sector), [1, 2],
    "se callo una raya por su numero de sector y no por donde cae");
});

prueba("un limite fuera del dibujo no se dibuja", () => {
  const m = marcasDeSector(
    [{ sector: 2, indice: 500, desde_m: 10 }], rectaHorizontal, proyectar);
  assert.deepStrictEqual(m, []);
});

prueba("sin proyeccion o sin puntos no se inventa nada", () => {
  assert.deepStrictEqual(marcasDeSector(sectores, rectaHorizontal, null), []);
  assert.deepStrictEqual(marcasDeSector(sectores, [], proyectar), []);
  assert.deepStrictEqual(marcasDeSector(sectores, [[0, 0]], proyectar), []);
  assert.deepStrictEqual(marcasDeSector(null, rectaHorizontal, proyectar), []);
});

prueba("dos puntos vecinos en el mismo sitio no dan una raya sin direccion", () => {
  /* Sin direccion no hay perpendicular, y la raya saldria degenerada o `NaN`.
     Se calla en vez de dibujar una marca que no significa nada. */
  const quieta = Array.from({ length: 100 }, () => [7, 7]);
  assert.deepStrictEqual(marcasDeSector(sectores, quieta, proyectar), []);
});

// -------------------------------------------------------- el rotulo

prueba("el rotulo va fuera de la raya y del mismo lado", () => {
  /* Puesto sobre el trazo lo tapa; puesto de cualquier lado, dos rotulos de
     sectores contiguos pueden caer uno a cada lado y se leen como dos cosas
     distintas. */
  const m = marcasDeSector(sectores, rectaHorizontal, proyectar);
  m.forEach(r => {
    const centro = (r.y1 + r.y2) / 2;
    assert.ok(Math.abs(r.ty - centro) > Math.abs(r.y2 - centro),
              "el rotulo cae dentro de la raya: " + JSON.stringify(r));
  });
  const lados = m.map(r => Math.sign(r.ty - (r.y1 + r.y2) / 2));
  assert.strictEqual(new Set(lados).size, 1, "los rotulos caen de lados distintos");
});

prueba("cada raya conserva su sector y su metro", () => {
  /* El metro viaja para poder decirlo al apuntar la raya. Que viaje en nulo es
     valido ---la fuente deportiva no mide metros--- y lo que no puede pasar es
     que se invente uno. */
  const m = marcasDeSector(sectores, rectaHorizontal, proyectar);
  assert.deepStrictEqual(m.map(r => r.desde_m), [400, 700]);
  const sinMetro = marcasDeSector(
    [{ sector: 1, indice: 0, desde_m: null }, { sector: 2, indice: 40, desde_m: null }],
    rectaHorizontal, proyectar);
  assert.deepStrictEqual(sinMetro.map(r => r.desde_m), [null]);
});

console.log(hechas + " pruebas de las rayas de sector: " +
            (process.exitCode ? "hubo fallos" : "OK"));
