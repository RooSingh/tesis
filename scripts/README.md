# Scripts

Herramientas de línea de comandos. Se corren desde la raíz del repositorio,
con el entorno de Python activado: `python scripts/<nombre>.py --help` muestra
las opciones de cada una.

## Servicios y operación

| script | qué hace |
| --- | --- |
| `capturar_f1_25.py` | capturador continuo de F1 25: escucha UDP 20777, guarda la captura cruda y publica por MQTT |
| `run_mqtt_consumer.py` | inicia el consumidor MQTT que persiste en la base |
| `apply_database_migration.py` | aplica una migración de `database/` |
| `convertir_a_hipertabla.py` | convierte la tabla de telemetría en hipertabla comprimida, por lotes |
| `escribir_en_el_pasado.py` | descomprime los fragmentos de una sesión, escribe y recomprime |
| `respaldo_spa.py` | exporta una sesión y la restaura en una base vacía |
| `activar_servicios.ps1` / `desactivar_servicios.ps1` | registran o quitan los servicios como tareas programadas de Windows |
| `activar_capturador.ps1` / `desactivar_capturador.ps1` | ídem, sólo el capturador |
| `*_servicio.bat` | lanzadores que usan esas tareas programadas |

## Fuentes de datos

| script | qué hace |
| --- | --- |
| `reproducir_captura_f1_25.py` | reemite una captura de F1 25 por UDP, con degradación controlada (descarte, *jitter*, retraso) |
| `republicar_captura.py` | vuelve a publicar una captura para completar lo que falte en la base |
| `recompletar_de_a_uno.py` | recompleta los vehículos rivales de una captura, de a uno por vez |
| `rederivar_metadatos.py` | vuelve a derivar los metadatos de capturas ya grabadas |
| `extraer_can.py` | extrae las tramas CAN de un segmento a formato propio (usa openpilot) |
| `reproducir_can.py` | reproduce tramas CAN grabadas hacia el contrato interno |
| `reconstruir_recorrido_can.py` | reconstruye el recorrido de un vehículo desde su bus, sin GPS |
| `descargar_paquete_openf1.py` | descarga el paquete de contexto de una sesión de OpenF1 |
| `download_openf1_session_telemetry.py` | completa la telemetría faltante de una sesión de OpenF1 |
| `encolar_cargas_openf1.py` | corre varias cargas de OpenF1 en secuencia |
| `prepare_replay_stream.py` | prepara un flujo ordenado para la reproducción de OpenF1 |
| `replay_openf1.py` | reproduce datos de OpenF1 por MQTT |
| `validate_session_package.py` / `import_session_package.py` | validan e importan un paquete de sesión |
| `day18_*.py` | recolección y carga de sesiones de OpenF1 |

## Análisis

| script | qué hace |
| --- | --- |
| `analizar_carrera_f1_25.py` | reconstruye una carrera a partir de una captura cruda |
| `analizar_vueltas_f1_25.py` | analiza vuelta por vuelta, detectando incidentes |
| `generate_session_analysis.py` | análisis automático de una sesión reproducida |
| `energia_recuperada_por_vuelta.py` | energía del ERS por vuelta |
| `firma_de_giros.py` | firma de giros de un circuito |
| `buscar_dos_humanos.py` | busca capturas con dos conductores humanos |
| `day2_*.py`, `day12_*.py`, `day16_*.py`, `day17_*.py` | análisis exploratorio del bus CAN del RAV4 para identificar señales |

## Mediciones de desempeño

| script | qué mide |
| --- | --- |
| `medir_latencia_cadena.py`, `medir_latencia_can.py` | latencia de punta a punta de la cadena |
| `medir_caudal_por_fuente.py`, `medir_caudal_sostenido_can.py` | caudal de cada fuente y su sostenimiento |
| `medir_cadena_parrilla_completa.py` | la cadena bajo la carga de una parrilla completa |
| `medir_consumo_de_recursos.py` | procesador, memoria y red bajo carga |
| `medir_costo_del_flujo_en_vivo.py` | costo del flujo en vivo en el servidor |
| `medir_tiempo_de_recuperacion.py` | recuperación ante un corte del consumidor |
| `medir_limite_sin_confirmar.py`, `acotar_ventana_en_vuelo.py`, `peldano_ventana_consumidor_lento.py` | ventana de mensajes en vuelo del intermediario |
| `medir_compresion_hipertabla.py` | ganancia de la hipertabla comprimida |
| `medir_intervalo_de_emision.py`, `medir_periodicidad_466.py` | regularidad de la emisión |
| `medir_desfase_de_relojes.py` | deriva entre relojes |
| `medir_recompletado.py` | costo del recompletado de rivales |
| `medir_curvas_de_un_circuito.py`, `medir_limites_de_pista.py` | curvas y límites de pista sobre el dato |
| `correr_escenarios_degradacion.py`, `provocar_fallas.py`, `carga_viva_aislada.py` | escenarios de degradación y fallas |
| `generar_figuras_mediciones.py` | arma los datos de las figuras de las mediciones |

## Verificaciones

| script | qué comprueba |
| --- | --- |
| `verificar_topes_intermediario.py` | que Mosquitto aplique los topes declarados, midiendo su conducta |
| `verificar_confirmacion_manual.py`, `verificar_sesion_persistente.py` | que no se pierdan mensajes con el consumidor caído |
| `verificar_hipertabla_comprimida.py` | que se pueda operar sobre la hipertabla comprimida |
| `verificar_anotador_vivo.py` | el anotador en vivo contra la lectura posterior |
| `verificar_lateral_generador.py` | la aceleración lateral del generador contra v·ω |
| `verificar_minisectores_contra_sectores.py` | la lectura de minisectores de OpenF1 contra los tiempos oficiales |
| `verificar_tablero.py` | que las funciones del tablero sigan existiendo |
| `calibrar_reconstruccion.py` | el error de la reconstrucción de recorrido |
| `contrastar_panel_contra_dato.py`, `extraer_cuadros_validacion.py` | el panel del juego contra la captura, con cuadros de video |
| `rastrear_un_mensaje.py`, `recontar_origenes_can.py`, `manifiesto_capturas.py` | trazabilidad de mensajes y capturas |
