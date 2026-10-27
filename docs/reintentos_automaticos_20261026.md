# Reintentos técnicos automáticos para la nueva campaña

Solicitud: reintentar automáticamente un comando si falla la infraestructura. El caso D05 puede utilizar un canal digital disponible compatible; su función de emergencia debe quedar autorizada en el mapa y vinculada al Oracle. No se modifica aquí la política de señales del banco físico ni los mapas históricos.

## Diseño y plan de implementación

- Configuración para lotes nuevos: máximo dos reintentos adicionales, después de 5 y 15 segundos. La política se copia al manifiesto al crear el lote. Los lotes anteriores sin política conservan el comportamiento manual.
- Solo INFRASTRUCTURE_ERROR terminado. FAIL, REVIEW, precheck bloqueado, integridad, autorización/cuota inválida y estados interrumpidos requieren tratamiento distinto y no provocan repetición automática.
- Evaluación fallida: nuevo attempt del mismo programa, conservando el intento previo. Generación/ASR fallidos por transporte: ensayo nuevo enlazado al anterior, mismo comando y audio congelado.
- Programación secuencial mediante Tk.after, sin bloquear la interfaz. Pausar/detener cancela la espera; cerrar la aplicación no inicia reintentos al reabrir. El contador se conserva en el manifiesto y no se reinicia por intervención manual.
- Motivo, origen, espera y número de reintento quedan en el manifiesto/resumen JSON. Si se agotan los reintentos, el lote se pausa. Nunca se repite un resultado experimental para buscar PASS.

Pasos: pruebas de política y del controlador con dobles, implementación, regresión del lote/voz y actualización de este registro. No se llama a API ni se ejecutan ensayos reales durante esta corrección.

## Coordinación de la nueva campaña

El autor indicó que realizará personalmente el lote de texto. Codex ejecutará las modalidades VOICE_CLEAN y VOICE_NOISE únicamente cuando el autor lo solicite después, reutilizando las grabaciones limpias y las mezclas ya guardadas. No se inicia ahora ninguna campaña ni se reemplazan las estadísticas existentes.

Antes de iniciar resultados de una nueva campaña, deben verificarse el mapa efectivo de D05, los hashes de los audios y la configuración exclusiva LLM, y congelarse la nueva versión con esta política de reintentos. Los manifiestos de campañas anteriores se conservan; esta edición no les añade retroactivamente la política automática.

## Verificación de la corrección

Regresión final: **93 pruebas aprobadas y 2 omitidas**, sin fallos. Registro JUnit: `runtime/retry_cierre_20261026.xml`. Se comprobaron los límites por comando, el mantenimiento del programa al repetir la evaluación, el enlace de una nueva generación tras fallo de transporte, el mismo audio limpio/ruidoso sin recaptura, la conservación de los intentos y el funcionamiento del botón Pausar durante la espera. Las pruebas utilizaron dobles de servicios, TIA, Runtime y Oracle; no son resultados experimentales de la tesis.

Los indicadores `allow_rule_fallback` y `allow_fallback_to_rules` continúan desactivados. Para cargar el controlador actualizado debe reiniciarse la aplicación. No se ha sustituido ni alterado el mapa del banco físico.
