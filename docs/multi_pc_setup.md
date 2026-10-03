# Trabajo en dos PCs (DEV y EVAL)

El repositorio se sincroniza por Git (GitHub) entre dos PCs:

| PC | Rol | Uso típico |
|---|---|---|
| **PC 1, DEV** | desarrollo | cambiar código, correr la suite, hacer commit y push |
| **PC 2, EVAL** | evaluación | `git pull`, usar Modo Normal y ejecutar ensayos de Experimentación |

Por Git viaja solo lo **compartido y reproducible**: código, pruebas, benchmark, Oracles, diseño
experimental, mapas base y documentación curada. Lo que depende de cada PC (rutas, proyectos TIA,
claves, resultados) es **local** y nunca se versiona.

## 1. Qué viaja por Git

| Categoría | Rutas |
|---|---|
| Código y pruebas | `src/`, `tests/` (incluye `tests/fixtures/`), `scripts/`, `schemas/`, `prompts/`, `knowledge_base/` |
| Bridges C# (solo código) | `tia_openness_bridge/Program.cs`, `plcsim_runtime_bridge/Program.cs` |
| Benchmark y evaluación (congelados) | `data/experiment_cases/`, `data/experiment_oracles/` (32 Oracles FROZEN), `data/experiment_benchmark/`, `data/experimental_design.json` |
| Mapas PLC versionados | `data/plc_maps/mapa_banco_fisico_base.json`, `mapa_simulacion_completo.json`, `mapa_pid_simulacion.json`, `mapa_pid_banco_fisico.json`, `profiles.json`, `experiment_variants.json` |
| Configuración compartida | `config/intents_catalog.json`, `safety_rules.json`, `pid_supervisor_config.json`, `parser_settings.json`, `llm_config.json`, `io_map.json` |
| Plantillas de configuración local | `.env.example`, `config/*.example.json` |
| Documentación curada | `docs/` (incluido `07_registro_pruebas.md`, que ya no recibe escrituras automáticas) |
| Entorno | `requirements.txt`, `requirements-transfer.txt` |

## 2. Qué NO viaja por Git (local por PC)

| Archivo / carpeta | Qué es | Cómo se crea en una PC nueva |
|---|---|---|
| `.env` | clave OpenAI y modelos | copiar `.env.example` → `.env` y poner la clave (o "Configurar API LLM" en la GUI) |
| `config/tia_openness_config.json` | rutas del proyecto TIA Normal y de las DLL de Siemens | copiar `config/tia_openness_config.example.json` y luego "Configurar TIA V18" en la GUI |
| `config/tia_projects.json` | proyecto Normal y TIA MASTER (ruta, hash, validación, snapshot) | copiar `config/tia_projects.example.json`; seleccionar Normal y MASTER desde la GUI |
| `config/normal_voice.json` | preferencias del flujo de voz Normal | lo crea la GUI (plantilla: `normal_voice.example.json`) |
| `config/voice_protocol_dev.json` | perfil de ruido/SNR de DEVELOPMENT | lo crea la GUI (plantilla: `voice_protocol_dev.example.json`) |
| `config/host_local.json` | identificador opcional de la PC, p. ej. `{"host_id": "EVAL_PC"}` | copiar `host_local.example.json` y cambiar el `host_id` (sin hostname real ni datos personales) |
| `data/plc_maps/mapa_banco_fisico_working.json` | mapa del banco que usa y modifica Modo Normal | se crea solo, desde el base, la primera vez que se abre la aplicación |
| `data/plc_maps/_active_map.json` | mapa activo seleccionado en la GUI | lo crea la GUI |
| `tia_projects/`, `tia_master/`, `tiaw/` | proyectos TIA `.ap18`, snapshots `.zap18` del MASTER, workspaces por ensayo | transferencia única (sección 6) |
| `experiments/`, `results/`, `experimental_results/*.csv/.jsonl` | ensayos y resultados | quedan en la PC donde se ejecutaron; ver sección 6 |
| `runtime/development_log.md` | registro automático de ejecuciones | lo escribe la aplicación |
| `generated_code/` (salvo `.gitkeep`) | paquetes PLC generados e historial de la GUI | los genera la aplicación |
| `voice_evidence/`, `audio/`, `tmp_audio/` | audios | locales |
| `.venv/`, `__pycache__/`, `.pytest_cache/`, `.pytest_tmp/` | entorno y cachés | `python -m venv` + `pip install` |

## 3. Mapa del banco: base frente a working

| | `mapa_banco_fisico_base.json` | `mapa_banco_fisico_working.json` |
|---|---|---|
| Git | versionado | ignorado (local por PC) |
| Contenido | hardware real: 24 canales, direcciones y estados de referencia | copia de trabajo: asignaciones ASSIGNED/FREE, nombres y `history` de Modo Normal |
| Quién lo usa | **Experimentación**: el working map de cada ensayo se copia desde aquí; los hashes de integridad lo protegen | **Modo Normal**: IOAllocator, MAP_CONFIG, la tabla de I/O de la GUI y la sincronización con TIA |
| Quién lo escribe | nadie desde la aplicación; solo un cambio deliberado de hardware, con commit | la aplicación, siempre en esta PC |

- Ambos comparten `map_id = "mapa_banco_fisico"`, así que el mapa activo, los perfiles y los ensayos siguen funcionando igual.
- **Inicialización.** Si el working no existe, la aplicación lo crea al listar los mapas (`plc_maps.store.ensure_working_maps`). El origen es una copia exacta del base o, si en esa PC existe el antiguo `mapa_banco_fisico.json` local, ese archivo (para no perder sus asignaciones; después se renombra a `mapa_banco_fisico.json.pre_working.bak`). La trazabilidad queda en `metadata.working_copy`: origen, hash del origen y del base, fecha y `host_id`.
- **Experimentación** nunca lee el working: `plc_maps.registry.experiment_reference_map_path` sustituye el working por su base. Los mapas de simulación y PID no tienen base y se usan tal cual.
- **Cambio real de hardware** (cableado nuevo): editar `mapa_banco_fisico_base.json` a propósito, hacer commit y, en cada PC, borrar su working para que se regenere desde el nuevo base (se pierden las asignaciones locales de Modo Normal de esa PC).

> Migración realizada el 2026-10-02 en la PC DEV: `git mv mapa_banco_fisico.json → mapa_banco_fisico_base.json`
> (bytes idénticos, sha256 `3ac411f0…`). El working se inicializó desde ese base con las mismas
> 24 variables, el mismo `history` y los mismos metadatos, más el bloque `working_copy`.

## 4. Flujo diario

**PC 1 (DEV):**
```powershell
git pull
# trabajar...
.venv\Scripts\python.exe -m pytest -q tests
git add -A
git status            # revisar: no debe aparecer nada local (config/*.json reales, *_working.json, results/...)
git commit -m "..."
git push
```

**PC 2 (EVAL):**
```powershell
git pull
.venv\Scripts\python.exe scripts\check_environment.py
```

Si se cambian las dependencias: `.venv\Scripts\python.exe -m pip install -r requirements-transfer.txt`.

## 5. Configurar la PC 2 por primera vez

1. Instalar el software Siemens, que pip **no** instala:
   - TIA Portal V18, con el mismo Update que el proyecto;
   - TIA Portal Openness V18. Agregar el usuario de Windows al grupo **Siemens TIA Openness** y cerrar e iniciar sesión;
   - S7-PLCSIM Advanced V5.x (Runtime API);
   - .NET Framework 4.8 (`csc.exe` en `C:\Windows\Microsoft.NET\Framework64\v4.0.30319\`).
2. Instalar Python 3.13 (x64) y Git.
3. Clonar y crear el entorno:
   ```powershell
   git clone https://github.com/HenryFerOZ-2000/voz-llm-plc-agent.git
   cd voz-llm-plc-agent
   git checkout feature/pid-supervisory
   py -3.13 -m venv .venv
   .venv\Scripts\python.exe -m pip install -r requirements-transfer.txt
   ```
4. Crear la configuración local a partir de las plantillas:
   ```powershell
   Copy-Item .env.example .env                      # luego poner OPENAI_API_KEY
   Copy-Item config\tia_openness_config.example.json config\tia_openness_config.json
   Copy-Item config\tia_projects.example.json config\tia_projects.json
   Copy-Item config\host_local.example.json config\host_local.json   # cambiar host_id a "EVAL_PC"
   ```
5. Copiar los proyectos TIA (sección 6) y, en la GUI, seleccionar el **proyecto Normal** ("Configurar TIA V18") y el **TIA MASTER** (Experimentación), y validar el MASTER.
6. Comprobar el entorno: `.venv\Scripts\python.exe scripts\check_environment.py`. Todo debe quedar en OK; un WARN indica un paso pendiente.
7. Correr la suite: `.venv\Scripts\python.exe -m pytest -q tests`.

## 6. Transferencias únicas (fuera de Git)

Por USB, OneDrive o Drive; **nunca** por Git:

| Qué | Origen (PC 1) | Destino (PC 2) | Nota |
|---|---|---|---|
| Proyectos TIA | `tia_projects\` (carpetas completas del `.ap18`) | misma ruta relativa | copiar con TIA cerrado; o archivar (`.zap18`) desde TIA y desarchivar en la PC 2 |
| Snapshot del MASTER | no hace falta | — | se regenera al validar el MASTER en la PC 2 |
| `.env` / clave | no copiar el archivo | crear desde `.env.example` | introducir la clave a mano; nunca enviarla por chat ni por correo |
| Resultados existentes | `experiments\`, `results\`, `experimental_results\` | carpeta de respaldo o las mismas rutas | solo si se van a analizar en la PC 2; los ensayos nuevos se quedan en la PC que los ejecuta |
| Mapa working (opcional) | `data\plc_maps\mapa_banco_fisico_working.json` | misma ruta | solo si se quieren las mismas asignaciones de Modo Normal en ambas PCs |

## 7. Secretos

- `.env` está ignorado. `.env.example` (versionado) solo tiene los nombres de las variables, sin valores.
- Ninguna plantilla `config/*.example.json` contiene rutas absolutas ni claves (lo comprueba `tests/test_multi_pc_setup.py`).
- La auditoría del 2026-10-02 no encontró secretos en el historial remoto: no hubo que rotar claves.
