# Registro de validación de desarrollo

Incidencias detectadas durante el uso real del software en **Modo Normal** (producto), fuera del
protocolo experimental. **Ninguna entrada es un ensayo FORMAL (FORMAL_TRIAL)**: no cuentan en las métricas
del diseño experimental v2 ni modifican benchmark, Oracles o comandos canónicos D/P.

Cada entrada registra el síntoma observado, la causa raíz real (reproducida sin TIA) y la corrección
aplicada, con su prueba de regresión.

---

## DVL-001: variable funcional sin nombre en un comando Manual/Automático complejo

| Campo | Valor |
|---|---|
| fecha | 2026-10-02 |
| modo | Normal (perfil `normal`, parser LLM) |
| clasificación | DEVELOPMENT_VALIDATION, no es FORMAL_TRIAL |
| stage | Generation |
| type | Functional resource representation |
| command_complexity | High (modos Manual/Automático, secuencia temporizada, supervisión de sensor, alarma enclavada con Reset, permisivo entre actuadores, órdenes manuales independientes) |
| symptom | `No se pudo generar el paquete PLC. Se solicitó una variable funcional sin nombre.` |
| status | detected / corrected |

**Comando.** Control Manual/Automático de una banda transportadora y una bomba:
- En Automático, Start arranca la banda y la bomba 3 s después.
- Si el sensor de presencia no cambia de estado en los 5 s siguientes al arranque, se detienen ambos actuadores y se activa una alarma.
- Stop detiene ambos actuadores.
- La alarma se mantiene hasta que desaparece la falla y se presiona Reset.
- En Manual, cada actuador responde a su propia orden, y la bomba nunca funciona con la banda apagada.

Se pidió una aclaración (mandos mantenidos o enclavados) y se respondió "mandos mantenidos".

**Reproducción (sin TIA).** Se reprodujo con el semantic output exacto guardado en
`generated_code/gui_history.json`: validación semántica → IR → generación. Los resultados fueron:
- validación semántica: `is_valid = true`;
- fallo en `ir_builder._resolve_functional_variables`, llamado desde `build_project_ir`.

**Recurso señalado.** `functional_requirements[3]`:

```json
{"type": "sensor_timeout_alarm", "sensor_input": "I_Piece_Sensor", "timeout": "T#5s",
 "start_condition": "I_Start AND M_AutoMode", "affected_outputs": ["Q_Conveyor_Enable", "Q_Pump_Enable"],
 "alarm_output": "Q_Alarm"}
```

**root_cause.** El requisito no era una variable sin nombre. Era un *comportamiento* (supervisión de
sensor con alarma) cuyo `type` no estaba en el catálogo de primitivas. Todos sus recursos tenían nombre.

`build_project_ir` separaba los requisitos en solo dos clases: "catálogo" y "todo lo demás". Lo
demás se trataba como variable funcional ad-hoc con la forma `{"name": ..., "type": REAL|BOOL...}`, y
`_resolve_functional_variables` exigía `name`. El fallo se descubría al final de la generación, sin ruta ni diagnóstico.

Hubo dos defectos asociados:
1. El validador semántico no comprobaba que cada requisito fuera identificable y generable, así que aprobaba la interpretación.
2. El compositor de secuencias (`timed_sequence`) ignoraba en silencio los requisitos que no sabía renderizar: modos, órdenes manuales, permisivos, supervisión y alarma. Si solo se hubiera corregido la clasificación, se habría generado un programa incompleto que el verificador aceptaba.

**Capas responsables.**
- E, IR builder: clasificación errónea.
- C, validador semántico: falta de validación temprana.
- G, generador: descarte silencioso dentro de la composición.

La salida del LLM (A) era una representación funcional razonable. El repair (B), el IOAllocator (D) y el
recolector de variables (F) no participaron.

**fix.**
1. **Clasificación en tres clases** (`functional_requirements.classify_functional_requirement`): primitiva del catálogo, variable funcional (con `name` o `type` IEC) o no soportado. Un comportamiento desconocido ya no se trata como variable.
2. **Recursos identificables, nombrables y asignables antes de IR/codegen** (`src/functional_resources.py`):
   - Hay un recorrido recursivo de todos los requisitos: `steps[].outputs[]`, `commands[].input/output`, `affected_outputs[]`, `*_input`, `*_output` y condiciones.
   - Un tag escrito se conserva.
   - Una referencia `{role, actor, kind}` sin nombre recibe un nombre canónico determinista (`canonical_functional_tag`) según la convención de prefijos del proyecto (`I_`, `Q_`, `M_`, `T_`, `C_`).
   - Si faltan rol y actor, o la dirección, el resultado es `FUNCTIONAL_RESOURCE_UNRESOLVED` con la ruta JSON. Nunca se genera `Variable1` ni `Output1`.
   - Un comportamiento desconocido produce `FUNCTIONAL_REQUIREMENT_UNSUPPORTED` con la ruta.
3. **Validación temprana** en `semantic_validator`, en Modo Normal y en programas compuestos:
   - Los errores anteriores y `COMPOSITION_NOT_SUPPORTED` se detectan antes de la IR.
   - Los nombres derivados entran al IOAllocator.
   - La IR repite la comprobación como defensa (`FunctionalResourceError`).
4. **Compositor genérico ampliado** (`code_generator._generate_composed_program`):
   - `automatic_mode`/`manual_mode`: modos excluyentes.
   - `manual_mode.commands[]`: órdenes `maintained`/`latched` con permisivo `enable_condition`.
   - `timed_sequence.mode_condition`.
   - `sensor_timeout_alarm` como primitiva genérica: falla enclavada que detiene las salidas afectadas; se borra con Reset una vez que el sensor vuelve a cambiar.
   - `alarm_output` y `reset_behavior`.
   - Cualquier otro tipo dentro de una composición produce `COMPOSITION_NOT_SUPPORTED`. No se descarta en silencio.
   - Las condiciones solo aceptan tags con `AND`/`OR`/`NOT`. El texto libre nunca se emite como código.
   - Una secuencia simple (p. ej. estrella-triángulo) produce exactamente el mismo código que antes.
5. **Política del LLM en Modo Normal** (`normal_interaction.NORMAL_MODE_POLICY`): documenta estas primitivas y exige que todo recurso lleve su nombre funcional.

**Resultado con la respuesta exacta del LLM.**
- semántica válida;
- 11 recursos externos asignados por el IOAllocator;
- IR construida;
- SCL generado;
- verificador `is_valid = true`, sin errores.

**Experimentación.** Sin cambios. La validación temprana solo se activa con el perfil Normal o con
programas compuestos (los ensayos D/P no usan composición). La IR conserva el mismo punto de fallo para
salidas experimentales con tipos desconocidos; solo cambia el mensaje, que ahora es estructurado. Ningún
ensayo experimental guardado contiene `sensor_timeout_alarm`.

**Regresión.** `tests/test_functional_resources.py` (25 pruebas), que usa como fixture la respuesta exacta
del LLM: `tests/fixtures/normal_incident_manual_auto_sequence.json`.
