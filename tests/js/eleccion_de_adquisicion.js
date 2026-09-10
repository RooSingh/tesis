/* Pruebas de la eleccion de adquisicion y fase, extraidas del `app.js` real.
 *
 * CRITERIO. Igual que los otros arneses: no se copia el codigo, se **extrae
 * del `app.js` que se publica**. Aca se ejercita lo que decide como se nombra
 * y como se rotula lo elegido ---`nombreDeFase` y `etiquetaDeCorrida`--- y se
 * comprueba, leyendo el archivo, que el flujo de apertura no marca como error
 * una eleccion que simplemente esta pendiente.
 *
 * POR QUE ESTAS DOS FUNCIONES. Las fases no vienen etiquetadas por la fuente:
 * son los tramos que el reloj del juego separa, y el nombre se deduce de su
 * sitio y su largo. Si esa deduccion se corre, la persona elige «Carrera» y
 * mira la formacion.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");

const APP = path.join(__dirname, "..", "..", "dashboard", "app.js");
const fuente = fs.readFileSync(APP, "utf8");

function extraer(nombre) {
  const marca = "function " + nombre + "(";
  const desde = fuente.indexOf(marca);
  if (desde === -1) throw new Error("no esta la funcion " + nombre + " en app.js");
  let i = fuente.indexOf("{", desde);
  let nivel = 0;
  for (; i < fuente.length; i++) {
    if (fuente[i] === "{") nivel++;
    else if (fuente[i] === "}") {
      nivel--;
      if (nivel === 0) return fuente.slice(desde, i + 1);
    }
  }
  throw new Error("no cierra la funcion " + nombre);
}

/* `etiquetaDeCorrida` lee `corrida`, que es el estado del modulo. Se lo pone
   en el ambito global, que es lo que ve un cuerpo construido con
   `new Function`. */
/* La fuente de datos vigente. Ojo con el nombre: el `fuente` de este archivo es
   el texto del `app.js`, y este es el de las funciones extraidas, que preguntan
   si esa fuente tiene eje de distancia. */
globalThis.fuente = "f1";
globalThis.corrida = { adquisicion: null, fase: null, disponibles: null };
const NOMBRES = ["nombreDeFase", "etiquetaDeCorrida", "duracionCorta",
                 "queEsLaFase", "numeroMedido",
                  "alcanceEsAmbiguo", "hayAlcanceQueElegir",
                  "adquisicionSeSolapa", "alcanceElegidoEsValido", "faseDeLaDireccion",
                  "filaDeCorrida", "fechaAr", "cifra", "hayEjeDeDistancia", "porQueNoHayDistancia",
                  "alcanceResuelto", "alcancePermitePedir"];
/* La tabla de que fuentes tienen eje de distancia: la compuerta la mira antes
   de dejar pedir, y sin ella no se puede ejercer la compuerta de verdad. */
function constante(nombre) {
  const i = fuente.indexOf("const " + nombre + " =");
  if (i === -1) throw new Error("no esta la constante " + nombre);
  return fuente.slice(i, fuente.indexOf("};", i) + 2);
}

const sacadas = new Function(constante("EJE_DE_DISTANCIA_POR_FUENTE") + "\n" +
                             NOMBRES.map(extraer).join("\n\n") +
                             "\nreturn { " + NOMBRES.join(", ") + " };")();
const nombreDeFase = sacadas.nombreDeFase;
const etiquetaDeCorrida = sacadas.etiquetaDeCorrida;
const duracionCorta = sacadas.duracionCorta;
const queEsLaFase = sacadas.queEsLaFase;

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

/* Las tres fases del original de Spa, como las devuelve `/adquisiciones`:
   formacion 189,0 s, espera de luces 7,9 s, carrera 2.827,1 s. */
const SPA = {
  clave: "original",
  es_reproduccion: false,
  fases: [
    { orden: 1, duracion_de_captura_s: 189.020 },
    { orden: 2, duracion_de_captura_s: 7.905 },
    { orden: 3, duracion_de_captura_s: 2827.103 },
  ],
};

// ---------------------------------------------------------------- nombres

prueba("la ultima fase es la carrera", () => {
  assert.strictEqual(nombreDeFase(SPA, SPA.fases[2]), "Carrera");
});

prueba("la primera es la formacion", () => {
  assert.strictEqual(nombreDeFase(SPA, SPA.fases[0]), "Formación");
});

prueba("una fase corta entre medio es la espera de luces", () => {
  assert.strictEqual(nombreDeFase(SPA, SPA.fases[1]), "Espera de luces");
});

prueba("con una sola fase no hay nada que nombrar", () => {
  const a = { fases: [{ orden: 1, duracion_de_captura_s: 77.9 }] };
  assert.strictEqual(nombreDeFase(a, a.fases[0]), "Fase única");
});

prueba("una fase larga entre medio no se llama espera de luces", () => {
  /* El umbral es el largo, no el sitio: un tramo de varios minutos entre la
     formacion y la carrera es otra cosa y no se le pone un nombre que no le
     consta al dato. */
  const a = {
    fases: [
      { orden: 1, duracion_de_captura_s: 100 },
      { orden: 2, duracion_de_captura_s: 600 },
      { orden: 3, duracion_de_captura_s: 2000 },
    ],
  };
  assert.strictEqual(nombreDeFase(a, a.fases[1]), "Fase 2");
});

prueba("sin fases declaradas no se rompe", () => {
  assert.strictEqual(typeof nombreDeFase({}, { orden: 1 }), "string");
});

// ---------------------------------------------------------------- etiqueta

prueba("sin elegir, la etiqueta lo dice: todo junto", () => {
  globalThis.corrida = { adquisicion: null, fase: null, disponibles: [SPA] };
  assert.strictEqual(etiquetaDeCorrida(), "todo junto");
});

prueba("la captura original se llama Original, no por su clave", () => {
  globalThis.corrida = { adquisicion: "original", fase: null, disponibles: [SPA] };
  assert.strictEqual(etiquetaDeCorrida(), "Original");
});

prueba("con fase elegida se dice cual", () => {
  globalThis.corrida = { adquisicion: "original", fase: 3, disponibles: [SPA] };
  assert.strictEqual(etiquetaDeCorrida(), "Original · Carrera");
});

prueba("una reproduccion se nombra por su identificador", () => {
  const r = { clave: "parrilla_20260908", es_reproduccion: true, fases: [] };
  globalThis.corrida = { adquisicion: "parrilla_20260908", fase: null, disponibles: [r] };
  assert.strictEqual(etiquetaDeCorrida(), "parrilla_20260908");
});

prueba("una fase que no figura se dice por su numero y no se inventa", () => {
  globalThis.corrida = { adquisicion: "original", fase: 9, disponibles: [SPA] };
  assert.strictEqual(etiquetaDeCorrida(), "Original · fase 9");
});

prueba("sin catalogo de adquisiciones la etiqueta sigue siendo legible", () => {
  globalThis.corrida = { adquisicion: "original", fase: 3, disponibles: null };
  assert.strictEqual(etiquetaDeCorrida(), "original");
});

// -------------------------------------- el flujo de apertura, leido del texto

/* Estas tres miran el `app.js` como texto porque lo que se comprueba es una
   decision del flujo de apertura, que toca el documento y no existe fuera de
   un navegador. Se comprueban igual: son las que se rompieron. */

prueba("una sesion mezclada no se marca como error", () => {
  /* `decirEstadoApi(mensaje, true)` pinta el estado en rojo. Una eleccion
     pendiente no es un fallo: falta una decision, no salio nada mal. */
  const i = fuente.indexOf("abrirElectorDeCorrida(ruta, apertura, s);");
  assert.ok(i > 0, "no esta la llamada al elector en el flujo de apertura");
  const antes = fuente.slice(Math.max(0, i - 900), i);
  assert.ok(antes.indexOf("decirEstadoApi(estado.motivo + \" Elegí abajo.\", false)") !== -1,
    "la eleccion pendiente se esta declarando como error");
});

prueba("se carga sin preguntar solo cuando el alcance no es ambiguo", () => {
  /* ESTA PRUEBA PEDIA LO CONTRARIO, Y ESTABA MAL.
     Decia «el elector se abre solo si la sesion esta mezclada», y `mezclada` la
     decide la API contando **adquisiciones**. Una captura con una sola
     adquisicion y tres etapas contestaba `false`, de modo que el tablero
     cargaba la formacion y la carrera juntas sin avisar. Y como el reloj del
     juego se reinicia al largar, las dos se solapan en UTC: la vuelta 1 traia
     las dos y el coche iba y venia. Medido en Spa, 72 retrocesos de la
     distancia recorriendo de la vuelta 1 a la 4.

     La condicion correcta no es «cuantas adquisiciones hay» sino «se puede dar
     el alcance por supuesto». */
  const i = fuente.indexOf("if (!pedida && !alcanceEsAmbiguo()) {");
  assert.ok(i > 0, "la salida temprana ya no consulta si el alcance es ambiguo");
  const bloque = fuente.slice(i, i + 200);
  assert.ok(bloque.indexOf("cargarDatosDeSesion") !== -1,
    "sin ambiguedad tiene que seguir cargando sin preguntar");
  assert.ok(fuente.indexOf("if (!a.mezclada) {") === -1,
    "volvio la salida temprana que solo miraba la cantidad de adquisiciones");
});

prueba("una sola adquisicion con etapas que reinician el reloj es ambigua", () => {
  const conReinicio = { disponibles: [{ clave: "original", fases: [
    { orden: 1, reloj_del_juego_reinicia_al_entrar: false },
    { orden: 2, reloj_del_juego_reinicia_al_entrar: true },
    { orden: 3, reloj_del_juego_reinicia_al_entrar: true }] }] };
  const seguidas = { disponibles: [{ clave: "original", fases: [
    { orden: 1, reloj_del_juego_reinicia_al_entrar: false },
    { orden: 2, reloj_del_juego_reinicia_al_entrar: false }] }] };
  const unaSola = { disponibles: [{ clave: "original", fases: [{ orden: 1 }] }] };
  const dos = { disponibles: [{ clave: "original", fases: [] }, { clave: "r1", fases: [] }] };

  const antes = globalThis.corrida;
  globalThis.corrida = conReinicio;
  assert.strictEqual(sacadas.alcanceEsAmbiguo(), true,
    "la formacion y la carrera se solapan en UTC y se estaban mostrando juntas");
  assert.strictEqual(sacadas.hayAlcanceQueElegir(), true);
  globalThis.corrida = seguidas;
  assert.strictEqual(sacadas.alcanceEsAmbiguo(), false,
    "etapas que no reinician el reloj son continuas: no hay por que preguntar");
  assert.strictEqual(sacadas.hayAlcanceQueElegir(), true,
    "igual se puede querer mirar una sola etapa");
  globalThis.corrida = unaSola;
  assert.strictEqual(sacadas.alcanceEsAmbiguo(), false);
  assert.strictEqual(sacadas.hayAlcanceQueElegir(), false,
    "sin nada que elegir el boton sobra");
  globalThis.corrida = dos;
  assert.strictEqual(sacadas.alcanceEsAmbiguo(), true);
  globalThis.corrida = antes;
});

/* --------------------------------------------------------------------------
   EL ALCANCE SE VALIDA ENTERO, NO SOLO LA ADQUISICION
   --------------------------------------------------------------------------
   `?adquisicion=original` sin fase se aceptaba y dejaba `fase = null`, que es
   «todo junto»: el mismo alcance que la proteccion de la apertura sin
   parametros impide. Y una fase inexistente, o de otra adquisicion, entraba
   igual y se convertia en «todas» sin decirlo.
   -------------------------------------------------------------------------- */

const SPA_SOLAPADA = { clave: "original", es_reproduccion: false, fases: [
  { orden: 1, duracion_de_captura_s: 189.02, reloj_del_juego_reinicia_al_entrar: false },
  { orden: 2, duracion_de_captura_s: 7.905, reloj_del_juego_reinicia_al_entrar: true },
  { orden: 3, duracion_de_captura_s: 2827.103, reloj_del_juego_reinicia_al_entrar: true }] };
const SEGUIDA = { clave: "libres", es_reproduccion: false, fases: [
  { orden: 1, duracion_de_captura_s: 100, reloj_del_juego_reinicia_al_entrar: false },
  { orden: 2, duracion_de_captura_s: 200, reloj_del_juego_reinicia_al_entrar: false }] };

function conDisponibles(lista, fn) {
  const antes = globalThis.corrida;
  globalThis.corrida = { adquisicion: null, fase: null, disponibles: lista };
  try { fn(); } finally { globalThis.corrida = antes; }
}

prueba("una adquisicion cuyas etapas se solapan exige elegir etapa", () => {
  conDisponibles([SPA_SOLAPADA], () => {
    assert.strictEqual(sacadas.adquisicionSeSolapa(SPA_SOLAPADA), true);
    /* Sin fase, el alcance esta incompleto: es el mismo «todo junto» que la
       apertura sin parametros no deja pasar. */
    assert.strictEqual(sacadas.alcanceElegidoEsValido("original", null), false,
      "la adquisicion sola alcanzaba para cargar la mezcla");
    assert.strictEqual(sacadas.alcanceElegidoEsValido("original", 3), true);
    assert.strictEqual(sacadas.alcanceElegidoEsValido("original", 1), true,
      "Formacion es una eleccion tan valida como Carrera");
  });
});

prueba("una fase inexistente o de otra adquisicion no se acepta", () => {
  conDisponibles([SPA_SOLAPADA, SEGUIDA], () => {
    assert.strictEqual(sacadas.alcanceElegidoEsValido("original", 9), false,
      "una fase que no existe se estaba aceptando");
    assert.strictEqual(sacadas.alcanceElegidoEsValido("original", 0), false);
    assert.strictEqual(sacadas.alcanceElegidoEsValido("original", -1), false);
    assert.strictEqual(sacadas.alcanceElegidoEsValido("original", 1.5), false);
    assert.strictEqual(sacadas.alcanceElegidoEsValido("original", NaN), false);
    assert.strictEqual(sacadas.alcanceElegidoEsValido("no_existe", 3), false);
    /* La fase 3 es de `original`; `libres` solo tiene la 1 y la 2. */
    assert.strictEqual(sacadas.alcanceElegidoEsValido("libres", 3), false,
      "una fase de otra adquisicion se estaba aceptando");
    assert.strictEqual(sacadas.alcanceElegidoEsValido("libres", 2), true);
  });
});

prueba("con etapas realmente continuas, la adquisicion sola alcanza", () => {
  conDisponibles([SEGUIDA], () => {
    assert.strictEqual(sacadas.adquisicionSeSolapa(SEGUIDA), false);
    assert.strictEqual(sacadas.alcanceElegidoEsValido("libres", null), true,
      "se le esta pidiendo elegir etapa a quien no lo necesita");
  });
});

prueba("«Todo» no se ofrece cuando las etapas se solapan", () => {
  /* El mecanismo minimo: si «Todo» no esta, no hay por donde volver a la
     mezcla. Se mira el marcado que arma el elector, no el texto del archivo:
     una condicion puede seguir escrita y no hacer nada. */
  const sinMarca = () => "";
  const conFecha = a => Object.assign({ vehiculos: 1, muestras_de_vuelta: 100,
                                        desde_utc: "2026-09-05T00:00:00Z" }, a);
  conDisponibles([SPA_SOLAPADA], () => {
    const html = sacadas.filaDeCorrida(conFecha(SPA_SOLAPADA), sinMarca);
    assert.strictEqual(html.indexOf('data-fase=""'), -1,
      "el elector sigue ofreciendo «Todo» para una captura cuyas etapas se solapan");
    assert.ok(html.indexOf("<b>Todo</b>") === -1);
    /* Las etapas si se ofrecen: hay que poder elegir una. */
    assert.ok(html.indexOf('data-fase="1"') !== -1);
    assert.ok(html.indexOf('data-fase="3"') !== -1);
    /* Y se dice por que falta «Todo». */
    assert.ok(html.indexOf("hay que elegir una") !== -1,
      "desaparece una opcion sin decir por que");
  });
  conDisponibles([SEGUIDA], () => {
    const html = sacadas.filaDeCorrida(conFecha(SEGUIDA), sinMarca);
    assert.ok(html.indexOf('data-fase=""') !== -1,
      "se quito «Todo» donde las etapas son continuas");
    assert.ok(html.indexOf("<b>Todo</b>") !== -1);
    assert.strictEqual(html.indexOf("hay que elegir una"), -1);
  });
});

prueba("elegir un alcance incompleto no pide datos: vuelve a preguntar", () => {
  const i = fuente.indexOf("function elegirCorrida(");
  assert.ok(i > 0, "no esta elegirCorrida");
  const cuerpo = fuente.slice(i, fuente.indexOf("\n}", i));
  const guarda = cuerpo.indexOf("alcanceElegidoEsValido");
  const carga = cuerpo.indexOf("cargarDatosDeSesion(");
  assert.ok(guarda > 0, "elegirCorrida no valida el alcance completo");
  assert.ok(guarda < carga,
    "se piden los datos antes de comprobar que el alcance este completo");
});

prueba("la direccion con adquisicion y sin fase no carga: pregunta", () => {
  const i = fuente.indexOf('const pedida = p.get("adquisicion");');
  assert.ok(i > 0, "no esta la lectura de la direccion");
  const bloque = fuente.slice(i, i + 1200);
  assert.ok(bloque.indexOf("alcanceElegidoEsValido(pedida, faseDelEnlace)") !== -1,
    "la direccion se acepta comprobando solo que la adquisicion exista");
  assert.ok(bloque.indexOf("fasePedida ? Number(fasePedida) : null") === -1,
    "la fase de la direccion se sigue convirtiendo sin validar");
});

prueba("una fase mal escrita en la direccion no se lee como un numero cualquiera", () => {
  const leer = sacadas.faseDeLaDireccion;
  assert.strictEqual(leer(null), null);
  assert.strictEqual(leer(""), null);
  assert.strictEqual(leer("   "), null);
  assert.strictEqual(leer("3"), 3);
  assert.strictEqual(leer(" 3 "), 3);
  assert.ok(Number.isNaN(leer("abc")), "«abc» se estaba leyendo como NaN silencioso");
  assert.ok(Number.isNaN(leer("3.5")));
  assert.ok(Number.isNaN(leer("-1")));
  assert.ok(Number.isNaN(leer("3x")));
});

prueba("al preguntar por la etapa se conserva la adquisicion que vino en el enlace", () => {
  const i = fuente.indexOf('const pedida = p.get("adquisicion");');
  const elector = fuente.indexOf("abrirElectorDeCorrida(ruta, apertura, s);", i);
  assert.ok(elector > i, "no se llega al elector desde la lectura de la direccion");
  const bloque = fuente.slice(i, elector);
  assert.ok(bloque.indexOf("corrida.adquisicion = pedida") !== -1,
    "la adquisicion del enlace se pierde al abrir el elector");
});

prueba("no se pide historico con el alcance sin resolver", () => {
  /* EL AGUJERO QUE QUEDABA. La apertura ya no cargaba con el alcance sin
     resolver, pero el transporte pide la vuelta bajo el cabezal por su cuenta,
     con 200 ms de retardo desde que arranca la pagina. Medido en Spa: la
     vuelta 1 se pedia a los 582 ms y `/adquisiciones` contestaba a los 953, de
     modo que se traia la mezcla con el elector abierto esperando. */
  const listo = sacadas.alcancePermitePedir;
  const antes = globalThis.corrida;
  /* Todavia no se sabe que adquisiciones hay. */
  globalThis.corrida = { adquisicion: null, fase: null, disponibles: null };
  assert.strictEqual(listo(), false, "se pedia antes de saber que se esta mirando");
  /* Ya se sabe, y no hay nada que elegir. */
  globalThis.corrida = { adquisicion: null, fase: null, disponibles: [SEGUIDA] };
  assert.strictEqual(listo(), true, "se dejo de pedir donde no hay ambiguedad");
  /* Ya se sabe, y hay que elegir etapa. */
  globalThis.corrida = { adquisicion: null, fase: null, disponibles: [SPA_SOLAPADA] };
  assert.strictEqual(listo(), false);
  globalThis.corrida = { adquisicion: "original", fase: null, disponibles: [SPA_SOLAPADA] };
  assert.strictEqual(listo(), false, "la adquisicion sola destrabo las consultas");
  globalThis.corrida = { adquisicion: "original", fase: 9, disponibles: [SPA_SOLAPADA] };
  assert.strictEqual(listo(), false, "una etapa que no existe destrabo las consultas");
  globalThis.corrida = { adquisicion: "original", fase: 3, disponibles: [SPA_SOLAPADA] };
  assert.strictEqual(listo(), true);
  /* Una API que no tiene la ruta declara la lista vacia y se sigue como antes. */
  globalThis.corrida = { adquisicion: null, fase: null, disponibles: [] };
  assert.strictEqual(listo(), true, "una API sin adquisiciones dejaria de cargar");
  globalThis.corrida = antes;
});

prueba("la compuerta esta en las dos consultas de historico", () => {
  [["asegurarVuelta", "alcanceResuelto()"],
   ["asegurarPosiciones", "alcancePermitePedir()"]].forEach(([nombre, compuerta]) => {
    const i = fuente.indexOf("function " + nombre + "(");
    assert.ok(i > 0, "no esta " + nombre);
    const cabeza = fuente.slice(i, i + 420);
    assert.ok(cabeza.indexOf(compuerta) !== -1,
      nombre + " pide sin comprobar que el alcance este resuelto");
  });
});

prueba("si no hay ruta de adquisiciones se declara la lista vacia", () => {
  /* Sin esto, la compuerta dejaria a una API mas vieja sin cargar nunca. */
  const i = fuente.indexOf("if (fueAnulada(e)) return;");
  assert.ok(i > 0, "no esta el catch de adquisiciones");
  const bloque = fuente.slice(i, i + 200);
  assert.ok(bloque.indexOf("corrida.disponibles = []") !== -1,
    "al fallar la consulta la compuerta queda cerrada para siempre");
});

prueba("la direccion se lee aunque la sesion no este mezclada", () => {
  /* El enlace que deja `elegirCorrida` trae `adquisicion` y `fase`. Se leia
     dentro de la rama de `mezclada`, asi que con una sola adquisicion el
     enlace decia `fase=3` y el tablero cargaba todo junto: quien recargaba
     creia estar mirando la carrera y estaba mirando la mezcla. */
  const url = fuente.indexOf('const pedida = p.get("adquisicion");');
  const salida = fuente.indexOf("if (!pedida && !alcanceEsAmbiguo()) {");
  assert.ok(url > 0 && salida > 0, "falta alguna de las dos");
  assert.ok(url < salida,
    "la direccion se sigue leyendo despues de decidir cargar sin alcance");
});

prueba("elegir no obliga a editar la direccion, pero la refleja", () => {
  const i = fuente.indexOf("cont.querySelectorAll(\"button[data-corrida]\")");
  assert.ok(i > 0, "no estan los botones del elector");
  const botones = fuente.slice(i, i + 400);
  assert.ok(botones.indexOf("addEventListener(\"click\"") !== -1,
    "las opciones del elector no responden al clic");
  assert.ok(botones.indexOf("elegirCorrida(") !== -1,
    "el clic no lleva al mismo sitio que el cambio de etapa");
  /* El clic del elector y el cambio desde el encabezado hacen lo mismo, y lo
     hacen en un solo sitio: si fueran dos caminos, uno de los dos se olvidaria
     de actualizar la direccion o de soltar los datos viejos. */
  const j = fuente.indexOf("function elegirCorrida(");
  const bloque = fuente.slice(j, fuente.indexOf("\n}", j));
  assert.ok(bloque.indexOf("history.replaceState") !== -1,
    "elegir no deja la direccion apuntando a lo elegido");
  assert.ok(bloque.indexOf("cargarDatosDeSesion") !== -1,
    "elegir no dispara la carga");
});

prueba("el alcance elegido queda declarado en el documento", () => {
  /* Para poder comprobar desde afuera ---una prueba, el banco de medicion---
     que lo que se pide es lo que se eligio, en vez de suponerlo. */
  assert.ok(fuente.indexOf("dataset.alcanceEnCurso") !== -1,
    "el tablero no declara que alcance esta mirando");
});

prueba("lo secundario espera a que lo esencial este resuelto", () => {
  /* Cuatro consultas pesadas a la vez no terminan antes: terminan todas tarde.
     Medido sobre Spa: 45,3 / 45,8 / 41,2 / 42,5 s cada una, contra 3,07 / 2,59
     / 0,01 s de a una. */
  assert.ok(fuente.indexOf("function laEsencialTermino()") !== -1,
    "no esta el gatillo que libera lo secundario");
  const i = fuente.indexOf("function cuandoHayaGrafico(");
  const bloque = fuente.slice(i, i + 400);
  assert.ok(bloque.indexOf("_esencialResuelta") !== -1,
    "la espera de cortesia sigue soltandose solo por reloj");
});


// ------------------------------------------------ duraciones que se entienden

prueba("una carrera de casi una hora no se dice en segundos", () => {
  /* «2.827 s» obliga a dividir por sesenta mentalmente para saber si son
     minutos o casi una hora. */
  assert.strictEqual(duracionCorta(2827.103), "47 min 07 s");
});

prueba("un tramo corto sigue en segundos", () => {
  assert.strictEqual(duracionCorta(7.905), "8 s");
});

prueba("los segundos se rellenan con cero para que las cifras se alineen", () => {
  assert.strictEqual(duracionCorta(189.02), "3 min 09 s");
});

prueba("mas de una hora se dice en horas", () => {
  assert.strictEqual(duracionCorta(3 * 3600 + 5 * 60), "3 h 05 min");
});

prueba("una duracion que no se midio no inventa un numero", () => {
  assert.strictEqual(duracionCorta(null), "0 s");
  assert.strictEqual(duracionCorta(undefined), "0 s");
});

// ------------------------------------------------ que es cada etapa

prueba("la carrera se explica como donde empiezan las vueltas", () => {
  assert.ok(queEsLaFase(SPA, SPA.fases[2]).indexOf("largada") !== -1);
});

prueba("la formacion se explica como lo previo a la largada", () => {
  assert.ok(queEsLaFase(SPA, SPA.fases[0]).indexOf("formación") !== -1);
});

prueba("con una sola etapa se dice que el reloj no se reinicia", () => {
  const a = { fases: [{ orden: 1, duracion_de_captura_s: 78 }] };
  assert.ok(queEsLaFase(a, a.fases[0]).indexOf("no se reinicia") !== -1);
});

// ------------------------------------------------ el menu, leido del texto

prueba("con una sola etapa no se ofrece dos veces lo mismo", () => {
  /* «Todo» y «Fase única» seleccionan las mismas filas: dos botones que hacen
     lo mismo obligan a pararse a decidir entre ellos para nada. */
  const i = fuente.indexOf("const fases = (etapas.length <= 1 ? [] : etapas).map(f =>");
  assert.ok(i > 0, "el elector sigue ofreciendo la fase única además de «Todo»");
});

prueba("lo elegido se marca, y solo lo elegido", () => {
  const i = fuente.indexOf("const elegida = (clave, f) =>");
  assert.ok(i > 0, "no está la marca de lo elegido");
  const bloque = fuente.slice(i, i + 320);
  assert.ok(bloque.indexOf('data-elegida="si"') !== -1, "no marca la opción elegida");
  assert.ok(bloque.indexOf("corrida.fase || null) === (f || null)") !== -1,
    "«Todo» y la fase 1 no se distinguen: quedarían marcadas las dos");
});

prueba("todas las opciones usan el mismo estilo de fondo", () => {
  /* Con «Todo» en estilo principal parecía elegido en las tres filas a la vez,
     porque el relleno de acento significaba dos cosas distintas. */
  const i = fuente.indexOf('data-fase=""');
  const bloque = fuente.slice(Math.max(0, i - 220), i);
  assert.ok(bloque.indexOf("boton secundario opcion-fase") !== -1,
    "el botón «Todo» vuelve a estar en estilo principal");
});

// ------------------------------------------------ cambiar la eleccion

prueba("cambiar de etapa suelta lo de la etapa anterior", () => {
  /* Las vueltas, las series, las posiciones y el trazado en pantalla son de la
     etapa anterior: sin soltarlos, la primera vuelta de la carrera queda
     dibujada sobre el trazado de la formación. */
  const i = fuente.indexOf("function elegirCorrida(");
  assert.ok(i > 0, "no está la función que cambia de etapa");
  const bloque = fuente.slice(i, fuente.indexOf("\n}", i));
  assert.ok(bloque.indexOf("olvidarLoDeLaCorrida()") !== -1,
    "cambiar de etapa no olvida los datos de la anterior");
  assert.ok(bloque.indexOf("nuevaSesionEnCurso()") !== -1,
    "cambiar de etapa no anula lo que quedó pedido de la anterior");
  assert.ok(bloque.indexOf("cargarDatosDeSesion") !== -1,
    "cambiar de etapa no vuelve a pedir los datos");
});

prueba("el olvido no borra la identidad de la sesion", () => {
  /* Al cambiar de etapa la sesión es la misma: si el olvido tocara
     `estado.abierta` o `sesionAbierta`, el tablero quedaría sin saber qué
     tiene abierto. */
  const i = fuente.indexOf("function olvidarLoDeLaCorrida()");
  assert.ok(i > 0, "no está el olvido");
  const j = fuente.indexOf("\n}", i);
  const cuerpo = fuente.slice(i, j);
  assert.ok(cuerpo.indexOf("estado.abierta") === -1, "el olvido borra la sesión abierta");
  assert.ok(cuerpo.indexOf("sesionAbierta") === -1, "el olvido borra el identificador");
  assert.ok(cuerpo.indexOf("_vigilanciaPedida") !== -1,
    "sin soltar la vigilancia, el panel seguiría mostrando lo de la etapa anterior");
});

prueba("hay un boton para volver a elegir, y se oculta si no hay que elegir", () => {
  const i = fuente.indexOf("function pintarBotonDeCorrida()");
  assert.ok(i > 0, "no está el botón del encabezado");
  const bloque = fuente.slice(i, i + 700);
  assert.ok(bloque.indexOf("b.hidden = !hay") !== -1,
    "el botón no se oculta cuando la sesión tiene una sola adquisición");
  assert.ok(bloque.indexOf("etiquetaDeCorrida()") !== -1,
    "el botón no dice qué etapa se está mirando");
});

prueba("el boton reabre el menu por el camino de una persona", () => {
  const i = fuente.indexOf("function controlesDelElector()");
  assert.ok(i > 0, "no están los controles del elector");
  const bloque = fuente.slice(i, i + 900);
  assert.ok(bloque.indexOf('getElementById("btn-corrida")') !== -1,
    "el botón del encabezado no está conectado");
  assert.ok(bloque.indexOf("abrirElectorDeCorrida") !== -1,
    "el botón no vuelve a abrir el elector");
});

prueba("se recuerda con que volver a preguntar aunque el elector no llegue a abrirse", () => {
  /* Si la dirección ya traía una elección, el elector no se abre y el botón del
     encabezado se quedaría sin nada que reabrir. */
  const i = fuente.indexOf("corrida.mezclada = !!a.mezclada;");
  assert.ok(i > 0, "no está el punto donde llegan las adquisiciones");
  /* SIN UN TOPE FIJO DE CARACTERES. Miraba los primeros quinientos y se rompía
     en cuanto la continuación crecía ---al agregarle la parrilla, sin ir más
     lejos---, sin que lo que quiere comprobar hubiera cambiado. Lo que importa
     es que el contexto se recuerde **al llegar la respuesta** y no recién
     cuando alguien abre el elector: se comprueba contra dónde se abre. */
  const abre = fuente.indexOf("abrirElectorDeCorrida(ruta, apertura, s)", i);
  const recuerda = fuente.indexOf("_contextoDeCorrida = { ruta: ruta, s: s }", i);
  assert.ok(recuerda !== -1, "no se recuerda el contexto salvo al abrir el elector");
  assert.ok(abre === -1 || recuerda < abre,
    "el contexto se recuerda recién al abrir el elector");
});

if (process.exitCode) {
  console.error("\n" + hechas + " pruebas pasaron; hubo fallos.");
} else {
  console.log(hechas + " pruebas de eleccion de adquisicion: OK");
}
