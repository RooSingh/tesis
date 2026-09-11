/* El panel muestra lo que la fuente trae, y dice cuando un valor se sostiene.
 *
 * CRITERIO. Como los demas arneses, las funciones se **extraen del `app.js` que
 * se publica** y se ejecutan; no se copian.
 *
 * QUE CIERRA ESTO. El tablero mostraba rayas en POSICION y AL LIDER, y el panel
 * de clima decia que OpenF1 no publica clima. Las tres cosas estaban en la base
 * desde la importacion ---155 muestras de clima, 19.943 de intervalos, 538 de
 * puestos--- y `context-at` ya las resolvia en un instante. Lo que faltaba era
 * pedirlas.
 *
 * Y al traerlas aparecieron dos preguntas que el tablero tenia mal resueltas:
 *
 * UNA. EL PANEL DE CLIMA TENIA CUATRO CASILLAS ESCRITAS A MANO ---pista, aire,
 * bandera y coche de seguridad--- porque el simulador publica esas cuatro.
 * OpenF1 publica otras: aire y pista tambien, y ademas humedad, presion, viento
 * y si llueve; y no publica ni bandera ni coche de seguridad. Con la lista fija,
 * OpenF1 daba dos casillas con una raya ---afirmando que no se sabe algo que la
 * fuente no publica--- y escondia cuatro magnitudes medidas.
 *
 * Lo que decide que casilla va es que la respuesta **traiga la clave**, no que
 * el valor no sea nulo. Una clave presente en nulo es «existe y ahora no se
 * sabe» y lleva su raya; una clave ausente es «esta fuente no lo publica».
 *
 * DOS. EL PUESTO NO SE MIDE EN EL INSTANTE EN TODAS LAS FUENTES. En el
 * simulador llega en cada muestra; en OpenF1 la fuente lo publica al cambiar
 * ---veintiocho veces en cincuenta y dos vueltas--- y entre dos cambios el
 * puesto se sostiene. Mostrarlo esta bien; presentarlo como una medicion de
 * ahora, no.
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
  const fin = fuenteApp.indexOf("];", i);
  if (fin === -1) throw new Error("no cierra la constante " + nombre);
  return fuenteApp.slice(i, fin + 2);
}

/* `cifra` es del tablero y la usa el armado de casillas. Se extrae tambien,
   para que la prueba mida el formato que se publica y no uno parecido. */
const sacadas = new Function(`
  ${extraer("cifra")}
  ${constante("CASILLAS_DEL_CLIMA")}
  ${extraer("celdasDelClima")}
  ${extraer("climaDeLaCarrera")}
  ${extraer("contextoPorPiloto")}
  ${extraer("edadEnPalabras")}
  return { celdasDelClima, climaDeLaCarrera, contextoPorPiloto, edadEnPalabras };
`)();
const { celdasDelClima, climaDeLaCarrera, contextoPorPiloto, edadEnPalabras } = sacadas;

let hechas = 0;
function prueba(titulo, fn) {
  try { fn(); hechas++; }
  catch (e) {
    process.exitCode = 1;
    console.error("FALLA  " + titulo + "\n       " + (e && e.message));
  }
}

const rotulos = d => celdasDelClima(d).map(c => c[0]);
const valores = d => {
  const m = {};
  celdasDelClima(d).forEach(c => { m[c[0]] = c[1]; });
  return m;
};

// ------------------------------------------------------------------ el clima

prueba("la simulacion sigue mostrando sus cuatro casillas", () => {
  /* Tal cual las devuelve `/contexto` de una sesion de F1 25. */
  const d = {
    temperatura_aire_c: 16.0, temperatura_pista_c: 20.0,
    codigo_de_clima: 3.0, bandera: 0.0,
    retraso_del_coche_de_seguridad_s: -0.0,
    clima: "lluvia ligera", bandera_texto: "ninguna",
  };
  assert.deepStrictEqual(rotulos(d), ["Pista", "Aire", "Bandera", "Coche de seg."]);
});

prueba("openf1 muestra lo suyo, y no las dos que no publica", () => {
  const d = climaDeLaCarrera({
    air_temperature_c: 17.8, track_temperature_c: 20.5, rainfall: true,
    humidity_percent: 77.0, pressure_mbar: 988.8, wind_speed_mps: 3.9,
    wind_direction_degrees: 65.0, weather_freshness: "current",
  });
  assert.deepStrictEqual(rotulos(d),
    ["Pista", "Aire", "Lluvia", "Humedad", "Viento", "Presión"]);
  /* Las dos que no publica no aparecen ni con una raya: una raya afirma que el
     dato existe en esta fuente y ahora no se sabe, y no es el caso. */
  assert.ok(!rotulos(d).includes("Bandera"));
  assert.ok(!rotulos(d).includes("Coche de seg."));
});

prueba("una clave presente en nulo si lleva su raya", () => {
  /* La distincion entera: `/contexto` puede traer la bandera sin saberla, y eso
     es distinto de que la fuente no tenga banderas. */
  const d = { temperatura_aire_c: 16.0, temperatura_pista_c: null,
              bandera_texto: null, retraso_del_coche_de_seguridad_s: null };
  assert.deepStrictEqual(rotulos(d), ["Pista", "Aire", "Bandera", "Coche de seg."]);
  /* Y la raya va sola: «— °C» se leeria como «no se cuantos grados», que dice
     de mas. Lo que no se sabe es el dato, no su unidad. */
  assert.strictEqual(valores(d)["Pista"], "—");
});

prueba("llover y no llover son los dos un dato, y ninguno es cero", () => {
  const llueve = climaDeLaCarrera({ rainfall: true });
  const seco = climaDeLaCarrera({ rainfall: false });
  assert.strictEqual(valores(llueve)["Lluvia"], "sí");
  assert.strictEqual(valores(seco)["Lluvia"], "no");
});

prueba("sin lluvia no se afirma que este despejado", () => {
  /* Esta fuente declara si llueve, no como esta el cielo. */
  assert.strictEqual(climaDeLaCarrera({ rainfall: false }).clima, "sin lluvia");
  assert.strictEqual(climaDeLaCarrera({ rainfall: true }).clima, "llueve");
  assert.strictEqual(climaDeLaCarrera({}).clima, "sin declarar");
});

prueba("el dibujo sale del dato y no de la frase", () => {
  assert.strictEqual(climaDeLaCarrera({ rainfall: true }).icono, "lluvia");
  assert.strictEqual(climaDeLaCarrera({ rainfall: false }).icono, "nube");
});

prueba("sin clima en la respuesta no se arma un clima vacio", () => {
  assert.strictEqual(climaDeLaCarrera(null), null);
  assert.strictEqual(climaDeLaCarrera(undefined), null);
  assert.deepStrictEqual(celdasDelClima(null), []);
});

prueba("una magnitud que la respuesta no trae no se inventa", () => {
  /* Un clima vencido vuelve con los campos en nulo pero con las claves: ahi si
     corresponde la raya. Uno donde la fuente no publica la magnitud, no. */
  const d = climaDeLaCarrera({ air_temperature_c: null, track_temperature_c: null,
                               rainfall: null, weather_freshness: "unavailable" });
  assert.deepStrictEqual(rotulos(d), ["Pista", "Aire", "Lluvia"]);
  assert.strictEqual(valores(d)["Lluvia"], "—");
  assert.strictEqual(d.frescura, "unavailable");
});

// ------------------------------------------------- el contexto de cada piloto

prueba("el contexto se indexa por numero de carrera", () => {
  const d = contextoPorPiloto({ drivers: [
    { driver_number: 1, name_acronym: "VER", position: 2 },
    { driver_number: 81, name_acronym: "PIA", position: 1 },
  ] });
  assert.strictEqual(d["1"].name_acronym, "VER");
  assert.strictEqual(d["81"].position, 1);
  assert.strictEqual(d["4"], undefined);
});

prueba("una respuesta vacia no rompe el indice", () => {
  assert.deepStrictEqual(contextoPorPiloto(null), {});
  assert.deepStrictEqual(contextoPorPiloto({}), {});
  assert.deepStrictEqual(contextoPorPiloto({ drivers: [] }), {});
});

// ------------------------------------------------------------------ la edad

prueba("la edad se dice en segundos o en minutos, segun cuanta sea", () => {
  assert.strictEqual(edadEnPalabras(6.7), ", hace 7 s");
  assert.strictEqual(edadEnPalabras(89), ", hace 89 s");
  assert.strictEqual(edadEnPalabras(90), ", hace 2 min");
  assert.strictEqual(edadEnPalabras(636.8), ", hace 11 min");
});

prueba("una edad que no se sabe no pone un parentesis vacio", () => {
  assert.strictEqual(edadEnPalabras(null), "");
  assert.strictEqual(edadEnPalabras(undefined), "");
  assert.strictEqual(edadEnPalabras("no es un numero"), "");
  /* Una edad negativa seria una muestra del futuro: no se la describe, se la
     calla, porque la consulta ya no puede devolverla. */
  assert.strictEqual(edadEnPalabras(-3), "");
});

prueba("la edad acepta lo que la base devuelve, que es una cadena", () => {
  /* `EXTRACT(EPOCH ...)` vuelve como texto decimal por psycopg. */
  assert.strictEqual(edadEnPalabras("222.638000"), ", hace 4 min");
});

console.log(hechas + " pruebas del contexto de carrera: " +
            (process.exitCode ? "hubo fallos" : "OK"));
