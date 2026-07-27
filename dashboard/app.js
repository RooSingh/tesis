const API_BASE_URL = "http://127.0.0.1:8000";
const ENDPOINT_ULTIMA_MUESTRA = `${API_BASE_URL}/telemetry/latest-by-signal`;
const ENDPOINT_POR_SENAL = `${API_BASE_URL}/telemetry/by-signal`;

const estadoCarga = document.getElementById("estado-carga");
const cuerpoTabla = document.querySelector("#tabla-telemetria tbody");
const botonRecargar = document.getElementById("boton-recargar");
const contenedorTarjetas = document.getElementById("tarjetas-telemetria");
const selectorSenal = document.getElementById("selector-senal");
const canvasGrafico = document.getElementById("grafico-senal");
const contextoGrafico = canvasGrafico.getContext("2d");
const INTERVALO_RECARGA_MS = 3000;

const SENALES_DESTACADAS = [
  "speed",
  "steer_angle",
  "yaw_rate",
  "accel_x",
  "accel_y",
  "gas_pedal",
  "gas_pressed",
  "brake_pressed",
  "wheel_speed_fl",
  "wheel_speed_fr",
  "wheel_speed_rl",
  "wheel_speed_rr",
];

const ETIQUETAS_SENALES = {
  speed: "Velocidad",
  steer_angle: "Angulo de direccion",
  yaw_rate: "Yaw rate",
  accel_x: "Aceleracion longitudinal",
  accel_y: "Aceleracion lateral",
  gas_pedal: "Acelerador",
  gas_pressed: "Acelerador activado",
  brake_pressed: "Freno activado",
  wheel_speed_fl: "Rueda delantera izq.",
  wheel_speed_fr: "Rueda delantera der.",
  wheel_speed_rl: "Rueda trasera izq.",
  wheel_speed_rr: "Rueda trasera der.",
};

function obtenerEtiquetaSenal(signalName) {
  return ETIQUETAS_SENALES[signalName] ?? signalName;
}

function obtenerClaseCalidad(qualityFlag) {
  return `calidad-${qualityFlag ?? "desconocida"}`;
}

function formatearValor(valorNumerico, valorBooleano, valorTexto) {
  if (valorNumerico !== null && valorNumerico !== undefined) {
    return Number(valorNumerico).toFixed(3);
  }

  if (valorBooleano !== null && valorBooleano !== undefined) {
    return String(valorBooleano);
  }

  if (valorTexto !== null && valorTexto !== undefined) {
    return valorTexto;
  }

  return "-";
}

function limpiarTabla() {
  cuerpoTabla.innerHTML = "";
}

function limpiarTarjetas() {
  contenedorTarjetas.innerHTML = "";
}

function renderizarTarjetas(mensajes) {
  limpiarTarjetas();

  const mensajesPorSenal = new Map(mensajes.map((mensaje) => [mensaje.signal_name, mensaje]));

  for (const signalName of SENALES_DESTACADAS) {
    const mensaje = mensajesPorSenal.get(signalName);

    if (!mensaje) {
      continue;
    }

    const tarjeta = document.createElement("article");
    tarjeta.className = `tarjeta-senal ${obtenerClaseCalidad(mensaje.quality_flag)}`;

    tarjeta.innerHTML = `
      <h3>${obtenerEtiquetaSenal(mensaje.signal_name)}</h3>
      <p class="tarjeta-valor">${formatearValor(mensaje.value_numeric, mensaje.value_boolean, mensaje.value_text)}</p>
      <p class="tarjeta-unidad">${mensaje.unit ?? "-"}</p>
      <p class="tarjeta-calidad ${obtenerClaseCalidad(mensaje.quality_flag)}">Calidad: ${mensaje.quality_flag}</p>
    `;

    contenedorTarjetas.appendChild(tarjeta);
  }
}

function renderizarTelemetria(mensajes) {
  limpiarTabla();

  const mensajesOrdenados = [...mensajes].sort((a, b) => {
    return SENALES_DESTACADAS.indexOf(a.signal_name) - SENALES_DESTACADAS.indexOf(b.signal_name);
  });

  for (const mensaje of mensajesOrdenados) {
    const fila = document.createElement("tr");
    fila.className = obtenerClaseCalidad(mensaje.quality_flag);

    fila.innerHTML = `
      <td>${obtenerEtiquetaSenal(mensaje.signal_name)}</td>
      <td>${formatearValor(mensaje.value_numeric, mensaje.value_boolean, mensaje.value_text)}</td>
      <td>${mensaje.unit ?? "-"}</td>
      <td>${mensaje.timestamp}</td>
      <td class="${obtenerClaseCalidad(mensaje.quality_flag)}">${mensaje.quality_flag}</td>
      <td>${mensaje.can_id ?? "-"}</td>
    `;

    cuerpoTabla.appendChild(fila);
  }
}

function dibujarGraficoSenal(mensajes, signalName) {
  contextoGrafico.clearRect(0, 0, canvasGrafico.width, canvasGrafico.height);

  if (!mensajes.length) {
    contextoGrafico.fillStyle = "#52606d";
    contextoGrafico.font = "16px Segoe UI";
    contextoGrafico.fillText("No hay datos para la senal seleccionada.", 20, 40);
    return;
  }

  const valores = mensajes
    .map((m) => m.value_numeric)
    .filter((v) => v !== null && v !== undefined);

  if (!valores.length) {
    contextoGrafico.fillStyle = "#52606d";
    contextoGrafico.font = "16px Segoe UI";
    contextoGrafico.fillText("La senal seleccionada no tiene valores numericos graficables.", 20, 40);
    return;
  }

  const ancho = canvasGrafico.width;
  const alto = canvasGrafico.height;
  const padding = 50;

  const minValor = Math.min(...valores);
  const maxValor = Math.max(...valores);
  const rango = maxValor - minValor || 1;

  // Fondo interno del grafico.
  contextoGrafico.fillStyle = "#f8fafc";
  contextoGrafico.fillRect(padding, padding, ancho - padding * 2, alto - padding * 2);

  // Rejilla suave para facilitar lectura visual.
  contextoGrafico.strokeStyle = "#e2e8f0";
  contextoGrafico.lineWidth = 1;
  const lineasHorizontales = 4;
  for (let i = 0; i <= lineasHorizontales; i += 1) {
    const y = padding + (i * (alto - padding * 2)) / lineasHorizontales;
    contextoGrafico.beginPath();
    contextoGrafico.moveTo(padding, y);
    contextoGrafico.lineTo(ancho - padding, y);
    contextoGrafico.stroke();
  }

  const lineasVerticales = Math.min(valores.length - 1, 5);
  for (let i = 0; i <= lineasVerticales; i += 1) {
    const x = padding + (i * (ancho - padding * 2)) / Math.max(lineasVerticales, 1);
    contextoGrafico.beginPath();
    contextoGrafico.moveTo(x, padding);
    contextoGrafico.lineTo(x, alto - padding);
    contextoGrafico.stroke();
  }

  // Marco del area de grafico.
  contextoGrafico.strokeStyle = "#cbd5e1";
  contextoGrafico.strokeRect(padding, padding, ancho - padding * 2, alto - padding * 2);

  contextoGrafico.beginPath();
  contextoGrafico.strokeStyle = "#0ea5e9";
  contextoGrafico.lineWidth = 3;

  const puntos = [];

  valores.forEach((valor, indice) => {
    const x = padding + (indice * (ancho - padding * 2)) / Math.max(valores.length - 1, 1);
    const y = alto - padding - ((valor - minValor) / rango) * (alto - padding * 2);
    puntos.push({ x, y });

    if (indice === 0) {
      contextoGrafico.moveTo(x, y);
    } else {
      contextoGrafico.lineTo(x, y);
    }
  });

  contextoGrafico.stroke();

  // Puntos de la serie para reforzar lectura.
  contextoGrafico.fillStyle = "#0284c7";
  for (const punto of puntos) {
    contextoGrafico.beginPath();
    contextoGrafico.arc(punto.x, punto.y, 3, 0, Math.PI * 2);
    contextoGrafico.fill();
  }

  contextoGrafico.fillStyle = "#1f2933";
  contextoGrafico.font = "14px Segoe UI";
  contextoGrafico.fillText(`Senal: ${obtenerEtiquetaSenal(signalName)}`, padding, 20);
  contextoGrafico.fillText(`Min: ${minValor.toFixed(3)}`, padding, alto - 12);
  contextoGrafico.fillText(`Max: ${maxValor.toFixed(3)}`, ancho - 150, alto - 12);
  contextoGrafico.fillStyle = "#52606d";
  contextoGrafico.fillText(`Ultimas ${valores.length} muestras`, padding, 38);
}

async function cargarSeriePorSenal(signalName) {
  const respuesta = await fetch(`${ENDPOINT_POR_SENAL}/${signalName}?limit=30`);

  if (!respuesta.ok) {
    throw new Error(`Error HTTP ${respuesta.status}`);
  }

  return respuesta.json();
}

async function cargarUltimaMuestraPorSenal() {
  estadoCarga.textContent = "Cargando telemetria...";

  try {
    const respuesta = await fetch(ENDPOINT_ULTIMA_MUESTRA);

    if (!respuesta.ok) {
      throw new Error(`Error HTTP ${respuesta.status}`);
    }

    const mensajes = await respuesta.json();
    renderizarTarjetas(mensajes);
    renderizarTelemetria(mensajes);
    estadoCarga.textContent = `Telemetria cargada: ${mensajes.length} senales.`;
  } catch (error) {
    console.error(error);
    estadoCarga.textContent = "No se pudo cargar la telemetria desde la API.";
  }
}

async function actualizarGrafico() {
  try {
    const signalName = selectorSenal.value;
    const mensajes = await cargarSeriePorSenal(signalName);
    dibujarGraficoSenal(mensajes.reverse(), signalName);
  } catch (error) {
    console.error(error);
    contextoGrafico.clearRect(0, 0, canvasGrafico.width, canvasGrafico.height);
    contextoGrafico.fillStyle = "#b91c1c";
    contextoGrafico.font = "16px Segoe UI";
    contextoGrafico.fillText("No se pudo cargar la serie temporal de la senal.", 20, 40);
  }
}

botonRecargar.addEventListener("click", cargarUltimaMuestraPorSenal);
selectorSenal.addEventListener("change", actualizarGrafico);

cargarUltimaMuestraPorSenal();
actualizarGrafico();

setInterval(() => {
  cargarUltimaMuestraPorSenal();
  actualizarGrafico();
}, INTERVALO_RECARGA_MS);
