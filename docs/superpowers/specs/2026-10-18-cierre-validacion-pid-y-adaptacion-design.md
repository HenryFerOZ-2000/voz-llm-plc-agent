# Cierre de validación, puesta en marcha PID y adaptación de mapas

Fecha: 18 de octubre de 2026, America/Guayaquil.

Estado: diseño aprobado por Henry el 18 de octubre de 2026 mediante «hazlo»,
después de revisar su resumen. Plan aprobado y ejecución en curso en la rama
aislada `feat/project-closure-20261018`; resultados y límites en `docs/30_cierre_validacion_pid_y_adaptacion.md`.

## Encargo y resultado esperado

Henry autoriza realizar los puntos 1–4 del cierre del proyecto: comprobar las 36
variantes P01–P12 con el producto actual, incorporar evaluación experimental del
PID nativo, completar su puesta en marcha desde la aplicación y comprobar
adaptación a otro mapa sin deteriorar las funciones existentes.

El resultado será software y evidencia DEVELOPMENT reproducible en PLCSIM
Advanced. No incluye congelar la versión final, iniciar FORMAL, grabar la campaña
de voz ni descargar al PLC físico. Tampoco certifica cualquier planta o CPU.

Se mantiene el objetivo del producto: el usuario describe el comportamiento; los
dispositivos y sus características proceden del mapa. El destino de descarga no
cambia la lógica de control. Un modelo externo aporta medición y responde al
actuador; no reemplaza el algoritmo PID que ejecuta la CPU.

## Situación comprobada y protección

- Normal y los ensayos nuevos comparten `PRODUCT_SHARED_V1` y preservan los
  dispositivos declarados mediante `PRODUCT_DECLARED_V1`.
- Los 36 ensayos TEXT históricos de P01–P12 están completos: 24 PASS, 10 FAIL y
  2 REVIEW. Sus resultados pertenecen a la versión anterior y no se sobrescriben.
- P01–P12 comprueban supervisión, consignas, modos y fallos mediante variables
  del DB; no son doce ensayos de sintonización de PID_Compact.
- PID_Compact regula el modelo de tanque en PLCSIM. La conservación de ajustes
  del mismo lazo fue comprobada tras guardarlos inicialmente desde TIA.
- El evaluador diferido rechaza todavía la evaluación nativa mediante
  `NATIVE_PID_EXPERIMENT_EVALUATION_UNSUPPORTED`.
- La GUI ofrece marcha, manual, ajuste y diagnóstico; la sesión de escritura
  está limitada a PLCSIM. No existe aún un recorrido integrado de guardado de
  parámetros online en el proyecto.
- Hay numerosos cambios previos y archivos nuevos en la carpeta principal.
  No se restablecen archivos ni se modifica el índice Git para crear un punto
  de partida artificialmente limpio.

Respaldo preparado y verificado:
`runtime/backups/pre_project_closure_20261018_192454_572756/backup_report.json`.
Contiene 573 archivos de producto/configuración y 3284 archivos de resultados y
audio, con comprobación CRC, contenido SHA-256 y ausencia de cambios durante la
copia. Incluye copia del índice Git y los dos archivos TIA previamente verificados
de la última prueba de persistencia. Esos archivos TIA no son un archivo nuevo del
proyecto abierto: antes de modificarlo se realizará Archive y se verificará.
No se copian secretos `.env`, todos los worktrees ni todos los paquetes generados.

## Alternativas y elección propuesta

1. Reutilizar el motor, el evaluador aislado, el proveedor de tanque y el puente
   actuales, añadiendo contratos y operaciones explícitas. Es la opción propuesta:
   aprovecha lo probado y mantiene una única interpretación del producto.
2. Crear scripts independientes para demostrar PID. Sería más corto, pero dejaría
   sin cerrar la GUI y la evaluación integrada. Los scripts solo se usarán como
   clientes de verificación de las mismas operaciones del producto.
3. Rediseñar el motor e incorporar soporte genérico de plantas y PLC físicos.
   Amplía demasiado el alcance y mezcla hardware aún no comprobado con el cierre
   de validación. Se difiere esa ampliación.

## 1. Auditoría P01–P12 con el motor actual

Se ejecutarán primero 36 generaciones DEVELOPMENT, P01–P12 × V1/V2/V3, con el
texto canónico exacto y la política de aclaración sin respuesta de los lotes.
Se utilizará la clave API existente cuya reutilización ya autorizó Henry.
Las peticiones contendrán comandos y contexto habitual del intérprete: mapa,
catálogo, reglas y conocimiento recuperado; nunca resultados esperados del Oracle.

Cada generación conservará comando, respuesta original, semántica efectiva,
asignación IO, mapa congelado, fuente, contrato e identidad del producto, modelo,
tiempos y resultado por etapa. Se clasificará el paquete real como supervisor o
nativo; el identificador Pxx no decide esa clasificación ni fuerza un intent.

Los casos evaluables continuarán por el recorrido oficial de Experimentación:
Retrieve del MASTER, importación en copia propia, compilación, archivo verificado,
descarga exclusivamente a la instancia PLCSIM declarada y ejecución del Oracle.
Una aclaración auténtica es un resultado de interpretación, no se contesta para
obtener PASS en el lote. Los fallos funcionales se conservan. Las correcciones se
verifican en una nueva ronda DEVELOPMENT identificada, nunca reescribiendo la
primera. Solo un fallo de infraestructura permite reintento técnico documentado.

Se investigarán los fallos reproducibles sin adaptar comandos ni exponer el
Oracle al LLM. Cambiar la especificación de un caso no forma parte de este cierre.

## 2. Evaluación experimental de PID nativo

Se reutilizará el recorrido de copia aislada del MASTER y su autorización de
descarga después de verificar el archivo de evidencia. No se llamará al recorrido
de importación Normal desde el evaluador experimental ni se modificará
`S71500_Prueba` para evaluar un ensayo.

El paquete congelado deberá ser autosuficiente para importar su infraestructura:
fuente SCL, variables, mapa, metadatos, manifiesto PID, bindings del proceso y XML
del OB cíclico. El perfil de planta y el protocolo de aceptación se congelarán
también; la evaluación no leerá silenciosamente un perfil vivo diferente.
Se versionará este contrato preservando la lectura de los contratos existentes;
no se crearán manifiestos retrospectivos para ensayos históricos.

La ampliación del puente compartirá la construcción y verificación de PID_Compact
que utiliza Normal, pero operará dentro de la copia experimental. Verificará CPU,
versión tecnológica, OB, período, bloques propios, identidad de fuente/configuración
y correspondencia con el destino antes de permitir ejecución.

La evaluación dinámica tendrá un protocolo DEVELOPMENT explícito adicional al
benchmark P01–P12. No se sustituirá un Oracle supervisor por una prueba de
convergencia para adjudicarle PASS. Si un Pxx produce un paquete nativo, solo podrá
recibir veredicto del benchmark cuando se hayan resuelto y comprobado todos sus
bindings y requisitos originales; de otro modo se conservará el motivo concreto
de no evaluabilidad y la evidencia dinámica se informará por separado.

Alcance inicial del protocolo nativo: un lazo de nivel, unidad %, válvula de
llenado, modelo de tanque identificado y PID_Compact compatible con la plataforma
comprobada. No habrá ajuste autónomo de un proceso físico desconocido.

El protocolo comprobará:

- identidad real del programa descargado y CPU RUN;
- medición y mando a través de las señales del mapa;
- respuesta manual y transición de presintonización observada;
- consignas 50/40/60 %, dentro de ±2 puntos durante 10 s antes de 300 s por consigna;
- fallos y paradas solicitados por el programa; lo no declarado se registra como
  no aplicable, sin inventar actuadores, alarmas o requisitos;
- ausencia de rearme/arranque indebido donde lo exige el comando;
- parada, liberación y restauración verificadas incluso al cancelar o fallar.

El veredicto separará generación, compilación, descarga, respuesta funcional,
paradas y limpieza. Una traza de software simulada o una etapa no ejecutada no
acredita ejecución nativa. La falta de limpieza es un fallo explícito.

## 3. Puesta en marcha y persistencia desde la GUI

Se ampliará el panel existente, evitando otro generador o una selección de
«simulación/físico» que cambie el programa. Mostrará sensor, actuador, unidad,
consigna, PV, CV, estado Siemens, fallos y estado de verificación de parámetros.

El flujo distinguirá lazo sin ajustes verificados, ajustando, pendiente de guardar,
guardado/verificado e incompatible. El estado guardado dependerá de comprobaciones
reales, no de pulsar un botón ni de un archivo local aislado.

Se añadirá una operación explícita «Guardar parámetros verificados en TIA»:

1. Leer del controlador correcto Kp/Ti/Td y estado, con identidad verificada.
2. Comprobar valores finitos, ausencia de ajuste en curso y correspondencia con
   sensor, actuador, escalas y configuración del lazo.
3. Archivar y verificar el proyecto antes de modificar sus parámetros offline.
4. Utilizar la API Openness disponible en V18 para escribir y releer los parámetros
   del objeto tecnológico propio, siguiendo los mecanismos ya utilizados por el
   puente. Confirmar guardado y registrar antes/después. No presentar como «subida
   online» una escritura offline sin lectura y comprobación de origen.
5. Si el proyecto tiene cambios pendientes del usuario o no se puede demostrar
   propiedad/correspondencia, detener la operación con un motivo; no guardar ni
   sustituir cambios ajenos silenciosamente.
6. Verificar regeneración, compilación y nueva descarga a PLCSIM conservando el
   mismo ajuste, y repetir regulación sin iniciar otra sintonización.

La disponibilidad exacta de los parámetros del objeto instalado se comprobará en
una copia antes de integrar la operación. Si V18 rechaza un acceso necesario,
se conservará el flujo TIA como limitación explícita; no se simulará un guardado.

La sintonización seguirá siendo una acción explícita autorizada por el operador.
No se inicia al abrir la ventana, generar un programa o cambiar una consigna.
Los ajustes solo se reutilizarán cuando coincida la configuración verificada;
no se transferirán ciegamente a otra planta o mapa.

Las operaciones largas se ejecutarán fuera del hilo de la GUI, con progreso,
cancelación, bloqueo de acciones incompatibles y resultado persistido. Se conserva
la restricción de escritura a PLCSIM; este encargo no habilita el PLC físico.

## 4. Adaptación de mapas y regresiones

Se trabajará exclusivamente con copias identificadas de mapas:

- mapa S7-1500 actual para conservar el comportamiento existente;
- un mapa alternativo con otros nombres y direcciones digitales y analógicas
  compatibles y sin solapamientos;
- representación DB de ingeniería para medición/mando cuando esté declarada y
  soportada por el contrato, sin inventar una planta al faltar canales;
- mapa digital con sensor(es) discretos y electroválvula para comprobar que no
  se introduce PID ni una salida analógica sin que lo requiera el comando.

Los ensayos combinarán marcha/parada, llenado por límite, histéresis y regulación
PID. No todas las combinaciones son compatibles: el resultado correcto de una
petición incompatible será una explicación o aclaración, no código fabricado.
Se comprobarán además recursos ausentes, dispositivos ambiguos, escalas inválidas,
solapamientos, unidades incompatibles y ajustes de otro lazo.

Cambiar de direcciones conservará la lógica solicitada y cambiará los bindings
verificados, sin valores físicos codificados en el generador. Esto prueba
adaptación de mapas en el S7-1500 virtual, no compatibilidad física con S7-1200.

Se ejecutarán pruebas focalizadas de cada cambio y las regresiones de motor,
discreto, supervisión, analógicas, GUI, persistencia e integridad experimental.
La suite completa se ejecutará sobre la implementación final. Se distinguirán
pruebas unitarias, llamadas LLM reales, compilaciones TIA y ejecuciones PLCSIM.

## Criterios de entrega y orden

1. Respaldo verificado y entorno de trabajo aislado que incluya los cambios
   actuales, sin restablecer el índice principal.
2. Ronda inicial de 36 variantes y diagnóstico con evidencia por etapa.
3. Implementación y pruebas del evaluador nativo y del guardado desde la GUI.
4. Nueva ronda DEVELOPMENT después de correcciones y matriz de adaptación.
5. Revisión final, evidencia, documentación y comprobación de integridad de los
   archivos protegidos. No basta con que el código nuevo tenga pruebas unitarias.

La entrega registrará qué puntos se completaron y cuáles quedaron bloqueados por
infraestructura. No se afirmará aprobación de las 36 variantes por existir
generación o compilación únicamente. Los resultados funcionales negativos se
conservarán y explicarán.

Se preparará una guía breve para Henry: seleccionar proyecto/mapa, generar,
descargar a PLCSIM, poner en marcha, ajustar cuando corresponda, guardar y reutilizar.
La evidencia tendrá inventarios de dispositivos representados, modelos, mapas,
protocolos y versiones para la redacción de la tesis.

## Fuera de alcance

- Modificar los resultados, audios o Oracles históricos para obtener PASS.
- Crear un nuevo congelamiento o ejecutar TEXT/VOICE FORMAL.
- Certificar hardware real, calibración física, seguridad funcional o toda planta.
- Iniciar una sintonización o movimiento físico sin puesta en marcha específica.
- Rediseñar todo el producto o incorporar soporte de fabricantes distintos.
- Cambiar la conexión Normal que ya funcionaba por una preferencia del entorno de
  pruebas. Los ajustes temporales quedarán en el entorno aislado y registrados.

## Revisión del diseño

Se contrastó el diseño con el evaluador diferido, su contrato de producto, el
protocolo nativo existente, el panel de puesta en marcha y la evidencia de
persistencia. Mantiene separados supervisión y regulación, preserva la protección
del MASTER y del proyecto Normal, y define comprobaciones verificables sin
prometer que cualquier planta se controla únicamente a partir de direcciones IO.

La comprobación previa ejecutó 95 pruebas existentes de motor compartido,
contratos experimentales, puesta en marcha, aceptación y empaquetado PID,
proyecto Normal y comandos naturales: 95 aprobadas. La primera ejecución obtuvo
93 aprobadas y dos errores de inicialización Tcl dentro del aislamiento. Una
ventana Tkinter mínima reprodujo el problema y funcionó fuera del aislamiento;
la repetición completa en ese entorno aprobó las 95. Hubo una advertencia de
permisos de la caché pytest. Evidencia: `runtime/project_closure_baseline.xml`.
Estas pruebas no son las 36 llamadas LLM ni nuevas compilaciones/ejecuciones TIA.

Henry aprobó el diseño y después el plan de implementación con ejecución
directa. La preparación descrita arriba se conserva como evidencia histórica.
El avance y las limitaciones actuales están en
`docs/30_cierre_validacion_pid_y_adaptacion.md`; la entrega sigue en una rama
aislada hasta completar la verificación e integración.
