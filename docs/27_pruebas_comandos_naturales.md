# Comandos naturales: diagnóstico y comprobación del 18 de octubre de 2026

Se comprobaron cuatro comandos del usuario sin nombres ni direcciones de IO: marcha/parada discreta, llenado hasta el 80 %, histéresis 30–80 % y mantenimiento de nivel al 50 % mediante PID. El contexto procede del mapa activo S7-1500 y del motor compartido del producto. No se inició una campaña FORMAL ni se modificó su congelamiento.

## Errores corregidos

- Una solicitud IO del modelo sin `functional_name_hint` ni `proposed_name` provocaba `NoneType.startswith`. Ahora se informa un error de formato para que opere la corrección controlada del intérprete.
- Una secuencia incompleta generada por el modelo podía preguntar por etapas que el usuario ya había definido. Una interpretación inválida con errores `CONTROL_` recibe una sola corrección antes de mostrar esa pregunta. Se conservan las aclaraciones funcionales solicitadas realmente por el modelo.
- El enclavamiento discreto y los enclavamientos compuestos de Start permitían rearranque al liberar Stop con Start mantenido. Los comandos directos de arranque usan un flanco y necesitan una nueva pulsación. Las condiciones booleanas compuestas o negadas mantienen su significado.
- La memoria de histéresis podía conservar ON después de deshabilitar el control. Los bloqueos del perfil del producto también limpian esa memoria.
- Los auxiliares de arranque se reservan sin reutilizar variables del mapa ni declaraciones explícitas; se comprueban colisiones sin distinguir mayúsculas.

Los cambios de generación se aplican al perfil del producto compartido. Se conserva el recorrido histórico de Experimentación.

## Evidencia y alcance

La auditoría está en `runtime/natural_commands_audit_20261018_145416`. Incluye las respuestas reales de la API, el mapa capturado, reproducciones fallidas, las regresiones y paquetes generados. El respaldo previo es `runtime/backups/pre_natural_commands_20261018_145416`.

Los cuatro programas se importaron y compilaron en `tia_projects/S71500_Prueba/S71500_Prueba.ap18`, con respaldo transaccional del programa anterior. Las descargas y escrituras se limitaron a `TESIS_PLC_SIM`; se conservaron la interfaz PG/PC y la configuración de red del usuario.

En PLCSIM pasaron 32 pasos observados para discreto, histéresis y llenado: arranque, límites, memoria de histéresis, nuevo Start, Stop y emergencia. Cada prueba terminó verificando las salidas apagadas. El PID nativo verificó lectura IW4, mando QW4 al 35 % en manual, bloqueo por sensor inválido, rearme y parada, con restauración verificada del proveedor.

Esto acredita interpretación, generación, compilación y los comportamientos observados. La prueba PID de esta auditoría no acredita regulación al 50 % ni sintonización: `ParametersConfirmed` permanece falso y el controlador usa manual hasta realizar la puesta en marcha correspondiente. El primer intento de prueba PID expiró correctamente por inactividad del proveedor; se corrigió el harness para suministrar el nivel continuamente, como hace la interfaz, y se conservó aquella evidencia.

El mapa real tiene las escalas analógicas marcadas como no confirmadas. Las pruebas analógicas de software usaron una copia con sus supuestos de prueba confirmados; no se modificó ni se certificó la calibración del mapa activo. El comando de llenado recibió una aclaración válida sobre la apertura de la válvula proporcional; se probó el ciclo completo con la respuesta explícita del 100 %. No se debe eliminar esa pregunta inventando un porcentaje.

Los conteos finales y hashes se registran en `runtime/natural_commands_delivery.json`. No equivalen a una garantía de interpretación de cualquier comando o compatibilidad con cualquier mapa/planta. Permanecen pendientes la confirmación del equipo real, la validación dinámica de regulación de esta versión y el cierre del alcance experimental del PID nativo.
