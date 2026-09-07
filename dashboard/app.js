/* ============================================================
   TABLERO DE TELEMETRIA
   ------------------------------------------------------------
   Todo lo que se ve viene de la API. No hay un solo valor escrito a mano
   en este archivo: la lista de sesiones, las vueltas, las series de cada
   señal, el trazado, el clima, el estado del vehiculo, los avisos y la
   puesta a punto salen de `backend/api_sesion.py`, que a su vez lee la
   base. Lo unico que este archivo decide es **como** mostrarlo.

   Cuando la fuente no tiene un dato, la API lo dice ---devuelve el bloque
   vacio y un `motivo_ausencia`--- y el panel muestra ese motivo en lugar
   del instrumento. Esa es la regla que gobierna todo el tablero: no se
   dibuja lo que no se midio, y se explica por que no esta.
   ============================================================ */

/* Donde vive la API. Por omision, el mismo host en el puerto 8000; se puede
   apuntar a otro con `?api=...`, que es lo que hace falta cuando el tablero
   se sirve aparte del backend ---en desarrollo, o detras del tunel. */
const API = (function () {
  const pedido = new URLSearchParams(location.search).get("api");
  if (pedido) return pedido.replace(/\/+$/, "");
  if (location.protocol === "file:") return "http://127.0.0.1:8000";
  if (location.port === "8000") return "";
  return location.protocol + "//" + location.hostname + ":8000";
})();

/* Una consulta a la API. Devuelve el cuerpo ya interpretado, o lanza con el
   motivo que dio el backend: los mensajes de error de esta API estan escritos
   para leerse, y taparlos con un «error de red» seria perder informacion. */
/* Las rutas de escritura ---empezar y detener una captura, importar un
   conjunto de datos, borrar una sesion--- son las mismas de siempre pero con
   cuerpo y con metodo. Se separan de `pedir` porque cambian el estado de la
   base y merecen leerse distinto en el codigo. */
async function mandar(ruta, metodo, cuerpo) {
  const r = await fetch(API + ruta, {
    method: metodo,
    headers: { "Accept": "application/json", "Content-Type": "application/json" },
    body: cuerpo === undefined ? undefined : JSON.stringify(cuerpo),
  });
  let d = null;
  try { d = await r.json(); } catch (e) { d = null; }
  if (!r.ok) {
    const motivo = (d && (d.detail || d.motivo)) || (r.status + " " + r.statusText);
    throw new Error(typeof motivo === "string" ? motivo : JSON.stringify(motivo));
  }
  return d;
}

async function pedir(ruta) {
  const r = await fetch(API + ruta, { headers: { "Accept": "application/json" } });
  let cuerpo = null;
  try { cuerpo = await r.json(); } catch (e) { cuerpo = null; }
  if (!r.ok) {
    const motivo = (cuerpo && (cuerpo.detail || cuerpo.motivo)) || (r.status + " " + r.statusText);
    const err = new Error(typeof motivo === "string" ? motivo : JSON.stringify(motivo));
    err.estado = r.status;
    throw err;
  }
  return cuerpo;
}

/* Lo que se sabe de la sesion abierta. Se llena al abrirla y se vacia al
   cerrarla; ningun panel lee otra cosa. */
const estado = {
  sesiones: [],        // catalogo completo, de /sesiones
  abierta: null,       // la entrada del catalogo que se esta mirando
  vueltas: [],         // de /sesiones/{id}/vueltas, con su duracion medida
  trazado: null,       // de /sesiones/{id}/trazado
  curvas: [],          // de /circuitos/{circuito}/curvas
  clima: null,         // de /sesiones/{id}/clima
  climaMotivo: "",
  vehiculo: null,      // de /sesiones/{id}/vehiculo
  vehiculoMotivo: "",
  puesta: null,        // de /sesiones/{id}/puesta-a-punto
  avisos: [],          // de /sesiones/{id}/avisos
  avisosMotivo: "",
  series: {},          // series por numero de vuelta, ya pedidas
  pidiendo: {},        // vueltas cuya consulta esta en curso
  posiciones: {},      // donde esta cada vehiculo, por vuelta
  pidiendoPos: {},
  disponibles: new Set(),   // que señales devolvio la fuente con dato
  vehiculoClave: null, // identificador del vehiculo del que hay telemetria
  cargando: false,
  motivo: "",          // por que no hay nada que mostrar
};

//: Cuantos puntos se piden por vuelta. La vuelta tiene unas 2.600 muestras y
//: el grafico mide trescientos pixeles: pedir mas es transferir para tirar.
const PUNTOS_POR_VUELTA = 500;


const FUENTES = {
  f1: {
    nombre: "F1 25",
    // Que instrumentos se pueden llenar lo contesta la API sesion por sesion;
    // esta lista es solo el orden en que se preguntan.
    tiene: new Set(),
    pista: "world_position_x / world_position_z, declarados por el paquete de movimiento. El trazado se rota sobre su eje principal solo para presentarlo.",
    accion: "Empezar a escuchar", accionVivo: "Detener escucha",
    ingreso: "El simulador emite por red y el capturador queda a la espera. No se sube ningún archivo.",
    motivos: { g: "", clima: "", auto: "", motor: "" },
    apiFalta: "POST /captura/iniciar y POST /captura/detener"
  },
  openf1: {
    nombre: "OpenF1",
    tiene: new Set(),
    pista: "track_position_x / track_position_y, declarados por la fuente. El muestreo de 3,7 Hz deja huecos de hasta 83 m entre muestras.",
    accion: "Importar sesión", accionVivo: "Importar sesión",
    ingreso: "Se elige una sesión del catálogo y se descarga. No hay flujo en vivo: es reproducción en diferido.",
    motivos: {
      g: "OpenF1 entrega nueve señales y ninguna es de aceleración.",
      clima: "El clima no viaja en la telemetría; llega por el contexto de sesión, aparte.",
      auto: "OpenF1 no publica temperatura ni presión de neumáticos, ni estado de daño.",
      motor: ""
    },
    apiFalta: "POST /openf1/importar"
  },
  can: {
    nombre: "CAN real",
    tiene: new Set(),
    pista: "El bus no declara posición: el recorrido se reconstruye por integración y se muestra como reconstrucción, no como medición.",
    accion: "Importar captura CAN", accionVivo: "Importar captura CAN",
    ingreso: "Se sube un segmento del conjunto de datos y se decodifica con el DBC del vehículo.",
    motivos: {
      g: "",
      clima: "Un bus vehicular de serie no publica temperatura de aire ni de pista.",
      auto: "El bus entrega velocidad de rueda, no temperatura ni presión de neumático.",
      motor: "La captura no incluye régimen de motor ni marcha seleccionada."
    },
    apiFalta: "POST /can/importar"
  }
};

/* LOS VEHICULOS DE LA SESION.
   ---------------------------------------------------------------------
   Antes habia veinte pilotos escritos con nombre y equipo. La base no
   guarda nombres: guarda identificadores de vehiculo, que es lo que el
   simulador y el bus publican. Poner «VER · Red Bull» sobre un
   identificador era ponerle al dato un nombre que el dato no tiene.

   La lista se arma con los vehiculos que la sesion abierta declara. El
   propio ---el unico del que hay telemetria privada--- es el primero que
   devuelve la consulta de series, y se puede cambiar. */
let AUTOS = [];

function claveCorta(clave) {
  const m = String(clave).match(/:(?:car|vehicle|driver):(.+)$/i);
  return m ? m[1] : String(clave).split(":").pop();
}

function armarAutos(claves) {
  const tintas = ["--auto-1", "--auto-2", "--auto-3", "--auto-4"];
  AUTOS = claves.map((c, i) => ({
    id: c,
    nombre: claveCorta(c),
    equipo: "vehículo declarado por la fuente",
    tinta: tintas[i % tintas.length],
    color: "var(" + tintas[i % tintas.length] + ")",
    propio: i === 0,
  }));
}

/* El nombre real de la senal en el contrato interno, para que cada grafico
   declare de donde sale y no solo como se llama en castellano. */
/* Los canales que el tablero sabe dibujar, con su rotulo y su unidad. Que
   fuentes lo tienen es una expectativa: la que manda es la respuesta de la
   API, que dice cuales trajo con dato. */
const METRICAS = [
  { id: "speed", rotulo: "Velocidad", unidad: "km/h", activa: true, fuentes: ["f1", "openf1", "can"] },
  { id: "throttle", rotulo: "Acelerador", unidad: "%", activa: true, fuentes: ["f1", "openf1", "can"] },
  { id: "brake", rotulo: "Freno", unidad: "%", activa: false, fuentes: ["f1", "openf1", "can"] },
  { id: "rpm", rotulo: "Régimen", unidad: "rpm", activa: true, fuentes: ["f1", "openf1"] },
  { id: "gear", rotulo: "Marcha", unidad: "de 8", activa: false, fuentes: ["f1", "openf1"] },
  { id: "glong", rotulo: "G longitudinal", unidad: "g", activa: true, fuentes: ["f1", "can"] },
  { id: "glat", rotulo: "G lateral", unidad: "g", activa: false, fuentes: ["f1", "can"] },
  { id: "steer", rotulo: "Dirección", unidad: "norm.", activa: false, fuentes: ["f1", "can"] },
  { id: "drs", rotulo: "DRS", unidad: "abierto", activa: false, fuentes: ["f1", "openf1"] },
  { id: "ers", rotulo: "Energía ERS", unidad: "%", activa: false, fuentes: ["f1"] },
  { id: "fuel", rotulo: "Combustible", unidad: "kg", activa: false, fuentes: ["f1"] },
  { id: "tyre", rotulo: "Temp. neumático", unidad: "°C", activa: false, fuentes: ["f1"] },
  { id: "brakeTemp", rotulo: "Temp. freno", unidad: "°C", activa: false, fuentes: ["f1"] },
  { id: "slip", rotulo: "Deslizamiento", unidad: "ratio", activa: false, fuentes: ["f1"] },
  { id: "gap", rotulo: "Diferencia acumulada", unidad: "s", activa: true, fuentes: ["f1", "openf1"] },
  { id: "gvert", rotulo: "G vertical", unidad: "g", activa: false, fuentes: ["f1"] },
  { id: "steerRate", rotulo: "Giro del volante", unidad: "°/s", activa: false, fuentes: ["can"] },
  { id: "yaw", rotulo: "Guiñada", unidad: "°/s", activa: false, fuentes: ["f1", "can"] },
  { id: "engineTemp", rotulo: "Temp. motor", unidad: "°C", activa: false, fuentes: ["f1"] },
  { id: "wheelFL", rotulo: "Rueda del. izq.", unidad: "km/h", activa: false, fuentes: ["f1", "can"] },
  { id: "wheelRR", rotulo: "Rueda tras. der.", unidad: "km/h", activa: false, fuentes: ["f1", "can"] }
];

const SENAL_DE = {
  speed: "speed", throttle: "throttle_position", brake: "brake_position",
  rpm: "engine_speed", gear: "gear_selected", glong: "g_force_longitudinal",
  glat: "g_force_lateral", gvert: "g_force_vertical", steer: "steering_normalized",
  steerRate: "steer_rate", yaw: "yaw_rate", drs: "drs_open",
  ers: "ers_stored_energy", fuel: "fuel_mass", engineTemp: "engine_temperature",
  tyre: "tyre_temperature_surface_front_left", brakeTemp: "brake_temperature_front_left",
  slip: "wheel_slip_ratio_front_left", wheelFL: "wheel_speed_front_left",
  wheelRR: "wheel_speed_rear_right", gap: "delta_to_race_leader"
};

const SENAL_CAN = {
  throttle: "gas_pressed", brake: "brake_pressed", glong: "accel_longitudinal",
  glat: "accel_lateral", steer: "steer_angle", steerRate: "steer_rate", yaw: "yaw_rate"
};

const SENAL_OPENF1 = { brake: "brake_applied", drs: "drs_state_code" };

function nombreDeSenal(id) {
  if (fuente === "can" && SENAL_CAN[id]) return SENAL_CAN[id];
  if (fuente === "openf1" && SENAL_OPENF1[id]) return SENAL_OPENF1[id];
  return SENAL_DE[id] || id;
}

const MOTIVO_METRICA = {
  openf1: "OpenF1 entrega nueve señales y esta no está entre ellas.",
  can: "El bus del vehículo no publica este canal."
};

let fuente = "f1";
let alcance = "1";
let seleccion = new Set();
let canalesTraza = { speed: true, throttle: true, brake: false };
let ampliado = false;
let estadoSesion = "cargado";
let ejeComparacion = "distancia";
let alcanceComparacion = "una";
let zoom = null;
let fuentePendiente = null;
let vueltaElegida = 1;

/* Nombres del catalogo externo citado; posiciones medidas sobre la vuelta.
   El nombre es anotacion, no medicion: se declara en la interfaz. */
/* El trazado y sus curvas llegan con la sesion. Hasta que llegan, el panel
   se dibuja vacio y dice que esta cargando: no hay un trazado por omision. */
let PISTA = { path: "", curvas: [], largo_m: null, desnivel_m: null, muestras: null };
let CURVAS = [];

const raiz = document.documentElement;
raiz.dataset.tema = "oscuro";

const tinta = n => getComputedStyle(raiz).getPropertyValue(n).trim();

/* UNA RAYA NO ES UN CERO.
   Cuando la fuente no publica una magnitud, el instrumento tiene que decir
   que no la tiene. Escribir 0 seria afirmar una medicion que nadie hizo. */
function cifra(v, decimales) {
  if (v === null || v === undefined || (typeof v === "number" && !isFinite(v))) return "—";
  const d = decimales === undefined ? 0 : decimales;
  return Number(v).toLocaleString("es-AR", { minimumFractionDigits: d, maximumFractionDigits: d });
}

/* FECHAS
   ---------------------------------------------------------------------
   Se muestran como se escriben en Argentina: dia, mes y ano separados por
   barras. Las fechas se guardan y se transportan en formato ISO ---que es
   lo correcto, porque ordena y no depende de la region--- y se convierten
   solo al mostrarlas. La conversion es explicita y no delegada al idioma
   del navegador: quien mira el tablero desde otro pais tiene que leer la
   misma fecha que quien lo escribio. */
function fechaAr(valor) {
  if (!valor) return "";

  // ORDEN IMPORTANTE. Una cadena ISO sin hora ---"2026-09-06"--- la
  // especificacion la interpreta como medianoche UTC, y leer despues el dia
  // local resta un dia en cualquier huso al oeste de Greenwich: en Argentina
  // esa fecha se mostraba como 05/09/2026. Por eso se parte la cadena antes
  // de construir una fecha, y no como respaldo de un intento fallido.
  const iso = String(valor).match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (iso) return iso[3] + "/" + iso[2] + "/" + iso[1];

  const d = valor instanceof Date ? valor : new Date(valor);
  if (isNaN(d.getTime())) return String(valor);
  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  return dd + "/" + mm + "/" + d.getFullYear();
}

function fechaHoraAr(valor) {
  if (!valor) return "";
  const d = valor instanceof Date ? valor : new Date(valor);
  if (isNaN(d.getTime())) return fechaAr(valor);
  const hh = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  return fechaAr(d) + " " + hh + ":" + mi;
}
const marcar = (grupo, attr, valor) =>
  grupo.querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset[attr] === valor)));

/* ---------------- tema y fuente ---------------- */
document.getElementById("sel-tema").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  raiz.dataset.tema = b.dataset.tema;
  marcar(e.currentTarget, "tema", b.dataset.tema);
  dibujarTraza(); if (compAbierta()) dibujarComparacion();
});

/* Un solo modal para toda accion que destruya lo que hay en pantalla.
   `accionPendiente` guarda que hacer si la persona confirma. */
let accionPendiente = null;

function pedirConfirmacion({ titulo, texto, razon, boton, alConfirmar }) {
  accionPendiente = alConfirmar;
  document.getElementById("modal-titulo").textContent = titulo;
  document.getElementById("modal-texto").innerHTML = texto;
  document.getElementById("modal-razon").innerHTML = razon;
  document.getElementById("modal-confirmar").textContent = boton;
  document.getElementById("velo-modal").dataset.abierto = "si";
  document.getElementById("modal-cancelar").focus();
}

document.getElementById("sel-fuente").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b || b.dataset.fuente === fuente) return;
  if (estadoSesion === "vacio") { cambiarFuente(b.dataset.fuente); return; }
  const destino = b.dataset.fuente;
  pedirConfirmacion({
    titulo: "Cambiar de fuente descarta la sesión",
    texto: "Hay una sesión de <b>" + FUENTES[fuente].nombre + "</b> cargada, con <b>" +
      cifra((estado.abierta || {}).senales, 0) + " señales</b> en pantalla. Pasar a <b>" +
      FUENTES[destino].nombre + "</b> descarta lo que estás mirando.",
    razon: "<b>Las fuentes no se mezclan.</b> Cada una tiene su propio conjunto de señales, su " +
      "reloj y su procedencia. Una sesión cargada pertenece a una fuente y no se reinterpreta en otra.",
    boton: "Descartar y cambiar",
    alConfirmar: () => cambiarFuente(destino)
  });
});

document.getElementById("modal-cancelar").addEventListener("click", cerrarModal);
document.getElementById("velo-modal").addEventListener("click", e => {
  if (e.target.id === "velo-modal") cerrarModal();
});
document.getElementById("modal-confirmar").addEventListener("click", () => {
  const accion = accionPendiente;
  cerrarModal();
  if (accion) accion();
});
function cerrarModal() {
  document.getElementById("velo-modal").dataset.abierto = "no";
  accionPendiente = null;
  fuentePendiente = null;
}
function cambiarFuente(nueva) {
  if (nueva !== "f1") cerrarFlujoEnVivo();
  olvidarCaches();
  fuente = nueva;
  marcar(document.getElementById("sel-fuente"), "fuente", fuente);
  estadoSesion = "cargado";
  if (fuente === "can") { alcance = "1"; seleccion = new Set(); marcar(document.getElementById("sel-alcance"), "alcance", "1"); }
  if (fuente === "f1") conectarFlujoEnVivo();
  render();
}

/* ---------------- ciclo de vida ---------------- */
/* ============================================================
   LAS ACCIONES QUE CAMBIAN LA BASE
   ------------------------------------------------------------
   Empezar una captura, detenerla, importar un conjunto de datos y borrar una
   sesion. Las cuatro escriben, las cuatro devuelven un trabajo o un resumen,
   y las cuatro se avisan con lo que contesto el backend ---no con un «listo»
   escrito aca, que seria afirmar un resultado que no se comprobo.
   ============================================================ */
function accionDeLaFuente() {
  if (fuente === "f1") {
    return estadoSesion === "vivo"
      ? { ruta: "/captura/detener", metodo: "POST", cuerpo: undefined,
          hecho: d => "Captura detenida. " + (d.capturas_cerradas !== undefined
            ? d.capturas_cerradas + " sesiones cerradas" : "Sin sesiones nuevas") }
      : { ruta: "/captura/iniciar", metodo: "POST", cuerpo: { parrilla_completa: true },
          hecho: d => "Capturador escuchando" + (d.puerto ? " en el puerto " + d.puerto : "") +
                      (d.trabajo ? " · trabajo " + d.trabajo : "") };
  }
  if (fuente === "openf1") {
    const sugerida = estado.abierta && FUENTE_CORTA[estado.abierta.fuente] === "openf1"
      ? String(estado.abierta.session_id).split(":").pop() : "";
    const escrita = window.prompt("Session key de OpenF1", sugerida);
    if (escrita === null) return null;
    const sessionKey = Number(escrita);
    if (!Number.isInteger(sessionKey)) throw new Error("La session key de OpenF1 debe ser un número entero.");
    return { ruta: "/openf1/importar", metodo: "POST",
             cuerpo: { session_key: sessionKey, descargar_telemetria: false },
             hecho: d => "Importación en curso" + (d.trabajo ? " · trabajo " + d.trabajo : "") };
  }
  const escritos = window.prompt("Segmentos CAN separados por coma", "");
  if (escritos === null) return null;
  const segmentos = escritos.split(",").map(s => s.trim()).filter(Boolean);
  if (!segmentos.length) throw new Error("Hay que indicar al menos un segmento CAN.");
  return { ruta: "/can/importar", metodo: "POST",
           cuerpo: { segmentos: segmentos, plataforma: "TOYOTA_RAV4_TSS2", etapa: "cargar" },
           hecho: d => "Importación en curso" + (d.trabajo ? " · trabajo " + d.trabajo : "") };
}

document.getElementById("btn-accion").addEventListener("click", () => {
  let a;
  try { a = accionDeLaFuente(); } catch (e) { avisar(e.message, true); return; }
  if (!a) return;
  const boton = document.getElementById("btn-accion");
  boton.disabled = true;
  mandar(a.ruta, a.metodo, a.cuerpo)
    .then(d => {
      avisar(a.hecho(d), false);
      // Lo que cambio en la base se ve pidiendo el catalogo de nuevo.
      pedir("/sesiones?limite=400")
        .then(c => { SESIONES = (c.sesiones || []).filter(s => s.filas > 0); render(); })
        .catch(() => {});
      vigilarEnVivo();
    })
    .catch(e => avisar(e.message, true))
    .then(() => { boton.disabled = false; });
  /* En vivo el cabezal esta siempre en el ultimo dato: es lo que significa
     estar en vivo. Dejarlo donde estaba hacia que el indicador dijera una
     vuelta y los instrumentos mostraran otra, que es peor que no decir nada. */
  if (estadoSesion === "vivo") { detener(); cabezal = 1; vueltaElegida = instante().vuelta; }
  render();
});
document.getElementById("btn-limpiar").addEventListener("click", () => {
  const f = FUENTES[fuente];
  // Cuantas filas se van a borrar es un dato de la sesion abierta, no una
  // cifra escrita: es lo que la confirmacion tiene que poder afirmar.
  const filas = estado.abierta ? cifra(estado.abierta.filas, 0) : "—";
  pedirConfirmacion({
    titulo: "Esto borra datos de la base",
    texto: "Se van a borrar <b>" + filas + " filas</b> y <b>" + cifra((estado.abierta || {}).senales, 0) +
      " señales</b> de la sesión de " + f.nombre + ". <b>La operación es irreversible.</b>",
    razon: "Volver a cargar el mismo origen <b>no restituye el estado anterior</b>: medido el " +
      "06/09/2026 sobre una captura CAN, la recarga devolvió 29 filas más que las que había, y " +
      "les asignó otras marcas de tiempo. El dato vuelve; el estado exacto, no.",
    boton: "Borrar " + filas + " filas",
    alConfirmar: () => {
      if (!estado.abierta) return;
      const id = estado.abierta.session_id;
      mandar("/sesion/" + encodeURIComponent(id) + "?confirmar=true", "DELETE")
        .then(d => {
          avisar("Borradas " + cifra(d.borradas, 0) + " filas de " + id, false);
          SESIONES = SESIONES.filter(s => s.session_id !== id);
          estado.abierta = null; sesionAbierta = null;
          estadoSesion = "vacio";
          estado.motivo = "La sesión se borró. Elegí otra del catálogo.";
          render();
        })
        .catch(e => avisar(e.message, true));
    }
  });
});
document.getElementById("btn-comparar").addEventListener("click", abrirComparacion);

/* El encabezado nombra la sesion que se esta mirando. Antes decia siempre lo
   mismo ---el nombre de la maqueta--- y el circuito quedaba en un renglon
   secundario, cuando es el primer dato que ubica todo lo demas. */
function pintarTitulo() {
  const t = document.getElementById("marca-titulo");
  const e = document.getElementById("marca-eyebrow");
  if (!t || !e) return;
  if (estadoSesion === "vacio") {
    e.textContent = "Banco de instrumentos";
    t.textContent = "Sin sesión";
    return;
  }
  const s = estado.abierta;
  e.textContent = FUENTES[fuente].nombre + " · " +
    (fuente === "can" ? "captura del bus"
                      : "vuelta " + vueltaElegida + " de " + vueltasDeLaSesion());
  t.textContent = s ? nombreDeSesion(s) : "Esperando sesión";
}

function pintarCiclo() {
  pintarTitulo();
  const f = FUENTES[fuente];
  const past = document.getElementById("pastilla-estado");
  const det = document.getElementById("detalle-estado");
  const acc = document.getElementById("btn-accion");

  past.className = "pastilla " + (estadoSesion === "vivo" ? "vivo" : estadoSesion === "cargado" ? "cargado" : "vacio");
  past.textContent = estadoSesion === "vivo" ? "recibiendo" : estadoSesion === "cargado" ? "sesión cargada" : "sin datos";

  if (estadoSesion === "vacio") {
    det.innerHTML = f.ingreso;
  } else if (estadoSesion === "vivo") {
    const recibidos = estado.vivo && estado.vivo.mensajes_recibidos;
    det.textContent = "Escuchando el flujo del simulador" +
      (recibidos !== undefined ? " · " + cifra(recibidos, 0) + " mensajes recibidos" : "");
  } else {
    const s = estado.abierta || {};
    det.textContent = nombreDeSesion(s) + " · " + cifra(s.senales, 0) + " señales · " +
      cifra(s.vehiculos, 0) + " vehículos";
  }
  acc.textContent = estadoSesion === "vivo" ? f.accionVivo : f.accion;
  document.getElementById("btn-limpiar").disabled = estadoSesion === "vacio";
  document.getElementById("btn-comparar").disabled = estadoSesion === "vacio" || fuente !== "f1" || AUTOS.length < 2;
}

/* ---------------- alcance y traza ---------------- */
document.getElementById("sel-alcance").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  alcance = b.dataset.alcance;
  marcar(e.currentTarget, "alcance", alcance);
  if (alcance === "1") seleccion = new Set(AUTOS.length ? [autoPropio().id] : []);
  if (alcance === "varios") seleccion = new Set(AUTOS.slice(0, 2).map(a => a.id));
  if (alcance === "todos") seleccion = new Set(AUTOS.map(a => a.id));
  render();
});

/* Los controles de la traza se construyen en `pintarControlesTraza`, porque
   dependen de que canales tenga la fuente activa: enlazarlos aca fallaria
   contra elementos que todavia no existen. */

/* ---------------- vehículos ---------------- */
/* Quien es el propio: el unico del que hay telemetria privada. Cambiarlo
   cambia de quien son la traza, los medidores, las esquinas y el daño. */
/* Mientras la sesion no llego no hay vehiculos, y eso no es un error: es el
   estado normal de los primeros cientos de milisegundos. Se devuelve un
   vehiculo vacio para que ningun panel tenga que preguntar si ya llego. */
const SIN_VEHICULO = { id: null, nombre: "—", equipo: "", tinta: "--auto-1", color: "var(--auto-1)", propio: true };

function autoPropio() {
  return AUTOS.find(a => a.propio) || AUTOS[0] || SIN_VEHICULO;
}

function elegirPropio(id) {
  const anterior = autoPropio().id;
  AUTOS.forEach(a => { a.propio = (a.id === id); });
  /* Si se estaba mirando solo al propio, se pasa a mirar solo al nuevo: elegir
     piloto es cambiar de quien se mira, no agregar uno. Si habia varios
     seleccionados ---se estaba comparando--- el nuevo se suma sin sacar a
     nadie, porque ahi la seleccion la armo quien mira. */
  if (seleccion.size === 1 && seleccion.has(anterior)) seleccion = new Set([id]);
  else seleccion.add(id);
  olvidarCaches();
  render();
}

function poblarPropio() {
  const s = document.getElementById("sel-propio");
  if (!s) return;
  const unico = AUTOS.length <= 1;
  s.closest(".elige-propio").style.display = unico ? "none" : "";
  if (!AUTOS.length) { s.innerHTML = ""; s.dataset.firma = ""; return; }
  if (unico) return;
  const actual = autoPropio().id;
  const firma = AUTOS.map(a => a.id).join(",") + "|" + actual;
  if (s.dataset.firma === firma) return;
  s.dataset.firma = firma;
  s.innerHTML = AUTOS.map(a =>
    '<option value="' + a.id + '"' + (a.id === actual ? " selected" : "") + '>' +
    a.nombre + ' · ' + a.equipo + '</option>').join("");
}

(function mandoDePropio() {
  const s = document.getElementById("sel-propio");
  if (!s) return;
  s.addEventListener("change", () => elegirPropio(s.value));
})();

function pintarAutos() {
  poblarPropio();
  const f = FUENTES[fuente];
  const cont = document.getElementById("lista-autos");
  const visibles = AUTOS;
  cont.innerHTML = "";
  visibles.forEach(a => {
    const fila = document.createElement("div");
    fila.className = "auto-fila";
    fila.setAttribute("role", "checkbox");
    fila.setAttribute("tabindex", "0");
    fila.setAttribute("aria-checked", String(seleccion.has(a.id)));
    fila.innerHTML =
      '<span class="punto" style="background:' + a.color + '"></span>' +
      '<span class="nombre">' + a.nombre + '<small>' + a.equipo + '</small></span>' +
      (a.propio
        ? '<span class="propio">propio · ' + cifra((estado.abierta || {}).senales, 0) + ' señales</span>'
        : '<span class="senales">cronometraje</span>');
    const alternar = () => {
      if (seleccion.has(a.id)) seleccion.delete(a.id); else seleccion.add(a.id);
      if (seleccion.size === 0) seleccion.add(a.id);
      render();
    };
    fila.addEventListener("click", alternar);
    fila.addEventListener("keydown", ev => {
      if (ev.key === " " || ev.key === "Enter") { ev.preventDefault(); alternar(); }
    });
    cont.appendChild(fila);
  });
  // Lo que decia el parrafo lo declara ahora cada fila: «propio» contra
  // «cronometraje». El fundamento completo queda en el titulo del panel.
  const panelAutos = cont.closest(".instrumento");
  if (panelAutos) {
    panelAutos.title = AUTOS.length <= 1
      ? "La captura del bus es de un solo vehículo: comparar entre autos no aplica en esta fuente."
      : "De los rivales se muestra cronometraje; la telemetría privada, solo del propio. La fuente entrega de todos lo mismo, y mostrarlo enseñaría un procedimiento que en un vehículo real no se puede ejecutar.";
  }
  document.getElementById("canal-autos").textContent = AUTOS.length
    ? (AUTOS.length === 1 ? "1 vehículo en la sesión" : AUTOS.length + " en la sesión")
    : "—";
}

/* ---------------- disponibilidad ---------------- */
function aplicarDisponibilidad() {
  const f = FUENTES[fuente];
  /* Un panel esta presente si la sesion abierta trajo con que llenarlo. No
     lo decide una tabla escrita aca: lo decide lo que devolvio la API. */
  document.querySelectorAll("[data-necesita]").forEach(el => {
    el.dataset.estado = (estadoSesion !== "vacio" &&
                         estado.disponibles.has(el.dataset.necesita)) ? "presente" : "ausente";
  });
  /* El motivo de cada ausencia lo escribe la API: es la fuente la que sabe
     por que no publica un dato, y repetirlo aca seria copiarlo mal tarde o
     temprano. Cuando la API no dio motivo se cae en el de la fuente. */
  const vacio = estadoSesion === "vacio";
  const txtVacio = "No hay sesión abierta.";
  const poner = (id, dela, fallback) => {
    const el = document.getElementById(id);
    if (el) el.textContent = vacio ? txtVacio : (dela || fallback || "");
  };
  poner("motivo-g", estado.vehiculoMotivo, f.motivos.g);
  poner("motivo-clima", estado.climaMotivo, f.motivos.clima);
  poner("motivo-auto", estado.vehiculoMotivo, f.motivos.auto);
  poner("motivo-motor", estado.vehiculoMotivo, f.motivos.motor);
  poner("motivo-avisos", estado.avisosMotivo, "");
  // La procedencia va al encabezado, que es donde el resto de los
  // instrumentos la declara, y la explicacion completa al titulo del panel.
  /* Lo que dice el encabezado del trazado es lo que midio **esta** sesion, no
     una cifra escrita: el largo, el desnivel y cuantas muestras hubo detras
     del dibujo salen de la respuesta de la API. */
  const cabPista = document.getElementById("canal-pista");
  if (PISTA.largo_m) {
    const partes = [cifra(PISTA.largo_m, 0) + " m"];
    if (PISTA.desnivel_m) partes.push(cifra(PISTA.desnivel_m, 1) + " m de desnivel");
    if (PISTA.muestras) partes.push(cifra(PISTA.muestras, 0) + " muestras");
    cabPista.textContent = partes.join(" · ");
  } else {
    cabPista.textContent = fuente === "can" ? "recorrido reconstruido" : "sin trazado";
  }
  const panelPista = cabPista.closest(".instrumento");
  if (panelPista) panelPista.title = f.pista;
}

/* ---------------- esquinas y daño ---------------- */
const colorVida = v => (v === null || v === undefined) ? "var(--linea-fuerte)"
  : v > 70 ? "var(--ok)" : v > 40 ? "var(--alerta)" : "var(--critico)";
const colorTemp = t => (t === null || t === undefined) ? "var(--texto-tenue)"
  : t > 102 ? "var(--critico)" : t > 96 ? "var(--alerta)" : "var(--ok)";

/* Lo que publica el vehiculo en cada esquina, tal cual. Antes esto partia de
   cuatro valores escritos y les sumaba una regla inventada de desgaste. */
function esquinaViva(clave) {
  const d = estado.vehiculo && estado.vehiculo.esquinas && estado.vehiculo.esquinas[clave];
  const rotulos = { front_left: "Del. izq.", front_right: "Del. der.",
                    rear_left: "Tras. izq.", rear_right: "Tras. der." };
  if (!d) return { rotulo: rotulos[clave] || clave, temp: null, pres: null, vida: null, freno: null };
  return {
    rotulo: rotulos[clave] || clave,
    temp: d.temperatura_superficie_c,
    pres: d.presion_psi,
    // La API declara desgaste; lo que se muestra es lo que queda.
    vida: d.desgaste_pct === null || d.desgaste_pct === undefined ? null : (100 - d.desgaste_pct),
    freno: d.freno_c,
    ampollas: d.ampollas_pct,
  };
}

let _firmaEsquinas = "";

function pintarEsquinas() {
  const ti = instante();
  const firmaE = [fuente, estadoSesion, ti.avance.toFixed(4), Math.round(ti.frenando),
                  tinta("--acento")].join("|");
  if (firmaE === _firmaEsquinas) return;
  _firmaEsquinas = firmaE;

  document.querySelectorAll("[data-esquina]").forEach(el => {
    const d = esquinaViva(el.dataset.esquina);
    el.innerHTML =
      '<p class="eyebrow">' + d.rotulo + '</p>' +
      '<div class="fila-canal"><span>Temp</span><b style="color:' + colorTemp(d.temp) + '">' + cifra(d.temp, 0) + '&nbsp;°C</b></div>' +
      '<div class="fila-canal"><span>Presión</span><b>' + cifra(d.pres, 1) + '&nbsp;psi</b></div>' +
      '<div class="fila-canal"><span>Freno</span><b>' + cifra(d.freno, 0) + '&nbsp;°C</b></div>' +
      '<div class="fila-canal"><span>Vida</span><b>' + cifra(d.vida, 0) + '&nbsp;%</b></div>' +
      '<div class="barra-desgaste"><i style="width:' + (d.vida === null ? 0 : d.vida) + '%;background:' + colorVida(d.vida) + '"></i></div>';
  });
  /* EL DAÑO APARECE CUANDO OCURRE, NO DESDE EL PRINCIPIO.
     El piso y el aleron estaban rotos ya en la vuelta 1, cuando los avisos
     que los declaran llegan pasada la mitad de la sesion. Se atan a los
     mismos umbrales: lo que dice el panel de avisos y lo que dice el esquema
     del vehiculo son la misma cosa contada dos veces. */
  /* EL DAÑO ES EL QUE DECLARA EL VEHICULO.
     Cada pieza trae su porcentaje de daño en `/sesiones/{id}/vehiculo`. La
     gravedad se lee de ese numero ---nada por debajo de uno, leve hasta
     veinte, grave por encima--- y no de un umbral de tiempo inventado. */
  const car = (estado.vehiculo && estado.vehiculo.carroceria) || {};
  const nivelDe = pct => (pct === null || pct === undefined || pct < 1) ? "ok"
                       : (pct < 20 ? "alerta" : "critico");
  const partes = [
    { ids: ["p-ala-del"], estado: nivelDe(car.ala_delantera_izq_pct), nombre: "Alerón del. izq.", pct: car.ala_delantera_izq_pct },
    { ids: ["p-ala-del-2"], estado: nivelDe(car.ala_delantera_der_pct), nombre: "Alerón del. der.", pct: car.ala_delantera_der_pct },
    { ids: ["p-pontones"], estado: nivelDe(car.pontones_pct), nombre: "Pontones", pct: car.pontones_pct },
    { ids: ["p-piso"], estado: nivelDe(car.piso_pct), nombre: "Piso", pct: car.piso_pct },
    { ids: ["p-ala-tras", "p-ala-tras-2"], estado: nivelDe(car.ala_trasera_pct), nombre: "Alerón trasero", pct: car.ala_trasera_pct },
    { ids: ["p-cuerpo"], estado: nivelDe(car.motor_pct), nombre: "Motor", pct: car.motor_pct },
    { ids: ["p-morro"], estado: nivelDe(car.difusor_pct), nombre: "Difusor", pct: car.difusor_pct }
  ];
  // var() no se resuelve dentro de un atributo de presentacion SVG: el relleno
  // cae a negro y la pieza desaparece sobre fondo oscuro. Se resuelve el color
  // antes y se asigna por estilo, que si lee las variables.
  const t = { ok: tinta("--linea-fuerte"), alerta: tinta("--alerta"), critico: tinta("--critico") };
  partes.forEach(p => {
    p.ids.forEach(id => {
      const el = document.getElementById(id); if (!el) return;
      el.style.fill = p.estado === "ok" ? tinta("--superficie-hueca") : t[p.estado];
      el.style.stroke = t[p.estado];
      el.style.strokeWidth = "1.4";
      el.style.opacity = p.estado === "ok" ? "0.92" : "0.8";
    });
  });
  // suspension y halo: trazo sin relleno
  ["p-suspension", "p-halo"].forEach(id => {
    const el = document.getElementById(id); if (!el) return;
    el.style.stroke = tinta("--linea-fuerte"); el.style.fill = "none";
  });
  const hab = document.getElementById("p-habitaculo");
  if (hab) { hab.style.fill = tinta("--superficie-hueca"); hab.style.stroke = tinta("--linea-fuerte"); }
  // neumaticos por temperatura y frenos por su propio canal
  document.querySelectorAll("[data-esquina-svg]").forEach(el => {
    const d = esquinaViva(el.dataset.esquinaSvg);
    el.style.fill = tinta(d.temp > 102 ? "--critico" : d.temp > 96 ? "--alerta" : "--ok");
    el.style.stroke = tinta("--superficie");
    el.style.opacity = "0.85";
  });
  document.querySelectorAll("[data-freno]").forEach(el => {
    const f = esquinaViva(el.dataset.freno).freno;
    el.style.fill = tinta(f > 800 ? "--critico" : f > 700 ? "--alerta" : "--texto-tenue");
  });
  // La gravedad va escrita, no solo en el color: los mismos ambar y rojo
  // marcan la temperatura de neumatico dos centimetros mas alla, y con el
  // color solo no habia forma de saber cual de las dos cosas se estaba
  // leyendo. El contorno rayado los separa a simple vista.
  const GRAVEDAD = { alerta: "leve", critico: "grave" };
  const danados = partes.filter(p => p.estado !== "ok");
  document.getElementById("leyenda-dano").innerHTML = danados.length
    ? danados.map(p => '<span class="chip ' + p.estado + '" title="Declarado por el vehículo">' +
        '<b>' + p.nombre + '</b> <span>' + GRAVEDAD[p.estado] +
        ', ' + cifra(p.pct, 0) + ' %</span></span>').join("")
    : '<span class="chip ok"><b>Sin daño</b> <span>ninguna pieza lo declara</span></span>';
}

/* ---------------- medidores ---------------- */
/* Un medidor circular con arco en degradado, marcas de escala y barrido
   animado. El degradado va de un color frio a uno caliente para que el
   valor se lea antes de leer la cifra: el color dice "esto va bien" o
   "esto esta al limite" sin exigir conocer la escala.

   El barrido se anima con `stroke-dashoffset`, no con un temporizador que
   redibuje: asi `prefers-reduced-motion` lo desactiva desde la hoja de
   estilos, sin ramas en el codigo. */

let secuenciaMedidor = 0;

function medidor(rotulo, valor, maximo, unidad, colorFrio, colorCaliente) {
  const id = "grad-medidor-" + (secuenciaMedidor += 1);
  const radio = 46;
  const circ = Math.PI * radio * 1.5;
  const frac = (valor === null || valor === undefined) ? 0
             : Math.max(0, Math.min(1, valor / maximo));
  const arco = "M16 90 A" + radio + " " + radio + " 0 1 1 108 90";

  // Marcas de escala cada cuarto de recorrido.
  let marcas = "";
  for (let i = 0; i <= 4; i++) {
    const ang = Math.PI * 0.75 + (Math.PI * 1.5 * i) / 4;
    const x1 = 62 + Math.cos(ang) * (radio + 8);
    const y1 = 90 + Math.sin(ang) * (radio + 8);
    const x2 = 62 + Math.cos(ang) * (radio + 12);
    const y2 = 90 + Math.sin(ang) * (radio + 12);
    marcas += '<line x1="' + x1.toFixed(1) + '" y1="' + y1.toFixed(1) +
      '" x2="' + x2.toFixed(1) + '" y2="' + y2.toFixed(1) +
      '" stroke="var(--linea)" stroke-width="1.5" stroke-linecap="round"></line>';
  }

  const escrito = (valor === null || valor === undefined) ? "—"
    : (Math.abs(valor) < 10 ? Number(valor).toFixed(1).replace(".", ",") : Math.round(valor));
  return '<div class="medidor" data-medidor="' + rotulo +
    '"><svg viewBox="0 0 124 112" role="img" aria-label="' +
    rotulo + ': ' + valor + ' ' + unidad + '">' +
      '<defs><linearGradient id="' + id + '" x1="0" y1="1" x2="1" y2="0">' +
        '<stop offset="0%" stop-color="' + colorFrio + '"></stop>' +
        '<stop offset="55%" stop-color="' + colorFrio + '"></stop>' +
        '<stop offset="100%" stop-color="' + colorCaliente + '"></stop>' +
      '</linearGradient></defs>' +
      marcas +
      '<path class="arco-fondo" fill="none" stroke-linecap="round" d="' + arco + '"></path>' +
      '<path class="arco-valor" fill="none" stroke-linecap="round" d="' + arco +
        '" stroke="url(#' + id + ')" stroke-dasharray="' + circ.toFixed(1) +
        '" stroke-dashoffset="' + (circ * (1 - frac)).toFixed(1) + '"></path>' +
      '<text class="valor-medidor" x="62" y="82" text-anchor="middle">' + escrito + '</text>' +
      '<text class="unidad-medidor" x="62" y="96" text-anchor="middle">' + unidad + '</text>' +
    '</svg><span class="rotulo">' + rotulo + '</span></div>';
}

/* Una barra de segmentos. Sirve para lo que se mira de reojo ---presion,
   temperatura de refrigerante, combustible--- donde importa el tramo y no
   la cifra exacta. */
function barraMedida(rotulo, valor, maximo, unidad, segmentos) {
  const n = segmentos || 12;
  const numero = typeof valor === "number" ? valor : parseFloat(String(valor).replace(",", "."));
  const llenos = isFinite(numero) ? Math.round(Math.max(0, Math.min(1, numero / maximo)) * n) : 0;
  let piezas = "";
  for (let i = 0; i < n; i++) {
    const t = i / (n - 1);
    const color = i < llenos
      ? (t > 0.82 ? "var(--critico)" : t > 0.6 ? "var(--alerta)" : "var(--acento)")
      : "";
    piezas += '<i' + (color ? ' data-lleno="si" style="background:' + color + '"' : "") + '></i>';
  }
  return '<div class="barra-medida"><p class="eyebrow">' + rotulo + '</p>' +
    '<div class="segmentos">' + piezas + '</div>' +
    '<b>' + valor + ' <span style="color:var(--texto-tenue);font-weight:400">' + unidad + '</span></b></div>';
}
/* AQUI ESTABA EL ULTIMO SALTO.
   El arco de cada medidor tiene una transicion de tres decimas: puesto un
   valor nuevo, la aguja **barre** hasta el. Pero `pintarMedidores` rehacia el
   HTML entero cada vez que cambiaba una cifra ---diez veces por segundo con el
   regimen--- y un elemento recien creado no transiciona: aparece ya en su
   posicion final. La aguja no barria, saltaba, diez veces por segundo.

   Ahora los medidores se construyen una vez y despues se les cambia el valor
   en su sitio: tres atributos por medidor. La transicion corre y la aguja se
   mueve como se mueve un instrumento. */
let _firmaMedidores = "";

const _RADIO_MEDIDOR = 46;
const _CIRC_MEDIDOR = Math.PI * _RADIO_MEDIDOR * 1.5;

function actualizarMedidor(rotulo, valor, maximo, unidad) {
  const el = document.querySelector('[data-medidor="' + rotulo + '"]');
  if (!el) return false;
  const frac = (valor === null || valor === undefined) ? 0
             : Math.max(0, Math.min(1, valor / maximo));
  const arco = el.querySelector(".arco-valor");
  if (arco) arco.setAttribute("stroke-dashoffset", (_CIRC_MEDIDOR * (1 - frac)).toFixed(1));
  const txt = el.querySelector(".valor-medidor");
  const escrito = valor === null || valor === undefined ? "—"
    : (Math.abs(valor) < 10 ? Number(valor).toFixed(1).replace(".", ",") : String(Math.round(valor)));
  if (txt && txt.textContent !== escrito) txt.textContent = escrito;
  const svg = el.querySelector("svg");
  if (svg) svg.setAttribute("aria-label", rotulo + ": " + valor + " " + unidad);
  return true;
}

function pintarMedidores() {
  const c = document.getElementById("fila-medidores");
  const t0f = instante();
  const frio = tinta("--acento");
  /* Que medidores hay lo decide la fuente; el HTML se arma una sola vez por
     conjunto y despues solo se actualizan los valores. */
  const cuales = fuente === "openf1"
    ? [["Régimen", t0f.rpm, 13000, "rpm", frio, tinta("--critico")],
       ["Marcha", t0f.marcha, 8, "de 8", tinta("--auto-3"), tinta("--auto-3")],
       ["Velocidad", t0f.velocidad, 360, "km/h", frio, tinta("--alerta")]]
    : [["Régimen", t0f.rpm, 13000, "rpm", frio, tinta("--critico")],
       ["Velocidad", t0f.velocidad, 360, "km/h", frio, tinta("--alerta")],
       ["Temp. motor", t0f.tempMotor, 140, "°C", frio, tinta("--critico")],
       /* `ers_stored_energy` viene en julios y el deposito son cuatro
          megajulios: mostrarlo como porcentaje sobre cien daba «4.000.000 %».
          Se muestra en MJ, que es como se lee en el vehiculo. */
       ["Energía ERS", t0f.ersMJ, 4, "MJ", tinta("--ok"), tinta("--ok")]];

  const firmaSet = [fuente, estadoSesion, tinta("--acento"),
                    cuales.map(m => m[0]).join(",")].join("|");
  if (c.dataset.firma !== firmaSet) {
    c.dataset.firma = firmaSet;
    c.innerHTML = cuales.map(m => medidor.apply(null, m)).join("");
  } else {
    cuales.forEach(m => actualizarMedidor(m[0], m[1], m[2], m[3]));
  }

  /* Las barras son segmentos: no tienen nada que barrer, y rehacerlas cuando
     ninguno cambia de estado es trabajo sin efecto. */
  const firmaBarras = [fuente, estadoSesion, cifra(t0f.combustibleKg, 1),
                       t0f.vueltasRestantes, t0f.tempFrenoDel, t0f.sesgoFreno,
                       tinta("--acento")].join("|");
  if (firmaBarras === _firmaMedidores) return;
  _firmaMedidores = firmaBarras;

  if (fuente === "openf1") {
    // OpenF1 no publica combustible ni frenos: las bandas laterales quedan
    // vacias en lugar de mostrar barras de un dato que no existe.
    const izq2 = document.getElementById("barras-izq");
    const der2 = document.getElementById("barras-der");
    if (izq2) izq2.innerHTML = "";
    if (der2) der2.innerHTML = "";
    document.getElementById("canal-motor").textContent = "";
  } else {
    const t = t0f;
    const izq = document.getElementById("barras-izq");
    const der = document.getElementById("barras-der");
    if (izq) izq.innerHTML =
      // Rotulos cortos: la columna de motor tiene un cuarto del ancho que
      // tenia la franja, y un rotulo que se corta no dice nada.
      barraMedida("Combustible", cifra(t.combustibleKg, 1), 110, "kg", 10) +
      barraMedida("Vueltas restantes", cifra(t.vueltasRestantes, 0), t.vueltas, "vueltas", 10);
    if (der) der.innerHTML =
      barraMedida("Freno delantero", cifra(t.tempFrenoDel, 0), 1000, "°C", 10) +
      barraMedida("Sesgo de freno", cifra(t.sesgoFreno, 0), 100, "%", 10);
    document.getElementById("canal-motor").textContent = "";
  }
}

/* ---------------- avisos ----------------
   Lo que interrumpe la lectura de una vuelta: la bandera en pista, una pieza
   rota, una rueda fuera del asfalto, una penalizacion.

   CADA AVISO DECLARA SU CANAL. Un aviso es una afirmacion sobre lo que
   ocurrio, y una afirmacion sin su origen no se puede discutir: por eso
   debajo de cada uno esta el nombre de la senal que lo dispara. Ese es el
   mismo cuidado que el trabajo exige a las anotaciones automaticas: una
   condicion que no se cumple con claridad no debe anotarse, porque un
   sistema que declara incidentes que no ocurrieron pierde la confianza que
   los ciertos le darian.

   Los avisos los levanta la API recorriendo la sesion; aca solo se muestran. */

const SUPERFICIES = { 0: "asfalto", 1: "hierba", 2: "grava", 3: "arena", 4: "tierra" };

/* Cada aviso lleva CUANDO ocurrio, no solo que ocurrio. Un aviso sin momento
   no se puede ubicar en la carrera ni cruzar con la traza: «piso dañado» sirve
   poco; «piso dañado en la vuelta 12, metro 3.065» se busca en el grafico.
   La lista va del mas reciente al mas viejo, que es el orden en que llegaron. */
/* LOS AVISOS LOS LEVANTA LA API.
   `/sesiones/{id}/avisos` recorre la sesion y devuelve el primer instante en
   que cada condicion se cumple, con la vuelta, el metro, el canal que la
   dispara y el umbral. Antes habia doce avisos escritos en este archivo con
   posiciones inventadas; el unico dato real de aquello era el nombre del
   canal. */
function avisosDeLaFuente() {
  return estado.avisos;
}

/* Lo mismo con los avisos: la lista solo cambia cuando llega uno nuevo. */
let _firmaAvisos = "";
let _cuantosAvisos = 0;

function pintarAvisos() {
  const cont = document.getElementById("lista-avisos");
  if (!cont) return;
  const todos = avisosDeLaFuente();

  /* SOLO LO QUE YA OCURRIO.
     Un panel que muestra de entrada lo que va a pasar no es un panel de
     avisos: es un resumen. Lo que lo vuelve util durante la reproduccion es
     que los avisos **van llegando**, en el mismo orden y en el mismo momento
     en que llegaron. En vivo se muestran todos, porque en vivo el cabezal
     esta siempre en el ultimo dato. */
  const hasta = estadoSesion === "vivo" ? 1 : cabezal + 1e-9;
  const avisos = todos.filter(a => a.en <= hasta).sort((a, b) => b.en - a.en);
  const firma = [fuente, estadoSesion, avisos.length, todos.length,
                 tinta("--acento")].join("|");
  if (firma === _firmaAvisos) return;
  // Solo se anuncia el que **acaba de llegar**: si la lista se acorto es
  // porque se rebobino, y entonces no hay nada nuevo que anunciar.
  const recienLlego = avisos.length > _cuantosAvisos;
  _firmaAvisos = firma;
  _cuantosAvisos = avisos.length;
  const motivo = fuente === "openf1"
    ? "OpenF1 no publica banderas, daño ni tipo de superficie: no hay con qué levantar un aviso."
    : "El bus del vehículo no declara estado de carrera ni daño de carrocería.";

  if (!avisos.length) {
    cont.innerHTML = '<p class="nota sin-avisos">Todavía no ocurrió nada en esta ' +
      'sesión hasta el punto que estás mirando. Los avisos van apareciendo a ' +
      'medida que avanza la reproducción, el más reciente arriba.</p>';
    document.getElementById("canal-avisos").textContent =
      "0/" + todos.length;
    document.getElementById("motivo-avisos").textContent = motivo;
    return;
  }

  cont.innerHTML = avisos.map((a, i) =>
    '<div class="aviso' + (i === 0 ? " nuevo" : "") +
      (i === 0 && recienLlego ? " recien" : "") + '" data-nivel="' + a.nivel + '">' +
      '<span class="cuando"><b>' + (hayVueltas() && a.vuelta ? "Vuelta " + a.vuelta : "Tramo") + '</b>' +
        (a.metro ? Math.round(a.metro).toLocaleString("es-AR") + " m" : "") + '</span>' +
      '<span class="marca"></span>' +
      '<span class="que">' + a.que + '</span>' +
      // El nombre del canal sale del renglon visible y queda en el titulo:
      // sigue disponible para quien lo necesite, sin competir con el aviso.
      // El detalle es el valor medido contra su umbral: es lo que sostiene el
      // aviso, y el canal queda en el titulo para quien quiera discutirlo.
      '<span class="canal" title="Canal: ' + a.canal + ' · umbral ' + a.umbral + '">' +
        cifra(a.valor, 1) + ' ' + (a.unidad || "") +
        (a.umbral !== undefined && a.umbral !== null ? ' · umbral ' + a.umbral : '') +
      '</span>' +
    '</div>').join("");

  const graves = avisos.filter(a => a.nivel === "critico").length;
  const leves = avisos.filter(a => a.nivel === "alerta").length;
  /* El recuento en un renglon: en dos ocupaba el alto de un aviso entero, y
     un aviso vale mas que su recuento. «1 graves» ademas estaba mal escrito. */
  const plural = (n, uno, varios) => n + " " + (n === 1 ? uno : varios);
  document.getElementById("canal-avisos").textContent =
    plural(graves, "grave", "graves") + " · " + plural(leves, "leve", "leves") +
    " · " + avisos.length + "/" + todos.length;
  document.getElementById("motivo-avisos").textContent =
    fuente === "openf1"
      ? "OpenF1 no publica banderas, daño ni tipo de superficie: no hay con qué levantar un aviso."
      : "El bus del vehículo no declara estado de carrera ni daño de carrocería.";
}

/* ---------------- aceleraciones ---------------- */
/* El clima deja de ser cuatro celdas iguales: la temperatura del aire manda,
   con su icono, y el resto acompana. */
let _firmaClima = "";

/* El clima es el que la fuente publico en la sesion: temperatura de aire y
   de pista, codigo de clima y bandera. No hay humedad ni viento porque el
   paquete de sesion no los trae; se muestran los que hay. */
function pintarClima() {
  const c = document.getElementById("clima");
  if (!c) return;
  const d = estado.clima;
  if (!d) { c.innerHTML = ""; return; }

  const iconos = {
    "despejado": "sol", "nubes ligeras": "nube", "cubierto": "nube",
    "lluvia ligera": "lluvia", "lluvia fuerte": "lluvia", "tormenta": "lluvia"
  };
  const cual = iconos[d.clima] || "nube";
  const dibujo = cual === "sol"
    ? '<svg class="icono" viewBox="0 0 48 48" role="img" aria-label="Despejado">' +
      '<circle cx="24" cy="24" r="10" fill="var(--alerta)"></circle>' +
      '<g stroke="var(--alerta)" stroke-width="2.5" stroke-linecap="round" opacity=".75">' +
      '<line x1="24" y1="3" x2="24" y2="9"></line><line x1="24" y1="39" x2="24" y2="45"></line>' +
      '<line x1="3" y1="24" x2="9" y2="24"></line><line x1="39" y1="24" x2="45" y2="24"></line>' +
      '</g></svg>'
    : cual === "lluvia"
      ? '<svg class="icono" viewBox="0 0 48 48" role="img" aria-label="Lluvia">' +
        '<path d="M14 30 a8 8 0 0 1 1 -16 a11 11 0 0 1 20 4 a7 7 0 0 1 -1 12 z" fill="var(--texto-tenue)"></path>' +
        '<g stroke="var(--auto-3)" stroke-width="2.5" stroke-linecap="round">' +
        '<line x1="17" y1="34" x2="15" y2="42"></line><line x1="25" y1="34" x2="23" y2="42"></line>' +
        '<line x1="33" y1="34" x2="31" y2="42"></line></g></svg>'
      : '<svg class="icono" viewBox="0 0 48 48" role="img" aria-label="Nubes">' +
        '<path d="M14 32 a8 8 0 0 1 1 -16 a11 11 0 0 1 20 4 a7 7 0 0 1 -1 12 z" fill="var(--texto-tenue)"></path></svg>';

  const banderas = { "ninguna": "ok", "verde": "ok", "amarilla": "alerta",
                     "roja": "critico", "azul": "info" };
  const bandera = d.bandera_texto || "ninguna";
  const celdas = [
    ["Pista", d.temperatura_pista_c, "°C"],
    ["Aire", d.temperatura_aire_c, "°C"],
    ["Bandera", null, null],
    ["Coche de seg.", d.retraso_del_coche_de_seguridad_s, "s"]
  ];

  c.innerHTML =
    '<div class="clima-principal">' + dibujo +
      '<div><span class="cifra-grande">' + cifra(d.temperatura_aire_c, 1) + '</span>' +
      '<span class="unidad-grande">°C</span>' +
      '<p class="eyebrow">' + (d.clima || "sin declarar") + '</p></div>' +
      '<span class="bandera ' + (banderas[bandera] || "ok") + '">' + bandera + '</span>' +
    '</div>' +
    '<dl class="clima-rejilla">' +
      celdas.map(f => '<div><dt>' + f[0] + '</dt><dd>' +
        (f[0] === "Bandera" ? bandera : cifra(f[1], 1) + "&nbsp;" + f[2]) +
        '</dd></div>').join("") +
    '</dl>';
}

function pintarG() {
  const tres = fuente === "f1";
  const t = instante();
  const g = v => (v === null || v === undefined) ? "—"
    : (v >= 0 ? "+" : "") + Number(v).toFixed(2).replace(".", ",") + " g";
  // Los nombres son los de la señal que llena cada renglon en esta fuente.
  const cs = tres
    ? [["g_force_longitudinal", g(t.gLong)], ["g_force_lateral", g(t.gLat)],
       ["g_force_vertical", g(t.gVert)]]
    : [["accel_longitudinal", g(t.gLong)], ["accel_lateral", g(t.gLat)],
       ["yaw_rate", t.gVert === null ? "—" : Number(t.gVert).toFixed(1).replace(".", ",") + " °/s"]];
  /* El HTML de los tres canales se rehacia sesenta veces por segundo para
     mostrar los mismos tres numeros. El nombre del canal se recorta cuando la
     columna es angosta: queda entero en el titulo. */
  const cajaG = document.getElementById("canales-g");
  const firmaG = cs.map(c => c.join("=")).join("|");
  if (cajaG.dataset.firma !== firmaG) {
    cajaG.dataset.firma = firmaG;
    cajaG.innerHTML =
      cs.map(c => '<div title="' + c[0] + '"><dt>' + c[0] + '</dt><dd>' +
                  c[1] + '</dd></div>').join("");
  }
  document.getElementById("canal-g").textContent = tres ? "3 ejes" : "2 ejes + guiñada";

  // La estela es la huella de la vuelta entera: no cambia al avanzar.
  const pts = _estelaG(t.vuelta);
  const estela = document.getElementById("estela-g");
  const firmaEstela = pts.length + "|" + pts[pts.length - 1].join(",");
  if (estela.dataset.firma !== firmaEstela) {
    estela.dataset.firma = firmaEstela;
    estela.setAttribute("d", "M" + pts.map(p => p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" L"));
  }
  // El punto va donde esta el cabezal, no dando vueltas por su cuenta: lo que
  // muestra es el instante que se esta mirando.
  const idx = Math.min(pts.length - 1, Math.max(0, Math.round(instante().fraccion * (pts.length - 1))));
  const punto = document.getElementById("punto-g");
  const halo = document.getElementById("halo-g");
  if (punto && halo) {
    punto.setAttribute("cx", pts[idx][0].toFixed(1));
    punto.setAttribute("cy", pts[idx][1].toFixed(1));
    halo.setAttribute("cx", pts[idx][0].toFixed(1));
    halo.setAttribute("cy", pts[idx][1].toFixed(1));
  }
}

/* El punto recorre la estela. Es la unica animacion por temporizador de la
   vista, y se apaga si la persona declaro preferir movimiento reducido. */
function _estelaG(vuelta) {
  const longitudinal = serieDeCanal("glong", vuelta, claveVehiculoPropio()) || [];
  const lateral = serieDeCanal("glat", vuelta, claveVehiculoPropio()) || [];
  const n = Math.min(longitudinal.length, lateral.length);
  if (!n) return [[90, 90]];
  const valores = [];
  const paso = Math.max(1, Math.floor(n / 80));
  for (let i = 0; i < n; i += paso) valores.push([Number(lateral[i][1]), Number(longitudinal[i][1])]);
  const maximo = Math.max(1, ...valores.flat().map(Math.abs));
  return valores.map(p => [90 + (p[0] / maximo) * 68, 90 - (p[1] / maximo) * 68]);
}

/* ---------------- trazado real ---------------- */
function pintarPista() {
  const linea = document.getElementById("linea-pista");
  linea.setAttribute("d", PISTA.path);

  /* EL DIBUJO SE AJUSTA A SU CAJA.
     El `viewBox` estaba fijo en 360 x 170 y el recorrido no lo llenaba: el
     trazado se dibujaba con margenes muertos a los costados y quedaba mas
     chico de lo que el panel permitia. Se toma la caja real del recorrido
     ---la que devuelve el navegador despues de dibujarlo--- y se le da al
     `viewBox`, con un margen para los numeros de curva y para el rotulo del
     vehiculo. Asi el dibujo usa todo el ancho disponible. */
  const svg = linea.ownerSVGElement;
  if (svg && !svg.dataset.ajustado) {
    const caja = linea.getBBox();
    if (caja.width > 0 && caja.height > 0) {
      const m = 10;
      svg.setAttribute("viewBox",
        (caja.x - m) + " " + (caja.y - m) + " " +
        (caja.width + m * 2) + " " + (caja.height + m * 2));
      svg.dataset.ajustado = "si";
    }
  }

  const largo = linea.getTotalLength();
  const g = document.getElementById("marcas-pista");
  if (estadoSesion === "vacio") { g.innerHTML = ""; g.dataset.firma = ""; return; }

  /* LAS CURVAS SE DIBUJAN UNA VEZ.
     Estaban rehaciendose en cada llamada ---trece grupos con circulo y numero,
     mas la marca de cada vehiculo---, y con la reproduccion a sesenta cuadros
     por segundo eso es rehacer medio centenar de nodos SVG sesenta veces por
     segundo para que ninguno cambie. Ahora se rehacen solo cuando cambia algo
     que las afecta ---la fuente, que vehiculos se miran o el tema--- y en cada
     cuadro se mueve unicamente la marca del vehiculo. */
  /* La firma tiene que incluir **cuantos vehiculos hay en pista**: las
     posiciones llegan despues que la sesion, y sin esto las marcas no se
     rehacian al llegar. Se veia un solo vehiculo en una carrera de dos. */
  const _enPista = posicionesAhora();
  const firma = [fuente, [...seleccion].join(","),
                 _enPista ? Object.keys(_enPista).length : 0,
                 tinta("--acento")].join("|");
  const rehacer = g.dataset.firma !== firma;
  if (rehacer) { g.innerHTML = ""; g.dataset.firma = firma; }
  // Curvas numeradas sobre el trazado y nombradas en la leyenda, que es como
  // las publican los mapas del circuito: rotular cada una en el dibujo las
  // superpone, porque las dobles caen a pocos metros una de otra.
  /* CADA CURVA SE UBICA POR SU METRO, NO POR UNAS COORDENADAS GUARDADAS.
     El catalogo externo da el nombre y el metro de la vuelta en que empieza
     cada curva; el trazado da el recorrido. Con los dos, el punto sale de
     recorrer el dibujo hasta ese metro. Asi el nombre sigue siendo anotacion
     citada y la posicion sigue siendo medicion, que es la separacion que el
     trabajo sostiene en todos lados. */
  if (rehacer && CURVAS.length && PISTA.largo_m) {
    const zonas = CURVAS.map((c, i) => {
      const p = linea.getPointAtLength(largo * Math.max(0, Math.min(1, c.metro_medido / PISTA.largo_m)));
      return { nombre: c.nombre, xy: [p.x, p.y], metro: c.metro_medido, orden: i + 1 };
    });
    /* CADA MARCA LLEVA SU NOMBRE ENCIMA.
       La leyenda de once renglones ocupaba un tercio del panel para decir algo
       que solo se consulta cuando uno se pregunta «que curva es esta». Ahora
       cada numero responde esa pregunta al apuntarlo: el `<title>` lo dice al
       lector de pantalla y al globo del navegador, y el globo propio lo dice
       con el tipo y el color del tablero. Se llega tambien con el teclado
       ---por eso `tabindex`--- porque si no, el nombre desaparece para quien
       no usa el puntero. */
    const NS = "http://www.w3.org/2000/svg";
    zonas.forEach((z, i) => {
      const marca = document.createElementNS(NS, "g");
      marca.setAttribute("class", "marca-curva");
      marca.setAttribute("tabindex", "0");
      marca.setAttribute("role", "img");
      marca.setAttribute("aria-label", "Curva " + (i + 1) + ": " + z.nombre);
      marca.dataset.nombre = z.nombre;
      marca.dataset.numero = String(i + 1);

      const rotulo = document.createElementNS(NS, "title");
      rotulo.textContent = (i + 1) + " · " + z.nombre;
      marca.appendChild(rotulo);

      // Blanco de puntero mas grande que el punto dibujado: apuntar un
      // circulo de seis pixeles con el mouse es incomodo.
      const blanco = document.createElementNS(NS, "circle");
      blanco.setAttribute("cx", z.xy[0]); blanco.setAttribute("cy", z.xy[1]);
      blanco.setAttribute("r", "11"); blanco.setAttribute("fill", "transparent");
      marca.appendChild(blanco);

      const p = document.createElementNS(NS, "circle");
      p.setAttribute("cx", z.xy[0]); p.setAttribute("cy", z.xy[1]); p.setAttribute("r", "6");
      p.style.fill = tinta("--superficie"); p.style.stroke = tinta("--linea-fuerte");
      p.style.strokeWidth = "1.2";
      marca.appendChild(p);

      const r = document.createElementNS(NS, "text");
      r.setAttribute("x", z.xy[0]); r.setAttribute("y", z.xy[1] + 2.6);
      r.setAttribute("text-anchor", "middle");
      r.setAttribute("font-size", "7"); r.setAttribute("font-weight", "600");
      r.setAttribute("font-family", "IBM Plex Mono, monospace");
      r.style.fill = tinta("--texto-medio");
      r.setAttribute("pointer-events", "none");
      r.textContent = String(i + 1);
      marca.appendChild(r);

      g.appendChild(marca);
    });
    document.getElementById("leyenda-curvas").innerHTML = zonas
      .map((z, i) => '<span><b>' + (i + 1) + '</b>' + z.nombre + '</span>').join("");
  } else if (rehacer) {
    document.getElementById("leyenda-curvas").innerHTML = "";
  }

  const NSV = "http://www.w3.org/2000/svg";
  /* Sobre el trazado se dibujan **todos** los vehiculos de los que la fuente
     publica posicion, no solo los seleccionados: la seleccion decide de quien
     se grafican las señales, no a quien se ve en la pista. */
  const enPista = posicionesAhora();
  const claves = enPista ? Object.keys(enPista) : [...seleccion];
  if (rehacer) {
    claves.forEach(id => {
      const a = AUTOS.find(x => x.id === id) || autoPropio();
      const grupo = document.createElementNS(NSV, "g");
      grupo.dataset.clave = id;
      grupo.setAttribute("class", "auto-en-pista");
      const c = document.createElementNS(NSV, "circle");
      // El propio se dibuja mas grande: es de quien se estan mirando las señales.
      c.setAttribute("r", a.propio ? "7" : "5");
      c.style.fill = tinta(a.tinta);
      c.setAttribute("class", "marca-auto" + (a.propio ? " propio" : ""));
      const t = document.createElementNS(NSV, "text");
      t.setAttribute("text-anchor", "middle"); t.style.fill = tinta("--texto-medio");
      t.setAttribute("font-size", "9.5"); t.setAttribute("font-family", "IBM Plex Mono, monospace");
      t.textContent = a.nombre;
      t.setAttribute("font-size", a.propio ? "9.5" : "8");
      grupo.appendChild(c); grupo.appendChild(t);
      g.appendChild(grupo);
    });
  }

  /* Lo unico que cambia de un cuadro al siguiente: donde esta cada vehiculo.
     Y ahora cada uno va **en su propio metro**, no en el del propio corrido un
     poco: por eso se ven los adelantamientos. Sin posiciones ---una fuente que
     no las publique--- se cae en lo unico que se puede afirmar, que es donde
     esta el vehiculo del que si hay serie. */
  const marcas = g.querySelectorAll(".auto-en-pista");
  const f = instante().fraccion;
  const enPistaAhora = posicionesAhora();
  const largoVuelta = PISTA.largo_m || 1;
  marcas.forEach((grupo, i) => {
    let frac = f;
    const clave = grupo.dataset.clave;
    if (enPistaAhora && enPistaAhora[clave] !== undefined) {
      frac = Math.max(0, Math.min(1, enPistaAhora[clave] / largoVuelta));
    }
    const p = linea.getPointAtLength(largo * frac);
    const c = grupo.firstChild, t = grupo.lastChild;
    c.setAttribute("cx", p.x.toFixed(1)); c.setAttribute("cy", p.y.toFixed(1));
    t.setAttribute("x", p.x.toFixed(1)); t.setAttribute("y", (p.y - 10).toFixed(1));
  });
}

/* El globo con el nombre de la curva. Se coloca sobre la marca apuntada,
   midiendo su caja en pantalla: el dibujo se escala con el panel, asi que las
   coordenadas del SVG no sirven para ubicar un elemento HTML. */
(function globoDeCurvas() {
  const panel = document.querySelector(".pista .cuerpo-instrumento");
  const globo = document.getElementById("globo-curva");
  if (!panel || !globo) return;

  function mostrar(marca) {
    const caja = marca.getBoundingClientRect();
    const base = panel.getBoundingClientRect();
    globo.innerHTML = "<b>" + marca.dataset.numero + "</b>" + marca.dataset.nombre;
    globo.style.left = (caja.left + caja.width / 2 - base.left) + "px";
    globo.style.top = (caja.top + caja.height / 2 - base.top) + "px";
    globo.hidden = false;
  }
  const ocultar = () => { globo.hidden = true; };

  panel.addEventListener("mouseover", e => {
    const m = e.target.closest(".marca-curva");
    if (m) mostrar(m); else ocultar();
  });
  panel.addEventListener("mouseleave", ocultar);
  panel.addEventListener("focusin", e => {
    const m = e.target.closest(".marca-curva");
    if (m) mostrar(m);
  });
  panel.addEventListener("focusout", ocultar);
})();

/* ============================================================
   EL TRAZADO
   ------------------------------------------------------------
   La API devuelve los puntos crudos del recorrido, en las unidades del
   mundo del simulador. Para dibujarlo hacen falta tres pasos, y los tres
   son decisiones de presentacion, no del dato:

   1. Acostarlo. El circuito se gira hasta que su eje mas largo quede
      horizontal ---el eje que sale de la nube de puntos, no uno elegido a
      ojo---, que es como lo publican los mapas del circuito.
   2. Encajarlo en la caja del dibujo, conservando la proporcion.
   3. Voltear el eje vertical si hace falta: en pantalla el eje Y crece
      hacia abajo y en el mundo hacia arriba, y sin esto el circuito sale
      espejado. La API declara en `para_dibujarlo` si toca invertir.
   ============================================================ */
function trazadoAPath(puntos, invertirY) {
  if (!puntos || puntos.length < 3) return { path: "", proyectar: null };

  // 1. El eje principal de la nube, por su matriz de covarianza.
  let mx = 0, my = 0;
  puntos.forEach(p => { mx += p[0]; my += p[1]; });
  mx /= puntos.length; my /= puntos.length;
  let sxx = 0, syy = 0, sxy = 0;
  puntos.forEach(p => {
    const dx = p[0] - mx, dy = p[1] - my;
    sxx += dx * dx; syy += dy * dy; sxy += dx * dy;
  });
  const ang = 0.5 * Math.atan2(2 * sxy, sxx - syy);
  const cos = Math.cos(-ang), sen = Math.sin(-ang);

  const giro = puntos.map(p => {
    const dx = p[0] - mx, dy = (p[1] - my) * (invertirY ? -1 : 1);
    return [dx * cos - dy * sen, dx * sen + dy * cos];
  });

  // 2. A la caja del dibujo, con margen para los numeros de curva.
  const xs = giro.map(p => p[0]), ys = giro.map(p => p[1]);
  const x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs);
  const y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
  const m = 16, W = 360, H = 170;
  const k = Math.min((W - m * 2) / Math.max(1e-6, x1 - x0),
                     (H - m * 2) / Math.max(1e-6, y1 - y0));
  const ox = (W - (x1 - x0) * k) / 2 - x0 * k;
  const oy = (H - (y1 - y0) * k) / 2 - y0 * k;
  const proyectar = p => [p[0] * k + ox, p[1] * k + oy];

  const d = giro.map((p, i) => {
    const q = proyectar(p);
    return (i === 0 ? "M" : "L") + q[0].toFixed(1) + " " + q[1].toFixed(1);
  }).join(" ") + " Z";
  return { path: d, proyectar: proyectar };
}

/* ---------------- series ---------------- */
/* ============================================================
   LAS SERIES
   ------------------------------------------------------------
   Una serie es una señal contra la distancia recorrida, de una vuelta y de
   un vehiculo. La API las entrega ya submuestreadas y declarando cuantas
   muestras habia detras. Aca se guardan por vuelta para no volver a pedir lo
   mismo, y se pide la siguiente mientras se mira la actual.
   ============================================================ */

/* Los canales que este tablero sabe dibujar. Se piden todos y se quedan los
   que la fuente devuelva con dato: asi la lista de señales disponibles la
   arma la fuente, no una tabla escrita aca. */
function senalesCandidatas() {
  const vistas = [];
  METRICAS.forEach(m => {
    if (m.fuentes.indexOf(fuente) === -1) return;
    const n = nombreDeSenal(m.id);
    if (vistas.indexOf(n) === -1) vistas.push(n);
  });
  return vistas;
}

function claveVehiculoPropio() { return estado.vehiculoClave; }

/* Una señal de una vuelta, como pares [metro, valor]. Devuelve `null` si la
   vuelta todavia no llego y `[]` si llego pero la fuente no trae ese canal:
   quien dibuja tiene que poder distinguir «no hay dato» de «todavia no
   llego». */
function serieDeCanal(canal, vuelta, clave) {
  if (estadoSesion === "vivo") {
    const vehiculo = vivo.series.get(clave || claveVehiculoPropio());
    return vehiculo ? (vehiculo.get(nombreDeSenal(canal)) || []) : [];
  }
  const bloque = estado.series[vuelta];
  if (!bloque) return null;
  const veh = bloque.vehiculos[clave];
  if (!veh) return [];
  const ys = veh[nombreDeSenal(canal)];
  const xs = veh.distancia_m;
  if (!ys || !xs) return [];
  const salida = [];
  for (let i = 0; i < xs.length; i++) {
    if (ys[i] === null || ys[i] === undefined) continue;
    salida.push([xs[i], ys[i]]);
  }
  return salida;
}

function serieVelocidad(clave, vuelta) {
  return serieDeCanal("speed", vuelta || vueltaElegida || 1, clave) || [];
}

/* Pide una vuelta si no esta y no se esta pidiendo ya. */
function asegurarVuelta(numero) {
  if (!estado.abierta || numero < 1) return Promise.resolve(null);
  const conocidos = estado.series[numero] && estado.series[numero].vehiculos || {};
  const pedidos = [...seleccion].filter(x => typeof x === "string");
  const faltantes = pedidos.filter(id => !conocidos[id]);
  if (estado.series[numero] && (!pedidos.length || !faltantes.length)) {
    return Promise.resolve(estado.series[numero]);
  }
  if (estado.pidiendo[numero]) return estado.pidiendo[numero];
  /* La API admite doce señales por consulta ---un limite razonable, porque
     cada una es una pasada sobre la tabla---. La simulacion publica mas: se
     piden en tandas de doce y se juntan, que es mas barato que pedir de a una
     y mas honesto que quedarse con doce y no decirlo. */
  const todas = senalesCandidatas();
  const tandas = [];
  for (let i = 0; i < todas.length; i += 12) tandas.push(todas.slice(i, i + 12));
  const autos = estado.series[numero] ? faltantes : pedidos;
  const sesionPedida = estado.abierta.session_id;
  const base = "/sesiones/" + encodeURIComponent(estado.abierta.session_id) +
               "/series?vuelta=" + numero +
               (autos.length ? "&vehiculos=" + encodeURIComponent(autos.join(",")) : "") +
               "&puntos=" + PUNTOS_POR_VUELTA + "&senales=";

  const peticion = Promise.all(tandas.map(t => pedir(base + encodeURIComponent(t.join(",")))))
    .then(partes => {
      const d = partes[0];
      // Las tandas siguientes aportan sus columnas al mismo vehiculo.
      partes.slice(1).forEach(p => {
        Object.keys(p.vehiculos || {}).forEach(k => {
          if (!d.vehiculos[k]) { d.vehiculos[k] = p.vehiculos[k]; return; }
          Object.keys(p.vehiculos[k]).forEach(c => {
            if (c !== "distancia_m") d.vehiculos[k][c] = p.vehiculos[k][c];
          });
        });
      });
      return d;
    })
    .then(d => {
      if (!estado.abierta || estado.abierta.session_id !== sesionPedida) return null;
      const anterior = estado.series[numero];
      if (anterior) {
        Object.assign(anterior.vehiculos, d.vehiculos || {});
        anterior.submuestreado = anterior.submuestreado || d.submuestreado;
        d = anterior;
      } else {
        estado.series[numero] = d;
      }
      const claves = Object.keys(d.vehiculos);
      if (!AUTOS.length && claves.length) {
        armarAutos(claves);
        seleccion = new Set([claves[0]]);
      }
      if (!estado.vehiculoClave) estado.vehiculoClave = claves[0] || null;
      anotarDisponibles(d);
      olvidarCaches();
      render();
      /* El acelerador de la traza puede haber bloqueado el ultimo redibujado
         justo cuando llegaba la vuelta; se destraba y se dibuja. Sin esto los
         graficos podian quedar diciendo «sin dato» con la vuelta ya en la
         mano, que es la peor forma de estar equivocado: la que se ve. */
      _ultimaTraza = 0;
      dibujarTraza();
      moverCabezalesGraficos();
      return d;
    })
    .catch(e => {
      // Una vuelta que no se puede traer no rompe el tablero: se avisa y se
      // sigue con las que si estan.
      avisar("Vuelta " + numero + ": " + e.message, true);
      return null;
    })
    .finally(() => { delete estado.pidiendo[numero]; });
  estado.pidiendo[numero] = peticion;
  return peticion;
}

/* ============================================================
   QUIEN ESTA DONDE
   ------------------------------------------------------------
   Un adelantamiento no se ve en las series: esas van contra la distancia de
   **cada** vehiculo, y dos que pasaron por el mismo metro con veinte segundos
   de diferencia no estuvieron juntos. `/sesiones/{id}/posiciones` reparte la
   vuelta en intervalos de tiempo iguales y dice donde estaba cada uno en cada
   intervalo. Sobre eso si se ve quien pasa a quien.
   ============================================================ */
function asegurarPosiciones(numero) {
  if (!estado.abierta || estado.posiciones[numero] || estado.pidiendoPos[numero]) return;
  estado.pidiendoPos[numero] = true;
  pedir("/sesiones/" + encodeURIComponent(estado.abierta.session_id) +
        "/posiciones?vuelta=" + numero + "&puntos=200")
    .then(d => {
      estado.posiciones[numero] = d;
      // Los rivales entran a la lista de vehiculos aunque no tengan telemetria
      // privada: de ellos se muestra donde estan, que es lo que la fuente
      // entrega de todos.
      const claves = Object.keys(d.vehiculos || {});
      if (claves.length > AUTOS.length) armarAutos(claves.sort());
      render();
    })
    // Un fallo de red aca no es grave; uno de dibujo si, y no puede quedar mudo.
    .catch(e => { if (e instanceof TypeError) console.error(e); })
    .then(() => { delete estado.pidiendoPos[numero]; });
}

/* Donde esta cada vehiculo en este instante, en metros de la vuelta. */
function posicionesAhora() {
  const t = instante();
  const d = estado.posiciones[t.vuelta];
  if (!d) return null;
  const salida = {};
  Object.keys(d.vehiculos).forEach(clave => {
    const serie = d.vehiculos[clave];
    const i = Math.min(serie.length - 1, Math.max(0, Math.round(t.fraccion * (serie.length - 1))));
    // El intervalo puede venir vacio: se busca hacia atras el ultimo con dato.
    for (let k = i; k >= 0; k--) {
      if (serie[k] !== null && serie[k] !== undefined) { salida[clave] = serie[k]; break; }
    }
  });
  return salida;
}

/* Que señales trajo la fuente con dato. Es lo que gobierna que instrumentos
   se muestran y que canales ofrece el panel de señales. */
function anotarDisponibles(d) {
  const veh = d.vehiculos[Object.keys(d.vehiculos)[0]];
  if (!veh) return;
  Object.keys(veh).forEach(nombre => {
    if (["distancia_m", "distancia_sesion_m", "timestamp_utc"].indexOf(nombre) !== -1) return;
    if (veh[nombre].some(x => x !== null && x !== undefined)) estado.disponibles.add(nombre);
  });
}

/* Antes esto **derivaba** cada magnitud de la velocidad con una formula
   inventada: el acelerador salia de la pendiente del trazo, el regimen de una
   regla de tres, las aceleraciones de un seno. Ahora cada canal es la señal
   que la fuente publica, tal como esta guardada. La funcion queda con este
   nombre porque el resto del codigo la llama asi, pero ya no deriva: busca. */
function derivar(_sinUso, metrica, vuelta, clave) {
  return serieDeCanal(metrica, vuelta || vueltaElegida || 1, clave) || [];
}


// Cada vehiculo trae su propia serie desde la base: no hay ninguno derivado
// de otro.
/* ESTA ERA LA CAUSA DE LOS SALTOS.
   `serieVelocidad` construia un arreglo nuevo de dos mil seiscientos pares en
   cada llamada, y `instante()` la llamaba una vez, y a `instante()` la llamaban
   siete funciones por cuadro. Reproduciendo a sesenta cuadros por segundo eso
   son mas de un millon de objetos por segundo creados y tirados: el navegador
   pasaba mas tiempo recogiendo basura que dibujando, y de ahi los saltos.

   La serie de cada vehiculo no cambia nunca: se calcula una vez y se guarda. */

/* Que canales tiene cada fuente, con el nombre real de la senal.
   ---------------------------------------------------------------------
   La simulacion publica ciento trece senales; mostrar cinco era una
   decision de la maqueta, no del dato. Aca estan las que tienen sentido
   graficar contra la distancia, y la grilla se llena con las que la fuente
   activa efectivamente tenga. */
const CANALES_POR_FUENTE = {
  f1: ["speed", "throttle", "brake", "rpm", "gear", "glong", "glat", "gvert",
       "steer", "drs", "ers", "fuel", "engineTemp", "tyre", "brakeTemp",
       "slip", "wheelFL", "wheelRR", "gap"],
  openf1: ["speed", "throttle", "brake", "rpm", "gear", "drs", "gap"],
  can: ["speed", "throttle", "brake", "glong", "glat", "steer", "steerRate",
        "yaw", "wheelFL", "wheelRR"]
};

/* QUE VIENE ENCENDIDO Y QUE NO.
   El panel ofrece **todas** las señales graficables que la fuente tenga
   ---diecinueve en la simulacion, diez en el bus--- y arranca con las cuatro
   que se miran siempre. Encender una mas agrega su grafico a la cabina;
   apagarla lo saca. Antes el panel ofrecia solo esas cuatro y las quince
   restantes vivian nada mas que en la vista de detalle, que es esconder lo
   que la fuente entrega detras de un boton.

   LA ELECCION ES DE CADA FUENTE, NO GLOBAL.
   Con un solo conjunto compartido, pasar de la simulacion al bus arrastraba
   lo que estuviera encendido alla: como `speed` y `brake` existen en las dos,
   el bus abria con esas dos y sin las suyas propias ---aceleracion
   longitudinal y direccion---, que son justamente las que lo distinguen. Cada
   fuente recuerda lo suyo y arranca con sus cuatro. */
const CANALES_ELEGIDOS = {};

function elegidos() {
  if (!CANALES_ELEGIDOS[fuente]) {
    const m = {};
    (CANALES_POR_FUENTE[fuente] || []).forEach(c => { m[c] = false; });
    (PRINCIPALES_POR_FUENTE[fuente] || []).forEach(c => { m[c] = true; });
    CANALES_ELEGIDOS[fuente] = m;
  }
  return CANALES_ELEGIDOS[fuente];
}

function canalesDeLaFuente() {
  return CANALES_POR_FUENTE[fuente] || [];
}

/* Si quedo todo apagado ---solo puede pasar cambiando de fuente--- vuelven
   las cuatro de siempre: la pantalla tiene que abrir mostrando algo. */
function encenderPrincipales() {
  if (canalesDeLaFuente().some(id => elegidos()[id])) return;
  canalesPrincipales().forEach(id => { elegidos()[id] = true; });
}

/* QUE SE MUESTRA EN LA PRINCIPAL, Y QUE NO.
   ---------------------------------------------------------------------
   Poner las diecinueve senales en la pantalla principal las volvia a todas
   igual de importantes, que es lo mismo que no jerarquizar ninguna. La
   principal muestra **las cuatro que se miran siempre** al leer una vuelta,
   y llenan exactamente una fila de la grilla. El resto vive en la vista de
   detalle, a un boton de distancia.

   Cuatro y no cinco ni seis: con cuatro columnas, cualquier otro numero
   deja la fila abierta. */
const PRINCIPALES_POR_FUENTE = {
  f1: ["speed", "throttle", "brake", "rpm"],
  openf1: ["speed", "throttle", "brake", "rpm"],
  can: ["speed", "throttle", "glong", "steer"]
};

function canalesPrincipales() {
  const disponibles = canalesDeLaFuente();
  return (PRINCIPALES_POR_FUENTE[fuente] || []).filter(id => disponibles.indexOf(id) !== -1);
}

/* Las que se estan graficando: las encendidas de la fuente activa. Si no hay
   ninguna ---porque se cambio de fuente y las de la anterior no existen aca---
   vuelven las cuatro de siempre. */
function canalesDibujados() {
  const activos = canalesDeLaFuente().filter(id => elegidos()[id]);
  if (activos.length) return activos;
  canalesPrincipales().forEach(id => { elegidos()[id] = true; });
  return canalesPrincipales();
}

/* Cuantas señales tiene la fuente y cuantas se estan graficando: sin esa
   cuenta, encender la decimoseptima no se distingue de encender la quinta. */
function contarCanales() {
  const e = document.getElementById("canal-traza");
  if (!e) return;
  const todas = canalesDeLaFuente().length;
  const puestas = canalesDeLaFuente().filter(id => elegidos()[id]).length;
  e.textContent = puestas + " de " + todas + " graficables, en pantalla";
}

function pintarControlesTraza() {
  const c = document.getElementById("controles-traza");
  if (!c) return;
  encenderPrincipales();
  c.innerHTML = "";

  canalesDeLaFuente().forEach(id => {
    const m = METRICAS.find(x => x.id === id);
    if (!m) return;
    const b = document.createElement("button");
    b.className = "boton-menor";
    b.type = "button";
    b.textContent = m.rotulo;
    b.title = nombreDeSenal(id);
    b.setAttribute("aria-pressed", String(elegidos()[id]));
    b.addEventListener("click", () => {
      elegidos()[id] = !elegidos()[id];
      // Apagar la ultima dejaria la cabina sin ningun grafico.
      if (!canalesDeLaFuente().some(x => elegidos()[x])) elegidos()[id] = true;
      b.setAttribute("aria-pressed", String(elegidos()[id]));
      dibujarTraza(); moverCabezalesGraficos();
      contarCanales();
    });
    c.appendChild(b);
  });
  contarCanales();

  /* Las dos acciones del panel no son canales: viven en su propio renglon,
     junto a la explicacion, para que la grilla de arriba sea solo señales. */
  let acciones = document.getElementById("acciones-panel");
  if (!acciones) {
    acciones = document.createElement("div");
    acciones.className = "acciones-panel";
    acciones.id = "acciones-panel";
    c.parentNode.insertBefore(acciones, document.getElementById("nota-traza"));
  }
  acciones.innerHTML = "";

  const todas = document.createElement("button");
  todas.className = "boton-menor";
  todas.type = "button";
  todas.id = "btn-todas-senales";
  const cuantas = canalesDeLaFuente().length;
  todas.textContent = "Ver las " + cuantas + " señales";
  todas.addEventListener("click", abrirDetalle);
  acciones.appendChild(todas);

  const exportarTodo = document.createElement("button");
  exportarTodo.className = "boton-menor";
  exportarTodo.type = "button";
  exportarTodo.textContent = "Exportar datos";
  exportarTodo.addEventListener("click", exportarCsv);
  acciones.appendChild(exportarTodo);

  contarCanales();
}

/* EXPORTAR
   ---------------------------------------------------------------------
   Un enlace con `download` no alcanza dentro del visor de maquetas: la
   pagina no tiene permiso para iniciar una descarga por su cuenta. La
   capacidad de descargas la media: la pagina ofrece el archivo y quien
   mira acepta o rechaza, viendo antes el nombre y el tamano.

   El tablero real, servido desde su propio origen, no necesita esa
   mediacion y usa el enlace directo. Por eso hay dos caminos y se intenta
   primero el de la capacidad; el segundo es el respaldo. */

let _descargas = null;
let _descargasPedidas = false;

async function obtenerDescargas() {
  if (_descargasPedidas) return _descargas;
  _descargasPedidas = true;
  try {
    if (window.claude && typeof window.claude.use === "function") {
      _descargas = await window.claude.use("downloads");
    }
  } catch (error) {
    _descargas = null;
  }
  return _descargas;
}

/* Una descarga nunca es silenciosa: puede rechazarse. Se dice que paso. */
function avisar(texto, esError) {
  const n = document.getElementById("aviso-descarga");
  if (!n) return;
  n.textContent = texto;
  n.dataset.error = esError ? "si" : "no";
  n.dataset.visible = "si";
  clearTimeout(avisar._t);
  avisar._t = setTimeout(() => { n.dataset.visible = "no"; }, 4200);
}

async function guardar(nombre, datos, descripcion) {
  const d = await obtenerDescargas();
  if (d) {
    try {
      const r = await d.save({ filename: nombre, data: datos });
      if (r.status === "saved") avisar(descripcion + ": " + nombre, false);
      return;
    } catch (error) {
      const codigo = error && error.code;
      if (codigo === "declined") { avisar("Descarga cancelada.", false); return; }
      if (codigo === "rate_limited") { avisar("Hay otra descarga en curso; probá de nuevo.", true); return; }
      avisar("No se pudo guardar: " + ((error && error.message) || "error"), true);
      return;
    }
  }
  try {
    const a = document.createElement("a");
    a.download = nombre;
    a.href = URL.createObjectURL(datos instanceof Blob ? datos : new Blob([datos]));
    a.click();
    avisar(descripcion + " exportado.", false);
  } catch (error) {
    avisar("Este visor no permite descargas.", true);
  }
}

/* EXPORTAR UNA IMAGEN
   ---------------------------------------------------------------------
   La imagen no es una captura del grafico chico: es un dibujo propio, a
   1.800 por 1.000, con ejes rotulados, rejilla, marcas de curva y leyenda.

   El grafico de la grilla mide poco mas de cien pixeles de alto y renuncia
   a los ejes a proposito: ahi lo que se lee es la forma. Una imagen que sale
   del tablero se mira sola y sin escala no se puede leer ---no hay contra
   que comparar la altura de un pico---, de modo que necesita lo contrario:
   valores en el eje vertical, metros en el horizontal, y de quien es cada
   traza. Escalar el chico habria dado un dibujo borroso y sin ejes. */

/* QUE DICE EL PIE DE UN GRAFICO EXPORTADO.
   Una imagen se va de la pantalla y se pega en otro lado; el pie es lo unico
   que viaja con ella. Tiene que decir de que sesion salio, de que vuelta y de
   que vehiculo, porque sin eso la imagen no se puede volver a encontrar en la
   base. Antes decia «valores de muestra», que ademas de inutil ya es falso. */
function pieDeExportacion() {
  const s = estado.abierta;
  if (!s) return "sin sesión abierta";
  const partes = [nombreDeSesion(s), s.session_id];
  if (hayVueltas()) partes.push("vuelta " + vueltaElegida + " de " + vueltasDeLaSesion());
  partes.push("vehículo " + autoPropio().nombre);
  const bloque = estado.series[vueltaElegida];
  if (bloque && bloque.muestras) {
    partes.push(cifra(bloque.muestras, 0) + " puntos" +
                (bloque.submuestreado ? " submuestreados" : ""));
  }
  return partes.join(" · ");
}

const EXPORTA = { ancho: 1800, alto: 1000, izq: 130, der: 60, arriba: 130, abajo: 150 };

function exportarPng(canalId) {
  const ids = [...seleccion];
  if (!ids.length) { avisar("Elegí al menos un vehículo antes de exportar.", true); return; }

  const m = METRICAS.find(x => x.id === canalId);
  if (!m) {
    // Salir en silencio fue exactamente el error que rompio el boton de la
    // vista completa: no volver a hacerlo.
    avisar("No se pudo exportar: canal desconocido (" + canalId + ").", true);
    return;
  }

  const cv = document.createElement("canvas");
  cv.width = EXPORTA.ancho;
  cv.height = EXPORTA.alto;
  const ctx = cv.getContext("2d");

  const X0 = EXPORTA.izq, Y0 = EXPORTA.arriba;
  const X1 = EXPORTA.ancho - EXPORTA.der, Y1 = EXPORTA.alto - EXPORTA.abajo;
  const ancho = X1 - X0, alto = Y1 - Y0;

  ctx.fillStyle = tinta("--superficie");
  ctx.fillRect(0, 0, cv.width, cv.height);

  // --- encabezado ---
  ctx.fillStyle = tinta("--texto");
  ctx.font = "700 40px 'Saira Condensed', sans-serif";
  ctx.fillText(m.rotulo.toUpperCase(), X0, 62);
  ctx.fillStyle = tinta("--texto-tenue");
  ctx.font = "20px 'IBM Plex Mono', monospace";
  ctx.fillText(
    nombreDeSesion(estado.abierta || {}) + " · vuelta " + vueltaElegida + " · " +
    FUENTES[fuente].nombre + " · " + fechaAr(new Date()),
    X0, 95);

  // --- datos ---
  // La vuelta que se esta mirando: cada una tiene su propia traza.
  const series = ids.map(id => serieVelocidad(id, vueltaElegida));
  const total = series[0].length;
  const desde = ampliado ? Math.floor(total * 0.34) : 0;
  const hasta = ampliado ? Math.floor(total * 0.58) : total;
  const bin = fuente === "can";
  let datos = series.map((s, si) => derivar(null, canalId, vueltaElegida, ids[si]).slice(desde, hasta));
  if (bin && (canalId === "throttle" || canalId === "brake")) {
    datos = datos.map(d => d.map(p => [p[0], p[1] > 40 ? 1 : 0]));
  }
  let mn = Infinity, mx = -Infinity;
  datos.forEach(d => d.forEach(p => { if (p[1] < mn) mn = p[1]; if (p[1] > mx) mx = p[1]; }));
  if (mx - mn < 1e-6) mx = mn + 1;
  const pad = (mx - mn) * 0.08; mn -= pad; mx += pad;
  const d0 = datos[0][0][0], d1 = datos[0][datos[0].length - 1][0];
  const dec = ["glong", "glat", "gvert", "gap", "slip", "steer"].indexOf(canalId) !== -1 ? 2 : 0;

  // --- rejilla y eje vertical ---
  ctx.strokeStyle = tinta("--linea");
  ctx.lineWidth = 1.4;
  ctx.font = "20px 'IBM Plex Mono', monospace";
  ctx.textAlign = "right";
  for (let i = 0; i <= 5; i++) {
    const y = Y1 - (alto * i) / 5;
    ctx.beginPath(); ctx.moveTo(X0, y); ctx.lineTo(X1, y); ctx.stroke();
    ctx.fillStyle = tinta("--texto-medio");
    ctx.fillText((mn + ((mx - mn) * i) / 5).toFixed(dec), X0 - 14, y + 7);
  }

  // --- eje horizontal, en metros ---
  ctx.textAlign = "center";
  for (let i = 0; i <= 8; i++) {
    const x = X0 + (ancho * i) / 8;
    ctx.strokeStyle = tinta("--linea");
    ctx.beginPath(); ctx.moveTo(x, Y0); ctx.lineTo(x, Y1); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(x, Y1); ctx.lineTo(x, Y1 + 10); ctx.stroke();
    ctx.fillStyle = tinta("--texto-medio");
    ctx.fillText(Math.round(d0 + ((d1 - d0) * i) / 8).toLocaleString("es-AR"), x, Y1 + 36);
  }

  ctx.strokeStyle = tinta("--linea-fuerte");
  ctx.lineWidth = 2;
  ctx.strokeRect(X0, Y0, ancho, alto);

  // --- rotulos de los ejes ---
  ctx.fillStyle = tinta("--texto-medio");
  ctx.font = "600 22px 'Saira Condensed', sans-serif";
  ctx.textAlign = "center";
  ctx.fillText("DISTANCIA RECORRIDA · METROS", X0 + ancho / 2, Y1 + 74);
  ctx.save();
  ctx.translate(38, Y0 + alto / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText((m.rotulo + " · " + m.unidad).toUpperCase(), 0, 0);
  ctx.restore();

  // --- curvas del circuito ---
  if (fuente === "f1" && (PISTA.curvas || []).length) {
    ctx.font = "17px 'IBM Plex Mono', monospace";
    const puestas = [];
    PISTA.curvas.forEach(cu => {
      if (cu.metro < d0 || cu.metro > d1) return;
      if (puestas.indexOf(cu.nombre) !== -1) return;
      puestas.push(cu.nombre);
      const x = X0 + ((cu.metro - d0) / (d1 - d0)) * ancho;
      ctx.strokeStyle = tinta("--linea-fuerte");
      ctx.setLineDash([5, 6]); ctx.globalAlpha = .5; ctx.lineWidth = 1.4;
      ctx.beginPath(); ctx.moveTo(x, Y0); ctx.lineTo(x, Y1); ctx.stroke();
      ctx.setLineDash([]); ctx.globalAlpha = 1;
      ctx.save();
      ctx.translate(x - 7, Y0 + 12);
      ctx.rotate(Math.PI / 2);
      ctx.fillStyle = tinta("--texto-tenue");
      ctx.textAlign = "left";
      ctx.fillText(cu.nombre, 0, 0);
      ctx.restore();
    });
  }

  // --- trazas ---
  const paleta = ["--auto-1", "--auto-2", "--auto-3", "--auto-4"];
  datos.forEach((d, ai) => {
    ctx.beginPath();
    d.forEach((p, i) => {
      const x = X0 + (i / (d.length - 1)) * ancho;
      const y = Y1 - ((p[1] - mn) / (mx - mn)) * alto;
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.strokeStyle = tinta(paleta[ai % 4]);
    ctx.lineWidth = 2.6;
    ctx.lineJoin = "round";
    ctx.stroke();
  });

  // --- leyenda ---
  let lx = X0;
  const ly = EXPORTA.alto - 42;
  ctx.textAlign = "left";
  ids.forEach((id, i) => {
    const a = AUTOS.find(v => v.id === id) || AUTOS[0];
    ctx.fillStyle = tinta(paleta[i % 4]);
    ctx.fillRect(lx, ly - 12, 34, 6);
    ctx.fillStyle = tinta("--texto");
    ctx.font = "600 22px 'IBM Plex Sans', sans-serif";
    ctx.fillText(a.nombre, lx + 46, ly);
    const w1 = ctx.measureText(a.nombre).width;
    ctx.fillStyle = tinta("--texto-tenue");
    ctx.font = "19px 'IBM Plex Sans', sans-serif";
    ctx.fillText(a.equipo, lx + 56 + w1, ly);
    lx += 46 + w1 + 10 + ctx.measureText(a.equipo).width + 44;
  });

  ctx.fillStyle = tinta("--texto-tenue");
  ctx.font = "17px 'IBM Plex Sans', sans-serif";
  ctx.textAlign = "right";
  ctx.fillText(pieDeExportacion(), X1, ly);

  cv.toBlob(blob => {
    if (!blob) { avisar("No se pudo generar la imagen.", true); return; }
    guardar("traza-" + canalId + ".png", blob, "Gráfico guardado");
  }, "image/png");
}

/* EXPORTAR LA VISTA A PANTALLA COMPLETA
   ---------------------------------------------------------------------
   El boton llamaba a `exportarPng("detalle")`, y esa funcion busca el canal
   en el catalogo de metricas: "detalle" no es un canal, no lo encontraba y
   **salia sin hacer nada ni decir nada**. Un boton que falla en silencio es
   peor que uno que no existe.

   Y ademas la vista completa no muestra un canal sino varios apilados sobre
   el mismo eje, de modo que exportar uno solo tampoco habria sido lo que se
   estaba mirando. Esta funcion dibuja lo que hay en pantalla: un panel por
   metrica activa, alineados, con un unico eje de distancia abajo. */
function exportarComparacion() {
  const ids = [...seleccion];
  const activas = METRICAS.filter(m => m.activa && m.fuentes.indexOf(fuente) !== -1);
  if (!ids.length) { avisar("Elegí al menos un vehículo antes de exportar.", true); return; }
  if (!activas.length) { avisar("Encendé al menos una métrica antes de exportar.", true); return; }

  const IZQ = 150, DER = 60, ARRIBA = 140, ABAJO = 160;
  const ALTO_PANEL = 190;
  const ancho = 1800 - IZQ - DER;
  const cv = document.createElement("canvas");
  cv.width = 1800;
  cv.height = ARRIBA + ALTO_PANEL * activas.length + ABAJO;
  const ctx = cv.getContext("2d");

  ctx.fillStyle = tinta("--superficie");
  ctx.fillRect(0, 0, cv.width, cv.height);

  ctx.fillStyle = tinta("--texto");
  ctx.font = "700 42px 'Saira Condensed', sans-serif";
  ctx.fillText(modoDetalle ? "TODAS LAS SEÑALES" : "COMPARACIÓN POR DISTANCIA", IZQ, 62);
  ctx.fillStyle = tinta("--texto-tenue");
  ctx.font = "20px 'IBM Plex Mono', monospace";
  ctx.fillText(
    nombreDeSesion(estado.abierta || {}) + " · vuelta " + vueltaElegida + " · " +
    FUENTES[fuente].nombre + " · " + activas.length + " métricas · " + fechaAr(new Date()),
    IZQ, 98);

  // La vuelta que se esta mirando: cada una tiene su propia traza.
  const series = ids.map(id => serieVelocidad(id, vueltaElegida));
  const total = series[0].length;
  const desde = zoom ? Math.floor(zoom[0] * total) : 0;
  const hasta = zoom ? Math.ceil(zoom[1] * total) : total;
  const bin = fuente === "can";
  const paleta = ["--auto-1", "--auto-2", "--auto-3", "--auto-4"];
  const d0 = series[0][desde][0];
  const d1 = series[0][Math.min(hasta, total) - 1][0];

  activas.forEach((m, pi) => {
    const Y0 = ARRIBA + pi * ALTO_PANEL;
    const Y1 = Y0 + ALTO_PANEL - 34;
    const alto = Y1 - Y0;

    let datos = series.map((s, si) => derivar(null, m.id, vueltaElegida, ids[si]).slice(desde, hasta));
    if (bin && (m.id === "throttle" || m.id === "brake")) {
      datos = datos.map(d => d.map(p => [p[0], p[1] > 40 ? 1 : 0]));
    }
    let mn = Infinity, mx = -Infinity;
    datos.forEach(d => d.forEach(p => { if (p[1] < mn) mn = p[1]; if (p[1] > mx) mx = p[1]; }));
    if (mx - mn < 1e-6) mx = mn + 1;
    const pad = (mx - mn) * 0.08; mn -= pad; mx += pad;
    const dec = ["glong", "glat", "gvert", "gap", "slip", "steer"].indexOf(m.id) !== -1 ? 2 : 0;

    ctx.strokeStyle = tinta("--linea");
    ctx.lineWidth = 1.2;
    for (let i = 0; i <= 3; i++) {
      const y = Y1 - (alto * i) / 3;
      ctx.beginPath(); ctx.moveTo(IZQ, y); ctx.lineTo(IZQ + ancho, y); ctx.stroke();
    }
    ctx.strokeStyle = tinta("--linea-fuerte");
    ctx.lineWidth = 1.6;
    ctx.strokeRect(IZQ, Y0, ancho, alto);

    ctx.fillStyle = tinta("--texto-medio");
    ctx.font = "600 19px 'Saira Condensed', sans-serif";
    ctx.save();
    ctx.translate(46, (Y0 + Y1) / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = "center";
    ctx.fillText((m.rotulo + " · " + m.unidad).toUpperCase(), 0, 0);
    ctx.restore();

    ctx.font = "18px 'IBM Plex Mono', monospace";
    ctx.fillStyle = tinta("--texto-tenue");
    ctx.textAlign = "right";
    ctx.fillText(mx.toFixed(dec), IZQ - 14, Y0 + 18);
    ctx.fillText(mn.toFixed(dec), IZQ - 14, Y1 - 4);
    ctx.textAlign = "left";

    // Las curvas se dibujan en todos los paneles: un mismo metro se sigue
    // de arriba abajo, que es la razon de apilarlos.
    if (fuente === "f1" && (PISTA.curvas || []).length) {
      ctx.strokeStyle = tinta("--linea-fuerte");
      ctx.setLineDash([5, 6]); ctx.globalAlpha = .42; ctx.lineWidth = 1.3;
      PISTA.curvas.forEach(cu => {
        if (cu.metro < d0 || cu.metro > d1) return;
        const x = IZQ + ((cu.metro - d0) / (d1 - d0)) * ancho;
        ctx.beginPath(); ctx.moveTo(x, Y0); ctx.lineTo(x, Y1); ctx.stroke();
      });
      ctx.setLineDash([]); ctx.globalAlpha = 1;
    }

    datos.forEach((d, ai) => {
      ctx.beginPath();
      d.forEach((p, i) => {
        const x = IZQ + (i / (d.length - 1)) * ancho;
        const y = Y1 - ((p[1] - mn) / (mx - mn)) * alto;
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      });
      ctx.strokeStyle = tinta(paleta[ai % 4]);
      ctx.lineWidth = 2.2;
      ctx.lineJoin = "round";
      ctx.stroke();
    });
  });

  // Un solo eje de distancia, debajo del ultimo panel, con los nombres de curva.
  const yEje = ARRIBA + ALTO_PANEL * activas.length - 30;
  ctx.textAlign = "center";
  ctx.font = "18px 'IBM Plex Mono', monospace";
  for (let i = 0; i <= 8; i++) {
    const x = IZQ + (ancho * i) / 8;
    ctx.fillStyle = tinta("--texto-medio");
    ctx.fillText(Math.round(d0 + ((d1 - d0) * i) / 8).toLocaleString("es-AR"), x, yEje + 8);
  }
  ctx.fillStyle = tinta("--texto-medio");
  ctx.font = "600 21px 'Saira Condensed', sans-serif";
  ctx.fillText("DISTANCIA RECORRIDA · METROS", IZQ + ancho / 2, yEje + 42);

  if (fuente === "f1") {
    ctx.font = "16px 'IBM Plex Mono', monospace";
    const puestas = [];
    (PISTA.curvas || []).forEach(cu => {
      if (cu.metro < d0 || cu.metro > d1) return;
      if (puestas.indexOf(cu.nombre) !== -1) return;
      puestas.push(cu.nombre);
      const x = IZQ + ((cu.metro - d0) / (d1 - d0)) * ancho;
      ctx.save();
      ctx.translate(x - 6, ARRIBA + 14);
      ctx.rotate(Math.PI / 2);
      ctx.fillStyle = tinta("--texto-tenue");
      ctx.textAlign = "left";
      ctx.fillText(cu.nombre, 0, 0);
      ctx.restore();
    });
  }

  let lx = IZQ;
  const ly = cv.height - 46;
  ctx.textAlign = "left";
  ids.forEach((id, i) => {
    const a = AUTOS.find(v => v.id === id) || AUTOS[0];
    ctx.fillStyle = tinta(paleta[i % 4]);
    ctx.fillRect(lx, ly - 12, 34, 6);
    ctx.fillStyle = tinta("--texto");
    ctx.font = "600 22px 'IBM Plex Sans', sans-serif";
    ctx.fillText(a.nombre, lx + 46, ly);
    const w1 = ctx.measureText(a.nombre).width;
    ctx.fillStyle = tinta("--texto-tenue");
    ctx.font = "19px 'IBM Plex Sans', sans-serif";
    ctx.fillText(a.equipo, lx + 56 + w1, ly);
    lx += 46 + w1 + 10 + ctx.measureText(a.equipo).width + 44;
  });

  ctx.fillStyle = tinta("--texto-tenue");
  ctx.font = "17px 'IBM Plex Sans', sans-serif";
  ctx.textAlign = "right";
  ctx.fillText(pieDeExportacion(), IZQ + ancho, ly);

  cv.toBlob(blob => {
    if (!blob) { avisar("No se pudo generar la imagen.", true); return; }
    guardar((modoDetalle ? "senales" : "comparacion") + "-vuelta-" + vueltaElegida + ".png",
            blob, "Imagen guardada");
  }, "image/png");
}

function exportarCsv() {
  const ids = [...seleccion];
  const canales = canalesDeLaFuente().filter(id => elegidos()[id]);
  // La vuelta que se esta mirando: cada una tiene su propia traza.
  const series = ids.map(id => serieVelocidad(id, vueltaElegida));
  const cab = ["distancia_m"];
  ids.forEach(id => {
    const a = AUTOS.find(x => x.id === id) || AUTOS[0];
    canales.forEach(c => cab.push(a.nombre + "_" + nombreDeSenal(c)));
  });
  const columnas = [];
  ids.forEach((id, ai) => canales.forEach(c => columnas.push(derivar(null, c, vueltaElegida, ids[ai]))));
  const filas = [cab.join(",")];
  for (let i = 0; i < series[0].length; i++) {
    const fila = [series[0][i][0]];
    columnas.forEach(col => fila.push(col[i][1].toFixed(3)));
    filas.push(fila.join(","));
  }
  guardar("traza-vuelta.csv", filas.join("\n"), "Datos guardados");
}

/* Un grafico chico por canal, como celda de la misma grilla que el resto.
   Se crean una sola vez por combinacion de fuente y canales activos, y se
   redibujan sin rehacer el DOM. */
const LIENZOS = {};

function asegurarGraficosChicos(ids) {
  /* Todos los graficos en la misma linea, a lo ancho de la pantalla. */
  const linea = document.getElementById("graficos-cabina");
  const unico = document.getElementById("tablero");
  if (!linea && !unico) return;
  const previos = Object.keys(LIENZOS);
  const iguales = previos.length === ids.length && ids.every(id => LIENZOS[id]);
  if (iguales) return;

  previos.forEach(id => {
    const celda = document.getElementById("celda-" + id);
    if (celda) celda.remove();
    delete LIENZOS[id];
  });

  ids.forEach(id => {
    const tablero = linea || unico;
    const m = METRICAS.find(x => x.id === id);
    if (!m) return;
    const s = document.createElement("section");
    s.className = "instrumento celda-1 grafico-chico";
    s.id = "celda-" + id;
    s.innerHTML =
      '<header><h2>' + m.rotulo + '</h2>' +
      '<span class="fuente-canal" title="Canal: ' + nombreDeSenal(id) + '"></span>' +
      '<span class="acciones-grafico">' +
        '<button class="boton-icono" type="button" data-ampliar="' + id + '" ' +
                'title="Ampliar este gráfico" aria-label="Ampliar ' + m.rotulo + '">' +
          '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" ' +
               'stroke-linecap="round" stroke-linejoin="round">' +
            '<path d="M9.5 2 h4.5 v4.5 M6.5 14 H2 V9.5 M14 2 L9 7 M2 14 L7 9"></path>' +
          '</svg>' +
        '</button>' +
        '<button class="boton-icono" type="button" data-exportar="' + id + '" ' +
                'title="Exportar este gráfico como imagen" aria-label="Exportar ' + m.rotulo + '">' +
          '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" ' +
               'stroke-linecap="round" stroke-linejoin="round">' +
            '<path d="M8 1.5 v8 M4.5 6 L8 9.5 L11.5 6 M2.5 12.5 h11"></path>' +
          '</svg>' +
        '</button>' +
      '</span></header>' +
      '<div class="cuerpo-instrumento">' +
        // El cabezal es un elemento aparte, encima del lienzo: moverlo cuesta
        // una propiedad, mientras que dibujarlo dentro obligaba a repintar la
        // traza entera ---dos mil seiscientos puntos por grafico--- en cada
        // cuadro de la reproduccion.
        '<div class="lienzo-envoltura">' +
          '<canvas id="lienzo-' + id + '" role="img" aria-label="' + m.rotulo + ' a lo largo de la vuelta"></canvas>' +
          '<i class="cabezal-grafico" id="cabezal-' + id + '" aria-hidden="true"></i>' +
        '</div>' +
        '<div class="pie-grafico" id="pie-' + id + '"></div>' +
      '</div>';
    tablero.appendChild(s);
    LIENZOS[id] = s.querySelector("canvas");
    const btn = s.querySelector("[data-exportar]");
    if (btn) btn.addEventListener("click", () => exportarPng(id));
    const amp = s.querySelector("[data-ampliar]");
    if (amp) amp.addEventListener("click", () => ampliarGrafico(id));
  });
}

function dibujarTraza() {
  const activos = canalesDibujados();
  asegurarGraficosChicos(activos);
  if (estadoSesion === "vacio") return;
  /* Mientras la vuelta viaja no hay nada que trazar. No es un error: es el
     segundo que tarda la consulta. La pregunta correcta es si **llego el
     bloque de esa vuelta**, no si tiene velocidad: una fuente puede traer
     acelerador y no velocidad, y preguntando por una sola señal el tablero
     se quedaba diciendo «sin dato» con los datos ya en la mano. */
  if (!estado.series[vueltaElegida]) { pintarEsperando(); return; }

  /* Sin seleccion no hay a quien graficar, y `series[0]` reventaba dentro de
     una promesa cuyo `.catch` se traga el error: los graficos quedaban en
     blanco sin decir nada en la consola. Si no hay nadie elegido se grafica el
     propio, que es de quien siempre hay serie. */
  const ids = seleccion.size ? [...seleccion] : [claveVehiculoPropio()].filter(Boolean);
  if (!ids.length) { pintarEsperando(); return; }
  const paleta = ["--auto-1", "--auto-2", "--auto-3", "--auto-4"];
  // La vuelta que se esta mirando: cada una tiene su propia traza.
  const series = ids.map(id => serieVelocidad(id, vueltaElegida));
  const total = series[0].length;
  const desde = ampliado ? Math.floor(total * 0.34) : 0;
  const hasta = ampliado ? Math.floor(total * 0.58) : total;
  const bin = fuente === "can";

  activos.forEach(canal => {
    const cv = LIENZOS[canal];
    if (!cv) return;
    const m = METRICAS.find(x => x.id === canal);
    const ctx = cv.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const w = cv.clientWidth || 240, h = cv.clientHeight || 104;
    cv.width = w * dpr; cv.height = h * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    let datos = series.map((s, si) => derivar(null, canal, vueltaElegida, ids[si]).slice(desde, hasta));
    if (bin && (canal === "throttle" || canal === "brake")) {
      datos = datos.map(d => d.map(p => [p[0], p[1] > 40 ? 1 : 0]));
    }
    let mn = Infinity, mx = -Infinity;
    datos.forEach(d => d.forEach(p => { if (p[1] < mn) mn = p[1]; if (p[1] > mx) mx = p[1]; }));
    if (mx - mn < 1e-6) mx = mn + 1;
    const pad = (mx - mn) * 0.1; mn -= pad; mx += pad;

    // rejilla
    ctx.strokeStyle = tinta("--linea"); ctx.lineWidth = 1;
    for (let i = 0; i <= 2; i++) {
      const y = 4 + (h - 8) * (i / 2);
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
    }

    // Las curvas que caen dentro de la ventana, en su metro.
    if (CURVAS.length) {
      const ti = instante();
      const vF = ventanaTraza ? ti.metro : (datos[0].length ? datos[0][datos[0].length - 1][0] : 1);
      const vI = ventanaTraza ? Math.max(0, ti.metro - ventanaTraza) : 0;
      const an = Math.max(1, vF - vI);
      ctx.strokeStyle = tinta("--linea-fuerte");
      ctx.globalAlpha = .35; ctx.setLineDash([2, 3]);
      CURVAS.forEach(cu => {
        if (cu.metro_medido < vI || cu.metro_medido > vF) return;
        const x = ((cu.metro_medido - vI) / an) * w;
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
      });
      ctx.setLineDash([]); ctx.globalAlpha = 1;
    }

    /* UNA VENTANA QUE SE DESPLAZA, NO UNA VUELTA QUE SE ESCRIBE.
       Escribir la vuelta entera dejaba el trazo cada vez mas apretado a medida
       que avanzaba: los ultimos metros entraban en pixeles. Un instrumento en
       marcha muestra **los ultimos tantos metros** y los va corriendo, de modo
       que el detalle es el mismo al principio y al final.

       `ventanaTraza` dice cuantos metros entran. En cero entra la vuelta
       completa, que sigue siendo lo que se quiere para leerla despues.

       La escala vertical, en cambio, es siempre la de la vuelta entera: si se
       ajustara a lo que entra en la ventana, el trazo saltaria de sitio en cada
       frenada al cambiar el maximo, y dos momentos dejarian de ser
       comparables entre si. */
    const t = instante();
    const metroAhora = t.metro;
    // Los dos extremos de lo que se ve. Con ventana, los ultimos N metros
    // recorridos; sin ventana, la vuelta entera.
    const vFin = ventanaTraza ? metroAhora : (datos[0].length ? datos[0][datos[0].length - 1][0] : 1);
    const vIni = ventanaTraza ? Math.max(0, metroAhora - ventanaTraza) : 0;
    const anchoV = Math.max(1, vFin - vIni);
    const enX = m => ((m - vIni) / anchoV) * w;

    datos.forEach((d, ai) => {
      ctx.beginPath();
      let primero = true;
      for (let i = 0; i < d.length; i++) {
        if (d[i][0] < vIni || d[i][0] > vFin) continue;
        const x = enX(d[i][0]);
        const y = (h - 6) - ((d[i][1] - mn) / (mx - mn)) * (h - 12) + 3;
        primero ? (ctx.moveTo(x, y), primero = false) : ctx.lineTo(x, y);
      }
      ctx.strokeStyle = tinta(paleta[ai % 4]);
      ctx.lineWidth = ids.length > 2 ? 1.2 : 1.7;
      ctx.lineJoin = "round";
      ctx.stroke();
    });

    const dec = (canal === "glong" || canal === "glat" || canal === "gvert" ||
                 canal === "gap" || canal === "slip" || canal === "steer") ? 2 : 0;
    const pie = document.getElementById("pie-" + canal);
    if (pie) {
      pie.innerHTML =
        '<span>mín <b>' + (mn + pad).toFixed(dec) + '</b></span>' +
        '<span>' + m.unidad + '</span>' +
        '<span>máx <b>' + (mx - pad).toFixed(dec) + '</b></span>';
    }
  });
}

/* Mientras la vuelta viaja, cada grafico dice que esta esperando en vez de
   quedarse en blanco: en blanco no se distingue de «esta fuente no tiene esta
   señal», que es una afirmacion muy distinta. */
function pintarEsperando() {
  Object.keys(LIENZOS).forEach(id => {
    const cv = LIENZOS[id];
    if (!cv) return;
    const ctx = cv.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const w = cv.clientWidth || 240, h = cv.clientHeight || 104;
    cv.width = w * dpr; cv.height = h * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = tinta("--texto-tenue");
    ctx.font = "11px 'IBM Plex Sans', sans-serif";
    ctx.fillText(estado.cargando ? "cargando…" : "sin dato en esta vuelta", 10, h / 2);
    const pie = document.getElementById("pie-" + id);
    if (pie) pie.innerHTML = "<span>—</span><span></span><span>—</span>";
  });
}

/* Lo unico que cambia de un cuadro al siguiente en los graficos. */
function moverCabezalesGraficos() {
  // Con ventana, el instante esta siempre al borde derecho ---es lo ultimo que
  // paso---. Sin ventana, en el punto de la vuelta que le toca.
  const pct = ventanaTraza ? 100
    : (estadoSesion === "vacio" ? 0 : instante().fraccion) * 100;
  const visible = estadoSesion !== "vacio";
  Object.keys(LIENZOS).forEach(id => {
    const c = document.getElementById("cabezal-" + id);
    if (!c) return;
    c.style.left = pct.toFixed(3) + "%";
    c.style.display = visible ? "" : "none";
  });
}

function pintarLeyendaTraza() {
  const paleta = ["var(--auto-1)", "var(--auto-2)", "var(--auto-3)", "var(--auto-4)"];
  const nombres = [...seleccion]
    .map(id => AUTOS.find(a => a.id === id))
    .filter(Boolean).map(a => a.nombre);
  const leyenda = document.getElementById("leyenda-traza");
  if (leyenda) leyenda.innerHTML =
    nombres.map((n, i) => '<span><i style="background:' + paleta[i % 4] + '"></i>' + n + '</span>').join("");
  const bin = fuente === "can";
  const notaT = document.getElementById("nota-traza");
  if (notaT) notaT.textContent = bin
    ? "En esta fuente el acelerador y el freno son binarios: gas_pressed y brake_pressed declaran pisado o no pisado, no cuánto."
    : "Cada señal encendida abre su propio gráfico, y cada gráfico se escribe a medida que avanza la vuelta: lo dibujado es lo que ya ocurrió. La escala vertical es la de la vuelta completa, para que un mismo alto signifique lo mismo al principio y al final. Todos van contra la distancia de la vuelta y comparten la marca del cabezal y las líneas de puntos de las curvas, de modo que un mismo metro se busca en cualquiera de ellos. Cuántas se pueden encender lo decide la fuente: la simulación publica diecinueve graficables, el bus del vehículo diez.";
  contarCanales();
}

/* ============================================================
   COMPARACIÓN A PANTALLA COMPLETA
   ============================================================ */
const compAbierta = () => document.getElementById("velo-comparacion").dataset.abierto === "si";

/* El panel a pantalla completa sirve a dos usos con la misma maquinaria:
   comparar varios pilotos, o mirar uno solo con todas sus senales. Lo unico
   que cambia es cuantos vehiculos entran y que metricas vienen encendidas;
   los ejes, el zoom, el selector de vuelta y las marcas de curva son los
   mismos. Escribir dos vistas separadas habria sido duplicar. */
let modoDetalle = false;

function abrirComparacion() {
  modoDetalle = false;
  if (seleccion.size < 2) seleccion = new Set(AUTOS.slice(0, 2).map(a => a.id));
  if (fuente !== "f1" || seleccion.size < 2) {
    avisar("Esta comparación requiere al menos dos vehículos F1 25 con distancia medida.", true);
    return;
  }
  document.getElementById("velo-comparacion").dataset.abierto = "si";
  document.querySelector("#velo-comparacion .cab-comparacion h3").firstChild.textContent = "Comparación por distancia";
  pintarMetricas(); pintarPilotosComparacion(); dibujarComparacion();
  document.getElementById("btn-cerrar-comparacion").focus();
}

/* AMPLIAR UN GRAFICO.
   Reusa el panel a pantalla completa que ya existe para la comparacion: el
   mismo lienzo, el mismo zoom por arrastre, las mismas marcas de curva y el
   mismo cabezal. Lo unico que cambia es que viene una sola metrica encendida.
   Escribir un visor aparte habria sido tener dos graficos distintos para el
   mismo dato. */
function ampliarGrafico(id) {
  const m = METRICAS.find(x => x.id === id);
  if (!m) { avisar("Ese canal no tiene panel ampliado", true); return; }
  modoDetalle = true;
  if (!seleccion.size) seleccion = new Set([autoPropio().id]);
  METRICAS.forEach(x => { x.activa = (x.id === id); });
  zoom = null;
  document.getElementById("velo-comparacion").dataset.abierto = "si";
  document.querySelector("#velo-comparacion .cab-comparacion h3").firstChild.textContent =
    m.rotulo + " · " + m.unidad;
  pintarMetricas(); pintarPilotosComparacion(); dibujarComparacion();
  document.getElementById("btn-cerrar-comparacion").focus();
}

function abrirDetalle() {
  modoDetalle = true;
  // Un solo vehiculo: el propio, que es del unico que hay telemetria privada.
  const propio = AUTOS.find(a => a.propio) || AUTOS[0];
  seleccion = new Set([propio.id]);
  // En detalle vienen encendidas todas las senales que la fuente tenga.
  METRICAS.forEach(m => { m.activa = m.fuentes.indexOf(fuente) !== -1; });
  document.getElementById("velo-comparacion").dataset.abierto = "si";
  document.querySelector("#velo-comparacion .cab-comparacion h3").firstChild.textContent = "Todas las señales";
  pintarMetricas(); pintarPilotosComparacion(); dibujarComparacion();
  document.getElementById("btn-cerrar-comparacion").focus();
}
document.getElementById("btn-cerrar-comparacion").addEventListener("click", () => {
  document.getElementById("velo-comparacion").dataset.abierto = "no";
});
document.addEventListener("keydown", e => {
  if (e.key === "Escape") {
    document.getElementById("velo-comparacion").dataset.abierto = "no";
    const s = document.getElementById("velo-sesiones");
    if (s) s.dataset.abierto = "no";
    cerrarModal();
  }
});
document.getElementById("sel-eje").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  ejeComparacion = b.dataset.eje; marcar(e.currentTarget, "eje", ejeComparacion); dibujarComparacion();
});
/* Las vueltas que ofrece el selector son las que la sesion tiene: ofrecer
   cincuenta y ocho sobre una sesion de cinco era prometer datos que no
   existen. Y elegir una vuelta **mueve el cabezal** a su comienzo, porque no
   puede haber dos posiciones distintas dentro de la misma sesion. */
function poblarVueltas() {
  const s = document.getElementById("sel-vuelta-numero");
  if (!s) return;
  const numeros = estado.vueltas.map(v => v.numero).filter(Number.isFinite);
  if (!numeros.length) numeros.push(1);
  if (numeros.indexOf(vueltaElegida) === -1) vueltaElegida = numeros[0];
  s.innerHTML = "";
  numeros.forEach(i => {
    const o = document.createElement("option");
    o.value = String(i);
    o.textContent = hayVueltas() ? "Vuelta " + i : "Tramo completo";
    if (i === vueltaElegida) o.selected = true;
    s.appendChild(o);
  });
  s.disabled = numeros.length <= 1 || alcanceComparacion === "carrera";
}

(function mandosDeVuelta() {
  const s = document.getElementById("sel-vuelta-numero");
  if (!s) return;
  // El poblado se hace al final, cuando SESIONES ya existe.
  s.addEventListener("change", () => {
    const v = parseInt(s.value, 10);
    vueltaElegida = v;
    detener();
    const indice = Math.max(0, estado.vueltas.findIndex(x => x.numero === v));
    moverCabezal(indice / vueltasDeLaSesion());
    zoom = null; pintarPilotosComparacion(); dibujarComparacion();
  });
})();

document.getElementById("sel-vuelta").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  alcanceComparacion = b.dataset.vuelta; marcar(e.currentTarget, "vuelta", alcanceComparacion);
  const selector = document.getElementById("sel-vuelta-numero");
  if (selector) selector.disabled = alcanceComparacion === "carrera" || estado.vueltas.length <= 1;
  zoom = null; asegurarDatosComparacion().then(dibujarComparacion);
});
document.getElementById("btn-reset-zoom").addEventListener("click", () => { zoom = null; dibujarComparacion(); });
document.getElementById("btn-exportar-detalle").addEventListener("click", exportarComparacion);

function pintarMetricas() {
  const c = document.getElementById("metricas-comparacion");
  c.innerHTML = "";
  METRICAS.forEach(m => {
    const disponible = m.fuentes.indexOf(fuente) !== -1 &&
      (estado.disponibles.has(nombreDeSenal(m.id)) || estado.cargando);
    const b = document.createElement("button");
    b.className = "boton-menor"; b.type = "button";
    b.setAttribute("aria-pressed", String(disponible && m.activa));
    b.textContent = m.rotulo;
    if (!disponible) {
      b.disabled = true;
      b.title = MOTIVO_METRICA[fuente] || "No disponible en esta fuente.";
      b.style.opacity = ".45";
      b.style.textDecoration = "line-through";
    } else {
      b.addEventListener("click", () => {
        m.activa = !m.activa;
        if (!METRICAS.some(x => x.activa && x.fuentes.indexOf(fuente) !== -1)) m.activa = true;
        b.setAttribute("aria-pressed", String(m.activa));
        dibujarComparacion();
      });
    }
    c.appendChild(b);
  });
  const hay = METRICAS.filter(m => estado.disponibles.has(nombreDeSenal(m.id))).length;
  const nota = document.createElement("span");
  nota.style.cssText = "margin-left:auto;font-size:.74rem;color:var(--texto-tenue)";
  nota.textContent = hay + " de " + METRICAS.length + " métricas disponibles en " + FUENTES[fuente].nombre;
  c.appendChild(nota);
}

/* Selector de pilotos dentro de la vista a pantalla completa.
   En modo detalle no aparece: esa vista es de un solo vehiculo, y el propio
   es el unico del que hay telemetria privada. */
function pintarEligePilotos() {
  const c = document.getElementById("elige-pilotos");
  if (!c) return;
  const grupo = c.closest(".grupo-control");
  if (modoDetalle || AUTOS.length <= 1) {
    if (grupo) grupo.hidden = true;
    return;
  }
  if (grupo) grupo.hidden = false;
  c.innerHTML = "";
  AUTOS.forEach(a => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = a.nombre;
    if (a.propio) {
      const m = document.createElement("span");
      m.className = "propio-marca";
      m.textContent = " ·";
      m.title = "Vehículo propio: el único con telemetría privada";
      b.appendChild(m);
    }
    const elegido = seleccion.has(a.id);
    b.setAttribute("aria-pressed", String(elegido));
    if (elegido) b.style.background = "var(" + a.tinta + ")";
    b.addEventListener("click", () => {
      if (seleccion.has(a.id)) {
        // Se puede quedar en uno o en ninguno: quedarse con uno es mirarlo
        // solo, y quedarse con ninguno es vaciar la vista para empezar de
        // nuevo. Forzar un minimo obligaba a deseleccionar en cierto orden.
        seleccion.delete(a.id);
      } else if (seleccion.size < 4) {
        seleccion.add(a.id);
      } else {
        avisar("La comparación admite hasta cuatro vehículos.", true);
        return;
      }
      pintarEligePilotos();
      pintarPilotosComparacion();
      dibujarComparacion();
      render();
    });
    c.appendChild(b);
  });
}

function pintarPilotosComparacion() {
  pintarEligePilotos();
  const ids = [...seleccion].slice(0, modoDetalle ? 1 : 4);
  if (!ids.length) {
    document.getElementById("pilotos-comparacion").innerHTML =
      '<span style="color:var(--texto-tenue);font-size:.82rem">Ningún vehículo seleccionado.</span>';
    document.getElementById("sub-comparacion").textContent = nombreDeSesion(estado.abierta || {});
    return;
  }
  document.getElementById("pilotos-comparacion").innerHTML = ids.map((id, i) => {
    const a = AUTOS.find(x => x.id === id);
    if (!a) return "";
    const numeros = vueltasParaComparar();
    const puntos = numeros.reduce((total, numero) => {
      const bloque = estado.series[numero];
      const veh = bloque && bloque.vehiculos && bloque.vehiculos[id];
      return total + (veh && veh.distancia_m ? veh.distancia_m.length : 0);
    }, 0);
    const mejor = puntos ? cifra(puntos, 0) + " puntos" : "sin datos";
    const dif = alcanceComparacion === "una" ? "vuelta " + vueltaElegida : numeros.length + " vueltas consultadas";
    return '<div class="tarjeta-piloto" style="border-left-color:' + a.color + '">' +
      '<div><div class="nom">' + a.nombre + '</div><div class="eq">' + a.equipo + '</div></div>' +
      '<div class="dato">' + mejor + '</div>' +
      '<div class="dato" style="color:var(--texto-tenue)">' + dif + '</div></div>';
  }).join("");
  const cuantas = METRICAS.filter(m => m.activa && m.fuentes.indexOf(fuente) !== -1).length;
  const s = estado.abierta || {};
  const pista = nombreDeSesion(s);
  const vuelta = estado.vueltas.find(v => v.numero === vueltaElegida);
  const cobertura = alcanceComparacion === "una"
    ? "vuelta " + vueltaElegida + (vuelta && vuelta.largo_m ? " · " + cifra(vuelta.largo_m, 1) + " m observados" : "")
    : estado.vueltas.length + " vueltas observadas";
  document.getElementById("sub-comparacion").textContent =
    pista + " · " + cobertura + " · " + cuantas +
    (modoDetalle ? (cuantas === 1 ? " señal" : " señales") : " métricas comparadas");
}

let arrastre = null;

function vueltasParaComparar() {
  return alcanceComparacion === "carrera"
    ? estado.vueltas.map(v => v.numero)
    : [vueltaElegida];
}

function asegurarDatosComparacion() {
  if (fuente !== "f1") return Promise.resolve([]);
  return Promise.all(vueltasParaComparar().map(asegurarVuelta));
}

function segmentosComparacion(metrica, vehiculo) {
  const nombre = nombreDeSenal(metrica);
  const segmentos = [];
  vueltasParaComparar().forEach(numero => {
    const bloque = estado.series[numero];
    const datos = bloque && bloque.vehiculos && bloque.vehiculos[vehiculo];
    if (!datos || !datos[nombre]) return;
    const ys = datos[nombre];
    let xs;
    if (ejeComparacion === "distancia") {
      xs = alcanceComparacion === "carrera" ? datos.distancia_sesion_m : datos.distancia_m;
    } else {
      const marcas = datos.timestamp_utc || [];
      const origen = alcanceComparacion === "carrera"
        ? new Date((estado.abierta || {}).desde || marcas[0]).getTime()
        : new Date(marcas[0]).getTime();
      xs = marcas.map(t => (new Date(t).getTime() - origen) / 1000);
    }
    if (!xs) return;
    const puntos = [];
    for (let i = 0; i < Math.min(xs.length, ys.length); i++) {
      if (xs[i] === null || ys[i] === null || !Number.isFinite(Number(xs[i])) || !Number.isFinite(Number(ys[i]))) continue;
      puntos.push([Number(xs[i]), Number(ys[i])]);
    }
    if (puntos.length) segmentos.push(puntos);
  });
  return segmentos;
}

function dibujarComparacion() {
  const cv = document.getElementById("lienzo-comparacion");
  const ctx = cv.getContext("2d");
  const ids0 = [...seleccion];
  if (!ids0.length) {
    const cv0 = document.getElementById("lienzo-comparacion");
    if (cv0) {
      const c0 = cv0.getContext("2d");
      const dpr0 = window.devicePixelRatio || 1;
      const w0 = cv0.clientWidth, h0 = 200;
      cv0.width = w0 * dpr0; cv0.height = h0 * dpr0; cv0.style.height = h0 + "px";
      c0.setTransform(dpr0, 0, 0, dpr0, 0, 0);
      c0.clearRect(0, 0, w0, h0);
      c0.fillStyle = tinta("--texto-tenue");
      c0.font = "14px 'IBM Plex Sans', sans-serif";
      c0.fillText("Ningún vehículo seleccionado. Elegí al menos uno arriba.", 20, h0 / 2);
    }
    const pieVacio = document.getElementById("nota-comparacion");
    if (pieVacio) pieVacio.textContent = "";
    return;
  }
  if (fuente !== "f1") {
    const w0 = cv.clientWidth, dpr0 = window.devicePixelRatio || 1;
    cv.width = w0 * dpr0; cv.height = 200 * dpr0; cv.style.height = "200px";
    ctx.setTransform(dpr0, 0, 0, dpr0, 0, 0); ctx.clearRect(0, 0, w0, 200);
    ctx.fillStyle = tinta("--texto-tenue"); ctx.font = "14px 'IBM Plex Sans', sans-serif";
    ctx.fillText("Esta vista espacial requiere distancia medida y solo está disponible para F1 25.", 20, 100);
    return;
  }
  const activas = METRICAS.filter(m => m.activa && estado.disponibles.has(nombreDeSenal(m.id)));
  if (!activas.length) return;
  const dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth;
  const altoPanel = Math.max(84, Math.min(150, (window.innerHeight - 260) / activas.length));
  const h = altoPanel * activas.length + 26;
  cv.width = w * dpr; cv.height = h * dpr; cv.style.height = h + "px";
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);

  const margenIzq = 62, margenDer = 12;
  const ancho = w - margenIzq - margenDer;
  const ids = [...seleccion].slice(0, 4);
  const paleta = ["--auto-1", "--auto-2", "--auto-3", "--auto-4"];

  const todos = [];
  activas.forEach(m => ids.forEach(id => segmentosComparacion(m.id, id).forEach(s => todos.push(...s))));
  if (!todos.length) {
    ctx.fillStyle = tinta("--texto-tenue"); ctx.font = "14px 'IBM Plex Sans', sans-serif";
    const faltan = vueltasParaComparar().some(numero => {
      const bloque = estado.series[numero];
      return !bloque || ids.some(id => !bloque.vehiculos[id]);
    });
    ctx.fillText(faltan ? "Cargando datos para los vehículos y el alcance seleccionados…"
                       : "Las métricas elegidas no tienen datos para estos vehículos.", 20, h / 2);
    if (faltan) asegurarDatosComparacion().then(() => { pintarPilotosComparacion(); dibujarComparacion(); });
    return;
  }
  let xMin = Infinity, xMax = -Infinity;
  todos.forEach(p => { if (p[0] < xMin) xMin = p[0]; if (p[0] > xMax) xMax = p[0]; });
  if (zoom) {
    const amplitud = xMax - xMin;
    xMax = xMin + amplitud * zoom[1];
    xMin = xMin + amplitud * zoom[0];
  }

  activas.forEach((m, pi) => {
    const y0 = pi * altoPanel + 6, y1 = y0 + altoPanel - 16;

    // marco y rejilla
    ctx.strokeStyle = tinta("--linea"); ctx.lineWidth = 1;
    ctx.strokeRect(margenIzq, y0, ancho, y1 - y0);
    for (let i = 1; i < 4; i++) {
      const y = y0 + (y1 - y0) * (i / 4);
      ctx.beginPath(); ctx.moveTo(margenIzq, y); ctx.lineTo(margenIzq + ancho, y); ctx.stroke();
    }

    const datos = ids.map(id => segmentosComparacion(m.id, id)
      .map(segmento => segmento.filter(p => p[0] >= xMin && p[0] <= xMax)));
    let mn = Infinity, mx = -Infinity;
    datos.forEach(grupo => grupo.forEach(d => d.forEach(p => { if (p[1] < mn) mn = p[1]; if (p[1] > mx) mx = p[1]; })));
    if (!Number.isFinite(mn) || !Number.isFinite(mx)) return;
    if (mx - mn < 1e-6) { mx = mn + 1; }
    const pad = (mx - mn) * 0.08; mn -= pad; mx += pad;

    // rótulo del eje
    ctx.fillStyle = tinta("--texto-medio");
    ctx.font = "600 10px 'Saira Condensed', sans-serif";
    ctx.save(); ctx.translate(13, (y0 + y1) / 2); ctx.rotate(-Math.PI / 2);
    ctx.textAlign = "center"; ctx.fillText(m.rotulo.toUpperCase() + " · " + m.unidad, 0, 0);
    ctx.restore();
    ctx.font = "9px 'IBM Plex Mono', monospace";
    ctx.fillStyle = tinta("--texto-tenue"); ctx.textAlign = "right";
    ctx.fillText(mx.toFixed(m.id === "glong" || m.id === "gap" ? 1 : 0), margenIzq - 6, y0 + 9);
    ctx.fillText(mn.toFixed(m.id === "glong" || m.id === "gap" ? 1 : 0), margenIzq - 6, y1 - 1);
    ctx.textAlign = "left";

    // curvas
    datos.forEach((grupo, ai) => {
      grupo.forEach(d => {
        ctx.beginPath();
        d.forEach((p, i) => {
          const x = margenIzq + ((p[0] - xMin) / Math.max(1e-9, xMax - xMin)) * ancho;
          const y = y1 - ((p[1] - mn) / (mx - mn)) * (y1 - y0);
          i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        });
        ctx.strokeStyle = tinta(paleta[ai % 4]);
        ctx.lineWidth = 1.6; ctx.stroke();
      });
    });
  });

  const yEje = activas.length * altoPanel + 4;

  /* EL CABEZAL, TAMBIEN ACA.
     Los paneles de comparacion mostraban la vuelta entera, quieta. Mirando
     dos pilotos sobre una vuelta congelada no se puede decir «en este momento
     el otro va medio segundo adelante»: hace falta el momento. La misma linea
     que cruza los graficos chicos cruza estos, en la misma posicion, porque
     leen el mismo cabezal; y sobre cada serie va el punto de ese instante,
     que es lo que permite leer el valor exacto de cada piloto. */
  if (estadoSesion !== "vacio" && alcanceComparacion === "una") {
    const t = instante();
    const valorCabezal = ejeComparacion === "distancia"
      ? t.metro : t.fraccion * (duracionDeVuelta(t.vuelta) || 0);
    if (valorCabezal >= xMin && valorCabezal <= xMax) {
      const xc = margenIzq + ((valorCabezal - xMin) / Math.max(1e-9, xMax - xMin)) * ancho;
      ctx.strokeStyle = tinta("--acento");
      ctx.lineWidth = 1.6;
      ctx.beginPath(); ctx.moveTo(xc, 0); ctx.lineTo(xc, yEje); ctx.stroke();
      if (hayVueltas()) {
        const et = "Vuelta " + t.vuelta + "/" + t.vueltas;
        ctx.font = "600 10px 'Saira Condensed', sans-serif";
        const anchoEt = ctx.measureText(et).width + 12;
        const xEt = Math.min(xc + 2, w - anchoEt);
        ctx.fillStyle = tinta("--acento");
        ctx.fillRect(xEt, 0, anchoEt, 15);
        ctx.fillStyle = tinta("--sobre-acento");
        ctx.fillText(et, xEt + 6, 11);
      }
    }
  }

  // marcas de curva: linea vertical en todos los paneles mas su rotulo
  if (ejeComparacion === "distancia" && alcanceComparacion === "una" && CURVAS.length) {
    const dIni = xMin, dFin = xMax;
    ctx.font = "9px 'IBM Plex Mono', monospace";
    CURVAS.forEach(cv2 => {
      if (cv2.metro < dIni || cv2.metro > dFin) return;
      const x = margenIzq + ((cv2.metro - dIni) / (dFin - dIni)) * ancho;
      ctx.strokeStyle = tinta("--linea-fuerte");
      ctx.setLineDash([3, 3]); ctx.globalAlpha = .5;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, yEje); ctx.stroke();
      ctx.setLineDash([]); ctx.globalAlpha = 1;
      ctx.save(); ctx.translate(x + 3, 12); ctx.rotate(-Math.PI / 2);
      ctx.fillStyle = tinta("--texto-tenue"); ctx.textAlign = "right";
      ctx.fillText(cv2.nombre, 0, 0); ctx.restore();
      ctx.textAlign = "left";
    });
  }

  ctx.fillStyle = tinta("--texto-tenue");
  ctx.font = "9px 'IBM Plex Mono', monospace";
  const d0 = xMin, d1 = xMax;
  for (let i = 0; i <= 6; i++) {
    const x = margenIzq + (ancho * i) / 6;
    const v = d0 + ((d1 - d0) * i) / 6;
    ctx.textAlign = i === 0 ? "left" : i === 6 ? "right" : "center";
    ctx.fillText(ejeComparacion === "distancia" ? Math.round(v) + " m" : v.toFixed(1) + " s", x, yEje + 10);
  }
  ctx.textAlign = "left";

  // franja de zoom en curso
  if (arrastre) {
    ctx.fillStyle = tinta("--acento-veta") || "rgba(34,211,238,.14)";
    ctx.globalAlpha = .35;
    ctx.fillRect(Math.min(arrastre.a, arrastre.b), 0, Math.abs(arrastre.b - arrastre.a), yEje);
    ctx.globalAlpha = 1;
  }

  document.getElementById("nota-comparacion").textContent = zoom
    ? "Zoom activo entre " + cifra(d0, 1) + (ejeComparacion === "distancia" ? " m" : " s") + " y " + cifra(d1, 1) + (ejeComparacion === "distancia" ? " m" : " s") + "."
    : (alcanceComparacion === "carrera" ? "Carrera completa con segmentos separados por vuelta. " : "") +
      (ejeComparacion === "distancia"
        ? "Eje medido por la fuente. Las curvas externas solo se anotan en una vuelta."
        : "Tiempo transcurrido desde el inicio observado " + (alcanceComparacion === "carrera" ? "de la sesión." : "de cada vuelta."));
}

(function habilitarZoom() {
  const cv = document.getElementById("lienzo-comparacion");
  const rel = e => {
    const r = cv.getBoundingClientRect();
    const margenIzq = 62, ancho = r.width - 74;
    return Math.max(0, Math.min(1, (e.clientX - r.left - margenIzq) / ancho));
  };
  cv.addEventListener("pointerdown", e => {
    const r = cv.getBoundingClientRect();
    arrastre = { a: e.clientX - r.left, b: e.clientX - r.left, ra: rel(e) };
    cv.setPointerCapture(e.pointerId);
  });
  cv.addEventListener("pointermove", e => {
    if (!arrastre) return;
    const r = cv.getBoundingClientRect();
    arrastre.b = e.clientX - r.left; arrastre.rb = rel(e);
    dibujarComparacion();
  });
  cv.addEventListener("pointerup", () => {
    if (arrastre && arrastre.rb !== undefined && Math.abs(arrastre.rb - arrastre.ra) > 0.02) {
      const a = Math.min(arrastre.ra, arrastre.rb), b = Math.max(arrastre.ra, arrastre.rb);
      const base = zoom || [0, 1];
      zoom = [base[0] + (base[1] - base[0]) * a, base[0] + (base[1] - base[0]) * b];
    }
    arrastre = null; dibujarComparacion();
  });
})();


/* ============================================================
   SESIONES GUARDADAS
   ------------------------------------------------------------
   POR QUE ESTE PANEL EXISTE. La interfaz solo ofrecia importar una sesion
   nueva. Quien cambiaba de modo, o cerraba el tablero, creia haber perdido lo
   anterior. **Nunca se perdio nada**: el dato queda persistido y el total se
   consulta al catalogo cada vez que se abre la aplicacion.
   Lo que faltaba no era guardar sino **poder encontrar**, y una sesion que no
   se puede encontrar se parece bastante a una que no existe.

   Lo unico que borra dato es «Limpiar sesion», que ejecuta un borrado real y
   por eso pide confirmacion.

   Las sesiones de esta lista son reales: salen del catalogo de la base.
   ============================================================ */

/* El catalogo de sesiones lo trae la API al arrancar. Antes esta lista
   estaba escrita en el archivo: veintiséis sesiones congeladas del dia que
   se armo la maqueta. */
let SESIONES = [];

/* Las tres fuentes se distinguen a simple vista y no solo por el color: cada
   una lleva su etiqueta escrita. Confundirlas es el error mas caro que puede
   cometer quien mira, porque lo que se puede afirmar de cada una es distinto. */
const ETIQUETA_FUENTE = { f1: "F1 25", openf1: "OpenF1", can: "CAN real" };

const FUENTE_CORTA = {
  f1_25_udp_simulation: "f1",
  openf1_historical_replay: "openf1",
  can_real_replay: "can",
  can_simulated: "can",
};

/* El vivo se mantiene separado del historico: una muestra que acaba de llegar
   no se hace pasar por una fila ya consultada a la base. */
const MAX_MUESTRAS_VIVO = 600;
const vivo = {
  eventSource: null,
  sesion: null,
  ultimos: new Map(),
  series: new Map(),
  distancia: new Map(),
  vuelta: new Map(),
  repintado: false,
  silencio: null,
};

function vaciarVivo(sesion) {
  vivo.sesion = sesion || null;
  vivo.ultimos.clear(); vivo.series.clear(); vivo.distancia.clear(); vivo.vuelta.clear();
}

function mapaVivo(contenedor, vehiculo) {
  if (!contenedor.has(vehiculo)) contenedor.set(vehiculo, new Map());
  return contenedor.get(vehiculo);
}

function incorporarTelemetriaViva(m) {
  if (!m || FUENTE_CORTA[m.source_type] !== "f1" || !m.session_id || !m.vehicle_id || !m.signal_name) return;
  if (vivo.sesion !== m.session_id) {
    vaciarVivo(m.session_id);
    fuente = "f1";
    sesionAbierta = m.session_id;
    estado.abierta = SESIONES.find(s => s.session_id === m.session_id) || {
      session_id: m.session_id, fuente: m.source_type, senales: null, vehiculos: 0,
      filas: 0, procedencia: {},
    };
    estado.series = {}; estado.pidiendo = {}; estado.posiciones = {}; estado.pidiendoPos = {};
    estado.disponibles = new Set();
    AUTOS = []; seleccion = new Set(); estado.vehiculoClave = null;
    marcar(document.getElementById("sel-fuente"), "fuente", fuente);
  }

  const ultimo = mapaVivo(vivo.ultimos, m.vehicle_id);
  ultimo.set(m.signal_name, m);
  estado.disponibles.add(m.signal_name);

  if (!AUTOS.some(a => a.id === m.vehicle_id)) {
    const ids = AUTOS.map(a => a.id).concat(m.vehicle_id);
    const propio = estado.vehiculoClave || m.vehicle_id;
    armarAutos(ids);
    AUTOS.forEach(a => { a.propio = a.id === propio; });
    estado.vehiculoClave = propio;
    if (!seleccion.size) seleccion.add(propio);
    if (estado.abierta) estado.abierta.vehiculos = AUTOS.length;
  }

  const numero = Number(m.value);
  if (m.signal_name === "lap_number" && Number.isFinite(numero)) {
    const anterior = vivo.vuelta.get(m.vehicle_id);
    vivo.vuelta.set(m.vehicle_id, numero);
    if (anterior !== undefined && anterior !== numero) vivo.series.delete(m.vehicle_id);
  }
  if (m.signal_name === "lap_distance" && Number.isFinite(numero)) {
    const anterior = vivo.distancia.get(m.vehicle_id);
    if (anterior !== undefined && numero + 20 < anterior) vivo.series.delete(m.vehicle_id);
    vivo.distancia.set(m.vehicle_id, numero);
  }

  const distancia = vivo.distancia.get(m.vehicle_id);
  const valor = typeof m.value === "boolean" ? Number(m.value) : Number(m.value);
  if (Number.isFinite(distancia) && Number.isFinite(valor)) {
    const porSenal = mapaVivo(vivo.series, m.vehicle_id);
    if (!porSenal.has(m.signal_name)) porSenal.set(m.signal_name, []);
    const serie = porSenal.get(m.signal_name);
    serie.push([distancia, valor]);
    if (serie.length > MAX_MUESTRAS_VIVO) serie.splice(0, serie.length - MAX_MUESTRAS_VIVO);
  }

  estadoSesion = "vivo";
  if (vivo.silencio) clearTimeout(vivo.silencio);
  vivo.silencio = setTimeout(() => {
    if (estadoSesion === "vivo") { estadoSesion = estado.abierta ? "cargado" : "vacio"; render(); }
  }, 10000);
  if (!vivo.repintado) {
    vivo.repintado = true;
    requestAnimationFrame(() => {
      vivo.repintado = false;
      _instanteClave = null; _ultimaTraza = 0;
      render();
    });
  }
}

function datoEvento(e) {
  try { return JSON.parse(e.data); } catch (_error) { return null; }
}

function conectarFlujoEnVivo() {
  if (vivo.eventSource || typeof EventSource === "undefined" || fuente !== "f1") return;
  const canal = new EventSource(API + "/live/stream");
  vivo.eventSource = canal;
  canal.addEventListener("estado", e => { const d = datoEvento(e); if (d) { estado.vivo = d; pintarTransporte(); } });
  canal.addEventListener("telemetria", e => incorporarTelemetriaViva(datoEvento(e)));
  canal.addEventListener("latido", e => {
    const d = datoEvento(e);
    if (d) estado.vivo = Object.assign({}, estado.vivo || {}, { mensajes_recibidos: d.recibidos });
    pintarTransporte();
  });
  canal.onopen = () => {
    pedir("/live/recent?limite=100").then(lista => lista.forEach(incorporarTelemetriaViva)).catch(() => {});
  };
  canal.onerror = () => {
    estado.vivo = Object.assign({}, estado.vivo || {}, { motivo: "Flujo interrumpido; reconectando." });
    pintarTransporte();
  };
}

function cerrarFlujoEnVivo() {
  if (vivo.eventSource) vivo.eventSource.close();
  vivo.eventSource = null;
  if (vivo.silencio) clearTimeout(vivo.silencio);
  vivo.silencio = null;
}

let filtroFuente = "todas";
let ordenSesiones = "fecha";
let sesionAbierta = null;

/* La sesion abierta se recuerda en el navegador: al volver, se sigue donde se
   estaba en vez de empezar de cero. Si el almacenamiento no esta disponible,
   la vista funciona igual y simplemente no recuerda. */
function recordarSesion(id) {
  try { window.localStorage.setItem("sesion-abierta", id); } catch (e) { /* sin memoria */ }
}
function sesionRecordada() {
  try { return window.localStorage.getItem("sesion-abierta"); } catch (e) { return null; }
}

const CIRCUITOS = {
  spa: "Spa-Francorchamps", silverstone: "Silverstone", hungaroring: "Hungaroring",
  interlagos: "Interlagos", catalunya: "Barcelona-Catalunya", spielberg: "Red Bull Ring",
  suzuka: "Suzuka", monza: "Monza",
};

/* El nombre sale de la procedencia, que el capturador deriva del paquete de
   sesion. Sin ella, una clasificacion y una carrera se ven iguales: dos
   identificadores con muchas filas. */
function nombreDeSesion(s) {
  const corta = FUENTE_CORTA[s.fuente] || "can";
  const circuito = (s.procedencia && s.procedencia.circuito) || s.circuito;
  if (circuito) return CIRCUITOS[circuito] || circuito;
  if (corta === "can") return "Segmento del bus";
  if (corta === "openf1") return "Sesión OpenF1 " + String(s.session_id).split(":").pop();
  return "Sesión sin procedencia declarada";
}

/* Practica, clasificacion, sprint, carrera y contrarreloj persiguen cosas
   distintas: agruparlas como «sesiones» borra esa diferencia. */
const FAMILIAS = {
  practica: "Práctica", clasificacion: "Clasificación", sprint: "Sprint",
  carrera: "Carrera", contrarreloj: "Contrarreloj", otro: "Otro",
};

function tipoDeSesion(s) {
  const p = s.procedencia;
  if (p && p.tipo_sesion_nombre) return p.tipo_sesion_nombre;
  if (s.tipo) return s.tipo;
  const corta = FUENTE_CORTA[s.fuente] || "can";
  if (corta === "openf1") return "Carrera";
  if (corta === "can") return "Captura de tránsito";
  return "Sin declarar";
}

function duracionDe(s) {
  // La API ya la calcula; si no viniera, se saca de las dos marcas.
  const seg = s.duracion_s !== undefined && s.duracion_s !== null
    ? s.duracion_s
    : (new Date(s.hasta) - new Date(s.desde)) / 1000;
  const min = Math.max(0, Math.round(seg / 60));
  return min >= 60 ? Math.floor(min / 60) + " h " + (min % 60) + " min" : min + " min";
}

/* CUIDADO CON ESTA FECHA.
   En la fuente del bus **es asignada**: el conjunto de datos es anonimo, no
   trae fecha, y la carga le pone una con un parametro. Rotularla «guardada»
   afirmaba algo que no ocurrio, y hacia parecer recien cargado un segmento que
   nadie tocaba hace dias. Se declara cual es cual. */
function esInstanteAsignado(s) {
  return (FUENTE_CORTA[s.fuente] || "can") === "can";
}

function fechaDeSesion(s) {
  if (!s.hasta) return "sin fecha";
  const d = new Date(s.hasta);
  if (isNaN(d)) return String(s.hasta).slice(0, 16);
  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  return dd + "/" + mm + "/" + d.getFullYear() + " · " + hh + ":" + mi;
}

function rotuloDeFecha(s) {
  return esInstanteAsignado(s) ? "instante asignado" : "instante del dato";
}

/* La duracion de una fuente con instante asignado no significa nada: si el
   segmento se cargo dos veces con distinto inicio, la distancia entre la
   primera y la ultima marca son dias. Se dice, en vez de mostrarla como si
   fuera el largo de la grabacion. */
function duracionLegible(s) {
  if (s.procedencia && s.procedencia.duracion_capturada_s) {
    const min = Math.round(s.procedencia.duracion_capturada_s / 60);
    return min >= 60 ? Math.floor(min / 60) + " h " + (min % 60) + " min" : min + " min";
  }
  if (s.duracion_capturada_s) {
    const min = Math.round(s.duracion_capturada_s / 60);
    return min >= 60 ? Math.floor(min / 60) + " h " + (min % 60) + " min" : min + " min";
  }
  const d = duracionDe(s);
  if (esInstanteAsignado(s) && d.indexOf("h") !== -1) return "cargado más de una vez";
  return d;
}

function sesionesFiltradas() {
  const texto = (document.getElementById("busca-sesion").value || "").trim().toLowerCase();
  let lista = SESIONES.filter(s => {
    const corta = FUENTE_CORTA[s.fuente] || "can";
    if (filtroFuente !== "todas" && corta !== filtroFuente) return false;
    if (!texto) return true;
    // Se busca sobre lo que la persona ve y tambien sobre el identificador:
    // quien tiene el identificador a mano no deberia tener que traducirlo.
    const donde = (nombreDeSesion(s) + " " + s.session_id + " " + fechaDeSesion(s) +
                   " " + (s.fuente || "") + " " + (tipoDeSesion(s) || "")).toLowerCase();
    return donde.indexOf(texto) !== -1;
  });
  lista = lista.slice().sort((a, b) => ordenSesiones === "tamano"
    ? b.filas - a.filas
    : (a.hasta < b.hasta ? 1 : -1));
  return lista;
}

function pintarSesiones() {
  const cont = document.getElementById("tabla-sesiones");
  if (!cont) return;
  const lista = sesionesFiltradas();

  document.getElementById("sub-sesiones").textContent =
    lista.length + " de " + SESIONES.length + " sesiones del catálogo";

  if (!lista.length) {
    cont.innerHTML = '<p class="sin-resultados">Ninguna sesión coincide con la búsqueda.</p>';
    return;
  }

  const cab = '<div class="cabecera-tabla-sesiones">' +
    '<span>Sesión</span><span>Fuente y tipo</span><span>Fecha</span>' +
    '<span>Duración</span><span>Señales</span><span>Filas</span><span></span></div>';

  cont.innerHTML = cab + lista.map(s => {
    const corta = FUENTE_CORTA[s.fuente] || "can";
    const abierta = s.session_id === sesionAbierta;
    return '<div class="fila-sesion" data-fuente="' + corta + '"' +
             (abierta ? ' data-abierta="si"' : '') + '>' +
      '<div><span class="titulo">' + nombreDeSesion(s) + '</span>' +
        '<span class="ident" title="' + s.session_id + '">' + s.session_id + '</span></div>' +
      '<div><span class="pastilla-fuente ' + corta + '">' + ETIQUETA_FUENTE[corta] + '</span>' +
        '<span class="tipo-sesion">' + tipoDeSesion(s) + '</span></div>' +
      '<div class="dato">' + fechaDeSesion(s) + '<small>' + rotuloDeFecha(s) + '</small></div>' +
      '<div class="dato">' + duracionLegible(s) + '<small>duración</small></div>' +
      '<div class="dato">' + s.senales + '<small>señales</small></div>' +
      '<div class="dato">' + s.filas.toLocaleString("es-AR") + '<small>filas</small></div>' +
      '<button class="boton' + (abierta ? '' : ' secundario') + '" type="button" ' +
              'data-abrir="' + s.session_id + '">' + (abierta ? "Abierta" : "Abrir") + '</button>' +
    '</div>';
  }).join("");

  cont.querySelectorAll("[data-abrir]").forEach(b => {
    b.addEventListener("click", () => abrirSesionGuardada(b.dataset.abrir));
  });

  document.getElementById("nota-sesiones").textContent =
    "Cambiar de modo o cerrar el tablero no borra nada: lo único que borra es «Limpiar sesión», " +
    "que pide confirmación. Estas sesiones salen del catálogo de la base.";
}

/* ============================================================
   ABRIR UNA SESION
   ------------------------------------------------------------
   Se piden en paralelo las siete cosas que describen una sesion. Ninguna es
   obligatoria: si la fuente no tiene clima, la consulta contesta con su
   motivo y el panel muestra ese motivo. Lo unico que se espera antes de
   dibujar es la lista de vueltas, porque sin ella no se sabe cuanto dura la
   sesion ni donde empieza cada vuelta.
   ============================================================ */
function abrirSesionGuardada(id) {
  const s = SESIONES.find(x => x.session_id === id);
  if (!s) return;

  estado.abierta = s;
  estado.vueltas = []; estado.series = {}; estado.pidiendo = {};
  estado.posiciones = {}; estado.pidiendoPos = {};
  estado.trazado = null; estado.curvas = []; estado.clima = null; estado.vehiculo = null;
  estado.puesta = null; estado.avisos = []; estado.disponibles = new Set();
  estado.vehiculoClave = null;
  estado.climaMotivo = ""; estado.vehiculoMotivo = ""; estado.avisosMotivo = "";
  estado.cargando = true;
  PISTA = { path: "", curvas: [], largo_m: null, desnivel_m: null, muestras: null };
  CURVAS = [];
  AUTOS = [];
  seleccion = new Set();
  sesionAbierta = id;
  recordarSesion(id);
  cabezal = 0;
  detener();
  olvidarCaches();

  const corta = FUENTE_CORTA[s.fuente] || "can";
  if (corta !== fuente) { fuente = corta; marcar(document.getElementById("sel-fuente"), "fuente", fuente); }
  estadoSesion = "cargado";
  document.getElementById("velo-sesiones").dataset.abierto = "no";
  const svgPista = document.getElementById("linea-pista");
  if (svgPista && svgPista.ownerSVGElement) delete svgPista.ownerSVGElement.dataset.ajustado;
  render();

  const ruta = "/sesiones/" + encodeURIComponent(id);
  const conMotivo = (p, guardar) => p.then(guardar).catch(e => guardar({ error: e.message }));

  Promise.all([
    pedir(ruta + "/vueltas").catch(e => ({ vueltas: [], error: e.message })),
    pedir(ruta + "/trazado?puntos=600").catch(e => ({ puntos: [], motivo: e.message })),
    pedir(ruta + "/clima").catch(e => ({ clima: null, motivo_ausencia: e.message })),
    pedir(ruta + "/vehiculo").catch(e => ({ esquinas: null, motivo_ausencia: e.message })),
    pedir(ruta + "/puesta-a-punto").catch(e => ({ puesta_a_punto: null })),
    pedir(ruta + "/avisos").catch(e => ({ avisos: [], motivo: e.message })),
  ]).then(([vueltas, trazado, clima, vehiculo, puesta, avisos]) => {
    estado.vueltas = vueltas.vueltas || [];
    poblarVueltas();
    estado.clima = clima.clima || null;
    estado.climaMotivo = clima.motivo_ausencia || "";
    estado.vehiculo = (vehiculo && vehiculo.esquinas) ? vehiculo : null;
    estado.vehiculoMotivo = (vehiculo && vehiculo.motivo_ausencia) || "";
    estado.puesta = (puesta && puesta.puesta_a_punto) || null;
    estado.avisosMotivo = (avisos && avisos.motivo_ausencia) || "";

    // Que instrumentos se pueden llenar: lo dice lo que vino.
    if (estado.clima) estado.disponibles.add("air_temperature");
    if (estado.vehiculo) estado.disponibles.add("tyre_temperature_surface_front_left");

    if (trazado && trazado.puntos && trazado.puntos.length) {
      estado.trazado = trazado;
      const armado = trazadoAPath(trazado.puntos,
        /invertir/i.test(trazado.para_dibujarlo || "") &&
        !/no invertir/i.test(trazado.para_dibujarlo || ""));
      PISTA = {
        path: armado.path,
        largo_m: trazado.largo_m,
        desnivel_m: trazado.desnivel_m,
        muestras: trazado.muestras_originales,
        curvas: [],
      };
    }

    ubicarAvisos(avisos.avisos || []);
    pedirCurvas(s);
    const primera = estado.vueltas.length ? estado.vueltas[0].numero : 1;
    vueltaElegida = primera;
    asegurarVuelta(primera);
    asegurarPosiciones(primera);
    estado.cargando = false;
    render();
    avisar("Sesión abierta: " + nombreDeSesion(s), false);
  });
}

/* EL INSTANTE QUE SE ESTA MIRANDO, EN HORA UTC.
   Los paneles de contexto ---clima y estado del vehiculo--- no son series: son
   el ultimo valor publicado hasta un momento. Ese momento sale de la vuelta en
   curso, que ahora declara sus dos instantes, y de la fraccion recorrida. */
function instanteUtc() {
  const t = instante();
  const v = estado.vueltas.find(x => x.numero === t.vuelta);
  if (!v || !v.desde_utc || !v.hasta_utc) return null;
  const t0 = new Date(v.desde_utc).getTime();
  const t1 = new Date(v.hasta_utc).getTime();
  return new Date(t0 + (t1 - t0) * t.fraccion).toISOString();
}

/* Se vuelven a pedir cuando cambia la vuelta, no en cada cuadro: el clima y el
   desgaste no cambian sesenta veces por segundo, y son dos consultas a la base
   cada una. */
let _contextoDe = "";

function refrescarContexto() {
  if (!estado.abierta) return;
  const t = instante();
  const clave = estado.abierta.session_id + "|" + t.vuelta;
  if (clave === _contextoDe) return;
  _contextoDe = clave;
  const cuando = instanteUtc();
  if (!cuando) return;
  const ruta = "/sesiones/" + encodeURIComponent(estado.abierta.session_id);
  const hasta = "?hasta=" + encodeURIComponent(cuando);
  pedir(ruta + "/clima" + hasta).then(d => {
    estado.clima = d.clima || null;
    estado.climaMotivo = d.motivo_ausencia || "";
    _firmaClima = "";
    pintarClima();
  }).catch(() => {});
  pedir(ruta + "/vehiculo" + hasta).then(d => {
    estado.vehiculo = d.esquinas ? d : null;
    estado.vehiculoMotivo = d.motivo_ausencia || "";
    _firmaEsquinas = "";
    pintarEsquinas();
  }).catch(() => {});
}

/* Cada aviso trae vuelta y metro; para colocarlo en la linea de tiempo hace
   falta pasarlo a fraccion de la sesion, que es lo unico que el reproductor
   entiende. */
function ubicarAvisos(lista) {
  const inicios = iniciosDeVuelta();
  const total = duracionSesionS();
  const largo = (PISTA.largo_m || 1);
  estado.avisos = lista.map(a => {
    const v = Math.max(1, Math.min(estado.vueltas.length || 1, a.vuelta || 1));
    const ini = inicios[v - 1] || 0;
    const parte = total > 0 ? duracionDeVuelta(v) / total : 0;
    return Object.assign({}, a, { en: ini + parte * Math.max(0, Math.min(1, (a.metro || 0) / largo)) });
  }).sort((x, y) => x.en - y.en);
}

/* Los nombres de curva son anotacion externa citada: se piden por circuito y
   solo si la sesion declara cual es. Sin procedencia no hay nombres, y el
   trazado se dibuja igual con sus metros. */
function pedirCurvas(s) {
  const circuito = (s.procedencia && s.procedencia.circuito) || s.circuito;
  if (!circuito) { CURVAS = []; return; }
  pedir("/circuitos/" + encodeURIComponent(circuito) + "/curvas")
    .then(d => { CURVAS = d.curvas || []; PISTA.curvas = CURVAS; render(); })
    .catch(() => { CURVAS = []; });
}

document.getElementById("btn-abrir").addEventListener("click", () => {
  document.getElementById("velo-sesiones").dataset.abierto = "si";
  pintarSesiones();
  document.getElementById("busca-sesion").focus();
});
document.getElementById("btn-cerrar-sesiones").addEventListener("click", () => {
  document.getElementById("velo-sesiones").dataset.abierto = "no";
});
document.getElementById("busca-sesion").addEventListener("input", pintarSesiones);
document.getElementById("filtro-fuente").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  filtroFuente = b.dataset.filtro;
  marcar(e.currentTarget, "filtro", filtroFuente);
  pintarSesiones();
});
document.getElementById("orden-sesiones").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  ordenSesiones = b.dataset.orden;
  marcar(e.currentTarget, "orden", ordenSesiones);
  pintarSesiones();
});

// Al arrancar, se recupera la ultima sesion mirada.
(function recuperarSesion() {
  const id = sesionRecordada();
  if (id && SESIONES.some(s => s.session_id === id)) {
    sesionAbierta = id;
  }
})();


/* ============================================================
   EL CABEZAL DE REPRODUCCION
   ------------------------------------------------------------
   Antes los instrumentos mostraban valores fijos: abrir una sesion cambiaba
   el titulo y nada mas. Una sesion guardada **se recorre**, y mientras se
   recorre los valores tienen que ser los de ese instante; si no, el tablero
   no muestra la sesion, muestra una foto que da igual cual se abra.

   `cabezal` es la posicion en la vuelta, de 0 a 1. Todo lo que cambia con el
   tiempo ---velocidad, marcha, regimen, aceleraciones, la marca sobre el
   trazado, el cronometraje--- se deriva de el. Un flujo en vivo no tiene
   cabezal: siempre esta en el ultimo dato, y por eso ahi los mandos no
   aparecen.
   ============================================================ */

let cabezal = 0;
let reproduciendo = false;
let velocidadRep = 1;
let relojRep = null;

/* UNA SESION NO ES UNA VUELTA.
   ---------------------------------------------------------------------
   El cabezal recorria la vuelta de referencia y terminaba ahi: una carrera
   de veintidos vueltas se veia igual que una clasificacion de una. Pero lo
   que se guarda es la sesion entera, y lo que se quiere leer ---donde se
   perdio tiempo, cuando se rompio algo, en que vuelta llego la bandera---
   solo existe si el recorrido abarca la sesion completa.

   Ahora `cabezal` va de 0 a 1 sobre **toda la sesion**. La vuelta y la
   posicion dentro de ella se derivan de el:

       posicion en vueltas   = cabezal x vueltas
       vuelta                = parte entera + 1
       fraccion en la vuelta = parte decimal

   Los graficos siguen yendo contra la distancia de una vuelta ---que es
   como se lee una vuelta--- y lo que se mueve sobre ellos es la marca del
   cabezal, que al cerrar una vuelta vuelve al principio. */

/* Cuantas vueltas declara la sesion abierta. El dato sale de la procedencia
   de la captura, que el capturador deriva del paquete de sesion. */
function sesionActual() {
  return estado.abierta;
}

/* Las vueltas son las que la API encontro en la base: no las que declara la
   configuracion de la sesion, que puede diferir si la captura se corto. */
function vueltasDeLaSesion() {
  return Math.max(1, estado.vueltas.length);
}

/* Cuanto duro cada vuelta, medido. Con esto el cabezal avanza al ritmo real:
   una vuelta lenta ocupa mas linea de tiempo que una rapida, que es lo que
   pasa de verdad y lo que una duracion fija por vuelta escondia. */
function duracionDeVuelta(numero) {
  const v = estado.vueltas.find(x => x.numero === numero);
  return (v && v.duracion_s) || 0;
}

/* En el bus no hay vueltas: hay un tramo de grabacion. Decirle «vuelta 1 de
   1» seria forzar el vocabulario del circuito sobre un dato de calle. */
function hayVueltas() { return estado.vueltas.length > 0 && fuente !== "can"; }

function duracionSesionS() {
  const suma = estado.vueltas.reduce((a, v) => a + (v.duracion_s || 0), 0);
  if (suma > 0) return suma;
  const s = estado.abierta;
  return (s && s.duracion_s) || 60;
}

/* Donde empieza cada vuelta dentro de la sesion, en fraccion de 0 a 1. Se
   calcula con las duraciones medidas, no repartiendo la sesion en partes
   iguales: en una carrera la primera vuelta y la de la parada en boxes duran
   cosas muy distintas. */
function iniciosDeVuelta() {
  const total = duracionSesionS();
  let acumulado = 0;
  return estado.vueltas.map(v => {
    const en = acumulado / total;
    acumulado += v.duracion_s || 0;
    return en;
  });
}

function relojDeSesion(seg) {
  const m = Math.floor(seg / 60), r = seg - m * 60;
  return m + ":" + r.toFixed(1).padStart(4, "0");
}

function serieDelPropio(vuelta) {
  return serieVelocidad(claveVehiculoPropio(), vuelta);
}

/* Y esto tambien se repetia: siete funciones por cuadro preguntaban por el
   mismo instante y cada una lo recalculaba entero. Se calcula una vez por
   posicion del cabezal y las demas leen lo ya calculado. */
let _instanteClave = null;
let _instanteCache = null;

function instante() {
  const clave = cabezal + "|" + fuente + "|" + sesionAbierta;
  if (clave === _instanteClave) return _instanteCache;
  _instanteCache = calcularInstante();
  _instanteClave = clave;
  return _instanteCache;
}

/* EL INSTANTE.
   ---------------------------------------------------------------------
   Todo lo que cambia con el tiempo se lee de aca, y aca no se calcula nada:
   cada magnitud es el valor que la fuente publico en ese metro de esa
   vuelta. Cuando la fuente no trae una señal, el campo vale `null` y el
   instrumento que lo muestra escribe una raya en vez de un numero.

   La vuelta se ubica con las duraciones medidas de cada vuelta, no
   repartiendo la sesion en partes iguales: la vuelta de la parada en boxes
   dura casi el doble que las otras y tiene que ocupar el doble de la linea
   de tiempo. */
function calcularInstante() {
  if (estadoSesion === "vivo") {
    const vehiculo = claveVehiculoPropio();
    const ultimos = vivo.ultimos.get(vehiculo) || new Map();
    const leer = canal => {
      const mensaje = ultimos.get(nombreDeSenal(canal));
      return mensaje && mensaje.value !== undefined ? mensaje.value : null;
    };
    const velocidad = leer("speed");
    const vuelta = vivo.vuelta.get(vehiculo) || 1;
    const metro = vivo.distancia.get(vehiculo) || 0;
    return {
      listo: velocidad !== null, indice: 0, vuelta: vuelta,
      vueltas: Math.max(vuelta, estado.vueltas.length || 1), fraccion: 1,
      fraccionSesion: 1, segundos: 0, metro: metro, velocidad: velocidad,
      acelerador: leer("throttle"), freno: leer("brake"), rpm: leer("rpm"),
      marcha: leer("gear"), gLong: leer("glong"), gLat: leer("glat"),
      gVert: leer("gvert"), tempMotor: leer("engineTemp"), ers: leer("ers"),
      ersMJ: leer("ers") === null ? null : Number(leer("ers")) / 1e6,
      combustibleKg: leer("fuel"), tempFrenoDel: leer("brakeTemp"),
      tempNeumatico: leer("tyre"), deslizamiento: leer("slip"),
      diferencia: leer("gap"), frenando: 0, avance: 1,
      vueltasRestantes: null, sesgoFreno: leer("brake_bias_front"),
    };
  }
  const n = vueltasDeLaSesion();
  const inicios = iniciosDeVuelta();
  let indiceVuelta = 0;
  for (let i = 0; i < inicios.length; i++) if (cabezal >= inicios[i] - 1e-9) indiceVuelta = i;
  const vuelta = estado.vueltas[indiceVuelta] ? estado.vueltas[indiceVuelta].numero : 1;

  const total = duracionSesionS();
  const ini = inicios[indiceVuelta] || 0;
  const parte = total > 0 ? duracionDeVuelta(vuelta) / total : 0;
  const dentro = parte > 0 ? Math.max(0, Math.min(1, (cabezal - ini) / parte)) : 0;

  const dist = serieDeCanal("speed", vuelta);
  const listo = !!(dist && dist.length);
  const idx = listo ? Math.min(dist.length - 1, Math.round(dentro * (dist.length - 1))) : 0;

  // Lee una señal en el mismo punto de la vuelta. Cada señal puede tener su
  // propia cantidad de muestras: se ubica por fraccion, no por indice.
  const leer = (canal) => {
    const s = serieDeCanal(canal, vuelta);
    if (!s || !s.length) return null;
    return s[Math.min(s.length - 1, Math.round(dentro * (s.length - 1)))][1];
  };

  const v = listo ? dist[idx][1] : null;
  const sig = listo ? dist[Math.min(idx + 1, dist.length - 1)][1] : null;

  return {
    listo: listo,
    indice: idx,
    vuelta: vuelta,
    vueltas: n,
    fraccion: dentro,
    fraccionSesion: cabezal,
    segundos: cabezal * total,
    metro: listo ? dist[idx][0] : 0,
    velocidad: v,
    acelerador: leer("throttle"),
    freno: leer("brake"),
    rpm: leer("rpm"),
    marcha: leer("gear"),
    gLong: leer("glong"),
    gLat: leer("glat"),
    gVert: leer("gvert"),
    tempMotor: leer("engineTemp"),
    ers: leer("ers"),
    ersMJ: (function () { const v = leer("ers"); return v === null ? null : v / 1e6; })(),
    combustibleKg: leer("fuel"),
    tempFrenoDel: leer("brakeTemp"),
    tempNeumatico: leer("tyre"),
    deslizamiento: leer("slip"),
    diferencia: leer("gap"),
    // Cuanto se esta frenando en este instante, para los paneles que lo usan.
    frenando: (v !== null && sig !== null) ? Math.max(0, v - sig) : 0,
    avance: cabezal,
    vueltasRestantes: Math.max(0, n - vuelta),
    sesgoFreno: estado.puesta ? estado.puesta.sesgo_de_freno_pct : null,
  };
}

function textoDeVuelta(metro) {
  return Math.round(metro).toLocaleString("es-AR") + " m";
}

function pintarTransporte() {
  const barra = document.getElementById("transporte");
  if (!barra) return;

  const modo = estadoSesion === "vivo" ? "vivo"
             : estadoSesion === "vacio" ? "vacio" : "reproduccion";
  barra.dataset.modo = modo;

  if (modo === "vivo") {
    // Un flujo en vivo no se recorre: no hay cabezal ni mandos que ofrecer.
    detener();
    /* Caudal y antiguedad los declara el difusor. Antes eran dos cifras
       escritas que no cambiaban nunca, que es lo peor que puede decir un
       indicador de «en vivo». */
    const v = estado.vivo || {};
    const a = estado.activa || {};
    const partes = [];
    if (v.mensajes_recibidos !== undefined) partes.push(cifra(v.mensajes_recibidos, 0) + " mensajes");
    if (v.vehiculos && v.vehiculos.length) partes.push(v.vehiculos.length + " vehículos en el flujo");
    if (a.ultimo_dato) {
      const seg = Math.max(0, (Date.now() - new Date(a.ultimo_dato)) / 1000);
      partes.push("último dato hace " + seg.toFixed(1).replace(".", ",") + " s");
    }
    if (v.conectado === false) partes.push("difusor desconectado" + (v.motivo ? ": " + v.motivo : ""));
    document.getElementById("detalle-vivo").textContent =
      partes.length ? partes.join(" · ") : "esperando al difusor…";
    return;
  }
  if (modo === "vacio") { detener(); return; }

  const t = instante();
  const s = serieDelPropio(t.vuelta);
  const total = s.length ? s[s.length - 1][0] : 0;
  const dur = duracionSesionS();

  // Lo primero que se lee es en que vuelta va, porque es lo que ubica todo
  // lo demas. El metro y el reloj acompañan.
  document.getElementById("tr-posicion").textContent = hayVueltas()
    ? "Vuelta " + t.vuelta + "/" + t.vueltas
    : relojDeSesion(t.segundos);
  document.getElementById("tr-total").textContent = hayVueltas()
    ? textoDeVuelta(t.metro) + " · " + relojDeSesion(t.segundos) + " de " + relojDeSesion(dur)
    : "de " + relojDeSesion(dur) + " grabados";
  document.getElementById("tr-cabezal").value = String(Math.round(cabezal * 10000));

  /* QUE SE MARCA SOBRE LA LINEA DE TIEMPO.
     Con una sola vuelta se marcan las curvas, que es lo que hay que ubicar
     dentro de ella. Con varias, las curvas serian cientos de rayas juntas y
     lo que hace falta ubicar son **las vueltas**: se marcan esas. */
  const marcas = document.getElementById("marcas-tiempo");
  if (!marcas) return;
  const n = vueltasDeLaSesion();
  // Las marcas solo cambian al cambiar de vuelta o de sesion.
  const firmaMarcas = [fuente, n, t.vuelta].join("|");
  if (marcas.dataset.firma === firmaMarcas) return;
  marcas.dataset.firma = firmaMarcas;
  if (n > 1) {
    const cada = Math.ceil(n / 12);
    let html = "";
    for (let v = 1; v <= n; v++) {
      const x = ((v - 1) / n) * 100;
      const rotula = (v === 1) || (v % cada === 0);
      html += '<span class="marca-vuelta' + (v === t.vuelta ? " actual" : "") +
        '" style="left:' + x.toFixed(2) + '%" title="Vuelta ' + v + '">' +
        (rotula ? v : "·") + '</span>';
    }
    marcas.innerHTML = html;
  } else if (fuente === "f1") {
    const puestas = [];
    marcas.innerHTML = (PISTA.curvas || []).filter(c => {
      if (puestas.indexOf(c.nombre) !== -1) return false;
      puestas.push(c.nombre); return true;
    }).map(c =>
      '<span style="left:' + ((c.metro / total) * 100).toFixed(1) + '%" title="' +
      c.nombre + '">·</span>').join("");
  } else {
    marcas.innerHTML = "";
  }
}

/* UN SOLO RELOJ PARA TODAS LAS VISTAS.
   El reproductor no pertenece al tablero: pertenece a la sesion. Por eso la
   barra esta fija abajo, se ve en la comparacion y en el detalle igual que
   en el tablero, y todo lo que dibuja la maqueta ---instrumentos, trazado,
   graficos chicos, paneles de comparacion--- lee el mismo cabezal. Dos
   relojes distintos en dos vistas de la misma sesion serian dos respuestas
   distintas a la misma pregunta. */
/* Al cambiar de piloto propio o de fuente, lo memorizado deja de valer. */
function olvidarCaches() {
  _instanteClave = null;
  _firmaMedidores = "";
  _firmaAvisos = "";
  _firmaEsquinas = "";
  _firmaClima = "";
  _ultimaVueltaDibujada = -1;
  const g = document.getElementById("marcas-pista");
  if (g) g.dataset.firma = "";
}

function moverCabezal(fraccion) {
  cabezal = Math.max(0, Math.min(1, fraccion));
  const t = instante();
  // La vuelta que mira la comparacion es la que esta bajo el cabezal.
  if (vueltaElegida !== t.vuelta) {
    vueltaElegida = t.vuelta;
    const sel = document.getElementById("sel-vuelta-numero");
    if (sel && sel.value !== String(t.vuelta)) sel.value = String(t.vuelta);
  }
  // El encabezado tambien anuncia la vuelta: si no se repinta, queda
  // declarando una vuelta mientras el cronometraje muestra otra.
  pintarTitulo();
  pintarTransporte();
  pintarMedidores();
  pintarG();
  pintarPista();
  pintarCronometraje();
  pintarAvisos();
  pintarEsquinas();
  pintarClima();
  /* Al cerrar una vuelta cambia la traza: hay que volver a dibujarla. Es una
     vez cada vuelta y media de minuto, no una vez por cuadro. */
  /* La vuelta que se esta mirando tiene que estar; la siguiente se pide
     mientras se mira esta, para que al cruzar el arco de meta ya este. Pedir
     la sesion entera de una serian veintidos consultas de medio megabyte para
     mirar una vuelta. */
  const vActual = instante().vuelta;
  if (vActual !== _ultimaVueltaDibujada) {
    _ultimaVueltaDibujada = vActual;
    asegurarVuelta(vActual);
    asegurarVuelta(vActual + 1);
    asegurarPosiciones(vActual);
    asegurarPosiciones(vActual + 1);
    refrescarContexto();
  }
  /* Los graficos no se vuelven a trazar: su traza es la de la vuelta y no
     cambia al avanzar el cabezal. Lo unico que se mueve es la linea. */
  moverCabezalesGraficos();
  /* La traza crece con el cabezal, asi que hay que volver a trazarla; treinta
     veces por segundo alcanza para que se vea continua y deja la mitad del
     presupuesto de cada cuadro libre para todo lo demas. */
  const ahoraT = performance.now();
  if (ahoraT - _ultimaTraza > 32) {
    _ultimaTraza = ahoraT;
    dibujarTraza();
  }
  /* La comparacion si vuelve a trazarse ---su cabezal lleva ademas el punto de
     cada serie, que hay que recalcular---, pero no hace falta a sesenta por
     segundo: veinticinco ya se ven continuos y el lienzo es grande. */
  if (compAbierta()) {
    const ahora = performance.now();
    if (ahora - _ultimaComparacion > 38) {
      _ultimaComparacion = ahora;
      dibujarComparacion();
    }
  }
}
let _ultimaComparacion = 0;
let _ultimaVueltaDibujada = -1;
let _ultimaTraza = 0;

/* Cuantos metros de vuelta entran en cada grafico. Cero es la vuelta entera.
   Es el mando que decide si se mira una frenada o la vuelta completa: con
   trescientos metros se ve el pedal punto por punto; con la vuelta entera se
   ve la forma general y se pierde el detalle. */
let ventanaTraza = 1200;

function detener() {
  reproduciendo = false;
  if (relojRep) { cancelAnimationFrame(relojRep); relojRep = null; }
  const b = document.getElementById("tr-play");
  if (b) {
    b.setAttribute("aria-pressed", "false");
    b.setAttribute("aria-label", "Reproducir");
    document.getElementById("icono-play").innerHTML = '<path d="M4 2 L14 8 L4 14 Z" />';
  }
}

function reproducir() {
  if (estadoSesion !== "cargado") return;
  reproduciendo = true;
  const b = document.getElementById("tr-play");
  b.setAttribute("aria-pressed", "true");
  b.setAttribute("aria-label", "Pausar");
  document.getElementById("icono-play").innerHTML =
    '<path d="M4 2 h3 v12 h-3 Z M9 2 h3 v12 h-3 Z" />';
  if (relojRep) cancelAnimationFrame(relojRep);
  // A 1x la sesion se recorre en el tiempo que duro de verdad: una vuelta de
  // Spa son unos noventa y cinco segundos, y una carrera de veintidos vueltas,
  // treinta y cinco minutos. Por eso hacen falta velocidades altas: a 10x esa
  // misma carrera se recorre en tres minutos y medio.
  /* CADA CUADRO DE PANTALLA, NO CADA CINCUENTA MILISEGUNDOS.
     Con un temporizador cada 50 ms el cabezal avanzaba a veinte pasos por
     segundo: a 1x eso son saltos visibles, porque el ojo distingue de sobra
     veinte posiciones por segundo. `requestAnimationFrame` entrega un cuadro
     cada vez que la pantalla se refresca ---sesenta por segundo en la
     mayoria--- y ademas dice **cuando**: el avance se calcula con el tiempo
     transcurrido de verdad, no suponiendo que cada paso duro lo que se pidio.
     Asi la reproduccion no se atrasa cuando un cuadro tarda de mas. */
  let anterior = performance.now();
  const paso = (ahora) => {
    if (!reproduciendo) return;
    const dt = Math.min(0.25, (ahora - anterior) / 1000);  // tras una pausa larga, no saltar
    anterior = ahora;
    cabezal += (dt * velocidadRep) / duracionSesionS();
    if (cabezal >= 1) { cabezal = 1; moverCabezal(1); detener(); return; }
    moverCabezal(cabezal);
    relojRep = requestAnimationFrame(paso);
  };
  relojRep = requestAnimationFrame(paso);
}

(function mandosDeTransporte() {
  const play = document.getElementById("tr-play");
  if (!play) return;
  play.addEventListener("click", () => (reproduciendo ? detener() : reproducir()));
  // Diez segundos de sesion, no de vuelta: el salto tiene que significar lo
  // mismo en una clasificacion de una vuelta que en una carrera de veintidos.
  document.getElementById("tr-atras").addEventListener("click",
    () => moverCabezal(cabezal - 10 / duracionSesionS()));
  document.getElementById("tr-adelante").addEventListener("click",
    () => moverCabezal(cabezal + 10 / duracionSesionS()));
  document.getElementById("tr-cabezal").addEventListener("input", e => {
    detener();
    moverCabezal(Number(e.target.value) / 10000);
  });
  document.getElementById("tr-velocidad").addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    velocidadRep = Number(b.dataset.vel);
    marcar(e.currentTarget, "vel", b.dataset.vel);
    if (reproduciendo) reproducir();
  });
  /* AMPLIAR LA CABINA.
     Cuando lo unico que se esta haciendo es mirar la carrera, el encabezado y
     lo que hay debajo de la cabina no aportan: la cabina toma la ventana
     entera menos la barra, que es lo que dice donde esta parado lo que se
     mira. Escape la devuelve a su sitio. */
  const btnCabina = document.getElementById("btn-cabina");
  const cabina = document.getElementById("cabina");

  /* PANTALLA COMPLETA DEL NAVEGADOR, Y SI NO SE PUEDE, DEL MARCO.
     El boton pide la pantalla completa de verdad ---la que saca la barra de
     direcciones y las pestañas---, que es lo que hace falta para mirar una
     carrera. Dentro de un marco incrustado el navegador puede negarla; en ese
     caso se cae en lo que si se puede: la cabina ocupando el marco entero.
     Se avisa cual de las dos quedo, porque salir se hace distinto. */
  function enPantallaCompleta() {
    return !!(document.fullscreenElement || document.webkitFullscreenElement);
  }

  function pedirPantallaCompleta() {
    const raiz = document.documentElement;
    const pedir = raiz.requestFullscreen || raiz.webkitRequestFullscreen;
    if (!pedir) { ampliarCabina(true); return; }
    let p;
    try { p = pedir.call(raiz); } catch (e) { ampliarCabina(true); return; }
    if (p && p.catch) p.catch(() => ampliarCabina(true));
  }

  function salirPantallaCompleta() {
    if (enPantallaCompleta()) {
      const salir = document.exitFullscreen || document.webkitExitFullscreen;
      if (salir) salir.call(document);
    }
    ampliarCabina(false);
  }

  function ampliarCabina(si) {
    if (!cabina || !btnCabina) return;
    cabina.dataset.pantalla = si ? "completa" : "normal";
    btnCabina.setAttribute("aria-pressed", String(si));
    btnCabina.title = si ? "Salir de pantalla completa" : "Ver en pantalla completa";
    document.body.style.overflow = si ? "hidden" : "";
    ajustarCabina();
    // Los lienzos se miden contra su caja: al cambiar de tamaño hay que
    // volver a dibujarlos o quedan estirados.
    requestAnimationFrame(() => { dibujarTraza(); moverCabezalesGraficos(); pintarPista(); });
  }
  if (btnCabina) {
    btnCabina.addEventListener("click", () => {
      const activa = enPantallaCompleta() || cabina.dataset.pantalla === "completa";
      activa ? salirPantallaCompleta() : pedirPantallaCompleta();
    });
  }
  // Salir con Escape lo maneja el navegador; queda avisar al boton y remedir.
  ["fullscreenchange", "webkitfullscreenchange"].forEach(ev =>
    document.addEventListener(ev, () => {
      const si = enPantallaCompleta();
      if (btnCabina) {
        btnCabina.setAttribute("aria-pressed", String(si));
        btnCabina.title = si ? "Salir de pantalla completa" : "Ver en pantalla completa";
      }
      requestAnimationFrame(() => {
        ajustarCabina(); dibujarTraza(); moverCabezalesGraficos(); pintarPista();
      });
    }));
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && cabina && cabina.dataset.pantalla === "completa" &&
        !enPantallaCompleta()) {
      ampliarCabina(false);
    }
  });

  // La barra espaciadora reproduce y pausa, como en cualquier reproductor.
  document.addEventListener("keydown", e => {
    if (e.code !== "Space") return;
    const t = e.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "BUTTON" ||
              t.tagName === "SELECT" || t.tagName === "TEXTAREA")) return;
    if (estadoSesion !== "cargado") return;
    e.preventDefault();
    reproduciendo ? detener() : reproducir();
  });
})();

/* El cronometraje deja de ser fijo: sale del cabezal. */
function pintarCronometraje() {
  const tira = document.querySelector(".tira-cronometraje");
  if (!tira) return;
  if (estadoSesion === "vacio") return;
  const t = instante();
  const s = serieDelPropio(t.vuelta);
  const total = s.length ? s[s.length - 1][0] : 0;
  // El reloj de vuelta corre dentro de la vuelta, no de la sesion: es el
  // tiempo de la vuelta en curso, que es lo que mira quien conduce.
  // El tiempo de vuelta corre sobre la duracion medida de **esta** vuelta.
  const seg = t.fraccion * duracionDeVuelta(t.vuelta);
  const reloj = Math.floor(seg / 60) + ":" + (seg % 60).toFixed(2).padStart(5, "0");
  const celdas = tira.querySelectorAll("dd");
  if (celdas.length >= 4) {
    celdas[1].innerHTML = hayVueltas()
      ? t.vuelta + '<span style="color:var(--texto-tenue);font-size:.8rem">/' +
        t.vueltas + "</span>"
      : '<span style="font-size:.9rem">tramo</span>';
    celdas[2].textContent = reloj;
    /* La diferencia con el lider es una señal de la fuente, no una cuenta que
       este tablero pueda hacer: si no viene, se dice que no viene. */
    const dif = t.diferencia;
    celdas[3].textContent = dif === null || dif === undefined ? "—" : Number(dif).toFixed(3);
    celdas[3].className = (dif !== null && dif < 0) ? "negativo" : "";
  }
  const cab = document.getElementById("canal-traza");
  if (cab) cab.title = "Cabezal en " + Math.round(t.metro) + " m";
  // La posicion es la del propio: decirlo evita leerla como la del lider.
  if (celdas.length >= 1) {
    celdas[0].innerHTML = AUTOS.length <= 1
      // En el bus no hay parrilla: no hay posicion contra nadie.
      ? '<span style="font-size:.9rem">sin parrilla</span>'
      /* La posicion en carrera no esta entre las señales que se guardan: se
         declara ausente en vez de inventar un P4. Lo que si se puede decir es
         de que vehiculo son los datos. */
      : '<span style="font-size:.9rem">' + autoPropio().nombre + '</span>';
  }
}

/* ============================================================
   QUE SOSTIENE CADA FUENTE
   ------------------------------------------------------------
   La tabla del pie estaba escrita a mano con lo que se habia medido el dia
   que se armo la maqueta. `/fuentes/matriz` la calcula sobre la base: para
   cada magnitud y cada fuente dice si esta, con que señal, en que unidad y a
   que frecuencia. Es la afirmacion central del trabajo y no puede depender
   de que alguien acuerde de actualizar una tabla.
   ============================================================ */
function pintarMatriz() {
  const m = estado.matriz;
  const tabla = document.querySelector("table.disponibilidad");
  if (!m || !tabla) return;

  const orden = ["f1_25_udp_simulation", "openf1_historical_replay", "can_real_replay"];
  const fuentes = orden
    .map(c => (m.fuentes || []).find(f => f.clave === c))
    .filter(Boolean);

  const celda = d => {
    if (!d || !d.disponible) return '<td class="no">no</td>';
    const detalle = [d.unidad, d.hz ? cifra(d.hz, 1) + " Hz" : null]
      .filter(Boolean).join(" · ");
    return '<td class="si" title="' + (d.senal || "") + '">' + (detalle || "sí") + '</td>';
  };

  tabla.querySelector("thead").innerHTML =
    "<tr><th>Magnitud</th>" +
    fuentes.map(f => '<th title="' + f.detalle + '">' + f.nombre + "</th>").join("") +
    "<th>Señal que la habilita</th></tr>";

  tabla.querySelector("tbody").innerHTML = (m.magnitudes || []).map(mag => {
    const senales = fuentes.map(f => (mag.fuentes[f.clave] || {}).senal).filter(Boolean);
    const nombres = senales.filter((s, i) => senales.indexOf(s) === i);
    return "<tr><td>" + mag.magnitud + "</td>" +
      fuentes.map(f => celda(mag.fuentes[f.clave])).join("") +
      "<td>" + (nombres.length ? nombres.map(s => "<code>" + s + "</code>").join(", ")
                               : "ninguna fuente la entrega") + "</td></tr>";
  }).join("");

  const pie = tabla.closest(".instrumento").querySelector(".fuente-canal");
  if (pie) {
    pie.textContent = "medido sobre la base" +
      (m.edad_del_calculo_s !== undefined && m.edad_del_calculo_s !== null
        ? " hace " + Math.round(m.edad_del_calculo_s / 60) + " min" : "") +
      (m.recalculando ? " · recalculando" : "");
  }
}

/* ---------------- render ---------------- */
function render() {
  /* La vuelta que se anuncia es siempre la del cabezal. Al cambiar de fuente
     cambia cuantas vueltas tiene la sesion, y sin esto el encabezado seguia
     anunciando la vuelta de la fuente anterior mientras el cronometraje ya
     mostraba la nueva: dos respuestas a la misma pregunta. */
  if (estadoSesion !== "vacio") vueltaElegida = instante().vuelta;
  pintarCiclo(); aplicarDisponibilidad(); pintarAutos(); pintarEsquinas();
  pintarTransporte(); pintarCronometraje();
  pintarMedidores(); pintarClima(); pintarAvisos(); pintarG(); pintarPista(); pintarControlesTraza();
  pintarLeyendaTraza(); dibujarTraza(); moverCabezalesGraficos();
  if (compAbierta()) { pintarPilotosComparacion(); dibujarComparacion(); }
}
/* La ayuda se despliega por CSS al pasar el puntero o al recibir el foco:
   no hace falta codigo. */

/* LA CABINA OCUPA LA PANTALLA, NO LO QUE SOBRA DEBAJO DEL ENCABEZADO.
   Antes se media el hueco entre donde empieza la cabina y la barra de
   reproduccion, contando el encabezado como parte de la pantalla. Pero el
   encabezado ---la nota, el titulo del circuito, el ciclo de vida--- se mira
   una vez: quien opera desplaza dos centimetros y lo deja arriba. Contarlo
   como sitio ocupado le quitaba doscientos pixeles a la cabina justamente
   cuando estaba fuera de la vista.

   Ahora la cabina mide **la ventana entera menos la barra**, que es lo que se
   ve una vez que el encabezado quedo arriba, y al abrir la pagina se coloca
   en ella. El encabezado sigue estando, a un desplazamiento hacia arriba. */
function ajustarCabina() {
  const cabina = document.getElementById("cabina");
  const barra = document.getElementById("transporte");
  if (!cabina || !barra) return;
  if (cabina.dataset.pantalla === "completa") { cabina.style.height = ""; return; }
  // Debajo de la caida a lista, la cabina crece con su contenido.
  if (window.innerWidth <= 1180) { cabina.style.height = ""; return; }
  const alto = window.innerHeight - barra.offsetHeight - 16;
  cabina.style.height = Math.max(380, alto) + "px";
}

/* Coloca la pagina en la cabina. Se hace una sola vez, al abrir: despues es
   de quien mira decidir donde quiere estar. */
let yaEncuadrada = false;
function encuadrarCabina() {
  const cabina = document.getElementById("cabina");
  if (!cabina || yaEncuadrada || window.innerWidth <= 1180) return;
  if (window.scrollY > 4) { yaEncuadrada = true; return; }  // ya la movieron
  window.scrollTo(0, Math.max(0, cabina.offsetTop - 8));
  yaEncuadrada = true;
}

window.addEventListener("resize", () => {
  ajustarCabina();
  dibujarTraza(); moverCabezalesGraficos();
  if (compAbierta()) dibujarComparacion();
});
/* ============================================================
   ARRANQUE
   ------------------------------------------------------------
   Primero el catalogo, porque sin el no hay nada que abrir. Despues, la
   sesion que se estaba mirando la ultima vez o, si no hay ninguna, la mas
   reciente que tenga filas.
   ============================================================ */
/* ============================================================
   ESTA ENTRANDO DATO O NO
   ------------------------------------------------------------
   La base sabe lo que ya entro; no sabe si algo esta entrando ahora. Eso lo
   contesta `/sesion/activa`, que distingue tres cosas que en un panel vacio
   se ven iguales: no hay sesion, hay una guardada, y ademas esta entrando
   dato en este momento. El indicador de «en vivo» sale de ahi y de
   `/live/status`, que da el caudal y la antiguedad del ultimo dato.
   ============================================================ */
let _relojVivo = null;

function vigilarEnVivo() {
  const mirar = () => {
    if (!estado.abierta) return;
    Promise.all([
      pedir("/sesion/activa?fuente=" + encodeURIComponent(estado.abierta.fuente)).catch(() => null),
      pedir("/live/status").catch(() => null),
    ]).then(([activa, vivo]) => {
      estado.activa = activa;
      estado.vivo = vivo;
      // El estado decorativo no convierte una sesion historica en viva. Solo
      // una muestra SSE correlacionada tiene autoridad para hacerlo.
      pintarTransporte();
    });
  };
  if (_relojVivo) clearInterval(_relojVivo);
  mirar();
  // Cada tres segundos: es un latido, no una consulta de datos.
  _relojVivo = setInterval(mirar, 3000);
}

function decirEstadoApi(texto, esError) {
  const el = document.getElementById("estado-api");
  if (!el) return;
  el.hidden = !texto;
  el.textContent = texto || "";
  el.dataset.error = esError ? "si" : "no";
}

function arrancar() {
  estadoSesion = "vacio";
  estado.motivo = "Pidiendo el catálogo de sesiones…";
  decirEstadoApi(estado.motivo, false);
  render();
  ajustarCabina();

  pedir("/sesiones?limite=400")
    .then(d => {
      SESIONES = (d.sesiones || []).filter(s => s.filas > 0);
      decirEstadoApi(SESIONES.length
        ? SESIONES.length + " sesiones en el catálogo · API en " + (API || "el mismo host")
        : "", false);
      if (!SESIONES.length) {
        estado.motivo = d.vacio_porque ||
          "El catálogo está vacío. No hay sesiones guardadas en la base.";
        render();
        return;
      }
      /* Cual se abre sola. La ultima que se miro, si sigue estando. Si no, la
         mas grande de la simulacion: es la unica fuente que declara distancia
         recorrida, y sin distancia no hay eje sobre el que dibujar. Abrir de
         entrada una de OpenF1 dejaba el tablero entero en blanco con razon,
         pero sin que se entendiera por que. */
      /* `?sesion=` abre una en particular. Sirve para compartir un enlace a
         lo que uno esta mirando, que en un tablero de analisis es la mitad de
         la conversacion. */
      const pedida = new URLSearchParams(location.search).get("sesion");
      const recordada = pedida || sesionRecordada();
      const conEje = SESIONES.filter(s => s.fuente === "f1_25_udp_simulation");
      const elegida = SESIONES.find(s => s.session_id === recordada) ||
        (conEje.length ? conEje : SESIONES).slice().sort((a, b) => b.filas - a.filas)[0];
      abrirSesionGuardada(elegida.session_id);
    })
    .catch(e => {
      estadoSesion = "vacio";
      estado.motivo = "No se pudo hablar con la API en " + (API || "el mismo host") +
        ": " + e.message;
      decirEstadoApi(estado.motivo, true);
      render();
    });

  // La matriz de fuentes tarda: se pide aparte y se dibuja cuando llega.
  pedir("/fuentes/matriz").then(m => { estado.matriz = m; pintarMatriz(); }).catch(() => {});
  vigilarEnVivo();
  conectarFlujoEnVivo();
}

poblarVueltas();
arrancar();
encuadrarCabina();
/* Las tipografias llegan por red y cambian el alto de todo lo que tiene texto:
   la medida tomada antes de que carguen queda vieja. Se vuelve a medir cuando
   terminan de cargar, y ahi se encuadra ---antes, el encabezado todavia no
   tiene su alto definitivo y la pagina quedaria corrida. */
if (document.fonts && document.fonts.ready) {
  document.fonts.ready.then(() => { ajustarCabina(); encuadrarCabina(); });
}
// La nota plegable cambia el alto del encabezado: la cabina vuelve a medirse.
(function notaPlegable() {
  const nota = document.querySelector(".aviso-maqueta");
  if (nota) nota.addEventListener("toggle", ajustarCabina);
})();
/* El cabezal arranca al principio de la sesion, que es donde empieza la
   sesion. La maqueta lo ponia a mitad para que se viera algo; con datos de
   verdad, empezar por el principio es lo correcto. */
moverCabezal(0);
window.addEventListener("pagehide", cerrarFlujoEnVivo);
/* Para poder mirar el tablero sin reproducir, se puede abrir con el cabezal
   en un punto: `#0.35` lo coloca al treinta y cinco por ciento de la sesion.
   Es una comodidad de desarrollo y de captura, no una funcion del producto. */
(function cabezalPorDireccion() {
  const f = parseFloat((location.hash || "").replace("#", ""));
  if (isFinite(f) && f >= 0 && f <= 1) {
    const cuando = () => { if (estado.vueltas.length) { moverCabezal(f); } else { setTimeout(cuando, 200); } };
    setTimeout(cuando, 400);
  }
})();
