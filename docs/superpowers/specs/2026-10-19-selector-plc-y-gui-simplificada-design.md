# Selector de PLC y simplificación de la GUI

Fecha: 19 de octubre de 2026, America/Guayaquil.

Estado: diseño corregido aprobado por Henry el 19 de octubre de 2026 mediante
«listo hazlo entonces, y también lo que estábamos hablando». El plan fue aprobado posteriormente. La implementación está integrada y verificada el 19 de octubre de 2026; el informe de entrega distingue la regresión por módulos, la comprobación real en PLCSIM y los límites aún no probados.

Corrección de Henry, 19 de octubre: se retiran los ocho botones laterales que
repiten el mapa completo. «Ejecutar y cargar al PLC» se conserva visible porque
lo utiliza para realizar el proceso completo desde el comando hasta la descarga.

## Objetivo y protección

Seleccionar desde la GUI el destino del Modo Normal, mostrar hechos del equipo
seleccionado y reducir controles duplicados. El comando continúa describiendo el
comportamiento y el mapa sigue definiendo los dispositivos. Cambiar el destino
no debe alterar la interpretación, inventar IO ni convertir una CPU en otra.

Respaldo previo verificado:
`runtime/backups/before_plc_selector_20261019_105048/RESTAURAR.md`.
Contiene tres ZIP, restauración comprobada de 11 893 archivos, historial Git,
índice y parches, e instantánea TIA `TIA_saved/NativePID.zap18` después del guardado
del usuario. Conserva por separado las credenciales `.env`. El archivo
`backup_report.json` distingue las muestras de estado PLCSIM de la configuración.

No se sobrescriben resultados, Oracles ni mapas. El índice de la carpeta principal
y sus cambios anteriores se conservan. El desarrollo continúa en la copia aislada
existente y se integra por comparación de hashes y respaldo de los archivos tocados.

## Hechos comprobados

- El panel actual renderiza `download_targets.normal` y consulta siempre la
  Runtime API de PLCSIM; no es un explorador general de PLC.
- El puente Runtime ya enumera nombres e identificadores de instancias registradas,
  pero la GUI solo muestra la instancia configurada.
- La descarga admite los tipos `PLCSIM_ADVANCED` y `PHYSICAL_PLC`. Actualmente
  selecciona modo PG/PC, nombre de interfaz y puerto del proyecto; una IP mostrada
  en la GUI no se transmite por sí sola como dirección explícita de descarga.
- La API pública instalada es V18. `ConfigurationPcInterface` no expone
  `GetAccessibleDevices()`. La documentación de Siemens para V21 sí lo documenta.
  No se puede presentar una lista de interfaces como si fueran PLC descubiertos.
- V18 documenta direcciones `ConfigurationAddress` y una sobrecarga de
  `DownloadProvider.Download` con dirección destino. Su uso se verificará antes
  de habilitar el nuevo encaminamiento; los campos no serán decorativos.
- La edición de variables está duplicada en el lateral y `FullIOMapWindow`.
  Esta última ya permite crear, editar, duplicar, bloquear y guardar variables.
- «GENERAR ENSAYO» y «GENERAR SOLO (DEVELOPMENT/DEBUG)» llaman al mismo método.

## Alternativas y elección

1. Añadir únicamente un selector de nombres: es pequeño, pero puede dejar la
   descarga y el estado apuntando a otro destino. Se descarta.
2. Selector integrado con configuración, direccionamiento y estado por destino:
   reutiliza los puentes y los flujos existentes. Es la opción elegida.
3. Añadir otro SDK de búsqueda o actualizar TIA para buscar PLC físicos: introduce
   dependencias y cambia el entorno probado. Queda fuera de esta entrega.

La primera entrega descubre las instancias virtuales registradas y permite
configurar destinos físicos por dirección explícita. La búsqueda automática de
PLC físicos queda declarada como capacidad no disponible en este V18, sin una
lista ficticia ni un barrido genérico de IP. El acceso manual a un PLC físico
sigue siendo parte del selector; «Buscar» describe su alcance según el proveedor.

## Flujo visible

El panel «Destino del programa» muestra:

- Proyecto TIA Normal seleccionado y CPU esperada de esa plantilla.
- Mapa IO activo, sin cambiarlo automáticamente por elegir otro PLC.
- Tipo de destino: PLCSIM Advanced o PLC físico.
- Interfaz PG/PC y puerto del proyecto; sus valores proceden de TIA.
- Instancia registrada cuando es virtual, o dirección IP cuando es físico.
- Estado del destino seleccionado y alcance de la última comprobación.

Botones del panel: «Seleccionar PLC…» y «Actualizar estado». El primero abre un
diálogo con búsqueda de instancias, interfaz, dirección manual, resumen y «Usar
este destino». Cambiar la fila seleccionada no guarda, conecta ni descarga nada.
Aceptar persiste la configuración; cancelar conserva exactamente la anterior.

La lista distingue «detectado», «configurado manualmente», «no disponible» y
«verificación pendiente». Los datos desconocidos se muestran como tales. La CPU
de la plantilla no se rotula como CPU leída del equipo. No se deduce RUN de una
descarga satisfactoria o de un ping.

## Configuración y encaminamiento

Un modelo de destino validado mantiene tipo, nombre descriptivo, instancia,
interfaz PG/PC, número de interfaz si es necesario, puerto y dirección explícita.
Nombre descriptivo y endpoint tienen funciones distintas. Se rechazan valores
ambiguos, IP inválida y dispositivos no seleccionados.

Se conservan las claves existentes y se añaden campos opcionales para direccionar.
Las configuraciones históricas sin dirección explícita conservan su ruta actual.
La selección nueva de una instancia cuya dirección no se pueda leer no se publica
como lista para descarga; se informa de la limitación y se mantiene el destino
anterior hasta completar su configuración.

La configuración de la instancia Runtime y el destino de descarga Normal se
actualizan juntos con escritura atómica, bajo una exclusión de operaciones.
Ninguna operación en curso puede cambiar de destino a mitad de una ejecución.

El puente recibe y reporta la dirección elegida y la interfaz realmente resuelta.
Se prueba la sobrecarga V18 con dirección usando una copia y PLCSIM, antes de
utilizarla en la GUI. Si no se demuestra encaminamiento correcto, no se habilita
el nuevo camino de descarga y se conserva el mecanismo histórico.

El cambio de destino elimina la autorización y el estado de disponibilidad de
descarga del destino anterior. Se comprueba de nuevo proyecto, paquete, mapa y
conexión antes de habilitar la carga. Esto no exige llamar otra vez al LLM: puede
revalidarse o recompilarse exactamente el paquete existente. Cambiar la plantilla
sí exige una compilación correspondiente a ese proyecto.

Un S7-1200 requiere su plantilla compatible. El selector no modifica CPU, módulos,
red de Windows, IP del PLC, protecciones ni configuración de hardware.

## Estado y capacidades por destino

Para PLCSIM se consulta la instancia elegida y se conserva su lectura real de
estado/IP; no se toma la primera instancia registrada ni se conserva el nombre
`TESIS_PLC_SIM` como destino obligatorio.

Para hardware se utiliza únicamente diagnóstico que V18 permita leer del endpoint
seleccionado. Si solo hay configuración, la GUI indica «configurado, sin verificar».
Si no se obtiene identidad suficiente, indica «compatibilidad no verificada» y no
habilita descarga automática. La descarga manual conserva la confirmación física
existente y las validaciones del proveedor de descarga de TIA.

Las pruebas de IO y la puesta en marcha PID de la aplicación siguen limitadas a
sus capacidades actuales en PLCSIM. Elegir un PLC físico no habilita escrituras
Runtime, sintonización o lectura RUN mediante la API del simulador. No se afirma
validación física sin disponer del equipo.

Experimentación mantiene su MASTER, mapas, destinos controlados y guardas de
simulación. El selector Normal no escribe `download_targets.experiment` ni permite
descargar ensayos a hardware. El motor de interpretación y generación no cambia.

## Limpieza concreta de controles

Se elimina la repetición de controles; las funciones útiles conservan una entrada
clara en su ventana correspondiente. No se borran datos ni métodos usados por
pruebas o por el flujo experimental.

| Control actual | Resultado propuesto |
| --- | --- |
| Plataforma objetivo, selector deshabilitado con un valor | Etiqueta «Siemens TIA V18» |
| Parser y botones API/Probar conexión en el lateral | Preferencias; modo activo visible como resumen; valor actual conservado |
| Configurar TIA V18 | Acceso desde el diálogo de destino; MASTER accesible desde Experimentación |
| Abrir mapa I/O, Guardar mapa I/O, Agregar variable, Editar variable, Bloquear variable, Desbloquear variable, Eliminar variable y Marcar como libre | Se retiran estos ocho botones del lateral; acciones disponibles en el mapa completo |
| Nuevo/guardar como/eliminar/validar mapa y sincronización/importación TIA | Menús del gestor de mapas; mismas validaciones y confirmaciones |
| Tabla de IO lateral más tabla completa | Resumen lateral del mapa y un botón «Gestionar mapa IO»; edición en una única ventana |
| Archivar/Limpiar códigos | Herramientas avanzadas, con las confirmaciones existentes |
| EJECUTAR COMANDO | «Generar y compilar», acción principal |
| EJECUTAR Y CARGAR AL PLC | Se conserva visible: interpreta el comando, genera, verifica, compila y carga el programa de esa ejecución si todas las etapas pasan |
| CARGAR PROGRAMA AL PLC | Se conserva y depende del paquete válido y el destino actual |
| CAPTURAR Y EJECUTAR POR VOZ | «Ejecutar por voz»; se conserva el flujo automático y su opción de carga |
| Grabar y Detener/transcribir manuales | Herramientas de voz para revisar/editar una transcripción; ejecución experimental conservada |
| Cancelar captura siempre visible y deshabilitado | Visible durante la captura que puede cancelar |
| Actualizar micrófonos | Dentro de las herramientas de voz; selector y micrófono actual visibles |
| PRUEBA DE I/O | Herramientas avanzadas; solo habilitada con sus requisitos reales |
| Puesta en marcha PID siempre visible | Acceso contextual cuando hay un paquete PID; disponible desde herramientas avanzadas |
| Procesar/Generar paquete/Diagnosticar/Importar y compilar último paquete | Herramientas avanzadas; no compiten con el flujo principal |
| GENERAR SOLO (DEVELOPMENT/DEBUG) duplicado | Se retira el duplicado; GENERAR ENSAYO mantiene su semántica actual |
| Lotes TEXT, VOICE_CLEAN, VOICE_NOISE, corpus, Oracles, evaluación, resultados | Se conservan en Experimentación |
| Historial y exportación | Se conservan |

El editor completo incorpora cualquier acción de biblioteca que todavía no tenga,
antes de retirar su acceso lateral. Los estados LOCKED/FREE, escalas analógicas,
unidades, señales de proceso y restricciones de ensayo se preservan. No se duplica
la lógica de persistencia. Selección y edición usan la fila de esa ventana, no una
fila antigua de la tabla lateral.

Las cuatro acciones operativas visibles son «Generar y compilar», «Ejecutar y
cargar al PLC», «Cargar programa al PLC» y «Ejecutar por voz». Las dos primeras
tienen propósitos distintos: la primera permite revisar antes de cargar; la
segunda completa el recorrido en un clic. La carga independiente permite cargar
un paquete ya compilado sin reinterpretar el comando.

## Componentes y límites

- GUI: diálogo de destino, panel de estado, preferencias y reubicación de controles.
- Configuración: modelo validado, migración compatible y actualización atómica.
- Puente Openness: enumeración de interfaces, capacidades y dirección de descarga.
- Puente Runtime: enumeración/lectura de instancias sin crearlas, iniciarlas o pararlas.
- Coordinación de operaciones: identidad de destino capturada al comenzar, sin
  permitir cambios durante generación, compilación, IO, PID o descarga.

El plan decidirá archivos y funciones concretas después de aprobar este contrato.
No incluye cambiar el LLM, resolver los 19 REVIEW, congelar una versión, ejecutar
FORMAL, instalar controladores/SDK, crear PLC virtuales adicionales ni descargar a
un PLC físico durante el desarrollo.

## Verificación de aceptación

1. Abrir y cancelar el diálogo deja configuración, mapa y paquete intactos.
2. Cero, una y varias instancias se representan sin inventar selección. La lista
   procede del proveedor; no contiene valores de prueba en ejecución normal.
3. La instancia y dirección elegidas llegan a estado, confirmación y petición de
   descarga. Un endpoint distinto nunca hereda un estado RUN o verificado anterior.
4. La configuración actual de TESIS_PLC_SIM sigue funcionando sin migración manual.
5. Las pruebas de dirección V18 identifican la interfaz y endpoint de la petición;
   cuando haya más de una instancia disponible, se verifica ausencia de ambigüedad.
   Si solo existe una, esa limitación se registra y no se afirma validación multi-PLC.
6. Un perfil físico se puede configurar desde la GUI sin modificar red o hardware;
   la ausencia de diagnóstico no se muestra como conexión ni compatibilidad probada.
7. Cambiar CPU/proyecto o mapa invalida la disponibilidad de la compilación anterior
   según sus contratos. Ningún flujo manual o por voz omite las guardas vigentes.
8. Todas las acciones retiradas del lateral que deban conservarse son accesibles
   en su nueva ubicación, incluidas la creación de un mapa vacío y las analógicas.
9. Texto, voz, PID y experimentación conservan su funcionalidad. No hay nueva
   llamada a la API como efecto de abrir, buscar o aceptar un destino.
10. Se realizan pruebas focalizadas y la suite completa; se comparan hashes de
    mapas, configuración protegida, resultados, Oracles e índice de la carpeta
    principal antes de integrar. La comprobación visual cubre textos completos,
    orden de tabulación y ventanas a la resolución actual y una más pequeña.
11. «Ejecutar y cargar al PLC» permanece visible y conserva el recorrido completo
    del comando actual. Una aclaración pendiente o un fallo en generación,
    verificación o compilación impide la descarga; nunca se sustituye el paquete
    fallido por uno anterior. El destino seleccionado se conserva durante el flujo.

La prueba de descarga disponible se limita a PLCSIM y requiere comprobar que el
destino seleccionado es virtual. La futura validación física constituye evidencia
separada y no se reemplaza con una prueba del simulador.
