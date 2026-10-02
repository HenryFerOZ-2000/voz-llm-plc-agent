"""
MODO NORMAL — interaccion centrada en el SIGNIFICADO FUNCIONAL del comando.

El usuario final nunca gestiona intenciones, catalogo, INT_UNKNOWN, schema ni modo de parser:

  * politica para el LLM (solo Modo Normal): componer comportamientos con primitivas genericas
    (timed_sequence, never_together, motor_start_latch, interlock, ...) en vez de exigir una
    intencion monolitica; preguntar SOLO datos funcionales indispensables, de a UNO;
  * aclaraciones: estructuradas {original_command, [{question, answer}]}, nunca concatenadas;
    una pregunta ya respondida no se repite;
  * filtro: cualquier pregunta/mensaje con detalles internos (catalogo, intencion, schema, parser)
    nunca llega al usuario -> SYSTEM_CAPABILITY_GAP en el log + mensaje de producto.

Experimentacion NO usa este modulo (su comportamiento queda congelado).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

PROFILE_NORMAL = "normal"
SYSTEM_CAPABILITY_GAP = "SYSTEM_CAPABILITY_GAP"
PRODUCT_CAPABILITY_GAP_MESSAGE = (
    "No puedo generar todavía este comportamiento porque requiere una capacidad de control que aún "
    "no está implementada. Puedes describirlo de otra forma o dividirlo en pasos más simples."
)

# Senales de detalle INTERNO de la arquitectura: nunca en un dialogo dirigido al usuario.
_INTERNAL_PATTERNS = [
    r"\bINT_[A-Z_]+", r"\bintenci[oó]n(es)?\b", r"\bintent(_id|s)?\b", r"\bcat[aá]logo\b", r"\bschema\b",
    r"\besquema\b", r"\bparser\b", r"\bplantilla(s)?\b", r"\btemplate(s)?\b", r"\bfunctional_requirements?\b",
    r"\bautorizad[ao]s?\b.*\b(intenci|cat[aá]logo)", r"\brequires_clarification\b", r"\bINT_UNKNOWN\b",
]
_INTERNAL_RE = re.compile("|".join(_INTERNAL_PATTERNS), re.IGNORECASE)

NORMAL_MODE_POLICY = """POLITICA DE MODO NORMAL (prevalece sobre las reglas generales del prompt cuando entren en conflicto):

1. Trabaja desde el SIGNIFICADO FUNCIONAL del comando. Las intenciones del catalogo se usan cuando
   encajan, pero NO son una lista cerrada de maquinas posibles. Si ninguna intencion representa el
   comando completo, usa intent_id = "INT_UNKNOWN" y describe el programa COMPLETO mediante primitivas
   componibles en functional_requirements. NUNCA pidas aclaracion porque "el catalogo no contiene una
   intencion", NUNCA propongas crear/autorizar una intencion, y NUNCA menciones intenciones, catalogo,
   schema, plantillas ni modo de parser en clarification_question.

2. Primitivas componibles adicionales (ademas del catalogo de functional_requirements):
   - "timed_sequence": secuencia de etapas excluyentes iniciada por un pulsador:
       {"type": "timed_sequence", "start_input": "I_...", "stop_input": "I_...",
        "steps": [{"outputs": ["Q_..."], "duration": "T#..."}, ..., {"outputs": ["Q_..."]}]}
     Cada etapa enumera TODAS las salidas activas durante ella. Toda etapa salvo la ultima lleva
     "duration" (IEC TIME). La ultima etapa se mantiene hasta Stop. Stop apaga todo.
   - "never_together": invariante de seguridad {"type": "never_together", "outputs": ["Q_a", "Q_b"]}:
     esas salidas nunca pueden estar activas simultaneamente.
   Ejemplo (arranque escalonado generico): etapa 1 = salidas A y B durante T, etapa 2 = salidas A y C;
   si B y C no deben coincidir agrega never_together [B, C].
   Infiere de la descripcion funcional las salidas que el comportamiento necesita (p. ej. el numero de
   contactores de un metodo de arranque conocido): no preguntes por ellas. Propon nombres funcionales
   claros (Q_..., I_...) o reutiliza los existentes; el IOAllocator asigna los canales.
   Primitivas que se combinan con timed_sequence en el mismo programa:
   - "automatic_mode" {"mode_input": "I_..."} y "manual_mode" {"mode_input": "I_...", "commands": [
       {"input": "I_...", "output": "Q_...", "behavior": "maintained"|"latched", "enable_condition": "Q_..."}]}:
     modos excluyentes; cada orden manual maneja UNA salida (maintained = solo mientras la orden esta
     presente; latched = enclavada hasta Stop). enable_condition es un permisivo opcional.
     En timed_sequence, "mode_condition": "M_AutoMode" limita la secuencia al modo Automatico.
   - "sensor_timeout_alarm" {"sensor_input": "I_...", "timeout": "T#...", "start_condition": "I_... AND M_...",
       "affected_outputs": ["Q_..."], "alarm_output": "Q_..."}: si el sensor no cambia de estado dentro del
     tiempo tras el arranque, detiene esas salidas y enclava la alarma; requiere "reset_behavior"
     {"reset_input": "I_..."} para reiniciarla.
   Las condiciones (mode_condition, enable_condition, start_condition) son solo tags con AND/OR/NOT.
   TODO recurso (entrada o salida) de una primitiva lleva su nombre funcional como texto ("I_...",
   "Q_..."): nunca lo dejes vacio ni lo describas solo con un rol.

3. Aclaraciones: pregunta SOLO un dato funcional indispensable que falte (p. ej. un tiempo que el
   comando no indica), UNA pregunta por vez, en lenguaje del proceso. Si "clarification_history" trae
   respuestas, incorporalas y NO vuelvas a preguntar lo ya respondido. Si para producir el programa
   tendrias que asumir un dato de seguridad no indicado (p. ej. un tiempo muerto entre etapas), no lo
   inventes: omitelo si no es indispensable, o pregunta por el.
"""


def normalize_question(text: str | None) -> str:
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii").lower()
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text).split())


def is_internal_message(text: str | None) -> bool:
    """True si el texto expone detalles internos (catalogo, intencion, schema, parser...)."""
    return bool(text) and bool(_INTERNAL_RE.search(str(text)))


def already_answered(question: str | None, history: list[dict[str, str]]) -> bool:
    target = normalize_question(question)
    if not target:
        return False
    for item in history:
        previous = normalize_question(item.get("question"))
        if previous and (previous == target or previous in target or target in previous):
            return True
    return False


def classify_clarification(question: str | None, history: list[dict[str, str]]) -> dict[str, Any]:
    """
    Decide que hacer con una aclaracion en Modo Normal:
      ask           -> pregunta funcional valida (mostrarla tal cual);
      capability_gap-> pregunta con detalles internos (no mostrar; mensaje de producto + log);
      repeated      -> ya respondida (no repetir; mensaje de producto + log).
    """
    if is_internal_message(question):
        return {"action": "capability_gap", "reason": f"{SYSTEM_CAPABILITY_GAP}: aclaracion interna suprimida: {question}"}
    if already_answered(question, history):
        return {"action": "repeated", "reason": f"{SYSTEM_CAPABILITY_GAP}: el interprete repitio una pregunta ya respondida: {question}"}
    return {"action": "ask", "reason": None}


def user_facing_errors(errors: list[str]) -> tuple[list[str], list[str]]:
    """(errores mostrables, errores internos que solo van al log)."""
    shown, internal = [], []
    for error in errors or []:
        (internal if is_internal_message(error) else shown).append(str(error))
    return shown, internal


def new_state(original_command: str) -> dict[str, Any]:
    return {"original_command": original_command, "history": []}


def rule_parser_text(original_command: str, history: list[dict[str, str]]) -> str:
    """Texto para el parser por reglas (no estructurado): comando original + respuestas, deterministico."""
    answers = " ".join(str(item.get("answer", "")).strip() for item in history if item.get("answer"))
    return f"{original_command} {answers}".strip()
