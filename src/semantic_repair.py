"""
Post-parse, pre-validation repair layer for `semantic_output["parameters"]`.

Problem this solves: the LLM sometimes understands a compound command correctly and already
reports every needed tag, but nests them under a DIFFERENT parameter shape than the fixed
canonical keys the chosen intent's codegen template reads (e.g. a list of per-motor
trigger/output pairs under "motor_controls" instead of the flat "trigger_input"/"motor_output"
INT_MOTOR_START_STOP's template expects). Rejecting that as "missing required parameters" is
wrong - the information IS present, just shaped differently. This module fills ONLY the specific
canonical keys a given intent's own required-parameter list (or, for INT_MUTUAL_INTERLOCK, its
codegen's own silently-defaulted keys) is missing, using values it can find UNAMBIGUOUSLY already
present somewhere in `parameters` - it never invents a tag, never fabricates a functional
requirement, and never overwrites a key the caller already set directly. It is a SHAPE
normalizer, not a semantic guesser: if the needed information genuinely is not present, it
changes nothing and the normal "missing parameters" validation error still fires afterward.

Deliberately narrow and table-driven rather than "smart": adding support for a new intent means
adding its base-slot keys to `_INTENT_EXTRA_BASE_SLOTS` below (or relying on
`INTENT_PARAMETER_RULES`, which already covers most of them) - never a bespoke branch per intent.
"""

from __future__ import annotations

from typing import Any

from io_allocator import IEC_NAME_PATTERN

# Keys this module knows how to fill - every other required key (stop_input, emergency_input,
# duration, preset, etc.) is a single, unambiguous concept the LLM rarely restructures, and is
# left for the normal validation error if genuinely absent.
_TRIGGER_KEY_ALIASES = ("trigger_input", "trigger", "input", "start_input")
_OUTPUT_KEY_ALIASES = ("motor_output", "output", "motor", "contactor")
_GENERAL_TRIGGER_KEY_ALIASES = ("trigger_input", "process_start_input", "process_enable_input", "start_input")
_KNOWN_BASE_SLOTS = {"trigger_input", "motor_output", "run_latch", "contactor_a", "contactor_b"}

# INT_MUTUAL_INTERLOCK has no entry in semantic_validator.INTENT_PARAMETER_RULES (so a shape
# mismatch never raises "missing parameters"), but its codegen (_generate_mutual_interlock_body)
# silently defaults trigger_input/contactor_a/contactor_b when absent - producing WRONG generated
# logic without ever failing validation. That silent-wrong-default is exactly the risk this module
# exists to close, so its base slots are listed explicitly here even though no "required" check
# would have caught them.
_INTENT_EXTRA_BASE_SLOTS: dict[str, set[str]] = {
    "INT_MUTUAL_INTERLOCK": {"trigger_input", "contactor_a", "contactor_b"}
}


def _first_str(source: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_actor_records(parameters: dict[str, Any]) -> list[dict[str, str | None]]:
    """
    Scans `parameters` for any nested list/dict shape that represents one trigger tag + one
    output tag per actor (the pattern LLM outputs commonly use for N independent motors -
    "motor_controls": [...], "motor_start_inputs": {...} - instead of the flat single-actor keys
    codegen reads). Returns records in the order the LLM listed them; the first actor found fills
    the base slots. Never invents a tag - every value returned here is copied verbatim from a
    string already present in `parameters`.
    """
    records: list[dict[str, str | None]] = []
    for key, value in parameters.items():
        if isinstance(value, list):
            for item in value:
                if not isinstance(item, dict):
                    continue
                trigger = _first_str(item, _TRIGGER_KEY_ALIASES)
                output = _first_str(item, _OUTPUT_KEY_ALIASES)
                if trigger or output:
                    records.append({"trigger": trigger, "output": output})
        elif isinstance(value, dict) and key not in _TRIGGER_KEY_ALIASES and key not in _OUTPUT_KEY_ALIASES:
            for sub_key, sub_value in value.items():
                if isinstance(sub_value, str):
                    # Forma "{output_tag: trigger_tag}" (p. ej. motor_start_inputs): solo se
                    # acepta si AMBOS lados ya parecen tags IEC validos - nunca se adivina que un
                    # nombre de clave arbitrario es un tag.
                    if IEC_NAME_PATTERN.match(sub_key) and IEC_NAME_PATTERN.match(sub_value):
                        records.append({"trigger": sub_value, "output": sub_key})
                elif isinstance(sub_value, dict):
                    trigger = _first_str(sub_value, _TRIGGER_KEY_ALIASES)
                    output = _first_str(sub_value, _OUTPUT_KEY_ALIASES)
                    if trigger or output:
                        records.append({"trigger": trigger, "output": output})
    return records


def repair_semantic_output(
    semantic_output: dict[str, Any],
    intent_parameter_rules: dict[str, Any]
) -> dict[str, Any]:
    """
    Returns `semantic_output` unchanged (same object) if nothing needed repairing (including
    every case where the needed data genuinely is not present - it never guesses); otherwise
    returns a shallow copy with a repaired `parameters` dict. Idempotent - running it twice, or on
    an output that already used the canonical shape, is a no-op the second time.
    """
    intent_id = str(semantic_output.get("intent_id", ""))
    required = set(intent_parameter_rules.get(intent_id, {}).get("required", []))
    required |= _INTENT_EXTRA_BASE_SLOTS.get(intent_id, set())
    parameters = semantic_output.get("parameters")
    if not isinstance(parameters, dict):
        return semantic_output

    missing = (required & _KNOWN_BASE_SLOTS) - set(parameters)
    if not missing:
        return semantic_output

    actor_records = _extract_actor_records(parameters)
    general_trigger = _first_str(parameters, _GENERAL_TRIGGER_KEY_ALIASES)
    repaired_parameters = dict(parameters)
    changed = False

    if "trigger_input" in missing:
        candidate = general_trigger or (actor_records[0]["trigger"] if actor_records else None)
        if candidate:
            repaired_parameters["trigger_input"] = candidate
            changed = True

    if "motor_output" in missing and actor_records and actor_records[0]["output"]:
        repaired_parameters["motor_output"] = actor_records[0]["output"]
        changed = True

    if "run_latch" in missing:
        # Recurso interno fijo (M_RunLatch, siempre autogenerado - ver
        # functional_requirements.FUNCTIONAL_REQUIREMENT_TAGS) - nunca ambiguo, nunca requiere
        # autorizacion fisica; completarlo no es adivinar informacion, es nombrar el unico recurso
        # que "run_latch" siempre significa en este proyecto.
        repaired_parameters["run_latch"] = "M_RunLatch"
        changed = True

    if "contactor_a" in missing and len(actor_records) >= 1 and actor_records[0]["output"]:
        repaired_parameters["contactor_a"] = actor_records[0]["output"]
        changed = True
    if "contactor_b" in missing and len(actor_records) >= 2 and actor_records[1]["output"]:
        repaired_parameters["contactor_b"] = actor_records[1]["output"]
        changed = True

    if not changed:
        return semantic_output

    repaired = dict(semantic_output)
    repaired["parameters"] = repaired_parameters
    return repaired


def strip_unavailable_emergency_reference(semantic_output: dict[str, Any], io_map: dict[str, Any]) -> dict[str, Any]:
    """
    A bench with no I_Emergency wired to the PLC (paro de emergencia externo) must never end up
    with I_Emergency auto-created, required, or referenced in generated code. Three independent
    consumers each need this handled, or the reference just reappears downstream of whichever one
    is missed:

    1. `semantic_validator.py`'s two-level validation would treat "I_Emergency" as a well-formed-
       but-unauthorized tag and auto-resolve it to a real FREE channel - claiming hardware nobody
       asked for. Removing it from `recognized_tags` prevents that.
    2. `ir_builder.py::get_required_variables_for_intent` builds its per-intent required list from
       `parameters.get("emergency_input", "I_Emergency")` - DELETING the `emergency_input` key
       would only re-trigger that same hardcoded default, reintroducing "I_Emergency" right back
       into `required_variables` (the actual bug this function exists to close). Every occurrence
       of the STRING "I_Emergency" as a parameter VALUE is instead replaced with the IEC boolean
       literal `"FALSE"` - a key present with value "FALSE" is what `.get(key, default)` returns,
       never the default, and "FALSE" does not start with any external/internal tag prefix, so it
       is silently excluded from both the required-variables and missing-variables checks.

       Section "regla definitiva" real bug found in production: when the LLM correctly followed
       the prompt instruction to OMIT `emergency_input` entirely (rather than including
       "I_Emergency" as a value) for a bench with no such tag, this function had nothing to
       substitute - `emergency_input` was simply ABSENT, and that same `.get("emergency_input",
       "I_Emergency")` default fired anyway, verbatim, in `get_required_variables_for_intent` AND
       in every one of `code_generator.py`'s ~20 templates (all of them use this exact key name,
       always with this exact default). An ABSENT `emergency_input` is just as dangerous as one
       literally set to "I_Emergency" - both trigger the same hardcoded fallback - so this function
       now ALSO fills `parameters["emergency_input"] = "FALSE"` whenever the key is missing, not
       only when it is present with the value "I_Emergency".
    3. `code_generator.py`'s ~20 codegen templates all read `emergency_input` this same way and
       splice it directly into boolean SCL expressions (`AND NOT {emergency_input}`,
       `IF {emergency_input} THEN ...`, `{fault_latch} OR {emergency_input}`) - substituting the
       literal `"FALSE"` keeps every one of those expressions valid, compilable SCL that never
       actually triggers on emergency (`AND NOT FALSE` is a no-op, `IF FALSE THEN` is dead code,
       `X OR FALSE` is `X`) - the correct behavior for "there is no PLC-readable emergency signal
       to test", without touching a single one of those templates individually.

    A fourth, independent source: a `functional_requirements` entry `{"type":
    "emergency_priority"}` always resolves to the FIXED tag list `["I_Emergency"]" via
    `functional_requirements.FUNCTIONAL_REQUIREMENT_TAGS` - unlike `emergency_input`, there is no
    parameter value to substitute "FALSE" into; the requirement itself ("this signal has priority
    override") is meaningless without a physical signal to test, so the entry is dropped entirely.
    Exception: when the command's own `intent_id` is `INT_EMERGENCY_PRIORITY` (the command is
    EXPLICITLY about emergency-stop behavior, not composing it as a side requirement), this is left
    untouched - genuinely asking for emergency logic on a bench with none wired is a real error to
    surface, not something to silently discard.

    This never touches `requested_io_assignments` (the EXPLICIT "usa X para emergencia" path, a
    separate field) - an explicit user request for an emergency channel is untouched, per the
    stated exception in the "regla definitiva" (I_Emergency may exist if the map already has it,
    or the user explicitly asked for it).
    """
    if any(str(variable.get("name")) == "I_Emergency" for variable in io_map.get("variables", [])):
        return semantic_output

    parameters = semantic_output.get("parameters")
    recognized_tags = semantic_output.get("recognized_tags")
    functional_requirements = semantic_output.get("functional_requirements")
    changed = False

    new_parameters = parameters
    if isinstance(parameters, dict):
        needs_value_substitution = any(value == "I_Emergency" for value in parameters.values())
        # "emergency_input" es SIEMPRE el mismo nombre de clave en cada uno de los ~19 entries de
        # get_required_variables_for_intent (parameter_overrides) y en cada template equivalente de
        # code_generator.py - todos caen en el mismo default hardcodeado "I_Emergency" cuando la
        # clave esta AUSENTE, exactamente igual que cuando esta presente con ese valor. Se rellena
        # siempre que la clave falte, sin condicionarlo a que existan otros parametros - agregarla a
        # un intent que nunca la lee es inofensivo (nunca se consulta esa clave), mientras que
        # omitir el relleno por un dict vacio dejaria pasar exactamente el mismo bug real que este
        # modulo existe para cerrar.
        needs_absent_fill = "emergency_input" not in parameters
        if needs_value_substitution or needs_absent_fill:
            new_parameters = {
                key: ("FALSE" if value == "I_Emergency" else value)
                for key, value in parameters.items()
            }
            if needs_absent_fill:
                new_parameters["emergency_input"] = "FALSE"
            changed = True

    new_recognized_tags = recognized_tags
    if isinstance(recognized_tags, list) and "I_Emergency" in recognized_tags:
        new_recognized_tags = [tag for tag in recognized_tags if tag != "I_Emergency"]
        changed = True

    new_functional_requirements = functional_requirements
    if (
        isinstance(functional_requirements, list)
        and semantic_output.get("intent_id") != "INT_EMERGENCY_PRIORITY"
        and any(req.get("type") == "emergency_priority" for req in functional_requirements if isinstance(req, dict))
    ):
        new_functional_requirements = [
            req for req in functional_requirements
            if not (isinstance(req, dict) and req.get("type") == "emergency_priority")
        ]
        changed = True

    if not changed:
        return semantic_output

    repaired = dict(semantic_output)
    repaired["parameters"] = new_parameters
    repaired["functional_requirements"] = new_functional_requirements
    repaired["recognized_tags"] = new_recognized_tags
    return repaired


__all__ = ["repair_semantic_output", "strip_unavailable_emergency_reference"]
