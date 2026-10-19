# Histéresis analógica y prueba de I/O

El comando de llenado con histéresis del 19 de octubre de 2026 ya contenía
`on_value: 100`, `off_value: 0`, `output_unit: "%"` y una condición de habilitación.
El generador solo admitía histéresis booleana y rechazaba la salida analógica
con `ANALOG_OUTPUT_COMMAND_REQUIRED`. La corrección conserva esos datos,
convierte sus unidades según el mapa y genera un mando numérico con memoria.
La habilitación se evalúa después de asignar su enclavamiento. Deshabilitar,
Stop o emergencia aplican el valor seguro configurado; el rearme del producto
conserva la exigencia de una nueva pulsación de Start. No se incorpora un PID
a este control de dos límites.

## Uso de la ventana

1. Reinicie la aplicación para cargar el código actualizado.
2. Genere, compile y cargue el programa en la instancia PLCSIM Advanced
   seleccionada. Los paquetes nuevos conservan una copia del mapa utilizado
   en `generation_io_map.json`; las escalas de la ventana salen de esa copia.
3. Abra **PRUEBA DE I/O**, visible junto a **SELECCIONAR PLC**.
4. Elija una entrada BOOL y use ON/OFF y **APLICAR ENTRADA**, o **PULSAR** para
   una pulsación momentánea. Para una analógica, ajuste el slider o escriba
   el valor en unidades físicas y pulse **APLICAR ENTRADA**. El readback muestra
   el valor efectivo y su RAW.
5. Seleccione una salida y pulse **LEER SALIDA REAL**. Puede activar la
   actualización periódica. El indicador muestra la respuesta del programa.
6. Al cerrar, se restauran y verifican los valores iniciales de las señales
   modificadas. Si no se puede restaurar, la ventana permanece abierta y la
   aplicación detiene su cierre para permitir un reintento.

Si un paquete antiguo carece de escala congelada, el control indica **RAW**;
no toma una escala del mapa activo que pudo cambiar después de la descarga.
Genere y cargue un paquete nuevo para trabajar en unidades físicas.

Para una prueba manual de salidas, cierre antes cualquier prueba con entradas
pendientes, coloque la CPU virtual en STOP y vuelva a abrir la ventana.
Marque **Prueba manual de salidas**. La herramienta habilita los mandos
BOOL o numéricos y verifica lo que escribe. Antes de volver a RUN restaure
y cierre esa prueba. La aplicación no cambia automáticamente RUN/STOP.
Esta operación es independiente de observar la respuesta del programa en RUN.

## Comprobación de la histéresis

Con escalas de nivel y apertura de 0–100 %, confirme primero en el mapa
que corresponden a su banco. Use el comando:

> Al pulsar Start, habilita el control de llenado. Cuando el nivel baje al
> 30 %, abre la válvula al 100 %. Cuando alcance el 80 %, ciérrala. Entre
> ambos límites conserva su estado. Stop o la emergencia deben cerrar la
> válvula y deshabilitar el control hasta una nueva pulsación de Start.

En RUN, aplique nivel 20 %: la válvula debe permanecer cerrada antes de
Start. Pulse Start: debe abrir al 100 %. Cambie el nivel a 50 %: sigue
abierta. Suba a 85 %: se cierra. Baje a 50 %: sigue cerrada. Baje a 20 %:
vuelve a abrir. Pruebe Stop y emergencia: la válvula se cierra y liberar
la señal no debe reanudar el llenado hasta otro Start.

Use 85 % para la primera comprobación del límite superior: el entero RAW
que representa exactamente 80 % puede redondearse ligeramente por debajo
del umbral. Eso es cuantización de la entrada.

## Alcance y evidencia

El panel admite BOOL, INT, WORD, UINT, DINT, DWORD y REAL en direcciones
físicas compatibles del programa descargado. Verifica instancia por nombre
y, cuando está configurado, por ID, además de nombre, área, dirección y tipo
de cada señal contra los símbolos cargados. Lecturas y readbacks contrastan
símbolo e imagen de proceso. Las escrituras manuales solo se permiten en
PLCSIM Advanced: entradas en RUN, salidas en STOP. No se accede a un PLC físico.

El transporte manual es independiente del protocolo histórico del Oracle;
no amplía sus capacidades declaradas ni convierte observaciones manuales en
resultados científicos de éxito funcional. Los mapas reales, la configuración
de conexión y las evidencias de ensayos anteriores se conservan.

La regresión de histéresis usa la respuesta capturada del intérprete y ejecuta
el SCL generado mediante el simulador local, incluidos memoria, habilitación,
Stop, emergencia, rearme y valores inválidos. La comprobación del transporte
real usa el programa de llenado finito previamente descargado en
`TESIS_PLC_SIM`: salida RAW 27648 → 0 → 0 al modificar el nivel, con restauración
verificada. Esa prueba no descarga un nuevo programa ni modifica TIA.
Las salidas manuales en STOP disponen de guardas y pruebas locales; su
comprobación interactiva en la instancia se realiza al usar ese modo.

La evidencia de desarrollo de este cambio se conserva en
`runtime/hysteresis_panel_20261019` de la copia de trabajo y su entrega en
`runtime/hysteresis_io_fix_20261019` de la carpeta principal. Esto no sustituye
las pruebas experimentales formales ni la futura validación en planta real.
