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
  puestaMotivo: "",    // por que no hay reglaje, dicho por la API
  avisos: [],          // de /sesiones/{id}/avisos, derivados de la telemetria
  controlDeCarrera: [],     // de /racing/.../race-control, declarados por la fuente
  controlDeCarreraCrudo: [],
  avisosMotivo: "",
  /* Por que la consulta de avisos no contesto, si no contesto. Distinto de
     «llego vacia», igual que `fallo` lo es para las vueltas: sin esta marca el
     panel afirma que no hubo incidentes cada vez que la consulta se corta. */
  avisosFallo: "",
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
   siendo una linea y no dos puntos unidos: con cincuenta muestras sobre siete
   kilometros, cada una cubre 140 m, que alcanza para ver el ritmo de una
   vuelta ---que es lo que se compara en la vista de carrera--- y no para ver
   una frenada, que es lo que se mira vuelta por vuelta.

   ERA VEINTE, Y ESO PRODUCIA UNA CONSULTA QUE LA API RECHAZA. `/series` y
   `/series-tiempo` declaran `ge=50`: por debajo de cincuenta puntos no
   contestan. Con el reparto del presupuesto, a partir de **cuarenta y nueve
   vueltas** el pedido cae por debajo de ese piso y la vista de carrera entera
   falla. En una carrera de F1 25 no se notaba ---veintidos vueltas dan 109
   puntos--- y en Silverstone 2025, que tiene cincuenta y dos, daba 46 y la
   respuesta era «Input should be greater than or equal to 50».

   Eran dos pisos para lo mismo y el del cliente era mas bajo que el del
   servidor, o sea que el cliente podia construir una consulta invalida por su
   cuenta. Ahora es el mismo, y una prueba lo comprueba contra el `ge=` que
   declara la ruta: copiar una cifra sin comprobarla es como no tenerla.

   Este piso si puede ganarle al presupuesto, y hay que decir cuando: por
   encima de 48 vueltas. Con cincuenta y dos ---la carrera cargada--- se piden
   2.600 puntos contra los 2.400 declarados, un ocho por ciento de mas. El
   presupuesto es una guarda de memoria y la poda lo hace cumplir igual; el piso
   de la API es un contrato, y entre una guarda y un contrato gana el contrato. */
const PUNTOS_MINIMOS_POR_VUELTA = 50;
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

   Otros paneles ya se cuidaban ---la comparacion se apagaba con
   `fuente !== "f1"`, el trazado dice «recorrido reconstruido»--- y este no.
   Ahora hay una sola declaracion de que fuentes tienen el eje, la compuerta la
   mira antes de pedir, y el reproductor dice por que no hay reproduccion en vez
   de fallar.

   Aquella guarda de la comparacion ya no esta, y vale decir por que: apagarla
   por fuente era cuidar lo correcto con el criterio equivocado. Lo que la
   comparacion necesita son dos vehiculos con telemetria, y eso no depende de
   quien la publique; el eje, cuando no hay metro, lo resuelve `ejeVigente`.

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

/* QUE FUENTE PUBLICA POSICION MEDIDA, Y CUAL NO.
   Se parece a la pregunta de arriba y no es la misma. Una fuente puede no tener
   metro medido y si tener posicion: OpenF1 es exactamente eso ---sin distancia
   de vuelta, con `track_position_x/y` declarados---. Y `/trazado` sale de la
   posicion, no de la distancia. Decidirlo por el eje de distancia le habria
   quitado el trazado a OpenF1, que lo tiene. */
const COORDENADAS_POR_FUENTE = {
  f1: { hay: true, porque: "" },
  openf1: { hay: true, porque: "" },
  can: { hay: false, porque:
    "un bus vehicular de serie no publica posición: la forma del recorrido se " +
    "obtiene integrando velocidad y velocidad de guiñada, de modo que el trazo " +
    "es fiel y el sitio del mundo donde ocurrió no es recuperable" },
};

/* DE DONDE SALE EL DIBUJO DEL TRAZADO, EN UNA FRASE.
   Cuando la forma es derivada manda el texto que trae el punto de acceso: es el
   que hizo la reconstruccion y el unico que sabe con que la hizo. Se guardaba y
   no se mostraba nunca ---tener la explicacion y no darla---. Si no vino, se
   cae en el motivo declarado para la fuente, y recien despues en la descripcion
   general de la fuente, que es la que describe una posicion medida. */
/* QUE DICE EL ENCABEZADO DEL PANEL DE TRAZADO.

   LA PREGUNTA ERA LA EQUIVOCADA. Esto decidia con `if (PISTA.largo_m)`, o sea
   preguntaba «¿se cuantos metros mide?» y, cuando no lo sabia, respondia «sin
   trazado» ---con el circuito dibujado justo debajo---. Son dos cosas
   distintas: el dibujo sale de la **posicion** y el largo sale de la
   **distancia de vuelta**, y hay fuentes que publican la primera y no la
   segunda. El comentario de `COORDENADAS_POR_FUENTE` ya lo decia con todas las
   letras, y advertia que decidirlo por el eje de distancia le quitaria el
   trazado a OpenF1, que lo tiene. Esta funcion lo decidia asi igual.

   Visto el 2026-09-11 sobre `openf1:session:9947`, pedido como lo pide el
   tablero ---con la clave del vehiculo---: vuelta 21, 641 muestras, 321 puntos
   y `largo_m: null`. Esa fuente guarda nueve señales y `lap_distance` no es una
   de ellas, de modo que el largo no le falta a esa vuelta: no existe en la
   fuente.

   LA AUSENCIA SE DECLARA Y NO SE CALLA, pero solo cuando se sabe de quien es.
   Si la fuente no publica distancia, la falta de largo es un hecho de la fuente
   y se dice. Si la publica y este trazado igual no la trae, la falta es de esta
   vuelta: se omite el largo y nada mas. Decir «sin metro medido» ahi seria
   concluir sobre la fuente desde un solo trazado.

   El motivo completo ---por que esa fuente no lo publica--- no entra en un
   renglon y vive en el titulo del panel, que es donde ya estaba. */
function queDiceElTrazado(pista, ctx) {
  if (pista && pista.path) {
    const partes = [];
    if (pista.largo_m) partes.push(cifra(pista.largo_m, 0) + " m");
    else if (!ctx.hayDistancia) partes.push("sin metro medido");
    if (pista.desnivel_m) partes.push(cifra(pista.desnivel_m, 1) + " m de desnivel");
    if (pista.muestras) partes.push(cifra(pista.muestras, 0) + " muestras");
    /* De donde sale el dibujo. Un recorrido a medio medir y un circuito
       completo se ven parecidos y no son lo mismo: el primero termina donde va
       el coche y el segundo cierra. */
    if (pista.enConstruccion) partes.push("recorrido en construcción, medido en vivo");
    else if (pista.medidoEnVivo) partes.push("medido en vivo, primera vuelta cerrada");
    /* Un recorrido derivado no se puede ver igual que uno medido. La forma sale
       de integrar velocidad y guiñada, así que es fiel en su trazo y no dice
       nada del sitio del mundo donde ocurrió. */
    else if (pista.derivado) partes.push("forma derivada por integración, sin coordenadas");
    /* Si la marca del vehiculo se esta dibujando entre dos muestras, se dice.
       Es una representacion y no una medicion: el dato guardado y lo que se
       exporta siguen siendo las muestras, sin tocar. */
    if (ctx.interpolada) partes.push("posición interpolada entre muestras");
    return partes.join(" · ");
  }
  if (ctx.estadoSesion === "vivo") {
    /* En vivo, sin trazado todavia, la espera tiene una razon concreta y un
       final: se esta midiendo. Decir «sin trazado» a secas se leeria como que
       la fuente no lo publica, que es otra cosa. */
    return ctx.posiciones
      ? "midiendo el recorrido: " + cifra(ctx.posiciones, 0) + " posiciones"
      : "esperando la primera posición del vehículo";
  }
  return ctx.fuente === "can" ? "recorrido reconstruido" : "sin trazado";
}

function explicacionDelTrazado() {
  if (PISTA.derivado) {
    const base = PISTA.advertencia || porQueNoHayCoordenadas();
    /* Y como se la contrasta, que es lo que hace que una integracion se pueda
       creer: el ancho de via no viaja en el bus, asi que dos señales
       decodificadas por separado coincidiendo en el es la comprobacion mas
       fuerte que esta fuente admite. */
    const contraste = textoDeLaValidacion(PISTA.validacion);
    return contraste
      ? base + " Se contrasta contra las cuatro ruedas, que deducen el ancho de " +
        "vía del vehículo sin que el bus lo publique: " + contraste + "."
      : base;
  }
  const f = FUENTES[fuente];
  return (f && f.pista) || "";
}

function hayCoordenadasMedidas(cual) {
  const d = COORDENADAS_POR_FUENTE[cual === undefined ? fuente : cual];
  return !d || d.hay;
}

function porQueNoHayCoordenadas(cual) {
  const d = COORDENADAS_POR_FUENTE[cual === undefined ? fuente : cual];
  return (d && d.porque) || "esta fuente no declara posición medida";
}

/* CON QUE EJE SE ABRE LA VISTA AMPLIADA.
   Se abria siempre en distancia, que es el eje del simulador. Sobre el bus eso
   dejaba la pantalla en un cartel ---«esta vista espacial requiere distancia
   medida»--- con el boton que si funciona al lado y sin decir que estaba ahi.
   Un tablero que ofrece de entrada lo unico que no puede hacer se lee como si
   no pudiera hacer nada. */
function ejeQueLaFuenteSostiene(cual) {
  return hayEjeDeDistancia(cual) ? "distancia" : "tiempo";
}

/* EL EJE CON EL QUE SE DIBUJA, DEDUCIDO Y NO REPARTIDO.
   `ejeComparacion` es lo que la persona eligio, y sobrevive a cambiar de
   sesion: elegir distancia en el simulador y abrir despues un tramo del bus
   dejaba la vista pidiendo un metro que esa fuente no mide. Fijarlo al abrir
   habria sido acordarse en los tres sitios que abren la vista y olvidarse en el
   cuarto. Se deduce en un solo lugar: manda lo elegido cuando la fuente lo
   sostiene, y si no, el eje que si tiene. */
function ejeVigente() {
  return hayEjeDeDistancia() ? ejeComparacion : ejeQueLaFuenteSostiene();
}

/* QUE TRAMO ABARCA LA VISTA, EN UNA FRASE.
   EN EL BUS NO HAY VUELTAS: HAY UN TRAMO DE GRABACION. Decir «vuelta 1» sobre
   un minuto de ruta es forzar el vocabulario del circuito sobre un dato de
   calle, y ademas prometer que hay una vuelta 2. `hayVueltas` ya distingue las
   dos cosas en el resto del tablero. */
function coberturaDeLaVista(vuelta) {
  if (!hayVueltas()) {
    return (vuelta && vuelta.duracion_s)
      ? "tramo de " + cifra(vuelta.duracion_s, 1) + " s"
      : "tramo completo";
  }
  if (alcanceComparacion === "una") {
    return "vuelta " + vueltaElegida +
      (vuelta && vuelta.largo_m ? " · " + cifra(vuelta.largo_m, 1) + " m observados" : "");
  }
  return estado.vueltas.length + " vueltas observadas";
}

/* Que impide dibujar la vista ampliada, o cadena vacia si nada lo impide. */
function motivoDelEjeEspacial() {
  if (ejeVigente() !== "distancia") return "";
  if (hayEjeDeDistancia()) return "";
  return "Sin distancia medida: " + porQueNoHayDistancia() +
         ". Contra el reloj sí se puede: elegí «Tiempo» arriba.";
}

function hayEjeDeDistancia(cual) {
  const d = EJE_DE_DISTANCIA_POR_FUENTE[cual === undefined ? fuente : cual];
  return !d || d.hay;
}

function porQueNoHayDistancia(cual) {
  const d = EJE_DE_DISTANCIA_POR_FUENTE[cual === undefined ? fuente : cual];
  return (d && d.porque) || "esta fuente no declara distancia recorrida";
}

/* ============================================================
   QUE PANEL NO TIENE NADA QUE DAR NUNCA, Y CUAL SOLO NO LO TRAJO HOY
   ------------------------------------------------------------
   Son dos afirmaciones distintas y el tablero las venia mezclando en una sola.

   `data-necesita` dice «esta sesion no trajo esta señal»: el panel se queda en
   su sitio, se cubre y **escribe el motivo**, que es lo correcto cuando el dato
   podria haber estado. Una captura del simulador sin clima es eso.

   Esto otro dice «esta fuente no publica esto, ni hoy ni nunca». Ahi el panel
   solo puede decir que no: ocupa un cuarto de la pantalla para declarar una
   ausencia estructural mientras las señales que si se midieron se aprietan en
   lo que sobra. Se lo saca del tablero.

   EL HECHO NO SE PIERDE, Y ESO ES LA MITAD DE LA REGLA. La tabla del pie
   ---«Qué sostiene cada fuente»--- tiene una fila por instrumento y las tres
   fuentes en columnas: ahi es donde la ausencia es el tema y donde se puede
   comparar, que es lo que un panel tapado nunca deja hacer. Sacar un panel sin
   ese registro seria esconder; con el, es ordenar.

   POR QUE ACA Y NO EN LA HOJA DE ESTILOS. Estaba escrito como reglas
   `display: none` por fuente, y una regla de estilo no puede llevar el motivo
   ni la puede leer una prueba. Peor: el selector alcanzaba tambien a las filas
   de la tabla del pie, que llevan el mismo `data-panel` justamente para que
   quede el registro, de modo que la fuente que escondia un panel escondia
   ademas el unico sitio donde ese hecho seguia escrito.
   ============================================================ */
const PANELES_QUE_LA_FUENTE_NO_TIENE = {
  f1: {},
  /* CLIMA Y AVISOS SALIERON DE ESTA TABLA, Y LA CORRECCION VALE ANOTARLA.
     Estaban declarados aca como ausencias de la fuente, con estos dos motivos:
     «el clima no viaja en la telemetría de esta fuente» y «OpenF1 no publica
     banderas, daño ni tipo de superficie». El segundo lo copie de lo que
     contesta `/avisos`, que responde lo mismo para el bus y para OpenF1 porque
     lo decide por fuente ---`if fuente != "f1_25_udp_simulation"`--- y para el
     bus es cierto.

     Para OpenF1 es falso, y el dato esta en esta misma base. El propio backend
     lo cuenta en `/racing/sessions/9947`: **155 muestras de clima y 158 eventos
     de control de carrera**, de los cuales 89 son banderas ---32 amarillas, 12
     dobles, 41 de pista libre, 1 azul, la verde y la de cuadros--- mas ocho de
     coche de seguridad. Y `/racing/sessions/{key}/context-at` ya los devuelve
     resueltos en un instante, junto con la diferencia al lider, el compuesto y
     la edad del neumatico, declarando ademas que tan fresco es cada uno.

     Lo que falta no es el dato: es que el tablero llame a esa ruta. Una
     ausencia que se puede llenar no pertenece a esta tabla, porque esta tabla
     dice «nunca», y decir «nunca» sobre algo que esta guardado es lo mismo que
     esconderlo. */
  openf1: {
    /* Esto si es estructural: `car_data` entrega seis canales ---velocidad,
       acelerador, freno, regimen, marcha y DRS--- y ninguno es del estado del
       vehiculo. De los neumaticos, OpenF1 publica compuesto y edad en
       `stints`, que no es lo que este panel muestra: ni temperatura por
       esquina, ni presion, ni desgaste, ni daño por parte. */
    vehiculo: "OpenF1 no publica temperatura ni presión de neumáticos, ni daño " +
              "por parte: de la telemetría llegan seis canales y ninguno es del " +
              "estado del vehículo",
    puesta: "OpenF1 no publica la configuración del vehículo",
    aceleraciones: "OpenF1 no publica aceleraciones en ningún eje",
  },
  can: {
    puesta: "un bus vehicular de serie no publica la configuración del vehículo",
    vehiculos: "la captura del bus es de un solo vehículo: no hay con quién " +
               "comparar",
  },
};

/* El motivo por el que la fuente no sostiene ese panel, o cadena vacia si lo
   sostiene. Se devuelve el motivo y no un booleano: quien decide esconder algo
   tiene que poder decir por que, y el mismo texto sirve para el titulo. */
function porQueLaFuenteNoTieneElPanel(panel, cual) {
  const d = PANELES_QUE_LA_FUENTE_NO_TIENE[cual === undefined ? fuente : cual];
  return (d && d[panel]) || "";
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
/* QUE SE TIENE DE ESTE VEHICULO, Y NO QUE PAPEL CUMPLE.
   El rotulo de la lista decia «propio · N señales» para uno y «cronometraje»
   para todos los demas. Es cierto en la simulacion ---la telemetria privada es
   la del coche que se conduce, y de los rivales llega posicion--- y falso en
   OpenF1, donde los tres pilotos cargados traen las mismas nueve señales: el
   rotulo decia «cronometraje» sobre dos vehiculos con 310.881 filas cada uno.

   Se dice lo que hay. El propio tiene serie por definicion ---es el que la
   sesion declara mas muestreado--- y de los demas se mira si la trajeron. */
function loQueSeSabeDelVehiculo(a, conSerie, senales) {
  const tiene = a.propio || (conSerie || []).indexOf(a.id) !== -1;
  if (!tiene) return { clase: "senales", texto: "cronometraje" };
  return {
    clase: a.propio ? "propio" : "senales",
    texto: (a.propio ? "propio · " : "") + cifra(senales, 0) + " señales",
  };
}

/* COMPARAR SE HABILITA POR LO QUE HAY, NO POR DE DONDE VIENE.
   La condicion llevaba `fuente !== "f1"`, de cuando comparar era cosa del
   simulador: sobre OpenF1 el boton quedaba apagado con tres pilotos cargados y
   telemetria de los tres ---310.881, 310.881 y 310.863 filas---. Lo que hace
   falta para comparar son dos vehiculos, y de donde vengan no cambia eso.

   Sale de la condicion en linea para poder ejercerla: dentro del pintado solo
   se la podia comprobar buscando su texto en el archivo, y este codigo tiene
   los comentarios llenos de las formas que se estan buscando. */
function sePuedeComparar() {
  return estadoSesion !== "vacio" && AUTOS.length >= 2;
}

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
    /* Tres letras, en mayusculas, como los cronometrajes de television.

       LA SIGLA LA DECLARA LA FUENTE CUANDO LA TIENE. Recortar el nombre a tres
       letras es un respaldo, no un criterio: de «Max VERSTAPPEN» sale «MAX»,
       que no es como se lo rotula en ningun cronometraje. OpenF1 publica
       `name_acronym` ---«VER»--- y esa es la sigla de verdad. Si el nombre es
       mas corto que tres letras, va entero: recortar a lo que no hay tampoco
       es un criterio. */
    etiqueta: (declarado.etiqueta || declarado.nombre.slice(0, 3)).toUpperCase(),
    completa: conNumero + (declarado.equipo ? " · " + declarado.equipo : ""),
    declarada: true, indice: indice,
  };
}

/* LA PARRILLA DE OPENF1 EXISTIA Y NADIE LA PEDIA.
   ============================================================
   El tablero rotulaba «Vehículo 1, índice interno del protocolo» sobre una
   sesion donde la API contesta «Max VERSTAPPEN · VER · Red Bull Racing» con el
   color del equipo. El dato estaba entero en `racing_*` desde que se importo el
   contexto; lo que faltaba era la consulta.

   POR QUE NO LLEGABA POR EL CAMINO DE SIEMPRE. La identidad de una sesion
   guardada viene de `/adquisiciones`, que la declara por captura. Esa ruta es
   del simulador: para OpenF1 contesta la lista vacia, correctamente, porque
   esta fuente no se capturo ---se importo---. Su parrilla vive en el contexto
   deportivo, que es otro sitio y otra consulta.

   Se arma una adquisicion sola, con la clave del contexto, porque una sesion
   importada no tiene dos capturas que puedan nombrar gente distinta en el mismo
   indice: es la ambiguedad que `parrillaVigente` cuida, y aca no existe. */
function claveDeSesionOpenF1(sessionId) {
  const partes = String(sessionId || "").split(":");
  const ultima = partes[partes.length - 1];
  return /^\d+$/.test(ultima) ? ultima : null;
}

function parrillaDesdePilotos(sessionId, pilotos) {
  const vehiculos = (pilotos || []).map(d => ({
    vehicle_id: sessionId + ":driver:" + d.driver_number,
    nombre: d.full_name || null,
    numero: Number.isFinite(d.driver_number) ? d.driver_number : null,
    equipo: d.team_name || null,
    /* La sigla de television, declarada por la fuente. */
    etiqueta: d.name_acronym || null,
    /* Son personas: no es una casilla sin llenar, es un no. */
    es_ia: false,
  })).filter(v => v.nombre);
  return { disponible: vehiculos.length > 0, vehiculos: vehiculos };
}

function pedirParrillaDeOpenF1(sessionId, apertura) {
  const clave = claveDeSesionOpenF1(sessionId);
  if (!clave) return;
  /* La apertura la da quien llama. Tomarla aca ataba la consulta al orden en
     que se la invoque, y ese orden ya fallo una vez. */
  if (apertura === undefined) apertura = aperturaVigente();
  pedir("/racing/sessions/" + encodeURIComponent(clave) + "/drivers",
        { senal: senalDeSesion() })
    .then(pilotos => {
      if (!sigueVigente(apertura)) return;
      const parrilla = parrillaDesdePilotos(sessionId, pilotos);
      if (!parrilla.disponible) return;
      anotarParrillas(sessionId, [{ clave: "contexto", parrilla: parrilla }]);
      renombrarAutos();
      render();
    })
    .catch(e => { if (e instanceof TypeError) console.error(e); });
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
/* EL COLOR ES DEL VEHICULO, NO DE SU LUGAR EN LA LISTA.
   Se asignaba por la posicion dentro de `AUTOS`, y esa posicion cambia: la
   lista se rehace cuando aparece un vehiculo nuevo, y con la seleccion armada a
   mano el orden depende de en que orden se marco. El mismo piloto cambiaba de
   color entre el trazado, los graficos y las tarjetas, y volvia a cambiar al
   marcar a otro. Un color que se mueve no sirve para seguir a nadie.

   Se recuerda la primera vez que se ve cada clave y no se reasigna. Se olvida
   al soltar la sesion, que es donde las claves dejan de existir. */
const TINTAS_DE_AUTO = ["--auto-1", "--auto-2", "--auto-3",
                        "--auto-4", "--auto-5", "--auto-6"];
let _tintaPorVehiculo = new Map();

function tintaDeVehiculo(clave) {
  if (!_tintaPorVehiculo.has(clave)) {
    _tintaPorVehiculo.set(
      clave, TINTAS_DE_AUTO[_tintaPorVehiculo.size % TINTAS_DE_AUTO.length]);
  }
  return _tintaPorVehiculo.get(clave);
}

function armarAutos(claves) {
  /* LO QUE LA PARRILLA DECLARA GANA A LO QUE SE PUEDA DEDUCIR.
     La parrilla dice cual es el coche propio ---sale de `player_car_index`, que
     el juego pone en la cabecera de cada paquete--- y esa es la respuesta. Las
     dos lineas de abajo son el respaldo para cuando no lo declara: una captura
     vieja, o la parrilla todavia en viaje.

     Antes eran la unica via, y acertaban por construccion mientras se capturaba
     un vehiculo: el que tenia serie era el unico que habia. Con cuatro pasan a
     ser una eleccion arbitraria, y el 2026-09-10 una sesion corrida con
     Hamilton abrio mostrando a Russell, con el panel de vehiculo en ceros
     porque de un rival el protocolo no publica temperaturas ni presiones. */
  const parrilla = parrillaVigente();
  const declarado = parrilla
    ? (parrilla.vehiculos.find(v => v.es_propio) || {}).vehicle_id
    : null;
  const conTelemetria = estado.vehiculoClave;
  const anterior = AUTOS.find(a => a.propio);
  const propio = (propioAMano && claves.indexOf(propioAMano) !== -1) ? propioAMano
               : (declarado && claves.indexOf(declarado) !== -1) ? declarado
               : (conTelemetria && claves.indexOf(conTelemetria) !== -1) ? conTelemetria
               : (anterior && claves.indexOf(anterior.id) !== -1) ? anterior.id
               : claves[0];
  AUTOS = claves.map((c, i) => Object.assign({
    id: c,
    /* Lo que este vehiculo aporta al tablero ---telemetria o solo posicion---
       no es identidad y tiene su propio campo: mezclarlas era lo que hacia que
       el panel dijera «19 · telemetría completa», dos hechos de distinta
       naturaleza pegados con un punto. */
    aporta: c === propio ? "telemetría completa" : "solo posición en pista",
    tinta: tintaDeVehiculo(c),
    color: "var(" + tintaDeVehiculo(c) + ")",
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
  { id: "steer", rotulo: "Ángulo de dirección", unidad: "°", activa: false, fuentes: ["f1", "can"] },
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
  { id: "steerFraction", rotulo: "Dirección normalizada", unidad: "°", activa: false, fuentes: ["can"] },
  { id: "yaw", rotulo: "Guiñada", unidad: "°/s", activa: false, fuentes: ["f1", "can"] },
  { id: "engineTemp", rotulo: "Temp. motor", unidad: "°C", activa: false, fuentes: ["f1"] },
  { id: "wheelFL", rotulo: "Rueda del. izq.", unidad: "km/h", activa: false, fuentes: ["f1", "can"] },
  { id: "wheelFR", rotulo: "Rueda del. der.", unidad: "km/h", activa: false, fuentes: ["can"] },
  { id: "wheelRL", rotulo: "Rueda tras. izq.", unidad: "km/h", activa: false, fuentes: ["can"] },
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
  { id: "posicion", fuentes: ["f1"] },
  /* LAS COORDENADAS MEDIDAS, PARA PODER UBICAR A CADA VEHICULO DE VERDAD.
     OpenF1 no tiene metro de vuelta, asi que `/posiciones` ---que ubica sobre
     un eje de metros--- contesta 422 con su motivo, y el tablero colocaba a
     cada coche por la **fraccion de tiempo** de la vuelta. Con un piloto eso
     pasaba por bueno; con tres se ve lo que siempre fue: los tres quedan en el
     mismo punto, porque la fraccion es la misma para todos.
     Estas dos son las que dibujan el circuito, y llegan a 3,9 Hz con su
     instante. Son lecturas y no metricas: no se grafican, se leen. */
  /* EL SIMULADOR TAMBIEN LAS NECESITA, y no por el mismo motivo que OpenF1.
     Ahi hacian falta porque esa fuente **no tiene metro de vuelta**. El
     simulador si lo tiene, y por eso estas dos se declararon solo para OpenF1.

     Pero el metro no ubica **antes de la linea de largada**: ahi es negativo y
     la vuelta no empezo ---ver `fraccionDelMetro`---. Sin estas dos series, la
     colocacion se quedaba sin posicion medida y repartia el coche por
     **tiempo** sobre el contorno dibujado, de modo que parecia recorrer tramos
     por los que no paso. La posicion estaba medida; faltaba pedirla. */
  { id: "posX", fuentes: ["f1", "openf1"] },
  { id: "posY", fuentes: ["f1", "openf1"] }
];

/* ============================================================
   LA UNIDAD TAMBIEN CAMBIA CON LA FUENTE
   ------------------------------------------------------------
   `METRICAS` declara la unidad del simulador, donde el acelerador y el freno
   son un porcentaje de recorrido del pedal. En el bus del vehiculo esas dos
   casillas son `gas_pressed` y `brake_pressed`, que son **pisado o no pisado**:
   la base los guarda con unidad `bool`. El panel escribia «%» sobre un booleano
   y ponia «mín 0 · máx 1» debajo, que es un porcentaje imposible.

   El nombre de la senal ya se traducia por fuente ---`nombreDeSenal`--- y la
   unidad no. Se resuelve igual y en un solo sitio, porque son cinco los que la
   escriben: el pie del grafico, los dos rotulos de las laminas, la comparacion
   y su exportacion.
   ============================================================ */
const UNIDAD_POR_FUENTE = {
  can: { throttle: "pisado", brake: "pisado" },
  /* La dirección del simulador es `steering_normalized`, una razón de -1 a 1.
     La del bus es `steer_angle`, en grados. La casilla es la misma y las dos
     unidades no. */
  f1: { steer: "norm." },
};

/* Que decir de una señal que llego y no se movio en todo el tramo visible.
   Un booleano quieto tiene nombre ---el pedal estuvo suelto--- y una magnitud
   quieta no: de esa solo se puede decir su valor. */
function sinCambiosEnElTramo(id, valor) {
  if (unidadDeCanal(id) === "pisado") {
    return valor ? "pisado todo el tramo" : "sin pisadas en este tramo";
  }
  /* `cifra` y no `toFixed`: el resto del tablero escribe los numeros como se
     escriben en el pais ---coma decimal--- y este renglon convive con ellos en
     el mismo pie. Dos separadores distintos en el mismo panel se leen como dos
     magnitudes distintas. */
  return "sin cambios · " + cifra(valor, 2) + " " + unidadDeCanal(id);
}

function unidadDeCanal(id) {
  const porFuente = UNIDAD_POR_FUENTE[fuente];
  if (porFuente && porFuente[id]) return porFuente[id];
  const m = METRICAS.find(x => x.id === id);
  return m ? m.unidad : "";
}

const SENAL_CAN = {
  throttle: "gas_pressed", brake: "brake_pressed", glong: "accel_longitudinal",
  glat: "accel_lateral", steer: "steer_angle", steerRate: "steer_rate",
  steerFraction: "steer_angle_fraction", yaw: "yaw_rate",
  wheelFL: "wheel_speed_front_left", wheelFR: "wheel_speed_front_right",
  wheelRL: "wheel_speed_rear_left", wheelRR: "wheel_speed_rear_right"
};

const SENAL_OPENF1 = { brake: "brake_applied", drs: "drs_state_code",
                       posX: "track_position_x", posY: "track_position_y" };

/* EN EL SIMULADOR EL PLANO DEL CIRCUITO ES `x` Y `z`, NO `x` E `y`: la `y` es
   la altura. Son las dos mismas señales con las que el backend arma el trazado
   ---ver `EJES_POR_FUENTE` en `api_sesion.py`--- y mapear `posY` a
   `world_position_y` dibujaria el desnivel como si fuera una coordenada del
   mapa. */
const SENAL_F1 = { posX: "world_position_x", posY: "world_position_z" };

function nombreDeSenal(id) {
  if (fuente === "can" && SENAL_CAN[id]) return SENAL_CAN[id];
  if (fuente === "openf1" && SENAL_OPENF1[id]) return SENAL_OPENF1[id];
  if (fuente === "f1" && SENAL_F1[id]) return SENAL_F1[id];
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
  current_lap_time: "s",
  /* EL BUS MANDA METROS POR SEGUNDO AL CUADRADO Y EL PANEL DECIA «g».
     El adaptador declara `m/s^2` para `accel_x` y `accel_y` ---es lo que
     publica el vehiculo---, y el tablero rotulaba esas cifras con la unidad de
     la tabla, que es la del simulador. Un tramo de autopista se leia con
     ±0,6 g de aceleracion lateral, que es lo que hace un coche de carrera en
     una curva rapida.

     Comprobado contra la fisica: en un giro plano `a_lat = velocidad x
     velocidad de guiñada`, y la guiñada ya esta validada contra las cuatro
     ruedas. Ajustando lo medido contra lo predicho en seis segmentos con curvas
     ---ciudad, ruta y detenciones--- la pendiente da 9,1, 10,0, 10,0, 10,3, 8,8
     y 5,4 con correlaciones de 0,76 a 0,98. Esa pendiente es la gravedad. */
  accel_longitudinal: "g",
  accel_lateral: "g"
};

/* Por cuanto hay que **dividir** para pasar de la unidad de la izquierda a la
   de la derecha. Un par que no este aca no se convierte con un numero supuesto.

   SE GUARDA COMO DIVISOR Y NO COMO FACTOR, y no es un detalle de estilo:
   `2937 * 0.001` da 2,9370000000000003 en coma flotante binaria y `2937 / 1000`
   da 2,937. La cola aparece en pantalla en cuanto alguien muestre el numero sin
   redondear. */
const DIVISOR_ENTRE_UNIDADES = { "ms|s": 1000, "m/s^2|g": 9.80665 };

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
let PISTA = { path: "", curvas: [], largo_m: null, desnivel_m: null, muestras: null,
          sectores: [], sectoresOrigen: "", puntos: [] };
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
  configurarVentanaDeGraficos();
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
    return (estadoSesion === "vivo" || estadoSesion === "escuchando")
      ? { ruta: "/captura/detener", metodo: "POST", cuerpo: undefined, dejaDeSeguir: true,
          hecho: d => "Captura detenida. " + (d.capturas_cerradas !== undefined
            ? d.capturas_cerradas + " sesiones cerradas" : "Sin sesiones nuevas") }
      // Encender el capturador es el acto explicito que pone a este tablero a
      // seguir el flujo. Sin eso, el objetivo queda sin fijar.
      /* YA NO SE PIDE LA PARRILLA ENTERA.
         Se pedia `parrilla_completa: true`, y eso son 33.250 senales/s medidas
         sobre la carrera de Spa contra las ~9.900 que el consumidor sostiene:
         llegaba el 15 %, y no el 15 % de los rivales sino de todo, tambien del
         coche propio. Ahora se arranca con el coche propio y se agrega a quien
         se quiera desde la lista de arriba, que es lo que el presupuesto
         permite. La eleccion que hubiera quedado de la sesion anterior sigue
         valiendo: no se manda `pilotos`, que borraria lo elegido. */
      : { ruta: "/captura/iniciar", metodo: "POST", cuerpo: {}, sigueVivo: true,
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
      if (a.sigueVivo) {
        vivo.objetivo = null; vivo.aceptaNueva = true; vivo.pedida = true; vivo.otra = null;
        prepararEscucha();
      }
      if (a.dejaDeSeguir) terminarEscucha();
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
        prepararEscucha();
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
  // Escuchando o recibiendo, lo que se ofrece es detener: la captura corre
  // igual, y no poder pararla fue justamente el callejon sin salida.
  acc.textContent = (estadoSesion === "vivo" || estadoSesion === "escuchando")
    ? f.accionVivo : f.accion;
  document.getElementById("btn-limpiar").disabled = estadoSesion === "vacio";
  document.getElementById("btn-comparar").disabled = !sePuedeComparar();
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

/* A QUIEN SE ELIGIO A MANO.
   La parrilla declara quien conduce y eso gana a cualquier deduccion, pero no
   a una eleccion explicita: mirar los datos de un rival es una pregunta
   legitima. Sin esto, `armarAutos` volvia a poner al declarado en cuanto la
   lista se rehacia, y elegir a otro no duraba un cuadro. Se olvida al cambiar
   de sesion, donde la clave ni siquiera existe. */
let propioAMano = null;

/* LOS AVISOS SON DEL PILOTO QUE SE MIRA.
   El pie del panel ya lo decia ---«del piloto, derivados de su telemetría»--- y
   no era cierto: `/avisos` se calculaba siempre sobre quien conduce y se pedia
   una sola vez al abrir. Medido el 2026-09-11 sobre Red Bull Ring con dos
   conductores: con el 19 elegido, los sesenta avisos eran del 18.
   Se piden del piloto elegido y se vuelven a pedir al elegir otro. Una
   respuesta que llega tarde, de un piloto que ya no se mira, se descarta:
   mostrarla le atribuiria a uno los incidentes de otro.
   Solo viaja una clave con forma de vehiculo. Antes de que haya lista de autos
   `autoPropio` devuelve un vehiculo vacio, y entonces no se elige: la API usa a
   quien conduce, que es lo mismo que se hacia antes. */
let _pedidoDeAvisos = 0;

function pedirAvisos(ruta, apertura, senal) {
  const mio = ++_pedidoDeAvisos;
  const quien = autoPropio().id;
  const alcance = sufijoDeCorrida(false);
  const deQuien = (typeof quien === "string" && quien.indexOf(":car:") !== -1)
    ? (alcance ? "&" : "?") + "vehiculo=" + encodeURIComponent(quien) : "";
  conCarga("avisos", () => pedir(ruta + "/avisos" + alcance + deQuien, { senal: senal })
    .then(d => {
      if (!sigueVigente(apertura) || mio !== _pedidoDeAvisos) return;
      ubicarAvisos(d.avisos || []); estado.avisosMotivo = d.motivo_ausencia || "";
      estado.avisosFallo = ""; render();
    })
    .catch(e => {
      if (!sigueVigente(apertura) || mio !== _pedidoDeAvisos) return;
      anotarFalloDeAvisos(e); render();
    }));
}

function elegirPropio(id) {
  const anterior = autoPropio().id;
  propioAMano = id;
  /* Y se cambia de quien se leen las señales, no solo quien figura marcado:
     sin esto el selector decia «Russell» y los instrumentos seguian siendo de
     Hamilton, que es peor que no dejar elegir. */
  estado.vehiculoClave = id;
  AUTOS.forEach(a => { a.propio = (a.id === id); });
  /* Si se estaba mirando solo al propio, se pasa a mirar solo al nuevo: elegir
     piloto es cambiar de quien se mira, no agregar uno. Si habia varios
     seleccionados ---se estaba comparando--- el nuevo se suma sin sacar a
     nadie, porque ahi la seleccion la armo quien mira. */
  if (seleccion.size === 1 && seleccion.has(anterior)) seleccion = new Set([id]);
  else seleccion.add(id);
  olvidarCaches();
  /* Los avisos tambien son de a quien se mira: ver `pedirAvisos`. Mientras
     llegan, el panel queda vacio en vez de seguir mostrando los del anterior. */
  if (estado.abierta && estadoSesion === "cargado" && id !== anterior) {
    estado.avisos = []; estado.avisosFallo = "";
    pedirAvisos("/sesiones/" + encodeURIComponent(estado.abierta.session_id),
                aperturaVigente(), senalDeSesion());
  }
  /* EL VEHICULO TAMBIEN ES DE A QUIEN SE MIRA. El contexto ---vehiculo, clima,
     puesta a punto--- se pedia recien al mover el cabezal, y como mucho una vez
     cada tres segundos: con la reproduccion en pausa, elegir otro piloto dejaba
     el panel mostrando los neumaticos del anterior. Se pide ya, sin esperar el
     plazo, que existe para no repetir consultas y no para postergar esta. */
  if (id !== anterior) { _contextoUltimo = 0; refrescarContexto(); }
  /* Y SUS SERIES, QUE SON DE DONDE LEE EL CRONOMETRAJE.
     Puesto, cronometro y diferencia al lider salen de la serie del piloto que
     se mira. Una vez aprendidos los vehiculos, las series se piden solo del
     elegido, de modo que las del otro no estan: al elegir a Piastri con la
     reproduccion en pausa el panel quedaba en rayas hasta mover el cabezal. Se
     pide ya la vuelta que se esta mirando. Si habia una consulta de esa vuelta
     en camino ---de antes de elegir--- se vuelve a preguntar cuando termine,
     porque la que viajaba no traia a este piloto. */
  if (id !== anterior && estado.abierta && estadoSesion === "cargado") {
    const vuelta = instante().vuelta || 1;
    Promise.resolve(asegurarVuelta(vuelta))
      .then(() => asegurarVuelta(vuelta))
      .catch(() => {});
  }
  render();
}

/* Lo mas corto que sigue distinguiendo a un piloto de otro: su apellido y su
   dorsal. Sin dorsal, el nombre tal cual; es lo que hay. */
function nombreCortoDeVehiculo(a) {
  const partes = String(a.nombre || "").trim().split(/\s+/);
  const corto = partes.length > 1 ? partes[partes.length - 1] : (a.nombre || "");
  return (a.numero === null || a.numero === undefined)
    ? corto : corto + " · #" + a.numero;
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
  /* EL SELECTOR NO REPITE LO QUE EL PANEL YA DICE.
     Llevaba la identidad entera ---«Oscar PIASTRI · #81 · McLaren»--- y el
     panel de cronometraje ya escribe ese mismo nombre completo en su primer
     renglon. En un encabezado angosto, compartido con el titulo, eso se cortaba
     en «· McLa...»: un rotulo truncado de algo que el tablero ya dice entero.
     Va corto: el nombre y el dorsal, que es lo que distingue una opcion de
     otra. La identidad completa queda en el titulo de cada opcion. */
  s.innerHTML = AUTOS.map(a =>
    '<option value="' + textoSeguro(a.id) + '"' + (a.id === actual ? " selected" : "") +
    ' title="' + textoSeguro(a.completa) + '">' +
    textoSeguro(nombreCortoDeVehiculo(a)) + '</option>').join("");
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
      (function () {
        const q = loQueSeSabeDelVehiculo(a, vehiculosConTraza(),
                                         (estado.abierta || {}).senales);
        return '<span class="' + q.clase + '">' + textoSeguro(q.texto) + '</span>';
      })();
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

/* SI LA SESION ABIERTA TRAJO CON QUE LLENAR ESTE PANEL.
   No lo decide una tabla escrita aca: lo decide lo que devolvio la API. Lo que
   el panel declara necesitar se traduce al nombre de **esta** fuente antes de
   buscarlo, porque la misma magnitud se llama distinto en cada una y
   `nombreDeSenal` deja intacto lo que no es un canal del tablero. */
function panelEstaPresente(necesita) {
  return estadoSesion !== "vacio" &&
         estado.disponibles.has(nombreDeSenal(necesita));
}

/* Saca del tablero los paneles que la fuente abierta no puede llenar nunca, y
   con ellos la columna de la cabina que se queda sin nada. La marca es un
   atributo ---igual que la espera y que la ausencia--- y el motivo viaja en el
   titulo, de modo que el hecho sigue disponible para quien inspeccione la
   pagina aunque el panel no este.

   SOLO LAS SECCIONES. Las filas de la tabla del pie llevan el mismo
   `data-panel` a proposito: son el registro que queda cuando el panel se va.
   Esconderlas junto con el panel seria borrar la unica constancia. */
function sacarLosPanelesQueLaFuenteNoLlena() {
  document.querySelectorAll("section[data-panel]").forEach(el => {
    const motivo = porQueLaFuenteNoTieneElPanel(el.dataset.panel);
    if (motivo) { el.dataset.fuera = "si"; el.title = motivo; }
    else if (el.dataset.fuera) { delete el.dataset.fuera; el.removeAttribute("title"); }
  });
  /* Una columna vacia sigue reservando su parte de la rejilla: el hueco se ve
     igual que se veia el panel, y encima sin decir nada. */
  document.querySelectorAll(".col-cabina").forEach(col => {
    const paneles = [...col.querySelectorAll("section[data-panel]")];
    const vacia = paneles.length > 0 && paneles.every(p => p.dataset.fuera === "si");
    if (vacia) col.dataset.fuera = "si"; else delete col.dataset.fuera;
  });
  /* EL SELECTOR DE PILOTO VA DONDE SE VE EL VEHICULO.
     Vive en el encabezado del panel «Vehiculo». Cuando la fuente no muestra ese
     panel ---OpenF1 no publica neumaticos ni daño--- se iria con el la unica
     forma de elegir piloto, y entonces pasa al cronometraje. Se mueve el mismo
     control y no se duplica: dos selectores tendrian que ponerse de acuerdo
     sobre a quien se mira.
     Va aca porque es donde se decide que panel queda fuera: moverlo en otro
     sitio seria volver a decidirlo, y tarde o temprano en desacuerdo. */
  if (typeof document.querySelector === "function") {
    const selector = document.querySelector(".elige-propio");
    const vehiculo = document.querySelector('section[data-panel="vehiculo"]');
    const crono = document.querySelector('section[data-panel="cronometraje"]');
    const panel = (vehiculo && vehiculo.dataset.fuera !== "si") ? vehiculo : crono;
    const cabecera = panel ? panel.querySelector("header") : null;
    if (selector && cabecera && selector.parentElement !== cabecera) {
      cabecera.appendChild(selector);
    }
  }
}

/* Como se llama un panel, tomado de su propio encabezado.
   Escribir los nombres otra vez en una tabla seria tener dos sitios donde el
   panel se llama de alguna manera, y el dia que uno cambie el otro miente. */
function nombreDelPanel(panel) {
  const seccion = document.querySelector('section[data-panel="' + panel + '"]');
  const titulo = seccion ? seccion.querySelector("h2") : null;
  return titulo ? titulo.textContent.trim() : panel;
}

/* LO QUE LA FUENTE NO SOSTIENE, ESCRITO DONDE SE PUEDE LEER.
   Un panel que se saca del tablero deja de poder explicarse solo: el motivo va
   en su titulo, y un panel que no esta no tiene titulo que apuntar. Esta lista
   sale de la **misma** declaracion que lo saca, de modo que lo que se lee aca y
   lo que falta en pantalla no pueden discrepar.

   Con la fuente que lo sostiene todo, el bloque no esta: un cartel que dice
   «nada» ocupa sitio para no decir nada. */
function pintarAusenciasDeclaradas() {
  const bloque = document.getElementById("ausencias-declaradas");
  if (!bloque) return;
  const tabla = PANELES_QUE_LA_FUENTE_NO_TIENE[fuente] || {};
  const paneles = Object.keys(tabla);
  bloque.hidden = paneles.length === 0;
  if (!paneles.length) return;

  const titulo = document.getElementById("titulo-ausencias");
  if (titulo) {
    titulo.textContent = (FUENTES[fuente] ? FUENTES[fuente].nombre : fuente) +
      " no sostiene " + (paneles.length === 1 ? "este instrumento" :
                         "estos " + paneles.length + " instrumentos") +
      ", y por eso no están en pantalla";
  }
  const lista = document.getElementById("lista-ausencias");
  if (!lista) return;
  /* Se arma con nodos y no con una cadena: el motivo es texto, y un texto que
     se concatena dentro de HTML es una via para que deje de serlo. */
  lista.textContent = "";
  paneles.forEach(panel => {
    const fila = document.createElement("div");
    const que = document.createElement("dt");
    que.textContent = nombreDelPanel(panel);
    const porque = document.createElement("dd");
    porque.textContent = tabla[panel];
    fila.appendChild(que);
    fila.appendChild(porque);
    lista.appendChild(fila);
  });
}

function aplicarDisponibilidad() {
  const f = FUENTES[fuente];
  document.querySelectorAll("[data-necesita]").forEach(el => {
    el.dataset.estado = panelEstaPresente(el.dataset.necesita) ? "presente" : "ausente";
  });
  sacarLosPanelesQueLaFuenteNoLlena();
  pintarAusenciasDeclaradas();
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
  /* `motivo-avisos` NO se escribe aca. Lo llena `pintarAvisos`, que es el unico
     que sabe cuantas entradas hay y de donde salen. Estaba en las dos, y esta
     ganaba por correr despues: el panel contaba «5 graves · 13 leves» y el pie
     quedaba vacio, borrado por un `estado.avisosMotivo` que en esta fuente no
     existe. Es el mismo enredo que el clima, que tambien tenia dos escritores
     para el mismo campo, y se arregla igual: un dato, un dueño. */
  // La procedencia va al encabezado, que es donde el resto de los
  // instrumentos la declara, y la explicacion completa al titulo del panel.
  /* Lo que dice el encabezado del trazado es lo que midio **esta** sesion, no
     una cifra escrita: el largo, el desnivel y cuantas muestras hubo detras
     del dibujo salen de la respuesta de la API. */
  const cabPista = document.getElementById("canal-pista");
  const claveEnVivo = estadoSesion === "vivo" ? claveVehiculoPropio() : null;
  cabPista.textContent = queDiceElTrazado(PISTA, {
    hayDistancia: hayEjeDeDistancia(),
    interpolada: _huboInterpolacion,
    estadoSesion,
    fuente,
    posiciones: (claveEnVivo && vivo.recorrido.get(claveEnVivo) || []).length,
  });
  const panelPista = cabPista.closest(".instrumento");
  if (panelPista) panelPista.title = explicacionDelTrazado();
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

/* La velocidad mas alta vista **en lo que se lleva mirado**, por sesion.

   No es el maximo de la sesion entera: es el de lo que ya se mostro, que es lo
   que hace que el numero suba mientras se mira y no que aparezca hecho. Por eso
   se registra al pintar y no se pide a la base.

   Se ata a la sesion para no arrastrar la maxima de una a la siguiente: una
   punta de Monza colgada de una vuelta de Monaco seria una afirmacion falsa
   sobre este coche en esta pista. */
let _maximaVista = { sesion: null, valor: null };

function registrarMaxima(sesion, velocidad) {
  if (_maximaVista.sesion !== (sesion || null)) {
    _maximaVista = { sesion: sesion || null, valor: null };
  }
  if (typeof velocidad === "number" && Number.isFinite(velocidad)
      && (_maximaVista.valor === null || velocidad > _maximaVista.valor)) {
    _maximaVista.valor = velocidad;
  }
  return _maximaVista.valor;
}

/* Como se escribe el valor de un medidor.

   Los continuos llevan una decimal por debajo de diez y entero por encima, que
   es lo que habia. **La marcha no es continua**: es la que el vehiculo tiene
   puesta, y escribir «3,0» sugiere una precision que no existe ---el propio
   tablero razona en otro lado que una marcha no pasa por la 4,5---. El punto
   muerto y la marcha atras tampoco son numeros que quepa promediar, de modo que
   se dicen con su nombre. */
function textoDeMedidor(rotulo, valor) {
  if (valor === null || valor === undefined) return "—";
  if (rotulo === "Marcha") {
    const g = Math.round(valor);
    return g < 0 ? "R" : g === 0 ? "N" : String(g);
  }
  return Math.abs(valor) < 10
    ? Number(valor).toFixed(1).replace(".", ",")
    : String(Math.round(valor));
}

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

  const escrito = textoDeMedidor(rotulo, valor);
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
  const escrito = textoDeMedidor(rotulo, valor);
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

  /* LA MAXIMA SE REGISTRA EN CADA CUADRO, AUNQUE SE DIBUJE MAS ABAJO.
     Es el mayor valor que la velocidad tomo en la sesion, y para saber cual es
     hay que mirar **todos** los cuadros. Va antes de cualquier salida temprana:
     el dibujo de las tiras se saltea cuando nada cambio, y si el registro
     viviera ahi dentro la maxima se perderia justo en los cuadros en que el
     resto del panel no se mueve. */
  const maxima = registrarMaxima(sesionAbierta, t0f.velocidad);

  /* DOS RELOJES, Y EL RESTO EN TIRAS.
     El panel llego a mostrar diez senales, seis de ellas como arcos, y en una
     columna angosta eso deja seis arcos chicos donde no se lee ninguno. Un arco
     sirve para lo que se mira **de reojo mientras se conduce** ---cuanto falta
     para el corte, a que velocidad se va--- porque la posicion de la aguja se
     entiende sin leer. Para todo lo demas lo que se mira es la cifra, y una
     tira de segmentos la da con un cuarto del alto.

     Quedan dos arcos, y por eso son grandes: la rejilla les reparte a dos lo
     que antes repartia a seis. */
  const cuales = [["Régimen", t0f.rpm, 13000, "rpm", frio, tinta("--critico")],
                  ["Velocidad", t0f.velocidad, 360, "km/h", frio, tinta("--alerta")]];

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
  const marcha = textoDeMedidor("Marcha", t0f.marcha);
  const firmaBarras = [fuente, estadoSesion, cifra(t0f.combustibleKg, 1),
                       marcha, cifra(maxima, 0), cifra(t0f.tempMotor, 0),
                       cifra(t0f.ersMJ, 1), t0f.tempFrenoDel,
                       tinta("--acento")].join("|");
  if (firmaBarras === _firmaMedidores) return;
  _firmaMedidores = firmaBarras;

  /* Rotulos cortos: la columna de motor tiene un cuarto del ancho que tenia la
     franja, y un rotulo que se corta no dice nada.

     La marcha lleva ocho segmentos y no diez porque las marchas son ocho: un
     segmento por marcha se lee como una posicion, no como una proporcion. Su
     cifra llega ya escrita ---"R" y "N" no son numeros--- y `barraMedida` no
     encuentra que llenar, que es lo correcto: la marcha atras no es una octava
     parte de nada. */
  const arriba = [barraMedida("Marcha", marcha, 8, "de 8", 8),
                  barraMedida("Máxima", cifra(maxima, 0), 360, "km/h", 10)];
  const abajo = [];
  /* OpenF1 no publica combustible, temperatura de motor, energia ni frenos: esas
     tiras no se dibujan en lugar de mostrar un dato que no existe. El regimen,
     la velocidad y la marcha si los publica, y esos se quedan. */
  if (fuente !== "openf1") {
    arriba.unshift(barraMedida("Combustible", cifra(t0f.combustibleKg, 1), 110, "kg", 10));
    abajo.push(barraMedida("Temp. motor", cifra(t0f.tempMotor, 0), 140, "°C", 10),
               barraMedida("Energía ERS", cifra(t0f.ersMJ, 1), 4, "MJ", 10),
               barraMedida("Freno delantero", cifra(t0f.tempFrenoDel, 0), 1000, "°C", 10));
  }
  const izq = document.getElementById("barras-izq");
  const der = document.getElementById("barras-der");
  if (izq) izq.innerHTML = arriba.join("");
  if (der) der.innerHTML = abajo.join("");
  const canal = document.getElementById("canal-motor");
  if (canal) canal.textContent = "";
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
/* ============================================================
   DOS LISTAS EN UN PANEL, Y CADA ENTRADA DICE DE DONDE SALE
   ------------------------------------------------------------
   `/avisos` declara en su respuesta que cada entrada salio de aplicar una regla
   con un umbral sobre la telemetria, y cuenta cuantas reglas evaluo. Una
   bandera de control de carrera no se derivo de nada: la fuente la declaro. Por
   eso viajan por rutas distintas ---meterlas en la misma dejaria ese criterio
   mintiendo para la mitad de las entradas--- y se juntan recien aca, que es
   donde verlas juntas sirve.

   Lo que no se pierde al juntarlas es de donde sale cada una. `origen` viaja en
   cada entrada y el panel lo escribe: «derivado de la telemetria» o «declarado
   por la fuente». Es la misma distincion que el catalogo de curvas hace entre
   el nombre, que es anotacion, y el metro, que es medicion.
   ============================================================ */
/* La procedencia de un aviso, en una frase. Es lo que distingue una medicion
   con umbral de un hecho que la fuente declaro, y va en el titulo de la entrada
   para que se pueda discutir cada una por lo que es. */
function procedenciaDelAviso(a) {
  if (a && a.origen === "declarado") {
    return "Declarado por la fuente en el control de carrera (" + (a.canal || "") +
           "). No se derivó de la telemetría ni se evaluó ningún umbral.";
  }
  const umbral = (a && a.umbral !== undefined && a.umbral !== null)
    ? " · umbral " + a.umbral : "";
  return "Derivado de la telemetría: canal " + ((a && a.canal) || "") + umbral + ".";
}

function avisosDeLaFuente() {
  const derivados = estado.avisos || [];
  const declarados = estado.controlDeCarrera || [];
  if (!declarados.length) return derivados;
  return derivados.concat(declarados).sort((a, b) => a.en - b.en);
}

/* QUE TAN GRAVE ES UNA BANDERA, Y POR QUE.
   La fuente declara la bandera; que color se le pone en pantalla es una
   decision de presentacion y vive aca, no en el backend, que se limita a
   copiar lo que OpenF1 publica.

   Se escribe con el motivo porque no todas son obvias: la azul no es una
   advertencia de peligro sino una instruccion a un piloto que va a ser doblado,
   y la de cuadros no alerta de nada, cierra la sesion. */
const GRAVEDAD_DE_LA_BANDERA = {
  "RED": { nivel: "critico", porque: "sesion detenida" },
  "DOUBLE YELLOW": { nivel: "critico", porque: "peligro en pista, listo para detenerse" },
  "YELLOW": { nivel: "alerta", porque: "peligro en el sector" },
  "BLUE": { nivel: "info", porque: "aviso a un piloto que va a ser doblado" },
  "GREEN": { nivel: "ok", porque: "pista despejada" },
  "CLEAR": { nivel: "ok", porque: "fin de la condicion anterior" },
  "CHEQUERED": { nivel: "info", porque: "fin de la sesion" },
};

/* Y las categorias que no traen bandera: coche de seguridad y estado de sesion
   tambien son hechos que cambian como se corre. */
const GRAVEDAD_DE_LA_CATEGORIA = {
  "SafetyCar": "alerta",
  "SessionStatus": "info",
  "Drs": "info",
  "Other": "info",
};

function nivelDelControl(evento) {
  const porBandera = GRAVEDAD_DE_LA_BANDERA[(evento && evento.flag) || ""];
  if (porBandera) return porBandera.nivel;
  return GRAVEDAD_DE_LA_CATEGORIA[(evento && evento.category) || ""] || "info";
}

/* En que vuelta del **vehiculo propio** cae un instante.
   No se usa el `lap_number` que trae el control de carrera: esa numeracion es
   de la sesion y arranca antes de la largada ---los primeros eventos de
   Silverstone dicen «vuelta 1» a las 13:19, cuarenta minutos antes de que la
   carrera empiece---. Ubicar un aviso por ese numero lo pondria dentro de la
   ventana de la vuelta 1 del piloto, que es otro momento. */
function vueltaDelInstante(iso) {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return null;
  const vs = estado.vueltas || [];
  for (let i = 0; i < vs.length; i++) {
    const d = Date.parse(vs[i].desde_utc), h = Date.parse(vs[i].hasta_utc);
    if (Number.isFinite(d) && Number.isFinite(h) && t >= d && t <= h) return vs[i].numero;
  }
  return null;
}

/* Un evento de control de carrera con la forma que el panel ya sabe dibujar.
   Lo que no existe no se rellena: un hecho declarado no tiene umbral ni valor
   medido, y escribirle uno seria inventarle un origen. */
function avisoDeControlDeCarrera(evento) {
  const vuelta = vueltaDelInstante(evento.instante);
  const detalle = [evento.flag, evento.scope,
                   evento.sector === null || evento.sector === undefined
                     ? null : "sector " + evento.sector]
    .filter(Boolean).join(" · ");
  return {
    nivel: nivelDelControl(evento),
    que: evento.message || evento.category || "control de carrera",
    detalle: detalle || (evento.category || ""),
    vuelta: vuelta,
    metro: null,
    instante: evento.instante,
    canal: "race_control",
    origen: "declarado",
  };
}

/* Los eventos que caen dentro de alguna vuelta de la sesion. Los de antes de la
   largada ---cuarenta minutos de preparativos en esta carrera--- no tienen
   donde ubicarse en una reproduccion que empieza con la vuelta 1, y ponerlos en
   la fraccion cero seria apilarlos todos en el arranque. */
function avisosDelControlDeCarrera(eventos) {
  return (eventos || [])
    .map(avisoDeControlDeCarrera)
    .filter(a => a.vuelta !== null);
}

/* UNA CONSULTA QUE NO CONTESTO NO ES UNA SESION SIN INCIDENTES.
   Medido el 2026-09-11 sobre una practica de 4.140.744 filas, `/avisos` en
   frio tardo 76,0 / 73,4 / 72,6 s. El cliente corta a los 30 s y el corte
   llega como `TiempoAgotado`, que no es `AbortError` ni `TypeError`: el
   `catch` de la carga solo anotaba los `TypeError`, y el fallo se perdia sin
   consola, sin motivo y sin marca. `estado.avisos` quedaba vacio y el panel
   escribia que no habia ocurrido nada sobre una sesion con veinticuatro
   avisos, cuatro de ellos alertas.
   Un panel vacio se lee como un panel vacio. Un panel que **afirma** que no
   hubo incidentes tranquiliza: el fallo se disfraza de hallazgo. */
function anotarFalloDeAvisos(e) {
  /* Cancelar a proposito no es fallar: cerrar la sesion aborta esta consulta
     igual que las demas, y no hay nada que declarar sobre una sesion que ya
     no se esta mirando. */
  if (fueAnulada(e)) return;
  estado.avisosFallo = (e && e.message) || "la consulta de avisos no volvió";
  console.error("avisos:", e);
}

/* Lo mismo con los avisos: la lista solo cambia cuando llega uno nuevo. */
let _firmaAvisos = "";
let _cuantosAvisos = 0;

/* DONDE CAE UN METRO DENTRO DE LA VUELTA, O `null` SI NO CAE.

   UN METRO NEGATIVO NO ES UN DATO FALTANTE NI ES EL METRO CERO. El protocolo
   publica `lap_distance` **negativa antes de cruzar la linea de largada**
   ---`backend/f1_udp.py:462`---, y con eso esta diciendo algo cierto: el coche
   esta antes de la linea. Lo que no puede hacer es ubicarlo **dentro de la
   vuelta**, porque la vuelta todavia no empezo.

   QUE PASABA. La colocacion preguntaba `!== undefined`, que un negativo
   cumple, y recortaba con `Math.max(0, metro / largo)`: fraccion cero
   constante hasta que el metro se volvia positivo. En la reproduccion el coche
   quedaba clavado en la meta los primeros segundos.

   Y LO PEOR NO ERA QUE NO SE MOVIERA: quedaba marcado como medido, sin
   `data-estimada`, de modo que el tablero **afirmaba una posicion medida que
   era un recorte**. El comentario que esta unas lineas mas abajo, en la
   colocacion, declara la regla que ese recorte rompia: una posicion supuesta y
   una medida no pueden verse igual.

   Medido sobre `f1_25:session:16227589096132074312` el 2026-09-12: la sesion
   arranca en el metro -5.342,3.

   LOS DOS EXTREMOS NO SON SIMETRICOS. Pasarse unos metros de la linea si se
   recorta a uno: ahi el coche esta sobre el circuito y el sobrante es ruido de
   medicion. Quedarse corto no, porque antes de la linea no hay circuito
   recorrido que mostrar. */
function fraccionDelMetro(metro, largoVuelta) {
  if (typeof metro !== "number" || !isFinite(metro) || metro < 0) return null;
  if (typeof largoVuelta !== "number" || !isFinite(largoVuelta) ||
      largoVuelta <= 0) return null;
  return Math.min(1, metro / largoVuelta);
}

/* EL AVISO SE MUESTRA CON MAYUSCULA INICIAL, Y SE CAPITALIZA **AL MOSTRARLO**.

   POR QUE NO EN EL BACKEND, QUE ERA LO OBVIO. Los textos los arma
   `backend/anotador_vivo.py`, y ahi hay una trampa: en `:629` el titulo se usa
   como **clave de agrupamiento comparada por tupla exacta**
   ---`clave == ("fuera de pista",)`---. Cambiar el literal apagaria en
   silencio la logica que distingue una salida con agarre de una sin el. No es
   texto de presentacion: es parte de una decision. Ademas `api_sesion.py:4001`
   promete que la reproduccion usa «los mismos textos que el flujo vivo», de
   modo que tocar uno solo de los dos caminos violaria esa promesa escrita.

   Aca abajo es presentacion y nada mas: nadie compara contra esto.

   SOLO LA PRIMERA LETRA. El control de carrera declara «DRS ENABLED» y
   «CAR 87 (BEA) TIME 2:00.293 DELETED» en mayuscula entera; bajar el resto
   seria reescribir lo que la fuente dijo. Y lo que no empieza con letra queda
   igual. */
function conMayusculaInicial(texto) {
  const t = (texto === null || texto === undefined) ? "" : String(texto);
  if (!t) return t;
  return t.charAt(0).toLocaleUpperCase("es-AR") + t.slice(1);
}

/* COMO SE ROTULA EL MOMENTO DE UN AVISO.

   Decidia con `hayVueltas() && a.vuelta`, y `hayVueltas()` mira
   `estado.vueltas`, que **en vivo esta vacio** porque las vueltas se arman al
   guardar la sesion. De modo que el mismo aviso decia «Vuelta 5» en
   reproduccion y «Tramo» en vivo: dos rotulos para un solo hecho.

   Lo decide el aviso. El anotador le escribe su `lap_number` cuando la fuente
   lo publica; un bus vehicular no tiene vueltas y sus avisos vienen sin ella,
   asi que siguen diciendo «Tramo» sin preguntarle nada a `estado`. Un dato,
   un dueño.

   El cero se compara aparte a proposito: `a.vuelta ? ...` lo leeria como
   ausencia, y un cero dicho por la fuente es un dato. */
function rotuloDeCuando(aviso) {
  const v = aviso ? aviso.vuelta : null;
  return (v === null || v === undefined || v === "") ? "Tramo" : "Vuelta " + v;
}

/* CUANDO OCURRIO UN AVISO, EN MILISEGUNDOS MEDIDOS, O NULL.

   El instante ya venia en el dato y el camino vivo lo descartaba. El anotador
   escribe `reloj_s` en cada anotacion y es epoca Unix de verdad ---`_segundos`
   la obtiene con `.timestamp()`---; la reproduccion la convierte a `instante`.
   En vivo se recibia y solo se usaba para armar un identificador. */
function cuandoOcurrio(aviso) {
  if (!aviso || !aviso.instante) return null;
  const t = Date.parse(aviso.instante);
  return Number.isFinite(t) ? t : null;
}

/* EL ORDEN DE LA LISTA DE AVISOS: EL MAS NUEVO ARRIBA, POR LOS DOS CAMINOS.

   QUE PASABA. En vivo todos los avisos entraban con `en: 1`, que es una
   constante y no una medicion. Ordenar por `en` con todos empatados deja el
   orden de insercion ---`sort` es estable--- o sea **el mas viejo arriba**. Y
   la insignia «NUEVO» es `i === 0`, no «no leido». El primer aviso de la
   sesion se quedaba arriba rotulado NUEVO para siempre.

   En reproduccion el mismo dato se ordenaba bien. Las dos listas mostraban los
   dos extremos de la misma coleccion: misma cuenta y contenido opuesto.

   POR QUE NO SE MEZCLAN LAS DOS UNIDADES. Un milisegundo de epoca y una
   fraccion de sesion entre cero y uno no son comparables. Devolver el que
   tenga instante como «mas grande» pondria cualquier aviso con instante por
   encima de todos los demas: una diferencia de unidad disfrazada de orden. Por
   eso el instante decide **solo cuando los dos lo tienen**, y si no se cae en
   la fraccion, que es lo que la reproduccion ya usaba. */
function masNuevoPrimero(a, b) {
  const ta = cuandoOcurrio(a), tb = cuandoOcurrio(b);
  if (ta !== null && tb !== null && ta !== tb) return tb - ta;
  return (b.en || 0) - (a.en || 0);
}

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
  const avisos = todos.filter(a => a.en <= hasta).sort(masNuevoPrimero);
  const firma = [fuente, estadoSesion, avisos.length, todos.length,
                 estado.avisosFallo, tinta("--acento")].join("|");
  if (firma === _firmaAvisos) return;
  // Solo se anuncia el que **acaba de llegar**: si la lista se acorto es
  // porque se rebobino, y entonces no hay nada nuevo que anunciar.
  const recienLlego = avisos.length > _cuantosAvisos;
  _firmaAvisos = firma;
  _cuantosAvisos = avisos.length;
  /* EL MOTIVO LO ESCRIBE LA API, NO UNA TABLA POR FUENTE.
     Aca habia dos frases escritas a mano y la de OpenF1 era falsa: decia que
     esa fuente no publica banderas cuando publica ochenta y nueve en esta
     sesion. El texto salia de lo que contesta `/avisos`, que decide por fuente
     ---`if fuente != "f1_25_udp_simulation"`--- y da el mismo motivo para el
     bus, donde si es cierto. Se usa el que la respuesta declare.
     Y si la respuesta no declaro ninguno, no se escribe ninguno: el respaldo
     que puse primero ---«esta fuente no declara incidentes que se puedan
     anotar»--- aparecia sobre la simulacion, que declara veinticuatro, cada vez
     que `/avisos` todavia no habia contestado. El cuerpo ya dice lo unico
     cierto en ese momento, que es que hasta aca no ocurrio nada. */
  const motivo = estado.avisosMotivo || "";

  /* El orden importa: mientras la consulta no haya vuelto, lo unico cierto es
     que no se sabe. Preguntar primero por la lista vacia haria que el panel
     contestara «no ocurrio nada» justamente cuando no tiene con que. */
  if (estado.avisosFallo && !todos.length) {
    cont.innerHTML = '<p class="nota sin-avisos">No se pudieron traer los avisos ' +
      'de esta sesión: ' + textoSeguro(estado.avisosFallo) + '. No quiere decir ' +
      'que no haya ocurrido nada; quiere decir que todavía no se sabe.</p>';
    document.getElementById("canal-avisos").textContent = "sin respuesta";
    document.getElementById("motivo-avisos").textContent =
      "La consulta de avisos recorre la sesión entera y en una captura larga " +
      "puede no llegar a contestar.";
    return;
  }

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
      '<span class="cuando"><b>' + rotuloDeCuando(a) + '</b>' +
        (a.metro ? Math.round(a.metro).toLocaleString("es-AR") + " m" : "") + '</span>' +
      '<span class="marca"></span>' +
      /* ESCAPADO, ADEMAS DE CAPITALIZADO. Este campo puede traer `message` del
         control de carrera de OpenF1 ---texto de una fuente externa--- y se
         insertaba crudo en la pagina, a diferencia del detalle de la linea de
         abajo, que si pasaba por `textoSeguro`. */
      '<span class="que">' + textoSeguro(conMayusculaInicial(a.que)) + '</span>' +
      // El nombre del canal sale del renglon visible y queda en el titulo:
      // sigue disponible para quien lo necesite, sin competir con el aviso.
      // El detalle es el valor medido contra su umbral: es lo que sostiene el
      // aviso, y el canal queda en el titulo para quien quiera discutirlo.
      /* DE DONDE SALE ESTE AVISO, Y ES LA MITAD DE LO QUE AFIRMA.
         Uno derivado de la telemetria se sostiene en un valor contra un umbral,
         y ese umbral se puede discutir. Uno declarado por el control de carrera
         no tiene umbral ni valor medido: lo afirmo la fuente. Escribirle un
         umbral inventado, o presentarlos sin distinguir, seria darle a los dos
         el respaldo de uno solo. */
      '<span class="canal" title="' + textoSeguro(procedenciaDelAviso(a)) + '">' +
        textoSeguro(a.detalle || (cifra(a.valor, 1) + ' ' + (a.unidad || "") +
        (a.umbral !== undefined && a.umbral !== null ? ' · umbral ' + a.umbral : ''))) +
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
  /* EL MOTIVO EXPLICA UNA AUSENCIA, ASI QUE NO VA DEBAJO DE UNA LISTA.
     Con la lista llena, escribir «esta fuente no declara incidentes» debajo de
     cinco graves y trece leves seria contradecir lo que esta justo arriba. Lo
     que corresponde decir aca es de donde salen: el panel mezcla lo derivado de
     la telemetria con lo que la fuente declaro, y el recuento no lo distingue. */
  const declarados = avisos.filter(a => a.origen === "declarado").length;
  const derivados = avisos.length - declarados;
  /* Y DE QUIEN SON, QUE NO ES LO MISMO PARA LOS DOS.
     Los derivados de la telemetria son del piloto que se mira: salen de sus
     señales y cambian al cambiar de piloto. Los declarados en el control de
     carrera son de la sesion ---banderas, coche de seguridad, estado de
     pista--- y no cambian con el piloto, lo cual se ve como que el panel no
     reacciona. Medido sobre la carrera cargada: de 158 eventos, **157 no
     nombran piloto**; el unico que lo hace es una bandera azul para el coche 31.
     Decirlo evita que la quietud del panel se lea como un fallo. */
  document.getElementById("motivo-avisos").textContent =
    (declarados && derivados)
      ? derivados + " del piloto, derivados de su telemetría · " + declarados +
        " de la carrera, declarados por la fuente"
      : declarados ? "De la carrera, no del piloto: declarados por la fuente en " +
                     "el control de carrera"
      : "";
}

/* ---------------- aceleraciones ---------------- */
/* El clima deja de ser cuatro celdas iguales: la temperatura del aire manda,
   con su icono, y el resto acompana. */
let _firmaClima = "";

/* El clima es el que la fuente publico en la sesion: temperatura de aire y
   de pista, codigo de clima y bandera. No hay humedad ni viento porque el
   paquete de sesion no los trae; se muestran los que hay. */
/* ============================================================
   EL PANEL DE CLIMA MUESTRA LO QUE LA FUENTE TRAE, NO CUATRO CASILLAS FIJAS
   ------------------------------------------------------------
   Eran cuatro escritas a mano ---pista, aire, bandera y coche de seguridad---
   porque el simulador publica esas cuatro. OpenF1 publica otras: temperatura de
   aire y de pista tambien, y ademas humedad, presion, viento y si llueve; y no
   publica ni bandera de sesion ni retraso del coche de seguridad.

   Con la lista fija, abrir OpenF1 daba dos casillas con una raya ---afirmando
   que no se sabe algo que la fuente no publica--- y escondia cuatro magnitudes
   que si estaban medidas.

   QUE DECIDE QUE CASILLA VA. Que la respuesta **traiga la clave**, no que el
   valor no sea nulo. Son dos cosas distintas y el tablero se apoya en la
   diferencia en todos lados: una clave presente con valor nulo es «esto existe
   en esta fuente y ahora no se sabe», y se dibuja con su raya; una clave que no
   viene es «esta fuente no lo publica», y entonces no hay casilla que dibujar.
   Asi no hace falta una tabla por fuente: cada respuesta declara lo suyo. */
const CASILLAS_DEL_CLIMA = [
  ["temperatura_pista_c", "Pista", "°C", 1],
  ["temperatura_aire_c", "Aire", "°C", 1],
  ["bandera_texto", "Bandera", "", null],
  ["retraso_del_coche_de_seguridad_s", "Coche de seg.", "s", 1],
  ["lluvia", "Lluvia", "", null],
  ["humedad_pct", "Humedad", "%", 0],
  ["viento_m_s", "Viento", "m/s", 1],
  ["presion_mbar", "Presión", "mbar", 1],
];

function celdasDelClima(d) {
  if (!d) return [];
  return CASILLAS_DEL_CLIMA
    .filter(c => Object.prototype.hasOwnProperty.call(d, c[0]))
    .map(([clave, rotulo, unidad, decimales]) => {
      const v = d[clave];
      /* Un booleano no es una cifra: «llueve» y «no llueve» son los dos un
         dato, y `0` no es ninguno de los dos. */
      if (typeof v === "boolean") return [rotulo, v ? "sí" : "no"];
      /* Sin valor, la raya sola. «— °C» se lee como «no se cuantos grados»,
         y eso dice de mas: lo que no se sabe es el dato, no su unidad. */
      if (v === null || v === undefined) return [rotulo, "—"];
      if (decimales === null) return [rotulo, String(v)];
      return [rotulo, cifra(v, decimales) + (unidad ? " " + unidad : "")];
    });
}

/* DE DONDE SALE EL CLIMA QUE SE DIBUJA.
   Son dos consultas distintas y llegan cuando llegan: `/contexto` trae el clima
   que viaja **en la telemetria** de la sesion, y `context-at` el que la fuente
   declara **aparte**, en su propia tabla. Las dos escribian `estado.clima`, de
   modo que la que contestaba ultima borraba a la otra: sobre OpenF1 el clima
   aparecia y desaparecia segun cual ganara la carrera, y perdia siempre la
   unica que lo tenia.

   No se ordenan las respuestas: se guardan en campos distintos y la eleccion se
   hace al dibujar. El de la telemetria manda cuando existe ---es el de la
   sesion abierta, muestra a muestra--- y el declarado es el respaldo. */
function climaQueSeMuestra() {
  return estado.clima || estado.climaDeCarrera || null;
}

function pintarClima() {
  const c = document.getElementById("clima");
  if (!c) return;
  const d = climaQueSeMuestra();
  if (!d) { c.innerHTML = ""; c.removeAttribute("title"); return; }
  /* Si las temperaturas o el cielo salieron de la procedencia de la captura y
     no de la telemetria, se dice en el titulo del panel: es un valor para toda
     la sesion y no cambia con el cabezal. */
  if (d.procedencia_nota) c.title = d.procedencia_nota;
  else c.removeAttribute("title");

  const iconos = {
    "despejado": "sol", "nubes ligeras": "nube", "cubierto": "nube",
    "lluvia ligera": "lluvia", "lluvia fuerte": "lluvia", "tormenta": "lluvia"
  };
  /* El dibujo sale de un campo y no de la prosa. Con `iconos[d.clima]` el icono
     dependia de que la frase coincidiera con una clave escrita aca, de modo que
     una fuente que dice «llueve» con otras palabras caia en la nube por defecto
     teniendo el dato. */
  const cual = d.icono || iconos[d.clima] || "nube";
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

  const fClima = comoSeVe(d.frescura || "current", d.edad_s);

  const banderas = { "ninguna": "ok", "verde": "ok", "amarilla": "alerta",
                     "roja": "critico", "azul": "info" };
  const bandera = d.bandera_texto || "ninguna";
  /* La chapa de la bandera solo va donde la fuente declara una. */
  const chapa = Object.prototype.hasOwnProperty.call(d, "bandera_texto")
    ? '<span class="bandera ' + (banderas[bandera] || "ok") + '">' + bandera + '</span>'
    : "";

  c.innerHTML =
    '<div class="clima-principal">' + dibujo +
      '<div><span class="cifra-grande">' + cifra(d.temperatura_aire_c, 1) + '</span>' +
      '<span class="unidad-grande">°C</span>' +
      '<p class="eyebrow">' + textoSeguro(d.clima || "sin declarar") + '</p></div>' +
      chapa +
    '</div>' +
    '<dl class="clima-rejilla">' +
      celdasDelClima(d).map(f => '<div><dt>' + textoSeguro(f[0]) + '</dt><dd>' +
        textoSeguro(f[1]).replace(/ /g, "&nbsp;") + '</dd></div>').join("") +
    '</dl>' +
    /* DE CUANDO ES ESTE CLIMA. La respuesta lo trae resuelto en
       `weather_freshness` desde que se conecto `context-at`, y hasta ahora el
       tablero lo guardaba y no lo leia: el dato llegaba resuelto y se tiraba.

       Se dice una vez para todo el panel, no en cada casilla: las siete
       magnitudes vienen de la **misma** muestra de clima, asi que todas tienen
       la misma edad y repetirla siete veces seria decir siete veces lo mismo. */
    (fClima.sufijo || fClima.aclara
      ? '<p class="frescura-panel" data-frescura="' + fClima.estado + '">' +
        textoSeguro(fClima.aclara || fClima.sufijo) + '</p>'
      : "");
}

/* LOS TRES RENGLONES DEL PANEL DE ACELERACIONES, CON EL NOMBRE DE LA SEÑAL QUE
   LLENA CADA UNO EN ESTA FUENTE.

   En el simulador son las tres aceleraciones. En el bus, que no tiene
   acelerometro vertical, el tercero es la velocidad de guiñada ---y se nombra
   `yaw_rate`, que es como la publica---.

   EL DEFECTO QUE ESTO CUIDA. Ese tercer renglon decia `yaw_rate` y leia
   `gVert`, que sale de `g_force_vertical`: una señal que solo publica el
   simulador. En el bus la casilla nunca se llenaba, de modo que el renglon
   mostraba una raya sobre una sesion que trae la guiñada completa. Decia el
   nombre correcto y traia el valor de otra cosa, que es la unica combinacion
   que no se nota mirando. */
function renglonesDelPanelG(t) {
  const g = v => (v === null || v === undefined) ? "—"
    : (v >= 0 ? "+" : "") + Number(v).toFixed(2).replace(".", ",") + " g";
  if (fuente === "f1") {
    return [["g_force_longitudinal", g(t.gLong)], ["g_force_lateral", g(t.gLat)],
            ["g_force_vertical", g(t.gVert)]];
  }
  const guinada = (t.yaw === null || t.yaw === undefined) ? "—"
    : Number(t.yaw).toFixed(1).replace(".", ",") + " °/s";
  return [["accel_longitudinal", g(t.gLong)], ["accel_lateral", g(t.gLat)],
          ["yaw_rate", guinada]];
}

function pintarG() {
  const tres = fuente === "f1";
  const t = instante();
  const cs = renglonesDelPanelG(t);
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
  /* Cuanto vale el borde. Sin esto la escala se estira sola y no se declara:
     el mismo dibujo para 0,06 g y para 5. */
  const rotuloEscala = document.getElementById("escala-g");
  if (rotuloEscala) rotuloEscala.textContent = cifra(huella.maximo, 2) + " g";
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
/* QUE TAN LEJOS SE PUEDE CONTRASTAR UNA FORMA DERIVADA, Y DICHO.
   ============================================================
   El recorrido del bus es una integracion, y una integracion no se comprueba
   sola: acumula lo que le den. Pero hay una comprobacion, y es fuerte.

   En una curva las ruedas de afuera recorren mas que las de adentro, y esa
   diferencia dividida por la velocidad de guiñada da el **ancho de via** del
   vehiculo. Es geometria pura, sin ningun supuesto sobre el neumatico. Y ese
   numero **no viaja en el bus**: nadie transmite el ancho de via. Que dos
   señales decodificadas por separado ---la guiñada y las cuatro ruedas---
   coincidan en una dimension fisica del vehiculo es lo mas fuerte que se puede
   afirmar sobre un decodificado.

   El punto de acceso ya la calculaba y la mandaba en cada respuesta. No la leia
   nadie: el resultado principal de esta fuente vivia en un campo que la
   pantalla nunca abria.

   CUANDO NO SE PUEDE AFIRMAR, SE DICE. La comprobacion descarta las muestras
   por debajo de un giro minimo, de modo que un tramo recto no deja con que
   medir: `sample_01` da cero muestras, y eso no es una falla sino la ausencia
   de evidencia, que hay que declarar y no esconder. Y con un puñado de
   muestras una correlacion de 1,00 no significa nada ---`sample_28` da 1,00
   con siete---, asi que por debajo del minimo se dice que no alcanza en vez de
   presentar un numero que no se sostiene.
   ============================================================ */

/* Cuantas muestras hacen falta para que el ajuste diga algo. Con siete, una
   correlacion de 1,00 es una recta entre dos nubes de puntos que casi no se
   mueven; con cincuenta ya hay curvas de verdad detras. */
const MUESTRAS_PARA_CONTRASTAR = 50;

/* Por debajo de esta correlacion las dos señales no estan describiendo lo
   mismo, y el ancho de via que sale del ajuste no es una medida del vehiculo. */
const CORRELACION_QUE_CONVENCE = 0.8;

function textoDeLaValidacion(v) {
  if (!v) return "";
  const n = v.muestras || 0;
  if (n < MUESTRAS_PARA_CONTRASTAR) {
    return n
      ? "pocas curvas en este tramo para contrastarlo con las ruedas"
      : "sin curvas en este tramo: nada con que contrastar la forma";
  }
  const ancho = v.ancho_de_via_m, r = v.correlacion;
  if (!Number.isFinite(ancho) || !Number.isFinite(r)) return "";
  const medida = cifra(ancho, 2) + " m de vía · r " + cifra(r, 2) +
                 " sobre " + cifra(n, 0) + " muestras";
  return r >= CORRELACION_QUE_CONVENCE
    ? "guiñada y ruedas coinciden en " + medida
    : "guiñada y ruedas no coinciden: " + medida;
}

/* Cuantos puntos dibuja la estela. Ochenta sobre un circulo de ciento treinta y
   seis unidades de diametro es algo mas de uno cada dos: por debajo se ven los
   escalones y por encima el trazo se vuelve una mancha. */
const PUNTOS_DE_LA_ESTELA = 80;

/* LA HUELLA DE LA VUELTA, SIN PERDER SUS EXTREMOS.
   Un diagrama de aceleraciones **es** su envolvente: lo que dice es cuanto se
   empujo al vehiculo y en que direcciones. Tomar una muestra de cada tantas
   tiraba justo los picos, que son lo unico que ese dibujo tiene para contar.
   Medido sobre los siete tramos del bus, la estela perdia entre el 9 y el 32 %
   del extremo; en `sample_27` eso bajaba la escala de 0,30 a 0,20 g y el punto
   del instante quedaba **sujeto al borde**, mostrando pegado al limite un valor
   que no estaba en el limite.

   De cada tramo se conserva el punto mas lejano del centro. Es una muestra
   medida, no un promedio ni una interpolacion: se elige por el modulo porque
   las dos componentes son un solo vector y su extremo es un instante real de la
   vuelta. La objecion que impide elegir por valor en las series ---que cada
   fila trae varias señales y el extremo de una no es el de las otras--- no
   aplica aca, donde las dos son la misma medicion.

   Y LA ESCALA SE MIDE SOBRE TODO, NO SOBRE LO DIBUJADO. Aunque la estela
   conserve los extremos, el borde del diagrama se declara con la vuelta
   entera: es lo que ese numero dice que es. */
function _estelaG(vuelta) {
  const longitudinal = serieDeCanal("glong", vuelta, claveVehiculoPropio()) || [];
  const lateral = serieDeCanal("glat", vuelta, claveVehiculoPropio()) || [];
  const n = Math.min(longitudinal.length, lateral.length);
  if (!n) return { puntos: [[90, 90]], maximo: PASOS_DE_LA_ESCALA_G[0] };
  const valores = [];
  const paso = Math.max(1, Math.ceil(n / PUNTOS_DE_LA_ESTELA));
  let tope = 0;
  for (let i = 0; i < n; i += paso) {
    let extremo = null, lejos = -1;
    for (let k = i; k < Math.min(i + paso, n); k++) {
      const x = Number(lateral[k][1]), y = Number(longitudinal[k][1]);
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
      if (Math.abs(x) > tope) tope = Math.abs(x);
      if (Math.abs(y) > tope) tope = Math.abs(y);
      const d = x * x + y * y;
      if (d > lejos) { lejos = d; extremo = [x, y]; }
    }
    if (extremo) valores.push(extremo);
  }
  if (!valores.length) return { puntos: [[90, 90]], maximo: PASOS_DE_LA_ESCALA_G[0] };
  const maximo = escalaDelDiagramaG(tope);
  /* Se devuelve tambien la escala: el punto del instante se coloca con las
     aceleraciones interpoladas y tiene que caer en el mismo dibujo que la
     estela, no en uno normalizado aparte. */
  return {
    puntos: valores.map(p => [90 + (p[0] / maximo) * 68, 90 - (p[1] / maximo) * 68]),
    maximo: maximo,
  };
}

/* HASTA DONDE LLEGA EL DIAGRAMA, Y ESCRITO.
   El borde valia `max(1, lo mas grande de la vuelta)`. Ese piso de 1 g es del
   simulador ---un coche de carrera pasa de 4--- y sobre un coche de calle deja
   la nube en un punto: en autopista la lateral no llega a 0,07 g. Y sin piso,
   una escala que se estira sola miente por omision: el dibujo se ve igual con
   0,06 g que con 5, porque no dice cuanto vale el borde.

   Dos cosas, entonces. La escala sube por pasos redondos, para que dos vueltas
   parecidas se dibujen a la misma escala y se puedan comparar de un vistazo. Y
   el valor del borde se escribe, que es lo que convierte el dibujo en una
   medicion. */
const PASOS_DE_LA_ESCALA_G = [0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1, 1.5, 2, 3, 4, 5, 6];

function escalaDelDiagramaG(maximo) {
  if (!Number.isFinite(maximo) || maximo <= 0) return PASOS_DE_LA_ESCALA_G[0];
  for (let i = 0; i < PASOS_DE_LA_ESCALA_G.length; i++) {
    if (maximo <= PASOS_DE_LA_ESCALA_G[i]) return PASOS_DE_LA_ESCALA_G[i];
  }
  return Math.ceil(maximo);
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

/* DONDE ESTUVO UN VEHICULO EN UN INSTANTE, SEGUN SUS COORDENADAS MEDIDAS.
   Las dos series llegan con su propio instante y se interpolan igual que
   cualquier continua: entre dos muestras separadas 0,26 s, el punto del medio
   es el punto del medio. No se extrapola ni se sostiene: sin las dos
   coordenadas no hay posicion, y quien llama se entera y coloca por tiempo,
   declarandolo.

   La proyeccion es **la misma** que dibujo el circuito. Usar otra pondria al
   coche fuera de su propio trazo. */
function puntoMedidoDe(clave, tUtcMs) {
  if (!PISTA.proyectarMundo || tUtcMs === null || tUtcMs === undefined) return null;
  const vuelta = instante().vuelta;
  const sx = serieTemporal("posX", vuelta, clave);
  const sy = serieTemporal("posY", vuelta, clave);
  if (!sx || !sy) return null;
  const x = valorContinuoEn(sx, tUtcMs);
  const y = valorContinuoEn(sy, tUtcMs);
  if (x === null || y === null) return null;
  const q = PISTA.proyectarMundo(x, y);
  return { x: q[0], y: q[1] };
}

/* ---------------- trazado real ---------------- */
function pintarPista() {
  const linea = document.getElementById("linea-pista");
  linea.setAttribute("d", PISTA.path);
  pintarValidacionDeLaForma();
  pintarElectorDelRecorrido();
  pintarTrazaPorSenal(linea);

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
  /* LAS RAYAS DE SECTOR VAN ANTES QUE LAS CURVAS.
     Se dibujan primero para que queden **debajo**: una raya cruza el trazo de
     lado a lado y taparia el numero de una curva que cayera cerca. El numero
     es lo que se consulta; la raya es contexto. */
  if (rehacer && PISTA.sectores && PISTA.sectores.length > 1) {
    const NS = "http://www.w3.org/2000/svg";
    marcasDeSector(PISTA.sectores, PISTA.puntos, PISTA.proyectarMundo).forEach(m => {
      const raya = document.createElementNS(NS, "line");
      raya.setAttribute("class", "raya-sector");
      raya.setAttribute("x1", m.x1); raya.setAttribute("y1", m.y1);
      raya.setAttribute("x2", m.x2); raya.setAttribute("y2", m.y2);
      const cual = document.createElementNS(NS, "title");
      cual.textContent = "Empieza el sector " + m.sector +
        (m.desde_m !== null && m.desde_m !== undefined ? " · metro " + cifra(m.desde_m, 0) : "");
      raya.appendChild(cual);
      g.appendChild(raya);
      const rot = document.createElementNS(NS, "text");
      rot.setAttribute("class", "rotulo-sector");
      rot.setAttribute("x", m.tx); rot.setAttribute("y", m.ty);
      rot.textContent = "S" + m.sector;
      g.appendChild(rot);
    });
  }

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
      /* MAS CHICO QUE ANTES. Con radio 6 y cuerpo 7 sobre un lienzo de 360 por
         170, quince numeros ocupaban mas superficie que el propio circuito: en
         el panel ampliado de la cabina se veian como pastillas y la forma del
         trazado quedaba detras de ellas. El blanco de puntero se conserva
         grande ---radio 11--- porque apuntar no tiene por que ser mas dificil
         solo porque la marca se achico. */
      p.setAttribute("cx", z.xy[0]); p.setAttribute("cy", z.xy[1]); p.setAttribute("r", "4.2");
      p.style.fill = tinta("--superficie"); p.style.stroke = tinta("--linea-fuerte");
      p.style.strokeWidth = "1.2";
      marca.appendChild(p);

      const r = document.createElementNS(NS, "text");
      r.setAttribute("x", z.xy[0]); r.setAttribute("y", z.xy[1] + 2.6);
      r.setAttribute("text-anchor", "middle");
      r.setAttribute("font-size", "5"); r.setAttribute("font-weight", "600");
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
  /* SOBRE LA PISTA VA QUIEN ESTA ELEGIDO, Y NO TODO EL QUE PUBLIQUE POSICION.
     Antes se dibujaban todos: la seleccion decidia de quien se grafican las
     señales y la pista mostraba el resto igual. Con un solo vehiculo capturado
     las dos listas eran la misma y la diferencia no existia. Desde que se
     escucha a varios pilotos si existe, y entonces el trazado contradice al
     resto del tablero: cuatro marcas moviendose mientras los graficos, el
     cronometraje y el vehiculo hablan de uno.

     El coche propio se dibuja aunque no este elegido, porque es de quien se
     estan mirando las señales y una pista sin el no ubica nada. */
  const enPista = posicionesAhora();
  const todosEnPista = enPista ? Object.keys(enPista) : [...seleccion];
  const propioEnPista = claveVehiculoPropio();
  let claves = todosEnPista.filter(
    id => seleccion.has(id) || id === propioEnPista);
  /* Sin nada que mostrar se cae a lo que haya, que es preferible a una pista
     vacia: puede no haberse elegido todavia. */
  if (!claves.length) claves = todosEnPista;
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
    /* El metro ubica al coche solo si cae dentro de la vuelta. Un negativo
       ---antes de la linea--- no es el metro cero: ver `fraccionDelMetro`. */
    const fracDelMetro = enPistaAhora
      ? fraccionDelMetro(enPistaAhora[clave], largoVuelta) : null;
    let medida = fracDelMetro !== null;
    let medidaDeVerdad = false;
    if (medida) frac = fracDelMetro;
    /* MIENTRAS SE MIDE EL RECORRIDO, EL COCHE VA POR SU POSICION.
       El camino dibujado se rehace cada veinticinco puntos ---rehacerlo en cada
       uno recalcula la orientacion de la nube y el dibujo salta---, pero la
       posicion del vehiculo es un dato que llega veinte veces por segundo y no
       tiene por que esperar al dibujo. Se la proyecta con la misma
       transformacion del camino vigente. */
    let p = null;
    if (PISTA.proyectarMundo && (PISTA.enConstruccion || PISTA.medidoEnVivo)) {
      const ult = vivo.posicionMundo.get(clave);
      if (ult) {
        const q = PISTA.proyectarMundo(ult[0], ult[1]);
        p = { x: q[0], y: q[1] };
      }
    }
    /* SOBRE UN RECORRIDO DERIVADO, EL COCHE VA POR SU INSTANTE.
       `frac` es una fraccion de tiempo y el camino esta parametrizado por
       longitud: las dos coinciden solo con velocidad constante. En este tramo
       casi lo es, que es lo que haria pasar el error por bueno. */
    if (!p && PISTA.derivado) {
      const q = puntoDelBusEn(instante().tUtcMs);
      if (q) p = q;
    }
    /* SOBRE UN CIRCUITO MEDIDO, CADA UNO VA DONDE SE LO MIDIO.
       Es lo mismo que hace el bus con su recorrido reconstruido, pero con
       coordenadas que la fuente publica en vez de integradas. Y es lo unico que
       separa a tres vehiculos: la fraccion de vuelta es la misma para los tres,
       de modo que sin esto los tres se dibujan en el mismo punto. */
    if (!p) {
      const q = puntoMedidoDe(clave, instante().tUtcMs);
      if (q) { p = q; medidaDeVerdad = true; }
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
    /* Se declara **despues** de colocarlo: hasta aca no se sabia si la
       coordenada medida estaba disponible para este instante. */
    const seUbicoMidiendo = medida || medidaDeVerdad;
    if (grupo.dataset.estimada !== (seUbicoMidiendo ? "no" : "si")) {
      grupo.dataset.estimada = seUbicoMidiendo ? "no" : "si";
      grupo.setAttribute("aria-label",
        seUbicoMidiendo ? "" : "posición estimada por tiempo, no medida");
    }
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
function globoDeCurvas(panel, globo) {
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
}
/* Los dos trazados tienen su globo. El del panel chico existe desde siempre; el
   de la vista grande hace falta por el mismo motivo, que no es el espacio sino
   que quince nombres escritos tapan la forma del circuito. */
globoDeCurvas(document.querySelector(".pista .cuerpo-instrumento"),
              document.getElementById("globo-curva"));
globoDeCurvas(document.querySelector("#velo-trazado .panel-comparacion"),
              document.getElementById("globo-curva-grande"));

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
/* CUANTO MAS DE LO POSIBLE SE TOLERA ANTES DE LLAMARLO SALTO.
   Medido sobre `f1_25:session:16227589096132074312` el 2026-09-12: el mayor
   movimiento real de la sesion fue de 10,72 m, y con la velocidad declarada el
   maximo posible era 10,73 m. El movimiento real **roza su cota**, asi que el
   margen no esta para acomodar el movimiento: esta para el desfase entre la
   muestra de posicion y la de velocidad, que no son el mismo paquete. */
const MARGEN_DE_MOVIMIENTO = 1.5;

/* Y un piso, porque al soltar el freno la velocidad previa es cero y el coche
   igual se mueve unos centimetros. Sin esto, cada arranque cortaria el
   trazado. */
const PISO_DE_MOVIMIENTO_M = 1.0;

/* Si el vehiculo pudo haber recorrido esa distancia en ese tiempo.

   POR QUE EXISTE. En una contrarreloj de Shanghai, al empezar la vuelta lanzada
   el simulador **teletransporta el coche** a la linea. El recorrido en vivo se
   acumula como una sola polilinea, asi que el tablero dibujo un segmento recto
   cruzando el circuito entre el sitio donde estaba y el sitio donde aparecio:
   afirmaba un camino que nadie recorrio.

   NO ES UNA REGLA DEL MODO. Lo primero que se penso fue «en contrarreloj no
   dibujes eso». Pero un salto ocurre igual con un `flashback` o con un
   reinicio en boxes, en cualquier modo, y en contrarreloj el resto del
   recorrido es tan real como en una carrera. Lo que separa un salto de un
   movimiento no es el modo: es que **el vehiculo publica su propia velocidad**
   y con ella declara cuanto pudo haberse movido.

   Medido: el salto fue de 479,3 m en 0,094 s con el coche declarando 0,0 km/h
   ---maximo posible, 0,00 m---. Los otros 4.590 saltos de la sesion tuvieron
   mediana 4,96 m y maximo 10,72 m.

   ANTE LA DUDA SE DIBUJA. Sin velocidad declarada o sin tiempo entre muestras
   no se puede acotar nada, y cortar ante la duda desarmaria el trazado de
   cualquier fuente que no publique velocidad. No poder decidir no es lo mismo
   que haber decidido. */
function pudoRecorrer(saltoM, dtS, kmhAntes, kmhDespues) {
  if (!(dtS > 0)) return true;
  const a = (kmhAntes === null || kmhAntes === undefined) ? null : Number(kmhAntes);
  const b = (kmhDespues === null || kmhDespues === undefined) ? null : Number(kmhDespues);
  if (a === null && b === null) return true;
  /* La mayor de las dos, y no la previa. En el salto medido la previa era cero
     ---el coche estaba detenido--- y tomarla cortaria tambien cada arranque.
     Con la mayor el salto se rechaza igual, por treinta y cuatro veces. */
  const kmh = Math.max(a === null ? 0 : a, b === null ? 0 : b);
  if (!isFinite(kmh)) return true;
  return saltoM <= (kmh / 3.6) * dtS * MARGEN_DE_MOVIMIENTO + PISO_DE_MOVIMIENTO_M;
}

/* MARCA LOS PUNTOS DE UNA SESION GUARDADA DONDE EL CAMINO SE CORTA.

   POR QUE HIZO FALTA UNA SEGUNDA VEZ. El primer arreglo cubrio el camino **en
   vivo**, donde el tablero acumula las posiciones a medida que llegan. Una
   sesion guardada dibuja lo que devuelve `/trazado`, y ahi el salto seguia
   entero: medido el 2026-09-12 sobre `f1_25:session:16227589096132074312`,
   **476 m entre dos puntos vecinos**, con una mediana de 12 m. Se veia como una
   recta cruzando el circuito, y como la reproduccion ubica al coche **sobre el
   camino dibujado**, el coche la recorria toda al cerrar la vuelta.

   LA REGLA ES LA MISMA Y VIVE EN UN SOLO SITIO. El punto de acceso no decide:
   entrega `dt_s` y `velocidad_kmh` por punto, y `pudoRecorrer` ---la misma
   funcion que usa el camino vivo--- resuelve. Escribir la fisica de nuevo en
   Python habria dado dos implementaciones de una sola cosa, que es el defecto
   que este sistema ya tuvo cuatro veces.

   NO SE ESCRIBE SOBRE LO QUE LLEGO. Los puntos son el dato medido y se copian
   antes de marcarlos; y si los arreglos no vienen alineados no se marca nada,
   porque marcar por indice desplazado cortaria el circuito en un sitio donde el
   coche si paso ---un defecto peor que el que se arregla. */
function marcarSaltos(puntos, dtS, velocidadKmh) {
  if (!Array.isArray(puntos) || !puntos.length) return puntos || [];
  if (!Array.isArray(dtS) || !Array.isArray(velocidadKmh) ||
      dtS.length !== puntos.length || velocidadKmh.length !== puntos.length) {
    return puntos;
  }
  return puntos.map((p, i) => {
    if (i === 0) return p;
    const salto = Math.hypot(p[0] - puntos[i - 1][0], p[1] - puntos[i - 1][1]);
    return pudoRecorrer(salto, dtS[i], velocidadKmh[i - 1], velocidadKmh[i])
      ? p : [p[0], p[1], true];
  });
}

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

  /* Un tercer elemento en el punto lo marca como comienzo de figura nueva. El
     punto **no se borra**: la posicion se midio y sigue siendo cierta. Lo que
     se deja de afirmar es el camino entre ella y la anterior. Ver
     `pudoRecorrer`. */
  const d = giro.map((p, i) => {
    const q = proyectar(p);
    return (i === 0 || puntos[i][2] ? "M" : "L")
           + q[0].toFixed(1) + " " + q[1].toFixed(1);
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
    /* La llave lleva la **revision** y no el largo: el largo se clava en el
       tope de la ventana movil y deja de distinguir un contenido de otro. */
    return divisor === 1 ? cruda
         : _enUnidad(cruda, divisor,
                     "vivo|" + (clave || "") + "|" + senal + "|" +
                     (cruda.rev || cruda.length));
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
  /* Cada bloque declara su eje. CAN y OpenF1 historico usan segundos desde el
     inicio del tramo; F1 25 conserva metros. No se guarda tiempo bajo un nombre
     de distancia para reutilizar el dibujante. */
  const xs = veh.distancia_m || veh.tiempo_s;
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

/* La vista convertida de una serie viva, memorizada por su **revision**.
   Sin esto se armaria una copia por canal y por cuadro.

   Decia «memorizada por su largo, porque el arreglo solo crece». Era cierto
   hasta las seiscientas muestras; desde ahi cada una nueva saca la mas vieja y
   el largo se queda quieto mientras el contenido cambia. La revision cuenta lo
   que entro, que es lo que distingue un contenido de otro. */
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

/* Y LA ABSCISA DE LA FUENTE QUE NO MIDE DISTANCIA, QUE ES EL RELOJ DEL TRAMO.
   `_armarSerieDeCanal` ya declara la regla: la abscisa de un bloque es
   `distancia_m` **o** `tiempo_s`, lo que la fuente traiga. Contra el tiempo esa
   segunda mitad no se podia leer ---solo existia la clave de la distancia--- y
   quien necesitaba la abscisa en un instante cualquiera no tenia de donde
   sacarla mas que de una muestra. Ahora las dos se leen igual. */
const EJE_TIEMPO = " tiempo";

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
  const divisor = (canal === EJE_DISTANCIA || canal === EJE_DISTANCIA_SESION ||
                   canal === EJE_TIEMPO)
    ? 1 : divisorDePresentacion(canal, vuelta, clave);
  if (divisor === null) return null;

  const cache = _cacheTemporal();
  const llave = vuelta + "|" + clave + "|" + canal;
  if (cache.has(llave)) return cache.get(llave);

  const ys = canal === EJE_DISTANCIA ? veh.distancia_m
           : canal === EJE_DISTANCIA_SESION ? veh.distancia_sesion_m
           : canal === EJE_TIEMPO ? veh.tiempo_s
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
   LA ABSCISA DE PRESENTACION SALE DEL RELOJ, NO DE LA MUESTRA MAS CERCANA
   ------------------------------------------------------------
   Es la que corre la ventana movil de los graficos y la que coloca el cabezal.
   Sobre una fuente con distancia medida ya se resolvia asi ---interpolando
   `distancia_m` entre las dos muestras que rodean el instante--- y por eso la
   ventana se desliza.

   Sobre una fuente **sin** distancia no habia de donde sacarla y se caia en
   `serie[Math.round(fraccion * (n - 1))][0]`, que es la abscisa de una muestra
   concreta: la ventana no avanzaba con el reloj sino a los saltos de la
   muestra, y con ella todo lo que se dibuja dentro.

   CUANTO SALTABA. OpenF1 de Silverstone 2025, vuelta 1 pedida como tramo
   propio: 401 muestras en 106,1 s, o sea una cada **0,265 s** de mediana. A 1x
   eso son menos de cuatro avances por segundo sobre una pantalla que entrega
   sesenta, y se ve: los graficos se mueven a tirones mientras los medidores
   ---que si leen por interpolacion--- cambian en continuo. Dos relojes para el
   mismo instante, otra vez.

   La regla de que abscisa usar no se escribe aca de nuevo: es la que ya declara
   `_armarSerieDeCanal`, distancia si la hay y reloj del tramo si no. Se lee la
   misma, contra el mismo instante compartido.
   ============================================================ */
function abscisaContinua(vuelta, clave, tUtc) {
  if (tUtc === null || tUtc === undefined) return null;
  const distancia = serieTemporal(EJE_DISTANCIA, vuelta, clave);
  if (distancia) return valorContinuoEn(distancia, tUtc, true);
  const reloj = serieTemporal(EJE_TIEMPO, vuelta, clave);
  return reloj ? valorContinuoEn(reloj, tUtc, true) : null;
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

/* Si el catalogo declara mas vehiculos con telemetria de los que el tablero
   conoce. Se compara contra lo que la sesion declara y no contra un numero
   escrito aca: cuantos hay depende de que se haya cargado, no de la fuente. */
function faltanVehiculosPorAprender() {
  const declarados = Number((estado.abierta || {}).vehiculos);
  if (!Number.isFinite(declarados) || declarados <= 1) return false;
  return AUTOS.length < declarados;
}

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

/* EL TRAMO DE UNA VUELTA, PARA PEDIR SOLO ESO.
   Sin acotar, `/series-tiempo` reparte los puntos pedidos sobre la sesion
   entera: en una carrera de dos horas y media, mil doscientos puntos son una
   muestra cada 7,8 segundos, y una ventana de veinte segundos se dibuja con dos
   o tres. Acotando a la vuelta, los mismos puntos caen sobre noventa segundos y
   sobra resolucion.

   Vacio cuando la vuelta no declara sus dos instantes: entonces se pide como
   antes, que es la sesion entera, y es mejor que pedir un tramo inventado. */
function tramoDeLaVuelta(numero) {
  const v = estado.vueltas.find(x => x.numero === numero);
  if (!v || !v.desde_utc || !v.hasta_utc) return "";
  return "desde=" + encodeURIComponent(v.desde_utc) +
         "&hasta=" + encodeURIComponent(v.hasta_utc);
}

/* Pide una vuelta si no esta y no se esta pidiendo ya. */
function asegurarVuelta(numero, puntos, deFondo) {
  const temporal = !hayEjeDeDistancia();
  /* UNA FUENTE SIN METRO MEDIDO YA PUEDE TENER VARIAS VUELTAS.
     Esto rechazaba cualquier vuelta que no fuera la 1 porque, sin distancia,
     `/vueltas` contestaba la lista vacia y el tablero armaba un tramo unico.
     OpenF1 declara sus vueltas por reloj ---cincuenta y dos, con su instante y
     su duracion--- y ahi la restriccion dejaba cincuenta y una sin poder
     pedirse. Lo que decide es si esa vuelta existe, no de que fuente viene. */
  if (!estado.abierta || numero < 1 ||
      (temporal && !estado.vueltas.some(v => v.numero === numero)) ||
      !alcanceResuelto()) {
    return Promise.resolve(null);
  }
  const quiere = puntos || (temporal ? 1200 : PUNTOS_POR_VUELTA);
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
  /* La API espacial admite doce señales por consulta. La temporal admite las
     veinte necesarias para mantener en una sola respuesta el eje comun de
     canales CAN que se publican con frecuencias distintas. */
  const todas = senalesCandidatas();
  const maximoPorTanda = temporal ? 20 : 12;
  const tandas = [];
  for (let i = 0; i < todas.length; i += maximoPorTanda) {
    tandas.push(todas.slice(i, i + maximoPorTanda));
  }

  /* EL VEHICULO DEL QUE HAY TELEMETRIA VA SIEMPRE.
     `seleccion` dice a quien dibujar sobre el trazado, y ahi entran vehiculos
     de los que la fuente publica **posicion y nada mas**. Usarla tal cual para
     pedir las series hacia que el tablero pidiera las señales de un vehiculo
     que no las tiene: la API contestaba con la lista vacia, correctamente, y
     los cuatro graficos quedaban diciendo «sin dato» sobre una vuelta que si
     estaba en la base.

     Se pide siempre por el vehiculo del que hay serie. Si todavia no se sabe
     cual es, no se acota y la API los devuelve todos, que es como se aprende.

     Y TAMPOCO SE ACOTA MIENTRAS FALTE APRENDER QUIENES SON LOS DEMAS. Esa
     regla solo miraba si se conocia **el propio**, y en OpenF1 se conoce desde
     el principio: `/vueltas` declara el vehiculo mas muestreado. De modo que la
     primera consulta ya salia acotada a ese uno y las otras dos nunca
     aparecian: la sesion tiene telemetria de tres pilotos ---310.881, 310.881 y
     310.863 filas--- y el tablero mostraba uno solo, sin forma de elegir a los
     otros, porque para ofrecerlos en la lista primero hay que saber que
     existen.

     El catalogo declara cuantos son ---tres en esta sesion, uno en el bus y uno
     en la simulacion, donde los rivales viajan por `/posiciones` y no por
     telemetria---. Mientras lo aprendido sea menos que lo declarado, la
     consulta no se acota y la respuesta ensena el resto. Es una sola vez por
     sesion: con la primera vuelta ya estan los tres. */
  const propio = estado.vehiculoClave;
  const conPropio = (estado.series[numero] ? faltantes : pedidos).slice();
  if (propio && conPropio.indexOf(propio) === -1) conPropio.push(propio);
  const autos = (propio && !faltanVehiculosPorAprender()) ? conPropio : [];
  const apertura = aperturaVigente();
  const base = "/sesiones/" + encodeURIComponent(estado.abierta.session_id) +
               (temporal ? "/series-tiempo?" + tramoDeLaVuelta(numero)
                         : "/series?vuelta=" + numero + "&") +
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
            if (["distancia_m", "distancia_sesion_m", "tiempo_s", "timestamp_utc"].indexOf(c) === -1) {
              d.vehiculos[k][c] = p.vehiculos[k][c];
            }
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

/* La precarga se decide por tiempo de pared, que es el plazo real antes de que
   el reproductor necesite la vuelta. A 10x, dos vueltas de cien segundos estan
   a diez y veinte segundos; esperar a entrar en cada una deja muy poco margen
   ante una consulta lenta. Siempre se trae la siguiente y, dentro del horizonte,
   las adicionales se encadenan para no ocupar todas las conexiones juntas. */
const HORIZONTE_PRECARGA_S = 20;
function vueltasParaPrecargar(numero) {
  const lista = estado.vueltas || [];
  const indice = lista.findIndex(v => v.numero === numero);
  if (indice === -1 || indice + 1 >= lista.length) return [];
  const rapidez = Math.max(1, velocidadRep || 1);
  const duracionActual = duracionDeVuelta(numero);
  let hastaElInicio = duracionActual > 0 ? duracionActual / rapidez : Infinity;
  const resultado = [];
  for (let i = indice + 1; i < lista.length; i++) {
    if (resultado.length && hastaElInicio > HORIZONTE_PRECARGA_S) break;
    resultado.push(lista[i].numero);
    const duracion = duracionDeVuelta(lista[i].numero);
    hastaElInicio = duracion > 0 ? hastaElInicio + duracion / rapidez : Infinity;
  }
  return resultado;
}

function precargarVueltas(numero, apertura) {
  let cola = Promise.resolve();
  vueltasParaPrecargar(numero).forEach(siguiente => {
    cola = cola.then(() => {
      if (!sigueVigente(apertura)) return null;
      const series = asegurarVuelta(siguiente, undefined, true);
      asegurarPosiciones(siguiente, true);
      return series || null;
    });
  });
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
  decirEstadoApi(hayVueltas() ? "Preparando la vuelta " + v + "…"
                              : "Preparando el tramo temporal…", false);
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
    /* UN COCHE DEL QUE YA NO HAY DATO NO SE DIBUJA DONDE ESTUVO.
       Sin `b` no hay con que interpolar: o el instante cayo despues de la
       ultima muestra, o ese vehiculo dejo de publicar. Devolver la ultima
       posicion conocida deja su marca clavada en la pista mientras los demas
       corren, y eso se lee como «esta ahi», que es falso.

       Paso el 2026-09-10: un piloto elegido y desmarcado a los pocos segundos
       quedo con veintinueve muestras de un solo segundo, y su marca se quedo
       quieta las tres vueltas. Se muestra mientras el instante siga cerca de su
       ultima medida ---un segundo, que a veinte hercios son veinte muestras---
       y despues se deja de dibujar: no saber donde esta es preferible a
       afirmar que sigue ahi. */
    if (!b) {
      const VENCE_MS = 1000;
      if (relativo !== null && a[0] !== undefined && relativo - a[0] > VENCE_MS) return;
      salida[clave] = a[1];
      return;
    }

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
    if (["distancia_m", "distancia_sesion_m", "tiempo_s", "timestamp_utc"].indexOf(nombre) !== -1) return;
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
        "steerFraction", "yaw", "wheelFL", "wheelFR", "wheelRL", "wheelRR"]
};

/* QUE VIENE ENCENDIDO Y QUE NO.
   El panel ofrece **todas** las señales graficables que la fuente tenga
   ---diecinueve en la simulacion, trece en el bus--- y arranca con las señales
   que mejor resumen cada fuente. Encender una mas agrega su grafico a la cabina;
   apagarla lo saca. Antes el panel ofrecia solo esas cuatro y las quince
   restantes vivian nada mas que en la vista de detalle, que es esconder lo
   que la fuente entrega detras de un boton.

   LA ELECCION ES DE CADA FUENTE, NO GLOBAL.
   Con un solo conjunto compartido, pasar de la simulacion al bus arrastraba
   lo que estuviera encendido alla: como `speed` y `brake` existen en las dos,
   el bus abria con esas dos y sin las suyas propias ---aceleracion
   longitudinal y direccion---, que son justamente las que lo distinguen. Cada
   fuente recuerda su propia seleccion inicial. */
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
   principal de carrera muestra las cuatro que se miran siempre y llena una fila.
   CAN aprovecha la cabina temporal completa con ocho señales en dos filas. El
   resto vive en la vista de detalle, a un boton de distancia.

   Se usan filas completas de cuatro para mantener la jerarquia visual. */
const PRINCIPALES_POR_FUENTE = {
  f1: ["speed", "throttle", "brake", "rpm"],
  openf1: ["speed", "throttle", "brake", "rpm"],
  can: ["speed", "throttle", "glong", "steer",
        "brake", "glat", "steerRate", "yaw"]
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
  ctx.fillText((m.rotulo + " · " + unidadDeCanal(m.id)).toUpperCase(), 0, 0);
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
  const paleta = TINTAS_DE_AUTO;
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
    ctx.strokeStyle = tinta(tintaDeVehiculo(ids[ai]) || paleta[ai % paleta.length]);
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
    ctx.fillStyle = tinta(tintaDeVehiculo(id) || paleta[i % paleta.length]);
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
  const paleta = TINTAS_DE_AUTO;

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
    ctx.fillText((m.rotulo + " · " + unidadDeCanal(m.id)).toUpperCase(), 0, 0);
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
      ctx.strokeStyle = tinta(tintaDeVehiculo(ids[ai]) || paleta[ai % paleta.length]);
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
    ctx.fillStyle = tinta(tintaDeVehiculo(id) || paleta[i % paleta.length]);
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
          '<canvas id="lienzo-' + id + '" role="img" aria-label="' + m.rotulo +
            (hayEjeDeDistancia() ? ' a lo largo de la vuelta' : ' a lo largo del tiempo') + '"></canvas>' +
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
  const paleta = TINTAS_DE_AUTO;
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
      datos = datos.map(d => d.map(p => [p[0], p[1] > 0 ? 1 : 0]));
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
        return binario ? t.map(x => x.map(p => [p[0], p[1] > 0 ? 1 : 0])) : t;
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
          return binario ? junto.map(p => [p[0], p[1] > 0 ? 1 : 0]) : junto;
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
    if (hayEjeDeDistancia() && CURVAS.length) {
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
    _ejeTraza[canal] = {
      ini: vIni, fin: vFin, acumulado: conAcumulada,
      unidad: hayEjeDeDistancia() ? "m" : "s",
    };

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
      ctx.strokeStyle = tinta(tintaDeVehiculo(ids[ai]) || paleta[ai % paleta.length]);
      ctx.lineWidth = ids.length > 2 ? 1.2 : 1.7;
      ctx.lineJoin = "round";
      ctx.stroke();
    });

    const dec = (canal === "glong" || canal === "glat" || canal === "gvert" ||
                 canal === "gap" || canal === "slip" || canal === "steer") ? 2 : 0;
    const pie = document.getElementById("pie-" + canal);
    if (pie) {
      /* UNA RAYA PLANA NO DICE SI ESTA ROTA O SI NO PASO NADA.
         Con el simulador daba igual: el acelerador de una vuelta de carrera se
         mueve siempre. Con el bus del vehiculo no: medio conjunto de datos son
         tramos de autopista con el crucero puesto, donde el acelerador y el
         freno estan sueltos el minuto entero y su traza es una recta en cero.
         Vista sola es indistinguible de un canal muerto, y son dos cosas muy
         distintas: una es un dato y la otra es una falla.

         Se dice cuando la señal llego y no cambio, que es lo unico que se puede
         afirmar. Que no haya llegado ya se dice en otro lado ---el lienzo
         escribe «sin dato»--- y no se pisan. */
      const quieta = Number.isFinite(escala.minReal) &&
                     escala.minReal === escala.maxReal;
      pie.innerHTML = quieta
        ? '<span class="quieta">' +
            textoSeguro(sinCambiosEnElTramo(canal, escala.minReal)) + "</span>"
        : '<span>mín <b>' + escala.minReal.toFixed(dec) + '</b></span>' +
          '<span>' + textoSeguro(unidadDeCanal(canal)) + '</span>' +
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
    ctx.fillText(estado.cargando ? "cargando…"
                 : hayEjeDeDistancia() ? "sin dato en esta vuelta" : "sin dato en este tramo",
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
  /* La leyenda lleva el color **del vehiculo**, no el del lugar que ocupa en la
     seleccion: es la misma que se ve en los graficos y en el trazado, y si no
     coincidieran la leyenda diria lo contrario que el dibujo que explica. */
  const elegidos = [...seleccion]
    .map(id => AUTOS.find(a => a.id === id))
    .filter(Boolean);
  const nombres = elegidos.map(a => a.nombre);
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
    elegidos.map(a => '<span><i style="background:' + a.color + '"></i>' +
      textoSeguro(a.nombre) + '</span>').join("");
  const bin = fuente === "can";
  const notaT = document.getElementById("nota-traza");
  if (notaT) notaT.textContent = bin
    ? "El eje horizontal es tiempo desde el inicio de la captura. El acelerador y el freno son binarios: gas_pressed y brake_pressed declaran pisado o no pisado, no cuánto."
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
  /* LO QUE HACE FALTA PARA COMPARAR SON DOS VEHICULOS, NO UNA FUENTE.
     Decia `fuente !== "f1"` y avisaba «requiere al menos dos vehiculos F1 25
     con distancia medida», que a esta altura es falso dos veces: la vista
     dibuja contra el reloj desde que existe el eje temporal, y OpenF1 trae tres
     pilotos con telemetria. Era la tercera copia de la misma guarda por fuente
     ---el boton, esta, y la que pedia los datos--- y las tres decidian sobre la
     procedencia en vez de sobre el dato. */
  if (seleccion.size < 2) {
    avisar("Comparar necesita al menos dos vehículos con telemetría. " +
           "Esta sesión trae uno.", true);
    return;
  }
  document.getElementById("velo-comparacion").dataset.abierto = "si";
  /* Y el titulo dice el eje que se esta usando, no el del simulador. */
  document.querySelector("#velo-comparacion .cab-comparacion h3").firstChild.textContent =
    ejeVigente() === "distancia" ? "Comparación por distancia"
                                 : "Comparación contra el reloj";
  pintarElectorDelEje(); pintarMetricas(); pintarPilotosComparacion(); dibujarComparacion();
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
    m.rotulo + " · " + unidadDeCanal(m.id);
  pintarElectorDelEje(); pintarMetricas(); pintarPilotosComparacion(); dibujarComparacion();
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
  pintarElectorDelEje(); pintarMetricas(); pintarPilotosComparacion(); dibujarComparacion();
  document.getElementById("btn-cerrar-comparacion").focus();
}
document.getElementById("btn-cerrar-comparacion").addEventListener("click", () => {
  document.getElementById("velo-comparacion").dataset.abierto = "no";
});
(function engancharTrazadoGrande() {
  const abrir = document.getElementById("btn-ampliar-trazado");
  if (abrir) abrir.addEventListener("click", () => {
    pintarEligePilotosDelTrazado();
    abrirTrazadoGrande();
  });
  const cerrar = document.getElementById("btn-cerrar-trazado");
  if (cerrar) cerrar.addEventListener("click", () => {
    const v = document.getElementById("velo-trazado");
    if (v) v.dataset.abierto = "no";
  });
})();
document.addEventListener("keydown", e => {
  if (e.key === "Escape") {
    document.getElementById("velo-comparacion").dataset.abierto = "no";
    const s = document.getElementById("velo-sesiones");
    if (s) s.dataset.abierto = "no";
    const tz = document.getElementById("velo-trazado");
    if (tz) tz.dataset.abierto = "no";
    cerrarModal();
  }
});
document.getElementById("sel-eje").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  ejeComparacion = b.dataset.eje; marcar(e.currentTarget, "eje", ejeVigente()); dibujarComparacion();
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

/* EL EJE QUE LA FUENTE NO TIENE SE OFRECE DECLARADO, NO MUDO.
   El boton de distancia seguia ahi, encendido, sobre una fuente sin metro
   medido: se lo apagaba al apretarlo, con un cartel. Ahora se ve apagado de
   entrada y el motivo esta en su titulo, que es donde el resto del tablero
   pone los porques. */
function pintarElectorDelEje() {
  const c = document.getElementById("sel-eje");
  if (!c) return;
  const hay = hayEjeDeDistancia();
  const b = c.querySelector('[data-eje="distancia"]');
  if (b) {
    b.disabled = !hay;
    b.title = hay ? "" : "Sin distancia medida: " + porQueNoHayDistancia();
  }
  marcar(c, "eje", ejeVigente());
}

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

/* ============================================================
   A QUIEN ESCUCHAR, MIENTRAS SE ESCUCHA
   ------------------------------------------------------------
   No es el mismo selector que el de comparar. Aquel elige a quien **mirar**
   entre lo que ya se capturo; este elige a quien **capturar**, y por eso
   cuesta: cada vehiculo agregado son 1.511 senales/s mas que tienen que
   atravesar el intermediario, el consumidor y la base.

   Por que aparece recien cuando se esta escuchando: los nombres llegan en el
   paquete de participantes, unos segundos despues de que la sesion arranca en
   el juego. Antes de eso no hay lista que ofrecer, y ofrecer una inventada
   seria peor que no ofrecer ninguna.

   El coche propio no es un boton. Va siempre, porque es el unico del que el
   protocolo entrega los datos completos, y un boton que no se puede apagar
   promete una decision que no existe.
   ============================================================ */

/* El color con que cada equipo se reconoce sin leer el nombre.
   No sale del juego: el protocolo entrega el identificador de equipo y su
   nombre, no su color. Se declara aca, con los del campeonato 2025, y quien no
   este ---un equipo personalizado, los genericos--- cae en el color neutro en
   vez de en uno inventado. */
const COLORES_DE_EQUIPO = {
  "Mercedes": "#00d7b6", "Ferrari": "#e8002d", "Red Bull Racing": "#3671c6",
  "Williams": "#64c4ff", "Aston Martin": "#229971", "Alpine": "#ff87bc",
  "RB": "#6692ff", "Haas": "#b6babd", "McLaren": "#ff8000",
  "Sauber": "#52e252",
};

function colorDeEquipo(equipo) {
  return COLORES_DE_EQUIPO[equipo] || "var(--linea-fuerte)";
}

let escuchados = null;      // los nombres elegidos, o `null` mientras no se leyo
let topeEscucha = 6;
let pidiendoEscuchados = false;

/* SE PIDE UNA VEZ, NO UNA POR DIBUJO.
   `pintarEligeEscucha` la llama cuando todavia no se leyo la eleccion, y a
   `render` lo llama el flujo en vivo varias veces por segundo: sin este
   candado, cada cuadro lanzaba otra peticion mientras la anterior seguia en
   vuelo. Decenas de GET por segundo para leer un archivo que no cambia. */
function leerEscuchados() {
  if (pidiendoEscuchados) return;
  pidiendoEscuchados = true;
  pedir("/captura/pilotos").then(d => {
    escuchados = (d && Array.isArray(d.pilotos)) ? d.pilotos : [];
    if (d && typeof d.maximo === "number") topeEscucha = d.maximo;
    pintarEligeEscucha();
  }).catch(() => { escuchados = []; })
    .then(() => { pidiendoEscuchados = false; });
}

/* SI ESTA SESION TIENE A ALGUIEN MAS A QUIEN ESCUCHAR.

   QUE PASABA. El selector recorria la parrilla declarada **sin ningun filtro**.
   En una contrarreloj eso ofrecia catorce vehiculos que no existen: ese modo
   llena la parrilla con los fantasmas de la tabla de tiempos en linea. La
   respuesta de la API lo decia sin ambiguedad ---`vehiculos: 15` junto a
   `vehiculos_en_carrera: 1`--- y nadie la leia.

   Y no era solo ruido: `backend/f1_udp.py:233` ya declara que en contrarreloj
   esa parrilla trae **identificadores de otras personas**.

   POR QUE ACA SI SE MIRA EL MODO, Y EN EL SALTO DEL VEHICULO NO. Un salto
   ocurre en cualquier modo, asi que alli la regla se apoya en lo que el
   vehiculo declara de si mismo ---ver `pudoRecorrer`--- y no en el modo. Que no
   haya rivales, en cambio, **es** una propiedad del contrarreloj y de ningun
   otro, y la fuente la declara. Las dos preguntas se parecen y no son la misma.

   UN SOLO CAMPO DECIDE. La procedencia trae `tipo_sesion`, `familia_de_sesion`
   y `modo_juego` diciendo lo mismo; consultar los tres seria tener tres
   respuestas para una pregunta el dia que difieran. Manda la familia, que es la
   que agrupa y la que el catalogo de sesiones ya usa.

   ANTE LA DUDA SE OFRECE. Sin procedencia no se sabe el modo, y no saberlo no
   es saber que es contrarreloj: esconder el selector por las dudas lo haria
   parpadear al arrancar cada sesion. */
function hayAQuienEscuchar(procedencia) {
  const familia = procedencia && procedencia.familia_de_sesion;
  if (!familia) return true;
  return String(familia).trim().toLowerCase() !== "contrarreloj";
}

function pintarEligeEscucha() {
  const caja = document.getElementById("elige-escucha");
  if (!caja) return;
  const escuchando = fuente === "f1"
    && (estadoSesion === "escuchando" || estadoSesion === "vivo")
    && hayAQuienEscuchar(estado.abierta && estado.abierta.procedencia);
  caja.hidden = !escuchando;
  if (!escuchando) return;
  if (escuchados === null) { leerEscuchados(); return; }

  const c = document.getElementById("pilotos-escucha");
  const nota = document.getElementById("nota-escucha");
  const parrilla = parrillaVigente();
  c.innerHTML = "";
  if (!parrilla || !parrilla.vehiculos.length) {
    /* Se dice que se esta esperando y no que no hay nadie: son cosas
       distintas, y la segunda haria pensar que el selector esta roto. */
    nota.textContent = "Esperando a que el juego declare la parrilla…";
    return;
  }

  const propio = (AUTOS.find(a => a.propio) || {}).id;
  const cabenMas = escuchados.length + 1 < topeEscucha;
  parrilla.vehiculos.forEach(v => {
    const esPropio = v.vehicle_id === propio;
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = v.nombre;
    /* EL COCHE PROPIO SE MUESTRA, MARCADO Y SIN APAGAR.
       Antes se lo sacaba de la lista. Escondido, la lista parecia incompleta
       ---faltaba justo quien conduce--- y no habia forma de ver que si se lo
       estaba escuchando. Se muestra marcado y deshabilitado: se escucha
       siempre, y eso no es una decision que se pueda tomar. */
    const elegido = esPropio || escuchados.indexOf(v.nombre) !== -1;
    b.setAttribute("aria-pressed", String(elegido));
    /* Los que no entran se muestran igual, apagados: sacarlos de la lista
       haria creer que ese piloto no esta en la carrera. */
    b.disabled = esPropio || (!elegido && !cabenMas);
    if (esPropio) {
      b.classList.add("propio");
      b.title = "Tu coche: se escucha siempre, es el unico con telemetria completa";
    }
    /* EL EQUIPO, EN UN PUNTO. NO EN EL BORDE NI EN EL FONDO.
       Con veinte pilotos, veinte bordes de colores distintos son veinte marcos
       compitiendo por la atencion, y lo que hay que ver de un vistazo es cuales
       estan elegidos. Un punto ocupa poco, dice el equipo igual, y deja el
       fondo y el borde libres para lo unico que cambia al pulsar. */
    const punto = document.createElement("i");
    punto.className = "punto-equipo";
    punto.style.background = colorDeEquipo(v.equipo);
    punto.title = v.equipo || "";
    b.insertBefore(punto, b.firstChild);
    if (!esPropio) b.addEventListener("click", () => cambiarEscuchado(v.nombre));
    c.appendChild(b);
  });

  const cuantos = escuchados.length + 1;
  nota.textContent = cuantos + " de " + topeEscucha + " vehículos"
    + (cabenMas ? "" : " · es el máximo que la cadena sostiene sin perder muestras");
}

function cambiarEscuchado(nombre) {
  const i = escuchados.indexOf(nombre);
  const pedidos = i === -1 ? escuchados.concat([nombre])
                           : escuchados.filter(n => n !== nombre);
  /* Se pinta con lo que **contesto el backend**, no con lo que se mando: si el
     tope rechaza la lista, el boton no debe quedar marcado. */
  mandar("/captura/pilotos", "POST", { pilotos: pedidos })
    .then(d => {
      escuchados = d.pilotos || [];
      pintarEligeEscucha();
      avisar(i === -1 ? "Escuchando también a " + nombre
                      : "Ya no se escucha a " + nombre, false);
    })
    .catch(e => { avisar(e.message, true); pintarEligeEscucha(); });
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
      } else if (seleccion.size < TINTAS_DE_AUTO.length) {
        seleccion.add(a.id);
      } else {
        /* Seis, que es lo que el capturador admite escuchar a la vez: el coche
           propio y cinco rivales. El tope de la comparacion es el de la paleta,
           porque mas alla de ahi dos pilotos compartirian trazo. */
        avisar("La comparación admite hasta " + TINTAS_DE_AUTO.length +
               " vehículos.", true);
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
  const ids = idsParaComparar();
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
    const puntos = muestrasQueAporta(id, numeros);
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
  const cobertura = coberturaDeLaVista(vuelta);
  document.getElementById("sub-comparacion").textContent =
    pista + " · " + cobertura + " · " + cuantas +
    (modoDetalle ? (cuantas === 1 ? " señal" : " señales") : " métricas comparadas");
}

let arrastre = null;

/* A QUIENES SE COMPARA. Lo decidian dos sitios con reglas distintas: el dibujo
   tomaba los primeros cuatro de la seleccion y la leyenda **uno solo** en la
   vista de detalle. De modo que la pantalla mostraba tres lineas y la leyenda
   nombraba a uno: quien mira no tenia como saber de quien era cada color.

   El detalle es de una señal, no de un piloto. Que se vea una sola magnitud no
   dice nada sobre cuantos vehiculos se estan comparando en ella. */
/* CUANTAS MUESTRAS APORTA UN VEHICULO, SOBRE EL EJE QUE EL BLOQUE DECLARA.
   Se contaba `distancia_m`, que OpenF1 no tiene: su abscisa es el reloj del
   tramo. Sobre tres pilotos con cuatrocientas una muestras cada uno, la leyenda
   decia «sin datos» al lado de sus propias lineas dibujadas. Es la misma regla
   que `_armarSerieDeCanal` ya declara: distancia si la hay, reloj si no. */
function muestrasQueAporta(id, numeros) {
  return (numeros || []).reduce((total, numero) => {
    const bloque = estado.series[numero];
    const veh = bloque && bloque.vehiculos && bloque.vehiculos[id];
    const eje = veh && (veh.distancia_m || veh.tiempo_s);
    return total + (eje ? eje.length : 0);
  }, 0);
}

function idsParaComparar() {
  return [...seleccion].slice(0, 4);
}

function vueltasParaComparar() {
  return alcanceComparacion === "carrera"
    ? estado.vueltas.map(v => v.numero)
    : [vueltaElegida];
}

/* ============================================================
   LA VISTA AMPLIADA TAMBIEN PIDE, Y NO SOLO EN LA SIMULACION
   ------------------------------------------------------------
   Esto arrancaba con `if (fuente !== "f1") return Promise.resolve([])`, de
   cuando comparar era cosa del simulador. Desde que la vista ampliada se abre
   sobre las tres fuentes, ese retorno temprano dejaba a las otras dos pidiendo
   nada: la vista se quedaba en «Cargando datos...» para siempre sobre una
   vuelta que la API tenia.

   Y bastante peor que eso, porque quien llamaba se volvia a dibujar al
   asentarse la promesa. Ver `reintentarComparacionCuandoLleguenLosDatos`.
   ============================================================ */
function asegurarDatosComparacion() {
  const cuales = vueltasParaComparar();
  /* Con una sola vuelta no hay presupuesto que repartir, y forzar los 300 de
     la vista espacial dejaria la ampliada mas gruesa que la cabina, que sobre
     una fuente que va contra el reloj pide 1.200. Se deja elegir al que sabe
     que eje tiene la fuente. */
  const puntos = cuales.length > 1 ? puntosParaVueltas(cuales.length) : undefined;

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
    if (ejeVigente() === "distancia") {
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
  const ids = idsParaComparar();
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

  const enDistancia = ejeVigente() === "distancia";
  const deLaCarrera = alcanceComparacion === "carrera";
  return {
    ids: ids, activas: activas, paneles: paneles,
    eje: ejeVigente(), alcance: alcanceComparacion,
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

/* ============================================================
   UN REINTENTO SE ATA A QUE ALGO CAMBIE, NO A QUE UNA PROMESA SE ASIENTE
   ------------------------------------------------------------
   ESTO COLGABA LA PAGINA, Y ASI. La vista ampliada, al no encontrar la vuelta
   bajo el cabezal, pedia los datos y se volvia a dibujar cuando la promesa se
   asentaba. Sobre una fuente que no fuera la simulacion esa promesa ya venia
   asentada y sin traer nada, de modo que el redibujo encontraba exactamente lo
   mismo, volvia a pedir, y otra vez. Son microtareas: se drenan enteras antes
   de que el navegador pueda pintar o atender un clic, asi que no es lentitud,
   es una pagina que no vuelve nunca.

   MEDIDO. Arrastrando el cabezal de OpenF1 con la ampliada abierta hasta una
   vuelta sin cargar: `dibujarComparacion` se llamo **928.517 veces en 72 s** y
   seguia. Todo lo demas del mismo arrastre, 143 llamadas. El servidor no
   recibio ni una consulta de mas: el bucle era entero del navegador.

   EL ARREGLO NO ES CONTAR INTENTOS. Un tope de reintentos elige un numero y
   deja el caso de al lado colgado un poco menos. Lo que hace falta es que el
   reintento dependa de que el estado **avance**: `_selloSeries` sube cada vez
   que `estado.series` cambia de verdad. Si despues de pedir el sello es el
   mismo, no llego nada y no hay nada que volver a dibujar. Y mientras se
   espera por un sello, no se abre una segunda espera por el mismo.
   ============================================================ */
let _selloEsperadoPorLaComparacion = null;

function reintentarComparacionCuandoLleguenLosDatos() {
  const sello = _selloSeries;
  if (_selloEsperadoPorLaComparacion === sello) return;
  _selloEsperadoPorLaComparacion = sello;
  asegurarDatosComparacion().then(() => {
    if (_selloEsperadoPorLaComparacion === sello) _selloEsperadoPorLaComparacion = null;
    if (_selloSeries === sello) return;
    pintarPilotosComparacion();
    dibujarComparacion();
  }, () => {
    if (_selloEsperadoPorLaComparacion === sello) _selloEsperadoPorLaComparacion = null;
  });
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
  /* LO QUE NO SE PUEDE ES EL EJE ESPACIAL, NO LA VISTA.
     Esto cortaba por fuente y dejaba fuera al bus entero. Lo que el bus no
     tiene es **metro medido**; contra el reloj tiene las trece señales y las
     marcas de tiempo con las que dibujarlas, que es lo que el boton de al lado
     hace. Se dice que falta y por que, y que el otro eje sirve. */
  const impedimento = motivoDelEjeEspacial();
  if (impedimento) { avisoDeComparacion(cv, ctx, impedimento); return; }

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
  const paleta = TINTAS_DE_AUTO;

  if (vista.vacia) {
    ctx.fillStyle = tinta("--texto-tenue"); ctx.font = "14px 'IBM Plex Sans', sans-serif";
    const faltan = vueltasParaComparar().some(numero => {
      const bloque = estado.series[numero];
      return !bloque || ids.some(id => !bloque.vehiculos[id]);
    });
    ctx.fillText(faltan ? "Cargando datos para los vehículos y el alcance seleccionados…"
                       : "Las métricas elegidas no tienen datos para estos vehículos.", 20, h / 2);
    if (faltan) reintentarComparacionCuandoLleguenLosDatos();
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
    ctx.textAlign = "center"; ctx.fillText(m.rotulo.toUpperCase() + " · " + unidadDeCanal(m.id), 0, 0);
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
        ctx.strokeStyle = tinta(tintaDeVehiculo(ids[ai]) || paleta[ai % paleta.length]);
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
    const valorCabezal = ejeVigente() === "distancia"
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
    ctx.fillText(ejeVigente() === "distancia" ? Math.round(v) + " m" : v.toFixed(1) + " s", x, yEje + 10);
  }
  ctx.textAlign = "left";

  // franja de zoom en curso
  if (arrastre) {
    ctx.fillStyle = tinta("--acento-veta") || "rgba(34,211,238,.14)";
    ctx.globalAlpha = .35;
    ctx.fillRect(Math.min(arrastre.a, arrastre.b), 0, Math.abs(arrastre.b - arrastre.a), yEje);
    ctx.globalAlpha = 1;
  }

  const unidadDelEje = ejeVigente() === "distancia" ? " m" : " s";
  const dice = [];
  if (zoom) {
    dice.push("Zoom activo entre " + cifra(d0, 1) + unidadDelEje + " y " +
              cifra(d1, 1) + unidadDelEje + ".");
  } else {
    if (alcanceComparacion === "carrera") dice.push("Carrera completa con segmentos separados por vuelta.");
    dice.push(ejeVigente() === "distancia"
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
  anotaciones: new Map(),
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
  //: La ultima coordenada es estado movil, no geometria del circuito. Sigue
  //: cambiando despues de cerrar la primera vuelta aunque `recorrido` se congele.
  posicionMundo: new Map(),
  /* La marca de tiempo y la velocidad de la posicion anterior, por vehiculo.
     Hacen falta para decidir si el coche **pudo** haber recorrido lo que hay
     entre dos posiciones, o si salto. Ver `pudoRecorrer`. */
  marcaDePosicion: new Map(),
  velocidadAnterior: new Map(),
  /* El metro de vuelta de cada posicion acumulada, en paralelo con
     `recorrido`. Hace falta para que el circuito que se congela no arrastre lo
     recorrido antes de la linea. Ver `soloDesdeLaLinea`. */
  metroDePosicion: new Map(),
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

/* Cierra la escucha y deja el tablero en algo que se pueda usar.

   Detener dejaba el boton diciendo «detener» ---porque el estado seguia siendo
   `escuchando` y nada lo sacaba de ahi--- de modo que no habia como volver a
   empezar. Y lo recien grabado no se podia mirar: estaba en la base, pero el
   tablero seguia esperando telemetria que ya no iba a llegar.

   Lo que se acaba de escuchar es justamente lo que se quiere ver, asi que se
   abre. El catalogo tarda unos segundos en incorporarlo ---la sesion se recuenta
   por detras--- y por eso se abre despues de refrescarlo, no antes. */
function terminarEscucha() {
  const recien = vivo.sesion;
  vivo.objetivo = null; vivo.aceptaNueva = false; vivo.pedida = false; vivo.otra = null;
  /* El flujo se cierra antes de cambiar de modo. Un lote SSE que ya estaba en
     cola podia llegar despues del clic y volver a poner el tablero en `vivo`,
     aunque la persona acabara de pedir exactamente lo contrario. */
  cerrarFlujoEnVivo();
  vaciarVivo(null);
  estadoSesion = estado.abierta ? "cargado" : "vacio";
  if (!recien) { render(); return; }
  estado.motivo = "Escucha detenida. Abriendo lo que se acaba de grabar…";
  render();
  const abrirCuandoEste = (quedan) => {
    if (SESIONES.some(x => x.session_id === recien)) { abrirSesionGuardada(recien); return; }
    if (quedan <= 1) {
      estado.motivo = "Escucha detenida. La sesión está en la base; si no aparece " +
                      "en la lista, abrila desde «Abrir sesión guardada».";
      render();
      return;
    }
    setTimeout(() => {
      pedir("/sesiones?limite=400")
        .then(c => { SESIONES = (c.sesiones || []).filter(x => x.filas > 0); })
        .catch(() => {})
        .then(() => abrirCuandoEste(quedan - 1));
    }, 1200);
  };
  abrirCuandoEste(8);
}

/* Deja el tablero listo para una sesion que todavia no llego.

   Pulsar «empezar a escuchar» no cambiaba nada visible: el boton seguia
   ofreciendo empezar ---de modo que no habia como detener--- y los paneles
   seguian mostrando la sesion que se estuviera reproduciendo, con sus datos y
   su circuito, como si fueran lo que esta entrando. Dos afirmaciones falsas al
   mismo tiempo.

   El estado `escuchando` es el que faltaba: no es `vivo`, porque todavia no
   llego ninguna muestra y decirlo seria mentir, y no es `cargado`, porque ya no
   se esta mirando nada guardado. Es la espera, y se declara como tal. */
function prepararEscucha() {
  estadoSesion = "escuchando";
  nuevaSesionEnCurso();
  PISTA = { path: "", curvas: [], largo_m: null, desnivel_m: null, muestras: null,
          sectores: [], sectoresOrigen: "", puntos: [] };
  CURVAS = [];
  vaciarVivo(null);
  sesionAbierta = null;
  estado.abierta = null;
  estado.vueltas = []; estado.series = {}; estado.pidiendo = {};
  estado.posiciones = {}; estado.pidiendoPos = {};
  cambiaronLasSeries();
  estado.disponibles = new Set();
  limpiarContextoDeSesion();
  AUTOS = []; seleccion = new Set(); estado.vehiculoClave = null;
  propioAMano = null; _tintaPorVehiculo = new Map();
  estado.cargando = false;
  estado.motivo = "Escuchando. Sin telemetría todavía: en cuanto el juego " +
                  "emita, el tablero se llena solo.";
  conectarFlujoEnVivo();
}

/* Pide la procedencia de una sesion que se esta capturando y la incorpora.

   Se pide una sola vez por sesion: la procedencia cambia dentro de una captura
   solo si el flujo se redeclara, y para eso ya esta el reintento de abajo, que
   corre unas pocas veces y para. Insistir seria consultar sesenta veces por
   minuto para recibir lo mismo. */
function pedirProcedenciaViva(sesion, intentos) {
  const quedan = intentos === undefined ? 5 : intentos;
  pedir("/sesiones/" + encodeURIComponent(sesion) + "/procedencia")
    .then(d => {
      if (!estado.abierta || estado.abierta.session_id !== sesion) return;
      /* QUIEN ES CADA VEHICULO, POR EL MISMO CAMINO QUE YA EXISTIA.
         `anotarParrillas` es lo que usa la reproduccion, y toma adquisiciones:
         se le pasa una sola, porque una captura en curso es una sola. Con una
         unica clave, `parrillaVigente` la toma sin necesidad de que haya
         adquisicion elegida ---en vivo no la hay--- y los vehiculos dejan de
         llamarse «Vehiculo 0» mientras se corre. */
      if (d && d.parrilla && d.parrilla.disponible) {
        anotarParrillas(sesion, [{ clave: "en-vivo", parrilla: d.parrilla }]);
        renombrarAutos();
      }
      if (d && d.procedencia) {
        estado.abierta.procedencia = d.procedencia;
        if (d.procedencia.circuito) estado.abierta.circuito = d.procedencia.circuito;
        render();
        return;
      }
      if (d && d.parrilla && d.parrilla.disponible) render();
      /* Todavia no hay: el flujo puede no haber declarado su tipo de sesion.
         Se vuelve a preguntar unas pocas veces, cada vez mas espaciado, y se
         deja de insistir. Sin procedencia el tablero ya sabe que decir. */
      if (quedan > 1) {
        setTimeout(() => pedirProcedenciaViva(sesion, quedan - 1),
                   (6 - quedan) * 2000 + 2000);
      }
    })
    .catch(() => {});
}

function vaciarVivo(sesion) {
  vivo.sesion = sesion || null;
  vivo.ultimos.clear(); vivo.series.clear(); vivo.distancia.clear(); vivo.vuelta.clear();
  vivo.reloj.clear(); vivo.vistos.clear(); vivo.ordenVistos.length = 0;
  vivo.anotaciones.clear();
  /* El recorrido es de la sesion que se deja: reusarlo dibujaria el circuito
     anterior debajo del coche de la nueva. */
  vivo.recorrido.clear(); vivo.posicionMundo.clear();
  vivo.marcaDePosicion.clear(); vivo.velocidadAnterior.clear();
  vivo.metroDePosicion.clear();
  vivo.recorridoDibujado = 0;
  /* Y lo derivado de las series tambien: las vistas temporales y los relojes de
     vuelta viven en otra cache, con la vuelta y el vehiculo por clave, y esos
     dos se repiten entre una sesion y la siguiente. */
  cambiaronLasSeries();
}

function limpiarContextoDeSesion() {
  estado.clima = null; estado.climaMotivo = "";
  /* El contexto de carrera se va con la sesion: es de esa carrera y de esos
     pilotos, y sobrevivir a un cambio dejaria el puesto de otro en pantalla. */
  estado.contextoCarrera = null; estado.climaDeCarrera = null;
  estado.controlDeCarrera = []; estado.controlDeCarreraCrudo = [];
  estado.vehiculo = null; estado.vehiculoMotivo = "";
  estado.puesta = null; estado.puestaMotivo = "";
  estado.avisos = []; estado.avisosMotivo = "";
  estado.avisosFallo = "";
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
  vivo.posicionMundo.set(vehiculo, [x, z]);

  /* Congelado significa una vuelta cerrada, no una ventana movil de vueltas.
     La posicion actual se conserva arriba, pero si se agrega al recorrido el
     `Z` del SVG une vueltas distintas y dibuja una cuerda que nunca se recorrio. */
  if (PISTA.medidoEnVivo === true && PISTA.enConstruccion === false) return;

  if (!vivo.recorrido.has(vehiculo)) vivo.recorrido.set(vehiculo, []);
  const puntos = vivo.recorrido.get(vehiculo);
  TESTIGO.posicionesConLasDos++;
  const ultimo = puntos.length ? puntos[puntos.length - 1] : null;
  // Un vehiculo detenido publica la misma posicion muchas veces por segundo.
  if (ultimo && ultimo[0] === x && ultimo[1] === z) return;
  TESTIGO.posicionesDistintas++;

  /* SI EL COCHE SALTO, EL TRAMO NO SE DIBUJA ---PERO LA POSICION SI SE GUARDA.
     El simulador teletransporta el coche al empezar una vuelta lanzada, y
     tambien con un `flashback` o un reinicio en boxes. Sin esto el recorrido
     los une con una recta que cruza el circuito. Ver `pudoRecorrer`. */
  const marcaAnterior = vivo.marcaDePosicion.get(vehiculo);
  let corte = false;
  if (ultimo && marcaAnterior !== undefined) {
    const dt = (marca - marcaAnterior) / 1000;
    const salto = Math.hypot(x - ultimo[0], z - ultimo[1]);
    const vel = ultimos.get("speed");
    const kmh = vel ? numeroMedido(vel.value) : null;
    corte = !pudoRecorrer(salto, dt, vivo.velocidadAnterior.get(vehiculo), kmh);
    if (corte) TESTIGO.saltosDeVehiculo = (TESTIGO.saltosDeVehiculo || 0) + 1;
    vivo.velocidadAnterior.set(vehiculo, kmh);
  } else {
    const vel = ultimos.get("speed");
    vivo.velocidadAnterior.set(vehiculo, vel ? numeroMedido(vel.value) : null);
  }
  vivo.marcaDePosicion.set(vehiculo, marca);

  puntos.push(corte ? [x, z, true] : [x, z]);
  /* En paralelo, el metro de vuelta de esa misma posicion. Se lee de la ultima
     muestra y no de `vivo.distancia`, que guarda el mayor visto: lo que hace
     falta es el metro **de este punto**, y antes de la linea es negativo. */
  if (!vivo.metroDePosicion.has(vehiculo)) vivo.metroDePosicion.set(vehiculo, []);
  const metros = vivo.metroDePosicion.get(vehiculo);
  const md = ultimos.get("lap_distance");
  metros.push(md ? numeroMedido(md.value) : null);
  if (metros.length > MAX_PUNTOS_DE_RECORRIDO) metros.shift();
  if (puntos.length > MAX_PUNTOS_DE_RECORRIDO) puntos.shift();
  /* CUANTAS POSICIONES DISTINTAS ENTRARON, NO CUANTAS QUEDAN.
     El redibujo se decidia por cuanto habia crecido el arreglo. Deja de crecer
     al llegar a las cuatro mil: desde ahi cada posicion nueva saca la mas
     vieja, la resta da cero y **el circuito deja de refinarse**. Justo al reves
     de lo que se queria: las vueltas siguientes vuelven a pasar por los mismos
     metros y son las que lo rectifican.

     Un contador que solo sube distingue «entro una posicion nueva» de «el
     arreglo tiene el mismo tamano». */
  puntos.rev = (puntos.rev || 0) + 1;
}

/* Rehace el dibujo del recorrido si crecio lo suficiente. Devuelve si cambio. */
function armarTrazadoVivo() {
  if (estadoSesion !== "vivo") return false;
  /* Un circuito ya cerrado manda sobre los puntos que lleguen despues. Mezclar
     varias vueltas en una polilinea cerrada inventa un tramo desde la punta
     actual hasta el comienzo de la primera. */
  if (PISTA.path && !PISTA.enConstruccion) return false;
  const clave = claveVehiculoPropio();
  const puntos = clave ? vivo.recorrido.get(clave) : null;
  if (!puntos || puntos.length < 3) return false;
  /* Se compara contra la revision, que cuenta lo que entro. El tope de
     redibujos se conserva: sigue siendo uno cada `PUNTOS_ENTRE_REDIBUJOS`
     posiciones distintas, y no uno por paquete. */
  const revision = puntos.rev || puntos.length;
  if (revision - vivo.recorridoDibujado < PUNTOS_ENTRE_REDIBUJOS
      && vivo.recorridoDibujado > 0) {
    return false;
  }
  vivo.recorridoDibujado = revision;

  const armado = trazadoAPath(puntos, false, false);
  if (!armado.path) return false;
  PISTA = {
    path: armado.path,
    largo_m: vivo.distancia.get(clave) || PISTA.largo_m || null,
    desnivel_m: null,
    muestras: puntos.length,
    vuelta: vivo.vuelta.get(clave) || null,
    curvas: CURVAS,
    enConstruccion: true,
    medidoEnVivo: undefined,
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
/* LO RECORRIDO ANTES DE LA LINEA NO ES EL CIRCUITO, TAMPOCO EN VIVO.

   TERCER SITIO DE LA MISMA REGLA, y los tres hacen falta porque los tres
   deciden cosas distintas: `fraccionDelMetro` decide donde poner el coche,
   `_solo_dentro_de_la_vuelta` ---en el backend--- decide que se dibuja de una
   sesion guardada, y esta decide **que se congela como circuito** en vivo.

   Mientras el recorrido se construye se dibuja entero, y esta bien: el
   encabezado declara «recorrido en construccion, medido en vivo» y lo que se
   ve es lo que el coche recorrio. Lo que no puede pasar es que eso se
   congele **como el circuito**: ahi entrarian la aproximacion y la vuelta
   rapida superpuestas, que es exactamente la cuña y la falsa chicana que se
   vieron en la sesion guardada de Shanghai.

   Sin metros no se recorta: una fuente que no publica distancia de vuelta
   ---el bus--- no declara nada sobre la linea, y recortarla la dejaria sin
   circuito. Desalineados tampoco, por lo mismo que en `marcarSaltos`: recortar
   por un indice corrido borraria un tramo que si se recorrio. */
function soloDesdeLaLinea(puntos, metros) {
  if (!Array.isArray(puntos) || !Array.isArray(metros) ||
      metros.length !== puntos.length) return puntos;
  let desde = -1;
  for (let i = 0; i < metros.length; i++) {
    const m = metros[i];
    if (typeof m === "number" && isFinite(m) && m < 0) desde = i;
  }
  return desde < 0 ? puntos : puntos.slice(desde + 1);
}

function congelarTrazadoVivo(largoDeLaVuelta) {
  const clave = claveVehiculoPropio();
  const crudos = clave ? vivo.recorrido.get(clave) : null;
  /* El circuito son los metros de la vuelta. Ver `soloDesdeLaLinea`. */
  const puntos = soloDesdeLaLinea(crudos, clave ? vivo.metroDePosicion.get(clave) : null);
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
    /* SE CONSERVA LA PROYECCION, Y ESO ES LO QUE HACE QUE EL COCHE NO
       DESAPAREZCA.
       Al cerrar se dejaba de guardarla, y desde ahi la marca se ubicaba por
       distancia recorrida sobre el camino. Cuando esa distancia no avanza
       ---un reinicio, un teletransporte, una vuelta que el juego no cierra---
       la marca se queda quieta o se va del dibujo, y lo que se ve es un
       circuito sin coche. La posicion medida llega veinte veces por segundo y
       no depende de nada de eso. */
    proyectarMundo: armado.proyectarMundo,
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
    PISTA = { path: "", curvas: [], largo_m: null, desnivel_m: null, muestras: null,
          sectores: [], sectoresOrigen: "", puntos: [] };
    CURVAS = [];
    vaciarVivo(m.session_id);
    fuente = "f1";
    sesionAbierta = m.session_id;
    estado.abierta = SESIONES.find(s => s.session_id === m.session_id) || {
      session_id: m.session_id, fuente: m.source_type, senales: null, vehiculos: 0,
      filas: 0, procedencia: {},
    };
    /* Y se le pregunta su procedencia, porque la de arriba viene vacia.
       El catalogo se recuenta por detras y **no incluye la sesion que se esta
       capturando ahora**, de modo que aca no se la encuentra y se arma una
       entrada propia sin circuito ni parrilla: el tablero decia «sesion sin
       procedencia declarada» mientras se corria, y le ponia el nombre recien al
       terminar. El capturador la escribe apenas el flujo se declara; lo que
       faltaba era pedirla. */
    pedirProcedenciaViva(m.session_id);
    recuperarAnotacionesVivas(m.session_id, vivo.conexion);
    estado.series = {}; estado.pidiendo = {}; estado.posiciones = {}; estado.pidiendoPos = {};
    cambiaronLasSeries();
    estado.disponibles = new Set();
    limpiarContextoDeSesion();
    AUTOS = []; seleccion = new Set(); estado.vehiculoClave = null;
  propioAMano = null; _tintaPorVehiculo = new Map();
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
    /* LA REVISION, PORQUE EL LARGO DEJA DE CRECER.
       La vista convertida a la unidad de presentacion se memorizaba por el
       largo del arreglo, con el argumento de que «el arreglo solo crece». Deja
       de crecer al llegar a las seiscientas muestras: desde ahi cada muestra
       nueva saca la mas vieja, el contenido cambia y el largo no. La vista
       memorizada se congelaba, y los canales que se muestran convertidos
       ---presiones, temperaturas--- dejaban de moverse **justo cuando la
       ventana se llena**, o sea al medio minuto de escuchar.

       Un contador que solo sube distingue las dos cosas: cuantas muestras
       entraron, no cuantas quedan. */
    serie.rev = (serie.rev || 0) + 1;
  }

  estadoSesion = "vivo";
  if (vivo.silencio) clearTimeout(vivo.silencio);
  vivo.silencio = setTimeout(() => {
    if (estadoSesion === "vivo") {
      // Si se estaba escuchando, callar es volver a esperar, no cerrar.
      estadoSesion = vivo.pedida || vivo.objetivo
        ? "escuchando" : (estado.abierta ? "cargado" : "vacio");
      render();
    }
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

const CAMPOS_PUESTA_VIVA = [
  ["aleron_delantero", "setup_front_wing", "nivel", true],
  ["aleron_trasero", "setup_rear_wing", "nivel", true],
  ["diferencial_con_acelerador_pct", "setup_differential_on_throttle", "%", true],
  ["diferencial_sin_acelerador_pct", "setup_differential_off_throttle", "%", true],
  ["caida_delantera_deg", "setup_camber_front", "deg", true],
  ["caida_trasera_deg", "setup_camber_rear", "deg", true],
  ["convergencia_delantera_deg", "setup_toe_front", "deg", true],
  ["convergencia_trasera_deg", "setup_toe_rear", "deg", true],
  ["suspension_delantera", "setup_suspension_front", "nivel", true],
  ["suspension_trasera", "setup_suspension_rear", "nivel", true],
  ["barra_delantera", "setup_anti_roll_bar_front", "nivel", true],
  ["barra_trasera", "setup_anti_roll_bar_rear", "nivel", true],
  ["altura_delantera", "setup_ride_height_front", "nivel", true],
  ["altura_trasera", "setup_ride_height_rear", "nivel", true],
  ["presion_de_freno_pct", "setup_brake_pressure", "%", true],
  ["sesgo_de_freno_pct", "setup_brake_bias_front", "%", true],
  ["freno_motor_pct", "setup_engine_braking", "%", true],
  ["presion_neumatico_trasero_izq_psi", "setup_tyre_pressure_rear_left", "psi", true],
  ["presion_neumatico_trasero_der_psi", "setup_tyre_pressure_rear_right", "psi", true],
  ["presion_neumatico_delantero_izq_psi", "setup_tyre_pressure_front_left", "psi", true],
  ["presion_neumatico_delantero_der_psi", "setup_tyre_pressure_front_right", "psi", true],
  ["lastre", "setup_ballast", "nivel", true],
  ["combustible_inicial_kg", "setup_fuel_load", "kg", true],
];

const CAMPOS_CARROCERIA_VIVA = {
  ala_delantera_izq_pct: "wing_damage_front_left",
  ala_delantera_der_pct: "wing_damage_front_right",
  ala_trasera_pct: "wing_damage_rear",
  piso_pct: "floor_damage",
  difusor_pct: "diffuser_damage",
  pontones_pct: "sidepod_damage",
  caja_pct: "gearbox_damage",
  motor_pct: "engine_damage",
};

const CAMPOS_ESQUINA_VIVA = {
  temperatura_superficie_c: "tyre_temperature_surface_%s",
  temperatura_interna_c: "tyre_temperature_inner_%s",
  presion_psi: "tyre_pressure_%s",
  desgaste_pct: "tyre_wear_%s",
  dano_pct: "tyre_damage_%s",
  ampollas_pct: "tyre_blisters_%s",
  freno_c: "brake_temperature_%s",
  dano_freno_pct: "brake_damage_%s",
  deslizamiento: "wheel_slip_ratio_%s",
  velocidad_rueda_kmh: "wheel_speed_%s",
  superficie: "surface_type_%s",
};

const CAMPOS_CLIMA_VIVO = {
  temperatura_aire_c: "air_temperature",
  temperatura_pista_c: "track_temperature",
  codigo_de_clima: "weather_code",
  bandera: "fia_flag",
  retraso_del_coche_de_seguridad_s: "safety_car_delta",
};

const CLIMA_TEXTO_VIVO = {
  0: "despejado", 1: "nubes ligeras", 2: "nublado",
  3: "lluvia ligera", 4: "lluvia intensa", 5: "tormenta",
};

const BANDERA_TEXTO_VIVO = {
  "-1": "sin dato", 0: "ninguna", 1: "verde", 2: "azul", 3: "amarilla", 4: "roja",
};

function sincronizarContextoVivo() {
  if (estadoSesion !== "vivo") return;
  const clave = claveVehiculoPropio();
  const ultimos = clave && vivo.ultimos.get(clave);
  if (!ultimos) return;
  const valor = canal => {
    const muestra = ultimos.get(canal);
    return muestra ? numeroMedido(muestra.value) : null;
  };

  const canalesClima = Object.values(CAMPOS_CLIMA_VIVO);
  const ultimosClima = [...vivo.ultimos.values()].find(
    mapa => canalesClima.some(canal => mapa.has(canal))) || ultimos;
  const clima = {};
  Object.entries(CAMPOS_CLIMA_VIVO).forEach(([nombre, canal]) => {
    const muestra = ultimosClima.get(canal);
    const medido = muestra ? numeroMedido(muestra.value) : null;
    if (medido !== null) clima[nombre] = medido;
  });
  if (clima.codigo_de_clima !== undefined) {
    clima.clima = CLIMA_TEXTO_VIVO[clima.codigo_de_clima] || "desconocido";
  }
  if (clima.bandera !== undefined) {
    clima.bandera_texto = BANDERA_TEXTO_VIVO[clima.bandera] || "desconocida";
  }
  estado.clima = Object.keys(clima).length ? clima : null;

  const esquinas = {};
  ["front_left", "front_right", "rear_left", "rear_right"].forEach(esquina => {
    const datos = {};
    Object.entries(CAMPOS_ESQUINA_VIVA).forEach(([nombre, plantilla]) => {
      const medido = valor(plantilla.replace("%s", esquina));
      if (medido !== null) datos[nombre] = medido;
    });
    if (Object.keys(datos).length) esquinas[esquina] = datos;
  });
  const carroceria = {};
  Object.entries(CAMPOS_CARROCERIA_VIVA).forEach(([nombre, canal]) => {
    const medido = valor(canal);
    if (medido !== null) carroceria[nombre] = medido;
  });
  estado.vehiculo = Object.keys(esquinas).length
    ? { esquinas: esquinas, carroceria: carroceria } : null;

  const campos = [];
  const puesta = {};
  const instantesPuesta = [];
  CAMPOS_PUESTA_VIVA.forEach(([nombre, canal, unidad, decodificado]) => {
    const muestra = ultimos.get(canal);
    const medido = muestra ? numeroMedido(muestra.value) : null;
    if (medido === null) return;
    puesta[nombre] = medido;
    campos.push({ clave: nombre, canal: canal, valor: medido,
                  unidad: unidad, decodificado: decodificado });
    if (muestra.timestamp) instantesPuesta.push(new Date(muestra.timestamp).getTime());
  });
  const completa = campos.length === CAMPOS_PUESTA_VIVA.length &&
    instantesPuesta.length === campos.length && new Set(instantesPuesta).size === 1;
  const rodajePosterior = ultimos.get("speed");
  const asentada = completa && rodajePosterior && rodajePosterior.timestamp &&
    numeroMedido(rodajePosterior.value) > 0 &&
    new Date(rodajePosterior.timestamp).getTime() > instantesPuesta[0];
  estado.puesta = campos.length ? {
    puesta_a_punto: puesta,
    campos: campos,
    puesta_completa: completa,
    puesta_asentada: !!asentada,
    sin_decodificar: [],
  } : null;
  estado.avisos = (vivo.anotaciones.get(clave) || []).slice();
}

function incorporarAnotacionViva(a) {
  if (!a || !a.vehiculo || !vivo.sesion ||
      !a.vehiculo.startsWith(vivo.sesion + ":car:")) return;
  if (!vivo.anotaciones.has(a.vehiculo)) vivo.anotaciones.set(a.vehiculo, []);
  const lista = vivo.anotaciones.get(a.vehiculo);
  const id = a.id === undefined
    ? [a.nivel, a.titulo, a.reloj_s].join("|")
    : "id:" + a.id;
  const aviso = {
    id: id,
    nivel: a.nivel === "incidente" ? "alerta" : "info",
    que: a.titulo || "Anotacion en vivo",
    detalle: a.detalle || "",
    vuelta: a.vuelta || null,
    metro: a.distancia_m || null,
    canal: a.fundamento || "anotador en vivo",
    umbral: a.fundamento || null,
    valor: null,
    unidad: "",
    /* EL INSTANTE MEDIDO, QUE ANTES SE DESCARTABA. `reloj_s` es epoca Unix en
       segundos, la misma que la reproduccion convierte a `instante`. Sin esto
       la lista viva quedaba en orden de llegada, con el mas viejo arriba. */
    instante: (typeof a.reloj_s === "number" && isFinite(a.reloj_s))
      ? new Date(a.reloj_s * 1000).toISOString() : null,
    /* En vivo no hay fraccion de sesion: la sesion no termino y no se sabe
       sobre que total. Se deja en 1 para que el filtro del cabezal ---que en
       vivo corta en 1--- los deje pasar a todos, y el orden lo decide el
       instante de arriba. */
    en: 1,
  };
  const anterior = lista.findIndex(x => x.id === id);
  if (anterior >= 0) lista[anterior] = aviso;
  else lista.push(aviso);
  _firmaAvisos = "";
  pedirPintado("valores");
}

function recuperarAnotacionesVivas(sesion, conexion) {
  if (!sesion) return;
  pedir("/live/anotaciones?sesion=" + encodeURIComponent(sesion))
    .then(d => {
      if (conexion !== vivo.conexion || sesion !== vivo.sesion) return;
      Object.entries((d && d.vehiculos) || {}).forEach(([vehiculo, bloque]) => {
        (bloque.anotaciones || []).forEach(a =>
          incorporarAnotacionViva(Object.assign({}, a, { vehiculo: vehiculo })));
      });
    })
    .catch(e => { if (!fueAnulada(e) && e instanceof TypeError) console.error(e); });
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
    /* El servidor agrupa senales para no pagar una respuesta SSE por cada una.
       Se conserva la forma individual para conexiones contra una version
       anterior durante un despliegue. */
    const recibido = datoEvento(e);
    const lote = Array.isArray(recibido) ? recibido : [recibido];
    lote.forEach(m => incorporarTelemetriaViva(m));
  });
  canal.addEventListener("anotacion", e => {
    const d = datoEvento(e);
    if (d) incorporarAnotacionViva(d);
  });
  canal.addEventListener("latido", e => {
    const d = datoEvento(e);
    if (d) estado.vivo = Object.assign({}, estado.vivo || {}, { mensajes_recibidos: d.recibidos });
    pintarTransporte();
  });
  canal.onopen = () => {
    recuperarAnotacionesVivas(vivo.sesion, miConexion);
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
/* CUAL SE ABRE SOLA AL ENTRAR: la que se estaba mirando, y ninguna otra.
   ---------------------------------------------------------------------
   Antes, sin nada recordado, se abria la sesion **mas grande de F1 25**. La
   idea era no dejar el tablero en blanco, pero abrir de prepo una carrera que
   nadie pidio tiene dos costos: la persona cree que eso es «lo suyo» cuando es
   la que mas filas tiene, y se pagan las consultas de una sesion que quiza no
   queria. Sin recuerdo no se abre nada: el tablero dice que elijas, que es lo
   que efectivamente hay que hacer.

   Se queda sin DOM para poder ejercerla. */
function sesionQueSeAbreSola(sesiones, recordada) {
  if (!recordada) return null;
  const hay = (sesiones || []).find(s => s.session_id === recordada);
  return hay ? hay.session_id : null;
}

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
  /* Algunos consumidores reutilizan esta limpieza sin cargar el transporte.
     `typeof` conserva ese contrato y, en el tablero, invalida el callback que
     una apertura anterior hubiera dejado pendiente. */
  if (typeof _relojPedidos !== "undefined") {
    clearTimeout(_relojPedidos);
    _relojPedidos = null;
  }
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
  estado.contextoCarrera = null; estado.climaDeCarrera = null;
  estado.controlDeCarrera = []; estado.controlDeCarreraCrudo = [];
  estado.puesta = null; estado.avisos = []; estado.avisosFallo = "";
  estado.disponibles = new Set();
  estado.vehiculoClave = null;
  estado.climaMotivo = ""; estado.vehiculoMotivo = ""; estado.avisosMotivo = "";
  estado.puestaMotivo = "";
  _esencialResuelta = false;
  estado.cargando = true;
  PISTA = { path: "", curvas: [], largo_m: null, desnivel_m: null, muestras: null,
          sectores: [], sectoresOrigen: "", puntos: [] };
  CURVAS = [];
  vivo.recorrido.clear();
  vivo.marcaDePosicion.clear(); vivo.velocidadAnterior.clear();
  vivo.metroDePosicion.clear();
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
  if (corta !== fuente) {
    fuente = corta;
    configurarVentanaDeGraficos();
    marcar(document.getElementById("sel-fuente"), "fuente", fuente);
  }
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

/* COMO SE LLAMA UNA ADQUISICION, Y SE DECIDE EN UN SOLO SITIO.

   Desde que la API separa las capturas originales ---`original-1`,
   `original-2`--- el elector muestra una fila por cada una. Las dos decian
   «Original» con la misma fecha y solo se distinguian por la cantidad de
   muestras, que es pedirle a quien mira que deduzca cual es cual; y elegir mal
   es reproducir la captura equivocada.

   El elector y el encabezado lo escribian cada uno por su cuenta y nada
   obligaba a que coincidieran. Con una sola captura ---el caso normal--- sigue
   diciendo «Original», porque no hay nada que numerar. */
function nombreDeAdquisicion(a, disponibles) {
  if (!a) return "";
  if (a.es_reproduccion) return a.clave;
  const capturas = (disponibles || []).filter(x => !x.es_reproduccion);
  if (capturas.length <= 1) return "Original";
  const cual = capturas.findIndex(x => x.clave === a.clave);
  if (cual < 0) return "Original";
  return "Captura " + (cual + 1) + " de " + capturas.length;
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
    "<span><b>" + textoSeguro(nombreDeAdquisicion(a, corrida.disponibles)) + "</b><br>" +
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
  /* Acá el tablero deja de cargar y pasa a esperar a la persona. Sostener el
     velo sobre una pregunta es esconder la pregunta. */
  levantarElVelo();
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
  return alcanceResuelto();
}

/* Resolver adquisicion y fase es necesario para cualquier eje. La distancia
   agrega otra restriccion, pero una fuente temporal no tiene que quedar afuera
   del historico solo por no publicar metros. */
function alcanceResuelto() {
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
  const base = a ? nombreDeAdquisicion(a, corrida.disponibles) : corrida.adquisicion;
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
  /* LA PARRILLA DE OPENF1 SE PIDE ACA, QUE ES POR DONDE PASAN TODOS.
     No viene por `/adquisiciones` ---esa ruta es del simulador y para esta
     fuente contesta vacio, correctamente---: vive en el contexto deportivo.

     ESTABA EN `abrirSesionGuardada` Y NO ALCANZABA. Esa funcion es uno de los
     caminos, no el unico: `elegirCorrida` vuelve a cargar la sesion por aca sin
     pasar por ella, y ese es justo el que corre al elegir adquisicion o fase, o
     al recargar la pagina con una eleccion en la direccion. Por ese camino la
     consulta no salia nunca y los pilotos seguian siendo «Vehículo 1».

     Y usa la apertura **que le dieron**. Pedida con una anterior en la mano,
     `sigueVigente` descarta la respuesta por vieja: la consulta sale, contesta
     en veinte milisegundos y el resultado se tira. */
  if (fuente === "openf1") pedirParrillaDeOpenF1((s || {}).session_id, apertura);

  /* Los avisos no hacen falta para dibujar y su consulta puede durar veinte
     segundos reteniendo una conexion. Se piden cuando ya hay un grafico. */
  cuandoHayaGrafico(() => pedirAvisos(ruta, apertura, senal));

  /* Y lo que la fuente declara por su cuenta, que es otra ruta porque es otra
     clase de hecho. Se pide una vez por sesion ---son ciento cincuenta y ocho
     eventos en una carrera, no una serie--- y falla sola: que no haya control
     de carrera no puede dejar sin avisos derivados a quien si los tiene. */
  pedirControlDeCarrera((s || {}).session_id, apertura);

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
  cuandoHayaGrafico(() => {
    const cuando = instanteUtc();
    return conCarga(["clima", "vehiculo", "puesta"], () =>
      pedir(ruta + "/contexto" + (cuando
        ? "?hasta=" + encodeURIComponent(cuando) + sufijoDeCorrida(true)
        : sufijoDeCorrida(false)), { senal: senal })
      .then(ctx => {
        if (!sigueVigente(apertura) || !ctx) return;
        estado.clima = ctx.clima || null;
        estado.climaMotivo = ctx.clima_motivo || "";
        estado.vehiculo = (ctx.esquinas && Object.keys(ctx.esquinas).length)
          ? { esquinas: ctx.esquinas, carroceria: ctx.carroceria } : null;
        estado.vehiculoMotivo = ctx.vehiculo_motivo || "";
        estado.puesta = (ctx.campos && ctx.campos.length) ? ctx : null;
        estado.puestaMotivo = motivoDeLaPuesta(ctx);
        if (estado.clima) estado.disponibles.add("air_temperature");
        if (estado.vehiculo) estado.disponibles.add("tyre_temperature_surface_front_left");
        if (estado.puesta) estado.disponibles.add("setup_front_wing");
        aplicarDisponibilidad();
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
        }));
  });

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
    /* Las funciones de reloj trabajan con tramos temporales. Para una fuente
       sin vueltas, el catalogo ya declara los dos extremos de la captura: se
       representa como un unico tramo interno, aunque la interfaz nunca lo llame
       vuelta. Esto permite compartir interpolacion, pausas y cabezal sin
       inventar una distancia. */
    if (!hayEjeDeDistancia() && !estado.vueltas.length && s.desde && s.hasta) {
      estado.vueltas = [{
        numero: 1,
        duracion_s: numeroMedido(s.duracion_s) ||
          Math.max(0, (Date.parse(s.hasta) - Date.parse(s.desde)) / 1000),
        desde_utc: s.desde,
        hasta_utc: s.hasta,
        huecos: [],
        continua: true,
        tramo_temporal: true,
      }];
    }

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
      /* UN HUECO LARGO NO ES UNA PERDIDA, Y NO SE PINTA COMO SI LO FUERA.
         A veinte hercios, perder muestras deja huecos de decimas. Un hueco de
         segundos es otra cosa: el coche parado en boxes, el juego en el menu,
         la sesion en pausa. La fuente no publica telemetria mientras no se
         conduce, y eso no tiene nada de malo.

         Se decia en rojo en los dos casos. Sobre una captura sin una sola
         muestra perdida ---cero descartes del intermediario, huecos de
         cincuenta milisegundos--- el tablero abria con un aviso de error por
         los veinticinco segundos que el coche estuvo en el garaje.

         Ahora se dice cuanto duro el mayor, que es el dato que permite
         distinguirlo, y solo se pinta como problema cuando es corto. */
      const mayor = Math.max.apply(null, rotas.map(v => v.hueco_mayor_s || 0));
      const esPerdida = mayor > 0 && mayor < 2;
      decirEstadoApi(
        rotas.length + (rotas.length === 1 ? " vuelta tiene" : " vueltas tienen") +
        " un salto entre muestras seguidas ---vuelta " +
        rotas.map(v => v.numero).join(", ") + ", el mayor de " +
        (mayor >= 1 ? cifra(mayor, 1) + " s" : Math.round(mayor * 1000) + " ms") + "---. " +
        (esPerdida
          ? "Un hueco tan corto son muestras que no llegaron. "
          : "Un hueco de ese largo es el coche detenido o el juego fuera de pista, " +
            "no telemetría perdida. ") +
        "La reproducción usa la duración de conducción continua; la diferencia " +
        "contra el tiempo total está declarada en la respuesta de la API.",
        esPerdida);
    }
    poblarVueltas();
    // Clima, vehiculo y puesta los aplica su propia consulta, arriba.
    pedirTrazado(ruta);
    if (trazado && trazado.puntos && trazado.puntos.length) {
      estado.trazado = trazado;
      PISTA = armarPista(trazado, CURVAS);
    }

    // Los avisos llegan por su cuenta; aca solo se recolocan los que ya haya,
    // porque ubicarlos necesita las vueltas y recien ahora estan. Y son dos
    // listas: los derivados de la telemetria y los que declaro la fuente.
    ubicarAvisos(estado.avisos.map(a => a));
    ubicarControlDeCarrera(estado.controlDeCarreraCrudo || []);
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
  /* La clave incluye de quien se mira: cambiar de piloto tiene que volver a
     pedir el contexto, o se seguiria mostrando el neumatico del anterior. */
  const clave = estado.abierta.session_id + "|" + t.vuelta + "|" + autoPropio().id;
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
    pedir(ruta + "/contexto?hasta=" + encodeURIComponent(cuando) +
          "&vehiculo=" + encodeURIComponent(autoPropio().id) + sufijoDeCorrida(true),
          { senal: senalDeSesion() })
      .then(d => {
        if (!sigueVigente(apertura)) return;
        estado.clima = d.clima || null;
        estado.climaMotivo = d.clima_motivo || "";
        estado.vehiculo = (d.esquinas && Object.keys(d.esquinas).length)
          ? { esquinas: d.esquinas, carroceria: d.carroceria } : null;
        estado.vehiculoMotivo = d.vehiculo_motivo || "";
        estado.puesta = (d.campos && d.campos.length) ? d : null;
        estado.puestaMotivo = motivoDeLaPuesta(d);
        if (estado.clima) estado.disponibles.add("air_temperature");
        if (estado.vehiculo) estado.disponibles.add("tyre_temperature_surface_front_left");
        if (estado.puesta) estado.disponibles.add("setup_front_wing");
        aplicarDisponibilidad();
        _firmaClima = ""; _firmaEsquinas = ""; _firmaPuesta = "";
        pintarClima(); pintarEsquinas(); pintarPuestaAPunto();
      })
      .catch(e => {
        // Si fallo, la clave se limpia para que el proximo intento vuelva a
        // pedirlo en vez de creer que ya lo tiene.
        _contextoDe = "";
        if (!fueAnulada(e) && e instanceof TypeError) console.error(e);
      })
      .then(() => {
        _contextoEnVuelo = false;
        /* Si mientras volaba se eligio otro piloto, lo que llego es del
           anterior. La clave termina en el vehiculo que se pidio. */
        if (estado.abierta && _contextoDe &&
            _contextoDe.split("|")[2] !== autoPropio().id) refrescarContexto();
      }));

  pedirContextoDeCarrera(cuando, apertura);
}

/* ============================================================
   EL CONTEXTO DE CARRERA DE OPENF1, QUE YA ESTABA GUARDADO Y NADIE PEDIA
   ------------------------------------------------------------
   El tablero mostraba rayas en POSICION y AL LIDER, y el panel de clima decia
   que esta fuente no publica clima. Las tres cosas estaban en la base desde la
   importacion. Contado por el propio backend sobre la sesion 9947:

       racing_weather        155 muestras
       racing_intervals   19.943 filas
       racing_positions      538 filas
       racing_stints          55 filas

   Y `/racing/sessions/{key}/context-at` ya las resolvia en un instante. Lo que
   faltaba era pedirla: el tablero no la nombraba en ninguna linea.

   NO ES LA MISMA CONSULTA QUE `/contexto`, Y POR ESO VA APARTE. Aquella trae lo
   que viaja **en la telemetria** de la sesion abierta. Esta trae lo que la
   fuente declara **alrededor** de la telemetria y que vive en otras tablas. Van
   al mismo instante y se piden juntas, pero una fuente puede tener una y no la
   otra, y mezclarlas obligaria a cada una a saber de la otra.
   ============================================================ */

/* El contexto de carrera del vehiculo propio, o `null` si esta fuente no tiene.
   Se busca por numero de carrera porque es la llave con la que vuelve. */
function contextoDelPropio() {
  const porNumero = estado.contextoCarrera;
  if (!porNumero) return null;
  const n = identidadDeVehiculo(claveVehiculoPropio()).numero;
  return (n !== null && n !== undefined) ? (porNumero[String(n)] || null) : null;
}

/* Cuanto hace que se declaro, en palabras y entre parentesis. Cadena vacia si
   no se sabe: un parentesis vacio en un titulo es peor que no ponerlo. */
/* QUE TAN FRESCO ES UN VALOR DEL CONTEXTO, Y COMO SE DICE.
   ---------------------------------------------------------------------
   La API resuelve el estado y lo manda: `current`, `aged`, `held` o
   `unavailable`. El tablero **no lo recalcula**, porque el umbral sale de la
   cadencia de cada magnitud y esa cadencia la conoce quien la midio, no quien
   la dibuja.

   POR QUE NO ALCANZABA UN UMBRAL UNICO. Las magnitudes de esta fuente se
   publican cada 8, 60 y 336 segundos. Con un corte unico de treinta, el clima
   ---edad mediana 49 s--- se habria borrado siempre, y el puesto en cincuenta y
   uno de cada sesenta instantes. Borrar un dato que la fuente declaro no es
   conservador: afirma un desconocimiento que no existe.

   `held` NO ES UN ESTADO DEGRADADO, y esta es la decision que mas importa de
   todo esto. Atenuar significa «desconfia un poco de esto». Un puesto que la
   fuente publica **al cambiar** no merece desconfianza entre dos cambios: es
   exactamente lo que declaro y no ha cambiado. Lo que merece es una aclaracion
   de cuando es, no una degradacion.

   Se separa del DOM para poder ejercerla. */
/* LA MARCA VISUAL VIVE EN LA HOJA, NO EN EL TEXTO. Primero el sostenido llevaba
   un punto pegado al numero, y con la edad desconocida quedaba « ·» solo: un
   caracter suelto que no dice nada. Una marca que depende de que haya otro dato
   al lado no es una marca. La pone el estilo sobre `data-frescura`, que esta
   siempre. */
const FRESCURAS = {
  current: { atenua: false, dice: "" },
  held: {
    atenua: false,
    dice: "sostenido: la fuente lo publica al cambiar, no en cada muestra",
  },
  aged: { atenua: true, dice: "mas viejo que la cadencia de esta magnitud" },
  unavailable: { atenua: false, dice: "" },
};

function comoSeVe(estado, segundos) {
  const regla = FRESCURAS[estado];
  if (!regla) return { estado: "current", atenua: false, sufijo: "", aclara: "" };
  /* La edad se escribe **solo cuando deja de ser obvia**. En `current`, que es
     el caso normal, una edad al lado de cada numero es ruido permanente para
     decir que todo esta bien, y el tablero tiene ocho paneles. */
  const edad = (estado === "held" || estado === "aged")
    ? edadEnPalabras(segundos) : "";
  return {
    estado: estado,
    atenua: regla.atenua,
    sufijo: edad.replace(/^,\s*/, ""),
    aclara: regla.dice + edad,
  };
}

function edadEnPalabras(segundos) {
  /* `Number(null)` es cero, no un no-numero: sin esta linea una edad que no
     se sabe se anunciaba como «hace 0 s», que es la afirmacion contraria. */
  if (segundos === null || segundos === undefined || segundos === "") return "";
  const s = Number(segundos);
  if (!Number.isFinite(s) || s < 0) return "";
  if (s < 90) return ", hace " + Math.round(s) + " s";
  return ", hace " + Math.round(s / 60) + " min";
}

/* Los numeros de carrera de los que se quiere contexto. Son numeros y no las
   claves internas: `context-at` habla el vocabulario de OpenF1. */
function numerosDePilotoDelContexto() {
  const vistos = [];
  const sumar = clave => {
    const n = identidadDeVehiculo(clave).numero;
    if (Number.isFinite(Number(n)) && vistos.indexOf(Number(n)) === -1) vistos.push(Number(n));
  };
  sumar(claveVehiculoPropio());
  [...seleccion].forEach(sumar);
  return vistos;
}

/* Lo que `context-at` contesta, indexado por numero de carrera. */
function contextoPorPiloto(d) {
  const porNumero = {};
  ((d && d.drivers) || []).forEach(p => { porNumero[String(p.driver_number)] = p; });
  return porNumero;
}

/* El clima de la carrera, con los nombres que el panel ya usa.
   Solo se copian las claves que la respuesta trae: una clave ausente es «esta
   fuente no lo publica» y el panel no le dibuja casilla. */
function climaDeLaCarrera(w) {
  if (!w) return null;
  const d = {};
  const copiar = (desde, hacia) => {
    if (w[desde] !== undefined) d[hacia] = w[desde];
  };
  copiar("track_temperature_c", "temperatura_pista_c");
  copiar("air_temperature_c", "temperatura_aire_c");
  copiar("rainfall", "lluvia");
  copiar("humidity_percent", "humedad_pct");
  copiar("wind_speed_mps", "viento_m_s");
  copiar("pressure_mbar", "presion_mbar");
  /* Esta fuente declara si llueve, no como esta el cielo. Decir «despejado»
     porque no llueve seria afirmar algo que nadie midio. */
  d.clima = w.rainfall === true ? "llueve"
          : w.rainfall === false ? "sin lluvia"
          : "sin declarar";
  d.icono = w.rainfall === true ? "lluvia" : "nube";
  d.frescura = w.weather_freshness || null;
  /* LA EDAD VIAJA CON LA FRESCURA. Se guardaba el estado y se tiraba el numero,
     de modo que el panel podia decir «viejo» pero no de cuando. Un estado sin su
     edad obliga a creerle al umbral sin poder juzgarlo. */
  d.edad_s = w.weather_age_seconds !== undefined ? w.weather_age_seconds : null;
  return d;
}

function pedirContextoDeCarrera(cuando, apertura) {
  const clave = claveDeSesionOpenF1(estado.abierta && estado.abierta.session_id);
  if (!clave) return;
  const numeros = numerosDePilotoDelContexto();
  if (!numeros.length) return;
  conCarga(["clima", "cronometraje"], () =>
    pedir("/racing/sessions/" + clave + "/context-at?timestamp=" +
          encodeURIComponent(cuando) + numeros.map(n => "&drivers=" + n).join(""),
          { senal: senalDeSesion() })
      .then(d => {
        if (!sigueVigente(apertura)) return;
        estado.contextoCarrera = contextoPorPiloto(d);
        const clima = climaDeLaCarrera(d && d.weather);
        if (clima) {
          estado.climaDeCarrera = clima;
          estado.climaMotivo = "";
          estado.disponibles.add("air_temperature");
          aplicarDisponibilidad();
          _firmaClima = "";
          pintarClima();
        }
        pintarCronometraje();
      })
      .catch(e => { if (!fueAnulada(e) && e instanceof TypeError) console.error(e); }));
}

/* ============================================================
   LA PUESTA A PUNTO
   ------------------------------------------------------------
   El paquete completo declara la condicion del vehiculo. Un valor observado en
   el menu no se presenta como aplicado hasta que exista rodaje posterior.
   ============================================================ */
const ROTULO_PUESTA = {
  aleron_delantero: "Alerón delantero",
  aleron_trasero: "Alerón trasero",
  diferencial_con_acelerador_pct: "Diferencial con acelerador",
  diferencial_sin_acelerador_pct: "Diferencial sin acelerador",
  caida_delantera_deg: "Caída delantera",
  caida_trasera_deg: "Caída trasera",
  convergencia_delantera_deg: "Convergencia delantera",
  convergencia_trasera_deg: "Convergencia trasera",
  suspension_delantera: "Suspensión delantera",
  suspension_trasera: "Suspensión trasera",
  barra_delantera: "Barra delantera",
  barra_trasera: "Barra trasera",
  altura_delantera: "Altura delantera",
  altura_trasera: "Altura trasera",
  presion_de_freno_pct: "Presión de freno",
  sesgo_de_freno_pct: "Sesgo de freno",
  freno_motor_pct: "Freno motor",
  presion_neumatico_trasero_izq_psi: "Presión trasera izq.",
  presion_neumatico_trasero_der_psi: "Presión trasera der.",
  presion_neumatico_delantero_izq_psi: "Presión delantera izq.",
  presion_neumatico_delantero_der_psi: "Presión delantera der.",
  lastre: "Lastre",
  combustible_inicial_kg: "Combustible inicial",
};

let _firmaPuesta = "";

/* POR QUE NO HAY REGLAJE, DICHO POR QUIEN LO SABE.
 *
 * Son dos ausencias distintas y la interfaz de consulta las separa: que la
 * fuente no publique configuracion del vehiculo, o que esta captura sea
 * anterior al paquete de reglaje normalizado. La primera es de la fuente; la
 * segunda es de la captura, y confundirlas le atribuye a F1 25 ---que si lo
 * publica--- una carencia que no tiene.
 *
 * Se lee de las dos rutas porque cada una lo llama distinto: `/contexto`, que
 * es la que el tablero consulta, manda `puesta_motivo`; `/puesta-a-punto`
 * manda `motivo_ausencia`. Buscar solo el segundo sobre la respuesta del
 * primero daba siempre `undefined`.
 */
function motivoDeLaPuesta(ctx) {
  if (!ctx) return "";
  return ctx.puesta_motivo || ctx.motivo_ausencia || "";
}

function pintarPuestaAPunto() {
  const cont = document.getElementById("lista-puesta");
  if (!cont) return;
  const d = estado.puesta;
  const campos = (d && d.campos) || [];
  const diferencias = (d && (d.diferencias_puesta || d.diferencias)) || [];
  /* El motivo entra en la firma: cuando no hay campos, es lo unico que cambia,
     y sin el el panel se quedaria con el texto de la sesion anterior. */
  const firma = [estadoSesion, JSON.stringify(campos), JSON.stringify(diferencias),
                 estado.puestaMotivo,
                 d && (d.puesta_asentada || d.asentada), tinta("--acento")].join("|");
  if (firma === _firmaPuesta) return;
  _firmaPuesta = firma;

  const motivo = document.getElementById("motivo-puesta");
  /* El respaldo es lo ultimo y no lo primero: la API ya dijo cual de las
     dos ausencias es, y solo si no contesto se cae en el texto generico. */
  if (motivo) motivo.textContent = estado.puestaMotivo ||
    motivoDeLaPuesta(d) ||
    "Esta fuente no publica configuración del vehículo.";

  const porClave = new Map(diferencias.map(x => [x.clave, x]));
  cont.innerHTML = campos.map(c => {
    const rot = ROTULO_PUESTA[c.clave] || c.clave;
    const valor = c.decodificado
      ? cifra(c.valor, c.clave === "sesgo_de_freno_pct" ? 0 : 0) + " " + (c.unidad || "")
      : '<span class="codigo-crudo">' + cifra(c.valor, 0) + '</span>';
    const comparada = porClave.get(c.clave);
    const referencia = comparada
      ? '<small class="valor-referencia">ref. ' + cifra(comparada.referencia, 0) + '</small>' : '';
    return '<div title="Canal: ' + c.canal + '"><dt>' + rot + '</dt><dd>' +
      valor + referencia + '</dd></div>';
  }).join("");

  const sinDecodificar = (d && d.sin_decodificar) || [];
  const nota = document.getElementById("nota-puesta");
  if (nota) {
    nota.textContent = !campos.length ? "" :
      ((d.puesta_asentada || d.asentada)
        ? "Configuración asentada: se observó rodaje posterior con este paquete completo."
        : "Configuración observada, todavía no confirmada por rodaje posterior.");
  }
  const bloqueReferencia = document.getElementById("referencia-puesta");
  if (bloqueReferencia) {
    bloqueReferencia.textContent = "";
    const referencia = d && (d.referencia_puesta || d.referencia);
    if (referencia) {
      bloqueReferencia.append(document.createTextNode(
        "Referencia: " + referencia.fuente.titulo + ". " + referencia.alcance + " "));
      try {
        const url = new URL(referencia.fuente.url);
        if (url.protocol === "https:" || url.protocol === "http:") {
          const enlace = document.createElement("a");
          enlace.href = url.href; enlace.target = "_blank"; enlace.rel = "noreferrer";
          enlace.textContent = "Ver fuente";
          bloqueReferencia.append(enlace);
        }
      } catch (_) { /* La referencia sigue identificada por titulo. */ }
    }
  }
  const cab = document.getElementById("canal-puesta");
  if (cab) cab.textContent = campos.length
    ? campos.length + " ajustes · " + ((d.puesta_asentada || d.asentada) ? "asentada" : "observada")
    : "—";
}

/* Cada aviso trae vuelta y metro; para colocarlo en la linea de tiempo hace
   falta pasarlo a fraccion de la sesion, que es lo unico que el reproductor
   entiende. */
/* DONDE, DENTRO DE SU VUELTA, VA UN AVISO. Devuelve una fraccion de 0 a 1.

   EL INSTANTE MANDA, PORQUE LA FUENTE LO DECLARA. `/avisos` trae `instante` en
   **cada** aviso. Reconstruirlo desde `vuelta` y `metro` era rehacer una cuenta
   que ya estaba hecha, y encima peor: `a.metro || 0` no distingue «en el metro
   cero» de «no se donde», y el metro cero es una posicion de la pista como
   cualquier otra. Es la misma familia que `Number(null)` dando cero donde el
   cero es un valor legitimo.

   MEDIDO el 2026-09-11: de los veinticuatro avisos de la practica de Catalunya,
   **veinte llegan con `metro: null`** ---los del aleron movil, la bandera
   amarilla--- y los catorce de la vuelta 1 terminaban apilados en la fraccion
   cero, todos en el mismo punto del arranque. El panel muestra los avisos cuyo
   `en` ya paso el cabezal, de modo que ubicarlos mal es mostrarlos cuando no
   ocurrieron.

   EL RELOJ ES EL QUE YA ESTABA. `utcDelCabezal` reparte linealmente la fraccion
   de una vuelta sobre su ventana `[desde_utc, hasta_utc]`; esta es la cuenta
   inversa, con la misma aproximacion declarada. No se introduce un segundo
   reloj que pueda desfasarse del primero.

   Y EL METRO SIGUE SIRVIENDO DE RESPALDO, para una fuente que ubique sus avisos
   sin decir cuando. Sin instante y sin metro no se inventa nada: el aviso queda
   al comienzo de su vuelta, que es lo unico que se sabe de el. */
function fraccionDentroDeLaVuelta(aviso, numero, largo) {
  const v = estado.vueltas.find(x => x.numero === numero);
  if (aviso.instante && v && v.desde_utc && v.hasta_utc) {
    const t = Date.parse(aviso.instante);
    const t0 = Date.parse(v.desde_utc);
    const t1 = Date.parse(v.hasta_utc);
    if (Number.isFinite(t) && Number.isFinite(t0) && Number.isFinite(t1) && t1 > t0) {
      return Math.max(0, Math.min(1, (t - t0) / (t1 - t0)));
    }
  }
  const metro = numeroMedido(aviso.metro);
  if (metro !== null) return Math.max(0, Math.min(1, metro / largo));
  return 0;
}

/* Donde cae cada aviso en la reproduccion. Lo usan las dos listas ---la
   derivada de la telemetria y la declarada por el control de carrera--- porque
   ubicar es la misma cuenta: se apoya en el instante que cada una trae, y dos
   copias de esta cuenta se desfasarian el dia que una cambie. */
function conFraccionDeSesion(lista) {
  const inicios = iniciosDeVuelta();
  const total = duracionSesionS();
  const largo = (PISTA.largo_m || 1);
  return lista.map(a => {
    const v = Math.max(1, Math.min(estado.vueltas.length || 1, a.vuelta || 1));
    const ini = inicios[v - 1] || 0;
    const parte = total > 0 ? duracionDeVuelta(v) / total : 0;
    return Object.assign({}, a, { en: ini + parte * fraccionDentroDeLaVuelta(a, v, largo) });
  }).sort((x, y) => x.en - y.en);
}

function ubicarAvisos(lista) {
  estado.avisos = conFraccionDeSesion(lista);
}

/* Se pide una vez por sesion y solo donde existe. `claveDeSesionOpenF1`
   contesta `null` para las otras dos fuentes, que no tienen control de carrera
   que declarar, y entonces no sale ninguna consulta. */
function pedirControlDeCarrera(sessionId, apertura) {
  const clave = claveDeSesionOpenF1(sessionId);
  if (!clave) return;
  conCarga("avisos", () =>
    pedir("/racing/sessions/" + clave + "/race-control", { senal: senalDeSesion() })
      .then(d => {
        if (!sigueVigente(apertura)) return;
        estado.controlDeCarreraCrudo = (d && d.eventos) || [];
        ubicarControlDeCarrera(estado.controlDeCarreraCrudo);
        render();
      })
      /* Un fallo aca no puede vaciar los avisos derivados: son dos listas y una
         no responde por la otra. Se anota y se sigue. */
      .catch(e => { if (!fueAnulada(e) && e instanceof TypeError) console.error(e); }));
}

function ubicarControlDeCarrera(eventos) {
  estado.controlDeCarrera = conFraccionDeSesion(avisosDelControlDeCarrera(eventos));
}

/* Con que señales se puede pintar el recorrido: las que este tablero sabe
   dibujar y esta sesion trajo con dato. La que manda es la respuesta, no una
   lista escrita aca. */
function senalesParaElRecorrido() {
  const clave = claveVehiculoPropio();
  const vuelta = vueltaEnFraccion(0);
  return canalesDeLaFuente().map(id => {
    /* `serieTemporal` contesta `null` o una serie con al menos una muestra:
       una columna que llego entera en nulos no arma serie. No hay un tercer
       caso que atajar. */
    const st = serieTemporal(id, vuelta, clave);
    if (!st) return null;
    /* SI LA SEÑAL SE MOVIO, SE SABE ANTES DE ELEGIRLA.
       Trece pastillas y en un minuto de autopista casi ninguna cambia: pintar
       el recorrido con una señal quieta lo deja de un color liso, que se lee
       igual que si el tablero no hubiera hecho nada. Que la pastilla lo diga de
       antemano evita tener que probarlas una por una para descubrirlo. */
    let mn = Infinity, mx = -Infinity;
    st.v.forEach(v => {
      if (v === null || !Number.isFinite(v)) return;
      if (v < mn) mn = v;
      if (v > mx) mx = v;
    });
    return { id: id, quieta: Number.isFinite(mn) && mn === mx, valor: mn };
  }).filter(Boolean);
}

/* La comprobacion contra las ruedas, en pantalla. Solo cuando la forma es
   derivada: sobre un circuito declarado no hay nada que contrastar. */
function pintarValidacionDeLaForma() {
  const el = document.getElementById("validacion-recorrido");
  if (!el) return;
  const texto = PISTA.derivado ? textoDeLaValidacion(PISTA.validacion) : "";
  if (el.textContent === texto) return;
  el.textContent = texto;
  el.dataset.alcanza = /coinciden en /.test(texto) ? "si" : "no";
}

/* El elector: una pastilla por señal, mas «ninguna». Se rehace solo cuando
   cambia lo que ofrece. */
function pintarElectorDelRecorrido() {
  const c = document.getElementById("elige-senal-recorrido");
  if (!c) return;
  if (!PISTA.derivado) { c.dataset.hay = "no"; c.innerHTML = ""; return; }
  const cuales = senalesParaElRecorrido();
  c.dataset.hay = cuales.length ? "si" : "no";
  const firma = cuales.map(s => s.id + (s.quieta ? "!" : "")).join(",") +
                "|" + (canalDelRecorrido || "");
  if (c.dataset.firma === firma) return;
  c.dataset.firma = firma;
  c.innerHTML = "";
  [null].concat(cuales).forEach(s => {
    const id = s && s.id;
    const m = id ? METRICAS.find(x => x.id === id) : null;
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = m ? m.rotulo : "Ninguna";
    if (s && s.quieta) {
      b.dataset.quieta = "si";
      b.title = sinCambiosEnElTramo(id, s.valor);
    }
    b.setAttribute("aria-pressed", String(canalDelRecorrido === id));
    b.addEventListener("click", () => {
      canalDelRecorrido = id;
      const capa = document.querySelector("#traza-por-senal");
      if (capa) capa.dataset.firma = "";
      c.dataset.firma = "";
      const pie = document.getElementById("leyenda-recorrido");
      if (pie && !id) pie.textContent = "";
      render();
    });
    c.appendChild(b);
  });
}

/* Pinta el recorrido por la señal elegida, encima del camino gris.

   Se rehace solo cuando cambia algo que lo afecta ---la señal, la sesion, el
   tema--- y no en cada cuadro: son doscientos nodos y el cabezal se mueve
   sesenta veces por segundo. */
function pintarTrazaPorSenal(linea) {
  const svg = linea.ownerSVGElement;
  if (!svg) return;
  let capa = svg.querySelector("#traza-por-senal");
  const canal = PISTA.derivado ? canalDelRecorrido : null;
  if (!canal) {
    if (capa) { capa.remove(); }
    linea.style.opacity = "";
    return;
  }
  if (!capa) {
    capa = document.createElementNS("http://www.w3.org/2000/svg", "g");
    capa.id = "traza-por-senal";
    svg.insertBefore(capa, linea.nextSibling);
  }
  const firma = [canal, PISTA.path.length, tinta("--acento"),
                 sesionAbierta].join("|");
  if (capa.dataset.firma === firma) return;
  capa.dataset.firma = firma;

  const valores = valoresSobreElRecorrido(canal);
  const tramos = tramosDelRecorrido(valores);
  if (!tramos.length) { capa.innerHTML = ""; linea.style.opacity = ""; return; }
  let mn = Infinity, mx = -Infinity;
  valores.forEach(v => {
    if (v === null || !Number.isFinite(v)) return;
    if (v < mn) mn = v;
    if (v > mx) mx = v;
  });
  /* El camino gris queda debajo y se atenua: sigue diciendo por donde se fue en
     los tramos donde la señal no llego. */
  linea.style.opacity = "0.35";
  /* Los dos extremos se leen una vez y no doscientas: `getComputedStyle` sobre
     la raiz por cada tramo es medir la hoja de estilos entera doscientas veces
     para obtener siempre lo mismo. */
  const extremos = extremosDeLaTraza();
/* Mas gruesa que el camino gris de abajo ---que mide 3--- por dos motivos: lo
     tapa en vez de dejar un halo, y un color necesita superficie para leerse.
     En un tramo casi recto la caja sobra de alto, asi que no cuesta nada. */
  const GRUESO_DE_LA_TRAZA = 5.5;
  capa.innerHTML = tramos.map(t =>
    '<path d="' + t.d + '" fill="none" stroke-width="' + GRUESO_DE_LA_TRAZA + '" stroke-linecap="round" ' +
    'stroke="' + tintaDelValor(t.valor, mn, mx, extremos) + '"></path>').join("");
  const pie = document.getElementById("leyenda-recorrido");
  if (pie) {
    pie.textContent = pieDelRecorrido(canal, mn, mx);
  }
}

/* ============================================================
   EL RECORRIDO, PINTADO POR LO QUE SE ESTABA MIDIENDO
   ------------------------------------------------------------
   Un recorrido dice por donde se fue. Con una señal encima dice **como** se
   fue: donde se levanto el pie, donde cargo el eje, donde la direccion se
   quedo quieta. Es la figura que un tramo de bus permite y que un grafico
   contra el tiempo no da, porque el tiempo no tiene forma.

   COMO SE ATAN LAS DOS COSAS. Cada punto del recorrido trae su instante, y cada
   señal se lee en un instante: se usa el **mismo** que ya comparten los
   instrumentos y el coche. No hay un segundo reloj ni una interpolacion nueva.

   QUE NO SE HACE. No se colorea por una escala absoluta inventada: los extremos
   son los de lo que se ve, y se escriben. Y no se pinta una señal escalonada
   con un degrade, porque entre pisado y suelto no hay medio pisado: esas se
   dibujan con dos tintas y nada en el medio.
   ============================================================ */

/* Cuantos tramos tiene la traza pintada. Doscientos sobre un dibujo de
   trescientos sesenta unidades de ancho es algo mas de un tramo por unidad:
   por debajo se ven los escalones, por encima son nodos que nadie distingue. */
const TRAMOS_DE_LA_TRAZA = 200;

/* La señal con la que se pinta el recorrido, o `null` para no pintarlo. */
let canalDelRecorrido = null;

/* El valor de `canal` en cada punto del recorrido, leido en su instante.
   Devuelve `null` cuando no hay con que: sin recorrido, sin origen declarado o
   sin serie temporal de esa señal. */
function valoresSobreElRecorrido(canal) {
  if (!PISTA.marcas_ms || !PISTA.origen_utc || !PISTA.mundo) return null;
  const origen = Date.parse(PISTA.origen_utc);
  if (!Number.isFinite(origen)) return null;
  const clave = claveVehiculoPropio();
  const st = serieTemporal(canal, vueltaEnFraccion(0), clave);
  if (!st || !st.t.length) return null;
  const escalonada = esCanalEscalonado(canal);
  return PISTA.marcas_ms.map(ms => {
    const t = origen + ms;
    return escalonada ? valorEscalonadoEn(st, t) : valorContinuoEn(st, t);
  });
}

/* Los tramos del recorrido con su valor: un objeto por tramo, con el camino
   que lo dibuja y el valor de la señal en el. Se reduce a `TRAMOS_DE_LA_TRAZA`
   quedandose con el **ultimo** punto de cada tramo, que es el que manda hasta
   el siguiente. */
function tramosDelRecorrido(valores) {
  if (!valores || !PISTA.mundo || PISTA.mundo.length < 2) return [];
  const n = PISTA.mundo.length;
  const paso = Math.max(1, Math.floor(n / TRAMOS_DE_LA_TRAZA));
  const tramos = [];
  let desde = 0;
  /* El ultimo corte es el ultimo punto y no el ultimo multiplo del paso: con
     2999 puntos y paso 14 el bucle terminaba en el 2996 y los tres finales se
     quedaban sin pintar, un cabo gris al final del recorrido. */
  const cortes = [];
  for (let i = paso; i < n - 1; i += paso) cortes.push(i);
  cortes.push(n - 1);
  for (const i of cortes) {
    const trozo = [];
    for (let k = desde; k <= i; k++) {
      const q = PISTA.proyectarMundo(PISTA.mundo[k][0], PISTA.mundo[k][1]);
      trozo.push((k === desde ? "M" : "L") + q[0].toFixed(1) + " " + q[1].toFixed(1));
    }
    /* El valor del tramo es el del punto donde termina: es el que estuvo
       vigente durante ese trozo del recorrido. */
    const v = valores[Math.min(i, valores.length - 1)];
    tramos.push({ d: trozo.join(" "), valor: v === undefined ? null : v });
    desde = i;
  }
  return tramos;
}

/* QUE DICE EL PIE DEL RECORRIDO, EN UNA FRASE.
   «De 0.00 a 0.00 pisado» es una forma pobre de decir que el pedal no se toco
   nunca: son dos cifras iguales que el ojo lee como un rango, y deja al que
   mira creyendo que el tablero no hizo nada. El pie del grafico ya tiene las
   palabras para esto ---«sin pisadas en este tramo»--- y son las mismas. */
function pieDelRecorrido(canal, mn, mx) {
  const m = METRICAS.find(x => x.id === canal);
  const rotulo = m ? m.rotulo : canal;
  if (!Number.isFinite(mn)) return rotulo + " · sin dato sobre este recorrido";
  if (mn === mx) return rotulo + " · " + sinCambiosEnElTramo(canal, mn);
  return rotulo + " · de " + cifra(mn, 2) + " a " + cifra(mx, 2) +
         " " + unidadDeCanal(canal);
}

/* De un valor a una tinta, entre los extremos de lo que se ve.

   UNA ESCALA DE DOS COLORES Y NO UN ARCOIRIS: un arcoiris ordena mal ---nadie
   sabe si el verde es mas que el naranja--- y una rampa de un extremo apagado a
   uno vivo se lee sola.

   POR OPACIDAD NO SE DISTINGUE NADA. Esto iba de `--linea-fuerte` a `--acento`,
   y en el tema oscuro `--linea-fuerte` **es** el acento al 34 % de opacidad: la
   escala entera era un mismo violeta cambiando de transparencia sobre un fondo
   oscuro, en una linea de tres pixeles. No habia dos colores; habia uno.
   Ahora va de `--texto-tenue` ---un gris azulado apagado--- a `--acento-vivo`,
   los dos opacos: cambia el tono, la saturacion y la claridad a la vez.

   Y SE RESUELVE EN JAVASCRIPT. Un `color-mix(... var(--acento) ...)` metido en
   un atributo de presentacion depende de que el navegador resuelva variables
   ahi, cosa que no todos hacen; si no la resuelve, el valor es invalido y el
   trazo no se dibuja. Mezclando aca sale un `rgb()` concreto que no depende de
   nada. */
function extremosDeLaTraza() {
  return { baja: _rgbDe(tinta("--texto-tenue")), alta: _rgbDe(tinta("--acento-vivo")) };
}

function tintaDelValor(v, mn, mx, extremos) {
  const e = extremos || extremosDeLaTraza();
  if (v === null || v === undefined || !Number.isFinite(v)) return tinta("--linea");
  const u = mx > mn ? Math.max(0, Math.min(1, (v - mn) / (mx - mn))) : 0.5;
  const c = [0, 1, 2].map(i => Math.round(e.baja[i] + (e.alta[i] - e.baja[i]) * u));
  return "rgb(" + c[0] + ", " + c[1] + ", " + c[2] + ")";
}

/* Un color de la hoja de estilos a sus tres componentes. Acepta lo que
   `getComputedStyle` devuelve ---`#rgb`, `#rrggbb`, `rgb(...)`, `rgba(...)`,
   y la forma con espacios que usan los navegadores nuevos---. La opacidad se
   descarta a proposito: la rampa se hace con color, no con transparencia. */
function _rgbDe(texto) {
  const s = String(texto || "").trim();
  if (s[0] === "#") {
    const h = s.length === 4
      ? s[1] + s[1] + s[2] + s[2] + s[3] + s[3]
      : s.slice(1, 7);
    return [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16) || 0);
  }
  const n = s.match(/-?[\d.]+/g);
  return n && n.length >= 3 ? n.slice(0, 3).map(x => Math.round(parseFloat(x))) : [128, 128, 128];
}

/* DONDE ESTABA EL VEHICULO EN ESTE INSTANTE, SOBRE EL RECORRIDO DERIVADO.

   El coche de una sesion con distancia se coloca por su metro. Acá no hay
   metro: hay una forma con una marca de tiempo por punto. Se busca el punto por
   su instante ---busqueda binaria, esto corre una vez por cuadro--- y se lo
   proyecta con la misma transformacion del camino dibujado.

   Colocarlo por la fraccion del cabezal habria estado casi bien y por casualidad:
   la fraccion es de tiempo y el camino esta parametrizado por longitud, y las
   dos coinciden solo si la velocidad es constante. En este tramo casi lo es, que
   es justo lo que haria pasar el error por bueno.

   `null` cuando no se puede ubicar: sin recorrido, sin marcas o sin origen
   declarado. */
function puntoDelBusEn(tUtcMs) {
  if (!PISTA.marcas_ms || !PISTA.marcas_ms.length || !PISTA.proyectarMundo) return null;
  if (!PISTA.origen_utc || tUtcMs === null || tUtcMs === undefined) return null;
  const origen = Date.parse(PISTA.origen_utc);
  if (!Number.isFinite(origen)) return null;
  const i = _indiceEnElRecorrido(tUtcMs - origen);
  if (i === null) return null;
  const q = PISTA.proyectarMundo(PISTA.mundo[i][0], PISTA.mundo[i][1]);
  return { x: q[0], y: q[1], indice: i };
}

/* El ultimo punto medido en ese instante o antes; `null` si el instante es
   anterior al primero, porque ahi el vehiculo no estaba en ningun lado todavia. */
function _indiceEnElRecorrido(tMs) {
  const m = PISTA.marcas_ms;
  if (!(tMs >= m[0])) return null;
  let lo = 0, hi = m.length - 1;
  while (lo < hi) {
    const medio = (lo + hi + 1) >> 1;
    if (m[medio] <= tMs) lo = medio; else hi = medio - 1;
  }
  return lo;
}

/* EL RECORRIDO DEL BUS: DERIVADO, Y DICHO.
   No es una posicion medida. Se integra velocidad y velocidad de guiñada, de
   modo que la forma es fiel pero su orientacion absoluta y su sitio en el mundo
   no son recuperables ---la respuesta lo declara y ese texto se muestra---.

   Cada punto viene con el instante en que el vehiculo estuvo ahi, en
   milisegundos desde el arranque del segmento. Es lo que permite colocar el
   coche sobre el recorrido con el **mismo** instante que ya comparten los
   instrumentos, y lo que permite pintar la traza por lo que se estaba midiendo. */
function pedirRecorridoDelBus() {
  if (!estado.abierta) return;
  const apertura = aperturaVigente();
  TESTIGO.trazadosPedidos++;
  conCarga("trazado", () =>
  pedir("/can/recorrido/" + encodeURIComponent(estado.abierta.session_id),
        { senal: senalDeSesion() })
    .then(r => {
      if (!sigueVigente(apertura)) return;
      const puntos = (r && r.puntos) || [];
      if (puntos.length < 3) { TESTIGO.trazadosDescartados++; return; }
      TESTIGO.trazadosAplicados++;
      estado.trazado = t;
      PISTA = armarPista(t, CURVAS);
      const svg = document.getElementById("linea-pista");
      if (svg && svg.ownerSVGElement) delete svg.ownerSVGElement.dataset.reserva;
      const g = document.getElementById("marcas-pista");
      if (g) g.dataset.firma = "";
      render();
    })
    .catch(e => { if (e instanceof TypeError) console.error(e); }));
}

/* EL TRAZADO SE DIBUJA CON UNA VUELTA COMPLETA Y SIN SALTOS.
   Sin elegir vuelta, la API contesta con la primera, y si esa vuelta tiene un
   salto de horas ---dos cargas de la misma sesion pegadas--- el recorrido sale
   con tramos que no se recorrieron: el circuito se ve deformado. Se elige la
   primera vuelta que sea continua y completa; si no hay ninguna, se pide sin
   elegir y se declara. */
/* ============================================================
   EL TRAZADO, GRANDE
   ------------------------------------------------------------
   El panel chico entra en una columna de la cabina, y ahi conviven quince
   numeros de curva, dos rayas de sector y hasta seis coches. Alcanza para
   saber donde esta el coche; no alcanza para leer el circuito.

   REUSA LA MISMA GEOMETRIA, ESCALADA. El `viewBox` es el mismo ---360 por
   170--- asi que el dibujo grande es el mismo camino, la misma proyeccion y
   las mismas rayas, agrandados por el navegador. No se recalcula nada: una
   segunda version de la geometria podria discrepar de la primera, y entonces
   habria dos circuitos distintos para la misma vuelta.

   LO QUE SI CAMBIA ES LO QUE ENTRA. Con espacio, el nombre de cada curva se
   escribe sobre el dibujo; en el panel chico se superponen ---las dobles caen
   a pocos metros una de otra--- y por eso alli viven en el globo.
   ============================================================ */
function trazadoGrandeAbierto() {
  const v = document.getElementById("velo-trazado");
  return !!v && v.dataset.abierto === "si";
}

function abrirTrazadoGrande() {
  const v = document.getElementById("velo-trazado");
  if (!v) return;
  v.dataset.abierto = "si";
  pintarTrazadoGrande();
  const cerrar = document.getElementById("btn-cerrar-trazado");
  if (cerrar) cerrar.focus();
}

/* Los mismos vehiculos que el resto del tablero, con el mismo color. Un piloto
   que aca fuera de otro color que en las graficas obligaria a recordar dos
   leyendas para mirar una sola carrera. */
function pintarEligePilotosDelTrazado() {
  const c = document.getElementById("elige-pilotos-trazado");
  const grupo = document.getElementById("grupo-pilotos-trazado");
  if (!c) return;
  if (grupo) grupo.hidden = AUTOS.length <= 1;
  c.innerHTML = "";
  AUTOS.forEach(a => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = a.nombre;
    b.style.setProperty("--tinta-piloto", a.color);
    b.setAttribute("aria-pressed", seleccion.has(a.id) ? "true" : "false");
    b.addEventListener("click", () => {
      if (seleccion.has(a.id)) {
        // No se puede apagar el ultimo: un trazado sin ningun coche no dice
        // donde esta nadie, y el boton parecería roto.
        if (seleccion.size > 1) seleccion.delete(a.id);
      } else {
        seleccion.add(a.id);
      }
      pintarEligePilotosDelTrazado();
      pintarTrazadoGrande();
      render();
    });
    c.appendChild(b);
  });
}

/* LA ESTRUCTURA SE REHACE CUANDO CAMBIA; LOS COCHES, EN CADA CUADRO.
   Es el mismo reparto que el panel chico: rehacer el camino, quince nombres de
   curva y tres rayas sesenta veces por segundo es rehacer medio centenar de
   nodos para que ninguno cambie. Lo unico que cambia con el reloj es donde
   esta cada coche. */
function pintarTrazadoGrande() {
  const svg = document.getElementById("trazado-grande");
  if (!svg || !trazadoGrandeAbierto()) return;
  const NS = "http://www.w3.org/2000/svg";

  const firma = [fuente, (PISTA.path || "").length, PISTA.vuelta,
                 (PISTA.sectores || []).length, CURVAS.length,
                 [...seleccion].join(","), tinta("--acento")].join("|");
  if (svg.dataset.firma === firma) { moverCochesDelTrazadoGrande(); return; }
  svg.dataset.firma = firma;
  svg.innerHTML = "";

  const sub = document.getElementById("sub-trazado");
  if (sub) {
    sub.textContent = PISTA.largo_m
      ? " · " + cifra(PISTA.largo_m, 0) + " m" +
        (PISTA.vuelta ? " · vuelta " + PISTA.vuelta : "")
      : "";
  }

  if (!PISTA.path) {
    svg.dataset.firma = "";
    const aviso = document.createElementNS(NS, "text");
    aviso.setAttribute("x", "180"); aviso.setAttribute("y", "85");
    aviso.setAttribute("class", "rotulo-sector");
    aviso.textContent = "Sin trazado para esta sesión.";
    svg.appendChild(aviso);
    return;
  }

  const linea = document.createElementNS(NS, "path");
  linea.setAttribute("class", "trazado");
  linea.setAttribute("d", PISTA.path);
  svg.appendChild(linea);

  // Las rayas de sector, con la misma funcion que el panel chico.
  marcasDeSector(PISTA.sectores, PISTA.puntos, PISTA.proyectarMundo).forEach(m => {
    const raya = document.createElementNS(NS, "line");
    raya.setAttribute("class", "raya-sector");
    raya.setAttribute("x1", m.x1); raya.setAttribute("y1", m.y1);
    raya.setAttribute("x2", m.x2); raya.setAttribute("y2", m.y2);
    svg.appendChild(raya);
    const rot = document.createElementNS(NS, "text");
    rot.setAttribute("class", "rotulo-sector grande");
    rot.setAttribute("x", m.tx); rot.setAttribute("y", m.ty);
    rot.textContent = "S" + m.sector +
      (m.desde_m !== null && m.desde_m !== undefined ? " · " + cifra(m.desde_m, 0) + " m" : "");
    svg.appendChild(rot);
  });

  const largo = linea.getTotalLength ? linea.getTotalLength() : 0;

  /* LAS CURVAS, NUMERADAS. EL NOMBRE, AL APUNTAR.
     Primero se escribian los quince nombres sobre el dibujo, y con quince
     nombres encima el circuito deja de verse: lo que uno mira en un trazado es
     la forma y donde esta el coche, y el nombre solo cuando se pregunta «que
     curva es esta». Es la misma decision que el panel chico ya habia tomado, y
     aca hay que tomarla igual porque el problema no era el espacio.

     Se reusa la clase `marca-curva`, que es la que el globo escucha. */
  if (largo && CURVAS.length && PISTA.largo_m) {
    CURVAS.forEach((cu, i) => {
      const f = Math.max(0, Math.min(1, cu.metro_medido / PISTA.largo_m));
      const q = linea.getPointAtLength(largo * f);
      const marca = document.createElementNS(NS, "g");
      marca.setAttribute("class", "marca-curva");
      marca.setAttribute("tabindex", "0");
      marca.setAttribute("role", "img");
      marca.setAttribute("aria-label", "Curva " + (i + 1) + ": " + cu.nombre);
      marca.dataset.nombre = cu.nombre;
      marca.dataset.numero = String(i + 1);
      const punto = document.createElementNS(NS, "circle");
      punto.setAttribute("class", "punto-curva-grande");
      punto.setAttribute("cx", q.x.toFixed(2));
      punto.setAttribute("cy", q.y.toFixed(2));
      punto.setAttribute("r", "2.4");
      const num = document.createElementNS(NS, "text");
      num.setAttribute("class", "numero-curva-grande");
      num.setAttribute("x", q.x.toFixed(2));
      num.setAttribute("y", q.y.toFixed(2));
      num.textContent = String(i + 1);
      const comoSeLlama = document.createElementNS(NS, "title");
      comoSeLlama.textContent = (i + 1) + ". " + cu.nombre;
      marca.appendChild(comoSeLlama);
      marca.appendChild(punto);
      marca.appendChild(num);
      svg.appendChild(marca);
    });
  }

  /* EL COCHE SE TIENE QUE DISTINGUIR DE UNA CURVA, Y ANTES NO SE DISTINGUIA:
     los dos eran un circulo del mismo color y del mismo tamaño. Lleva su sigla
     encima, siempre visible ---no al apuntarlo---, porque saber cual coche es
     cual es la pregunta permanente de un trazado con varios pilotos, no una
     consulta ocasional como el nombre de una curva.

     Es la misma estructura que el panel chico: circulo con la tinta del
     vehiculo, tres letras arriba y la identidad entera en el `<title>`. */
  const siglas = [];
  [...seleccion].forEach(id => {
    const a = AUTOS.find(x => x.id === id);
    if (!a) return;
    const grupo = document.createElementNS(NS, "g");
    grupo.setAttribute("class", "auto-grande");
    grupo.dataset.clave = a.clave || id;
    /* La tinta va una vez en el grupo y de ahi la toman el punto y la sigla.
       Puesta suelta en cada uno, el estado estimado ---que vacia el relleno---
       se quedaba sin color y el punto desaparecia sobre el fondo. */
    grupo.style.setProperty("--tinta-auto", tinta(a.tinta));
    const c = document.createElementNS(NS, "circle");
    c.setAttribute("class", "coche-grande");
    c.setAttribute("r", a.propio ? "3.4" : "2.8");
    const quien = document.createElementNS(NS, "title");
    quien.textContent = a.completa;
    grupo.appendChild(quien); grupo.appendChild(c);
    svg.appendChild(grupo);
    /* LA SIGLA VA EN OTRA CAPA, ENCIMA DE TODOS LOS PUNTOS. Dentro del grupo,
       el circulo del coche siguiente la tapaba: con tres pilotos juntos ---y
       juntos es justamente cuando hace falta distinguirlos--- se leian dos
       siglas de tres. El halo del texto solo lo despega de lo que se dibujo
       antes que el, no de lo que viene despues. */
    const rot = document.createElementNS(NS, "text");
    rot.setAttribute("class", "sigla-auto-grande");
    rot.dataset.clave = a.clave || id;
    rot.style.setProperty("--tinta-auto", tinta(a.tinta));
    rot.textContent = a.etiqueta;
    siglas.push(rot);
  });
  siglas.forEach(s => svg.appendChild(s));
  moverCochesDelTrazadoGrande();

  /* DE DONDE SALE CADA COSA DEL DIBUJO, ESCRITO DEBAJO. El trazo y las rayas
     son medicion; el nombre de una curva es anotacion externa citada. Verlas
     juntas sin decirlo le daria a las dos el respaldo de una sola. */
  const nota = document.getElementById("nota-trazado");
  if (nota) {
    const partes = [];
    if (PISTA.sectoresOrigen) partes.push("<b>Sectores:</b> " + textoSeguro(PISTA.sectoresOrigen) + ".");
    if (CURVAS.length) {
      partes.push("<b>Nombres de curva:</b> anotación externa citada; el metro " +
                  "en que se ubica cada una es medido sobre la vuelta.");
    }
    nota.innerHTML = partes.join(" ");
  }
}

/* MOVER LOS COCHES DEL TRAZADO GRANDE.
   Lo unico que cambia con el reloj. Se llama desde `moverCabezal`, al lado de
   `pintarPista`, porque ese es el camino que la reproduccion recorre en cada
   cuadro: `pintarTrazas` **no esta en el**, y engancharse ahi ---que fue el
   primer intento--- dejaba el coche quieto en el trazado grande mientras el
   panel chico lo movia.

   EL RESPALDO ES EL MISMO QUE EL DEL PANEL CHICO. Sin posicion medida el coche
   se ubica por la fraccion recorrida sobre el camino dibujado, y se dibuja
   hueco: no es lo mismo, y el dibujo no puede afirmar que midio algo que
   estimo. */
function moverCochesDelTrazadoGrande() {
  const svg = document.getElementById("trazado-grande");
  if (!svg || !trazadoGrandeAbierto()) return;
  const camino = svg.querySelector("path.trazado");
  if (!camino) return;
  const t = instante();
  const largo = camino.getTotalLength ? camino.getTotalLength() : 0;
  const frac = Math.max(0, Math.min(1, t.fraccion || 0));
  svg.querySelectorAll(".auto-grande").forEach(grupo => {
    const medido = puntoMedidoDe(grupo.dataset.clave, t.tUtcMs);
    const q = medido || (largo ? camino.getPointAtLength(largo * frac) : null);
    if (!q) return;
    const c = grupo.querySelector("circle");
    const px = q.x.toFixed(2), py = q.y.toFixed(2);
    c.setAttribute("cx", px); c.setAttribute("cy", py);
    // La sigla vive en la capa de arriba: se la busca por la clave del coche.
    const rot = svg.querySelector(
      '.sigla-auto-grande[data-clave="' + grupo.dataset.clave + '"]');
    if (rot) {
      rot.setAttribute("x", px);
      rot.setAttribute("y", (q.y - ALTURA_SIGLA_GRANDE).toFixed(2));
    }
    /* Se declara despues de colocarlo: hasta aca no se sabia si la coordenada
       medida estaba disponible para este instante. */
    grupo.dataset.estimada = medido ? "no" : "si";
    /* La sigla esta en la capa de arriba y no dentro del grupo, asi que no
       hereda el estado: lo lleva ella tambien. */
    if (rot) rot.dataset.estimada = medido ? "no" : "si";
    grupo.setAttribute("aria-label",
      medido ? "" : "posición estimada por tiempo, no medida");
  });
}

/* LA PISTA SE ARMA EN UN SOLO SITIO.
   ---------------------------------------------------------------------
   Habia dos. `cargarDatosDeSesion` armaba una con lo que ya tenia en la mano y
   `pedirTrazado` armaba otra al volver su consulta, las dos desde la **misma**
   respuesta de `/trazado`. La segunda era la completa; la primera se olvidaba
   de `proyectarMundo`, de `invertirY` y de la vuelta, y se quedaba con las
   curvas vacias.

   Mientras lo unico que se dibujaba era la linea, las dos servian y la
   diferencia no se veia. Al agregar los sectores dejo de servir: el dibujo
   salia sin rayas porque la copia que ganaba no los traia, y no habia forma de
   saber cual de las dos habia ganado.

   Es el mismo defecto que este tablero ya tuvo dos veces ---`estado.clima` y el
   pie de avisos---: dos escritores para un mismo dato. El arreglo es el mismo,
   y es estructural: un solo constructor, y todos los sitios lo llaman.

   Y quedo a medias: eran **tres** sitios, no dos, y `pedirTrazado` siguio
   armandolo a mano hasta el 2026-09-11 mientras este comentario afirmaba lo
   contrario. Por eso la prueba de `tests/js/lo_que_dice_el_trazado.js` cuenta
   los constructores sobre el `app.js` publicado: un comentario que afirma una
   invariante no la sostiene. */
function armarPista(t, curvas) {
  const invertir = /invertir/i.test(t.para_dibujarlo || "") &&
                   !/no invertir/i.test(t.para_dibujarlo || "");
  /* Los tramos que el vehiculo no pudo haber recorrido se marcan antes de
     armar el camino: la posicion se midio y se conserva, lo que se deja de
     afirmar es el trazo entre ella y la anterior. Ver `marcarSaltos`. */
  const puntos = marcarSaltos(t.puntos, t.dt_s, t.velocidad_kmh);
  const armado = trazadoAPath(puntos, invertir);
  return {
    path: armado.path,
    largo_m: t.largo_m,
    desnivel_m: t.desnivel_m,
    muestras: t.muestras_originales,
    vuelta: t.vuelta,
    curvas: curvas || [],
    /* La transformacion que llevo estos puntos al dibujo, guardada. La armaba
       `trazadoAPath` y uno de los dos sitios la tiraba, de modo que una
       coordenada medida no se podia poner sobre el trazo aunque se tuviera. */
    proyectarMundo: armado.proyectarMundo,
    /* LOS SECTORES SON MEDICION, A DIFERENCIA DEL NOMBRE DE UNA CURVA. El
       nombre no esta en ningun canal y viene del catalogo externo; el limite de
       sector si esta en el dato, y cada fuente lo alcanza por su dimension
       ---el simulador lo declara en cada muestra, la fuente deportiva por las
       duraciones de la vuelta---. La respuesta trae escrito cual de las dos. */
    sectores: t.sectores || [],
    sectoresOrigen: t.sectores_origen || "",
    /* Los puntos crudos, para poder orientar la marca de sector: una raya que
       marca un limite tiene que cruzar la pista, y para eso hace falta saber
       hacia donde va la pista en ese punto. Van los **marcados**, que son los
       mismos con la marca de corte: los sectores se ubican por indice y dos
       arreglos distintos se desalinearian. */
    puntos: puntos || [],
    invertirY: invertir,
  };
}

/* DONDE Y COMO CRUZA CADA RAYA DE SECTOR.
   ---------------------------------------------------------------------
   Una raya que marca un limite tiene que **cruzar** la pista, no correr a lo
   largo de ella: puesta en cualquier direccion se lee como un tramo del
   circuito y no como una division. La direccion sale de por donde va la pista
   en ese punto, que se saca de los dos puntos vecinos del propio trazado.

   Se extrae del dibujo para poder ejercerla: lo unico que decide es geometria,
   y eso se puede comprobar sin un navegador.

   EL PRIMER SECTOR NO LLEVA RAYA. Su limite es la linea de meta, que es donde
   el trazado empieza y termina: dibujarla ahi marcaria el corte del dibujo y
   no un limite de sector, y ademas caeria encima del final del lazo. */
const LARGO_RAYA_SECTOR = 7;
/* Cuantas muestras se miran a cada lado buscando una que este en otro sitio.
   Pocas a proposito: mas lejos la direccion ya no es la de ese punto. */
const VECINOS_PARA_LA_DIRECCION = 6;
/* Cuanto sube la sigla sobre el punto del coche, en unidades del dibujo. */
const ALTURA_SIGLA_GRANDE = 4.4;

function marcasDeSector(sectores, puntos, proyectar) {
  if (!proyectar || !puntos || puntos.length < 2) return [];
  const salida = [];
  (sectores || []).forEach(s => {
    const i = s.indice;
    /* EL LIMITE DEL PRIMER SECTOR TAMBIEN SE MARCA, y antes no.
       El razonamiento era que ahi el dibujo empieza y termina, de modo que la
       raya marcaria el corte del lazo. Pero el corte del lazo **es** la linea
       de meta: no es un artefacto del dibujo, es el sitio del circuito donde
       la vuelta empieza y donde empieza el sector 1. Callarla dejaba un
       circuito con dos de sus tres divisiones, que se lee como que falta una.

       Lo que si hace falta es una direccion, y en el primer punto se toma la
       del tramo que sigue. */
    if (i < 0 || i >= puntos.length) return;
    /* EL VECINO INMEDIATO PUEDE SER EL MISMO PUNTO, y entonces no hay
       direccion. Pasa de verdad: en Silverstone, con el coche detenido en la
       parrilla y la fuente publicando a 3,7 Hz, las dos primeras muestras del
       trazado son identicas ---[-1040, 2156] las dos--- y la raya del sector 1
       se descartaba por falta de direccion. No se veia como un defecto: se
       veia como un circuito con dos divisiones en vez de tres.

       Asi que se busca hacia afuera el primer vecino que **este en otro
       sitio**. Unas pocas muestras alcanzan; si en ese entorno no hay ninguna,
       es que ahi el coche no se movio y no hay direccion que dibujar. */
    const vecino = (desde, paso) => {
      for (let k = desde + paso; k >= 0 && k < puntos.length &&
                                 Math.abs(k - desde) <= VECINOS_PARA_LA_DIRECCION;
           k += paso) {
        if (puntos[k][0] !== puntos[desde][0] || puntos[k][1] !== puntos[desde][1]) {
          return puntos[k];
        }
      }
      return null;
    };
    const antes = vecino(i, -1) || puntos[i];
    const despues = vecino(i, 1) || puntos[i];
    /* `proyectarMundo` devuelve un **arreglo** `[x, y]`, no un objeto. Leerlo
       como `.x` daba `undefined`, la resta daba `NaN`, y `if (!largo)` lo
       descartaba en silencio: cero rayas y ningun error. */
    const a = proyectar(antes[0], antes[1]);
    const b = proyectar(despues[0], despues[1]);
    const c = proyectar(puntos[i][0], puntos[i][1]);
    const dx = b[0] - a[0], dy = b[1] - a[1];
    const largo = Math.hypot(dx, dy);
    if (!largo) return;
    // La normal de la direccion de marcha, escalada a la mitad a cada lado.
    const nx = -dy / largo * (LARGO_RAYA_SECTOR / 2);
    const ny = dx / largo * (LARGO_RAYA_SECTOR / 2);
    salida.push({
      sector: s.sector, desde_m: s.desde_m,
      x1: +(c[0] - nx).toFixed(2), y1: +(c[1] - ny).toFixed(2),
      x2: +(c[0] + nx).toFixed(2), y2: +(c[1] + ny).toFixed(2),
      // El rotulo va del lado de afuera de la raya, para no pisar el trazo.
      tx: +(c[0] + nx * 1.9).toFixed(2), ty: +(c[1] + ny * 1.9).toFixed(2),
    });
  });
  return salida;
}

function pedirTrazado(ruta) {
  /* EL BUS NO PUBLICA COORDENADAS, Y AUN ASI TIENE UNA FORMA.
     `/trazado` sale de `world_position_*`, que la simulacion declara y el bus
     no: para una sesion del bus contesta vacio y el panel se quedaba con el
     rotulo «recorrido reconstruido» y nada debajo ---una etiqueta sin nada
     detras---. La forma existe: se obtiene integrando velocidad y guinada, y
     `/can/recorrido` la calcula desde hace tiempo. Nadie se la pedia.

     SE PREGUNTA POR LA POSICION Y NO POR LA DISTANCIA. Son dos carencias
     distintas: OpenF1 no tiene metro medido y si tiene `track_position_*`, de
     modo que su trazado sale de `/trazado` como siempre. */
  if (!hayCoordenadasMedidas()) { pedirRecorridoDelBus(); return; }
  const buena = estado.vueltas.find(v => v.continua !== false && v.completa);
  const cual = buena ? "&vuelta=" + buena.numero : "";
  /* De quien es el recorrido. La fuente deportiva no publica quien conduce
     ---no tiene nada como `player_car_index`--- y sin decirlo el punto de
     acceso no puede saber de cual de los tres pilotos dibujar. */
  const deQuien = claveVehiculoPropio()
    ? "&vehiculo=" + encodeURIComponent(claveVehiculoPropio()) : "";
  TESTIGO.trazadosPedidos++;
  conCarga("trazado", () =>
  pedir(ruta + "/trazado?puntos=600" + cual + deQuien + sufijoDeCorrida(true),
        { senal: senalDeSesion() })
    .then(t => {
      if (!t || !t.puntos || !t.puntos.length) { TESTIGO.trazadosDescartados++; return; }
      TESTIGO.trazadosAplicados++;
      estado.trazado = t;
      /* EL TERCER SITIO. `armarPista` se extrajo porque habia dos copias y la
         que ganaba no traia los sectores; este quedo armando el objeto a mano
         igual, y el comentario de `armarPista` afirmaba que no quedaba
         ninguno. Hoy los campos coinciden uno a uno ---se comprobo--- asi que
         no llego a divergir, pero es exactamente la posicion desde la que ya
         se rompio una vez: el proximo campo que se agregue alla no llega aca. */
      PISTA = armarPista(t, CURVAS);
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
/* ============================================================
   QUE UNA FUENTE DECLARE VUELTAS Y QUE MIDA METROS SON DOS PREGUNTAS
   ------------------------------------------------------------
   Estaban respondidas con una sola. `hayVueltas` exigia ademas eje de
   distancia, de modo que OpenF1 se presentaba como «tramo» aunque declara sus
   **cincuenta y dos** vueltas por reloj ---cada una con su instante de inicio,
   su fin y su duracion medida---, el tablero le pida los datos vuelta por
   vuelta y el propio encabezado diga «VUELTA 1 DE 52». Tres centimetros mas
   abajo, el reproductor decia «tramo»: la misma sesion contando dos cosas
   distintas sobre si misma.

   Que no haya metro medido no borra las vueltas: son de la fuente, no del eje.
   Lo que la distancia gobierna es **escribir un metro**, y eso se pregunta
   donde se escribe uno, que es un solo sitio en el transporte.

   LO QUE SI HAY QUE DISTINGUIR YA ESTABA MARCADO. Cuando una fuente no declara
   vueltas ---el bus, que entrega un minuto de ruta--- este tablero se arma un
   tramo unico para poder compartir cabezal e interpolacion, y lo declara:
   `tramo_temporal`. Ese no es una vuelta y la interfaz nunca lo llama asi. La
   pregunta correcta es entonces si queda alguna vuelta que la fuente haya
   declarado de verdad.
   ============================================================ */
function hayVueltas() { return estado.vueltas.some(v => !v.tramo_temporal); }

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
      gVert: leer("gvert"), yaw: leer("yaw"),
      tempMotor: leer("engineTemp"), ers: leer("ers"),
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

  /* LA ABSCISA DE PRESENTACION TAMBIEN SALE DEL INSTANTE.
     Es la que corre la ventana de los graficos y la que coloca el cabezal en
     modo vuelta completa. Sacarla de la muestra discreta de velocidad dejaba la
     ventana anclada a un metro que solo cambiaba cada 425 ms ---y, en la fuente
     que mide contra el reloj y no contra el metro, cada 265 ms---. No se
     interpola sobre el cruce de meta: cuando la abscisa baja, la vuelta se
     cerro. */
  const metroSuave = abscisaContinua(vuelta, propioAqui, tUtc);

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
    yaw: leer("yaw"),
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

  /* ESCUCHAR NO ES REPRODUCIR, Y POR ESO NO LLEVA REPRODUCTOR.
     Escuchando cae del lado del vivo: no hay nada que recorrer todavia, y
     ofrecer un cabezal, una velocidad y un boton de reproducir sobre una sesion
     que no existe invita a manipular algo que no esta. Lo que se recorre es lo
     que ya se guardo, y para eso esta «abrir sesion guardada». */
  const modo = (estadoSesion === "vivo" || estadoSesion === "escuchando") ? "vivo"
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
      estadoSesion === "escuchando"
        ? "sin telemetría todavía · en cuanto el juego emita, el tablero se llena solo"
        : (partes.length ? partes.join(" · ") : "esperando al difusor…");
    return;
  }
  if (modo === "vacio") { detener(); return; }

  /* ============================================================
     EL AVISO QUE EXPLICABA UN ESTADO QUE YA NO EXISTE
     ------------------------------------------------------------
     Aca iba un parrafo de tres renglones ---«reproduccion temporal de tal
     fuente: las señales avanzan contra el reloj de la captura, no se inventan
     vueltas ni distancia»--- que ocupaba un tercio de la barra. Nacio cuando
     una fuente sin metro medido **no tenia reproduccion**: el texto iba en el
     sitio de los mandos, en vez de dejarlos ofreciendo algo que fallaba al
     primer paso.

     Hoy los mandos funcionan, asi que el parrafo ya no reemplazaba nada: se
     habia quedado al lado de lo que explicaba que no se podia hacer. Y desde
     que las vueltas declaradas se cuentan, la mitad de la frase era falsa: la
     barra de al lado dice «Vuelta 30/52».

     Lo que el aviso queria decir lo dicen los propios mandos, que es donde se
     lee sin leer un parrafo: la ventana se mide en segundos y no en metros, y
     el transporte cuenta reloj de sesion. Y lo que la fuente no sostiene esta
     escrito al pie, que es donde se puede comparar con las otras dos. */

  const t = instante();
  const s = serieDelPropio(t.vuelta);
  const total = s.length ? s[s.length - 1][0] : 0;
  const dur = duracionSesionS();

  // Lo primero que se lee es en que vuelta va, porque es lo que ubica todo
  // lo demas. El metro y el reloj acompañan.
  document.getElementById("tr-posicion").textContent = hayVueltas()
    ? "Vuelta " + rotuloDeVuelta(t)
    : relojDeSesion(t.segundos);
  /* EL METRO SOLO SE ESCRIBE DONDE SE MIDIO. En una fuente que declara vueltas
     pero no distancia, `t.metro` lleva el reloj del tramo: imprimirlo con el
     rotulo «m» seria poner segundos bajo una unidad que nadie midio. */
  const reloj = relojDeSesion(t.segundos) + " de " + relojDeSesion(dur);
  document.getElementById("tr-total").textContent = hayEjeDeDistancia()
    ? textoDeVuelta(t.metro) + " · " + reloj
    : reloj + " grabados";
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
  /* El trazado grande comparte el instante con el panel chico: dos
     posiciones distintas para el mismo momento serian el tablero
     contandose dos cosas. */
  moverCochesDelTrazadoGrande();
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
    const apertura = aperturaVigente();
    _relojPedidos = setTimeout(() => {
      if (!sigueVigente(apertura)) return;
      const v = instante().vuelta;
      asegurarVuelta(v);
      asegurarPosiciones(v);
      refrescarContexto();
      precargarVueltas(v, apertura);
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
let _relojPedidos = null;

/* Cuanto eje entra en cada grafico. En F1 25 son metros; en las fuentes sin
   distancia son segundos. Cero siempre significa el tramo completo. */
let ventanaTraza = 1200;

function configurarVentanaDeGraficos() {
  const temporal = !hayEjeDeDistancia();
  const opciones = temporal
    ? [[5, "5 s"], [20, "20 s"], [60, "60 s"], [0, "tramo"]]
    : [[300, "300 m"], [1200, "1,2 km"], [3000, "3 km"], [0, "vuelta"]];
  const mando = document.getElementById("tr-ventana");
  if (!mando) return;
  const botones = mando.querySelectorAll("[data-ventana]");
  botones.forEach((boton, i) => {
    boton.dataset.ventana = String(opciones[i][0]);
    boton.textContent = opciones[i][1];
  });
  const permitidas = opciones.map(x => x[0]);
  if (permitidas.indexOf(ventanaTraza) === -1) ventanaTraza = temporal ? 20 : 1200;
  marcar(mando, "ventana", String(ventanaTraza));
}

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
      decirEstadoApi((hayVueltas() ? "La vuelta " + v : "El tramo temporal") +
                     " no se pudo traer: " + motivo +
                     (f && f.permanente
                       ? " La reproducción se detuvo acá y no se reintenta: " +
                          "volver a pedirlo daría lo mismo."
                       : " La reproducción se detuvo acá; mové el cabezal para " +
                          "volver a pedirlo."), true);
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
  /* La frescura va en un atributo aparte y no mezclada con `data-medido`: son
     dos preguntas distintas ---«se midio o se estimo» y «de cuando es»--- y una
     celda puede estar medida y vieja a la vez. */
  const frescura = (id, estado) => {
    const c = document.getElementById(id);
    if (!c) return;
    if (!estado) c.removeAttribute("data-frescura");
    else c.dataset.frescura = estado;
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

  /* EN QUE PUESTO.
     En el simulador es `track_position_order`, una señal que llega en cada
     muestra. En OpenF1 el puesto no es una señal: la fuente lo publica **al
     cambiar**, veintiocho veces en cincuenta y dos vueltas, y vive en otra
     tabla. Ahi el puesto no se mide en el instante, se sostiene desde el
     ultimo cambio declarado, y eso se dice en vez de presentarlo como una
     medicion de ahora. Lo que no cambia: sin dato, una raya. */
  const delContexto = contextoDelPropio();
  const puesto = t.posicion !== null && t.posicion !== undefined
    ? t.posicion
    : (delContexto ? delContexto.position : null);
  const sostenido = (t.posicion === null || t.posicion === undefined) &&
                    !!delContexto && delContexto.position_freshness === "held";
  const hayPuesto = puesto !== null && puesto !== undefined &&
                    Number.isFinite(Number(puesto)) && Number(puesto) >= 1;
  /* La frescura la resuelve la API y el tablero la muestra. Sin contexto ---el
     simulador, el bus--- no hay estado que mostrar y la celda no lleva marca. */
  const fPuesto = comoSeVe(
    hayPuesto ? ((delContexto && delContexto.position_freshness) ||
                 (t.posicion !== null && t.posicion !== undefined ? "current" : "unavailable"))
              : "unavailable",
    delContexto && delContexto.position_age_seconds);
  pon("crono-posicion",
      hayPuesto
        ? "P" + Math.round(Number(puesto)) +
          (fPuesto.sufijo ? '<span class="edad">' + textoSeguro(fPuesto.sufijo) + "</span>" : "")
        : "—",
      !hayPuesto
        ? "La fuente no declara puesto en carrera en este instante"
        : sostenido
          ? "Puesto declarado por la fuente en el último cambio" +
            edadEnPalabras(delContexto.position_age_seconds) +
            ". Esta fuente publica el puesto al cambiar, no en cada muestra."
          : "Puesto en carrera medido por la fuente en este instante");
  frescura("crono-posicion", hayPuesto ? fPuesto.estado : null);

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
  let dif = enSegundos ? diferenciaEnSegundos(t.diferencia) : null;
  let crudo = t.diferencia;
  let deLaCarrera = false;
  /* Y donde la diferencia no es una señal, sale del contexto de carrera, que la
     publica ya en segundos. Es la misma magnitud por otro camino: OpenF1 la
     entrega en `intervals`, una muestra cada ocho segundos. */
  if (dif === null && delContexto && delContexto.gap_to_leader_seconds !== null &&
      delContexto.gap_to_leader_seconds !== undefined) {
    crudo = Number(delContexto.gap_to_leader_seconds);
    dif = diferenciaEnSegundos(crudo);
    deLaCarrera = true;
  }
  const celdaDif = document.getElementById("crono-diferencia");
  /* Solo la que viene del contexto tiene frescura declarada: la del propio
     paquete de telemetria llega con cada muestra y no envejece aparte. */
  const fDif = comoSeVe(
    dif === null ? "unavailable"
                 : (deLaCarrera && delContexto
                      ? (delContexto.interval_freshness || "current") : "current"),
    delContexto && delContexto.interval_age_seconds);
  pon("crono-diferencia",
      dif === null ? "—"
        : textoSeguro(dif) + ' <span class="unidad">s</span>' +
          (fDif.sufijo ? '<span class="edad">' + textoSeguro(fDif.sufijo) + "</span>" : ""),
      dif === null
        ? (enSegundos
            ? "La fuente no declara diferencia con el líder en este instante"
            : "La diferencia llegó en una unidad que este tablero no sabe mostrar")
        : deLaCarrera
          ? "Diferencia con el líder declarada por la fuente (intervals)" +
            edadEnPalabras(delContexto.interval_age_seconds)
          : "Diferencia con el líder de la carrera (delta_to_race_leader)");
  frescura("crono-diferencia", dif === null ? null : fDif.estado);
  if (celdaDif) {
    celdaDif.className = (dif !== null && crudo < 0) ? "negativo" : "";
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
  if (cab) cab.title = hayEjeDeDistancia()
    ? "Cabezal en " + Math.round(t.metro) + " m"
    : "Cabezal en " + relojDeSesion(t.segundos);
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

   EL PANEL DE VIGILANCIA YA NO EXISTE EN EL TABLERO, y su consulta tampoco se
   pide desde aca. Las cifras de arriba y las de abajo se dejan como se
   midieron, con ella adentro, porque asi fue la medicion y reescribirla sin la
   consulta que la produjo seria contar otra cosa. El endpoint sigue en el
   backend, con su modulo de analisis y sus pruebas: lo que se quito es el
   panel. Lo que la medicion demuestra ---que lo secundario tiene que esperar
   a que lo esencial termine--- no depende de cual sea lo secundario, y hoy lo
   son `/avisos`, `/contexto` y `/fuentes/matriz`.
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
/* ============================================================
   EL VELO DE ARRANQUE
   ------------------------------------------------------------
   POR QUE EXISTE. Entre que la pagina pinta y que el tablero tiene algo que
   mostrar hay un rato en que se ven veinte paneles vacios con rayas. Eso no se
   lee como «esta cargando»: se lee como un tablero roto.

   CUANDO SE VA. Cuando el tablero **queda listo para la persona**, que no es
   lo mismo que «cuando termino de cargar todo». Son cuatro situaciones y las
   cuatro cuentan: lo esencial se resolvio ---haya llegado o haya fallado---,
   el elector de etapa quedo esperando una decision, el catalogo esta vacio, o
   la API no contesto. En las dos ultimas el velo **tiene que** irse: tapar un
   error es dejar a alguien mirando un giro eterno sin saber que paso.

   EL PISO NO SE SUMA, COMPITE. Medido el 2026-09-11 sobre Spa: en frio lo que
   hace falta para dibujar entra en 1,1 s ---`/vueltas` 0,27, `/trazado` 0,30,
   `/contexto` 0,74--- y tibio el primer trazo aparece a los 657 ms. Un velo que
   durase el piso **mas** la carga castigaria cada recarga con cinco segundos
   de mas. Lo que se quiere es que nunca parpadee: dura lo que tarde la carga, y
   si la carga fue mas rapida que el piso, dura el piso. Ni un milisegundo mas.

   `/avisos` queda afuera de esta cuenta a proposito: tarda 16,9 s con el
   backend en frio y 0,01 s despues, es secundaria, y ya espera su turno por
   `cuandoHayaGrafico`. Retener el velo por ella seria esconder diecisiete
   segundos un tablero que ya se puede leer y usar.

   EL TECHO NO VIVE ACA. Esta en un guion en linea dentro del propio HTML,
   porque un velo que solo este archivo sabe levantar deja la pagina tapada
   para siempre el dia que este archivo no cargue.
   ============================================================ */
const PISO_DEL_VELO_MS = 5000;

/* La unica decision que el velo toma, sin tocar el DOM para poder ejercerla:
   cuanto falta para poder levantarlo, dado cuanto hace que arranco la pagina. */
function esperaDelVelo(msDesdeElArranque) {
  const falta = PISO_DEL_VELO_MS - msDesdeElArranque;
  return falta > 0 ? falta : 0;
}

/* Cuanto dura el desvanecido. Tiene que coincidir con la transicion de la hoja:
   menos, y el velo desaparece de golpe a mitad de camino. */
const DESVANECIDO_DEL_VELO_MS = 300;

let _veloLevantado = false;
function levantarElVelo() {
  /* La primera situacion que declare «listo» manda. Las demas llegan igual
     ---el elector se abre y despues lo esencial termina--- y sin esta guarda
     cada una programaria su propia levantada. */
  if (_veloLevantado) return;
  _veloLevantado = true;
  setTimeout(() => {
    const velo = document.getElementById("velo-de-arranque");
    if (!velo) return;
    velo.dataset.abierto = "no";
    /* EL DESVANECIDO ES ADORNO; `hidden` ES LA GARANTIA.
       Una transicion de CSS **no corre en una pestaña que no se ve**: el
       navegador no pinta cuadros ahi. Y abrir el tablero y cambiar de pestaña
       mientras carga es lo normal, no el caso raro. Visto el 2026-09-11: con la
       pestaña de fondo, el velo quedaba a medio desvanecer, con el giro dando
       vueltas sobre el tablero ya cargado.

       Colgar la desaparicion de que la transicion termine es colgarla de algo
       que puede no pasar nunca. Asi que la transicion queda para que se vea
       lindo cuando se puede ver, y lo que saca el velo de la pagina es el
       atributo, que no depende de que se pinte un solo cuadro. */
    setTimeout(() => { velo.hidden = true; }, DESVANECIDO_DEL_VELO_MS);
  }, esperaDelVelo(performance.now()));
}

const ESPERA_MAXIMA_DE_CORTESIA_MS = 35000;
let _enEspera = [];
let _relojCortesia = null;
let _esencialResuelta = false;

/* Lo esencial son las vueltas: sin ellas no hay eje ni duracion, y con ellas
   ya se puede dibujar. Se marca tanto si llegaron como si fallaron: lo que
   libera a lo secundario no es el exito, es que la conexion quedo libre. */
function laEsencialTermino() {
  _esencialResuelta = true;
  /* Llego o fallo, pero ya no hay nada mas que esperar para mostrar. */
  levantarElVelo();
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
  if (estadoSesion === "vivo") sincronizarContextoVivo();
  if (estadoSesion !== "vacio") vueltaElegida = instante().vuelta;
  pintarEsquinas(); pintarTransporte(); pintarCronometraje();
  pintarMedidores(); pintarClima(); pintarAvisos(); pintarG();
  pintarPuestaAPunto();
}

function pintarTrazas() {
  pintarPista(); dibujarTraza(); moverCabezalesGraficos();
  /* Con la vista grande abierta, el coche tiene que moverse ahi tambien: son
     el mismo instante mirado dos veces, y dos posiciones distintas para el
     mismo momento serian un tablero contandose dos cosas. */
  if (trazadoGrandeAbierto()) pintarTrazadoGrande();
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
  raiz.dataset.fuente = fuente;
  /* VA PRIMERO Y NO ULTIMO. Estaba al final, y entonces cualquier error en los
     graficos ---que se dibujan antes--- dejaba la caja de escucha con el estado
     anterior: aparecia sobre una sesion guardada, ofreciendo elegir a quien
     escuchar cuando ya no se escuchaba nada. Mostrar u ocultar un control no
     puede depender de que un lienzo se haya dibujado bien. */
  pintarEligeEscucha();
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
        levantarElVelo();
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
      const elegida = sesionQueSeAbreSola(SESIONES, recordada);

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
      if (!elegida) {
        /* Que no se abra nada tiene dos motivos distintos y no se dicen igual.
           Uno es no haber mirado nada todavia, y ahi el pie ya invita a elegir.
           El otro es que lo que se estaba mirando ya no esta, y callarselo
           dejaria a alguien creyendo que el tablero se olvido de su sesion. */
        if (recordada) {
          estado.motivo = "La sesión que estabas mirando ya no está en el " +
            "catálogo. Elegí una guardada.";
        }
        render();
        levantarElVelo();
        return;
      }
      abrirSesionGuardada(elegida);
    })
    .catch(e => {
      estadoSesion = "vacio";
      estado.motivo = "No se pudo hablar con la API en " + (API || "el mismo host") +
        ": " + e.message;
      decirEstadoApi(estado.motivo, true);
      render();
      /* Un velo que se queda puesto cuando la API no contesta convierte un
         error legible en un giro eterno. */
      levantarElVelo();
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
