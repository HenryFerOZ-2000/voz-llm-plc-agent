# Conservación de la sintonización PID: 18 de octubre de 2026

Se guardaron en `S71500_Prueba` los parámetros obtenidos en la prueba anterior de tanque, se regeneró el mismo programa y se descargó nuevamente a `TESIS_PLC_SIM`. La regulación volvió a cumplir las tres consignas sin otra presintonización ni sintonización fina.

## Guardado inicial en TIA

Con el controlador detenido y con salida cero, se creó `BeforeTuningUpload.zap18` y se verificó su CRC. Se abrió `Technology objects > PID_Loop1 > Commissioning`, se inició la medición y se utilizó **Upload PID parameters**, seguido de **Save project**. La vista offline mostró los ajustes aprendidos.

Después se activó **Enable manual entry** en la configuración de parámetros PID, conservando sus valores. Esta opción deja los valores definidos en la plantilla; la regulación posterior se verificó en automático, con estado Siemens 3. El puente existente reconoce la confirmación offline para inicializar `ParametersConfirmed=TRUE` al regenerar.

Este guardado inicial se realiza desde TIA. La aplicación utiliza después los parámetros verificados del objeto tecnológico propio. La operación local sigue el [procedimiento de Siemens para guardar parámetros optimizados en el proyecto](https://docs.tia.siemens.cloud/r/simatic_s7_1500_et_200mp_manual_collection_enus_21/comprehensive-information/technology-function-manuals/pid-control/configuring-a-software-controller/save-optimized-pid-parameter-in-the-project?contentId=xPIqa_edXIf~HjyUDqb0ug); en este equipo se comprobó directamente la interfaz instalada V18.

## Comprobaciones realizadas

La fuente generada y la identidad de configuración coincidieron con las del programa anterior. La compilación Normal indicó `technology_created=false`, `parameters_preserved=true` y `parameters_verified_offline=true`. La descarga terminó correctamente y Runtime confirmó los mismos Kp/Ti/Td, con tolerancia absoluta de 0,0001 por el almacenamiento de valores REAL.

| Parámetro | Antes de guardar | Después de regenerar y descargar |
| --- | --- | --- |
| Kp | 79,217964 | 79,217957 |
| Ti | 1,118766 s | 1,118766 s |
| Td | 0,195784 s | 0,195784 s |

La respuesta posterior utilizó los parámetros conservados. Se mantuvo cada consigna dentro de ±2 puntos durante 10 segundos antes de 300 segundos. Los tiempos siguientes incluyen la permanencia de 10 segundos y se miden desde cada comando.

| Consigna | Resultado | Criterio completo a |
| --- | --- | --- |
| 50 % | Aprobado | 36,47 s |
| 40 % | Aprobado | 21,62 s |
| 60 % | Aprobado | 26,57 s |

La traza no contiene estados de sintonización 1/2 durante esta repetición. Los criterios se recalcularon desde las muestras guardadas. La sesión terminó con parada y restauración verificadas: controlador detenido, CV=0, consigna del 50 %, parámetros confirmados y sin fallo.

## Cambio de configuración

En una copia del mapa se cambió exclusivamente el máximo raw de la medición de 27648 a 27000 para representar un contrato de calibración distinto. Cambiaron la identidad del controlador y la fuente. La prueba se ejecutó en una copia TIA obtenida mediante Archive/Retrieve; el puente rechazó la reutilización del OB existente con `PID_BLOCK_CONFLICT`. Ese paquete no se descargó y el mapa activo permaneció intacto.

La prueba acredita esa guarda en el recorrido aislado y la conservación del mismo lazo en Modo Normal. Una configuración o un programa distinto requiere verificar nuevamente su correspondencia con los ajustes. No se presenta este ensayo como cobertura de todas las transiciones posibles ni de una planta física nueva.

## Evidencia y límites

La entrega estable es `runtime/pid_persistence_delivery.json`, con evidencia en `runtime/pid_persistence_20261018_161122`: respaldo anterior, respaldo posterior con ajustes, generación, compilación, descarga, trazas JSONL/CSV, prueba de cambio de configuración y hashes. También pasaron 51 comprobaciones existentes de contratos, identidad y configuración PID. El primer intento de la prueba aislada se detuvo por cambios sin guardar; se conservó su reporte y se repitió después de guardar el proyecto.

Se verificaron 3.459 archivos protegidos, incluyendo mapa, configuración, resultados previos y el índice Git principal. El código del producto permaneció igual; se actualizó el estado gestionado del proyecto Normal y se añadieron herramientas/evidencia de desarrollo y esta documentación.

Los parámetros pertenecen al modelo de tanque ensayado. La calibración del equipo real continúa pendiente, la evaluación experimental del PID nativo conserva su guarda vigente y no se creó un congelamiento ni una campaña FORMAL nueva.
