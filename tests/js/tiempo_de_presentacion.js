/* Un solo instante para todo el tablero, y es una marca de tiempo.
 *
 * CRITERIO. Como los demas arneses, las funciones se **extraen del `app.js`
 * que se publica** y se ejecutan; no se copian. Probar una reimplementacion
 * comprueba que la reimplementacion anda, que es justo lo que no interesa.
 *
 * EL DEFECTO QUE ESTO CUIDA. La marca del coche se interpolaba sobre instantes
 * medidos y todo lo demas se leia con `Math.round(fraccion * (muestras - 1))`.
 * A 300 puntos sobre una vuelta de Spa de 127 s cada escalon dura 425 ms: a 60
 * cuadros por segundo son veinticinco cuadros con la misma cifra mientras el
 * coche se mueve. Y como cada canal traia su propia cantidad de muestras, los
 * escalones de dos canales ni siquiera caian en el mismo sitio.
 *
 * Ademas habia una incoherencia de reloj: el transporte reparte la sesion con
 * `duracion_s`, que es la duracion **efectiva** ---la API descarta los huecos
 * de captura---, y `posicionesAhora` estiraba esa fraccion sobre la ventana UTC
 * **bruta** de la vuelta, que los incluye. Con un hueco de cinco segundos en el
 * medio, el coche y los instrumentos mostraban momentos distintos.
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

/* Las tablas del archivo, para no reescribirlas aca: `calcularInstante`
   pregunta por la unidad de lo que lee. */
function constante(nombre) {
  const i = fuenteApp.indexOf("const " + nombre + " =");
  if (i === -1) throw new Error("no esta la constante " + nombre);
  return fuenteApp.slice(i, fuenteApp.indexOf(";", i) + 1);
}

/* El estado del modulo que estas funciones leen, puesto en el ambito global:
   es lo que ve un cuerpo construido con `new Function`. */
globalThis.estadoSesion = "cargado";
globalThis.fuente = "f1";
globalThis.cabezal = 0;
globalThis.vueltaElegida = 1;
/* OJO: esto es una copia a mano de `const vivo` de `app.js`, y se desincroniza.
   Paso el 2026-09-12 al agregar `marcaDePosicion` y `velocidadAnterior`: el
   reset de produccion las limpia y aca no existian, de modo que fallaba con
   «Cannot read properties of undefined (reading 'clear')» ---un error que
   apunta al arnes y no al cambio---. `tests/js/aislamiento_de_sesiones.js`
   extrae el objeto de `app.js` en vez de copiarlo, y no tuvo el problema. */
globalThis.vivo = { series: new Map(), ultimos: new Map(), recorrido: new Map(),
                    marcaDePosicion: new Map(), velocidadAnterior: new Map(),
                    recorridoDibujado: 0 };
/* Lo minimo que `olvidarLoDeLaCorrida` ---el reset de produccion--- toca fuera
   del estado. Se lo deja hacer de verdad: sustituirlo por un reset propio es
   exactamente lo que impidio ver que no invalidaba las caches derivadas. */
globalThis.document = { getElementById: () => null };
globalThis.detener = () => {};
globalThis.olvidarCaches = () => { globalThis._instanteClave = null; };
globalThis.AUTOS = [];
globalThis.seleccion = new Set();
globalThis.CURVAS = [];
globalThis._esencialResuelta = false;
globalThis.PISTA = { largo_m: 7000 };
globalThis.HUECO_DE_CAPTURA_MS = 2000;
globalThis.EJE_DISTANCIA = " distancia";
globalThis.EJE_DISTANCIA_SESION = " distancia de sesion";
globalThis.EJE_TIEMPO = " tiempo";
globalThis._selloSeries = 0;
globalThis._selloDeLoArmado = -1;
globalThis._seriesArmadas = new Map();
globalThis._selloDeLoTemporal = -1;
globalThis._temporales = new Map();
globalThis._huboInterpolacion = false;
globalThis.SENAL_DE = {
  speed: "speed", throttle: "throttle_position", brake: "brake_position",
  rpm: "engine_speed", gear: "gear_selected", glong: "g_force_longitudinal",
  glat: "g_force_lateral", drs: "drs_open",
};
globalThis.SENAL_CAN = { throttle: "gas_pressed", brake: "brake_pressed" };
globalThis.SENAL_OPENF1 = { brake: "brake_applied", drs: "drs_state_code" };
/* `nombreDeSenal` tambien consulta la tabla del simulador. Copia a mano, como
   las demas de este arnes: ver la nota de `vivo` mas arriba. */
globalThis.SENAL_F1 = { posX: "world_position_x", posY: "world_position_z" };
globalThis.corrida = { adquisicion: null, fase: null, disponibles: null, mezclada: false };
globalThis.estado = { series: {}, posiciones: {}, vueltas: [], abierta: null, puesta: null };

const NOMBRES = [
  "numeroMedido", "nombreDeSenal", "recortarPorDominio",
  "esCanalEscalonado", "_cacheTemporal", "serieTemporal", "_serieTemporalCruda",
  "continuidadDeVuelta", "_umbralDeVuelta", "tiempoEfectivoEntre", "hayCorteEntre",
  "_antesDe", "valorContinuoEn", "valorEscalonadoEn", "abscisaContinua",
  "serieAcumuladaDeCanal", "tramoAcumuladoDeVuelta", "vueltasEnTramoAcumulado",
  "trazaContinua", "hayCorteEntreVueltas", "hayCorteEntreVentanas",
  "vueltaSiguienteDeclarada",
  "relojDeVuelta", "_armarRelojDeVuelta", "_tramosContinuos", "_tramosDeMuestras",
  "tiempoDePresentacion", "recortarConBordes",
  "unidadDeclaradaDe", "divisorDePresentacion", "estaEnLaUnidadQueSeMuestra",
  "divisorDeUnidad", "serieCrudaDeCanal", "_armarSerieDeCanal", "_enUnidad",
  "serieDeCanal", "claveVehiculoPropio", "duracionDeVuelta", "duracionSesionS",
  "vueltasDeLaSesion", "iniciosDeVuelta", "calcularInstante",
  "paresDePosicion", "posicionesAhora",
];
const sacadas = new Function(
  constante("UNIDAD_QUE_MUESTRA_EL_TABLERO") + "\n" +
  constante("DIVISOR_ENTRE_UNIDADES") + "\n" +
  "const _vistasVivas = new Map();\n" +
  NOMBRES.map(extraer).join("\n\n") +
  "\nreturn { " + NOMBRES.join(", ") + " };")();
const {
  serieTemporal, valorContinuoEn, valorEscalonadoEn, abscisaContinua,
  tiempoDePresentacion,
  relojDeVuelta, recortarConBordes, calcularInstante, posicionesAhora,
  esCanalEscalonado, _antesDe, continuidadDeVuelta, tiempoEfectivoEntre,
  serieAcumuladaDeCanal, tramoAcumuladoDeVuelta, vueltasEnTramoAcumulado,
  trazaContinua, vueltaSiguienteDeclarada,
} = sacadas;

/* `posicionesAhora` pregunta por el instante. Se lo damos: el de verdad, el que
   calcula `calcularInstante`. Asi la prueba de correspondencia compara al coche
   contra la velocidad **del mismo instante compartido**, que es lo que este
   trabajo tenia que lograr. */
globalThis.instante = () => calcularInstante();

let hechas = 0;
function prueba(titulo, fn) {
  try {
    fn();
    hechas++;
  } catch (e) {
    process.exitCode = 1;
    console.error("FALLA  " + titulo + "\n       " + (e && e.message));
  }
}

// ------------------------------------------------------------------ utilidad

const T0 = Date.parse("2026-09-05T00:38:00.000Z");
const iso = ms => new Date(ms).toISOString();

/* Deja cargada una vuelta como la entrega `/series`: columnas paralelas, con
   `timestamp_utc` y con los huecos en nulo. `marcas` son milisegundos desde
   `T0`. */
function cargarVuelta(numero, marcas, columnas, opciones) {
  const o = opciones || {};
  const veh = { timestamp_utc: marcas.map(m => (m === null ? null : iso(T0 + m))) };
  if (o.sinTiempos) delete veh.timestamp_utc;
  Object.keys(columnas).forEach(c => { veh[c] = columnas[c]; });
  globalThis.estado.series[numero] = {
    vuelta: numero, puntos_pedidos: 300,
    vehiculos: { "car:0": veh },
  };
  globalThis.estado.vehiculoClave = "car:0";
  globalThis._selloSeries++;
  return veh;
}

function declararVueltas(lista) {
  globalThis.estado.vueltas = lista;
}

function reiniciar() {
  globalThis.estado = { series: {}, posiciones: {}, vueltas: [],
                        abierta: null, puesta: null, vehiculoClave: "car:0" };
  globalThis._selloSeries++;
  globalThis.cabezal = 0;
  globalThis.fuente = "f1";
}

/* Una vuelta pareja de veinte muestras cada 100 ms: 1.900 ms de reloj, la
   velocidad subiendo de 200 a 238 km/h y la distancia de 0 a 95 m. */
function vueltaPareja() {
  reiniciar();
  const marcas = [], dist = [], vel = [], marcha = [];
  for (let i = 0; i < 20; i++) {
    marcas.push(i * 100);
    dist.push(i * 5);
    vel.push(200 + i * 2);
    marcha.push(i < 10 ? 4 : 5);
  }
  cargarVuelta(1, marcas, { distancia_m: dist, speed: vel, gear_selected: marcha });
  declararVueltas([{ numero: 1, duracion_s: 1.9,
                     desde_utc: iso(T0), hasta_utc: iso(T0 + 1900) }]);
  return { marcas, dist, vel };
}

// ------------------------------------------ interpolacion con reloj irregular

prueba("interpola entre dos muestras separadas de forma despareja", () => {
  reiniciar();
  cargarVuelta(1, [0, 100, 900, 1000],
               { distancia_m: [0, 10, 90, 100], speed: [100, 200, 300, 400] });
  const st = serieTemporal("speed", 1, "car:0");
  /* La mitad del tramo largo: 200 y 300 separados por 800 ms, a los 500 ms
     desde el arranque van 400 ms del tramo. Repartiendo por indice ---cuatro
     muestras, fraccion 0,5--- daria la muestra 2, es decir 300. */
  assert.strictEqual(valorContinuoEn(st, T0 + 500), 250);
  assert.strictEqual(valorContinuoEn(st, T0 + 100), 200);
  assert.strictEqual(valorContinuoEn(st, T0 + 950), 350);
});

prueba("el valor cambia entre dos muestras, no solo al cambiar de muestra", () => {
  /* Es la comprobacion del defecto tal cual se ve: dos instantes distintos
     dentro del mismo intervalo tienen que dar cifras distintas. Con el
     redondeo del indice daban la misma. */
  reiniciar();
  cargarVuelta(1, [0, 400], { distancia_m: [0, 20], speed: [100, 200] });
  const st = serieTemporal("speed", 1, "car:0");
  const a = valorContinuoEn(st, T0 + 100);
  const b = valorContinuoEn(st, T0 + 200);
  const c = valorContinuoEn(st, T0 + 300);
  assert.ok(a < b && b < c, "el valor no se mueve dentro del intervalo: " + [a, b, c]);
  assert.strictEqual(b, 150);
});

prueba("no se supone orden temporal: la respuesta viene ordenada por distancia", () => {
  /* `/series` devuelve `ORDER BY vehicle_id, distancia`. Sobre el cruce de meta
     el ultimo metro de la vuelta y el primero de la siguiente quedan en el
     orden contrario al del reloj. */
  reiniciar();
  cargarVuelta(1, [2000, 0, 1000],
               { distancia_m: [0, 10, 20], speed: [30, 10, 20] });
  const st = serieTemporal("speed", 1, "car:0");
  assert.deepStrictEqual(st.t.map(t => t - T0), [0, 1000, 2000]);
  assert.deepStrictEqual(st.v, [10, 20, 30]);
});

prueba("dos muestras con la misma marca no producen NaN", () => {
  reiniciar();
  cargarVuelta(1, [0, 500, 500, 1000],
               { distancia_m: [0, 5, 6, 10], speed: [100, 200, 999, 300] });
  const st = serieTemporal("speed", 1, "car:0");
  assert.deepStrictEqual(st.t.map(t => t - T0), [0, 500, 1000]);
  assert.deepStrictEqual(st.v, [100, 200, 300], "no se quedo con la primera");
  const v = valorContinuoEn(st, T0 + 750);
  assert.ok(Number.isFinite(v), "salio NaN de un intervalo de duracion cero");
  assert.strictEqual(v, 250);
});

// ------------------------------------------------ frecuencias distintas y nulos

prueba("dos canales con distinta cantidad de muestras dan el mismo instante", () => {
  /* Era el defecto de fondo: cada canal se ubicaba con `fraccion * (n - 1)` y
     `n` era distinto en cada uno. Con el instante compartido los dos se
     preguntan por el mismo milisegundo. */
  reiniciar();
  /* La velocidad cada 100 ms; el regimen solo en tres de esas marcas. La
     columna del regimen tiene nulos donde no hubo medicion. */
  const marcas = [0, 100, 200, 300, 400];
  cargarVuelta(1, marcas, {
    distancia_m: [0, 5, 10, 15, 20],
    speed: [100, 110, 120, 130, 140],
    engine_speed: [10000, null, null, null, 14000],
  });
  const sVel = serieTemporal("speed", 1, "car:0");
  const sRpm = serieTemporal("rpm", 1, "car:0");
  assert.strictEqual(sVel.t.length, 5);
  assert.strictEqual(sRpm.t.length, 2, "los nulos no son muestras");
  assert.strictEqual(valorContinuoEn(sVel, T0 + 200), 120);
  /* El regimen se interpola entre sus dos muestras reales, que estan a 400 ms
     una de la otra: a la mitad, 12.000. Un nulo no es un cero. */
  assert.strictEqual(valorContinuoEn(sRpm, T0 + 200), 12000);
});

prueba("un nulo no se convierte en cero", () => {
  reiniciar();
  cargarVuelta(1, [0, 100, 200],
               { distancia_m: [0, 5, 10], speed: [100, null, 200] });
  const st = serieTemporal("speed", 1, "car:0");
  assert.deepStrictEqual(st.v, [100, 200]);
  assert.strictEqual(valorContinuoEn(st, T0 + 100), 150,
    "el nulo entro como cero y hundio la interpolacion");
});

// -------------------------------------------------------- extremos y huecos

prueba("antes de la primera muestra vale la primera, sin extrapolar", () => {
  reiniciar();
  cargarVuelta(1, [500, 1500], { distancia_m: [10, 60], speed: [100, 200] });
  const st = serieTemporal("speed", 1, "car:0");
  assert.strictEqual(valorContinuoEn(st, T0), 100);
  assert.strictEqual(valorContinuoEn(st, T0 - 100000), 100);
});

prueba("despues de la ultima vale la ultima, sin extrapolar", () => {
  reiniciar();
  cargarVuelta(1, [0, 1000], { distancia_m: [0, 50], speed: [100, 200] });
  const st = serieTemporal("speed", 1, "car:0");
  assert.strictEqual(valorContinuoEn(st, T0 + 1000), 200);
  assert.strictEqual(valorContinuoEn(st, T0 + 100000), 200);
});

prueba("sobre un hueco de captura no se une: se sostiene la ultima medida", () => {
  /* Cinco segundos sin muestras. Que paso ahi no se sabe, y trazar una recta
     entre los dos bordes seria afirmarlo. */
  reiniciar();
  cargarVuelta(1, [0, 100, 5100, 5200],
               { distancia_m: [0, 5, 300, 305], speed: [100, 110, 300, 310] });
  const st = serieTemporal("speed", 1, "car:0");
  assert.strictEqual(valorContinuoEn(st, T0 + 2600), 110,
    "se invento una rampa sobre el hueco");
  assert.strictEqual(valorContinuoEn(st, T0 + 5100), 300);
});

/* --------------------------------------------------------------------------
   LOS LIMITES DE CONTINUIDAD SON DE LA VUELTA Y NO DEPENDEN DE LA RESOLUCION
   --------------------------------------------------------------------------
   La primera version deducia el umbral de cada serie ya reducida, con
   `max(2 s, mediana x 4)`. Dependia de cuantos puntos se hubieran pedido y
   cada canal calculaba el suyo despues de descartar sus nulos.
   -------------------------------------------------------------------------- */

/* La misma captura, con dos resoluciones: 4.000 muestras a 50 ms con un corte
   real de 2,05 s en el medio, y la version reducida a 300 puntos. */
function capturaConCorte(puntos) {
  const marcas = [], dist = [];
  let t = 0, d = 0;
  for (let i = 0; i < 4000; i++) {
    if (i === 2000) t += 2050; else if (i) t += 50;
    marcas.push(t); dist.push(d); d += 2.5;
  }
  const paso = Math.max(1, Math.ceil(marcas.length / puntos));
  const mT = [], mD = [];
  for (let i = 0; i < marcas.length; i += paso) { mT.push(marcas[i]); mD.push(dist[i]); }
  if (mT[mT.length - 1] !== marcas[marcas.length - 1]) {
    mT.push(marcas[marcas.length - 1]); mD.push(dist[dist.length - 1]);
  }
  /* El corte cae entre las dos muestras que lo rodean en la resolucion
     completa; la API lo declara con esos dos extremos, que no cambian al
     reducir. */
  return { marcas: mT, dist: mD, corte: [marcas[1999], marcas[2000]],
           efectivo: marcas[marcas.length - 1] - marcas[0] - 2050 };
}

prueba("el corte declarado vale igual a cualquier resolucion", () => {
  /* ES EL CASO REPRODUCIDO. A 300 puntos los intervalos quedan de 700 ms, el
     umbral heuristico sube a 2,8 s y los 2,05 s de corte dejan de contar: el
     reloj reproduce una pausa que el backend excluyo. Con el corte declarado,
     las dos resoluciones dan el mismo tiempo efectivo. */
  const relojes = [4000, 300].map(puntos => {
    reiniciar();
    const c = capturaConCorte(puntos);
    cargarVuelta(1, c.marcas, { distancia_m: c.dist, speed: c.dist.map(() => 200) });
    declararVueltas([{ numero: 1, duracion_s: c.efectivo / 1000,
                       hueco_mayor_s: 2.05,
                       huecos: [{ desde_utc: iso(T0 + c.corte[0]),
                                  hasta_utc: iso(T0 + c.corte[1]), duracion_s: 2.05 }],
                       desde_utc: iso(T0 + c.marcas[0]),
                       hasta_utc: iso(T0 + c.marcas[c.marcas.length - 1]) }]);
    const r = relojDeVuelta(1);
    return { total: Math.round(r.total), exacto: !r.aproximado, esperado: c.efectivo };
  });
  assert.strictEqual(relojes[0].total, relojes[1].total,
    "el reloj cambia con la resolucion: " + relojes[0].total + " contra " + relojes[1].total);
  assert.strictEqual(relojes[1].total, relojes[1].esperado,
    "el tiempo efectivo no coincide con el que declara la API");
  assert.ok(relojes[1].exacto, "un reloj con cortes declarados no es una suposicion");
});

/* Deja cargada la captura del fixture a la resolucion pedida, con la vuelta
   declarando su ventana y su corte. Devuelve lo que hace falta para preguntar
   por un tiempo efectivo concreto. */
function conCorteDeclarado(puntos) {
  reiniciar();
  const c = capturaConCorte(puntos);
  cargarVuelta(1, c.marcas, { distancia_m: c.dist, speed: c.dist.map(() => 200) });
  declararVueltas([{ numero: 1, duracion_s: c.efectivo / 1000, hueco_mayor_s: 2.05,
                     huecos: [{ desde_utc: iso(T0 + c.corte[0]),
                                hasta_utc: iso(T0 + c.corte[1]), duracion_s: 2.05 }],
                     desde_utc: iso(T0 + c.marcas[0]),
                     hasta_utc: iso(T0 + c.marcas[c.marcas.length - 1]) }]);
  return c;
}

prueba("el mismo tiempo efectivo da el mismo instante a cualquier resolucion", () => {
  /* EL DEFECTO QUE QUEDABA. El total ya coincidia entre resoluciones ---la
     prueba de arriba lo comprueba--- pero eso no dice que el mismo tiempo
     efectivo caiga en el mismo instante. El reloj guardaba solo las marcas
     **submuestreadas** y `tiempoDePresentacion` interpolaba entre ellas: si el
     submuestreo se llevo por delante las dos muestras que rodean el corte, esa
     recta lo atraviesa.

     Medido con este mismo fixture, preguntando por 100.000 ms de tiempo
     rodado: a resolucion completa da 102.050 ms ---el instante justo despues
     del corte---; a 300 puntos daba 101.892,3 ms, que cae **dentro** del
     corte, donde no hay captura. */
  const instantes = [4000, 300].map(puntos => {
    const c = conCorteDeclarado(puntos);
    return tiempoDePresentacion(1, 100000 / c.efectivo) - T0;
  });
  assert.strictEqual(Math.round(instantes[1] * 1000) / 1000,
                     Math.round(instantes[0] * 1000) / 1000,
    "el instante cambia con la resolucion: " + instantes[0] + " contra " + instantes[1]);
  assert.strictEqual(Math.round(instantes[0]), 102050,
    "el instante no es el que corresponde al tiempo rodado pedido");
});

prueba("ningun instante cae estrictamente dentro de un corte declarado", () => {
  /* Recorriendo la vuelta entera a las dos resoluciones. El corte va de 99.950
     a 102.000 ms: los dos extremos son instantes validos ---son las ultimas y
     primeras muestras de cada tramo--- y todo lo de adentro, no. */
  [4000, 300].forEach(puntos => {
    const c = conCorteDeclarado(puntos);
    for (let i = 0; i <= 2000; i++) {
      const ms = tiempoDePresentacion(1, i / 2000) - T0;
      assert.ok(!(ms > c.corte[0] + 1e-9 && ms < c.corte[1] - 1e-9),
        "a " + puntos + " puntos, el instante " + ms + " cae dentro del corte " +
        c.corte[0] + "-" + c.corte[1]);
    }
  });
});

prueba("antes, en el limite y despues del corte", () => {
  const c = conCorteDeclarado(300);
  const enEfectivo = ms => tiempoDePresentacion(1, ms / c.efectivo) - T0;
  /* El corte empieza a los 99.950 ms de reloj, que son 99.950 ms de tiempo
     rodado porque hasta ahi no hubo cortes. */
  assert.strictEqual(Math.round(enEfectivo(99949)), 99949, "antes del corte");
  assert.strictEqual(Math.round(enEfectivo(99950)), 102000,
    "al agotarse el tramo se sigue en el arranque del siguiente, no en el corte");
  assert.strictEqual(Math.round(enEfectivo(99951)), 102001, "despues del corte");
});

prueba("varios cortes, incluso dos dentro del mismo intervalo submuestreado", () => {
  /* Con una serie de pocas muestras, dos cortes pueden caer entre dos marcas
     seguidas. Interpolando entre ellas se atraviesan los dos. */
  reiniciar();
  /* Reloj de 0 a 10.000 ms; dos cortes: 2.000-4.000 y 6.000-9.000. Rodado:
     10.000 - 2.000 - 3.000 = 5.000 ms. Y la serie trae **tres** muestras, de
     modo que el intervalo 1.000-10.000 contiene los dos cortes. */
  cargarVuelta(1, [0, 1000, 10000], { distancia_m: [0, 10, 100], speed: [200, 210, 220] });
  declararVueltas([{ numero: 1, duracion_s: 5, hueco_mayor_s: 3,
                     huecos: [{ desde_utc: iso(T0 + 2000), hasta_utc: iso(T0 + 4000), duracion_s: 2 },
                              { desde_utc: iso(T0 + 6000), hasta_utc: iso(T0 + 9000), duracion_s: 3 }],
                     desde_utc: iso(T0), hasta_utc: iso(T0 + 10000) }]);
  const r = relojDeVuelta(1);
  assert.strictEqual(r.total, 5000);
  assert.strictEqual(r.aproximado, false);
  const en = ms => tiempoDePresentacion(1, ms / 5000) - T0;
  assert.strictEqual(en(0), 0);
  assert.strictEqual(en(1000), 1000);
  assert.strictEqual(en(2000), 4000, "no siguio en el arranque del segundo tramo");
  assert.strictEqual(en(3000), 5000);
  assert.strictEqual(en(4000), 9000, "no siguio en el arranque del tercer tramo");
  assert.strictEqual(en(5000), 10000);
  for (let ms = 0; ms <= 5000; ms += 5) {
    const t = en(ms);
    assert.ok(!(t > 2000 && t < 4000) && !(t > 6000 && t < 9000),
      "el instante " + t + " cae dentro de un corte");
  }
});

prueba("los cortes no meten muestras que nadie midio", () => {
  /* Los limites del reloj son limites, no telemetria: no pueden aparecer como
     puntos de velocidad ni de distancia. */
  const c = conCorteDeclarado(300);
  const antes = JSON.stringify(estado.series[1].vehiculos["car:0"]);
  const sV = serieTemporal("speed", 1, "car:0");
  const sD = serieTemporal(EJE_DISTANCIA, 1, "car:0");
  const nV = sV.t.length, nD = sD.t.length;
  for (let i = 0; i <= 400; i++) tiempoDePresentacion(1, i / 400);
  assert.strictEqual(serieTemporal("speed", 1, "car:0").t.length, nV,
    "el reloj agrego muestras a la velocidad");
  assert.strictEqual(serieTemporal(EJE_DISTANCIA, 1, "car:0").t.length, nD,
    "el reloj agrego muestras a la distancia");
  assert.strictEqual(JSON.stringify(estado.series[1].vehiculos["car:0"]), antes,
    "el reloj escribio sobre las muestras");
  /* Y la senal sigue sin unirse por encima del corte. */
  assert.strictEqual(valorContinuoEn(sD, T0 + 100500), valorContinuoEn(sD, T0 + 99950),
    "la distancia se interpolo sobre el corte");
});

prueba("el reloj de la vuelta se arma una sola vez", () => {
  const c = conCorteDeclarado(300);
  const a = relojDeVuelta(1);
  const b = relojDeVuelta(1);
  assert.strictEqual(a, b, "se rearma en cada cuadro");
  globalThis._selloSeries++;
  assert.notStrictEqual(relojDeVuelta(1), a, "no se invalido al cambiar los datos");
});

prueba("una vuelta sin cortes no cambia de comportamiento", () => {
  const f = vueltaPareja();
  const r = relojDeVuelta(1);
  assert.strictEqual(r.total, 1900);
  const en = frac => tiempoDePresentacion(1, frac) - T0;
  assert.strictEqual(en(0), 0, "el arranque de la vuelta");
  assert.strictEqual(en(1), 1900, "el final de la vuelta");
  assert.strictEqual(en(0.25), 475);
  assert.strictEqual(en(0.5), 950);
  void f;
});

prueba("sin el corte declarado, la resolucion sola no alcanza", () => {
  /* La demostracion de por que hizo falta el dato: con la misma captura y sin
     `huecos`, las dos resoluciones dan relojes distintos. Es lo que habia. */
  const totales = [4000, 300].map(puntos => {
    reiniciar();
    const c = capturaConCorte(puntos);
    cargarVuelta(1, c.marcas, { distancia_m: c.dist, speed: c.dist.map(() => 200) });
    return Math.round(relojDeVuelta(1).total);
  });
  assert.notStrictEqual(totales[0], totales[1],
    "deberian diferir: es el defecto que el dato declarado corrige");
});

prueba("una vuelta que se declara continua no tiene nada que saltar", () => {
  /* `hueco_mayor_s` por debajo del umbral es una afirmacion sobre la
     resolucion completa: no hubo corte. Medido en Spa, la heuristica sobre la
     serie reducida llegaba a declarar 22 s de huecos en una vuelta cuya mayor
     separacion real es de 0,067 s. */
  reiniciar();
  const marcas = [], dist = [];
  for (let i = 0; i < 10; i++) { marcas.push(i * 3000); dist.push(i * 150); }
  cargarVuelta(1, marcas, { distancia_m: dist, speed: dist.map(() => 200) });
  declararVueltas([{ numero: 1, duracion_s: 27, hueco_mayor_s: 0.067,
                     desde_utc: iso(T0), hasta_utc: iso(T0 + 27000) }]);
  const r = relojDeVuelta(1);
  assert.strictEqual(r.total, 27000,
    "se saltearon intervalos en una vuelta que la API declara continua");
  assert.ok(!r.aproximado);
  const st = serieTemporal("speed", 1, "car:0");
  assert.strictEqual(valorContinuoEn(st, T0 + 1500), 200);
});

prueba("un canal disperso usa los limites de la vuelta, no los suyos", () => {
  /* El regimen llega en tres muestras de las diez; su mediana de intervalos es
     enorme y con el umbral propio interpolaba tranquilamente por encima del
     corte que el reloj de la distancia ya habia detectado. */
  reiniciar();
  const marcas = [], dist = [], rpm = [];
  for (let i = 0; i < 10; i++) {
    marcas.push(i < 5 ? i * 100 : 6000 + (i - 5) * 100);
    dist.push(i * 10);
    rpm.push(i === 0 || i === 4 || i === 9 ? 10000 + i * 100 : null);
  }
  cargarVuelta(1, marcas, { distancia_m: dist, speed: dist.map(() => 200), engine_speed: rpm });
  declararVueltas([{ numero: 1, duracion_s: 0.8, hueco_mayor_s: 5.6,
                     huecos: [{ desde_utc: iso(T0 + 400), hasta_utc: iso(T0 + 6000),
                                duracion_s: 5.6 }],
                     desde_utc: iso(T0), hasta_utc: iso(T0 + 6400) }]);
  const sD = serieTemporal(EJE_DISTANCIA, 1, "car:0");
  const sR = serieTemporal("rpm", 1, "car:0");
  assert.strictEqual(sR.t.length, 3, "el canal disperso tiene tres muestras");
  assert.deepStrictEqual(sR.cont, sD.cont,
    "dos canales de la misma vuelta con distintos limites de continuidad");
  /* En medio del corte, las dos sostienen su ultima medida en vez de trazar
     una recta sobre lo que no se midio. */
  assert.strictEqual(valorContinuoEn(sD, T0 + 3000), 40);
  assert.strictEqual(valorContinuoEn(sR, T0 + 3000), 10400,
    "el regimen interpolo por encima del corte que la distancia si respeta");
});

prueba("el tiempo efectivo resta el solapamiento, no el intervalo entero", () => {
  /* Dos muestras reducidas pueden abarcar el corte y ademas conduccion de los
     dos lados. Contar cero borraria esa conduccion; restar el corte deja lo
     que se rodo. */
  const cont = { huecos: [[1000, 3000]], umbral: Infinity, exacto: true };
  assert.strictEqual(tiempoEfectivoEntre(cont, 500, 3500), 1000);
  assert.strictEqual(tiempoEfectivoEntre(cont, 0, 500), 500);
  assert.strictEqual(tiempoEfectivoEntre(cont, 1200, 2000), 0);
  assert.strictEqual(tiempoEfectivoEntre({ huecos: [], umbral: Infinity, exacto: true },
                                          0, 900000), 900000,
    "sin cortes declarados no se descuenta nada");
});

// ----------------------------------------------------------- senales discretas

prueba("la marcha no pasa por la 4,5", () => {
  const f = vueltaPareja();
  const st = serieTemporal("gear", 1, "car:0");
  assert.ok(esCanalEscalonado("gear"), "la marcha se declaro interpolable");
  for (let ms = 0; ms <= 1900; ms += 10) {
    const g = valorEscalonadoEn(st, T0 + ms);
    assert.ok(g === 4 || g === 5, "marcha intermedia " + g + " a los " + ms + " ms");
  }
  void f;
});

prueba("una senal discreta no adelanta su cambio", () => {
  /* Con el redondeo a la muestra mas cercana, la marcha subia hasta medio
     intervalo antes de que el dato dijera que subio: es mostrar un estado
     futuro. En escalon, cambia en su instante medido y no antes. */
  vueltaPareja();
  const st = serieTemporal("gear", 1, "car:0");
  assert.strictEqual(valorEscalonadoEn(st, T0 + 999), 4, "la marcha subio antes de tiempo");
  assert.strictEqual(valorEscalonadoEn(st, T0 + 1000), 5);
});

prueba("el DRS es discreto y el acelerador del bus tambien", () => {
  globalThis.fuente = "f1";
  assert.strictEqual(esCanalEscalonado("drs"), true);
  assert.strictEqual(esCanalEscalonado("throttle"), false);
  globalThis.fuente = "can";
  assert.strictEqual(esCanalEscalonado("throttle"), true,
    "gas_pressed es pisado o no pisado, no cuanto");
  assert.strictEqual(esCanalEscalonado("brake"), true);
  globalThis.fuente = "f1";
});

// ------------------------------------------------- el reloj y la politica de pausas

prueba("el reloj de la vuelta acumula tiempo efectivo, no bruto", () => {
  reiniciar();
  /* Diez muestras cada 100 ms, cinco segundos de hueco, diez mas. Bruto:
     6.800 ms. Efectivo: 1.800. Es la misma cuenta que hace la API para
     `duracion_s`. */
  const marcas = [], dist = [], vel = [];
  for (let i = 0; i < 10; i++) { marcas.push(i * 100); dist.push(i * 5); vel.push(200); }
  for (let i = 0; i < 10; i++) { marcas.push(5900 + i * 100); dist.push(50 + i * 5); vel.push(250); }
  cargarVuelta(1, marcas, { distancia_m: dist, speed: vel });
  /* Sin cortes declarados el reloj los deduce, y lo dice: `aproximado`. El
     total sigue siendo el tiempo rodado, que es lo que esta prueba mira. */
  const r = relojDeVuelta(1);
  assert.strictEqual(r.total, 1800, "el reloj conto el hueco como tiempo rodado");
  assert.strictEqual(r.aproximado, true,
    "un reloj apoyado en un umbral deducido no puede presentarse como medido");

  /* Con la vuelta declarando donde se corto, el mismo reloj deja de ser una
     suposicion y da lo mismo. */
  declararVueltas([{ numero: 1, duracion_s: 1.8, hueco_mayor_s: 5,
                     huecos: [{ desde_utc: iso(T0 + 900), hasta_utc: iso(T0 + 5900),
                                duracion_s: 5 }],
                     desde_utc: iso(T0), hasta_utc: iso(T0 + 6800) }]);
  globalThis._selloSeries++;
  const rd = relojDeVuelta(1);
  assert.strictEqual(rd.total, 1800);
  assert.strictEqual(rd.aproximado, false);
});

prueba("el tiempo de presentacion nunca cae dentro de un hueco", () => {
  /* ES EL DEFECTO DE FONDO. El transporte dimensiona la vuelta con la duracion
     efectiva y `posicionesAhora` estiraba esa fraccion sobre el intervalo UTC
     bruto: a mitad de reproduccion el coche quedaba en medio del hueco ---donde
     no hay dato--- y los instrumentos en otro sitio. Una sola politica: el
     hueco no consume tiempo de reproduccion. */
  reiniciar();
  const marcas = [], dist = [], vel = [];
  for (let i = 0; i < 10; i++) { marcas.push(i * 100); dist.push(i * 5); vel.push(200); }
  for (let i = 0; i < 10; i++) { marcas.push(5900 + i * 100); dist.push(50 + i * 5); vel.push(250); }
  cargarVuelta(1, marcas, { distancia_m: dist, speed: vel });
  for (let f = 0; f <= 1.0001; f += 0.01) {
    const ms = tiempoDePresentacion(1, Math.min(1, f)) - T0;
    assert.ok(ms <= 900 || ms >= 5900,
      "el instante cayo dentro del hueco de captura: " + ms + " ms");
  }
  assert.strictEqual(tiempoDePresentacion(1, 0.5) - T0, 5900,
    "a mitad del tiempo rodado no arranca el tramo de despues del hueco");
});

prueba("sin serie todavia el reloj se declara aproximado", () => {
  reiniciar();
  declararVueltas([{ numero: 1, duracion_s: 90,
                     desde_utc: iso(T0), hasta_utc: iso(T0 + 90000) }]);
  const r = relojDeVuelta(1);
  assert.strictEqual(r.aproximado, true,
    "una suposicion se esta presentando como una medicion");
  assert.strictEqual(tiempoDePresentacion(1, 0.5) - T0, 45000);
});

prueba("sin instantes en la respuesta no hay reloj y cada lectura vuelve a lo que hacia", () => {
  reiniciar();
  cargarVuelta(1, [0, 100], { distancia_m: [0, 5], speed: [100, 200] },
               { sinTiempos: true });
  assert.strictEqual(serieTemporal("speed", 1, "car:0"), null);
  assert.strictEqual(relojDeVuelta(1), null);
  assert.strictEqual(tiempoDePresentacion(1, 0.5), null);
});

// -------------------------------------- correspondencia coche / velocidad / metro

/* Deja cargada una respuesta de `/posiciones` derivada de las mismas muestras
   que las series: es lo que hace la API, que las saca de la misma tabla. */
function cargarPosiciones(numero, marcas, dist) {
  globalThis.estado.posiciones[numero] = {
    vuelta: numero,
    puntos: marcas.length - 1,
    desde_utc: iso(T0 + marcas[0]),
    hasta_utc: iso(T0 + marcas[marcas.length - 1]),
    intervalo_ms: (marcas[marcas.length - 1] - marcas[0]) / (marcas.length - 1),
    vehiculos: { "car:0": dist.slice() },
    instantes_ms: { "car:0": marcas.map(m => m - marcas[0]) },
  };
}

prueba("el coche, la velocidad y el metro son el mismo instante", () => {
  const f = vueltaPareja();
  cargarPosiciones(1, f.marcas, f.dist);
  /* A un cuarto de vuelta: 475 ms de las 1.900. La distancia medida ahi sale de
     interpolar entre la muestra de 400 ms (20 m) y la de 500 ms (25 m). */
  globalThis.cabezal = 0.25;
  const t = calcularInstante();
  assert.strictEqual(t.tUtcMs - T0, 475, "el instante compartido no es el esperado");
  assert.ok(Math.abs(t.metro - 23.75) < 1e-9, "el metro no es el del instante: " + t.metro);
  assert.ok(Math.abs(t.velocidad - 209.5) < 1e-9,
    "la velocidad no es la del instante: " + t.velocidad);
  const enPista = posicionesAhora();
  assert.ok(Math.abs(enPista["car:0"] - t.metro) < 1e-6,
    "el coche esta en " + enPista["car:0"] + " y el metro dice " + t.metro);
});

prueba("con un hueco de captura, el coche y los instrumentos siguen coincidiendo", () => {
  /* Es el caso que separaba las dos escalas: la fraccion efectiva contra la
     ventana bruta. Antes, a mitad de reproduccion el coche quedaba en el metro
     del medio del hueco y la velocidad en otro; ahora los dos leen el mismo
     instante UTC. */
  reiniciar();
  const marcas = [], dist = [], vel = [];
  for (let i = 0; i < 10; i++) { marcas.push(i * 100); dist.push(i * 5); vel.push(200 + i); }
  for (let i = 0; i < 10; i++) { marcas.push(5900 + i * 100); dist.push(300 + i * 5); vel.push(250 + i); }
  cargarVuelta(1, marcas, { distancia_m: dist, speed: vel });
  declararVueltas([{ numero: 1, duracion_s: 1.8,
                     desde_utc: iso(T0), hasta_utc: iso(T0 + 6800) }]);
  cargarPosiciones(1, marcas, dist);
  globalThis.cabezal = 0.5;
  const t = calcularInstante();
  assert.strictEqual(t.tUtcMs - T0, 5900);
  assert.strictEqual(t.metro, 300);
  const enPista = posicionesAhora();
  assert.ok(Math.abs(enPista["car:0"] - t.metro) < 1e-6,
    "el coche en " + enPista["car:0"] + " y el metro en " + t.metro);
});

// --------------------------------------- pausa, seek y velocidad de reproduccion

prueba("una pausa no mueve nada: el mismo cabezal da el mismo instante", () => {
  const f = vueltaPareja();
  cargarPosiciones(1, f.marcas, f.dist);
  globalThis.cabezal = 0.37;
  const a = calcularInstante();
  const enA = posicionesAhora()["car:0"];
  const b = calcularInstante();
  const enB = posicionesAhora()["car:0"];
  assert.strictEqual(a.tUtcMs, b.tUtcMs);
  assert.strictEqual(a.velocidad, b.velocidad);
  assert.strictEqual(enA, enB);
});

prueba("un seek da lo mismo que llegar reproduciendo", () => {
  /* El instante es funcion del cabezal y de nada mas: no hay estado acumulado
     que dependa del camino, y por eso saltar y reproducir coinciden. */
  const f = vueltaPareja();
  cargarPosiciones(1, f.marcas, f.dist);
  globalThis.cabezal = 0.6;
  const saltando = calcularInstante().tUtcMs;
  const enSalto = posicionesAhora()["car:0"];
  for (let c = 0; c <= 0.6 + 1e-12; c += 0.02) {
    globalThis.cabezal = Math.min(0.6, c);
    calcularInstante();
  }
  globalThis.cabezal = 0.6;
  assert.strictEqual(calcularInstante().tUtcMs, saltando);
  assert.strictEqual(posicionesAhora()["car:0"], enSalto);
});

prueba("la velocidad de reproduccion no cambia lo que se muestra en cada cabezal", () => {
  /* Reproducir a 4x avanza el cabezal cuatro veces mas rapido; lo que se ve en
     cada posicion del cabezal tiene que ser el mismo dato. */
  const f = vueltaPareja();
  cargarPosiciones(1, f.marcas, f.dist);
  const aUnaVez = [];
  for (let c = 0; c <= 1.0001; c += 0.05) {
    globalThis.cabezal = Math.min(1, c);
    aUnaVez.push(calcularInstante().velocidad);
  }
  const aCuatro = [];
  for (let i = 0; i < aUnaVez.length; i++) {
    globalThis.cabezal = Math.min(1, i * 0.05);
    aCuatro.push(calcularInstante().velocidad);
  }
  assert.deepStrictEqual(aCuatro, aUnaVez);
});

prueba("el instante avanza de forma monotona con el cabezal", () => {
  vueltaPareja();
  let anterior = -Infinity;
  for (let c = 0; c <= 1.0001; c += 0.005) {
    globalThis.cabezal = Math.min(1, c);
    const t = calcularInstante().tUtcMs;
    assert.ok(t >= anterior, "el instante retrocedio en " + c);
    anterior = t;
  }
});

// --------------------------------------- vueltas distintas y cruce de meta

prueba("dos vueltas de distinta duracion ocupan lo que duraron", () => {
  reiniciar();
  const m1 = [], d1 = [], v1 = [];
  for (let i = 0; i < 10; i++) { m1.push(i * 100); d1.push(i * 5); v1.push(200); }
  cargarVuelta(1, m1, { distancia_m: d1, speed: v1 });
  const m2 = [], d2 = [], v2 = [];
  for (let i = 0; i < 10; i++) { m2.push(3000 + i * 300); d2.push(i * 15); v2.push(100); }
  cargarVuelta(2, m2, { distancia_m: d2, speed: v2 });
  declararVueltas([
    { numero: 1, duracion_s: 0.9, desde_utc: iso(T0), hasta_utc: iso(T0 + 900) },
    { numero: 2, duracion_s: 2.7, desde_utc: iso(T0 + 3000), hasta_utc: iso(T0 + 5700) },
  ]);
  /* La vuelta 1 dura un cuarto de la sesion: el cabezal en 0,25 es justo el
     cambio de vuelta. */
  globalThis.cabezal = 0.2;
  assert.strictEqual(calcularInstante().vuelta, 1);
  globalThis.cabezal = 0.3;
  const t = calcularInstante();
  assert.strictEqual(t.vuelta, 2);
  /* Y dentro de la vuelta 2, el instante es de la ventana de la vuelta 2, no de
     una rejilla repartida sobre la sesion entera. */
  assert.ok(t.tUtcMs >= T0 + 3000 && t.tUtcMs <= T0 + 5700,
    "el instante de la vuelta 2 cayo fuera de su ventana: " + (t.tUtcMs - T0));
});

prueba("no se interpola sobre el cruce de meta", () => {
  /* Vuelta 22 de Spa: `... 6.978,0 · 2,1`. La distancia de vuelta se reinicia
     porque el coche cruzo la meta. Interpolar entre esos dos haria retroceder
     siete kilometros en pantalla. Y tampoco se fuerza que crezca: esconderlo
     haria que un descenso que **si** es un error se viera igual de prolijo. */
  reiniciar();
  cargarVuelta(22, [0, 1000, 2000],
               { distancia_m: [6900, 6978, 2.1], speed: [300, 305, 306] });
  declararVueltas([{ numero: 22, duracion_s: 2,
                     desde_utc: iso(T0), hasta_utc: iso(T0 + 2000) }]);
  const st = serieTemporal(globalThis.EJE_DISTANCIA, 22, "car:0");
  assert.strictEqual(valorContinuoEn(st, T0 + 1500, true), 6978,
    "el coche retrocede sobre el cruce de meta");
  globalThis.cabezal = 0.75;
  assert.strictEqual(calcularInstante().metro, 6978);
  /* La velocidad, que no se reinicia, si se sigue interpolando: el cruce de
     meta no es una discontinuidad de todas las senales. */
  globalThis.cabezal = 0.75;
  assert.ok(Math.abs(calcularInstante().velocidad - 305.5) < 1e-9);
});

// ---------------------------------------------- ventana movil con bordes

prueba("el borde de la ventana se calcula, no se recorta", () => {
  const serie = [[0, 10], [100, 20], [200, 30], [300, 40]];
  /* La ventana termina en 150: sin el borde, el trazo se corta en 100 y la
     punta solo avanza cuando entra la muestra de 200. */
  const r = recortarConBordes(serie, 50, 150, false);
  assert.deepStrictEqual(r, [[50, 15], [100, 20], [150, 25]]);
});

prueba("la punta del trazo avanza en cada cuadro, no de muestra en muestra", () => {
  const serie = [];
  for (let m = 0; m <= 1000; m += 50) serie.push([m, m]);
  const a = recortarConBordes(serie, 0, 320.5, false);
  const b = recortarConBordes(serie, 0, 321.7, false);
  const puntaA = a[a.length - 1][0], puntaB = b[b.length - 1][0];
  assert.notStrictEqual(puntaA, puntaB, "la punta del trazo se quedo quieta");
  assert.ok(Math.abs(puntaA - 320.5) < 1e-9);
  assert.ok(Math.abs(puntaB - 321.7) < 1e-9);
});

prueba("una senal escalonada no se cruza en diagonal en el borde", () => {
  const marchas = [[0, 4], [100, 5], [200, 6]];
  const r = recortarConBordes(marchas, 0, 150, true);
  assert.deepStrictEqual(r, [[0, 4], [100, 5], [150, 5]],
    "el borde invento una marcha intermedia");
});

prueba("sin dominio, recortar con bordes no agrega nada", () => {
  const serie = [[0, 10], [100, 20]];
  assert.deepStrictEqual(recortarConBordes(serie, null, null, false), serie);
});

prueba("una ventana entre dos muestras devuelve sus dos bordes", () => {
  const serie = [[0, 0], [100, 100]];
  assert.deepStrictEqual(recortarConBordes(serie, 40, 60, false), [[40, 40], [60, 60]]);
});

prueba("recortar con bordes suelta lo que no se puede ubicar", () => {
  const serie = [[0, 10], [NaN, 20], [100, NaN], [200, 30]];
  const r = recortarConBordes(serie, null, null, false);
  assert.deepStrictEqual(r, [[0, 10], [200, 30]]);
});

// ------------------------------------------------------------- inmutabilidad

prueba("leer instantes no toca las muestras", () => {
  const f = vueltaPareja();
  cargarPosiciones(1, f.marcas, f.dist);
  const antesSeries = JSON.stringify(globalThis.estado.series[1].vehiculos["car:0"]);
  const antesPos = JSON.stringify(globalThis.estado.posiciones[1].vehiculos);
  const antesInstantes = JSON.stringify(globalThis.estado.posiciones[1].instantes_ms);
  for (let c = 0; c <= 1.0001; c += 0.01) {
    globalThis.cabezal = Math.min(1, c);
    calcularInstante();
    posicionesAhora();
  }
  assert.strictEqual(JSON.stringify(globalThis.estado.series[1].vehiculos["car:0"]),
                     antesSeries, "el suavizado escribio sobre las muestras");
  assert.strictEqual(JSON.stringify(globalThis.estado.posiciones[1].vehiculos), antesPos);
  assert.strictEqual(JSON.stringify(globalThis.estado.posiciones[1].instantes_ms),
                     antesInstantes);
});

prueba("los maximos que se leen de la serie no cambian con la interpolacion", () => {
  const f = vueltaPareja();
  const st = serieTemporal("speed", 1, "car:0");
  assert.strictEqual(Math.max.apply(null, st.v), Math.max.apply(null, f.vel));
  assert.strictEqual(Math.min.apply(null, st.v), Math.min.apply(null, f.vel));
});

prueba("la vista temporal se arma una sola vez por vuelta, vehiculo y senal", () => {
  vueltaPareja();
  const a = serieTemporal("speed", 1, "car:0");
  const b = serieTemporal("speed", 1, "car:0");
  assert.strictEqual(a, b, "se rearma en cada cuadro");
  globalThis._selloSeries++;
  assert.notStrictEqual(serieTemporal("speed", 1, "car:0"), a,
    "no se invalido al cambiar los datos");
});

/* ==========================================================================
   LA VENTANA MOVIL NO SE CORTA EN LA META
   ==========================================================================
   El defecto: la ventana se corria sobre la distancia de vuelta, que vuelve a
   cero al cruzar. A los nueve metros de la vuelta nueva medía nueve metros,
   con la anterior en memoria y sin dibujar. Medido en Spa cruzando de la 3 a
   la 4: de 52 puntos abarcando 1.200 m a 2 puntos abarcando 9.
   ========================================================================== */

/* DOS VUELTAS DE VERDAD, encadenadas como las entrega la API: la acumulada no
   se reinicia y la de vuelta si. Cada vuelta son 7.000 m en 100 s. */
function cargarDosVueltas(opciones) {
  const o = opciones || {};
  reiniciar();
  const armar = (numero, base, t0) => {
    const marcas = [], local = [], sesion = [], vel = [], marcha = [];
    for (let i = 0; i <= 100; i++) {
      marcas.push(t0 + i * 1000);
      local.push(i * 70);
      sesion.push(base + i * 70);
      vel.push(200 + (i % 10) * 5);
      marcha.push(4 + (i % 3));
    }
    const cols = { distancia_m: local, distancia_sesion_m: sesion,
                   speed: vel, gear_selected: marcha };
    if (o.sinAcumulada === numero || o.sinAcumulada === "todas") delete cols.distancia_sesion_m;
    if (o.acumuladaConNulos === numero) {
      cols.distancia_sesion_m = sesion.map((x, i) => (i % 7 === 3 ? null : x));
    }
    cargarVuelta(numero, marcas, cols);
    return { base: base, t0: t0, fin: t0 + 100000 };
  };
  /* La vuelta 1 arranca en el metro 0 de sesion; la 2, donde termino la 1 mas
     el paso de una muestra. */
  const a = armar(1, 0, 0);
  const b = armar(2, 7000 + 70, o.corte ? 100000 + o.corte : 101000);
  /* `cortePorLaVentana` reproduce lo que devuelve la API de verdad: las dos
     vueltas internamente continuas ---`huecos: []`--- y el corte visible solo
     como separacion entre sus ventanas declaradas, porque el backend calcula
     los saltos con `PARTITION BY vuelta` y el de en medio no cae en ninguna. */
  const dentro = o.corte && !o.cortePorLaVentana;
  const v2 = { numero: 2, duracion_s: 100,
      hueco_mayor_s: dentro ? o.corte / 1000 : 0.05,
      huecos: dentro ? [{ desde_utc: iso(T0 + 100000), hasta_utc: iso(T0 + 100000 + o.corte),
                          duracion_s: o.corte / 1000 }] : [],
      desde_utc: iso(T0 + b.t0), hasta_utc: iso(T0 + b.fin) };
  if (o.sinVentana === 2) { delete v2.desde_utc; delete v2.hasta_utc; }
  if (o.solapadas) v2.desde_utc = iso(T0 + a.t0 + 50000);   // empieza antes de que termine la 1
  declararVueltas([
    { numero: 1, duracion_s: 100, hueco_mayor_s: 0.05, huecos: [],
      desde_utc: iso(T0 + a.t0), hasta_utc: iso(T0 + a.fin) },
    v2,
  ]);
  return { a, b };
}

prueba("la acumulada sale de la medida, no de multiplicar por el largo", () => {
  cargarDosVueltas();
  const t1 = tramoAcumuladoDeVuelta(1, "car:0");
  const t2 = tramoAcumuladoDeVuelta(2, "car:0");
  assert.strictEqual(t1.desde, 0);
  assert.strictEqual(t1.hasta, 7000);
  assert.strictEqual(t2.desde, 7070);
  assert.strictEqual(t2.hasta, 14070);
  /* El desplazamiento de vuelta a sesion es medido: la vuelta 2 empieza en el
     metro local 0 y en el de sesion 7.070. */
  assert.strictEqual(t2.desfase, 7070);
});

prueba("una vuelta sin acumulada no aporta, y se dice", () => {
  /* No se la reconstruye con `(vuelta - 1) * largo`: sin el dato, esa vuelta
     no entra en la ventana. */
  cargarDosVueltas({ sinAcumulada: 1 });
  assert.strictEqual(tramoAcumuladoDeVuelta(1, "car:0"), null);
  assert.deepStrictEqual(serieAcumuladaDeCanal("speed", 1, "car:0"), []);
  assert.deepStrictEqual(vueltasEnTramoAcumulado(0, 20000, "car:0"), [2]);
});

prueba("los nulos de la acumulada se sueltan, no se rellenan", () => {
  cargarDosVueltas({ acumuladaConNulos: 1 });
  const s = serieAcumuladaDeCanal("speed", 1, "car:0");
  assert.ok(s.length < 101, "no se descarto ninguna muestra sin sitio en el eje");
  assert.ok(s.every(p => Number.isFinite(p[0])), "quedo un punto sin distancia");
  for (let i = 1; i < s.length; i++) {
    assert.ok(s[i][0] > s[i - 1][0], "el eje acumulado dejo de crecer");
  }
});

prueba("cruzando la meta la ventana sigue midiendo 1.200 m", () => {
  /* ES EL CASO. A los 100 m de la vuelta 2 tienen que seguir estando los
     ultimos 1.100 de la vuelta 1. */
  cargarDosVueltas();
  const enSesion = 7070 + 100;              // 100 m dentro de la vuelta 2
  const vs = vueltasEnTramoAcumulado(enSesion - 1200, enSesion, "car:0");
  assert.deepStrictEqual(vs, [1, 2], "la vuelta anterior no entra en la ventana");
  const tramos = trazaContinua("speed", "car:0", enSesion - 1200, enSesion);
  const recortados = tramos.map(d => recortarConBordes(d, enSesion - 1200, enSesion, false));
  const puntos = recortados.reduce((n, d) => n + d.length, 0);
  assert.ok(puntos > 10, "quedaron " + puntos + " puntos: la ventana se vacio");
  const primero = recortados[0][0][0];
  const ultimo = recortados[recortados.length - 1][recortados[recortados.length - 1].length - 1][0];
  assert.ok(Math.abs((ultimo - primero) - 1200) < 1e-6,
    "la ventana abarca " + (ultimo - primero) + " m en vez de 1.200");
  /* Y hay muestras de los dos lados de la meta. */
  assert.ok(primero < 7000 && ultimo > 7070,
    "la ventana no cruza la meta: " + primero + " a " + ultimo);
});

prueba("dos vueltas seguidas y sin corte se dibujan de un solo trazo", () => {
  cargarDosVueltas();
  const enSesion = 7070 + 100;
  const tramos = trazaContinua("speed", "car:0", enSesion - 1200, enSesion);
  assert.strictEqual(tramos.length, 1,
    "se partio el trazo entre dos vueltas que se midieron seguidas");
});

prueba("con un corte de captura en el medio no se unen", () => {
  /* Cinco segundos sin muestras entre el final de una vuelta y el arranque de
     la siguiente: una recta ahi seria un recorrido que nadie midio. */
  cargarDosVueltas({ corte: 5000 });
  const t2 = tramoAcumuladoDeVuelta(2, "car:0");
  const enSesion = t2.desde + 100;
  const tramos = trazaContinua("speed", "car:0", enSesion - 1200, enSesion);
  assert.strictEqual(tramos.length, 2, "se unieron dos vueltas separadas por un corte");
});

prueba("un corte ENTRE dos vueltas se ve, aunque las dos digan huecos vacios", () => {
  /* EL DEFECTO. El backend calcula los saltos con `PARTITION BY vuelta`, asi
     que el hueco que cae **entre** la ultima muestra de una vuelta y la primera
     de la siguiente no aparece en la lista de ninguna de las dos: las dos son
     internamente continuas y declaran `huecos: []`. Preguntando solo por esas
     listas, el tablero unia los dos tramos y trazaba una recta sobre cinco
     segundos sin captura.

     Se reproduce la respuesta real: `huecos: []` en las dos y una separacion
     entre sus ventanas declaradas. No se inventa una entrada en una lista
     donde el backend no la pondria. */
  cargarDosVueltas({ corte: 5000, cortePorLaVentana: true });
  assert.deepStrictEqual(estado.vueltas[0].huecos, [], "el fixture no es el caso real");
  assert.deepStrictEqual(estado.vueltas[1].huecos, [], "el fixture no es el caso real");
  const t2 = tramoAcumuladoDeVuelta(2, "car:0");
  const tramos = trazaContinua("speed", "car:0", t2.desde - 1100, t2.desde + 100);
  assert.strictEqual(tramos.length, 2,
    "se unieron dos vueltas separadas por cinco segundos sin captura");
});

prueba("el cruce normal se sigue uniendo", () => {
  /* La correccion no puede partir lo que si es continuo: entre una vuelta y la
     siguiente hay un intervalo de muestreo, no un corte. */
  cargarDosVueltas();
  const t2 = tramoAcumuladoDeVuelta(2, "car:0");
  const tramos = trazaContinua("speed", "car:0", t2.desde - 1100, t2.desde + 100);
  assert.strictEqual(tramos.length, 1, "se partio un cruce continuo");
});

prueba("el limite del umbral entre vueltas", () => {
  /* Justo por debajo del umbral del contrato de captura se unen; justo por
     encima, no. El umbral es el mismo con el que la API separa la duracion
     efectiva de la bruta, no una medida del submuestreo. */
  cargarDosVueltas({ corte: 1900, cortePorLaVentana: true });
  assert.strictEqual(
    trazaContinua("speed", "car:0", 6000, 9000).length, 1,
    "se partio por una separacion que el contrato no llama corte");
  cargarDosVueltas({ corte: 2100, cortePorLaVentana: true });
  assert.strictEqual(
    trazaContinua("speed", "car:0", 6000, 9000).length, 2,
    "no se partio por una separacion que el contrato si llama corte");
});

prueba("con ventanas invalidas o solapadas no se afirma continuidad", () => {
  /* Si los limites declarados no permiten decidir ---faltan, o la siguiente
     empieza antes de que termine la anterior--- no se sabe si se midio
     seguido, y no saberlo no es lo mismo que saber que si. */
  cargarDosVueltas({ sinVentana: 2 });
  assert.strictEqual(trazaContinua("speed", "car:0", 6000, 9000).length, 2,
    "sin limites declarados se afirmo que las dos vueltas se tocan");
  cargarDosVueltas({ solapadas: true });
  assert.strictEqual(trazaContinua("speed", "car:0", 6000, 9000).length, 2,
    "con ventanas solapadas se afirmo que las dos vueltas se tocan");
});

prueba("dos vueltas que no son consecutivas tampoco se unen", () => {
  /* La del medio no esta cargada: entre una y otra falta una vuelta entera. */
  cargarDosVueltas();
  const veh = estado.series[2];
  delete estado.series[2];
  estado.series[3] = veh;                    // la 2 pasa a ser la 3
  globalThis._selloSeries++;
  const tramos = trazaContinua("speed", "car:0", 6000, 8000);
  assert.strictEqual(tramos.length, 2,
    "se unieron dos vueltas con una sin cargar en el medio");
});

prueba("la posicion en el eje acumulado sale del instante compartido", () => {
  cargarDosVueltas();
  globalThis.cabezal = 0.4;                  // dentro de la vuelta 1
  const t = calcularInstante();
  assert.strictEqual(t.vuelta, 1);
  /* La acumulada y la de vuelta son la misma cuenta con distinto origen, y las
     dos salen del mismo `tUtcMs`: aca la vuelta 1 arranca en el metro 0. */
  assert.ok(Math.abs(t.metroSesion - t.metro) < 1e-6,
    "la acumulada no coincide con la de vuelta en la primera: " +
    t.metroSesion + " contra " + t.metro);
  /* Ya en la vuelta 2, la acumulada lleva el desplazamiento medido. */
  globalThis.cabezal = 0.75;
  const t2 = calcularInstante();
  assert.strictEqual(t2.vuelta, 2);
  assert.ok(Math.abs(t2.metroSesion - (7070 + t2.metro)) < 1e-6,
    "la acumulada de la vuelta 2 no lleva su desplazamiento");
});

prueba("sin acumulada no hay ventana continua, y no se inventa", () => {
  cargarDosVueltas({ sinAcumulada: "todas" });
  globalThis.cabezal = 0.75;
  const t = calcularInstante();
  assert.strictEqual(t.vuelta, 2);
  assert.strictEqual(t.metroSesion, null,
    "se invento una distancia acumulada que la fuente no trae");
  assert.ok(t.metro > 0, "la distancia de vuelta tiene que seguir estando");
});

/* ------------------------------------------------------------------
   LA ABSCISA DE UNA FUENTE QUE NO MIDE DISTANCIA
   ------------------------------------------------------------------
   Un bloque declara su abscisa: `distancia_m` si la fuente la mide, y si no el
   reloj del tramo en `tiempo_s`. Lo segundo no se podia leer contra un instante
   cualquiera, y la ventana movil de los graficos terminaba anclada a la abscisa
   de **una muestra concreta**: avanzaba a saltos del tamaño del muestreo en vez
   de correr con el reloj.

   Las marcas de abajo son las medidas en OpenF1 ---Silverstone 2025, vuelta 1
   pedida como tramo propio: 401 muestras en 106,1 s, una cada 0,265 s---, que es
   donde se ve. A 1x eso son menos de cuatro avances por segundo.
   ------------------------------------------------------------------ */

/* Una vuelta como la entrega una fuente sin distancia: cuatro muestras
   separadas 265 ms y la abscisa en `tiempo_s`, no en metros. */
function vueltaSinDistancia() {
  reiniciar();
  cargarVuelta(1, [0, 265, 530, 795],
               { tiempo_s: [0, 0.265, 0.53, 0.795],
                 speed: [100, 120, 140, 160] });
  declararVueltas([{ numero: 1, duracion_s: 0.795,
                     desde_utc: iso(T0), hasta_utc: iso(T0 + 795) }]);
}

prueba("sin distancia medida la abscisa la lleva el reloj, no la muestra", () => {
  vueltaSinDistancia();
  /* Dos instantes **dentro del mismo intervalo entre muestras**. Con la abscisa
     sacada de la muestra mas cercana los dos daban exactamente lo mismo, que es
     el salto tal cual se ve en pantalla. */
  globalThis.cabezal = 0.05;
  const a = calcularInstante();
  globalThis.cabezal = 0.15;
  const b = calcularInstante();
  assert.strictEqual(a.vuelta, 1);
  assert.ok(a.tUtcMs < T0 + 265 && b.tUtcMs < T0 + 265,
            "los dos instantes tienen que caer antes de la segunda muestra");
  assert.ok(b.metro - a.metro > 1e-6,
    "la abscisa no se movio entre dos instantes del mismo intervalo: " +
    a.metro + " y " + b.metro);
  /* Y se mueve **como el reloj**, no de cualquier manera: la recta entre las
     dos muestras que lo rodean, que es lo mismo que ya se hacia con la
     distancia. */
  const esperado = t => (t - T0) / 1000;
  assert.ok(Math.abs(a.metro - esperado(a.tUtcMs)) < 1e-9, "a: " + a.metro);
  assert.ok(Math.abs(b.metro - esperado(b.tUtcMs)) < 1e-9, "b: " + b.metro);
});

prueba("la abscisa por reloj no adelanta ni atrasa las muestras medidas", () => {
  vueltaSinDistancia();
  /* En el arranque y en el final del tramo tiene que dar el valor medido, sin
     interpolar contra nada que este fuera. */
  globalThis.cabezal = 0;
  assert.ok(Math.abs(calcularInstante().metro - 0) < 1e-9);
  globalThis.cabezal = 1;
  assert.ok(Math.abs(calcularInstante().metro - 0.795) < 1e-9);
});

prueba("donde hay distancia medida, manda la distancia y no el reloj", () => {
  /* La regla de que abscisa usar es una sola y ya estaba escrita: el reloj es
     el respaldo, no un reemplazo. Una vuelta con las dos columnas tiene que
     seguir midiendose en metros. */
  reiniciar();
  cargarVuelta(1, [0, 1000],
               { distancia_m: [0, 100], tiempo_s: [0, 1], speed: [100, 200] });
  declararVueltas([{ numero: 1, duracion_s: 1,
                     desde_utc: iso(T0), hasta_utc: iso(T0 + 1000) }]);
  globalThis.cabezal = 0.5;
  const t = calcularInstante();
  assert.ok(Math.abs(t.metro - 50) < 1e-9,
    "la abscisa dejo de ser la distancia medida: " + t.metro);
});

prueba("sin ninguna de las dos columnas no se inventa una abscisa", () => {
  reiniciar();
  cargarVuelta(1, [0, 1000], { speed: [100, 200] });
  declararVueltas([{ numero: 1, duracion_s: 1,
                     desde_utc: iso(T0), hasta_utc: iso(T0 + 1000) }]);
  assert.strictEqual(abscisaContinua(1, "car:0", T0 + 500), null);
});

prueba("las senales discretas siguen en escalon sobre el eje acumulado", () => {
  cargarDosVueltas();
  const s = serieAcumuladaDeCanal("gear", 2, "car:0");
  assert.ok(s.length > 0);
  assert.ok(s.every(p => Number.isInteger(p[1])), "aparecio una marcha intermedia");
  /* Y el borde de la ventana no la mezcla. */
  const r = recortarConBordes(s, s[3][0] + 10, s[6][0] - 10, true);
  assert.ok(r.every(p => Number.isInteger(p[1])),
    "el borde invento una marcha entre dos medidas");
});

prueba("la siguiente vuelta es la declarada, no numero + 1", () => {
  cargarDosVueltas();
  declararVueltas([{ numero: 1 }, { numero: 3 }, { numero: 4 }]);
  assert.strictEqual(vueltaSiguienteDeclarada(1), 3,
    "se pidio la vuelta 2, que la sesion no declara");
  assert.strictEqual(vueltaSiguienteDeclarada(3), 4);
  assert.strictEqual(vueltaSiguienteDeclarada(4), null, "en la ultima no hay siguiente");
  assert.strictEqual(vueltaSiguienteDeclarada(99), null);
});

prueba("armar la ventana no toca las muestras", () => {
  cargarDosVueltas();
  const antes = JSON.stringify(estado.series[1].vehiculos["car:0"]) +
                JSON.stringify(estado.series[2].vehiculos["car:0"]);
  for (let m = 6000; m < 9000; m += 25) trazaContinua("speed", "car:0", m - 1200, m);
  assert.strictEqual(JSON.stringify(estado.series[1].vehiculos["car:0"]) +
                     JSON.stringify(estado.series[2].vehiculos["car:0"]), antes,
    "la ventana continua escribio sobre las muestras");
});

prueba("la serie acumulada se arma una sola vez", () => {
  cargarDosVueltas();
  const a = serieAcumuladaDeCanal("speed", 1, "car:0");
  assert.strictEqual(serieAcumuladaDeCanal("speed", 1, "car:0"), a, "se rearma en cada cuadro");
  globalThis._selloSeries++;
  assert.notStrictEqual(serieAcumuladaDeCanal("speed", 1, "car:0"), a,
    "no se invalido al cambiar los datos");
});

// -------------------------------------------- lo que se lee del archivo

prueba("el cabezal de vuelta completa va por distancia, no por porcentaje de tiempo", () => {
  /* `moverCabezalesGraficos` toca el documento y no existe fuera de un
     navegador; lo que se comprueba es que el eje de metros que fija
     `dibujarTraza` sea el que la marca usa. */
  const i = fuenteApp.indexOf("function moverCabezalesGraficos(");
  assert.ok(i > 0, "no esta moverCabezalesGraficos");
  const bloque = fuenteApp.slice(i, i + 2000);
  assert.ok(bloque.indexOf("_ejeTraza[id]") !== -1,
    "el cabezal no lee el eje de metros que se dibujo");
  assert.ok(bloque.indexOf("t.metro") !== -1,
    "el cabezal no se coloca por la distancia de presentacion");
});

prueba("la ventana movil de los graficos usa los bordes calculados", () => {
  const i = fuenteApp.indexOf("function dibujarTraza(");
  assert.ok(i > 0, "no esta dibujarTraza");
  const bloque = fuenteApp.slice(i, fuenteApp.indexOf("function ajustarLienzo("));
  assert.ok(bloque.indexOf("recortarConBordes(d, vIni, vFin") !== -1,
    "la ventana volvio a recortar sin calcular los bordes");
});

prueba("reproduciendo no hay barrido; en vivo se conserva", () => {
  /* La primera version saco las dos transiciones **globalmente**, y el vivo no
     interpola: ahi se muestra el ultimo mensaje que llego, y sin transicion la
     aguja vuelve a saltar, que es lo que la transicion arreglaba. La regla
     correcta distingue los dos modos. */
  const css = fs.readFileSync(
    path.join(__dirname, "..", "..", "dashboard", "styles.css"), "utf8");
  const lineas = css.split("\n").filter(l => l.indexOf("transition: stroke-dashoffset") !== -1 ||
                                             l.indexOf("transition: cx 90ms") !== -1);
  assert.ok(lineas.length >= 1, "el vivo se quedo sin barrido");
  lineas.forEach(l => assert.ok(l.indexOf('[data-modo-del-tiempo="vivo"]') !== -1,
    "una transicion sin acotar al vivo: reproduciendo desfasa el instrumento — " + l.trim()));
  /* Y el histórico tiene que quedarse sin ella: la regla suelta declara solo el
     grosor. */
  assert.ok(css.indexOf("  .arco-valor { stroke-width: 11; }") !== -1,
    "la regla del historico volvio a llevar transicion");
  /* Quien pidio menos movimiento no recibe ninguno, tampoco el del vivo. */
  assert.ok(css.indexOf("@media (prefers-reduced-motion: reduce) { * { transition: none !important;") !== -1,
    "se perdio la regla que apaga el movimiento para quien lo pidio");
});

prueba("el modo del tiempo se declara en el documento", () => {
  /* Es lo que la hoja de estilos mira para distinguir reproduccion de vivo. */
  const i = fuenteApp.indexOf("function pintarTransporte(");
  assert.ok(i > 0, "no esta pintarTransporte");
  const bloque = fuenteApp.slice(i, i + 1400);
  assert.ok(bloque.indexOf("document.body.dataset.modoDelTiempo = modo") !== -1,
    "el documento no declara si se esta reproduciendo o mirando en vivo");
});

// ------------------------------------- cambio de alcance: el reset de verdad

/* `olvidarLoDeLaCorrida` es el reset **de produccion**: es el que corre cuando
   se cambia de adquisicion o de etapa. El `reiniciar()` de este arnes hace
   subir el sello a mano, y por eso no habria visto nunca este defecto: hay que
   ejecutar el de verdad. */
const olvidarLoDeLaCorrida = new Function(
  extraer("olvidarLoDeLaCorrida") + "\nreturn olvidarLoDeLaCorrida;")();
globalThis.cambiaronLasSeries = sacadas.cambiaronLasSeries ||
  new Function(extraer("cambiaronLasSeries") + "\nreturn cambiaronLasSeries;")();

prueba("cambiar de etapa suelta el reloj de la vuelta, no solo los datos", () => {
  /* EL DEFECTO. `olvidarLoDeLaCorrida` vaciaba `estado.series` y
     `estado.posiciones`, pero las vistas temporales y los relojes viven en su
     propia cache, con la vuelta y el vehiculo por clave. La vuelta 3 de la
     formacion y la vuelta 3 de la carrera comparten las dos cosas.

     La clave incluye el vehiculo, y el reset lo pone en `null`: por eso hay que
     preguntar **con el mismo vehiculo de los dos lados**, que es el caso real.
     Preguntar con la clave ya cambiada pasaria por otro motivo y no probaria
     nada. */
  reiniciar();
  globalThis.estado.vehiculoClave = "car:0";
  cargarVuelta(3, [0, 1000, 2000], { distancia_m: [0, 50, 100], speed: [100, 150, 200] });
  declararVueltas([{ numero: 3, duracion_s: 2, hueco_mayor_s: 0.05,
                     desde_utc: iso(T0), hasta_utc: iso(T0 + 2000) }]);
  assert.strictEqual(relojDeVuelta(3).total, 2000);

  /* Se cambia de etapa. Llegan las vueltas nuevas; las series todavia viajan.
     El reset de produccion es el que tiene que invalidar lo derivado: aca no se
     toca el sello a mano, que es justo lo que ocultaba el defecto. */
  olvidarLoDeLaCorrida();
  assert.deepStrictEqual(globalThis.estado.series, {}, "el reset no solto las series");
  globalThis.estado.vehiculoClave = "car:0";
  declararVueltas([{ numero: 3, duracion_s: 0.5, hueco_mayor_s: 0.05,
                     desde_utc: iso(T0), hasta_utc: iso(T0 + 500) }]);
  const despues = relojDeVuelta(3);
  assert.strictEqual(despues.total, 500,
    "sigue contestando el reloj de la etapa anterior con la vuelta y el vehiculo repetidos");
  /* La vuelta nueva declara su ventana y que no tuvo cortes, asi que el reloj
     es exacto aunque las series todavia viajen: los limites son de la vuelta,
     no de las senales. */
  assert.strictEqual(despues.aproximado, false);
});

prueba("un reloj aproximado guardado antes de las series tampoco sobrevive", () => {
  /* Es el caso que el ciclo de invalidacion se perdia. Al abrir una etapa,
     `/vueltas` llega antes que las series y el reloj se arma con sus dos
     extremos ---y con el vehiculo todavia sin resolver, o sea la misma clave en
     las dos etapas---. Si el reset no lo suelta, la etapa nueva lee el reloj de
     la anterior. */
  reiniciar();
  globalThis.estado.vehiculoClave = null;
  declararVueltas([{ numero: 5, duracion_s: 100,
                     desde_utc: iso(T0), hasta_utc: iso(T0 + 100000) }]);
  const aprox = relojDeVuelta(5);
  assert.strictEqual(aprox.aproximado, true);
  assert.strictEqual(aprox.total, 100000);

  olvidarLoDeLaCorrida();
  globalThis.estado.vehiculoClave = null;
  declararVueltas([{ numero: 5, duracion_s: 30,
                     desde_utc: iso(T0), hasta_utc: iso(T0 + 30000) }]);
  assert.strictEqual(relojDeVuelta(5).total, 30000,
    "el reloj aproximado de la etapa anterior sigue en pie");
});

prueba("el reset de produccion es el que invalida, no el del arnes", () => {
  /* `reiniciar()` sube el sello a mano y por eso no habria visto nunca este
     defecto. Se comprueba que la invalidacion este **dentro** de la funcion que
     corre en el tablero. */
  const i = fuenteApp.indexOf("function olvidarLoDeLaCorrida(");
  assert.ok(i > 0, "no esta olvidarLoDeLaCorrida");
  const cuerpo = fuenteApp.slice(i, fuenteApp.indexOf("\n}", i));
  assert.ok(cuerpo.indexOf("cambiaronLasSeries()") !== -1,
    "el reset de alcance no invalida las vistas temporales");
  const j = fuenteApp.indexOf("function vaciarVivo(");
  const cuerpoVivo = fuenteApp.slice(j, fuenteApp.indexOf("\n}", j));
  assert.ok(cuerpoVivo.indexOf("cambiaronLasSeries()") !== -1,
    "vaciar el vivo tampoco invalida lo derivado");
});

// -------------------------------- llegada de las respuestas en distinto orden

prueba("las posiciones antes que las series dan el mismo instante que al reves", () => {
  /* El orden en que contestan `/series` y `/posiciones` no puede cambiar donde
     se dibuja nada. Lo que si cambia es cuanto se sabe: con las posiciones
     solas y sin reloj medido, la marca es una estimacion y se declara. */
  const marcas = [], dist = [], vel = [];
  for (let i = 0; i < 20; i++) { marcas.push(i * 100); dist.push(i * 5); vel.push(200 + i); }
  const vueltas = [{ numero: 1, duracion_s: 1.9, hueco_mayor_s: 0.05,
                     desde_utc: iso(T0), hasta_utc: iso(T0 + 1900) }];

  const armar = (primeroSeries) => {
    reiniciar();
    declararVueltas(vueltas);
    if (primeroSeries) {
      cargarVuelta(1, marcas, { distancia_m: dist, speed: vel });
      cargarPosiciones(1, marcas, dist);
    } else {
      cargarPosiciones(1, marcas, dist);
      globalThis._selloSeries++;
      cargarVuelta(1, marcas, { distancia_m: dist, speed: vel });
    }
    globalThis.cabezal = 0.4;
    const t = calcularInstante();
    return { tU: t.tUtcMs, met: +t.metro.toFixed(6), vel: +t.velocidad.toFixed(6),
             coche: +posicionesAhora()["car:0"].toFixed(6) };
  };
  assert.deepStrictEqual(armar(false), armar(true),
    "el orden de llegada cambio lo que se muestra");
});

prueba("con posiciones y sin series todavia, el reloj ya es el de la vuelta", () => {
  /* Los limites son de la vuelta y los declara `/vueltas`, que llega antes que
     las series: el instante no se corre cuando las series aterrizan, que es lo
     que pasaba cuando el reloj se armaba con las marcas de las muestras. */
  reiniciar();
  declararVueltas([{ numero: 1, duracion_s: 1.9, hueco_mayor_s: 0.05,
                     desde_utc: iso(T0), hasta_utc: iso(T0 + 1900) }]);
  cargarPosiciones(1, [0, 950, 1900], [0, 50, 95]);
  globalThis.cabezal = 0.5;
  const t = calcularInstante();
  assert.strictEqual(relojDeVuelta(1).aproximado, false);
  assert.strictEqual(t.tUtcMs - T0, 950);
  assert.strictEqual(posicionesAhora()["car:0"], 50);

  /* Y al llegar las series, el mismo cabezal sigue dando el mismo instante. */
  const marcas = [], dist = [];
  for (let i = 0; i < 20; i++) { marcas.push(100 + i * 90); dist.push(i * 5); }
  cargarVuelta(1, marcas, { distancia_m: dist, speed: dist.map(() => 200) });
  assert.strictEqual(calcularInstante().tUtcMs - T0, 950,
    "el instante se corrio cuando llegaron las series");
});

prueba("sin ventana declarada el reloj se apoya en la serie, y se dice", () => {
  /* Una API que no devuelve `desde_utc`/`hasta_utc` deja los bordes en manos
     del submuestreo: se sigue dibujando, y se declara. */
  reiniciar();
  cargarVuelta(1, [100, 1000, 1900], { distancia_m: [0, 50, 95], speed: [200, 210, 220] });
  declararVueltas([{ numero: 1, duracion_s: 1.8, hueco_mayor_s: 0.05 }]);
  const r = relojDeVuelta(1);
  assert.strictEqual(r.aproximado, true);
  assert.strictEqual(r.total, 1800);
});

// ------------------------------------- la formacion y la carrera, sin mezclar

prueba("dos etapas solapadas en UTC no se pueden mirar juntas", () => {
  /* ES LA CAUSA DE LOS SALTOS DEL ARRANQUE, EN CHICO. El reloj del juego se
     reinicia al largar, de modo que la vuelta 1 de la formacion y la vuelta 1
     de la carrera comparten ventana. Mezcladas, la serie de la vuelta va y
     viene; separadas, es monotona. Medido en Spa: 72 retrocesos contra 0. */
  reiniciar();
  const marcas = [], dist = [];
  /* Dos pasadas por el circuito dentro de la misma vuelta declarada. */
  for (let i = 0; i < 10; i++) { marcas.push(i * 500); dist.push(i * 700); }
  for (let i = 0; i < 10; i++) { marcas.push(5000 + i * 500); dist.push(i * 700); }
  cargarVuelta(1, marcas, { distancia_m: dist, speed: dist.map(() => 200) });
  declararVueltas([{ numero: 1, duracion_s: 9.5, hueco_mayor_s: 0.5,
                     desde_utc: iso(T0), hasta_utc: iso(T0 + 9500) }]);
  const st = serieTemporal(EJE_DISTANCIA, 1, "car:0");
  let retro = 0;
  for (let i = 1; i < st.v.length; i++) if (st.v[i] < st.v[i - 1]) retro++;
  assert.ok(retro > 0, "el caso de prueba no reproduce la mezcla");
  /* Y la presentacion **no la esconde**: el retroceso esta en el dato y se ve.
     Taparlo con un maximo acumulado haria que un descenso que si es un error
     se viera igual de prolijo. Lo que se corrige es el alcance, no el dibujo. */
  globalThis.cabezal = 0.55;
  const met = calcularInstante().metro;
  assert.ok(met >= 0, "el metro dejo de ser un numero");
});

// ---------------------------------------- discretas antes de la primera muestra

prueba("una discreta no existe antes de su primera muestra", () => {
  /* Devolvia la primera muestra tambien hacia atras: la marcha aparecia puesta
     antes de que nadie la midiera. Una continua se sostiene ---el coche venia
     de algun sitio---; un estado, no. */
  reiniciar();
  cargarVuelta(1, [1000, 2000], { distancia_m: [50, 100], gear_selected: [4, 5],
                                  speed: [200, 210] });
  const g = serieTemporal("gear", 1, "car:0");
  assert.strictEqual(valorEscalonadoEn(g, T0 + 999), null,
    "la marcha se mostraba antes de haberse medido");
  assert.strictEqual(valorEscalonadoEn(g, T0 + 1000), 4);
  assert.strictEqual(valorEscalonadoEn(g, T0 + 1500), 4);
  /* La continua si se sostiene, y esa diferencia es la que importa. */
  const v = serieTemporal("speed", 1, "car:0");
  assert.strictEqual(valorContinuoEn(v, T0 + 999), 200);
});

prueba("la ausencia de una discreta llega como ausencia, no como cero", () => {
  /* Un cero es una marcha: la del punto muerto. Convertir «todavia no se
     midio» en cero afirma una medicion que nadie hizo. */
  reiniciar();
  cargarVuelta(1, [0, 1000, 2000], { distancia_m: [0, 50, 100], speed: [100, 150, 200],
                                     gear_selected: [null, 4, 5] });
  declararVueltas([{ numero: 1, duracion_s: 2, hueco_mayor_s: 0.05,
                     desde_utc: iso(T0), hasta_utc: iso(T0 + 2000) }]);
  globalThis.cabezal = 0.1;
  const t = calcularInstante();
  assert.strictEqual(t.marcha, null, "la marcha sin medir salio como un numero");
  assert.notStrictEqual(t.marcha, 0);
  /* La quinta esta medida en el ultimo instante, y hasta ahi sigue la cuarta:
     una discreta no se adelanta. */
  globalThis.cabezal = 0.9;
  assert.strictEqual(calcularInstante().marcha, 4);
  globalThis.cabezal = 1;
  assert.strictEqual(calcularInstante().marcha, 5);
});

// ------------------------------------- el contexto pregunta por el mismo UTC

const instanteUtc = new Function(
  extraer("instanteUtc") + "\nreturn instanteUtc;")();

prueba("el contexto se pregunta por el instante compartido", () => {
  /* Calculaba `inicioUTC + fraccion x duracionBruta`, que es la mezcla de
     relojes que el resto del tablero dejo de hacer: el clima que se mostraba
     podia ser el de otro momento de la vuelta.

     La ventana que declara `/vueltas` no coincide con el tramo que traen las
     series ---en Spa la vuelta 1 empieza 250 ms antes de su primera muestra de
     distancia, y con un corte en el medio la diferencia es de segundos---, asi
     que las dos cuentas dan instantes distintos. Es lo que hace que esta
     comprobacion signifique algo. */
  reiniciar();
  /* La vuelta tiene un corte de 2 s en el medio: la cuenta vieja lo recorre
     ---reparte la fraccion sobre el intervalo entero--- y el instante
     compartido lo saltea. Sin un corte las dos cuentas coinciden y la
     comprobacion no diria nada. */
  const marcas = [], dist = [], vel = [];
  for (let i = 0; i < 10; i++) { marcas.push(i * 100); dist.push(i * 5); vel.push(200 + i); }
  for (let i = 0; i < 10; i++) { marcas.push(2900 + i * 100); dist.push(50 + i * 5); vel.push(210 + i); }
  cargarVuelta(1, marcas, { distancia_m: dist, speed: vel });
  declararVueltas([{ numero: 1, duracion_s: 1.8, hueco_mayor_s: 2,
                     huecos: [{ desde_utc: iso(T0 + 900), hasta_utc: iso(T0 + 2900),
                                duracion_s: 2 }],
                     desde_utc: iso(T0), hasta_utc: iso(T0 + 3800) }]);
  cargarPosiciones(1, marcas, dist);
  globalThis.cabezal = 0.25;
  const t = calcularInstante();
  const viejaCuenta = new Date(T0 + 3800 * t.fraccion).toISOString();
  assert.notStrictEqual(new Date(t.tUtcMs).toISOString(), viejaCuenta,
    "el caso de prueba no distingue las dos cuentas");
  assert.strictEqual(instanteUtc(), new Date(t.tUtcMs).toISOString(),
    "el contexto pregunta por un instante distinto del que se esta mostrando");
});

prueba("sin instante compartido el contexto cae en lo que hay, y no en nada", () => {
  reiniciar();
  declararVueltas([{ numero: 1, duracion_s: 100,
                     desde_utc: iso(T0), hasta_utc: iso(T0 + 100000) }]);
  globalThis.cabezal = 0.5;
  assert.ok(typeof instanteUtc() === "string",
    "sin reloj medido el contexto dejo de preguntar");
});

if (process.exitCode) {
  console.error("\n" + hechas + " pruebas pasaron; hubo fallos.");
} else {
  console.log(hechas + " pruebas de tiempo de presentacion: OK");
}
