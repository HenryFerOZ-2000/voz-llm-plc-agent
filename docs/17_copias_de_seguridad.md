# 17 Copias de Seguridad (Git Tags)

## Proposito

Este documento lleva el registro de los puntos de restauracion (`git tag`) creados sobre el repositorio `voz_llm_plc_agent`. Cada copia de seguridad es un tag anotado que apunta a un commit especifico, subido tanto al repositorio local como a GitHub (`https://github.com/HenryFerOZ-2000/voz-llm-plc-agent`).

## Convencion de nombres

`backup-AAAA-MM-DD-descripcion-corta`

## Como volver a una version guardada

Opcion recomendada: crear una rama nueva desde el tag, sin tocar `main` ni el trabajo actual.

```powershell
git checkout -b recuperacion <nombre-del-tag>
```

Por ejemplo, para volver al primer backup:

```powershell
git checkout -b recuperacion backup-2026-08-26-initial
```

Esto deja el codigo de ese punto disponible en la rama `recuperacion` para revisar o copiar archivos, sin perder el trabajo hecho despues en `main`.

### Alternativa destructiva

Solo si se quiere descartar por completo todo lo hecho despues del backup:

```powershell
git reset --hard <nombre-del-tag>
```

Esto reescribe `main` al estado exacto del tag y borra los cambios posteriores no guardados en otra rama.

## Ver diferencias antes de decidir

```powershell
git diff <nombre-del-tag>
```

## Listar todos los backups disponibles

```powershell
git tag -l -n99
```

## Registro de copias de seguridad

| Tag | Fecha | Commit | Descripcion |
|---|---|---|---|
| `backup-2026-08-26-initial` | 2026-08-26 | `2be72ef378cdfd0d6e05960f6bb18aaef57c70ee` | Commit inicial subido a GitHub. Incluye parser reglas/LLM/hibrido, validacion semantica con io_map, generacion IEC 61131-3, integracion TIA Portal Openness V18 con compilacion `TIA_COMPILATION_PASSED` verificada. |
| `backup-2026-08-26-mapa-maestro-plc` | 2026-08-26 | `981d4a1ba24b0b5b51f05f2788e809448990644e` | Mapa Maestro PLC: biblioteca de mapas versionados (`src/plc_maps/`), metadata semantica por variable, resolucion de alias, gate `llm_allowed`, y acciones nuevas `sync_map`/`read_tags` en el puente C# (conservadoras, sin tocar `import_compile`/`diagnose`). 63 pruebas pasando. |
| `backup-2026-08-28-modo-experimentacion` | 2026-08-28 | `da1c760d969649bd04fc70dd5099919354076b78` | Modo Experimentacion: "Caso experimental" como selector principal (perfil D01-D20 auto-vinculado, ya no se elige perfil a mano), variantes V1-V3 desde `data/plc_maps/experiment_variants.json`, `experiment_label`/repeticion calculada consultando `experimental_results.json` (sin contador aparte), y panel central de la GUI convertido a `CTkScrollableFrame`. 92 pruebas pasando. |
