/* Una vuelta puede contener dos pasadas, y no se dibujan como una.
 *
 * CRITERIO. Como los demas arneses, la funcion se **extrae del `app.js` que se
 * publica** y se ejecuta; no se copia.
 *
 * QUE PASABA, REPORTADO EL 2026-09-14 sobre una carrera real de cinco vueltas
 * con dos jugadores. En la comparacion, con el alcance «toda la carrera», el
 * trazo de quien termino primero se volvia una maraña de rectas largas cruzando
 * el ultimo tramo del grafico.
 *
 * MEDIDO CONTRA LA BASE, sesion `f1_25:session:8835784415147808373`:
 *
 *   - El `session_distance` que publica el juego **es monotono**: 124 -> 23.653,6 m,
 *     con un solo retroceso de 1,5 m en 9.438 muestras. El dato esta bien.
 *   - Pero dentro de `lap_number = 5` hay **dos pasadas**: 1.446 muestras de
 *     17.295 a 21.615 m, y despues del cruce de meta a las 00:31:43, otras 883
 *     de 21.618 a 23.654 m, con el odometro de vuelta **reiniciado desde cero**.
 *     Es la vuelta de desaceleracion: la carrera termino y el juego no avanza el
 *     numero de vuelta.
 *   - Y la consulta devuelve las filas **ordenadas por distancia de vuelta**, de
 *     modo que las dos pasadas quedan intercaladas: 0 m de la primera, 0 m de la
 *     segunda, 10 m de la primera... Contra el eje de sesion eso retrocede 77
 *     veces, y cada retroceso es una de esas rectas.
 *
 * POR QUE NO ALCANZA CON ORDENAR. Contra el eje de sesion, ordenar arregla el
 * dibujo; contra el eje de vuelta no, porque las dos pasadas ocupan el **mismo**
 * tramo de x y ordenar las deja pisadas una sobre otra. Lo que son es dos
 * tramos, y como tales se dibujan.
 *
 * ES EL MISMO CRITERIO QUE EL TRAZADO Y LOS HUECOS: una linea entre dos
 * mediciones **afirma el camino que las une**. Entre el final de una pasada y el
 * principio de la siguiente ese camino no ocurrio.
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
  const m = fuenteApp.match(new RegExp("const\\s+" + nombre + "\\s*=\\s*(\\d+)\\s*;"));
  if (!m) throw new Error("no esta la constante " + nombre);
  return "const " + nombre + " = " + m[1] + ";";
}

const porPasadas = new Function(
  constante("VUELVE_AL_PRINCIPIO_M") + "\n" +
  extraer("enPasadas") + "\nreturn enPasadas;")();

/* Una vuelta tal como la devuelve la consulta: ordenada por distancia de vuelta,
   con las dos pasadas intercaladas. Los instantes las separan. */
function comoLlegaDeLaApi() {
  const t = s => "2026-09-14T00:" + s + "Z";
  return {
    distancia_m:         [0,      0,      10,     10,     4321,   4321],
    distancia_sesion_m:  [17295,  21618,  17305,  21628,  21615,  23654],
    timestamp_utc:       [t("30:30.000"), t("31:43.100"), t("30:30.200"),
                          t("31:43.300"), t("31:42.900"), t("32:27.000")],
  };
}

let hechas = 0;
function prueba(nombre, fn) {
  try { fn(); hechas++; } catch (e) {
    process.exitCode = 1;
    console.error("FALLA  " + nombre + "\n       " + (e && e.message));
  }
}

prueba("EL DEFECTO: la vuelta con dos pasadas se parte en dos", () => {
  const tramos = porPasadas(comoLlegaDeLaApi());
  assert.strictEqual(tramos.length, 2,
    "salio en " + tramos.length + " tramos: las dos pasadas siguen unidas");
});

prueba("y cada tramo queda en orden de tiempo, no de distancia de vuelta", () => {
  const tramos = porPasadas(comoLlegaDeLaApi());
  tramos.forEach((tramo, n) => {
    for (let i = 1; i < tramo.length; i++) {
      assert.ok(tramo[i].t >= tramo[i - 1].t,
        "el tramo " + n + " no quedo en orden de tiempo");
    }
  });
});

prueba("LA PRIMERA PASADA ES LA VUELTA Y LA SEGUNDA LA DESACELERACION", () => {
  const [primera, segunda] = porPasadas(comoLlegaDeLaApi());
  assert.deepStrictEqual(primera.map(p => p.sesion), [17295, 17305, 21615]);
  assert.deepStrictEqual(segunda.map(p => p.sesion), [21618, 21628, 23654]);
});

prueba("una vuelta normal sigue siendo un solo tramo", () => {
  /* El caso comun no puede pagar el arreglo del raro. */
  const normal = {
    distancia_m: [0, 1000, 2000, 3000, 4300],
    distancia_sesion_m: [4318, 5318, 6318, 7318, 8618],
    timestamp_utc: ["a", "b", "c", "d", "e"],
  };
  assert.strictEqual(porPasadas(normal).length, 1);
});

prueba("UN RETROCESO CHICO NO ES UNA PASADA NUEVA", () => {
  /* El propio `session_distance` retrocedio 1,5 m una vez en 9.438 muestras. Si
     cualquier retroceso partiera el trazo, el ruido de la fuente lo haria
     confeti. Lo que separa una pasada es que el odometro **vuelva al
     principio**, no que tiemble. */
  const con_ruido = {
    distancia_m: [0, 1000, 999, 2000, 4300],
    distancia_sesion_m: [4318, 5318, 5317, 6318, 8618],
    timestamp_utc: ["a", "b", "c", "d", "e"],
  };
  assert.strictEqual(porPasadas(con_ruido).length, 1);
});

prueba("sin distancia de vuelta no se parte nada", () => {
  /* La fuente deportiva no publica metro medido: ahi no hay odometro que mirar
     y el trazo es uno. */
  const sinMetro = {
    distancia_m: null,
    distancia_sesion_m: [1, 2, 3],
    timestamp_utc: ["a", "b", "c"],
  };
  assert.strictEqual(porPasadas(sinMetro).length, 1);
});

prueba("una vuelta vacia no produce tramos", () => {
  assert.deepStrictEqual(porPasadas({ distancia_m: [], timestamp_utc: [] }), []);
  assert.deepStrictEqual(porPasadas(null), []);
});

console.log("ok " + hechas + " pruebas de dos pasadas no son una vuelta");
