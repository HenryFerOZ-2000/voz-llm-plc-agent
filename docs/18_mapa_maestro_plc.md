# 18 Mapa Maestro PLC

## Que es

El Mapa Maestro PLC evoluciona el antiguo `config/io_map.json` (documentado en `04_paso2_mapa_io.md`) hacia una biblioteca de mapas versionados. Sigue siendo una **whitelist**: el parser, el IR, el generador y el verificador solo aceptan variables declaradas en el mapa activo. Lo nuevo es que ahora pueden existir varios mapas guardados (uno por banco de pruebas o proyecto), cada uno con metadata propia, y cada variable puede llevar informacion semantica adicional (aliases, rol semantico, permiso de uso por LLM, nivel de seguridad).

## PLCVariableMap vs PLCProjectIR

- **PLCVariableMap** (`src/plc_maps/`): que variables existen y estan autorizadas en el proyecto PLC. Es configuracion, cambia poco, se edita desde la GUI.
- **PLCProjectIR** (`src/plc_ir.py`): que logica debe implementar el programa solicitado por el usuario en un comando puntual. Se construye en cada ejecucion a partir del mapa activo (`ir_builder.build_project_ir`) y no se toco en esta evolucion.

Ambas responsabilidades se mantienen separadas: `PLCProjectIR` sigue leyendo variables desde el mapa activo via `build_io_map_index`, pero el mapa en si (su ciclo de vida, versionado, sincronizacion con TIA) vive enteramente en `src/plc_maps/`.

## Formato de archivo

Cada mapa es un JSON en `data/plc_maps/<id>.json`:

```json
{
  "schema_version": 1,
  "metadata": {
    "map_id": "...", "name": "...", "version": 1, "description": "...",
    "target_platform": "SIEMENS_SCL_V18",
    "created_at": "...", "updated_at": "...",
    "tia_project_path": "", "tia_plc_name": "",
    "sync_status": "unknown", "dirty": false
  },
  "naming_convention": { "...": "igual que antes" },
  "variables": [
    {
      "name": "I_Start", "class": "input", "type": "BOOL", "location": "%IX0.0",
      "initial_value": "FALSE", "description": "Pulsador de arranque.",
      "aliases": ["pulsador verde"], "semantic_role": "start_command",
      "llm_allowed": true, "safety_level": "normal",
      "unit": "", "min": null, "max": null, "comments": ""
    }
  ]
}
```

`data/plc_maps/` es estado local (como `generated_code/gui_history.json`) y **no se versiona en git** — cada clon del repositorio lo regenera automaticamente en el primer arranque a partir de `config/io_map.json`, que sigue siendo la semilla de solo lectura.

## Biblioteca y mapa activo

`data/plc_maps/_active_map.json` guarda el `map_id` del mapa activo. `src/gui.py` reasigna `self.io_map_path` a ese archivo al iniciar y cada vez que el usuario cambia de mapa; el resto del pipeline (`parse_command`, `build_project_ir`, `generate_project_package`) no necesita saber que existe una biblioteca, porque siempre recibe el `io_map` cargado desde `self.io_map_path`.

### Como crear un mapa

Boton **Nuevo mapa** en el panel "Mapa PLC activo": pide nombre y descripcion, crea un archivo vacio y lo activa.

### Como cargar / cambiar de mapa

El selector desplegable "Mapa PLC activo" lista todos los mapas guardados. Si hay cambios sin guardar en el mapa actual, se pide confirmacion antes de cambiar.

### Como guardar / guardar como otro mapa

**Guardar mapa I/O** persiste el mapa activo (conserva su metadata). **Guardar como...** crea un mapa nuevo a partir del contenido actual de la tabla, sin modificar el original.

### Como eliminar un mapa

Boton **Eliminar mapa**: no permite eliminar el ultimo mapa disponible y pide confirmacion.

## Crear y editar variables

Desde **Abrir mapa I/O completo**, use **Nueva variable**, incluso si el mapa esta vacio. Seleccione entrada o salida digital, entrada o salida analogica, memoria interna, temporizador, contador o detector de flanco. El formulario ofrece los tipos que soporta el generador actual: BOOL, INT, TON, TP, CTU, R_TRIG y F_TRIG. Las analogicas fisicas usan INT para el valor crudo del canal.

En **Variable** se definen nombre, tipo, direccion, valor inicial y descripcion. Puede escribir direcciones como `I16.0`, `Q8.0`, `IW0` o `QW0`; se guardan en el formato interno `%IX16.0`, `%QX8.0`, `%IW0` y `%QW0`. El prefijo del nombre depende de la clase (`I_`, `Q_`, `AI_`, `AO_`, etc.). Los bloques y memorias internas pueden existir sin direccion fisica. En **Avanzado** estan los alias, rol semantico, permiso LLM, seguridad, unidad, minimo, maximo y comentarios. Estos campos no configuran los modulos de TIA ni constituyen una configuracion completa de sensor o PID.

**Editar variable** o doble clic abre el formulario completo. **Duplicar** propone una copia sin direccion: hay que indicar un canal distinto para variables fisicas. **Eliminar** pide confirmacion. Las variables LOCKED deben desbloquearse antes de editarse o eliminarse. Las operaciones estan bloqueadas durante ensayos o perfiles experimentales.

Los cambios aceptados en la ventana completa se validan y guardan inmediatamente, conservan los campos adicionales del canal y actualizan el panel principal. Se rechazan nombres repetidos, direcciones duplicadas o solapadas, combinaciones incompatibles y valores numericos invalidos. Cancelar no modifica el archivo. Si el mapa cambio desde otra ventana, se exige actualizar la seleccion; si hay cambios pendientes en el panel principal, se deben guardar primero. Una modificacion invalida la compilacion anterior para exigir generar y compilar de nuevo antes de descargar.

Los botones **Agregar variable**, **Editar variable** y **Eliminar variable** del panel principal siguen trabajando sobre su tabla en memoria y requieren **Guardar mapa I/O**. Agregar y editar usan el mismo formulario guiado.

### Configuracion analogica por dispositivo

Al editar un canal INT en `%IW...` o `%QW...`, abra **Analogica** y active **Configurar senal y escalado de este canal**. Defina dispositivo, magnitud, senal electrica, rango electrico, rango raw del modulo, rango fisico y unidad fisica. Las opciones incluyen 0-10 V, -10 a 10 V, 0-20 mA, 4-20 mA y rangos personalizados de voltaje o corriente.

Seleccionar 4-20 mA rellena solo sus extremos electricos, 4 y 20. No determina los valores raw: estos deben verificarse en la plantilla TIA y la documentacion del modulo. La unidad fisica de `analog_config.engineering_unit` es independiente del campo general `unit` de los mapas anteriores (que puede contener V o mA).

Para una entrada, la respuesta configurable ante una senal invalida es inhibir el control o sustituir el valor de entrada. Para una salida, se configura un valor seguro en unidades fisicas. Los valores de sustitucion/seguridad deben pertenecer al rango fisico. Ningun valor cero ni accion por defecto se consideran confirmados automaticamente.

Los datos incompletos pueden guardarse como pendientes. **Confirmo senal y rangos con TIA y el dispositivo** requiere todos los campos y rangos validos. Modificar parametros, clase o direccion borra la confirmacion y exige verificarla otra vez. Desactivar la configuracion y aceptar elimina el bloque `analog_config` de esa variable. Una configuracion analogica activa no es valida en variables digitales o internas.

El bloque opcional `analog_config` usa `schema_version: 1`, `confirmed`, `device_name`, `quantity`, `signal_type`, `electrical_min/max`, `raw_min/max`, `engineering_min/max`, `engineering_unit`, `fault_action` y `fault_value`. Los valores raw deben ser enteros del tipo INT; los otros valores numericos deben ser finitos y los extremos deben estar ordenados. Los mapas sin este bloque siguen siendo compatibles. Los campos adicionales del bloque se conservan al editar y guardar.

El editor guarda y valida la configuración por canal. El generador utiliza los canales confirmados como se describe en «Escalamiento generado desde el mapa». `analog_configuration_report(...)["ready"]` significa metadata completa y confirmada, no una prueba del cableado. La configuración global existente en `config/pid_supervisor_config.json` mantiene su comportamiento; esta etapa no genera ni sintoniza un PID.

### Selectores de dispositivos, magnitudes y unidades

El formulario ofrece categorias de dispositivo compatibles con la direccion: sensor en entradas; valvula proporcional, variador u otro actuador en salidas; y otro dispositivo para casos particulares. El nombre/modelo sigue siendo editable. La categoria opcional se guarda como `analog_config.device_kind`; los mapas anteriores sin ella conservan su formato.

La magnitud fisica se elige de un catalogo: nivel, distancia, volumen, caudal, presion, temperatura, apertura, velocidad de giro, frecuencia, voltaje, corriente, masa, fuerza y potencia. El selector de unidad muestra las opciones de esa magnitud. **Personalizada...** permite introducir magnitudes y unidades adicionales. Unidades conocidas de otra magnitud se rechazan (por ejemplo, bar para nivel); una unidad personalizada no tiene conversion inferida.

Cambiar entre unidades equivalentes convierte el minimo fisico, el maximo fisico y el valor ante fallo, y retira la confirmacion. Por ejemplo, `0..200 cm` con valor seguro `20 cm` pasa a `0..2 m` y `0.2 m`. Las conversiones de temperatura incluyen el desplazamiento entre escalas. Los rangos raw y electricos permanecen iguales.

Si cambia la magnitud, si no existe una conversion directa (por ejemplo, porcentaje a centimetros de nivel), o si los numeros previos son invalidos, se vacian los limites fisicos y el valor ante fallo para introducir una nueva calibracion. El formulario indica lo ocurrido. No se infiere geometria del tanque, relacion entre rpm y Hz de un variador, ni factores de unidades no registradas.

Abrir y aceptar una configuracion existente conserva sus textos y campos adicionales: alias antiguos como `quantity: "Level"` se muestran como Nivel sin reescribir el valor guardado. El catalogo y las conversiones viven en `src/engineering_units.py`; esta ampliacion sigue preparando metadata, sin generar control PID ni operar la planta.

## Validacion del mapa

Boton **Validar mapa** (`src/plc_maps/map_validator.py`): reutiliza las reglas existentes (`gui_helpers.validate_io_map_variables`) y agrega direcciones fisicas duplicadas, `safety_level` invalido, variables criticas sin `safety_level=critical`, rangos `min`/`max` incoherentes. Un mapa con errores no puede sincronizarse con TIA.

### Escalamiento generado desde el mapa

Los canales físicos INT utilizados por un programa con `analog_config` deben tener una calibración completa y confirmada. El generador conserva el canal raw y crea auxiliares REAL/BOOL dentro del FB para el valor físico y su validez. Estos auxiliares no se agregan al mapa de dispositivos. Los canales no utilizados no bloquean la generación aunque su configuración esté pendiente.

La entrada se calcula como `(REAL(raw) - raw_min) / (raw_max - raw_min) * (engineering_max - engineering_min) + engineering_min`. Se convierte a REAL antes de restar para admitir rangos bipolares y todo el intervalo INT sin desbordamiento entero. El rango eléctrico documenta la calibración, pero no sustituye los extremos raw explícitos del módulo. No se presupone que 4 mA equivalga a 0 o a 5530 cuentas.

La histeresis sobre un canal configurado compara valores físicos. Su campo opcional `unit` permite convertir umbrales compatibles (por ejemplo 1,5 m a 150 cm); sin ese campo se interpreta la unidad física del mapa. En condiciones como `AI_Level > 150` el número usa la unidad física del canal. El campo `condition_unit` conserva una unidad explícita del comando y el generador convierte sus umbrales; `conditional_output` también admite `unit` como alias. En una orden `analog_output`, `unit` pertenece a su valor de salida y `condition_unit` a su condición. No se permite usar un canal analógico como BOOL ni compararlo contra un operando BOOL.

La primitiva `analog_output` representa una orden numérica: `{"type":"analog_output","output":"AO_Valve","value":50,"unit":"%","condition":"I_Run"}`. La condición es opcional; sin ella la orden es continua salvo emergencia. El generador valida el valor y la unidad, aplica la calibración inversa y convierte a INT. Sin habilitación o con emergencia utiliza el valor ante fallo del mapa. Una orden BOOL no reemplaza una orden analógica. Se rechazan múltiples escritores de la misma salida analógica.

Se normalizan los extremos a la precisión REAL del PLC, se rechazan rangos indistinguibles o no representables, y la salida raw se limita al intervalo confirmado antes de convertirla a INT. Un comando fuera del rango físico se rechaza durante la generación. Un valor de ejecución inválido utiliza el valor ante fallo; no se extrapola al actuador.

Una lectura fuera del intervalo raw nominal produce `Valid=FALSE`. Con `SUBSTITUTE_VALUE` se utiliza el valor físico de sustitución y se conserva el diagnóstico inválido. Con `INHIBIT_CONTROL` se fuerzan a FALSE todas las salidas BOOL de la POU y se aplican los valores ante fallo de sus salidas analógicas, en el mismo ciclo; también se deshabilita `PID_Enable` si existe. Esta política no es una parada de seguridad certificada ni enclava un rearme: la lógica interna continúa evaluándose y puede volver a habilitarse al recuperarse la señal. Los requisitos de parada/rearme deben definirse para el proceso.

Por compatibilidad, un canal antiguo sin `analog_config` conserva sus comparaciones raw. Solicitar unidades explícitas o una orden `analog_output` exige configuración confirmada. Para pasar un programa antiguo a unidades físicas hay que revisar sus umbrales; confirmar una calibración cambia la interpretación numérica de ese canal.

Esta etapa genera escalamiento y respuesta por rango nominal; no incorpora diagnóstico específico de módulo/cable roto, modelo dinámico de planta ni creación/llamada/sintonización de PID_Compact. Tampoco verifica que la plantilla TIA coincida con el mapa. La comprobación offline ejecuta el SCL generado; la compilación y prueba con el PLC siguen siendo verificaciones separadas.

Referencias de Siemens: [tratamiento de valores analógicos](https://docs.tia.siemens.cloud/r/fail_safe_modules_manual_collection_enus_20/device-specific-information/s7-1200-fail-safe-modules/s7-1200-g2-programmable-logic-controller/plc-concepts-configuration-and-programming/program-structure/processing-of-analog-values?contentId=1GNsv~EhwKEYrqn4755Qhw), [conversiones REAL para S7-1500](https://docs.tia.siemens.cloud/r/en-us/v20/data-types/data-type-conversion-for-s7-1500-s7-1500/explicit-conversions-s7-1500/floating-point-numbers-s7-1500/explicit-conversion-of-real-s7-1500).

## Validacion de comandos contra el mapa activo

El parser (reglas o LLM) sigue rechazando variables no autorizadas, ahora con dos niveles:

1. **No autorizada**: la variable no existe en el mapa activo (como antes).
2. **No permitida para LLM**: la variable existe pero tiene `llm_allowed=false` (`src/semantic_validator.py`). El LLM ademas nunca ve esas variables en su contexto (`src/llm_context_builder.py` las filtra antes de construir el prompt).

En ningun caso el sistema sustituye automaticamente una variable no autorizada por otra — el comando se rechaza con un mensaje explicito.

## Resolucion de alias

Cada variable puede declarar `aliases` (frases en lenguaje natural). `src/alias_resolver.py::build_alias_index` construye un indice `frase normalizada -> tag`, que se pasa opcionalmente a `semantic_parser.extract_tags`. Es aditivo: si no se provee `alias_index`, el parser se comporta exactamente igual que antes. Solo resuelve alias para las ~15 variables con un "slot" semantico ya conocido por el parser de reglas (`I_Start`, `I_Emergency`, etc.); no crea automaticamente nuevas intenciones para variables completamente nuevas.

## Sincronizacion con TIA Portal

Boton **Sincronizar con TIA**: valida el mapa localmente, arma la lista de tags de entrada/salida y llama al puente C# (`Program.cs`) con la accion `sync_map` (nueva, no reemplaza `import_compile`). A diferencia de `EnsureTags` (usado por la importacion/compilacion normal, que aborta ante cualquier conflicto), `sync_map` es conservadora: crea tags nuevos, reporta conflictos de tipo/direccion sin lanzar excepcion, y nunca borra tags que existan en TIA pero no en el mapa local — esos se listan en `extra_in_tia` para que el usuario decida.

## Importacion desde TIA Portal

Boton **Importar desde TIA**: llama a la accion `read_tags` del puente (tambien nueva), que enumera todas las tablas de tags del proyecto abierto. Al fusionar con el mapa local: las variables que ya existen conservan sus aliases/rol semantico/permisos/descripcion, solo se actualiza direccion/tipo/clase; las variables nuevas se agregan con `llm_allowed=false` (una variable nunca vista por un humano no se autoriza automaticamente para el LLM). Los cambios quedan en memoria; hay que usar "Guardar mapa I/O" para persistirlos.

## Limitaciones conocidas

- `read_tags` solo puede leer `PlcTagTable`/`PlcTag` (entradas, salidas y memorias declaradas como tags). Temporizadores, contadores y detectores de flanco son instancias de bloque de funcion dentro del programa, no aparecen en las tablas de tags, y por lo tanto no se pueden importar automaticamente.
- La sincronizacion y la importacion no se pudieron probar en vivo contra una sesion real de TIA Portal desde este entorno de desarrollo (si involucran escribir/leer tags en el proyecto `.ap18` del usuario). El codigo C# si se compilo exitosamente contra las DLL reales de Siemens instaladas en la maquina. Verificacion manual pendiente: ver `15_guia_de_configuracion.md`.
- `physical_download_allowed` sigue fijo en `false` en todas las operaciones, incluida `sync_map`.

## Archivos involucrados

- `src/plc_maps/schema.py`, `store.py`, `registry.py`, `migration.py`, `map_validator.py`, `tia_sync.py`
- `src/alias_resolver.py`
- `src/gui.py`, `src/gui_helpers.py` (extendidos, no reemplazados)
- `src/semantic_parser.py`, `src/semantic_validator.py`, `src/llm_parser.py`, `src/llm_context_builder.py` (integracion aditiva)
- `tia_openness_bridge/Program.cs` (acciones `sync_map` y `read_tags` nuevas; `diagnose`/`import_compile` intactas)
