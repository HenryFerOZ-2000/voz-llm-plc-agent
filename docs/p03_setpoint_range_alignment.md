# P03: alineación del rango de setpoint (0-100 % frente a 10-90 %) — RESUELTO

> **Estado (2026-10-12, rama feat/preformal-readiness-v3):** resuelto. `config/pid_supervisor_config.json` usa
> `level_setpoint` 0-100 %; `semantic_validator` lo lee de la configuración sin valores codificados y la capacidad
> `reject_unsafe_setpoint` valida en el PLC la solicitud (`Level_SP_Command`) contra ese rango. El texto "setpoint
> 10-90 %" que conservan las convenciones C-PID de los Oracles P congelados es informativo (no se evalúa) y no
> se modifica. El resto de este documento es el análisis previo.

**Fuente v3 (FORMAL):** el benchmark y el Oracle de P03 fijan el rango aceptado en **0 % - 100 %** (comando canónico sin
cambios; invariante `INV_SP_RANGE` 0-100). La configuración legacy usa **10 % - 90 %**. Esta alineación queda
**pendiente**: afecta a código de producción y no se ha cambiado.

## Sitios donde sigue el rango 10-90 %

| Sitio | Qué hace | Cambio necesario |
|---|---|---|
| `config/pid_supervisor_config.json` → `level_setpoint.min = 10.0`, `max = 90.0` | Límite de setpoint seguro del supervisor PID | `min: 0.0`, `max: 100.0` |
| `src/semantic_validator.py` → `_detect_unsafe_level_setpoints` (lee `level_setpoint`) y su uso en la validación semántica | Marca como inválido cualquier `set_level_setpoint` fuera de 10-90 y pide aclaración | Sin cambio de código: tomará el nuevo rango de la configuración |
| `tests/test_pid_supervisor.py::test_setpoint_range_is_config_driven_not_hardcoded` | Congela que 5 % y 95 % son inseguros y 50 % es seguro | Ajustar los valores de prueba al rango 0-100 (p.ej. -5 % y 150 % inseguros; 0 %, 60 % y 100 % seguros) |
| `tests/test_pid_supervisor.py::test_p03_out_of_range_setpoint_is_rejected_deterministically` | 150 % rechazado | Sigue válido con 0-100 |

## Impacto si no se alinea

- El Oracle P03 solo prueba 60 % (aceptado) y 150 % (rechazado), así que una implementación 10-90 % también pasaría.
- Pero la **validación semántica** rechazaría (pidiendo aclaración) un comando que fije un setpoint entre 0-10 % o
  90-100 %, aunque el benchmark v3 lo considere válido. P02 (60 %) y P12 (60 %) no se ven afectados.

## Recomendación

Alinear `level_setpoint` a 0-100 % antes de la congelación del software para FORMAL, en un cambio separado y con su
test, y registrarlo en el changelog.
