# 07 Registro de Pruebas

Este documento concentra:

- la matriz base de pruebas del MVP,
- la diferencia entre intencion detectada y plantilla implementada,
- el historial automatico de ejecuciones.

## Criterios base de aceptacion

| case_id | comando base | intent_id esperado | plantilla implementada | resultado esperado |
|---|---|---|---|---|
| `D01` | Activa una salida durante 5 segundos cuando presione Start | `INT_TIMED_PULSE` | Si | `is_valid = true` |
| `D03` | Haz que el motor se encienda con Start y se apague con Stop | `INT_MOTOR_START_STOP` | Si | `is_valid = true` |
| `D05` | El paro de emergencia debe apagar el motor siempre | `INT_EMERGENCY_PRIORITY` | Si | `is_valid = true` |
| `D07` | Arranca el motor despues de un retardo de 3 segundos | `INT_DELAYED_START` | Si | `is_valid = true` |
| `D08B` | Enciende el motor con un pulsante y que se apague 10 segundos despues de presionar el boton de paro | `INT_DELAYED_STOP` | Si | `is_valid = true` |
| `D09` | Cuenta cinco pulsos del sensor y activa la alarma | `INT_COUNTER_PULSES` | Si | `is_valid = true` |

## Matriz base resumida

| case_id | comando | intent_id esperado | observacion |
|---|---|---|---|
| `D01_V1` | Activa una salida durante 5 segundos cuando presione Start | `INT_TIMED_PULSE` | Caso base de pulso temporizado |
| `D03_V1` | Haz que el motor se encienda con Start y se apague con Stop | `INT_MOTOR_START_STOP` | Caso base de marcha y paro |
| `D05_V1` | El paro de emergencia debe apagar el motor siempre | `INT_EMERGENCY_PRIORITY` | Caso base de seguridad |
| `D07_V1` | Arranca el motor despues de un retardo de 3 segundos | `INT_DELAYED_START` | Caso base de retardo de arranque |
| `D08B_V1` | Enciende el motor con un pulsante y que se apague 10 segundos despues de presionar el boton de paro | `INT_DELAYED_STOP` | Caso base de apagado retardado |
| `D09_V1` | Cuenta cinco pulsos del sensor y activa la alarma | `INT_COUNTER_PULSES` | Caso base de conteo |

## Registros automaticos del sistema

Cada vez que `main.py` procesa un comando, `logger.py` agrega una fila debajo de este marcador.

| fecha | comando probado | intencion detectada | plantilla implementada | plataforma | archivo ST generado | verificacion valida si/no | errores | observaciones |
|---|---|---|---|---|---|---|---|---|
| 2026-07-08T17:47:30 | Haz que el motor se encienda con Start y se apague con Stop | INT_MOTOR_START_STOP | Si | OPENPLC_ST | D:\Documentos\Automatizacion para la Industria 4.0\TESIS\Software\voz_llm_plc_agent\generated_code\OPENPLC\active\2026-07-08_17-47-29_NOCASE_INT_MOTOR_START_STOP_OPENPLC_ST_full_program.st | Si | - | Asegure que este caso quede registrado tambien como prueba funcional basica. |
| 2026-07-08T17:47:30 | Haz que el motor se encienda con Start y se apague con Stop | INT_MOTOR_START_STOP | Si | CODESYS_ST | D:\Documentos\Automatizacion para la Industria 4.0\TESIS\Software\voz_llm_plc_agent\generated_code\CODESYS\active\2026-07-08_17-47-30_NOCASE_INT_MOTOR_START_STOP_CODESYS_ST_full_program.st | Si | - | Asegure que este caso quede registrado tambien como prueba funcional basica. |
| 2026-07-08T18:18:59 | Enciende el motor con un pulsante de encendido, y que se apague 5 segundos despues de precionar el pulsante de apagado | INT_DELAYED_START | Si | OPENPLC_ST | D:\Documentos\Automatizacion para la Industria 4.0\TESIS\Software\voz_llm_plc_agent\generated_code\OPENPLC\active\2026-07-08_18-18-59_NOCASE_INT_DELAYED_START_OPENPLC_ST_full_program.st | Si | - | Asegure que este caso quede registrado tambien como prueba funcional basica. |
| 2026-07-08T18:18:59 | Enciende el motor con un pulsante de encendido, y que se apague 5 segundos despues de precionar el pulsante de apagado | INT_DELAYED_START | Si | CODESYS_ST | D:\Documentos\Automatizacion para la Industria 4.0\TESIS\Software\voz_llm_plc_agent\generated_code\CODESYS\active\2026-07-08_18-18-59_NOCASE_INT_DELAYED_START_CODESYS_ST_full_program.st | Si | - | Asegure que este caso quede registrado tambien como prueba funcional basica. |
| 2026-07-09T08:16:07 | Enciende un motor con el pulsante de encendido, que se encienda 3 segundos despues de presionarlo, y que se aapague con un pulsante de paro | INT_DELAYED_START | Si | OPENPLC_ST | D:\Documentos\Automatizacion para la Industria 4.0\TESIS\Software\voz_llm_plc_agent\generated_code\OPENPLC\active\2026-07-09_08-16-07_NOCASE_INT_DELAYED_START_OPENPLC_ST_full_program.st | Si | - | Asegure que este caso quede registrado tambien como prueba funcional basica. |
| 2026-07-09T08:16:07 | Enciende un motor con el pulsante de encendido, que se encienda 3 segundos despues de presionarlo, y que se aapague con un pulsante de paro | INT_DELAYED_START | Si | CODESYS_ST | D:\Documentos\Automatizacion para la Industria 4.0\TESIS\Software\voz_llm_plc_agent\generated_code\CODESYS\active\2026-07-09_08-16-07_NOCASE_INT_DELAYED_START_CODESYS_ST_full_program.st | Si | - | Asegure que este caso quede registrado tambien como prueba funcional basica. |
| 2026-07-13T22:57:02 | Enciende el motor 5 segundos despues de presionar un pulsante de inicio, , este se debe mantener encendido hasta que presionemos el boton de alto | INT_DELAYED_START | Si | CODESYS_ST | D:\Documentos\Automatizacion para la Industria 4.0\TESIS\Software\voz_llm_plc_agent\generated_code\CODESYS\active\2026-07-13_22-57-01_NOCASE_INT_DELAYED_START_CODESYS_ST_full_program.st | Si | - | Asegure que este caso quede registrado tambien como prueba funcional basica. |
| 2026-07-13T23:18:01 | Enciende un motor desepues de presionar el pulsante, que se quede prendido hasta presionar el pulsante de paro, y despues de presionar se apague en 5 segundos | INT_DELAYED_STOP | Si | OPENPLC_ST | D:\Documentos\Automatizacion para la Industria 4.0\TESIS\Software\voz_llm_plc_agent\generated_code\OPENPLC\active\2026-07-13_23-18-01_NOCASE_INT_DELAYED_STOP_OPENPLC_ST_full_program.st | Si | - | Asegure que este caso quede registrado tambien como prueba funcional basica. |
| 2026-07-13T23:18:01 | Enciende un motor desepues de presionar el pulsante, que se quede prendido hasta presionar el pulsante de paro, y despues de presionar se apague en 5 segundos | INT_DELAYED_STOP | Si | CODESYS_ST | D:\Documentos\Automatizacion para la Industria 4.0\TESIS\Software\voz_llm_plc_agent\generated_code\CODESYS\active\2026-07-13_23-18-01_NOCASE_INT_DELAYED_STOP_CODESYS_ST_full_program.st | Si | - | Asegure que este caso quede registrado tambien como prueba funcional basica. |
| 2026-07-14T12:56:35 | Enciende un motor con un pulsante, el motor se debe encender 3 segundos despues de presionar el pulsante, y se debe apagar cunado presione el paro | INT_DELAYED_START | Paquete PLC | OPENPLC_ST | D:\Documentos\Automatizacion para la Industria 4.0\TESIS\Software\voz_llm_plc_agent\generated_code\OPENPLC\active\2026-07-14_12-56-33_NOCASE_INT_DELAYED_START | Si | - | - |
| 2026-07-14T12:56:40 | Enciende un motor con un pulsante, el motor se debe encender 3 segundos despues de presionar el pulsante, y se debe apagar cunado presione el paro | INT_DELAYED_START | Paquete PLC | CODESYS_ST | D:\Documentos\Automatizacion para la Industria 4.0\TESIS\Software\voz_llm_plc_agent\generated_code\CODESYS\active\2026-07-14_12-56-39_NOCASE_INT_DELAYED_START | Si | - | - |
| 2026-07-14T23:51:25 | Enciende un motor dentro de tres segundos de presionar el pulsante de encendido y apágalo cinco segundos después de presionar el pulsante de apagado. | INT_DELAYED_START | Paquete PLC | OPENPLC_ST | D:\Documentos\Automatizacion para la Industria 4.0\TESIS\Software\voz_llm_plc_agent\generated_code\OPENPLC\active\2026-07-14_23-51-21_NOCASE_INT_DELAYED_START | Si | - | - |
| 2026-07-14T23:51:28 | Enciende un motor dentro de tres segundos de presionar el pulsante de encendido y apágalo cinco segundos después de presionar el pulsante de apagado. | INT_DELAYED_START | Paquete PLC | CODESYS_ST | D:\Documentos\Automatizacion para la Industria 4.0\TESIS\Software\voz_llm_plc_agent\generated_code\CODESYS\active\2026-07-14_23-51-27_NOCASE_INT_DELAYED_START | Si | - | - |
| 2026-07-15T07:37:43 | Enciendo un motor al presionar el pulsante de encendido y que este se apague tres segundos después de presionar el pulsante de paro. | INT_DELAYED_STOP | Paquete PLC | OPENPLC_ST | D:\Documentos\Automatizacion para la Industria 4.0\TESIS\Software\voz_llm_plc_agent\generated_code\OPENPLC\active\2026-07-15_07-37-29_NOCASE_INT_DELAYED_STOP | No | Simulacion OpenPLC: DST_02: Salida distinta a la esperada | - |
| 2026-07-15T07:37:58 | Enciendo un motor al presionar el pulsante de encendido y que este se apague tres segundos después de presionar el pulsante de paro. | INT_DELAYED_STOP | Paquete PLC | CODESYS_ST | D:\Documentos\Automatizacion para la Industria 4.0\TESIS\Software\voz_llm_plc_agent\generated_code\CODESYS\active\2026-07-15_07-37-56_NOCASE_INT_DELAYED_STOP | Si | - | - |
| 2026-08-20T14:17:57 | Haz que el motor se encienda con Start y se apague con Stop | INT_MOTOR_START_STOP | Paquete PLC | SIEMENS_SCL_V18 | D:\Documentos\Automatizacion para la Industria 4.0\TESIS\Software\voz_llm_plc_agent\generated_code\SIEMENS\active\2026-08-20_14-17-56_NOCASE_INT_MOTOR_START_STOP | Si | - | - |
| 2026-08-20T14:18:10 | Haz que el motor se encienda con Start y se apague con Stop | INT_MOTOR_START_STOP | Paquete PLC | OPENPLC_ST | D:\Documentos\Automatizacion para la Industria 4.0\TESIS\Software\voz_llm_plc_agent\generated_code\OPENPLC\active\2026-08-20_14-18-03_NOCASE_INT_MOTOR_START_STOP | Si | - | - |
| 2026-08-20T14:18:35 | Haz que el motor se encienda con Start y se apague con Stop | INT_MOTOR_START_STOP | Paquete PLC | SIEMENS_SCL_V18 | D:\Documentos\Automatizacion para la Industria 4.0\TESIS\Software\voz_llm_plc_agent\generated_code\SIEMENS\active\2026-08-20_14-18-33_NOCASE_INT_MOTOR_START_STOP | Si | - | - |
| 2026-08-20T14:18:46 | Haz que el motor se encienda con Start y se apague con Stop | INT_MOTOR_START_STOP | Paquete PLC | OPENPLC_ST | D:\Documentos\Automatizacion para la Industria 4.0\TESIS\Software\voz_llm_plc_agent\generated_code\OPENPLC\active\2026-08-20_14-18-42_NOCASE_INT_MOTOR_START_STOP | Si | - | - |
| 2026-08-20T14:53:31 | Haz que el motor se encienda con Start y se apague con Stop | INT_MOTOR_START_STOP | Paquete PLC | SIEMENS_SCL_V18 | D:\Documentos\Automatizacion para la Industria 4.0\TESIS\Software\voz_llm_plc_agent\generated_code\SIEMENS\active\2026-08-20_14-53-30_NOCASE_INT_MOTOR_START_STOP | Si | - | - |
| 2026-08-20T14:53:47 | Haz que el motor se encienda con Start y se apague con Stop | INT_MOTOR_START_STOP | Paquete PLC | OPENPLC_ST | D:\Documentos\Automatizacion para la Industria 4.0\TESIS\Software\voz_llm_plc_agent\generated_code\OPENPLC\active\2026-08-20_14-53-39_NOCASE_INT_MOTOR_START_STOP | Si | - | - |
| 2026-08-26T14:57:28 | Enciende el motor despues de presionar el pulsante de inicio, cuando presione el stop debe detenerse despues de 10 segundos | INT_DELAYED_STOP | Paquete PLC | SIEMENS_SCL_V18 | D:\Documentos\Automatizacion para la Industria 4.0\TESIS\Software\voz_llm_plc_agent\generated_code\SIEMENS\active\2026-08-26_14-57-25_NOCASE_INT_DELAYED_STOP | Si | - | - |
<!-- AUTO-TEST-ROWS -->

## Pruebas de robustez linguistica

| fecha | comando | expected_intent | detected_intent | correcto | codigo generado | observaciones |
|---|---|---|---|---|---|---|
<!-- AUTO-ROBUSTNESS-ROWS -->
