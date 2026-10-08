# 00 Indice de Documentacion

Este directorio concentra la documentacion tecnica y metodologica del proyecto `voz_llm_plc_agent`. Su objetivo es dejar evidencia del avance del software y servir como base organizada para la redaccion de la tesis.

## Estructura documental

- `00_indice_documentacion.md`
  Orienta la lectura general de la carpeta `docs/`.

- `01_tema_y_objetivos.md`
  Resume el tema de titulacion, el problema abordado y el alcance del MVP.

- `02_etapa1_requisitos.md`
  Documenta los requisitos funcionales y la arquitectura esperada del sistema.

- `03_paso1_casos_prueba.md`
  Registra los casos discretos de automatizacion usados como banco inicial de pruebas.

- `04_paso2_mapa_io.md`
  Explica el mapa I/O autorizado y su rol como lista blanca del sistema.

- `05_paso3_intenciones_json.md`
  Describe el catalogo de intenciones y el contrato JSON del parser.

- `06_mvp_funcional.md`
  Expone el funcionamiento actual del MVP, sus modulos y el flujo operativo.

- `07_registro_pruebas.md`
  Sirve como bitacora de pruebas y se actualiza automaticamente desde el software.

- `08_decisiones_tecnicas.md`
  Justifica las decisiones de diseno y seguridad adoptadas en el proyecto.

- `09_representacion_intermedia_plc.md`
  Explica la arquitectura de `PLCProjectIR` y la capa intermedia independiente de la plataforma.

- `10_generacion_de_pou_y_proyectos.md`
  Describe la generacion de POU, tarea y paquetes PLC para Siemens, OpenPLC y CODESYS.

- `16_integracion_tia_openness_v18.md`
  Documenta la conexion controlada con TIA Portal Openness V18.

- `18_mapa_maestro_plc.md`
  Explica la biblioteca de mapas PLC versionados, su metadata semantica y la sincronizacion con TIA.

- `19_perfiles_experimentales_d01_d20.md`
  Documenta MAPA_SIMULACION_COMPLETO, MAPA_BANCO_FISICO y los perfiles D01-D20 del banco discreto.

- `20_modo_experimentacion.md`
  Documenta el Modo Experimentacion de la GUI: condiciones C1-C4, captura automatica de ensayos y log maestro.

- `21_pid_supervisory_control.md`
  Documenta la supervision PID (P01-P12): intent unico + functional_requirements, MAPA_PID_SIMULACION/MAPA_PID_BANCO_FISICO, perfiles P01-P12 y por que el bloque PID nunca se redisena.

- `22_banco_fisico_direcciones.md`
  Documenta las direcciones fisicas reales del banco (%IX16.x/%QX8.x, canales analogicos %IW/%QW) y el soporte de recursos externos AI_/AO_.

- `23_io_allocator.md`
  Documenta el estado FREE/ASSIGNED/LOCKED por variable, el IOAllocator deterministico y los comandos de configuracion de mapa (MAP_CONFIG) en Modo Normal.

- `17_copias_de_seguridad.md`
  Registra los puntos de restauracion (`git tag`) del repositorio y como volver a ellos.

- `CHANGELOG_TESIS.md`
  Mantiene un registro cronologico de los avances del proyecto.

- `README_TESIS.md`
  Conserva el contexto general inicial y materiales de apoyo previos.

## Orden sugerido de lectura

1. `01_tema_y_objetivos.md`
2. `02_etapa1_requisitos.md`
3. `03_paso1_casos_prueba.md`
4. `04_paso2_mapa_io.md`
5. `05_paso3_intenciones_json.md`
6. `06_mvp_funcional.md`
7. `08_decisiones_tecnicas.md`
8. `09_representacion_intermedia_plc.md`
9. `10_generacion_de_pou_y_proyectos.md`
10. `16_integracion_tia_openness_v18.md`
11. `18_mapa_maestro_plc.md`
12. `19_perfiles_experimentales_d01_d20.md`
13. `20_modo_experimentacion.md`
14. `21_pid_supervisory_control.md`
15. `22_banco_fisico_direcciones.md`
16. `23_io_allocator.md`
17. `07_registro_pruebas.md`
18. `17_copias_de_seguridad.md`
19. `CHANGELOG_TESIS.md`
20. `development_validation_log.md`
21. `multi_pc_setup.md`
22. `text_batch_execution.md`
23. `24_semantica_efectiva.md`

## Criterio de uso en tesis

La documentacion se organiza para cubrir tres necesidades complementarias:

- justificar el problema y la arquitectura propuesta,
- evidenciar tecnicamente el desarrollo incremental del software,
- registrar decisiones, pruebas y resultados con trazabilidad.
