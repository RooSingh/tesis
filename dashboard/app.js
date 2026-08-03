const API_BASE_URL = "http://127.0.0.1:8000";
const SESSION_ID = "mqtt_phase_recalibrated_01";
const ENDPOINT_SESION = `${API_BASE_URL}/telemetry/by-session/${SESSION_ID}?limit=100`;
const INTERVALO_RECARGA_MS = 3000;

const estadoCarga = document.getElementById("estado-carga");
const resumenSesion = document.getElementById("resumen-sesion");
const estadoOrigen = document.getElementById("estado-origen");
const contextoSesion = document.getElementById("contexto-sesion");
const lineaFases = document.getElementById("linea-fases");
const cantidadFases = document.getElementById("cantidad-fases");
const resumenOperativo = document.getElementById("resumen-operativo");
const descripcionMapa = document.getElementById("descripcion-mapa");
const descripcionPuntoSeleccionado = document.getElementById("descripcion-punto-seleccionado");
const valoresPuntoSeleccionado = document.getElementById("valores-punto-seleccionado");
const cuerpoTabla = document.querySelector("#tabla-telemetria tbody");
const botonRecargar = document.getElementById("boton-recargar");
const detalleGrafico = document.getElementById("detalle-grafico");
const GRAFICOS = {
  speed: document.getElementById("grafico-velocidad"),
  brake_pressed: document.getElementById("grafico-freno"),
  steer_angle: document.getElementById("grafico-direccion"),
};

const SENALES_OPERATIVAS = ["speed", "brake_pressed", "steer_angle"];
const ETIQUETAS = {
  speed: "Velocidad",
  brake_pressed: "Freno",
  steer_angle: "Direccion",
};
const ETIQUETAS_SEGMENTOS = {
  demo_straight_entry: "Recta inicial",
  demo_braking_zone: "Zona de frenada",
  demo_corner_entry: "Entrada a curva",
  demo_corner_apex: "Apice",
  demo_corner_exit: "Salida de curva",
  demo_straight_exit: "Recta final",
};

let mensajesSesion = [];
let indiceFaseSeleccionado = null;

function obtenerEtiqueta(signalName) {
  return ETIQUETAS[signalName] ?? signalName;
}

function obtenerEtiquetaSegmento(segmentId) {
  return ETIQUETAS_SEGMENTOS[segmentId] ?? segmentId ?? "Sin segmento";
}

function obtenerEtiquetaPunto(fase, indice, cantidadPuntos) {
  if (fase.track_segment_id === "demo_straight_exit") {
    return indice === cantidadPuntos - 1 ? "Fin de recta final" : "Inicio de recta final";
  }

  return obtenerEtiquetaSegmento(fase.track_segment_id);
}

function obtenerValor(mensaje) {
  if (mensaje.value_numeric !== null && mensaje.value_numeric !== undefined) {
    return Number(mensaje.value_numeric);
  }

  if (mensaje.value_boolean !== null && mensaje.value_boolean !== undefined) {
    return mensaje.value_boolean ? 1 : 0;
  }

  return null;
}

function formatearValor(mensaje) {
  if (mensaje.value_numeric !== null && mensaje.value_numeric !== undefined) {
    const valor = Number(mensaje.value_numeric);
    return (Math.abs(valor) < 0.005 ? 0 : valor).toFixed(2);
  }

  if (mensaje.value_boolean !== null && mensaje.value_boolean !== undefined) {
    return mensaje.value_boolean ? "ACTIVO" : "LIBERADO";
  }

  return mensaje.value_text ?? "-";
}

function formatearHora(timestamp) {
  return new Date(timestamp).toLocaleTimeString("es-AR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    fractionalSecondDigits: 3,
  });
}

function ordenarCronologicamente(mensajes) {
  return [...mensajes].sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
}

function obtenerUltimosPorSenal(mensajes) {
  const ultimos = new Map();
  for (const mensaje of ordenarCronologicamente(mensajes)) {
    ultimos.set(mensaje.signal_name, mensaje);
  }
  return ultimos;
}

function obtenerFases(mensajes) {
  const fases = new Map();
  for (const mensaje of ordenarCronologicamente(mensajes)) {
    if (!fases.has(mensaje.timestamp)) {
      fases.set(mensaje.timestamp, mensaje);
    }
  }
  return [...fases.values()];
}

function renderizarContexto(mensajes) {
  const muestra = ordenarCronologicamente(mensajes).at(-1);
  if (!muestra) {
    return;
  }

  resumenSesion.textContent = `${muestra.vehicle_id} · ${muestra.driver_id} · ${muestra.lap_id}`;
  estadoOrigen.textContent = muestra.source_type === "can_simulated" ? "SIMULACION CONTROLADA" : muestra.source_type;
  estadoOrigen.className = `estado-origen estado-${muestra.source_type}`;

  const datos = [
    ["Sesion", muestra.session_id],
    ["Vehiculo", muestra.vehicle_id],
    ["Piloto", muestra.driver_id],
    ["Vuelta", muestra.lap_id ?? "-"],
    ["Sector", muestra.sector_id ?? "-"],
  ];
  contextoSesion.innerHTML = datos.map(([etiqueta, valor]) => `<div><dt>${etiqueta}</dt><dd>${valor}</dd></div>`).join("");
}

function renderizarResumenOperativo() {
  resumenOperativo.textContent = "Selecciona un punto de control para revisar velocidad, freno y direccion.";
}

function renderizarFases(mensajes) {
  const fases = obtenerFases(mensajes);
  if (indiceFaseSeleccionado === null || indiceFaseSeleccionado >= fases.length) {
    indiceFaseSeleccionado = Math.max(fases.length - 1, 0);
  }
  const cantidadFasesUnicas = new Set(fases.map((fase) => fase.track_segment_id)).size;
  cantidadFases.textContent = `${fases.length} puntos de control · ${cantidadFasesUnicas} fases`;
  lineaFases.innerHTML = fases.map((fase, indice) => `
    <button
      class="hito-fase ${indice === indiceFaseSeleccionado ? "hito-seleccionado" : ""}"
      type="button"
      data-indice-fase="${indice}"
      aria-pressed="${indice === indiceFaseSeleccionado}"
    >
      <span class="numero-fase">${String(indice + 1).padStart(2, "0")}</span>
      <div>
        <strong>${obtenerEtiquetaPunto(fase, indice, fases.length)}</strong>
        <p>${fase.curve_id ? "Punto de control en curva" : "Punto de control en recta"}</p>
      </div>
    </button>
  `).join("");
}

function renderizarPuntoSeleccionado(mensajes) {
  const fases = obtenerFases(mensajes);
  const fase = fases[indiceFaseSeleccionado];
  if (!fase) {
    descripcionPuntoSeleccionado.textContent = "No hay un punto disponible para analizar.";
    valoresPuntoSeleccionado.innerHTML = "";
    return;
  }

  const mensajesPunto = mensajes.filter((mensaje) => mensaje.timestamp === fase.timestamp);
  descripcionPuntoSeleccionado.textContent = `Punto ${String(indiceFaseSeleccionado + 1).padStart(2, "0")}: ${obtenerEtiquetaPunto(fase, indiceFaseSeleccionado, fases.length)}.`;
  valoresPuntoSeleccionado.innerHTML = SENALES_OPERATIVAS.map((signalName) => {
    const mensaje = mensajesPunto.find((item) => item.signal_name === signalName);
    if (!mensaje) {
      return "";
    }

    const unidad = mensaje.value_boolean === null || mensaje.value_boolean === undefined
      ? mensaje.unit ?? ""
      : "";
    return `
      <article class="tarjeta-punto tarjeta-${signalName}">
        <p>${obtenerEtiqueta(signalName)}</p>
        <strong>${formatearValor(mensaje)}</strong>
        <span>${unidad}</span>
      </article>
    `;
  }).join("");
}

function renderizarMapa(mensajes) {
  const fase = obtenerFases(mensajes)[indiceFaseSeleccionado];
  const segmentoSeleccionado = fase?.track_segment_id;
  document.querySelectorAll(".tramo-mapa").forEach((tramo) => {
    tramo.classList.toggle("tramo-activo", tramo.dataset.segmento === segmentoSeleccionado);
  });
  descripcionMapa.textContent = segmentoSeleccionado
    ? `Tramo iluminado: ${obtenerEtiquetaSegmento(segmentoSeleccionado)}.`
    : "Selecciona un punto para iluminar el tramo correspondiente.";
}

function renderizarTabla(mensajes) {
  const faseSeleccionada = obtenerFases(mensajes)[indiceFaseSeleccionado];
  cuerpoTabla.innerHTML = ordenarCronologicamente(mensajes).map((mensaje) => {
    const unidad = mensaje.value_boolean === null || mensaje.value_boolean === undefined
      ? mensaje.unit ?? ""
      : "";
    return `
      <tr class="${mensaje.timestamp === faseSeleccionada?.timestamp ? "fila-seleccionada" : ""}">
        <td>${obtenerEtiqueta(mensaje.signal_name)}</td>
        <td>${formatearValor(mensaje)} ${unidad}</td>
        <td>${formatearHora(mensaje.timestamp)}</td>
        <td>${mensaje.track_segment_id ?? "-"}</td>
        <td>${mensaje.curve_id ?? "-"}</td>
        <td>${mensaje.source_type ?? "-"}</td>
        <td>${mensaje.can_id ?? "-"}</td>
      </tr>
    `;
  }).join("");
}

function dibujarGrafico(signalName, canvasGrafico) {
  const contextoGrafico = canvasGrafico.getContext("2d");
  const muestras = ordenarCronologicamente(mensajesSesion)
    .filter((mensaje) => mensaje.signal_name === signalName)
    .map((mensaje) => ({ ...mensaje, valor: obtenerValor(mensaje) }))
    .filter((mensaje) => mensaje.valor !== null);

  const ancho = canvasGrafico.width;
  const alto = canvasGrafico.height;
  const margen = { superior: 42, derecho: 24, inferior: 48, izquierdo: 74 };
  contextoGrafico.clearRect(0, 0, ancho, alto);
  contextoGrafico.fillStyle = "#0b1220";
  contextoGrafico.fillRect(0, 0, ancho, alto);

  if (!muestras.length) {
    contextoGrafico.fillStyle = "#94a3b8";
    contextoGrafico.font = "16px Segoe UI";
    contextoGrafico.fillText("No hay muestras para la senal seleccionada.", margen.izquierdo, alto / 2);
    return;
  }

  const valores = muestras.map((muestra) => muestra.valor);
  const minimo = Math.min(...valores);
  const maximo = Math.max(...valores);
  const rango = maximo - minimo || 1;
  const areaAncho = ancho - margen.izquierdo - margen.derecho;
  const areaAlto = alto - margen.superior - margen.inferior;
  const fases = obtenerFases(mensajesSesion);
  const indiceSeleccionado = Math.min(indiceFaseSeleccionado ?? muestras.length - 1, muestras.length - 1);
  const muestraSeleccionada = muestras[indiceSeleccionado];

  contextoGrafico.strokeStyle = "rgba(148, 163, 184, 0.22)";
  contextoGrafico.lineWidth = 1;
  for (let indice = 0; indice <= 4; indice += 1) {
    const y = margen.superior + (areaAlto * indice) / 4;
    contextoGrafico.beginPath();
    contextoGrafico.moveTo(margen.izquierdo, y);
    contextoGrafico.lineTo(ancho - margen.derecho, y);
    contextoGrafico.stroke();
  }

  contextoGrafico.fillStyle = "#94a3b8";
  contextoGrafico.font = "11px Segoe UI";
  if (signalName === "brake_pressed") {
    contextoGrafico.fillText("ACTIVO", 8, margen.superior + 4);
    contextoGrafico.fillText("LIBERADO", 8, margen.superior + areaAlto);
  } else {
    for (let indice = 0; indice <= 4; indice += 2) {
      const y = margen.superior + (areaAlto * indice) / 4;
      const valorEscala = maximo - (rango * indice) / 4;
      const precision = Math.abs(maximo - minimo) < 10 ? 1 : 0;
      contextoGrafico.fillText(valorEscala.toFixed(precision), 18, y + 4);
    }
  }

  if (signalName === "steer_angle" && minimo <= 0 && maximo >= 0) {
    const yCero = margen.superior + areaAlto - ((0 - minimo) / rango) * areaAlto;
    contextoGrafico.strokeStyle = "rgba(248, 250, 252, 0.58)";
    contextoGrafico.setLineDash([5, 4]);
    contextoGrafico.beginPath();
    contextoGrafico.moveTo(margen.izquierdo, yCero);
    contextoGrafico.lineTo(ancho - margen.derecho, yCero);
    contextoGrafico.stroke();
    contextoGrafico.setLineDash([]);
  }

  const color = signalName === "brake_pressed" ? "#f97316" : signalName === "steer_angle" ? "#a78bfa" : "#22d3ee";
  contextoGrafico.beginPath();
  contextoGrafico.strokeStyle = color;
  contextoGrafico.lineWidth = 4;

  muestras.forEach((muestra, indice) => {
    const x = margen.izquierdo + (areaAncho * indice) / Math.max(muestras.length - 1, 1);
    const y = margen.superior + areaAlto - ((muestra.valor - minimo) / rango) * areaAlto;
    if (indice === 0) {
      contextoGrafico.moveTo(x, y);
    } else {
      contextoGrafico.lineTo(x, y);
    }
  });
  contextoGrafico.stroke();

  muestras.forEach((muestra, indice) => {
    const x = margen.izquierdo + (areaAncho * indice) / Math.max(muestras.length - 1, 1);
    const y = margen.superior + areaAlto - ((muestra.valor - minimo) / rango) * areaAlto;
    contextoGrafico.fillStyle = color;
    contextoGrafico.beginPath();
    contextoGrafico.arc(x, y, 5, 0, Math.PI * 2);
    contextoGrafico.fill();
    contextoGrafico.fillStyle = "#cbd5e1";
    contextoGrafico.font = "12px Segoe UI";
    contextoGrafico.fillText(String(indice + 1).padStart(2, "0"), x - 7, alto - 20);
  });

  if (muestraSeleccionada) {
    const x = margen.izquierdo + (areaAncho * indiceSeleccionado) / Math.max(muestras.length - 1, 1);
    const y = margen.superior + areaAlto - ((muestraSeleccionada.valor - minimo) / rango) * areaAlto;
    contextoGrafico.strokeStyle = "#f8fafc";
    contextoGrafico.lineWidth = 3;
    contextoGrafico.beginPath();
    contextoGrafico.arc(x, y, 9, 0, Math.PI * 2);
    contextoGrafico.stroke();
  }

  contextoGrafico.fillStyle = "#e2e8f0";
  contextoGrafico.font = "600 17px Segoe UI";
  contextoGrafico.fillText(obtenerEtiqueta(signalName), margen.izquierdo, 25);
  contextoGrafico.fillStyle = "#94a3b8";
  contextoGrafico.font = "13px Segoe UI";
  contextoGrafico.fillText(`Min ${minimo.toFixed(2)} · Max ${maximo.toFixed(2)} · ${muestras.length} muestras`, margen.izquierdo, alto - 5);

  const faseSeleccionada = fases[indiceSeleccionado];
  detalleGrafico.textContent = `Punto ${String(indiceSeleccionado + 1).padStart(2, "0")}: ${obtenerEtiquetaPunto(faseSeleccionada, indiceSeleccionado, fases.length)}. Las tres series comparten este punto de control.`;
}

function dibujarGraficosCoordinados() {
  for (const signalName of SENALES_OPERATIVAS) {
    dibujarGrafico(signalName, GRAFICOS[signalName]);
  }
}

async function cargarSesion() {
  estadoCarga.textContent = "Cargando sesion demostrativa...";
  try {
    const respuesta = await fetch(ENDPOINT_SESION);
    if (!respuesta.ok) {
      throw new Error(`Error HTTP ${respuesta.status}`);
    }

    mensajesSesion = await respuesta.json();
    renderizarContexto(mensajesSesion);
    renderizarResumenOperativo();
    renderizarFases(mensajesSesion);
    renderizarMapa(mensajesSesion);
    renderizarPuntoSeleccionado(mensajesSesion);
    renderizarTabla(mensajesSesion);
    dibujarGraficosCoordinados();
    estadoCarga.textContent = `${mensajesSesion.length} mensajes de ${SESSION_ID}.`;
  } catch (error) {
    console.error(error);
    estadoCarga.textContent = "No se pudo cargar la sesion desde la API.";
  }
}

botonRecargar.addEventListener("click", cargarSesion);
lineaFases.addEventListener("click", (event) => {
  const boton = event.target.closest("[data-indice-fase]");
  if (!boton) {
    return;
  }

  indiceFaseSeleccionado = Number(boton.dataset.indiceFase);
  renderizarFases(mensajesSesion);
  renderizarMapa(mensajesSesion);
  renderizarPuntoSeleccionado(mensajesSesion);
  renderizarTabla(mensajesSesion);
  dibujarGraficosCoordinados();
});

cargarSesion();
setInterval(cargarSesion, INTERVALO_RECARGA_MS);
