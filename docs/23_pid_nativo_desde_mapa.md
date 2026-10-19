# PID nativo desde el mapa PLC

> Documento histórico de paquetes v1. Para la generación actual, sin selector de entorno PID y con conexiones desde el mapa, consulte [PID unificado desde el mapa](24_pid_unificado_desde_mapa.md).

Implementación de desarrollo del 16 de octubre de 2026. No constituye todavía una validación en planta ni una nueva congelación experimental.

## Banco preparado

El mapa working del banco S7-1500 conserva sus digitales I16.x/Q8.x. Solo se prepararon AI_Level_Raw en IW4 y AO_Fill_Command en QW4: transmisor de nivel y válvula proporcional de llenado, ambos 4–20 mA, escala raw 0–27648 y unidades 0–100 %. Son supuestos de prueba: `confirmed=false`, `configuration_basis=ASSUMED_FOR_TEST`. Antes del modo físico se deben verificar canal, escala, acción de falla y configuración del módulo en TIA y confirmar ambos dispositivos en el editor del mapa.

El motor resuelve nombres, permisos y direcciones del mapa seleccionado. No exige Q8.4/Q8.7. Bloquear la asignación de una variable no revoca su permiso de uso: ese permiso se configura separadamente. Si existen varios sensores o actuadores compatibles, se debe indicar cuál usar. Los mandos no vinculados a entradas físicas se declaran como variables internas del DB del programa.

## Primer ensayo

1. Usar Modo Normal y Siemens TIA V18; elegir «Simulacion» como modo PID antes de generar, o indicarlo expresamente en el comando.
2. Ejemplo: «En simulación, controla el nivel del tanque al 50 % con PID usando el sensor de nivel y la válvula de llenado; inicia con Start, detén con Stop y detén el llenado ante emergencia o nivel de 95 %; después de una falla exige Reset y un nuevo Start».
3. Generar y compilar. El software crea una copia de desarrollo por Archive/Retrieve de la plantilla configurada, el objeto PID_Compact 2.3, FB/DB y OB de interrupción cíclica a 100 ms. Rechaza un programa ajeno que pueda ejecutarse en paralelo; no lo elimina por coincidencia de nombre. La migración del antiguo programa de la aplicación exige comprobar que su fuente almacenada reproduce sus bloques.
4. Descargar exclusivamente a la instancia PLCSIM seleccionada. «Puesta en marcha PID» permite leer PV/CV, consigna, estados, errores y ganancias, dar Start/Stop/Reset, solicitar manual y autorizar explícitamente una sintonización. Abrir el panel no escribe valores.
5. El modo simulado usa un modelo de tanque dentro del PLC; mantiene la salida analógica física en reposo. No utiliza un controlador PID escrito en Python. Las ganancias demo Kp=2, Ti=20 s, Td=0 pertenecen exclusivamente a simulación.

El modo físico exige calibración confirmada y arranca sin ganancias demo. Antes de confirmar parámetros, permite operación manual y solicitudes explícitas de ajuste; el valor manual inicial es cero. Las condiciones de una planta deben admitir la excitación requerida por la sintonización. El panel de acceso runtime actual utiliza PLCSIM Advanced; la puesta en marcha de un PLC físico se realiza en TIA/HMI con las variables declaradas del DB, hasta disponer de un transporte físico validado.

Para presintonizar el modelo del ejemplo, preparar el nivel bajo con el control detenido; seleccionar mando manual40%, dar rearme y marcha en manual, autorizar el ajuste y solicitar «Presintonizar» directamente. El valor40% equilibra exclusivamente este modelo; en planta el operador debe preparar un punto de funcionamiento apropiado. Verificar en TIA la actualización de entradas/salidas y la asignación de imagen de proceso de la plantilla, además de los rangos y el ciclo efectivo. La terminación real comprobada en esta entrega es presintonización (1→3); la petición de ajuste fino está implementada, pero su terminación requiere otro ensayo. Los avisos internos no fatales `Warning` del PID se consultan en TIA; el panel actual publica `ErrorBits` y `FaultCode`.

## Parámetros y compatibilidad

Una reimportación compatible reutiliza el mismo objeto tecnológico y conserva sus parámetros offline. Las copias compiladas se registran por plantilla, huella de la plantilla y configuración del lazo, para reutilizarlas también desde un paquete nuevo. Un cambio incompatible requiere migración explícita. Los valores aprendidos online permanecen en el PLC; antes de una nueva descarga deben guardarse/sincronizarse en el proyecto TIA. No se afirma que el registro de proyectos haga una carga automática de parámetros online.

Primer alcance: un lazo de nivel, actuador proporcional 0–100 %, período verificado de 100 ms. Las combinaciones con secuencias no integradas y escritores concurrentes de la misma salida se rechazan con diagnóstico. El soporte de una plantilla concreta requiere comprobar CPU, firmware y versión del objeto tecnológico; no basta con que el archivo sea de TIA V18.

## Evidencia y estado

Se verificó en TIA V18 una CPU 1516-3 PN/DP firmware V2.6: importación con cero errores y cero advertencias, PID_Compact 2.3 y OB efectivo `CyclicInterrupt`, `CyclicTime=100000` microsegundos. Una segunda importación conservó Gain=1.75 y no recreó el objeto tecnológico. La plantilla Normal mantuvo su SHA256.

Los informes están bajo `runtime/native_pid_compile6_stdout.log`, `runtime/native_pid_reimport1_stdout.log` y el paquete indicado por `runtime/native_pid_package_path.txt`. El ejemplo completo de tanque está indicado por `runtime/native_pid_tank_package_path.txt`; su interpretación fue inyectada para comprobar integración, y no demuestra comprensión de un LLM real.

El primer ejemplo completo se compiló y descargó realmente a `TESIS_PLC_SIM`. Con ganancias demo Kp=2, Ti=20 s, Td=0, alcanzó la banda de ±2 puntos durante 10 segundos continuos a 50/40/60 % en 124,08/98,61/103,76 segundos respectivamente, dentro del límite previo de 300 segundos. El tanque estaba inicialmente en 0 %. Pasaron las comprobaciones de Stop, sensor inválido, Start mantenido tras rearme, emergencia mediante I16.2, consigna fuera de rango y sobrellenado. Estos son resultados de desarrollo del PID Siemens real, con sobreimpulso observado; no prueban desempeño universal ni sustituyen la campaña experimental de tesis.

La presintonización solicitada después de provocar sobrellenado terminó con fallo enclavado; el informe original se conserva como `PARTIAL`. Esa primera versión reseteaba el diagnóstico transitorio del bloque Siemens, por lo que su traza no permite atribuir retrospectivamente una causa exacta. La revisión posterior conserva `ErrorBits` y `FaultCode` hasta el rearme y compila con cero errores/advertencias. El protocolo ahora detiene el control y espera un nivel inferior al 20 % antes del rearme y de la presintonización a 60 %, comprobando la distancia PV/SP requerida. No se cambió el criterio de convergencia ni se sustituyó el resultado de la primera corrida.

La siguiente prueba conservó `FaultCode=6` y `ErrorBits=128 (0x80)` y mostró `CV=100` antes de solicitar el ajuste desde automático. Siemens documenta ese error cuando la salida ya está limitada o la respuesta no admite la identificación. Se corrigió la transición del mando software: solicitar presintonización o ajuste fino libera `CmdManual` en el mismo grupo de escritura que solicita el ajuste, conservando la prioridad de los selectores físicos. La preparación del protocolo utiliza manual al 40 %, el equilibrio del modelo simulado definido, en lugar de activar primero automático. [Referencia de Siemens sobre ErrorBits](https://docs.tia.siemens.cloud/r/en-us/v20/pid_compact-s7-1200-s7-1500/pid_compact-as-of-v2-s7-1200-s7-1500/errorbits-as-of-v2-parameter-s7-1200-s7-1500).

Desde esas condiciones se observó realmente `State=1 → State=3`, sin fallo, a los 59,3 segundos de observación. Siemens calculó Kp=474,19025, Ti=0,240408 s y Td=0,0420714 s para este tanque ideal simulado; **no son parámetros para transferir a una planta física**. El informe separado está en `native_pid_validation/tuning_5b16d9f95351/summary.json` del paquete actual. La primera corrida fallida y la posterior con error128 se conservan. La comprobación del control con las ganancias aprendidas se registra como otra corrida completa mediante `latest_run.json`.

La corrida completa final `run_d4eca94e8299` terminó **PASSED en sus siete etapas**. Con los parámetros aprendidos mantuvo la banda acordada a 50/40/60 % en 54,63/18,92/32,83 s respectivamente. Pasaron Stop, sensor inválido, Start mantenido tras rearme, emergencia, límite de consigna y sobrellenado. Tras recuperar el nivel y arrancar en manual al 40 %, también terminó otra presintonización 1→3 a consigna 60 %, sin fallo; Siemens dejó Gain=474,72510, Ti=0,240137 s y Td=0,0420240 s. El cierre del protocolo ordenó Stop y restauró las entradas de prueba. Esta corrida reutilizó el programa realmente cargado, verificó su huella y declaró expresamente que no realizó otra descarga, conservando los valores aprendidos online.

El primer paquete observado está señalado por `runtime/native_pid_baseline_package_path.txt`; contiene `development_baseline_summary.json`. La revisión con diagnóstico está señalada por `runtime/native_pid_tank_package_path.txt`, con `live_compile_status.json` del intento `tank10`. Cada nueva ejecución del protocolo crea su propia carpeta bajo `native_pid_validation` y actualiza `latest_run.json`; los ensayos adicionales de sintonización se registran por separado. El resultado final de esa comprobación debe leerse en su `summary.json`, sin inferir éxito a partir de la compilación.

La instancia existente utiliza Softbus y la configuración guardada selecciona un adaptador Ethernet distinto. Para este ensayo se eligió PN/IE → PLCSIM → X1 únicamente en la solicitud del proceso de desarrollo, después de consultar las conexiones reales y verificar que existía una única instancia `TESIS_PLC_SIM`; el SHA256 de la configuración guardada permaneció intacto. En futuras pruebas se debe seleccionar una interfaz disponible para la instancia real. No se cambió la red ni se descargó al PLC físico.

Las nuevas invocaciones nativas del puente escriben stdout/stderr en carpetas `tia_bridge_*` del paquete. Esto evita esperar indefinidamente un pipe heredado por TIA cuando vence el proceso del puente. El tiempo agotado produce `TIA_OPENNESS_TIMEOUT`, invalida cualquier éxito anterior de esa invocación y no cierra el Portal. No confirma una descarga: se debe verificar el destino y la identidad cargada antes de continuar. Los permisos Openness siguen siendo una acción del usuario.

La revisión independiente detectó ocho problemas y se añadieron regresiones para corregirlos: protección de funciones existentes, conflicto Auto/Manual, comprobación real antes de descargar, escritor único por salida, cancelación del ajuste al pasar a manual, invalidación de copias ante cambios de plantilla, reposo digital en simulación e identidad del programa que incluye la implementación del generador. La regresión final, después de las correcciones del diagnóstico, timeout y transición de manual a ajuste, pasó con **1.739 pruebas, 7 omitidas y 1 fallo esperado**, en 386,44 segundos; conserva una advertencia previa de escape de texto en una prueba. La integración en la carpeta habitual conservó el índice Git y pasó 85 pruebas dirigidas; la corrección de Openness/descarga pasó otras 31 y la puesta en marcha64. Un subproceso real con un descendiente que heredaba su salida confirmó el timeout en 2,04 segundos sin iniciar TIA ni tocar el PLC.

El protocolo reproducible es:

```powershell
.venv\Scripts\python.exe scripts\validate_native_pid.py --project-root C:\TESIS_HENRY\voz-llm-plc-agent --package-dir <paquete_compilado> --mode SIMULATION
```

Exige ±2 puntos durante 10 segundos continuos antes de 300 segundos por consigna y guarda trazas PV/SP/CV/estado e informes separados. La ausencia de runtime queda pendiente; un timeout de convergencia es fallo. La sintonización se informa separadamente con el resultado observado del bloque. La preparación de una sintonización necesita marcha, sensor válido, ausencia de fallo, condiciones de proceso admisibles y autorización explícita. `FaultCode` distingue emergencia, sensor, consigna, conflicto Auto/Manual, sobrellenado, fallo Siemens y mando inválido; `ErrorBits` conserva el error nativo aunque el bloque se resetee después.

## Respaldo y tesis

Respaldo completo previo: `runtime/backups/pre_pid_20261016_101817`, con ZIP, bundle Git, manifiesto SHA256 e instrucciones de restauración. Se comprobó una restauración en una carpeta separada. El cambio del mapa tiene además respaldo byte a byte bajo `runtime/map_backups/pid_tank_setup` e informe `runtime/pid_tank_map_setup.json`.

Las congelaciones y resultados anteriores se conservan. Una nueva congelación incluirá los módulos PID y sus contratos XML/JSON; las pruebas finales de texto, voz y ruido deberán identificar esa versión. Las pruebas de desarrollo no sustituyen los ensayos formales ni la verificación del banco físico.

La integración de código tiene otro respaldo bajo `runtime/backups/native_pid_integration_20261016_114812`, con hashes por archivo y estado del índice. La rama aislada conserva los commits del desarrollo. Antes de una nueva congelación se deben registrar también los archivos nuevos en Git; la integración no altera las selecciones que ya tenía el investigador en su índice.
