# PID basado en el mapa IO, independiente del entorno de ejecución

Fecha: 2026-10-16. Estado: diseño escrito para revisión; todavía sin cambios en el generador.

## Objetivo aprobado en la conversación

El investigador escribe la orden del proceso y selecciona su mapa IO. No tiene que indicar «simulación» o «físico», ni dentro del comando ni mediante un selector específico del PID. El software resuelve los dispositivos y genera el controlador con sus conexiones, escalas, límites y prioridades. Ese controlador debe poder ejecutarse en PLCSIM Advanced o en la CPU compatible de la plantilla TIA, utilizando las señales que describe el mapa.

El destino configurado determina la conexión y descarga. No determina la fuente de la medición ni autoriza a fabricar una planta: PLCSIM también puede recibir señales de otro simulador y una CPU real puede trabajar con variables de proceso en DB. Una prueba con modelo de tanque es una operación separada del control.

La aprobación del usuario «hazlo entonces» corresponde a este cambio de funcionamiento. Esta especificación sustituye, para la nueva generación nativa, las decisiones de `SIMULATION/PHYSICAL` del diseño anterior. Los paquetes y evidencias anteriores se conservan identificados con su contrato original.

## Estado de partida y respaldo

- Última entrega nativa: rama `feat/native-pid-map`, código `7ae5658`, documentación `2713d19`.
- Evidencia anterior: 1.739 pruebas de software aprobadas y corrida nativa `run_d4eca94e8299` aprobada en sus siete etapas. El modelo de tanque anterior estaba dentro del programa y sus resultados no prueban este diseño nuevo.
- Incidente real: con «Según comando», el LLM produjo `pid_control.mode=PHYSICAL` y pidió confirmar la calibración de `AI_Level_Raw`. El mapa tenía rangos supuestos, no confirmados.
- Respaldo nuevo: `runtime/backups/pre_pid_io_unificado_20261016_143014`, ZIP y bundle Git verificados; 12.555 archivos y 524.787.362 bytes de origen. Restauración comprobada en `.pytest_tmp/rU`: todos los SHA256 y el estado Git previo coinciden; índice original conservado.
- Copia aislada: `runtime/worktrees/pid-io-map-driven`, rama `feat/pid-io-map-driven`. Mantener el índice y los cambios previos de la carpeta habitual.
- Comprobación de base de esa copia: 66 pruebas de resolución, generación, puesta en marcha y paquetes aprobadas. Un fallo inicial de preparación de la carpeta temporal se corrigió sin cambiar código.

## Decisión de arquitectura

Se mantiene un controlador único y se mueve el modelo de planta a la infraestructura de prueba.

Alternativas descartadas:

1. Inferir `SIMULATION/PHYSICAL` desde el destino: no distingue un PLCSIM conectado a otro modelo ni una CPU con señales de DB; seguiría cambiando el programa por el entorno.
2. Conservar dos programas y ocultar el selector: elimina un control de la interfaz, pero mantiene dos comportamientos y una decisión implícita.

La opción elegida permite comparar exactamente la fuente SCL y el OB de un mismo comando/mapa entre destinos. Cambiar el modelo de prueba o la conexión no cambia el controlador ni su huella. Cambiar dispositivos, escalas o lógica sí la cambia.

Esto no convierte el generador en universal: se conserva el alcance comprobado de un lazo de nivel, acción FILL/DRAIN, actuador proporcional, PID_Compact 2.3 y OB de 100 ms, sujeto a compatibilidad de CPU/firmware. No se agregan control de temperatura, cascada, varios lazos o nuevas combinaciones funcionales.

## Contrato del comando

`pid_control` contiene consigna, unidad, acción del actuador, identificación opcional de sensor/actuador y recursos pedidos (Start, Stop, Reset, emergencia, permisos e indicaciones). No contiene un modo de simulación/planta.

La selección de recursos procede del mapa y sus permisos. Un único dispositivo compatible se resuelve automáticamente; varios candidatos indistinguibles requieren aclarar el proceso o dispositivo. No se codifican IW4/QW4 ni nombres del banco en la lógica. La consigna y el límite de sobrellenado se expresan en la unidad del requisito y se convierten una sola vez a la del sensor; no se interpretan valores eléctricos/raw como unidades de proceso.

El LLM no decide el entorno, no confirma calibraciones y no activa el modelo de prueba. El normalizador determinista excluye los campos antiguos `pid_control.mode` y `parameters.pid_mode` de la nueva IR y conserva su procedencia en la traza cuando una respuesta antigua los incluya. La presencia de esas palabras no altera los canales del mapa ni sustituye sensores por variables internas. Los ensayos congelados del supervisor PID y el perfil experimental histórico mantienen su contrato.

Una configuración incompleta se informa con el dato faltante y el dispositivo correspondiente. Una respuesta «sí» a una aclaración del LLM no modifica `analog_config.confirmed`.

## Contrato de señales del mapa

Cada conexión de proceso normalizada identifica nombre, función, magnitud, unidad, rango, representación, procedencia y permisos. El mapa distingue dos representaciones explícitas:

### Canal analógico de hardware

Se conserva el contrato actual `class=input/output`, `type=INT`, `location=%IWn/%QWn` y `analog_config` para señal eléctrica, rangos raw/ingeniería, dispositivo y acción ante fallo. No se cambia el esquema de las digitales ni se marcan calibraciones como confirmadas automáticamente.

Para el banco actual, el controlador lee IW4, escala la lectura a nivel, calcula el mando y escribe QW4 tras su conversión a raw. Ese mismo recorrido se conserva cuando la CPU es PLCSIM. Las salidas no quedan sustituidas por cero por un supuesto modo de simulación.

### Señal de proceso en DB

Se agrega una clase editable «Señal de proceso en DB» con valor REAL y metadatos `process_config`, sin dirección de hardware inventada. Sus propiedades son:

- `schema_version=1` y `role=MEASUREMENT` o `MANIPULATED`.
- `quantity`, `engineering_unit`, `engineering_min`, `engineering_max`.
- `storage.kind=GENERATED_DB`, `storage.db` y `storage.member`, identificadores Siemens válidos.
- Una medición declara `validity_member` BOOL, inicialmente falso, que actualiza su proveedor de datos.
- Un mando declara `fault_value` dentro del rango; en este primer alcance la salida proporcional se expresa en 0–100 %.

La entrada del mapa conserva su nombre/alias funcional y permiso. Los metadatos describen su almacenamiento, no le conceden al intérprete acceso arbitrario a otros DB. El generador crea únicamente los DB declarados de su propiedad; rechaza coincidencias con DB ajenos, miembros incompatibles y escritores duplicados. Se agrupan los miembros de un DB sin sobrescribir los de otro propietario.

En una conexión REAL de ingeniería no se aplica conversión eléctrica/raw. Se comprueban finitud, límites y calidad. El estado de validez evita interpretar un cero inicial sin proveedor como una medición comprobada.

Si faltan entradas/salidas analógicas y tampoco hay señales de DB declaradas, se informa el recurso faltante. No se crea una planta oculta. El editor permite preparar una vez el mapa de señales virtuales; la generación posterior usa ese mapa sin otro selector de entorno. Si hay candidatos físicos y de DB simultáneamente, se aplican las mismas reglas de resolución/ambigüedad, sin preferencia por el destino.

## Controlador generado

La nueva IR contiene conexiones de entrada/salida normalizadas y configuración del controlador; no contiene `mode`, `SimLevel`, tasas de llenado/vaciado ni un modelo de planta.

Orden del ciclo: leer y convertir entrada → validar medición/consigna/permisivos → actualizar marcha/fallo → llamar una vez al PID → aplicar prioridades y límites finales → convertir/escribir salida → publicar diagnóstico.

Se conservan las propiedades verificadas: OB real de interrupción de 100 ms, inicio por flanco cuando lo pide el comando, Stop/emergencia prioritarios, fallo enclavado, rearme sin rearranque, rechazo Auto/Manual contradictorio y único escritor de cada salida. `FaultCode` y `ErrorBits` conservan el diagnóstico hasta el rearme. Los recursos digitales pedidos se actualizan con su lógica normal en ambos destinos; no se agregan habilitación o alarma por convenio.

El controlador nuevo arranca sin parámetros demo y sin habilitación automática no confirmada. Mantiene operación manual inicialmente en cero y solicitudes explícitas de ajuste. La presintonización entra directamente desde manual mediante el grupo de escritura ya corregido; los selectores físicos mantienen su prioridad. La terminación nativa válida confirma los parámetros según el contrato existente. Un objeto compatible con parámetros offline verificados los conserva; el cambio de contrato no reutiliza sin revisión una instancia antigua identificada como demo.

Los valores aprendidos online siguen requiriendo sincronización con TIA antes de otra descarga. La automatización de esa carga no forma parte de esta revisión y debe permanecer visible en las instrucciones.

## Calibración y etapas de autorización

Separar tres resultados: configuración estructuralmente completa, compilación válida y dispositivo físicamente confirmado. Los rangos completos marcados `ASSUMED_FOR_TEST` permiten generar/compilar y probar en PLCSIM, conservando esa procedencia. No se convierten a calibración física confirmada.

La descarga mediante la aplicación a un destino físico exige confirmar los canales analógicos y sus rangos en el editor y verificar compatibilidad de plantilla/CPU. PLCSIM permite ensayar los rangos declarados sin certificar hardware. Esta comprobación pertenece al servicio de descarga y a sus diagnósticos, no a un modo del algoritmo ni a una pregunta improvisada del LLM.

La lógica de control no contiene una detección de PLCSIM ni un permiso que cambie silenciosamente la fuente de PV. La generación o apertura del panel no inicia marcha, ajuste ni modelo. La prueba de hardware y la descarga física no forman parte de la implementación de desarrollo actual; requieren la puesta en marcha del banco.

## Modelo de prueba independiente

Se incorpora un perfil de tanque identificado y editable en la infraestructura de prueba, separado del paquete del controlador. Usa las mismas ecuaciones de demostración: nivel inicial al 20 % del rango, llenado máximo de 2 % del rango por segundo y vaciado de 0,8 % por segundo. No representa una planta identificada. Las propiedades y la versión del perfil quedan en la evidencia del ensayo.

El modelo recibe el mando realmente escrito por el controlador, calcula la respuesta y proporciona la medición por la conexión declarada:

- Hardware: leer la palabra QW indicada; convertirla a apertura; escribir la palabra IW correspondiente al nivel. El controlador vuelve a escalar esa palabra. No escribir el área de salidas desde el modelo.
- DB: leer el mando REAL declarado; escribir la medición REAL y su calidad. No escribir `PV`, `CV`, estados o ganancias privados del controlador para fabricar resultados.

La operación «Probar con modelo de tanque» queda separada en el panel de puesta en marcha. Inicia un trabajo de prueba en segundo plano con cancelación y plazo definido; no es una selección de modo del PID. También puede utilizarse el controlador con un modelo externo sin activar el de la aplicación.

La infraestructura runtime propia de esta entrega se limita a PLCSIM Advanced. En una CPU real con señales de DB, un proveedor externo/HMI o modelo PLC separado debe alimentarlas; esta revisión no afirma tener un transporte de escritura física validado.

Se usa un único proceso de prueba con muestreo nominal de 100 ms; no se lanza un ejecutable nuevo por cada paso del modelo. Se registra tiempo real, jitter, muestras perdidas, valores raw, nivel, mando, calidad, estado y errores. Los parámetros del perfil se convierten a las unidades del mapa y el paso de integración queda explícito. La nueva respuesta puede diferir de la anterior por cuantización y temporización; se mantienen los criterios de aceptación y se conservan ambos resultados.

## Acceso tipado de prueba y límites

La DLL instalada de PLCSIM Advanced API 5.0 expone, comprobado por reflexión sin conectar ni escribir: `IIOArea.ReadBytes(UInt32, UInt32)` y `WriteBytes(UInt32, Byte[])`, además de acceso simbólico INT16/REAL en `IInstance`. Esto demuestra disponibilidad de firmas; no demuestra todavía una escritura de IW correcta en ejecución.

Antes de activar el modelo, comprobar realmente una palabra de entrada con 0, 13824 y 27648, leyendo por dirección y por símbolo. Determinar y registrar el orden de bytes con esa prueba, sin presuponerlo. Restaurar la entrada original. Un error de firma/orden/lectura bloquea el modelo y se informa; no se sustituye por una planta dentro del controlador.

Toda escritura de prueba exige instancia PLCSIM identificada, CPU RUN, paquete compilado verificado y huella del programa cargado. Solo se admite la entrada INT o miembro de DB de medición/calidad declarado para ese ensayo. Se rechazan destinos físicos, salidas Q, áreas M arbitrarias, diagnósticos, parámetros PID y símbolos ajenos. No debilitar los guardas BOOL/REAL existentes.

Guardar las entradas originales y restaurarlas al cerrar/cancelar tras ordenar Stop con la identidad vigente. Si cambia el programa cargado, suspender escrituras y registrar la interrupción; no declarar un cierre correcto ni escribir con un descriptor antiguo. Los errores/timeout y limpieza fallida se conservan en una carpeta única por intento.

Para el fallo de sensor se utiliza un raw representable fuera del rango declarado o una calidad explícita del mapa. Si ninguna opción existe, informar que esa inyección no está disponible en ese perfil; no fabricar un PASS.

## Compatibilidad y trazabilidad

El paquete nuevo usa un manifiesto nativo versión 2 con conexiones de mapa y sin modo/modelo. Incluye descriptores de acceso/propiedad de los DB generados y estado de calibración. La huella del controlador depende de lógica, dispositivos, escalas y versión de sus componentes; no depende del modelo ni del destino de descarga.

Los paquetes v1 se reconocen como históricos y conservan las restricciones originales, incluida la prohibición de descargar un antiguo paquete SIMULATION a un PLC físico. No se convierten en paquetes unificados por quitar una clave JSON. Se conserva la evidencia v1 y no se reescriben freezes, Oracles o resultados experimentales anteriores.

Los programas digitales y `INT_PID_SUPERVISOR` siguen sus rutas actuales. Quitar el selector afecta solo al entorno del PID nativo, no a Manual/Automático del proceso, parser, plataforma, conexión o selección de mapa. La plantilla hardware se sigue preparando manualmente; no se cambian módulos, red o direcciones por suposición.

## Componentes afectados

- Resolución y validación: `pid_control`, `semantic_validator`, `llm_parser`, política Normal y construcción de contexto.
- Contratos/generación: IR, conexiones de proceso, escalamiento, `pid_scl`, adaptador Siemens y verificador.
- Mapa/editor: validación de `process_config`, tipo de señal DB y reutilización de selectores de unidad existentes.
- Paquetes/TIA: manifiesto v2, creación/propiedad de DB, compatibilidad, preservación de parámetros y validación de descarga.
- GUI/runtime: retirada del selector, panel de puesta en marcha, prueba separada, descriptores de acceso y puente PLCSIM.
- Evidencia: perfil/modelo de prueba y protocolo reproducible nuevo; documentación de versión y actualizaciones del freeze futuro.

No refactorizar componentes ajenos ni modificar automáticamente el mapa activo o la confirmación de los dos dispositivos preparados. Un mapa de prueba DB se crea como recurso separado y no cambia el puntero activo.

## Criterios de aceptación

1. Mismo comando y mapa generan SCL y OB idénticos con destino PLCSIM o físico configurado. No se solicita ni se infiere un modo PID. Una respuesta LLM antigua con `mode=PHYSICAL/SIMULATION` no cambia el resultado.
2. Con el mapa del banco, el SCL siempre lee IW4/escribe QW4 mediante su configuración, sin modelo embebido ni anulación de salidas por el entorno. Sensores/actuadores renombrados o reubicados se resuelven igual.
3. Con mapa DB, la IR conecta los miembros declarados, crea solo bloques propios, comprueba calidad y omite conversiones eléctricas. Faltantes, ambigüedades, conflictos y unidades incompatibles producen diagnósticos concretos.
4. `confirmed=false` permanece intacto tras interpretar/generar/ensayar. Compilación con rangos completos y procedencia de prueba queda distinguida de autorización de descarga física.
5. El puente rechaza escrituras no declaradas o de otro destino; pasa la comprobación real de palabra/readback antes de ensayar el tanque. Cambios de identidad, cancelación y errores restauran o registran un cierre fallido, nunca un éxito supuesto.
6. Compilar en TIA V18 una copia aislada de la plantilla existente, conservando original/MASTER. Verificar PID_Compact 2.3, una llamada en OB real de 100 ms, objetos propios y parámetros offline preservados en una reimportación compatible.
7. Ejecutar el modelo externo en PLCSIM con canales IW/QW y repetir con DB. Primero comprobar manual y presintonización nativa desde condiciones admisibles; luego Start, consignas 50/40/60 %, Stop, emergencia, fallo de sensor, límites, sobrellenado y recuperación sin rearranque. La convergencia mantiene ±2 puntos durante 10 s continuos antes de 300 s por cambio. Registrar si la sintonización termina o falla; no cambiar el modelo o los umbrales para ocultar un fallo.
8. Guardar fuentes/huellas, perfil del modelo, trazas raw/ingeniería, estados, error retenido, parámetros nativos y cierre. Cada intento queda separado; las pruebas offline no se presentan como ejecución Siemens.
9. Ejecutar regresiones del PID, GUI/mapas, escalamiento, programas digitales, supervisor histórico y freeze. Revisar el cambio completo antes de integrarlo, respetando los archivos del usuario y sin stage/stash/revert del índice original.

Las campañas formales de texto/voz/ruido y el banco físico siguen pendientes de su versión congelada correspondiente. Esta especificación no declara esas pruebas realizadas.

## Revisión del diseño

El contrato de señales define explícitamente de dónde vienen los valores; el modelo, el destino y la autorización de hardware son responsabilidades separadas. La eliminación de los dos programas anteriores no se resuelve ocultando el selector. Las pruebas de SDK y TIA están identificadas como requisitos pendientes y tienen un resultado observable. Se mantienen las limitaciones reales del primer lazo y las evidencias históricas.
