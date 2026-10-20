# Recuperación de ASSIGNED y reinicio de lote discreto

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Corregir la preparación de programas nuevos y ejecutar de nuevo las 60 celdas TEXT solicitadas por Henry.

**Architecture:** Mismo motor para Normal y Experimental. Liberar bindings digitales anteriores sin protección persistente, preservando direcciones/tipos/configuración física y los dispositivos de proceso analógicos/DB; una ampliación conserva los bindings actuales. Congelar una versión nueva sin modificar el benchmark ni las expectativas del Oracle.

**Tech Stack:** Python, pytest, Tk, TIA Openness V18 y PLCSIM Advanced.

**Spec:** Solicitud de Henry del 20-10-2026: ASSIGNED recuerda programas anteriores y puede sobrescribirse para un programa nuevo; retirar ensayos del lote defectuoso y ejecutar nuevamente TEXT.

## Restricciones

- Conservar LOCKED y reservas manuales/persistent explícitas; mantener todos los atributos de hardware.
- No cambiar los requisitos, variantes o expectativas para obtener PASS.
- No modificar el maestro ni descargar a PLC físico.
- Retirar solo el lote TEXT_FORMAL_20261020_001 y sus ensayos referenciados, con respaldo verificado fuera del árbol activo de resultados.
- Preservar los freezes anteriores y registrar una identidad nueva para la campaña corregida.

## Tareas

- [x] Reproducir con una prueba la asignación fallida sobre el mapa real, sin llamadas API/TIA.
- [x] Corregir la preparación compartida y probar nuevo programa, ampliación, reservas y conservación de señales de proceso.
- [x] Ejecutar regresiones pertinentes y la suite completa; revisar diferencias.
- [x] Respaldar y retirar el lote cancelado con validación de rutas y restauración documentada.
- [x] Integrar el cambio, preparar THESIS_DISCRETE_V3 y comprobar su freeze y runtime.
- [ ] Reiniciar GUI con código nuevo, ejecutar lote TEXT FORMAL de 60 y observar su inicio/persistencia.

## Decisiones y evidencia

- El lote original está CANCELLED con 29 ensayos terminados antes de cambiar código.
- Causa: PRODUCT_DECLARED_V1 exige owner/source para liberar y el banco digital heredado carece de esos datos; no quedan canales digitales FREE.
- Las asignaciones analógicas/DB describen dispositivos de proceso y se preservan; el problema reportado corresponde a los bindings digitales del lote discreto.
- RED inicial: cinco fallos reproducidos, cuatro recursos del banco real y un propietario antiguo distinto; 85 regresiones relevantes pasaron tras el primer ajuste.
- Revisión independiente: detectó que reutilizar un nombre digital sin propuesta dejaba el canal FREE tras commit. Dos pruebas adicionales reprodujeron el defecto antes de corregir el sellado; 87 regresiones relevantes pasan después.
- La primera suite amplia se invalidó por configuración local ausente, rutas largas y cambio de identidad durante la ejecución. La segunda alcanzó más de 2.000 pruebas sin fallos de aserción, pero terminó por una violación de acceso nativa de Tk. Se ejecuta la colección completa en grupos de procesos secuenciales con los archivos estables.
- Retirados 29 ensayos y el manifiesto del lote cancelado; 374 archivos verificados en `runtime/backups/assigned_restart_20261020_131002`. Los stubs ARCHIVED.json reservan los identificadores sin aportar trial.json o batch_manifest.json a las estadísticas activas.
- Revisión final del sellado: sin observaciones pendientes. PLCSIM TESIS_PLC_SIM responde CONNECTED/RUN y el MASTER conserva FORMAL_READY/VALID.
- Validación final: colección completa de 2.193 pruebas ejecutada en cinco procesos secuenciales; 2.185 PASS, 8 SKIP, 0 FAIL y 0 ERROR. Informe y JUnit por grupo en `runtime/assigned_restart_20261020/regression_groups/`. `git diff --check` sin observaciones.
- Integrado en el programa principal en c5800c9. Freeze THESIS_DISCRETE_V3 validado: 391 archivos, 32 Oracles íntegros y maestro FORMAL_READY; se conserva el freeze THESIS_DISCRETE_V2. El lanzador operativo utiliza la función existente `VozLLMPLCGUI.start_text_batch` y espera a que se cierre la GUI anterior antes de arrancar otra instancia.
