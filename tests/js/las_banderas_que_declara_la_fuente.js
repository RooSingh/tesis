/* Dos listas en un panel, y cada entrada dice de donde sale.
 *
 * CRITERIO. Como los demas arneses, las funciones se **extraen del `app.js` que
 * se publica** y se ejecutan; no se copian.
 *
 * POR QUE SON DOS LISTAS Y NO UNA. `/avisos` declara en su propia respuesta que
 * cada entrada salio de aplicar una regla con un umbral sobre la telemetria, y
 * cuenta cuantas reglas evaluo. Una bandera de control de carrera no se derivo
 * de nada: la fuente la declaro. Meterlas en la misma ruta dejaria ese
 * `criterio` mintiendo para la mitad de las entradas y `reglas_evaluadas`
 * contando reglas que no evaluaron nada.
 *
 * Es la misma distincion que el proyecto ya cuida en otros sitios: el catalogo
 * de curvas declara que el nombre es anotacion y el metro es medicion; el
 * reglaje distingue lo observado de lo asentado.
 *
 * Asi que viajan por rutas distintas y se juntan al dibujar, que es donde verlas
 * juntas sirve. Lo que no se pierde al juntarlas es de donde sale cada una.
 *
 * LO QUE HAY EN LA SESION 9947: 158 eventos, de los cuales 89 son banderas
 * ---32 amarillas, 12 dobles, 41 de pista libre, 1 azul, la verde y la de
 * cuadros--- mas 8 de coche de seguridad y 4 de DRS.
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
  const i = fuenteApp.indexOf("const " + nombre + " =");
  if (i === -1) throw new Error("no esta la constante " + nombre);
  const fin = fuenteApp.indexOf("};", i);
  if (fin === -1) throw new Error("no cierra la constante " + nombre);
  return fuenteApp.slice(i, fin + 2);
}

const vueltas = [
  { numero: 1, desde_utc: "2025-07-06T14:03:49.615Z", hasta_utc: "2025-07-06T14:05:35.749Z" },
  { numero: 2, desde_utc: "2025-07-06T14:05:35.748Z", hasta_utc: "2025-07-06T14:07:51.346Z" },
];

const sacadas = new Function("estado", `
  ${constante("GRAVEDAD_DE_LA_BANDERA")}
  ${constante("GRAVEDAD_DE_LA_CATEGORIA")}
  ${extraer("nivelDelControl")}
  ${extraer("vueltaDelInstante")}
  ${extraer("avisoDeControlDeCarrera")}
  ${extraer("avisosDelControlDeCarrera")}
  ${extraer("procedenciaDelAviso")}
  ${extraer("avisosDeLaFuente")}
  return { GRAVEDAD_DE_LA_BANDERA, nivelDelControl, vueltaDelInstante,
           avisoDeControlDeCarrera, avisosDelControlDeCarrera,
           procedenciaDelAviso, avisosDeLaFuente };
`);

const estado = { vueltas: vueltas, avisos: [], controlDeCarrera: [] };
const m = sacadas(estado);

let hechas = 0;
function prueba(titulo, fn) {
  try { fn(); hechas++; }
  catch (e) {
    process.exitCode = 1;
    console.error("FALLA  " + titulo + "\n       " + (e && e.message));
  }
}

const evento = (extra) => Object.assign({
  instante: "2025-07-06T14:04:30Z", driver_number: null, lap_number: 1,
  category: "Flag", flag: null, scope: "Track", message: "un mensaje", sector: null,
}, extra || {});

// --------------------------------------------------------- que tan grave es

prueba("cada bandera tiene su gravedad, y esta escrita con su motivo", () => {
  Object.keys(m.GRAVEDAD_DE_LA_BANDERA).forEach(bandera => {
    const d = m.GRAVEDAD_DE_LA_BANDERA[bandera];
    assert.ok(["critico", "alerta", "ok", "info"].includes(d.nivel), bandera);
    assert.ok(d.porque && d.porque.length > 8,
              "la bandera " + bandera + " no dice por que es de ese nivel");
  });
});

prueba("la doble amarilla pesa mas que la amarilla", () => {
  assert.strictEqual(m.nivelDelControl(evento({ flag: "DOUBLE YELLOW" })), "critico");
  assert.strictEqual(m.nivelDelControl(evento({ flag: "YELLOW" })), "alerta");
});

prueba("la verde y la de pista libre no alarman", () => {
  assert.strictEqual(m.nivelDelControl(evento({ flag: "GREEN" })), "ok");
  assert.strictEqual(m.nivelDelControl(evento({ flag: "CLEAR" })), "ok");
});

prueba("la azul no es una alarma, es una instruccion", () => {
  /* Le avisa a un piloto que va a ser doblado. Pintarla de rojo diria que pasa
     algo peligroso en pista, y no es eso lo que dice. */
  assert.strictEqual(m.nivelDelControl(evento({ flag: "BLUE" })), "info");
});

prueba("la de cuadros cierra la sesion, no alerta de nada", () => {
  assert.strictEqual(m.nivelDelControl(evento({ flag: "CHEQUERED" })), "info");
});

prueba("el coche de seguridad alerta aunque no traiga bandera", () => {
  assert.strictEqual(m.nivelDelControl(evento({ category: "SafetyCar", flag: null })), "alerta");
});

prueba("una categoria desconocida no se pinta de grave", () => {
  /* Ante algo que este tablero no sabe leer, lo unico defendible es mostrarlo
     sin decir que tan grave es. */
  assert.strictEqual(m.nivelDelControl(evento({ category: "AlgoNuevo", flag: null })), "info");
  assert.strictEqual(m.nivelDelControl(evento({ category: null, flag: "NARANJA" })), "info");
  assert.strictEqual(m.nivelDelControl(null), "info");
});

// ------------------------------------------------- en que vuelta cae un hecho

prueba("un evento se ubica por su instante, no por la vuelta que declara", () => {
  /* La numeracion del control de carrera es de la sesion y arranca antes de la
     largada: los primeros eventos de Silverstone dicen «vuelta 1» a las 13:19,
     cuarenta minutos antes de que la carrera empiece. */
  const a = m.avisoDeControlDeCarrera(evento({
    instante: "2025-07-06T14:06:30Z", lap_number: 1 }));
  assert.strictEqual(a.vuelta, 2, "se creyo el numero de vuelta de la fuente");
});

prueba("lo que pasa antes de la primera vuelta no se apila en el arranque", () => {
  /* Cuarenta minutos de preparativos no tienen donde ubicarse en una
     reproduccion que empieza con la vuelta 1. Ponerlos en la fraccion cero
     seria amontonarlos todos sobre la largada. */
  const lista = m.avisosDelControlDeCarrera([
    evento({ instante: "2025-07-06T13:19:04Z", message: "AWNINGS MAY BE USED" }),
    evento({ instante: "2025-07-06T14:04:30Z", message: "YELLOW IN SECTOR 7", flag: "YELLOW" }),
    evento({ instante: "2025-07-06T18:00:00Z", message: "despues del final" }),
  ]);
  assert.strictEqual(lista.length, 1);
  assert.strictEqual(lista[0].que, "YELLOW IN SECTOR 7");
});

prueba("un instante que no se puede leer no ubica nada", () => {
  assert.strictEqual(m.vueltaDelInstante("no es una fecha"), null);
  assert.strictEqual(m.vueltaDelInstante(null), null);
});

// ---------------------------------------------------------- la forma del aviso

prueba("el detalle junta bandera, alcance y sector", () => {
  const a = m.avisoDeControlDeCarrera(evento({
    flag: "YELLOW", scope: "Sector", sector: 7 }));
  assert.strictEqual(a.detalle, "YELLOW · Sector · sector 7");
});

prueba("lo que la fuente no trae no se rellena", () => {
  /* Un hecho declarado no tiene umbral ni valor medido. Escribirle uno seria
     darle el respaldo de una medicion que nadie hizo. */
  const a = m.avisoDeControlDeCarrera(evento({ flag: "GREEN", scope: null }));
  assert.strictEqual(a.umbral, undefined);
  assert.strictEqual(a.valor, undefined);
  assert.strictEqual(a.metro, null);
  assert.strictEqual(a.detalle, "GREEN");
});

prueba("un evento sin mensaje cae en su categoria y no en una cadena vacia", () => {
  const a = m.avisoDeControlDeCarrera(evento({ message: null, category: "SafetyCar" }));
  assert.strictEqual(a.que, "SafetyCar");
});

// ------------------------------------------------------------- la procedencia

prueba("un hecho declarado y una medicion no dicen lo mismo de si mismos", () => {
  const declarado = m.procedenciaDelAviso(
    { origen: "declarado", canal: "race_control" });
  const derivado = m.procedenciaDelAviso(
    { canal: "wheel_slip_ratio_rear_left", umbral: 0.35 });
  assert.ok(/[Dd]eclarado por la fuente/.test(declarado), declarado);
  assert.ok(/no se derivó de la telemetría/i.test(declarado), declarado);
  /* Nombrar el umbral para decir que **no lo hubo** es justamente lo que se
     quiere; lo que no puede aparecer es una cifra de umbral, que le daria el
     respaldo de una medicion. */
  assert.ok(!/umbral\s+[-\d]/.test(declarado),
            "a un hecho declarado se le escribio una cifra de umbral: " + declarado);
  assert.ok(/[Dd]erivado de la telemetr/.test(derivado), derivado);
  assert.ok(/umbral 0\.35/.test(derivado), derivado);
});

prueba("una medicion sin umbral no inventa la palabra umbral", () => {
  const t = m.procedenciaDelAviso({ canal: "speed" });
  assert.ok(!/umbral/.test(t), t);
  assert.ok(/canal speed/.test(t), t);
});

// -------------------------------------------------------- las dos, mezcladas

prueba("las dos listas se ven juntas y en orden", () => {
  estado.avisos = [{ que: "derivado", en: 0.5, canal: "glat" }];
  estado.controlDeCarrera = [
    { que: "bandera tarde", en: 0.9, origen: "declarado" },
    { que: "bandera temprano", en: 0.1, origen: "declarado" },
  ];
  assert.deepStrictEqual(m.avisosDeLaFuente().map(a => a.que),
    ["bandera temprano", "derivado", "bandera tarde"]);
});

prueba("sin control de carrera, la lista derivada se entrega tal cual", () => {
  /* Y se entrega **la misma**, no una copia ordenada: la fuente que no tiene
     control de carrera no paga el costo de mezclar nada. */
  const derivados = [{ que: "uno", en: 0.5 }];
  estado.avisos = derivados;
  estado.controlDeCarrera = [];
  assert.strictEqual(m.avisosDeLaFuente(), derivados);
});

console.log(hechas + " pruebas de las banderas declaradas: " +
            (process.exitCode ? "hubo fallos" : "OK"));
