# Selector de PLC y GUI simplificada

El destino de Modo Normal se selecciona en **Seleccionar PLC**. El mapa IO sigue describiendo los dispositivos y sus escalas; elegir un destino no cambia el mapa ni convierte la CPU de la plantilla.

## Uso

1. Configure en Preferencias → Configurar TIA la plantilla compatible con la CPU y sus módulos.
2. Abra Seleccionar PLC y pulse Buscar. Las instancias virtuales proceden de PLCSIM Advanced; las interfaces PG/PC y los puertos proceden del proyecto TIA.
3. Seleccione explícitamente la instancia, la dirección leída correspondiente y la interfaz. En hardware, escriba la dirección del PLC. Revise el proyecto y su CPU esperada antes de aceptar.
4. Actualice el estado. Una configuración guardada no demuestra conexión ni RUN. Un cambio de destino invalida la disponibilidad de carga anterior; recompile el paquete para el destino actual sin necesidad de reinterpretarlo.
5. Use Generar y compilar, Ejecutar y cargar al PLC, Cargar programa al PLC o la ejecución por voz según corresponda.

La biblioteca y la edición se concentran en **Abrir mapa I/O completo**: variables, tipos, escalas, bloqueos, guardado y operaciones de biblioteca/TIA. Preferencias conserva API, parser y ajustes TIA. Herramientas avanzadas conserva voz manual, micrófonos, mantenimiento, diagnóstico, pruebas de IO y puesta en marcha PID. El acceso PID también aparece para un programa PID disponible.

## Alcance

TIA Openness V18 ofrece interfaces y descarga por dirección, pero esta integración no ofrece descubrimiento automático de PLC físicos. El destino físico se configura manualmente. Su identidad, compatibilidad y estado permanecen sin verificar mientras no exista una lectura que los confirme. La carga manual conserva su confirmación; la carga automática por voz no se habilita para un destino físico nuevo sin verificar. Las herramientas actuales de IO/modelo PID permanecen limitadas a PLCSIM.

El selector mantiene separados los destinos Normal y Experimentación. La instancia elegida se identifica por nombre e ID; un ID desaparecido o que corresponde a otro nombre no autoriza operaciones sobre un sustituto. Cancelar no persiste cambios. Los resultados de estado de un destino anterior se descartan.

## Respaldo y evidencia

El respaldo previo está en `runtime/backups/before_plc_selector_20261019_105048/RESTAURAR.md`: 11 893 archivos restaurados y comprobados, historial, índice y snapshot TIA. Las credenciales permanecen fuera de los ZIP.

La validación de esta entrega se registra en `runtime/plc_selector_validation/delivery.json`. Sus pruebas son evidencia de desarrollo; no sustituyen ni cambian los ensayos formales anteriores. El informe distingue pruebas locales, comprobaciones reales y capacidades aún no probadas.


La dirección explícita se crea en la colección `ConfigurationTargetInterface.Addresses` del puerto elegido, según el ejemplo oficial de [Siemens sobre DownloadProvider](https://docs.tia.siemens.cloud/r/en-us/v20/tia-portal-openness-api-for-automation-of-engineering-workflows/tia-portal-openness-api/functions-for-accessing-the-data-of-a-plc-device/functions-for-downloading-data-to-plc-device/downloading-to-plc-devices). La colección de la interfaz PG/PC no permite esa creación en el contexto DeviceItem de la versión instalada; la comprobación real es el criterio de habilitación.


## Comprobaciones y decisiones de esta entrega

- TIA V18 enumeró la CPU PLC_1, las interfaces PG/PC y los puertos X1/X2 de S71500_Prueba. PLCSIM devolvió una sola instancia, TESIS_PLC_SIM, ID 0; un ID inexistente devolvió instancia no encontrada.
- La descarga con dirección explícita se probó en una copia recuperada de una instantánea actual del proyecto, usando el adaptador virtual verificado. TIA confirmó la dirección 192.168.0.1 y la Runtime API confirmó RUN.
- El botón Ejecutar y cargar se probó con interpretación previamente guardada, generación real, compilación real y descarga real. No hubo llamadas nuevas al LLM. La fuente generada fue idéntica por SHA-256 a la del contador anterior; los tags y los 14 valores legibles del DB coincidieron después.
- La geometría y el ancho de los textos principales se comprobaron mediante Tk a 1920×1080 y 1600×900. Esto no equivale a una inspección visual independiente ni a una prueba de planta física.
- Los auxiliares de registro se ejecutaron con Python porque no estaba disponible Git Bash. Su riesgo es una diferencia de registro; se contrastan con resultados de pruebas, commits y hashes.
- Se conserva la configuración Runtime compartida histórica para Experimentación. La identidad Runtime Normal se guarda dentro de su propio destino, en el mismo JSON atómico. Los consumidores nuevos deben utilizar ese destino explícito; las llamadas antiguas conservan su comportamiento.
- La suite del producto se ejecuta completa desde tests/. La búsqueda inicial sin ruta incluyó copias temporales de runtime y falló en recolección; no se considera una ejecución aprobada. El riesgo de omitir pruebas externas se controla usando todos los módulos del directorio de pruebas del proyecto, sin filtros.
- La integración se realiza por copia con respaldo y hashes, manteniendo la rama y la evidencia. No se fusiona Git ni se altera el índice principal. Cualquier archivo concurrentemente modificado bloquea su sustitución; la recuperación usa el respaldo de integración y el respaldo completo previo.

Mejora menor pendiente de la revisión: el mensaje final de una búsqueda puede reemplazar el detalle de un error de proveedor. Los informes de consulta se conservan para diagnóstico. Las pruebas de hardware físico y de selección entre varias instancias reales quedan fuera de los hechos demostrados en este equipo.

## Regresión de la entrega

Se ejecutaron los 2 113 casos recopilados en los 144 módulos del directorio tests/, sin filtros ni reintentos: 2 105 aprobados, siete omitidos y un fallo esperado. Los 530 archivos de entrada sellados no cambiaron. Cada módulo se ejecutó consecutivamente en un proceso nuevo; se comprobó que la lista completa de identificadores coincidiera con la recopilación global.

La ejecución previa en un único proceso alcanzó el 95 % sin fallos de pruebas y terminó con una excepción nativa de Windows en Tk durante test_text_batch. Ese módulo pasó sus 26 pruebas por separado y de nuevo en la ejecución completa por módulos. No se afirma haber corregido la causa del cierre nativo ni haber validado una sesión GUI prolongada equivalente. El registro conserva también los intentos anteriores fallidos o interrumpidos.

Los temporales usan una ruta corta de runtime para respetar los límites de nombres de archivo de Windows. Las pruebas GUI guardan sus historiales en directorios temporales propios; la persistencia de historial del producto conserva su comportamiento y el archivo existente se protege por hash. El selector rechaza combinar una instancia virtual con una interfaz física.

La carpeta principal recibió 28 archivos mediante copia protegida, con respaldo individual previo. Ambos puentes compilaron y las 115 pruebas focalizadas sobre esa carpeta pasaron. Los 3 813 archivos protegidos ajenos al cambio, el historial, las credenciales y las 496 entradas del índice Git se conservaron. Para ver la nueva interfaz, cierre y vuelva a abrir la aplicación; no es necesario cambiar su conexión actual a TESIS_PLC_SIM.
