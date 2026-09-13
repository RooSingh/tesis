/* Que dice el tablero mientras escucha y no entra nada.
 *
 * CRITERIO. Como los demas arneses, las funciones se **extraen del `app.js`
 * que se publica** y se ejecutan; no se copian.
 *
 * QUE PASABA, MEDIDO EL 2026-09-12. Se le corto la corriente a la Pi con una
 * contrarreloj de Spa corriendo. Los valores se congelaron ---bien--- y los
 * graficos se vaciaron ---bien---, pero dos minutos despues el transporte
 * seguia diciendo «sin telemetria todavia · en cuanto el juego emita, el
 * tablero se llena solo» y el boton seguia ofreciendo «Detener escucha». La
 * persona recargo la pagina y volvio a empezar, que era lo unico que quedaba,
 * sin que nada en pantalla se lo dijera.
 *
 * LAS DOS AFIRMACIONES NO SON LA MISMA. «Todavia no llego ninguna» es cierta
 * antes de la primera muestra. Despues de un corte es falsa: llego telemetria,
 * lo que se ve es de antes del corte, y nada se va a llenar solo si el
 * capturador murio. El dato que las separa ya existia ---`vivo.ultimaLlegada`,
 * que el camino vivo escribe en cada muestra--- y esta linea no lo miraba.
 *
 * Y EL TEXTO NO SE REFRESCABA SOLO. La linea del transporte se escribe al
 * pintar, y pintar lo dispara una muestra: sin muestras no se pintaba nunca.
 * De modo que aunque hubiera dicho la verdad, la habria dicho una sola vez.
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
  const marca = "const " + nombre + " = ";
  const desde = fuenteApp.indexOf(marca);
  if (desde === -1) throw new Error("no esta la constante " + nombre);
  return fuenteApp.slice(desde, fuenteApp.indexOf(";", desde) + 1);
}

/* El banco: las tres funciones publicadas, con el estado de modulo del que
   dependen puesto desde afuera. `edadDelFlujo` lee `vivo` en tiempo de
   llamada, que es justo lo que permite moverlo entre casos. */
function banco(estadoDelModulo) {
  return new Function(
    "estado", "vivo", "ahora",
    [constante("HUECO_DE_CAPTURA_MS"),
     constante("SILENCIO_QUE_APAGA_MS"),
     extraer("comoSeVeElFlujo"),
     "function edadDelFlujo() {" +
     "  if (!vivo.ultimaLlegada) return null;" +
     "  return (ahora - vivo.ultimaLlegada) / 1000; }",
     extraer("loQueDiceLaEspera"),
     "return loQueDiceLaEspera;"].join("\n"))(
    estadoDelModulo.estado || {},
    estadoDelModulo.vivo || {},
    estadoDelModulo.ahora || 0);
}

/* El segundo banco: el tablero se entera solo de que el capturador ya no esta.
   `pedir` se controla y `terminarEscucha` se cuenta, que es lo unico que
   interesa comprobar ---quien lo llame decide dejar de escuchar---. */
function bancoDeLaComprobacion(cfg) {
  const visto = { terminadas: 0, avisos: [], pedidos: [], consola: [] };
  const cuerpo = [
    constante("SILENCIO_QUE_APAGA_MS"),
    constante("CADA_CUANTO_SE_PREGUNTA_POR_LA_CAPTURA_MS"),
    "let _ultimaPreguntaPorLaCaptura = 0;",
    "let ultima = null;",
    "const pedir = r => { visto.pedidos.push(r); ultima = cfg.responder(); return ultima; };",
    "const terminarEscucha = () => { visto.terminadas++; estadoSesion = 'cargado'; };",
    "const avisar = (t, malo) => visto.avisos.push([t, malo]);",
    "const render = () => {};",
    "const convieneAvisar = () => true;",
    "const console = { error: e => visto.consola.push(String(e && e.name || e)) };",
    extraer("haceCuantoQueNoSeSabeNada"),
    extraer("comprobarQueLaCapturaSigue"),
    "return { correr: () => { comprobarQueLaCapturaSigue(); return ultima; },",
    "         estado: () => estadoSesion };",
  ].join("\n");
  const f = new Function("cfg", "visto", "vivo", "estadoSesion", "Date_now",
    "const Date = { now: () => Date_now() };\n" + cuerpo);
  return [f(cfg, visto, cfg.vivo || {}, cfg.estadoSesion || "escuchando",
            cfg.ahora || (() => 0)), visto];
}

/* La funcion pura que decide si un fallo es en realidad el estado que se
   queria. Se extrajo del manejador del boton justamente para poder ejercerla:
   adentro de un `addEventListener` no hay forma de llamarla. */
const significadoDelFallo = new Function(
  extraer("significadoDelFallo") + "\nreturn significadoDelFallo;")();

let hechas = 0;
const pendientes = [];
function prueba(nombre, fn) {
  const r = fn();
  if (r && typeof r.then === "function") {
    pendientes.push(r.then(() => { hechas++; }, e => {
      process.exitCode = 1;
      console.error("FALLA  " + nombre + "\n       " + (e && e.message));
    }));
    return;
  }
  hechas++;
}

prueba("antes de la primera muestra, la espera se declara como espera", () => {
  const texto = banco({ vivo: { ultimaLlegada: null } })();
  assert.ok(/sin telemetría todavía/.test(texto), texto);
  assert.ok(/se llena solo/.test(texto), texto);
});

prueba("EL DEFECTO: despues de un corte ya no es «todavia»", () => {
  /* Los dos minutos reales del 2026-09-12. */
  const texto = banco({
    vivo: { ultimaLlegada: 1000 },
    ahora: 1000 + 120000,
  })();
  assert.ok(!/todavía/.test(texto),
    "sigue diciendo que nunca llego telemetria: " + texto);
  assert.ok(/se cortó/.test(texto), texto);
});

prueba("y dice que hacer, que es lo que faltaba", () => {
  const texto = banco({
    vivo: { ultimaLlegada: 1000 },
    ahora: 1000 + 120000,
  })();
  assert.ok(/detené la escucha/.test(texto),
    "no dice como volver a empezar: " + texto);
});

prueba("recibiendo con normalidad no se avisa nada", () => {
  /* Por debajo del umbral con el que todo el archivo decide que una captura se
     corto, un silencio es la cadencia del flujo y no un corte. */
  const texto = banco({
    vivo: { ultimaLlegada: 1000 },
    ahora: 1000 + 500,
  })();
  assert.strictEqual(texto, "recibiendo…");
});

prueba("si el difusor se declara caido, eso se dice en los dos casos", () => {
  /* Es una afirmacion distinta de las otras dos: no es que el juego no emita
     ni que el flujo se haya cortado en el camino, es que del otro lado no hay
     quien reparta. La declara `/live/status`. */
  const sinNada = banco({
    estado: { vivo: { conectado: false, motivo: "MQTT sin conexión" } },
    vivo: { ultimaLlegada: null },
  })();
  assert.ok(/difusor desconectado: MQTT sin conexión/.test(sinNada), sinNada);

  const trasElCorte = banco({
    estado: { vivo: { conectado: false } },
    vivo: { ultimaLlegada: 1000 },
    ahora: 1000 + 120000,
  })();
  assert.ok(/difusor desconectado/.test(trasElCorte), trasElCorte);
});

prueba("un difusor conectado no agrega ruido", () => {
  const texto = banco({
    estado: { vivo: { conectado: true } },
    vivo: { ultimaLlegada: null },
  })();
  assert.ok(!/difusor/.test(texto), texto);
});

/* -------- y el texto tiene que refrescarse sin muestras nuevas -------- */

prueba("EL SEGUNDO DEFECTO: la linea se escribia solo al pintar", () => {
  /* El reloj de un segundo existia y solo movia la marca de frescura. La linea
     del transporte quedaba con lo que decia en el ultimo dibujo, y el ultimo
     dibujo lo habia disparado la ultima muestra: la de antes del corte. */
  const i = fuenteApp.indexOf("function latidoDeFrescura(");
  assert.notStrictEqual(i, -1, "no esta el latido");
  const cuerpo = fuenteApp.slice(i, fuenteApp.indexOf("\n}", i));
  assert.ok(/marcarFrescuraDelFlujo\(\)/.test(cuerpo),
    "el latido dejo de mover la marca de frescura");
  assert.ok(/loQueDiceLaEspera\(\)/.test(cuerpo),
    "el latido no reescribe la linea del transporte");
  assert.ok(/setInterval\(latidoDeFrescura, 1000\)/.test(fuenteApp),
    "el reloj de un segundo no llama al latido");
});

prueba("y el vigia no se apaga por no haber sesion abierta", () => {
  /* `prepararEscucha` deja `estado.abierta` en nulo a proposito. El vigia
     salia por esa puerta, de modo que durante toda la espera nadie preguntaba
     por el difusor: el unico que puede decir que se cayo. */
  const i = fuenteApp.indexOf("function vigilarEnVivo(");
  assert.notStrictEqual(i, -1, "no esta vigilarEnVivo");
  const cuerpo = fuenteApp.slice(i, i + 1800);
  assert.ok(!/if \(!estado\.abierta\) \{ _relojVivo = null; return; \}/.test(cuerpo),
    "el vigia sigue apagandose en cuanto se empieza a escuchar");
  assert.ok(/estadoSesion === "escuchando"/.test(cuerpo),
    "el vigia no contempla la escucha");
});

/* ==================================================================
   EL TABLERO SE DA CUENTA SOLO, SIN QUE NADIE PULSE NADA
   ------------------------------------------------------------------
   REPORTADO POR EL USUARIO EL 2026-09-13, despues del experimento del corte de
   corriente con Docker. Tuvo que **recargar la pagina** para poder volver a
   escuchar: el boton seguia ofreciendo «Detener escucha» y pulsarlo no servia.

   POR QUE PULSARLO NO SERVIA. Los trabajos viven en la memoria del proceso y se
   pierden cuando el contenedor se recrea ---es deliberado: lo que hay que poder
   reconstruir es el dato, no la lista de veces que alguien apreto un boton---.
   De modo que `/captura/detener` contesta 409 «No hay ninguna captura en curso
   para detener.», el tablero lo trataba como un fallo cualquiera, y
   `estadoSesion` se quedaba en `escuchando` para siempre.

   LA ASIMETRIA ES LO QUE LO EXPLICA. Empezar ya manejaba su 409 ---«ya hay un
   trabajo de la misma familia en curso» no es un error para quien quiere
   escuchar: la captura esta corriendo, que es lo que pidio---. Detener no tenia
   el suyo, y es el mismo argumento al reves: que no haya nada que detener no es
   un error para quien quiere dejar de escuchar.

   Y RECARGAR NO TENDRIA QUE HACER FALTA PARA ENTERARSE. El backend sabe si hay
   una captura corriendo y el tablero no se lo preguntaba nunca.
   ================================================================== */

prueba("EL DEFECTO: detener algo que ya no existe no es un error", () => {
  const que = significadoDelFallo(
    { dejaDeSeguir: true },
    Object.assign(new Error("No hay ninguna captura en curso para detener."),
                  { estado: 409, detalle: "No hay ninguna captura en curso para detener." }));
  assert.strictEqual(que, "ya no está");
});

prueba("y empezar algo que ya estaba corriendo tampoco, que ya andaba", () => {
  const que = significadoDelFallo(
    { sigueVivo: true },
    Object.assign(new Error("Ya hay un trabajo"), {
      estado: 409, detalle: { trabajo_en_curso: { familia: "captura", duracion_s: 12 } } }));
  assert.strictEqual(que, "ya estaba");
});

prueba("UN FALLO DE VERDAD SIGUE SIENDO UN FALLO", () => {
  /* Si todo 409 se tragara, un conflicto real ---otra familia ocupada, un
     puerto tomado--- quedaria sin decirse. */
  assert.strictEqual(significadoDelFallo({ dejaDeSeguir: true },
    Object.assign(new Error("boom"), { estado: 500 })), "");
  assert.strictEqual(significadoDelFallo({ sigueVivo: true },
    Object.assign(new Error("otra familia"), {
      estado: 409, detalle: { trabajo_en_curso: { familia: "importacion" } } })), "");
  assert.strictEqual(significadoDelFallo({ sigueVivo: true },
    Object.assign(new Error("sin detalle"), { estado: 409, detalle: null })), "");
});

prueba("empezar y detener no se confunden entre si", () => {
  /* El 409 de detener no trae `trabajo_en_curso`: son dos conflictos distintos
     y el mismo codigo. Lo que los separa es que pidio quien pulso. */
  assert.strictEqual(significadoDelFallo({ sigueVivo: true },
    Object.assign(new Error("nada que detener"), { estado: 409, detalle: "texto" })), "");
});

/* ---- y la mitad que no necesita que nadie pulse ---- */

prueba("hace cuanto que no se sabe nada: la ultima muestra o el encendido", () => {
  const cuanto = (vivo, ahora) => new Function("vivo", "ahora",
    "const Date = { now: () => ahora };\n" + extraer("haceCuantoQueNoSeSabeNada") +
    "\nreturn haceCuantoQueNoSeSabeNada();")(vivo, ahora);
  //: Con muestras, se cuenta desde la ultima.
  assert.strictEqual(cuanto({ ultimaLlegada: 1000, escuchaDesde: 1000 }, 6000), 5000);
  /* SIN NINGUNA MUESTRA SE CUENTA DESDE QUE SE ENCENDIO LA ESCUCHA, y no se
     devuelve nulo: el caso «pulse escuchar y el capturador estaba muerto» no
     tiene primera muestra nunca, y es justo el que hay que poder detectar. */
  assert.strictEqual(cuanto({ ultimaLlegada: null, escuchaDesde: 1000 }, 9000), 8000);
  //: Sin ninguno de los dos no se sabe, y no saber no es cero.
  assert.strictEqual(cuanto({ ultimaLlegada: null, escuchaDesde: null }, 9000), null);
});

prueba("callado el tiempo suficiente, se le pregunta al servidor", async () => {
  const [b, visto] = bancoDeLaComprobacion({
    vivo: { ultimaLlegada: 1000, escuchaDesde: 1000 },
    ahora: () => 1000 + 30000,
    responder: () => Promise.resolve({ trabajos: [] }),
  });
  await b.correr();
  assert.deepStrictEqual(visto.pedidos, ["/trabajos"]);
});

prueba("SI NO HAY CAPTURA CORRIENDO, LA ESCUCHA SE CIERRA SOLA", async () => {
  const [b, visto] = bancoDeLaComprobacion({
    vivo: { ultimaLlegada: 1000, escuchaDesde: 1000 },
    ahora: () => 1000 + 30000,
    responder: () => Promise.resolve({ trabajos: [] }),
  });
  await b.correr();
  assert.strictEqual(visto.terminadas, 1, "la escucha siguio abierta sobre nada");
  assert.strictEqual(visto.avisos.length, 1);
  assert.ok(/captur/i.test(visto.avisos[0][0]), visto.avisos[0][0]);
});

prueba("con la captura corriendo no se toca nada, aunque el juego no emita", () => {
  /* Es el caso normal de esperar: el capturador esta y el juego todavia no
     arranco. Cerrar la escucha ahi seria el defecto contrario. */
  const [b, visto] = bancoDeLaComprobacion({
    vivo: { ultimaLlegada: null, escuchaDesde: 1000 },
    ahora: () => 1000 + 30000,
    responder: () => Promise.resolve({ trabajos: [
      { familia: "captura", estado: "en_curso" }] }),
  });
  return b.correr().then(() => {
    assert.strictEqual(visto.terminadas, 0, "cerro una escucha que estaba viva");
    assert.strictEqual(visto.avisos.length, 0);
  });
});

prueba("un trabajo de otra familia no cuenta como captura", () => {
  const [b, visto] = bancoDeLaComprobacion({
    vivo: { ultimaLlegada: 1000, escuchaDesde: 1000 },
    ahora: () => 1000 + 30000,
    responder: () => Promise.resolve({ trabajos: [
      { familia: "importacion", estado: "en_curso" },
      { familia: "captura", estado: "terminado" }] }),
  });
  return b.correr().then(() => {
    assert.strictEqual(visto.terminadas, 1,
      "una importacion en curso hizo pasar por viva a una captura terminada");
  });
});

prueba("mientras llega telemetria no se le pregunta nada al servidor", () => {
  /* Preguntar en cada latido serian sesenta consultas por minuto para
     confirmar lo que el flujo ya demuestra al llegar.

     EL RELOJ ARRANCA LEJOS DEL CERO A PROPOSITO. Con instantes chicos, el
     limite de ritmo ---que compara contra un cero inicial--- tapaba este caso:
     la prueba pasaba aunque el umbral de silencio no existiera. Se comprobo
     quitandolo. */
  const [b, visto] = bancoDeLaComprobacion({
    vivo: { ultimaLlegada: 600000, escuchaDesde: 500000 },
    ahora: () => 600500,
    responder: () => Promise.resolve({ trabajos: [] }),
  });
  b.correr();
  assert.deepStrictEqual(visto.pedidos, [],
    "se pregunto por la captura con el flujo llegando hace medio segundo");
});

prueba("NO SE PREGUNTA EN CADA LATIDO, QUE CORRE UNA VEZ POR SEGUNDO", () => {
  const [b, visto] = bancoDeLaComprobacion({
    vivo: { ultimaLlegada: 1000, escuchaDesde: 1000 },
    ahora: () => 1000 + 30000,
    responder: () => Promise.resolve({ trabajos: [
      { familia: "captura", estado: "en_curso" }] }),
  });
  b.correr(); b.correr(); b.correr();
  assert.deepStrictEqual(visto.pedidos, ["/trabajos"],
    "se pregunto " + visto.pedidos.length + " veces seguidas");
});

prueba("fuera del estado de escucha no se pregunta nunca", () => {
  const [b, visto] = bancoDeLaComprobacion({
    estadoSesion: "cargado",
    vivo: { ultimaLlegada: 1000, escuchaDesde: 1000 },
    ahora: () => 1000 + 30000,
    responder: () => Promise.resolve({ trabajos: [] }),
  });
  b.correr();
  assert.deepStrictEqual(visto.pedidos, []);
});

prueba("si la consulta falla, la escucha NO se cierra", () => {
  /* Un servidor que no contesta no demuestra que la captura murio, y cerrar la
     escucha por eso perderia el flujo que quiza siga entrando. */
  const [b, visto] = bancoDeLaComprobacion({
    vivo: { ultimaLlegada: 1000, escuchaDesde: 1000 },
    ahora: () => 1000 + 30000,
    responder: () => Promise.reject(Object.assign(new Error("caido"), { estado: 503 })),
  });
  return b.correr().catch(() => {}).then(() => {
    assert.strictEqual(visto.terminadas, 0, "cerro la escucha por un fallo de red");
  });
});

Promise.all(pendientes).then(() => {
console.log("ok " + hechas + " pruebas de escuchar sin recibir");
});
