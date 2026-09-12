"""BARS tool contracts (constitution section 3).

Chat tool dispatch moves from [TAG:] regex markers to provider-native
function calling. This registry is the single seam that owns what the model
may see (DeepSeek Harness ToolDefinition pattern):

- the model-facing schema list is built by explicit allowlist: host-only
  metadata (marker, side_effect, followups) can never leak into a request
- every tool declares a MANDATORY output schema that is enforced on results
- write-class tools declare required follow-ups (read-back before done);
  proposals stay proposals: confirmations are untouched and remain the only
  path from proposal to execution
"""

# Host-only fields (marker, side_effect, followups, output) are stripped by
# model_schemas(); only name/description/parameters ever reach a provider.
TOOLS = {
    "deploy_mission": {
        "description": ("Deploy a squad member on a background mission with full "
                        "web/file access. Use when the request needs live data, real "
                        "research, prospecting, auditing, or actual work product. "
                        "Proposes the mission only - the Commander approves it."),
        "parameters": {"type": "object", "properties": {
            "brief": {"type": "string", "description":
                      "Self-contained mission brief, third person, keeping every "
                      "specific the user gave - numbers, cities, criteria."},
            "agent": {"type": "string", "enum": ["CASE", "KIPP", "PLEX", "N1X"],
                      "description": "Squad member to send."}},
            "required": ["brief"]},
        "output": {"type": "object", "required": ["proposed", "brief"], "properties": {
            "proposed": {"type": "boolean"}, "brief": {"type": "string"},
            "agent": {"type": ["string", "null"]}}},
        "marker": "DEPLOY",
        "side_effect": "proposal",
        "followups": ["mission.exec confirmation", "read-back of the mission row"],
    },
    "propose_action": {
        "description": ("Queue a single OUTWARD action (send, post, email, publish, "
                        "schedule, message) for the Commander's explicit confirmation. "
                        "Never executes."),
        "parameters": {"type": "object", "properties": {
            "instruction": {"type": "string", "description":
                            "Exact single action instruction with all specifics."}},
            "required": ["instruction"]},
        "output": {"type": "object", "required": ["id", "desc"], "properties": {
            "id": {"type": "string"}, "desc": {"type": "string"}}},
        "marker": "ACT",
        "side_effect": "proposal",
        "followups": ["act.exec confirmation", "read-back of the action result"],
    },
    "request_takeover": {
        "description": ("Ask permission to drive the Commander's real screen, mouse "
                        "and keyboard for a concrete task. Runs only after he confirms."),
        "parameters": {"type": "object", "properties": {
            "task": {"type": "string", "description":
                     "The task in plain words, e.g. 'fill out the signup form on this "
                     "page with his email'."}},
            "required": ["task"]},
        "output": {"type": "object", "required": ["confirm_id", "task"], "properties": {
            "confirm_id": {"type": "string"}, "task": {"type": "string"},
            "danger": {"type": "boolean"}}},
        "marker": "TAKEOVER",
        "side_effect": "proposal",
        "followups": ["human confirmation", "read-back of the final screen state"],
    },
    "manage_tool": {
        "description": ("Propose adding/installing/connecting or removing a tool or "
                        "integration. The actual change needs the Commander's separate "
                        "tools.write confirmation."),
        "parameters": {"type": "object", "properties": {
            "op": {"type": "string", "enum": ["add", "remove"]},
            "id": {"type": "string", "description": "Catalog id, e.g. notion, gmail, slack."}},
            "required": ["op", "id"]},
        "output": {"type": "object", "required": ["proposed", "op", "id"], "properties": {
            "proposed": {"type": "boolean"}, "op": {"type": "string"},
            "id": {"type": "string"}, "auth": {"type": "string"}}},
        "marker": "TOOL",
        "side_effect": "proposal",
        "followups": ["tools.write confirmation", "read-back of installed tools"],
    },
}


def model_schemas():
    """Provider-native tools array, built by allowlist. Host internals
    (output, marker, side_effect, followups) are never included."""
    return [{"type": "function", "function": {
        "name": name,
        "description": spec["description"],
        "parameters": spec["parameters"],
    }} for name, spec in TOOLS.items()]


def _check(value, schema, path, errs):
    t = schema.get("type")
    if t:
        types = t if isinstance(t, list) else [t]
        ok = False
        for tt in types:
            ok |= (tt == "string" and isinstance(value, str)
                   or tt == "boolean" and isinstance(value, bool)
                   or tt == "number" and isinstance(value, (int, float))
                   or tt == "object" and isinstance(value, dict)
                   or tt == "array" and isinstance(value, list)
                   or tt == "null" and value is None)
        if not ok:
            errs.append(f"{path}: expected {t}, got {type(value).__name__}")
            return
    if isinstance(value, dict):
        for req in schema.get("required", []):
            if req not in value:
                errs.append(f"{path}.{req}: missing required field")
        props = schema.get("properties", {})
        for k, v in value.items():
            if k in props:
                _check(v, props[k], f"{path}.{k}", errs)
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            _check(item, schema["items"], f"{path}[{i}]", errs)


def validate_args(name, arguments):
    """Validate + allowlist model-supplied call arguments. Returns a clean
    args dict, or None when the call is malformed (caller falls back)."""
    spec = TOOLS.get(name)
    if spec is None:
        return None
    if isinstance(arguments, str):
        import json
        try:
            arguments = json.loads(arguments)
        except ValueError:
            return None
    if not isinstance(arguments, dict):
        return None
    props = spec["parameters"].get("properties", {})
    args = {k: v for k, v in arguments.items() if k in props}
    errs = []
    _check(args, spec["parameters"], name, errs)
    if errs:
        return None
    for k, v in args.items():
        if isinstance(v, str):
            args[k] = v[:4000]
    return args


def validate_result(name, result):
    """Enforce the tool's mandatory output schema on the result the host is
    about to ship. Returns (ok, errors)."""
    spec = TOOLS.get(name)
    if spec is None:
        return False, [f"unknown tool: {name}"]
    errs = []
    _check(result, spec["output"], f"{name}.result", errs)
    return not errs, errs
