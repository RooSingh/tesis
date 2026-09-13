/* La mitad que va del navegador al disco del servidor.
 *
 * CRITERIO. Como los demas arneses, las funciones se **extraen del `app.js` que
 * se publica** y se ejecutan; no se copian.
 *
 * QUE PASABA. Los botones de importar **no subian nada**. Pedian una
 * `session_key` o unos nombres de segmento por `window.prompt` y el servidor
 * procesaba lo que **ya estaba en su disco**: quien no hubiera copiado el
 * archivo a la maquina por su cuenta recibia un 404 sobre una sesion que nunca
 * existio. El boton decia «importar» y hacia «procesar lo que ya trajiste».
 *
 * LAS TRES COSAS QUE ESTE ARNES CUIDA, y las tres vienen de un defecto real:
 *
 * 1. **El orden del par no es una preferencia.** Los metadatos se aceptan solo
 *    si la captura que describen ya esta subida; al reves el servidor los
 *    rechaza siempre. Elegir los dos archivos juntos no dice en que orden los
 *    entrega el navegador.
 * 2. **Lo que hay que convertir se avisa antes de subir.** Un `rlog.zst` de
 *    commaCarSegments es el archivo que tiene quien viene de esa fuente. Subir
 *    cientos de megabytes para recibir «no se reconoce el contenido» es gastar
 *    la red para no decir nada.
 * 3. **Lo que no se puede procesar se declara, no se simula.** De las tres
 *    clases que el servidor acepta, dos todavia no tienen a donde ir: la
 *    captura del simulador no tiene ruta que la republique y el paquete
 *    comprimido no se descomprime. Un boton que dice «listo» sobre eso miente.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");

const APP = path.join(__dirname, "..", "..", "dashboard", "app.js");
const INDICE = path.join(__dirname, "..", "..", "dashboard", "index.html");
const fuenteApp = fs.readFileSync(APP, "utf8");
const indice = fs.readFileSync(INDICE, "utf8");

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
  // Las constantes de este bloque son objetos y arreglos de varias lineas: se
  // corta en el `;` que cierra, no en el primero que aparezca.
  let i = fuenteApp.indexOf("=", desde) + 1;
  let nivel = 0;
  for (; i < fuenteApp.length; i++) {
    const c = fuenteApp[i];
    if (c === "{" || c === "[") nivel++;
    else if (c === "}" || c === "]") nivel--;
    else if (c === ";" && nivel === 0) return fuenteApp.slice(desde, i + 1);
  }
  throw new Error("no cierra la constante " + nombre);
}

const CONSTANTES = ["EXTENSIONES_QUE_HAY_QUE_CONVERTIR", "SUFIJO_ACOMPANANTE",
                    "EXTENSION_DEL_ACOMPANANTE"];
const NOMBRES = ["extensionDe", "esAcompanante", "ordenDeSubida",
                 "extensionesQueSeAceptan", "comoSeProcesa", "tamanoLegible"];

const sacadas = new Function(
  CONSTANTES.map(constante).join("\n") + "\n" +
  "function cifra(n, d) { return n.toFixed(d); }\n" +
  NOMBRES.map(extraer).join("\n\n") +
  "\nreturn { " + NOMBRES.concat(CONSTANTES).join(", ") + " };")();

const { extensionDe, esAcompanante, ordenDeSubida, extensionesQueSeAceptan,
        comoSeProcesa, tamanoLegible } = sacadas;

let hechas = 0;
//: Las que devuelven una promesa se esperan; las demas siguen siendo directas.
const pendientes = [];
function prueba(titulo, fn) {
  const fallo = e => {
    process.exitCode = 1;
    console.error("FALLA  " + titulo + "\n       " + (e && e.message));
  };
  let r;
  try { r = fn(); } catch (e) { fallo(e); return; }
  if (r && typeof r.then === "function") {
    pendientes.push(r.then(() => { hechas++; }, fallo));
    return;
  }
  hechas++;
}

/* -------- lo que se ofrece en el dialogo lo dice el servidor -------- */

prueba("las extensiones salen de la respuesta y no de una lista escrita", () => {
  /* Escribirlas en el tablero seria tener el mismo dato en dos sitios: el dia
     que el servidor acepte una clase mas, el dialogo no la ofreceria. */
  const contestado = {
    formatos: [{ extension: ".canraw" }, { extension: ".f1raw" },
               { extension: ".zip" }],
  };
  const lista = extensionesQueSeAceptan(contestado);
  assert.ok(lista.indexOf(".canraw") !== -1);
  assert.ok(lista.indexOf(".f1raw") !== -1);
  assert.ok(lista.indexOf(".zip") !== -1);
});

prueba("EL METADATO SE OFRECE COMO `.json`, QUE ES SU EXTENSION DE VERDAD", () => {
  /* `.meta.json` es una **convencion de nombre** y no una extension. El dialogo
     del sistema resuelve cada termino de `accept` a un tipo conocido y ese no
     lo es: en macOS los metadatos salian **en gris, imposibles de elegir**, de
     modo que no habia forma de subir el par. Reportado el 2026-09-13 con una
     captura del selector. */
  const lista = extensionesQueSeAceptan({ formatos: [{ extension: ".canraw" }] });
  assert.ok(lista.indexOf(".json") !== -1,
    "el dialogo no deja elegir los metadatos: " + lista.join(","));
  assert.strictEqual(lista.indexOf(".meta.json"), -1,
    "volvio el termino que el selector no entiende");
});

prueba("y la convencion de nombre sigue siendo la que empareja el par", () => {
  /* Son dos trabajos distintos: uno es el filtro del dialogo y el otro la regla
     que decide que es un metadato y en que orden se sube. Mezclarlos fue el
     defecto. */
  assert.strictEqual(sacadas.SUFIJO_ACOMPANANTE, ".meta.json");
  assert.strictEqual(sacadas.EXTENSION_DEL_ACOMPANANTE, ".json");
  assert.strictEqual(esAcompanante("x.canraw.meta.json"), true);
  assert.strictEqual(esAcompanante("cualquiera.json"), false,
    "un json suelto dejo de distinguirse de un metadato");
});

prueba("sin respuesta no se inventa un filtro", () => {
  assert.deepStrictEqual(extensionesQueSeAceptan(null), [".json"]);
  assert.deepStrictEqual(extensionesQueSeAceptan({}), [".json"]);
});

/* -------- el orden del par -------- */

prueba("EL DEFECTO QUE HABRIA: los metadatos primero fallan siempre", () => {
  /* El servidor los acepta **solo si la captura que describen ya esta**. Elegir
     los dos juntos no dice en que orden los entrega el navegador. */
  const meta = { name: "TOYOTA_RAV4_TSS2_abc.canraw.meta.json", size: 900 };
  const captura = { name: "TOYOTA_RAV4_TSS2_abc.canraw", size: 102408 };
  assert.deepStrictEqual(ordenDeSubida([meta, captura]).map(a => a.name),
                         [captura.name, meta.name]);
  assert.deepStrictEqual(ordenDeSubida([captura, meta]).map(a => a.name),
                         [captura.name, meta.name]);
});

prueba("con dos pares, cada captura sigue yendo antes que su metadato", () => {
  const lista = ordenDeSubida([
    { name: "b.f1raw.meta.json" }, { name: "a.f1raw" },
    { name: "a.f1raw.meta.json" }, { name: "b.f1raw" },
  ]).map(a => a.name);
  assert.ok(lista.indexOf("a.f1raw") < lista.indexOf("a.f1raw.meta.json"));
  assert.ok(lista.indexOf("b.f1raw") < lista.indexOf("b.f1raw.meta.json"));
});

prueba("reconocer un metadato no depende de mayusculas ni del resto del nombre", () => {
  assert.strictEqual(esAcompanante("x.canraw.META.json"), true);
  assert.strictEqual(esAcompanante("x.canraw"), false);
  assert.strictEqual(esAcompanante("meta.json.canraw"), false);
  assert.strictEqual(esAcompanante(""), false);
});

prueba("sin archivos no hay orden que armar", () => {
  assert.deepStrictEqual(ordenDeSubida(null), []);
  assert.deepStrictEqual(ordenDeSubida([]), []);
});

/* -------- lo que hay que convertir se avisa antes -------- */

prueba("EL REGISTRO DE OPENPILOT SE AVISA ANTES DE SUBIRLO", () => {
  /* Es el archivo que tiene quien viene de commaCarSegments. El servidor lo
     rechaza bien ---no lleva el numero magico--- pero despues de recibirlo. */
  const aviso = sacadas.EXTENSIONES_QUE_HAY_QUE_CONVERTIR[extensionDe("rlog.zst")];
  assert.ok(aviso, "un rlog.zst no dispara ningun aviso previo");
  assert.ok(/extraer_can\.py/.test(aviso),
    "el aviso no dice como convertirlo: " + aviso);
});

prueba("la extension se lee como la lee el filtro, en minusculas", () => {
  assert.strictEqual(extensionDe("CAPTURA.CANRAW"), ".canraw");
  assert.strictEqual(extensionDe("sin_extension"), "");
  assert.strictEqual(extensionDe(".oculto"), "");
  assert.strictEqual(extensionDe(null), "");
});

/* -------- que se hace con lo subido -------- */

prueba("EL PLAN LO DECLARA EL SERVIDOR Y NO SE PARTE NINGUN NOMBRE", () => {
  /* Antes se reconstruia `{segmentos, plataforma}` partiendo
     `TOYOTA_RAV4_TSS2_sample_01.canraw` por un prefijo escrito en este archivo:
     un acuerdo entre dos lados guardado en uno solo. Ahora sale del
     `.meta.json`, que declara la plataforma y el segmento. */
  const plan = comoSeProcesa({
    clase: "metadatos",
    procesar: { ruta: "/can/importar", metodo: "POST",
                cuerpo: { segmentos: ["tramo_9"], plataforma: "OTRA_PLATAFORMA",
                          etapa: "cargar" },
                motivo: "la plataforma y el segmento salen de lo que la captura declara" },
  });
  assert.strictEqual(plan.ruta, "/can/importar");
  assert.deepStrictEqual(plan.cuerpo, {
    segmentos: ["tramo_9"], plataforma: "OTRA_PLATAFORMA", etapa: "cargar" });
  assert.ok(/salen de lo que la captura declara/.test(plan.motivo));
});

prueba("una plataforma con guion bajo de mas ya no rompe nada", () => {
  /* Es el caso que hacia inevitable el cambio: partir por prefijo no puede
     saber donde termina `OTRA_PLATAFORMA_RARA` y empieza el segmento. */
  const plan = comoSeProcesa({
    procesar: { ruta: "/can/importar", cuerpo: { segmentos: ["a_b_c"] } },
  });
  assert.deepStrictEqual(plan.cuerpo.segmentos, ["a_b_c"]);
  assert.strictEqual(plan.metodo, "POST", "el metodo por omision dejo de ser POST");
});

prueba("y cuando el servidor dice que no hay como, se muestra su motivo", () => {
  /* El paquete comprimido hasta que se lo descomprima, por ejemplo. El motivo
     es del servidor: escribir uno propio seria adivinar por que. */
  const plan = comoSeProcesa({
    clase: "paquete_openf1",
    procesar: { ruta: null, motivo: "hay que descomprimirlo para saber que sesion es" },
  });
  assert.ok(!plan.ruta);
  assert.ok(/descomprimirlo/.test(plan.porQueNo), plan.porQueNo);
});

prueba("NO SE INVENTA UN RESPALDO CUANDO EL SERVIDOR NO DECLARA NADA", () => {
  /* Derivar «por las dudas» seria devolver el acuerdo implicito que se acaba de
     sacar, y encima escondido tras un `if`. */
  const plan = comoSeProcesa({
    clase: "can_crudo",
    guardado: "/srv/datasets/can/capturas/TOYOTA_RAV4_TSS2_sample_01.canraw",
  });
  assert.ok(!plan.ruta, "volvio a derivar el plan del nombre del archivo");
  assert.ok(/no declaró/.test(plan.porQueNo), plan.porQueNo);
});

prueba("EL METADATO NO ES LO QUE SE PROCESA, Y SE VIO PROBANDOLO", () => {
  /* El `.meta.json` va segundo por obligacion ---el servidor lo acepta solo si
     la captura ya esta--- de modo que su respuesta es siempre la ultima. Guardar
     «la ultima» hacia que el plan se calculara sobre la clase `metadatos` y un
     par entero y verificado terminara diciendo «no hay un procesamiento
     declarado para esta clase». Se vio subiendo el par de verdad contra la API
     viva el 2026-09-13. */
  const i = fuenteApp.indexOf("function subirLoElegido(");
  const cuerpo = fuenteApp.slice(i, fuenteApp.indexOf("\n}", i));
  assert.ok(/respuesta\.procesar\) ultima = respuesta/.test(cuerpo),
    "no se conserva la respuesta que trae el plan de procesamiento");
  assert.ok(comoSeProcesa({ clase: "metadatos" }).porQueNo,
    "un metadato sin plan declarado no puede procesarse solo");
});

prueba("una respuesta sin plan no dispara nada", () => {
  assert.ok(comoSeProcesa({}).porQueNo);
  assert.ok(comoSeProcesa(null).porQueNo);
  assert.ok(comoSeProcesa({ clase: "inventada" }).porQueNo);
});

prueba("UNA VERIFICACION QUE NO PASA CORTA EL FLUJO", () => {
  /* El servidor contesta **200** y lo dice en el cuerpo: `verificacion.acepta`
     en falso. Sin mirarlo, la cadena seguia hasta el plan y el ultimo renglon
     afirmaba que la captura estaba guardada y verificada tres renglones debajo
     de «llegaron 108 bytes de los 99.999 que el archivo declara». Se vio
     subiendo un par truncado contra la API viva el 2026-09-13. */
  const i = fuenteApp.indexOf("function subirLoElegido(");
  const cuerpo = fuenteApp.slice(i, fuenteApp.indexOf("\n}", i));
  assert.ok(/huboRechazo = true/.test(cuerpo),
    "un 200 que declara que no verifica pasa como si hubiera verificado");
  assert.ok(/if \(huboRechazo\)/.test(cuerpo),
    "se sigue al plan de procesamiento con una verificacion que no paso");
});

prueba("y ningun texto propio afirma una verificacion que no ocurrio", () => {
  /* «Guardada y verificada» era cierto para el caso feliz y falso para el otro,
     y se escribia igual en los dos. Hoy los motivos los redacta el servidor: lo
     que queda de este lado no puede afirmar una verificacion. */
  assert.ok(!/verificad/.test(comoSeProcesa({}).porQueNo));
  assert.ok(!/verificad/.test(comoSeProcesa({ procesar: { ruta: null } }).porQueNo));
});

/* -------- la barra, y por que no es `fetch` -------- */

prueba("LA SUBIDA VA POR XHR, Y ESA ES LA UNICA RAZON", () => {
  /* `fetch` no informa la progresion de subida. El paquete de OpenF1 mas grande
     son 273,4 MB: una barra que no avanza y una que no existe se ven igual. */
  const i = fuenteApp.indexOf("function subirUnArchivo(");
  assert.notStrictEqual(i, -1, "no esta subirUnArchivo");
  const cuerpo = fuenteApp.slice(i, i + 2200);
  assert.ok(/new XMLHttpRequest\(\)/.test(cuerpo), "volvio a usar fetch");
  assert.ok(/xhr\.upload\.onprogress/.test(cuerpo), "no informa la progresion");
  assert.ok(/xhr\.send\(archivo\)/.test(cuerpo),
    "el cuerpo dejo de ir crudo: multipart exige python-multipart, que no esta");
  assert.ok(/lengthComputable/.test(cuerpo),
    "dibuja una fraccion aunque el navegador no sepa el total");
});

prueba("el tamano se escribe como se lee", () => {
  assert.strictEqual(tamanoLegible(0), "0 B");
  assert.strictEqual(tamanoLegible(512), "512 B");
  assert.ok(/kB$/.test(tamanoLegible(2048)));
  assert.ok(/MB$/.test(tamanoLegible(273 * 1024 * 1024)));
  assert.ok(/GB$/.test(tamanoLegible(2 * 1024 * 1024 * 1024)));
});

/* -------- el trabajo se sigue, no se dispara y se olvida -------- */

prueba("el procesamiento se sigue hasta que deja de estar en curso", () => {
  const i = fuenteApp.indexOf("function seguirTrabajo(");
  assert.notStrictEqual(i, -1, "no esta seguirTrabajo");
  const cuerpo = fuenteApp.slice(i, i + 900);
  assert.ok(/\/trabajos\//.test(cuerpo), "no consulta el estado del trabajo");
  assert.ok(/en_curso/.test(cuerpo), "no distingue un trabajo que sigue corriendo");
  assert.ok(/restantes <= 1/.test(cuerpo),
    "pregunta para siempre: los trabajos viven en memoria del servidor y se " +
    "pierden al reiniciarlo");
});

prueba("EL TRABAJO SE SIGUE POR `trabajo`, QUE ES COMO SE LLAMA", () => {
  /* Se leia `t.id`, que no existe. **Todos** los procesamientos informaban «el
     servidor aceptó el pedido y no devolvió un trabajo que seguir» y ninguno se
     seguia nunca, mientras el trabajo corria igual: el tablero perdia su
     resultado, incluido el fallo.

     Se vio el 2026-09-13 reinyectando una captura de Shanghai. El trabajo
     corrio 123 s y termino en `fallido` porque esa sesion ya estaba en la base
     y el guion se nego a duplicarla ---la negativa es correcta--- y nada de eso
     llego a la pantalla. */
  const i = fuenteApp.indexOf("function subirLoElegido(");
  const cuerpo = fuenteApp.slice(i, fuenteApp.indexOf("\n}", i));
  assert.ok(/const cual = t && t\.trabajo;/.test(cuerpo),
    "volvio a leerse un campo que la respuesta no trae");
  /* La expresion y no el nombre: el comentario que explica por que se fue lo
     nombra, y un guardian que se rompe con su propia explicacion obliga a
     borrar la explicacion. */
  assert.ok(!/!t\.id/.test(cuerpo), "quedo la lectura del nombre inventado");
  assert.ok(!/seguirTrabajo\(t\.id/.test(cuerpo));
});

prueba("NINGUN PASO SE QUEDA CONTRADICIENDO AL SIGUIENTE", () => {
  /* «Procesando…» quedaba en pantalla debajo de «el servidor no devolvió un
     trabajo que seguir»: desde afuera se lee como que el trabajo sigue
     corriendo, y se ve igual que uno colgado. Cada desenlace reemplaza al paso
     en curso en vez de agregarse. */
  const i = fuenteApp.indexOf("function subirLoElegido(");
  const cuerpo = fuenteApp.slice(i, fuenteApp.indexOf("\n}", i));
  const enCurso = (cuerpo.match(/anotarPasoDeSubida\("Procesando…"/g) || []).length;
  const quitados = (cuerpo.match(/_quitarUltimoPaso\(\)/g) || []).length;
  assert.strictEqual(enCurso, 1, "hay mas de un paso en curso que anotar");
  assert.ok(quitados >= 2,
    "algun desenlace se agrega sin sacar el «Procesando…» de arriba");
});

prueba("y el paso en curso lleva un giro que se apaga solo", () => {
  /* Un texto quieto no distingue un trabajo que avanza de uno colgado. El giro
     lo enciende **el estado del paso**, no un temporizador aparte que haya que
     acordarse de parar. */
  const i = fuenteApp.indexOf("function _pintarPasosDeSubida(");
  const cuerpo = fuenteApp.slice(i, fuenteApp.indexOf("\n}", i));
  assert.ok(/p\.estado === "en-curso" \? '<i class="girando"/.test(cuerpo),
    "el paso en curso no se distingue de los demas");
  const css = fs.readFileSync(
    path.join(__dirname, "..", "..", "dashboard", "styles.css"), "utf8");
  assert.ok(/prefers-reduced-motion[\s\S]*?\.girando \{ animation: none/.test(css),
    "quien pidio menos movimiento igual recibe el giro");
});

prueba("la verificacion se rotula con la captura, no con su metadato", () => {
  /* El servidor compara la captura cuando recibe su metadato. Rotularlo con el
     nombre del metadato decia «x.canraw.meta.json — llegaron 200.000 bytes de
     los 4.769.640»: ese archivo pesa un kilobyte y llego entero. */
  const i = fuenteApp.indexOf("function subirLoElegido(");
  const cuerpo = fuenteApp.slice(i, fuenteApp.indexOf("\n}", i));
  assert.ok(/respuesta\.describe_a/.test(cuerpo),
    "la verificacion vuelve a rotularse con el archivo equivocado");
});

prueba("y al terminar se refresca el catalogo", () => {
  /* Una sesion que no entra al catalogo existe en la base y **no se puede
     abrir**: paso el 2026-09-12 con dos sesiones. */
  const i = fuenteApp.indexOf("function subirLoElegido(");
  const cuerpo = fuenteApp.slice(i, fuenteApp.indexOf("\n}", i));
  assert.ok(/refrescarCatalogo\(/.test(cuerpo),
    "se procesa y el catalogo queda sin la sesion nueva");
});

prueba("EL MOTIVO DEL FALLO SE MUESTRA, NO SE REMITE A UN ARCHIVO", () => {
  /* Remitia a `/app/logs/...`, una ruta **dentro del contenedor** que quien
     mira el tablero no puede abrir. Y `error` se arma con la ultima linea del
     registro, que suele ser el **remedio**: la causa esta antes. Se muestran
     las ultimas lineas tal como el servidor las leyo, sin elegir cual, porque
     elegir una seria volver a perder la otra. */
  const i = fuenteApp.indexOf("function subirLoElegido(");
  const cuerpo = fuenteApp.slice(i, fuenteApp.indexOf("\n}", i));
  assert.ok(/t\.final_del_registro/.test(cuerpo),
    "el motivo sigue siendo una ruta que nadie puede abrir");
  assert.ok(/filter\(l => String\(l\)\.trim\(\)\)/.test(cuerpo),
    "las lineas vacias del cierre empujan al motivo fuera de lo que se muestra");
});

prueba("NO SE ANUNCIA QUE APARECIO SIN HABER MIRADO", () => {
  /* Decia «Listo: la sesión tiene que aparecer en Abrir sesión guardada» a los
     cuatro segundos, sin comprobar nada. Se vio el 2026-09-13 cargando un
     segmento del bus: el trabajo termino bien, **las 57.890 filas entraron en
     la base** y la sesion no estaba en el catalogo. Quien leyo el cartel la fue
     a buscar y no estaba. */
  const i = fuenteApp.indexOf("function subirLoElegido(");
  const cuerpo = fuenteApp.slice(i, fuenteApp.indexOf("\n}", i));
  assert.ok(/refrescarCatalogo\(/.test(cuerpo),
    "no se mira si la sesion aparecio");
  assert.ok(/comoQuedoElCatalogo\(/.test(cuerpo),
    "el desenlace no se decide mirando si la sesion esta");
  /* La cadena que se escribe y no la que la explica: el comentario que cuenta
     por que se fue la nombra, y un guardian que se rompe con su propia
     explicacion obliga a borrar la explicacion. Tercera vez hoy. */
  assert.ok(!/"Listo: la sesión tiene que aparecer/.test(cuerpo),
    "volvio la promesa que no se comprueba");
});

/* El banco del refresco: `pedir` contesta lo que se le diga y las esperas se
   cuentan en vez de dormirse. Lo que interesa es **cuantas veces pregunta**. */
function bancoDelRefresco(lista, sesionesIniciales) {
  const visto = { pedidos: 0, esperas: 0, final: null };
  const cuerpo = [
    "let SESIONES = sesionesIniciales;",
    "const render = () => {};",
    "const pedir = () => { visto.pedidos++; return Promise.resolve({ sesiones: lista }); };",
    "const setTimeout = (f) => { visto.esperas++; f(); };",
    extraer("refrescarCatalogo"),
    "return refrescarCatalogo;",
  ].join("\n");
  const fn = new Function("lista", "sesionesIniciales", "visto", cuerpo)(
    lista, sesionesIniciales, visto);
  return [fn, visto];
}

prueba("EL REFRESCO PARA CUANDO ESTA LO QUE ESPERA, aunque la lista no crezca", () => {
  /* Recontar una sesion tarda segundos, y el largo de la lista **no cambia
     cuando la sesion ya estaba**. Esperando un cambio ahi se gastaban los seis
     intentos para terminar diciendo que no aparecio. */
  const lista = [{ session_id: "can:segmento:sample_01", filas: 57890 }];
  const [refrescar, visto] = bancoDelRefresco(lista, lista);
  refrescar(6, r => { visto.final = r; }, ["can:segmento:sample_01"]);
  return Promise.resolve().then(() => {
    assert.strictEqual(visto.pedidos, 1,
      "insistio " + visto.pedidos + " veces sobre una sesion que ya estaba");
    assert.strictEqual(visto.esperas, 0);
  });
});

prueba("y sigue insistiendo mientras la sesion declarada no aparece", () => {
  const [refrescar, visto] = bancoDelRefresco([], []);
  refrescar(3, r => { visto.final = r; }, ["can:segmento:sample_01"]);
  return Promise.resolve().then(() => {}).then(() => {}).then(() => {}).then(() => {
    assert.ok(visto.pedidos > 1,
      "no volvio a preguntar por una sesion que todavia no esta");
  });
});

prueba("sin sesion declarada se conserva el criterio viejo: que la lista crezca", () => {
  const lista = [{ session_id: "a", filas: 1 }, { session_id: "b", filas: 1 }];
  const [refrescar, visto] = bancoDelRefresco(lista, [{ session_id: "a", filas: 1 }]);
  refrescar(6, r => { visto.final = r; }, []);
  return Promise.resolve().then(() => {
    assert.strictEqual(visto.pedidos, 1);
    assert.strictEqual(visto.final.cambio, true);
  });
});

prueba("el refresco devuelve la lista, que es contra lo que se decide", () => {
  const lista = [{ session_id: "x", filas: 1 }];
  const [refrescar, visto] = bancoDelRefresco(lista, []);
  refrescar(1, r => { visto.final = r; }, ["x"]);
  return Promise.resolve().then(() => {
    assert.deepStrictEqual(visto.final.lista, lista);
  });
});

/* ==================================================================
   «NO CAMBIO» NO ES «NO ESTA»
   ------------------------------------------------------------------
   REPORTADO POR EL USUARIO EL 2026-09-13 con la pantalla delante. Subio otra
   vez un segmento que ya estaba cargado. El procesamiento termino bien ---y
   concilio, que es lo que se acababa de arreglar--- y el tablero dijo:

       «El procesamiento termino bien, pero el catalogo no cambio. El dato
        puede estar cargado y faltar catalogarlo.»

   La sesion estaba en el catalogo desde hacia rato. El catalogo no cambio
   porque **no tenia por que cambiar**, y el aviso mandaba a buscar un problema
   que no existia.

   ES LA TERCERA VEZ EN EL DIA QUE APARECE LA MISMA PREGUNTA MAL FORMULADA. La
   conciliacion del guion preguntaba «¿cuanto crecio la base?» en vez de «¿tiene
   lo que estos segmentos deben dejar?». Aca se preguntaba «¿cambio la lista?»
   en vez de «¿esta la sesion?». Las dos confunden **el movimiento** con **el
   estado**, y las dos dan falso negativo cuando la operacion es idempotente.

   Y AHORA SE PUEDE PREGUNTAR BIEN, QUE ANTES NO SE PODIA. El comentario que
   estaba aca decia que el trabajo no declara que sesion cargo: eso se arreglo
   el mismo dia ---`lanzar_proceso` recibe las sesiones y las deja en
   `detalle`--- de modo que el tablero ya tiene contra que mirar.
   ================================================================== */

const sesionesDelTrabajo = new Function(
  extraer("sesionesDelTrabajo") + "\nreturn sesionesDelTrabajo;")();
const comoQuedoElCatalogo = new Function(
  extraer("comoQuedoElCatalogo") + "\nreturn comoQuedoElCatalogo;")();

prueba("el trabajo declara que sesiones toco, y se leen de ahi", () => {
  assert.deepStrictEqual(
    sesionesDelTrabajo({ detalle: { sesiones: ["can:segmento:sample_01"] } }),
    ["can:segmento:sample_01"]);
  //: Los trabajos que corren dentro del servidor devuelven una sola, con otro nombre.
  assert.deepStrictEqual(
    sesionesDelTrabajo({ detalle: { session_id: "f1_25:session:9" } }),
    ["f1_25:session:9"]);
  assert.deepStrictEqual(sesionesDelTrabajo({ detalle: { comando: ["x"] } }), []);
  assert.deepStrictEqual(sesionesDelTrabajo(null), []);
});

prueba("EL DEFECTO: que ya estuviera no es que falte catalogarla", () => {
  const lista = [{ session_id: "can:segmento:sample_01" }];
  assert.strictEqual(
    comoQuedoElCatalogo(["can:segmento:sample_01"], true, lista), "ya estaba");
});

prueba("y una sesion nueva se anuncia como lo que es", () => {
  const lista = [{ session_id: "can:segmento:sample_01" }];
  assert.strictEqual(
    comoQuedoElCatalogo(["can:segmento:sample_01"], false, lista), "apareció");
});

prueba("LA ALARMA SE CONSERVA PARA CUANDO DE VERDAD FALTA", () => {
  /* Es el caso que motivo todo esto: 57.890 filas en la base y la sesion sin
     catalogar. No puede aflojarse por arreglar el falso positivo. */
  assert.strictEqual(
    comoQuedoElCatalogo(["can:segmento:sample_01"], false, []), "no está");
  assert.strictEqual(
    comoQuedoElCatalogo(["a", "b"], false, [{ session_id: "a" }]), "no está",
    "con dos sesiones declaradas alcanza con que falte una");
});

prueba("un trabajo que no declara sesion no permite afirmar nada", () => {
  /* Queda el criterio viejo ---si la lista cambio--- y su aviso, que para ese
     caso sigue siendo lo unico que se puede decir. */
  assert.strictEqual(comoQuedoElCatalogo([], false, []), "sin declarar");
});

/* ==================================================================
   UNA IMPORTACION DE CONTEXTO NO DEJA UNA SESION EN LA LISTA
   ------------------------------------------------------------------
   REPORTADO POR EL USUARIO EL 2026-09-13. Subio el paquete real de Spa. La
   importacion salio bien en 5 s ---`racing_sessions` quedo con 9939, y con ella
   20 pilotos, 879 vueltas, 60 tandas y 223 muestras de clima--- y el tablero
   dijo:

       «El procesamiento termino bien, pero el catalogo no cambio. El dato
        puede estar cargado y faltar catalogarlo.»

   NO HABIA NADA QUE CATALOGAR. «Abrir sesion guardada» sale de
   `sesiones_catalogo`, que lista sesiones con filas en `telemetry_messages`;
   una importacion de **contexto** registra en `racing_sessions` y no trae
   telemetria ---el tablero la pide con `descargar_telemetria: false`---. El
   catalogo no cambio porque esta importacion no lo toca.

   ES LA MISMA FAMILIA QUE LAS OTRAS DOS DE HOY Y CON UNA VUELTA MAS: no es
   confundir el movimiento con el estado, es **preguntar por el sitio
   equivocado**. La respuesta correcta no era «si o no» sino «que dejo», y el
   trabajo ya lo declara: `detalle.importacion.counts`.
   ================================================================== */

const loQueImporto = new Function(
  [constante("LO_QUE_SE_CUENTA_DE_UNA_IMPORTACION"),
   extraer("cifra"), extraer("loQueImporto"),
   "return loQueImporto;"].join("\n"))();

//: Lo que declaro el trabajo real, tal cual.
const LO_DE_SPA = { detalle: { session_key: 9939, importacion: { counts: {
  drivers: 20, laps: 879, stints: 60, pit: 26, weather: 223,
  race_control: 117, sessions: 1, intervals: 23307 } } } };

prueba("EL DEFECTO: lo que importo se dice, en vez de preguntar por otra lista", () => {
  const dice = loQueImporto(LO_DE_SPA);
  assert.ok(/20 pilotos/.test(dice), dice);
  assert.ok(/879 vueltas/.test(dice), dice);
  assert.ok(!/cat.logo/i.test(dice), "sigue hablando del catalogo: " + dice);
});

prueba("y los numeros salen como se escriben aca", () => {
  assert.ok(/23\.307/.test(loQueImporto(LO_DE_SPA)),
    "veintitres mil trescientos siete se escribe con punto");
});

prueba("un trabajo que no importo contexto no declara nada", () => {
  assert.strictEqual(loQueImporto({ detalle: { sesiones: ["can:segmento:x"] } }), "");
  assert.strictEqual(loQueImporto({ detalle: {} }), "");
  assert.strictEqual(loQueImporto(null), "");
});

prueba("un conteo en cero no se anuncia como si hubiera entrado algo", () => {
  const vacio = { detalle: { importacion: { counts: { drivers: 0, laps: 0 } } } };
  assert.strictEqual(loQueImporto(vacio), "");
});

prueba("EL DESENLACE LO DECIDE LO QUE EL TRABAJO DECLARA", () => {
  /* Si el trabajo dice que importo, se cuenta eso; si dice que sesiones toco,
     se mira la lista. Preguntarle a la lista por una importacion de contexto
     es preguntarle a un sitio que esa importacion no escribe. */
  const i = fuenteApp.indexOf("function subirLoElegido(");
  const cuerpo = fuenteApp.slice(i, fuenteApp.indexOf("\n}", i));
  assert.ok(/loQueImporto\(/.test(cuerpo),
    "el desenlace no mira lo que el trabajo importo");
});

prueba("los tres desenlaces tienen su texto, y ninguno promete", () => {
  const i = fuenteApp.indexOf("function subirLoElegido(");
  const cuerpo = fuenteApp.slice(i, fuenteApp.indexOf("\n}", i));
  assert.ok(/ya aparece en/.test(cuerpo), "falta el texto de la que aparecio");
  assert.ok(/ya estaba en/.test(cuerpo), "falta el texto de la que ya estaba");
  assert.ok(/faltar catalogarlo/.test(cuerpo), "falta el aviso de la que no esta");
});

/* -------- el marcado que todo esto necesita -------- */

prueba("el dialogo existe y tiene sus tres partes", () => {
  assert.ok(/id="velo-subida"/.test(indice), "no esta el dialogo");
  assert.ok(/id="formatos-subida"/.test(indice), "no dice que se acepta");
  assert.ok(/id="barra-subida"/.test(indice), "no hay barra de progreso");
  assert.ok(/id="pasos-subida"/.test(indice), "no hay donde escribir que paso");
  assert.ok(/id="archivo-subida"[^>]*multiple/.test(indice),
    "no deja elegir la captura y su metadato juntos");
});

prueba("y se puede llegar a el con cualquier fuente elegida", () => {
  /* El servidor reconoce por contenido: atar la subida al selector obligaria a
     acertar la fuente antes de saber que es el archivo. Y la captura del
     simulador no tendria camino: su boton dice «empezar a escuchar». */
  assert.ok(/id="btn-subir"/.test(indice), "no hay boton propio de subida");
});

Promise.all(pendientes).then(() => {
  console.log("ok " + hechas + " pruebas de subir un archivo");
});
