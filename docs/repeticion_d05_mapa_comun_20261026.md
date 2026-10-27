# Repetición D05 con inventario común 8+8

Autorización: el autor aprobó el 26-10-2026 repetir exclusivamente las nueve celdas D05 con el mapa de simulación 8+8, conservar los originales y sustituir las nueve celdas en el análisis revisado independientemente de su resultado.

## Diseño y límites

- Tres variantes por tres modalidades, en orden TEXT, VOICE_CLEAN y VOICE_NOISE. Los seis archivos de audio se reutilizan exactamente, sin grabar ni volver a mezclar.
- Copia preparada del mapa base congelado: ocho entradas BOOL en bytes16 y ocho salidas BOOL en byte8. I_Start/I_Stop conservan sus canales protegidos. El canal digital disponible I16.2 se declara I_Emergency, LOCKED y autorizado como SAFETY_TRIP exclusivamente en simulación. El mapa original no se modifica.
- Se conserva el intérprete, ASR, prompt, catálogo, reglas, generador local y Oracle D05. No se añade memoria, rearme manual ni una expectativa de rearranque que el requisito no exige.
- La ejecución utiliza el mismo motor de producto, protocolo de voz, persistencia, evaluación diferida y copia aislada del maestro TIA. No se crea otro intérprete ni un evaluador paralelo.
- Se confirma PLCSIM_ADVANCED/TESIS_PLC_SIM y se aplica el precheck de entorno antes de llamar servicios. No se utiliza un controlador físico.
- Una ejecución seleccionada por celda; los reintentos internos permanecen en la invocación. Una incidencia técnica pausa la campaña y conserva todo intento. Los fallos funcionales no provocan búsqueda de un resultado favorable.
- Los nuevos ensayos se etiquetan como repetición de desarrollo con motivo, enlace al original y manifiesto previo. No se presenta identidad de software congelado completa si los hashes no la acreditan.
- El artículo podrá describir inventario común8+8 con revisión específica de autorización para D05. No se afirmará que los180 registros históricos usaron un JSON idéntico desde el principio.

## Pasos y registro

- [x] Congelar mapa revisado, fuentes, audios, orden y selección antes de ejecutar.
- [x] Validar sin API los nueve estímulos, compatibilidad y entorno virtual.
- [x] Ejecutar las nueve celdas, conservando artefactos y trazas por etapa.
- [x] Verificar integridad, I/O, pareamiento y persistencia de los nuevos ensayos.
- [x] Crear matriz revisada180 =171 anteriores +9 nuevos; conservar la matriz anterior.
- [x] Recalcular estadísticas, gráficos y manuscrito; compilar y revisar entregables.

La ejecución se registra en `runtime/d05_mapa_comun_20261026/`. Los resultados originales y la entrega anterior se conservan.

## Resultado verificado

Nueve ejecuciones:8 PASS y1 FAIL. Matriz revisada:163 PASS,16 FAIL y un REVIEW. Se conservaron los3826 archivos fuente originales y las171 celdas ajenas a D05. Artículo14 páginas físicas y suplemento18, compilados y revisados. Entrega:output/articulo_d05_mapa_comun_20261026.zip.
