# PID conectado al mapa IO

El comando y el mapa definen el controlador. Elegir PLCSIM Advanced o un PLC compatible cambia la conexión y las verificaciones de descarga; no añade una planta al programa ni cambia su lógica.

## Alcance implementado

- Un lazo de **nivel**, acción de llenado o vaciado y un actuador proporcional de 0–100 %. TIA V18, PID_Compact 2.3 y OB cíclico de 100 ms.
- Medición y mando por canales INT de hardware, con sus direcciones y escalas declaradas, o por miembros REAL de DB propios declarados expresamente en el mapa. La medición DB exige un miembro BOOL de calidad.
- Resolución por función, alias, magnitud, unidad y permiso. Dos señales igualmente compatibles requieren aclaración. Una variable bloqueada no se utiliza como sustituto.
- Consigna, sobrellenado y rangos se convierten a la unidad del mapa. No se inventan señales, calibraciones ni parámetros sintonizados.
- Marcha por flanco, parada y emergencia prioritarias, fallos enclavados y rearme sin rearranque al mantener Marcha pulsada. Las salidas opcionales solo se conectan si el comando y el mapa las autorizan.
- Los paquetes históricos v1 mantienen su ruta explícita; el supervisor experimental y los resultados anteriores conservan su significado.

No supone compatibilidad con cualquier planta analógica. Otros procesos, múltiples lazos, actuadores distintos o versiones Siemens requieren ampliar y verificar su contrato.

## Interpretación del control en Modo Normal

Las reglas de composición de Modo Normal tienen prioridad en la instrucción del intérprete. La petición original se conserva durante los reintentos y se contrasta con el resultado antes de generar el programa:

- «Llenar hasta un límite y detener» representa una operación finita con lectura del sensor y parada del actuador; no se convierte en un PID, un supervisor ni una secuencia que repita o mantenga la última etapa.
- Dos límites de encendido y apagado requieren histéresis con memoria. Tener una entrada analógica no implica usar PID.
- Pedir un PID nuevo requiere crear el lazo nativo; una consigna o una bandera de habilitación no lo sustituyen. Supervisar un PID existente conserva esa arquitectura, incluso si se pide crear una alarma adicional.
- El actuador solicitado se contrasta con el dispositivo del mapa. Una petición de una bomba no autoriza sustituirla por la válvula proporcional disponible.

Una medición empleada únicamente en una alarma no demuestra que el actuador se detenga. La comprobación estructural relaciona la medición con las condiciones, transiciones o cortes de las salidas de proceso, admitiendo indicadores independientes. Si falta la medición, el dispositivo o un dato indispensable del comportamiento, el sistema bloquea la generación o solicita aclaración. No confirma calibraciones ni modifica el mapa para superar una validación fallida.

Los reintentos de formato de Modo Normal reciben el error del contrato JSON y conservan su límite de intentos. Los metadatos del contexto no son campos de salida; la respuesta sigue pasando por el esquema estricto y por los validadores funcionales. Los perfiles históricos de experimentación conservan su instrucción y recorrido anteriores.

Estas comprobaciones cubren restricciones explícitas y las primitivas admitidas; no demuestran la equivalencia de expresiones arbitrarias ni garantizan entender cualquier comando. Los ensayos con respuestas reales, las regresiones y las simulaciones locales se registran por separado de una compilación Siemens o una prueba en PLC. La entrega de esta corrección se documenta en `runtime/normal_control_interpretation_delivery.json`.

## Preparar y probar un tanque

1. Configure la plantilla TIA con su CPU, módulos y direcciones reales. En el mapa habilite un sensor de nivel y un actuador proporcional, indicando rango eléctrico, raw, ingeniería, unidad y mando ante fallo. Para el banco S7-1500 se han usado IW4/QW4, 4–20 mA y 0–100 %, con digitales I16.x/Q8.x. Los rangos supuestos siguen marcados como supuestos hasta comprobar el equipo.
2. Pida, por ejemplo: «Mantén el nivel del tanque al 50 % mediante PID usando el sensor de nivel y la válvula proporcional de llenado. Start inicia, Stop detiene y la emergencia para el proceso. Al llegar al 95 %, detén el llenado y enclava el fallo. Reset rearma; exige una nueva pulsación de Start».
3. Genere, importe y compile. El software crea su infraestructura PID y conecta el programa según el mapa. El controlador comienza sin sintonización confirmada; no se presenta una ganancia de demostración como ajuste válido.
4. Descargue en el destino configurado. Para hardware se exigen los datos analógicos confirmados y la compatibilidad CPU/firmware/TIA. Este desarrollo solo descarga en TESIS_PLC_SIM.
5. En PLCSIM puede abrir **Puesta en marcha PID → Probar con modelo de tanque**. Abrir la ventana no inicia el modelo ni escribe valores. El botón inicia un proveedor externo; después use Rearme, Marcha, mando manual y la autorización de sintonización de la ventana. Los selectores físicos declarados conservan su prioridad.
6. Detener el modelo o cerrar la ventana cancela el trabajo y comprueba parada y restauración. Si la limpieza falla, el error permanece visible. No descargue otro programa durante una prueba.

Para un mapa sin analógicas puede crear señales «Señal de proceso en DB», REAL, con función, unidad, rango, DB/miembro y calidad. El ejemplo `data/plc_maps/examples/pid_tank_db.json` está separado del mapa activo y no se activa automáticamente. La ausencia de analógicas por sí sola no autoriza a inventar una planta o sustituir el mapa.

## Plantilla abierta y proyecto generado

En Modo Normal, los programas discretos y PID se importan, compilan y guardan en el proyecto Normal configurado: para el banco actual, `tia_projects/S71500_Prueba/S71500_Prueba.ap18`. El puente se conecta únicamente a la sesión cuya ruta coincide con ese proyecto. El PID queda visible dentro de ese proyecto y la descarga usa el mismo proyecto verificado, sin redirigirla a una copia anterior de `runtime/pid`.

Antes de sustituir un programa, Modo Normal guarda el estado actual y crea un respaldo comprimido en `runtime/backups/normal_program_<identificador>/BeforeProgram.zap18`. El reporte contiene `normal_program_backup_path`. Para recuperar un respaldo, recupérelo desde TIA en una carpeta nueva y compruebe su contenido antes de seleccionar el proyecto recuperado como proyecto Normal.

Los cambios discreto → PID, PID → discreto y PID → otro PID verifican la propiedad de los bloques antes de retirarlos. El registro del proyecto incluye manifiesto, identidad del objeto tecnológico, código, interfaces y atributos de planificación y memoria de los bloques. Una modificación manual funcional, una colisión con bloques ajenos o un registro que no coincide bloquean la sustitución. La sintonización offline compatible del mismo PID se conserva por separado.

La verificación del programa discreto anterior regenera su fuente, compila y compara sus bloques antes de iniciar la transacción de sustitución: Siemens no permite compilar dentro de una transacción ni exportar bloques recién regenerados que siguen inconsistentes. Esta preparación se realiza bajo acceso exclusivo y después del respaldo. La generación nueva utiliza una transacción de Openness; la compilación ocurre fuera de ella. Ante un fallo de preparación, generación o compilación antes de guardar el programa nuevo, el puente descarta únicamente sus cambios posteriores al respaldo y vuelve a abrir el último proyecto guardado. El registro se prepara antes de guardar; si su publicación final falla, queda una copia pendiente verificable para recuperar la correspondencia con el programa.

La descarga PID comprueba de nuevo el inventario compilado bajo acceso exclusivo y rechaza cambios sin guardar o diferencias con el programa verificado. Los paquetes históricos v1 y las herramientas que solicitan explícitamente una copia aislada mantienen su recorrido anterior. Un fallo de acceso/importación se presenta separado de los errores devueltos por el compilador.

## Modelo y evidencia

`config/pid_tank_test_profile.json` define exclusivamente la planta de prueba: nivel inicial 20 %, llenado 2 % del rango/s, descarga 0,8 % del rango/s, período nominal 100 ms y duración limitada. Se integra con el tiempo realmente transcurrido. Lee el mando real QW o REAL declarado y escribe únicamente la medición/calidad de prueba; no sustituye PID_Compact ni escribe PV/CV privados o ganancias.

Cada intento tiene una carpeta única con perfil, hashes de artefactos, raw/ingeniería, consigna, mando, calidad, estados, errores, parámetros observados, tiempos, jitter y cierre. Un proveedor terminado o cancelado no equivale a aceptación del control.

El protocolo explícito `scripts/validate_native_pid.py` distingue v1 y v2. En v2 exige mando manual, transición nativa de presintonización, consignas 50/40/60 % dentro de ±2 puntos del rango durante 10 s antes de 300 s por consigna, seis comprobaciones de parada/fallo y limpieza verificada. Una inyección de fallo no representable se registra como no disponible y no aprueba el caso.

La sesión persistente comprueba la instancia, RUN y las 16 palabras Build antes de cada escritura y restauración. Si cambia el programa, rechaza las escrituras y no intenta restaurar usando la identidad anterior. Las lecturas digitales mantienen la lista IODB porque la Runtime API comparte esa lista entre clientes.

## Sintonización y límites de la validación

Los parámetros observados online quedan en el PLC/PLCSIM. Antes de otra descarga, sincronícelos manualmente con el proyecto TIA si desea conservarlos; no se realiza carga online automática. La reimportación conserva el objeto tecnológico propio y sus parámetros offline; únicamente se restaura la confirmación si esos parámetros ya estaban verificados offline.

La prueba de reimportación realizada conservó el baseline offline existente (Kp=1, Ti=20 s, Td=0), sin convertirlo en sintonizado. La API Openness de este equipo expone los parámetros retenidos como solo lectura; se retiró el intento de sembrar una ganancia de prueba. La sintonización nativa online se verifica por separado.

El registro de entrega `runtime/pid_io_unification_delivery.json` distingue pruebas de software, compilación Siemens, ejecución nativa, limpieza y archivos integrados. Los intentos fallidos también se conservan. Estas son comprobaciones de desarrollo, no una nueva campaña formal de tesis ni una validación en planta física. Aún corresponde verificar calibración/cableado reales y ejecutar las campañas text, voice command y voice noise sobre la versión que se congele para presentar resultados comparables.

## Evidencia de desarrollo del 16 de octubre de 2026

La comprobación adicional en el proyecto original abierto `S71500_Prueba` quedó registrada en `runtime/pid_normal_live_20261016_193442`: discreto → PID (`step1g_pid`), reimportación (`step2_reimport`), PID → discreto (`step3_discrete`), regreso a PID (`step4_pid`) y reimportación posterior a recuperación (`step6_after_recovery`) compilaron y guardaron con cero errores y cero advertencias. La reimportación conservó el objeto tecnológico y sus parámetros offline. El proyecto terminó con `FB_PID_Tank_Level_Fill`, su DB de instancia y `OB_PID_Tank_Level_Fill` (OB30, 100 ms), además del objeto PID_Compact.

La fuente temporal `step5_failure` incluyó una variable no declarada: TIA devolvió un error de compilación, el puente no guardó ese programa y reabrió el último proyecto guardado. La siguiente reimportación verificó el inventario propio y pasó. Cada intento creó su archivo `BeforeProgram.zap18`; el respaldo inicial anterior a las transiciones está en `runtime/backups/normal_program_d9019c1a`. Los intentos previos de acceso y el fallo de exportación también se conservan. Esta comprobación no descargó programas al PLC ni repitió la prueba dinámica del lazo.

| Conexión | Intento final | Resultado |
| --- | --- | --- |
| IW4/QW4, INT, 4–20 mA configurados en el mapa | `run_314cb4cedf79` | Aprobado: siete etapas, tres consignas, seis casos de seguridad y limpieza verificada. |
| `DB_TankProcess`, medición REAL/calidad y mando REAL | `run_ef9e1ebdc606` | Aprobado con el mismo protocolo y criterios. |

Ambos paquetes compilaron sin errores en TIA y se ejecutaron con PID_Compact 2.3 en OB cíclico real de 100 ms. La inyección de una huella incorrecta fue rechazada por Runtime sin escrituras. La revisión independiente detectó y permitió corregir cuatro casos de errores tardíos, nombres Siemens y rangos REAL; se conservaron sus reproducciones y pruebas de regresión.

El intento DB anterior `run_c43d1cc735dd` tuvo un timeout tardío de Runtime y limpieza no verificada; permanece como **FAILED**, aunque había aprobado la sintonización y las consignas. La repetición serializada pasó. Esto no convierte el intento fallido en aprobado ni demuestra ausencia universal de fallos de infraestructura.
