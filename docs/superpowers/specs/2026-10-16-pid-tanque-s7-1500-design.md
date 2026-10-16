# Primer control completo de tanque con PID_Compact

Fecha: 2026-10-16. Estado: propuesta para revisión; todavía no implementada.

## Resultado solicitado

Configurar el banco S7-1500 existente para un transmisor de nivel y una válvula proporcional de llenado. Generar desde el comando y el mapa el escalamiento, el controlador Siemens nativo, sus datos y su llamada periódica. Entregar un primer programa que pueda compilarse y probarse en PLCSIM antes de usar la planta.

El usuario autorizó elegir una configuración inicial editable y eligió **válvula proporcional de llenado**. Las direcciones y la separación corriente/voltaje del banco están confirmadas. Los modelos, rangos raw, cableado y comportamiento del dispositivo todavía no están comprobados: los valores siguientes son una propuesta de prueba, no una certificación del hardware.

## Configuración propuesta del banco

Modificar solamente `data/plc_maps/mapa_banco_fisico_working.json`, con copia de seguridad y comparación del contenido justo antes de guardar. Mantener todos sus 24 canales y sus direcciones; conservar el mapa base y los activos experimentales congelados. No cambiar el mapa activo en silencio. Si el archivo cambia durante la preparación, rehacer la propuesta sobre el contenido nuevo antes de guardarla.

| Función | Nombre | Dirección del mapa | Configuración inicial |
|---|---|---|---|
| Arranque | I_Start | %IX16.0 | Conservar nombre, dirección y bloqueo |
| Parada | I_Stop | %IX16.1 | Conservar nombre, dirección y bloqueo |
| Emergencia | I_Emergency | %IX16.2 | Conservar nombre; prioridad de parada |
| Reset | I_Reset | %IX16.3 | Reconocer fallo y permitir nuevo Start |
| Manual | I_Mode_Manual | %IX16.5 | Conservar selector existente |
| Automático | I_Mode_Auto | %IX16.6 | Conservar selector existente |
| Nivel | AI_Level_Raw | %IW4 | Transmisor 4–20 mA; raw 0–27648; nivel 0–100 % |
| Mando de llenado | AO_Fill_Command | %QW4 | Válvula proporcional 4–20 mA; raw 0–27648; apertura 0–100 %; valor ante fallo 0 % |
| Habilitación del equipo de llenado | Q_Pump_Enable | %QX8.4 | Reutilizar el canal FREE Q_Aux_Output |
| Alarma del proceso | Q_Alarm | %QX8.7 | Reutilizar el canal FREE Q_Free_8_7 |

La habilitación digital queda disponible para una bomba de alimentación/permiso del banco; no sustituye el mando proporcional de la válvula ni se exige energizar una bomba inexistente. El ejemplo habilita esta salida solamente mientras el control está autorizado. Se documentará que la conexión física de ese permiso es opcional y debe corresponder al banco.

No reasignar las salidas ASSIGNED Q_Traffic_Green, Q_Traffic_Yellow y Q_Traffic_Red. Mantener los demás canales como están. Si alguno de los cuatro canales elegidos dejó de estar FREE o ya tiene configuración propia, no sustituirla automáticamente: presentar el conflicto concreto.

Los dos canales analógicos tendrán `analog_config` con señal, dispositivo, magnitud, unidad, rangos y respuesta ante fallo. Se registrará la procedencia de los valores como `ASSUMED_FOR_TEST`; `confirmed=false` hasta que el investigador compruebe el módulo/dispositivo. Autorizar sus nombres para interpretación y conservar esta confirmación física separada de la disponibilidad de simulación. No marcar como comprobados los rangos de corriente/raw por elegirlos para una prueba.

## Enfoque seleccionado y alternativas

Se recomienda crear un objeto tecnológico PID_Compact de instancia individual mediante **TIA Openness**, generar SCL para la lógica de proceso y crear/configurar un OB de interrupción cíclica. Aprovecha la API V18 instalada y conserva la puesta en marcha estándar de Siemens.

Una alternativa es exigir al usuario un PID y un OB previamente cableados en la plantilla. Reduce el trabajo del generador, pero no satisface el requisito de que el software cree esa infraestructura. Otra es generar un algoritmo PI propio en SCL: no satisface la exigencia de utilizar el bloque PID estándar ni permite atribuirle sus funciones de sintonización. Ambas quedan fuera del primer entregable.

## Integración en el proyecto

Se amplía el pipeline actual parser → validación → IR → adaptador Siemens → Openness. No se crea un segundo generador de programas ni se identifica el comportamiento por una frase literal.

Añadir una representación explícita de un lazo `pid_control` en los requisitos funcionales y un descriptor tipado en la IR. Debe identificar entrada analógica, salida analógica, setpoint y unidad, dirección de acción, período, modo SIMULATION/PHYSICAL y entradas de Start/Stop/Reset/emergencia. El ejemplo usa setpoint 50 %, límites 0–100 %, acción de llenado (nivel bajo requiere mayor apertura) y período 100 ms.

El LLM interpreta el objetivo y los recursos; no inventa calibraciones, ganancias, parámetros de Openness ni direcciones. La validación determinista comprueba que los canales existen, están permitidos, tienen dirección/tipo compatibles y unidades coherentes. Un comando ambiguo entre llenar y vaciar debe pedir esa información del proceso.

Los requisitos históricos de `INT_PID_SUPERVISOR` siguen disponibles para P01–P12. No se convierten silenciosamente en un PID ejecutable ni se cambian sus ensayos congelados. Un lazo nativo solicitado explícitamente puede incorporar supervisión compatible, pero se rechaza una mezcla cuyo orden de ejecución o escritores no pueda resolverse.

## Infraestructura Siemens generada

Crear y registrar como propiedad de la aplicación: `PID_Tank_Controller` (objeto tecnológico/DB de instancia individual), `FB_PID_Tank`, `DB_PID_Tank` y `OB_PID_Tank` de interrupción cíclica a 100 ms. El número inicial propuesto es OB30; si está ocupado por un bloque ajeno, informar el conflicto sin reemplazarlo. Evitar cualquier doble llamada del controlador desde OB1 y el OB cíclico.

La API V18 instalada expone `PlcSoftware.TechnologicalObjectGroup.TechnologicalObjects.Create(string, string, Version)` y parámetros mediante `Parameters.Find(...).Value`. La versión de PID debe comprobarse contra CPU/firmware y catálogo reales antes de crearla; se propone comenzar con V2.3 cuando sea compatible. Un rechazo de versión no provoca una sustitución silenciosa por otro algoritmo ni una declaración ficticia del bloque.

El puente debe crear/configurar el objeto tecnológico antes de importar el código que lo llama. Debe importar un OB realmente identificado como interrupción cíclica y comprobar su período efectivo por la API. Declarar solamente `T#100ms` en un manifiesto o renombrar un OB de ciclo no cumple este requisito. La implementación resolverá los atributos admitidos por V18 y comprobará su lectura posterior; si no puede establecerlos, se detiene con un diagnóstico antes de descargar.

Usar el escalamiento de la aplicación para producir `Level_PV` REAL y enviar `Input` al PID con `Config.InputPerOn=false`. Obtener `Output` REAL limitado a 0–100 % y convertirlo una sola vez al raw de la válvula. No usar simultáneamente `Input_PER`/`Output_PER` y el escalamiento externo para el mismo lazo. Aplicar parámetros estáticos con el controlador inactivo y diferenciar nombres específicos de cada versión de PID.

Importar y compilar de forma repetible sin borrar bloques ajenos ni restablecer una sintonización existente porque se generó de nuevo el mismo programa. Una diferencia de versión/configuración del lazo debe producir un diagnóstico y una migración explícita, no una sobrescritura silenciosa.

## Ejecución, paradas y diagnóstico

Orden de cada ciclo: leer/escalar o actualizar planta simulada → comprobar permisivos y fallos → actualizar estado de marcha → llamar al PID una sola vez → aplicar límites y prioridades finales → escalar salida y publicar diagnóstico.

Después de arrancar la CPU el control queda detenido. Start requiere un flanco nuevo y entradas válidas. Stop, emergencia, fallo de sensor, fallo del PID o sobrellenado detienen el llenado, llevan la apertura al valor ante fallo y retiran la habilitación digital. No basta retirar `PID_Enable` dejando intacta la salida anterior.

La parada por fallo/emergencia queda enclavada. Reset solo la reconoce cuando desaparece su causa; no inicia el proceso. Tras Stop o la recuperación de un fallo se exige otro flanco de Start. Mantener Start presionado durante la recuperación no produce rearranque. Un conflicto entre selectores Manual/Automático lleva a reposo con diagnóstico.

Publicar nivel medido/simulado, setpoint solicitado y aceptado, mando calculado y aplicado, validez del sensor, marcha, modo, estado PID, error/advertencia, código de fallo y estado de sintonización. Las variables de control quedan en DB; no se inventan direcciones físicas para ellas.

## Simulación y hardware

La primera prueba completa será **SIMULATION** explícita. Utiliza un modelo de tanque y variables en DB con estado inicial 20 %, entrada máxima 2 puntos porcentuales/s y descarga constante 0,8 puntos/s, paso 0,1 s y nivel limitado a 0–100 %. Este modelo es una demostración editable y no representa por defecto una planta identificada. El PID sigue siendo el PID_Compact nativo ejecutado en PLCSIM; no se reemplaza por un controlador Python para declarar éxito.

En este modo se utiliza una copia declarada de los parámetros de prueba, sin promover a confirmada la calibración del mapa físico. La lógica simulada no utiliza la lectura analógica física como PV y mantiene las salidas de hardware en reposo. El paquete identifica claramente su modo; la falta de canales analógicos no activa una simulación oculta.

**PHYSICAL** exige las dos calibraciones confirmadas y una configuración de control apta para esa planta. El simulador del tanque deja de ser la fuente de PV. No se modifican la configuración de módulos ni el cableado desde el generador.

## Parámetros y sintonización

El ejemplo de simulación usa parámetros de demostración: acción PI, ganancia 2, tiempo integral 20 s y derivativo 0. Se identifican como `DEMO_SIMULATION`, editables y no transferibles automáticamente al hardware. El sistema no declara que estén sintonizados para el equipo real.

Exponer solicitudes explícitas de presintonización/sintonización fina a los modos soportados por PID_Compact, con realimentación de estado, progreso y error. Nunca iniciarlas solo por descargar o arrancar la CPU. Solo se permiten con el lazo habilitado, PV/setpoint válidos, salidas permitidas y límites de proceso definidos. Una parada cancela la solicitud y aplica reposo; reanudar la sintonización requiere otra acción del operador.

Los parámetros aprendidos permanecen en la instancia Siemens; la regeneración no debe sustituirlos por los parámetros de demostración. La puesta en marcha física requiere elegir sintonización del bloque o introducir parámetros verificados para ese proceso.

## Cambios previstos y límites

Componentes afectados: requisitos funcionales/normalización del comando, validación, representación IR, adaptador Siemens, puente C# y empaquetado de sus requisitos de tecnología/OB. El escalamiento existente se reutiliza, admitiendo un escritor PID numérico en vez de exigir una orden fija `analog_output`. La interfaz muestra modo y estado del lazo y proporciona parámetros editables de puesta en marcha.

Un objetivo distinto de Siemens para esta primitiva se rechaza explícitamente hasta disponer de soporte. El sistema de verificación no tratará una llamada PID que su intérprete offline desconoce como simulación aprobada. Se distinguirán análisis estructural, compilación TIA y ejecución nativa en PLCSIM.

Conservar las funciones actuales de programas digitales, metadatos del mapa, backups, transacciones y aislamiento experimental. No cambiar `config/pid_supervisor_config.json` congelado para habilitar el ejemplo nativo; su configuración nueva tendrá identidad propia.

## Verificación y aceptación

1. Verificar la propuesta de mapa: 24 canales, mismas direcciones, sin solapamientos, sin cambios en salidas ya asignadas y con copia exacta anterior recuperable. Verificar que guardar no pierde extensiones/historial ni sobrescribe una edición concurrente.
2. Pruebas de validación: canal no permitido/ausente, rangos pendientes en modo físico, unidades incompatibles, período inválido, escritores duplicados y estado contradictorio. Probar conservación de comandos digitales y supervisores P01–P12.
3. Comprobar que el paquete contiene un solo lazo, la instancia tecnológica requerida, un único escritor final por salida y una sola llamada periódica al PID. Probar repetición de importación y detección de bloques ajenos.
4. Compilar el puente contra las DLL V18 instaladas. Importar el ejemplo en un proyecto de desarrollo aislado derivado del normal configurado; conservar intactos el MASTER formal y el proyecto original. Confirmar por lectura de TIA el tipo de OB, período y versión PID. Guardar informe completo de compilación.
5. Ejecutar en PLCSIM: Start/Stop/Reset/emergencia, setpoint 50 %, cambios a 40/60 %, límites de salida, fallo de sensor y ausencia de rearranque al recuperarse. Para el modelo de demostración, comprobar convergencia a ±2 puntos del setpoint, permanencia durante 10 s y plazo máximo de 300 s tras un cambio. Un resultado que no converge se informa como fallo y requiere ajustar el ejemplo, no cambiar el criterio después de observarlo.
6. La sintonización nativa se considera comprobada solo con evidencia de transición, terminación/error y parámetros del bloque en TIA/PLCSIM. No basta generar los nombres de sus modos.

Entregables de implementación: mapa preparado y respaldado, generación integrada, comando de ejemplo y su paquete completo, instrucciones breves de prueba, resultados de pruebas automáticas y evidencia de compilación/ejecución cuando TIA y PLCSIM estén disponibles. Una comprobación no ejecutada debe figurar como pendiente, nunca como aprobada.

## Fuentes y evidencia técnica

- [Siemens: PID control with PID_Compact, ejemplo de 2022](https://support.industry.siemens.com/cs/attachments/100746401/100746401_S71x00_PidCompact_DOC_V3.0_en.pdf): uso del OB cíclico y ejemplo de simulación.
- [Siemens: manual de TIA Openness, 2019](https://cache.industry.siemens.com/dl/files/802/109773802/att_1007204/v1/TIAPortalOpenness_en-US.pdf): creación de objetos tecnológicos y lectura/escritura de parámetros. La firma de creación se contrastó por reflexión de la DLL V18 instalada, sin conectar ni modificar proyectos.
- [Siemens: parámetros de entrada de PID_Compact](https://docs.tia.siemens.cloud/r/es-es/v20/pid_compact-s7-1200-s7-1500/pid_compact-a-partir-de-v2-s7-1200-s7-1500/parametros-de-entrada-de-pid_compact-a-partir-de-v2-s7-1200-s7-1500?contentId=BrhhCE0VbTiCIsq1dlfZLQ) y [variables estáticas](https://docs.tia.siemens.cloud/r/en-us/v20/pid_compact-s7-1200-s7-1500/pid_compact-as-of-v2-s7-1200-s7-1500/static-tags-of-pid_compact-as-of-v2-s7-1200-s7-1500): referencia de interfaces. Son documentación V20; nombres, modos y versiones se validarán contra el objeto V18 real antes de programarlos. No se presupone compatibilidad de los campos nuevos V3 con V2.3.

## Revisión del documento

La configuración usa canales realmente presentes y libres, contempla el actuador elegido, distingue supuestos de hardware confirmado, separa simulación y planta, define ejecución periódica y preservación de la sintonización, y establece evidencia de compilación y control. No contiene una implementación ni declara que el PID esté listo. La revisión del diseño precede al plan detallado de implementación.
