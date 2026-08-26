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
11. `07_registro_pruebas.md`
12. `17_copias_de_seguridad.md`
13. `CHANGELOG_TESIS.md`

## Criterio de uso en tesis

La documentacion se organiza para cubrir tres necesidades complementarias:

- justificar el problema y la arquitectura propuesta,
- evidenciar tecnicamente el desarrollo incremental del software,
- registrar decisiones, pruebas y resultados con trazabilidad.
