# 02 Etapa 1: Requisitos

## Propósito de la etapa

La Etapa 1 corresponde al análisis de requisitos funcionales y operativos del sistema propuesto. Esta etapa define qué componentes debe contener la arquitectura completa y qué responsabilidades cumple cada uno dentro del flujo de programación automática de PLC.

## Requisitos funcionales generales

- recibir instrucciones del usuario en lenguaje natural,
- transformar la entrada a una forma lingüística normalizada,
- identificar una intención de automatización industrial,
- convertir la intención a una estructura formal interoperable,
- generar lógica PLC en Structured Text,
- verificar restricciones sintácticas, semánticas y de seguridad,
- registrar resultados y artefactos de cada ejecución,
- evolucionar posteriormente hacia una interfaz por voz.

## Requisitos operativos generales

- ejecución local con Python,
- funcionamiento sin depender de hardware industrial en el MVP,
- trazabilidad de resultados por archivo,
- control de variables autorizadas,
- capacidad de ampliar el catálogo de intenciones,
- capacidad de sustituir componentes por modelos más avanzados en fases posteriores.

## Componentes de la arquitectura

| Componente | Función dentro de la arquitectura | Estado actual |
|---|---|---|
| Entrada por comando | Recibe la instrucción del usuario en texto. | Implementado |
| Reconocimiento de voz ASR | Convierte voz a texto antes del análisis semántico. | Pendiente |
| Normalización lingüística | Limpia, unifica y simplifica la forma del comando. | Implementado en el parser |
| Interpretación semántica | Clasifica la intención operativa del comando. | Implementado por reglas |
| Estructura formal JSON | Representa la intención y sus parámetros en formato estructurado. | Implementado |
| Generación de código ST mediante LLM/reglas | Produce lógica Structured Text a partir de la intención detectada. | Implementado con reglas y plantillas |
| Verificación sintáctica, semántica y de seguridad | Revisa tags, formato, condiciones críticas y coherencia mínima. | Implementado de forma básica |
| Simulación o ejecución PLC | Valida la lógica en un entorno industrial o simulador. | Pendiente |
| Registro de resultados | Guarda código, logs y evidencia documental. | Implementado |

## Flujo objetivo de la arquitectura completa

1. Captura del comando por voz o texto.
2. Conversión voz a texto mediante ASR.
3. Normalización lingüística de la instrucción.
4. Interpretación semántica de la intención.
5. Construcción de JSON formal.
6. Generación de código ST mediante reglas o LLM.
7. Verificación del resultado.
8. Simulación o despliegue controlado.
9. Registro del caso y sus evidencias.

## Estado actual del MVP frente a la arquitectura completa

El MVP se enfoca deliberadamente en el tramo central del sistema. Actualmente trabaja con texto y posterga la integración de voz para una fase posterior. Esta decisión reduce variables de implementación y permite validar primero:

- el diseño del catálogo de intenciones,
- el control del mapa de señales,
- la generación ST por plantillas,
- la verificación y trazabilidad del proceso.

## Justificación de iniciar con texto

La entrada textual permite comprobar la viabilidad de la arquitectura sin introducir todavía la complejidad del reconocimiento de voz, como:

- errores de transcripción,
- ruido ambiental,
- diferencias de pronunciación,
- dependencia de modelos ASR,
- propagación de errores entre etapas.

Por ello, la Etapa 1 considera la voz como un componente previsto, pero no obligatorio para demostrar el concepto funcional del MVP.
