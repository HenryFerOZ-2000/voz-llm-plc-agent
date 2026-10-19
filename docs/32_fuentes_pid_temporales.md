# Fuentes externas del PID generado

El puente utiliza una fuente externa temporal para generar los bloques PID.
Cada importación crea un nombre `VozNativePid_<identificador>.scl` y conserva
el objeto devuelto por TIA. Al terminar la generación se elimina únicamente
ese objeto, incluso si la generación falla. Si falla la eliminación, se
propaga el error y se aplica la recuperación de la operación Normal.

El archivo `siemens_source.scl` del paquete generado permanece como evidencia.
Eliminar el transporte temporal no elimina los bloques generados ni el
controlador tecnológico. La transición de PID a discreto sigue retirando
solamente la infraestructura PID cuyo inventario de propiedad fue verificado.

No se buscan ni eliminan fuentes por llamarse `native_pid.scl`. Ese nombre lo
utilizaban versiones anteriores, pero un operador también podría usarlo para
una fuente manual. Los archivos históricos requieren una revisión puntual;
la política nueva no los sobrescribe ni los adopta como propios.

La regresión del ciclo de vida ejecuta el código C# de producción con archivos
reales: generación correcta, fallo de creación, fallo de generación y fallo
de eliminación. Conserva una fuente manual llamada `native_pid.scl` y verifica
que los bloques producidos sobreviven a la retirada de la fuente temporal.

La prueba explícita en TIA se ejecuta sobre una copia archivada del proyecto
Normal: discreto → PID → discreto → PID. Incluye una fuente manual y el nombre
histórico para comprobar su conservación. No utiliza la API del LLM ni realiza
descargas al PLC. Sus resultados y los de la suite completa se conservan en
`runtime/native_source_cleanup` de la copia de trabajo de cierre.
