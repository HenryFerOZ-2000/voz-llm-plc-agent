# Proyecto completo para reimportar en Overleaf

El usuario autorizó volver a subir imágenes y pidió un ZIP completo. La entrega más reciente es `output/articulo_overleaf_actualizado_20261027.zip`, con `articulo_CEP_voz_LLM_PLC.tex` como único archivo LaTeX principal en la raíz.

Parte del fuente corregido de `output/correcciones_articulo_20261027/`; conserva su texto, encabezados españoles, comparación preliminar indicativa, clasificación D14, resultados principales y pendientes. La única modificación del cuerpo del fuente es sustituir el bloque de máscara de Figura 1 por una inclusión normal de la nueva imagen `Graficos/arquitectura_voz_llm_plc.png`. Esa figura se regeneró desde código, con LLM explícito y sin la nota errónea de respaldo. Las otras seis imágenes principales se conservaron.

El proyecto incluye bibliografía, los tres archivos CAS, PDF de vista previa y suplemento. Se añadieron la matriz preliminar original, el cálculo portable de acuerdo entre campañas y evidencia de la rectificación D14. La campaña principal sigue conteniendo exclusivamente 180 comandos de la versión final (165 PASS, 7 FAIL, 8 REVIEW). Los datos preliminares no se suman al denominador ni sustituyen observaciones.

Los scripts de ensamblado, diagrama, compilación y verificación se encuentran en `runtime/paquete_overleaf_20261027/`. La compilación fue satisfactoria y las rutas de siete imágenes y las 31 claves bibliográficas quedaron resueltas. Se inspeccionaron las páginas renderizadas y la Figura 1 regenerada. El ZIP se verifica por CRC y por huellas SHA-256 de sus archivos.

No se modificó el proyecto externo del tutor ni los registros experimentales. El usuario importará el ZIP y seleccionará `articulo_CEP_voz_LLM_PLC.tex` como documento principal.
