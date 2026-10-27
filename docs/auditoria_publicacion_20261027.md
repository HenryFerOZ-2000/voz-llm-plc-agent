# Auditoría previa a publicar la evidencia de tesis

Repositorio: `https://github.com/HenryFerOZ-2000/voz-llm-plc-agent`.

La comprobación se realizó con el repositorio privado. No se cambió su visibilidad ni se modificó `articulo_CEP_voz_LLM_PLC.tex`. La declaración de disponibilidad pública queda condicionada a que los materiales sean accesibles públicamente.

## Búsqueda de secretos

Se actualizaron las referencias remotas y se revisaron los 142 commits disponibles en ramas, etiquetas y reflogs locales, con 1703 blobs distintos. Gitleaks 8.30.1, obtenido de su distribución oficial con SHA-256 verificado, analizó el historial completo y una extracción de los archivos versionados actuales. Ambos análisis terminaron sin detecciones. Se habilitó la redacción completa de valores y no se verificó ninguna credencial contra servicios externos.

La comprobación adicional incluyó prefijos de claves de API, tokens, claves privadas, credenciales en URL y asignaciones literales de contraseñas y secretos. También se buscaron archivos `.env`, variantes `.env.*` no destinadas a ejemplo y ficheros terminados en `.env`. No se encontraron archivos de entorno reales versionados.

Las coincidencias adicionales correspondieron a comprobaciones de configuración y a marcadores sintéticos de pruebas de ocultación de credenciales. No se encontraron credenciales reales en esas coincidencias. Sin reproducir sus valores, las ubicaciones inspeccionadas fueron:

| Archivo | Commit inspeccionado |
|---|---|
| `scripts/check_environment.py` | `cd1bb186faf7157a452a6f17c2b2c08e6aa696e7` |
| `tests/test_evaluation_persistence.py` | `cd1bb186faf7157a452a6f17c2b2c08e6aa696e7` |

Se auditó asimismo el conjunto de evidencia preparado para versionar, sin detecciones de Gitleaks ni de los patrones adicionales. La auditoría es una búsqueda local basada en reglas y revisión de coincidencias; no constituye una garantía absoluta contra todo formato posible de secreto. Su alcance exacto y el commit previo se conservan en `audit_publication.json` dentro del conjunto de datos.

## Materiales de la campaña

Los Oracles y prompts generales ya estaban versionados. Faltaban la selección final de registros y los cálculos asociados. Se incorporó una carpeta específica para evitar confundir los archivos generales de la aplicación con los utilizados por la campaña final:

`data/thesis_campaigns/THESIS_DISCRETE_LLM_180_20261026_R2/`

| Elemento | Ruta relativa a esa carpeta |
|---|---|
| Código conservado de la campaña | `software_frozen/src/`, con configuración y recursos asociados |
| Veinte Oracles D01–D20 | `Oracles/` |
| Prompt semántico completo | `prompt_semantico.txt` |
| Mapa I/O común | `mapa_comun_8x8.json` |
| Matriz final de 180 celdas | `matriz_180_celdas.json` y `.csv` |
| Registros originales disponibles por etapa | `trials/<trial_id>/` |
| Scripts estadísticos portables | `recalcular.py` y `comparar_campanas.py` |
| Protocolo y rectificación documentada | `Auditoria/` |
| Identidad e integridad de los archivos publicados | `manifest_publication.json` |

Se conservaron 180 `trial.json`, 176 programas SCL y 174 informes conductuales con sus trazas. Las 120 transcripciones originales se distribuyen en `trials/<trial_id>/asr/asr_result.json`; la ruta original se conserva como procedencia en el manifiesto. No se incluyen WAV, ruido maestro, credenciales, archivos ZIP ni proyectos binarios TIA.

Los archivos se copiaron sin modificar sus contenidos; el manifiesto registra sus SHA-256. La regla `data/thesis_campaigns/** -text` conserva esos bytes al pasar por Git, incluso entre Windows y otros sistemas. Los 126 archivos de código, esquemas, prompts y conocimiento congelados se contrastaron con las huellas del protocolo.

Ambos scripts de análisis terminaron correctamente, reproduciendo 165 PASS, siete FAIL y ocho REVIEW, el WER agregado y las comparaciones incluidas en el artículo. La matriz preliminar permanece separada y se utiliza únicamente para la comparación indicativa entre versiones.

Los registros preservan rutas locales y estados históricos. No todas las etapas producen archivos cuando el ensayo se detiene antes de ejecutarlas. Los scripts de recálculo funcionan con la biblioteca estándar de Python y no llaman a servicios de IA ni a controladores.
