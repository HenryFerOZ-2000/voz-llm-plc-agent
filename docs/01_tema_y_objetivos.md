# 01 Tema y Objetivos

> Documento del MVP inicial, conservado como antecedente. Desde el 20 de octubre de 2026,
> el alcance de evaluación para sustentación es texto/voz → LLM → SCL → TIA → PLCSIM,
> exclusivamente discreto. Consultar la [campaña vigente](31_campana_discreta_tesis.md).
> Las limitaciones de texto, voz y despliegue descritas abajo corresponden al MVP histórico.

## Tema del trabajo de titulación

**Desarrollo de una arquitectura de programación automática de PLC mediante comandos de voz y modelos de lenguaje (LLM) para sistemas de automatización industrial.**

## Descripción breve del problema

La programación de controladores lógicos programables en entornos industriales exige conocimiento técnico, precisión en el uso de señales y validación rigurosa de la lógica de control. Este proceso suele ser manual, consume tiempo y depende fuertemente de la experiencia del programador.

El problema central que aborda esta tesis es cómo diseñar una arquitectura capaz de transformar instrucciones expresadas en lenguaje natural, y posteriormente en comandos de voz, en lógica PLC estructurada, verificable y segura.

## Objetivo general del sistema

Diseñar e implementar una arquitectura modular que permita interpretar instrucciones operativas en lenguaje natural, convertirlas a una representación estructurada de intención y generar código PLC en Structured Text, aplicando reglas de seguridad y control sobre variables autorizadas.

## Objetivos técnicos del MVP actual

- recibir comandos escritos en lenguaje natural,
- identificar la intención de control industrial,
- estructurar la intención en formato JSON,
- generar código ST a partir de plantillas,
- verificar reglas básicas de sintaxis y seguridad,
- guardar el código generado y su evidencia de ejecución.

## Alcance actual del MVP

El estado actual del proyecto corresponde a un MVP local que ejecuta el flujo:

`Texto -> interpretación semántica -> JSON estructurado -> generación ST -> verificación -> guardado`

El prototipo actual:

- trabaja únicamente con texto,
- no integra aún reconocimiento automático de voz,
- no utiliza todavía un LLM real,
- no se conecta con PLC físicos,
- no despliega código directamente a CODESYS ni Siemens,
- mantiene trazabilidad mediante archivos `.st` y logs `.json`.

## Relación con comandos de voz, LLM y programación automática de PLC

La arquitectura propuesta está pensada para evolucionar en tres capas:

1. **Comandos de voz**  
   En una etapa posterior, la entrada textual será sustituida o complementada por ASR para convertir voz a texto.

2. **Modelos de lenguaje (LLM)**  
   El parser por reglas del MVP funciona como una base controlada. Más adelante podrá ser reemplazado o reforzado por un LLM para ampliar la cobertura semántica.

3. **Programación automática de PLC**  
   El objetivo final no es solo interpretar lenguaje, sino traducirlo a lógica de control formal, verificable y compatible con plataformas industriales.

## Aporte del MVP a la tesis

El MVP actual demuestra la viabilidad inicial de la arquitectura porque ya implementa:

- separación entre comprensión del comando y generación de código,
- restricción por lista blanca de señales,
- verificación previa al uso del código generado,
- almacenamiento de evidencia útil para análisis experimental y redacción académica.
