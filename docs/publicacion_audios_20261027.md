# Incorporación del corpus de voz

El primer autor, identificado como locutor S01 en el estudio, solicitó incluir en el repositorio las grabaciones de los comandos. Esta actualización incorpora las 60 locuciones limpias y los 60 derivados con ruido que se utilizaron en la campaña final; no se capturaron ni transcribieron audios nuevos.

Ruta: `data/thesis_campaigns/THESIS_DISCRETE_LLM_180_20261026_R2/corpus/`.

`README.md` enlaza los archivos por caso, variante y condición. `index.json` relaciona cada archivo con su referencia, ensayo, registro ASR, formato, duración y SHA-256. `validar.py` verifica las huellas contra los registros originales, el formato PCM16 mono a 16 kHz, el pareamiento y el SNR recalculado desde las muestras.

La excepción en `.gitignore` está limitada a los WAV de esta carpeta de campaña. Los demás audios locales, los ZIP de Overleaf, las credenciales y los proyectos binarios TIA continúan excluidos. El ruido maestro no se incorpora en esta actualización.

La publicación añade un archivo documental separado de los directorios que utiliza la aplicación. No cambia el código activo, la configuración, los prompts operativos, los Oracles utilizados, los resultados ni el artículo. La visibilidad del repositorio no se cambia; el acceso de terceros depende de ella.
