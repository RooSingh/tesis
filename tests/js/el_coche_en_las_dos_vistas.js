/* Donde esta el coche, en el panel chico y en la vista ampliada.
 *
 * CRITERIO. Como los demas arneses, las funciones se **extraen del `app.js` que
 * se publica** y se ejecutan; no se copian.
 *
 * QUE PASABA, REPORTADO EL 2026-09-13. Transmitiendo en vivo desde F1 25, con
 * la vista ampliada del trazado abierta, **el coche dejaba de moverse**. Al
 * cerrarla, el mismo coche en el widget chico se movia bien.
 *
 * POR QUE. Los dos resolvian la posicion por su cuenta y solo uno sabia del
 * vivo. El chico probaba, en orden: la ultima coordenada del mundo que publico
 * el flujo, el punto del recorrido derivado, y las coordenadas guardadas. La
 * vista ampliada probaba **solo la tercera**, y en vivo esa no existe: el
 * instante compartido vale `null` mientras se transmite. De ahi caia en la
 * fraccion del camino, y esa fraccion **esta fijada en uno** mientras el
 * circuito se esta midiendo ---`PISTA.enConstruccion`--- porque el trazo
 * termina donde esta el coche. Resultado: clavado en la punta.
 *
 * Es el mismo defecto que este tablero ya tuvo con `estado.clima`, con el pie
 * de avisos y con el constructor de la pista: dos sitios resolviendo el mismo
 * dato y uno quedandose viejo. El arreglo es el mismo: un solo sitio.
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

/* El banco: la funcion publicada, con el estado de modulo del que depende
   puesto desde afuera. `PISTA` y `vivo` se leen en tiempo de llamada. */
function banco(estado) {
  return new Function(
    "PISTA", "vivo", "puntoDelBusEn", "puntoMedidoDe",
    extraer("puntoMedidoDelCoche") + "\nreturn puntoMedidoDelCoche;")(
    estado.PISTA || {},
    estado.vivo || { posicionMundo: new Map() },
    estado.puntoDelBusEn || (() => null),
    estado.puntoMedidoDe || (() => null));
}

let hechas = 0;
function prueba(nombre, fn) {
  try { fn(); hechas++; } catch (e) {
    process.exitCode = 1;
    console.error("FALLA  " + nombre + "\n       " + (e && e.message));
  }
}

//: Una proyeccion cualquiera, la misma que dibujo el camino. Lo que importa es
//: que la posicion del mundo pase por ella y no por otra.
const PROYECTAR = (x, z) => [x * 2, z * 3];

prueba("EL DEFECTO: en vivo, la posicion sale del flujo y no del camino", () => {
  /* Mientras el circuito se mide, esto es lo unico que ubica al coche: las
     coordenadas guardadas todavia no existen y la fraccion vale uno. */
  const p = banco({
    PISTA: { proyectarMundo: PROYECTAR, enConstruccion: true },
    vivo: { posicionMundo: new Map([["car:0", [10, 20]]]) },
  })("car:0", null);
  assert.deepStrictEqual(p, { x: 20, y: 60 },
    "en vivo no se usa la ultima posicion publicada");
});

prueba("y tambien con el circuito ya congelado en vivo", () => {
  /* Al cerrar la primera vuelta el camino deja de crecer, pero la posicion
     sigue llegando veinte veces por segundo. */
  const p = banco({
    PISTA: { proyectarMundo: PROYECTAR, medidoEnVivo: true, enConstruccion: false },
    vivo: { posicionMundo: new Map([["car:0", [1, 1]]]) },
  })("car:0", null);
  assert.deepStrictEqual(p, { x: 2, y: 3 });
});

prueba("sin instante compartido, que es el caso del vivo, igual hay posicion", () => {
  /* `calcularInstante` devuelve `tUtcMs: null` mientras se transmite. La rama
     que fallaba era justamente la que necesita ese instante. */
  const p = banco({
    PISTA: { proyectarMundo: PROYECTAR, enConstruccion: true },
    vivo: { posicionMundo: new Map([["car:0", [3, 4]]]) },
  })("car:0", null);
  assert.ok(p, "sin instante se quedo sin posicion, que es el defecto entero");
});

prueba("cada coche va donde se midio el suyo", () => {
  /* Es lo unico que separa a varios vehiculos: la fraccion de vuelta es la
     misma para todos, de modo que sin esto se dibujan en el mismo punto. */
  const estado = {
    PISTA: { proyectarMundo: PROYECTAR, enConstruccion: true },
    vivo: { posicionMundo: new Map([["car:0", [1, 1]], ["car:19", [5, 5]]]) },
  };
  assert.deepStrictEqual(banco(estado)("car:0", null), { x: 2, y: 3 });
  assert.deepStrictEqual(banco(estado)("car:19", null), { x: 10, y: 15 });
});

prueba("un coche del que no llego posicion no toma la de otro", () => {
  const p = banco({
    PISTA: { proyectarMundo: PROYECTAR, enConstruccion: true },
    vivo: { posicionMundo: new Map([["car:0", [1, 1]]]) },
  })("car:19", null);
  assert.strictEqual(p, null, "se le presto la posicion de otro vehiculo");
});

prueba("sobre un recorrido derivado manda el punto de su instante", () => {
  /* El bus: el camino se reconstruye integrando, y una fraccion de tiempo
     sobre un camino parametrizado por longitud solo coincide con velocidad
     constante. */
  const p = banco({
    PISTA: { derivado: true },
    puntoDelBusEn: t => (t === 1234 ? { x: 7, y: 8 } : null),
  })("car:0", 1234);
  assert.deepStrictEqual(p, { x: 7, y: 8 });
});

prueba("y en histórico, las coordenadas guardadas", () => {
  const p = banco({
    PISTA: { proyectarMundo: PROYECTAR },
    puntoMedidoDe: (clave, t) => (clave === "car:0" && t === 99 ? { x: 1, y: 2 } : null),
  })("car:0", 99);
  assert.deepStrictEqual(p, { x: 1, y: 2 });
});

prueba("SIN NINGUNA MEDICION DEVUELVE NULO, y no un punto inventado", () => {
  /* Quien llama coloca entonces por fraccion **y lo declara**: una posicion
     supuesta y una medida no pueden verse igual. */
  assert.strictEqual(banco({ PISTA: {} })("car:0", null), null);
  assert.strictEqual(
    banco({ PISTA: { proyectarMundo: PROYECTAR, enConstruccion: true },
            vivo: { posicionMundo: new Map() } })("car:0", null), null);
});

prueba("sin proyeccion no se coloca por coordenadas del mundo", () => {
  /* Usar otra transformacion pondria al coche fuera de su propio trazo. */
  const p = banco({
    PISTA: { enConstruccion: true },
    vivo: { posicionMundo: new Map([["car:0", [10, 20]]]) },
  })("car:0", null);
  assert.strictEqual(p, null);
});

/* -------- y las dos vistas tienen que preguntarle a ella -------- */

prueba("LAS DOS VISTAS RESUELVEN LA POSICION EN EL MISMO SITIO", () => {
  /* Si una de las dos vuelve a resolverla por su cuenta, vuelve el defecto:
     dos posiciones distintas para el mismo instante son el tablero
     contandose dos cosas. */
  const grande = fuenteApp.indexOf("function moverCochesDelTrazadoGrande(");
  assert.notStrictEqual(grande, -1, "no esta moverCochesDelTrazadoGrande");
  const cuerpoGrande = fuenteApp.slice(grande, fuenteApp.indexOf("\n}", grande));
  assert.ok(/puntoMedidoDelCoche\(/.test(cuerpoGrande),
    "la vista ampliada volvio a resolver la posicion por su cuenta");

  const chico = fuenteApp.indexOf("let medidaDeVerdad = false;");
  assert.notStrictEqual(chico, -1, "no esta la colocacion del panel chico");
  const cuerpoChico = fuenteApp.slice(chico, chico + 700);
  assert.ok(/puntoMedidoDelCoche\(/.test(cuerpoChico),
    "el panel chico dejo de usar el sitio compartido");
  assert.ok(!/vivo\.posicionMundo\.get/.test(cuerpoChico),
    "el panel chico volvio a tener su propia copia de la rama del vivo");
});

console.log("ok " + hechas + " pruebas del coche en las dos vistas");
