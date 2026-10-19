# PID en lazo cerrado: comprobación del 18 de octubre de 2026

Se conectó el proveedor de tanque existente al PID actual de `S71500_Prueba`, cargado en `TESIS_PLC_SIM`. La medición entró por IW4 y el mando se leyó de QW4 conforme a los bindings del paquete. PID_Compact 2.3 se ejecutó en el PLC virtual; el modelo externo únicamente representó la dinámica del tanque. No se sustituyó el controlador Siemens por un PID en Python.

La presintonización observó la transición nativa de estado 1 a estado 3 y `ParametersConfirmed=TRUE`. Los valores aprendidos online fueron Kp=79,217964, Ti=1,118766 s y Td=0,195784 s. Son resultados del modelo de demostración de esta prueba; no constituyen ajustes de una planta física.

Se registraron 1.586 muestras y se recalculó la aceptación desde la traza. Cada consigna debía mantenerse dentro de ±2 puntos de nivel durante 10 segundos consecutivos, antes de 300 segundos. El tiempo de la tabla incluye los 10 segundos de permanencia y se mide desde el comando de cambio de consigna.

| Consigna | Resultado | Criterio completo a | Sobreimpulso observado durante esa fase |
| --- | --- | --- | --- |
| 50 % | Aprobado | 33,47 s | 0,20 puntos |
| 40 % | Aprobado | 21,65 s | 0,13 puntos |
| 60 % | Aprobado | 26,76 s | 0,22 puntos |

También pasaron el mando manual al 40 %, Stop, fallo del sensor, rearme con Start mantenido sin rearranque y emergencia. La aplicación rechazó una consigna del 101 %; esa comprobación acredita su guarda de rango. No se ensayó una protección de sobrellenado porque el comando actual no declara ese umbral; no se añadió comportamiento al programa para aprobar un caso ajeno a su alcance.

El proveedor terminó con parada y restauración verificadas. El controlador quedó detenido, con CV=0 y la consigna original del 50 % restaurada. Se verificaron el respaldo ZIP, 3.459 hashes protegidos y los archivos de software/paquete capturados; el mapa y los resultados históricos permanecen intactos. Se reutilizó el programa ya compilado y verificado, sin efectuar otra descarga durante esta prueba.

La evidencia completa está en `runtime/pid_closed_loop_20261018_153508`: perfil, respaldo, precondiciones, trazas JSONL y CSV, etapas, seguridad, parámetros y entrega verificada. El resumen estable es `runtime/pid_closed_loop_delivery.json`.

## Pendiente antes del congelamiento

Los parámetros aprendidos permanecen online en PLCSIM. El último reporte de compilación conserva el baseline offline Kp=1, Ti=20 s y Td=0. Esta prueba no sincronizó los ajustes online con el proyecto TIA ni comprobó su conservación al regenerar o descargar. Debe cerrarse ese recorrido antes de asumir que una descarga posterior conserva la sintonización.

Las escalas se tomaron de la copia de prueba utilizada en la auditoría anterior. El mapa real continúa con calibración no confirmada. El ensayo no valida cableado, calibración o comportamiento de una planta física, ni demuestra estabilidad ante cualquier perturbación. No se inició una campaña FORMAL ni se modificó el congelamiento histórico.
