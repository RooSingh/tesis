/* Que la lista de avisos diga lo mismo en vivo y en reproduccion.
 *
 * CRITERIO. Como los demas arneses, las funciones se **extraen del `app.js`
 * que se publica** y se ejecutan; no se copian.
 *
 * QUE PASABA. En vivo, todos los avisos entraban con `en: 1` ---una constante,
 * no una medicion---. El panel ordena por `en` de mayor a menor; con todos
 * empatados el orden de `sort` es estable y quedaba **el de insercion**, o sea
 * **el mas viejo arriba**. Y la insignia «NUEVO» no significa nuevo: es
 * `i === 0`. De modo que el primer aviso de la sesion se quedaba arriba
 * rotulado NUEVO para siempre y los que llegaban despues caian abajo.
 *
 * En reproduccion el mismo dato se ordena bien, porque ahi si se calcula el
 * instante. Las dos listas mostraban los dos extremos de la misma coleccion:
 * misma cuenta ---36 leves, 60 de 60--- y contenido visible opuesto.
 *
 * DE DONDE SALE EL ARREGLO. El instante ya estaba: el anotador escribe
 * `reloj_s` en cada anotacion (`backend/anotador_vivo.py:837`) y es epoca Unix
 * de verdad ---`_segundos` la obtiene con `.timestamp()`---. La reproduccion lo
 * convierte a `instante` (`backend/api_sesion.py:3903`). El camino vivo lo
 * recibia y **lo tiraba**: solo lo usaba para armar un identificador.
 *
 * ASI QUE NO SE INVENTA UN ORDEN: se deja de descartar el que ya venia.
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

const cuandoOcurrio = new Function(`${extraer("cuandoOcurrio")} return cuandoOcurrio;`)();
const conMayusculaInicial = new Function(
  `${extraer("conMayusculaInicial")} return conMayusculaInicial;`)();
const rotuloDeCuando = new Function(`${extraer("rotuloDeCuando")} return rotuloDeCuando;`)();
const masNuevoPrimero = new Function(`
  ${extraer("cuandoOcurrio")}
  ${extraer("masNuevoPrimero")}
  return masNuevoPrimero;
`)();

let hechas = 0;
function prueba(nombre, fn) { fn(); hechas++; }

const T0 = Date.parse("2026-09-12T04:12:10.000Z");
const enT = s => new Date(T0 + s * 1000).toISOString();

prueba("un aviso sin instante no finge tener uno", () => {
  assert.strictEqual(cuandoOcurrio({ en: 0.5 }), null);
  assert.strictEqual(cuandoOcurrio({ instante: null, en: 0.5 }), null);
  assert.strictEqual(cuandoOcurrio({ instante: "no es una fecha" }), null);
});

prueba("con instante se devuelve el milisegundo medido", () => {
  assert.strictEqual(cuandoOcurrio({ instante: enT(0) }), T0);
  assert.strictEqual(cuandoOcurrio({ instante: enT(37) }), T0 + 37000);
});

prueba("EL DEFECTO: en vivo todos empatados quedaban en orden de llegada", () => {
  /* Los tres avisos de la captura de Shanghai, en el orden en que llegaron.
     Con `en: 1` para los tres, el orden resultante era este mismo ---el mas
     viejo primero--- y «impacto vertical» se quedaba arriba. */
  const vivos = [
    { que: "impacto vertical", en: 1, instante: enT(10) },
    { que: "aleron movil en camino", en: 1, instante: enT(40) },
    { que: "aleron movil habilitado", en: 1, instante: enT(70) },
  ];
  const orden = vivos.slice().sort(masNuevoPrimero).map(a => a.que);
  assert.strictEqual(orden[0], "aleron movil habilitado",
    "el mas viejo sigue arriba: " + orden.join(" | "));
  assert.deepStrictEqual(orden,
    ["aleron movil habilitado", "aleron movil en camino", "impacto vertical"]);
});

prueba("la reproduccion de esos mismos avisos da el mismo orden", () => {
  /* LA PRUEBA QUE DA SENTIDO A TODAS LAS DEMAS. El mismo hecho, llegado por
     los dos caminos, tiene que quedar en el mismo sitio de la lista. En
     reproduccion los avisos traen ademas `en` ---la fraccion de sesion--- y
     eso no debe cambiar el resultado. */
  const reproducidos = [
    { que: "aleron movil habilitado", en: 0.70, instante: enT(70) },
    { que: "impacto vertical", en: 0.10, instante: enT(10) },
    { que: "aleron movil en camino", en: 0.40, instante: enT(40) },
  ];
  const vivos = [
    { que: "impacto vertical", en: 1, instante: enT(10) },
    { que: "aleron movil en camino", en: 1, instante: enT(40) },
    { que: "aleron movil habilitado", en: 1, instante: enT(70) },
  ];
  assert.deepStrictEqual(
    reproducidos.slice().sort(masNuevoPrimero).map(a => a.que),
    vivos.slice().sort(masNuevoPrimero).map(a => a.que),
    "el mismo hecho cae en distinto sitio segun por donde haya llegado");
});

prueba("sin instante se sigue ordenando por la fraccion de sesion", () => {
  /* No todo aviso tiene instante: el del control de carrera puede no traerlo.
     Perder ese orden para arreglar el otro seria cambiar un defecto por otro. */
  const l = [{ que: "a", en: 0.2 }, { que: "c", en: 0.9 }, { que: "b", en: 0.5 }];
  assert.deepStrictEqual(l.slice().sort(masNuevoPrimero).map(a => a.que),
                         ["c", "b", "a"]);
});

prueba("uno con instante y otro sin el no se comparan por unidades distintas", () => {
  /* Un milisegundo de epoca y una fraccion entre cero y uno no son
     comparables. Mezclarlos pondria cualquier aviso con instante por encima de
     todos los demas, que es una diferencia de unidad disfrazada de orden. */
  const conInstante = { que: "con", en: 0.1, instante: enT(0) };
  const sinInstante = { que: "sin", en: 0.9 };
  const orden = [conInstante, sinInstante].sort(masNuevoPrimero).map(a => a.que);
  assert.deepStrictEqual(orden, ["sin", "con"],
    "se comparo un milisegundo contra una fraccion: " + orden.join(" | "));
});

prueba("dos avisos del mismo instante no se reordenan al azar", () => {
  const l = [{ que: "primero", en: 1, instante: enT(5) },
             { que: "segundo", en: 1, instante: enT(5) }];
  assert.deepStrictEqual(l.slice().sort(masNuevoPrimero).map(a => a.que),
                         ["primero", "segundo"]);
});

prueba("el rotulo sale de la vuelta que el aviso declara", () => {
  /* EL OTRO SITIO DONDE LAS DOS VISTAS NO COINCIDIAN. El rotulo decidia con
     `hayVueltas() && a.vuelta`, y `hayVueltas()` mira `estado.vueltas`, que en
     vivo esta vacio porque las vueltas se arman al guardar. Asi que el mismo
     aviso decia «Vuelta 5» en reproduccion y «Tramo» en vivo.

     Lo decide el aviso: el anotador le escribe su `lap_number` cuando lo hay.
     Un bus vehicular no tiene vueltas y sus avisos vienen sin ella, de modo
     que siguen diciendo «Tramo» sin necesidad de preguntarle a nadie mas. */
  assert.strictEqual(rotuloDeCuando({ vuelta: 5 }), "Vuelta 5");
  assert.strictEqual(rotuloDeCuando({ vuelta: 1 }), "Vuelta 1");
  assert.strictEqual(rotuloDeCuando({ vuelta: null }), "Tramo");
  assert.strictEqual(rotuloDeCuando({}), "Tramo");
});

prueba("la vuelta cero no se lee como ausencia de vuelta", () => {
  /* `a.vuelta ? ...` trata el cero como falso. No hay vuelta cero en una
     carrera, pero el contrarreloj numera desde la vuelta de salida y un cero
     dicho por la fuente es un dato, no un hueco. */
  assert.strictEqual(rotuloDeCuando({ vuelta: 0 }), "Vuelta 0");
});

prueba("el aviso se muestra con mayuscula inicial", () => {
  assert.strictEqual(conMayusculaInicial("fuera de pista"), "Fuera de pista");
  assert.strictEqual(conMayusculaInicial("perdida de tren trasero"),
                     "Perdida de tren trasero");
});

prueba("el que ya venia capitalizado no se toca", () => {
  /* El anotador escribe los incidentes en minuscula y los transitorios con
     mayuscula ---`backend/anotador_vivo.py:534`---, de modo que el panel
     mezclaba los dos estilos. Capitalizar no debe alterar los segundos. */
  assert.strictEqual(conMayusculaInicial("Aleron movil habilitado"),
                     "Aleron movil habilitado");
});

prueba("solo cambia la primera letra, no el resto", () => {
  /* «DRS ENABLED» y «CAR 87 (BEA) TIME 2:00.293 DELETED» llegan del control de
     carrera en mayuscula entera. Poner el resto en minuscula seria reescribir
     lo que la fuente declaro. */
  assert.strictEqual(conMayusculaInicial("DRS ENABLED"), "DRS ENABLED");
  assert.strictEqual(conMayusculaInicial("aleron movil DRS"), "Aleron movil DRS");
});

prueba("lo que no empieza con letra se deja como esta", () => {
  assert.strictEqual(conMayusculaInicial(""), "");
  assert.strictEqual(conMayusculaInicial("3 ruedas sobre asfalto"),
                     "3 ruedas sobre asfalto");
  assert.strictEqual(conMayusculaInicial(null), "");
  assert.strictEqual(conMayusculaInicial(undefined), "");
});

prueba("una acentuada se capitaliza igual", () => {
  assert.strictEqual(conMayusculaInicial("ángulo excesivo"), "Ángulo excesivo");
});

prueba("EL TEXTO DEL AVISO SE ESCAPA ANTES DE PONERLO EN LA PAGINA", () => {
  /* Este campo puede traer `message` del control de carrera de OpenF1, que es
     texto de una fuente externa, y se insertaba en el HTML **sin escapar** ---a
     diferencia del detalle de la linea de al lado, que si pasa por
     `textoSeguro`---. Se comprueba sobre el `app.js` publicado y no sobre una
     copia de la regla. */
  const i = fuenteApp.indexOf('<span class="que">');
  assert.notStrictEqual(i, -1, "no esta el renglon del texto del aviso");
  const renglon = fuenteApp.slice(i, i + 160);
  assert.ok(/textoSeguro\(/.test(renglon),
    "el texto del aviso no pasa por textoSeguro: " + renglon.split("\n")[0]);
  assert.ok(/conMayusculaInicial\(/.test(renglon),
    "el texto del aviso no se capitaliza: " + renglon.split("\n")[0]);
});

prueba("EL CAMINO VIVO GUARDA EL INSTANTE QUE RECIBE", () => {
  /* SE EJECUTA LA FUNCION DE PRODUCCION, no se comprueba la regla aparte. La
     mutacion que devolvia `null` en vez del instante **no mataba ninguna
     prueba**: todas las de arriba fabrican avisos que ya lo traen, y ninguna
     miraba el sitio donde se escribe. Es el mismo hueco que ya aparecio hoy
     con la ficha del circuito: el defecto estaba en quien emite el dato y las
     pruebas miraban a quien lo consume. */
  const anotaciones = new Map();
  const incorporar = new Function("vivo", "pedirPintado", "_firmaAvisos", `
    ${extraer("incorporarAnotacionViva")}
    return incorporarAnotacionViva;
  `)({ sesion: "s1", anotaciones: anotaciones }, () => {}, "");

  const reloj = 1789185130.5;   // epoca Unix, como la escribe el anotador
  incorporar({ vehiculo: "s1:car:0", titulo: "fuera de pista", nivel: "incidente",
               reloj_s: reloj, vuelta: 5, distancia_m: 782 });

  const guardado = anotaciones.get("s1:car:0")[0];
  assert.strictEqual(guardado.instante, new Date(reloj * 1000).toISOString(),
    "el instante que traia la anotacion no se guardo");
  assert.strictEqual(cuandoOcurrio(guardado), Math.round(reloj * 1000));
  assert.strictEqual(rotuloDeCuando(guardado), "Vuelta 5");
});

prueba("una anotacion sin reloj no inventa un instante", () => {
  const anotaciones = new Map();
  const incorporar = new Function("vivo", "pedirPintado", "_firmaAvisos", `
    ${extraer("incorporarAnotacionViva")}
    return incorporarAnotacionViva;
  `)({ sesion: "s1", anotaciones: anotaciones }, () => {}, "");
  incorporar({ vehiculo: "s1:car:0", titulo: "algo", nivel: "info" });
  assert.strictEqual(anotaciones.get("s1:car:0")[0].instante, null);
});

console.log("ok " + hechas + " pruebas de avisos en vivo y en reproduccion");
