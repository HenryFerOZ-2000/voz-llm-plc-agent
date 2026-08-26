# Notas de tesis

Este proyecto implementa un prototipo base para la tesis:

**Arquitectura para la Programación Automática de Controladores Lógicos Programables mediante Comandos de Voz y Modelos de Lenguaje Largo Aplicada a Sistemas de Automatización Industrial**

## Propósito del prototipo

El prototipo busca demostrar la viabilidad de una arquitectura modular donde una entrada en lenguaje natural pueda transformarse en una intención formal de control industrial y posteriormente en código Structured Text verificable.

## Alcance del MVP

En esta fase se limita el alcance a comandos escritos. La cadena funcional incluye:

- entrada textual,
- interpretación semántica,
- representación estructurada,
- generación de código PLC,
- verificación básica de seguridad,
- trazabilidad de resultados.

## Valor académico

El MVP permite justificar técnicamente:

- la separación entre comprensión semántica y síntesis de código,
- el uso de catálogos de intención y mapas de I/O como mecanismos de control,
- la necesidad de un verificador de seguridad previo a la aceptación del código,
- una ruta incremental para integrar voz y LLMs reales en etapas posteriores.

## Línea de evolución sugerida

1. Sustituir el parser por reglas por un LLM controlado con prompts.
2. Añadir ASR para entrada por voz.
3. Incorporar pruebas automáticas por intención.
4. Ejecutar validación en simuladores industriales.
5. Comparar calidad, tiempo y seguridad frente a programación manual.
