# Conjunto principal con interpretación LLM exclusiva

Autorizado el26-10-2026: repetir D11–V1/V2 TEXT y D06–V2/V3 VOICE_CLEAN, las cuatro celdas cuya ruta efectiva fue el respaldo por reglas. Mantener los176 registros ya interpretados mediante LLM y las nueve repeticiones D05 previamente incorporadas. El conjunto principal seguirá teniendo180 celdas, con las revisiones y fechas explícitas.

La selección completa se fija antes de ejecutar, independientemente del veredicto. Se conservan todos los registros anteriores, los audios originales y los Oracles. No se presenta la modificación como una campaña homogénea ejecutada desde el principio con respaldo desactivado. Se desactiva el respaldo en config/llm_config.json y config/parser_settings.json; las reglas de recursos y la emisión local IR/SCL siguen vigentes.

Los reintentos internos mantienen su configuración existente. Si falla infraestructura, la ejecución se pausa; se admite un reintento técnico documentado por celda después de corregir la causa, sin sustituir fallos funcionales. No se fuerza la etiqueta LLM a resultados producidos por reglas.

- [x] Guardar configuraciones anteriores, protocolo, entradas y hashes.
- [x] Probar el bloqueo del respaldo mediante error simulado sin red.
- [x] Ejecutar y verificar las cuatro repeticiones exclusivamente en PLCSIM.
- [x] Conciliar176 anteriores +4 nuevos, conservar selección previa y recalcular estadísticas.
- [x] Actualizar artículo/suplemento y comprobar fuentes, compilación y presentación.
