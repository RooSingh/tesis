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

/* Donde vive la API.

   LA REGLA ES «EL MISMO ORIGEN, SALVO QUE ESTEMOS EN EL SERVIDOR DE DESARROLLO».

   La version anterior hacia lo contrario: le pegaba `:8000` al host salvo que ya
   estuviera en el 8000. Eso funciona mientras el tablero y la API vivan en la
   misma maquina y en dos puertos, y **se rompe apenas dejan de hacerlo**:
   servido en `https://un.dominio/`, pedia `https://un.dominio:8000`, un puerto
   que detras de un tunel no existe y que nadie publica.

   Al derredor: el 3000 es el servidor de desarrollo del tablero, el unico caso
   donde la API esta en otro lado. En cualquier otro origen ---la API sirviendo
   los archivos ella misma, que es como corre el despliegue--- se pide contra el
   mismo origen y no hay ni puerto que adivinar ni CORS que permitir.

   `?api=...` sigue ganando sobre todo, que es lo que hace falta para medir un
   backend contra otro. */
const API = (function () {
  const pedido = new URLSearchParams(location.search).get("api");
  if (pedido) return pedido.replace(/\/+$/, "");
  if (location.protocol === "file:") return "http://127.0.0.1:8000";
  if (location.port === "3000") {
    return location.protocol + "//" + location.hostname + ":8000";
  }
  return "";
})();

/* ============================================================
   QUE ESTA ESPERANDO
   ------------------------------------------------------------
   Un panel que espera una consulta y un panel sin dato se ven igual si
   ninguno de los dos lo dice, y son dos afirmaciones distintas: uno todavia
   no sabe y el otro sabe que la fuente no lo publica. Todo este tablero se
   apoya en esa diferencia, de modo que la espera necesita su propia marca.

   Cada consulta declara **que panel** deja esperando. Un mismo panel puede
   estar esperando dos cosas ---el vehiculo espera su estado y la serie de su
   vuelta--- y por eso se cuenta, no se marca con un booleano. */
const PANELES_DE = {
  catalogo: [],
  vueltas: ["cronometraje"],
  trazado: ["trazado"],
  clima: ["clima"],
  vehiculo: ["vehiculo"],
  puesta: ["puesta"],
  avisos: ["avisos"],
  series: ["motor", "cronometraje", "aceleraciones", "graficos"],
  posiciones: ["trazado", "vehiculos"],
  curvas: ["trazado"],
};

/* Esto se contaba con dos llamadas apareadas ---una al empezar y otra al
   terminar--- y el par se puede romper de tres maneras: una salida temprana
   entre las dos, una excepcion en el medio, o una consulta que no vuelve
   nunca. Las tres dejan al panel diciendo que espera algo que ya no espera, y
   se vio: el tablero mostraba los ocho paneles cargando sobre datos dibujados.

   Un indicador de espera que se traba es peor que no tenerlo, porque miente
   sobre lo unico que tiene que decir. Asi que la espera ya no se cuenta: se
   entrega un vale por consulta, el vale se devuelve solo cuando la promesa se
   asienta ---salga bien o mal--- y ademas vence. Un vale que nadie devolvio en
   treinta segundos corresponde a una consulta que fracaso sin avisar. */
const LIMITE_ESPERA_MS = 30000;
const _vales = new Map();
let _proximoVale = 0;
let _relojVales = null;

/* Envuelve una consulta con su marca de espera. Recibe la funcion que la
   lanza, no la promesa ya lanzada, para que una excepcion al construirla
   tambien devuelva el vale. */
/* `deFondo` es una consulta que **no se esta esperando para mirar**: la vuelta
   siguiente, pedida mientras se mira la actual. Cuenta igual para el limite de
   espera y para la deduplicacion ---es la misma consulta--- pero no enciende el
   velo de los paneles, porque esos paneles tienen dato valido en pantalla y
   taparlos con un shimmer dice que no lo tienen. */
function conCarga(claves, lanzar, deFondo) {
  const cl = Array.isArray(claves) ? claves : [claves];
  const vale = ++_proximoVale;
  _vales.set(vale, { claves: cl, vence: Date.now() + LIMITE_ESPERA_MS, fondo: !!deFondo });
  vigilarVales();
  pintarCargas();
  const soltar = () => { if (_vales.delete(vale)) pintarCargas(); };
  let p;
  try { p = lanzar(); } catch (e) { soltar(); throw e; }
  if (!p || typeof p.then !== "function") { soltar(); return p; }
  return p.then(v => { soltar(); return v; }, e => { soltar(); throw e; });
}

/* El vencimiento necesita que alguien mire el reloj. El vigilante existe solo
   mientras hay vales: sin esperas no hay temporizador corriendo. */
function vigilarVales() {
  if (_relojVales || !_vales.size) return;
  _relojVales = setInterval(() => {
    if (!_vales.size) { clearInterval(_relojVales); _relojVales = null; return; }
    const ahora = Date.now();
    let vencio = false;
    _vales.forEach((v, k) => { if (v.vence <= ahora) { _vales.delete(k); vencio = true; } });
    if (vencio) pintarCargas();
  }, 1000);
}

/* Marca cada panel que este esperando algo. Es un atributo y no una clase
   porque la hoja lo lee con un selector de atributo, igual que el estado de
   ausencia: los dos son estados del panel y se leen juntos. */
function pintarCargas() {
  const activos = new Set();
  _vales.forEach(v => {
    if (v.fondo) return;
    v.claves.forEach(que => (PANELES_DE[que] || []).forEach(p => activos.add(p)));
  });
  document.querySelectorAll("[data-panel]").forEach(el => {
    el.dataset.cargando = activos.has(el.dataset.panel) ? "si" : "no";
  });
  // Los graficos no son un panel: son varios, y se marcan todos juntos.
  const graficos = activos.has("graficos");
  document.querySelectorAll(".grafico-chico").forEach(el => {
    el.dataset.cargando = graficos ? "si" : "no";
  });
}

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
    const error = new Error(typeof motivo === "string" ? motivo : JSON.stringify(motivo));
    /* El texto es para la persona; **el detalle es para el codigo**. Aplanarlo a
       una cadena obligaba a quien llama a leer el JSON del mensaje o a tratar
       todos los fallos igual, y hay fallos que no lo son: un 409 diciendo que la
       captura ya esta en curso es exactamente lo que se pidio. */
    error.estado = r.status;
    error.detalle = (d && d.detail) || null;
    throw error;
  }
  return d;
}

/* Una sesion que se cierra deja consultas en el aire. Dos problemas
   distintos: gastan una de las seis conexiones que el navegador da por origen
   ---justo las que necesita la sesion nueva--- y pueden llegar tarde y pisar
   lo que ya se dibujo. `senal` las corta. El corte por tiempo se agrega
   siempre: una consulta que no vuelve nunca es un panel esperando para
   siempre. */
async function pedir(ruta, opciones) {
  const o = opciones || {};
  const corte = new AbortController();
  /* QUIEN CORTO, Y POR QUE. Las dos cosas abortan con el mismo controlador, y
     desde el error se ven iguales: `AbortError`. Confundirlas costaba caro en
     los dos sentidos. Un corte por tiempo tomado por cancelacion no se anotaba
     como fallo, de modo que la reproduccion seguia creyendo que la vuelta venia
     en camino y la volvia a pedir en cada cuadro; una cancelacion tomada por
     fallo pintaria un error donde no lo hubo. Se anota cual de las dos fue. */
  let porTiempo = false;
  const reloj = setTimeout(() => { porTiempo = true; corte.abort(); },
                           o.limite_ms || LIMITE_ESPERA_MS);
  if (o.senal) {
    if (o.senal.aborted) corte.abort();
    else o.senal.addEventListener("abort", () => corte.abort(), { once: true });
  }
  try {
    return await pedirCrudo(ruta, corte.signal);
  } catch (e) {
    if (porTiempo && e && e.name === "AbortError") {
      const t = new Error("la consulta no contestó en " +
                          Math.round((o.limite_ms || LIMITE_ESPERA_MS) / 1000) + " s");
      t.name = "TiempoAgotado";
      t.porTiempo = true;
      throw t;
    }
    throw e;
  } finally {
    clearTimeout(reloj);
  }
}

/* Se anulo a proposito: no es un fallo y no se avisa como tal. El corte por
   tiempo no entra aca porque `pedir` ya lo convirtio en otro error: la
   distincion se hace en un solo sitio, donde se sabe quien aborto. */
function fueAnulada(e) {
  return !!e && e.name === "AbortError";
}

async function pedirCrudo(ruta, senal) {
  const r = await fetch(API + ruta, { headers: { "Accept": "application/json" }, signal: senal });
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
  /* Vueltas cuya consulta fallo, con el motivo. Distinto de «todavia no llego»
     y de «llego vacia»: sin esta marca, la reproduccion esperaria para siempre
     una vuelta que no va a venir. */
  fallo: {},
  posiciones: {},      // donde esta cada vehiculo, por vuelta
  pidiendoPos: {},
  disponibles: new Set(),   // que señales devolvio la fuente con dato
  vehiculoClave: null, // identificador del vehiculo del que hay telemetria
  cargando: false,
  motivo: "",          // por que no hay nada que mostrar
};

//: Cuantos puntos se piden por vuelta. La vuelta tiene unas 2.600 muestras y
//: el grafico mide trescientos pixeles: pedir mas es transferir para tirar.
const PUNTOS_POR_VUELTA = 300;

/* ============================================================
   CUANTO SE TRAE, Y CUANTO SE GUARDA
   ------------------------------------------------------------
   Mirar una vuelta y comparar una carrera son dos necesidades distintas, y
   pedirlas igual hace que una de las dos este mal.

   Con una vuelta se quiere resolucion: trescientos puntos sobre siete
   kilometros son unos veintitres metros por muestra, que alcanza para ver una
   frenada.

   Con la carrera entera no se quiere resolucion, se quiere **la forma**: donde
   se perdio tiempo, en que vuelta cambio el ritmo. Pedir veintidos vueltas a
   trescientos puntos son 6.600 puntos por señal y por vehiculo, y ademas
   chocaba de frente con la poda: la poda deja ocho vueltas, la comparacion
   pedia veintidos, y las que se expulsaban se volvian a pedir enseguida ---un
   ciclo de descargar y tirar que no termina nunca y que ademas no dibuja bien,
   porque en cada momento faltan catorce.

   Se resuelve declarando el presupuesto en vez de descubrirlo: **2.400 puntos
   por señal y vehiculo**, repartidos entre las vueltas que se vayan a mirar.
   Veintidos vueltas dan 109 puntos cada una, unos 64 m por muestra. Y la poda
   no toca lo que la comparacion esta usando.

   El detalle sigue disponible: al volver a una sola vuelta se la pide de nuevo
   a trescientos puntos, porque la respuesta declara con cuantos vino y una
   copia mas gruesa no se hace pasar por la fina.
   ============================================================ */
/* TRES COSAS DISTINTAS, QUE ANTES ERAN UNA.

   1. **Resolucion objetivo de la vista**: cuantos puntos por vuelta se piden
      para lo que se va a dibujar. Depende de cuantas vueltas entren en la
      pantalla, no de cuantas hay en la sesion.

   2. **Limite de almacenamiento de detalle**: cuantos puntos se guardan en
      total. Es un limite sobre la memoria, y se hace cumplir podando; sin eso
      un presupuesto es una intencion.

   3. **Representacion reducida de carrera**: la vista de carrera completa no
      guarda el detalle de cada vuelta, guarda cada vuelta a la resolucion que
      el presupuesto permite. Es otra cosa que el detalle, y por eso se
      declara aparte.

   EL DEFECTO QUE ESTO CORRIGE. `Math.max(60, floor(2400 / vueltas))` no acota:
   el piso de sesenta gana a la division y el total se dispara. Medido:

   | vueltas | puntos/vuelta | total | dentro de 2.400 |
   |---------|---------------|-------|------------------|
   |      22 |           109 | 2.398 | si               |
   |      40 |            60 | 2.400 | si               |
   |      60 |            60 | 3.600 | **no**, +1.200   |
   |     100 |            60 | 6.000 | **no**, +3.600   |

   Y no era un caso hipotetico: una carrera de F1 llega a setenta y ocho
   vueltas. El presupuesto estaba escrito como techo y no lo era. */
const PRESUPUESTO_DE_PUNTOS = 2400;

/* Piso absoluto por vuelta. Es lo que hace falta para que una vuelta siga
   siendo una linea y no dos puntos unidos: con veinte muestras sobre siete
   kilometros, cada una cubre 350 m, que alcanza para ver el ritmo de una
   vuelta ---que es lo que se compara en la vista de carrera--- y no para ver
   una frenada, que es lo que se mira vuelta por vuelta.

   Este piso si puede ganarle al presupuesto, y hay que decir cuando: por
   encima de 120 vueltas. Ninguna carrera de F1 llega ahi ---el maximo
   historico es 78--- pero la cifra queda escrita para que el limite sea
   comprobable en vez de suponerse. */
const PUNTOS_MINIMOS_POR_VUELTA = 20;
const VUELTAS_HASTA_ROMPER_EL_PRESUPUESTO =
  Math.floor(PRESUPUESTO_DE_PUNTOS / PUNTOS_MINIMOS_POR_VUELTA);

/* Cuantos puntos se guardan en total, sumando todas las vueltas cargadas. Es
   el presupuesto de la vista de carrera **mas** un conjunto de trabajo de
   vueltas en detalle: quien mira una carrera completa y ademas abre una vuelta
   en detalle tiene las dos cosas, y ninguna expulsa a la otra.

   Se expresa en puntos y no en vueltas porque una vuelta no ocupa siempre lo
   mismo: a 300 puntos ocupa quince veces lo que a 20. Contar vueltas dejaba
   pasar 8 x 300 = 2.400 puntos o 8 x 20 = 160, y llamaba «ocho» a las dos. */
const LIMITE_DE_DETALLE_PUNTOS =
  PRESUPUESTO_DE_PUNTOS + PUNTOS_POR_VUELTA * 4;
//: Cuantas consultas de series pueden estar en vuelo a la vez. El navegador
//: abre seis conexiones por origen; dejando tres para las series, las otras
//: tres quedan para el trazado, el contexto y las posiciones, que son las que
//: hacen falta para que la pantalla se dibuje.
const SERIES_A_LA_VEZ = 3;

/* La resolucion objetivo de la vista. El presupuesto manda; el piso solo se
   aplica cuando hay tantas vueltas que respetarlo dejaria menos de veinte
   muestras por vuelta, y en ese caso se sabe cuantas hacen falta para llegar
   ahi: `VUELTAS_HASTA_ROMPER_EL_PRESUPUESTO`. */
function puntosParaVueltas(cuantas) {
  if (cuantas <= 1) return PUNTOS_POR_VUELTA;
  const porPresupuesto = Math.floor(PRESUPUESTO_DE_PUNTOS / cuantas);
  if (porPresupuesto >= PUNTOS_POR_VUELTA) return PUNTOS_POR_VUELTA;
  return Math.max(PUNTOS_MINIMOS_POR_VUELTA, porPresupuesto);
}

/* Cuantos puntos ocupa lo que hay cargado. Se usa `puntos_pedidos` y no la
   longitud real porque es lo que la vuelta reservo: una vuelta pedida a 300
   ocupa el sitio de 300 aunque la fuente haya entregado 280. */
function puntosGuardados() {
  let total = 0;
  Object.keys(estado.series).forEach(n => {
    const b = estado.series[n];
    if (b) total += b.puntos_pedidos || PUNTOS_POR_VUELTA;
  });
  return total;
}

/* Corre las tareas de a `cuantas`, no todas juntas. `Promise.all` sobre
   veintidos vueltas pone veintidos consultas en vuelo; el navegador abre seis
   y las otras dieciseis hacen cola, de modo que la primera vuelta ---la que se
   va a dibujar antes--- termina esperando detras de las que no se ven. */
function enTandas(lista, cuantas, hacer) {
  const salida = new Array(lista.length);
  let siguiente = 0;
  const obrero = () => {
    if (siguiente >= lista.length) return Promise.resolve();
    const i = siguiente++;
    return Promise.resolve(hacer(lista[i], i))
      .then(r => { salida[i] = r; })
      .then(obrero);
  };
  const obreros = [];
  for (let i = 0; i < Math.min(cuantas, lista.length); i++) obreros.push(obrero());
  return Promise.all(obreros).then(() => salida);
}


/* ============================================================
   NO TODAS LAS FUENTES TIENEN EJE DE DISTANCIA
   ------------------------------------------------------------
   EL DEFECTO. La reproduccion historica va contra **distancia recorrida**: las
   vueltas se delimitan por metro, los graficos van contra metro y la ventana
   movil se corre sobre metros. El bus del vehiculo publica velocidad de rueda y
   no publica odometro ni distancia de vuelta, de modo que ese eje no existe
   para el.

   El transporte no lo miraba. Con una captura del bus abierta pedia la vuelta
   que hay bajo el cabezal como con cualquier otra fuente, la API contestaba 422
   ---correctamente--- y el tablero mostraba «La vuelta 1 no se pudo traer», con
   un motivo escrito para OpenF1 y un consejo de reintentar que no podia
   funcionar: la fuente no va a declarar distancia por intentarlo otra vez.

   Otros paneles ya se cuidaban ---la comparacion se apaga con `fuente !== "f1"`,
   el trazado dice «recorrido reconstruido»--- y este no. Ahora hay una sola
   declaracion de que fuentes tienen el eje, la compuerta la mira antes de
   pedir, y el reproductor dice por que no hay reproduccion en vez de fallar.

   QUE NO ES ESTO. No se inventa una distancia integrando la velocidad para que
   el eje aparezca. Se podria ---el recorrido del bus ya se reconstruye asi y se
   declara como reconstruccion--- y es otro trabajo, con su error acumulado
   dicho. Mientras tanto se dice que no hay, que es lo que hay.
   ============================================================ */

/* Que fuentes declaran distancia recorrida, y por que las otras no. El motivo
   viaja aca para poder escribirlo en el panel sin esperar a que la API falle. */
const EJE_DE_DISTANCIA_POR_FUENTE = {
  f1: { hay: true, porque: "" },
  openf1: { hay: false, porque:
    "el muestreo de 3,7 Hz deja huecos de hasta 83 m entre muestras, y sobre ese " +
    "eje dos puntos vecinos no son dos lugares vecinos del circuito" },
  can: { hay: false, porque:
    "el bus publica velocidad de rueda pero no odómetro ni distancia de vuelta: " +
    "no hay metro medido con el que ubicar una muestra en el circuito" },
};

function hayEjeDeDistancia(cual) {
  const d = EJE_DE_DISTANCIA_POR_FUENTE[cual === undefined ? fuente : cual];
  return !d || d.hay;
}

function porQueNoHayDistancia(cual) {
  const d = EJE_DE_DISTANCIA_POR_FUENTE[cual === undefined ? fuente : cual];
  return (d && d.porque) || "esta fuente no declara distancia recorrida";
}

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

/* Un texto que viene de afuera, puesto donde se arma marcado con cadenas.
   Los nombres de la parrilla los escribe el juego y llegan por un archivo de
   metadatos: son datos, no marcado, y no hay ninguna razon para que un
   `<img onerror=...>` en un nombre se ejecute en esta pagina. */
function textoSeguro(t) {
  return String(t === null || t === undefined ? "" : t)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

/* ============================================================
   QUIEN ES CADA VEHICULO: LA IDENTIDAD NO ES EL INDICE
   ------------------------------------------------------------
   EL DEFECTO. El marcador decia «19». Ese 19 es el **indice del vehiculo en
   el protocolo**: la posicion que ocupa en el arreglo de veinte que viaja en
   cada paquete. No es su numero de carrera ---que es el 4---, ni su puesto en
   la carrera, ni nada que identifique a nadie. El tablero lo mostraba porque
   `claveCorta` recorta el sufijo de la clave tecnica, y el sufijo era lo
   unico que habia.

   Y habia mas: el nombre estaba guardado desde el dia de la captura. El
   paquete de participantes declara NORRIS, numero 4, McLaren, y el capturador
   lo escribe en el metadato. Lo que faltaba era que cruzara a la consulta.

   COMO SE UNE. Por sesion, nunca por indice suelto. `/adquisiciones` devuelve
   la parrilla de **esa** sesion con la clave tecnica que le corresponde a cada
   participante; el tablero busca por esa clave y no por el numero del final.
   Dos capturas distintas tienen dos parrillas distintas aunque las dos
   numeren un `car:19`.

   SIN METADATO NO SE INVENTA. Un vehiculo que la parrilla no nombra se llama
   «Vehículo 19», que dice lo que es ---el indice interno--- y no se puede
   confundir con un numero de carrera.
   ============================================================ */

/* ============================================================
   LA IDENTIDAD VIVE ATADA A SU ALCANCE
   ------------------------------------------------------------
   EL DEFECTO. `PARRILLA` era una variable suelta y `nuevaSesionEnCurso()` la
   ponia en `null` para que una respuesta atrasada no pusiera nombres de otra
   sesion. Pero esa funcion tambien la llama `elegirCorrida`, que corre
   **despues** de que `/adquisiciones` contesto y sin volver a pedirla: elegir
   Carrera desde el elector borraba el nombre y ya no volvia. Abrir con el
   enlace completo funcionaba y abrir desde el catalogo no, que es exactamente
   el sintoma que se reporto.

   LA CORRECCION. Se separan dos cosas que estaban juntas: **anular consultas en
   vuelo** ---que es lo que hace `nuevaSesionEnCurso`--- y **saber a que alcance
   pertenece un nombre**. Lo segundo no necesita borrarse: se guarda con el
   alcance al que pertenece y se lee comprobandolo. Si el alcance vigente es
   otro, no hay identidad y se usa el respaldo; si vuelve a ser el mismo, el
   nombre esta.

   Y como `/adquisiciones` ahora declara una parrilla **por adquisicion**,
   cambiar de adquisicion no pierde nada: la elegida se resuelve leyendo la que
   corresponde. Cambiar de etapa tampoco, porque las etapas son de la misma
   captura y comparten participantes.
   ============================================================ */

/* Las parrillas que declaro `/adquisiciones`, con la sesion a la que
   pertenecen. `null` mientras no llego ninguna. */
let PARRILLAS = null;

function anotarParrillas(sessionId, adquisiciones) {
  const porClave = {};
  (adquisiciones || []).forEach(a => {
    const p = a && a.parrilla;
    if (p && p.disponible && Array.isArray(p.vehiculos)) porClave[a.clave] = p;
  });
  PARRILLAS = sessionId ? { sesion: sessionId, porClave: porClave } : null;
}

/* La parrilla del alcance que se esta mirando.

   Devuelve `null` ---y entonces nadie queda nombrado--- cuando lo guardado es
   de otra sesion, cuando la adquisicion elegida no declara la suya, y cuando no
   hay eleccion pero hay mas de una para elegir: con dos capturas que declaran
   gente distinta en el mismo indice, tomar cualquiera seria inventar. */
function parrillaVigente() {
  if (!PARRILLAS) return null;
  const abierta = estado.abierta && estado.abierta.session_id;
  if (!abierta || PARRILLAS.sesion !== abierta) return null;
  const porClave = PARRILLAS.porClave || {};
  if (corrida.adquisicion) return porClave[corrida.adquisicion] || null;
  const claves = Object.keys(porClave);
  return claves.length === 1 ? porClave[claves[0]] : null;
}

/* Cuantos vehiculos de este alcance tienen telemetria guardada. Es cobertura,
   no identidad: la parrilla puede nombrar veinte y la base tener uno. */
function vehiculosConTelemetriaGuardada() {
  const p = parrillaVigente();
  if (p && Number.isFinite(p.con_telemetria)) return p.con_telemetria;
  return AUTOS.length;
}

/* La identidad de un vehiculo, o el respaldo explicito si no se la conoce.

   `etiqueta` es lo que entra en la marca del circuito, donde hay sitio para
   tres letras; `completa` es lo que se lee en voz alta y lo que va al titulo
   accesible. Las dos salen del mismo sitio para que no puedan discrepar. */
function identidadDeVehiculo(clave) {
  const indice = claveCorta(clave);
  const parrilla = parrillaVigente();
  const declarado = parrilla
    ? parrilla.vehiculos.find(v => v.vehicle_id === clave)
    : null;
  if (!declarado || !declarado.nombre) {
    return {
      nombre: "Vehículo " + indice, numero: null, equipo: null, esIA: null,
      etiqueta: indice, completa: "Vehículo " + indice + ", índice interno del protocolo",
      declarada: false, indice: indice,
    };
  }
  const numero = Number.isFinite(declarado.numero) ? declarado.numero : null;
  const conNumero = declarado.nombre + (numero === null ? "" : " · #" + numero);
  return {
    nombre: declarado.nombre,
    numero: numero,
    equipo: declarado.equipo || null,
    esIA: typeof declarado.es_ia === "boolean" ? declarado.es_ia : null,
    /* Tres letras, en mayusculas, como los cronometrajes de television. Si el
       nombre es mas corto, va entero: recortar a lo que no hay no es un
       criterio. */
    etiqueta: declarado.nombre.slice(0, 3).toUpperCase(),
    completa: conNumero + (declarado.equipo ? " · " + declarado.equipo : ""),
    declarada: true, indice: indice,
  };
}

/* EL PROPIO NO ES EL PRIMERO DE LA LISTA.
   Cuando llegan las posiciones se rehace la lista con todos los vehiculos que
   publican posicion, y ordenada da «car:0» primero. Marcar a ese como propio
   cambiaba de quien se leen las señales, y como de el la fuente publica
   posicion pero no telemetria, el tablero se quedaba en blanco: los graficos
   decian «sin dato» y los medidores una raya.

   El propio es el vehiculo del que **hay serie**, que es el que la consulta de
   series devolvio primero. Si todavia no llego ninguna, el primero de la
   lista. */
function armarAutos(claves) {
  const tintas = ["--auto-1", "--auto-2", "--auto-3", "--auto-4"];
  const conTelemetria = estado.vehiculoClave;
  const anterior = AUTOS.find(a => a.propio);
  const propio = (conTelemetria && claves.indexOf(conTelemetria) !== -1) ? conTelemetria
               : (anterior && claves.indexOf(anterior.id) !== -1) ? anterior.id
               : claves[0];
  AUTOS = claves.map((c, i) => Object.assign({
    id: c,
    /* Lo que este vehiculo aporta al tablero ---telemetria o solo posicion---
       no es identidad y tiene su propio campo: mezclarlas era lo que hacia que
       el panel dijera «19 · telemetría completa», dos hechos de distinta
       naturaleza pegados con un punto. */
    aporta: c === propio ? "telemetría completa" : "solo posición en pista",
    tinta: tintas[i % tintas.length],
    color: "var(" + tintas[i % tintas.length] + ")",
    propio: c === propio,
  }, camposDeIdentidad(c)));
}

/* LOS CAMPOS QUE LA IDENTIDAD APORTA A UN VEHICULO, EN UN SOLO SITIO.
   Son dos los que los copian ---armar la lista y renombrarla--- y estaban
   escritos dos veces. Un campo agregado en `identidadDeVehiculo` y olvidado en
   uno de los dos es exactamente como `es_ia` dejo de llegar al rotulo: el
   tooltip leia `undefined`, que no es `null`, y afirmaba «conducido por una
   persona» de un vehiculo del que el metadato no dice nada. */
function camposDeIdentidad(clave) {
  const quien = identidadDeVehiculo(clave);
  return {
    nombre: quien.nombre,
    numero: quien.numero,
    etiqueta: quien.etiqueta,
    completa: quien.completa,
    equipo: quien.equipo,
    /* Nulable de punta a punta. `true` es maquina, `false` es persona y `null`
       es «el metadato no lo declara»: son tres estados y no dos. Deducirlo de
       la plataforma, del nombre o de que haya telemetria seria inventar quien
       tenia el control. */
    esIA: quien.esIA,
    identidadDeclarada: quien.declarada,
    indiceInterno: quien.indice,
  };
}

/* Lo que va debajo del nombre. El equipo cuando la parrilla lo declara ---es
   identidad, y es lo que se espera leer al lado de un piloto---; lo que el
   vehiculo aporta al tablero cuando no, que es lo unico que se puede afirmar
   sin metadato. */
function secundarioDeVehiculo(a) { return (a && a.equipo) || (a && a.aporta) || ""; }

/* La parrilla puede llegar despues de que la lista este armada ---son dos
   consultas y no hay orden garantizado---. Cuando llega, se renombra lo que ya
   esta **sin tocar las claves ni el propio**: la reproduccion no se reinicia
   por enterarse de un nombre. */
/* Sube cada vez que un vehiculo cambia de nombre. Entra en la firma del
   trazado: sin el, las marcas ya dibujadas se quedarian con el indice interno
   hasta que cambiara otra cosa. */
let _selloDeIdentidad = 0;

function renombrarAutos() {
  let cambio = false;
  AUTOS.forEach(a => {
    const campos = camposDeIdentidad(a.id);
    /* Se comparan **todos** los campos que se copian, no dos elegidos. La
       version anterior miraba el nombre y si estaba declarada: un vehiculo que
       cambiara solo de equipo o de control se quedaba con lo viejo. */
    if (Object.keys(campos).every(k => a[k] === campos[k])) return;
    Object.assign(a, campos);
    cambio = true;
  });
  if (cambio) _selloDeIdentidad++;
  return cambio;
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
  /* «Diferencia acumulada» no decia contra quien. La fuente publica dos
     diferencias ---al lider de la carrera y al coche de adelante--- y son
     numeros distintos: el rotulo nombra la que se dibuja. Viene en
     milisegundos y se muestra en segundos, convertida al entrar la respuesta. */
  { id: "gap", rotulo: "Diferencia al líder", unidad: "s", activa: true, fuentes: ["f1", "openf1"] },
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
  wheelRR: "wheel_speed_rear_right", gap: "delta_to_race_leader",
  /* LO QUE SE LEE Y NO SE DIBUJA.
     `METRICAS` es «los canales que el tablero sabe dibujar», y estos dos no son
     graficos: son el cronometraje. Ponerlos ahi habria agregado dos ejes que
     nadie pidio. Van en el contrato de nombres porque se leen igual que
     cualquier otra señal ---por el instante compartido--- y en `LECTURAS` para
     que la consulta los traiga. */
  cronometro: "current_lap_time", posicion: "track_position_order"
};

/* Señales que se leen para el cronometraje y no se grafican, con las fuentes
   que las declaran. La que manda sigue siendo la respuesta: si la fuente no
   las trae, el panel escribe una raya. */
const LECTURAS = [
  { id: "cronometro", fuentes: ["f1"] },
  { id: "posicion", fuentes: ["f1"] }
];

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

/* ============================================================
   LA UNIDAD LA DECLARA LA RESPUESTA, Y SE CONVIERTE UNA SOLA VEZ
   ------------------------------------------------------------
   EL DEFECTO. `delta_to_race_leader` se compone en el adaptador sumando la
   parte de minutos y la de milisegundos: son **milisegundos enteros**. El
   tablero lo imprimia crudo bajo un rotulo que decia «Al líder» y su grafico
   declaraba segundos. Los 2.937 ms de una diferencia real se leian como
   «2937.000», que no es un tiempo de carrera en ninguna unidad.

   POR QUE NO ALCANZA CON DIVIDIR POR MIL. En la misma respuesta viajan
   `penalty_time` y `safety_car_delta`, que **ya estan en segundos**: una lista
   de nombres escrita a mano que dividiera «los canales de tiempo» los rompe a
   los dos. Y una fuente nueva puede publicar mañana un canal parecido en otra
   unidad.

   LA CORRECCION. `/series` declara la unidad de cada señal, tomada de las
   mismas filas de las que sale el valor. El tablero convierte **una vez**, al
   entrar la respuesta, y solo cuando el par de unidades es uno que conoce. Lo
   que no sabe convertir lo deja como vino y lo sigue declarando como vino, de
   modo que quien lo muestra puede decir que no lo sabe en vez de mentir la
   unidad.

   QUE NO SE TOCA. Lo persistido y las exportaciones crudas siguen en su unidad
   de origen: esto es el limite de presentacion, no la base.
   ============================================================ */

/* En que unidad muestra el tablero cada señal que no se muestra como viene.
   Las que no figuran se muestran tal cual. */
const UNIDAD_QUE_MUESTRA_EL_TABLERO = {
  delta_to_race_leader: "s",
  delta_to_car_in_front: "s",
  current_lap_time: "s"
};

/* Por cuanto hay que **dividir** para pasar de la unidad de la izquierda a la
   de la derecha. Un par que no este aca no se convierte con un numero supuesto.

   SE GUARDA COMO DIVISOR Y NO COMO FACTOR, y no es un detalle de estilo:
   `2937 * 0.001` da 2,9370000000000003 en coma flotante binaria y `2937 / 1000`
   da 2,937. La cola aparece en pantalla en cuanto alguien muestre el numero sin
   redondear. */
const DIVISOR_ENTRE_UNIDADES = { "ms|s": 1000 };

/* Por cuanto dividir para llevar `senal` de la unidad `declarada` a la que se
   muestra. `1` si ya coinciden o si la señal se muestra como viene; `null` si
   hay que convertirla y el par no se conoce, que es distinto de no tener que
   hacerlo. */
function divisorDeUnidad(senal, declarada) {
  const destino = UNIDAD_QUE_MUESTRA_EL_TABLERO[senal];
  if (!destino) return 1;
  if (!declarada || declarada === destino) return declarada === destino ? 1 : null;
  const d = DIVISOR_ENTRE_UNIDADES[declarada + "|" + destino];
  return d === undefined ? null : d;
}

/* ============================================================
   LA CONVERSION ES UNA VISTA, NO UNA REESCRITURA
   ------------------------------------------------------------
   LA PRIMERA VERSION CONVERTIA EL BLOQUE GUARDADO, y de ahi salieron tres
   incoherencias distintas.

   UNA. El vivo no tiene bloque. `calcularInstante` convertia el mensaje con la
   unidad del propio mensaje ---bien--- y el panel preguntaba «¿esta en
   segundos?» a `estado.series`, que en vivo esta vacio a proposito: contestaba
   que no y el panel escribia una raya sobre un valor correcto. El grafico, que
   no preguntaba nada, dibujaba los 2.937 ms crudos bajo un eje que decia
   segundos.

   DOS. En historico con una unidad que no se sabe convertir pasaba lo
   contrario: el panel rechazaba el valor y los graficos y la comparacion lo
   dibujaban igual, bajo la unidad fija que declara `METRICAS`.

   TRES. Reescribir el bloque cambiaba lo exportado. El CSV sale de las mismas
   series y paso a decir 2,937 donde la base guarda 2937, sin que nadie lo
   pidiera.

   LA REGLA, UNA SOLA. **Lo que llega se guarda como llego** ---valores y
   unidades--- y la conversion vive en los accesos de presentacion: las series
   que se dibujan y las lecturas del instante. La unidad declarada se busca
   donde viva segun el modo: el bloque de la vuelta en historico, el ultimo
   mensaje en vivo. Si no se puede llevar a la unidad que se muestra, no se
   muestra ---ni numero ni curva--- y se dice por que.
   ============================================================ */

/* En que unidad llega una señal ahora mismo. En vivo la declara cada mensaje;
   en historico, la respuesta de la vuelta. `null` mientras no se sepa: quien la
   muestre escribe una raya y no supone. */
function unidadDeclaradaDe(senal, vuelta, clave) {
  if (estadoSesion === "vivo") {
    const ultimos = vivo.ultimos.get(clave || claveVehiculoPropio());
    const m = ultimos && ultimos.get(senal);
    return (m && m.unit) || null;
  }
  const bloque = estado.series[vuelta];
  const u = bloque && bloque.unidades && bloque.unidades[senal];
  return u || null;
}

/* Por cuanto dividir lo que trae `canal` para mostrarlo. `1` cuando se muestra
   tal cual; `null` cuando hay que convertirlo y no se sabe con que. */
function divisorDePresentacion(canal, vuelta, clave) {
  const senal = nombreDeSenal(canal);
  if (!UNIDAD_QUE_MUESTRA_EL_TABLERO[senal]) return 1;
  return divisorDeUnidad(senal, unidadDeclaradaDe(senal, vuelta, clave));
}

/* Si lo que se lee de `canal` se puede mostrar en la unidad que el rotulo
   declara. Sirve para el numero y para la curva, que es el punto: antes uno
   preguntaba y la otra no. */
function estaEnLaUnidadQueSeMuestra(canal, vuelta, clave) {
  return divisorDePresentacion(canal, vuelta, clave) !== null;
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
      // Encender el capturador es el acto explicito que pone a este tablero a
      // seguir el flujo. Sin eso, el objetivo queda sin fijar.
      : { ruta: "/captura/iniciar", metodo: "POST", cuerpo: { parrilla_completa: true }, sigueVivo: true,
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
      /* Encender la captura es pedir seguir la sesion que se cree. Todavia no
         se sabe cual es ---el capturador la nombra al recibir el primer
         paquete--- asi que se habilita adoptar la proxima y fijarla. */
      if (a.sigueVivo) { vivo.objetivo = null; vivo.aceptaNueva = true; vivo.pedida = true; vivo.otra = null; }
      avisar(a.hecho(d) + (a.sigueVivo ? " · " + esperaDeTelemetria() : ""), false);
      /* EL CATALOGO NO ESTA LISTO CUANDO LA RESPUESTA VUELVE.
         Detener una captura refresca la sesion recien grabada **por detras**:
         recontarla lleva segundos. Pedir el catalogo una sola vez, aca mismo,
         devolvia la lista de antes ---sin la sesion nueva--- y el tablero se
         quedaba con esa. Ocurrio el 2026-09-09: Suzuka tenia 481.355 filas en
         la base y no aparecia en «sesiones guardadas», de modo que no habia
         forma de abrirla. Se vuelve a pedir hasta que la lista deje de
         cambiar, con techo: si no cambia, no se insiste. */
      refrescarCatalogo(6);
      vigilarEnVivo();
    })
    .catch(e => {
      /* «Ya hay un trabajo de la misma familia en curso» **no es un error para
         quien pulso escuchar**: la captura esta corriendo, que es lo que queria.
         Tratarlo como fallo dejaba el tablero en la sesion que estuviera
         reproduciendo, mostraba el JSON crudo del trabajo, y el boton seguia
         diciendo «Empezar a escuchar» ---de modo que volver a pulsarlo repetia
         el mismo error---. Se cayo en eso tres veces el 2026-09-09.

         Se adopta el flujo igual que en el camino feliz, y se dice desde cuando
         viene escuchando, que es el dato que faltaba para entender que no hacia
         falta hacer nada. */
      const enCurso = e.estado === 409 && e.detalle && e.detalle.trabajo_en_curso;
      if (a.sigueVivo && enCurso && enCurso.familia === "captura") {
        vivo.objetivo = null; vivo.aceptaNueva = true; vivo.pedida = true; vivo.otra = null;
        avisar("Ya estaba escuchando" +
               (enCurso.duracion_s ? " desde hace " + Math.round(enCurso.duracion_s) + " s" : "") +
               ". Se sigue esa captura. " + esperaDeTelemetria(), false);
        vigilarEnVivo();
        render();
        return;
      }
      avisar(e.message, true);
    })
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
const SIN_VEHICULO = { id: null, nombre: "—", numero: null, etiqueta: "—",
                       completa: "sin vehículo", identidadDeclarada: false,
                       indiceInterno: null, equipo: null, esIA: null, aporta: "",
                       tinta: "--auto-1", color: "var(--auto-1)", propio: true };

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
    '<option value="' + textoSeguro(a.id) + '"' + (a.id === actual ? " selected" : "") + '>' +
    textoSeguro(a.completa) + '</option>').join("");
}

(function mandoDePropio() {
  const s = document.getElementById("sel-propio");
  if (!s) return;
  s.addEventListener("change", () => elegirPropio(s.value));
})();

function pintarAutos() {
  poblarPropio();
  const enParrilla = (parrillaVigente() || { vehiculos: [] }).vehiculos.length;
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
      '<span class="nombre">' + textoSeguro(a.nombre) +
        (a.numero === null || a.numero === undefined ? ""
          : '<span class="dorsal">#' + textoSeguro(a.numero) + "</span>") +
        '<small>' + textoSeguro(secundarioDeVehiculo(a)) + '</small></span>' +
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
    /* UN SOLO VEHICULO CON TELEMETRIA NO ES UNA SESION SIN PARRILLA.
       El titulo decia «la captura del bus es de un solo vehículo» cada vez que
       habia uno solo, tambien en una carrera de veinte contra veinte de la que
       se guardo la telemetria de uno. Son dos motivos distintos y ahora se
       distinguen por lo que la parrilla declara, no por cuantas series hay. */
    panelAutos.title = AUTOS.length > 1
      ? "De los rivales se muestra cronometraje; la telemetría privada, solo del propio. La fuente entrega de todos lo mismo, y mostrarlo enseñaría un procedimiento que en un vehículo real no se puede ejecutar."
      : (enParrilla > 1
          ? "La sesión declara " + enParrilla + " participantes y se guardó la telemetría de uno: se conocen sus nombres, no sus señales."
          : "Esta fuente entrega un solo vehículo: comparar entre autos no aplica.");
  }
  /* DOS CIFRAS QUE NO SON LA MISMA. Cuantos vehiculos tienen telemetria
     guardada, y cuantos declara la parrilla. Antes se mostraba una sola y se
     leia como si fueran las dos. */
  document.getElementById("canal-autos").textContent = AUTOS.length
    ? ((AUTOS.length === 1 ? "1 con telemetría" : AUTOS.length + " con telemetría") +
       (enParrilla ? " · " + enParrilla + " en parrilla" : ""))
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
    /* De donde sale el dibujo. Un recorrido a medio medir y un circuito
       completo se ven parecidos y no son lo mismo: el primero termina donde va
       el coche y el segundo cierra. */
    if (PISTA.enConstruccion) partes.push("recorrido en construcción, medido en vivo");
    else if (PISTA.medidoEnVivo) partes.push("medido en vivo, primera vuelta cerrada");
    /* Si la marca del vehiculo se esta dibujando entre dos muestras, se dice.
       Es una representacion y no una medicion: el dato guardado y lo que se
       exporta siguen siendo las muestras, sin tocar. */
    if (_huboInterpolacion) partes.push("posición interpolada entre muestras");
    cabPista.textContent = partes.join(" · ");
  } else if (estadoSesion === "vivo") {
    /* En vivo, sin trazado todavia, la espera tiene una razon concreta y un
       final: se esta midiendo. Decir «sin trazado» a secas se leeria como que
       la fuente no lo publica, que es otra cosa. */
    const clave = claveVehiculoPropio();
    const n = (clave && vivo.recorrido.get(clave) || []).length;
    cabPista.textContent = n
      ? "midiendo el recorrido: " + cifra(n, 0) + " posiciones"
      : "esperando la primera posición del vehículo";
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
    rotulo + ': ' + escrito + ' ' + unidad + '">' +
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
  /* Se anuncia lo mismo que se escribe. Con el valor sin medir, `valor` es
     `null` y esto decia «Marcha: null de 8»: quien lo lee con un lector de
     pantalla recibia una palabra del lenguaje en vez de una ausencia. */
  if (svg) svg.setAttribute("aria-label", rotulo + ": " + escrito + " " + unidad);
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
  const huella = _estelaG(t.vuelta);
  const pts = huella.puntos;
  const estela = document.getElementById("estela-g");
  const firmaEstela = pts.length + "|" + pts[pts.length - 1].join(",");
  if (estela.dataset.firma !== firmaEstela) {
    estela.dataset.firma = firmaEstela;
    estela.setAttribute("d", "M" + pts.map(p => p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" L"));
  }
  /* EL PUNTO VA EN LA ACELERACION DEL INSTANTE, NO EN UN INDICE DE LA ESTELA.
     La estela se dibuja con ochenta puntos ---uno de cada tantos, para que el
     trazo no sea una mancha---, y el punto se colocaba redondeando la fraccion
     de vuelta sobre esos ochenta: ochenta posiciones para una vuelta de dos
     minutos son 1,6 s de escalon, y el punto daba saltos mientras el coche se
     movia. Ahora se coloca con las dos aceleraciones que ya trae el instante
     compartido, interpoladas como el resto de los instrumentos. La escala es la
     misma de la estela, para que el punto y el trazo hablen del mismo dibujo.

     La estela esta decimada y puede haber perdido el pico: si el valor del
     instante se sale del recuadro, se lo sujeta al borde en vez de dibujarlo
     fuera del panel. */
  const punto = document.getElementById("punto-g");
  const halo = document.getElementById("halo-g");
  if (punto && halo) {
    let cx, cy;
    const gx = t.gLat, gy = t.gLong;
    if (typeof gx === "number" && Number.isFinite(gx) &&
        typeof gy === "number" && Number.isFinite(gy)) {
      const norm = v => Math.max(-1, Math.min(1, v / huella.maximo));
      cx = 90 + norm(gx) * 68;
      cy = 90 - norm(gy) * 68;
    } else {
      const idx = Math.min(pts.length - 1,
                           Math.max(0, Math.round(t.fraccion * (pts.length - 1))));
      cx = pts[idx][0];
      cy = pts[idx][1];
    }
    punto.setAttribute("cx", cx.toFixed(2));
    punto.setAttribute("cy", cy.toFixed(2));
    halo.setAttribute("cx", cx.toFixed(2));
    halo.setAttribute("cy", cy.toFixed(2));
  }
}

/* El punto recorre la estela. Es la unica animacion por temporizador de la
   vista, y se apaga si la persona declaro preferir movimiento reducido. */
function _estelaG(vuelta) {
  const longitudinal = serieDeCanal("glong", vuelta, claveVehiculoPropio()) || [];
  const lateral = serieDeCanal("glat", vuelta, claveVehiculoPropio()) || [];
  const n = Math.min(longitudinal.length, lateral.length);
  if (!n) return { puntos: [[90, 90]], maximo: 1 };
  const valores = [];
  const paso = Math.max(1, Math.floor(n / 80));
  for (let i = 0; i < n; i += paso) valores.push([Number(lateral[i][1]), Number(longitudinal[i][1])]);
  const maximo = Math.max(1, ...valores.flat().map(Math.abs));
  /* Se devuelve tambien la escala: el punto del instante se coloca con las
     aceleraciones interpoladas y tiene que caer en el mismo dibujo que la
     estela, no en uno normalizado aparte. */
  return {
    puntos: valores.map(p => [90 + (p[0] / maximo) * 68, 90 - (p[1] / maximo) * 68]),
    maximo: maximo,
  };
}

/* Cuanto se deja alrededor del recorrido al encuadrarlo. A los costados y
   abajo alcanza con el radio de la marca del vehiculo y los circulos numerados
   de las curvas. */
const MARGEN_DEL_TRAZADO = 10;

/* Arriba hace falta mas, y por una razon concreta: el rotulo del vehiculo se
   dibuja `ALTURA_DEL_ROTULO` por encima de su marca y sus mayusculas suben otro
   tanto desde la linea base. Con el mismo margen que a los costados, el nombre
   se cortaba cada vez que el coche pasaba por el punto mas alto del circuito;
   en Spa eso es la recta de Kemmel, que se recorre entera y a fondo. */
const ALTURA_DEL_ROTULO = 10;
const CUERPO_DEL_ROTULO = 9.5;

/* CUANTO SUBE LA TINTA DEL ROTULO, MEDIDO Y NO SUPUESTO.
   El primer intento reservo `cuerpo x 0,8`, que es la altura de las mayusculas
   de IBM Plex Mono. No alcanzo: la caja de un texto llega hasta la
   **ascendente** de la fuente, que en esta es 1,025 del cuerpo, y el rotulo
   seguia cortandose 2,25 unidades. Un segundo factor escrito a mano seria la
   misma clase de suposicion, y ademas depende de que la fuente pedida haya
   cargado: si no, manda la de respaldo, con otras metricas.

   Se mide una vez sobre el rotulo de verdad, ya dibujado, y con eso se vuelve a
   encuadrar. Hasta que haya algo que medir se usa una cota amplia, de modo que
   el primer cuadro tampoco se corta. */
let _ascendenteDelRotulo = null;

/* Y se vuelve a medir cuando terminan de cargar las fuentes. La primera medida
   puede caer mientras IBM Plex Mono todavia viaja, y entonces se midio la de
   respaldo del sistema; cuando la pedida llega, sus metricas son otras y la
   reserva calculada con las anteriores puede quedar corta. Es una sola medicion
   mas, y solo si la pagina llego a dibujar antes que la fuente. */
if (typeof document !== "undefined" && document.fonts && document.fonts.ready) {
  document.fonts.ready.then(() => { _ascendenteDelRotulo = null; }).catch(() => {});
}

function reservaDeArriba(svg) {
  if (_ascendenteDelRotulo === null && svg) {
    const t = svg.querySelector(".auto-en-pista text");
    const caja = t && t.getBBox();
    const y = t && Number(t.getAttribute("y"));
    if (caja && caja.height > 0 && Number.isFinite(y)) {
      _ascendenteDelRotulo = y - caja.y;
    }
  }
  const sube = _ascendenteDelRotulo === null
    ? CUERPO_DEL_ROTULO * 1.3   // caja entera: cota, no medida
    : _ascendenteDelRotulo;
  return Math.ceil(ALTURA_DEL_ROTULO + sube);
}

/* Encuadra el recorrido en su caja, dejando arriba sitio para el rotulo.
   Se rehace solo cuando la reserva cambia ---al medirla por primera vez--- y no
   en cada cuadro: mover el `viewBox` sesenta veces por segundo haria temblar
   todo el dibujo. */
function encuadrarTrazado(svg, linea) {
  if (!svg) return;
  const reserva = reservaDeArriba(svg);
  if (svg.dataset.reserva === String(reserva)) return;
  const caja = linea.getBBox();
  if (!(caja.width > 0 && caja.height > 0)) return;
  svg.setAttribute("viewBox",
    (caja.x - MARGEN_DEL_TRAZADO) + " " + (caja.y - reserva) + " " +
    (caja.width + MARGEN_DEL_TRAZADO * 2) + " " +
    (caja.height + reserva + MARGEN_DEL_TRAZADO));
  svg.dataset.reserva = String(reserva);
}

/* EN QUE METRO DE LA VUELTA ESTA UNA CURVA.
   El catalogo lo publica como `metro_medido` ---«metro: medido sobre la
   vuelta», dice su propio campo `origen`--- y cuatro sitios lo leian como
   `cu.metro`, que no existe. `undefined < d0` es `false` y `undefined > d1`
   tambien, de modo que ninguna curva se descartaba por estar fuera del tramo y
   todas terminaban en `x = NaN`: el navegador no dibuja nada con NaN y no se
   queja. La vista de comparacion y las dos exportaciones de imagen quedaron sin
   una sola marca de curva, en silencio.

   Se lee en un solo sitio para que no vuelva a haber cuatro copias de un nombre
   de campo. `null` si el catalogo no lo declara: una curva sin metro no se
   puede ubicar en un eje de metros y se omite. */
function metroDeCurva(cu) {
  const m = cu && (cu.metro_medido !== undefined ? cu.metro_medido : cu.metro);
  return Number.isFinite(m) ? m : null;
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
  encuadrarTrazado(svg, linea);

  /* SIN RECORRIDO NO HAY DONDE UBICAR A NADIE.
     El trazado llega despues que la sesion ---hay que saber que vueltas hay
     para elegir una sin saltos---, de modo que este panel se dibuja al menos
     una vez con el camino vacio. Preguntarle un punto a un camino vacio lanza,
     y esa excepcion caia dentro de una promesa que la absorbia. */
  const largo = PISTA.path ? linea.getTotalLength() : 0;
  const g = document.getElementById("marcas-pista");
  if (!largo) { g.innerHTML = ""; g.dataset.firma = ""; return; }
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
                 _selloDeIdentidad,
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
      t.setAttribute("font-family", "IBM Plex Mono, monospace");
      /* TRES LETRAS EN LA PISTA, LA IDENTIDAD ENTERA AL ALCANCE.
         Sobre el trazado hay sitio para una etiqueta corta y para nada mas: el
         nombre completo con su numero y su equipo taparia la curva de al lado.
         Va en el `<title>`, que es lo que lee un lector de pantalla y lo que
         aparece al detener el puntero encima: acortar lo que se ve no es lo
         mismo que perder lo que se sabe. */
      t.textContent = a.etiqueta;
      t.setAttribute("font-size", String(a.propio ? CUERPO_DEL_ROTULO : 8));
      const comoSeLlama = document.createElementNS(NSV, "title");
      comoSeLlama.textContent = a.completa;
      grupo.appendChild(comoSeLlama); grupo.appendChild(c); grupo.appendChild(t);
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
  TESTIGO.pintadosDePista++;
  let seMovio = false;
  marcas.forEach((grupo, i) => {
    let frac = f;
    const clave = grupo.dataset.clave;
    /* LA FRACCION DE TIEMPO NO ES UNA POSICION.
       Sin posicion medida, la marca se colocaba en la fraccion **temporal** de
       la vuelta: a la mitad del tiempo, a la mitad del circuito. Un coche no
       recorre el circuito a ritmo parejo ---en Spa, la recta de Kemmel y la
       chicana del bus no se hacen a la misma velocidad--- de modo que ese punto
       no es donde esta, y al llegar la primera posicion medida la marca salta.

       No se quita la capacidad: una fuente que no publique posicion sigue
       mostrando por donde va la vuelta. Pero se declara ---`data-estimada`--- y
       se dibuja distinto, porque una posicion supuesta y una medida no pueden
       verse igual. */
    const medida = enPistaAhora && enPistaAhora[clave] !== undefined;
    if (medida) {
      frac = Math.max(0, Math.min(1, enPistaAhora[clave] / largoVuelta));
    }
    if (grupo.dataset.estimada !== (medida ? "no" : "si")) {
      grupo.dataset.estimada = medida ? "no" : "si";
      grupo.setAttribute("aria-label", medida ? "" : "posición estimada por tiempo, no medida");
    }
    /* MIENTRAS SE MIDE EL RECORRIDO, EL COCHE VA POR SU POSICION.
       El camino dibujado se rehace cada veinticinco puntos ---rehacerlo en cada
       uno recalcula la orientacion de la nube y el dibujo salta---, pero la
       posicion del vehiculo es un dato que llega veinte veces por segundo y no
       tiene por que esperar al dibujo. Se la proyecta con la misma
       transformacion del camino vigente. */
    let p = null;
    if (PISTA.enConstruccion && PISTA.proyectarMundo) {
      const suyo = vivo.recorrido.get(clave);
      if (suyo && suyo.length) {
        const ult = suyo[suyo.length - 1];
        const q = PISTA.proyectarMundo(ult[0], ult[1]);
        p = { x: q[0], y: q[1] };
      }
    }
    if (!p) p = linea.getPointAtLength(largo * frac);
    /* Por etiqueta y no por posicion: el grupo lleva ademas un `<title>` con la
       identidad completa, y `firstChild` dejo de ser el circulo el dia que se
       agrego. Buscar por lo que cada nodo es no se rompe al agregar otro. */
    const c = grupo.querySelector("circle"), t = grupo.querySelector("text");
    /* DOS DECIMALES, NO UNO.
       Medido sobre el trazado de Spa: el dibujo se escala a 0,0976 unidades por
       metro, asi que **una decima de unidad son 1,02 m de pista**. A 55,3 m/s
       de media el coche recorre 0,92 m en un cuadro de 16,7 ms: menos que un
       escalon. La marca avanzaba entonces cero o un escalon por cuadro, en un
       patron irregular que se ve como un temblor. Con dos decimales el escalon
       es de 0,10 m, la novena parte de lo que se mueve en un cuadro. */
    const px = p.x.toFixed(2), py = p.y.toFixed(2);
    /* Se compara contra lo que el elemento ya tenia. Escribir el mismo valor
       no mueve nada, y contar ese pintado como movimiento es justo el error
       que este testigo existe para no cometer. */
    /* Un pintado que no mueve la marca no es una posicion perdida: casi
       siempre es que se pinto mas veces de las que llegaron posiciones. Se
       cuenta como lo que es ---pintados sin cambio--- y no como redondeo, que
       era una atribucion sin medir. */
    if (c.getAttribute("cx") !== px || c.getAttribute("cy") !== py) seMovio = true;
    else TESTIGO.pintadosSinCambio++;
    c.setAttribute("cx", px); c.setAttribute("cy", py);
    t.setAttribute("x", px);
    t.setAttribute("y", (p.y - ALTURA_DEL_ROTULO).toFixed(2));
  });
  if (seMovio) TESTIGO.movimientosDeCoche++;
  /* Con los rotulos ya colocados hay algo que medir: si la reserva de arriba
     resulta ser otra, se vuelve a encuadrar. Pasa una sola vez por dibujo. */
  encuadrarTrazado(linea.ownerSVGElement, linea);
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
/* `cerrar` en falso deja el camino abierto. Hace falta para el recorrido que
   se esta construyendo: cerrarlo dibujaria una cuerda recta desde el ultimo
   punto medido hasta el primero, y esa linea **no se recorrio**. Es la
   diferencia entre un circuito y un tramo. */
function trazadoAPath(puntos, invertirY, cerrar) {
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
  /* La misma transformacion, pero desde coordenadas del mundo. Hace falta para
     poder ubicar un punto **que todavia no esta en el camino dibujado**: en
     vivo el coche va por delante del trazo, que se rehace cada tantos puntos.
     Sin esto, la marca solo se movia cuando se redibujaba el camino entero, y
     eso son menos de dos veces por segundo. */
  const proyectarMundo = (px, py) => {
    const dx = px - mx, dy = (py - my) * (invertirY ? -1 : 1);
    return proyectar([dx * cos - dy * sen, dx * sen + dy * cos]);
  };

  const d = giro.map((p, i) => {
    const q = proyectar(p);
    return (i === 0 ? "M" : "L") + q[0].toFixed(1) + " " + q[1].toFixed(1);
  }).join(" ") + (cerrar === false ? "" : " Z");
  return { path: d, proyectar: proyectar, proyectarMundo: proyectarMundo };
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
  METRICAS.concat(LECTURAS).forEach(m => {
    if (m.fuentes.indexOf(fuente) === -1) return;
    const n = nombreDeSenal(m.id);
    if (vistas.indexOf(n) === -1) vistas.push(n);
  });
  return vistas;
}

/* ============================================================
   EL ALCANCE: QUE ADQUISICION Y QUE FASE SE ESTA MIRANDO
   ------------------------------------------------------------
   Un `session_id` sale del identificador que el juego le da a la sesion, de
   modo que **volver a capturarla produce filas con el mismo identificador**. En
   `f1_25:session:3731090176871608020` conviven tres adquisiciones: la carrera
   original del 5 de septiembre y dos pruebas de parrilla del 8.

   Juntas, la vuelta 1 abarca tres dias y `/posiciones` reparte 260.454 s en
   doscientos cubos ---mil trescientos segundos cada uno--- mientras el
   reproductor recorre 283. El coche no se mueve, y no porque el tablero este
   mal: porque le estan dando tres carreras como si fueran una.

   Ademas, dentro de la original el reloj del juego se reinicia en la largada.
   Las fases ---formacion, espera de luces, carrera--- se solapan en UTC, y solo
   el reloj monotonico de captura las separa.

   Este alcance viaja en **todas** las consultas de datos. Filtrar unas si y
   otras no seria peor que no filtrar: el tablero mostraria la traza de una
   adquisicion sobre las posiciones de otra.
   ============================================================ */
const corrida = { adquisicion: null, fase: null, disponibles: null, mezclada: false };
/* Con que se vuelve a abrir el elector. Elegir no es un acto unico: la primera
   eleccion se hace sin haber visto nada, y lo normal es querer cambiarla
   despues ---mirar la formacion, volver a la carrera---. Se guarda lo que hace
   falta para volver a preguntar sin reabrir la sesion entera. */
let _contextoDeCorrida = null;

/* La cadena que se agrega a cada consulta. Vacia mientras no haya eleccion, que
   es el comportamiento de siempre. */
function sufijoDeCorrida(yaTieneParametros) {
  const partes = [];
  if (corrida.adquisicion) partes.push("adquisicion=" + encodeURIComponent(corrida.adquisicion));
  if (corrida.fase) partes.push("fase=" + corrida.fase);
  if (!partes.length) return "";
  return (yaTieneParametros ? "&" : "?") + partes.join("&");
}

function claveVehiculoPropio() { return estado.vehiculoClave; }

/* ============================================================
   UN NUMERO MEDIDO, O NADA
   ------------------------------------------------------------
   `Number(null)`, `Number("")` y `Number(false)` valen **cero**, y cero es un
   valor legitimo de casi todos estos canales: el freno suelto marca cero, la
   distancia marca cero al cruzar la linea. Convertir con `Number` a secas mete
   ceros que nadie midio justo donde no se distinguen de los medidos ---y una
   distancia falsa en cero no ensucia un punto: reubica todas las muestras que
   vengan detras.

   Un booleano si es una medicion: es una bandera, y vale 1 o 0 por definicion
   de la fuente, no por conversion.
   ============================================================ */
function numeroMedido(v) {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v === "boolean") return v ? 1 : 0;
  if (typeof v === "string") {
    const t = v.trim();
    if (!t) return null;
    const n = Number(t);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

/* De quien hay traza para dibujar. En vivo sale del flujo; con una sesion
   guardada, de la vuelta que se trajo. Preguntarselo siempre al historico
   dejaba los graficos en blanco durante una sesion en vivo, que es cuando la
   fuente esta entregando dato. */
function vehiculosConTraza() {
  if (estadoSesion === "vivo") return [...vivo.series.keys()];
  return Object.keys((estado.series[vueltaElegida] || {}).vehiculos || {});
}

/* Hasta donde llega el eje horizontal, mirando **todas** las listas que se van
   a dibujar. Se tomaba de la primera, y de ahi salian dos errores: con el
   primer vehiculo mas corto que el segundo se recortaba al segundo, y sin
   velocidad la primera lista medía cero y no se dibujaba nada de nada. */
function extremosDeDistancia(listas) {
  let a = Infinity, b = -Infinity;
  for (let i = 0; i < listas.length; i++) {
    const l = listas[i];
    for (let j = 0; j < l.length; j++) {
      const x = l[j][0];
      if (typeof x !== "number" || !Number.isFinite(x)) continue;
      if (x < a) a = x;
      if (x > b) b = x;
    }
  }
  return (Number.isFinite(a) && Number.isFinite(b)) ? [a, b] : null;
}

/* ============================================================
   REDUCIR PARA DIBUJAR SIN BORRAR LOS PICOS
   ------------------------------------------------------------
   Un lienzo de 240 px no puede mostrar 2.500 muestras: sobran diez por
   columna. Dibujarlas todas no es mas fiel, es mas lento y ademas engaña, y
   quedarse con una de cada diez ---que es lo que hace un muestreo uniforme---
   puede borrar justo el pico de una muestra, que es lo que una anotacion
   señala. Un bloqueo de rueda dura milisegundos.

   Por columna de pixel se conservan el minimo y el maximo de lo que cae ahi.
   Cuesta lo mismo que quedarse con uno y **no puede perder un extremo**: si
   hubo un pico en esa columna, esta. El trazo pasa a tener un tramo vertical
   donde el dato oscila, que es lo que de verdad ocurrio.

   Se aplica solo cuando hay mas muestras que pixeles. Con menos, la serie se
   dibuja tal cual y esto no interviene.
   ============================================================ */
function reducirAAncho(serie, ini, fin, ancho) {
  const columnas = Math.max(1, Math.floor(ancho));
  if (serie.length <= columnas * 2) return serie;
  const largo = fin - ini;
  if (!(largo > 0)) return serie;

  const salida = [];
  let col = -1, mn = null, mx = null, xMn = 0, xMx = 0;
  const cerrar = () => {
    if (mn === null) return;
    // Se emiten en el orden en que ocurrieron, para que el trazo no invierta
    // el sentido de la oscilacion.
    if (xMn <= xMx) { salida.push([xMn, mn]); if (xMx !== xMn) salida.push([xMx, mx]); }
    else { salida.push([xMx, mx]); salida.push([xMn, mn]); }
  };
  for (let i = 0; i < serie.length; i++) {
    const x = serie[i][0], y = serie[i][1];
    const c = Math.min(columnas - 1, Math.floor(((x - ini) / largo) * columnas));
    if (c !== col) { cerrar(); col = c; mn = mx = y; xMn = xMx = x; continue; }
    if (y < mn) { mn = y; xMn = x; }
    if (y > mx) { mx = y; xMx = x; }
  }
  cerrar();
  return salida;
}

/* ============================================================
   LO ESCALONADO SE DIBUJA COMO ESCALON
   ------------------------------------------------------------
   EL DEFECTO. `esCanalEscalonado` ya clasificaba bien el puesto en carrera y la
   diferencia al lider, y el lector numerico los trataba en escalon; los cuatro
   renderizadores seguian uniendo muestra con muestra por una diagonal. Con
   [100 m, 2,653 s] y [200 m, 2,336 s], a los 150 m la curva dibujaba 2,49 s
   mientras el panel decia 2,653: dos afirmaciones distintas sobre el mismo
   instante, y una de las dos era inventada.

   LA CORRECCION. Una continua se une con una recta ---entre 249 y 258 km/h el
   coche paso por 253---. Una escalonada vale lo que valia hasta que la muestra
   siguiente diga otra cosa: se dibuja plana hasta el punto donde se midio el
   cambio y ahi sube o baja de una vez.

   NO SE AGREGAN PUNTOS A LOS DATOS. El escalon lo da el **camino de dibujo**:
   los arreglos que se exportan, se comparan y se reducen siguen teniendo una
   muestra por observacion. */
function trazarSerie(ctx, puntos, enX, enY, escalonada) {
  for (let i = 0; i < puntos.length; i++) {
    const x = enX(puntos[i][0]), y = enY(puntos[i][1]);
    if (i === 0) { ctx.moveTo(x, y); continue; }
    /* El vertice va en la x de la muestra nueva: el valor anterior se sostiene
       hasta ahi. Ponerlo antes adelantaria el cambio a un sitio donde nadie lo
       midio. */
    if (escalonada) ctx.lineTo(x, enY(puntos[i - 1][1]));
    ctx.lineTo(x, y);
  }
}

/* Parte un texto en renglones que entren en `ancho`, midiendolos con la fuente
   que el contexto ya tiene puesta. Hace falta porque un lienzo no acomoda texto
   solo: `fillText` escribe una linea y la deja salirse de la imagen. */
function partirEnRenglones(ctx, texto, ancho) {
  if (!texto) return [];
  const palabras = String(texto).split(/\s+/).filter(Boolean);
  const renglones = [];
  let actual = "";
  palabras.forEach(pal => {
    const probar = actual ? actual + " " + pal : pal;
    if (actual && ctx.measureText(probar).width > ancho) {
      renglones.push(actual);
      actual = pal;
    } else {
      actual = probar;
    }
  });
  if (actual) renglones.push(actual);
  return renglones;
}

/* Recorta por dominio ---metros--- y no por indice. Un indice significa cosas
   distintas en cada señal: `slice(0, 300)` sobre una señal de 300 muestras es
   la vuelta entera y sobre una de 900 es el primer tercio. De paso se sueltan
   los puntos no finitos, que no se pueden ubicar en ningun eje. */
function recortarPorDominio(serie, ini, fin) {
  const salida = [];
  for (let i = 0; i < serie.length; i++) {
    const x = serie[i][0], y = serie[i][1];
    if (typeof x !== "number" || !Number.isFinite(x)) continue;
    if (typeof y !== "number" || !Number.isFinite(y)) continue;
    if (ini !== null && x < ini) continue;
    if (fin !== null && x > fin) continue;
    salida.push(serie[i]);
  }
  return salida;
}

/* La escala vertical, o `null` si no hay nada finito que escalar. Devolver
   `null` es el punto: con las listas vacias esto daba `Infinity`/`-Infinity`,
   de ahi `pad = NaN`, y el pie del grafico terminaba escribiendo «NaN» como si
   fuera una medicion. */
function escalaDe(listas, holgura) {
  let mn = Infinity, mx = -Infinity;
  for (let i = 0; i < listas.length; i++) {
    const l = listas[i];
    for (let j = 0; j < l.length; j++) {
      const y = l[j][1];
      if (typeof y !== "number" || !Number.isFinite(y)) continue;
      if (y < mn) mn = y;
      if (y > mx) mx = y;
    }
  }
  if (!Number.isFinite(mn) || !Number.isFinite(mx)) return null;
  // Una señal constante necesita alto igual: sin esto la division por cero
  // manda la traza al infinito.
  if (mx - mn < 1e-6) { mx = mn + 1; }
  const pad = (mx - mn) * (holgura || 0.1);
  return { mn: mn - pad, mx: mx + pad, minReal: mn, maxReal: mx };
}

/* El tramo de metros que se muestra. `ampliado` era un recorte de arreglo: el
   mismo par de indices caia en metros distintos en cada señal. Ahora es lo que
   siempre quiso decir, un tramo de la vuelta. */
function dominioAmpliado(extremos) {
  if (!extremos) return [null, null];
  if (!ampliado) return [null, null];
  const [a, b] = extremos;
  const largo = b - a;
  return [a + largo * 0.34, a + largo * 0.58];
}

/* Una señal de una vuelta, como pares [metro, valor]. Devuelve `null` si la
   vuelta todavia no llego y `[]` si llego pero la fuente no trae ese canal:
   quien dibuja tiene que poder distinguir «no hay dato» de «todavia no
   llego». */
/* ============================================================
   LA SERIE SE ARMA UNA VEZ POR VUELTA, NO POR LECTURA
   ------------------------------------------------------------
   La API entrega cada vuelta como columnas paralelas ---un arreglo de
   distancias y uno de valores por señal, con huecos en nulo--- y dibujar
   necesita pares. Armar los pares recorre las trescientas muestras y crea
   trescientos arreglos de dos.

   Se hacia en cada lectura. `calcularInstante` llama diecisiete veces para
   armar un instante, de modo que **leer un valor** costaba cinco mil
   escrituras y diecisiete arreglos nuevos. Un instante por cuadro a sesenta
   cuadros son trescientas mil escrituras por segundo para mostrar diecisiete
   numeros que ya estaban en memoria.

   El bloque de una vuelta no cambia mientras esta cargado, asi que el
   resultado se guarda. El sello sube cuando `estado.series` cambia ---llega
   una tanda nueva, se poda una vuelta, se cierra la sesion--- y con eso todo
   lo guardado deja de valer sin tener que buscar que entrada invalidar.
   ============================================================ */
let _selloSeries = 0;
let _selloDeLoArmado = -1;
const _seriesArmadas = new Map();

function cambiaronLasSeries() {
  _selloSeries++;
  /* El instante compartido se resuelve contra los instantes medidos de la
     vuelta: si cambian los datos o su alcance, lo memorizado deja de valer
     aunque el cabezal no se haya movido. */
  _instanteClave = null;
}

/* LA SERIE COMO LA TRAJO LA FUENTE. Valores en la unidad que la respuesta
   declara, sin tocar. Es lo que exporta el CSV: un archivo que dice lo que la
   base guarda no puede cambiar de unidad porque un panel cambio de rotulo. */
function serieCrudaDeCanal(canal, vuelta, clave) {
  return _armarSerieDeCanal(canal, vuelta, clave, 1);
}

/* LA MISMA SERIE, EN LA UNIDAD QUE EL TABLERO MUESTRA. Vacia cuando la unidad
   declarada no se puede llevar a esa: dibujar milisegundos bajo un eje que dice
   segundos afirma una cifra que nadie midio, y es peor que no dibujar. */
function serieDeCanal(canal, vuelta, clave) {
  const d = divisorDePresentacion(canal, vuelta, clave);
  if (d === null) return estadoSesion === "vivo" || estado.series[vuelta] ? [] : null;
  return _armarSerieDeCanal(canal, vuelta, clave, d);
}

function _armarSerieDeCanal(canal, vuelta, clave, divisor) {
  const senal = nombreDeSenal(canal);
  if (estadoSesion === "vivo") {
    const vehiculo = vivo.series.get(clave || claveVehiculoPropio());
    const cruda = vehiculo ? (vehiculo.get(senal) || []) : [];
    return divisor === 1 ? cruda : _enUnidad(cruda, divisor, "vivo|" + (clave || "") + "|" + senal + "|" + cruda.length);
  }
  const bloque = estado.series[vuelta];
  if (!bloque) return null;
  const veh = bloque.vehiculos[clave];
  if (!veh) return [];

  if (_selloDeLoArmado !== _selloSeries) {
    _seriesArmadas.clear();
    _selloDeLoArmado = _selloSeries;
  }
  /* El divisor entra en la clave: la serie cruda y la de presentacion son dos
     arreglos distintos y no pueden compartir casillero. */
  const guardada = vuelta + "|" + clave + "|" + senal + "|" + divisor;
  const hecha = _seriesArmadas.get(guardada);
  if (hecha) return hecha;

  const ys = veh[senal];
  const xs = veh.distancia_m;
  if (!ys || !xs) return [];
  const salida = [];
  const n = Math.min(xs.length, ys.length);
  for (let i = 0; i < n; i++) {
    if (ys[i] === null || ys[i] === undefined) continue;
    salida.push([xs[i], divisor === 1 ? ys[i] : ys[i] / divisor]);
  }
  _seriesArmadas.set(guardada, salida);
  return salida;
}

/* La vista convertida de una serie viva, memorizada por su largo. El arreglo
   solo crece, de modo que el largo alcanza para saber si cambio; sin esto se
   armaria una copia por canal y por cuadro. */
const _vistasVivas = new Map();
function _enUnidad(serie, divisor, llave) {
  const guardada = _vistasVivas.get(llave);
  if (guardada) return guardada;
  const salida = serie.map(p => {
    const q = p.slice();
    q[1] = p[1] === null || p[1] === undefined ? p[1] : p[1] / divisor;
    return q;
  });
  /* Solo se conserva la ultima vista de cada canal: las de largos anteriores no
     las vuelve a pedir nadie y guardarlas todas seria una fuga. */
  _vistasVivas.forEach((_v, k) => {
    if (k.slice(0, k.lastIndexOf("|")) === llave.slice(0, llave.lastIndexOf("|"))) {
      _vistasVivas.delete(k);
    }
  });
  _vistasVivas.set(llave, salida);
  return salida;
}

/* ============================================================
   LA VENTANA MOVIL NO SE CORTA EN LA META
   ------------------------------------------------------------
   EL DEFECTO. La ventana se corria sobre la distancia **de la vuelta**, que al
   cruzar la meta vuelve a cero: `fin = metro`, `inicio = max(0, metro - 1200)`.
   A los nueve metros de la vuelta nueva la ventana medía nueve metros. Medido
   sobre Spa cruzando de la vuelta 3 a la 4, con las dos ya cargadas: el trazo
   pasaba de 52 puntos abarcando 1.200 m a 2 puntos abarcando 9. La vuelta
   anterior estaba en memoria y no se dibujaba.

   LA CORRECCION. Las ventanas moviles se corren sobre la distancia
   **acumulada de la sesion**, que la API ya entrega medida en
   `distancia_sesion_m` y que no se reinicia. Con 1.200 m de ventana, a los
   cien metros de una vuelta se siguen viendo los ultimos 1.100 de la anterior.

   NO SE INVENTA LA ACUMULADA. Nada de `(vuelta - 1) * largo del circuito`: si
   una vuelta no la trae, esa vuelta no aporta a la ventana y se dice. La
   posicion sobre ese eje sale del **mismo** `tUtcMs` que ya comparten los
   instrumentos y el coche, interpolada sobre la misma serie temporal: no hay un
   segundo reloj.

   QUE SIGUE SIENDO LOCAL. El circuito, sus etiquetas, el metro que escribe el
   transporte y el modo «vuelta completa» siguen en distancia de vuelta, que es
   lo que significan. La comparacion tiene su propio eje y no se toca.
   ============================================================ */
const EJE_DISTANCIA_SESION = " distancia de sesion";

/* Una senal de una vuelta contra la distancia acumulada. Es `serieDeCanal` con
   el otro eje, y se guarda igual: una vez por vuelta, vehiculo y senal.

   Los nulos de la acumulada se descartan como los de cualquier senal: un punto
   sin sitio en el eje no se puede dibujar, y rellenarlo seria inventarlo. */
function serieAcumuladaDeCanal(canal, vuelta, clave) {
  if (estadoSesion === "vivo") return [];
  const bloque = estado.series[vuelta];
  if (!bloque) return null;
  const veh = bloque.vehiculos[clave];
  if (!veh) return [];
  const senal = canal === EJE_DISTANCIA ? "distancia_m" : nombreDeSenal(canal);

  if (_selloDeLoArmado !== _selloSeries) {
    _seriesArmadas.clear();
    _selloDeLoArmado = _selloSeries;
  }
  // La misma politica que en las otras dos vistas: convertida para mostrar.
  const divisor = canal === EJE_DISTANCIA ? 1
                : divisorDePresentacion(canal, vuelta, clave);
  if (divisor === null) return [];

  const guardada = "acum|" + vuelta + "|" + clave + "|" + senal + "|" + divisor;
  const hecha = _seriesArmadas.get(guardada);
  if (hecha) return hecha;

  const ys = veh[senal];
  const xs = veh.distancia_sesion_m;
  if (!ys || !xs) return [];
  const salida = [];
  const n = Math.min(xs.length, ys.length);
  for (let i = 0; i < n; i++) {
    const x = numeroMedido(xs[i]);
    if (x === null) continue;
    if (ys[i] === null || ys[i] === undefined) continue;
    salida.push([x, divisor === 1 ? ys[i] : ys[i] / divisor]);
  }
  _seriesArmadas.set(guardada, salida);
  return salida;
}

/* Donde empieza y termina cada vuelta sobre el eje acumulado, y con que
   desplazamiento se pasa de metro de vuelta a metro de sesion. Sale de lo
   medido ---la primera y la ultima muestra que traen las dos distancias--- y
   no de una multiplicacion por el largo del circuito. */
function tramoAcumuladoDeVuelta(vuelta, clave) {
  const cache = _cacheTemporal();
  const llave = "acumulada|" + vuelta + "|" + clave;
  if (cache.has(llave)) return cache.get(llave);

  let armado = null;
  const bloque = estado.series[vuelta];
  const veh = bloque && bloque.vehiculos[clave];
  const xs = veh && veh.distancia_sesion_m;
  const ls = veh && veh.distancia_m;
  if (xs && ls) {
    let a = null, b = null, desfase = null;
    for (let i = 0; i < Math.min(xs.length, ls.length); i++) {
      const s = numeroMedido(xs[i]);
      const l = numeroMedido(ls[i]);
      if (s === null) continue;
      if (a === null) a = s;
      b = s;
      if (desfase === null && l !== null) desfase = s - l;
    }
    if (a !== null && b !== null && desfase !== null) {
      armado = { desde: a, hasta: b, desfase: desfase };
    }
  }
  cache.set(llave, armado);
  return armado;
}

/* Las vueltas cargadas que aportan muestras al tramo `[ini, fin]` del eje
   acumulado, en orden. No se supone que sean dos: con la ventana grande y las
   vueltas cortas pueden ser tres, y con una vuelta sin acumulada puede ser una
   sola con un agujero declarado. */
function vueltasEnTramoAcumulado(ini, fin, clave) {
  const salida = [];
  Object.keys(estado.series).forEach(k => {
    const n = Number(k);
    if (!Number.isFinite(n)) return;
    const t = tramoAcumuladoDeVuelta(n, clave);
    if (!t) return;
    if (t.hasta < ini || t.desde > fin) return;
    salida.push(n);
  });
  return salida.sort((a, b) => a - b);
}

/* ============================================================
   LO QUE SE DIBUJA SON TRAMOS, Y SE UNEN SOLO SI SE TOCAN
   ------------------------------------------------------------
   Dos vueltas seguidas que se midieron sin corte son un solo trazo: la ultima
   muestra de una y la primera de la siguiente estan a un intervalo de muestreo,
   y unirlas dice lo que paso. Dos vueltas que no son consecutivas ---porque la
   del medio no esta cargada, o porque hubo un corte de captura--- no se unen:
   una recta ahi afirmaria un recorrido que nadie midio.

   Se devuelve una lista de tramos contiguos en vez de un arreglo con agujeros
   para que el recorte de bordes y la reduccion por columna sigan trabajando
   sobre arreglos normales, que es lo que saben hacer.
   ============================================================ */
function trazaContinua(canal, clave, ini, fin) {
  const vueltas = vueltasEnTramoAcumulado(ini, fin, clave);
  const tramos = [];
  let actual = null, anterior = null;
  for (let i = 0; i < vueltas.length; i++) {
    const v = vueltas[i];
    const serie = serieAcumuladaDeCanal(canal, v, clave);
    if (!serie || !serie.length) { actual = null; anterior = null; continue; }
    const pega = anterior !== null && v === anterior + 1 && !hayCorteEntreVueltas(anterior, v, clave);
    if (pega && actual) {
      for (let j = 0; j < serie.length; j++) actual.push(serie[j]);
    } else {
      actual = serie.slice();
      tramos.push(actual);
    }
    anterior = v;
  }
  return tramos;
}

/* Si entre el final de una vuelta y el arranque de la siguiente hubo un corte
   de captura, no se las une. Se pregunta con los mismos limites declarados que
   usa el reloj: no hay un criterio nuevo. */
/* ============================================================
   EL CORTE QUE NO ESTA EN NINGUNA DE LAS DOS LISTAS
   ------------------------------------------------------------
   La API calcula los saltos con `PARTITION BY vuelta`, de modo que el
   intervalo que va de la ultima muestra de una vuelta a la primera de la
   siguiente **no cae en ninguna de las dos**: las dos pueden ser internamente
   continuas y declarar `huecos: []` con cinco segundos sin captura en el
   medio. Preguntando solo por esas listas, el tablero unia los dos tramos y
   trazaba una recta sobre lo que nadie midio.

   Se comprueba tambien la separacion entre los limites **de las vueltas**
   ---`hasta_utc` de una contra `desde_utc` de la otra, que es lo que la API
   declara como su extension--- contra el mismo umbral del contrato de captura
   que separa la duracion efectiva de la bruta. No se mide la separacion entre
   muestras submuestreadas, que cambia con cuantos puntos se hayan pedido.

   Y si los limites no permiten decidir ---faltan, no son legibles, o la
   siguiente empieza antes de que termine la anterior--- no se sabe si se midio
   seguido. No saberlo no es lo mismo que saber que si: se corta.
   ============================================================ */
function hayCorteEntreVueltas(anterior, siguiente, clave) {
  const a = serieTemporal(EJE_DISTANCIA, anterior, clave);
  const b = serieTemporal(EJE_DISTANCIA, siguiente, clave);
  if (!a || !b || !a.t.length || !b.t.length) return true;
  const fin = a.t[a.t.length - 1];
  const arranque = b.t[0];
  if (!(arranque > fin)) return true;
  /* Un corte declarado dentro de cualquiera de las dos, como siempre. */
  if (hayCorteEntre(a.cont, fin, arranque) || hayCorteEntre(b.cont, fin, arranque)) {
    return true;
  }
  return hayCorteEntreVentanas(anterior, siguiente);
}

/* La separacion entre lo que las dos vueltas declaran como su extension.
   Devuelve `true` tambien cuando no se puede decidir. */
function hayCorteEntreVentanas(anterior, siguiente) {
  const lista = estado.vueltas || [];
  const va = lista.find(x => x.numero === anterior);
  const vb = lista.find(x => x.numero === siguiente);
  if (!va || !vb) return true;
  const cierra = va.hasta_utc ? Date.parse(va.hasta_utc) : NaN;
  const abre = vb.desde_utc ? Date.parse(vb.desde_utc) : NaN;
  if (!Number.isFinite(cierra) || !Number.isFinite(abre)) return true;
  if (abre < cierra) return true;             // se solapan: no se puede afirmar
  return (abre - cierra) > HUECO_DE_CAPTURA_MS;
}

function serieVelocidad(clave, vuelta) {
  return serieDeCanal("speed", vuelta || vueltaElegida || 1, clave) || [];
}

/* ============================================================
   UN SOLO INSTANTE DE PRESENTACION, Y ES UNA MARCA DE TIEMPO
   ------------------------------------------------------------
   EL DEFECTO. La marca del coche se interpolaba sobre instantes medidos
   ---`posicionesAhora`--- y todo lo demas se leia con
   `Math.round(fraccion * (muestras - 1))`. Dos cosas distintas: una avanza de
   forma continua y la otra a escalones, y ademas cada canal tiene su propia
   cantidad de muestras, de modo que el escalon del regimen y el de la
   velocidad no caian ni siquiera en el mismo sitio. En Spa, con 300 puntos
   sobre una vuelta de 127 s, cada escalon dura 425 ms: a 60 cuadros por
   segundo son veinticinco cuadros mostrando la misma cifra mientras el coche
   se mueve.

   LA CORRECCION. Se resuelve **una** referencia temporal por cuadro ---un
   instante UTC absoluto--- y de ahi leen los instrumentos, la distancia, la
   marca del coche y los cabezales de los graficos. Un instante absoluto es lo
   unico que las respuestas de la API tienen en comun: `/series` entrega
   `timestamp_utc` por muestra y `/posiciones` entrega `desde_utc` mas
   `instantes_ms`. Dos fracciones normalizadas sobre intervalos distintos no
   son el mismo momento; dos marcas UTC si.

   LA POLITICA DE LAS PAUSAS, DICHA UNA VEZ. `duracion_s` de `/vueltas` es la
   duracion **efectiva**: la API suma solo los intervalos de conduccion
   continua y descarta los huecos de captura de mas de dos segundos. El
   transporte ya reparte la linea de tiempo con esa cifra. Antes,
   `posicionesAhora` tomaba esa fraccion y la estiraba sobre la ventana UTC
   **bruta** de la vuelta, que incluye los huecos: se comprimia el tiempo de un
   lado y se lo repartia entero del otro. Ahora hay una sola politica y esta
   escrita aca: **un hueco de captura no consume tiempo de reproduccion**. El
   reloj de la vuelta acumula tiempo efectivo y salta el hueco, igual que la
   cifra con la que el transporte dimensiono esta vuelta.

   ESTO ES REPRESENTACION, NO DATO. `estado.series` y `estado.posiciones`
   quedan intactos. Lo que se arma aca son vistas temporales derivadas, en su
   propia cache, invalidadas por el mismo sello que las series por distancia.
   Los maximos y minimos de los graficos, la exportacion y la comparacion
   siguen leyendo las muestras.
   ============================================================ */

/* Que es un hueco de captura. Es el mismo umbral que usa la API para separar
   `duracion_s` de `duracion_bruta_s`: a veinte muestras por segundo, dos
   seguidas estan a cincuenta milisegundos, y mas de dos segundos no es
   conduccion sino captura cortada. */
const HUECO_DE_CAPTURA_MS = 2000;

/* La distancia recorrida no es un canal de la lista de metricas, pero se lee
   contra el tiempo igual que ellos: se la nombra con una clave que ninguna
   senal puede tener. */
const EJE_DISTANCIA = " distancia";

/* QUE SE INTERPOLA Y QUE NO, POR LO QUE LA SENAL ES.
   Una velocidad entre 249 y 258 km/h paso por 253: interpolarla dice algo que
   ocurrio. Una marcha entre la 4 y la 5 **no** pasa por la 4,5, y un DRS entre
   cerrado y abierto no esta medio abierto. Esas se mantienen en escalon sobre
   su instante medido: valen lo que valian hasta que la muestra siguiente diga
   otra cosa, y nunca antes.

   En el bus del vehiculo el acelerador y el freno son `gas_pressed` y
   `brake_pressed`: pisado o no pisado, no cuanto. Ahi tambien son escalones. */
function esCanalEscalonado(canal) {
  /* La posicion en carrera es un puesto, no una magnitud: entre el cuarto y el
     quinto no hay un cuatro y medio, y adelantarla media muestra seria mostrar
     un adelantamiento antes de que ocurriera.

     LA DIFERENCIA AL LIDER TAMBIEN ES UN ESCALON, Y ESO SE MIDIO. Sobre la
     vuelta 1 de Spa a resolucion completa ---2.735 muestras, sin submuestrear---
     el canal cambia **80 veces**: el juego lo recalcula alrededor de una vez por
     segundo y lo sostiene entre recalculos, subiendo y bajando. Interpolar entre
     dos de esos valores afirma un ritmo de acercamiento que nadie midio.
     Comprobado en el navegador: al instante 00:37:18,795 la fuente dice 2.653 ms
     durante todo el segundo que lo rodea y el tablero mostraba 2,721 s. */
  if (canal === "gear" || canal === "drs" || canal === "posicion" ||
      canal === "gap") return true;
  if (fuente === "can" && (canal === "throttle" || canal === "brake")) return true;
  return false;
}

/* ============================================================
   LOS LIMITES DE CONTINUIDAD SON DE LA VUELTA, NO DE CADA CANAL
   ------------------------------------------------------------
   LA PRIMERA VERSION LOS DEDUCIA DE CADA SERIE, Y ESO NO SE PUEDE.

   Tomaba `max(2 s, mediana de intervalos x 4)` sobre la serie **ya reducida**,
   y de ahi salen dos errores.

   Uno: el umbral depende de cuantos puntos se hayan pedido. Cuatro mil
   muestras a 50 ms con un corte real de 2,05 s, reducidas a 300 puntos, quedan
   con intervalos de 700 ms: el umbral sube a 2,8 s y el corte deja de contar.
   La misma captura, pedida a otra resolucion, da otro reloj.

   Dos: cada canal calculaba el suyo **despues** de descartar sus nulos. Un
   regimen con pocas muestras interpola por encima de un hueco que el reloj de
   la distancia ya habia detectado y salteado. Dos senales de la misma vuelta
   con dos ideas distintas de cuando hubo captura.

   MEDIDO EN SPA. La vuelta 1 sin acotar el alcance mezcla la formacion y la
   carrera; reducida a 294 puntos, la heuristica declaraba 22 s de huecos. La
   API, sobre la resolucion completa, dice `hueco_mayor_s = 0,067`: no hubo un
   solo corte. El umbral no estaba midiendo la captura, estaba midiendo el
   submuestreo.

   AHORA LOS DECLARA LA API. `/vueltas` devuelve `huecos`, los mismos
   intervalos que descarta para calcular `duracion_s`, con sus dos extremos y
   calculados sobre todas las muestras. Son unos para toda la vuelta y valen
   igual para la distancia, la velocidad y el regimen.

   CUANDO NO SE SABE. Una vuelta que declara `hueco_mayor_s` por debajo del
   umbral es continua, y eso es exacto: no hay nada que saltar. Solo cuando la
   vuelta declara que se corto y no dice donde ---una API mas vieja--- se cae en
   un umbral, y entonces se calcula **uno para la vuelta**, del canal mas denso,
   y se usa el mismo para todos. El reloj queda marcado `aproximado`, porque lo
   es.
   ============================================================ */
function continuidadDeVuelta(vuelta, clave) {
  const cache = _cacheTemporal();
  const llave = "continuidad|" + vuelta + "|" + clave;
  if (cache.has(llave)) return cache.get(llave);

  const v = (estado.vueltas || []).find(x => x.numero === vuelta);
  let armado;
  if (v && Array.isArray(v.huecos)) {
    const lista = [];
    for (let i = 0; i < v.huecos.length; i++) {
      const a = Date.parse(v.huecos[i].desde_utc);
      const b = Date.parse(v.huecos[i].hasta_utc);
      if (Number.isFinite(a) && Number.isFinite(b) && b > a) lista.push([a, b]);
    }
    armado = { huecos: lista, umbral: Infinity, exacto: true };
  } else if (v && numeroMedido(v.hueco_mayor_s) !== null &&
             v.hueco_mayor_s * 1000 <= HUECO_DE_CAPTURA_MS) {
    /* La vuelta declara que su mayor separacion esta por debajo del umbral:
       no hubo corte. Es una afirmacion, no una suposicion. */
    armado = { huecos: [], umbral: Infinity, exacto: true };
  } else {
    armado = { huecos: null, umbral: _umbralDeVuelta(vuelta, clave), exacto: false };
  }
  cache.set(llave, armado);
  return armado;
}

/* El umbral de emergencia, uno para toda la vuelta. Sale del canal mas denso
   que hay ---la distancia, que viene en cada muestra--- y no de cada senal por
   separado, que es lo que hacia que dos canales de la misma vuelta no
   coincidieran. Sigue dependiendo de la resolucion, y por eso solo se usa
   cuando la vuelta no declara sus cortes. */
function _umbralDeVuelta(vuelta, clave) {
  const st = _serieTemporalCruda(EJE_DISTANCIA, vuelta, clave);
  const marcas = st ? st.t : null;
  if (!marcas || marcas.length < 2) return HUECO_DE_CAPTURA_MS;
  const ds = [];
  for (let i = 1; i < marcas.length; i++) ds.push(marcas[i] - marcas[i - 1]);
  ds.sort((a, b) => a - b);
  return Math.max(HUECO_DE_CAPTURA_MS, ds[ds.length >> 1] * 4);
}

/* Cuanto del intervalo `[a, b]` fue captura de verdad. Con los cortes
   declarados se resta el solapamiento, que es lo que hace que un reloj armado
   sobre 300 puntos de una vuelta de 2.644 muestras coincida con la
   `duracion_s` que la API calculo sobre las 2.644. Sin ellos, un intervalo que
   pasa el umbral cuenta cero, que es lo unico defendible cuando no se sabe
   donde empieza el corte. */
function tiempoEfectivoEntre(cont, a, b) {
  if (!(b > a)) return 0;
  if (!cont) return (b - a) > HUECO_DE_CAPTURA_MS ? 0 : b - a;
  if (cont.huecos) {
    let quitar = 0;
    for (let i = 0; i < cont.huecos.length; i++) {
      const h = cont.huecos[i];
      const solapa = Math.min(b, h[1]) - Math.max(a, h[0]);
      if (solapa > 0) quitar += solapa;
    }
    return Math.max(0, (b - a) - quitar);
  }
  return (b - a) > cont.umbral ? 0 : b - a;
}

/* Si entre dos muestras hubo un corte, no se las une con una recta. */
function hayCorteEntre(cont, a, b) {
  return tiempoEfectivoEntre(cont, a, b) < (b - a) - 1e-9;
}

/* Las vistas temporales viven en su propia cache y se invalidan con el mismo
   sello que las series por distancia: llega una tanda, se poda una vuelta, se
   cierra la sesion, y todo lo derivado deja de valer sin tener que buscar que
   entrada tocar. */
let _selloDeLoTemporal = -1;
const _temporales = new Map();

function _cacheTemporal() {
  if (_selloDeLoTemporal !== _selloSeries) {
    _temporales.clear();
    _selloDeLoTemporal = _selloSeries;
  }
  return _temporales;
}

/* Una senal de una vuelta contra el **tiempo**, como dos columnas paralelas
   ordenadas por instante. Devuelve `null` cuando no se puede armar: no llego
   la vuelta, la fuente no trae esa senal, o la respuesta no trae
   `timestamp_utc` ---una API mas vieja--- y entonces quien llama vuelve a la
   rejilla por indice, que es lo que habia.

   NO SE SUPONE ORDEN TEMPORAL. `/series` devuelve `ORDER BY vehicle_id,
   distancia`: sobre una vuelta normal eso coincide con el tiempo, y sobre el
   cruce de meta no. Se comprueba y solo se ordena si hace falta, que es el
   caso raro; recorrer para comprobar cuesta menos que ordenar siempre.

   Se arma una vez por vuelta, vehiculo y senal. Reconstruirla por cuadro seria
   el mismo defecto que `serieDeCanal` ya corrigio, en otro sitio. */
function serieTemporal(canal, vuelta, clave) {
  const st = _serieTemporalCruda(canal, vuelta, clave);
  /* Los limites de continuidad se le cuelgan a la serie, pero son de la
     vuelta: la misma lista para todos sus canales. Se resuelven aparte y no
     dentro del armado para que `continuidadDeVuelta` pueda mirar la serie de
     distancia sin llamarse a si misma. */
  if (st && !st.cont) st.cont = continuidadDeVuelta(vuelta, clave);
  return st;
}

function _serieTemporalCruda(canal, vuelta, clave) {
  if (estadoSesion === "vivo") return null;
  const bloque = estado.series[vuelta];
  if (!bloque) return null;
  const veh = bloque.vehiculos[clave];
  if (!veh || !veh.timestamp_utc) return null;

  /* La conversion de unidad va aca y no en el bloque: la serie temporal es una
     vista de presentacion ---la usan el instante y los graficos--- y el bloque
     tiene que seguir diciendo lo que la fuente mando. Si la unidad declarada no
     se puede llevar a la que se muestra, no hay serie que dar. */
  const divisor = (canal === EJE_DISTANCIA || canal === EJE_DISTANCIA_SESION)
    ? 1 : divisorDePresentacion(canal, vuelta, clave);
  if (divisor === null) return null;

  const cache = _cacheTemporal();
  const llave = vuelta + "|" + clave + "|" + canal;
  if (cache.has(llave)) return cache.get(llave);

  const ys = canal === EJE_DISTANCIA ? veh.distancia_m
           : canal === EJE_DISTANCIA_SESION ? veh.distancia_sesion_m
           : veh[nombreDeSenal(canal)];
  const marcas = veh.timestamp_utc;
  let armada = null;
  if (ys) {
    const n = Math.min(marcas.length, ys.length);
    const puntos = [];
    for (let i = 0; i < n; i++) {
      /* Un nulo no es un cero y no se rellena: la muestra no existe, y entre
         las dos que la rodean hay lo que haya. */
      const y = numeroMedido(ys[i]);
      if (y === null) continue;
      const t = typeof marcas[i] === "number" ? marcas[i] : Date.parse(marcas[i]);
      if (!Number.isFinite(t)) continue;
      puntos.push([t, divisor === 1 ? y : y / divisor]);
    }
    let ordenada = true;
    for (let i = 1; i < puntos.length; i++) {
      if (puntos[i][0] < puntos[i - 1][0]) { ordenada = false; break; }
    }
    if (!ordenada) puntos.sort((a, b) => a[0] - b[0]);
    /* DOS MUESTRAS CON LA MISMA MARCA NO SON DOS INSTANTES. Se queda la
       primera: interpolar sobre un intervalo de duracion cero divide por cero,
       y elegir la ultima seria preferir una por su posicion en el arreglo, que
       no es un criterio. */
    const t = [], v = [];
    for (let i = 0; i < puntos.length; i++) {
      if (i && puntos[i][0] === puntos[i - 1][0]) continue;
      t.push(puntos[i][0]);
      v.push(puntos[i][1]);
    }
    if (t.length) armada = { t: t, v: v };
  }
  cache.set(llave, armada);
  return armada;
}

/* La ultima muestra en el instante pedido o antes de el; -1 si el instante es
   anterior a la primera. Busqueda binaria: esto se llama una vez por canal y
   por cuadro. */
function _antesDe(st, t) {
  if (!(t >= st.t[0])) return -1;
  let lo = 0, hi = st.t.length - 1;
  while (lo < hi) {
    const medio = (lo + hi + 1) >> 1;
    if (st.t[medio] <= t) lo = medio; else hi = medio - 1;
  }
  return lo;
}

/* UNA SENAL CONTINUA, ENTRE SUS DOS MUESTRAS.
   Antes de la primera vale la primera y despues de la ultima vale la ultima:
   no se extrapola, porque fuera del tramo medido no hay pendiente que
   defender. Sobre un hueco de captura tampoco se une ---no se sabe que paso
   ahi--- y se sostiene la ultima medida hasta que llegue la siguiente.

   `sinRetroceso` es para la distancia de vuelta: cuando baja, la vuelta se
   cerro. Unir esos dos puntos haria retroceder siete kilometros en pantalla, y
   forzar que crezca esconderia los descensos que **si** son un error. Se
   sostiene la ultima medida, igual que hace `posicionesAhora`. */
function valorContinuoEn(st, t, sinRetroceso) {
  if (!st || !st.t.length) return null;
  const i = _antesDe(st, t);
  if (i < 0) return st.v[0];
  if (i >= st.t.length - 1) return st.v[i];
  const dt = st.t[i + 1] - st.t[i];
  if (!(dt > 0) || hayCorteEntre(st.cont, st.t[i], st.t[i + 1])) return st.v[i];
  if (sinRetroceso && st.v[i + 1] < st.v[i]) return st.v[i];
  const u = Math.min(1, Math.max(0, (t - st.t[i]) / dt));
  return st.v[i] + (st.v[i + 1] - st.v[i]) * u;
}

/* UNA SENAL DISCRETA, EN ESCALON SOBRE SU INSTANTE MEDIDO.
   Vale lo que valia hasta que la muestra siguiente diga otra cosa. Elegir la
   muestra **mas cercana** ---que es lo que hacia el redondeo--- adelanta el
   cambio hasta medio intervalo: la marcha subia antes de que el dato dijera
   que subio, y eso es mostrar un estado futuro.

   ANTES DE LA PRIMERA MUESTRA NO HAY ESTADO, Y SE DICE.
   Una continua se sostiene en su primer valor porque el coche venia de algun
   sitio y esa es la mejor cota que hay. Una discreta no: que la primera marcha
   medida sea la cuarta no dice que estuviera en cuarta antes de que empezara a
   medirse, y afirmarlo es inventar un estado. Se devuelve `null`, que los
   instrumentos ya saben escribir como una raya. La regla no se extiende hacia
   atras salvo que la fuente declare que ese estado venia de antes, y ninguna
   de las que hay lo declara. */
function valorEscalonadoEn(st, t) {
  if (!st || !st.t.length) return null;
  const i = _antesDe(st, t);
  return i < 0 ? null : st.v[i];
}

/* ============================================================
   EL RELOJ ES UNA LISTA DE TRAMOS CONTINUOS, NO UNA LISTA DE MUESTRAS
   ------------------------------------------------------------
   LO QUE FALTABA. El reloj ya descontaba los cortes declarados, de modo que el
   **total** coincidia a cualquier resolucion. Pero guardaba las marcas de las
   muestras ---submuestreadas--- y la vuelta de tiempo efectivo a UTC
   interpolaba entre dos de ellas. Cuando el submuestreo se llevaba por delante
   las dos muestras que rodean el corte, esa recta lo atravesaba.

   Medido con 4.000 muestras cada 50 ms y un corte de 2,05 s entre los 99.950 y
   los 102.000 ms, preguntando por 100.000 ms de tiempo rodado:

   | resolucion | instante |
   |---|---:|
   | completa | 102.050 ms |
   | 300 puntos | **101.892,3 ms**, dentro del corte |

   El total era el mismo y el instante no. Comparar totales no comprueba que
   dos resoluciones representen el mismo momento.

   AHORA. El reloj se arma con los limites de la **vuelta** ---los que declara
   `/vueltas`--- partidos por los cortes que la misma respuesta declara. Cada
   tramo es un intervalo de captura continua, y pasar de tiempo rodado a UTC es
   una suma dentro del tramo que le toca: no hay recta que cruce nada, y no
   depende de cuantas muestras se hayan pedido.

   ESTOS LIMITES NO SON MUESTRAS. Son los bordes de la captura, no telemetria:
   no entran en ninguna serie, no aportan una velocidad ni una distancia que
   nadie midio, y las senales siguen sin unirse por encima de un corte.

   AL AGOTARSE UN TRAMO SE SIGUE EN EL ARRANQUE DEL SIGUIENTE. Es la unica
   respuesta defendible: el instante siguiente al ultimo que se midio antes del
   corte es el primero que se midio despues.

   CUANDO LA VUELTA NO DECLARA SUS CORTES ---una API mas vieja--- los tramos se
   deducen de las muestras, que es lo que habia, y el reloj se marca
   `aproximado` porque depende de la resolucion.
   ============================================================ */
function relojDeVuelta(vuelta) {
  const cache = _cacheTemporal();
  const llave = "reloj|" + vuelta + "|" + claveVehiculoPropio();
  if (cache.has(llave)) return cache.get(llave);
  const armado = _armarRelojDeVuelta(vuelta);
  cache.set(llave, armado);
  return armado;
}

/* Parte `[ini, fin]` por los cortes, y devuelve los tramos que quedan. Los
   cortes se ordenan y se recortan a la vuelta: uno que caiga afuera no la
   toca, y dos que se solapen cuentan una sola vez. */
function _tramosContinuos(ini, fin, huecos) {
  const orden = huecos.slice().sort((a, b) => a[0] - b[0]);
  const tramos = [];
  let desde = ini;
  for (let i = 0; i < orden.length; i++) {
    const a = Math.max(ini, orden[i][0]);
    const b = Math.min(fin, orden[i][1]);
    if (!(b > a)) continue;
    if (a > desde) tramos.push([desde, a]);
    if (b > desde) desde = b;
  }
  if (fin > desde) tramos.push([desde, fin]);
  return tramos;
}

/* Sin cortes declarados no hay mas remedio que deducirlos de las muestras. Se
   corta donde `hayCorteEntre` dice que se corto, y el tramo sigue en la
   muestra siguiente. Da lo mismo que daba antes, y sigue dependiendo de la
   resolucion: por eso quien lo usa se declara aproximado. */
function _tramosDeMuestras(st, cont, ini, fin) {
  if (!st || st.t.length < 2) return fin > ini ? [[ini, fin]] : [];
  const tramos = [];
  let desde = st.t[0];
  for (let i = 1; i < st.t.length; i++) {
    if (hayCorteEntre(cont, st.t[i - 1], st.t[i])) {
      if (st.t[i - 1] > desde) tramos.push([desde, st.t[i - 1]]);
      desde = st.t[i];
    }
  }
  const ultimo = st.t[st.t.length - 1];
  if (ultimo > desde) tramos.push([desde, ultimo]);
  return tramos;
}

function _armarRelojDeVuelta(vuelta) {
  const clave = claveVehiculoPropio();
  const st = serieTemporal(EJE_DISTANCIA, vuelta, clave);
  const cont = st ? st.cont : continuidadDeVuelta(vuelta, clave);
  const v = (estado.vueltas || []).find(x => x.numero === vuelta);

  /* LOS EXTREMOS SON DE LA VUELTA, NO DE LAS SENALES.
     `/vueltas` los saca del primer y el ultimo instante en que se publico ese
     numero de vuelta; la serie empieza en su primera muestra con distancia, que
     en Spa cae 250 ms mas tarde. Tomar los de la vuelta es ademas lo que hace
     que el reloj y el `desde_utc` de `/posiciones` ---que salen de la misma
     consulta--- arranquen en el mismo sitio. */
  let ini = v && v.desde_utc ? Date.parse(v.desde_utc) : NaN;
  let fin = v && v.hasta_utc ? Date.parse(v.hasta_utc) : NaN;
  const declarados = Number.isFinite(ini) && Number.isFinite(fin) && fin > ini;
  if (!declarados) {
    if (!st || st.t.length < 2) return null;
    ini = st.t[0];
    fin = st.t[st.t.length - 1];
  }
  if (!(fin > ini)) return null;

  let tramos, exacto;
  if (cont && cont.huecos) {
    tramos = _tramosContinuos(ini, fin, cont.huecos);
    /* Exacto solo si los dos lados lo son: los cortes declarados y la ventana
       declarada. Con la ventana sacada de la serie, los bordes se corren con
       la resolucion aunque los cortes no. */
    exacto = !!cont.exacto && declarados;
  } else {
    tramos = _tramosDeMuestras(st, cont, ini, fin);
    exacto = false;
  }
  /* Una vuelta que quedo entera dentro de un corte no tiene tiempo rodado, y
     eso no es un error: se la coloca en su arranque y no se mueve. */
  if (!tramos.length) tramos = [[ini, ini]];

  const acumulado = new Array(tramos.length);
  let suma = 0;
  for (let i = 0; i < tramos.length; i++) {
    acumulado[i] = suma;
    suma += tramos[i][1] - tramos[i][0];
  }
  return { tramos: tramos, acumulado: acumulado, total: suma, aproximado: !exacto };
}

/* El instante que se esta mostrando, en milisegundos UTC. `null` cuando no hay
   con que resolverlo, y entonces cada consumidor vuelve a lo que hacia. */
function tiempoDePresentacion(vuelta, fraccion) {
  const r = relojDeVuelta(vuelta);
  if (!r) return null;
  if (!(r.total > 0)) return r.tramos[0][0];
  const meta = Math.max(0, Math.min(1, fraccion)) * r.total;
  /* El ultimo tramo que empieza en este tiempo rodado o antes. Justo en el
     borde gana el siguiente, que es la regla: agotado un tramo, se sigue en el
     arranque del que viene. */
  let lo = 0, hi = r.acumulado.length - 1;
  while (lo < hi) {
    const medio = (lo + hi + 1) >> 1;
    if (r.acumulado[medio] <= meta) lo = medio; else hi = medio - 1;
  }
  /* Dentro del tramo, el tiempo rodado y el de reloj son el mismo: no hay
     cortes adentro, por definicion. */
  return Math.min(r.tramos[lo][1], r.tramos[lo][0] + (meta - r.acumulado[lo]));
}

/* ============================================================
   LOS BORDES DE LA VENTANA SE CALCULAN, NO SE RECORTAN
   ------------------------------------------------------------
   La ventana movil de los graficos se corre con la distancia de presentacion,
   que ahora es continua. Pero recortar por dominio deja fuera las muestras que
   caen del otro lado del borde, de modo que el extremo del trazo solo se mueve
   cuando **entra o sale una muestra**: la ventana se desliza y la punta del
   trazo avanza a saltos de una muestra. Es el mismo escalon, en el sitio donde
   mas se ve.

   Se calcula el punto donde la senal cruza cada borde y se lo agrega. Un punto
   calculado no es una medicion: no entra en la escala, ni en los maximos del
   pie, ni en la exportacion; se usa solo para cerrar el trazo contra el borde.

   Una senal escalonada no se cruza en diagonal: su valor en el borde es el que
   tenia la ultima muestra, no una mezcla de las dos. */
function recortarConBordes(serie, ini, fin, escalonada) {
  const limpia = recortarPorDominio(serie, null, null);
  if (!limpia.length) return limpia;
  const a = (ini === null || ini === undefined) ? -Infinity : ini;
  const b = (fin === null || fin === undefined) ? Infinity : fin;
  const enX = (p, q, x) => {
    const dx = q[0] - p[0];
    if (!(dx > 0)) return null;
    if (escalonada) return [x, p[1]];
    return [x, p[1] + (q[1] - p[1]) * ((x - p[0]) / dx)];
  };
  const salida = [];
  for (let i = 0; i < limpia.length; i++) {
    const p = limpia[i], q = limpia[i + 1];
    if (q && p[0] < a && q[0] > a) { const e = enX(p, q, a); if (e) salida.push(e); }
    if (p[0] >= a && p[0] <= b) salida.push(p);
    if (q && p[0] < b && q[0] > b) { const e = enX(p, q, b); if (e) salida.push(e); }
  }
  return salida;
}

/* ============================================================
   LO QUE SE GUARDA Y LO QUE SE SUELTA
   ------------------------------------------------------------
   Cada vuelta traida se guarda para no volver a pedirla, y eso esta bien: es
   justo lo que hace que volver atras sea instantaneo. Pero guardadas todas,
   una carrera larga deja en memoria la sesion entera medida a trescientos
   puntos por vuelta y por señal, que es lo que se quiso evitar al pedirlas de
   a una.

   Se sueltan las mas lejanas al cabezal, no las mas viejas. Alguien que mira
   la vuelta 12 va a volver a la 11 o a pasar a la 13 mucho antes que a la 2, y
   la distancia dice eso mejor que el orden en que se pidieron.
   ============================================================ */
const VUELTAS_EN_MEMORIA = 8;

function podarVueltas() {
  const centro = instante().vuelta || 1;
  const enComparacion = compAbierta() ? new Set(vueltasParaComparar()) : new Set();
  /* LO QUE TODAVIA SE VE SE CONSERVA PRIMERO, PERO NO SIN LIMITE.
     Con la ventana movil sobre el eje acumulado, la vuelta anterior sigue
     aportando muestras despues de cruzar la meta: podarla porque el cabezal ya
     no esta en ella vaciaria media pantalla. Pero excluirla de la poda **sin
     limite** rompe el presupuesto: trece vueltas cortas aportando a una
     ventana de tres kilometros son 3.900 puntos contra los 3.600 que se
     declararon, y la memoria de lo visible no puede ser ilimitada.

     Se conserva por prioridad y no por exclusion: lo visible se suelta ultimo,
     y si aun asi no entra, se suelta lo mas viejo de la ventana. Se pierde
     cobertura por el extremo antiguo ---se ve menos historia, que es lo
     honesto--- y no se inventan puntos ni se falsean extremos medidos. */
  const enPantalla = new Set(_vueltasEnPantalla);

  /* LAS SERIES SE PODAN POR PUNTOS, NO POR CANTIDAD DE VUELTAS.
     Contar vueltas dejaba pasar ocho de 300 puntos o ocho de 20 y llamaba
     «ocho» a las dos. Y proteger sin limite todo lo que la comparacion usa
     convertia la proteccion en una excepcion al limite: quien recorria veinte
     vueltas en detalle y despues abria la carrera se quedaba con veinte
     bloques de 300 puntos protegidos para siempre.

     Se sueltan primero las que la comparacion no usa, de la mas lejana al
     cabezal hacia adentro; recien si con eso no alcanza se tocan las de la
     comparacion, tambien por lejania. La vuelta que se esta mirando no se
     suelta nunca.

     Que no haya ciclo de descargar y expulsar no es una esperanza: el limite
     es el presupuesto de la carrera **mas** cuatro vueltas en detalle, de modo
     que la carrera entera entra sin desalojar a nadie. */
  let total = puntosGuardados();
  if (total > LIMITE_DE_DETALLE_PUNTOS) {
    const nums = Object.keys(estado.series).map(Number).filter(n => !isNaN(n));
    /* Tres capas: primero lo que no se ve ni se compara, despues lo que se
       compara pero no se ve, y al final lo que se ve. Dentro de cada capa, lo
       mas lejano al cabezal. La vuelta que se esta mirando no se suelta. */
    const capa = n => (enPantalla.has(n) ? 2 : enComparacion.has(n) ? 1 : 0);
    const orden = nums
      .filter(n => n !== centro)
      .sort((a, b) => {
        const ca = capa(a), cb = capa(b);
        if (ca !== cb) return ca - cb;
        return Math.abs(b - centro) - Math.abs(a - centro);   // y lo mas lejano
      });
    for (let i = 0; i < orden.length && total > LIMITE_DE_DETALLE_PUNTOS; i++) {
      const n = orden[i];
      total -= (estado.series[n].puntos_pedidos || PUNTOS_POR_VUELTA);
      delete estado.series[n];
    }
    cambiaronLasSeries();
  }

  /* LAS POSICIONES SE PODAN APARTE Y NO LAS PROTEGE LA COMPARACION.
     Son para el trazado, que muestra **una** vuelta por vez; la comparacion no
     las lee. Protegerlas por estar en su alcance guardaba doscientos puntos por
     vuelta por veinte vehiculos de vueltas que nadie iba a dibujar. */
  const pos = Object.keys(estado.posiciones).map(Number).filter(n => !isNaN(n));
  if (pos.length > VUELTAS_EN_MEMORIA) {
    pos.filter(n => n !== centro)
       .sort((a, b) => Math.abs(b - centro) - Math.abs(a - centro))
       .slice(0, pos.length - VUELTAS_EN_MEMORIA)
       .forEach(n => { delete estado.posiciones[n]; });
  }
}

/* ============================================================
   QUE CONSULTAS SIGUEN SIENDO UTILES
   ------------------------------------------------------------
   Cambiar de sesion invalida todo lo que estaba pidiendo la anterior. No
   alcanza con ignorar la respuesta cuando llegue: mientras viaja ocupa una
   conexion de las seis que el navegador da por origen, y son justo las que
   necesita la sesion nueva para dibujarse.

   La vuelta se trata distinto, a proposito. Una respuesta de la vuelta 5 que
   llega cuando ya estas en la 12 **no se tira**: se guarda en
   `estado.series[5]`, que es donde corresponde, y sirve entera si volves.
   Anularla seria pagar la consulta y despues romperla. Lo que no puede pasar
   es que pise el instante que se esta mirando, y eso lo resuelve la clave por
   vuelta, no la anulacion.
   ============================================================ */
let _mandoSesion = null;

/* ============================================================
   CADA APERTURA ES UNA, Y SE LA NUMERA
   ------------------------------------------------------------
   Comprobar el `session_id` antes de aplicar un resultado no alcanza. Abrir A,
   pasar a B y volver a A ---dos clics, cosa de segundos--- deja viajando la
   consulta de la **primera** A. Cuando vuelve, el identificador coincide y el
   resultado se aplica sobre la segunda A como si fuera suyo, con la vuelta que
   se estaba mirando entonces y con el vehiculo que estaba elegido entonces.

   Un numero de apertura no tiene ese agujero: la primera A y la segunda A son
   aperturas distintas aunque sean la misma sesion. Todo lo que vuelva de la
   red se pregunta si la apertura que lo pidio sigue siendo la vigente antes de
   tocar nada.
   ============================================================ */
let _aperturaActual = 0;

function nuevaSesionEnCurso() {
  if (_mandoSesion) _mandoSesion.abort();
  _mandoSesion = new AbortController();
  /* AQUI NO SE BORRA LA IDENTIDAD.
     Esta funcion anula lo que este en vuelo, y a eso la llaman tres caminos: al
     abrir una sesion, al elegir adquisicion y al elegir etapa. Borrar la
     parrilla aca hacia que elegir Carrera perdiera el nombre que la respuesta
     ya habia traido. Lo que evita que la parrilla de A nombre a los vehiculos
     de B es que se guarda **con su sesion** y se lee comprobandola, no que se
     la borre en el unico sitio que anula consultas. */
  return ++_aperturaActual;
}

function aperturaVigente() { return _aperturaActual; }

function sigueVigente(apertura) { return apertura === _aperturaActual; }

function senalDeSesion() {
  if (!_mandoSesion) _mandoSesion = new AbortController();
  return _mandoSesion.signal;
}

/* Pide una vuelta si no esta y no se esta pidiendo ya. */
function asegurarVuelta(numero, puntos, deFondo) {
  if (!estado.abierta || numero < 1 || !alcancePermitePedir()) {
    return Promise.resolve(null);
  }
  const quiere = puntos || PUNTOS_POR_VUELTA;
  const bloque = estado.series[numero];
  const conocidos = bloque && bloque.vehiculos || {};
  const pedidos = [...seleccion].filter(x => typeof x === "string");
  const faltantes = pedidos.filter(id => !conocidos[id]);
  /* Una copia mas gruesa no se hace pasar por la fina. La respuesta declara
     con cuantos puntos vino; si la guardada tiene menos de los que ahora se
     quieren, se vuelve a pedir. Sin esto, mirar la carrera entera y despues
     una sola vuelta dejaba esa vuelta dibujada a 109 puntos para siempre. */
  const bastaLaGuardada = bloque && (bloque.puntos_pedidos || 0) >= quiere;
  if (bastaLaGuardada && (!pedidos.length || !faltantes.length)) {
    return Promise.resolve(bloque);
  }
  if (estado.pidiendo[numero]) return estado.pidiendo[numero];
  /* La API admite doce señales por consulta ---un limite razonable, porque
     cada una es una pasada sobre la tabla---. La simulacion publica mas: se
     piden en tandas de doce y se juntan, que es mas barato que pedir de a una
     y mas honesto que quedarse con doce y no decirlo. */
  const todas = senalesCandidatas();
  const tandas = [];
  for (let i = 0; i < todas.length; i += 12) tandas.push(todas.slice(i, i + 12));

  /* EL VEHICULO DEL QUE HAY TELEMETRIA VA SIEMPRE.
     `seleccion` dice a quien dibujar sobre el trazado, y ahi entran vehiculos
     de los que la fuente publica **posicion y nada mas**. Usarla tal cual para
     pedir las series hacia que el tablero pidiera las señales de un vehiculo
     que no las tiene: la API contestaba con la lista vacia, correctamente, y
     los cuatro graficos quedaban diciendo «sin dato» sobre una vuelta que si
     estaba en la base.

     Se pide siempre por el vehiculo del que hay serie. Si todavia no se sabe
     cual es, no se acota y la API los devuelve todos, que es como se aprende. */
  const propio = estado.vehiculoClave;
  const conPropio = (estado.series[numero] ? faltantes : pedidos).slice();
  if (propio && conPropio.indexOf(propio) === -1) conPropio.push(propio);
  const autos = propio ? conPropio : [];
  const apertura = aperturaVigente();
  const base = "/sesiones/" + encodeURIComponent(estado.abierta.session_id) +
               "/series?vuelta=" + numero +
               (autos.length ? "&vehiculos=" + encodeURIComponent(autos.join(",")) : "") +
               "&puntos=" + quiere + sufijoDeCorrida(true) + "&senales=";

  /* La señal de sesion tambien acota estas consultas. Cambiar de sesion las
     invalida por completo ---la caché por vuelta se vacia con ella--- y
     mientras viajan ocupan las conexiones que necesita la sesion nueva.

     Lo que **no** se anula es un cambio de vuelta: la respuesta de la vuelta 5
     se guarda en `estado.series[5]`, que es su lugar, y sirve entera si se
     vuelve. Anularla seria pagar la consulta y despues romperla. */
  const peticion = Promise.all(tandas.map(t =>
      pedir(base + encodeURIComponent(t.join(",")), { senal: senalDeSesion() })))
    .then(partes => {
      const d = partes[0];
      d.unidades = Object.assign({}, d.unidades);
      // Las tandas siguientes aportan sus columnas al mismo vehiculo.
      partes.slice(1).forEach(p => {
        // Y su unidad con ellas: la señal viaja en la tanda que la trajo.
        Object.assign(d.unidades, p.unidades || {});
        Object.keys(p.vehiculos || {}).forEach(k => {
          if (!d.vehiculos[k]) { d.vehiculos[k] = p.vehiculos[k]; return; }
          Object.keys(p.vehiculos[k]).forEach(c => {
            if (c !== "distancia_m") d.vehiculos[k][c] = p.vehiculos[k][c];
          });
        });
      });
      /* NO SE CONVIERTE NADA ACA. Lo que llego se guarda como llego, con su
         mapa de unidades; convertir es cosa de las vistas de presentacion. */
      return d;
    })
    .then(d => {
      // Vigencia por apertura, no por identificador: A -> B -> A es la misma
      // sesion y dos aperturas distintas.
      if (!estado.abierta || !sigueVigente(apertura)) return null;
      if (estado.fallo) delete estado.fallo[numero];
      cambiaronLasSeries();
      const anterior = estado.series[numero];
      // Si lo que llega es mas fino que lo guardado, manda lo nuevo.
      if (anterior && (anterior.puntos_pedidos || 0) < (d.puntos_pedidos || 0)) {
        estado.series[numero] = d;
      } else if (anterior) {
        Object.assign(anterior.vehiculos, d.vehiculos || {});
        // Y su unidad con ellas: cada columna viene en la que la fuente declaro.
        anterior.unidades = Object.assign({}, anterior.unidades, d.unidades || {});
        anterior.submuestreado = anterior.submuestreado || d.submuestreado;
        d = anterior;
      } else {
        estado.series[numero] = d;
      }
      /* LOS VEHICULOS DE LA SERIE SE SUMAN, NO SOLO CUANDO LA LISTA ESTA VACIA.
         Decia `if (!AUTOS.length)`, y eso perdia vehiculos segun **cual de dos
         consultas contestara primero**: si `/posiciones` llegaba antes con un
         solo vehiculo, la lista quedaba armada con ese uno y las series de los
         demas ya no la ampliaban. El tablero terminaba conociendo un vehiculo
         de los dos que tenia el dato en la mano, y «Comparar pilotos» quedaba
         apagado sin motivo.

         Se veia como una prueba intermitente: `test_dashboard_browser` fallaba
         una de cada veinte corridas, y solo cuando `/posiciones` ganaba la
         carrera. La lista se completa con lo que traiga cada respuesta, venga
         en el orden que venga. */
      const claves = Object.keys(d.vehiculos);
      const nuevas = claves.filter(c => !AUTOS.some(a => a.id === c));
      if (nuevas.length) {
        const vacia = !AUTOS.length;
        armarAutos(AUTOS.map(a => a.id).concat(nuevas).sort());
        if (vacia) seleccion = new Set([claves[0]]);
      }
      /* Las posiciones pueden llegar antes que las series, y entonces la lista
         de vehiculos se armo sin saber cual tiene telemetria. Al llegar la
         serie se sabe, y se corrige quien es el propio: es este el unico
         momento en que el dato lo dice. */
      if (!estado.vehiculoClave) estado.vehiculoClave = claves[0] || null;
      if (estado.vehiculoClave && AUTOS.length) {
        const yaEsta = AUTOS.some(a => a.propio && a.id === estado.vehiculoClave);
        if (!yaEsta && AUTOS.some(a => a.id === estado.vehiculoClave)) {
          AUTOS.forEach(a => {
            a.propio = a.id === estado.vehiculoClave;
            a.aporta = a.propio ? "telemetría completa" : "solo posición en pista";
          });
          const sel = document.getElementById("sel-propio");
          if (sel) sel.dataset.firma = "";
        }
      }
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
      // Una vuelta anulada no es una vuelta que fallo: se cancelo porque su
      // sesion se cerro, y avisarlo seria un error donde no lo hubo.
      if (fueAnulada(e)) return null;
      /* EL ERROR PERTENECE A SU APERTURA, IGUAL QUE EL ACIERTO.
         La continuacion feliz comprueba la vigencia y esta no lo hacia: el
         error de una consulta de A, terminando despues de haber pasado a B,
         quedaba anotado en `B.fallo` y cambiaba su decision de esperar datos.
         Comparar el identificador de sesion no alcanza ---A -> B -> A es la
         misma sesion y dos aperturas--- y por eso se compara la apertura. */
      if (!estado.abierta || !sigueVigente(apertura)) return null;
      // Una vuelta que no se puede traer no rompe el tablero: se avisa y se
      // sigue con las que si estan.
      /* Y se anota que fallo. Sin esta marca, la reproduccion se quedaria
         esperandola para siempre: «todavia no llego» y «no va a llegar» se
         ven igual desde afuera si nadie lo dice. */
      if (!estado.fallo) estado.fallo = {};
      /* REINTENTAR SOLO LO QUE PUEDE SALIR DISTINTO.
         Este consejo se escribio para fallos pasajeros ---una red lenta, un
         tiempo agotado--- y se daba tambien cuando la API contesta 422, que es
         «esta consulta no se puede responder para esta fuente». Mover el
         cabezal mil veces no va a hacer que el bus declare distancia: mandar a
         reintentar lo permanente es mandar a perder el tiempo. */
      const permanente = e.estado === 422;
      estado.fallo[numero] = { motivo: e.message, permanente: permanente };
      avisar("Vuelta " + numero + ": " + e.message +
             (permanente ? "" : ". Se puede reintentar moviendo el cabezal a esa vuelta."),
             true);
      return null;
    });

  /* LA MARCA LA BORRA SU DUEÑA.
     `delete estado.pidiendo[numero]` a secas lo borraba sin mirar de quien
     era: una peticion vieja que termina tarde borraba la marca de la peticion
     **nueva** de la misma vuelta, y a partir de ahi todo pedido de esa vuelta
     arrancaba una consulta mas porque la marca ya no estaba. Se compara la
     identidad antes de borrar. */
  const registrada = conCarga("series", () => peticion, deFondo);
  estado.pidiendo[numero] = registrada;
  registrada.catch(() => null).then(() => {
    if (estado.pidiendo[numero] === registrada) delete estado.pidiendo[numero];
    podarVueltas();
  });
  return registrada;
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
function asegurarPosiciones(numero, deFondo) {
  if (!estado.abierta || estado.posiciones[numero] || estado.pidiendoPos[numero]) return;
  if (!alcancePermitePedir()) return;
  const apertura = aperturaVigente();
  estado.pidiendoPos[numero] = apertura;
  conCarga("posiciones", () =>
  pedir("/sesiones/" + encodeURIComponent(estado.abierta.session_id) +
        "/posiciones?vuelta=" + numero + "&puntos=200" + sufijoDeCorrida(true),
        { senal: senalDeSesion() })
    .then(d => {
      if (!sigueVigente(apertura)) return;
      estado.posiciones[numero] = d;
      // Los rivales entran a la lista de vehiculos aunque no tengan telemetria
      // privada: de ellos se muestra donde estan, que es lo que la fuente
      // entrega de todos.
      const claves = Object.keys(d.vehiculos || {});
      // Los rivales se suman a la lista; quien es el propio ya esta decidido.
      if (claves.length > AUTOS.length) armarAutos(claves.sort());
      render();
    })
    // Un fallo de red aca no es grave; uno de dibujo si, y no puede quedar mudo.
    .catch(e => { if (!fueAnulada(e) && e instanceof TypeError) console.error(e); })
    .then(() => {
      if (estado.pidiendoPos[numero] === apertura) delete estado.pidiendoPos[numero];
      podarVueltas();
    }), deFondo);
}

/* Cual es la vuelta que viene despues de esta, segun lo que `/vueltas`
   declaro. No es `numero + 1`: una vuelta sin muestras no figura en la lista,
   y suponer que los numeros son seguidos gasta una consulta que solo puede
   contestarse con una lista vacia. `null` en la ultima. */
function vueltaSiguienteDeclarada(numero) {
  const lista = estado.vueltas || [];
  const i = lista.findIndex(x => x.numero === numero);
  if (i === -1 || i + 1 >= lista.length) return null;
  return lista[i + 1].numero;
}

/* Que vueltas aportaron muestras al ultimo dibujo. Lo escribe `dibujarTraza` y
   lo lee la poda: mientras una vuelta este en la ventana, soltarla vaciaria
   media pantalla. */
let _vueltasEnPantalla = [];

/* ============================================================
   UNA VENTANA VACIA Y UN CUADRO RETENIDO NO SON LO MISMO
   ------------------------------------------------------------
   Esto se escribia solo cuando la lista nueva tenia elementos, y esa
   condicion dejaba la proteccion pegada: al pasar a «vuelta completa» ---donde
   la ventana es de una vuelta y no aporta acumuladas--- quedaban protegidas
   para siempre vueltas que ya no se ven.

   Pero vaciarla siempre tampoco sirve: mientras se espera la vuelta siguiente
   el cuadro anterior sigue en pantalla, y ese cuadro **necesita** sus datos.
   La distincion es esa: si hay una espera en curso, lo que estaba dibujado
   sigue estandolo y se conserva; si no, la lista nueva manda aunque venga
   vacia.
   ============================================================ */
function anotarEnPantalla(vueltas) {
  if (!vueltas.length && _esperandoVuelta !== null) return;
  _vueltasEnPantalla = vueltas;
}

/* ============================================================
   SI LO QUE VIENE NO LLEGO, SE ESPERA QUIETO Y SE DICE
   ------------------------------------------------------------
   Con la precarga andando esto no deberia pasar casi nunca: la vuelta
   siguiente se pide mientras se mira la actual. Pero puede ---una red lenta,
   un salto a una vuelta que nadie pidio--- y lo que hacia el tablero era seguir
   avanzando el cabezal sobre una vuelta sin datos: los medidores pasaban a
   rayas y los graficos se vaciaban, y despues, cuando la respuesta llegaba, el
   cabezal ya estaba varios segundos mas adelante.

   Ahora se detiene el avance del reloj compartido y se deja el ultimo cuadro
   coherente en pantalla. Se avisa en la linea de estado ---no se tapa nada---
   y se reanuda solo. Como el avance se calcula con el tiempo transcurrido de
   verdad y ese tiempo no se acumula mientras se espera, al reanudar no hay
   salto: se sigue donde se dejo.

   QUE NO ES ESPERAR. Una respuesta que llego y vino vacia no es una espera: es
   una vuelta sin datos, y se sigue. Un fallo tampoco: se avisa y se sigue. Solo
   se espera lo que esta en camino.
   ============================================================ */
function vueltaEnFraccion(f) {
  const inicios = iniciosDeVuelta();
  let i = 0;
  for (let k = 0; k < inicios.length; k++) if (f >= inicios[k] - 1e-9) i = k;
  return estado.vueltas[i] ? estado.vueltas[i].numero : 1;
}

/* SE PREGUNTA POR DONDE SE VA A PISAR, NO POR DONDE SE PISO.
   Comprobandolo despues de mover, el cabezal ya habia entrado en la vuelta sin
   datos y el cuadro ya se habia pintado vacio: los cuatro graficos decian «sin
   dato en esta vuelta» y los medidores, rayas. Preguntando antes, el ultimo
   cuadro coherente ---el final de la vuelta anterior--- se queda intacto en
   pantalla mientras se espera. */
function faltaLoImprescindible(fraccion) {
  if (estadoSesion !== "cargado") return false;
  /* Esperar es esperar **algo que esta en camino**. Sin eje de distancia no se
     pidio nada y no se va a pedir: quedarse en «Preparando la vuelta 1…» para
     siempre seria una espera sin nada que esperar. */
  if (!hayEjeDeDistancia()) return false;
  const v = fraccion === undefined ? instante().vuelta : vueltaEnFraccion(fraccion);
  if (estado.series[v]) return false;          // ya esta
  if (estado.fallo && estado.fallo[v]) return false;  // fallo: no se espera mas
  return true;
}

/* La espera se corta sola cuando llegan los datos, y tambien cuando alguien
   decide otra cosa: pausa, seek, cambio de sesion o de etapa. Una respuesta
   atrasada no puede reanudar lo que una persona detuvo. */
let _esperandoVuelta = null;

/* Devuelve `true` solo la primera vez que se entra a esperar esta vuelta. El
   bucle de animacion corre sesenta veces por segundo y no puede pedir en cada
   una: la deduplicacion por `estado.pidiendo` lo tapaba, pero pedir sesenta
   veces algo que ya se pidio sigue siendo trabajo por nada, y en cuanto la
   marca se libera ---al fallar, por ejemplo--- se convierte en una tormenta. */
function anotarEspera(v) {
  if (_esperandoVuelta === v) return false;
  _esperandoVuelta = v;
  decirEstadoApi("Preparando la vuelta " + v + "…", false);
  return true;
}

function soltarEspera() {
  if (_esperandoVuelta === null) return;
  _esperandoVuelta = null;
  decirEstadoApi(etiquetaDeCorrida() === "todo junto"
    ? SESIONES.length + " sesiones en el catálogo"
    : "Mirando « " + etiquetaDeCorrida() + " »", false);
}

/* Donde esta cada vehiculo en este instante, en metros de la vuelta. */
/* ============================================================
   LA POSICION SE INTERPOLA ENTRE MUESTRAS VALIDAS
   ------------------------------------------------------------
   `/posiciones` entrega doscientos puntos por vuelta. Elegir el mas cercano
   deja al coche quieto entre muestra y muestra y despues lo teletransporta:
   sobre una vuelta de noventa segundos son unos dos movimientos por segundo, y
   se ve como una figura que salta.

   Medido el 2026-09-08 antes de esto: en 300 s de reproduccion el trazado se
   pinto 17.844 veces y la marca del vehiculo cambio de sitio **34**. Cero coma
   uno por segundo. Los sesenta cuadros por segundo eran ciertos y no
   significaban nada: se estaba redibujando lo mismo.

   QUE SE INTERPOLA Y QUE NO. Solo entre **dos muestras validas y
   consecutivas**, y solo si la distancia entre ellas es la de un intervalo
   normal. No se une por encima de un hueco de captura ---ahi no se sabe por
   donde fue--- ni del cruce de meta, donde la distancia vuelve a cero: en los
   dos casos se muestra la ultima posicion medida y se deja de inventar.

   ESTO ES REPRESENTACION, NO DATO. `estado.posiciones` queda intacto: lo que
   se interpola es donde se pinta el circulo, y el panel lo declara. Nada de
   esto llega al analisis ni a la exportacion, que siguen leyendo las muestras.
   ============================================================ */
let _huboInterpolacion = false;

/* CADA MUESTRA, EN EL INSTANTE EN QUE SE MIDIO.
   ------------------------------------------------------------
   La respuesta trae `puntos+1` distancias, una por intervalo, y **cuando** se
   midio cada una. Antes solo traia las distancias, de modo que el unico camino
   era suponerlas repartidas en partes iguales dentro de la vuelta. No lo estan:
   cada una es la primera muestra de su intervalo, y esa cae donde cae.

   Suponerlas parejas corre cada punto hasta medio intervalo ---en una vuelta de
   Spa con 200 intervalos, hasta 340 ms--- y ese corrimiento no es constante:
   cambia de un punto al siguiente, que es lo que se ve como un tiron.

   Se arma una vez por respuesta ---`_pares` queda en el objeto que devolvio la
   API--- y se guarda solo lo que tiene dato: los huecos dejan de ser un caso
   especial y pasan a ser, simplemente, dos muestras mas separadas. */
function paresDePosicion(d, clave) {
  if (!d._pares) d._pares = {};
  if (d._pares[clave]) return d._pares[clave];
  const serie = d.vehiculos[clave] || [];
  const marcas = (d.instantes_ms && d.instantes_ms[clave]) || null;
  const total = numeroMedido(d.intervalo_ms) !== null && numeroMedido(d.puntos) !== null
    ? d.intervalo_ms * d.puntos : null;
  const pares = [];
  for (let i = 0; i < serie.length; i++) {
    const v = numeroMedido(serie[i]);
    if (v === null) continue;
    /* Sin instantes ---una API mas vieja--- se cae en la rejilla pareja, que es
       lo que habia. Se declara en `aproximado` para no presentar una suposicion
       como una medicion. */
    const t = marcas && numeroMedido(marcas[i]) !== null
      ? marcas[i]
      : (total !== null && serie.length > 1 ? total * (i / (serie.length - 1)) : i);
    pares.push([t, v]);
  }
  const armado = { pares: pares, aproximado: !marcas, duracion: total };
  d._pares[clave] = armado;
  return armado;
}

function posicionesAhora() {
  const t = instante();
  const d = estado.posiciones[t.vuelta];
  if (!d) return null;
  const salida = {};
  const largo = PISTA.largo_m || 0;
  _huboInterpolacion = false;

  /* EL MISMO INSTANTE QUE LOS INSTRUMENTOS, Y POR ESO EN UTC.
     `instantes_ms` cuenta desde `desde_utc`, que es el primer instante de la
     vuelta; el instante compartido es una marca UTC absoluta. Restando una de
     la otra, la marca del coche y la velocidad se leen en el mismo momento.

     Sin `desde_utc` ---una API mas vieja--- se cae en lo que habia: la fraccion
     de vuelta repartida sobre la ventana de la respuesta. Eso supone que la
     fraccion efectiva del transporte y el intervalo UTC bruto de la vuelta son
     la misma escala, y con un hueco de captura en el medio no lo son. */
  if (d._baseUtc === undefined) {
    d._baseUtc = d.desde_utc ? Date.parse(d.desde_utc) : NaN;
  }
  const relativo = (t.tUtcMs !== null && t.tUtcMs !== undefined &&
                    Number.isFinite(d._baseUtc)) ? t.tUtcMs - d._baseUtc : null;

  Object.keys(d.vehiculos).forEach(clave => {
    const { pares, duracion } = paresDePosicion(d, clave);
    if (!pares.length) return;
    const objetivo = relativo !== null ? relativo
                   : (duracion !== null ? t.fraccion * duracion
                                        : t.fraccion * (pares.length - 1));

    /* La muestra anterior al instante buscado. Busqueda binaria: con 201 puntos
       por vuelta y veinte vehiculos, recorrerlas linealmente en cada cuadro es
       trabajo que se hace sesenta veces por segundo para nada. */
    let lo = 0, hi = pares.length - 1;
    while (lo < hi) {
      const medio = (lo + hi + 1) >> 1;
      if (pares[medio][0] <= objetivo) lo = medio; else hi = medio - 1;
    }
    const a = pares[lo];
    const b = pares[lo + 1];
    if (!b) { salida[clave] = a[1]; return; }

    const dt = b[0] - a[0];
    const salto = b[1] - a[1];
    /* EL TOPE SE MIDE CONTRA EL TIEMPO QUE PASO, NO CONTRA UN INTERVALO SUPUESTO.
       Antes era `largo / n * 3`, que da lo mismo para dos muestras separadas
       50 ms que para dos separadas medio segundo. Ahora es tres veces lo que se
       recorreria a ritmo medio en ese hueco: un salto mayor no es la muestra
       siguiente, es la vuelta que se cierra o un tramo que falta. */
    const tope = (largo && duracion && dt > 0) ? (largo * (dt / duracion)) * 3 : Infinity;
    if (dt > 0 && salto >= 0 && salto <= tope) {
      const u = Math.min(1, Math.max(0, (objetivo - a[0]) / dt));
      salida[clave] = a[1] + salto * u;
      if (u > 0) _huboInterpolacion = true;
      return;
    }
    /* Ni se interpola sobre el cierre de vuelta ni se fuerza que crezca: se
       queda en la ultima medida hasta que la siguiente sea contigua. */
    salida[clave] = a[1];
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
function pieDeExportacion(vista) {
  const s = estado.abierta;
  if (!s) return "sin sesión abierta";
  const partes = [nombreDeSesion(s), s.session_id];
  /* CON UNA VISTA, SE DESCRIBE LO QUE ESA VISTA CUBRE.
     Sin ella el pie decia siempre «vuelta N de M» y los puntos de esa vuelta:
     en una exportacion de la carrera entera eso nombraba una vuelta que no era
     la unica dibujada y contaba una fraccion de lo que se ve. Y si estan
     cargadas siete de veintidos, se dice, porque presentar una cobertura
     parcial como completa es afirmar de mas. */
  if (vista && vista.alcance === "carrera") {
    const hay = vueltasDeLaSesion();
    partes.push(vista.vueltas.length === hay
      ? vista.vueltas.length + " vueltas"
      : vista.vueltas.length + " de " + hay + " vueltas cargadas");
  } else if (hayVueltas()) {
    partes.push("vuelta " + vueltaElegida + " de " + vueltasDeLaSesion());
  }
  if (vista && vista.ids && vista.ids.length) {
    partes.push((vista.ids.length === 1 ? "vehículo " : "vehículos ") +
      vista.ids.map(id => ((AUTOS.find(a => a.id === id) || {}).nombre) || claveCorta(id))
        .join(", "));
  } else {
    partes.push("vehículo " + autoPropio().nombre);
  }
  if (vista && !vista.vacia) {
    /* Los puntos que de verdad se dibujaron en el tramo visible, no los de una
       vuelta cualquiera. */
    let n = 0, reducido = false;
    vista.paneles.forEach(pa => pa.porVehiculo.forEach(segs => segs.forEach(seg => {
      seg.forEach(pt => { if (pt[0] >= vista.xMin && pt[0] <= vista.xMax) n++; });
    })));
    Object.keys(estado.series).forEach(k => {
      if (estado.series[k] && estado.series[k].submuestreado) reducido = true;
    });
    if (n) partes.push(cifra(n, 0) + " puntos" + (reducido ? " submuestreados" : ""));
    return partes.join(" · ");
  }
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
  const bin = fuente === "can";
  const crudas = ids.map(id => derivar(null, canalId, vueltaElegida, id));
  const extremos = extremosDeDistancia(crudas);
  const [ampIni, ampFin] = dominioAmpliado(extremos);
  let datos = crudas.map(d => recortarPorDominio(d, ampIni, ampFin));
  if (bin && (canalId === "throttle" || canalId === "brake")) {
    datos = datos.map(d => d.map(p => [p[0], p[1] > 40 ? 1 : 0]));
  }
  const escala = escalaDe(datos, 0.08);
  const vistos = extremosDeDistancia(datos);
  // Una lamina de un canal sin muestras no se exporta: seria una hoja con ejes
  // y nada adentro, firmada como si fuera una medicion.
  if (!escala || !vistos) {
    avisar("Ese canal no tiene muestras en esta vuelta: no hay lámina que exportar", true);
    return;
  }
  const mn = escala.mn, mx = escala.mx;
  const d0 = vistos[0], d1 = vistos[1];
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
      const metro = metroDeCurva(cu);
      if (metro === null || metro < d0 || metro > d1) return;
      if (puestas.indexOf(cu.nombre) !== -1) return;
      puestas.push(cu.nombre);
      const x = X0 + ((metro - d0) / (d1 - d0)) * ancho;
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
  /* EL EJE ES LA DISTANCIA, NO LA POSICION EN EL ARREGLO.
     `i / (d.length - 1)` estira cada serie hasta ocupar todo el ancho: dos
     vehiculos con distinta cantidad de muestras quedaban dibujados uno encima
     del otro **como si estuvieran alineados**, y sobre una lamina que se
     exporta y se mira despues eso no se puede notar. */
  const anchoX = Math.max(1e-9, d1 - d0);
  const enXLamina = m => X0 + ((m - d0) / anchoX) * ancho;
  const escalonadaLamina = esCanalEscalonado(canalId);
  datos.forEach((d, ai) => {
    ctx.beginPath();
    trazarSerie(ctx, reducirAAncho(d, d0, d1, ancho), enXLamina,
                v => Y1 - ((v - mn) / (mx - mn)) * alto, escalonadaLamina);
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
    const sec = secundarioDeVehiculo(a);
    ctx.fillText(sec, lx + 56 + w1, ly);
    lx += 46 + w1 + 10 + ctx.measureText(sec).width + 44;
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
/* Como se llama el archivo. Decia siempre «-vuelta-N» aunque lo exportado
   fuera la carrera entera sobre el eje de tiempo. */
function nombreDeLaLamina(vista) {
  const que = modoDetalle ? "senales" : "comparacion";
  const cubre = vista.alcance === "carrera" ? "carrera" : "vuelta-" + vueltaElegida;
  const eje = vista.eje === "distancia" ? "distancia" : "tiempo";
  return [que, cubre, eje].concat(vista.conZoom ? ["tramo"] : []).join("-") + ".png";
}

function exportarComparacion() {
  /* LA MISMA VISTA QUE LA PANTALLA, Y NO UNA RECONSTRUIDA. */
  const vista = vistaDeComparacion();
  const ids = vista.ids, activas = vista.activas;
  if (!ids.length) { avisar("Elegí al menos un vehículo antes de exportar.", true); return; }
  if (!activas.length) { avisar("Encendé al menos una métrica antes de exportar.", true); return; }
  if (vista.vacia) { avisar("No hay muestras para exportar en lo que estás mirando.", true); return; }

  /* Abajo entra ademas la explicacion de las franjas, que puede ocupar dos o
     tres renglones: se mide cuantos y se reserva el alto antes de crear el
     lienzo, porque despues ya no se puede crecer. */
  const IZQ = 150, DER = 60, ARRIBA = 140;
  const ALTO_PANEL = 190;
  const ancho = 1800 - IZQ - DER;

  const d0 = vista.xMin, d1 = vista.xMax;
  /* Las mismas franjas que en pantalla y con el mismo eje y alcance, que ahora
     viajan como argumento. `ancho` es el de la lamina, que es mayor: puede
     entrar el detalle de referencia donde en pantalla entraba el de vuelta, y
     esta bien que asi sea ---la regla es «si se lee, se pinta»--- pero el texto
     que la acompaña dice cual de las dos cosas se pinto. */
  const [bandasDeLaLamina, notaDeLaLamina] =
    bandasParaElTramo(d0, d1, ids[0], ancho, vista.eje, vista.alcance);

  const medidor = document.createElement("canvas").getContext("2d");
  medidor.font = "17px 'IBM Plex Sans', sans-serif";
  const renglones = partirEnRenglones(medidor, notaDeLaLamina, ancho);
  const ABAJO = 160 + renglones.length * 24;

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
  /* NO SE LLAMA «VUELTA N» A UNA EXPORTACION DE LA CARRERA ENTERA. */
  const queCubre = vista.alcance === "carrera"
    ? (vista.vueltas.length === 1 ? "1 vuelta" : vista.vueltas.length + " vueltas")
    : "vuelta " + vueltaElegida;
  ctx.fillText(
    nombreDeSesion(estado.abierta || {}) + " · " + queCubre + " · " +
    (vista.eje === "distancia" ? "eje de distancia" : "eje de tiempo") +
    (vista.conZoom ? " · tramo ampliado" : "") + " · " +
    FUENTES[fuente].nombre + " · " + activas.length + " métricas · " + fechaAr(new Date()),
    IZQ, 98);

  /* EL ZOOM ES UN TRAMO DE METROS, NO UN TRAMO DE ARREGLO.
     `zoom` viene como dos fracciones de la vuelta, y se las convertia en
     indices sobre la velocidad del primer vehiculo. Ese par de indices se
     aplicaba despues a **todos** los canales de **todos** los vehiculos, que
     no tienen ni la misma cantidad de muestras ni las mismas distancias. El
     resultado es que cada panel de la comparacion mostraba un tramo distinto
     de la vuelta, alineados solo en apariencia ---y comparar es exactamente lo
     que esta pantalla existe para hacer. */
  const bin = fuente === "can";
  const paleta = ["--auto-1", "--auto-2", "--auto-3", "--auto-4"];

  activas.forEach((m, pi) => {
    const Y0 = ARRIBA + pi * ALTO_PANEL;
    const Y1 = Y0 + ALTO_PANEL - 34;
    const alto = Y1 - Y0;

    /* LOS SEGMENTOS SON LOS DE LA VISTA, uno por vehiculo y por tramo continuo:
       asi se conservan los huecos ---dos tramos que no se tocan no se unen--- y
       el eje y el alcance que la pantalla esta usando. */
    let datos = vista.paneles[pi].porVehiculo.map(segs => segs.map(
      seg => seg.filter(pt => pt[0] >= d0 && pt[0] <= d1)));
    if (bin && (m.id === "throttle" || m.id === "brake")) {
      datos = datos.map(segs => segs.map(d => d.map(p => [p[0], p[1] > 40 ? 1 : 0])));
    }
    const escalaM = escalaDe(datos.map(segs => [].concat.apply([], segs)), 0.08);
    // Un canal sin muestras en el tramo elegido deja su panel rotulado y
    // vacio: es distinto de dibujar una linea plana en cero.
    if (!escalaM) {
      ctx.fillStyle = tinta("--texto-tenue");
      ctx.font = "22px 'IBM Plex Sans', sans-serif";
      ctx.fillText("sin muestras en este tramo", IZQ + 12, Y0 + alto / 2);
      return;
    }
    const mn = escalaM.mn, mx = escalaM.mx;
    const dec = ["glong", "glat", "gvert", "gap", "slip", "steer"].indexOf(m.id) !== -1 ? 2 : 0;

    /* Las mismas franjas que en pantalla, y por la misma razon: una imagen se
       pega en otro lado y ahi el pie es lo unico que viaja con ella. Si la
       pantalla dice de que tramo es cada parte y la lamina no, las dos dejan de
       ser la misma figura. */
    if (bandasDeLaLamina) {
      pintarZonas(ctx, bandasDeLaLamina, d0, d1, IZQ, ancho, Y0, Y1);
    }

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

    // El borde de cada franja, de arriba abajo: un mismo metro se sigue entre
    // paneles apilados, que es la razon de apilarlos.
    if (bandasDeLaLamina) {
      ctx.strokeStyle = tinta("--linea-fuerte");
      ctx.setLineDash([5, 6]); ctx.globalAlpha = .42; ctx.lineWidth = 1.3;
      bandasDeLaLamina.forEach(b => {
        if (b.ini < d0 || b.ini > d1) return;
        const x = IZQ + ((b.ini - d0) / Math.max(1e-9, d1 - d0)) * ancho;
        ctx.beginPath(); ctx.moveTo(x, Y0); ctx.lineTo(x, Y1); ctx.stroke();
      });
      ctx.setLineDash([]); ctx.globalAlpha = 1;
    }

    // Mismo criterio que en la lamina: el eje es el tramo de metros elegido,
    // y comparar es justamente lo que esta pantalla existe para hacer.
    const anchoX = Math.max(1e-9, d1 - d0);
    const escalonadaComp = esCanalEscalonado(m.id);
    datos.forEach((segs, ai) => {
      ctx.strokeStyle = tinta(paleta[ai % 4]);
      ctx.lineWidth = 2.2;
      ctx.lineJoin = "round";
      /* Un trazo por tramo: dos vueltas que no se tocan no se unen con una
         recta que nadie midio. La pantalla ya lo hacia asi. */
      segs.forEach(d => {
        if (!d.length) return;
        ctx.beginPath();
        trazarSerie(ctx, reducirAAncho(d, d0, d1, ancho),
                    x0 => IZQ + ((x0 - d0) / anchoX) * ancho,
                    v => Y1 - ((v - mn) / (mx - mn)) * alto, escalonadaComp);
        ctx.stroke();
      });
    });
  });

  /* UN SOLO EJE, ROTULADO CON LO QUE DE VERDAD SE ESTA MIRANDO.
     Decia «DISTANCIA RECORRIDA · METROS» tambien con el eje de tiempo puesto, y
     escribia numeros de metros sobre valores que eran segundos. */
  const yEje = ARRIBA + ALTO_PANEL * activas.length - 30;
  ctx.textAlign = "center";
  ctx.font = "18px 'IBM Plex Mono', monospace";
  for (let i = 0; i <= 8; i++) {
    const x = IZQ + (ancho * i) / 8;
    ctx.fillStyle = tinta("--texto-medio");
    ctx.fillText(vista.formatearEje(d0 + ((d1 - d0) * i) / 8), x, yEje + 8);
  }
  ctx.fillStyle = tinta("--texto-medio");
  ctx.font = "600 21px 'Saira Condensed', sans-serif";
  ctx.fillText(vista.rotuloDelEje, IZQ + ancho / 2, yEje + 42);

  /* Los nombres de las referencias ya los escribe `pintarZonas` dentro de su
     franja, con el mismo dominio. La lista rotada que habia aca los repetia
     ---y en el eje de tiempo los ponia sobre coordenadas que no eran metros. */

  /* La leyenda sube tanto como ocupe la explicacion: el alto ya se reservo al
     crear el lienzo, y sin este corrimiento el ultimo renglon caia fuera de la
     imagen. Medido: con dos renglones, «aparecen.» quedaba cortado por abajo. */
  let lx = IZQ;
  const altoExplicacion = renglones.length * 24;
  const ly = cv.height - 46 - altoExplicacion;
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
    const sec = secundarioDeVehiculo(a);
    ctx.fillText(sec, lx + 56 + w1, ly);
    lx += 46 + w1 + 10 + ctx.measureText(sec).width + 44;
  });

  ctx.fillStyle = tinta("--texto-tenue");
  ctx.font = "17px 'IBM Plex Sans', sans-serif";
  ctx.textAlign = "right";
  ctx.fillText(pieDeExportacion(vista), IZQ + ancho, ly);

  /* QUE SON LAS FRANJAS, ESCRITO EN LA IMAGEN.
     El archivo se abre sin el tablero al lado: quien lo mire tiene que poder
     distinguir una franja por vuelta de un intervalo entre referencias, y saber
     cuando no hay franjas porque el eje es temporal. El texto se parte en
     renglones medidos y el alto de la lamina ya se reservo para ellos, de modo
     que no se corta ni se monta sobre la leyenda ni sobre la procedencia. */
  if (renglones.length) {
    ctx.textAlign = "left";
    ctx.fillStyle = tinta("--texto-tenue");
    ctx.font = "17px 'IBM Plex Sans', sans-serif";
    renglones.forEach((linea, i) => {
      ctx.fillText(linea, IZQ, ly + 30 + i * 24);
    });
  }

  cv.toBlob(blob => {
    if (!blob) { avisar("No se pudo generar la imagen.", true); return; }
    guardar(nombreDeLaLamina(vista), blob, "Imagen guardada");
  }, "image/png");
}

/* ============================================================
   LA EXPORTACION SE ALINEA POR DISTANCIA
   ------------------------------------------------------------
   Esto recorria las columnas por posicion: `col[i]` contra la muestra `i` de
   la velocidad del primer vehiculo. Y las columnas **no tienen la misma
   longitud**: `serieDeCanal` descarta las muestras nulas, de modo que un canal
   con huecos queda mas corto y desde el primer hueco todo lo que sigue se
   corre un lugar. Una fila del archivo podia juntar los 100 m de velocidad con
   los 300 m de acelerador, con aspecto perfectamente normal.

   Es el peor sitio posible para ese error, porque el archivo se abre despues
   en otra herramienta, donde ya no hay forma de notarlo.

   Ahora la distancia es la clave, no el indice. Cada columna se consulta por
   el metro de la fila; si ese canal no tiene medicion en ese metro, la celda
   queda **vacia**. Una celda vacia dice «no se midio»; un cero diria otra
   cosa.
   ============================================================ */
function exportarCsv() {
  const ids = [...seleccion];
  const canales = canalesDeLaFuente().filter(id => elegidos()[id]);
  if (!ids.length || !canales.length) {
    avisar("No hay canales seleccionados para exportar", true);
    return;
  }

  const cab = ["distancia_m"];
  const columnas = [];
  ids.forEach(id => {
    const a = AUTOS.find(x => x.id === id) || AUTOS[0];
    canales.forEach(c => {
      /* EL CSV EXPORTA LO QUE LA FUENTE MANDO, EN SU UNIDAD Y CON SU
         ENCABEZADO. Cuando la conversion se hacia sobre el bloque guardado,
         este archivo empezo a decir 2,937 donde la base guarda 2937, y con un
         sufijo de unidad que nadie pidio. Un archivo que se lleva a otro lado
         no puede cambiar de contrato porque un panel cambio de rotulo: se lee
         la serie **cruda** y el encabezado vuelve a ser `<vehiculo>_<senal>`.
         Lo unico que cambia es el nombre del vehiculo, que ahora es el que la
         captura declara en vez del indice interno del protocolo. */
      cab.push((a ? a.nombre : id) + "_" + nombreDeSenal(c));
      const porMetro = new Map();
      (serieCrudaDeCanal(c, vueltaElegida, id) || []).forEach(p => {
        if (Number.isFinite(p[0]) && Number.isFinite(p[1])) porMetro.set(p[0], p[1]);
      });
      columnas.push(porMetro);
    });
  });

  // El eje de filas es la union de las distancias que de verdad se midieron.
  const metros = new Set();
  columnas.forEach(col => col.forEach((_v, m) => metros.add(m)));
  if (!metros.size) {
    avisar("No hay muestras que exportar en esta vuelta", true);
    return;
  }
  const orden = [...metros].sort((a, b) => a - b);

  const filas = [cab.join(",")];
  orden.forEach(m => {
    const fila = [m];
    columnas.forEach(col => fila.push(col.has(m) ? col.get(m).toFixed(3) : ""));
    filas.push(fila.join(","));
  });
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
  /* EN VIVO NO HAY UNA VUELTA CONSULTADA, Y NO TIENE QUE HABERLA.
     Esto exigia el bloque historico de la vuelta para dibujar cualquier cosa.
     Durante una sesion en vivo `estado.series` esta vacio a proposito ---se lo
     limpia al cambiar de sesion--- de modo que las muestras que estaban
     llegando por el flujo no se dibujaban nunca: los cuatro graficos decian
     «sin dato» mientras la fuente entregaba mil setecientas señales por
     segundo. */
  const enVivo = estadoSesion === "vivo";
  /* NO SE BORRA LO QUE SE PUEDE SEGUIR DIBUJANDO.
     Esto exigia el bloque de la vuelta bajo el cabezal y, si faltaba, vaciaba
     los cuatro lienzos. Al cruzar la meta con la vuelta siguiente todavia en
     viaje, eso borraba los 1.200 m anteriores que estaban en memoria. Con la
     ventana movil sobre el eje acumulado, la vuelta anterior alcanza para
     dibujar; solo cuando no hay **nada** cargado se pinta la espera, que es la
     carga inicial y esa si hay que declararla. */
  const hayAlgoQueDibujar = enVivo || estado.series[vueltaElegida] ||
    (ventanaTraza && Object.keys(estado.series).length > 0);
  if (!hayAlgoQueDibujar) { pintarEsperando(); return; }

  /* SE GRAFICA A QUIEN TIENE SERIE, NO A QUIEN ESTA SELECCIONADO.
     La seleccion decide a quien mostrar sobre el trazado, y ahi hay vehiculos
     de los que la fuente publica posicion y nada mas. Tomarla tal cual dejaba
     los cuatro graficos en blanco sobre una vuelta que si estaba cargada.

     Ademas `series[0]` reventaba con la lista vacia, dentro de una promesa
     cuyo `.catch` se traga el error: quedaba en blanco sin decir nada. */
  const disponibles = vehiculosConTraza();
  let ids = [...seleccion].filter(id => disponibles.indexOf(id) !== -1);
  if (!ids.length && disponibles.length) {
    const propio = claveVehiculoPropio();
    ids = [disponibles.indexOf(propio) !== -1 ? propio : disponibles[0]];
  }
  if (!ids.length) { pintarEsperando(); return; }
  const paleta = ["--auto-1", "--auto-2", "--auto-3", "--auto-4"];
  const bin = fuente === "can";
  const enPantalla = [];

  activos.forEach(canal => {
    const cv = LIENZOS[canal];
    if (!cv) return;
    const m = METRICAS.find(x => x.id === canal);
    const w = cv.clientWidth || 240, h = cv.clientHeight || 104;
    const ctx = ajustarLienzo(cv, w, h);
    ctx.clearRect(0, 0, w, h);

    /* CADA CANAL SE RECORTA CON SU PROPIO DOMINIO.
       Cada vehiculo trae este canal con la cantidad de muestras que trae, que
       no es la de otro vehiculo ni la de otra señal. */
    const escalonada = esCanalEscalonado(canal);
    /* EL EJE DE LA VENTANA MOVIL ES EL ACUMULADO; EL DE LA VUELTA COMPLETA, NO.
       Con ventana se mira «los ultimos tantos metros», y esos metros cruzan la
       meta: el eje tiene que ser uno que no se reinicie. Sin ventana se mira
       **la vuelta**, y ahi el eje es el de la vuelta, que es lo que sus
       etiquetas y su cabezal significan. */
    const conAcumulada = !!(ventanaTraza && !enVivo &&
                            instante().metroSesion !== null &&
                            instante().metroSesion !== undefined);
    const crudas = ids.map(id => derivar(null, canal, vueltaElegida, id));
    const extremos = extremosDeDistancia(crudas);
    const [ampIni, ampFin] = dominioAmpliado(extremos);
    let datos = crudas.map(d => recortarPorDominio(d, ampIni, ampFin));
    const binario = bin && (canal === "throttle" || canal === "brake");
    if (binario) {
      datos = datos.map(d => d.map(p => [p[0], p[1] > 40 ? 1 : 0]));
    }
    /* LOS DOS EXTREMOS DE LO QUE SE VE, ANTES QUE LA ESCALA.
       Con ventana, los ultimos N metros de sesion; sin ventana, la vuelta
       entera en metros de vuelta. */
    const ti = instante();
    const vistosLocal = extremosDeDistancia(datos);
    let vFin, vIni, tramos;
    if (conAcumulada) {
      vFin = ti.metroSesion;
      vIni = vFin - ventanaTraza;
      tramos = ids.map(id => {
        const t = trazaContinua(canal, id, vIni, vFin);
        return binario ? t.map(x => x.map(p => [p[0], p[1] > 40 ? 1 : 0])) : t;
      });
      /* Lo que aporto a esta ventana no se poda: se la sigue viendo. */
      vueltasEnTramoAcumulado(vIni, vFin, ids[0]).forEach(v => {
        if (enPantalla.indexOf(v) === -1) enPantalla.push(v);
      });
    } else {
      vFin = ventanaTraza ? ti.metro : (vistosLocal ? vistosLocal[1] : 1);
      vIni = ventanaTraza ? Math.max(0, ti.metro - ventanaTraza) : 0;
      tramos = datos.map(d => [d]);
    }
    const anchoV = Math.max(1, vFin - vIni);

    /* LA ESCALA ES LA DE LAS VUELTAS QUE ESTAN EN PANTALLA.
       Antes era la de la vuelta bajo el cabezal, de modo que al cruzar la meta
       saltaba entera a la envolvente de la vuelta nueva ---de golpe, y por
       cambiar de vuelta y no por lo que se ve---. Ahora es la union de las
       vueltas que aportan a la ventana, tomando cada una **completa** y no el
       trozo visible: asi no respira con el desplazamiento, cambia como mucho
       una vez por vuelta y solo por la diferencia entre dos vueltas vecinas. No
       recorta picos ni obliga a traer la carrera entera: son las vueltas que ya
       estan cargadas. */
    const paraEscala = conAcumulada
      ? ids.map(id => {
          const junto = [];
          vueltasEnTramoAcumulado(vIni, vFin, id).forEach(v => {
            const s = serieAcumuladaDeCanal(canal, v, id) || [];
            for (let i = 0; i < s.length; i++) junto.push(s[i]);
          });
          return binario ? junto.map(p => [p[0], p[1] > 40 ? 1 : 0]) : junto;
        })
      : datos;
    const escala = escalaDe(paraEscala, 0.1);
    if (!escala) { vaciarLienzo(canal, enVivo ? "esperando esta señal" : "sin dato en esta vuelta"); return; }
    const mn = escala.mn, mx = escala.mx;

    // rejilla
    ctx.strokeStyle = tinta("--linea"); ctx.lineWidth = 1;
    for (let i = 0; i <= 2; i++) {
      const y = 4 + (h - 8) * (i / 2);
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
    }

    /* LAS CURVAS ESTAN EN METROS DE VUELTA, Y EL EJE PUEDE NO ESTARLO.
       Una curva a 405 m es a 405 m **de cada vuelta**: sobre el eje acumulado
       hay que correrla con el desplazamiento medido de la vuelta que se este
       mirando, y por eso puede aparecer mas de una vez en una ventana que cruza
       la meta. Ponerla directamente en 405 sobre metros de sesion la dejaria en
       la primera vuelta de la carrera para siempre. */
    if (CURVAS.length) {
      const enX0 = m => ((m - vIni) / anchoV) * w;
      const bases = conAcumulada
        ? vueltasEnTramoAcumulado(vIni, vFin, ids[0])
            .map(v => { const t = tramoAcumuladoDeVuelta(v, ids[0]); return t ? t.desfase : null; })
            .filter(d => d !== null)
        : [0];
      ctx.strokeStyle = tinta("--linea-fuerte");
      ctx.globalAlpha = .35; ctx.setLineDash([2, 3]);
      CURVAS.forEach(cu => {
        bases.forEach(base => {
          const m = base + cu.metro_medido;
          if (m < vIni || m > vFin) return;
          const x = enX0(m);
          ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
        });
      });
      ctx.setLineDash([]); ctx.globalAlpha = 1;
    }

    /* UNA VENTANA QUE SE DESPLAZA, NO UNA VUELTA QUE SE ESCRIBE.
       Escribir la vuelta entera dejaba el trazo cada vez mas apretado a medida
       que avanzaba: los ultimos metros entraban en pixeles. Un instrumento en
       marcha muestra **los ultimos tantos metros** y los va corriendo, de modo
       que el detalle es el mismo al principio y al final.

       `ventanaTraza` dice cuantos metros entran. En cero entra la vuelta
       completa, que sigue siendo lo que se quiere para leerla despues. */
    const enX = m => ((m - vIni) / anchoV) * w;
    /* El cabezal de este canal se coloca sobre **este** eje: el acumulado con
       ventana, el de la vuelta sin ella. Antes se lo ponia en la fraccion
       temporal de la vuelta sobre un eje de metros, que son dos magnitudes
       distintas. */
    _ejeTraza[canal] = { ini: vIni, fin: vFin, acumulado: conAcumulada };

    /* CUANDO EL PRIMER GRAFICO SIRVE PARA ALGO.
       Es una medida distinta de «cuanto tardaron las consultas»: entre que la
       respuesta llega y que hay un trazo dibujado hay trabajo, y confundir las
       dos hace parecer rapido lo que no lo es. Se sella una sola vez, la
       primera vez que un canal tiene de verdad algo que trazar. */
    if (!document.body.dataset.primerTrazoMs && tramos.some(ts => ts.some(d => d.length > 1))) {
      document.body.dataset.primerTrazoMs = String(Math.round(performance.now()));
    }
    TESTIGO.dibujosDeTraza++;
    tramos.forEach((ts, ai) => {
      /* UN SUBTRAZO POR TRAMO CONTIGUO. Dos vueltas que se midieron seguidas
         llegan aca en un solo tramo y se dibujan de un trazo; dos que no se
         tocan llegan separadas y no se unen, porque la recta entre ellas seria
         un recorrido que nadie midio. */
      ctx.beginPath();
      let ultimo = null, cuantos = 0;
      ts.forEach(d => {
        // Reducida al ancho del lienzo, conservando minimo y maximo por columna:
        // un pico de una muestra sobrevive, que es lo que una anotacion señala.
        const dd = reducirAAncho(recortarConBordes(d, vIni, vFin, escalonada),
                                 vIni, vFin, w);
        trazarSerie(ctx, dd, enX,
                    v => (h - 6) - ((v - mn) / (mx - mn)) * (h - 12) + 3,
                    escalonada);
        cuantos += dd.length;
        if (dd.length) ultimo = dd[dd.length - 1];
      });
      /* EL TESTIGO MIRA LO QUE SE DIBUJA, NO LO QUE SE TENIA.
         La primera version firmaba el arreglo **antes** de recortarlo por la
         ventana: con la vuelta entera cargada ese arreglo no cambia nunca, de
         modo que el testigo decia «cero trazas con dato nuevo» mientras la
         ventana movil se desplazaba correctamente. Un testigo que mide otra
         cosa es peor que ninguno, porque parece evidencia. */
      if (ai === 0) {
        const firma = cuantos + ":" + (ultimo ? ultimo[0].toFixed(1) + ":" + ultimo[1] : "-");
        if (cv.dataset.firmaTestigo !== firma) {
          cv.dataset.firmaTestigo = firma;
          TESTIGO.trazasConDatoNuevo++;
        }
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
        '<span>mín <b>' + escala.minReal.toFixed(dec) + '</b></span>' +
        '<span>' + m.unidad + '</span>' +
        '<span>máx <b>' + escala.maxReal.toFixed(dec) + '</b></span>';
    }
  });
  anotarEnPantalla(enPantalla);
}

/* ============================================================
   EL LIENZO SE REDIMENSIONA CUANDO CAMBIA, NO CUANDO SE DIBUJA
   ------------------------------------------------------------
   Asignar `canvas.width` reasigna el buffer y borra el contenido **aunque el
   valor sea el mismo**. Estaba en cada dibujo de cada grafico: con ocho
   lienzos a sesenta cuadros por segundo son cuatrocientas ochenta
   reasignaciones por segundo de buffers que no cambiaron de tamano.

   La transformacion si se aplica siempre: es barata y depende del contexto,
   que se puede haber reseteado por otro motivo.
   ============================================================ */
function ajustarLienzo(cv, w, h) {
  const dpr = window.devicePixelRatio || 1;
  const aw = Math.max(1, Math.round(w * dpr));
  const ah = Math.max(1, Math.round(h * dpr));
  const ctx = cv.getContext("2d");
  if (cv.width !== aw || cv.height !== ah) { cv.width = aw; cv.height = ah; }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return ctx;
}

/* Un solo grafico sin dato. Se separa de `pintarEsperando` porque la ausencia
   es **por canal**: que no haya velocidad no dice nada sobre el regimen, y
   apagar los cuatro porque falta uno era exactamente el defecto. */
function vaciarLienzo(id, texto) {
  const cv = LIENZOS[id];
  if (!cv) return;
  const ctx = cv.getContext("2d");
  const w = cv.clientWidth || 240, h = cv.clientHeight || 104;
  ajustarLienzo(cv, w, h);
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = tinta("--texto-tenue");
  ctx.font = "11px 'IBM Plex Sans', sans-serif";
  ctx.fillText(texto, 10, h / 2);
  const pie = document.getElementById("pie-" + id);
  if (pie) pie.innerHTML = "<span>—</span><span></span><span>—</span>";
}

/* Mientras la vuelta viaja, cada grafico dice que esta esperando en vez de
   quedarse en blanco: en blanco no se distingue de «esta fuente no tiene esta
   señal», que es una afirmacion muy distinta. */
function pintarEsperando() {
  Object.keys(LIENZOS).forEach(id => {
    const cv = LIENZOS[id];
    if (!cv) return;
    const w = cv.clientWidth || 240, h = cv.clientHeight || 104;
    const ctx = ajustarLienzo(cv, w, h);
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = tinta("--texto-tenue");
    ctx.font = "11px 'IBM Plex Sans', sans-serif";
    ctx.fillText(!hayEjeDeDistancia() ? "sin eje de distancia en esta fuente"
                 : estado.cargando ? "cargando…" : "sin dato en esta vuelta",
                 10, h / 2);
    const pie = document.getElementById("pie-" + id);
    if (pie) pie.innerHTML = "<span>—</span><span></span><span>—</span>";
  });
}

/* Lo unico que cambia de un cuadro al siguiente en los graficos. */
/* Sobre que tramo de metros quedo dibujado cada canal. Lo escribe
   `dibujarTraza` y lo lee el cabezal: los dos tienen que hablar del mismo eje o
   la linea no cae donde cae el trazo. */
const _ejeTraza = {};

function moverCabezalesGraficos() {
  // Con ventana, el instante esta siempre al borde derecho ---es lo ultimo que
  // paso---. Sin ventana, en el metro de la vuelta que le toca.
  const visible = estadoSesion !== "vacio";
  const t = visible ? instante() : null;
  Object.keys(LIENZOS).forEach(id => {
    const c = document.getElementById("cabezal-" + id);
    if (!c) return;
    let pct;
    if (ventanaTraza) {
      pct = 100;
    } else if (!t) {
      pct = 0;
    } else {
      /* EN VUELTA COMPLETA EL EJE ES DE METROS, Y EL CABEZAL TAMBIEN.
         Estaba en `fraccion * 100`, que es la fraccion **temporal** de la
         vuelta puesta sobre un eje espacial. Un coche no recorre el circuito a
         ritmo parejo ---en Spa, la recta de Kemmel y la chicana del bus no se
         hacen a la misma velocidad---, de modo que a mitad del tiempo no esta a
         mitad del circuito: la linea marcaba un metro y el trazo debajo estaba
         en otro. Ahora va por la distancia de presentacion, que es continua y
         es la misma que corre la ventana. */
      const eje = _ejeTraza[id];
      pct = (eje && eje.fin > eje.ini)
        ? Math.max(0, Math.min(100, ((t.metro - eje.ini) / (eje.fin - eje.ini)) * 100))
        : t.fraccion * 100;
    }
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
  /* EL NOMBRE ES UN DATO, NO MARCADO.
     Mientras `nombre` era el sufijo del identificador tecnico ---«19»--- esto
     no podia ser otra cosa que digitos. Desde que sale del paquete de
     participantes de la captura es texto que escribio otro, y concatenarlo en
     `innerHTML` convertia un `<img src=x onerror=...>` en un elemento de esta
     pagina. Se escapa aca, en el borde donde el texto entra al marcado, y no
     en el dato: alterar el nombre para que un renderizador sea seguro
     ensuciaria la comparacion, el titulo accesible y el CSV. */
  if (leyenda) leyenda.innerHTML =
    nombres.map((n, i) => '<span><i style="background:' + paleta[i % 4] + '"></i>' +
      textoSeguro(n) + '</span>').join("");
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
    moverCabezal(indice / vueltasDeLaSesion(), true);
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
      '<div><div class="nom">' + textoSeguro(a.nombre) + '</div><div class="eq">' +
        textoSeguro(secundarioDeVehiculo(a)) + '</div></div>' +
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
  const cuales = vueltasParaComparar();
  const puntos = puntosParaVueltas(cuales.length);

  /* LO QUE SE VE PRIMERO SE PIDE PRIMERO.
     La vuelta bajo el cabezal es la que alguien esta mirando: si sale al final
     de la cola, la comparacion tarda en mostrar algo aunque ya hayan llegado
     quince vueltas que estan fuera de la pantalla. */
  const orden = cuales.slice().sort((a, b) =>
    Math.abs(a - vueltaElegida) - Math.abs(b - vueltaElegida));

  return enTandas(orden, SERIES_A_LA_VEZ, v => asegurarVuelta(v, puntos))
    .then(r => { pedirPintado("trazas"); return r; });
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

/* Un aviso centrado sobre el lienzo de comparacion. Tres sitios decian lo
   mismo con el mismo codigo repetido. */
function avisoDeComparacion(cv, ctx, texto) {
  const w = cv.clientWidth;
  if (cv.style.height !== "200px") cv.style.height = "200px";
  ajustarLienzo(cv, w, 200);
  ctx.clearRect(0, 0, w, 200);
  ctx.fillStyle = tinta("--texto-tenue");
  ctx.font = "14px 'IBM Plex Sans', sans-serif";
  ctx.fillText(texto, 20, 100);
  const pie = document.getElementById("nota-comparacion");
  if (pie) pie.textContent = "";
}

/* ============================================================
   QUE PARTE DEL CIRCUITO SE ESTA MIRANDO
   ------------------------------------------------------------
   EL PROBLEMA. Sobre la carrera entera el eje va de 76 a 154.163 m y la
   grafica es una sucesion de dientes: se ve **que** paso pero no **donde**.
   Con una linea de puntos por curva se resolvia en una vuelta ---y ni eso,
   porque leia un campo que no existe--- y sobre veintidos vueltas serian
   trescientas treinta lineas encima de la traza.

   QUE ES UNA ZONA, Y QUE NO ES. El catalogo publica **un metro por curva**:
   el que se midio, no un principio y un final. Una zona es entonces el tramo
   que **empieza** en una curva y termina donde empieza la siguiente, y eso es
   lo que dice su rotulo. No es la curva: es el tramo que abre. Inventarle un
   ancho a la curva ---por la frenada, por la G lateral--- seria fabricar una
   geometria que el catalogo no declara.

   SOBRE LA CARRERA, LAS ZONAS SE REPITEN CON EL DESPLAZAMIENTO MEDIDO. Cada
   vuelta aporta su juego, corrido por `tramoAcumuladoDeVuelta().desfase`, que
   sale de comparar las dos distancias que la fuente publica. Nada de
   `(vuelta - 1) x largo del circuito`.

   Y CUANDO NO ENTRAN, NO SE PINTAN. A veintidos vueltas cada zona mide seis
   pixeles: un rayado que no dice nada y tapa la traza. Debajo del ancho minimo
   se pintan las **vueltas**, que es lo que a esa escala si se puede
   identificar, y el pie declara cual de las dos cosas se esta viendo.
   ============================================================ */

/* Cuanto tiene que medir una banda para que valga la pena pintarla, y cuanto
   para que ademas entre su nombre. */
const ZONA_MINIMA_PX = 12;
/* El minimo absoluto: por debajo, ni el nombre mas corto se lee. El ancho que
   de verdad hace falta lo mide el propio texto. */
const ZONA_CON_ROTULO_PX = 26;

/* Los tramos entre curvas que caen en `[xMin, xMax]`, sobre el eje que se este
   usando. Devuelve `null` cuando no se los puede ubicar, que no es lo mismo que
   una lista vacia: `null` es «no se sabe» y se dice en el pie.

   EN EL EJE DE TIEMPO NO SE UBICAN. Una curva esta en un metro, no en un
   segundo, y el segundo en que cada piloto la cruza es distinto y cambia vuelta
   a vuelta. Pintar las zonas de uno sobre la traza del otro seria afirmar que
   pasaron por el mismo sitio al mismo tiempo. */
/* ============================================================
   QUE SE ESTA MIRANDO, RESUELTO UNA SOLA VEZ
   ------------------------------------------------------------
   EL DEFECTO. La pantalla y su exportacion armaban su propia vista, y no la
   misma. La pantalla lee `segmentosComparacion`, que respeta el eje y el
   alcance elegidos ---distancia de vuelta o acumulada, tiempo de vuelta o de
   sesion---; la lamina llamaba a `derivar(..., vueltaElegida, ...)`, que es
   siempre la distancia local de **una** vuelta. Con la carrera abierta y las
   vueltas 7 y 8 cargadas entre los 42.000 y los 56.000 m acumulados, el PNG
   salia con un eje de 0 a 7.000 m de la vuelta elegida mientras las franjas
   ---que si preguntaban por el alcance global--- esperaban coordenadas
   acumuladas: el tramo exportado no era el que estaba en pantalla.

   Y sobre el eje de tiempo era peor: la lamina seguia rotulando metros, y las
   franjas desaparecian porque el ayudante sabia que el eje era temporal.

   LA CORRECCION. Una funcion arma la vista ---quienes, que señales, que eje,
   que alcance, que dominio y que segmentos--- y las dos la usan. No quedan dos
   cuentas del dominio que puedan separarse, porque no queda mas que una. */
function vistaDeComparacion() {
  const ids = [...seleccion].slice(0, 4);
  /* Las que la fuente **trajo con dato**, no las que se espera que tenga. La
     lamina filtraba por `m.fuentes`, de modo que podia reservar un panel para
     un canal que en pantalla no estaba. */
  const activas = METRICAS.filter(m => m.activa && estado.disponibles.has(nombreDeSenal(m.id)));
  if (!ids.length || !activas.length) {
    return { ids: ids, activas: activas, vacia: true };
  }

  /* Los segmentos salen de `segmentosComparacion`, que es la unica que sabe
     traducir eje y alcance a numeros. Se piden una vez por panel y vehiculo y
     se guardan: el dominio, la escala y el trazo tienen que mirar lo mismo. */
  const paneles = activas.map(m => ({
    metrica: m,
    porVehiculo: ids.map(id => segmentosComparacion(m.id, id)),
  }));

  let xMin = Infinity, xMax = -Infinity;
  paneles.forEach(p => p.porVehiculo.forEach(segs => segs.forEach(seg => seg.forEach(pt => {
    if (pt[0] < xMin) xMin = pt[0];
    if (pt[0] > xMax) xMax = pt[0];
  }))));
  if (!Number.isFinite(xMin) || !Number.isFinite(xMax)) {
    return { ids: ids, activas: activas, paneles: paneles, vacia: true };
  }

  const completo = [xMin, xMax];
  if (zoom) {
    const amplitud = xMax - xMin;
    xMax = xMin + amplitud * zoom[1];
    xMin = xMin + amplitud * zoom[0];
  }

  const enDistancia = ejeComparacion === "distancia";
  const deLaCarrera = alcanceComparacion === "carrera";
  return {
    ids: ids, activas: activas, paneles: paneles,
    eje: ejeComparacion, alcance: alcanceComparacion,
    xMin: xMin, xMax: xMax, completo: completo, conZoom: !!zoom,
    unidad: enDistancia ? "m" : "s",
    rotuloDelEje: enDistancia
      ? (deLaCarrera ? "DISTANCIA DE SESIÓN · METROS" : "DISTANCIA DE VUELTA · METROS")
      : (deLaCarrera ? "TIEMPO DE SESIÓN · SEGUNDOS" : "TIEMPO DE VUELTA · SEGUNDOS"),
    /* Como se escribe un numero de este eje. Los metros van redondeados y con
       separador de miles; los segundos, con una decima, que es lo que la
       pantalla ya hacia. */
    formatearEje: v => enDistancia
      ? Math.round(v).toLocaleString("es-AR")
      : v.toFixed(1),
    /* Que vueltas hay detras de lo que se ve. Son las que la sesion declara **y
       ademas estan cargadas**: `vueltasParaComparar` devuelve todas las
       declaradas, y con siete de veintidos traidas eso presentaria una
       cobertura parcial como completa. Sirve ademas para no llamar «vuelta 7» a
       una exportacion de la carrera entera. */
    vueltas: deLaCarrera
      ? vueltasParaComparar().filter(n => !!estado.series[n])
      : [vueltaElegida],
    vacia: false,
  };
}

function zonasDeCurva(xMin, xMax, clave, eje, alcance) {
  /* El eje y el alcance llegan como argumento y no se leen de la variable
     global: la lamina los tomaba de ahi mientras sus datos venian de otro
     modo, y las dos mitades del dibujo hablaban de cosas distintas. */
  if (eje !== "distancia") return null;
  if (!CURVAS.length) return null;

  /* Los limites, ordenados. Uno por curva y por vuelta visible. */
  const curvas = CURVAS
    .map(c => ({ metro: metroDeCurva(c), nombre: c.nombre, curva: c }))
    .filter(c => c.metro !== null)
    .sort((a, b) => a.metro - b.metro);
  if (!curvas.length) return null;

  /* DOS CURVAS PUEDEN LLAMARSE IGUAL. En Spa el catalogo trae dos «Les Combes»
     y dos «Fagnes»: son curvas distintas de un mismo complejo y las distingue
     su numero de cronometraje. Sin el, dos franjas seguidas dicen lo mismo y
     parecen un error de dibujo. */
  const repetido = {};
  curvas.forEach(c => { repetido[c.nombre] = (repetido[c.nombre] || 0) + 1; });
  const rotuloDe = c => {
    if (repetido[c.nombre] < 2) return c.nombre;
    const n = (c.curva.numeros_cronometraje || []).join("-");
    return n ? c.nombre + " " + n : c.nombre;
  };

  let vueltas;
  if (alcance === "carrera") {
    vueltas = [];
    Object.keys(estado.series).forEach(k => {
      const v = Number(k);
      if (!Number.isFinite(v)) return;
      const t = tramoAcumuladoDeVuelta(v, clave);
      if (!t) return;                       // esa vuelta no trae acumulada
      vueltas.push({ numero: v, desfase: t.desfase, hasta: t.hasta, desde: t.desde });
    });
    if (!vueltas.length) return null;
    vueltas.sort((a, b) => a.numero - b.numero);
  } else {
    const fin = PISTA.largo_m || curvas[curvas.length - 1].metro;
    vueltas = [{ numero: null, desfase: 0, hasta: fin, desde: 0 }];
  }

  /* Se arma la sucesion completa y despues se recorta: asi el tramo que
     **cruza la meta** ---de la ultima curva de una vuelta a la primera de la
     siguiente--- queda cubierto en vez de dejar un hueco de cuatrocientos
     metros sin nombre. */
  const limites = [];
  vueltas.forEach(v => curvas.forEach(c => limites.push({
    x: v.desfase + c.metro, rotulo: rotuloDe(c), vuelta: v.numero,
    finDeSuVuelta: v.hasta, ordenDeVuelta: v.numero,
  })));
  limites.sort((a, b) => a.x - b.x);

  const zonas = [];
  for (let i = 0; i < limites.length; i++) {
    const a = limites[i], b = limites[i + 1];
    /* Se une con el limite siguiente solo si es de la misma vuelta o de la que
       viene justo despues. Con una vuelta sin cargar en el medio, una sola
       franja taparia el hueco y afirmaria un recorrido que no esta. */
    const seguido = b && (b.vuelta === a.vuelta ||
      (a.vuelta !== null && b.vuelta === a.vuelta + 1));
    const fin = seguido ? b.x : a.finDeSuVuelta;
    if (!(fin > a.x)) continue;
    if (fin < xMin || a.x > xMax) continue;
    zonas.push({ ini: a.x, fin: fin, nombre: a.rotulo, orden: i, vuelta: a.vuelta });
  }
  return zonas.length ? zonas : null;
}

/* Las vueltas cargadas que caen en el tramo visible, para cuando las zonas de
   curva no entran. Sobre una sola vuelta no hay nada que separar. */
function bandasDeVuelta(xMin, xMax, clave, eje, alcance) {
  if (eje !== "distancia" || alcance !== "carrera") return null;
  const bandas = [];
  Object.keys(estado.series).forEach(k => {
    const v = Number(k);
    if (!Number.isFinite(v)) return;
    const t = tramoAcumuladoDeVuelta(v, clave);
    if (!t || t.hasta < xMin || t.desde > xMax) return;
    bandas.push({ ini: t.desde, fin: t.hasta, nombre: "V" + v, orden: v, vuelta: v });
  });
  return bandas.length ? bandas.sort((a, b) => a.ini - b.ini) : null;
}

/* Pinta las bandas detras de todo y devuelve que se pinto, para el pie.

   Se alternan dos tintas muy tenues en vez de una por zona: quince colores
   distintos serian un codigo que nadie puede recordar, y lo que hace falta es
   ver **donde termina una y empieza la otra**. El nombre va solo donde entra. */
function pintarZonas(ctx, bandas, xMin, xMax, izq, ancho, arriba, abajo) {
  const anchoDe = b => ((Math.min(b.fin, xMax) - Math.max(b.ini, xMin)) /
                        Math.max(1e-9, xMax - xMin)) * ancho;
  const enX = m => izq + ((m - xMin) / Math.max(1e-9, xMax - xMin)) * ancho;
  let conRotulo = 0;
  ctx.save();
  ctx.beginPath();
  ctx.rect(izq, arriba, ancho, abajo - arriba);
  ctx.clip();
  bandas.forEach((b, i) => {
    const x0 = enX(Math.max(b.ini, xMin)), x1 = enX(Math.min(b.fin, xMax));
    ctx.fillStyle = tinta("--linea");
    /* Dos tintas muy tenues y alternadas. Lo que hace falta ver es **donde
       termina una y empieza la otra**; quince colores distintos serian un
       codigo que nadie puede recordar, y uno fuerte taparia la traza, que es
       lo que se vino a mirar. */
    ctx.globalAlpha = (b.orden % 2) ? 0.55 : 0.14;
    ctx.fillRect(x0, arriba, Math.max(0, x1 - x0), abajo - arriba);
    ctx.globalAlpha = 1;
    /* EL ROTULO SE MIDE, NO SE SUPONE.
       Con un ancho minimo fijo, «Fagnes 13» entraba donde no cabia y se
       montaba sobre «Campus». Se pregunta cuanto mide **este** nombre con
       **esta** fuente y se lo escribe solo si entra con su margen. */
    if (b.nombre) {
      ctx.font = "9px 'IBM Plex Mono', monospace";
      const necesita = ctx.measureText(b.nombre).width + 8;
      if (anchoDe(b) >= Math.max(ZONA_CON_ROTULO_PX, necesita)) {
        conRotulo++;
        ctx.fillStyle = tinta("--texto-tenue");
        ctx.textAlign = "left";
        ctx.fillText(b.nombre, x0 + 4, arriba + 10);
      }
    }
  });
  ctx.restore();
  ctx.globalAlpha = 1;
  ctx.textAlign = "left";
  return conRotulo;
}

/* Que bandas corresponden al tramo visible: las de curva si entran, las de
   vuelta si no, y `null` cuando no hay con que ubicarlas. El segundo elemento
   es lo que el pie tiene que decir. */
function bandasParaElTramo(xMin, xMax, clave, ancho, eje, alcance) {
  /* SE MIDE LA BANDA TIPICA, NO LA MAS ANGOSTA.
     La primera version tomaba el minimo, y el minimo lo decide siempre una
     banda **cortada por el borde de la ventana**: basta con que un tramo empiece
     dos metros antes del final del zoom para que mida un pixel. Eso no dice
     nada de si las bandas se leen; dice donde cayo el recorte. Se toma la
     mediana del ancho **entero** de cada banda, que no depende de por donde
     pase el borde. */
  const cabe = bandas => {
    if (!bandas || !bandas.length) return false;
    const px = bandas
      .map(b => ((b.fin - b.ini) / Math.max(1e-9, xMax - xMin)) * ancho)
      .sort((a, b) => a - b);
    return px[Math.floor(px.length / 2)] >= ZONA_MINIMA_PX;
  };
  const curvas = zonasDeCurva(xMin, xMax, clave, eje, alcance);
  if (cabe(curvas)) {
    /* SE DESCRIBE LO QUE EL CODIGO HACE, NO LO QUE SERIA COMODO DECIR.
       Decia que toda franja termina en la curva siguiente, y no es asi: la
       ultima de cada tramo cargado termina en el limite de la vuelta o de lo
       que se llego a medir, porque no hay una referencia siguiente que la
       cierre. Y el catalogo publica **un punto de referencia por curva**, no su
       entrada ni su ancho: llamarlo «entrada de curva» seria atribuirle al
       catalogo una precision que no declara. */
    return [curvas, "Franjas: intervalos entre puntos de referencia del " +
      "catálogo del circuito. Cada una empieza en la referencia que la nombra " +
      "y llega hasta la siguiente; la última llega hasta donde termina la " +
      "vuelta o la cobertura cargada, porque no hay referencia siguiente que la " +
      "cierre. El metro de cada referencia está medido sobre la vuelta; el " +
      "ancho de la curva no se declara, así que la franja es el intervalo y no " +
      "la curva. El tramo anterior a la primera referencia queda sin franja."];
  }
  const vueltas = bandasDeVuelta(xMin, xMax, clave, eje, alcance);
  if (cabe(vueltas)) {
    return [vueltas, "Franjas: una por vuelta cargada, entre sus distancias " +
      "acumuladas medidas. A esta escala los intervalos entre referencias del " +
      "circuito medirían pocos píxeles y taparían la traza; acercándose con el " +
      "zoom aparecen."];
  }
  if (eje !== "distancia") {
    return [null, "Sin franjas de circuito: van sobre el eje de distancia. Una " +
      "referencia del catálogo está en un metro, y el segundo en que cada " +
      "piloto lo cruza es otro y cambia vuelta a vuelta."];
  }
  return [null, ""];
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
    avisoDeComparacion(cv, ctx,
      "Esta vista espacial requiere distancia medida y solo está disponible para F1 25.");
    return;
  }

  /* LA COMPARACION TRABAJA SOBRE VUELTAS GUARDADAS, Y HAY QUE DECIRLO.
     Compara **vueltas cerradas** entre si: lee `estado.series`, que en vivo
     esta vacio a proposito. Los cuatro graficos chicos si leen el flujo, de
     modo que durante una sesion en vivo la pantalla mostraba unos paneles con
     dato y este en blanco, sin explicar la diferencia.

     No se la conecta al flujo porque no hay que conectar: en vivo hay **una**
     vuelta y esta a medio correr, y comparar una vuelta incompleta contra nada
     no es una comparacion. Lo que corresponde es decir que espera a que la
     vuelta cierre. */
  if (estadoSesion === "vivo" && !Object.keys(estado.series).length) {
    avisoDeComparacion(cv, ctx,
      "La comparación trabaja sobre vueltas ya cerradas. Esta sesión está en curso: " +
      "en cuanto se guarde la primera vuelta completa aparece acá.");
    return;
  }
  /* LA MISMA VISTA QUE EXPORTA LA LAMINA. Quienes, que señales, que eje, que
     alcance, que dominio y que segmentos: resueltos una vez, en un solo sitio. */
  const vista = vistaDeComparacion();
  const activas = vista.activas;
  if (!activas.length) return;
  const w = cv.clientWidth;
  const altoPanel = Math.max(84, Math.min(150, (window.innerHeight - 260) / activas.length));
  const h = altoPanel * activas.length + 26;
  // Este si cambia de alto ---depende de cuantas metricas hay--- pero solo
  // cuando cambia: `ajustarLienzo` no toca el buffer si el tamano es el mismo.
  if (cv.style.height !== h + "px") cv.style.height = h + "px";
  ajustarLienzo(cv, w, h);
  ctx.clearRect(0, 0, w, h);

  const margenIzq = 62, margenDer = 12;
  const ancho = w - margenIzq - margenDer;
  const ids = vista.ids;
  const paleta = ["--auto-1", "--auto-2", "--auto-3", "--auto-4"];

  if (vista.vacia) {
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
  const xMin = vista.xMin, xMax = vista.xMax;

  /* Las franjas de circuito se resuelven una vez y se pintan en todos los
     paneles: un mismo metro se sigue de arriba abajo, que es la razon de
     apilarlos. Van **detras** de la rejilla y de la traza. */
  const [bandas, notaDeBandas] = bandasParaElTramo(xMin, xMax, ids[0], ancho,
                                                   vista.eje, vista.alcance);

  activas.forEach((m, pi) => {
    const y0 = pi * altoPanel + 6, y1 = y0 + altoPanel - 16;

    if (bandas) pintarZonas(ctx, bandas, xMin, xMax, margenIzq, ancho, y0, y1);

    // marco y rejilla
    ctx.strokeStyle = tinta("--linea"); ctx.lineWidth = 1;
    ctx.strokeRect(margenIzq, y0, ancho, y1 - y0);
    for (let i = 1; i < 4; i++) {
      const y = y0 + (y1 - y0) * (i / 4);
      ctx.beginPath(); ctx.moveTo(margenIzq, y); ctx.lineTo(margenIzq + ancho, y); ctx.stroke();
    }

    const datos = vista.paneles[pi].porVehiculo
      .map(segs => segs.map(segmento => segmento.filter(p => p[0] >= xMin && p[0] <= xMax)));
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
    const escalonadaPanel = esCanalEscalonado(m.id);
    datos.forEach((grupo, ai) => {
      grupo.forEach(d => {
        ctx.beginPath();
        trazarSerie(ctx, d,
                    x0 => margenIzq + ((x0 - xMin) / Math.max(1e-9, xMax - xMin)) * ancho,
                    v => y1 - ((v - mn) / (mx - mn)) * (y1 - y0), escalonadaPanel);
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
        const et = "Vuelta " + rotuloDeVuelta(t);
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

  /* EL BORDE DE CADA FRANJA, DE ARRIBA ABAJO. La franja dice de que tramo es
     cada parte; la linea deja seguir un mismo metro entre paneles apilados, que
     es la razon de apilarlos. Antes era una linea por curva y leia `cv2.metro`,
     un campo que el catalogo no publica: no se dibujaba ninguna. */
  if (bandas) {
    ctx.strokeStyle = tinta("--linea-fuerte");
    ctx.setLineDash([3, 3]); ctx.globalAlpha = .45;
    bandas.forEach(b => {
      if (b.ini < xMin || b.ini > xMax) return;
      const x = margenIzq + ((b.ini - xMin) / Math.max(1e-9, xMax - xMin)) * ancho;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, yEje); ctx.stroke();
    });
    ctx.setLineDash([]); ctx.globalAlpha = 1;
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

  const unidadDelEje = ejeComparacion === "distancia" ? " m" : " s";
  const dice = [];
  if (zoom) {
    dice.push("Zoom activo entre " + cifra(d0, 1) + unidadDelEje + " y " +
              cifra(d1, 1) + unidadDelEje + ".");
  } else {
    if (alcanceComparacion === "carrera") dice.push("Carrera completa con segmentos separados por vuelta.");
    dice.push(ejeComparacion === "distancia"
      ? "Eje medido por la fuente."
      : "Tiempo transcurrido desde el inicio observado " +
        (alcanceComparacion === "carrera" ? "de la sesión." : "de cada vuelta."));
  }
  /* Que son las franjas se declara siempre, incluso con el zoom puesto: son lo
     primero que se lee del dibujo y no pueden quedar sin explicacion. */
  if (notaDeBandas) dice.push(notaDeBandas);
  document.getElementById("nota-comparacion").textContent = dice.join(" ");
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
const MUESTRAS_RECORDADAS = 600;
const vivo = {
  eventSource: null,
  sesion: null,
  ultimos: new Map(),
  series: new Map(),
  distancia: new Map(),
  vuelta: new Map(),
  //: Reloj de la ultima muestra aplicada, por vehiculo y por señal. Es lo que
  //: permite decir que un canal esta viejo aunque esten llegando otros, y
  //: descartar una muestra atrasada sin descartar la que la sigue.
  reloj: new Map(),
  //: Identidades ya incorporadas, para no aplicar dos veces la misma muestra
  //: cuando la recuperacion y el flujo se solapan.
  vistos: new Set(),
  ordenVistos: [],
  //: A QUE SESION SE SIGUE. No es un booleano: «seguir el vivo» tiene que
  //: significar seguir **una** sesion, no alternar entre todas las que
  //: publiquen. Con un booleano, dos productores simultaneos hacian que el
  //: tablero cambiara de sesion en cada mensaje.
  //:
  //: Nulo quiere decir que todavia no se eligio. Una vez elegida, queda fija
  //: hasta un acto explicito: abrir otra del catalogo, o encender una captura.
  objetivo: null,
  //: Si se puede adoptar la primera sesion que aparezca y fijarla como
  //: objetivo. Lo pone en verdadero el arranque sin nada abierto y el boton de
  //: empezar a capturar; nunca un mensaje.
  aceptaNueva: true,
  //: Si **una persona pidio escuchar**, y no el arranque por omision.
  //:
  //: `aceptaNueva` no alcanzaba para distinguirlos porque arranca en verdadero:
  //: leerlo antes que la sesion abierta habria convertido al tablero en
  //: seguidor de cualquier sesion que apareciera, que es justo lo que se
  //: evitaba. Este solo lo enciende el boton, y se apaga al adoptar.
  pedida: false,
  //: El recorrido que se va midiendo, por vehiculo: pares [x, z] del mundo,
  //: en el orden en que llegaron. Es la **misma senal** con la que el backend
  //: arma el trazado de una sesion guardada ---`world_position_x` y
  //: `world_position_z`--- de modo que no es una geometria inventada ni una
  //: forma de catalogo: son las posiciones que el vehiculo declara.
  recorrido: new Map(),
  //: Cuantos puntos habia la ultima vez que se rehizo el dibujo. Rehacerlo en
  //: cada punto significa recalcular la orientacion de la nube entera, y el
  //: dibujo salta de sitio a cada paso.
  recorridoDibujado: 0,
  //: Una sesion viva distinta de la que se mira, para poder decirlo.
  otra: null,
  //: Que conexion de flujo esta vigente. Cada `EventSource` lleva su numero, y
  //: lo que su apertura haya pedido se descarta cuando el numero cambia.
  conexion: 0,
  mandoFlujo: null,
  silencio: null,
};

function vaciarVivo(sesion) {
  vivo.sesion = sesion || null;
  vivo.ultimos.clear(); vivo.series.clear(); vivo.distancia.clear(); vivo.vuelta.clear();
  vivo.reloj.clear(); vivo.vistos.clear(); vivo.ordenVistos.length = 0;
  /* El recorrido es de la sesion que se deja: reusarlo dibujaria el circuito
     anterior debajo del coche de la nueva. */
  vivo.recorrido.clear();
  vivo.recorridoDibujado = 0;
  /* Y lo derivado de las series tambien: las vistas temporales y los relojes de
     vuelta viven en otra cache, con la vuelta y el vehiculo por clave, y esos
     dos se repiten entre una sesion y la siguiente. */
  cambiaronLasSeries();
}

/* ============================================================
   QUE MUESTRA ES CUAL
   ------------------------------------------------------------
   La marca temporal sola no identifica una muestra: con la parrilla completa
   hay veinte vehiculos publicando la misma señal en el mismo instante, y a mil
   setecientas señales por segundo un mismo vehiculo puede repetir marca dentro
   de una señal. La identidad es la tupla completa.

   Queda un caso que esto no separa: dos muestras del mismo vehiculo, la misma
   señal y la misma marca temporal. Se descarta la segunda. Es una perdida
   acotada y consciente ---un punto de un canal que ya tiene un punto en ese
   instante--- y solo puede ocurrir en la recuperacion, que es donde la
   duplicacion importa mas que la completitud. La persistencia no pasa por
   aca: la escribe otro proceso desde el mismo flujo.
   ============================================================ */
function identidadDeMuestra(m) {
  return m.source_type + "|" + m.session_id + "|" + m.vehicle_id + "|" +
         m.signal_name + "|" + m.timestamp;
}

function recordarVista(id) {
  vivo.vistos.add(id);
  vivo.ordenVistos.push(id);
  while (vivo.ordenVistos.length > MUESTRAS_RECORDADAS) {
    vivo.vistos.delete(vivo.ordenVistos.shift());
  }
}

/* ============================================================
   UNA SESION EN VIVO NO SE APROPIA DE LA PANTALLA
   ------------------------------------------------------------
   Esto adoptaba cualquier sesion que apareciera en el flujo: quien estuviera
   revisando una carrera guardada veia el tablero cambiar solo, con otra
   sesion, otro vehiculo y la caché de vueltas vaciada, porque alguien encendio
   el capturador en otra maquina. Peor con dos productores publicando a la vez:
   el tablero oscilaba entre los dos, adoptando la sesion de cada mensaje.

   Se adopta en tres casos, y los tres son una decision de quien mira:
   se pidio seguir el vivo, no hay nada abierto que pisar, o la sesion que
   emite es justamente la que se esta mirando.
   ============================================================ */
function puedeAdoptarVivo(sesionId) {
  // Ya se eligio a quien seguir: solo esa.
  if (vivo.objetivo) return vivo.objetivo === sesionId;
  /* Se pidio escuchar, y eso manda sobre lo que este abierto.
     Sin esto, pulsar «empezar a escuchar» mientras se reproduce una sesion
     guardada no hacia nada visible: el permiso quedaba debajo de esta linea y
     la telemetria nueva se descartaba por no ser la que se estaba mirando. El
     tablero se quedaba congelado en la sesion vieja, con el boton todavia
     ofreciendo empezar. Ocurrio el 2026-09-09 con Suzuka entrando y Red Bull
     Ring en pantalla. */
  if (vivo.pedida) return true;
  // La sesion que se esta mirando, si justo empieza a emitir.
  if (estado.abierta) return estado.abierta.session_id === sesionId;
  // Nada abierto y permiso para elegir: se adopta la primera y **se fija**.
  return vivo.aceptaNueva === true;
}

/* El reloj de la muestra en milisegundos, o `null` si la fuente no lo declara
   legible. Nunca `Date.now()`: la hora en que esto se entero no es la hora en
   que se midio, y confundirlas hace que dos muestras que llegaron juntas
   parezcan simultaneas cuando no lo fueron. */
/* ============================================================
   EL RECORRIDO SE MIDE, NO SE SUPONE
   ------------------------------------------------------------
   Con una sesion guardada, `/trazado` devuelve el recorrido porque las
   posiciones ya estan en la base. En vivo no hay nada que consultar: la sesion
   todavia se esta corriendo. El tablero quedaba sin trazado y, sin trazado,
   `pintarPista` sale temprano y **el coche no se dibuja en ningun lado**.

   La solucion no es inventar una geometria de catalogo ni dibujar un circuito
   generico. El flujo trae `world_position_x` y `world_position_z`, que son las
   mismas dos senales con las que el backend arma el trazado guardado. Asi que
   se dibuja lo que se midio, y **se declara que esta a medio recorrer**: un
   tramo abierto que crece, con el coche en su punta.

   Al cerrar la primera vuelta el recorrido pasa a ser el circuito: se congela,
   se cierra el camino y desde ahi el coche se ubica por su distancia medida,
   igual que en una sesion guardada.
   ============================================================ */
const MAX_PUNTOS_DE_RECORRIDO = 4000;
const PUNTOS_ENTRE_REDIBUJOS = 25;

function anotarPosicionViva(vehiculo, marca) {
  const ultimos = vivo.ultimos.get(vehiculo);
  if (!ultimos) return;
  const mx = ultimos.get("world_position_x");
  const mz = ultimos.get("world_position_z");
  // Las dos, y de la misma muestra.
  if (!mx || !mz || mx.timestamp !== marca || mz.timestamp !== marca) {
    TESTIGO.paresRotos++;
    return;
  }
  const x = numeroMedido(mx.value), z = numeroMedido(mz.value);
  if (x === null || z === null) return;

  if (!vivo.recorrido.has(vehiculo)) vivo.recorrido.set(vehiculo, []);
  const puntos = vivo.recorrido.get(vehiculo);
  TESTIGO.posicionesConLasDos++;
  const ultimo = puntos.length ? puntos[puntos.length - 1] : null;
  // Un vehiculo detenido publica la misma posicion muchas veces por segundo.
  if (ultimo && ultimo[0] === x && ultimo[1] === z) return;
  TESTIGO.posicionesDistintas++;
  puntos.push([x, z]);
  if (puntos.length > MAX_PUNTOS_DE_RECORRIDO) puntos.shift();
}

/* Rehace el dibujo del recorrido si crecio lo suficiente. Devuelve si cambio. */
function armarTrazadoVivo() {
  if (estadoSesion !== "vivo") return false;
  // Un trazado guardado, o uno ya congelado, manda sobre este.
  if (PISTA.path && !PISTA.enConstruccion) return false;
  const clave = claveVehiculoPropio();
  const puntos = clave ? vivo.recorrido.get(clave) : null;
  if (!puntos || puntos.length < 3) return false;
  if (puntos.length - vivo.recorridoDibujado < PUNTOS_ENTRE_REDIBUJOS
      && vivo.recorridoDibujado > 0) {
    return false;
  }
  vivo.recorridoDibujado = puntos.length;

  const armado = trazadoAPath(puntos, false, false);
  if (!armado.path) return false;
  PISTA = {
    path: armado.path,
    largo_m: vivo.distancia.get(clave) || null,
    desnivel_m: null,
    muestras: puntos.length,
    vuelta: vivo.vuelta.get(clave) || null,
    curvas: CURVAS,
    enConstruccion: true,
    // Con esto la marca del vehiculo se ubica por su ultima posicion medida,
    // sin esperar a que el camino se vuelva a dibujar.
    proyectarMundo: armado.proyectarMundo,
  };
  const svg = document.getElementById("linea-pista");
  if (svg && svg.ownerSVGElement) delete svg.ownerSVGElement.dataset.reserva;
  const g = document.getElementById("marcas-pista");
  if (g) g.dataset.firma = "";
  return true;
}

/* Al cerrar una vuelta, lo recorrido **es** el circuito: se cierra el camino y
   se deja de crecer. Desde ahi el coche se ubica por su distancia, que es lo
   que permite verlo dar vueltas en vez de alargar una linea. */
function congelarTrazadoVivo(largoDeLaVuelta) {
  const clave = claveVehiculoPropio();
  const puntos = clave ? vivo.recorrido.get(clave) : null;
  if (!puntos || puntos.length < 20) return;
  const armado = trazadoAPath(puntos, false, true);
  if (!armado.path) return;
  PISTA = {
    path: armado.path,
    largo_m: largoDeLaVuelta || PISTA.largo_m,
    desnivel_m: null,
    muestras: puntos.length,
    vuelta: vivo.vuelta.get(clave) || null,
    curvas: CURVAS,
    enConstruccion: false,
    medidoEnVivo: true,
  };
  const svg = document.getElementById("linea-pista");
  if (svg && svg.ownerSVGElement) delete svg.ownerSVGElement.dataset.reserva;
  const g = document.getElementById("marcas-pista");
  if (g) g.dataset.firma = "";
}

function relojDeMuestra(m) {
  if (!m || !m.timestamp) return null;
  const t = Date.parse(m.timestamp);
  return Number.isFinite(t) ? t : null;
}

function mapaVivo(contenedor, vehiculo) {
  if (!contenedor.has(vehiculo)) contenedor.set(vehiculo, new Map());
  return contenedor.get(vehiculo);
}

function incorporarTelemetriaViva(m, recuperando) {
  if (!m || FUENTE_CORTA[m.source_type] !== "f1" || !m.session_id || !m.vehicle_id || !m.signal_name) {
    TESTIGO.descarteFuente++;
    return;
  }
  if (m.signal_name === "world_position_x") TESTIGO.llegaronX++;
  else if (m.signal_name === "world_position_z") TESTIGO.llegaronZ++;

  // La misma muestra dos veces no aporta un punto: aporta un punto repetido.
  const identidad = identidadDeMuestra(m);
  if (vivo.vistos.has(identidad)) { TESTIGO.descarteDuplicado++; return; }

  if (vivo.sesion !== m.session_id) {
    /* UN SNAPSHOT NO ELIGE SESION.
       `/live/recent` describe lo que el difusor tenia guardado, que puede ser
       de otra sesion y de hace rato. Adoptar desde ahi cambiaba la sesion del
       tablero con un dato viejo, y ademas ocurria **antes** del filtro por
       reloj, de modo que ni siquiera se comprobaba que fuera reciente. La
       recuperacion sirve para completar la sesion que ya se sigue. */
    if (recuperando) return;
    if (!puedeAdoptarVivo(m.session_id)) {
      // Se declara y no se toca nada. Abrirla del catalogo es lo que la adopta.
      TESTIGO.descarteNoAdoptada++;
      if (vivo.otra !== m.session_id) {
        vivo.otra = m.session_id;
        avisar("Está entrando telemetría de otra sesión (" + m.session_id +
               "). Abrila del catálogo para verla en vivo.", false);
        pintarTransporte();
      }
      return;
    }
    vivo.otra = null;
    /* La eleccion queda fija. Antes esto era un booleano y adoptar la sesion
       que ya se estaba mirando ---que es correcto--- convertia al tablero en
       seguidor de cualquier otra que apareciera despues. */
    vivo.objetivo = m.session_id;
    vivo.aceptaNueva = false;
    vivo.pedida = false;
    /* Y lo que estaba pidiendo la sesion anterior deja de valer. Sin esto, una
       consulta historica en vuelo volvia despues del cambio, pasaba la
       comprobacion de vigencia ---porque el numero de apertura no habia
       cambiado--- y escribia las series de la sesion vieja sobre la nueva. */
    nuevaSesionEnCurso();
    /* Y el dibujo de la pista tambien: es de la sesion que se deja. Sin esto,
       el circuito anterior queda debajo del coche de la sesion nueva, que es
       una afirmacion falsa sobre donde esta el vehiculo. */
    PISTA = { path: "", curvas: [], largo_m: null, desnivel_m: null, muestras: null };
    CURVAS = [];
    vaciarVivo(m.session_id);
    fuente = "f1";
    sesionAbierta = m.session_id;
    estado.abierta = SESIONES.find(s => s.session_id === m.session_id) || {
      session_id: m.session_id, fuente: m.source_type, senales: null, vehiculos: 0,
      filas: 0, procedencia: {},
    };
    estado.series = {}; estado.pidiendo = {}; estado.posiciones = {}; estado.pidiendoPos = {};
    cambiaronLasSeries();
    estado.disponibles = new Set();
    AUTOS = []; seleccion = new Set(); estado.vehiculoClave = null;
    marcar(document.getElementById("sel-fuente"), "fuente", fuente);
  }

  /* UNA MUESTRA ATRASADA NO PISA A UNA MAS NUEVA.
     `/live/recent` devuelve lo ultimo que el difusor tenia guardado, y se pide
     al abrir el flujo: para cuando llega, el flujo ya entrego muestras mas
     nuevas. Aplicadas sin mirar el reloj, esas muestras viejas hacen retroceder
     los ultimos valores ---y una distancia que retrocede dispara el corte por
     vuelta nueva, que **borra la serie viva entera**. */
  const reloj = relojDeMuestra(m);
  const relojes = mapaVivo(vivo.reloj, m.vehicle_id);
  const relojPrevio = relojes.get(m.signal_name);
  if (recuperando && reloj !== null && relojPrevio !== undefined && reloj <= relojPrevio) {
    TESTIGO.descarteRecuperacionVieja++;
    return;
  }

  recordarVista(identidad);
  if (reloj !== null && (relojPrevio === undefined || reloj > relojPrevio)) {
    relojes.set(m.signal_name, reloj);
  }

  /* Cuando llego, medido con el reloj de esta maquina. Es lo unico con lo que
     se puede calcular la antiguedad de lo que se ve: el reloj de la fuente no
     tiene origen comparable con este. */
  m._recibidoEnMs = performance.now();
  const ultimo = mapaVivo(vivo.ultimos, m.vehicle_id);
  ultimo.set(m.signal_name, m);
  estado.disponibles.add(m.signal_name);

  /* LAS DOS COORDENADAS VIENEN EN MENSAJES SEPARADOS, Y EL ORDEN IMPORTA.
     El paquete de movimiento se normaliza a una senal por eje, con la misma
     marca temporal. El par se anota cuando las dos estan y comparten marca:
     con una sola no hay punto que dibujar, y aparearlas por orden de llegada
     mezclaria la x de una muestra con la z de la siguiente.

     Esto **tiene que ir despues** de guardar la muestra en `vivo.ultimos`.
     Estaba antes, y entonces al llegar la z la x de esa misma marca todavia no
     se habia guardado: la comprobacion fallaba y el par no se anotaba nunca.
     Medido el 2026-09-08 con carga real: la fuente entrega 20,0 posiciones por
     segundo y llegaban **4,3**. Los movimientos del coche no se perdian al
     dibujar; se perdian tres lineas antes. */
  if (m.signal_name === "world_position_x" || m.signal_name === "world_position_z") {
    anotarPosicionViva(m.vehicle_id, m.timestamp);
  }

  if (!AUTOS.some(a => a.id === m.vehicle_id)) {
    // Un vehiculo nuevo si es un cambio de estructura: hay una lista mas.
    pedirPintado("estructura");
    const ids = AUTOS.map(a => a.id).concat(m.vehicle_id);
    const propio = estado.vehiculoClave || m.vehicle_id;
    armarAutos(ids);
    AUTOS.forEach(a => { a.propio = a.id === propio; });
    estado.vehiculoClave = propio;
    if (!seleccion.size) seleccion.add(propio);
    if (estado.abierta) estado.abierta.vehiculos = AUTOS.length;
  }

  /* Ver `numeroMedido`: `Number(null)` da cero, y una vuelta cero o una
     distancia cero inventadas no se distinguen de las medidas. */
  const numero = numeroMedido(m.value);
  if (m.signal_name === "lap_number" && numero !== null) {
    const anterior = vivo.vuelta.get(m.vehicle_id);
    vivo.vuelta.set(m.vehicle_id, numero);
    // Un snapshot de recuperacion nunca abre una vuelta: describe la que ya
    // paso. Dejarlo cortar aca borraria las muestras nuevas que se recuperan.
    if (!recuperando && anterior !== undefined && anterior !== numero) {
      vivo.series.delete(m.vehicle_id);
      /* Se cerro una vuelta: lo recorrido hasta aca es el circuito. El largo
         es la ultima distancia declarada antes de volver a cero. */
      if (m.vehicle_id === claveVehiculoPropio() && PISTA.enConstruccion) {
        congelarTrazadoVivo(vivo.distancia.get(m.vehicle_id));
      }
    }
  }
  if (m.signal_name === "lap_distance" && numero !== null) {
    const anterior = vivo.distancia.get(m.vehicle_id);
    if (!recuperando && anterior !== undefined && numero + 20 < anterior) {
      vivo.series.delete(m.vehicle_id);
    }
    // Con la recuperacion, la distancia solo avanza: una muestra vieja no
    // reubica las que ya se dibujaron.
    if (!recuperando || anterior === undefined || numero > anterior) {
      vivo.distancia.set(m.vehicle_id, numero);
    }
  }

  const distancia = vivo.distancia.get(m.vehicle_id);
  const valor = numeroMedido(m.value);
  if (Number.isFinite(distancia) && valor !== null) {
    const porSenal = mapaVivo(vivo.series, m.vehicle_id);
    if (!porSenal.has(m.signal_name)) porSenal.set(m.signal_name, []);
    const serie = porSenal.get(m.signal_name);
    /* El tercer elemento es el reloj de la fuente, en milisegundos. No se
       dibuja: sirve para saber **cuando** se midio cada punto, que es lo unico
       que permite decir si un canal esta viejo y ordenar lo que llega tarde.
       Sin eso, dos muestras de la misma distancia son indistinguibles. */
    serie.push([distancia, valor, relojDeMuestra(m)]);
    if (serie.length > MAX_MUESTRAS_VIVO) serie.splice(0, serie.length - MAX_MUESTRAS_VIVO);
  }

  estadoSesion = "vivo";
  if (vivo.silencio) clearTimeout(vivo.silencio);
  vivo.silencio = setTimeout(() => {
    if (estadoSesion === "vivo") { estadoSesion = estado.abierta ? "cargado" : "vacio"; render(); }
  }, 10000);
  /* Una muestra cambia valores y trazas, nunca la estructura. La unica
     excepcion es un vehiculo que aparece por primera vez, y eso se pide donde
     ocurre, no en cada mensaje. */
  /* LA LATENCIA SE ABRE AQUI Y SE CIERRA AL PINTAR.
     Se anota **la primera** muestra todavia no reflejada, no la ultima: lo que
     interesa es cuanto espera el dato mas viejo que ya deberia verse. */
  TESTIGO.muestrasIncorporadas++;
  TESTIGO.pendientes++;
  if (TESTIGO.pendienteDesde === null) TESTIGO.pendienteDesde = performance.now();

  // El recorrido crece con las posiciones que llegan.
  if (armarTrazadoVivo()) pedirPintado("estructura");

  _instanteClave = null; _ultimaTraza = 0;
  pedirPintado(["valores", "trazas"]);
}

function datoEvento(e) {
  try { return JSON.parse(e.data); } catch (_error) { return null; }
}

function conectarFlujoEnVivo() {
  if (vivo.eventSource || typeof EventSource === "undefined" || fuente !== "f1") return;
  /* Cada conexion lleva su numero y su mando de cancelacion. Lo que esta
     apertura pida ---el snapshot de recuperacion--- deja de valer en cuanto la
     conexion se cierra o se abre otra: sin eso, un snapshot pedido por una
     conexion vieja llegaba despues de reconectar y se incorporaba como si
     fuera de la nueva. */
  const miConexion = ++vivo.conexion;
  const mando = new AbortController();
  vivo.mandoFlujo = mando;
  const canal = new EventSource(API + "/live/stream");
  vivo.eventSource = canal;
  canal.addEventListener("estado", e => { const d = datoEvento(e); if (d) { estado.vivo = d; pintarTransporte(); } });
  canal.addEventListener("telemetria", e => {
    TESTIGO.eventosSSE++;
    incorporarTelemetriaViva(datoEvento(e));
  });
  canal.addEventListener("latido", e => {
    const d = datoEvento(e);
    if (d) estado.vivo = Object.assign({}, estado.vivo || {}, { mensajes_recibidos: d.recibidos });
    pintarTransporte();
  });
  canal.onopen = () => {
    /* RECUPERAR NO ES VOLVER ATRAS.
       El servidor devuelve su ventana corta en el orden en que la guardo, y
       este navegador puede llevar ya varios segundos de flujo. Se ordena por
       el reloj de la fuente ---no por el de llegada, que es otra cosa--- y se
       incorpora en modo recuperacion: lo que sea mas viejo que lo que ya se
       muestra se descarta en vez de pisarlo. */
    pedir("/live/recent?limite=100", { senal: mando.signal })
      .then(lista => {
        // El dueño del snapshot es esta conexion. Si ya no es la vigente, lo
        // que traiga describe un estado que este tablero dejo atras.
        if (miConexion !== vivo.conexion) return;
        (lista || [])
          .slice()
          .sort((a, b) => (relojDeMuestra(a) || 0) - (relojDeMuestra(b) || 0))
          .forEach(m => incorporarTelemetriaViva(m, true));
      })
      .catch(e => { if (!fueAnulada(e) && e instanceof TypeError) console.error(e); });
  };
  canal.onerror = () => {
    estado.vivo = Object.assign({}, estado.vivo || {}, { motivo: "Flujo interrumpido; reconectando." });
    pintarTransporte();
  };
}

function cerrarFlujoEnVivo() {
  if (vivo.eventSource) vivo.eventSource.close();
  vivo.eventSource = null;
  /* Cerrar el flujo tiene que cancelar lo que el flujo pidio. El snapshot de
     recuperacion viaja por HTTP y no se entera de que el `EventSource` se
     cerro: sin esto llegaba despues, se incorporaba, y podia reabrir una
     sesion que se acababa de dejar. */
  vivo.conexion++;
  if (vivo.mandoFlujo) { vivo.mandoFlujo.abort(); vivo.mandoFlujo = null; }
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
/* El alcance elegido, soltado. Distinto de `olvidarLoDeLaCorrida`, que suelta
   los **datos** de la etapa: esto suelta la eleccion misma. */
function olvidarLaCorrida() {
  corrida.adquisicion = null;
  corrida.fase = null;
  corrida.disponibles = null;
  corrida.mezclada = false;
  _contextoDeCorrida = null;
  declararAlcance();
  pintarBotonDeCorrida();
  try {
    const u = new URL(location.href);
    u.searchParams.delete("adquisicion");
    u.searchParams.delete("fase");
    history.replaceState(null, "", u.toString());
  } catch (e) { /* sin historial se sigue igual */ }
}

/* TODO LO QUE DEPENDE DEL ALCANCE, Y NADA MAS.
   Se usa en dos sitios: al abrir una sesion y al cambiar de adquisicion o de
   etapa dentro de la misma. Lo que queda afuera es la identidad ---cual sesion
   esta abierta, que fuente es--- porque eso no cambia al cambiar de etapa. */
function olvidarLoDeLaCorrida() {
  estado.vueltas = []; estado.series = {}; estado.pidiendo = {};
  estado.posiciones = {}; estado.pidiendoPos = {};
  /* LO DERIVADO SE SUELTA CON LO ORIGINAL.
     Vaciar `estado.series` no vacia las vistas temporales ni los relojes de
     vuelta: esos viven en su propia cache y se invalidan por sello. Sin esta
     linea, la vuelta 3 de la formacion y la vuelta 3 de la carrera comparten
     numero y vehiculo, y el reloj de la primera seguia contestando por la
     segunda mientras las series nuevas viajaban ---incluido un reloj
     aproximado guardado antes de que llegaran las vueltas. */
  cambiaronLasSeries();
  estado.trazado = null; estado.curvas = []; estado.clima = null; estado.vehiculo = null;
  estado.puesta = null; estado.avisos = []; estado.disponibles = new Set();
  estado.vehiculoClave = null;
  estado.climaMotivo = ""; estado.vehiculoMotivo = ""; estado.avisosMotivo = "";
  estado.vigilancia = null; estado.vigilanciaMotivo = "";
  /* La vigilancia se pide una vez por sesion y se recuerda cual. Al cambiar de
     etapa la sesion es la misma, asi que sin esto no se volveria a pedir y el
     panel seguiria mostrando lo medido sobre la etapa anterior. */
  _vigilanciaPedida = null;
  _esencialResuelta = false;
  estado.cargando = true;
  PISTA = { path: "", curvas: [], largo_m: null, desnivel_m: null, muestras: null };
  CURVAS = [];
  vivo.recorrido.clear();
  vivo.recorridoDibujado = 0;
  AUTOS = [];
  seleccion = new Set();
  cabezal = 0;
  detener();
  _vueltasEnPantalla = [];
  estado.fallo = {};
  olvidarCaches();
  const svg = document.getElementById("linea-pista");
  if (svg && svg.ownerSVGElement) delete svg.ownerSVGElement.dataset.reserva;
}

function abrirSesionGuardada(id) {
  const s = SESIONES.find(x => x.session_id === id);
  if (!s) return;

  /* EL ALCANCE NO SE HEREDA DE LA SESION ANTERIOR.
     `original` es la clave de toda captura que no declara reproduccion, o sea
     casi todas: dejar puesto `adquisicion=original&fase=3` al pasar a otra
     sesion la habria abierto en su tercera fase ---o en ninguna, si no tiene
     tres--- sin que nadie lo pidiera. La direccion se limpia junto con el
     estado, porque si no la vuelve a leer la consulta de adquisiciones.

     Solo al **cambiar** de sesion: al abrir la primera, `?adquisicion=` de la
     direccion es una eleccion explicita de quien comparte el enlace. */
  if (sesionAbierta && sesionAbierta !== id) olvidarLaCorrida();

  estado.abierta = s;
  olvidarLoDeLaCorrida();
  sesionAbierta = id;
  recordarSesion(id);

  TESTIGO.aperturas++;
  const corta = FUENTE_CORTA[s.fuente] || "can";
  if (corta !== fuente) { fuente = corta; marcar(document.getElementById("sel-fuente"), "fuente", fuente); }
  estadoSesion = "cargado";
  document.getElementById("velo-sesiones").dataset.abierto = "no";
  render();

  const ruta = "/sesiones/" + encodeURIComponent(id);
  const conMotivo = (p, guardar) => p.then(guardar).catch(e => guardar({ error: e.message }));

  // Lo que quedo pidiendo la sesion anterior ya no le sirve a nadie.
  const apertura = nuevaSesionEnCurso();
  /* Abrir una sesion guardada es un acto explicito: fija el objetivo del vivo
     en esa sesion si es la que esta emitiendo, y lo suelta si no. En ningun
     caso queda «siguiendo lo que aparezca». */
  vivo.objetivo = (vivo.sesion && vivo.sesion === id) ? id : null;
  vivo.aceptaNueva = false;
  vivo.pedida = false;
  /* LO QUE HACE FALTA PARA ABRIR, Y LO QUE PUEDE LLEGAR DESPUES.
     Abrir la sesion esperaba a las seis consultas, y una de ellas ---los
     avisos--- tarda cuatro segundos: recorre la sesion entera buscando el
     primer instante en que se cumple cada condicion. Durante esos cuatro
     segundos el tablero no mostraba nada, aunque las vueltas ya estuvieran.

     Lo unico que hace falta para empezar a dibujar son las vueltas: sin ellas
     no se sabe cuanto dura la sesion ni donde empieza cada una. El resto
     aparece cuando llega, cada panel con su marca de espera. */
  /* ANTES DE PEDIR NADA, SABER QUE SE ESTA MIRANDO.
     Si la sesion tiene mas de una adquisicion, pedir sus vueltas sin elegir
     devuelve las tres juntas y el tablero las dibuja como una carrera continua.
     Asi que primero se pregunta, y si hay ambiguedad **no se pide nada mas**
     hasta que alguien elija: mostrar una mezcla sin decirlo es peor que no
     mostrar. La eleccion se pasa por la direccion, `?adquisicion=` y `?fase=`,
     que ademas es lo que permite compartir un enlace a lo que uno mira. */
  conCarga("cronometraje", () =>
    pedir(ruta + "/adquisiciones", { senal: senalDeSesion() })
      .then(a => {
        if (!sigueVigente(apertura) || !a) return;
        corrida.disponibles = a.adquisiciones || [];
        corrida.mezclada = !!a.mezclada;
        /* QUIEN ES CADA VEHICULO, SI LA CAPTURA LO DECLARO.
           Puede llegar despues de que las series ya hayan armado la lista: se
           renombra lo que hay, sin tocar claves, seleccion, propio ni cabezal.
           Enterarse de un nombre no reinicia una reproduccion. */
        anotarParrillas(a.session_id || (estado.abierta || {}).session_id,
                        a.adquisiciones);
        if (renombrarAutos()) {
          const sel = document.getElementById("sel-propio");
          if (sel) sel.dataset.firma = "";
          render();
        }
        /* Con que volver a preguntar. Se guarda aca y no solo al abrir el
           elector: si la direccion ya traia una eleccion, el elector no llega a
           abrirse y el boton del encabezado se quedaria sin nada que reabrir. */
        _contextoDeCorrida = { ruta: ruta, s: s };
        pintarBotonDeCorrida();

        /* LA DIRECCION SE LEE SIEMPRE, NO SOLO CUANDO LA API DICE «mezclada».
           `mezclada` cuenta adquisiciones; la eleccion que trae el enlace puede
           ser de etapa, y con una sola adquisicion esta rama ni se miraba: el
           enlace decia `fase=3` y el tablero cargaba todo junto. */
        const p = new URLSearchParams(location.search);
        const pedida = p.get("adquisicion");
        const faseDelEnlace = faseDeLaDireccion(p.get("fase"));
        const existe = (corrida.disponibles || []).some(x => x.clave === pedida);
        if (!pedida && !alcanceEsAmbiguo()) {
          declararAlcance();
          cargarDatosDeSesion(ruta, apertura, senalDeSesion(), s);
          return;
        }
        if (pedida && alcanceElegidoEsValido(pedida, faseDelEnlace)) {
          corrida.adquisicion = pedida;
          corrida.fase = faseDelEnlace;
          declararAlcance();
          pintarBotonDeCorrida();
          decirEstadoApi("Mirando la adquisición «" + pedida + "»" +
            (corrida.fase ? ", fase " + corrida.fase : "") + " de " +
            corrida.disponibles.length + " que hay en esta sesión.", false);
          cargarDatosDeSesion(ruta, apertura, senalDeSesion(), s);
          return;
        }
        /* EL ENLACE TRAE MEDIA ELECCION: SE CONSERVA Y SE PREGUNTA EL RESTO.
           `?adquisicion=original` sin etapa, o con una etapa que esa
           adquisicion no declara. No se carga nada ---seria la mezcla--- pero
           tampoco se tira lo que sí vino: el elector se abre con la
           adquisicion ya marcada y solo falta la etapa. */
        if (pedida && existe) {
          corrida.adquisicion = pedida;
          corrida.fase = null;
        }

        /* Ambigua y sin elegir: se pregunta. No se adivina cual, y **no es un
           error**: es una eleccion pendiente, y marcarla en rojo diria que algo
           salio mal cuando lo que falta es una decision. */
        estadoSesion = "vacio";
        estado.cargando = false;
        estado.motivo = (corrida.disponibles.length > 1)
          ? ("Esta sesión guarda " + corrida.disponibles.length + " adquisiciones " +
             "distintas bajo el mismo identificador del juego. Juntas no son una " +
             "carrera continua, así que hay que elegir cuál mirar.")
          /* Con una sola adquisición la ambigüedad es de etapa: el reloj del
             juego se reinicia al largar, así que la formación y la carrera se
             solapan en el tiempo. Mostradas juntas, la primera vuelta trae las
             dos y el coche va y viene. */
          : ("Esta captura tiene varias etapas y el reloj del juego se reinicia " +
             "entre ellas, así que la formación y la carrera se solapan en el " +
             "tiempo. Juntas no son una carrera continua: hay que elegir cuál mirar.");
        decirEstadoApi(estado.motivo + " Elegí abajo.", false);
        abrirElectorDeCorrida(ruta, apertura, s);
        render();
      })
      .catch(e => {
        /* Si la ruta no esta ---una API mas vieja--- se sigue como siempre: no
           se rompe por no poder preguntar. Se declara la lista vacia, que es lo
           que se sabe ---no hay adquisiciones que elegir--- y ademas es lo que
           destraba la compuerta de `alcancePermitePedir`. */
        if (fueAnulada(e)) return;
        if (!corrida.disponibles) corrida.disponibles = [];
        cargarDatosDeSesion(ruta, apertura, senalDeSesion(), s);
      }));
}

/* ============================================================
   ELEGIR ADQUISICION Y FASE, SIN EDITAR LA DIRECCION
   ------------------------------------------------------------
   La proteccion contra mezclar adquisiciones tiene que dejar seguir. Pedirle a
   alguien que escriba `?adquisicion=original&fase=3` a mano es trasladarle un
   detalle de la implementacion y, sobre todo, exige saber que existen esas
   fases y como se numeran.

   Se listan con lo que hace falta para decidir: cuantas muestras, cuantos
   vehiculos, cuando se capturo, y para cada fase su duracion. La direccion se
   actualiza con lo elegido ---sin recargar--- para que el enlace siga sirviendo
   para compartir lo que uno mira.
   ============================================================ */
/* Un largo de tramo, dicho como lo diria una persona. «2.827 s» obliga a
   dividir mentalmente por sesenta para saber si son minutos o casi una hora. */
function duracionCorta(segundos) {
  const t = Math.max(0, Math.round(numeroMedido(segundos) || 0));
  if (t < 90) return t + " s";
  const m = Math.floor(t / 60);
  const r = t % 60;
  if (m < 60) return m + " min " + (r < 10 ? "0" : "") + r + " s";
  return Math.floor(m / 60) + " h " + ((m % 60) < 10 ? "0" : "") + (m % 60) + " min";
}

/* Que es cada tramo, en una linea. El nombre solo no alcanza: «Fase 2» no dice
   nada, y «Carrera» no dice que las vueltas cronometradas empiezan ahi. */
function queEsLaFase(a, f) {
  const fases = a.fases || [];
  if (fases.length <= 1) return "la adquisición entera; el reloj del juego no se reinicia";
  if (f.orden === 1) return "antes de la largada: vuelta de formación y parrilla";
  if (f.orden === fases.length) return "desde la largada: acá empiezan las vueltas cronometradas";
  if (f.duracion_de_captura_s < 30) return "el coche detenido en la grilla, esperando las luces";
  return "tramo " + f.orden + ", entre dos reinicios del reloj del juego";
}

/* Una fila del elector: la adquisicion, y los botones con los que se la elige.
   Se separa del elector porque es lo unico que decide **que opciones existen**,
   y eso hay que poder comprobarlo sin un documento. `elegida` viene de afuera
   porque marca contra el alcance vigente, que es del elector. */
function filaDeCorrida(a, elegida) {
  const cuando = a.desde_utc ? fechaAr(new Date(a.desde_utc)) : "sin fecha";
  const que = a.es_reproduccion ? "reproducción de prueba" : "captura original";
  const etapas = a.fases || [];
  const total = etapas.reduce((t, f) => t + (f.duracion_de_captura_s || 0), 0);
  /* «TODO» NO SE OFRECE CUANDO LAS ETAPAS SE SOLAPAN.
     Es el mecanismo minimo para que la mezcla no vuelva por la puerta de al
     lado: si el reloj del juego se reinicia entre etapas, sus ventanas de
     tiempo se pisan y juntas no son una carrera continua ---la vuelta 1 traeria
     la formacion y la carrera, y el coche iria y vendria---. Donde las etapas
     son de verdad continuas, «Todo» sigue estando. */
  const seSolapa = adquisicionSeSolapa(a);
  /* Con una sola etapa, «Todo» y «Fase unica» son la misma cosa: dos botones
     que hacen lo mismo obligan a pararse a decidir entre ellos para nada. */
  const fases = (etapas.length <= 1 ? [] : etapas).map(f =>
    '<button type="button" class="boton secundario opcion-fase" data-corrida="' +
    a.clave + '" data-fase="' + f.orden + '" title="' + queEsLaFase(a, f) + '"' +
    elegida(a.clave, f.orden) + "><b>" + nombreDeFase(a, f) + "</b><small>" +
    duracionCorta(f.duracion_de_captura_s) + "</small></button>").join("");
  return '<div class="fila-sesion fila-corrida" data-fuente="f1"' +
    (corrida.adquisicion === a.clave ? ' data-elegida="si"' : "") + ">" +
    "<span><b>" + (a.es_reproduccion ? a.clave : "Original") + "</b><br>" +
    "<small>" + que + " · " + cuando + "</small></span>" +
    "<span>" + a.vehiculos + (a.vehiculos === 1 ? " vehículo" : " vehículos") +
    "<br><small>" + cifra(a.muestras_de_vuelta, 0) + " muestras · " +
    (etapas.length === 1 ? "una sola etapa" : etapas.length + " etapas") +
    (seSolapa ? " · el reloj se reinicia entre ellas: hay que elegir una" : "") +
    "</small></span>" +
    '<span class="acciones-corrida">' +
      (seSolapa ? "" :
        '<button type="button" class="boton secundario opcion-fase" data-corrida="' + a.clave +
        '" data-fase="" title="las etapas seguidas, como se capturaron"' +
        elegida(a.clave, null) + "><b>Todo</b><small>" + duracionCorta(total) +
        "</small></button>") + fases +
    "</span></div>";
}

function abrirElectorDeCorrida(ruta, apertura, s) {
  const velo = document.getElementById("velo-corridas");
  const cont = document.getElementById("tabla-corridas");
  const sub = document.getElementById("sub-corridas");
  const nota = document.getElementById("nota-corridas");
  if (!velo || !cont) return;
  _contextoDeCorrida = { ruta: ruta, s: s };

  const lista = corrida.disponibles || [];
  if (sub) {
    sub.textContent = corrida.adquisicion
      ? "mirando « " + etiquetaDeCorrida() + " », de " + lista.length + " adquisiciones"
      : lista.length + " adquisiciones bajo el mismo identificador";
  }
  if (nota) {
    nota.textContent =
      "Una adquisición es cada vez que esta sesión se capturó o se reprodujo. " +
      "Las etapas son los tramos entre reinicios del reloj del juego: en una " +
      "carrera, la formación, la espera de luces y la carrera propiamente dicha. " +
      "Se puede cambiar cuando se quiera, con el botón del encabezado.";
  }

  /* Lo elegido se marca. Un menu que no dice donde estas parado obliga a
     acordarse, y al volver a abrirlo para cambiar de etapa es lo primero que
     hace falta saber. */
  const elegida = (clave, f) => (corrida.adquisicion === clave &&
    (corrida.fase || null) === (f || null))
    ? ' data-elegida="si" aria-pressed="true"' : ' aria-pressed="false"';

  cont.innerHTML = lista.map(a => filaDeCorrida(a, elegida)).join("");

  cont.querySelectorAll("button[data-corrida]").forEach(b => {
    b.addEventListener("click", () => {
      elegirCorrida(b.dataset.corrida, b.dataset.fase ? Number(b.dataset.fase) : null);
    });
  });

  velo.dataset.abierto = "si";
  pintarBotonDeCorrida();
}

/* CAMBIAR DE ETAPA ES VOLVER A ABRIR, NO SUPERPONER.
   Las vueltas, las series, las posiciones y el trazado que hay en pantalla son
   de la etapa anterior. Si no se sueltan, la primera vuelta de la carrera queda
   dibujada sobre el trazado de la formacion y la linea de tiempo mezcla las
   dos. Se olvida lo que depende del alcance ---no la sesion, que es la misma---
   y se anula lo que quedo pedido, que ya no le sirve a nadie. */
function elegirCorrida(clave, fase) {
  if (!_contextoDeCorrida) return;
  const velo = document.getElementById("velo-corridas");
  if (velo) velo.dataset.abierto = "no";

  const pedida = (fase === undefined || fase === "") ? null : fase;
  /* UN ALCANCE A MEDIAS NO PIDE DATOS.
     Es el mismo cuidado que la lectura de la direccion, en el otro camino que
     lleva hasta aca. Sin esto, cualquier llamada con la adquisicion sola
     ---un enlace viejo, un elector de otra version--- volvia a cargar la
     mezcla. Se conserva lo que sí se eligio y se pregunta el resto. */
  if (!alcanceElegidoEsValido(clave, pedida)) {
    const a = (corrida.disponibles || []).find(x => x.clave === clave);
    corrida.adquisicion = a ? clave : null;
    corrida.fase = null;
    declararAlcance();
    pintarBotonDeCorrida();
    estadoSesion = "vacio";
    estado.cargando = false;
    estado.motivo = a
      ? ("En esta captura el reloj del juego se reinicia entre etapas, así que " +
         "sus ventanas de tiempo se solapan. Juntas no son una carrera continua: " +
         "hay que elegir una etapa.")
      : "Esa adquisición no está en esta sesión. Elegí una de las que hay.";
    decirEstadoApi(estado.motivo, false);
    abrirElectorDeCorrida(_contextoDeCorrida.ruta, aperturaVigente(), _contextoDeCorrida.s);
    render();
    return;
  }

  corrida.adquisicion = clave;
  corrida.fase = pedida;

  /* La direccion refleja lo elegido, sin recargar: el enlace tiene que seguir
     sirviendo para volver a esto mismo. */
  try {
    const u = new URL(location.href);
    u.searchParams.set("adquisicion", corrida.adquisicion);
    if (corrida.fase) u.searchParams.set("fase", String(corrida.fase));
    else u.searchParams.delete("fase");
    history.replaceState(null, "", u.toString());
  } catch (e) { /* sin historial se sigue igual */ }

  olvidarLoDeLaCorrida();
  estadoSesion = "cargado";
  estado.cargando = true;
  declararAlcance();
  pintarBotonDeCorrida();
  decirEstadoApi("Mirando « " + etiquetaDeCorrida() + " », de " +
                 (corrida.disponibles || []).length + " adquisiciones.", false);
  render();
  cargarDatosDeSesion(_contextoDeCorrida.ruta, nuevaSesionEnCurso(),
                      senalDeSesion(), _contextoDeCorrida.s);
}

/* El boton del encabezado dice que se esta mirando y sirve para cambiarlo.
   Solo aparece cuando hay algo que elegir: en una sesion de una sola
   adquisicion seria un control que no hace nada. */
/* ============================================================
   UNA SESION CON VARIAS ETAPAS TAMPOCO SE PUEDE MIRAR JUNTA
   ------------------------------------------------------------
   EL DEFECTO. `mezclada` lo decide la API contando **adquisiciones**, y con
   una sola contestaba `false`: el tablero cargaba sin resolver el alcance, sin
   ofrecer el elector ---el boton se escondia con `disponibles.length > 1`--- y
   sin mirar siquiera la eleccion que traia la direccion. Quien elegia
   «Original · Carrera» y recargaba volvia a «todo junto» con la direccion
   diciendo lo contrario.

   POR QUE IMPORTA. Una etapa empieza donde el reloj del juego se reinicia, y
   al reiniciarse el `timestamp` derivado retrocede: la formacion y la carrera
   **se solapan en UTC a proposito**. Juntas no son una carrera continua.

   MEDIDO EN SPA, 2026-09-08, recorriendo de la vuelta 1 a la 4:

   | | sin resolver el alcance | Original · Carrera |
   |---|---:|---:|
   | retrocesos de la distancia | 72 (el peor, 7.003 m -> 1 m) | 0 |
   | retrocesos de la marca del coche | 61 (el peor, 6.477 m -> 634 m) | 0 |
   | salto del instante al pasar de la vuelta 1 a la 2 | **-40,8 s** | +0,25 s |

   La vuelta 1 sin acotar trae la formacion y la carrera entrelazadas: el coche
   avanza, salta atras, vuelve a avanzar. Se estabiliza cuando se acaban las
   muestras de formacion, que es a mitad de la vuelta 2. Es exactamente el
   sintoma que se reporto.

   LA REGLA. Se resuelve el alcance ---o se pregunta--- cuando hay mas de una
   adquisicion **o** cuando alguna tiene etapas que reinician el reloj del
   juego. Eso ultimo lo declara la propia API en cada fase, asi que no hay que
   adivinarlo. Con etapas que no reinician nada, seguidas son continuas y
   mirarlas juntas es correcto: no se molesta a nadie.
   ============================================================ */
function adquisicionSeSolapa(a) {
  if (!a) return false;
  const fases = a.fases || [];
  return fases.length > 1 && fases.some(f => f.reloj_del_juego_reinicia_al_entrar);
}

function alcanceEsAmbiguo() {
  const lista = corrida.disponibles || [];
  if (lista.length > 1) return true;
  return lista.some(adquisicionSeSolapa);
}

/* ============================================================
   UN ALCANCE ES LA ADQUISICION **Y** LA ETAPA
   ------------------------------------------------------------
   EL DEFECTO. Se comprobaba que la adquisicion existiera y nada mas:
   `?adquisicion=original` entraba con `fase = null`, que es «todo junto», el
   mismo alcance que la apertura sin parametros no deja pasar. El enlace se
   saltaba la proteccion. Y una fase que no existe, o que es de otra
   adquisicion, se convertia en «todas» sin decirlo: se pedia `fase=9`, la API
   no la encontraba y devolvia la mezcla.

   LA REGLA. Sin fase, el alcance vale solo si las etapas de esa adquisicion no
   se solapan. Con fase, tiene que ser un numero entero que **esa** adquisicion
   declare. Nada se convierte en otra cosa en silencio.
   ============================================================ */
function alcanceElegidoEsValido(clave, fase) {
  const a = (corrida.disponibles || []).find(x => x.clave === clave);
  if (!a) return false;
  if (fase === null || fase === undefined) return !adquisicionSeSolapa(a);
  if (typeof fase !== "number" || !Number.isInteger(fase)) return false;
  return (a.fases || []).some(f => f.orden === fase);
}

/* ============================================================
   NO SE PIDE HISTORICO CON EL ALCANCE SIN RESOLVER
   ------------------------------------------------------------
   `abrirSesionGuardada` ya no carga hasta que alguien elige, pero **no es el
   unico que pide**: el transporte pide la vuelta que hay bajo el cabezal por su
   cuenta, con doscientos milisegundos de retardo, desde que la pagina arranca.
   Esa consulta salia antes de que `/adquisiciones` contestara. Medido en Spa:
   la vuelta 1 se pedia a los 582 ms y las adquisiciones llegaban a los 953, de
   modo que la primera vuelta se traia mezclada aunque el elector estuviera
   abierto esperando una respuesta.

   La compuerta va aca, que es por donde pasa todo el historico. Mientras no se
   sepa que adquisiciones hay, no se pide; sabiendolo, se pide solo si el
   alcance no es ambiguo o si ya esta elegido entero.
   ============================================================ */
function alcancePermitePedir() {
  /* Sin eje de distancia no hay vuelta que pedir: la ruta que trae las series
     va contra metro. Se corta aca, que es por donde pasa todo el historico, y
     no en cada sitio que pide. */
  if (!hayEjeDeDistancia()) return false;
  if (!corrida.disponibles) return false;
  if (!alcanceEsAmbiguo()) return true;
  return alcanceElegidoEsValido(corrida.adquisicion, corrida.fase);
}

/* La etapa que trae la direccion, leida sin adivinar. `Number("abc")` da `NaN`
   y `Number("3.5")` da 3,5: los dos entraban y quedaban en `corrida.fase`
   pareciendo una eleccion. Vacio es «no pidieron etapa»; cualquier otra cosa
   que no sea un entero escrito en digitos es `NaN`, o sea invalida. */
function faseDeLaDireccion(texto) {
  if (texto === null || texto === undefined) return null;
  const t = String(texto).trim();
  if (!t) return null;
  return /^[0-9]+$/.test(t) ? Number(t) : NaN;
}

/* Hay algo que elegir aunque no sea ambiguo: con varias etapas continuas el
   boton sigue sirviendo para mirar una sola. Ofrecerlo no obliga a nada. */
function hayAlcanceQueElegir() {
  const lista = corrida.disponibles || [];
  return lista.length > 1 || lista.some(a => (a.fases || []).length > 1);
}

function pintarBotonDeCorrida() {
  const b = document.getElementById("btn-corrida");
  if (!b) return;
  const hay = hayAlcanceQueElegir();
  b.hidden = !hay;
  if (!hay) return;
  b.textContent = corrida.adquisicion
    ? "Etapa: " + etiquetaDeCorrida()
    : "Elegir qué mirar";
  b.title = corrida.adquisicion
    ? "Cambiar la adquisición o la etapa que se está mirando"
    : "Esta sesión guarda varias adquisiciones: elegí cuál mirar";
}

/* El nombre de una fase se deduce de su sitio y su largo, y se dice como tal:
   son los tramos que el reloj del juego separa, no etiquetas que la fuente
   declare. Con una sola fase no hay nada que nombrar. */
/* «Vuelta 10/8» afirma algo imposible, y aparecio en cuanto una captura empezo
   con el juego ya en la vuelta 4.

   Son dos numeraciones distintas puestas una al lado de la otra: `t.vuelta` es
   **el numero que le da el juego** ---el que se ve en su propia pantalla, y el
   que sirve para comparar con el--- y el total es **cuantas se grabaron**. Con
   la grabacion empezada tarde, la primera es mayor que la segunda.

   No se resuelve renumerando desde uno: eso tiraria el unico dato que permite
   cruzar esta sesion con la del juego. Se resuelve **diciendo el tramo que se
   grabo**, que es lo que explica por que el numero no llega hasta el total.

   Cuando la grabacion si empieza en la vuelta uno ---el caso comun--- «X/N» es
   cierto y se deja como estaba. */
function rotuloDeVuelta(t) {
  const numeros = (estado.vueltas || []).map(v => v.numero).filter(n => n > 0);
  if (!numeros.length) return t.vuelta + "/" + t.vueltas;
  const primera = Math.min.apply(null, numeros);
  const ultima = Math.max.apply(null, numeros);
  if (primera <= 1) return t.vuelta + "/" + t.vueltas;
  // Con una sola vuelta no hay tramo que declarar: «7 de 7-7» no dice nada que
  // «7» no diga, y dice peor.
  if (primera === ultima) return String(t.vuelta);
  return t.vuelta + " de " + primera + "\u2013" + ultima;
}

/* Escuchar y recibir no son lo mismo, y el tablero los confundia: decia que
   seguia la captura y se quedaba mostrando la sesion anterior, congelada, sin
   explicar que estaba esperando datos que no llegaban. Cualquiera concluye que
   se rompio ---se concluyo el 2026-09-09, y costo media hora---. La regla de
   este tablero es que no se dibuja lo que no se midio **y se explica por que**;
   esto es la parte que faltaba. */
function esperaDeTelemetria() {
  return estadoSesion === "vivo"
    ? "Entrando telemetria."
    : "Sin telemetria todavia: en cuanto el juego emita, el tablero cambia solo.";
}

/* Pide el catalogo hasta que se estabilice. `intentos` es el techo: cada uno
   espera un poco mas que el anterior, de modo que un refresco de siete segundos
   entra sin castigar al caso comun, que responde en el primero. */
function refrescarCatalogo(intentos) {
  const antes = SESIONES.length;
  pedir("/sesiones?limite=400")
    .then(c => {
      const lista = (c.sesiones || []).filter(s => s.filas > 0);
      const cambio = lista.length !== antes;
      SESIONES = lista;
      render();
      // Se insiste solo mientras no haya cambiado nada y queden intentos: en
      // cuanto la sesion nueva aparece, no hay motivo para volver a preguntar.
      if (!cambio && intentos > 1) {
        setTimeout(() => refrescarCatalogo(intentos - 1), (7 - intentos) * 1000 + 1000);
      }
    })
    .catch(() => {});
}

function nombreDeFase(a, f) {
  const fases = a.fases || [];
  if (fases.length <= 1) return "Fase única";
  if (f.orden === fases.length) return "Carrera";
  if (f.orden === 1) return "Formación";
  if (f.duracion_de_captura_s < 30) return "Espera de luces";
  return "Fase " + f.orden;
}

/* El alcance queda escrito en el documento. No es adorno: permite comprobar
   desde afuera ---una prueba, el banco de medicion--- que lo que el tablero
   esta pidiendo es lo que se eligio, en vez de suponerlo por lo que se pulso. */
function declararAlcance() {
  try { document.body.dataset.alcanceEnCurso = etiquetaDeCorrida(); } catch (e) {}
}

function etiquetaDeCorrida() {
  if (!corrida.adquisicion) return "todo junto";
  const a = (corrida.disponibles || []).find(x => x.clave === corrida.adquisicion);
  const base = a && !a.es_reproduccion ? "Original" : corrida.adquisicion;
  if (!corrida.fase || !a) return base;
  const f = (a.fases || []).find(x => x.orden === corrida.fase);
  return base + " · " + (f ? nombreDeFase(a, f) : "fase " + corrida.fase);
}

/* Lo que se pide una vez resuelto el alcance.
   Recibe la sesion del catalogo porque la necesita para nombrarla al terminar:
   dejarla implicita del ambito de `abrirSesion` funcionaba mientras el cuerpo
   vivia ahi, y al separarlo lanzaba un `ReferenceError` que se veia como «la
   sesion se abrio a medias». */
function cargarDatosDeSesion(ruta, apertura, senal, s) {
  /* Los avisos no hacen falta para dibujar y su consulta puede durar veinte
     segundos reteniendo una conexion. Se piden cuando ya hay un grafico. */
  cuandoHayaGrafico(() =>
  conCarga("avisos", () => pedir(ruta + "/avisos" + sufijoDeCorrida(false), { senal: senal })
    .then(d => {
      if (!sigueVigente(apertura)) return;
      ubicarAvisos(d.avisos || []); estado.avisosMotivo = d.motivo_ausencia || ""; render();
    })
    .catch(e => { if (!fueAnulada(e) && e instanceof TypeError) console.error(e); })));

  /* UNA CONSULTA ANULADA NO ES UNA CONSULTA QUE FALLO.
     Estos `catch` convertian cualquier error en una respuesta de respaldo
     ---vueltas vacias, clima nulo--- y la cadena seguia. Con la anulacion eso
     significa que cancelar una apertura no la detiene: escribe igual, encima
     de la sesion que si esta abierta, un estado vacio con un motivo de error.
     Se distingue: anulada corta la cadena, fallada declara el motivo. */
  /* EL CONTEXTO NO PUEDE MATAR LA APERTURA.
     Estaba dentro del mismo `Promise.all` que las vueltas, y su anulacion
     cortaba la continuacion entera: sin vueltas, sin trazado, sin coche y sin
     que la vuelta avanzara. Medido el 2026-09-08 sobre
     `f1_25:session:10802737583091545160`: `/contexto` tarda **31,42 s** y el
     corte por tiempo de `pedir` es de 30, de modo que se anulaba **siempre** y
     esa sesion no se abria nunca del todo. En Spa la misma ruta tarda 0,35 s y
     por eso el defecto no se veia.

     Clima, estado del vehiculo y puesta a punto son paneles: no hace falta
     ninguno para dibujar una traza. Se piden aparte y cada uno declara su
     ausencia si no llega. Lo unico que la apertura necesita esperar son las
     vueltas. */
  /* El contexto **tambien** espera. Estaba fuera de la espera porque no mata
     la apertura, pero no matarla no es lo mismo que no estorbarla: corriendo al
     lado de `/vueltas` le duplica el tiempo, y ninguno de sus tres paneles hace
     falta para dibujar una traza. */
  cuandoHayaGrafico(() =>
  conCarga(["clima", "vehiculo", "puesta"], () =>
    pedir(ruta + "/contexto" + sufijoDeCorrida(false), { senal: senal })
      .then(ctx => {
        if (!sigueVigente(apertura) || !ctx) return;
        estado.clima = ctx.clima || null;
        estado.climaMotivo = ctx.clima_motivo || "";
        estado.vehiculo = (ctx.esquinas && Object.keys(ctx.esquinas).length)
          ? { esquinas: ctx.esquinas, carroceria: ctx.carroceria } : null;
        estado.vehiculoMotivo = ctx.vehiculo_motivo || "";
        estado.puesta = (ctx.campos && ctx.campos.length) ? ctx : null;
        if (estado.clima) estado.disponibles.add("air_temperature");
        if (estado.vehiculo) estado.disponibles.add("tyre_temperature_surface_front_left");
        _firmaClima = ""; _firmaEsquinas = ""; _firmaPuesta = "";
        pintarClima(); pintarEsquinas(); pintarPuestaAPunto();
      })
      .catch(e => {
        if (fueAnulada(e)) {
          estado.climaMotivo = "la consulta de contexto se anuló; se reintenta al mover el cabezal";
        } else {
          estado.climaMotivo = e.message || "";
        }
        _firmaClima = "";
        pintarClima();
      })));

  conCarga(["vueltas"], () => Promise.all([
    pedir(ruta + "/vueltas" + sufijoDeCorrida(false), { senal: senal })
      .catch(e => (fueAnulada(e) ? null : { vueltas: [], error: e.message })),
    Promise.resolve(null),
    Promise.resolve({}),
  ]).then(([vueltas, trazado, ctx]) => {
    /* La conexion que ocupaba lo esencial quedo libre: lo secundario puede
       salir, haya llegado o no. */
    laEsencialTermino();
    if (!sigueVigente(apertura)) {
      TESTIGO.cortes.vigencia++; TESTIGO.ultimoCorte = "otra apertura la reemplazo";
      return;
    }
    if (vueltas === null) {
      TESTIGO.cortes.vueltasNulas++; TESTIGO.ultimoCorte = "/vueltas anulada";
      return;
    }

    estado.vueltas = vueltas.vueltas || [];

    /* QUIEN ES EL VEHICULO PROPIO SE DECIDE UNA VEZ Y ACA.
       Lo venian decidiendo dos consultas distintas ---la de series y la de
       posiciones--- segun cual contestara primero, y como la vuelta 1 de una
       sesion con dos capturas pegadas trae veinte vehiculos, a veces ganaba
       uno del que la fuente publica posicion y nada mas. El tablero quedaba
       pidiendo las señales de un vehiculo que no las tiene.

       `/vueltas` ya elige el mas muestreado ---que es el que se conduce, porque
       de los rivales solo hay cronometraje--- y ahora lo declara. Esa es la
       respuesta autoritativa y ninguna otra la pisa. */
    if (vueltas.vehiculo) {
      estado.vehiculoClave = vueltas.vehiculo;
      seleccion = new Set([vueltas.vehiculo]);
      armarAutos([vueltas.vehiculo]);
    }
    /* LO DERIVADO SE SUELTA CUANDO LLEGA LO AUTORITATIVO, NO SOLO AL RESETEAR.
       El reset de alcance ya invalida las vistas temporales, pero esto es otra
       cosa: pasa **dentro** de la misma apertura. Con el alcance ya elegido, el
       transporte pide la vuelta bajo el cabezal por su cuenta, y si `/series`
       contesta antes que `/vueltas` el primer render arma un reloj provisional:
       sin la ventana ni los cortes que declara la vuelta, apoyado en los
       extremos de la serie submuestreada y con un umbral deducido.

       Aca llegan los dos datos que ese reloj necesitaba ---los limites de cada
       vuelta y cual es el vehiculo propio--- y con el mismo numero de vuelta y
       el mismo vehiculo la clave de cache es la misma, de modo que el
       provisional seguia contestando hasta que algo mas subiera el sello. Se
       suelta aca, antes de que nadie vuelva a calcular el instante. */
    cambiaronLasSeries();
    /* Si alguna vuelta tiene un salto, se dice arriba: es un problema del dato
       y no del tablero, y quien mira tiene que saberlo antes de sacar una
       conclusion de la linea de tiempo. */
    const rotas = estado.vueltas.filter(v => v.continua === false);
    if (rotas.length) {
      decirEstadoApi(
        rotas.length + (rotas.length === 1 ? " vuelta tiene" : " vueltas tienen") +
        " un salto entre muestras seguidas ---vuelta " +
        rotas.map(v => v.numero).join(", ") + "---. La reproducción usa la duración " +
        "de conducción continua; la diferencia contra el tiempo total está declarada " +
        "en la respuesta de la API.", true);
    }
    poblarVueltas();
    // Clima, vehiculo y puesta los aplica su propia consulta, arriba.
    pedirTrazado(ruta);
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

    // Los avisos llegan por su cuenta; aca solo se recolocan los que ya haya,
    // porque ubicarlos necesita las vueltas y recien ahora estan.
    ubicarAvisos(estado.avisos.map(a => a));
    pedirCurvas(s);
    const primera = estado.vueltas.length ? estado.vueltas[0].numero : 1;
    vueltaElegida = primera;
    asegurarVuelta(primera);
    asegurarPosiciones(primera);
    estado.cargando = false;
    render();
    avisar("Sesión abierta: " + nombreDeSesion(s), false);
  }).catch(e => {
    /* Una excepcion aca dejaba la apertura a medias **en silencio**: el
       `.then` no tenia captura y el fallo se perdia como rechazo no atendido.
       Se veia como un tablero sin trazado y sin vueltas, sin ningun error. */
    TESTIGO.cortes.excepcion++;
    TESTIGO.ultimoCorte = (e && e.message) ? e.message : String(e);
    console.error("apertura interrumpida:", e);
    avisar("La sesión se abrió a medias: " + TESTIGO.ultimoCorte, true);
  }));
}

/* EL INSTANTE QUE SE ESTA MIRANDO, EN HORA UTC.
   Los paneles de contexto ---clima y estado del vehiculo--- no son series: son
   el ultimo valor publicado hasta un momento. Ese momento sale de la vuelta en
   curso, que ahora declara sus dos instantes, y de la fraccion recorrida. */
function instanteUtc() {
  const t = instante();
  /* EL MISMO INSTANTE QUE TODO LO DEMAS.
     Esto repartia la fraccion de vuelta sobre la ventana UTC **bruta**, que es
     justo la mezcla de relojes que el resto del tablero dejo de hacer: el
     transporte dimensiona la vuelta con la duracion efectiva y esta cuenta la
     estiraba sobre el intervalo entero. El clima que se mostraba podia ser el
     de otro momento de la vuelta.

     Que la consulta salga cada tres segundos no cambia nada: preguntar poco no
     es lo mismo que preguntar por el momento equivocado. */
  if (t.tUtcMs !== null && t.tUtcMs !== undefined && Number.isFinite(t.tUtcMs)) {
    return new Date(t.tUtcMs).toISOString();
  }
  /* Sin instante compartido ---en vivo, o antes de que llegue la vuelta--- se
     cae en lo unico que hay, y es una aproximacion declarada aca. */
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
let _contextoEnVuelo = false;
let _contextoUltimo = 0;

/* ESTAS DOS CONSULTAS SON LAS MAS CARAS DEL TABLERO.
   `/vehiculo` resuelve cuarenta señales con `DISTINCT ON` y tarda unos dos
   segundos y medio; `/avisos` casi tres. Pedirlas en cada cambio de vuelta
   ---que a diez veces la velocidad ocurre cada nueve segundos--- deja al
   navegador con una consulta pesada permanentemente en vuelo, y eso es lo que
   se siente como trabazon.

   Se acotan por dos lados: una sola en vuelo a la vez, y no mas de una cada
   tres segundos. El desgaste del neumatico y el clima no cambian mas rapido
   que eso. */
function refrescarContexto() {
  if (!estado.abierta || _contextoEnVuelo) return;
  const ahora = performance.now();
  if (ahora - _contextoUltimo < 3000) return;
  const t = instante();
  const clave = estado.abierta.session_id + "|" + t.vuelta;
  if (clave === _contextoDe) return;
  /* El instante se resuelve **antes** de anotar que hay una consulta en curso.
     Al reves ---como estaba--- una sesion sin instante utc dejaba la marca
     puesta y el contexto no se volvia a pedir nunca. */
  const cuando = instanteUtc();
  if (!cuando) return;
  _contextoDe = clave;
  _contextoUltimo = ahora;
  _contextoEnVuelo = true;
  const apertura = aperturaVigente();
  const ruta = "/sesiones/" + encodeURIComponent(estado.abierta.session_id);

  /* UNA SOLA CONSULTA PARA LAS TRES PARTES DEL CONTEXTO.
     Clima, estado del vehiculo y puesta a punto se piden siempre juntos y
     siempre al mismo instante. Eran tres viajes de red y tres idas a la base
     para responder la misma pregunta, en cada cambio de vuelta.

     Y no es solo velocidad: pedidos por separado pueden volver de instantes
     distintos si uno tarda mas que otro, y el panel mostraria el clima de un
     momento y el neumatico de otro. */
  conCarga(["clima", "vehiculo", "puesta"], () =>
    pedir(ruta + "/contexto?hasta=" + encodeURIComponent(cuando) + sufijoDeCorrida(true),
          { senal: senalDeSesion() })
      .then(d => {
        if (!sigueVigente(apertura)) return;
        estado.clima = d.clima || null;
        estado.climaMotivo = d.clima_motivo || "";
        estado.vehiculo = (d.esquinas && Object.keys(d.esquinas).length)
          ? { esquinas: d.esquinas, carroceria: d.carroceria } : null;
        estado.vehiculoMotivo = d.vehiculo_motivo || "";
        estado.puesta = (d.campos && d.campos.length) ? d : null;
        _firmaClima = ""; _firmaEsquinas = ""; _firmaPuesta = "";
        pintarClima(); pintarEsquinas(); pintarPuestaAPunto();
      })
      .catch(e => {
        // Si fallo, la clave se limpia para que el proximo intento vuelva a
        // pedirlo en vez de creer que ya lo tiene.
        _contextoDe = "";
        if (!fueAnulada(e) && e instanceof TypeError) console.error(e);
      })
      .then(() => { _contextoEnVuelo = false; }));
}

/* ============================================================
   LA PUESTA A PUNTO
   ------------------------------------------------------------
   Cinco campos, y la mitad del valor de este panel esta en decir cuales de
   ellos son una medicion legible y cuales son un codigo que el trabajo
   todavia no puede traducir. Un panel que muestra «compuesto: 7» sin decir
   que 7 es un codigo invita a leerlo como una cantidad.
   ============================================================ */
const ROTULO_PUESTA = {
  sesgo_de_freno_pct: "Sesgo de freno",
  mezcla_de_combustible: "Mezcla de combustible",
  modo_de_despliegue_ers: "Modo de ERS",
  compuesto: "Compuesto",
  edad_del_neumatico_vueltas: "Edad del neumático",
};

let _firmaPuesta = "";

function pintarPuestaAPunto() {
  const cont = document.getElementById("lista-puesta");
  if (!cont) return;
  const d = estado.puesta;
  const campos = (d && d.campos) || [];
  const firma = [estadoSesion, JSON.stringify(campos), tinta("--acento")].join("|");
  if (firma === _firmaPuesta) return;
  _firmaPuesta = firma;

  const motivo = document.getElementById("motivo-puesta");
  if (motivo) motivo.textContent = (d && d.motivo_ausencia) ||
    "Esta fuente no publica configuración del vehículo.";

  cont.innerHTML = campos.map(c => {
    const rot = ROTULO_PUESTA[c.clave] || c.clave;
    const valor = c.decodificado
      ? cifra(c.valor, c.clave === "sesgo_de_freno_pct" ? 0 : 0) + " " + (c.unidad || "")
      : '<span class="codigo-crudo">' + cifra(c.valor, 0) + '</span>';
    return '<div title="Canal: ' + c.canal + '"><dt>' + rot + '</dt><dd>' + valor + '</dd></div>';
  }).join("");

  const sinDecodificar = (d && d.sin_decodificar) || [];
  const nota = document.getElementById("nota-puesta");
  if (nota) {
    nota.textContent = sinDecodificar.length
      ? "Los valores en gris son códigos de la especificación del juego. El " +
        "trabajo todavía no cita la tabla que los traduce, y traducirlos de " +
        "memoria pondría una anotación sin fuente donde hoy hay una medición."
      : "";
  }
  const cab = document.getElementById("canal-puesta");
  if (cab) cab.textContent = campos.length
    ? campos.length + " campos · " + (campos.length - sinDecodificar.length) + " legibles"
    : "—";
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

/* EL TRAZADO SE DIBUJA CON UNA VUELTA COMPLETA Y SIN SALTOS.
   Sin elegir vuelta, la API contesta con la primera, y si esa vuelta tiene un
   salto de horas ---dos cargas de la misma sesion pegadas--- el recorrido sale
   con tramos que no se recorrieron: el circuito se ve deformado. Se elige la
   primera vuelta que sea continua y completa; si no hay ninguna, se pide sin
   elegir y se declara. */
function pedirTrazado(ruta) {
  const buena = estado.vueltas.find(v => v.continua !== false && v.completa);
  const cual = buena ? "&vuelta=" + buena.numero : "";
  TESTIGO.trazadosPedidos++;
  conCarga("trazado", () =>
  pedir(ruta + "/trazado?puntos=600" + cual + sufijoDeCorrida(true), { senal: senalDeSesion() })
    .then(t => {
      if (!t || !t.puntos || !t.puntos.length) { TESTIGO.trazadosDescartados++; return; }
      TESTIGO.trazadosAplicados++;
      estado.trazado = t;
      const armado = trazadoAPath(t.puntos,
        /invertir/i.test(t.para_dibujarlo || "") &&
        !/no invertir/i.test(t.para_dibujarlo || ""));
      PISTA = {
        path: armado.path,
        largo_m: t.largo_m,
        desnivel_m: t.desnivel_m,
        muestras: t.muestras_originales,
        vuelta: t.vuelta,
        curvas: CURVAS,
      };
      const svg = document.getElementById("linea-pista");
      if (svg && svg.ownerSVGElement) delete svg.ownerSVGElement.dataset.reserva;
      const g = document.getElementById("marcas-pista");
      if (g) g.dataset.firma = "";
      render();
    })
    .catch(e => { if (e instanceof TypeError) console.error(e); }));
}

/* Los nombres de curva son anotacion externa citada: se piden por circuito y
   solo si la sesion declara cual es. Sin procedencia no hay nombres, y el
   trazado se dibuja igual con sus metros. */
function pedirCurvas(s) {
  const circuito = (s.procedencia && s.procedencia.circuito) || s.circuito;
  if (!circuito) { CURVAS = []; return; }
  conCarga("curvas", () =>
  pedir("/circuitos/" + encodeURIComponent(circuito) + "/curvas", { senal: senalDeSesion() })
    .then(d => { CURVAS = d.curvas || []; PISTA.curvas = CURVAS; render(); })
    .catch(() => { CURVAS = []; }));
}

(function controlesDelElector() {
  const cerrar = document.getElementById("btn-cerrar-corridas");
  if (cerrar) cerrar.addEventListener("click", () => {
    document.getElementById("velo-corridas").dataset.abierto = "no";
  });
  /* Volver a abrirlo. Sin esto la unica forma de cambiar de etapa era editar la
     direccion, que es justo lo que el elector vino a evitar. */
  const abrir = document.getElementById("btn-corrida");
  if (abrir) abrir.addEventListener("click", () => {
    if (!_contextoDeCorrida) return;
    abrirElectorDeCorrida(_contextoDeCorrida.ruta, aperturaVigente(), _contextoDeCorrida.s);
  });
})();

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
    /* Lo mismo, pero llevado a la unidad que el tablero muestra. La unidad sale
       de `divisorDePresentacion`, que en vivo la busca en el propio mensaje: es
       la misma politica que usan las series y el historico, escrita una vez.
       Sin unidad declarada, o con un par que no se sabe convertir, devuelve
       `null`: un numero cuya unidad no se conoce no se puede mostrar. */
    const leerEnUnidad = canal => {
      const mensaje = ultimos.get(nombreDeSenal(canal));
      if (!mensaje || mensaje.value === undefined || mensaje.value === null) return null;
      const d = divisorDePresentacion(canal, null, vehiculo);
      const v = numeroMedido(mensaje.value);
      return (v === null || d === null) ? null : v / d;
    };
    const velocidad = leer("speed");
    const vuelta = vivo.vuelta.get(vehiculo) || 1;
    /* `|| 0` convertia «todavia no se» en el metro cero, que es una posicion
       de la pista como cualquier otra. Se distingue: sin distancia declarada,
       la fraccion no se calcula y el coche no se coloca en ningun lado. */
    const hayMetro = vivo.distancia.has(vehiculo);
    const metro = hayMetro ? vivo.distancia.get(vehiculo) : 0;
    return {
      listo: velocidad !== null, indice: 0, vuelta: vuelta,
      vueltas: Math.max(vuelta, estado.vueltas.length || 1),
      /* DONDE VA EL COCHE EN VIVO, Y SON DOS CASOS DISTINTOS.

         Mientras el recorrido se esta midiendo, el camino dibujado **termina
         donde esta el coche**: el ultimo punto del trazo es su ultima posicion
         medida, de modo que la fraccion es uno y eso es exacto, no un relleno.

         Una vez congelado el circuito ---al cerrar la primera vuelta--- el
         camino ya no crece y el coche se ubica por la distancia que declara,
         igual que en una sesion guardada.

         Antes esto estaba fijo en uno **siempre**, incluido el caso del
         circuito completo, y ahi si era el final del trazado para siempre:
         medido el 2026-09-08, 283.768 muestras en 300 s y la marca se movio
         tres veces. */
      fraccion: PISTA.enConstruccion
        ? 1
        : ((hayMetro && PISTA.largo_m && Number.isFinite(metro))
            ? Math.max(0, Math.min(1, metro / PISTA.largo_m)) : 0),
      fraccionSesion: 1, segundos: 0, tUtcMs: null, metro: metro, metroSesion: null,
      velocidad: velocidad,
      acelerador: leer("throttle"), freno: leer("brake"), rpm: leer("rpm"),
      marcha: leer("gear"), gLong: leer("glong"), gLat: leer("glat"),
      gVert: leer("gvert"), tempMotor: leer("engineTemp"), ers: leer("ers"),
      ersMJ: leer("ers") === null ? null : Number(leer("ers")) / 1e6,
      combustibleKg: leer("fuel"), tempFrenoDel: leer("brakeTemp"),
      tempNeumatico: leer("tyre"), deslizamiento: leer("slip"),
      diferencia: leerEnUnidad("gap"), frenando: 0, avance: 1,
      /* En vivo no hay bloque de vuelta que declare unidades: cada mensaje trae
         la suya y se convierte con ella. Una unidad que no se sabe convertir da
         `null` ---una raya--- y no un numero en la unidad equivocada. */
      posicion: leer("posicion"),
      cronometroS: leerEnUnidad("cronometro"),
      cronometroMedido: estaEnLaUnidadQueSeMuestra("cronometro", null, vehiculo),
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

  /* LA CLAVE DEL VEHICULO VA SIEMPRE.
     `serieDeCanal` exige saber de que vehiculo se pide la señal, y esta bien
     que lo exija: en una sesion con varios, «la serie» sin decir de quien no
     significa nada. Pero aca se la estaba llamando sin ella y devolvia vacio,
     de modo que el instante entero quedaba sin datos: los medidores mostraban
     rayas, el transporte decia «0 m» y los graficos ---que si pasaban la
     clave--- dibujaban su escala y ningun trazo, porque la ventana movil se
     apoya en ese metro que valia cero. */
  const propioAqui = claveVehiculoPropio();
  const dist = serieDeCanal("speed", vuelta, propioAqui);
  const listo = !!(dist && dist.length);
  const idx = listo ? Math.min(dist.length - 1, Math.round(dentro * (dist.length - 1))) : 0;

  /* EL INSTANTE, RESUELTO UNA SOLA VEZ Y COMPARTIDO.
     De aca salen los instrumentos, la distancia de presentacion, la marca del
     coche y los cabezales de los graficos. Antes cada uno se ubicaba por su
     cuenta: la marca del coche interpolaba sobre instantes medidos y los demas
     redondeaban un indice, de modo que ni siquiera mostraban el mismo momento.
     `null` cuando no hay con que resolverlo ---una API sin `timestamp_utc`, o
     la vuelta todavia en viaje--- y entonces cada lectura vuelve a la rejilla
     por indice, que es lo que habia. */
  const tUtc = tiempoDePresentacion(vuelta, dentro);

  /* Lee una señal en el instante compartido. Las continuas se interpolan entre
     las dos muestras que lo rodean; las discretas se sostienen en escalon
     sobre su instante medido, porque una marcha no pasa por la 4,5. */
  const leer = (canal) => {
    if (tUtc !== null) {
      const st = serieTemporal(canal, vuelta, propioAqui);
      if (st) {
        return esCanalEscalonado(canal) ? valorEscalonadoEn(st, tUtc)
                                        : valorContinuoEn(st, tUtc);
      }
    }
    const s = serieDeCanal(canal, vuelta, propioAqui);
    if (!s || !s.length) return null;
    return s[Math.min(s.length - 1, Math.round(dentro * (s.length - 1)))][1];
  };

  const v = leer("speed");
  /* Cuanto se esta frenando: la velocidad de ahora contra la de la muestra
     siguiente. Se toma del mismo eje temporal que `v`, no de un indice: mezclar
     un valor interpolado con la muestra cruda de al lado daba una diferencia
     que no era ni una cosa ni la otra. */
  const stV = tUtc !== null ? serieTemporal("speed", vuelta, propioAqui) : null;
  const sig = stV
    ? (function () {
        const i = _antesDe(stV, tUtc);
        return stV.v[Math.min(stV.v.length - 1, Math.max(0, i + 1))];
      })()
    : (listo ? dist[Math.min(idx + 1, dist.length - 1)][1] : null);

  /* LA DISTANCIA DE PRESENTACION TAMBIEN SALE DEL INSTANTE.
     Es la que corre la ventana de los graficos y la que coloca el cabezal en
     modo vuelta completa. Sacarla de la muestra discreta de velocidad dejaba la
     ventana anclada a un metro que solo cambiaba cada 425 ms. No se interpola
     sobre el cruce de meta: cuando la distancia baja, la vuelta se cerro. */
  const stD = tUtc !== null ? serieTemporal(EJE_DISTANCIA, vuelta, propioAqui) : null;
  const metroSuave = stD ? valorContinuoEn(stD, tUtc, true) : null;

  /* LA MISMA POSICION, SOBRE EL EJE QUE NO SE REINICIA.
     `metro` es la distancia de la vuelta y vuelve a cero en la meta: sirve para
     el circuito y para el modo vuelta completa, y corta la ventana movil en dos.
     `metroSesion` es la acumulada que la API mide, resuelta con **este mismo**
     instante y sobre la misma serie temporal, de modo que no hay un segundo
     reloj que pueda desfasarse del primero. `null` cuando la fuente no la trae,
     y entonces la ventana vuelve a ser de vuelta. */
  const stS = tUtc !== null ? serieTemporal(EJE_DISTANCIA_SESION, vuelta, propioAqui) : null;
  const metroSesion = stS ? valorContinuoEn(stS, tUtc, true) : null;

  return {
    listo: listo,
    indice: idx,
    vuelta: vuelta,
    vueltas: n,
    fraccion: dentro,
    fraccionSesion: cabezal,
    segundos: cabezal * total,
    /* El instante compartido, en milisegundos UTC. `null` significa que no se
       pudo resolver y que cada consumidor vuelve a la rejilla por indice. */
    tUtcMs: tUtc,
    metro: metroSuave !== null ? metroSuave : (listo ? dist[idx][0] : 0),
    metroSesion: metroSesion,
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
    /* EL PUESTO EN CARRERA, MEDIDO. Es `track_position_order`, que la fuente
       publica veinte veces por segundo y que estaba guardado sin que nadie lo
       leyera. Se lo lee en escalon: un puesto no se interpola. `null` antes de
       la primera muestra, que es donde no hay puesto que declarar. */
    posicion: leer("posicion"),
    /* EL CRONOMETRO DE LA VUELTA, EL DEL JUEGO. No es el tiempo de
       presentacion: aquel decide **que instante mirar** y este es una señal
       que se lee en ese instante. Viene en milisegundos y llega aca en
       segundos, convertido una sola vez al entrar la respuesta. */
    cronometroS: leer("cronometro"),
    cronometroMedido: estaEnLaUnidadQueSeMuestra("cronometro", vuelta, propioAqui),
    // Cuanto se esta frenando en este instante, para los paneles que lo usan.
    frenando: (v !== null && sig !== null) ? Math.max(0, v - sig) : 0,
    avance: cabezal,
    vueltasRestantes: Math.max(0, n - vuelta),
    sesgoFreno: (estado.puesta && estado.puesta.puesta_a_punto)
      ? estado.puesta.puesta_a_punto.sesgo_de_freno_pct : null,
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
  /* EL BARRIDO DE LOS INSTRUMENTOS ES DE UN MODO Y NO DEL OTRO.
     En el historico los valores se interpolan y cambian en cada cuadro: una
     transicion solo dibujaria la aguja donde estuvo hasta 300 ms atras, y eso
     es un desfase contra el coche y los graficos. En vivo no hay interpolacion
     ---se muestra el ultimo mensaje que llego, a la cadencia del flujo--- y sin
     transicion la aguja salta, que es lo que la transicion vino a arreglar. La
     hoja de estilos decide por este atributo. */
  try { document.body.dataset.modoDelTiempo = modo; } catch (e) {}

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

  /* SIN EJE DE DISTANCIA NO HAY REPRODUCCION QUE OFRECER, Y SE DICE ACA.
     El reproductor va contra distancia recorrida: la barra reparte la sesion
     por metro, las vueltas se delimitan por metro y los graficos van contra
     metro. Con una fuente que no la declara, el reproductor quedaba entero
     ---botones, barra, velocidades--- ofreciendo algo que al primer paso daba
     un fallo. Se apaga y se dice por que, que es lo que ya hacen la comparacion
     y el trazado con lo que su fuente no tiene. */
  if (!hayEjeDeDistancia()) {
    detener();
    barra.dataset.sinDistancia = "si";
    const nota = document.getElementById("nota-transporte");
    if (nota) {
      /* Sin dos puntos seguidos: el motivo ya trae los suyos. */
      nota.textContent = "En " + FUENTES[fuente].nombre +
        " no hay reproducción por distancia, porque " + porQueNoHayDistancia() +
        ". Las señales de esta captura se leen contra el tiempo.";
    }
    return;
  }
  barra.dataset.sinDistancia = "no";

  const t = instante();
  const s = serieDelPropio(t.vuelta);
  const total = s.length ? s[s.length - 1][0] : 0;
  const dur = duracionSesionS();

  // Lo primero que se lee es en que vuelta va, porque es lo que ubica todo
  // lo demas. El metro y el reloj acompañan.
  document.getElementById("tr-posicion").textContent = hayVueltas()
    ? "Vuelta " + rotuloDeVuelta(t)
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
      /* Una vuelta con un salto entre muestras no se rodo de corrido: hay
         tiempo que no esta. Se marca sobre la propia linea de tiempo, porque
         es ahi donde alguien se pregunta por que el cabezal se comporta raro. */
      const datos = estado.vueltas[v - 1] || {};
      const rota = datos.continua === false;
      const cuanto = rota ? Math.round(datos.hueco_mayor_s / 60) : 0;
      html += '<span class="marca-vuelta' + (v === t.vuelta ? " actual" : "") +
        (rota ? " rota" : "") + '" style="left:' + x.toFixed(2) + '%" title="Vuelta ' + v +
        (rota ? ": tiene un salto de " + cifra(cuanto, 0) +
                " minutos entre dos muestras seguidas. La duración que se usa es la " +
                "de conducción continua." : "") + '">' +
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
  _firmaPuesta = "";
  _ultimaVueltaDibujada = -1;
  const g = document.getElementById("marcas-pista");
  if (g) g.dataset.firma = "";
}

/* `porMano` distingue un movimiento que **pidio una persona** ---arrastrar la
   barra, los saltos de diez segundos, elegir una vuelta--- del avance
   automatico del reproductor, que llega sesenta veces por segundo. */
function moverCabezal(fraccion, porMano) {
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
  /* SEGUNDO MOTIVO PARA PEDIR: QUE ALGUIEN LO PIDA.
     El aviso de un fallo dice «mové el cabezal a esa vuelta para volver a
     pedirla», y esto pedia **solo al cambiar de vuelta**: quien ya estaba
     dentro de la vuelta fallida movia el cabezal y no pasaba nada, de modo que
     la instruccion del mensaje no se podia cumplir.

     Ahora un movimiento a mano dentro de una vuelta cuyo bloque falta tambien
     pide. Es del reintento y no del avance: el reproductor no pasa `porMano`,
     asi que el bucle de animacion sigue sin pedir nada dentro de la misma
     vuelta. Y comparte el mismo retardo, de modo que arrastrar la barra deja
     una consulta y no una por cada movimiento. */
  const reintentoAMano = !!porMano && !estado.series[vActual];
  if (vActual !== _ultimaVueltaDibujada || reintentoAMano) {
    _ultimaVueltaDibujada = vActual;
    /* NO SE PIDE NADA MIENTRAS EL CABEZAL SE MUEVE.
       Arrastrando la linea de tiempo se cruzan diez vueltas en un segundo, y
       cada cruce disparaba las consultas de esa vuelta: diez tandas de datos
       que nadie va a mirar, todas compitiendo con la unica que importa, que es
       la del sitio donde uno solto el cursor.

       Se espera a que el cabezal se quede quieto. Doscientos milisegundos
       alcanzan para distinguir un arrastre de una parada, y son invisibles
       reproduciendo, donde entre vuelta y vuelta pasan segundos. */
    clearTimeout(_relojPedidos);
    _relojPedidos = setTimeout(() => {
      const v = instante().vuelta;
      asegurarVuelta(v);
      asegurarPosiciones(v);
      refrescarContexto();
      /* Lo de la vuelta siguiente sale cuando lo de esta ya esta en camino:
         pedir las dos juntas ponia ocho consultas en vuelo y el navegador
         abre seis, de modo que la que hacia falta para dibujar quedaba
         haciendo cola detras de una que todavia no se mira. */
      clearTimeout(_relojSiguiente);
      _relojSiguiente = setTimeout(() => {
        /* LA SIGUIENTE DECLARADA, NO `v + 1`. Los numeros de vuelta no tienen
           por que ser seguidos ---una vuelta sin muestras no figura--- y pedir
           `v + 1` a ciegas gasta una consulta que la API solo puede contestar
           con una lista vacia. Se pregunta cual viene despues en la lista que
           `/vueltas` declaro; en la ultima no hay ninguna y no se pide nada.

           Y va **de fondo**: los paneles que estan en pantalla tienen dato
           valido, y encenderles el velo mientras se precarga lo que todavia no
           se mira dice que no lo tienen. */
        const siguiente = vueltaSiguienteDeclarada(v);
        if (siguiente === null) return;
        asegurarVuelta(siguiente, undefined, true);
        asegurarPosiciones(siguiente, true);
      }, 1200);
    }, 200);
  }
  /* La traza crece con el cabezal, asi que hay que volver a trazarla; treinta
     veces por segundo alcanza para que se vea continua y deja la mitad del
     presupuesto de cada cuadro libre para todo lo demas. */
  const ahoraT = performance.now();
  if (ahoraT - _ultimaTraza > 32) {
    _ultimaTraza = ahoraT;
    dibujarTraza();
  }
  /* Despues de trazar, no antes: el cabezal se coloca sobre el eje de metros
     que `dibujarTraza` acaba de fijar. Al reves, en el primer cuadro no hay eje
     todavia y la linea arranca en el sitio equivocado. */
  moverCabezalesGraficos();
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
let _relojSiguiente = null;
let _relojPedidos = null;

/* Cuantos metros de vuelta entran en cada grafico. Cero es la vuelta entera.
   Es el mando que decide si se mira una frenada o la vuelta completa: con
   trescientos metros se ve el pedal punto por punto; con la vuelta entera se
   ve la forma general y se pierde el detalle. */
let ventanaTraza = 1200;

function detener() {
  reproduciendo = false;
  /* Quien pausa cancela la espera: una respuesta que llega despues no puede
     deshacer lo que una persona decidio. */
  soltarEspera();
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
    /* SI FALTA LO IMPRESCINDIBLE, EL RELOJ SE DETIENE; NO SE SALTA.
       El cabezal no avanza y `anterior` ya quedo en `ahora`, de modo que el
       tiempo de espera no se acumula en ningun lado: al reanudar se sigue
       donde se dejo, sin recuperar nada de un tiron. El cuadro que hay en
       pantalla se queda como esta ---no se limpia ni se pasa a rayas--- y el
       aviso va en la linea de estado, que no tapa ningun instrumento. */
    const propuesto = cabezal + (dt * velocidadRep) / duracionSesionS();
    /* UN FALLO NO ES UNA ESPERA: SE PARA Y SE DICE.
       Avanzar sobre una vuelta que no va a venir vaciaria los graficos y
       pasaria los medidores a rayas. Se conserva el ultimo cuadro coherente,
       se detiene la reproduccion y se declara la salida: mover el cabezal a
       esa vuelta la vuelve a pedir. */
    if (propuesto < 1 && estado.fallo && estado.fallo[vueltaEnFraccion(propuesto)]) {
      const v = vueltaEnFraccion(propuesto);
      soltarEspera();
      detener();
      const f = estado.fallo[v];
      const motivo = (f && f.motivo) || f;
      decirEstadoApi("La vuelta " + v + " no se pudo traer: " + motivo +
                     (f && f.permanente
                       ? " La reproducción se detuvo acá y no se reintenta: " +
                         "volver a pedirla daría lo mismo."
                       : " La reproducción se detuvo acá; mové el cabezal a esa " +
                         "vuelta para volver a pedirla."), true);
      return;
    }
    if (propuesto < 1 && faltaLoImprescindible(propuesto)) {
      const v = vueltaEnFraccion(propuesto);
      /* Se pide una sola vez por espera, no una por cuadro. */
      if (anotarEspera(v)) { asegurarVuelta(v); asegurarPosiciones(v); }
      relojRep = requestAnimationFrame(paso);
      return;
    }
    soltarEspera();
    cabezal = propuesto;
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
    () => moverCabezal(cabezal - 10 / duracionSesionS(), true));
  document.getElementById("tr-adelante").addEventListener("click",
    () => moverCabezal(cabezal + 10 / duracionSesionS(), true));
  document.getElementById("tr-cabezal").addEventListener("input", e => {
    detener();
    moverCabezal(Number(e.target.value) / 10000, true);
  });
  /* Cuantos metros de vuelta entran en cada grafico. Vive al lado del mando de
     velocidad porque las dos son decisiones sobre el tiempo: una dice a que
     ritmo avanza la reproduccion, la otra cuanto del pasado se sigue viendo. */
  const mandoVentana = document.getElementById("tr-ventana");
  if (mandoVentana) {
    mandoVentana.addEventListener("click", e => {
      const b = e.target.closest("button"); if (!b) return;
      ventanaTraza = Number(b.dataset.ventana);
      marcar(mandoVentana, "ventana", b.dataset.ventana);
      _ultimaTraza = 0;
      dibujarTraza();
      moverCabezalesGraficos();
    });
  }

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

/* ============================================================
   EL CRONOMETRAJE: CINCO HECHOS DE DISTINTA NATURALEZA
   ------------------------------------------------------------
   LO QUE DECIA ANTES, Y POR QUE ESTABA MAL.

   «Vehículo: 19». El 19 es el indice del vehiculo en el protocolo, no su
   numero de carrera ---que es el 4--- ni su puesto. Y cuando habia un solo
   vehiculo con telemetria decia «sin parrilla», que confundia dos cosas
   distintas: que no haya participantes declarados, y que de veinte
   participantes se haya guardado la telemetria de uno. En esta captura la
   parrilla existe, tiene veinte nombres, y la telemetria es de uno.

   «Actual: 1:21.52», calculado como `fraccion del cabezal x duracion de la
   vuelta`. Eso es **el tiempo de reproduccion**, no el cronometro que midio el
   juego. Los dos numeros se parecen y no son lo mismo: uno dice donde esta el
   cabezal y el otro es una señal medida, `current_lap_time`, que estaba
   guardada desde el primer dia y que nadie leia.

   «Al líder: 2937.000» con el rotulo hablando de una diferencia de carrera.
   El canal viene en milisegundos: eran 2,937 s.

   LO QUE DICE AHORA. Cinco celdas, una por hecho: quien es, en que puesto va,
   en que vuelta, cuanto lleva de vuelta segun el cronometro del juego, y a
   cuanto del lider. Cada una con su ausencia propia cuando el dato no esta.
   ============================================================ */

/* Un tiempo de vuelta, en `m:ss,mmm`. Coma decimal, que es como se escriben
   los tiempos en castellano y como los escribe el resto del tablero. */
function tiempoDeVuelta(seg) {
  if (seg === null || seg === undefined || !Number.isFinite(seg)) return null;
  const negativo = seg < 0;
  const total = Math.abs(seg);
  const minutos = Math.floor(total / 60);
  const resto = total - minutos * 60;
  const ss = resto.toFixed(3).padStart(6, "0").replace(".", ",");
  return (negativo ? "−" : "") + minutos + ":" + ss;
}

/* Una diferencia de carrera, en segundos y con su signo. El cero valido se
   escribe `+0,000 s` y se distingue de la ausencia, que es una raya: un cero
   redondeado no convierte a nadie en lider. */
function diferenciaEnSegundos(seg) {
  if (seg === null || seg === undefined || !Number.isFinite(seg)) return null;
  const signo = seg < 0 ? "−" : "+";
  return signo + Math.abs(seg).toFixed(3).replace(".", ",");
}

/* TRES ESTADOS, NO DOS. El metadato de participantes declara si el vehiculo lo
   conducia la maquina; cuando no lo declara, eso es una tercera cosa y se dice.
   Y es lo que declaraba **ese momento de la captura**: el paquete de
   participantes es una foto, no un registro de quien tuvo el control durante
   toda la sesion, asi que se atribuye al metadato y no a la carrera. */
function quienConduce(esIA) {
  if (esIA === true) return "según la parrilla capturada, lo conducía la máquina";
  if (esIA === false) return "según la parrilla capturada, lo conducía una persona";
  return "la parrilla capturada no declara si lo conducía una persona o la máquina";
}

function pintarCronometraje() {
  const piloto = document.getElementById("crono-piloto");
  if (!piloto) return;
  if (estadoSesion === "vacio") return;
  const t = instante();
  const yo = autoPropio();
  const pon = (id, html, titulo, medido) => {
    const c = document.getElementById(id);
    if (!c) return;
    c.innerHTML = html;
    if (titulo === undefined || titulo === null) c.removeAttribute("title");
    else c.title = titulo;
    if (medido === undefined) c.removeAttribute("data-medido");
    else c.dataset.medido = medido ? "si" : "no";
  };

  /* QUIEN. El nombre y el numero de carrera arriba, el equipo debajo: son las
     dos cosas que identifican a un piloto, y no son la misma. El indice
     interno no es identidad y va al titulo, que es donde va lo tecnico. */
  pon("crono-piloto",
      textoSeguro(yo.nombre) +
        (yo.numero === null || yo.numero === undefined ? ""
          : ' <span class="unidad">#' + textoSeguro(yo.numero) + "</span>") +
        (yo.equipo ? '<span class="secundario">' + textoSeguro(yo.equipo) + "</span>"
                   : ""),
      yo.identidadDeclarada
        ? yo.completa + " · índice interno " + yo.indiceInterno + " · " +
          quienConduce(yo.esIA)
        : "La captura no declara la parrilla de esta sesión: «" +
          yo.indiceInterno + "» es el índice interno del vehículo en el " +
          "protocolo, no su número de carrera.");

  /* EN QUE PUESTO. Es `track_position_order`, medida y discreta. Sin muestra
     no hay puesto: una raya, nunca un P0 ni el puesto de hace un rato. */
  const puesto = t.posicion;
  const hayPuesto = puesto !== null && puesto !== undefined &&
                    Number.isFinite(puesto) && puesto >= 1;
  pon("crono-posicion",
      hayPuesto ? "P" + Math.round(puesto) : "—",
      hayPuesto
        ? "Puesto en carrera medido por la fuente en este instante"
        : "La fuente no declara puesto en carrera en este instante");

  /* EN QUE VUELTA. */
  pon("crono-vuelta",
      hayVueltas()
        ? rotuloDeVuelta(t).replace(/(\/|\sde\s)(.*)$/, '<span class="unidad">$1$2</span>')
        : '<span class="unidad">tramo</span>');

  /* CUANTO LLEVA DE VUELTA. Primero el cronometro medido; si la fuente no lo
     trae, el tiempo de reproduccion **declarado como tal**, porque un tiempo
     de cabezal presentado como medicion es una medicion inventada. */
  const medido = t.cronometroMedido ? t.cronometroS : null;
  const comoMedido = tiempoDeVuelta(medido);
  if (comoMedido !== null) {
    pon("crono-tiempo", textoSeguro(comoMedido),
        "Cronómetro de la vuelta medido por la fuente (current_lap_time)", true);
  } else {
    const deReproduccion = tiempoDeVuelta(t.fraccion * duracionDeVuelta(t.vuelta));
    pon("crono-tiempo",
        deReproduccion === null || !hayVueltas() ? "—"
          : "≈ " + textoSeguro(deReproduccion),
        "La fuente no trae el cronómetro de vuelta en este instante: esto es " +
        "el tiempo de reproducción, calculado con el cabezal y la duración " +
        "medida de la vuelta. No es una medición del juego.",
        false);
  }

  /* A CUANTO DEL LIDER. Es una señal de la fuente, no una cuenta que este
     tablero pueda hacer, y viene en milisegundos: llega aca en segundos porque
     la respuesta declara su unidad y se convierte al entrar. Si esa unidad no
     es la que se muestra, se dice que no se sabe en vez de escribir el numero
     bajo un rotulo que no le corresponde. */
  const enSegundos = estaEnLaUnidadQueSeMuestra("gap", t.vuelta, claveVehiculoPropio());
  const dif = enSegundos ? diferenciaEnSegundos(t.diferencia) : null;
  const celdaDif = document.getElementById("crono-diferencia");
  pon("crono-diferencia",
      dif === null ? "—" : textoSeguro(dif) + ' <span class="unidad">s</span>',
      dif === null
        ? (enSegundos
            ? "La fuente no declara diferencia con el líder en este instante"
            : "La diferencia llegó en una unidad que este tablero no sabe mostrar")
        : "Diferencia con el líder de la carrera (delta_to_race_leader)");
  if (celdaDif) {
    celdaDif.className = (dif !== null && t.diferencia < 0) ? "negativo" : "";
  }

  /* LA COBERTURA NO ES LA IDENTIDAD. Conocer los nombres de los rivales no es
     tener sus señales: se declara aparte y con sus propias palabras. */
  const cobertura = document.getElementById("crono-cobertura");
  if (cobertura) {
    const n = vehiculosConTelemetriaGuardada();
    const enParrilla = (parrillaVigente() || { vehiculos: [] }).vehiculos.length;
    cobertura.textContent =
      (n === 1 ? "1 vehículo con telemetría guardada" :
        n + " vehículos con telemetría guardada") +
      (enParrilla ? " · " + enParrilla + " en la parrilla declarada" : "");
  }

  const cab = document.getElementById("canal-traza");
  if (cab) cab.title = "Cabezal en " + Math.round(t.metro) + " m";
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
const INTENTOS_DE_MATRIZ = 12;

function pedirMatriz(intento) {
  pedir("/fuentes/matriz")
    .then(m => {
      estado.matriz = m;
      pintarMatriz();
      if (m && m.sin_medir && intento < INTENTOS_DE_MATRIZ) {
        setTimeout(() => pedirMatriz(intento + 1), 10000);
      }
    })
    .catch(e => { if (!fueAnulada(e) && e instanceof TypeError) console.error(e); });
}

function pintarMatriz() {
  const m = estado.matriz;
  const tabla = document.querySelector("table.disponibilidad");
  if (!m || !tabla) return;

  /* Todavia no hay medicion. Se dice, con su motivo, en vez de dibujar una
     tabla vacia que se leeria como "ninguna fuente sostiene nada". */
  if (m.sin_medir) {
    const inst = tabla.closest(".instrumento");
    const pieSin = inst ? inst.querySelector(".fuente-canal") : null;
    if (pieSin) pieSin.textContent = m.motivo_ausencia || "midiendo...";
    return;
  }

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

/* ---------------- qué vigilar si se corta ---------------- */

/* LA ÚNICA CONSULTA DEL TABLERO QUE NO MIRA EL VALOR DEL DATO.
   Las demás preguntan qué dice la telemetría; ésta pregunta qué pasa si deja
   de decir algo. Es una pregunta que un auto no tiene ---allí el sensor y el
   tablero están cableados juntos--- y que sólo aparece cuando el dato viaja.

   SE PIDE UNA VEZ POR SESIÓN, NO EN CADA RENDER. Mide la frecuencia real de
   cada canal sobre una ventana del final de la sesión, y eso cuesta unos tres
   segundos contra la tabla de ochenta y siete millones de filas. Es una
   propiedad de la sesión y no del cabezal: no cambia mientras se reproduce. */
let _vigilanciaPedida = null;

/* NO SE PIDE MIENTRAS LA SESION SE ESTA ABRIENDO.
   Medido en el navegador el 2026-09-08, sobre la sesion de Spa y con el backend
   recien arrancado: esta consulta tarda 29,8 s en frio, y mientras corre
   **bloquea a todas las demas**. `/fuentes/matriz`, que sola tarda 0,01 s,
   tardo 30 s en esa misma corrida; `/vueltas`, que sola tarda 1,4 s, tardo 16,7.
   No es la base: es trabajo de Python sobre muchas filas, que retiene el
   interprete mientras dura.

   Es un panel secundario ---que senales, si se pierden, merecen alarma--- y no
   hace falta para dibujar nada. Se pide despues, cuando el tablero ya tiene su
   primer trazo y las consultas que si hacen falta ya volvieron.

   Es una espera declarada, no un descarte: el panel dice que la esta esperando,
   y la respuesta se guarda en el backend, de modo que la segunda visita a la
   misma sesion la tiene enseguida. */
/* ============================================================
   LO SECUNDARIO ESPERA A QUE HAYA UN GRAFICO
   ------------------------------------------------------------
   Un navegador abre **seis conexiones por origen**. El flujo en vivo retiene
   una para siempre, y al abrir una sesion hay quince consultas que hacer. Con
   dos de ellas ---avisos y vigilancia--- ocupando una conexion cada una
   durante veinte segundos, quedan tres para todo lo demas, incluida la unica
   que hace falta para dibujar.

   Medido el 2026-09-08 y es lo que lo demuestra: `/fuentes/matriz` tardo
   4,04 s vistos desde el navegador y **no figura entre las consultas lentas
   que el backend registro**. Ese tiempo no lo paso siendo atendida: lo paso
   esperando una conexion libre.

   El backend no era el problema. Medido en la misma corrida: el retraso del
   bucle de asyncio fue de 8,7 ms de mediana y 23,5 ms el peor, y el pico de
   peticiones simultaneas fue cinco. Con una consulta pesada corriendo al lado,
   `/series` pasa de 1,91 s a 3,17 s ---1,7x, reparto normal de una base--- y no
   de 1,9 a 12.

   Asi que lo secundario espera. No se cancela ni se descarta: se pide en cuanto
   hay un trazo dibujado, o a los doce segundos si no llega a haberlo, para que
   un tablero sin datos no deje de pedir lo que si podria mostrar.
   ============================================================ */
/* DOCE SEGUNDOS NO ERAN LA CONDICION CORRECTA.
   La espera se soltaba por reloj, y en una sesion grande eso cae **en medio**
   de la consulta que hace falta para dibujar: lo secundario arrancaba mientras
   `/vueltas` todavia estaba corriendo, que es exactamente lo que se queria
   evitar.

   Medido el 2026-09-08 sobre Spa en `original`, fase 3, con el proceso recien
   arrancado. De a una y en caliente: `/vueltas` 3,07 s, `/contexto` 2,59 s,
   `/avisos` 0,01 s. Las mismas cuatro ---con `/vigilancia`--- lanzadas juntas
   desde el navegador: 45,3, 45,8, 41,2 y 42,5 s **cada una**, medidas del lado
   del servidor. No es reparto: la base es el recurso serie y correr cuatro
   consultas pesadas a la vez no las hace terminar antes, hace que terminen
   todas tarde. El navegador corto las cuatro a los 30 s y no se dibujo nada.

   Asi que la condicion pasa a ser la que importa: **que lo esencial ya este
   resuelto**, con o sin exito. El tope por reloj se conserva como red ---si
   `/vueltas` se colgara--- pero por encima del corte de 30 s de `pedir`, de
   modo que en la practica siempre se suelta por la primera condicion. */
const ESPERA_MAXIMA_DE_CORTESIA_MS = 35000;
let _enEspera = [];
let _relojCortesia = null;
let _esencialResuelta = false;

/* Lo esencial son las vueltas: sin ellas no hay eje ni duracion, y con ellas
   ya se puede dibujar. Se marca tanto si llegaron como si fallaron: lo que
   libera a lo secundario no es el exito, es que la conexion quedo libre. */
function laEsencialTermino() {
  _esencialResuelta = true;
  if (!_enEspera.length) return;
  const cola = _enEspera;
  _enEspera = [];
  cola.forEach(f => { try { f(); } catch (e) { console.error(e); } });
}

function cuandoHayaGrafico(hacer) {
  if (document.body.dataset.primerTrazoMs || _esencialResuelta) { hacer(); return; }
  _enEspera.push(hacer);
  if (_relojCortesia) return;
  const desde = performance.now();
  const mirar = () => {
    const listo = !!document.body.dataset.primerTrazoMs || _esencialResuelta;
    if (listo || performance.now() - desde > ESPERA_MAXIMA_DE_CORTESIA_MS) {
      _relojCortesia = null;
      const cola = _enEspera;
      _enEspera = [];
      cola.forEach(f => { try { f(); } catch (e) { console.error(e); } });
      return;
    }
    _relojCortesia = setTimeout(mirar, 250);
  };
  _relojCortesia = setTimeout(mirar, 250);
}

const ESPERA_ANTES_DE_VIGILANCIA_MS = 4000;
let _relojVigilancia = null;

function asegurarVigilancia() {
  if (!estado.abierta) return;
  const id = estado.abierta.session_id;
  if (_vigilanciaPedida === id) return;
  _vigilanciaPedida = id;
  clearTimeout(_relojVigilancia);
  cuandoHayaGrafico(() => {
    _relojVigilancia = setTimeout(() => pedirVigilancia(id), ESPERA_ANTES_DE_VIGILANCIA_MS);
  });
}

function pedirVigilancia(id) {
  if (_vigilanciaPedida !== id) return;
  pedir("/analisis/" + encodeURIComponent(id) + "/vigilancia", { senal: senalDeSesion() })
    .then(d => {
      if (_vigilanciaPedida !== id) return;   // cambió la sesión mientras tanto
      estado.vigilancia = d;
      estado.vigilanciaMotivo = "";
      render();
    })
    .catch(e => {
      if (_vigilanciaPedida !== id || fueAnulada(e)) return;
      estado.vigilancia = null;
      /* El backend explica por qué no puede, y ese motivo está escrito para
         leerse. Reemplazarlo por «no disponible» sería perder la explicación. */
      estado.vigilanciaMotivo = (e && (e.motivo || e.message)) || "";
      render();
    });
}

/* Sin abreviar el eje. «crítica» a secas volvería a fundir los dos ejes, que
   es exactamente lo que el módulo separa: la velocidad del vehículo es crítica
   **para el análisis** y no es un peligro. */
function textoNivel(v) {
  const eje = v.eje === "seguridad" ? "seguridad" : "análisis";
  if (v.nivel === "critica") return "alarma · " + eje;
  if (v.nivel === "atencion") return "aviso · " + eje;
  return "informativa";
}

function pintarVigilancia() {
  const panel = document.getElementById("panel-vigilancia");
  if (!panel) return;
  const cuerpo = document.getElementById("cuerpo-vigilancia");
  const canal = document.getElementById("canal-vigilancia");
  const conteo = document.getElementById("conteo-vigilancia");
  const nota = document.getElementById("nota-vigilancia");

  if (!estado.abierta) {
    panel.dataset.vacio = "si";
    cuerpo.innerHTML = "";
    conteo.innerHTML = "";
    canal.textContent = "—";
    nota.textContent = "Se calcula sobre una sesión abierta: sin sesión no hay frecuencias que medir.";
    return;
  }

  asegurarVigilancia();
  const d = estado.vigilancia;

  if (!d) {
    panel.dataset.vacio = "si";
    cuerpo.innerHTML = "";
    conteo.innerHTML = "";
    canal.textContent = estado.vigilanciaMotivo ? "no se pudo medir" : "midiendo…";
    nota.textContent = estado.vigilanciaMotivo ||
      "Midiendo la frecuencia real de cada canal sobre el final de la sesión.";
    return;
  }

  panel.dataset.vacio = "no";
  const c = d.conteo || {};
  conteo.innerHTML =
    '<span class="pastilla-nivel critica">' + (c.critica || 0) + ' de alarma</span>' +
    '<span class="pastilla-nivel atencion">' + (c.atencion || 0) + ' de aviso</span>' +
    '<span class="pastilla-nivel informativa">' + (c.informativa || 0) + ' informativas</span>';

  cuerpo.innerHTML = (d.vigilancias || []).map(v => {
    const hz = v.hz == null ? "—" : cifra(v.hz, 1) + " Hz";
    const sil = v.silencio_para_alarmar_s == null
      ? "sin medir"
      : cifra(v.silencio_para_alarmar_s, 2) + " s";
    return '<tr data-nivel="' + v.nivel + '">' +
      '<td><b>' + v.magnitud + '</b><small><code>' + (v.senal || "—") + '</code></small></td>' +
      '<td class="nivel"><span class="punto-nivel"></span>' + textoNivel(v) + '</td>' +
      '<td class="aviso">' + v.aviso_perdido +
        '<small>' + v.percepcion_del_conductor + '</small></td>' +
      '<td class="num">' + hz + '</td>' +
      '<td class="num">' + sil + '</td>' +
    '</tr>';
  }).join("");

  canal.textContent = (d.vigilancias || []).length + " canales medidos";
  /* La terna medida viaja con las cifras y no aparte: una frecuencia medida
     sobre un recorte que no se nombra no es verificable, y en este trabajo esa
     omisión ya produjo dos cifras plausibles y falsas. */
  nota.innerHTML = d.medido_sobre
    ? '<strong>Medido sobre:</strong> <code>' + d.medido_sobre + '</code>, en una ventana del final de la sesión.'
    : "";
}

/* ============================================================
   TESTIGOS: EVIDENCIA DE QUE ALGO CAMBIO EN PANTALLA
   ------------------------------------------------------------
   Un contador de `requestAnimationFrame` demuestra que el navegador entrego
   cuadros. No demuestra que el coche se haya movido, ni que un grafico haya
   mostrado un dato nuevo, ni que lo que se ve sea reciente. Son afirmaciones
   distintas, y hasta ahora la primera se estaba usando para sostener las
   otras: sesenta cuadros por segundo dibujando exactamente lo mismo dan el
   mismo numero que sesenta cuadros dibujando telemetria que avanza.

   Esto anota lo que de verdad cambio. Cuesta un puñado de comparaciones por
   cuadro y tiene memoria acotada ---contadores y un anillo de mil latencias,
   no un registro por mensaje---, de modo que puede quedar siempre encendido:
   una instrumentacion que hay que activar no esta cuando hace falta.

   SOBRE LA LATENCIA QUE MIDE. Es **de la recepcion del evento en el navegador
   hasta el pintado que lo incluye**, y nada mas. No es extremo a extremo: el
   reloj de la captura y el de esta maquina no tienen un origen comparable, y
   restarlos daria un numero con aspecto de medicion. Tampoco es el instante en
   que la pantalla se ilumina: es la llamada de dibujo, que ocurre antes.
   ============================================================ */
const LATENCIAS_RECORDADAS = 1000;
const TESTIGO = {
  //: Cuantas veces se ejecuto el dibujo del trazado.
  pintadosDePista: 0,
  //: De esas, cuantas movieron de verdad alguna marca de vehiculo.
  movimientosDeCoche: 0,
  //: Cuantas veces se redibujaron las trazas, y cuantas con dato distinto.
  dibujosDeTraza: 0,
  trazasConDatoNuevo: 0,
  //: Camino vivo.
  muestrasIncorporadas: 0,
  pintadosDeValores: 0,
  //: Anillo de latencias recepcion -> pintado, en milisegundos.
  latencias: [],
  //: Cuando llego la primera muestra todavia no reflejada en pantalla.
  pendienteDesde: null,
  //: El camino de la posicion, tramo por tramo. Sin esto no se puede decir
  //: donde se pierden: la fuente entrega veinte por segundo y el marcador se
  //: movia ocho, y atribuirlo a la fuente sin medir seria adivinar.
  //: LA CUENTA DEL CAMINO VIVO, TRAMO POR TRAMO.
  //: Sin separar los motivos, «llegan 675 de 1.856» no dice donde buscar.
  eventosSSE: 0,            // el manejador del EventSource se ejecuto
  descarteFuente: 0,        // no es F1 25, o le falta un campo obligatorio
  descarteDuplicado: 0,     // ya se habia incorporado esa identidad
  descarteNoAdoptada: 0,    // es de una sesion que este tablero no sigue
  descarteRecuperacionVieja: 0,
  //: Cuantas x y cuantas z llegaron. El par necesita las dos de la misma
  //: marca, de modo que una perdida del 50 % en cada una deja un cuarto de
  //: los pares: el emparejamiento amplifica la perdida al cuadrado.
  llegaronX: 0,
  llegaronZ: 0,
  paresRotos: 0,            // llego una y su companera no tenia la misma marca
  posicionesConLasDos: 0,   // llego el par (x, z) con la misma marca
  posicionesDistintas: 0,   // y ademas distinto del punto anterior
  pintadosSinCambio: 0,     // se pinto y la marca ya estaba donde va
  //: Cuantas veces se abrio una sesion y cuantas se pidio y se aplico el
  //: trazado. Abrir de mas no es solo trabajo repetido: cada apertura anula la
  //: anterior, y el trazado que venia en camino se pierde con ella.
  aperturas: 0,
  //: Por que se corto una apertura, si se corto. Una apertura que termina
  //: temprano deja el tablero a medias sin decir nada, y sin esto la unica
  //: pista es que faltan cosas en pantalla.
  cortes: { vigencia: 0, vueltasNulas: 0, contextoNulo: 0, excepcion: 0 },
  ultimoCorte: "",
  trazadosPedidos: 0,
  trazadosAplicados: 0,
  trazadosDescartados: 0,
  //: Cuantas muestras se juntaron en el pintado anterior. Con agrupamiento,
  //: una actualizacion visual representa varias muestras y solo muestra la
  //: ultima de cada canal: contar una por muestra seria falso.
  muestrasPorPintado: [],
  pendientes: 0,
};

function anotarLatencia(ms) {
  TESTIGO.latencias.push(ms);
  if (TESTIGO.latencias.length > LATENCIAS_RECORDADAS) TESTIGO.latencias.shift();
}

/* Lo publica en el objeto global para que un banco de medicion externo pueda
   leerlo: las variables de modulo no son propiedades de `window`. */
/* Antiguedad de lo que se esta mostrando, canal por canal. Un tablero puede
   tener sesenta cuadros por segundo y estar mostrando un valor de hace diez
   segundos: son dos cosas distintas y hay que poder preguntarlas por separado.

   Se mide contra el reloj de esta maquina y contra el instante de recepcion,
   nunca contra la marca de la fuente: esa viene de otro reloj. */
TESTIGO.antiguedades = function () {
  const salida = {};
  try {
    const clave = estado.vehiculoClave;
    const ultimos = vivo.ultimos.get(clave);
    if (!ultimos) return salida;
    const ahora = performance.now();
    ultimos.forEach((m, senal) => {
      if (m && typeof m._recibidoEnMs === "number") {
        salida[senal] = Math.round(ahora - m._recibidoEnMs);
      }
    });
  } catch (e) { /* sin sesion viva no hay nada que declarar */ }
  return salida;
};

window.TESTIGO = TESTIGO;

/* ---------------- render ---------------- */
/* ============================================================
   TRES CLASES DE TRABAJO, Y UN SOLO CUADRO
   ------------------------------------------------------------
   No todo lo que dibuja este tablero cuesta lo mismo ni cambia con la misma
   frecuencia. Hay tres cosas distintas mezcladas en una sola pasada:

   * **estructura**: que paneles existen, que vehiculos hay, que canales tiene
     la fuente, que opciones traen las listas. Cambia al abrir una sesion, al
     cambiar de fuente y al elegir otro vehiculo. Nunca por una muestra;

   * **valores**: los numeros de los instrumentos. Cambian con el cabezal, o
     sea muchas veces por segundo;

   * **trazas**: los lienzos. Cambian con el cabezal y con la ventana.

   Estaban las tres juntas, de modo que **cada muestra que llegaba en vivo
   rehacia las listas desplegables**. Ademas de trabajo, eso pisa el foco del
   teclado: quien estuviera tipeando en el buscador de sesiones lo perdia.

   `pedirPintado` junta lo que se pida dentro del mismo cuadro y lo hace una
   sola vez. Se piden capas, no funciones, y pedir dos veces la misma capa en
   el mismo cuadro la dibuja una vez.
   ============================================================ */
let _pedidoDePintado = 0;
const _capasPedidas = { estructura: false, valores: false, trazas: false };

function pedirPintado(capas) {
  (Array.isArray(capas) ? capas : [capas]).forEach(c => { _capasPedidas[c] = true; });
  /* Con la pestana oculta no hay nada que mirar, y el navegador no entrega
     cuadros igual: el pedido quedaria en cola y se acumularia. Lo pedido se
     conserva ---no se pierde la ultima actualizacion--- y se dibuja de una sola
     vez al volver, con lo que haya en ese momento, que es lo correcto: lo
     intermedio ya no le sirve a nadie. */
  if (typeof document !== "undefined" && document.hidden) return;
  if (_pedidoDePintado) return;
  _pedidoDePintado = requestAnimationFrame(() => {
    _pedidoDePintado = 0;
    const pedidas = Object.assign({}, _capasPedidas);
    _capasPedidas.estructura = _capasPedidas.valores = _capasPedidas.trazas = false;
    if (pedidas.estructura) pintarEstructura();
    if (pedidas.valores) pintarValores();
    if (pedidas.trazas) pintarTrazas();
  });
}

function pintarEstructura() {
  pintarCiclo(); aplicarDisponibilidad(); pintarAutos();
  pintarControlesTraza(); pintarLeyendaTraza();
  if (compAbierta()) pintarPilotosComparacion();
}

function pintarValores() {
  TESTIGO.pintadosDeValores++;
  if (TESTIGO.pendienteDesde !== null) {
    anotarLatencia(performance.now() - TESTIGO.pendienteDesde);
    /* Cuantas muestras representa este pintado. Con agrupamiento una
       actualizacion visual refleja varias y solo se ve la ultima de cada
       canal: contar una actualizacion por muestra seria falso. */
    TESTIGO.muestrasPorPintado.push(TESTIGO.pendientes);
    if (TESTIGO.muestrasPorPintado.length > LATENCIAS_RECORDADAS) {
      TESTIGO.muestrasPorPintado.shift();
    }
    TESTIGO.pendienteDesde = null;
    TESTIGO.pendientes = 0;
  }
  if (estadoSesion !== "vacio") vueltaElegida = instante().vuelta;
  pintarEsquinas(); pintarTransporte(); pintarCronometraje();
  pintarMedidores(); pintarClima(); pintarAvisos(); pintarG();
  pintarVigilancia(); pintarPuestaAPunto();
}

function pintarTrazas() {
  pintarPista(); dibujarTraza(); moverCabezalesGraficos();
  /* En vivo la comparacion no lee nada de lo que llega ---trabaja sobre
     vueltas cerradas--- asi que repintarla en cada muestra es trabajo por un
     dibujo identico. Se la repinta cuando cambia lo que si lee. */
  if (compAbierta() && !(estadoSesion === "vivo" && !Object.keys(estado.series).length)) {
    dibujarComparacion();
  }
}

/* La pasada completa. Se conserva ---y se sigue llamando en todo lo que cambia
   la estructura--- porque hay orden entre las capas: los valores necesitan la
   vuelta que fija `pintarValores`, y las trazas la necesitan ya fijada. */
function render() {
  /* La vuelta que se anuncia es siempre la del cabezal. Al cambiar de fuente
     cambia cuantas vueltas tiene la sesion, y sin esto el encabezado seguia
     anunciando la vuelta de la fuente anterior mientras el cronometraje ya
     mostraba la nueva: dos respuestas a la misma pregunta. */
  pintarEstructura();
  pintarValores();
  pintarTrazas();
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
  // `?quieto=1` deja la pagina donde esta. Sirve para mirar el encabezado y el
  // estado de la conexion, que es lo primero que hay que leer cuando algo no
  // aparece y lo que el encuadre automatico deja fuera de la vista.
  if (new URLSearchParams(location.search).get("quieto")) { yaEncuadrada = true; return; }
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
  /* EL LATIDO ESPERA SU PROPIA RESPUESTA.
     Era un `setInterval` de tres segundos. Medido el 2026-09-08, en frio
     `/sesion/activa` tarda 14,8 s: cada tres segundos se abria otra consulta
     de quince, sin que la anterior hubiera vuelto. A los treinta segundos hay
     diez en vuelo, cada una con su conexion a la base, y todo lo demas ---las
     vueltas, el trazado, las series--- hace cola detras. **El tablero se
     ahogaba solo**, y se veia como si la base fuera lenta.

     Encadenado, nunca hay mas de uno. Si la respuesta tarda quince segundos, el
     latido late cada quince: es lo que el sistema puede, y fingir tres no lo
     hace mas rapido. */
  const mirar = () => {
    if (!estado.abierta) { _relojVivo = null; return; }
    const otraVez = () => {
      if (document.hidden) { _relojVivo = null; return; }
      _relojVivo = setTimeout(mirar, 3000);
    };
    Promise.all([
      pedir("/sesion/activa?fuente=" + encodeURIComponent(estado.abierta.fuente)).catch(() => null),
      pedir("/live/status").catch(() => null),
    ]).then(([activa, vivo]) => {
      estado.activa = activa;
      estado.vivo = vivo;
      // El estado decorativo no convierte una sesion historica en viva. Solo
      // una muestra SSE correlacionada tiene autoridad para hacerlo.
      pintarTransporte();
    }).catch(() => {}).then(otraVez);
  };
  if (_relojVivo) { clearInterval(_relojVivo); clearTimeout(_relojVivo); }
  _relojVivo = null;
  mirar();
}

/* El latido son dos consultas cada tres segundos ---mil doscientas por hora---
   y con la pestana en segundo plano nadie las mira. Se corta al ocultarse y se
   retoma al volver, preguntando de entrada para no mostrar el estado viejo.

   La reproduccion no necesita nada de esto: `requestAnimationFrame` no entrega
   cuadros en una pestana oculta, asi que se detiene sola. Y al volver, el
   avance se calcula con el tiempo transcurrido de verdad, con un tope de
   250 ms por cuadro, de modo que una hora en segundo plano no salta la sesion
   hasta el final. */
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    if (_relojVivo) { clearInterval(_relojVivo); _relojVivo = null; }
  } else {
    // Al volver se dibuja lo que quedo pedido mientras no se miraba.
    if (_capasPedidas.estructura || _capasPedidas.valores || _capasPedidas.trazas) {
      pedirPintado([]);
    }
    if (estado.abierta && !_relojVivo) vigilarEnVivo();
  }
});

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

      /* SI YA HAY UNA SESION VIVA ADOPTADA, NO SE ABRE UNA GUARDADA ENCIMA.
         El catalogo tarda mas en llegar que la primera muestra del flujo. Al
         abrir el tablero con telemetria entrando, el vivo se adoptaba primero
         ---correctamente, no habia nada abierto--- y despues esta linea abria
         una sesion guardada **arriba**: quedaba el trazado de una carrera
         historica bajo el coche de la sesion en curso, `estado.vehiculoClave`
         en nulo, y el recorrido que se estaba midiendo borrado.

         Medido el 2026-09-08 con carga viva y el tablero abierto de cero:
         436.423 muestras incorporadas en 300 s y la marca del vehiculo se movio
         **siete veces**. Con la sesion viva ya elegida, abrir otra encima no es
         una preferencia: es pisar lo que se esta mirando.

         Salvo que la pidan por nombre: `?sesion=` es un acto explicito y manda.
         Tambien se declara, porque el catalogo sigue estando y la sesion
         guardada se puede abrir a mano. */
      if (vivo.sesion && !pedida) {
        estado.motivo = "";
        decirEstadoApi(SESIONES.length + " sesiones en el catálogo · siguiendo la " +
                       "sesión en vivo " + vivo.sesion, false);
        return;
      }
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
  /* LA MATRIZ SE PIDE HASTA QUE ESTE.
     Se mide recorriendo lo persistido y tarda decenas de segundos. Con el
     backend recien arrancado contesta `sin_medir` en vez de retener la
     conexion ---era una de las seis que el navegador da por origen, ocupada
     cuarenta segundos por el pie de pagina---. Se vuelve a preguntar cada diez
     segundos, un punado de veces: no es un sondeo permanente, es esperar a que
     un calculo que ya arranco termine. */
  cuandoHayaGrafico(() => pedirMatriz(0));
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
