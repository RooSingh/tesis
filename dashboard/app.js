const API_BASE_URL = "http://127.0.0.1:8000";
const SESSION_ID = "mqtt_phase_recalibrated_01";
const ENDPOINT_SESION = `${API_BASE_URL}/telemetry/by-session/${SESSION_ID}?limit=100`;
const INTERVALO_RECARGA_MS = 3000;

// Sesion y corrida elegidas desde la interfaz.
//
// Eran dos constantes escritas en el codigo, `9947` y `d7_silverstone_full_001`.
// La base tiene tres sesiones importadas -Silverstone, Spa-Francorchamps y
// Suzuka- y dos de ellas no tenian forma de mostrarse, lo que contradecia de
// frente la reutilizacion multicircuito que el trabajo sostiene. Ahora son estado:
// se pueblan desde `/racing/sessions` y `/racing/sessions/{key}/replay-runs`.
//
// La corrida no es un detalle menor de la sesion: una misma carrera acumula el
// replay definitivo junto a mas de una decena de sondeos de carga de las mismas
// vueltas, de modo que sin elegir corrida se mezclan repeticiones. El literal
// anterior ya habia tenido que cambiarse a mano una vez.
let sesionesOpenF1 = [];
let sesionOpenF1Seleccionada = null;
let corridasReplaySesion = [];
let corridaReplaySeleccionada = null;
// Limites persistidos por corrida de analisis, indexados por `replay_run_id`.
// Es de donde salen la resolucion de minisector y la granularidad de muestreo, que
// antes eran textos fijos con los valores de Silverstone.
let limitesPorCorrida = new Map();

const estadoCarga = document.getElementById("estado-carga");
const resumenSesion = document.getElementById("resumen-sesion");
const estadoOrigen = document.getElementById("estado-origen");
const etiquetaCabecera = document.getElementById("etiqueta-cabecera");
const tituloCabecera = document.getElementById("titulo-cabecera");
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
const selectorModo = document.getElementById("selector-modo");
const panelOpenF1 = document.getElementById("panel-openf1");
const openF1Titulo = document.getElementById("openf1-titulo");
const openF1Resumen = document.getElementById("openf1-resumen");
const openF1EstadoCarga = document.getElementById("openf1-estado-carga");
const openF1Contexto = document.getElementById("openf1-contexto");
const casillasPilotosComparacion = document.getElementById("casillas-pilotos-comparacion");
const botonLimpiarPilotos = document.getElementById("boton-limpiar-pilotos");
const botonTodosPilotos = document.getElementById("boton-todos-pilotos");
const busquedaPilotosComparacion = document.getElementById("busqueda-pilotos-comparacion");
const seleccionadosPilotosComparacion = document.getElementById("seleccionados-pilotos-comparacion");
const cuerpoTablaOpenF1 = document.querySelector("#tabla-openf1 tbody");
const tarjetasComparacionPilotos = document.getElementById("tarjetas-comparacion-pilotos");
const PILOTOS_COMPARACION_INICIALES = [1, 4, 81];
const selectorSesionOpenF1 = document.getElementById("selector-sesion-openf1");
const selectorCorridaReplay = document.getElementById("selector-corrida-replay");
const declaracionTelemetriaSesion = document.getElementById("declaracion-telemetria-sesion");
// Secciones que solo tienen sentido con una corrida de replay persistida. Se
// ocultan cuando no la hay, y la ausencia se declara arriba: un panel vacio no
// distingue "no hay dato" de "la consulta fallo".
const SECCIONES_DEPENDIENTES_DE_TELEMETRIA = [
  document.getElementById("seccion-analisis-carrera"),
  document.getElementById("seccion-trazabilidad-openf1"),
  document.getElementById("seccion-analisis-vuelta"),
];

// Tope de muestras crudas que se piden por piloto para la tabla de auditoria.
// La tabla existe para inspeccionar el formato de los mensajes, no para volcarlos:
// la carrera completa tiene 6.217.506 y el navegador construia una fila por cada uno.
const LIMITE_MUESTRAS_AUDITORIA_POR_PILOTO = 200;
const resumenAnalisisCarrera = document.getElementById("resumen-analisis-carrera");
const estadoAnalisisCarrera = document.getElementById("estado-analisis-carrera");
const leyendaAnalisisCarrera = document.getElementById("leyenda-analisis-carrera");
const GRAFICOS_CARRERA = {
  speed: document.getElementById("grafico-velocidad-carrera"),
  throttle: document.getElementById("grafico-acelerador-carrera"),
  brake_applied: document.getElementById("grafico-freno-carrera"),
};
const resumenInstanteCarrera = document.getElementById("resumen-instante-carrera");
const climaInstanteCarrera = document.getElementById("clima-instante-carrera");
const pilotosInstanteCarrera = document.getElementById("pilotos-instante-carrera");
const estadoProcesamientoSesiones = document.getElementById("estado-procesamiento-sesiones");
const tarjetasProcesamientoSesiones = document.getElementById("tarjetas-procesamiento-sesiones");
const COLORES_PILOTOS_OPENF1 = {
  1: "#38bdf8",
  4: "#fb923c",
  81: "#e879f9",
};
const CONFIGURACION_SENALES_CARRERA = {
  speed: { etiqueta: "Velocidad", unidad: "km/h", minimo: null, maximo: null },
  throttle: { signalName: "throttle_position", etiqueta: "Acelerador", unidad: "%", minimo: 0, maximo: 100 },
  brake_applied: { etiqueta: "Freno", unidad: "bool", minimo: 0, maximo: 1, esBooleana: true },
};
let ultimaSerieCarrera = null;
let instanteSeleccionadoCarrera = null;
let pilotosSeleccionadosEstado = [...PILOTOS_COMPARACION_INICIALES];
let pilotosConTelemetriaReplay = new Set(PILOTOS_COMPARACION_INICIALES);

function obtenerPilotosSeleccionados() {
  return pilotosSeleccionadosEstado;
}

function renderizarCasillasPilotos() {
  const query = busquedaPilotosComparacion.value.trim().toLowerCase();
  const grupos = new Map();
  pilotosOpenF1
    .filter((piloto) => `${piloto.name_acronym} ${piloto.full_name} ${piloto.team_name}`.toLowerCase().includes(query))
    .forEach((piloto) => {
      const grupo = piloto.team_name ?? "Sin grupo";
      if (!grupos.has(grupo)) {
        grupos.set(grupo, []);
      }
      grupos.get(grupo).push(piloto);
    });
  casillasPilotosComparacion.innerHTML = [...grupos.entries()].map(([grupo, pilotos]) => `<section class="grupo-pilotos-comparacion">
    <h4>${escaparHtml(grupo)}</h4>
    ${pilotos.map((piloto) => `<label class="casilla-piloto-comparacion">
      <input type="checkbox" value="${piloto.driver_number}" ${pilotosSeleccionadosEstado.includes(piloto.driver_number) ? "checked" : ""}>
      <span class="punto-equipo" style="background:#${escaparHtml(piloto.team_colour ?? "64748B")}"></span>
      ${escaparHtml(piloto.name_acronym)}${pilotosConTelemetriaReplay.has(piloto.driver_number) ? "" : " <small>sin traza</small>"}
    </label>`).join("")}
  </section>`).join("");
  seleccionadosPilotosComparacion.innerHTML = pilotosSeleccionadosEstado.length
    ? pilotosSeleccionadosEstado.map((numero) => {
      const piloto = pilotosOpenF1.find((item) => item.driver_number === numero);
      return `<span>${escaparHtml(piloto?.name_acronym ?? numero)} <button type="button" data-quitar-piloto="${numero}" aria-label="Quitar ${escaparHtml(piloto?.name_acronym ?? numero)}">×</button></span>`;
    }).join("")
    : "<em>Sin pilotos seleccionados</em>";
}
const GRAFICOS = {
  speed: document.getElementById("grafico-velocidad"),
  brake_pressed: document.getElementById("grafico-freno"),
  steer_angle: document.getElementById("grafico-direccion"),
};

// La demo usa tres senales representativas para leer la maniobra sin afirmar
// que el dashboard muestre todo el catalogo del generador.
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
let pilotosOpenF1 = [];

function escaparHtml(valor) {
  return String(valor ?? "-").replace(/[&<>"]/g, (caracter) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[caracter]);
}

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
  // Cada punto de control comparte timestamp entre sus tres senales; un mensaje
  // por timestamp alcanza para construir el recorrido sincronizado.
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
  // Las tres series tienen una muestra por punto de control, por eso este indice
  // mantiene alineados graficos, mapa, panel operativo y tabla.
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
  if (selectorModo.value !== "simulation") {
    return;
  }
  estadoCarga.textContent = "Cargando sesion demostrativa...";
  try {
    const respuesta = await fetch(ENDPOINT_SESION);
    if (!respuesta.ok) {
      throw new Error(`Error HTTP ${respuesta.status}`);
    }

    // La API ya devuelve filas persistidas; el dashboard solo las representa y
    // no genera datos ni consulta TimescaleDB de forma directa.
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

function valorOpenF1(mensaje) {
  if (mensaje.value_numeric !== null && mensaje.value_numeric !== undefined) {
    return Number(mensaje.value_numeric).toFixed(2);
  }
  if (mensaje.value_boolean !== null && mensaje.value_boolean !== undefined) {
    return mensaje.value_boolean ? "ACTIVO" : "LIBERADO";
  }
  return mensaje.value_text ?? "-";
}

function renderizarTablaOpenF1(mensajes) {
  cuerpoTablaOpenF1.innerHTML = mensajes.map((mensaje) => {
    const extra = mensaje.metadata?.extra ?? {};
    return `<tr>
      <td>${escaparHtml(mensaje.signal_name)}</td>
      <td>${escaparHtml(valorOpenF1(mensaje))} ${escaparHtml(mensaje.unit)}</td>
      <td>${escaparHtml(mensaje.timestamp)}</td>
      <td>${escaparHtml(extra.published_at_utc)}</td>
      <td>${escaparHtml(extra.source_endpoint)}</td>
      <td>${escaparHtml(extra.raw_field)}</td>
    </tr>`;
  }).join("");
}

function formatearTiempoVuelta(segundos) {
  if (segundos === null || segundos === undefined) {
    return "-";
  }
  const minutos = Math.floor(segundos / 60);
  return `${minutos}:${(segundos % 60).toFixed(3).padStart(6, "0")}`;
}

function renderizarCompuestos(compuestos) {
  if (!compuestos) {
    return "-";
  }
  return `<div class="comparacion-compuestos">${compuestos.split(", ").map((compuesto) => `<span class="comparacion-compuesto">${escaparHtml(compuesto)}</span>`).join("")}</div>`;
}

function renderizarComparacionPilotos(filas) {
  tarjetasComparacionPilotos.innerHTML = filas.map((fila) => `<article class="tarjeta-comparacion-piloto">
    <header>
      <div><span class="punto-equipo" style="background:#${escaparHtml(pilotosOpenF1.find((item) => item.driver_number === fila.driver_number)?.team_colour ?? "64748B")}"></span>${escaparHtml(fila.name_acronym)}</div>
      <strong class="comparacion-posicion">P${escaparHtml(fila.final_position)}</strong>
    </header>
    <p>${escaparHtml(fila.team_name)}</p>
    <dl>
      <div><dt>Mejor vuelta</dt><dd class="comparacion-mejor-vuelta">${escaparHtml(formatearTiempoVuelta(fila.best_lap_seconds))}</dd></div>
      <div><dt>Puntos</dt><dd>${escaparHtml(fila.points)}</dd></div>
      <div><dt>Estrategia</dt><dd>${escaparHtml(fila.stint_count)} stints · ${escaparHtml(fila.pit_stop_count)} paradas</dd></div>
    </dl>
    ${renderizarCompuestos(fila.compounds)}
  </article>`).join("");
}

function obtenerNumeroPiloto(driverId) {
  return Number(driverId.split(":").at(-1));
}

function dibujarSerieCarrera(mensajes, configuracion, canvas, rangoComun) {
  const contexto = canvas.getContext("2d");
  const ancho = canvas.width;
  const alto = canvas.height;
  const margen = { superior: 34, derecho: 30, inferior: 48, izquierdo: 66 };
  const areaAncho = ancho - margen.izquierdo - margen.derecho;
  const areaAlto = alto - margen.superior - margen.inferior;
  contexto.clearRect(0, 0, ancho, alto);
  contexto.fillStyle = "#07101c";
  contexto.fillRect(0, 0, ancho, alto);

  const puntos = mensajes
    .filter((mensaje) => (configuracion.esBooleana && mensaje.value_boolean !== null && mensaje.value_boolean !== undefined)
      || (!configuracion.esBooleana && mensaje.value_numeric !== null && mensaje.value_numeric !== undefined))
    .map((mensaje) => ({
      piloto: obtenerNumeroPiloto(mensaje.driver_id),
      tiempo: new Date(mensaje.timestamp).getTime(),
      timestamp: mensaje.timestamp,
      valor: configuracion.esBooleana ? (mensaje.value_boolean ? 1 : 0) : Number(mensaje.value_numeric),
    }));
  if (!puntos.length) {
    estadoAnalisisCarrera.textContent = `No hay puntos numericos para ${configuracion.etiqueta.toLowerCase()}.`;
    return;
  }

  const inicio = rangoComun.inicio;
  const fin = rangoComun.fin;
  const minimoObservado = Math.min(...puntos.map((punto) => punto.valor));
  const maximoObservado = Math.max(...puntos.map((punto) => punto.valor));
  const minimo = configuracion.minimo ?? minimoObservado;
  const maximo = configuracion.maximo ?? maximoObservado;
  const rangoTiempo = fin - inicio || 1;
  const rangoValor = maximo - minimo || 1;
  const x = (tiempo) => margen.izquierdo + ((tiempo - inicio) / rangoTiempo) * areaAncho;
  const y = (valor) => margen.superior + areaAlto - ((valor - minimo) / rangoValor) * areaAlto;

  contexto.strokeStyle = "rgba(148, 163, 184, 0.22)";
  contexto.lineWidth = 1;
  contexto.fillStyle = "#94a3b8";
  contexto.font = "12px Segoe UI";
  const divisionesEscala = configuracion.esBooleana ? 1 : 4;
  for (let indice = 0; indice <= divisionesEscala; indice += 1) {
    const posicionY = margen.superior + (areaAlto * indice) / divisionesEscala;
    const valorEscala = maximo - (rangoValor * indice) / divisionesEscala;
    contexto.beginPath();
    contexto.moveTo(margen.izquierdo, posicionY);
    contexto.lineTo(ancho - margen.derecho, posicionY);
    contexto.stroke();
    const etiquetaEscala = configuracion.esBooleana
      ? (valorEscala >= 0.5 ? "ACTIVO" : "LIBERADO")
      : `${valorEscala.toFixed(0)} ${configuracion.unidad}`;
    contexto.fillText(etiquetaEscala, 8, posicionY + 4);
  }
  for (let indice = 0; indice <= 4; indice += 1) {
    const posicionX = margen.izquierdo + (areaAncho * indice) / 4;
    const segundos = ((rangoTiempo * indice) / 4 / 1000).toFixed(1);
    contexto.fillText(`${segundos} s`, posicionX - 10, alto - 18);
  }

  const porPiloto = new Map();
  puntos.forEach((punto) => {
    if (!porPiloto.has(punto.piloto)) {
      porPiloto.set(punto.piloto, []);
    }
    porPiloto.get(punto.piloto).push(punto);
  });
  porPiloto.forEach((serie, piloto) => {
    contexto.beginPath();
    contexto.strokeStyle = COLORES_PILOTOS_OPENF1[piloto] ?? "#f8fafc";
    contexto.lineWidth = 3;
    serie.forEach((punto, indice) => {
      if (indice === 0) {
        contexto.moveTo(x(punto.tiempo), y(punto.valor));
      } else {
        if (configuracion.esBooleana) {
          contexto.lineTo(x(punto.tiempo), y(serie[indice - 1].valor));
        }
        contexto.lineTo(x(punto.tiempo), y(punto.valor));
      }
    });
    contexto.stroke();
  });

  if (instanteSeleccionadoCarrera !== null) {
    const posicionX = x(instanteSeleccionadoCarrera);
    contexto.strokeStyle = "rgba(248, 250, 252, 0.82)";
    contexto.lineWidth = 1.5;
    contexto.setLineDash([5, 4]);
    contexto.beginPath();
    contexto.moveTo(posicionX, margen.superior);
    contexto.lineTo(posicionX, margen.superior + areaAlto);
    contexto.stroke();
    contexto.setLineDash([]);
  }

  const pilotos = [...porPiloto.keys()].sort((a, b) => a - b);
  return { mensajes, configuracion, puntos, inicio, fin, margen, areaAncho };
}

function formatearFrescura(freshness, ageSeconds) {
  if (freshness === "current") {
    return "actual";
  }
  if (freshness === "aged") {
    return `con aviso: ${Number(ageSeconds).toFixed(1)} s`;
  }
  return "no disponible para este instante";
}

function formatearGap(context) {
  if (context.interval_freshness === "unavailable") {
    return "Gap: no disponible para este instante";
  }
  const value = context.gap_to_leader_seconds ?? context.gap_to_leader_text;
  return `Gap: ${value ?? "-"} s (${formatearFrescura(context.interval_freshness, context.interval_age_seconds)})`;
}

function renderizarContextoInstante(contexto, timestamp) {
  const hora = new Date(timestamp).toISOString().slice(11, 23);
  resumenInstanteCarrera.textContent = `Instante seleccionado: ${hora} UTC. Los valores muestran la muestra OpenF1 mas cercana y su frescura.`;
  const weather = contexto.weather;
  climaInstanteCarrera.innerHTML = weather ? `<div>
    <strong>Clima</strong>
    <p>${weather.weather_freshness === "unavailable" ? "No disponible para este instante" : `${weather.rainfall ? "Lluvia" : "Sin lluvia"} · pista ${weather.track_temperature_c} C · aire ${weather.air_temperature_c} C`}<br><span class="contexto-frescura-${weather.weather_freshness}">${formatearFrescura(weather.weather_freshness, weather.weather_age_seconds)}</span></p>
  </div>` : "";
  pilotosInstanteCarrera.innerHTML = contexto.drivers.map((driver) => `<article class="contexto-piloto-instante">
    <strong>${escaparHtml(driver.name_acronym)}</strong>
    <p>Posicion: ${driver.position === null ? "no disponible" : `P${driver.position}`}<br><span class="contexto-frescura-${driver.position_freshness}">${formatearFrescura(driver.position_freshness, driver.position_age_seconds)}</span></p>
    <p>${escaparHtml(formatearGap(driver))}</p>
    <p>Stint ${driver.stint_number ?? "-"} · ${escaparHtml(driver.compound ?? "compuesto no disponible")}</p>
  </article>`).join("");
}

async function seleccionarInstanteCarrera(timestamp) {
  instanteSeleccionadoCarrera = timestamp;
  if (ultimaSerieCarrera) {
    Object.entries(ultimaSerieCarrera.series).forEach(([signalName, mensajes]) => {
      dibujarSerieCarrera(mensajes, CONFIGURACION_SENALES_CARRERA[signalName], GRAFICOS_CARRERA[signalName], ultimaSerieCarrera);
    });
  }
  resumenInstanteCarrera.textContent = "Consultando contexto racing cercano...";
  const parametros = new URLSearchParams({ timestamp: new Date(timestamp).toISOString() });
  obtenerPilotosSeleccionados().forEach((driver) => parametros.append("drivers", driver));
  try {
    const respuesta = await fetch(`${API_BASE_URL}/racing/sessions/${sesionOpenF1Seleccionada}/context-at?${parametros}`);
    if (!respuesta.ok) {
      throw new Error(`Error HTTP ${respuesta.status}`);
    }
    renderizarContextoInstante(await respuesta.json(), timestamp);
  } catch (error) {
    console.error(error);
    resumenInstanteCarrera.textContent = "No se pudo cargar el contexto para este instante.";
  }
}

async function cargarSerieCarrera() {
  instanteSeleccionadoCarrera = null;
  resumenInstanteCarrera.textContent = "Selecciona un punto de la curva para cargar contexto racing sincronizado.";
  climaInstanteCarrera.innerHTML = "";
  pilotosInstanteCarrera.innerHTML = "";
  if (!corridaReplaySeleccionada) {
    estadoAnalisisCarrera.textContent = "Esta sesion no tiene ninguna corrida de replay persistida: no hay serie que cargar.";
    Object.values(GRAFICOS_CARRERA).forEach((canvas) => canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height));
    return;
  }
  estadoAnalisisCarrera.textContent = "Cargando telemetria coordinada...";
  const pilotosSeleccionados = obtenerPilotosSeleccionados();
  if (!pilotosSeleccionados.length) {
    estadoAnalisisCarrera.textContent = "Selecciona al menos un piloto para cargar la serie.";
    Object.values(GRAFICOS_CARRERA).forEach((canvas) => canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height));
    return;
  }
  try {
    const series = await Promise.all(Object.entries(CONFIGURACION_SENALES_CARRERA).map(async ([signalName, configuracion]) => {
      const parametros = new URLSearchParams({
        replay_run_id: corridaReplaySeleccionada,
        signal: configuracion.signalName ?? signalName,
      });
      pilotosSeleccionados.forEach((driver) => parametros.append("drivers", driver));
      const respuesta = await fetch(`${API_BASE_URL}/racing/sessions/${sesionOpenF1Seleccionada}/replay-series?${parametros}`);
      if (!respuesta.ok) {
        throw new Error(`Error HTTP ${respuesta.status}`);
      }
      return [signalName, await respuesta.json()];
    }));
    const seriesPorSenal = Object.fromEntries(series);
    const puntosTiempo = seriesPorSenal.speed.map((mensaje) => new Date(mensaje.timestamp).getTime());
    const rangoComun = { inicio: Math.min(...puntosTiempo), fin: Math.max(...puntosTiempo) };
    Object.entries(seriesPorSenal).forEach(([signalName, mensajes]) => {
      dibujarSerieCarrera(mensajes, CONFIGURACION_SENALES_CARRERA[signalName], GRAFICOS_CARRERA[signalName], rangoComun);
    });
    const pilotosLeyenda = pilotosSeleccionados.map((numero) => {
      const piloto = pilotosOpenF1.find((item) => item.driver_number === numero);
      return `<span><i style="background:${COLORES_PILOTOS_OPENF1[numero] ?? `#${piloto?.team_colour ?? "94a3b8"}`}"></i>${escaparHtml(piloto?.name_acronym ?? numero)}</span>`;
    });
    leyendaAnalisisCarrera.innerHTML = pilotosLeyenda.join("");
    const sinTraza = pilotosSeleccionados.filter((numero) => !pilotosConTelemetriaReplay.has(numero));
    resumenAnalisisCarrera.textContent = `Velocidad, acelerador y freno durante ${((rangoComun.fin - rangoComun.inicio) / 1000).toFixed(2)} s de reloj deportivo. Los pilotos pueden ocupar puntos distintos del circuito.${sinTraza.length ? ` Sin traza MQTT en esta ejecucion: ${sinTraza.map((numero) => pilotosOpenF1.find((piloto) => piloto.driver_number === numero)?.name_acronym ?? numero).join(", ")}.` : ""}`;
    // La corrida se nombra en vez de un "replay v1" generico: es el filtro que
    // decide que muestras entran en el grafico.
    estadoAnalisisCarrera.textContent = `${pilotosSeleccionados.length} pilotos · ${seriesPorSenal.speed.length} puntos de velocidad · corrida ${corridaReplaySeleccionada}`;
    ultimaSerieCarrera = { ...rangoComun, series: seriesPorSenal, puntos: seriesPorSenal.speed.map((mensaje) => ({ tiempo: new Date(mensaje.timestamp).getTime() })), margen: { izquierdo: 66 }, areaAncho: GRAFICOS_CARRERA.speed.width - 96 };
  } catch (error) {
    console.error(error);
    estadoAnalisisCarrera.textContent = "No se pudieron cargar las series coordinadas.";
  }
}

// ---------------------------------------------------------------------------
// Seleccion de sesion y de corrida
//
// Las tres sesiones importadas se leen de `/racing/sessions`, que declara ademas
// si el paquete de cada una trae `car_data`. Las corridas se leen de
// `/racing/sessions/{key}/replay-runs`, que enumera por saltos de indice en vez de
// agregar millones de filas: el listado exhaustivo cuesta 23 segundos medidos y por
// eso no se expone.
// ---------------------------------------------------------------------------

function sesionSeleccionada() {
  return sesionesOpenF1.find((sesion) => sesion.session_key === sesionOpenF1Seleccionada) ?? null;
}

function limitesCorridaActual() {
  if (!corridaReplaySeleccionada) {
    return null;
  }
  return limitesPorCorrida.get(corridaReplaySeleccionada) ?? null;
}

function etiquetaSesion(sesion) {
  const fecha = sesion.date_start ? new Date(sesion.date_start).toISOString().slice(0, 10) : "sin fecha";
  const anio = sesion.date_start ? new Date(sesion.date_start).getUTCFullYear() : "s/f";
  const circuito = sesion.circuit_short_name ?? sesion.location ?? `Sesion ${sesion.session_key}`;
  const tipo = sesion.session_type ?? sesion.session_name ?? "sesion";
  // La ausencia de telemetria se anuncia ya en el propio selector: elegir una
  // sesion sin traza no deberia ser una sorpresa que se descubre al ver un panel
  // vacio.
  const sinTelemetria = sesion.telemetria?.disponible ? "" : " · solo contexto";
  return `${circuito} ${anio} · ${tipo} · ${fecha}${sinTelemetria}`;
}

function etiquetaCorrida(corrida) {
  const volumen = corrida.mensajes_estimados === null || corrida.mensajes_estimados === undefined
    ? "volumen no derivable"
    : `${corrida.mensajes_estimados.toLocaleString("es-AR")} mensajes`;
  const duracion = corrida.desde && corrida.hasta
    ? `${((new Date(corrida.hasta) - new Date(corrida.desde)) / 60000).toFixed(1)} min`
    : "duracion no derivable";
  const conAnalisis = limitesPorCorrida.has(corrida.replay_run_id) ? " · con analisis" : "";
  return `${corrida.replay_run_id} · ${volumen} · ${duracion}${conAnalisis}`;
}

async function cargarAnalisisDisponibles(sessionKey) {
  limitesPorCorrida = new Map();
  try {
    const respuesta = await fetch(`${API_BASE_URL}/racing/sessions/${sessionKey}/analysis`);
    if (!respuesta.ok) {
      return;
    }
    // La respuesta viene de la mas reciente a la mas antigua, de modo que la
    // primera entrada de cada corrida es la version vigente de su analisis.
    for (const analisis of await respuesta.json()) {
      if (!limitesPorCorrida.has(analisis.replay_run_id)) {
        limitesPorCorrida.set(analisis.replay_run_id, analisis.limits ?? {});
      }
    }
  } catch (error) {
    console.error(error);
  }
}

async function cargarCorridasReplay() {
  corridasReplaySesion = [];
  corridaReplaySeleccionada = null;
  cacheAnalisis.clear();
  await cargarAnalisisDisponibles(sesionOpenF1Seleccionada);
  try {
    const respuesta = await fetch(`${API_BASE_URL}/racing/sessions/${sesionOpenF1Seleccionada}/replay-runs`);
    if (!respuesta.ok) {
      throw new Error(`Error HTTP ${respuesta.status}`);
    }
    corridasReplaySesion = await respuesta.json();
  } catch (error) {
    console.error(error);
  }
  if (!corridasReplaySesion.length) {
    selectorCorridaReplay.innerHTML = "<option value=\"\">Sin corridas de replay persistidas</option>";
    selectorCorridaReplay.disabled = true;
    return;
  }
  selectorCorridaReplay.disabled = false;
  selectorCorridaReplay.innerHTML = corridasReplaySesion
    .map((corrida) => `<option value="${escaparHtml(corrida.replay_run_id)}">${escaparHtml(etiquetaCorrida(corrida))}</option>`)
    .join("");
  // Se prefiere una corrida que ya tenga analisis generado, y en su defecto la de
  // mayor volumen. Los sondeos de carga abarcan segundos de carrera y elegir uno
  // por descuido fue justamente el defecto que motivo fijar la corrida a mano.
  const preferida = corridasReplaySesion.find((corrida) => limitesPorCorrida.has(corrida.replay_run_id))
    ?? corridasReplaySesion[0];
  corridaReplaySeleccionada = preferida.replay_run_id;
  selectorCorridaReplay.value = corridaReplaySeleccionada;
}

async function cargarSesionesDisponibles() {
  try {
    const respuesta = await fetch(`${API_BASE_URL}/racing/sessions`);
    if (!respuesta.ok) {
      throw new Error(`Error HTTP ${respuesta.status}`);
    }
    sesionesOpenF1 = await respuesta.json();
  } catch (error) {
    console.error(error);
    declaracionTelemetriaSesion.textContent = "No se pudo recuperar la lista de sesiones importadas desde la API.";
    return false;
  }
  if (!sesionesOpenF1.length) {
    selectorSesionOpenF1.innerHTML = "<option value=\"\">Sin sesiones importadas</option>";
    declaracionTelemetriaSesion.textContent = "No hay ninguna sesion importada en la base.";
    return false;
  }
  selectorSesionOpenF1.innerHTML = sesionesOpenF1
    .map((sesion) => `<option value="${sesion.session_key}">${escaparHtml(etiquetaSesion(sesion))}</option>`)
    .join("");
  // Arranca en la primera sesion con telemetria declarada para que la vista por
  // defecto siga siendo una con datos, sin por eso esconder las demas.
  const inicial = sesionesOpenF1.find((sesion) => sesion.telemetria?.disponible) ?? sesionesOpenF1[0];
  sesionOpenF1Seleccionada = inicial.session_key;
  selectorSesionOpenF1.value = String(sesionOpenF1Seleccionada);
  await cargarCorridasReplay();
  return true;
}

function aplicarDisponibilidadTelemetria() {
  const sesion = sesionSeleccionada();
  const hayCorrida = Boolean(corridaReplaySeleccionada);
  SECCIONES_DEPENDIENTES_DE_TELEMETRIA.forEach((seccion) => {
    if (seccion) {
      seccion.hidden = !hayCorrida;
    }
  });
  declaracionTelemetriaSesion.classList.toggle("declaracion-ausente", !hayCorrida);
  if (!sesion) {
    return;
  }
  if (hayCorrida) {
    declaracionTelemetriaSesion.textContent = `Telemetria disponible: ${sesion.telemetria?.pilotos_car_data ?? 0} pilotos con car_data en el paquete importado y ${corridasReplaySesion.length} corrida(s) de replay persistida(s). Se analiza ${corridaReplaySeleccionada}.`;
    return;
  }
  // Declaracion de ausencia, no panel vacio. Es la diferencia entre decir "esta
  // sesion no tiene telemetria replicada" y dejar que el lector concluya que la
  // aplicacion se rompio.
  const motivo = sesion.telemetria?.motivo
    ?? "no hay corridas de replay persistidas para esta sesion";
  declaracionTelemetriaSesion.textContent = `Sin telemetria para esta sesion: ${motivo}. Se muestra el contexto oficial importado (${sesion.laps} vueltas, ${sesion.stints} stints, ${sesion.drivers} pilotos). Los paneles de telemetria por reloj deportivo, analisis por vuelta y trazabilidad del replay quedan ocultos porque no hay dato que mostrar, no porque la consulta haya fallado.`;
}

// Granularidad de muestreo y resolucion espacial.
//
// Las dos estaban escritas a mano con los valores de Silverstone: "car_data
// ~3.7 Hz" y "227 m de resolucion espacial", que es `5891 / 26`. Spa da 250 m y
// Suzuka 223 m, de modo que en cualquier otra sesion el texto afirmaba un numero
// ajeno. Ambas se leen ahora de los limites que el analisis persiste para la
// corrida elegida, y si no estan se declara la ausencia en vez de mostrar el
// numero de otra sesion.

function textoGranularidad() {
  const hz = limitesCorridaActual()?.muestreo_telemetria_hz;
  return typeof hz === "number"
    ? `car_data ~${hz} Hz`
    : "no declarada para esta corrida";
}

function textoResolucionMinisector() {
  const limites = limitesCorridaActual();
  const bloque = limites?.resolucion_minisector;
  if (bloque?.disponible) {
    return `Los minisectores dan ${bloque.resolucion_m} m de resolucion espacial: ${bloque.minisectores_por_vuelta} por vuelta, moda sobre ${bloque.vueltas_consideradas} vueltas de esta misma sesion.`;
  }
  if (bloque && !bloque.disponible) {
    return `Resolucion espacial de los minisectores no disponible: ${bloque.motivo}.`;
  }
  if (typeof limites?.resolucion_minisector_m === "number") {
    // Analisis anteriores a la derivacion por sesion: publican el valor pero no
    // sobre cuantas vueltas se apoya. Se muestra lo que hay, sin atribuirle una
    // procedencia que ese analisis no guardo.
    return `Los minisectores dan ${limites.resolucion_minisector_m} m de resolucion espacial segun los limites persistidos de esta corrida, que no declaran sobre cuantas vueltas se derivo.`;
  }
  return "El analisis de esta corrida no declara la resolucion espacial de los minisectores.";
}

async function obtenerComparacionPilotos(pilotosSeleccionados) {
  const parametros = pilotosSeleccionados.map((driver) => `drivers=${driver}`).join("&");
  const respuesta = await fetch(`${API_BASE_URL}/racing/sessions/${sesionOpenF1Seleccionada}/driver-comparison?${parametros}`);
  if (!respuesta.ok) {
    throw new Error("No se pudo recuperar la comparacion de pilotos.");
  }
  return respuesta.json();
}

function renderizarIdentidadSesion(sesion) {
  openF1Titulo.textContent = `${sesion.circuit_short_name} ${sesion.session_name} · Comparador operativo`;
  etiquetaCabecera.textContent = "Analisis historico de carrera";
  tituloCabecera.textContent = `${sesion.circuit_short_name} ${new Date(sesion.date_start).getUTCFullYear()} · ${sesion.session_name}`;
  resumenSesion.textContent = corridaReplaySeleccionada
    ? `${sesion.country_name} · sesion ${sesion.session_key} · replay historico persistido`
    : `${sesion.country_name} · sesion ${sesion.session_key} · contexto oficial sin telemetria replicada`;
  estadoOrigen.textContent = corridaReplaySeleccionada ? "OPENF1 HISTORICAL REPLAY" : "OPENF1 SOLO CONTEXTO";
  estadoOrigen.className = "estado-origen estado-openf1-replay";
}

function renderizarContextoOpenF1(sesion, pilotosSeleccionados, mensajesSeleccionados) {
  const muestras = mensajesSeleccionados === null
    ? "sin telemetria replicada para esta sesion"
    : `${mensajesSeleccionados.length} (max ${LIMITE_MUESTRAS_AUDITORIA_POR_PILOTO} por piloto)`;
  return [
    ["Sesion", sesion.session_key],
    ["Meeting", sesion.meeting_key],
    ["Seleccion", `${pilotosSeleccionados.length} pilotos`],
    ["Muestras", muestras],
    ["Granularidad", textoGranularidad()],
    ["Calidad", "observed_openf1"],
  ].map(([etiqueta, valor]) => `<div><dt>${escaparHtml(etiqueta)}</dt><dd>${escaparHtml(valor)}</dd></div>`).join("");
}

async function cargarReplayOpenF1() {
  if (!sesionOpenF1Seleccionada) {
    return;
  }
  aplicarDisponibilidadTelemetria();
  openF1EstadoCarga.textContent = "Consultando replay y contexto...";
  try {
    const [sesionRespuesta, pilotosRespuesta] = await Promise.all([
      fetch(`${API_BASE_URL}/racing/sessions/${sesionOpenF1Seleccionada}`),
      fetch(`${API_BASE_URL}/racing/sessions/${sesionOpenF1Seleccionada}/drivers`),
    ]);
    if (!sesionRespuesta.ok || !pilotosRespuesta.ok) {
      throw new Error("No se pudo recuperar el contexto OpenF1.");
    }
    const sesion = await sesionRespuesta.json();
    pilotosOpenF1 = await pilotosRespuesta.json();
    // La seleccion de pilotos pertenece a la sesion: al cambiar de sesion se
    // descartan los numeros que no corren en ella, en vez de arrastrarlos y pedir
    // comparaciones de un piloto ausente.
    pilotosSeleccionadosEstado = pilotosSeleccionadosEstado.filter(
      (numero) => pilotosOpenF1.some((piloto) => piloto.driver_number === numero),
    );
    renderizarCasillasPilotos();
    // El analisis por vuelta se apoya en el mismo catalogo de pilotos.
    poblarSelectorPilotosAnalisis();
    if (corridaReplaySeleccionada) {
      actualizarAnalisisVuelta();
    }
    renderizarIdentidadSesion(sesion);
    const pilotosSeleccionados = obtenerPilotosSeleccionados();
    if (!pilotosSeleccionados.length) {
      renderizarComparacionPilotos([]);
      cargarSerieCarrera();
      openF1EstadoCarga.textContent = "Selecciona al menos un piloto para iniciar la comparacion.";
      return;
    }
    if (!corridaReplaySeleccionada) {
      // Sesion importada sin telemetria replicada. El contexto oficial se muestra
      // igual porque existe y es util; lo que no hay es traza. La ausencia ya quedo
      // declarada en el selector, de modo que aca solo se evita pedir una corrida
      // que no existe y se deja de afirmar un volumen de muestras que no hubo.
      pilotosConTelemetriaReplay = new Set();
      renderizarCasillasPilotos();
      renderizarComparacionPilotos(await obtenerComparacionPilotos(pilotosSeleccionados));
      renderizarTablaOpenF1([]);
      openF1Resumen.textContent = `Sin corrida de replay · ${sesion.laps} vueltas · ${sesion.stints} stints · ${sesion.race_control_events} eventos de control.`;
      openF1Contexto.innerHTML = renderizarContextoOpenF1(sesion, pilotosSeleccionados, null);
      openF1EstadoCarga.textContent = "Sesion sin telemetria replicada: se muestra el contexto oficial importado.";
      return;
    }
    // Se pide una muestra acotada por piloto seleccionado en vez de la sesion
    // completa. La llamada anterior no filtraba por corrida ni por piloto y no
    // tenia tope: con la carrera persistida pedia 10.079.006 filas al backend.
    const [replayPorPiloto, comparacion] = await Promise.all([
      Promise.all(pilotosSeleccionados.map(async (numero) => {
        const parametros = new URLSearchParams({
          replay_run_id: corridaReplaySeleccionada,
          driver_number: String(numero),
          limite: String(LIMITE_MUESTRAS_AUDITORIA_POR_PILOTO),
        });
        const respuesta = await fetch(`${API_BASE_URL}/racing/sessions/${sesionOpenF1Seleccionada}/replay?${parametros}`);
        if (!respuesta.ok) {
          throw new Error("No se pudo recuperar el lote replay.");
        }
        return { numero, cuerpo: await respuesta.json() };
      })),
      obtenerComparacionPilotos(pilotosSeleccionados),
    ]);
    // Un piloto tiene traza si su propia consulta devolvio muestras. Antes esto se
    // deducia descargando la sesion entera y agrupando en el navegador.
    pilotosConTelemetriaReplay = new Set(
      replayPorPiloto.filter(({ cuerpo }) => cuerpo.total_devuelto > 0).map(({ numero }) => numero),
    );
    renderizarCasillasPilotos();
    const mensajesSeleccionados = replayPorPiloto.flatMap(({ cuerpo }) => cuerpo.muestras);
    openF1Resumen.textContent = `Corrida ${corridaReplaySeleccionada} · ${sesion.laps} vueltas · ${sesion.stints} stints · ${sesion.race_control_events} eventos de control.`;
    openF1Contexto.innerHTML = renderizarContextoOpenF1(sesion, pilotosSeleccionados, mensajesSeleccionados);
    renderizarComparacionPilotos(comparacion);
    cargarSerieCarrera();
    renderizarTablaOpenF1(mensajesSeleccionados);
    openF1EstadoCarga.textContent = `${mensajesSeleccionados.length} mensajes de muestra para auditoria de formato. No es el total de la corrida.`;
  } catch (error) {
    console.error(error);
    openF1EstadoCarga.textContent = "No se pudo cargar el replay desde la API.";
  }
}

function resumirCapacidadesProcesamiento(run) {
  const capacidades = run.inventory?.capabilities ?? {};
  const telemetria = capacidades.telemetry_drivers ?? { car_data: [], location: [] };
  return { carData: telemetria.car_data?.length ?? 0, location: telemetria.location?.length ?? 0 };
}

function traducirEstadoProcesamiento(status) {
  return ({ completed: "COMPLETO", partial: "PARCIAL", validated: "VALIDADO", failed: "FALLIDO", running: "EN PROCESO" })[status] ?? status;
}

function etiquetaCapacidad(nombre) {
  return ({
    drivers: "Pilotos",
    laps: "Vueltas",
    stints: "Stints",
    results: "Resultados",
    weather: "Clima",
    intervals: "Intervalos",
    overtakes: "Adelantamientos",
    pit_stops: "Pit stops",
    positions: "Posiciones",
    team_radio: "Radio",
    race_control: "Control de carrera",
  })[nombre] ?? nombre;
}

function etiquetaConteo(nombre) {
  return ({
    drivers: "Pilotos",
    laps: "Vueltas",
    stints: "Stints",
    session_result: "Resultados",
    weather: "Clima",
    intervals: "Intervalos",
    overtakes: "Adelantamientos",
    pit: "Pits",
    position: "Posiciones",
    team_radio: "Radio",
    race_control: "Control",
    sessions: "Sesion",
  })[nombre] ?? nombre;
}

function tituloSesionProcesada(run, contexto) {
  if (!contexto) {
    return `Sesion ${run.session_key}`;
  }
  const year = contexto.date_start ? new Date(contexto.date_start).getUTCFullYear() : "s/f";
  return `${contexto.circuit_short_name ?? contexto.location ?? "Sesion"} ${year} · ${contexto.session_name ?? run.session_key}`;
}

function obtenerConteo(run, ...keys) {
  const counts = run.counts ?? {};
  for (const key of keys) {
    if (counts[key] !== undefined) {
      return counts[key];
    }
  }
  return 0;
}

function resumenEstadoProcesamiento(run, issues, telemetria) {
  if (run.status === "partial") {
    return `${issues.length} advertencias · telemetria local no completa · solo contexto disponible.`;
  }
  return `Contexto del paquete local completo · telemetria detallada para ${telemetria.carData} pilotos.`;
}

function resumenEspacialProcesamiento(run) {
  const capacidades = run.inventory?.capabilities ?? {};
  const posiciones = capacidades.positions === true;
  const intervalos = capacidades.intervals === true;
  if (posiciones && intervalos) {
    return {
      estado: "Disponible",
      clase: "disponible",
      detalle: "Posiciones e intervalos importados; util para contexto espacial por tiempo.",
    };
  }
  const faltantes = [!posiciones ? "position.json" : null, !intervalos ? "intervals.json" : null].filter(Boolean);
  return {
    estado: "No disponible",
    clase: "no-disponible",
    detalle: `Faltan ${faltantes.join(" e ")}; no usar para comparacion espacial.`,
  };
}

async function cargarProcesamientoSesiones() {
  try {
    const respuesta = await fetch(`${API_BASE_URL}/processing/runs`);
    if (!respuesta.ok) {
      throw new Error("No se pudieron recuperar las corridas de procesamiento.");
    }
    const runs = await respuesta.json();
    const detalles = await Promise.all(runs.map(async (run) => {
      const [issuesRespuesta, contextoRespuesta] = await Promise.all([
        fetch(`${API_BASE_URL}/processing/runs/${run.run_id}/issues`),
        fetch(`${API_BASE_URL}/racing/sessions/${run.session_key}`),
      ]);
      return {
        issues: issuesRespuesta.ok ? await issuesRespuesta.json() : [],
        contexto: contextoRespuesta.ok ? await contextoRespuesta.json() : null,
      };
    }));
    tarjetasProcesamientoSesiones.innerHTML = runs.map((run, index) => {
      const issues = detalles[index].issues;
      const contexto = detalles[index].contexto;
      const capacidades = run.inventory?.capabilities ?? {};
      const capacidadesDisponibles = Object.entries(capacidades)
        .filter(([nombre, valor]) => nombre !== "telemetry_drivers" && valor === true)
        .map(([nombre]) => etiquetaCapacidad(nombre));
      const telemetria = resumirCapacidadesProcesamiento(run);
      const espacial = resumenEspacialProcesamiento(run);
      return `<article class="tarjeta-procesamiento-sesion estado-${escaparHtml(run.status)}">
        <header><div><strong>${escaparHtml(tituloSesionProcesada(run, contexto))}</strong><small>Run ${escaparHtml(run.run_id)} · sesion ${escaparHtml(run.session_key)}</small></div><span>${escaparHtml(traducirEstadoProcesamiento(run.status))}</span></header>
        <p class="resumen-procesamiento">${escaparHtml(resumenEstadoProcesamiento(run, issues, telemetria))}</p>
        <p class="resultado-espacial ${escaparHtml(espacial.clase)}"><strong>Resultado espacial: ${escaparHtml(espacial.estado)}</strong><br>${escaparHtml(espacial.detalle)} No implica distancia, trazada ni curvas reales.</p>
        <div class="metricas-procesamiento">
          <span><strong>${escaparHtml(obtenerConteo(run, "drivers"))}</strong>Pilotos</span>
          <span><strong>${escaparHtml(obtenerConteo(run, "laps"))}</strong>Vueltas</span>
          <span><strong>${escaparHtml(obtenerConteo(run, "stints"))}</strong>Stints</span>
          <span><strong>${escaparHtml(obtenerConteo(run, "weather"))}</strong>Clima</span>
          <span><strong>${escaparHtml(issues.length)}</strong>Alertas</span>
        </div>
        <p class="telemetria-procesamiento">Telemetria local: car_data ${escaparHtml(telemetria.carData)} pilotos · location ${escaparHtml(telemetria.location)} pilotos</p>
        <details class="detalles-procesamiento"><summary>Ver capacidades y advertencias</summary>
          <p>Contexto: ${escaparHtml(capacidadesDisponibles.join(", ") || "sin contexto declarado")}</p>
          <ul class="advertencias-procesamiento">${issues.length ? issues.map((issue) => `<li>${escaparHtml(issue.message)}</li>`).join("") : "<li>Sin advertencias registradas.</li>"}</ul>
        </details>
      </article>`;
    }).join("");
    estadoProcesamientoSesiones.textContent = `${runs.length} corridas procesadas disponibles.`;
  } catch (error) {
    console.error(error);
    estadoProcesamientoSesiones.textContent = "No se pudieron cargar las sesiones procesadas.";
  }
}


// ---------------------------------------------------------------------------
// Camino en vivo
// ---------------------------------------------------------------------------
//
// No consulta la base. Abre una conexion de eventos enviados por el servidor y
// recibe cada mensaje al llegar, sin volver a preguntar. La telemetria va en una
// sola direccion, de modo que un canal bidireccional resolveria un problema que
// no existe.
//
// Que sea un camino distinto del historico es lo que vuelve significativa la
// comparacion entre operacion en vivo y post-sesion.

const panelVivo = document.getElementById("panel-vivo");
const vivoEstado = document.getElementById("vivo-estado");
const vivoTarjetas = document.getElementById("vivo-tarjetas");
const vivoDiagnostico = document.getElementById("vivo-diagnostico");

// Ultimo valor de cada senal. El flujo trae un mensaje por senal, de modo que la
// vista se arma acumulando y no esperando un paquete completo.
const ultimoPorSenal = new Map();
let fuenteEnVivo = null;
let mensajesEnVivo = 0;
let latenciaMs = null;
let pintadoPendiente = false;

const TARJETAS_VIVO = {
  speed: { elemento: "vivo-velocidad", formato: (v) => Math.round(v) },
  gear_selected: {
    elemento: "vivo-marcha",
    // La marcha atras llega como -1 y el punto muerto como 0. Mostrarlos como
    // numeros seria ilegible para quien mira la pantalla.
    formato: (v) => (v === -1 ? "R" : v === 0 ? "N" : String(v)),
  },
  engine_speed: { elemento: "vivo-rpm", formato: (v) => Math.round(v).toLocaleString("es-AR") },
  throttle_position: { elemento: "vivo-acelerador", formato: (v) => v.toFixed(0) },
  brake_position: { elemento: "vivo-freno", formato: (v) => v.toFixed(0) },
  drs_open: { elemento: "vivo-drs", formato: (v) => (v ? "ABIERTO" : "cerrado") },
  lap_number: { elemento: "vivo-vuelta", formato: (v) => String(v) },
  lap_distance: { elemento: "vivo-distancia", formato: (v) => v.toFixed(0) },
};

function registrarMensajeEnVivo(mensaje) {
  ultimoPorSenal.set(mensaje.signal_name, mensaje);
  registrarEnCatalogo(mensaje);
  acumularEnTraza(mensaje);
  instanteUltimoMensaje = performance.now();
  mensajesEnVivo += 1;

  // La latencia se mide, no se estima: ambos instantes viajan en el mensaje.
  const publicado = mensaje?.metadata?.extra?.published_at_utc;
  if (publicado && mensaje._recibido_utc) {
    const delta = Date.parse(mensaje._recibido_utc) - Date.parse(publicado);
    if (Number.isFinite(delta)) {
      latenciaMs = latenciaMs === null ? delta : latenciaMs * 0.9 + delta * 0.1;
    }
  }

  // Se pinta una vez por cuadro y no una vez por mensaje: a veinte hercios y con
  // ocho senales llegan ciento sesenta mensajes por segundo, y redibujar en cada
  // uno gastaria mas tiempo en la pantalla que en los datos.
  if (!pintadoPendiente) {
    pintadoPendiente = true;
    requestAnimationFrame(pintarEnVivo);
  }
}

function pintarEnVivo() {
  pintadoPendiente = false;
  if (!ultimoPorSenal.size) {
    return;
  }
  vivoTarjetas.hidden = false;
  vivoDiagnostico.hidden = false;
  dibujarTrazas();

  for (const [senal, config] of Object.entries(TARJETAS_VIVO)) {
    const elemento = document.getElementById(config.elemento);
    if (!elemento) continue;
    const mensaje = ultimoPorSenal.get(senal);
    elemento.textContent = mensaje === undefined ? "—" : config.formato(mensaje.value);
  }

  const cualquiera = ultimoPorSenal.values().next().value;
  document.getElementById("vivo-mensajes").textContent = mensajesEnVivo.toLocaleString("es-AR");
  document.getElementById("vivo-latencia").textContent =
    latenciaMs === null ? "no declarada" : `${Math.round(latenciaMs)} ms`;
  document.getElementById("vivo-ultimo").textContent =
    cualquiera?.timestamp ? new Date(cualquiera.timestamp).toLocaleTimeString("es-AR") : "—";

  // El origen se lee del mensaje, no se asume por el canal. Los dos viajan por
  // el mismo topico: la consola en vivo y la reproduccion de una captura. Que la
  // vista diga "en vivo" mientras muestra una grabacion seria el mismo defecto
  // de procedencia que este trabajo le reclama a las fuentes ajenas.
  const origen = cualquiera?.metadata?.extra?.origen_adquisicion;
  const reproducido = origen === "captura_reproducida";
  const marcaOrigen = document.getElementById("vivo-origen");
  if (marcaOrigen) {
    marcaOrigen.hidden = origen === undefined;
    marcaOrigen.textContent = reproducido ? "CAPTURA REPRODUCIDA" : "CONSOLA EN VIVO";
    marcaOrigen.classList.toggle("marca-origen-reproducido", reproducido);
  }

  const sesion = cualquiera?.session_id;
  if (sesion) {
    const encabezado = reproducido ? "F1 25 reproducido" : "F1 25 en vivo";
    document.getElementById("vivo-titulo").textContent = `${encabezado} — ${sesion}`;
  }
  vivoEstado.hidden = true;
}

// ---------------------------------------------------------------------------
// Trazas en vivo
// ---------------------------------------------------------------------------
//
// Una tarjeta muestra el instante; una traza muestra el gesto. Una frenada, una
// salida de curva o un cambio de marcha no se leen en un numero suelto: se leen
// como forma.
//
// El catalogo **no esta escrito aca**. Se arma con las senales que efectivamente
// llegan, y de cada una se toman la unidad y el paquete de origen que el propio
// mensaje declara. Una lista fija obligaria a tocar esta pagina cada vez que el
// adaptador aprende un canal nuevo, que es exactamente la duplicacion que dejo
// la energia y el dano fuera de la base.
//
// Se dibuja sobre lienzo y no con una biblioteca de graficos: son lineas sobre
// una ventana movil, y una dependencia nueva costaria mas de lo que resuelve.

// Cuantas muestras conserva cada traza. A la frecuencia declarada por el juego
// —veinte por segundo— son unos treinta segundos de historia, que es lo que dura
// una secuencia completa de frenada, curva y salida.
const MUESTRAS_POR_TRAZA = 600;

// Los 4 MJ **no son la capacidad** del acumulador: el reglamento no fija ninguna.
// Son el maximo admitido de diferencia entre la carga maxima y la minima
// mientras el vehiculo esta en pista. El porcentaje que se muestra es sobre esa
// franja utilizable, no sobre un deposito, y es tambien como lo lee el tablero
// del propio juego.
const ERS_FRANJA_UTIL_J = 4000000;

// Nombre legible de cada paquete, para agrupar el catalogo por familia.
const FAMILIAS = {
  car_telemetry: "Conduccion y motor",
  lap_data: "Vuelta, posicion y boxes",
  car_status: "Energia, combustible y neumatico",
  car_damage: "Dano y desgaste",
};

// Las cuatro ruedas, en el orden del protocolo. Se usa para reconocer que
// cuatro senales son la misma magnitud medida en distintos lugares y dibujarlas
// juntas: comparar ruedas entre si es el uso normal de esos canales.
const RUEDAS = [
  { sufijo: "rear_left", nombre: "trasera izq.", color: "#4ea8ff" },
  { sufijo: "rear_right", nombre: "trasera der.", color: "#4ade80" },
  { sufijo: "front_left", nombre: "delantera izq.", color: "#fbbf24" },
  { sufijo: "front_right", nombre: "delantera der.", color: "#f87171" },
];

// Combinaciones que se dibujan juntas porque solo tienen sentido comparadas.
// Es la unica parte escrita a mano, y se justifica: que acelerador y freno vayan
// en el mismo lienzo no se deduce de los datos, se sabe de como se lee una
// telemetria.
const COMBINACIONES = {
  pedales: {
    etiqueta: "Acelerador y freno",
    familia: "car_telemetry",
    unidad: "%",
    series: [
      { senal: "throttle_position", nombre: "acelerador", color: "#4ade80" },
      { senal: "brake_position", nombre: "freno", color: "#f87171" },
    ],
  },
  // El aleron movil se lee de tres canales que llegan en tres paquetes
  // distintos, y por eso el catalogo los reparte en tres grupos. Juntos cuentan
  // una secuencia: la distancia baja hasta cero, el permiso se concede, y recien
  // ahi el aleron puede abrirse. Separados hay que reconstruir esa secuencia de
  // memoria mirando tres lienzos.
  //
  // La distancia se dibuja normalizada sobre su propio maximo observado, porque
  // esta en metros y los otros dos son booleanos: en un eje comun de cero a uno,
  // los tres se leen a la vez sin que la escala de uno aplaste a los otros.
  aleron: {
    etiqueta: "Aleron movil",
    familia: "car_telemetry",
    unidad: "bool",
    series: [
      { senal: "drs_open", nombre: "abierto", color: "#4ade80" },
      { senal: "drs_allowed", nombre: "permitido", color: "#fbbf24" },
      { senal: "drs_activation_distance", nombre: "faltan (m)", color: "#4ea8ff",
        normalizar: true },
    ],
  },
};

// Seleccion inicial. Son las que se miran mientras se maneja; el resto esta a un
// clic. Guardar la seleccion en el navegador evita rearmarla en cada recarga.
const SELECCION_POR_DEFECTO = ["speed", "pedales", "aleron", "ers_stored_energy"];
const CLAVE_SELECCION = "tesis.trazas.seleccion";

const graficasVivo = document.getElementById("vivo-graficas");
const catalogoVivo = document.getElementById("vivo-catalogo");
const grillaTrazas = document.getElementById("vivo-trazas");

const panelAnotaciones = document.getElementById("vivo-anotaciones");
const listaAnotaciones = document.getElementById("vivo-lista-anotaciones");
const conteoAnotaciones = document.getElementById("vivo-conteo-anotaciones");
const avisoReglasCiegas = document.getElementById("vivo-reglas-ciegas");

// Las anotaciones se guardan por identidad y no en una lista.
//
// Un incidente se emite **dos veces**: al empezar, para que el aviso llegue a
// tiempo, y al cerrarse, ya con su duracion medida. Son la misma cosa, y
// acumularlas mostraria el doble de incidentes de los que ocurrieron.
const anotacionesPorId = new Map();
let proximaAnotacionSuelta = -1;

// La historia, indexada **por vehiculo y despues por senal**.
//
// Una sola capa por senal alcanzaba mientras se publicaba un unico vehiculo. Con
// dos conductores en pantalla dividida, las muestras de los dos caian en la misma
// serie y la traza dibujaba una linea que no describia a ninguno.
const historiaPorVehiculo = new Map();
const tiemposPorVehiculo = new Map();
const distanciaPorVehiculo = new Map();

// La sesion entera a resolucion reducida, por vehiculo y por senal.
//
// Se declara junto a los demas mapas de estado y no donde se usa: las funciones
// que limpian una sesion vieja lo tocan, y en JavaScript una constante todavia
// no inicializada lanza al leerse en lugar de dar indefinido.
const resumenPorVehiculo = new Map();
let modoSesionCompleta = false;
let intervaloResumen = 1;
// El instante absoluto de la primera muestra de la sesion.
//
// Las anotaciones viajan con el reloj de la sesion y el resumen con el tiempo
// transcurrido. Este valor es lo que traduce entre los dos, y sin el una
// anotacion no se puede ubicar sobre la traza.
let origenDeLaSesion = null;

// Que conductores hay y como se los muestra. El orden de llegada fija el color,
// de modo que un conductor no cambia de color al recargar la pagina.
const COLORES_CONDUCTOR = ["#4ea8ff", "#f59e0b", "#4ade80", "#f87171"];
const conductores = new Map();
let conductorElegido = null;
let compararConductores = true;

// La sesion que se esta mirando. Un identificador de vehiculo es
// `...:session:UID:car:N`, de modo que el mismo auto de dos carreras distintas
// son dos claves distintas.
let sesionEnPantalla = null;

function sesionDe(vehiculo) {
  const partes = String(vehiculo).split(":car:");
  return partes.length > 1 ? partes[0] : null;
}

// Descarta lo que quedo de una carrera anterior.
//
// El caso que lo motiva: al terminar una carrera y empezar otra sin recargar la
// pagina, el auto de la carrera vieja seguia registrado como un segundo
// conductor **y su traza quedaba congelada**, porque ya no le llegaba nada. La
// autora lo vio como una linea naranja estatica en todos los graficos, en una
// prueba de **un solo conductor**.
//
// El mecanismo se penso para pantalla dividida, donde los dos conductores son
// simultaneos. Nadie previo que una sesion nueva conviviera con la anterior.
function olvidarSesionesViejas(sesionActual) {
  if (!sesionActual || sesionEnPantalla === sesionActual) return;
  const habiaOtra = sesionEnPantalla !== null;
  sesionEnPantalla = sesionActual;
  if (!habiaOtra) return;

  for (const vehiculo of [...conductores.keys()]) {
    if (sesionDe(vehiculo) === sesionActual) continue;
    conductores.delete(vehiculo);
    historiaPorVehiculo.delete(vehiculo);
    tiemposPorVehiculo.delete(vehiculo);
    distanciaPorVehiculo.delete(vehiculo);
    resumenPorVehiculo.delete(vehiculo);
    if (conductorElegido === vehiculo) conductorElegido = null;
  }
  // Las anotaciones de la carrera anterior tampoco pertenecen a esta.
  for (const [clave, a] of [...anotacionesPorId.entries()]) {
    if (a.vehiculo && sesionDe(a.vehiculo) !== sesionActual) {
      anotacionesPorId.delete(clave);
    }
  }
  // El eje arranca de nuevo con la sesion nueva.
  origenDeLaSesion = null;
  dibujarSelectorDeConductor();
  dibujarAnotaciones();
}

function registrarConductor(vehiculo) {
  olvidarSesionesViejas(sesionDe(vehiculo));
  if (!vehiculo || conductores.has(vehiculo)) return;
  const i = conductores.size;
  conductores.set(vehiculo, {
    color: COLORES_CONDUCTOR[i % COLORES_CONDUCTOR.length],
    // El identificador es largo y termina en el indice del auto, que es lo
    // unico que distingue a un conductor de otro en la misma sesion.
    nombre: `auto ${String(vehiculo).split(":").pop()}`,
  });
  if (conductorElegido === null) conductorElegido = vehiculo;
  dibujarSelectorDeConductor();
}

// Que vehiculos se dibujan: el elegido, o todos si se esta comparando.
function vehiculosADibujar() {
  if (compararConductores && conductores.size > 1) return [...conductores.keys()];
  return conductorElegido ? [conductorElegido] : [...conductores.keys()];
}

// El selector solo aparece cuando hay mas de un conductor. Con uno solo seria un
// control que no decide nada, ocupando el lugar de algo que si informa.
function dibujarSelectorDeConductor() {
  const caja = document.getElementById("vivo-conductores");
  if (!caja) return;
  caja.hidden = conductores.size < 2;
  if (caja.hidden) return;

  caja.replaceChildren();
  for (const [vehiculo, info] of conductores) {
    const boton = document.createElement("button");
    boton.type = "button";
    boton.className = "pastilla-conductor";
    if (compararConductores || conductorElegido === vehiculo) {
      boton.classList.add("elegida");
    }
    boton.style.setProperty("--color-conductor", info.color);
    boton.textContent = info.nombre;
    boton.addEventListener("click", () => {
      conductorElegido = vehiculo;
      compararConductores = false;
      dibujarSelectorDeConductor();
      dibujarTrazas();
      dibujarAnotaciones();
    });
    caja.append(boton);
  }

  const comparar = document.createElement("button");
  comparar.type = "button";
  comparar.className = "pastilla-conductor pastilla-comparar";
  if (compararConductores) comparar.classList.add("elegida");
  comparar.textContent = "comparar";
  comparar.addEventListener("click", () => {
    compararConductores = !compararConductores;
    dibujarSelectorDeConductor();
    dibujarTrazas();
    dibujarAnotaciones();
  });
  caja.append(comparar);
}

function serieDe(vehiculo, senal) {
  return historiaPorVehiculo.get(vehiculo)?.get(senal) ?? [];
}

function tiemposDe(vehiculo, senal) {
  return tiemposPorVehiculo.get(vehiculo)?.get(senal) ?? [];
}

const historiaPorSenal = new Map();
// El instante de cada muestra, en paralelo a su valor. Es lo unico que las
// anotaciones y las trazas comparten, y por lo tanto lo unico que permite
// ubicar una sobre las otras.
const tiemposPorSenal = new Map();
// La anotacion senalada, si hay alguna. Las trazas marcan su instante.
let anotacionSenalada = null;
// Lo que cada senal declara de si misma: unidad y paquete de origen.
const catalogoSenales = new Map();
let seleccionTrazas = cargarSeleccion();
let catalogoDibujado = "";

function cargarSeleccion() {
  try {
    const guardada = window.localStorage.getItem(CLAVE_SELECCION);
    if (guardada) return new Set(JSON.parse(guardada));
  } catch (error) {
    // Un navegador que bloquea el almacenamiento no debe romper la vista: se
    // pierde la comodidad de recordar la seleccion, nada mas.
  }
  return new Set(SELECCION_POR_DEFECTO);
}

function guardarSeleccion() {
  try {
    window.localStorage.setItem(CLAVE_SELECCION, JSON.stringify([...seleccionTrazas]));
  } catch (error) {
    /* sin persistencia, la seleccion vale solo para esta sesion */
  }
}

// Convierte "tyre_wear_front_left" en {base: "tyre_wear", sufijo: "front_left"}.
function separarRueda(senal) {
  for (const rueda of RUEDAS) {
    const cola = `_${rueda.sufijo}`;
    if (senal.endsWith(cola)) {
      return { base: senal.slice(0, -cola.length), sufijo: rueda.sufijo };
    }
  }
  return null;
}

function etiquetaLegible(clave) {
  return clave.replace(/_/g, " ");
}

function registrarEnCatalogo(mensaje) {
  const senal = mensaje.signal_name;
  if (catalogoSenales.has(senal)) return;
  catalogoSenales.set(senal, {
    unidad: mensaje.unit,
    familia: mensaje?.metadata?.extra?.paquete ?? "otros",
  });
  // El catalogo se redibuja solo cuando aparece una senal nueva.
  catalogoDibujado = "";
}

// Arma las entradas del catalogo: combinaciones, grupos por rueda y senales
// individuales. Cada entrada sabe que series dibujar y en que rango.
function entradasDelCatalogo() {
  const entradas = new Map();
  const consumidas = new Set();

  for (const [clave, combinacion] of Object.entries(COMBINACIONES)) {
    const presentes = combinacion.series.filter((s) => catalogoSenales.has(s.senal));
    if (presentes.length < 2) continue;
    entradas.set(clave, { ...combinacion, series: presentes });
    presentes.forEach((s) => consumidas.add(s.senal));
  }

  // Las cuatro ruedas de una misma magnitud van juntas: se reconocen por el
  // sufijo, sin necesidad de enumerarlas.
  const porBase = new Map();
  for (const senal of catalogoSenales.keys()) {
    const partes = separarRueda(senal);
    if (!partes) continue;
    if (!porBase.has(partes.base)) porBase.set(partes.base, []);
    porBase.get(partes.base).push(senal);
  }
  for (const [base, senales] of porBase) {
    if (senales.length < 2) continue;
    const referencia = catalogoSenales.get(senales[0]);
    entradas.set(base, {
      etiqueta: etiquetaLegible(base),
      familia: referencia.familia,
      unidad: referencia.unidad,
      series: RUEDAS.filter((r) => catalogoSenales.has(`${base}_${r.sufijo}`)).map((r) => ({
        senal: `${base}_${r.sufijo}`,
        nombre: r.nombre,
        color: r.color,
      })),
    });
    senales.forEach((s) => consumidas.add(s));
  }

  for (const [senal, info] of catalogoSenales) {
    if (consumidas.has(senal)) continue;
    entradas.set(senal, {
      etiqueta: etiquetaLegible(senal),
      familia: info.familia,
      unidad: info.unidad,
      series: [{ senal, nombre: etiquetaLegible(senal), color: "#4ea8ff" }],
    });
  }
  return entradas;
}

// El rango sale de la unidad, no de una tabla por senal. Un porcentaje va de
// cero a cien por definicion; escalarlo a lo observado haria que un toque leve
// de freno se viera como una frenada a fondo. Lo demas se ajusta a lo observado,
// porque un eje fijo aplastaria un circuito lento contra uno rapido.
// La marca del contrato viene como cadena ISO. Se la pasa a segundos para poder
// compararla con el reloj que traen las anotaciones.
function instanteDe(marca) {
  if (typeof marca === "number") return marca;
  if (typeof marca !== "string") return null;
  const ms = Date.parse(marca);
  return Number.isNaN(ms) ? null : ms / 1000;
}

function rangoDe(entrada) {
  if (entrada.unidad === "%") return [0, 100];
  if (entrada.unidad === "bool") return [-0.1, 1.1];
  return "observado";
}

// La energia se declara en joules y se lee en porcentaje de carga.
function conversionDe(senal) {
  if (senal === "ers_stored_energy") return (j) => (j / ERS_FRANJA_UTIL_J) * 100;
  return (v) => v;
}

function acumularEnTraza(mensaje) {
  const valor = typeof mensaje.value === "boolean" ? Number(mensaje.value) : mensaje.value;
  if (typeof valor !== "number" || !Number.isFinite(valor)) return;
  const vehiculo = mensaje.vehicle_id ?? "sin-vehiculo";
  registrarConductor(vehiculo);
  if (!historiaPorVehiculo.has(vehiculo)) {
    historiaPorVehiculo.set(vehiculo, new Map());
    tiemposPorVehiculo.set(vehiculo, new Map());
  }
  const suHistoria = historiaPorVehiculo.get(vehiculo);
  const susTiempos = tiemposPorVehiculo.get(vehiculo);

  let suSerie = suHistoria.get(mensaje.signal_name);
  if (!suSerie) { suSerie = []; suHistoria.set(mensaje.signal_name, suSerie); }
  suSerie.push(valor);
  if (suSerie.length > MUESTRAS_POR_TRAZA) suSerie.shift();

  let susMarcas = susTiempos.get(mensaje.signal_name);
  if (!susMarcas) { susMarcas = []; susTiempos.set(mensaje.signal_name, susMarcas); }
  susMarcas.push(instanteDe(mensaje.timestamp));
  if (susMarcas.length > MUESTRAS_POR_TRAZA) susMarcas.shift();

  if (mensaje.signal_name === "lap_distance") {
    let d = distanciaPorVehiculo.get(vehiculo);
    if (!d) { d = []; distanciaPorVehiculo.set(vehiculo, d); }
    d.push(valor);
    if (d.length > MUESTRAS_POR_TRAZA) d.shift();
  }

  let serie = historiaPorSenal.get(mensaje.signal_name);
  if (serie === undefined) {
    serie = [];
    historiaPorSenal.set(mensaje.signal_name, serie);
  }
  serie.push(valor);
  // Ventana movil: lo viejo se descarta en lugar de acumularse. Una carrera son
  // treinta mil muestras por senal, y conservarlas todas para mostrar los
  // ultimos treinta segundos seria memoria gastada sin uso.
  if (serie.length > MUESTRAS_POR_TRAZA) serie.shift();

  let marcas = tiemposPorSenal.get(mensaje.signal_name);
  if (!marcas) {
    marcas = [];
    tiemposPorSenal.set(mensaje.signal_name, marcas);
  }
  marcas.push(instanteDe(mensaje.timestamp));
  if (marcas.length > MUESTRAS_POR_TRAZA) marcas.shift();
}

function dibujarCatalogo() {
  const entradas = entradasDelCatalogo();
  const firma = [...entradas.keys()].sort().join("|");
  if (firma === catalogoDibujado) {
    actualizarMarcasDelCatalogo();
    return;
  }
  catalogoDibujado = firma;

  const porFamilia = new Map();
  for (const [clave, entrada] of entradas) {
    if (!porFamilia.has(entrada.familia)) porFamilia.set(entrada.familia, []);
    porFamilia.get(entrada.familia).push([clave, entrada]);
  }

  catalogoVivo.replaceChildren();
  for (const [familia, lista] of porFamilia) {
    const grupo = document.createElement("div");
    grupo.className = "grupo-catalogo";
    const titulo = document.createElement("span");
    titulo.className = "titulo-grupo";
    titulo.textContent = FAMILIAS[familia] ?? familia;
    grupo.append(titulo);

    lista.sort((a, b) => a[1].etiqueta.localeCompare(b[1].etiqueta));
    for (const [clave, entrada] of lista) {
      const boton = document.createElement("button");
      boton.type = "button";
      boton.className = "chip-senal";
      boton.dataset.clave = clave;
      boton.textContent = entrada.etiqueta;
      boton.title = `${entrada.etiqueta} (${entrada.unidad})`;
      boton.addEventListener("click", () => alternarTraza(clave));
      grupo.append(boton);
    }
    catalogoVivo.append(grupo);
  }
  actualizarMarcasDelCatalogo();
}

function actualizarMarcasDelCatalogo() {
  for (const boton of catalogoVivo.querySelectorAll(".chip-senal")) {
    boton.classList.toggle("chip-elegido", seleccionTrazas.has(boton.dataset.clave));
  }
  const conteo = document.getElementById("vivo-conteo-senales");
  if (conteo) {
    conteo.textContent =
      `${seleccionTrazas.size} de ${catalogoSenales.size} senales`;
  }
}

function alternarTraza(clave) {
  if (seleccionTrazas.has(clave)) seleccionTrazas.delete(clave);
  else seleccionTrazas.add(clave);
  guardarSeleccion();
  actualizarMarcasDelCatalogo();
  sincronizarLienzos();
  dibujarTrazas();
}

// Crea o quita lienzos para que haya exactamente uno por traza elegida.
function sincronizarLienzos() {
  const entradas = entradasDelCatalogo();
  const elegidas = [...seleccionTrazas].filter((clave) => entradas.has(clave));

  const existentes = new Map(
    [...grillaTrazas.children].map((figura) => [figura.dataset.clave, figura]),
  );
  for (const [clave, figura] of existentes) {
    if (!elegidas.includes(clave)) figura.remove();
  }

  for (const clave of elegidas) {
    if (existentes.has(clave)) continue;
    const entrada = entradas.get(clave);
    const figura = document.createElement("figure");
    figura.className = "grafica-vivo";
    figura.dataset.clave = clave;

    const pie = document.createElement("figcaption");
    const nombre = document.createElement("span");
    nombre.textContent = entrada.etiqueta;
    const unidad = document.createElement("span");
    unidad.className = "unidad";
    unidad.textContent = clave === "ers_stored_energy" ? "%" : entrada.unidad;
    pie.append(nombre, unidad);

    if (entrada.series.length > 1) {
      const leyenda = document.createElement("span");
      leyenda.className = "leyenda";
      for (const serie of entrada.series) {
        const marca = document.createElement("i");
        marca.style.background = serie.color;
        const texto = document.createElement("span");
        texto.textContent = serie.nombre;
        leyenda.append(marca, texto);
      }
      pie.append(leyenda);
    }

    // Tocar el titulo amplia el grafico a todo el ancho.
    //
    // Una miniatura alcanza para ver la forma de una senal y no para leer un
    // instante. Con el eje de la sesion completa el problema se agrava: media
    // hora repartida en trescientos cincuenta pixeles deja cada segundo en
    // menos de un pixel, y las marcas de anotacion quedan encimadas.
    //
    // Se amplia **uno a la vez**: dos graficos grandes no entran en la pantalla
    // y obligarian a desplazarse para compararlos, que es justo lo que la vista
    // superpuesta evita.
    const lupa = document.createElement("span");
    lupa.className = "lupa";
    lupa.textContent = "ampliar";
    pie.append(lupa);
    pie.tabIndex = 0;
    pie.setAttribute("role", "button");
    const alternarAmpliada = () => {
      const yaEstaba = figura.classList.contains("ampliada");
      for (const otra of grillaTrazas.querySelectorAll(".ampliada")) {
        otra.classList.remove("ampliada");
        const suLupa = otra.querySelector(".lupa");
        if (suLupa) suLupa.textContent = "ampliar";
      }
      if (!yaEstaba) {
        figura.classList.add("ampliada");
        lupa.textContent = "reducir";
      }
      dibujarTrazas();
    };
    pie.addEventListener("click", alternarAmpliada);
    pie.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        alternarAmpliada();
      }
    });

    const lienzo = document.createElement("canvas");
    lienzo.height = 110;
    figura.append(pie, lienzo);
    grillaTrazas.append(figura);
  }

  if (!elegidas.length) {
    const vacio = document.createElement("p");
    vacio.className = "aviso-vacio";
    vacio.textContent = "Ninguna senal elegida. Toque una del catalogo para verla.";
    grillaTrazas.append(vacio);
  }
}

//: Ancho reservado a la izquierda para los valores del eje.
//
// Antes los numeros se escribian encima del lienzo, sobre la propia traza, y
// quedaban ilegibles justo donde la linea pasaba. Reservar la banda cuesta
// espacio de dibujo y hace que la escala se pueda leer, que es para lo que esta.
const BANDA_EJE = 46;

//: Cuantas divisiones tiene el eje. Tres —minimo, medio y maximo— alcanzan para
//: ubicar un valor sin convertir el lienzo en una grilla.
const DIVISIONES_EJE = 3;

function formatearValor(valor, unidad) {
  const absoluto = Math.abs(valor);
  if (unidad === "J") return `${(valor / 1e6).toFixed(1)}M`;
  if (absoluto >= 1000) return valor.toFixed(0);
  if (absoluto >= 100) return valor.toFixed(0);
  if (absoluto >= 10) return valor.toFixed(1);
  return valor.toFixed(2);
}

// Dibuja las anotaciones sobre la traza, en el instante en que ocurrieron.
//
// **Es lo que las saca de la lista de abajo.** Una anotacion es un instante con
// un lugar, y hasta ahora no tenia donde vivir dentro del grafico porque el eje
// se desplazaba y ese instante desaparecia a los treinta segundos. Con el eje
// que abarca la sesion, cada anotacion tiene una abscisa estable.
//
// Se dibujan en todos los graficos y no solo en el del canal que las produjo:
// lo que se quiere leer es **que estaban haciendo las demas senales cuando
// ocurrio**, que es justamente lo que una lista aparte no puede mostrar.
function dibujarMarcasDeAnotacion(ctx, alto, duracion, zona) {
  if (origenDeLaSesion === null || duracion <= 0) return;
  const vehiculos = new Set(vehiculosADibujar());
  for (const anotacion of anotacionesPorId.values()) {
    if (anotacion.reloj_s === undefined) continue;
    // Una anotacion pertenece a un conductor: si ese conductor no se esta
    // dibujando, su anotacion tampoco.
    if (anotacion.vehiculo && vehiculos.size && !vehiculos.has(anotacion.vehiculo)) {
      continue;
    }
    const segundo = anotacion.reloj_s - origenDeLaSesion;
    if (segundo < 0 || segundo > duracion) continue;
    const x = BANDA_EJE + (segundo / duracion) * zona;
    // La que esta senalada se dibuja fuerte y el resto tenue. Todas visibles y
    // una destacada: ver solo la elegida obliga a recorrer la lista para saber
    // si hubo algo mas, que es el trabajo que la vista deberia ahorrar.
    const senalada = anotacionSenalada === anotacion.reloj_s;
    ctx.strokeStyle = COLOR_MARCA_ANOTACION[anotacion.nivel] ?? "#94a3b8";
    ctx.lineWidth = senalada ? 2 : 1;
    ctx.globalAlpha = senalada ? 0.95 : 0.3;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, alto - 12);
    ctx.stroke();
    // Un punto en la cabecera para que la marca se vea aunque la traza pase por
    // encima. Sin el, una linea tenue sobre una zona densa desaparece.
    ctx.fillStyle = ctx.strokeStyle;
    ctx.globalAlpha = senalada ? 1 : 0.55;
    ctx.beginPath();
    ctx.arc(x, 3, senalada ? 3 : 2.2, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalAlpha = 1;
}

// Rotula el eje de tiempo de la vista de sesion completa.
//
// Sin rotulo, un eje que crece es indistinguible de uno que se desplaza: las dos
// vistas se ven igual y quien mira no sabe cual esta leyendo. El minuto y segundo
// al pie lo declara.
function dibujarEjeDeTiempo(ctx, ancho, alto, duracion, zona) {
  const marcas = 4;
  ctx.globalAlpha = 0.45;
  ctx.textAlign = "center";
  ctx.textBaseline = "bottom";
  for (let i = 0; i <= marcas; i += 1) {
    const segundo = (duracion * i) / marcas;
    const x = BANDA_EJE + (segundo / duracion) * zona;
    const minutos = Math.floor(segundo / 60);
    const resto = Math.round(segundo % 60);
    ctx.fillText(`${minutos}:${String(resto).padStart(2, "0")}`,
                 Math.min(ancho - 12, Math.max(BANDA_EJE + 12, x)), alto - 1);
  }
  ctx.globalAlpha = 1;
  ctx.textAlign = "left";
}

function dibujarUnaTraza(figura, entrada, clave) {
  const lienzo = figura.querySelector("canvas");
  if (!lienzo) return;

  const densidad = window.devicePixelRatio || 1;
  const ancho = lienzo.clientWidth;
  // El alto sale del lienzo y no de una constante: un grafico ampliado mide
  // mas, y con el alto fijo la traza se dibujaba en la franja superior dejando
  // el resto en blanco.
  const alto = lienzo.clientHeight || 110;
  if (!ancho) return;
  // Se comprueban **las dos** dimensiones. Mirando solo el ancho, un grafico
  // que se amplia sin cambiar de ancho ---el unico de su fila--- conservaba el
  // bufer de ciento diez pixeles y la traza salia aplastada contra el borde
  // superior, con el resto en blanco.
  if (lienzo.width !== Math.round(ancho * densidad)
      || lienzo.height !== Math.round(alto * densidad)) {
    lienzo.width = Math.round(ancho * densidad);
    lienzo.height = Math.round(alto * densidad);
  }
  const ctx = lienzo.getContext("2d");
  ctx.setTransform(densidad, 0, 0, densidad, 0, 0);
  ctx.clearRect(0, 0, ancho, alto);

  // El color se lee del tema: el guion asumia fondo oscuro y esta vista es clara.
  const tinta = getComputedStyle(lienzo).color;
  ctx.fillStyle = tinta;
  ctx.strokeStyle = tinta;
  ctx.font = "10px system-ui, sans-serif";

  // Cada conductor aporta sus propias series. Con uno solo el resultado es el de
  // siempre; con dos, las lineas se superponen sobre el mismo lienzo y **la
  // separacion entre ellas es la diferencia**, que es lo que se quiere leer.
  // Ponerlas en graficos separados obliga a alternar la mirada y la diferencia
  // se pierde.
  const vehiculos = vehiculosADibujar();
  const combinaciones = [];
  for (const vehiculo of vehiculos) {
    for (const s of entrada.series) {
      combinaciones.push({
        ...s,
        // Con un conductor manda el color de la senal; con dos manda el del
        // conductor, porque lo que se esta comparando son los conductores.
        color: vehiculos.length > 1
          ? (conductores.get(vehiculo)?.color ?? s.color) : s.color,
        vehiculo,
      });
    }
  }

  const series = (combinaciones.length ? combinaciones : entrada.series)
    .map((s) => {
      let valores = (s.vehiculo
        ? serieDe(s.vehiculo, s.senal)
        : (historiaPorSenal.get(s.senal) ?? [])).map(conversionDe(s.senal));
      // Una serie marcada para normalizar comparte lienzo con otras de distinta
      // unidad. Se la lleva a la escala comun sobre su propio maximo observado,
      // que es lo que permite leer las tres a la vez.
      if (s.normalizar && valores.length) {
        const tope = Math.max(...valores.map(Math.abs), 1);
        valores = valores.map((v) => v / tope);
      }
      // En la vista de sesion completa se usa el resumen y no la ventana.
      const intervalos = s.vehiculo
        ? (resumenPorVehiculo.get(s.vehiculo)?.get(s.senal) ?? null)
        : null;
      return { color: s.color, valores, intervalos };
    })
    .filter((s) => s.valores.length > 1
      || (modoSesionCompleta && s.intervalos && s.intervalos.length > 1));

  if (!series.length) {
    ctx.globalAlpha = 0.4;
    ctx.fillText("sin muestras todavia", BANDA_EJE + 8, alto / 2);
    ctx.globalAlpha = 1;
    return;
  }

  let minimo;
  let maximo;
  const rango = rangoDe(entrada);
  if (rango === "observado") {
    const todos = series.flatMap((s) => s.valores);
    minimo = Math.min(...todos);
    maximo = Math.max(...todos);
    const margen = (maximo - minimo) * 0.08 || 1;
    minimo -= margen;
    maximo += margen;
  } else {
    minimo = rango[0];
    maximo = rango[1];
  }

  const zona = ancho - BANDA_EJE;
  const escalaY = (valor) =>
    alto - ((valor - minimo) / (maximo - minimo || 1)) * alto;

  // Divisiones con su valor a la izquierda. La linea guia cruza el lienzo entero
  // para que un valor pueda seguirse de un extremo al otro.
  const unidad = clave === "ers_stored_energy" ? "%" : entrada.unidad;
  for (let i = 0; i < DIVISIONES_EJE; i += 1) {
    const proporcion = i / (DIVISIONES_EJE - 1);
    const valor = maximo - proporcion * (maximo - minimo);
    let y = escalaY(valor);
    // Las lineas extremas se corren hacia adentro para no quedar cortadas.
    y = Math.min(alto - 1, Math.max(1, y));

    ctx.globalAlpha = 0.14;
    ctx.beginPath();
    ctx.moveTo(BANDA_EJE, y);
    ctx.lineTo(ancho, y);
    ctx.stroke();

    ctx.globalAlpha = 0.6;
    ctx.textAlign = "right";
    ctx.textBaseline = i === 0 ? "top" : (i === DIVISIONES_EJE - 1 ? "bottom" : "middle");
    ctx.fillText(formatearValor(valor, unidad), BANDA_EJE - 6, y);
  }
  ctx.globalAlpha = 1;

  // En la vista de sesion completa el eje va del inicio al instante actual, y
  // cada intervalo se dibuja como un segmento vertical entre su minimo y su
  // maximo. Un trazo entre medias suavizaria justo los picos que las
  // anotaciones senalan; el segmento declara el rango que realmente ocurrio.
  if (modoSesionCompleta) {
    const duracion = duracionDeLaSesion();
    if (duracion > 0) {
      for (const serie of series) {
        if (!serie.intervalos || !serie.intervalos.length) continue;
        ctx.strokeStyle = serie.color;
        ctx.lineWidth = 1;
        ctx.globalAlpha = 0.85;
        ctx.beginPath();
        for (const [segundo, bajo, alto_] of serie.intervalos) {
          const x = BANDA_EJE + (segundo / duracion) * zona;
          ctx.moveTo(x, escalaY(bajo));
          ctx.lineTo(x, escalaY(alto_));
        }
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
      dibujarMarcasDeAnotacion(ctx, alto, duracion, zona);
      dibujarEjeDeTiempo(ctx, ancho, alto, duracion, zona);
      return;
    }
  }

  const paso = zona / (MUESTRAS_POR_TRAZA - 1);
  for (const serie of series) {
    const desplazamiento = ancho - (serie.valores.length - 1) * paso;
    ctx.strokeStyle = serie.color;
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    serie.valores.forEach((valor, i) => {
      const x = Math.max(BANDA_EJE, desplazamiento + i * paso);
      const y = escalaY(valor);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();

    // El valor actual, marcado en el extremo derecho. Es el que se mira mientras
    // se conduce, y en una traza de trescientas muestras es el mas dificil de
    // distinguir.
    const ultimo = serie.valores[serie.valores.length - 1];
    const y = escalaY(ultimo);
    ctx.fillStyle = serie.color;
    ctx.beginPath();
    ctx.arc(ancho - 2, y, 2.5, 0, Math.PI * 2);
    ctx.fill();
  }

  // La anotacion senalada, ubicada sobre la traza por su instante.
  //
  // Es lo que conecta las dos mitades de la vista: la lista dice que paso y
  // cuando, y la traza muestra que hacian los canales en ese momento. Sin la
  // marca hay que buscar el instante a ojo, que es exactamente lo que la lista
  // deberia ahorrar.
  if (anotacionSenalada !== null) {
    const vehiculoDeReferencia = vehiculosADibujar()[0];
    const senalDeReferencia = entrada.series
      .map((s) => s.senal)
      .find((s) => tiemposDe(vehiculoDeReferencia, s).length > 1);
    const marcas = senalDeReferencia
      ? tiemposDe(vehiculoDeReferencia, senalDeReferencia) : null;
    if (marcas && marcas.length > 1) {
      const primero = marcas[0];
      const ultimo = marcas[marcas.length - 1];
      const t = anotacionSenalada;
      if (t >= primero && t <= ultimo && ultimo > primero) {
        const x = BANDA_EJE + ((t - primero) / (ultimo - primero)) * zona;
        ctx.save();
        ctx.strokeStyle = "#d1495b";
        ctx.lineWidth = 1.5;
        ctx.setLineDash([4, 3]);
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, alto);
        ctx.stroke();
        ctx.restore();
      }
    }
  }

  ctx.fillStyle = tinta;
  ctx.textAlign = "left";
  ctx.textBaseline = "alphabetic";
}

function dibujarTrazas() {
  if (!catalogoSenales.size) return;
  graficasVivo.hidden = false;
  dibujarCatalogo();
  if (!grillaTrazas.children.length) sincronizarLienzos();
  const entradas = entradasDelCatalogo();
  for (const figura of grillaTrazas.querySelectorAll(".grafica-vivo")) {
    const entrada = entradas.get(figura.dataset.clave);
    if (entrada) dibujarUnaTraza(figura, entrada, figura.dataset.clave);
  }
}

// El lienzo se dimensiona al ancho real, de modo que un cambio de tamano lo
// deja estirado hasta el proximo mensaje. Con el flujo detenido, para siempre.
window.addEventListener("resize", () => dibujarTrazas());

const botonLimpiar = document.getElementById("vivo-limpiar-trazas");
if (botonLimpiar) {
  botonLimpiar.addEventListener("click", () => {
    seleccionTrazas.clear();
    guardarSeleccion();
    actualizarMarcasDelCatalogo();
    sincronizarLienzos();
  });
}

// El control que alterna entre la ventana y la sesion completa.
//
// Al pasar a sesion completa se refresca el resumen antes de dibujar: la vista
// tiene que mostrar lo que hay ahora y no lo que habia cuando se abrio la
// pagina. Mientras el modo esta activo, el resumen se refresca solo, porque un
// eje que crece sin traer datos nuevos deja de crecer sin decirlo.
const botonModoEje = document.getElementById("vivo-modo-eje");
let refrescoDelResumen = null;
if (botonModoEje) {
  botonModoEje.addEventListener("click", async () => {
    modoSesionCompleta = !modoSesionCompleta;
    botonModoEje.textContent = modoSesionCompleta
      ? "Ver ultimos 30 s" : "Ver sesion completa";
    if (modoSesionCompleta) {
      await traerResumenDeSesion();
      refrescoDelResumen = window.setInterval(async () => {
        await traerResumenDeSesion();
        dibujarTrazas();
      }, 2000);
    } else if (refrescoDelResumen !== null) {
      window.clearInterval(refrescoDelResumen);
      refrescoDelResumen = null;
    }
    dibujarTrazas();
  });
}

// ---------------------------------------------------------------------------
// Deteccion de flujo detenido
// ---------------------------------------------------------------------------
//
// Sin esto la vista conserva los ultimos valores en pantalla cuando el flujo se
// corta, y quien mira no distingue una sesion en curso de una terminada hace
// media hora. Un tablero que muestra un numero viejo sin decir que es viejo
// afirma algo falso: que eso esta pasando ahora.

// Cuanto puede pasar sin un mensaje antes de considerar detenido el flujo. A
// veinte hercios, tres segundos son sesenta muestras perdidas: ya no es una
// demora, es una interrupcion.
const SILENCIO_PARA_DETENIDO_MS = 3000;
const REVISION_SILENCIO_MS = 1000;

let instanteUltimoMensaje = null;

function revisarSilencio() {
  const aviso = document.getElementById("vivo-silencio");
  if (!aviso) return;
  if (instanteUltimoMensaje === null) return;
  const silencio = performance.now() - instanteUltimoMensaje;
  const detenido = silencio > SILENCIO_PARA_DETENIDO_MS;
  aviso.hidden = !detenido;
  panelVivo.classList.toggle("flujo-detenido", detenido);
  if (detenido) {
    const segundos = Math.round(silencio / 1000);
    const texto =
      segundos < 90
        ? `${segundos} s`
        : `${Math.round(segundos / 60)} min`;
    aviso.textContent =
      `Flujo detenido: no llega telemetria desde hace ${texto}. ` +
      "Los valores en pantalla son los ultimos recibidos, no el estado actual.";
  }
}

setInterval(revisarSilencio, REVISION_SILENCIO_MS);

// ---------------------------------------------------------------------------
// Evidencia de persistencia
// ---------------------------------------------------------------------------
//
// La vista declara que no pasa por la base. Es cierto, y leido solo dice que el
// dato no se guarda. En lugar de aclararlo con una nota, se muestra el estado
// real de la persistencia, que corre en paralelo y no depende de esta vista.

const INTERVALO_PERSISTENCIA_MS = 5000;
let temporizadorPersistencia = null;

async function consultarPersistencia() {
  const destino = document.getElementById("vivo-persistencia");
  if (!destino) return;
  try {
    const respuesta = await fetch(`${API_BASE_URL}/live/persistencia`);
    const estado = await respuesta.json();
    if (!estado.disponible) {
      destino.textContent =
        "sin respuesta de la base (" + (estado.motivo ?? "motivo no declarado") + ")";
      return;
    }
    if (!estado.filas_recientes) {
      destino.textContent = "conectada, sin escrituras recientes";
      return;
    }
    destino.textContent =
      estado.filas_recientes.toLocaleString("es-AR") +
      " filas y " +
      estado.senales_distintas +
      " senales en los ultimos " +
      estado.ventana_s +
      " s de datos";
  } catch (error) {
    destino.textContent = "no se pudo consultar (" + error.message + ")";
  }
}

function ajustarTemporizadorPersistencia(activo) {
  if (activo && temporizadorPersistencia === null) {
    consultarPersistencia();
    temporizadorPersistencia = setInterval(consultarPersistencia, INTERVALO_PERSISTENCIA_MS);
  } else if (!activo && temporizadorPersistencia !== null) {
    clearInterval(temporizadorPersistencia);
    temporizadorPersistencia = null;
  }
}

function declararEstadoEnVivo(estado) {
  document.getElementById("vivo-camino").textContent = estado.camino_vista ?? "—";
  document.getElementById("vivo-camino-base").textContent =
    estado.camino_persistencia ?? "—";
  if (estado.conectado) {
    vivoEstado.hidden = false;
    vivoEstado.textContent =
      "Conectado al flujo. Esperando telemetria: entre a pista para que el juego emita.";
    vivoEstado.classList.remove("aviso-error");
  } else {
    // Se declara el motivo en lugar de mostrar una pantalla vacia: no es lo
    // mismo que no haya datos a que no haya conexion.
    vivoEstado.hidden = false;
    vivoEstado.classList.add("aviso-error");
    vivoEstado.textContent =
      `Sin conexion con el broker (${estado.motivo ?? "motivo no declarado"}). ` +
      "La captura y la persistencia no dependen de este camino: siguen corriendo.";
  }
}

// Pide el catalogo completo antes de que llegue el primer mensaje. Sin esto,
// abrir la pagina fuera de una sesion mostraria un catalogo vacio, que dice algo
// falso: no es que no haya canales, es que en ese instante no llega ninguno.
async function pedirCatalogoDeSenales() {
  try {
    const respuesta = await fetch(`${API_BASE_URL}/live/senales`);
    const cuerpo = await respuesta.json();
    if (!cuerpo.disponible) return;
    for (const senal of cuerpo.senales) {
      if (catalogoSenales.has(senal.signal_name)) continue;
      catalogoSenales.set(senal.signal_name, {
        unidad: senal.unit,
        familia: senal.paquete,
      });
    }
    catalogoDibujado = "";
    graficasVivo.hidden = false;
    dibujarCatalogo();
    sincronizarLienzos();
    // Se dibuja aunque todavia no haya llegado nada. El dibujo estaba atado a la
    // llegada de mensajes, de modo que sin flujo los lienzos quedaban en blanco
    // sin decir por que: no se distinguia "todavia no llega" de "esto esta roto".
    dibujarTrazas();
  } catch (error) {
    // Sin catalogo previo la vista sigue funcionando: se arma con lo que
    // llegue, que es el comportamiento anterior.
  }
}

// ---------------------------------------------------------------------------
// La sesion entera, con el eje que crece
// ---------------------------------------------------------------------------
//
// La ventana de arriba conserva treinta segundos: su eje **se desplaza** y lo
// viejo sale por la izquierda. Con eso una anotacion de hace dos minutos no
// tiene donde dibujarse, y por eso las anotaciones vivian en una lista aparte.
//
// Este modo dibuja **toda la sesion desde su inicio**, con un intervalo por
// segundo. El servidor conserva el minimo y el maximo de cada intervalo en lugar
// de una muestra representativa, de modo que un pico de frenada ---que dura
// menos que el intervalo--- no desaparece al reducir.
//
// Las dos vistas conviven y no se reemplazan: una da el detalle de lo que esta
// pasando y la otra el recorrido completo.


// Con que color se dibuja cada nivel de anotacion sobre las trazas.
//
// Un incidente ya ocurrio y un aviso todavia se puede evitar: son dos cosas
// distintas y el grafico las distingue, igual que la lista.
const COLOR_MARCA_ANOTACION = {
  incidente: "#f87171",
  aviso: "#f59e0b",
};

async function traerResumenDeSesion() {
  try {
    const respuesta = await fetch(`${API_BASE_URL}/live/resumen`);
    const cuerpo = await respuesta.json();
    intervaloResumen = cuerpo.intervalo_s ?? 1;
    origenDeLaSesion = cuerpo.origen_s ?? null;
    resumenPorVehiculo.clear();
    for (const [vehiculo, senales] of Object.entries(cuerpo.vehiculos ?? {})) {
      registrarConductor(vehiculo);
      const porSenal = new Map();
      for (const [senal, intervalos] of Object.entries(senales ?? {})) {
        if (Array.isArray(intervalos) && intervalos.length) {
          porSenal.set(senal, intervalos);
        }
      }
      resumenPorVehiculo.set(vehiculo, porSenal);
    }
  } catch (error) {
    // Sin resumen, la vista de ventana sigue sirviendo igual.
  }
}

// Cuanto duro la sesion, en segundos, segun el resumen mas largo.
//
// Se toma el maximo entre vehiculos y senales para que **los dos conductores
// compartan el mismo eje**: si cada uno se escalara a su propia duracion, dos
// trazas del mismo instante quedarian en abscisas distintas y la comparacion
// diria cualquier cosa.
function duracionDeLaSesion() {
  let fin = 0;
  for (const porSenal of resumenPorVehiculo.values()) {
    for (const intervalos of porSenal.values()) {
      const ultimo = intervalos[intervalos.length - 1];
      if (ultimo && ultimo[0] > fin) fin = ultimo[0];
    }
  }
  return fin;
}

// Trae lo que ya paso antes de que se abriera la vista.
//
// Sin esto la traza empezaba en el instante de conectarse: abrir la pagina a
// mitad de una vuelta mostraba los lienzos vacios, como si antes no hubiera
// ocurrido nada. La vista arrancaba cuando miraba el observador y no cuando
// empezo el vehiculo.
async function sembrarHistoria() {
  try {
    const respuesta = await fetch(`${API_BASE_URL}/live/historia`);
    const cuerpo = await respuesta.json();
    for (const [vehiculo, datos] of Object.entries(cuerpo.vehiculos ?? {})) {
      registrarConductor(vehiculo);
      const series = new Map();
      const marcas = new Map();
      for (const [senal, valores] of Object.entries(datos.series ?? {})) {
        const limpia = valores
          .map((v) => (typeof v === "boolean" ? Number(v) : v))
          .filter((v) => typeof v === "number" && Number.isFinite(v));
        if (limpia.length) {
          series.set(senal, limpia.slice(-MUESTRAS_POR_TRAZA));
          // El catalogo se arma con lo que efectivamente llega, de modo que
          // sembrarlo aca evita que la vista arranque sin nada que elegir.
          historiaPorSenal.set(senal, limpia.slice(-MUESTRAS_POR_TRAZA));
        }
      }
      for (const [senal, t] of Object.entries(datos.tiempos ?? {})) {
        const limpia = t.map(instanteDe).filter((x) => x !== null);
        if (limpia.length) marcas.set(senal, limpia.slice(-MUESTRAS_POR_TRAZA));
      }
      historiaPorVehiculo.set(vehiculo, series);
      tiemposPorVehiculo.set(vehiculo, marcas);
      if (Array.isArray(datos.distancia) && datos.distancia.length) {
        distanciaPorVehiculo.set(vehiculo, datos.distancia.slice(-MUESTRAS_POR_TRAZA));
      }
    }
    dibujarSelectorDeConductor();
    dibujarTrazas();
  } catch (error) {
    // Sin historia la vista sigue sirviendo: dibuja desde ahora.
  }
}

// ---------------------------------------------------------------------------
// Anotaciones en tiempo real
// ---------------------------------------------------------------------------
//
// No repiten lo que las trazas ya muestran. Una traza en movimiento obliga a
// reconocer el suceso mientras pasa y a recordarlo despues; la anotacion lo
// declara con su vuelta, su lugar y el fundamento de su umbral, de modo que en
// el informe pueda **citarse** en lugar de recordarse.

function registrarAnotacion(anotacion) {
  const clave = anotacion.id !== undefined
    ? `${anotacion.vehiculo ?? ""}#i${anotacion.id}`
    // Los avisos no llevan identidad porque no se corrigen despues: se emiten
    // una sola vez, cuando la condicion aparece.
    : `a${(proximaAnotacionSuelta -= 1)}`;
  anotacionesPorId.set(clave, anotacion);
  dibujarAnotaciones();
}

// Donde paso, dicho de la forma mas util que el dato permita.
//
// "curva 7" se entiende sin saber nada del circuito; "metro 2.105" obliga a
// saber donde queda el metro 2.105. Cuando el sistema todavia no aprendio el
// trazado cae al metro, que es menos util y sigue siendo cierto.
function textoDeUbicacion(anotacion) {
  const partes = [];
  if (anotacion.vuelta !== undefined) partes.push(`vuelta ${anotacion.vuelta}`);
  if (anotacion.lugar) {
    partes.push(anotacion.lugar);
  } else if (anotacion.distancia_m !== undefined) {
    partes.push(`metro ${Math.round(anotacion.distancia_m).toLocaleString("es-AR")}`);
  }
  return partes.join(", ");
}

function dibujarAnotaciones() {
  if (!listaAnotaciones) return;

  // Con un conductor elegido, la lista muestra solo lo suyo: mezclarlas obliga
  // a leer el nombre en cada linea para saber a quien le paso.
  const visibles = vehiculosADibujar();
  const entradas = [...anotacionesPorId.entries()].filter(
    ([, a]) => !a.vehiculo || conductores.size < 2 || visibles.includes(a.vehiculo));

  panelAnotaciones.hidden = entradas.length === 0;
  if (!entradas.length) return;

  // Lo mas reciente arriba: en vivo, lo que acaba de pasar es lo que se mira.
  entradas.sort((a, b) => (b[1].reloj_s ?? 0) - (a[1].reloj_s ?? 0));

  const incidentes = entradas.filter(([, a]) => a.nivel === "incidente").length;
  const avisos = entradas.length - incidentes;
  conteoAnotaciones.textContent =
    `${incidentes} ${incidentes === 1 ? "incidente" : "incidentes"}`
    + (avisos ? ` y ${avisos} ${avisos === 1 ? "aviso" : "avisos"}` : "");

  listaAnotaciones.replaceChildren(...entradas.map(([clave, a]) => {
    const item = document.createElement("li");
    item.className = `anotacion anotacion-${a.nivel}`;
    // Un incidente todavia abierto se marca: su duracion es la medida hasta
    // ahora y va a crecer, y presentarla como definitiva seria afirmar de mas.
    if (a.cerrada === false) item.classList.add("anotacion-abierta");
    item.dataset.clave = clave;

    // Tocar una anotacion la senala sobre las trazas; tocarla otra vez la
    // suelta. Es la operacion que relaciona las dos mitades de la vista, y por
    // eso el elemento se comporta como un control y no como texto.
    item.tabIndex = 0;
    item.setAttribute("role", "button");
    const alternar = () => {
      anotacionSenalada = anotacionSenalada === a.reloj_s ? null : a.reloj_s;
      dibujarAnotaciones();
      dibujarTrazas();
    };
    item.addEventListener("click", alternar);
    item.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); alternar(); }
    });
    if (anotacionSenalada === a.reloj_s) item.classList.add("anotacion-senalada");

    const titulo = document.createElement("strong");
    titulo.textContent = a.titulo;
    // Comparando dos conductores hace falta saber a quien le paso cada cosa.
    if (a.vehiculo && conductores.size > 1 && compararConductores) {
      const quien = document.createElement("span");
      quien.className = "anotacion-conductor";
      quien.textContent = conductores.get(a.vehiculo)?.nombre ?? "";
      quien.style.color = conductores.get(a.vehiculo)?.color ?? "inherit";
      titulo.prepend(quien);
    }
    const ubicacion = textoDeUbicacion(a);
    if (ubicacion) {
      const donde = document.createElement("span");
      donde.className = "anotacion-donde";
      donde.textContent = ubicacion;
      titulo.append(donde);
    }

    const detalle = document.createElement("p");
    detalle.className = "anotacion-detalle";
    detalle.textContent = a.detalle;

    item.append(titulo, detalle);

    // Que venia pasando antes. Es lo que separa "algo ocurrio" de "esto ocurrio
    // y se sospecha por que". Se escribe como sospecha y no como causa: lo que
    // el dato permite afirmar es que dos cosas pasaron en ese orden, y que una
    // haya producido la otra es una lectura.
    if (a.sospecha) {
      const sospecha = document.createElement("p");
      sospecha.className = "anotacion-sospecha";
      const encabezado = document.createElement("strong");
      encabezado.textContent = `Se sospecha que ${a.sospecha}. `;
      sospecha.append(encabezado,
                      document.createTextNode(a.sospecha_evidencia ?? ""));
      item.append(sospecha);
    }

    if (a.fundamento) {
      const pie = document.createElement("p");
      pie.className = "anotacion-fundamento";
      // Si la ubicacion es una curva, se declara de cuantas vueltas salio esa
      // numeracion. Sin eso, "curva 7" se lee como una cita del trazado
      // oficial, y no lo es: es lo que el dato de esta sesion declaro.
      pie.textContent = a.curvas_derivadas_de
        ? `${a.fundamento} · curvas derivadas de ${a.curvas_derivadas_de} `
          + `${a.curvas_derivadas_de === 1 ? "vuelta" : "vueltas"} de referencia`
        : a.fundamento;
      item.append(pie);
    }
    return item;
  }));
}

// Trae lo ya anotado, por conductor, y declara que reglas quedaron ciegas.
async function sembrarAnotaciones() {
  try {
    const respuesta = await fetch(`${API_BASE_URL}/live/anotaciones`);
    const cuerpo = await respuesta.json();
    const ciegas = new Set();
    for (const [vehiculo, datos] of Object.entries(cuerpo.vehiculos ?? {})) {
      registrarConductor(vehiculo);
      for (const anotacion of datos.anotaciones ?? []) {
        registrarAnotacion({ ...anotacion, vehiculo });
      }
      for (const [regla, puede] of Object.entries(datos.reglas_evaluables ?? {})) {
        if (!puede) ciegas.add(regla);
      }
    }
    // Una regla cuyo canal no llega **no dice que no paso nada**: dice que no
    // pudo mirarse. Sin declararlo, una lista vacia se lee como si no hubiera
    // ocurrido nada.
    if (avisoReglasCiegas) {
      avisoReglasCiegas.hidden = ciegas.size === 0;
      avisoReglasCiegas.textContent = ciegas.size
        ? `Sin canal para evaluar: ${[...ciegas].join(", ")}. `
          + "Que no se anote no significa que no haya ocurrido."
        : "";
    }
  } catch (error) {
    // Sin anotaciones previas la vista sigue sirviendo: recibe las que vengan.
  }
}

const botonLimpiarAnotaciones = document.getElementById("vivo-limpiar-anotaciones");
if (botonLimpiarAnotaciones) {
  botonLimpiarAnotaciones.addEventListener("click", () => {
    anotacionesPorId.clear();
    anotacionSenalada = null;
    dibujarAnotaciones();
    dibujarTrazas();
  });
}

function conectarFlujoEnVivo() {
  if (fuenteEnVivo) {
    return;
  }
  pedirCatalogoDeSenales().then(sembrarHistoria);
  sembrarAnotaciones();
  fuenteEnVivo = new EventSource(`${API_BASE_URL}/live/stream`);

  fuenteEnVivo.addEventListener("estado", (evento) => {
    declararEstadoEnVivo(JSON.parse(evento.data));
  });
  fuenteEnVivo.addEventListener("telemetria", (evento) => {
    registrarMensajeEnVivo(JSON.parse(evento.data));
  });
  fuenteEnVivo.addEventListener("anotacion", (evento) => {
    registrarAnotacion(JSON.parse(evento.data));
  });
  fuenteEnVivo.addEventListener("latido", () => {
    // Distingue "sin datos" de "conexion cortada": sin el latido, un
    // intermediario podria cerrar la conexion inactiva sin que se note.
    if (!ultimoPorSenal.size) {
      vivoEstado.textContent =
        "Conectado al flujo. Todavia no llego telemetria: entre a pista.";
    }
  });
  fuenteEnVivo.onerror = () => {
    vivoEstado.hidden = false;
    vivoEstado.classList.add("aviso-error");
    vivoEstado.textContent =
      "Se corto el flujo en vivo. El navegador reintenta la conexion solo.";
  };
}

function desconectarFlujoEnVivo() {
  if (fuenteEnVivo) {
    fuenteEnVivo.close();
    fuenteEnVivo = null;
  }
}

// ---------------------------------------------------------------------------
// Matriz de capacidades y ausencias
// ---------------------------------------------------------------------------
//
// No lista senales: contrasta **que puede medirse en cada fuente y con que
// resolucion**, organizado por magnitud fisica. Cada fuente nombra lo suyo a su
// manera —la deportiva llama `brake_applied` a lo que el bus llama
// `brake_pressed`— de modo que comparar nombres no compararia nada.
//
// Las ausencias se muestran con su motivo, y no son equivalentes: que un
// vehiculo de calle no tenga aleron movil es un limite del objeto; que la fuente
// deportiva no exponga la aceleracion es un limite del acceso.

const panelMatriz = document.getElementById("panel-matriz");
let matrizCargada = false;

const ORDEN_FUENTES = [
  "can_real_replay",
  "openf1_historical_replay",
  "f1_25_udp_simulation",
];

function celdaDeFuente(dato) {
  const celda = document.createElement("td");
  if (!dato || !dato.disponible) {
    celda.className = "ausente";
    celda.append(document.createTextNode("no disponible"));
    const motivo = dato && dato.motivo;
    if (motivo) {
      const span = document.createElement("span");
      span.className = "motivo";
      span.textContent = motivo;
      celda.append(span);
    }
    return celda;
  }
  celda.className = "presente";
  celda.append(document.createTextNode(dato.senal));
  const detalle = document.createElement("span");
  detalle.className = "unidad-hz";
  // La frecuencia se muestra medida, no declarada. Cuando no se pudo medir se
  // dice, en lugar de mostrar un hueco que se lee como cero.
  detalle.textContent = dato.hz === null || dato.hz === undefined
    ? `${dato.unidad ?? ""} · frecuencia no medible`
    : `${dato.unidad ?? ""} · ${dato.hz} Hz`;
  celda.append(detalle);
  return celda;
}

function dibujarMatriz(datos) {
  const estado = document.getElementById("matriz-estado");
  const contenedorFuentes = document.getElementById("matriz-fuentes");
  const contenedorTabla = document.getElementById("matriz-tabla");
  const pie = document.getElementById("matriz-pie");

  contenedorFuentes.replaceChildren();
  const porClave = new Map(datos.fuentes.map((f) => [f.clave, f]));
  for (const clave of ORDEN_FUENTES) {
    const fuente = porClave.get(clave);
    if (!fuente) continue;
    const tarjeta = document.createElement("article");
    tarjeta.className = "tarjeta-fuente";
    tarjeta.dataset.nivel = fuente.nivel;
    tarjeta.innerHTML = `
      <span class="nivel">Nivel ${fuente.nivel}</span>
      <h3></h3>
      <p class="detalle"></p>
      <div class="cifras-fuente">
        <span><b>${fuente.filas.toLocaleString("es-AR")}</b>filas</span>
        <span><b>${fuente.senales}</b>senales</span>
        <span><b>${fuente.vehiculos}</b>vehiculos</span>
      </div>`;
    // El nombre y el detalle se escriben como texto y no como marcado, para que
    // un valor con caracteres especiales no se interprete.
    tarjeta.querySelector("h3").textContent = fuente.nombre;
    tarjeta.querySelector(".detalle").textContent = fuente.medicion;
    contenedorFuentes.append(tarjeta);
  }
  contenedorFuentes.hidden = false;

  const tabla = document.createElement("table");
  tabla.className = "matriz";
  const cabecera = document.createElement("tr");
  for (const titulo of ["Magnitud", "Bus de vehiculo real", "Fuente deportiva",
                        "Simulador"]) {
    const th = document.createElement("th");
    th.textContent = titulo;
    cabecera.append(th);
  }
  const thead = document.createElement("thead");
  thead.append(cabecera);
  tabla.append(thead);

  const cuerpo = document.createElement("tbody");
  let familiaAnterior = null;
  for (const fila of datos.magnitudes) {
    const tr = document.createElement("tr");
    // La linea mas gruesa separa familias: agrupa lo que se lee junto.
    if (fila.familia !== familiaAnterior) {
      tr.className = "familia-nueva";
      familiaAnterior = fila.familia;
    }
    const magnitud = document.createElement("td");
    magnitud.className = "celda-magnitud";
    magnitud.append(document.createTextNode(fila.magnitud));
    const familia = document.createElement("span");
    familia.className = "familia";
    familia.textContent = fila.familia;
    magnitud.append(familia);
    tr.append(magnitud);

    for (const clave of ORDEN_FUENTES) {
      tr.append(celdaDeFuente(fila.fuentes[clave]));
    }
    cuerpo.append(tr);

    if (fila.nota) {
      const notaFila = document.createElement("tr");
      const celda = document.createElement("td");
      celda.colSpan = 4;
      celda.className = "nota-magnitud";
      celda.textContent = fila.nota;
      notaFila.append(celda);
      cuerpo.append(notaFila);
    }
  }
  tabla.append(cuerpo);
  contenedorTabla.replaceChildren(tabla);
  contenedorTabla.hidden = false;

  pie.textContent =
    `Frecuencias medidas sobre ${datos.medido_sobre}. ` +
    "Ninguna cifra se declara sin haberla medido.";
  pie.hidden = false;
  estado.hidden = true;
}

async function cargarMatriz() {
  if (matrizCargada) return;
  const estado = document.getElementById("matriz-estado");
  try {
    const respuesta = await fetch(`${API_BASE_URL}/fuentes/matriz`);
    const datos = await respuesta.json();
    dibujarMatriz(datos);
    matrizCargada = true;
  } catch (error) {
    estado.hidden = false;
    estado.classList.add("aviso-error");
    // Se declara el motivo en lugar de dejar la pantalla a medias.
    estado.textContent = `No se pudo construir la matriz (${error.message}).`;
  }
}

async function cambiarModo() {
  const modo = selectorModo.value;
  const openF1Activo = modo === "openf1";
  const vivoActivo = modo === "vivo";
  const matrizActiva = modo === "matriz";
  document.body.classList.toggle("modo-openf1-activo", openF1Activo);
  document.body.classList.toggle("modo-vivo-activo", vivoActivo);
  document.querySelectorAll(".modo-simulacion").forEach((elemento) => {
    elemento.hidden = modo !== "simulation";
  });
  panelOpenF1.hidden = !openF1Activo;
  panelVivo.hidden = !vivoActivo;
  panelMatriz.hidden = !matrizActiva;
  if (matrizActiva) cargarMatriz();
  // La cabecera describe la sesion demostrativa: en los otros espacios de
  // trabajo anunciaba una sesion que la pantalla no esta mostrando.
  const cabecera = document.querySelector(".cabecera-sesion");
  if (cabecera) cabecera.hidden = modo !== "simulation";

  // La conexion en vivo se abre solo al entrar al espacio de trabajo y se cierra
  // al salir: mantenerla abierta en segundo plano consumiria un suscriptor y
  // ancho de banda sin que nadie mire la pantalla.
  ajustarTemporizadorSimulacion(modo === "simulation");
  // La consulta de persistencia sigue la misma regla: solo corre en el espacio
  // de trabajo que la muestra.
  ajustarTemporizadorPersistencia(vivoActivo);

  if (vivoActivo) {
    conectarFlujoEnVivo();
  } else {
    desconectarFlujoEnVivo();
  }
  if (openF1Activo) {
    // El catalogo de sesiones se pide una sola vez: no cambia mientras la
    // aplicacion esta abierta, y la eleccion del usuario debe sobrevivir a ir y
    // volver del espacio de trabajo de simulacion.
    if (!sesionesOpenF1.length) {
      await cargarSesionesDisponibles();
    }
    cargarReplayOpenF1();
    cargarProcesamientoSesiones();
  } else {
    etiquetaCabecera.textContent = "Telemetria de conduccion";
    tituloCabecera.textContent = "Sesion demostrativa";
    cargarSesion();
  }
}

botonRecargar.addEventListener("click", cargarSesion);
selectorModo.addEventListener("change", cambiarModo);
selectorSesionOpenF1.addEventListener("change", async () => {
  sesionOpenF1Seleccionada = Number(selectorSesionOpenF1.value);
  // Las corridas pertenecen a la sesion, de modo que cambiar de sesion obliga a
  // rehacer el listado antes de pedir cualquier dato.
  await cargarCorridasReplay();
  cargarReplayOpenF1();
});
selectorCorridaReplay.addEventListener("change", () => {
  corridaReplaySeleccionada = selectorCorridaReplay.value || null;
  cacheAnalisis.clear();
  cargarReplayOpenF1();
});
casillasPilotosComparacion.addEventListener("change", () => {
  pilotosSeleccionadosEstado = [...casillasPilotosComparacion.querySelectorAll("input:checked")].map((input) => Number(input.value));
  cargarReplayOpenF1();
});
busquedaPilotosComparacion.addEventListener("input", renderizarCasillasPilotos);
seleccionadosPilotosComparacion.addEventListener("click", (event) => {
  const boton = event.target.closest("[data-quitar-piloto]");
  if (!boton) {
    return;
  }
  pilotosSeleccionadosEstado = pilotosSeleccionadosEstado.filter((numero) => numero !== Number(boton.dataset.quitarPiloto));
  cargarReplayOpenF1();
});
botonLimpiarPilotos.addEventListener("click", () => {
  pilotosSeleccionadosEstado = [];
  cargarReplayOpenF1();
});
botonTodosPilotos.addEventListener("click", () => {
  pilotosSeleccionadosEstado = pilotosOpenF1.map((piloto) => piloto.driver_number);
  cargarReplayOpenF1();
});
Object.values(GRAFICOS_CARRERA).forEach((graficoAnalisisCarrera) => graficoAnalisisCarrera.addEventListener("click", (event) => {
  if (!ultimaSerieCarrera) {
    return;
  }
  const rect = graficoAnalisisCarrera.getBoundingClientRect();
  const xCanvas = ((event.clientX - rect.left) / rect.width) * graficoAnalisisCarrera.width;
  const relativeX = Math.min(Math.max(xCanvas, ultimaSerieCarrera.margen.izquierdo), ultimaSerieCarrera.margen.izquierdo + ultimaSerieCarrera.areaAncho);
  const targetTime = ultimaSerieCarrera.inicio + ((relativeX - ultimaSerieCarrera.margen.izquierdo) / ultimaSerieCarrera.areaAncho) * (ultimaSerieCarrera.fin - ultimaSerieCarrera.inicio);
  const timestamp = ultimaSerieCarrera.puntos.reduce((nearest, point) => (
    Math.abs(point.tiempo - targetTime) < Math.abs(nearest.tiempo - targetTime) ? point : nearest
  )).tiempo;
  seleccionarInstanteCarrera(timestamp);
}));
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


// --- Recorrido reconstruido del vehiculo de calle ------------------------- //
//
// El registro no trae coordenadas: la forma sale de integrar velocidad y
// velocidad de guinada. Se dibuja con **la misma escala en los dos ejes**
// porque estirar el dibujo para que llene el lienzo haria parecer sinuoso un
// tramo recto, que es justamente lo contrario de lo que el dato dice.
const CANVAS_RECORRIDO = document.getElementById("grafico-recorrido");
const DETALLE_RECORRIDO = document.getElementById("detalle-recorrido");

function dibujarRecorrido(datos) {
  if (!CANVAS_RECORRIDO) return;
  const ctx = CANVAS_RECORRIDO.getContext("2d");
  const { width: ancho, height: alto } = CANVAS_RECORRIDO;
  ctx.clearRect(0, 0, ancho, alto);
  ctx.fillStyle = "#0b1220";
  ctx.fillRect(0, 0, ancho, alto);

  const puntos = datos?.puntos ?? [];
  if (puntos.length < 2) {
    ctx.fillStyle = "#94a3b8";
    ctx.font = "13px system-ui, sans-serif";
    ctx.fillText("Sin recorrido para este segmento.", 16, 26);
    return;
  }

  const xs = puntos.map((p) => p.x);
  const ys = puntos.map((p) => p.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const margen = 28;
  // Una sola escala para los dos ejes: la proporcion real es parte del dato.
  const escala = Math.min(
    (ancho - margen * 2) / Math.max(maxX - minX, 1),
    (alto - margen * 2) / Math.max(maxY - minY, 1)
  );
  const centroX = (minX + maxX) / 2;
  const centroY = (minY + maxY) / 2;
  const aPantalla = (p) => [
    ancho / 2 + (p.x - centroX) * escala,
    // El eje vertical del lienzo crece hacia abajo y el del recorrido hacia
    // arriba: sin invertirlo, el dibujo sale espejado.
    alto / 2 - (p.y - centroY) * escala,
  ];

  // Barra de escala: sin ella, un recorrido de cien metros y uno de dos mil se
  // ven iguales, porque el dibujo se ajusta al lienzo en los dos casos.
  const metrosBarra = escalaLegible(Math.max(maxX - minX, maxY - minY) / 4);
  ctx.strokeStyle = "rgba(148, 163, 184, 0.5)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(margen, alto - 18);
  ctx.lineTo(margen + metrosBarra * escala, alto - 18);
  ctx.stroke();
  ctx.fillStyle = "#94a3b8";
  ctx.font = "11px system-ui, sans-serif";
  ctx.fillText(`${metrosBarra} m`, margen, alto - 24);

  ctx.strokeStyle = "#38bdf8";
  ctx.lineWidth = 2;
  ctx.lineJoin = "round";
  ctx.beginPath();
  puntos.forEach((p, i) => {
    const [px, py] = aPantalla(p);
    if (i === 0) ctx.moveTo(px, py);
    else ctx.lineTo(px, py);
  });
  ctx.stroke();

  const [ix, iy] = aPantalla(puntos[0]);
  ctx.fillStyle = "#f8fafc";
  ctx.beginPath();
  ctx.arc(ix, iy, 4, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillText("inicio", ix + 8, iy + 4);
}

function escalaLegible(metros) {
  const candidatos = [10, 25, 50, 100, 250, 500, 1000];
  return candidatos.find((c) => c >= metros) ?? 1000;
}

function describirRecorrido(datos) {
  if (!DETALLE_RECORRIDO) return;
  const v = datos?.validacion_guinada;
  // La comprobacion se muestra siempre, tambien cuando no se pudo hacer: que un
  // tramo recto no permita deducir el ancho de via **es informacion**, y
  // ocultarla dejaria creer que la validacion siempre corrio.
  const comprobacion = v?.ancho_de_via_m
    ? `Comprobado contra las cuatro ruedas: el ancho de via que se deduce es de ${v.ancho_de_via_m} m, con correlacion ${v.correlacion} sobre ${v.muestras.toLocaleString("es-AR")} muestras. Ese valor no viaja en el bus: surge de dos senales decodificadas por separado.`
    : "Sin giro suficiente para deducir el ancho de via: en un tramo recto la diferencia entre ruedas es ruido y la comprobacion no aplica.";
  DETALLE_RECORRIDO.textContent =
    `${datos.recorrido_m.toLocaleString("es-AR")} m recorridos, en ${Math.round(datos.extension_x_m)} por ${Math.round(datos.extension_y_m)} m. ${comprobacion}`;
}

async function traerRecorrido(sessionId) {
  if (!CANVAS_RECORRIDO) return;
  try {
    const respuesta = await fetch(`${API_BASE_URL}/can/recorrido/${encodeURIComponent(sessionId)}`);
    if (!respuesta.ok) {
      dibujarRecorrido(null);
      if (DETALLE_RECORRIDO) {
        DETALLE_RECORRIDO.textContent =
          respuesta.status === 404
            ? "Este segmento no tiene velocidad y guinada juntas, que son las dos senales que la reconstruccion necesita."
            : `No se pudo obtener el recorrido (${respuesta.status}).`;
      }
      return;
    }
    const datos = await respuesta.json();
    dibujarRecorrido(datos);
    describirRecorrido(datos);
  } catch (error) {
    dibujarRecorrido(null);
    if (DETALLE_RECORRIDO) {
      DETALLE_RECORRIDO.textContent = `No se pudo obtener el recorrido: ${error.message}`;
    }
  }
}

// El segmento de bus que se dibuja. Es una constante y no una eleccion porque
// el tablero muestra un segmento de referencia; que sea urbano y no de
// autopista es deliberado: en autopista el vehiculo va derecho y el recorrido
// es una recta, que es cierto pero no muestra nada.
const SEGMENTO_RECORRIDO = "can:segmento:sample_10";

cargarSesion();
traerRecorrido(SEGMENTO_RECORRIDO);
// La recarga conserva soporte para una vista actualizable, aunque la demo actual
// usa una sesion historica y finita.
// El temporizador solo corre en el espacio de trabajo que lo necesita. Antes
// consultaba en los tres modos: en vivo generaba una consulta por segundo a una
// sesion que la pantalla no mostraba, y en modo historico lo mismo.
let temporizadorSimulacion = null;

function ajustarTemporizadorSimulacion(activo) {
  if (activo && temporizadorSimulacion === null) {
    temporizadorSimulacion = setInterval(cargarSesion, INTERVALO_RECARGA_MS);
  } else if (!activo && temporizadorSimulacion !== null) {
    clearInterval(temporizadorSimulacion);
    temporizadorSimulacion = null;
  }
}

ajustarTemporizadorSimulacion(selectorModo.value === "simulation");


// ---------------------------------------------------------------------------
// Analisis automatico por vuelta y por stint
//
// Consume `/racing/sessions/{key}/analysis/{run}/laps` y `/stints`, generados por
// `scripts/generate_session_analysis.py`.
//
// La interfaz conserva la separacion en tres bloques con la que el analisis fue
// calculado y guardado. Aplanar las metricas en una sola tabla borraria la
// distincion entre dato observado y dato derivado, que es justamente el aporte
// metodologico del analisis y el motivo por el que la tabla las separa.
// ---------------------------------------------------------------------------

const selectorPilotoAnalisis = document.getElementById("selector-piloto-analisis");
const selectorAlcanceAnalisis = document.getElementById("selector-alcance-analisis");
const selectorVueltaAnalisis = document.getElementById("selector-vuelta-analisis");
const etiquetaSelectorVuelta = document.getElementById("etiqueta-selector-vuelta");
const detalleAnalisisVuelta = document.getElementById("detalle-analisis-vuelta");
const resumenAnalisisVuelta = document.getElementById("resumen-analisis-vuelta");
const estadoAnalisisVuelta = document.getElementById("estado-analisis-vuelta");

// Cache por piloto y alcance: el analisis de una corrida ya generada no cambia,
// de modo que volver a pedirlo al cambiar de vuelta seria trafico inutil.
const cacheAnalisis = new Map();

// Etiquetas legibles de las metricas. Las claves no listadas se muestran con su
// nombre crudo en vez de ocultarse: preferimos un nombre feo a una metrica que
// desaparece de la vista sin que nadie lo note.
const ETIQUETAS_ANALISIS = {
  lap_duration_seconds: "Duracion de vuelta (s)",
  duration_sector_1_seconds: "Sector 1 (s)",
  duration_sector_2_seconds: "Sector 2 (s)",
  duration_sector_3_seconds: "Sector 3 (s)",
  i1_speed_kph: "Velocidad intermedio 1 (km/h)",
  i2_speed_kph: "Velocidad intermedio 2 (km/h)",
  speed_trap_kph: "Trampa de velocidad (km/h)",
  is_pit_out_lap: "Vuelta de salida de boxes",
  minisectores_total: "Minisectores",
  minisectores_con_dato: "Minisectores con dato",
  minisectores_sin_dato: "Minisectores sin dato",
  minisectores_purpura: "Minisectores en purpura",
  minisectores_verde: "Minisectores en verde",
  minisectores_amarillo: "Minisectores en amarillo",
  vueltas: "Vueltas del stint",
  tyre_age_at_start: "Edad del neumatico al inicio",
  velocidad_min_kph: "Velocidad minima (km/h)",
  velocidad_max_kph: "Velocidad maxima (km/h)",
  velocidad_media_kph: "Velocidad media (km/h)",
  acelerador_medio_pct: "Acelerador medio (%)",
  acelerador_a_fondo_pct: "Acelerador a fondo (%)",
  freno_aplicado_pct: "Freno aplicado (%)",
  marcha_maxima: "Marcha maxima",
  marcha_media: "Marcha media",
  rpm_max: "RPM maximo",
  rpm_medio: "RPM medio",
  drs_abierto_pct: "DRS abierto (%)",
  distancia_m: "Distancia recorrida (m)",
  distancia_desvio_pct: "Desvio contra longitud oficial (%)",
  muestras_velocidad: "Muestras de velocidad",
  hueco_maximo_segundos: "Hueco temporal maximo (s)",
  ventana_fin_estimado: "Fin de ventana estimado",
  ventana_completa: "Ventana completa",
};

// Claves que describen el metodo o su validacion en vez de aportar un valor
// medido. Se omiten de la grilla y se resumen aparte, para que no compitan
// visualmente con las metricas.
const CLAVES_METODOLOGICAS = new Set([
  "acelerador_umbral_a_fondo",
  "distancia_metodo",
  "distancia_referencia_m",
  "distancia_validada",
  "drs_codigos",
  "drs_interpretacion_validada",
  "longitud_referencia_m",
  "muestras_por_senal",
]);

function formatearValorAnalisis(valor) {
  if (valor === null || valor === undefined) return "sin dato";
  if (typeof valor === "boolean") return valor ? "si" : "no";
  if (typeof valor === "number") return Number.isInteger(valor) ? String(valor) : valor.toFixed(2);
  return String(valor);
}

function renderizarBloqueMetricas(titulo, nota, metricas) {
  const filas = Object.entries(metricas ?? {})
    .filter(([clave]) => !CLAVES_METODOLOGICAS.has(clave))
    .map(([clave, valor]) => `<div><dt>${escaparHtml(ETIQUETAS_ANALISIS[clave] ?? clave)}</dt><dd>${escaparHtml(formatearValorAnalisis(valor))}</dd></div>`);
  if (!filas.length) return "";
  return `<article class="bloque-analisis">
    <h4>${escaparHtml(titulo)}</h4>
    <p class="nota-analisis">${escaparHtml(nota)}</p>
    <dl class="grilla-analisis">${filas.join("")}</dl>
  </article>`;
}

function renderizarDetalleAnalisis(fila) {
  if (!fila) {
    detalleAnalisisVuelta.innerHTML = "";
    return;
  }
  const derivadas = fila.metricas_derivadas ?? {};
  const calidad = fila.calidad ?? {};

  // Advertencias propias de ESTA vuelta o stint.
  //
  // Solo entran aqui las condiciones que varian entre una seleccion y otra. Una
  // salvedad del metodo, que vale para todas las vueltas por igual, no puede ir en
  // esta banda: apareceria siempre, dejaria de leerse como advertencia y se
  // volveria ruido permanente. Esas salvedades se resumen en la nota del bloque.
  const advertencias = [];
  if (calidad.ventana_completa === false) {
    advertencias.push("La ventana temporal no pudo determinarse por completo: no hay metricas derivadas para este tramo.");
  } else if (calidad.ventana_fin_estimado) {
    advertencias.push("El fin de la ventana es estimado a partir de la duracion declarada, porque no existe una vuelta siguiente contigua.");
  }

  const bloques = [
    renderizarBloqueMetricas(
      "Medicion oficial",
      `Proviene de OpenF1 sin transformar. ${textoResolucionMinisector()}`,
      fila.metricas_oficiales,
    ),
    renderizarBloqueMetricas(
      "Derivado de la telemetria",
      [
        "Calculado por el proyecto a partir de la telemetria replicada.",
        derivadas.distancia_metodo
          ? `Distancia por ${derivadas.distancia_metodo}, validada contra ${formatearValorAnalisis(derivadas.distancia_referencia_m)} m oficiales.`
          : "",
        derivadas.drs_interpretacion_validada === false
          ? "El porcentaje de DRS usa una interpretacion de codigos aun no validada."
          : "",
      ].filter(Boolean).join(" "),
      derivadas,
    ),
    renderizarBloqueMetricas(
      "Calidad del resultado",
      "Cobertura de la muestra sobre la que se apoyan las metricas derivadas.",
      calidad,
    ),
  ].filter(Boolean);

  const avisos = advertencias.length
    ? `<p class="aviso-analisis">${advertencias.map(escaparHtml).join(" ")}</p>`
    : "";
  detalleAnalisisVuelta.innerHTML = avisos + `<div class="bloques-analisis">${bloques.join("")}</div>`;
}

async function obtenerAnalisis(driverNumber, alcance) {
  const clave = `${alcance}:${driverNumber}`;
  if (cacheAnalisis.has(clave)) return cacheAnalisis.get(clave);
  const ruta = alcance === "stint" ? "stints" : "laps";
  const parametros = new URLSearchParams({ driver_number: String(driverNumber) });
  const respuesta = await fetch(
    `${API_BASE_URL}/racing/sessions/${sesionOpenF1Seleccionada}/analysis/${corridaReplaySeleccionada}/${ruta}?${parametros}`,
  );
  if (respuesta.status === 404) {
    cacheAnalisis.set(clave, []);
    return [];
  }
  if (!respuesta.ok) throw new Error("No se pudo recuperar el analisis.");
  const filas = await respuesta.json();
  cacheAnalisis.set(clave, filas);
  return filas;
}

function poblarSelectorPilotosAnalisis() {
  selectorPilotoAnalisis.innerHTML = pilotosOpenF1
    .map((piloto) => `<option value="${piloto.driver_number}">${escaparHtml(piloto.name_acronym ?? piloto.driver_number)}</option>`)
    .join("");
}

async function actualizarAnalisisVuelta() {
  const driverNumber = Number(selectorPilotoAnalisis.value);
  const alcance = selectorAlcanceAnalisis.value;
  if (!driverNumber) return;
  if (!corridaReplaySeleccionada) {
    // Sin corrida no hay analisis posible, y decirlo es preferible a pedir una
    // ruta con la corrida en `null` y mostrar el error de red resultante.
    selectorVueltaAnalisis.innerHTML = "";
    renderizarDetalleAnalisis(null);
    estadoAnalisisVuelta.textContent = "Sin corrida de replay para esta sesion";
    resumenAnalisisVuelta.textContent = "El analisis por vuelta se calcula sobre una corrida de replay, y esta sesion no tiene ninguna persistida.";
    return;
  }
  etiquetaSelectorVuelta.textContent = alcance === "stint" ? "Stint" : "Vuelta";
  estadoAnalisisVuelta.textContent = "Cargando analisis...";
  try {
    const filas = await obtenerAnalisis(driverNumber, alcance);
    if (!filas.length) {
      selectorVueltaAnalisis.innerHTML = "";
      renderizarDetalleAnalisis(null);
      estadoAnalisisVuelta.textContent = "Sin analisis generado para esta corrida";
      resumenAnalisisVuelta.textContent = "Ejecutar scripts/generate_session_analysis.py para generarlo.";
      return;
    }
    const claveNumero = alcance === "stint" ? "stint_number" : "lap_number";
    const seleccionPrevia = selectorVueltaAnalisis.value;
    selectorVueltaAnalisis.innerHTML = filas
      .map((fila) => `<option value="${fila[claveNumero]}">${fila[claveNumero]}</option>`)
      .join("");
    if (filas.some((fila) => String(fila[claveNumero]) === seleccionPrevia)) {
      selectorVueltaAnalisis.value = seleccionPrevia;
    }
    const elegida = filas.find((fila) => String(fila[claveNumero]) === selectorVueltaAnalisis.value) ?? filas[0];
    renderizarDetalleAnalisis(elegida);
    estadoAnalisisVuelta.textContent = `${filas.length} ${alcance === "stint" ? "stints" : "vueltas"} analizadas · ${escaparHtml(elegida.analyzer_version ?? "")}`;
    resumenAnalisisVuelta.textContent = "Las metricas se muestran separadas por nivel de evidencia: lo observado, lo derivado y la calidad de la muestra que las sostiene.";
  } catch (error) {
    estadoAnalisisVuelta.textContent = "No se pudo cargar el analisis";
    resumenAnalisisVuelta.textContent = String(error.message ?? error);
  }
}

function mostrarDetalleSeleccionado() {
  const alcance = selectorAlcanceAnalisis.value;
  const clave = `${alcance}:${Number(selectorPilotoAnalisis.value)}`;
  const filas = cacheAnalisis.get(clave) ?? [];
  const claveNumero = alcance === "stint" ? "stint_number" : "lap_number";
  renderizarDetalleAnalisis(filas.find((fila) => String(fila[claveNumero]) === selectorVueltaAnalisis.value));
}

selectorPilotoAnalisis?.addEventListener("change", actualizarAnalisisVuelta);
selectorAlcanceAnalisis?.addEventListener("change", actualizarAnalisisVuelta);
selectorVueltaAnalisis?.addEventListener("change", mostrarDetalleSeleccionado);
