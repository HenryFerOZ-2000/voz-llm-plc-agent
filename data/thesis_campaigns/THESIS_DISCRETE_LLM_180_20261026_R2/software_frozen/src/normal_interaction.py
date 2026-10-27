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
   Normaliza el lenguaje por su significado, no por frases: pulsar/presionar/oprimir/activar el
   pulsador de marcha/arranque/inicio = flanco de la entrada de arranque; encender/activar/energizar/
   abrir = salida en TRUE; apagar/desactivar/detener/cerrar/retirar = salida en FALSE.

2. Elige el comportamiento por lo que pide el comando, antes de elegir una intencion o dispositivos:
   - Llenar/vaciar HASTA un limite y detener: conmutacion por umbral o secuencia finita. NO es PID,
     NO es supervision PID y NO es una consigna que deba mantenerse. Conserva el actuador pedido.
     Usa timed_sequence con advance_on y repeat="once", o enclavamiento con parada por el sensor.
     Si falta como iniciar/reiniciar, pregunta ese dato; no inventes un controlador continuo.
   - Encender bajo un limite y apagar al alcanzar otro: hysteresis_switch, con memoria entre limites.
     Una entrada analogica NO implica PID. Usa su unidad de ingenieria y el sensor del mapa.
   - Crear/mantener regulacion continua mediante PID: pid_control. No basta set_level_setpoint,
     enable_pid ni una bandera interna: el programa debe crear y conectar el controlador nativo.
   - INT_PID_SUPERVISOR se reserva a supervision de un PID existente solicitado expresamente;
     nunca lo uses como sustituto de un llenado simple ni de crear un nuevo lazo PID.
   requested_control_behavior expresa restricciones detectadas del comando original: THRESHOLD,
   HYSTERESIS, CONTINUOUS o SUPERVISION. UNSPECIFIED no autoriza inventar el comportamiento faltante.
   Un reintento debe corregir la representacion del MISMO comportamiento, no cambiar el tipo de control,
   sustituir dispositivos, agregar alarmas no solicitadas ni evitar errores de configuracion del mapa.
   No uses Level_PV como lectura interna nueva sin conexion al sensor; las condiciones deben leer la
   medicion real declarada y escalada. La disponibilidad de un actuador proporcional no convierte una
   operacion por limite en PID ni autoriza usarlo en lugar de otro dispositivo solicitado.

   Para un control PID NATIVO solicitado, usa functional_requirements con un solo requisito:
   {"type":"pid_control", "loop_id":"Loop1", "setpoint":50, "unit":"%", "direction":"FILL",
    "process_input":"AI_...", "control_output":"AO_...",
    "resources":{"start":"I_...", "stop":"I_...", "reset":"I_...", "emergency":"I_..."}}.
   process_input/control_output se toman del mapa; pueden omitirse si hay un dispositivo compatible único.
   direction es FILL o DRAIN según la acción del actuador. No hay un modo de entorno PID: usa las señales
   hardware o DB declaradas en el mapa, independientemente del destino. No preguntes por simulación/planta
   ni confirmes calibraciones; la validación del mapa y la descarga comprueban esos datos. resources solo incluye funciones pedidas/disponibles;
   nunca agregues una salida digital de habilitación ni alarma si no se necesita. Sin pulsadores vinculados
   el control tiene mandos internos de operador. Conserva la unidad del setpoint, sin convertirlo a raw.
   Puedes incluir overfill_limit en la misma unidad del requisito/setpoint si el comando lo pide. No combines todavía
   pid_control con primitivas separadas: sus pulsadores, alarma/permisos y parada pertenecen al requisito.
   INT_PID_SUPERVISOR y sus requisitos existentes siguen sirviendo para supervisión de un PID ya instalado;
   no representan la creación de un lazo nativo. No sustituyas un PID por una salida analógica fija.

   Primitivas componibles (ademas del catalogo de functional_requirements). Una misma primitiva sirve
   para cualquier maquina: no existen primitivas por dominio.
   - "timed_sequence": secuencia GENERICA de N etapas excluyentes (2, 3 o mas):
       {"type": "timed_sequence",
        "start_input": "I_...",            (disparo por pulsador/sensor; opcional, ver abajo)
        "stop_input": "I_...",             (opcional; Stop/emergencia siempre llevan a reposo)
        "mode_condition": "M_AutoMode",    (opcional: la secuencia corre MIENTRAS se cumple)
        "repeat": "once" | "continuous" | "hold_last",
        "steps": [{"outputs": ["Q_A", "Q_B"], "duration": "T#10s"},
                  {"outputs": ["Q_C"], "advance_on": "I_Sensor"},
                  {"outputs": ["Q_D"], "duration": "T#15s", "advance_on": "I_Level_High",
                   "timeout_alarm_output": "Q_Alarm"}]}
     * start_input y stop_input contienen UNA senal, nunca expresiones AND/OR. Para varias causas
       de parada usa force_off con condition compuesta y las salidas afectadas; no combines tags en stop_input.
     * Cada etapa enumera TODAS las salidas ACTIVAS durante ella (varias a la vez si corresponde); las
       no listadas quedan apagadas. Una etapa sin salidas y con duracion es una pausa.
     * Para salidas analógicas usa dentro de la etapa:
       "analog_outputs": [{"output": "AO_...", "value": 100, "unit": "%"}].
       "outputs" contiene solo BOOL. La orden numérica queda ligada al estado de ESA etapa;
       no inventes una memoria de secuencia activa ni dupliques la orden en analog_output.
       "condition_unit" junto a advance_on indica la unidad del umbral del sensor.
       Al finalizar o cancelar se aplica el valor seguro configurado en el mapa.
     * Fin de etapa: "duration" (IEC TIME) y/o "advance_on" (condicion). Con ambas avanza con lo que
       ocurra primero; si ademas lleva "timeout_alarm_output", vencer el tiempo antes de la condicion
       termina la secuencia en falla y enclava esa alarma (rama "si en X s no ocurre Y").
     * repeat: "once" = una sola ejecucion; al terminar la ultima etapa TODO queda apagado y espera un
       nuevo disparo. "continuous" = tras la ultima etapa vuelve a la etapa 1 (ciclo). "hold_last" = la
       ultima etapa queda activa hasta Stop. Un comando que dice cuanto dura la ultima etapa y no pide
       repetir es "once": NO agregues una etapa vacia para decir "todo apagado".
     * Disparo: start_input si el comando lo nombra. Un ciclo "continuous" sin disparador arranca solo;
       con mode_condition arranca y se detiene con esa condicion.
   - "never_together": invariante de seguridad {"type": "never_together", "outputs": ["Q_a", "Q_b"]}:
     esas salidas nunca pueden estar activas simultaneamente.
   - "conditional_output": {"condition": "I_A AND I_B", "outputs": ["Q_..."], "duration": "T#4s"}:
     sin duration la salida sigue a la condicion (activa mientras se cumple); con duration es un pulso
     de ese tiempo cada vez que la condicion empieza a cumplirse.
   - "hysteresis_switch": {"input": "AI_...", "output": "Q_...", "on_above": 80, "off_below": 70}
     Para salida analógica conserva además on_value, off_value y output_unit (órdenes numéricas explícitas).
     La unidad de los umbrales va en unit; la de apertura en output_unit. Conserva enable_condition cuando exista habilitación.
     Si Start habilita y Stop/emergencia deshabilitan, representa esa memoria con latch y úsala en enable_condition.
     (o "on_below"/"off_above"): encender al cruzar un umbral y apagar solo al cruzar el otro. Usala
     siempre que el comando de dos umbrales distintos para encender y apagar; nunca una comparacion simple.
     Si el comando indica unidades, incluye "unit" (p. ej. "cm"). Con analog_config confirmada los umbrales
     usan unidades físicas, no cuentas raw. Sin unidad explícita se usa engineering_unit del canal.
   - "analog_output": {"output": "AO_...", "value": 50, "unit": "%", "condition": "I_..."}:
     orden numérica a una salida analógica configurada; condition es opcional. Deshabilitada o con emergencia,
     aplica el valor ante fallo del mapa. Nunca uses TRUE/FALSE para un actuador analógico.
     No inventes calibraciones: analog_config debe estar completa y confirmada en el mapa. Si se solicita PID,
     esta orden fija NO lo reemplaza: utiliza el requisito pid_control descrito arriba.
   - "force_off": {"condition": "I_...", "outputs": ["Q_..."]}: la condicion apaga esas salidas de
     inmediato (prioridad sobre todo, aunque un temporizador no haya terminado) y detiene la secuencia
     que las maneja.
   - "pulse_counter": {"name": "Pieces", "count_input": "I_...", "preset": 10, "reset": "I_Reset",
       "outputs": ["Q_..."]}: contador ascendente (CTU) dentro de un programa compuesto; cuenta flancos de
     count_input (o de "count_condition") y al llegar a preset activa outputs. Expone M_<name>_Done (alcanzado)
     y M_<name>_CV (valor actual), utilizables en condiciones (p. ej. advance_on: "M_Pieces_Done"); reset es una
     condicion (p. ej. "I_Reset" o "NOT M_Seq1_S1" para reiniciar al salir de la etapa 1 de la secuencia 1).
   - "latch": {"set": "I_Fault", "reset": "I_Reset", "outputs": ["Q_..."]}: enclavamiento generico; la
     salida se activa con set y queda activa hasta reset (reset prioritario).
   - "automatic_mode" {"mode_input": "I_..."} y "manual_mode" {"mode_input": "I_...", "commands": [
       {"input": "I_...", "output": "Q_...", "behavior": "maintained"|"latched", "enable_condition": "Q_..."}]}:
     modos excluyentes; cada orden manual maneja UNA salida (maintained = solo mientras la orden esta
     presente; latched = enclavada hasta Stop). enable_condition es un permisivo opcional.
     En timed_sequence, "mode_condition": "M_AutoMode" limita la secuencia al modo Automatico.
   - "sensor_timeout_alarm" {"sensor_input": "I_...", "timeout": "T#...", "start_condition": "I_... AND M_...",
       "affected_outputs": ["Q_..."], "alarm_output": "Q_..."}: si el sensor no cambia de estado dentro del
     tiempo tras el arranque, detiene esas salidas y enclava la alarma; requiere "reset_behavior"
     {"reset_input": "I_..."} para reiniciarla.
   Un parametro de recurso de una intencion (trigger_input, output, ...) lleva UNA sola senal: si el disparo
   combina varias senales o comparaciones usa conditional_output/timed_sequence en vez de esa intencion.
   Las condiciones (mode_condition, enable_condition, start_condition, condition, advance_on) son tags con
   AND/OR/NOT/parentesis y comparaciones tag-numero (AI_Temp > 80).
   Con canales analógicos, conserva la unidad solicitada en "condition_unit" junto a la condición
   (p. ej. condition="AI_Level > 1.5", condition_unit="m"); el software convierte el umbral al rango del mapa.
   En analog_output, "unit" corresponde a la orden de salida y "condition_unit" al umbral de su condición.
   Si el comando no indica unidad, la comparación utiliza engineering_unit del mapa; no conviertas a raw.
   Para comportamientos simples ya
   cubiertos por una intencion del catalogo (marcha/paro, temporizador, contador, alarma con reset...)
   usa esa intencion.
   Infiere de la descripcion funcional las salidas que el comportamiento necesita: no preguntes por ellas.
   Propon nombres funcionales claros (Q_..., I_..., AI_...) o reutiliza los existentes del mapa; NUNCA
   indiques ni preguntes direcciones fisicas o canales: el IOAllocator los asigna, y si faltan canales
   es una falta de hardware que el sistema informa, no una pregunta para el usuario.
   TODO recurso (entrada o salida) de una primitiva lleva su nombre funcional como texto ("I_...",
   "Q_..."): nunca lo dejes vacio ni lo describas solo con un rol.

3. Completo vs ambiguo vs contradictorio (un comando largo NO es por eso ambiguo):
   a) COMPLETO: indica que lo inicia (o que es un ciclo continuo), que actuadores intervienen, en que
      orden, los tiempos/condiciones necesarios y que ocurre al terminar -> requires_clarification=false.
      Un ciclo que debe repetirse continuamente y no nombra disparador ES COMPLETO: usa repeat="continuous"
      sin start_input; el sistema lo arranca solo y registra esa inferencia. No preguntes como arranca.
      Si no dice que ocurre al terminar y no pide repetir, el estado final es TODO APAGADO (repeat="once").
   b) PARCIALMENTE INFERIBLE con una convencion segura e inequivoca (p. ej. "A 10 segundos,
      B 3 y C 10": el 3 esta en segundos por el contexto; "cada 10 s" = cada etapa dura 10 s)
      -> generalo y registra CADA inferencia en "assumptions" con el prefijo "INFERRED: ...".
   c) AMBIGUO: falta un dato funcional indispensable con varias interpretaciones razonables (tiempos,
      orden o disparo no dichos) -> pregunta SOLO ese dato, UNA pregunta por vez, en lenguaje del proceso.
   d) CONTRADICTORIO (p. ej. activar a la vez dos salidas que tambien deben ser excluyentes) -> no
      adivines: requires_clarification=true y la pregunta explica la contradiccion.
   Si "clarification_history" trae respuestas, incorporalas al comando original y NO vuelvas a
   preguntar lo ya respondido. Si para producir el programa tendrias que asumir un dato de seguridad no
   indicado (p. ej. un tiempo muerto entre etapas), no lo inventes: omitelo si no es indispensable, o
   pregunta por el.
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


def answered_question_note(question: str | None, history: list[dict[str, str]]) -> str:
    """Nota de correccion para reinterpretar integrando la respuesta que ya dio el usuario."""
    target = normalize_question(question)
    answers = [item for item in history if normalize_question(item.get("question")) and (
        normalize_question(item.get("question")) in target or target in normalize_question(item.get("question")))]
    pairs = "; ".join(f"pregunta: {item.get('question')} -> respuesta del usuario: {item.get('answer')}" for item in answers or history)
    return ("La interpretacion anterior volvio a preguntar algo que el usuario YA respondio (" + pairs + "). "
            "Integra esa respuesta en functional_requirements/parameters del comando original y genera el programa; "
            "no repitas la pregunta. Solo si sigue faltando OTRO dato indispensable, pregunta por ese otro dato.")


def invalid_interpretation_note(errors: list[str]) -> str:
    """Nota de correccion para UNA reinterpretacion de un resultado no generable (errores exactos del validador)."""
    return ("La interpretacion anterior no se puede generar por estos errores de validacion: " + "; ".join(errors[:6])
            + ". Corrige la representacion del MISMO comando: cada parametro de recurso lleva una sola senal; las "
            "condiciones combinadas, comparaciones, secuencias y enclavamientos se expresan con las primitivas "
            "componibles de la politica. No cambies el comportamiento pedido.")


def trace(event: str, **fields: Any) -> str:
    """Linea de log de Modo Normal: '[NORMAL_<EVENTO>] clave=valor; ...' (eventos en NORMAL_LOG_EVENTS)."""
    details = "; ".join(f"{key}={value}" for key, value in fields.items() if value not in (None, "", [], {}))
    return f"[{event}] {details}".rstrip()


NORMAL_LOG_EVENTS = (
    "NORMAL_SEMANTIC_PARSE", "NORMAL_INFERENCES", "NORMAL_CLARIFICATION_REQUIRED", "NORMAL_CLARIFICATION_RESOLVED",
    "NORMAL_CLARIFICATION_REPEATED", "NORMAL_RESOURCE_REQUIREMENTS", "NORMAL_RESOURCE_BINDING", "NORMAL_MAP_CONFIG_EXPLICIT", "NORMAL_IO_PROVISIONAL",
    "NORMAL_IO_COMMIT", "NORMAL_IO_ROLLBACK", "NORMAL_GENERATION", "NORMAL_INTERNAL_RESOURCES", "NORMAL_IR_BUILT",
    "NORMAL_CAPABILITY_GAP", "NORMAL_DOWNLOAD", "NORMAL_PROGRAM_SCOPE", "NORMAL_PROGRAM_COMMIT",
)

# Clasificacion de la operacion sobre el mapa (Modo Normal). Un rol funcional (bomba, valvula, tanque, sensor...)
# con un nombre nuevo es un REQUISITO de recurso del programa, nunca una configuracion del mapa: solo una
# asignacion con DIRECCION dicha por el usuario ("usa %QX8.1 para ...") es configuracion explicita.
MAP_OPERATION_CONFIG = "MAP_CONFIG_EXPLICIT"
MAP_OPERATION_PROGRAM = "PROGRAM"
ROLLBACK_MESSAGE = "No se aplicaron cambios al mapa debido a un error en la generación del programa."


# Campos de la semantica que contienen REFERENCIAS a recursos (nunca el texto libre del usuario).
_BINDABLE_FIELDS = ("parameters", "functional_requirements", "recognized_tags", "effective_semantics", "parameter_provenance")


def apply_resource_bindings(semantic_output: dict[str, Any], bindings: dict[str, str]) -> dict[str, Any]:
    """
    Sustituye cada nombre pedido por el simbolo RESUELTO por el IOAllocator ({"Q_Motor_Enable": "Q_Motor"}) en
    parametros, requisitos (incluidas condiciones "I_A AND Q_x"), tags reconocidos y semantica efectiva, para que
    validacion, IR, SCL y verificacion usen exactamente el mismo recurso. El texto del usuario no se toca.
    """
    if not bindings:
        return semantic_output
    pattern = re.compile(r"\b(" + "|".join(re.escape(name) for name in sorted(bindings, key=len, reverse=True)) + r")\b")

    def rebind(value: Any) -> Any:
        if isinstance(value, str):
            return pattern.sub(lambda match: bindings[match.group(1)], value)
        if isinstance(value, list):
            return [rebind(item) for item in value]
        if isinstance(value, dict):
            return {rebind(key) if isinstance(key, str) else key: rebind(item) for key, item in value.items()}
        return value

    rebound = dict(semantic_output)
    for field in _BINDABLE_FIELDS:
        if field in rebound:
            rebound[field] = rebind(rebound[field])
    rebound["resource_bindings"] = {**(semantic_output.get("resource_bindings") or {}), **bindings}
    return rebound


def classify_map_operation(semantic_output: dict[str, Any]) -> dict[str, Any]:
    """
    MAP_CONFIG_EXPLICIT: solo asignaciones con direccion explicita, sin logica ni aclaracion pendiente (se aplican
    al confirmarse). PROGRAM: todo lo demas, incluido el comando mixto; sus recursos (implicitos y explicitos) se
    asignan de forma PROVISIONAL y solo se confirman con el programa generado y verificado.
    """
    validation = semantic_output.get("semantic_validation") or {}
    proposals = [p for p in validation.get("io_assignment_proposals") or [] if isinstance(p, dict)]
    # address_was_explicit lo fija el IOAllocator; sin ese dato se usa la clasificacion del parser (operation_type).
    config_command = semantic_output.get("operation_type") == "MAP_CONFIG"
    explicit = [p for p in proposals if p.get("address_was_explicit", config_command)]
    explicit_names = {p.get("proposed_name") for p in explicit}
    # Una mencion implicita del MISMO nombre que el usuario ya asigno por direccion no es otro recurso.
    implicit = [p for p in proposals if not p.get("address_was_explicit", config_command)
                and p.get("proposed_name") not in explicit_names]
    has_logic = bool(semantic_output.get("functional_requirements")) or \
        semantic_output.get("intent_id") not in (None, "", "INT_UNKNOWN")
    clarification = bool(semantic_output.get("requires_clarification") or validation.get("requires_clarification"))
    kind = MAP_OPERATION_CONFIG if explicit and not implicit and not has_logic and not clarification else MAP_OPERATION_PROGRAM
    return {"kind": kind, "explicit": explicit, "implicit": implicit, "has_logic": has_logic}


def resource_requirement_fields(semantic_output: dict[str, Any]) -> dict[str, str]:
    """Para NORMAL_RESOURCE_REQUIREMENTS: recursos que ya existen, los que hay que asignar y los sin canal."""
    validation = semantic_output.get("semantic_validation") or {}
    proposals = validation.get("io_assignment_proposals") or []
    needed = [p for p in proposals if not p.get("blocked")]
    return {"to_allocate": ", ".join(f"{p.get('proposed_name')}->{p.get('address')}" for p in needed),
            "blocked": ", ".join(str(p.get("proposed_name")) for p in proposals if p.get("blocked")),
            "recognized": ", ".join(str(tag) for tag in semantic_output.get("recognized_tags") or [])}


def capability_gap_message(gap: dict[str, Any]) -> str:
    """Mensaje de producto para una falta de HARDWARE (nunca una pregunta sobre canales)."""
    return (f"{SYSTEM_CAPABILITY_GAP}: {gap.get('message')}\n\n"
            "Libere canales compatibles en el mapa PLC (estado FREE) o seleccione otro mapa, y repita el comando.")


def semantic_trace_fields(semantic_output: dict[str, Any]) -> dict[str, Any]:
    """Resumen de la semantica para NORMAL_SEMANTIC_PARSE (tipos de requisito, aclaracion, validez)."""
    validation = semantic_output.get("semantic_validation") or {}
    return {"intent": semantic_output.get("intent_id"),
            "requirements": ",".join(str(r.get("type")) for r in semantic_output.get("functional_requirements") or []
                                     if isinstance(r, dict)),
            "valid": validation.get("is_valid"),
            "clarification": validation.get("requires_clarification") or semantic_output.get("requires_clarification")}


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
