const API_BASE_URL = "http://127.0.0.1:8000";
const SESSION_ID = "mqtt_phase_recalibrated_01";
const ENDPOINT_SESION = `${API_BASE_URL}/telemetry/by-session/${SESSION_ID}?limit=100`;
const INTERVALO_RECARGA_MS = 3000;
const OPENF1_SESSION_KEY = 9947;

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
// Corrida de replay que analiza el dashboard.
//
// Apuntaba a `silverstone_2025_probe_151800_151810_v1`, un sondeo de 963 mensajes
// que abarca 9,9 segundos de carrera. La sesion contiene ademas una decena larga de
// sondeos de carga bajo el mismo `session_id`, de modo que elegir corrida de forma
// explicita no es opcional: sin ese filtro se mezclan repeticiones de las mismas
// vueltas. `d7_silverstone_full_001` es la carrera completa verificada.
const REPLAY_RUN_ID_ANALISIS_CARRERA = "d7_silverstone_full_001";

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
    const respuesta = await fetch(`${API_BASE_URL}/racing/sessions/${OPENF1_SESSION_KEY}/context-at?${parametros}`);
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
        replay_run_id: REPLAY_RUN_ID_ANALISIS_CARRERA,
        signal: configuracion.signalName ?? signalName,
      });
      pilotosSeleccionados.forEach((driver) => parametros.append("drivers", driver));
      const respuesta = await fetch(`${API_BASE_URL}/racing/sessions/${OPENF1_SESSION_KEY}/replay-series?${parametros}`);
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
    estadoAnalisisCarrera.textContent = `${pilotosSeleccionados.length} pilotos · ${seriesPorSenal.speed.length} puntos de velocidad · replay v1`;
    ultimaSerieCarrera = { ...rangoComun, series: seriesPorSenal, puntos: seriesPorSenal.speed.map((mensaje) => ({ tiempo: new Date(mensaje.timestamp).getTime() })), margen: { izquierdo: 66 }, areaAncho: GRAFICOS_CARRERA.speed.width - 96 };
  } catch (error) {
    console.error(error);
    estadoAnalisisCarrera.textContent = "No se pudieron cargar las series coordinadas.";
  }
}

async function cargarReplayOpenF1() {
  openF1EstadoCarga.textContent = "Consultando replay y contexto...";
  try {
    const [sesionRespuesta, pilotosRespuesta] = await Promise.all([
      fetch(`${API_BASE_URL}/racing/sessions/${OPENF1_SESSION_KEY}`),
      fetch(`${API_BASE_URL}/racing/sessions/${OPENF1_SESSION_KEY}/drivers`),
    ]);
    if (!sesionRespuesta.ok || !pilotosRespuesta.ok) {
      throw new Error("No se pudo recuperar el contexto OpenF1.");
    }
    const sesion = await sesionRespuesta.json();
    pilotosOpenF1 = await pilotosRespuesta.json();
    renderizarCasillasPilotos();
    const pilotosSeleccionados = obtenerPilotosSeleccionados();
    if (!pilotosSeleccionados.length) {
      renderizarComparacionPilotos([]);
      cargarSerieCarrera();
      openF1EstadoCarga.textContent = "Selecciona al menos un piloto para iniciar la comparacion.";
      return;
    }
    // Se pide una muestra acotada por piloto seleccionado en vez de la sesion
    // completa. La llamada anterior no filtraba por corrida ni por piloto y no
    // tenia tope: con la carrera persistida pedia 10.079.006 filas al backend.
    const [replayPorPiloto, comparacionRespuesta] = await Promise.all([
      Promise.all(pilotosSeleccionados.map(async (numero) => {
        const parametros = new URLSearchParams({
          replay_run_id: REPLAY_RUN_ID_ANALISIS_CARRERA,
          driver_number: String(numero),
          limite: String(LIMITE_MUESTRAS_AUDITORIA_POR_PILOTO),
        });
        const respuesta = await fetch(`${API_BASE_URL}/racing/sessions/${OPENF1_SESSION_KEY}/replay?${parametros}`);
        if (!respuesta.ok) {
          throw new Error("No se pudo recuperar el lote replay.");
        }
        return { numero, cuerpo: await respuesta.json() };
      })),
      fetch(`${API_BASE_URL}/racing/sessions/${OPENF1_SESSION_KEY}/driver-comparison?${pilotosSeleccionados.map((driver) => `drivers=${driver}`).join("&")}`),
    ]);
    if (!comparacionRespuesta.ok) {
      throw new Error("No se pudo recuperar la comparacion de pilotos.");
    }
    const comparacion = await comparacionRespuesta.json();
    // Un piloto tiene traza si su propia consulta devolvio muestras. Antes esto se
    // deducia descargando la sesion entera y agrupando en el navegador.
    pilotosConTelemetriaReplay = new Set(
      replayPorPiloto.filter(({ cuerpo }) => cuerpo.total_devuelto > 0).map(({ numero }) => numero),
    );
    renderizarCasillasPilotos();
    const mensajesSeleccionados = replayPorPiloto.flatMap(({ cuerpo }) => cuerpo.muestras);
    openF1Titulo.textContent = `${sesion.circuit_short_name} ${sesion.session_name} · Comparador operativo`;
    openF1Resumen.textContent = `Corrida ${REPLAY_RUN_ID_ANALISIS_CARRERA} · ${sesion.laps} vueltas · ${sesion.stints} stints · ${sesion.race_control_events} eventos de control.`;
    openF1Contexto.innerHTML = [["Sesion", sesion.session_key], ["Meeting", sesion.meeting_key], ["Seleccion", `${pilotosSeleccionados.length} pilotos`], ["Muestras", `${mensajesSeleccionados.length} (max ${LIMITE_MUESTRAS_AUDITORIA_POR_PILOTO} por piloto)`], ["Granularidad", "car_data ~3.7 Hz"], ["Calidad", "observed_openf1"]].map(([etiqueta, valor]) => `<div><dt>${escaparHtml(etiqueta)}</dt><dd>${escaparHtml(valor)}</dd></div>`).join("");
    renderizarComparacionPilotos(comparacion);
    cargarSerieCarrera();
    renderizarTablaOpenF1(mensajesSeleccionados);
    openF1EstadoCarga.textContent = `${mensajesSeleccionados.length} mensajes de muestra para auditoria de formato. No es el total de la corrida.`;
    etiquetaCabecera.textContent = "Analisis historico de carrera";
    tituloCabecera.textContent = `${sesion.circuit_short_name} ${new Date(sesion.date_start).getUTCFullYear()} · ${sesion.session_name}`;
    resumenSesion.textContent = `${sesion.country_name} · sesion ${sesion.session_key} · replay historico persistido`;
    estadoOrigen.textContent = "OPENF1 HISTORICAL REPLAY";
    estadoOrigen.className = "estado-origen estado-openf1-replay";
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

function cambiarModo() {
  const openF1Activo = selectorModo.value === "openf1";
  document.body.classList.toggle("modo-openf1-activo", openF1Activo);
  document.querySelectorAll(".modo-simulacion").forEach((elemento) => {
    elemento.hidden = openF1Activo;
  });
  panelOpenF1.hidden = !openF1Activo;
  if (openF1Activo) {
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

cargarSesion();
// La recarga conserva soporte para una vista actualizable, aunque la demo actual
// usa una sesion historica y finita.
setInterval(cargarSesion, INTERVALO_RECARGA_MS);
