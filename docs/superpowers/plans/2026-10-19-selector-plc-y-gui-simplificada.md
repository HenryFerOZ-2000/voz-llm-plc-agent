# Selector de PLC y GUI simplificada — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Ejecución por el agente principal en esta sesión y una revisión independiente final, conservando el método de trabajo ya utilizado.

**Goal:** Seleccionar el destino Normal desde la GUI y retirar controles duplicados, conservando «Ejecutar y cargar al PLC» y el comportamiento existente.

**Architecture:** Un modelo de destino separa configuración, descubrimiento y estado. La GUI usa proveedores existentes para PLCSIM y un puente V18 para interfaces y direccionamiento explícito; una dirección manual física no se presenta como equipo descubierto. La simplificación concentra las acciones del mapa en su ventana completa sin modificar el motor del producto.

**Tech Stack:** Python 3.13, CustomTkinter/Tk, pytest, C#/.NET Framework x64 mediante csc, TIA Openness V18 y PLCSIM Advanced 5. No se instalan nuevos SDK ni controladores.

**Spec:** `docs/superpowers/specs/2026-10-19-selector-plc-y-gui-simplificada-design.md`, corregida y aprobada el 19 de octubre de 2026. Plan aprobado por Henry el 19 de octubre de 2026 mediante «hazlo»; implementación y validación en curso.

## Global Constraints

- «Ejecutar y cargar al PLC» se conserva visible para realizar el proceso completo desde el comando hasta la descarga.
- Se retiran estos ocho botones del lateral: Abrir mapa I/O, Guardar mapa I/O, Agregar variable, Editar variable, Bloquear variable, Desbloquear variable, Eliminar variable y Marcar como libre.
- El motor de interpretación y generación no cambia. No hay nuevas llamadas LLM al abrir, buscar o aceptar un destino.
- Experimentación conserva MASTER, IO, resultados, Oracles y `download_targets.experiment`; nunca descarga a hardware.
- Las configuraciones históricas sin dirección explícita conservan su ruta actual. No se modifica automáticamente la red, CPU, módulos o protecciones.
- No se ofrecen búsqueda física automática en V18, RUN físico ni compatibilidad verificada sin evidencia. IO y puesta en marcha PID siguen limitados a sus capacidades actuales en PLCSIM.
- Trabajo en `runtime/worktrees/project-closure`, base funcional `529356f`, diseño corregido `3719808`; preservar el directorio ajeno sin seguimiento `ps/`.
- Respaldo `runtime/backups/before_plc_selector_20261019_105048`, estado VERIFIED. No fusionar, restablecer ni preparar archivos en el índice de la carpeta principal.

## Review Focus

1. Dos instancias con el mismo nombre o un ID reutilizado: no elegir silenciosamente otro PLC. Prueba en Task 3.
2. Cambio de destino con una compilación o respuesta de estado en vuelo: no publicar el estado antiguo ni descargar al equipo nuevo con autorización anterior. Pruebas en Tasks 1 y 4.
3. Dirección física en un archivo de configuración: debe llegar al DownloadProvider, sin confundirse con nombre descriptivo o puerto X1. Prueba en Task 2.
4. Cancelar el selector, fallo de escritura o configuración editada mientras está abierto: no perder campos ni publicar medio cambio. Prueba en Task 1.
5. Editar una fila en el mapa completo mientras el lateral conserva otra selección: editar el recurso de esa ventana y preservar bloqueos de ensayo. Prueba en Task 5.

## Estructura de archivos

| Archivo | Responsabilidad |
| --- | --- |
| `src/plc_targets.py` (nuevo) | Normalizar, identificar, guardar y describir destinos; contrato de capacidades |
| `src/plc_target_dialog.py` (nuevo) | Diálogo de selección, sin acceso directo a persistencia o descarga |
| `src/tia_openness.py` | Enumerar interfaces mediante puente y construir peticiones con endpoint |
| `tia_openness_bridge/ConnectionTargetSupport.cs` (nuevo) | Selección de interfaz y dirección V18; política verificable sin conexión física |
| `tia_openness_bridge/Program.cs` | Acción de interfaces y uso del direccionamiento en la descarga existente |
| `src/plcsim_runtime.py`, `plcsim_runtime_bridge/Program.cs` | Enumerar y consultar instancias por identidad explícita |
| `src/gui.py` | Coordinación de destino, controles principales y gestor completo de mapas |
| `docs/33_selector_plc_y_gui.md` (nuevo) | Uso, compatibilidad V18, límites y evidencia de validación |

Los nuevos módulos extraen esta responsabilidad; no se reorganiza todo `gui.py`.

### Task 1: Modelo y persistencia coherente del destino Normal

**Files:** Create `src/plc_targets.py`, `tests/test_plc_targets.py`; Modify `src/tia_openness.py:resolve_download_target`.

**Interfaces:** `normalize_target(candidate: dict) -> dict`, `target_identity(target: dict) -> str`, `load_normal_target(root: Path) -> dict`, `read_target_revision(root: Path) -> dict`, `save_normal_target(root: Path, target: dict, expected_revision: dict) -> dict`. La revisión contiene hashes de `config/tia_openness_config.json` y `config/tia_projects.json` si existe. El destino normalizado conserva campos históricos y admite `target_address`, `pc_interface_number`, `instance_name` e `instance_id` opcionales.

Test `test_target_identity_tracks_endpoint_not_caption`, con el destino válido `a` creado en el propio test:
```python
assert target_identity(a) == target_identity({**a, 'target_name': 'Otra etiqueta'})
assert target_identity(a) != target_identity({**a, 'target_address': '192.168.0.2'})
```

- [x] Escribir casos RED: configuración actual sin campos nuevos conserva su significado; IP inválida falla; nombre descriptivo no sustituye IP; cambiar nombre sin cambiar endpoint no crea otra identidad; cambiar interfaz, dirección, proyecto o instancia sí exige nueva comprobación. Probar revisión obsoleta y fallo de escritura sin modificar el archivo anterior.
- [x] Ejecutar `python -m pytest tests/test_plc_targets.py -q` y conservar el fallo esperado.
- [x] Implementar normalización y revisión; actualizar `download_targets.normal` y `plcsim_runtime` en una única escritura temporal y `os.replace`, preservando campos ajenos. No cambiar `download_targets.experiment` ni preferencias API. No publicar una instancia nueva sin dirección comprobable.
- [x] Ejecutar los casos anteriores y pruebas existentes de configuración/descarga. Resultado: mismos valores históricos y cero escrituras ante una revisión obsoleta.
- [x] Commit exclusivo de estos archivos en la copia de trabajo.

### Task 2: Interfaces y endpoint explícito en Openness V18

**Files:** Create `tia_openness_bridge/ConnectionTargetSupport.cs`, `tests/test_tia_connection_targets.py`, `tests/fixtures/ConnectionTargetPolicyProbe.cs`; Modify `tia_openness_bridge/Program.cs:ResolveDownloadTarget, PerformDownload`, `src/tia_openness.py:_bridge_paths, build_openness_bridge, prepare_download_request`.

**Interfaces:** `list_tia_connections(root: Path) -> dict` entrega `status`, `project_path`, `expected_cpus`, `connections` (modo, nombre/número PG/PC y puertos), `capabilities.physical_discovery=false`. `prepare_download_request` transmite `target_address` e interfaz numérica cuando existen. En `ConnectionTargetSupport`, `Dictionary<string,object> SelectInterface(IEnumerable<Dictionary<string,object>> candidates, Dictionary<string,object> request)` resuelve una única interfaz; `string ValidateAddress(Dictionary<string,object> request)` devuelve dirección canónica o `null` para ruta histórica. Las funciones C# usan diccionarios del patrón actual del puente.

Test `test_explicit_endpoint_reaches_download_request`: construir un paquete discreto temporal con el patrón de `test_pid_normal_project.py`, guardar el destino `192.168.0.2`, ejecutar `prepare_download_request` y comprobar:
```python
assert request['target_address'] == '192.168.0.2'
assert request['target_name'] == 'Banco secundario'
assert request['purpose'] == 'normal'
```

- [x] Escribir RED: dos interfaces homónimas con números distintos requieren número; ausencia de IP conserva la ruta anterior; IP explícita distinta del nombre llega intacta a la petición; IP inválida/ambigüedad aborta antes de descargar; Experimentación física se rechaza.
- [x] Ejecutar pytest y el probe C# contra la lógica de producción, sin buscar dispositivos ni escribir al PLC.
- [x] Añadir `list_connections`, abierta sobre el proyecto Normal exacto, sin guardar ni compilar. Incorporar el nuevo CS a las entradas de build. Separar datos de interfaces de equipos detectados.
- [x] Con dirección explícita, crear `ConfigurationAddress` en la interfaz resuelta y usar la sobrecarga V18 de `Download(configuration, address, pre, post, options)`. Sin dirección conservar la sobrecarga actual. Reportar interfaz, dirección solicitada y ruta aplicada; no cambiar IP del proyecto/Windows/PLC.
- [x] Ejecutar pruebas de política, build y self-tests existentes. La prueba en PLCSIM de Task 6 debe verificar esta ruta antes de habilitarla en la entrega.
- [x] Commit de la tarea.

### Task 3: Descubrimiento y lectura inequívoca de instancias PLCSIM

**Files:** Modify `plcsim_runtime_bridge/Program.cs`, `src/plcsim_runtime.py:get_runtime_config`; Create `tests/test_plc_instance_discovery.py` y fixture C# si requiere ejercitar la selección sin Runtime Manager.

**Interfaces:** `list_plcsim_instances(root: Path) -> dict` devuelve `status`, `instances` con `instance_id`, `instance_name`, dirección y estado solo cuando fueron leídos; más `errors`. `resolve_instance(instances: list[dict], target: dict) -> dict` en `src/plcsim_runtime.py` exige coincidencia inequívoca o lanza `ValueError`. `get_plcsim_runtime_status(project_root: Path | None = None, action: str = ACTION_RUNTIME_STATUS, *, target: dict | None = None) -> dict` conserva los parámetros actuales y admite la identidad elegida sin sustituir la configuración persistida para realizar una previsualización.

Test `test_duplicate_names_require_matching_identity`:
```python
instances = [{'instance_id': 1, 'instance_name': 'Banco'}, {'instance_id': 2, 'instance_name': 'Banco'}]
with pytest.raises(ValueError): resolve_instance(instances, {'instance_name': 'Banco'})
assert resolve_instance(instances, {'instance_id': 2, 'instance_name': 'Banco'})['instance_id'] == 2
with pytest.raises(ValueError): resolve_instance(instances, {'instance_id': 2, 'instance_name': 'Otro'})
```

- [x] RED para cero/una/varias instancias, nombres duplicados, coincidencia ID+nombre, ID reutilizado con otro nombre, instancia desaparecida y dirección no leíble. Afirmar que no se elige la primera ni se usa `TESIS_PLC_SIM` como reemplazo silencioso.
- [x] Ejecutar pytest/probe y observar RED antes de cambiar la selección.
- [x] Añadir acción de enumeración usando `RegisteredInstanceInfo` y lecturas del API existente. No crear, arrancar, detener ni descargar instancias. Mantener cliente de lectura y liberación conforme al patrón actual. Para configuraciones antiguas, conservar selección por nombre único; para nuevas, ID+nombre deben concordar.
- [x] Ejecutar pruebas nuevas y las existentes de Runtime/IO. Registrar desconocidos como desconocidos, sin datos de ejemplo.
- [x] Commit de la tarea.

### Task 4: Selector, estado y exclusión de operaciones en la GUI

**Files:** Create `src/plc_target_dialog.py`, `tests/test_gui_plc_targets.py`; Modify `src/gui.py:_build_plc_connection_panel, _start_runtime_refresh, _render_configured_target, _tia_busy, _start_download` y flujos de texto/voz encadenados.

**Interfaces:** `PlcTargetDialog(app, initial_target: dict, revision: dict)` publica `result: dict | None`; su búsqueda llama a los proveedores de Tasks 2–3 mediante trabajador y cola. `app.select_normal_plc_target()`, `app.refresh_selected_target_status()` y `app._target_operation_busy() -> bool` coordinan persistencia y estado. Cada respuesta lleva `target_identity`; la GUI descarta respuestas de un destino anterior o de un diálogo cerrado.

Tests `test_cancel_keeps_configuration_bytes` y `test_old_target_result_is_not_rendered`: la cancelación deja `result is None` y los bytes de configuración iguales; una respuesta del destino A recibida después de aceptar B conserva el identificador B y no publica el RUN de A. Usar los proveedores externos sustituidos por respuestas guardadas; no simular la política de selección que se está probando.

- [x] RED: cancelar no guarda; dos resultados no seleccionan automáticamente; un trabajador antiguo no cambia el estado del destino recién elegido; cerrar la ventana durante búsqueda no deja controles bloqueados; error de guardado conserva valores anteriores.
- [x] RED: no se acepta otro destino durante captura/flujo de voz, generación, compilación, descarga, sesión IO o PID. Cambio aceptado invalida disponibilidad/autorización anterior. IP física nunca produce un estado de PLCSIM ni un RUN deducido.
- [x] Implementar diálogo y panel con proyecto/CPU esperada, mapa, destino y alcance de comprobación. «Buscar» lista instancias virtuales; físico ofrece dirección manual y explica ausencia de búsqueda V18. Preferencias de TIA siguen accesibles. Las consultas no realizan descarga ni llaman al LLM.
- [x] Conectar el endpoint a petición y confirmación. Capturar identidad al iniciar un flujo y comprobarla antes de descargar. Verificación de un paquete existente puede revalidar/recompilar su SCL sin reinterpretación. Una plantilla distinta requiere compilación correspondiente.
- [x] Para físicos, mostrar configuración y diagnóstico realmente disponible; si no se lee identidad suficiente, mostrar compatibilidad no verificada y bloquear carga automática. Mantener confirmación física y validaciones TIA para carga manual. No habilitar IO/PID Runtime físicos.
- [x] Ejecutar pruebas de diálogo y `tests/test_normal_execute_and_load.py`, `tests/test_normal_voice_auto_flow.py`, `tests/test_gui_pid_lifecycle.py` y `tests/test_runtime_request_isolation.py`. Conservar configuración original al finalizar.
- [x] Commit de la tarea.

### Task 5: Retirar controles duplicados y conservar el recorrido completo

**Files:** Modify `src/gui.py:FullIOMapWindow, _build_left_panel, _build_center_panel, _apply_responsive_layout, _refresh_voice_button_states`; Create `tests/test_gui_simplified_controls.py`; adaptar solo expectativas visuales de pruebas existentes cuando cambie la ubicación.

**Interfaces:** `FullIOMapWindow` concentra edición y menús de biblioteca/TIA usando persistencia y validadores existentes. `app.open_preferences()` ofrece los controles API/parser existentes sin cambiar sus valores. «Herramientas avanzadas» conserva diagnóstico, mantenimiento, IO y herramientas manuales de voz. No se elimina ningún callback funcional para satisfacer una prueba de ausencia de texto.

Test `test_execute_and_load_remains_visible_in_normal_mode`, con la aplicación en Normal, y `test_full_map_edit_uses_its_own_selection` contra dos variables temporales con nombres distintos:
```python
assert app.execute_and_load_button.winfo_manager() != ''
assert saved_variables['Variable_A']['description'] == 'Sin cambios'
assert saved_variables['Variable_B']['description'] == 'Editada en mapa completo'
```
La segunda prueba ejecuta la edición real sobre B con A seleccionada en el lateral, antes de leer el archivo guardado.

- [x] RED de interacción: abrir mapa vacío y agregar una variable; editar una selección diferente de la lateral; bloquear/desbloquear/marcar libre; guardar como, nuevo, validar y abrir mapa importado; respetar restricciones de ensayo. Cada operación comprueba el recurso y archivo resultantes en directorios temporales.
- [x] RED de acceso: los ocho controles no aparecen en el lateral; su función está en el mapa completo; «Ejecutar y cargar» sigue visible y llama al flujo completo; generación o compilación fallida no descarga ni reutiliza un paquete anterior.
- [x] Concentrar gestor de mapas y retirar botones laterales. Sustituir plataforma única por etiqueta, mover preferencias API/parser, archivar/limpiar y micrófonos avanzados a sus ubicaciones aprobadas. Mantener resumen del modo activo. Preservar todos los estados, escalas y validadores.
- [x] Mantener visibles «Generar y compilar», «Ejecutar y cargar al PLC», «Cargar programa al PLC» y «Ejecutar por voz». Mostrar cancelación durante captura. Puesta en marcha PID contextual con acceso avanzado. Retirar solo el duplicado experimental «GENERAR SOLO»; conservar lotes, corpus, Oracles y evaluación.
- [x] Ajustar listas/referencias de widgets, habilitación, cambio de modo y diseño responsivo para que ninguna referencia al control retirado rompa el flujo. No cambiar significado de los callbacks ni el motor.
- [x] Ejecutar nuevas pruebas y grupos GUI/mapas/voz/PID/Experimentación. Comprobar geometría y ancho de textos con Tk a resolución actual y una menor. Se realizaron pruebas programáticas a 1920×1080 y 1600×900; la inspección visual independiente queda declarada como no realizada.
- [x] Commit de la tarea.

### Task 6: Verificación real, revisión e integración protegida

**Files:** Create `docs/33_selector_plc_y_gui.md`; pruebas auxiliares y evidencia en `runtime/plc_selector_validation/`, fuera de resultados experimentales. Actualizar estado del plan y del diseño con los hechos comprobados.

**Interfaces:** `runtime/plc_selector_validation/delivery.json` registra commits, hashes de archivos, respaldo, pruebas, capacidades disponibles y limitaciones; ninguna evidencia DEVELOPMENT cambia un veredicto histórico.

- [x] Capturar antes de integrar los hashes del código/configuración/mapas/resultados/Oracles e índice principal. Respaldar cada archivo que se sustituirá y los dos puentes compilados. Verificar que el respaldo anterior sigue VERIFIED y que la fuente principal coincide con la base esperada.
- [x] En una copia de configuración/proyecto, enumerar interfaces e instancias disponibles, escoger explícitamente TESIS_PLC_SIM y consultar su estado. Verificar cancelación y endpoint propagado. La descarga de prueba solo procede si la instancia y el adaptador virtual están inequívocamente identificados; ninguna operación usa destino físico.
- [x] Probar la sobrecarga V18 con dirección en PLCSIM con respaldo del programa previo y restauración comprobada. Registrar si solo existe una instancia: no afirmar prueba de selección entre múltiples CPU. No crear instancias extra ni cambiar red para conseguir un PASS.
- [x] Verificar «Ejecutar y cargar» en el recorrido disponible, utilizando respuestas de interpretación guardadas para no enviar nuevas llamadas a la API. Compilar y descargar únicamente a la instancia virtual verificada; conservar evidencia del paquete exacto y las guardas ante fallos. Restaurar el programa previo cuando corresponda.
- [x] Solicitar una revisión independiente del cambio completo, corrigiendo hallazgos importantes con regresiones. Ejecutar la suite completa con bytes de entrada sellados; informar también omisiones y fallos esperados, sin presentar un filtro de pruebas como suite completa.
- [x] Integrar por copia y comprobación de hashes, reconstruir los puentes principales y ejecutar pruebas focalizadas sobre la carpeta principal. Verificar que sus mapas, resultados, Oracles y 496 entradas preparadas siguen intactos. Si hay modificaciones concurrentes, conservarlas y no sobrescribirlas.
- [x] Registrar pruebas visuales, límites físicos/V18, respaldo/restauración y pasos de uso en la guía. Commit en la rama de trabajo, conservar worktree/evidencia, publicar prueba de entrega sin fusionar ni reescribir Git principal.

## Revisión del plan y siguiente paso

La cobertura corresponde a los once criterios de aceptación del diseño: Tasks
1–4 cubren coherencia de destino; Task 5 cubre limpieza y flujo completo; Task 6
cubre respaldo, pruebas reales y protección. Los cinco fallos del Review Focus
tienen una prueba asignada. No hay búsqueda física prometida ni prueba real
afirmada como realizada.

Henry aprobó este plan antes de implementar. Se conserva la ejecución en esta
sesión por el agente principal con revisión independiente final.

## Entrega verificada — 19 de octubre de 2026

Integrada por copia protegida de 28 archivos. Ambos puentes recompilados en la carpeta principal; 115 pruebas focalizadas aprobadas allí. Regresión completa por módulos: 2 105 aprobadas, siete omitidas y un fallo esperado, con identidad de los 2 113 casos y 530 entradas selladas intactas. Se conservan 3 813 archivos protegidos ajenos al cambio, mapas, configuración, resultados, Oracles, historial, credenciales y las 496 entradas preparadas. La revisión independiente y la descarga real a la instancia virtual están registradas.

La guía declara el cierre nativo de Tk de la ejecución monolítica, las pruebas geométricas sin inspección visual independiente, el hardware físico y la selección entre múltiples instancias reales no probados, y la mejora menor pendiente del texto de errores de búsqueda. Informe: runtime/plc_selector_validation/delivery.json. Se conserva la rama y el worktree; el Git principal no se fusiona ni se prepara.
