# Preparación de la subida a GitHub — 27-10-2026

Destino: `origin`, repositorio `HenryFerOZ-2000/voz-llm-plc-agent`, rama de trabajo `feat/normal-mode-hardening`.

Se incluyen los cambios de interpretación LLM exclusiva, evidencia de audio anidada y reintentos técnicos acotados por lote; sus pruebas, la documentación del trabajo y el `.tex` revisado. Los ZIP de transferencia a Overleaf se conservan únicamente en el equipo local por indicación del autor. Las credenciales, los WAV, los registros nativos, los proyectos TIA y los volcados de fallos permanecen fuera de Git conforme a `.gitignore`.

La fuente del artículo conserva la huella SHA-256 `c1496ccb264f997ca888e13a1255de36159bba91088199e4f32dabeed407e573`. La preparación para GitHub no cambió sus resultados ni sus conclusiones.

## Verificación del código

La ejecución dirigida sobre los ocho módulos de pruebas relacionados con los cambios terminó con **140 aprobadas y dos omitidas**, sin fallos. Incluyó integridad de rutas de audio, reintentos, contrato del motor, campañas históricas y flujos de voz y texto.

Durante la comprobación se adelantó la validación de identidad de campaña respecto de la consulta al estado de la interfaz, conservando el rechazo de reintentos de campañas históricas. También se hizo explícita la política de respaldo en la prueba que evalúa esa capacidad: el caso de prueba puede habilitarla, mientras la configuración de la aplicación sigue desactivada. La prueba del clasificador histórico ahora utiliza una copia versionada en `tests/fixtures`, sin depender de una carpeta `runtime` ausente en un clon.

La suite global no se declara completamente aprobada: hubo cierres nativos de Tcl/Tk con `Windows fatal exception: access violation` durante la destrucción de widgets. Los registros completos de esos intentos y de la ejecución dirigida permanecen en `runtime/github_upload_20261027`, que es local. La prueba dirigida posterior verifica las correcciones descritas; no equivale a una ejecución global sin interrupciones.

Se revisaron los archivos preparados y los objetos de los commits locales pendientes de subir mediante una búsqueda de patrones de credenciales, sin detectar claves privadas ni tokens. `git diff --cached --check` no detectó errores de espacios. La publicación conserva la rama de trabajo y no implica una validación nueva de todos los componentes ni una aprobación para desplegar en hardware.
