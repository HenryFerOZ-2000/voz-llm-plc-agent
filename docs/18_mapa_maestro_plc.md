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

## CRUD de variables (sin cambios de flujo)

**Agregar variable**, **Editar variable** y **Eliminar variable** siguen funcionando igual que antes sobre la tabla visible (6 columnas: nombre, clase, tipo, direccion, valor inicial, descripcion). Los campos avanzados (aliases, rol semantico, permitido para LLM, nivel de seguridad, unidad, minimo, maximo, comentarios) se editan en el mismo dialogo de variable, en una seccion "Avanzado", y se guardan en un diccionario sombra en memoria que se fusiona con la tabla al guardar el mapa.

## Validacion del mapa

Boton **Validar mapa** (`src/plc_maps/map_validator.py`): reutiliza las reglas existentes (`gui_helpers.validate_io_map_variables`) y agrega direcciones fisicas duplicadas, `safety_level` invalido, variables criticas sin `safety_level=critical`, rangos `min`/`max` incoherentes. Un mapa con errores no puede sincronizarse con TIA.

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
