# 23 IOAllocator: canal físico vs. rol funcional

## Propósito

Ampliación **aditiva** de la arquitectura existente que separa definitivamente el **canal físico**
(dirección real del banco, fija) del **rol funcional** (el nombre que un programa le da). Antes de
esta tarea, el único mecanismo para cambiar un nombre funcional era editar el mapa a mano en el
gestor de mapas (`Agregar/Editar/Eliminar variable`), sin ningún control de "esto es seguridad
crítica, no lo toques sin confirmar" — de hecho, durante el desarrollo de esta misma tarea eso
ocurrió de verdad: `I_Emergency`/`I_Reset`/`Q_Alarm` fueron renombrados manualmente a
`I_Pulsante1`/`I_Pulsante2`/`Q_Motor_2` en `mapa_banco_fisico.json`, rompiendo D01-D20. Se restauró
con confirmación del usuario y quedó como el caso de prueba real de por qué este mecanismo hace
falta.

## Estado FREE / ASSIGNED / LOCKED

Nuevo campo `state` por variable del mapa (`src/io_allocator.py`):

- **FREE**: sin función asignada; el allocator puede tomarlo automáticamente para una nueva
  petición por rol.
- **ASSIGNED**: tiene una función, reutilizable tal cual; solo se reasigna con confirmación humana
  explícita (nunca en silencio).
- **LOCKED**: nunca se renombra ni reasigna automáticamente, ni por voz/texto, ni por otro
  perfil/programa. Solo un `[Desbloquear variable]` manual en la GUI lo cambia. **LOCKED no impide
  usar la variable en lógica** — solo impide cambiar su nombre (sección 17).

`data/plc_maps/mapa_banco_fisico.json` quedó con `I_Start`, `I_Stop` e `I_Emergency` en `LOCKED`
(fundamentales/seguridad crítica) y el resto de los nombres D01-D20 en `ASSIGNED`; los 8 canales
analógicos (`AI_IW0/2/4/6`, `AO_QW0/2/4/6`) quedaron en `FREE` (sin sensor/actuador confirmado).

## Dónde vive el campo `state`

`state` es un campo "avanzado" más, igual que `unit`/`min`/`max`/`comments` — se añadió a las
**tres** listas blancas que ya existían para esos campos y que de otro modo lo habrían descartado
silenciosamente en cada guardado/edición: `utils._ADVANCED_VARIABLE_FIELDS`,
`gui_helpers.ADVANCED_VARIABLE_DEFAULTS` y `plc_maps.schema.ADVANCED_VARIABLE_FIELDS`. El diálogo
`Editar variable` de la GUI **no** incluye un campo editable para `state` a propósito: solo se
muestra (de solo lectura) para que editar otro campo (p. ej. la descripción) nunca reinicie/pierda
un `LOCKED` existente en silencio - el único camino para cambiarlo son los botones dedicados.

## IOAllocator (`src/io_allocator.py`)

Capa determinística, sin LLM: `propose_assignment(io_map, requests) -> [proposals]`. Nunca muta el
mapa - solo el llamador, tras confirmación humana, aplica con `apply_assignments(...)`. Prioridad
(sección 18):

1. Reutilizar una variable que **ya tiene exactamente ese nombre** (sin cambio).
2. Reclamar un canal **FREE** compatible (misma dirección I/Q, mismo digital/analógico).
3. Si no hay FREE, proponer reasignar un canal **ASSIGNED** compatible (`conflict=True`, requiere
   confirmación explícita, nunca aplicado en silencio).
4. **Nunca** toca un canal LOCKED - si no queda nada más, la propuesta vuelve `blocked=True`.

Cuando el comando da una dirección explícita ("Usa Q8.1..."), `validate_assignment_request()`
comprueba que la dirección exista físicamente, que la clase (input/output) coincida con el prefijo
solicitado (I_/AI_ vs Q_/AO_) y que digital/analógico sea compatible - "Usa I16.0 como salida del
motor" se rechaza porque I16.0 es una entrada.

## El LLM nunca elige una dirección

`extract_io_assignment_requests(command_text)` es la **única** fuente de `requested_io_assignments`
- un escaneo por expresiones regulares (`usa|configura|asigna` + dirección + `para|como` + rol), sin
LLM. Si el comando no menciona ninguno de esos verbos, no se detecta nada y el comando sigue el
camino normal de lógica PLC. Todo lo que el parser/LLM aporta es un **texto crudo** (`"Q8.1"`,
`"el motor 2"`); la normalización de dirección (`normalize_address`), la existencia física, la
compatibilidad y la prioridad FREE/ASSIGNED/LOCKED se calculan **enteramente en Python**, en
`io_allocator.propose_assignment()`, invocado desde `semantic_validator.validate_semantic_output()`
- nunca se confía en que el LLM haga esa aritmética. El propio `operation_type` (`PROGRAM` vs
`MAP_CONFIG`) se recalcula ahí mismo a partir de si hay `requested_io_assignments`, ignorando
cualquier valor que el LLM haya puesto.

## Normalización de direcciones

`normalize_address()` acepta `Q8.1`, `%Q8.1`, `salida 8.1`, `I16.2`, `entrada 16.2`, `IW0`, `%IW0`
y los reduce a la forma interna canónica del proyecto: `%QX8.1`, `%IX16.2`, `%IW0` (el sufijo `X`
es una convención interna de este proyecto para bits, que `SiemensSCLAdapter.to_siemens_address()`
ya recortaba a la sintaxis Siemens real `%Q8.1`/`%I16.2` al exportar - ver
`docs/22_banco_fisico_direcciones.md`). Cualquier texto no reconocido devuelve `None` - nunca un
intento de adivinar.

## semantic_output: `operation_type` / `requested_io_assignments`

`schemas.SemanticOutput` (Pydantic) y `schemas/semantic_output.schema.json` ganaron dos campos
opcionales (default `"PROGRAM"` / `[]`, compatibles con todo el historial de comandos existente).
`semantic_validation.io_assignment_proposals` (nuevo campo en `SemanticValidationResult`) lleva las
propuestas ya resueltas y validadas. Efecto colateral corregido de paso: `recognized_tags` en el
schema JSON era un `enum` cerrado (había que añadir cada tag nuevo a mano, como se hizo para
`Q_Pump_Enable` en la tarea PID) - **incompatible** con nombres dinámicos creados por MAP_CONFIG
(`Q_Motor_2`, etc.). Se cambió a un `pattern` abierto (mismo regex que ya validaba
`PLC_TAG_PATTERN` en el modelo Pydantic); `PLC_TAG_PATTERN` en sí se amplió de paso para aceptar
`AI_`/`AO_` (bug latente desde la tarea anterior: nunca se había actualizado ahí).

## Política de confirmaciones (minimizar preguntas)

`propose_assignment()` marca cada propuesta con `requires_confirmation`, calculado así:

| Estado del canal | Efecto | `requires_confirmation` |
|---|---|---|
| FREE | se asigna solo | `False` |
| ASSIGNED al mismo nombre ya solicitado | se reutiliza tal cual | `False` |
| ASSIGNED a un nombre distinto | se propone reasignar | `True` |
| LOCKED | se rechaza (nunca se pregunta - no hay nada que confirmar) | `False` (va en `blocked`) |

`gui.py::_handle_map_config_command` separa las propuestas de un mismo comando en tres grupos:
`auto_apply` (se aplican directo, sin preguntar), `needs_confirmation` (**una sola** ventana
`[Cancelar] [Aplicar cambios]` agrupando TODAS las reasignaciones de canales ya asignados del
comando - nunca una ventana por variable) y `blocked` (se rechazan individualmente y se informan
en el resumen final, **sin** impedir que el resto del comando se aplique). Recursos internos
`M_/T_/C_/R_/F_` nunca pasan por aquí - los sigue autogenerando `ir_builder` sin preguntar, como
siempre. Al final se muestra **un único** mensaje compacto con las direcciones efectivamente
aplicadas (y, si aplica, cuáles quedaron rechazadas por estar protegidas) - nunca dos ventanas
seguidas, incluso cuando el comando era puramente de configuración.

## Ejemplo: comando de solo configuración

```
"Configura Q8.0 como motor 1."
```
→ `operation_type: "MAP_CONFIG"`, `requested_io_assignments: [{"address":"%QX8.0", "functional_name_hint":"Q_Motor_1", ...}]`
→ propuesta: `%QX8.0: Q_Free1 (FREE) -> Q_Motor_1`, `requires_confirmation=False`
→ se aplica directo (sin preguntar) → `Q_Free1` pasa a `name=Q_Motor_1`, `state=ASSIGNED`
→ resumen compacto: "Asignaciones aplicadas: %QX8.0 -> Q_Motor_1 (...no se generó ningún programa)"
→ **no se genera ningún programa PLC** (sección 15).

## Ejemplo: comando combinado

```
"Usa I16.0 como Start, I16.1 como Stop, Q8.0 para motor 1 y Q8.1 para motor 2; cuando arranque
el motor 2 apaga el motor 1."
```
`extract_io_assignment_requests` encuentra las cuatro menciones con dirección (la cláusula final
no tiene ninguna, así que nunca se confunde con una asignación). Contra el mapa de ejemplo
(`I_Start`/`I_Stop` ya LOCKED con esos mismos nombres, `Q8.0`/`Q8.1` FREE): `%IX16.0`/`%IX16.1` se
resuelven como "ya es ese nombre" (sin cambio, sin preguntar), `%QX8.0`/`%QX8.1` son FREE (se
aplican directo). Si en cambio `Q8.1` ya tuviera otro rol asignado, esa única reasignación se
agruparía en la misma ventana de confirmación que cualquier otra reasignación del mismo comando -
nunca una ventana por variable. `process_command()` (`gui.py::_handle_map_config_command`) aplica
todo lo que corresponda en un solo `apply_assignments()`, **recarga el mapa desde disco** y
**revalida el mismo `semantic_output`** contra el mapa ya actualizado (`validate_semantic_output`,
sin volver a interpretar el texto) - si el intent ya no es `INT_UNKNOWN`, el flujo normal continúa
exactamente como cualquier otro comando (IR → SCL → TIA, con su propia confirmación humana ya
existente antes de generar).

## Modo Experimentación: working map por ensayo

El ensayo usa **el mismo inventario físico y el mismo IOAllocator** que Modo Normal, pero nunca
escribe el mapa activo. `trial_experiments/trial_io_map.py`:

1. `start_trial` → `create_working_map`: el **mapa base** es el mapa activo normalizado (LOCKED se
   conserva; ASSIGNED/FREE vuelven a FREE con su nombre genérico `I_Free16_6`/`Q_Free8_3`/`AI_IW0`/
   `AO_QW0` y sin aliases; internas no LOCKED se descartan). Se escribe en
   `results/experiments/<case>/<variant>/<trial_id>/working_io_map.json`.
2. `PREPARING`: el pipeline (`process_command` → `_handle_map_config_command`) asigna FREE,
   reasigna ASSIGNED, reutiliza LOCKED compatibles y acepta direcciones explícitas con
   `propose_assignment`/`apply_assignments` sin cambios, sobre el working map
   (`apply_proposals_to_working_map`: candidato → validación → escritura atómica; si falla, el
   archivo queda intacto). No se aplica el filtro legacy `allowed_variables` del perfil.
3. Antes de IR/SCL: `freeze_working_map` → `io_map_snapshot.json` (24 canales, bindings activos,
   `parameter_bindings` rol → nombre → dirección) y `lifecycle_state = IO_RESOLVED`. Desde ahí
   cualquier mutación falla con `EXPERIMENT_IO_FROZEN`.
4. Al finalizar (o cancelar) el ensayo, `working_io_map.json` se descarta; el snapshot queda como
   evidencia y `trial.json.io_map` lo referencia.

Errores: `EXPERIMENT_IO_BASE_UNAVAILABLE`, `EXPERIMENT_IO_ALLOCATION_FAILED`, `EXPERIMENT_IO_FROZEN`,
`EXPERIMENT_IO_SNAPSHOT_FAILED`. Un fallo de I/O cierra el ensayo (FAIL / INFRASTRUCTURE_ERROR) sin
compilar ni descargar.

`io_allocator.block_map_config_message(active_trial, active_profile_id)` se conserva **solo** para la
edición MANUAL del mapa durante un ensayo (`IOMapWindow` en solo lectura) y para el caso legacy de
Modo Normal con un perfil Dxx/Pxx seleccionado. Ya no bloquea al allocator del ensayo.

## GUI

Columna `state` añadida al treeview del mapa maestro (gratis, vía `IO_TREE_COLUMNS`). Tres botones
nuevos junto a los ya existentes: `[Bloquear variable]`, `[Desbloquear variable]`,
`[Marcar como libre]` (este último rechaza marcar libre una variable `LOCKED` - hay que desbloquear
primero). No se rediseñó el resto de la GUI.

## Historial y undo

`plc_maps.store.save_plc_map()` ganó un parámetro opcional `history_entries` que se **añaden** (no
reemplazan) a un array `history` de nivel superior en el JSON del mapa, con
`timestamp/address/old_name/new_name/old_state/new_state/source`, capado a 500 entradas. Solo las
aplicaciones del IOAllocator (MAP_CONFIG confirmado) generan estas entradas - la edición manual de
variables en la tabla (`Agregar/Editar/Eliminar`) no se instrumentó con historial en esta tarea
(fuera de alcance, ver limitaciones). `io_allocator.undo_last_map_change(io_map, history)` revierte
el último cambio (nombre y estado, nunca la dirección) - implementado y probado a nivel de función,
**sin** botón dedicado en la GUI todavía (mejora futura, como permite explícitamente la sección 27).

## Qué NO cambia

D01-D20, P01-P12, el pipeline `semantic_output → IR → SCL → TIA`, la confirmación humana ya
existente antes de generar/importar, y el comportamiento de cualquier comando que no mencione
`usa/configura/asigna` — todos siguen exactamente igual (207/207 tests, incluyendo los 164 previos
a esta tarea).

## Corrección: el renombrado no se propagaba con frases naturales

**Causa raíz encontrada** (diagnóstico pedido antes de implementar): `_slugify_role()` usaba
`re.match` (ancla al INICIO del texto) para detectar "motor N", y no quitaba verbos de relleno.
`"Usa la salida Q8.1 para controlar el motor 2."` producía `role_text = "controlar el motor 2"` -
como el texto NO empieza con "motor", el patrón nunca coincidía y el nombre caía al genérico
`Q_Controlar_El_Motor_2` en vez de `Q_Motor_2`. El resto del pipeline (aplicar, guardar, releer,
GUI, IR, SCL) **ya funcionaba correctamente** - el problema era exclusivamente la generación del
nombre propuesto. Corregido: `_FILLER_VERB_PREFIX` quita verbos como "controlar/accionar/manejar/
activar/..." antes de evaluar sinónimos, y la detección de "motor N" usa `re.search` (no anclada).
También se ampliaron los sinónimos de piloto (`"piloto de marcha"` -> `Pilot_Run`, igual
convención que D01-D20/PID) y se corrigió el orden de coincidencia para que frases largas
("piloto de paro") no las capture antes una corta genérica ("paro").

Dos gaps reales adicionales, encontrados y corregidos en la misma revisión:
- **Alias para comandos futuros**: `apply_assignments()` ahora guarda la frase de rol (normalizada,
  sin verbos de relleno) en el campo `aliases` de la variable renombrada. Sin esto, un comando
  POSTERIOR en modo `rule_based`/`hybrid` ("enciende el motor 2") no tenía forma de resolver
  "motor 2" -> `Q_Motor_2`, porque `alias_resolver.build_alias_index()` solo indexa por `aliases`
  y por nombre exacto - nunca por texto libre.
- **Nombres duplicados**: `propose_assignment()` ahora detecta si el nombre propuesto ya está en
  uso en OTRA dirección (y lo rechaza como `blocked`, salvo que esa otra dirección se esté
  liberando en el mismo lote - permite un intercambio de roles en un solo comando). Antes nada
  impedía terminar con dos direcciones activas para el mismo nombre funcional.

## Ventana "Mapa I/O completo"

`gui.py::FullIOMapWindow` (`CTkToplevel`), abierta con el botón `[ABRIR MAPA I/O COMPLETO]`
(panel izquierdo). Muestra **todas** las variables del mapa activo - no solo las que caben en la
tabla pequeña - con columnas Dirección/Nombre funcional/Tipo/Clase/Estado/Descripción; la
dirección nunca es editable ahí. Un canal `FREE` muestra `—` en Nombre (nunca el nombre interno
tipo `Q_Free1`/`AI_IW0` que sigue existiendo en el JSON solo para indexado - ver limitaciones).
Acciones `[Editar nombre]`/`[Bloquear]`/`[Desbloquear]`/`[Marcar libre]`: cada una valida con
`io_allocator` y **persiste de inmediato** (`apply_assignments`/`set_variable_state` +
`save_plc_map`) en vez de quedar solo en memoria esperando un guardado posterior - así se evita
exactamente el problema reportado. Tras cada acción se refresca la propia ventana (conservando la
fila seleccionada) y el panel izquierdo de la ventana principal (`io_variables`,
`io_variable_metadata`, treeview). `[Guardar]`/`[Guardar como...]` reutilizan
`app.save_io_map()`/`app.save_plc_map_as()` sin duplicar esa lógica. Durante un ensayo
experimental activo o con un perfil Dxx/Pxx seleccionado, la ventana se abre en modo solo lectura
(los cuatro botones de edición quedan deshabilitados) mostrando el mensaje de
`block_map_config_message()`.

## Dos niveles de validación: no confundir "no existe el tag" con "no tiene sentido"

Bug real reportado por el usuario tras probar la GUI: el comando *"Quiero encender mi proceso con
un pulsante de inicio... para encender el motor 1 o el motor 2..."* (sin direcciones explícitas)
devolvía `INT_UNKNOWN` + `requires_clarification=true`, pidiendo qué tag físico usar para "motor
1"/"motor 2". Causa raíz: `prompts/llm_semantic_parser_prompt.txt` prohibía "inventar variables" y
`llm_context_builder.py` solo exponía los nombres ACTUALES del mapa como una lista plana (sin
`state`) - el LLM no tenía forma de saber que un tag `ASSIGNED` es reasignable, así que trató el
mapa como una whitelist rígida de nombres y, al no encontrar coincidencia exacta, cayó
(correctamente, según sus propias instrucciones) en pedir aclaración.

Corrección en tres capas:
1. **`llm_context_builder.py`**: cada tag del contexto ahora incluye `state`, más un bloque
   `io_allocation_policy` explicando FREE/ASSIGNED/LOCKED y que el LLM puede proponer un nombre
   funcional nuevo (nunca una dirección) para una función física que el mapa aún no tiene.
2. **`prompts/llm_semantic_parser_prompt.txt`**: se reescribió la sección de "solo puedes"/"no
   puedes" - ya NO prohíbe proponer nombres funcionales nuevos (solo prohíbe proponer
   direcciones), se explica quue elegir el canal NUNCA es una ambigüedad a preguntar, y se agregó
   un ejemplo completo con el comando exacto reportado.
3. **`semantic_validator.py`**: `validate_semantic_output()` ahora separa dos niveles - un tag no
   autorizado pero bien formado (`AI_`/`AO_`/`I_`/`Q_` + identificador IEC válido) se intenta
   resolver vía `propose_assignment()` (mismo IOAllocator, sin dirección explícita) ANTES de
   rechazarlo; solo si el allocator tampoco puede resolverlo (todo LOCKED/incompatible/insuficiente)
   es un error real - y ese error es del allocator ("recursos insuficientes"), nunca una pregunta
   de "qué tag usar". `gui.py::process_command()` dispara el mismo flujo de aplicación
   (`_handle_map_config_command`) tanto para asignaciones explícitas como para estas implícitas,
   detectando la presencia de `io_assignment_proposals` en vez de depender solo de
   `operation_type`.

**Verificado con una llamada real al LLM** (no simulada) contra el comando exacto reportado: elige
`INT_MUTUAL_INTERLOCK`, reutiliza `I_Start`/`I_Stop` (LOCKED), propone `I_Start_Motor_1`/
`I_Start_Motor_2` para los dos pulsantes nuevos, `requires_clarification=False`, cero tags no
autorizados. La fidelidad exacta de la lógica de enclavamiento generada por `INT_MUTUAL_INTERLOCK`
frente a la descripción textual completa del usuario ("si se enciende uno se apaga el otro y
viceversa") sigue siendo una cuestión de calidad de interpretación del LLM/plantilla, no de
selección de tags - ver limitaciones.

### Hallazgo de seguridad corregido de paso: `DEFAULT_STATE`

Al implementar la resolución automática se encontró que `config/io_map.json`,
`mapa_simulacion_completo.json` y `mapa_pid_simulacion.json` (D01-D20/PID) **no tienen** campo
`state` en ninguna variable (se crearon antes de que existiera FREE/ASSIGNED/LOCKED). Con el
`DEFAULT_STATE` original (`ASSIGNED`), CUALQUIER tag nuevo bien formado que el LLM propusiera
podría haber reasignado automáticamente `I_Emergency` o cualquier otro tag crítico de esos mapas -
un riesgo real para "no romper D01-D20". Corregido cambiando `DEFAULT_STATE` a `LOCKED`: una
variable sin `state` explícito ahora se trata como protegida por defecto; solo un mapa que declara
`state` explícitamente (como `mapa_banco_fisico.json`) participa del allocator automático.

## Limitaciones conocidas

- La edición manual de variables (botones `Agregar/Editar/Eliminar` ya existentes) no registra
  entradas de historial - solo lo hace la aplicación de una propuesta del IOAllocator.
- No hay botón de `[Deshacer último cambio de mapa]` en la GUI todavía; la función
  `undo_last_map_change` existe y está probada, lista para conectarse.
- `extract_io_assignment_requests` reconoce los patrones explícitamente pedidos
  (`usa/configura/asigna` + dirección + `para/como` + rol, con "y"/"e" como conector entre varias
  asignaciones); no intenta cubrir cualquier frase posible en español - un comando de configuración
  fuera de ese patrón simplemente no se detecta como MAP_CONFIG y sigue el camino normal (nunca se
  interpreta mal como lógica con una dirección inventada).
- Un canal `FREE` sigue teniendo un nombre interno real en el JSON (p. ej. `Q_Free1`, `AI_IW0`) -
  es necesario porque todo el pipeline indexa variables por `name` (`build_io_map_index`,
  autorización de tags, etc.); "sin nombre" habría exigido rediseñar esa indexación, fuera del
  alcance de esta tarea. La ventana "Mapa I/O completo" lo oculta mostrando `—`, que es lo único
  que el usuario ve - el nombre interno nunca se expone en comandos, IR ni SCL mientras el canal
  siga FREE.
- `alias_resolver` es lo que permite que un nombre recién asignado se reconozca en un comando
  posterior en modo reglas/híbrido; el modo LLM puro no depende de esto (ve el mapa actualizado
  directamente en su contexto), pero tampoco lo usa como refuerzo - un alias mal capturado por
  `_normalize_role_phrase` no rompe nada, simplemente no ayuda a esa resolución futura.

## Autonomía en Modo Normal: cero confirmaciones (revisión de política)

Cambio deliberado respecto a la primera versión de esta ventana: reasignar un canal `ASSIGNED` a
un rol distinto **ya no pide confirmación** en Modo Normal. Como MAP_CONFIG solo corre en Modo
Normal (Experimentación lo bloquea antes de llegar aquí - `block_map_config_message`), esto
equivale a "cero confirmaciones siempre que MAP_CONFIG se ejecute". `conflict`/
`requires_confirmation` se siguen calculando en `propose_assignment` (útiles para tests y para
distinguir "conservado" de "reasignado" en el resumen), pero `gui.py::_handle_map_config_command`
ya no los usa para abrir un `askyesno` - aplica todo lo no bloqueado y muestra un resumen
`CONFIGURACION AUTOMATICA` con secciones **Conservados**/**Reasignados**/**Rechazados (protegidos)**
después del hecho.

### Bug real corregido: colisión de dirección dentro de un mismo lote

`propose_assignment()` resolvía cada petición por rol contra el MISMO `io_map` estático, sin saber
qué había reclamado una petición anterior del mismo lote - `["Q_Motor_1", "Q_Motor_2"]` sin
dirección explícita podían terminar ambas propuestas sobre el mismo canal FREE. Corregido con un
conjunto `claimed_in_batch` que excluye, en cada petición sucesiva, las direcciones ya usadas por
peticiones anteriores del mismo comando (`tests/test_io_allocator_autonomy.py`).

### Determinismo (sección 37)

Entre varios canales FREE/ASSIGNED compatibles, `_compatible_free_or_assigned()` ahora elige
siempre la **dirección física más baja** (`_address_sort_key`), nunca el primero que aparezca en
el orden del JSON - el mismo mapa inicial + el mismo comando producen siempre la misma asignación.

### Prioridad exacta (sección 7)

1. Dirección explícita del usuario (honrada tal cual, incluso si implica reasignar un `ASSIGNED`).
2/3. Nombre exacto ya existente (`LOCKED` o `ASSIGNED`, sin distinción - se reutiliza sin cambio).
4. Canal `FREE` compatible (dirección más baja).
5. Canal `ASSIGNED` compatible, reasignado automáticamente (dirección más baja) si no hay `FREE`.
6. Recursos internos `M_/T_/C_/R_/F_`: fuera del alcance de IOAllocator - los autogenera
   `ir_builder` como siempre, sin autorización.
7. Nada disponible → propuesta `blocked=True` con motivo explícito (nunca una pregunta).

### Patrón implícito "N motores con pulsante independiente" (sección 42)

`extract_implicit_multi_resource_requests()` es un *fallback* determinista y deliberadamente
acotado - reconoce **solo** la combinación "(dos|tres|.../número) motor(es)" + una mención de
"pulsante ... independiente" en el mismo comando, cuando `extract_io_assignment_requests` (ruta de
dirección explícita) no encontró nada. Genera N pares de peticiones por rol
(`I_Start`/`Q_Motor_1` para el primero, `I_Start_Motor_N`/`Q_Motor_N` para los siguientes), que
pasan por el MISMO `propose_assignment()` ya probado. No es NLU general: cualquier otra redacción
simplemente no genera nada aquí y el comando sigue el camino normal - nunca se inventa una petición
que el texto no sugiere con claridad.

**Límite honesto**: esto resuelve la parte de *asignación de mapa* del escenario totalmente
implícito (sección 42/46) de forma determinista y probada. La parte de *lógica* (que el intent/
parámetros generados representen correctamente "el motor 2 apaga al motor 1") sigue dependiendo de
que el LLM/parser interprete bien el comando compuesto una vez el mapa ya tiene los nombres - no se
tocó el prompt del LLM en esta tarea (cambiarlo para que proponga nombres nuevos activamente es un
cambio de mayor riesgo, con impacto en TODOS los comandos existentes, y se dejó fuera de esta
entrega). Para el resultado garantizado sin preguntas, la vía más robusta hoy sigue siendo dar
direcciones explícitas (sección 41, totalmente soportado) o dejar que el patrón implícito resuelva
el mapa y revisar el programa generado.

### I_Emergency ya no se exige si el banco no lo tiene físicamente (sección 4)

`semantic_validator._requires_emergency()` ahora recibe `io_index` y devuelve `False`
inmediatamente si `"I_Emergency"` no está en el mapa activo - antes exigía esa entrada para
`INT_MOTOR_START_STOP`/`INT_MOTOR_LATCH`/etc. sin importar si existía físicamente, lo que habría
bloqueado **todo** comando de ese tipo en un banco sin paro de emergencia cableado al PLC. Si el
mapa SÍ tiene `I_Emergency` (banco D01-D20), el comportamiento no cambia - verificado con test
dedicado. Esto no crea ni inventa `I_Emergency`: solo dejar de exigir una entrada que nunca existió.

### Trazabilidad de origen (sección 35)

`io_allocator.py` define las cuatro fuentes exactas pedidas:
`SOURCE_AUTO_ALLOCATOR`/`SOURCE_VOICE_EXPLICIT`/`SOURCE_TEXT_EXPLICIT`/`SOURCE_MANUAL_EDITOR`.
Cada propuesta de `propose_assignment()` lleva `address_was_explicit` (si el usuario dio la
dirección) para que `apply_assignments()` registre `AUTO_ALLOCATOR` cuando el allocator decidió el
canal por su cuenta, incluso dentro de un lote que mezcla direcciones explícitas e implícitas.
**Pendiente**: no existe todavía una señal limpia para distinguir voz de texto en `process_command`
- por ahora todo lo que no es manual se registra como `TEXT_EXPLICIT` incluso si vino de voz.
