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
