# Campaña final de la tesis

Identificador: `THESIS_DISCRETE_LLM_180_20261026_R2`. La unidad es caso–variante–modalidad: veinte casos, tres variantes y tres modalidades, para 180 observaciones principales. El procesamiento por lotes es la automatización de esas observaciones.

La matriz principal contiene 165 PASS, siete FAIL y ocho REVIEW. Compilaron 174 programas: 58 de texto, 59 de voz limpia y 57 de voz con ruido. Cada modalidad conserva 55/60 PASS. Los resultados REVIEW permanecen separados; no se convierten en éxitos o fallos por conveniencia.

## Contenido

- `matriz_180_celdas.json` y `.csv`: selección final por celda, resultados por etapa, transcripciones, errores de palabras, duraciones y procedencia.
- `trials/<trial_id>/`: 180 registros originales `trial.json`, 176 programas SCL y sus asignaciones, 174 informes de evaluación con trazas y 120 registros originales ASR. Las etapas detenidas no tienen artefactos de etapas que no llegaron a ejecutarse.
- `Oracles/`: veinte plantillas JSON fijadas para los casos D01–D20.
- [`corpus/`](corpus/README.md): 60 grabaciones limpias y 60 versiones con ruido, con enlaces por caso y variante e índice de huellas y correspondencia con los ensayos.
- `prompt_semantico.txt`, `mapa_comun_8x8.json`, `llm_config_efectiva.json`, `parser_settings.json` e `identificacion_modelos.json`: contexto y configuración de la campaña.
- `software_frozen/`: copia del código y los recursos conservados antes de la campaña. Sus archivos de código se contrastaron con las huellas del protocolo. Esta copia se distingue de la aplicación en desarrollo de la raíz del repositorio.
- `estadistica.json` y los CSV asociados: resultados consolidados. `recalcular.py` reproduce conteos, WER agregado, Wilson y comparaciones pareadas a partir de los registros tabulares.
- `Preliminar/` y `comparar_campanas.py`: comparación complementaria entre versiones. La matriz preliminar no se mezcla con las 180 observaciones finales.
- `Auditoria/`: protocolo previo, rectificación documentada de D14–V3 textual y conservación del reintento improcedente excluido. Se conserva el primer fallo, sin sustituirlo por el PASS del reintento.
- `manifest_publication.json`: rutas y SHA-256 de los archivos distribuidos. `audit_publication.json` documenta el alcance de la búsqueda local de secretos, sin valores sensibles.

## Recalcular los resultados

Con Python y su biblioteca estándar, desde cualquier directorio:

```text
python data/thesis_campaigns/THESIS_DISCRETE_LLM_180_20261026_R2/recalcular.py
python data/thesis_campaigns/THESIS_DISCRETE_LLM_180_20261026_R2/comparar_campanas.py
```

Estos scripts leen los datos archivados; no llaman al ASR, al LLM ni a un PLC. El programa de la arquitectura requiere además sus dependencias y el entorno Siemens descrito en el artículo. La configuración conserva los identificadores solicitados a los servicios; no acredita una instantánea inmutable del modelo servido.

## Alcance de los registros

Los archivos originales conservan rutas del equipo del investigador, identificadores de fase y referencias a sus ubicaciones de captura y proyectos. Esas rutas son procedencia histórica, no rutas que deban existir en un clon. Los WAV distribuidos están en `corpus/`; `corpus/index.json` los enlaza con sus referencias y transcripciones originales. Los datos tabulares y las transcripciones permiten recalcular las estadísticas sin invocar nuevamente los servicios.

El primer autor y locutor autorizó compartir las grabaciones de comandos y sus derivados pareados. Se incluyen los 120 WAV originales de esas condiciones; no se incluyen el ruido maestro, credenciales ni proyectos binarios TIA. Los manifiestos acústicos conservan formato, pareamiento, SNR y huellas. En cuatro ensayos detenidos antes de la integración, el resultado terminal está en `final_status`, mientras `final_verdict` está vacío. La matriz final y la auditoría documentan esa conciliación.

Las expectativas del Oracle permanecen separadas del generador. Su revisión de contenido fue la revisión manual declarada por el investigador; la publicación de las plantillas no equivale a validación independiente ni certificación de seguridad industrial.
