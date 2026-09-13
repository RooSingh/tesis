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
                    "PLATAFORMAS_CAN"];
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
function prueba(titulo, fn) {
  try { fn(); hechas++; } catch (e) {
    process.exitCode = 1;
    console.error("FALLA  " + titulo + "\n       " + (e && e.message));
  }
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

prueba("y los metadatos entran aunque el servidor no los liste como formato", () => {
  /* No son una clase ---no tienen numero magico, son JSON--- pero se suben, y
     un dialogo que no los ofrezca hace imposible completar el par. */
  const lista = extensionesQueSeAceptan({ formatos: [{ extension: ".canraw" }] });
  assert.ok(lista.indexOf(".meta.json") !== -1,
    "el dialogo no deja elegir los metadatos: " + lista.join(","));
});

prueba("sin respuesta no se inventa un filtro", () => {
  assert.deepStrictEqual(extensionesQueSeAceptan(null), [".meta.json"]);
  assert.deepStrictEqual(extensionesQueSeAceptan({}), [".meta.json"]);
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

prueba("un bus vehicular se carga, y el supuesto se declara", () => {
  /* El nombre se compone `<plataforma>_<segmento>.canraw`, y mientras el
     servidor no diga que pedir hay que reconstruirlo de ahi. Eso es el mismo
     dato en dos sitios: por eso la suposicion se escribe en pantalla. */
  const plan = comoSeProcesa({
    clase: "can_crudo",
    guardado: "/srv/datasets/can/capturas/TOYOTA_RAV4_TSS2_2023-07-27--13-01-19--5.canraw",
  });
  assert.strictEqual(plan.ruta, "/can/importar");
  assert.deepStrictEqual(plan.cuerpo, {
    segmentos: ["2023-07-27--13-01-19--5"],
    plataforma: "TOYOTA_RAV4_TSS2",
    etapa: "cargar",
  });
  assert.ok(/derivado del nombre/.test(plan.supuesto || ""),
    "la suposicion no se declara: " + plan.supuesto);
});

prueba("y si el nombre no dice la plataforma, no se adivina una", () => {
  const plan = comoSeProcesa({ clase: "can_crudo",
                               guardado: "/srv/datasets/can/capturas/cualquiera.canraw" });
  assert.ok(plan.porQueNo, "se invento una plataforma");
  assert.ok(!plan.ruta, "se disparo una carga con datos inventados");
});

prueba("LO QUE EL SERVIDOR DECLARE GANA SOBRE CUALQUIER DERIVACION", () => {
  /* Es la salida prevista: en cuanto la respuesta traiga `procesar`, el tablero
     deja de partir nombres. Si esta rama no existiera, el acuerdo implicito
     sobreviviria al arreglo. */
  const plan = comoSeProcesa({
    clase: "can_crudo",
    guardado: "/srv/datasets/can/capturas/TOYOTA_RAV4_TSS2_abc.canraw",
    procesar: { ruta: "/otra/ruta", metodo: "POST", cuerpo: { lo: "que diga" } },
  });
  assert.strictEqual(plan.ruta, "/otra/ruta");
  assert.deepStrictEqual(plan.cuerpo, { lo: "que diga" });
  assert.strictEqual(plan.declaradoPorElServidor, true);
  assert.ok(!plan.supuesto, "se declaro un supuesto sobre algo que no se supuso");
});

prueba("una captura del simulador se declara pendiente, no terminada", () => {
  /* No hay ruta en la API que republique un `.f1raw`: lo hace un guion. Decir
     «listo» sobre eso seria afirmar que la sesion quedo disponible. */
  const plan = comoSeProcesa({ clase: "f1_25_crudo", guardado: "/x/y.f1raw" });
  assert.ok(plan.porQueNo, "se dio por procesada una captura que nadie procesa");
  assert.ok(/republicar_captura/.test(plan.porQueNo),
    "no dice que es lo que falta: " + plan.porQueNo);
});

prueba("y un paquete comprimido tampoco se da por importado", () => {
  const plan = comoSeProcesa({ clase: "paquete_openf1", guardado: "/x/y.zip" });
  assert.ok(plan.porQueNo);
  assert.ok(/descomprime/.test(plan.porQueNo), plan.porQueNo);
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
  assert.ok(/clase !== "metadatos"/.test(cuerpo),
    "se vuelve a procesar la respuesta del metadato en vez de la de la captura");
  assert.strictEqual(comoSeProcesa({ clase: "metadatos" }).porQueNo !== undefined, true,
    "un metadato no puede declarar un procesamiento propio");
});

prueba("una clase que nadie declara no dispara nada", () => {
  assert.ok(comoSeProcesa({}).porQueNo);
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

prueba("y ningun texto afirma una verificacion que no ocurrio", () => {
  /* «Guardada y verificada» era cierto para el caso feliz y falso para el otro,
     y se escribia igual en los dos. */
  const plan = comoSeProcesa({ clase: "f1_25_crudo", guardado: "/x/y.f1raw" });
  assert.ok(!/verificada/.test(plan.porQueNo),
    "el texto afirma que quedo verificada sin haberlo comprobado: " + plan.porQueNo);
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

prueba("y al terminar se refresca el catalogo", () => {
  /* Una sesion que no entra al catalogo existe en la base y **no se puede
     abrir**: paso el 2026-09-12 con dos sesiones. */
  const i = fuenteApp.indexOf("function subirLoElegido(");
  const cuerpo = fuenteApp.slice(i, fuenteApp.indexOf("\n}", i));
  assert.ok(/refrescarCatalogo\(/.test(cuerpo),
    "se procesa y el catalogo queda sin la sesion nueva");
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

console.log("ok " + hechas + " pruebas de subir un archivo");
